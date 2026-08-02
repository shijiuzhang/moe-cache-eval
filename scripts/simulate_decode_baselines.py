#!/usr/bin/env python3
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


POLICIES = ("lru", "lfu", "lfru", "least_stale", "belady")
CAUSAL = ("lru", "lfu", "lfru", "least_stale")
FRACTIONS = (0.20, 0.30, 0.40)
SCOPES = ("global", "per_layer")
TIE_SEED = 20260729
K3_LOGICAL_BYTES_PER_TOKEN = 25.83e9


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run atomic FCFS-union decode cache baselines."
    )
    parser.add_argument("events", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--scope",
        action="append",
        choices=SCOPES,
        help="Cache scope to evaluate; repeat as needed (default: both).",
    )
    parser.add_argument(
        "--fraction",
        action="append",
        type=float,
        help="Capacity fraction to evaluate; repeat as needed (default: .2/.3/.4).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output.exists():
        raise FileExistsError(f"Output exists: {args.output}.")
    policy_rows: list[dict] = []
    gap_rows: list[dict] = []
    for root in args.events:
        trace = load_event_trace(root)
        conversion = trace.manifest["conversion"]
        if trace.manifest["kind"] != "decode_event_trace":
            raise ValueError(f"{root} is not a decode event trace.")
        if not conversion["same_step_cross_request_dedup"]:
            raise ValueError("Decode baseline requires cross-request dedup.")
        batch_size = int(conversion["batch_size"])
        logical = int(
            trace.manifest["counts"][
                "logical_expert_assignments_before_dedup"
            ]
        )
        union = int(
            trace.manifest["counts"]["union_expert_accesses"]
        )
        output_tokens = int(
            trace.manifest["counts"]["decode_forwards"]
        )
        scopes = tuple(args.scope) if args.scope else SCOPES
        fractions = tuple(args.fraction) if args.fraction else FRACTIONS
        for scope in scopes:
            for fraction in fractions:
                if not 0.0 < fraction <= 1.0:
                    raise ValueError("Capacity fractions must be in (0, 1].")
                capacity = round(trace.num_expert_blocks * fraction)
                group: dict[str, dict] = {}
                for policy in POLICIES:
                    result = simulate_event_atomic(
                        trace,
                        policy=policy,
                        capacity_blocks=capacity,
                        cache_scope=scope,
                        tie_seed=TIE_SEED,
                    )
                    effective_miss = (
                        result.transferred_blocks / logical
                        if logical
                        else 0.0
                    )
                    projected_bytes = (
                        K3_LOGICAL_BYTES_PER_TOKEN * effective_miss
                    )
                    row = {
                        "model_label": root.name,
                        "batch_size": batch_size,
                        "queue_order": conversion["queue_order"],
                        "cache_scope": scope,
                        "rho": fraction,
                        "capacity_blocks": capacity,
                        "policy": policy,
                        "logical_blocks_before_dedup": logical,
                        "union_blocks_before_cache": union,
                        "fcfs_union_ratio": union / logical,
                        "output_tokens": output_tokens,
                        "transferred_blocks": result.transferred_blocks,
                        "blocks_per_output_token": (
                            result.transferred_blocks / output_tokens
                        ),
                        "effective_miss_fraction": effective_miss,
                        "projected_k3_bytes_per_output_token": projected_bytes,
                        "projected_bw_at_20tps_per_active_user": (
                            projected_bytes * batch_size * 20
                        ),
                        "event_miss_p99": result.event_miss_p99,
                        "step_miss_p99": result.step_miss_p99,
                        "max_step_misses": result.max_step_misses,
                        "event_semantics": result.event_semantics,
                        "tie_seed": TIE_SEED,
                    }
                    policy_rows.append(row)
                    group[policy] = row
                best = min(
                    (group[policy] for policy in CAUSAL),
                    key=lambda item: item["transferred_blocks"],
                )
                oracle = group["belady"]
                gap = (
                    (
                        best["transferred_blocks"]
                        - oracle["transferred_blocks"]
                    )
                    / best["transferred_blocks"]
                    if best["transferred_blocks"]
                    else 0.0
                )
                primary_r = batch_size * 20
                budget = 150e9 / (
                    K3_LOGICAL_BYTES_PER_TOKEN * primary_r
                )
                causal_meets = (
                    best["effective_miss_fraction"] <= budget
                )
                oracle_meets = (
                    oracle["effective_miss_fraction"] <= budget
                )
                if not oracle_meets:
                    verdict = "oracle_veto_pure_cache_schedule_infeasible"
                elif causal_meets and gap < 0.10:
                    verdict = "commodity_baseline_sufficient"
                elif causal_meets:
                    verdict = "feasible_with_optional_algorithm_space"
                else:
                    verdict = "algorithm_required_or_baseline_infeasible"
                gap_rows.append(
                    {
                        "model_label": root.name,
                        "batch_size": batch_size,
                        "cache_scope": scope,
                        "rho": fraction,
                        "best_causal": best["policy"],
                        "best_causal_effective_miss_fraction": best[
                            "effective_miss_fraction"
                        ],
                        "belady_effective_miss_fraction": oracle[
                            "effective_miss_fraction"
                        ],
                        "recoverable_gap": gap,
                        "primary_bw_bytes_per_second": 150e9,
                        "primary_aggregate_output_tps": primary_r,
                        "primary_m_budget": budget,
                        "best_causal_meets_primary_budget": causal_meets,
                        "belady_meets_primary_budget": oracle_meets,
                        "verdict": verdict,
                    }
                )
                print(
                    f"{root.name} B={batch_size} {scope} "
                    f"rho={fraction:.1f} best={best['policy']} "
                    f"m={best['effective_miss_fraction']:.4f} "
                    f"oracle={oracle['effective_miss_fraction']:.4f} "
                    f"gap={gap:.4f} verdict={verdict}",
                    flush=True,
                )

    args.output.mkdir(parents=True)
    for filename, rows in (
        ("policy-results.csv", policy_rows),
        ("belady-gap-and-budget.csv", gap_rows),
    ):
        with (args.output / filename).open(
            "w",
            encoding="utf-8",
            newline="",
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "inputs": [
            {
                "root": str(root.resolve()),
                "manifest_sha256": sha256_file(root / "manifest.json"),
            }
            for root in args.events
        ],
        "baseline": {
            "scheduler": "FCFS",
            "same_step_cross_request_dedup": True,
            "event_semantics": "atomic",
            "policies": list(POLICIES),
            "scopes": list(scopes),
            "fractions": list(fractions),
            "tie_seed": TIE_SEED,
        },
        "k3_projection": {
            "logical_bytes_per_output_token": K3_LOGICAL_BYTES_PER_TOKEN,
            "warning": (
                "conditional paper projection from local effective miss "
                "fraction; not a K3 performance claim"
            ),
            "primary_bandwidth_bytes_per_second": 150e9,
            "primary_per_active_user_tps": 20,
        },
        "artifacts": {
            "policy_results": "policy-results.csv",
            "gap_and_budget": "belady-gap-and-budget.csv",
        },
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
