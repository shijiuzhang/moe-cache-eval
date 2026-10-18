"""R6 regression check for the MoE-Beyond case study (PREREG §7, RECON §3.1).

(a) §2.5 reference trace: 12 hits / 18 misses under the package simulator.
(b) Regenerate two frozen main-paper conditions: event tensors content-equal,
    requests byte-equal, schedule byte-equal after dropping the later-added
    all-zero arrival_offsets.
(c) Re-read a frozen trace through the canonical EventTrace format and re-save it:
    the event tensors are content-equal.

"Content-equal" for a safetensors file means the parsed header (tensor names,
dtypes, shapes, data offsets and the metadata dictionary) is equal and every
byte of the tensor payload is equal (DEVIATIONS D-003).  The raw file hash is
not used because safetensors writes its two metadata keys in a per-process
random order, so identical content yields one of two file hashes.
(d) The package test suite and the case-study tests pass.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

CASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = CASE_DIR.parents[1]
LAB_ROOT = Path("/Users/zhangyu/Documents/moe-hierarchy-lab")
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from build_paper_blocking_evidence import _toy_trace  # noqa: E402
from moe_controller.convert import convert_decode_trace  # noqa: E402
from moe_controller.events import load_event_trace, save_event_trace, sha256_file  # noqa: E402
from moe_controller.simulation import simulate_event_atomic  # noqa: E402
sys.path.insert(0, str(CASE_DIR))
from content_digest import content_equal, safetensors_content  # noqa: E402

FROZEN_SOURCE = "artifacts/controller-probe-v0.1.3-olmoe-decode64-discovery-v1"
FROZEN_CONDITIONS = {
    1: "cache-events-controller-probe-v0.1.3-olmoe-decode64-fcfs-b1-v1",
    8: "cache-events-controller-probe-v0.1.3-olmoe-decode64-fcfs-b8-v1",
}


def check_a() -> dict:
    trace = _toy_trace()
    trace.validate()
    result = simulate_event_atomic(
        trace, policy="lru", capacity_blocks=6, cache_scope="per_layer", tie_seed=7
    )
    return {"hits": result.hits, "misses": result.misses, "pass": (result.hits, result.misses) == (12, 18)}


def _schedule_without_arrival_offsets(path: Path) -> tuple[bytes, bool]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    all_zero = True
    for row in rows:
        offsets = row.pop("arrival_offsets", [])
        all_zero &= all(int(value) == 0 for value in offsets)
    body = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    return body.encode("utf-8"), all_zero


def check_b(workdir: Path) -> dict:
    report: dict = {}
    for batch, name in FROZEN_CONDITIONS.items():
        frozen_root = LAB_ROOT / name
        manifest = json.loads((frozen_root / "manifest.json").read_text(encoding="utf-8"))
        out = workdir / f"b{batch}"
        convert_decode_trace(
            LAB_ROOT / FROZEN_SOURCE, out, batch_size=batch,
            queue_order="category_round_robin", category_field="workload_archetype",
        )
        events_ok = content_equal(out / "events.safetensors", frozen_root / "events.safetensors")
        # The frozen file itself still matches its manifest exactly.
        frozen_intact = sha256_file(frozen_root / "events.safetensors") == manifest["artifacts"]["events"]["sha256"]
        requests_ok = sha256_file(out / "requests.jsonl") == manifest["artifacts"]["requests"]["sha256"]
        stripped, all_zero = _schedule_without_arrival_offsets(out / "schedule.jsonl")
        schedule_ok = stripped == (frozen_root / "schedule.jsonl").read_bytes()
        report[name] = {
            "frozen_events_match_manifest": frozen_intact,
            "events_content_equal": events_ok,
            "requests_byte_equal": requests_ok,
            "schedule_byte_equal_after_dropping_arrival_offsets": schedule_ok,
            "arrival_offsets_all_zero": all_zero,
            "pass": frozen_intact and events_ok and requests_ok and schedule_ok and all_zero,
        }
    return report


def check_c(workdir: Path) -> dict:
    frozen_root = LAB_ROOT / FROZEN_CONDITIONS[1]
    trace = load_event_trace(frozen_root)
    out = workdir / "resaved"
    save_event_trace(
        out,
        manifest=dict(trace.manifest),
        request_indices=trace.request_indices,
        scheduler_steps=trace.scheduler_steps,
        forward_cycles=trace.forward_cycles,
        phases=trace.phases,
        layer_ids=trace.layer_ids,
        token_counts=trace.token_counts,
        offsets=trace.offsets,
        expert_ids=trace.expert_ids,
        assignment_counts=trace.assignment_counts,
        gate_mass=trace.gate_mass,
    )
    header_f, payload_f = safetensors_content(frozen_root / "events.safetensors")
    header_r, payload_r = safetensors_content(out / "events.safetensors")
    return {
        "frozen_payload_sha256": payload_f,
        "resaved_payload_sha256": payload_r,
        "headers_equal": header_f == header_r,
        "pass": header_f == header_r and payload_f == payload_r,
    }


def check_d() -> dict:
    report = {}
    for label, start in (("package_tests", "tests"), ("case_study_tests", "case_studies/moe_beyond/tests")):
        completed = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", start],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        tail = (completed.stderr or completed.stdout).strip().splitlines()[-3:]
        report[label] = {"returncode": completed.returncode, "tail": tail, "pass": completed.returncode == 0}
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="optional JSON report path")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        report = {"a": check_a(), "b": check_b(work), "c": check_c(work), "d": check_d()}
    passed = (
        report["a"]["pass"]
        and all(item["pass"] for item in report["b"].values())
        and report["c"]["pass"]
        and all(item["pass"] for item in report["d"].values())
    )
    report["overall_pass"] = passed
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
