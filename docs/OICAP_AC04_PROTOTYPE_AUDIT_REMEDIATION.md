# OICAP AC04 prototype audit remediation

**Audit source:** `docs/OICAP_AC04_PROTOTYPE_AUDIT.md`

**Disposition:** H1–H4 addressed before entering private AC04 data

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

## Verification commands

```sh
node --check web/intake-prototype/app.mjs
node --check web/intake-prototype/model.mjs
node --test tests/oicap-intake-prototype.test.mjs
uv run --no-default-groups python -m unittest discover -s tests -p 'test*.py'
```
