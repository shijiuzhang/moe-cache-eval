#!/usr/bin/env python3
"""Freeze an equal-per-layer static expert pin list from discovery events."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moe_controller.events import load_event_trace, sha256_file
from moe_controller.simulation import flatten_accesses


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("events", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--capacity-blocks", type=int, default=2458)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    trace = load_event_trace(args.events)
    blocks, _, _, _ = flatten_accesses(trace)
    frequencies = np.bincount(blocks, minlength=trace.num_expert_blocks)
    base = args.capacity_blocks // trace.num_layers
    remainder = args.capacity_blocks % trace.num_layers
    resident: list[int] = []
    quotas: list[int] = []
    for layer in range(trace.num_layers):
        quota = base + int(layer < remainder)
        quotas.append(quota)
        start = layer * trace.num_experts_per_layer
        end = start + trace.num_experts_per_layer
        local = np.arange(start, end)
        order = np.lexsort((local, -frequencies[start:end]))
        resident.extend(int(value) for value in local[order[:quota]])
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "frozen_from_discovery_only",
        "source_event_root": str(args.events.resolve()),
        "source_manifest_sha256": sha256_file(args.events / "manifest.json"),
        "capacity_blocks": args.capacity_blocks,
        "cache_scope": "per_layer_equal_quota",
        "layer_quotas": quotas,
        "resident_blocks": resident,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)


if __name__ == "__main__":
    main()
