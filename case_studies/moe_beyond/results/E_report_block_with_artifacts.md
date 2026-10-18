# MoE-Beyond — reporting block with the public artifact, the package and analyst steps

```
Execution model
  event unit .......................... per-access (probe A2, five seeds)
  retention decision .................. immediate
  intra-event order (if immediate) .... ascending id (40118 of 40118 replayed rows ascending; accessed in list order)
  conformance trace ................... no (none in the public repository)

Workload
  templates per category .............. NA(no category labels in the public artifact)
  distinct prompt heads / finals ...... 100 / 100
  chat template applied ............... no
  decode steps recorded ............... 0
  position-locked cohorts ............. n/a (B = 1; no concurrent requests)
  unique generated sequences .......... n/a (no generated token is recorded)
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
  miss denominator .................... per expert access, pre-dedup
  dedup credited to policy ............ n/a (B = 1; nothing to deduplicate)
  static fit source ................... n/a (no static policy in the simulator)
  static quota rule ................... n/a (no static policy in the simulator)
  initial pinned load counted ......... n/a (no static policy in the simulator)

Oracle
  offline bound reported .............. no
  forced-admission decomposition ...... NA(not defined for the original prefetch-inclusive per-access contract; a package-contract analysis is reported separately)
  absolute bytes per output token ..... n/a (no generated token is recorded)
  bandwidth budget assumed ............ DECLARE
```

| field | class | provenance | source |
|---|---|---|---|
| event unit | answered | execution | results/A_contract.json sha256 8e99a6aa6ce5bddeb320f5251b77177c2418a14dff5890cdfae2c946576c50e6 |
| retention decision | answered | execution | probe A2; results/A_contract.json sha256 8e99a6aa6ce5bddeb320f5251b77177c2418a14dff5890cdfae2c946576c50e6 |
| intra-event order (if immediate) | answered | data_inspection | canonical/test-e1-source sha256 e13cdf4aaece26c830b0552dd33623dbc8feaa9f3698db666f7123ed0f9087ef; cache_simulator/infinity_moe_sim.py sha256 734891c7b3eed32416d6d806e354d7801363175ce12940906cdb8a0898fa9dfa lines 242-251 |
| conformance trace | answered | analyst_inference | repository inventory INPUTS.sha256 sha256 bc8213a0a58672ab42ba031801de3028345d3865619925019ff53b45e2a6512c |
| templates per category | NA | — | — |
| distinct prompt heads / finals | answered | execution | results/C_workload.json sha256 42bd7984fe6a4c76f5bf365bb7de78e7599d7b871e686d4581a44fd5ec95dc25 |
| chat template applied | answered | code_inspection | expert_activation_scripts/generate_deepseek_logs_eamc.py sha256 17458e1904928fb8c381286cea7ef508b33b685a7d6910a2ac630b414525077e line 122 |
| decode steps recorded | answered | code_inspection | expert_activation_scripts/generate_deepseek_logs_eamc.py sha256 17458e1904928fb8c381286cea7ef508b33b685a7d6910a2ac630b414525077e lines 122-124 |
| position-locked cohorts | not_applicable | code_inspection | cache_simulator/infinity_moe_sim.py sha256 734891c7b3eed32416d6d806e354d7801363175ce12940906cdb8a0898fa9dfa lines 284-292 (one test file per replay call) |
| unique generated sequences | not_applicable | code_inspection | expert_activation_scripts/generate_deepseek_logs_eamc.py sha256 17458e1904928fb8c381286cea7ef508b33b685a7d6910a2ac630b414525077e lines 122-124 |
| positional token agreement | answered | execution | results/C_workload.json sha256 42bd7984fe6a4c76f5bf365bb7de78e7599d7b871e686d4581a44fd5ec95dc25 |
| expert Jaccard \| low-text-overlap | answered | execution | results/C_workload.json sha256 42bd7984fe6a4c76f5bf365bb7de78e7599d7b871e686d4581a44fd5ec95dc25 |
| effect stable across position bands | NA | — | — |
| experts N, top-k, layers | answered | execution | event trace events.safetensors sha256 e52f4782889d401091798e87c88a8cb28956cbacffae5cd78f03f1a9e2471d10 |
| residency fraction rho | answered | code_inspection | cache_simulator/infinity_moe_sim.py sha256 734891c7b3eed32416d6d806e354d7801363175ce12940906cdb8a0898fa9dfa lines 81-90 and 275 (one global cache; int(1664 x 0.10)) |
| cache scope | answered | code_inspection | cache_simulator/infinity_moe_sim.py sha256 734891c7b3eed32416d6d806e354d7801363175ce12940906cdb8a0898fa9dfa lines 81-90 and 275 (one global cache; int(1664 x 0.10)) |
| union per layer-step | answered | execution | event trace events.safetensors sha256 e52f4782889d401091798e87c88a8cb28956cbacffae5cd78f03f1a9e2471d10 |
| capacity per layer | answered | execution | event trace events.safetensors sha256 e52f4782889d401091798e87c88a8cb28956cbacffae5cd78f03f1a9e2471d10 |
| r(s,l) = union / capacity | answered | execution | event trace events.safetensors sha256 e52f4782889d401091798e87c88a8cb28956cbacffae5cd78f03f1a9e2471d10 |
| concurrency | answered | execution | event trace events.safetensors sha256 e52f4782889d401091798e87c88a8cb28956cbacffae5cd78f03f1a9e2471d10 |
| service discipline | answered | execution | contract check in results/A_contract.json sha256 8e99a6aa6ce5bddeb320f5251b77177c2418a14dff5890cdfae2c946576c50e6 |
| miss denominator | answered | execution | denominator check in results/A_contract.json sha256 8e99a6aa6ce5bddeb320f5251b77177c2418a14dff5890cdfae2c946576c50e6 |
| dedup credited to policy | not_applicable | code_inspection | cache_simulator/infinity_moe_sim.py sha256 734891c7b3eed32416d6d806e354d7801363175ce12940906cdb8a0898fa9dfa lines 284-292 |
| static fit source | not_applicable | code_inspection | cache_simulator/infinity_moe_sim.py sha256 734891c7b3eed32416d6d806e354d7801363175ce12940906cdb8a0898fa9dfa |
| static quota rule | not_applicable | code_inspection | cache_simulator/infinity_moe_sim.py sha256 734891c7b3eed32416d6d806e354d7801363175ce12940906cdb8a0898fa9dfa |
| initial pinned load counted | not_applicable | code_inspection | cache_simulator/infinity_moe_sim.py sha256 734891c7b3eed32416d6d806e354d7801363175ce12940906cdb8a0898fa9dfa |
| offline bound reported | answered | code_inspection | cache_simulator/infinity_moe_sim.py sha256 734891c7b3eed32416d6d806e354d7801363175ce12940906cdb8a0898fa9dfa (no offline optimum) |
| forced-admission decomposition | NA | — | — |
| absolute bytes per output token | not_applicable | code_inspection | expert_activation_scripts/generate_deepseek_logs_eamc.py sha256 17458e1904928fb8c381286cea7ef508b33b685a7d6910a2ac630b414525077e lines 122-124 |
| bandwidth budget assumed | DECLARE | — | only the original authors can state the bandwidth they assumed |

Answered: 19 of 30. Established as not applicable (counted separately): 7.
