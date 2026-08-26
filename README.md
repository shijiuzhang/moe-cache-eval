# MoE Cache Evaluation

> **Paper:** Yu Zhang. *Reproducible Evaluation of MoE Expert Caching: Replay
> Semantics, Workload Contamination, and Operating Regimes.*
> arXiv:2608.07911 (2026). <https://arxiv.org/abs/2608.07911>
>
> ```bibtex
> @misc{zhang2026moecacheeval,
>   title  = {Reproducible Evaluation of MoE Expert Caching:
>             Replay Semantics, Workload Contamination, and Operating Regimes},
>   author = {Zhang, Yu},
>   year   = {2026},
>   eprint = {2608.07911},
>   archivePrefix = {arXiv},
>   primaryClass  = {cs.LG},
>   doi    = {10.48550/arXiv.2608.07911}
> }
> ```


Reproducibility package for **Reproducible Evaluation of MoE Expert Caching**
by Yu Zhang (China National Chemical Equipment Co. Ltd.).

The repository focuses on measurement correctness for trace-driven Mixture-of-
Experts cache studies. It contains:

- an event-atomic cache simulator and a hand-checkable conformance trace;
- cache-policy, scheduling, contamination, and operating-regime analyses;
- the tie-aware victim-ranking measurement and its 46,172 sampled decisions;
- preregistrations and content-free aggregate result artifacts;
- the 38-page arXiv manuscript, figures, and self-contained source archive.

## Scope of this release

This first release deliberately excludes model weights, raw routing traces,
prompt payloads, and locally cached datasets. Those objects are large and carry
upstream terms that cannot be replaced by the repository's Apache-2.0 licence.
Where payload redistribution is not yet cleared, the repository provides the
collector or builder, frozen identifiers, aggregate outputs, and hashes.

See [`paper/ARTIFACT_LICENSE_MATRIX.md`](paper/ARTIFACT_LICENSE_MATRIX.md) and
[`paper/artifact_attributions.csv`](paper/artifact_attributions.csv) before
redistributing data-derived material.

## Paper

- [`paper/v2/manuscript.pdf`](paper/v2/manuscript.pdf)
- [`paper/v2/arxiv_source.tar.gz`](paper/v2/arxiv_source.tar.gz)
- Primary arXiv category: `cs.LG`; cross-list: `cs.PF`
- **Preprint: [arXiv:2608.07911](https://arxiv.org/abs/2608.07911)** (announced 2026-08-08)
- Archived with artifact hashes at [doi.org/10.5281/zenodo.21788821](https://doi.org/10.5281/zenodo.21788821) (deposited 2026-08-04)

## Platform roadmap

The next phase turns the paper's reporting contract into a vendor-neutral,
open-source capacity-planning and acceptance platform for private model
deployments. The draft product contract is available for independent audit:

- [`docs/PLATFORM_PRODUCT_SPECIFICATION_V0_1.md`](docs/PLATFORM_PRODUCT_SPECIFICATION_V0_1.md)
- [`docs/PLATFORM_SPEC_V0_1_AUDIT.md`](docs/PLATFORM_SPEC_V0_1_AUDIT.md)
- [`docs/PLATFORM_SPEC_V0_1_AUDIT_DISPOSITION.md`](docs/PLATFORM_SPEC_V0_1_AUDIT_DISPOSITION.md)

The schema-0.1 checkpoint is deliberately smaller: a self-calibrating black-box
runner that records one honest load point and emits a recomputable, unsigned private
evidence bundle. Verification establishes internal consistency; it does not attest
producer identity or prevent a producer from regenerating altered evidence.
SLO adjudication, sweeps, comparison and reports begin in v0.2. Engine-specific
MoE telemetry is a later diagnostic extension; the specification deliberately
excludes a universal score and unmeasured hardware claims.

The M1 implementation is now under local audit. Its exact implemented boundary,
evidence layout and still-pending acceptance controls are recorded in
[`docs/OICAP_M1_IMPLEMENTATION.md`](docs/OICAP_M1_IMPLEMENTATION.md). It is an
implementation checkpoint, not yet a v0.1 release.

## Quick checks

Python 3.12 is the frozen research environment. Install dependencies with `uv`
and run the release-contained tests:

```bash
uv sync
uv run python -m unittest discover -s tests -v
```

Rebuild the manuscript when Pandoc and Tectonic are available:

```bash
uv run python scripts/build_arxiv_manuscript.py --paper-dir paper/v2
tectonic --outdir paper/v2 paper/v2/manuscript.tex
uv run python scripts/package_arxiv_source.py --paper-dir paper/v2
```

Some end-to-end analysis scripts additionally require the event streams named
in their manifests. These are intentionally not mirrored in this first release.

## Repository layout

```text
moe_controller/    event representation, conversion, metrics, simulation
scripts/           collectors, builders, audits, and paper analyses
tests/             self-contained simulator and paper-evidence tests
analysis/          selected aggregate and decision-level result artifacts
paper/             manuscript, figures, references, and licence audit
plans/             frozen preregistrations and experiment designs
artifacts/         redistribution boundary notes
```

## Licence

Original project source code is licensed under the Apache License 2.0. Dataset,
model, prompt, and route-derived artifacts retain their upstream terms. See
[`LICENSE`](LICENSE), [`NOTICE`](NOTICE), and the artifact licence matrix.
