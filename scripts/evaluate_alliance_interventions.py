#!/usr/bin/env python3
"""Evaluate reversible Granite expert-alliance routing interventions."""

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


CONDITIONS = (
    "baseline",
    "learned_token",
    "random_token",
    "learned_block64",
    "random_block64",
    "learned_block64_top1",
    "random_block64_top1",
    "learned_block64_top2",
    "random_block64_top2",
)


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
            token_nll = tensors.get_tensor("token_nll").to(torch.float32)
            for row, metadata in enumerate(metadata_rows):
                record = metadata["metadata"]
                if (
                    record["variant_type"] != "original"
                    or record["split"] != "confirmatory"
                ):
                    continue
                length = int(lengths[row])
                baseline_losses = token_nll[row, :length]
                baseline_losses = baseline_losses[
                    torch.isfinite(baseline_losses)
                ]
                yield {
                    "sample_index": int(sample_indices[row]),
                    "id": metadata["id"],
                    "category": record["category"],
                    "length": length,
                    "input_ids": input_ids[row, :length].clone(),
                    "baseline_nll": float(baseline_losses.mean()),
                    "baseline_loss_sum": float(baseline_losses.sum()),
                    "loss_tokens": int(len(baseline_losses)),
                }


def active_layers_from_stability(path: Path) -> list[int]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    selected = [
        int(row["layer"])
        for row in rows
        if row["comparison"] == "cross_split_same_scale"
        and int(row["scale_a"]) == 64
        and int(row["scale_b"]) == 64
        and int(row["clusters"]) == 2
        and float(row["adjusted_rand"]) >= 0.5
        and int(row["min_discovery_cluster_size"]) >= 8
    ]
    return sorted(selected)


def randomize_labels(labels: list[list[int]], seed: int) -> list[list[int]]:
    randomized = []
    for layer, layer_labels in enumerate(labels):
        rng = np.random.default_rng(seed + 1009 * (layer + 1))
        values = np.asarray(layer_labels, dtype=np.int64)
        randomized.append(values[rng.permutation(len(values))].tolist())
    return randomized


class RouterIntervention:
    def __init__(
        self,
        learned_labels: list[list[int]],
        random_labels: list[list[int]],
        active_layers: list[int],
        num_experts: int,
        block_size: int = 64,
    ) -> None:
        self.learned_labels = learned_labels
        self.random_labels = random_labels
        self.active_layers = set(active_layers)
        self.num_experts = num_experts
        self.block_size = block_size
        self.condition = "baseline"
        self.telemetry: dict[str, float] = {}
        self.reset_telemetry()

    def reset_telemetry(self) -> None:
        self.telemetry = defaultdict(float)

    def configure(self, condition: str) -> None:
        if condition not in CONDITIONS:
            raise ValueError(condition)
        self.condition = condition

    def _labels(self, layer: int, device: torch.device) -> torch.Tensor:
        source = (
            self.random_labels
            if self.condition.startswith("random")
            else self.learned_labels
        )
        return torch.tensor(source[layer], dtype=torch.int64, device=device)

    def allowed_mask(
        self, logits: torch.Tensor, layer: int
    ) -> torch.Tensor:
        tokens, experts = logits.shape
        if self.condition == "baseline" or layer not in self.active_layers:
            return torch.ones(
                (tokens, experts), dtype=torch.bool, device=logits.device
            )
        labels = self._labels(layer, logits.device)
        top1_clusters = labels[logits.argmax(dim=-1)]
        if self.condition.endswith("_token"):
            selected_clusters = top1_clusters
        else:
            probabilities = torch.softmax(logits, dim=-1)
            one_hot = F.one_hot(labels, num_classes=2).to(probabilities.dtype)
            cluster_mass = probabilities @ one_hot
            selected_clusters = torch.empty(
                tokens, dtype=torch.int64, device=logits.device
            )
            for start in range(0, tokens, self.block_size):
                end = min(start + self.block_size, tokens)
                dominant = cluster_mass[start:end].mean(dim=0).argmax()
                selected_clusters[start:end] = dominant
        allowed = labels[None, :] == selected_clusters[:, None]
        if self.condition.endswith("_top1"):
            exceptions = logits.topk(1, dim=-1).indices
            allowed.scatter_(1, exceptions, True)
        elif self.condition.endswith("_top2"):
            exceptions = logits.topk(2, dim=-1).indices
            allowed.scatter_(1, exceptions, True)
        return allowed

    def record(
        self,
        logits: torch.Tensor,
        allowed: torch.Tensor,
        new_topk: torch.Tensor,
        layer: int,
    ) -> None:
        original_topk = logits.topk(new_topk.shape[1], dim=-1).indices
        self.telemetry["tokens"] += logits.shape[0]
        self.telemetry["top1_changed"] += float(
            (original_topk[:, 0] != new_topk[:, 0]).sum()
        )
        intersections = (
            original_topk[:, :, None] == new_topk[:, None, :]
        ).any(dim=-1).sum(dim=-1)
        self.telemetry["topk_jaccard_sum"] += float(
            (intersections / (16.0 - intersections)).sum()
        )
        for start in range(0, logits.shape[0], self.block_size):
            end = min(start + self.block_size, logits.shape[0])
            self.telemetry["candidate_slots"] += self.num_experts
            self.telemetry["allowed_candidate_slots"] += float(
                allowed[start:end].any(dim=0).sum()
            )
            self.telemetry["original_executed_slots"] += float(
                torch.unique(original_topk[start:end]).numel()
            )
            self.telemetry["new_executed_slots"] += float(
                torch.unique(new_topk[start:end]).numel()
            )
            if layer in self.active_layers:
                self.telemetry["active_candidate_slots"] += self.num_experts
                self.telemetry["active_allowed_candidate_slots"] += float(
                    allowed[start:end].any(dim=0).sum()
                )

    def summary(self) -> dict[str, float]:
        tokens = self.telemetry["tokens"]
        candidate_slots = self.telemetry["candidate_slots"]
        active_slots = self.telemetry["active_candidate_slots"]
        return {
            "top1_change_fraction": (
                self.telemetry["top1_changed"] / tokens if tokens else 0.0
            ),
            "mean_top8_jaccard": (
                self.telemetry["topk_jaccard_sum"] / tokens
                if tokens
                else 1.0
            ),
            "candidate_expert_block_fraction": (
                self.telemetry["allowed_candidate_slots"] / candidate_slots
                if candidate_slots
                else 1.0
            ),
            "active_candidate_expert_block_fraction": (
                self.telemetry["active_allowed_candidate_slots"] / active_slots
                if active_slots
                else 1.0
            ),
            "original_executed_expert_block_fraction": (
                self.telemetry["original_executed_slots"] / candidate_slots
                if candidate_slots
                else 0.0
            ),
            "new_executed_expert_block_fraction": (
                self.telemetry["new_executed_slots"] / candidate_slots
                if candidate_slots
                else 0.0
            ),
        }


def install_intervention(
    model: torch.nn.Module, controller: RouterIntervention
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
            allowed = controller.allowed_mask(logits, _layer_index)
            masked_logits = logits.masked_fill(~allowed, float("-inf"))
            top_k_logits, top_k_indices = masked_logits.topk(
                self.top_k, dim=1
            )
            top_k_gates = torch.softmax(top_k_logits, dim=1).type_as(
                hidden_states
            )
            zeros = torch.zeros(
                [top_k_gates.size(0), self.num_experts],
                dtype=top_k_gates.dtype,
                device=top_k_gates.device,
            )
            gates = zeros.scatter(1, top_k_indices, 1)
            expert_size = gates.long().sum(0).tolist()
            top_k_experts = top_k_indices.flatten()
            _, index_sorted_experts = top_k_experts.sort(0)
            batch_index = index_sorted_experts.div(
                self.top_k, rounding_mode="trunc"
            )
            flat_gates = top_k_gates.flatten()
            batch_gates = flat_gates[index_sorted_experts]
            controller.record(
                logits, allowed, top_k_indices, _layer_index
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


def load_existing_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return list(csv.DictReader(path.open(encoding="utf-8")))


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["condition"]].append(row)
    summary = []
    for condition, selected in grouped.items():
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
        summary.append(
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
                    key: float(np.mean([float(row[key]) for row in selected]))
                    for key in (
                        "top1_change_fraction",
                        "mean_top8_jaccard",
                        "candidate_expert_block_fraction",
                        "active_candidate_expert_block_fraction",
                        "original_executed_expert_block_fraction",
                        "new_executed_expert_block_fraction",
                        "elapsed_seconds",
                    )
                },
            }
        )
    return sorted(summary, key=lambda row: CONDITIONS.index(row["condition"]))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact",
        type=Path,
        default=Path("artifacts/probe-1k-granite-512-v1.1"),
    )
    parser.add_argument(
        "--alliances",
        type=Path,
        default=Path("analysis/expert-alliances-v1/frozen_alliances.json"),
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
        default=Path("analysis/alliance-interventions-v1"),
    )
    parser.add_argument(
        "--conditions",
        nargs="+",
        choices=CONDITIONS,
        default=list(CONDITIONS),
    )
    parser.add_argument("--max-samples", type=int)
    parser.add_argument("--seed", type=int, default=20260727)
    parser.add_argument("--summarize-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.summarize_only:
        complete_rows = []
        completed_conditions = []
        for condition in CONDITIONS:
            condition_path = args.output / f"{condition}.csv"
            if condition_path.exists():
                complete_rows.extend(load_existing_rows(condition_path))
                completed_conditions.append(condition)
        write_csv(args.output / "summary.csv", summarize(complete_rows))
        manifest_path = args.output / "manifest.json"
        if manifest_path.exists():
            metadata = json.loads(manifest_path.read_text(encoding="utf-8"))
            metadata["conditions_completed"] = completed_conditions
            metadata.pop("conditions", None)
            manifest_path.write_text(
                json.dumps(
                    metadata, ensure_ascii=False, indent=2, sort_keys=True
                )
                + "\n",
                encoding="utf-8",
            )
        print(f"[summarized] {args.output}", flush=True)
        return
    manifest = json.loads(
        (args.artifact / "manifest.json").read_text(encoding="utf-8")
    )
    alliance_payload = json.loads(args.alliances.read_text(encoding="utf-8"))
    learned_labels = [
        alliance_payload["layers"][str(layer)]["2"]
        for layer in range(int(manifest["model"]["num_layers"]))
    ]
    random_labels = randomize_labels(learned_labels, args.seed + 701)
    active_layers = active_layers_from_stability(args.stability)
    if any(
        min(np.bincount(np.asarray(learned_labels[layer]), minlength=2)) < 8
        for layer in active_layers
    ):
        raise RuntimeError("An active alliance cannot hold top-8 experts.")

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
    controller = RouterIntervention(
        learned_labels,
        random_labels,
        active_layers,
        int(manifest["model"]["num_experts"]),
    )
    install_intervention(model, controller)
    print(
        f"[loaded] seconds={time.perf_counter()-started:.2f} "
        f"active_layers={active_layers}",
        flush=True,
    )

    samples = list(iter_confirmatory_samples(args.artifact, manifest))
    if args.max_samples is not None:
        samples = samples[: args.max_samples]
    all_rows = []
    replay_reference: dict[int, dict[str, Any]] = {}
    for condition in args.conditions:
        output_path = args.output / f"{condition}.csv"
        existing = load_existing_rows(output_path)
        if condition != "baseline" and not replay_reference:
            baseline_path = args.output / "baseline.csv"
            if not baseline_path.exists():
                raise RuntimeError(
                    "Run baseline first so interventions use a same-device "
                    "per-sample reference."
                )
            replay_reference = {
                int(row["sample_index"]): row
                for row in load_existing_rows(baseline_path)
            }
        completed = {int(row["sample_index"]) for row in existing}
        rows = list(existing)
        controller.configure(condition)
        print(
            f"[condition] {condition} resume={len(completed)} total={len(samples)}",
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
            intervention_nll, intervention_sum, loss_tokens = compute_nll(
                outputs.logits, input_ids
            )
            elapsed = time.perf_counter() - sample_started
            if loss_tokens != sample["loss_tokens"]:
                raise RuntimeError("NLL token count changed.")
            if condition == "baseline":
                reference_nll = sample["baseline_nll"]
                reference_sum = sample["baseline_loss_sum"]
                reference_kind = "stored_mps_fp16"
            else:
                reference = replay_reference[sample["sample_index"]]
                reference_nll = float(reference["intervention_nll"])
                reference_sum = float(reference["intervention_loss_sum"])
                reference_kind = "replayed_cpu_fp32"
            rows.append(
                {
                    "condition": condition,
                    "sample_index": sample["sample_index"],
                    "id": sample["id"],
                    "category": sample["category"],
                    "length": sample["length"],
                    "loss_tokens": loss_tokens,
                    "stored_baseline_nll": sample["baseline_nll"],
                    "baseline_nll": reference_nll,
                    "intervention_nll": intervention_nll,
                    "nll_delta": intervention_nll - reference_nll,
                    "stored_baseline_loss_sum": sample["baseline_loss_sum"],
                    "baseline_loss_sum": reference_sum,
                    "intervention_loss_sum": intervention_sum,
                    "reference_kind": reference_kind,
                    "elapsed_seconds": elapsed,
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
        if condition == "baseline":
            replay_reference = {
                int(row["sample_index"]): row for row in rows
            }
        all_rows.extend(rows)
    complete_rows = []
    completed_conditions = []
    for condition in CONDITIONS:
        condition_path = args.output / f"{condition}.csv"
        if condition_path.exists():
            complete_rows.extend(load_existing_rows(condition_path))
            completed_conditions.append(condition)
    write_csv(args.output / "summary.csv", summarize(complete_rows))
    metadata = {
        "schema_version": "alliance-intervention-v1",
        "model_id": manifest["model"]["id"],
        "model_commit": manifest["model"]["commit"],
        "device": str(device),
        "dtype": str(dtype).removeprefix("torch."),
        "conditions_requested_this_run": args.conditions,
        "conditions_completed": completed_conditions,
        "active_layers": active_layers,
        "num_active_layers": len(active_layers),
        "alliance_source": str(args.alliances),
        "stability_source": str(args.stability),
        "random_partition_seed": args.seed + 701,
        "block_size": controller.block_size,
        "max_samples": args.max_samples,
    }
    (args.output / "manifest.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"[complete] {args.output}", flush=True)


if __name__ == "__main__":
    main()
