# Reproducible 13-condition gap-invariance artifact

This supersedes `paper-gap-invariance-workload-composition-v1`, whose request
selection and arrival mapping were not frozen.

Scope: Qwen3-30B-A3B-4bit, D1 diverse confirmatory routes, event-atomic replay,
per-layer cache, `rho=0.40`, `B=8`, tie seed `20260729`.

Rebuild from the repository root:

```bash
.venv/bin/python -u scripts/build_paper_gap_invariance.py \
  artifacts/controller-probe-d1-diverse-confirmatory-chat-nothink-decode384-v1 \
  --output analysis/paper-gap-invariance-workload-composition-v2-rebuild
```

`condition-specs.json` freezes every request ID, arrival offset, queue ordering,
and semantic-condition hash. `gap-invariance.csv` contains the per-condition
policy result. The observed gap range is 44.1774%–45.9295%; it must not be
pooled with `B=2` or the residency-fraction sweep.
