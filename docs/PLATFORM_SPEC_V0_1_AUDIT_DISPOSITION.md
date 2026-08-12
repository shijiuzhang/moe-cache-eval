# Disposition of the independent audit of Platform specification v0.1

**Date:** 2026-08-12  
**Audited input:** commit `b709412`  
**Audit:** `docs/PLATFORM_SPEC_V0_1_AUDIT.md`  
**Revised specification:** `docs/PLATFORM_PRODUCT_SPECIFICATION_V0_1.md`  
**Status:** all B1–B6 and S1–S5 accepted; ready for audit recheck

This file records how each requested change was handled. It is not a substitute
for reviewing the revised normative text.

## Blocking findings

| ID | Disposition | Revised contract |
|---|---|---|
| B1 | **Accepted** | §4 splits releases. v0.1 is M1 only: contracts/hashes, OpenAI adapter, deterministic server, open/closed load generation, raw observations/metrics, self-calibration, private evidence and `verify`. SLO adjudication, sweeps, comparison, goodput and HTML reports move to v0.2. §15, §16, §21, CLI examples and README are synchronized with this boundary. |
| B2 | **Accepted with measurement clarification** | §7.5 requires same-runner local null-endpoint calibration and records schedule lag, timing overheads, arrival realization, CPU and event-loop load. Threshold decisions inside calibrated resolution become `INSUFFICIENT_EVIDENCE`; configuration differences inside combined resolution become `within_noise` and cannot drive ranking or attribution. Calibration is not subtracted from SUT measurements and does not claim to capture remote-network variability. V01-AC4 and V02-AC1 supply controls. |
| B3 | **Accepted** | §7.7 makes the full ordered compliance vector primary and derives both `max_compliant_load` and `min_non_compliant_load`. A failure below a pass raises `non_monotonic_compliance` and defaults to overall `INSUFFICIENT_EVIDENCE`. V02-AC3 contains both non-monotonic positive controls. |
| B4 | **Accepted** | §9.2 permits selection only when normalized scenario, SLO and run hashes match and only SUT differs. All other differences are refused and enumerated. Service-discipline differences are allowed only as explicit whole-SUT comparisons and cannot support component attribution. V02-AC4 covers acceptance and refusal paths. |
| B5 | **Accepted** | §15.2 requires an isolated positive control for TTFT, ITL, TPOT, end-to-end latency, success rate, quality rate and every global gate. It also requires one isolated control for every §8.4 invalidation condition. Endpoint errors remain failures rather than invalidations. |
| B6 | **Accepted** | §7.1 separates `t_first_chunk` from `t_first_token`. Empty, role-only, whitespace-only and keep-alive chunks cannot satisfy TTFT. V01-AC2 requires a conformance stream with an immediate empty delta and delayed substantive content. |

## Should-fix findings

| ID | Disposition | Revised contract |
|---|---|---|
| S1 | **Accepted** | The CLI is provisionally `oicap`, derived from Open Inference Capacity and Acceptance Platform. M0 must freeze the name before the first evidence bundle. The research repository may retain its existing name. |
| S2 | **Accepted with whole-SUT distinction** | §6.3 makes service discipline structured and normative. §9.2 and §14 block silent comparison and component attribution. Different disciplines may still be compared as complete appliances, because procurement legitimately compares whole products, but the difference must be prominent. |
| S3 | **Accepted** | §10.3 makes post-hoc validation the default over buffered measured responses. Inline validation requires declaration, overhead measurement and identical use across compared configurations. |
| S4 | **Accepted** | §7.6 requires per-repeat gate and overall outcomes, and V02-AC3 requires them in machine-readable and HTML output. Default compliance requires every valid repeat to pass unless another rule was pre-registered. |
| S5 | **Accepted** | §16.1 states one part-time implementer plus asynchronous auditor, no dedicated GPU cluster, milestone effort envelopes and external dependencies. Only M0 and M1 are authorized now. |

## Additional audit-answer dispositions

- Conditional envelope outputs in §9.3 now carry the same
  `measured`/`interpolated`/`extrapolated` status as other outputs.
- §13.2 requires a redacted or aggregate bundle to remain recomputable for every
  included summary; otherwise it is labelled a presentation-only export.
- §14 identifies the buyer-controlled held-out pack as the load-bearing defense
  against benchmark-pack overfitting.
- v0.1 explicitly emits no `PASS`, `FAIL`, capacity boundary, comparison or
  procurement report. These terms become normative only in v0.2.

## Recheck request

The auditor should now verify:

1. that no section accidentally reintroduces v0.2 scope into v0.1;
2. that the calibrated-noise rule is operational rather than descriptive;
3. that the compliance-vector definition handles all arrangements of pass,
   fail and insufficient-evidence points;
4. that whole-SUT comparison does not reopen silent mechanism attribution;
5. that every v0.2 gate and every invalidation path has a required isolated
   control;
6. that the provisional CLI name is acceptable before M0 freezes it.
