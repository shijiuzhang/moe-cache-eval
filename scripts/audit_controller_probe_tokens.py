#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from transformers import AutoTokenizer


MODELS = {
    "granite": "ibm-granite/granite-3.1-3b-a800m-base",
    "olmoe": "allenai/OLMoE-1B-7B-0125",
}


def summarize(values: list[int]) -> dict:
    array = np.asarray(values)
    return {
        "count": len(values),
        "min": int(array.min()),
        "p25": float(np.quantile(array, 0.25)),
        "median": float(np.quantile(array, 0.50)),
        "p75": float(np.quantile(array, 0.75)),
        "p95": float(np.quantile(array, 0.95)),
        "max": int(array.max()),
        "mean": float(array.mean()),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--max-length", type=int, default=512)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}.")
    rows = [
        json.loads(line)
        for line in args.dataset.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    model_results = {}
    for alias, model_id in MODELS.items():
        tokenizer = AutoTokenizer.from_pretrained(
            model_id,
            local_files_only=True,
        )
        overall: list[int] = []
        grouped: dict[str, list[int]] = defaultdict(list)
        truncated: dict[str, int] = defaultdict(int)
        prefix_hashes: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            token_ids = tokenizer.encode(
                row["prompt_text"],
                add_special_tokens=True,
            )
            length = len(token_ids)
            archetype = row["workload_archetype"]
            overall.append(length)
            grouped[archetype].append(length)
            if length > args.max_length:
                truncated[archetype] += 1
            prefix = token_ids[: args.max_length]
            prefix_hashes[archetype].add(
                ",".join(str(value) for value in prefix)
            )
        model_results[alias] = {
            "model_id": model_id,
            "tokenizer_class": tokenizer.__class__.__name__,
            "truncation_side": tokenizer.truncation_side,
            "overall": summarize(overall),
            "by_archetype": {
                archetype: {
                    **summarize(values),
                    "truncated_at_max_length": truncated[archetype],
                    "truncated_fraction": (
                        truncated[archetype] / len(values)
                    ),
                    "unique_stored_prefixes": len(
                        prefix_hashes[archetype]
                    ),
                }
                for archetype, values in sorted(grouped.items())
            },
        }
    output = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "dataset": str(args.dataset.resolve()),
        "max_length": args.max_length,
        "models": model_results,
    }
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
