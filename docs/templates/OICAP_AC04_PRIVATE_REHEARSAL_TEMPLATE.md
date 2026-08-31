# OICAP V02-AC04 private procurement rehearsal record

> **PRIVATE — DO NOT POPULATE OR COMMIT THIS FILE IN THE PUBLIC REPOSITORY.**
>
> Copy this blank template to `private/oicap-ac04/` or another buyer-approved
> private location. Apply the buyer's retention, access-control and deletion rules.
> The public repository receives only the separately reviewed structural summary.

## 1. Authorization and participants

- rehearsal identifier:
- authorization owner and date:
- source case: real / de-identified real
- procurement representative role:
- business owner role:
- infrastructure/operations role:
- security/compliance role:
- OICAP facilitator role:
- authorized confidentiality reviewer role:
- private storage location and retention rule:

Do not proceed without a procurement participant able to explain the tender and
acceptance workflow. A technical team guessing what procurement meant does not pass
V02-AC04.

## 2. Source-material inventory

Record private source locations, owners and dates. Do not copy source text into the
public summary.

| Source artifact | Owner | Available? | Used for which decision? | Gap |
|---|---|---:|---|---|
| Tender/SLA requirement | | | | |
| Model and deployment specification | | | | |
| Workload or usage estimate | | | | |
| Supplier response/equipment list | | | | |
| Acceptance/retest clause | | | | |
| Security/network constraints | | | | |
| Site/time/resource plan | | | | |

## 3. Ambiguous business phrases

Preserve the original phrase only in this private record. Resolve it to typed
semantics; do not silently choose the most convenient interpretation.

| Original phrase | Plausible meanings | Procurement intent | Typed resolution | Unresolved consequence |
|---|---|---|---|---|
| e.g. “20 TPS” | aggregate output TPS / per-session TPS / visible-token goodput | | | |
| e.g. “500 concurrent users” | active requests / sessions with think time / admitted users | | | |
| e.g. “response within 2 seconds” | TTFT / complete response / p50 / p95 / maximum | | | |

## 4. SLA-to-pack intake

For every gate record population, class, statistic, comparator, threshold,
duration/sample sufficiency, quality eligibility and evidence authority.

| Gate | Population/class | Statistic/comparator/threshold | Minimum evidence | Quality eligibility | Authority | Supplyable before tender? |
|---|---|---|---|---|---|---:|
| TTFT | | | | | | |
| End-to-end latency | | | | | | |
| Aggregate output-token throughput | | | | | | |
| Per-session generation rate | | | | | | |
| Success rate | | | | | | |
| Quality | | | | | | |

Record bare or ambiguous metrics that could not be frozen:

- 

## 5. Workload profile and quality evidence

- intended business classes and weights:
- input-length distribution or bounded alternatives:
- output-length distribution or bounded alternatives:
- session/think-time semantics:
- streaming requirement:
- warm/cold/reset expectations:
- public, buyer-local or distribution-matched pack source:
- private prompt/reference handling:
- quality validator, runtime/dependency lock and reference-manifest needs:
- fields procurement could not supply:
- safe fallback: refuse freeze / explicit bounded choice / acknowledged information gap:

## 6. Deployment catalogue walkthrough

Every v0.2 catalogue key must appear exactly once. `not_required` is an explicit
decision, not the result of silence.

| Catalogue key | State (`required`/`allowed_set`/`not_required`/`informational`) | Constraint | Who can supply? | On-site evidence | Gap or warning |
|---|---|---|---|---|---|
| model_identity | | | | | |
| tokenizer_and_chat_template | | | | | |
| quantization | | | | | |
| serving_engine | | | | | |
| container_and_runtime | | | | | |
| launch_configuration | | | | | |
| endpoint_boundary | | | | | |
| external_dependencies | | | | | |
| accelerator_topology | | | | | |
| host_platform | | | | | |
| parallelism | | | | | |
| memory_and_offload | | | | | |
| decoding_acceleration | | | | | |
| batching_scheduling_admission | | | | | |

Physical-memory consistency prerequisites are `model_identity`, `quantization`,
`serving_engine`, `accelerator_topology`, `parallelism`, and
`memory_and_offload`. If any is not bounded, record
`UNAVAILABLE_BY_CONTRACT` and the assurance lost; never turn it into PASS.

## 7. Typed but doubtful achievability

OICAP may warn that a requirement appears risky; this rehearsal must not pretend to
predict unmeasured performance.

| Requirement | Why it may be physically doubtful | Evidence available before tender | Authoring warning | Freeze decision and owner |
|---|---|---|---|---|
| | | | | |

## 8. Test-site and client plan

- planned maximum load:
- proposed client topology:
- pre-departure preflight owner/date:
- required CPU, memory, descriptors, storage and network:
- on-site path and frozen SUT boundary:
- calibration-responder placement and buyer-side launcher:
- credential/access prerequisites:
- whether a coordinated multi-client run is required:
- failure mode if the client cannot sustain load:

## 9. Wall-clock rehearsal

Derive time from the frozen SLA boundary and protocol—not from hoped-for SUT
performance. Name every margin and cap.

| Phase | Minimum | Expected | Upper bound/hard cap | Derivation/source |
|---|---:|---:|---:|---|
| Setup and identity evidence | | | | |
| On-site same-path calibration | | | | |
| Warm-up/reset/cold-start work | | | | |
| Load points and repeats | | | | |
| Quality evaluation | | | | |
| Packaging/upload/verification | | | | |
| Reserve | | | | |
| Total | | | | |

- fits the authorized site window: yes / no
- coverage profile changes considered before freeze:
- steps that site staff might be tempted to skip, and prevention:

## 10. Disputes and technical transitions

OICAP records technical evidence and transitions; the commercial consequence stays
in the contract.

| Likely dispute | Evidence needed | Technical state/reason code | Retest allowed? | Frozen mutable paths | Commercial owner (not OICAP) |
|---|---|---|---:|---|---|
| Client did not apply load | | | | | |
| Service gate missed | | | | | |
| Deployment differs from contract | | | | | |
| Evidence is insufficient | | | | | |
| Route/config changed after calibration | | | | | |
| Quality validator identity mismatch | | | | | |

## 11. Findings and schema decisions

| Finding | Field/process affected | Schema change proposed? | Decision | Owner |
|---|---|---:|---|---|
| | | | | |

- fields procurement could supply:
- fields procurement could not supply:
- terms resolved:
- unresolved blockers:
- estimated execution window:
- schema freeze recommendation: proceed / revise / do not freeze

## 12. Private sign-off

- procurement participant confirms workflow was represented accurately:
- technical participant confirms deployment/evidence assumptions:
- confidentiality reviewer confirms source record remains private:
- date:

