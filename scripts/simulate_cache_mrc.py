#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moe_controller.events import load_event_trace
from moe_controller.simulation import (
    SUPPORTED_POLICIES,
    capacity_blocks_from_fractions,
    simulate,
)


def parse_csv_floats(value: str) -> list[float]:
    values = [float(item) for item in value.split(",") if item.strip()]
    if not values or any(item <= 0 or item > 1 for item in values):
        raise argparse.ArgumentTypeError(
            "Capacity fractions must be comma-separated values in (0, 1]."
        )
    return values


def parse_csv_strings(value: str) -> list[str]:
    values = [item.strip() for item in value.split(",") if item.strip()]
    unknown = sorted(set(values) - set(SUPPORTED_POLICIES))
    if unknown:
        raise argparse.ArgumentTypeError(f"Unknown policies: {unknown}")
    return values


def parse_csv_scopes(value: str) -> list[str]:
    values = [item.strip() for item in value.split(",") if item.strip()]
    unknown = sorted(set(values) - {"global", "per_layer"})
    if not values or unknown:
        raise argparse.ArgumentTypeError(
            f"Cache scopes must be global/per_layer; unknown: {unknown}"
        )
    return values


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay MoE expert cache policies and emit an MRC table."
    )
    parser.add_argument("events", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--capacities",
        type=parse_csv_floats,
        default=parse_csv_floats("0.05,0.10,0.20,0.30,0.40,0.50,0.60"),
    )
    parser.add_argument(
        "--policies",
        type=parse_csv_strings,
        default=list(SUPPORTED_POLICIES),
    )
    parser.add_argument(
        "--scopes",
        type=parse_csv_scopes,
        default=["global", "per_layer"],
        help="Comma-separated cache scopes (default: global,per_layer).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    result_path = args.output / "mrc.csv"
    manifest_path = args.output / "manifest.json"
    if result_path.exists() or manifest_path.exists():
        raise FileExistsError(
            f"Refusing to overwrite an existing simulation: {args.output}"
        )
    trace = load_event_trace(args.events)
    capacities = capacity_blocks_from_fractions(trace, args.capacities)
    rows: list[dict] = []
    for scope in args.scopes:
        for capacity in capacities:
            for policy in args.policies:
                result = simulate(
                    trace,
                    policy=policy,
                    capacity_blocks=capacity,
                    cache_scope=scope,
                )
                row = result.to_dict()
                rows.append(row)
                print(
                    f"{scope:9s} {policy:12s} C={capacity:4d} "
                    f"miss={result.miss_ratio:.4f} "
                    f"blocks/token={result.blocks_per_model_token:.4f}"
                )
    with result_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "events_root": str(args.events.resolve()),
        "events_manifest_sha256": sha256_file(args.events / "manifest.json"),
        "policies": args.policies,
        "cache_scopes": args.scopes,
        "requested_capacity_fractions": args.capacities,
        "realized_capacity_blocks": capacities,
        "semantics": {
            "strict_lossless": True,
            "prefetch": False,
            "block_size": "uniform_normalized_expert_block",
            "access_order": trace.manifest["conversion"][
                "expert_access_order"
            ],
            "static_cache": "offline frequency, preload counted once",
            "dynamic_caches": "cold start",
            "belady": "offline block-level oracle with bypass admission",
            "per_layer_capacity": (
                "equal integer quota; remainder assigned to low layer ids"
            ),
        },
        "artifacts": {
            "mrc": {
                "path": result_path.name,
                "sha256": sha256_file(result_path),
                "bytes": result_path.stat().st_size,
            }
        },
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
