#!/usr/bin/env python3
"""Solve frozen-split expert facility-location budgets from substitution costs."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import numpy as np
import torch
from safetensors import safe_open


METHODS = ("facility", "frequency", "random")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"No rows for {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def weighted_objective(
    costs: np.ndarray,
    weights: np.ndarray,
    assignment: np.ndarray,
) -> float:
    sources = np.arange(len(weights))
    valid = (
        (weights > 0)
        & np.isfinite(costs[sources, assignment])
    )
    if not valid.any():
        return float("nan")
    return float(
        np.sum(weights[valid] * costs[sources[valid], assignment[valid]])
        / np.sum(weights[valid])
    )


def assignment_for_keep(
    costs: np.ndarray, keep: list[int], weights: np.ndarray
) -> np.ndarray:
    assignment = np.full(len(weights), keep[0], dtype=np.int64)
    keep_array = np.asarray(keep, dtype=np.int64)
    for source in range(len(weights)):
        if source in keep:
            assignment[source] = source
        elif weights[source] > 0 and np.isfinite(costs[source]).any():
            candidates = costs[source, keep_array]
            finite = np.isfinite(candidates)
            if finite.any():
                assignment[source] = keep_array[
                    np.where(finite)[0][np.argmin(candidates[finite])]
                ]
    return assignment


def greedy_facilities(
    costs: np.ndarray, weights: np.ndarray, budget: int
) -> list[int]:
    selected: list[int] = []
    remaining = set(range(costs.shape[0]))
    for _ in range(budget):
        best_candidate = None
        best_objective = float("inf")
        for candidate in sorted(remaining):
            trial = selected + [candidate]
            assignment = assignment_for_keep(costs, trial, weights)
            objective = weighted_objective(costs, weights, assignment)
            if objective < best_objective:
                best_objective = objective
                best_candidate = candidate
        if best_candidate is None:
            raise RuntimeError("No finite facility candidate.")
        selected.append(best_candidate)
        remaining.remove(best_candidate)
    return sorted(selected)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--matrix-dir",
        type=Path,
        default=Path("analysis/substitution-matrix-v1"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("analysis/expert-budget-v1"),
    )
    parser.add_argument(
        "--matrix-file",
        default="substitution_matrices.safetensors",
    )
    parser.add_argument(
        "--cost",
        default="relative_mse",
        help="Tensor prefix, read as <cost>_discovery/confirmatory.",
    )
    parser.add_argument(
        "--weight",
        default="selection_counts",
        help="Tensor prefix, read as <weight>_discovery/confirmatory.",
    )
    parser.add_argument("--exclude-layers", type=int, nargs="*", default=[])
    parser.add_argument("--budget", type=int, default=32)
    parser.add_argument("--seed", type=int, default=20260727)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    matrix_manifest = json.loads(
        (args.matrix_dir / "manifest.json").read_text(encoding="utf-8")
    )
    active_layers = [
        layer
        for layer in matrix_manifest["active_layers"]
        if layer not in set(args.exclude_layers)
    ]
    with safe_open(
        args.matrix_dir / args.matrix_file,
        framework="np",
    ) as tensors:
        discovery_costs = tensors.get_tensor(f"{args.cost}_discovery")
        confirmatory_costs = tensors.get_tensor(
            f"{args.cost}_confirmatory"
        )
        discovery_counts = tensors.get_tensor(f"{args.weight}_discovery")
        confirmatory_counts = tensors.get_tensor(
            f"{args.weight}_confirmatory"
        )
    num_experts = discovery_costs.shape[-1]
    if not 1 <= args.budget <= num_experts:
        raise ValueError(args.budget)
    policies: dict[str, dict[str, Any]] = {
        method: {} for method in METHODS
    }
    rows = []
    for layer in active_layers:
        d_cost = discovery_costs[layer].astype(np.float64)
        c_cost = confirmatory_costs[layer].astype(np.float64)
        d_weight = discovery_counts[layer].astype(np.float64)
        c_weight = confirmatory_counts[layer].astype(np.float64)
        rng = np.random.default_rng(args.seed + 104729 * (layer + 1))
        keeps = {
            "facility": greedy_facilities(d_cost, d_weight, args.budget),
            "frequency": sorted(
                np.argsort(-d_weight, kind="stable")[: args.budget].tolist()
            ),
            "random": sorted(
                rng.choice(
                    num_experts, size=args.budget, replace=False
                ).tolist()
            ),
        }
        for method in METHODS:
            keep = keeps[method]
            assignment = assignment_for_keep(d_cost, keep, d_weight)
            if not set(assignment).issubset(set(keep)):
                raise RuntimeError("Assignment points to a removed expert.")
            discovery_objective = weighted_objective(
                d_cost, d_weight, assignment
            )
            confirmatory_objective = weighted_objective(
                c_cost, c_weight, assignment
            )
            policies[method][str(layer)] = {
                "keep": keep,
                "removed": sorted(set(range(num_experts)) - set(keep)),
                "assignment": assignment.tolist(),
                "discovery_objective": discovery_objective,
                "confirmatory_objective": confirmatory_objective,
            }
            rows.append(
                {
                    "method": method,
                    "layer": layer,
                    "budget": args.budget,
                    "removed_experts": " ".join(
                        map(str, policies[method][str(layer)]["removed"])
                    ),
                    "discovery_weighted_relative_mse": discovery_objective,
                    "confirmatory_weighted_relative_mse": (
                        confirmatory_objective
                    ),
                    "generalization_ratio": (
                        confirmatory_objective / discovery_objective
                        if discovery_objective > 0
                        else float("nan")
                    ),
                }
            )
    summary = []
    for method in METHODS:
        selected = [row for row in rows if row["method"] == method]
        summary.append(
            {
                "method": method,
                "layers": len(selected),
                "budget": args.budget,
                "mean_discovery_weighted_relative_mse": float(
                    np.mean(
                        [
                            row["discovery_weighted_relative_mse"]
                            for row in selected
                        ]
                    )
                ),
                "mean_confirmatory_weighted_relative_mse": float(
                    np.mean(
                        [
                            row["confirmatory_weighted_relative_mse"]
                            for row in selected
                        ]
                    )
                ),
                "expert_fraction_kept_in_active_layers": (
                    args.budget / num_experts
                ),
                "expert_fraction_kept_across_all_layers": (
                    (
                        len(active_layers) * args.budget
                        + (discovery_costs.shape[0] - len(active_layers))
                        * num_experts
                    )
                    / (discovery_costs.shape[0] * num_experts)
                ),
            }
        )
    payload = {
        "schema_version": "expert-budget-policy-v1",
        "model_id": matrix_manifest["model_id"],
        "model_commit": matrix_manifest["model_commit"],
        "source_split": "discovery",
        "held_out_split": "confirmatory",
        "matrix_source": str(args.matrix_dir / args.matrix_file),
        "cost": args.cost,
        "weight": args.weight,
        "objective": (
            "selection-frequency weighted directed k-medoids/facility loss"
        ),
        "budget": args.budget,
        "num_experts": num_experts,
        "active_layers": active_layers,
        "excluded_layers": sorted(set(args.exclude_layers)),
        "seed": args.seed,
        "methods": policies,
    }
    (args.output / "policies.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_csv(args.output / "objectives_by_layer.csv", rows)
    write_csv(args.output / "objective_summary.csv", summary)
    print(json.dumps(summary, indent=2), flush=True)
    print(f"[complete] {args.output}", flush=True)


if __name__ == "__main__":
    main()
