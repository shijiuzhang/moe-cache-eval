#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moe_controller.events import load_event_trace, subset_event_trace
from moe_controller.simulation import simulate


def parse_fractions(value: str) -> list[float]:
    return [float(item) for item in value.split(",") if item.strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Blocked request bootstrap for LFU-to-Belady gaps."
    )
    parser.add_argument("events", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--capacities",
        type=parse_fractions,
        default=parse_fractions("0.20,0.30,0.40"),
    )
    parser.add_argument("--num-blocks", type=int, default=20)
    parser.add_argument("--resamples", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20260729)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}.")
    rng = np.random.default_rng(args.seed)
    block_rows: list[dict] = []
    summary_rows: list[dict] = []

    for event_root in args.events:
        trace = load_event_trace(event_root)
        requests = np.unique(trace.request_indices)
        request_blocks = [
            values for values in np.array_split(requests, args.num_blocks)
            if values.size
        ]
        model_label = event_root.name
        for block_index, request_block in enumerate(request_blocks):
            block_trace = subset_event_trace(trace, request_block.tolist())
            for fraction in args.capacities:
                capacity = max(
                    1,
                    int(round(trace.num_expert_blocks * fraction)),
                )
                for scope in ("global", "per_layer"):
                    lfu = simulate(
                        block_trace,
                        policy="lfu",
                        capacity_blocks=capacity,
                        cache_scope=scope,
                    )
                    belady = simulate(
                        block_trace,
                        policy="belady",
                        capacity_blocks=capacity,
                        cache_scope=scope,
                    )
                    block_rows.append(
                        {
                            "model_label": model_label,
                            "block_index": block_index,
                            "num_requests": len(request_block),
                            "cache_scope": scope,
                            "capacity_fraction": (
                                capacity / trace.num_expert_blocks
                            ),
                            "capacity_blocks": capacity,
                            "lfu_transferred_blocks": lfu.transferred_blocks,
                            "belady_transferred_blocks": (
                                belady.transferred_blocks
                            ),
                        }
                    )

        keys = sorted(
            {
                (
                    row["cache_scope"],
                    row["capacity_blocks"],
                    row["capacity_fraction"],
                )
                for row in block_rows
                if row["model_label"] == model_label
            }
        )
        for scope, capacity, fraction in keys:
            rows = [
                row
                for row in block_rows
                if row["model_label"] == model_label
                and row["cache_scope"] == scope
                and row["capacity_blocks"] == capacity
            ]
            lfu_values = np.asarray(
                [row["lfu_transferred_blocks"] for row in rows],
                dtype=np.float64,
            )
            belady_values = np.asarray(
                [row["belady_transferred_blocks"] for row in rows],
                dtype=np.float64,
            )
            indices = rng.integers(
                0,
                len(rows),
                size=(args.resamples, len(rows)),
            )
            sampled_lfu = lfu_values[indices].sum(axis=1)
            sampled_belady = belady_values[indices].sum(axis=1)
            gaps = (sampled_lfu - sampled_belady) / sampled_lfu
            aggregate_gap = (
                (lfu_values.sum() - belady_values.sum())
                / lfu_values.sum()
            )
            summary_rows.append(
                {
                    "model_label": model_label,
                    "cache_scope": scope,
                    "capacity_fraction": fraction,
                    "capacity_blocks": capacity,
                    "num_request_blocks": len(rows),
                    "requests_per_block_nominal": (
                        len(requests) / len(rows)
                    ),
                    "block_reset_aggregate_gap": aggregate_gap,
                    "bootstrap_p025": float(np.quantile(gaps, 0.025)),
                    "bootstrap_p50": float(np.quantile(gaps, 0.50)),
                    "bootstrap_p975": float(np.quantile(gaps, 0.975)),
                    "prefill_stop_supported": bool(
                        np.quantile(gaps, 0.975) < 0.10
                    ),
                }
            )

    args.output.mkdir(parents=True)
    for filename, rows in (
        ("block-results.csv", block_rows),
        ("bootstrap-summary.csv", summary_rows),
    ):
        path = args.output / filename
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "method": (
            "contiguous request blocks; cache cold-reset at every block; "
            "paired nonparametric bootstrap over block totals"
        ),
        "warning": (
            "This is a sensitivity interval for block-reset prefill replay, "
            "not an IID confidence interval for the continuous cache stream."
        ),
        "causal_policy": "lfu (frozen from full-trace baseline)",
        "oracle": "Belady with bypass admission",
        "num_blocks": args.num_blocks,
        "resamples": args.resamples,
        "seed": args.seed,
        "summary": summary_rows,
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for row in summary_rows:
        print(
            f"{row['model_label']} {row['cache_scope']} "
            f"rho={row['capacity_fraction']:.3f} "
            f"gap={row['block_reset_aggregate_gap']:.4f} "
            f"CI=[{row['bootstrap_p025']:.4f},"
            f"{row['bootstrap_p975']:.4f}] "
            f"stop={row['prefill_stop_supported']}"
        )


if __name__ == "__main__":
    main()
