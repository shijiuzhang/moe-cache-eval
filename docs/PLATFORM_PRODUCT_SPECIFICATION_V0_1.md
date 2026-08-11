# Open Inference Capacity and Acceptance Platform

## Product specification v0.1

**Status:** Draft for independent audit  
**Date:** 2026-08-11  
**Scope:** Product contract and MVP requirements; not an implementation claim  
**Working name:** *Platform* (a public product name is intentionally deferred)

This document defines an open, vendor-neutral platform for planning and
accepting privately deployed large-model appliances. It translates a stated
workload and service-level objective (SLO) into reproducible measurements of
which tested configurations satisfy that objective. Mixture-of-Experts (MoE)
diagnostics are a first-class extension, but the acceptance core is deliberately
model- and engine-agnostic.

The specification is written for independent review before implementation. The
words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are
normative.

---

## 1. Problem statement

Private-deployment procurement is usually expressed in incompatible units:

- users specify concurrent users, context lengths, task mixes and acceptable
  response times;
- vendors quote model names, accelerator counts, peak bandwidth and a small
  number of favorable throughput measurements;
- serving engines expose their own batch, queue, cache and offload controls;
- acceptance teams receive no common procedure for proving that the purchased
  system satisfies the intended workload.

This creates two asymmetric failures:

1. **Over-provisioning:** a bidder recommends more hardware than the workload
   requires, raising acquisition and operating cost or losing the bid.
2. **Under-provisioning:** a system looks responsive in a single-user demo but
   fails its latency or availability target under production concurrency.

The Platform's job is not to make an untested system faster. Its job is to make
the capacity/SLO trade-off measurable, reproducible and contractible.

### 1.1 Product thesis

For a declared workload, SLO and system configuration, an independent runner
can produce a portable evidence bundle that answers:

- What load was actually applied?
- What service discipline and admission behavior were observed?
- Which latency, throughput, quality and reliability targets passed?
- What is the highest **measured** compliant load?
- Which tested configuration is the least costly one that passes?
- Where is the first observed failure boundary?
- Can another party reproduce the result or identify why it is not comparable?

### 1.2 What “convert an SLO to GPU count” means

The Platform MUST distinguish three levels of answer:

| Level | Output | Evidentiary status |
|---|---|---|
| Measured | A specific hardware/software configuration passed a frozen scenario | Suitable for acceptance evidence |
| Interpolated | A value between measured points is estimated with an uncertainty interval | Planning aid only unless independently measured |
| Extrapolated | A different model, topology, accelerator count or unmeasured regime is projected | Hypothesis only; MUST NOT be presented as a procurement guarantee |

An SLO-to-card-count recommendation in v0.1 MUST select among measured
configurations. The Platform MUST NOT invent a card count from model size or
peak bandwidth alone.

---

## 2. Target users and decisions

### 2.1 Primary users

1. **Enterprise procurement and acceptance teams** — define a workload
   contract, compare bids and verify an installed system.
2. **Server OEMs and system integrators** — qualify reference configurations
   and avoid bids that cannot meet the stated SLO.
3. **GPU and accelerator vendors** — publish reproducible design points rather
   than peak-specification claims.
4. **Independent test laboratories and researchers** — reproduce results,
   compare systems and audit benchmark methodology.

### 2.2 Primary decisions

- accept or reject an installed system against a frozen contract;
- choose the minimum-cost tested configuration that passes;
- identify a safe concurrency range rather than a single demo throughput;
- explain whether failure is dominated by queueing, prefill, decode, memory,
  transfer, errors or output-quality gates;
- decide whether deeper, engine-specific instrumentation is worth requesting.

### 2.3 Non-users

The v0.1 product is not a model-training benchmark, a public chatbot preference
arena, a model-quality leaderboard, or a replacement for application-specific
validation.

---

## 3. Product principles

### P1. Contract before measurement

The workload, arrival process, SLO, repetitions, stopping rules and pass/fail
logic MUST be frozen before the measured run begins. Changing them creates a new
run, not a correction to the old result.

### P2. Pareto surface before score

The primary result is a latency-throughput-reliability-quality surface. v0.1
MUST NOT publish one composite score. A score can hide whether a system favors
one fast user or many slow users and is unusually easy to game.

### P3. User-visible truth before internal proxies

Acceptance is based on end-to-end service metrics and quality gates. Cache hit
rate, utilization, bandwidth and expert traffic are explanatory diagnostics,
not substitutes for an SLO.

### P4. Measured fact must be visually distinct from estimate

Every table, chart, API object and report MUST label values as `measured`,
`interpolated`, or `extrapolated`. Default reports MUST exclude extrapolated
values from pass/fail decisions.

### P5. Black-box core, white-box plugins

The minimum test requires only a network endpoint and documented API. Privileged
telemetry and engine hooks MAY enrich the diagnosis but MUST NOT be required for
the baseline acceptance result.

### P6. Reproducibility is an output

Every formal run produces a machine-readable evidence bundle containing the
scenario, environment fingerprint, raw client observations, metric definitions,
software versions, hashes and report. A screenshot is not a benchmark result.

### P7. No silent policy credit

The report MUST distinguish gains due to batching, request deduplication,
admission, scheduling, caching, model changes and lossy quality changes where
the available instrumentation permits it. Unsupported attribution MUST be
labelled unknown.

### P8. Local-first and data-minimizing

Prompts and responses stay on the runner by default. Publishing a result MUST
not implicitly upload request content. Aggregate publication and raw evidence
retention are separate operator decisions.

---

## 4. Scope

### 4.1 v0.1 MUST include

- an OpenAI-compatible black-box endpoint adapter;
- a versioned scenario and SLO schema;
- closed-loop and open-loop load generation with explicit semantics;
- deterministic workload replay from a local JSONL source;
- configurable concurrency/rate sweeps;
- warm-up, measured and cool-down phases;
- TTFT, inter-token latency, TPOT, end-to-end latency, throughput, goodput,
  error and timeout metrics;
- per-workload-class and aggregate results;
- a discrete search over tested configurations or load points;
- an HTML report and a machine-readable result bundle;
- environment, engine and model fingerprints;
- validators for schema, timing consistency and evidence completeness;
- a local synthetic server or trace fixture for conformance testing;
- optional generic host/GPU telemetry when it is available without engine
  modification;
- import and comparison of evidence bundles produced by another operator.

### 4.2 v0.1 SHOULD include

- request-level correctness hooks supplied by the workload pack;
- bootstrap confidence intervals clustered by request or experimental repeat;
- cold-start and warm-steady-state profiles as separate experiments;
- cost metadata and selection of the least-cost measured passing configuration;
- an MoE reporting plugin implementing the relevant checklist from the paper;
- redacted, aggregate-only publication bundles.

### 4.3 Explicit non-goals for v0.1

- a universal “AI appliance score”;
- a hosted leaderboard accepting unaudited vendor claims;
- prediction of an untested frontier-scale model from small-model traces;
- automatic conversion of theoretical bandwidth into contractual throughput;
- modification of model weights, routing or serving-engine kernels;
- an online expert-cache controller;
- a claim that a given offload mechanism saves a fixed number of accelerators;
- semantic evaluation of arbitrary business tasks without a supplied validator;
- trusted hardware attestation.

---

## 5. Operating modes

### 5.1 Mode A — Black-box acceptance

Required access: endpoint URL, authentication supplied locally, and the model's
request/response contract.

This mode measures the customer-visible system, including server queueing. It
is the normative v0.1 acceptance mode. It MUST work without SSH, root access,
engine patches or GPU telemetry.

### 5.2 Mode B — White-box diagnosis

Optional access: node telemetry, engine metrics or trace hooks.

This mode explains a Mode A result with metrics such as GPU memory, KV-cache
occupancy, host-to-device traffic, batch size, preemption and MoE expert cache
behavior. A Mode B plugin MUST declare its permissions and supported engine
versions. Its absence MUST NOT invalidate a Mode A result.

### 5.3 Mode C — Evidence-backed planning

This mode compares existing evidence bundles and selects among measured
configurations. It MAY interpolate within a declared envelope, with uncertainty,
but MUST NOT turn a paper model into an acceptance certificate.

### 5.4 Mode D — Trace-driven research

The existing event-atomic simulator remains useful for mechanism studies. Its
results MUST be labelled simulated and MUST satisfy the replay, workload,
regime and oracle-reporting contract documented by the paper. Mode D evidence
cannot by itself pass a deployment SLO.

---

## 6. Core domain model

The canonical exchange format is a directory with versioned YAML/JSON documents.
All schemas MUST include `schema_version` and reject unknown major versions.

```text
benchmark/
  scenario.yaml       workload and arrival contract
  slo.yaml            pass/fail thresholds
  sut.yaml            system-under-test declaration
  run.yaml            execution protocol and random seeds
  results/
    observations.jsonl
    summary.json
    telemetry/        optional
  report/
    report.html
  manifest.json       hashes and provenance
```

### 6.1 `scenario.yaml`

Required fields:

```yaml
schema_version: "0.1"
scenario_id: enterprise-rag-mixed-v1
workload_classes:
  - id: rag_interactive
    weight: 0.60
    source:
      kind: local_jsonl
      content_sha256: "..."
    request_adapter: chat_completions
    validator: rag_contract_v1
    input_length_distribution: {source: measured_from_payload}
    requested_output_tokens: {p50: 300, p90: 800, max: 1200}
arrival:
  kind: closed_loop
  active_users: 16
session:
  turns: 1
  think_time_ms: 0
```

Rules:

- workload weights MUST sum to one within a documented tolerance;
- the runner MUST record realized, not only requested, workload proportions;
- payload hashes MUST be recorded without embedding payloads in a public bundle;
- input and requested-output length distributions MUST be reported per class;
- templates, chat formatting and truncation behavior MUST be explicit;
- a workload pack MUST declare its licence and redistribution boundary.

### 6.2 `slo.yaml`

SLOs are evaluated per workload class before any aggregate result.

```yaml
schema_version: "0.1"
targets:
  rag_interactive:
    ttft_ms: {p95_lte: 2000}
    inter_token_ms: {p99_lte: 100}
    end_to_end_ms: {p95_lte: 30000}
    request_success_rate: {gte: 0.995}
    quality_gate: {pass_rate_gte: 0.98}
    goodput_eligibility:
      ttft_ms_lte: 2000
      tpot_ms_lte: 100
      quality_required: true
global:
  run_duration_s: {gte: 900}
  minimum_completed_requests: {gte: 500}
```

The schema MUST support thresholds on distributions rather than only means.
`goodput_eligibility` is a separate per-request contract; a distribution-level
target such as `p95_lte` cannot be applied to one request. A missing required
metric is a failure to establish compliance, not a pass.

### 6.3 `sut.yaml`

The system-under-test declaration MUST cover:

- model identifier, revision and quantization;
- tokenizer and chat-template revision where available;
- serving engine, version/commit and relevant configuration;
- accelerator model, count, memory and power mode;
- CPU, RAM, NUMA layout and operating system;
- PCIe/NVLink or other interconnect topology when disclosed;
- container image digest and driver/runtime versions;
- tensor/pipeline/expert parallelism;
- maximum sequences, batch-token limits and queue/admission settings;
- KV-cache format and capacity where known;
- expert offload/cache configuration where applicable;
- whether speculative decoding, prefix caching, response caching or lossy
  techniques are enabled.

Unknown fields MUST be represented as `unknown`, not silently omitted. A report
MUST list every unknown field that limits comparability.

### 6.4 `run.yaml`

The run contract MUST record:

- open-loop or closed-loop semantics;
- arrival distribution or active-user count;
- workload selection seed and request-order seed;
- warm-up duration and warm-up completion condition;
- measurement duration and minimum completion count;
- client concurrency, connection pooling and retry policy;
- per-request timeout and global abort conditions;
- number of independent repetitions;
- sweep points and their order;
- whether state is reset between points;
- client and server clock assumptions;
- response streaming mode;
- token-accounting authority and tokenizer revision;
- explicit stop and invalidation rules.

---

## 7. Metric contract

### 7.1 Time anchors

For each request the runner records monotonic-clock timestamps:

- `t_scheduled`: intended arrival time under the frozen arrival process;
- `t_submit`: request is handed to the client's HTTP/request subsystem;
- `t_send_start`: network send begins;
- `t_first_byte`: first response byte, when observable;
- `t_first_token`: first complete generated token is received;
- `t_token[i]`: each subsequent token reception;
- `t_complete`: valid response stream completes;
- `t_error`: terminal error or timeout.

The primary endpoint interval begins at `t_submit` and therefore includes
server-side queueing. The runner also reports `t_submit - t_scheduled` as client
schedule lag. Excessive client lag means the load generator did not realize the
declared arrival process and invalidates that load point; it must not be charged
to the system under test or silently omitted. If a report presents a narrower
server-internal latency, it MUST be named separately and MUST NOT replace the
endpoint value.

### 7.2 Required latency metrics

- **TTFT:** `t_first_token - t_submit`.
- **End-to-end latency:** `t_complete - t_submit`.
- **Inter-token latency (ITL):** each `t_token[i] - t_token[i-1]` for `i > 0`.
- **TPOT:** `(t_complete - t_first_token) / (generated_tokens - 1)` when at
  least two generated tokens exist; otherwise undefined.

Undefined values MUST remain undefined. They MUST NOT be silently replaced by
zero or removed from denominators without disclosure.

### 7.3 Required throughput and reliability metrics

- completed requests per second;
- generated output tokens per second;
- input plus output tokens per second, reported separately from output tokens;
- realized active requests and queue depth when observable;
- HTTP/protocol errors by type;
- timeouts, cancellations and malformed streams;
- request success rate;
- workload-validator pass rate;
- **goodput:** output tokens or requests that complete successfully and meet all
  per-request `goodput_eligibility` latency and quality thresholds, divided by
  measured wall-clock time.

Raw throughput MUST NOT include failed or invalid responses as goodput.

### 7.4 Token accounting

The run contract MUST identify the authority used to count input and generated
tokens: a frozen local tokenizer, server-reported usage, or both. If both are
available, their disagreement MUST be reported. Character counts or streaming
chunk counts MUST NOT be labelled tokens. A serving stack that does not expose
token boundaries may still be tested for request latency and success, but token
latency/throughput fields that cannot be established remain unavailable.

### 7.5 Aggregation rules

- quantiles are computed from request-level observations unless the metric is
  explicitly token-level;
- per-class metrics MUST precede any weighted aggregate;
- the report MUST state quantile method and software version;
- confidence intervals MUST cluster observations at the repeat/run level when
  independent repeats exist;
- retry attempts MUST be reported, and successful retries MUST NOT erase the
  original failure;
- censored requests at run end MUST be counted and reported;
- the tool MUST preserve enough raw timing data to recompute all summaries.

### 7.6 Maximum compliant load

For a fixed SUT and scenario, the **maximum measured compliant load** is the
highest tested load point for which:

1. every required class-specific SLO passes;
2. global reliability and quality gates pass;
3. minimum duration and sample-count conditions pass;
4. every required repeat passes, unless the contract pre-registers another
   repeat aggregation rule.

An untested point beyond the maximum passing point is not known to fail. The
runner SHOULD test at least one higher load point to establish an observed
failure boundary.

---

## 8. Experiment protocol

### 8.1 Load semantics

**Closed-loop mode** models a fixed number of users: each user sends the next
request after the previous one completes plus optional think time. It is useful
for interactive concurrency but can conceal overload by reducing offered load
when latency rises.

**Open-loop mode** generates arrivals independently of completions. It is
required for rate-based capacity and overload behavior. The arrival process
MUST be named, for example constant, Poisson, or replayed timestamps.

Reports MUST NOT compare an open-loop result with a closed-loop result as if
they were the same load.

### 8.2 Run phases

Each load point has:

1. **setup:** endpoint health and tokenizer checks;
2. **warm-up:** excluded from primary metrics but preserved separately;
3. **measurement:** fixed by time and minimum completion count;
4. **drain:** submitted requests are completed or censored;
5. **cool-down/reset:** optional, declared in advance.

Cold-start behavior is a separate scenario, not a reason to mix warm-up traffic
into steady-state metrics.

### 8.3 Sweep protocol

The default exploratory sweep MAY adaptively locate a boundary. The final
confirmatory sweep MUST freeze:

- all tested load points;
- their order or randomized-order seed;
- state-reset policy;
- repetitions;
- SLO and stopping rules.

The report MUST distinguish exploratory and confirmatory runs. Only the latter
can generate a formal acceptance result.

### 8.4 Default invalidation conditions

A run is invalid, not failed, when evidence collection itself is broken, for
example:

- client timing or tokenizer accounting is unavailable for a required metric;
- the configured workload mix was not delivered within tolerance;
- the SUT configuration changed during the run;
- telemetry collection caused a declared unacceptable perturbation;
- too few requests completed to meet the frozen evidence floor;
- required raw observations or hashes are missing.

Endpoint errors and timeouts under valid load are benchmark failures, not run
invalidations.

---

## 9. Capacity planning and acceptance logic

### 9.1 Configuration registry

A configuration identity is the hash of normalized SUT, scenario, run-contract
and software-version documents. Results with different identities MUST NOT be
merged silently.

The registry stores discrete tested points:

```text
(model, quantization, engine, engine_config, hardware, scenario, load)
    -> evidence bundle + pass/fail + confidence
```

### 9.2 Selection rule

Given a cost function and SLO, the planner selects the lowest-cost measured
configuration whose confirmatory evidence passes. Cost inputs MUST state
currency, date, source and whether they represent purchase price, rental price
or a declared total-cost model. If several configurations are statistically
indistinguishable, the report SHOULD present all of them rather than manufacture
a ranking.

### 9.3 Conditional envelopes

Capacity and bandwidth formulas MAY be shown as conditional envelopes when all
inputs and assumptions are explicit. The report MUST separate:

- storage/capacity feasibility;
- sustained transfer feasibility;
- compute feasibility;
- measured end-to-end compliance.

Crossing a memory-capacity boundary is not proof of throughput. Reducing bytes
is not proof of reducing an integer accelerator count.

### 9.4 Procurement acceptance report

The report MUST include:

- contract identity and hashes;
- tested configuration and unknown fields;
- pass/fail by workload class and metric;
- maximum measured compliant load;
- first measured non-compliant point, if tested;
- raw throughput and goodput;
- cold and warm results where requested;
- confidence and repetition information;
- invalidated attempts;
- deviations from the frozen contract;
- measured/interpolated/extrapolated labels;
- instructions and command required to verify the evidence bundle.

The default acceptance conclusion is one of:

- `PASS` — all frozen gates satisfied;
- `FAIL` — at least one frozen gate failed in a valid run;
- `INSUFFICIENT_EVIDENCE` — required evidence is missing or the run is invalid.

---

## 10. Workload packs and quality gates

### 10.1 Workload pack interface

A pack contains:

- a manifest, source revision and licence;
- request builder and endpoint adapter;
- locally held or redistributable payload references;
- deterministic selection/split rules;
- workload-class labels;
- output-length policy;
- optional response validator;
- contamination diagnostics;
- a public/private payload boundary.

### 10.2 Workload sources

The Platform supports three source types:

1. **Standard public packs** for comparability.
2. **Customer-local packs** that never leave the customer's environment.
3. **Distribution-only synthetic packs** matching length, turn and arrival
   distributions without claiming semantic equivalence to customer traffic.

Synthetic traffic MUST NOT be labelled a customer workload unless its match has
been independently established.

### 10.3 Quality gates

Performance without valid output is not compliant. v0.1 MUST support:

- schema/JSON validity;
- exact or normalized string checks;
- deterministic tool-call contract checks;
- user-provided local validator commands;
- an explicit `not_evaluated` state.

LLM-as-judge MAY be added later, but its model, prompt, sampling and cost must be
versioned. It MUST NOT be the only validator for a contractual acceptance test
without explicit agreement.

### 10.4 Contamination controls

For generated or templated packs, the pack audit SHOULD report:

- distinct templates, prompt heads and final lines;
- application of the model chat template;
- token positional agreement and unique generated sequences;
- input/output length distributions;
- decode-position stability where routing locality is claimed;
- matched-pair controls where feasible.

These are mandatory for a pack used to claim workload-conditioned MoE behavior.

---

## 11. System architecture

```text
                         +----------------------+
 scenario/slo/sut/run -->| Contract validator   |
                         +----------+-----------+
                                    |
                         +----------v-----------+
                         | Experiment planner   |
                         | sweep + repetitions  |
                         +----------+-----------+
                                    |
              +---------------------+---------------------+
              |                                           |
   +----------v-----------+                    +----------v-----------+
   | Workload/load runner |---- network ----->| System under test    |
   | timing + validation  |                    | OpenAI-compatible API|
   +----------+-----------+                    +----------+-----------+
              |                                           |
              |                               +-----------v----------+
              |                               | Optional telemetry   |
              |                               | and MoE plugins      |
              |                               +-----------+----------+
              +----------------------+--------------------+
                                     |
                          +----------v-----------+
                          | Evidence writer      |
                          | raw + hashes         |
                          +----------+-----------+
                                     |
                          +----------v-----------+
                          | Metrics and report   |
                          | acceptance + Pareto  |
                          +----------------------+
```

### 11.1 Proposed packages

```text
platform/
  contracts/       schemas, normalization and validation
  workloads/       pack interface and local loaders
  adapters/        OpenAI-compatible and future endpoint adapters
  loadgen/         open-loop and closed-loop scheduling
  observations/    timestamped request/token records
  telemetry/       optional host, GPU and engine collectors
  metrics/         definitions, quantiles, CIs and SLO evaluation
  planner/         sweeps and measured-configuration selection
  evidence/        manifests, hashes, redaction and verification
  report/          JSON and HTML rendering
  cli/             stable command-line interface
```

### 11.2 Initial CLI contract

```bash
# Validate without sending traffic
moe-eval validate benchmark/

# Exploratory boundary search; cannot issue a formal PASS
moe-eval explore benchmark/ --endpoint http://sut.example/v1

# Frozen confirmatory run
moe-eval run benchmark/ --endpoint http://sut.example/v1 \
  --output runs/2026-08-11-a

# Verify hashes and recompute summaries
moe-eval verify runs/2026-08-11-a

# Compare measured configurations
moe-eval compare runs/* --slo benchmark/slo.yaml

# Render a self-contained acceptance report
moe-eval report runs/2026-08-11-a --format html
```

Secrets MUST be supplied through environment variables, OS key stores or
interactive input. They MUST NOT be written into the evidence bundle.

### 11.3 Plugin boundaries

Plugins MUST communicate through versioned data contracts. A serving-engine
plugin MUST NOT alter primary black-box observations. Telemetry is joined by
timestamps and run IDs, and the report must tolerate missing telemetry.

---

## 12. MoE diagnostic extension

MoE diagnostics are optional explanatory evidence. A conforming plugin SHOULD
report, when the engine exposes the data:

- prefill and decode separately;
- active batch-size distribution;
- per-step/per-layer distinct expert-union distribution;
- per-layer expert-cache capacity;
- event-specific `union / capacity`, its mean and fraction above one;
- cache scope and remainder allocation;
- logical assignments, distinct transfers and transferred bytes;
- whether cross-request deduplication is credited;
- service discipline, admission, rotation and preemption;
- static-pin fit split, quota rule and initial-load accounting;
- expert H2D bytes per output token and per scheduler step;
- mean, p95, p99 and maximum transfer bursts;
- forced-admission oracle decomposition only in trace-driven research mode.

The plugin MUST name its transfer accounting unit. If the engine executes one
fused transfer per distinct expert in a `(step, layer)` event, a simulator used
for comparison MUST defer retention decisions to that event boundary.

MoE metrics MUST NOT be compared across models solely at equal batch size. The
report must place each point in its operating regime and list remaining model
differences. `union / capacity` is required context, not a sufficient statistic.

---

## 13. Evidence, privacy and security

### 13.1 Evidence bundle

`manifest.json` MUST contain:

- schema and tool versions;
- UTC creation times;
- hashes of all included files;
- normalized contract hashes;
- command line with secrets removed;
- code commit and dirty-tree status;
- environment fingerprint;
- excluded/private artifact declarations;
- deviations and invalidations;
- optional signer identity and signature.

### 13.2 Publication profiles

The evidence writer supports:

- `private-full`: request and response records retained locally;
- `redacted`: payload removed, timing and salted opaque request IDs retained;
- `aggregate-public`: only contracts, summaries, environment and hashes;
- `custom`: explicit field-level policy, marked non-standard.

The default is `private-full` locally plus a separately generated
`aggregate-public` bundle. Nothing is uploaded automatically.

### 13.3 Threat model

v0.1 addresses accidental disclosure and casual result manipulation through
schemas, hashes and reproducible computation. It does not prove that a vendor
ran the declared hardware or did not modify the server after the run.

Mitigations SHOULD include:

- independent or customer-operated runner;
- randomized request order and undisclosed held-out payloads;
- server identity and configuration capture;
- signed manifests;
- append-only public release records;
- paired repeat runs by buyer and vendor where practical.

Hardware-backed remote attestation is deferred.

### 13.4 Licensing

Code may use the repository's Apache-2.0 licence. Workload payloads and derived
artifacts retain their own terms. Every pack MUST ship a machine-readable
attribution and redistribution decision. An unclear licence results in a
builder-plus-hash release, not payload mirroring.

---

## 14. Anti-gaming and comparability rules

1. Report the full load curve, not only the best point.
2. Freeze prompts and selection rules before confirmatory execution.
3. Preserve failed, timed-out and censored requests.
4. Report enabled caches, speculative decoding and request deduplication.
5. Run quality gates on the same responses used for performance metrics.
6. Separate cold and warm states.
7. Report client bottlenecks and validate that the load generator has spare
   capacity.
8. Report per-class results so a dominant easy class cannot hide another class.
9. Use at least one held-out or buyer-controlled pack for formal procurement
   acceptance where feasible.
10. Do not compare results produced under different arrival semantics without
    an explicit normalization argument.
11. Do not rank statistically indistinguishable configurations.
12. Preserve the exact evidence needed to recompute every published number.

The future public registry SHOULD show methodology-compliance badges and
evidence completeness before it considers a composite score.

---

## 15. MVP acceptance criteria

The v0.1 implementation is complete only when all of the following pass.

### AC1. Contract validation

- Valid example contracts are accepted.
- Unknown major schema versions, invalid workload weights and incomplete SLOs
  are rejected with actionable errors.
- Normalization produces stable hashes independent of YAML key order.

### AC2. Timing correctness

- A deterministic synthetic streaming server with injected queue, TTFT and
  token delays reproduces expected metrics within frozen tolerances.
- Single-token responses yield undefined TPOT without crashing or becoming
  zero.
- Injected client schedule lag is detected separately from endpoint TTFT.
- Retries, timeouts and censored requests remain visible.

### AC3. Load semantics

- Closed-loop mode maintains the configured active-user count when possible.
- Open-loop mode reproduces the configured arrival schedule independently of
  response latency until an explicit client-saturation limit is reached.
- Client saturation is detected and invalidates capacity claims above it.

### AC4. SLO evaluation

- Class-specific gates are evaluated before global aggregation.
- The known boundary of a synthetic SUT is found by a confirmatory sweep.
- `PASS`, `FAIL` and `INSUFFICIENT_EVIDENCE` are exercised by tests.

### AC5. Evidence reproducibility

- `verify` detects any modified evidence file.
- Recomputed summaries match stored summaries byte-for-byte or within a
  documented floating-point tolerance.
- Secrets and payloads are absent from `aggregate-public` fixtures.

### AC6. Report integrity

- Every plotted value can be traced to a result field.
- Measured and estimated values use visibly different styling.
- The report lists unknown SUT fields, deviations and invalidated runs.
- No composite score is emitted.

### AC7. Cross-platform minimum

- The black-box runner and verifier pass on Linux x86-64 and macOS arm64.
- A report bundle produced on one platform verifies on the other.

### AC8. Existing research compatibility

- The event-atomic simulator's existing tests remain green.
- A Mode D import can render its result as simulated evidence without being
  eligible for a Mode A acceptance `PASS`.

---

## 16. Delivery milestones

### M0 — Specification and audit

- independent audit of this document;
- resolve blocking ambiguities;
- freeze v0.1 schemas and acceptance criteria.

Exit: reviewed specification with numbered audit dispositions.

### M1 — Reproducible black-box kernel

- contracts, OpenAI-compatible adapter, deterministic test server;
- closed/open load generators;
- raw observations and required metrics;
- local CLI and evidence hashing.

Exit: AC1–AC3 and core AC5 tests pass.

### M2 — Acceptance reports

- SLO evaluator, load sweep, class-aware goodput;
- HTML report and comparison CLI;
- invalidation/deviation workflow.

Exit: AC4 and AC6 pass on synthetic overload fixtures.

### M3 — Real-system calibration

- run against at least two different serving stacks or configurations;
- measure client overhead and repeatability;
- publish a redacted evidence example.

Exit: one independently reproducible end-to-end report; no procurement claim
until the target hardware is actually measured.

### M4 — MoE diagnostics

- first engine plugin;
- union/capacity and transfer accounting;
- integration of the paper's reporting checklist.

Exit: plugin output reconciles with black-box token counts and a hand-checkable
trace.

### M5 — Evidence registry and planning UI

- signed/hashed bundle index;
- measured-configuration comparison;
- optional web interface;
- governance for public benchmark submissions.

Exit: public registry policy, moderation process and anti-gaming review. A
single score remains a separate decision.

---

## 17. Risks and mitigations

| Risk | Consequence | Mitigation / product rule |
|---|---|---|
| No target hardware data | Planner cannot honestly recommend card count | Start with runner and evidence format; select only among measured points |
| Vendor benchmark gaming | Misleading public comparison | Full curves, held-out packs, quality gates, independent runner, evidence badges |
| Client becomes bottleneck | False server capacity ceiling | Synthetic calibration, client utilization checks, distributed loadgen later |
| Workload mismatch | Passing benchmark fails production | Customer-local packs, per-class distributions, explicit similarity limits |
| Prompt/data leakage | Compliance and trust failure | Local-first execution, separate aggregate publication, redaction tests |
| Metric-definition drift | Results become incomparable | Versioned schemas and normative definitions |
| Engine-specific coupling | High maintenance cost | Black-box core and isolated plugins |
| One score hides trade-offs | Procurement distortion | Pareto/SLO reports first; no v0.1 score |
| Model output quality degrades | Speed result is invalid | Same-response quality gate and explicit `not_evaluated` |
| Sparse evidence encourages extrapolation | Unsupported commercial promises | Strong measured/interpolated/extrapolated labels |
| Public packs become overfit | Inflated leaderboard result | Buyer-held packs and pack-version rotation |
| Telemetry changes performance | Biased diagnosis | Measure overhead and allow black-box-only acceptance |

---

## 18. Governance and release policy

- Semantic versioning applies independently to tool code, schemas, workload
  packs and metric contracts.
- A major metric/schema change creates a new comparability domain.
- Frozen evidence bundles are immutable; corrections create a superseding
  bundle that links to the original.
- Public benchmark submissions MUST disclose conflicts of interest and who
  operated the runner.
- Vendor-contributed adapters require conformance tests and cannot change core
  metric definitions.
- A public leaderboard, if created, requires a written moderation, dispute and
  result-withdrawal policy.
- The project SHOULD maintain a public decision log for changes that affect
  comparability.

---

## 19. Executor–auditor workflow

This project separates implementation from result adjudication.

1. The executor implements against frozen acceptance criteria.
2. The auditor reviews schemas, metric definitions, threat model and test
   coverage before confirmatory results exist.
3. Any requested change is recorded as accepted, rejected or deferred with a
   reason.
4. Once a confirmatory experiment starts, its SLO, workload, seeds, sweep and
   pass rule are immutable.
5. The executor may fix implementation bugs, but the affected result is
   invalidated and rerun from the frozen input.
6. The auditor independently recomputes a sample of report values from raw
   observations and verifies hashes.
7. Neither role may promote an interpolated or simulated value to a measured
   acceptance result.

---

## 20. Questions for the v0.1 audit

The independent audit should explicitly answer:

1. Is the black-box acceptance boundary sufficient to prevent engine-specific
   proxies from becoming pass/fail metrics?
2. Are TTFT, ITL, TPOT, goodput, retry and censoring definitions unambiguous?
3. Are open-loop and closed-loop semantics separated strongly enough?
4. Can the maximum-compliant-load rule be gamed by sparse sweep points or repeat
   selection?
5. Is `INSUFFICIENT_EVIDENCE` used wherever missing data would otherwise create
   a false pass?
6. Does the measured/interpolated/extrapolated distinction prevent unsupported
   SLO-to-card-count claims?
7. Are the workload licensing, quality and contamination requirements adequate?
8. Does the evidence bundle expose enough information to reproduce results
   without exposing customer payloads?
9. Are the anti-gaming controls realistic for procurement and vendor-operated
   tests?
10. Which MVP requirements are unnecessarily broad and should be deferred?
11. Which critical acceptance failure mode is absent?
12. Are any requirements based on paper-only evidence being incorrectly treated
    as deployment facts?

---

## 21. Frozen product statement for v0.1

The v0.1 product claim is limited to:

> Given a versioned workload contract, SLO and system configuration, the
> Platform can execute a reproducible black-box load test, determine whether
> each **measured** load point satisfies the contract, identify the highest
> measured compliant point, and produce a verifiable evidence bundle and
> acceptance report. Optional telemetry can explain the result but cannot
> replace it.

It does **not** claim to predict unmeasured hardware, save a fixed number of
accelerators, improve the serving engine, or provide a universal model score.
