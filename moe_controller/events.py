from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

import numpy as np
import torch
from safetensors.torch import load_file, save_file


EVENT_SCHEMA_VERSION = 1
PHASE_PREFILL = 0
PHASE_DECODE = 1
PHASE_NAMES = {
    PHASE_PREFILL: "prefill",
    PHASE_DECODE: "decode",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


@dataclass(frozen=True)
class Event:
    event_index: int
    request_index: int
    scheduler_step: int
    forward_cycle: int
    phase: int
    layer_id: int
    token_count: int
    expert_ids: np.ndarray
    assignment_counts: np.ndarray
    gate_mass: np.ndarray


@dataclass(frozen=True)
class EventTrace:
    root: Path
    manifest: dict
    request_indices: np.ndarray
    scheduler_steps: np.ndarray
    forward_cycles: np.ndarray
    phases: np.ndarray
    layer_ids: np.ndarray
    token_counts: np.ndarray
    offsets: np.ndarray
    expert_ids: np.ndarray
    assignment_counts: np.ndarray
    gate_mass: np.ndarray

    @property
    def num_events(self) -> int:
        return int(self.layer_ids.shape[0])

    @property
    def num_accesses(self) -> int:
        return int(self.expert_ids.shape[0])

    @property
    def num_layers(self) -> int:
        return int(self.manifest["model"]["num_layers"])

    @property
    def num_experts_per_layer(self) -> int:
        return int(self.manifest["model"]["num_experts"])

    @property
    def num_expert_blocks(self) -> int:
        return self.num_layers * self.num_experts_per_layer

    def block_ids_for_event(self, event_index: int) -> np.ndarray:
        start = int(self.offsets[event_index])
        end = int(self.offsets[event_index + 1])
        layer = int(self.layer_ids[event_index])
        return (
            layer * self.num_experts_per_layer
            + self.expert_ids[start:end].astype(np.int64, copy=False)
        )

    def event(self, event_index: int) -> Event:
        start = int(self.offsets[event_index])
        end = int(self.offsets[event_index + 1])
        return Event(
            event_index=event_index,
            request_index=int(self.request_indices[event_index]),
            scheduler_step=int(self.scheduler_steps[event_index]),
            forward_cycle=int(self.forward_cycles[event_index]),
            phase=int(self.phases[event_index]),
            layer_id=int(self.layer_ids[event_index]),
            token_count=int(self.token_counts[event_index]),
            expert_ids=self.expert_ids[start:end],
            assignment_counts=self.assignment_counts[start:end],
            gate_mass=self.gate_mass[start:end],
        )

    def iter_events(self) -> Iterator[Event]:
        for event_index in range(self.num_events):
            yield self.event(event_index)

    def validate(self) -> None:
        event_length = self.num_events
        for name, array in {
            "request_indices": self.request_indices,
            "scheduler_steps": self.scheduler_steps,
            "forward_cycles": self.forward_cycles,
            "phases": self.phases,
            "token_counts": self.token_counts,
        }.items():
            if len(array) != event_length:
                raise ValueError(
                    f"{name} has {len(array)} rows; expected {event_length}."
                )
        if len(self.offsets) != event_length + 1:
            raise ValueError("offsets must have num_events + 1 entries.")
        if int(self.offsets[0]) != 0:
            raise ValueError("offsets must start at zero.")
        if np.any(np.diff(self.offsets) < 0):
            raise ValueError("offsets must be monotonic.")
        if int(self.offsets[-1]) != self.num_accesses:
            raise ValueError("Final offset does not match access-array length.")
        for name, array in {
            "assignment_counts": self.assignment_counts,
            "gate_mass": self.gate_mass,
        }.items():
            if len(array) != self.num_accesses:
                raise ValueError(
                    f"{name} has {len(array)} rows; "
                    f"expected {self.num_accesses}."
                )
        if np.any(self.layer_ids < 0) or np.any(
            self.layer_ids >= self.num_layers
        ):
            raise ValueError("layer_ids contains an out-of-range value.")
        if np.any(self.expert_ids < 0) or np.any(
            self.expert_ids >= self.num_experts_per_layer
        ):
            raise ValueError("expert_ids contains an out-of-range value.")
        if np.any(self.assignment_counts <= 0):
            raise ValueError("Every materialized expert access needs a count.")
        if np.any(self.gate_mass < 0):
            raise ValueError("gate_mass cannot be negative.")
        if np.any(~np.isin(self.phases, list(PHASE_NAMES))):
            raise ValueError("Unknown phase identifier.")
        if event_length:
            order = np.lexsort(
                (
                    self.layer_ids,
                    self.forward_cycles,
                    self.scheduler_steps,
                )
            )
            if not np.array_equal(order, np.arange(event_length)):
                raise ValueError(
                    "Events must be ordered by scheduler step, forward cycle, "
                    "and layer."
                )


def subset_event_trace(
    trace: EventTrace,
    request_indices: Iterable[int],
) -> EventTrace:
    requested = np.asarray(sorted(set(request_indices)), dtype=np.int64)
    event_mask = np.isin(trace.request_indices, requested)
    selected_events = np.flatnonzero(event_mask)
    lengths = np.diff(trace.offsets)[selected_events].astype(
        np.int64,
        copy=False,
    )
    access_parts = [
        np.arange(
            int(trace.offsets[event_index]),
            int(trace.offsets[event_index + 1]),
            dtype=np.int64,
        )
        for event_index in selected_events
    ]
    selected_accesses = (
        np.concatenate(access_parts)
        if access_parts
        else np.empty(0, dtype=np.int64)
    )
    offsets = np.concatenate(
        (
            np.asarray([0], dtype=np.int64),
            np.cumsum(lengths, dtype=np.int64),
        )
    )
    _, scheduler_steps = np.unique(
        trace.scheduler_steps[selected_events],
        return_inverse=True,
    )
    _, forward_cycles = np.unique(
        trace.forward_cycles[selected_events],
        return_inverse=True,
    )
    subset = EventTrace(
        root=trace.root,
        manifest=trace.manifest,
        request_indices=trace.request_indices[selected_events],
        scheduler_steps=scheduler_steps.astype(np.int32, copy=False),
        forward_cycles=forward_cycles.astype(np.int32, copy=False),
        phases=trace.phases[selected_events],
        layer_ids=trace.layer_ids[selected_events],
        token_counts=trace.token_counts[selected_events],
        offsets=offsets,
        expert_ids=trace.expert_ids[selected_accesses],
        assignment_counts=trace.assignment_counts[selected_accesses],
        gate_mass=trace.gate_mass[selected_accesses],
    )
    subset.validate()
    return subset


def reorder_event_trace(
    trace: EventTrace,
    request_order: Iterable[int],
) -> EventTrace:
    """Select and concatenate complete requests in an explicit order.

    Request-internal forward-cycle and layer order is preserved. Scheduler
    steps and forward cycles are remapped to a continuous stream so cache
    state can be carried across workload-category boundaries without reset.
    """
    ordered_requests = [int(value) for value in request_order]
    if len(ordered_requests) != len(set(ordered_requests)):
        raise ValueError("request_order cannot contain duplicate requests.")
    available = set(int(value) for value in np.unique(trace.request_indices))
    missing = [value for value in ordered_requests if value not in available]
    if missing:
        raise ValueError(f"Unknown request indices: {missing[:5]}.")

    selected_events: list[int] = []
    remapped_steps: list[int] = []
    remapped_cycles: list[int] = []
    next_step = 0
    next_cycle = 0
    for request_index in ordered_requests:
        event_indices = np.flatnonzero(
            trace.request_indices == request_index
        )
        request_steps = trace.scheduler_steps[event_indices]
        request_cycles = trace.forward_cycles[event_indices]
        step_values = list(dict.fromkeys(int(value) for value in request_steps))
        cycle_values = list(
            dict.fromkeys(int(value) for value in request_cycles)
        )
        step_map = {
            value: next_step + offset
            for offset, value in enumerate(step_values)
        }
        cycle_map = {
            value: next_cycle + offset
            for offset, value in enumerate(cycle_values)
        }
        selected_events.extend(int(value) for value in event_indices)
        remapped_steps.extend(
            step_map[int(value)] for value in request_steps
        )
        remapped_cycles.extend(
            cycle_map[int(value)] for value in request_cycles
        )
        next_step += len(step_values)
        next_cycle += len(cycle_values)

    selected = np.asarray(selected_events, dtype=np.int64)
    lengths = np.diff(trace.offsets)[selected].astype(
        np.int64,
        copy=False,
    )
    access_parts = [
        np.arange(
            int(trace.offsets[event_index]),
            int(trace.offsets[event_index + 1]),
            dtype=np.int64,
        )
        for event_index in selected
    ]
    accesses = (
        np.concatenate(access_parts)
        if access_parts
        else np.empty(0, dtype=np.int64)
    )
    offsets = np.concatenate(
        (
            np.asarray([0], dtype=np.int64),
            np.cumsum(lengths, dtype=np.int64),
        )
    )
    reordered = EventTrace(
        root=trace.root,
        manifest=trace.manifest,
        request_indices=trace.request_indices[selected],
        scheduler_steps=np.asarray(remapped_steps, dtype=np.int32),
        forward_cycles=np.asarray(remapped_cycles, dtype=np.int32),
        phases=trace.phases[selected],
        layer_ids=trace.layer_ids[selected],
        token_counts=trace.token_counts[selected],
        offsets=offsets,
        expert_ids=trace.expert_ids[accesses],
        assignment_counts=trace.assignment_counts[accesses],
        gate_mass=trace.gate_mass[accesses],
    )
    reordered.validate()
    return reordered


def load_event_trace(
    root: Path | str,
    *,
    verify_checksum: bool = True,
) -> EventTrace:
    root = Path(root)
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if int(manifest["schema_version"]) != EVENT_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported event schema {manifest['schema_version']}."
        )
    tensor_path = root / manifest["artifacts"]["events"]["path"]
    if verify_checksum:
        observed = sha256_file(tensor_path)
        expected = manifest["artifacts"]["events"]["sha256"]
        if observed != expected:
            raise ValueError(
                f"Event checksum mismatch: {observed} != {expected}."
            )
    tensors = load_file(tensor_path)
    trace = EventTrace(
        root=root,
        manifest=manifest,
        request_indices=tensors["request_indices"].numpy(),
        scheduler_steps=tensors["scheduler_steps"].numpy(),
        forward_cycles=tensors["forward_cycles"].numpy(),
        phases=tensors["phases"].numpy(),
        layer_ids=tensors["layer_ids"].numpy(),
        token_counts=tensors["token_counts"].numpy(),
        offsets=tensors["offsets"].numpy(),
        expert_ids=tensors["expert_ids"].numpy(),
        assignment_counts=tensors["assignment_counts"].numpy(),
        gate_mass=tensors["gate_mass"].numpy(),
    )
    trace.validate()
    return trace


def save_event_trace(
    root: Path | str,
    *,
    manifest: dict,
    request_indices: np.ndarray,
    scheduler_steps: np.ndarray,
    forward_cycles: np.ndarray,
    phases: np.ndarray,
    layer_ids: np.ndarray,
    token_counts: np.ndarray,
    offsets: np.ndarray,
    expert_ids: np.ndarray,
    assignment_counts: np.ndarray,
    gate_mass: np.ndarray,
) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    tensor_path = root / "events.safetensors"
    tensors = {
        "request_indices": torch.from_numpy(
            np.asarray(request_indices, dtype=np.int32)
        ),
        "scheduler_steps": torch.from_numpy(
            np.asarray(scheduler_steps, dtype=np.int32)
        ),
        "forward_cycles": torch.from_numpy(
            np.asarray(forward_cycles, dtype=np.int32)
        ),
        "phases": torch.from_numpy(np.asarray(phases, dtype=np.uint8)),
        "layer_ids": torch.from_numpy(np.asarray(layer_ids, dtype=np.int16)),
        "token_counts": torch.from_numpy(
            np.asarray(token_counts, dtype=np.int32)
        ),
        "offsets": torch.from_numpy(np.asarray(offsets, dtype=np.int64)),
        "expert_ids": torch.from_numpy(
            np.asarray(expert_ids, dtype=np.int16)
        ),
        "assignment_counts": torch.from_numpy(
            np.asarray(assignment_counts, dtype=np.int32)
        ),
        "gate_mass": torch.from_numpy(
            np.asarray(gate_mass, dtype=np.float32)
        ),
    }
    save_file(
        tensors,
        tensor_path,
        metadata={
            "schema": "moe-controller-events",
            "schema_version": str(EVENT_SCHEMA_VERSION),
        },
    )
    output_manifest = dict(manifest)
    output_manifest["schema_version"] = EVENT_SCHEMA_VERSION
    output_manifest["artifacts"] = {
        **output_manifest.get("artifacts", {}),
        "events": {
            "path": tensor_path.name,
            "sha256": sha256_file(tensor_path),
            "bytes": tensor_path.stat().st_size,
        },
    }
    temporary = root / ".manifest.json.tmp"
    temporary.write_text(
        json.dumps(
            output_manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(root / "manifest.json")
    return root
