"""Analysis D: residency-gap decomposition (PREREG P6).

Grid: rho in {0.10, 0.20, 0.30, 0.40} x {E1, E2} x B = 1 x scope {per_layer
(main), global} x start state {(i) persistent across requests, cold start;
(ii) per-request cold reset}.  Secondary: E1, constructed B = 8, per_layer, (i).

Policies are replayed with the package's event-atomic simulator, five tie seeds,
no prefetch.  m = transferred_blocks / logical (pre-dedup); g = (m_c - m_B)/m_c;
admission share = (m_F - m_B)/(m_c - m_B); future-victim share =
(m_c - m_F)/(m_c - m_B); best causal = lowest mean m among LRU, LFU, LFRU and
Least-Stale.  Static follows scripts/freeze_static_pins.py on the training
trace of the same event definition (D-005 for its scope).

Outputs: results/D_decomposition.json, results/D_decomposition.md.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

CASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CASE_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(CASE_DIR))

import numpy as np  # noqa: E402

import prereg_guard  # noqa: E402
from moe_controller.events import EventTrace, load_event_trace, sha256_file, subset_event_trace  # noqa: E402
from moe_controller.simulation import (  # noqa: E402
    capacity_blocks_from_fractions,
    flatten_accesses,
    simulate_event_atomic,
    simulate_static_fixed,
)

RESULTS = CASE_DIR / "results"
CANONICAL = CASE_DIR / "canonical"
RHOS = (0.10, 0.20, 0.30, 0.40)
TIE_SEEDS = (11, 23, 47, 89, 131)
CAUSAL = ("lru", "lfu", "lfru", "least_stale")
ORACLES = ("belady", "belady_forced_admit")
NOTE = (
    "These are prefetch-free residency results under our replay contract and are not comparable "
    "with the prefetch-inclusive hit rates reported by MoE-Beyond."
)


def _recorded() -> dict[str, str]:
    return dict(
        reversed(line.split("  ", 1))
        for line in (CANONICAL / "HASHES.txt").read_text(encoding="utf-8").splitlines()
    )


def load_checked(name: str, recorded: dict[str, str], files: dict[str, str]) -> EventTrace:
    relative = f"{name}/events.safetensors"
    digest = sha256_file(CANONICAL / relative)
    if recorded.get(relative) != digest:
        raise RuntimeError(f"{relative} differs from canonical/HASHES.txt")
    files[f"canonical/{relative}"] = digest
    return load_event_trace(CANONICAL / name)


def with_request_indices(trace: EventTrace, name: str, recorded: dict[str, str], files: dict[str, str]) -> EventTrace:
    """E1 B = 1 traces carry request index -1; recover it from schedule.jsonl (D-005 note)."""
    if np.all(trace.request_indices >= 0):
        return trace
    relative = f"{name}/schedule.jsonl"
    digest = sha256_file(CANONICAL / relative)
    if recorded.get(relative) != digest:
        raise RuntimeError(f"{relative} differs from canonical/HASHES.txt")
    files[f"canonical/{relative}"] = digest
    step_to_request = {}
    for line in (CANONICAL / relative).read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if len(row["active_request_indices"]) != 1:
            raise RuntimeError("Per-request reset needs B = 1.")
        step_to_request[int(row["scheduler_step"])] = int(row["active_request_indices"][0])
    requests = np.asarray([step_to_request[int(s)] for s in trace.scheduler_steps], dtype=np.int32)
    return EventTrace(
        root=trace.root, manifest=trace.manifest, request_indices=requests,
        scheduler_steps=trace.scheduler_steps, forward_cycles=trace.forward_cycles, phases=trace.phases,
        layer_ids=trace.layer_ids, token_counts=trace.token_counts, offsets=trace.offsets,
        expert_ids=trace.expert_ids, assignment_counts=trace.assignment_counts, gate_mass=trace.gate_mass,
    )


def static_pins(train: EventTrace, capacity: int) -> list[int]:
    """Same rule as scripts/freeze_static_pins.py: per-layer equal quota, frequency desc, lower id."""
    blocks, _, _, _ = flatten_accesses(train)
    frequencies = np.bincount(blocks, minlength=train.num_expert_blocks)
    base, remainder = divmod(capacity, train.num_layers)
    resident: list[int] = []
    for layer in range(train.num_layers):
        quota = base + int(layer < remainder)
        start = layer * train.num_experts_per_layer
        local = np.arange(start, start + train.num_experts_per_layer)
        order = np.lexsort((local, -frequencies[start : start + train.num_experts_per_layer]))
        resident.extend(int(value) for value in local[order[:quota]])
    return resident


def transferred(trace: EventTrace, policy: str, capacity: int, scope: str, seed: int, reset: bool) -> int:
    if not reset:
        return simulate_event_atomic(trace, policy=policy, capacity_blocks=capacity, cache_scope=scope,
                                     tie_seed=seed).transferred_blocks
    total = 0
    for request in np.unique(trace.request_indices):
        part = subset_event_trace(trace, [int(request)])
        total += simulate_event_atomic(part, policy=policy, capacity_blocks=capacity, cache_scope=scope,
                                       tie_seed=seed).transferred_blocks
    return total


def condition(trace: EventTrace, train: EventTrace | None, rho: float, scope: str, reset: bool) -> dict:
    (capacity,) = capacity_blocks_from_fractions(trace, [rho])
    logical = int(trace.assignment_counts.sum())
    m: dict[str, dict] = {}
    for policy in CAUSAL + ORACLES:
        values = [transferred(trace, policy, capacity, scope, seed, reset) / logical for seed in TIE_SEEDS]
        m[policy] = {"mean": float(np.mean(values)), "min": float(min(values)), "max": float(max(values))}
    if train is not None and scope == "per_layer" and not reset:
        result = simulate_static_fixed(trace, resident_blocks=static_pins(train, capacity))
        m["static"] = {"mean": result.transferred_blocks / logical, "initial_load_blocks": result.initial_load_blocks}
    else:
        reason = "global scope (PREREG §3)" if scope == "global" else "per-request reset would re-load the pinned set for every request (D-005)"
        m["static"] = {"NA": reason}
    best = min(CAUSAL, key=lambda name: m[name]["mean"])
    mc, mb, mf = m[best]["mean"], m["belady"]["mean"], m["belady_forced_admit"]["mean"]
    gap_abs = mc - mb
    return {
        "rho": rho,
        "scope": scope,
        "start_state": "(ii) per-request reset" if reset else "(i) persistent, cold start",
        "capacity_blocks": capacity,
        "logical_assignments": logical,
        "miss_fraction": m,
        "best_causal": best,
        "m_best_causal": mc,
        "m_belady": mb,
        "m_forced_admit": mf,
        "recoverable_gap": gap_abs / mc if mc else None,
        "admission_share": (mf - mb) / gap_abs if gap_abs else None,
        "future_victim_share": (mc - mf) / gap_abs if gap_abs else None,
    }


def main() -> None:
    lock = prereg_guard.verify_prereg()
    for name in ("D_decomposition.json", "D_decomposition.md"):
        if (RESULTS / name).exists():
            raise FileExistsError(f"Refusing to overwrite {RESULTS / name}")
    recorded = _recorded()
    files: dict[str, str] = {}
    sets = {
        "E1 (per-token)": ("test-e1-b1", "train-e1-b1"),
        "E2 (whole-prefill)": ("test-e2-b1", "train-e2-b1"),
    }
    rows: list[dict] = []
    for definition, (test_name, train_name) in sets.items():
        test = with_request_indices(load_checked(test_name, recorded, files), test_name, recorded, files)
        train = load_checked(train_name, recorded, files)
        for rho in RHOS:
            for scope in ("per_layer", "global"):
                for reset in (False, True):
                    row = condition(test, train, rho, scope, reset)
                    row.update({"event_definition": definition, "batch": 1, "constructed_by_this_paper": False})
                    rows.append(row)
                    print(f"{definition} rho={rho} {scope} reset={reset} done", flush=True)
    b8 = load_checked("test-e1-b8-constructed", recorded, files)
    for rho in RHOS:
        row = condition(b8, None, rho, "per_layer", False)
        row["miss_fraction"]["static"] = {"NA": "secondary condition; Static not pre-registered for B = 8"}
        row.update({"event_definition": "E1 (per-token)", "batch": 8, "constructed_by_this_paper": True})
        rows.append(row)

    payload = {"rows": rows, "note": NOTE, "inputs": prereg_guard.inputs_record(lock, files)}
    (RESULTS / "D_decomposition.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def pct(value):
        return "—" if value is None else f"{100 * value:.2f}%"

    md = ["# Analysis D — residency-gap decomposition", ""]
    groups = [
        ("Main: B = 1, per-layer, (i) persistent", lambda r: r["batch"] == 1 and r["scope"] == "per_layer" and r["start_state"].startswith("(i)")),
        ("B = 1, global, (i) persistent", lambda r: r["batch"] == 1 and r["scope"] == "global" and r["start_state"].startswith("(i)")),
        ("Alignment column: B = 1, per-layer, (ii) per-request reset", lambda r: r["batch"] == 1 and r["scope"] == "per_layer" and r["start_state"].startswith("(ii)")),
        ("Alignment column: B = 1, global, (ii) per-request reset", lambda r: r["batch"] == 1 and r["scope"] == "global" and r["start_state"].startswith("(ii)")),
        ("Secondary: B = 8 constructed by this paper, per-layer, (i)", lambda r: r["batch"] == 8),
    ]
    for title, keep in groups:
        md += [f"## {title}", "",
               "| events | ρ | best causal | m (best causal) | m (Static) | m (Belady) | m (forced-admit) | gap | admission share | future-victim share |",
               "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
        for r in filter(keep, rows):
            static = r["miss_fraction"]["static"]
            md.append(
                f"| {r['event_definition']} | {r['rho']:.2f} | {r['best_causal']} | {pct(r['m_best_causal'])} | "
                f"{pct(static['mean']) if 'mean' in static else 'NA'} | {pct(r['m_belady'])} | {pct(r['m_forced_admit'])} | "
                f"{pct(r['recoverable_gap'])} | {pct(r['admission_share'])} | {pct(r['future_victim_share'])} |"
            )
        md += ["", f"*{NOTE}*", ""]
    (RESULTS / "D_decomposition.md").write_text("\n".join(md), encoding="utf-8")
    print(RESULTS / "D_decomposition.md")


if __name__ == "__main__":
    main()
