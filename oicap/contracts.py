from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


SCHEMA_VERSION = "0.1"
CONTRACT_FILES = ("scenario.yaml", "slo.yaml", "sut.yaml", "run.yaml")


class ContractError(ValueError):
    """A contract is missing, inconsistent, or outside the supported schema."""


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{where} must be a mapping.")
    return dict(value)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ContractError(f"Missing contract file: {path}")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ContractError(f"Invalid YAML in {path}: {exc}") from exc
    document = _mapping(value, str(path))
    version = str(document.get("schema_version", ""))
    if version != SCHEMA_VERSION:
        raise ContractError(
            f"{path.name}: unsupported schema_version {version!r}; "
            f"expected {SCHEMA_VERSION!r}."
        )
    return document


@dataclass(frozen=True)
class ContractSet:
    root: Path
    scenario: dict[str, Any]
    slo: dict[str, Any]
    sut: dict[str, Any]
    run: dict[str, Any]

    @property
    def documents(self) -> dict[str, dict[str, Any]]:
        return {
            "scenario": self.scenario,
            "slo": self.slo,
            "sut": self.sut,
            "run": self.run,
        }

    @property
    def hashes(self) -> dict[str, str]:
        return {name: canonical_sha256(value) for name, value in self.documents.items()}

    @property
    def identity(self) -> str:
        return canonical_sha256(
            {**self.hashes, "workload_sha256": file_sha256(self.workload_path)}
        )

    @property
    def measurement_identity(self) -> str:
        """Identity of runner-affecting inputs, excluding non-adjudicated SLOs."""
        return canonical_sha256(
            {
                **{name: digest for name, digest in self.hashes.items() if name != "slo"},
                "workload_sha256": file_sha256(self.workload_path),
            }
        )

    @property
    def workload_path(self) -> Path:
        source = _mapping(self.scenario["source"], "scenario.source")
        raw = Path(str(source["path"]))
        return raw if raw.is_absolute() else self.root / raw

    def normalized(self) -> dict[str, Any]:
        return json.loads(canonical_json(self.documents))


def load_contracts(root: str | Path) -> ContractSet:
    root_path = Path(root).resolve()
    loaded = {name.removesuffix(".yaml"): _load_yaml(root_path / name) for name in CONTRACT_FILES}
    contracts = ContractSet(root=root_path, **loaded)
    validate_contracts(contracts)
    return contracts


def validate_contracts(contracts: ContractSet) -> None:
    scenario = contracts.scenario
    run = contracts.run
    sut = contracts.sut
    slo = contracts.slo

    if not str(scenario.get("scenario_id", "")).strip():
        raise ContractError("scenario.scenario_id is required.")
    classes = scenario.get("workload_classes")
    if not isinstance(classes, list) or not classes:
        raise ContractError("scenario.workload_classes must be a non-empty list.")
    ids: list[str] = []
    weights: list[float] = []
    for index, item in enumerate(classes):
        entry = _mapping(item, f"scenario.workload_classes[{index}]")
        class_id = str(entry.get("id", "")).strip()
        if not class_id or class_id in ids:
            raise ContractError("Workload class IDs must be non-empty and unique.")
        ids.append(class_id)
        try:
            weights.append(float(entry["weight"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError(f"Workload class {class_id!r} needs numeric weight.") from exc
    if (
        any(not math.isfinite(weight) or weight < 0 for weight in weights)
        or abs(sum(weights) - 1.0) > 1e-9
    ):
        raise ContractError("Workload class weights must be non-negative and sum to 1.")

    source = _mapping(scenario.get("source"), "scenario.source")
    if source.get("kind") != "local_jsonl" or not source.get("path"):
        raise ContractError("v0.1 requires scenario.source kind=local_jsonl and path.")
    workload = contracts.workload_path
    if not workload.is_file():
        raise ContractError(f"Workload JSONL does not exist: {workload}")
    declared = source.get("content_sha256")
    if declared and declared != file_sha256(workload):
        raise ContractError("scenario.source.content_sha256 does not match workload file.")
    from .workloads import load_jsonl

    try:
        rows = load_jsonl(workload)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ContractError(f"Invalid workload JSONL: {exc}") from exc
    row_classes = {row.workload_class for row in rows}
    unexpected_classes = sorted(row_classes - set(ids))
    missing_classes = sorted(set(ids) - row_classes)
    if unexpected_classes:
        raise ContractError(
            f"Workload rows contain undeclared classes: {unexpected_classes}"
        )
    if missing_classes:
        raise ContractError(
            f"Workload source has no rows for declared classes: {missing_classes}"
        )

    arrival = _mapping(scenario.get("arrival"), "scenario.arrival")
    kind = arrival.get("kind")
    if kind == "closed_loop":
        if int(arrival.get("active_users", 0)) <= 0:
            raise ContractError("closed_loop arrival requires active_users > 0.")
    elif kind == "open_loop":
        rate = float(arrival.get("rate_per_s", 0))
        if not math.isfinite(rate) or rate <= 0:
            raise ContractError("open_loop arrival requires rate_per_s > 0.")
        if arrival.get("process") != "constant":
            raise ContractError("v0.1 open_loop arrival requires process=constant.")
    else:
        raise ContractError("scenario.arrival.kind must be closed_loop or open_loop.")

    if not str(run.get("run_id", "")).strip():
        raise ContractError("run.run_id is required.")
    setup = _mapping(run.get("setup"), "run.setup")
    if setup.get("endpoint_health") not in {"none"}:
        raise ContractError("v0.1 supports run.setup.endpoint_health=none only.")
    if setup.get("tokenizer_check") not in {"none"}:
        raise ContractError("v0.1 supports run.setup.tokenizer_check=none only.")
    client = _mapping(run.get("client"), "run.client")
    if client.get("transport") != "python_urllib":
        raise ContractError("v0.1 requires run.client.transport=python_urllib.")
    if client.get("connection_pooling") != "none":
        raise ContractError("v0.1 urllib adapter requires connection_pooling=none.")
    if client.get("streaming") is not True:
        raise ContractError("v0.1 requires run.client.streaming=true.")
    measurement = _mapping(run.get("measurement"), "run.measurement")
    if int(measurement.get("requests", 0)) <= 0:
        raise ContractError("run.measurement.requests must be > 0.")
    if int(run.get("max_in_flight", 0)) <= 0:
        raise ContractError("run.max_in_flight must be > 0.")
    timeout_s = float(run.get("timeout_s", 0))
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ContractError("run.timeout_s must be > 0.")
    retry = _mapping(run.get("retry_policy"), "run.retry_policy")
    try:
        max_attempts = int(retry.get("max_attempts", 0))
        backoff_ms = float(retry.get("backoff_ms", -1))
    except (TypeError, ValueError) as exc:
        raise ContractError("run.retry_policy values must be numeric.") from exc
    if max_attempts <= 0 or backoff_ms < 0:
        raise ContractError(
            "run.retry_policy requires max_attempts > 0 and backoff_ms >= 0."
        )
    if not math.isfinite(backoff_ms):
        raise ContractError("run.retry_policy.backoff_ms must be finite.")
    retry_on = retry.get("retry_on")
    if not isinstance(retry_on, list) or not all(
        isinstance(value, str) and value for value in retry_on
    ):
        raise ContractError("run.retry_policy.retry_on must be a list of error names.")
    drain = _mapping(run.get("drain"), "run.drain")
    if drain.get("policy") != "complete_all":
        raise ContractError("v0.1 requires run.drain.policy=complete_all.")
    calibration = _mapping(run.get("self_calibration"), "run.self_calibration")
    if calibration.get("profile") != "local_zero_delay_stream_v1":
        raise ContractError(
            "v0.1 requires run.self_calibration.profile=local_zero_delay_stream_v1."
        )
    for field in (
        "max_schedule_lag_p99_ms",
        "max_runner_process_cpu_percent_one_core",
        "min_arrival_rate_ratio",
        "noise_stability_tolerance_ms",
    ):
        if field not in calibration:
            raise ContractError(f"run.self_calibration.{field} is required.")
    if int(calibration.get("repetitions", 0)) < 2:
        raise ContractError("run.self_calibration.repetitions must be >= 2.")
    try:
        schedule_limit = float(calibration["max_schedule_lag_p99_ms"])
        cpu_limit = float(calibration["max_runner_process_cpu_percent_one_core"])
        rate_ratio = float(calibration["min_arrival_rate_ratio"])
        stability = float(calibration["noise_stability_tolerance_ms"])
    except (TypeError, ValueError) as exc:
        raise ContractError("run.self_calibration limits must be numeric.") from exc
    if not all(math.isfinite(value) for value in (schedule_limit, cpu_limit, rate_ratio, stability)):
        raise ContractError("run.self_calibration limits must be finite.")
    if schedule_limit < 0 or cpu_limit <= 0 or not 0 < rate_ratio <= 1 or stability < 0:
        raise ContractError("run.self_calibration limits are outside their valid ranges.")
    accounting = _mapping(run.get("token_accounting"), "run.token_accounting")
    if accounting.get("authority") not in {
        "none",
        "server_usage",
        "synthetic_one_token_per_content_event",
    }:
        raise ContractError("Unsupported run.token_accounting.authority.")
    validator = _mapping(run.get("validator"), "run.validator")
    if validator.get("mode") != "none":
        raise ContractError("v0.1 records responses but only supports validator.mode=none.")

    if not str(sut.get("sut_id", "")).strip():
        raise ContractError("sut.sut_id is required.")
    discipline = _mapping(sut.get("service_discipline"), "sut.service_discipline")
    for field in ("batching", "admission", "preemption"):
        if field not in discipline:
            raise ContractError(f"sut.service_discipline.{field} is required (use unknown if needed).")

    targets = slo.get("targets")
    if not isinstance(targets, Mapping) or not targets:
        raise ContractError(
            "slo.targets must be a non-empty mapping (recorded but not adjudicated in v0.1)."
        )
    missing_targets = sorted(set(ids) - set(map(str, targets)))
    extra_targets = sorted(set(map(str, targets)) - set(ids))
    if missing_targets:
        raise ContractError(
            f"slo.targets lacks declared workload classes: {missing_targets}"
        )
    if extra_targets:
        raise ContractError(f"slo.targets contains undeclared classes: {extra_targets}")
    for class_id, target in targets.items():
        if not isinstance(target, Mapping) or not target:
            raise ContractError(f"slo.targets.{class_id} must be a non-empty mapping.")
