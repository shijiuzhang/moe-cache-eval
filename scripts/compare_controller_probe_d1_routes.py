#!/usr/bin/env python3
"""Compare matched ControllerProbe-D1 diverse and single-template routes."""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import random
from collections import defaultdict
from pathlib import Path

import numpy as np

from audit_probe_diversity import load_routes


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_probe(path: Path) -> dict[str, dict]:
    return {
        row["id"]: row
        for row in (
            json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
        )
        if row.get("split") == "confirmatory"
    }


def make_member(topk: np.ndarray, lengths: np.ndarray, n_experts: int) -> np.ndarray:
    n_samples, n_layers, n_steps, _ = topk.shape
    member = np.zeros((n_samples, n_layers, n_steps, n_experts), dtype=bool)
    active = np.arange(n_steps)[None, :] < lengths[:, None]
    for rank in range(topk.shape[-1]):
        expert = topk[..., rank]
        valid = (expert >= 0) & active[:, None, :]
        sample_i, layer_i, step_i = np.nonzero(valid)
        member[sample_i, layer_i, step_i, expert[valid]] = True
    return member


def union_mean(
    member: np.ndarray,
    lengths: np.ndarray,
    batches: list[list[int]],
    lo: int,
    hi: int,
) -> float:
    values: list[float] = []
    for batch in batches:
        indices = np.asarray(batch, dtype=int)
        upper = min(hi, member.shape[2])
        for step in range(lo, upper):
            active = indices[lengths[indices] > step]
            if active.size:
                values.append(float(member[active, :, step, :].any(0).sum(-1).mean()))
    return float(np.mean(values)) if values else float("nan")


def pair_summary(
    indices: list[int],
    emitted: np.ndarray,
    lengths: np.ndarray,
    member: np.ndarray,
) -> dict[str, float | int]:
    agreements: list[float] = []
    jaccards: list[float] = []
    low_token: list[float] = []
    for left, right in itertools.combinations(indices, 2):
        steps = min(int(lengths[left]), int(lengths[right]))
        agreement = float(
            (emitted[left, :steps] == emitted[right, :steps]).mean()
        )
        inter = (member[left, :, :steps] & member[right, :, :steps]).sum(-1)
        union = (member[left, :, :steps] | member[right, :, :steps]).sum(-1)
        expert_jaccard = float((inter / union).mean())
        agreements.append(agreement)
        jaccards.append(expert_jaccard)
        if agreement < 0.05:
            low_token.append(expert_jaccard)
    unique = len(
        {tuple(emitted[index, : lengths[index]].tolist()) for index in indices}
    )
    return {
        "token_agreement": float(np.mean(agreements)),
        "unique_sequences": unique,
        "pair_count": len(agreements),
        "expert_jaccard": float(np.mean(jaccards)),
        "low_token_expert_jaccard": (
            float(np.mean(low_token)) if low_token else float("nan")
        ),
        "low_token_pair_count": len(low_token),
    }


def deterministic_batches(
    groups: dict[str, list[int]],
    *,
    batch_size: int,
    trials: int,
    seed: int,
) -> tuple[dict[str, list[list[int]]], list[list[int]]]:
    pure: dict[str, list[list[int]]] = defaultdict(list)
    mixed: list[list[int]] = []
    categories = sorted(groups)
    rng = random.Random(seed)
    for trial in range(trials):
        for category in categories:
            pure[category].append(rng.sample(groups[category], batch_size))
        category_order = [
            categories[(trial + slot) % len(categories)]
            for slot in range(batch_size)
        ]
        counts: dict[str, int] = defaultdict(int)
        for category in category_order:
            counts[category] += 1
        selected_by_category = {
            category: iter(rng.sample(groups[category], count))
            for category, count in counts.items()
        }
        mixed.append(
            [next(selected_by_category[category]) for category in category_order]
        )
    return pure, mixed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diverse-routes", type=Path, required=True)
    parser.add_argument("--control-routes", type=Path, required=True)
    parser.add_argument("--diverse-probe", type=Path, required=True)
    parser.add_argument("--control-probe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--trials", type=int, default=100)
    parser.add_argument(
        "--bands", default="0-16,16-64,64-160,160-384"
    )
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Output exists: {args.output}")

    diverse_probe = read_probe(args.diverse_probe)
    control_probe = read_probe(args.control_probe)
    paired_diverse_ids = {row["pair_id"] for row in control_probe.values()}
    if None in paired_diverse_ids or len(paired_diverse_ids) != len(control_probe):
        raise ValueError("Control pair_id values must be complete and unique.")

    arms = {}
    for label, routes, probe, allowed in (
        ("diverse", args.diverse_routes, diverse_probe, paired_diverse_ids),
        ("single_template", args.control_routes, control_probe, set(control_probe)),
    ):
        ids, lengths, emitted, topk, n_experts = load_routes(routes)
        index = {sample_id: position for position, sample_id in enumerate(ids)}
        missing = allowed - set(index)
        if missing:
            raise ValueError(f"{label} trace lacks {len(missing)} matched IDs.")
        groups: dict[str, list[int]] = defaultdict(list)
        for sample_id in sorted(allowed):
            groups[probe[sample_id]["workload_archetype"]].append(index[sample_id])
        if any(len(group) != 12 for group in groups.values()):
            raise ValueError(f"{label} does not have 12 matched rows per category.")
        arms[label] = {
            "ids": ids,
            "index": index,
            "lengths": lengths,
            "emitted": emitted,
            "member": make_member(topk, lengths, n_experts),
            "groups": groups,
            "probe": probe,
        }

    bands = [tuple(map(int, chunk.split("-"))) for chunk in args.bands.split(",")]
    rows: list[dict] = []
    for arm_number, (label, arm) in enumerate(arms.items()):
        pure_batches, mixed_batches = deterministic_batches(
            arm["groups"],
            batch_size=args.batch_size,
            trials=args.trials,
            seed=20260801 + arm_number,
        )
        summaries = {
            category: pair_summary(
                indices, arm["emitted"], arm["lengths"], arm["member"]
            )
            for category, indices in arm["groups"].items()
        }
        for lo, hi in bands:
            reference = union_mean(
                arm["member"], arm["lengths"], mixed_batches, lo, hi
            )
            for category, indices in sorted(arm["groups"].items()):
                pure = union_mean(
                    arm["member"], arm["lengths"], pure_batches[category], lo, hi
                )
                summary = summaries[category]
                rows.append(
                    {
                        "arm": label,
                        "category": category,
                        "band_start": lo,
                        "band_end": hi,
                        "matched_requests": len(indices),
                        "survival_at_band_start": float(
                            np.mean(arm["lengths"][indices] > lo)
                        ),
                        "survival_at_band_end": float(
                            np.mean(arm["lengths"][indices] >= hi)
                        ),
                        "pure_union": pure,
                        "mixed_union": reference,
                        "union_reduction_vs_mixed": 1.0 - pure / reference,
                        **summary,
                    }
                )

    by_key = {
        (row["arm"], row["category"], row["band_start"], row["band_end"]): row
        for row in rows
    }
    for row in rows:
        if row["arm"] != "diverse":
            continue
        control = by_key[
            ("single_template", row["category"], row["band_start"], row["band_end"])
        ]
        row["template_echo_union_reduction_delta"] = (
            control["union_reduction_vs_mixed"] - row["union_reduction_vs_mixed"]
        )
    for row in rows:
        row.setdefault("template_echo_union_reduction_delta", "")

    args.output.mkdir(parents=True)
    diverse_ids_path = args.output / "matched-diverse-ids.txt"
    heldout_diverse_ids = set(diverse_probe) - paired_diverse_ids
    if len(heldout_diverse_ids) != len(paired_diverse_ids):
        raise ValueError("Expected an equal-sized held-out diverse half.")
    heldout_ids_path = args.output / "heldout-diverse-ids.txt"
    control_ids_path = args.output / "matched-control-ids.txt"
    diverse_ids_path.write_text(
        "".join(f"{sample_id}\n" for sample_id in sorted(paired_diverse_ids)),
        encoding="utf-8",
    )
    control_ids_path.write_text(
        "".join(f"{sample_id}\n" for sample_id in sorted(control_probe)),
        encoding="utf-8",
    )
    heldout_ids_path.write_text(
        "".join(f"{sample_id}\n" for sample_id in sorted(heldout_diverse_ids)),
        encoding="utf-8",
    )
    diverse_arrivals = {
        sample_id: int(
            diverse_probe[sample_id]["collection"]["arrival_offset_steps"]
        )
        for sample_id in paired_diverse_ids
    }
    control_arrivals = {
        control_id: diverse_arrivals[row["pair_id"]]
        for control_id, row in control_probe.items()
    }
    heldout_arrivals = {
        sample_id: int(
            diverse_probe[sample_id]["collection"]["arrival_offset_steps"]
        )
        for sample_id in heldout_diverse_ids
    }
    diverse_arrivals_path = args.output / "matched-diverse-arrivals.json"
    control_arrivals_path = args.output / "matched-control-arrivals.json"
    heldout_arrivals_path = args.output / "heldout-diverse-arrivals.json"
    diverse_arrivals_path.write_text(
        json.dumps(diverse_arrivals, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    control_arrivals_path.write_text(
        json.dumps(control_arrivals, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    heldout_arrivals_path.write_text(
        json.dumps(heldout_arrivals, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    csv_path = args.output / "matched-route-comparison.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "status": "complete",
        "kind": "controller_probe_d1_matched_route_comparison",
        "matched_pairs": len(control_probe),
        "batch_size": args.batch_size,
        "trials": args.trials,
        "bands": bands,
        "inputs": {
            "diverse_routes": str(args.diverse_routes.resolve()),
            "control_routes": str(args.control_routes.resolve()),
            "diverse_probe_sha256": sha256_file(args.diverse_probe),
            "control_probe_sha256": sha256_file(args.control_probe),
        },
        "artifact": {
            "path": csv_path.name,
            "sha256": sha256_file(csv_path),
            "rows": len(rows),
        },
        "matched_schedule_inputs": {
            path.name: sha256_file(path)
            for path in (
                diverse_ids_path,
                heldout_ids_path,
                control_ids_path,
                diverse_arrivals_path,
                heldout_arrivals_path,
                control_arrivals_path,
            )
        },
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(csv_path)


if __name__ == "__main__":
    main()
