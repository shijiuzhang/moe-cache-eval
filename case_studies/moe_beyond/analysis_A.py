"""Analysis A: execution contract, Axis-I applicability, reproduction (PREREG P1–P3).

Outputs (refuses to overwrite):
  results/A_probes/            probe files (our construction) and EXPECTED.json
  results/A_probes_raw.json    raw third-party counts per probe and seed
  results/A_confirm_raw.json   execution checks of the contract fields
  results/A_reproduction_raw.json
  results/A_contract.json      classification, P2, P3 and all input hashes
  results/A_contract.md        contract table and the frozen conclusion sentences

Protocol §7: if a reproduction falls outside tolerance, no conclusion sentence is
written; the Markdown carries only the raw numbers and a hold marker.
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

import prereg_guard  # noqa: E402
import probes  # noqa: E402
from moe_controller.events import load_event_trace, sha256_file  # noqa: E402
from moe_controller.simulation import capacity_blocks_from_fractions  # noqa: E402

RESULTS = CASE_DIR / "results"
CANONICAL = CASE_DIR / "canonical"
TPY = REPO_ROOT / "third_party" / ".venv-moebeyond" / "bin" / "python"
HARNESS = CASE_DIR / "thirdparty_harness.py"
REPORTED = {"moe_infinity_eamc": 17.0, "moe_beyond_predicted": 72.0}
TOLERANCE_PP = 2.0
THEIR_CAPACITY = int(1664 * 0.10)


class StopAnalysis(RuntimeError):
    pass


def _harness(*args: str) -> None:
    completed = subprocess.run([str(TPY), "-I", str(HARNESS), *args], capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)


def _canonical_hash_ok(relative: str) -> str:
    recorded = {}
    for line in (CANONICAL / "HASHES.txt").read_text(encoding="utf-8").splitlines():
        digest, _, path = line.partition("  ")
        recorded[path] = digest
    observed = sha256_file(CANONICAL / relative)
    if recorded.get(relative) != observed:
        raise StopAnalysis(f"{relative} differs from canonical/HASHES.txt")
    return observed


def classify_probes(raw: dict) -> dict:
    out: dict = {}
    for name, rows in raw["probes"].items():
        eligible = [r for r in rows if r["eligible_for_classification"]]
        counts = sorted({(r["probe_hits"], r["probe_misses"]) for r in eligible})
        out[name] = {
            "eligible_seeds": [r["seed"] for r in eligible],
            "excluded_seeds": [r["seed"] for r in rows if not r["eligible_for_classification"]],
            "probe_counts_observed": [{"hits": h, "misses": m} for h, m in counts],
            "consistent_across_seeds": len(counts) == 1,
        }
    a0 = out["A0"]
    if not a0["consistent_across_seeds"] or a0["probe_counts_observed"] != [{"hits": 3, "misses": 3}]:
        raise StopAnalysis(f"A0 mapping check failed: {a0}")
    a2 = out["A2"]
    if not a2["consistent_across_seeds"]:
        a2["classification"] = "inconsistent_across_seeds"
    else:
        misses = a2["probe_counts_observed"][0]["misses"]
        a2["classification"] = {4: "event_level", 6: "per_access"}.get(misses, "other")
    a1 = out["A1"]
    a1["matches_reference_12_18"] = a1["consistent_across_seeds"] and a1["probe_counts_observed"] == [
        {"hits": 12, "misses": 18}
    ]
    out["executed_contract"] = a2["classification"]
    # A1 is a mapping check: under the simulator's global LRU both retention
    # contracts give 12 / 18 on the reference trace.  A failed A1 is the only
    # conflict with A2; A2 then governs (PREREG P1).
    out["a1_a2_conflict"] = not a1["matches_reference_12_18"]
    return out


def axis_one(trace_rel: str, event_definition: str) -> list[dict]:
    trace_sha = _canonical_hash_ok(f"{trace_rel}/events.safetensors")
    trace = load_event_trace(CANONICAL / trace_rel)
    union = np.diff(trace.offsets).astype(np.int64)
    (ours,) = capacity_blocks_from_fractions(trace, [0.10])
    base, remainder = divmod(ours, trace.num_layers)
    quotas = np.asarray([base + int(layer < remainder) for layer in trace.layer_ids], dtype=np.int64)
    rows = []
    for setting, capacity in (
        ("reported point: B=1, global scope, 166 blocks (int(1664*0.10))", np.full(union.shape, THEIR_CAPACITY)),
        (f"package frame: B=1, per-layer scope, rho=0.10 (total {ours}, quotas {int(quotas.min())}-{int(quotas.max())})", quotas),
    ):
        over = union > capacity
        rows.append(
            {
                "event_definition": event_definition,
                "setting": setting,
                "events": int(union.size),
                "max_event_union": int(union.max()),
                "fraction_over_capacity": float(over.mean()),
                "all_fit": bool(not over.any()),
                "trace": trace_rel,
                "events_sha256": trace_sha,
            }
        )
    return rows


def summarize_reproduction(raw: dict) -> dict:
    summary = {}
    for path_kind, reported in REPORTED.items():
        runs = [r for r in raw["runs"] if r["path"] == path_kind]
        rates = [100.0 * r["cache_hit_rate"] for r in runs]
        mean = float(np.mean(rates))
        summary[path_kind] = {
            "reported_percent": reported,
            "per_seed_cache_hit_percent": {r["seed"]: 100.0 * r["cache_hit_rate"] for r in runs},
            "mean_cache_hit_percent": mean,
            "min_cache_hit_percent": float(min(rates)),
            "max_cache_hit_percent": float(max(rates)),
            "per_seed_prediction_hit_percent": {r["seed"]: 100.0 * r["prediction_hit_rate"] for r in runs},
            "files_used": sorted({r["files_used"] for r in runs}),
            "files_skipped_no_access": sorted({r["files_skipped_no_access"] for r in runs}),
            "absolute_difference_pp": abs(mean - reported),
            "within_tolerance": abs(mean - reported) <= TOLERANCE_PP,
        }
    return summary


def _sentences(probe: dict, p2: list[dict], p3: dict) -> list[str]:
    a2 = probe["A2"]
    lines = []
    if a2["classification"] in {"event_level", "per_access"}:
        retention = "per-access" if a2["classification"] == "per_access" else "event-level"
        misses = a2["probe_counts_observed"][0]["misses"]
        lines.append(
            f"On the in-event eviction probe, the published simulator recorded {misses} misses, "
            f"the count expected under {retention} retention; its executed replay contract is "
            f"classified as {retention}."
        )
    else:
        lines.append(
            f"On the in-event eviction probe, the published simulator recorded "
            f"{a2['probe_counts_observed']} misses, matching neither reference contract; we report "
            "the raw counts and do not classify it."
        )
    a1 = probe["A1"]
    if a1["consistent_across_seeds"]:
        a1_counts = a1["probe_counts_observed"][0]
        lines.append(
            f"On the reference trace of §2.5 the published simulator recorded {a1_counts['hits']} hits and "
            f"{a1_counts['misses']} misses, {'matching' if a1['matches_reference_12_18'] else 'not matching'} "
            "the event-atomic reference counts (12 / 18)."
        )
    for row in p2:
        setting = f"{row['setting']} with {row['event_definition']} events"
        if row["all_fit"]:
            lines.append(
                f"At {setting}, every event's expert set fits within capacity, so in-event eviction "
                "cannot occur; whatever replay semantics the simulator uses, its counts there coincide "
                "with the event-atomic contract. Axis I does not operate in this setting."
            )
        else:
            lines.append(
                f"At {setting}, a fraction {row['fraction_over_capacity']:.4f} of events exceed capacity; "
                "in that setting the replay contract affects the counts and should be declared "
                "(checklist A1–A2)."
            )
    for path_kind, item in p3.items():
        x, y = item["mean_cache_hit_percent"], item["reported_percent"]
        lines.append(
            "Running the published artifact at the reported configuration reproduced the reported "
            f"value ({x:.1f}% vs {y:.0f}%)."
        )
    return lines


def main() -> None:
    lock = prereg_guard.verify_prereg()
    files = prereg_guard.verify_third_party_files([probes_path for probes_path in ("cache_simulator/infinity_moe_sim.py",)])
    outputs = [RESULTS / name for name in (
        "A_probes", "A_probes_raw.json", "A_confirm_raw.json", "A_reproduction_raw.json",
        "A_contract.json", "A_contract.md",
    )]
    for path in outputs:
        if path.exists():
            raise FileExistsError(f"Refusing to overwrite {path}")
    RESULTS.mkdir(exist_ok=True)

    probe_dir = RESULTS / "A_probes"
    probes.write_probes(probe_dir)
    _harness("probe", "--probes", str(probe_dir), "--output", str(RESULTS / "A_probes_raw.json"))
    raw_probes = json.loads((RESULTS / "A_probes_raw.json").read_text(encoding="utf-8"))
    classification = classify_probes(raw_probes)  # raises on an A0 mismatch

    _harness("confirm", "--probes", str(probe_dir), "--output", str(RESULTS / "A_confirm_raw.json"))
    confirm = json.loads((RESULTS / "A_confirm_raw.json").read_text(encoding="utf-8"))["confirmation"]
    contract_fields = {
        "cache_retained_across_requests": {
            "value": "no; each prompt starts from a new, randomly pre-filled cache",
            "code": "infinity_moe_sim.py:211 (ExpertCache constructed per call), :86-90",
            "execution_check": confirm["stateless_between_calls"]["identical"],
        },
        "hit_denominator": {
            "value": "each actual expert access",
            "code": "infinity_moe_sim.py:242-251",
            "execution_check": confirm["denominator"]["measured_accesses"]
            == confirm["denominator"]["sentinel_plus_probe_expert_accesses"],
        },
        "prefetch_loads_counted_as_hits": {
            "value": "no; predicted experts are loaded before counting and change LRU order",
            "code": "infinity_moe_sim.py:237-239",
            "execution_check": confirm["prefetch"]["same_denominator"],
        },
    }

    p2 = axis_one("test-e1-b1", "E1 (per-token)") + axis_one("test-e2-b1", "E2 (whole-prefill)")

    _harness("reproduce", "--output", str(RESULTS / "A_reproduction_raw.json"))
    reproduction = summarize_reproduction(
        json.loads((RESULTS / "A_reproduction_raw.json").read_text(encoding="utf-8"))
    )
    hold = not all(item["within_tolerance"] for item in reproduction.values())

    for name in ("A_probes_raw.json", "A_confirm_raw.json", "A_reproduction_raw.json"):
        files[f"results/{name}"] = sha256_file(RESULTS / name)
    for path in sorted(probe_dir.iterdir()):
        files[f"results/A_probes/{path.name}"] = sha256_file(path)

    payload = {
        "P1_probes": classification,
        "contract_fields": contract_fields,
        "P2_axis_one": p2,
        "P3_reproduction": reproduction,
        "hold_for_author_review": hold,
        "inputs": prereg_guard.inputs_record(lock, files),
    }
    (RESULTS / "A_contract.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    md = ["# Analysis A — execution contract, Axis I, reproduction", ""]
    md += ["| contract field | value | code | execution check |", "|---|---|---|---|"]
    md += [f"| {k} | {v['value']} | `{v['code']}` | {v['execution_check']} |" for k, v in contract_fields.items()]
    md += ["", "| setting | events | max union | fraction over capacity |", "|---|---:|---:|---:|"]
    md += [f"| {r['setting']} — {r['event_definition']} | {r['events']} | {r['max_event_union']} | "
           f"{r['fraction_over_capacity']:.4f} |" for r in p2]
    md += ["", "| path | reported | mean over 5 seeds | min–max | files used |", "|---|---:|---:|---|---|"]
    md += [f"| {k} | {v['reported_percent']:.0f}% | {v['mean_cache_hit_percent']:.2f}% | "
           f"{v['min_cache_hit_percent']:.2f}–{v['max_cache_hit_percent']:.2f}% | {v['files_used']} |"
           for k, v in reproduction.items()]
    md.append("")
    if hold:
        md += ["**HOLD — protocol §7.** A reproduction is outside the ±2.0 pp tolerance. No conclusion "
               "sentence is written; the raw numbers go to the author first.", ""]
    else:
        md += ["## Frozen conclusion sentences", ""] + [f"- {s}" for s in _sentences(classification, p2, reproduction)] + [""]
    (RESULTS / "A_contract.md").write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({"hold_for_author_review": hold, "executed_contract": classification["executed_contract"]}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except StopAnalysis as error:
        print(f"STOP: {error}", file=sys.stderr)
        sys.exit(2)
