# Independent audit — OICAP M1 measurement kernel

**Auditor:** independent review role per §19
**Date:** 2026-08-14
**Subject:** commit `30141f6`, `oicap/` and `tests/test_oicap.py`
**Against:** `docs/PLATFORM_PRODUCT_SPECIFICATION_V0_1.md` §15.1 (V01-AC1…AC6)
**Disposition format:** each finding is numbered for accept / reject / defer

Every finding below was reproduced against the committed code. Where a finding
is demonstrated, the measured numbers are shown.

---

## Overall

The hard parts are right. Four decisions in particular are not standard practice
in this tool category and should survive any rework:

- the empty/role-only delta is not counted as the first token, and
  `t_first_byte`, `t_first_chunk` and `t_first_token` are three separate anchors;
- `synthetic_one_token_per_content_event` is refused unless the request carries
  the `oicap_test` field, so SSE chunks can never be silently relabelled tokens
  against a real endpoint (`openai_adapter.py:60`);
- the open-loop semaphore is acquired *after* the arrival sleep, so client
  saturation shows up as schedule lag instead of quietly reshaping the arrival
  process (`runner.py:241`);
- apparatus validity is kept structurally distinct from an SLO verdict, and the
  checkpoint emits no verdict, ranking or comparison.

The executor's own caveat is also correct and should be held: AC6 cannot be
claimed until CI has actually run on both platforms. Do not tag v0.1.

Four findings are blocking. B1 and B3 cause the kernel to report numbers that
are wrong rather than merely incomplete. B2 concerns what `verify` can be said
to prove. Seven further findings should be resolved before v0.1 but do not block
continued work.

---

## Blocking

### B1. Closed-loop does not maintain the active-user count — V01-AC3 fails

`_closed_loop` partitions the request sequence statically, round-robin, one
fixed slice per worker (`runner.py:200-201`):

```python
worker_count = min(active_users, max_in_flight, len(sequence))
queues = [sequence[index::worker_count] for index in range(worker_count)]
```

A worker that draws cheap requests finishes its slice and exits. The remaining
workers run on alone, so the concurrency the SUT actually sees decays over the
tail of the run. AC3 requires the configured active-user count be *maintained*
when possible.

**Demonstrated.** Six requests alternating 200 ms and 1 ms, `active_users: 2`,
`max_in_flight: 4`. Worker 1 received all three fast requests, finished in a few
milliseconds and exited:

```
closed_loop active_users=2, 6 requests, span 424 ms
sampled ms with in-flight < 2: 211/425 = 50%
peak_in_flight reported: 2
```

Half the run was executed at half the declared concurrency, and it was entirely
possible to avoid — a shared queue keeps both users busy for the whole span.

Two things make this worse than a scheduling inefficiency:

- **The evidence hides it.** `summary.json` reports `peak_in_flight: 2`, which
  reads as "the target was met". There is no mean or time-weighted concurrency
  in the summary, so an auditor holding only the bundle cannot detect the decay.
- **The bias has a direction.** Against a batching inference server, lower
  concurrency means lower latency. A closed-loop load point therefore reports
  latency systematically better than the declared operating point, and the
  effect grows with workload heterogeneity — which is exactly what the
  multi-class scenario contract is built to express.

The test does not catch it because it asserts the wrong side of the criterion.
`test_closed_loop_limits_active_requests` (`tests/test_oicap.py:227-247`) uses
eight identical 10 ms items and asserts `maximum == 3` — an upper bound. AC3 is
a lower bound. With homogeneous latency, static partitioning happens to keep
every worker busy, so the defect is invisible to this fixture by construction.

**Requested change.** Replace the static partition with a shared
`asyncio.Queue` drained by `worker_count` workers. Add to the summary a
time-weighted mean in-flight count over the measurement window, and have the
apparatus assessment flag a closed-loop run whose realized mean concurrency
falls below the declared `active_users` by more than a registered tolerance.
Change the test fixture to heterogeneous latencies and assert the floor, not
the ceiling.

### B2. `verify` proves internal consistency, not tamper evidence

The manifest is unsigned and lists the hashes of files that sit beside it. A
party who can edit the bundle can recompute the manifest, and `verify` recomputes
exactly the same quantities the writer did.

**Demonstrated.** Starting from a bundle produced by
`scripts/generate_oicap_ci_bundle.py`, every `t_first_token_ns` was moved halfway
toward its `t_submit_ns`, then `summary.json`, `apparatus.json` and
`manifest.files` were regenerated using the tool's own functions:

```
ttft p99 before tamper: 6.65 ms
ttft p99 after  tamper: 3.32 ms
verify ok: True errors: []
```

Naive edits are caught — editing one observation alone yields
`['hash_mismatch:observations.jsonl', 'summary_mismatch']`. The gap is a
producer who reruns the recomputation.

This is not a coding error; it is inherent to an unsigned self-contained
manifest. It is blocking because of what is claimed around it. The checkpoint
report describes "防篡改校验", and the project's entire positioning is
third-party-checkable capacity measurement *as against* vendor-published
numbers. Against the adversary that positioning names — the party publishing the
bundle — `verify` currently establishes nothing.

**Requested change.** Two parts, and the wording matters as much as the code.

1. State the actual property in `OICAP_M1_IMPLEMENTATION.md` and in `verify`'s
   own output: the bundle is internally consistent and has not been altered by
   anyone who did not rerun the tool. It does not attest to who measured what.
2. For v0.2, add a detached signature over `manifest.json` by the measuring
   party, and anchor the timestamp outside the bundle. Until then, do not
   describe bundles as tamper-evident anywhere, including the README.

### B3. Latency distributions mix failed requests with successful ones

`_summarize_rows` computes `per_request` over every row (`metrics.py:101-102`),
so any observation carrying `t_complete_ns` contributes to `latency_ms`. A
stream that returns HTTP 200 and no substantive content sets both
`success = False` and `t_complete_ns` (`openai_adapter.py:141-150`), and such
requests fail fast.

**Demonstrated.** Three good requests at ~110 ms plus one 200-OK-but-empty
response:

```
requests.total       : 4
requests.successful  : 3
latency_ms.end_to_end: count 4, mean 80.9, p50 104.7
latency_ms.ttft      : count 3, mean 107.6, p50 105.8
```

One failure in four pulled mean end-to-end latency down 25%, from 107.6 to 80.9.
The incentive runs the wrong way: an endpoint that sheds load by returning fast
empty 200s measures *faster* on the headline latency metric. A benchmarking
kernel must not create that gradient.

The population problem is more general than the one failure mode. `end_to_end`
has `count: 4` while `ttft` has `count: 3` and `requests.successful` is 3, and
nothing in `summary.json` says which requests each distribution was computed
over. A reader cannot reconcile the counts.

**Requested change.** Compute all latency distributions over successful requests
only, and state the population in the summary — add an explicit
`population: "successful"` field and a `count` that must equal
`requests.successful`. Keep failed and timed-out requests in the reliability
block where they already are, and add a separate `time_to_failure_ms`
distribution if that signal is wanted; do not fold it into latency.

### B4. ITL cannot be computed for any real endpoint

`token_timestamps_ns` is appended only under
`synthetic_one_token_per_content_event` (`openai_adapter.py:129-133`), and the
adapter refuses that authority unless the request carries `oicap_test`. Real
endpoints must therefore use `server_usage` or `none` — and under both,
`token_timestamps_ns` stays empty.

**Demonstrated**, same four-token response under each authority:

```
                        server_usage: itl_samples=0  tpot=24.1
synthetic_one_token_per_content_event: itl_samples=3  tpot=22.8
                                none: itl_samples=0  tpot=None

server_usage summary latency_ms.itl: {'count': 0, 'mean': None, 'p50': None, ...}
```

`latency_ms.itl` is `count: 0` in every measurement of a real system. The same
holds inside `calibrate`: `noise_resolution["itl_ms"]` is `None` for any
real-endpoint contract, so ITL has no registered noise floor either, and nothing
flags its absence.

The checkpoint report lists "TTFT、ITL、TPOT、端到端延迟等原始测量" among the
delivered results, and `OICAP_M1_IMPLEMENTATION.md` lists ITL in the required
v0.1 summaries. That is not what ships.

The underlying decision — refusing to call an arbitrary SSE chunk a token — is
correct and should not be reversed. The defect is that the consequence was not
carried through. The raw data is already in the bundle:
`ChunkObservation.received_ns` records every content event.

**Requested change.** Derive an `inter_chunk_latency_ms` distribution from
content-chunk timestamps under all authorities, named for what it measures.
Report `itl_ms` only where the token authority makes chunks and tokens
equivalent, and emit `null` with a stated reason otherwise rather than an empty
distribution. Correct the claim in the implementation document.

---

## Non-blocking

### N1. The published JSON Schemas are never enforced, and already disagree with the validator

Nothing loads `oicap/schemas/0.1/*.json`. They are copied into evidence bundles
and shipped in the wheel; validation is the hand-written
`validate_contracts`. `test_published_schema_documents_are_valid_json`
(`tests/test_oicap.py:117`) checks only that the four files parse and carry a
`$schema` key. Two independent definitions of validity exist and neither is
checked against the other.

They have already drifted. `sut.schema.json` requires `model`, `engine` and
`hardware`; `validate_contracts` requires only `sut_id` and
`service_discipline` (`contracts.py:270-275`). Demonstrated:

```
validate_contracts: ACCEPTED sut.yaml with no model/engine/hardware
sut.schema.json required: [schema_version, sut_id, model, engine, hardware, service_discipline]
missing vs schema: [model, engine, hardware]
```

Those three fields are precisely what makes a measurement attributable to a
system. As it stands a bundle can be produced, verified and published with no
record of which model on which hardware was measured, and `verify` returns
`ok: true`.

**Requested change.** Validate every contract against its published schema
first, then apply the cross-document semantic checks that JSON Schema cannot
express. Add a test asserting the example contracts satisfy the schemas, and one
asserting a schema-invalid contract is rejected.

### N2. `censored` is never set by any production path

`RequestObservation.censored` (`observations.py:30`) is summed into
`requests.censored` (`metrics.py:144`) and set nowhere else in `oicap/`. The only
test that exercises it constructs the flag by hand. `requests.censored` is
therefore 0 in every real run.

AC2 requires censored requests to remain visible. The natural censoring case is
present and mislabelled: a request that hits `timeout_s` has a latency known only
to exceed the timeout, which is the definition of a right-censored observation.
It is recorded as `timed_out` with `censored` left false, so the distinction the
field exists for is discarded.

**Requested change.** Set `censored = True` on timeout, and state in the
implementation document what other censoring cannot arise under
`drain: complete_all`. A field that is structurally always zero, with a unit
test that fabricates its input, reads as a passing control for an unimplemented
requirement.

### N3. Runner load is measured during calibration and never during the run

`psutil` and `time.process_time_ns()` appear only in `calibration.py:48`. The
measured run records no CPU or process load at all, and `apparatus_assessment`
checks only schedule lag and arrival ratio (`evidence.py:186-196`).

So the noise floor is registered under observed conditions and then applied to a
run whose conditions are unobserved. A run sharing the machine with an unrelated
load is assessed `VALID` provided schedule lag stays inside the limit. Schedule
lag is a reasonable proxy but it is not the same evidence, and the disposition
of B2 in the specification audit committed to recording CPU and event-loop load.

**Requested change.** Record process CPU, system CPU and event-loop lag over the
measurement window in `environment.json` or a new `runner_load.json`, and have
the apparatus assessment compare them against the calibration limits.

### N4. `source_bundle_manifest_sha256` is recorded but never checked

`load_calibration` records the calibration bundle's manifest hash
(`calibration.py:193`), and `verify_bundle` checks only the embedded record's own
hash (`evidence.py:302-311`). The link back to the calibration bundle as a
separate object is written down and never verified. Given B2 this is minor, but
it is the one field that could tie a run to a calibration obtained independently.

### N5. The evidence bundle publishes the working tree's dirty file list

`git_fingerprint` writes `git_status_paths` in full (`evidence.py:79-83`). The
bundle generated for this audit contains:

```json
"git_status_paths": ["M paper/ARXIV_SUBMISSION_METADATA.md",
                     " M paper/ZENODO_DEPOSIT.md"]
```

Those files have nothing to do with the measurement. `manifest.excluded` claims
only "API keys and authorization headers", so a reader has no notice that local
paths are included. Harmless here; not harmless when the bundle is shared and
the working tree holds customer or unreleased paths.

**Requested change.** Keep `git_commit` and `git_dirty`; replace the path list
with a count, or a hash of the sorted list.

### N6. The documented bundle layout omits `schemas/`

`write_bundle` copies the schema directory into every bundle
(`evidence.py:113-114`), and a produced bundle contains four files under
`schemas/`. The listing in `OICAP_M1_IMPLEMENTATION.md` does not mention it. The
document is the stated audit entry point, so its file listing should be exact.

### N7. CI does not cover AC6 as written

- `conformance` runs the matrix on Linux and macOS but only `tests.test_oicap`.
- `research-regression`, which is what keeps the event-atomic simulator green,
  runs on `macos-14` only. AC6 requires the simulator's existing tests remain
  green as part of cross-platform compatibility, and the simulator is the more
  platform-sensitive of the two code bases.
- The producer/verifier pair covers macOS → Linux only. AC6 says an evidence
  bundle produced on one platform verifies on the other; the reverse direction
  is untested.

**Requested change.** Move the full `unittest discover` into the OS matrix, and
add the Linux → macOS verification leg.

---

## Acceptance status after this audit

| Criterion | Executor's claim | Audit |
|---|---|---|
| V01-AC1 contracts | implemented, controls pass | **Qualified** — semantic checks pass; published schemas unenforced and already divergent (N1) |
| V01-AC2 timing anchors | implemented, controls pass | **Qualified** — anchors correct; ITL unavailable for real endpoints (B4), censoring unimplemented (N2) |
| V01-AC3 load semantics | implemented, controls pass | **Fails** — closed loop does not maintain active users (B1); the test asserts the ceiling, not the floor |
| V01-AC4 apparatus calibration | controls pass locally | **Qualified** — calibration is sound; the measured run records none of the same load evidence (N3) |
| V01-AC5 evidence reproducibility | implemented, tamper controls pass | **Qualified** — reproducibility holds; "tamper" is the wrong word for what is proven (B2) |
| V01-AC6 cross-platform | pending, CI not yet observed | **Agreed, and narrower than stated** — the workflow as written does not cover AC6 (N7) |

Nothing here contradicts the executor's central judgement: this is an
implementation checkpoint, not v0.1. That judgement was correct and was made
without prompting.

---

## Reproduction

Findings B1, B3, B4 and N1 were reproduced with short scripts against
`examples/oicap/basic` on the committed tree; B2 was reproduced against a bundle
from `scripts/generate_oicap_ci_bundle.py`. The full suite was re-run
independently: `72 tests, OK` under `python -m unittest discover -s tests`, and
the documented quick-start path (`calibrate` → `run` → `verify`) completes with
`ok: true`.

---

# Re-audit of the remediation — 2026-08-26

Reviewing commit `8756db1` "Resolve OICAP M1 implementation audit" against the
four blocking and seven non-blocking findings above.

Everything below was established by running the code and reading the artifacts
it produced, not by reading the remediation note or the test names. Where a fix
is claimed to be covered by a test, the behaviour was reconstructed
independently so that a passing test and a working fix are two pieces of
evidence rather than one.

## Verdict

**All four blocking findings are fixed.** All seven non-blocking findings are
addressed. Two minor findings are raised below, neither blocking. The
checkpoint should remain an M1 checkpoint and must not be called v0.1 until AC6
is demonstrated on hosted runners.

The full repository suite was run here: **81 tests, OK**.

## B1 — closed-loop concurrency decay: fixed, and demonstrated

Static per-worker slices were replaced with a shared `asyncio.Queue`, which
removes the failure mode by construction: a worker cannot exhaust its private
slice while others still have work.

More important is that the apparatus can now *detect* the condition, which is
what AC3 required and what the original audit found missing. Verified by
building a deliberately over-committed contract — `active_users: 16` against
`max_in_flight: 4` and eight measurement requests:

```
requested_active_users            16
realized_mean_in_flight            3.29
closed_loop_concurrency_ratio      0.206     (floor 0.60)
valid                              false
invalid_reasons                    ["closed_loop_concurrency_not_maintained"]
oicap run                          refused, exit 2
```

Calibration marks the apparatus invalid and the run is blocked. On the healthy
example the same machinery reports `realized_mean_in_flight 1.979` against
`requested_active_users 2`, ratio `0.989`, `status VALID`.

The `mean_in_flight_before_final_submission` construction is correct: it
integrates the concurrency function over `[first submission, final submission]`
and divides by that window, which excludes the unavoidable drain tail without
excluding a genuine mid-run collapse. On the healthy run the two means differ as
they should — 1.979 pre-drain against 1.759 full-span.

## B2 — unsigned manifest overclaim: corrected

`verify` now emits a five-field `verification_scope` block, and the three
claims that cannot be supported are explicitly false:

```
internal_consistency                     true
calibration_source_manifest_verified     true   (false + warning when omitted)
producer_identity_attested               false
detached_signature_verified              false
external_timestamp_anchor_verified       false
```

The accompanying note is the strongest available formulation because it names
the specific attack rather than gesturing at a limitation: verification "does
not attest who ran the measurement **or prevent a producer from regenerating
altered evidence**." That is exactly the property a reader was previously
invited to infer.

## B3 — failed requests contaminating latency: fixed, verified bit-exactly

Constructed three successful requests, recorded the `end_to_end` mean, then
added a genuinely timed-out request and re-summarised:

```
total 4  successful 3  timed_out 1  censored 1
end_to_end mean with the failure present   25.042 ms
end_to_end mean of the three successes     25.042 ms   identical
end_to_end request_count                   3           not 4
time_to_failure                            1 sample, 51.5 ms
```

The failure contributes nothing to the success latencies, the population is
named and sized in the output, and the failure duration is reported separately
rather than discarded. N2 is confirmed in the same run: `censored` is set on the
live adapter timeout path, not only in a unit fixture.

## B4 — real-endpoint ITL: made explicit and correct

Under `server_usage` authority against a streaming endpoint:

```
itl                  count 0   availability unavailable
                     unavailable_reason no_authoritative_per_token_timestamps
inter_chunk_latency  populated from content-event timestamps
```

The distinction is the right one. A chunk is not a token, and the summary now
says so in machine-readable form instead of publishing a chunk interval under a
token-interval name.

## Non-blocking findings, spot-checked

- **N1** — removing `model`, `engine` and `hardware` from `sut.yaml` is rejected
  at `validate` with `"sut.yaml violates published schema at <root>: 'model' is
  a required property"`. Schemas are enforced, not merely shipped.
- **N3** — `runner_load.json` carries measurement-window process CPU, system CPU
  and an independent 1 ms asyncio wake-up-lag probe, and the apparatus compares
  all three against calibrated limits.
- **N4** — `verify --calibration-source` sets
  `calibration_source_manifest_verified`; omitting it yields `false` plus the
  warning `calibration_source_manifest_not_independently_checked`.
- **N5** — `environment.json` carries `git_status_entry_count` and
  `git_status_paths_sha256` only. No path string survives; the bundle contains no
  occurrence of the developer's home directory.
- **N6/N7** — bundle listing includes `schemas/` and `runner_load.json`; the
  workflow runs the full suite on both platforms and exchanges evidence in both
  directions.

## F1 — the concurrency check is disabled by declared think time (minor)

`evidence.py` skips the closed-loop ratio whenever `think_time_ms > 0`, setting
`closed_loop_concurrency_check: "not_applicable_declared_think_time"`.

Skipping is defensible: with think time the expected in-flight count is not
`active_users`, so a naive ratio would fail healthy runs. The state is
machine-readable rather than silent, and the shared queue removes the structural
failure mode regardless. Schedule lag and event-loop lag still cover client
saturation, and `t_scheduled_ns` is taken after the think-time sleep, so a
congested loop is still visible.

What remains is narrower: **for any scenario declaring think time,
`capacity_claim_permitted` can be true although the concurrency B1 was about was
never checked.** A check is constructible — Little's Law gives an expected
in-flight of `N × S / (S + Z)` from quantities the run already measures — so the
gap is a deferred implementation rather than an unmeasurable quantity. Worth
either implementing before any think-time scenario is used for a capacity claim,
or stating in the documentation that such scenarios carry no concurrency
verification.

## F2 — `calibrate` prints `ok: true` while writing `valid: false` (minor)

The over-committed contract above produced `{"ok": true}` on stdout from
`oicap calibrate` while `calibration.json` recorded `valid: false`. The safety
property holds — `run` refuses with exit 2 — but at the end of a calibration
command the word `ok` reads as a verdict on the apparatus, which is precisely
the reading B2 exists to prevent elsewhere. Either surface the validity in the
command's own output or reserve `ok` for "the command completed".

## Position

The remediation is substantive rather than cosmetic: each blocking finding was
answered with a change to what the system *measures and refuses*, not only with
a change to what it says. The AC3 demonstration in particular converts the
original finding from an argument into a reproducible control.

AC6 remains the outstanding criterion, and one macOS host is not evidence of it.
Push, observe the hosted Linux and macOS runs including both evidence-exchange
directions, and only then revisit the version label.

---

# Re-audit of F1, F2 and AC6 — 2026-08-27

Reviewing `1980feb` "Close OICAP M1 re-audit findings" and `c443b41` "Record
hosted OICAP cross-platform evidence".

## F1 — closed: and the fix discriminates correctly

The `not_applicable_declared_think_time` branch is gone. Think-time sessions now
compute an expected concurrency from the interactive response-time law,
`N × S / (S + Z)`, and apply the same registered realization-ratio floor.

The audit concern was that `S` is measured from the same run, so a saturated
client might inflate `S`, inflate the expectation, and leave the ratio near one —
a check that cancels itself. **That concern was wrong, and the reason it is wrong
is the reason the model is right.** Probed directly with `N = 4`, `Z = 100 ms`:

| Condition | observed | expected | ratio | verdict |
|---|---:|---:|---:|---|
| healthy, `S = 100 ms` | 2.0 | 2.0 | 1.00 | pass |
| **client late, `S = 100 ms`** | 1.0 | 2.0 | **0.50** | **caught** |
| slow server, `S = 900 ms` | 3.6 | 3.6 | 1.00 | correctly not flagged |

Client lateness occurs *before* `t_submit` — during the think sleep and
scheduling — so it does not enter `S`. It only depresses observed concurrency,
and the ratio falls. Server slowness raises `S` and observed concurrency
together, so the ratio holds at one, which is the correct verdict: the apparatus
check asks whether the client delivered the intended load, not whether the
server was fast. The two failure modes are discriminated rather than conflated.

Populations are consistent: `intervals` spans `t_submit` to terminal for **all**
requests including failures, and both `observed` and `S` derive from it. A failed
request still occupied a worker slot, so including it is correct.

Reachability confirmed end to end: a scenario carrying `session.think_time_ms:
50` validates, calibrates, selects `method: interactive_response_time_law` and
produces `closed_loop_concurrency_ratio: 0.915` against a measured service time
of 1.05 ms and a declared think time of 50 ms.

## F2 — closed

`oicap calibrate` now separates the two claims and the exit code follows
validity, not completion:

```
invalid contract  ->  command_completed true, calibration_valid false, ok false, exit 2
valid contract    ->  ok true, exit 0
```

## AC6 — demonstrated on hosted runners

Verified through the GitHub API rather than from the report: run
`33038054751` at `c443b41`, which is the current `origin/main`, conclusion
**success**, all six jobs green:

```
full-regression (ubuntu-latest)          success
full-regression (macos-14)               success
portable-evidence-producer-macos         success
portable-evidence-verifier-linux         success   <- macOS bundle verified on Linux
portable-evidence-producer-linux         success
portable-evidence-verifier-macos         success   <- Linux bundle verified on macOS
```

Both exchange directions complete on machines the author does not control, which
is what makes this evidence rather than assertion. The full repository suite runs
on both platforms in the same workflow. Local re-run here: **84 tests, OK**.

## F3 — `session.think_time_ms` is load-bearing but undeclared (minor, new)

`session` does not appear in `scenario.schema.json`, and no contract schema sets
`additionalProperties: false`, so the block is accepted without validation.

The field now selects the concurrency model and drives the runner's sleep. A
misspelling — `think_time`, `think_time_s` — is silently ignored.

Severity is limited by two things. The runner, calibration and apparatus all read
the identical key, so a typo removes think time everywhere at once; the run then
has no think time, and the apparatus correctly assesses it against
`declared_active_users`. The result stays internally consistent and correctly
judged. And `runner.py` rejects a negative value at runtime.

What is lost is narrower: **the operator asked for a think-time scenario, did not
get one, and nothing said so.** Declaring `session` in the schema — and, more
generally, deciding whether contract schemas should close to unknown keys — would
convert a silent no-op into a rejected contract. Worth doing before think-time
scenarios are used for anything published, and it is the same class of gap that
N1 was raised about.

## Verdict on the version label

All six acceptance criteria now have evidence, and AC6's evidence is external.
Nothing found in this pass blocks a v0.1 tag.

Recommendation: **close F3 first, then tag.** It is a schema addition, it is
cheap, and tagging a release whose contract schema silently accepts an
undeclared field that changes the apparatus verdict is the kind of detail this
project has repeatedly paid for later.

---

# F3 close-out — 2026-08-27

Reviewing `f9a6745` "Reject undeclared OICAP contract fields".

## Closed

`session` is now declared, required for closed-loop and forbidden otherwise, and
all four contracts reject unknown top-level keys. Verified by construction rather
than from the test names:

| Case | Expected | Result |
|---|---|---|
| baseline example | accept | accept |
| `session: {think_time: 50}` | reject | reject — `at session: Additional properties are not allowed` |
| `session: {think_time_s: 0.05}` | reject | reject — same |
| closed-loop with `session` absent | reject | reject — `'session' is a required property` |
| `think_time_ms: -1` | reject | reject — `is less than the minimum` |
| unknown key in scenario / run / sut / slo | reject | reject, all four |
| open-loop **with** `session` | reject | reject |
| open-loop without `session` | accept | accept |

The silent no-op is gone: the two misspellings that previously disabled think
time without comment are now contract errors naming the offending key.

## Not over-tightened

Closing a schema can substitute one defect for another, so the extension points
were checked in the opposite direction:

| Case | Expected | Result |
|---|---|---|
| extra field inside `sut.model` | accept | accept |
| extra field inside `sut.engine` | accept | accept |
| extra field inside `sut.hardware` | accept | accept |
| new SLO target group | accept | accept |
| new metric inside an existing SLO group | accept | accept |

The fixed M1 structures are closed and the declared extension points remain
open, which is the correct division.

Two apparent failures in the first pass of this check were errors in the audit's
own fixtures — an open-loop arrival missing `process: constant`, and an SLO
target written as a scalar where the schema requires an object. Both were
corrected before drawing any conclusion. Recorded because a schema audit that
reports its own malformed fixtures as findings is worse than no audit.

## Independent evidence

- Full repository suite here: **87 tests, OK**.
- The four schemas as **packaged in the built wheel** exist, are valid
  Draft 2020-12, and carry `additionalProperties: false` at the top level — the
  shipped artifact, not the source tree.
- CI run `33046848920` at `f9a6745`, which equals the local and remote HEAD:
  conclusion **success**, all six jobs green, both evidence-exchange directions
  included.
- End-to-end after the tightening: calibrate, run and verify all exit 0,
  apparatus `VALID`, and `verification_scope` still reports the three
  unsupportable attestations as false.

## Verdict

**F3 is closed. No finding remains open against the OICAP M1 checkpoint.**

Across three passes the four blocking and seven non-blocking findings, plus
three raised during re-audit, have each been answered with a change to what the
system measures or refuses. Every claim in this document was re-derived from the
running code and its artifacts; where the audit's own reasoning was wrong — the
concern that the think-time model would cancel itself, and the two malformed
fixtures above — that is recorded alongside the findings.

The checkpoint is ready to be tagged v0.1 on the evidence available.

## What a v0.1 tag does and does not assert

Worth stating plainly at the moment the label is applied, because the label will
outlive the memory of this audit:

- it asserts that the six V01 acceptance criteria have demonstrated evidence,
  including cross-platform evidence produced on machines the author does not
  control;
- it does **not** assert tamper evidence. `verify` establishes unsigned internal
  consistency. Producer identity, detached signatures and external timestamp
  anchoring are all reported false and remain post-M1 work;
- it does **not** assert that the measurement kernel has been exercised against a
  real inference engine under real load. Everything demonstrated here runs
  against the deterministic test protocol. That is the honest boundary of M1 and
  the first thing M2 should cross.

---

# v0.1 release verification — 2026-08-28

Verifying the published release rather than the report of it.

## The tagged code is the audited code

`git diff f9a6745..e62fed3` — the last commit this audit examined against the
tagged commit — touches nine files and **no measurement-kernel logic**:

```
oicap/__init__.py       0.1.0.dev0 -> 0.1.0
pyproject.toml          0.1.0.dev0 -> 0.1.0
tests/test_oicap.py     + a test asserting the two version strings agree
README.md, docs/, uv.lock
```

This matters more than any other check here. A release is only as good as the
correspondence between what was audited and what was tagged, and that
correspondence is exact. The added test is the right kind: it prevents the two
version declarations from drifting apart later, which is a failure that would
otherwise surface only as a confusing bug report.

## The published artifact, verified from GitHub

Downloaded independently rather than compared against a local build:

| Check | Result |
|---|---|
| Release state | published, `draft: false`, `prerelease: false` |
| Tag `v0.1` | annotated, dereferences to `e62fed3` |
| Asset | `moe_cache_eval-0.1.0-py3-none-any.whl`, 53,256 bytes |
| SHA-256 of the downloaded file | `05ba5fe96900fee571b9fee2bbe92d3ff85710e3ac16bbacbe71d0a3a63632af` — matches |
| Wheel metadata | `Version: 0.1.0`, `Requires-Python: >=3.12,<3.13`, three runtime deps |
| `__version__` inside the wheel | `0.1.0` |
| Schemas inside the wheel | all four present |
| CI run `33053496626` | at `e62fed3`, conclusion success, six jobs green, both exchange directions |
| Local full suite | 88 tests, OK |

## The released wheel was run, not only inspected

Everything to this point had been tested from the source tree. The artifact a
user actually downloads had not been. Installed the downloaded wheel into a
clean virtual environment with no repository on the path and ran the full
pipeline from it:

```
validate   exit 0
calibrate  exit 0
run        exit 0
verify     exit 0   ok: true
apparatus  VALID     closed_loop_concurrency_ratio 0.9868
verification_scope   internal_consistency true,
                     calibration_source_manifest_verified true,
                     producer_identity_attested false,
                     detached_signature_verified false,
                     external_timestamp_anchor_verified false
```

The console script resolves, the packaged schemas load through
`importlib.resources` from the installed location, and the honest scope block
survives into the distributed artifact rather than existing only in the
development tree.

## The release notes state the boundary

`OICAP_V0_1_RELEASE_NOTES.md` says in its own voice what this audit asked to be
said at the moment the label is applied: no tamper or producer attestation, no
validation against a real inference engine, no SLO or procurement verdict, and
"a measurement foundation, not a capacity recommendation product."

That the limits are published alongside the release, rather than recoverable
only from an audit trail, is what makes the label safe to apply.

## Verdict

**v0.1 is verified. No finding is open.**

The remaining honest gap is the one the release notes name themselves: every
result demonstrated here was produced against the deterministic test protocol.
Crossing that is M2's first job, and until it is crossed the platform's claims
about real serving behaviour are untested rather than wrong.
