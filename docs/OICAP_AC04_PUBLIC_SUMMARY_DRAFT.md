# OICAP V02-AC04 public structural summary — PUBLIC WORKING DRAFT

> **Not an accepted AC04 evidence artifact.** This de-identified working draft was
> committed before an authorized confidentiality approval was recorded. It is
> already public and is labelled accordingly rather than pretending that the
> publication gate still controls it. Future drafts remain under `private/` until
> approval. This document intentionally omits project, supplier, model, hardware,
> threshold, workload, date, price and organization details.

## Status

- rehearsal basis: de-identified real enterprise acceptance case;
- participant roles represented: procurement acceptance and technical facilitation;
- private source: outside Git under the ignored `private/` tree;
- automated and independent content scans: passed; authorized confidentiality
  approval: pending;
- V02-AC04 result: pending confidentiality and final acceptance review; the buyer UI
  revision has been implemented locally.

## Structural findings

### What procurement could supply

- the intended private-deployment context and buyer/SUT boundary at a business level;
- the model and broad service/hardware commitments named in procurement material;
- the expected maximum use and available onsite acceptance window;
- the evidence actually supplied by the vendor;
- the basis on which the historical acceptance decision was made;
- the principal residual operational concerns and the absence/presence of a defined
  post-failure commercial path.

### What procurement could not reasonably author

- statistical population and percentile semantics for each service gate;
- input/output token distributions and authoritative per-token timing rules;
- a machine-executable quality-validator contract;
- low-level serving configuration across the complete deployment catalogue;
- scan-point selection, calibration controls and runner preflight mechanics.

These are not fields that should be guessed by procurement. They require an OICAP
compiler plus a named technical reviewer, with unresolved translations blocking
contract freeze.

### Historical evidence baseline

The case used a supplier-environment test report, a hardware inventory, subjective UI
interaction and a small informal simultaneous-use exercise. That evidence could not
establish large-load concurrency, sustained stability, latency distributions or the
absence of resource-exhaustion failure on the delivered path. This is a limitation of
the acceptance evidence, not a retrospective claim that the service failed.

### Principal technical disputes exposed

- whether a supplier-environment result transfers to the buyer's delivered system;
- whether the client actually sustained the promised concurrent load;
- whether a service failure is proven OOM or only consistent with resource exhaustion;
- whether listed hardware/configuration is bound to the serving process;
- what may change on retest and what technical state follows a FAIL when the original
  contract contains no predetermined transition.

### On-site evidence availability

| Evidence category | Rehearsal finding | Structural consequence |
|---|---|---|
| Supplier-environment performance report | available | provenance-bearing input only; buyer-site reproduction remains required |
| Hardware inventory | available | inventory alone does not bind equipment to the serving process |
| Runtime/process binding | not established by the historical acceptance evidence | requires an explicit L2 collection plan |
| Buyer-controlled high-load evidence | unavailable historically | concurrency and stability remained unproven at the promised scale |
| OOM attribution evidence | unavailable historically | black-box failure may not be labelled proven OOM |

### Operational envelope

- the buyer could state the available site window;
- setup and execution duration could not be estimated because no technical scan or
  soak plan had yet been derived;
- single- versus multi-client load generation remained a technical translation task;
- sustained stability and client capacity were the principal time risks.

This is a product finding: OICAP must derive and show a plan that fits the site window,
not ask procurement to invent load points or silently compress the protocol onsite.

### Typed but potentially unachievable requirements

No claim of physical achievability could be made because the buyer-facing draft did
not yet contain translated technical gates or a run plan. The revised flow retains
this as a later human warning; it does not pretend to predict supplier capability.

### Schema and process changes required

1. split buyer business intake from expert contract authoring;
2. replace free-text workload foreign keys with controlled references;
3. translate plain-language experience promises into explicit candidate gates, never
   silent defaults;
4. record unresolved translations as blocking tasks assigned to a role;
5. derive candidate load scans and wall-clock plans from frozen intent rather than
   asking procurement to design them;
6. make concurrency and sustained stability first-class acceptance intents;
7. treat vendor reports and inventories as evidence inputs with provenance, not PASS;
8. distinguish observed OOM evidence from black-box symptoms;
9. require a technical retest/mutability policy before freeze while leaving commercial
   consequences to the procurement contract.
10. validate relationships across buyer answers: a declined governing promise cannot
    retain active target fields, and requested coverage that exceeds the appointment
    window must be surfaced before technical compilation rather than silently
    shortened on site.
11. require every retained acceptance input to name its downstream compilation
    obligation; complete latency and quality answers must not disappear from the
    translator's work queue.

## Confidentiality review checklist

- [x] no tender text or distinctive paraphrase;
- [x] no price, budget or purchasing decision;
- [x] no supplier, product, model or hardware identity;
- [x] no private prompt, workload distribution or business data;
- [x] no network, security or access detail;
- [x] no direct personal/project identifier;
- [ ] authorized reviewer confirms no combination of facts reasonably identifies the
  project;
- [x] private source material remains outside the public repository.
