#!/usr/bin/env python3
"""Audit one frozen static pin list across standard continuous batch sizes."""
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", type=Path, nargs="+")
    parser.add_argument("--static-pins", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    pins_payload = json.loads(args.static_pins.read_text(encoding="utf-8"))
    pins = pins_payload["resident_blocks"]
    rows: list[dict] = []
    inputs: list[dict] = []
    for root in args.events:
        trace = load_event_trace(root)
        logical = int(trace.manifest["counts"]["logical_expert_assignments_before_dedup"])
        forwards = int(trace.manifest["counts"]["decode_forwards"])
        steps = int(trace.manifest["counts"]["scheduler_steps"])
        batch_size = int(trace.manifest["conversion"]["batch_size"])
        results = {
            "static_fixed": simulate_static_fixed(trace, resident_blocks=pins),
            "lfru": simulate_event_atomic(
                trace,
                policy="lfru",
                capacity_blocks=pins_payload["capacity_blocks"],
                cache_scope="per_layer",
                tie_seed=20260729,
            ),
            "belady": simulate_event_atomic(
                trace,
                policy="belady",
                capacity_blocks=pins_payload["capacity_blocks"],
                cache_scope="per_layer",
                tie_seed=20260729,
            ),
        }
        lfru_blocks = results["lfru"].transferred_blocks
        for policy, result in results.items():
            rows.append(
                {
                    "batch_size": batch_size,
                    "average_batch": forwards / steps,
                    "policy": policy,
                    "transferred_blocks": result.transferred_blocks,
                    "effective_miss_fraction": result.transferred_blocks / logical,
                    "relative_to_lfru": (
                        (lfru_blocks - result.transferred_blocks) / lfru_blocks
                    ),
                    "step_miss_p99": result.step_miss_p99,
                }
            )
        inputs.append(
            {
                "root": str(root.resolve()),
                "manifest_sha256": sha256_file(root / "manifest.json"),
            }
        )
    rows.sort(key=lambda row: (row["batch_size"], row["policy"]))
    args.output.mkdir(parents=True)
    csv_path = args.output / "static-pin-concurrency.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "posthoc_scope_audit",
        "static_pins_sha256": sha256_file(args.static_pins),
        "inputs": inputs,
        "artifact": {
            "path": csv_path.name,
            "sha256": sha256_file(csv_path),
            "rows": len(rows),
        },
        "warning": "scope audit, not a new confirmatory hypothesis test",
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
