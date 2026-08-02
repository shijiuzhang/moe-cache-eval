# §4 Axis I — Replay Semantics

*Draft v2 — 2026-08-02.*

> **Claim.** Under the fused-event traffic contract of §2, replaying an event as
> individual accesses permits eviction and artificial refetch of an expert that
> was resident at event start and is still required later in the same event.
> The resulting error is not uniform noise: it penalizes recency-based policies
> by roughly 27–29% while leaving frequency-based, offline, and static policies
> within 4%, and it inverts the policy ranking.

## 4.1 The mechanism

Under sequential replay, early misses may be admitted before all start-resident
members of the event have been served. If an early admission evicts a resident
expert that appears later in the flattened order, that later access is counted
as a miss even though the fused-event contract would have counted it as a hit.
Evicting an already-served expert does not create a current-event miss; it can,
however, bias the event's final retained set and therefore future events.

A recency-based policy is especially sensitive because the arbitrary order
inside the event immediately changes its key and its victims. Frequency-based
policies are less sensitive when their counters are dominated by prior events.
The offline optimum uses future position, and a static pinned set never evicts.
This difference in policy sensitivity, rather than a uniform counting offset,
is the mechanism tested below.

Expert identifiers make this worse in a specific way. If the flattened order is
the natural one — ascending expert index — then the surviving residents are
systematically the highest-indexed experts of each event, and expert numbering,
an arbitrary artifact of the checkpoint, enters the retention decision.

## 4.2 Randomization is not a fix

A natural repair is to randomize the intra-event order. Table 1 shows that this
addresses only half of the problem.

**Table 1.** Miss ratio under three replay semantics.
*(64-expert model, per-layer scope, ρ = 40%, LRU; range over 5 tie seeds.)*

| replay semantics | miss ratio |
|---|---:|
| sequential, ascending expert index | 99.73% |
| sequential, seeded-random order | 87.15% – 87.19% |
| **event-atomic (Definition 2)** | **56.92% – 57.11%** |

Randomization removes the dependence on expert numbering, which accounts for
the drop from 99.73% to roughly 87%. It does not remove intra-event eviction of
not-yet-consumed residents, which accounts for the remaining 30 percentage
points. Only deferring the retention decision to the event boundary removes
both.

## 4.3 The distortion is selective, and it inverts rankings

Table 2 holds the trace, capacity, concurrency, cache scope and residency
fraction fixed and varies only the replay semantics. It is the data behind
Figure 1.

**Table 2.** Effective miss fraction under sequential and event-atomic replay.
*(128-expert model, held-out split, per-layer scope, ρ = 40%, B = 8. Identical
trace and capacity in both columns.)*

| policy | sequential replay | event-atomic | inflation |
|---|---:|---:|---:|
| LRU | 24.59% | 19.30% | +27.4% |
| LFRU | 23.14% | 18.01% | +28.5% |
| Least-Stale | 24.59% | 19.30% | +27.4% |
| LFU | 19.80% | 19.14% | +3.4% |
| Belady | 10.36% | 9.93% | +4.3% |
| Static-same-trace (diagnostic) | 19.10% | 19.10% | 0.0% |

![**Figure 1. Replay semantics selectively changes policy measurements.**
The trace, capacity, concurrency, scope and residency fraction are identical;
only replay semantics changes. Values are built from the frozen Table 2
artifact.](figures/figure1_replay_semantics.pdf){#fig:replay-semantics width=95%}

Two observations follow.

**The ranking inverts.** Under sequential replay the best causal policy is the
same-trace static diagnostic, which appears to beat LFRU by 4.04 percentage
points. Under event-atomic replay LFRU is best and beats that diagnostic by 5.70%
relative (1.09 percentage points). A study
that concluded "a fixed, offline-chosen residency set outperforms online
replacement" would be an artifact of the replay model alone.

The static row is fitted on the evaluated trace in both columns so that replay
semantics is the only changed variable. It is therefore evidence of
replay-invariance, not evidence for a deployable static policy; §9 evaluates the
discovery-frozen protocol separately.

**The error cannot be treated as a calibration offset.** Because the inflation
ranges from 0.0% to 28.5% across policies, no single correction factor recovers
the correct ordering. Results obtained under sequential replay are not
convertible to event-atomic results after the fact.

Least-Stale coincides exactly with LRU in both columns. This is expected rather
than anomalous: in the absence of prefetching, the two-generation staleness test
degenerates to last-access order. We retain it as a distinct implementation so
that the diagnostic is explicit, and we note that its published advantage is
reported in combination with prefetching and miss handling, which we do not
evaluate here.

## 4.4 Consequence for a downstream conclusion

The semantics changed one of our own conclusions rather than merely its
precision. Under event-atomic replay, the steady-state prefill gap between the
best causal policy and the offline optimum is:

**Table 3.** Recoverable gap, prefill, per-layer scope, mean over 5 tie seeds.

| model | ρ = 20% | ρ = 30% | ρ = 40% |
|---|---:|---:|---:|
| 40-expert | 0.155% | 0.320% | 0.733% |
| 64-expert | 0.601% | 1.516% | 3.169% |

All six points fall far below the 10% threshold we had pre-registered as the
level at which designing a new steady-state prefill eviction rule would be
worthwhile. Under the earlier sequential semantics the same measurements had
appeared to leave several times that much headroom, and a conclusion we had
drawn from them — that admission and pinning were the dominant mechanism — did not survive
the correction and was formally withdrawn.

We report this because it illustrates the failure mode the paper is about. The
sequential result was not obviously wrong when produced: the miss ratios were
plausible, the policies were implemented correctly, and the relative ordering
looked reasonable. The defect was in the replay model, which is exactly the
component least often described.

The magnitude of the inflation is not a constant: it grows with concurrency and
shrinks with residency fraction, converging when events fit inside the quota.
The qualitative property we claim — selectivity by policy family, and therefore
ranking change — follows from the contract argument of §2.2 and does not depend
on the operating point (§11).

