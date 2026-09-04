# OICAP V02-AC05 llama.cpp CPU protocol qualification

**Status:** PASS for V02-AC05  
**Date:** 2026-09-04

**Runner commit:** `68c0e8d8957ad487112f0fa353ab42748dd73288` (clean tree)

**OICAP version:** `0.2.0.dev0`  
**Metrics version:** `0.2-dev2`

This record qualifies the measurement kernel against one real CPU-hosted
OpenAI-compatible inference service. It unlocks v0.2 software work and pilot use.
It does **not** qualify GPU capacity measurement and does not authorize formal
delivery verdicts.

## 1. Environment

- engine: `llama.cpp` 10210 (`000547513`), AppleClang Darwin arm64 build;
- server mode: `llama-server`, CPU only, four slots, 2048-token context;
- client/SUT host: Apple M4 Pro, 25,769,803,776 bytes RAM, Darwin arm64;
- model: local 11,907,350,576-parameter Q4_K_M GGUF;
- model SHA-256:
  `1278394b693672ac2799eadc9a83fd98259a6a88a40acfb1dcaa6c6fc895a606`;
- endpoint: loopback OpenAI-compatible `/v1/chat/completions`.

These are protocol-qualification conditions, not a portable performance baseline.

## 2. Evidence

The evidence is under
`artifacts/oicap/ac05_llama_cpp_cpu_2026-08-31/`:

| Record | SHA-256 |
|---|---|
| `calibration/manifest.json` | `9886904562b85a7253989c9186ea75f7467eb42c5b7a0ea90647be39fa929863` |
| `run/manifest.json` | `e22d8e4ab98bca43df0f7ad4ff176bdb8bd82a8eb28ba52f94200ab8904013e3` |
| `protocol-qualification.json` | `0b9e96f1130697a109f1c2c5ce1e9497cfdee94548600a6a7f4dfe52d1982414` |

`oicap verify` passes with the external calibration manifest supplied. The run
bundle records `git_dirty: false` and the exact runner commit above. Verification
retains the v0.1 honesty boundary: it establishes unsigned internal consistency,
not producer identity, detached signature or external timestamp anchoring.

## 3. Compatibility matrix

| V02-AC05 condition | Observed evidence | Result |
|---|---|---|
| Genuine SSE role-only/empty/content events | Stream begins with one combined `role_empty` event and the content control emits eight content events plus `[DONE]`. | PASS |
| Non-streaming response | HTTP 200, nonblank content and usage object. | PASS |
| Authoritative usage present and absent | With `stream_options.include_usage`, input/output counts are 24/9; without it both remain null while the request still succeeds. | PASS |
| Timeout and right censoring | 1 ms client deadline yields `timed_out: true`, `censored: true`, `error_type: timeout`. | PASS |
| Connection or HTTP error | Invalid route returns HTTP 404 and `error_type: http_error`. | PASS |
| HTTP 200 without substantive content | One-token reasoning-only response returns HTTP 200 but is classified `empty_or_non_substantive_response`, not success. | PASS |
| Multiple chunks and unavailable authoritative ITL | Seven content inter-chunk intervals are reported; ITL remains unavailable with `no_authoritative_per_token_timestamps`. | PASS |
| Repeated real requests have non-zero variance | Four requests yield a TTFT range from below the 6247.889 ms mean to a 10470.698 ms maximum. | PASS |
| Token-timing authority is visible | Every protocol observation records `server_usage`; the summary reports the homogeneous authority set and marks per-token adjudication ineligible. | PASS |

The normal evidence run completed four of four measured requests, maintained
`1.999942 / 2.0` mean in-flight requests before final submission, and reports the
apparatus `VALID`. Those numbers establish protocol execution and load realization
for this fixture only; they are not a capacity verdict.

## 4. Positive controls

All three required controls are machine-recorded as `passed: true` in
`protocol-qualification.json`:

1. Adding an HTTP-200 empty response leaves the one successful request's latency
   population and mean unchanged; the empty response enters the error count.
2. Adding a true timeout leaves successful latency unchanged, increments timeout
   and censored counts, and contributes one time-to-failure sample.
3. Seven content-chunk intervals are exposed only as
   `inter_chunk_latency`; ITL is unavailable and TPOT is also unavailable without
   authoritative first-to-last token timestamps.

## 5. Defect discovered and closed

The first real run exposed a semantic defect that deterministic fixtures had not:
`llama.cpp` reports aggregate `completion_tokens` that include hidden reasoning
tokens, while OICAP anchors TTFT at the first nonblank user-visible content event.
The old calculation divided only the short post-content tail by all reported
completion tokens and produced an implausibly favorable TPOT (about 1.35 ms/token
in the reproduction, while server generation timing was about 53 ms/token).

The fix is deliberately conservative:

- server usage remains authoritative for aggregate throughput counts;
- reasoning events are named but their text is not retained;
- TPOT requires authoritative first-to-last per-token timestamps;
- server-usage-only runs report TPOT unavailable instead of manufacturing a value;
- `inter_chunk_latency` remains distinct from ITL;
- the verifier dispatches by stored `metrics_version`, so v0.2 still reproduces
  frozen v0.1 evidence exactly rather than retroactively changing it;
- the verifier explicitly names the applied ruleset, warns on superseded
  semantics, and prevents legacy per-token metrics from becoming v0.2 evidence;
- synthetic token timing requires a response-side marker from the registered
  deterministic test protocol; a request field alone cannot authorize it;
- current summaries carry the observed token-timing authority, and synthetic
  timing is qualified as `synthetic_available`, never bare `available`.

The full repository suite passes 93 tests. A genuine evidence bundle produced by
the tagged v0.1 release is frozen under `tests/fixtures/`; the current verifier
recomputes it exactly while reporting `superseded_metrics_ruleset:0.1` and
`adjudication_eligible: false`. Positive controls also cover response-side
protocol identity, reasoning-event handling and TPOT unavailability.

## 6. Remaining boundary

V02-AC05 is a protocol gate. A real GPU serving stack is still required before
OICAP may issue formal capacity or delivery-acceptance verdicts. AC04 procurement
rehearsal also remains organizational work: it requires an authorized,
de-identified real procurement case and procurement participants, neither of which
can be fabricated from repository data.
