# OICAP AC04 prototype audit remediation

**Audit source:** `docs/OICAP_AC04_PROTOTYPE_AUDIT.md`

**Disposition:** H1–H4, J1 and the post-rehearsal cross-field consistency finding addressed before translating an intake draft

## H1 — clipboard egress

The copy-to-clipboard control and all `navigator.clipboard` use were removed. The
download is now the only export path. The frontend test asserts that neither the
clipboard API nor the removed control is present.

This does not make the download confidential; it removes one unnecessary shared-
system egress path.

## H2 — browser-selected download location

The generated name now begins `PRIVATE-oicap-ac04-`. A warning beside the download
control and the post-download status both state that the browser's download directory
may be system- or cloud-synchronized and instruct the operator to move the file to a
buyer-approved private location immediately.

The prefix and warning are handling signals, not access control or encryption.

## H3 — stable apparatus-integrity reason

Missing or incorrect response-side deterministic protocol identity now records:

```text
deterministic_protocol_marker_absent
```

An internal observation-failure type carries the stable reason code separately from
its Python exception class. The existing endpoint-identity positive control now
asserts the stable code. Other unclassified exceptions retain their current fallback
until individually promoted to documented reasons.

## H4 — intake-to-contract boundary

`web/intake-prototype/README.md` now maps every draft section to the future canonical
contract document and lists important fields deliberately absent from the AC04
prototype. It explicitly forbids Slice B from treating the draft shape as the frozen
contract API and identifies `validation`/`derived` as advisory rather than canonical
adjudication.

## J1 — requirement-derived test-plan obligations

Plan-generation tasks no longer depend on which concern boxes the buyer selects.
They are derived from the recorded requirements:

- a resolved peak-user count or interaction pattern creates a concurrency or
  arrival-rate plan task;
- a positive continuous-stability duration creates a soak-plan task;
- a stated recovery expectation creates a recovery-observation task, while an
  unclear expectation also creates a freeze-blocking clarification task.

The concern list is retained as `buyer_emphasis` on the corresponding task and is
shown as “买方重点” in the review page. It can prioritize the translator's work but
cannot add or remove a contractual test obligation. The OOM concern continues to
create a separate evidence-planning task; it is not used to decide whether load,
stability, or recovery requirements are tested.

The regression suite includes the audit counterexample verbatim in substance: 500
declared peak users, 720 declared stability hours, and only OOM selected as a concern.
The finalized draft still contains `CONCURRENCY_SWEEP_REQUIRED`,
`SOAK_PLAN_REQUIRED`, and `RECOVERY_OBSERVATION_PLAN_REQUIRED`.

## Cross-field consistency — governing answers and the site window

Buyer validation now has an explicit cross-field pass after the individual field
checks. It enforces two relationships exposed by the first buyer rehearsal:

- when `first_response_required` is `no` or `unclear`, retained response-time seconds
  or reliability values are rejected as
  `FIRST_RESPONSE_SUBORDINATE_FIELDS_NOT_ALLOWED`; a declined promise cannot create a
  latency-translation task;
- when the declared continuous-stability duration exceeds the declared on-site
  window, the intake emits the existing AC10 code
  `SITE_WINDOW_BELOW_MEASUREMENT_FLOOR` as a freeze-blocking procurement task. The
  task requires a deliberate staged observation profile or a changed requirement;
  it does not silently shorten the soak.

The browser disables and clears the two first-response subordinate controls unless
the governing answer is `yes`. Imported or hand-edited JSON still goes through the
model-level rejection, so the UI is not the enforcement boundary.

The original private `test case 1` file remains byte-for-byte unchanged. It is a
primary rehearsal observation, not a draft to repair in place. Revalidation under the
new rules exposes the stale subordinate fields and site-window conflict without
rewriting the source file.

## Verification commands

```sh
node --check web/intake-prototype/app.mjs
node --check web/intake-prototype/model.mjs
node --check web/intake-prototype/buyer-app.mjs
node --check web/intake-prototype/buyer-model.mjs
node --test tests/oicap-intake-prototype.test.mjs tests/oicap-buyer-intake.test.mjs
uv run --no-default-groups python -m unittest discover -s tests -p 'test*.py'
```
