"""Analysis E: reporting-block comparison (PREREG P7, revised by DEVIATIONS D-007/D-008).

Both blocks describe one target: the original reported configuration (the
published simulator's contract, rho = 0.10, global scope, B = 1, per-token
replay unit, prefetch included).  Both are produced by the released package's
command ``python -m moe_controller.report_block`` under one rule:

* ``answered`` / ``not_applicable`` / ``NA`` / ``DECLARE`` / ``NR`` (paper-only);
* every ``answered`` or ``not_applicable`` value states its provenance — text,
  execution, code inspection, data inspection or analyst inference;
* the headline counts ``answered`` only; ``not_applicable`` is counted apart.

Results obtained under the package's own contract (analysis D: atomic,
prefetch-free, cold start) are not entries of the block; they are listed in a
separate "package analyses" section of E_delta and never counted.

The comparison is paper text versus public artifact plus package plus the
documented analyst steps; there is no artifact-only control (D-008).

Outputs: results/E_report_block_paper_only.{md,json},
results/E_report_block_with_artifacts.{md,json}, results/E_facts.json,
results/E_delta.{md,json}.
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

import numpy as np  # noqa: E402
from safetensors import safe_open  # noqa: E402

import prereg_guard  # noqa: E402
from moe_controller.events import sha256_file  # noqa: E402
from moe_controller.report_block import FIELDS  # noqa: E402

RESULTS = CASE_DIR / "results"
CANONICAL = CASE_DIR / "canonical"
PAPER_HTML = REPO_ROOT / "third_party" / "moebeyond-paper" / "2508.17137v1.html"
PAPER_SHA256 = "ef57960064f883656578c12ed6df67d2d66313181ee333fd0ceb29888f0fc590"
SIMULATOR = "cache_simulator/infinity_moe_sim.py"
COLLECTOR = "expert_activation_scripts/generate_deepseek_logs_eamc.py"
NOTE = ("These are prefetch-free residency results under our replay contract and are not "
        "comparable with the prefetch-inclusive hit rates reported by MoE-Beyond.")

# Paper-only mode: (value, section). Fixed by D-007.
PAPER_ANSWERED = {
    "event_unit": ("token-by-token replay of each test prompt", "§4.1.4 Simulator"),
    "conformance_trace": ("no", "no conformance or reference trace appears in §4.1.4"),
    "experts_topk_layers": ("64 routed (+2 shared) / 6 / 27", "§4.1.1 Models; §4.1.4 Simulator"),
    "residency_fraction": ("0.10 headline; capacity swept", "Abstract; §4.2.1"),
    "concurrency": ("1", "Abstract; §5 Limitations"),
    "service_discipline": ("one prompt replayed at a time", "§4.1.4 Simulator"),
    "miss_denominator": ("per ground-truth expert activation", "§4.1.4; §4.2.1 GPU Cache Hit Rate"),
    "offline_bound_reported": ("no", "no offline optimum in §4.2 Results"),
}
PAPER_NOT_APPLICABLE = {
    "position_locked_cohorts": ("batch size one; no concurrent requests", "Abstract; §5 Limitations"),
    "dedup_credited_to_policy": ("batch size one; nothing to deduplicate", "Abstract; §5 Limitations"),
    "static_fit_source": ("no static policy; only MoE-Infinity is compared", "§4.1.3 Baseline"),
    "static_quota_rule": ("no static policy; only MoE-Infinity is compared", "§4.1.3 Baseline"),
    "initial_pinned_load_counted": ("no static policy; only MoE-Infinity is compared", "§4.1.3 Baseline"),
}


def _paper_only(out_md: Path, out_json: Path) -> None:
    args = [sys.executable, "-I", "-m", "moe_controller.report_block", "--paper-only",
            "--title", "MoE-Beyond — reporting block from the public text only",
            "--paper-file", str(PAPER_HTML), "--out-md", str(out_md), "--out-json", str(out_json)]
    for key, (value, section) in PAPER_ANSWERED.items():
        args += ["--paper", f"{key}={value}@{section}"]
    for key, (value, section) in PAPER_NOT_APPLICABLE.items():
        args += ["--paper-not-applicable", f"{key}={value}@{section}"]
    subprocess.run(args, cwd=REPO_ROOT, check=True, capture_output=True, text=True)


def _intra_event_order(files: dict[str, str]) -> tuple[str, str]:
    source = CANONICAL / "test-e1-source"
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    rows = ascending = 0
    digest = ""
    for shard in manifest["shards"]:
        path = source / shard["tensor_file"]
        digest = sha256_file(path)
        files[f"canonical/test-e1-source/{shard['tensor_file']}"] = digest
        with safe_open(path, framework="pt") as handle:
            lengths = handle.get_tensor("sequence_lengths").tolist()
            indices = handle.get_tensor("topk_indices").numpy()
        for local, length in enumerate(lengths):
            block = indices[local, :, :length, :].reshape(-1, indices.shape[-1])
            rows += block.shape[0]
            ascending += int(np.all(np.diff(block, axis=1) > 0, axis=1).sum())
    return f"ascending id ({ascending} of {rows} replayed rows ascending; accessed in list order)", digest


def main() -> None:
    lock = prereg_guard.verify_prereg()
    names = ["E_report_block_paper_only.md", "E_report_block_paper_only.json",
             "E_report_block_with_artifacts.md", "E_report_block_with_artifacts.json",
             "E_facts.json", "E_delta.md", "E_delta.json"]
    for name in names:
        if (RESULTS / name).exists():
            raise FileExistsError(f"Refusing to overwrite {RESULTS / name}")
    if sha256_file(PAPER_HTML) != PAPER_SHA256:
        raise RuntimeError("Paper HTML differs from the hash frozen in PREREG §0.")
    files: dict[str, str] = {"third_party/moebeyond-paper/2508.17137v1.html": PAPER_SHA256}
    files.update(prereg_guard.verify_third_party_files([SIMULATOR, COLLECTOR]))
    for name in ("A_contract.json", "C_workload.json", "D_decomposition.json"):
        files[f"results/{name}"] = sha256_file(RESULTS / name)
    a = json.loads((RESULTS / "A_contract.json").read_text(encoding="utf-8"))
    c = json.loads((RESULTS / "C_workload.json").read_text(encoding="utf-8"))
    d = json.loads((RESULTS / "D_decomposition.json").read_text(encoding="utf-8"))
    sha_a, sha_c, sha_d = (files[f"results/{n}"] for n in ("A_contract.json", "C_workload.json", "D_decomposition.json"))
    sim = f"{SIMULATOR} sha256 {files[SIMULATOR]}"
    collector = f"{COLLECTOR} sha256 {files[COLLECTOR]}"
    inputs_sha = lock["inputs_manifest_sha256"]

    order_value, order_sha = _intra_event_order(files)
    route = c["route_side"]
    retention = a["P1_probes"]["executed_contract"]

    def answer(value, provenance, source):
        return {"value": value, "kind": "answered", "provenance": provenance, "source": source}

    def not_applicable(reason, provenance, source):
        return {"value": reason, "kind": "not_applicable", "provenance": provenance, "source": source}

    def na(reason):
        return {"value": reason, "kind": "NA", "source": ""}

    facts = {"fields": {
        "event_unit": answer(f"{retention.replace('_', '-')} (probe A2, five seeds)", "execution",
                             f"results/A_contract.json sha256 {sha_a}"),
        "retention_decision": answer("immediate" if retention == "per_access" else "event boundary", "execution",
                                     f"probe A2; results/A_contract.json sha256 {sha_a}"),
        "intra_event_order": answer(order_value, "data_inspection",
                                    f"canonical/test-e1-source sha256 {order_sha}; {sim} lines 242-251"),
        "conformance_trace": answer("no (none in the public repository)", "analyst_inference",
                                    f"repository inventory INPUTS.sha256 sha256 {inputs_sha}"),
        "templates_per_category": na("no category labels in the public artifact"),
        "distinct_prompt_heads_finals": answer(
            f"{c['prompt_side']['distinct_prompt_heads_70_chars']} / {c['prompt_side']['distinct_final_lines']}",
            "execution", f"results/C_workload.json sha256 {sha_c}"),
        "chat_template_applied": answer("no", "code_inspection", f"{collector} line 122"),
        "decode_steps_recorded": answer(0, "code_inspection", f"{collector} lines 122-124"),
        "position_locked_cohorts": not_applicable("B = 1; no concurrent requests", "code_inspection",
                                                  f"{sim} lines 284-292 (one test file per replay call)"),
        "unique_generated_sequences": not_applicable("no generated token is recorded", "code_inspection",
                                                     f"{collector} lines 122-124"),
        "positional_token_agreement": answer(
            {"mean": route["token_positional_agreement_mean"], "p95": route["token_positional_agreement_p95"],
             "scope": "input sequences, first 48 records; post-hoc decomposition in C_exploratory_positional (D-004)"},
            "execution", f"results/C_workload.json sha256 {sha_c}"),
        "expert_jaccard_low_text_overlap": answer(route["expert_jaccard_low_token_mean"], "execution",
                                                  f"results/C_workload.json sha256 {sha_c}"),
        "effect_stable_across_position_bands": na("no category labels or matched template arm"),
        "service_discipline": answer("one prompt replayed at a time; cache rebuilt for every prompt", "execution",
                                     f"contract check in results/A_contract.json sha256 {sha_a}"),
        "miss_denominator": answer("per expert access, pre-dedup", "execution",
                                   f"denominator check in results/A_contract.json sha256 {sha_a}"),
        "dedup_credited_to_policy": not_applicable("B = 1; nothing to deduplicate", "code_inspection",
                                                   f"{sim} lines 284-292"),
        "static_fit_source": not_applicable("no static policy in the simulator", "code_inspection", sim),
        "static_quota_rule": not_applicable("no static policy in the simulator", "code_inspection", sim),
        "initial_pinned_load_counted": not_applicable("no static policy in the simulator", "code_inspection", sim),
        "offline_bound_reported": answer("no", "code_inspection", f"{sim} (no offline optimum)"),
        "forced_admission_decomposition": na(
            "not defined for the original prefetch-inclusive per-access contract; a package-contract "
            "analysis is reported separately"),
        "absolute_bytes_per_output_token": not_applicable("no generated token is recorded", "code_inspection",
                                                          f"{collector} lines 122-124"),
    }}
    facts["inputs"] = prereg_guard.inputs_record(lock, dict(files))
    (RESULTS / "E_facts.json").write_text(json.dumps(facts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files["results/E_facts.json"] = sha256_file(RESULTS / "E_facts.json")

    _paper_only(RESULTS / "E_report_block_paper_only.md", RESULTS / "E_report_block_paper_only.json")
    subprocess.run(
        [sys.executable, "-I", "-m", "moe_controller.report_block",
         "--events", str(CANONICAL / "test-e1-b1"), "--rho", "0.10", "--scope", "global",
         "--parameter-provenance", "code_inspection",
         "--parameter-source", f"{sim} lines 81-90 and 275 (one global cache; int(1664 x 0.10))",
         "--facts", str(RESULTS / "E_facts.json"),
         "--declare", "bandwidth_budget_assumed=only the original authors can state the bandwidth they assumed",
         "--title", "MoE-Beyond — reporting block with the public artifact, the package and analyst steps",
         "--out-md", str(RESULTS / "E_report_block_with_artifacts.md"),
         "--out-json", str(RESULTS / "E_report_block_with_artifacts.json")],
        cwd=REPO_ROOT, check=True, capture_output=True, text=True,
    )
    paper = json.loads((RESULTS / "E_report_block_paper_only.json").read_text(encoding="utf-8"))
    full = json.loads((RESULTS / "E_report_block_with_artifacts.json").read_text(encoding="utf-8"))
    files["canonical/test-e1-b1/events.safetensors"] = full["inputs"]["events_sha256"]

    rows = []
    for section, key, label in FIELDS:
        p, w = paper["fields"][key], full["fields"][key]
        rows.append({
            "section": section, "field": label,
            "paper_only": p["kind"], "with_artifacts": w["kind"],
            "with_artifacts_provenance": w.get("provenance", ""),
            "answered_only_with_artifacts": p["kind"] != "answered" and w["kind"] == "answered",
        })
    added = [(r["field"], r["with_artifacts_provenance"]) for r in rows if r["answered_only_with_artifacts"]]
    main_row = next(r for r in d["rows"] if r["batch"] == 1 and r["event_definition"].startswith("E1")
                    and r["rho"] == 0.40 and r["scope"] == "per_layer" and r["start_state"].startswith("(i)"))
    package_analyses = [{
        "analysis": "residency-gap decomposition (analysis D)",
        "contract": "package: event-atomic, prefetch-free, cold start; E1, rho 0.40, per-layer, persistent",
        "recoverable_gap": main_row["recoverable_gap"],
        "admission_share": main_row["admission_share"],
        "future_victim_share": main_row["future_victim_share"],
        "note": NOTE,
        "source": f"results/D_decomposition.json sha256 {sha_d}",
    }]
    summary = {
        "target": "original reported configuration (published simulator contract, rho 0.10, global, B = 1, prefetch included)",
        "counting_rule": "headline = answered fields; not_applicable counted separately (DEVIATIONS D-007)",
        "paper_only_answered": paper["answered_count"],
        "paper_only_not_applicable": paper["not_applicable_count"],
        "with_artifacts_answered": full["answered_count"],
        "with_artifacts_not_applicable": full["not_applicable_count"],
        "total_fields": len(FIELDS),
        "answered_only_with_artifacts": [{"field": f, "provenance": p} for f, p in added],
        "comparison_scope": ("paper text vs public artifact + package + documented analyst steps; "
                             "no artifact-only control (DEVIATIONS D-008)"),
        "package_analyses_not_counted": package_analyses,
        "rows": rows,
        "inputs": prereg_guard.inputs_record(lock, files),
    }
    (RESULTS / "E_delta.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def pct(x):
        return f"{100 * x:.2f}%"

    md = ["# Analysis E — reporting-block comparison", "",
          f"Target of every field: {summary['target']}. Counting: {summary['counting_rule']}.", "",
          "| section | field | paper only | with artifact, package and analyst steps | provenance |",
          "|---|---|---|---|---|"]
    md += [f"| {r['section']} | {r['field'].replace('|', chr(92) + '|')} | {r['paper_only']} | "
           f"{r['with_artifacts']} | {r['with_artifacts_provenance'] or '—'} |" for r in rows]
    listing = ", ".join(f"{f} ({p.replace('_', ' ')})" for f, p in added)
    md += ["",
           f"From the paper text alone, {summary['paper_only_answered']} of the {len(FIELDS)} reporting-block fields "
           f"are answered ({summary['paper_only_not_applicable']} more are established as not applicable); with the "
           f"public artifact, the package and the documented analyst steps, {summary['with_artifacts_answered']} are "
           f"answered ({summary['with_artifacts_not_applicable']} not applicable). The fields answered only in the "
           f"second mode, with their provenance, are: {listing}.", "",
           f"Scope: {summary['comparison_scope']}.", "",
           "## Package analyses (different contract; not entries of the block, not counted)", ""]
    for item in package_analyses:
        md += [f"- {item['analysis']} — {item['contract']}: recoverable gap {pct(item['recoverable_gap'])}, "
               f"admission share {pct(item['admission_share'])}, future-victim share {pct(item['future_victim_share'])}.",
               f"  *{item['note']}*"]
    md += ["",
           "Divergence recorded without attribution: the public text (§4.1.2) describes recording “each token in the "
           "generated sequences”; the published collection scripts run one prefill forward pass per prompt and "
           "record no generated token.", ""]
    (RESULTS / "E_delta.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("paper_only_answered", "paper_only_not_applicable",
                                              "with_artifacts_answered", "with_artifacts_not_applicable")}, indent=2))


if __name__ == "__main__":
    main()
