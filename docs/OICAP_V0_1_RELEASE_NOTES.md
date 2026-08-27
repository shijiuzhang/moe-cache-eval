# OICAP v0.1 — reproducible measurement kernel

**Release date:** 2026-08-27  
**Package version:** `0.1.0`  
**Git tag:** `v0.1`

OICAP v0.1 is the smallest independently audited kernel that can record one
black-box inference load point and emit a recomputable private evidence bundle.
It is a measurement foundation, not a capacity recommendation product.

## What this release asserts

- Four versioned contract documents are normalized, hashed and enforced against
  bundled Draft 2020-12 JSON Schemas. Fixed M1 structures reject unknown fields;
  declared SLO and SUT-description extension points remain open.
- The OpenAI-compatible streaming adapter distinguishes first byte, first protocol
  chunk and first substantive response content.
- Closed-loop fixed-user and open-loop constant-arrival execution record realized
  load. Closed-loop concurrency is checked with and without declared think time.
- Repeated self-calibration measures the runner noise floor and can invalidate a
  load point when the client does not realize the registered load contract.
- Successful-request latency distributions are separated from failure duration;
  timeouts remain visible as right-censored failures.
- Evidence verification recomputes hashes, identities, schemas, metric summaries,
  apparatus validity and an independently supplied calibration-manifest reference.
- V01-AC1 through V01-AC6 have demonstrated evidence. Hosted Linux x86-64 and
  macOS ARM64 jobs run the full regression suite and verify evidence in both
  cross-platform directions.

## What this release does not assert

- **No tamper or producer attestation.** The manifest is unsigned. `verify`
  establishes internal consistency, not who produced the evidence, an external
  timestamp, or resistance to a producer regenerating altered evidence. Producer
  identity, detached signatures and external timestamp anchors are reported as
  unsupported.
- **No real-engine validation claim.** The release acceptance evidence uses the
  deterministic test protocol. The measurement kernel has not yet been validated
  against a real inference engine under a representative real workload; that is
  the first M2 objective.
- **No SLO or procurement verdict.** v0.1 emits no `PASS`, `FAIL`, maximum compliant
  load, sweep, comparison, recommendation, goodput score or HTML report. Those are
  v0.2 scope and must not be inferred from a v0.1 evidence bundle.
- **No invented token timing.** Real endpoints expose token-level ITL only when an
  authoritative per-token timestamp source exists. Otherwise the distinct
  `inter_chunk_latency` metric is reported and ITL is explicitly unavailable.

## Acceptance evidence

- Independent implementation audit and close-out:
  [`OICAP_M1_IMPLEMENTATION_AUDIT.md`](OICAP_M1_IMPLEMENTATION_AUDIT.md).
- Finding-by-finding remediation:
  [`OICAP_M1_AUDIT_REMEDIATION.md`](OICAP_M1_AUDIT_REMEDIATION.md).
- Implemented boundary and acceptance mapping:
  [`OICAP_M1_IMPLEMENTATION.md`](OICAP_M1_IMPLEMENTATION.md).
- Release-candidate local evidence: 46 OICAP tests and 88 full-repository tests passed;
  the built wheel contained all four valid, strict-root contract schemas.
- Pre-release hosted evidence: GitHub Actions run
  [`33046848920`](https://github.com/shijiuzhang/moe-cache-eval/actions/runs/33046848920)
  passed all six jobs at commit `f9a6745`, including bidirectional evidence exchange.

## Next boundary

M2 begins with validation against a real OpenAI-compatible inference engine under a
representative workload. Signing, timestamp anchoring, SLO adjudication, sweeps,
comparison and reporting remain separate later milestones; none is silently folded
into the v0.1 claim.
