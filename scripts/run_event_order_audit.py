#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moe_controller.events import load_event_trace
from moe_controller.simulation import simulate, simulate_event_atomic


POLICIES = ("lru", "lfru", "least_stale", "lfu", "belady")
FRACTIONS = (0.20, 0.30, 0.40)
SEEDS = (11, 23, 47, 89, 131)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit cache results against within-event order bias."
    )
    parser.add_argument("events", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}.")
    rows: list[dict] = []
    for root in args.events:
        trace = load_event_trace(root)
        model_label = root.name
        for fraction in FRACTIONS:
            capacity = int(round(trace.num_expert_blocks * fraction))
            for policy in POLICIES:
                configurations = [
                    ("sequential_source", "source", None),
                    ("sequential_reverse", "reverse", None),
                    *[
                        ("sequential_seeded_random", "seeded_random", seed)
                        for seed in SEEDS
                    ],
                ]
                for semantics, order, seed in configurations:
                    result = simulate(
                        trace,
                        policy=policy,
                        capacity_blocks=capacity,
                        cache_scope="per_layer",
                        access_order=order,
                        access_order_seed=seed,
                    )
                    row = {
                        "model_label": model_label,
                        "requested_fraction": fraction,
                        "event_semantics_label": semantics,
                        **result.to_dict(),
                    }
                    rows.append(row)
                    print(
                        f"{model_label} rho={fraction:.1f} {policy} "
                        f"{semantics} seed={seed} "
                        f"miss={result.miss_ratio:.4f}",
                        flush=True,
                    )
                for seed in SEEDS:
                    result = simulate_event_atomic(
                        trace,
                        policy=policy,
                        capacity_blocks=capacity,
                        cache_scope="per_layer",
                        tie_seed=seed,
                    )
                    rows.append(
                        {
                            "model_label": model_label,
                            "requested_fraction": fraction,
                            "event_semantics_label": "event_atomic",
                            **result.to_dict(),
                        }
                    )
                    print(
                        f"{model_label} rho={fraction:.1f} {policy} "
                        f"event_atomic seed={seed} "
                        f"miss={result.miss_ratio:.4f}",
                        flush=True,
                    )

    args.output.mkdir(parents=True)
    csv_path = args.output / "event-order-results.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "purpose": (
            "blocker audit for expert-ID within-event replay-order bias"
        ),
        "policies": list(POLICIES),
        "fractions": list(FRACTIONS),
        "seeds": list(SEEDS),
        "scope": "per_layer_equal_quota",
        "semantics": {
            "sequential_source": "expert_id_ascending from event artifact",
            "sequential_reverse": "reverse source order",
            "sequential_seeded_random": "independent seeded shuffle per event",
            "event_atomic": (
                "hits fixed at event start; misses fetched; retention decided "
                "after all experts in the event are served"
            ),
        },
        "artifacts": {"results": csv_path.name},
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
