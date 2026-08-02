#!/usr/bin/env python3
"""Apply the route-contamination diagnostics to a public routing dataset.

The initial supported format is AllenAI's ``analysis_mixtral`` JSONL artifact:
each row contains ``input_ids``, ``predicted_token_ids``, and ``exp_ids`` with
shape [tokens, top_k, layers].  A truncated final line is ignored so a
range/prefix download can be audited without pretending it is the full file.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-records", type=int, default=48)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument(
        "--synthetic-shared-prefix-tokens",
        type=int,
        default=0,
        help=(
            "Inject a synthetic positive control by copying this many input-token "
            "and route positions from record 0 into every record. This tests "
            "diagnostic sensitivity; it is not a model-generated result."
        ),
    )
    parser.add_argument(
        "--source-url",
        default=(
            "https://huggingface.co/datasets/allenai/analysis_mixtral/"
            "resolve/main/c4_results.jsonl"
        ),
    )
    return parser.parse_args()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_complete_rows(path: Path, limit: int) -> tuple[list[dict], int]:
    rows: list[dict] = []
    malformed = 0
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if len(rows) >= limit:
                break
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if not {"input_ids", "predicted_token_ids", "exp_ids"} <= row.keys():
                malformed += 1
                continue
            rows.append(row)
    return rows, malformed


def _token_ngrams(tokens: np.ndarray, n: int = 5) -> set[tuple[int, ...]]:
    if len(tokens) < n:
        return {tuple(int(value) for value in tokens)}
    return {
        tuple(int(value) for value in tokens[index : index + n])
        for index in range(len(tokens) - n + 1)
    }


def _set_jaccard(left: set, right: set) -> float:
    if not left and not right:
        return 1.0
    return len(left & right) / len(left | right)


def _expert_jaccard(left: np.ndarray, right: np.ndarray) -> float:
    # Inputs are [token, layer, top_k], with unique experts inside top_k.
    equality = left[:, :, :, None] == right[:, :, None, :]
    intersection = equality.any(axis=3).sum(axis=2)
    top_k = left.shape[2]
    union = 2 * top_k - intersection
    return float((intersection / union).mean())


def _inject_shared_prefix(
    token_arrays: list[np.ndarray],
    route_arrays: list[np.ndarray],
    prefix_tokens: int,
) -> int:
    """Inject a token-and-route prefix for a labelled synthetic positive control."""
    if prefix_tokens < 0:
        raise ValueError("Synthetic prefix length must be non-negative.")
    if not prefix_tokens:
        return 0
    shared = min(
        prefix_tokens,
        min(len(array) for array in token_arrays),
        min(len(array) for array in route_arrays),
    )
    if shared == 0:
        raise ValueError("Cannot inject a shared prefix into empty sequences.")
    donor_tokens = token_arrays[0][:shared].copy()
    donor_routes = route_arrays[0][:shared].copy()
    for tokens, routes in zip(token_arrays, route_arrays, strict=True):
        tokens[:shared] = donor_tokens
        routes[:shared] = donor_routes
    return shared


def main() -> None:
    args = _parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}.")
    rows, malformed = _load_complete_rows(args.input, args.max_records)
    if len(rows) < 8:
        raise ValueError(f"Need at least 8 complete records; found {len(rows)}")
    args.output.mkdir(parents=True)

    token_arrays: list[np.ndarray] = []
    route_arrays: list[np.ndarray] = []
    ngram_sets: list[set[tuple[int, ...]]] = []
    for row in rows:
        tokens = np.asarray(row["input_ids"], dtype=np.int64)[: args.max_tokens]
        routes = np.asarray(row["exp_ids"], dtype=np.int16)[: args.max_tokens]
        if routes.ndim != 3:
            raise ValueError(f"Expected exp_ids rank 3; got {routes.shape}")
        # Public artifact layout is [token, top_k, layer].
        routes = np.transpose(routes, (0, 2, 1))
        token_arrays.append(tokens)
        route_arrays.append(routes)
    injected_prefix = _inject_shared_prefix(
        token_arrays,
        route_arrays,
        args.synthetic_shared_prefix_tokens,
    )
    ngram_sets = [_token_ngrams(tokens) for tokens in token_arrays]

    pair_rows: list[dict] = []
    for left_index, right_index in itertools.combinations(range(len(rows)), 2):
        steps = min(len(token_arrays[left_index]), len(token_arrays[right_index]))
        left_tokens = token_arrays[left_index][:steps]
        right_tokens = token_arrays[right_index][:steps]
        token_agreement = float((left_tokens == right_tokens).mean())
        token_ngram_jaccard = _set_jaccard(
            ngram_sets[left_index], ngram_sets[right_index]
        )
        expert_jaccard = _expert_jaccard(
            route_arrays[left_index][:steps], route_arrays[right_index][:steps]
        )
        pair_rows.append(
            {
                "left": left_index,
                "right": right_index,
                "token_positional_agreement": token_agreement,
                "token_5gram_jaccard": token_ngram_jaccard,
                "expert_jaccard": expert_jaccard,
            }
        )

    with (args.output / "pairwise.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(pair_rows[0]))
        writer.writeheader()
        writer.writerows(pair_rows)

    token_agreement = np.asarray(
        [row["token_positional_agreement"] for row in pair_rows]
    )
    ngram_jaccard = np.asarray([row["token_5gram_jaccard"] for row in pair_rows])
    expert_jaccard = np.asarray([row["expert_jaccard"] for row in pair_rows])
    exact_sequences = len({tuple(array.tolist()) for array in token_arrays})
    low_token = token_agreement < 0.05
    higher_token = ~low_token
    correlation = spearmanr(token_agreement, expert_jaccard)

    summary = {
        "records": len(rows),
        "malformed_or_partial_lines_skipped": malformed,
        "tokens_per_record_audited": args.max_tokens,
        "layers": int(route_arrays[0].shape[1]),
        "top_k": int(route_arrays[0].shape[2]),
        "unique_token_sequences": exact_sequences,
        "pair_count": len(pair_rows),
        "token_positional_agreement_mean": float(token_agreement.mean()),
        "token_positional_agreement_p95": float(np.quantile(token_agreement, 0.95)),
        "token_5gram_jaccard_mean": float(ngram_jaccard.mean()),
        "token_5gram_jaccard_p95": float(np.quantile(ngram_jaccard, 0.95)),
        "expert_jaccard_mean": float(expert_jaccard.mean()),
        "expert_jaccard_low_token_mean": (
            float(expert_jaccard[low_token].mean()) if low_token.any() else None
        ),
        "expert_jaccard_higher_token_mean": (
            float(expert_jaccard[higher_token].mean()) if higher_token.any() else None
        ),
        "higher_token_pair_count": int(higher_token.sum()),
        "spearman_token_agreement_vs_expert_jaccard": float(correlation.statistic),
        "spearman_p_value": float(correlation.pvalue),
        "contamination_flag": bool(
            exact_sequences < len(rows)
            or np.quantile(token_agreement, 0.95) >= 0.05
            or np.quantile(ngram_jaccard, 0.95) >= 0.30
        ),
    }
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "kind": (
            "external_route_contamination_synthetic_positive_control"
            if injected_prefix
            else "external_route_contamination_validity_check"
        ),
        "source": {
            "dataset": "allenai/analysis_mixtral",
            "split_file": "c4_results.jsonl",
            "url": args.source_url,
            "local_path": str(args.input.resolve()),
            "local_bytes": args.input.stat().st_size,
            "local_sha256": _sha256(args.input),
            "download_note": (
                "Prefix download of the public JSONL; only complete JSON rows "
                "are audited. This is not represented as the full dataset."
            ),
        },
        "synthetic_transformation": (
            {
                "kind": "shared_token_and_route_prefix",
                "prefix_tokens": injected_prefix,
                "donor_record": 0,
                "purpose": (
                    "Sensitivity positive control only; not a naturally occurring "
                    "or model-generated contamination effect."
                ),
            }
            if injected_prefix
            else None
        ),
        "interpretation_boundary": (
            (
                "This artifact deliberately injects an identical token-and-route "
                "prefix into public C4 records. It tests detector sensitivity to "
                "a known synthetic perturbation, not model response to a prompt "
                "template and not the magnitude of a natural contamination effect."
            )
            if injected_prefix
            else (
                "The public C4 artifact has no workload-category labels or matched "
                "template arm. It tests diagnostic portability and false-positive "
                "behavior, not replication of the internal matched-pair causal effect."
            )
        ),
        "summary": summary,
        "artifacts": ["pairwise.csv", "REPORT.md", "README.md"],
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    report = f"""# External route-contamination diagnostic

Source: `allenai/analysis_mixtral`, `c4_results.jsonl` (public route artifact).

Synthetic shared prefix injected: **{injected_prefix} token-and-route positions**.

This run audits {summary['records']} complete sequences × {summary['tokens_per_record_audited']} tokens,
with {summary['layers']} layers and top-{summary['top_k']} expert IDs.

| metric | value |
|---|---:|
| unique token sequences | {summary['unique_token_sequences']} / {summary['records']} |
| token positional agreement, mean | {summary['token_positional_agreement_mean']:.4%} |
| token positional agreement, p95 | {summary['token_positional_agreement_p95']:.4%} |
| token 5-gram Jaccard, mean | {summary['token_5gram_jaccard_mean']:.6f} |
| token 5-gram Jaccard, p95 | {summary['token_5gram_jaccard_p95']:.6f} |
| expert Jaccard, all pairs | {summary['expert_jaccard_mean']:.6f} |
| expert Jaccard, token agreement <5% | {summary['expert_jaccard_low_token_mean'] if summary['expert_jaccard_low_token_mean'] is not None else 'not estimable (no low-overlap pairs)'} |
| Spearman(token agreement, expert Jaccard) | {summary['spearman_token_agreement_vs_expert_jaccard']:.4f} |
| contamination flag | {summary['contamination_flag']} |

Interpretation boundary: {manifest['interpretation_boundary']}
"""
    (args.output / "REPORT.md").write_text(report, encoding="utf-8")
    readme = (
        "# External route-contamination audit\n\n"
        + manifest["interpretation_boundary"]
        + "\n\nSee `REPORT.md` for summary metrics and `manifest.json` for the "
        "source hash and transformation label.\n"
    )
    (args.output / "README.md").write_text(readme, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
