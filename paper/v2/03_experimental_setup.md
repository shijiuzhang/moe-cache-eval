# §3 Experimental Setup

*Draft v2 — 2026-08-02.*

## 3.1 Why expert caching is a cache problem with unusual structure

A routed MoE layer selects `k` of `N` experts per token; under offloading the
resident subset lives in device memory and the remainder is streamed on touch.
Three properties shape every measurement that follows. The access unit is a set,
not an element: all experts a step touches at a layer are required together
(§2.1), so hit/miss classification is naturally event-level. Concurrency
deduplicates for free: experts selected by several concurrent requests are
fetched once, a benefit belonging to the scheduler rather than to any policy,
which we account for separately throughout. And the binding budget is bandwidth,
not capacity alone: raising the residency fraction lowers traffic but consumes
memory that also serves KV state and workspace, so a policy is useful only if it
reduces bytes at fixed residency, or permits lower residency at fixed service
quality.

## 3.2 Models

| | experts `N` | top-`k` | MoE layers `L` | blocks `L·N` |
|---|---:|---:|---:|---:|
| Granite-3.1-3B-A800M | 40 | 8 | 32 | 1,280 |
| OLMoE-1B-7B-0125 | 64 | 8 | 16 | 1,024 |
| **Qwen3-30B-A3B (4-bit)** | **128** | **8** | **48** | **6,144** |

The model-family descriptions follow their official technical reports or model
documentation [@ibm2024granite31; @muennighoff2025olmoe; @yang2025qwen3].

The exact model revisions are frozen in the route manifests: Granite commit
`d4dd87aa3a6c201bc374851d7d7ff4cf39a0b82a`, OLMoE commit
`9b0c1aa87e34a20052389dce1f0cf01da783f654`, and the MLX Qwen3 snapshot
`d388dead1515f5e085ef7a0431dd8fadf0886c57` (4-bit, group size 64).

Qwen3-30B-A3B is the primary model: its expert count places it at the boundary
where the per-step expert union crosses per-layer cache capacity (§6), which is
the regime the two smaller models cannot reach. The smaller models are used for
cross-model checks and for the replay-semantics measurement of §4. All three are
evaluated at the same residency fractions and under identical replay semantics.

**Analytical reference frame.** To express results in engineering units we also
use a paper specification of a frontier-scale MoE: 92 MoE layers, 896 routed
experts, top-16, 82,432 expert blocks of ≈16.74 MiB, ≈106.55 GiB of non-routed
weights, ≈1,347.12 GiB of routed expert weights, and ≈25.83 GB of logical expert
bytes per output token before deduplication. **No trace from this model was
collected and no measurement in this paper was taken on it.** It is used only to
state operating regimes and unit conversions, and every quantity derived from it
is labelled as an analytical projection, never as a prediction.

## 3.3 Traces

Decode routing was collected autoregressively with the model's chat template
applied and reasoning mode disabled, greedy decoding, prompts capped at 4,096
tokens, and up to 384 recorded decode forwards per request with natural
end-of-sequence termination. For each request we store the emitted token
sequence, the effective length, and the complete per-layer router logits,
top-`k` indices, probabilities, gate weights, entropy and margin.

Two collection choices matter for later sections and are the direct consequence
of §5. Applying the chat template prevents the model from continuing the
instruction text instead of answering it. Recording several hundred decode steps
places the majority of each trace beyond the boilerplate-dominated opening
region. An earlier collection that did neither is retained and re-analysed in
§5 as the contaminated condition.

Traces are converted into event streams (§2.1) under first-come-first-served
continuous batching with same-step cross-request deduplication. Admission
offsets are configurable so that concurrent requests are not locked to identical
decode positions.

The primary Qwen3 collection ran on a Mac mini with an Apple M4 Pro and 24 GiB
unified memory under macOS 26.5.1, Python 3.12.13, MLX 0.32.0 and MLX-LM 0.31.3.
It contains 144 confirmatory requests in 24 shards, uses the snapshot above,
and reached 19.31 GB peak Metal allocation. All collection parameters and shard
hashes are stored in the source manifest rather than inferred from filenames.
MLX is cited as versioned software rather than as an inferred hardware-system
paper [@mlx2025].

## 3.4 Workload probe set

Measuring workload-conditioned routing requires requests partitioned by task.
We use **ControllerProbe-D1**: 432 records over six workload archetypes —
document RAG, tool agent, ERP structured analytics, office/legal, process
diagnostics, and equipment maintenance/BOM — built from public benchmark and
public industrial sources. The benchmark-derived portions use LongBench,
Berkeley Function Calling Leaderboard, Spider 2.0, and LegalBench
[@bai2023longbench; @yan2024bfcl; @lei2024spider20; @guha2023legalbench]; the
industrial portions include the Petrobras 3W data and Apache OFBiz sample
entities [@vargas2019threew; @apacheofbiz2026], with the complete source and
licence ledger released alongside the artifact. Its construction is described
in §5; the properties
that matter here are:

- twelve structurally distinct prompt forms, each terminating in a different
  kind of line, crossed with two instruction languages, so that no two records
  in a cell share a form–language pair;
- eight task framings per archetype and five payload rendering styles;
- a **matched-pair control arm** in which a subset of the same source records is
  re-rendered with a single fixed template, so that template effects can be
  measured rather than argued;
- a group-aware discovery/confirmatory split with no source group in both sides.

Category proportions in the probe set are a design choice for controlled
comparison and are **not** an estimate of any deployment's traffic mix.

## 3.5 Simulator and statistical discipline

The simulator implements Definition 2 with per-layer and global scope, seeded
tie-breaking, and the policy set of §2.3. It is validated against the reference
trace of §2.5.

Every threshold presented as a confirmatory **decision criterion** was
pre-registered and frozen before the corresponding measurement was read,
together with the split it would be evaluated on. Exploratory diagnostics,
failure attribution, and reviewer-driven audits were not pre-registered. We
release the decision documents unchanged, including those in
which a criterion failed and the associated development line was stopped. Where
a design parameter was revised, the revision and its rationale are recorded with
the statement that no result had yet been generated or read; §8 gives one such
case. Discovery and confirmatory splits are disjoint at the source-group level,
and confirmatory data is read once.

We report tie-seed sensitivity for the principal conditions. We do not report
population confidence intervals for quantities estimated from a single trace,
and we mark such quantities as implementation-stable rather than
statistically bounded.
