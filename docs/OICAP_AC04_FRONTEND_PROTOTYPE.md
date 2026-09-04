# OICAP AC04 procurement-intake frontend prototype

**Status:** implemented for private workflow rehearsal

**Product claim:** browser-local authoring and structural validation only

**Not claimed:** frozen contract, test-pack compilation, evidence upload, SLA
adjudication, deployment-conformance adjudication, authentication, or server signature

## Why this exists now

V02-AC04 asks a real procurement participant to walk an authorized or de-identified
case through OICAP before the v0.2 schema is frozen. A Markdown template alone tests
whether a technical reader understands the specification; it does not test whether a
buyer can actually enter procurement intent through the product surface.

The prototype under `web/intake-prototype/` makes the authoring surface testable now,
without waiting for a hosted backend or access to a production inference server. It
is intended for the buyer who recently completed a private-model deployment
acceptance and therefore knows which tender and acceptance facts were available in
practice.

## Implemented flow

1. de-identified project roles and frozen SUT boundary;
2. class-aware SLA gates with metric, population, statistic, comparator, threshold,
   evidence sufficiency and authority;
3. workload sources, class weights, input/output lengths, session/think time,
   streaming and quality rule;
4. all fourteen deployment-requirement catalogue decisions;
5. load points, independent repeats, site time, client preflight and retest mutable
   paths;
6. structural findings and machine-readable JSON export.

The page does not persist or upload form data. It has no remote JavaScript, fonts,
analytics or API calls. The operator must store an exported draft under the ignored
`private/` tree or another buyer-approved private location.

## Controls already encoded

- bare `TPS` is rejected;
- every SLA gate names its workload class and statistical population;
- class weights must total 100%;
- every deployment-catalogue key must be explicitly classified;
- `required` and `allowed_set` entries require a written constraint;
- missing physical-memory-envelope prerequisites become
  `UNAVAILABLE_BY_CONTRACT`, never `PASS`;
- per-token latency/rate gates require authoritative per-token timestamps;
- the minimum load-point measurement time is checked against the site window;
- sustained maximum-load preflight, resource capture, on-site same-path calibration
  and buyer-controlled responder checks are explicit;
- the export status is at most `READY_FOR_HUMAN_REVIEW`.

## Deliberate omissions

The prototype does not yet implement the canonical v0.2 document split
(`project.yaml`, `sla.yaml`, `workload-profile.yaml`, `sut-requirements.yaml`,
`acceptance-policy.yaml`, `run-plan.yaml`). The AC04 export is one discovery document
because the rehearsal is supposed to change the future schemas if procurement users
cannot supply or understand their fields.

It also does not estimate SLA-derived hard caps. The displayed site-time calculation
is named `measurement_floor_minutes`: it covers only declared points × repeats ×
minimum point duration and explicitly excludes setup, calibration, reset, quality and
upload time. Calling that value an expected duration would be false precision.

## Verification

Run:

```sh
node --test tests/oicap-intake-prototype.test.mjs
python3 -m http.server 8765 --directory web/intake-prototype
```

The automated controls cover a complete review-ready draft, ambiguous TPS, catalogue
silence, physical-memory prerequisite loss, workload weights, site-time overflow,
token-timing authority and absence of network/persistence calls. HTTP smoke testing
must confirm `index.html`, `app.mjs` and `model.mjs` are served successfully.

## AC04 use and privacy boundary

The buyer should enter a de-identified reconstruction of the recent procurement case,
not copy tender text. The resulting JSON is a private rehearsal record. Only findings
such as “this field was unavailable”, “this phrase had multiple meanings” or “this
step would not fit the site window” may be transferred into
`OICAP_AC04_PUBLIC_SUMMARY_TEMPLATE.md`, after an authorized confidentiality review.
