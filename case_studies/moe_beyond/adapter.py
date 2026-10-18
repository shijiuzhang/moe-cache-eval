"""External adapter for the MoE-Beyond public trace artifact.

This module reads the third-party CSV traces without importing or modifying any
third-party code, validates them, and writes them into the formats that the
released package already consumes:

* E1 (per-token events): the decode-route source format read by
  ``moe_controller.convert.convert_decode_trace``.  The source records the
  replay model explicitly; the physical phase of every row is prefill.
* E2 (whole-prefill events): an ``EventTrace`` with one event per
  (request, layer), written with ``moe_controller.events.save_event_trace``.

It also writes probe traces back into the third-party simulator's input format.
Both event definitions are declared reporting contracts (PREREG section 2); none
of them is asserted to be the third-party system's own execution.
"""

from __future__ import annotations

import ast
import csv
import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import numpy as np
import torch
from safetensors.torch import save_file

from moe_controller.events import PHASE_PREFILL, save_event_trace, sha256_file

RAW_FIRST_LAYER = 1
NUM_LAYERS = 26
NUM_EXPERTS = 64
TOP_K = 6
MODEL_ID = "deepseek-ai/DeepSeek-V2-Lite-Chat"
THIRD_PARTY_REPO = "https://github.com/ngavhane/moe-beyond"
THIRD_PARTY_COMMIT = "47031eefc7808e996ecd5c01d7ed90aa32e32514"
BOS_TOKEN = "<｜begin▁of▁sentence｜>"
EXPERT_COLUMN = "Activated Expert IDs"
PREDICTED_COLUMN = "Predicted Expert IDs"


@dataclass(frozen=True)
class RawRow:
    layer: int
    token: str
    experts: tuple[int, ...]
    predicted: tuple[int, ...] | None
    src_file: str
    src_row: int


@dataclass
class PromptTrace:
    """One prompt file, normalized to zero-based MoE layers."""

    request_id: str
    src_file: str
    src_sha256: str
    experts: np.ndarray  # [NUM_LAYERS, T, TOP_K], int16
    tokens: list[str] | None
    violations: dict[str, int] = field(default_factory=dict)

    @property
    def num_tokens(self) -> int:
        return int(self.experts.shape[1])

    def layer_signature(self) -> tuple:
        """Per-layer sequence of expert sets; independent of within-row order."""
        return tuple(
            (layer, tuple(frozenset(int(e) for e in self.experts[layer, t]) for t in range(self.num_tokens)))
            for layer in range(NUM_LAYERS)
        )


def load_raw(path: Path | str) -> Iterator[RawRow]:
    """Stream rows of one third-party CSV (formatted or predicted variant)."""
    path = Path(path)
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for index, row in enumerate(reader, start=2):  # header is line 1
            experts = tuple(int(value) for value in ast.literal_eval(row[EXPERT_COLUMN]))
            predicted = None
            if PREDICTED_COLUMN in row and row[PREDICTED_COLUMN] is not None:
                predicted = tuple(int(value) for value in ast.literal_eval(row[PREDICTED_COLUMN]))
            yield RawRow(
                layer=int(row["Layer ID"]),
                token=row["Token"],
                experts=experts,
                predicted=predicted,
                src_file=path.name,
                src_row=index,
            )


def parse_prompt_file(path: Path | str, *, request_id: str) -> PromptTrace:
    """Read one prompt file, validate it, and normalize it.

    Violations are counted, never silently repaired or dropped.  A trace with
    any violation is still returned so that callers can report the counts; the
    canonical builders refuse to emit traces that carry violations.
    """
    path = Path(path)
    by_layer: dict[int, list[RawRow]] = defaultdict(list)
    for row in load_raw(path):
        by_layer[row.layer].append(row)

    violations: dict[str, int] = defaultdict(int)
    expected_layers = list(range(RAW_FIRST_LAYER, RAW_FIRST_LAYER + NUM_LAYERS))
    if sorted(by_layer) != expected_layers:
        violations["layer_set_not_1_to_26"] += 1
    lengths = {len(rows) for rows in by_layer.values()}
    if len(lengths) != 1:
        violations["unequal_tokens_per_layer"] += 1
    num_tokens = min(lengths) if lengths else 0

    experts = np.full((NUM_LAYERS, num_tokens, TOP_K), -1, dtype=np.int16)
    for raw_layer in expected_layers:
        rows = by_layer.get(raw_layer, [])
        for position, row in enumerate(rows[:num_tokens]):
            if len(row.experts) != TOP_K:
                violations["row_not_exactly_top_k"] += 1
            if len(set(row.experts)) != len(row.experts):
                violations["row_duplicate_expert"] += 1
            if any(e < 0 or e >= NUM_EXPERTS for e in row.experts):
                violations["expert_id_out_of_range"] += 1
            if len(row.experts) == TOP_K:
                experts[raw_layer - RAW_FIRST_LAYER, position, :] = row.experts

    tokens: list[str] | None = None
    first_layer_rows = by_layer.get(RAW_FIRST_LAYER, [])
    with path.open(encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle))
    # The formatted variant carries token strings and a "Batch Number" column;
    # the predicted variant stores the per-layer position in "Token".
    if first_layer_rows and "Batch Number" in header:
        tokens = [row.token for row in first_layer_rows[:num_tokens]]
        for raw_layer in expected_layers[1:]:
            other = [row.token for row in by_layer.get(raw_layer, [])[:num_tokens]]
            if other != tokens:
                violations["token_sequence_differs_across_layers"] += 1

    return PromptTrace(
        request_id=request_id,
        src_file=path.name,
        src_sha256=sha256_file(path),
        experts=experts,
        tokens=tokens,
        violations=dict(violations),
    )


def match_by_signature(
    primary: dict[int, PromptTrace],
    secondary: dict[int, PromptTrace],
) -> dict[int, int]:
    """Map each primary file number to the unique secondary file with identical
    per-layer expert-set sequences.  Raises unless the mapping is a bijection."""
    index: dict[tuple, list[int]] = defaultdict(list)
    for number, trace in secondary.items():
        index[trace.layer_signature()].append(number)
    mapping: dict[int, int] = {}
    for number, trace in primary.items():
        matches = index.get(trace.layer_signature(), [])
        if len(matches) != 1:
            raise ValueError(
                f"Primary file {number} has {len(matches)} signature matches; "
                "expected exactly one."
            )
        mapping[number] = matches[0]
    if len(set(mapping.values())) != len(mapping):
        raise ValueError("Signature mapping is not injective.")
    return mapping


def reconstruct_prompt_text(tokens: Sequence[str]) -> str:
    """Byte-level BPE approximation fixed in PREREG P5.

    Drops the BOS token, maps the space marker 'Ġ' to a space and the newline
    marker 'Ċ' to a newline, and concatenates the remaining token strings.
    """
    pieces = [token for token in tokens if token != BOS_TOKEN]
    return "".join(pieces).replace("Ġ", " ").replace("Ċ", "\n")


def _total_violations(traces: Iterable[PromptTrace]) -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for trace in traces:
        for key, value in trace.violations.items():
            totals[key] += value
    return dict(totals)


def _refuse_on_violations(traces: Sequence[PromptTrace]) -> None:
    totals = _total_violations(traces)
    if totals:
        raise ValueError(f"Refusing to emit canonical trace; violations: {totals}")


def _model_block() -> dict:
    return {
        "id": MODEL_ID,
        "commit": "not_recorded_by_third_party_collection_script",
        "model_type": "deepseek_v2",
        "num_layers": NUM_LAYERS,
        "num_experts": NUM_EXPERTS,
        "top_k": TOP_K,
        "dense_layers_excluded": [0],
        "shared_experts_per_layer_excluded": 2,
        "raw_layer_ids": [RAW_FIRST_LAYER, RAW_FIRST_LAYER + NUM_LAYERS - 1],
    }


def _third_party_block() -> dict:
    return {"repository": THIRD_PARTY_REPO, "commit": THIRD_PARTY_COMMIT}


def write_e1_source(
    traces: Sequence[PromptTrace],
    output: Path | str,
    *,
    dataset_label: str,
    shard_size: int = 200,
) -> Path:
    """Write the decode-route source format consumed by ``convert_decode_trace``.

    ``collection.kind`` names the replay model (sequential positions); the
    physical phase of every row is recorded as prefill.
    """
    _refuse_on_violations(traces)
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    shards = []
    for shard_index, start in enumerate(range(0, len(traces), shard_size)):
        chunk = traces[start : start + shard_size]
        max_len = max(trace.num_tokens for trace in chunk)
        indices = np.full((len(chunk), NUM_LAYERS, max_len, TOP_K), -1, dtype=np.int16)
        for local, trace in enumerate(chunk):
            indices[local, :, : trace.num_tokens, :] = trace.experts
        tensor_name = f"routes-{shard_index:05d}.safetensors"
        metadata_name = f"routes-{shard_index:05d}.jsonl"
        save_file(
            {
                "sample_indices": torch.arange(start, start + len(chunk), dtype=torch.int32),
                "sequence_lengths": torch.tensor([t.num_tokens for t in chunk], dtype=torch.int32),
                "topk_indices": torch.from_numpy(indices),
                # The third-party CSVs carry no gate weights.  Zero is a placeholder;
                # no replay policy reads gate mass.
                "topk_weights": torch.zeros(indices.shape, dtype=torch.float16),
            },
            output / tensor_name,
        )
        with (output / metadata_name).open("w", encoding="utf-8") as handle:
            for local, trace in enumerate(chunk):
                row = {
                    "collection_index": start + local,
                    "id": trace.request_id,
                    "metadata": {
                        "source_dataset": dataset_label,
                        "source_file": trace.src_file,
                        "source_sha256": trace.src_sha256,
                        "num_tokens": trace.num_tokens,
                    },
                }
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        shards.append(
            {
                "tensor_file": tensor_name,
                "metadata_file": metadata_name,
                "tensor_sha256": sha256_file(output / tensor_name),
                "metadata_sha256": sha256_file(output / metadata_name),
            }
        )
    manifest = {
        "schema_version": 1,
        "collection": {
            "kind": "autoregressive_decode",
            "replay_model": "E1_per_token_sequential_positions",
            "physical_phase": "prefill",
            "note": (
                "Rows come from one prefill forward pass per prompt. They are laid "
                "out as sequential positions so that the package's FCFS builder can "
                "replay the declared E1 contract; no decode step was recorded."
            ),
            "gate_weights": "absent_in_source_zero_placeholder",
        },
        "model": _model_block(),
        "third_party": _third_party_block(),
        "dataset_label": dataset_label,
        "completed_samples": len(traces),
        "shards": shards,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output


def build_e2_trace(
    traces: Sequence[PromptTrace],
    output: Path | str,
    *,
    dataset_label: str,
) -> Path:
    """Write one event per (request, layer): the union over all prompt positions."""
    _refuse_on_violations(traces)
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output}")
    request_indices: list[int] = []
    steps: list[int] = []
    layer_ids: list[int] = []
    token_counts: list[int] = []
    offsets = [0]
    expert_ids: list[int] = []
    assignment_counts: list[int] = []
    logical = 0
    for request_index, trace in enumerate(traces):
        for layer in range(NUM_LAYERS):
            counts = np.bincount(
                trace.experts[layer].reshape(-1).astype(np.int64),
                minlength=NUM_EXPERTS,
            )
            union = np.flatnonzero(counts)
            logical += int(counts.sum())
            request_indices.append(request_index)
            steps.append(request_index)
            layer_ids.append(layer)
            token_counts.append(trace.num_tokens)
            expert_ids.extend(union.tolist())
            assignment_counts.extend(counts[union].tolist())
            offsets.append(len(expert_ids))
    with_requests = output / "requests.jsonl"
    output.mkdir(parents=True, exist_ok=True)
    with with_requests.open("w", encoding="utf-8") as handle:
        for request_index, trace in enumerate(traces):
            handle.write(
                json.dumps(
                    {
                        "request_index": request_index,
                        "id": trace.request_id,
                        "source_file": trace.src_file,
                        "source_sha256": trace.src_sha256,
                        "num_tokens": trace.num_tokens,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )
    manifest = {
        "kind": "prefill_event_trace",
        "status": "complete",
        "model": _model_block(),
        "third_party": _third_party_block(),
        "dataset_label": dataset_label,
        "conversion": {
            "batch_size": 1,
            "event_semantics": "E2_whole_prefill_union_per_layer",
            "queue_order": "source",
            "scheduler": "sequential_requests",
            "gate_weights": "absent_in_source_zero_placeholder",
        },
        "counts": {
            "requests": len(traces),
            "events": len(layer_ids),
            "union_expert_accesses": len(expert_ids),
            "logical_expert_assignments_before_dedup": logical,
        },
        "artifacts": {
            "requests": {
                "path": with_requests.name,
                "sha256": sha256_file(with_requests),
                "bytes": with_requests.stat().st_size,
            }
        },
    }
    return save_event_trace(
        output,
        manifest=manifest,
        request_indices=np.asarray(request_indices),
        scheduler_steps=np.asarray(steps),
        forward_cycles=np.asarray(steps),
        phases=np.full(len(layer_ids), PHASE_PREFILL, dtype=np.uint8),
        layer_ids=np.asarray(layer_ids),
        token_counts=np.asarray(token_counts),
        offsets=np.asarray(offsets),
        expert_ids=np.asarray(expert_ids),
        assignment_counts=np.asarray(assignment_counts),
        gate_mass=np.zeros(len(expert_ids), dtype=np.float32),
    )


def to_moebeyond_format(
    rows: Sequence[tuple[int, Sequence[int], Sequence[int]]],
    path: Path | str,
) -> Path:
    """Write rows in the third-party simulator's predicted-CSV input format.

    ``rows`` are (raw layer id, activated experts, predicted experts) in file
    order.  The ``Token`` column is the per-layer position, as in the
    published predicted files.  The third-party replay derives token order with
    ``groupby('Layer ID').cumcount()``, so file order within a layer is the
    position order.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    positions: dict[int, int] = defaultdict(int)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Layer ID", "Token", EXPERT_COLUMN, PREDICTED_COLUMN])
        for layer, experts, predicted in rows:
            writer.writerow(
                [layer, positions[layer], str(list(experts)), str(list(predicted))]
            )
            positions[layer] += 1
    return path
