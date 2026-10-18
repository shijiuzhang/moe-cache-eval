# Deviations from the protocol and the pre-registration

The pre-registration (`PREREG.md`) is locked by `PREREG.lock` and is not edited.
Every change or clarification is appended here, in order.

## D-001 — Location of the reporting-block generator (protocol path, not PREREG)

- Recorded: 2026-10-18, during stage 2.
- Results read before this change: **none**. No analysis script had run, and `results/` did not exist.
- Protocol §4.4 names `tools/report_block.py` (`python -m tools.report_block`).
- Implemented instead as the package module `moe_controller/report_block.py` (`python -m moe_controller.report_block`).
- Reason: the reviewer asks what a reader can do with the *released* artifact. A top-level `tools` package
  is not included in the built distribution (`pyproject.toml` packages only `moe_controller*` and `oicap*`),
  so the generator would be absent from what readers install. The change is a new file;
  no existing module is modified (R1).

## D-002 — Seeding of the reproduction runs (clarification of PREREG P3)

- Recorded: 2026-10-18, during stage 2.
- Results read before this change: **none**. Only the harness smoke test on a non-probe input had run.
- PREREG P3 says “5 个种子，每次调用前执行 `np.random.seed(s)`”. For P3, “调用” could mean either
  each per-file replay call or each full reproduction run.
- Fixed interpretation: seed **once per full reproduction run**, immediately before the loop over the 100 test files.
  - Reason: the original program draws every file's random cache pre-fill from one unseeded RNG stream.
    Seeding once per run keeps that structure and makes it reproducible.
  - Seeding before every file would give all 100 prompts the identical pre-fill, which the original never does.
- For P1 the two readings coincide, because each probe is a single call.

## D-003 — R6 compares safetensors files by content, not by raw file hash (approved by the author 2026-10-18)

- Recorded: 2026-10-18, during stage 2.
- Results read before this change: **none**.
- **Observation.** R6(b) failed for `controller-probe-v0.1.3-olmoe-decode64-fcfs-b8-v1`: the regenerated
  `events.safetensors` had SHA-256 `22e71a14a518cd937188a01bb69930c3048e77ec1e6f9b53daa810da5fc1a316`
  against the frozen `5d31a0f36bff49237bff8c6ca9648a8cb2099f51855e92b0bc851afe2ac93a15`.
  The stage-0 baseline regeneration had matched.
- **Diagnosis.**
  - All ten event arrays are equal, and the two files have the same length.
  - The 43 differing bytes all lie in the safetensors header JSON. The two `__metadata__` keys are written as
    `{"schema", "schema_version"}` in the frozen file and as `{"schema_version", "schema"}` in the regenerated one.
  - Reproduced in isolation: saving one fixed tensor with the same metadata in six separate processes produced
    two different file hashes, `293893447fa1ad48…` (4 runs) and `ddf7ac4c2e3039b9…` (2 runs),
    while the payload hash was always `15ec7bf0b50732b4…`. These three are 16-character prefixes printed
    by the throw-away demonstration; the temporary files were not retained, so no full hash is claimed.
    The two full hashes above were re-measured with `shasum -a 256` on the physical files.
  - So safetensors (0.8.0) writes its metadata keys in a per-process random order. Identical content yields one
    of two file hashes. The stage-0 match was one of the two outcomes, not evidence of byte determinism.
- **Change.** R6(b) and R6(c) compare `events.safetensors` by content: the parsed header (names, dtypes, shapes,
  data offsets, metadata dictionary) must be equal, **and** the SHA-256 of the tensor payload must be equal.
  Any change to any tensor byte or header field still fails. R6(b) additionally checks that the frozen file
  still matches its own manifest hash exactly.
- **Verification.** With this criterion R6 passed in three separate processes.
- **Wider note for the author.** Any regeneration of a package event trace reproduces the published file hash
  with only about even odds. For canonical traces in this case study, `HASHES.txt` file digests are therefore
  not rebuild-stable; payload digests are.

## D-004 — Post-hoc decomposition of the route-side positional agreement (approved by the author 2026-10-18)

- Recorded: 2026-10-18, during stage 3, **after** reading the analysis C result. This is a post-hoc addition.
- **Trigger.** The pre-registered §5.8 detector reported `flag = true` on the first 48 test records.
  The trigger was positional token agreement p95 0.2857, against a threshold of 0.05.
  The prompt side showed 100 distinct heads, 100 distinct final lines and zero word 5-gram overlap.
  Because a contamination flag could be read as a statement about the reported hit rates,
  the result was held and given to the author under protocol §7.
- **Addition.** `exploratory_C_positional.py` writes `results/C_exploratory_positional.{json,md}`,
  which are labelled post-hoc. It decomposes the agreement: position 0 (a shared BOS token) versus the rest,
  and the most common position-1 tokens.
- **What does not change.** The pre-registered flag (`true`) and the frozen P5 sentence in `C_workload.md`
  stand as generated. The exploratory numbers are reported beside them and never in their place.
- **Reporting decision (author).**
  1. Report `flag = true` with the frozen P5 sentence, followed by the factual description of where the
     agreement sits.
  2. Report the position-0-excluded figures as post-hoc.
  3. State the detector's length sensitivity as a limitation of the package's own tool. Its threshold was
     validated on 512-token sequences; these records have 3–38 tokens.

## D-005 — Static under the per-request reset column (clarification of PREREG §3)

- Recorded: 2026-10-18, during stage 3, **before** any analysis D result existed.
  Results of A–C had been read; none of them bears on this choice.
- PREREG fixes Static to `per_layer` only (`global` is NA), but does not state how Static is treated
  under start state (ii), the per-request reset alignment column.
- **Fixed.** Static is reported only under start state (i). Under (ii) it is
  `NA(per-request reset would re-load the pinned set for every request)`.
  - The package counts a static policy's initial pinned load in its transfers
    (`transferred_blocks = misses + initial_load_blocks`; reporting-block field "initial pinned load counted").
  - Resetting per request would charge that load 100 times. That matches neither a deployment nor the
    third-party contract, whose own comparison has no static policy.
  - Static does not enter the best-causal choice, so no gap or share changes.
- **Implementation note (not a deviation).** E1 traces built by the package's FCFS converter mark event
  request indices with the sentinel −1. For the per-request reset column, analysis D recovers each
  event's request from `schedule.jsonl` (B = 1: one active request per scheduler step) before using
  `subset_event_trace`.

## D-006 — The P2 template's equivalence implication is invalid (audit F1)

- Recorded: 2026-10-19, after the independent audit of commit `4869568` (`docs/revision/MOE_BEYOND_EXPERIMENT_AUDIT_20261019.md`, F1).
  All results had been read. The audit's private recomputation was **not** seen by the implementer.
- **Error.** The PREREG P2 template concludes that if every event's expert set fits within capacity,
  “in-event eviction cannot occur; whatever replay semantics the simulator uses, its counts there coincide
  with the event-atomic contract. Axis I does not operate in this setting.” The implication is false.
  Under per-access LRU, a miss can evict a block that was resident at event start and is needed **later in the
  same event**, even when the whole event fits.
- **Hand-derived counterexample.** Derived before any execution; it becomes a regression control:
  - setup: one layer, capacity 2, LRU, per-event access in ascending expert id;
  - events {1, 3} then {0, 1}; both fit, since |E| = 2 ≤ 2;
  - per-access: event 2 misses 0 (evicting 1), then misses 1 (evicting 3) → **4 misses, 0 hits**;
  - event-atomic: block 1 is resident at the start of event 2 → **3 misses, 1 hit**.
- **What stands.** The measured capacity fractions, the probe-based contract classification (per-access)
  and the reproduction results are unchanged.
- **What changes.**
  - The all-fit result is reported only as a capacity observation.
  - The over-capacity wording changes from “affects the counts” to “can affect the counts”.
  - “Axis I does not operate” and every count-equivalence claim are removed from every surface.
  - Replacement sentences:
    - **All fit:** “At {setting}, every event's expert set fits within capacity. This is a capacity
      observation; it does not by itself establish equal counts under per-access and event-atomic replay,
      because a per-access miss can evict a resident expert needed later in the same event.”
    - **Over capacity:** “At {setting}, a fraction {f} of events exceed capacity; in that setting the replay
      contract can affect the counts and should be declared (checklist A1–A2).”
    - **Contract:** “The simulator's executed contract is per-access (probe A2); its reported counts are
      per-access counts, and setting them beside an event-atomic study requires declaring this
      (checklist A1–A2).”
- This makes no statement about the direction or size of any effect on the published comparison.

## D-007 — Reporting-block target, classes and counting rule (audit F2)

- Recorded: 2026-10-19, after the audit (F2), before regenerating E.
  The previously reported E outputs are archived under `history/results_E_d030306/`.
- **Target.** Every one of the 30 fields describes the **original reported configuration**: the published
  simulator's contract, rho = 0.10, global scope, B = 1, per-token replay unit, prefetch included.
  Results obtained under the package's own contract (analysis D: atomic, prefetch-free, cold-start) are
  **not** entries of the block. They are listed in a separate “package analyses” section and never counted.
- **Classes, one rule for both modes.**
  - `answered` — a definite value for the target, including “no” for a question about whether something
    exists or was reported.
  - `not_applicable` — the field presupposes a mechanism the target configuration does not have:
    no static policy; B = 1, so no concurrent cohorts and nothing to deduplicate; no generated tokens.
    The absence must be established by the cited source.
  - `NA` — the required information exists in neither the text nor the artifact.
  - `DECLARE` — only the original authors can state it.
  - `NR` — paper-only mode; not stated in the text.
- **Provenance**, required for `answered` and `not_applicable`: `text` (paper-only), `execution`,
  `code_inspection`, `data_inspection`, or `analyst_inference`. Every non-`text` provenance cites a SHA-256.
- **Counting.** The headline in each mode is the number of `answered` fields. `not_applicable` is reported
  as a separate count in each mode and is never added to the headline.
- **Field assignment**, fixed now:
  - `forced_admission_decomposition`: `NA` for the original contract, which is not defined under its
    prefetch-inclusive per-access replay.
  - `unique_generated_sequences` and `absolute_bytes_per_output_token`: `not_applicable` with artifacts,
    because no generated token is recorded. In paper-only mode they are `NR`, because the text describes
    generated sequences and does not establish their absence.
  - `position_locked_cohorts` and `dedup_credited_to_policy`: `not_applicable` in both modes (B = 1).
  - The three static fields: `not_applicable` in both modes.
- The package module `moe_controller.report_block` is changed to these classes (kind `computed` becomes
  `answered`, plus `not_applicable` and a provenance field), with tests.

## D-008 — Scope of the package-benefit claim (audit F3; replaces the P7 conclusion template)

- Recorded: 2026-10-19, after the audit (F3).
- The P7 template “The fields that only the package made fillable are …” and the draft sentence “each was
  obtained by executing the published artifact” overstate the evidence.
  - The comparison is paper text versus public artifact **plus** package **plus** analyst work.
  - There is no artifact-only control.
  - Several answers come from code inspection or analyst inference, not from execution.
- **Replacement template:** “From the paper text alone, {a} of the 30 reporting-block fields are answered
  ({na_a} more are established as not applicable); with the public artifact, the package and the
  documented analyst steps, {b} are answered ({na_b} not applicable). The fields answered only in the second
  mode, with their provenance, are: {list}.”
- The paper describes the concrete checks and structured outputs the workflow provides, with its manual steps
  declared. It does not claim that an ordinary simulator cannot perform them.
