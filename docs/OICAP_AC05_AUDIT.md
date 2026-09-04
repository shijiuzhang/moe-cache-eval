# OICAP AC05 Protocol-Qualification Audit

**Auditor:** Claude (Anthropic), independent of the implementing agent
**Date:** 2026-09-04
**Scope:** commits `34cd893`, `80bd203`, `7227a54`, `fd07e0a`; the AC05 evidence
snapshot; the metrics semantics change and its v0.1 compatibility layer
**Status:** AC05 accepted as a protocol gate. G1–G3 open, none blocking.

## 1. Claims verified independently

Every claim below was re-derived from the artifacts, not read from the hand-off
report.

| Claim | Method | Result |
|---|---|---|
| 4 commits ahead, tree clean, nothing pushed | `git status`, `git rev-list --count` | confirmed |
| `v0.1` tag unmoved | `git rev-parse v0.1^{commit}` | `e62fed3`, unchanged |
| 90 tests pass | `python -m unittest discover -s tests` | 90 run, OK |
| AC05 bundle verifies | `oicap verify …/run` | `ok: true`, `errors: []` |
| False TPOT eliminated | recomputed summary | `tpot.availability: unavailable`, reason `no_authoritative_first_to_last_token_timestamps` |
| Inter-chunk kept separate | recomputed summary | `inter_chunk_latency` count 7, population `content_chunk_intervals_from_successful_requests` |
| Aggregate usage still drives throughput | recomputed summary | `output_tokens: 254`, `output_tokens_per_s: 19.72` |
| `git_dirty: false`, commit `80bd203` | `run/environment.json` | both exact |
| No path/credential/reasoning leakage | grep for `/Users/`, `/private/tmp`, username, `reasoning_content` over the snapshot | no hits |
| Reasoning text discarded, timing kept | `observations.jsonl` | 227 chunks `kind: reasoning`, every one `content: ""` |
| Engine and model identity recorded | qualification report §lines 16–21 | llama.cpp 10210 (`000547513`), Q4_K_M GGUF, model hash `1278394b…` |
| Rehearsal material cannot reach the public tree | wrote a probe file into `private/oicap-ac04/`, ran `git status` and `git check-ignore -v` | ignored, invisible to status |
| Synthetic token authority cannot target a real endpoint | executed the adapter with and without `oicap_test` | guard raises without it |
| Report does not overclaim | qualification report lines 10–11, 98 | states it unlocks v0.2 software and pilot only, explicitly not GPU capacity or formal verdicts |

## 2. The v0.1 compatibility layer — tested end-to-end, not asserted

The claim that "the new verifier still recomputes v0.1 evidence exactly" was the
highest-risk claim in this delivery and **the repository contains no v0.1 evidence
bundle to test it against**. `tests/test_oicap.py::test_legacy_metrics_remain_
recomputable` exercises the legacy formula on a synthesised observation, which
proves the branch works but not that a real v0.1-produced bundle survives.

The auditor therefore produced one:

1. `git worktree add` at `v0.1^{commit}` (`e62fed3`);
2. ran the **v0.1 code** — `calibrate` then `run` — against the deterministic server,
   producing a genuine v0.1 bundle (`metrics_version: 0.1`, `tpot.mean: 1.9444635`,
   population `successful_requests_with_at_least_two_authoritative_output_tokens`);
3. verified that bundle with the v0.1 verifier: `ok: true`, `errors: []`;
4. verified the **same** bundle with the current `0.2-dev1` verifier.

Result: `ok: true`, `errors: []`, recomputed `metrics_version: 0.1`, and the
recomputed TPOT distribution byte-identical to the stored one, legacy population
string included. No `summary_mismatch`.

**The compatibility claim holds against real v0.1 output.** The design detail that
makes it work is that the legacy branch omits the `availability` /
`unavailable_reason` keys entirely rather than adding them with null values — a key
added to the legacy shape would have broken canonical-JSON equality on every
historical bundle. The test asserts this (`assertNotIn("availability", …)`), which
is the right assertion to have written.

Recommendation: commit this generated v0.1 bundle, or an equivalent, as a frozen
regression fixture. The compatibility guarantee currently has no artifact in the
repository that would fail if someone broke it.

## 3. The defect AC05 found, and the fix

The finding is genuine and could only have come from a real engine: llama.cpp's
`completion_tokens` includes hidden reasoning tokens, while OICAP anchors TTFT to the
first user-visible content event. The old TPOT divided a numerator measured from the
visible-content anchor by a denominator counting tokens generated before it —
producing ≈1.35 ms/token against a server actually generating at ≈53 ms/token. A
*flattering* false number, in the direction that would let a non-compliant system
pass.

The fix is correct in principle and in the delivered code: TPOT is computed only from
`token_timestamps_ns`, which the adapter populates only under the synthetic authority;
under `server_usage` it stays empty, so TPOT reports `unavailable` with a
machine-readable reason. Aggregate usage remains available for throughput, where it
*is* authoritative. Verified above on the real bundle.

Two secondary decisions are also right: reasoning events are typed but their text is
discarded, and `_event_kind` distinguishes `role_empty` / `reasoning` / `empty` /
`metadata` so the empty-200 pathology is observable rather than inferred.

## 4. Findings

### G1 — `verify` takes the metrics ruleset from the file it is verifying, and does not report that a superseded ruleset was applied (OPEN)

**Where:** `oicap/evidence.py:355-359`.

```python
stored = json.loads((bundle / "summary.json").read_text(encoding="utf-8"))
metrics_version = str(stored.get("metrics_version", "0.1"))
recomputed = summarize(..., metrics_version=metrics_version)
```

The ruleset used to adjudicate a bundle is read from that bundle's own summary, and
the default when the key is absent is the legacy ruleset. Demonstrated in §2: the
v0.1 bundle verified `ok: true` with a legacy TPOT of 1.94 ms/token present in the
recomputed summary, `verification_scope` identical to a current-ruleset bundle, and
no warning. Nothing in the output distinguishes "verified under current semantics"
from "verified under semantics this project has since established are wrong".

The manifest hash prevents a *third party* from flipping the field, but the project's
own `verification_scope` already states that an unsigned manifest does not prevent a
producer from regenerating altered evidence — so the guarantee here is exactly as
strong as producer honesty, on a field that selects between a correct and a known-
defective metric definition.

Spec §18 requires that importing v0.1 evidence "MUST NOT manufacture a v0.2 SLA or
conformance verdict **when required fields are absent**". The legacy TPOT is not
absent. It is present, well-formed, and wrong. §18 has no rule for **superseded**
semantics, only for missing ones.

This is the same defect family as D1 and E1 in the specification audit — a value on
the trust path taken from the artifact's own self-report — and the specification now
forbids that pattern in three other places.

Required:

1. `verify` output MUST name the ruleset it applied (a top-level `metrics_ruleset`,
   or a `verification_scope` entry), and MUST emit a warning when it is not the
   current one;
2. the v0.2 adjudicator MUST treat legacy-ruleset TPOT and ITL as inadmissible for
   any gate, in the same way `UNAVAILABLE_BY_CONTRACT` is inadmissible;
3. spec §18 needs a superseded-semantics clause beside its absent-field clause;
4. the honest-runner path is already safe — `summarize` defaults to
   `METRICS_VERSION` — so no code change is needed on the emit side.

### G2 — the synthetic-token-authority guard is request-shaped, not endpoint-shaped (OPEN)

**Where:** `oicap/openai_adapter.py:61-68`; `oicap/metrics.py:96`.

The guard is sound in intent and fires correctly (verified):

```python
if token_authority == "synthetic_one_token_per_content_event" and "oicap_test" not in body:
    raise ValueError("… restricted to the deterministic oicap_test protocol …")
```

But the condition inspects the **request body**, not the endpoint. OpenAI-compatible
servers commonly ignore unknown top-level JSON fields, so a run configured with
`synthetic_one_token_per_content_event` and an `oicap_test` key in its workload would
pass the guard while pointed at a real engine. `token_timestamps_ns` would then be
filled with **content-chunk arrival times**, and — because the new TPOT rule requires
only `len(token_timestamps_ns) >= 2` — both TPOT and ITL would report
`availability: available`.

That is inter-chunk timing presented as inter-token timing: precisely what v0.2 spec
§4.3 forbids ("Inter-chunk latency MUST be named separately and MUST NOT satisfy an
inter-token gate") and precisely the defect AC05 just removed from the `server_usage`
path. The guard prevents an accident; it does not prevent a misconfiguration.

Aggravating factor: `token_timing_authority` is recorded per observation but **is not
present in `summary.json`** (verified: zero occurrences). A consumer reading
`latency_ms.tpot.availability: available` therefore has no way to tell whether the
underlying timestamps were authoritative or synthetic.

Required:

1. carry the token-timing authority into the summary, and make the synthetic case
   report its availability with an explicit synthetic qualifier rather than a bare
   `available`;
2. strengthen the guard from a request-shape check to an endpoint-identity check —
   the deterministic server should return a marker the runner verifies, so a real
   engine cannot satisfy it by ignoring an unknown field;
3. AC05's compatibility matrix should record the authority alongside each case.

### G3 — the rehearsal ignore rule is narrower than the risk (MINOR, OPEN)

`.gitignore:10` ignores `private/oicap-ac04/` exactly. Verified working. But material
placed in `private/` itself, or in `private/ac04-notes/`, `private/tender/` or any
other sibling, is **not** ignored, and the failure mode is a tender document committed
to a public repository. Ignore `private/` as a whole; the cost of over-ignoring here
is zero and the cost of under-ignoring is not recoverable by deletion.

## 5. Disposition

**V02-AC05 is accepted as a protocol gate.** The evidence is real, machine-readable,
reproducible from a committed probe rather than from terminal output, correctly
scoped to what it releases, and it found a defect that no fixture-based testing would
have produced. The eight compatibility conditions and three positive controls are
recorded with outcomes, not merely named.

The strongest thing about this delivery is that the executor stopped and reported a
failing metric instead of shipping a passing one, and did not fall back to the
deterministic server when the real engine misbehaved.

G1 and G2 are both instances of the pattern the specification audit closed three
times: a value on the trust path taken from a self-report, and a measurement whose
provenance is not carried alongside its number. Neither blocks AC04. Both should be
fixed before the v0.2 adjudicator consumes TPOT or ITL for any gate, because both
produce a number that reads as authoritative and is not.

G3 should be fixed before the AC04 rehearsal begins, since that is when real
procurement material first exists on this machine.
