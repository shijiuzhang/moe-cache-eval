#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from safetensors import safe_open

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moe_controller.metrics import normalized_topk_boundary_gap


QUANTILES = (0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99)
LOW_GAP_THRESHOLDS = (0.001, 0.005, 0.01, 0.02, 0.05, 0.10)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def summarize(values: np.ndarray) -> dict:
    result = {
        "count": int(values.size),
        "mean": float(values.mean()),
        "std": float(values.std()),
    }
    for quantile in QUANTILES:
        result[f"p{int(quantile * 100):02d}"] = float(
            np.quantile(values, quantile)
        )
    for threshold in LOW_GAP_THRESHOLDS:
        label = str(threshold).replace(".", "_")
        result[f"fraction_le_{label}"] = float(
            np.mean(values <= threshold)
        )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Profile normalized top-k router boundary gaps."
    )
    parser.add_argument("trace", type=Path)
    parser.add_argument("output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}.")
    manifest_path = args.trace / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    top_k = int(manifest["model"]["top_k"])
    num_layers = int(manifest["model"]["num_layers"])
    per_layer: list[list[np.ndarray]] = [[] for _ in range(num_layers)]

    for shard in manifest["shards"]:
        tensor_path = args.trace / shard["tensor_file"]
        if sha256_file(tensor_path) != shard["tensor_sha256"]:
            raise ValueError(f"Checksum mismatch: {tensor_path}")
        with safe_open(tensor_path, framework="pt", device="cpu") as handle:
            logits = handle.get_tensor("router_logits")
            lengths = handle.get_tensor("sequence_lengths")
        for row, length_value in enumerate(lengths.tolist()):
            length = int(length_value)
            gaps = normalized_topk_boundary_gap(
                logits[row, :, :length, :],
                top_k=top_k,
            ).numpy()
            for layer_id in range(num_layers):
                per_layer[layer_id].append(gaps[layer_id])

    args.output.mkdir(parents=True)
    layer_rows: list[dict] = []
    all_values: list[np.ndarray] = []
    for layer_id, chunks in enumerate(per_layer):
        values = np.concatenate(chunks).astype(np.float32, copy=False)
        all_values.append(values)
        layer_rows.append({"layer_id": layer_id, **summarize(values)})
    global_values = np.concatenate(all_values)
    global_summary = summarize(global_values)

    csv_path = args.output / "boundary-gap-by-layer.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(layer_rows[0]))
        writer.writeheader()
        writer.writerows(layer_rows)
    output_manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "metric": "(z_k-z_k+1)/population_std(all_router_logits)",
        "source_trace": str(args.trace.resolve()),
        "source_manifest_sha256": sha256_file(manifest_path),
        "model": manifest["model"],
        "global": global_summary,
        "artifacts": {
            "by_layer": {
                "path": csv_path.name,
                "sha256": sha256_file(csv_path),
                "bytes": csv_path.stat().st_size,
            }
        },
    }
    (args.output / "summary.json").write_text(
        json.dumps(output_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(global_summary, indent=2))


if __name__ == "__main__":
    main()
