# Reproducible Evaluation of MoE Expert Caching
## Replay Semantics, Workload Contamination, and Operating Regimes

*Draft v2 — 2026-08-02. Numbers cite frozen repository artifacts; the
Related Work reporting audit is in §12 and Appendix A.*

---

## Abstract

Mixture-of-Experts (MoE) models have outgrown the high-bandwidth memory of the
accelerators that serve them, and offloading expert weights to host memory has
become a standard response. This makes expert cache management an attractive
lever: if a smarter policy raised the hit rate, the same model would need less
expert traffic per token. Evaluating that hypothesis is a measurement problem,
and we find the measurement fragile.

Using a trace-driven, event-atomic simulator over three MoE models (40, 64 and
128 experts), we isolate three evaluation axes that change conclusions rather
than shift numbers. *Replay semantics*: under a fused-event traffic contract, an
inconsistent per-access replay inflates recency-based policies by 27–29% while
leaving frequency-based and static policies within 4%, inverting the policy
ranking. *Workload contamination*: probe sets using one instruction template per
category produce verbatim-identical generation prefixes; a matched-pair
rendering intervention moves the measured early-window effect by 19.4–31.9
percentage points and reverses which workloads appear most cache-friendly.
*Operating regimes*: normalized miss fractions do not transfer across models, so
the per-step expert union relative to per-layer capacity must be reported —
though permuting only the temporal order of an otherwise identical event stream
moves the offline-optimal gap from 44.9% to 30.8%, so it is not sufficient.

After correcting all three, a stable gap to the offline optimum remains
(44.2–45.9% across 13 frozen workload compositions). A forced-admission oracle
attributes 84.3–96.6% of it to knowing which resident expert is used furthest in
the future. A causal next-use predictor, used as an eviction rule, recovers $-11.4$% of the
gap; at the decision points it selects an optimal victim 3.4% of the time
against 2.4% for a random resident block and 20.6-22.1% for LRU and LFRU. Our
position is narrow: **in our evaluated settings a large offline-optimal gap
substantially overstates the gains recovered by representative lightweight
causal mechanisms.** On publication we will release the simulator, a diversity-controlled probe
set, the contamination diagnostics and a reporting checklist, subject to the
upstream licences recorded in the artifact matrix.

---

## 1. Introduction

Serving a frontier Mixture-of-Experts model no longer fits the memory it was
designed for. A contemporary large MoE dedicates on the order of 1.3 TiB to
routed expert weights while activating only a small fraction per token, so
recent systems keep a subset of experts resident in device memory and stream
the rest from host memory on demand. Variants appear in open-source prototypes,
research systems, and inference-engine proposals; their execution contracts and
performance targets differ [@shazeer2017sparselygated; @fedus2022switch;
@eliseev2023mixtraloffloading; @xue2025moeinfinity; @tang2024hobbit].

The design also creates an obvious hypothesis. If experts are cached, then a
better cache policy should raise the hit rate, lower host-to-device traffic,
and let the same model run on fewer accelerators. A workload-aware controller —
one that learns which experts a customer's traffic actually touches — would then
be worth building. A substantial body of recent work pursues variants of this
idea through prefetching, learned routing prediction, and specialized
replacement policies [@du2024sidamoe; @fang2025fate; @hoang2026specmd;
@zhu2026dali].

Whether the hypothesis holds is an empirical question, and answering it requires
measuring how much room a policy has: the distance between the best causal
policy and an offline optimum. We set out to measure exactly that. What we found
first was that the measurement itself is unstable in ways that are easy to miss
and that change the answer, not just its precision.

**Three axes.** Within our trace-driven study, we identify three evaluation
choices, each individually plausible and each capable of reversing a
conclusion. Their applicability is not identical: Axis I concerns replay of a
claimed fused-event contract and does not apply retrospectively to a real
end-to-end system whose implementation defines its own transfer semantics
(§12); Axes II and III concern workload construction and operating-regime
reporting more broadly.

*Replay semantics.* Under the fused-event traffic contract studied here, the
experts a scheduling step touches at a layer form one committed execution unit.
A simulator that flattens this unit into individual accesses can evict, part-way
through the event, an expert that was resident at event start and is required
later, then count an artificial refetch. The distortion is not uniform noise.
On Qwen3-30B-A3B at ρ=40% and B=8, sequential replay inflates LRU by 27.4%,
LFRU by 28.5%, and Least-Stale by 27.4%, but LFU by only 3.4%, Belady by 4.3%,
and a same-trace static diagnostic not at all. Because it penalizes exactly one
family of policies, it inverts their ranking: under sequential replay the
same-trace static diagnostic appears to beat every dynamic policy; under
event-atomic replay LFRU beats it by 5.7%. This is a replay-invariance
comparison, not a deployable static baseline (§2.3). In our own earlier
measurements, correcting this semantics moved the
steady-state prefill gap on two models from a range that looked like algorithmic
headroom down to 0.155–3.169%.

*Workload contamination.* Studies of workload-conditioned routing need probe
sets partitioned by task. The natural construction — one instruction template
per category, filled with different payloads — turns out to be hazardous. Under
raw continuation, or within a short decode window, the model reproduces the
shared template before it produces anything task-specific, so concurrent
requests emit verbatim-identical prefixes at identical decode positions. In one
of our own probe categories, 4 of 16 requests generated byte-identical 63-token
outputs. The resulting expert overlap is easily mistaken for semantic locality:
restricting the comparison to request pairs whose generated text barely overlaps
collapses one category's within-class expert Jaccard from 0.229 to 0.092,
against a cross-category baseline of 0.078. We introduce a matched-pair design —
the same source records rendered both with diverse and with fixed templates —
that changes the early-window effect by 19.4–31.9 percentage points. An abrupt
decay aligned with a shared generated prefix is a diagnostic of surface
repetition, though genuine task effects may also vary by response phase.
Correcting the construction reverses the point-estimate ordering; only two of
six corrected category effects replicate clearly across two request draws.

*Operating regimes.* Normalized miss fractions are routinely compared across MoE
models with different expert counts. They should not be. The relevant variable
is the ratio of the per-step, per-layer expert union to the per-layer cache
capacity. As the fraction of events exceeding capacity grows, capacity-forced
traffic increases and policy headroom can collapse — so a small gap can mean
"the capacity floor dominates" rather than "existing policies suffice". Holding the model and the workload fixed and
changing only the cache fraction moves the gap from 7.4% to 33.3%. The ratio is
necessary but not sufficient: permuting only the temporal order of an event
stream, with the event set and the ratio held exactly constant, moves the gap
from 44.9% to 30.8% and changes which causal policy is best.

**What remains after correction.** With all three controlled, a large gap to the
offline optimum persists: 44.2–45.9% across 13 frozen workload compositions at ρ=40%
and B=8, and 50.4% at B=2. The natural reading is that a substantial opportunity
is waiting for a better online policy. We tested that reading directly.

Belady's advantage over a causal policy has two sources: refusing to admit a
block that will not be reused before it would be evicted, and knowing which
resident block is used furthest in the future. Only the first has a clear online
analogue. Replacing the oracle with one that is forced to admit every miss
separates them: bypass admission accounts for 15.7% of the gap at B=8 and 3.4%
at B=2, leaving 84.3% and 96.6% to future-victim knowledge. We then trained a
next-use-distance predictor on causal features available at eviction time —
recency, frequency, gate mass, concurrent routing multiplicity, layer, and
popularity rate — fitted on one trace and evaluated on a disjoint one. It
transfers at R²=0.24 and, substituted for the oracle's input in the same
eviction and admission machinery, recovers −11.4% of the gap: it is worse than
the causal baseline it was meant to improve.

**Position.** We state our claim narrowly. We do not show that expert caching is
a closed problem, that future-victim knowledge is unpredictable in principle, or
that online MoE cache controllers have no future; existing work on expert
*prefetching* predicts a different quantity — which experts will be routed next,
rather than how long a cached block will remain unused — and is not contradicted
by our result. What we show is that in our evaluated settings a large
offline-optimal gap substantially overstates the gains recovered by
representative lightweight causal mechanisms, and that reporting such a gap
without decomposing it invites an unwarranted inference. We accompany this with
three scoped negative results and one invalidated mechanism experiment —
steady-state prefill eviction, warm-cache workload transition, semantic cache
partitioning, and causal affinity batching — each annotated with the model, cache fraction,
concurrency, scheduling discipline, and waiting constraint under which it was
measured, because we found that at least one of these mechanisms fails for a
reason that does not extrapolate.

**Contributions.**

1. We formalize and implement an **event-atomic replay protocol** for the
   fused-event traffic contract used in our trace-driven evaluation, show that
   an inconsistent flattened replay selectively
   penalizes recency-based policies and inverts policy rankings, and provide a
   hand-verifiable reference trace (§2, §4).
2. We introduce a **matched-pair method** for quantifying prompt-template
   contamination in workload-conditioned routing studies, together with
   prompt-side and route-side diagnostics, and release a diversity-controlled
   probe set built to be free of it (§5).
3. We show that **cross-model comparison of MoE cache results requires
   explicitly controlling the operating regime**, give the union-to-capacity
   ratio as a first-order variable that must be reported, and demonstrate by
   ablation that it is necessary but not sufficient (§6).
4. We **decompose the offline-optimal gap** into an online-approximable and a
   future-dependent component and show, for representative causal mechanisms in
   our settings, a large gap between the oracle bound and realizable gains
   (§7, §8).
5. We distill the above into a **reporting checklist** for future MoE cache
   evaluations (§10) and will release, on publication, the simulator, probe set, contamination
   tools, frozen manifests and — where upstream licences permit — routing
   artifacts and pre-registration documents including failed criteria (§13).

**Scope.** All results are trace-driven simulation; we do not measure real
host-to-device transfers, kernel time, or interconnect topology. Our primary
results use a single model, with two smaller models for cross-model checks, and
we evaluate only strictly lossless policies — no expert substitution, pruning,
or reduced-precision fallback. Section 11 states these limits in full. We regard
the checklist in §10, rather than any individual number, as the most portable
result of this work.

**Relation to prior evaluations.** We audited the public reporting of ten
representative papers (§12). Seven are end-to-end systems, so our replay failure
is not applicable to their actual execution; one is trace-driven but does not
report enough detail to reconstruct our fused-event contract and assumes batch
size one; two study architecture or prediction targets. None directly reports
the measured union-to-capacity ratio needed to place its results in §6's regime,
and prompt-template multiplicity is generally not reported. These omissions do
not make the results incorrect. They prevent direct comparison under a common
evaluation contract, which is the motivation for §10's checklist.
