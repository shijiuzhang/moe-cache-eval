#!/usr/bin/env python3
"""Block-permutation null tests for multiscale MoE expert clustering."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import torch
from safetensors import safe_open
from scipy.cluster.hierarchy import cophenet, fcluster, linkage
from scipy.spatial.distance import squareform
from scipy.stats import rankdata

from analyze_routes import (
    CLUSTER_COUNTS,
    EPS,
    adjusted_rand,
    normalized_mutual_information,
    pearson_from_ranked,
)


DEFAULT_BLOCK_SIZES = (1, 2, 4, 8, 16, 32, 64)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"No rows for {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def bh_adjust(p_values: list[float]) -> list[float]:
    values = np.asarray(p_values, dtype=np.float64)
    order = np.argsort(values)
    adjusted = np.empty_like(values)
    running = 1.0
    for reverse_rank in range(len(values) - 1, -1, -1):
        index = order[reverse_rank]
        rank = reverse_rank + 1
        running = min(running, float(values[index]) * len(values) / rank)
        adjusted[index] = running
    return adjusted.tolist()


def correlation_from_moments(
    sums: torch.Tensor, seconds: torch.Tensor, count: int
) -> np.ndarray:
    """Return [..., layer, expert, expert] correlations."""
    mean = sums / count
    second = seconds / count
    covariance = second - torch.einsum("...le,...lf->...lef", mean, mean)
    variances = covariance.diagonal(dim1=-2, dim2=-1).clamp_min(0)
    denominator = torch.sqrt(
        variances[..., :, :, None] * variances[..., :, None, :]
    )
    correlation = torch.where(
        denominator > EPS, covariance / denominator, 0.0
    ).clamp(-1.0, 1.0)
    experts = correlation.shape[-1]
    diagonal = torch.arange(experts)
    correlation[..., diagonal, diagonal] = 1.0
    return correlation.numpy()


def tree_and_partitions(
    correlation: np.ndarray, cluster_counts: tuple[int, ...]
) -> tuple[np.ndarray, dict[int, np.ndarray]]:
    distance = np.clip((1.0 - correlation) / 2.0, 0.0, 1.0)
    np.fill_diagonal(distance, 0.0)
    tree = linkage(squareform(distance, checks=False), method="average")
    coph = cophenet(tree)
    if isinstance(coph, tuple):
        coph = coph[-1]
    partitions = {
        k: fcluster(tree, t=k, criterion="maxclust") for k in cluster_counts
    }
    return np.asarray(coph), partitions


def iter_original_gates(
    root: Path,
    manifest: dict[str, Any],
    dataset_split: str | None = None,
) -> Iterator[tuple[int, torch.Tensor]]:
    num_experts = int(manifest["model"]["num_experts"])
    for shard in manifest["shards"]:
        metadata_rows = [
            json.loads(line)
            for line in (root / shard["metadata_file"]).read_text(
                encoding="utf-8"
            ).splitlines()
            if line
        ]
        with safe_open(
            root / shard["tensor_file"], framework="pt", device="cpu"
        ) as tensors:
            sample_indices = tensors.get_tensor("sample_indices").to(torch.int64)
            lengths = tensors.get_tensor("sequence_lengths").to(torch.int64)
            topk_indices = tensors.get_tensor("topk_indices").to(torch.int64)
            topk_weights = tensors.get_tensor("topk_weights").to(torch.float64)
            for row, metadata in enumerate(metadata_rows):
                record = metadata["metadata"]
                if record["variant_type"] != "original":
                    continue
                if dataset_split is not None and record["split"] != dataset_split:
                    continue
                sample_index = int(sample_indices[row])
                length = int(lengths[row])
                indices = topk_indices[row, :, :length, :]
                weights = topk_weights[row, :, :length, :]
                gates = torch.zeros(
                    (indices.shape[0], length, num_experts),
                    dtype=torch.float64,
                )
                gates.scatter_add_(2, indices, weights)
                yield sample_index, gates


def block_orders(
    num_tokens: int,
    block_size: int,
    repetitions: int,
    sample_index: int,
    seed: int,
) -> tuple[torch.Tensor, np.ndarray]:
    """Shuffle full blocks; keep a final partial block fixed at the end."""
    full_blocks = num_tokens // block_size
    full_length = full_blocks * block_size
    base_blocks = np.arange(full_blocks, dtype=np.int64)
    tail = np.arange(full_length, num_tokens, dtype=np.int64)
    offsets = np.arange(block_size, dtype=np.int64)
    orders = np.empty((repetitions, num_tokens), dtype=np.int64)
    moved = np.zeros(repetitions, dtype=np.float64)
    for repetition in range(repetitions):
        rng = np.random.default_rng(
            seed
            ^ ((sample_index + 1) * 0x9E3779B1)
            ^ ((block_size + 1) * 0x85EBCA77)
            ^ ((repetition + 1) * 0xC2B2AE3D)
        )
        shuffled = rng.permutation(base_blocks)
        full_order = (
            shuffled[:, None] * block_size + offsets[None, :]
        ).reshape(-1)
        order = np.concatenate((full_order, tail))
        orders[repetition] = order
        moved[repetition] = float(np.mean(order != np.arange(num_tokens)))
    return torch.from_numpy(orders), moved


def window_values(gates: torch.Tensor, scale: int) -> torch.Tensor:
    """Window means for [repeat, layer, token, expert] gates."""
    num_tokens = gates.shape[2]
    starts = torch.arange(0, num_tokens, scale, dtype=torch.int64)
    ends = torch.clamp(starts + scale, max=num_tokens)
    prefix = torch.cat(
        (
            torch.zeros(
                (*gates.shape[:2], 1, gates.shape[-1]), dtype=gates.dtype
            ),
            gates.cumsum(dim=2),
        ),
        dim=2,
    )
    totals = prefix[:, :, ends, :] - prefix[:, :, starts, :]
    counts = (ends - starts).to(gates.dtype)
    return totals / counts[None, None, :, None]


def observed_metrics(
    observed_dir: Path,
) -> dict[tuple[int, int], dict[str, float]]:
    rows = list(
        csv.DictReader(
            (observed_dir / "scale_cluster_stability.csv").open(
                encoding="utf-8"
            )
        )
    )
    grouped: dict[tuple[int, int], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[(int(row["scale_a"]), int(row["scale_b"]))].append(row)
    result = {}
    for pair, selected in grouped.items():
        result[pair] = {
            "adjusted_rand": float(
                np.mean([float(row["adjusted_rand"]) for row in selected])
            ),
            "normalized_mutual_information": float(
                np.mean(
                    [
                        float(row["normalized_mutual_information"])
                        for row in selected
                    ]
                )
            ),
            "cophenetic_spearman": float(
                np.mean(
                    [float(row["cophenetic_spearman"]) for row in selected]
                )
            ),
        }
    return result


def analyze_block(
    model_name: str,
    root: Path,
    manifest: dict[str, Any],
    block_size: int,
    repetitions: int,
    seed: int,
    dataset_split: str | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    num_layers = int(manifest["model"]["num_layers"])
    num_experts = int(manifest["model"]["num_experts"])
    cluster_counts = tuple(k for k in CLUSTER_COUNTS if k < num_experts)
    scales = tuple(
        scale for scale in (block_size, 2 * block_size, 4 * block_size)
        if scale <= 512
    )
    base_scale = scales[0]
    permuted_scales = scales[1:]
    observed_sum = {
        scale: torch.zeros(
            (num_layers, num_experts), dtype=torch.float64
        )
        for scale in scales
    }
    observed_second = {
        scale: torch.zeros(
            (num_layers, num_experts, num_experts), dtype=torch.float64
        )
        for scale in scales
    }
    permuted_sum = {
        scale: torch.zeros(
            (repetitions, num_layers, num_experts), dtype=torch.float64
        )
        for scale in permuted_scales
    }
    permuted_second = {
        scale: torch.zeros(
            (repetitions, num_layers, num_experts, num_experts),
            dtype=torch.float64,
        )
        for scale in permuted_scales
    }
    moved_sum = np.zeros(repetitions, dtype=np.float64)
    eligible_samples = 0
    sample_count = 0

    for sample_index, gates in iter_original_gates(
        root, manifest, dataset_split
    ):
        sample_count += 1
        num_tokens = gates.shape[1]
        if num_tokens // block_size >= 2:
            eligible_samples += 1
        for scale in scales:
            observed_values = window_values(gates[None, ...], scale)[0]
            observed_sum[scale] += observed_values.mean(dim=1)
            observed_second[scale] += torch.einsum(
                "lwe,lwf->lef", observed_values, observed_values
            ) / observed_values.shape[1]

        orders, moved = block_orders(
            num_tokens,
            block_size,
            repetitions,
            sample_index,
            seed,
        )
        moved_sum += moved
        permuted = gates[:, orders, :].permute(1, 0, 2, 3).contiguous()
        for scale in permuted_scales:
            values = window_values(permuted, scale)
            permuted_sum[scale] += values.mean(dim=2)
            permuted_second[scale] += torch.einsum(
                "rlwe,rlwf->rlef", values, values
            ) / values.shape[2]

    observed_corr = {
        scale: correlation_from_moments(
            observed_sum[scale], observed_second[scale], sample_count
        )
        for scale in scales
    }
    permuted_corr = {
        scale: correlation_from_moments(
            permuted_sum[scale], permuted_second[scale], sample_count
        )
        for scale in permuted_scales
    }

    observed_trees = {}
    for scale in scales:
        observed_trees[scale] = []
        for layer in range(num_layers):
            observed_trees[scale].append(
                tree_and_partitions(observed_corr[scale][layer], cluster_counts)
            )
    permuted_trees: dict[int, list[list[tuple[np.ndarray, dict[int, np.ndarray]]]]] = {}
    for scale in permuted_scales:
        permuted_trees[scale] = []
        for repetition in range(repetitions):
            per_layer = []
            for layer in range(num_layers):
                per_layer.append(
                    tree_and_partitions(
                        permuted_corr[scale][repetition, layer],
                        cluster_counts,
                    )
                )
            permuted_trees[scale].append(per_layer)

    observed_rows = []
    for scale_a, scale_b in zip(scales[:-1], scales[1:], strict=True):
        metrics = defaultdict(list)
        for layer in range(num_layers):
            coph_a, partitions_a = observed_trees[scale_a][layer]
            coph_b, partitions_b = observed_trees[scale_b][layer]
            metrics["cophenetic_spearman"].append(
                pearson_from_ranked(rankdata(coph_a), rankdata(coph_b))
            )
            for k in cluster_counts:
                metrics["adjusted_rand"].append(
                    adjusted_rand(partitions_a[k], partitions_b[k])
                )
                metrics["normalized_mutual_information"].append(
                    normalized_mutual_information(
                        partitions_a[k], partitions_b[k]
                    )
                )
        observed_rows.append(
            {
                "model": model_name,
                "dataset_split": dataset_split or "all",
                "block_size": block_size,
                "scale_a": scale_a,
                "scale_b": scale_b,
                "adjusted_rand": float(np.mean(metrics["adjusted_rand"])),
                "normalized_mutual_information": float(
                    np.mean(metrics["normalized_mutual_information"])
                ),
                "cophenetic_spearman": float(
                    np.mean(metrics["cophenetic_spearman"])
                ),
            }
        )

    rows = []
    for repetition in range(repetitions):
        for scale_a, scale_b in zip(scales[:-1], scales[1:], strict=True):
            metrics = defaultdict(list)
            for layer in range(num_layers):
                if scale_a == base_scale:
                    coph_a, partitions_a = observed_trees[base_scale][layer]
                else:
                    coph_a, partitions_a = permuted_trees[scale_a][repetition][
                        layer
                    ]
                coph_b, partitions_b = permuted_trees[scale_b][repetition][layer]
                metrics["cophenetic_spearman"].append(
                    pearson_from_ranked(rankdata(coph_a), rankdata(coph_b))
                )
                for k in cluster_counts:
                    metrics["adjusted_rand"].append(
                        adjusted_rand(partitions_a[k], partitions_b[k])
                    )
                    metrics["normalized_mutual_information"].append(
                        normalized_mutual_information(
                            partitions_a[k], partitions_b[k]
                        )
                    )
            rows.append(
                {
                    "model": model_name,
                    "block_size": block_size,
                    "repetition": repetition,
                    "scale_a": scale_a,
                    "scale_b": scale_b,
                    "mean_moved_token_fraction": float(
                        moved_sum[repetition] / sample_count
                    ),
                    "adjusted_rand": float(np.mean(metrics["adjusted_rand"])),
                    "normalized_mutual_information": float(
                        np.mean(metrics["normalized_mutual_information"])
                    ),
                    "cophenetic_spearman": float(
                        np.mean(metrics["cophenetic_spearman"])
                    ),
                }
            )
    metadata = {
        "model": model_name,
        "dataset_split": dataset_split or "all",
        "block_size": block_size,
        "repetitions": repetitions,
        "samples": sample_count,
        "eligible_samples": eligible_samples,
        "eligible_sample_fraction": eligible_samples / sample_count,
        "mean_moved_token_fraction": float(
            np.mean(moved_sum / sample_count)
        ),
        "scales": list(scales),
    }
    return rows, observed_rows, metadata


def observed_metrics_from_rows(
    rows: list[dict[str, Any]],
) -> dict[tuple[int, int], dict[str, float]]:
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(int(row["scale_a"]), int(row["scale_b"]))].append(row)
    result = {}
    for pair, selected in grouped.items():
        result[pair] = {
            metric: float(np.mean([float(row[metric]) for row in selected]))
            for metric in (
                "adjusted_rand",
                "normalized_mutual_information",
                "cophenetic_spearman",
            )
        }
    return result


def summarize(
    rows: list[dict[str, Any]],
    observed: dict[tuple[int, int], dict[str, float]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[
            (int(row["block_size"]), int(row["scale_a"]), int(row["scale_b"]))
        ].append(row)
    summary_rows = []
    metrics = (
        "adjusted_rand",
        "normalized_mutual_information",
        "cophenetic_spearman",
    )
    for (block_size, scale_a, scale_b), selected in sorted(grouped.items()):
        for metric in metrics:
            null = np.asarray(
                [float(row[metric]) for row in selected], dtype=np.float64
            )
            value = observed[(scale_a, scale_b)][metric]
            greater_p = float(
                (1 + np.sum(null >= value)) / (len(null) + 1)
            )
            less_p = float(
                (1 + np.sum(null <= value)) / (len(null) + 1)
            )
            two_sided_p = float(
                (
                    1
                    + np.sum(
                        np.abs(null - null.mean())
                        >= abs(value - null.mean())
                    )
                )
                / (len(null) + 1)
            )
            summary_rows.append(
                {
                    "block_size": block_size,
                    "scale_a": scale_a,
                    "scale_b": scale_b,
                    "metric": metric,
                    "observed": value,
                    "null_mean": float(null.mean()),
                    "null_std": float(null.std(ddof=1)),
                    "null_p05": float(np.quantile(null, 0.05)),
                    "null_p95": float(np.quantile(null, 0.95)),
                    "observed_minus_null": float(value - null.mean()),
                    "empirical_greater_p_value": greater_p,
                    "empirical_less_p_value": less_p,
                    "empirical_two_sided_p_value": two_sided_p,
                    "observed_null_percentile": float(np.mean(null < value)),
                    "mean_moved_token_fraction": float(
                        np.mean(
                            [
                                row["mean_moved_token_fraction"]
                                for row in selected
                            ]
                        )
                    ),
                    "repetitions": len(null),
                }
            )
    for metric in metrics:
        indices = [
            index
            for index, row in enumerate(summary_rows)
            if row["metric"] == metric
        ]
        for p_column, q_column in (
            (
                "empirical_greater_p_value",
                "bh_greater_q_value_within_metric",
            ),
            (
                "empirical_two_sided_p_value",
                "bh_two_sided_q_value_within_metric",
            ),
        ):
            adjusted = bh_adjust(
                [summary_rows[index][p_column] for index in indices]
            )
            for index, q_value in zip(indices, adjusted, strict=True):
                summary_rows[index][q_column] = q_value
    return summary_rows


def change_point_analysis(
    rows: list[dict[str, Any]],
    observed: dict[tuple[int, int], dict[str, float]],
) -> list[dict[str, Any]]:
    """Max-contrast test over all candidate cuts on the canonical block curve."""
    metrics = (
        "adjusted_rand",
        "normalized_mutual_information",
        "cophenetic_spearman",
    )
    canonical = [
        row for row in rows if int(row["scale_a"]) == int(row["block_size"])
    ]
    blocks = sorted({int(row["block_size"]) for row in canonical})
    repetitions = sorted({int(row["repetition"]) for row in canonical})
    result = []
    for metric in metrics:
        observed_curve = np.asarray(
            [observed[(block, 2 * block)][metric] for block in blocks],
            dtype=np.float64,
        )
        null_curve = np.zeros(
            (len(repetitions), len(blocks)), dtype=np.float64
        )
        lookup = {
            (int(row["repetition"]), int(row["block_size"])): float(row[metric])
            for row in canonical
        }
        for repetition_index, repetition in enumerate(repetitions):
            for block_index, block in enumerate(blocks):
                null_curve[repetition_index, block_index] = lookup[
                    (repetition, block)
                ]
        observed_contrasts = np.asarray(
            [
                observed_curve[cut:].mean() - observed_curve[:cut].mean()
                for cut in range(1, len(blocks))
            ]
        )
        null_contrasts = np.stack(
            [
                null_curve[:, cut:].mean(axis=1)
                - null_curve[:, :cut].mean(axis=1)
                for cut in range(1, len(blocks))
            ],
            axis=1,
        )
        best_cut = int(observed_contrasts.argmax())
        observed_max = float(observed_contrasts[best_cut])
        null_max = null_contrasts.max(axis=1)
        result.append(
            {
                "metric": metric,
                "change_before_block_size": blocks[best_cut + 1],
                "fine_block_sizes": " ".join(
                    str(block) for block in blocks[: best_cut + 1]
                ),
                "coarse_block_sizes": " ".join(
                    str(block) for block in blocks[best_cut + 1 :]
                ),
                "observed_max_coarse_minus_fine": observed_max,
                "null_max_mean": float(null_max.mean()),
                "null_max_p95": float(np.quantile(null_max, 0.95)),
                "observed_minus_null_max_mean": float(
                    observed_max - null_max.mean()
                ),
                "selection_adjusted_empirical_p_value": float(
                    (1 + np.sum(null_max >= observed_max))
                    / (len(null_max) + 1)
                ),
                "repetitions": len(repetitions),
            }
        )
    adjusted = bh_adjust(
        [row["selection_adjusted_empirical_p_value"] for row in result]
    )
    for row, q_value in zip(result, adjusted, strict=True):
        row["bh_q_value_across_metrics"] = q_value
    return result


def frozen_contrast_analysis(
    rows: list[dict[str, Any]],
    observed: dict[tuple[int, int], dict[str, float]],
    fine_blocks: tuple[int, ...] = (1, 2, 4, 8),
    coarse_blocks: tuple[int, ...] = (16, 32, 64),
) -> list[dict[str, Any]]:
    """Pre-specified coarse-minus-fine contrast without breakpoint search."""
    metrics = (
        "adjusted_rand",
        "normalized_mutual_information",
        "cophenetic_spearman",
    )
    canonical = [
        row for row in rows if int(row["scale_a"]) == int(row["block_size"])
    ]
    repetitions = sorted({int(row["repetition"]) for row in canonical})
    result = []
    for metric in metrics:
        observed_fine = np.asarray(
            [observed[(block, 2 * block)][metric] for block in fine_blocks]
        )
        observed_coarse = np.asarray(
            [observed[(block, 2 * block)][metric] for block in coarse_blocks]
        )
        observed_contrast = float(
            observed_coarse.mean() - observed_fine.mean()
        )
        lookup = {
            (int(row["repetition"]), int(row["block_size"])): float(row[metric])
            for row in canonical
        }
        null_contrasts = []
        for repetition in repetitions:
            null_fine = np.asarray(
                [lookup[(repetition, block)] for block in fine_blocks]
            )
            null_coarse = np.asarray(
                [lookup[(repetition, block)] for block in coarse_blocks]
            )
            null_contrasts.append(
                float(null_coarse.mean() - null_fine.mean())
            )
        null = np.asarray(null_contrasts, dtype=np.float64)
        result.append(
            {
                "metric": metric,
                "role": (
                    "primary"
                    if metric == "adjusted_rand"
                    else "secondary_consistency"
                ),
                "fine_block_sizes": " ".join(map(str, fine_blocks)),
                "coarse_block_sizes": " ".join(map(str, coarse_blocks)),
                "observed_fine_mean": float(observed_fine.mean()),
                "observed_coarse_mean": float(observed_coarse.mean()),
                "observed_coarse_minus_fine": observed_contrast,
                "null_contrast_mean": float(null.mean()),
                "null_contrast_std": float(null.std(ddof=1)),
                "null_contrast_p95": float(np.quantile(null, 0.95)),
                "observed_minus_null_contrast": float(
                    observed_contrast - null.mean()
                ),
                "prespecified_one_sided_p_value": float(
                    (1 + np.sum(null >= observed_contrast))
                    / (len(null) + 1)
                ),
                "repetitions": len(null),
            }
        )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--observed-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repetitions", type=int, default=32)
    parser.add_argument(
        "--block-sizes",
        type=int,
        nargs="+",
        default=list(DEFAULT_BLOCK_SIZES),
    )
    parser.add_argument("--seed", type=int, default=20260727)
    parser.add_argument(
        "--dataset-split",
        choices=("discovery", "confirmatory"),
        default=None,
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(
        (args.artifact / "manifest.json").read_text(encoding="utf-8")
    )
    all_rows = []
    all_observed_rows = []
    block_metadata = []
    for block_size in args.block_sizes:
        checkpoint = args.output / f"block-{block_size:03d}.json"
        if checkpoint.exists():
            payload = json.loads(checkpoint.read_text(encoding="utf-8"))
            rows = payload["rows"]
            observed_rows = payload.get("observed_rows", [])
            metadata = payload["metadata"]
            expected_split = args.dataset_split or "all"
            if metadata.get("dataset_split", "all") != expected_split:
                raise ValueError(
                    f"Checkpoint split mismatch for {checkpoint}: "
                    f"{metadata.get('dataset_split')} != {expected_split}"
                )
            if int(metadata["repetitions"]) != args.repetitions:
                raise ValueError(
                    f"Checkpoint repetition mismatch for {checkpoint}: "
                    f"{metadata['repetitions']} != {args.repetitions}"
                )
            print(f"[resume] block={block_size}", flush=True)
        else:
            print(f"[analyze] block={block_size}", flush=True)
            rows, observed_rows, metadata = analyze_block(
                args.model_name,
                args.artifact,
                manifest,
                block_size,
                args.repetitions,
                args.seed,
                args.dataset_split,
            )
            checkpoint.write_text(
                json.dumps(
                    {
                        "metadata": metadata,
                        "observed_rows": observed_rows,
                        "rows": rows,
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        all_rows.extend(rows)
        all_observed_rows.extend(observed_rows)
        block_metadata.append(metadata)
        print(
            f"[done] block={block_size} "
            f"moved={metadata['mean_moved_token_fraction']:.3f}",
            flush=True,
        )

    if all_observed_rows:
        observed = observed_metrics_from_rows(all_observed_rows)
    else:
        observed = observed_metrics(args.observed_dir)
    summary_rows = summarize(all_rows, observed)
    change_point_rows = change_point_analysis(all_rows, observed)
    frozen_contrast_rows = frozen_contrast_analysis(all_rows, observed)
    write_csv(args.output / "null_replicates.csv", all_rows)
    if all_observed_rows:
        write_csv(args.output / "observed_transitions.csv", all_observed_rows)
    write_csv(args.output / "transition_summary.csv", summary_rows)
    write_csv(args.output / "change_point_summary.csv", change_point_rows)
    write_csv(args.output / "frozen_contrast_summary.csv", frozen_contrast_rows)
    summary = {
        "schema_version": "block-permutation-v1",
        "model": args.model_name,
        "model_id": manifest["model"]["id"],
        "model_commit": manifest["model"]["commit"],
        "repetitions": args.repetitions,
        "block_sizes": args.block_sizes,
        "seed": args.seed,
        "dataset_split": args.dataset_split or "all",
        "null": (
            "shuffle complete contiguous blocks while preserving within-block "
            "token order and keeping any final partial block fixed"
        ),
        "sample_weighting": "uniform sample, then uniform window within sample",
        "blocks": block_metadata,
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"[complete] {args.output}", flush=True)


if __name__ == "__main__":
    main()
