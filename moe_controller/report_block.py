"""Minimal reporting block (paper Appendix B.1 / §10.5) as a fillable artifact.

Every one of the 30 fields carries exactly one value class:

* ``computed`` — derived by a tool; its ``source`` must cite at least one
  SHA-256 of the file it was computed from;
* ``DECLARE`` — only the original authors can state it; it cannot be derived;
* ``NA`` — the information does not exist in the data (the reason is required);
* ``NR`` — not reported in the public text (paper-only mode default);
* ``paper`` — stated in the public text (paper-only mode; ``source`` must cite
  the section or sentence).

Regime fields are computed from an event trace with the same definitions as the
paper's regime tables: per-layer integer quotas from the §2.3 capacity rule,
``r(s,l) = |E(s,l)| / c_l`` averaged over events, p95 with the "higher" rule,
and the fraction of events whose union exceeds its quota.

Usage::

    python -m moe_controller.report_block --events TRACE_DIR --rho 0.10 \\
        --scope per_layer --facts facts.json --out-md block.md --out-json block.json
    python -m moe_controller.report_block --paper-only \\
        --paper "concurrency=1@Abstract" --out-md paper_only.md --out-json paper_only.json
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from .events import EventTrace, load_event_trace, sha256_file
from .simulation import capacity_blocks_from_fractions

# (section, key, label) in Appendix B.1 order; labels are verbatim.
FIELDS: tuple[tuple[str, str, str], ...] = (
    ("Execution model", "event_unit", "event unit"),
    ("Execution model", "retention_decision", "retention decision"),
    ("Execution model", "intra_event_order", "intra-event order (if immediate)"),
    ("Execution model", "conformance_trace", "conformance trace"),
    ("Workload", "templates_per_category", "templates per category"),
    ("Workload", "distinct_prompt_heads_finals", "distinct prompt heads / finals"),
    ("Workload", "chat_template_applied", "chat template applied"),
    ("Workload", "decode_steps_recorded", "decode steps recorded"),
    ("Workload", "position_locked_cohorts", "position-locked cohorts"),
    ("Workload", "unique_generated_sequences", "unique generated sequences"),
    ("Workload", "positional_token_agreement", "positional token agreement"),
    ("Workload", "expert_jaccard_low_text_overlap", "expert Jaccard | low-text-overlap"),
    ("Workload", "effect_stable_across_position_bands", "effect stable across position bands"),
    ("Regime", "experts_topk_layers", "experts N, top-k, layers"),
    ("Regime", "residency_fraction", "residency fraction rho"),
    ("Regime", "cache_scope", "cache scope"),
    ("Regime", "union_per_layer_step", "union per layer-step"),
    ("Regime", "capacity_per_layer", "capacity per layer"),
    ("Regime", "r_union_over_capacity", "r(s,l) = union / capacity"),
    ("Regime", "concurrency", "concurrency"),
    ("Regime", "service_discipline", "service discipline"),
    ("Regime", "miss_denominator", "miss denominator"),
    ("Regime", "dedup_credited_to_policy", "dedup credited to policy"),
    ("Regime", "static_fit_source", "static fit source"),
    ("Regime", "static_quota_rule", "static quota rule"),
    ("Regime", "initial_pinned_load_counted", "initial pinned load counted"),
    ("Oracle", "offline_bound_reported", "offline bound reported"),
    ("Oracle", "forced_admission_decomposition", "forced-admission decomposition"),
    ("Oracle", "absolute_bytes_per_output_token", "absolute bytes per output token"),
    ("Oracle", "bandwidth_budget_assumed", "bandwidth budget assumed"),
)
FIELD_KEYS = tuple(key for _, key, _ in FIELDS)
VALUE_KINDS = ("computed", "DECLARE", "NA", "NR", "paper")
_SHA256 = re.compile(r"\b[0-9a-f]{64}\b")


@dataclass(frozen=True)
class FieldValue:
    value: object
    kind: str
    source: str

    def validate(self, key: str) -> None:
        if self.kind not in VALUE_KINDS:
            raise ValueError(f"{key}: unknown value kind {self.kind!r}")
        if self.kind == "computed" and not _SHA256.search(self.source or ""):
            raise ValueError(f"{key}: a computed value must cite the SHA-256 of its input")
        if self.kind == "NA" and not str(self.value).strip():
            raise ValueError(f"{key}: NA requires a reason")
        if self.kind == "paper" and not str(self.source).strip():
            raise ValueError(f"{key}: a paper value must cite its section or sentence")


def _quantile_higher(values: np.ndarray, probability: float) -> float:
    return float(np.quantile(values, probability, method="higher"))


def regime_fields(trace: EventTrace, *, rho: float, scope: str, trace_sha256: str) -> dict[str, FieldValue]:
    """Regime fields computed from an event trace (paper §6.1 definitions)."""
    if scope not in {"per_layer", "global"}:
        raise ValueError("scope must be 'per_layer' or 'global'")
    (capacity,) = capacity_blocks_from_fractions(trace, [rho])
    union = np.diff(trace.offsets).astype(np.int64, copy=False)
    if scope == "per_layer":
        base, remainder = divmod(capacity, trace.num_layers)
        quotas = np.asarray(
            [base + int(layer < remainder) for layer in trace.layer_ids], dtype=np.int64
        )
        capacity_text = (
            f"{int(quotas.min())}-{int(quotas.max())} blocks per layer "
            f"(total {capacity} = round({trace.num_expert_blocks} x {rho}))"
        )
    else:
        quotas = np.full(union.shape, capacity, dtype=np.int64)
        capacity_text = f"{capacity} blocks shared by all layers (global; round({trace.num_expert_blocks} x {rho}))"
    ratio = union / quotas
    source = f"event trace events.safetensors sha256 {trace_sha256}"
    model = trace.manifest.get("model", {})
    batch = trace.manifest.get("conversion", {}).get("batch_size")
    return {
        "experts_topk_layers": FieldValue(
            f"{trace.num_experts_per_layer} / {model.get('top_k')} / {trace.num_layers}", "computed", source
        ),
        "residency_fraction": FieldValue(rho, "computed", source),
        "cache_scope": FieldValue(scope.replace("_", "-"), "computed", source),
        "union_per_layer_step": FieldValue(
            {"mean": float(union.mean()), "p95": _quantile_higher(union, 0.95)}, "computed", source
        ),
        "capacity_per_layer": FieldValue(capacity_text, "computed", source),
        "r_union_over_capacity": FieldValue(
            {
                "mean": float(ratio.mean()),
                "p95": _quantile_higher(ratio, 0.95),
                "fraction_gt_1": float(np.mean(union > quotas)),
            },
            "computed",
            source,
        ),
        "concurrency": FieldValue(batch, "computed" if batch is not None else "NA",
                                  source if batch is not None else "trace manifest has no batch size"),
    }


def build_block(
    *,
    mode: str,
    supplied: dict[str, FieldValue] | None = None,
) -> dict[str, FieldValue]:
    """Fill all 30 fields. Unsupplied fields default to NR (paper-only) or NA."""
    if mode not in {"paper_only", "with_artifacts"}:
        raise ValueError("mode must be 'paper_only' or 'with_artifacts'")
    supplied = dict(supplied or {})
    unknown = set(supplied) - set(FIELD_KEYS)
    if unknown:
        raise ValueError(f"Unknown reporting-block fields: {sorted(unknown)}")
    block: dict[str, FieldValue] = {}
    for key in FIELD_KEYS:
        if key in supplied:
            value = supplied[key]
            if mode == "paper_only" and value.kind not in {"paper", "NR"}:
                raise ValueError(f"{key}: paper-only mode accepts only text-cited values")
            if mode == "with_artifacts" and value.kind in {"NR", "paper"}:
                raise ValueError(f"{key}: with-artifacts mode needs computed, DECLARE or NA")
        elif mode == "paper_only":
            value = FieldValue("NR", "NR", "not reported in the public text")
        else:
            value = FieldValue("not supplied by any analysis", "NA", "")
        value.validate(key)
        block[key] = value
    return block


def filled_count(block: dict[str, FieldValue]) -> int:
    """Fields carrying information: computed or paper-cited values.

    DECLARE and NA fields are not counted: the value is not available to a reader.
    """
    return sum(1 for value in block.values() if value.kind in {"computed", "paper"})


def _format(value: object) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{k} {_format(v)}" for k, v in value.items())
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _cell(text: object) -> str:
    """Escape a value for a Markdown table cell (one B.1 label contains '|')."""
    return str(text).replace("|", "\\|")


def render_markdown(block: dict[str, FieldValue], *, title: str) -> str:
    lines = [f"# {title}", "", "```"]
    section = None
    for name, key, label in FIELDS:
        if name != section:
            if section is not None:
                lines.append("")
            lines.append(name)
            section = name
        value = block[key]
        shown = _format(value.value) if value.kind in {"computed", "paper"} else (
            f"{value.kind}" if value.kind in {"NR", "DECLARE"} else f"NA({_format(value.value)})"
        )
        lines.append(f"  {label} {'.' * max(3, 36 - len(label))} {shown}")
    lines += ["```", "", "| field | class | source |", "|---|---|---|"]
    for _, key, label in FIELDS:
        value = block[key]
        lines.append(f"| {_cell(label)} | {value.kind} | {_cell(value.source or '—')} |")
    lines += ["", f"Fields carrying information (computed or text-cited): {filled_count(block)} of {len(FIELDS)}.", ""]
    return "\n".join(lines)


def _load_facts(paths: Iterable[Path]) -> dict[str, FieldValue]:
    facts: dict[str, FieldValue] = {}
    for path in paths:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        for key, raw in payload["fields"].items():
            if key in facts:
                raise ValueError(f"{key} is supplied by more than one facts file")
            facts[key] = FieldValue(raw["value"], raw["kind"], raw.get("source", ""))
    return facts


def _parse_paper_values(items: Iterable[str]) -> dict[str, FieldValue]:
    values: dict[str, FieldValue] = {}
    for item in items:
        key_value, _, source = item.partition("@")
        key, _, value = key_value.partition("=")
        values[key.strip()] = FieldValue(value.strip(), "paper", source.strip())
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--events", type=Path, help="event-trace directory for the regime fields")
    parser.add_argument("--rho", type=float)
    parser.add_argument("--scope", choices=("per_layer", "global"))
    parser.add_argument("--facts", type=Path, action="append", default=[],
                        help="JSON {'fields': {key: {value, kind, source}}} from an analysis")
    parser.add_argument("--declare", action="append", default=[],
                        help="key=reason for a field only the original authors can state")
    parser.add_argument("--paper-only", action="store_true")
    parser.add_argument("--paper", action="append", default=[],
                        help="paper-only mode: key=value@section-or-sentence")
    parser.add_argument("--title", default="Minimal reporting block")
    parser.add_argument("--out-md", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    args = parser.parse_args()
    for out in (args.out_md, args.out_json):
        if out.exists():
            raise FileExistsError(f"Refusing to overwrite {out}")

    if args.paper_only:
        block = build_block(mode="paper_only", supplied=_parse_paper_values(args.paper))
        inputs: dict = {}
    else:
        supplied = _load_facts(args.facts)
        inputs = {"facts": {str(p): sha256_file(p) for p in args.facts}}
        if args.events:
            if args.rho is None or args.scope is None:
                parser.error("--events requires --rho and --scope")
            events_sha = sha256_file(args.events / "events.safetensors")
            trace = load_event_trace(args.events)
            for key, value in regime_fields(trace, rho=args.rho, scope=args.scope, trace_sha256=events_sha).items():
                if key in supplied:
                    raise ValueError(f"{key} is supplied both by the trace and by a facts file")
                supplied[key] = value
            inputs["events_sha256"] = events_sha
        for item in args.declare:
            key, _, reason = item.partition("=")
            supplied[key.strip()] = FieldValue("DECLARE", "DECLARE", reason.strip())
        block = build_block(mode="with_artifacts", supplied=supplied)

    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(render_markdown(block, title=args.title), encoding="utf-8")
    args.out_json.write_text(
        json.dumps(
            {
                "mode": "paper_only" if args.paper_only else "with_artifacts",
                "fields": {key: asdict(value) for key, value in block.items()},
                "filled_count": filled_count(block),
                "total_fields": len(FIELDS),
                "inputs": inputs,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(args.out_md)


if __name__ == "__main__":
    main()
