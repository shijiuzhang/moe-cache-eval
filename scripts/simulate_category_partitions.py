#!/usr/bin/env python3
"""Evaluate hard workload-labelled cache partitions on one mixed stream."""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moe_controller.events import load_event_trace, sha256_file
from moe_controller.simulation import simulate_event_atomic


ALLOCATIONS = (
    (4, 4, 43),
    (6, 6, 39),
    (8, 8, 35),
    (10, 10, 31),
    (12, 12, 27),
    (14, 14, 23),
    (16, 16, 19),
)
POLICY = "lfru"
TOTAL_CAPACITY = 2458
NUM_LAYERS = 48
REMAINDER_BLOCKS = 10


def allocation_blocks(allocation: tuple[int, int, int]) -> dict[str, int]:
    office, rag, other = allocation
    if office + rag + other != 51:
        raise ValueError("Per-layer partition slots must sum to 51.")
    capacities = {
        "office": office * NUM_LAYERS,
        "rag": rag * NUM_LAYERS,
        "other": other * NUM_LAYERS + REMAINDER_BLOCKS,
    }
    if sum(capacities.values()) != TOTAL_CAPACITY:
        raise ValueError("Partition capacity differs from shared baseline.")
    return capacities


def step_miss_distribution(trace, event_misses: tuple[int, ...]) -> np.ndarray:
    values = np.zeros(int(trace.scheduler_steps.max()) + 1, dtype=np.int64)
    np.add.at(values, trace.scheduler_steps, np.asarray(event_misses, dtype=np.int64))
    return values


def summarize_shared(label: str, root: Path) -> tuple[dict, object, object]:
    trace = load_event_trace(root)
    result = simulate_event_atomic(
        trace,
        policy=POLICY,
        capacity_blocks=TOTAL_CAPACITY,
        cache_scope="per_layer",
        tie_seed=20260729,
        include_event_misses=True,
    )
    logical = int(trace.manifest["counts"]["logical_expert_assignments_before_dedup"])
    output_tokens = int(trace.manifest["counts"]["decode_forwards"])
    row = {
        "split": label,
        "kind": "shared",
        "allocation": "shared=51",
        "office_slots": "",
        "rag_slots": "",
        "other_slots": "",
        "total_capacity_blocks": TOTAL_CAPACITY,
        "logical_blocks": logical,
        "output_tokens": output_tokens,
        "transferred_blocks": result.transferred_blocks,
        "effective_miss_fraction": result.transferred_blocks / logical,
        "blocks_per_output_token": result.transferred_blocks / output_tokens,
        "relative_transfer_reduction_vs_shared": 0.0,
        "step_miss_p99": result.step_miss_p99,
        "max_step_misses": result.max_step_misses,
        "cache_churn_blocks": result.cache_churn_blocks,
    }
    return row, trace, result


def evaluate_split(
    label: str,
    base_root: Path,
    partitions_root: Path,
) -> list[dict]:
    shared_row, base_trace, shared_result = summarize_shared(label, base_root)
    rows = [shared_row]
    traces = {
        name: load_event_trace(partitions_root / name)
        for name in ("office", "rag", "other")
    }
    logical = int(base_trace.manifest["counts"]["logical_expert_assignments_before_dedup"])
    output_tokens = int(base_trace.manifest["counts"]["decode_forwards"])
    if sum(
        int(trace.manifest["counts"]["logical_expert_assignments_before_dedup"])
        for trace in traces.values()
    ) != logical:
        raise ValueError("Partition logical assignments do not sum to the base stream.")

    for allocation in ALLOCATIONS:
        capacities = allocation_blocks(allocation)
        results = {
            name: simulate_event_atomic(
                trace,
                policy=POLICY,
                capacity_blocks=capacities[name],
                cache_scope="per_layer",
                tie_seed=20260729,
                include_event_misses=True,
            )
            for name, trace in traces.items()
        }
        transferred = sum(result.transferred_blocks for result in results.values())
        max_step = max(int(base_trace.scheduler_steps.max()), 0) + 1
        combined_steps = np.zeros(max_step, dtype=np.int64)
        for name, result in results.items():
            values = step_miss_distribution(traces[name], result.event_misses)
            combined_steps[: len(values)] += values
        rows.append(
            {
                "split": label,
                "kind": "hard_partition",
                "allocation": f"office={allocation[0]};rag={allocation[1]};other={allocation[2]}",
                "office_slots": allocation[0],
                "rag_slots": allocation[1],
                "other_slots": allocation[2],
                "total_capacity_blocks": sum(capacities.values()),
                "logical_blocks": logical,
                "output_tokens": output_tokens,
                "transferred_blocks": transferred,
                "effective_miss_fraction": transferred / logical,
                "blocks_per_output_token": transferred / output_tokens,
                "relative_transfer_reduction_vs_shared": (
                    1.0 - transferred / shared_result.transferred_blocks
                ),
                "step_miss_p99": float(np.quantile(combined_steps, 0.99)),
                "max_step_misses": int(combined_steps.max()),
                "cache_churn_blocks": sum(
                    result.cache_churn_blocks for result in results.values()
                ),
            }
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discovery-base", type=Path, required=True)
    parser.add_argument("--discovery-partitions", type=Path, required=True)
    parser.add_argument("--heldout-base", type=Path, required=True)
    parser.add_argument("--heldout-partitions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Output exists: {args.output}")

    discovery_rows = evaluate_split(
        "discovery_matched", args.discovery_base, args.discovery_partitions
    )
    candidates = [row for row in discovery_rows if row["kind"] == "hard_partition"]
    selected = min(candidates, key=lambda row: row["transferred_blocks"])
    heldout_rows = evaluate_split(
        "confirmatory_heldout", args.heldout_base, args.heldout_partitions
    )
    selected_heldout = next(
        row for row in heldout_rows if row["allocation"] == selected["allocation"]
    )
    heldout_shared = next(row for row in heldout_rows if row["kind"] == "shared")
    heldout_oracle = min(
        (row for row in heldout_rows if row["kind"] == "hard_partition"),
        key=lambda row: row["transferred_blocks"],
    )
    improvement = float(selected_heldout["relative_transfer_reduction_vs_shared"])
    if improvement >= 0.05:
        verdict = "go_category_partition_then_affinity"
    elif improvement > 0.0:
        verdict = "gray_soft_reservation_only"
    else:
        verdict = "no_go_hard_partition"

    rows = discovery_rows + heldout_rows
    args.output.mkdir(parents=True)
    csv_path = args.output / "partition-grid.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "kind": "category_partition_experiment",
        "policy": POLICY,
        "cache_scope": "per_layer",
        "rho": 0.4,
        "total_capacity_blocks": TOTAL_CAPACITY,
        "discovery_selected_allocation": selected["allocation"],
        "discovery_selected_improvement": selected[
            "relative_transfer_reduction_vs_shared"
        ],
        "heldout_selected_improvement": improvement,
        "heldout_selected_effective_miss_fraction": selected_heldout[
            "effective_miss_fraction"
        ],
        "heldout_shared_effective_miss_fraction": heldout_shared[
            "effective_miss_fraction"
        ],
        "heldout_oracle_allocation": heldout_oracle["allocation"],
        "heldout_oracle_improvement": heldout_oracle[
            "relative_transfer_reduction_vs_shared"
        ],
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
