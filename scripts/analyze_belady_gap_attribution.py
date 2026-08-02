#!/usr/bin/env python3
"""Decompose causal-to-Belady gap into admission and victim knowledge."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moe_controller.events import load_event_trace, sha256_file
from moe_controller.simulation import simulate_event_atomic


CAPACITIES = (288, 1872, 2064, 2448, 2458)
PRIMARY_CAPACITY = 2458
POLICIES = ("lfru", "belady_forced_admit", "belady")


def analyze(label: str, root: Path, capacities: tuple[int, ...]) -> list[dict]:
    trace = load_event_trace(root)
    logical = int(trace.manifest["counts"]["logical_expert_assignments_before_dedup"])
    rows: list[dict] = []
    for capacity in capacities:
        results = {
            policy: simulate_event_atomic(
                trace,
                policy=policy,
                capacity_blocks=capacity,
                cache_scope="per_layer",
                tie_seed=20260729,
            )
            for policy in POLICIES
        }
        causal = results["lfru"].transferred_blocks
        forced = results["belady_forced_admit"].transferred_blocks
        bypass = results["belady"].transferred_blocks
        if not bypass <= forced:
            raise RuntimeError("Constrained Belady beat the unconstrained oracle.")
        total_gap = causal - bypass
        admission = forced - bypass
        future_victim = causal - forced
        if admission + future_victim != total_gap:
            raise RuntimeError("Gap decomposition does not close arithmetically.")
        rows.append(
            {
                "split": label,
                "event_root": root.name,
                "capacity_blocks": capacity,
                "capacity_fraction": capacity / trace.num_expert_blocks,
                "slots_per_layer_base": capacity // trace.num_layers,
                "slots_remainder": capacity % trace.num_layers,
                "logical_blocks": logical,
                "lfru_transferred_blocks": causal,
                "forced_admit_belady_transferred_blocks": forced,
                "bypass_belady_transferred_blocks": bypass,
                "lfru_miss_fraction": causal / logical,
                "forced_admit_belady_miss_fraction": forced / logical,
                "bypass_belady_miss_fraction": bypass / logical,
                "total_gap_blocks": total_gap,
                "total_gap_fraction_of_lfru": total_gap / causal,
                "admission_contribution_blocks": admission,
                "future_victim_contribution_blocks": future_victim,
                "admission_share_of_total_gap": (
                    admission / total_gap if total_gap else 0.0
                ),
                "future_victim_share_of_total_gap": (
                    future_victim / total_gap if total_gap else 0.0
                ),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--heldout", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--capacities",
        type=int,
        nargs="+",
        default=list(CAPACITIES),
        help="Total cache capacities to evaluate (default: the full diagnostic sweep).",
    )
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Output exists: {args.output}")

    capacities = tuple(dict.fromkeys(args.capacities))
    if PRIMARY_CAPACITY not in capacities:
        raise ValueError(
            f"Primary capacity {PRIMARY_CAPACITY} must be included for the frozen verdict."
        )
    rows = analyze("discovery_matched", args.discovery, capacities) + analyze(
        "confirmatory_heldout", args.heldout, capacities
    )
    discovery = next(
        row
        for row in rows
        if row["split"] == "discovery_matched"
        and row["capacity_blocks"] == PRIMARY_CAPACITY
    )
    heldout = next(
        row
        for row in rows
        if row["split"] == "confirmatory_heldout"
        and row["capacity_blocks"] == PRIMARY_CAPACITY
    )
    share = heldout["admission_share_of_total_gap"]
    if share >= 0.50 and discovery["admission_share_of_total_gap"] >= 0.50:
        verdict = "admission_dominant_go_causal_reuse_prediction"
    elif share >= 0.25:
        verdict = "gray_causal_upper_bound_only"
    else:
        verdict = "future_victim_dominant_stop_dynamic_controller"

    args.output.mkdir(parents=True)
    csv_path = args.output / "gap-attribution.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "kind": "belady_gap_attribution",
        "primary_capacity_blocks": PRIMARY_CAPACITY,
        "capacities_blocks": list(capacities),
        "discovery_admission_share": discovery["admission_share_of_total_gap"],
        "heldout_admission_share": heldout["admission_share_of_total_gap"],
        "heldout_future_victim_share": heldout[
            "future_victim_share_of_total_gap"
        ],
        "heldout_total_gap_fraction_of_lfru": heldout[
            "total_gap_fraction_of_lfru"
        ],
        "verdict": verdict,
        "warning": "forced-admit Belady is a decomposition oracle, not a deployable policy",
        "inputs": {
            "discovery_manifest_sha256": sha256_file(
                args.discovery / "manifest.json"
            ),
            "heldout_manifest_sha256": sha256_file(args.heldout / "manifest.json"),
        },
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
