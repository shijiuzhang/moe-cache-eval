#!/usr/bin/env python3
"""Split one mixed decode schedule into category-labelled cache event traces."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from safetensors import safe_open

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moe_controller.events import PHASE_DECODE, save_event_trace, sha256_file


def parse_partition(value: str) -> tuple[str, tuple[str, ...]]:
    name, separator, categories = value.partition("=")
    members = tuple(item.strip() for item in categories.split(",") if item.strip())
    if not separator or not name or not members:
        raise argparse.ArgumentTypeError("partition must be NAME=category[,category]")
    return name, members


def build_partitioned_events(
    routes_root: Path,
    base_events_root: Path,
    output_root: Path,
    *,
    partitions: dict[str, tuple[str, ...]],
    category_field: str = "workload_archetype",
) -> Path:
    if output_root.exists():
        raise FileExistsError(f"Output exists: {output_root}")
    category_to_partition: dict[str, str] = {}
    for partition, categories in partitions.items():
        for category in categories:
            if category in category_to_partition:
                raise ValueError(f"Category {category!r} occurs in two partitions.")
            category_to_partition[category] = partition

    route_manifest = json.loads((routes_root / "manifest.json").read_text())
    base_manifest = json.loads((base_events_root / "manifest.json").read_text())
    schedule_rows = [
        json.loads(line)
        for line in (base_events_root / "schedule.jsonl").read_text().splitlines()
        if line.strip()
    ]
    base_request_rows = [
        json.loads(line)
        for line in (base_events_root / "requests.jsonl").read_text().splitlines()
        if line.strip()
    ]
    selected_indices = {int(row["collection_index"]) for row in base_request_rows}
    samples: dict[int, dict] = {}
    for shard in route_manifest["shards"]:
        tensor_path = routes_root / shard["tensor_file"]
        metadata_path = routes_root / shard["metadata_file"]
        if sha256_file(tensor_path) != shard["tensor_sha256"]:
            raise ValueError(f"Checksum mismatch: {tensor_path}")
        if sha256_file(metadata_path) != shard["metadata_sha256"]:
            raise ValueError(f"Checksum mismatch: {metadata_path}")
        metadata_rows = [
            json.loads(line)
            for line in metadata_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        with safe_open(tensor_path, framework="numpy") as handle:
            indices = handle.get_tensor("sample_indices")
            lengths = handle.get_tensor("sequence_lengths")
            topk = handle.get_tensor("topk_indices")
            weights = handle.get_tensor("topk_weights").astype(np.float64)
        for local_index, index_value in enumerate(indices):
            request_index = int(index_value)
            if request_index not in selected_indices:
                continue
            row = metadata_rows[local_index]
            length = int(lengths[local_index])
            category = row["metadata"].get(category_field)
            if category not in category_to_partition:
                raise ValueError(f"No partition for category {category!r}.")
            samples[request_index] = {
                "row": row,
                "length": length,
                "category": category,
                "partition": category_to_partition[category],
                "topk": topk[local_index, :, :length, :].astype(
                    np.int64, copy=True
                ),
                "weights": weights[local_index, :, :length, :].copy(),
            }
    missing = selected_indices - set(samples)
    if missing:
        raise ValueError(f"Route artifact lacks {len(missing)} scheduled requests.")

    model = route_manifest["model"]
    num_layers = int(model["num_layers"])
    num_experts = int(model["num_experts"])
    state = {
        name: {
            "request_indices": [],
            "scheduler_steps": [],
            "forward_cycles": [],
            "phases": [],
            "layer_ids": [],
            "token_counts": [],
            "offsets": [0],
            "expert_ids": [],
            "assignment_counts": [],
            "gate_mass": [],
            "logical": 0,
            "decode_forwards": 0,
        }
        for name in partitions
    }

    for schedule in schedule_rows:
        scheduler_step = int(schedule["scheduler_step"])
        grouped: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for request_index, position in zip(
            schedule["active_request_indices"], schedule["decode_positions"]
        ):
            sample = samples[int(request_index)]
            grouped[sample["partition"]].append((int(request_index), int(position)))
        for partition, active in grouped.items():
            target = state[partition]
            target["decode_forwards"] += len(active)
            for layer_id in range(num_layers):
                ids = np.concatenate(
                    [samples[index]["topk"][layer_id, position] for index, position in active]
                )
                weights = np.concatenate(
                    [samples[index]["weights"][layer_id, position] for index, position in active]
                )
                valid = ids >= 0
                ids = ids[valid]
                weights = weights[valid]
                counts = np.bincount(ids, minlength=num_experts)
                masses = np.bincount(ids, weights=weights, minlength=num_experts)
                union = np.flatnonzero(counts)
                target["logical"] += int(counts.sum())
                target["request_indices"].append(-1)
                target["scheduler_steps"].append(scheduler_step)
                target["forward_cycles"].append(scheduler_step)
                target["phases"].append(PHASE_DECODE)
                target["layer_ids"].append(layer_id)
                target["token_counts"].append(len(active))
                target["expert_ids"].extend(union.tolist())
                target["assignment_counts"].extend(counts[union].astype(int).tolist())
                target["gate_mass"].extend(masses[union].tolist())
                target["offsets"].append(len(target["expert_ids"]))

    output_root.mkdir(parents=True)
    partition_manifests: dict[str, dict] = {}
    for partition, target in state.items():
        root = output_root / partition
        root.mkdir()
        rows = [
            samples[index]["row"]
            for index in sorted(selected_indices)
            if samples[index]["partition"] == partition
        ]
        requests_path = root / "requests.jsonl"
        requests_path.write_text(
            "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        manifest = {
            "status": "complete",
            "kind": "decode_event_trace",
            "source": {
                "routes_root": str(routes_root.resolve()),
                "base_events_root": str(base_events_root.resolve()),
                "base_manifest_sha256": sha256_file(base_events_root / "manifest.json"),
            },
            "conversion": {
                "scheduler": "FCFS",
                "batch_size": int(base_manifest["conversion"]["batch_size"]),
                "queue_order": base_manifest["conversion"]["queue_order"],
                "same_step_cross_request_dedup": True,
                "event_semantics": "expert_union_per_layer_within_partition",
                "partition": partition,
                "categories": list(partitions[partition]),
                "category_field": category_field,
            },
            "model": {
                "id": model["id"],
                "commit": model["commit"],
                "model_type": model["model_type"],
                "num_layers": num_layers,
                "num_experts": num_experts,
                "top_k": int(model["top_k"]),
            },
            "counts": {
                "requests": len(rows),
                "decode_forwards": int(target["decode_forwards"]),
                "scheduler_steps": len(set(target["scheduler_steps"])),
                "events": len(target["layer_ids"]),
                "union_expert_accesses": len(target["expert_ids"]),
                "logical_expert_assignments_before_dedup": int(target["logical"]),
            },
            "artifacts": {
                "requests": {
                    "path": requests_path.name,
                    "sha256": sha256_file(requests_path),
                    "bytes": requests_path.stat().st_size,
                }
            },
        }
        save_event_trace(
            root,
            manifest=manifest,
            request_indices=np.asarray(target["request_indices"]),
            scheduler_steps=np.asarray(target["scheduler_steps"]),
            forward_cycles=np.asarray(target["forward_cycles"]),
            phases=np.asarray(target["phases"]),
            layer_ids=np.asarray(target["layer_ids"]),
            token_counts=np.asarray(target["token_counts"]),
            offsets=np.asarray(target["offsets"]),
            expert_ids=np.asarray(target["expert_ids"]),
            assignment_counts=np.asarray(target["assignment_counts"]),
            gate_mass=np.asarray(target["gate_mass"]),
        )
        manifest_path = root / "manifest.json"
        partition_manifests[partition] = {
            "path": str(Path(partition) / "manifest.json"),
            "sha256": sha256_file(manifest_path),
        }

    (output_root / "manifest.json").write_text(
        json.dumps(
            {
                "status": "complete",
                "kind": "partitioned_decode_event_traces",
                "partitions": {key: list(value) for key, value in partitions.items()},
                "artifacts": partition_manifests,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return output_root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("routes", type=Path)
    parser.add_argument("base_events", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--partition", action="append", type=parse_partition, required=True)
    parser.add_argument("--category-field", default="workload_archetype")
    args = parser.parse_args()
    partitions = dict(args.partition)
    if len(partitions) != len(args.partition):
        raise ValueError("Partition names must be unique.")
    output = build_partitioned_events(
        args.routes,
        args.base_events,
        args.output,
        partitions=partitions,
        category_field=args.category_field,
    )
    print(output)


if __name__ == "__main__":
    main()
