# External route-contamination diagnostic

Source: `allenai/analysis_mixtral`, `c4_results.jsonl` (public route artifact).

Synthetic shared prefix injected: **64 token-and-route positions**.

This run audits 48 complete sequences × 512 tokens,
with 32 layers and top-2 expert IDs.

| metric | value |
|---|---:|
| unique token sequences | 48 / 48 |
| token positional agreement, mean | 13.0497% |
| token positional agreement, p95 | 13.6719% |
| token 5-gram Jaccard, mean | 0.057527 |
| token 5-gram Jaccard, p95 | 0.060990 |
| expert Jaccard, all pairs | 0.286357 |
| expert Jaccard, token agreement <5% | not estimable (no low-overlap pairs) |
| Spearman(token agreement, expert Jaccard) | 0.2623 |
| contamination flag | True |

Interpretation boundary: This artifact deliberately injects an identical token-and-route prefix into public C4 records. It tests detector sensitivity to a known synthetic perturbation, not model response to a prompt template and not the magnitude of a natural contamination effect.
