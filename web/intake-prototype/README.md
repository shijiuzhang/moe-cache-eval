# OICAP AC04 intake prototype

This directory contains two browser-local surfaces:

- `index.html` is the default, plain-language buyer intake. It records business
  intent and emits explicit technical-translation tasks.
- `expert.html` is the technical contract workshop for OICAP/compiler maintainers and
  named technical reviewers. It is not a procurement questionnaire.

It is deliberately **not** the hosted v0.2 service. It does not authenticate users,
compile or seal a test pack, upload evidence, adjudicate a result, or sign a report.
A buyer export says at most `READY_FOR_TECHNICAL_TRANSLATION`; an expert export says
at most `READY_FOR_HUMAN_REVIEW`. Neither says `FROZEN` or `PASS`.

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

The buyer surface covers:

- business use, peak users and interaction pattern;
- visible first-response expectations without asking for percentile terminology;
- continuous stability, recovery and buyer concerns such as concurrency or OOM;
- supplier evidence availability, site time and the existing FAIL/retest process;
- a role-assigned queue of technical translations that block freeze when unresolved.

The expert surface covers:

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

## Draft-to-contract map

The intake JSON is deliberately not a shortcut around the seven-document contract.
Slice B must normalize it into independently versioned documents instead of treating
the prototype shape as a frozen API.

| Intake draft section | Future contract document | Deliberately absent from the draft |
|---|---|---|
| `project` | `project.yaml` | legal party identifiers, authorization objects, immutable revision, full endpoint/path fingerprint |
| `sla_gates` | `sla.yaml` | canonical units, complete gate identifiers, noise/variation allowances, reason-code policy |
| `workload_classes` | `workload-profile.yaml` | formal distribution objects, private-payload manifest hashes, generator and quality-hook locks |
| `deployment_requirements` | `sut-requirements.yaml` | catalogue version, typed constraint objects, evidence-layer requirements and observation schemas |
| `execution.preflight` and retest fields | `acceptance-policy.yaml` | attempt state machine, review roles, expiry, supersession and all frozen mutable paths |
| `execution` load points/repeats | `run-plan.yaml` | phases, seeds, reset rules, SLA-derived caps, named margins and full wall-clock derivation |
| no direct draft section | `pack-recipe.yaml` | compiler/generator versions, public method, sealed-instance policy, responder and validator identities |

The prototype's `validation` and `derived` blocks are advisory AC04 findings. They
must not be copied into canonical contracts as if they were server adjudication.

## Handling downloaded drafts

The copy-to-clipboard path is intentionally absent: system clipboards may be shared
with other applications or devices. Downloads use a `PRIVATE-` filename prefix, but
the browser still chooses the destination. Move the file immediately from Downloads
to a buyer-approved private location and check whether that destination is cloud-
synced. A filename is a warning, not access control.

## Test

```sh
node --test tests/oicap-intake-prototype.test.mjs tests/oicap-buyer-intake.test.mjs
```
