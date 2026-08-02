#!/usr/bin/env python3
"""Build the frozen design manifest for IndustrialProbe-1K v0.1.

This script does not render prompts. It freezes the intended source-by-scale
balance, inputs, controls and materialization state before prompt engineering
can change the experiment post hoc.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "industrial_public"
OUTPUT = DATA_DIR / "PROBE_MANIFEST.v0.1.json"

SOURCES = {
    "hai_23_05": {
        "artifact": "derived/hai_23_05/sample_100_events.jsonl",
        "license": "CC-BY-SA-4.0",
        "scale_units": [
            ("point", "single_1hz_observation", "seed_ready"),
            ("local_window", "contiguous_32_64_128_points", "case_pool_ready"),
            ("episode", "label_transition_bounded_interval", "case_pool_ready"),
            ("process_plant", "related_interval_comparison", "planned"),
        ],
    },
    "pronto": {
        "artifact": "derived/pronto/sample_100_events.jsonl",
        "license": "CC-BY-4.0",
        "scale_units": [
            ("event", "single_alarm_or_operation_event", "seed_ready"),
            ("local_window", "same_test_8_16_32_events", "planned"),
            ("episode", "complete_test_event_chain", "planned"),
            ("process_plant", "same_condition_cross_test_comparison", "planned"),
        ],
    },
    "packaging_alarms": {
        "artifact": "derived/packaging_alarms/sample_100_events.jsonl",
        "license": "CC-BY-4.0",
        "scale_units": [
            ("event", "single_alarm", "seed_ready"),
            ("local_window", "same_machine_8_16_32_alarms", "planned"),
            ("asset_episode", "same_machine_deterministic_time_block", "planned"),
            ("plant_fleet", "cross_machine_alarm_distribution", "planned"),
        ],
    },
    "petrobras_3w": {
        "artifact": "derived/petrobras_3w/sample_100_episodes.jsonl",
        "license": "CC-BY-4.0",
        "scale_units": [
            ("point", "single_episode_timestamp", "case_pool_ready"),
            ("local_window", "same_episode_32_128_512_points", "case_pool_ready"),
            ("episode", "complete_parquet_episode", "seed_ready"),
            (
                "process_field",
                "same_class_cross_instance_comparison",
                "case_pool_ready",
            ),
        ],
    },
    "ofbiz_manufacturing": {
        "artifact": "derived/ofbiz_manufacturing/sample_100_entities.jsonl",
        "license": "Apache-2.0",
        "scale_units": [
            ("entity", "single_xml_entity", "seed_ready"),
            ("relation", "explicit_key_one_hop_neighborhood", "planned"),
            ("workflow", "verified_key_business_chain", "planned"),
            ("enterprise", "cross_module_consistency_case", "planned"),
        ],
    },
}

CASE_POOLS = [
    ("hai_23_05", "S1", "derived/hai_23_05/cases_s1_100_windows.jsonl"),
    ("hai_23_05", "S2", "derived/hai_23_05/cases_s2_100_episodes.jsonl"),
    (
        "petrobras_3w",
        "S0",
        "derived/petrobras_3w/cases_s0_100_points.jsonl",
    ),
    (
        "petrobras_3w",
        "S1",
        "derived/petrobras_3w/cases_s1_100_windows.jsonl",
    ),
    (
        "petrobras_3w",
        "S3",
        "derived/petrobras_3w/cases_s3_50_comparisons.jsonl",
    ),
]

SCALE_TASKS = {
    "S0": [
        "exact_field_extraction",
        "state_or_entity_classification",
        "evidence_selection",
    ],
    "S1": [
        "local_change_detection",
        "window_comparison",
        "relation_consistency",
    ],
    "S2": [
        "episode_classification",
        "event_chain_summary",
        "workflow_consistency",
    ],
    "S3": [
        "cross_case_comparison",
        "priority_ranking",
        "process_or_enterprise_constraint_check",
    ],
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def line_count(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for line in handle if line.strip())


def build() -> dict[str, Any]:
    inputs = {}
    case_pools = []
    cells = []
    for source_id, source in SOURCES.items():
        relative = source["artifact"]
        path = DATA_DIR / relative
        if not path.exists():
            raise FileNotFoundError(path)
        inputs[source_id] = {
            "path": relative,
            "records": line_count(path),
            "sha256": sha256(path),
            "license": source["license"],
        }
        for index, (unit, rule, status) in enumerate(
            source["scale_units"]
        ):
            scale = f"S{index}"
            cells.append(
                {
                    "cell_id": f"{source_id}:{scale}",
                    "source_id": source_id,
                    "semantic_scale": scale,
                    "semantic_unit": unit,
                    "construction_rule": rule,
                    "task_families": SCALE_TASKS[scale],
                    "target_probes": 50,
                    "primary_probes": 40,
                    "paired_control_probes": 10,
                    "language_target": {"zh": 25, "en": 25},
                    "materialization_status": status,
                }
            )
    for source_id, scale, relative in CASE_POOLS:
        path = DATA_DIR / relative
        if not path.exists():
            raise FileNotFoundError(path)
        case_pools.append(
            {
                "source_id": source_id,
                "semantic_scale": scale,
                "path": relative,
                "records": line_count(path),
                "sha256": sha256(path),
            }
        )
    return {
        "manifest_version": "industrial-probe-1k-design-v0.1",
        "created_at": "2026-07-28",
        "status": "design_frozen_case_pools_partial_prompts_not_materialized",
        "records_materialized": 0,
        "case_pool_records_materialized": sum(
            pool["records"] for pool in case_pools
        ),
        "case_pool_cells_ready": len(case_pools),
        "target_probes": sum(cell["target_probes"] for cell in cells),
        "target_distribution": {
            "per_source": 200,
            "per_semantic_scale": 250,
            "per_source_scale_cell": 50,
            "primary": 800,
            "paired_controls": 200,
        },
        "semantic_scales": {
            "S0": "point_event_or_entity",
            "S1": "local_window_or_relation",
            "S2": "episode_asset_or_workflow",
            "S3": "process_plant_or_enterprise",
        },
        "routing_token_block_scales": [1, 8, 16, 32, 64, 128, 256],
        "scale_axes_are_independent": True,
        "split_policy": {
            "target": {
                "discovery": 0.5,
                "confirmatory": 0.25,
                "test": 0.25,
            },
            "group_constraint": (
                "all scales/languages/serializations/controls derived from "
                "one base_case_id remain in one split"
            ),
        },
        "control_pool": [
            "length_matched_unrelated",
            "within_window_permutation",
            "label_permutation",
            "serialization_pair",
            "language_pair",
            "scale_ablation",
        ],
        "required_probe_fields": [
            "id",
            "base_case_id",
            "source",
            "semantic_scale",
            "semantic_unit",
            "window_rule",
            "source_record_ids",
            "source_record_count",
            "token_count",
            "language",
            "serialization",
            "control_type",
            "prompt_text",
            "reference_answer",
            "evaluator",
            "split",
        ],
        "inputs": inputs,
        "case_pools": case_pools,
        "cells": cells,
        "specification": "MULTISCALE_WINDOW_SPEC.zh-CN.md",
        "notes": [
            "A seed_ready cell has normalized source units, not finished prompts.",
            "A case_pool_ready cell has grouped cases, not finished prompts.",
            "A planned cell requires deterministic window/relation construction.",
            "No held or license-unverified source contributes to this manifest.",
        ],
    }


def main() -> int:
    manifest = build()
    OUTPUT.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(OUTPUT.relative_to(ROOT)),
                "cells": len(manifest["cells"]),
                "target_probes": manifest["target_probes"],
                "records_materialized": manifest["records_materialized"],
                "case_pool_records_materialized": manifest[
                    "case_pool_records_materialized"
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
