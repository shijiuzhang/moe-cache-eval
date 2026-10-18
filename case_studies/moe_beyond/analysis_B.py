"""Analysis B: operating-regime placement (PREREG P4).

Regime statistics use ``moe_controller.report_block.regime_fields`` (tested to
agree with the paper's regime script).  The uniform-routing null uses the
paper's ``expected_union`` with m = the number of independent top-k draws in
each event (its ``token_counts``): B active requests for E1, T prompt tokens
for E2.  Placement against Table 11 is made only at B = 1, rho = 0.40.

Outputs: results/B_regime.json, results/B_regime.md (refuses to overwrite).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CASE_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(CASE_DIR))

import numpy as np  # noqa: E402

import prereg_guard  # noqa: E402
from build_decode_operating_envelope import expected_union  # noqa: E402
from moe_controller.events import load_event_trace, sha256_file  # noqa: E402
from moe_controller.report_block import regime_fields  # noqa: E402

RESULTS = CASE_DIR / "results"
CANONICAL = CASE_DIR / "canonical"
RHOS = (0.10, 0.20, 0.30, 0.40)
PLACEMENT_RHO = 0.40
OUTSIDE_THRESHOLD = 0.15
# Table 11 alignment points (rho = 40%, per-layer, event-atomic), frozen in PREREG P4.
TABLE_11 = (
    ("40-expert", 8, 1.75),
    ("64-expert", 8, 1.44),
    ("128-expert", 8, 0.83),
    ("64-expert", 1, 0.313),
    ("128-expert", 2, 0.293),
    ("40-expert", 1, 0.500),
    ("128-expert", 4, 0.519),
)
TRACES = (
    ("E1 (per-token)", 1, "test-e1-b1", False),
    ("E2 (whole-prefill)", 1, "test-e2-b1", False),
    ("E1 (per-token)", 2, "test-e1-b2-constructed", True),
    ("E1 (per-token)", 4, "test-e1-b4-constructed", True),
    ("E1 (per-token)", 8, "test-e1-b8-constructed", True),
)


def _recorded_hashes() -> dict[str, str]:
    recorded = {}
    for line in (CANONICAL / "HASHES.txt").read_text(encoding="utf-8").splitlines():
        digest, _, path = line.partition("  ")
        recorded[path] = digest
    return recorded


def place(r_bar: float) -> dict:
    model, batch, point = min(TABLE_11, key=lambda item: abs(item[2] - r_bar))
    difference = abs(point - r_bar)
    return {
        "nearest_model": model,
        "nearest_batch": batch,
        "nearest_r_bar": point,
        "difference": difference,
        "within_measured_range": difference <= OUTSIDE_THRESHOLD,
    }


def main() -> None:
    lock = prereg_guard.verify_prereg()
    for name in ("B_regime.json", "B_regime.md"):
        if (RESULTS / name).exists():
            raise FileExistsError(f"Refusing to overwrite {RESULTS / name}")
    recorded = _recorded_hashes()
    files: dict[str, str] = {}
    rows: list[dict] = []
    for definition, batch, trace_dir, constructed in TRACES:
        relative = f"{trace_dir}/events.safetensors"
        digest = sha256_file(CANONICAL / relative)
        if recorded.get(relative) != digest:
            raise RuntimeError(f"{relative} differs from canonical/HASHES.txt")
        files[f"canonical/{relative}"] = digest
        trace = load_event_trace(CANONICAL / trace_dir)
        union = np.diff(trace.offsets).astype(np.int64)
        null = np.asarray(
            [expected_union(trace.num_experts_per_layer, 6, int(m)) for m in trace.token_counts]
        )
        for rho in RHOS:
            fields = regime_fields(trace, rho=rho, scope="per_layer", trace_sha256=digest)
            r = fields["r_union_over_capacity"].value
            rows.append(
                {
                    "event_definition": definition,
                    "batch": batch,
                    "constructed_by_this_paper": constructed,
                    "rho": rho,
                    "capacity_per_layer": fields["capacity_per_layer"].value,
                    "union_mean": fields["union_per_layer_step"].value["mean"],
                    "union_p95": fields["union_per_layer_step"].value["p95"],
                    "r_bar": r["mean"],
                    "r_p95": r["p95"],
                    "fraction_r_gt_1": r["fraction_gt_1"],
                    "null_union_mean": float(null.mean()),
                    "measured_minus_null": float(union.mean() - null.mean()),
                    "measured_below_null_relative": float((null.mean() - union.mean()) / null.mean()),
                    "trace": trace_dir,
                }
            )
    placements = [
        {
            "event_definition": row["event_definition"],
            "r_bar": row["r_bar"],
            **place(row["r_bar"]),
        }
        for row in rows
        if row["batch"] == 1 and row["rho"] == PLACEMENT_RHO
    ]

    payload = {"rows": rows, "placement_rho_0_40_b1": placements, "inputs": prereg_guard.inputs_record(lock, files)}
    (RESULTS / "B_regime.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    md = ["# Analysis B — operating regime", ""]
    md += ["| events | B | rho | union mean / p95 | r̄ | r p95 | fraction r > 1 | null union | measured below null |",
           "|---|---:|---:|---|---:|---:|---:|---:|---:|"]
    for row in rows:
        label = row["event_definition"] + (" — constructed by this paper" if row["constructed_by_this_paper"] else "")
        md.append(
            f"| {label} | {row['batch']} | {row['rho']:.2f} | {row['union_mean']:.2f} / {row['union_p95']:.0f} | "
            f"{row['r_bar']:.3f} | {row['r_p95']:.3f} | {row['fraction_r_gt_1']:.4f} | "
            f"{row['null_union_mean']:.2f} | {100 * row['measured_below_null_relative']:.1f}% |"
        )
    md += ["", "Rows marked “constructed by this paper” are FCFS batches built by the package; "
           "they are not MoE-Beyond's setting, which is B = 1.", "", "## Placement (B = 1, ρ = 40%, per-layer)", ""]
    for item in placements:
        if item["within_measured_range"]:
            md.append(
                f"- Under our reporting frame, the {item['event_definition']} event stream of this setting has "
                f"r̄ = {item['r_bar']:.3f} at ρ = 40% (per-layer scope); the nearest measured alignment point "
                f"in Table 11 is {item['nearest_model']}, B = {item['nearest_batch']} (r̄ = {item['nearest_r_bar']})."
            )
        else:
            md.append(
                f"- Under our reporting frame, the {item['event_definition']} event stream of this setting has "
                f"r̄ = {item['r_bar']:.3f} at ρ = 40% (per-layer scope); this lies outside the range of regimes "
                f"we measured (nearest: {item['nearest_model']}, B = {item['nearest_batch']}, "
                f"difference {item['difference']:.3f})."
            )
    md.append("")
    (RESULTS / "B_regime.md").write_text("\n".join(md), encoding="utf-8")
    print(RESULTS / "B_regime.md")


if __name__ == "__main__":
    main()
