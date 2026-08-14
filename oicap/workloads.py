from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WorkloadItem:
    item_id: str
    workload_class: str
    body: dict[str, Any]


def load_jsonl(path: Path) -> list[WorkloadItem]:
    items: list[WorkloadItem] = []
    item_ids: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number}: each row must be an object.")
            try:
                item_id = str(value["id"]).strip()
                workload_class = str(value["workload_class"]).strip()
                body = value["body"]
                if not item_id or not workload_class or not isinstance(body, dict):
                    raise ValueError
                item = WorkloadItem(item_id, workload_class, dict(body))
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(
                    f"{path}:{line_number}: expected id, workload_class and object body."
                ) from exc
            if item.item_id in item_ids:
                raise ValueError(
                    f"{path}:{line_number}: duplicate workload id {item.item_id!r}."
                )
            item_ids.add(item.item_id)
            items.append(item)
    if not items:
        raise ValueError(f"Workload is empty: {path}")
    return items


def deterministic_sequence(
    items: list[WorkloadItem],
    count: int,
    seed: int,
    class_weights: dict[str, float] | None = None,
) -> list[WorkloadItem]:
    rng = random.Random(seed)
    if class_weights is None:
        indices = list(range(len(items)))
        result: list[WorkloadItem] = []
        while len(result) < count:
            rng.shuffle(indices)
            result.extend(items[index] for index in indices)
        return result[:count]

    grouped: dict[str, list[WorkloadItem]] = {}
    for item in items:
        grouped.setdefault(item.workload_class, []).append(item)
    missing = sorted(set(class_weights) - set(grouped))
    if missing:
        raise ValueError(f"Workload source has no rows for declared classes: {missing}")
    class_ids = list(class_weights)
    cumulative: list[float] = []
    total = 0.0
    for class_id in class_ids:
        total += class_weights[class_id]
        cumulative.append(total)
    class_queues: dict[str, list[WorkloadItem]] = {key: [] for key in class_ids}
    class_offsets = {key: 0 for key in class_ids}

    def next_item(class_id: str) -> WorkloadItem:
        queue = class_queues[class_id]
        offset = class_offsets[class_id]
        if offset >= len(queue):
            queue[:] = grouped[class_id]
            rng.shuffle(queue)
            offset = 0
        item = queue[offset]
        class_offsets[class_id] = offset + 1
        return item

    result = []
    for _ in range(count):
        draw = rng.random() * total
        selected = class_ids[-1]
        for class_id, boundary in zip(class_ids, cumulative):
            if draw < boundary:
                selected = class_id
                break
        result.append(next_item(selected))
    return result
