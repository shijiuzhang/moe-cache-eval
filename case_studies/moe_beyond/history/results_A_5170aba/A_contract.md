# Analysis A — execution contract, Axis I, reproduction

| contract field | value | code | execution check |
|---|---|---|---|
| cache_retained_across_requests | no; each prompt starts from a new, randomly pre-filled cache | `infinity_moe_sim.py:211 (ExpertCache constructed per call), :86-90` | True |
| hit_denominator | each actual expert access | `infinity_moe_sim.py:242-251` | True |
| prefetch_loads_counted_as_hits | no; predicted experts are loaded before counting and change LRU order | `infinity_moe_sim.py:237-239` | True |

| setting | events | max union | fraction over capacity |
|---|---:|---:|---:|
| reported point: B=1, global scope, 166 blocks (int(1664*0.10)) — E1 (per-token) | 40118 | 6 | 0.0000 |
| package frame: B=1, per-layer scope, rho=0.10 (total 166, quotas 6-7) — E1 (per-token) | 40118 | 6 | 0.0000 |
| reported point: B=1, global scope, 166 blocks (int(1664*0.10)) — E2 (whole-prefill) | 2600 | 62 | 0.0000 |
| package frame: B=1, per-layer scope, rho=0.10 (total 166, quotas 6-7) — E2 (whole-prefill) | 2600 | 62 | 1.0000 |

| path | reported | mean over 5 seeds | min–max | files used |
|---|---:|---:|---|---|
| moe_infinity_eamc | 17% | 16.86% | 16.86–16.86% | [80] |
| moe_beyond_predicted | 72% | 72.37% | 72.37–72.37% | [80] |

## Frozen conclusion sentences

- On the in-event eviction probe, the published simulator recorded 6 misses, the count expected under per-access retention; its executed replay contract is classified as per-access.
- On the reference trace of §2.5 the published simulator recorded 12 hits and 18 misses, matching the event-atomic reference counts (12 / 18).
- At reported point: B=1, global scope, 166 blocks (int(1664*0.10)) with E1 (per-token) events, every event's expert set fits within capacity, so in-event eviction cannot occur; whatever replay semantics the simulator uses, its counts there coincide with the event-atomic contract. Axis I does not operate in this setting.
- At package frame: B=1, per-layer scope, rho=0.10 (total 166, quotas 6-7) with E1 (per-token) events, every event's expert set fits within capacity, so in-event eviction cannot occur; whatever replay semantics the simulator uses, its counts there coincide with the event-atomic contract. Axis I does not operate in this setting.
- At reported point: B=1, global scope, 166 blocks (int(1664*0.10)) with E2 (whole-prefill) events, every event's expert set fits within capacity, so in-event eviction cannot occur; whatever replay semantics the simulator uses, its counts there coincide with the event-atomic contract. Axis I does not operate in this setting.
- At package frame: B=1, per-layer scope, rho=0.10 (total 166, quotas 6-7) with E2 (whole-prefill) events, a fraction 1.0000 of events exceed capacity; in that setting the replay contract affects the counts and should be declared (checklist A1–A2).
- Running the published artifact at the reported configuration reproduced the reported value (16.9% vs 17%).
- Running the published artifact at the reported configuration reproduced the reported value (72.4% vs 72%).
