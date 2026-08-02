#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moe_controller.events import load_event_trace, reorder_event_trace
from moe_controller.simulation import simulate_event_atomic


CATEGORIES = (
    "tool_agent",
    "document_rag",
    "legal_compliance",
    "structured_analytics",
    "software_engineering",
)
POLICIES = ("lru", "lfu", "lfru", "least_stale", "belady")
FRACTIONS = (0.20, 0.30, 0.40)
SCHEDULE_SEEDS = (11, 23, 47)
WINDOWS = (10, 25, 50, 100)
WARM_REQUESTS = 100
TARGET_REQUESTS = 100
TIE_SEED = 20260729


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit warm-cache A-to-B workload transition gaps."
    )
    parser.add_argument("events", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def stable_order(values: list[int], *, seed: int, label: str) -> list[int]:
    digest = hashlib.sha256(f"{seed}:{label}".encode()).digest()
    mixed_seed = int.from_bytes(digest[:8], "big")
    output = list(values)
    random.Random(mixed_seed).shuffle(output)
    return output


def request_metadata(root: Path) -> dict[int, dict]:
    rows: dict[int, dict] = {}
    with (root / "requests.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                rows[int(row["collection_index"])] = row["metadata"]
    return rows


def misses_by_request(trace, event_misses: tuple[int, ...]) -> dict[int, int]:
    output: dict[int, int] = defaultdict(int)
    for request_index, miss_count in zip(
        trace.request_indices,
        event_misses,
    ):
        output[int(request_index)] += int(miss_count)
    return output


def main() -> None:
    args = parse_args()
    result_names = {
        "policy-window-results.csv",
        "belady-gap-windows.csv",
        "gap-aggregate.csv",
        "manifest.json",
    }
    if args.output.exists() and any(
        (args.output / name).exists() for name in result_names
    ):
        raise FileExistsError(
            f"Refusing to overwrite existing results in {args.output}."
        )
    policy_rows: list[dict] = []
    gap_rows: list[dict] = []

    for root in args.events:
        trace = load_event_trace(root)
        metadata = request_metadata(root)
        discovery: dict[str, list[int]] = defaultdict(list)
        for request_index, row in metadata.items():
            if row["split"] == "discovery":
                discovery[row["category"]].append(request_index)
        for category in CATEGORIES:
            if len(discovery[category]) < max(WARM_REQUESTS, TARGET_REQUESTS):
                raise ValueError(f"Not enough discovery rows for {category}.")

        for schedule_seed in SCHEDULE_SEEDS:
            orders = {
                category: stable_order(
                    discovery[category],
                    seed=schedule_seed,
                    label=category,
                )
                for category in CATEGORIES
            }
            for source in CATEGORIES:
                for target in CATEGORIES:
                    if source == target:
                        continue
                    source_requests = orders[source][:WARM_REQUESTS]
                    target_requests = orders[target][:TARGET_REQUESTS]
                    scheduled = reorder_event_trace(
                        trace,
                        source_requests + target_requests,
                    )
                    for fraction in FRACTIONS:
                        capacity = round(
                            scheduled.num_expert_blocks * fraction
                        )
                        window_policy_values: dict[int, dict[str, int]] = {
                            window: {} for window in WINDOWS
                        }
                        for policy in POLICIES:
                            result = simulate_event_atomic(
                                scheduled,
                                policy=policy,
                                capacity_blocks=capacity,
                                cache_scope="per_layer",
                                tie_seed=TIE_SEED,
                                include_event_misses=True,
                            )
                            if result.event_misses is None:
                                raise RuntimeError("Missing event timeline.")
                            per_request = misses_by_request(
                                scheduled,
                                result.event_misses,
                            )
                            for window in WINDOWS:
                                transferred = sum(
                                    per_request[index]
                                    for index in target_requests[:window]
                                )
                                window_policy_values[window][policy] = (
                                    transferred
                                )
                                policy_rows.append(
                                    {
                                        "model_label": root.name,
                                        "rho": fraction,
                                        "schedule_seed": schedule_seed,
                                        "source_category": source,
                                        "target_category": target,
                                        "window_requests": window,
                                        "policy": policy,
                                        "transferred_blocks": transferred,
                                        "event_semantics": "atomic",
                                        "cache_scope": "per_layer",
                                    }
                                )

                        for window in WINDOWS:
                            values = window_policy_values[window]
                            causal = {
                                key: value
                                for key, value in values.items()
                                if key != "belady"
                            }
                            best_policy = min(causal, key=causal.get)
                            best = causal[best_policy]
                            oracle = values["belady"]
                            gap = (best - oracle) / best if best else 0.0
                            gap_rows.append(
                                {
                                    "model_label": root.name,
                                    "rho": fraction,
                                    "schedule_seed": schedule_seed,
                                    "source_category": source,
                                    "target_category": target,
                                    "window_requests": window,
                                    "best_causal": best_policy,
                                    "best_causal_blocks": best,
                                    "belady_blocks": oracle,
                                    "recoverable_gap": gap,
                                }
                            )
                        print(
                            f"{root.name} seed={schedule_seed} "
                            f"{source}->{target} rho={fraction:.1f} "
                            f"N100_gap={gap_rows[-1]['recoverable_gap']:.4f}",
                            flush=True,
                        )

    args.output.mkdir(parents=True, exist_ok=True)
    for filename, rows in (
        ("policy-window-results.csv", policy_rows),
        ("belady-gap-windows.csv", gap_rows),
    ):
        with (args.output / filename).open(
            "w",
            encoding="utf-8",
            newline="",
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    aggregates: list[dict] = []
    grouped: dict[tuple, list[float]] = defaultdict(list)
    for row in gap_rows:
        key = (
            row["model_label"],
            row["rho"],
            row["window_requests"],
        )
        grouped[key].append(float(row["recoverable_gap"]))
    for (model, rho, window), values in sorted(grouped.items()):
        ordered = sorted(values)
        p95_index = min(
            len(ordered) - 1,
            max(0, int(0.95 * len(ordered)) - 1),
        )
        aggregates.append(
            {
                "model_label": model,
                "rho": rho,
                "window_requests": window,
                "count": len(values),
                "mean_gap": statistics.mean(values),
                "median_gap": statistics.median(values),
                "p95_gap": ordered[p95_index],
                "max_gap": max(values),
                "fraction_ge_10pct": (
                    sum(value >= 0.10 for value in values) / len(values)
                ),
            }
        )
    with (args.output / "gap-aggregate.csv").open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(aggregates[0]))
        writer.writeheader()
        writer.writerows(aggregates)

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "design": {
            "categories": list(CATEGORIES),
            "policies": list(POLICIES),
            "fractions": list(FRACTIONS),
            "schedule_seeds": list(SCHEDULE_SEEDS),
            "windows": list(WINDOWS),
            "warm_requests": WARM_REQUESTS,
            "target_requests": TARGET_REQUESTS,
            "split": "discovery",
            "cache_reset_at_transition": False,
            "event_semantics": "atomic",
            "cache_scope": "per_layer",
            "tie_seed": TIE_SEED,
        },
        "inputs": [str(path.resolve()) for path in args.events],
        "artifacts": {
            "policy_results": "policy-window-results.csv",
            "gap_results": "belady-gap-windows.csv",
            "aggregate": "gap-aggregate.csv",
        },
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
