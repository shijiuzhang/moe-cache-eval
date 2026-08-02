#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_gap(
    path: Path,
    *,
    model_label: str,
    cache_scope: str,
    rho: float,
) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as handle:
        matches = [
            row
            for row in csv.DictReader(handle)
            if row["model_label"] == model_label
            and row["cache_scope"] == cache_scope
            and abs(float(row["rho"]) - rho) < 1e-12
        ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one gap row for {model_label}, observed {len(matches)}."
        )
    return matches[0]


def condition_row(
    label: str,
    event_root: Path,
    gap_csv: Path,
    *,
    cache_scope: str,
    rho: float,
) -> dict:
    manifest_path = event_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    counts = manifest["counts"]
    layers = int(manifest["model"]["num_layers"])
    steps = int(counts["scheduler_steps"])
    logical = int(counts["logical_expert_assignments_before_dedup"])
    union = int(counts["union_expert_accesses"])
    gap = load_gap(
        gap_csv,
        model_label=event_root.name,
        cache_scope=cache_scope,
        rho=rho,
    )
    return {
        "condition": label,
        "event_root": str(event_root.resolve()),
        "requests": int(counts["requests"]),
        "batch_size": int(manifest["conversion"]["batch_size"]),
        "mean_active_requests": int(counts["decode_forwards"]) / steps,
        "mean_union_per_layer_step": union / (steps * layers),
        "union_fraction_of_logical": union / logical,
        "cache_scope": cache_scope,
        "rho": rho,
        "best_causal": gap["best_causal"],
        "best_causal_miss_fraction": float(
            gap["best_causal_effective_miss_fraction"]
        ),
        "belady_miss_fraction": float(
            gap["belady_effective_miss_fraction"]
        ),
        "recoverable_gap": float(gap["recoverable_gap"]),
        "event_manifest_sha256": sha256_file(manifest_path),
        "gap_csv_sha256": sha256_file(gap_csv),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare workload-conditioned decode cache behavior."
    )
    parser.add_argument(
        "--condition",
        action="append",
        nargs=3,
        metavar=("LABEL", "EVENT_ROOT", "GAP_CSV"),
        required=True,
    )
    parser.add_argument("--cache-scope", default="per_layer")
    parser.add_argument("--rho", type=float, default=0.4)
    parser.add_argument("--reference", default="mixed_balanced")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Output exists: {args.output}.")

    rows = [
        condition_row(
            label,
            Path(event_root),
            Path(gap_csv),
            cache_scope=args.cache_scope,
            rho=args.rho,
        )
        for label, event_root, gap_csv in args.condition
    ]
    reference = next(
        (row for row in rows if row["condition"] == args.reference),
        None,
    )
    if reference is None:
        raise ValueError(f"Missing reference condition {args.reference!r}.")
    for row in rows:
        row["union_reduction_vs_reference"] = 1.0 - (
            row["mean_union_per_layer_step"]
            / reference["mean_union_per_layer_step"]
        )
        row["causal_miss_reduction_vs_reference"] = 1.0 - (
            row["best_causal_miss_fraction"]
            / reference["best_causal_miss_fraction"]
        )
        row["belady_miss_reduction_vs_reference"] = 1.0 - (
            row["belady_miss_fraction"]
            / reference["belady_miss_fraction"]
        )

    args.output.mkdir(parents=True)
    csv_path = args.output / "workload-comparison.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
        "kind": "workload_conditioning_comparison",
        "cache_scope": args.cache_scope,
        "rho": args.rho,
        "reference": args.reference,
        "conditions": len(rows),
        "artifact": {
            "path": csv_path.name,
            "bytes": csv_path.stat().st_size,
            "sha256": sha256_file(csv_path),
        },
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    print(args.output)


if __name__ == "__main__":
    main()
