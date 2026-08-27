# OICAP M1 implementation-audit remediation

**Date:** 2026-08-25  
**Audit:** `OICAP_M1_IMPLEMENTATION_AUDIT.md`  
**Status:** implemented locally; hosted Linux/macOS CI evidence still pending

This note records how the four blocking and seven non-blocking findings were
addressed. It does not upgrade the checkpoint to a v0.1 release.

## Blocking findings

| Finding | Disposition | Implementation and positive control |
|---|---|---|
| B1 closed-loop concurrency decay | **Fixed** | Static per-worker slices were replaced with a shared `asyncio.Queue`. `summary.json` now records peak concurrency, full-span time-weighted mean concurrency, and a pre-drain mean from first through final submission. Apparatus validity uses the registered tolerance against the pre-drain value. A heterogeneous slow/fast fixture asserts the maintained floor. |
| B2 unsigned manifest overclaim | **Corrected, cryptographic attestation deferred** | CLI, README, verification output and the implementation report now say “unsigned internal consistency.” The result explicitly reports producer identity, detached signature and external timestamp as unverified. Detached signatures and timestamp anchoring remain post-M1 work. |
| B3 failed requests lower latency | **Fixed** | TTFT, first-chunk-to-token, end-to-end, ITL and TPOT use successful requests only and name their populations. Failure duration is a separate `time_to_failure` distribution. A three-success/one-fast-empty-response control verifies the successful latency mean is unchanged. |
| B4 real-endpoint ITL absent | **Made explicit** | Token ITL is available only under authoritative per-token timestamps (currently the deterministic synthetic protocol). Real endpoint summaries mark ITL unavailable with a reason and report `inter_chunk_latency` from content-event timestamps. A server-usage fixture verifies inter-chunk samples exist while ITL remains unavailable. |

## Non-blocking findings

| Finding | Disposition |
|---|---|
| N1 schemas unenforced | Contract loading now validates all four documents against the published Draft 2020-12 schemas before semantic checks. Bundle verification validates normalized contracts against the bundled schema copies. A contract missing model, engine and hardware is rejected. |
| N2 censoring has no production path | Adapter timeouts now set both `timed_out` and `censored`; a live timeout fixture checks the production path. Complete-all drain semantics and the absence of run-end censoring are documented. |
| N3 run load unobserved | Measurement-window process CPU, system CPU and an independent 1 ms periodic asyncio wake-up-lag probe are written to `runner_load.json`; apparatus validity compares them with calibrated limits. Request schedule lag remains a separate metric. |
| N4 calibration source hash unchecked | `oicap verify --calibration-source PATH` checks the external calibration manifest against the recorded digest. Omitting the source leaves verification successful but emits an explicit warning; mismatch is an error. |
| N5 dirty paths leaked | Evidence now stores only dirty-entry count and an aggregate SHA-256 over sorted status entries, not path names. |
| N6 schemas omitted from documentation | The bundle listing now includes `schemas/*.schema.json` and `runner_load.json`. |
| N7 asymmetric/incomplete CI | The workflow now runs the full repository test suite on both Linux and macOS and exchanges evidence in both macOS→Linux and Linux→macOS directions, including external calibration-manifest checks. AC6 remains pending until hosted runs are observed. |

## Verification boundary

The following are different claims and remain separate in machine-readable output:

- `internal_consistency`: hashes, identities, schemas, summaries and apparatus
  assessment recompute from the bundle;
- `calibration_source_manifest_verified`: an independently supplied calibration
  bundle matches the recorded source digest;
- producer identity, detached signature and external timestamp: **not verified**.

The first two can be demonstrated at M1. The third requires an external trust
mechanism and must not be inferred from a green `verify` result.

## Local evidence at this checkpoint

- targeted OICAP suite: 42 tests, all passing;
- full repository suite: 84 tests, all passing on the local macOS development host;
- deterministic quick-start: calibration, measurement and verification with an
  independently supplied calibration source complete with `ok: true`, apparatus
  `VALID`, and all five machine-readable verification-scope fields present;
- hosted cross-platform workflow: not yet observed.

## Re-audit follow-up

The 2026-08-26 re-audit accepted B1–B4 and N1–N7, then raised two minor findings:

- **F1, think-time concurrency:** the former `not_applicable` branch was removed.
  Think-time sessions now derive expected mean concurrency using the interactive
  response-time law `N × S / (S + Z)` from declared users and think time plus measured
  service time. Calibration and run apparatus use the same helper and retain the
  registered realization-ratio floor. Healthy and deficient positive controls cover
  the branch.
- **F2, calibration CLI ambiguity:** `oicap calibrate` now emits separate
  `command_completed` and `calibration_valid` fields. `ok` equals calibration validity,
  and an invalid calibration exits 2 while preserving the diagnostic bundle.
