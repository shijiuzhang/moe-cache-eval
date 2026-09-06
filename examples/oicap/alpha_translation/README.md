# Expert-draft translation alpha fixture

This public synthetic fixture exercises the narrow `v0.2.0-alpha.1` workflow.
It is not a procurement contract and its thresholds are not recommendations.

Compile one declared load point using the AC05 public workload:

```bash
oicap translate-expert examples/oicap/alpha_translation/expert-draft.json \
  --workload examples/oicap/llama_cpp_ac05/workload.jsonl \
  --load-point 2 \
  --output /tmp/oicap-alpha-benchmark
oicap validate /tmp/oicap-alpha-benchmark
```

With a local OpenAI-compatible endpoint running, finish the local measurement
workflow:

```bash
oicap calibrate /tmp/oicap-alpha-benchmark --output /tmp/oicap-alpha-calibration
oicap run /tmp/oicap-alpha-benchmark \
  --endpoint http://127.0.0.1:18080/v1/chat/completions \
  --calibration /tmp/oicap-alpha-calibration \
  --output /tmp/oicap-alpha-run
oicap verify /tmp/oicap-alpha-run \
  --calibration-source /tmp/oicap-alpha-calibration
```

Read `translation-report.json` before running. The alpha preserves the full
expert intent but executes only one local load point. It does not enforce the
minimum duration or independent repeats, execute a quality gate, or issue an
SLA/deployment verdict.
