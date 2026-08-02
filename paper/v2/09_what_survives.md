# §9 What Survives

*Draft v2 — 2026-08-02.*

Three corrections, three scoped negative results, and one invalidated design
leave a small set of descriptive statements and baselines
statements. This section reports them, together with one confounder we did not
anticipate and found only because a mechanism experiment happened to use a
different service discipline.

## 9.1 A static pinned set is a simple reference, not a frontier

The simplest possible residency policy holds a fixed set of experts chosen
offline from a calibration trace and never updates it. It requires no counters,
no eviction logic, and no runtime state. Table 19 compares it against dynamic
policies under standard continuous batching, using a pin list fitted on the
calibration split and frozen before the held-out split was read.

**Table 19.** Static pinned residency versus dynamic policies across
concurrency. *(128-expert model, held-out split, per-layer scope, ρ = 40%,
event-atomic; pin list frozen from the calibration split; initial load counted.)*

| active B | static pinned | LFRU | Belady | static vs LFRU |
|---:|---:|---:|---:|---:|
| 2 | 21.50% | 12.84% | 6.37% | **−67.4%** |
| 4 | 20.81% | 16.26% | 8.43% | −28.0% |
| 8 | 19.37% | 18.01% | 9.93% | −7.5% |
| 16 | 17.10% | 16.64% | 11.32% | −2.8% |
| 24 | 15.28% | 14.92% | 12.21% | −2.4% |
| 32 | 13.84% | 13.52% | 12.20% | **−2.3%** |

The static set never wins, but the margin narrows monotonically from a factor of
1.7 at B = 2 to 2.3% at B = 32. The mechanism is the regime variable of §6: at
low concurrency the per-step working set is small relative to capacity and a
dynamic policy can track it precisely, whereas a fixed set must cover the global
popularity distribution; as concurrency grows the union approaches and then
exceeds capacity and the advantage of tracking disappears.

At B=8 and above the pin list transfers with a modest absolute penalty, but at
B=2 it is 67.4% worse than LFRU. This matters because a frontier-scale model at
the same residency fraction may occupy a similarly slack union/capacity regime;
our local data therefore do not support a product claim for static pinning.

The B=8 protocol audit makes the fit-source comparison explicit. On the same
held-out event stream and with identical equal per-layer quotas,
`Static-frozen` transfers 19.3684% of logical assignments, while the leaky
`Static-same-trace` diagnostic transfers 19.1004%. The frozen list therefore
pays 0.268 percentage points, or 1.403% relative, on this one held-out stream.
Both numbers count the initial 2,458-block preload. We make no claim about an
optimized nonuniform layer allocation: an earlier draft quoted such a result
without a frozen artifact, so it is removed rather than reconstructed after the
fact.

## 9.2 Static residency performance is a function of the popularity distribution alone

Because a static set never evicts, its steady-state miss count is simply the number of
accesses to non-resident blocks. Measured over the held-out trace, the access
distribution is only moderately concentrated:

| fraction of blocks | share of accesses |
|---:|---:|
| top 10% | 24.8% |
| top 20% | 44.0% |
| top 30% | 59.6% |
| top 40% | **72.3%** |

For the `Static-same-trace` diagnostic at ρ = 40%, the identity predicts a miss
ratio of 1 − 0.723 = 27.99% of **union accesses**, and the simulator reports
27.99% under that denominator before adding the one-time preload. This is not
the pre-dedup effective-miss fraction used in Table 19. The identity is exact for
the union-access denominator: static residency traffic depends only on the
access-count distribution and not on access order.

This has a useful consequence. Unlike every other policy in this paper, the
performance of a static pinned set can be computed from an **aggregate
per-layer, per-expert access histogram**, with no sequential trace required.
Predicting how a dynamic policy will behave requires the sequence; predicting
how a static one will behave does not.

## 9.3 A fourth confounder: service discipline

§8.3 evaluated affinity batching under a deadline-driven rotation in which up to
24 sessions are admitted and eight are served per step. We had also measured the
same request set under standard continuous batching. The two disagree about
which residency policy is better.

**Table 20.** Static versus dynamic residency under two service disciplines.
*(Identical 72 requests, 23,529 decode forwards, capacity and pin list;
128-expert model, ρ = 40%.)*

| service discipline | mean batch | static pinned | LFRU | static vs LFRU |
|---|---:|---:|---:|---:|
| continuous batching, B = 8 | 7.69 | 19.37% | 18.01% | **−7.5%** |
| deadline rotation, 24 admitted / 8 served, W = 4 | 7.83 | 19.15% | 23.08% | **+17.0%** |

The static arm barely moves (19.37% → 19.15%); LFRU degrades by five percentage
points. Rotating a subset of admitted sessions repeatedly disrupts the recency
and frequency state on which dynamic policies depend, while a fixed set has no
state to disrupt.

The two disciplines are not equally representative. Production continuous
batching advances every admitted sequence each iteration up to a concurrency
limit; queued requests wait rather than being rotated in, and rotation arises
mainly under memory-pressure preemption. The rotation used in §8.3 was chosen to
create the scheduling slack affinity selection requires, not because it models a
default deployment.

We report this as a measurement result rather than a design recommendation. It
means that **a residency-policy comparison that does not state its service
discipline is not interpretable**, on the same footing as the three axes of
§4–§6. We did not anticipate it, and we found it only because two experiments
run for different purposes happened to disagree.

## 9.4 Gate-mass rank is descriptive, not a quality result

Every mechanism in §8 attempts to reduce the *number* of misses. An orthogonal
approach reduces the *bytes per miss*: serve low-weight experts at reduced
precision while keeping high-weight experts at full precision. This changes
traffic without changing hit rate, so it is untouched by the Belady bound.

Its viability depends on how unevenly gate mass is distributed across the
top-`k` ranks. On the 128-expert model it is nearly flat:

| rank | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| share of gate mass | 21.5% | 16.4% | 13.7% | 11.9% | 10.5% | 9.4% | 8.6% | 8.0% |

The highest-ranked expert carries only 2.7× the mass of the lowest, and ranks
1–4 account for 63.5% of the total. This says that rank is a weak byte-allocation
heuristic on this model. It does **not** measure the quality loss from reducing
precision: gate mass is not causal output importance, quantization error is not
equivalent to dropping a contribution, and no mixed-precision implementation
was evaluated. We therefore retain the distribution as a design warning, not as
evidence that mixed precision is closed or that a larger model will be flatter.

A cross-model comparison at aligned regimes suggests the static disadvantage may
grow with expert count, but the evidence is two comparable points on
heterogeneously collected traces; we report it in Appendix B as
hypothesis-generating only.

