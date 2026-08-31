# OICAP v0.2 Acceptance Criteria

**Status:** Draft for independent audit

**Date:** 2026-08-30

**Normative specification:** [Platform Product Specification v0.2](PLATFORM_PRODUCT_SPECIFICATION_V0_2.md)

**Product authority:** [OICAP Product Charter](OICAP_PRODUCT_CHARTER.md)

**Does not modify:** any released OICAP v0.1 artifact or claim

This document defines evidence required to accept OICAP v0.2. A test name, green CI
job, implementation note, screenshot or self-authored checkpoint report is not by
itself sufficient evidence. Each criterion requires inspection of the delivered
artifact and at least one independently constructed positive or negative control.

The criteria distinguish three release decisions:

1. **schema freeze readiness** — the procurement data contract can be implemented;
2. **v0.2 acceptance-alpha release** — the end-to-end software may be released for
   internal and explicitly non-contractual pilots;
3. **formal-verdict enablement** — the hosted service may issue formal technical
   procurement verdicts inside a specifically validated GPU envelope.

The third decision is not required to publish v0.2 software. It is the entry gate
for a v0.3-or-later service in which `formal_procurement_verdict_enabled` may be
`true`; it does not upgrade historical v0.2 records.

---

## 1. Evidence rules

For every applicable criterion the release record MUST contain:

- source revision and release artifact hashes;
- exact commands or API calls used;
- fixtures or project records sufficient to reproduce the check;
- expected and actual outcome;
- platform and dependency identity;
- links to machine-readable outputs, not only prose summaries;
- an independent audit disposition.

A control is **positive** when it deliberately creates the prohibited condition and
demonstrates that the intended gate catches that condition. A control that merely
causes some unrelated gate to fail does not validate the target gate.

No criterion may be waived silently. A waiver records scope, reason, approver,
expiry, resulting assurance limitation and the exact claims thereby disabled.

---

## 2. Schema-freeze criteria

### V02-AC01 — v0.1 immutability and version boundary

**Requirement:** v0.2 development MUST NOT rewrite the released v0.1 specification,
tag, schemas, evidence semantics or release artifact. Incompatible changes use new
versions.

**Evidence:**

- the v0.1 annotated tag still resolves to the independently audited commit;
- the released wheel hash and packaged v0.1 schemas remain unchanged;
- a v0.1 bundle verifies with the released v0.1 verifier;
- v0.2 imports the bundle as measurement evidence without manufacturing fields that
  v0.1 never recorded.

**Positive control:** remove a v0.2-required field from an imported fixture and show
that adjudication returns `INSUFFICIENT_EVIDENCE` or refuses the import rather than
supplying a default.

### V02-AC02 — closed, typed procurement contract

**Requirement:** every document in the frozen contract set validates against its
packaged schema. Top-level unknown keys are rejected; intentional extension maps
remain usable. Procurement facts are explicit.

**Evidence:** valid fixtures for project, SLA, workload profile, SUT requirements,
acceptance policy, run plan and pack recipe; normalized hashes; round-trip
serialization; schemas present in the installed distribution.

**Positive controls:** each of the following MUST be rejected with a path-specific
error:

- misspelled top-level key;
- unknown contract major version;
- closed-loop load without required concurrency/session semantics;
- negative think time or duration;
- required deployment field with no value or state;
- `quantization` or any other key omitted entirely from the versioned deployment
  catalogue;
- a catalogue key without exactly one of `required`, `allowed_set`, `not_required`,
  or `informational`;
- invalid workload weights;
- an unbounded execution plan;
- an unauthorized mutable path in a retest policy.

**Reverse controls:** declared extension maps, additional workload classes, additional
quality metrics and engine-specific informational metadata remain accepted where the
schema deliberately permits them.

### V02-AC03 — unambiguous SLA semantics

**Requirement:** the SLA expresses metric population, class, statistic, comparator,
threshold, duration/sample sufficiency and quality eligibility. Bare `tps` is not a
valid frozen metric.

**Positive controls:**

- `tps: 20` is rejected with alternatives named;
- a p95 latency without its request population is rejected;
- an aggregate gate without weighting semantics is rejected;
- an inter-token gate without authoritative token timing adjudicates as
  `INSUFFICIENT_EVIDENCE`, not from chunk timing;
- a missing required metric cannot pass;
- an empty or whitespace-only first stream event cannot end TTFT.

**Reverse control:** a complete class-aware SLA containing aggregate output-token
throughput, TTFT, end-to-end latency, success rate and a quality gate compiles without
manual edits.

### V02-AC04 — procurement workflow rehearsal before schema freeze

**Requirement:** one authorized real or de-identified enterprise procurement case is
walked through from tender requirement to retest/review discussion before the v0.2
schemas are declared stable. Code is not required for this rehearsal.

**Evidence:** a private rehearsal record and a separately reviewed public structural
summary identifying:

- fields that procurement staff could and could not supply;
- ambiguous business phrases and their typed resolution;
- configuration evidence the supplier can provide on site;
- requirements that are typed and freezable but of doubtful physical achievability,
  and how the authoring flow warns without pretending to predict performance;
- estimated setup and execution time;
- likely dispute points and technical state transitions;
- schema changes resulting from the exercise.

**Confidentiality control:** an authorized reviewer demonstrates that the public
summary contains no tender text, price, supplier identity, private workload,
security detail, internal decision, direct identifier or reasonably inferable project
identity. The private source material is not committed to the public repository.

Passing V02-AC01 through V02-AC04 permits the v0.2 schema freeze decision.

---

## 3. Protocol and measurement criteria

### V02-AC05 — real CPU endpoint protocol compatibility

**Requirement:** before the acceptance engine relies on the measurement kernel, the
released runner is exercised against a real CPU-hosted OpenAI-compatible inference
service, initially llama.cpp. A repository-owned deterministic test server is not
sufficient for this criterion.

**Evidence:** a versioned compatibility matrix and evidence bundles covering:

- genuine SSE streaming with role-only, empty and content events;
- non-streaming response;
- authoritative usage present and absent;
- timeout and right-censoring path;
- connection or HTTP error;
- HTTP 200 with no substantive content;
- multiple chunks and an unavailable authoritative ITL;
- repeated real requests showing non-zero timing variance.

**Positive controls:** empty content fails success/quality without improving the
successful latency distribution; timeout enters reliability and time-to-failure but
not successful-request latency; chunk intervals are never labelled token intervals.

Passing this criterion unlocks v0.2 software work and pilot use. It does not unlock
formal capacity verdicts.

### V02-AC06 — load realization and apparatus validity

**Requirement:** the runner proves that it applied the requested load. Client
saturation, scheduler lag or insufficient client resources cannot be reported as a
SUT capacity limit. Before measurement it also establishes per-metric resolution on
the actual on-site path and compares it with the frozen reserve.

**Positive controls:** independently construct:

- a heterogeneous closed-loop workload that would drain static worker partitions;
- an over-requested closed-loop plan that the client cannot sustain;
- a think-time workload with injected client-side delay before submission;
- an open-loop workload whose schedule exceeds client capability;
- an office preflight that passes on loopback followed by an on-site path whose
  measured resolution exceeds the frozen reserve;
- an on-site route, VPN/jump, TLS/load-balancer, ingress or endpoint change after a
  valid calibration;
- an otherwise functional responder that is not named by the pack, has the wrong
  artifact digest or version, presents a mismatched plan hash, or replays a prior
  challenge nonce;
- a substituted responder that self-reports the expected digest/build identity while
  the buyer-side launcher computes a different artifact digest;
- variation injected inside the frozen SUT boundary, which must remain service
  behavior rather than being reclassified as instrument resolution;
- a calibration path whose outside-boundary contribution cannot be separated from
  in-boundary SUT variation.

Each must either maintain the mathematically expected load or produce an invalid
apparatus reason and prevent a service-capacity verdict. A genuinely slow service
under a healthy closed-loop client must not be misclassified as client saturation.
An outside-boundary resolution above reserve, a post-calibration path change, or an
inseparable calibration path MUST emit `CLIENT_APPARATUS_INVALID`, move the attempt
to `RUN_INVALID`, and prevent the formal measured phase until same-path calibration
succeeds. In-boundary variation must remain in service observations and cannot
enlarge the frozen margin.

An unregistered, mismatched or replaying responder MUST emit
`CALIBRATION_RESPONDER_IDENTITY_INVALID`, move the attempt to `RUN_INVALID`, and
prevent both calibration and formal measurement. A responder artifact correctly
pinned by the pack, launched under buyer control and completing a fresh challenge is
the reverse control and may proceed to path calibration.

**Evidence:** realized mean concurrency or schedule lag, requested/expected ratio,
resource headroom, both office and on-site per-metric resolutions, client/route/
endpoint/boundary fingerprints, calibration validity and stable reason codes appear
in the bundle and hosted report. The evidence also carries runner/responder versions
and digests, project/pack/plan hashes, challenge transcript and buyer-controlled
launch record.

### V02-AC07 — metric populations, failure and noise handling

**Requirement:** successful latency, failure latency, reliability, censoring, noise
and comparison populations are explicit and internally consistent.

**Positive controls:**

- add a fast failing request to a successful fixture and demonstrate that the
  successful latency distribution is unchanged;
- produce a real timeout and demonstrate `censored: true` and time-to-failure;
- create a threshold value inside instrument resolution and obtain
  `INSUFFICIENT_EVIDENCE`;
- compare two configurations within combined resolution and obtain `within_noise`
  with no ranking;
- alter an observation without updating its manifest and demonstrate verification
  failure;
- regenerate an altered unsigned bundle and demonstrate that verification scope
  still says producer identity, detached signature and external timestamp are not
  proven.

No metric overhead is subtracted to create a more favorable value.

---

## 4. Pack compiler and field-readiness criteria

### V02-AC08 — SLA-to-pack compilation and sealed instances

**Requirement:** a valid frozen project produces a runnable pack without hand-editing,
and an unsupported requirement produces a refusal rather than a nearest-match pack.

**Evidence:** at least one pack each for `oicap_standard`, `buyer_local` and
`distribution_matched_synthetic`; complete manifests; compiler version; normalized
contract hash; public recipe; sealed or buyer-local instance binding; expiry; nonce;
runner lock; calibration-responder binary/image or immutable OCI reference and lock;
on-site calibration plan; quality-hook artifacts/references and
`quality-hooks-lock.json`; client requirements; execution plan; wall-clock budget.

**Positive controls:**

- alter the frozen SLA after compilation and show pack binding fails;
- substitute a concrete instance from another project and show execution or upload
  fails;
- remove or replace the calibration-responder artifact/descriptor and show
  `pack-manifest.json` or runner-lock verification fails;
- remove or replace a quality-validator artifact, runtime/dependency lock,
  configuration or reference manifest and show pack or runner-lock verification
  fails;
- replay an expired or already consumed formal nonce and show refusal;
- request an unsupported quality validator and show compile refusal;
- attempt to label distribution-matched synthetic input as production-equivalent
  without matching evidence and show refusal.

**Reproducibility control:** identical authorized inputs and seed reproduce the same
pack manifest; a new formal attempt creates a distinct authorized instance while
preserving recipe semantics.

### V02-AC09 — client capability self-check before site travel

**Requirement:** every pack declares its client resource envelope and includes a
pre-departure preflight that tests the exact locked runner and proposed client
topology against one or more compiler-issued reference profiles derived from the
frozen SLA, workload profile and run plan.

**Evidence:** `client-requirements.yaml` and `client-preflight.json` record CPU,
memory, descriptors, network, storage, clock, runner version, maximum load, measured
headroom, client fingerprint, validity period and whether a distributed topology is
required. `preflight-endpoint-profile.yaml` records TTFT pacing, event cadence,
output-length/response-size distribution, class mix, streaming semantics, maximum
in-flight requests, aggregate event rate, minimum sustained duration, cumulative
request/chunk/byte volume, tolerance and profile hash.

**Positive controls:**

- constrain CPU or scheduler capacity until planned concurrency cannot be sustained;
- exhaust the declared file-descriptor or evidence-write budget safely in a fixture;
- use a zero-delay or otherwise unpaced endpoint that reaches peak concurrency but
  does not serve the compiler-issued timing profile;
- end a correctly paced preflight before its minimum sustained duration or cumulative
  event-volume requirement;
- use an expired preflight;
- run formally from a materially different client fingerprint;
- request a load above the qualified single-client envelope.

Each condition MUST block the formal plan, require an authorized multi-client plan,
or require a new preflight. It MUST be discoverable before travel when the condition
is reproducible off site.

**Boundary control:** the report distinguishes office preflight from the separate
on-site network/connectivity check. Passing the former cannot assert the latter.
Reference-endpoint TTFT and throughput are labelled harness-health observations and
cannot be presented as SUT measurements or predictions.

### V02-AC10 — declared and executable wall-clock budget

**Requirement:** every compiled plan has bounded `minimum`, `expected` and
`upper_bound` wall-clock estimates covering setup, warm-up, all points, repeats,
resets, cold starts, quality evaluation, packaging, upload and reserve. The compiler
derives the budget from the frozen SLA boundary, minimum samples/duration, workload
lengths, timeout policy and fixed protocol allowances, and enforces a hard cap for
each point and repeat. Every cap extends beyond its SLA-boundary window by a named,
non-zero frozen margin no smaller than the reserved instrument resolution plus the
frozen inter-run-variation allowance.

**Evidence:** `budget-derivation.json` with inputs, formulas, rounding and sources;
separate instrument-resolution and run-variation margin components; component sums;
hard-cap fields in the execution plan; one end-to-end CPU execution showing that
phase and point caps are enforced; supported coverage profiles and the claims
disabled by each profile.

**Positive controls:**

- an unbounded phase or plan is rejected;
- an SLA missing the information required to derive boundary request time or
  completion rate cannot freeze;
- a zero combined deadline margin is rejected;
- an office preflight whose measured timing resolution exceeds the frozen reserve
  rejects the proposed client before travel;
- an office preflight inside the reserve followed by an on-site same-path resolution
  above it emits `CLIENT_APPARATUS_INVALID` and prevents the formal measured phase;
- a plan exceeding the buyer's frozen appointment window cannot be frozen without a
  deliberate profile change;
- an endpoint paced at the SLA boundary with jitter inside the on-site same-path
  resolution and frozen variation allowance cannot receive `FAIL` solely because it
  touches the un-margined boundary; if the threshold remains indistinguishable,
  §4.4 returns `INSUFFICIENT_EVIDENCE` with
  `WITHIN_MEASUREMENT_RESOLUTION`;
- an apparatus-valid endpoint deliberately slower than the complete boundary plus
  margin hits the point cap, stops with
  `SUT_POINT_DEADLINE_EXCEEDED`, censors outstanding requests under the frozen rule
  and fails the affected service gates instead of running indefinitely or returning
  insufficient evidence;
- a client-invalid run hitting a cap produces `CLIENT_APPARATUS_INVALID` and cannot
  establish a SUT capacity failure;
- an unattributable interruption produces `EXTERNAL_INTERRUPTION` and insufficient
  evidence rather than a service failure;
- removing a load point, repeat, reset or quality step after freeze changes the hash
  or makes the run incomplete;
- an incomplete on-site run yields `INSUFFICIENT_EVIDENCE` for affected claims, not a
  result computed from the convenient subset;
- a retry reserve cannot become a hidden additional formal attempt.

At least one standard profile MUST fit an eight-hour field appointment including the
declared operational reserve, or the UI MUST state that the plan requires multiple
appointments. The threshold is a product-operability check, not permission to weaken
an already frozen contract.

This criterion establishes structural completeness, deterministic derivation and
timeout enforcement. It does not claim that `expected` predicts a real GPU system.
Estimate-versus-actual accuracy within a supported GPU envelope is deferred to
V02-AC20. Threshold and cap adjudication use the on-site resolution; the office
preflight value cannot substitute for it.

---

## 5. Adjudication criteria

### V02-AC11 — complete sweeps, repetitions and non-monotonicity

**Requirement:** the primary capacity result is the complete point-by-repeat gate
matrix. Derived maximum or boundary scalars never hide failed or unresolved lower
points.

**Positive controls:**

- `{4: FAIL, 8: PASS, 16: PASS}` sets `non_monotonic_compliance: true` and cannot
  claim a contiguous compliant range;
- `{4: PASS, 8: INSUFFICIENT_EVIDENCE, 16: PASS}` cannot claim a contiguous range;
- repeats `{PASS, PASS, FAIL}` remain visible and follow the frozen repeat rule;
- an exploratory point selected after seeing data cannot silently become a
  confirmatory point;
- changing only the point order or reset policy after freeze invalidates binding.

The report includes `highest_passing_point` and `lowest_failing_point` only as
derived fields beside the full vector.

### V02-AC12 — quality-gate validity and anti-shortcut behavior

**Requirement:** every formal quality or correctness gate is post-hoc by default,
versioned, privacy-scoped, bound to a pack-locked validator execution closure, and
demonstrated by its own positive control.

**Identity evidence:** `runner-lock.json`, `quality-hooks-lock.json` and
`pack-manifest.json` cover validator artifact/OCI, runtime or dependency lock,
configuration and private-reference manifest. Immediately before evaluation the
buyer-controlled runner independently computes those digests, stages an immutable
execution copy and binds every quality outcome to the verified identities.

**Positive controls:** at minimum cover:

- empty/whitespace HTTP 200;
- malformed structured output;
- a semantically wrong but syntactically valid response;
- response truncation;
- cached or constant response when request-specific output is required;
- unavailable private reference data;
- a validator whose artifact, runtime/dependency lock, configuration or reference
  manifest digest differs from the official pack;
- a substituted validator that self-reports the expected identifier and version
  while the runner computes a different digest;
- a validator artifact mutated after initial verification rather than executed from
  the content-addressed read-only stage.

Each target gate catches its own violation. A fast invalid response cannot improve
goodput. Missing validator evidence yields `INSUFFICIENT_EVIDENCE`, not a quality
pass. Post-hoc validation timing is excluded from SUT latency and reported
separately. Every validator identity mismatch emits
`QUALITY_VALIDATOR_IDENTITY_INVALID`; the affected quality gate cannot return
`PASS`, and its requests cannot contribute to qualified goodput. A correctly pinned,
independently hashed and immutably staged validator is the reverse identity control.

### V02-AC13 — dual verdicts and deployment conformance

**Requirement:** service performance and deployment conformance are independently
adjudicated and displayed.

**Evidence:** a conformance matrix covering every required model, quantization,
engine, container, command, hardware, topology and configuration field with evidence
layer L0-L3 and stable result reasons. The physical-memory row lists its catalogue
prerequisites and distinguishes `UNAVAILABLE_BY_CONTRACT` from
`UNAVAILABLE_BY_ENVIRONMENT`.

**Positive controls:**

- a smaller substituted model that satisfies all performance gates produces
  `service_sla_verdict: PASS`, `deployment_conformance_verdict: FAIL`, overall FAIL;
- required model files present on disk while the runtime process cannot be bound to
  them produces insufficient evidence or failure according to the frozen rule;
- a buyer-observed restart ties hashes, command line, opened artifacts and endpoint
  to the measured process;
- an endpoint proxying inference to an undeclared external service fails or becomes
  insufficient through the frozen network-boundary checks;
- a physical memory observation below the conservative complete-topology minimum is
  contradictory;
- declared tensor parallelism or CPU offload prevents use of an invalid single-GPU
  memory shortcut;
- a contract with `parallelism.requirement_state: not_required` displays
  `physical_memory_consistency.status: UNAVAILABLE_BY_CONTRACT`, names the lost
  runtime-identity support, and does not report pass or a missing field;
- the same unavailable-by-contract condition prevents freeze when the acceptance
  policy requires the physical-memory check or the dependent L2 assurance;
- an `allowed_set` too broad to compute a conservative minimum is treated as
  unavailable by contract rather than selecting a convenient member after execution;
- an operating environment that blocks runtime inspection uses
  `UNAVAILABLE_BY_ENVIRONMENT`, not the contract-caused status;
- API model name or challenge fingerprint alone cannot create conformance PASS;
- an explicitly `not_required` field is reported as such, not silently passed.

The UI and exported report show both verdicts before the overall technical result.

### V02-AC14 — comparison refusal and causal boundaries

**Requirement:** the service compares only compatible evidence and separates
whole-system procurement comparison from component attribution.

**Positive controls:** mismatch scenario, SLA, run plan, pack instance/equivalence,
metric semantics or adjudicator version one at a time and demonstrate refusal or an
explicit non-comparable result.

Two complete systems with different service disciplines MAY be compared as delivered
products if the frozen procurement contract permits it. The same pair MUST NOT
support a claim that one component caused the difference without a registered
controlled design.

No v0.2 comparison recommends cost, a supplier, an unmeasured card count or a
universal score.

---

## 6. Hosted evidence and workflow criteria

### V02-AC15 — data-minimized upload remains recomputable

**Requirement:** the hosted redacted profile contains enough evidence to recompute
every hosted gate from its declared observations and excludes prompt/response
content, credentials, absolute paths and workspace file names by default. For a
buyer-local private quality validator, the server recomputes the frozen aggregation
over per-request outcomes but does not claim to have independently re-evaluated
content it never received.

**Evidence:** field-level data inventory, upload preview, local full-bundle hash,
redacted fixture, server recomputation result and privacy scan.

**Positive controls:**

- inject a credential, absolute path, private prompt and response into candidate
  upload fields and demonstrate rejection or redaction before transmission;
- alter a per-request observation and demonstrate manifest or recomputation failure;
- upload a producer summary inconsistent with observations and demonstrate that the
  server ignores/rejects it;
- omit a field required for a verdict and obtain `INSUFFICIENT_EVIDENCE`, not an
  inferred value;
- submit a buyer-local quality result without validator version, execution location,
  runner-verified artifact/runtime/configuration/reference digests,
  quality-hooks-lock hash, eligible population or response/reference hashes and
  demonstrate refusal or an explicit insufficient-evidence result;
- attempt decompression or payload-size abuse and demonstrate bounded rejection.

### V02-AC16 — canonical server adjudication and UI parity

**Requirement:** the hosted service, not a local preview, issues the canonical result.
API JSON, rendered report and UI derive from the same adjudication object.

**Evidence:** an end-to-end project traverses authoring, validation, freeze, pack
issue, preflight, upload, verification and adjudication; each transition records
actor, time, versions and hashes.

**Positive controls:**

- a local preview cannot be uploaded or displayed as canonical;
- unsupported runner or adjudicator version is refused;
- duplicate/replayed pack nonce is refused;
- an adjudicated result with one or both verdicts equal to
  `INSUFFICIENT_EVIDENCE` remains in project state `ADJUDICATED`; the verdict value is
  never serialized as a competing lifecycle state;
- API/UI/report snapshot tests expose both verdicts and all reason codes;
- before GPU qualification, every surface displays `assurance_level: pilot` and
  `formal_procurement_verdict_enabled: false`;
- a hidden or omitted pilot warning fails the criterion even if JSON is correct.

### V02-AC17 — retest, supersession and technical review

**Requirement:** retests obey the pre-frozen acceptance policy. Old evidence and
adjudications remain addressable. OICAP does not derive a commercial remedy.

**Positive controls:**

- modify an allowed tuning path and complete an authorized retest with a new sealed
  instance;
- modify a forbidden model, hardware or quantization path and demonstrate refusal or
  creation of a new SUT/project identity;
- exceed the allowed attempt count;
- supersede a result and demonstrate the previous record remains retrievable;
- open a technical review and demonstrate that it cannot erase the source record;
- attempt to infer `ACCEPT`, payment deduction or delivery rejection from a partial
  gate result and demonstrate no such product rule exists.

The report may record a buyer-entered commercial disposition as external metadata,
but does not calculate it.

---

## 7. Release and qualification criteria

### V02-AC18 — distribution, migration and independent execution

**Requirement:** the exact released distribution, not only the source tree, completes
the supported workflow in a clean environment.

**Evidence:**

- release tag resolves to the audited commit;
- wheel or container hashes match release claims;
- packaged schemas, compiler assets, calibration-responder and quality-validator
  artifact descriptors, and report templates are present;
- clean-install execution completes validate, compile, preflight, run, upload to a
  test service, verify and adjudicate;
- Linux and macOS supported paths exchange and verify evidence in both directions;
- a v0.1 bundle follows the documented compatibility path without semantic upgrade.

An independent auditor downloads the release artifact from its public release
location and repeats the workflow outside the source tree.

### V02-AC19 — acceptance-alpha release boundary

The v0.2 acceptance alpha may be released when:

- V02-AC01 through V02-AC18 pass;
- the CPU protocol compatibility evidence is public or auditable;
- the procurement rehearsal's public structural summary passes confidentiality
  review;
- no open blocking audit finding remains;
- release notes state that real GPU capacity correctness is not yet qualified;
- every result surface keeps formal procurement verdicts disabled.

The release notes MUST distinguish implemented functionality from validated claim.

### V02-AC20 — GPU capacity qualification and formal-verdict enablement

**Requirement:** formal technical procurement verdicts remain disabled until the
measurement and adjudication stack is validated on a real supported GPU inference
deployment.

**Minimum evidence:**

- exact model, quantization, engine, container, driver, GPU topology and settings;
- a qualified load-client preflight;
- genuine memory pressure, batching, queueing, streaming and timeout behavior;
- at least one independently predicted or externally checked passing point;
- at least one failing SLA point;
- at least one client-saturated run correctly invalidated;
- at least one insufficient-evidence path;
- repeated points sufficient to expose run-to-run variation;
- budget estimate-versus-actual evidence for the supported GPU envelope, with error
  reported separately for setup, measurement, drain/reset and post-processing rather
  than hidden in one total;
- L2 runtime-binding and physical-memory evidence;
- independent recomputation of the hosted verdict;
- a stated supported envelope beyond which formal verdicts remain disabled.

**Positive controls:** substitute the model or quantization; under-drive the load;
remove required runtime-binding evidence; corrupt an upload; and use an unqualified
engine/version. Each must prevent an overall formal PASS for the affected project.

Passing V02-AC20 permits a v0.3-or-later qualified service to enable:

```yaml
assurance_level: gpu_qualified
formal_procurement_verdict_enabled: true
```

only for the documented model/engine/protocol/configuration envelope. It does not
convert OICAP into a universal certification for all private deployments, and it
does not alter the assurance label of any v0.2 record.

---

## 8. Required audit summary

The final audit MUST report each criterion as `PASS`, `FAIL`, `BLOCKED`, or
`NOT_APPLICABLE`, with evidence and residual limitations. `BLOCKED` is not a release
pass. `NOT_APPLICABLE` requires a normative reason and cannot be used for a feature
that the release advertises.

The audit MUST explicitly answer:

1. Can the buyer discover an inadequate load client before arriving on site?
2. Is preflight paced and sustained according to the frozen SLA rather than accepted
   from a momentary peak-concurrency burst?
3. Is timing resolution re-established on the actual on-site path, and does a value
   above the frozen reserve block measurement rather than reuse the office result?
4. Can the complete protocol execute inside its frozen wall-clock budget without
   silently dropping coverage, and does an SLA-slow SUT stop with the correct failure
   reason instead of running indefinitely?
5. Can an SLA-boundary SUT avoid a false `FAIL` caused solely by timer resolution or
   frozen run-variation allowance?
6. Can a substituted smaller model pass service gates while still failing deployment
   conformance?
7. Does a contract that declines a physical-envelope prerequisite show
   `UNAVAILABLE_BY_CONTRACT` rather than pass or silently omit the check?
8. Can a producer-controlled summary override raw evidence?
9. Can an incomplete or non-monotonic sweep produce a misleading maximum capacity?
10. Can private payload or credentials leave the buyer environment by default?
11. Can any surface issue a formal verdict before the GPU qualification gate?
12. Are the code, schemas, released artifacts and audited revision exactly aligned?
13. Does every verdict-affecting component, including the calibration responder and
    every quality validator, have an owner, pack-pinned artifact identity and runtime
    validation before use?

Only evidence-backed affirmative answers to the intended safety property permit the
corresponding release decision.
