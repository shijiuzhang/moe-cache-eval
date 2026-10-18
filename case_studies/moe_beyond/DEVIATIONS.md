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
