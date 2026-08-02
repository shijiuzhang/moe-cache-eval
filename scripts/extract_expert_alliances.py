#!/usr/bin/env python3
"""Extract Granite expert alliances and validate them across frozen splits."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import torch
from safetensors import safe_open

from analyze_block_permutations import (
    correlation_from_moments,
    tree_and_partitions,
)
from analyze_routes import adjusted_rand, normalized_mutual_information


SCALES = (32, 64, 128)
CLUSTER_COUNTS = (2, 4, 8)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"No rows for {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def iter_original_routes(
    root: Path, manifest: dict[str, Any]
) -> Iterator[tuple[str, int, torch.Tensor, torch.Tensor]]:
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
                split = record["split"]
                sample_index = int(sample_indices[row])
                length = int(lengths[row])
                indices = topk_indices[row, :, :length, :]
                weights = topk_weights[row, :, :length, :]
                gates = torch.zeros(
                    (indices.shape[0], length, num_experts),
                    dtype=torch.float64,
                )
                gates.scatter_add_(2, indices, weights)
                yield split, sample_index, gates, indices


def window_values(gates: torch.Tensor, scale: int) -> torch.Tensor:
    values = []
    for start in range(0, gates.shape[1], scale):
        values.append(gates[:, start : start + scale, :].mean(dim=1))
    return torch.stack(values, dim=1)


def build_partitions(
    root: Path, manifest: dict[str, Any]
) -> tuple[
    dict[str, dict[int, np.ndarray]],
    dict[str, dict[int, dict[int, list[np.ndarray]]]],
    dict[str, int],
]:
    num_layers = int(manifest["model"]["num_layers"])
    num_experts = int(manifest["model"]["num_experts"])
    splits = ("discovery", "confirmatory")
    sums = {
        split: {
            scale: torch.zeros((num_layers, num_experts), dtype=torch.float64)
            for scale in SCALES
        }
        for split in splits
    }
    seconds = {
        split: {
            scale: torch.zeros(
                (num_layers, num_experts, num_experts), dtype=torch.float64
            )
            for scale in SCALES
        }
        for split in splits
    }
    counts = {split: 0 for split in splits}
    for split, _, gates, _ in iter_original_routes(root, manifest):
        counts[split] += 1
        for scale in SCALES:
            values = window_values(gates, scale)
            sums[split][scale] += values.mean(dim=1)
            seconds[split][scale] += torch.einsum(
                "lwe,lwf->lef", values, values
            ) / values.shape[1]

    correlations: dict[str, dict[int, np.ndarray]] = {
        split: {} for split in splits
    }
    partitions = {
        split: {
            scale: {k: [] for k in CLUSTER_COUNTS} for scale in SCALES
        }
        for split in splits
    }
    for split in splits:
        for scale in SCALES:
            correlations[split][scale] = correlation_from_moments(
                sums[split][scale], seconds[split][scale], counts[split]
            )
            for layer in range(num_layers):
                _, labels = tree_and_partitions(
                    correlations[split][scale][layer], CLUSTER_COUNTS
                )
                for k in CLUSTER_COUNTS:
                    partitions[split][scale][k].append(labels[k])
    return correlations, partitions, counts


def stability_rows(
    partitions: dict[str, dict[int, dict[int, list[np.ndarray]]]],
    num_layers: int,
) -> list[dict[str, Any]]:
    comparisons = (
        ("discovery", 64, "confirmatory", 64, "cross_split_same_scale"),
        ("discovery", 64, "discovery", 32, "discovery_scale"),
        ("discovery", 64, "discovery", 128, "discovery_scale"),
        ("discovery", 64, "confirmatory", 32, "cross_split_cross_scale"),
        ("discovery", 64, "confirmatory", 128, "cross_split_cross_scale"),
    )
    rows = []
    for split_a, scale_a, split_b, scale_b, comparison in comparisons:
        for k in CLUSTER_COUNTS:
            for layer in range(num_layers):
                labels_a = partitions[split_a][scale_a][k][layer]
                labels_b = partitions[split_b][scale_b][k][layer]
                sizes = sorted(
                    np.bincount(labels_a, minlength=k + 1)[1:].tolist()
                )
                rows.append(
                    {
                        "comparison": comparison,
                        "split_a": split_a,
                        "scale_a": scale_a,
                        "split_b": split_b,
                        "scale_b": scale_b,
                        "clusters": k,
                        "layer": layer,
                        "adjusted_rand": adjusted_rand(labels_a, labels_b),
                        "normalized_mutual_information": normalized_mutual_information(
                            labels_a, labels_b
                        ),
                        "discovery_cluster_sizes": " ".join(map(str, sizes)),
                        "min_discovery_cluster_size": min(sizes),
                        "max_discovery_cluster_size": max(sizes),
                    }
                )
    return rows


def summarize_stability(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int, int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[
            (
                row["comparison"],
                int(row["scale_a"]),
                int(row["scale_b"]),
                int(row["clusters"]),
            )
        ].append(row)
    summary = []
    for (comparison, scale_a, scale_b, k), selected in sorted(grouped.items()):
        aris = np.asarray([row["adjusted_rand"] for row in selected])
        nmis = np.asarray(
            [row["normalized_mutual_information"] for row in selected]
        )
        minimum_sizes = np.asarray(
            [row["min_discovery_cluster_size"] for row in selected]
        )
        summary.append(
            {
                "comparison": comparison,
                "scale_a": scale_a,
                "scale_b": scale_b,
                "clusters": k,
                "mean_adjusted_rand": float(aris.mean()),
                "median_adjusted_rand": float(np.median(aris)),
                "layers_ari_ge_0_5": int((aris >= 0.5).sum()),
                "mean_normalized_mutual_information": float(nmis.mean()),
                "minimum_cluster_size_across_layers": int(minimum_sizes.min()),
                "layers_all_clusters_at_least_top_k_8": int(
                    (minimum_sizes >= 8).sum()
                ),
                "layers": len(selected),
            }
        )
    return summary


def coverage_analysis(
    root: Path,
    manifest: dict[str, Any],
    frozen_partitions: dict[int, list[np.ndarray]],
) -> list[dict[str, Any]]:
    num_layers = int(manifest["model"]["num_layers"])
    num_experts = int(manifest["model"]["num_experts"])
    per_sample_rows = []
    for split, sample_index, gates, topk_indices in iter_original_routes(
        root, manifest
    ):
        if split != "confirmatory":
            continue
        top1 = topk_indices[..., 0]
        for k in CLUSTER_COUNTS:
            labels = np.stack(frozen_partitions[k], axis=0) - 1
            label_tensor = torch.from_numpy(labels).to(torch.int64)
            one_hot = torch.nn.functional.one_hot(
                label_tensor, num_classes=k
            ).to(torch.float64)
            cluster_sizes = one_hot.sum(dim=1)
            token_cluster_mass = torch.einsum(
                "lte,lek->ltk", gates, one_hot
            )
            top1_clusters = torch.gather(
                label_tensor[:, None, :].expand(
                    -1, top1.shape[1], -1
                ),
                2,
                top1[..., None],
            ).squeeze(-1)
            tokenwise_selected_mass = torch.gather(
                token_cluster_mass,
                2,
                top1_clusters[..., None],
            ).squeeze(-1)
            tokenwise_pool_size = torch.gather(
                cluster_sizes[:, None, :].expand(
                    -1, top1.shape[1], -1
                ),
                2,
                top1_clusters[..., None],
            ).squeeze(-1)
            for layer in range(num_layers):
                per_sample_rows.append(
                    {
                        "sample_index": sample_index,
                        "policy": "token_top1_alliance",
                        "clusters": k,
                        "scale": 1,
                        "layer": layer,
                        "executed_gate_mass_coverage": float(
                            tokenwise_selected_mass[layer].mean()
                        ),
                        "top1_coverage": 1.0,
                        "candidate_pool_size": float(
                            tokenwise_pool_size[layer].to(torch.float64).mean()
                        ),
                        "candidate_pool_fraction": float(
                            tokenwise_pool_size[layer].to(torch.float64).mean()
                            / num_experts
                        ),
                    }
                )
            for scale in SCALES:
                for layer in range(num_layers):
                    for start in range(0, gates.shape[1], scale):
                        end = min(start + scale, gates.shape[1])
                        mass = token_cluster_mass[layer, start:end].mean(dim=0)
                        selected_cluster = int(mass.argmax())
                        selected_mass = float(mass[selected_cluster])
                        selected_top1 = float(
                            (
                                top1_clusters[layer, start:end]
                                == selected_cluster
                            )
                            .to(torch.float64)
                            .mean()
                        )
                        pool_size = int(
                            cluster_sizes[layer, selected_cluster]
                        )
                        per_sample_rows.append(
                            {
                                "sample_index": sample_index,
                                "policy": "block_dominant_alliance",
                                "clusters": k,
                                "scale": scale,
                                "layer": layer,
                                "executed_gate_mass_coverage": selected_mass,
                                "top1_coverage": selected_top1,
                                "candidate_pool_size": pool_size,
                                "candidate_pool_fraction": pool_size
                                / num_experts,
                            }
                        )
    grouped: dict[tuple[str, int, int, int], dict[int, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in per_sample_rows:
        grouped[
            (
                row["policy"],
                int(row["clusters"]),
                int(row["scale"]),
                int(row["layer"]),
            )
        ][int(row["sample_index"])].append(row)
    result = []
    for (policy, k, scale, layer), by_sample in sorted(grouped.items()):
        sample_means = []
        for rows in by_sample.values():
            sample_means.append(
                {
                    key: float(np.mean([row[key] for row in rows]))
                    for key in (
                        "executed_gate_mass_coverage",
                        "top1_coverage",
                        "candidate_pool_size",
                        "candidate_pool_fraction",
                    )
                }
            )
        result.append(
            {
                "policy": policy,
                "clusters": k,
                "scale": scale,
                "layer": layer,
                **{
                    key: float(np.mean([row[key] for row in sample_means]))
                    for key in sample_means[0]
                },
                "samples": len(sample_means),
            }
        )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact",
        type=Path,
        default=Path("artifacts/probe-1k-granite-512-v1.1"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("analysis/expert-alliances-v1"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.mkdir(parents=True)
    manifest = json.loads(
        (args.artifact / "manifest.json").read_text(encoding="utf-8")
    )
    _, partitions, counts = build_partitions(args.artifact, manifest)
    stability = stability_rows(
        partitions, int(manifest["model"]["num_layers"])
    )
    write_csv(args.output / "alliance_stability_by_layer.csv", stability)
    write_csv(
        args.output / "alliance_stability_summary.csv",
        summarize_stability(stability),
    )
    frozen = {
        k: partitions["discovery"][64][k] for k in CLUSTER_COUNTS
    }
    alliance_payload = {
        "schema_version": "expert-alliance-v1",
        "model_id": manifest["model"]["id"],
        "model_commit": manifest["model"]["commit"],
        "source_split": "discovery",
        "source_scale": 64,
        "cluster_counts": list(CLUSTER_COUNTS),
        "sample_counts": counts,
        "layers": {
            str(layer): {
                str(k): (frozen[k][layer] - 1).tolist()
                for k in CLUSTER_COUNTS
            }
            for layer in range(int(manifest["model"]["num_layers"]))
        },
    }
    (args.output / "frozen_alliances.json").write_text(
        json.dumps(alliance_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    coverage = coverage_analysis(args.artifact, manifest, frozen)
    write_csv(args.output / "confirmatory_policy_coverage.csv", coverage)
    print(f"[complete] {args.output}", flush=True)


if __name__ == "__main__":
    main()
