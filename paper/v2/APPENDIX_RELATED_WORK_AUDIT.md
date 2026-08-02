# Appendix A — Related-work reporting audit

Date audited: 2026-08-02.  
Rule: `not reported` means only that the public paper text did not expose the
field. It is not an assertion about private code or actual execution.

The audit freezes the following public versions: SpecMD v1, DALI v1, Fate v2,
Pre-gated MoE v3, SiDA-MoE v2, MoE-Beyond v1, Mixtral-Offloading v1, HOBBIT v2,
MoE-Infinity v3, and SP-MoE v2. Titles and version identifiers were rechecked
against the official arXiv abstract pages on 2026-08-02; detailed evaluation
claims were checked against the corresponding PDFs. `paper/references.bib`
contains the formal records. A later paper revision must be re-audited rather
than silently substituted.

## A.1 Self-audit first

| item | original state | correction | status |
|---|---|---|---|
| offline oracle | forced every miss to be admitted | implemented bypass-capable Belady; retained forced-admit only as a decomposition probe | superseded |
| replay | flattened an event in ascending expert-ID order | event-start hit/miss classification and boundary retention | conclusion about admission/pinning withdrawn |
| workload probe | one category template, raw continuation, 63 decode steps | chat template, diverse wrappers, 384-step cap, natural EOS, staggered arrivals, matched control | industrial-locality headline withdrawn |
| scheduling oracle | per-step best of 300 random batches: 19.3% | complete trajectories, `W=4`: 5.9–7.9% | old headroom estimate withdrawn |
| semantic partitions | best dedicated partition had 6 slots for top-8 routing | identified that the grid could not hold one request's single-step set | treated as design failure, not mechanism refutation |
| condition count | verbal claim of 17; first 13-condition artifact lacked frozen selections | deterministic 13-condition v2 with IDs, offsets, condition hashes and source hash | v1 superseded |

## A.2 Per-paper extraction

Abbreviations: **A** end-to-end system; **B** trace-driven simulation; **C**
architecture/training co-design; **D** prediction study. “Union ratio” means the
measured per-step/per-layer union divided by usable cache capacity, not a null
model estimate.

\begin{landscape}
\scriptsize

| work | class / evaluation vehicle | workloads and reported generation setting | capacity / concurrency reporting | event replay applicability | union ratio | prompt-surface fields | interpretation |
|---|---|---|---|---|---|---|---|
| [SpecMD](https://arxiv.org/abs/2602.03921) | A; PyTorch hooks on one A100-80GB with software capacity/bandwidth constraints | GSM8K, TruthfulQA, NaturalQuestions; autoregressive generation | 1/5/25% capacity; 5GB/s example; active batch/chat formatting not reported | N/A to its end-to-end path | not reported | template multiplicity and chat template not reported | directly comparable policy names do not imply the same execution contract or denominator |
| [DALI](https://arxiv.org/abs/2602.03495) | A; KTransformers-based RTX 3090 system | C4; WikiText calibration; default prompt/output 64 | batch-size sweeps; often 50% cache, some 25% ablations | N/A | not reported | chat formatting and template multiplicity not reported | reports real throughput; Axis I is not a criticism of it |
| [Fate](https://arxiv.org/abs/2502.12224) | A/D; two-PC implementation | ChatGPT-prompts, HumanEval, GSM8K; decode output up to 1024 and prefill lengths 128/256/512 | memory budgets reported; active decode concurrency not reported | N/A | not reported | chat formatting and template multiplicity not reported | predicts next experts for prefetch, not next-use distance |
| [Pre-gated MoE](https://arxiv.org/abs/2308.12066) | C; trained architecture and FasterTransformer implementation | XSum, closed-book QA, SQuAD; primary system focus batch 1 | model/cache design reported | not the paper's trace-replay question | not reported | task datasets reported; chat template not applicable/reported | modifies training and routing contract; outside strictly post-hoc caching scope |
| [SiDA-MoE](https://arxiv.org/abs/2310.18859) | C/D; hash-based predictor/system design | C4 and Switch-family evaluation | model configuration reported | not the primary question | not reported | category-template risk not applicable to the reported corpus setup | prediction objective differs from victim next-use ranking |
| [MoE-Beyond v1](https://arxiv.org/abs/2508.17137v1) | B/D; token/layer activation predictor plus trace-based simulator | 6,994 Puffin prompts for training; 100 WebGLM-QA prompts for test | batch size 1 explicitly; cache-capacity sweep | applicable in principle; token-by-token replay described, fused-event retention details not reported | not reported | chat formatting not reported | batch 1 removes cross-request union; insufficient detail for event-contract comparison |
| [Mixtral-Offloading](https://arxiv.org/abs/2312.17238) | A; end-to-end offloading implementation | OpenAssistant conversations; autoregressive sampling | practical focus batch 1; per-layer cache sizes reported | N/A | not reported | source conversations reported; chat-template details not reported | real-system latency is not invalidated by our replay result |
| [HOBBIT](https://arxiv.org/abs/2411.01433) | A; llama.cpp-based CPU–GPU system | Alpaca for performance; GSM8K and TruthfulQA for quality; several input/output lengths | batch 1; cache/precision budgets reported | N/A | not reported | chat formatting and category-template multiplicity not reported | includes lossy precision fallback, outside our strictly lossless scope |
| [MoE-Infinity](https://arxiv.org/abs/2401.14361) | A; RTX A5000 end-to-end system | 290 BIGBench/FLAN/MMLU tasks; prompt 512/output 32 in main latency test | local deployment, effectively batch 1 in reported path | N/A | not reported | many tasks reported; task rendering details not sufficient for §5 diagnostics | request-level activation maps and real execution answer a different question |
| [SP-MoE](https://arxiv.org/abs/2510.10302) | A; speculative decoding and expert prefetch system | four public datasets; autoregressive evaluation | batch size 1 reported | N/A | not reported | chat/template multiplicity not reported | prefetch/speculation target differs from cache victim prediction |

\normalsize
\end{landscape}

## A.3 What may and may not be concluded

The audit supports three reporting claims: most audited systems do not expose a
directly comparable `r_bar`; prompt-surface contamination cannot generally be
checked from their papers; and our replay-semantics warning should not be aimed
at end-to-end implementations. It does not support re-labelling published
speedups as artifacts, assigning a direction to an unreported implementation
choice, or inferring that a dataset used one fixed prompt merely because prompt
construction was omitted.
