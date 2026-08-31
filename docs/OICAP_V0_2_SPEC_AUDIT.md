# OICAP v0.2 Charter / Specification / Acceptance-Criteria Audit

**Auditor:** Claude (Anthropic), independent of the implementing agent
**Date:** 2026-08-30
**Status:** Findings issued; A1–A4 open, A5 advisory

## 0. Objects audited

Audited as delivered on disk, not as described in the hand-off report.

| Document | Lines | SHA-256 |
|---|---|---|
| `docs/OICAP_PRODUCT_CHARTER.md` | 248 | `5855067ad21bb66a4911796d6df03521f1c169c54bd202983d3766958ab2b9e6` |
| `docs/PLATFORM_PRODUCT_SPECIFICATION_V0_2.md` | 795 | `bdf50d37bdb8d5bc5bd498f8864651014ab8d66972e324cff4f8b54898fd21a4` |
| `docs/OICAP_V0_2_ACCEPTANCE_CRITERIA.md` | 544 | `868924acb38de62b6380166a0d9f6f1d92dc736c1e1b053cb4b8e8949bbc1b75` |

## 1. v0.1 immutability — VERIFIED

The claim "v0.1 tracked files, spec, code and tag unchanged" was checked, not accepted.

- `v0.1` is an annotated tag object `b32f53a8…`, resolving to commit `e62fed3`.
- `git diff --stat v0.1^{commit} HEAD` = one file, `docs/OICAP_M1_IMPLEMENTATION_AUDIT.md`,
  +84 lines — the post-release audit record, not a spec or code change.
- `git status --porcelain` shows exactly three untracked files, the three documents above.
  Nothing else added, modified or staged.

Verdict: **PASS.** The v0.2 work is additive and the released v0.1 surface is intact.

## 2. Findings

### A1 — the wall-clock budget has no anchor and no overrun rule (OPEN)

**Where:** Spec §8.1, §8.2; AC10.

§8.1 requires `minimum`, `expected` and `upper_bound`, and forbids an unbounded plan.
It never states what the estimate is computed **from**. Before the acceptance test runs,
the only performance numbers in existence are the buyer's *frozen SLA targets* — the
delivered system's actual throughput is precisely the unknown the test exists to resolve.

Two consequences, neither addressed:

1. **No anchor.** The budget must be derived from the frozen SLA targets (declared output
   length ÷ required decode rate, required sample count, required duration per point), and
   the derivation must be recorded. Otherwise `expected` is an unfalsifiable number.
2. **No overrun rule.** §8.2 forbids the operator from silently dropping coverage, and AC10
   makes an incomplete run yield `INSUFFICIENT_EVIDENCE`. Neither says what happens when the
   plan is complete but *slow* — an under-performing SUT makes every point take longer than
   budgeted, which is the single most likely on-site outcome. The spec must define a per-point
   hard cap derived from the SLA, and state that hitting the cap terminates the point with a
   recorded reason code, never a silent extension into the next appointment.

**Second-order:** AC10 validates the estimator against "at least one end-to-end timed
execution". At v0.2 the only qualified endpoint is CPU llama.cpp (AC05), which is one to two
orders of magnitude slower than the GPU stack the budget is meant to size. The estimator's
*accuracy* therefore cannot be validated at v0.2. AC10 should say so and limit its own claim
to structural correctness (bounded, complete, components sum) — with predictive accuracy
deferred to AC20's GPU envelope.

### A2 — the preflight reference endpoint's timing profile is unbound (OPEN)

**Where:** Spec §7.2; AC09.

§7.2 requires the pre-departure preflight to run "against a deterministic OICAP test endpoint
or replay fixture at the maximum planned concurrency and event rate". It never requires that
endpoint to be **paced from the frozen SLA**.

Measured on the shipped v0.1 `DeterministicServer` (`oicap/test_server.py`), 60-token
responses, requested concurrency reached in both arms:

| mode | requested N | peak in-flight | wall time |
|---|---|---|---|
| SLA-paced (TTFT 200 ms, 50 ms cadence) | 128 | 128 | 3425 ms |
| zero-delay (default) | 128 | 125 | **83 ms** |
| SLA-paced | 512 | 512 | 3491 ms |
| zero-delay (default) | 512 | 496 | **277 ms** |

Peak concurrency is reached either way, so a naive preflight reports "512 concurrent: OK".
But the unpaced arm holds those streams for 277 ms. **A preflight can certify a client for
0.3 seconds of work when the appointment it is certifying is hours long.** Sustained hold —
not momentary peak — is what exhausts descriptors, stream-parser memory and scheduler capacity.

Required: the compiler MUST emit a preflight endpoint profile derived from the frozen SLA
(TTFT, decode cadence, output-length distribution, class mix) **and a minimum sustained
duration**, and the preflight MUST be refused if the endpoint was not paced to it. AC09 needs
a matching negative control: an unpaced or short-duration preflight is rejected, not accepted.

**Correction to my own prior concern.** I expected `ThreadingHTTPServer` + `time.sleep`
(one OS thread per in-flight request) to distort timing at acceptance-scale concurrency, and
said so. Measured, it does not: at N = 1024 paced streams the median per-request duration was
3449 ms against an ideal 3150 ms — the same ~7–9 % inflation present at N = 8, i.e. constant
`time.sleep` overshoot, not concurrency collapse. The reference endpoint is adequate. The
defect is in the specification, not the server.

One residual: reference-endpoint TTFT p95 drifts from 206 ms at N = 8 to 321 ms at N = 1024
(accept-backlog artifact). It is a property of the harness, not of any SUT, and the spec should
forbid reading preflight TTFT as a measurement of anything but client health.

### A3 — "silence is not conformance" is unenforceable as written (OPEN)

**Where:** Charter §5.3; Spec §6.1; AC02.

Charter §5.3 and Spec §6.1 both assert that a deployment field is exempt only when explicitly
marked `not_required`, and that silence never means conformance. But §6.1 introduces the field
list with "Required fields **MAY** include:". A permissive list cannot force an explicit state:
if the buyer's `sut-requirements.yaml` simply never mentions quantization, there is no field to
be silent *about*, and the rule has nothing to bind to.

AC02's positive control — "required deployment field with no value or state" — tests a field
that is **present and empty**. It does not test a field that is **absent**, which is the case
the invariant is actually about.

Required: a normative, versioned catalogue of deployment field keys, each of which MUST carry
exactly one of `required` / `allowed_set` / `not_required` / `informational`; the schema rejects
a `sut-requirements.yaml` that omits any catalogue key. Add the AC02 control: omit `quantization`
entirely from a contract and show that freeze is refused with a path-specific error.

Without this the most valuable invariant in the Charter is decorative — and the omission it
fails to catch (nobody wrote down the quantization requirement) is exactly the omission a
supplier benefits from.

### A4 — `INSUFFICIENT_EVIDENCE` is simultaneously a project state and a verdict value (OPEN)

**Where:** Spec §2 (line 103) vs. §4.4, §5.3 (Charter), §6.4, §9.2.

§2 lists `INSUFFICIENT_EVIDENCE` as an exceptional **project state**. §4.4 makes it a **gate
result**, and both `service_sla_verdict` and `deployment_conformance_verdict` take it as a
**verdict value**. A project that completes adjudication with an insufficient verdict is then
in state `ADJUDICATED` and state `INSUFFICIENT_EVIDENCE` at the same time, and the record
cannot say which. Two different consumers will serialize this two different ways.

Required: rename the state (`ADJUDICATED_INSUFFICIENT`, or drop it — the verdict fields already
carry the information and §2's other exceptional states are all genuinely pre-adjudication).
§13's requirement that "the API MUST expose the same state machine and reason codes as the UI"
makes this a wire-format problem, not a naming preference.

### A5 — rehearsal should surface physically unmeetable SLAs (ADVISORY)

**Where:** AC04.

AC04's findings list covers fields procurement cannot supply and phrases that are ambiguous.
It does not cover a requirement that is **unambiguous, typed, freezable and impossible** —
e.g. a concurrency/latency/model-size combination no delivered system can satisfy. OICAP would
correctly report FAIL, and would be correct; but the buyer froze a doomed tender and OICAP was
the instrument that revealed it only after the appointment.

Detecting this in general needs prediction, which is a stated non-goal and should stay one.
The rehearsal, however, costs nothing and is exactly where such a requirement first becomes
visible to a human. Add one bullet to AC04's findings list: *requirements that are typed and
freezable but of doubtful physical achievability, and how the authoring UI flags them without
asserting a prediction.*

## 3. Accepted without finding

- **Two independent verdicts** (Charter §5, Spec §6.4, AC13). The substituted-smaller-model
  control — `service_sla_verdict: PASS`, `deployment_conformance_verdict: FAIL`, overall FAIL —
  is the correct discriminating case and it is present in the acceptance criteria, not only in
  prose.
- **L2 physical-memory envelope** (Charter §5.2, Spec §6.3). This is a genuine improvement on
  the auditor's original suggestion. The refinements — a conservative envelope over the complete
  declared topology including tensor parallelism, offload, KV reservation and engine overhead;
  and the asymmetry that observation *below* the minimum is contradictory while agreement is
  only supporting evidence — correct a real defect in the auditor's simpler single-GPU version.
- **Undeclared-proxy detection** (Charter §4, Spec §6.3, AC13). Listener ownership and active
  connection inspection was not raised by the auditor and closes a real evasion path.
- **Technical verdict / commercial disposition separation** (Charter §6, Spec §12.2, AC17).
  Placing retest count, mutable-path allowlist and supersession rules inside the frozen
  acceptance policy — while refusing to derive `ACCEPT`/`DEDUCT`/`REJECT` — is the correct
  boundary. The mutable-path allowlist in particular converts a commercial-looking clause into
  a checkable technical one.
- **Pilot labelling** (Spec §1.2, AC16). Requiring the pilot marking on every surface, and
  failing the criterion when the JSON is correct but the UI hides the warning, is the right
  shape for a claim gate.
- **No in-place edit of the v0.1 specification.** Verified in §1 above.

## 4. Disposition

A1–A4 are specification defects, not implementation defects; all four are cheap to fix now and
expensive to fix after code exists against them. A5 is advisory.

Recommended: resolve A1–A4 in the documents before the schema-freeze decision (AC01–AC04), and
re-issue the three files for a confirming pass. No code should be written against §7.2 or §8.1
until A1 and A2 are settled, because both change what the compiler must emit.

---

# Confirming pass — 2026-08-30

## 5. Objects re-audited

| Document | Lines | SHA-256 |
|---|---|---|
| `OICAP_PRODUCT_CHARTER.md` | 251 | `a06cbc0315372a2a08e902a030ddc4499274c94f0e5bacecf29dd83d923bc2b6` |
| `PLATFORM_PRODUCT_SPECIFICATION_V0_2.md` | 892 | `f6bb84b1d89f5681f7cbc46eea7eeb495bbefcb4701989b087a3b7cc3a10d85e` |
| `OICAP_V0_2_ACCEPTANCE_CRITERIA.md` | 588 | `aad3623e5770d8e43e1222fa3db5b8ecce146fe48005d4267ae625ccefe47afe` |

All three hashes moved. This audit file's own hash is unchanged
(`3f8c0fc9…`), confirming the implementer did not edit the audit record.
`git status` still shows four untracked files and no tracked modification; the
v0.1 surface remains untouched.

## 6. Disposition of A1–A5

**A1 — CLOSED.** §8.1 now anchors the budget to the frozen SLA and requires
`budget-derivation.json` with inputs, formulas, rounding and sources; a plan that
cannot derive them must not freeze. The three cap outcomes are the correct
trichotomy, and the sentence forbidding the runner from turning "an SLA-derived
service timeout into `INSUFFICIENT_EVIDENCE`" closes the loophole that would have
let an under-performing SUT collect the benefit of the doubt. AC10 correctly limits
its own claim to structural completeness and defers accuracy to AC20. See B1 below.

**A2 — CLOSED.** `preflight-endpoint-profile.yaml` is derived from the frozen SLA,
carries a minimum sustained duration and cumulative request/chunk/byte volume, and
the runner must independently measure realized pace and reject zero-delay, unpaced,
short or out-of-tolerance reference runs. "Merely reaching the requested peak
in-flight count is not a passing preflight" states the measured defect directly.
The `concurrency_hold` / `event_rate` profile split is a refinement the auditor did
not propose and covers both extremes rather than one. The harness-health clause
disposes of the reference-endpoint TTFT drift.

**A3 — CLOSED.** §6.1 now defines a versioned catalogue of fourteen keys, each of
which must appear exactly once with exactly one `requirement_state`; the schema must
reject an absent key, and omitting `quantization` is explicitly not equivalent to
declaring it `not_required`. Catalogue additions require a version bump with no
silent upgrade at freeze. Charter §5.3 and AC02 carry matching language. See B2 below.

**A4 — CLOSED.** `INSUFFICIENT_EVIDENCE` is removed from the project state list, and
§2 states explicitly that it is a gate or verdict value and that a completed project
whose verdict is insufficient remains `ADJUDICATED`. No residual use of the term as
a state remains in the specification.

**A5 — CLOSED.** AC04's findings list now includes requirements that are typed and
freezable but of doubtful physical achievability, with the correct constraint that
the authoring flow warns without pretending to predict performance.

Cross-checks: AC01–AC20 numbering continuous; the three cap reason codes appear in
both the specification and the acceptance criteria and nowhere else; all internal
document links resolve.

## 7. New findings introduced by the fixes

### B1 — the SLA-derived hard cap has no margin, and contradicts §4.4 (OPEN)

**Where:** Spec §8.1 vs §4.4.

§4.4 requires that a measured value close enough to instrument resolution that the
threshold cannot be distinguished MUST return `INSUFFICIENT_EVIDENCE`. §8.1 derives
the per-point hard cap from the SLA boundary and makes a breach
`SUT_POINT_DEADLINE_EXCEEDED` with affected service gates `FAIL` — with no resolution
or variance carve-out, and no requirement that the cap carry any margin over the
boundary it is derived from.

A SUT sitting *at* the SLA boundary has roughly even odds of breaching a
zero-margin boundary-derived cap on any given repeat. The same physical situation
therefore yields `INSUFFICIENT_EVIDENCE` when §4.4 evaluates it and `FAIL` when §8.1
caps it. Two clauses of one specification disagree about the same measurement.

This is the **false-FAIL** direction: a compliant delivery rejected on a timing
artifact. For an acceptance instrument whose entire value is that both parties accept
its verdicts, a demonstrated false FAIL is more damaging than a missed FAIL.

The mechanism to fix it already exists — §8.1 permits a versioned, pre-frozen timeout
multiplier — but nothing requires it to be non-zero. Required:

1. the cap MUST exceed the SLA-boundary window by a frozen margin no smaller than the
   calibrated instrument resolution plus the frozen run-to-run variance allowance,
   and `budget-derivation.json` MUST show that margin as a named term;
2. when a point breaches the cap but the partial evidence places the metric within
   instrument resolution of the threshold, §4.4 governs and the gate is
   `INSUFFICIENT_EVIDENCE`. `SUT_POINT_DEADLINE_EXCEEDED` yields `FAIL` only when the
   partial evidence independently supports it;
3. AC10 needs the corresponding control: a SUT paced *at* the SLA boundary must not
   produce `FAIL` from cap breach alone.

### B2 — the physical memory envelope can lose its inputs while the contract looks complete (OPEN)

**Where:** Spec §6.1 vs §6.3; second-order consequence of the A3 fix.

§6.3's conservative memory envelope is computed "from declared weights, quantization,
sharding, CPU/GPU offload, KV reservation and engine overhead". Under the new
catalogue, `parallelism` and `memory_and_offload` are ordinary keys that a contract
may legitimately state as `not_required` or `informational`.

When it does, the envelope has no declared inputs — yet every catalogue key is
present and stated, so the contract passes freeze as complete. §6.3's unavailability
clause covers only the case where "process inspection is technically unavailable"; it
does not cover the case where the contract never declared the topology.

The result is that the strongest anti-substitution control in the product can be
silently disabled by a contract that looks fully specified. A buyer who does not care
about the parallelism strategy per se — a reasonable position — would disable the
memory check without being told.

Required: the specification MUST state that the physical memory-envelope check has
`model_identity`, `quantization`, `parallelism` and `memory_and_offload` as
prerequisites at `required` or `allowed_set`; that a contract stating any of them
`not_required` or `informational` renders the check unavailable; and that the
authoring flow and the report both say so explicitly rather than omitting the check.
AC13 needs a control: a contract with `parallelism: not_required` shows the memory
check as unavailable-by-contract in the conformance matrix, not as passed or absent.

## 8. Confirming-pass disposition

A1–A5 are closed on inspection of the delivered text, and the acceptance criteria
carry matching controls rather than prose alone. B1 and B2 are new, both second-order
consequences of the A1 and A3 fixes, and both are specification-level and cheap now.

Recommended: resolve B1 and B2, then the schema-freeze decision (AC01–AC04) may
proceed. Neither finding blocks work outside §8.1 and §6.3.

Minor, no action required: Charter §5.3 is titled "Overall technical result" but its
closing paragraph states the catalogue completeness rule, which is a contract-shape
rule rather than a verdict-combination rule.

---

# Second confirming pass — 2026-08-30

## 9. Objects re-audited

| Document | Lines | SHA-256 |
|---|---|---|
| `OICAP_PRODUCT_CHARTER.md` | 255 | `ac4dcf954515e51eac96656693a8b9cfa8908fcb7b2ec03d9edd3d2e99d930f5` |
| `PLATFORM_PRODUCT_SPECIFICATION_V0_2.md` | 939 | `5d8f13a204edc428b2ce7cddec85955c46efa5d81717fc1e1bdc8dc4f8127078` |
| `OICAP_V0_2_ACCEPTANCE_CRITERIA.md` | 614 | `c0076cdd18c48a5a1f74fe93de8472e0c8f6a490308416027879693027f2a89b` |

This audit file's hash was `8517450169…` before this section was appended, unchanged
from the previous pass. `git status` still shows four untracked files, no tracked
modification, v0.1 untouched.

## 10. Disposition of B1 and B2

**B1 — CLOSED.** §8.1 adds `deadline_margin` as a named derivation term (item 5) built
from an instrument-resolution reserve plus a frozen inter-run-variation allowance, and
item 6 requires the point cap to add the *complete* margin beyond the SLA-boundary
window. The combined margin MUST be non-zero, and both components must be listed
separately with units and the mapping formula.

The fix is better than what was requested in three respects:

1. adjudication is now an explicit **ordered precedence** — apparatus validity, then
   threshold indistinguishability, then cap cause — rather than a set of coordinate
   rules that an implementer would have to reconcile;
2. §4.4 itself was amended to say the indistinguishability rule governs an observation
   that reaches a wall-clock cap and that the cap alone cannot override it with `FAIL`,
   so the contradiction is closed from both sides rather than only from §8.1;
3. the preflight must *demonstrate* that actual timing resolution does not exceed the
   reserved value, which prevents the margin from being a declared fiction. This was
   not requested. See C1.

`WITHIN_MEASUREMENT_RESOLUTION` is used correctly as a reason code attached to
`INSUFFICIENT_EVIDENCE`, not as a fourth gate value; the §4.4 enum and the two verdict
enums remain three-valued. This was checked specifically because a new adjudication
outcome is where an A4-class state/value collision would reappear.

AC10 carries controls in both directions: a zero combined margin is rejected; an
endpoint paced *at* the boundary with jitter inside the calibrated resolution cannot
receive `FAIL`; an endpoint slower than boundary-plus-margin must receive
`SUT_POINT_DEADLINE_EXCEEDED`. Both error directions are tested, which is what makes
the pair meaningful.

**B2 — CLOSED.** §6.3 names six catalogue prerequisites that must each be `required`
or `allowed_set`; the conformance matrix emits `UNAVAILABLE_BY_CONTRACT` with the
missing prerequisites and the lost effect; contract-caused and environment-caused
unavailability must not be merged; and a contract whose acceptance policy depends on
the check cannot freeze without the prerequisites, while a buyer who does not depend
on it may knowingly accept reduced assurance with a persistent report warning.

The added `allowed_set` bounding rule — usable only when a conservative minimum can be
computed across the whole set — was not requested and closes the obvious workaround of
satisfying the prerequisite with a set so wide that no minimum exists.

Cross-checks: AC01–AC20 continuous, twenty criteria present; the new status codes
appear consistently in Charter, specification and acceptance criteria; internal links
resolve; no code was written against §7.2 or §8.1.

## 11. New finding

### C1 — the resolution reserve is validated in the office, never on the measurement path that adjudicates (OPEN)

**Where:** Spec §8.1 (line 534) vs §7.2 (line 480) and §9.3.

§8.1 requires that "the **preflight** calibration MUST demonstrate that the actual
relevant timing resolution does not exceed the reserved value". The preflight runs in
the buyer's office, against a local deterministic reference endpoint, over loopback.

The gates are adjudicated on site, over the delivery network — a different NIC path,
possibly a jump host or VPN, shared switching, and an unknown noise floor. On-site
timing resolution can be materially worse than the loopback figure that justified the
reserve.

§7.2 already concedes that a local preflight "does not validate the delivery site's
network" and requires a separate on-site check — but that check is scoped to
"connectivity and client-saturation". Nothing re-establishes timing resolution against
the actual measurement path, and nothing makes on-site resolution exceeding the frozen
reserve an apparatus-invalidity condition. §9.3's per-metric calibration record does
not say which calibration — office or site — the gates are adjudicated against.

The consequence is that `deadline_margin` can be correctly derived, correctly frozen,
correctly demonstrated in the office, and still be undersized where it is used. That
reintroduces exactly the false-FAIL failure mode B1 was written to remove, relocated
from the office to the site — the one place it produces a disputed verdict against a
real supplier.

Required:

1. the on-site pre-measurement check MUST re-establish the relevant per-metric timing
   resolution over the actual measurement path, before the first measured phase;
2. an on-site resolution exceeding the frozen reserve MUST invalidate the apparatus —
   §8.1's precedence item 1 then handles it correctly — rather than allowing the run to
   proceed on an undersized margin;
3. §9.3 MUST state that gate adjudication uses the on-site calibration record, and the
   evidence bundle MUST carry both figures so the difference is visible;
4. AC06 or AC10 needs the control: an on-site path whose measured resolution exceeds
   the frozen reserve blocks the measured phase and cannot produce a service verdict.

**Pattern worth carrying into implementation.** A2, B1 and C1 are one defect family:
a property is verified against a stand-in — an unpaced reference endpoint, a loopback
calibration — rather than against the path that carries the real measurement. The
specification is now correct about this in §7.2 for network and in §6.3 for contract
prerequisites; C1 is the last place where the stand-in is still treated as sufficient.
Every check added during implementation should be asked the same question: *is this
validated against the thing that will actually be measured, or against a convenient
substitute?*

## 12. Second-confirming-pass disposition

B1 and B2 are closed on inspection of the delivered text, with acceptance controls in
both error directions. C1 is the single open finding and is confined to §8.1's last
sentence on calibration, §7.2's on-site check, §9.3 and one acceptance control.

The schema-freeze decision (AC01–AC04) does not depend on C1 and may proceed. C1 must
be resolved before any code is written against §8.1's cap enforcement, because it
changes when the runner is permitted to begin a measured phase.

---

# Third confirming pass — 2026-08-30

## 13. Objects re-audited

| Document | Lines | SHA-256 |
|---|---|---|
| `OICAP_PRODUCT_CHARTER.md` | 257 | `5457205998b61dda4f439f99b7a59534aeff8be2e8451a1948621c7048b45671` |
| `PLATFORM_PRODUCT_SPECIFICATION_V0_2.md` | 990 | `8b4f98dfdb1c45d4b3f710faa1e2a4eb2cdcaa23c919d860236ec659f0dc505e` |
| `OICAP_V0_2_ACCEPTANCE_CRITERIA.md` | 635 | `3863d8c1618ecceef4bbded0495a8bc19ed80ee13948b692ddb24f0d519ec472` |

Audit file hash before this section: `1a510cf907…`, unchanged. `git status`: four
untracked files, no tracked modification, v0.1 untouched.

## 14. Disposition of C1 — CLOSED

New §7.3 separates the two calibrations correctly. The office preflight is explicitly
demoted — §8.1 now states it "is not the resolution used for adjudication" — and the
on-site same-path calibration must run immediately before the measured phase, after
routing, VPN/jump path, TLS termination, load balancer and ingress are final, using
the formal client topology and traversing the same interfaces. Route, endpoint and
boundary fingerprints are recorded; a post-calibration path change invalidates it.
§9.3 states that formal gate adjudication uses the on-site figure, and the bundle
carries both with their path fingerprints. On-site resolution above the frozen reserve
emits `CLIENT_APPARATUS_INVALID`, moves the attempt to `RUN_INVALID`, and forbids the
measured phase. All four required elements are present.

**The abuse vector this fix created was anticipated and closed.** Allowing
outside-boundary variation to count as instrument resolution is a new degree of
freedom that could be used to enlarge the margin by attributing SUT jitter to the
apparatus. §7.3 closes it from both sides: in-boundary network, ingress and serving
variation "remain part of service performance: their latency is not subtracted or
forgiven as instrument noise", and — the load-bearing sentence — "Uncertainty is not
reassigned from the SUT to the instrument merely because the path is difficult to
decompose." An undecomposable path yields apparatus-invalid, not a wider margin. The
default is the conservative one. AC06 carries both controls, including injected
in-boundary variation that must not be reclassified.

The measurement boundary is defined in `project.yaml`, which is part of the frozen
contract set under §3, so the boundary cannot be chosen after seeing data.

## 15. New finding

### D1 — the calibration responder is on the trust path with no assigned custody (OPEN)

**Where:** Spec §7.3 vs §5.2 and Charter §3.3.

§7.3 introduces a "registered deterministic calibration responder at the frozen SUT
boundary". Its output now:

- gates whether the formal measured phase may begin at all;
- sets the on-site per-metric resolution that §4.4 uses for threshold
  indistinguishability;
- sets the resolution that §8.1 compares against the frozen reserve;
- sets the resolution that §9.3 uses for `within_noise`.

It is therefore one of the most trusted components in the system. But:

1. **It is not in the pack.** §5.2's compiler output lists `runner-lock.json`,
   `preflight-endpoint-profile.yaml` and eleven other artifacts. The responder and an
   on-site calibration plan are not among them. Only "method, responder and runner
   versions" are recorded in `onsite-path-calibration.json` — after the fact.
2. **Nobody owns it.** Charter §3.3 says the supplier "does not control the official
   runner, sealed test instance, uploaded evidence or canonical adjudicator". The
   responder is not in that list. §7.3 never says who supplies, deploys or operates it.
3. **Its identity is never verified.** "Registered" is not defined, and no clause
   requires the runner to check the responder against a pack-declared hash before
   accepting a calibration.

The responder must sit at the frozen SUT boundary — physically at the delivery site,
which is the supplier's ground. A supplier-supplied responder that understates path
variation makes real buyer-side apparatus noise get attributed to the SUT, pushing
marginal gates toward `FAIL`; one that overstates it blocks the run. The first is the
false-FAIL direction that B1 and C1 exist to prevent, reintroduced through a component
neither the trust model nor the pack manifest covers.

Required:

1. add the responder — image or binary, version and hash — to §5.2's compiler output
   and to `pack-manifest.json` or `runner-lock.json`;
2. state in §7.3 that it is deployed and operated under buyer control, and add it to
   Charter §3.3's list of components the supplier does not control;
3. require the runner to verify the responder's identity against the pack-declared
   hash before a calibration is admissible, and to reject an unregistered or
   version-mismatched responder;
4. add the AC06 control: a calibration served by a responder that is not the
   pack's own, or whose hash does not match, is inadmissible and the apparatus is
   invalid.

**Pattern.** C1's fix added a new trusted component; the trust model, the pack
manifest and the role assignments were not extended to cover it. This is a different
family from A2/B1/C1 (stand-in versus real path) and worth a standing check of its
own: *when a fix introduces a component, does Charter §3.3, §5.2's pack contents and
the runner's verification list all account for it?* Two of the three do not here.

## 16. Third-confirming-pass disposition

C1 is closed, including the abuse vector its own fix opened. AC01–AC20 continuous;
the final audit summary now poses twelve questions and covers the on-site resolution,
false-FAIL and `UNAVAILABLE_BY_CONTRACT` cases explicitly.

D1 is the single open finding. It is narrow — four edits across §5.2, §7.3, Charter
§3.3 and AC06 — and introduces no new mechanism, only custody and verification for a
component the specification already requires.

**Schema freeze (AC01–AC04) may proceed; D1 does not touch the contract schemas.**
D1 must be resolved before code is written against §7.3, because it determines what
the pack must ship and what the runner must verify before it is allowed to measure.

---

# Fourth confirming pass — 2026-08-30

## 17. Objects re-audited

| Document | Lines | SHA-256 |
|---|---|---|
| `OICAP_PRODUCT_CHARTER.md` | 264 | `435e25423e8fa63dd7d74ad5d02f2677700858478fa34eee054f3c440cda15aa` |
| `PLATFORM_PRODUCT_SPECIFICATION_V0_2.md` | 1039 | `a79e394806a413f54888d2c7ea0f6fc6ca2398a401120e95a157b291fd74a97a` |
| `OICAP_V0_2_ACCEPTANCE_CRITERIA.md` | 655 | `6d5a24d9c18ed0b533548dd683da5efc40b01729942ee3ff8fdc180627b6f5fd` |

Audit file hash before this section: `ce31c08e47…`, unchanged. `git status`: four
untracked files, no tracked modification, v0.1 untouched.

## 18. Disposition of D1 — CLOSED

All four required edits are present, and the fix goes further than requested.

Custody is assigned in Charter §3.2 (the buyer test operator "controls the official
runner, the pack-pinned calibration-responder artifact" and starts it at the frozen
boundary from the pack-named artifact) and §3.3 adds the responder to the list of
things the supplier does not control, while allowing the supplier to provide only the
agreed boundary location and network conditions. Charter §4 adds "an unregistered or
supplier-controlled calibration responder biases the apparatus" to the threat list.
§5.2 ships `calibration-responder/responder-lock.json` plus the platform binary or
immutable OCI reference and `onsite-calibration-plan.yaml`; `runner-lock.json` pins
both runner and responder by digest; `pack-manifest.json` covers the artifact or OCI
descriptor. Identity mismatch emits `CALIBRATION_RESPONDER_IDENTITY_INVALID`, makes
the apparatus invalid and moves the attempt to `RUN_INVALID`.

**The decisive addition is §7.3's launcher rule** (line 529): the buyer-controlled
launcher MUST compute the binary or resolved OCI manifest digest, and the responder's
self-report is not trusted. AC06 carries the matching adversarial control — "a
substituted responder that self-reports the expected digest/build identity while the
buyer-side launcher computes a different artifact digest". That is exactly the attack
D1 described, tested from the attacker's side rather than the happy path.

Charter invariant 11 — "No unowned trusted component" — generalizes the finding into a
standing rule rather than patching the single instance. The honesty boundary is also
kept: these checks bind to the official pack and a buyer-controlled process and are
not equivalent to hardware attestation against a malicious host.

## 19. New finding

### E1 — invariant 11 is not yet satisfied by the quality validators (OPEN)

**Where:** Charter §7 invariant 11 vs Spec §5.2 (line 270), §7.2 (line 486), §10 and
§11.3.

Invariant 11 requires that every component able to affect load, timing resolution,
evidence or adjudication have an explicit owner, a versioned artifact, pack-manifest
identity **and runtime validation before it can influence a formal result**. Applied
to the specification that declares it, the quality validators do not meet it.

A quality validator determines quality gate outcomes, which feed `service_sla_verdict`
directly. Its current treatment is:

- it ships in the pack as `quality-hooks/` — pack presence ✓;
- §10 requires "validator version and deterministic inputs" — a **declared** property,
  not a verified digest;
- §7.2's preflight checks "quality-hook availability" — **presence, not identity**;
- §11.3 states that for buyer-local private validation the server "does not
  independently establish that each semantic outcome was correct".

So the validator's identity is self-declared, and the server cannot recompute what it
decided. That combination makes validator identity **more** load-bearing than the
responder's, not less — the responder's output can at least be cross-checked against
the office calibration, whereas a private-reference quality outcome has no second
source anywhere in the system.

`runner-lock.json` pins "the official runner and every permitted calibration-responder
platform artifact" — an enumerated list that does not include quality hooks.

The realistic failure is not malice. Charter §3.2 states the operator wants a correct
result but that intent does not guarantee correct execution. A wrong validator version
pulled on site, or a validator locally patched by a well-meaning engineer because it
"false-positives" against the delivered system, produces a clean-looking bundle whose
quality gate outcomes nothing in the pipeline can contradict.

Required:

1. `runner-lock.json` (or a sibling `quality-hooks-lock.json`) MUST pin every packaged
   validator by version and digest, and `pack-manifest.json` MUST cover them;
2. the runner MUST verify validator digests against the pack before any formal quality
   evaluation, computing the digest itself rather than accepting the validator's
   self-reported version — the same launcher rule §7.3 already applies to the responder;
3. a mismatch MUST invalidate the affected quality gates rather than reporting them,
   with a stable reason code alongside `CALIBRATION_RESPONDER_IDENTITY_INVALID`;
4. the uploaded quality record in §5.4/§11.2 MUST carry the **verified** digest, not
   only the declared validator version, so the server can confirm which validator
   produced an outcome it cannot itself recompute;
5. AC12 needs the control: a validator whose digest does not match the pack cannot
   produce a quality `PASS`, including one that self-reports the expected version.

**Secondary, same invariant, lower severity:** the preflight reference endpoint gates
the formal plan and produces `client-preflight.json` as evidence, but §5.2 ships only
`preflight-endpoint-profile.yaml`, not a pinned endpoint artifact. This is materially
weaker than the validator case — §7.2 already requires the runner to independently
measure realized pace and reject profile-hash mismatches, and §8.1 has demoted the
office resolution out of adjudication — so the endpoint is partly self-checking and
cannot reach a verdict. Worth one sentence in §7.2 acknowledging the residual, not a
new artifact.

## 20. Fourth-confirming-pass disposition and convergence

D1 is closed, with the launcher rule and the self-reporting-responder control both
present. AC01–AC20 continuous; internal links resolve; v0.1 untouched.

E1 is the single open finding, and it was produced by applying the implementer's own
new invariant to the document that declares it — which is the correct use of a
universal rule and the reason invariant 11 was worth adding.

**On convergence.** Five rounds: A1–A5 (five findings, structural), B1–B2 (two,
second-order), C1 (one, third-order), D1 (one, custody of a component the previous fix
created), E1 (one, a component the newest invariant reaches). Each round's findings are
narrower than the last and each fix has been sound, including anticipating abuse
vectors the auditor had not named. This is convergence, not a treadmill.

E1 is worth one more round because a verdict-determining component with self-declared
identity, whose output the server cannot recompute, is the same class of defect as D1
and the fix is the same mechanism already written for the responder. After E1 the
remaining items would be genuinely marginal, and the correct next step is to stop
reviewing prose and start the two activities that generate new information rather than
new text: the AC04 procurement rehearsal and the AC05 CPU llama.cpp protocol
qualification. Both will find things no amount of specification review can.

---

# Fifth confirming pass — audit closed — 2026-08-31

## 21. Objects re-audited

| Document | Lines | SHA-256 |
|---|---|---|
| `OICAP_PRODUCT_CHARTER.md` | 274 | `a8adf7cd6998c911c5d3e96ac1bed83115c13bd59c98dadc64c3e21868774410` |
| `PLATFORM_PRODUCT_SPECIFICATION_V0_2.md` | 1081 | `8c3487cc0bd12545b8fcbde9758f1307c8f0946a3357f8ba72209233d6ae9b41` |
| `OICAP_V0_2_ACCEPTANCE_CRITERIA.md` | 676 | `380f43e06ecb389bc91a301487d40c13a270a4425bfe10120a67495ade9c0016` |

Audit file hash before this section: `1e24f485a9…`, unchanged across all five rounds.
`git status`: four untracked files, no tracked modification. `git diff v0.1^{commit}
HEAD` remains a single file, `docs/OICAP_M1_IMPLEMENTATION_AUDIT.md`, +84 lines.

## 22. Disposition of E1 — CLOSED

§5.2 now ships `quality-hooks/quality-hooks-lock.json` plus validator artifacts or
immutable OCI references; `runner-lock.json` references the quality-lock digest;
`pack-manifest.json` covers every validator artifact and OCI descriptor. §10 makes
every validator that can influence a formal quality gate a trusted pack component and
imposes a five-step pre-evaluation procedure on the buyer-controlled runner.
Mismatch emits `QUALITY_VALIDATOR_IDENTITY_INVALID`; the gate is
`INSUFFICIENT_EVIDENCE`, cannot emit `PASS`, and its requests cannot contribute to
qualified goodput.

Three elements exceed what was requested and each closes a real hole:

1. **Full execution closure, not just the artifact.** The lock pins runtime or
   dependency lock, configuration digest and private-reference manifest hash. Pinning
   only the validator binary would have left the same validator producing different
   verdicts under a different dependency set or reference file — which is the actual
   way a validator silently changes behavior in practice.
2. **Content-addressed read-only staging** (step 4) and explicit post-verification
   mutation detection. This closes the verify-then-swap window that a digest check
   alone leaves open. AC12 tests it directly — "a validator artifact mutated after
   initial verification rather than executed from the content-addressed read-only
   stage".
3. **Goodput exclusion.** Requests under an invalidated validator cannot contribute
   to qualified goodput. Without this, an invalidated quality gate would still have
   laundered its requests into the throughput population — the exact trade of quality
   for speed that invariant 6 forbids.

AC12's three adversarial controls are correctly framed from the attacker's side,
including the self-reporting substitute, and a reverse identity control is present.

**Preflight reference endpoint — residual accepted, correctly.** §7.2 lines 512–517
state that the office reference endpoint is not a verdict-producing component, that
its binary is not pack-locked in v0.2, that an endpoint identity claim carries no
credit, and that a wrong endpoint can cause preflight refusal but cannot obtain a
formal `PASS`. The residual is *recorded rather than promoted into the formal trusted-
component set*. That is the correct disposition of a knowingly accepted limitation:
bounded, written down, and not disguised as a control.

## 23. Final consistency checks

- AC01–AC20 present and continuous, twenty criteria.
- All internal document links resolve.
- All eight adjudication reason codes — `SUT_POINT_DEADLINE_EXCEEDED`,
  `CLIENT_APPARATUS_INVALID`, `EXTERNAL_INTERRUPTION`, `WITHIN_MEASUREMENT_RESOLUTION`,
  `UNAVAILABLE_BY_CONTRACT`, `UNAVAILABLE_BY_ENVIRONMENT`,
  `CALIBRATION_RESPONDER_IDENTITY_INVALID`, `QUALITY_VALIDATOR_IDENTITY_INVALID` —
  appear in both the specification and the acceptance criteria, each defined once
  normatively and exercised by at least one control.
- Gate and verdict enums remain three-valued; no reason code was promoted to a fourth
  outcome across five rounds of additions.
- v0.1 specification, code, schemas, evidence and tag untouched throughout.

## 24. Audit closed

Ten findings were raised across five rounds and all ten are closed: A1–A5 (structural),
B1–B2 (second-order consequences of the A1 and A3 fixes), C1 (calibration validated
off the adjudicating path), D1 (custody of the component C1's fix created), E1 (the
component invariant 11 reached). Findings narrowed monotonically; no fix reopened an
earlier one; several fixes anticipated abuse vectors the auditor had not named.

**Disposition: the three documents are accepted as a specification baseline.** The
schema-freeze decision (AC01–AC04) may proceed on this text.

**No further specification review is recommended.** The remaining uncertainty in this
product is no longer resolvable by reading prose. The next two activities generate
information that specification review cannot:

1. **AC04 — the procurement rehearsal.** It is the only step that tests whether real
   procurement staff can supply the fields this contract set demands. Every schema
   decision frozen without it is an assumption.
2. **AC05 — CPU llama.cpp protocol qualification.** The v0.1 kernel has never met a
   real inference server; the deterministic harness cannot produce the SSE, usage,
   timeout and empty-response pathologies that a real engine produces.

Both will produce findings, and those findings will be worth more than any further
round on this text. The auditor's standing recommendation is to stop writing
specification and start collecting evidence against reality.

**Audit status: CLOSED. Ten of ten findings resolved.**
