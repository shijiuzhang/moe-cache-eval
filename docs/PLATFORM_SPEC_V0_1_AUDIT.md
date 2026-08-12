# Independent audit — Platform product specification v0.1

**Auditor:** independent review role per §19
**Date:** 2026-08-12
**Subject:** `docs/PLATFORM_PRODUCT_SPECIFICATION_V0_1.md` (commit b709412)
**Disposition format:** each finding is numbered for accept / reject / defer

---

## Overall

The specification succeeds at the thing that is hardest to get right: it
transfers the measurement discipline established in the paper into a product
contract. The measured/interpolated/extrapolated ladder (§1.2, P4), the
`INSUFFICIENT_EVIDENCE` outcome (§9.4), the invalid-versus-failed distinction
(§8.4), and the separation of client schedule lag from endpoint TTFT (§7.1) are
all correct and are not standard practice in this tool category.

Six findings are blocking. Two of them (B2, B3) can produce wrong conclusions
rather than merely incomplete ones. Five further findings should be resolved but
do not block starting implementation.

---

## Blocking

### B1. "v0.1" is not a shippable scope

§4.1 lists seventeen MUST items including a sweep planner, an HTML report,
cross-operator bundle import and comparison. §16 places those in M2 and later.
The two sections disagree about what v0.1 is, and as written v0.1 is a
multi-quarter build.

This matters more than tidiness. A specification whose first release cannot be
finished produces no evidence bundles, and the entire value of the project
depends on evidence bundles existing.

**Requested change.** Redefine v0.1 as M1 only:

- contracts, normalization and hashing;
- OpenAI-compatible adapter;
- deterministic synthetic server;
- closed- and open-loop generation;
- raw observations and the §7.2–7.4 metrics;
- evidence bundle plus `verify`.

Move to v0.2: sweep planner, SLO evaluator, HTML report, `compare`, goodput
selection. Move to v0.3+: MoE plugin, registry, publication profiles beyond
`private-full`.

Rationale: a v0.1 that can record one honest load point and let a third party
recompute it is already more than the market has. Sweeps and reports are
valuable but they are not what makes the tool trustworthy.

### B2. No noise floor for the measurement apparatus

§17 lists "client becomes bottleneck" as a risk and AC3 requires saturation
detection. Neither establishes what timing resolution the runner actually has.

Without this the tool can report a difference it cannot measure. If client-side
scheduling jitter is 5 ms, a reported 8 ms TTFT difference between two
configurations is not a finding. Nothing in the current specification prevents
that number from appearing in a procurement report with a `measured` label.

This is the same failure the paper documents in a different form: an apparatus
artefact presented as a property of the system under test.

**Requested change.** Add a required self-calibration phase, executed against a
local null endpoint that returns a fixed response with zero server delay, before
any confirmatory run. Record in the evidence bundle, per metric:

- client schedule lag distribution (mean, p95, p99, max);
- observed TTFT and ITL against the null endpoint, which is the noise floor;
- achieved versus requested arrival rate;
- runner CPU saturation during the calibration.

Add a rule: **a reported difference smaller than the calibrated noise floor for
that metric MUST be labelled `within_noise` and MUST NOT drive a pass/fail
decision.** Add an acceptance criterion that this labelling fires on a synthetic
pair of configurations separated by less than the noise floor.

### B3. Maximum compliant load assumes monotonicity that serving systems do not have

§7.6 defines the maximum measured compliant load as the highest tested point
that passes. It does not require lower points to pass, and does not say what to
report when they do not.

Non-monotonic pass/fail is real. A configuration can fail at a load below its
batching sweet spot and pass above it, or pass at low and high load while
failing in a queueing-unstable middle. Under the current definition, a sweep of
{4, 8, 16} in which 4 fails and 8 and 16 pass yields "maximum compliant load =
16" with no obligation to surface that 4 failed. That is a materially misleading
acceptance result.

§14.1 requires reporting the full curve, but §7.6 is the normative definition
and the report generator will implement §7.6.

**Requested change.** Redefine the result as a **pass/fail vector over all
tested points**, from which two scalars are derived:

- `max_compliant_load`: highest passing point;
- `min_non_compliant_load`: lowest failing point, if any.

Require that when `min_non_compliant_load < max_compliant_load`, the report
raises a `non_monotonic_compliance` flag, states it prominently, and the
acceptance conclusion is `INSUFFICIENT_EVIDENCE` unless the contract
pre-registers a rule for interpreting non-monotonic behaviour. Silence here is
worse than failure.

### B4. The selection rule can compare configurations that are not comparable

§9.1 correctly forbids merging results with different configuration identities.
§9.2 then selects the lowest-cost passing configuration across the registry.
Configuration identity by construction differs between the candidates, since it
hashes the SUT document.

The precondition is presumably that scenario, SLO and run contract match while
the SUT differs, but this is never stated. Without it, the planner will happily
compare a vendor's result under one workload pack with a buyer's under another.

**Requested change.** State the precondition normatively: candidates may be
compared only when the normalized `scenario`, `slo` and `run` hashes are
identical and only the `sut` hash differs. Any other comparison MUST be refused
or explicitly labelled non-comparable with the differing fields enumerated. Add
an acceptance criterion covering the refusal path.

### B5. Every gate needs a positive control, not only an exercise

AC4 requires that `PASS`, `FAIL` and `INSUFFICIENT_EVIDENCE` are "exercised by
tests". That is satisfied by a test suite that happens to reach each branch. It
does not establish that each individual gate catches its own violation.

The paper makes exactly this argument about the contamination detector: a
detector shown only not to fire is unvalidated, which is why a synthetic
positive control was added. The same standard applies here, and more so, because
a gate that silently never fires produces a false `PASS` on a real procurement.

**Requested change.** Require one positive control per frozen gate. For each of
TTFT, ITL, TPOT, end-to-end latency, success rate, quality pass rate and each
global gate, a synthetic SUT that violates that gate and only that gate MUST
produce `FAIL` attributed to that gate. Symmetrically, require negative controls
for `INSUFFICIENT_EVIDENCE`: for each invalidation condition in §8.4, a fixture
that triggers only that condition.

### B6. `t_first_token` is ambiguous and is the most gameable anchor

§7.1 defines `t_first_token` as "first complete generated token is received".
Streaming APIs commonly emit a leading chunk with empty or whitespace content,
a role delta, or a keep-alive. Whether those count is undefined, and the
difference lands directly on the headline TTFT number.

A server that emits an empty delta immediately and the real first token 400 ms
later would report an excellent TTFT under one reading and an honest one under
the other.

**Requested change.** Define `t_first_token` as the receipt time of the first
chunk whose decoded content contributes at least one non-whitespace character to
the final response body. Require the runner to record, separately,
`t_first_chunk` for any earlier protocol chunk, and to report the gap. Add a
conformance fixture whose server emits a leading empty delta and assert that
TTFT is measured from the first substantive token.

---

## Should fix

### S1. The CLI name contradicts the product positioning

§11.2 names the CLI `moe-eval` while §1 states the acceptance core is
"deliberately model- and engine-agnostic". A procurement team evaluating a dense
model will not believe the tool applies to them, and the name will have to
change later at the cost of every documented command and every published
evidence bundle that records the command line.

Rename before the first bundle is written. The research repository can keep its
name; the platform should not inherit it.

### S2. Service discipline should be a comparability dimension, not a field

§14.10 forbids comparing open-loop and closed-loop results without an explicit
normalization argument. Service discipline deserves the same treatment and does
not get it — it appears only as a `sut.yaml` field in §6.3.

The paper's own §9.3 found that changing only the service discipline, at fixed
request set, capacity and mean batch size, moved a static residency policy from
7.5% worse than LFRU to 17.0% better. That is a 24.5-point swing from a variable
this specification currently treats as descriptive metadata.

**Requested change.** Add service discipline (continuous batching, rotation with
a fairness bound, preemption policy, admission rule) to the set of fields whose
difference blocks silent comparison, alongside arrival semantics.

### S3. When validators run is unspecified

§10.3 requires quality gates and §14.5 requires they run on the same responses
used for performance metrics, but nothing says whether validation is inline or
post-hoc. Inline validation with a user-supplied local command can perturb the
timing it is supposed to qualify.

**Requested change.** Require post-hoc validation by default, with responses
buffered during the measurement phase; permit inline validation only when the
contract declares it and the report states the measured validator overhead.

### S4. Repeat disagreement must be visible, not just aggregated

§7.6 requires every repeat to pass unless another rule is pre-registered, and
§7.5 requires clustered confidence intervals. Neither requires reporting that
repeats disagreed.

Two passes and one failure across three repeats is a different fact from three
marginal passes, and a procurement reader needs to see it. Require a per-repeat
pass/fail table in the acceptance report whenever repeats exist.

### S5. No resourcing assumption is stated

M0–M5 carry no dates, no effort estimate and no statement of who implements
them. Combined with B1, this is how a specification becomes an artefact rather
than a product. State the assumption explicitly, even if it is "one part-time
implementer", because that assumption is what justifies the v0.1 scope cut.

---

## Answers to the §20 audit questions

1. **Black-box boundary sufficient?** Yes, subject to B6. P5 and §5.2 are
   correctly constructed; the residual risk is not engine proxies leaking into
   pass/fail but the endpoint gaming the anchors.
2. **Metric definitions unambiguous?** TTFT is not (B6). ITL, TPOT, retry and
   censoring are. Goodput is well defined but depends on S3.
3. **Open/closed loop separated enough?** Yes. §8.1 and §14.10 are adequate.
4. **Can max compliant load be gamed by sparse sweeps?** Yes, and worse than the
   question implies — see B3. Sparse sweeps are the lesser problem;
   non-monotonicity is the real one.
5. **Is `INSUFFICIENT_EVIDENCE` used wherever needed?** Nearly. Add the
   non-monotonic case (B3) and the noise-floor case (B2).
6. **Does the labelling prevent unsupported card-count claims?** Yes for direct
   claims. Extend the labels explicitly to §9.3 envelope outputs, which
   currently require explicit assumptions but not an evidence-status label.
7. **Workload licensing, quality and contamination adequate?** Yes. §10.4 is
   the strongest section in the document.
8. **Enough to reproduce without exposing payloads?** Yes, given §13.2. Add an
   acceptance criterion that a `redacted` bundle can still recompute every
   summary in the report, which is the property that actually matters.
9. **Anti-gaming realistic?** Mostly. §14.9's held-out pack is the load-bearing
   control and should be marked as such; the others are hygiene.
10. **Which MVP requirements are too broad?** See B1.
11. **Which critical failure mode is absent?** Two: apparatus noise (B2) and
    non-monotonic compliance (B3).
12. **Any paper-only evidence treated as deployment fact?** No. §5.4 and §12 are
    correctly fenced. This is handled better than in earlier documents.

---

## Recommendation

Accept the specification as the design contract, subject to B1–B6 being resolved
before implementation begins and S1–S5 before the first evidence bundle is
published.

B1 is the one that decides whether this project produces anything. The remaining
five are the difference between a tool that is trusted and one that is merely
careful.
