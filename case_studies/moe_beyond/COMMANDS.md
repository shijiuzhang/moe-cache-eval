# Commands

Every command run for this case study, in order. Paths are relative to the repository root.
`PY` is the package interpreter `.venv/bin/python`.
`TPY` is the isolated third-party interpreter `third_party/.venv-moebeyond/bin/python`.

## Stage 0 — reconnaissance

```bash
# Pin the third-party repository without pulling LFS payloads. The global git
# proxy (127.0.0.1:7897) was not running, so it is bypassed for this one command.
mkdir -p third_party && cd third_party
GIT_LFS_SKIP_SMUDGE=1 git -c http.proxy= -c https.proxy= clone https://github.com/ngavhane/moe-beyond.git
git -C moe-beyond rev-parse HEAD   # 47031eefc7808e996ecd5c01d7ed90aa32e32514
git -C moe-beyond lfs ls-files -s  # two predictor checkpoints, not pulled

# Freeze the hash list of every third-party input (run inside third_party/moe-beyond).
{ find test_datasets/predicted_csvs test_datasets/formatted_csvs training_data_eamc \
       expert_activation_scripts/training_data_eamc -type f -name '*.csv'
  echo cache_simulator/infinity_moe_sim.py
  echo expert_activation_scripts/generate_deepseek_logs_eamc.py
  echo expert_activation_scripts/generate_deepseek_logs_v2.py
  echo expert_activation_scripts/generate_deepseek_logs.py
  echo prompt_datasets/tagged_puffin_prompts.txt
  echo README.md; } | LC_ALL=C sort | while read f; do shasum -a 256 "$f"; done \
  > ../../case_studies/moe_beyond/INPUTS.sha256
shasum -a 256 -c ../../case_studies/moe_beyond/INPUTS.sha256   # 2206 OK
```

## Stage 1 — pre-registration

```bash
git add case_studies/moe_beyond/PREREG.md && git commit    # 08938d1
shasum -a 256 case_studies/moe_beyond/PREREG.md             # written to PREREG.lock
git add case_studies/moe_beyond/PREREG.lock && git commit   # 152f151
```

## Stage 2 — tools

```bash
# Isolated environment for the third-party simulator (never imported by the package).
/opt/homebrew/bin/python3.12 -m venv third_party/.venv-moebeyond
TPY -m pip install pandas numpy scipy scikit-learn
#   -> pandas 3.0.6, numpy 2.5.4, scipy 1.18.1, scikit-learn 1.9.1, Python 3.12.13

# The harness loads and calls the simulator on a non-probe input with a hand-computed answer.
TPY -I case_studies/moe_beyond/thirdparty_harness.py smoke        # hits 2, misses 0, as expected

# Unit tests of the adapter, probe writer and content digest.
PY -m unittest discover -s case_studies/moe_beyond/tests

# Canonical traces: E1 source and E1 events (B = 1, plus constructed B = 2, 4, 8),
# and E2 events, for test and train. Output is git-ignored except the two hash lists.
PY -I case_studies/moe_beyond/build_canonical.py
#   -> 2200 third-party files, zero validation violations; peak RSS 6.46 GB; about 78 s.
#   Rebuilt twice from scratch: CONTENT_HASHES.txt identical; some raw file hashes differ (D-003).

# R6 regression check (must pass before every merge).
PY -I case_studies/moe_beyond/regress.py
```

```bash
# Reporting block (Appendix B.1), package module per D-001. Checked on the §2.5 toy trace only.
PY -m unittest tests.test_report_block              # 8 tests, incl. agreement with the paper's regime script
PY -I -m moe_controller.report_block --events <toy-trace-dir> --rho 0.5 --scope per_layer \
   --declare "chat_template_applied=<reason>" --out-md with.md --out-json with.json
PY -I -m moe_controller.report_block --paper-only --paper "concurrency=1@Abstract" \
   --out-md paper.md --out-json paper.json
```

## Stage 3 — analyses

```bash
# Analysis A (P1-P3): probes, contract-field execution checks, Axis-I applicability, reproduction.
PY -I case_studies/moe_beyond/analysis_A.py
#   internally: TPY -I thirdparty_harness.py probe|confirm|reproduce  (third-party code run in isolation)
#   -> results/A_contract.{json,md}; about 15 s; peak RSS 0.22 GB
```

```bash
# Analysis B (P4): regime statistics, uniform-routing null, placement against Table 11.
PY -I case_studies/moe_beyond/analysis_B.py      # -> results/B_regime.{json,md}; under 1 s
```
