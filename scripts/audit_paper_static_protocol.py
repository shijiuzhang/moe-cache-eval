#!/usr/bin/env python3
"""Freeze and compare the two static-residency protocols used in the paper.

This is an artifact audit over an existing event stream.  It does not collect
routes or fit a model.  The two protocols deliberately answer different
questions:

* ``static_same_trace`` selects the most frequent experts on the evaluated
  trace itself.  It is a leaky diagnostic upper reference, not deployable.
* ``static_frozen`` evaluates a pin list selected from a disjoint discovery
  trace and frozen before the evaluated trace is read.

Both use equal per-layer quotas and count the one-time preload in transferred
blocks.  Keeping the protocols under different names prevents their values from
being silently combined in the manuscript.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moe_controller.events import load_event_trace, sha256_file
from moe_controller.simulation import simulate_event_atomic, simulate_static_fixed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", type=Path)
    parser.add_argument("--static-pins", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)

    trace = load_event_trace(args.events)
    pins_payload = json.loads(args.static_pins.read_text(encoding="utf-8"))
    if pins_payload.get("status") != "frozen_from_discovery_only":
        raise ValueError("Static pins are not marked discovery-frozen")
    if pins_payload.get("cache_scope") != "per_layer_equal_quota":
        raise ValueError("Static pins do not use equal per-layer quotas")

    capacity = int(pins_payload["capacity_blocks"])
    logical = int(
        trace.manifest["counts"]["logical_expert_assignments_before_dedup"]
    )
    same_trace = simulate_event_atomic(
        trace,
        policy="static",
        capacity_blocks=capacity,
        cache_scope="per_layer",
        tie_seed=20260729,
    )
    frozen = simulate_static_fixed(
        trace,
        resident_blocks=pins_payload["resident_blocks"],
    )

    rows = [
        {
            "protocol": "static_same_trace",
            "fit_source": "evaluation_trace_itself",
            "deployable": False,
            "quota_rule": "equal_per_layer_low_index_remainder",
            "initial_preload_counted": True,
            "initial_load_blocks": same_trace.initial_load_blocks,
            "miss_blocks": same_trace.misses,
            "transferred_blocks": same_trace.transferred_blocks,
            "effective_miss_fraction": same_trace.transferred_blocks / logical,
        },
        {
            "protocol": "static_frozen",
            "fit_source": "disjoint_discovery_trace",
            "deployable": True,
            "quota_rule": "equal_per_layer_low_index_remainder",
            "initial_preload_counted": True,
            "initial_load_blocks": frozen.initial_load_blocks,
            "miss_blocks": frozen.misses,
            "transferred_blocks": frozen.transferred_blocks,
            "effective_miss_fraction": frozen.transferred_blocks / logical,
        },
    ]
    relative_transfer_penalty = (
        rows[1]["effective_miss_fraction"]
        - rows[0]["effective_miss_fraction"]
    ) / rows[0]["effective_miss_fraction"]

    args.output.mkdir(parents=True)
    csv_path = args.output / "static-protocol-comparison.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete_posthoc_protocol_audit",
        "scope": "one frozen B=8 held-out event stream; not a new hypothesis test",
        "events": {
            "root": str(args.events.resolve()),
            "manifest_sha256": sha256_file(args.events / "manifest.json"),
        },
        "static_pins": {
            "path": str(args.static_pins.resolve()),
            "sha256": sha256_file(args.static_pins),
            "source_event_root": pins_payload["source_event_root"],
            "source_manifest_sha256": pins_payload["source_manifest_sha256"],
        },
        "capacity_blocks": capacity,
        "logical_assignments": logical,
        "relative_frozen_vs_same_trace_transfer_penalty": relative_transfer_penalty,
        "artifact": {
            "path": csv_path.name,
            "sha256": sha256_file(csv_path),
            "rows": len(rows),
        },
        "paper_usage": {
            "static_same_trace": "diagnostic replay-invariance reference only",
            "static_frozen": "held-out deployment-style baseline",
        },
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
