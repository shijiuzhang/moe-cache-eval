# Analysis C — exploratory decomposition of positional agreement

**POST-HOC, NOT PRE-REGISTERED (DEVIATIONS D-004).** The pre-registered detector result in `C_workload.md` stands unchanged; this file only describes where the agreement sits.

| quantity | value |
|---|---:|
| records / pairs | 48 / 1128 |
| tokens per record, min / median / max | 3 / 15.5 / 38 |
| all records start with the same BOS token | true |
| positional agreement, frozen definition, mean / p95 | 0.1343 / 0.2857 |
| positional agreement, position 0 excluded, mean / p95 | 0.0280 / 0.1429 |
| pairs whose only agreement is position 0 | 815 (72.3%) |
| most common tokens at position 1 | Why (16), What (10), How (8) |

Factual statement for the report: the agreement is concentrated at position 0, a shared BOS token (72% of pairs agree only there), and at the question opener, in sequences of 3–38 tokens; the detector's threshold was validated on 512-token sequences. This describes the detector's length sensitivity; it is not a statement about whether that study's workload is contaminated.
