#!/usr/bin/env python3
"""Create deterministic IndustrialPublic events from packaging alarm CSV data."""

from __future__ import annotations

import argparse
import csv
import json
import zipfile
from collections import Counter
from pathlib import Path
from typing import Iterator


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "industrial_public"
ARCHIVE = DATA_DIR / "raw" / "packaging_alarms" / "alarms_log_data.zip"
MEMBER = "alarms_log_data/raw/alarms.csv"
DEFAULT_OUTPUT = (
    DATA_DIR
    / "derived"
    / "packaging_alarms"
    / "sample_100_events.jsonl"
)
REVISION = "Research Data Unipd record 1031, metadata revision 2"


def source_rows() -> Iterator[tuple[int, dict[str, str]]]:
    with zipfile.ZipFile(ARCHIVE) as archive:
        with archive.open(MEMBER) as binary:
            import io

            text = io.TextIOWrapper(binary, encoding="utf-8", newline="")
            for row_number, row in enumerate(csv.DictReader(text), start=1):
                yield row_number, row


def normalize(row_number: int, row: dict[str, str]) -> dict:
    serial = row["serial"]
    alarm = row["alarm"]
    timestamp = row["timestamp"]
    return {
        "schema_version": "industrial-event-v0.1",
        "id": f"packaging_alarms:{row_number}",
        "source": {
            "dataset_id": "packaging_alarms",
            "record_id": str(row_number),
            "revision": REVISION,
            "license": "CC-BY-4.0",
            "relative_path": (
                "alarms_log_data.zip::alarms_log_data/raw/alarms.csv"
            ),
            "row_number": row_number,
        },
        "domain": {
            "industry": "industrial_packaging",
            "system": "machine_alarm_logger",
            "process": "packaging_equipment_operation",
            "site": None,
        },
        "modality": "alarm",
        "event_type": "machine_alarm",
        "time": {
            "kind": "instant",
            "start": timestamp,
            "end": timestamp,
            "timezone": None,
            "sample_period_seconds": None,
        },
        "asset": {
            "asset_id": f"machine-{serial}",
            "asset_type": "packaging_machine",
            "parent_asset_id": None,
        },
        "context": {
            "scales": ["event", "asset"],
            "sequence_id": f"packaging-machine-{serial}",
            "previous_event_ids": [],
            "related_event_ids": [],
        },
        "payload": {
            "signals": {},
            "alarm": {"code": alarm},
            "operation": None,
            "maintenance": None,
            "erp": None,
            "bom": None,
            "text": None,
            "raw_fields": dict(row),
        },
        "labels": {
            "state": None,
            "fault": None,
            "attack": None,
            "quality": "upstream_raw",
        },
        "provenance": {
            "adapter": "scripts/adapt_packaging_alarms.py",
            "adapter_version": "v0.1",
            "transforms": [
                "csv_parse",
                "field_mapping_without_semantic_inference",
            ],
            "contains_private_data": False,
        },
        "probe": None,
    }


def select_balanced(per_machine: int) -> tuple[list[dict], dict]:
    selected: list[dict] = []
    counts: Counter[str] = Counter()
    raw_rows = 0
    min_timestamp: str | None = None
    max_timestamp: str | None = None
    alarms: set[str] = set()
    machines: set[str] = set()
    for row_number, row in source_rows():
        raw_rows += 1
        timestamp = row["timestamp"]
        min_timestamp = min(min_timestamp or timestamp, timestamp)
        max_timestamp = max(max_timestamp or timestamp, timestamp)
        alarms.add(row["alarm"])
        machines.add(row["serial"])
        if counts[row["serial"]] < per_machine:
            selected.append(normalize(row_number, row))
            counts[row["serial"]] += 1
    audit = {
        "source_rows": raw_rows,
        "source_machine_count": len(machines),
        "source_alarm_code_count": len(alarms),
        "source_time_min": min_timestamp,
        "source_time_max": max_timestamp,
        "selection": "first_n_events_per_machine_in_source_order",
        "per_machine": per_machine,
        "selected_events": len(selected),
        "selected_by_machine": dict(sorted(counts.items(), key=lambda x: int(x[0]))),
    }
    return selected, audit


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-machine", type=int, default=5)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.per_machine < 1:
        raise SystemExit("--per-machine must be positive")
    events, audit = select_balanced(args.per_machine)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(
            json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
            for event in events
        ),
        encoding="utf-8",
    )
    audit_path = args.output.with_suffix(".audit.json")
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
