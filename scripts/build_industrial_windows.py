#!/usr/bin/env python3
"""Materialize deterministic HAI and Petrobras 3W multiscale case pools."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pyarrow.compute as pc
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "industrial_public"
RAW_DIR = DATA_DIR / "raw"
DERIVED_DIR = DATA_DIR / "derived"

HAI_ARCHIVE = RAW_DIR / "hai_23_05" / "hai-security-dataset-kaggle-v10.zip"
THREE_W_DIR = RAW_DIR / "petrobras_3w" / "dataset"
THREE_W_EPISODES = (
    DERIVED_DIR / "petrobras_3w" / "sample_100_episodes.jsonl"
)

REVISIONS = {
    "hai_23_05": "kaggle-v10-2023-06-01",
    "petrobras_3w": "a6b588cafdc26265d04f2f289b2142f2682bd6b3",
}
LICENSES = {
    "hai_23_05": "CC-BY-SA-4.0",
    "petrobras_3w": "CC-BY-4.0",
}
SPLIT_THRESHOLDS = (50, 75)
HAI_WINDOW_QUOTAS = {32: 17, 64: 17, 128: 16}
THREE_W_WIDTHS = (32, 32, 32, 32, 128, 128, 128, 512, 512, 512)


def stable_split(group_id: str) -> str:
    value = int.from_bytes(
        hashlib.sha256(group_id.encode("utf-8")).digest()[:8], "big"
    ) % 100
    if value < SPLIT_THRESHOLDS[0]:
        return "discovery"
    if value < SPLIT_THRESHOLDS[1]:
        return "confirmatory"
    return "test"


def balanced_group_splits(
    group_weights: dict[str, Counter[str]],
) -> dict[str, str]:
    """Assign indivisible groups while minimizing normalized target error."""
    splits = ("discovery", "confirmatory", "test")
    fractions = {"discovery": 0.5, "confirmatory": 0.25, "test": 0.25}
    metrics = sorted(
        {metric for weights in group_weights.values() for metric in weights}
    )
    totals = {
        metric: sum(weights[metric] for weights in group_weights.values())
        for metric in metrics
    }
    targets = {
        split: {
            metric: totals[metric] * fractions[split]
            for metric in metrics
        }
        for split in splits
    }
    current = {
        split: Counter({metric: 0 for metric in metrics})
        for split in splits
    }
    ordered = sorted(
        group_weights,
        key=lambda group_id: (
            -sum(group_weights[group_id].values()),
            hashlib.sha256(group_id.encode("utf-8")).hexdigest(),
        ),
    )
    assignments = {}
    for group_id in ordered:
        weights = group_weights[group_id]
        candidates = []
        for split_index, split in enumerate(splits):
            cost = 0.0
            for candidate_split in splits:
                for metric in metrics:
                    value = current[candidate_split][metric]
                    if candidate_split == split:
                        value += weights[metric]
                    cost += abs(value - targets[candidate_split][metric]) / max(
                        totals[metric], 1
                    )
            candidates.append((cost, split_index, split))
        _cost, _index, selected = min(candidates)
        assignments[group_id] = selected
        current[selected].update(weights)
    return assignments


def finite(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def evenly_spaced(items: list[Any], count: int) -> list[Any]:
    if count > len(items):
        raise ValueError(f"requested {count} from {len(items)} candidates")
    if count == len(items):
        return list(items)
    indices = [((2 * index + 1) * len(items)) // (2 * count) for index in range(count)]
    if len(set(indices)) != count:
        raise RuntimeError("evenly_spaced produced duplicate indices")
    return [items[index] for index in indices]


def source(dataset_id: str, paths: Iterable[str]) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id,
        "revision": REVISIONS[dataset_id],
        "license": LICENSES[dataset_id],
        "relative_paths": sorted(set(paths)),
    }


def provenance(transforms: list[str]) -> dict[str, Any]:
    return {
        "builder": "build_industrial_windows.py",
        "builder_version": "v0.1",
        "transforms": transforms,
        "contains_private_data": False,
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def write_audit(path: Path, audit: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


@dataclass(frozen=True)
class HaiRun:
    test: str
    start: int
    end: int
    label: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1

    @property
    def group_id(self) -> str:
        return f"hai_23_05:{self.test}:run:{self.start}-{self.end}"


@dataclass
class HaiInterval:
    scale: str
    unit: str
    test: str
    start: int
    end: int
    label: int
    run: HaiRun
    width: int | None
    timestamps: list[str] = field(default_factory=list)
    source_record_ids: list[str] = field(default_factory=list)
    stats: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def id(self) -> str:
        return (
            f"hai_23_05:{self.scale}:{self.test}:"
            f"{self.start}-{self.end}"
        )


def read_hai_runs(archive: zipfile.ZipFile, test: str) -> list[HaiRun]:
    member = f"hai-23.05/label-{test}.csv"
    runs: list[HaiRun] = []
    with archive.open(member) as raw:
        reader = csv.DictReader(
            io.TextIOWrapper(raw, encoding="utf-8", newline="")
        )
        previous = None
        start = 1
        last_row = 0
        for row_number, row in enumerate(reader, start=1):
            label = int(row["label"])
            if previous is None:
                previous = label
            elif label != previous:
                runs.append(HaiRun(test, start, row_number - 1, previous))
                start = row_number
                previous = label
            last_row = row_number
        if previous is not None:
            runs.append(HaiRun(test, start, last_row, previous))
    return runs


def selected_hai_runs(all_runs: list[HaiRun]) -> list[HaiRun]:
    normal = [run for run in all_runs if run.label == 0]
    attack = [run for run in all_runs if run.label != 0]
    return sorted(
        evenly_spaced(normal, 50) + evenly_spaced(attack, 50),
        key=lambda run: (run.test, run.start),
    )


def hai_windows(runs: list[HaiRun]) -> list[HaiInterval]:
    selected: list[HaiInterval] = []
    for label in (0, 1):
        state_runs = [run for run in runs if (run.label != 0) == bool(label)]
        for width, quota in HAI_WINDOW_QUOTAS.items():
            candidates = []
            for run in state_runs:
                for start in range(run.start, run.end - width + 2, width):
                    candidates.append((run, start))
            for run, start in evenly_spaced(candidates, quota):
                selected.append(
                    HaiInterval(
                        scale="S1",
                        unit="local_window",
                        test=run.test,
                        start=start,
                        end=start + width - 1,
                        label=run.label,
                        run=run,
                        width=width,
                    )
                )
    return sorted(selected, key=lambda row: (row.test, row.start, row.end))


def initialize_stats(names: list[str]) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "count": 0,
            "null_count": 0,
            "min": None,
            "max": None,
            "sum": 0.0,
            "first": None,
            "last": None,
        }
        for name in names
    }


def update_stats(stats: dict[str, dict[str, Any]], row: dict[str, str]) -> None:
    for name, state in stats.items():
        raw = row.get(name)
        try:
            value = float(raw) if raw not in (None, "") else None
        except ValueError:
            value = None
        if value is None or not math.isfinite(value):
            state["null_count"] += 1
            continue
        if state["count"] == 0:
            state["first"] = value
            state["min"] = value
            state["max"] = value
        state["last"] = value
        state["min"] = min(state["min"], value)
        state["max"] = max(state["max"], value)
        state["sum"] += value
        state["count"] += 1


def hai_timestamps_align(data_timestamp: str, label_timestamp: str) -> bool:
    if data_timestamp == label_timestamp:
        return True
    data_time = datetime.strptime(data_timestamp, "%Y-%m-%d %H:%M:%S")
    label_time = datetime.strptime(label_timestamp, "%Y-%m-%d %H:%M")
    return data_time.replace(second=0) == label_time


def finalize_stats(stats: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    output = {}
    for name, state in stats.items():
        count = state["count"]
        output[name] = {
            "count": count,
            "null_count": state["null_count"],
            "min": state["min"],
            "max": state["max"],
            "mean": finite(state["sum"] / count) if count else None,
            "first": state["first"],
            "last": state["last"],
        }
    return output


def collect_hai(
    archive: zipfile.ZipFile, intervals: list[HaiInterval]
) -> None:
    by_test: dict[str, list[HaiInterval]] = defaultdict(list)
    for interval in intervals:
        by_test[interval.test].append(interval)
    for test, cases in sorted(by_test.items()):
        starts: dict[int, list[HaiInterval]] = defaultdict(list)
        for case in cases:
            starts[case.start].append(case)
        data_member = f"hai-23.05/hai-{test}.csv"
        label_member = f"hai-23.05/label-{test}.csv"
        with archive.open(data_member) as data_raw, archive.open(
            label_member
        ) as label_raw:
            data_reader = csv.DictReader(
                io.TextIOWrapper(data_raw, encoding="utf-8", newline="")
            )
            label_reader = csv.DictReader(
                io.TextIOWrapper(label_raw, encoding="utf-8", newline="")
            )
            signal_names = [
                name for name in (data_reader.fieldnames or [])
                if name != "timestamp"
            ]
            active: list[HaiInterval] = []
            for row_number, (data, label) in enumerate(
                zip(data_reader, label_reader, strict=True), start=1
            ):
                if not hai_timestamps_align(
                    data["timestamp"], label["timestamp"]
                ):
                    raise RuntimeError(
                        f"HAI timestamp mismatch in {test} row {row_number}"
                    )
                active.extend(starts.get(row_number, []))
                for case in active:
                    if not case.stats:
                        case.stats = initialize_stats(signal_names)
                    if int(label["label"]) != case.label:
                        raise RuntimeError(
                            f"HAI label boundary crossed by {case.id}"
                        )
                    update_stats(case.stats, data)
                    case.timestamps.append(data["timestamp"])
                    case.source_record_ids.append(
                        f"{test}:row:{row_number}"
                    )
                active = [case for case in active if case.end > row_number]


def hai_case(
    case: HaiInterval, split_by_group: dict[str, str]
) -> dict[str, Any]:
    data_member = f"hai-23.05/hai-{case.test}.csv"
    label_member = f"hai-23.05/label-{case.test}.csv"
    expected = case.end - case.start + 1
    if len(case.source_record_ids) != expected:
        raise RuntimeError(f"incomplete HAI interval {case.id}")
    return {
        "case_schema_version": "industrial-case-v0.1",
        "id": case.id,
        "base_case_id": case.run.group_id,
        "group_id": case.run.group_id,
        "split": split_by_group[case.run.group_id],
        "source": source(
            "hai_23_05",
            [
                f"hai-security-dataset-kaggle-v10.zip::{data_member}",
                f"hai-security-dataset-kaggle-v10.zip::{label_member}",
            ],
        ),
        "semantic_scale": case.scale,
        "semantic_unit": case.unit,
        "construction": {
            "rule": (
                "contiguous_fixed_point_window"
                if case.scale == "S1"
                else "upstream_label_transition_bounded_interval"
            ),
            "parameters": {
                "test": case.test,
                "start_row": case.start,
                "end_row": case.end,
                "width": case.width,
                "sample_period_seconds": 1,
            },
            "temporal_access": "retrospective",
        },
        "source_record_ids": case.source_record_ids,
        "source_record_count": expected,
        "time": {
            "start": case.timestamps[0],
            "end": case.timestamps[-1],
            "sample_period_seconds": 1,
        },
        "payload": {
            "signal_summary": finalize_stats(case.stats),
            "signal_count": len(case.stats),
        },
        "labels": {
            "state": "attack" if case.label else "normal",
            "attack": bool(case.label),
            "fault": case.label,
            "quality": "upstream_test_label",
        },
        "provenance": provenance(
            [
                "zip_member_stream",
                (
                    "timestamp_exact_join"
                    if case.test == "test1"
                    else "row_exact_join_and_timestamp_minute_alignment"
                ),
                "contiguous_source_rows",
                "per_signal_count_min_max_mean_first_last",
                "no_interpolation",
            ]
        ),
    }


def build_hai() -> dict[str, Any]:
    with zipfile.ZipFile(HAI_ARCHIVE) as archive:
        runs = [
            run
            for test in ("test1", "test2")
            for run in read_hai_runs(archive, test)
        ]
        episode_runs = selected_hai_runs(runs)
        s1_intervals = hai_windows(episode_runs)
        s2_intervals = [
            HaiInterval(
                scale="S2",
                unit="episode",
                test=run.test,
                start=run.start,
                end=run.end,
                label=run.label,
                run=run,
                width=None,
            )
            for run in episode_runs
        ]
        collect_hai(archive, s1_intervals + s2_intervals)
    group_weights: dict[str, Counter[str]] = defaultdict(Counter)
    for case in s1_intervals + s2_intervals:
        state = "attack" if case.label else "normal"
        group_weights[case.run.group_id][case.scale] += 1
        group_weights[case.run.group_id][f"{case.scale}:{state}"] += 1
    split_by_group = balanced_group_splits(group_weights)
    s1_rows = [hai_case(case, split_by_group) for case in s1_intervals]
    s2_rows = [hai_case(case, split_by_group) for case in s2_intervals]
    directory = DERIVED_DIR / "hai_23_05"
    s1_path = directory / "cases_s1_100_windows.jsonl"
    s2_path = directory / "cases_s2_100_episodes.jsonl"
    write_jsonl(s1_path, s1_rows)
    write_jsonl(s2_path, s2_rows)
    audit = {
        "source_id": "hai_23_05",
        "available_label_runs": len(runs),
        "available_by_state": dict(
            Counter("attack" if run.label else "normal" for run in runs)
        ),
        "s1_cases": len(s1_rows),
        "s1_by_state": dict(Counter(row["labels"]["state"] for row in s1_rows)),
        "s1_by_width": dict(
            sorted(
                Counter(
                    str(row["construction"]["parameters"]["width"])
                    for row in s1_rows
                ).items()
            )
        ),
        "s2_cases": len(s2_rows),
        "s2_by_state": dict(Counter(row["labels"]["state"] for row in s2_rows)),
        "split_case_counts": {
            "S1": dict(Counter(row["split"] for row in s1_rows)),
            "S2": dict(Counter(row["split"] for row in s2_rows)),
        },
        "outputs": [
            str(s1_path.relative_to(ROOT)),
            str(s2_path.relative_to(ROOT)),
        ],
    }
    write_audit(directory / "multiscale_cases.audit.json", audit)
    return audit


def arrow_stats(table: Any) -> dict[str, dict[str, Any]]:
    summaries = {}
    for name in table.column_names:
        if name in {"timestamp", "class", "state"}:
            continue
        column = table[name]
        count = int(pc.count(column).as_py())
        first = None
        last = None
        if count:
            valid = pc.drop_null(column)
            first = finite(valid[0].as_py())
            last = finite(valid[len(valid) - 1].as_py())
        summaries[name] = {
            "count": count,
            "null_count": table.num_rows - count,
            "min": finite(pc.min(column).as_py()) if count else None,
            "max": finite(pc.max(column).as_py()) if count else None,
            "mean": finite(pc.mean(column).as_py()) if count else None,
            "first": first,
            "last": last,
        }
    return summaries


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class UnionFind:
    def __init__(self, values: Iterable[str]):
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[max(left_root, right_root)] = min(left_root, right_root)


def three_w_groups(
    episodes: list[dict[str, Any]],
) -> tuple[dict[str, str], list[tuple[dict[str, Any], dict[str, Any]]]]:
    by_class: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for episode in episodes:
        by_class[int(episode["labels"]["fault"])].append(episode)
    pairs = []
    union = UnionFind(episode["id"] for episode in episodes)
    for class_id in range(10):
        selected = sorted(by_class[class_id], key=lambda row: row["id"])
        for index in range(0, 10, 2):
            left, right = selected[index : index + 2]
            pairs.append((left, right))
            union.union(left["id"], right["id"])
    real_by_well: dict[str, list[str]] = defaultdict(list)
    for episode in episodes:
        if episode["labels"]["quality"] == "real":
            real_by_well[episode["asset"]["asset_id"]].append(episode["id"])
    for ids in real_by_well.values():
        for episode_id in ids[1:]:
            union.union(ids[0], episode_id)
    components: dict[str, list[str]] = defaultdict(list)
    for episode in episodes:
        components[union.find(episode["id"])].append(episode["id"])
    group_by_episode = {}
    for members in components.values():
        group_id = "petrobras_3w:component:" + hashlib.sha256(
            "\n".join(sorted(members)).encode("utf-8")
        ).hexdigest()[:16]
        for member in members:
            group_by_episode[member] = group_id
    return group_by_episode, pairs


def three_w_relative_path(episode: dict[str, Any]) -> Path:
    return RAW_DIR / "petrobras_3w" / episode["source"]["relative_path"]


def three_w_case_common(
    episode: dict[str, Any],
    group_id: str,
    split_by_group: dict[str, str],
    scale: str,
    unit: str,
) -> dict[str, Any]:
    return {
        "case_schema_version": "industrial-case-v0.1",
        "base_case_id": episode["id"],
        "group_id": group_id,
        "split": split_by_group[group_id],
        "source": source(
            "petrobras_3w", [episode["source"]["relative_path"]]
        ),
        "semantic_scale": scale,
        "semantic_unit": unit,
        "labels": dict(episode["labels"]),
        "provenance": provenance(
            [
                "parquet_read",
                "contiguous_source_rows",
                "no_interpolation",
            ]
        ),
    }


def build_three_w() -> dict[str, Any]:
    episodes = read_jsonl(THREE_W_EPISODES)
    episodes.sort(
        key=lambda row: (int(row["labels"]["fault"]), row["id"])
    )
    group_by_episode, pairs = three_w_groups(episodes)
    group_weights: dict[str, Counter[str]] = defaultdict(Counter)
    for episode in episodes:
        group_id = group_by_episode[episode["id"]]
        group_weights[group_id]["S0"] += 1
        group_weights[group_id]["S1"] += 1
    for left, _right in pairs:
        group_id = group_by_episode[left["id"]]
        group_weights[group_id]["S3"] += 1
    split_by_group = balanced_group_splits(group_weights)
    class_index = Counter()
    s0_rows = []
    s1_rows = []
    for episode in episodes:
        class_id = int(episode["labels"]["fault"])
        width = THREE_W_WIDTHS[class_index[class_id]]
        class_index[class_id] += 1
        path = three_w_relative_path(episode)
        table = pq.read_table(path)
        middle = table.num_rows // 2
        start = middle - width // 2
        point = table.slice(middle, 1)
        window = table.slice(start, width)
        relative = episode["source"]["relative_path"]
        group_id = group_by_episode[episode["id"]]
        point_case = three_w_case_common(
            episode, group_id, split_by_group, "S0", "point"
        )
        point_case.update(
            {
                "id": f"{episode['id']}:S0:row:{middle + 1}",
                "construction": {
                    "rule": "deterministic_middle_timestamp",
                    "parameters": {"row_number": middle + 1},
                    "temporal_access": "retrospective",
                },
                "source_record_ids": [
                    f"{relative}:row:{middle + 1}"
                ],
                "source_record_count": 1,
                "time": {
                    "start": point["timestamp"][0].as_py().isoformat(),
                    "end": point["timestamp"][0].as_py().isoformat(),
                },
                "payload": {
                    "signals": {
                        name: finite(point[name][0].as_py())
                        for name in point.column_names
                        if name not in {"timestamp", "class", "state"}
                    }
                },
            }
        )
        window_case = three_w_case_common(
            episode, group_id, split_by_group, "S1", "local_window"
        )
        window_case.update(
            {
                "id": (
                    f"{episode['id']}:S1:rows:"
                    f"{start + 1}-{start + width}"
                ),
                "construction": {
                    "rule": "deterministic_centered_fixed_point_window",
                    "parameters": {
                        "start_row": start + 1,
                        "end_row": start + width,
                        "width": width,
                    },
                    "temporal_access": "retrospective",
                },
                "source_record_ids": [
                    f"{relative}:row:{row_number}"
                    for row_number in range(start + 1, start + width + 1)
                ],
                "source_record_count": width,
                "time": {
                    "start": window["timestamp"][0].as_py().isoformat(),
                    "end": window["timestamp"][width - 1].as_py().isoformat(),
                },
                "payload": {
                    "signal_summary": arrow_stats(window),
                    "signal_count": len(window.column_names) - 3,
                },
            }
        )
        s0_rows.append(point_case)
        s1_rows.append(window_case)
    s3_rows = []
    for pair_index, (left, right) in enumerate(pairs, start=1):
        group_id = group_by_episode[left["id"]]
        if group_id != group_by_episode[right["id"]]:
            raise RuntimeError("3W comparison pair crossed split component")
        left_means = left["payload"]["signals"]
        right_means = right["payload"]["signals"]
        names = sorted(set(left_means) & set(right_means))
        comparisons = {}
        for name in names:
            left_value = left_means[name]
            right_value = right_means[name]
            comparisons[name] = {
                "left_mean": left_value,
                "right_mean": right_value,
                "delta_right_minus_left": (
                    right_value - left_value
                    if isinstance(left_value, (int, float))
                    and isinstance(right_value, (int, float))
                    else None
                ),
            }
        class_id = int(left["labels"]["fault"])
        relative_paths = [
            left["source"]["relative_path"],
            right["source"]["relative_path"],
        ]
        s3_rows.append(
            {
                "case_schema_version": "industrial-case-v0.1",
                "id": f"petrobras_3w:S3:class:{class_id}:pair:{pair_index}",
                "base_case_id": f"petrobras_3w:class:{class_id}:pair:{pair_index}",
                "group_id": group_id,
                "split": split_by_group[group_id],
                "source": source("petrobras_3w", relative_paths),
                "semantic_scale": "S3",
                "semantic_unit": "process_field",
                "construction": {
                    "rule": "same_upstream_class_paired_episode_comparison",
                    "parameters": {
                        "class_id": class_id,
                        "member_episode_ids": [left["id"], right["id"]],
                        "source_types": [
                            left["labels"]["quality"],
                            right["labels"]["quality"],
                        ],
                    },
                    "temporal_access": "retrospective",
                },
                "source_record_ids": [left["id"], right["id"]],
                "source_record_count": 2,
                "time": {
                    "start": min(left["time"]["start"], right["time"]["start"]),
                    "end": max(left["time"]["end"], right["time"]["end"]),
                },
                "payload": {
                    "members": [
                        {
                            "id": row["id"],
                            "asset_id": row["asset"]["asset_id"],
                            "source_type": row["labels"]["quality"],
                            "row_count": row["payload"]["raw_fields"]["row_count"],
                        }
                        for row in (left, right)
                    ],
                    "signal_mean_comparison": comparisons,
                },
                "labels": {
                    "state": left["labels"]["state"],
                    "fault": class_id,
                    "attack": None,
                    "quality": "paired_same_upstream_class",
                },
                "provenance": provenance(
                    [
                        "normalized_episode_summary_read",
                        "same_class_deterministic_pair",
                        "common_signal_mean_delta",
                        "real_well_connected_component_split_guard",
                    ]
                ),
            }
        )
    directory = DERIVED_DIR / "petrobras_3w"
    outputs = {
        "S0": directory / "cases_s0_100_points.jsonl",
        "S1": directory / "cases_s1_100_windows.jsonl",
        "S3": directory / "cases_s3_50_comparisons.jsonl",
    }
    for scale, rows in (("S0", s0_rows), ("S1", s1_rows), ("S3", s3_rows)):
        write_jsonl(outputs[scale], rows)
    audit = {
        "source_id": "petrobras_3w",
        "s0_cases": len(s0_rows),
        "s1_cases": len(s1_rows),
        "s1_by_class": dict(
            sorted(
                Counter(str(row["labels"]["fault"]) for row in s1_rows).items()
            )
        ),
        "s1_by_width": dict(
            sorted(
                Counter(
                    str(row["construction"]["parameters"]["width"])
                    for row in s1_rows
                ).items()
            )
        ),
        "s3_cases": len(s3_rows),
        "s3_by_class": dict(
            sorted(
                Counter(str(row["labels"]["fault"]) for row in s3_rows).items()
            )
        ),
        "connected_split_groups": len(set(group_by_episode.values())),
        "split_case_counts": {
            "S0": dict(Counter(row["split"] for row in s0_rows)),
            "S1": dict(Counter(row["split"] for row in s1_rows)),
            "S3": dict(Counter(row["split"] for row in s3_rows)),
        },
        "outputs": [
            str(path.relative_to(ROOT)) for path in outputs.values()
        ],
    }
    write_audit(directory / "multiscale_cases.audit.json", audit)
    return audit


def main() -> int:
    summary = {
        "hai_23_05": build_hai(),
        "petrobras_3w": build_three_w(),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
