#!/usr/bin/env python3
"""Build split-replicated directed Granite expert-substitution matrices.

For every active layer and source expert i, this script samples token contexts
where i was actually selected by the router.  It then evaluates every expert j
on the same hidden states and defines C(i -> j) as the relative output MSE.
Discovery and confirmatory matrices are estimated independently.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import torch
import torch.nn.functional as F
from safetensors import safe_open
from safetensors.torch import save_file
from scipy.stats import spearmanr
from transformers import AutoModelForCausalLM


SPLITS = ("discovery", "confirmatory")


@dataclass(frozen=True)
class Context:
    sample_index: int
    token_position: int


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"No rows for {path}")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def select_device() -> tuple[torch.device, torch.dtype]:
    if torch.backends.mps.is_available():
        return torch.device("mps"), torch.float16
    return torch.device("cpu"), torch.float32


def active_layers_from_stability(path: Path) -> list[int]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    return sorted(
        int(row["layer"])
        for row in rows
        if row["comparison"] == "cross_split_same_scale"
        and int(row["scale_a"]) == 64
        and int(row["scale_b"]) == 64
        and int(row["clusters"]) == 2
        and float(row["adjusted_rand"]) >= 0.5
        and int(row["min_discovery_cluster_size"]) >= 8
    )


def iter_original_shard_rows(
    root: Path, manifest: dict[str, Any]
) -> Iterator[dict[str, Any]]:
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
            input_ids = tensors.get_tensor("input_ids").to(torch.int64)
            topk_indices = tensors.get_tensor("topk_indices").to(torch.int64)
            for row, metadata in enumerate(metadata_rows):
                record = metadata["metadata"]
                if record["variant_type"] != "original":
                    continue
                length = int(lengths[row])
                yield {
                    "split": record["split"],
                    "sample_index": int(sample_indices[row]),
                    "length": length,
                    "input_ids": input_ids[row, :length].clone(),
                    "topk_indices": topk_indices[row, :, :length, :].clone(),
                }


def reservoir_contexts(
    root: Path,
    manifest: dict[str, Any],
    active_layers: list[int],
    contexts_per_expert: int,
    seed: int,
) -> tuple[
    dict[str, dict[int, dict[int, list[Context]]]],
    dict[str, torch.Tensor],
    dict[int, torch.Tensor],
    dict[int, str],
]:
    """Sample across documents, with at most one candidate token/document/expert."""
    num_layers = int(manifest["model"]["num_layers"])
    num_experts = int(manifest["model"]["num_experts"])
    reservoirs = {
        split: {
            layer: {expert: [] for expert in range(num_experts)}
            for layer in active_layers
        }
        for split in SPLITS
    }
    document_counts = {
        split: torch.zeros((num_layers, num_experts), dtype=torch.int64)
        for split in SPLITS
    }
    token_counts = {
        split: torch.zeros((num_layers, num_experts), dtype=torch.int64)
        for split in SPLITS
    }
    rngs = {
        (split, layer, expert): np.random.default_rng(
            seed
            + 1_000_003 * SPLITS.index(split)
            + 10_007 * layer
            + 101 * expert
        )
        for split in SPLITS
        for layer in active_layers
        for expert in range(num_experts)
    }
    input_ids_by_sample: dict[int, torch.Tensor] = {}
    split_by_sample: dict[int, str] = {}
    sample_counter = defaultdict(int)
    for sample in iter_original_shard_rows(root, manifest):
        split = sample["split"]
        if split not in SPLITS:
            continue
        sample_index = sample["sample_index"]
        input_ids_by_sample[sample_index] = sample["input_ids"]
        split_by_sample[sample_index] = split
        sample_counter[split] += 1
        routes = sample["topk_indices"]
        for layer in active_layers:
            indices = routes[layer].numpy()
            token_counts[split][layer] += torch.from_numpy(
                np.bincount(indices.reshape(-1), minlength=num_experts)
            )
            for expert in range(num_experts):
                positions = np.flatnonzero((indices == expert).any(axis=1))
                if not len(positions):
                    continue
                document_counts[split][layer, expert] += 1
                rng = rngs[(split, layer, expert)]
                token_position = int(positions[rng.integers(len(positions))])
                candidate = Context(sample_index, token_position)
                reservoir = reservoirs[split][layer][expert]
                seen = int(document_counts[split][layer, expert])
                if len(reservoir) < contexts_per_expert:
                    reservoir.append(candidate)
                else:
                    replacement = int(rng.integers(seen))
                    if replacement < contexts_per_expert:
                        reservoir[replacement] = candidate
        total = sample_counter["discovery"] + sample_counter["confirmatory"]
        if total % 100 == 0:
            print(
                f"[sample-contexts] originals={total} "
                f"discovery={sample_counter['discovery']} "
                f"confirmatory={sample_counter['confirmatory']}",
                flush=True,
            )
    return (
        reservoirs,
        token_counts,
        input_ids_by_sample,
        split_by_sample,
    )


class HiddenCapture:
    def __init__(
        self,
        contexts: dict[str, dict[int, dict[int, list[Context]]]],
        active_layers: list[int],
    ) -> None:
        self.active_layers = set(active_layers)
        self.current_samples: list[int] = []
        self.positions: dict[int, dict[int, set[int]]] = defaultdict(
            lambda: defaultdict(set)
        )
        self.hidden: dict[tuple[int, int, int], torch.Tensor] = {}
        for by_layer in contexts.values():
            for layer, by_expert in by_layer.items():
                for selected in by_expert.values():
                    for context in selected:
                        self.positions[context.sample_index][layer].add(
                            context.token_position
                        )

    def hook(self, layer: int):
        def capture(
            module: torch.nn.Module,
            args: tuple[torch.Tensor, ...],
        ) -> None:
            del module
            hidden_states = args[0]
            for batch_row, sample_index in enumerate(self.current_samples):
                positions = sorted(self.positions[sample_index].get(layer, ()))
                if not positions:
                    continue
                values = (
                    hidden_states[batch_row, positions]
                    .detach()
                    .to(device="cpu", dtype=torch.float32)
                )
                for token_position, value in zip(positions, values, strict=True):
                    self.hidden[(layer, sample_index, token_position)] = value

        return capture


def capture_hidden_states(
    model: torch.nn.Module,
    device: torch.device,
    input_ids_by_sample: dict[int, torch.Tensor],
    capture: HiddenCapture,
    active_layers: list[int],
    batch_size: int,
) -> None:
    handles = [
        model.model.layers[layer].block_sparse_moe.register_forward_pre_hook(
            capture.hook(layer)
        )
        for layer in active_layers
    ]
    selected_samples = sorted(
        capture.positions,
        key=lambda index: len(input_ids_by_sample[index]),
    )
    started = time.perf_counter()
    try:
        for start in range(0, len(selected_samples), batch_size):
            batch_samples = selected_samples[start : start + batch_size]
            capture.current_samples = batch_samples
            lengths = [len(input_ids_by_sample[index]) for index in batch_samples]
            max_length = max(lengths)
            input_ids = torch.zeros(
                (len(batch_samples), max_length), dtype=torch.int64
            )
            attention_mask = torch.zeros_like(input_ids)
            for row, sample_index in enumerate(batch_samples):
                values = input_ids_by_sample[sample_index]
                input_ids[row, : len(values)] = values
                attention_mask[row, : len(values)] = 1
            with torch.inference_mode():
                model(
                    input_ids=input_ids.to(device),
                    attention_mask=attention_mask.to(device),
                    use_cache=False,
                    return_dict=True,
                    logits_to_keep=1,
                )
            completed = min(start + batch_size, len(selected_samples))
            if completed % max(20, batch_size) < batch_size:
                elapsed = time.perf_counter() - started
                print(
                    f"[capture] samples={completed}/{len(selected_samples)} "
                    f"hidden={len(capture.hidden)} seconds={elapsed:.1f}",
                    flush=True,
                )
    finally:
        for handle in handles:
            handle.remove()
        capture.current_samples = []


def all_expert_outputs(
    moe: torch.nn.Module, hidden_states: torch.Tensor
) -> torch.Tensor:
    """Return [contexts, experts, hidden] raw expert outputs."""
    contexts = hidden_states.shape[0]
    experts = moe.router.num_experts
    expert_inputs = hidden_states.repeat(experts, 1)
    expert_size = [contexts] * experts
    projected = moe.input_linear(expert_inputs, expert_size)
    gate, value = projected.chunk(2, dim=-1)
    activated = moe.activation(gate) * value
    outputs = moe.output_linear(activated, expert_size)
    return outputs.view(experts, contexts, -1).transpose(0, 1)


def build_costs(
    model: torch.nn.Module,
    contexts: dict[str, dict[int, dict[int, list[Context]]]],
    hidden: dict[tuple[int, int, int], torch.Tensor],
    active_layers: list[int],
    num_layers: int,
    num_experts: int,
) -> dict[str, torch.Tensor]:
    relative_mse = {
        split: torch.full(
            (num_layers, num_experts, num_experts),
            float("nan"),
            dtype=torch.float32,
        )
        for split in SPLITS
    }
    cosine_distance = {
        split: torch.full_like(relative_mse[split], float("nan"))
        for split in SPLITS
    }
    context_counts = {
        split: torch.zeros((num_layers, num_experts), dtype=torch.int64)
        for split in SPLITS
    }
    with torch.inference_mode():
        for layer in active_layers:
            moe = model.model.layers[layer].block_sparse_moe
            for split in SPLITS:
                for source in range(num_experts):
                    selected = contexts[split][layer][source]
                    if not selected:
                        continue
                    states = torch.stack(
                        [
                            hidden[
                                (
                                    layer,
                                    context.sample_index,
                                    context.token_position,
                                )
                            ]
                            for context in selected
                        ]
                    ).to(
                        device=next(moe.parameters()).device,
                        dtype=next(moe.parameters()).dtype,
                    )
                    outputs = all_expert_outputs(moe, states).float()
                    source_outputs = outputs[:, source : source + 1, :]
                    squared_error = (
                        (outputs - source_outputs).square().sum(dim=-1)
                    )
                    source_energy = (
                        source_outputs.square().sum(dim=-1).clamp_min(1e-12)
                    )
                    relative_mse[split][layer, source] = (
                        squared_error / source_energy
                    ).mean(dim=0).cpu()
                    cosine_distance[split][layer, source] = (
                        1.0
                        - F.cosine_similarity(
                            outputs,
                            source_outputs.expand_as(outputs),
                            dim=-1,
                            eps=1e-8,
                        )
                    ).mean(dim=0).cpu()
                    context_counts[split][layer, source] = len(selected)
            print(
                f"[costs] layer={layer} "
                f"completed={active_layers.index(layer)+1}/{len(active_layers)}",
                flush=True,
            )
    result = {}
    for split in SPLITS:
        result[f"relative_mse_{split}"] = relative_mse[split]
        result[f"cosine_distance_{split}"] = cosine_distance[split]
        result[f"context_counts_{split}"] = context_counts[split]
    return result


def rank_reproducibility(
    discovery: np.ndarray,
    confirmatory: np.ndarray,
    active_layers: list[int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = []
    source_correlations = []
    top1_matches = []
    top5_overlaps = []
    layer_correlations = []
    positive_layers = 0
    num_experts = discovery.shape[-1]
    for layer in active_layers:
        layer_source_corr = []
        layer_top1 = []
        layer_top5 = []
        off_diagonal = ~np.eye(num_experts, dtype=bool)
        valid_matrix = (
            off_diagonal
            & np.isfinite(discovery[layer])
            & np.isfinite(confirmatory[layer])
        )
        layer_corr = float(
            spearmanr(
                discovery[layer][valid_matrix],
                confirmatory[layer][valid_matrix],
            ).statistic
        )
        layer_correlations.append(layer_corr)
        positive_layers += int(layer_corr > 0)
        for source in range(num_experts):
            if not (
                np.isfinite(discovery[layer, source]).all()
                and np.isfinite(confirmatory[layer, source]).all()
            ):
                continue
            targets = np.arange(num_experts) != source
            d = discovery[layer, source, targets]
            c = confirmatory[layer, source, targets]
            corr = float(spearmanr(d, c).statistic)
            candidate_ids = np.arange(num_experts)[targets]
            d_order = candidate_ids[np.argsort(d)]
            c_order = candidate_ids[np.argsort(c)]
            top1 = float(d_order[0] == c_order[0])
            top5 = len(set(d_order[:5]) & set(c_order[:5])) / 5.0
            layer_source_corr.append(corr)
            layer_top1.append(top1)
            layer_top5.append(top5)
        source_correlations.extend(layer_source_corr)
        top1_matches.extend(layer_top1)
        top5_overlaps.extend(layer_top5)
        asymmetry = np.abs(
            discovery[layer] - discovery[layer].T
        )[valid_matrix & valid_matrix.T]
        magnitude = (
            np.abs(discovery[layer])
            + np.abs(discovery[layer].T)
        )[valid_matrix & valid_matrix.T]
        rows.append(
            {
                "layer": layer,
                "matrix_spearman": layer_corr,
                "median_source_spearman": float(
                    np.nanmedian(layer_source_corr)
                ),
                "mean_source_spearman": float(np.nanmean(layer_source_corr)),
                "top1_agreement": float(np.mean(layer_top1)),
                "top5_overlap_fraction": float(np.mean(layer_top5)),
                "directed_asymmetry_ratio": float(
                    np.mean(asymmetry / np.maximum(magnitude, 1e-12))
                ),
            }
        )
    median_source = float(np.nanmedian(source_correlations))
    mean_top5 = float(np.mean(top5_overlaps))
    positive_fraction = positive_layers / len(active_layers)
    thresholds = {
        "median_source_spearman_min": 0.30,
        "mean_top5_overlap_fraction_min": 0.25,
        "positive_layer_matrix_spearman_fraction_min": 0.75,
    }
    passed = (
        median_source >= thresholds["median_source_spearman_min"]
        and mean_top5 >= thresholds["mean_top5_overlap_fraction_min"]
        and positive_fraction
        >= thresholds["positive_layer_matrix_spearman_fraction_min"]
    )
    summary = {
        "active_layers": active_layers,
        "layer_count": len(active_layers),
        "source_layer_pairs": len(source_correlations),
        "median_source_spearman": median_source,
        "mean_source_spearman": float(np.nanmean(source_correlations)),
        "mean_layer_matrix_spearman": float(np.nanmean(layer_correlations)),
        "median_layer_matrix_spearman": float(
            np.nanmedian(layer_correlations)
        ),
        "positive_layer_matrix_spearman_fraction": positive_fraction,
        "top1_agreement": float(np.mean(top1_matches)),
        "top5_overlap_fraction": mean_top5,
        "random_top1_agreement": 1.0 / (num_experts - 1),
        "random_top5_overlap_fraction": 5.0 / (num_experts - 1),
        "thresholds_frozen_before_evaluation": thresholds,
        "passed": passed,
    }
    return rows, summary


def context_rows(
    contexts: dict[str, dict[int, dict[int, list[Context]]]]
) -> list[dict[str, Any]]:
    rows = []
    for split in SPLITS:
        for layer, by_expert in contexts[split].items():
            for expert, selected in by_expert.items():
                for rank, context in enumerate(selected):
                    rows.append(
                        {
                            "split": split,
                            "layer": layer,
                            "source_expert": expert,
                            "context_rank": rank,
                            "sample_index": context.sample_index,
                            "token_position": context.token_position,
                        }
                    )
    return rows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact",
        type=Path,
        default=Path("artifacts/probe-1k-granite-512-v1.1"),
    )
    parser.add_argument(
        "--stability",
        type=Path,
        default=Path(
            "analysis/expert-alliances-v1/alliance_stability_by_layer.csv"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("analysis/substitution-matrix-v1"),
    )
    parser.add_argument("--contexts-per-expert", type=int, default=4)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260727)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(
        (args.artifact / "manifest.json").read_text(encoding="utf-8")
    )
    active_layers = active_layers_from_stability(args.stability)
    num_layers = int(manifest["model"]["num_layers"])
    num_experts = int(manifest["model"]["num_experts"])
    started = time.perf_counter()
    contexts, token_counts, input_ids, split_by_sample = reservoir_contexts(
        args.artifact,
        manifest,
        active_layers,
        args.contexts_per_expert,
        args.seed,
    )
    del split_by_sample
    observed_context_counts = [
        len(contexts[split][layer][expert])
        for split in SPLITS
        for layer in active_layers
        for expert in range(num_experts)
        if contexts[split][layer][expert]
    ]
    minimum = min(observed_context_counts)
    if minimum < args.contexts_per_expert:
        raise RuntimeError(
            f"Only {minimum} contexts available for at least one expert."
        )
    selected = {
        context.sample_index
        for split in SPLITS
        for layer in active_layers
        for expert in range(num_experts)
        for context in contexts[split][layer][expert]
    }
    sampled_context_count = sum(
        len(contexts[split][layer][expert])
        for split in SPLITS
        for layer in active_layers
        for expert in range(num_experts)
    )
    print(
        f"[sampled] contexts={sampled_context_count} "
        f"unique_samples={len(selected)} active_layers={active_layers}",
        flush=True,
    )
    write_csv(args.output / "sampled_contexts.csv", context_rows(contexts))

    device, dtype = select_device()
    print(f"[load] device={device} dtype={dtype}", flush=True)
    model = AutoModelForCausalLM.from_pretrained(
        manifest["model"]["id"],
        revision=manifest["model"]["commit"],
        dtype=dtype,
        low_cpu_mem_usage=True,
        local_files_only=True,
    )
    model.to(device)
    model.eval()
    capture = HiddenCapture(contexts, active_layers)
    capture_hidden_states(
        model,
        device,
        input_ids,
        capture,
        active_layers,
        args.batch_size,
    )
    expected_hidden = len(
        {
            (layer, context.sample_index, context.token_position)
            for split in SPLITS
            for layer in active_layers
            for expert in range(num_experts)
            for context in contexts[split][layer][expert]
        }
    )
    if len(capture.hidden) != expected_hidden:
        raise RuntimeError(
            f"Captured {len(capture.hidden)} hidden states, expected "
            f"{expected_hidden}."
        )
    matrices = build_costs(
        model,
        contexts,
        capture.hidden,
        active_layers,
        num_layers,
        num_experts,
    )
    for split in SPLITS:
        matrices[f"selection_counts_{split}"] = token_counts[split]
    save_file(matrices, args.output / "substitution_matrices.safetensors")
    rows, reproducibility = rank_reproducibility(
        matrices["relative_mse_discovery"].numpy(),
        matrices["relative_mse_confirmatory"].numpy(),
        active_layers,
    )
    write_csv(args.output / "reproducibility_by_layer.csv", rows)
    (args.output / "reproducibility_summary.json").write_text(
        json.dumps(reproducibility, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    metadata = {
        "schema_version": "directed-expert-substitution-v1",
        "model_id": manifest["model"]["id"],
        "model_commit": manifest["model"]["commit"],
        "definition": (
            "C(i->j) is mean ||f_j(h)-f_i(h)||^2/||f_i(h)||^2 on "
            "document-balanced token contexts where source expert i was "
            "selected by the original top-k router."
        ),
        "active_layer_rule": (
            "Frozen alliance validation: discovery-vs-confirmatory ARI >= 0.5 "
            "at block 64, k=2, with discovery minimum cluster size >= 8."
        ),
        "active_layers": active_layers,
        "contexts_per_expert_per_split": args.contexts_per_expert,
        "sampled_contexts": sampled_context_count,
        "unobserved_source_experts": {
            split: {
                str(layer): [
                    expert
                    for expert in range(num_experts)
                    if not contexts[split][layer][expert]
                ]
                for layer in active_layers
                if any(
                    not contexts[split][layer][expert]
                    for expert in range(num_experts)
                )
            }
            for split in SPLITS
        },
        "sampling_seed": args.seed,
        "unique_samples_forwarded": len(selected),
        "unique_hidden_states": len(capture.hidden),
        "elapsed_seconds": time.perf_counter() - started,
        "reproducibility_passed": reproducibility["passed"],
    }
    (args.output / "manifest.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"[complete] output={args.output} passed={reproducibility['passed']} "
        f"median_source_spearman="
        f"{reproducibility['median_source_spearman']:.4f} "
        f"top5_overlap={reproducibility['top5_overlap_fraction']:.4f} "
        f"seconds={metadata['elapsed_seconds']:.1f}",
        flush=True,
    )


if __name__ == "__main__":
    main()
