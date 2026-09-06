from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Any, Mapping

import yaml

from .contracts import ContractError, file_sha256, load_contracts
from .workloads import load_jsonl


EXPERT_DRAFT_SCHEMA = "oicap-ac04-intake-draft/0.1"
ALPHA_PROFILE = "oicap-local-measurement-alpha1"
DEPLOYMENT_KEYS = (
    "model_identity",
    "tokenizer_and_chat_template",
    "quantization",
    "serving_engine",
    "container_and_runtime",
    "launch_configuration",
    "endpoint_boundary",
    "external_dependencies",
    "accelerator_topology",
    "host_platform",
    "parallelism",
    "memory_and_offload",
    "decoding_acceleration",
    "batching_scheduling_admission",
)
SUPPORTED_REQUIREMENT_STATES = {
    "required",
    "allowed_set",
    "not_required",
    "informational",
}
UNSUPPORTED_GATE_AUTHORITIES = {
    "quality_hook": "the alpha runner has no locked quality-hook execution path",
    "authoritative_token_timestamps": (
        "the OpenAI-compatible alpha adapter has no authoritative per-token timestamp source"
    ),
}


class TranslationError(ContractError):
    """An expert draft cannot be faithfully compiled by the local alpha."""


def translate_expert_draft(
    expert_path: str | Path,
    workload_path: str | Path,
    output_path: str | Path,
    *,
    load_point: float | None = None,
    max_in_flight: int | None = None,
    timeout_s: float = 60.0,
    seed: int = 20260906,
) -> Path:
    source_path = Path(expert_path).resolve()
    workload_source = Path(workload_path).resolve()
    destination = Path(output_path).resolve()
    if destination.exists():
        raise TranslationError(f"Output path already exists: {destination}")
    if not source_path.is_file():
        raise TranslationError(f"Expert draft does not exist: {source_path}")
    if not workload_source.is_file():
        raise TranslationError(f"Workload JSONL does not exist: {workload_source}")
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise TranslationError("timeout_s must be finite and greater than zero.")

    try:
        draft = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TranslationError(f"Invalid expert draft JSON: {exc}") from exc
    if not isinstance(draft, Mapping):
        raise TranslationError("Expert draft must be a JSON object.")
    draft = dict(draft)
    normalized = _validate_expert_draft(draft)
    selected_load = _select_load_point(normalized["execution"], load_point)
    workload_rows = _validate_workload(workload_source, normalized["class_ids"])
    documents, report = _compile_documents(
        draft,
        normalized,
        workload_source,
        selected_load,
        source_expert_draft_sha256=file_sha256(source_path),
        max_in_flight=max_in_flight,
        timeout_s=timeout_s,
        seed=seed,
    )
    report["workload_row_count"] = len(workload_rows)

    destination.mkdir(parents=True)
    try:
        shutil.copyfile(workload_source, destination / "workload.jsonl")
        for name, document in documents.items():
            (destination / f"{name}.yaml").write_text(
                yaml.safe_dump(document, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
        (destination / "translation-report.json").write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        contracts = load_contracts(destination)
        report["emitted_contract_identity"] = contracts.identity
        report["emitted_contract_hashes"] = contracts.hashes
        (destination / "translation-report.json").write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    except Exception:
        shutil.rmtree(destination)
        raise
    return destination


def _validate_expert_draft(draft: dict[str, Any]) -> dict[str, Any]:
    if draft.get("schema") != EXPERT_DRAFT_SCHEMA:
        raise TranslationError(
            f"Unsupported expert draft schema {draft.get('schema')!r}; "
            f"expected {EXPERT_DRAFT_SCHEMA!r}."
        )
    if draft.get("status") != "READY_FOR_HUMAN_REVIEW":
        raise TranslationError(
            "Expert draft is not READY_FOR_HUMAN_REVIEW; unresolved drafts cannot be compiled."
        )
    validation = _object(draft.get("validation"), "validation")
    if int(validation.get("error_count", -1)) != 0:
        raise TranslationError("Expert draft reports unresolved validation errors.")

    project = _object(draft.get("project"), "project")
    for key in ("project_id", "buyer_role", "technical_role", "measurement_boundary"):
        if not str(project.get(key, "")).strip():
            raise TranslationError(f"project.{key} is required.")

    classes = draft.get("workload_classes")
    if not isinstance(classes, list) or not classes:
        raise TranslationError("workload_classes must be a non-empty array.")
    class_ids: list[str] = []
    weights: list[float] = []
    think_times: list[float] = []
    for index, raw in enumerate(classes):
        item = _object(raw, f"workload_classes[{index}]")
        class_id = str(item.get("class_id", "")).strip()
        if not class_id or class_id in class_ids:
            raise TranslationError("Workload class IDs must be non-empty and unique.")
        class_ids.append(class_id)
        weight = _finite_number(item.get("weight_percent"), f"{class_id}.weight_percent")
        if weight <= 0:
            raise TranslationError(f"{class_id}.weight_percent must be greater than zero.")
        weights.append(weight)
        for key in ("input_tokens", "output_tokens", "quality_rule"):
            if not str(item.get(key, "")).strip():
                raise TranslationError(f"{class_id}.{key} is required.")
        think_time = _finite_number(item.get("think_time_ms", 0), f"{class_id}.think_time_ms")
        if think_time < 0:
            raise TranslationError(f"{class_id}.think_time_ms cannot be negative.")
        think_times.append(think_time)
    if abs(sum(weights) - 100.0) > 0.001:
        raise TranslationError("Workload class weights must sum to 100 percent.")

    gates = draft.get("sla_gates")
    if not isinstance(gates, list) or not gates:
        raise TranslationError("sla_gates must be a non-empty array.")
    gate_min_samples: list[int] = []
    gate_min_durations: list[float] = []
    authorities: set[str] = set()
    for index, raw in enumerate(gates):
        gate = _object(raw, f"sla_gates[{index}]")
        for key in ("metric", "workload_class", "statistic", "comparator", "unit", "population", "authority"):
            if not str(gate.get(key, "")).strip():
                raise TranslationError(f"sla_gates[{index}].{key} is required.")
        if str(gate["workload_class"]).strip() not in class_ids:
            raise TranslationError(f"sla_gates[{index}] references an unknown workload class.")
        _finite_number(gate.get("threshold"), f"sla_gates[{index}].threshold")
        samples_value = _finite_number(
            gate.get("min_samples"), f"sla_gates[{index}].min_samples"
        )
        if not samples_value.is_integer():
            raise TranslationError(f"sla_gates[{index}].min_samples must be an integer.")
        samples = int(samples_value)
        duration = _finite_number(gate.get("min_duration_s"), f"sla_gates[{index}].min_duration_s")
        if samples <= 0 or duration <= 0:
            raise TranslationError("Every SLA gate needs positive sample and duration minima.")
        gate_min_samples.append(samples)
        gate_min_durations.append(duration)
        authority = str(gate["authority"])
        authorities.add(authority)
        if authority in UNSUPPORTED_GATE_AUTHORITIES:
            raise TranslationError(
                f"sla_gates[{index}] cannot be compiled: {UNSUPPORTED_GATE_AUTHORITIES[authority]}."
            )

    requirements = _object(draft.get("deployment_requirements"), "deployment_requirements")
    if set(requirements) != set(DEPLOYMENT_KEYS):
        missing = sorted(set(DEPLOYMENT_KEYS) - set(requirements))
        extra = sorted(set(requirements) - set(DEPLOYMENT_KEYS))
        raise TranslationError(
            f"deployment_requirements must contain the frozen 14-key catalogue; "
            f"missing={missing}, extra={extra}."
        )
    for key in DEPLOYMENT_KEYS:
        requirement = _object(requirements[key], f"deployment_requirements.{key}")
        state = requirement.get("requirement_state")
        if state not in SUPPORTED_REQUIREMENT_STATES:
            raise TranslationError(f"deployment_requirements.{key} has an invalid state.")
        if state in {"required", "allowed_set"} and not str(requirement.get("constraint", "")).strip():
            raise TranslationError(f"deployment_requirements.{key}.constraint is required.")

    execution = _object(draft.get("execution"), "execution")
    semantics = execution.get("load_semantics")
    if semantics not in {"closed_loop", "open_loop"}:
        raise TranslationError("execution.load_semantics must be closed_loop or open_loop.")
    points = execution.get("load_points")
    if not isinstance(points, list) or not points:
        raise TranslationError("execution.load_points must be a non-empty array.")
    numeric_points = [_finite_number(value, "execution.load_points") for value in points]
    if any(point <= 0 for point in numeric_points):
        raise TranslationError("Every load point must be greater than zero.")
    if _finite_number(execution.get("max_load"), "execution.max_load") <= 0:
        raise TranslationError("execution.max_load must be greater than zero.")
    repeats_value = _finite_number(execution.get("repeats"), "execution.repeats")
    samples_value = _finite_number(
        execution.get("min_point_samples"), "execution.min_point_samples"
    )
    if not repeats_value.is_integer() or not samples_value.is_integer():
        raise TranslationError("Execution repeats and min_point_samples must be integers.")
    repeats = int(repeats_value)
    min_samples = int(samples_value)
    min_duration = _finite_number(execution.get("min_point_duration_s"), "execution.min_point_duration_s")
    if repeats < 2 or min_samples <= 0 or min_duration <= 0:
        raise TranslationError("Execution repetition, sample, and duration minima are invalid.")
    preflight = _object(execution.get("preflight"), "execution.preflight")
    for key in (
        "max_load_sustained",
        "resource_recorded",
        "onsite_same_path_calibration",
        "buyer_controls_responder",
    ):
        if preflight.get(key) is not True:
            raise TranslationError(f"execution.preflight.{key} must be true before translation.")

    if semantics == "closed_loop" and len(set(think_times)) != 1:
        raise TranslationError(
            "The current runner supports one closed-loop think_time_ms; all workload classes must agree."
        )
    return {
        "class_ids": class_ids,
        "weights": weights,
        "think_times": think_times,
        "gate_min_samples": gate_min_samples,
        "gate_min_durations": gate_min_durations,
        "authorities": authorities,
        "execution": execution,
        "load_points": numeric_points,
    }


def _select_load_point(execution: dict[str, Any], requested: float | None) -> float:
    points = [_finite_number(value, "execution.load_points") for value in execution["load_points"]]
    if requested is None:
        if len(points) != 1:
            raise TranslationError(
                "The expert draft declares multiple load points; select one with --load-point."
            )
        return points[0]
    selected = _finite_number(requested, "load_point")
    if not any(math.isclose(selected, point, rel_tol=0, abs_tol=1e-9) for point in points):
        raise TranslationError("Selected load point is not declared in execution.load_points.")
    return selected


def _validate_workload(path: Path, class_ids: list[str]) -> list[Any]:
    try:
        rows = load_jsonl(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise TranslationError(f"Invalid workload JSONL: {exc}") from exc
    present = {row.workload_class for row in rows}
    expected = set(class_ids)
    if present != expected:
        raise TranslationError(
            f"Workload class set differs from expert draft: missing={sorted(expected-present)}, "
            f"extra={sorted(present-expected)}."
        )
    return rows


def _compile_documents(
    draft: dict[str, Any],
    normalized: dict[str, Any],
    workload_source: Path,
    selected_load: float,
    *,
    source_expert_draft_sha256: str,
    max_in_flight: int | None,
    timeout_s: float,
    seed: int,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    project = dict(draft["project"])
    classes = list(draft["workload_classes"])
    gates = list(draft["sla_gates"])
    requirements = dict(draft["deployment_requirements"])
    execution = normalized["execution"]
    semantics = execution["load_semantics"]

    if semantics == "closed_loop":
        if not float(selected_load).is_integer():
            raise TranslationError("A closed-loop active-user load point must be an integer.")
        active_users = int(selected_load)
        arrival = {"kind": "closed_loop", "active_users": active_users}
        session = {"think_time_ms": normalized["think_times"][0]}
        effective_max_in_flight = active_users
        if max_in_flight is not None and max_in_flight != active_users:
            raise TranslationError(
                "For closed-loop alpha runs, --max-in-flight must equal the selected active-user point."
            )
    else:
        arrival = {"kind": "open_loop", "process": "constant", "rate_per_s": selected_load}
        session = None
        if max_in_flight is None or max_in_flight <= 0:
            raise TranslationError("Open-loop translation requires --max-in-flight > 0.")
        effective_max_in_flight = max_in_flight

    scenario: dict[str, Any] = {
        "schema_version": "0.1",
        "scenario_id": f"{project['project_id']}-load-{_id_number(selected_load)}",
        "workload_classes": [
            {"id": item["class_id"], "weight": float(item["weight_percent"]) / 100.0}
            for item in classes
        ],
        "source": {
            "kind": "local_jsonl",
            "path": "workload.jsonl",
            "content_sha256": file_sha256(workload_source),
        },
        "arrival": arrival,
    }
    if session is not None:
        scenario["session"] = session

    targets: dict[str, dict[str, Any]] = {
        class_id: {"gates": []} for class_id in normalized["class_ids"]
    }
    for gate in gates:
        class_id = str(gate["workload_class"]).strip()
        targets[class_id]["gates"].append(
            {
                key: gate[key]
                for key in (
                    "metric",
                    "statistic",
                    "comparator",
                    "threshold",
                    "unit",
                    "population",
                    "min_samples",
                    "min_duration_s",
                    "quality_eligible",
                    "authority",
                )
            }
        )
    slo = {"schema_version": "0.1", "targets": targets}

    service_constraint = _parse_service_discipline(
        requirements["batching_scheduling_admission"].get("constraint")
    )
    sut = {
        "schema_version": "0.1",
        "sut_id": f"{project['project_id']}-declared-sut",
        "model": {
            key: requirements[key]
            for key in ("model_identity", "tokenizer_and_chat_template", "quantization")
        },
        "engine": {
            key: requirements[key]
            for key in (
                "serving_engine",
                "container_and_runtime",
                "launch_configuration",
                "decoding_acceleration",
            )
        },
        "hardware": {
            key: requirements[key]
            for key in (
                "accelerator_topology",
                "host_platform",
                "parallelism",
                "memory_and_offload",
                "endpoint_boundary",
                "external_dependencies",
            )
        },
        "service_discipline": service_constraint,
    }

    measurement_requests = max(
        int(execution["min_point_samples"]),
        max(normalized["gate_min_samples"]),
    )
    authority = "server_usage" if "server_usage" in normalized["authorities"] else "none"
    run = {
        "schema_version": "0.1",
        "run_id": f"{project['project_id']}-load-{_id_number(selected_load)}-alpha1",
        "seed": seed,
        "setup": {"endpoint_health": "none", "tokenizer_check": "none"},
        "client": {
            "transport": "python_urllib",
            "connection_pooling": "none",
            "streaming": True,
        },
        "warmup": {"requests": 1},
        "measurement": {"requests": measurement_requests},
        "max_in_flight": effective_max_in_flight,
        "timeout_s": timeout_s,
        "retry_policy": {
            "max_attempts": 1,
            "backoff_ms": 0,
            "retry_on": ["timeout", "http_429", "http_502", "http_503", "http_504"],
        },
        "drain": {"policy": "complete_all"},
        "token_accounting": {"authority": authority},
        "validator": {"mode": "none"},
        "self_calibration": {
            "profile": "local_zero_delay_stream_v1",
            "repetitions": 2,
            "max_schedule_lag_p99_ms": 20,
            "max_event_loop_lag_p99_ms": 20,
            "max_runner_process_cpu_percent_one_core": 10000,
            "max_runner_system_cpu_percent": 100,
            "min_closed_loop_concurrency_ratio": 0.60,
            "min_arrival_rate_ratio": 0.98,
            "noise_stability_tolerance_ms": 20,
        },
    }

    report = {
        "schema": "oicap-expert-translation-report/0.1-alpha1",
        "profile": ALPHA_PROFILE,
        "source_expert_draft_sha256": source_expert_draft_sha256,
        "workload_sha256": file_sha256(workload_source),
        "selected_load_point": selected_load,
        "load_semantics": semantics,
        "formal_procurement_verdict_enabled": False,
        "local_measurement_enabled": True,
        "local_unsigned_evidence_verification_enabled": True,
        "preserved_but_not_enforced": {
            "slo_gates": True,
            "minimum_point_duration_s": execution["min_point_duration_s"],
            "independent_repeats": execution["repeats"],
            "declared_load_points": normalized["load_points"],
            "quality_rules": {item["class_id"]: item["quality_rule"] for item in classes},
        },
        "not_included": [
            "sealed_test_pack",
            "multi_point_sweep",
            "minimum_duration_enforcement",
            "minimum_successful_sample_enforcement",
            "independent_repeat_execution",
            "quality_gate_execution",
            "service_sla_verdict",
            "deployment_conformance_verdict",
            "server_side_adjudication",
            "hosted_report",
            "gpu_capacity_qualification",
        ],
        "warnings": [
            "sut.yaml preserves declared procurement requirements; it does not prove the observed deployment conforms to them.",
            "measurement.requests is sized from declared sample minima, but failures can leave fewer successful samples and no alpha verdict is issued.",
            "verify checks unsigned bundle internal consistency, not producer identity or tamper resistance.",
        ],
        "alpha_runner_profile": {
            "seed": seed,
            "warmup_requests": 1,
            "measurement_requests": measurement_requests,
            "max_in_flight": effective_max_in_flight,
            "timeout_s": timeout_s,
            "token_accounting_authority": authority,
            "self_calibration": run["self_calibration"],
        },
    }
    return {"scenario": scenario, "slo": slo, "sut": sut, "run": run}, report


def _parse_service_discipline(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, str) or not raw.strip():
        raise TranslationError(
            "batching_scheduling_admission.constraint must be a JSON object for alpha translation."
        )
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TranslationError(
            "batching_scheduling_admission.constraint must be JSON with batching, admission, and preemption."
        ) from exc
    value = _object(value, "batching_scheduling_admission.constraint")
    allowed = {"batching", "admission", "preemption", "fairness_bound_ms"}
    if set(value) - allowed:
        raise TranslationError("Service-discipline JSON contains unsupported fields.")
    for key in ("batching", "admission", "preemption"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise TranslationError(f"Service-discipline JSON requires string field {key!r}.")
    if "fairness_bound_ms" not in value:
        value["fairness_bound_ms"] = None
    return value


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise TranslationError(f"{where} must be an object.")
    return dict(value)


def _finite_number(value: Any, where: str) -> float:
    if isinstance(value, bool):
        raise TranslationError(f"{where} must be numeric, not boolean.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise TranslationError(f"{where} must be numeric.") from exc
    if not math.isfinite(result):
        raise TranslationError(f"{where} must be finite.")
    return result


def _id_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value).replace(".", "p")
