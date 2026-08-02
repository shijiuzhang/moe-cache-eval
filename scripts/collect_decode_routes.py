#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import json
import platform
import random
import sys
import time
from pathlib import Path
from typing import Any

import torch
import transformers
from transformers import AutoModelForCausalLM, AutoTokenizer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.collect_routes import (  # noqa: E402
    STORAGE_DTYPES,
    atomic_json,
    read_records,
    resolve_compute_dtype,
    resolve_device,
    resolve_model_id,
    routing_metrics,
    sha256_file,
    stack_router_logits,
    truncate_ids,
    utc_now,
    write_shard,
)


SCHEMA_VERSION = 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect true autoregressive MoE decode router traces."
    )
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", default="main")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--text-field", default="text")
    parser.add_argument("--id-field", default="id")
    parser.add_argument("--split", default="discovery")
    parser.add_argument("--category-field", default="workload_archetype")
    parser.add_argument("--samples-per-category", type=int, default=20)
    parser.add_argument("--max-prompt-length", type=int, default=512)
    parser.add_argument("--max-new-tokens", type=int, default=64)
    parser.add_argument("--shard-size", type=int, default=8)
    parser.add_argument("--storage-dtype", choices=sorted(STORAGE_DTYPES), default="float16")
    parser.add_argument(
        "--compute-dtype",
        choices=["auto", "float16", "float32", "bfloat16"],
        default="auto",
    )
    parser.add_argument("--device", choices=["auto", "mps", "cpu"], default="auto")
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--local-files-only", action="store_true")
    return parser.parse_args()


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
    for record in read_records(path, text_field, id_field):
        metadata = record["metadata"]
        if metadata.get("split") != split:
            continue
        category = metadata.get(category_field)
        if not isinstance(category, str) or not category:
            raise ValueError(
                f"Record {record['id']} has no {category_field!r}."
            )
        grouped.setdefault(category, []).append(record)
    categories = sorted(grouped)
    if not categories:
        raise ValueError(f"No records matched split={split!r}.")
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


def empty_metrics(
    *,
    num_layers: int,
    num_experts: int,
    top_k: int,
    storage_dtype: torch.dtype,
) -> dict[str, torch.Tensor]:
    return {
        "router_logits": torch.empty(
            (num_layers, 0, num_experts), dtype=storage_dtype
        ),
        "topk_indices": torch.empty(
            (num_layers, 0, top_k), dtype=torch.int16
        ),
        "topk_probabilities": torch.empty(
            (num_layers, 0, top_k), dtype=storage_dtype
        ),
        "topk_weights": torch.empty(
            (num_layers, 0, top_k), dtype=storage_dtype
        ),
        "router_entropy": torch.empty(
            (num_layers, 0), dtype=storage_dtype
        ),
        "router_normalized_entropy": torch.empty(
            (num_layers, 0), dtype=storage_dtype
        ),
        "router_margin": torch.empty(
            (num_layers, 0), dtype=storage_dtype
        ),
    }


def collect_one(
    *,
    model,
    tokenizer,
    record: dict[str, Any],
    device: torch.device,
    storage_dtype: torch.dtype,
    max_prompt_length: int,
    max_new_tokens: int,
    num_layers: int,
    num_experts: int,
    top_k: int,
) -> dict[str, Any]:
    original_ids = tokenizer.encode(record["text"], add_special_tokens=True)
    prompt_ids, truncated = truncate_ids(
        original_ids,
        max_prompt_length,
        tokenizer.truncation_side,
    )
    if not prompt_ids:
        raise ValueError(f"Tokenizer produced no tokens for {record['id']}.")
    prompt = torch.tensor([prompt_ids], dtype=torch.long, device=device)

    with torch.inference_mode():
        outputs = model(
            input_ids=prompt,
            output_router_logits=False,
            use_cache=True,
            return_dict=True,
            logits_to_keep=1,
        )
    current = outputs.logits[:, -1, :].argmax(dim=-1, keepdim=True)
    past_key_values = outputs.past_key_values
    first_emitted_id = int(current.item())
    del outputs

    consumed_ids: list[int] = []
    emitted_ids: list[int] = []
    metric_parts: dict[str, list[torch.Tensor]] = {
        "router_logits": [],
        "topk_indices": [],
        "topk_probabilities": [],
        "topk_weights": [],
        "router_entropy": [],
        "router_normalized_entropy": [],
        "router_margin": [],
    }
    eos_id = tokenizer.eos_token_id
    total_emitted = 1
    stop_reason = "max_new_tokens"

    while total_emitted < max_new_tokens:
        if eos_id is not None and int(current.item()) == eos_id:
            stop_reason = "eos"
            break
        with torch.inference_mode():
            outputs = model(
                input_ids=current,
                past_key_values=past_key_values,
                output_router_logits=True,
                use_cache=True,
                return_dict=True,
                logits_to_keep=1,
            )
        if outputs.router_logits is None:
            raise RuntimeError("Decode forward returned no router logits.")
        router = stack_router_logits(outputs.router_logits, 1, 1)
        if tuple(router.shape) != (1, num_layers, 1, num_experts):
            raise RuntimeError(
                f"Unexpected decode router shape {tuple(router.shape)}."
            )
        metrics = routing_metrics(router, top_k)
        metric_parts["router_logits"].append(
            router[0].to(device="cpu", dtype=storage_dtype)
        )
        for key, value in metrics.items():
            metric_parts[key].append(
                value[0].to(
                    device="cpu",
                    dtype=(
                        torch.int16
                        if key == "topk_indices"
                        else storage_dtype
                    ),
                )
            )
        consumed_ids.append(int(current.item()))
        next_token = outputs.logits[:, -1, :].argmax(
            dim=-1,
            keepdim=True,
        )
        emitted_ids.append(int(next_token.item()))
        past_key_values = outputs.past_key_values
        current = next_token
        total_emitted += 1
        del outputs, router, metrics

    if (
        total_emitted >= max_new_tokens
        and eos_id is not None
        and int(current.item()) == eos_id
    ):
        stop_reason = "eos"

    if consumed_ids:
        collected_metrics = {
            key: torch.cat(parts, dim=1)
            for key, parts in metric_parts.items()
        }
    else:
        collected_metrics = empty_metrics(
            num_layers=num_layers,
            num_experts=num_experts,
            top_k=top_k,
            storage_dtype=storage_dtype,
        )
    metadata = {
        **record["metadata"],
        "decode_alignment": (
            "input_ids[t] consumed by decode forward t; "
            "emitted_ids[t] emitted by that forward"
        ),
        "first_emitted_id_from_prefill": first_emitted_id,
        "prompt_original_token_length": len(original_ids),
        "prompt_stored_token_length": len(prompt_ids),
        "prompt_truncated": truncated,
        "total_emitted_tokens_including_prefill": total_emitted,
        "decode_forward_count": len(consumed_ids),
        "stop_reason": stop_reason,
    }
    return {
        "id": record["id"],
        "source_line": record["source_line"],
        "source_index": record["source_index"],
        "text": record["text"],
        "metadata": metadata,
        "original_token_length": len(consumed_ids),
        "stored_token_length": len(consumed_ids),
        "truncated": False,
        "input_ids": torch.tensor(consumed_ids, dtype=torch.int32),
        "emitted_ids": torch.tensor(emitted_ids, dtype=torch.int32),
        **collected_metrics,
    }


def main() -> None:
    args = parse_args()
    if args.samples_per_category < 1:
        raise ValueError("samples-per-category must be positive.")
    if args.max_prompt_length < 2 or args.max_new_tokens < 2:
        raise ValueError("Prompt and generation lengths must be at least 2.")
    if args.shard_size < 1:
        raise ValueError("shard-size must be positive.")
    if args.output.exists():
        raise FileExistsError(f"Output already exists: {args.output}.")

    model_id = resolve_model_id(args.model)
    device = resolve_device(args.device)
    compute_dtype = resolve_compute_dtype(args.compute_dtype, device)
    storage_dtype = STORAGE_DTYPES[args.storage_dtype]
    random.seed(args.seed)
    torch.manual_seed(args.seed)
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
            "id": model_id,
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
            "selection": "first_n_per_sorted_category",
            "samples_per_category": args.samples_per_category,
            "selected_samples": len(records),
            "max_prompt_length": args.max_prompt_length,
            "max_new_tokens_including_prefill_emission": args.max_new_tokens,
            "generation": "greedy",
            "shard_size": args.shard_size,
            "storage_dtype": args.storage_dtype,
            "compute_dtype": str(compute_dtype).removeprefix("torch."),
            "device": str(device),
            "seed": args.seed,
        },
        "software": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "torch": torch.__version__,
            "transformers": transformers.__version__,
        },
        "tensor_layout": {
            "sample_indices": "[sample]",
            "sequence_lengths": "[sample]",
            "input_ids": "[sample, decode_forward]",
            "emitted_ids": "[sample, decode_forward]",
            "router_logits": "[sample, layer, decode_forward, expert]",
            "topk_indices": "[sample, layer, decode_forward, rank]",
            "topk_probabilities": "[sample, layer, decode_forward, rank]",
            "topk_weights": "[sample, layer, decode_forward, rank]",
            "router_entropy": "[sample, layer, decode_forward]",
            "router_normalized_entropy": (
                "[sample, layer, decode_forward]"
            ),
            "router_margin": "[sample, layer, decode_forward]",
        },
        "shards": [],
    }
    atomic_json(manifest_path, manifest)

    tokenizer = AutoTokenizer.from_pretrained(
        model_id,
        revision=args.revision,
        local_files_only=args.local_files_only,
    )
    started = time.perf_counter()
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        revision=args.revision,
        dtype=compute_dtype,
        low_cpu_mem_usage=True,
        local_files_only=args.local_files_only,
    )
    model.to(device)
    model.eval()
    config = model.config
    num_layers = int(config.num_hidden_layers)
    num_experts = int(
        getattr(config, "num_local_experts", None)
        or getattr(config, "num_experts", None)
    )
    top_k = int(
        getattr(config, "num_experts_per_tok", None)
        or getattr(config, "num_experts_per_token", None)
    )
    max_positions = int(
        getattr(config, "max_position_embeddings", args.max_prompt_length)
    )
    if args.max_prompt_length + args.max_new_tokens > max_positions:
        raise ValueError("Requested prompt + generation exceeds model limit.")
    manifest["model"].update(
        {
            "commit": getattr(config, "_commit_hash", None),
            "model_type": config.model_type,
            "num_layers": num_layers,
            "num_experts": num_experts,
            "top_k": top_k,
            "max_position_embeddings": max_positions,
            "tokenizer_class": tokenizer.__class__.__name__,
            "eos_token_id": tokenizer.eos_token_id,
        }
    )
    manifest["status"] = "in_progress"
    manifest["updated_at"] = utc_now()
    atomic_json(manifest_path, manifest)
    print(
        f"model={model_id} device={device} "
        f"routing={num_layers}x{num_experts} top_k={top_k}",
        flush=True,
    )

    buffer: list[dict[str, Any]] = []
    shard_index = 0
    for record in records:
        sample = collect_one(
            model=model,
            tokenizer=tokenizer,
            record=record,
            device=device,
            storage_dtype=storage_dtype,
            max_prompt_length=args.max_prompt_length,
            max_new_tokens=args.max_new_tokens,
            num_layers=num_layers,
            num_experts=num_experts,
            top_k=top_k,
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
                True,
                storage_dtype,
            )
            manifest["shards"].append(shard)
            manifest["completed_samples"] = shard["end_sample_exclusive"]
            manifest["updated_at"] = utc_now()
            atomic_json(manifest_path, manifest)
            buffer = []
            shard_index += 1
            gc.collect()
            if device.type == "mps":
                torch.mps.empty_cache()
    if buffer:
        start = int(manifest["completed_samples"])
        shard = write_shard(
            args.output,
            shard_index,
            start,
            buffer,
            True,
            storage_dtype,
        )
        manifest["shards"].append(shard)
        manifest["completed_samples"] = shard["end_sample_exclusive"]

    manifest["status"] = "complete"
    manifest["updated_at"] = utc_now()
    manifest["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    atomic_json(manifest_path, manifest)
    print(
        f"completed_samples={manifest['completed_samples']} "
        f"elapsed_seconds={manifest['elapsed_seconds']}",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        raise SystemExit(130)
