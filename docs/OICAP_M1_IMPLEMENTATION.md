# OICAP M1 implementation checkpoint

**Date:** 2026-08-25

**Specification:** `PLATFORM_PRODUCT_SPECIFICATION_V0_1.md`

**Status:** implementation checkpoint; not yet a v0.1 release

This document maps the current code to the reviewed M1 contract. It is deliberately
not a product announcement and does not claim that all V01 acceptance criteria have
passed.

## Implemented boundary

- versioned 0.1 contract documents, normalization, workload hashing and validation;
- deterministic local JSONL selection;
- OpenAI-compatible streaming adapter with distinct first-byte, first-chunk and
  first-substantive-token anchors;
- closed-loop fixed-user execution backed by a shared queue, plus open-loop
  constant-arrival execution;
- explicit setup, client transport, retry and complete-all drain contracts;
- raw warm-up and measurement observations, per-attempt retry history and latency,
  throughput and reliability summaries with explicit statistical populations;
- successful-request latency distributions separated from time-to-failure, so fast
  failures cannot make a system appear faster;
- repeated self-calibration against the deterministic local null server;
- private-full evidence bundles with a workload snapshot, enforced JSON Schemas,
  normalized contracts, measurement-window runner load, environment fingerprint,
  calibration record, apparatus assessment and hashes;
- `validate`, `calibrate`, `run` and `verify` commands.

The public JSON Schema documents under `oicap/schemas/0.1/` are enforced when
contracts are loaded and checked again from the bundled schema copies during
verification. Runtime semantic checks in `oicap/contracts.py` additionally enforce
cross-document constraints such as class coverage and weights summing to one.
Contract roots and every fixed structure interpreted by M1 reject unknown keys.
The deliberately extensible SLO metric maps and SUT `model`, `engine`, and `hardware`
description objects remain open. A closed-loop scenario must explicitly declare
`session.think_time_ms` as a non-negative number; an open-loop scenario rejects the
unused `session` block. Misspellings therefore fail validation instead of silently
selecting a different load model.

## Deliberate limitations

This checkpoint supports only the standard-library `urllib` transport without
connection pooling. It records that restriction in `run.yaml`, preventing the
implementation from silently claiming a client configuration it does not have.

For real OpenAI-compatible endpoints, token accounting is either `server_usage` or
`none`. The `synthetic_one_token_per_content_event` authority is accepted only for
the deterministic `oicap_test` protocol. Arbitrary SSE chunks are not labelled
tokens. Consequently token-level ITL is explicitly unavailable for real endpoints
unless authoritative per-token timestamps are added by a future adapter. The runner
reports the distinct, honestly named `inter_chunk_latency` distribution instead.

The apparatus assessment can state `VALID`, `CLIENT_SATURATED`, or `UNCALIBRATED`
and can block a capacity claim. It is not an SLO verdict. This checkpoint emits no
`PASS`, `FAIL`, capacity boundary, comparison, recommendation, goodput result or
HTML report.

Closed-loop concurrency is checked in both session modes. With zero think time, the
target is the declared active-user count. With declared think time `Z`, the runner
uses the measured mean request service time `S` and the interactive response-time
law `N × S / (S + Z)` to derive expected mean in-flight concurrency. The evidence
records the method, inputs, expectation, observation and realization ratio; a value
below the registered floor invalidates the apparatus.

A request that reaches `timeout_s` is recorded as both timed out and right-censored:
its latency is known only to exceed the timeout. With `drain: complete_all`, the
runner does not terminate outstanding requests at a run boundary, so no separate
run-end censoring path exists in M1.

## Evidence bundle

`private-full` bundles contain request bodies and response content and therefore
remain local by default. They contain:

```text
manifest.json
apparatus.json
summary.json
observations.jsonl
runner_load.json
environment.json
calibration_ref.json       # measured run only
contracts/*.json
schemas/*.schema.json
inputs/workload.jsonl
```

`verify` hashes every listed file, rejects unlisted files, recomputes contract and
workload identity, validates bundled contracts against bundled schemas, recomputes
the metric summary, recomputes apparatus validity and checks the embedded
calibration-record hash. Passing `--calibration-source` also verifies the referenced
calibration manifest against an independently supplied calibration bundle. API keys
and authorization headers are excluded; command paths are replaced with placeholders,
and dirty working-tree paths are represented only by an entry count and aggregate hash.

The manifest is unsigned. Verification therefore establishes self-contained internal
consistency and detects edits made without recomputing the bundle; it does **not**
attest producer identity, prove an external timestamp or prevent the producer from
regenerating altered evidence. Detached signatures and external timestamp anchors are
deferred beyond M1. No M1 document or CLI output may describe this as tamper-proof or
tamper-evident evidence.

## Local quick start

```bash
uv sync
oicap validate examples/oicap/basic
oicap calibrate examples/oicap/basic --output /tmp/oicap-calibration
oicap run examples/oicap/basic \
  --endpoint http://127.0.0.1:8000/v1/chat/completions \
  --calibration /tmp/oicap-calibration \
  --output /tmp/oicap-run
oicap verify /tmp/oicap-run --calibration-source /tmp/oicap-calibration
```

`oicap calibrate` reports `command_completed` separately from
`calibration_valid`. Its top-level `ok` is true only for a valid calibration; an
invalid calibration bundle remains available for diagnosis but the command exits 2.

The example workload uses the deterministic test protocol. A real endpoint contract
must replace its test payload and choose `server_usage` or `none` token accounting.

## Acceptance status

| Criterion | Current checkpoint |
|---|---|
| V01-AC1 contracts | Implemented; local controls pass |
| V01-AC2 timing anchors | Implemented; deterministic controls pass |
| V01-AC3 load semantics | Shared-queue closed loop implemented; peak, full-span mean and pre-drain mean concurrency are recorded; heterogeneous positive control passes locally |
| V01-AC4 apparatus calibration | Repeated calibration, overload invalidation and stability controls pass locally |
| V01-AC5 evidence reproducibility | Unsigned internal-consistency verification implemented; producer attestation is explicitly absent |
| V01-AC6 cross-platform compatibility | Demonstrated by GitHub Actions run `33028822268` at commit `1980feb`: the full 84-test suite passed on Ubuntu 24.04 x86_64 and macOS 14 ARM64, and evidence produced on each platform was verified on the other platform with its external calibration manifest supplied |

All six rows now have implementation evidence, including hosted cross-platform
evidence for AC6. This remains an M1 checkpoint until the acceptance evidence is
reviewed as a whole and an explicit release decision is made; passing CI alone does
not create or tag a v0.1 release.

The hosted AC6 evidence is GitHub Actions run
[`33028822268`](https://github.com/shijiuzhang/moe-cache-eval/actions/runs/33028822268)
for commit `1980feb7cc1e68fd003e720f76fe40a5146b159f`. Its six successful jobs were
the full regression suite on both operating systems, a portable-evidence producer
on each, and the two reciprocal verifier jobs (macOS-produced evidence on Linux and
Linux-produced evidence on macOS).
