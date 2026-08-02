#!/usr/bin/env python3
"""Build the frozen 240-record ControllerProbe-v0.1 prompt set."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "data" / "controller_probe_v0_1_3"
VERSION = "v0.1.3"
SEED = "controller-probe-v0.1-20260729"

PUBLIC_PATH = (
    ROOT / "data" / "enterprise_proxy_1k" / "enterprise_proxy_1k.jsonl"
)
SYNTHETIC_PATH = (
    ROOT
    / "data"
    / "synthetic_enterprise_1k"
    / "synthetic_enterprise_1k.jsonl"
)
INDUSTRIAL = ROOT / "data" / "industrial_public"
HAI_S1 = INDUSTRIAL / "derived/hai_23_05/cases_s1_100_windows.jsonl"
HAI_S2 = INDUSTRIAL / "derived/hai_23_05/cases_s2_100_episodes.jsonl"
THREE_W_S1 = (
    INDUSTRIAL / "derived/petrobras_3w/cases_s1_100_windows.jsonl"
)
PRONTO = INDUSTRIAL / "derived/pronto/sample_100_events.jsonl"
PACKAGING = (
    INDUSTRIAL / "derived/packaging_alarms/sample_100_events.jsonl"
)
OFBIZ = (
    INDUSTRIAL
    / "derived/ofbiz_manufacturing/sample_100_entities.jsonl"
)

ARCHETYPES = (
    "document_rag",
    "tool_agent",
    "erp_structured_analytics",
    "office_legal",
    "dcs_process_diagnostics",
    "equipment_maintenance_bom",
)
SPLITS = ("discovery", "confirmatory")
RENDERER_VERSION = "controller-probe-industrial-renderer-v0.1.2"


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_key(value: str) -> str:
    return hashlib.sha256(f"{SEED}|{value}".encode()).hexdigest()


def json_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def fmt(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def signal_rows(summary: dict, limit: int = 5) -> list[tuple[str, dict]]:
    ranked = []
    for name, values in summary.items():
        numeric = [
            float(values[key])
            for key in ("first", "last", "min", "max", "mean")
            if finite(values.get(key))
        ]
        if not numeric:
            score = -1.0
        else:
            low = float(values["min"]) if finite(values.get("min")) else min(
                numeric
            )
            high = (
                float(values["max"])
                if finite(values.get("max"))
                else max(numeric)
            )
            mean = (
                float(values["mean"])
                if finite(values.get("mean"))
                else sum(numeric) / len(numeric)
            )
            score = abs(high - low) / (abs(mean) + 1.0)
        ranked.append((score, name, values))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [(name, values) for _, name, values in ranked[:limit]]


def render_signal_case(row: dict) -> tuple[str, str]:
    summary = row["payload"]["signal_summary"]
    lines = []
    for name, values in signal_rows(summary):
        lines.append(
            f"- {name}: first={fmt(values.get('first'))}, "
            f"last={fmt(values.get('last'))}, "
            f"min={fmt(values.get('min'))}, "
            f"max={fmt(values.get('max'))}"
        )
    labels = row["labels"]
    prompt = (
        "You are an industrial process-operations assistant. Use only the "
        "public benchmark record below; do not invent causes or missing "
        "measurements.\n\n"
        f"Dataset: {row['source']['dataset_id']}\n"
        f"Case: {row['id']}\n"
        f"Semantic scale: {row['semantic_scale']} "
        f"({row['semantic_unit']})\n"
        f"Interval: {row['time']['start']} to {row['time']['end']}\n"
        f"Record label: state={labels.get('state')}, "
        f"fault={labels.get('fault')}, attack={labels.get('attack')}\n"
        "Selected signal summaries (deterministically ranked by normalized "
        "range):\n"
        + "\n".join(lines)
        + "\n\nTask: Summarize the operating interval, identify the three "
        "signals with the clearest changes, and report the supplied state/"
        "fault label. Separate observed evidence from any hypothesis."
    )
    return prompt, "process_interval_diagnosis"


def render_pronto(row: dict) -> tuple[str, str]:
    alarm = row["payload"]["alarm"]
    prompt = (
        "You are triaging an alarm from a public industrial process "
        "benchmark. Use only the fields supplied.\n\n"
        f"Benchmark record: {row['id']}\n"
        f"Condition: {row['labels'].get('state')}\n"
        f"Timestamp: {row['time'].get('start')}\n"
        f"Area: {alarm.get('area')}\n"
        f"Module: {alarm.get('module')} "
        f"({alarm.get('module_description')})\n"
        f"Parameter: {alarm.get('parameter')}\n"
        f"Alarm level: {alarm.get('level')}\n"
        f"State: {alarm.get('state')}\n"
        f"Descriptions: {alarm.get('description_1')} | "
        f"{alarm.get('description_2')}\n\n"
        "Task: Produce a concise operator handoff containing the affected "
        "module, severity, acknowledgement state, and the exact evidence. "
        "Do not claim a root cause."
    )
    return prompt, "alarm_triage"


def render_packaging(row: dict) -> tuple[str, str]:
    fields = row["payload"]["raw_fields"]
    prompt = (
        "You are assisting maintenance staff with a public packaging-machine "
        "alarm record.\n\n"
        f"Machine serial: {fields.get('serial')}\n"
        f"Alarm code: {fields.get('alarm')}\n"
        f"Timestamp: {fields.get('timestamp')}\n\n"
        "Task: Create a maintenance intake note. Preserve the exact machine, "
        "alarm code and time; list which additional evidence would be needed "
        "before diagnosing the fault. Do not invent an alarm-code meaning."
    )
    return prompt, "maintenance_alarm_intake"


def render_ofbiz(row: dict) -> tuple[str, str]:
    erp = row["payload"]["erp"] or {}
    attributes = erp.get("attributes") or row["payload"]["raw_fields"]
    serialized = json.dumps(
        attributes,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    )
    prompt = (
        "You are an ERP and manufacturing-data assistant. The following "
        "record comes from Apache OFBiz public demo data.\n\n"
        f"Entity type: {erp.get('entity')}\n"
        f"Record identifier: {row['id']}\n"
        f"Attributes:\n{serialized}\n\n"
        "Task: Explain what this record represents, extract its identifiers "
        "and operationally relevant fields, and state which related ERP/BOM "
        "records would be needed to validate it. Do not invent relationships "
        "that are not present."
    )
    return prompt, "erp_entity_analysis"


def seed_split_map(rows: list[dict]) -> dict[str, str]:
    groups = sorted(
        {row["context"]["sequence_id"] for row in rows},
        key=stable_key,
    )
    midpoint = len(groups) // 2
    return {
        group: ("discovery" if index < midpoint else "confirmatory")
        for index, group in enumerate(groups)
    }


def select(
    rows: list[dict],
    *,
    quota: int,
    salt: str,
    predicate: Callable[[dict], bool],
    group_key: Callable[[dict], str] | None = None,
    used: set[str] | None = None,
) -> list[dict]:
    candidates = [row for row in rows if predicate(row)]
    candidates.sort(key=lambda row: stable_key(f"{salt}|{row['id']}"))
    selected = []
    seen_groups: set[str] = set()
    for row in candidates:
        origin = row["id"]
        if used is not None and origin in used:
            continue
        if group_key is not None:
            group = group_key(row)
            if group in seen_groups:
                continue
            seen_groups.add(group)
        selected.append(row)
        if used is not None:
            used.add(origin)
        if len(selected) == quota:
            return selected
    raise RuntimeError(
        f"Only selected {len(selected)}/{quota} records for {salt}."
    )


def source_group(row: dict) -> str:
    return str(
        row.get("workflow_id")
        or row.get("session_id")
        or row["id"]
    )


def adapt_existing(
    row: dict,
    *,
    archetype: str,
    source_path: Path,
    source_hash: str,
) -> dict:
    source = row["source"]
    return {
        "workload_archetype": archetype,
        "task_type": row["operation"],
        "prompt_text": row["prompt_text"],
        "reference_continuation": row.get("reference_answer"),
        "split": row["split"],
        "language": row["language"],
        "session_id": row.get("session_id") or row["id"],
        "turn_index": int(row.get("turn_index") or 0),
        "group_id": (
            f"{source.get('dataset')}::{source_group(row)}"
        ),
        "source_record_ids": [str(source.get("row_id") or row["id"])],
        "source_family": str(source.get("dataset")),
        "provenance": {
            "provenance_type": row["provenance_type"],
            "source": source,
            "local_source_artifact": str(source_path.relative_to(ROOT)),
            "local_source_sha256": source_hash,
            "source_probe_id": row["id"],
            "transform": "prompt_text_selected_without_reference_answer",
            "contains_private_data": False,
        },
    }


def adapt_industrial(
    row: dict,
    *,
    archetype: str,
    source_path: Path,
    source_hash: str,
    split: str,
    renderer: Callable[[dict], tuple[str, str]],
) -> dict:
    prompt, task_type = renderer(row)
    source_record_ids = row.get("source_record_ids") or [
        row["source"].get("record_id") or row["id"]
    ]
    group = row.get("group_id") or row["context"]["sequence_id"]
    return {
        "workload_archetype": archetype,
        "task_type": task_type,
        "prompt_text": prompt,
        "reference_continuation": None,
        "split": split,
        "language": "en",
        "session_id": row["id"],
        "turn_index": 0,
        "group_id": f"{row['source']['dataset_id']}::{group}",
        "source_record_ids": source_record_ids,
        "source_family": row["source"]["dataset_id"],
        "provenance": {
            "provenance_type": "public_industrial_benchmark",
            "source": row["source"],
            "local_source_artifact": str(source_path.relative_to(ROOT)),
            "local_source_sha256": source_hash,
            "source_probe_id": row["id"],
            "transform": RENDERER_VERSION,
            "contains_private_data": False,
        },
    }


def build() -> tuple[list[dict], dict, dict]:
    source_paths = (
        PUBLIC_PATH,
        SYNTHETIC_PATH,
        HAI_S1,
        HAI_S2,
        THREE_W_S1,
        PRONTO,
        PACKAGING,
        OFBIZ,
    )
    hashes = {path: sha256_file(path) for path in source_paths}
    public = read_jsonl(PUBLIC_PATH)
    synthetic = read_jsonl(SYNTHETIC_PATH)
    industrial_rows = {
        HAI_S1: read_jsonl(HAI_S1),
        HAI_S2: read_jsonl(HAI_S2),
        THREE_W_S1: read_jsonl(THREE_W_S1),
        PRONTO: read_jsonl(PRONTO),
        PACKAGING: read_jsonl(PACKAGING),
        OFBIZ: read_jsonl(OFBIZ),
    }
    seed_splits = {
        path: seed_split_map(industrial_rows[path])
        for path in (PRONTO, PACKAGING, OFBIZ)
    }
    selected: list[dict] = []
    used_industrial = {path: set() for path in industrial_rows}

    def add_existing(
        rows: list[dict],
        path: Path,
        archetype: str,
        category: str,
        split: str,
        quota: int,
        *,
        extra: Callable[[dict], bool] = lambda row: True,
        unique_group: bool = False,
    ) -> None:
        chosen = select(
            rows,
            quota=quota,
            salt=f"{archetype}|{category}|{split}",
            predicate=lambda row: (
                row["category"] == category
                and row["split"] == split
                and extra(row)
            ),
            group_key=source_group if unique_group else None,
        )
        selected.extend(
            adapt_existing(
                row,
                archetype=archetype,
                source_path=path,
                source_hash=hashes[path],
            )
            for row in chosen
        )

    def add_industrial(
        path: Path,
        archetype: str,
        split: str,
        quota: int,
        renderer: Callable[[dict], tuple[str, str]],
        *,
        existing_split: bool,
    ) -> None:
        rows = industrial_rows[path]
        if existing_split:
            predicate = lambda row: row["split"] == split
            split_for = lambda row: row["split"]
        else:
            mapping = seed_splits[path]
            predicate = (
                lambda row: mapping[row["context"]["sequence_id"]] == split
            )
            split_for = (
                lambda row: mapping[row["context"]["sequence_id"]]
            )
        chosen = select(
            rows,
            quota=quota,
            salt=f"{archetype}|{path.name}|{split}",
            predicate=predicate,
            group_key=(
                None
                if existing_split
                else lambda row: row["context"]["sequence_id"]
            ),
            used=used_industrial[path],
        )
        selected.extend(
            adapt_industrial(
                row,
                archetype=archetype,
                source_path=path,
                source_hash=hashes[path],
                split=split_for(row),
                renderer=renderer,
            )
            for row in chosen
        )

    for split in SPLITS:
        add_existing(
            public,
            PUBLIC_PATH,
            "document_rag",
            "document_rag",
            split,
            20,
        )
        add_existing(
            public,
            PUBLIC_PATH,
            "tool_agent",
            "tool_agent",
            split,
            10,
            extra=lambda row: (
                not bool(row["metadata"].get("multi_turn"))
                and not row["truncated_at_512"]["granite"]
                and not row["truncated_at_512"]["olmoe"]
            ),
        )
        add_existing(
            public,
            PUBLIC_PATH,
            "tool_agent",
            "tool_agent",
            split,
            10,
            extra=lambda row: (
                bool(row["metadata"].get("multi_turn"))
                and not row["truncated_at_512"]["granite"]
                and not row["truncated_at_512"]["olmoe"]
            ),
        )
        add_existing(
            public,
            PUBLIC_PATH,
            "erp_structured_analytics",
            "structured_analytics",
            split,
            10,
        )
        add_industrial(
            OFBIZ,
            "erp_structured_analytics",
            split,
            10,
            render_ofbiz,
            existing_split=False,
        )
        add_existing(
            public,
            PUBLIC_PATH,
            "office_legal",
            "legal_compliance",
            split,
            10,
        )
        add_existing(
            synthetic,
            SYNTHETIC_PATH,
            "office_legal",
            "hr_policy",
            split,
            5,
            unique_group=True,
        )
        add_existing(
            synthetic,
            SYNTHETIC_PATH,
            "office_legal",
            "legal_contract",
            split,
            5,
            unique_group=True,
        )
        for path in (HAI_S1, HAI_S2, THREE_W_S1):
            add_industrial(
                path,
                "dcs_process_diagnostics",
                split,
                5,
                render_signal_case,
                existing_split=True,
            )
        add_industrial(
            PRONTO,
            "dcs_process_diagnostics",
            split,
            5,
            render_pronto,
            existing_split=False,
        )
        add_industrial(
            PACKAGING,
            "equipment_maintenance_bom",
            split,
            10,
            render_packaging,
            existing_split=False,
        )
        add_industrial(
            OFBIZ,
            "equipment_maintenance_bom",
            split,
            5,
            render_ofbiz,
            existing_split=False,
        )
        add_existing(
            synthetic,
            SYNTHETIC_PATH,
            "equipment_maintenance_bom",
            "engineering_change",
            split,
            5,
            unique_group=True,
        )

    selected.sort(
        key=lambda row: (
            ARCHETYPES.index(row["workload_archetype"]),
            SPLITS.index(row["split"]),
            stable_key(
                f"{row['workload_archetype']}|"
                f"{row['provenance']['source_probe_id']}"
            ),
        )
    )
    records = []
    for index, row in enumerate(selected):
        record = {
            "schema_version": f"controller-probe-{VERSION}",
            "id": f"cp-v01-{index:03d}",
            "selection_index": index,
            **row,
            "expected_phase": "prefill",
            "phase_scope": "prompt_only",
            "text": row["prompt_text"],
        }
        record["content_sha256"] = hashlib.sha256(
            record["prompt_text"].encode()
        ).hexdigest()
        records.append(record)

    source_manifest = {
        str(path.relative_to(ROOT)): {
            "sha256": hashes[path],
            "records": len(read_jsonl(path)),
        }
        for path in source_paths
    }
    manifest = {
        "schema_version": f"controller-probe-manifest-{VERSION}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "selection_seed": SEED,
        "renderer_version": RENDERER_VERSION,
        "records": len(records),
        "target": {
            "per_archetype": 40,
            "per_archetype_split": 20,
            "splits": list(SPLITS),
            "archetypes": list(ARCHETYPES),
        },
        "scope": (
            "prompt-only controller instrumentation; not an accuracy "
            "benchmark and not a claim about enterprise traffic prevalence"
        ),
        "sources": source_manifest,
        "split_policy": {
            "existing_enterprise_rows": "retain frozen upstream proxy split",
            "industrial_case_pools": "retain frozen group-aware case split",
            "industrial_seed_rows": (
                "sort unique sequence groups by SHA256(seed|group), first "
                "half discovery, second half confirmatory"
            ),
            "group_leakage": "prohibited across discovery/confirmatory",
        },
    }
    audit = audit_records(records)
    return records, manifest, audit


def audit_records(records: list[dict]) -> dict:
    archetypes = Counter(row["workload_archetype"] for row in records)
    cells = Counter(
        (row["workload_archetype"], row["split"]) for row in records
    )
    group_splits: dict[str, set[str]] = defaultdict(set)
    for row in records:
        group_splits[row["group_id"]].add(row["split"])
    prompt_hashes = Counter(row["content_sha256"] for row in records)
    forbidden = ("kraussmaffei", "/users/localuser", "localuser")
    checks = {
        "record_count_240": len(records) == 240,
        "six_archetypes_40_each": (
            set(archetypes) == set(ARCHETYPES)
            and set(archetypes.values()) == {40}
        ),
        "cells_20_each": (
            len(cells) == 12 and set(cells.values()) == {20}
        ),
        "unique_ids": len({row["id"] for row in records}) == len(records),
        "unique_prompts": max(prompt_hashes.values(), default=0) == 1,
        "no_group_split_leakage": all(
            len(values) == 1 for values in group_splits.values()
        ),
        "no_private_markers": not any(
            marker in row["prompt_text"].casefold()
            for row in records
            for marker in forbidden
        ),
        "all_prompt_only": all(
            row["expected_phase"] == "prefill"
            and row["phase_scope"] == "prompt_only"
            and row["text"] == row["prompt_text"]
            for row in records
        ),
        "provenance_complete": all(
            row["provenance"]["local_source_sha256"]
            and row["provenance"]["source_probe_id"]
            and row["provenance"]["contains_private_data"] is False
            for row in records
        ),
    }
    return {
        "all_checks_pass": all(checks.values()),
        "checks": checks,
        "counts": {
            "archetypes": dict(sorted(archetypes.items())),
            "archetype_split": {
                f"{key[0]}::{key[1]}": value
                for key, value in sorted(cells.items())
            },
            "sources": dict(
                sorted(Counter(row["source_family"] for row in records).items())
            ),
            "languages": dict(
                sorted(Counter(row["language"] for row in records).items())
            ),
        },
        "prompt_characters": {
            "min": min(len(row["prompt_text"]) for row in records),
            "max": max(len(row["prompt_text"]) for row in records),
            "mean": (
                sum(len(row["prompt_text"]) for row in records) / len(records)
            ),
        },
        "dataset_content_sha256": json_hash(records),
    }


def write_outputs(records: list[dict], manifest: dict, audit: dict) -> None:
    if OUTPUT.exists():
        raise FileExistsError(f"Refusing to overwrite {OUTPUT}.")
    OUTPUT.mkdir(parents=True)
    data_path = OUTPUT / "controller_probe_v0_1_3.jsonl"
    with data_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(
                json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
            )
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "ControllerProbe-v0.1 record",
        "type": "object",
        "required": [
            "schema_version",
            "id",
            "workload_archetype",
            "task_type",
            "prompt_text",
            "reference_continuation",
            "expected_phase",
            "split",
            "group_id",
            "source_record_ids",
            "provenance",
            "content_sha256",
        ],
        "properties": {
            "split": {"enum": list(SPLITS)},
            "workload_archetype": {"enum": list(ARCHETYPES)},
            "expected_phase": {"const": "prefill"},
            "phase_scope": {"const": "prompt_only"},
        },
    }
    schema_path = OUTPUT / "schema.json"
    schema_path.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    audit_path = OUTPUT / "audit.json"
    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest["artifacts"] = {
        "records": {
            "path": data_path.name,
            "sha256": sha256_file(data_path),
            "bytes": data_path.stat().st_size,
        },
        "schema": {
            "path": schema_path.name,
            "sha256": sha256_file(schema_path),
        },
        "audit": {
            "path": audit_path.name,
            "sha256": sha256_file(audit_path),
        },
    }
    (OUTPUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUTPUT / "README.md").write_text(
        "# ControllerProbe-v0.1.3\n\n"
        "用于 MoE 内存控制器的 240 条 prompt-only 场景探测集。六类各 "
        "40 条，discovery/confirmatory 各 20 条。它用于路由与缓存"
        "画像，不是模型准确率排行榜，也不代表企业真实流量比例。\n\n"
        "全部记录来自已冻结的公开数据或确定性合成数据，不包含公司"
        "内部资料。具体来源、哈希、许可证和渲染规则见 manifest 与"
        "逐行 provenance。\n",
        encoding="utf-8",
    )


def main() -> int:
    records, manifest, audit = build()
    if not audit["all_checks_pass"]:
        raise RuntimeError(json.dumps(audit, ensure_ascii=False, indent=2))
    write_outputs(records, manifest, audit)
    print(
        json.dumps(
            {
                "output": str(OUTPUT.relative_to(ROOT)),
                "records": len(records),
                "audit": audit,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
