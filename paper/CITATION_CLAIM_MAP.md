# Citation and claim map

Frozen for the arXiv draft on 2026-08-02. “Version” is the version actually
audited, not necessarily the newest version that may exist later. Recheck on
submission day.

| Key | Claim supported in this paper | Frozen source / evidence boundary |
|---|---|---|
| `shazeer2017sparselygated` | sparse gating selects a small subset of experts | arXiv:1701.06538v1, abstract and method |
| `fedus2022switch` | sparse expert activation scales parameter count while controlling active compute | arXiv:2101.03961v3 / JMLR 23(120) |
| `belady1966replacement` | furthest-future-use replacement is an offline reference | IBM Systems Journal 5(2), DOI frozen in BibTeX |
| `denning1968workingset` | working set is windowed and differs from cumulative distinct footprint | CACM 11(5), DOI frozen in BibTeX |
| `yang2025qwen3` | Qwen3 family includes MoE models; official family description | arXiv:2505.09388v1; exact local snapshot remains in route manifest |
| `muennighoff2025olmoe` | OLMoE architecture/model family | arXiv:2409.02060v2; exact local revision remains in route manifest |
| `ibm2024granite31` | Granite 3.1 MoE model family | IBM official announcement; exact local revision remains in route manifest |
| `mlx2025` | software framework and cited local version | official MLX repository; version 0.32.0 in collection manifest |
| `eliseev2023mixtraloffloading` | end-to-end MoE expert offloading system | arXiv:2312.17238v1 |
| `xue2025moeinfinity` | sparsity-aware expert cache/offloading system | arXiv:2401.14361v3 |
| `tang2024hobbit` | mixed-precision expert offloading | arXiv:2411.01433v2 |
| `hoang2026specmd` | hook-based framework and Least-Stale policy | arXiv:2602.03921v1 |
| `zhu2026dali` | workload-aware offloading and next-expert prefetching | arXiv:2602.03495v1 |
| `chen2025spmoe` | expert prefetching combined with speculative decoding | arXiv:2510.10302v2 |
| `fang2025fate` | cross-layer next-expert prediction/prefetching | arXiv:2502.12224v2; do not attribute its fallback mode as lossless |
| `hwang2024pregated` | pre-gated architecture/system co-design | arXiv:2308.12066v3 |
| `du2024sidamoe` | data-aware MoE serving and expert activation prediction | arXiv:2310.18859v2 |
| `gavhane2025moebeyond` | activation prediction plus a batch-one trace cache simulation | arXiv:2508.17137v1; wording limited to public text audited in Appendix A |
| `bai2023longbench` | provenance of the LongBench-derived probe records | arXiv:2308.14508 plus dataset manifest |
| `yan2024bfcl` | provenance of function-calling probe records | arXiv:2402.11717 plus dataset manifest |
| `lei2024spider20` | provenance of enterprise text-to-SQL probe records | arXiv:2411.07763 plus dataset manifest |
| `guha2023legalbench` | provenance of legal probe records | arXiv:2308.11462 plus task-level provenance in dataset manifest |
| `vargas2019threew` | provenance of Petrobras 3W industrial records | journal article and frozen repository revision |
| `apacheofbiz2026` | provenance of OFBiz demo entities | official repository, revision and NOTICE frozen in source manifest |
| `raffel2020t5` | C4 corpus provenance | arXiv:1910.10683; does not by itself license the derived public route artifact |
| `allenai2024mixtralroutes` | provenance of the external Mixtral/C4 route artifact | public dataset page; exact prefix hash in local manifest |

## Citation discipline

1. A model paper does not replace an exact snapshot hash.
2. A benchmark paper does not replace task-level source provenance or licence.
3. A system paper is cited for its reported mechanism, not for an unreported
   replay contract.
4. The ten-paper audit is a reporting audit, not an independent replication of
   any paper's speedup.
5. All “v1/v2/v3” assertions must be rechecked against the official arXiv
   abstract pages on the actual submission date.

