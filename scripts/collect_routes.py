from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import os
import platform
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import torch
import torch.nn.functional as F
import transformers
from safetensors.torch import save_file
from transformers import AutoModelForCausalLM, AutoTokenizer


SCHEMA_VERSION = 1
MODELS = {
    "granite": "ibm-granite/granite-3.1-3b-a800m-base",
    "olmoe": "allenai/OLMoE-1B-7B-0125",
}
STORAGE_DTYPES = {
    "float16": torch.float16,
    "float32": torch.float32,
}
COMPUTE_DTYPES = {
    "float16": torch.float16,
    "float32": torch.float32,
    "bfloat16": torch.bfloat16,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)


def resolve_model_id(model: str) -> str:
    return MODELS.get(model, model)


def resolve_device(requested: str) -> torch.device:
    if requested == "auto":
        return torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    if requested == "mps" and not torch.backends.mps.is_available():
        raise RuntimeError("MPS was requested but is not available.")
    return torch.device(requested)


def resolve_compute_dtype(requested: str, device: torch.device) -> torch.dtype:
    if requested == "auto":
        return torch.float16 if device.type == "mps" else torch.float32
    return COMPUTE_DTYPES[requested]


def read_records(
    path: Path,
    text_field: str,
    id_field: str,
) -> Iterator[dict[str, Any]]:
    suffix = path.suffix.lower()
    with path.open("r", encoding="utf-8") as handle:
        logical_index = 0
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue

            if suffix == ".jsonl":
                try:
                    source = json.loads(stripped)
                except json.JSONDecodeError as error:
                    raise ValueError(
                        f"Invalid JSON on line {line_number}: {error}"
                    ) from error
                if not isinstance(source, dict):
                    raise ValueError(
                        f"Line {line_number} must contain a JSON object."
                    )
                text = source.get(text_field)
                if not isinstance(text, str) or not text:
                    raise ValueError(
                        f"Line {line_number} has no non-empty string field "
                        f"{text_field!r}."
                    )
                sample_id = source.get(id_field, str(logical_index))
                metadata = {
                    key: value
                    for key, value in source.items()
                    if key not in {text_field, id_field}
                }
            else:
                text = stripped
                sample_id = str(logical_index)
                metadata = {}

            yield {
                "source_line": line_number,
                "source_index": logical_index,
                "id": str(sample_id),
                "text": text,
                "metadata": metadata,
            }
            logical_index += 1


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


def stack_router_logits(
    router_logits: tuple[torch.Tensor, ...] | list[torch.Tensor],
    batch_size: int,
    sequence_length: int,
) -> torch.Tensor:
    layers: list[torch.Tensor] = []
    for layer_index, layer in enumerate(router_logits):
        if layer.ndim == 2:
            expected = batch_size * sequence_length
            if layer.shape[0] != expected:
                raise RuntimeError(
                    f"Layer {layer_index} has {layer.shape[0]} routed tokens; "
                    f"expected {expected}."
                )
            layer = layer.reshape(batch_size, sequence_length, -1)
        elif layer.ndim == 3:
            if tuple(layer.shape[:2]) != (batch_size, sequence_length):
                raise RuntimeError(
                    f"Unexpected router shape at layer {layer_index}: "
                    f"{tuple(layer.shape)}."
                )
        else:
            raise RuntimeError(
                f"Router logits at layer {layer_index} have unsupported "
                f"rank {layer.ndim}."
            )
        layers.append(layer)
    return torch.stack(layers, dim=1)


def routing_metrics(
    router_logits: torch.Tensor,
    top_k: int,
) -> dict[str, torch.Tensor]:
    probabilities = torch.softmax(router_logits.float(), dim=-1)
    topk_probabilities, topk_indices = probabilities.topk(top_k, dim=-1)
    topk_weights = topk_probabilities / topk_probabilities.sum(
        dim=-1, keepdim=True
    ).clamp_min(torch.finfo(torch.float32).tiny)
    entropy = -(
        probabilities
        * probabilities.clamp_min(torch.finfo(torch.float32).tiny).log()
    ).sum(dim=-1)
    normalized_entropy = entropy / math.log(probabilities.shape[-1])
    if top_k >= 2:
        margin = topk_probabilities[..., 0] - topk_probabilities[..., 1]
    else:
        margin = topk_probabilities[..., 0]
    return {
        "topk_indices": topk_indices,
        "topk_probabilities": topk_probabilities,
        "topk_weights": topk_weights,
        "router_entropy": entropy,
        "router_normalized_entropy": normalized_entropy,
        "router_margin": margin,
    }


def token_nll(
    logits: torch.Tensor,
    input_ids: torch.Tensor,
    attention_mask: torch.Tensor,
) -> torch.Tensor:
    result = torch.full(
        input_ids.shape,
        float("nan"),
        dtype=torch.float32,
        device=logits.device,
    )
    losses = F.cross_entropy(
        logits[:, :-1, :].float().transpose(1, 2),
        input_ids[:, 1:],
        reduction="none",
    )
    valid = attention_mask[:, 1:].bool()
    result[:, 1:] = torch.where(
        valid,
        losses,
        torch.full_like(losses, float("nan")),
    )
    return result


def write_shard(
    output_dir: Path,
    shard_index: int,
    start_index: int,
    samples: list[dict[str, Any]],
    store_text: bool,
    storage_dtype: torch.dtype,
) -> dict[str, Any]:
    count = len(samples)
    max_length = max(sample["stored_token_length"] for sample in samples)
    first = samples[0]
    num_layers, _, num_experts = first["router_logits"].shape
    top_k = first["topk_indices"].shape[-1]

    tensors: dict[str, torch.Tensor] = {
        "sample_indices": torch.arange(
            start_index, start_index + count, dtype=torch.int64
        ),
        "sequence_lengths": torch.zeros(count, dtype=torch.int32),
        "input_ids": torch.zeros((count, max_length), dtype=torch.int32),
        "attention_mask": torch.zeros((count, max_length), dtype=torch.bool),
        "router_logits": torch.zeros(
            (count, num_layers, max_length, num_experts),
            dtype=storage_dtype,
        ),
        "topk_indices": torch.full(
            (count, num_layers, max_length, top_k),
            -1,
            dtype=torch.int16,
        ),
        "topk_probabilities": torch.zeros(
            (count, num_layers, max_length, top_k),
            dtype=storage_dtype,
        ),
        "topk_weights": torch.zeros(
            (count, num_layers, max_length, top_k),
            dtype=storage_dtype,
        ),
        "router_entropy": torch.zeros(
            (count, num_layers, max_length),
            dtype=storage_dtype,
        ),
        "router_normalized_entropy": torch.zeros(
            (count, num_layers, max_length),
            dtype=storage_dtype,
        ),
        "router_margin": torch.zeros(
            (count, num_layers, max_length),
            dtype=storage_dtype,
        ),
    }
    if "token_nll" in first:
        tensors["token_nll"] = torch.full(
            (count, max_length), float("nan"), dtype=torch.float32
        )
    if "emitted_ids" in first:
        tensors["emitted_ids"] = torch.full(
            (count, max_length), -1, dtype=torch.int32
        )

    metadata_rows: list[dict[str, Any]] = []
    for row, sample in enumerate(samples):
        length = sample["stored_token_length"]
        tensors["sequence_lengths"][row] = length
        tensors["input_ids"][row, :length] = sample["input_ids"].to(torch.int32)
        tensors["attention_mask"][row, :length] = True
        for key in (
            "router_logits",
            "topk_indices",
            "topk_probabilities",
            "topk_weights",
            "router_entropy",
            "router_normalized_entropy",
            "router_margin",
        ):
            tensor = sample[key]
            if tensor.ndim == 3:
                tensors[key][row, :, :length, :] = tensor
            else:
                tensors[key][row, :, :length] = tensor
        if "token_nll" in sample:
            tensors["token_nll"][row, :length] = sample["token_nll"]
        if "emitted_ids" in sample:
            tensors["emitted_ids"][row, :length] = sample[
                "emitted_ids"
            ].to(torch.int32)

        metadata_row = {
            "collection_index": start_index + row,
            "id": sample["id"],
            "source_line": sample["source_line"],
            "source_index": sample["source_index"],
            "original_token_length": sample["original_token_length"],
            "stored_token_length": length,
            "truncated": sample["truncated"],
            "metadata": sample["metadata"],
        }
        if store_text:
            metadata_row["text"] = sample["text"]
        metadata_rows.append(metadata_row)

    tensor_name = f"routes-{shard_index:05d}.safetensors"
    metadata_name = f"samples-{shard_index:05d}.jsonl"
    tensor_path = output_dir / tensor_name
    metadata_path = output_dir / metadata_name
    tensor_tmp = output_dir / f".{tensor_name}.tmp"
    metadata_tmp = output_dir / f".{metadata_name}.tmp"

    save_file(tensors, tensor_tmp)
    with metadata_tmp.open("w", encoding="utf-8") as handle:
        for row in metadata_rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    os.replace(tensor_tmp, tensor_path)
    os.replace(metadata_tmp, metadata_path)

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


def validate_resume(
    manifest: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    checks = (
        ("model.id", manifest["model"]["id"], expected["model_id"]),
        ("model.revision", manifest["model"]["revision"], expected["revision"]),
        ("input.sha256", manifest["input"]["sha256"], expected["input_sha256"]),
        (
            "collection.max_length",
            manifest["collection"]["max_length"],
            expected["max_length"],
        ),
        (
            "collection.batch_size",
            manifest["collection"]["batch_size"],
            expected["batch_size"],
        ),
        (
            "collection.shard_size",
            manifest["collection"]["shard_size"],
            expected["shard_size"],
        ),
        (
            "collection.storage_dtype",
            manifest["collection"]["storage_dtype"],
            expected["storage_dtype"],
        ),
        (
            "collection.add_special_tokens",
            manifest["collection"]["add_special_tokens"],
            expected["add_special_tokens"],
        ),
        (
            "collection.capture_token_nll",
            manifest["collection"]["capture_token_nll"],
            expected["capture_token_nll"],
        ),
        (
            "collection.store_text",
            manifest["collection"]["store_text"],
            expected["store_text"],
        ),
        (
            "collection.compute_dtype",
            manifest["collection"]["compute_dtype"],
            expected["compute_dtype"],
        ),
        (
            "collection.device",
            manifest["collection"]["device"],
            expected["device"],
        ),
        (
            "collection.seed",
            manifest["collection"]["seed"],
            expected["seed"],
        ),
        (
            "collection.max_samples",
            manifest["collection"]["max_samples"],
            expected["max_samples"],
        ),
        ("input.text_field", manifest["input"]["text_field"], expected["text_field"]),
        ("input.id_field", manifest["input"]["id_field"], expected["id_field"]),
    )
    mismatches = [
        f"{name}: existing={actual!r}, requested={wanted!r}"
        for name, actual, wanted in checks
        if actual != wanted
    ]
    if mismatches:
        raise ValueError(
            "Cannot resume because collection settings changed:\n"
            + "\n".join(mismatches)
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect token-level MoE router telemetry."
    )
    parser.add_argument(
        "--model",
        required=True,
        help="granite, olmoe, or a Hugging Face model ID",
    )
    parser.add_argument("--revision", default="main")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--text-field", default="text")
    parser.add_argument("--id-field", default="id")
    parser.add_argument("--max-samples", type=int)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--shard-size", type=int, default=16)
    parser.add_argument(
        "--add-special-tokens",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--store-text",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--capture-token-nll",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    parser.add_argument(
        "--storage-dtype",
        choices=sorted(STORAGE_DTYPES),
        default="float16",
    )
    parser.add_argument(
        "--compute-dtype",
        choices=["auto", *sorted(COMPUTE_DTYPES)],
        default="auto",
    )
    parser.add_argument(
        "--device",
        choices=["auto", "mps", "cpu"],
        default="auto",
    )
    parser.add_argument("--seed", type=int, default=20260727)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--local-files-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.batch_size < 1 or args.shard_size < 1 or args.max_length < 2:
        raise ValueError("batch-size and shard-size must be positive; max-length >= 2.")
    if args.max_samples is not None and args.max_samples < 1:
        raise ValueError("max-samples must be positive.")
    if not args.input.is_file():
        raise FileNotFoundError(args.input)

    model_id = resolve_model_id(args.model)
    input_path = args.input.resolve()
    output_dir = args.output.resolve()
    input_sha256 = sha256_file(input_path)
    device = resolve_device(args.device)
    compute_dtype = resolve_compute_dtype(args.compute_dtype, device)
    storage_dtype = STORAGE_DTYPES[args.storage_dtype]

    random.seed(args.seed)
    torch.manual_seed(args.seed)

    expected = {
        "model_id": model_id,
        "revision": args.revision,
        "input_sha256": input_sha256,
        "max_length": args.max_length,
        "batch_size": args.batch_size,
        "shard_size": args.shard_size,
        "storage_dtype": args.storage_dtype,
        "compute_dtype": str(compute_dtype).removeprefix("torch."),
        "device": str(device),
        "add_special_tokens": args.add_special_tokens,
        "capture_token_nll": args.capture_token_nll,
        "store_text": args.store_text,
        "seed": args.seed,
        "max_samples": args.max_samples,
        "text_field": args.text_field,
        "id_field": args.id_field,
    }

    manifest_path = output_dir / "manifest.json"
    if output_dir.exists():
        if not args.resume:
            raise FileExistsError(
                f"Output directory already exists: {output_dir}. "
                "Choose a new directory or pass --resume."
            )
        if not manifest_path.is_file():
            raise FileNotFoundError(
                f"Cannot resume: {manifest_path} does not exist."
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        validate_resume(manifest, expected)
        if manifest["status"] == "complete":
            print(
                f"Collection is already complete: "
                f"{manifest['completed_samples']} samples."
            )
            return
        completed_samples = int(manifest["completed_samples"])
        shard_index = len(manifest["shards"])
    else:
        if args.resume:
            raise FileNotFoundError(
                f"Cannot resume because output directory does not exist: {output_dir}"
            )
        output_dir.mkdir(parents=True)
        completed_samples = 0
        shard_index = 0
        manifest = {
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
                "path": str(input_path),
                "sha256": input_sha256,
                "format": "jsonl" if input_path.suffix.lower() == ".jsonl" else "text",
                "text_field": args.text_field,
                "id_field": args.id_field,
            },
            "collection": {
                "max_samples": args.max_samples,
                "max_length": args.max_length,
                "batch_size": args.batch_size,
                "shard_size": args.shard_size,
                "add_special_tokens": args.add_special_tokens,
                "store_text": args.store_text,
                "capture_token_nll": args.capture_token_nll,
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
                "router_logits": "[sample, layer, token, expert]",
                "topk_indices": "[sample, layer, token, rank]",
                "topk_probabilities": "[sample, layer, token, rank]",
                "topk_weights": "[sample, layer, token, rank]",
                "router_entropy": "[sample, layer, token]",
                "router_normalized_entropy": "[sample, layer, token]",
                "router_margin": "[sample, layer, token]",
                "input_ids": "[sample, token]",
                "attention_mask": "[sample, token]",
                **(
                    {"token_nll": "[sample, token]"}
                    if args.capture_token_nll
                    else {}
                ),
            },
            "shards": [],
        }
        atomic_json(manifest_path, manifest)

    print(f"model={model_id}")
    print(f"device={device} compute_dtype={compute_dtype}")
    print(f"input={input_path}")
    print(f"output={output_dir}")
    if completed_samples:
        print(f"resume_from={completed_samples}")

    tokenizer = AutoTokenizer.from_pretrained(
        model_id,
        revision=args.revision,
        local_files_only=args.local_files_only,
    )
    if tokenizer.pad_token_id is None:
        fallback = tokenizer.eos_token or tokenizer.bos_token
        if fallback is None:
            raise RuntimeError("Tokenizer has no pad, eos, or bos token.")
        tokenizer.pad_token = fallback
    tokenizer.padding_side = "right"

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
    max_positions = int(getattr(config, "max_position_embeddings", args.max_length))
    if args.max_length > max_positions:
        raise ValueError(
            f"max-length={args.max_length} exceeds model limit {max_positions}."
        )

    manifest["model"].update(
        {
            "commit": getattr(config, "_commit_hash", None),
            "model_type": config.model_type,
            "num_layers": num_layers,
            "num_experts": num_experts,
            "top_k": top_k,
            "max_position_embeddings": max_positions,
            "tokenizer_class": tokenizer.__class__.__name__,
            "vocab_size": len(tokenizer),
            "pad_token_id": tokenizer.pad_token_id,
        }
    )
    manifest["status"] = "in_progress"
    manifest["updated_at"] = utc_now()
    atomic_json(manifest_path, manifest)
    print(f"loaded_in={time.perf_counter() - started:.2f}s")
    print(f"routing={num_layers} layers x {num_experts} experts, top_k={top_k}")

    records = read_records(input_path, args.text_field, args.id_field)
    for _ in range(completed_samples):
        try:
            next(records)
        except StopIteration as error:
            raise RuntimeError(
                "Input now contains fewer records than the existing collection."
            ) from error

    collected_buffer: list[dict[str, Any]] = []
    processed = completed_samples
    stop = False

    while not stop:
        raw_batch: list[dict[str, Any]] = []
        while len(raw_batch) < args.batch_size:
            if args.max_samples is not None and processed + len(raw_batch) >= args.max_samples:
                stop = True
                break
            try:
                raw_batch.append(next(records))
            except StopIteration:
                stop = True
                break
        if not raw_batch:
            break

        prepared: list[dict[str, Any]] = []
        for record in raw_batch:
            original_ids = tokenizer.encode(
                record["text"],
                add_special_tokens=args.add_special_tokens,
            )
            ids, truncated = truncate_ids(
                original_ids,
                args.max_length,
                tokenizer.truncation_side,
            )
            if not ids:
                raise ValueError(
                    f"Tokenizer produced no tokens for source line "
                    f"{record['source_line']}."
                )
            prepared.append(
                {
                    **record,
                    "ids": ids,
                    "original_token_length": len(original_ids),
                    "stored_token_length": len(ids),
                    "truncated": truncated,
                }
            )

        batch_length = max(item["stored_token_length"] for item in prepared)
        input_ids = torch.full(
            (len(prepared), batch_length),
            tokenizer.pad_token_id,
            dtype=torch.long,
        )
        attention_mask = torch.zeros(
            (len(prepared), batch_length),
            dtype=torch.long,
        )
        for row, item in enumerate(prepared):
            length = item["stored_token_length"]
            input_ids[row, :length] = torch.tensor(item["ids"], dtype=torch.long)
            attention_mask[row, :length] = 1

        input_ids = input_ids.to(device)
        attention_mask = attention_mask.to(device)
        with torch.inference_mode():
            outputs = model(
                input_ids=input_ids,
                attention_mask=attention_mask,
                output_router_logits=True,
                use_cache=False,
                return_dict=True,
                logits_to_keep=0 if args.capture_token_nll else 1,
            )
        if outputs.router_logits is None:
            raise RuntimeError(
                "Model returned no router logits. Check the Transformers version "
                "and whether this architecture supports output_router_logits."
            )

        all_router_logits = stack_router_logits(
            outputs.router_logits,
            len(prepared),
            batch_length,
        )
        if all_router_logits.shape[1:] != (
            num_layers,
            batch_length,
            num_experts,
        ):
            raise RuntimeError(
                f"Router tensor shape {tuple(all_router_logits.shape)} does not "
                f"match model config."
            )
        metrics = routing_metrics(all_router_logits, top_k)
        nll = (
            token_nll(outputs.logits, input_ids, attention_mask)
            if args.capture_token_nll
            else None
        )

        router_cpu = all_router_logits.to(
            device="cpu", dtype=storage_dtype
        )
        metric_cpu = {
            key: value.to(
                device="cpu",
                dtype=torch.int16 if key == "topk_indices" else storage_dtype,
            )
            for key, value in metrics.items()
        }
        input_ids_cpu = input_ids.to("cpu")
        nll_cpu = nll.to("cpu") if nll is not None else None

        for row, item in enumerate(prepared):
            length = item["stored_token_length"]
            collected = {
                key: value
                for key, value in item.items()
                if key != "ids"
            }
            collected.update(
                {
                    "input_ids": input_ids_cpu[row, :length].clone(),
                    "router_logits": router_cpu[row, :, :length, :].clone(),
                    **{
                        key: value[row, :, :length].clone()
                        for key, value in metric_cpu.items()
                    },
                }
            )
            if nll_cpu is not None:
                collected["token_nll"] = nll_cpu[row, :length].clone()
            collected_buffer.append(collected)
            processed += 1

        del (
            outputs,
            all_router_logits,
            metrics,
            router_cpu,
            metric_cpu,
            input_ids,
            attention_mask,
        )
        if nll is not None:
            del nll

        while len(collected_buffer) >= args.shard_size:
            shard_samples = collected_buffer[: args.shard_size]
            collected_buffer = collected_buffer[args.shard_size :]
            start_index = int(manifest["completed_samples"])
            shard = write_shard(
                output_dir,
                shard_index,
                start_index,
                shard_samples,
                args.store_text,
                storage_dtype,
            )
            manifest["shards"].append(shard)
            manifest["completed_samples"] = shard["end_sample_exclusive"]
            manifest["updated_at"] = utc_now()
            atomic_json(manifest_path, manifest)
            print(
                f"wrote={shard['tensor_file']} "
                f"samples={shard['start_sample']}:{shard['end_sample_exclusive']}"
            )
            shard_index += 1
            gc.collect()
            if device.type == "mps":
                torch.mps.empty_cache()

    if collected_buffer:
        start_index = int(manifest["completed_samples"])
        shard = write_shard(
            output_dir,
            shard_index,
            start_index,
            collected_buffer,
            args.store_text,
            storage_dtype,
        )
        manifest["shards"].append(shard)
        manifest["completed_samples"] = shard["end_sample_exclusive"]
        manifest["updated_at"] = utc_now()
        atomic_json(manifest_path, manifest)
        print(
            f"wrote={shard['tensor_file']} "
            f"samples={shard['start_sample']}:{shard['end_sample_exclusive']}"
        )

    manifest["status"] = "complete"
    manifest["updated_at"] = utc_now()
    manifest["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    atomic_json(manifest_path, manifest)
    print(f"completed_samples={manifest['completed_samples']}")
    print(f"elapsed_seconds={manifest['elapsed_seconds']}")
    print("status=OK")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted; completed shards can be resumed with --resume.", file=sys.stderr)
        raise SystemExit(130)
