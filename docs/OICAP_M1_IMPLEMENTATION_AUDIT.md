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
