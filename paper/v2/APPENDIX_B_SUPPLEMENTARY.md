# Appendix B — Supplementary material

*Draft v2 — 2026-08-02.*

Material referenced from the body but not required to follow the argument.

## B.1 A minimal reporting block

The following is compact enough to include verbatim in a paper or artifact
README, and covers the items above that admit a one-line answer.

```
Execution model
  event unit ......................... (step, layer) union | per-access
  retention decision ................. event boundary | immediate
  intra-event order (if immediate) ... ascending id | randomized | n/a
  conformance trace .................. yes | no

Workload
  templates per category ............. N
  distinct prompt heads / finals ..... N / N
  chat template applied .............. yes | no
  decode steps recorded .............. N
  position-locked cohorts ............ yes | no
  unique generated sequences ......... N / N
  positional token agreement ......... mean, p95
  expert Jaccard | low-text-overlap .. value (cross-category baseline: value)
  effect stable across position bands  yes | no | n/a

Regime
  experts N, top-k, layers ........... N / k / L
  residency fraction rho ............. value
  cache scope ........................ per-layer | global
  union per layer-step ............... mean, p95
  capacity per layer ................. value
  r(s,l) = union / capacity .......... mean, p95, fraction > 1
  concurrency ........................ B (and admitted sessions if rotating)
  service discipline ................. continuous | rotation(W=..) | other
  miss denominator ................... pre-dedup | post-dedup
  dedup credited to policy ........... yes | no
  static fit source .................. same trace | discovery split | n/a
  static quota rule .................. description | n/a
  initial pinned load counted ........ yes | no | n/a

Oracle
  offline bound reported ............. yes | no
  forced-admission decomposition ..... admission % / future-victim %
  absolute bytes per output token .... value
  bandwidth budget assumed ........... value (and target service rate)
```

## B.2 The checklist applied to this paper

We fill the reporting block of §10.5 for the primary configuration. One field we
cannot complete, and we say so rather than omitting it.

```
Execution model
  event unit ......................... (step, layer) union
  retention decision ................. event boundary
  intra-event order .................. n/a
  conformance trace .................. yes (§2.5)

Workload
  templates per category ............. 24 form x language (diverse arm)
                                       1 (matched control arm, by design)
  distinct prompt heads / finals ..... 23-24 / 16-22 per 24-record cell
  chat template applied .............. yes, reasoning mode disabled
  decode steps recorded .............. up to 384, natural EOS
  position-locked cohorts ............ no (arrival offsets 0-23)
  unique generated sequences ......... 12 / 12 per archetype sample
  positional token agreement ......... 0.45-1.06% mean
  expert Jaccard | low-text-overlap .. 0.085-0.144 (cross-category: 0.077)
  effect stable across position bands  yes for 2 of 6 archetypes (§5.4, §5.7)

Regime
  experts N, top-k, layers ........... 128 / 8 / 48
  residency fraction rho ............. 0.40
  cache scope ........................ per-layer, remainder to lowest indices
  union per layer-step ............... 42.63 mean, 50 p95
  capacity per layer ................. 51-52
  r(s,l) = union / capacity .......... mean 0.833; fraction >1: 2.19%
  concurrency ........................ B = 8
  service discipline ................. continuous batching (FCFS);
                                       rotation variant reported separately
  miss denominator ................... pre-dedup (logical assignments)
  dedup credited to policy ........... no
  static fit source .................. discovery split (Static-frozen);
                                       evaluation trace (diagnostic only)
  static quota rule .................. equal per layer; remainder to lowest indices
  initial pinned load counted ........ yes

Oracle
  offline bound reported ............. yes
  forced-admission decomposition ..... 15.69% / 84.31%  (B=8)
                                       3.40% / 96.60%   (B=2)
  absolute transfer .................. 69.2 blocks per output token
                                       (best causal, held-out)
  bandwidth budget assumed ........... NOT APPLICABLE - no service-rate target
                                       is assumed for the primary model
```

The last field is a gap in our own reporting. Item D1 asks that a gap be
accompanied by the bandwidth budget implied by a target service rate, and for
the primary model we set no such target: the measurements are in blocks, and
converting them to a budget would require the hardware calibration §11.1 says we
do not have. We record the block count instead, and note that a reader wishing
to apply D1 to our numbers must supply the missing conversion themselves.

For completeness, the failures recorded during this work and released with the
pre-registrations are: an initial offline bound that forced admission of every
miss and was therefore not the offline optimum; the sequential replay of §4,
whose correction withdrew a conclusion about admission and pinning; the
single-template probe set of §5, whose correction withdrew a confirmatory
conclusion about industrial workload locality; a scheduling headroom estimate of
19.3% that fell to 5.9–7.9% when measured on complete trajectories (§8.4); a
category partitioning experiment that could not have produced a positive result
(§8.2); and, during internal review, an unsourced condition count that was
corrected from seventeen to thirteen. The first 13-condition artifact still
lacked frozen request selections and was superseded by a deterministic v2 with
every request ID, arrival offset, condition hash and source-manifest hash.

## B.3 Does the static disadvantage grow with expert count?

Referenced from §9. **Hypothesis-generating only**: two comparable points on the
expert-count axis, heterogeneous models, and all four rows collected under the
single-template protocol of §5, whose surface repetition inflates temporal
locality and therefore plausibly inflates the static disadvantage in every row.
The comparison is internally consistent; the levels are not trustworthy, and a
two-point extrapolation across a further factor of seven in expert count would
not be.

Table 18 measures one model. Comparing across models requires aligning on the
regime variable of §6, and doing so suggests a trend we can report but not
establish.

**Table B1.** Static versus dynamic at aligned operating regimes.
*(ρ = 40%, per-layer scope. Pin lists fitted on the evaluation trace itself —
deliberately leaky, so the static arm is shown at its best case and the trend is
conservative.)*

| model | experts | `r_bar` | static | LFRU | static vs LFRU |
|---|---:|---:|---:|---:|---:|
| 40-expert | 40 | 0.500 | 31.15% | 25.91% | −20.2% |
| 64-expert | 64 | 0.312 | 35.64% | 25.65% | **−39.0%** |
| 128-expert | 128 | 0.293 | 19.57% | 12.83% | **−52.6%** |
| 128-expert | 128 | 0.156 | 19.87% | 10.57% | −87.9% |

Two directions are visible: at comparable `r_bar`, the disadvantage grows with
expert count (−39.0% at 64 experts, −52.6% at 128); and within a single model it
grows as the regime becomes slacker (−52.6% at `r_bar` = 0.29, −87.9% at
`r_bar` = 0.16). Both are consistent with the mechanism of §9.1 — more experts means
a flatter popularity distribution, so a fixed top-fraction captures less of the
traffic, while a dynamic policy still tracks a working set that remains small
relative to capacity.

We label this hypothesis-generating rather than a result. There are only two
comparable points on the expert-count axis; the models differ in training and
tokenizer as well as in expert count; and all four rows use the
single-template collection of §5, whose surface repetition inflates temporal
locality and therefore plausibly inflates the static disadvantage in every row.
The comparison is internally consistent, but the levels are not trustworthy and
a two-point extrapolation across a further factor of seven in expert count would
not be.

## B.4 The invalidated partition grid

Referenced from §8.2. Retained so that the design failure is inspectable, not as
a negative result for semantic partitioning.

The partitioning experiment gave a dedicated per-layer slot budget to each of
the two archetypes that §5.7 identified as genuinely cache-friendly, with the
remaining four sharing a third partition. Total capacity was held exactly equal
to the shared baseline and the remainder was assigned to the shared partition,
so the dedicated partitions received no arithmetic advantage. A seven-point
allocation grid was swept on the calibration split, the best allocation frozen,
and the held-out split evaluated once. Every allocation lost, and the frozen one
increased transfer by 115.9%.

The natural reading is that semantic partitioning destroys cross-category expert
sharing and duplicates commonly used experts across partitions. We tested that
reading and it is largely wrong. Running the *shared* cache at each partition's
own slot count gives 61.08% miss at 6 slots and 27.25% at 39 slots, against
18.76% at the full 51. Weighting these by each partition's share of logical
expert assignments (0.1415, 0.1557, 0.7028) predicts

> 0.1415 × 61.08% + 0.1557 × 61.08% + 0.7028 × 27.25% = **37.30%**

against a measured 37.99%. **Capacity fragmentation alone accounts for 96% of
the degradation**; sharing and duplication together account for the remaining 4%.

The root cause is arithmetic. Top-`k` is 8, so a single request touches eight
experts at every layer, while a dedicated partition in the best allocation holds
six. No partition in the grid could retain even one request's per-step working
set, and the grid's largest dedicated allocation, 16 slots, holds two. **The
experiment as designed could not have produced a positive result**, and we say
so rather than presenting the outcome as a mechanism-level refutation.

Whether the arithmetic generalizes is a separate question, and for the
frontier-scale reference frame of §3.2 it does not: 358 per-layer slots divided
six ways gives ≈59.7 per partition against a per-category per-step union of
roughly 16–26, a margin of 2.3–3.7×. Hard partitioning may still lose there for
the sharing and duplication reasons, but it would not be excluded by capacity
arithmetic, and the −115.9% figure must not be carried across.
