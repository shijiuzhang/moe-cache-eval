# §5 Axis II — Workload Contamination

*Draft v2 — 2026-08-02.*

> **Claim.** Probe sets that wrap each workload category in a single instruction
> template produce verbatim-identical generation prefixes across concurrent
> requests. The resulting expert overlap is readily mistaken for semantic
> locality. A matched-pair rendering intervention changes the measured
> early-window effect by 19.4–31.9 percentage points, and correcting the
> construction reverses the point-estimate category ordering.

## 5.1 A conclusion that did not survive

We first measured workload-conditioned expert locality on a probe set built the
obvious way: six workload archetypes, one instruction template per archetype,
public payloads substituted into each. The result was clean, passed a
pre-registered confirmatory split, and had an appealing interpretation —
industrial process-diagnostics traffic appeared to concentrate on a markedly
narrower expert working set than general office traffic.

Table 4 shows what happened when the probe set was rebuilt to control for
prompt-surface repetition, holding the model, the payload sources, the cache
configuration, and the metric fixed.

**Table 4.** Reduction in effective miss fraction of a homogeneous
single-archetype stream relative to a mixed stream.
*(128-expert model, per-layer scope, ρ = 40%, B = 8, event-atomic.)*

| workload archetype | single-template probe set | diversity-controlled probe set |
|---|---:|---:|
| process diagnostics | **57.2%** *(headline result)* | **5.9%** |
| document RAG | 57.9% | 43.7% |
| ERP structured analytics | 36.2% | 7.6% |
| equipment maintenance / BOM | 35.3% | 22.0% |
| office / legal | 26.9% | **53.3%** |
| tool agent | 9.5% | 10.2% |

The point-estimate ordering does not merely compress; it inverts. The archetype that had
supported the strongest claim falls to near the bottom, and the archetype that
had ranked second from last rises to the top. We withdrew the original
conclusion. The remainder of this section explains why it was wrong, how to
detect the failure, and how much of the corrected ordering is actually
supported.

## 5.2 Mechanism

Three conditions combine, none of which is individually unusual.

*A shared template tail.* Every prompt in a category ends with the same
instruction sentence. Under raw continuation — that is, when the model's chat
template is not applied — the model completes that sentence verbatim before
producing anything task-specific, and then emits a fixed reasoning preamble.

*A short decode window.* If only a few dozen decode steps are recorded, the
shared prefix is a large fraction of every trace. In our original collection the
first 15–25 of 63 recorded steps were near-identical across requests.

*Position-locked cohorts.* If all requests are the same length and are admitted
and retired in lock-step, concurrent requests occupy identical decode positions,
so the shared prefix aligns exactly at the same scheduling step. The per-step
expert union is then computed over near-identical token contexts.

The consequence is direct. In one archetype, 4 of 16 requests produced
byte-identical 63-token outputs; positional token agreement within that
archetype was 20.65%, against 1.04% for a category whose payloads were long
heterogeneous documents.

## 5.3 Two diagnostics that separate the explanations

Within-category expert overlap alone cannot distinguish semantic locality from
surface repetition. Two measurements do, and neither requires a control arm.

*Residual after removing near-duplicate text.* We restrict the comparison to
request pairs whose generated text barely overlaps — positional token agreement
below 5% — and compare the residual against a cross-archetype baseline.

**Table 5.** Within-archetype pairwise expert Jaccard, all pairs and restricted
to low-text-overlap pairs. *(16 requests per archetype.)*

| | single-template set | | diversity-controlled set | |
|---|---:|---:|---:|---:|
| archetype | token agr. | expJac \| lowTok | token agr. | expJac \| lowTok |
| process diagnostics | 20.65% | 0.158 | 0.78% | 0.087 |
| equipment / BOM | 15.33% | **0.092** | 1.06% | 0.108 |
| ERP | 5.15% | 0.118 | 0.61% | 0.096 |
| tool agent | 1.85% | 0.103 | 0.53% | 0.085 |
| document RAG | 1.04% | 0.144 | 0.45% | 0.119 |
| office / legal | 0.74% | 0.123 | 0.57% | 0.144 |
| *cross-archetype baseline* | | *0.078* | | *0.077* |

On the single-template set, equipment/BOM has a raw within-class Jaccard of
0.229; restricting to low-text-overlap pairs collapses it to 0.092, essentially
the cross-archetype baseline of 0.078, and process diagnostics falls from 0.291
to 0.158. Categories whose payloads were naturally heterogeneous barely move. On
the diversity-controlled set all sequences are unique and the two columns nearly
coincide, indicating that the surface-repetition channel has been closed rather
than reduced. We report `expJac | lowTok` minus the cross-archetype baseline as
the residual workload effect.

*Prefix-aligned decay.* Template echo must fade as the shared prefix ends. A
genuine task effect can also vary across response phases, so position dependence
alone is neither necessary nor sufficient; the stronger signal is an abrupt
decay aligned with a shared, near-identical generated prefix.

**Table 6.** Reduction in per-step expert union of a homogeneous stream relative
to a category-round-robin mixture, by decode-position band. *(B = 16.)*

| archetype | single-template set | | diversity-controlled set | |
|---|---:|---:|---:|---:|
| | early (t 0–8) | late (t 32–63) | early (t 0–16) | late (t 160–384) |
| process diagnostics | 65.7% | 29.1% | 6.0% | **−7.8%** |
| equipment / BOM | 39.2% | 13.8% | 3.7% | 6.2% |
| ERP | 24.5% | 11.5% | 6.8% | −8.6% |
| document RAG | 1.2% | **20.2%** | 7.1% | **17.1%** |
| office / legal | 4.0% | 9.7% | 11.6% | **20.1%** |
| tool agent | 7.1% | 5.8% | −8.6% | 24.3% |

On the contaminated set the three template-rendered categories decay steeply
while the two with heterogeneous natural-language payloads are flat or rising;
on the corrected set the decaying categories collapse to near zero or below and
the rising ones persist. Combined with prompt and output overlap this gives a
screening rule: **an effect concentrated in a position band occupied by a shared
generated prefix should be treated as surface repetition until a diverse or
matched control says otherwise.**

## 5.5 Matched-pair attribution

Diagnostics indicate contamination; they do not quantify it. We therefore render
a subset of the *same source records* twice — once with the diversified forms and
once with a single fixed template ending in a fixed instruction — and pair them
by source record. Model, cache configuration, concurrency and metric are
identical; the prompt-rendering policy is the treatment.

**Table 7.** Difference in apparent union reduction under the fixed rendering,
matched on source record, early decode band (t 0–16).

| archetype | template-attributable |
|---|---:|
| office / legal | +31.9 pp |
| process diagnostics | +28.8 pp |
| ERP | +26.4 pp |
| tool agent | +24.5 pp |
| equipment / BOM | +20.9 pp |
| document RAG | +19.4 pp |

![**Figure 2. Prompt rendering contributes materially to the apparent
early-window workload effect.** Each bar is the fixed-template arm minus the
diverse arm for the same source records at t=0–16; it is not an end-to-end miss
reduction.](figures/figure2_template_attribution.pdf){#fig:template-attribution width=92%}

This matched contrast is causal for the **rendering policy**, not for a pure
full-service template-echo component: changing the wrapper also changes the
continuation, response length and cache churn. Its early position-aligned band,
together with the shared prefix, is what specifically supports the echo
interpretation.

One asymmetry deserves note. The fixed-template arm has a *higher* effective
miss fraction over the full trace (21.99% vs 18.78% at ρ = 40%, B = 8) even
though it shows a larger early-window union reduction, because the fixed
template also shortens responses and increases cold-start frequency. Template
echo therefore cannot be read off the end-to-end miss difference; only the
position-resolved union comparison isolates it.

## 5.6 A diversity-controlled probe set

The corrected set holds payload sources fixed and varies only the wrapper:
twelve structurally distinct prompt forms, each terminating in a different kind
of line, crossed with two instruction languages, so that no two records in an
(archetype, split) cell share a form-language pair; eight task framings per
archetype; five payload rendering styles; and, for the industrial archetypes,
six source families with different record shapes. Candidate payloads whose
5-gram Jaccard against an already-selected payload exceeds 0.30 are rejected at
selection time, because several public sources are internally repetitive. The
matched-pair arm of §5.5 is built in. The result is 23-24 distinct 70-character
prompt heads per 24-record cell against 1-4 per 20-record cell in the original,
and a mean pairwise 5-gram Jaccard of 0.002-0.014 against 0.038-0.190.

## 5.7 How much of the corrected ordering is supported

Correcting a measurement invites the assumption that the corrected result is
sound. We checked. Two issues affect Table 4's right-hand column.

First, the mixed reference stream contains six times as many distinct requests
as each homogeneous stream, and a stream with fewer distinct requests has more
inter-request reuse for reasons unrelated to workload. We rebuilt the reference
as seven size-matched draws. The confound proves small — the size-matched
reference is 17.81% against 18.76% for the original — but the seven draws span
15.54%–19.04%, a standard deviation of 1.18 percentage points.

Second, each homogeneous condition is itself a single draw of twelve requests.
We replicated all six on a disjoint held-out set of twelve.

**Table 8.** Homogeneous-stream miss fraction, two independent draws, against a
size-matched reference. Interval propagates the reference's draw-to-draw spread;
it is not a population confidence interval.

| archetype | draw 1 | draw 2 | mean | improvement vs 17.81% | ±1 s.d. of reference |
|---|---:|---:|---:|---:|---|
| office / legal | 8.76% | 8.15% | 8.45% | **52.5%** | 49.2 – 55.5 |
| document RAG | 10.57% | 10.69% | 10.63% | **40.3%** | 36.1 – 44.0 |
| equipment / BOM | 14.64% | 13.33% | 13.99% | 21.5% | 15.9 – 26.4 |
| ERP | 17.33% | 15.18% | 16.25% | 8.8% | 2.3 – 14.4 |
| process diagnostics | 17.65% | 16.34% | 16.99% | 4.6% | **−2.2 – 10.5** |
| tool agent | 16.85% | 18.17% | 17.51% | 1.7% | **−5.3 – 7.8** |

Only the top two archetypes are clearly separated from the reference;
equipment/BOM is positive with a wide interval; and the bottom three are not
distinguishable from zero at this sample size. The honest statement is therefore
not that six archetypes form an ordering, but that **two of six show a workload
effect that survives both the contamination correction and a size-matched
reference.**

## 5.8 Applicability beyond our own data

The diagnostics of §5.3–§5.4 are not specific to our probe set. Applied to the
first 48 complete records of a public Mixtral routing artifact over C4 input
sequences, each truncated to 512 input tokens, they report 48 of 48 unique token
sequences and a 95th-percentile positional agreement of 1.37% — no contamination
signal [@raffel2020t5; @allenai2024mixtralroutes]. As a labelled sensitivity
check, we then copied one record's first 64
token-and-route positions into every record. Positional agreement rose from
0.641% to 13.050%, mean expert Jaccard from 0.185 to 0.286, and the diagnostic
flag changed from false to true.

The natural-C4 run is a false-positive check and the injected run is a synthetic
positive control. Neither is an external replication of the prompt-rendering
effect: the public artifact contains no workload labels or matched template arm,
and the injection is not a model-generated response.

The effect requires a shared template tail, a decode window short enough for the
prefix to dominate, and, for the union metric, position-aligned concurrency; we
do not claim every template-based probe set satisfies them (§11).

