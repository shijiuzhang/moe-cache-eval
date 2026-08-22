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

## Deferred corrections for a future arXiv version

Do not publish a new version solely for these. Fold them in whenever a version
is produced for another reason, such as a journal revision.

1. **Abstract and §13 use the future tense for artifact release.** Both say
   "On publication we will release the simulator, a diversity-controlled probe
   set, the contamination diagnostics and a reporting checklist". Everything is
   already public as of 2026-08-11. A reader of v1 may conclude the artifacts
   are unavailable. Replace with the present tense and cite
   <https://github.com/shijiuzhang/moe-cache-eval> and
   <https://doi.org/10.5281/zenodo.21788821> directly.
2. **The arXiv licence is per-version and irrevocable.** v1 carries the arXiv
   perpetual non-exclusive licence. If a future version should carry CC BY or
   the CC BY-NC-ND required after journal acceptance, that choice is made at
   the moment the new version is submitted.

---

## Journal submission

| | |
|---|---|
| **Journal** | *Performance Evaluation* (Elsevier, ISSN 0166-5316) |
| **Manuscript number** | **PEVA-D-26-00369** |
| Submitted | 2026-08-11 |
| Handling editor | Giuliano Casale (Editor-in-Chief) |
| System | Editorial Manager, <https://www.editorialmanager.com/peva/> |
| Review model | Single anonymized |
| Indexing | SCIE; CCF B |
| Manuscript file | `paper/submission/manuscript-submission.pdf` — 39 pp, continuous line numbering 1–1270 |
| Attachments | `cover-letter.pdf`, `declaration-of-interest.pdf` |
| Suggested reviewers | Supplied; three named, none opposed. Names are not recorded here — they are third parties who took no part in this work. |
| Preprint declared | arXiv:2608.07911 |
| SSRN co-posting | Declined |
| Data availability | Published verbatim, 172 characters, pointing to the GitHub repository and the Zenodo hash manifest |

### Expected timeline, from the journal's published medians

| Milestone | Median | Projected |
|---|---:|---|
| Submission to first decision | 4 d | 2026-08-15 |
| Submission to decision after review | 93 d | 2026-11-12 |
| Submission to acceptance | 126 d | 2026-12-15 |
| Acceptance to online publication | 11 d | 2026-12-26 |

The 4-day median for a first decision sits 89 days below the median for a
decision after review, which implies that most submissions are desk-rejected
without going out for review. A decision arriving within roughly a week is
therefore most likely a desk rejection; silence past that point indicates the
manuscript went to reviewers.

**If desk-rejected:** the next targets in order are JPDC (CCF B, SCIE), then
FGCS or Concurrency and Computation (CCF C, SCIE). The initial submission was
free-format under "Your Paper Your Way", so redirecting costs only a revised
cover letter.

**On acceptance:** the arXiv version may be updated to the accepted manuscript,
which must then carry CC BY-NC-ND and link to the ScienceDirect version of
record. arXiv licences are per-version and irrevocable, so that becomes v2.
Record the journal reference here and on the Zenodo record.

**At revision stage:** Editorial Manager does not accept PDFs for the
manuscript, table or title-page item types. An editable Word version will need
to be produced from the LaTeX source at that point.

---

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

---

## SSRN preprint record

| Field | Value |
|---|---|
| SSRN Abstract ID | 7269986 |
| Abstract page | <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7269986> |
| Submitted | 2026-08-12 |
| Licence | CC BY (matches the Zenodo record) |
| Status | **Revised 2026-08-22** — current manuscript, current title, full AI declaration |
| Author affiliation as entered | China National Chemical Equipment Co. Ltd |

Posted for reach into the technical-economics readership through the JEL codes
(C63 computational techniques and simulation modelling, L86 information and
internet services, O33 technological change and diffusion). The computer-science
readership for this paper is on arXiv, not SSRN; the SSRN record exists to
establish an author profile in the second research direction rather than to
distribute this paper.

**Do not use the "Journal Finder" prompt shown after submission.** The next
submission goes to a target chosen on its own merits, with a cover letter
written for it, not through a routing tool.

The record was revised on 2026-08-22 to carry the current manuscript and title.
The file SSRN serves was downloaded afterwards and checked rather than assumed:
it is byte-identical to `paper/v2/manuscript.pdf`, 39 pages, with no rendering
defects and the full declaration present.

### Cross-references still to add

- Zenodo — concept DOI 10.5281/zenodo.21788820, currently version 3
  (10.5281/zenodo.22055736) → Alternate identifiers → add the SSRN abstract URL.
- ORCID 0009-0000-8884-6497 → Works → add the SSRN record, and cite the concept
  DOI rather than a version DOI.
- No change to the arXiv or journal records; neither has a field for this.

---

## arXiv version 2 — announced 2026-08-14

Replaced in place, so the identifier 2608.07911 is unchanged and v1 remains
permanently reachable at <https://arxiv.org/abs/2608.07911v1>.

Two changes, neither touching a result: the declaration of generative AI and
AI-assisted technologies with its companion statement in Section 3, and the
correction of the rendering defect recorded in `RENDERING_DEFECT_2026-08-13.md`.

Verified against the copy arXiv itself compiled and serves, not against the
local build: 39 pages, no hits from `scripts/check_rendered_pdf.py`, both AI
statements present, and all four rows of Table B1 restored. This matters because
v1 was correct locally and corrupt on arXiv, so a local build proves nothing
about what readers receive.

Deferred corrections listed earlier in this file were **not** folded in. The
tense of the artifact-release sentence still reads as future. That was a
deliberate choice: a version published to correct a disclosure failure should
change only what it says it changes, so that a reader comparing v1 and v2 sees
exactly the two stated corrections and nothing else.

---

## arXiv version 3 — submitted 2026-08-22

Replaced in place as `submit/7980236`; the identifier 2608.07911 is unchanged and
every earlier version remains permanently reachable. Announcement follows the
usual cycle.

Two changes, neither touching a result, number, table, figure or conclusion.

1. **The declaration of generative AI is completed.** Version 2 named Claude
   (Anthropic) only; the work also used Codex (OpenAI). Both are now named with
   their distinct roles, in the declaration and in the Section 3 statement. The
   declaration also states the author's role precisely and states that neither
   system synthesised, altered or selected any raw trace, observation or
   reported number.
2. **The title changes** to *Reproducible Evaluation of MoE Expert Caching:
   Replay Semantics, Workload Contamination, and Operating Regimes*. The
   subtitle is unchanged. The previous interrogative title read as a critique
   rather than as the reusable evaluation method the paper delivers.

39 pages before and after; extracted word count 18,701 → 18,820, and the
119-word difference is exactly these two edits.

The abstract was **not** changed. arXiv stores a condensed abstract of 1,893
characters, cut to fit the 1,920-character limit, while the manuscript's own
abstract is 2,279. The two have always differed and both are accurate.

### Verification after announcement

Download the PDF **arXiv itself compiles and serves** and run
`scripts/check_rendered_pdf.py` against it, then confirm the new title on the
abstract page. A local build proves nothing about what a reader receives.

## Companion records, as of 2026-08-22

| Record | Version | State |
|---|---|---|
| arXiv 2608.07911 | v3 submitted | queued for announcement |
| Zenodo (concept 10.5281/zenodo.21788820) | deposit-3, 10.5281/zenodo.22055736 | published, files verified by MD5 |
| SSRN 7269986 | revised | live, served file verified byte-identical |

All three carry the same manuscript and the same title.
