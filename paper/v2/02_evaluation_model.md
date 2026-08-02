# §2 Evaluation Model

*Draft v2 — 2026-08-02.*

Results in this area are difficult to compare because the underlying replay
model is rarely stated. We therefore fix notation and semantics before reporting
any number. Everything in §4–§8 is defined against this model, and a
hand-verifiable reference trace is released with the artifacts.

## 2.1 Traces and events

A model has `L` MoE layers and `N` routed experts per layer, and routes each
token to `k` experts per layer. The unit of cache management is an **expert
block** `b = (l, e)` with `l ∈ [L]`, `e ∈ [N]`; the block universe has size
`L·N`.

Requests are served under first-come-first-served continuous batching. At
scheduling step `s`, `A(s)` denotes the set of active requests. For the
fused-event traffic contract evaluated in this paper, the quantity that matters
for memory traffic is not the per-token expert assignment but its **union over
the concurrent batch**:

> **Definition 1 (event).** An *event* is a pair `(s, l)`. Its expert set is
> `E(s, l) = ⋃_{r ∈ A(s)} topk(r, l, s)`, the distinct expert blocks that step
> `s` touches at layer `l`.

A **trace** is the sequence of events ordered lexicographically by `(s, l)`.
Deduplication inside an event is a property of the execution unit, not of any
cache policy: an expert selected by five concurrent requests is fetched once.
We therefore treat it as free and never credit it to a policy (§2.4).

## 2.2 Event-atomic replay

> **Definition 2 (event-atomic replay).** Let `C` be the cache contents. For
> each event `(s, l)` in trace order:
>
> 1. take the snapshot `C` at event start;
> 2. classify every member of `E(s,l)` against that snapshot:
>    `hits = E ∩ C`, `misses = E \ C`;
> 3. serve **all** of `misses` (no partial service);
> 4. only after the event completes, apply admission and eviction to obtain
>    `C'`.

The ordering constraint is step 4. Admission and eviction are deferred to the
event boundary, so no member of `E ∩ C` can be evicted before the event that
needs it has completed. This counts each missing expert once and assumes the
execution workspace can stream that expert, compute all tokens routed to it,
and release temporary state before choosing the retained cache contents. It does
**not** assume that all members of `E` fit in the cache simultaneously.

**Sequential replay**, the alternative we examine in §4, flattens `E(s,l)` into
an ordered list of individual accesses and applies admission and eviction after
each one. When `|E(s,l)|` exceeds the layer's quota, an access late in the event
can evict a block in `E ∩ C` that the *same* event has not yet consumed, which
is then counted as a miss.

**A remark on modelling.** We do not claim event-atomic replay is the only
admissible model of MoE execution. An engine that serializes expert loads within
a layer is a legitimate alternative, and a simulator may reasonably model it.
The distinction we draw is narrower and is a correctness property, not a
preference:

> Sequential *execution* is a realizable system. What is inconsistent is to
> claim one-transfer-per-distinct-expert fused-event accounting while evicting a
> block resident at event start, still required later in that committed event,
> and counting its refetch as if it were a new demand.

A simulator should state which contract it targets. Section 4 measures what
happens when a flattened replay is used to estimate the fused-event contract
without protecting start-resident, not-yet-served members.

## 2.3 Cache scope, capacity and policies

Capacity is a residency fraction `rho` of the block universe; the resident set
at any instant is the analogue of a working set in the classical sense
[@denning1968workingset]. Under **per-layer
scope** the budget is divided into quotas `c_l`, with the remainder to the
lowest-indexed layers; under **global scope** a single pool serves all layers.
Per-layer scope is primary throughout, because expert weights are consumed
layer-by-layer within a step.

We evaluate `Demand` (no cache), `Static` (a fixed set chosen offline from a
calibration trace and never updated), `LRU`, `LFU`, `LFRU` (rank by
`frequency / age`), `Least-Stale` (blocks untouched in the current forward cycle
are evicted first), `Belady` [@belady1966replacement] (offline optimum with bypass admission), and
`Belady-forced-admit`, which is not deployable but is the decomposition probe of
§7.2. Ties break by seeded random priority; §7.1 reports tie-seed sensitivity.
Two static pin protocols appear in this paper and are named where used: a
**calibration-fitted** list, frozen from a disjoint trace and used in §9, and a
**same-trace diagnostic** list used only in Table 2, where the question is
whether replay semantics moves a policy that by construction cannot move. The
initial load of a pinned set is counted in transferred blocks and reported
separately from steady-state traffic.

## 2.4 Metrics

Let `M` be the number of blocks transferred over a trace, and define

- `logical` — expert assignments **before** intra-event deduplication. For the
  decode traces used in the primary experiments this is
  `Σ_{s,l} |A(s)| · k`; for prefill it must additionally sum the routed tokens
  contributed by each request rather than merely the request count;
- `union   = Σ_{s,l} |E(s,l)|` — distinct blocks touched.

We report

> `effective miss fraction  m = M / logical`
> `recoverable gap          g = (m_best-causal − m_Belady) / m_best-causal`

and, separately, `union / logical`.

Two conventions deserve emphasis. First, `m` uses the **pre-deduplication**
denominator so that a single number remains comparable across concurrency
levels; the deduplication benefit itself is reported as `union / logical` and is
never counted as a policy's contribution, because any FCFS scheduler obtains it
for free. Second, `g` is a *relative* quantity and is meaningful only alongside
the absolute traffic; §6.1 shows that a small `g` can indicate either that
existing policies suffice or that no policy can help, and that the two are
distinguished only by absolute transferred bytes against a bandwidth budget.

For a static pinned set, the initial load of the pinned blocks is counted in `M`
and is reported separately from steady-state traffic. Because this one-time cost
is sensitive to trace length, static/dynamic comparisons must also report the
fit source, quota rule, number of events, and either total traffic or an
amortized steady-state view.

## 2.5 Reference trace

The artifact includes a deliberately small trace — 3 layers, 4 experts per
layer, 5 scheduling steps, 30 union accesses — that can be replayed by hand.
Under Definition 2 with the released capacity setting it yields 12 hits and 18
misses. It is intended as an executable specification: a simulator that does not
reproduce these counts does not implement the semantics used in this paper.
