#!/usr/bin/env python3
"""Build the small, reproducible artifacts that block the arXiv draft.

This script intentionally operates only on already-collected event traces.  It
does not collect routes or require a model forward pass.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from moe_controller.events import EventTrace, PHASE_DECODE, load_event_trace
from moe_controller.simulation import simulate, simulate_event_atomic


CAUSAL_POLICIES = ("lru", "lfu", "lfru", "least_stale")
FIGURE_POLICIES = (*CAUSAL_POLICIES, "belady", "static")
DEFAULT_TIE_SEEDS = (11, 23, 47, 89, 131)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    toy = subparsers.add_parser("toy-trace")
    toy.add_argument("--output", type=Path, required=True)

    figure = subparsers.add_parser("figure-one")
    figure.add_argument("events", type=Path)
    figure.add_argument("--output", type=Path, required=True)
    figure.add_argument("--rho", type=float, default=0.40)
    figure.add_argument("--tie-seed", type=int, default=20260729)

    uncertainty = subparsers.add_parser("tie-seed-sensitivity")
    uncertainty.add_argument("events", type=Path, nargs="+")
    uncertainty.add_argument("--output", type=Path, required=True)
    uncertainty.add_argument("--rho", type=float, default=0.40)
    uncertainty.add_argument(
        "--tie-seeds",
        type=lambda value: tuple(int(item) for item in value.split(",")),
        default=DEFAULT_TIE_SEEDS,
    )

    regime = subparsers.add_parser("regime-ablation")
    regime.add_argument("events", type=Path)
    regime.add_argument("--output", type=Path, required=True)
    regime.add_argument("--rho", type=float, default=0.40)
    regime.add_argument("--permutations", type=int, default=20)
    regime.add_argument("--seed", type=int, default=20260801)
    regime.add_argument("--tie-seed", type=int, default=20260729)
    return parser.parse_args()


def _ensure_new_directory(path: Path) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite {path}.")
    path.mkdir(parents=True)


def _toy_trace() -> EventTrace:
    # Five scheduler steps, three layers, four experts/layer.  The same local
    # sequence is used in every layer so every row is hand-checkable.
    local_sets = (
        (0, 1),
        (0, 2),
        (0, 1),
        (0, 3),
        (0, 1),
    )
    offsets = [0]
    expert_ids: list[int] = []
    scheduler_steps: list[int] = []
    layer_ids: list[int] = []
    for step, local in enumerate(local_sets):
        for layer in range(3):
            scheduler_steps.append(step)
            layer_ids.append(layer)
            expert_ids.extend(local)
            offsets.append(len(expert_ids))
    num_events = len(scheduler_steps)
    return EventTrace(
        root=Path("."),
        manifest={
            "schema_version": 1,
            "model": {"num_layers": 3, "num_experts": 4},
        },
        request_indices=np.zeros(num_events, dtype=np.int32),
        scheduler_steps=np.asarray(scheduler_steps, dtype=np.int32),
        forward_cycles=np.asarray(scheduler_steps, dtype=np.int32),
        phases=np.full(num_events, PHASE_DECODE, dtype=np.uint8),
        layer_ids=np.asarray(layer_ids, dtype=np.int16),
        token_counts=np.ones(num_events, dtype=np.int32),
        offsets=np.asarray(offsets, dtype=np.int64),
        expert_ids=np.asarray(expert_ids, dtype=np.int16),
        assignment_counts=np.ones(len(expert_ids), dtype=np.int32),
        gate_mass=np.ones(len(expert_ids), dtype=np.float32),
    )


def _run_toy_trace(output: Path) -> None:
    _ensure_new_directory(output)
    trace = _toy_trace()
    trace.validate()
    result = simulate_event_atomic(
        trace,
        policy="lru",
        capacity_blocks=6,
        cache_scope="per_layer",
        tie_seed=7,
        include_event_misses=True,
    )
    expected_event_misses = (2, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1)
    if result.event_misses != expected_event_misses:
        raise AssertionError((result.event_misses, expected_event_misses))
    if (result.hits, result.misses) != (12, 18):
        raise AssertionError((result.hits, result.misses))

    rows: list[dict] = []
    for event_index in range(trace.num_events):
        event = trace.event(event_index)
        rows.append(
            {
                "event_index": event_index,
                "scheduler_step": event.scheduler_step,
                "layer": event.layer_id,
                "requested_experts": " ".join(
                    str(int(value)) for value in event.expert_ids
                ),
                "misses": expected_event_misses[event_index],
                "hits": len(event.expert_ids) - expected_event_misses[event_index],
            }
        )
    with (output / "events.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    markdown = [
        "# Event-atomic toy trace",
        "",
        "This executable example contains 3 layers, 4 experts per layer, and 5 scheduler steps.",
        "Each layer has capacity 2; the total cache capacity is 6 blocks.",
        "LRU decisions occur only after every expert in an event has been served.",
        "",
        "| step | layer | requested local experts | hits | misses |",
        "|---:|---:|---|---:|---:|",
    ]
    for row in rows:
        markdown.append(
            f"| {row['scheduler_step']} | {row['layer']} | "
            f"{{{row['requested_experts'].replace(' ', ', ')}}} | "
            f"{row['hits']} | {row['misses']} |"
        )
    markdown.extend(
        (
            "",
            "Hand-check: step 0 cold-loads two experts per layer (6 misses). "
            "At each later step, expert 0 remains resident and the second expert changes, "
            "giving one hit and one miss per layer (12 further misses).",
            "",
            "Total: 30 accesses, 12 hits, 18 misses.",
            "",
        )
    )
    (output / "README.md").write_text("\n".join(markdown), encoding="utf-8")
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "purpose": "human-checkable executable specification of event-atomic replay",
        "model": {"num_layers": 3, "num_experts_per_layer": 4},
        "scheduler_steps": 5,
        "cache_scope": "per_layer",
        "capacity_blocks_total": 6,
        "capacity_blocks_per_layer": 2,
        "policy": "lru",
        "tie_seed": 7,
        "expected": asdict(result),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _capacity(trace: EventTrace, rho: float) -> int:
    return int(round(trace.num_expert_blocks * rho))


def _effective_miss(result, logical: int) -> float:
    return result.transferred_blocks / logical


def _figure_svg(rows: list[dict]) -> str:
    width, height = 980, 510
    left, right, top, bottom = 95, 35, 55, 95
    plot_w = width - left - right
    plot_h = height - top - bottom
    maximum = max(float(row["effective_miss_percent"]) for row in rows)
    y_max = max(30.0, np.ceil(maximum / 5.0) * 5.0)
    policies = [row["policy"] for row in rows if row["semantics"] == "sequential"]
    sequential = {row["policy"]: row for row in rows if row["semantics"] == "sequential"}
    atomic = {row["policy"]: row for row in rows if row["semantics"] == "event_atomic"}
    group_w = plot_w / len(policies)
    bar_w = group_w * 0.28

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<style>text{font-family:Arial,Helvetica,sans-serif;fill:#202124}.axis{stroke:#5f6368;stroke-width:1}.grid{stroke:#dadce0;stroke-width:1}.label{font-size:13px}.small{font-size:11px}.title{font-size:20px;font-weight:700}</style>',
        f'<text class="title" x="{left}" y="28">Replay semantics selectively changes policy rankings</text>',
    ]
    for tick in np.arange(0, y_max + 0.1, 5.0):
        y = top + plot_h * (1.0 - tick / y_max)
        parts.append(f'<line class="grid" x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}"/>')
        parts.append(f'<text class="small" x="{left - 12}" y="{y + 4:.1f}" text-anchor="end">{tick:.0f}%</text>')
    parts.append(f'<line class="axis" x1="{left}" y1="{top}" x2="{left}" y2="{top + plot_h}"/>')
    parts.append(f'<line class="axis" x1="{left}" y1="{top + plot_h}" x2="{left + plot_w}" y2="{top + plot_h}"/>')
    for index, policy in enumerate(policies):
        center = left + group_w * (index + 0.5)
        for offset, source, color in ((-bar_w / 1.8, sequential, "#d93025"), (bar_w / 1.8, atomic, "#188038")):
            value = float(source[policy]["effective_miss_percent"])
            bar_h = plot_h * value / y_max
            x = center + offset - bar_w / 2
            y = top + plot_h - bar_h
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" fill="{color}"/>')
            parts.append(f'<text class="small" x="{x + bar_w / 2:.1f}" y="{y - 5:.1f}" text-anchor="middle">{value:.2f}</text>')
        display_policy = "static*" if policy == "static" else policy
        parts.append(f'<text class="label" x="{center:.1f}" y="{top + plot_h + 24}" text-anchor="middle">{display_policy}</text>')
    legend_y = height - 34
    parts.extend(
        (
            f'<rect x="{left}" y="{legend_y - 11}" width="14" height="14" fill="#d93025"/>',
            f'<text class="label" x="{left + 21}" y="{legend_y}">sequential expert-ID replay</text>',
            f'<rect x="{left + 260}" y="{legend_y - 11}" width="14" height="14" fill="#188038"/>',
            f'<text class="label" x="{left + 281}" y="{legend_y}">event-atomic replay</text>',
            f'<text class="small" x="{left + 570}" y="{legend_y}">* same-trace diagnostic</text>',
            f'<text class="label" transform="translate(22 {top + plot_h / 2}) rotate(-90)" text-anchor="middle">effective transfer fraction</text>',
            '</svg>',
        )
    )
    return "\n".join(parts) + "\n"


def _run_figure_one(events: Path, output: Path, rho: float, tie_seed: int) -> None:
    _ensure_new_directory(output)
    trace = load_event_trace(events)
    capacity = _capacity(trace, rho)
    logical = int(trace.assignment_counts.sum())
    rows: list[dict] = []
    for policy in FIGURE_POLICIES:
        sequential = simulate(
            trace,
            policy=policy,
            capacity_blocks=capacity,
            cache_scope="per_layer",
        )
        atomic = simulate_event_atomic(
            trace,
            policy=policy,
            capacity_blocks=capacity,
            cache_scope="per_layer",
            tie_seed=tie_seed,
        )
        for semantics, result in (("sequential", sequential), ("event_atomic", atomic)):
            rows.append(
                {
                    "policy": policy,
                    "semantics": semantics,
                    "miss_ratio": result.miss_ratio,
                    "effective_miss_fraction": _effective_miss(result, logical),
                    "effective_miss_percent": 100.0 * _effective_miss(result, logical),
                    "transferred_blocks": result.transferred_blocks,
                }
            )
    with (output / "figure-1-data.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output / "figure-1.svg").write_text(_figure_svg(rows), encoding="utf-8")
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "single_variable_design": True,
        "events": str(events.resolve()),
        "rho": rho,
        "capacity_blocks": capacity,
        "cache_scope": "per_layer",
        "tie_seed": tie_seed,
        "only_changed_variable": "replay semantics",
        "static_protocol": "same_trace_diagnostic_not_deployable",
        "artifacts": ["figure-1-data.csv", "figure-1.svg"],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _run_tie_seed_sensitivity(
    event_roots: list[Path],
    output: Path,
    rho: float,
    tie_seeds: tuple[int, ...],
) -> None:
    _ensure_new_directory(output)
    rows: list[dict] = []
    for root in event_roots:
        trace = load_event_trace(root)
        capacity = _capacity(trace, rho)
        logical = int(trace.assignment_counts.sum())
        for tie_seed in tie_seeds:
            results = {
                policy: simulate_event_atomic(
                    trace,
                    policy=policy,
                    capacity_blocks=capacity,
                    cache_scope="per_layer",
                    tie_seed=tie_seed,
                )
                for policy in (*CAUSAL_POLICIES, "belady")
            }
            causal_policy = min(
                CAUSAL_POLICIES,
                key=lambda name: results[name].transferred_blocks,
            )
            causal = _effective_miss(results[causal_policy], logical)
            belady = _effective_miss(results["belady"], logical)
            rows.append(
                {
                    "event_root": root.name,
                    "tie_seed": tie_seed,
                    "best_causal_policy": causal_policy,
                    "best_causal_effective_miss": causal,
                    "belady_effective_miss": belady,
                    "recoverable_gap": (causal - belady) / causal,
                }
            )
    with (output / "tie-seed-results.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summaries: list[dict] = []
    for root in event_roots:
        values = np.asarray(
            [row["recoverable_gap"] for row in rows if row["event_root"] == root.name],
            dtype=np.float64,
        )
        summaries.append(
            {
                "event_root": root.name,
                "num_tie_seeds": len(values),
                "gap_min": float(values.min()),
                "gap_median": float(np.median(values)),
                "gap_max": float(values.max()),
                "gap_std": float(values.std(ddof=1)) if len(values) > 1 else 0.0,
            }
        )
    with (output / "tie-seed-summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "complete",
                "method": "event-atomic replay sensitivity over frozen tie-break seeds",
                "rho": rho,
                "cache_scope": "per_layer",
                "tie_seeds": list(tie_seeds),
                "event_roots": [str(path.resolve()) for path in event_roots],
                "summary": summaries,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _permute_step_groups(trace: EventTrace, order: np.ndarray) -> EventTrace:
    unique_steps = np.unique(trace.scheduler_steps)
    if sorted(int(value) for value in order) != list(range(len(unique_steps))):
        raise ValueError("order must be a permutation of scheduler-step indices")
    selected_events: list[int] = []
    remapped_steps: list[int] = []
    for new_step, old_step_index in enumerate(order):
        old_step = unique_steps[int(old_step_index)]
        indices = np.flatnonzero(trace.scheduler_steps == old_step)
        selected_events.extend(int(value) for value in indices)
        remapped_steps.extend([new_step] * len(indices))
    selected = np.asarray(selected_events, dtype=np.int64)
    lengths = np.diff(trace.offsets)[selected].astype(np.int64, copy=False)
    access_parts = [
        np.arange(int(trace.offsets[index]), int(trace.offsets[index + 1]), dtype=np.int64)
        for index in selected
    ]
    accesses = np.concatenate(access_parts) if access_parts else np.empty(0, dtype=np.int64)
    offsets = np.concatenate((np.asarray([0], dtype=np.int64), np.cumsum(lengths)))
    permuted = EventTrace(
        root=trace.root,
        manifest=trace.manifest,
        request_indices=trace.request_indices[selected],
        scheduler_steps=np.asarray(remapped_steps, dtype=np.int32),
        forward_cycles=np.asarray(remapped_steps, dtype=np.int32),
        phases=trace.phases[selected],
        layer_ids=trace.layer_ids[selected],
        token_counts=trace.token_counts[selected],
        offsets=offsets,
        expert_ids=trace.expert_ids[accesses],
        assignment_counts=trace.assignment_counts[accesses],
        gate_mass=trace.gate_mass[accesses],
    )
    permuted.validate()
    return permuted


def _trace_regime_metrics(trace: EventTrace, capacity: int) -> tuple[float, float]:
    lengths = np.diff(trace.offsets).astype(np.float64)
    per_layer_capacity = capacity / trace.num_layers
    return float(lengths.mean() / per_layer_capacity), float(lengths.std())


def _evaluate_regime_trace(trace: EventTrace, capacity: int, tie_seed: int) -> dict:
    logical = int(trace.assignment_counts.sum())
    results = {
        policy: simulate_event_atomic(
            trace,
            policy=policy,
            capacity_blocks=capacity,
            cache_scope="per_layer",
            tie_seed=tie_seed,
        )
        for policy in (*CAUSAL_POLICIES, "belady")
    }
    best = min(CAUSAL_POLICIES, key=lambda name: results[name].transferred_blocks)
    causal = _effective_miss(results[best], logical)
    belady = _effective_miss(results["belady"], logical)
    ratio, union_std = _trace_regime_metrics(trace, capacity)
    return {
        "best_causal_policy": best,
        "best_causal_effective_miss": causal,
        "belady_effective_miss": belady,
        "recoverable_gap": (causal - belady) / causal,
        "mean_union_to_capacity": ratio,
        "event_union_std": union_std,
    }


def _run_regime_ablation(
    events: Path,
    output: Path,
    rho: float,
    permutations: int,
    seed: int,
    tie_seed: int,
) -> None:
    _ensure_new_directory(output)
    trace = load_event_trace(events)
    capacity = _capacity(trace, rho)
    rng = np.random.default_rng(seed)
    num_steps = len(np.unique(trace.scheduler_steps))
    rows = [{"condition": "original", "permutation_seed": "", **_evaluate_regime_trace(trace, capacity, tie_seed)}]
    for index in range(permutations):
        order = rng.permutation(num_steps)
        permuted = _permute_step_groups(trace, order)
        rows.append(
            {
                "condition": f"step_permutation_{index:02d}",
                "permutation_seed": seed,
                **_evaluate_regime_trace(permuted, capacity, tie_seed),
            }
        )
    ratios = np.asarray([row["mean_union_to_capacity"] for row in rows])
    if not np.allclose(ratios, ratios[0], rtol=0.0, atol=1e-12):
        raise AssertionError("Step permutation changed union/cache regime")
    with (output / "regime-ablation.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    gaps = np.asarray([row["recoverable_gap"] for row in rows[1:]])
    causal = np.asarray([row["best_causal_effective_miss"] for row in rows[1:]])
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "purpose": "show union/cache is necessary for regime reporting but not sufficient",
        "controlled_invariant": "multiset of event expert sets and therefore union/cache distribution",
        "changed_variable": "scheduler-step order and therefore temporal reuse",
        "events": str(events.resolve()),
        "rho": rho,
        "capacity_blocks": capacity,
        "permutations": permutations,
        "seed": seed,
        "tie_seed": tie_seed,
        "original": rows[0],
        "permuted_gap_range": [float(gaps.min()), float(gaps.max())],
        "permuted_causal_miss_range": [float(causal.min()), float(causal.max())],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    args = _parse_args()
    if args.command == "toy-trace":
        _run_toy_trace(args.output)
    elif args.command == "figure-one":
        _run_figure_one(args.events, args.output, args.rho, args.tie_seed)
    elif args.command == "tie-seed-sensitivity":
        _run_tie_seed_sensitivity(args.events, args.output, args.rho, args.tie_seeds)
    elif args.command == "regime-ablation":
        _run_regime_ablation(
            args.events,
            args.output,
            args.rho,
            args.permutations,
            args.seed,
            args.tie_seed,
        )
    else:
        raise AssertionError(args.command)


if __name__ == "__main__":
    main()
