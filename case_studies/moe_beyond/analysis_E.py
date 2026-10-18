"""Analysis E: reporting-block delta (PREREG P7).

Both blocks are produced by the released package's own command,
``python -m moe_controller.report_block``:

* paper-only — only statements in the public text (arXiv 2508.17137v1, HTML
  hash frozen in PREREG §0), each with its section;
* with-artifacts — the reported configuration (the simulator's contract,
  rho = 0.10, global scope, B = 1, its per-token replay unit) filled from the
  public artifact and analyses A–D.

The paper-only fill is deliberately generous: a field counts as stated when
the text states it, even if only in passing, so that the delta does not
overstate what the package adds.

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

# Statements in the public text, each with its section (arXiv 2508.17137v1).
PAPER_VALUES = {
    "event_unit": ("token-by-token replay of each test prompt", "§4.1.4 Simulator"),
    "experts_topk_layers": ("64 routed (+2 shared) / 6 / 27", "§4.1.1 Models; §4.1.4 Simulator"),
    "residency_fraction": ("0.10 headline; capacity swept", "Abstract; §4.2.1"),
    "concurrency": ("1", "Abstract; §5 Limitations"),
    "service_discipline": ("one prompt replayed at a time", "§4.1.4 Simulator"),
    "miss_denominator": ("per ground-truth expert activation", "§4.1.4; §4.2.1 GPU Cache Hit Rate"),
    "offline_bound_reported": ("no", "no offline optimum in §4.2 Results"),
    # Generous inferences, each from an explicit statement or a consistent absence:
    "conformance_trace": ("no", "no conformance or reference trace appears in §4.1.4"),
    "position_locked_cohorts": ("no (batch size one)", "Abstract; §5 Limitations"),
    "dedup_credited_to_policy": ("no (batch size one)", "Abstract; §5 Limitations"),
    "static_fit_source": ("n/a (only MoE-Infinity is compared)", "§4.1.3 Baseline"),
    "static_quota_rule": ("n/a (only MoE-Infinity is compared)", "§4.1.3 Baseline"),
    "initial_pinned_load_counted": ("n/a (only MoE-Infinity is compared)", "§4.1.3 Baseline"),
}


def _paper_only(out_md: Path, out_json: Path) -> None:
    args = [sys.executable, "-I", "-m", "moe_controller.report_block", "--paper-only",
            "--title", "MoE-Beyond — reporting block from the public text only",
            "--out-md", str(out_md), "--out-json", str(out_json)]
    for key, (value, source) in PAPER_VALUES.items():
        args += ["--paper", f"{key}={value}@{source}"]
    subprocess.run(args, cwd=REPO_ROOT, check=True, capture_output=True, text=True)


def _intra_event_order(files: dict[str, str]) -> tuple[str, str]:
    source = CANONICAL / "test-e1-source"
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    rows = ascending = 0
    for shard in manifest["shards"]:
        path = source / shard["tensor_file"]
        files[f"canonical/test-e1-source/{shard['tensor_file']}"] = sha256_file(path)
        with safe_open(path, framework="pt") as handle:
            lengths = handle.get_tensor("sequence_lengths").tolist()
            indices = handle.get_tensor("topk_indices").numpy()
        for local, length in enumerate(lengths):
            block = indices[local, :, :length, :].reshape(-1, indices.shape[-1])
            rows += block.shape[0]
            ascending += int(np.all(np.diff(block, axis=1) > 0, axis=1).sum())
    return f"ascending id ({ascending} of {rows} rows ascending in the replayed files)", files[
        f"canonical/test-e1-source/{manifest['shards'][0]['tensor_file']}"]


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
    for name in ("A_contract.json", "C_workload.json", "D_decomposition.json"):
        files[f"results/{name}"] = sha256_file(RESULTS / name)
    a = json.loads((RESULTS / "A_contract.json").read_text(encoding="utf-8"))
    c = json.loads((RESULTS / "C_workload.json").read_text(encoding="utf-8"))
    d = json.loads((RESULTS / "D_decomposition.json").read_text(encoding="utf-8"))
    sha_a, sha_c, sha_d = (files[f"results/{n}"] for n in ("A_contract.json", "C_workload.json", "D_decomposition.json"))
    inputs_sha = prereg_guard.read_lock()["inputs_manifest_sha256"]

    order_value, order_sha = _intra_event_order(files)
    route = c["route_side"]
    (their_row,) = [
        r for r in d["rows"]
        if r["batch"] == 1 and r["event_definition"].startswith("E1") and r["rho"] == 0.10
        and r["scope"] == "global" and r["start_state"].startswith("(ii)")
    ]
    retention = a["P1_probes"]["executed_contract"]

    def fact(value, source):
        return {"value": value, "kind": "computed", "source": source}

    facts = {"fields": {
        "event_unit": fact(f"{retention.replace('_', '-')} (probe A2, five seeds)", f"results/A_contract.json sha256 {sha_a}"),
        "retention_decision": fact("immediate" if retention == "per_access" else "event boundary", f"probe A2; results/A_contract.json sha256 {sha_a}"),
        "intra_event_order": fact(order_value, f"canonical/test-e1-source sha256 {order_sha}"),
        "conformance_trace": fact("no (none in the public repository)", f"INPUTS.sha256 sha256 {inputs_sha}"),
        "templates_per_category": {"value": "no category labels in the public artifact", "kind": "NA", "source": ""},
        "distinct_prompt_heads_finals": fact(
            f"{c['prompt_side']['distinct_prompt_heads_70_chars']} / {c['prompt_side']['distinct_final_lines']}",
            f"results/C_workload.json sha256 {sha_c}"),
        "chat_template_applied": fact("no", f"collection scripts; results/C_workload.json sha256 {sha_c}"),
        "decode_steps_recorded": fact(0, f"collection scripts; results/C_workload.json sha256 {sha_c}"),
        "position_locked_cohorts": fact("no (B = 1)", f"results/A_contract.json sha256 {sha_a}"),
        "unique_generated_sequences": {"value": "no generated tokens are recorded; input sequences 48 / 48 unique",
                                       "kind": "NA", "source": ""},
        "positional_token_agreement": fact(
            {"mean": route["token_positional_agreement_mean"], "p95": route["token_positional_agreement_p95"],
             "scope": "input sequences, first 48 records; post-hoc decomposition in C_exploratory_positional (D-004)"},
            f"results/C_workload.json sha256 {sha_c}"),
        "expert_jaccard_low_text_overlap": fact(route["expert_jaccard_low_token_mean"], f"results/C_workload.json sha256 {sha_c}"),
        "effect_stable_across_position_bands": {"value": "no category labels or matched template arm", "kind": "NA", "source": ""},
        "service_discipline": fact("one prompt replayed at a time; cache rebuilt for every prompt",
                                   f"results/A_contract.json sha256 {sha_a}"),
        "miss_denominator": fact("per expert access, pre-dedup (no dedup at B = 1)", f"results/A_contract.json sha256 {sha_a}"),
        "dedup_credited_to_policy": fact("no (B = 1, nothing to deduplicate)", f"results/A_contract.json sha256 {sha_a}"),
        "static_fit_source": fact("n/a (no static policy in the reported comparison)", f"results/A_contract.json sha256 {sha_a}"),
        "static_quota_rule": fact("n/a", f"results/A_contract.json sha256 {sha_a}"),
        "initial_pinned_load_counted": fact("n/a; each prompt starts from a random pre-fill and its first 10 tokens are not counted",
                                            f"results/A_contract.json sha256 {sha_a}"),
        "offline_bound_reported": fact(
            "not in the study; this package supplies a prefetch-free Belady bound (analysis D), "
            "not comparable with the prefetch-inclusive rates", f"results/D_decomposition.json sha256 {sha_d}"),
        "forced_admission_decomposition": fact(
            {"admission_share": their_row["admission_share"], "future_victim_share": their_row["future_victim_share"],
             "contract": "prefetch-free, E1, rho 0.10, global, per-request reset; not comparable with prefetch-inclusive rates"},
            f"results/D_decomposition.json sha256 {sha_d}"),
        "absolute_bytes_per_output_token": {"value": "no output tokens are generated and expert byte sizes are not in the artifact",
                                            "kind": "NA", "source": ""},
    }}
    (RESULTS / "E_facts.json").write_text(json.dumps(facts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    files["results/E_facts.json"] = sha256_file(RESULTS / "E_facts.json")

    _paper_only(RESULTS / "E_report_block_paper_only.md", RESULTS / "E_report_block_paper_only.json")
    subprocess.run(
        [sys.executable, "-I", "-m", "moe_controller.report_block",
         "--events", str(CANONICAL / "test-e1-b1"), "--rho", "0.10", "--scope", "global",
         "--facts", str(RESULTS / "E_facts.json"),
         "--declare", "bandwidth_budget_assumed=only the original authors can state the bandwidth they assumed",
         "--title", "MoE-Beyond — reporting block with the public artifact and the released package",
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
            "added_by_package": p["kind"] not in {"computed", "paper"} and w["kind"] == "computed",
        })
    added = [row["field"] for row in rows if row["added_by_package"]]
    summary = {
        "paper_only_filled": paper["filled_count"],
        "with_artifacts_filled": full["filled_count"],
        "total_fields": len(FIELDS),
        "delta": full["filled_count"] - paper["filled_count"],
        "fields_only_the_package_made_fillable": added,
        "rows": rows,
        "inputs": prereg_guard.inputs_record(lock, files),
    }
    (RESULTS / "E_delta.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    md = ["# Analysis E — reporting-block delta", "",
          f"Paper text alone: **{summary['paper_only_filled']} of {len(FIELDS)}** fields. "
          f"Public artifact with the released package: **{summary['with_artifacts_filled']} of {len(FIELDS)}**.", "",
          "| section | field | paper only | with artifact + package | added by package |", "|---|---|---|---|---|"]
    md += [f"| {r['section']} | {r['field'].replace('|', chr(92) + '|')} | {r['paper_only']} | {r['with_artifacts']} | {'yes' if r['added_by_package'] else ''} |" for r in rows]
    md += ["", f"From the paper text alone, {summary['paper_only_filled']} of the 30 reporting-block fields can be filled; "
           f"with the public artifact and the released package, {summary['with_artifacts_filled']} can be filled. "
           f"The fields that only the package made fillable are: {', '.join(added)}.", "",
           "*Oracle-field values computed here are prefetch-free residency results under our replay contract and are not "
           "comparable with the prefetch-inclusive hit rates reported by MoE-Beyond.*", "",
           "Divergence recorded without attribution: the public text (§4.1.2) describes recording “each token in the "
           "generated sequences”; the published collection scripts run one prefill forward pass per prompt and record no "
           "generated token.", ""]
    (RESULTS / "E_delta.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("paper_only_filled", "with_artifacts_filled", "delta")}, indent=2))


if __name__ == "__main__":
    main()
