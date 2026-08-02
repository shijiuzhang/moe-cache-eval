# §7 The Offline-Optimal Gap and Its Decomposition

*Draft v2 — 2026-08-02.*

> **Claim.** With all three axes controlled, a large gap to the offline optimum
> remains and is stable across workload composition. Decomposing it shows that
> 84.3–96.6% derives from knowing which resident block is used furthest in the
> future, a quantity for which the natural online estimator not only fails to
> help but performs worse than the baseline it replaces. A large offline-optimal
> gap is therefore not, on its own, evidence of an online opportunity.

## 7.1 The gap is large and stable

**Table 12.** Recoverable gap on the principal conditions.
*(128-expert model, per-layer scope, ρ = 40%, event-atomic; best causal chosen
from LRU, LFU, LFRU, Least-Stale.)*

| condition | best causal | Belady | gap |
|---|---:|---:|---:|
| held-out, B = 8 | 18.01% (LFRU) | 9.93% | 44.85% |
| held-out, B = 2 | 12.84% (LFRU) | 6.37% | 50.42% |
| calibration, B = 8 | 18.76% (LFRU) | 10.35% | 44.90% |
| fixed-template arm, B = 8 | 21.99% (LFRU) | 12.02% | 45.33% |

The gap does not depend on the contamination of §5: the fixed-template arm,
whose absolute miss fraction is 22% higher, shows the same gap to within half a
percentage point. Nor is it an artifact of a particular workload mixture.
Holding ρ = 40%, B = 8 and the replay semantics fixed, we constructed thirteen
streams — seven size-matched mixtures drawn from disjoint request pools and six
homogeneous single-archetype streams — and measured the gap on each.

**Table 13.** Gap invariance across workload composition. *(13 deterministically
frozen conditions, ρ = 40%, B = 8, per-layer scope. The conditions comprise six
matched mixtures, one non-matched mixture, and six non-matched pure streams.)*

| | gap |
|---|---:|
| minimum | 44.18% |
| maximum | 45.93% |
| mean | 45.09% |

The best causal policy is LFRU in twelve of thirteen conditions and LFU in the
homogeneous office/legal stream. **This range applies to ρ = 40%, B = 8 only.**
It must not be pooled with the B = 2 condition of Table 12 or with the residency
sweep of §6.3, whose gaps span 1.95%–44.78%; those are different operating
points and combining them would misrepresent the variability.

Across the four principal conditions, varying the tie-breaking seed moves the
gap by order 10⁻⁵. We report this as implementation stability, not as a
population confidence interval: it bounds the simulator's nondeterminism, not
the sampling variability of the underlying traffic.

## 7.2 What the offline optimum's advantage consists of

Belady's advantage over a causal policy has two distinguishable sources.

*Bypass admission.* On a miss, the optimum may decline to cache the incoming
block at all, if that block's next use is farther away than that of every
resident candidate. This has familiar causal approximations in storage caching,
including admission filters and reuse prediction, but the oracle share measured
below is not thereby guaranteed to be recoverable.

*Future-victim selection.* When the optimum does admit, it evicts the resident
block whose next use is farthest away. This asks for a *ranking* of all resident
blocks by next-use distance, a substantially harder estimation problem.

Both use future information; they differ in how tractable their online analogues
are. To separate them we run a third variant, `Belady-forced-admit`, which
retains furthest-next-use eviction but is required to admit every miss. It is
not a deployable policy — it still consults the future — but it isolates the
contribution of the admission decision. Writing `m_c`, `m_B`, `m_F` for the miss
fractions of the best causal policy, Belady, and forced-admit Belady:

> `admission share      = (m_F − m_B) / (m_c − m_B)`
> `future-victim share  = (m_c − m_F) / (m_c − m_B)`

**Table 14.** Decomposition of the recoverable gap. *(128-expert model,
per-layer scope, ρ = 40%, held-out split; discovery values in parentheses.)*

| condition | total gap | admission share | future-victim share |
|---|---:|---:|---:|
| B = 8 | 44.85% | 15.69% (16.33%) | **84.31%** |
| B = 2 | 50.42% | 3.40% (3.37%) | **96.60%** |

![**Figure 4. Most of the offline-optimal gap is future-victim knowledge in
the two held-out operating points.** Shares use event-atomic replay and the
forced-admission decomposition; neither component is thereby guaranteed to be
causally recoverable.](figures/figure4_gap_decomposition.pdf){#fig:gap-decomposition width=72%}

The component with familiar online analogues is the minority in both
conditions, and it shrinks as concurrency falls. At B = 2 — the operating point
whose mean regime ratio `r_bar` is closest to the frontier-scale reference frame of
§6.4 — 96.6% of the gap rests on ranking resident blocks by future distance.

## 7.3 Can the dominant component be estimated online?

The decomposition locates the gap; it does not establish that the located
quantity is unpredictable. We tested that directly by replacing the oracle's
input with a prediction and leaving everything else unchanged.

We train a next-use-distance predictor on features available at the moment of
each access: log recency, a first-observation indicator, log frequency, the log
of the previous inter-access gap, the gate mass of the access, the log of the
number of concurrent requests routing to that block in the same event, the layer
index, and a popularity rate. The last three are not used by any of our causal
baselines, so the predictor has strictly more information than LFRU. It is
fitted on one trace and evaluated on a disjoint one, and its output is
substituted for the true next-use array in the *same* eviction and admission
machinery, yielding an algorithmically causal candidate. We do not measure its
inference cost or establish that it meets a production scheduling budget.

**Table 15.** Predicted-next-use policy against the baselines it replaces.
*(128-expert model, fitted on calibration split, evaluated on held-out split,
per-layer scope, $\rho$ = 40%, B = 8.)*

| | effective miss fraction |
|---|---:|
| LFU | 19.14% |
| **LFRU (best causal)** | **18.01%** |
| **predicted next-use** | **18.93%** |
| Belady | 9.93% |
| **fraction of the gap recovered** | **$-11.39$%** |

The predictor is informative as a regressor — its transfer $R^2$ on log next-use
distance is 0.237 — and still makes the policy worse than the baseline it was
intended to improve. Regression accuracy over all accesses is, however, the
wrong measure: eviction needs a correct *ordering* among the blocks that are
resident at the moment of decision. We therefore instrumented the policy's
eviction decisions directly.

**Table 16.** Victim-ranking quality at eviction decision points, tie-aware.
*(Same configuration; 1,708,374 eviction decisions, 46,172 sampled every 37th
decision; mean candidate set 51.2 blocks; mean optimal-victim set 1.24 blocks;
95% CIs by cluster bootstrap over 3,055 scheduler steps.)*

| victim chosen by | in the optimal-victim set | distance regret |
|---|---:|---:|
| random candidate | 2.42% [2.28, 2.56] | 0.00530 |
| **predicted next use** | **3.39% [3.22, 3.57]** | 0.00519 |
| LRU | 20.64% [20.20, 21.07] | 0.00315 |
| LFRU | **22.11% [21.68, 22.56]** | 0.00301 |

| rank correlation, predicted vs. true next use | Spearman |
|---|---:|
| all resident candidates (average ranks for ties) | $-0.207$ [$-0.210$, $-0.204$] |
| excluding candidates never used again | $-0.206$ [$-0.209$, $-0.203$] |

Because the optimal victim need not be unique, we score a choice as correct if
it attains the maximum true next-use key, not if it equals a particular
tie-broken identifier; Spearman uses average ranks. Ties are in fact rare here —
the mean optimal set holds 1.24 blocks and on average 0.07 candidates are never
used again — so neither convention drives the result.

Three readings agree. The predicted ordering is *anti-correlated* with the truth,
and this survives both tie-aware ranking and dropping never-again candidates. The
predictor selects an optimal victim 3.39% of the time, barely above the 2.42%
obtained by choosing a resident block uniformly at random, and roughly six times
less often than LRU or LFRU at the identical cache state. Its distance regret is
statistically close to random and about 70% worse than either causal baseline.
The predictor therefore supplies no usable ordering signal where the decision is
taken, which is what the end-to-end result of Table 15 reflects; because the same
predictions also drive bypass admission, errors compound, as a block whose next
use is over-estimated is refused admission and then immediately required.

A positive global $R^2$ and a negative conditional rank correlation can coexist.
Selection induced by the policy is one possible explanation — the resident set is
not a random sample of blocks, since survivors are those the predictor scored as
soon to be reused — but we have not isolated this experimentally, and we offer it
as a hypothesis rather than a finding.

## 7.4 What this establishes, and what it does not

We separate three claims and do not permit inference between them.

| | claim | status |
|---|---|---|
| 1 | The full gap is the offline bound for residency policies on a fixed access sequence | definitional |
| 2 | Bypass admission contributes 3.4–15.7%; future-victim selection contributes 84.3–96.6% | measured, stable across splits |
| 3 | The causal approximation of §7.3 fails to recover the gap | specific to these features, this predictor, this model, this workload, this operating point |

Claim 3 does not imply that future-victim distance is unpredictable in
principle, and we make no such claim. A predictor with materially higher
transfer accuracy, or one using features our traces do not contain, could change
the result.

It is also worth separating our negative result from a body of work that is
sometimes read as adjacent. Expert *prefetching* predicts **which experts a
future step will route to**; our predictor estimates **how long a cached block
will remain unused**. These are different targets with different horizons and
different error costs, and a positive result on the former is not evidence
against the negative result here [@fang2025fate; @du2024sidamoe;
@gavhane2025moebeyond; @zhu2026dali].

What we do claim is narrower and, we believe, portable:

> **In our evaluated settings a large offline-optimal gap substantially
> overstates the gains recovered by representative lightweight causal
> mechanisms.**

The practical implication is a reporting requirement rather than a design
conclusion. A gap reported without decomposition invites the reader to treat it
as available headroom. We recommend that any work motivating a cache controller
by an offline-optimal gap also report the forced-admission decomposition, so
that the share of the gap resting on future-victim knowledge is visible.

The gap itself is regime-dependent (§6), so these values are not properties of
MoE routing in general; the predictor is one model class and no architecture
search was performed (§11).

