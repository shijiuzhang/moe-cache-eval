# Clean-checkout verification

- Date: 2026-10-19
- Commit: `855f0ab` cloned into a fresh directory; its committed `results/` removed before the run.
- Isolation: no file from the author's laboratory directory was read. Network was used for PyPI, GitHub and arXiv.
- Machine: Apple M4 Pro, 24 GB, macOS 26.5.1.
- `uv sync` used `--no-config` because the user-level `uv.toml` points at a proxy that was not running.

## Run log

```
HEAD 855f0ab
paper html ef57960064f88365
non-OK inputs: 0
build_canonical ok 85s
analysis_A ok 36s
analysis_B ok 0s
analysis_C ok 12s
exploratory_C_positional ok 1s
analysis_D ok 610s
analysis_E ok 2s
make_macros ok 0s
ALL-DONE
```

## Comparison with the committed results

Numbers are compared for exact equality.
File hashes are not compared, because they can differ through timestamps, paths and the safetensors key order (D-003).

```
MATCH   A probe A0
MATCH   A probe A1
MATCH   A probe A2
MATCH   A executed contract
MATCH   A P2 fractions
MATCH   A P3 moe_beyond_predicted per-seed
MATCH   A P3 moe_beyond_predicted files
MATCH   A P3 moe_infinity_eamc per-seed
MATCH   A P3 moe_infinity_eamc files
MATCH   B rows
MATCH   B placement
MATCH   C route summary
MATCH   C prompt side
MATCH   C exploratory
MATCH   D rows (all 36)
MATCH   E paper_only_answered
MATCH   E paper_only_not_applicable
MATCH   E with_artifacts_answered
MATCH   E with_artifacts_not_applicable
MATCH   E answered_only_with_artifacts
MATCH   E rows
MATCH   macros (all values)
22 of 22 checks match
```
