# MoE-Beyond — reporting block from the public text only

```
Execution model
  event unit .......................... token-by-token replay of each test prompt
  retention decision .................. NR
  intra-event order (if immediate) .... NR
  conformance trace ................... no

Workload
  templates per category .............. NR
  distinct prompt heads / finals ...... NR
  chat template applied ............... NR
  decode steps recorded ............... NR
  position-locked cohorts ............. no (batch size one)
  unique generated sequences .......... NR
  positional token agreement .......... NR
  expert Jaccard | low-text-overlap ... NR
  effect stable across position bands ... NR

Regime
  experts N, top-k, layers ............ 64 routed (+2 shared) / 6 / 27
  residency fraction rho .............. 0.10 headline; capacity swept
  cache scope ......................... NR
  union per layer-step ................ NR
  capacity per layer .................. NR
  r(s,l) = union / capacity ........... NR
  concurrency ......................... 1
  service discipline .................. one prompt replayed at a time
  miss denominator .................... per ground-truth expert activation
  dedup credited to policy ............ no (batch size one)
  static fit source ................... n/a (only MoE-Infinity is compared)
  static quota rule ................... n/a (only MoE-Infinity is compared)
  initial pinned load counted ......... n/a (only MoE-Infinity is compared)

Oracle
  offline bound reported .............. no
  forced-admission decomposition ...... NR
  absolute bytes per output token ..... NR
  bandwidth budget assumed ............ NR
```

| field | class | source |
|---|---|---|
| event unit | paper | §4.1.4 Simulator |
| retention decision | NR | not reported in the public text |
| intra-event order (if immediate) | NR | not reported in the public text |
| conformance trace | paper | no conformance or reference trace appears in §4.1.4 |
| templates per category | NR | not reported in the public text |
| distinct prompt heads / finals | NR | not reported in the public text |
| chat template applied | NR | not reported in the public text |
| decode steps recorded | NR | not reported in the public text |
| position-locked cohorts | paper | Abstract; §5 Limitations |
| unique generated sequences | NR | not reported in the public text |
| positional token agreement | NR | not reported in the public text |
| expert Jaccard \| low-text-overlap | NR | not reported in the public text |
| effect stable across position bands | NR | not reported in the public text |
| experts N, top-k, layers | paper | §4.1.1 Models; §4.1.4 Simulator |
| residency fraction rho | paper | Abstract; §4.2.1 |
| cache scope | NR | not reported in the public text |
| union per layer-step | NR | not reported in the public text |
| capacity per layer | NR | not reported in the public text |
| r(s,l) = union / capacity | NR | not reported in the public text |
| concurrency | paper | Abstract; §5 Limitations |
| service discipline | paper | §4.1.4 Simulator |
| miss denominator | paper | §4.1.4; §4.2.1 GPU Cache Hit Rate |
| dedup credited to policy | paper | Abstract; §5 Limitations |
| static fit source | paper | §4.1.3 Baseline |
| static quota rule | paper | §4.1.3 Baseline |
| initial pinned load counted | paper | §4.1.3 Baseline |
| offline bound reported | paper | no offline optimum in §4.2 Results |
| forced-admission decomposition | NR | not reported in the public text |
| absolute bytes per output token | NR | not reported in the public text |
| bandwidth budget assumed | NR | not reported in the public text |

Fields carrying information (computed or text-cited): 13 of 30.
