from __future__ import annotations

import unittest

from moe_controller.affinity import (
    affinity_partition,
    fcfs_partition,
    partition_cost,
    select_affinity_batch,
)


class AffinityPartitionTests(unittest.TestCase):
    def test_fcfs_chunks_in_order(self) -> None:
        self.assertEqual(fcfs_partition([0, 1, 2, 3, 4], 2), [[0, 1], [2, 3], [4]])

    def test_empty_history_falls_back_to_fcfs(self) -> None:
        items = [0, 1, 2, 3]
        signatures = {item: frozenset() for item in items}
        self.assertEqual(
            affinity_partition(items, signatures, 2),
            [[0, 1], [2, 3]],
        )

    def test_affinity_reduces_predicted_union(self) -> None:
        items = [0, 1, 2, 3]
        signatures = {
            0: frozenset({0, 1}),
            1: frozenset({10, 11}),
            2: frozenset({0, 2}),
            3: frozenset({10, 12}),
        }
        fcfs = fcfs_partition(items, 2)
        affinity = affinity_partition(items, signatures, 2)
        self.assertLess(
            partition_cost(affinity, signatures),
            partition_cost(fcfs, signatures),
        )
        self.assertEqual(
            {frozenset(group) for group in affinity},
            {frozenset({0, 2}), frozenset({1, 3})},
        )

    def test_partition_is_deterministic_and_capacity_bounded(self) -> None:
        items = list(range(9))
        signatures = {
            item: frozenset({item % 3, 10 + item % 2}) for item in items
        }
        first = affinity_partition(items, signatures, 4)
        second = affinity_partition(items, signatures, 4)
        self.assertEqual(first, second)
        self.assertEqual(sorted(value for group in first for value in group), items)
        self.assertTrue(all(len(group) <= 4 for group in first))

    def test_deadline_required_items_are_always_selected(self) -> None:
        items = [0, 1, 2, 3, 4]
        signatures = {
            0: frozenset({0}),
            1: frozenset({10}),
            2: frozenset({10, 11}),
            3: frozenset({0, 1}),
            4: frozenset({20}),
        }
        priority = {item: (item, item) for item in items}
        selected = select_affinity_batch(
            items,
            signatures,
            3,
            required=[0, 1],
            priority=priority,
        )
        self.assertEqual(selected[:2], [0, 1])
        self.assertEqual(len(selected), 3)


if __name__ == "__main__":
    unittest.main()
