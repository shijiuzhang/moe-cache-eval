#!/usr/bin/env python3
"""Tie-aware victim-ranking quality of a causal next-use predictor.

Regression accuracy over all accesses is the wrong measure for an eviction rule:
what matters is the ordering among the blocks resident at the moment of
decision, and whether the chosen victim is *an* optimal victim rather than the
particular one an arbitrary tie-break selects.

This script replays the predicted-next-use policy under event-atomic semantics
and, at deterministically sampled eviction decisions, records:

  * the tie-aware optimal-victim set (all candidates attaining the maximum true
    next-use key) and whether each policy's choice lands in it;
  * Spearman rank correlation using average ranks for ties, over all candidates
    and again excluding candidates that are never used again;
  * normalized distance regret of the chosen victim;
  * the same quantities for random, LRU and LFRU victims chosen at the identical
    cache state, so that "no usable signal" has a calibrated meaning.

Uncertainty is reported by cluster bootstrap over scheduler steps, because
eviction decisions within a step are not independent.

Outputs a manifest, a per-sample CSV and the input hashes.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from moe_controller import simulation as sim  # noqa: E402
from moe_controller.events import load_event_trace  # noqa: E402

FEATURES = [
    "log_recency", "first_seen", "log_freq", "log_inter_gap",
    "gate_mass", "log_concurrent", "layer_frac", "popularity_rate",
]


# --------------------------------------------------------------------------
# predictor
# --------------------------------------------------------------------------


def build_features(trace, block_ids: np.ndarray) -> np.ndarray:
    n = len(block_ids)
    n_blocks = trace.num_expert_blocks
    gate = np.asarray(trace.gate_mass, dtype=np.float32)
    conc = np.asarray(trace.assignment_counts, dtype=np.float32)
    last = np.full(n_blocks, -1, dtype=np.int64)
    seen = np.zeros(n_blocks, dtype=np.int64)
    prev_gap = np.zeros(n_blocks, dtype=np.float32)
    recency = np.empty(n, dtype=np.float32)
    first = np.zeros(n, dtype=np.float32)
    freq = np.empty(n, dtype=np.float32)
    inter = np.empty(n, dtype=np.float32)
    for i in range(n):
        b = block_ids[i]
        if last[b] < 0:
            recency[i] = 0.0
            first[i] = 1.0
            inter[i] = 0.0
        else:
            gap = float(i - last[b])
            recency[i] = gap
            inter[i] = prev_gap[b] if prev_gap[b] > 0 else gap
            prev_gap[b] = gap
        seen[b] += 1
        freq[i] = seen[b]
        last[b] = i
    pos = np.arange(1, n + 1, dtype=np.float32)
    return np.column_stack([
        np.log1p(recency), first, np.log1p(freq), np.log1p(inter),
        gate, np.log1p(conc),
        (block_ids // trace.num_experts_per_layer).astype(np.float32)
        / trace.num_layers,
        np.log1p(freq) / np.log1p(pos) * 1e3,
    ]).astype(np.float32)


def next_event_per_access(trace) -> tuple[np.ndarray, int]:
    sentinel = trace.num_events + 1
    nxt = np.full(trace.num_accesses, sentinel, dtype=np.int64)
    last: dict[int, int] = {}
    for ev in range(trace.num_events - 1, -1, -1):
        start = int(trace.offsets[ev])
        blocks = trace.block_ids_for_event(ev)
        for off, b in enumerate(blocks):
            nxt[start + off] = last.get(int(b), sentinel)
        for b in blocks:
            last[int(b)] = ev
    return nxt, sentinel


def fit_predictor(trace) -> np.ndarray:
    blocks, _, _, _ = sim.flatten_accesses(trace)
    nxt, sentinel = next_event_per_access(trace)
    ev_of = np.repeat(np.arange(trace.num_events), np.diff(trace.offsets))
    dist = np.where(nxt >= sentinel, trace.num_events, nxt - ev_of)
    y = np.log1p(dist.astype(np.float64))
    X = build_features(trace, blocks)
    A = np.column_stack([X, np.ones(len(X), dtype=np.float32)])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    return coef


# --------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------


def rankdata_average(a: np.ndarray) -> np.ndarray:
    """Ranks with ties assigned the average rank (scipy 'average' method)."""
    order = np.argsort(a, kind="stable")
    ranks = np.empty(len(a), dtype=np.float64)
    sorted_a = a[order]
    i = 0
    while i < len(a):
        j = i
        while j + 1 < len(a) and sorted_a[j + 1] == sorted_a[i]:
            j += 1
        ranks[order[i:j + 1]] = 0.5 * (i + j) + 1.0
        i = j + 1
    return ranks


def spearman_tied(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3:
        return float("nan")
    rx = rankdata_average(x)
    ry = rankdata_average(y)
    rx = rx - rx.mean()
    ry = ry - ry.mean()
    denom = np.sqrt((rx * rx).sum() * (ry * ry).sum())
    return float((rx * ry).sum() / denom) if denom > 0 else float("nan")


def cluster_bootstrap(values: np.ndarray, clusters: np.ndarray,
                      reps: int = 2000, seed: int = 20260802) -> tuple[float, float]:
    """Percentile CI resampling whole clusters (scheduler steps)."""
    rng = np.random.default_rng(seed)
    uniq, inv = np.unique(clusters, return_inverse=True)
    by = [np.flatnonzero(inv == k) for k in range(len(uniq))]
    means = np.empty(reps)
    finite = np.isfinite(values)
    for r in range(reps):
        pick = rng.integers(0, len(by), len(by))
        idx = np.concatenate([by[p] for p in pick])
        v = values[idx]
        v = v[np.isfinite(v)]
        means[r] = v.mean() if v.size else np.nan
    lo, hi = np.nanpercentile(means, [2.5, 97.5])
    return float(lo), float(hi)


# --------------------------------------------------------------------------
# instrumented replay
# --------------------------------------------------------------------------


def replay(trace, capacity: int, true_key_acc: np.ndarray,
           pred_key_acc: np.ndarray, sentinel: int,
           stride: int, seed: int) -> tuple[list[dict], int]:
    rng = np.random.default_rng(seed)
    n_layers = trace.num_layers
    base, rem = capacity // n_layers, capacity % n_layers
    quota = np.array([base + (l < rem) for l in range(n_layers)], dtype=np.int64)

    resident = np.zeros(trace.num_expert_blocks, dtype=bool)
    size = np.zeros(n_layers, dtype=np.int64)
    key_pred = np.full(trace.num_expert_blocks, sentinel, dtype=np.int64)
    key_true = np.full(trace.num_expert_blocks, sentinel, dtype=np.int64)
    last_acc = np.full(trace.num_expert_blocks, -1, dtype=np.int64)
    freq = np.zeros(trace.num_expert_blocks, dtype=np.int64)
    members: list[set] = [set() for _ in range(n_layers)]

    rows: list[dict] = []
    decisions = 0
    clock = 0
    horizon = float(trace.num_events)

    for ev in range(trace.num_events):
        start, end = int(trace.offsets[ev]), int(trace.offsets[ev + 1])
        blocks = trace.block_ids_for_event(ev)
        layer = int(trace.layer_ids[ev])
        step = int(trace.scheduler_steps[ev])
        res_mask = resident[blocks]
        for off in range(len(blocks)):
            b = int(blocks[off])
            key_pred[b] = pred_key_acc[start + off]
            key_true[b] = true_key_acc[start + off]
            clock += 1
            last_acc[b] = clock
            freq[b] += 1
        for b in np.unique(blocks[~res_mask]):
            b = int(b)
            if resident[b]:
                continue
            if size[layer] >= quota[layer]:
                cand = np.fromiter(members[layer], dtype=np.int64)
                if cand.size == 0:
                    continue
                kp, kt = key_pred[cand], key_true[cand]
                victim = int(cand[np.argmax(kp)])
                decisions += 1
                if decisions % stride == 0 and cand.size >= 3:
                    best = kt.max()
                    opt = cand[kt == best]
                    optset = set(int(x) for x in opt)
                    lru_v = int(cand[np.argmin(last_acc[cand])])
                    age = np.maximum(clock - last_acc[cand], 1)
                    lfru_v = int(cand[np.argmin(freq[cand] / age)])
                    rand_v = int(cand[rng.integers(0, cand.size)])
                    finite = kt < sentinel
                    rows.append(dict(
                        scheduler_step=step, layer=layer, candidates=int(cand.size),
                        optimal_set_size=int(opt.size),
                        never_again_candidates=int((~finite).sum()),
                        pred_hits_optimal=int(victim in optset),
                        random_hits_optimal=int(rand_v in optset),
                        lru_hits_optimal=int(lru_v in optset),
                        lfru_hits_optimal=int(lfru_v in optset),
                        spearman_all=spearman_tied(kp.astype(float), kt.astype(float)),
                        spearman_finite=(
                            spearman_tied(kp[finite].astype(float),
                                          kt[finite].astype(float))
                            if finite.sum() >= 3 else float("nan")
                        ),
                        regret_pred=float((best - key_true[victim]) / horizon),
                        regret_random=float((best - key_true[rand_v]) / horizon),
                        regret_lru=float((best - key_true[lru_v]) / horizon),
                        regret_lfru=float((best - key_true[lfru_v]) / horizon),
                    ))
                if key_pred[b] > key_pred[victim]:
                    continue
                resident[victim] = False
                members[layer].discard(victim)
                size[layer] -= 1
            resident[b] = True
            members[layer].add(b)
            size[layer] += 1
    return rows, decisions


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fit-events", required=True)
    ap.add_argument("--eval-events", required=True)
    ap.add_argument("--capacity-blocks", type=int, default=2458)
    ap.add_argument("--stride", type=int, default=37)
    ap.add_argument("--seed", type=int, default=20260802)
    ap.add_argument("--bootstrap-reps", type=int, default=2000)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    ftr = load_event_trace(Path(args.fit_events))
    coef = fit_predictor(ftr)

    etr = load_event_trace(Path(args.eval_events))
    eb, _, _, _ = sim.flatten_accesses(etr)
    true_key, sentinel = next_event_per_access(etr)
    X = build_features(etr, eb)
    pred_log = np.column_stack([X, np.ones(len(X), dtype=np.float32)]) @ coef
    ev_of = np.repeat(np.arange(etr.num_events), np.diff(etr.offsets))
    pidx = ev_of + np.maximum(np.expm1(np.clip(pred_log, 0, 25)), 1.0)
    pred_key = np.where(pidx >= etr.num_events, sentinel, pidx).astype(np.int64)

    rows, decisions = replay(etr, args.capacity_blocks, true_key, pred_key,
                             sentinel, args.stride, args.seed)

    args.output.mkdir(parents=True, exist_ok=True)
    csv_path = args.output / "victim-decisions.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    arr = {k: np.array([r[k] for r in rows], dtype=float) for k in rows[0]}
    clusters = arr["scheduler_step"]
    summary = {}
    for key in ["pred_hits_optimal", "random_hits_optimal", "lru_hits_optimal",
                "lfru_hits_optimal", "spearman_all", "spearman_finite",
                "regret_pred", "regret_random", "regret_lru", "regret_lfru"]:
        v = arr[key]
        lo, hi = cluster_bootstrap(v, clusters, args.bootstrap_reps, args.seed)
        summary[key] = {
            "mean": float(np.nanmean(v)),
            "ci95_low": lo, "ci95_high": hi,
        }

    manifest = {
        "kind": "victim_rank_quality_tie_aware",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "inputs": {
            "fit_events": str(args.fit_events),
            "fit_manifest_sha256": sha256_file(Path(args.fit_events) / "manifest.json"),
            "eval_events": str(args.eval_events),
            "eval_manifest_sha256": sha256_file(Path(args.eval_events) / "manifest.json"),
            "predictor": "ordinary least squares on 8 causal features",
            "features": FEATURES,
            "coefficients": [float(c) for c in coef],
        },
        "config": {
            "capacity_blocks": args.capacity_blocks,
            "cache_scope": "per_layer",
            "replay": "event_atomic",
            "policy": "predicted-next-use eviction with predicted bypass admission",
            "sampling": f"every {args.stride}th eviction decision with >=3 candidates",
            "seed": args.seed,
            "bootstrap": f"cluster bootstrap over scheduler steps, {args.bootstrap_reps} reps",
            "tie_handling": (
                "optimal victim set = all candidates attaining the maximum true "
                "next-use key; Spearman uses average ranks for ties; the "
                "spearman_finite variant drops candidates never used again"
            ),
        },
        "counts": {
            "eviction_decisions": decisions,
            "sampled_decisions": len(rows),
            "mean_candidates": float(np.mean(arr["candidates"])),
            "mean_optimal_set_size": float(np.mean(arr["optimal_set_size"])),
            "mean_never_again_candidates": float(np.mean(arr["never_again_candidates"])),
            "distinct_scheduler_steps": int(len(np.unique(clusters))),
        },
        "summary": summary,
        "artifacts": {"decisions_csv": csv_path.name,
                      "decisions_csv_sha256": sha256_file(csv_path)},
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"counts": manifest["counts"], "summary": summary}, indent=2))
    print("->", args.output)


if __name__ == "__main__":
    main()
