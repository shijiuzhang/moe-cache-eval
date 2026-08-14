from __future__ import annotations

import asyncio
import json
import hashlib
import os
import time
from pathlib import Path
from typing import Any

import psutil

from .contracts import ContractSet, canonical_json, file_sha256
from .evidence import write_bundle
from .metrics import quantile, summarize
from .runner import execute_load_point
from .runner import RunResult
from .test_server import DeterministicServer


CALIBRATION_VERSION = "0.1"


async def calibrate(contracts: ContractSet, output: str | Path) -> Path:
    process = psutil.Process(os.getpid())
    process.cpu_percent(None)
    psutil.cpu_percent(None)
    process_start = time.process_time_ns()
    wall_start = time.perf_counter_ns()
    repetition_count = int(contracts.run["self_calibration"]["repetitions"])
    results: list[RunResult] = []
    with DeterministicServer(force_zero_delay=True) as server:
        for repetition in range(repetition_count):
            current = await execute_load_point(contracts, server.endpoint)
            for row in current.observations:
                row.request_id = f"c{repetition:02d}-{row.request_id}"
            results.append(current)
    result = RunResult(
        observations=[row for current in results for row in current.observations],
        started_ns=min(current.started_ns for current in results),
        finished_ns=max(current.finished_ns for current in results),
    )
    wall_end = time.perf_counter_ns()
    process_end = time.process_time_ns()
    measured_rows = [row for row in result.observations if row.phase == "measurement"]
    summary = summarize(measured_rows)
    duration_s = max((wall_end - wall_start) / 1_000_000_000, 1e-12)
    process_cpu = (process_end - process_start) / 1_000_000_000 / duration_s * 100.0
    system_cpu = psutil.cpu_percent(None)
    expected_rate = _requested_rate(contracts)
    repeat_rows = [
        [row for row in current.observations if row.phase == "measurement"]
        for current in results
    ]
    repeat_summaries = [summarize(rows) for rows in repeat_rows]
    repeat_achieved_rates = [
        item["load_realization"]["achieved_submission_rate_per_s"]
        for item in repeat_summaries
    ]
    achieved_values = [float(value) for value in repeat_achieved_rates if value is not None]
    achieved_rate = min(achieved_values) if achieved_values else None
    latency = summary["latency_ms"]
    clock_ms = time.get_clock_info("perf_counter").resolution * 1000.0
    repeat_resolutions = [
        {
            name: max(clock_ms, float(values["p99"])) if values["p99"] is not None else None
            for name, values in {
                "ttft_ms": item["latency_ms"]["ttft"],
                "itl_ms": item["latency_ms"]["itl"],
                "tpot_ms": item["latency_ms"]["tpot"],
                "end_to_end_ms": item["latency_ms"]["end_to_end"],
            }.items()
        }
        for item in repeat_summaries
    ]
    resolution = {
        metric: max(
            (float(item[metric]) for item in repeat_resolutions if item[metric] is not None),
            default=None,
        )
        for metric in ("ttft_ms", "itl_ms", "tpot_ms", "end_to_end_ms")
    }
    schedule_lags = [
        (row.t_submit_ns - row.t_scheduled_ns) / 1_000_000.0 for row in measured_rows
    ]
    config = contracts.run.get("self_calibration", {})
    max_schedule_lag = float(config.get("max_schedule_lag_p99_ms", float("inf")))
    max_process_cpu = float(
        config.get("max_runner_process_cpu_percent_one_core", float("inf"))
    )
    min_arrival_ratio = float(config.get("min_arrival_rate_ratio", 0.98))
    stability_tolerance = float(config["noise_stability_tolerance_ms"])
    schedule_p99 = latency["schedule_lag"]["p99"]
    invalid_reasons: list[str] = []
    if not measured_rows or not all(row.success for row in measured_rows):
        invalid_reasons.append("null_endpoint_request_failure")
    if schedule_p99 is None or float(schedule_p99) > max_schedule_lag:
        invalid_reasons.append("schedule_lag_exceeded")
    if process_cpu > max_process_cpu:
        invalid_reasons.append("runner_process_cpu_exceeded")
    if expected_rate is not None and (
        achieved_rate is None or achieved_rate / expected_rate < min_arrival_ratio
    ):
        invalid_reasons.append("arrival_rate_not_realized")
    instability: dict[str, float] = {}
    for metric in resolution:
        values = [
            float(item[metric]) for item in repeat_resolutions if item[metric] is not None
        ]
        if values:
            instability[metric] = max(values) - min(values)
            if instability[metric] > stability_tolerance:
                invalid_reasons.append(f"noise_resolution_unstable:{metric}")
    calibration_record = {
        "schema_version": "0.1",
        "calibration_version": CALIBRATION_VERSION,
        "profile": "local_zero_delay_stream_v1",
        "measurement_identity": contracts.measurement_identity,
        "noise_resolution": resolution,
        "noise_resolution_by_repetition": repeat_resolutions,
        "noise_resolution_range_ms": instability,
        "client_schedule_lag_ms": latency["schedule_lag"],
        "requested_arrival_rate_per_s": expected_rate,
        "arrival_kind": contracts.scenario["arrival"]["kind"],
        "requested_active_users": contracts.scenario["arrival"].get("active_users"),
        "achieved_arrival_rate_per_s": achieved_rate,
        "arrival_rate_ratio": (
            achieved_rate / expected_rate
            if expected_rate and achieved_rate is not None
            else None
        ),
        "runner_process_cpu_percent_one_core": process_cpu,
        "runner_system_cpu_percent": system_cpu,
        "event_loop_lag_ms": _event_loop_lag(schedule_lags),
        "realized_peak_in_flight": summary["load_realization"]["peak_in_flight"],
        "request_count": len(measured_rows),
        "repetitions": repetition_count,
        "duration_s": duration_s,
        "request_payload_bytes": {
            "min": min(
                len(canonical_json(row.request_body).encode("utf-8")) for row in measured_rows
            ),
            "max": max(
                len(canonical_json(row.request_body).encode("utf-8")) for row in measured_rows
            ),
        },
        "response_shape": {
            "leading_empty_delta": True,
            "substantive_content_events": 2,
            "completion_tokens": 2,
        },
        "limits": {
            "max_schedule_lag_p99_ms": max_schedule_lag,
            "max_runner_process_cpu_percent_one_core": max_process_cpu,
            "min_arrival_rate_ratio": min_arrival_ratio,
            "noise_stability_tolerance_ms": stability_tolerance,
        },
        "invalid_reasons": invalid_reasons,
        "valid": not invalid_reasons,
    }
    bundle = write_bundle(
        output,
        contracts,
        result,
        "local://deterministic-null",
        calibration_ref=None,
        require_calibration=False,
        invocation=["oicap", "calibrate"],
    )
    (bundle / "calibration.json").write_text(
        json.dumps(calibration_record, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    _refresh_manifest(bundle)
    return bundle


def load_calibration(path: str | Path, expected_measurement_identity: str) -> dict[str, Any]:
    from .evidence import verify_bundle

    root = Path(path).resolve()
    verification = verify_bundle(root)
    if not verification["ok"]:
        raise ValueError(f"Calibration bundle is invalid: {verification['errors']}")
    record_path = root / "calibration.json"
    if not record_path.is_file():
        raise ValueError("Calibration bundle lacks calibration.json.")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if record.get("measurement_identity") != expected_measurement_identity:
        raise ValueError("Calibration measurement identity does not match run contract.")
    if not record.get("valid"):
        raise ValueError("Calibration record is not valid.")
    return {
        "source_bundle_manifest_sha256": file_sha256(root / "manifest.json"),
        "calibration_record_sha256": hashlib.sha256(
            canonical_json(record).encode("utf-8")
        ).hexdigest(),
        "record": record,
    }


def _requested_rate(contracts: ContractSet) -> float | None:
    arrival = contracts.scenario["arrival"]
    if arrival["kind"] == "open_loop":
        return float(arrival["rate_per_s"])
    return None


def _event_loop_lag(schedule_lags: list[float]) -> dict[str, float | None]:
    return {
        "p99": quantile(schedule_lags, 0.99),
        "max": max(schedule_lags) if schedule_lags else None,
    }


def _refresh_manifest(root: Path) -> None:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    )
    manifest["files"] = {name: file_sha256(root / name) for name in files}
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
