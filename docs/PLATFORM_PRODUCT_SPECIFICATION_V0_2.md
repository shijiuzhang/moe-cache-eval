# Open Inference Capacity and Acceptance Platform

## Product specification v0.2

**Status:** Draft for independent audit; not an implementation claim

**Date:** 2026-08-30

**Applies to:** OICAP v0.2 development and the hosted acceptance alpha

**Authority:** [OICAP Product Charter](OICAP_PRODUCT_CHARTER.md)

**Does not modify:** the released v0.1 specification, code, evidence, release notes, or tag

This document specifies the first end-to-end version of OICAP as an enterprise
procurement-acceptance product. The words **MUST**, **MUST NOT**, **SHOULD**,
**SHOULD NOT**, and **MAY** are normative.

OICAP v0.2 turns a buyer's pre-tender service-level agreement into a frozen,
executable test pack; lets the buyer exercise a privately deployed inference
service on site; accepts a data-minimized evidence upload; and recomputes two
independent technical verdicts on the OICAP service:

- whether the service met the frozen SLA; and
- whether the deployed system conformed to the frozen deployment requirements.

It does not decide the commercial remedy. It does not produce a universal score,
leaderboard, cost recommendation, or prediction for unmeasured hardware.

---

## 1. Product boundary and release claim

### 1.1 v0.1 is an immutable dependency

OICAP v0.1 is the released measurement kernel. v0.2 MUST consume its evidence
semantics through an explicit compatibility layer. This document does not amend
what v0.1 claimed, measured, or excluded.

If v0.2 requires an incompatible measurement change, the change MUST use a new
schema or protocol version. It MUST NOT reinterpret an existing v0.1 bundle as if
the new information had always been present.

### 1.2 v0.2 software claim

v0.2 is an acceptance **alpha** that implements the complete software workflow:

```text
SLA authoring -> contract freeze -> pack compilation -> client preflight
-> on-site execution -> redacted upload -> server verification
-> service SLA verdict + deployment conformance verdict -> report
```

The software MAY be released and used for internal pilots after the CPU protocol
compatibility gate passes. Every v0.2 hosted result MUST carry:

```yaml
assurance_level: pilot
formal_procurement_verdict_enabled: false
```

The user interface, API, exported JSON and rendered report MUST display this
limitation. A hidden disclaimer in documentation is insufficient. Passing the GPU
capacity-qualification gate is an entry condition for v0.3 formal-verdict enablement;
it does not retroactively upgrade a v0.2 record.

### 1.3 Two qualification gates

| Gate | Required evidence | What it releases |
|---|---|---|
| Protocol compatibility | At least one real CPU-hosted OpenAI-compatible inference endpoint, initially llama.cpp, exercising genuine streaming, usage, error, timeout, empty-response and variance paths | All v0.2 software development and pilot reports |
| Capacity-measurement qualification | At least one supported real GPU serving stack under realistic concurrency and memory pressure, with independent expected-result checks | Formal external technical verdicts for the explicitly qualified stack and envelope |

The GPU gate MUST NOT block implementation of the compiler, sweep engine, quality
gates, evidence profile, adjudicator, reports, or website. Conversely, completing
those features MUST NOT be represented as GPU capacity validation.

---

## 2. Canonical acceptance project

An acceptance project is a versioned, append-only record with a stable
`project_id`. Its states are:

```text
DRAFT
  -> VALIDATED
  -> FROZEN
  -> PACK_ISSUED
  -> PREFLIGHT_PASSED
  -> RUNNING
  -> EVIDENCE_UPLOADED
  -> VERIFIED
  -> ADJUDICATED
  -> CLOSED
```

Exceptional states and transitions are:

- `INVALID_CONTRACT`: authoring inputs are ambiguous or inconsistent;
- `PREFLIGHT_FAILED`: the proposed client cannot execute the plan honestly;
- `RUN_INVALID`: the apparatus, protocol, pack binding, or evidence is invalid;
- `RETEST_AUTHORIZED`: a frozen acceptance policy permits another attempt;
- `UNDER_TECHNICAL_REVIEW`: a party has raised a reproducibility or interpretation
  issue;
- `SUPERSEDED`: a newer adjudication replaces this record without deleting it.

Only the OICAP service MAY issue the canonical `ADJUDICATED` record. A local CLI
preview MUST be labelled `local_preview` and MUST NOT be visually confusable with a
hosted result.

`INSUFFICIENT_EVIDENCE` is a gate or verdict value, never a project lifecycle state.
A completed project whose service or conformance verdict is insufficient remains in
`ADJUDICATED`; the verdict object and reason codes carry the insufficiency.

Every transition MUST record actor, timestamp, software version, input hashes and
reason. Failed and superseded attempts remain addressable.

---

## 3. Contract set and hash binding

A frozen project comprises the following separately versioned documents:

```text
project/
  project.yaml              parties, roles, endpoint boundary and project metadata
  sla.yaml                  service performance, reliability and quality requirements
  workload-profile.yaml     workload classes and target distributions
  sut-requirements.yaml     required model, quantization, engine and hardware
  acceptance-policy.yaml    attempts, retests, mutable fields and observation rules
  run-plan.yaml             load points, repeats, phases, seeds and time budget
  pack-recipe.yaml          public method and generator versions
  manifests/
    frozen-contract.json    canonical hashes of every document above
```

Each document MUST validate against a packaged JSON Schema. Top-level unknown keys
MUST be rejected. Declared extension maps MAY remain open, but their contents MUST
not affect a verdict unless a versioned plugin claims them.

The canonical hash is computed from normalized machine-readable content, not from
presentation formatting. Editing any verdict-relevant field creates a new contract
hash and, after `FROZEN`, a new project revision.

### 3.1 No implicit defaults for procurement facts

OICAP MUST reject rather than guess when any of the following is ambiguous:

- target model revision or acceptable equivalence set;
- quantization method or precision;
- workload class and request-length distribution;
- concurrency semantics or arrival process;
- the meaning and population of a throughput target;
- latency percentile and population;
- output-length policy;
- quality rule;
- minimum sample size or duration;
- allowed deployment changes between attempts.

Defaults MAY exist for presentation or safe local execution. They MUST NOT silently
become procurement requirements.

---

## 4. SLA authoring contract

### 4.1 Required dimensions

`sla.yaml` MUST express gates by workload class before any aggregate rule. A class
MUST identify:

- request share or arrival rate;
- input-token and requested-output-token distributions;
- single-turn or multi-turn session semantics and think time;
- streaming or non-streaming response contract;
- success and allowed error rules;
- quality validator and threshold;
- TTFT, decode cadence or end-to-end requirements where applicable;
- minimum duration and successful-sample count.

An aggregate gate MUST declare its weighting population. A fast class MUST NOT hide
failure in a slower required class.

### 4.2 Throughput terminology

The bare key or label `tps` MUST be rejected in a frozen SLA. It is ambiguous.
Supported throughput terms MUST name both numerator and population, for example:

- `aggregate_output_tokens_per_second` — successful, quality-eligible output tokens
  divided by the declared measured interval;
- `per_request_decode_tokens_per_second` — a per-request distribution derived only
  when authoritative token timing exists;
- `qualified_requests_per_second` — completed requests that satisfy all per-request
  eligibility gates;
- `class_aware_goodput_requests_per_second` — qualified throughput reported per
  workload class and under the frozen class mix.

The report MUST repeat the full metric name and statistical population. UI shorthand
may display `TPS` only beside a visible definition.

### 4.3 Latency and missing metrics

TTFT is the time from client submission to the first streamed block that contributes
a non-whitespace character to the final response. Empty deltas, role-only events and
keepalives do not end TTFT.

Inter-token latency is available only when authoritative per-token timestamps exist.
Inter-chunk latency MUST be named separately and MUST NOT satisfy an inter-token gate.

A required metric that is unavailable yields `INSUFFICIENT_EVIDENCE`, not `PASS` or
an inferred substitute.

### 4.4 Gate result

Every gate returns one of:

- `PASS`;
- `FAIL`;
- `INSUFFICIENT_EVIDENCE`.

The record contains threshold, operator, measured value, population, sample count,
uncertainty or noise status, and a stable reason code. Values close enough to the
instrument resolution, together with any applicable frozen run-variation allowance,
that the threshold cannot be distinguished MUST return `INSUFFICIENT_EVIDENCE`.
Instrument overhead is not subtracted to manufacture precision. This threshold-
indistinguishability rule also governs an observation that reaches a wall-clock cap;
the cap alone cannot override it with `FAIL`.

---

## 5. Workload profile and SLA-to-pack compiler

### 5.1 Supported workload sources

A workload class uses exactly one source policy:

1. `oicap_standard` — an openly specified OICAP pack family;
2. `buyer_local` — buyer-controlled payloads that remain local;
3. `distribution_matched_synthetic` — generated inputs matching declared structural
   distributions but not claimed to reproduce buyer semantics.

OICAP MUST NOT label a synthetic pack as representative of a production workload
unless an independently versioned matching assessment supports that statement.

### 5.2 Compiler output

For a valid frozen project the compiler produces:

```text
test-pack/
  PACK_README.md
  public-recipe.yaml
  sealed-instance.enc or local-instance.manifest
  normalized-contracts/
  runner-lock.json
  calibration-responder/
    responder-lock.json
    <platform binary or immutable OCI artifact reference>
  client-requirements.yaml
  preflight-endpoint-profile.yaml
  preflight-plan.yaml
  onsite-calibration-plan.yaml
  execution-plan.yaml
  wall-clock-budget.yaml
  quality-hooks/
    quality-hooks-lock.json
    <validator artifacts or immutable OCI artifact references>
  pack-manifest.json
```

`runner-lock.json` MUST pin both the official runner and every permitted calibration-
responder platform artifact, and MUST reference the digest of
`quality-hooks-lock.json`. The responder directory MUST contain the platform binary
or an immutable OCI artifact reference, its digest, supported platform, protocol
version and build identity.
`onsite-calibration-plan.yaml` binds the responder, boundary placement, method,
expected handshake and one-time challenge semantics to the project and pack.
`quality-hooks-lock.json` MUST pin each validator's identifier, version, artifact or
immutable OCI digest, runtime/dependency lock, configuration digest, governed gate
identifiers and private-reference manifest hash. `pack-manifest.json` MUST cover
every local responder and validator artifact and the immutable descriptor of every
referenced OCI artifact.

The public recipe states how the pack is generated, its distributions, validator
semantics and limitations. The sealed instance binds concrete prompts, order,
nonces, seeds, issue time, expiry and manifest hash. The buyer receives or unlocks
the concrete instance according to the frozen observation policy. The calibration
responder is an official pack component, not an implementation supplied ad hoc at
the delivery site. The same rule applies to every quality validator: local edits
after pack issue create an identity mismatch, not an authorized correction.

A sealed instance is an anti-adaptation control, not a secret scientific method.
The supplier may review the recipe and acceptance criteria before tender while the
concrete held-out payload remains controlled until execution.

### 5.3 Determinism and variants

Given the same compiler version, normalized contract, authorized private payload
manifest and seed, the compiler MUST reproduce the same pack manifest. Different
formal attempts SHOULD receive different authorized instances drawn from the same
frozen recipe.

The compiler MUST emit explicit refusal reasons when no available pack can implement
the requested workload or quality rule. It MUST NOT silently choose the nearest
standard scenario.

### 5.4 Data boundaries

Buyer-local prompts and responses remain on the buyer-controlled runner by default.
The pack manifest records content hashes and aggregate distributions without
embedding private content. A quality hook that requires a private reference answer
executes post-hoc on the buyer side and uploads only the minimum verdict evidence
defined by the project. That record MUST state `quality_evaluation_location`,
validator identifier/version, runner-verified validator artifact and runtime digests,
quality-hooks-lock hash, eligible population and response/reference hashes. The
server can recompute aggregation over the uploaded per-request outcomes and verify
that the recorded validator identity is the one authorized by the pack, but MUST NOT
claim to have re-evaluated private content it did not receive.

---

## 6. Deployment requirements and conformance

### 6.1 `sut-requirements.yaml`

The document names a versioned `deployment_catalogue_version`. For that catalogue,
every key below MUST appear exactly once and carry exactly one `requirement_state`:

- `model_identity` — family, exact revision and weight hashes;
- `tokenizer_and_chat_template` — identifiers and revisions;
- `quantization` — algorithm, bit width, group size and calibration identifier;
- `serving_engine` — product, version or commit;
- `container_and_runtime` — image digest and runtime;
- `launch_configuration` — startup command and verdict-relevant environment;
- `endpoint_boundary` — endpoint path, model aliases and listener ownership;
- `external_dependencies` — permitted network egress and remote services;
- `accelerator_topology` — model, count, memory, links and power mode;
- `host_platform` — CPU, RAM, NUMA, operating system and storage;
- `parallelism` — tensor, pipeline, data or expert parallelism;
- `memory_and_offload` — weight placement, KV-cache format/capacity and offload;
- `decoding_acceleration` — speculative or other decoding mechanisms;
- `batching_scheduling_admission` — sequence limits, batch limits, queueing, cache,
  deduplication and admission controls.

The four states mean:

- `required`: one exact constraint object MUST be supplied and satisfied;
- `allowed_set`: a non-empty set or bounded predicate MUST be supplied, and the
  observation must fall inside it;
- `not_required`: the field is deliberately excluded from conformance and MUST NOT
  carry a hidden constraint;
- `informational`: the field must be observed when available but cannot change the
  conformance verdict.

The schema MUST reject an absent catalogue key, an unknown key outside a declared
extension map, multiple states, or a state without its required value shape. In
particular, omitting `quantization` is invalid; it is not equivalent to declaring
`quantization.requirement_state: not_required`.

New catalogue keys require a new catalogue version and an explicit migration. A
contract written against an older catalogue is never silently upgraded at freeze
time.

### 6.2 Evidence levels

The adjudicator reports the highest completed evidence layer for each requirement:

- **L0 self-declared:** service metadata and supplier statements;
- **L1 black-box consistency:** anomaly-oriented challenges and fingerprints;
- **L2 buyer-observed runtime binding:** on-site evidence tying inspected artifacts
  to the process that serves the measured endpoint;
- **L3 hardware-backed attestation:** optional future trusted evidence.

L0 and L1 alone MUST NOT establish conformance for model identity.

### 6.3 Required L2 bridges

Where the operating system and deployment permit, L2 collection MUST include:

- buyer-observed controlled service restart;
- hashes of model, tokenizer, quantization and configuration artifacts used by the
  restart;
- container digest, process command line and relevant environment configuration;
- open file handles or equivalent runtime-to-artifact binding;
- listener ownership and active network connections sufficient to detect an
  undeclared proxy or remote inference dependency;
- hardware inventory and topology;
- before-load, after-load and steady-state accelerator and host memory observations;
- a conservative physical memory envelope computed from declared weights,
  quantization, sharding, CPU/GPU offload, KV reservation and engine overhead.

The physical-memory check has explicit contract prerequisites. At minimum,
`model_identity`, `quantization`, `serving_engine`, `accelerator_topology`,
`parallelism`, and `memory_and_offload` MUST each be `required` or `allowed_set`, and
their constraints MUST be bounded tightly enough to compute a conservative minimum
over every permitted configuration. `allowed_set` is usable only when that minimum
can be computed across the whole set.

If any prerequisite is `not_required`, `informational`, or insufficiently bounded,
the authoring UI MUST warn before freeze and name the lost check. The conformance
matrix MUST emit:

```yaml
physical_memory_consistency:
  status: UNAVAILABLE_BY_CONTRACT
  missing_prerequisites: [parallelism]
  effect: does_not_support_runtime_model_identity
```

This is neither `PASS` nor a missing-field error. If the frozen acceptance policy
requires the physical-memory check or requires an L2 identity level that depends on
it, such a contract MUST NOT freeze until the prerequisites are bounded. Otherwise
the buyer may acknowledge the reduced assurance and freeze it, but every report MUST
retain the warning.

The physical check applies to the complete declared topology. A measurement below
the conservative minimum is contradictory. Agreement supports the claim but does
not alone prove identity. If process inspection is technically unavailable, the
record uses `UNAVAILABLE_BY_ENVIRONMENT`, states why, and the affected conformance
gate may become `INSUFFICIENT_EVIDENCE`. Contract-caused and environment-caused
unavailability MUST NOT be merged.

### 6.4 Service and conformance verdicts

The adjudicator emits independent `service_sla_verdict` and
`deployment_conformance_verdict` objects. A smaller substituted model that meets
latency and throughput can therefore receive:

```yaml
service_sla_verdict: PASS
deployment_conformance_verdict: FAIL
overall_technical_result: FAIL
```

No UI view may collapse these into an unexplained green badge.

---

## 7. Client capability and pre-departure preflight

### 7.1 Pack-declared client requirements

Every pack MUST declare, for the planned maximum load:

- supported runner and operating-system versions;
- minimum CPU cores, memory and file-descriptor budget;
- minimum measured network bandwidth and maximum acceptable client-side network
  latency or loss where relevant;
- whether one client is sufficient or a coordinated multi-client run is required;
- clock requirements when multiple clients are used;
- credential and endpoint-connectivity prerequisites;
- local temporary-storage requirement;
- expected evidence size.

These values are supported operating envelopes, not generic hardware estimates.

### 7.2 Pre-departure self-check

Before a formal on-site appointment, the buyer MUST run the exact locked runner and
planned client topology against a deterministic OICAP test endpoint or replay
fixture using the compiler-issued `preflight-endpoint-profile.yaml`.

The profile MUST be derived from the frozen SLA, workload profile and run plan. It
MUST declare, by workload class:

- TTFT pacing;
- content-event cadence and response-event count or output-length distribution;
- response-size distribution and streaming semantics;
- class mix and arrival/session semantics;
- maximum simultaneous in-flight requests;
- required aggregate client event rate;
- minimum sustained duration;
- permissible pacing tolerance and the profile hash.

One profile need not maximize connection hold time and event-processing rate at the
same instant. The compiler MAY issue separate `concurrency_hold` and `event_rate`
profiles, but together they MUST cover both extremes implied by the frozen SLA. The
minimum sustained duration MUST be at least the longest uninterrupted measured phase
in the formal run plan, and the preflight's cumulative requests, chunks and bytes
MUST meet or exceed the largest planned repeat at SLA-boundary behavior.

The reference endpoint MUST emit the configured profile hash and pacing parameters.
The runner MUST independently measure the realized pace and reject a hash mismatch,
unpaced, zero-delay, short-duration or out-of-tolerance reference run. Merely
reaching the requested peak in-flight count is not a passing preflight.

The preflight MUST verify at least:

- runner self-calibration and noise resolution;
- sustained closed-loop concurrency or open-loop schedule accuracy;
- CPU, memory, descriptor and network headroom;
- local evidence write rate and free storage;
- time synchronization for distributed clients;
- pack integrity, schema compatibility, and quality-hook artifact identity and
  availability.

The result is a signed or hash-bound `client-preflight.json` containing the client
fingerprint, profile hash, realized pacing, sustained duration, cumulative event
volume and validity interval. The formal runner compares the on-site client
fingerprint. A different or expired client requires a new preflight or an explicitly
recorded on-site preflight.

A preflight against a local deterministic endpoint does not validate the delivery
site's network or establish the timing resolution used for formal adjudication. It
is an off-site suitability screen. The runner MUST perform the on-site checks in
§7.3 before the measured phase.

Reference-endpoint TTFT, latency and throughput are harness-health observations only.
They MUST NOT be interpreted as measurements or predictions of the delivered SUT.

The office reference endpoint is not a verdict-producing component and its binary is
not pack-locked in v0.2. The runner accepts only independently measured pacing,
duration, volume and profile-hash behavior; an endpoint identity claim carries no
credit. A wrong endpoint can therefore cause preflight refusal, but cannot obtain a
formal service or quality `PASS`. This limited availability risk is recorded rather
than promoted into the formal trusted-component set.

If the client cannot apply the declared load, OICAP MUST require a supported
multi-client topology or refuse the formal plan. The failure MUST be discovered
before travel when it is reproducible in preflight.

### 7.3 On-site same-path calibration

Immediately before a formal measured phase, after the endpoint, routing, VPN or jump
path, TLS termination, load balancer and ingress configuration are final, the runner
MUST re-establish per-metric timing resolution on the actual measurement path.

The calibration MUST use the formal client machine or distributed client topology
and the deterministic calibration responder pinned by the official test pack at the
frozen SUT boundary. The buyer test operator, not the supplier, deploys, starts and
controls that responder from the pack artifact. The supplier MAY provide the agreed
execution location and networking but MUST NOT substitute its own responder binary,
image, configuration or process.

Before accepting any calibration sample, the runner MUST verify:

- the complete pack manifest;
- responder artifact or immutable OCI digest and version against
  `runner-lock.json` and `responder-lock.json`;
- calibration protocol and build identity;
- project, pack and calibration-plan hashes;
- a fresh runner-issued one-time challenge nonce returned in the responder's signed
  or hash-bound protocol transcript.

The buyer-controlled launcher MUST compute the binary or resolved OCI manifest digest
before launch. A digest or build identity reported only by the responder is not
sufficient evidence of identity.

An unregistered responder, unsupported version, digest mismatch, stale/replayed
challenge, plan mismatch or absence of buyer-controlled launch evidence MUST emit
`CALIBRATION_RESPONDER_IDENTITY_INVALID`, make the apparatus invalid, move the
attempt to `RUN_INVALID`, and prevent calibration and formal measurement.

The responder path MUST traverse the same client interfaces and all buyer-side
routing components used by the formal requests. The responder and runner record a
path/profile hash and the realized timestamp, scheduling and transport variation for
each relevant metric. If equivalence to the formal path cannot be established, the
apparatus is invalid.

`project.yaml` MUST define the measurement boundary. Variability in buyer-controlled
components outside the SUT boundary contributes conservatively to the on-site
instrument resolution. Network, ingress or serving components inside the contracted
SUT boundary remain part of service performance: their latency is not subtracted or
forgiven as instrument noise.

The registered method MUST isolate the outside-boundary apparatus contribution. If
the calibration responder necessarily includes an in-boundary SUT component and the
method cannot separate its variation, that result is not admissible for enlarging
instrument resolution; the apparatus remains invalid until an equivalent boundary
calibration can be established. Uncertainty is not reassigned from the SUT to the
instrument merely because the path is difficult to decompose.

The result is `onsite-path-calibration.json`, containing at least:

- the office-preflight calibration and profile hash;
- the on-site per-metric resolution;
- the boundary decomposition and any excluded in-boundary variation;
- client, route, endpoint and boundary fingerprints;
- method, responder and runner versions and artifact digests;
- project/pack/plan hashes, challenge nonce and buyer-controlled launch record;
- timestamp and validity scope;
- comparison with the frozen instrument-resolution reserve.

If any on-site resolution required by a gate exceeds its frozen reserve, the runner
MUST emit `CLIENT_APPARATUS_INVALID`, move the attempt to `RUN_INVALID`, and MUST NOT
begin the formal measured phase.
Changing the client, route, VPN/jump path, TLS/load-balancer path, ingress or endpoint
after calibration invalidates it and requires a new on-site calibration.

Digest, version and challenge checks establish binding to the pack under the buyer-
controlled baseline process. They are not hardware-backed proof against a hostile
host that can subvert the running responder. If the buyer cannot retain operational
control at the boundary, the baseline formal method is unavailable unless an
independently qualified stronger attestation mode is used.

---

## 8. Wall-clock budget and execution plan

### 8.1 Required budget

Every compiled pack MUST contain a declared wall-clock budget with:

- setup and integrity-check allowance;
- warm-up time;
- per-load-point measured duration or completion target;
- independent repetitions;
- reset and cool-down time;
- cold-start runs, if required;
- post-hoc quality evaluation;
- evidence packaging and upload;
- retry reserve that does not silently become an additional formal attempt;
- `minimum`, `expected`, and `upper_bound` total duration.

The budget is anchored to the frozen SLA, not to an assumed performance of the
unknown SUT. The compiler MUST emit `budget-derivation.json` containing every input,
formula, rounding rule and source. At minimum it derives:

1. an SLA-boundary request time from the relevant TTFT, end-to-end, decode-rate,
   output-length and explicit timeout requirements;
2. an SLA-boundary completion or qualified-throughput rate for each class;
3. a measurement window equal to the greater of the frozen minimum duration and the
   time needed to reach the frozen minimum eligible sample count at that boundary;
4. a drain deadline and per-request timeout from the frozen timeout policy;
5. a named `deadline_margin` comprising an instrument-resolution reserve and a
   frozen inter-run-variation allowance;
6. a hard wall-clock cap for each load point and repeat that adds the complete
   `deadline_margin` beyond the SLA-boundary window;
7. total `minimum`, `expected`, and `upper_bound` values by summing all required
   phases, repetitions and fixed allowances.

If the SLA does not contain enough information to derive these values, the plan
MUST NOT freeze. Any timeout multiplier, fixed operational allowance or rounding
rule is versioned and frozen in `run-plan.yaml`; it is not selected after observing
the SUT.

The contract MUST freeze a maximum admissible instrument-resolution reserve and a
non-negative inter-run-variation allowance before execution. Their combined
`deadline_margin` MUST be non-zero. The office preflight calibration MUST demonstrate
that the proposed client is capable of staying inside the reserve before travel, but
it is not the resolution used for adjudication. The on-site same-path calibration in
§7.3 MUST independently demonstrate that the actual relevant resolution does not
exceed the same frozen reserve; otherwise the apparatus is invalid and the formal
run cannot begin. `budget-derivation.json` MUST list the two margin components
separately, their units and the formula that maps them to each point cap.

`expected` means the planning duration if the SUT behaves at the frozen SLA boundary.
It is not a prediction of the delivered system. `upper_bound` is the enforced
protocol cap, not a confidence interval. v0.2 claims structural completeness and
enforcement of this derivation, not predictive accuracy for a GPU stack that has not
passed capacity qualification.

When a load point reaches its hard cap, the runner MUST stop that point and mark
outstanding requests according to the frozen censoring policy. Adjudication applies
this precedence:

1. an invalid apparatus controls the result;
2. if the available measurement cannot distinguish the relevant SLA boundary within
   the on-site same-path resolution plus the frozen variation allowance, §4.4
   controls and the affected gate returns `INSUFFICIENT_EVIDENCE` with reason
   `WITHIN_MEASUREMENT_RESOLUTION`;
3. otherwise the cap cause is one of:
   - `SUT_POINT_DEADLINE_EXCEEDED` when the apparatus remained valid but the SUT did
     not achieve the SLA-derived completion requirement; affected service gates are
     `FAIL`;
   - `CLIENT_APPARATUS_INVALID` when the client failed to apply the required load;
     the run is invalid and cannot establish a SUT capacity result;
   - `EXTERNAL_INTERRUPTION` when evidence cannot attribute the stop to the SUT or
     client; affected gates are `INSUFFICIENT_EVIDENCE`.

The runner MUST NOT silently extend a point, borrow time from another phase, or turn
an SLA-derived service timeout into `INSUFFICIENT_EVIDENCE` except for the threshold-
indistinguishability rule mandated by §4.4. The actual elapsed time, both frozen
margin components and cap reason are part of the evidence. An unbounded plan is
invalid.

### 8.2 Coverage profiles

Before the project is frozen, the compiler MAY offer named profiles such as
`screening`, `standard`, and `high_assurance`. A profile may trade load points,
repetitions or cold-start coverage for time, but MUST show which claims become
unavailable.

Selecting a profile changes `run-plan.yaml` and the frozen hash. On site, the
operator MUST NOT silently remove a load point, repeat, reset or quality step to fit
the appointment. An incomplete plan yields `INSUFFICIENT_EVIDENCE` for affected
claims and records the actual elapsed time. A point that executes the frozen steps
but reaches its SLA-derived hard cap follows §8.1; it is not treated as a voluntary
coverage reduction.

### 8.3 Formal execution controls

The execution plan freezes:

- exploratory versus confirmatory phases;
- ordered or randomized load points;
- warm/cold state policy;
- repetition count and independent seeds;
- stopping rules;
- timeout and censoring policy;
- permitted operator interventions;
- evidence upload deadline.

Exploratory measurements can choose a confirmatory range but cannot themselves
produce the formal verdict unless pre-registered as part of the frozen plan.

---

## 9. Sweeps, repetitions and SLO adjudication

### 9.1 Per-point result

For every tested load point and repeat the runner preserves raw outcomes and a
machine-readable gate vector. Aggregation MUST NOT hide repeat disagreement.

The server recomputes all summaries from eligible successful requests. Failed and
timed-out requests are reported separately, including time-to-failure and censoring,
and contribute to reliability gates as defined by the SLA. They do not improve the
successful-request latency distribution.

### 9.2 Compliance vector

The primary sweep result is the ordered vector of all measured points:

```yaml
points:
  - load: 4
    verdict: PASS
  - load: 8
    verdict: FAIL
  - load: 16
    verdict: PASS
non_monotonic_compliance: true
contiguous_compliant_range_established: false
```

Derived scalars MAY include `highest_passing_point` and `lowest_failing_point`, but
the full vector is mandatory. If the lowest failing point is below the highest
passing point, the sweep is non-monotonic and the capacity conclusion is
`INSUFFICIENT_EVIDENCE` unless the frozen contract registered an independently
audited interpretation rule.

An `INSUFFICIENT_EVIDENCE` point at or below the highest passing point prevents a
claim of a contiguous compliant range.

### 9.3 Noise and repeats

The evidence bundle carries both office-preflight and on-site same-path resolution
per metric, with their path fingerprints. Formal gate adjudication MUST use the
on-site value. The office value establishes pre-departure client suitability only.

A threshold decision within the on-site resolution plus its applicable frozen
run-variation allowance is insufficient evidence. A difference between two
configurations below their combined on-site resolutions is marked `within_noise` and
cannot drive ordering or attribution. If a route or boundary fingerprint changes
after on-site calibration, the affected measurement is invalid until recalibrated.

All repeat outcomes are shown. Two passes and one failure are not equivalent to
three marginal passes. The frozen policy defines whether unanimity, a minimum pass
count, or a confidence rule establishes the point verdict.

### 9.4 Comparison boundary

Formal configuration comparison is permitted only when scenario, SLA, run plan,
pack recipe, concrete instance or authorized equivalence class, adjudicator version
and relevant measurement semantics match. The comparison record lists every hash.

Different complete products MAY be compared for whole-system procurement decisions.
Differences in service discipline, engine or configuration prevent component-level
causal attribution unless a registered controlled comparison isolates them.

OICAP v0.2 does not select a cheapest system and does not forecast an unmeasured
configuration.

---

## 10. Quality gates

Quality is evaluated post-hoc by default so that validation does not perturb request
timing. Each workload pack defines:

- validator version and deterministic inputs;
- eligible response population;
- pass, fail and unavailable outcomes;
- privacy behavior and whether references stay local;
- positive controls that prove the gate detects its own violation;
- invalidation controls for missing or malformed outputs.

Every validator that can influence a formal quality gate is a trusted pack component.
Immediately before post-hoc evaluation, the buyer-controlled runner MUST:

1. verify `pack-manifest.json`, `runner-lock.json` and
   `quality-hooks-lock.json`;
2. independently compute the validator artifact or resolved OCI digest, runtime or
   dependency-lock digest, configuration digest and private-reference manifest hash;
3. compare them with the pack-pinned values without accepting a self-reported
   validator version or digest as identity evidence;
4. stage the verified validator and configuration in a content-addressed, read-only
   execution location or immutable container;
5. bind every per-request quality outcome to those verified digests.

An unregistered validator, artifact/runtime/configuration/reference mismatch, or
post-verification mutation MUST emit `QUALITY_VALIDATOR_IDENTITY_INVALID`. The
affected quality gate is `INSUFFICIENT_EVIDENCE`, cannot emit `PASS`, and its requests
cannot contribute to qualified goodput. If the SLA requires that quality gate, the
service SLA cannot pass on the affected evidence.

Every formal gate MUST have a gate-specific positive control. Merely causing some
other gate to fail does not validate it.

A fast empty HTTP 200 response is unsuccessful. Response caching, request
deduplication or degraded generation MAY be allowed only if the frozen deployment
and quality contracts allow them. Quality failure cannot be traded against speed by
an implicit composite score.

---

## 11. Evidence profiles and upload

### 11.1 Local `private-full` evidence

The buyer-controlled runner retains the richest bundle locally, including private
payload references where authorized. It contains normalized contracts, raw timing
observations, response hashes or encrypted responses, configuration evidence,
calibration, environment data, summaries and manifests.

### 11.2 Hosted `redacted` evidence

The default upload MUST allow every hosted gate to be recomputed from its declared
observations while excluding prompt and response content. It includes:

- frozen contract and pack hashes;
- pack instance identifier and nonce proof;
- supported runner and adapter versions;
- office-preflight and on-site same-path calibration records, client fingerprint and
  route/endpoint/boundary fingerprints;
- runner/responder versions and artifact digests, calibration-plan hash, fresh
  challenge transcript and buyer-controlled launch record;
- per-request timing, class, status, error, censoring and quality outcome;
- authority and execution location for each quality outcome;
- validator identifier/version, runner-verified artifact/runtime/configuration/
  reference digests, quality-hooks-lock hash and identity-verification result for
  each quality outcome;
- token counts only when their authority is declared;
- deployment-conformance observations allowed by policy;
- raw repeat boundaries;
- local full-bundle hash;
- manifest hashes.

The uploader MUST preview exactly which fields leave the buyer's environment.
Secrets, credentials, local absolute paths and workspace file names MUST be absent.

### 11.3 Server verification and adjudication

The OICAP service MUST:

1. authenticate the buyer project and upload actor;
2. verify schema versions, hashes, pack binding, nonce, runner support and evidence
   completeness, including that every recorded quality-validator digest and lock hash
   matches the official pack;
3. recompute metrics and gate outcomes from uploaded observations, while preserving
   whether the underlying quality decision was made by the buyer-local validator or
   a server-side validator;
4. reject a producer-supplied summary that disagrees;
5. evaluate service SLA and deployment conformance separately;
6. issue a canonical adjudication record and human-readable report;
7. preserve the exact adjudicator image or digest and ruleset version.

For buyer-local private validation, server recomputation establishes that the frozen
gate follows from the uploaded quality outcomes; it does not independently establish
that each semantic outcome was correct or that the recorded local artifact actually
executed. The verified pack identity narrows which validator the buyer-controlled
runner was authorized to execute; it is not remote attestation. This limitation is
acceptable in the buyer-operated baseline trust model only when the acceptance
policy permits local validation, and it MUST remain visible in the report.

Self-contained unsigned manifests establish internal consistency, not who ran the
test or whether a producer regenerated altered evidence. The hosted service MUST not
describe them as tamper-proof. Service-side receipt, server-signed adjudication and
append-only history strengthen the chain after upload; hardware attestation remains
a separate future control.

---

## 12. Technical reports and retests

### 12.1 Required report sections

The report MUST show:

- assurance level and whether formal procurement verdicts are enabled;
- project, contract, pack, run, client and adjudicator identities;
- the full measured load and repeat matrix;
- every service gate and reason;
- apparatus validity, realized load, and office versus on-site per-metric resolution;
- `service_sla_verdict`;
- deployment requirement, evidence level and finding matrix;
- `deployment_conformance_verdict`;
- overall technical result;
- missing or insufficient evidence;
- deviations, operator interventions and elapsed wall-clock time;
- history links for retest, review and supersession;
- a plain-language limitations section.

### 12.2 Retest policy

`acceptance-policy.yaml` freezes:

- maximum attempts;
- who authorizes and operates a retest;
- cooldown, reset and observation procedure;
- paths that may change between attempts;
- paths whose change creates a new SUT identity or project revision;
- whether a new sealed instance is mandatory;
- how the new result supersedes the previous result.

The service MUST compare observed changes with this allowlist before adjudication.
Replacing hardware, model, quantization or another frozen identity field cannot be
presented as a retest of the same SUT unless the pre-tender policy explicitly defines
that equivalence.

### 12.3 Technical review

An appeal may challenge evidence completeness, calculation, pack execution,
conformance interpretation or service availability. It does not erase the original
record and does not ask OICAP to decide payment or legal remedies.

---

## 13. Minimal website and API

The v0.2 website is a core product surface. It MUST provide:

1. authenticated organization and role management;
2. an SLA/workload/SUT/policy authoring wizard with machine-readable export;
3. validation errors that identify ambiguous or unsupported requirements;
4. project freeze and immutable revision history;
5. pack compilation, issue, download and expiry;
6. preflight result registration;
7. evidence upload with a redaction preview;
8. server-side progress, verification and adjudication;
9. separate service and conformance verdict views;
10. report download and stable record identifier;
11. retest, supersession and technical-review workflows.

The website MUST never require private prompts or responses for the baseline hosted
flow. A fully local enterprise deployment MAY be supported later using the same
protocol and adjudicator image.

The API MUST expose the same state machine and reason codes as the UI. The UI cannot
invent a result not present in the canonical adjudication JSON.

---

## 14. Internal procurement rehearsal

Before the v0.2 schema is declared stable, the team MUST walk one authorized real or
de-identified enterprise procurement case through:

```text
tender requirement -> typed SLA -> workload profile -> SUT requirements
-> acceptance policy -> compiled plan -> mock on-site execution
-> technical verdict -> retest/review discussion
```

The rehearsal MAY use a manual compiler and manual report. Its purpose is to expose
which procurement fields are unavailable, which terms are ambiguous, which evidence
the supplier can provide, and which steps cause operational dispute before those
assumptions become code.

The rehearsal MUST also flag requirements that are syntactically valid, unambiguous
and freezable but appear physically doubtful to the human reviewers. This is a
non-binding authoring warning, not a performance prediction: OICAP does not reject or
rewrite such a requirement without measured evidence, and the buyer remains free to
freeze it after acknowledgement.

Only structural findings may enter the public repository. Tender documents, prices,
supplier identities, internal workload data, security details and organizational
decisions remain outside it unless the company gives explicit release authorization.
The public record MUST be reviewed for indirect identification as well as direct
names.

---

## 15. Security, privacy and operational controls

At minimum v0.2 MUST implement:

- short-lived scoped upload credentials;
- encrypted transport and server-side encryption;
- secret-field rejection and log redaction;
- per-project authorization and audit events;
- pack nonce replay detection;
- upload size and decompression limits;
- parser isolation for untrusted bundles;
- deterministic adjudicator containers or images;
- server-signed adjudication records;
- retention and deletion policies for hosted redacted evidence;
- export of project history before account closure.

The system MUST document what signatures prove. A server signature proves that the
OICAP service issued a record over stated evidence; it does not prove that the
machine or model truthfully identified itself.

---

## 16. Delivery slices

### Slice A — contract and CPU protocol qualification

- finalize the Charter and v0.2 schemas;
- run v0.1 measurement against a real CPU llama.cpp endpoint;
- close protocol defects found in genuine SSE, usage, timeout, empty and error paths;
- complete the internal procurement workflow rehearsal;
- freeze the initial SLA-to-pack data contract.

### Slice B — local acceptance engine

- compile packs and time budgets;
- run preflight and sweeps;
- evaluate gate-specific quality controls;
- calculate the complete compliance vector;
- emit dual local-preview verdicts and redacted evidence.

### Slice C — hosted alpha

- implement project lifecycle, upload, server recomputation and canonical reports;
- sign adjudications and preserve supersession history;
- publish v0.2 alpha with formal procurement verdicts disabled.

### Slice D — GPU qualification

- validate at least one real GPU stack and supported configuration envelope;
- exercise memory pressure, concurrency, timeout, batching and quality behavior;
- independently reproduce expected pass, fail, client-saturated and insufficient-
  evidence outcomes;
- enable formal reports only for the qualified envelope.

### Slice E — enterprise pilot

- run a buyer-controlled end-to-end on-site pilot;
- document operational and technical disputes;
- revise schemas only through explicit versioning;
- decide whether the evidence assurance is adequate for contractual use.

---

## 17. Explicit non-goals for v0.2

v0.2 does not:

- provide a public leaderboard or universal score;
- recommend a supplier, accelerator count, price or cost optimum;
- predict performance on an unmeasured configuration;
- assert that a standard or synthetic pack is identical to production traffic;
- prescribe contractual remedies;
- offer cryptographic proof of model identity without attestation;
- make MoE-specific research, trace simulation or a paper part of the acceptance
  path;
- permit supplier-controlled execution alone to generate the baseline formal result;
- call a pilot result a formal procurement verdict before GPU qualification.

---

## 18. Compatibility and change control

- v0.1 bundles remain verifiable by the v0.1 verifier and may be imported as
  measurement evidence only.
- Importing v0.1 evidence MUST NOT manufacture a v0.2 SLA or conformance verdict when
  required fields are absent.
- Schemas, compiler, runner, workload recipe, concrete instance and adjudicator are
  versioned independently and bound by hash.
- Any change to metric population, threshold semantics or verdict logic requires a
  new adjudicator ruleset version and regression fixtures.
- A hosted re-adjudication of old evidence creates a linked new record and leaves the
  prior result intact.

Implementation is complete only when the separately maintained
`OICAP_V0_2_ACCEPTANCE_CRITERIA.md` is satisfied by artifacts and adversarial
controls, not merely by unit-test names or feature documentation.
