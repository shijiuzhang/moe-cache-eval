from __future__ import annotations

import heapq
import math
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Iterable

import numpy as np

from .events import EventTrace


SUPPORTED_POLICIES = (
    "demand",
    "static",
    "lru",
    "lfu",
    "lfru",
    "least_stale",
    "belady",
)
ATOMIC_PROBE_POLICIES = ("belady_forced_admit",)


@dataclass(frozen=True)
class SimulationResult:
    policy: str
    cache_scope: str
    capacity_blocks: int
    capacity_fraction: float
    total_expert_blocks: int
    total_accesses: int
    hits: int
    misses: int
    compulsory_misses: int
    capacity_misses: int
    collision_misses: int
    evictions: int
    cache_insertions: int
    cache_churn_blocks: int
    churn_blocks_per_1000_steps: float
    initial_load_blocks: int
    transferred_blocks: int
    hit_ratio: float
    miss_ratio: float
    collision_miss_ratio: float
    blocks_per_model_token: float
    event_miss_p50: float
    event_miss_p95: float
    event_miss_p99: float
    step_miss_p50: float
    step_miss_p95: float
    step_miss_p99: float
    max_step_misses: int
    event_semantics: str = "sequential"
    access_order: str = "source"
    access_order_seed: int | None = None
    event_misses: tuple[int, ...] | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class CachePolicy:
    def __init__(self) -> None:
        self.clock = 0
        self.last_access: dict[int, int] = {}
        self.last_cycle: dict[int, int] = {}
        self.frequency: Counter[int] = Counter()

    def choose_victim(
        self,
        cache: set[int],
        *,
        cycle: int,
        layer: int,
    ) -> int:
        raise NotImplementedError

    def record_access(
        self,
        block: int,
        *,
        cycle: int,
        layer: int,
        next_use: int | None = None,
    ) -> None:
        self.clock += 1
        self.last_access[block] = self.clock
        self.last_cycle[block] = cycle
        self.frequency[block] += 1

    def record_eviction(self, block: int) -> None:
        return None


class LRUPolicy(CachePolicy):
    def choose_victim(
        self,
        cache: set[int],
        *,
        cycle: int,
        layer: int,
    ) -> int:
        return min(cache, key=lambda block: (self.last_access[block], block))


class LFUPolicy(CachePolicy):
    def choose_victim(
        self,
        cache: set[int],
        *,
        cycle: int,
        layer: int,
    ) -> int:
        return min(
            cache,
            key=lambda block: (
                self.frequency[block],
                self.last_access[block],
                block,
            ),
        )


class LFRUPolicy(CachePolicy):
    def choose_victim(
        self,
        cache: set[int],
        *,
        cycle: int,
        layer: int,
    ) -> int:
        def score(block: int) -> tuple[float, int]:
            age = self.clock - self.last_access[block] + 1
            return (self.frequency[block] / age, block)

        return min(cache, key=score)


class LeastStalePolicy(CachePolicy):
    """Two-generation Least-Stale baseline from the SpecMD description.

    Blocks not touched in the current forward cycle are stale and are evicted
    before current blocks. FIFO/last-access order breaks ties. Without
    prefetching this policy is expected to be close to LRU; preserving it as a
    distinct implementation makes that diagnostic explicit.
    """

    def choose_victim(
        self,
        cache: set[int],
        *,
        cycle: int,
        layer: int,
    ) -> int:
        stale = [
            block
            for block in cache
            if self.last_cycle.get(block, -1) < cycle
        ]
        candidates = stale if stale else list(cache)
        return min(
            candidates,
            key=lambda block: (self.last_access[block], block),
        )


class BeladyPolicy(CachePolicy):
    def __init__(self) -> None:
        super().__init__()
        self.next_use: dict[int, int] = {}

    def choose_victim(
        self,
        cache: set[int],
        *,
        cycle: int,
        layer: int,
    ) -> int:
        return max(
            cache,
            key=lambda block: (self.next_use.get(block, math.inf), block),
        )

    def record_access(
        self,
        block: int,
        *,
        cycle: int,
        layer: int,
        next_use: int | None = None,
    ) -> None:
        super().record_access(
            block,
            cycle=cycle,
            layer=layer,
            next_use=next_use,
        )
        self.next_use[block] = math.inf if next_use is None else next_use


def _policy(name: str) -> CachePolicy:
    if name == "lru":
        return LRUPolicy()
    if name == "lfu":
        return LFUPolicy()
    if name == "lfru":
        return LFRUPolicy()
    if name == "least_stale":
        return LeastStalePolicy()
    if name == "belady":
        return BeladyPolicy()
    raise ValueError(f"No dynamic policy implementation for {name!r}.")


def flatten_accesses(
    trace: EventTrace,
    *,
    access_order: str = "source",
    access_order_seed: int | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    lengths = np.diff(trace.offsets).astype(np.int64, copy=False)
    event_indices = np.repeat(
        np.arange(trace.num_events, dtype=np.int32),
        lengths,
    )
    layers = np.repeat(trace.layer_ids.astype(np.int32, copy=False), lengths)
    cycles = np.repeat(
        trace.forward_cycles.astype(np.int32, copy=False),
        lengths,
    )
    block_ids = (
        layers.astype(np.int64) * trace.num_experts_per_layer
        + trace.expert_ids.astype(np.int64, copy=False)
    )
    if access_order not in {"source", "reverse", "seeded_random"}:
        raise ValueError(
            "access_order must be source, reverse, or seeded_random."
        )
    if access_order != "source":
        block_ids = block_ids.copy()
        rng = np.random.default_rng(access_order_seed)
        for event_index in range(trace.num_events):
            start = int(trace.offsets[event_index])
            end = int(trace.offsets[event_index + 1])
            if access_order == "reverse":
                block_ids[start:end] = block_ids[start:end][::-1]
            else:
                rng.shuffle(block_ids[start:end])
    return block_ids, event_indices, cycles, layers


def compute_next_uses(block_ids: np.ndarray) -> np.ndarray:
    next_uses = np.full(block_ids.shape, -1, dtype=np.int64)
    next_position: dict[int, int] = {}
    for position in range(len(block_ids) - 1, -1, -1):
        block = int(block_ids[position])
        next_uses[position] = next_position.get(block, -1)
        next_position[block] = position
    return next_uses


def _quantile(values: np.ndarray, probability: float) -> float:
    if values.size == 0:
        return 0.0
    return float(np.quantile(values, probability, method="higher"))


def _result(
    trace: EventTrace,
    *,
    policy: str,
    cache_scope: str,
    capacity_blocks: int,
    hits: int,
    misses: int,
    compulsory_misses: int,
    collision_misses: int,
    evictions: int,
    cache_insertions: int,
    initial_load_blocks: int,
    event_misses: np.ndarray,
    event_semantics: str = "sequential",
    access_order: str = "source",
    access_order_seed: int | None = None,
    include_event_misses: bool = False,
) -> SimulationResult:
    total_accesses = hits + misses
    transferred_blocks = misses + initial_load_blocks
    steps = int(trace.scheduler_steps.max()) + 1 if trace.num_events else 0
    step_misses = np.bincount(
        trace.scheduler_steps.astype(np.int64),
        weights=event_misses,
        minlength=steps,
    ).astype(np.int64)
    layer_zero = trace.layer_ids == 0
    model_tokens = int(trace.token_counts[layer_zero].sum())
    return SimulationResult(
        policy=policy,
        cache_scope=cache_scope,
        capacity_blocks=capacity_blocks,
        capacity_fraction=(
            capacity_blocks / trace.num_expert_blocks
            if trace.num_expert_blocks
            else 0.0
        ),
        total_expert_blocks=trace.num_expert_blocks,
        total_accesses=total_accesses,
        hits=hits,
        misses=misses,
        compulsory_misses=compulsory_misses,
        capacity_misses=misses - compulsory_misses,
        collision_misses=collision_misses,
        evictions=evictions,
        cache_insertions=cache_insertions,
        cache_churn_blocks=cache_insertions + evictions,
        churn_blocks_per_1000_steps=(
            1000.0 * (cache_insertions + evictions) / steps
            if steps
            else 0.0
        ),
        initial_load_blocks=initial_load_blocks,
        transferred_blocks=transferred_blocks,
        hit_ratio=hits / total_accesses if total_accesses else 0.0,
        miss_ratio=misses / total_accesses if total_accesses else 0.0,
        collision_miss_ratio=(
            collision_misses / misses if misses else 0.0
        ),
        blocks_per_model_token=(
            transferred_blocks / model_tokens if model_tokens else 0.0
        ),
        event_miss_p50=_quantile(event_misses, 0.50),
        event_miss_p95=_quantile(event_misses, 0.95),
        event_miss_p99=_quantile(event_misses, 0.99),
        step_miss_p50=_quantile(step_misses, 0.50),
        step_miss_p95=_quantile(step_misses, 0.95),
        step_miss_p99=_quantile(step_misses, 0.99),
        max_step_misses=int(step_misses.max()) if step_misses.size else 0,
        event_semantics=event_semantics,
        access_order=access_order,
        access_order_seed=access_order_seed,
        event_misses=(
            tuple(int(value) for value in event_misses)
            if include_event_misses
            else None
        ),
    )


def simulate_static_fixed(
    trace: EventTrace,
    *,
    resident_blocks: Iterable[int],
    include_event_misses: bool = False,
) -> SimulationResult:
    """Evaluate one externally frozen pinned-expert set on an event trace."""
    resident_ids = np.asarray(sorted(set(int(value) for value in resident_blocks)))
    if np.any(resident_ids < 0) or np.any(resident_ids >= trace.num_expert_blocks):
        raise ValueError("resident_blocks contains an out-of-range block")
    resident = np.zeros(trace.num_expert_blocks, dtype=np.bool_)
    resident[resident_ids] = True
    event_misses = np.zeros(trace.num_events, dtype=np.int64)
    hits = 0
    misses = 0
    seen: set[int] = set()
    for event_index in range(trace.num_events):
        blocks = trace.block_ids_for_event(event_index)
        event_hits = int(resident[blocks].sum())
        event_miss_count = len(blocks) - event_hits
        hits += event_hits
        misses += event_miss_count
        event_misses[event_index] = event_miss_count
        seen.update(int(value) for value in blocks)
    return _result(
        trace,
        policy="static_fixed",
        cache_scope="frozen_external",
        capacity_blocks=len(resident_ids),
        hits=hits,
        misses=misses,
        compulsory_misses=len(seen),
        collision_misses=0,
        evictions=0,
        cache_insertions=len(resident_ids),
        initial_load_blocks=len(resident_ids),
        event_misses=event_misses,
        event_semantics="atomic",
        access_order="simultaneous_set",
        include_event_misses=include_event_misses,
    )


def simulate(
    trace: EventTrace,
    *,
    policy: str,
    capacity_blocks: int,
    cache_scope: str = "global",
    access_order: str = "source",
    access_order_seed: int | None = None,
) -> SimulationResult:
    if policy not in SUPPORTED_POLICIES:
        raise ValueError(f"Unsupported policy {policy!r}.")
    if capacity_blocks < 0 or capacity_blocks > trace.num_expert_blocks:
        raise ValueError("capacity_blocks is outside the model block range.")
    if cache_scope not in {"global", "per_layer"}:
        raise ValueError("cache_scope must be 'global' or 'per_layer'.")

    block_ids, event_indices, cycles, layers = flatten_accesses(
        trace,
        access_order=access_order,
        access_order_seed=access_order_seed,
    )
    event_misses = np.zeros(trace.num_events, dtype=np.int64)
    if policy == "demand" or capacity_blocks == 0:
        for event_index in event_indices:
            event_misses[int(event_index)] += 1
        distinct = len(np.unique(block_ids))
        return _result(
            trace,
            policy=policy,
            cache_scope=cache_scope,
            capacity_blocks=capacity_blocks,
            hits=0,
            misses=len(block_ids),
            compulsory_misses=distinct,
            collision_misses=0,
            evictions=0,
            cache_insertions=0,
            initial_load_blocks=0,
            event_misses=event_misses,
            access_order=access_order,
            access_order_seed=access_order_seed,
        )

    if policy == "static":
        frequencies = np.bincount(
            block_ids,
            minlength=trace.num_expert_blocks,
        )
        resident: set[int] = set()
        if cache_scope == "global":
            ranking = np.lexsort(
                (
                    np.arange(trace.num_expert_blocks),
                    -frequencies,
                )
            )
            resident.update(int(value) for value in ranking[:capacity_blocks])
        else:
            base = capacity_blocks // trace.num_layers
            remainder = capacity_blocks % trace.num_layers
            for layer_id in range(trace.num_layers):
                layer_capacity = base + int(layer_id < remainder)
                start = layer_id * trace.num_experts_per_layer
                end = start + trace.num_experts_per_layer
                local_blocks = np.arange(start, end)
                local_ranking = np.lexsort(
                    (
                        local_blocks,
                        -frequencies[start:end],
                    )
                )
                resident.update(
                    int(local_blocks[index])
                    for index in local_ranking[:layer_capacity]
                )
        hits = 0
        misses = 0
        seen: set[int] = set()
        compulsory = 0
        for block_value, event_index_value in zip(block_ids, event_indices):
            block = int(block_value)
            if block not in seen:
                compulsory += 1
                seen.add(block)
            if block in resident:
                hits += 1
            else:
                misses += 1
                event_misses[int(event_index_value)] += 1
        return _result(
            trace,
            policy=policy,
            cache_scope=cache_scope,
            capacity_blocks=capacity_blocks,
            hits=hits,
            misses=misses,
            compulsory_misses=compulsory,
            collision_misses=0,
            evictions=0,
            cache_insertions=len(resident),
            initial_load_blocks=len(resident),
            event_misses=event_misses,
            access_order=access_order,
            access_order_seed=access_order_seed,
        )

    cache_mask = np.zeros(trace.num_expert_blocks, dtype=np.bool_)
    num_buckets = 1 if cache_scope == "global" else trace.num_layers
    cache_sizes = np.zeros(num_buckets, dtype=np.int32)
    if cache_scope == "global":
        bucket_capacities = np.asarray([capacity_blocks], dtype=np.int32)
    else:
        base = capacity_blocks // trace.num_layers
        remainder = capacity_blocks % trace.num_layers
        bucket_capacities = np.asarray(
            [
                base + int(layer_id < remainder)
                for layer_id in range(trace.num_layers)
            ],
            dtype=np.int32,
        )
    next_uses = (
        compute_next_uses(block_ids) if policy == "belady" else None
    )
    last_access = np.full(trace.num_expert_blocks, -1, dtype=np.int64)
    last_cycle = np.full(trace.num_expert_blocks, -1, dtype=np.int64)
    frequency = np.zeros(trace.num_expert_blocks, dtype=np.int64)
    current_next_use = np.full(
        trace.num_expert_blocks,
        len(block_ids) + 1,
        dtype=np.int64,
    )
    lru_heaps: list[list[tuple[int, int]]] = [
        [] for _ in range(num_buckets)
    ]
    lfu_heaps: list[list[tuple[int, int, int]]] = [
        [] for _ in range(num_buckets)
    ]
    belady_heaps: list[list[tuple[int, int, int]]] = [
        [] for _ in range(num_buckets)
    ]

    def choose_heap_victim(
        current_policy: str,
        *,
        bucket: int,
        clock: int,
    ) -> int:
        if current_policy in {"lru", "least_stale"}:
            heap = lru_heaps[bucket]
            while heap:
                access_time, candidate = heapq.heappop(heap)
                if (
                    cache_mask[candidate]
                    and int(last_access[candidate]) == access_time
                ):
                    return candidate
        elif current_policy == "lfu":
            heap = lfu_heaps[bucket]
            while heap:
                count, access_time, candidate = heapq.heappop(heap)
                if (
                    cache_mask[candidate]
                    and int(frequency[candidate]) == count
                    and int(last_access[candidate]) == access_time
                ):
                    return candidate
        elif current_policy == "belady":
            heap = belady_heaps[bucket]
            while heap:
                negative_next, negative_block, candidate = heapq.heappop(
                    heap
                )
                expected = -negative_next
                if (
                    cache_mask[candidate]
                    and int(current_next_use[candidate]) == expected
                    and -negative_block == candidate
                ):
                    return candidate
        raise RuntimeError(f"No valid victim for {current_policy}.")

    seen: set[int] = set()
    last_evicted_cycle: dict[int, int] = {}
    hits = 0
    misses = 0
    compulsory = 0
    collision = 0
    evictions = 0
    insertions = 0

    for position, (
        block_value,
        event_index_value,
        cycle_value,
        layer_value,
    ) in enumerate(zip(block_ids, event_indices, cycles, layers)):
        block = int(block_value)
        event_index = int(event_index_value)
        cycle = int(cycle_value)
        layer = int(layer_value)
        bucket = 0 if cache_scope == "global" else layer
        if block not in seen:
            compulsory += 1
            seen.add(block)
        if cache_mask[block]:
            hits += 1
        else:
            misses += 1
            event_misses[event_index] += 1
            if last_evicted_cycle.get(block) == cycle:
                collision += 1
            should_insert = int(bucket_capacities[bucket]) > 0
            if (
                should_insert
                and int(cache_sizes[bucket])
                >= int(bucket_capacities[bucket])
            ):
                if policy == "lfru":
                    if cache_scope == "global":
                        candidates = np.flatnonzero(cache_mask)
                    else:
                        start = layer * trace.num_experts_per_layer
                        end = start + trace.num_experts_per_layer
                        candidates = (
                            np.flatnonzero(cache_mask[start:end]) + start
                        )
                    ages = position - last_access[candidates] + 1
                    scores = frequency[candidates] / ages
                    victim = int(candidates[int(np.argmin(scores))])
                else:
                    victim = choose_heap_victim(
                        policy,
                        bucket=bucket,
                        clock=position,
                    )
                if policy == "belady":
                    incoming_next = len(block_ids) + 1
                    if (
                        next_uses is not None
                        and int(next_uses[position]) >= 0
                    ):
                        incoming_next = int(next_uses[position])
                    victim_next = int(current_next_use[victim])
                    if incoming_next >= victim_next:
                        should_insert = False
                        # Victim selection pops the heap entry. When Belady
                        # bypasses the incoming one-use/far-future block, the
                        # victim remains resident and must remain selectable.
                        heapq.heappush(
                            belady_heaps[bucket],
                            (-victim_next, -victim, victim),
                        )
                if should_insert:
                    cache_mask[victim] = False
                    last_evicted_cycle[victim] = cycle
                    evictions += 1
                    cache_sizes[bucket] -= 1
            if should_insert:
                cache_mask[block] = True
                cache_sizes[bucket] += 1
                insertions += 1
        access_clock = position + 1
        last_access[block] = access_clock
        last_cycle[block] = cycle
        frequency[block] += 1
        if policy in {"lru", "least_stale"}:
            if cache_mask[block]:
                heapq.heappush(
                    lru_heaps[bucket],
                    (access_clock, block),
                )
        elif policy == "lfu":
            if cache_mask[block]:
                heapq.heappush(
                    lfu_heaps[bucket],
                    (int(frequency[block]), access_clock, block),
                )
        elif policy == "belady":
            next_key = len(block_ids) + 1
            if next_uses is not None and int(next_uses[position]) >= 0:
                next_key = int(next_uses[position])
            current_next_use[block] = next_key
            if cache_mask[block]:
                heapq.heappush(
                    belady_heaps[bucket],
                    (-next_key, -block, block),
                )

    return _result(
        trace,
        policy=policy,
        cache_scope=cache_scope,
        capacity_blocks=capacity_blocks,
        hits=hits,
        misses=misses,
        compulsory_misses=compulsory,
        collision_misses=collision,
        evictions=evictions,
        cache_insertions=insertions,
        initial_load_blocks=0,
        event_misses=event_misses,
        access_order=access_order,
        access_order_seed=access_order_seed,
    )


def simulate_event_atomic(
    trace: EventTrace,
    *,
    policy: str,
    capacity_blocks: int,
    cache_scope: str = "global",
    tie_seed: int = 20260729,
    include_event_misses: bool = False,
) -> SimulationResult:
    """Replay events as simultaneous expert-set requests.

    Hits are determined from cache residency at event start. All misses are
    fetched for that event before an end-of-event retention decision. This
    prevents an arbitrary expert execution order from evicting a resident
    expert that is still needed by the same fused MoE event.
    """
    if policy not in SUPPORTED_POLICIES + ATOMIC_PROBE_POLICIES:
        raise ValueError(f"Unsupported policy {policy!r}.")
    if capacity_blocks < 0 or capacity_blocks > trace.num_expert_blocks:
        raise ValueError("capacity_blocks is outside the model block range.")
    if cache_scope not in {"global", "per_layer"}:
        raise ValueError("cache_scope must be 'global' or 'per_layer'.")

    block_ids, event_indices, _, _ = flatten_accesses(trace)
    event_misses = np.zeros(trace.num_events, dtype=np.int64)
    if policy == "demand" or capacity_blocks == 0:
        lengths = np.diff(trace.offsets).astype(np.int64, copy=False)
        event_misses[:] = lengths
        return _result(
            trace,
            policy=policy,
            cache_scope=cache_scope,
            capacity_blocks=capacity_blocks,
            hits=0,
            misses=len(block_ids),
            compulsory_misses=len(np.unique(block_ids)),
            collision_misses=0,
            evictions=0,
            cache_insertions=0,
            initial_load_blocks=0,
            event_misses=event_misses,
            event_semantics="atomic",
            access_order="simultaneous_set",
            access_order_seed=tie_seed,
            include_event_misses=include_event_misses,
        )

    if cache_scope == "global":
        bucket_capacities = np.asarray([capacity_blocks], dtype=np.int32)
    else:
        base = capacity_blocks // trace.num_layers
        remainder = capacity_blocks % trace.num_layers
        bucket_capacities = np.asarray(
            [
                base + int(layer_id < remainder)
                for layer_id in range(trace.num_layers)
            ],
            dtype=np.int32,
        )

    if policy == "static":
        frequencies = np.bincount(
            block_ids,
            minlength=trace.num_expert_blocks,
        )
        resident = np.zeros(trace.num_expert_blocks, dtype=np.bool_)
        if cache_scope == "global":
            ranking = np.lexsort(
                (np.arange(trace.num_expert_blocks), -frequencies)
            )
            resident[ranking[:capacity_blocks]] = True
        else:
            for layer in range(trace.num_layers):
                start = layer * trace.num_experts_per_layer
                end = start + trace.num_experts_per_layer
                local = np.arange(start, end)
                ranking = np.lexsort((local, -frequencies[start:end]))
                resident[local[ranking[: int(bucket_capacities[layer])]]] = True
        hits = int(resident[block_ids].sum())
        misses = len(block_ids) - hits
        missing = ~resident[block_ids]
        np.add.at(event_misses, event_indices[missing], 1)
        return _result(
            trace,
            policy=policy,
            cache_scope=cache_scope,
            capacity_blocks=capacity_blocks,
            hits=hits,
            misses=misses,
            compulsory_misses=len(np.unique(block_ids)),
            collision_misses=0,
            evictions=0,
            cache_insertions=int(resident.sum()),
            initial_load_blocks=int(resident.sum()),
            event_misses=event_misses,
            event_semantics="atomic",
            access_order="simultaneous_set",
            access_order_seed=tie_seed,
            include_event_misses=include_event_misses,
        )

    sentinel = trace.num_events + 1
    next_event_for_access = np.full(
        trace.num_accesses,
        sentinel,
        dtype=np.int64,
    )
    if policy in {"belady", "belady_forced_admit"}:
        next_by_block: dict[int, int] = {}
        for event_index in range(trace.num_events - 1, -1, -1):
            start = int(trace.offsets[event_index])
            end = int(trace.offsets[event_index + 1])
            blocks = trace.block_ids_for_event(event_index)
            for offset, block_value in enumerate(blocks):
                block = int(block_value)
                next_event_for_access[start + offset] = next_by_block.get(
                    block,
                    sentinel,
                )
            for block_value in blocks:
                next_by_block[int(block_value)] = event_index

    rng = np.random.default_rng(tie_seed)
    tie_priority = rng.random(trace.num_expert_blocks)
    cache = np.zeros(trace.num_expert_blocks, dtype=np.bool_)
    frequency = np.zeros(trace.num_expert_blocks, dtype=np.int64)
    last_event = np.full(trace.num_expert_blocks, -1, dtype=np.int64)
    next_event = np.full(
        trace.num_expert_blocks,
        sentinel,
        dtype=np.int64,
    )
    seen = np.zeros(trace.num_expert_blocks, dtype=np.bool_)
    hits = 0
    misses = 0
    compulsory = 0
    evictions = 0
    insertions = 0

    for event_index in range(trace.num_events):
        blocks = trace.block_ids_for_event(event_index)
        start_offset = int(trace.offsets[event_index])
        resident_at_start = cache[blocks]
        event_hits = int(resident_at_start.sum())
        event_miss_count = len(blocks) - event_hits
        hits += event_hits
        misses += event_miss_count
        event_misses[event_index] = event_miss_count
        new_blocks = ~seen[blocks]
        compulsory += int(new_blocks.sum())
        seen[blocks] = True

        frequency[blocks] += 1
        last_event[blocks] = event_index
        if policy in {"belady", "belady_forced_admit"}:
            next_event[blocks] = next_event_for_access[
                start_offset : start_offset + len(blocks)
            ]

        layer = int(trace.layer_ids[event_index])
        bucket = 0 if cache_scope == "global" else layer
        capacity = int(bucket_capacities[bucket])
        if cache_scope == "global":
            old_resident = np.flatnonzero(cache)
        else:
            layer_start = layer * trace.num_experts_per_layer
            layer_end = layer_start + trace.num_experts_per_layer
            old_resident = (
                np.flatnonzero(cache[layer_start:layer_end]) + layer_start
            )
        candidates = np.union1d(old_resident, blocks)
        if capacity == 0:
            kept = np.empty(0, dtype=np.int64)
        elif len(candidates) <= capacity:
            kept = candidates
        else:
            if policy in {"lru", "least_stale"}:
                order = np.lexsort(
                    (
                        -tie_priority[candidates],
                        -last_event[candidates],
                    )
                )
            elif policy == "lfu":
                order = np.lexsort(
                    (
                        -tie_priority[candidates],
                        -last_event[candidates],
                        -frequency[candidates],
                    )
                )
            elif policy == "lfru":
                ages = event_index - last_event[candidates] + 1
                scores = frequency[candidates] / ages
                order = np.lexsort(
                    (-tie_priority[candidates], -scores)
                )
            elif policy == "belady":
                order = np.lexsort(
                    (-tie_priority[candidates], next_event[candidates])
                )
            elif policy == "belady_forced_admit":
                # Diagnostic oracle: retain every newly fetched block whenever
                # capacity permits, while keeping Belady's perfect future
                # victim ranking for all remaining slots.  The delta from
                # ordinary Belady isolates optional bypass admission; the
                # delta from a causal policy isolates future-victim knowledge.
                required = blocks[~resident_at_start]
                if len(required) >= capacity:
                    order = np.lexsort(
                        (-tie_priority[required], next_event[required])
                    )
                    kept = required[order[:capacity]]
                else:
                    optional = np.setdiff1d(
                        candidates, required, assume_unique=True
                    )
                    remaining = capacity - len(required)
                    order = np.lexsort(
                        (-tie_priority[optional], next_event[optional])
                    )
                    kept = np.concatenate(
                        (required, optional[order[:remaining]])
                    )
            else:
                raise ValueError(f"Unsupported atomic policy {policy!r}.")
            if policy != "belady_forced_admit":
                kept = candidates[order[:capacity]]

        old_mask = cache[old_resident].copy()
        if old_mask.size and not np.all(old_mask):
            raise RuntimeError("Atomic cache index inconsistency.")
        kept_set = np.zeros(trace.num_expert_blocks, dtype=np.bool_)
        kept_set[kept] = True
        evictions += int((~kept_set[old_resident]).sum())
        insertions += int((~cache[kept]).sum())
        cache[old_resident] = False
        cache[kept] = True

    return _result(
        trace,
        policy=policy,
        cache_scope=cache_scope,
        capacity_blocks=capacity_blocks,
        hits=hits,
        misses=misses,
        compulsory_misses=compulsory,
        collision_misses=0,
        evictions=evictions,
        cache_insertions=insertions,
        initial_load_blocks=0,
        event_misses=event_misses,
        event_semantics="atomic",
        access_order="simultaneous_set",
        access_order_seed=tie_seed,
        include_event_misses=include_event_misses,
    )


def capacity_blocks_from_fractions(
    trace: EventTrace,
    fractions: Iterable[float],
) -> list[int]:
    values = {
        min(
            trace.num_expert_blocks,
            max(1, int(round(trace.num_expert_blocks * fraction))),
        )
        for fraction in fractions
    }
    return sorted(values)
