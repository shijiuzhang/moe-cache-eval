"""Conformance probes for the third-party simulator (PREREG P1).

The probes are written in the simulator's own input format.  Each starts with a
sentinel row because the simulator processes row 0 in both its warm-up and its
measured loop even when ``warmup_count=0`` (RECON Q6).  The sentinel
contributions below were derived by hand from that code path and frozen in
PREREG P1 before any probe was run.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from .adapter import to_moebeyond_format
except ImportError:  # executed as a script
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from adapter import to_moebeyond_format  # type: ignore[no-redef]

SENTINEL_EXPERT = 63
EMPTY: tuple[int, ...] = ()

# Reference trace of the paper's §2.5: three layers, five steps, same local sets.
REFERENCE_SETS = ((0, 1), (0, 2), (0, 1), (0, 3), (0, 1))

PROBES = {
    "A0": {
        "capacity_blocks": 3,
        "rows": [(1, (SENTINEL_EXPERT,), EMPTY), (1, (0, 1, 2), EMPTY), (1, (0, 1, 2), EMPTY)],
        "sentinel_contribution": {"hits": 1, "misses": 0},
        "expected_probe": {"any_contract": {"hits": 3, "misses": 3}},
        "probe_blocks": [[1, 0], [1, 1], [1, 2]],
        "sentinel_blocks": [[1, SENTINEL_EXPERT]],
    },
    "A2": {
        "capacity_blocks": 2,
        "rows": [(1, (SENTINEL_EXPERT,), EMPTY), (1, (0, 1, 2), EMPTY), (1, (0, 1, 2), EMPTY)],
        "sentinel_contribution": {"hits": 1, "misses": 0},
        "expected_probe": {
            "event_level_retention": {"hits": 2, "misses": 4},
            "per_access_retention": {"hits": 0, "misses": 6},
        },
        "probe_blocks": [[1, 0], [1, 1], [1, 2]],
        "sentinel_blocks": [[1, SENTINEL_EXPERT]],
    },
    "A1": {
        "capacity_blocks": 6,
        "rows": (
            [(layer, (SENTINEL_EXPERT,), EMPTY) for layer in (1, 2, 3)]
            + [
                (layer, local, EMPTY)
                for layer in (1, 2, 3)
                for local in REFERENCE_SETS
            ]
        ),
        "sentinel_contribution": {"hits": 1, "misses": 2},
        "expected_probe": {"event_atomic_reference": {"hits": 12, "misses": 18}},
        "probe_blocks": [[layer, e] for layer in (1, 2, 3) for e in (0, 1, 2, 3)],
        "sentinel_blocks": [[layer, SENTINEL_EXPERT] for layer in (1, 2, 3)],
    },
}


def write_probes(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    expected: dict[str, dict] = {}
    for name, spec in PROBES.items():
        path = to_moebeyond_format(spec["rows"], output / f"{name}.csv")
        expected[name] = {
            "file": path.name,
            "capacity_blocks": spec["capacity_blocks"],
            "cache_scope": "global (third-party simulator)",
            "warmup_count": 0,
            "predicted_expert_ids": "empty for every row (prefetch disabled)",
            "sentinel_contribution": spec["sentinel_contribution"],
            "expected_probe_counts": spec["expected_probe"],
            "probe_blocks": spec["probe_blocks"],
            "sentinel_blocks": spec["sentinel_blocks"],
            "source": "PREREG P1",
        }
    (output / "EXPECTED.json").write_text(
        json.dumps(expected, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return expected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    write_probes(args.output)
    print(args.output)


if __name__ == "__main__":
    main()
