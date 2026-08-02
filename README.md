# MoE Cache Evaluation

Reproducibility package for **When Does Trace-Driven Evaluation Mislead MoE
Expert Caching?** by Yu Zhang (China National Chemical Equipment Co. Ltd.).

The repository focuses on measurement correctness for trace-driven Mixture-of-
Experts cache studies. It contains:

- an event-atomic cache simulator and a hand-checkable conformance trace;
- cache-policy, scheduling, contamination, and operating-regime analyses;
- the tie-aware victim-ranking measurement and its 46,172 sampled decisions;
- preregistrations and content-free aggregate result artifacts;
- the 39-page arXiv manuscript, figures, and self-contained source archive.

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
- Primary arXiv category: `cs.PF`; cross-list: `cs.LG`

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

