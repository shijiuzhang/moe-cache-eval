"""External harness around the published MoE-Beyond cache simulator.

Run only with the isolated third-party interpreter, for example::

    third_party/.venv-moebeyond/bin/python -I case_studies/moe_beyond/thirdparty_harness.py smoke

The harness loads ``cache_simulator/infinity_moe_sim.py`` from the pinned
checkout by file path and calls its functions.  It never edits that file and is
never imported by the released package.  Its global ``np.random`` state is
seeded immediately before the simulator constructs its randomly pre-filled
cache, which makes otherwise unseeded runs reproducible.

``probe``, ``confirm`` and ``reproduce`` produce stage-3 results and therefore refuse to run
unless the pre-registration lock verifies.  ``smoke`` checks only that the
simulator can be loaded and called, on a hand-checkable input that is not one of
the pre-registered probes.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import platform
import sys
import tempfile
from importlib import metadata
from pathlib import Path

CASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CASE_DIR))

import prereg_guard  # noqa: E402  (standard library only)

SIMULATOR_RELATIVE = "cache_simulator/infinity_moe_sim.py"
TIE_SEEDS = (11, 23, 47, 89, 131)


def load_simulator(third_party_root: Path = prereg_guard.THIRD_PARTY_ROOT):
    path = third_party_root / SIMULATOR_RELATIVE
    spec = importlib.util.spec_from_file_location("moebeyond_infinity_moe_sim", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def environment() -> dict:
    versions = {}
    for package in ("pandas", "numpy", "scipy", "scikit-learn"):
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = None
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": versions,
    }


def predicted_prefill(module, seed: int, cache_size: int) -> set[tuple[int, int]]:
    """Replay the simulator's own pre-fill shuffle for a given seed.

    Mirrors ``ExpertCache.__init__``: build every (layer, expert) pair for
    layers 1..NUM_LAYERS-1, shuffle with the global numpy RNG, keep the first
    ``cache_size``.  The constructor is the first RNG consumer inside the
    replay functions, so seeding immediately before the call yields this set.
    """
    import numpy as np

    np.random.seed(seed)
    blocks = [
        (layer, expert)
        for layer in range(1, module.NUM_LAYERS)
        for expert in range(module.NUM_EXPERTS)
    ]
    np.random.shuffle(blocks)
    return set(blocks[:cache_size])


def call_with_predicted(module, csv_path: Path, cache_size: int, seed: int, warmup_count: int) -> dict:
    import numpy as np

    np.random.seed(seed)
    hits, misses, prediction_hits, prediction_misses = (
        module.test_single_csv_predict_mode_with_predicted(
            str(csv_path), cache_size, warmup_count=warmup_count, top_k=6
        )
    )
    return {
        "hits": int(hits),
        "misses": int(misses),
        "prediction_hits": int(prediction_hits),
        "prediction_misses": int(prediction_misses),
    }


def run_probe(module, csv_path: Path, spec: dict) -> list[dict]:
    """Run one pre-registered probe under every tie seed (PREREG P1)."""
    cache_size = int(spec["capacity_blocks"])
    watched = {tuple(block) for block in spec["probe_blocks"] + spec["sentinel_blocks"]}
    rows = []
    for seed in TIE_SEEDS:
        prefill = predicted_prefill(module, seed, cache_size)
        overlap = sorted(watched & prefill)
        raw = call_with_predicted(module, csv_path, cache_size, seed, warmup_count=0)
        sentinel = spec["sentinel_contribution"]
        rows.append(
            {
                "seed": seed,
                "raw": raw,
                "prefill_overlaps_probe_or_sentinel": [list(b) for b in overlap],
                "eligible_for_classification": not overlap,
                "probe_hits": raw["hits"] - sentinel["hits"],
                "probe_misses": raw["misses"] - sentinel["misses"],
            }
        )
    return rows


def confirm_contract_fields(module, probes_dir: Path, workdir: Path) -> dict:
    """Execution checks of the three contract fields (PREREG P2); not decision probes.

    * Each replay call builds its own cache: the same input and seed, called
      twice in a row, gives identical counts.
    * The hit denominator is per expert access: on probe A0 the measured
      accesses are the sentinel (1) plus 2 x 3 probe experts.
    * Prefetch loads are not counted but do change residency: the same A0 rows
      with the probe experts also listed as predictions keep the same
      denominator while the probe accesses become hits.
    """
    expected = json.loads((probes_dir / "EXPECTED.json").read_text(encoding="utf-8"))
    a0 = expected["A0"]
    seed = TIE_SEEDS[0]
    first = call_with_predicted(module, probes_dir / a0["file"], a0["capacity_blocks"], seed, 0)
    second = call_with_predicted(module, probes_dir / a0["file"], a0["capacity_blocks"], seed, 0)

    prefetch_path = workdir / "A0_with_predictions.csv"
    with (probes_dir / a0["file"]).open(encoding="utf-8", newline="") as source, prefetch_path.open(
        "w", encoding="utf-8", newline=""
    ) as target:
        reader = csv.reader(source)
        writer = csv.writer(target)
        writer.writerow(next(reader))
        for index, row in enumerate(reader):
            if index > 0:  # keep the sentinel row prediction-free
                row[3] = row[2]
            writer.writerow(row)
    with_prefetch = call_with_predicted(module, prefetch_path, a0["capacity_blocks"], seed, 0)
    return {
        "seed": seed,
        "stateless_between_calls": {"first": first, "second": second, "identical": first == second},
        "denominator": {
            "measured_accesses": first["hits"] + first["misses"],
            "sentinel_plus_probe_expert_accesses": 1 + 2 * 3,
        },
        "prefetch": {
            "without_predictions": first,
            "with_predictions": with_prefetch,
            "same_denominator": (first["hits"] + first["misses"])
            == (with_prefetch["hits"] + with_prefetch["misses"]),
            "prefetch_file_sha256": prereg_guard.sha256_path(prefetch_path),
        },
    }


def _aggregate_like_main(per_file: list[tuple[int, int, int, int]]) -> dict:
    """Aggregate exactly as the simulator's ``main()``, including its skips."""
    totals = [0, 0, 0, 0]
    used = skipped_no_access = skipped_no_prediction = 0
    for hits, misses, pred_hits, pred_misses in per_file:
        if hits == 0 and misses == 0:
            skipped_no_access += 1
            continue
        if pred_hits == 0 and pred_misses == 0:
            skipped_no_prediction += 1
            continue
        totals = [a + b for a, b in zip(totals, (hits, misses, pred_hits, pred_misses))]
        used += 1
    hits, misses, pred_hits, pred_misses = totals
    return {
        "files_used": used,
        "files_skipped_no_access": skipped_no_access,
        "files_skipped_no_prediction": skipped_no_prediction,
        "hits": hits,
        "misses": misses,
        "prediction_hits": pred_hits,
        "prediction_misses": pred_misses,
        "cache_hit_rate": hits / (hits + misses) if hits + misses else 0.0,
        "prediction_hit_rate": (
            pred_hits / (pred_hits + pred_misses) if pred_hits + pred_misses else 0.0
        ),
    }


def reproduce(module, path_kind: str, seed: int, cache_size: int, third_party_root: Path) -> dict:
    """One full reproduction run of a published configuration (PREREG P3).

    The global RNG is seeded once before the loop over test files, matching the
    single unseeded RNG stream of the original program (DEVIATIONS D-002).
    """
    import numpy as np

    test_dir = third_party_root / "test_datasets" / "predicted_csvs"
    test_files = [test_dir / f"prompt_{n}_data_predicted.csv" for n in range(1, 101)]
    eamc = None
    if path_kind == "moe_infinity_eamc":
        eamc = module.EAMC(capacity=module.EAMC_CAPACITY)
        for n in range(1, module.EAMC_SIZE):
            eamc.add(
                module.process_csv_to_ream(
                    str(third_party_root / "training_data_eamc" / f"prompt_{n}_data.csv")
                )
            )
        eamc.cluster_reams(n_clusters=module.NUM_CLUSTERS)
    np.random.seed(seed)
    per_file = []
    for test_file in test_files:
        if path_kind == "moe_infinity_eamc":
            per_file.append(
                module.test_single_csv_predict_mode(str(test_file), eamc, cache_size, warmup_count=10)
            )
        elif path_kind == "moe_beyond_predicted":
            per_file.append(
                module.test_single_csv_predict_mode_with_predicted(
                    str(test_file), cache_size, warmup_count=10
                )
            )
        else:
            raise ValueError(path_kind)
    result = _aggregate_like_main([tuple(int(v) for v in row) for row in per_file])
    result.update({"path": path_kind, "seed": seed, "cache_size": cache_size})
    return result


def smoke() -> dict:
    """Load and call the simulator on a hand-checkable input.

    With the cache as large as the whole block universe every block is
    pre-filled, so every access is a hit.  Row 0 is processed by the warm-up
    loop and again by the measured loop, giving two measured hits for two rows.
    """
    module = load_simulator()
    full = (module.NUM_LAYERS - 1) * module.NUM_EXPERTS
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "smoke.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Layer ID", "Token", "Activated Expert IDs", "Predicted Expert IDs"])
            writer.writerow([1, 0, "[5]", "[]"])
            writer.writerow([1, 1, "[6]", "[]"])
        raw = call_with_predicted(module, path, full, seed=0, warmup_count=0)
    return {"cache_size": full, "raw": raw, "expected": {"hits": 2, "misses": 0}, "environment": environment()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("smoke")
    probe_parser = sub.add_parser("probe")
    probe_parser.add_argument("--probes", type=Path, required=True)
    probe_parser.add_argument("--output", type=Path, required=True)
    confirm_parser = sub.add_parser("confirm")
    confirm_parser.add_argument("--probes", type=Path, required=True)
    confirm_parser.add_argument("--output", type=Path, required=True)
    rep_parser = sub.add_parser("reproduce")
    rep_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "smoke":
        print(json.dumps(smoke(), indent=2, sort_keys=True))
        return

    lock = prereg_guard.verify_prereg()
    files = prereg_guard.verify_third_party_files([SIMULATOR_RELATIVE])
    module = load_simulator()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite {args.output}")

    if args.command == "probe":
        expected = json.loads((args.probes / "EXPECTED.json").read_text(encoding="utf-8"))
        probe_files = {name: str(prereg_guard.sha256_path(args.probes / spec["file"])) for name, spec in expected.items()}
        results = {
            name: run_probe(module, args.probes / spec["file"], spec)
            for name, spec in expected.items()
        }
        payload = {"probes": results, "expected": expected, "probe_file_sha256": probe_files}
    elif args.command == "confirm":
        with tempfile.TemporaryDirectory() as tmp:
            payload = {"confirmation": confirm_contract_fields(module, args.probes, Path(tmp))}
        payload["probe_file_sha256"] = {
            "A0.csv": prereg_guard.sha256_path(args.probes / "A0.csv"),
            "EXPECTED.json": prereg_guard.sha256_path(args.probes / "EXPECTED.json"),
        }
    else:
        relative = (
            [f"test_datasets/predicted_csvs/prompt_{n}_data_predicted.csv" for n in range(1, 101)]
            + [f"training_data_eamc/prompt_{n}_data.csv" for n in range(1, 10)]
        )
        files.update(prereg_guard.verify_third_party_files(relative))
        runs = [
            reproduce(module, kind, seed, int(1664 * 0.1), prereg_guard.THIRD_PARTY_ROOT)
            for kind in ("moe_infinity_eamc", "moe_beyond_predicted")
            for seed in TIE_SEEDS
        ]
        payload = {"runs": runs}
    payload["inputs"] = prereg_guard.inputs_record(lock, files)
    payload["environment"] = environment()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
