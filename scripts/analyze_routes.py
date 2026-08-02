#!/usr/bin/env python3
"""Analyze Probe-1K MoE routes at layer, category, pair, and token scales."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import torch
from safetensors import safe_open
from scipy.cluster.hierarchy import cophenet, fcluster, linkage
from scipy.spatial.distance import squareform
from scipy.stats import rankdata, wilcoxon


SCALES = (1, 2, 4, 8, 16, 32, 64, 128, 256, 512)
CLUSTER_COUNTS = (2, 4, 8, 16)
EPS = 1e-12


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"No rows for {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def gini(probabilities: np.ndarray) -> float:
    values = np.sort(np.asarray(probabilities, dtype=np.float64))
    if values.sum() <= 0:
        return 0.0
    n = len(values)
    return float(
        (2.0 * np.dot(np.arange(1, n + 1), values) / (n * values.sum()))
        - (n + 1) / n
    )


def entropy(probabilities: np.ndarray) -> float:
    p = np.asarray(probabilities, dtype=np.float64)
    p = p[p > 0]
    return float(-(p * np.log(p)).sum())


def js_distance(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Jensen-Shannon metric in [0, 1], operating on the last axis."""
    a = np.clip(np.asarray(a, dtype=np.float64), EPS, None)
    b = np.clip(np.asarray(b, dtype=np.float64), EPS, None)
    a /= a.sum(axis=-1, keepdims=True)
    b /= b.sum(axis=-1, keepdims=True)
    midpoint = 0.5 * (a + b)
    divergence = 0.5 * (
        (a * np.log(a / midpoint)).sum(axis=-1)
        + (b * np.log(b / midpoint)).sum(axis=-1)
    )
    return np.sqrt(np.maximum(divergence / math.log(2.0), 0.0))


def adjusted_rand(labels_a: np.ndarray, labels_b: np.ndarray) -> float:
    labels_a = np.asarray(labels_a)
    labels_b = np.asarray(labels_b)
    _, inverse_a = np.unique(labels_a, return_inverse=True)
    _, inverse_b = np.unique(labels_b, return_inverse=True)
    table = np.zeros((inverse_a.max() + 1, inverse_b.max() + 1), dtype=np.int64)
    np.add.at(table, (inverse_a, inverse_b), 1)

    def comb2(values: np.ndarray | int) -> np.ndarray | float:
        values = np.asarray(values, dtype=np.float64)
        return values * (values - 1.0) / 2.0

    total_pairs = float(comb2(len(labels_a)))
    if total_pairs == 0:
        return 1.0
    sum_cells = float(comb2(table).sum())
    sum_rows = float(comb2(table.sum(axis=1)).sum())
    sum_cols = float(comb2(table.sum(axis=0)).sum())
    expected = sum_rows * sum_cols / total_pairs
    maximum = 0.5 * (sum_rows + sum_cols)
    denominator = maximum - expected
    return float((sum_cells - expected) / denominator) if denominator else 1.0


def normalized_mutual_information(
    labels_a: np.ndarray, labels_b: np.ndarray
) -> float:
    labels_a = np.asarray(labels_a)
    labels_b = np.asarray(labels_b)
    _, inverse_a = np.unique(labels_a, return_inverse=True)
    _, inverse_b = np.unique(labels_b, return_inverse=True)
    table = np.zeros((inverse_a.max() + 1, inverse_b.max() + 1), dtype=np.float64)
    np.add.at(table, (inverse_a, inverse_b), 1)
    table /= table.sum()
    pa = table.sum(axis=1)
    pb = table.sum(axis=0)
    expected = pa[:, None] * pb[None, :]
    mask = table > 0
    mutual_information = float((table[mask] * np.log(table[mask] / expected[mask])).sum())
    ha = entropy(pa)
    hb = entropy(pb)
    denominator = ha + hb
    return float(2.0 * mutual_information / denominator) if denominator else 1.0


def pearson_from_ranked(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    denominator = np.linalg.norm(a) * np.linalg.norm(b)
    return float(np.dot(a, b) / denominator) if denominator else 0.0


def stable_hash_u64(
    sample_index: int, window_indices: np.ndarray, scale: int, seed: int
) -> np.ndarray:
    mask = (1 << 64) - 1
    base = (
        (sample_index + 1) * 0x9E3779B185EBCA87
        + (scale + 1) * 0xC2B2AE3D27D4EB4F
        + (seed + 1) * 0x165667B19E3779F9
    ) & mask
    values = window_indices.astype(np.uint64) + np.uint64(base)
    values ^= values >> np.uint64(30)
    values *= np.uint64(0xBF58476D1CE4E5B9)
    values ^= values >> np.uint64(27)
    values *= np.uint64(0x94D049BB133111EB)
    values ^= values >> np.uint64(31)
    return values


class ScaleMoments:
    """Exact sample-balanced moments of window-by-expert activations."""

    def __init__(
        self,
        num_layers: int,
        num_experts: int,
        split_seed: int,
    ) -> None:
        self.num_layers = num_layers
        self.num_experts = num_experts
        self.split_seed = split_seed
        self.scopes = ("all", "split_0", "split_1", "shuffled_all")
        self.sums = {
            scope: {
                scale: torch.zeros(
                    (num_layers, num_experts), dtype=torch.float64
                )
                for scale in SCALES
            }
            for scope in self.scopes
        }
        self.second_moments = {
            scope: {
                scale: torch.zeros(
                    (num_layers, num_experts, num_experts),
                    dtype=torch.float64,
                )
                for scale in SCALES
            }
            for scope in self.scopes
        }
        self.sample_counts = {
            scope: {scale: 0 for scale in SCALES} for scope in self.scopes
        }

    def update(self, sample_index: int, gates: torch.Tensor) -> None:
        # gates: [layer, token, expert], rows sum to one.
        gates = gates.to(torch.float64)
        num_tokens = gates.shape[1]
        shuffle_rng = np.random.default_rng(
            self.split_seed ^ ((sample_index + 1) * 0x9E3779B1)
        )
        shuffled_order = torch.from_numpy(shuffle_rng.permutation(num_tokens))
        shuffled_gates = gates[:, shuffled_order, :]
        split_hash = stable_hash_u64(
            sample_index,
            np.array([0], dtype=np.uint64),
            scale=0,
            seed=self.split_seed,
        )
        split_scope = f"split_{int(split_hash[0] & np.uint64(1))}"
        for scale in SCALES:
            def window_values(source: torch.Tensor) -> torch.Tensor:
                return torch.stack(
                    [
                        source[:, start : start + scale, :].mean(dim=1)
                        for start in range(0, num_tokens, scale)
                    ],
                    dim=0,
                )

            values = window_values(gates)  # [window, layer, expert]
            shuffled_values = window_values(shuffled_gates)
            for scope in ("all", split_scope):
                self.sums[scope][scale] += values.mean(dim=0)
                self.second_moments[scope][scale] += torch.einsum(
                    "wle,wlf->lef", values, values
                ) / values.shape[0]
                self.sample_counts[scope][scale] += 1
            self.sums["shuffled_all"][scale] += shuffled_values.mean(dim=0)
            self.second_moments["shuffled_all"][scale] += torch.einsum(
                "wle,wlf->lef", shuffled_values, shuffled_values
            ) / shuffled_values.shape[0]
            self.sample_counts["shuffled_all"][scale] += 1

    def correlation(self, scope: str, scale: int) -> np.ndarray:
        count = self.sample_counts[scope][scale]
        if count < 2:
            raise ValueError(f"Too few samples in {scope} at scale {scale}")
        mean = self.sums[scope][scale] / count
        second = self.second_moments[scope][scale] / count
        covariance = second - torch.einsum("le,lf->lef", mean, mean)
        variances = covariance.diagonal(dim1=-2, dim2=-1).clamp_min(0)
        denominator = torch.sqrt(
            variances[:, :, None] * variances[:, None, :]
        )
        correlation = torch.where(
            denominator > EPS, covariance / denominator, 0.0
        ).clamp(-1.0, 1.0)
        diagonal = torch.arange(self.num_experts)
        correlation[:, diagonal, diagonal] = 1.0
        return correlation.numpy()


@dataclass
class RouteFeatures:
    model_name: str
    root: Path
    manifest: dict[str, Any]
    metadata: list[dict[str, Any]]
    weighted_routes: np.ndarray
    top1_routes: np.ndarray
    mean_entropy: np.ndarray
    mean_margin: np.ndarray
    mean_nll: np.ndarray
    lengths: np.ndarray
    moments: ScaleMoments


def build_features(
    model_name: str,
    root: Path,
    split_seed: int,
) -> RouteFeatures:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    num_samples = int(manifest["completed_samples"])
    num_layers = int(manifest["model"]["num_layers"])
    num_experts = int(manifest["model"]["num_experts"])
    metadata: list[dict[str, Any] | None] = [None] * num_samples
    weighted = np.zeros((num_samples, num_layers, num_experts), dtype=np.float32)
    top1 = np.zeros_like(weighted)
    mean_entropy = np.zeros((num_samples, num_layers), dtype=np.float32)
    mean_margin = np.zeros_like(mean_entropy)
    mean_nll = np.zeros(num_samples, dtype=np.float32)
    lengths = np.zeros(num_samples, dtype=np.int32)
    moments = ScaleMoments(num_layers, num_experts, split_seed)

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
            sequence_lengths = tensors.get_tensor("sequence_lengths").to(torch.int64)
            topk_indices = tensors.get_tensor("topk_indices").to(torch.int64)
            topk_weights = tensors.get_tensor("topk_weights").to(torch.float32)
            route_entropy = tensors.get_tensor("router_entropy").to(torch.float32)
            route_margin = tensors.get_tensor("router_margin").to(torch.float32)
            token_nll = tensors.get_tensor("token_nll").to(torch.float32)
            for row, sample_index_tensor in enumerate(sample_indices):
                sample_index = int(sample_index_tensor)
                length = int(sequence_lengths[row])
                lengths[sample_index] = length
                metadata[sample_index] = metadata_rows[row]
                indices = topk_indices[row, :, :length, :]
                weights = topk_weights[row, :, :length, :]
                gates = torch.zeros(
                    (num_layers, length, num_experts), dtype=torch.float32
                )
                gates.scatter_add_(2, indices, weights)
                weighted[sample_index] = gates.mean(dim=1).numpy()
                first_indices = indices[..., 0]
                top1_counts = torch.zeros(
                    (num_layers, num_experts), dtype=torch.float32
                )
                top1_counts.scatter_add_(
                    1,
                    first_indices,
                    torch.full_like(first_indices, 1.0 / length, dtype=torch.float32),
                )
                top1[sample_index] = top1_counts.numpy()
                mean_entropy[sample_index] = (
                    route_entropy[row, :, :length].mean(dim=1).numpy()
                )
                mean_margin[sample_index] = (
                    route_margin[row, :, :length].mean(dim=1).numpy()
                )
                valid_nll = token_nll[row, :length]
                valid_nll = valid_nll[torch.isfinite(valid_nll)]
                mean_nll[sample_index] = float(valid_nll.mean())
                record = metadata_rows[row]["metadata"]
                if record["variant_type"] == "original":
                    moments.update(sample_index, gates)

    if any(item is None for item in metadata):
        raise RuntimeError(f"Missing sample metadata in {model_name}")
    return RouteFeatures(
        model_name=model_name,
        root=root,
        manifest=manifest,
        metadata=[item for item in metadata if item is not None],
        weighted_routes=weighted,
        top1_routes=top1,
        mean_entropy=mean_entropy,
        mean_margin=mean_margin,
        mean_nll=mean_nll,
        lengths=lengths,
        moments=moments,
    )


def original_indices(features: RouteFeatures) -> np.ndarray:
    return np.array(
        [
            index
            for index, row in enumerate(features.metadata)
            if row["metadata"]["variant_type"] == "original"
        ],
        dtype=np.int64,
    )


def utilization_analysis(features: RouteFeatures) -> list[dict[str, Any]]:
    rows = []
    originals = original_indices(features)
    num_experts = features.manifest["model"]["num_experts"]
    for route_kind, routes in (
        ("weighted_topk", features.weighted_routes),
        ("top1", features.top1_routes),
    ):
        layer_loads = routes[originals].mean(axis=0)
        for layer, load in enumerate(layer_loads):
            load = load / load.sum()
            load_entropy = entropy(load)
            rows.append(
                {
                    "model": features.model_name,
                    "layer": layer,
                    "route_kind": route_kind,
                    "normalized_load_entropy": load_entropy / math.log(num_experts),
                    "effective_experts": math.exp(load_entropy),
                    "gini": gini(load),
                    "max_expert_share": float(load.max()),
                    "min_expert_share": float(load.min()),
                    "experts_above_uniform": int(
                        (load > 1.0 / num_experts).sum()
                    ),
                    "mean_router_entropy": float(
                        features.mean_entropy[originals, layer].mean()
                    ),
                    "mean_router_margin": float(
                        features.mean_margin[originals, layer].mean()
                    ),
                }
            )
    return rows


def balanced_category_mi(
    routes: np.ndarray, category_indices: np.ndarray, num_categories: int
) -> np.ndarray:
    # routes: [sample, layer, expert], each row sums to one.
    conditional = []
    for category in range(num_categories):
        conditional.append(routes[category_indices == category].mean(axis=0))
    p_e_given_c = np.stack(conditional, axis=0).astype(np.float64)
    p_e_given_c = np.clip(p_e_given_c, EPS, None)
    p_e_given_c /= p_e_given_c.sum(axis=-1, keepdims=True)
    p_e = p_e_given_c.mean(axis=0)
    mi = (
        p_e_given_c
        * (np.log(p_e_given_c) - np.log(np.clip(p_e[None, ...], EPS, None)))
    ).sum(axis=(0, 2)) / num_categories
    return mi / math.log(num_categories)


def category_mi_analysis(
    features: RouteFeatures, permutations: int, seed: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    originals = original_indices(features)
    categories = np.array(
        [features.metadata[index]["metadata"]["category"] for index in originals]
    )
    category_names = sorted(set(categories))
    category_to_index = {name: index for index, name in enumerate(category_names)}
    category_indices = np.array(
        [category_to_index[name] for name in categories], dtype=np.int64
    )
    rng = np.random.default_rng(seed)
    rows = []
    summary: dict[str, Any] = {"categories": category_names}
    for route_kind, all_routes in (
        ("weighted_topk", features.weighted_routes),
        ("top1", features.top1_routes),
    ):
        routes = all_routes[originals]
        observed = balanced_category_mi(
            routes, category_indices, len(category_names)
        )
        null = np.zeros((permutations, routes.shape[1]), dtype=np.float64)
        for permutation in range(permutations):
            shuffled = rng.permutation(category_indices)
            null[permutation] = balanced_category_mi(
                routes, shuffled, len(category_names)
            )
        p_values = (1 + (null >= observed[None, :]).sum(axis=0)) / (
            permutations + 1
        )
        for layer in range(routes.shape[1]):
            rows.append(
                {
                    "model": features.model_name,
                    "layer": layer,
                    "route_kind": route_kind,
                    "normalized_mutual_information": float(observed[layer]),
                    "null_mean": float(null[:, layer].mean()),
                    "null_p95": float(np.quantile(null[:, layer], 0.95)),
                    "permutation_p_value": float(p_values[layer]),
                }
            )
        summary[route_kind] = {
            "mean_normalized_mi": float(observed.mean()),
            "max_normalized_mi": float(observed.max()),
            "max_layer": int(observed.argmax()),
            "significant_layers_p_lt_0_05": int((p_values < 0.05).sum()),
            "num_layers": int(len(observed)),
        }
    return rows, summary


def control_groups(features: RouteFeatures) -> dict[str, dict[str, int]]:
    groups: dict[str, dict[str, int]] = defaultdict(dict)
    for index, row in enumerate(features.metadata):
        record = row["metadata"]
        pair_id = record.get("pair_id")
        if pair_id:
            groups[pair_id][record["variant_type"]] = index
    return groups


def aggregate_control_analysis(
    features: RouteFeatures, seed: int
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    groups = control_groups(features)
    originals = original_indices(features)
    by_category: dict[str, list[int]] = defaultdict(list)
    for index in originals:
        category = features.metadata[index]["metadata"]["category"]
        by_category[category].append(int(index))
    rng = np.random.default_rng(seed)
    rows = []
    pair_means: dict[str, list[float]] = defaultdict(list)
    for pair_id in sorted(groups):
        group = groups[pair_id]
        original = group["original"]
        prompt = group["prompt_only"]
        format_variant = group["format_variant"]
        category = features.metadata[original]["metadata"]["category"]
        candidates = [
            index for index in by_category[category] if index != original
        ]
        candidates.sort(
            key=lambda index: (
                abs(int(features.lengths[index]) - int(features.lengths[original])),
                index,
            )
        )
        random_match = int(rng.choice(candidates[: min(10, len(candidates))]))
        comparisons = {
            "original_vs_prompt_only": prompt,
            "original_vs_format_variant": format_variant,
            "original_vs_same_category_random": random_match,
        }
        for comparison, other in comparisons.items():
            distances = js_distance(
                features.weighted_routes[original],
                features.weighted_routes[other],
            )
            pair_means[comparison].append(float(distances.mean()))
            for layer, distance in enumerate(distances):
                rows.append(
                    {
                        "model": features.model_name,
                        "pair_id": pair_id,
                        "base_category": category,
                        "comparison": comparison,
                        "layer": layer,
                        "js_distance": float(distance),
                        "original_length": int(features.lengths[original]),
                        "other_length": int(features.lengths[other]),
                    }
                )
    random_values = np.asarray(
        pair_means["original_vs_same_category_random"], dtype=np.float64
    )
    summary: dict[str, Any] = {}
    for comparison, values_list in pair_means.items():
        values = np.asarray(values_list, dtype=np.float64)
        item = {
            "mean_js_distance": float(values.mean()),
            "median_js_distance": float(np.median(values)),
            "p25": float(np.quantile(values, 0.25)),
            "p75": float(np.quantile(values, 0.75)),
        }
        if comparison != "original_vs_same_category_random":
            statistic = wilcoxon(
                values,
                random_values,
                alternative="less",
                zero_method="wilcox",
            )
            item.update(
                {
                    "mean_ratio_to_random": float(
                        values.mean() / random_values.mean()
                    ),
                    "wilcoxon_less_than_random_statistic": float(
                        statistic.statistic
                    ),
                    "wilcoxon_less_than_random_p_value": float(
                        statistic.pvalue
                    ),
                }
            )
        summary[comparison] = item
    return rows, summary


def prefix_control_analysis(
    features: RouteFeatures,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    wanted: dict[str, tuple[str, str]] = {}
    for row in features.metadata:
        record = row["metadata"]
        pair_id = record.get("pair_id")
        if pair_id and record["variant_type"] in ("original", "prompt_only"):
            wanted[row["id"]] = (pair_id, record["variant_type"])
    pending: dict[str, dict[str, dict[str, torch.Tensor]]] = defaultdict(dict)
    rows: list[dict[str, Any]] = []
    common_prefixes = []
    prefix_ratios = []
    for shard in features.manifest["shards"]:
        metadata_rows = [
            json.loads(line)
            for line in (features.root / shard["metadata_file"]).read_text(
                encoding="utf-8"
            ).splitlines()
            if line
        ]
        with safe_open(
            features.root / shard["tensor_file"], framework="pt", device="cpu"
        ) as tensors:
            lengths = tensors.get_tensor("sequence_lengths").to(torch.int64)
            input_ids = tensors.get_tensor("input_ids").to(torch.int64)
            logits = tensors.get_tensor("router_logits").to(torch.float32)
            topk = tensors.get_tensor("topk_indices").to(torch.int64)
            for row_index, metadata in enumerate(metadata_rows):
                if metadata["id"] not in wanted:
                    continue
                pair_id, variant = wanted[metadata["id"]]
                length = int(lengths[row_index])
                pending[pair_id][variant] = {
                    "input_ids": input_ids[row_index, :length].clone(),
                    "router_logits": logits[row_index, :, :length, :].clone(),
                    "topk_indices": topk[row_index, :, :length, :].clone(),
                }
                if {"original", "prompt_only"} <= set(pending[pair_id]):
                    original = pending[pair_id]["original"]
                    prompt = pending[pair_id]["prompt_only"]
                    limit = min(
                        len(original["input_ids"]), len(prompt["input_ids"])
                    )
                    equality = (
                        original["input_ids"][:limit]
                        == prompt["input_ids"][:limit]
                    )
                    mismatch = torch.nonzero(~equality)
                    common = int(mismatch[0]) if len(mismatch) else limit
                    if common < 2:
                        del pending[pair_id]
                        continue
                    p = torch.softmax(
                        original["router_logits"][:, :common, :], dim=-1
                    )
                    q = torch.softmax(
                        prompt["router_logits"][:, :common, :], dim=-1
                    )
                    midpoint = 0.5 * (p + q)
                    divergence = 0.5 * (
                        (
                            p
                            * (
                                p.clamp_min(EPS).log()
                                - midpoint.clamp_min(EPS).log()
                            )
                        ).sum(dim=-1)
                        + (
                            q
                            * (
                                q.clamp_min(EPS).log()
                                - midpoint.clamp_min(EPS).log()
                            )
                        ).sum(dim=-1)
                    )
                    js = torch.sqrt(
                        torch.clamp(divergence / math.log(2.0), min=0)
                    ).mean(dim=1)
                    topk_a = original["topk_indices"][:, :common, :]
                    topk_b = prompt["topk_indices"][:, :common, :]
                    intersections = (
                        topk_a[..., :, None] == topk_b[..., None, :]
                    ).any(dim=-1).sum(dim=-1).to(torch.float32)
                    jaccard = (intersections / (16.0 - intersections)).mean(
                        dim=1
                    )
                    for layer in range(len(js)):
                        rows.append(
                            {
                                "model": features.model_name,
                                "pair_id": pair_id,
                                "layer": layer,
                                "common_prefix_tokens": common,
                                "soft_router_js_distance": float(js[layer]),
                                "topk_jaccard": float(jaccard[layer]),
                            }
                        )
                    common_prefixes.append(common)
                    prefix_ratios.append(
                        common / min(
                            len(original["input_ids"]), len(prompt["input_ids"])
                        )
                    )
                    del pending[pair_id]
    if pending:
        raise RuntimeError(
            f"Incomplete prefix control groups: {sorted(pending)[:5]}"
        )
    js_values = np.asarray(
        [row["soft_router_js_distance"] for row in rows], dtype=np.float64
    )
    jaccard_values = np.asarray(
        [row["topk_jaccard"] for row in rows], dtype=np.float64
    )
    summary = {
        "pairs": len(common_prefixes),
        "mean_common_prefix_tokens": float(np.mean(common_prefixes)),
        "mean_common_prefix_ratio": float(np.mean(prefix_ratios)),
        "mean_soft_router_js_distance": float(js_values.mean()),
        "mean_topk_jaccard": float(jaccard_values.mean()),
    }
    return rows, summary


def correlation_tree(similarity: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Cluster experts from an exact expert-by-expert correlation matrix."""
    similarity = np.clip(np.asarray(similarity), -1.0, 1.0)
    distance = np.clip((1.0 - similarity) / 2.0, 0.0, 1.0)
    np.fill_diagonal(distance, 0.0)
    condensed = squareform(distance, checks=False)
    tree = linkage(condensed, method="average")
    coph = cophenet(tree)
    if isinstance(coph, tuple):
        coph = coph[-1]
    return tree, np.asarray(coph)


def cluster_stability_analysis(
    features: RouteFeatures, permutations: int, seed: int
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    rng = np.random.default_rng(seed)
    num_layers = int(features.manifest["model"]["num_layers"])
    num_experts = int(features.manifest["model"]["num_experts"])
    scopes = features.moments.scopes
    trees: dict[str, dict[int, list[np.ndarray]]] = {
        scope: {} for scope in scopes
    }
    cophenetic: dict[str, dict[int, list[np.ndarray]]] = {
        scope: {} for scope in scopes
    }
    partitions: dict[str, dict[int, dict[int, list[np.ndarray]]]] = {
        scope: {} for scope in scopes
    }
    for scope in scopes:
        for scale in SCALES:
            correlations = features.moments.correlation(scope, scale)
            trees[scope][scale] = []
            cophenetic[scope][scale] = []
            partitions[scope][scale] = {
                k: [] for k in CLUSTER_COUNTS if k < num_experts
            }
            for layer in range(num_layers):
                tree, coph = correlation_tree(correlations[layer])
                trees[scope][scale].append(tree)
                cophenetic[scope][scale].append(coph)
                for k in partitions[scope][scale]:
                    labels = fcluster(tree, t=k, criterion="maxclust")
                    partitions[scope][scale][k].append(labels)

    adjacent_rows = []
    primary_scope = "all"
    for scale_a, scale_b in zip(SCALES[:-1], SCALES[1:], strict=True):
        for layer in range(num_layers):
            coph_a = cophenetic[primary_scope][scale_a][layer]
            coph_b = cophenetic[primary_scope][scale_b][layer]
            ranked_a = rankdata(coph_a)
            ranked_b = rankdata(coph_b)
            observed_coph = pearson_from_ranked(ranked_a, ranked_b)
            coph_b_matrix = squareform(coph_b)
            null_coph = []
            for _ in range(max(20, permutations // 4)):
                permutation = rng.permutation(num_experts)
                permuted = squareform(
                    coph_b_matrix[np.ix_(permutation, permutation)],
                    checks=False,
                )
                null_coph.append(
                    pearson_from_ranked(ranked_a, rankdata(permuted))
                )
            for k in partitions[primary_scope][scale_a]:
                labels_a = partitions[primary_scope][scale_a][k][layer]
                labels_b = partitions[primary_scope][scale_b][k][layer]
                observed_ari = adjusted_rand(labels_a, labels_b)
                observed_nmi = normalized_mutual_information(labels_a, labels_b)
                null_ari = []
                null_nmi = []
                for _ in range(permutations):
                    permutation = rng.permutation(num_experts)
                    shuffled = labels_b[permutation]
                    null_ari.append(adjusted_rand(labels_a, shuffled))
                    null_nmi.append(
                        normalized_mutual_information(labels_a, shuffled)
                    )
                adjacent_rows.append(
                    {
                        "model": features.model_name,
                        "layer": layer,
                        "scale_a": scale_a,
                        "scale_b": scale_b,
                        "clusters": k,
                        "adjusted_rand": observed_ari,
                        "normalized_mutual_information": observed_nmi,
                        "ari_null_mean": float(np.mean(null_ari)),
                        "ari_permutation_p_value": float(
                            (1 + np.sum(np.asarray(null_ari) >= observed_ari))
                            / (len(null_ari) + 1)
                        ),
                        "nmi_null_mean": float(np.mean(null_nmi)),
                        "nmi_permutation_p_value": float(
                            (1 + np.sum(np.asarray(null_nmi) >= observed_nmi))
                            / (len(null_nmi) + 1)
                        ),
                        "cophenetic_spearman": observed_coph,
                        "cophenetic_null_mean": float(np.mean(null_coph)),
                        "cophenetic_permutation_p_value": float(
                            (1 + np.sum(np.asarray(null_coph) >= observed_coph))
                            / (len(null_coph) + 1)
                        ),
                    }
                )

    replicate_rows = []
    first_scope, second_scope = "split_0", "split_1"
    for scale in SCALES:
        for layer in range(num_layers):
            coph_a = cophenetic[first_scope][scale][layer]
            coph_b = cophenetic[second_scope][scale][layer]
            coph_correlation = pearson_from_ranked(
                rankdata(coph_a), rankdata(coph_b)
            )
            for k in partitions[first_scope][scale]:
                labels_a = partitions[first_scope][scale][k][layer]
                labels_b = partitions[second_scope][scale][k][layer]
                replicate_rows.append(
                    {
                        "model": features.model_name,
                        "layer": layer,
                        "scale": scale,
                        "clusters": k,
                        "split_a": first_scope,
                        "split_b": second_scope,
                        "adjusted_rand": adjusted_rand(labels_a, labels_b),
                        "normalized_mutual_information": normalized_mutual_information(
                            labels_a, labels_b
                        ),
                        "cophenetic_spearman": coph_correlation,
                    }
                )

    order_null_rows = []
    shuffled_scope = "shuffled_all"
    for scale_a, scale_b in zip(SCALES[:-1], SCALES[1:], strict=True):
        for layer in range(num_layers):
            coph_a = cophenetic[shuffled_scope][scale_a][layer]
            coph_b = cophenetic[shuffled_scope][scale_b][layer]
            coph_correlation = pearson_from_ranked(
                rankdata(coph_a), rankdata(coph_b)
            )
            for k in partitions[shuffled_scope][scale_a]:
                labels_a = partitions[shuffled_scope][scale_a][k][layer]
                labels_b = partitions[shuffled_scope][scale_b][k][layer]
                order_null_rows.append(
                    {
                        "model": features.model_name,
                        "layer": layer,
                        "scale_a": scale_a,
                        "scale_b": scale_b,
                        "clusters": k,
                        "adjusted_rand": adjusted_rand(labels_a, labels_b),
                        "normalized_mutual_information": normalized_mutual_information(
                            labels_a, labels_b
                        ),
                        "cophenetic_spearman": coph_correlation,
                    }
                )

    ari_values = np.asarray(
        [row["adjusted_rand"] for row in adjacent_rows], dtype=np.float64
    )
    coph_values = np.asarray(
        [row["cophenetic_spearman"] for row in adjacent_rows],
        dtype=np.float64,
    )
    replicate_ari = np.asarray(
        [row["adjusted_rand"] for row in replicate_rows], dtype=np.float64
    )
    order_null_ari = np.asarray(
        [row["adjusted_rand"] for row in order_null_rows], dtype=np.float64
    )
    order_null_coph = np.asarray(
        [row["cophenetic_spearman"] for row in order_null_rows],
        dtype=np.float64,
    )
    summary = {
        "scales": list(SCALES),
        "cluster_counts": [
            k for k in CLUSTER_COUNTS if k < num_experts
        ],
        "estimator": "exact sample-balanced window covariance",
        "split_seed": features.moments.split_seed,
        "split_sample_counts": {
            scope: features.moments.sample_counts[scope][SCALES[0]]
            for scope in ("split_0", "split_1")
        },
        "mean_adjacent_scale_ari": float(ari_values.mean()),
        "median_adjacent_scale_ari": float(np.median(ari_values)),
        "mean_adjacent_scale_cophenetic_spearman": float(coph_values.mean()),
        "median_adjacent_scale_cophenetic_spearman": float(
            np.median(coph_values)
        ),
        "fraction_adjacent_ari_significant_p_lt_0_05": float(
            np.mean(
                [
                    row["ari_permutation_p_value"] < 0.05
                    for row in adjacent_rows
                ]
            )
        ),
        "fraction_cophenetic_significant_p_lt_0_05": float(
            np.mean(
                [
                    row["cophenetic_permutation_p_value"] < 0.05
                    for row in adjacent_rows
                ]
            )
        ),
        "mean_same_scale_split_half_ari": float(
            replicate_ari.mean()
        ),
        "token_order_null": {
            "mean_adjacent_scale_ari": float(order_null_ari.mean()),
            "mean_adjacent_scale_cophenetic_spearman": float(
                order_null_coph.mean()
            ),
            "observed_minus_null_ari": float(
                ari_values.mean() - order_null_ari.mean()
            ),
            "observed_minus_null_cophenetic_spearman": float(
                coph_values.mean() - order_null_coph.mean()
            ),
        },
    }
    return adjacent_rows, replicate_rows, order_null_rows, summary


def summarize_utilization(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {}
    for route_kind in ("weighted_topk", "top1"):
        selected = [row for row in rows if row["route_kind"] == route_kind]
        effective = np.asarray(
            [row["effective_experts"] for row in selected], dtype=np.float64
        )
        ginis = np.asarray([row["gini"] for row in selected], dtype=np.float64)
        maximum = np.asarray(
            [row["max_expert_share"] for row in selected], dtype=np.float64
        )
        summary[route_kind] = {
            "mean_effective_experts": float(effective.mean()),
            "min_effective_experts": float(effective.min()),
            "min_effective_experts_layer": int(
                selected[int(effective.argmin())]["layer"]
            ),
            "mean_gini": float(ginis.mean()),
            "max_gini": float(ginis.max()),
            "max_gini_layer": int(selected[int(ginis.argmax())]["layer"]),
            "mean_max_expert_share": float(maximum.mean()),
            "max_expert_share": float(maximum.max()),
            "max_expert_share_layer": int(
                selected[int(maximum.argmax())]["layer"]
            ),
        }
    return summary


def analyze_model(
    model_name: str,
    root: Path,
    output_dir: Path,
    permutations: int,
    seed: int,
) -> dict[str, Any]:
    print(f"[load] {model_name}", flush=True)
    features = build_features(model_name, root, seed + 41)
    model_dir = output_dir / model_name
    model_dir.mkdir(parents=True, exist_ok=True)

    print(f"[analyze] {model_name}: utilization", flush=True)
    utilization_rows = utilization_analysis(features)
    write_csv(model_dir / "layer_utilization.csv", utilization_rows)

    print(f"[analyze] {model_name}: category MI", flush=True)
    mi_rows, mi_summary = category_mi_analysis(
        features, permutations, seed + 11
    )
    write_csv(model_dir / "category_mutual_information.csv", mi_rows)

    print(f"[analyze] {model_name}: controls", flush=True)
    control_rows, control_summary = aggregate_control_analysis(
        features, seed + 21
    )
    write_csv(model_dir / "control_route_distances.csv", control_rows)
    prefix_rows, prefix_summary = prefix_control_analysis(features)
    write_csv(model_dir / "prompt_prefix_distances.csv", prefix_rows)

    print(f"[analyze] {model_name}: multiscale clusters", flush=True)
    (
        scale_rows,
        replicate_rows,
        order_null_rows,
        scale_summary,
    ) = cluster_stability_analysis(
        features, permutations, seed + 31
    )
    write_csv(model_dir / "scale_cluster_stability.csv", scale_rows)
    write_csv(model_dir / "scale_split_half_replicability.csv", replicate_rows)
    write_csv(model_dir / "scale_token_order_null.csv", order_null_rows)

    return {
        "model_id": features.manifest["model"]["id"],
        "model_commit": features.manifest["model"]["commit"],
        "samples": features.manifest["completed_samples"],
        "layers": features.manifest["model"]["num_layers"],
        "experts": features.manifest["model"]["num_experts"],
        "utilization": summarize_utilization(utilization_rows),
        "category_mutual_information": mi_summary,
        "controls": {
            "aggregate": control_summary,
            "prompt_prefix": prefix_summary,
        },
        "multiscale_clustering": scale_summary,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--granite",
        type=Path,
        default=Path("artifacts/probe-1k-granite-512-v1.1"),
    )
    parser.add_argument(
        "--olmoe",
        type=Path,
        default=Path("artifacts/probe-1k-olmoe-512-v1.1"),
    )
    parser.add_argument(
        "--output", type=Path, default=Path("analysis/probe-1k-512-v1.1")
    )
    parser.add_argument("--permutations", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260727)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output.exists():
        raise FileExistsError(
            f"Output exists: {args.output}. Choose a new output directory."
        )
    args.output.mkdir(parents=True)
    summary = {
        "schema_version": "route-analysis-v2",
        "dataset": {
            "id": "probe-1k-v1.1",
            "sha256": "a4c7444cbb572a0c88c63ac416fa04f4ceeee22c5f0dd6e56306b822e8345696",
        },
        "parameters": {
            "permutations": args.permutations,
            "scales": list(SCALES),
            "cluster_counts": list(CLUSTER_COUNTS),
            "seed": args.seed,
            "category_prior": "uniform",
            "sample_weighting": "each original sample has equal total routing mass",
            "control_distance": "Jensen-Shannon metric using executed top-k gate weights",
            "cluster_profile": "exact sample-balanced covariance of non-overlapping window-mean executed gate vectors",
        },
        "models": {},
    }
    for model_name, root in (("granite", args.granite), ("olmoe", args.olmoe)):
        summary["models"][model_name] = analyze_model(
            model_name,
            root,
            args.output,
            args.permutations,
            args.seed,
        )
    summary_path = args.output / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary["artifact_sha256"] = hashlib.sha256(summary_path.read_bytes()).hexdigest()
    print(canonical_json(summary["models"]), flush=True)
    print(f"[done] {summary_path}", flush=True)


if __name__ == "__main__":
    main()
