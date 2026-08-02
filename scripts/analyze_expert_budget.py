#!/usr/bin/env python3
"""Analyze paired confirmatory expert-budget interventions."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import wilcoxon


CONDITIONS = ("facility", "frequency", "random")
COMPARISONS = (
    ("facility", "frequency"),
    ("facility", "random"),
    ("frequency", "random"),
)


def read_csv(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"No rows for {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def holm_pvalues(pvalues: list[float]) -> list[float]:
    order = np.argsort(pvalues)
    adjusted = np.empty(len(pvalues), dtype=np.float64)
    running = 0.0
    for rank, index in enumerate(order):
        value = (len(pvalues) - rank) * pvalues[index]
        running = max(running, value)
        adjusted[index] = min(1.0, running)
    return adjusted.tolist()


def bootstrap_token_difference(
    rows_a: list[dict[str, str]],
    rows_b: list[dict[str, str]],
    seed: int,
    replicates: int,
) -> tuple[float, float]:
    delta_sum = np.asarray(
        [
            float(a["intervention_loss_sum"])
            - float(b["intervention_loss_sum"])
            for a, b in zip(rows_a, rows_b, strict=True)
        ],
        dtype=np.float64,
    )
    tokens = np.asarray(
        [int(row["loss_tokens"]) for row in rows_a], dtype=np.float64
    )
    rng = np.random.default_rng(seed)
    estimates = np.empty(replicates, dtype=np.float64)
    for replicate in range(replicates):
        indices = rng.integers(0, len(rows_a), size=len(rows_a))
        estimates[replicate] = (
            delta_sum[indices].sum() / tokens[indices].sum()
        )
    return tuple(np.quantile(estimates, [0.025, 0.975]).tolist())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("analysis/expert-budget-interventions-v1"),
    )
    parser.add_argument("--seed", type=int, default=20260727)
    parser.add_argument("--bootstrap-replicates", type=int, default=10000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    by_condition = {
        condition: {
            int(row["sample_index"]): row
            for row in read_csv(args.input / f"{condition}.csv")
        }
        for condition in CONDITIONS
    }
    common = sorted(
        set.intersection(
            *(set(rows) for rows in by_condition.values())
        )
    )
    comparison_rows = []
    raw_pvalues = []
    for comparison_index, (condition_a, condition_b) in enumerate(COMPARISONS):
        rows_a = [by_condition[condition_a][index] for index in common]
        rows_b = [by_condition[condition_b][index] for index in common]
        delta_a = np.asarray(
            [float(row["nll_delta"]) for row in rows_a]
        )
        delta_b = np.asarray(
            [float(row["nll_delta"]) for row in rows_b]
        )
        paired = delta_a - delta_b
        token_difference = (
            sum(
                float(a["intervention_loss_sum"])
                - float(b["intervention_loss_sum"])
                for a, b in zip(rows_a, rows_b, strict=True)
            )
            / sum(int(row["loss_tokens"]) for row in rows_a)
        )
        ci_low, ci_high = bootstrap_token_difference(
            rows_a,
            rows_b,
            args.seed + 1009 * comparison_index,
            args.bootstrap_replicates,
        )
        test = wilcoxon(paired, zero_method="wilcox", alternative="two-sided")
        raw_pvalues.append(float(test.pvalue))
        comparison_rows.append(
            {
                "condition_a": condition_a,
                "condition_b": condition_b,
                "samples": len(common),
                "mean_sample_nll_difference_a_minus_b": float(paired.mean()),
                "median_sample_nll_difference_a_minus_b": float(
                    np.median(paired)
                ),
                "token_weighted_nll_difference_a_minus_b": token_difference,
                "token_weighted_bootstrap_ci_low": ci_low,
                "token_weighted_bootstrap_ci_high": ci_high,
                "fraction_a_better": float(np.mean(paired < 0)),
                "fraction_tied": float(np.mean(paired == 0)),
                "wilcoxon_statistic": float(test.statistic),
                "wilcoxon_p_raw": float(test.pvalue),
            }
        )
    for row, adjusted in zip(
        comparison_rows, holm_pvalues(raw_pvalues), strict=True
    ):
        row["wilcoxon_p_holm"] = adjusted
    write_csv(args.input / "paired_comparisons.csv", comparison_rows)

    category_rows = []
    categories: dict[str, list[int]] = defaultdict(list)
    for index in common:
        categories[by_condition["facility"][index]["category"]].append(index)
    for category, indices in sorted(categories.items()):
        for condition in CONDITIONS:
            selected = [by_condition[condition][index] for index in indices]
            total_delta = sum(
                float(row["intervention_loss_sum"])
                - float(row["baseline_loss_sum"])
                for row in selected
            )
            total_tokens = sum(int(row["loss_tokens"]) for row in selected)
            category_rows.append(
                {
                    "category": category,
                    "condition": condition,
                    "samples": len(selected),
                    "token_weighted_nll_delta": total_delta / total_tokens,
                    "mean_sample_nll_delta": float(
                        np.mean(
                            [float(row["nll_delta"]) for row in selected]
                        )
                    ),
                    "mean_rerouted_gate_mass_fraction": float(
                        np.mean(
                            [
                                float(row["rerouted_gate_mass_fraction"])
                                for row in selected
                            ]
                        )
                    ),
                }
            )
    write_csv(args.input / "category_summary.csv", category_rows)
    output = {
        "samples": len(common),
        "bootstrap_replicates": args.bootstrap_replicates,
        "seed": args.seed,
        "comparisons": comparison_rows,
    }
    (args.input / "paired_summary.json").write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(output, indent=2), flush=True)


if __name__ == "__main__":
    main()
