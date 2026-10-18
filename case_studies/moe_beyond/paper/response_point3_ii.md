**Point 3, option (ii) — external case study.** We ran the released package on a
third-party public artifact, MoE-Beyond, the only study in our audit that publishes
both its traces and its trace simulator ([SEC]). The analysis was pre-registered;
all deviations, including post-audit corrections, are listed in the artifact.
Running its published simulator at the reported configuration reproduced both
reported hit rates (16.9% vs 17%; 72.4% vs 72%). Conformance probes executed
through that simulator classify its replay contract as per-access, which must be
declared before its counts are set beside an event-atomic study. Every
reporting-block field is classified for the published configuration under one
rule: the paper text answers 8 of the 30 fields, and the public artifact with the
package and documented analyst steps answers 19, each with its provenance ([SEC],
table [TAB]). Without an artifact-only control, this measures the combined
workflow, not the package alone. Full tables are in the supplement ([SUPP]).

The study stays inside Appendix A.3 and re-interprets no reported result. We built
no prefetch-free baseline inside the third-party contract: it would require
modelling prefetching, which point 4 asks us to keep out of scope, and would
re-evaluate a published baseline, which point 7 rules out. Our residency-gap
figures are labelled as not comparable with those hit rates. The case also exposed
two limits of our own tools, both stated in the paper: the positional-agreement
detector is length-sensitive, and the forced-admission decomposition is not
interpretable once most events exceed their quota.
