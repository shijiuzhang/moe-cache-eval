#!/usr/bin/env python3
"""Compare all frozen 32/40 budget strategies on the same confirmatory set."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import numpy as np
from scipy.stats import spearmanr, wilcoxon


STRATEGIES = {
    "random": Path("analysis/expert-budget-interventions-v1/random.csv"),
    "frequency_count": Path(
        "analysis/expert-budget-interventions-v1/frequency.csv"
    ),
    "frequency_gate_mass": Path(
        "analysis/expert-budget-gatemse-interventions-v1/frequency.csv"
    ),
    "facility_raw_mse_4": Path(
        "analysis/expert-budget-interventions-v1/facility.csv"
    ),
    "facility_raw_mse_8": Path(
        "analysis/expert-budget-raw8-interventions-v1/facility.csv"
    ),
    "facility_gate_weighted_mse": Path(
        "analysis/expert-budget-gatemse-interventions-v1/facility.csv"
    ),
    "facility_diagonal_fisher_23": Path(
        "analysis/expert-budget-downstream-interventions-v1/facility.csv"
    ),
    "facility_diagonal_fisher_22": Path(
        "analysis/expert-budget-downstream-stable22-interventions-v1/"
        "facility.csv"
    ),
}

COMPARISONS = (
    ("facility_diagonal_fisher_23", "frequency_gate_mass"),
    ("facility_diagonal_fisher_22", "frequency_gate_mass"),
    ("facility_gate_weighted_mse", "frequency_gate_mass"),
    ("frequency_gate_mass", "frequency_count"),
    ("facility_raw_mse_8", "facility_raw_mse_4"),
    ("facility_gate_weighted_mse", "facility_raw_mse_8"),
    ("facility_diagonal_fisher_22", "facility_diagonal_fisher_23"),
    ("facility_diagonal_fisher_23", "facility_raw_mse_8"),
)


def read_rows(path: Path) -> dict[int, dict[str, str]]:
    return {
        int(row["sample_index"]): row
        for row in csv.DictReader(path.open(encoding="utf-8"))
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"No rows for {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def holm(pvalues: list[float]) -> list[float]:
    order = np.argsort(pvalues)
    adjusted = np.empty(len(pvalues), dtype=np.float64)
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, (len(pvalues) - rank) * pvalues[index])
        adjusted[index] = min(1.0, running)
    return adjusted.tolist()


def bootstrap_difference(
    rows_a: list[dict[str, str]],
    rows_b: list[dict[str, str]],
    rng: np.random.Generator,
    replicates: int,
) -> tuple[float, float]:
    loss_difference = np.asarray(
        [
            float(a["intervention_loss_sum"])
            - float(b["intervention_loss_sum"])
            for a, b in zip(rows_a, rows_b, strict=True)
        ]
    )
    tokens = np.asarray([int(row["loss_tokens"]) for row in rows_a])
    estimates = np.empty(replicates)
    for replicate in range(replicates):
        indices = rng.integers(0, len(rows_a), size=len(rows_a))
        estimates[replicate] = (
            loss_difference[indices].sum() / tokens[indices].sum()
        )
    return tuple(np.quantile(estimates, [0.025, 0.975]).tolist())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("analysis/downstream-budget-comparison-v1"),
    )
    parser.add_argument("--seed", type=int, default=20260727)
    parser.add_argument("--bootstrap-replicates", type=int, default=10000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    data = {name: read_rows(path) for name, path in STRATEGIES.items()}
    common = sorted(set.intersection(*(set(rows) for rows in data.values())))
    if len(common) != 200:
        raise RuntimeError(f"Expected 200 paired samples, found {len(common)}.")
    strategy_rows = []
    for name, rows_by_index in data.items():
        rows = [rows_by_index[index] for index in common]
        total_delta = sum(
            float(row["intervention_loss_sum"])
            - float(row["baseline_loss_sum"])
            for row in rows
        )
        total_tokens = sum(int(row["loss_tokens"]) for row in rows)
        sample_deltas = np.asarray(
            [float(row["nll_delta"]) for row in rows]
        )
        gate_mass = np.asarray(
            [float(row["rerouted_gate_mass_fraction"]) for row in rows]
        )
        strategy_rows.append(
            {
                "strategy": name,
                "samples": len(rows),
                "token_weighted_nll_delta": total_delta / total_tokens,
                "perplexity_ratio": float(
                    np.exp(total_delta / total_tokens)
                ),
                "mean_sample_nll_delta": float(sample_deltas.mean()),
                "median_sample_nll_delta": float(
                    np.median(sample_deltas)
                ),
                "mean_rerouted_gate_mass_fraction": float(gate_mass.mean()),
                "sample_gate_mass_vs_nll_spearman": float(
                    spearmanr(gate_mass, sample_deltas).statistic
                ),
                "fraction_samples_delta_le_0_05": float(
                    np.mean(sample_deltas <= 0.05)
                ),
            }
        )
    write_csv(args.output / "strategy_summary.csv", strategy_rows)

    comparison_rows = []
    pvalues = []
    for comparison_index, (name_a, name_b) in enumerate(COMPARISONS):
        rows_a = [data[name_a][index] for index in common]
        rows_b = [data[name_b][index] for index in common]
        sample_difference = np.asarray(
            [
                float(a["nll_delta"]) - float(b["nll_delta"])
                for a, b in zip(rows_a, rows_b, strict=True)
            ]
        )
        token_difference = (
            sum(
                float(a["intervention_loss_sum"])
                - float(b["intervention_loss_sum"])
                for a, b in zip(rows_a, rows_b, strict=True)
            )
            / sum(int(row["loss_tokens"]) for row in rows_a)
        )
        ci_low, ci_high = bootstrap_difference(
            rows_a,
            rows_b,
            np.random.default_rng(args.seed + 1009 * comparison_index),
            args.bootstrap_replicates,
        )
        test = wilcoxon(
            sample_difference, zero_method="wilcox", alternative="two-sided"
        )
        pvalues.append(float(test.pvalue))
        comparison_rows.append(
            {
                "strategy_a": name_a,
                "strategy_b": name_b,
                "samples": len(common),
                "mean_sample_nll_difference_a_minus_b": float(
                    sample_difference.mean()
                ),
                "median_sample_nll_difference_a_minus_b": float(
                    np.median(sample_difference)
                ),
                "token_weighted_nll_difference_a_minus_b": token_difference,
                "bootstrap_ci_low": ci_low,
                "bootstrap_ci_high": ci_high,
                "fraction_a_better": float(np.mean(sample_difference < 0)),
                "wilcoxon_p_raw": float(test.pvalue),
            }
        )
    for row, adjusted in zip(comparison_rows, holm(pvalues), strict=True):
        row["wilcoxon_p_holm"] = adjusted
    write_csv(args.output / "paired_comparisons.csv", comparison_rows)
    manifest = {
        "schema_version": "downstream-budget-comparison-v1",
        "samples": len(common),
        "strategies": {name: str(path) for name, path in STRATEGIES.items()},
        "comparisons": [list(pair) for pair in COMPARISONS],
        "bootstrap_replicates": args.bootstrap_replicates,
        "seed": args.seed,
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(strategy_rows, indent=2), flush=True)
    print(json.dumps(comparison_rows, indent=2), flush=True)


if __name__ == "__main__":
    main()
