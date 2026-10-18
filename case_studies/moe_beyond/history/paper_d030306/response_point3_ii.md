**Point 3, option (ii) — external case study.** We ran the released package on a
third-party public artifact, MoE-Beyond, the only study in our audit that publishes
both its traces and its trace simulator ([SEC]). The analysis was pre-registered
before any result was computed, and every deviation is listed in the artifact.
Running its published simulator at the reported configuration reproduced both
reported hit rates (16.9% vs 17%; 72.4% vs 72%). Our conformance probes, executed
through that simulator, classify its replay contract as per-access and show that,
at the reported operating point, every event fits in the cache, so Axis I does not
affect the reported comparison. The decisive result is the reporting block: the
paper text fills 13 of its 30 fields, while the public artifact with the package
fills 25 ([SEC], table [TAB]). Full tables, the pre-registration and all
deviations are in the supplement ([SUPP]).

The study stays inside Appendix A.3. We do not re-interpret any reported result.
We also did not construct a prefetch-free baseline inside the third-party contract:
it would require modelling prefetching, which point 4 asks us to keep out of scope,
and it would re-evaluate a published baseline, which point 7 rules out. Our
residency-gap figures are therefore labelled as not comparable with the published
prefetch-inclusive hit rates. The case also exposed two limits of our own tools:
the positional-agreement detector is length-sensitive, and the forced-admission
decomposition is not interpretable once most events exceed their quota. Both are
now stated in the paper.
