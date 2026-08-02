# Synthetic contamination positive control

This is a labelled sensitivity test for the route-contamination diagnostic.
It copies record 0's first 64 **input-token and routing** positions into every
one of 48 public C4 records, then reruns the same diagnostics used on the
unaltered data.

The control changes the detector flag from false to true. It does not represent
a prompt template, a generated model response, or a natural effect-size estimate.
The unmodified false-positive check is in
`analysis/external-route-contamination-allenai-mixtral-c4-v1/`.

Rebuild with a fresh output directory:

```bash
.venv/bin/python scripts/audit_external_route_contamination.py \
  data/external/allenai-analysis-mixtral/c4_results.jsonl \
  --output analysis/external-route-contamination-allenai-mixtral-c4-synthetic-prefix64-rebuild \
  --max-records 48 --max-tokens 512 --synthetic-shared-prefix-tokens 64
```
