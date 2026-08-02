# §10 Benchmarking Recommendations

*Draft v2 — 2026-08-02.*

Each of the preceding sections identifies an evaluation choice that is rarely
stated and that changes conclusions when it varies. We collect them here as a
reporting checklist. Every item is one we failed to report, or reported
incorrectly, at some point in this work; the section reference gives the
evidence that motivated it. We apply the checklist to ourselves in §13.

The intent is comparability rather than compliance. Most items ask an author to
*state* a choice, not to make a particular one. Two items — A2 and D3 —
are stronger, because the practices they exclude are not alternative modelling
choices but errors.

## 10.1 Group A — Replay and execution model

**Applicability.** Group A applies to trace-driven or otherwise modelled cache
evaluation. For an end-to-end real-system experiment, the implementation itself
defines the transfer unit and retention order; A1 should report that contract,
while A2–A4 may be marked not applicable rather than imposed retroactively.

**A1. State the execution unit.** Is hit/miss classified once per
`(step, layer)` event over the batch-wide expert union, or per individual
expert access? The two are not interchangeable. *(§2.1)*

**A2. State whether retention decisions are deferred to the event boundary.**
If they are not, state explicitly whether a block resident at event start and
required later can be evicted and counted again. Such a replay is inconsistent
with one-transfer-per-distinct-expert fused-event accounting; it may instead
describe a genuinely serialized execution, which should be named as a different
contract. *(§2.2, §4)*

**A3. If replay is sequential, state the intra-event ordering rule.** Ascending
expert index makes checkpoint numbering part of the retention decision;
randomizing it removes that dependence but not the error in A2. *(§4.1–§4.2)*

**A4. Provide a small hand-verifiable trace or equivalent conformance check**, so
that a reader can confirm which semantics an implementation realizes. *(§2.5)*

## 10.2 Group B — Workload construction

**B1. Report the number of distinct instruction templates per workload
category**, together with the number of distinct prompt prefixes and distinct
final lines per category. A single template per category is a risk indicator,
not a defect by itself. *(§5.6)*

**B2. State whether the model's chat template was applied.** Under raw
continuation the model may complete the instruction rather than answer it,
producing shared prefixes across all requests in a category. *(§5.2)*

**B3. Report the number of decode steps recorded** and whether the analysis
window extends beyond the shared-prefix region. Short windows are dominated by
it. *(§5.2)*

**B4. State whether concurrent requests are position-locked** — equal length,
lock-step admission and retirement — since this aligns any shared prefix at
identical scheduling steps and inflates per-step union effects. *(§5.2)*

**B5. Report positional token agreement and the number of unique generated
sequences per category.** *(§5.3)*

**B6. Report within-category expert overlap restricted to request pairs whose
generated text barely overlaps, against a cross-category baseline.** The residual
is the portion of the effect not explained by surface repetition. *(§5.3)*

**B7. Report whether the effect is stable across decode-position bands.** An
effect concentrated in the same band as a shared generated prefix should be
treated as surface repetition until shown otherwise. Position decay without a
shared prefix can be a genuine response-phase effect. *(§5.4)*

**B8. Where feasible, include a matched-pair control** in which the same source
records are rendered under both constructions, which converts the artifact from
an argument into a measurement. *(§5.5)*

## 10.3 Group C — Regime and comparability

**C1. Report the per-step, per-layer expert-union distribution, the per-layer
capacity, event-specific `r(s,l)`, and at least its mean `r_bar` and fraction
above one.** Without these a result cannot be placed; the mean alone is not a
sufficient statistic. *(§6.1, §6.5)*

**C2. State the cache scope** — per-layer or global — and, for per-layer, how the
remainder of the budget is allocated. *(§2.3)*

**C3. State the miss denominator**: expert assignments before or after
intra-event deduplication. *(§2.4)*

**C4. State whether cross-request deduplication is credited to the policy.** It
is obtained by any batching scheduler and is not a policy contribution. *(§2.4)*

**C5. State the service discipline**: continuous batching, rotation of a subset
of admitted sessions, admission and preemption rules, and any fairness bound.
Changing only this, at fixed request set, capacity and mean batch size, moved a
static pinned set from 7.5% worse than LFRU to 17.0% better. *(§9.3)*

**C6. For every static or pinned baseline, state its fit source, split boundary,
quota rule, and whether the initial load is counted** in reported traffic. A
same-trace popularity diagnostic and a discovery-frozen pin list are different
baselines even if both are called "static". *(§2.3–§2.4, §9.1)*

**C7. For cross-model comparison, first align on `r_bar`, not on batch size, and
then report remaining architectural differences.** Aligned on
batch size, three models in this paper span 36.8 percentage points of gap;
aligned on `r_bar`, the same measurements agree to within 1.1–4.6. *(§6.4)*

## 10.4 Group D — Interpreting oracle bounds

**D1. Report absolute transferred bytes per output token alongside any gap**,
together with the bandwidth budget implied by the target service rate. A small
gap is ambiguous between "existing policies suffice" and "no policy is viable",
and only the absolute figure distinguishes them. *(§6.6)*

**D2. When motivating a controller by an offline-optimal gap, report the
forced-admission decomposition**, so that the share of the gap resting on
future-victim ranking is visible rather than implied to be available. *(§7.2)*

**D3. Do not report per-step best-of-`N` batch compositions as achievable
scheduling gains.** Estimate scheduling headroom on complete trajectories under
the intended fairness constraint; the per-step figure in this work overstated
the trajectory figure by a factor of roughly three. *(§8.4)*

**D4. State the scope of every negative result**: model, residency fraction,
concurrency, service discipline, fairness constraint, and whether service is
strictly lossless. One attempted negative result in this paper was invalidated
by its own capacity floor and would be misleading without this scope. *(§8.2,
§8.5)*

Appendix B gives a minimal reporting block, compact enough to include verbatim in
a paper or artifact README, covering the items above that admit a one-line answer.

## 10.6 What the checklist does not cover

The checklist addresses trace-driven evaluation of residency and scheduling. It
says nothing about several things that matter for a deployment claim and that we
did not measure: real host-to-device transfer and its overlap with compute,
interconnect topology and achievable sustained bandwidth, kernel time, memory
contention between expert cache and attention state, and any quality-lossy
mechanism. A study that satisfies every item here has established comparability
with other trace-driven studies, not deployability.

We also expect the list to be incomplete. §9.3 documents a confounder we did not
anticipate and found by accident, after three others had already been
identified; we see no reason to believe it is the last.
