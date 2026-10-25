# MoE-Beyond external case study — report

**Deviations from the protocol and the pre-registration** (full text in `DEVIATIONS.md`): D-001 — Location of the reporting-block generator (protocol path, not PREREG); D-002 — Seeding of the reproduction runs (clarification of PREREG P3); D-003 — R6 compares safetensors files by content, not by raw file hash (approved by the author 2026-10-18); D-004 — Post-hoc decomposition of the route-side positional agreement (approved by the author 2026-10-18); D-005 — Static under the per-request reset column (clarification of PREREG §3); D-006 — The P2 template's equivalence implication is invalid (audit F1); D-007 — Reporting-block target, classes and counting rule (audit F2); D-008 — Scope of the package-benefit claim (audit F3; replaces the P7 conclusion template). In addition, `RECON.md` §7 corrects a stage-0 descriptive statistic (test-prompt lengths); the reported version is archived under `history/`, and PREREG was unaffected.

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

The executed replay contract is per-access, so the reported counts are per-access counts. At the reported operating point every event fits within capacity under both event definitions; this is a capacity observation and does not by itself establish equal counts under per-access and event-atomic replay (DEVIATIONS D-006; regression control tests/test_fit_is_not_equivalence.py). Both reported hit rates were reproduced within tolerance.

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

## E — reporting-block comparison (target: published configuration; DEVIATIONS D-007, D-008)

| item | value |
|---|---|
| answered from the paper text | 8 of 30 (5 not applicable) |
| answered with artifact, package and analyst steps | 19 of 30 (7 not applicable) |
| answered only in the second mode, with provenance | retention decision (execution), intra-event order (if immediate) (data inspection), distinct prompt heads / finals (execution), chat template applied (code inspection), decode steps recorded (code inspection), positional token agreement (execution), expert Jaccard \| low-text-overlap (execution), cache scope (code inspection), union per layer-step (execution), capacity per layer (execution), r(s,l) = union / capacity (execution) |
| comparison scope | paper text vs public artifact + package + documented analyst steps; no artifact-only control (DEVIATIONS D-008) |
| package analysis, not counted | residency-gap decomposition (analysis D): gap 47.71%, future-victim share 96.05% (package: event-atomic, prefetch-free, cold start; E1, rho 0.40, per-layer, persistent) |

## Clean-checkout verification

See `CLEAN_CHECKOUT_VERIFICATION.md` (sha256 `96d34fedbca1725a984705ee55a725de8f1323c026886429f15ab51f68db935f`): 22 of 22 checks match.

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
        "Ran 14 tests in 0.028s",
        "",
        "OK"
      ]
    },
    "package_tests": {
      "pass": true,
      "returncode": 0,
      "tail": [
        "Ran 115 tests in 12.129s",
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

## Public paper files

| file | sha256 |
|---|---|
| case_study_macros.tex | `097d0c703804e25d826ba04d334c8c5c95a5c3b01f003b318ec1dbf4f9c7a897` |
| case_study_table.tex | `3c82c6c6e4ea0ae6bbb493052517d54a4614c8fd36f2034265213b791d2509aa` |
| case_study_section.tex | `8ca7cd997951b79b80f7c7cd9616867faf735245de62f8a031b7220c04e72db9` |
| how_to_use_walkthrough.md | `ae3d954d8cfd037bb0fcfc462d156ea941b55cc100bc6207b902106b721927dd` |
