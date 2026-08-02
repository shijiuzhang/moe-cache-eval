#!/usr/bin/env python3
"""Collect autoregressive MoE decode routes from an MLX-quantized model.

This collector is intentionally separate from the Transformers/PyTorch
collector. MLX imports are delayed until runtime so the repository's normal
test environment does not need Metal or mlx-lm.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import time
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from safetensors.numpy import save_file


SCHEMA_VERSION = 1


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)


def read_records(
    path: Path,
    *,
    text_field: str,
    id_field: str,
) -> Iterable[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        logical_index = 0
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            source = json.loads(line)
            text = source.get(text_field)
            if not isinstance(text, str) or not text:
                raise ValueError(
                    f"Line {line_number} has no {text_field!r} text."
                )
            sample_id = str(source.get(id_field, logical_index))
            yield {
                "source_line": line_number,
                "source_index": logical_index,
                "id": sample_id,
                "text": text,
                "metadata": {
                    key: value
                    for key, value in source.items()
                    if key not in {text_field, id_field}
                },
            }
            logical_index += 1


def select_records(
    path: Path,
    *,
    text_field: str,
    id_field: str,
    split: str,
    category_field: str,
    samples_per_category: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in read_records(
        path,
        text_field=text_field,
        id_field=id_field,
    ):
        metadata = record["metadata"]
        if metadata.get("split") != split:
            continue
        category = metadata.get(category_field)
        if not isinstance(category, str) or not category:
            raise ValueError(
                f"Record {record['id']} lacks {category_field!r}."
            )
        grouped.setdefault(category, []).append(record)
    categories = sorted(grouped)
    if not categories:
        raise ValueError(f"No rows matched split={split!r}.")
    selected: list[dict[str, Any]] = []
    for category in categories:
        rows = grouped[category]
        if len(rows) < samples_per_category:
            raise ValueError(
                f"{category} has {len(rows)} rows; "
                f"need {samples_per_category}."
            )
        selected.extend(rows[:samples_per_category])
    return selected, categories


def truncate_ids(
    token_ids: list[int],
    max_length: int,
    truncation_side: str,
) -> tuple[list[int], bool]:
    if len(token_ids) <= max_length:
        return token_ids, False
    if truncation_side == "left":
        return token_ids[-max_length:], True
    return token_ids[:max_length], True


def encode_prompt_ids(
    tokenizer: Any,
    text: str,
    *,
    prompt_format: str,
    enable_thinking: bool,
) -> list[int]:
    """Encode a raw continuation or a one-turn user chat explicitly.

    Workload-conditioning experiments must not rely on a tokenizer's implicit
    defaults: Qwen3's thinking mode changes the assistant prefix, and feeding
    instructions as raw text makes the model continue the instruction shell.
    """
    if prompt_format == "chat":
        if not hasattr(tokenizer, "apply_chat_template"):
            raise TypeError("Tokenizer does not provide apply_chat_template().")
        token_ids = tokenizer.apply_chat_template(
            [{"role": "user", "content": text}],
            tokenize=True,
            add_generation_prompt=True,
            enable_thinking=enable_thinking,
        )
    elif prompt_format == "raw":
        token_ids = tokenizer.encode(text, add_special_tokens=True)
    else:
        raise ValueError(f"Unsupported prompt format: {prompt_format!r}.")
    if hasattr(token_ids, "ids"):
        token_ids = token_ids.ids
    return [int(value) for value in token_ids]


def routing_metrics_numpy(
    router_logits: np.ndarray,
    top_k: int,
) -> dict[str, np.ndarray]:
    """Compute the same stored routing metrics as the PyTorch collector."""
    logits = np.asarray(router_logits, dtype=np.float32)
    shifted = logits - logits.max(axis=-1, keepdims=True)
    probabilities = np.exp(shifted)
    probabilities /= probabilities.sum(axis=-1, keepdims=True)
    order = np.argsort(-probabilities, axis=-1, kind="stable")
    topk_indices = order[..., :top_k]
    topk_probabilities = np.take_along_axis(
        probabilities,
        topk_indices,
        axis=-1,
    )
    denominator = np.maximum(
        topk_probabilities.sum(axis=-1, keepdims=True),
        np.finfo(np.float32).tiny,
    )
    topk_weights = topk_probabilities / denominator
    entropy = -(
        probabilities
        * np.log(np.maximum(probabilities, np.finfo(np.float32).tiny))
    ).sum(axis=-1)
    normalized_entropy = entropy / math.log(probabilities.shape[-1])
    if top_k >= 2:
        margin = topk_probabilities[..., 0] - topk_probabilities[..., 1]
    else:
        margin = topk_probabilities[..., 0]
    return {
        "topk_indices": topk_indices.astype(np.int16),
        "topk_probabilities": topk_probabilities,
        "topk_weights": topk_weights,
        "router_entropy": entropy,
        "router_normalized_entropy": normalized_entropy,
        "router_margin": margin,
    }


class RouteSink:
    def __init__(self, num_layers: int):
        self.num_layers = num_layers
        self.active = False
        self._current: dict[int, Any] = {}

    def begin(self) -> None:
        if self._current:
            raise RuntimeError("Previous route capture was not consumed.")
        self.active = True

    def record(self, layer_id: int, logits: Any) -> None:
        if not self.active:
            return
        if layer_id in self._current:
            raise RuntimeError(f"Layer {layer_id} was captured twice.")
        self._current[layer_id] = logits

    def finish(self, mx: Any, output_logits: Any) -> np.ndarray:
        self.active = False
        expected = set(range(self.num_layers))
        observed = set(self._current)
        if observed != expected:
            missing = sorted(expected - observed)
            raise RuntimeError(f"Missing router layers: {missing[:8]}.")
        arrays = [self._current[index] for index in range(self.num_layers)]
        mx.eval(output_logits, *arrays)
        stacked = np.stack(
            [
                np.asarray(value.astype(mx.float32))
                .reshape(-1, value.shape[-1])[-1]
                .copy()
                for value in arrays
            ],
            axis=0,
        )
        self._current.clear()
        return stacked


def install_qwen3_route_capture(model: Any, mx: Any) -> RouteSink:
    from mlx_lm.models import qwen3_moe

    layers = model.layers
    sink = RouteSink(len(layers))
    for layer_id, layer in enumerate(layers):
        if not isinstance(
            layer.mlp,
            qwen3_moe.Qwen3MoeSparseMoeBlock,
        ):
            raise TypeError(f"Layer {layer_id} is not Qwen3 sparse MoE.")
        layer.mlp._route_layer_id = layer_id
        layer.mlp._route_sink = sink

    def traced_call(self: Any, x: Any) -> Any:
        raw_gates = self.gate(x)
        self._route_sink.record(self._route_layer_id, raw_gates)
        gates = mx.softmax(raw_gates, axis=-1, precise=True)
        k = self.top_k
        indices = mx.argpartition(gates, kth=-k, axis=-1)[..., -k:]
        scores = mx.take_along_axis(gates, indices, axis=-1)
        if self.norm_topk_prob:
            scores /= mx.sum(scores, axis=-1, keepdims=True)
        y = self.switch_mlp(x, indices)
        return (y * scores[..., None]).sum(axis=-2)

    qwen3_moe.Qwen3MoeSparseMoeBlock.__call__ = traced_call
    return sink


def normalize_eos_ids(value: Any) -> set[int]:
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        return {int(item) for item in value}
    return {int(value)}


def collect_one(
    *,
    model: Any,
    tokenizer: Any,
    mx: Any,
    make_prompt_cache: Any,
    sink: RouteSink,
    record: dict[str, Any],
    max_prompt_length: int,
    max_new_tokens: int,
    num_layers: int,
    num_experts: int,
    top_k: int,
    eos_ids: set[int],
    prompt_format: str,
    enable_thinking: bool,
) -> dict[str, Any]:
    requires_chat = bool(
        record["metadata"].get("collection", {}).get(
            "requires_chat_template", False
        )
    )
    if requires_chat and prompt_format != "chat":
        raise ValueError(
            f"Record {record['id']} requires a chat template; "
            "use --prompt-format chat."
        )
    original_ids = encode_prompt_ids(
        tokenizer,
        record["text"],
        prompt_format=prompt_format,
        enable_thinking=enable_thinking,
    )
    truncation_side = getattr(tokenizer, "truncation_side", "right")
    prompt_ids, truncated = truncate_ids(
        original_ids,
        max_prompt_length,
        truncation_side,
    )
    if not prompt_ids:
        raise ValueError(f"Tokenizer produced no tokens for {record['id']}.")

    cache = make_prompt_cache(model)
    sink.active = False
    prompt = mx.array([prompt_ids], dtype=mx.int32)
    prompt_logits = model(prompt, cache=cache)
    mx.eval(prompt_logits)
    current = int(mx.argmax(prompt_logits[0, -1]).item())
    first_emitted = current

    consumed_ids: list[int] = []
    emitted_ids: list[int] = []
    router_steps: list[np.ndarray] = []
    total_emitted = 1
    stop_reason = "max_new_tokens"
    while total_emitted < max_new_tokens:
        if current in eos_ids:
            stop_reason = "eos"
            break
        sink.begin()
        output = model(
            mx.array([[current]], dtype=mx.int32),
            cache=cache,
        )
        router = sink.finish(mx, output)
        if router.shape != (num_layers, num_experts):
            raise RuntimeError(f"Unexpected router shape: {router.shape}.")
        next_token = int(mx.argmax(output[0, -1]).item())
        consumed_ids.append(current)
        emitted_ids.append(next_token)
        router_steps.append(router)
        current = next_token
        total_emitted += 1
        mx.clear_cache()

    if total_emitted >= max_new_tokens and current in eos_ids:
        stop_reason = "eos"
    if router_steps:
        router_logits = np.stack(router_steps, axis=1)
        metrics = routing_metrics_numpy(router_logits, top_k)
    else:
        router_logits = np.empty(
            (num_layers, 0, num_experts),
            dtype=np.float32,
        )
        metrics = {
            "topk_indices": np.empty(
                (num_layers, 0, top_k), dtype=np.int16
            ),
            "topk_probabilities": np.empty(
                (num_layers, 0, top_k), dtype=np.float32
            ),
            "topk_weights": np.empty(
                (num_layers, 0, top_k), dtype=np.float32
            ),
            "router_entropy": np.empty(
                (num_layers, 0), dtype=np.float32
            ),
            "router_normalized_entropy": np.empty(
                (num_layers, 0), dtype=np.float32
            ),
            "router_margin": np.empty(
                (num_layers, 0), dtype=np.float32
            ),
        }
    return {
        "id": record["id"],
        "source_line": record["source_line"],
        "source_index": record["source_index"],
        "text": record["text"],
        "metadata": {
            **record["metadata"],
            "decode_alignment": (
                "input_ids[t] consumed by decode forward t; "
                "emitted_ids[t] emitted by that forward"
            ),
            "first_emitted_id_from_prefill": first_emitted,
            "generated_text_including_prefill": tokenizer.decode(
                [first_emitted, *emitted_ids]
            ),
            "prompt_format": prompt_format,
            "enable_thinking": enable_thinking,
            "prompt_original_token_length": len(original_ids),
            "prompt_stored_token_length": len(prompt_ids),
            "prompt_truncated": truncated,
            "total_emitted_tokens_including_prefill": total_emitted,
            "decode_forward_count": len(consumed_ids),
            "stop_reason": stop_reason,
        },
        "stored_token_length": len(consumed_ids),
        "input_ids": np.asarray(consumed_ids, dtype=np.int32),
        "emitted_ids": np.asarray(emitted_ids, dtype=np.int32),
        "router_logits": router_logits.astype(np.float16),
        **{
            key: (
                value
                if key == "topk_indices"
                else value.astype(np.float16)
            )
            for key, value in metrics.items()
        },
    }


def write_shard(
    output_dir: Path,
    shard_index: int,
    start_index: int,
    samples: list[dict[str, Any]],
) -> dict[str, Any]:
    count = len(samples)
    max_length = max(sample["stored_token_length"] for sample in samples)
    first = samples[0]
    num_layers, _, num_experts = first["router_logits"].shape
    top_k = first["topk_indices"].shape[-1]
    tensors: dict[str, np.ndarray] = {
        "sample_indices": np.arange(
            start_index, start_index + count, dtype=np.int64
        ),
        "sequence_lengths": np.zeros(count, dtype=np.int32),
        "input_ids": np.zeros((count, max_length), dtype=np.int32),
        "emitted_ids": np.full((count, max_length), -1, dtype=np.int32),
        "attention_mask": np.zeros((count, max_length), dtype=np.bool_),
        "router_logits": np.zeros(
            (count, num_layers, max_length, num_experts),
            dtype=np.float16,
        ),
        "topk_indices": np.full(
            (count, num_layers, max_length, top_k),
            -1,
            dtype=np.int16,
        ),
        "topk_probabilities": np.zeros(
            (count, num_layers, max_length, top_k),
            dtype=np.float16,
        ),
        "topk_weights": np.zeros(
            (count, num_layers, max_length, top_k),
            dtype=np.float16,
        ),
        "router_entropy": np.zeros(
            (count, num_layers, max_length),
            dtype=np.float16,
        ),
        "router_normalized_entropy": np.zeros(
            (count, num_layers, max_length),
            dtype=np.float16,
        ),
        "router_margin": np.zeros(
            (count, num_layers, max_length),
            dtype=np.float16,
        ),
    }
    metadata_rows: list[dict[str, Any]] = []
    for row_index, sample in enumerate(samples):
        length = sample["stored_token_length"]
        tensors["sequence_lengths"][row_index] = length
        tensors["input_ids"][row_index, :length] = sample["input_ids"]
        tensors["emitted_ids"][row_index, :length] = sample["emitted_ids"]
        tensors["attention_mask"][row_index, :length] = True
        for key in (
            "router_logits",
            "topk_indices",
            "topk_probabilities",
            "topk_weights",
            "router_entropy",
            "router_normalized_entropy",
            "router_margin",
        ):
            value = sample[key]
            if value.ndim == 3:
                tensors[key][row_index, :, :length, :] = value
            else:
                tensors[key][row_index, :, :length] = value
        metadata_rows.append(
            {
                "collection_index": start_index + row_index,
                "id": sample["id"],
                "source_line": sample["source_line"],
                "source_index": sample["source_index"],
                "original_token_length": length,
                "stored_token_length": length,
                "truncated": False,
                "metadata": sample["metadata"],
                "text": sample["text"],
            }
        )

    tensor_name = f"routes-{shard_index:05d}.safetensors"
    metadata_name = f"samples-{shard_index:05d}.jsonl"
    tensor_path = output_dir / tensor_name
    metadata_path = output_dir / metadata_name
    save_file(tensors, tensor_path)
    with metadata_path.open("w", encoding="utf-8") as handle:
        for row in metadata_rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    return {
        "index": shard_index,
        "start_sample": start_index,
        "end_sample_exclusive": start_index + count,
        "num_samples": count,
        "max_sequence_length": max_length,
        "tensor_file": tensor_name,
        "tensor_sha256": sha256_file(tensor_path),
        "metadata_file": metadata_name,
        "metadata_sha256": sha256_file(metadata_path),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect Qwen3 MoE decode routes with MLX."
    )
    parser.add_argument(
        "--model",
        default="mlx-community/Qwen3-30B-A3B-4bit",
    )
    parser.add_argument("--revision", default="main")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--text-field", default="prompt_text")
    parser.add_argument("--id-field", default="id")
    parser.add_argument("--split", default="discovery")
    parser.add_argument("--category-field", default="workload_archetype")
    parser.add_argument("--samples-per-category", type=int, default=1)
    parser.add_argument("--max-prompt-length", type=int, default=128)
    parser.add_argument("--max-new-tokens", type=int, default=8)
    parser.add_argument("--shard-size", type=int, default=2)
    parser.add_argument(
        "--prompt-format",
        choices=("raw", "chat"),
        default="raw",
        help="Use 'chat' for service-like instruction following.",
    )
    parser.add_argument(
        "--enable-thinking",
        action="store_true",
        help="Enable Qwen3 thinking in the chat template (off by default).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output.exists():
        raise FileExistsError(f"Output exists: {args.output}.")
    if args.samples_per_category < 1:
        raise ValueError("samples-per-category must be positive.")
    if args.max_prompt_length < 2 or args.max_new_tokens < 2:
        raise ValueError("Prompt and generation lengths must be at least 2.")

    import mlx.core as mx
    from huggingface_hub import HfApi
    from mlx_lm import load
    from mlx_lm.models.cache import make_prompt_cache

    records, categories = select_records(
        args.input,
        text_field=args.text_field,
        id_field=args.id_field,
        split=args.split,
        category_field=args.category_field,
        samples_per_category=args.samples_per_category,
    )
    args.output.mkdir(parents=True)
    manifest_path = args.output / "manifest.json"
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "initializing",
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "completed_samples": 0,
        "model": {
            "alias": args.model,
            "id": args.model,
            "revision": args.revision,
        },
        "input": {
            "path": str(args.input.resolve()),
            "sha256": sha256_file(args.input),
            "text_field": args.text_field,
            "id_field": args.id_field,
            "split": args.split,
            "category_field": args.category_field,
            "categories": categories,
        },
        "collection": {
            "kind": "autoregressive_decode",
            "backend": "mlx",
            "selection": "first_n_per_sorted_category",
            "samples_per_category": args.samples_per_category,
            "selected_samples": len(records),
            "max_prompt_length": args.max_prompt_length,
            "max_new_tokens_including_prefill_emission": args.max_new_tokens,
            "generation": "greedy",
            "prompt_format": args.prompt_format,
            "chat_role": "user" if args.prompt_format == "chat" else None,
            "add_generation_prompt": args.prompt_format == "chat",
            "enable_thinking": args.enable_thinking,
            "shard_size": args.shard_size,
            "storage_dtype": "float16",
            "seed": 20260730,
        },
        "software": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "mlx": importlib.metadata.version("mlx"),
            "mlx_lm": importlib.metadata.version("mlx-lm"),
        },
        "tensor_layout": {
            "input_ids": "[sample, decode_forward]",
            "emitted_ids": "[sample, decode_forward]",
            "router_logits": "[sample, layer, decode_forward, expert]",
            "topk_indices": "[sample, layer, decode_forward, rank]",
        },
        "shards": [],
    }
    atomic_json(manifest_path, manifest)

    local_model_path = Path(args.model).expanduser()
    if local_model_path.exists():
        resolved_model = str(local_model_path.resolve())
        model_commit = args.revision
        model, tokenizer, config = load(
            resolved_model,
            return_config=True,
        )
        manifest["model"]["local_path"] = resolved_model
    else:
        info = HfApi().model_info(args.model, revision=args.revision)
        model_commit = info.sha
        model, tokenizer, config = load(
            args.model,
            revision=model_commit,
            return_config=True,
        )
    num_layers = int(config["num_hidden_layers"])
    num_experts = int(config["num_experts"])
    top_k = int(config["num_experts_per_tok"])
    if (num_layers, num_experts, top_k) != (48, 128, 8):
        raise RuntimeError(
            "This experiment expects Qwen3-30B-A3B 48x128 top-8; "
            f"observed {(num_layers, num_experts, top_k)}."
        )
    sink = install_qwen3_route_capture(model, mx)
    eos_ids = normalize_eos_ids(config.get("eos_token_id"))
    manifest["model"].update(
        {
            "commit": model_commit,
            "model_type": config["model_type"],
            "num_layers": num_layers,
            "num_experts": num_experts,
            "top_k": top_k,
            "max_position_embeddings": int(
                config["max_position_embeddings"]
            ),
            "tokenizer_class": type(tokenizer).__name__,
            "eos_token_id": sorted(eos_ids),
            "quantization": config.get("quantization"),
        }
    )
    manifest["status"] = "in_progress"
    manifest["updated_at"] = utc_now()
    atomic_json(manifest_path, manifest)

    if hasattr(mx, "reset_peak_memory"):
        mx.reset_peak_memory()
    elif hasattr(mx.metal, "reset_peak_memory"):
        mx.metal.reset_peak_memory()
    started = time.perf_counter()
    buffer: list[dict[str, Any]] = []
    shard_index = 0
    for record in records:
        sample = collect_one(
            model=model,
            tokenizer=tokenizer,
            mx=mx,
            make_prompt_cache=make_prompt_cache,
            sink=sink,
            record=record,
            max_prompt_length=args.max_prompt_length,
            max_new_tokens=args.max_new_tokens,
            num_layers=num_layers,
            num_experts=num_experts,
            top_k=top_k,
            eos_ids=eos_ids,
            prompt_format=args.prompt_format,
            enable_thinking=args.enable_thinking,
        )
        buffer.append(sample)
        print(
            f"sample={record['id']} "
            f"decode_forwards={sample['stored_token_length']} "
            f"stop={sample['metadata']['stop_reason']}",
            flush=True,
        )
        if len(buffer) >= args.shard_size:
            start = int(manifest["completed_samples"])
            shard = write_shard(
                args.output,
                shard_index,
                start,
                buffer,
            )
            manifest["shards"].append(shard)
            manifest["completed_samples"] = shard["end_sample_exclusive"]
            manifest["updated_at"] = utc_now()
            atomic_json(manifest_path, manifest)
            buffer = []
            shard_index += 1
            mx.clear_cache()
    if buffer:
        start = int(manifest["completed_samples"])
        shard = write_shard(
            args.output,
            shard_index,
            start,
            buffer,
        )
        manifest["shards"].append(shard)
        manifest["completed_samples"] = shard["end_sample_exclusive"]

    manifest["status"] = "complete"
    manifest["updated_at"] = utc_now()
    manifest["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    if hasattr(mx, "get_peak_memory"):
        manifest["peak_metal_bytes"] = int(mx.get_peak_memory())
    elif hasattr(mx.metal, "get_peak_memory"):
        manifest["peak_metal_bytes"] = int(mx.metal.get_peak_memory())
    atomic_json(manifest_path, manifest)
    print(
        f"completed_samples={manifest['completed_samples']} "
        f"elapsed_seconds={manifest['elapsed_seconds']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
