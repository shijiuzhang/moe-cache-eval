#!/usr/bin/env python3
"""Audit a decode probe set for template-echo contamination.

Two modes, either or both:

``--probe PATH``
    Prompt-side audit.  Reports, per (archetype, split, variant) cell, how many
    distinct prompt heads and final lines exist and the pairwise 5-gram Jaccard
    of the prompts.  A cell with one distinct head and one distinct final line
    is a single-template cell: any per-step expert union measured on it is
    partly reporting template alignment.

``--routes DIR``
    Route-side audit on a collected decode artifact.  Reports, per archetype:

    * positional agreement of the emitted token sequences;
    * how many of the sequences are exact duplicates;
    * mean pairwise expert Jaccard within the archetype, against the
      cross-archetype baseline;
    * the same Jaccard restricted to request pairs whose generated text barely
      overlaps -- this is the part of the effect that is *not* explained by
      near-duplicate generation;
    * the per-step expert union by decode-position band, pure archetype versus
      a category-round-robin mixture.

    A workload-conditioning effect that is real should be roughly flat across
    the position bands.  One that decays toward the mixture baseline as the
    decode position grows is template echo.

Both modes are read-only.
"""
from __future__ import annotations

import argparse
import collections
import glob
import itertools
import json
import random
from pathlib import Path
from typing import Sequence


# ---------------------------------------------------------------------------
# prompt-side
# ---------------------------------------------------------------------------


def ngrams(text: str, n: int = 5) -> set[str]:
    tokens = text.split()
    if len(tokens) < n:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def audit_probe(path: Path, text_field: str, group_fields: Sequence[str]) -> None:
    rows = [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]
    cells: dict[tuple, list[dict]] = collections.defaultdict(list)
    for row in rows:
        key = tuple(str(row.get(field, "-")) for field in group_fields)
        cells[key].append(row)

    print(f"\n=== prompt-side audit: {path} ({len(rows)} records) ===")
    header = (
        f"{'cell':56s} {'n':>3} {'heads':>5} {'tails':>5} "
        f"{'jacc.mean':>9} {'jacc.p95':>8} {'chars.med':>9}"
    )
    print(header)
    print("-" * len(header))
    flagged: list[str] = []
    for key, group in sorted(cells.items()):
        label = "/".join(key)
        heads = {row[text_field][:70] for row in group}
        tails = {row[text_field].rsplit("\n", 1)[-1][:120] for row in group}
        grams = [ngrams(row[text_field]) for row in group]
        sims = sorted(
            jaccard(grams[i], grams[j])
            for i, j in itertools.combinations(range(len(grams)), 2)
        )
        lengths = sorted(len(row[text_field]) for row in group)
        mean = sum(sims) / len(sims) if sims else 0.0
        p95 = sims[int(0.95 * (len(sims) - 1))] if sims else 0.0
        print(
            f"{label:56s} {len(group):3d} {len(heads):5d} {len(tails):5d} "
            f"{mean:9.4f} {p95:8.4f} {lengths[len(lengths) // 2]:9d}"
        )
        if len(group) < 4:
            continue
        reasons = []
        if len(heads) <= 2:
            reasons.append(f"{len(heads)} distinct heads")
        if len(tails) <= 2:
            reasons.append(f"{len(tails)} distinct final lines")
        if p95 >= 0.30:
            reasons.append(f"5-gram jaccard p95 {p95:.2f}")
        if reasons:
            flagged.append(f"{label}  ({'; '.join(reasons)})")

    if flagged:
        print(
            "\nCONTAMINATED CELLS -- per-step union measured on these is partly "
            "reporting\nprompt redundancy rather than workload structure:"
        )
        for label in flagged:
            print(f"  - {label}")
    else:
        print("\nNo contaminated cell detected.")


# ---------------------------------------------------------------------------
# route-side
# ---------------------------------------------------------------------------


def load_routes(routes_dir: Path):
    import numpy as np
    from safetensors import safe_open

    manifest = json.loads((routes_dir / "manifest.json").read_text())
    n_experts = int(manifest["model"]["num_experts"])
    ids: list[str] = []
    for meta_path in sorted(routes_dir.glob("samples-*.jsonl")):
        for line in meta_path.open(encoding="utf-8"):
            ids.append(json.loads(line)["id"])

    emitted_parts, topk_parts, length_parts = [], [], []
    for shard in sorted(routes_dir.glob("routes-*.safetensors")):
        with safe_open(str(shard), "numpy") as handle:
            emitted_parts.append(handle.get_tensor("emitted_ids"))
            topk_parts.append(handle.get_tensor("topk_indices"))
            length_parts.append(handle.get_tensor("sequence_lengths"))
    lengths = np.concatenate(length_parts).astype("int32")
    max_steps = int(lengths.max())
    n_samples = int(lengths.size)
    n_layers = int(topk_parts[0].shape[1])
    top_k = int(topk_parts[0].shape[3])
    emitted = np.full((n_samples, max_steps), -1, dtype="int32")
    topk = np.full(
        (n_samples, n_layers, max_steps, top_k), -1, dtype="int32"
    )
    offset = 0
    for emitted_part, topk_part in zip(emitted_parts, topk_parts):
        count, part_steps = emitted_part.shape
        emitted[offset : offset + count, :part_steps] = emitted_part
        topk[offset : offset + count, :, :part_steps, :] = topk_part
        offset += count
    return ids, lengths, emitted, topk, n_experts


def audit_routes(
    routes_dir: Path,
    probe_path: Path,
    category_field: str,
    per_cat: int,
    bands: Sequence[tuple[int, int]],
) -> None:
    import numpy as np

    category = {}
    for line in probe_path.open(encoding="utf-8"):
        row = json.loads(line)
        category[row["id"]] = row.get(category_field, "-")

    ids, lengths, emitted, topk, n_experts = load_routes(routes_dir)
    n_samples, n_layers, n_steps, _ = topk.shape
    member = np.zeros((n_samples, n_layers, n_steps, n_experts), dtype=bool)
    active_tokens = np.arange(n_steps)[None, :] < lengths[:, None]
    for rank in range(topk.shape[-1]):
        expert = topk[..., rank]
        valid = (expert >= 0) & active_tokens[:, None, :]
        sample_i, layer_i, step_i = np.nonzero(valid)
        member[sample_i, layer_i, step_i, expert[valid]] = True

    groups: dict[str, list[int]] = collections.defaultdict(list)
    for index, rid in enumerate(ids):
        groups[category.get(rid, "-")].append(index)
    keys = sorted(groups)
    picked = {k: sorted(groups[k])[:per_cat] for k in keys}

    print(
        f"\n=== route-side audit: {routes_dir} "
        f"({n_samples} samples, {n_layers} layers, {n_steps} steps, "
        f"{n_experts} experts) ==="
    )

    def pair_jaccard(a: int, b: int) -> float:
        steps = min(int(lengths[a]), int(lengths[b]))
        inter = (member[a, :, :steps] & member[b, :, :steps]).sum(-1)
        union = (member[a, :, :steps] | member[b, :, :steps]).sum(-1)
        return float((inter / union).mean())

    # ---- text duplication and expert overlap ------------------------------
    print(
        f"\n{'archetype':30s} {'tokAgr':>7} {'uniqSeq':>8} {'expJac':>7} "
        f"{'expJac|lowTok':>14} {'nLowTok':>8}"
    )
    for key in keys:
        idx = picked[key]
        if len(idx) < 2:
            continue
        agreements, jaccards, low = [], [], []
        for a, b in itertools.combinations(idx, 2):
            steps = min(int(lengths[a]), int(lengths[b]))
            agree = float((emitted[a, :steps] == emitted[b, :steps]).mean())
            score = pair_jaccard(a, b)
            agreements.append(agree)
            jaccards.append(score)
            if agree < 0.05:
                low.append(score)
        unique = len(
            {tuple(emitted[i, : lengths[i]].tolist()) for i in idx}
        )
        low_mean = f"{np.mean(low):14.3f}" if low else f"{'n/a':>14}"
        print(
            f"{key:30s} {np.mean(agreements):7.2%} {unique:4d}/{len(idx):<3d} "
            f"{np.mean(jaccards):7.3f} {low_mean} {len(low):4d}/{len(jaccards):<3d}"
        )

    rng = random.Random(7)
    flat = [(k, i) for k in keys for i in picked[k]]
    cross = []
    for _ in range(400):
        (k1, a), (k2, b) = rng.sample(flat, 2)
        if k1 != k2:
            cross.append(pair_jaccard(a, b))
    print(f"{'CROSS-ARCHETYPE BASELINE':30s} {'':7s} {'':8s} {np.mean(cross):7.3f}")
    print(
        "\n  expJac|lowTok is the within-archetype expert overlap after removing"
        "\n  request pairs whose generated text overlaps. If it collapses toward"
        "\n  the cross-archetype baseline, the effect was text duplication."
    )

    # ---- union by decode-position band ------------------------------------
    def union_mean(indices: Sequence[int], lo: int, hi: int) -> float:
        hi = min(hi, n_steps)
        if lo >= hi:
            return float("nan")
        index_array = np.asarray(indices, dtype=int)
        union = member[index_array, :, lo:hi, :].any(0).sum(-1)
        active = np.asarray(
            [np.any(lengths[index_array] > step) for step in range(lo, hi)]
        )
        if not active.any():
            return float("nan")
        return float(union[:, active].mean())

    batch = min(per_cat, 16)
    mixtures = []
    for _ in range(30):
        mixtures.append([rng.choice(picked[keys[j % len(keys)]]) for j in range(batch)])

    print(
        f"\nper-step expert union at B={batch}, pure archetype vs "
        f"category-round-robin mixture"
    )
    band_names = " ".join(f"{'t%d-%d' % b:>16s}" for b in bands)
    print(f"{'archetype':30s} {band_names}")
    reference = [float(np.mean([union_mean(m, lo, hi) for m in mixtures])) for lo, hi in bands]
    print(
        f"{'MIXTURE (reference)':30s} "
        + " ".join(f"{value:16.1f}" for value in reference)
    )
    for key in keys:
        pool = picked[key]
        if len(pool) < batch:
            continue
        subsets = [rng.sample(pool, batch) for _ in range(30)]
        cells = []
        for (lo, hi), ref in zip(bands, reference):
            value = float(np.mean([union_mean(s, lo, hi) for s in subsets]))
            cells.append(f"{value:8.1f}({1 - value / ref:5.1%})")
        print(f"{key:30s} " + " ".join(cells))
    print(
        "\n  A durable workload effect holds its reduction across bands."
        "\n  A reduction that shrinks toward the later bands is template echo."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path, help="probe .jsonl to audit")
    parser.add_argument("--text-field", default="prompt_text")
    parser.add_argument(
        "--group-by",
        default="workload_archetype,split,render_variant",
        help="comma-separated record fields defining an audit cell",
    )
    parser.add_argument("--routes", type=Path, help="collected route artifact dir")
    parser.add_argument(
        "--routes-probe",
        type=Path,
        help="probe .jsonl mapping record id -> archetype (defaults to --probe)",
    )
    parser.add_argument("--category-field", default="workload_archetype")
    parser.add_argument("--per-category", type=int, default=16)
    parser.add_argument(
        "--bands",
        default="0-8,8-16,16-32,32-64",
        help="decode-position bands, e.g. 0-8,8-32,32-128,128-256",
    )
    args = parser.parse_args()

    if not args.probe and not args.routes:
        parser.error("pass --probe and/or --routes")

    if args.probe:
        audit_probe(
            args.probe, args.text_field, [f.strip() for f in args.group_by.split(",")]
        )

    if args.routes:
        probe_path = args.routes_probe or args.probe
        if probe_path is None:
            parser.error("--routes needs --probe or --routes-probe")
        bands = []
        for chunk in args.bands.split(","):
            lo, hi = chunk.split("-")
            bands.append((int(lo), int(hi)))
        audit_routes(
            args.routes, probe_path, args.category_field, args.per_category, bands
        )


if __name__ == "__main__":
    main()
