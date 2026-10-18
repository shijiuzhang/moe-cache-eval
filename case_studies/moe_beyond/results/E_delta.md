# Analysis E — reporting-block comparison

Target of every field: original reported configuration (published simulator contract, rho 0.10, global, B = 1, prefetch included). Counting: headline = answered fields; not_applicable counted separately (DEVIATIONS D-007).

| section | field | paper only | with artifact, package and analyst steps | provenance |
|---|---|---|---|---|
| Execution model | event unit | answered | answered | execution |
| Execution model | retention decision | NR | answered | execution |
| Execution model | intra-event order (if immediate) | NR | answered | data_inspection |
| Execution model | conformance trace | answered | answered | analyst_inference |
| Workload | templates per category | NR | NA | — |
| Workload | distinct prompt heads / finals | NR | answered | execution |
| Workload | chat template applied | NR | answered | code_inspection |
| Workload | decode steps recorded | NR | answered | code_inspection |
| Workload | position-locked cohorts | not_applicable | not_applicable | code_inspection |
| Workload | unique generated sequences | NR | not_applicable | code_inspection |
| Workload | positional token agreement | NR | answered | execution |
| Workload | expert Jaccard \| low-text-overlap | NR | answered | execution |
| Workload | effect stable across position bands | NR | NA | — |
| Regime | experts N, top-k, layers | answered | answered | execution |
| Regime | residency fraction rho | answered | answered | code_inspection |
| Regime | cache scope | NR | answered | code_inspection |
| Regime | union per layer-step | NR | answered | execution |
| Regime | capacity per layer | NR | answered | execution |
| Regime | r(s,l) = union / capacity | NR | answered | execution |
| Regime | concurrency | answered | answered | execution |
| Regime | service discipline | answered | answered | execution |
| Regime | miss denominator | answered | answered | execution |
| Regime | dedup credited to policy | not_applicable | not_applicable | code_inspection |
| Regime | static fit source | not_applicable | not_applicable | code_inspection |
| Regime | static quota rule | not_applicable | not_applicable | code_inspection |
| Regime | initial pinned load counted | not_applicable | not_applicable | code_inspection |
| Oracle | offline bound reported | answered | answered | code_inspection |
| Oracle | forced-admission decomposition | NR | NA | — |
| Oracle | absolute bytes per output token | NR | not_applicable | code_inspection |
| Oracle | bandwidth budget assumed | NR | DECLARE | — |

From the paper text alone, 8 of the 30 reporting-block fields are answered (5 more are established as not applicable); with the public artifact, the package and the documented analyst steps, 19 are answered (7 not applicable). The fields answered only in the second mode, with their provenance, are: retention decision (execution), intra-event order (if immediate) (data inspection), distinct prompt heads / finals (execution), chat template applied (code inspection), decode steps recorded (code inspection), positional token agreement (execution), expert Jaccard | low-text-overlap (execution), cache scope (code inspection), union per layer-step (execution), capacity per layer (execution), r(s,l) = union / capacity (execution).

Scope: paper text vs public artifact + package + documented analyst steps; no artifact-only control (DEVIATIONS D-008).

## Package analyses (different contract; not entries of the block, not counted)

- residency-gap decomposition (analysis D) — package: event-atomic, prefetch-free, cold start; E1, rho 0.40, per-layer, persistent: recoverable gap 47.71%, admission share 3.95%, future-victim share 96.05%.
  *These are prefetch-free residency results under our replay contract and are not comparable with the prefetch-inclusive hit rates reported by MoE-Beyond.*

Divergence recorded without attribution: the public text (§4.1.2) describes recording “each token in the generated sequences”; the published collection scripts run one prefill forward pass per prompt and record no generated token.
