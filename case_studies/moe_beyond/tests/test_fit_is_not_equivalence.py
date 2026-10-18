"""D-006 regression control: events that fit in capacity can still be counted
differently by per-access and event-atomic replay.

Expected counts are derived by hand in DEVIATIONS.md D-006 (one layer, capacity
2, LRU, ascending access order; events {1, 3} then {0, 1}):
per-access 4 misses / 0 hits; event-atomic 3 misses / 1 hit.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from moe_controller.events import PHASE_DECODE, EventTrace  # noqa: E402
from moe_controller.simulation import simulate, simulate_event_atomic  # noqa: E402


def _trace() -> EventTrace:
    events = ((1, 3), (0, 1))
    offsets = np.cumsum([0] + [len(e) for e in events])
    return EventTrace(
        root=Path("."),
        manifest={"schema_version": 1, "model": {"num_layers": 1, "num_experts": 4}},
        request_indices=np.zeros(2, dtype=np.int32),
        scheduler_steps=np.arange(2, dtype=np.int32),
        forward_cycles=np.arange(2, dtype=np.int32),
        phases=np.full(2, PHASE_DECODE, dtype=np.uint8),
        layer_ids=np.zeros(2, dtype=np.int16),
        token_counts=np.ones(2, dtype=np.int32),
        offsets=offsets.astype(np.int64),
        expert_ids=np.asarray([x for e in events for x in e], dtype=np.int16),
        assignment_counts=np.ones(4, dtype=np.int32),
        gate_mass=np.ones(4, dtype=np.float32),
    )


class FitIsNotEquivalenceTests(unittest.TestCase):
    def test_every_event_fits(self) -> None:
        trace = _trace()
        trace.validate()
        self.assertTrue(np.all(np.diff(trace.offsets) <= 2))

    def test_per_access_and_atomic_counts_differ(self) -> None:
        trace = _trace()
        for scope in ("global", "per_layer"):
            sequential = simulate(trace, policy="lru", capacity_blocks=2, cache_scope=scope, access_order="source")
            atomic = simulate_event_atomic(trace, policy="lru", capacity_blocks=2, cache_scope=scope)
            self.assertEqual((sequential.misses, sequential.hits), (4, 0), scope)
            self.assertEqual((atomic.misses, atomic.hits), (3, 1), scope)


if __name__ == "__main__":
    unittest.main()
