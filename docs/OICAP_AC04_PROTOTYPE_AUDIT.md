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
