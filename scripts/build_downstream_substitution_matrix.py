#!/usr/bin/env python3
"""Build split-replicated, downstream-sensitive expert substitution costs."""

from __future__ import annotations

import argparse
import csv
import json
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

from build_substitution_matrix import (
    active_layers_from_stability,
    all_expert_outputs,
    select_device,
    write_csv,
)


SPLITS = ("discovery", "confirmatory")


@dataclass(frozen=True)
class WeightedContext:
    sample_index: int
    token_position: int
    gate_weight: float


def iter_original_rows(
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
            topk_weights = tensors.get_tensor("topk_weights").to(torch.float32)
            for row, metadata in enumerate(metadata_rows):
                record = metadata["metadata"]
                if record["variant_type"] != "original":
                    continue
                length = int(lengths[row])
                yield {
                    "split": record["split"],
                    "sample_index": int(sample_indices[row]),
                    "input_ids": input_ids[row, :length].clone(),
                    "topk_indices": topk_indices[row, :, :length, :].clone(),
                    "topk_weights": topk_weights[row, :, :length, :].clone(),
                }


def sample_contexts(
    root: Path,
    manifest: dict[str, Any],
    active_layers: list[int],
    contexts_per_expert: int,
    seed: int,
) -> tuple[
    dict[str, dict[int, dict[int, list[WeightedContext]]]],
    dict[str, torch.Tensor],
    dict[str, torch.Tensor],
    dict[int, torch.Tensor],
]:
    """Document-balanced reservoir sampling, excluding final sequence tokens."""
    num_layers = int(manifest["model"]["num_layers"])
    num_experts = int(manifest["model"]["num_experts"])
    contexts = {
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
    selection_counts = {
        split: torch.zeros((num_layers, num_experts), dtype=torch.int64)
        for split in SPLITS
    }
    gate_mass = {
        split: torch.zeros((num_layers, num_experts), dtype=torch.float64)
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
    input_ids_by_sample = {}
    split_counts = defaultdict(int)
    for sample in iter_original_rows(root, manifest):
        split = sample["split"]
        sample_index = sample["sample_index"]
        input_ids_by_sample[sample_index] = sample["input_ids"]
        split_counts[split] += 1
        # The final hidden position has no next-token NLL in teacher forcing.
        indices_by_layer = sample["topk_indices"][:, :-1, :]
        weights_by_layer = sample["topk_weights"][:, :-1, :]
        for layer in active_layers:
            indices = indices_by_layer[layer].numpy()
            weights = weights_by_layer[layer].numpy()
            selection_counts[split][layer] += torch.from_numpy(
                np.bincount(indices.reshape(-1), minlength=num_experts)
            )
            gate_mass[split][layer].scatter_add_(
                0,
                torch.from_numpy(indices.reshape(-1)),
                torch.from_numpy(weights.reshape(-1)).to(torch.float64),
            )
            for expert in range(num_experts):
                token_positions, ranks = np.nonzero(indices == expert)
                if not len(token_positions):
                    continue
                document_counts[split][layer, expert] += 1
                rng = rngs[(split, layer, expert)]
                choice = int(rng.integers(len(token_positions)))
                candidate = WeightedContext(
                    sample_index=sample_index,
                    token_position=int(token_positions[choice]),
                    gate_weight=float(weights[token_positions[choice], ranks[choice]]),
                )
                reservoir = contexts[split][layer][expert]
                seen = int(document_counts[split][layer, expert])
                if len(reservoir) < contexts_per_expert:
                    reservoir.append(candidate)
                else:
                    replacement = int(rng.integers(seen))
                    if replacement < contexts_per_expert:
                        reservoir[replacement] = candidate
        total = sum(split_counts.values())
        if total % 100 == 0:
            print(
                f"[sample-contexts] originals={total} "
                f"discovery={split_counts['discovery']} "
                f"confirmatory={split_counts['confirmatory']}",
                flush=True,
            )
    return contexts, selection_counts, gate_mass, input_ids_by_sample


class GradientCapture:
    def __init__(
        self,
        contexts: dict[
            str, dict[int, dict[int, list[WeightedContext]]]
        ],
    ) -> None:
        self.positions: dict[int, dict[int, set[int]]] = defaultdict(
            lambda: defaultdict(set)
        )
        for split in SPLITS:
            for layer, by_expert in contexts[split].items():
                for selected in by_expert.values():
                    for context in selected:
                        self.positions[context.sample_index][layer].add(
                            context.token_position
                        )
        self.inputs: dict[int, torch.Tensor] = {}
        self.outputs: dict[int, torch.Tensor] = {}
        self.hidden: dict[tuple[int, int, int], torch.Tensor] = {}
        self.gradients: dict[tuple[int, int, int], torch.Tensor] = {}
        self.current_samples: list[int] = []

    @staticmethod
    def embedding_hook(
        module: torch.nn.Module,
        args: tuple[torch.Tensor, ...],
        output: torch.Tensor,
    ) -> torch.Tensor:
        del module, args
        return output.detach().requires_grad_(True)

    def input_hook(
        self, layer: int
    ):
        def capture(
            module: torch.nn.Module, args: tuple[torch.Tensor, ...]
        ) -> None:
            del module
            self.inputs[layer] = args[0]

        return capture

    def output_hook(self, layer: int):
        def capture(
            module: torch.nn.Module,
            args: tuple[torch.Tensor, ...],
            output: tuple[torch.Tensor, torch.Tensor],
        ) -> None:
            del module, args
            output[0].retain_grad()
            self.outputs[layer] = output[0]

        return capture

    def extract_batch(self, active_layers: list[int]) -> None:
        for layer in active_layers:
            layer_input = self.inputs[layer]
            layer_gradient = self.outputs[layer].grad
            if layer_gradient is None:
                raise RuntimeError(f"Missing output gradient for layer {layer}.")
            for batch_row, sample_index in enumerate(self.current_samples):
                positions = sorted(self.positions[sample_index].get(layer, ()))
                if not positions:
                    continue
                hidden_values = layer_input[batch_row, positions].detach().to(
                    device="cpu", dtype=torch.float32
                )
                gradient_values = layer_gradient[
                    batch_row, positions
                ].detach().to(device="cpu", dtype=torch.float32)
                for position, hidden, gradient in zip(
                    positions,
                    hidden_values,
                    gradient_values,
                    strict=True,
                ):
                    key = (layer, sample_index, position)
                    self.hidden[key] = hidden
                    self.gradients[key] = gradient
        self.inputs.clear()
        self.outputs.clear()


def capture_gradients(
    model: torch.nn.Module,
    device: torch.device,
    input_ids_by_sample: dict[int, torch.Tensor],
    capture: GradientCapture,
    active_layers: list[int],
    batch_size: int,
) -> None:
    model.requires_grad_(False)
    handles = [
        model.model.embed_tokens.register_forward_hook(
            capture.embedding_hook
        )
    ]
    for layer in active_layers:
        moe = model.model.layers[layer].block_sparse_moe
        handles.append(
            moe.register_forward_pre_hook(capture.input_hook(layer))
        )
        handles.append(moe.register_forward_hook(capture.output_hook(layer)))
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
            input_ids = input_ids.to(device)
            attention_mask = attention_mask.to(device)
            outputs = model(
                input_ids=input_ids,
                attention_mask=attention_mask,
                use_cache=False,
                return_dict=True,
                logits_to_keep=0,
            )
            token_losses = F.cross_entropy(
                outputs.logits[:, :-1, :].float().transpose(1, 2),
                input_ids[:, 1:],
                reduction="none",
            )
            loss_mask = attention_mask[:, 1:].to(token_losses.dtype)
            per_document_mean = (
                (token_losses * loss_mask).sum(dim=1)
                / loss_mask.sum(dim=1).clamp_min(1)
            )
            per_document_mean.sum().backward()
            capture.extract_batch(active_layers)
            del outputs, token_losses, per_document_mean, input_ids
            del attention_mask, loss_mask
            completed = min(start + batch_size, len(selected_samples))
            if completed % max(20, batch_size) < batch_size:
                elapsed = time.perf_counter() - started
                print(
                    f"[gradients] samples={completed}/{len(selected_samples)} "
                    f"contexts={len(capture.hidden)} seconds={elapsed:.1f}",
                    flush=True,
                )
    finally:
        for handle in handles:
            handle.remove()
        capture.current_samples = []


def build_costs(
    model: torch.nn.Module,
    contexts: dict[str, dict[int, dict[int, list[WeightedContext]]]],
    capture: GradientCapture,
    active_layers: list[int],
    num_layers: int,
    num_experts: int,
) -> dict[str, torch.Tensor]:
    metric_names = (
        "diagonal_fisher",
        "gradient_projection_squared",
        "absolute_first_order",
        "relative_mse",
    )
    matrices = {
        f"{metric}_{split}": torch.full(
            (num_layers, num_experts, num_experts),
            float("nan"),
            dtype=torch.float32,
        )
        for metric in metric_names
        for split in SPLITS
    }
    context_counts = {
        split: torch.zeros((num_layers, num_experts), dtype=torch.int64)
        for split in SPLITS
    }
    with torch.inference_mode():
        for layer_position, layer in enumerate(active_layers, start=1):
            moe = model.model.layers[layer].block_sparse_moe
            parameter = next(moe.parameters())
            for split in SPLITS:
                for source in range(num_experts):
                    selected = contexts[split][layer][source]
                    if not selected:
                        continue
                    keys = [
                        (
                            layer,
                            context.sample_index,
                            context.token_position,
                        )
                        for context in selected
                    ]
                    hidden_states = torch.stack(
                        [capture.hidden[key] for key in keys]
                    ).to(device=parameter.device, dtype=parameter.dtype)
                    gradients = torch.stack(
                        [capture.gradients[key] for key in keys]
                    ).to(device=parameter.device, dtype=torch.float32)
                    gate_weights = torch.tensor(
                        [context.gate_weight for context in selected],
                        dtype=torch.float32,
                        device=parameter.device,
                    )
                    outputs = all_expert_outputs(moe, hidden_states).float()
                    source_outputs = outputs[:, source : source + 1, :]
                    delta = outputs - source_outputs
                    effective_delta = (
                        delta * gate_weights[:, None, None]
                    )
                    gradient_products = (
                        gradients[:, None, :] * effective_delta
                    )
                    matrices[f"diagonal_fisher_{split}"][
                        layer, source
                    ] = (
                        gradient_products.square().sum(dim=-1).mean(dim=0).cpu()
                    )
                    matrices[f"gradient_projection_squared_{split}"][
                        layer, source
                    ] = (
                        gradient_products.sum(dim=-1).square().mean(dim=0).cpu()
                    )
                    matrices[f"absolute_first_order_{split}"][
                        layer, source
                    ] = (
                        gradient_products.sum(dim=-1).abs().mean(dim=0).cpu()
                    )
                    squared_error = delta.square().sum(dim=-1)
                    source_energy = (
                        source_outputs.square().sum(dim=-1).clamp_min(1e-12)
                    )
                    matrices[f"relative_mse_{split}"][
                        layer, source
                    ] = (squared_error / source_energy).mean(dim=0).cpu()
                    context_counts[split][layer, source] = len(selected)
            print(
                f"[costs] layer={layer} "
                f"completed={layer_position}/{len(active_layers)}",
                flush=True,
            )
    for split in SPLITS:
        matrices[f"context_counts_{split}"] = context_counts[split]
    return matrices


def reproducibility(
    discovery: np.ndarray,
    confirmatory: np.ndarray,
    active_layers: list[int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    num_experts = discovery.shape[-1]
    rows = []
    source_correlations = []
    top1_matches = []
    top5_overlaps = []
    layer_correlations = []
    for layer in active_layers:
        off_diagonal = ~np.eye(num_experts, dtype=bool)
        valid = (
            off_diagonal
            & np.isfinite(discovery[layer])
            & np.isfinite(confirmatory[layer])
        )
        layer_corr = float(
            spearmanr(
                discovery[layer][valid],
                confirmatory[layer][valid],
            ).statistic
        )
        layer_correlations.append(layer_corr)
        local_corr = []
        local_top1 = []
        local_top5 = []
        for source in range(num_experts):
            if not (
                np.isfinite(discovery[layer, source]).all()
                and np.isfinite(confirmatory[layer, source]).all()
            ):
                continue
            targets = np.arange(num_experts) != source
            ids = np.arange(num_experts)[targets]
            d = discovery[layer, source, targets]
            c = confirmatory[layer, source, targets]
            corr = float(spearmanr(d, c).statistic)
            d_order = ids[np.argsort(d)]
            c_order = ids[np.argsort(c)]
            top1 = float(d_order[0] == c_order[0])
            top5 = len(set(d_order[:5]) & set(c_order[:5])) / 5.0
            local_corr.append(corr)
            local_top1.append(top1)
            local_top5.append(top5)
        source_correlations.extend(local_corr)
        top1_matches.extend(local_top1)
        top5_overlaps.extend(local_top5)
        rows.append(
            {
                "layer": layer,
                "matrix_spearman": layer_corr,
                "median_source_spearman": float(np.median(local_corr)),
                "mean_source_spearman": float(np.mean(local_corr)),
                "top1_agreement": float(np.mean(local_top1)),
                "top5_overlap_fraction": float(np.mean(local_top5)),
            }
        )
    thresholds = {
        "median_source_spearman_min": 0.30,
        "mean_top5_overlap_fraction_min": 0.25,
        "positive_layer_matrix_spearman_fraction_min": 0.75,
    }
    summary = {
        "active_layers": active_layers,
        "source_layer_pairs": len(source_correlations),
        "median_source_spearman": float(np.median(source_correlations)),
        "mean_source_spearman": float(np.mean(source_correlations)),
        "mean_layer_matrix_spearman": float(np.mean(layer_correlations)),
        "positive_layer_matrix_spearman_fraction": float(
            np.mean(np.asarray(layer_correlations) > 0)
        ),
        "top1_agreement": float(np.mean(top1_matches)),
        "top5_overlap_fraction": float(np.mean(top5_overlaps)),
        "random_top1_agreement": 1.0 / (num_experts - 1),
        "random_top5_overlap_fraction": 5.0 / (num_experts - 1),
        "thresholds_frozen_before_evaluation": thresholds,
    }
    summary["passed"] = (
        summary["median_source_spearman"]
        >= thresholds["median_source_spearman_min"]
        and summary["top5_overlap_fraction"]
        >= thresholds["mean_top5_overlap_fraction_min"]
        and summary["positive_layer_matrix_spearman_fraction"]
        >= thresholds["positive_layer_matrix_spearman_fraction_min"]
    )
    return rows, summary


def context_rows(
    contexts: dict[str, dict[int, dict[int, list[WeightedContext]]]]
) -> list[dict[str, Any]]:
    rows = []
    for split in SPLITS:
        for layer, by_expert in contexts[split].items():
            for source, selected in by_expert.items():
                for rank, context in enumerate(selected):
                    rows.append(
                        {
                            "split": split,
                            "layer": layer,
                            "source_expert": source,
                            "context_rank": rank,
                            "sample_index": context.sample_index,
                            "token_position": context.token_position,
                            "gate_weight": context.gate_weight,
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
        default=Path("analysis/downstream-substitution-matrix-v1"),
    )
    parser.add_argument("--contexts-per-expert", type=int, default=8)
    parser.add_argument("--batch-size", type=int, default=2)
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
    contexts, selection_counts, gate_mass, input_ids = sample_contexts(
        args.artifact,
        manifest,
        active_layers,
        args.contexts_per_expert,
        args.seed + 1709,
    )
    observed = [
        len(contexts[split][layer][expert])
        for split in SPLITS
        for layer in active_layers
        for expert in range(num_experts)
        if contexts[split][layer][expert]
    ]
    if min(observed) < args.contexts_per_expert:
        raise RuntimeError(
            f"Only {min(observed)} contexts for an observed source expert."
        )
    sampled_context_count = sum(observed)
    selected_samples = {
        context.sample_index
        for split in SPLITS
        for layer in active_layers
        for expert in range(num_experts)
        for context in contexts[split][layer][expert]
    }
    write_csv(args.output / "sampled_contexts.csv", context_rows(contexts))
    print(
        f"[sampled] contexts={sampled_context_count} "
        f"unique_samples={len(selected_samples)}",
        flush=True,
    )

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
    capture = GradientCapture(contexts)
    capture_gradients(
        model,
        device,
        input_ids,
        capture,
        active_layers,
        args.batch_size,
    )
    expected = len(
        {
            (layer, context.sample_index, context.token_position)
            for split in SPLITS
            for layer in active_layers
            for expert in range(num_experts)
            for context in contexts[split][layer][expert]
        }
    )
    if len(capture.hidden) != expected or len(capture.gradients) != expected:
        raise RuntimeError(
            f"Capture mismatch: hidden={len(capture.hidden)} "
            f"gradient={len(capture.gradients)} expected={expected}."
        )
    matrices = build_costs(
        model,
        contexts,
        capture,
        active_layers,
        num_layers,
        num_experts,
    )
    for split in SPLITS:
        matrices[f"selection_counts_{split}"] = selection_counts[split]
        matrices[f"gate_mass_{split}"] = gate_mass[split].to(torch.float32)
    save_file(
        matrices,
        args.output / "downstream_substitution_matrices.safetensors",
    )
    rows, summary = reproducibility(
        matrices["diagonal_fisher_discovery"].numpy(),
        matrices["diagonal_fisher_confirmatory"].numpy(),
        active_layers,
    )
    write_csv(args.output / "reproducibility_by_layer.csv", rows)
    metric_summary_rows = []
    for metric in (
        "diagonal_fisher",
        "gradient_projection_squared",
        "absolute_first_order",
        "relative_mse",
    ):
        _, metric_summary = reproducibility(
            matrices[f"{metric}_discovery"].numpy(),
            matrices[f"{metric}_confirmatory"].numpy(),
            active_layers,
        )
        metric_summary_rows.append(
            {
                "metric": metric,
                "median_source_spearman": (
                    metric_summary["median_source_spearman"]
                ),
                "mean_layer_matrix_spearman": (
                    metric_summary["mean_layer_matrix_spearman"]
                ),
                "positive_layer_matrix_spearman_fraction": (
                    metric_summary[
                        "positive_layer_matrix_spearman_fraction"
                    ]
                ),
                "top1_agreement": metric_summary["top1_agreement"],
                "top5_overlap_fraction": (
                    metric_summary["top5_overlap_fraction"]
                ),
                "passed": metric_summary["passed"],
            }
        )
    write_csv(
        args.output / "metric_reproducibility_summary.csv",
        metric_summary_rows,
    )
    (args.output / "reproducibility_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    metadata = {
        "schema_version": "downstream-expert-substitution-v1",
        "model_id": manifest["model"]["id"],
        "model_commit": manifest["model"]["commit"],
        "primary_cost": "diagonal_fisher",
        "primary_cost_definition": (
            "Mean sum_d [grad_d * gate_i * "
            "(f_j(h)_d-f_i(h)_d)]^2, where grad is the derivative of "
            "per-document mean next-token NLL with respect to the MoE layer "
            "output at the sampled token."
        ),
        "secondary_costs": [
            "gradient_projection_squared",
            "absolute_first_order",
            "relative_mse",
        ],
        "active_layers": active_layers,
        "contexts_per_expert_per_split": args.contexts_per_expert,
        "sampled_contexts": sampled_context_count,
        "unique_samples_forwarded": len(selected_samples),
        "unique_hidden_gradient_pairs": expected,
        "excluded_contexts": "final token of every sequence",
        "loss_normalization": (
            "mean next-token NLL within each document; document means summed "
            "within a batch"
        ),
        "sampling_seed": args.seed + 1709,
        "device": str(device),
        "dtype": str(dtype).removeprefix("torch."),
        "reproducibility_passed": summary["passed"],
        "elapsed_seconds": time.perf_counter() - started,
    }
    (args.output / "manifest.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"[complete] passed={summary['passed']} "
        f"median_source_spearman={summary['median_source_spearman']:.4f} "
        f"top5_overlap={summary['top5_overlap_fraction']:.4f} "
        f"seconds={metadata['elapsed_seconds']:.1f}",
        flush=True,
    )


if __name__ == "__main__":
    main()
