# OICAP M1 implementation checkpoint

**Date:** 2026-08-13

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
- closed-loop fixed-user and open-loop constant-arrival execution;
- explicit setup, client transport, retry and complete-all drain contracts;
- raw warm-up and measurement observations, per-attempt retry history and the
  required v0.1 latency, throughput and reliability summaries;
- repeated self-calibration against the deterministic local null server;
- private-full evidence bundles with a workload snapshot, normalized contracts,
  environment fingerprint, calibration record, apparatus assessment and hashes;
- `validate`, `calibrate`, `run` and `verify` commands.

The public JSON Schema documents under `oicap/schemas/0.1/` describe the exchange
shape. Runtime semantic checks in `oicap/contracts.py` additionally enforce
cross-document constraints such as class coverage and weights summing to one.

## Deliberate limitations

This checkpoint supports only the standard-library `urllib` transport without
connection pooling. It records that restriction in `run.yaml`, preventing the
implementation from silently claiming a client configuration it does not have.

For real OpenAI-compatible endpoints, token accounting is either `server_usage` or
`none`. The `synthetic_one_token_per_content_event` authority is accepted only for
the deterministic `oicap_test` protocol. Arbitrary SSE chunks are not labelled
tokens.

The apparatus assessment can state `VALID`, `CLIENT_SATURATED`, or `UNCALIBRATED`
and can block a capacity claim. It is not an SLO verdict. This checkpoint emits no
`PASS`, `FAIL`, capacity boundary, comparison, recommendation, goodput result or
HTML report.

## Evidence bundle

`private-full` bundles contain request bodies and response content and therefore
remain local by default. They contain:

```text
manifest.json
apparatus.json
summary.json
observations.jsonl
environment.json
calibration_ref.json       # measured run only
contracts/*.json
inputs/workload.jsonl
```

`verify` hashes every listed file, rejects unlisted files, recomputes contract and
workload identity, recomputes the metric summary, recomputes apparatus validity,
and checks the embedded calibration-record hash. API keys and authorization headers
are excluded; command paths are replaced with placeholders.

## Local quick start

```bash
uv sync
oicap validate examples/oicap/basic
oicap calibrate examples/oicap/basic --output /tmp/oicap-calibration
oicap run examples/oicap/basic \
  --endpoint http://127.0.0.1:8000/v1/chat/completions \
  --calibration /tmp/oicap-calibration \
  --output /tmp/oicap-run
oicap verify /tmp/oicap-run
```

The example workload uses the deterministic test protocol. A real endpoint contract
must replace its test payload and choose `server_usage` or `none` token accounting.

## Acceptance status

| Criterion | Current checkpoint |
|---|---|
| V01-AC1 contracts | Implemented; local controls pass |
| V01-AC2 timing anchors | Implemented; deterministic controls pass |
| V01-AC3 load semantics | Implemented; local schedule and client-saturation controls pass |
| V01-AC4 apparatus calibration | Repeated calibration, overload invalidation and stability controls pass locally |
| V01-AC5 evidence reproducibility | Implemented; tamper controls pass |
| V01-AC6 cross-platform compatibility | Existing simulator tests pending full regression; Linux CI not yet observed |

The checkpoint MUST NOT be called v0.1 until every row above is demonstrated. In
particular, one successful macOS run is not evidence of Linux/macOS portability.
