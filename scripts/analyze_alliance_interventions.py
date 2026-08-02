#!/usr/bin/env python3
"""Paired statistical analysis for expert-alliance interventions."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import wilcoxon


PAIRS = (
    ("learned_token", "random_token", "token_top1_alliance"),
    ("learned_block64", "random_block64", "strict_block64"),
    (
        "learned_block64_top1",
        "random_block64_top1",
        "block64_top1_exception",
    ),
    (
        "learned_block64_top2",
        "random_block64_top2",
        "block64_top2_exception",
    ),
)


def read_csv(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(path)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def bootstrap_mean_ci(
    values: np.ndarray, seed: int, repetitions: int = 10000
) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, len(values), size=(repetitions, len(values)))
    means = values[indices].mean(axis=1)
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def paired_analysis(root: Path, seed: int) -> list[dict[str, Any]]:
    rows = []
    for pair_index, (learned_name, random_name, policy) in enumerate(PAIRS):
        learned = {
            int(row["sample_index"]): row
            for row in read_csv(root / f"{learned_name}.csv")
        }
        random = {
            int(row["sample_index"]): row
            for row in read_csv(root / f"{random_name}.csv")
        }
        sample_indices = sorted(set(learned) & set(random))
        nll_difference = np.asarray(
            [
                float(learned[index]["nll_delta"])
                - float(random[index]["nll_delta"])
                for index in sample_indices
            ],
            dtype=np.float64,
        )
        candidate_difference = np.asarray(
            [
                float(learned[index]["candidate_expert_block_fraction"])
                - float(random[index]["candidate_expert_block_fraction"])
                for index in sample_indices
            ],
            dtype=np.float64,
        )
        low, high = bootstrap_mean_ci(
            nll_difference, seed + pair_index
        )
        less = wilcoxon(
            nll_difference,
            alternative="less",
            zero_method="wilcox",
        )
        greater = wilcoxon(
            nll_difference,
            alternative="greater",
            zero_method="wilcox",
        )
        rows.append(
            {
                "policy": policy,
                "learned_condition": learned_name,
                "random_condition": random_name,
                "samples": len(sample_indices),
                "mean_paired_nll_learned_minus_random": float(
                    nll_difference.mean()
                ),
                "median_paired_nll_learned_minus_random": float(
                    np.median(nll_difference)
                ),
                "bootstrap_95_ci_low": low,
                "bootstrap_95_ci_high": high,
                "fraction_learned_nll_lower": float(
                    np.mean(nll_difference < 0)
                ),
                "wilcoxon_learned_less_p_value": float(less.pvalue),
                "wilcoxon_learned_greater_p_value": float(greater.pvalue),
                "mean_candidate_fraction_learned_minus_random": float(
                    candidate_difference.mean()
                ),
            }
        )
    return rows


def category_analysis(root: Path) -> list[dict[str, Any]]:
    result = []
    for condition_path in sorted(root.glob("*.csv")):
        if condition_path.stem in {
            "summary",
            "paired_comparisons",
            "category_summary",
        }:
            continue
        rows = read_csv(condition_path)
        if not rows or "condition" not in rows[0]:
            continue
        grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            grouped[row["category"]].append(row)
        for category, selected in sorted(grouped.items()):
            deltas = np.asarray(
                [float(row["nll_delta"]) for row in selected]
            )
            total_difference = sum(
                float(row["intervention_loss_sum"])
                - float(row["baseline_loss_sum"])
                for row in selected
            )
            tokens = sum(int(row["loss_tokens"]) for row in selected)
            result.append(
                {
                    "condition": condition_path.stem,
                    "category": category,
                    "samples": len(selected),
                    "mean_sample_nll_delta": float(deltas.mean()),
                    "token_weighted_nll_delta": float(
                        total_difference / tokens
                    ),
                    "candidate_expert_block_fraction": float(
                        np.mean(
                            [
                                float(
                                    row[
                                        "candidate_expert_block_fraction"
                                    ]
                                )
                                for row in selected
                            ]
                        )
                    ),
                }
            )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("analysis/alliance-interventions-v1"),
    )
    parser.add_argument("--seed", type=int, default=20260727)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    paired = paired_analysis(args.root, args.seed)
    categories = category_analysis(args.root)
    write_csv(args.root / "paired_comparisons.csv", paired)
    write_csv(args.root / "category_summary.csv", categories)
    print(f"[complete] {args.root}", flush=True)


if __name__ == "__main__":
    main()
