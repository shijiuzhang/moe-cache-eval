# arXiv submission metadata (working draft)

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

### Frozen classification

- **Primary:** `cs.PF` (Performance)
- **Cross-list:** `cs.LG` (Machine Learning)

Reason: the paper's object is a machine-learning model, but its main
contribution is performance measurement and evaluation: replay semantics,
cache simulation, workload contamination, operating-regime normalization, and
an evaluation checklist. This matches the official `cs.PF` description more
directly than the official `cs.AI` description.

### Why not `cs.DC` as primary

`cs.DC` covers distributed algorithms, parallel computation and cluster
computing. The paper discusses concurrency but does not introduce or evaluate a
distributed protocol or cluster implementation. It is a possible cross-list
only for a later real-system version.

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
