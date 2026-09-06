# OICAP v0.2.0-alpha.1 local workflow qualification

**Status:** PASS for the local-workflow developer-alpha claim

**Date:** 2026-09-06

**Runner commit:** `ecb165d6fa265df71627878248e4eb70f860be6e`

**OICAP version:** `0.2.0a1`

**Formal procurement verdict enabled:** `false`

## Scope

This qualification checks the exact narrow chain introduced by alpha.1:

```text
reviewed public expert draft
  -> translate-expert
  -> four schema-0.1 contracts
  -> validate
  -> calibrate
  -> run against real llama.cpp
  -> verify with an independent calibration manifest
```

It is protocol evidence for a local developer alpha. It is not a capacity test,
SLA verdict, deployment-conformance result, GPU qualification, or procurement
acceptance record.

## Real endpoint

- engine: llama.cpp 10210 (`000547513`), Darwin arm64;
- model: `QuantFactory/SmolLM2-135M-Instruct-GGUF`, Q4_K_M;
- model file size: approximately 105 MB;
- model SHA-256:
  `8030f04528538d47bda434f6f0bdf3952c40a58123e4d5e755332f23731a8684`;
- model licence reported by its repository: Apache-2.0;
- endpoint: loopback OpenAI-compatible `/v1/chat/completions`;
- server slots: 2; server context: 1024 total / 512 per slot.

The small public model was selected to make the protocol check fast and
repeatable. Its performance is not representative of a private enterprise model.

## Results

The source tree was clean when the evidence run started. The run bundle records
the exact commit above and `git_dirty: false`.

| Check | Result |
|---|---|
| Translation | `ok: true`; selected declared load point 2 |
| Formal verdict flag | `false` |
| Four emitted contracts | accepted by the published schema-0.1 validator |
| Calibration | `valid: true`; no invalid reasons |
| Real run | 4/4 measured requests successful |
| Closed-loop load | 2 users with explicit 1,000 ms think time; interactive response-time-law check |
| Load realization | expected mean in-flight 0.1240; realized 0.1621; ratio 1.3074; apparatus `VALID` |
| Evidence verification | `ok: true`; `errors: []` |
| Metrics ruleset | current `0.2-dev2`; adjudication eligible as measurement evidence |
| Per-token latency | unavailable, as required without authoritative token timestamps |
| External calibration manifest | verified |

The observed throughput and latency values are intentionally not promoted here.
They characterize only this tiny loopback protocol fixture and cannot support a
capacity or procurement conclusion.

## Frozen checksums

| Record | SHA-256 |
|---|---|
| generated `translation-report.json` | `4fba1e5f12cbd0f4a910d3970580addb6205954eed66e19f3927c204feb736a6` |
| calibration `manifest.json` | `0c110659f422fb6c68d7695d7014616f23b3e55d50e82d472a0dd9eef99367bc` |
| run `manifest.json` | `fd7dd88d33f4d014cdad194dcaf87f168a4083627d82cf0a8052fc372b18f665` |

These are execution-record checksums, not a detached signature or external
timestamp anchor. The bundles remain unsigned, exactly as `oicap verify` reports.

## Test suites

- Python: 105 tests, all passed;
- buyer/expert browser-local workflow: 30 tests, all passed;
- translator-specific positive and negative controls: 12 tests, all passed.

The negative controls reject unfinished expert drafts, mismatched workload
classes, undeclared load points, ambiguous service-discipline text, unsupported
quality-hook and authoritative per-token gates, open-loop runs without a bounded
client concurrency, and an existing output path.

## Distribution artifact

The wheel was built from the committed candidate, installed with dependencies
into a new Python 3.12 virtual environment outside the repository, and the full
translation, validation, calibration, real-endpoint run, and verification chain
was repeated through the installed `oicap` console script. The installed runtime
reported `0.2.0a1`; all five commands succeeded and verification again returned
`ok: true` with no errors. The final artifact was rebuilt twice with
`SOURCE_DATE_EPOCH=1788703043`; both builds produced the same digest below.

| Artifact | Size | SHA-256 |
|---|---:|---|
| `moe_cache_eval-0.2.0a1-py3-none-any.whl` | 61,910 bytes | `8b73a88c8a93f715a2fb32b71f2e0e41246bf53f03dce2ba9a36e826122a3c01` |

The wheel contains the translator, console entry point, and all four published
schema documents.
