# MoE-Beyond — reporting block with the public artifact and the released package

```
Execution model
  event unit .......................... per-access (probe A2, five seeds)
  retention decision .................. immediate
  intra-event order (if immediate) .... ascending id (40118 of 40118 rows ascending in the replayed files)
  conformance trace ................... no (none in the public repository)

Workload
  templates per category .............. NA(no category labels in the public artifact)
  distinct prompt heads / finals ...... 100 / 100
  chat template applied ............... no
  decode steps recorded ............... 0
  position-locked cohorts ............. no (B = 1)
  unique generated sequences .......... NA(no generated tokens are recorded; input sequences 48 / 48 unique)
  positional token agreement .......... mean 0.134298, p95 0.285714, scope input sequences, first 48 records; post-hoc decomposition in C_exploratory_positional (D-004)
  expert Jaccard | low-text-overlap ... 0.147371
  effect stable across position bands ... NA(no category labels or matched template arm)

Regime
  experts N, top-k, layers ............ 64 / 6 / 26
  residency fraction rho .............. 0.1
  cache scope ......................... global
  union per layer-step ................ mean 6, p95 6
  capacity per layer .................. 166 blocks shared by all layers (global; round(1664 x 0.1))
  r(s,l) = union / capacity ........... mean 0.0361446, p95 0.0361446, fraction_gt_1 0
  concurrency ......................... 1
  service discipline .................. one prompt replayed at a time; cache rebuilt for every prompt
  miss denominator .................... per expert access, pre-dedup (no dedup at B = 1)
  dedup credited to policy ............ no (B = 1, nothing to deduplicate)
  static fit source ................... n/a (no static policy in the reported comparison)
  static quota rule ................... n/a
  initial pinned load counted ......... n/a; each prompt starts from a random pre-fill and its first 10 tokens are not counted

Oracle
  offline bound reported .............. not in the study; this package supplies a prefetch-free Belady bound (analysis D), not comparable with the prefetch-inclusive rates
  forced-admission decomposition ...... admission_share 0.0135278, contract prefetch-free, E1, rho 0.10, global, per-request reset; not comparable with prefetch-inclusive rates, future_victim_share 0.986472
  absolute bytes per output token ..... NA(no output tokens are generated and expert byte sizes are not in the artifact)
  bandwidth budget assumed ............ DECLARE
```

| field | class | source |
|---|---|---|
| event unit | computed | results/A_contract.json sha256 8e99a6aa6ce5bddeb320f5251b77177c2418a14dff5890cdfae2c946576c50e6 |
| retention decision | computed | probe A2; results/A_contract.json sha256 8e99a6aa6ce5bddeb320f5251b77177c2418a14dff5890cdfae2c946576c50e6 |
| intra-event order (if immediate) | computed | canonical/test-e1-source sha256 e13cdf4aaece26c830b0552dd33623dbc8feaa9f3698db666f7123ed0f9087ef |
| conformance trace | computed | INPUTS.sha256 sha256 bc8213a0a58672ab42ba031801de3028345d3865619925019ff53b45e2a6512c |
| templates per category | NA | — |
| distinct prompt heads / finals | computed | results/C_workload.json sha256 42bd7984fe6a4c76f5bf365bb7de78e7599d7b871e686d4581a44fd5ec95dc25 |
| chat template applied | computed | collection scripts; results/C_workload.json sha256 42bd7984fe6a4c76f5bf365bb7de78e7599d7b871e686d4581a44fd5ec95dc25 |
| decode steps recorded | computed | collection scripts; results/C_workload.json sha256 42bd7984fe6a4c76f5bf365bb7de78e7599d7b871e686d4581a44fd5ec95dc25 |
| position-locked cohorts | computed | results/A_contract.json sha256 8e99a6aa6ce5bddeb320f5251b77177c2418a14dff5890cdfae2c946576c50e6 |
| unique generated sequences | NA | — |
| positional token agreement | computed | results/C_workload.json sha256 42bd7984fe6a4c76f5bf365bb7de78e7599d7b871e686d4581a44fd5ec95dc25 |
| expert Jaccard \| low-text-overlap | computed | results/C_workload.json sha256 42bd7984fe6a4c76f5bf365bb7de78e7599d7b871e686d4581a44fd5ec95dc25 |
| effect stable across position bands | NA | — |
| experts N, top-k, layers | computed | event trace events.safetensors sha256 e52f4782889d401091798e87c88a8cb28956cbacffae5cd78f03f1a9e2471d10 |
| residency fraction rho | computed | event trace events.safetensors sha256 e52f4782889d401091798e87c88a8cb28956cbacffae5cd78f03f1a9e2471d10 |
| cache scope | computed | event trace events.safetensors sha256 e52f4782889d401091798e87c88a8cb28956cbacffae5cd78f03f1a9e2471d10 |
| union per layer-step | computed | event trace events.safetensors sha256 e52f4782889d401091798e87c88a8cb28956cbacffae5cd78f03f1a9e2471d10 |
| capacity per layer | computed | event trace events.safetensors sha256 e52f4782889d401091798e87c88a8cb28956cbacffae5cd78f03f1a9e2471d10 |
| r(s,l) = union / capacity | computed | event trace events.safetensors sha256 e52f4782889d401091798e87c88a8cb28956cbacffae5cd78f03f1a9e2471d10 |
| concurrency | computed | event trace events.safetensors sha256 e52f4782889d401091798e87c88a8cb28956cbacffae5cd78f03f1a9e2471d10 |
| service discipline | computed | results/A_contract.json sha256 8e99a6aa6ce5bddeb320f5251b77177c2418a14dff5890cdfae2c946576c50e6 |
| miss denominator | computed | results/A_contract.json sha256 8e99a6aa6ce5bddeb320f5251b77177c2418a14dff5890cdfae2c946576c50e6 |
| dedup credited to policy | computed | results/A_contract.json sha256 8e99a6aa6ce5bddeb320f5251b77177c2418a14dff5890cdfae2c946576c50e6 |
| static fit source | computed | results/A_contract.json sha256 8e99a6aa6ce5bddeb320f5251b77177c2418a14dff5890cdfae2c946576c50e6 |
| static quota rule | computed | results/A_contract.json sha256 8e99a6aa6ce5bddeb320f5251b77177c2418a14dff5890cdfae2c946576c50e6 |
| initial pinned load counted | computed | results/A_contract.json sha256 8e99a6aa6ce5bddeb320f5251b77177c2418a14dff5890cdfae2c946576c50e6 |
| offline bound reported | computed | results/D_decomposition.json sha256 66fe9104a560d0c9e7d3a372a864f861c0f56f328212ac2ce91d9909e2777b0a |
| forced-admission decomposition | computed | results/D_decomposition.json sha256 66fe9104a560d0c9e7d3a372a864f861c0f56f328212ac2ce91d9909e2777b0a |
| absolute bytes per output token | NA | — |
| bandwidth budget assumed | DECLARE | only the original authors can state the bandwidth they assumed |

Fields carrying information (computed or text-cited): 25 of 30.
