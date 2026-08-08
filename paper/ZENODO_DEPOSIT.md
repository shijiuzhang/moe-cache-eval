# Zenodo deposit — ready-to-paste metadata

## ✅ DEPOSITED

| | |
|---|---|
| **DOI** | **10.5281/zenodo.21788821** |
| **Resolves to** | https://doi.org/10.5281/zenodo.21788821 |
| **Deposit date (priority date)** | **2026-08-04** |
| Author | Zhang, Yu — ORCID [0009-0000-8884-6497](https://orcid.org/0009-0000-8884-6497) |
| Affiliation | China National Chemical Equipment Co. Ltd. |
| Files | Embargoed until 2026-12-31 |
| Metadata | Public (verified by anonymous fetch) |
| Licence | CC BY 4.0 |
| Deposited manuscript SHA-256 | `32b16ce0bf1fcc7860d40425918f45d76c171bc6b53a6d47d382b66b169d9a60` |

**Cite as:** Zhang, Y. (2026). *When Does Trace-Driven Evaluation Mislead MoE
Expert Caching? Replay Semantics, Workload Contamination, and Operating
Regimes.* Zenodo. https://doi.org/10.5281/zenodo.21788821

### Outstanding actions on this record

- [ ] After arXiv posting: add the arXiv ID under **Alternate identifiers**
      (`Scheme: arXiv`, `Identifier: arXiv:26XX.XXXXX`)
- [ ] After arXiv posting: shorten the embargo to release the files
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
When Does Trace-Driven Evaluation Mislead MoE Expert Caching? Replay Semantics, Workload Contamination, and Operating Regimes
```

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
