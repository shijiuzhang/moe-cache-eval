from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import torch
from safetensors import safe_open


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect a route collection.")
    parser.add_argument("collection", type=Path)
    parser.add_argument("--verify-checksums", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = args.collection.resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    model = manifest["model"]

    print(f"status={manifest['status']}")
    print(f"model={model['id']} revision={model['revision']}")
    print(
        f"routing={model['num_layers']} layers x "
        f"{model['num_experts']} experts, top_k={model['top_k']}"
    )
    print(
        f"samples={manifest['completed_samples']} "
        f"shards={len(manifest['shards'])}"
    )

    usage = torch.zeros(
        (model["num_layers"], model["num_experts"]),
        dtype=torch.int64,
    )
    metadata_rows = 0
    for shard in manifest["shards"]:
        tensor_path = root / shard["tensor_file"]
        metadata_path = root / shard["metadata_file"]
        if args.verify_checksums:
            if sha256_file(tensor_path) != shard["tensor_sha256"]:
                raise RuntimeError(f"Checksum mismatch: {tensor_path}")
            if sha256_file(metadata_path) != shard["metadata_sha256"]:
                raise RuntimeError(f"Checksum mismatch: {metadata_path}")

        with safe_open(tensor_path, framework="pt", device="cpu") as handle:
            topk = handle.get_tensor("topk_indices")
            topk_probabilities = handle.get_tensor("topk_probabilities")
            topk_weights = handle.get_tensor("topk_weights")
            margin = handle.get_tensor("router_margin")
            attention_mask = handle.get_tensor("attention_mask")
            sequence_lengths = handle.get_tensor("sequence_lengths")
            router_shape = handle.get_slice("router_logits").get_shape()
        expected_prefix = [
            shard["num_samples"],
            model["num_layers"],
            shard["max_sequence_length"],
            model["num_experts"],
        ]
        if list(router_shape) != expected_prefix:
            raise RuntimeError(
                f"Unexpected router shape in {tensor_path}: {router_shape}"
            )

        valid = attention_mask[:, None, :, None].expand_as(topk)
        if not torch.equal(
            sequence_lengths.to(torch.int64),
            attention_mask.sum(dim=1).to(torch.int64),
        ):
            raise RuntimeError(f"Sequence length mismatch in {tensor_path}.")
        if torch.any(topk[valid] < 0) or torch.any(
            topk[valid] >= model["num_experts"]
        ):
            raise RuntimeError(f"Invalid expert index in {tensor_path}.")
        if torch.any(topk[~valid] != -1):
            raise RuntimeError(f"Unmasked padded expert index in {tensor_path}.")

        valid_tokens = attention_mask[:, None, :].expand(
            -1, model["num_layers"], -1
        )
        weight_sums = topk_weights.float().sum(dim=-1)
        if not torch.allclose(
            weight_sums[valid_tokens],
            torch.ones_like(weight_sums[valid_tokens]),
            atol=3e-3,
            rtol=3e-3,
        ):
            raise RuntimeError(f"Top-k weights do not sum to one in {tensor_path}.")
        if torch.any(
            topk_probabilities[..., :-1][valid[..., :-1]]
            < topk_probabilities[..., 1:][valid[..., 1:]]
        ):
            raise RuntimeError(f"Top-k probabilities are not sorted in {tensor_path}.")
        expected_margin = (
            topk_probabilities[..., 0] - topk_probabilities[..., 1]
        ).float()
        if not torch.allclose(
            margin.float()[valid_tokens],
            expected_margin[valid_tokens],
            atol=3e-3,
            rtol=3e-3,
        ):
            raise RuntimeError(f"Router margin mismatch in {tensor_path}.")

        for layer in range(model["num_layers"]):
            selected = topk[:, layer][valid[:, layer]]
            usage[layer] += torch.bincount(
                selected.to(torch.int64),
                minlength=model["num_experts"],
            )

        with metadata_path.open("r", encoding="utf-8") as handle:
            metadata_rows += sum(1 for line in handle if line.strip())

    if metadata_rows != manifest["completed_samples"]:
        raise RuntimeError(
            f"Metadata rows={metadata_rows}, expected={manifest['completed_samples']}."
        )

    layers = sorted({0, model["num_layers"] // 2, model["num_layers"] - 1})
    for layer in layers:
        counts, experts = usage[layer].topk(min(5, model["num_experts"]))
        summary = ", ".join(
            f"E{int(expert)}={int(count)}"
            for expert, count in zip(experts, counts)
        )
        print(f"layer_{layer}_top_experts: {summary}")
    print("status=OK")


if __name__ == "__main__":
    main()
