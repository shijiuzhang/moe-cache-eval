# Artifact licence and redistribution matrix

Status: conservative release plan, 2026-08-02. This is an engineering
provenance review, not legal advice.

## Release rule

No artifact inherits one blanket project licence. Code, probe text, model
outputs, route tensors and derived aggregate tables have different provenance.
When a right is unclear, release the builder/collector, frozen IDs, manifest and
cryptographic hash instead of the payload.

| Artifact family | Inputs / upstream terms | Release now? | Required action |
|---|---|---:|---|
| simulator, conversion and audit code | original project code | **yes under Apache-2.0** | root `LICENSE` and `NOTICE` added; preserve third-party notices |
| paper text and original figures | original author work | yes after author licence choice | select arXiv paper licence; state figure sources |
| event-atomic toy trace | original synthetic artifact | yes | release with code licence or CC0/CC-BY as explicitly selected |
| derived CSV/JSON result tables | simulator outputs from locally held routes | generally yes | exclude prompt text and token-level identifiers; include input hashes and methodology |
| ControllerProbe-D1 builder and selection IDs | original transformation code plus public IDs | yes | preserve source URLs, revisions and attribution |
| ControllerProbe-D1 rendered text as one bundle | mixed: public domain/MIT/Apache-2.0/CC-BY-4.0/**CC-BY-SA-4.0** | **not as an undifferentiated permissive bundle** | safest: split by source family and licence; HAI-derived records must carry CC-BY-SA-4.0 and attribution; include OFBiz NOTICE |
| LongBench/GovReport-derived prompts | US government public-domain source; LongBench wrapper MIT | yes with provenance | retain report IDs and LongBench revision |
| BFCL-derived prompts | Apache-2.0 | yes | include licence and attribution |
| Spider2-derived prompts | MIT | yes | include licence and attribution |
| LegalBench/ContractNLI-derived prompts | dataset card CC-BY-4.0; task-level provenance retained | yes with attribution | preserve upstream task name and licence notice |
| HAI-derived prompts | CC-BY-SA-4.0 chosen conservatively because upstream metadata conflicts | yes only under share-alike terms | attribute HAI and distribute this subset under CC-BY-SA-4.0 |
| PRONTO-derived prompts | CC-BY-4.0 | yes with attribution | cite DOI and Zenodo revision |
| Petrobras 3W-derived prompts | data CC-BY-4.0; repository code Apache-2.0 | yes with attribution | cite frozen revision and dataset paper |
| packaging-alarm-derived prompts | CC-BY-4.0 | yes with attribution | cite DOI/source revision |
| OFBiz-derived prompts | Apache-2.0 | yes | include Apache licence and OFBiz NOTICE |
| ERPsim records | licence unverified | **no** | do not publish payload; currently not a ControllerProbe-D1 source |
| Qwen3 route tensors and generated text | Qwen3 weights Apache-2.0; prompts retain their source terms | route tensors: conditional; text: source-by-source | release routes without prompt text/request content where possible; retain snapshot hash and source-family mapping |
| OLMoE route tensors | model and prompt terms must be carried through | conditional | verify model-card licence at release tag; release numeric routes separately from source prompts |
| Granite route tensors | model and prompt terms must be carried through | conditional | verify exact model-card licence at release tag; release numeric routes separately from source prompts |
| AllenAI Mixtral/C4 48-record prefix | third-party public artifact; local README has no captured explicit redistribution licence | **do not mirror by default** | publish downloader, byte range/record selection, SHA-256 and derived aggregate diagnostics; ask upstream or verify dataset-card licence before mirroring JSONL |
| synthetic-prefix positive-control aggregate | locally transformed diagnostic output | yes as aggregate | do not include the third-party source JSONL unless its redistribution terms are verified |
| preregistrations and decision manifests | original project documents | yes | release unchanged; redact only secrets or absolute local paths |

## Recommended repository layout

```text
LICENSE                         # code licence selected by author
NOTICE                          # all required attributions
artifact_licenses/
  controller_probe_sources.csv
  model_snapshots.csv
  route_release_decisions.csv
data/controller_probe_d1/
  public_domain_mit_apache/     # permissive subsets
  cc_by_4_0/                    # attribution subsets
  cc_by_sa_4_0/                 # HAI-derived subset
scripts/download_external_routes.py
analysis/                       # aggregate, content-free result tables
```

## Blocking decisions before public release

1. Split ControllerProbe-D1 by source/licence, or release only the deterministic
   builder plus source IDs until the split is implemented.
2. Verify exact OLMoE and Granite model-card licences for the frozen revisions.
3. Verify the AllenAI route artifact's redistribution terms; absent an explicit
   grant, do not upload the 21.6 MB local prefix.
4. Generate a machine-readable attribution file from the two source manifests.
