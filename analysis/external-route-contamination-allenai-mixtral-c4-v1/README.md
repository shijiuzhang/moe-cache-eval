# External route-contamination false-positive check

This audits the first 48 complete records of a public Mixtral C4 routing
artifact, truncated to 512 **input tokens** per record. The public data have no
workload labels or matched template arm, so this checks diagnostic portability
and false-positive behavior only; it does not replicate the internal
prompt-rendering experiment.

See `REPORT.md` for metrics and `manifest.json` for the source hash and prefix
download boundary.
