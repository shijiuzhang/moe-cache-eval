#!/usr/bin/env python3
"""Build small, provenance-complete samples from four industrial sources.

This is an adapter validation stage, not an LLM prompt generator. Every
transformation is mechanical and recorded in ``provenance.transforms``.
Source-specific industrial meanings are copied only from upstream labels or
configuration files.
"""

from __future__ import annotations

import argparse
import configparser
import csv
import io
import json
import math
import re
import zipfile
from collections import Counter, defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
import xml.etree.ElementTree as ET

import pyarrow.compute as pc
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "industrial_public"
RAW_DIR = DATA_DIR / "raw"
DERIVED_DIR = DATA_DIR / "derived"

HAI_ARCHIVE = RAW_DIR / "hai_23_05" / "hai-security-dataset-kaggle-v10.zip"
PRONTO_ARCHIVE = RAW_DIR / "pronto" / "PRONTO benchmark case study.zip"
THREE_W_DIR = RAW_DIR / "petrobras_3w" / "dataset"
OFBIZ_DEMO_DIR = (
    RAW_DIR
    / "ofbiz_manufacturing"
    / "applications"
    / "datamodel"
    / "data"
    / "demo"
)

REVISIONS = {
    "hai_23_05": "kaggle-v10-2023-06-01",
    "pronto": "Zenodo record 1341583 revision 7",
    "petrobras_3w": "a6b588cafdc26265d04f2f289b2142f2682bd6b3",
    "ofbiz_manufacturing": "e23e7d7262a226873132db13b41860d6403d48d3",
}

LICENSES = {
    "hai_23_05": "CC-BY-SA-4.0",
    "pronto": "CC-BY-4.0",
    "petrobras_3w": "CC-BY-4.0",
    "ofbiz_manufacturing": "Apache-2.0",
}


def parse_scalar(value: str | None) -> Any:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if re.fullmatch(r"[-+]?\d+", text):
        return int(text)
    try:
        number = float(text)
    except ValueError:
        return text
    return number if math.isfinite(number) else None


def finite_or_none(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def source_ref(
    dataset_id: str,
    record_id: str,
    relative_path: str,
    *,
    row_number: int | None = None,
) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id,
        "record_id": record_id,
        "revision": REVISIONS[dataset_id],
        "license": LICENSES[dataset_id],
        "relative_path": relative_path,
        "row_number": row_number,
    }


def provenance(adapter: str, transforms: list[str]) -> dict[str, Any]:
    return {
        "adapter": adapter,
        "adapter_version": "v0.1",
        "transforms": transforms,
        "contains_private_data": False,
    }


def write_artifact(
    source_id: str,
    filename: str,
    rows: list[dict[str, Any]],
    audit: dict[str, Any],
) -> tuple[Path, Path]:
    directory = DERIVED_DIR / source_id
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / filename
    output.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    audit_path = output.with_suffix(".audit.json")
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output, audit_path


def build_hai() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    data_member = "hai-23.05/hai-test1.csv"
    label_member = "hai-23.05/label-test1.csv"
    selected: list[dict[str, Any]] = []
    by_attack = Counter()
    scanned = 0
    with zipfile.ZipFile(HAI_ARCHIVE) as archive:
        with archive.open(data_member) as data_binary, archive.open(
            label_member
        ) as label_binary:
            data_text = io.TextIOWrapper(data_binary, encoding="utf-8", newline="")
            label_text = io.TextIOWrapper(
                label_binary, encoding="utf-8", newline=""
            )
            data_rows = csv.DictReader(data_text)
            label_rows = csv.DictReader(label_text)
            for row_number, (data, label) in enumerate(
                zip(data_rows, label_rows, strict=True), start=1
            ):
                scanned += 1
                if data["timestamp"] != label["timestamp"]:
                    raise RuntimeError(
                        f"HAI timestamp mismatch at row {row_number}"
                    )
                label_value = int(label["label"])
                attack = label_value != 0
                bucket = "attack" if attack else "normal"
                if by_attack[bucket] >= 50:
                    if by_attack["normal"] >= 50 and by_attack["attack"] >= 50:
                        break
                    continue
                signals = {
                    key: parse_scalar(value)
                    for key, value in data.items()
                    if key != "timestamp"
                }
                timestamp = data["timestamp"]
                selected.append(
                    {
                        "schema_version": "industrial-event-v0.1",
                        "id": f"hai_23_05:test1:{row_number}",
                        "source": source_ref(
                            "hai_23_05",
                            f"test1:{row_number}",
                            (
                                "hai-security-dataset-kaggle-v10.zip::"
                                f"{data_member}+{label_member}"
                            ),
                            row_number=row_number,
                        ),
                        "domain": {
                            "industry": "industrial_control_system_testbed",
                            "system": "heterogeneous_dcs_plc_hil",
                            "process": (
                                "boiler_turbine_water_treatment_and_hil"
                            ),
                            "site": "HAI testbed",
                        },
                        "modality": "time_series",
                        "event_type": "ics_observation",
                        "time": {
                            "kind": "instant",
                            "start": timestamp,
                            "end": timestamp,
                            "timezone": None,
                            "sample_period_seconds": 1,
                        },
                        "asset": {
                            "asset_id": "HAI-integrated-testbed",
                            "asset_type": "industrial_control_testbed",
                            "parent_asset_id": None,
                        },
                        "context": {
                            "scales": ["event", "process", "plant"],
                            "sequence_id": "hai-23.05-test1",
                            "previous_event_ids": [],
                            "related_event_ids": [],
                        },
                        "payload": {
                            "signals": signals,
                            "alarm": None,
                            "operation": None,
                            "maintenance": None,
                            "erp": None,
                            "bom": None,
                            "text": None,
                            "raw_fields": {"label": label_value},
                        },
                        "labels": {
                            "state": bucket,
                            "fault": label_value,
                            "attack": attack,
                            "quality": "upstream_test_label",
                        },
                        "provenance": provenance(
                            "build_industrial_samples.py:hai",
                            [
                                "zip_member_stream",
                                "timestamp_exact_join",
                                "numeric_scalar_parse",
                                "balanced_first_50_normal_and_attack",
                            ],
                        ),
                        "probe": None,
                    }
                )
                by_attack[bucket] += 1
    selected.sort(key=lambda row: row["source"]["row_number"])
    audit = {
        "source_id": "hai_23_05",
        "source_members": [data_member, label_member],
        "rows_scanned": scanned,
        "selected_events": len(selected),
        "selection": dict(by_attack),
        "signal_count": (
            len(selected[0]["payload"]["signals"]) if selected else 0
        ),
        "all_timestamps_joined_exactly": True,
    }
    return selected, audit


def arrow_stat(column: Any, operation: str) -> Any:
    function = getattr(pc, operation)
    scalar = function(column)
    return finite_or_none(scalar.as_py())


def arrow_value_counts(column: Any) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in pc.value_counts(pc.drop_null(column)).to_pylist():
        result[str(row["values"])] = int(row["counts"])
    return dict(sorted(result.items()))


def three_w_source_type(stem: str) -> str:
    if stem.startswith("WELL-"):
        return "real"
    if stem.startswith("DRAWN_"):
        return "drawn"
    if stem.startswith("SIMULATED_"):
        return "simulated"
    return "unknown"


def three_w_asset_id(stem: str) -> str:
    match = re.match(r"^(WELL-\d+)", stem)
    return match.group(1) if match else f"instance:{stem}"


def build_three_w() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config = configparser.ConfigParser()
    config.read(THREE_W_DIR / "dataset.ini", encoding="utf-8")
    event_descriptions = {}
    for raw_name in config["EVENTS"]["NAMES"].replace("\n", "").split(","):
        name = raw_name.strip()
        if name:
            event_descriptions[int(config[name]["LABEL"])] = config[name][
                "DESCRIPTION"
            ]
    rows: list[dict[str, Any]] = []
    class_counts: dict[str, int] = {}
    source_types = Counter()
    for class_id in range(10):
        files = sorted((THREE_W_DIR / str(class_id)).glob("*.parquet"))[:10]
        class_counts[str(class_id)] = len(files)
        for path in files:
            table = pq.read_table(path)
            timestamps = table["timestamp"]
            start = arrow_stat(timestamps, "min")
            end = arrow_stat(timestamps, "max")
            timestamp_values = timestamps.slice(0, 2).to_pylist()
            sample_period = None
            if len(timestamp_values) == 2:
                sample_period = (
                    timestamp_values[1] - timestamp_values[0]
                ).total_seconds()
            summary: dict[str, Any] = {}
            means: dict[str, Any] = {}
            for name in table.column_names:
                if name in {"timestamp", "class", "state"}:
                    continue
                column = table[name]
                count = int(pc.count(column).as_py())
                values = {
                    "count": count,
                    "null_count": table.num_rows - count,
                    "min": None,
                    "max": None,
                    "mean": None,
                }
                if count:
                    values.update(
                        {
                            "min": arrow_stat(column, "min"),
                            "max": arrow_stat(column, "max"),
                            "mean": arrow_stat(column, "mean"),
                        }
                    )
                    means[f"{name}.mean"] = values["mean"]
                summary[name] = values
            source_type = three_w_source_type(path.stem)
            source_types[source_type] += 1
            relative = path.relative_to(
                RAW_DIR / "petrobras_3w"
            ).as_posix()
            rows.append(
                {
                    "schema_version": "industrial-event-v0.1",
                    "id": f"petrobras_3w:{class_id}:{path.stem}",
                    "source": source_ref(
                        "petrobras_3w",
                        f"{class_id}/{path.name}",
                        relative,
                    ),
                    "domain": {
                        "industry": "offshore_oil_and_gas",
                        "system": "oil_well_historian",
                        "process": "oil_well_operation",
                        "site": None,
                    },
                    "modality": "time_series",
                    "event_type": "oil_well_episode",
                    "time": {
                        "kind": "interval",
                        "start": start.isoformat() if start else None,
                        "end": end.isoformat() if end else None,
                        "timezone": None,
                        "sample_period_seconds": sample_period,
                    },
                    "asset": {
                        "asset_id": three_w_asset_id(path.stem),
                        "asset_type": (
                            "oil_well"
                            if source_type == "real"
                            else "synthetic_or_drawn_instance"
                        ),
                        "parent_asset_id": None,
                    },
                    "context": {
                        "scales": ["episode", "asset", "process"],
                        "sequence_id": path.stem,
                        "previous_event_ids": [],
                        "related_event_ids": [],
                    },
                    "payload": {
                        "signals": means,
                        "alarm": None,
                        "operation": None,
                        "maintenance": None,
                        "erp": None,
                        "bom": None,
                        "text": None,
                        "raw_fields": {
                            "row_count": table.num_rows,
                            "source_type": source_type,
                            "signal_summary": summary,
                            "class_value_counts": arrow_value_counts(
                                table["class"]
                            ),
                            "state_value_counts": arrow_value_counts(
                                table["state"]
                            ),
                        },
                    },
                    "labels": {
                        "state": event_descriptions[class_id],
                        "fault": class_id,
                        "attack": None,
                        "quality": source_type,
                    },
                    "provenance": provenance(
                        "build_industrial_samples.py:petrobras_3w",
                        [
                            "parquet_read",
                            "per_file_episode",
                            "per_signal_count_min_max_mean",
                            "upstream_class_directory_label",
                        ],
                    ),
                    "probe": None,
                }
            )
    audit = {
        "source_id": "petrobras_3w",
        "dataset_version": config["VERSION"]["DATASET"],
        "selection": "lexicographically_first_10_files_per_class",
        "selected_by_class": class_counts,
        "selected_by_source_type": dict(sorted(source_types.items())),
        "selected_episodes": len(rows),
        "event_descriptions": event_descriptions,
    }
    return rows, audit


def pronto_test_key(member: str) -> tuple[str, str]:
    parts = member.split("/")
    return parts[1], parts[2]


def pronto_alarm_members(names: Iterable[str]) -> dict[str, list[str]]:
    candidates: dict[tuple[str, str], list[str]] = defaultdict(list)
    for name in names:
        if not name.lower().endswith(".txt"):
            continue
        if "Alarm" not in name and "Alarms" not in name:
            continue
        condition, test = pronto_test_key(name)
        candidates[(condition, test)].append(name)
    selected: dict[str, list[str]] = defaultdict(list)
    for (condition, _test), values in sorted(candidates.items()):
        preferred = [
            value
            for value in values
            if re.search(r"Alm_?Evt", value, flags=re.IGNORECASE)
        ]
        selected[condition].append(sorted(preferred or values)[0])
    return selected


def read_pronto_alarm_rows(
    archive: zipfile.ZipFile, member: str
) -> list[tuple[int, dict[str, str | None]]]:
    lines = archive.read(member).decode(
        "utf-8-sig", errors="replace"
    ).splitlines()
    reader = csv.reader(lines, delimiter="\t")
    raw_headers = next(reader)
    headers = [
        (header.strip().rstrip("*") or "_row_id")
        for header in raw_headers
    ]
    output = []
    for row_number, values in enumerate(reader, start=1):
        if not values or not any(value.strip() for value in values):
            continue
        padded = values + [""] * max(0, len(headers) - len(values))
        record = {
            key: (value.strip() or None)
            for key, value in zip(headers, padded)
        }
        output.append((row_number, record))
    return output


def pronto_condition_code(condition: str) -> int:
    match = re.match(r"C(\d+)", condition)
    if not match:
        raise ValueError(f"unknown PRONTO condition: {condition}")
    return int(match.group(1))


def build_pronto() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    selected_by_condition = Counter()
    selected_by_test = Counter()
    with zipfile.ZipFile(PRONTO_ARCHIVE) as archive:
        members = pronto_alarm_members(archive.namelist())
        for condition in sorted(members):
            queues: list[deque[tuple[str, int, dict[str, Any]]]] = []
            for member in members[condition]:
                queues.append(
                    deque(
                        (member, row_number, record)
                        for row_number, record in read_pronto_alarm_rows(
                            archive, member
                        )
                    )
                )
            queue_index = 0
            while selected_by_condition[condition] < 25:
                if not any(queues):
                    raise RuntimeError(
                        f"insufficient PRONTO rows for {condition}"
                    )
                queue = queues[queue_index % len(queues)]
                queue_index += 1
                if not queue:
                    continue
                member, row_number, record = queue.popleft()
                _condition, test = pronto_test_key(member)
                event_type = (record.get("Event Type") or "unknown").lower()
                timestamp = record.get("Date/Time")
                module = record.get("Module")
                node = record.get("Node")
                sequence_id = f"{condition}:{test}"
                row_id = record.get("_row_id") or str(row_number)
                relative = (
                    "PRONTO benchmark case study.zip::" + member
                )
                rows.append(
                    {
                        "schema_version": "industrial-event-v0.1",
                        "id": (
                            f"pronto:{condition}:{test}:"
                            f"{Path(member).stem}:{row_id}"
                        ),
                        "source": source_ref(
                            "pronto",
                            f"{member}:{row_number}",
                            relative,
                            row_number=row_number,
                        ),
                        "domain": {
                            "industry": "multiphase_flow_research_facility",
                            "system": "process_alarm_and_event_log",
                            "process": condition,
                            "site": "PRONTO multiphase flow facility",
                        },
                        "modality": "event_log",
                        "event_type": f"pronto_{event_type}",
                        "time": {
                            "kind": "instant",
                            "start": timestamp,
                            "end": timestamp,
                            "timezone": None,
                            "sample_period_seconds": None,
                        },
                        "asset": {
                            "asset_id": module or node,
                            "asset_type": "process_module_or_node",
                            "parent_asset_id": node,
                        },
                        "context": {
                            "scales": ["event", "process", "plant"],
                            "sequence_id": sequence_id,
                            "previous_event_ids": [],
                            "related_event_ids": [],
                        },
                        "payload": {
                            "signals": {},
                            "alarm": {
                                "event_type": record.get("Event Type"),
                                "category": record.get("Category"),
                                "area": record.get("Area"),
                                "module": module,
                                "module_description": record.get(
                                    "Module Description"
                                ),
                                "parameter": record.get("Parameter"),
                                "state": record.get("State"),
                                "level": record.get("Level"),
                                "description_1": record.get("Desc1"),
                                "description_2": record.get("Desc2"),
                            },
                            "operation": (
                                record
                                if event_type == "change"
                                else None
                            ),
                            "maintenance": None,
                            "erp": None,
                            "bom": None,
                            "text": None,
                            "raw_fields": record,
                        },
                        "labels": {
                            "state": condition,
                            "fault": pronto_condition_code(condition),
                            "attack": None,
                            "quality": record.get("Level"),
                        },
                        "provenance": provenance(
                            "build_industrial_samples.py:pronto",
                            [
                                "zip_member_read",
                                "tab_separated_parse",
                                "upstream_condition_directory_label",
                                "round_robin_across_tests",
                            ],
                        ),
                        "probe": None,
                    }
                )
                selected_by_condition[condition] += 1
                selected_by_test[sequence_id] += 1
    audit = {
        "source_id": "pronto",
        "selection": (
            "25_alarm_or_event_rows_per_condition_round_robin_across_tests"
        ),
        "selected_events": len(rows),
        "selected_by_condition": dict(sorted(selected_by_condition.items())),
        "selected_by_test": dict(sorted(selected_by_test.items())),
    }
    return rows, audit


OFBIZ_FAMILY_SPECS: dict[str, dict[str, Any]] = {
    "manufacturing_asset": {
        "entity_quotas": {
            "FixedAsset": 8,
            "CustomMethod": 3,
            "TechDataCalendarWeek": 1,
            "TechDataCalendar": 1,
            "TechDataCalendarExcDay": 1,
            "FixedAssetDepMethod": 2,
        },
        "preferred_files": ["ManufacturingDemoData.xml"],
        "predicate": lambda tag, attrs: tag
        in {
            "CustomMethod",
            "TechDataCalendarWeek",
            "TechDataCalendar",
            "TechDataCalendarExcDay",
            "FixedAsset",
            "FixedAssetDepMethod",
        },
    },
    "bom_product": {
        "entity_quotas": {"ProductAssoc": 8, "Product": 10},
        "preferred_files": ["OrderDemoData.xml"],
        "predicate": lambda tag, attrs: (
            tag == "Product"
            or (
                tag == "ProductAssoc"
                and attrs.get("productAssocTypeId")
                in {"MANUF_COMPONENT", "PRODUCT_COMPONENT"}
            )
        ),
    },
    "inventory": {
        "entity_quotas": {
            "InventoryItem": 6,
            "InventoryItemDetail": 6,
            "ProductFacility": 4,
        },
        "preferred_files": ["OrderDemoData.xml"],
        "predicate": lambda tag, attrs: tag
        in {"InventoryItem", "InventoryItemDetail", "ProductFacility"},
    },
    "order": {
        "entity_quotas": {
            "OrderHeader": 4,
            "OrderItem": 5,
            "OrderStatus": 7,
        },
        "preferred_files": ["OrderDemoData.xml"],
        "predicate": lambda tag, attrs: tag
        in {"OrderHeader", "OrderItem", "OrderStatus"},
    },
    "accounting": {
        "entity_quotas": {
            "Invoice": 6,
            "InvoiceItem": 4,
            "Payment": 4,
            "AcctgTrans": 4,
        },
        "preferred_files": [
            "AccountingDemoData.xml",
            "OrderDemoData.xml",
        ],
        "predicate": lambda tag, attrs: tag
        in {"Invoice", "InvoiceItem", "Payment", "AcctgTrans"},
    },
    "workeffort": {
        "entity_quotas": {
            "WorkEffort": 8,
            "WorkEffortAssoc": 4,
            "WorkEffortPartyAssignment": 3,
            "WorkEffortFixedAssetAssign": 1,
        },
        "preferred_files": ["WorkEffortDemoData.xml"],
        "predicate": lambda tag, attrs: tag
        in {
            "WorkEffort",
            "WorkEffortAssoc",
            "WorkEffortPartyAssignment",
            "WorkEffortFixedAssetAssign",
        },
    },
}


def ofbiz_time(attributes: dict[str, str]) -> tuple[str, str | None]:
    preferred = [
        "transactionDate",
        "orderDate",
        "invoiceDate",
        "paymentDate",
        "datetimeReceived",
        "statusDatetime",
        "estimatedStartDate",
        "fromDate",
        "dateAcquired",
    ]
    for key in preferred:
        if attributes.get(key):
            return "instant", attributes[key]
    return "none", None


def ofbiz_asset(attributes: dict[str, str]) -> str | None:
    for key in (
        "fixedAssetId",
        "productId",
        "orderId",
        "inventoryItemId",
        "invoiceId",
        "paymentId",
        "acctgTransId",
        "workEffortId",
        "facilityId",
    ):
        if attributes.get(key):
            return f"{key}:{attributes[key]}"
    return None


def build_ofbiz() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates: dict[str, list[tuple[str, int, str, dict[str, str]]]] = {
        family: [] for family in OFBIZ_FAMILY_SPECS
    }
    for path in sorted(OFBIZ_DEMO_DIR.glob("*.xml")):
        for index, element in enumerate(ET.parse(path).getroot(), start=1):
            tag = element.tag.split("}")[-1]
            attributes = dict(sorted(element.attrib.items()))
            for family, spec in OFBIZ_FAMILY_SPECS.items():
                predicate = spec["predicate"]
                if predicate(tag, attributes):
                    candidates[family].append(
                        (path.name, index, tag, attributes)
                    )
    rows: list[dict[str, Any]] = []
    selected_by_family: dict[str, int] = {}
    selected_by_entity = Counter()
    for family, spec in OFBIZ_FAMILY_SPECS.items():
        available = candidates[family]
        file_rank = {
            filename: rank
            for rank, filename in enumerate(spec["preferred_files"])
        }
        selected: list[tuple[str, int, str, dict[str, str]]] = []
        for entity, quota in spec["entity_quotas"].items():
            matching = sorted(
                (row for row in available if row[2] == entity),
                key=lambda row: (
                    file_rank.get(row[0], len(file_rank)),
                    row[0],
                    row[1],
                ),
            )
            if len(matching) < quota:
                raise RuntimeError(
                    f"insufficient OFBiz {family}/{entity}: "
                    f"{len(matching)} < {quota}"
                )
            selected.extend(matching[:quota])
        selected.sort(
            key=lambda row: (
                file_rank.get(row[0], len(file_rank)),
                row[0],
                row[1],
            )
        )
        selected_by_family[family] = len(selected)
        for filename, index, tag, attributes in selected:
            time_kind, timestamp = ofbiz_time(attributes)
            asset_id = ofbiz_asset(attributes)
            component_assoc = (
                tag == "ProductAssoc"
                and attributes.get("productAssocTypeId")
                in {"MANUF_COMPONENT", "PRODUCT_COMPONENT"}
            )
            selected_by_entity[tag] += 1
            rows.append(
                {
                    "schema_version": "industrial-event-v0.1",
                    "id": f"ofbiz:{Path(filename).stem}:{index}",
                    "source": source_ref(
                        "ofbiz_manufacturing",
                        f"{filename}:{index}",
                        (
                            "applications/datamodel/data/demo/"
                            f"{filename}"
                        ),
                        row_number=index,
                    ),
                    "domain": {
                        "industry": "synthetic_enterprise_demo",
                        "system": "Apache OFBiz ERP",
                        "process": family,
                        "site": None,
                    },
                    "modality": (
                        "bom" if component_assoc else "erp_transaction"
                    ),
                    "event_type": f"ofbiz_{tag}",
                    "time": {
                        "kind": time_kind,
                        "start": timestamp,
                        "end": timestamp,
                        "timezone": None,
                        "sample_period_seconds": None,
                    },
                    "asset": {
                        "asset_id": asset_id,
                        "asset_type": tag,
                        "parent_asset_id": None,
                    },
                    "context": {
                        "scales": ["event", "asset", "enterprise"],
                        "sequence_id": (
                            asset_id or f"{filename}:{tag}"
                        ),
                        "previous_event_ids": [],
                        "related_event_ids": [],
                    },
                    "payload": {
                        "signals": {},
                        "alarm": None,
                        "operation": None,
                        "maintenance": None,
                        "erp": {
                            "entity": tag,
                            "attributes": attributes,
                        },
                        "bom": (
                            {
                                "parent_product_id": attributes.get(
                                    "productId"
                                ),
                                "component_product_id": attributes.get(
                                    "productIdTo"
                                ),
                                "association_type": attributes.get(
                                    "productAssocTypeId"
                                ),
                                "quantity": parse_scalar(
                                    attributes.get("quantity")
                                ),
                            }
                            if component_assoc
                            else None
                        ),
                        "text": None,
                        "raw_fields": attributes,
                    },
                    "labels": {
                        "state": attributes.get("statusId")
                        or attributes.get("currentStatusId"),
                        "fault": None,
                        "attack": None,
                        "quality": "upstream_demo_xml",
                    },
                    "provenance": provenance(
                        "build_industrial_samples.py:ofbiz",
                        [
                            "xml_element_parse",
                            "attribute_preservation",
                            "entity_family_and_type_quota",
                            "preferred_domain_demo_file_then_source_order",
                        ],
                    ),
                    "probe": None,
                }
            )
    audit = {
        "source_id": "ofbiz_manufacturing",
        "selection": (
            "fixed_entity_family_and_type_quotas_with_preferred_demo_files"
        ),
        "selected_entities": len(rows),
        "selected_by_family": selected_by_family,
        "selected_by_entity": dict(sorted(selected_by_entity.items())),
        "available_by_family": {
            family: len(values)
            for family, values in sorted(candidates.items())
        },
    }
    return rows, audit


BUILDERS = {
    "hai_23_05": (build_hai, "sample_100_events.jsonl"),
    "petrobras_3w": (build_three_w, "sample_100_episodes.jsonl"),
    "pronto": (build_pronto, "sample_100_events.jsonl"),
    "ofbiz_manufacturing": (
        build_ofbiz,
        "sample_100_entities.jsonl",
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "sources",
        nargs="*",
        choices=sorted(BUILDERS),
        help="sources to build; default is all four",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected = args.sources or list(BUILDERS)
    summary: dict[str, Any] = {}
    for source_id in selected:
        builder, filename = BUILDERS[source_id]
        print(f"[{source_id}] building", flush=True)
        rows, audit = builder()
        output, audit_path = write_artifact(
            source_id, filename, rows, audit
        )
        summary[source_id] = {
            "records": len(rows),
            "output": str(output.relative_to(ROOT)),
            "audit": str(audit_path.relative_to(ROOT)),
        }
        print(f"[{source_id}] wrote {len(rows)} records", flush=True)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
