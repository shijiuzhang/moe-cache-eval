# OICAP Product Charter

**Status:** Draft for independent audit

**Date:** 2026-08-30

**Applies to:** OICAP v0.2 and later

**Does not modify:** the released OICAP v0.1 specification, code, evidence, or tag

## 1. North star

The Open Inference Capacity and Acceptance Platform (OICAP) exists so that an
enterprise buyer can turn a procurement SLA into a frozen, executable acceptance
contract and determine whether a privately deployed large-model serving system
delivered on site satisfies that contract.

The canonical product flow is:

```text
buyer defines procurement SLA before tender
  -> OICAP validates and freezes the acceptance contract
  -> OICAP compiles a test-pack recipe and a sealed test instance
  -> buyer runs the official runner against the delivered system on site
  -> buyer uploads a data-minimized evidence bundle
  -> OICAP re-verifies and re-adjudicates the evidence server-side
  -> OICAP reports technical verdicts and gate-level reasons
  -> the procurement contract, not OICAP, determines the commercial remedy
```

OICAP is an open and vendor-neutral procurement acceptance system. It is not a
universal benchmark score or a model leaderboard.

## 2. Problem being solved

Enterprise buyers commonly specify concurrency, latency, throughput, reliability,
model and quantization requirements while suppliers quote hardware specifications
or favorable single-user demonstrations. Organizing hundreds of human users for an
acceptance test is impractical, and an improvised load test is easy to dispute.

OICAP replaces improvised demonstrations with a pre-registered load contract,
buyer-operated synthetic users, calibrated measurement, reproducible evidence and
a canonical technical adjudicator.

The product succeeds when a buyer can answer, for the exact delivered system and
the exact frozen contract:

- Was the required load actually applied?
- Did the service meet every required SLA gate at every measured point?
- Was the deployed model, quantization, engine and hardware configuration consistent
  with the procurement contract?
- Is the evidence sufficient for a technical conclusion?
- If not, is the cause a service failure, a deployment mismatch, an invalid test
  apparatus, missing evidence, or an unresolved measurement?

## 3. Roles and authority

### 3.1 Buyer contract owner

Defines and freezes the procurement SLA, workload profile, required deployment,
acceptance policy and authorized test plan before formal execution. Commercial
remedies remain under the buyer's procurement contract.

### 3.2 Buyer test operator

Controls the official runner, the pack-pinned calibration-responder and quality-
validator artifacts and processes, credentials and evidence upload at the delivery
site. The operator deploys and starts the responder at the frozen measurement
boundary and executes validators only from artifacts named by the official pack. The
operator is assumed to want a correct result, not to falsify a passing result for an
under-performing supplier. OICAP still detects operator mistakes and apparatus
failure because intent does not guarantee correct execution.

### 3.3 Supplier

Delivers and configures the system under test (SUT), discloses the required
configuration evidence, and may observe execution where the contract permits. The
supplier does not control the official runner, calibration-responder artifact or
process, quality-validator artifact or process, sealed test instance, uploaded
evidence or canonical adjudicator. It may provide the agreed boundary execution
location and networking needed by the buyer-controlled responder.

### 3.4 OICAP service

Versions and serves the contract schemas, pack compiler, calibration responder and
standard quality validators, issues the sealed test instance, accepts a data-
minimized evidence bundle, recomputes the technical result, and preserves
adjudication and supersession history. Its adjudication logic is open source; the
hosted service identifies the exact canonical version used.

### 3.5 Independent auditor or test laboratory

May reproduce calculations, review methodology or operate the test under a separate
agreement. An auditor is not required for the baseline buyer-operated flow.

## 4. Trust model

The primary threat is not a buyer fabricating a favorable upload. The primary risks
are:

- the supplier optimizes specifically for a known fixed test instance;
- the delivered service uses a different model, quantization or configuration;
- the measured endpoint proxies work to an undeclared external service rather than
  the contracted private deployment;
- the buyer's load generator cannot realize the declared load;
- an unregistered or supplier-controlled calibration responder biases the apparatus
  resolution used by the verdict;
- a wrong, locally patched or self-identified quality validator produces outcomes
  that the server cannot independently recompute from private content;
- the operator selects the wrong endpoint, credentials, model alias or run plan;
- the public and private parts of a pack drift;
- the uploaded evidence is incomplete, from an unsupported runner, or bound to the
  wrong contract;
- either party later disputes what was run, changed or superseded.

The baseline mitigations are buyer-controlled execution, explicit configuration
capture, a public recipe plus sealed held-out instance, official runner and
calibration-responder identity, pack-pinned quality-validator identity, apparatus
self-checks, immutable contract and pack hashes, server-side recomputation, and
append-only supersession records.

Unsigned evidence can support internal use, but a hosted formal result must identify
the issuing OICAP service, canonical adjudicator version, contract, pack instance,
runner version and upload time. Hardware-backed remote attestation is not assumed.

## 5. Two independent technical verdicts

OICAP MUST never merge service performance and deployment identity into an opaque
green result.

### 5.1 `service_sla_verdict`

Answers whether the measured endpoint satisfied every frozen performance,
reliability and quality gate at the measured loads. Its values are:

- `PASS`
- `FAIL`
- `INSUFFICIENT_EVIDENCE`

### 5.2 `deployment_conformance_verdict`

Answers whether the deployed model, quantization, engine, configuration and hardware
meet the frozen SUT requirements. Its values are:

- `PASS`
- `FAIL`
- `INSUFFICIENT_EVIDENCE`

Deployment evidence is layered:

- **L0 — self-declared:** API model name and supplier-provided metadata. Recorded,
  but not proof.
- **L1 — black-box consistency:** challenge responses or output fingerprints. Useful
  for anomaly detection, but never sufficient by themselves for `PASS`.
- **L2 — buyer-observed runtime binding:** hashes and configuration are tied to the
  running process by an on-site restart/load observation, process command line and
  open-file inspection where available, plus a physical memory-consistency check.
- **L3 — hardware-backed attestation:** optional future evidence from a trusted
  execution or hardware root of trust.

The L2 memory check MUST use a conservative envelope covering the declared model,
quantization, sharding, offload, KV-cache reservation and engine overhead. A single
GPU's memory use is not proof when tensor parallelism or CPU offload is declared.
An observation below the conservative minimum for the complete declared topology is
a contradiction; agreement is supporting evidence, not identity proof by itself.
The check is available only when every catalogue input needed for that envelope is
bounded by `required` or `allowed_set`. A buyer who deliberately marks such an input
`not_required` or `informational` has not passed the check; the evidence matrix MUST
show `UNAVAILABLE_BY_CONTRACT` and explain the lost identity assurance.

### 5.3 Overall technical result

The default overall result is:

- `PASS` only when both required verdicts are `PASS`;
- `FAIL` when either verdict is `FAIL`;
- `INSUFFICIENT_EVIDENCE` otherwise.

Every key in the versioned deployment-requirement catalogue MUST appear in the
contract with exactly one state: `required`, `allowed_set`, `not_required`, or
`informational`. A catalogue key cannot be omitted. Silence is therefore a contract
error, not conformance.

## 6. Technical verdict versus commercial disposition

OICAP reports technical facts. It MUST NOT decide whether the buyer rejects delivery,
deducts payment, grants a cure period or accepts a waiver.

The frozen acceptance policy may record the agreed technical procedure:

- maximum attempts and retests;
- which configuration paths may change before a retest;
- whether a change creates a new SUT identity or a new acceptance project;
- required reset and observation rules;
- who operates and who may observe;
- how new evidence supersedes, but never deletes, old evidence;
- how an appeal requests technical review.

Commercial outcomes such as `ACCEPT`, `CONDITIONAL_ACCEPT`, `CURE_AND_RETEST`,
`DEDUCT`, or `REJECT_DELIVERY` are procurement dispositions. They may be recorded
for audit history, but OICAP does not derive them from a technical percentage.

Partial gate success is displayed, not converted into a fourth technical verdict.
If one required gate fails, the technical SLA verdict is `FAIL`; a separately
pre-agreed commercial policy may still permit conditional acceptance.

## 7. Product invariants

1. **Contract before execution.** SLA, workload semantics, SUT requirements, gates,
   repeats, stopping rules, SLA-derived time budget and per-point hard caps, and
   retest policy are frozen before a formal run.
2. **Buyer controls the run.** Supplier-operated evidence alone cannot produce the
   baseline formal buyer-acceptance result.
3. **Rules public, instance controlled.** The test method and workload distribution
   are reviewable; held-out concrete instances may remain sealed until on-site use.
4. **Measured points only.** Formal conclusions apply only to tested configurations
   and measured load points.
5. **No load without apparatus evidence.** A client that cannot sustain the
   SLA-derived concurrency-hold and event-rate profiles for the planned duration, or
   whose on-site same-path timing resolution exceeds the frozen reserve, yields
   an invalid apparatus record and no SUT capacity verdict, not a false capacity
   ceiling.
6. **No speed without quality.** Fast invalid output cannot pass.
7. **No service PASS as identity proof.** Performance and deployment conformance are
   independent.
8. **No private payload upload by default.** The hosted flow uses a redacted evidence
   profile; private-full evidence remains under buyer control.
9. **No erased history.** Corrections and retests create linked superseding records.
10. **No silent field or protocol downgrade.** Unsupported or missing requirements
    are rejected or reported as insufficient evidence.
11. **No unowned trusted component.** Every component whose identity or unverified
    output is relied upon to authorize measurement or support a formal gate has an
    explicit owner, versioned artifact, pack-manifest identity and runtime validation
    before use. A component treated only as an untrusted stimulus may remain unpinned
    only when the runner independently measures every accepted property and its
    identity or self-report receives no formal credit.

## 8. Non-goals

The core OICAP product does not:

- publish a universal model, appliance or accelerator score;
- operate a public performance leaderboard;
- recommend cost or choose a commercial supplier;
- predict an unmeasured GPU count or untested hardware configuration;
- claim that a benchmark pack is identical to an enterprise's production workload;
- train, fine-tune or modify a model;
- optimize a serving engine;
- depend on any paper, MoE-specific research result or trace-driven simulator;
- require MoE telemetry or another engine-specific diagnostic for baseline
  acceptance;
- prescribe contractual payment, rejection or legal remedies;
- claim cryptographic proof of model identity without an appropriate attestation
  mechanism.

Research modes, MoE diagnostics, public comparison and cost planning may exist as
separate optional projects or plugins. They MUST NOT determine the core acceptance
roadmap or weaken its evidence requirements.

## 9. Release direction

- **v0.1:** released reproducible measurement kernel; one load point, no SLA verdict.
- **v0.2:** end-to-end acceptance alpha: typed SLA, pack compilation, client preflight,
  sweep, quality gates, dual verdicts, redacted upload, server-side adjudication and
  minimal project UI. Results remain pilot/non-contractual until the GPU qualification
  gate passes.
- **v0.3:** GPU-qualified enterprise pilot with at least one real procurement rehearsal
  and formal hosted technical reports enabled for supported configurations.
- **v1.0:** hardened public industrial acceptance service with multiple workload-pack
  families, multiple validated serving stacks, organizational controls, durable audit
  history and documented dispute operations.

The public website is a core delivery surface beginning in v0.2. It is not an optional
late-stage registry feature.
