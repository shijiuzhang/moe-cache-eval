# §8 Scoped Negative Results and One Invalidated Design

*Draft v2 — 2026-08-02.*

> **Framing.** §7 shows that the offline-optimal gap is dominated by a component
> whose natural online estimator does not help. This section reports what
> happened when we pursued four mechanisms that do not require estimating that
> component. Three produced scoped negative results; the hard-partition study
> had no power to test its intended mechanism because its dedicated cache was
> smaller than one request's top-k set. We report each with the
> conditions under which it was measured, because at least one fails for a reason
> that does not generalize, and we do not claim mechanism-level closure.

## 8.1 The four attempted mechanisms

Each decision threshold below was frozen, together with the split it would be
evaluated on, before the corresponding measurement was read. The later failure
attribution and the determination that the partition grid was arithmetically
incapable of a fair positive test are post-hoc audits, not confirmatory results.

**Table 17.** Pre-registered criteria and outcomes, with measurement scope.

\begin{landscape}
\scriptsize

| mechanism | model | ρ | concurrency | scheduling | other constraints | criterion | measured | outcome in scope |
|---|---|---:|---|---|---|---|---:|---|
| steady-state prefill eviction / admission | 40- and 64-expert | 20/30/40% | prefill, 128-token blocks | — | strictly lossless | gap ≥ 10% | 0.155–3.169% | not met |
| warm-cache workload transition | 40- and 64-expert | 20/30/40% | prefill, 128-token blocks | directed A→B transitions | windows N = 10/25/50/100 | gap ≥ 10% | 1439/1440 units < 10% | not met |
| semantic category partitioning | 128-expert | 40% | B = 8 | FCFS | equal total capacity; **6 slots < top-`k` = 8** | transfer ↓ ≥ 5% | **+115.9%** | invalid test of mechanism; design floor dominated |
| causal affinity batching | 128-expert | 40% | B = 8, 24 admitted | deadline rotation | W = 4, strictly lossless | transfer ↓ ≥ 10% | 4.76% / 4.55% | not met |

\normalsize
\end{landscape}

The warm-transition experiment covers 1440 units — two models × three residency
fractions × three request-order seeds × twenty directed transitions between five
workload proxies × four post-transition windows. A single unit exceeded the
threshold, at 10.74%, and decayed to 6.83%, 5.03% and 3.95% as the window
widened from 10 to 25, 50 and 100 requests, which is the signature of a
short-lived warm-start transient rather than a sustainable control opportunity.

## 8.2 One invalidated design

The partitioning experiment gave a dedicated per-layer slot budget to each of the
two archetypes §5.7 identifies as genuinely cache-friendly, with the remaining
four sharing a third partition, at exactly equal total capacity. Every allocation
in a seven-point grid lost, and the frozen one increased transfer by 115.9%.

The natural reading — that partitioning destroys cross-category expert sharing —
is largely wrong. Running the *shared* cache at each partition's own slot count
and weighting by each partition's share of logical assignments predicts 37.30%
against a measured 37.99%: **capacity fragmentation alone accounts for 96% of the
degradation.** The cause is arithmetic. Top-`k` is 8, so a single request touches
eight experts per layer, while the best dedicated partition holds six; no point
in the grid could retain even one request's per-step working set. **The
experiment as designed could not have produced a positive result**, and we
present it as an invalidated design and a measurement lesson (§10, item D5)
rather than as a negative result for semantic partitioning. The arithmetic does
not generalize: at the reference scale of §3.2, 358 per-layer slots divided six
ways leave a 2.3–3.7x margin over the per-category per-step union, so the
$-115.9$% figure must not be carried across. Appendix B gives the grid.

## 8.3 Affinity batching: not a prediction problem

The remaining mechanism does not touch residency at all. It changes which
requests are co-scheduled, and therefore changes the event sequence itself — a
degree of freedom that the Belady bound of §7 does not cover, since that bound
is defined on a fixed access sequence.

Up to 24 sessions are admitted and at most `B = 8` are served per step, with a
frozen fairness constraint that an admitted request's inter-service interval
never exceeds `W = 4` steps. Three schedulers share identical arrival,
admission and completion rules and differ only in how they select up to eight
requests from the active set: `fcfs_deadline`; `causal_prev_route`, which uses
only each request's per-layer expert set at its previous executed token and
greedily minimizes the predicted union; and `oracle_current_route`, which runs
the same selection using the true expert sets of the tokens about to execute.
The oracle is a rolling, route-aware bound, not a global optimum, and all
metrics are computed on the complete cache trajectory rather than per step.

**Table 18.** Causal affinity batching against FCFS, held-out split.
*(128-expert model, ρ = 40%, per-layer scope, B = 8, 24 admitted, W = 4.)*

| policy | FCFS | causal | oracle | causal gain | oracle gain | share | Δp99 |
|---|---:|---:|---:|---:|---:|---:|---:|
| LFRU | 23.08% | 21.98% | 21.71% | **4.76%** | 5.92% | **80.43%** | +7.06% |
| static pinned | 19.15% | 18.28% | 17.64% | **4.55%** | 7.90% | 57.65% | +10.08% |

No request starved and the maximum inter-service interval was 4 throughout. The
static-residency arm additionally violated the frozen p99 constraint at 10.08%.

The important number is the second-to-last column. The causal scheduler captures
80.4% of what the route-aware oracle achieves under the same fairness
constraint. **The shortfall is therefore not a weakness of the prediction
signal**; it is that the schedulable headroom under `W = 4` at this concurrency
is itself only 5.9–7.9%. Improving the predictor cannot reach a 10% threshold
that the oracle does not reach either. This distinguishes the result from §7.3,
where the causal estimator was the binding constraint.

The signal itself is real: within a request, the per-layer expert set at step
`t+1` overlaps that at step `t` with mean Jaccard 0.293, against 0.032 for two
independent uniform draws — a ninefold enrichment. It is simply not worth much
once fairness is enforced.

## 8.4 A methodological consequence: single-step order statistics

Before running §8.3 we estimated the headroom the cheap way, by sampling 300
random batch compositions at a fixed step and comparing the best to the mean
union. That estimate was **19.3%**. The full-trajectory measurement under the
same concurrency with `W = 4` yields an oracle headroom of **5.9–7.9%**.

Two effects account for the difference and both are general. The maximum over
300 draws is an order statistic and is biased upward as an estimate of what a
systematic method achieves. More importantly, a per-step measurement ignores
conservation: requests that are deferred because they route poorly with the
current batch must still be served later, and their cost reappears. A per-step
union reduction is therefore an upper bound that can be almost entirely
recovered by the later schedule.

We recommend that scheduling headroom for MoE caching be estimated on complete
trajectories under the intended fairness constraint, and that per-step
best-of-`N` figures not be reported as achievable gains.

## 8.5 What these results do not close

We state the complement explicitly, because the value of a negative result
depends on its boundary.

- **Prefill execution ordering.** §8.1 finds little eviction/admission headroom
  in the measured prefill conditions only. Layer-major versus chunk-major
  prefill scheduling was never measured;
  under an independent uniform-routing approximation the two differ by roughly
  two orders of magnitude in total expert traffic for long contexts, and it
  remains the largest unexamined lever we are aware of.
- **Lossy settings.** All results assume strictly lossless service. Expert
  substitution, pruning, and reduced-precision fallback are excluded by
  construction.
- **Prefetching.** We evaluate residency and scheduling, not prefetch. §7.4
  states why our negative result does not bear on expert prediction for
  prefetching.
- **Frontier scale.** Every mechanism was measured at `r_bar` values reachable
  by models of 40–128 experts. §6.4 shows that the reference frame of §3.2 sits
  at a mean regime those models reach only at low concurrency.
- **Other fairness settings.** §8.3 fixes `W = 4` and 24 admitted sessions;
  relaxing either enlarges the schedulable headroom and was not swept.

## 8.6 Recorded design revision

One parameter in §8.3 was revised before execution. The initial draft admitted
`B x W = 32` sessions; a pre-execution check showed this implies exactly 100%
service load, leaving no discretion for affinity selection to exercise. The
count was reduced to 24, and the revision was recorded together with the
statement that no result had been generated or read, and with an explicit
prohibition on relaxing `W` or reverting the count afterwards. The document is
released unchanged.
