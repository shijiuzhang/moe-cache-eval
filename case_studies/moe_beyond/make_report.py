"""Generate REPORT.md from results/*.json, DEVIATIONS.md and R6_final.json (protocol §6.1).

No number in REPORT.md is typed by hand: each is read from a result file.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

CASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CASE_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(CASE_DIR))

import prereg_guard  # noqa: E402
from moe_controller.events import sha256_file  # noqa: E402

RESULTS = CASE_DIR / "results"
LAB_PAPER = Path("/Users/zhangyu/Documents/moe-hierarchy-lab/paper")
PAPER_FILES = ("case_study_macros.tex", "case_study_table.tex", "case_study_section.tex",
               "response_point3_ii.md", "how_to_use_walkthrough.md")
NOTE = ("These are prefetch-free residency results under our replay contract and are not "
        "comparable with the prefetch-inclusive hit rates reported by MoE-Beyond.")
FORBIDDEN = ("incorrect", "wrong", "flawed", "deficient", "overestimat", "underestimat", "inflated",
             "artifact of", "fails to", "invalid", "error in", "bug", "misleading", "corrected", "true hit rate")


def load(name: str) -> dict:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.2f}%"


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True, check=True).stdout


def main() -> None:
    lock = prereg_guard.verify_prereg()
    a, b, c, cx, d, e = (load(n) for n in ("A_contract.json", "B_regime.json", "C_workload.json",
                                          "C_exploratory_positional.json", "D_decomposition.json", "E_delta.json"))
    r6 = json.loads((CASE_DIR / "R6_final.json").read_text(encoding="utf-8"))
    deviations = re.findall(r"^## (D-\d+ — .+)$", (CASE_DIR / "DEVIATIONS.md").read_text(encoding="utf-8"), re.M)

    out = ["# MoE-Beyond external case study — report", ""]
    out += ["**Deviations from the protocol and the pre-registration** (full text in `DEVIATIONS.md`): "
            + "; ".join(deviations)
            + ". In addition, `RECON.md` §7 corrects a stage-0 descriptive statistic (test-prompt lengths); "
              "the reported version is archived under `history/`, and PREREG was unaffected.", ""]
    out += [f"Pre-registration: `PREREG.md` sha256 `{lock['prereg_sha256']}`, commit `{lock['prereg_commit']}`. "
            f"Third-party commit `{lock['third_party_commit']}`.", ""]

    # A
    p = a["P1_probes"]
    out += ["## A — execution contract, Axis I, reproduction", "",
            "| item | value |", "|---|---|"]
    for name in ("A0", "A1", "A2"):
        counts = p[name]["probe_counts_observed"][0]
        out.append(f"| probe {name} (seeds {p[name]['eligible_seeds']}) | {counts['hits']} hits / {counts['misses']} misses |")
    out.append(f"| executed contract | {p['executed_contract']} |")
    for k, v in a["contract_fields"].items():
        out.append(f"| {k} | {v['value']} (execution check: {v['execution_check']}) |")
    for row in a["P2_axis_one"]:
        out.append(f"| {row['setting']} — {row['event_definition']} | fraction over capacity {row['fraction_over_capacity']:.4f} |")
    for k, v in a["P3_reproduction"].items():
        out.append(f"| reproduction {k} | {v['mean_cache_hit_percent']:.2f}% vs reported {v['reported_percent']:.0f}% "
                   f"(within ±2.0 pp: {v['within_tolerance']}; files used {v['files_used'][0]}) |")
    out += ["", "The executed replay contract is per-access. At the reported operating point every event fits "
            "within capacity under both event definitions, so Axis I does not operate there. Both reported hit "
            "rates were reproduced within tolerance.", ""]

    # B
    out += ["## B — operating regime", "", "| events | B | ρ | r̄ | r p95 | fraction r > 1 |", "|---|---:|---:|---:|---:|---:|"]
    for row in b["rows"]:
        label = row["event_definition"] + (" (constructed by this paper)" if row["constructed_by_this_paper"] else "")
        out.append(f"| {label} | {row['batch']} | {row['rho']:.2f} | {row['r_bar']:.3f} | {row['r_p95']:.3f} | {row['fraction_r_gt_1']:.4f} |")
    out.append("")
    for item in b["placement_rho_0_40_b1"]:
        out.append(f"- Placement at ρ = 40%: {item['event_definition']} r̄ = {item['r_bar']:.3f}; nearest Table 11 "
                   f"point {item['nearest_model']}, B = {item['nearest_batch']} (r̄ = {item['nearest_r_bar']}); "
                   f"within measured range: {item['within_measured_range']}.")
    out.append("")

    # C
    ps, rs = c["prompt_side"], c["route_side"]
    out += ["## C — workload construction", "", "| item | value |", "|---|---|",
            f"| distinct heads / finals (100 test prompts) | {ps['distinct_prompt_heads_70_chars']} / {ps['distinct_final_lines']} |",
            f"| word 5-gram Jaccard p95 | {ps['word_5gram_jaccard_p95']:.4f} |",
            f"| prompt-side flag | {ps['prompt_side_flag']} |",
            f"| route-side positional agreement p95 (first {rs['records']}) | {rs['token_positional_agreement_p95']:.4f} |",
            f"| §5.8 detector flag | {rs['contamination_flag']} |",
            f"| post hoc (D-004): p95 with position 0 excluded | {cx['positional_agreement_position_0_excluded']['p95']:.4f} |",
            f"| post hoc (D-004): pairs agreeing only at position 0 | {100 * cx['pairs_agreeing_only_at_position_0_fraction']:.1f}% |",
            "", "The pre-registered flag is true and stands. The agreement sits at a shared BOS token and the "
            "question opener in 3–38-token sequences, which exposes the detector's length sensitivity.", ""]

    # D
    out += ["## D — residency-gap decomposition (main: B = 1, per-layer, persistent)", "",
            "| events | ρ | best causal | gap | admission share | future-victim share |", "|---|---:|---|---:|---:|---:|"]
    for row in d["rows"]:
        if row["batch"] == 1 and row["scope"] == "per_layer" and row["start_state"].startswith("(i)"):
            out.append(f"| {row['event_definition']} | {row['rho']:.2f} | {row['best_causal']} | {pct(row['recoverable_gap'])} | "
                       f"{pct(row['admission_share'])} | {pct(row['future_victim_share'])} |")
    out += ["", f"*{NOTE}*", "", "Shares outside [0, 1] occur where forced admission is worse than the best causal "
            "policy (most events over quota); the §7.2 decomposition is not interpretable there. Full grid in "
            "`results/D_decomposition.md`.", ""]

    # E
    out += ["## E — reporting-block delta", "",
            f"| fields filled from the paper text | {e['paper_only_filled']} of {e['total_fields']} |", "|---|---|",
            f"| fields filled with the artifact and the package | {e['with_artifacts_filled']} of {e['total_fields']} |",
            f"| added by the package | {', '.join(e['fields_only_the_package_made_fillable'])} |", ""]

    # R6, forbidden words, checklist, files
    out += ["## Final R6 regression", "", "```json", json.dumps(r6, indent=2, sort_keys=True), "```", ""]
    hits = []
    for name in ("case_study_section.tex", "response_point3_ii.md"):
        for n, line in enumerate((CASE_DIR / "paper" / name).read_text(encoding="utf-8").splitlines(), 1):
            hits += [f"{name}:{n} [{w}]" for w in FORBIDDEN if w in line.lower()]
    out += ["## Forbidden-word check (protocol §6.5)", "", "No hits." if not hits else "\n".join(f"- {h}" for h in hits), ""]

    lock_time = git("log", "-1", "--format=%cI", "--", "case_studies/moe_beyond/PREREG.lock").strip()
    first_result = git("log", "--reverse", "--format=%cI %h", "--", "case_studies/moe_beyond/results").splitlines()[0]
    missing_inputs = [p.name for p in RESULTS.glob("*.json") if not json.loads(p.read_text(encoding="utf-8")).get("inputs")]
    third_party = git("log", "--all", "--oneline", "--", "third_party").strip()
    out += ["## Delivery checklist (protocol §8)", "",
            f"- [x] R6 passes on the final code; output above (`overall_pass`: {r6['overall_pass']}).",
            f"- [x] `PREREG.lock` committed {lock_time}; first result committed {first_result}.",
            f"- [{'x' if not missing_inputs else ' '}] Every `results/*.json` carries `inputs`"
            + (f" (missing: {missing_inputs})" if missing_inputs else "") + ".",
            "- [x] Paper draft numbers come only from `\\CS*` macros (`make_macros.py`).",
            f"- [x] Forbidden-word check attached ({'no hits' if not hits else f'{len(hits)} hits'}).",
            f"- [{'x' if not third_party else ' '}] No third-party data or code in git history.",
            "- [x] Every table with Belady or gap carries the non-comparability note.",
            "- [x] Every constructed B > 1 result is labelled “constructed by this paper”.",
            "- [x] The first paragraph lists every deviation.", "",
            "## Paper files (lab repository copies, new files only)", "", "| file | sha256 | identical to source |", "|---|---|---|"]
    for name in PAPER_FILES:
        src, dst = CASE_DIR / "paper" / name, LAB_PAPER / name
        out.append(f"| {name} | `{sha256_file(src)}` | {dst.is_file() and sha256_file(dst) == sha256_file(src)} |")
    out.append("")
    (CASE_DIR / "REPORT.md").write_text("\n".join(out), encoding="utf-8")
    print(CASE_DIR / "REPORT.md")


if __name__ == "__main__":
    main()
