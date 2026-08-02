#!/usr/bin/env python3
"""Evaluate frozen affinity schedules under LFRU and frozen static pins."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moe_controller.events import load_event_trace, sha256_file
from moe_controller.simulation import simulate_event_atomic, simulate_static_fixed


SCHEDULERS = ("fcfs_deadline", "causal_prev_route", "oracle_current_route")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("discovery", "confirmatory"), required=True)
    parser.add_argument("--fcfs", type=Path, required=True)
    parser.add_argument("--causal", type=Path, required=True)
    parser.add_argument("--oracle", type=Path, required=True)
    parser.add_argument("--static-pins", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    pin_payload = json.loads(args.static_pins.read_text(encoding="utf-8"))
    if pin_payload["status"] != "frozen_from_discovery_only":
        raise ValueError("Static pins are not marked discovery-frozen")
    resident = pin_payload["resident_blocks"]
    roots = {
        "fcfs_deadline": args.fcfs,
        "causal_prev_route": args.causal,
        "oracle_current_route": args.oracle,
    }
    rows: list[dict] = []
    logical_reference: int | None = None
    for scheduler in SCHEDULERS:
        root = roots[scheduler]
        trace = load_event_trace(root)
        observed_scheduler = trace.manifest["conversion"]["scheduler"]
        if observed_scheduler != scheduler:
            raise ValueError(f"Scheduler mismatch: {observed_scheduler} != {scheduler}")
        logical = int(trace.manifest["counts"]["logical_expert_assignments_before_dedup"])
        if logical_reference is None:
            logical_reference = logical
        elif logical != logical_reference:
            raise ValueError("Schedulers do not contain identical logical work")
        union = int(trace.manifest["counts"]["union_expert_accesses"])
        results = {
            "lfru": simulate_event_atomic(
                trace,
                policy="lfru",
                capacity_blocks=pin_payload["capacity_blocks"],
                cache_scope="per_layer",
                tie_seed=20260729,
            ),
            "static_fixed": simulate_static_fixed(trace, resident_blocks=resident),
        }
        metrics = trace.manifest["scheduler_metrics"]
        for residency, result in results.items():
            rows.append(
                {
                    "split": args.split,
                    "scheduler": scheduler,
                    "residency": residency,
                    "logical_blocks": logical,
                    "union_blocks": union,
                    "union_fraction": union / logical,
                    "transferred_blocks": result.transferred_blocks,
                    "effective_miss_fraction": result.transferred_blocks / logical,
                    "step_miss_p99": result.step_miss_p99,
                    "max_step_misses": result.max_step_misses,
                    "max_service_interval": metrics["max_service_interval"],
                    "p99_service_interval": metrics["p99_service_interval"],
                    "admission_wait_p99": metrics["admission_wait_p99"],
                    "admission_wait_max": metrics["admission_wait_max"],
                    "starved_requests": metrics["starved_requests"],
                }
            )

    indexed = {(row["scheduler"], row["residency"]): row for row in rows}
    verdicts: dict[str, dict] = {}
    for residency in ("lfru", "static_fixed"):
        fcfs = indexed[("fcfs_deadline", residency)]
        causal = indexed[("causal_prev_route", residency)]
        oracle = indexed[("oracle_current_route", residency)]
        causal_improvement = (
            fcfs["transferred_blocks"] - causal["transferred_blocks"]
        ) / fcfs["transferred_blocks"]
        oracle_headroom = (
            fcfs["transferred_blocks"] - oracle["transferred_blocks"]
        ) / fcfs["transferred_blocks"]
        recovered = (
            causal_improvement / oracle_headroom if oracle_headroom > 0 else 0.0
        )
        p99_change = (
            causal["step_miss_p99"] - fcfs["step_miss_p99"]
        ) / fcfs["step_miss_p99"]
        verdicts[residency] = {
            "causal_transfer_improvement": causal_improvement,
            "oracle_transfer_headroom": oracle_headroom,
            "causal_share_of_oracle_headroom": recovered,
            "causal_p99_change": p99_change,
        }

    constraints_ok = all(
        indexed[("causal_prev_route", residency)]["max_service_interval"] <= 4
        and indexed[("causal_prev_route", residency)]["starved_requests"] == 0
        and verdicts[residency]["causal_p99_change"] <= 0.10
        for residency in ("lfru", "static_fixed")
    )
    improvements = [
        verdicts[residency]["causal_transfer_improvement"]
        for residency in ("lfru", "static_fixed")
    ]
    frozen_pass = max(improvements) >= 0.10 and min(improvements) >= -0.02 and constraints_ok
    verdict = (
        "go_affinity_runtime_controller"
        if frozen_pass
        else "stop_local_dynamic_affinity"
    )

    args.output.mkdir(parents=True)
    csv_path = args.output / "schedule-policy-results.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "split": args.split,
        "static_pins_sha256": sha256_file(args.static_pins),
        "event_inputs": {
            scheduler: {
                "root": str(root.resolve()),
                "manifest_sha256": sha256_file(root / "manifest.json"),
            }
            for scheduler, root in roots.items()
        },
        "verdict_by_residency": verdicts,
        "constraints_ok": constraints_ok,
        "frozen_threshold_pass": frozen_pass,
        "verdict": verdict,
        "artifact": {
            "path": csv_path.name,
            "sha256": sha256_file(csv_path),
            "rows": len(rows),
        },
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
