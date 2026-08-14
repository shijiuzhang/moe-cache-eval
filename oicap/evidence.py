from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import __version__
from .contracts import ContractSet, canonical_json, file_sha256
from .metrics import summarize
from .observations import RequestObservation
from .runner import RunResult


EVIDENCE_SCHEMA_VERSION = "0.1"


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _write_observations(path: Path, rows: Iterable[RequestObservation]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row.to_dict()) + "\n")


def load_observations(path: Path) -> list[RequestObservation]:
    with path.open("r", encoding="utf-8") as handle:
        return [RequestObservation.from_dict(json.loads(line)) for line in handle if line.strip()]


def environment_fingerprint(repo_root: Path | None = None) -> dict[str, Any]:
    from importlib.metadata import PackageNotFoundError, version

    packages: dict[str, str | None] = {}
    for distribution in ("psutil", "PyYAML"):
        try:
            packages[distribution] = version(distribution)
        except PackageNotFoundError:
            packages[distribution] = None
    return {
        "python": sys.version,
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "monotonic_clock": time_clock_info(),
        "client": {
            "transport": "python_urllib",
            "connection_pooling": "none",
            "streaming_parser": "oicap-sse-0.1",
        },
        "packages": packages,
        "code": git_fingerprint(repo_root or Path.cwd()),
    }


def git_fingerprint(root: Path) -> dict[str, Any]:
    def command(*args: str) -> str | None:
        try:
            return subprocess.run(
                ["git", "-C", str(root), *args],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None

    commit = command("rev-parse", "HEAD")
    status = command("status", "--porcelain=v1")
    return {
        "git_commit": commit,
        "git_dirty": bool(status) if status is not None else None,
        "git_status_paths": status.splitlines() if status else [],
    }


def time_clock_info() -> dict[str, Any]:
    import time

    info = time.get_clock_info("perf_counter")
    return {
        "implementation": info.implementation,
        "monotonic": info.monotonic,
        "adjustable": info.adjustable,
        "resolution_s": info.resolution,
    }


def write_bundle(
    output: str | Path,
    contracts: ContractSet,
    result: RunResult,
    endpoint: str,
    calibration_ref: dict[str, Any] | None = None,
    require_calibration: bool = True,
    invocation: list[str] | None = None,
) -> Path:
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    contracts_dir = root / "contracts"
    contracts_dir.mkdir()
    for name, document in contracts.normalized().items():
        _write_json(contracts_dir / f"{name}.json", document)
    schemas_dir = root / "schemas"
    shutil.copytree(Path(__file__).parent / "schemas" / "0.1", schemas_dir)
    inputs_dir = root / "inputs"
    inputs_dir.mkdir()
    workload_snapshot = inputs_dir / "workload.jsonl"
    shutil.copyfile(contracts.workload_path, workload_snapshot)
    observations_path = root / "observations.jsonl"
    _write_observations(observations_path, result.observations)
    summary = summarize(row for row in result.observations if row.phase == "measurement")
    _write_json(root / "summary.json", summary)
    _write_json(
        root / "apparatus.json",
        apparatus_assessment(contracts.scenario, summary, calibration_ref),
    )
    _write_json(
        root / "environment.json",
        environment_fingerprint(Path(__file__).resolve().parents[1]),
    )
    if calibration_ref is not None:
        _write_json(root / "calibration_ref.json", calibration_ref)
    files = sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    )
    manifest = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "tool": {"name": "oicap", "version": __version__},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "profile": "private-full",
        "contract_hashes": contracts.hashes,
        "contract_identity": contracts.identity,
        "measurement_identity": contracts.measurement_identity,
        "workload_sha256": file_sha256(contracts.workload_path),
        "endpoint": _redact_endpoint(endpoint),
        "invocation": invocation or [],
        "run": {"started_ns": result.started_ns, "finished_ns": result.finished_ns},
        "calibration_required": require_calibration,
        "calibration_present": calibration_ref is not None,
        "files": {name: file_sha256(root / name) for name in files},
        "excluded": ["API keys and authorization headers"],
    }
    _write_json(root / "manifest.json", manifest)
    return root


def apparatus_assessment(
    scenario: dict[str, Any],
    summary: dict[str, Any],
    calibration_ref: dict[str, Any] | None,
) -> dict[str, Any]:
    if calibration_ref is None:
        return {
            "schema_version": "0.1",
            "status": "UNCALIBRATED",
            "capacity_claim_permitted": False,
            "reasons": ["missing_calibration"],
        }
    record = calibration_ref.get("record")
    if not isinstance(record, dict) or not isinstance(record.get("limits"), dict):
        return {
            "schema_version": "0.1",
            "status": "UNCALIBRATED",
            "capacity_claim_permitted": False,
            "reasons": ["invalid_calibration_record"],
        }
    limits = record["limits"]
    schedule_p99 = summary["latency_ms"]["schedule_lag"]["p99"]
    requested_rate = None
    achieved_rate = summary["load_realization"]["achieved_submission_rate_per_s"]
    if scenario["arrival"]["kind"] == "open_loop":
        requested_rate = float(scenario["arrival"]["rate_per_s"])
    reasons: list[str] = []
    if schedule_p99 is None or float(schedule_p99) > float(
        limits["max_schedule_lag_p99_ms"]
    ):
        reasons.append("schedule_lag_exceeded")
    arrival_ratio = None
    if requested_rate is not None:
        arrival_ratio = (
            float(achieved_rate) / requested_rate if achieved_rate is not None else None
        )
        if arrival_ratio is None or arrival_ratio < float(limits["min_arrival_rate_ratio"]):
            reasons.append("arrival_rate_not_realized")
    return {
        "schema_version": "0.1",
        "status": "CLIENT_SATURATED" if reasons else "VALID",
        "capacity_claim_permitted": not reasons,
        "reasons": reasons,
        "schedule_lag_p99_ms": schedule_p99,
        "requested_arrival_rate_per_s": requested_rate,
        "achieved_submission_rate_per_s": achieved_rate,
        "arrival_rate_ratio": arrival_ratio,
        "note": "This is apparatus validity, not an SLO verdict.",
    }


def verify_bundle(root: str | Path) -> dict[str, Any]:
    bundle = Path(root).resolve()
    manifest_path = bundle / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Missing manifest.json.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported evidence schema {manifest.get('schema_version')!r}."
        )
    calibration_ref = bundle / "calibration_ref.json"
    errors: list[str] = []
    manifest_files = manifest.get("files")
    if not isinstance(manifest_files, dict):
        raise ValueError("manifest.files must be a mapping.")
    for name, expected in manifest_files.items():
        if not isinstance(name, str) or not isinstance(expected, str):
            errors.append("invalid_manifest_file_entry")
            continue
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            errors.append(f"unsafe_path:{name}")
            continue
        path = bundle / relative
        if not path.is_file():
            errors.append(f"missing:{name}")
        elif file_sha256(path) != expected:
            errors.append(f"hash_mismatch:{name}")
    listed = set(manifest_files) | {"manifest.json"}
    actual = {
        str(path.relative_to(bundle))
        for path in bundle.rglob("*")
        if path.is_file()
    }
    for name in sorted(actual - listed):
        errors.append(f"unlisted_file:{name}")
    contract_hashes: dict[str, str] = {}
    for name in ("scenario", "slo", "sut", "run"):
        path = bundle / "contracts" / f"{name}.json"
        try:
            contract_hashes[name] = _json_sha256(
                json.loads(path.read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"contract_unreadable:{name}:{type(exc).__name__}")
    if contract_hashes and contract_hashes != manifest.get("contract_hashes"):
        errors.append("contract_hashes_mismatch")
    identity_input = {
        **contract_hashes,
        "workload_sha256": manifest.get("workload_sha256"),
    }
    if contract_hashes and _json_sha256(identity_input) != manifest.get("contract_identity"):
        errors.append("contract_identity_mismatch")
    measurement_input = {
        **{name: digest for name, digest in contract_hashes.items() if name != "slo"},
        "workload_sha256": manifest.get("workload_sha256"),
    }
    if contract_hashes and _json_sha256(measurement_input) != manifest.get(
        "measurement_identity"
    ):
        errors.append("measurement_identity_mismatch")
    workload_snapshot = bundle / "inputs" / "workload.jsonl"
    if not workload_snapshot.is_file():
        errors.append("missing_workload_snapshot")
    elif file_sha256(workload_snapshot) != manifest.get("workload_sha256"):
        errors.append("workload_hash_mismatch")
    try:
        observations = load_observations(bundle / "observations.jsonl")
        recomputed = summarize(row for row in observations if row.phase == "measurement")
        stored = json.loads((bundle / "summary.json").read_text(encoding="utf-8"))
        if canonical_json(recomputed) != canonical_json(stored):
            errors.append("summary_mismatch")
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        recomputed = None
        errors.append(f"observations_unreadable:{type(exc).__name__}")
    try:
        apparatus = json.loads((bundle / "apparatus.json").read_text(encoding="utf-8"))
        scenario = json.loads(
            (bundle / "contracts" / "scenario.json").read_text(encoding="utf-8")
        )
        reference = None
        if calibration_ref.is_file():
            reference = json.loads(calibration_ref.read_text(encoding="utf-8"))
        if "stored" not in locals():
            raise TypeError("summary unavailable")
        expected_apparatus = apparatus_assessment(scenario, stored, reference)
        if canonical_json(apparatus) != canonical_json(expected_apparatus):
            errors.append("apparatus_assessment_mismatch")
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        errors.append(f"apparatus_unreadable:{type(exc).__name__}")
    if manifest.get("calibration_required") and not manifest.get("calibration_present"):
        errors.append("missing_calibration")
    if manifest.get("calibration_present"):
        if not calibration_ref.is_file():
            errors.append("missing_calibration_ref")
        else:
            reference = json.loads(calibration_ref.read_text(encoding="utf-8"))
            record = reference.get("record")
            if not isinstance(record, dict):
                errors.append("missing_calibration_record")
            elif _json_sha256(record) != reference.get("calibration_record_sha256"):
                errors.append("calibration_record_hash_mismatch")
    return {"ok": not errors, "errors": errors, "recomputed_summary": recomputed}


def _json_sha256(value: Any) -> str:
    import hashlib

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _redact_endpoint(endpoint: str) -> str:
    from urllib.parse import urlsplit, urlunsplit

    if endpoint.startswith("local://"):
        return endpoint
    value = urlsplit(endpoint)
    host = value.hostname or ""
    if value.port:
        host = f"{host}:{value.port}"
    return urlunsplit((value.scheme, host, value.path, "", ""))
