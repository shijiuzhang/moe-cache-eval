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

**Table A1.** Per-paper extraction from the frozen public versions. “NR” means
not reported in the public paper.

| work | class and evaluation vehicle | reported experimental setting | reporting interpretation |
|---|---|---|---|
| [SpecMD](https://arxiv.org/abs/2602.03921) | A; PyTorch hooks on one A100-80GB with software capacity/bandwidth constraints | GSM8K, TruthfulQA and NaturalQuestions; autoregressive generation; 1/5/25% capacity; 5GB/s example; active batch and chat formatting NR | End-to-end path, so event replay is N/A; union ratio and template multiplicity NR. Comparable policy names do not imply the same execution contract or denominator. |
| [DALI](https://arxiv.org/abs/2602.03495) | A; KTransformers-based RTX 3090 system | C4 with WikiText calibration; default prompt/output 64; batch-size sweeps; often 50% cache with some 25% ablations; chat formatting and template multiplicity NR | Event replay is N/A and union ratio is NR. DALI reports real throughput; Axis I is not a criticism of it. |
| [Fate](https://arxiv.org/abs/2502.12224) | A/D; two-PC implementation | ChatGPT-prompts, HumanEval and GSM8K; decode output up to 1024; prefill lengths 128/256/512; memory budgets reported; active decode concurrency, chat formatting and template multiplicity NR | Event replay is N/A and union ratio is NR. Fate predicts next experts for prefetch, not next-use distance. |
| [Pre-gated MoE](https://arxiv.org/abs/2308.12066) | C; trained architecture and FasterTransformer implementation | XSum, closed-book QA and SQuAD; primary system focus at batch 1; model/cache design and task datasets reported; chat template not applicable or NR | Event replay is not the paper's question and union ratio is NR. The method modifies training and the routing contract, outside strictly post-hoc caching. |
| [SiDA-MoE](https://arxiv.org/abs/2310.18859) | C/D; hash-based predictor/system design | C4 and Switch-family evaluation; model configuration reported; category-template risk not applicable to the reported corpus setup | Event replay is not the primary question and union ratio is NR. Its prediction objective differs from victim next-use ranking. |
| [MoE-Beyond v1](https://arxiv.org/abs/2508.17137v1) | B/D; token/layer activation predictor plus trace-based simulator | 6,994 Puffin training prompts and 100 WebGLM-QA test prompts; batch size 1; cache-capacity sweep; chat formatting NR | Token-by-token replay is described, but fused-event retention details and union ratio are NR. Batch 1 removes cross-request union, leaving insufficient detail for an event-contract comparison. |
| [Mixtral-Offloading](https://arxiv.org/abs/2312.17238) | A; end-to-end offloading implementation | OpenAssistant conversations with autoregressive sampling; practical focus at batch 1; per-layer cache sizes and source conversations reported; chat-template details NR | Event replay is N/A and union ratio is NR. Its real-system latency is not invalidated by our replay result. |
| [HOBBIT](https://arxiv.org/abs/2411.01433) | A; llama.cpp-based CPU–GPU system | Alpaca for performance; GSM8K and TruthfulQA for quality; several input/output lengths; batch 1; cache/precision budgets reported; chat formatting and template multiplicity NR | Event replay is N/A and union ratio is NR. Lossy precision fallback is outside our strictly lossless scope. |
| [MoE-Infinity](https://arxiv.org/abs/2401.14361) | A; RTX A5000 end-to-end system | 290 BIGBench/FLAN/MMLU tasks; prompt 512/output 32 in the main latency test; local deployment, effectively batch 1; task rendering insufficient for §5 diagnostics | Event replay is N/A and union ratio is NR. Request-level activation maps and real execution answer a different question. |
| [SP-MoE](https://arxiv.org/abs/2510.10302) | A; speculative decoding and expert-prefetch system | Four public datasets; autoregressive evaluation; batch size 1; chat/template multiplicity NR | Event replay is N/A and union ratio is NR. Its prefetch/speculation target differs from cache-victim prediction. |

## A.3 What may and may not be concluded

The audit supports three reporting claims: most audited systems do not expose a
directly comparable `r_bar`; prompt-surface contamination cannot generally be
checked from their papers; and our replay-semantics warning should not be aimed
at end-to-end implementations. It does not support re-labelling published
speedups as artifacts, assigning a direction to an unreported implementation
choice, or inferring that a dataset used one fixed prompt merely because prompt
construction was omitted.
