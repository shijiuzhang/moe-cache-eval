# OICAP AC04 intake prototype

This is a browser-local procurement rehearsal surface. It lets a buyer translate
an existing tender/acceptance case into a typed draft and exposes ambiguities before
the v0.2 contract schemas are frozen.

It is deliberately **not** the hosted v0.2 service. It does not authenticate users,
compile or seal a test pack, upload evidence, adjudicate a result, or sign a report.
An exported record says `READY_FOR_HUMAN_REVIEW`, never `FROZEN` or `PASS`.

## Run locally

From the repository root:

```sh
python3 -m http.server 8765 --directory web/intake-prototype
```

Open <http://127.0.0.1:8765/>. The page has no external assets, network calls or
automatic persistence. Downloaded drafts can contain confidential procurement
information and belong under the ignored `private/` tree or another buyer-approved
location—not in the public repository.

## Rehearsal boundary

The prototype covers:

- buyer/SUT measurement boundary;
- class-aware, population-explicit SLA gates;
- workload source, length, session, streaming and quality semantics;
- all 14 deployment-catalogue decisions;
- load points, repeats, site time, preflight and retest mutability;
- structural validation and machine-readable JSON export.

It intentionally leaves contract normalization, schema validation, budget derivation,
pack compilation, held-out instance generation and canonical adjudication to later
v0.2 components. The JSON shape is an AC04 discovery artifact and may change as the
procurement rehearsal finds missing or unusable fields.

## Test

```sh
node --test tests/oicap-intake-prototype.test.mjs
```
