from __future__ import annotations

import json
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from safetensors import safe_open

from .events import (
    PHASE_DECODE,
    PHASE_PREFILL,
    save_event_trace,
    sha256_file,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def convert_prefill_trace(
    source_root: Path | str,
    output_root: Path | str,
    *,
    prefill_chunk_size: int,
    verify_source_checksums: bool = True,
) -> Path:
    if prefill_chunk_size <= 0:
        raise ValueError("prefill_chunk_size must be positive.")
    source_root = Path(source_root)
    output_root = Path(output_root)
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(
            f"Output directory is not empty: {output_root}"
        )
    source_manifest_path = source_root / "manifest.json"
    source_manifest = json.loads(
        source_manifest_path.read_text(encoding="utf-8")
    )
    model = source_manifest["model"]
    num_layers = int(model["num_layers"])
    num_experts = int(model["num_experts"])

    event_request_indices: list[int] = []
    event_scheduler_steps: list[int] = []
    event_forward_cycles: list[int] = []
    event_phases: list[int] = []
    event_layer_ids: list[int] = []
    event_token_counts: list[int] = []
    event_offsets = [0]
    access_expert_ids: list[int] = []
    access_assignment_counts: list[int] = []
    access_gate_mass: list[float] = []
    request_rows: list[dict] = []

    forward_cycle = 0
    for shard in source_manifest["shards"]:
        tensor_path = source_root / shard["tensor_file"]
        metadata_path = source_root / shard["metadata_file"]
        if verify_source_checksums:
            observed = sha256_file(tensor_path)
            if observed != shard["tensor_sha256"]:
                raise ValueError(
                    f"Source tensor checksum mismatch for {tensor_path}."
                )
            observed = sha256_file(metadata_path)
            if observed != shard["metadata_sha256"]:
                raise ValueError(
                    f"Source metadata checksum mismatch for {metadata_path}."
                )
        with metadata_path.open("r", encoding="utf-8") as handle:
            shard_rows = [json.loads(line) for line in handle if line.strip()]
        with safe_open(tensor_path, framework="pt", device="cpu") as handle:
            sample_indices = handle.get_tensor("sample_indices").numpy()
            sequence_lengths = handle.get_tensor("sequence_lengths").numpy()
            topk_indices = handle.get_tensor("topk_indices").numpy()
            topk_weights = handle.get_tensor("topk_weights").float().numpy()
        if len(shard_rows) != len(sample_indices):
            raise ValueError(
                f"Metadata/tensor sample mismatch in shard {shard['index']}."
            )
        if topk_indices.shape[1] != num_layers:
            raise ValueError("Trace layer count differs from its manifest.")

        for local_index, request_index_value in enumerate(sample_indices):
            request_index = int(request_index_value)
            row = dict(shard_rows[local_index])
            if int(row["collection_index"]) != request_index:
                raise ValueError(
                    "Metadata collection index differs from tensor index."
                )
            request_rows.append(row)
            length = int(sequence_lengths[local_index])
            if length <= 0:
                continue
            for chunk_start in range(0, length, prefill_chunk_size):
                chunk_end = min(length, chunk_start + prefill_chunk_size)
                chunk_token_count = chunk_end - chunk_start
                for layer_id in range(num_layers):
                    ids = topk_indices[
                        local_index,
                        layer_id,
                        chunk_start:chunk_end,
                        :,
                    ].reshape(-1)
                    weights = topk_weights[
                        local_index,
                        layer_id,
                        chunk_start:chunk_end,
                        :,
                    ].reshape(-1)
                    valid = ids >= 0
                    ids = ids[valid].astype(np.int64, copy=False)
                    weights = weights[valid].astype(np.float64, copy=False)
                    counts = np.bincount(ids, minlength=num_experts)
                    masses = np.bincount(
                        ids,
                        weights=weights,
                        minlength=num_experts,
                    )
                    active = np.flatnonzero(counts)

                    event_request_indices.append(request_index)
                    event_scheduler_steps.append(forward_cycle)
                    event_forward_cycles.append(forward_cycle)
                    event_phases.append(PHASE_PREFILL)
                    event_layer_ids.append(layer_id)
                    event_token_counts.append(chunk_token_count)
                    access_expert_ids.extend(active.tolist())
                    access_assignment_counts.extend(
                        counts[active].astype(np.int64).tolist()
                    )
                    access_gate_mass.extend(masses[active].tolist())
                    event_offsets.append(len(access_expert_ids))
                forward_cycle += 1

    output_root.mkdir(parents=True, exist_ok=True)
    requests_path = output_root / "requests.jsonl"
    with requests_path.open("w", encoding="utf-8") as handle:
        for row in sorted(request_rows, key=lambda item: item["collection_index"]):
            handle.write(
                json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            )

    manifest = {
        "created_at": utc_now(),
        "status": "complete",
        "kind": "prefill_event_trace",
        "source": {
            "root": str(source_root.resolve()),
            "manifest_sha256": sha256_file(source_manifest_path),
            "completed_samples": int(source_manifest["completed_samples"]),
        },
        "conversion": {
            "prefill_chunk_size": prefill_chunk_size,
            "expert_access_order": "expert_id_ascending",
            "gate_mass": "sum_of_topk_normalized_weights",
            "duplicate_experts_within_event": "deduplicated",
            "source_checksums_verified": verify_source_checksums,
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
            "requests": len(request_rows),
            "forward_cycles": forward_cycle,
            "events": len(event_layer_ids),
            "expert_accesses": len(access_expert_ids),
        },
        "artifacts": {
            "requests": {
                "path": requests_path.name,
                "sha256": sha256_file(requests_path),
                "bytes": requests_path.stat().st_size,
            }
        },
    }
    return save_event_trace(
        output_root,
        manifest=manifest,
        request_indices=np.asarray(event_request_indices),
        scheduler_steps=np.asarray(event_scheduler_steps),
        forward_cycles=np.asarray(event_forward_cycles),
        phases=np.asarray(event_phases),
        layer_ids=np.asarray(event_layer_ids),
        token_counts=np.asarray(event_token_counts),
        offsets=np.asarray(event_offsets),
        expert_ids=np.asarray(access_expert_ids),
        assignment_counts=np.asarray(access_assignment_counts),
        gate_mass=np.asarray(access_gate_mass),
    )


def convert_decode_trace(
    source_root: Path | str,
    output_root: Path | str,
    *,
    batch_size: int,
    queue_order: str = "category_round_robin",
    category_field: str = "workload_archetype",
    include_categories: tuple[str, ...] | None = None,
    include_request_ids: tuple[str, ...] | None = None,
    requests_per_category: int | None = None,
    arrival_offset_field: str | None = None,
    arrival_offset_map: dict[str, int] | None = None,
    verify_source_checksums: bool = True,
) -> Path:
    """Build FCFS decode events with same-step cross-request expert union."""
    if batch_size <= 0:
        raise ValueError("batch_size must be positive.")
    if queue_order not in {"source", "category_round_robin"}:
        raise ValueError("queue_order must be source or category_round_robin.")
    if requests_per_category is not None and requests_per_category <= 0:
        raise ValueError("requests_per_category must be positive.")
    source_root = Path(source_root)
    output_root = Path(output_root)
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(
            f"Output directory is not empty: {output_root}"
        )
    source_manifest_path = source_root / "manifest.json"
    source_manifest = json.loads(
        source_manifest_path.read_text(encoding="utf-8")
    )
    if source_manifest["collection"]["kind"] != "autoregressive_decode":
        raise ValueError("Source is not an autoregressive decode trace.")
    model = source_manifest["model"]
    num_layers = int(model["num_layers"])
    num_experts = int(model["num_experts"])
    top_k = int(model["top_k"])

    samples: dict[int, dict] = {}
    request_rows: list[dict] = []
    for shard in source_manifest["shards"]:
        tensor_path = source_root / shard["tensor_file"]
        metadata_path = source_root / shard["metadata_file"]
        if verify_source_checksums:
            if sha256_file(tensor_path) != shard["tensor_sha256"]:
                raise ValueError(
                    f"Source tensor checksum mismatch for {tensor_path}."
                )
            if sha256_file(metadata_path) != shard["metadata_sha256"]:
                raise ValueError(
                    f"Source metadata checksum mismatch for {metadata_path}."
                )
        with metadata_path.open(encoding="utf-8") as handle:
            metadata_rows = [
                json.loads(line) for line in handle if line.strip()
            ]
        with safe_open(tensor_path, framework="pt", device="cpu") as handle:
            sample_indices = handle.get_tensor("sample_indices").numpy()
            lengths = handle.get_tensor("sequence_lengths").numpy()
            topk_indices = handle.get_tensor("topk_indices").numpy()
            topk_weights = handle.get_tensor("topk_weights").float().numpy()
        if len(metadata_rows) != len(sample_indices):
            raise ValueError("Decode metadata/tensor sample mismatch.")
        for local_index, sample_index_value in enumerate(sample_indices):
            sample_index = int(sample_index_value)
            row = metadata_rows[local_index]
            if int(row["collection_index"]) != sample_index:
                raise ValueError("Decode collection index mismatch.")
            length = int(lengths[local_index])
            samples[sample_index] = {
                "length": length,
                "topk_indices": topk_indices[
                    local_index, :, :length, :
                ].astype(np.int64, copy=True),
                "topk_weights": topk_weights[
                    local_index, :, :length, :
                ].astype(np.float64, copy=True),
                "metadata": row,
            }
            request_rows.append(row)

    selected_categories = (
        tuple(sorted(set(include_categories))) if include_categories else None
    )
    selected_request_ids = (
        frozenset(include_request_ids) if include_request_ids else None
    )
    if selected_request_ids is not None:
        samples = {
            request_index: sample
            for request_index, sample in samples.items()
            if sample["metadata"].get("id") in selected_request_ids
        }
        selected_indices = set(samples)
        request_rows = [
            row
            for row in request_rows
            if int(row["collection_index"]) in selected_indices
        ]
        observed_ids = {
            sample["metadata"].get("id") for sample in samples.values()
        }
        missing = selected_request_ids - observed_ids
        if missing:
            raise ValueError(
                "Requested decode IDs are absent from the trace: "
                + ", ".join(sorted(missing)[:8])
            )
    if selected_categories is not None:
        allowed = set(selected_categories)
        samples = {
            request_index: sample
            for request_index, sample in samples.items()
            if sample["metadata"]["metadata"].get(category_field) in allowed
        }
        selected_indices = set(samples)
        request_rows = [
            row
            for row in request_rows
            if int(row["collection_index"]) in selected_indices
        ]
        if not samples:
            raise ValueError(
                "No decode requests match include_categories="
                f"{selected_categories!r}."
            )

    if requests_per_category is not None:
        category_counts: defaultdict[str, int] = defaultdict(int)
        selected_indices: set[int] = set()
        for request_index in sorted(samples):
            category = samples[request_index]["metadata"]["metadata"].get(
                category_field
            )
            if not isinstance(category, str) or not category:
                raise ValueError(
                    f"Request {request_index} lacks {category_field!r}."
                )
            if category_counts[category] < requests_per_category:
                selected_indices.add(request_index)
                category_counts[category] += 1
        samples = {
            request_index: sample
            for request_index, sample in samples.items()
            if request_index in selected_indices
        }
        request_rows = [
            row
            for row in request_rows
            if int(row["collection_index"]) in selected_indices
        ]

    source_order = sorted(samples)
    if queue_order == "source":
        ordered_requests = source_order
    else:
        by_category: dict[str, deque[int]] = defaultdict(deque)
        for request_index in source_order:
            metadata = samples[request_index]["metadata"]["metadata"]
            category = metadata.get(category_field)
            if not isinstance(category, str) or not category:
                raise ValueError(
                    f"Request {request_index} lacks {category_field!r}."
                )
            by_category[category].append(request_index)
        ordered_requests = []
        categories = sorted(by_category)
        while any(by_category.values()):
            for category in categories:
                if by_category[category]:
                    ordered_requests.append(
                        by_category[category].popleft()
                    )

    event_request_indices: list[int] = []
    event_scheduler_steps: list[int] = []
    event_forward_cycles: list[int] = []
    event_phases: list[int] = []
    event_layer_ids: list[int] = []
    event_token_counts: list[int] = []
    event_offsets = [0]
    access_expert_ids: list[int] = []
    access_assignment_counts: list[int] = []
    access_gate_mass: list[float] = []
    schedule_rows: list[dict] = []

    def nested_metadata_value(request_index: int, field_path: str) -> object:
        value: object = samples[request_index]["metadata"]["metadata"]
        for component in field_path.split("."):
            if not isinstance(value, dict) or component not in value:
                raise ValueError(
                    f"Request {request_index} lacks arrival field "
                    f"{field_path!r}."
                )
            value = value[component]
        return value

    arrival_offsets: dict[int, int] = {}
    for request_index in ordered_requests:
        request_id = str(samples[request_index]["metadata"].get("id"))
        if arrival_offset_map is not None:
            if request_id not in arrival_offset_map:
                raise ValueError(
                    f"Request {request_id!r} lacks an arrival-map entry."
                )
            raw_offset = arrival_offset_map[request_id]
        else:
            raw_offset = (
                nested_metadata_value(request_index, arrival_offset_field)
                if arrival_offset_field
                else 0
            )
        offset = int(raw_offset)
        if offset < 0:
            raise ValueError("Arrival offsets must be non-negative.")
        arrival_offsets[request_index] = offset

    waiting = list(ordered_requests)
    active: list[dict[str, int]] = []
    scheduler_step = 0
    logical_assignments = 0
    while waiting or active:
        if not active and waiting:
            scheduler_step = max(
                scheduler_step,
                min(arrival_offsets[index] for index in waiting),
            )
        retained: list[int] = []
        for request_index in waiting:
            if (
                len(active) < batch_size
                and arrival_offsets[request_index] <= scheduler_step
            ):
                active.append(
                    {"request_index": int(request_index), "position": 0}
                )
            else:
                retained.append(request_index)
        waiting = retained
        if not active:
            continue
        schedule_rows.append(
            {
                "scheduler_step": scheduler_step,
                "active_request_indices": [
                    item["request_index"] for item in active
                ],
                "decode_positions": [item["position"] for item in active],
                "arrival_offsets": [
                    arrival_offsets[item["request_index"]] for item in active
                ],
                "categories": [
                    samples[item["request_index"]]["metadata"]["metadata"][
                        category_field
                    ]
                    for item in active
                ],
            }
        )
        for layer_id in range(num_layers):
            ids = np.concatenate(
                [
                    samples[item["request_index"]]["topk_indices"][
                        layer_id, item["position"], :
                    ]
                    for item in active
                ]
            )
            weights = np.concatenate(
                [
                    samples[item["request_index"]]["topk_weights"][
                        layer_id, item["position"], :
                    ]
                    for item in active
                ]
            )
            valid = ids >= 0
            ids = ids[valid]
            weights = weights[valid]
            counts = np.bincount(ids, minlength=num_experts)
            masses = np.bincount(
                ids,
                weights=weights,
                minlength=num_experts,
            )
            union = np.flatnonzero(counts)
            logical_assignments += int(counts.sum())
            event_request_indices.append(-1)
            event_scheduler_steps.append(scheduler_step)
            event_forward_cycles.append(scheduler_step)
            event_phases.append(PHASE_DECODE)
            event_layer_ids.append(layer_id)
            event_token_counts.append(len(active))
            access_expert_ids.extend(union.tolist())
            access_assignment_counts.extend(
                counts[union].astype(np.int64).tolist()
            )
            access_gate_mass.extend(masses[union].tolist())
            event_offsets.append(len(access_expert_ids))
        for item in active:
            item["position"] += 1
        active = [
            item
            for item in active
            if item["position"] < samples[item["request_index"]]["length"]
        ]
        scheduler_step += 1

    output_root.mkdir(parents=True, exist_ok=True)
    requests_path = output_root / "requests.jsonl"
    with requests_path.open("w", encoding="utf-8") as handle:
        for row in sorted(
            request_rows,
            key=lambda item: item["collection_index"],
        ):
            handle.write(
                json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            )
    schedule_path = output_root / "schedule.jsonl"
    with schedule_path.open("w", encoding="utf-8") as handle:
        for row in schedule_rows:
            handle.write(
                json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            )
    manifest = {
        "created_at": utc_now(),
        "status": "complete",
        "kind": "decode_event_trace",
        "source": {
            "root": str(source_root.resolve()),
            "manifest_sha256": sha256_file(source_manifest_path),
            "completed_samples": int(source_manifest["completed_samples"]),
        },
        "conversion": {
            "scheduler": "FCFS",
            "batch_size": batch_size,
            "queue_order": queue_order,
            "category_field": category_field,
            "include_categories": (
                list(selected_categories)
                if selected_categories is not None
                else None
            ),
            "include_request_ids_count": (
                len(selected_request_ids)
                if selected_request_ids is not None
                else None
            ),
            "requests_per_category": requests_per_category,
            "arrival_offset_field": arrival_offset_field,
            "arrival_offset_map_used": arrival_offset_map is not None,
            "same_step_cross_request_dedup": True,
            "event_semantics": "expert_union_per_layer",
            "request_indices_in_events": (
                "-1 sentinel; consult schedule.jsonl active_request_indices"
            ),
            "source_checksums_verified": verify_source_checksums,
        },
        "model": {
            "id": model["id"],
            "commit": model["commit"],
            "model_type": model["model_type"],
            "num_layers": num_layers,
            "num_experts": num_experts,
            "top_k": top_k,
        },
        "counts": {
            "requests": len(samples),
            "decode_forwards": sum(
                int(sample["length"]) for sample in samples.values()
            ),
            "scheduler_steps": scheduler_step,
            "events": len(event_layer_ids),
            "union_expert_accesses": len(access_expert_ids),
            "logical_expert_assignments_before_dedup": logical_assignments,
        },
        "artifacts": {
            "requests": {
                "path": requests_path.name,
                "sha256": sha256_file(requests_path),
                "bytes": requests_path.stat().st_size,
            },
            "schedule": {
                "path": schedule_path.name,
                "sha256": sha256_file(schedule_path),
                "bytes": schedule_path.stat().st_size,
            },
        },
    }
    return save_event_trace(
        output_root,
        manifest=manifest,
        request_indices=np.asarray(event_request_indices),
        scheduler_steps=np.asarray(event_scheduler_steps),
        forward_cycles=np.asarray(event_forward_cycles),
        phases=np.asarray(event_phases),
        layer_ids=np.asarray(event_layer_ids),
        token_counts=np.asarray(event_token_counts),
        offsets=np.asarray(event_offsets),
        expert_ids=np.asarray(access_expert_ids),
        assignment_counts=np.asarray(access_assignment_counts),
        gate_mass=np.asarray(access_gate_mass),
    )
