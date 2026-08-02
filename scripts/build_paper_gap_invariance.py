#!/usr/bin/env python3
"""Rebuild the 13-condition workload-composition gap artifact.

The split construction is explicit and deterministic:

* the 12 matched records per archetype are split into six two-record draws;
* the 12 non-matched records per archetype form the held-out pure streams;
* the held-out mixed stream takes the first two non-matched records per archetype.

Temporary event traces are discarded after simulation.  The released artifact
stores every selected request ID and a hash of each semantic condition spec, so
the result does not depend on a timestamped temporary event manifest.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moe_controller.convert import convert_decode_trace
from moe_controller.events import load_event_trace, sha256_file
from moe_controller.simulation import simulate_event_atomic


POLICIES = ("lru", "lfu", "lfru", "least_stale", "belady")
CAUSAL = POLICIES[:-1]
RHO = 0.40
BATCH_SIZE = 8
TIE_SEED = 20260729


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def _source_rows(source: Path) -> list[dict]:
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    rows: list[dict] = []
    for shard in manifest["shards"]:
        with (source / shard["metadata_file"]).open(encoding="utf-8") as handle:
            rows.extend(json.loads(line) for line in handle if line.strip())
    return sorted(rows, key=lambda row: int(row["collection_index"]))


def _conditions(rows: list[dict]) -> list[dict]:
    matched: dict[str, list[dict]] = defaultdict(list)
    heldout: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        metadata = row["metadata"]
        category = metadata["workload_archetype"]
        target = matched if metadata.get("pair_id") else heldout
        target[category].append(row)
    categories = sorted(set(matched) | set(heldout))
    if len(categories) != 6:
        raise ValueError(f"Expected six archetypes, found {categories!r}")
    for category in categories:
        if len(matched[category]) != 12 or len(heldout[category]) != 12:
            raise ValueError(
                f"Expected 12 matched and 12 held-out rows for {category}; "
                f"found {len(matched[category])} and {len(heldout[category])}."
            )

    conditions: list[dict] = []
    for draw in range(6):
        selected = [
            row
            for category in categories
            for row in matched[category][2 * draw : 2 * draw + 2]
        ]
        conditions.append(
            {
                "condition": f"mixed12_draw{draw + 1}",
                "description": f"mixed, 2/category, matched draw {draw + 1}",
                "queue_order": "category_round_robin",
                "rows": selected,
            }
        )
    conditions.append(
        {
            "condition": "mixed12_heldout",
            "description": "mixed, 2/category, held-out pool",
            "queue_order": "category_round_robin",
            "rows": [
                row
                for category in categories
                for row in heldout[category][:2]
            ],
        }
    )
    short_names = {
        "dcs_process_diagnostics": "dcs",
        "document_rag": "rag",
        "equipment_maintenance_bom": "equipment",
        "erp_structured_analytics": "erp",
        "office_legal": "office",
        "tool_agent": "agent",
    }
    for category in categories:
        conditions.append(
            {
                "condition": f"pure_{short_names[category]}",
                "description": f"pure {category}",
                "queue_order": "source",
                "rows": heldout[category],
            }
        )
    return conditions


def _spec(condition: dict) -> dict:
    return {
        "condition": condition["condition"],
        "description": condition["description"],
        "queue_order": condition["queue_order"],
        "request_ids": [str(row["id"]) for row in condition["rows"]],
        "arrival_offsets": {
            str(row["id"]): int(
                row["metadata"]["collection"]["arrival_offset_steps"]
            )
            for row in condition["rows"]
        },
    }


def _spec_hash(spec: dict) -> str:
    encoded = json.dumps(
        spec, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def main() -> None:
    args = _args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")
    source_manifest = args.source / "manifest.json"
    conditions = _conditions(_source_rows(args.source))
    result_rows: list[dict] = []
    released_specs: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="moe-gap-invariance-") as tmp:
        tmp_root = Path(tmp)
        for condition in conditions:
            spec = _spec(condition)
            events = tmp_root / condition["condition"]
            convert_decode_trace(
                args.source,
                events,
                batch_size=BATCH_SIZE,
                queue_order=condition["queue_order"],
                include_request_ids=tuple(spec["request_ids"]),
                arrival_offset_map=spec["arrival_offsets"],
            )
            trace = load_event_trace(events)
            logical = int(
                trace.manifest["counts"][
                    "logical_expert_assignments_before_dedup"
                ]
            )
            capacity = round(trace.num_expert_blocks * RHO)
            measured: dict[str, float] = {}
            for policy in POLICIES:
                result = simulate_event_atomic(
                    trace,
                    policy=policy,
                    capacity_blocks=capacity,
                    cache_scope="per_layer",
                    tie_seed=TIE_SEED,
                )
                measured[policy] = result.transferred_blocks / logical
            best_policy = min(CAUSAL, key=measured.__getitem__)
            best = measured[best_policy]
            oracle = measured["belady"]
            gap = (best - oracle) / best
            scheduler_steps = int(trace.manifest["counts"]["scheduler_steps"])
            decode_forwards = int(trace.manifest["counts"]["decode_forwards"])
            result_rows.append(
                {
                    "condition": condition["condition"],
                    "description": condition["description"],
                    "requests": len(spec["request_ids"]),
                    "scheduler_steps": scheduler_steps,
                    "mean_active_batch": decode_forwards / scheduler_steps,
                    "condition_spec_sha256": _spec_hash(spec),
                    "best_causal": best_policy,
                    "best_causal_miss": best,
                    "belady_miss": oracle,
                    "recoverable_gap": gap,
                }
            )
            released_specs.append({**spec, "sha256": _spec_hash(spec)})
            print(condition["condition"], f"gap={gap:.6%}", flush=True)

    args.output.mkdir(parents=True)
    with (args.output / "gap-invariance.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(result_rows[0]))
        writer.writeheader()
        writer.writerows(result_rows)
    (args.output / "condition-specs.json").write_text(
        json.dumps(released_specs, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    gaps = [float(row["recoverable_gap"]) for row in result_rows]
    manifest = {
        "kind": "belady_gap_invariance_across_workload_composition",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "generator": "scripts/build_paper_gap_invariance.py",
        "source": {
            "root": str(args.source.resolve()),
            "manifest_sha256": sha256_file(source_manifest),
        },
        "scope": {
            "model": "Qwen3-30B-A3B-4bit",
            "split": "D1 diverse confirmatory",
            "cache_scope": "per_layer",
            "rho": RHO,
            "batch_size": BATCH_SIZE,
            "replay": "event_atomic",
            "tie_seed": TIE_SEED,
            "policies": list(POLICIES),
        },
        "conditions": len(result_rows),
        "gap_min": min(gaps),
        "gap_max": max(gaps),
        "gap_mean": sum(gaps) / len(gaps),
        "artifacts": ["gap-invariance.csv", "condition-specs.json", "README.md"],
        "exclusion": (
            "Do not pool with the rho sweep or B=2; those are different "
            "operating points."
        ),
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output / "README.md").write_text(
        "# Reproducible 13-condition gap-invariance artifact\n\n"
        "Generated by `scripts/build_paper_gap_invariance.py`. The semantic "
        "condition file freezes request IDs, arrival offsets, queue ordering, "
        "and a hash for each condition.\n\n"
        f"Observed gap range: {min(gaps):.4%}–{max(gaps):.4%}; mean "
        f"{sum(gaps) / len(gaps):.4%}. Do not pool this range with another "
        "batch size or residency fraction.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
