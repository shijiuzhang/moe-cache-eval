# External route-contamination diagnostic

Source: `allenai/analysis_mixtral`, `c4_results.jsonl` (public route artifact).

This run audits 48 complete sequences × 512 tokens,
with 32 layers and top-2 expert IDs.

| metric | value |
|---|---:|
| unique token sequences | 48 / 48 |
| token positional agreement, mean | 0.6410% |
| token positional agreement, p95 | 1.3672% |
| token 5-gram Jaccard, mean | 0.000101 |
| token 5-gram Jaccard, p95 | 0.000989 |
| expert Jaccard, all pairs | 0.185118 |
| expert Jaccard, token agreement <5% | 0.185118 |
| Spearman(token agreement, expert Jaccard) | 0.2450 |
| contamination flag | False |

Interpretation boundary: this external C4 artifact has no task categories and no
matched template-control arm. It is therefore an external portability and
false-positive check for the diagnostics, not an independent replication of the
template-echo causal effect measured by ControllerProbe-D1.
