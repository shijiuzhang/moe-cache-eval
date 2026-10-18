# How to use the artifact: a third-party trace through the diagnostic chain

The minimum command sequence used in the MoE-Beyond case study, taken from
`case_studies/moe_beyond/COMMANDS.md`. Paths are relative to the repository root.
`PY` is the package interpreter; `TPY` is a separate interpreter for third-party code.

1. **Install and check the package.**
   `uv sync --frozen && PY -m unittest discover -s tests`
   Builds the locked environment and runs the package tests.
   Output: a passing test report.

2. **Pin the third-party artifact and freeze its inputs.**
   `git clone <artifact> third_party/<name>`, then `shasum -a 256` every input into
   `case_studies/<study>/INPUTS.sha256`.
   Third-party code and data stay in the git-ignored `third_party/`; only hashes are tracked.
   Output: `INPUTS.sha256`.

3. **Pre-register.**
   Write `PREREG.md`, commit it, and record its hash in `PREREG.lock`.
   Every analysis script refuses to run if the lock does not verify.
   Output: `PREREG.lock`.

4. **Normalize the trace.**
   `PY -I case_studies/moe_beyond/build_canonical.py`
   The adapter validates every row, counts violations instead of dropping them, and writes the
   package's own formats. The FCFS builder `moe_controller.convert.convert_decode_trace` then
   produces per-token events at B = 1 and constructed B > 1 streams; whole-prefill events are
   written as an `EventTrace`.
   Output: `canonical/` (ignored), plus `HASHES.txt` and the rebuild-stable `CONTENT_HASHES.txt`.

5. **Run the conformance probes through the third-party simulator.**
   `TPY -I case_studies/moe_beyond/thirdparty_harness.py probe --probes <dir> --output <json>`
   The probes are the event-atomic reference trace of Section 2.5 and an in-event eviction probe,
   written in the simulator's own input format. They classify the executed replay contract.
   Output: raw probe counts. The classification is in `results/A_contract.json`.

6. **Fill the reporting block.**
   `PY -m moe_controller.report_block --events canonical/<trace> --rho 0.10 --scope global --facts <facts.json> --out-md block.md --out-json block.json`
   Fills all 30 fields of Appendix B.1. Every value is computed with its input hash cited,
   declared, or marked NA with a reason. `--paper-only` produces the text-only baseline for comparison.
   Output: `results/E_report_block_*.{md,json}`.

7. **Place the setting on the regime axis.**
   `PY -I case_studies/moe_beyond/analysis_B.py`
   Computes r(s,l), its mean and p95, the fraction of events over quota, and the uniform-routing
   null, then places the setting against Table 11.
   Output: `results/B_regime.{json,md}`.

8. **Decompose the residency gap.**
   `PY -I case_studies/moe_beyond/analysis_D.py`
   Event-atomic replay of every policy, Belady and forced-admit Belady, with recoverable gap,
   admission share and future-victim share. Read the shares only where m_F ≤ m_c.
   Output: `results/D_decomposition.{json,md}`; every table carries its non-comparability note.

9. **Regression before every change.**
   `PY -I case_studies/moe_beyond/regress.py`
   Checks the reference trace (12 / 18), content-equal regeneration of two frozen paper
   conditions, a canonical re-read, and both test suites.
   Output: a JSON report with `overall_pass`.
