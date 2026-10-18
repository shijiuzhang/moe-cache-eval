"""Generate paper/case_study_macros.tex from results/*.json (protocol §6.1).

Every number that enters the paper is one ``\\CS*`` macro whose value is read
from a result file here; the paper text never types these numbers.  Macro names
are letters only (TeX control words cannot contain digits).
"""

from __future__ import annotations

import json
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
OUTPUT = CASE_DIR / "paper" / "case_study_macros.tex"
SOURCES = ("A_contract.json", "A_reproduction_raw.json", "B_regime.json", "C_workload.json", "C_exploratory_positional.json",
           "D_decomposition.json", "E_delta.json")


def pct(value: float, digits: int = 1) -> str:
    text = f"{100 * abs(value):.{digits}f}\\%"
    return f"$-${text}" if value < 0 else text


def load(name: str) -> dict:
    return json.loads((RESULTS / name).read_text(encoding="utf-8"))


def one(rows, **match):
    found = [r for r in rows if all(r.get(k) == v for k, v in match.items())]
    if len(found) != 1:
        raise RuntimeError(f"Expected one row for {match}, found {len(found)}")
    return found[0]


def build() -> list[tuple[str, str, str]]:
    a, _, b, c, cx, d, e = (load(name) for name in SOURCES)
    probes = a["P1_probes"]
    repro = a["P3_reproduction"]
    p2_e2_layer = one(a["P2_axis_one"], event_definition="E2 (whole-prefill)",
                      setting=next(r["setting"] for r in a["P2_axis_one"] if r["setting"].startswith("package frame")))
    brow = lambda d_, rho: one(b["rows"], event_definition=d_, batch=1, rho=rho)  # noqa: E731
    placements = {p["event_definition"]: p for p in b["placement_rho_0_40_b1"]}
    drow = lambda d_, rho: one(d["rows"], event_definition=d_, batch=1, rho=rho,  # noqa: E731
                               scope="per_layer", start_state="(i) persistent, cold start")
    route = c["route_side"]
    commit = subprocess.run(["git", "-C", str(prereg_guard.THIRD_PARTY_ROOT), "rev-parse", "--short=7", "HEAD"],
                            capture_output=True, text=True, check=True).stdout.strip()
    e1, e2 = "E1 (per-token)", "E2 (whole-prefill)"
    m = []
    add = lambda name, value, source: m.append((name, value, source))  # noqa: E731
    add("CSthirdPartyCommit", commit, "git rev-parse of third_party/moe-beyond")
    add("CStestPrompts", str(c["prompt_side"]["records"]), "C_workload.prompt_side.records")
    add("CSseeds", str(len(probes["A2"]["eligible_seeds"])), "A_contract.P1_probes.A2.eligible_seeds")
    add("CSprobeAtwoMisses", str(probes["A2"]["probe_counts_observed"][0]["misses"]), "A_contract.P1_probes.A2")
    add("CSprobeAoneHits", str(probes["A1"]["probe_counts_observed"][0]["hits"]), "A_contract.P1_probes.A1")
    add("CSprobeAoneMisses", str(probes["A1"]["probe_counts_observed"][0]["misses"]), "A_contract.P1_probes.A1")
    sizes = {run["cache_size"] for run in load("A_reproduction_raw.json")["runs"]}
    if len(sizes) != 1:
        raise RuntimeError(f"Expected one reproduction cache size, found {sizes}")
    add("CStheirCapacity", str(sizes.pop()), "A_reproduction_raw.runs[].cache_size")
    add("CSreproInfinity", f"{repro['moe_infinity_eamc']['mean_cache_hit_percent']:.1f}\\%", "A_contract.P3_reproduction")
    add("CSreportedInfinity", f"{repro['moe_infinity_eamc']['reported_percent']:.0f}\\%", "A_contract.P3_reproduction")
    add("CSreproBeyond", f"{repro['moe_beyond_predicted']['mean_cache_hit_percent']:.1f}\\%", "A_contract.P3_reproduction")
    add("CSreportedBeyond", f"{repro['moe_beyond_predicted']['reported_percent']:.0f}\\%", "A_contract.P3_reproduction")
    add("CSreproTolerance", "2.0", "PREREG P3")
    add("CSfilesUsed", str(repro["moe_beyond_predicted"]["files_used"][0]), "A_contract.P3_reproduction.files_used")
    add("CSmaxUnionEtwo", str(p2_e2_layer["max_event_union"]), "A_contract.P2_axis_one")
    add("CSoverCapEtwoPerLayerTen", pct(p2_e2_layer["fraction_over_capacity"]), "A_contract.P2_axis_one")
    add("CSrbarEoneRhoTen", f"{brow(e1, 0.10)['r_bar']:.3f}", "B_regime.rows")
    add("CSrbarEoneRhoForty", f"{brow(e1, 0.40)['r_bar']:.3f}", "B_regime.rows")
    add("CSrbarEtwoRhoForty", f"{brow(e2, 0.40)['r_bar']:.3f}", "B_regime.rows")
    for key, item in ((e1, placements[e1]), (e2, placements[e2])):
        tag = "Eone" if key == e1 else "Etwo"
        add(f"CSnearest{tag}", f"{item['nearest_model']} model at \\mbox{{$B={item['nearest_batch']}$}}", "B_regime.placement")
        add(f"CSnearest{tag}Rbar", f"{item['nearest_r_bar']}", "B_regime.placement")
    add("CSunionEtwoMean", f"{brow(e2, 0.40)['union_mean']:.1f}", "B_regime.rows")
    add("CSnullBelowEtwo", pct(brow(e2, 0.40)["measured_below_null_relative"]), "B_regime.rows")
    add("CSlenMin", str(cx["tokens_per_record"]["min"]), "C_exploratory_positional")
    add("CSlenMax", str(cx["tokens_per_record"]["max"]), "C_exploratory_positional")
    add("CSheadsDistinct", str(c["prompt_side"]["distinct_prompt_heads_70_chars"]), "C_workload.prompt_side")
    add("CSfinalsDistinct", str(c["prompt_side"]["distinct_final_lines"]), "C_workload.prompt_side")
    add("CSpromptJaccardPninetyfive", f"{c['prompt_side']['word_5gram_jaccard_p95']:.3f}", "C_workload.prompt_side")
    add("CSdetectorRecords", str(route["records"]), "C_workload.route_side")
    add("CSposAgreePninetyfive", f"{route['token_positional_agreement_p95']:.3f}", "C_workload.route_side")
    add("CSdetectorFlag", "true" if route["contamination_flag"] else "false", "C_workload.route_side")
    add("CSposAgreeNoBosPninetyfive", f"{cx['positional_agreement_position_0_excluded']['p95']:.3f}",
        "C_exploratory_positional (post-hoc, D-004)")
    add("CSonlyBosShare", pct(cx["pairs_agreeing_only_at_position_0_fraction"], 0), "C_exploratory_positional (post-hoc)")
    for rho, word in ((0.10, "Ten"), (0.40, "Forty")):
        row = drow(e1, rho)
        add(f"CSgapRho{word}", pct(row["recoverable_gap"]), "D_decomposition E1 per-layer (i)")
        add(f"CSadmShareRho{word}", pct(row["admission_share"]), "D_decomposition E1 per-layer (i)")
        add(f"CSfvShareRho{word}", pct(row["future_victim_share"]), "D_decomposition E1 per-layer (i)")
    brk = drow(e2, 0.40)
    add("CSadmShareBreak", pct(brk["admission_share"]), "D_decomposition E2 per-layer (i) rho 0.40")
    add("CSfvShareBreak", pct(brk["future_victim_share"]), "D_decomposition E2 per-layer (i) rho 0.40")
    add("CSfieldsTotal", str(e["total_fields"]), "E_delta")
    add("CSfieldsPaperOnly", str(e["paper_only_answered"]), "E_delta (answered, D-007)")
    add("CSfieldsPaperOnlyNotApplicable", str(e["paper_only_not_applicable"]), "E_delta (D-007)")
    add("CSfieldsWithArtifacts", str(e["with_artifacts_answered"]), "E_delta (answered, D-007)")
    add("CSfieldsWithArtifactsNotApplicable", str(e["with_artifacts_not_applicable"]), "E_delta (D-007)")
    added = e["answered_only_with_artifacts"]
    add("CSfieldsAnsweredOnlyWithArtifacts", str(len(added)), "E_delta.answered_only_with_artifacts")
    for provenance, word in (("execution", "Execution"), ("code_inspection", "CodeInspection"),
                             ("data_inspection", "DataInspection"), ("analyst_inference", "AnalystInference")):
        add(f"CSaddedBy{word}", str(sum(1 for item in added if item["provenance"] == provenance)),
            f"E_delta.answered_only_with_artifacts provenance {provenance}")
    for name, _, _ in m:
        if not name.isalpha():
            raise RuntimeError(f"Macro name {name} is not letters only")
    return m


def main() -> None:
    lock = prereg_guard.verify_prereg()
    macros = build()
    header = [
        "% Generated by case_studies/moe_beyond/make_macros.py -- do not edit by hand.",
        f"% PREREG sha256 {lock['prereg_sha256']}",
    ] + [f"% {name} sha256 {sha256_file(RESULTS / name)}" for name in SOURCES]
    body = [f"\\newcommand{{\\{name}}}{{{value}}} % {source}" for name, value, source in macros]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(header + body) + "\n", encoding="utf-8")
    print(f"{OUTPUT} ({len(macros)} macros)")


if __name__ == "__main__":
    main()
