# How to use the artifact: a third-party trace through the diagnostic chain

Revised after the 2026-10-19 audit (F4); previous version in `history/paper_d030306/`.
This is the dependency-ordered sequence used for the MoE-Beyond case study, followed by
the extension points. Run every command from the repository root. Each step's prerequisite
is the step above it.

## 0. Interpreters and conventions

```bash
# Package interpreter: the locked environment of this repository (Python 3.12).
uv sync --frozen
PY=.venv/bin/python

# Third-party interpreter: a separate environment that only ever runs the third-party
# simulator. The package never imports third-party code.
/opt/homebrew/bin/python3.12 -m venv third_party/.venv-moebeyond     # any CPython 3.12
third_party/.venv-moebeyond/bin/python -m pip install pandas numpy scipy scikit-learn
TPY=third_party/.venv-moebeyond/bin/python
```

- The recorded run used pandas 3.0.6, numpy 2.5.4, scipy 1.18.1 and scikit-learn 1.9.1 for `TPY`.
- Every analysis script refuses to overwrite its outputs.
- Every analysis script refuses to run unless `PREREG.lock` verifies.

## 1. Pin the third-party artifact (case study inputs already frozen)

```bash
mkdir -p third_party && cd third_party
GIT_LFS_SKIP_SMUDGE=1 git clone https://github.com/ngavhane/moe-beyond.git
git -C moe-beyond checkout 47031eefc7808e996ecd5c01d7ed90aa32e32514
cd ..
(cd third_party/moe-beyond && shasum -a 256 -c ../../case_studies/moe_beyond/INPUTS.sha256 | grep -vc ': OK$')
```

The last command prints `0` when all 2206 frozen inputs match.
`third_party/` is git-ignored; only the hash list is tracked.

For a new study, freeze `INPUTS.sha256` the same way, then write and commit `PREREG.md` and record its hash
in `PREREG.lock`. `case_studies/moe_beyond/COMMANDS.md` shows the exact commands.

## 2. Normalize the trace

```bash
$PY -I case_studies/moe_beyond/build_canonical.py
```

- Validates every third-party row and refuses to write output if any violation is counted.
- Writes E1 (per-token) events at B = 1 and constructed B = 2, 4, 8 streams through the package's FCFS
  builder, and E2 (whole-prefill) events.
- Output: `canonical/` (git-ignored), `canonical/HASHES.txt` (raw file hashes) and
  `canonical/CONTENT_HASHES.txt` (rebuild-stable safetensors digests).
- Recorded run: about 78 s, peak resident memory 6.46 GB on an Apple M4 Pro with 24 GB.
  This covers parsing 2200 CSV files and every conversion.

## 3. Execution contract, probes and reproduction (analysis A)

```bash
$PY -I case_studies/moe_beyond/analysis_A.py
```

- Writes the probe files, then calls `TPY -I case_studies/moe_beyond/thirdparty_harness.py` with
  `probe`, `confirm` and `reproduce`.
- Classifies the executed replay contract, measures event fit and reproduces both reported hit rates.
- Output: `results/A_probes/`, `results/A_*_raw.json`, `results/A_contract.{json,md}`.
- Recorded run: about 15 s.

`$PY -I case_studies/moe_beyond/analysis_A.py --render-only` rebuilds `A_contract.md` from the stored
JSON without executing anything.

## 4. Regime (analysis B)

```bash
$PY -I case_studies/moe_beyond/analysis_B.py
```

- Computes r(s,l): mean, p95 and the fraction of events over quota, together with the uniform-routing
  null, then places the setting against Table 11.
- Output: `results/B_regime.{json,md}`. Recorded run: under 1 s.

## 5. Workload construction (analysis C)

```bash
$PY -I case_studies/moe_beyond/analysis_C.py
$PY -I case_studies/moe_beyond/exploratory_C_positional.py    # post hoc, DEVIATIONS D-004
```

- Runs the prompt-side audit and the §5.8 route detector, both unchanged.
- Output: `results/C_workload.{json,md}` and `results/C_exploratory_positional.{json,md}`.
  The detector's own files stay in `canonical/C_workload_local/`.

## 6. Package-contract residency analysis (analysis D)

```bash
$PY -I case_studies/moe_beyond/analysis_D.py
```

- Event-atomic replay of every policy, Belady and forced-admit Belady, over five tie seeds.
- Output: `results/D_decomposition.{json,md}`.
  Every table states that the results are not comparable with prefetch-inclusive hit rates.
- Read the admission and future-victim shares only where m_F ≤ m_c.
- Recorded run: 613 s, peak resident memory 1.64 GB.
  Most of that time is the per-request-reset column, which simulates each of the 100 requests separately.

## 7. Reporting block (analysis E)

```bash
$PY -I case_studies/moe_beyond/analysis_E.py
```

- Depends on A, C and D.
- Fills both 30-field blocks for the published configuration through the package command
  `python -m moe_controller.report_block`: one from the paper text only, and one from the artifact,
  the package and the analyst steps. Each value carries its class and provenance.
- Results under the package's own contract are listed separately and are not counted.
- Output: `results/E_*`.

## 8. Paper numbers and report

```bash
$PY -I case_studies/moe_beyond/make_macros.py     # paper/case_study_macros.tex from results/*.json
$PY -I case_studies/moe_beyond/make_report.py     # REPORT.md
```

There is **no single command that regenerates every table of the paper**. These two commands regenerate
only the case-study macros and report. The paper's other tables come from their own scripts and
manifests.

## 9. Regression

```bash
$PY -I case_studies/moe_beyond/regress.py
```

- Checks the reference trace (12 / 18), content-equal regeneration of two frozen paper conditions,
  a canonical re-read, and both test suites.
- Check (b) reads the frozen paper traces from the author's laboratory directory
  (`regress.py`, constant `LAB_ROOT`). It is not portable to a fresh checkout without those traces.

## Extension points

**Normalized trace.** `moe_controller.events.EventTrace`, saved and loaded with
`save_event_trace` / `load_event_trace`. Per event it stores:

- `request_indices`, `scheduler_steps`, `forward_cycles`, `phases` (prefill or decode), `layer_ids`,
  `token_counts`;
- `offsets` into the per-access arrays `expert_ids` (the event's distinct experts),
  `assignment_counts` (pre-deduplication count) and `gate_mass`.

The manifest carries `model.num_layers`, `model.num_experts`, `model.top_k`, `conversion.batch_size` and
`counts.logical_expert_assignments_before_dedup`. The decode-route source format consumed by
`moe_controller.convert.convert_decode_trace` is documented in that function. It contains
`topk_indices[N, L, T, k]` with −1 padding, `sequence_lengths`, and per-request metadata JSONL.

**Adapter.** `case_studies/moe_beyond/adapter.py` provides:

- reading and validation: `load_raw`, `parse_prompt_file` (counts violations), `match_by_signature`;
- writing: `write_e1_source`, `build_e2_trace`, `to_moebeyond_format` (probes in the third-party format);
- `reconstruct_prompt_text`.

A new third-party format needs a new adapter with the same outputs.

**Policies.**

- The per-access simulator `simulate` takes a subclass of `CachePolicy` that implements `choose_victim`
  and optionally `record_access` / `record_eviction`. It is registered in `_policy()` and in
  `SUPPORTED_POLICIES` (`moe_controller/simulation.py`).
- The event-atomic simulator `simulate_event_atomic` has **no plugin interface**. Its retention order is
  a branch on the policy name (`moe_controller/simulation.py`, around lines 878–906), so a new atomic
  policy requires a new branch there.

**Reporting block.** `moe_controller.report_block` defines the 30 fields (`FIELDS`), the value classes,
`regime_fields` for trace-derived regime statistics, and the command-line interface used in step 7.
