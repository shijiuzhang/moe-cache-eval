# §6 Axis III — Operating Regimes

*Draft v2 — 2026-08-02.*

> **Claim.** Normalized miss fractions do not transfer across MoE models. The
> distribution of the per-step, per-layer expert union relative to cache capacity
> is a first-order variable that must be reported before any cross-model
> comparison is meaningful. Its mean is necessary but not sufficient: holding
> the event-set multiset and mean ratio exactly constant and permuting only temporal order
> moves the offline-optimal gap from 44.9% to 30.8% and changes which causal
> policy is best.

## 6.1 The regime variable

Two quantities determine whether a replacement policy has room to act at all:
how many distinct expert blocks a single event requires, and how many the layer
can hold. Write

> `r(s,l) = |E(s,l)| / c_l`, and `r_bar` is its mean over reported events.

For an event with `r(s,l) < 1`, its working set fits in the quota; misses can
still arise from drift between events and eviction order may matter. For an
event with `r(s,l) > 1`, at least `|E|-c_l` members cannot remain resident after
the event, creating a capacity-forced floor. As the mass of the `r(s,l)`
distribution above one grows, replacement policies have less headroom. This is
a tendency, not a theorem that all policies or all traces converge.

`r_bar` is not a free parameter. It generally rises with concurrency and top-`k`, and
falls with expert count and residency fraction, so two models compared "at the
same batch size" are routinely in different regimes.

## 6.2 Crossing the boundary

Table 9 sweeps concurrency on the 128-expert model at fixed residency,
reporting the measured union, the fraction of events that exceed the layer
quota, and the resulting gap.

**Table 9.** Regime and gap versus concurrency.
*(128-expert model, per-layer scope, ρ = 40%, `c_l` ≈ 51.2, event-atomic.)*

| B | union / layer-step | p95 | `r_bar` | events over quota | recoverable gap |
|---:|---:|---:|---:|---:|---:|
| 1 | 8.00 | 8 | 0.156 | 0.00% | 46.97% |
| 2 | 15.02 | 16 | 0.293 | 0.00% | 49.25% |
| 4 | 26.58 | 30 | 0.519 | 0.00% | 48.12% |
| 8 | 42.63 | 50 | 0.833 | 2.19% | 44.96% |
| 16 | 59.21 | 72 | **1.156** | **81.49%** | **33.32%** |

The gap is roughly flat while `r_bar < 1` and falls sharply once the union routinely
exceeds capacity. The measured unions also fall below an independent uniform
routing null by 3.1% at B = 2 rising to 28.2% at B = 16, so concurrent requests
do overlap; the crossover is nevertheless reached between B = 8 and B = 16.

## 6.3 Same model, same workload, capacity only

Concurrency is not the only way to move `r_bar`. Holding the model, the trace and
the concurrency fixed and varying only the residency fraction produces the same
effect.

**Table 10.** Gap versus residency fraction at fixed concurrency.
*(128-expert model, per-layer scope, B = 16.)*

| ρ | best causal | Belady | recoverable gap |
|---:|---:|---:|---:|
| 20% | 30.33% | 28.08% | **7.42%** |
| 30% | 22.24% | 18.09% | 18.65% |
| 40% | 15.58% | 10.39% | **33.32%** |

A study reporting only the ρ = 20% row would conclude that existing policies are
within 7.4% of optimal and that the problem is closed. A study reporting only
the ρ = 40% row would conclude that a third of the traffic is recoverable. Both
are the same model, the same workload and the same concurrency.

## 6.4 Cross-model comparison fails on batch size and improves on `r_bar`

Table 11 compares three models two ways: aligned on batch size, as is
conventional, and aligned on mean `r_bar`.

**Table 11.** Recoverable gap under two alignment choices. *(ρ = 40%, per-layer
scope, event-atomic.)*

| alignment | model | B | `r_bar` | gap | spread |
|---|---|---:|---:|---:|---:|
| **on batch size** | 40-expert | 8 | 1.75 | 8.17% | |
| | 64-expert | 8 | 1.44 | 28.26% | |
| | 128-expert | 8 | 0.83 | 44.96% | **36.8 pp** |
| **on `r_bar ≈ 0.30`** | 64-expert | 1 | 0.313 | 48.13% | |
| | 128-expert | 2 | 0.293 | 49.25% | **1.1 pp** |
| **on `r_bar ≈ 0.51`** | 40-expert | 1 | 0.500 | 43.48% | |
| | 128-expert | 4 | 0.519 | 48.12% | **4.6 pp** |

Aligned on batch size, the three models appear to behave qualitatively
differently — one suggests the problem is essentially closed, another that it is
wide open. Aligned on `r_bar`, the same measurements agree to within a few
percentage points. The apparent architecture dependence was a regime difference.

This also bounds what small models can be used for. The 40-expert model at
ρ = 40% cannot reach `r_bar < 0.5` at any concurrency, because a single request
already touches 8 of its 16 per-layer slots. Regimes below that are simply not
observable on it, and results from it cannot be extrapolated into them.

**A note on the analytical reference frame.** For the frontier-scale
specification of §3.2 — 896 experts, top-16, ρ = 40%, giving `c_l ≈ 358` — the
expected per-step union at B = 8 under a uniform routing null is ≈120, so
`r_bar ≈ 0.335` under that null. That places it near the 64-expert model at B = 1 and the 128-expert
model at B = 2, and far from any of them at B = 8. We state this only to
illustrate that the alignment matters at scale; it is an analytical projection
from published architecture parameters, not a measurement.

## 6.5 Necessary but not sufficient

`r_bar` is a normalizer, not a sufficient statistic. To show this directly we
hold the multiset of event expert sets and `r_bar` **exactly** constant — the
same events, the same sets, the same mean value 0.8237 — and permute only their
temporal order.

The recoverable gap moves from 44.85% to 30.79%–31.06%, and the best causal
policy changes from LFRU to LFU.

![**Figure 3. Matching mean union/cache is not sufficient.** The original
event order and all twenty permutations have the same event-set multiset and
mean ratio (0.8237); only temporal order changes.](figures/figure3_regime_not_sufficient.pdf){#fig:regime-insufficiency width=78%}

The permutation does not represent a realizable request scheduler; it is a
mathematical sufficiency counterexample. It shows that reuse structure, not just
working-set size relative to capacity,
determines both the size of the gap and which policy realizes it. Quantities
that vary independently of `r_bar` and that we expect to matter include the
inter-event drift of the working set, the reuse-distance distribution, expert
popularity concentration, top-`k`/`N`, cache scope, and the scheduling
discipline. §9 gives an instance of the last: changing only the service
discipline, at fixed request set, capacity and mean batch size, moves a static
pinned set from 7.5% worse than LFRU to 17.0% better.

The correct prescription is therefore: **report the distribution of `r(s,l)`
and at least `r_bar` — without it, cross-model comparison is not interpretable —
but do not treat matching `r_bar` as sufficient grounds for extrapolation.**

## 6.6 Consequence: gap alone is not a decision criterion

Sections 6.2 and 6.3 have a practical corollary. A small gap is ambiguous: it
can mean that existing policies are close to optimal, or that the system is in
the thrashing regime where nothing helps. The two are distinguished only by the
absolute traffic relative to a transfer budget.

Here "offline traffic" means Belady's transferred bytes under the fixed access
sequence, because causal traffic above budget does not by itself establish
physical infeasibility.

| | small causal-to-offline gap | large causal-to-offline gap |
|---|---|---|
| **offline traffic within budget** | existing policies suffice; a controller is unnecessary | genuine algorithmic headroom on the fixed sequence |
| **offline traffic over budget** | **no residency policy on this sequence is viable** | oracle also fails; the gap is not enough to cross the budget |

We recommend that any reported gap be accompanied by the absolute transferred
bytes per output token and the bandwidth budget implied by the target service
rate. In our own use of this criterion, the smaller models produced operating
points in the lower-left cell — gap under 10% with the offline optimum still
several times over budget — that a gap-only reading would have classified as
"existing policies already suffice."

We do not claim `r = 1` is a sharp threshold, only that behaviour changes across
it; the permutation ablation establishes insufficiency rather than quantifying
how much of the gap reuse structure explains in general (§11).

