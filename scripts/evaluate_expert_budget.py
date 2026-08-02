#!/usr/bin/env python3
"""Evaluate frozen expert-budget substitution policies on confirmatory NLL."""

from __future__ import annotations

import argparse
import csv
import json
import math
import time
import types
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import torch
import torch.nn.functional as F
from safetensors import safe_open
from transformers import AutoModelForCausalLM


CONDITIONS = ("facility", "frequency", "random")


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


def iter_confirmatory_samples(
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
            for row, metadata in enumerate(metadata_rows):
                record = metadata["metadata"]
                if (
                    record["variant_type"] != "original"
                    or record["split"] != "confirmatory"
                ):
                    continue
                length = int(lengths[row])
                yield {
                    "sample_index": int(sample_indices[row]),
                    "id": metadata["id"],
                    "category": record["category"],
                    "length": length,
                    "input_ids": input_ids[row, :length].clone(),
                }


def load_rows(path: Path) -> list[dict[str, Any]]:
    return list(csv.DictReader(path.open(encoding="utf-8")))


class BudgetController:
    def __init__(
        self,
        methods: dict[str, dict[str, Any]],
        active_layers: list[int],
        num_layers: int,
        num_experts: int,
        block_size: int = 64,
    ) -> None:
        self.methods = methods
        self.active_layers = set(active_layers)
        self.num_layers = num_layers
        self.num_experts = num_experts
        self.block_size = block_size
        self.condition = CONDITIONS[0]
        self.telemetry: dict[str, float] = {}
        self.reset_telemetry()

    def configure(self, condition: str) -> None:
        if condition not in CONDITIONS:
            raise ValueError(condition)
        self.condition = condition

    def mapping(self, layer: int, device: torch.device) -> torch.Tensor:
        if layer not in self.active_layers:
            values = list(range(self.num_experts))
        else:
            values = self.methods[self.condition][str(layer)]["assignment"]
        return torch.tensor(values, dtype=torch.int64, device=device)

    def keep(self, layer: int) -> list[int]:
        if layer not in self.active_layers:
            return list(range(self.num_experts))
        return self.methods[self.condition][str(layer)]["keep"]

    def reset_telemetry(self) -> None:
        self.telemetry = defaultdict(float)

    def record(
        self,
        original_indices: torch.Tensor,
        mapped_indices: torch.Tensor,
        gates: torch.Tensor,
        layer: int,
    ) -> None:
        tokens, top_k = original_indices.shape
        changed = original_indices != mapped_indices
        self.telemetry["tokens"] += tokens
        self.telemetry["assignments"] += tokens * top_k
        self.telemetry["top1_changed"] += float(changed[:, 0].sum())
        self.telemetry["assignments_changed"] += float(changed.sum())
        self.telemetry["gate_mass_changed"] += float(
            (gates * changed).sum()
        )
        original_present = F.one_hot(
            original_indices, num_classes=self.num_experts
        ).any(dim=1)
        mapped_present = F.one_hot(
            mapped_indices, num_classes=self.num_experts
        ).any(dim=1)
        intersection = (original_present & mapped_present).sum(dim=1)
        union = (original_present | mapped_present).sum(dim=1)
        self.telemetry["topk_jaccard_sum"] += float(
            (intersection / union.clamp_min(1)).sum()
        )
        keep = self.keep(layer)
        for start in range(0, tokens, self.block_size):
            end = min(start + self.block_size, tokens)
            self.telemetry["candidate_slots"] += self.num_experts
            self.telemetry["kept_candidate_slots"] += len(keep)
            self.telemetry["original_executed_slots"] += float(
                torch.unique(original_indices[start:end]).numel()
            )
            self.telemetry["mapped_executed_slots"] += float(
                torch.unique(mapped_indices[start:end]).numel()
            )
            if layer in self.active_layers:
                self.telemetry["active_candidate_slots"] += self.num_experts
                self.telemetry["active_kept_candidate_slots"] += len(keep)

    def summary(self) -> dict[str, float]:
        tokens = self.telemetry["tokens"]
        assignments = self.telemetry["assignments"]
        candidate_slots = self.telemetry["candidate_slots"]
        active_slots = self.telemetry["active_candidate_slots"]
        return {
            "top1_change_fraction": self.telemetry["top1_changed"] / tokens,
            "assignment_change_fraction": (
                self.telemetry["assignments_changed"] / assignments
            ),
            "rerouted_gate_mass_fraction": (
                self.telemetry["gate_mass_changed"] / tokens
            ),
            "mean_top8_set_jaccard": (
                self.telemetry["topk_jaccard_sum"] / tokens
            ),
            "candidate_expert_block_fraction": (
                self.telemetry["kept_candidate_slots"] / candidate_slots
            ),
            "active_candidate_expert_block_fraction": (
                self.telemetry["active_kept_candidate_slots"] / active_slots
            ),
            "original_executed_expert_block_fraction": (
                self.telemetry["original_executed_slots"] / candidate_slots
            ),
            "mapped_executed_expert_block_fraction": (
                self.telemetry["mapped_executed_slots"] / candidate_slots
            ),
        }


def install_intervention(
    model: torch.nn.Module, controller: BudgetController
) -> None:
    for layer_index, decoder_layer in enumerate(model.model.layers):
        router = decoder_layer.block_sparse_moe.router

        def forward(
            self: torch.nn.Module,
            hidden_states: torch.Tensor,
            *,
            _layer_index: int = layer_index,
        ):
            logits = self.layer(hidden_states).float()
            top_k_logits, original_indices = logits.topk(self.top_k, dim=1)
            top_k_gates = torch.softmax(top_k_logits, dim=1).type_as(
                hidden_states
            )
            mapping = controller.mapping(_layer_index, logits.device)
            mapped_indices = mapping[original_indices]
            expert_size = torch.bincount(
                mapped_indices.flatten(), minlength=self.num_experts
            ).tolist()
            flat_experts = mapped_indices.flatten()
            _, index_sorted_experts = flat_experts.sort(0)
            batch_index = index_sorted_experts.div(
                self.top_k, rounding_mode="trunc"
            )
            flat_gates = top_k_gates.flatten()
            batch_gates = flat_gates[index_sorted_experts]
            controller.record(
                original_indices,
                mapped_indices,
                top_k_gates,
                _layer_index,
            )
            return (
                index_sorted_experts,
                batch_index,
                batch_gates,
                expert_size,
                logits,
            )

        router.forward = types.MethodType(forward, router)


def compute_nll(
    logits: torch.Tensor, input_ids: torch.Tensor
) -> tuple[float, float, int]:
    losses = F.cross_entropy(
        logits[:, :-1, :].float().transpose(1, 2),
        input_ids[:, 1:],
        reduction="none",
    )
    return float(losses.mean()), float(losses.sum()), int(losses.numel())


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["condition"]].append(row)
    result = []
    for condition in CONDITIONS:
        selected = grouped.get(condition, [])
        if not selected:
            continue
        deltas = np.asarray(
            [float(row["nll_delta"]) for row in selected], dtype=np.float64
        )
        total_intervention = sum(
            float(row["intervention_loss_sum"]) for row in selected
        )
        total_baseline = sum(
            float(row["baseline_loss_sum"]) for row in selected
        )
        total_tokens = sum(int(row["loss_tokens"]) for row in selected)
        token_delta = (total_intervention - total_baseline) / total_tokens
        telemetry_keys = (
            "top1_change_fraction",
            "assignment_change_fraction",
            "rerouted_gate_mass_fraction",
            "mean_top8_set_jaccard",
            "candidate_expert_block_fraction",
            "active_candidate_expert_block_fraction",
            "original_executed_expert_block_fraction",
            "mapped_executed_expert_block_fraction",
            "elapsed_seconds",
        )
        result.append(
            {
                "condition": condition,
                "samples": len(selected),
                "mean_sample_nll_delta": float(deltas.mean()),
                "median_sample_nll_delta": float(np.median(deltas)),
                "p95_sample_nll_delta": float(np.quantile(deltas, 0.95)),
                "token_weighted_nll_delta": float(token_delta),
                "perplexity_ratio": float(math.exp(token_delta)),
                "fraction_samples_delta_le_0_01": float(
                    np.mean(deltas <= 0.01)
                ),
                "fraction_samples_delta_le_0_05": float(
                    np.mean(deltas <= 0.05)
                ),
                **{
                    key: float(
                        np.mean([float(row[key]) for row in selected])
                    )
                    for key in telemetry_keys
                },
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
        "--policies",
        type=Path,
        default=Path("analysis/expert-budget-v1/policies.json"),
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path("analysis/alliance-interventions-v1/baseline.csv"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("analysis/expert-budget-interventions-v1"),
    )
    parser.add_argument(
        "--conditions",
        nargs="+",
        choices=CONDITIONS,
        default=list(CONDITIONS),
    )
    parser.add_argument("--max-samples", type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(
        (args.artifact / "manifest.json").read_text(encoding="utf-8")
    )
    policies = json.loads(args.policies.read_text(encoding="utf-8"))
    baseline = {
        int(row["sample_index"]): row for row in load_rows(args.baseline)
    }
    samples = list(iter_confirmatory_samples(args.artifact, manifest))
    if args.max_samples is not None:
        samples = samples[: args.max_samples]
    missing = [
        sample["sample_index"]
        for sample in samples
        if sample["sample_index"] not in baseline
    ]
    if missing:
        raise RuntimeError(f"Baseline missing samples: {missing[:5]}")
    device, dtype = select_device()
    print(f"[load] device={device} dtype={dtype}", flush=True)
    started = time.perf_counter()
    model = AutoModelForCausalLM.from_pretrained(
        manifest["model"]["id"],
        revision=manifest["model"]["commit"],
        dtype=dtype,
        low_cpu_mem_usage=True,
        local_files_only=True,
    )
    model.to(device)
    model.eval()
    controller = BudgetController(
        policies["methods"],
        policies["active_layers"],
        int(manifest["model"]["num_layers"]),
        int(manifest["model"]["num_experts"]),
    )
    install_intervention(model, controller)
    for condition in args.conditions:
        output_path = args.output / f"{condition}.csv"
        rows = load_rows(output_path) if output_path.exists() else []
        completed = {int(row["sample_index"]) for row in rows}
        controller.configure(condition)
        print(
            f"[condition] {condition} resume={len(completed)} "
            f"total={len(samples)}",
            flush=True,
        )
        for position, sample in enumerate(samples, start=1):
            if sample["sample_index"] in completed:
                continue
            input_ids = sample["input_ids"][None, :].to(device)
            attention_mask = torch.ones_like(input_ids)
            controller.reset_telemetry()
            sample_started = time.perf_counter()
            with torch.inference_mode():
                outputs = model(
                    input_ids=input_ids,
                    attention_mask=attention_mask,
                    use_cache=False,
                    return_dict=True,
                    logits_to_keep=0,
                )
            nll, loss_sum, loss_tokens = compute_nll(
                outputs.logits, input_ids
            )
            reference = baseline[sample["sample_index"]]
            reference_nll = float(reference["intervention_nll"])
            reference_sum = float(reference["intervention_loss_sum"])
            rows.append(
                {
                    "condition": condition,
                    "sample_index": sample["sample_index"],
                    "id": sample["id"],
                    "category": sample["category"],
                    "length": sample["length"],
                    "loss_tokens": loss_tokens,
                    "baseline_nll": reference_nll,
                    "intervention_nll": nll,
                    "nll_delta": nll - reference_nll,
                    "baseline_loss_sum": reference_sum,
                    "intervention_loss_sum": loss_sum,
                    "reference_kind": "replayed_cpu_fp32",
                    "elapsed_seconds": (
                        time.perf_counter() - sample_started
                    ),
                    **controller.summary(),
                }
            )
            write_csv(output_path, rows)
            del outputs, input_ids, attention_mask
            if position % 20 == 0 or position == len(samples):
                print(
                    f"[progress] {condition} {position}/{len(samples)}",
                    flush=True,
                )
    all_rows = []
    completed_conditions = []
    for condition in CONDITIONS:
        path = args.output / f"{condition}.csv"
        if path.exists():
            all_rows.extend(load_rows(path))
            completed_conditions.append(condition)
    write_csv(args.output / "summary.csv", summarize(all_rows))
    output_manifest = {
        "schema_version": "expert-budget-intervention-v1",
        "model_id": manifest["model"]["id"],
        "model_commit": manifest["model"]["commit"],
        "device": str(device),
        "dtype": str(dtype).removeprefix("torch."),
        "policy_source": str(args.policies),
        "baseline_source": str(args.baseline),
        "conditions_completed": completed_conditions,
        "active_layers": policies["active_layers"],
        "budget": policies["budget"],
        "num_experts": policies["num_experts"],
        "gate_policy": (
            "Preserve original top-8 gate weights; map each selected source "
            "expert to its frozen retained substitute, summing duplicates."
        ),
        "max_samples": args.max_samples,
        "elapsed_seconds": time.perf_counter() - started,
    }
    (args.output / "manifest.json").write_text(
        json.dumps(output_manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"[complete] {args.output}", flush=True)


if __name__ == "__main__":
    main()
