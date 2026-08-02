#!/usr/bin/env python3
"""Build full-trajectory decode events for frozen affinity schedulers."""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from safetensors import safe_open

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moe_controller.affinity import select_affinity_batch
from moe_controller.events import PHASE_DECODE, save_event_trace, sha256_file


SCHEDULERS = ("fcfs_deadline", "causal_prev_route", "oracle_current_route")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def percentile(values: list[int], quantile: float) -> float:
    return float(np.quantile(np.asarray(values, dtype=np.float64), quantile)) if values else 0.0


def load_samples(
    source_root: Path,
    request_ids: frozenset[str],
) -> tuple[dict[int, dict], list[dict], dict]:
    manifest_path = source_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    model = manifest["model"]
    samples: dict[int, dict] = {}
    rows: list[dict] = []
    for shard in manifest["shards"]:
        tensor_path = source_root / shard["tensor_file"]
        metadata_path = source_root / shard["metadata_file"]
        if sha256_file(tensor_path) != shard["tensor_sha256"]:
            raise ValueError(f"Tensor checksum mismatch: {tensor_path}")
        if sha256_file(metadata_path) != shard["metadata_sha256"]:
            raise ValueError(f"Metadata checksum mismatch: {metadata_path}")
        metadata_rows = [
            json.loads(line)
            for line in metadata_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        with safe_open(tensor_path, framework="pt", device="cpu") as handle:
            sample_indices = handle.get_tensor("sample_indices").numpy()
            lengths = handle.get_tensor("sequence_lengths").numpy()
            topk_indices = handle.get_tensor("topk_indices").numpy()
            topk_weights = handle.get_tensor("topk_weights").float().numpy()
        for local_index, raw_index in enumerate(sample_indices):
            row = metadata_rows[local_index]
            if row.get("id") not in request_ids:
                continue
            request_index = int(raw_index)
            length = int(lengths[local_index])
            samples[request_index] = {
                "length": length,
                "topk_indices": topk_indices[local_index, :, :length, :].astype(
                    np.int64, copy=True
                ),
                "topk_weights": topk_weights[local_index, :, :length, :].astype(
                    np.float64, copy=True
                ),
                "metadata": row,
            }
            rows.append(row)
    observed = {sample["metadata"]["id"] for sample in samples.values()}
    missing = request_ids - observed
    if missing:
        raise ValueError(f"Missing request IDs: {sorted(missing)[:8]}")
    return samples, rows, manifest


def category_round_robin(samples: dict[int, dict]) -> list[int]:
    by_category: dict[str, deque[int]] = defaultdict(deque)
    for request_index in sorted(samples):
        category = samples[request_index]["metadata"]["metadata"][
            "workload_archetype"
        ]
        by_category[str(category)].append(request_index)
    ordered: list[int] = []
    categories = sorted(by_category)
    while any(by_category.values()):
        for category in categories:
            if by_category[category]:
                ordered.append(by_category[category].popleft())
    return ordered


def signature(sample: dict, position: int, num_experts: int) -> frozenset[int]:
    if position < 0:
        return frozenset()
    ids = sample["topk_indices"][:, position, :]
    layer_offsets = np.arange(ids.shape[0], dtype=np.int64)[:, None] * num_experts
    blocks = (ids + layer_offsets)[ids >= 0]
    return frozenset(int(value) for value in blocks)


def build_events(
    *,
    source_root: Path,
    output_root: Path,
    request_id_file: Path,
    arrival_map_path: Path,
    scheduler: str,
    batch_size: int,
    max_service_interval: int,
    max_active_requests: int,
) -> Path:
    if scheduler not in SCHEDULERS:
        raise ValueError(f"Unknown scheduler {scheduler!r}")
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output_root}")
    request_ids = frozenset(
        line.strip()
        for line in request_id_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    arrival_by_id = {
        str(key): int(value)
        for key, value in json.loads(
            arrival_map_path.read_text(encoding="utf-8")
        ).items()
    }
    samples, request_rows, source_manifest = load_samples(source_root, request_ids)
    model = source_manifest["model"]
    num_layers = int(model["num_layers"])
    num_experts = int(model["num_experts"])
    ordered = category_round_robin(samples)
    order_rank = {request_index: rank for rank, request_index in enumerate(ordered)}
    arrival = {
        request_index: arrival_by_id[samples[request_index]["metadata"]["id"]]
        for request_index in ordered
    }
    if max_active_requests > batch_size * max_service_interval:
        raise ValueError("Active population exceeds the deadline-feasible bound")
    max_active = max_active_requests

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

    waiting = list(ordered)
    active: list[int] = []
    positions = {request_index: 0 for request_index in ordered}
    admitted_at: dict[int, int] = {}
    last_served: dict[int, int] = {}
    service_intervals: list[int] = []
    first_service_waits: list[int] = []
    admission_waits: list[int] = []
    scheduler_step = 0
    logical_assignments = 0
    predicted_union_total = 0

    while waiting or active:
        if not active and waiting:
            scheduler_step = max(scheduler_step, min(arrival[index] for index in waiting))
        retained: list[int] = []
        for request_index in waiting:
            if len(active) < max_active and arrival[request_index] <= scheduler_step:
                active.append(request_index)
                admitted_at[request_index] = scheduler_step
                admission_waits.append(scheduler_step - arrival[request_index])
            else:
                retained.append(request_index)
        waiting = retained
        if not active:
            continue

        deadlines = {
            request_index: (
                last_served[request_index] + max_service_interval
                if request_index in last_served
                else admitted_at[request_index] + max_service_interval - 1
            )
            for request_index in active
        }
        priority = {
            request_index: (deadlines[request_index], order_rank[request_index])
            for request_index in active
        }
        earliest = sorted(active, key=lambda item: priority[item])
        required_count = 0
        for horizon in range(max_service_interval):
            due = sum(
                deadline <= scheduler_step + horizon
                for deadline in deadlines.values()
            )
            required_count = max(required_count, due - batch_size * horizon)
        required_count = max(0, required_count)
        if required_count > batch_size:
            raise RuntimeError(
                "Deadline set is infeasible before affinity selection: "
                f"required={required_count}, B={batch_size}"
            )
        required = earliest[:required_count]

        if scheduler == "fcfs_deadline":
            signatures = {request_index: frozenset() for request_index in active}
            group = earliest[:batch_size]
        else:
            use_current = scheduler == "oracle_current_route"
            signatures = {
                request_index: signature(
                    samples[request_index],
                    positions[request_index] if use_current else positions[request_index] - 1,
                    num_experts,
                )
                for request_index in active
            }
            group = select_affinity_batch(
                active,
                signatures,
                batch_size,
                required=required,
                priority=priority,
            )
            predicted_union_total += len(
                frozenset().union(*(signatures[index] for index in group))
            )

        decode_positions = [positions[request_index] for request_index in group]
        for request_index in group:
            if request_index in last_served:
                service_intervals.append(scheduler_step - last_served[request_index])
            else:
                first_service_waits.append(scheduler_step - admitted_at[request_index])
            last_served[request_index] = scheduler_step
        schedule_rows.append(
            {
                "scheduler_step": scheduler_step,
                "active_request_indices": list(group),
                "decode_positions": decode_positions,
                "arrival_offsets": [arrival[index] for index in group],
                "deadlines": [deadlines[index] for index in group],
                "required_request_indices": list(required),
                "categories": [
                    samples[index]["metadata"]["metadata"]["workload_archetype"]
                    for index in group
                ],
            }
        )
        for layer_id in range(num_layers):
            ids = np.concatenate(
                [
                    samples[index]["topk_indices"][layer_id, positions[index], :]
                    for index in group
                ]
            )
            weights = np.concatenate(
                [
                    samples[index]["topk_weights"][layer_id, positions[index], :]
                    for index in group
                ]
            )
            valid = ids >= 0
            ids = ids[valid]
            weights = weights[valid]
            counts = np.bincount(ids, minlength=num_experts)
            masses = np.bincount(ids, weights=weights, minlength=num_experts)
            union = np.flatnonzero(counts)
            logical_assignments += int(counts.sum())
            event_request_indices.append(-1)
            event_scheduler_steps.append(scheduler_step)
            event_forward_cycles.append(scheduler_step)
            event_phases.append(PHASE_DECODE)
            event_layer_ids.append(layer_id)
            event_token_counts.append(len(group))
            access_expert_ids.extend(union.tolist())
            access_assignment_counts.extend(counts[union].astype(np.int64).tolist())
            access_gate_mass.extend(masses[union].tolist())
            event_offsets.append(len(access_expert_ids))
        for request_index in group:
            positions[request_index] += 1

        active = [
            request_index
            for request_index in active
            if positions[request_index] < samples[request_index]["length"]
        ]
        scheduler_step += 1

    maximum_interval = max(service_intervals, default=0)
    if maximum_interval > max_service_interval:
        raise RuntimeError(
            f"Service interval {maximum_interval} exceeds W={max_service_interval}"
        )
    expected_forwards = sum(sample["length"] for sample in samples.values())
    observed_forwards = sum(positions.values())
    if observed_forwards != expected_forwards:
        raise RuntimeError("Scheduler did not serve every decode position exactly once")

    output_root.mkdir(parents=True)
    requests_path = output_root / "requests.jsonl"
    with requests_path.open("w", encoding="utf-8") as handle:
        for row in sorted(request_rows, key=lambda item: item["collection_index"]):
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    schedule_path = output_root / "schedule.jsonl"
    with schedule_path.open("w", encoding="utf-8") as handle:
        for row in schedule_rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    manifest = {
        "created_at": utc_now(),
        "status": "complete",
        "kind": "decode_event_trace",
        "source": {
            "root": str(source_root.resolve()),
            "manifest_sha256": sha256_file(source_root / "manifest.json"),
            "request_id_file_sha256": sha256_file(request_id_file),
            "arrival_map_sha256": sha256_file(arrival_map_path),
        },
        "conversion": {
            "scheduler": scheduler,
            "batch_size": batch_size,
            "max_service_interval": max_service_interval,
            "max_active_requests": max_active,
            "queue_order": "category_round_robin",
            "same_step_cross_request_dedup": True,
            "event_semantics": "expert_union_per_layer",
            "request_indices_in_events": "-1 sentinel; consult schedule.jsonl",
            "affinity_signal": (
                "none"
                if scheduler == "fcfs_deadline"
                else "previous_token_route"
                if scheduler == "causal_prev_route"
                else "current_token_true_route"
            ),
            "selection_algorithm": "deadline_required_plus_greedy_min_union",
            "tie_seed": 20260801,
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
            "requests": len(samples),
            "decode_forwards": observed_forwards,
            "scheduler_steps": scheduler_step,
            "events": len(event_layer_ids),
            "union_expert_accesses": len(access_expert_ids),
            "logical_expert_assignments_before_dedup": logical_assignments,
        },
        "scheduler_metrics": {
            "max_service_interval": maximum_interval,
            "mean_service_interval": float(np.mean(service_intervals)),
            "p99_service_interval": percentile(service_intervals, 0.99),
            "first_service_wait_p99": percentile(first_service_waits, 0.99),
            "admission_wait_p50": percentile(admission_waits, 0.50),
            "admission_wait_p95": percentile(admission_waits, 0.95),
            "admission_wait_p99": percentile(admission_waits, 0.99),
            "admission_wait_max": max(admission_waits, default=0),
            "starved_requests": sum(
                1 for request_index in ordered if request_index not in last_served
            ),
            "predicted_partition_union_total": predicted_union_total,
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--request-id-file", type=Path, required=True)
    parser.add_argument("--arrival-map", type=Path, required=True)
    parser.add_argument("--scheduler", choices=SCHEDULERS, required=True)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--max-service-interval", type=int, default=4)
    parser.add_argument("--max-active-requests", type=int, default=24)
    args = parser.parse_args()
    output = build_events(
        source_root=args.source,
        output_root=args.output,
        request_id_file=args.request_id_file,
        arrival_map_path=args.arrival_map,
        scheduler=args.scheduler,
        batch_size=args.batch_size,
        max_service_interval=args.max_service_interval,
        max_active_requests=args.max_active_requests,
    )
    print(output)


if __name__ == "__main__":
    main()
