# OICAP v0.2.0-alpha.1 release notes

**Release class:** local-workflow developer alpha

**Formal procurement verdict enabled:** no

**GPU capacity qualified:** no

## What this release does

This release closes one executable local path:

1. the browser-local buyer and expert workbenches produce a reviewed expert
   draft;
2. `oicap translate-expert` compiles one explicitly selected load point into
   the four contracts consumed by the audited v0.1 measurement kernel;
3. `oicap validate`, `calibrate`, and `run` execute a local
   OpenAI-compatible endpoint measurement; and
4. `oicap verify` recomputes and checks the unsigned evidence bundle's internal
   consistency.

The translator does not trust the draft's status alone. It rechecks the frozen
14-key deployment catalogue, workload classes and weights, gate populations and
authorities, execution minima, preflight declarations, workload JSONL class set,
and the selected load point. It refuses unfinished drafts, unknown load points,
unstructured service-discipline declarations, quality-hook gates, and gates that
need authoritative per-token timestamps unavailable from the current adapter.
It refuses to overwrite an existing output directory.

Every successful translation includes `translation-report.json`, the source and
workload SHA-256 values, emitted contract identity and hashes, selected load
point, and a machine-readable statement that formal procurement verdicts are
disabled. Closed-loop think time must be explicitly reviewed: the buyer-derived
mean request cycle is carried forward as provenance but is never silently treated
as think time or replaced with zero.

## What this release does not do

This is not the complete acceptance alpha defined by V02-AC19, and this tag does
not claim V02-AC06 through V02-AC18. It does not provide:

- a sealed or held-out test pack;
- automatic multi-point sweep execution;
- enforcement of minimum point duration, successful sample minima, or independent
  repeats;
- a locked quality-hook execution path or quality gate;
- `service_sla_verdict` or `deployment_conformance_verdict`;
- server-side adjudication or a hosted report;
- producer identity, detached-signature, or external timestamp attestation; or
- qualification for GPU capacity or formal delivery acceptance.

The generated `sut.yaml` preserves procurement declarations. It does not prove
that the process serving the measured endpoint conforms to those declarations.

## Qualification boundary

The measurement kernel has passed the V02-AC05 protocol gate against a real,
CPU-hosted llama.cpp OpenAI-compatible endpoint, including real streaming,
usage, timeout, HTTP-error, empty-response, and variance paths. That evidence
qualifies protocol compatibility and local pilot work only. A real GPU serving
stack remains mandatory before OICAP may issue formal delivery verdicts.

## Reproduce the public local workflow

```bash
oicap translate-expert examples/oicap/alpha_translation/expert-draft.json \
  --workload examples/oicap/llama_cpp_ac05/workload.jsonl \
  --load-point 2 \
  --output /tmp/oicap-alpha-benchmark
oicap validate /tmp/oicap-alpha-benchmark
oicap calibrate /tmp/oicap-alpha-benchmark \
  --output /tmp/oicap-alpha-calibration
oicap run /tmp/oicap-alpha-benchmark \
  --endpoint http://127.0.0.1:18080/v1/chat/completions \
  --calibration /tmp/oicap-alpha-calibration \
  --output /tmp/oicap-alpha-run
oicap verify /tmp/oicap-alpha-run \
  --calibration-source /tmp/oicap-alpha-calibration
```

The endpoint and model are operator-provided and are not distributed in the
wheel or repository.

The release-candidate chain was also executed against a real CPU llama.cpp
endpoint. Its scoped evidence and checksums are recorded in
[`OICAP_V0_2_ALPHA1_LOCAL_WORKFLOW_QUALIFICATION.md`](OICAP_V0_2_ALPHA1_LOCAL_WORKFLOW_QUALIFICATION.md).
