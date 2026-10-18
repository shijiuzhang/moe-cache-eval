"""POST-HOC, NOT PRE-REGISTERED (DEVIATIONS D-004).

Decomposes the positional token agreement behind the pre-registered §5.8
detector flag of analysis C.  It does not replace or reinterpret that flag; it
describes where the agreement sits, so that the detector's length sensitivity
can be stated as a limitation of the package's own tool.

Same records and same agreement definition as the detector: the first 48 test
records in predicted numbering, pairwise equality over the shorter length.

Outputs: results/C_exploratory_positional.json and .md (refuses to overwrite).
"""

from __future__ import annotations

import itertools
import json
import sys
from collections import Counter
from pathlib import Path

CASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CASE_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(CASE_DIR))

import numpy as np  # noqa: E402

import prereg_guard  # noqa: E402
from adapter import BOS_TOKEN  # noqa: E402
from moe_controller.events import sha256_file  # noqa: E402

RESULTS = CASE_DIR / "results"
CANONICAL = CASE_DIR / "canonical"
RECORDS = 48


def main() -> None:
    lock = prereg_guard.verify_prereg()
    for name in ("C_exploratory_positional.json", "C_exploratory_positional.md"):
        if (RESULTS / name).exists():
            raise FileExistsError(f"Refusing to overwrite {RESULTS / name}")
    prompts_path = CANONICAL / "test_prompts.jsonl"
    recorded = dict(
        reversed(line.split("  ", 1))
        for line in (CANONICAL / "HASHES.txt").read_text(encoding="utf-8").splitlines()
    )
    digest = sha256_file(prompts_path)
    if recorded.get("test_prompts.jsonl") != digest:
        raise RuntimeError("test_prompts.jsonl differs from canonical/HASHES.txt")
    tokens = [json.loads(line)["tokens"] for line in prompts_path.read_text(encoding="utf-8").splitlines()][:RECORDS]

    full, without_first, only_first = [], [], 0
    for left, right in itertools.combinations(tokens, 2):
        steps = min(len(left), len(right))
        equal = np.array([left[i] == right[i] for i in range(steps)])
        full.append(float(equal.mean()))
        without_first.append(float(equal[1:].mean()) if steps > 1 else 0.0)
        only_first += bool(equal[0] and not equal[1:].any())
    full_arr, without_arr = np.array(full), np.array(without_first)
    lengths = [len(t) for t in tokens]
    openers = Counter(t[1] for t in tokens if len(t) > 1)

    payload = {
        "status": "POST-HOC, NOT PRE-REGISTERED (DEVIATIONS D-004)",
        "records": len(tokens),
        "pairs": len(full),
        "all_records_start_with_bos": all(t[0] == BOS_TOKEN for t in tokens),
        "tokens_per_record": {"min": min(lengths), "median": float(np.median(lengths)), "max": max(lengths)},
        "positional_agreement_frozen_definition": {
            "mean": float(full_arr.mean()), "p95": float(np.quantile(full_arr, 0.95)),
        },
        "positional_agreement_position_0_excluded": {
            "mean": float(without_arr.mean()), "p95": float(np.quantile(without_arr, 0.95)),
        },
        "pairs_agreeing_only_at_position_0": only_first,
        "pairs_agreeing_only_at_position_0_fraction": only_first / len(full),
        "most_common_tokens_at_position_1": openers.most_common(5),
        "reference_validation_length_tokens": 512,
        "inputs": prereg_guard.inputs_record(lock, {"canonical/test_prompts.jsonl": digest}),
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "C_exploratory_positional.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    md = [
        "# Analysis C — exploratory decomposition of positional agreement",
        "",
        "**POST-HOC, NOT PRE-REGISTERED (DEVIATIONS D-004).** The pre-registered detector result in "
        "`C_workload.md` stands unchanged; this file only describes where the agreement sits.",
        "",
        "| quantity | value |",
        "|---|---:|",
        f"| records / pairs | {payload['records']} / {payload['pairs']} |",
        f"| tokens per record, min / median / max | {min(lengths)} / {np.median(lengths):.1f} / {max(lengths)} |",
        f"| all records start with the same BOS token | {str(payload['all_records_start_with_bos']).lower()} |",
        f"| positional agreement, frozen definition, mean / p95 | {full_arr.mean():.4f} / {np.quantile(full_arr, 0.95):.4f} |",
        f"| positional agreement, position 0 excluded, mean / p95 | {without_arr.mean():.4f} / {np.quantile(without_arr, 0.95):.4f} |",
        f"| pairs whose only agreement is position 0 | {only_first} ({100 * only_first / len(full):.1f}%) |",
        f"| most common tokens at position 1 | {', '.join(f'{tok} ({n})' for tok, n in openers.most_common(3))} |",
        "",
        "Factual statement for the report: the agreement is concentrated at position 0, a shared BOS "
        f"token ({100 * only_first / len(full):.0f}% of pairs agree only there), and at the question "
        f"opener, in sequences of {min(lengths)}–{max(lengths)} tokens; the detector's threshold was "
        "validated on 512-token sequences. This describes the detector's length sensitivity; it is not a "
        "statement about whether that study's workload is contaminated.",
        "",
    ]
    (RESULTS / "C_exploratory_positional.md").write_text("\n".join(md), encoding="utf-8")
    print(RESULTS / "C_exploratory_positional.md")


if __name__ == "__main__":
    main()
