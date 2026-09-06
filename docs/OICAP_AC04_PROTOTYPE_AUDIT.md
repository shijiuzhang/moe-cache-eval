# OICAP AC05 Remediation and AC04 Intake-Prototype Audit

**Auditor:** Claude (Anthropic), independent of the implementing agent
**Date:** 2026-09-04
**Scope:** commits `68c0e8d`, `cc17ad0`, `b47b501`; the G1–G3 remediation; the
buyer-side intake prototype under `web/intake-prototype/`
**Status:** G1–G3 closed. H1–H3 open, all minor. H4 is a note. Clear to begin AC04.

## 1. G1–G3 disposition

### G1 — CLOSED, verified on both bundle generations

`verify` now emits a `metrics_ruleset` block and warns when the applied ruleset is
not current. Confirmed by running the verifier against the two bundles that matter:

| Bundle | `applied_for_recomputation` | `adjudication_eligible` | warnings |
|---|---|---|---|
| `tests/fixtures/oicap/v0_1_genuine_bundle/run` | `0.1` | **false** | `superseded_metrics_ruleset:0.1` |
| `artifacts/oicap/ac05_llama_cpp_cpu_2026-08-31/run` | `0.2-dev2` | **true** | none |

The legacy bundle still verifies `ok: true` with its original TPOT recomputed
byte-identically — the compatibility guarantee survives — but it can no longer reach
a v0.2 gate. That is the correct pair of properties: **old evidence stays verifiable
and stops being adjudicable.**

Two decisions beyond what was asked:

- `METRICS_VERSION` was bumped to `0.2-dev2` and the AC05 evidence **regenerated**,
  rather than leaving the previously generated `0.2-dev1` bundle marked eligible under
  a ruleset that had since changed. Leaving it would have created exactly the stale-
  eligibility case G1 was about.
- A missing `metrics_version` key now warns `missing_metrics_ruleset_assumed_legacy:0.1`
  instead of silently defaulting.

### G2 — CLOSED, verified against a hostile endpoint

The guard moved from the request body to the **response header**
(`DETERMINISTIC_PROTOCOL_HEADER` / `DETERMINISTIC_PROTOCOL_ID`, `oicap/protocol.py`).

Tested directly: a purpose-built rogue server that ignores unknown request fields and
streams normal content — i.e. exactly how a real OpenAI-compatible engine would
respond to a body carrying `oicap_test` — was driven with
`synthetic_one_token_per_content_event`. Result:

```
success          = False
error_type       = ValueError
error_message    = synthetic_one_token_per_content_event requires an endpoint
                   authenticated by the deterministic OICAP test protocol marker.
token_timestamps = 0
output_tokens    = None
```

A real engine cannot mint synthetic token timestamps by ignoring a field. The control
case (genuine deterministic server) still produces three timestamps.

The summary-side half of G2 is also closed: `summarize` now emits a `token_timing`
block carrying `declared_authorities`, `per_token_timestamp_status` and
`per_token_latency_adjudication_eligible`, and synthetic timings report
`availability: synthetic_available` with population
`synthetic_content_event_intervals_from_test_protocol`. A synthetic number can no
longer be read as an authoritative one. Verified on the AC05 bundle:
`declared_authorities: ["server_usage"]`, `per_token_latency_adjudication_eligible:
false`.

**Auditor error, recorded.** The first probe reported "SPOOF SUCCEEDED". That was
wrong: the adapter records the `ValueError` on the observation instead of propagating
it, so the probe's `except` never fired. Re-probed by inspecting the returned
observation, which is how the result above was obtained. The finding H3 below comes
out of that mistake.

### G3 — CLOSED

`.gitignore:11` now ignores `private/` entirely rather than the single
`private/oicap-ac04/` path. Previously verified working at the narrow path; the broad
rule strictly contains it.

### Regression fixture — the §2 recommendation was adopted

`tests/fixtures/oicap/v0_1_genuine_bundle/` is a complete v0.1-produced calibration
and run pair, committed. The compatibility guarantee now has an artifact in the
repository that fails if someone breaks it, which it did not before.

## 2. Intake prototype — verified

| Claim | Method | Result |
|---|---|---|
| Serves over HTTP | `python3 -m http.server`, `curl -o /dev/null -w %{http_code}` on all four resources | `/` `app.mjs` `model.mjs` `styles.css` all 200 |
| Rule tests 7/7 | `node --test tests/oicap-intake-prototype.test.mjs` | 7 pass, 0 fail |
| Python regression 93/93 | `python -m unittest discover -s tests` | 93 run, OK |
| 14 deployment requirements | extracted `DEPLOYMENT_CATALOGUE` keys and spec §6.1 keys, `diff` | **identical, 14/14**, same order |
| Memory-envelope prerequisites | `MEMORY_ENVELOPE_PREREQUISITES` vs spec §6.3 | identical, 6/6 |
| No remote assets or network I/O | grep for `fetch`/`XMLHttpRequest`/`WebSocket`/`sendBeacon`/`http(s)://`/`localStorage`/`sessionStorage`/`indexedDB`/`document.cookie` across all four files | **no occurrence of any**; only same-directory `styles.css` and `app.mjs` are referenced |
| Not a static mockup | `model.mjs` validation logic | emits typed error codes (`DEPLOYMENT_CATALOGUE_INCOMPLETE`, `DEPLOYMENT_CONSTRAINT_REQUIRED`) and warning `MEMORY_ENVELOPE_UNAVAILABLE_BY_CONTRACT` with the text "这不等于通过" |
| README positioning | `README.md:55` | "OICAP is an independent product line, not an evaluation of the paper and not a paper-dependent derivative." |

The seventh rule test is literally *"the page has no remote scripts, styles or
automatic persistence"*. The implementer wrote the privacy assertion as an executable
test before the auditor raised it. That is the right instinct for a page that is about
to receive real procurement content.

The prototype's honesty boundary is correct: it emits `READY_FOR_HUMAN_REVIEW` and
does not claim to have compiled a pack, frozen a contract or produced an SLA verdict.

## 3. Findings

### H1 — the copy button is an egress path the page's own claim does not cover (MINOR, OPEN)

**Where:** `web/intake-prototype/app.mjs:260-264`.

```js
await navigator.clipboard.writeText(JSON.stringify(draft, null, 2));
```

The page correctly claims it uploads nothing, and the rule test correctly asserts no
remote assets and no automatic persistence. Neither statement covers the system
clipboard. `#copy-json` places the entire draft — every field the buyer typed — onto
a buffer shared with every application on the machine. On macOS with Handoff enabled,
Universal Clipboard replicates it to the user's other Apple devices automatically and
without further consent.

For de-identified content that is probably tolerable; it is still the one path by
which typed procurement text leaves the page, and it sits behind the button whose
label most invites casual use. Either warn at the button, or remove it — the download
path is sufficient and produces a file the user controls.

### H2 — the downloaded draft lands wherever the browser puts it (MINOR, OPEN)

**Where:** `app.mjs:233-245`; the hand-off instruction to place the file in `private/`.

The download is a normal browser save, so the file arrives in `~/Downloads` by
default — on macOS potentially inside iCloud Desktop & Documents sync — and moving it
into the ignored `private/` directory is a manual step performed afterwards, if
remembered. `.gitignore` protects the repository; it does not protect `~/Downloads`.

Cheap mitigation: prefix the generated filename so its sensitivity is visible in the
file listing (`PRIVATE-oicap-ac04-<id>.json`), and put the handling instruction in the
page's own status text rather than only in the hand-off message. The person who needs
the instruction is the one looking at the page.

### H3 — apparatus-integrity failures surface as a bare Python exception class name (MINOR, OPEN)

**Where:** the G2 probe result — `error_type: "ValueError"`.

Every other failure in this system carries a stable, machine-readable reason code:
`empty_or_non_substantive_response`, `timeout`, `http_error`. A deterministic-protocol
marker mismatch is an apparatus-integrity failure — arguably the most important class
to classify correctly — and it is recorded as the name of the Python exception that
happened to be raised.

In a sweep, that lands in `errors_by_type` as `ValueError` beside genuine transport
errors, and cannot be distinguished by a consumer. Give it a code, for example
`deterministic_protocol_marker_absent`, and reserve bare exception class names for
genuinely unclassified faults.

### H4 — the intake draft schema is becoming a de-facto data model (NOTE)

`model.mjs` defines `oicap-ac04-intake-draft/0.1` with sections `project`,
`sla_gates`, workload, `deployment_requirements`, `execution`. Spec §3 defines seven
separately versioned contract documents (`project.yaml`, `sla.yaml`,
`workload-profile.yaml`, `sut-requirements.yaml`, `acceptance-policy.yaml`,
`run-plan.yaml`, `pack-recipe.yaml`).

For AC04 this divergence is correct — an intake draft is not a frozen contract, and
the prototype says so. The risk is only that the draft shape is now the first concrete
data model anyone can see, and Slice B will be written against whatever exists.

Prophylactic, one table in `web/intake-prototype/README.md`: which draft section
becomes which specification document, and which fields the draft deliberately does not
yet carry. Written now it costs nothing; written after Slice B it is a migration.

## 4. Disposition

G1, G2 and G3 are closed, each verified against the running code rather than the
change description, and two of the three fixes are stronger than what was requested.
The prototype is a working instrument, not an illustration: the catalogue matches the
specification key-for-key, the validation refuses the cases the specification says it
must refuse, and it makes no claim it has not earned.

H1 and H2 concern the moment real procurement content first exists on this machine, so
they should be handled before the rehearsal rather than after. Both are minutes of
work. H3 and H4 can follow at any time.

**AC04 may begin.** The remaining prerequisite was never software — it was an
authorized case and a participant who knows procurement, and both now exist.

---

# Confirming pass — 2026-09-04

Commit `1cebe44`; working tree clean; 8 commits ahead of the remote, unpushed.
`v0.1` tag unmoved.

| Finding | Verification | Result |
|---|---|---|
| H1 | grep for `clipboard` / `copy-json` / `copyJson` across the prototype | no occurrence in code; only a README line explaining the deliberate absence |
| H2 | `app.mjs:241`, `index.html:132` and `:148` | filename is `PRIVATE-oicap-ac04-<id>.json`; the page itself states Downloads may be synced by the OS or a cloud service and must be moved immediately |
| H3 | rogue-endpoint probe re-run | `error_type: deterministic_protocol_marker_absent`, `success: False`, zero token timestamps |
| H4 | `web/intake-prototype/README.md` §Draft-to-contract map | seven-row table, including the `pack-recipe.yaml` row with no draft source, plus an explicit statement that the `validation`/`derived` blocks are advisory and must not be copied into canonical contracts |
| Regression | all four resources re-served | 200 / 200 / 200 / 200 |
| Regression | 7/7 rule tests, 93/93 Python | pass |

**Wiring regression check.** Removing a button is the kind of edit that leaves a
listener bound to a deleted element, in which case `initialize()` throws on load and
the entire form silently stops working — and neither test suite would catch it,
because both exercise `model.mjs` rather than the DOM wiring. Extracted all 18
`querySelector("#…")` targets from `app.mjs` and checked each against the ids present
in `index.html`: **all 18 resolve, none dangling.**

H1–H4 are closed. No new findings. AC04 has no remaining technical prerequisite.

---

# Buyer/expert split audit — 2026-09-06

**Commit:** `20a4799` "Split buyer intake from expert contract authoring". The
hand-off message degenerated while trying to state this hash; it was resolved from
`git log`. Working tree clean, 10 commits ahead of the remote, `v0.1` tag unmoved.

## 24. Verified

| Claim | Method | Result |
|---|---|---|
| 16/16 rule and wiring tests | `node --test` on both suites | 16 pass, 0 fail |
| 93/93 measurement kernel | `python -m unittest discover -s tests` | OK |
| Privacy preserved on **both** pages | grep for `clipboard`/`fetch`/`XHR`/`WebSocket`/`sendBeacon`/`localStorage`/`sessionStorage`/`indexedDB`/`cookie`/any absolute URL across all `.mjs`, `.html`, `.css` | **no occurrence of any** |
| H2 preserved on the new page | `buyer-app.mjs:58` | `PRIVATE-oicap-buyer-intake-<id>.json` |
| DOM wiring intact after the split | extracted every `querySelector("#…")` per page and matched against that page's ids | `buyer-app.mjs`→`index.html` 12/12; `app.mjs`→`expert.html` 18/18; none dangling |
| Public summary de-identified | scanned the draft for organization, supplier, model, hardware, price, date, IP and parameter-count patterns | zero hits; header states omissions and marks itself pending confidentiality review |
| No silent technical defaults | read `buyer-model.mjs` in full | the model never writes a percentile, population, concurrency figure, token authority or scan point; every unknown produces a named task with an owner and a `blocks_freeze` flag |
| Honest handoff | `finalizeBuyerIntake` | best status is `READY_FOR_TECHNICAL_TRANSLATION`; `technical_contract_frozen`, `test_pack_compiled` and `verdict_available` are all hard-coded `false` |

The baseline documents were amended, which is what AC04 exists to cause. The changes
reviewed as sound: Charter §3.1.1 introduces a technical contract translator whose
every translation records source intent and reviewer; invariant 12 — "No forced expert
authorship" — generalizes the rehearsal finding rather than patching the form; and
AC03 gains four controls, of which two (a supplier-environment report cannot create a
buyer-site `PASS`; a black-box timeout without bound system/process evidence cannot be
labelled proven `OUT_OF_MEMORY`) come directly from what the rehearsal exposed.

## 25. Finding

### J1 — test-plan tasks are keyed to the buyer's stated worry, not to the buyer's stated requirement (OPEN)

**Where:** `web/intake-prototype/buyer-model.mjs:47-48`.

```js
if (draft.experience?.risks?.includes("concurrency")) task("oicap_compiler", "CONCURRENCY_SWEEP_REQUIRED", …);
if (draft.experience?.risks?.includes("stability"))  task("oicap_compiler", "SOAK_PLAN_REQUIRED", …);
```

`risks` is the answer to "what worries you most". `peak_users`, `interaction_pattern`
and `stability_hours` are the answers to what the contract actually requires. Plan
generation is driven by the former.

Probed with a buyer who declares **500 peak concurrent users** and a **720-hour
stability requirement**, whose single ticked worry is OOM:

```
status = READY_FOR_TECHNICAL_TRANSLATION
declared peak_users    = 500
declared stability_hrs = 720
tasks: OOM_EVIDENCE_PLAN_REQUIRED, SUPPLIER_REPORT_PROVENANCE_ONLY
CONCURRENCY_SWEEP_REQUIRED present?  false
SOAK_PLAN_REQUIRED present?          false
```

Both requirements are captured as data and neither becomes an obligation. The task
list is the translator's work list, so a requirement that generates no task is a
requirement nobody is assigned to compile.

This matters because of what the same commit just added to AC03: "a sustained-
stability promise compiles to a named soak phase and cannot be satisfied by a short
capacity point." The intake that feeds the translator can now record a 720-hour
promise and emit nothing that requires a soak phase to exist. The failure direction is
**under-scoping**: a delivered system passes a plan that never tested what the contract
promised.

Note that the model already mixes two kinds of task. Ambiguity tasks
(`PEAK_USERS_UNRESOLVED`, `INPUT_DISTRIBUTION_UNRESOLVED`) correctly fire on missing or
unclear input and block freeze. Plan-generation tasks (`CONCURRENCY_SWEEP_REQUIRED`,
`SOAK_PLAN_REQUIRED`, owner `oicap_compiler`, non-blocking) are a different kind, and
it is only these that are wired to the wrong field.

Required:

1. derive plan-generation tasks from the declared requirements — a resolved
   `peak_users` or `interaction_pattern` requires a concurrency/arrival plan; a
   positive `stability_hours` requires a soak phase; a stated `recovery_expectation`
   requires a restart/recovery observation plan;
2. keep `risks` as priority and emphasis input, not as the trigger;
3. add a rule test for exactly the probed case: a stated requirement with the matching
   worry unticked still produces its plan task.

## 26. Disposition

The split is the right product decision and the rehearsal earned it: the first
version required a procurement officer to author percentiles and scan geometry, and
the rehearsal proved they cannot and should not. The rewrite preserves every privacy
and honesty property established in earlier rounds, and adds no new claim it has not
earned.

J1 is the single open finding. It is confined to two lines plus a test, does not
affect the privacy properties, and does not block the re-run of the rehearsal on the
new buyer page — but it should be fixed before any translated contract is produced
from an intake draft, because it determines what the translator is told to build.

---

# J1 confirming pass and rehearsal-analysis audit — 2026-09-06

**Commit:** `4ddf0c8` "Derive buyer test plans from requirements". Tree clean,
11 commits ahead, `v0.1` at `e62fed3`.

## 27. J1 — CLOSED

The auditor's original counterexample was re-run unchanged: a buyer declaring 500 peak
users and 720 hours of stability whose only ticked worry is OOM.

```
CONCURRENCY_SWEEP_REQUIRED           owner oicap_compiler
SOAK_PLAN_REQUIRED                   owner oicap_compiler
RECOVERY_OBSERVATION_PLAN_REQUIRED   owner oicap_compiler
OOM_EVIDENCE_PLAN_REQUIRED           owner technical_reviewer
```

All three plan tasks now derive from the declared requirements. `RECOVERY_OBSERVATION_
PLAN_REQUIRED` was added for `recovery_expectation`, which the finding named but did
not demonstrate. Tests 18/18 and 93/93.

## 28. Rehearsal artifact — structural checks only

The buyer instructed the auditor to review structural conclusions and
de-identification, not procurement content. That instruction was honoured: the draft's
answers were not read. The checks below are structural, and the two reproducible
findings were confirmed against **synthetic inputs constructed by the auditor**, not
against the buyer's answers.

- `private/` contains the two drafts and the rehearsal analysis; `git ls-files private/`
  returns nothing and `git check-ignore` matches `.gitignore:11` for both JSON files.
  Nothing from the rehearsal is tracked.
- The reported digest is correct: `724ad4b71cbbc59d…`.
- The rehearsal analysis is itself inside the ignored tree, which is the right place
  for a document that quotes procurement content.

## 29. The implementer's findings 2 and 3 are one defect

Both reproduce, and neither is specific to the buyer's case.

**Case A — a task is generated about a promise the buyer said does not exist.**
With `first_response_required: "no"` and stale subordinate values
(`first_response_seconds: 10`, `first_response_reliability: "unclear"`):

```
status = READY_FOR_TECHNICAL_TRANSLATION   errors = 0
tasks  = LATENCY_RELIABILITY_TRANSLATION, …
```

`LATENCY_RELIABILITY_TRANSLATION` fires unconditionally on the subordinate field, so
the translator receives a blocking task about a latency promise that was explicitly
declined. The subordinate fields are required when the answer is "yes" but are never
cleared or rejected when it is "no".

**Case B — a stability promise that cannot fit the on-site window passes silently.**
With `stability_hours: 1000` and `site_window_hours: 8`:

```
status = READY_FOR_TECHNICAL_TRANSLATION   errors = 0
no task or error references the window conflict
```

`stability_hours` and `site_window_hours` appear in `buyer-model.mjs` only inside
isolated presence checks (lines 45 and 85). **They are never compared.** More broadly,
the model validates every field in isolation and has no cross-field consistency pass
at all. Findings 2 and 3 are two symptoms of that single absence, and enumerating
them as separate patches will leave the next instance to be discovered by the next
rehearsal.

**Case B is already mandated by the accepted baseline.** AC10 requires that "a plan
exceeding the buyer's frozen appointment window cannot be frozen without a deliberate
profile change", and §8.2 forbids silently trimming coverage on site to fit the
appointment. The intake is the cheapest possible place to detect this — it holds both
numbers, in hours, before anyone compiles anything — and it is the only place where
the buyer can still change the answer rather than discover the conflict on site.

Required:

1. add a cross-field consistency pass to `validateBuyerIntake`, distinct from the
   per-field checks;
2. subordinate fields must be cleared or rejected when their governing answer is "no"
   or "unclear", so no task can be generated about a declined promise;
3. a stability requirement exceeding the site window MUST surface at intake, and MUST
   carry the AC10 reason code rather than a locally invented one, so intake and
   compiler name the same condition. The resolution is a business choice between a
   site soak plus a defined follow-on observation period and a changed requirement —
   which is exactly the kind of choice that belongs to the buyer, before travel;
4. rule tests for both cases.

On findings 1 and 4 — the concurrency/TPS ambiguity and a stability answer occupying
the quality field — the auditor takes no position, having not read the content. Both
are the kind of finding AC04 exists to produce, and both are recorded in the right
place.

## 30. Disposition

J1 is closed. The rehearsal has already returned its principal value: one pass by a
real procurement owner produced four product defects, two of which are reproducible
model bugs and one of which contradicts a rule the accepted specification already
carries. That is a better return than any further review of the specification text
would have given, and it is the outcome that was predicted when specification review
was closed.

The single open item is the missing cross-field consistency pass. It should be built
as a layer rather than as two fixes, and item 3 should reuse the AC10 code. The buyer's
existing `test case 1` draft must be preserved unmodified as the rehearsal's primary
record; the re-run belongs in a new file.

---

# Review of the two test-case-2 findings — 2026-09-06

Both implementer findings reproduce. They were confirmed against **synthetic inputs
constructed by the auditor**, not against the buyer's answers, per the standing
instruction that the auditor reviews structure and de-identification only.

Probe: `peak_users: 50`, `interaction_pattern: "conversational"`,
`requests_per_minute: 30`, `first_response_required: "yes"` / `10s` / `"most"`,
`quality_expectation` filled, `stability_hours: 10`.

```
status = READY_FOR_TECHNICAL_TRANSLATION   errors = 0
tasks  = CONCURRENCY_SWEEP_REQUIRED, SOAK_PLAN_REQUIRED,
         RECOVERY_OBSERVATION_PLAN_REQUIRED, SUPPLIER_REPORT_PROVENANCE_ONLY

requests_per_minute = 30      -> arrival-rate task?   false
first_response 10s / "most"   -> any TTFT gate task?  false
quality_expectation set       -> quality gate task?   false
stability_hours = 10          -> soak task?           true      (contrast)
```

## 31. Finding 1 confirmed — but the proposed remedy is wrong

`buyer-model.mjs:80-93` selects the plan task with a ternary:

```js
const arrivalRatePlan = draft.peak_use?.interaction_pattern === "known_request_rate";
task("oicap_compiler", arrivalRatePlan ? "ARRIVAL_RATE_PLAN_REQUIRED" : "CONCURRENCY_SWEEP_REQUIRED", …)
```

Exactly one task is ever produced, so a populated `requests_per_minute` under any
other interaction pattern drives nothing and raises no error. The finding is correct.

**The proposed fix — "generate both a concurrency plan and an arrival-rate plan" —
should not be adopted.** Closed-loop concurrency and open-loop arrival rate are
different load models, not two views of one. Emitting both doubles the measured phases
and therefore the wall-clock budget, which collides with `SITE_WINDOW_BELOW_MEASUREMENT_
FLOOR` — the AC10 rule committed in the previous change — and yields two capacity
answers that can disagree with no rule for reconciling them.

The two numbers are not redundant and not alternatives. **Together they determine think
time**, which is precisely the field the buyer can never state and the scenario schema
demands:

- `oicap/schemas/0.1/scenario.schema.json` makes `session.think_time_ms` **required**
  whenever `arrival.kind` is `closed_loop`, and forbids `session` otherwise;
- `oicap/metrics.py:362-372` already implements the interactive response time law
  `N × S/(S+Z)` and reports `method: "interactive_response_time_law"`.

For the probed pair, 50 users at 30 requests/minute gives `S + Z = 100 s` — one request
per user every hundred seconds. That is a derived think time, obtained from two
questions a procurement officer can answer, for a parameter they could never be asked
about directly. **Treating the pair as mutually exclusive discards the only route by
which think time can be supplied at all.**

Correct treatment: when both are present, derive the implied per-user request interval,
surface it to the technical reviewer for confirmation, and pick one load model with the
other number retained as a consistency check. If the pair is internally impossible,
that is an intake-time error, not a site-time discovery.

## 32. Finding 2 confirmed — it is an incomplete J1, not a new class

A fully specified latency promise produces no obligation. `LATENCY_RELIABILITY_
TRANSLATION` fires only when reliability is `"unclear"`, and
`FIRST_RESPONSE_PROMISE_UNRESOLVED` only when the promise itself is `"unclear"`. A
buyer who answers the question *well* — yes, 10 seconds, most requests — generates
nothing, while a buyer who answers it badly generates a blocking task.

J1's fix established the rule that a declared requirement creates a plan obligation,
and implemented it for load, stability and recovery. Latency is the fourth requirement
family and was not covered. The comment now standing at `buyer-model.mjs:76-78` states
the rule the code does not yet fully keep.

## 33. Auditor addition — quality is the third instance

Neither party has named it: `QUALITY_RULE_UNRESOLVED` fires only when
`quality_expectation` is **empty**. A buyer who states a quality expectation clearly
produces no obligation to compile a quality gate.

This is the most consequential of the three. Charter invariant 6 is "No speed without
quality", spec §10 requires every formal quality gate to carry a gate-specific positive
control, and AC12 makes that a release criterion. If the intake records a quality
requirement and emits no task, the quality gate can simply never be built — and a
delivered system then passes on latency and throughput alone, which is the exact
outcome the invariant exists to prevent.

## 34. The rule to implement, rather than three more patches

All three are one gap: **a populated field that generates neither an obligation nor an
error is silently idle.** The model already applies the correct rule to three
requirement families; it needs to apply it to all of them, and to reject input it does
not consume.

1. every declared requirement produces a compilation obligation — latency, quality and
   arrival rate joining load, stability and recovery;
2. a populated field that no task consumes and no rule rejects is itself a defect;
   add a completeness check that fails when input is retained without an obligation;
3. a rule test per requirement family asserting that the well-specified answer produces
   its task, mirroring the J1 counterexample test;
4. the arrival-rate pair per §31 — derive, confirm, choose one model.

## 35. Push and tag — verified, and one process finding

Checked against the remote rather than the local copy. `refs/heads/main` is
`67f03c89`; the annotated tag object `192b9b0a` dereferences to `67f03c89` on the
remote; `refs/tags/v0.1^{}` still dereferences to `e62fed3`. The tag name
`v0.2-ac04-intake-1` correctly does not claim a v0.2 release.

No rehearsal material reached the public repository: `git log --all --name-only`
contains no path under `private/`, and a content scan of every tracked file for
organization, vendor, model, hardware, price and threshold patterns returns nothing.
The only matches for "test case 1" are two audit documents referring to the codename
itself, which carries no information.

**Process finding, no harm done.** `docs/OICAP_AC04_PUBLIC_SUMMARY_DRAFT.md` is now on
public GitHub while its own header still reads "**Not yet approved for publication** …
still requires an authorized confidentiality review", and its status block still says
`confidentiality review: pending`. The content is in fact clean — that was verified
before and after the push — so nothing was disclosed. But the gate the team wrote for
itself was passed by an ordinary `git push`, which means the gate is currently
advisory. A document that must not be published before review should not sit in the
tracked tree; it belongs under `private/` until the review is recorded, and the
`v0.1`-style discipline of hashing the reviewed version applies here too.

---

# v0.2.0-alpha.1 release-candidate audit — 2026-09-06

**Candidate:** `afe8671`, identical on `origin/main`. Tree clean. `v0.1` still
`e62fed3`. No `v0.2.0-alpha.1` tag yet. Wheel `moe_cache_eval-0.2.0a1-py3-none-any.whl`
digest `936d99ddb48f532d…` matches the reported value.

## 36. Verified

- 29/29 frontend, 93/93 Python locally; the candidate additionally reports 104/104
  under CI's fuller collection.
- The wheel was installed into a **clean venv** and the documented example run end to
  end: `translate-expert` → `validate`, both `ok: true`, identity
  `52cf80b46f9b6978…`.
- `formal_procurement_verdict_enabled: false` is emitted by the translator itself, not
  only stated in the notes.
- `translation-report.json` records the emitted contract hashes and the runner profile,
  so a compiled benchmark is traceable to the draft it came from.
- **The translator's entry gate is correct.** `_validate_expert_draft` refuses any
  draft whose `schema` is unrecognised, whose `status` is not
  `READY_FOR_HUMAN_REVIEW`, or whose `validation.error_count` is non-zero. An
  unresolved draft cannot be compiled.
- The translator otherwise invents nothing: `weight_percent`, `input_tokens`,
  `output_tokens`, `quality_rule`, every gate field and every execution field raise
  `TranslationError` when absent.

## 37. Finding K1 — `think_time_ms` is the one silent default, at two layers (OPEN)

`oicap/translator.py:158`

```python
think_time = _finite_number(item.get("think_time_ms", 0), f"{class_id}.think_time_ms")
```

is the only `.get(..., <literal>)` in the file. Every neighbouring field is strictly
required; think time alone becomes `0` when absent. `web/intake-prototype/model.mjs:99`
initialises the same field to `0`, and the shipped fixture carries it. Running the
documented example produces:

```yaml
arrival:
  kind: closed_loop
  active_users: 2
session:
  think_time_ms: 0.0
```

Two consequences:

1. **It is not the same load.** Zero think time means clients that resubmit the instant
   a response completes. That is a continuous-hammer profile, not the conversational
   use the intake describes. Spec §3.1 lists "concurrency semantics or arrival process"
   among the facts OICAP MUST reject rather than guess.
2. **It silently changes the apparatus check.** `oicap/metrics.py:364` branches on
   `think_s <= 0` to `method: "declared_active_users"`, so the interactive response
   time law — the check that catches a client failing to sustain load — is never
   applied to any contract that omitted think time.

The sharper point is the pipeline as a whole. Commit `40e9dc7`, one commit earlier,
rebuilt the buyer intake specifically so that peak users plus request rate derive an
average request cycle — 100 s for the probed pair. **Nothing consumes it.** The expert
workbench defaults the field to 0 and the translator accepts 0, so the value the
previous fix existed to produce is discarded at the next layer. This is the same
silently-idle-input defect as J1 and §31-33, now one layer down.

Required, and small: make `think_time_ms` required in `_validate_expert_draft` exactly
as its four neighbours are; leave the expert workbench field empty rather than `0`; give
the fixture a think time consistent with the workload it claims to model; and carry the
intake's derived cycle into the expert draft.

## 38. Disposition

K1 is **not release-blocking for this alpha as scoped** — it emits no SLA verdict, the
fixture is labelled synthetic and explicitly not a recommendation, and no procurement
conclusion can be drawn from the output. Everything else in the candidate is sound, and
the chain genuinely runs from a clean install.

It should nonetheless be fixed before tagging, because it is roughly fifteen minutes of
work and because the shipped worked example currently models conversational users as
zero-think-time hammering — a poor first demonstration of the discipline the product
exists to enforce. Fix K1, re-run the example, then tag, release and re-verify the
published wheel as planned.
