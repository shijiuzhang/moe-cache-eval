#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moe_controller.events import load_event_trace, sha256_file


K3_LOGICAL_BYTES_PER_TOKEN = 25.83e9
DEFAULT_BANDWIDTHS_GBPS = (100.0, 150.0, 200.0)
DEFAULT_INTERACTIVE_RATES = (10.0, 15.0, 20.0)
DEFAULT_AGGREGATE_RATES = (20.0, 40.0, 80.0)


def model_name(model_label: str) -> str:
    for candidate in ("granite", "olmoe", "qwen3"):
        if candidate in model_label.lower():
            return candidate
    return model_label


def expected_union(num_experts: int, top_k: int, batch_size: int) -> float:
    return num_experts * (
        1.0 - (1.0 - top_k / num_experts) ** batch_size
    )


def critical_batch_size(
    num_experts: int,
    top_k: int,
    resident_fraction: float,
) -> float:
    return math.log(1.0 - resident_fraction) / math.log(
        1.0 - top_k / num_experts
    )


def load_gap_rows(paths: Iterable[Path]) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                rows.append(row)
    if not rows:
        raise ValueError("No baseline rows were loaded.")
    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"Cannot write empty artifact: {path.name}.")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def build_envelope_rows(
    gap_rows: Iterable[dict],
    *,
    bandwidths_gbps: Iterable[float] = DEFAULT_BANDWIDTHS_GBPS,
) -> list[dict]:
    rows: list[dict] = []
    for source in gap_rows:
        batch_size = int(source["batch_size"])
        variants = (
            (
                "best_causal",
                source["best_causal"],
                float(source["best_causal_effective_miss_fraction"]),
            ),
            (
                "belady",
                "belady",
                float(source["belady_effective_miss_fraction"]),
            ),
        )
        for policy_kind, policy, miss_fraction in variants:
            for bandwidth_gbps in bandwidths_gbps:
                aggregate_tps = (
                    bandwidth_gbps * 1e9
                    / (K3_LOGICAL_BYTES_PER_TOKEN * miss_fraction)
                    if miss_fraction
                    else math.inf
                )
                rows.append(
                    {
                        "model": model_name(source["model_label"]),
                        "batch_size": batch_size,
                        "cache_scope": source["cache_scope"],
                        "rho": float(source["rho"]),
                        "policy_kind": policy_kind,
                        "policy": policy,
                        "effective_miss_fraction": miss_fraction,
                        "projected_k3_bytes_per_output_token": (
                            K3_LOGICAL_BYTES_PER_TOKEN * miss_fraction
                        ),
                        "bandwidth_gbps": bandwidth_gbps,
                        "aggregate_tps_ceiling": aggregate_tps,
                        "per_user_tps_ceiling": aggregate_tps / batch_size,
                        "projection_warning": (
                            "local m_eff mapped to K3 bytes; not K3 trace"
                        ),
                    }
                )
    return rows


def build_sla_rows(
    gap_rows: Iterable[dict],
    *,
    interactive_rates: Iterable[float] = DEFAULT_INTERACTIVE_RATES,
    aggregate_rates: Iterable[float] = DEFAULT_AGGREGATE_RATES,
    bandwidths_gbps: Iterable[float] = DEFAULT_BANDWIDTHS_GBPS,
) -> list[dict]:
    rows: list[dict] = []
    bandwidths = tuple(float(value) for value in bandwidths_gbps)
    for source in gap_rows:
        batch_size = int(source["batch_size"])
        variants = (
            (
                "best_causal",
                source["best_causal"],
                float(source["best_causal_effective_miss_fraction"]),
            ),
            (
                "belady",
                "belady",
                float(source["belady_effective_miss_fraction"]),
            ),
        )
        for policy_kind, policy, miss_fraction in variants:
            for rate in interactive_rates:
                aggregate_rate = batch_size * float(rate)
                required = (
                    K3_LOGICAL_BYTES_PER_TOKEN
                    * miss_fraction
                    * aggregate_rate
                    / 1e9
                )
                row = {
                    "model": model_name(source["model_label"]),
                    "batch_size": batch_size,
                    "cache_scope": source["cache_scope"],
                    "rho": float(source["rho"]),
                    "policy_kind": policy_kind,
                    "policy": policy,
                    "sla_class": "human_interactive",
                    "sla_rate_semantics": "per_active_user_tps",
                    "sla_rate": float(rate),
                    "aggregate_tps": aggregate_rate,
                    "effective_miss_fraction": miss_fraction,
                    "required_bandwidth_gbps": required,
                }
                for bandwidth in bandwidths:
                    row[f"meets_{bandwidth:g}gbps"] = required <= bandwidth
                rows.append(row)
            for rate in aggregate_rates:
                aggregate_rate = float(rate)
                required = (
                    K3_LOGICAL_BYTES_PER_TOKEN
                    * miss_fraction
                    * aggregate_rate
                    / 1e9
                )
                row = {
                    "model": model_name(source["model_label"]),
                    "batch_size": batch_size,
                    "cache_scope": source["cache_scope"],
                    "rho": float(source["rho"]),
                    "policy_kind": policy_kind,
                    "policy": policy,
                    "sla_class": "agent_or_batch",
                    "sla_rate_semantics": "aggregate_tps",
                    "sla_rate": aggregate_rate,
                    "aggregate_tps": aggregate_rate,
                    "effective_miss_fraction": miss_fraction,
                    "required_bandwidth_gbps": required,
                }
                for bandwidth in bandwidths:
                    row[f"meets_{bandwidth:g}gbps"] = required <= bandwidth
                rows.append(row)
    return rows


def build_regime_rows(
    event_roots: Iterable[Path],
    *,
    rho: float = 0.40,
) -> list[dict]:
    rows: list[dict] = []
    for root in event_roots:
        trace = load_event_trace(root)
        capacity = round(trace.num_expert_blocks * rho)
        base, remainder = divmod(capacity, trace.num_layers)
        layer_capacities = np.asarray(
            [
                base + int(layer_id < remainder)
                for layer_id in trace.layer_ids
            ],
            dtype=np.int64,
        )
        union_sizes = np.diff(trace.offsets).astype(np.int64, copy=False)
        logical = int(
            trace.manifest["counts"][
                "logical_expert_assignments_before_dedup"
            ]
        )
        forced_excess = np.maximum(union_sizes - layer_capacities, 0)
        rows.append(
            {
                "model": model_name(root.name),
                "batch_size": int(
                    trace.manifest["conversion"]["batch_size"]
                ),
                "num_experts": trace.num_experts_per_layer,
                "top_k": int(trace.manifest["model"]["top_k"]),
                "rho": rho,
                "mean_layer_capacity": capacity / trace.num_layers,
                "min_layer_capacity": int(layer_capacities.min()),
                "max_layer_capacity": int(layer_capacities.max()),
                "mean_union": float(union_sizes.mean()),
                "median_union": float(np.median(union_sizes)),
                "p95_union": float(
                    np.quantile(union_sizes, 0.95, method="higher")
                ),
                "mean_union_to_capacity_ratio": float(
                    np.mean(union_sizes / layer_capacities)
                ),
                "event_over_capacity_fraction": float(
                    np.mean(union_sizes > layer_capacities)
                ),
                "forced_excess_fraction_of_logical": (
                    float(forced_excess.sum() / logical) if logical else 0.0
                ),
                "event_root": str(root.resolve()),
            }
        )
    return rows


def build_reference_regime_rows(
    *,
    rho: float = 0.40,
    batches: Iterable[int] = (1, 2, 4, 8, 16, 24, 28, 29, 30, 32),
) -> list[dict]:
    rows: list[dict] = []
    for name, num_experts, top_k in (
        ("qwen3_30b_a3b", 128, 8),
        ("k3", 896, 16),
    ):
        capacity = rho * num_experts
        critical = critical_batch_size(num_experts, top_k, rho)
        for batch_size in batches:
            union = expected_union(num_experts, top_k, batch_size)
            rows.append(
                {
                    "model": name,
                    "num_experts": num_experts,
                    "top_k": top_k,
                    "rho": rho,
                    "batch_size": int(batch_size),
                    "expected_union_uniform_null": union,
                    "continuous_layer_capacity": capacity,
                    "union_to_capacity_ratio": union / capacity,
                    "continuous_critical_batch_size": critical,
                    "warning": (
                        "uniform independent routing null; not a trace result"
                    ),
                }
            )
    return rows


def _svg_polyline(
    points: list[tuple[float, float]],
    *,
    color: str,
    dashed: bool,
) -> str:
    coordinates = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    dash = ' stroke-dasharray="7 5"' if dashed else ""
    return (
        f'<polyline points="{coordinates}" fill="none" stroke="{color}" '
        f'stroke-width="2.2"{dash}/>'
    )


def write_pareto_svg(
    path: Path,
    envelope_rows: Iterable[dict],
    *,
    bandwidth_gbps: float = 150.0,
    cache_scope: str = "per_layer",
) -> None:
    selected = [
        row
        for row in envelope_rows
        if row["bandwidth_gbps"] == bandwidth_gbps
        and row["cache_scope"] == cache_scope
    ]
    if not selected:
        raise ValueError("No rows match the requested bandwidth and scope.")
    models = tuple(sorted({str(row["model"]) for row in selected}))
    batches = tuple(sorted({int(row["batch_size"]) for row in selected}))
    rhos = tuple(sorted({float(row["rho"]) for row in selected}))
    palette = ("#d95f02", "#7570b3", "#1b9e77", "#e7298a")
    colors = {
        rho: palette[index % len(palette)] for index, rho in enumerate(rhos)
    }
    height = 520
    panel_width = 400
    panel_gap = 80
    lefts = tuple(70 + index * (panel_width + panel_gap) for index in range(len(models)))
    width = lefts[-1] + panel_width + 30
    top, bottom = 50, 430
    y_max = 60.0
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<style>text{font-family:-apple-system,BlinkMacSystemFont,'
        '"Segoe UI",sans-serif;fill:#222}.small{font-size:12px}'
        '.axis{stroke:#444;stroke-width:1}.grid{stroke:#ddd;stroke-width:1}'
        '.title{font-size:17px;font-weight:600}</style>',
        f'<text x="{width / 2:.1f}" y="24" text-anchor="middle" class="title">'
        "Conditional K3 per-user throughput envelope — 150 GB/s, "
        "per-layer cache</text>",
    ]
    for panel, (model, left) in enumerate(zip(models, lefts)):
        right = left + panel_width
        parts.extend(
            [
                f'<line x1="{left}" y1="{top}" x2="{left}" '
                f'y2="{bottom}" class="axis"/>',
                f'<line x1="{left}" y1="{bottom}" x2="{right}" '
                f'y2="{bottom}" class="axis"/>',
                f'<text x="{(left + right) / 2}" y="46" '
                f'text-anchor="middle" class="title">{model}</text>',
            ]
        )
        for tick in (0, 10, 20, 30, 40, 50, 60):
            y = bottom - (tick / y_max) * (bottom - top)
            parts.append(
                f'<line x1="{left}" y1="{y:.1f}" x2="{right}" '
                f'y2="{y:.1f}" class="grid"/>'
            )
            if panel == 0:
                parts.append(
                    f'<text x="{left - 8}" y="{y + 4:.1f}" '
                    f'text-anchor="end" class="small">{tick}</text>'
                )
        x_denominator = max(len(batches) - 1, 1)
        for index, batch in enumerate(batches):
            x = left + index * panel_width / x_denominator
            parts.append(
                f'<text x="{x:.1f}" y="{bottom + 20}" '
                f'text-anchor="middle" class="small">{batch}</text>'
            )
        for rho in rhos:
            for policy_kind in ("best_causal", "belady"):
                lookup = {
                    int(row["batch_size"]): row
                    for row in selected
                    if row["model"] == model
                    and float(row["rho"]) == rho
                    and row["policy_kind"] == policy_kind
                }
                points = []
                for index, batch in enumerate(batches):
                    row = lookup.get(batch)
                    if row is None:
                        continue
                    x = left + index * panel_width / x_denominator
                    value = min(float(row["per_user_tps_ceiling"]), y_max)
                    y = bottom - (value / y_max) * (bottom - top)
                    points.append((x, y))
                parts.append(
                    _svg_polyline(
                        points,
                        color=colors[rho],
                        dashed=policy_kind == "belady",
                    )
                )
        parts.append(
            f'<text x="{(left + right) / 2}" y="{bottom + 42}" '
            'text-anchor="middle" class="small">active decode streams B</text>'
        )
    parts.extend(
        [
            '<text x="18" y="255" transform="rotate(-90 18 255)" '
            'text-anchor="middle" class="small">per-user token/s ceiling</text>',
            '<text x="70" y="502" class="small">'
            "rho colors follow ascending cache fraction; "
            "solid = best causal, dashed = Belady</text>",
            "</svg>",
        ]
    )
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build conditional K3 operating envelopes from decode baselines."
    )
    parser.add_argument(
        "--gap-csv",
        type=Path,
        action="append",
        required=True,
        help="Repeat for each belady-gap-and-budget.csv artifact.",
    )
    parser.add_argument(
        "--events",
        type=Path,
        action="append",
        default=[],
        help="Optional decode event roots for union/cache regime diagnostics.",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output.exists():
        raise FileExistsError(f"Output exists: {args.output}.")
    args.output.mkdir(parents=True)
    gap_rows = load_gap_rows(args.gap_csv)
    envelope_rows = build_envelope_rows(gap_rows)
    sla_rows = build_sla_rows(gap_rows)
    regime_rows = build_regime_rows(args.events)
    reference_rows = build_reference_regime_rows()
    artifacts: dict[str, str] = {}
    for filename, rows in (
        ("operating-envelope.csv", envelope_rows),
        ("sla-sensitivity.csv", sla_rows),
        ("observed-union-cache-regimes.csv", regime_rows),
        ("reference-union-cache-regimes.csv", reference_rows),
    ):
        write_csv(args.output / filename, rows)
        artifacts[filename] = sha256_file(args.output / filename)
    svg_path = args.output / "per-user-throughput-envelope-150gbps.svg"
    write_pareto_svg(svg_path, envelope_rows)
    artifacts[svg_path.name] = sha256_file(svg_path)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "projection": {
            "k3_logical_bytes_per_output_token": K3_LOGICAL_BYTES_PER_TOKEN,
            "warning": (
                "Operating envelope maps local m_eff to K3 logical bytes. "
                "It is not a K3 trace or performance claim."
            ),
        },
        "inputs": [
            {"path": str(path.resolve()), "sha256": sha256_file(path)}
            for path in args.gap_csv
        ],
        "event_inputs": [
            {
                "root": str(root.resolve()),
                "manifest_sha256": sha256_file(root / "manifest.json"),
            }
            for root in args.events
        ],
        "artifacts": artifacts,
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(args.output)


if __name__ == "__main__":
    main()
