# Analysis C — workload construction

| prompt side (100 test prompts) | value |
|---|---:|
| distinct 70-character prompt heads | 100 |
| distinct final lines | 100 |
| word 5-gram Jaccard, mean / p95 | 0.0000 / 0.0000 |
| prompt-side flag | false |
| max repeated template count | NA (no skeleton rule in §5.6) |
| chat template applied | no |
| decode steps recorded | 0 |

| route side (first 48 records, input sequences) | value |
|---|---:|
| unique token sequences | 48 / 48 |
| positional token agreement, mean / p95 | 0.1343 / 0.2857 |
| token 5-gram Jaccard, mean / p95 | 0.0000 / 0.0000 |
| expert Jaccard, mean (pairwise p5–p95) | 0.2431 (0.1454–0.4086) |
| expert Jaccard on low-text-overlap pairs (agreement < 5%) | 0.14737107054939225 |
| §5.8 detector flag | true |

On the public test prompts, the §5.8 detector reports flag = true; this is a detector-level screening result, not a replication or refutation of any workload effect in that study.
