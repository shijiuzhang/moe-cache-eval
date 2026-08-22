# Zenodo deposit — ready-to-paste metadata

## ✅ DEPOSITED

| | |
|---|---|
| **DOI** | **10.5281/zenodo.21788821** |
| **Resolves to** | https://doi.org/10.5281/zenodo.21788821 |
| **Deposit date (priority date)** | **2026-08-04** |
| **arXiv** | [arXiv:2608.07911](https://arxiv.org/abs/2608.07911) — announced 2026-08-08, cs.LG primary, cs.PF cross-list |
| **arXiv DOI** | 10.48550/arXiv.2608.07911 |
| Author | Zhang, Yu — ORCID [0009-0000-8884-6497](https://orcid.org/0009-0000-8884-6497) |
| Affiliation | China National Chemical Equipment Co. Ltd. |
| Files | Embargoed until 2026-12-31 |
| Metadata | Public (verified by anonymous fetch) |
| Licence | CC BY 4.0 |
| Deposited manuscript SHA-256 | `32b16ce0bf1fcc7860d40425918f45d76c171bc6b53a6d47d382b66b169d9a60` |

**Cite as:** Zhang, Y. (2026). *Reproducible Evaluation of MoE Expert Caching:
Replay Semantics, Workload Contamination, and Operating Regimes.* Zenodo.
https://doi.org/10.5281/zenodo.21788820

The **concept** DOI is used here deliberately: it resolves to the newest version,
which since 2026-08-22 is version 3 (`10.5281/zenodo.22055736`). The version DOIs
`…21788821` (v1) and `…21913767` (v2) still resolve to records carrying the
previous title, "When Does Trace-Driven Evaluation Mislead MoE Expert Caching?",
which was changed in version 3.

### Outstanding actions on this record

- [ ] Add the arXiv ID under **Alternate identifiers**
      (`Scheme: arXiv`, `Identifier: arXiv:2608.07911`)
- [ ] Shorten the embargo to release the files
- [x] ~~Merge the wide-table layout fix from `moe-cache-eval-release`~~ — **not
      required.** Verified 2026-08-04: the portrait-table restructuring was made
      in the lab first and copied outward, and the deposited build reports
      **0 overfull hboxes** at 38 pages. `moe-cache-eval-release` contains
      nothing the lab lacks; the only differences are the ORCID author block and
      the 10pt layout, both newer in the lab. The deposited PDF is the current
      best version and needs no replacement inside the 45-day file window.
- [ ] Keep `moe-cache-eval` on GitHub **private** until arXiv is live.

---

## 1. Upload type

**Publication** → **Preprint**

---

## 2. Files to upload

| file | source path | why |
|---|---|---|
| `manuscript.pdf` | `paper/v2/manuscript.pdf` | the work itself |
| `ZENODO_ARTIFACT_HASHES.json` | `paper/ZENODO_ARTIFACT_HASHES.json` | SHA-256 of 32 files across 20 artifact groups |
| `references.bib` | `paper/references.bib` | the 26 verified citations as of deposit |

Do **not** upload the routing traces or the probe corpus in this deposit. Their
hashes are in `ZENODO_ARTIFACT_HASHES.json`, which is what establishes that they
existed in this exact state on the deposit date. Bulk data release is a separate
decision governed by `ARTIFACT_LICENSE_MATRIX.md`.

---

## 3. Basic information

**DOI** — leave blank, select *"Get a DOI now!"* so Zenodo mints one via DataCite.

**Resource type** — Preprint

**Title**

```
Reproducible Evaluation of MoE Expert Caching: Replay Semantics, Workload Contamination, and Operating Regimes
```

From version 3 onward. Versions 1 and 2 were deposited under the previous title
and are not retitled; Zenodo's title field is per-version.

**Publication date** — the deposit date (this is the date that carries the
priority claim; do not backdate).

**Creators**

```
Family name: Zhang
Given names: Yu
Affiliation: [CONFIRM — see note 8.1]
ORCID: [supply if you have one; create at orcid.org first, it takes 5 minutes]
```

**Version**

```
manuscript-v2 (2026-08-02)
```

**Language** — English

---

## 4. Description / abstract

Paste the following. It is the manuscript abstract with LaTeX markup removed
and one added provenance paragraph; Zenodo's description field is HTML-ish and
does not render `$...$` or `*emphasis*`.

```
Mixture-of-Experts (MoE) models have outgrown the high-bandwidth memory of the
accelerators that serve them, and offloading expert weights to host memory has
become a standard response. This makes expert cache management an attractive
lever: if a smarter policy raised the hit rate, the same model would need less
expert traffic per token. Evaluating that hypothesis is a measurement problem,
and we find the measurement fragile.

Using a trace-driven, event-atomic simulator over three MoE models (40, 64 and
128 experts), we isolate three evaluation axes that change conclusions rather
than shift numbers. Replay semantics: under a fused-event traffic contract, an
inconsistent per-access replay inflates recency-based policies by 27-29% while
leaving frequency-based and static policies within 4%, inverting the policy
ranking. Workload contamination: probe sets using one instruction template per
category produce verbatim-identical generation prefixes; a matched-pair
rendering intervention moves the measured early-window effect by 19.4-31.9
percentage points and reverses which workloads appear most cache-friendly.
Operating regimes: normalized miss fractions do not transfer across models, so
the per-step expert union relative to per-layer capacity must be reported,
though permuting only the temporal order of an otherwise identical event stream
moves the offline-optimal gap from 44.9% to 30.8%, so it is not sufficient.

After correcting all three, a stable gap to the offline optimum remains
(44.2-45.9% across 13 frozen workload compositions). A forced-admission oracle
attributes 84.3-96.6% of it to knowing which resident expert is used furthest in
the future. A causal next-use predictor, used as an eviction rule, recovers
-11.4% of the gap; at the decision points it selects an optimal victim 3.4% of
the time against 2.4% for a random resident block and 20.6-22.1% for LRU and
LFRU. Our position is narrow: in our evaluated settings a large offline-optimal
gap substantially overstates the gains recovered by representative lightweight
causal mechanisms.

All results are trace-driven simulation. No real host-to-device transfer,
interconnect topology, kernel time or latency was measured, and no deployment
claim follows from any result. This deposit records the manuscript together
with SHA-256 hashes of the simulator, the diversity-controlled workload probe
set, the contamination diagnostics and the frozen result manifests, so that a
later public release can be verified against this record.
```

---

## 5. Access

**Access right** — **Embargoed**

**Embargo date** — `2026-12-31`

Rationale to record in your own notes (Zenodo does not require it): the embargo
must outlast arXiv moderation and endorsement. An embargo can be shortened
later by editing the record; it cannot be usefully lengthened after the fact,
so err long. Lift it as soon as the arXiv posting is live.

**Why embargoed rather than open**

- The DOI, title, authors, abstract and deposit date are public immediately —
  that is the entire priority claim, and it is satisfied without disclosing the
  file.
- An embargoed deposit is not a public disclosure, so it does not start any
  novelty clock. If anything in the later tooling work is ever intended for
  patent protection, an open deposit would foreclose it in absolute-novelty
  jurisdictions including China and the EU.

**Licence** — `Creative Commons Attribution 4.0 International (CC BY 4.0)`

CC BY is the least friction for a preprint that you also want cited and reused,
and is compatible with arXiv's licence options. It governs **this manuscript
only**; it does not and cannot relicense the upstream datasets, model weights
or third-party code recorded in `ARTIFACT_LICENSE_MATRIX.md`.

---

## 6. Keywords and subjects

```
Mixture-of-Experts
MoE inference
expert offloading
cache replacement
performance evaluation
trace-driven simulation
evaluation methodology
measurement validity
Belady optimal
benchmarking
negative results
```

---

## 7. Related identifiers

Add these under *Related/alternate identifiers*. They cost nothing and they
make the record self-documenting.

| relation | identifier | note |
|---|---|---|
| `is supplemented by` | arXiv ID | **add after arXiv posting** by editing the record |
| `cites` | `10.48550/arXiv.2401.14361` | MoE-Infinity |
| `cites` | `10.48550/arXiv.2602.03921` | SpecMD |
| `cites` | `10.48550/arXiv.2502.12224` | Fate |
| `is derived from` | `10.48550/arXiv.2308.14508` | LongBench (probe payloads) |
| `is derived from` | `10.48550/arXiv.2308.11462` | LegalBench (probe payloads) |
| `is derived from` | `10.48550/arXiv.2402.11717` | BFCL (probe payloads) |
| `is derived from` | `10.48550/arXiv.2411.07763` | Spider 2.0 (probe payloads) |

(arXiv DOIs follow the pattern `10.48550/arXiv.<id>`. Verify each before
entering it.)

**Funding** — leave empty. Do not list a grant you do not have.

---

## 8. Three decisions only you can make

### 8.1 Affiliation

`ARXIV_SUBMISSION_METADATA.md` currently records **"China National Chemical
Equipment Co. Ltd."** This must match what the employer review approved, and it
must be the same string on Zenodo, arXiv and the journal submission — an
affiliation that changes between records looks careless and invites questions.

If the review approved a personal-capacity submission rather than a corporate
one, the correct field is `Independent researcher` and the employer should not
appear at all. **Confirm which it is before depositing**, because the deposit
date is the thing you are trying to make immutable.

### 8.2 ORCID

If you do not have one, create it before depositing. It is free, takes about
five minutes, and it is the identifier that ties the Zenodo record, the arXiv
submission and the journal submission to the same person. Endorsers also look
for it.

### 8.3 Email on the record

Use the `tsinghua.org.cn` address consistently across Zenodo, arXiv and the
endorsement request. Consistency matters more than which domain you pick.

---

## 9. A conflict to resolve before the arXiv step

This does not affect the Zenodo deposit, but resolve it before you write to
Leyang Xue.

`ARXIV_SUBMISSION_METADATA.md` freezes **cs.PF primary, cs.LG cross-list**.
That classification is the more accurate description of the contribution.

But **arXiv endorsement is per-category**, and MoE-Infinity is **cs.LG primary
with cs.PF cross-listed**. Whether a cross-list confers endorsement eligibility
for that category is not documented in arXiv's public help pages. If it does
not, an endorsement obtained from that paper's authors may cover `cs.LG` and
not `cs.PF`, and a `cs.PF` primary submission would still be blocked.

Two options:

| option | trade-off |
|---|---|
| Keep `cs.PF` primary | More accurate; risks the endorsement not applying, costing another round and another researcher's time |
| Switch to `cs.LG` primary, `cs.PF` cross | Matches this literature's convention (MoE-Infinity, HOBBIT, SpecMD are all cs.LG primary); endorsement almost certainly applies; wider readership; cs.PF cross still reaches the performance community |

**Practical check that settles it:** start the arXiv submission, select the
category, and read the endorsement request email arXiv generates — it names the
category the endorsement will apply to. Then open the MoE-Infinity abstract page
and use *"Which authors of this paper are endorsers?"* while that category is
what you need. If the answer is ambiguous, submit `cs.LG` primary first; you can
request a cross-list to `cs.PF` after the paper is live.

---

## 10. Order of operations

```
1. Confirm affiliation string (8.1) and create ORCID (8.2)
2. Deposit on Zenodo, embargoed          -> DOI issued, priority established
3. Screenshot the DOI record
4. Start the arXiv submission, choose the category, get the endorsement link
5. Email Leyang Xue: Zenodo DOI, not the PDF
6. On arXiv acceptance: add the arXiv ID as a related identifier, lift embargo
7. Journal submission (Performance Evaluation) with the same author string
```

Steps 1–3 take under an hour and are the ones that make every later step safe.

---

## Licence consistency across venues

| Venue | Licence | Revocable |
|---|---|---|
| arXiv v1 (2608.07911) | arXiv.org perpetual non-exclusive 1.0 | No — per-version and frozen |
| Zenodo (10.5281/zenodo.21788821) | CC BY 4.0 | No — published |
| SSRN | CC BY, chosen 2026-08-12 to match Zenodo | No |
| Source code repository | Apache License 2.0 | — |

The manuscript is already available under CC BY 4.0 through the Zenodo record.
Selecting a more restrictive licence at any later venue would not restrict
anyone, because the CC BY copy exists and cannot be withdrawn; it would only
make the records disagree. CC BY was therefore chosen at SSRN for consistency
rather than as a fresh grant.

None of these licences relicense the upstream datasets, model weights or
third-party code, whose terms remain as recorded in `ARTIFACT_LICENSE_MATRIX.md`.

If Performance Evaluation accepts the paper, the **accepted manuscript** is a
distinct version and will carry whatever licence Elsevier requires, expected to
be CC BY-NC-ND. That does not conflict with the preprint licences above and
does not retroactively affect them.

---

## Version 2 of the deposit — published 2026-08-13

| Field | Value |
|---|---|
| **Concept DOI** | **10.5281/zenodo.21788820** — always resolves to the newest version; cite this from now on |
| Version 2 DOI | 10.5281/zenodo.21913767 |
| Version 1 DOI | 10.5281/zenodo.21788821 — still resolves to the 2026-08-04 files |
| Version label | `deposit-2 — manuscript of 2026-08-13` |
| Manuscript SHA-256 | `e8304da0ebf0935a10c8126e4bf3695f08622ee41bbad872bb7196e3d3063803` |
| Licence | CC BY 4.0, unchanged |

Contents verified against the local staging copies by MD5 after publication:
`manuscript.pdf` = `1d87a883222dee6b9a5f9a77b8ad9b9c`,
`ZENODO_ARTIFACT_HASHES.json` = `efc4486ad7b42e94c24bf231e8362d01`. Both match.

**`references.bib` is absent from version 2.** It was removed with the other
files and not re-uploaded, and Zenodo does not permit file changes after
publication. It is not being corrected: the bibliography is already rendered
into the manuscript, and the file remains available in version 1 and in the
source repository. Include it if a third version is ever published for another
reason. — Version 3 was published, and it is restored there.

---

## Version 3 of the deposit — published 2026-08-22

| Field | Value |
|---|---|
| **Version 3 DOI** | **10.5281/zenodo.22055736** |
| **Concept DOI** | 10.5281/zenodo.21788820 — verified to resolve here (`parent` 21788820, `is_last: true`) |
| Version label | `deposit-3 — manuscript of 2026-08-15` |
| Publication date | 2026-08-22 |
| Title | Reproducible Evaluation of MoE Expert Caching: Replay Semantics, Workload Contamination, and Operating Regimes |
| Manuscript SHA-256 | `fd89c4b43b51476f642f745a3ad52eeb22d400d4d88cc6f139852bfb5bc4b741` |
| Licence | CC BY 4.0, unchanged |

**What changed.** The declaration of generative AI now names both systems used —
Codex (OpenAI) and Claude (Anthropic) — with their distinct roles, states the
author's role precisely, and states that neither system synthesised, altered or
selected any raw trace, observation or reported number. The title changed. No
result, number, table, figure or conclusion changed; 39 pages in both versions,
extracted body +119 words. `references.bib` is restored.

**Verified after publication against the Zenodo API, not the upload form.** The
record holds exactly three files and every MD5 matches the local staging copy:

| File | Bytes | MD5 |
|---|---:|---|
| `manuscript.pdf` | 275,327 | `b1e1f32fb94e77fe9e65dbd67e16d96c` |
| `ZENODO_ARTIFACT_HASHES.json` | 8,445 | `b039a676568dd76a5f2ac1277248b178` |
| `references.bib` | 11,237 | `cfffacd126de47570e625f0651b48474` |

Exactly three files matters on its own: the copied `manuscript.pdf` and
`ZENODO_ARTIFACT_HASHES.json` had to be deleted before uploading, because Zenodo
cannot replace a file in place. A fourth entry would have meant the old
manuscript was still attached under the new DOI.

The deposited `ZENODO_ARTIFACT_HASHES.json` was itself corrected before upload:
its `changed_in_this_version` still described version 2's changes and its
`supersedes` block pointed at version 1. All 33 hash entries verified against
disk both before and after. See `ZENODO_V3_INSTRUCTIONS.md`.

### Which DOI to use

Everything written before 2026-08-13 cites the version-1 DOI `…821`, including
Section 13 of the manuscript, the data availability statement and the cover
letter. Those remain correct — a version DOI is a fixed, citable snapshot — and
are not worth revising.

Use the **concept DOI `10.5281/zenodo.21788820`** in anything written from now
on, including the ORCID entry and the next journal submission, so that the
reference follows future versions instead of freezing on one.
