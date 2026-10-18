"""Analysis C: workload-construction diagnostics (PREREG P5).

Prompt side: the package's ``audit_probe`` (scripts/audit_probe_diversity.py) is
called unchanged on the 100 reconstructed test prompts; its printed table is
parsed and cross-checked against an independent recomputation that uses the
same module's ``ngrams`` and ``jaccard``.

Route side: the §5.8 detector (scripts/audit_external_route_contamination.py)
is run unchanged as a subprocess with its frozen defaults (first 48 complete
records, 512 tokens).  Its input is the test traces in the detector's JSONL
layout.  Token strings are mapped injectively to integers; the detector uses
token IDs only for equality and 5-grams, so its outputs do not depend on the
mapping.  The detector hard-codes an "allenai/analysis_mixtral" source label in
its own output files; those files therefore stay local (canonical/, ignored),
and this analysis records the true provenance and hashes instead.

Outputs: results/C_workload.json, results/C_workload.md (refuses to overwrite).
"""

from __future__ import annotations

import contextlib
import io
import itertools
import json
import re
import subprocess
import sys
from pathlib import Path

CASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CASE_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(CASE_DIR))

import numpy as np  # noqa: E402
from safetensors import safe_open  # noqa: E402

import prereg_guard  # noqa: E402
from audit_probe_diversity import audit_probe, jaccard, ngrams  # noqa: E402
from moe_controller.events import sha256_file  # noqa: E402

RESULTS = CASE_DIR / "results"
CANONICAL = CASE_DIR / "canonical"
DETECTOR = REPO_ROOT / "scripts" / "audit_external_route_contamination.py"
PROMPT_AUDIT = REPO_ROOT / "scripts" / "audit_probe_diversity.py"
MAX_RECORDS = 48
MAX_TOKENS = 512


def _recorded(relative: str) -> str:
    recorded = dict(
        reversed(line.split("  ", 1))
        for line in (CANONICAL / "HASHES.txt").read_text(encoding="utf-8").splitlines()
    )
    digest = sha256_file(CANONICAL / relative)
    if recorded.get(relative) != digest:
        raise RuntimeError(f"{relative} differs from canonical/HASHES.txt")
    return digest


def _load_test_routes() -> list[np.ndarray]:
    """Per test request (predicted numbering), experts as [layer, token, top_k]."""
    source = CANONICAL / "test-e1-source"
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    routes: list[np.ndarray] = []
    for shard in manifest["shards"]:
        with safe_open(source / shard["tensor_file"], framework="pt") as handle:
            lengths = handle.get_tensor("sequence_lengths").tolist()
            indices = handle.get_tensor("topk_indices").numpy()
        for local, length in enumerate(lengths):
            routes.append(indices[local, :, :length, :].astype(np.int64))
    return routes


def prompt_side(prompts: list[dict], workdir: Path) -> dict:
    path = workdir / "C_prompts_for_audit.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for row in prompts:
            handle.write(json.dumps({"dataset": "webglm_qa_test", "prompt_text": row["prompt_text_reconstructed"]},
                                    ensure_ascii=False) + "\n")
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        audit_probe(path, "prompt_text", ["dataset"])
    printed = buffer.getvalue()
    match = re.search(r"^webglm_qa_test\s+(\d+)\s+(\d+)\s+(\d+)\s+([0-9.]+)\s+([0-9.]+)\s+(\d+)\s*$", printed, re.M)
    if not match:
        raise RuntimeError(f"Could not parse audit_probe output:\n{printed}")
    n, heads, tails, mean, p95, median_chars = match.groups()
    flagged = "No contaminated cell detected." not in printed

    # Independent recomputation with the same module's helpers (cross-check only).
    texts = [row["prompt_text_reconstructed"] for row in prompts]
    grams = [ngrams(text) for text in texts]
    sims = sorted(jaccard(grams[i], grams[j]) for i, j in itertools.combinations(range(len(grams)), 2))
    recomputed = {
        "heads": len({text[:70] for text in texts}),
        "tails": len({text.rsplit("\n", 1)[-1][:120] for text in texts}),
        "jaccard_mean": sum(sims) / len(sims),
        "jaccard_p95": sims[int(0.95 * (len(sims) - 1))],
    }
    parsed = {"heads": int(heads), "tails": int(tails), "jaccard_mean": float(mean), "jaccard_p95": float(p95)}
    agree = (
        parsed["heads"] == recomputed["heads"]
        and parsed["tails"] == recomputed["tails"]
        and abs(parsed["jaccard_mean"] - recomputed["jaccard_mean"]) < 5e-5
        and abs(parsed["jaccard_p95"] - recomputed["jaccard_p95"]) < 5e-5
    )
    if not agree:
        raise RuntimeError(f"audit_probe output and recomputation disagree: {parsed} vs {recomputed}")
    return {
        "records": int(n),
        "distinct_prompt_heads_70_chars": parsed["heads"],
        "distinct_final_lines": parsed["tails"],
        "word_5gram_jaccard_mean": recomputed["jaccard_mean"],
        "word_5gram_jaccard_p95": recomputed["jaccard_p95"],
        "median_prompt_chars": int(median_chars),
        "prompt_side_flag": flagged,
        "flag_rules": "heads <= 2, or final lines <= 2, or p95 5-gram Jaccard >= 0.30 (audit_probe_diversity.py:96-101)",
        "max_repeated_template_count": "NA(no skeleton-clustering rule exists in the paper, §5.6)",
        "audit_probe_printout": printed.strip().splitlines(),
        "input_sha256": sha256_file(path),
    }


def route_side(prompts: list[dict], routes: list[np.ndarray], workdir: Path) -> tuple[dict, dict]:
    vocabulary = sorted({token for row in prompts for token in row["tokens"]})
    token_id = {token: index for index, token in enumerate(vocabulary)}
    detector_input = workdir / "C_route_detector_input.jsonl"
    with detector_input.open("w", encoding="utf-8") as handle:
        for row, experts in zip(prompts, routes, strict=True):
            if len(row["tokens"]) != experts.shape[1]:
                raise RuntimeError(f"Token/route length mismatch for {row['id']}")
            handle.write(
                json.dumps(
                    {
                        "id": row["id"],
                        "input_ids": [token_id[token] for token in row["tokens"]],
                        "predicted_token_ids": [],
                        # Detector layout is [token, top_k, layer].
                        "exp_ids": np.transpose(experts, (1, 2, 0)).tolist(),
                    }
                )
                + "\n"
            )
    output = workdir / "C_route_detector"
    completed = subprocess.run(
        [sys.executable, "-I", str(DETECTOR), str(detector_input), "--output", str(output),
         "--max-records", str(MAX_RECORDS), "--max-tokens", str(MAX_TOKENS),
         "--source-url", "https://github.com/ngavhane/moe-beyond (test_datasets, via the case-study adapter)"],
        capture_output=True, text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)
    summary = json.loads((output / "manifest.json").read_text(encoding="utf-8"))["summary"]
    pair_jaccard = np.loadtxt(output / "pairwise.csv", delimiter=",", skiprows=1, usecols=4)
    distribution = {
        f"p{q}": float(np.quantile(pair_jaccard, q / 100)) for q in (5, 25, 50, 75, 95)
    }
    hashes = {
        "detector_input_jsonl_local": sha256_file(detector_input),
        "detector_manifest_local": sha256_file(output / "manifest.json"),
        "detector_pairwise_csv_local": sha256_file(output / "pairwise.csv"),
    }
    return summary | {"expert_jaccard_pairwise_quantiles": distribution}, hashes


def main() -> None:
    lock = prereg_guard.verify_prereg()
    for name in ("C_workload.json", "C_workload.md"):
        if (RESULTS / name).exists():
            raise FileExistsError(f"Refusing to overwrite {RESULTS / name}")
    workdir = CANONICAL / "C_workload_local"
    if workdir.exists():
        raise FileExistsError(f"Refusing to overwrite {workdir}")
    workdir.mkdir()

    files = {
        "canonical/test_prompts.jsonl": _recorded("test_prompts.jsonl"),
        "scripts/audit_probe_diversity.py": sha256_file(PROMPT_AUDIT),
        "scripts/audit_external_route_contamination.py": sha256_file(DETECTOR),
    }
    for line in (CANONICAL / "HASHES.txt").read_text(encoding="utf-8").splitlines():
        digest, _, relative = line.partition("  ")
        if relative.startswith("test-e1-source/routes-"):
            files[f"canonical/{relative}"] = _recorded(relative)
    files.update(prereg_guard.verify_third_party_files(
        ["expert_activation_scripts/generate_deepseek_logs_eamc.py",
         "expert_activation_scripts/generate_deepseek_logs_v2.py",
         "expert_activation_scripts/generate_deepseek_logs.py"]))

    prompts = [json.loads(line) for line in (CANONICAL / "test_prompts.jsonl").read_text(encoding="utf-8").splitlines()]
    routes = _load_test_routes()
    prompt = prompt_side(prompts, workdir)
    route, local_hashes = route_side(prompts, routes, workdir)
    files.update({f"canonical/C_workload_local/{k}": v for k, v in local_hashes.items()})
    files["canonical/C_workload_local/C_prompts_for_audit.jsonl"] = prompt["input_sha256"]

    payload = {
        "prompt_side": prompt,
        "route_side": route,
        "route_side_scope": (
            "first 48 complete test records in predicted numbering, prompt input sequences "
            "(no generated tokens exist), detector defaults frozen in §5.8"
        ),
        "chat_template_applied": {
            "value": "no",
            "evidence": "all three collection scripts call tokenizer(text) on raw text "
                        "(generate_deepseek_logs_eamc.py:122); the script instance that produced "
                        "the test set is not identified in the repository",
        },
        "decode_steps_recorded": {
            "value": 0,
            "evidence": "one prefill forward pass per prompt (generate_deepseek_logs_eamc.py:122-124); "
                        "no generate(), max_new_tokens or do_sample in any repository script",
        },
        "category_dependent_items": "NA(no category labels)",
        "inputs": prereg_guard.inputs_record(lock, files),
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "C_workload.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    flag = "true" if route["contamination_flag"] else "false"
    md = [
        "# Analysis C — workload construction", "",
        "| prompt side (100 test prompts) | value |", "|---|---:|",
        f"| distinct 70-character prompt heads | {prompt['distinct_prompt_heads_70_chars']} |",
        f"| distinct final lines | {prompt['distinct_final_lines']} |",
        f"| word 5-gram Jaccard, mean / p95 | {prompt['word_5gram_jaccard_mean']:.4f} / {prompt['word_5gram_jaccard_p95']:.4f} |",
        f"| prompt-side flag | {str(prompt['prompt_side_flag']).lower()} |",
        "| max repeated template count | NA (no skeleton rule in §5.6) |",
        "| chat template applied | no |",
        "| decode steps recorded | 0 |", "",
        "| route side (first 48 records, input sequences) | value |", "|---|---:|",
        f"| unique token sequences | {route['unique_token_sequences']} / {route['records']} |",
        f"| positional token agreement, mean / p95 | {route['token_positional_agreement_mean']:.4f} / {route['token_positional_agreement_p95']:.4f} |",
        f"| token 5-gram Jaccard, mean / p95 | {route['token_5gram_jaccard_mean']:.4f} / {route['token_5gram_jaccard_p95']:.4f} |",
        f"| expert Jaccard, mean (pairwise p5–p95) | {route['expert_jaccard_mean']:.4f} "
        f"({route['expert_jaccard_pairwise_quantiles']['p5']:.4f}–{route['expert_jaccard_pairwise_quantiles']['p95']:.4f}) |",
        f"| expert Jaccard on low-text-overlap pairs (agreement < 5%) | {route['expert_jaccard_low_token_mean']} |",
        f"| §5.8 detector flag | {flag} |", "",
        f"On the public test prompts, the §5.8 detector reports flag = {flag}; this is a detector-level "
        "screening result, not a replication or refutation of any workload effect in that study.", "",
    ]
    (RESULTS / "C_workload.md").write_text("\n".join(md), encoding="utf-8")
    print(RESULTS / "C_workload.md")


if __name__ == "__main__":
    main()
