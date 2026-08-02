#!/usr/bin/env python3
"""Build paper figures exclusively from frozen CSV artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "paper" / "figures"
OUT.mkdir(parents=True, exist_ok=True)

SOURCES = {
    "replay": ROOT / "paper/artifacts/figure-1-replay-semantics-v2/figure-1-data.csv",
    "workload": ROOT / "analysis/controller-probe-d1-qwen3-matched-route-comparison-v3/matched-route-comparison.csv",
    "regime": ROOT / "analysis/paper-regime-ablation-qwen3-heldout-v1/regime-ablation.csv",
    "gap_b8": ROOT / "analysis/controller-probe-d1-belady-gap-attribution-v1/gap-attribution.csv",
    "gap_b2": ROOT / "analysis/controller-probe-d1-belady-gap-attribution-b2-v1/gap-attribution.csv",
}


def rows(key: str) -> list[dict[str, str]]:
    with SOURCES[key].open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def finish(fig: plt.Figure, stem: str) -> None:
    fig.tight_layout()
    for suffix in ("pdf", "png"):
        fig.savefig(OUT / f"{stem}.{suffix}", dpi=240, bbox_inches="tight")
    plt.close(fig)


def replay_figure() -> None:
    data = rows("replay")
    policies = ["lru", "lfru", "least_stale", "lfu", "belady", "static"]
    labels = ["LRU", "LFRU", "Least-Stale", "LFU", "Belady", "Static\n(same trace)"]
    lookup = {(r["policy"], r["semantics"]): float(r["effective_miss_percent"]) for r in data}
    x = np.arange(len(policies))
    width = 0.37
    fig, ax = plt.subplots(figsize=(8.4, 4.3))
    ax.bar(x - width / 2, [lookup[p, "sequential"] for p in policies], width,
           label="Sequential replay", color="#cc6677")
    ax.bar(x + width / 2, [lookup[p, "event_atomic"] for p in policies], width,
           label="Event-atomic replay", color="#4477aa")
    ax.set_ylabel("Effective miss fraction (%)")
    ax.set_xticks(x, labels)
    ax.legend(frameon=False, ncols=2)
    ax.grid(axis="y", alpha=0.25)
    finish(fig, "figure1_replay_semantics")


def workload_figure() -> None:
    data = [r for r in rows("workload") if r["arm"] == "diverse" and r["band_start"] == "0" and r["band_end"] == "16"]
    labels = {
        "office_legal": "Office/legal",
        "dcs_process_diagnostics": "Process diagnostics",
        "erp_structured_analytics": "ERP",
        "tool_agent": "Tool agent",
        "equipment_maintenance_bom": "Equipment/BOM",
        "document_rag": "Document RAG",
    }
    data.sort(key=lambda r: float(r["template_echo_union_reduction_delta"]), reverse=True)
    vals = [100 * float(r["template_echo_union_reduction_delta"]) for r in data]
    fig, ax = plt.subplots(figsize=(8.4, 4.2))
    bars = ax.barh([labels[r["category"]] for r in data][::-1], vals[::-1], color="#228833")
    ax.set_xlabel("Fixed-template minus diverse-arm union reduction (percentage points)")
    ax.grid(axis="x", alpha=0.25)
    for bar, value in zip(bars, vals[::-1]):
        ax.text(value + 0.5, bar.get_y() + bar.get_height() / 2, f"{value:.1f}", va="center")
    finish(fig, "figure2_template_attribution")


def regime_figure() -> None:
    data = rows("regime")
    original = next(r for r in data if r["condition"] == "original")
    permuted = [100 * float(r["recoverable_gap"]) for r in data if r["condition"].startswith("step_permutation_")]
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    ax.boxplot([permuted], positions=[1], widths=0.45, showfliers=True,
               boxprops={"color": "#4477aa"}, medianprops={"color": "#4477aa"})
    ax.scatter([2], [100 * float(original["recoverable_gap"])], s=75, color="#cc6677", zorder=3)
    ax.set_xticks([1, 2], ["20 temporal\npermutations", "Original\norder"])
    ax.set_ylabel("Recoverable gap (%)")
    ax.set_title(f"Mean union/cache fixed at {float(original['mean_union_to_capacity']):.4f}")
    ax.grid(axis="y", alpha=0.25)
    finish(fig, "figure3_regime_not_sufficient")


def heldout_rho40(key: str) -> dict[str, str]:
    candidates = [r for r in rows(key) if r["split"] == "confirmatory_heldout"]
    return min(candidates, key=lambda r: abs(float(r["capacity_fraction"]) - 0.40))


def decomposition_figure() -> None:
    b2, b8 = heldout_rho40("gap_b2"), heldout_rho40("gap_b8")
    admission = [100 * float(b2["admission_share_of_total_gap"]), 100 * float(b8["admission_share_of_total_gap"])]
    victim = [100 * float(b2["future_victim_share_of_total_gap"]), 100 * float(b8["future_victim_share_of_total_gap"])]
    x = np.arange(2)
    fig, ax = plt.subplots(figsize=(6.6, 4.2))
    ax.bar(x, admission, label="Bypass-admission share", color="#eeaa33")
    ax.bar(x, victim, bottom=admission, label="Future-victim share", color="#4477aa")
    ax.set_xticks(x, ["B = 2", "B = 8"])
    ax.set_ylim(0, 100)
    ax.set_ylabel("Share of causal-to-Belady gap (%)")
    ax.legend(frameon=False, loc="lower right")
    for idx in range(2):
        ax.text(idx, admission[idx] / 2, f"{admission[idx]:.1f}%", ha="center", va="center")
        ax.text(idx, admission[idx] + victim[idx] / 2, f"{victim[idx]:.1f}%", ha="center", va="center", color="white")
    finish(fig, "figure4_gap_decomposition")


def main() -> None:
    for path in SOURCES.values():
        if not path.exists():
            raise SystemExit(f"missing frozen input: {path}")
    replay_figure()
    workload_figure()
    regime_figure()
    decomposition_figure()
    manifest = {
        "builder": "scripts/build_submission_figures.py",
        "inputs": {
            key: {"path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for key, path in SOURCES.items()
        },
        "outputs": sorted(p.name for p in OUT.iterdir() if p.suffix in {".pdf", ".png"}),
        "note": "No values are manually entered; all plotted values are read from frozen CSV artifacts.",
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

