# arXiv submission metadata

## ✅ ANNOUNCED

| | |
|---|---|
| **arXiv ID** | **[arXiv:2608.07911](https://arxiv.org/abs/2608.07911)** |
| **arXiv DOI** | 10.48550/arXiv.2608.07911 |
| Announced | 2026-08-08 (v1) |
| Subjects | Machine Learning (cs.LG); Performance (cs.PF) |
| Licence | arXiv.org perpetual, non-exclusive licence 1.0 — **irrevocable for v1** |
| Preprint archive | [10.5281/zenodo.21788821](https://doi.org/10.5281/zenodo.21788821) |

The v1 licence cannot be changed. A different licence can only be chosen when
submitting a new version, and there is no reason to publish a version solely to
change it.

---


Last checked: 2026-08-02

## Title

**When Does Trace-Driven Evaluation Mislead MoE Expert Caching?**

Subtitle used in the manuscript: *Replay Semantics, Workload Contamination,
and Operating Regimes*.

## Authors

- **Yu Zhang** — China National Chemical Equipment Co. Ltd.
- Corresponding email: `[TO BE SUPPLIED IN THE ARXIV SUBMISSION FORM]`

## Abstract

Use the abstract in `01_abstract_intro.md` verbatim. Do not maintain a second
copy here, because two independently edited abstracts will drift.

## Subject-class decision

### Final classification (2026-08-04)

- **Primary:** `cs.LG` (Machine Learning)
- **Cross-list:** `cs.PF` (Performance)

### Why this changed from the earlier `cs.PF` primary

The earlier draft froze `cs.PF` primary on accuracy grounds: the contribution is
performance measurement rather than a machine-learning method. That reasoning is
still correct on the merits, but two practical facts decided it the other way.

1. **The cited literature is cs.LG primary.** MoE-Infinity, HOBBIT, SpecMD, Fate
   and DALI are all `cs.LG` primary, several with `cs.PF` or `cs.DC` cross-listed.
   Readers who follow this line of work watch `cs.LG`; `cs.PF` carries far less
   traffic.
2. **Endorsement domain is shared, so it is not a tie-breaker.** arXiv's
   endorsement request for `cs.LG` states that an endorser qualifies by having
   submitted three papers to *any* of the `cs.*` categories — `cs.PF` included —
   between three months and five years ago. Endorsement therefore does not
   distinguish the two choices, and the earlier concern that a `cs.PF` primary
   might be unendorsable does not apply.

If arXiv moderation reclassifies the submission to `cs.PF`, that is an
acceptable outcome and requires no action.

### Endorsement status

- Endorsement requested for `cs.LG` on 2026-08-04.
- Code issued to `zhangyu.2002@tsinghua.org.cn`. **Do not publish the code.**
- First endorser approached: Leyang Xue (University of Edinburgh), submitter of
  MoE-Infinity (arXiv 2401.14361, `cs.LG` primary / `cs.PF` cross-list),
  confirmed eligible via arXiv's own "Which of the authors of this article can
  endorse?" check.
- Method: forward the arXiv endorsement email with a short covering note; link
  the Zenodo DOI rather than attaching the PDF.
- Contact one endorser at a time; arXiv prohibits mass solicitation.

### Why not `cs.DC` as primary

`cs.DC` covers distributed algorithms, parallel computation and cluster
computing. The paper discusses concurrency but does not introduce or evaluate a
distributed protocol or cluster implementation. It is a possible cross-list only
for a later real-system version.

## Comments field

Suggested arXiv comments:

> Measurement and scoped negative-results study. 13 main sections plus an
> evaluation-contract audit appendix. Artifacts include an event-atomic
> simulator, conformance trace, diversity-controlled probe set, contamination
> diagnostics, frozen manifests and redistributable routing results.

Do not claim real-hardware speedup, K3 performance, or a deployable controller
in the comments field.

## Licence selection

The project source code is licensed under **Apache License 2.0**. This does not
set the arXiv paper licence: arXiv's submission form requires a separate paper
distribution licence. A conventional choice is arXiv's non-exclusive licence
to distribute. The paper licence does **not** override the source licences of
data, routes, figures or code. See `ARTIFACT_LICENSE_MATRIX.md`.

## Remaining author-supplied metadata

- corresponding email;
- ORCID identifiers, if desired;
- acknowledgement and funding text;
- conflict-of-interest or employer-review text, if applicable;
- arXiv paper distribution licence selection;
- public repository URL and immutable release tag/DOI.

## Official taxonomy links

- Category taxonomy: https://arxiv.org/category_taxonomy
- Submission help: https://info.arxiv.org/help/submit/index.html
