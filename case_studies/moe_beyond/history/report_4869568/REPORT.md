# MoE-Beyond external case study — report

Public historical copy: correspondence omitted and journal-specific header comments removed. Numerical analyses are unchanged; the original copy is retained privately.

**Deviations from the protocol and the pre-registration** (full text in `DEVIATIONS.md`): D-001 — Location of the reporting-block generator (protocol path, not PREREG); D-002 — Seeding of the reproduction runs (clarification of PREREG P3); D-003 — R6 compares safetensors files by content, not by raw file hash (approved by the author 2026-10-18); D-004 — Post-hoc decomposition of the route-side positional agreement (approved by the author 2026-10-18); D-005 — Static under the per-request reset column (clarification of PREREG §3). In addition, `RECON.md` §7 corrects a stage-0 descriptive statistic (test-prompt lengths); the reported version is archived under `history/`, and PREREG was unaffected.

Pre-registration: `PREREG.md` sha256 `187427d8f9173f644d597bab27283864c2df6d3e5089a34fcdc20fc16170a69d`, commit `08938d1e4a9240b6afbb3017ed499468df1895bf`. Third-party commit `47031eefc7808e996ecd5c01d7ed90aa32e32514`.

## A — execution contract, Axis I, reproduction

| item | value |
|---|---|
| probe A0 (seeds [11, 23, 47, 89, 131]) | 3 hits / 3 misses |
| probe A1 (seeds [11, 23, 47, 89, 131]) | 12 hits / 18 misses |
| probe A2 (seeds [11, 23, 47, 89, 131]) | 0 hits / 6 misses |
| executed contract | per_access |
| cache_retained_across_requests | no; each prompt starts from a new, randomly pre-filled cache (execution check: True) |
| hit_denominator | each actual expert access (execution check: True) |
| prefetch_loads_counted_as_hits | no; predicted experts are loaded before counting and change LRU order (execution check: True) |
| reported point: B=1, global scope, 166 blocks (int(1664*0.10)) — E1 (per-token) | fraction over capacity 0.0000 |
| package frame: B=1, per-layer scope, rho=0.10 (total 166, quotas 6-7) — E1 (per-token) | fraction over capacity 0.0000 |
| reported point: B=1, global scope, 166 blocks (int(1664*0.10)) — E2 (whole-prefill) | fraction over capacity 0.0000 |
| package frame: B=1, per-layer scope, rho=0.10 (total 166, quotas 6-7) — E2 (whole-prefill) | fraction over capacity 1.0000 |
| reproduction moe_beyond_predicted | 72.37% vs reported 72% (within ±2.0 pp: True; files used 80) |
| reproduction moe_infinity_eamc | 16.86% vs reported 17% (within ±2.0 pp: True; files used 80) |

The executed replay contract is per-access. At the reported operating point every event fits within capacity under both event definitions, so Axis I does not operate there. Both reported hit rates were reproduced within tolerance.

## B — operating regime

| events | B | ρ | r̄ | r p95 | fraction r > 1 |
|---|---:|---:|---:|---:|---:|
| E1 (per-token) | 1 | 0.10 | 0.945 | 1.000 | 0.0000 |
| E1 (per-token) | 1 | 0.20 | 0.469 | 0.500 | 0.0000 |
| E1 (per-token) | 1 | 0.30 | 0.313 | 0.316 | 0.0000 |
| E1 (per-token) | 1 | 0.40 | 0.234 | 0.240 | 0.0000 |
| E2 (whole-prefill) | 1 | 0.10 | 6.203 | 8.333 | 1.0000 |
| E2 (whole-prefill) | 1 | 0.20 | 3.081 | 4.083 | 0.9988 |
| E2 (whole-prefill) | 1 | 0.30 | 2.054 | 2.684 | 0.9473 |
| E2 (whole-prefill) | 1 | 0.40 | 1.540 | 2.040 | 0.9092 |
| E1 (per-token) (constructed by this paper) | 2 | 0.10 | 1.749 | 2.000 | 0.9833 |
| E1 (per-token) (constructed by this paper) | 2 | 0.20 | 0.867 | 1.000 | 0.0000 |
| E1 (per-token) (constructed by this paper) | 2 | 0.30 | 0.579 | 0.632 | 0.0000 |
| E1 (per-token) (constructed by this paper) | 2 | 0.40 | 0.433 | 0.480 | 0.0000 |
| E1 (per-token) (constructed by this paper) | 4 | 0.10 | 3.074 | 3.667 | 0.9958 |
| E1 (per-token) (constructed by this paper) | 4 | 0.20 | 1.525 | 1.769 | 0.9879 |
| E1 (per-token) (constructed by this paper) | 4 | 0.30 | 1.017 | 1.200 | 0.5112 |
| E1 (per-token) (constructed by this paper) | 4 | 0.40 | 0.762 | 0.885 | 0.0000 |
| E1 (per-token) (constructed by this paper) | 8 | 0.10 | 4.895 | 6.000 | 0.9934 |
| E1 (per-token) (constructed by this paper) | 8 | 0.20 | 2.428 | 2.917 | 0.9885 |
| E1 (per-token) (constructed by this paper) | 8 | 0.30 | 1.619 | 1.895 | 0.9725 |
| E1 (per-token) (constructed by this paper) | 8 | 0.40 | 1.214 | 1.440 | 0.9151 |

- Placement at ρ = 40%: E1 (per-token) r̄ = 0.234; nearest Table 11 point 128-expert, B = 2 (r̄ = 0.293); within measured range: True.
- Placement at ρ = 40%: E2 (whole-prefill) r̄ = 1.540; nearest Table 11 point 64-expert, B = 8 (r̄ = 1.44); within measured range: True.

## C — workload construction

| item | value |
|---|---|
| distinct heads / finals (100 test prompts) | 100 / 100 |
| word 5-gram Jaccard p95 | 0.0000 |
| prompt-side flag | False |
| route-side positional agreement p95 (first 48) | 0.2857 |
| §5.8 detector flag | True |
| post hoc (D-004): p95 with position 0 excluded | 0.1429 |
| post hoc (D-004): pairs agreeing only at position 0 | 72.3% |

The pre-registered flag is true and stands. The agreement sits at a shared BOS token and the question opener in 3–38-token sequences, which exposes the detector's length sensitivity.

## D — residency-gap decomposition (main: B = 1, per-layer, persistent)

| events | ρ | best causal | gap | admission share | future-victim share |
|---|---:|---|---:|---:|---:|
| E1 (per-token) | 0.10 | lfru | 25.13% | 62.42% | 37.58% |
| E1 (per-token) | 0.20 | lfru | 34.69% | 15.06% | 84.94% |
| E1 (per-token) | 0.30 | lfru | 42.34% | 6.86% | 93.14% |
| E1 (per-token) | 0.40 | lfu | 47.71% | 3.95% | 96.05% |
| E2 (whole-prefill) | 0.10 | lfu | 0.30% | 7.19% | 92.81% |
| E2 (whole-prefill) | 0.20 | lfu | 2.48% | 65.89% | 34.11% |
| E2 (whole-prefill) | 0.30 | lfu | 6.93% | 171.35% | -71.35% |
| E2 (whole-prefill) | 0.40 | lfu | 14.20% | 194.06% | -94.06% |

*These are prefetch-free residency results under our replay contract and are not comparable with the prefetch-inclusive hit rates reported by MoE-Beyond.*

Shares outside [0, 1] occur where forced admission is worse than the best causal policy (most events over quota); the §7.2 decomposition is not interpretable there. Full grid in `results/D_decomposition.md`.

## E — reporting-block delta

| fields filled from the paper text | 13 of 30 |
|---|---|
| fields filled with the artifact and the package | 25 of 30 |
| added by the package | retention decision, intra-event order (if immediate), distinct prompt heads / finals, chat template applied, decode steps recorded, positional token agreement, expert Jaccard | low-text-overlap, cache scope, union per layer-step, capacity per layer, r(s,l) = union / capacity, forced-admission decomposition |

## Final R6 regression

```json
{
  "a": {
    "hits": 12,
    "misses": 18,
    "pass": true
  },
  "b": {
    "cache-events-controller-probe-v0.1.3-olmoe-decode64-fcfs-b1-v1": {
      "arrival_offsets_all_zero": true,
      "events_content_equal": true,
      "frozen_events_match_manifest": true,
      "pass": true,
      "requests_byte_equal": true,
      "schedule_byte_equal_after_dropping_arrival_offsets": true
    },
    "cache-events-controller-probe-v0.1.3-olmoe-decode64-fcfs-b8-v1": {
      "arrival_offsets_all_zero": true,
      "events_content_equal": true,
      "frozen_events_match_manifest": true,
      "pass": true,
      "requests_byte_equal": true,
      "schedule_byte_equal_after_dropping_arrival_offsets": true
    }
  },
  "c": {
    "frozen_payload_sha256": "60464b33e6e7d82eeab2879822ab019412a00092b78507c5c37b821b0c44eba2",
    "headers_equal": true,
    "pass": true,
    "resaved_payload_sha256": "60464b33e6e7d82eeab2879822ab019412a00092b78507c5c37b821b0c44eba2"
  },
  "d": {
    "case_study_tests": {
      "pass": true,
      "returncode": 0,
      "tail": [
        "Ran 12 tests in 0.015s",
        "",
        "OK"
      ]
    },
    "package_tests": {
      "pass": true,
      "returncode": 0,
      "tail": [
        "Ran 114 tests in 12.076s",
        "",
        "OK"
      ]
    }
  },
  "overall_pass": true
}
```

## Forbidden-word check (protocol §6.5)

No hits.

## Delivery checklist (protocol §8)

- [x] R6 passes on the final code; output above (`overall_pass`: True).
- [x] `PREREG.lock` committed 2026-10-18T22:25:08+08:00; first result committed 2026-10-18T22:53:04+08:00 5170aba.
- [x] Every `results/*.json` carries `inputs`.
- [x] Paper draft numbers come only from `\CS*` macros (`make_macros.py`).
- [x] Forbidden-word check attached (no hits).
- [x] No third-party data or code in git history.
- [x] Every table with Belady or gap carries the non-comparability note.
- [x] Every constructed B > 1 result is labelled “constructed by this paper”.
- [x] The first paragraph lists every deviation.

## Public historical paper files

| file | sha256 |
|---|---|
| case_study_macros.tex | `a961ba84c8592106c4e9bd7e70e6694656089c4a85cb5f11786c5481f4ebd84d` |
| case_study_table.tex | `7bd93feaa4b1e5b083d0e546f2642fdf8bc60b627535720f2186f0bf05b3fe79` |
| case_study_section.tex | `bddf7ab76afbe8466ef18f0c6ce54fc889e5f4c3bee3ec9be475583970850754` |
| how_to_use_walkthrough.md | `6628d7fc7fe01d17ed74a0d4943aa7b5da693ae39c2711ea308a6608f673c35d` |
