# Analysis E — reporting-block delta

Paper text alone: **13 of 30** fields. Public artifact with the released package: **25 of 30**.

| section | field | paper only | with artifact + package | added by package |
|---|---|---|---|---|
| Execution model | event unit | paper | computed |  |
| Execution model | retention decision | NR | computed | yes |
| Execution model | intra-event order (if immediate) | NR | computed | yes |
| Execution model | conformance trace | paper | computed |  |
| Workload | templates per category | NR | NA |  |
| Workload | distinct prompt heads / finals | NR | computed | yes |
| Workload | chat template applied | NR | computed | yes |
| Workload | decode steps recorded | NR | computed | yes |
| Workload | position-locked cohorts | paper | computed |  |
| Workload | unique generated sequences | NR | NA |  |
| Workload | positional token agreement | NR | computed | yes |
| Workload | expert Jaccard \| low-text-overlap | NR | computed | yes |
| Workload | effect stable across position bands | NR | NA |  |
| Regime | experts N, top-k, layers | paper | computed |  |
| Regime | residency fraction rho | paper | computed |  |
| Regime | cache scope | NR | computed | yes |
| Regime | union per layer-step | NR | computed | yes |
| Regime | capacity per layer | NR | computed | yes |
| Regime | r(s,l) = union / capacity | NR | computed | yes |
| Regime | concurrency | paper | computed |  |
| Regime | service discipline | paper | computed |  |
| Regime | miss denominator | paper | computed |  |
| Regime | dedup credited to policy | paper | computed |  |
| Regime | static fit source | paper | computed |  |
| Regime | static quota rule | paper | computed |  |
| Regime | initial pinned load counted | paper | computed |  |
| Oracle | offline bound reported | paper | computed |  |
| Oracle | forced-admission decomposition | NR | computed | yes |
| Oracle | absolute bytes per output token | NR | NA |  |
| Oracle | bandwidth budget assumed | NR | DECLARE |  |

From the paper text alone, 13 of the 30 reporting-block fields can be filled; with the public artifact and the released package, 25 can be filled. The fields that only the package made fillable are: retention decision, intra-event order (if immediate), distinct prompt heads / finals, chat template applied, decode steps recorded, positional token agreement, expert Jaccard | low-text-overlap, cache scope, union per layer-step, capacity per layer, r(s,l) = union / capacity, forced-admission decomposition.

*Oracle-field values computed here are prefetch-free residency results under our replay contract and are not comparable with the prefetch-inclusive hit rates reported by MoE-Beyond.*

Divergence recorded without attribution: the public text (§4.1.2) describes recording “each token in the generated sequences”; the published collection scripts run one prefill forward pass per prompt and record no generated token.
