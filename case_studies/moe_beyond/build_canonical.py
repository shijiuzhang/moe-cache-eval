"""Build the canonical traces for the MoE-Beyond case study (protocol §4.1–4.2).

Outputs go to ``canonical/``, which is git-ignored because every trace there is
derived from third-party data (R2).  Only ``canonical/HASHES.txt`` is tracked.
This script prepares data; it computes no hit rate, regime or diagnostic value.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CASE_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(CASE_DIR))

from adapter import (  # noqa: E402
    build_e2_trace,
    match_by_signature,
    parse_prompt_file,
    reconstruct_prompt_text,
    write_e1_source,
)
from build_controller_probe_d1 import stable_rank  # noqa: E402
from moe_controller.convert import convert_decode_trace  # noqa: E402
from moe_controller.events import sha256_file  # noqa: E402
import prereg_guard  # noqa: E402
from content_digest import content_digest  # noqa: E402

ARRIVAL_SEED = "moe-beyond-case-study-20261018" + "arrival"
SYNTHETIC_BATCHES = (2, 4, 8)
CATEGORY_FIELD = "source_dataset"


def arrival_offset(request_id: str) -> int:
    """PREREG §3: the package's 0–23 admission-offset rule with a case-study seed."""
    return stable_rank(ARRIVAL_SEED, request_id) % 24


def _parse_set(root: Path, relative_paths: list[str], request_ids: list[str]):
    return [
        parse_prompt_file(root / relative, request_id=request_id)
        for relative, request_id in zip(relative_paths, request_ids)
    ]


def build(output: Path) -> dict:
    lock = prereg_guard.verify_prereg()
    root = prereg_guard.THIRD_PARTY_ROOT
    if output.exists() and any(p.name not in {"HASHES.txt", "CONTENT_HASHES.txt"} for p in output.iterdir()):
        raise FileExistsError(f"Canonical directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    predicted_rel = [f"test_datasets/predicted_csvs/prompt_{n}_data_predicted.csv" for n in range(1, 101)]
    formatted_rel = [f"test_datasets/formatted_csvs/prompt_{n}_data_formatted.csv" for n in range(1, 101)]
    train_rel = [f"training_data_eamc/prompt_{n}_data.csv" for n in range(1, 1001)] + [
        f"expert_activation_scripts/training_data_eamc/prompt_{n}_data.csv" for n in range(1001, 2001)
    ]
    prereg_guard.verify_third_party_files(predicted_rel + formatted_rel + train_rel)

    test_ids = [f"moebeyond-test-{n}" for n in range(1, 101)]
    predicted = _parse_set(root, predicted_rel, test_ids)
    formatted = _parse_set(root, formatted_rel, [f"formatted-{n}" for n in range(1, 101)])
    train = _parse_set(root, train_rel, [f"moebeyond-train-{n}" for n in range(1, 2001)])

    violations = {
        "test_predicted": {t.src_file: t.violations for t in predicted if t.violations},
        "test_formatted": {t.src_file: t.violations for t in formatted if t.violations},
        "train": {t.src_file: t.violations for t in train if t.violations},
    }
    (output / "violations.json").write_text(json.dumps(violations, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if any(violations.values()):
        raise ValueError(f"Validation violations found; see {output / 'violations.json'}")

    mapping = match_by_signature(
        {n: t for n, t in zip(range(1, 101), predicted)},
        {n: t for n, t in zip(range(1, 101), formatted)},
    )
    (output / "bijection_predicted_to_formatted.json").write_text(
        json.dumps({str(k): v for k, v in sorted(mapping.items())}, indent=2) + "\n", encoding="utf-8"
    )
    with (output / "test_prompts.jsonl").open("w", encoding="utf-8") as handle:
        for n, trace in zip(range(1, 101), predicted):
            tokens = formatted[mapping[n] - 1].tokens
            handle.write(
                json.dumps(
                    {
                        "id": trace.request_id,
                        "predicted_file": trace.src_file,
                        "formatted_file": formatted[mapping[n] - 1].src_file,
                        "tokens": tokens,
                        "prompt_text_reconstructed": reconstruct_prompt_text(tokens),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
            )

    write_e1_source(predicted, output / "test-e1-source", dataset_label="webglm_qa_test")
    write_e1_source(train, output / "train-e1-source", dataset_label="puffin_train")
    convert_decode_trace(
        output / "test-e1-source", output / "test-e1-b1",
        batch_size=1, queue_order="source", category_field=CATEGORY_FIELD,
    )
    convert_decode_trace(
        output / "train-e1-source", output / "train-e1-b1",
        batch_size=1, queue_order="source", category_field=CATEGORY_FIELD,
    )
    offsets = {request_id: arrival_offset(request_id) for request_id in test_ids}
    (output / "arrival_offsets_test.json").write_text(json.dumps(offsets, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for batch in SYNTHETIC_BATCHES:
        convert_decode_trace(
            output / "test-e1-source", output / f"test-e1-b{batch}-constructed",
            batch_size=batch, queue_order="source", category_field=CATEGORY_FIELD,
            arrival_offset_map=offsets,
        )
    build_e2_trace(predicted, output / "test-e2-b1", dataset_label="webglm_qa_test")
    build_e2_trace(train, output / "train-e2-b1", dataset_label="puffin_train")

    hashes = sorted(
        (str(path.relative_to(output)), sha256_file(path))
        for path in output.rglob("*")
        if path.is_file() and path.name not in {"HASHES.txt", "CONTENT_HASHES.txt"}
    )
    (output / "HASHES.txt").write_text(
        "".join(f"{digest}  {relative}\n" for relative, digest in hashes), encoding="utf-8"
    )
    # Raw file hashes of safetensors files are not rebuild-stable (DEVIATIONS D-003);
    # these content digests are.
    content = sorted(
        (str(path.relative_to(output)), content_digest(path))
        for path in output.rglob("*.safetensors")
    )
    (output / "CONTENT_HASHES.txt").write_text(
        "".join(f"{digest}  {relative}\n" for relative, digest in content), encoding="utf-8"
    )
    return {
        "prereg_sha256": lock["prereg_sha256"],
        "test_requests": len(predicted),
        "train_requests": len(train),
        "files_hashed": len(hashes),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=CASE_DIR / "canonical")
    args = parser.parse_args()
    print(json.dumps(build(args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
