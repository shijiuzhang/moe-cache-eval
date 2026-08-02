from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch
from safetensors.torch import save_file

from moe_controller.convert import convert_prefill_trace
from moe_controller.events import (
    PHASE_PREFILL,
    EventTrace,
    load_event_trace,
    reorder_event_trace,
    sha256_file,
    subset_event_trace,
)
from moe_controller.metrics import normalized_topk_boundary_gap
from moe_controller.simulation import (
    simulate,
    simulate_event_atomic,
    simulate_static_fixed,
)


def manual_trace(
    block_events: list[list[int]],
    *,
    cycles: list[int],
    num_layers: int,
    num_experts: int,
) -> EventTrace:
    offsets = [0]
    expert_ids: list[int] = []
    layer_ids: list[int] = []
    for event_index, blocks in enumerate(block_events):
        layer = event_index % num_layers
        layer_ids.append(layer)
        for block in blocks:
            expected_layer = block // num_experts
            if expected_layer != layer:
                raise ValueError("Manual block is assigned to the wrong layer.")
            expert_ids.append(block % num_experts)
        offsets.append(len(expert_ids))
    event_count = len(block_events)
    return EventTrace(
        root=Path("."),
        manifest={
            "schema_version": 1,
            "model": {
                "num_layers": num_layers,
                "num_experts": num_experts,
            },
        },
        request_indices=np.zeros(event_count, dtype=np.int32),
        scheduler_steps=np.asarray(cycles, dtype=np.int32),
        forward_cycles=np.asarray(cycles, dtype=np.int32),
        phases=np.full(event_count, PHASE_PREFILL, dtype=np.uint8),
        layer_ids=np.asarray(layer_ids, dtype=np.int16),
        token_counts=np.ones(event_count, dtype=np.int32),
        offsets=np.asarray(offsets, dtype=np.int64),
        expert_ids=np.asarray(expert_ids, dtype=np.int16),
        assignment_counts=np.ones(len(expert_ids), dtype=np.int32),
        gate_mass=np.ones(len(expert_ids), dtype=np.float32),
    )


class CachePolicyTests(unittest.TestCase):
    def test_frozen_static_resident_set_is_not_refit(self) -> None:
        trace = manual_trace(
            [[0], [1], [0]],
            cycles=[0, 1, 2],
            num_layers=1,
            num_experts=2,
        )
        pinned_zero = simulate_static_fixed(trace, resident_blocks=[0])
        pinned_one = simulate_static_fixed(trace, resident_blocks=[1])
        self.assertEqual(pinned_zero.misses, 1)
        self.assertEqual(pinned_zero.transferred_blocks, 2)
        self.assertEqual(pinned_one.misses, 2)
        self.assertEqual(pinned_one.transferred_blocks, 3)

    def test_hand_computed_lru_and_collision(self) -> None:
        trace = manual_trace(
            [[0], [2], [1], [2]],
            cycles=[0, 0, 1, 1],
            num_layers=2,
            num_experts=2,
        )
        trace.validate()
        capacity_two = simulate(trace, policy="lru", capacity_blocks=2)
        self.assertEqual(capacity_two.misses, 3)
        self.assertEqual(capacity_two.hits, 1)
        self.assertEqual(capacity_two.compulsory_misses, 3)
        self.assertEqual(capacity_two.collision_misses, 0)

        capacity_one = simulate(trace, policy="lru", capacity_blocks=1)
        self.assertEqual(capacity_one.misses, 4)
        self.assertEqual(capacity_one.collision_misses, 1)

    def test_static_preload_is_explicit(self) -> None:
        trace = manual_trace(
            [[0], [2], [1], [2]],
            cycles=[0, 0, 1, 1],
            num_layers=2,
            num_experts=2,
        )
        result = simulate(trace, policy="static", capacity_blocks=1)
        self.assertEqual(result.hits, 2)
        self.assertEqual(result.misses, 2)
        self.assertEqual(result.initial_load_blocks, 1)
        self.assertEqual(result.transferred_blocks, 3)

    def test_belady_is_an_offline_upper_bound(self) -> None:
        trace = manual_trace(
            [[0], [1], [2], [0], [1], [2]],
            cycles=[0, 1, 2, 3, 4, 5],
            num_layers=1,
            num_experts=3,
        )
        lru = simulate(trace, policy="lru", capacity_blocks=2)
        belady = simulate(trace, policy="belady", capacity_blocks=2)
        self.assertEqual(lru.misses, 6)
        self.assertEqual(belady.misses, 4)

    def test_belady_can_bypass_one_time_incoming_block(self) -> None:
        trace = manual_trace(
            [[0], [1], [0]],
            cycles=[0, 1, 2],
            num_layers=1,
            num_experts=2,
        )
        belady = simulate(trace, policy="belady", capacity_blocks=1)
        self.assertEqual(belady.misses, 2)
        self.assertEqual(belady.hits, 1)
        self.assertEqual(belady.cache_insertions, 1)
        self.assertEqual(belady.evictions, 0)

    def test_per_layer_scope_respects_total_capacity(self) -> None:
        trace = manual_trace(
            [[0], [2], [0], [3]],
            cycles=[0, 0, 1, 1],
            num_layers=2,
            num_experts=2,
        )
        result = simulate(
            trace,
            policy="static",
            capacity_blocks=2,
            cache_scope="per_layer",
        )
        self.assertEqual(result.cache_scope, "per_layer")
        self.assertEqual(result.initial_load_blocks, 2)
        self.assertEqual(result.cache_insertions, 2)

    def test_event_atomic_does_not_evict_unserved_resident(self) -> None:
        trace = manual_trace(
            [[0, 1], [0, 1]],
            cycles=[0, 1],
            num_layers=1,
            num_experts=2,
        )
        sequential = simulate(
            trace,
            policy="lru",
            capacity_blocks=1,
        )
        atomic = simulate_event_atomic(
            trace,
            policy="lru",
            capacity_blocks=1,
            tie_seed=7,
        )
        self.assertEqual(sequential.misses, 4)
        self.assertEqual(atomic.misses, 3)
        self.assertEqual(atomic.event_semantics, "atomic")

    def test_seeded_random_access_order_is_reproducible(self) -> None:
        trace = manual_trace(
            [[0, 1], [0, 1], [0, 1]],
            cycles=[0, 1, 2],
            num_layers=1,
            num_experts=2,
        )
        first = simulate(
            trace,
            policy="lru",
            capacity_blocks=1,
            access_order="seeded_random",
            access_order_seed=19,
        )
        second = simulate(
            trace,
            policy="lru",
            capacity_blocks=1,
            access_order="seeded_random",
            access_order_seed=19,
        )
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_event_atomic_belady_is_no_worse_than_atomic_lru(self) -> None:
        trace = manual_trace(
            [[0, 1], [1, 2], [0, 2]],
            cycles=[0, 1, 2],
            num_layers=1,
            num_experts=3,
        )
        belady = simulate_event_atomic(
            trace,
            policy="belady",
            capacity_blocks=1,
            tie_seed=3,
        )
        lru = simulate_event_atomic(
            trace,
            policy="lru",
            capacity_blocks=1,
            tie_seed=3,
        )
        self.assertEqual(belady.misses, 4)
        self.assertLessEqual(belady.misses, lru.misses)

    def test_forced_admit_belady_removes_optional_bypass(self) -> None:
        trace = manual_trace(
            [[0], [1], [0]],
            cycles=[0, 1, 2],
            num_layers=1,
            num_experts=2,
        )
        bypass = simulate_event_atomic(
            trace,
            policy="belady",
            capacity_blocks=1,
        )
        forced = simulate_event_atomic(
            trace,
            policy="belady_forced_admit",
            capacity_blocks=1,
        )
        self.assertEqual(bypass.misses, 2)
        self.assertEqual(forced.misses, 3)

    def test_forced_admit_keeps_all_new_blocks_when_they_fit(self) -> None:
        trace = manual_trace(
            [[0, 1], [2], [0, 1]],
            cycles=[0, 1, 2],
            num_layers=1,
            num_experts=3,
        )
        forced = simulate_event_atomic(
            trace,
            policy="belady_forced_admit",
            capacity_blocks=2,
        )
        self.assertEqual(forced.misses, 4)

    def test_event_atomic_can_return_event_miss_timeline(self) -> None:
        trace = manual_trace(
            [[0, 1], [1, 2], [0, 2]],
            cycles=[0, 1, 2],
            num_layers=1,
            num_experts=3,
        )
        result = simulate_event_atomic(
            trace,
            policy="lru",
            capacity_blocks=1,
            include_event_misses=True,
        )
        self.assertEqual(len(result.event_misses or ()), trace.num_events)
        self.assertEqual(sum(result.event_misses or ()), result.misses)

    def test_least_stale_without_prefetch_matches_lru_on_simple_trace(self) -> None:
        trace = manual_trace(
            [[0], [2], [1], [3], [0], [2]],
            cycles=[0, 0, 1, 1, 2, 2],
            num_layers=2,
            num_experts=2,
        )
        lru = simulate(trace, policy="lru", capacity_blocks=2)
        least_stale = simulate(
            trace,
            policy="least_stale",
            capacity_blocks=2,
        )
        self.assertEqual(lru.misses, least_stale.misses)


class ControllerMetricTests(unittest.TestCase):
    def test_normalized_topk_boundary_gap(self) -> None:
        logits = torch.tensor([[4.0, 3.0, 1.0, 0.0]])
        result = normalized_topk_boundary_gap(logits, top_k=2)
        expected = (3.0 - 1.0) / logits.std(
            dim=-1,
            unbiased=False,
        )
        torch.testing.assert_close(result, expected)

    def test_boundary_gap_rejects_invalid_k(self) -> None:
        logits = torch.zeros((2, 3))
        with self.assertRaises(ValueError):
            normalized_topk_boundary_gap(logits, top_k=3)


class EventConversionTests(unittest.TestCase):
    def test_prefill_chunk_conversion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            output = root / "events"
            source.mkdir()
            tensor_path = source / "routes-00000.safetensors"
            metadata_path = source / "samples-00000.jsonl"

            topk_indices = torch.tensor(
                [
                    [
                        [[0, 1], [0, 1], [1, 2]],
                        [[2, 1], [2, 1], [0, 2]],
                    ]
                ],
                dtype=torch.int16,
            )
            topk_weights = torch.tensor(
                [
                    [
                        [[0.75, 0.25], [0.60, 0.40], [0.55, 0.45]],
                        [[0.70, 0.30], [0.80, 0.20], [0.65, 0.35]],
                    ]
                ],
                dtype=torch.float16,
            )
            save_file(
                {
                    "sample_indices": torch.tensor([0], dtype=torch.int64),
                    "sequence_lengths": torch.tensor([3], dtype=torch.int32),
                    "topk_indices": topk_indices,
                    "topk_weights": topk_weights,
                },
                tensor_path,
            )
            metadata_path.write_text(
                json.dumps(
                    {
                        "collection_index": 0,
                        "id": "sample-0",
                        "text": "abc",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            manifest = {
                "completed_samples": 1,
                "model": {
                    "id": "test/model",
                    "commit": "deadbeef",
                    "model_type": "test_moe",
                    "num_layers": 2,
                    "num_experts": 3,
                    "top_k": 2,
                },
                "shards": [
                    {
                        "index": 0,
                        "tensor_file": tensor_path.name,
                        "tensor_sha256": sha256_file(tensor_path),
                        "metadata_file": metadata_path.name,
                        "metadata_sha256": sha256_file(metadata_path),
                    }
                ],
            }
            (source / "manifest.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            convert_prefill_trace(
                source,
                output,
                prefill_chunk_size=2,
            )
            trace = load_event_trace(output)
            self.assertEqual(trace.num_events, 4)
            self.assertEqual(trace.manifest["counts"]["forward_cycles"], 2)
            self.assertEqual(trace.token_counts.tolist(), [2, 2, 1, 1])
            self.assertEqual(trace.event(0).expert_ids.tolist(), [0, 1])
            self.assertEqual(
                trace.event(0).assignment_counts.tolist(),
                [2, 2],
            )
            self.assertEqual(trace.event(2).expert_ids.tolist(), [1, 2])

    def test_subset_event_trace_preserves_selected_requests(self) -> None:
        trace = manual_trace(
            [[0], [2], [1], [3]],
            cycles=[0, 0, 1, 1],
            num_layers=2,
            num_experts=2,
        )
        request_indices = trace.request_indices.copy()
        request_indices[:2] = 10
        request_indices[2:] = 20
        trace = EventTrace(
            **{
                **trace.__dict__,
                "request_indices": request_indices,
            }
        )
        subset = subset_event_trace(trace, [20])
        self.assertEqual(subset.num_events, 2)
        self.assertEqual(subset.num_accesses, 2)
        self.assertEqual(subset.request_indices.tolist(), [20, 20])
        self.assertEqual(subset.scheduler_steps.tolist(), [0, 0])

    def test_reorder_event_trace_preserves_request_internal_order(self) -> None:
        trace = manual_trace(
            [[0], [2], [1], [3]],
            cycles=[0, 0, 1, 1],
            num_layers=2,
            num_experts=2,
        )
        request_indices = trace.request_indices.copy()
        request_indices[:2] = 10
        request_indices[2:] = 20
        trace = EventTrace(
            **{
                **trace.__dict__,
                "request_indices": request_indices,
            }
        )
        reordered = reorder_event_trace(trace, [20, 10])
        self.assertEqual(
            reordered.request_indices.tolist(),
            [20, 20, 10, 10],
        )
        self.assertEqual(reordered.scheduler_steps.tolist(), [0, 0, 1, 1])
        self.assertEqual(reordered.layer_ids.tolist(), [0, 1, 0, 1])


if __name__ == "__main__":
    unittest.main()
