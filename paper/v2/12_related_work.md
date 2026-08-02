# §12 Related Work and Reporting Audit

*Draft v2 — 2026-08-02.*

## 12.1 Expert caching and offloading systems

Recent work attacks MoE memory pressure through expert caching, prefetching,
mixed-precision fallback, expert substitution, and CPU–GPU co-execution.
Mixtral-Offloading [@eliseev2023mixtraloffloading], MoE-Infinity
[@xue2025moeinfinity], and HOBBIT [@tang2024hobbit] implement end-to-end offloading
systems under different hardware and precision assumptions.
SpecMD [@hoang2026specmd] provides a PyTorch-hook framework for
composing caching, prefetch, miss-handling, and routing policies and proposes
Least-Stale eviction. DALI [@zhu2026dali] studies
residual-based expert prefetching in a KTransformers-based system, while
SP-MoE [@chen2025spmoe] combines expert prefetching with
speculative decoding. These works primarily ask which mechanisms improve a
specified implementation. We ask a complementary question: what must be stated
before a trace-derived policy comparison can be interpreted or transferred?

The distinction matters for Axis I. A real execution system determines its own
transfer and retention order; our replay counterexample does not retroactively
apply to such a system. It applies to a simulator only when the simulator claims
the fused-event traffic contract of §2 while permitting a start-resident,
not-yet-served expert to be evicted and counted again inside that event.

## 12.2 Expert prediction is not next-use prediction

Fate [@fang2025fate], Pre-gated MoE [@hwang2024pregated], SiDA-MoE
[@du2024sidamoe], and MoE-Beyond [@gavhane2025moebeyond] exploit predictability in expert
activation. Their prediction targets and system contracts differ: several
predict which experts a request will select in an upcoming layer or token so
that transfer can begin early; Pre-gated MoE changes the architecture and
training procedure; MoE-Beyond predicts token/layer expert activations from
token embeddings and layer positions and separately evaluates a trace-based
cache simulation at batch size one. Section 7 instead
predicts a cached block's next-use distance for victim ranking and bypass
admission. A positive result on next-expert prediction is therefore neither a
counterexample to nor evidence for our negative next-use result.

## 12.3 Audit of reported evaluation contracts

We audited the public text of ten representative papers (Appendix A): seven
end-to-end offloading systems, one trace-driven cache simulation, and two
architecture/prediction studies. We record what each paper reports, not what an
unreleased implementation may do. Axis I has narrow applicability — for the seven
end-to-end systems the implementation, not a trace replay, defines execution, and
the single trace-driven study assumes batch size one, which removes the
cross-request union central to our conditions. Beyond that, none of the ten
directly reports the measured per-step/per-layer expert union divided by usable
per-layer capacity, so the `r_bar` required by §6 cannot be reconstructed without
the underlying routes; and while papers identify datasets and often prompt or
generation lengths, the number of instruction templates per category,
chat-template application and positional synchronization are generally not
reported, which prevents applying the diagnostic of §5 from the paper alone.
Missing fields do not imply contamination.

This audit does **not** show that any cited speedup or quality result is wrong.
Many evaluate targets outside our scope, and real-system measurements avoid the
specific replay failure by construction. It shows that the public reports do not
expose a common evaluation contract sufficient to compare cache-policy numbers
across systems and models. Appendix A gives the per-paper evidence and puts our
own invalidated analyses in the first row.
