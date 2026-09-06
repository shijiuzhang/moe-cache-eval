# OICAP v0.2.0-alpha.1 local workflow qualification

**Status:** PASS for the local-workflow developer-alpha claim

**Date:** 2026-09-06

**Runner commit:** `61c1f46581124e2b4b352d28c1b8052653ec0275`

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
| Closed-loop load | requested 2; realized mean before final submission 1.9956 |
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
| generated `translation-report.json` | `10c6c52262cc1d66c6eb305c510897d3f08e9526ba553ed17848c9a5830a0768` |
| calibration `manifest.json` | `8c13f7ac3cb81346a7bf6eebc1ff6a9e28d76c6db400517f73bb4da245c571f4` |
| run `manifest.json` | `b9fd62341da6e4537b504aec6631901c35ca1cb961f593e1c33e24a3c3de8906` |

These are execution-record checksums, not a detached signature or external
timestamp anchor. The bundles remain unsigned, exactly as `oicap verify` reports.

## Test suites

- Python: 104 tests, all passed;
- buyer/expert browser-local workflow: 29 tests, all passed;
- translator-specific positive and negative controls: 11 tests, all passed.

The negative controls reject unfinished expert drafts, mismatched workload
classes, undeclared load points, ambiguous service-discipline text, unsupported
quality-hook and authoritative per-token gates, open-loop runs without a bounded
client concurrency, and an existing output path.
