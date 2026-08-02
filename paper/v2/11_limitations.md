# §11 Limitations

*Draft v2 — 2026-08-02.*

This paper argues that MoE cache results are sensitive to unreported evaluation
choices, which obliges us to state our own boundaries plainly.

**Everything here is trace-driven simulation.** We replay recorded routing
decisions against a cache model and count blocks transferred. We do not measure
host-to-device transfer, its overlap with compute, sustained bandwidth,
interconnect topology, kernel time, graph-capture interactions, or contention
between the expert cache and attention state. Miss bursts are reported in block
counts, not in time. A policy that transfers fewer blocks here may not be faster
in a system, and one that transfers more may be, if its transfers overlap
better. No deployment claim follows from any result in this paper; where
engineering units appear they are unit conversions applied to the analytical
reference frame of §3.2 and are labelled as such.

**Model and scale coverage is narrow.** The results of §5, §7, §8 and §9 rest on
a single 128-expert model, which is additionally 4-bit quantized; routing under
quantization may differ from full precision and we did not compare them. The 40-
and 64-expert models appear only for cross-model checks. No trace was collected
at the 896-expert scale that motivates the application, and §6.4 shows that its
regime ratio is reached by our models only at low concurrency — so the setting
the motivation comes from is the one our data covers least well. Regime coverage
is also bounded below by expert count: the 40-expert model cannot reach
`r_bar < 0.5` at ρ = 40% at any concurrency, so conclusions about slack regimes
rest on the 128-expert model alone.

**Workload and probe construction constrain what the conclusions mean.** We
evaluate strictly lossless service only; expert substitution, pruning, merging
and reduced-precision fallback are excluded by construction, and §9.4 measures
the gate-mass distribution that would govern one such mechanism without
evaluating any implementation of it. §8.1 closes prefill eviction and admission
only — layer-major versus chunk-major prefill execution ordering was never
measured and remains the largest lever this paper does not examine. All traces
use greedy decoding, which is reproducible but does not sample production
generation diversity. The probe set repackages public sources; its category
proportions are a design choice and estimate no deployment's traffic mix, and
the six archetypes are not a taxonomy of enterprise workloads. §9.1 fits a
static residency set from one calibration trace and measures transfer to one
held-out trace; we do not study how quickly such a set becomes stale under
workload drift, which is the question a deployment would ask.

**Method-specific and statistical limits.** The next-use estimator of §7.3 is a
linear model over eight features with no architecture search; a negative result
from a single estimator is weaker than the decomposition it accompanies, and we
report it because its failure is not marginal and because it is what a
practitioner would try first. The forced-admission decomposition is arithmetic
given a trace and inherits every limitation above. §9.3 compares two service
disciplines, not a family, and §8.3 fixes one fairness setting (`W = 4`, 24
admitted sessions), so its 5.9–7.9% oracle headroom is specific to that
constraint. Tie-seed variation of order $10^{-5}$ bounds simulator
nondeterminism, not sampling variability; we report no population confidence
intervals for quantities estimated from a single trace. Where draw-to-draw
spread is quantified (§5.7) it is an estimate of reference variability from
seven size-matched draws, and each homogeneous condition is still two draws of
twelve requests. Reported ranges apply to one operating point: the 44.18–45.93%
range of §7.1 covers thirteen workload compositions at ρ = 40%, B = 8, and must
not be pooled with the B = 2 condition or the residency sweep, whose gaps span
1.95–44.78%. Discovery and confirmatory splits share no source group but were
collected under the same model, decoding configuration and length cap. Finally,
the audit in §12 evaluates what each work **reports**, not what it does; it
establishes that certain results cannot be compared, not that any is incorrect.

**The two that matter most.** If one limitation were removed we would choose
real-hardware validation: every result here is a block count, and the step to
service quality passes through overlap, topology and contention we do not model.
If a second were removed we would choose a routing trace at the scale the
motivation comes from — because §6 establishes that these results are
regime-dependent, the measurement that would most change our confidence is not a
better policy or a stronger predictor but a trace from that regime.
