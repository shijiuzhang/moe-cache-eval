from __future__ import annotations

from collections.abc import Mapping, Sequence


def partition_cost(
    groups: Sequence[Sequence[int]],
    signatures: Mapping[int, frozenset[int]],
) -> int:
    """Return the summed expert-union size of a request partition."""
    return sum(
        len(frozenset().union(*(signatures[item] for item in group)))
        for group in groups
        if group
    )


def fcfs_partition(items: Sequence[int], batch_size: int) -> list[list[int]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    return [
        list(items[start : start + batch_size])
        for start in range(0, len(items), batch_size)
    ]


def _canonical(groups: Sequence[Sequence[int]]) -> tuple[tuple[int, ...], ...]:
    return tuple(tuple(group) for group in groups)


def _swap_improve(
    groups: list[list[int]],
    signatures: Mapping[int, frozenset[int]],
) -> list[list[int]]:
    """Deterministic pair-swap local search on the supplied signatures."""
    current = partition_cost(groups, signatures)
    while True:
        best_cost = current
        best: list[list[int]] | None = None
        best_key: tuple[tuple[int, ...], ...] | None = None
        for left_index in range(len(groups)):
            for right_index in range(left_index + 1, len(groups)):
                for left_offset in range(len(groups[left_index])):
                    for right_offset in range(len(groups[right_index])):
                        candidate = [list(group) for group in groups]
                        candidate[left_index][left_offset], candidate[right_index][
                            right_offset
                        ] = (
                            candidate[right_index][right_offset],
                            candidate[left_index][left_offset],
                        )
                        candidate_cost = partition_cost(candidate, signatures)
                        candidate_key = _canonical(candidate)
                        if candidate_cost < best_cost or (
                            candidate_cost == best_cost
                            and best is not None
                            and candidate_key < best_key
                        ):
                            best_cost = candidate_cost
                            best = candidate
                            best_key = candidate_key
        if best is None or best_cost >= current:
            return groups
        groups = best
        current = best_cost


def affinity_partition(
    items: Sequence[int],
    signatures: Mapping[int, frozenset[int]],
    batch_size: int,
) -> list[list[int]]:
    """Group requests by predicted expert overlap without future information.

    The routine is deliberately small and frozen: compare an FCFS seed with a
    similarity-greedy seed, improve each by deterministic pair swaps, and keep
    the lower predicted-union partition. Empty signatures force FCFS, which is
    the required cold-start behavior for first-token requests.
    """
    ordered = list(items)
    if len(set(ordered)) != len(ordered):
        raise ValueError("items cannot contain duplicates")
    if any(item not in signatures for item in ordered):
        raise ValueError("every item needs a signature")
    baseline = fcfs_partition(ordered, batch_size)
    if not ordered or not any(signatures[item] for item in ordered):
        return baseline

    remaining = list(ordered)
    greedy: list[list[int]] = []
    while remaining:
        seed = max(
            remaining,
            key=lambda item: (
                sum(
                    len(signatures[item] & signatures[other])
                    for other in remaining
                    if other != item
                ),
                -ordered.index(item),
            ),
        )
        group = [seed]
        remaining.remove(seed)
        while remaining and len(group) < batch_size:
            current_union = frozenset().union(
                *(signatures[item] for item in group)
            )
            candidate = min(
                remaining,
                key=lambda item: (
                    len(current_union | signatures[item]) - len(current_union),
                    ordered.index(item),
                ),
            )
            group.append(candidate)
            remaining.remove(candidate)
        greedy.append(group)

    candidates = [
        _swap_improve([list(group) for group in baseline], signatures),
        _swap_improve(greedy, signatures),
    ]
    return min(
        candidates,
        key=lambda groups: (partition_cost(groups, signatures), _canonical(groups)),
    )


def select_affinity_batch(
    items: Sequence[int],
    signatures: Mapping[int, frozenset[int]],
    batch_size: int,
    *,
    required: Sequence[int] = (),
    priority: Mapping[int, tuple[int, int]],
) -> list[int]:
    """Select one deadline-feasible batch using only supplied signatures."""
    ordered = list(items)
    required_items = sorted(set(required), key=lambda item: priority[item])
    if len(required_items) > batch_size:
        raise ValueError("More deadline-required requests than batch capacity")
    if any(item not in signatures or item not in priority for item in ordered):
        raise ValueError("every item needs a signature and priority")
    if any(item not in ordered for item in required_items):
        raise ValueError("required requests must be active")

    def extend(seed_items: Sequence[int]) -> list[int]:
        chosen = list(seed_items)
        remaining = [item for item in ordered if item not in chosen]
        while remaining and len(chosen) < batch_size:
            current_union = frozenset().union(
                *(signatures[item] for item in chosen)
            )
            candidate = min(
                remaining,
                key=lambda item: (
                    len(current_union | signatures[item]) - len(current_union),
                    priority[item],
                ),
            )
            chosen.append(candidate)
            remaining.remove(candidate)
        return chosen

    if required_items:
        return extend(required_items)
    if not ordered:
        return []
    if not any(signatures[item] for item in ordered):
        return sorted(ordered, key=lambda item: priority[item])[:batch_size]

    candidates = [extend([seed]) for seed in ordered]
    return min(
        candidates,
        key=lambda group: (
            len(frozenset().union(*(signatures[item] for item in group))),
            tuple(priority[item] for item in group),
        ),
    )
