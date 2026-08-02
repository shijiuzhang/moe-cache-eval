#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


CAUSAL_POLICIES = {"lru", "lfu", "lfru", "least_stale"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize causal-to-Belady recoverable cache gaps."
    )
    parser.add_argument("mrc", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def load_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def main() -> None:
    args = parse_args()
    result_rows: list[dict] = []
    for path in args.mrc:
        rows = load_rows(path)
        grouped: dict[tuple[str, int], list[dict]] = {}
        for row in rows:
            key = (row["cache_scope"], int(row["capacity_blocks"]))
            grouped.setdefault(key, []).append(row)
        for (scope, capacity), group in sorted(grouped.items()):
            by_policy = {row["policy"]: row for row in group}
            causal = min(
                (
                    by_policy[policy]
                    for policy in CAUSAL_POLICIES
                    if policy in by_policy
                ),
                key=lambda row: int(row["transferred_blocks"]),
            )
            belady = by_policy["belady"]
            static = by_policy.get("static")
            causal_blocks = int(causal["transferred_blocks"])
            belady_blocks = int(belady["transferred_blocks"])
            gap = (
                (causal_blocks - belady_blocks) / causal_blocks
                if causal_blocks
                else 0.0
            )
            result_rows.append(
                {
                    "source_mrc": str(path.resolve()),
                    "model_label": path.parent.name,
                    "cache_scope": scope,
                    "capacity_blocks": capacity,
                    "capacity_fraction": float(
                        belady["capacity_fraction"]
                    ),
                    "best_causal_policy": causal["policy"],
                    "best_causal_transferred_blocks": causal_blocks,
                    "belady_transferred_blocks": belady_blocks,
                    "recoverable_gap": gap,
                    "prefill_cell_stop_candidate": gap < 0.10,
                    "static_same_trace_transferred_blocks": (
                        int(static["transferred_blocks"])
                        if static is not None
                        else None
                    ),
                    "static_same_trace_is_deployable": False,
                }
            )

    args.output.mkdir(parents=True, exist_ok=False)
    csv_path = args.output / "belady-gap.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(result_rows[0]),
        )
        writer.writeheader()
        writer.writerows(result_rows)
    summary = {
        "status": "complete",
        "scope": (
            "Probe-1K teacher-forced prefill only; not a project-level "
            "go/no-go"
        ),
        "gap_definition": (
            "(best causal transferred blocks - Belady transferred blocks) "
            "/ best causal transferred blocks"
        ),
        "causal_policies": sorted(CAUSAL_POLICIES),
        "static_warning": (
            "Static residents were selected on the evaluated trace and are "
            "an oracle-static diagnostic, not a deployable baseline."
        ),
        "rows": result_rows,
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
