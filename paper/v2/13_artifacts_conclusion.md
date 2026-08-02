# §13 Artifacts and Conclusion

*Draft v2 — 2026-08-02.*

## 13.1 Released artifacts

**Simulator.** The event-atomic replay engine of §2, with per-layer and global
cache scope, seeded tie-breaking, and the eight policies of §2.3 including the
`Belady-forced-admit` decomposition probe of §7.2.

**Conformance trace.** The hand-verifiable trace of §2.5 — 3 layers, 4 experts
per layer, 5 scheduling steps, 30 union accesses, yielding 12 hits and 18 misses
under Definition 2 — with the expected counts, so that an independent
implementation can confirm which semantics it realizes.

**Workload probe set.** ControllerProbe-D1: 432 records across six workload
archetypes, twelve prompt forms crossed with two instruction languages, eight
task framings and five payload rendering styles per archetype, a group-aware
discovery/confirmatory split, and the matched-pair fixed-template control arm of
§5.5. Built entirely from public benchmark and public industrial sources.

**Contamination audit tooling.** The prompt-side and route-side diagnostics of
§5.3–§5.4, implemented to run on any probe set and any route collection, not
only ours. This is the component we expect to be most directly reusable.

**Routing traces and event streams.** Where upstream licences permit
redistribution, decode routing for three models, including the corrected
collection of §3.3 and the earlier single-template collection retained as the
contaminated condition. Otherwise the release contains collection/conversion
scripts, frozen selections, manifests and cryptographic hashes rather than
silently redistributing restricted source material.

**Pre-registration documents, unchanged.** Every frozen criterion with the split
it was to be evaluated on, including those in which a criterion failed and the
associated development line was stopped, and including the design revision
recorded in §8.6.

**Derived result artifacts**, each with per-condition rows and input manifest
hashes, notably the reproducible v2 thirteen-condition gap-invariance
measurement of §7.1, the regime ablation of §6.5, the natural-C4 false-positive
check, its labelled 64-token synthetic-prefix positive control, and the static
protocol audit that freezes the evaluated event-manifest hash, discovery pin
hash, quota rule, preload convention, and both static values used in the text.

We apply the checklist of §10 to this paper in Appendix B, including one item we
cannot complete: we set no service-rate target for the primary model, so the
bandwidth budget required by D1 is unavailable without the hardware calibration
§11 says we lack. The invalidated analyses recorded during this work are listed
in Appendix A.

## 13.3 Conclusion

We set out to measure how much room a workload-aware expert cache controller has
in MoE inference. The measurement turned out to be the harder problem.

Three evaluation choices — how a fused-event traffic contract is replayed, how a
workload-partitioned probe set is constructed, and what operating regime a
result sits in — each change conclusions rather than merely shift numbers. The
first inverts policy rankings by selectively penalizing recency-based policies.
The second manufactures apparent workload locality large enough to reverse which
workloads look cache-friendly. The third makes cross-model comparison
uninterpretable unless the ratio of per-step expert union to cache capacity is
reported, and even then does not license extrapolation. A fourth — the service
discipline — we found only by accident, after the first three were already
identified.

With all of them controlled, a large and stable gap to the offline optimum
remains, and it is mostly not what it appears to be: 84.3–96.6% of it rests on
knowing which resident block is used furthest in the future, and the natural
online estimator of that quantity performs worse than the baseline it replaces.
Three natural mechanisms failed to reach pre-registered thresholds in the
settings we measured; a fourth experiment, semantic partitioning, was itself
invalidated because its dedicated partitions could not hold one request's
top-k set. A fixed, offline-chosen residency set remains a useful transparent
reference whose union-denominator traffic is determined by an access-count
distribution rather than access order. It never wins under standard continuous
batching, is close to LFRU only at high local concurrency, and is substantially
worse in the slack regimes most relevant to our unmeasured frontier-scale
motivation; it is not a validated product mechanism.

We state our position narrowly. We have not shown that expert caching is a
closed problem, that future-victim distance is unpredictable in principle, or
that online controllers have no future. We have shown that **in our evaluated
settings a large offline-optimal gap substantially overstates the gains
recovered by representative lightweight causal mechanisms**, and that reporting
such a gap without decomposing it invites an inference the evidence does not
support.

The portable output of this work is not any individual number — §6 establishes
that the numbers are regime-bound — but the reporting checklist of §10, the
conformance trace that pins down the replay semantics, the contamination
diagnostics that need no control arm, and the released artifacts. We expect the
checklist to be incomplete, and we would consider a fifth confounder found by a
reader to be a use of it rather than a refutation.
