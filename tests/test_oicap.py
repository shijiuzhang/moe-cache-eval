from __future__ import annotations

import asyncio
import copy
import io
import json
import os
import tempfile
import time
import tomllib
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import yaml

from oicap.calibration import calibrate, load_calibration
from oicap.cli import main as cli_main
from oicap.contracts import ContractError, canonical_sha256, load_contracts
from oicap import __version__
from oicap.evidence import apparatus_assessment, verify_bundle, write_bundle
from oicap.metrics import observation_metrics, summarize
from oicap.observations import ChunkObservation, RequestObservation
from oicap.openai_adapter import OpenAIAdapter
from oicap.runner import (
    RunResult,
    _closed_loop,
    _execute_with_retries,
    _open_loop,
    execute_load_point,
)
from oicap.test_server import DeterministicServer
from oicap.workloads import WorkloadItem, deterministic_sequence


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "oicap" / "basic"


class ContractTests(unittest.TestCase):
    def test_runtime_and_package_versions_match(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text())
        self.assertEqual(__version__, project["project"]["version"])

    def test_example_contract_is_valid_and_hash_stable(self) -> None:
        contracts = load_contracts(EXAMPLE)
        reordered = {key: contracts.scenario[key] for key in reversed(contracts.scenario)}
        self.assertEqual(canonical_sha256(contracts.scenario), canonical_sha256(reordered))
        self.assertEqual(len(contracts.identity), 64)

    def test_unknown_major_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for source in EXAMPLE.iterdir():
                if source.is_file():
                    (root / source.name).write_bytes(source.read_bytes())
            scenario = yaml.safe_load((root / "scenario.yaml").read_text())
            scenario["schema_version"] = "1.0"
            (root / "scenario.yaml").write_text(yaml.safe_dump(scenario))
            with self.assertRaisesRegex(ContractError, "unsupported schema_version"):
                load_contracts(root)

    def test_declared_class_weights_drive_deterministic_selection(self) -> None:
        items = [
            WorkloadItem("a", "a", {}),
            WorkloadItem("b", "b", {}),
        ]
        first = deterministic_sequence(items, 1000, 7, {"a": 0.8, "b": 0.2})
        second = deterministic_sequence(items, 1000, 7, {"a": 0.8, "b": 0.2})
        self.assertEqual(first, second)
        count_a = sum(item.workload_class == "a" for item in first)
        self.assertGreater(count_a, 750)
        self.assertLess(count_a, 850)

    def test_invalid_weights_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for source in EXAMPLE.iterdir():
                if source.is_file():
                    (root / source.name).write_bytes(source.read_bytes())
            scenario = yaml.safe_load((root / "scenario.yaml").read_text())
            scenario["workload_classes"][0]["weight"] = 0.5
            (root / "scenario.yaml").write_text(yaml.safe_dump(scenario))
            with self.assertRaisesRegex(ContractError, "sum to 1"):
                load_contracts(root)

    def test_non_finite_weight_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for source in EXAMPLE.iterdir():
                if source.is_file():
                    (root / source.name).write_bytes(source.read_bytes())
            scenario = yaml.safe_load((root / "scenario.yaml").read_text())
            scenario["workload_classes"][0]["weight"] = float("nan")
            (root / "scenario.yaml").write_text(yaml.safe_dump(scenario))
            with self.assertRaisesRegex(ContractError, "sum to 1"):
                load_contracts(root)

    def test_incomplete_slo_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for source in EXAMPLE.iterdir():
                if source.is_file():
                    (root / source.name).write_bytes(source.read_bytes())
            slo = yaml.safe_load((root / "slo.yaml").read_text())
            slo["targets"] = {}
            (root / "slo.yaml").write_text(yaml.safe_dump(slo))
            with self.assertRaisesRegex(ContractError, "non-empty|violates published schema"):
                load_contracts(root)

    def test_undeclared_chunk_token_authority_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for source in EXAMPLE.iterdir():
                if source.is_file():
                    (root / source.name).write_bytes(source.read_bytes())
            run = yaml.safe_load((root / "run.yaml").read_text())
            run["token_accounting"]["authority"] = "declared_one_token_per_content_event"
            (root / "run.yaml").write_text(yaml.safe_dump(run))
            with self.assertRaisesRegex(ContractError, "Unsupported|violates published schema"):
                load_contracts(root)

    def test_published_schema_documents_are_valid_json(self) -> None:
        schema_root = ROOT / "oicap" / "schemas" / "0.1"
        self.assertEqual(
            {path.name for path in schema_root.glob("*.json")},
            {"scenario.schema.json", "slo.schema.json", "sut.schema.json", "run.schema.json"},
        )
        for path in schema_root.glob("*.json"):
            schema = json.loads(path.read_text())
            self.assertEqual(schema["$schema"],
                             "https://json-schema.org/draft/2020-12/schema")
            from jsonschema import Draft202012Validator
            Draft202012Validator.check_schema(schema)

    def test_published_schema_is_enforced_before_semantic_validation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for source in EXAMPLE.iterdir():
                if source.is_file():
                    (root / source.name).write_bytes(source.read_bytes())
            sut = yaml.safe_load((root / "sut.yaml").read_text())
            for field in ("model", "engine", "hardware"):
                sut.pop(field)
            (root / "sut.yaml").write_text(yaml.safe_dump(sut))
            with self.assertRaisesRegex(ContractError, "violates published schema"):
                load_contracts(root)

    def test_session_think_time_is_declared_strict_and_reachable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for source in EXAMPLE.iterdir():
                if source.is_file():
                    (root / source.name).write_bytes(source.read_bytes())
            scenario_path = root / "scenario.yaml"
            scenario = yaml.safe_load(scenario_path.read_text())
            scenario["session"] = {"think_time_ms": 5}
            scenario_path.write_text(yaml.safe_dump(scenario))
            self.assertEqual(load_contracts(root).scenario["session"]["think_time_ms"], 5)

            scenario.pop("session")
            scenario_path.write_text(yaml.safe_dump(scenario))
            with self.assertRaisesRegex(ContractError, "violates published schema"):
                load_contracts(root)

            for misspelled in ("think_time", "think_time_s"):
                with self.subTest(misspelled=misspelled):
                    scenario["session"] = {misspelled: 5}
                    scenario_path.write_text(yaml.safe_dump(scenario))
                    with self.assertRaisesRegex(ContractError, "violates published schema"):
                        load_contracts(root)

    def test_session_is_rejected_for_open_loop_where_it_would_be_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for source in EXAMPLE.iterdir():
                if source.is_file():
                    (root / source.name).write_bytes(source.read_bytes())
            scenario = yaml.safe_load((root / "scenario.yaml").read_text())
            scenario["arrival"] = {
                "kind": "open_loop", "process": "constant", "rate_per_s": 10,
            }
            scenario["session"] = {"think_time_ms": 5}
            (root / "scenario.yaml").write_text(yaml.safe_dump(scenario))
            with self.assertRaisesRegex(ContractError, "violates published schema"):
                load_contracts(root)

    def test_fixed_contract_shapes_reject_unknown_keys(self) -> None:
        mutations = {
            "scenario.yaml": lambda value: value.__setitem__("sessions", {}),
            "slo.yaml": lambda value: value.__setitem__("aggregate", {}),
            "sut.yaml": lambda value: value.__setitem__("service_policy", {}),
            "run.yaml": lambda value: value["self_calibration"].__setitem__(
                "max_schedule_lag_ms", 20
            ),
        }
        for filename, mutate in mutations.items():
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                for source in EXAMPLE.iterdir():
                    if source.is_file():
                        (root / source.name).write_bytes(source.read_bytes())
                path = root / filename
                value = yaml.safe_load(path.read_text())
                mutate(value)
                path.write_text(yaml.safe_dump(value))
                with self.assertRaisesRegex(ContractError, "violates published schema"):
                    load_contracts(root)


class TimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_delta_is_not_first_token(self) -> None:
        with DeterministicServer() as server:
            adapter = OpenAIAdapter(server.endpoint)
            row = await adapter.execute(
                "r1",
                "interactive",
                {"model": "x", "oicap_test": {"leading_empty": True, "ttft_ms": 30, "tokens": ["x"]}},
                time.perf_counter_ns(),
                2,
                "synthetic_one_token_per_content_event",
            )
        self.assertTrue(row.success)
        self.assertIsNotNone(row.t_first_chunk_ns)
        self.assertIsNotNone(row.t_first_token_ns)
        self.assertEqual(row.chunks[0].kind, "role_empty")
        self.assertGreaterEqual((row.t_first_token_ns - row.t_first_chunk_ns) / 1e6, 20)

    async def test_single_token_tpot_is_undefined(self) -> None:
        with DeterministicServer() as server:
            row = await OpenAIAdapter(server.endpoint).execute(
                "r1",
                "interactive",
                {"model": "x", "oicap_test": {"tokens": ["only"]}},
                time.perf_counter_ns(),
                2,
                "synthetic_one_token_per_content_event",
            )
        self.assertIsNone(observation_metrics(row)["tpot_ms"])

    def test_legacy_metrics_remain_recomputable(self) -> None:
        now = time.perf_counter_ns()
        row = RequestObservation(
            request_id="legacy",
            workload_class="x",
            phase="measurement",
            t_scheduled_ns=now,
            t_submit_ns=now,
            t_first_token_ns=now + 10_000_000,
            t_complete_ns=now + 40_000_000,
            success=True,
            output_tokens=4,
            token_timing_authority="server_usage",
        )
        legacy = summarize([row], metrics_version="0.1")
        current = summarize([row])
        self.assertEqual(legacy["metrics_version"], "0.1")
        self.assertEqual(legacy["latency_ms"]["tpot"]["mean"], 10.0)
        self.assertNotIn("availability", legacy["latency_ms"]["tpot"])
        self.assertEqual(current["latency_ms"]["tpot"]["availability"], "unavailable")
        self.assertIsNone(current["latency_ms"]["tpot"]["mean"])

    async def test_injected_delays_are_visible(self) -> None:
        with DeterministicServer() as server:
            row = await OpenAIAdapter(server.endpoint).execute(
                "r1",
                "interactive",
                {"model": "x", "oicap_test": {"ttft_ms": 20, "token_delay_ms": 15, "tokens": ["a", "b"]}},
                time.perf_counter_ns(),
                2,
                "synthetic_one_token_per_content_event",
            )
        values = observation_metrics(row)
        self.assertGreaterEqual(values["ttft_ms"], 15)
        self.assertGreaterEqual(values["itl_ms"][0], 10)

    async def test_queue_delay_precedes_first_byte(self) -> None:
        with DeterministicServer() as server:
            row = await OpenAIAdapter(server.endpoint).execute(
                "r1", "interactive",
                {"model": "x", "oicap_test": {"queue_ms": 25, "tokens": ["x"]}},
                time.perf_counter_ns(), 2,
                "synthetic_one_token_per_content_event",
            )
        self.assertGreaterEqual((row.t_first_byte_ns - row.t_submit_ns) / 1e6, 15)

    async def test_synthetic_token_authority_is_refused_for_real_payload(self) -> None:
        adapter = OpenAIAdapter("http://127.0.0.1:9/v1/chat/completions")
        with self.assertRaisesRegex(ValueError, "restricted"):
            await adapter.execute(
                "r", "x", {"model": "x", "messages": []},
                time.perf_counter_ns(), 0.01,
                "synthetic_one_token_per_content_event",
            )

    async def test_none_token_authority_does_not_silently_use_server_usage(self) -> None:
        with DeterministicServer() as server:
            row = await OpenAIAdapter(server.endpoint).execute(
                "r", "x", {"model": "x", "oicap_test": {"tokens": ["a", "b"]}},
                time.perf_counter_ns(), 2, "none",
            )
        self.assertTrue(row.success)
        self.assertIsNone(row.input_tokens)
        self.assertIsNone(row.output_tokens)
        self.assertEqual(row.token_timestamps_ns, [])

    async def test_real_endpoint_reports_inter_chunk_but_not_token_itl(self) -> None:
        with DeterministicServer() as server:
            row = await OpenAIAdapter(server.endpoint).execute(
                "r", "x",
                {"model": "x", "oicap_test": {
                    "tokens": ["a", "b", "c"], "token_delay_ms": 5,
                }},
                time.perf_counter_ns(), 2, "server_usage",
            )
        summary = summarize([row])
        self.assertEqual(summary["latency_ms"]["itl"]["availability"], "unavailable")
        self.assertEqual(summary["latency_ms"]["itl"]["count"], 0)
        self.assertEqual(summary["latency_ms"]["inter_chunk_latency"]["count"], 2)
        self.assertEqual(summary["latency_ms"]["tpot"]["availability"], "unavailable")
        self.assertEqual(summary["latency_ms"]["tpot"]["count"], 0)
        self.assertEqual(
            summary["latency_ms"]["tpot"]["unavailable_reason"],
            "no_authoritative_first_to_last_token_timestamps",
        )

    async def test_reasoning_events_are_named_without_retaining_reasoning_text(self) -> None:
        with DeterministicServer() as server:
            row = await OpenAIAdapter(server.endpoint).execute(
                "r", "x",
                {"model": "x", "oicap_test": {
                    "reasoning_tokens": ["private ", "reasoning"],
                    "tokens": ["OK"],
                }},
                time.perf_counter_ns(), 2, "server_usage",
            )
        self.assertTrue(row.success)
        self.assertEqual([chunk.kind for chunk in row.chunks].count("reasoning"), 2)
        self.assertNotIn("private", "".join(chunk.content for chunk in row.chunks))

    async def test_timeout_is_recorded_as_right_censored(self) -> None:
        with DeterministicServer() as server:
            row = await OpenAIAdapter(server.endpoint).execute(
                "r", "x",
                {"model": "x", "oicap_test": {"queue_ms": 100, "tokens": ["x"]}},
                time.perf_counter_ns(), 0.01, "server_usage",
            )
        self.assertTrue(row.timed_out)
        self.assertTrue(row.censored)
        self.assertEqual(row.error_type, "timeout")


class LoadSemanticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_open_loop_schedule_is_independent_of_completion(self) -> None:
        contracts = load_contracts(EXAMPLE)
        items = [
            type("Item", (), {"workload_class": "x", "body": {}})()
            for _ in range(4)
        ]

        async def slow_execute(request_id, workload_class, body, scheduled_ns, timeout_s, authority, phase):
            submitted = time.perf_counter_ns()
            await asyncio.sleep(0.04)
            completed = time.perf_counter_ns()
            return RequestObservation(
                request_id=request_id, workload_class=workload_class, phase=phase,
                t_scheduled_ns=scheduled_ns, t_submit_ns=submitted,
                t_first_token_ns=completed, t_complete_ns=completed,
                success=True, output_tokens=1,
            )

        started = time.perf_counter_ns()
        rows = await _open_loop(items, slow_execute, started, 50.0, 8, 1, "none", "measurement")
        scheduled = sorted(row.t_scheduled_ns for row in rows)
        self.assertTrue(all(abs((b - a) / 1e6 - 20) < 0.01 for a, b in zip(scheduled, scheduled[1:])))
        self.assertLess((max(row.t_submit_ns for row in rows) - min(row.t_submit_ns for row in rows)) / 1e6, 80)

    async def test_closed_loop_limits_active_requests(self) -> None:
        active = 0
        maximum = 0
        lock = asyncio.Lock()
        items = [type("Item", (), {"workload_class": "x", "body": {}})() for _ in range(8)]

        async def execute(request_id, workload_class, body, scheduled_ns, timeout_s, authority, phase):
            nonlocal active, maximum
            async with lock:
                active += 1
                maximum = max(maximum, active)
            await asyncio.sleep(0.01)
            async with lock:
                active -= 1
            now = time.perf_counter_ns()
            return RequestObservation(request_id=request_id, workload_class=workload_class, phase=phase,
                                      t_scheduled_ns=scheduled_ns, t_submit_ns=scheduled_ns,
                                      t_first_token_ns=now, t_complete_ns=now, success=True, output_tokens=1)

        await _closed_loop(items, execute, time.perf_counter_ns(), 3, 3, 1, "none", "measurement")
        self.assertEqual(maximum, 3)

    async def test_closed_loop_replenishes_from_shared_queue_for_heterogeneous_work(self) -> None:
        active = 0
        intervals: list[tuple[int, int]] = []
        lock = asyncio.Lock()
        items = [
            WorkloadItem(str(index), "slow" if index % 2 == 0 else "fast", {})
            for index in range(6)
        ]

        async def execute(request_id, workload_class, body, scheduled_ns, timeout_s, authority, phase):
            nonlocal active
            start = time.perf_counter_ns()
            async with lock:
                active += 1
                self.assertLessEqual(active, 2)
            await asyncio.sleep(0.04 if workload_class == "slow" else 0.001)
            end = time.perf_counter_ns()
            async with lock:
                active -= 1
            intervals.append((start, end))
            return RequestObservation(
                request_id=request_id, workload_class=workload_class, phase=phase,
                t_scheduled_ns=scheduled_ns, t_submit_ns=start,
                t_first_token_ns=end, t_complete_ns=end, success=True,
                output_tokens=1, token_timing_authority="none",
            )

        rows = await _closed_loop(
            items, execute, time.perf_counter_ns(), 2, 2, 1, "none", "measurement"
        )
        summary = summarize(rows)
        self.assertEqual(len(rows), 6)
        self.assertEqual(summary["load_realization"]["peak_in_flight"], 2)
        self.assertGreater(
            summary["load_realization"]["mean_in_flight_before_final_submission"], 1.8
        )

    async def test_retry_attempt_history_is_not_erased(self) -> None:
        calls = 0

        async def execute(*args):
            nonlocal calls
            calls += 1
            now = time.perf_counter_ns()
            if calls == 1:
                return RequestObservation(
                    "r", "x", "measurement", now, now,
                    t_error_ns=now + 1, status_code=503,
                    error_type="http_error", error_message="injected",
                )
            return RequestObservation(
                "r", "x", "measurement", now, now,
                t_first_token_ns=now + 1, t_complete_ns=now + 2,
                status_code=200, success=True, output_tokens=1,
            )

        row = await _execute_with_retries(
            execute, (), 2, 0, {"http_503"}
        )
        self.assertTrue(row.success)
        self.assertEqual(row.attempts, 2)
        self.assertEqual([item["status_code"] for item in row.attempt_history], [503, 200])
        self.assertLess(row.t_submit_ns, row.attempt_history[1]["t_submit_ns"])

    async def test_timeout_remains_visible_without_retry(self) -> None:
        now = time.perf_counter_ns()

        async def execute(*args):
            return RequestObservation(
                "r", "x", "measurement", now, now,
                t_error_ns=now + 1, timed_out=True, error_type="timeout",
            )

        row = await _execute_with_retries(execute, (), 1, 0, {"timeout"})
        self.assertTrue(row.timed_out)
        self.assertFalse(row.success)
        self.assertEqual(row.attempts, 1)
        self.assertEqual(row.attempt_history[0]["error_type"], "timeout")


class EvidenceTests(unittest.TestCase):
    def test_calibrated_run_verifies_and_tamper_is_detected(self) -> None:
        contracts = load_contracts(EXAMPLE)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            calibration_dir = root / "calibration"
            asyncio.run(calibrate(contracts, calibration_dir))
            reference = load_calibration(calibration_dir, contracts.measurement_identity)
            with DeterministicServer() as server:
                result = asyncio.run(execute_load_point(contracts, server.endpoint))
                bundle = write_bundle(root / "run", contracts, result, server.endpoint, reference)
            verification = verify_bundle(bundle, calibration_source=calibration_dir)
            self.assertTrue(verification["ok"])
            self.assertTrue(
                verification["verification_scope"]["calibration_source_manifest_verified"]
            )
            self.assertFalse(verification["verification_scope"]["producer_identity_attested"])
            with (bundle / "observations.jsonl").open("a") as handle:
                handle.write("{}\n")
            self.assertIn("hash_mismatch:observations.jsonl", verify_bundle(bundle)["errors"])

    def test_unsigned_verification_states_its_boundary(self) -> None:
        contracts = load_contracts(EXAMPLE)
        now = time.perf_counter_ns()
        row = RequestObservation(
            "m", "x", "measurement", now, now,
            t_first_token_ns=now + 1, t_complete_ns=now + 2,
            success=True, output_tokens=1,
        )
        with tempfile.TemporaryDirectory() as raw:
            bundle = write_bundle(
                Path(raw) / "run", contracts, RunResult([row], now, now + 2),
                "local://fixture", None, require_calibration=False,
            )
            result = verify_bundle(bundle)
        self.assertTrue(result["ok"])
        self.assertTrue(result["verification_scope"]["internal_consistency"])
        self.assertFalse(result["verification_scope"]["detached_signature_verified"])
        self.assertIn("does not attest who ran", result["note"])

    def test_external_calibration_manifest_mismatch_is_detected(self) -> None:
        contracts = load_contracts(EXAMPLE)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            calibration_dir = root / "calibration"
            asyncio.run(calibrate(contracts, calibration_dir))
            reference = load_calibration(calibration_dir, contracts.measurement_identity)
            now = time.perf_counter_ns()
            row = RequestObservation(
                "m", "x", "measurement", now, now,
                t_first_token_ns=now + 1, t_complete_ns=now + 2,
                success=True, output_tokens=1,
            )
            bundle = write_bundle(
                root / "run", contracts, RunResult([row], now, now + 2),
                "local://fixture", reference,
            )
            fake_source = root / "fake-calibration"
            fake_source.mkdir()
            (fake_source / "manifest.json").write_text("{}\n")
            result = verify_bundle(bundle, calibration_source=fake_source)
        self.assertFalse(result["ok"])
        self.assertTrue(result["verification_scope"]["internal_consistency"])
        self.assertFalse(
            result["verification_scope"]["calibration_source_manifest_verified"]
        )
        self.assertIn("calibration_source_manifest_hash_mismatch", result["errors"])

    def test_verify_recomputes_contract_identity(self) -> None:
        contracts = load_contracts(EXAMPLE)
        now = time.perf_counter_ns()
        row = RequestObservation("m", "x", "measurement", now, now,
                                 t_first_token_ns=now + 1, t_complete_ns=now + 2,
                                 success=True, output_tokens=1)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            bundle = write_bundle(
                root / "run", contracts, RunResult([row], now, now + 2),
                "http://example.invalid/v1",
                {"record": {}, "calibration_record_sha256": canonical_sha256({})},
            )
            manifest_path = bundle / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            scenario_path = bundle / "contracts" / "scenario.json"
            scenario = json.loads(scenario_path.read_text())
            scenario["scenario_id"] = "tampered"
            scenario.pop("workload_classes")
            scenario_path.write_text(json.dumps(scenario, sort_keys=True, indent=2) + "\n")
            from oicap.contracts import file_sha256
            manifest["files"]["contracts/scenario.json"] = file_sha256(scenario_path)
            manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
            errors = verify_bundle(bundle)["errors"]
            self.assertIn("contract_schema_violation:scenario", errors)
            self.assertIn("contract_hashes_mismatch", errors)

    def test_calibration_ignores_workload_delay_injection(self) -> None:
        contracts = load_contracts(EXAMPLE)
        with tempfile.TemporaryDirectory() as raw:
            bundle = asyncio.run(calibrate(contracts, Path(raw) / "calibration"))
            record = json.loads((bundle / "calibration.json").read_text())
            self.assertLess(record["noise_resolution"]["ttft_ms"], 100)
            self.assertEqual(record["repetitions"], 2)
            self.assertEqual(len(record["noise_resolution_by_repetition"]), 2)
            tolerance = record["limits"]["noise_stability_tolerance_ms"]
            self.assertTrue(
                all(value <= tolerance for value in record["noise_resolution_range_ms"].values())
            )

    def test_think_time_calibration_uses_interactive_response_time_law(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            benchmark = root / "benchmark"
            benchmark.mkdir()
            for source in EXAMPLE.iterdir():
                if source.is_file():
                    (benchmark / source.name).write_bytes(source.read_bytes())
            scenario = yaml.safe_load((benchmark / "scenario.yaml").read_text())
            scenario["session"] = {"think_time_ms": 5}
            (benchmark / "scenario.yaml").write_text(yaml.safe_dump(scenario))
            contracts = load_contracts(benchmark)
            bundle = asyncio.run(calibrate(contracts, root / "calibration"))
            record = json.loads((bundle / "calibration.json").read_text())
        self.assertTrue(record["valid"])
        self.assertEqual(
            record["closed_loop_concurrency_check"],
            "interactive_response_time_law",
        )
        self.assertIsNotNone(record["expected_mean_in_flight"])
        self.assertGreater(record["closed_loop_concurrency_ratio"], 0.6)

    def test_overloaded_calibration_fixture_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            benchmark = root / "benchmark"
            benchmark.mkdir()
            for source in EXAMPLE.iterdir():
                if source.is_file():
                    (benchmark / source.name).write_bytes(source.read_bytes())
            scenario = yaml.safe_load((benchmark / "scenario.yaml").read_text())
            scenario["arrival"] = {
                "kind": "open_loop", "process": "constant", "rate_per_s": 1_000_000,
            }
            scenario.pop("session")
            (benchmark / "scenario.yaml").write_text(yaml.safe_dump(scenario))
            run = yaml.safe_load((benchmark / "run.yaml").read_text())
            run["warmup"]["requests"] = 0
            run["measurement"]["requests"] = 20
            run["max_in_flight"] = 1
            run["self_calibration"]["max_schedule_lag_p99_ms"] = 0
            run["self_calibration"]["noise_stability_tolerance_ms"] = 10_000
            (benchmark / "run.yaml").write_text(yaml.safe_dump(run))
            contracts = load_contracts(benchmark)
            bundle = asyncio.run(calibrate(contracts, root / "calibration"))
            record = json.loads((bundle / "calibration.json").read_text())
            self.assertFalse(record["valid"])
            self.assertTrue(
                {"schedule_lag_exceeded", "arrival_rate_not_realized"}
                & set(record["invalid_reasons"])
            )

    def test_calibration_is_bound_to_workload_hash(self) -> None:
        contracts = load_contracts(EXAMPLE)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            calibration_dir = root / "calibration"
            asyncio.run(calibrate(contracts, calibration_dir))
            modified_root = root / "modified"
            modified_root.mkdir()
            for source in EXAMPLE.iterdir():
                if source.is_file():
                    (modified_root / source.name).write_bytes(source.read_bytes())
            with (modified_root / "workload.jsonl").open("a") as handle:
                extra = json.loads((EXAMPLE / "workload.jsonl").read_text().splitlines()[0])
                extra["id"] = "hello-3"
                handle.write(json.dumps(extra, sort_keys=True) + "\n")
            modified = load_contracts(modified_root)
            with self.assertRaisesRegex(ValueError, "measurement identity"):
                load_calibration(calibration_dir, modified.measurement_identity)

    def test_warmup_is_recorded_but_excluded_from_summary(self) -> None:
        now = time.perf_counter_ns()
        warm = RequestObservation("w", "x", "warmup", now, now, t_first_token_ns=now + 1, t_complete_ns=now + 2,
                                  success=True, output_tokens=100)
        measured = RequestObservation("m", "x", "measurement", now, now, t_first_token_ns=now + 1,
                                      t_complete_ns=now + 2, success=True, output_tokens=1)
        result = RunResult([warm, measured], now, now + 2)
        contracts = load_contracts(EXAMPLE)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            bundle = write_bundle(root / "run", contracts, result, "http://example.invalid/v1", {"record": {}, "calibration_record_sha256": canonical_sha256({})})
            summary = json.loads((bundle / "summary.json").read_text())
            self.assertEqual(summary["throughput"]["output_tokens"], 1)
            self.assertEqual(summary["realized_workload_mix"], {"x": 1.0})
            self.assertEqual(len((bundle / "observations.jsonl").read_text().splitlines()), 2)

    def test_latency_distributions_exclude_failed_requests(self) -> None:
        now = time.perf_counter_ns()
        rows = [
            RequestObservation(
                f"ok-{index}", "x", "measurement", now, now,
                t_first_token_ns=now + 100_000_000,
                t_complete_ns=now + 110_000_000,
                success=True, output_tokens=1,
            )
            for index in range(3)
        ]
        rows.append(RequestObservation(
            "empty", "x", "measurement", now, now,
            t_complete_ns=now + 1_000_000,
            status_code=200, success=False,
            error_type="empty_or_non_substantive_response",
        ))
        value = summarize(rows)
        end_to_end = value["latency_ms"]["end_to_end"]
        self.assertEqual(value["requests"]["successful"], 3)
        self.assertEqual(end_to_end["count"], 3)
        self.assertEqual(end_to_end["population"], "successful_requests")
        self.assertAlmostEqual(end_to_end["mean"], 110.0)
        self.assertEqual(value["latency_ms"]["time_to_failure"]["count"], 1)

    def test_warmup_and_measurement_ids_are_distinct(self) -> None:
        contracts = load_contracts(EXAMPLE)
        with DeterministicServer() as server:
            result = asyncio.run(execute_load_point(contracts, server.endpoint))
        ids = [row.request_id for row in result.observations]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(sum(row.phase == "warmup" for row in result.observations), 2)
        self.assertEqual(sum(row.phase == "measurement" for row in result.observations), 8)
        self.assertGreater(result.runner_load["event_loop_lag_ms"]["sample_count"], 0)
        self.assertIsNotNone(result.runner_load["event_loop_lag_ms"]["p99"])

    def test_client_saturation_blocks_capacity_claim_but_not_as_slo_verdict(self) -> None:
        scenario = {"arrival": {"kind": "open_loop", "process": "constant", "rate_per_s": 100}}
        summary = {
            "latency_ms": {"schedule_lag": {"p99": 50}},
            "load_realization": {"achieved_submission_rate_per_s": 20},
        }
        calibration = {
            "record": {
                "limits": {
                    "max_schedule_lag_p99_ms": 10,
                    "min_arrival_rate_ratio": 0.98,
                }
            }
        }
        value = apparatus_assessment(scenario, summary, calibration)
        self.assertEqual(value["status"], "CLIENT_SATURATED")
        self.assertFalse(value["capacity_claim_permitted"])
        self.assertNotIn("slo_verdict", value)

    def test_low_closed_loop_mean_concurrency_invalidates_apparatus(self) -> None:
        scenario = {"arrival": {"kind": "closed_loop", "active_users": 2}}
        summary = {
            "latency_ms": {"schedule_lag": {"p99": 0}},
            "load_realization": {
                "achieved_submission_rate_per_s": None,
                "mean_in_flight_before_final_submission": 1.0,
            },
        }
        calibration = {"record": {"limits": {
            "max_schedule_lag_p99_ms": 10,
            "max_runner_process_cpu_percent_one_core": 100,
            "max_runner_system_cpu_percent": 100,
            "min_closed_loop_concurrency_ratio": 0.8,
            "min_arrival_rate_ratio": 0.98,
        }}}
        runner_load = {
            "runner_process_cpu_percent_one_core": 1,
            "runner_system_cpu_percent": 1,
        }
        value = apparatus_assessment(scenario, summary, calibration, runner_load)
        self.assertEqual(value["status"], "CLIENT_SATURATED")
        self.assertIn("closed_loop_concurrency_not_maintained", value["reasons"])

    def test_think_time_concurrency_uses_interactive_response_time_law(self) -> None:
        scenario = {
            "arrival": {"kind": "closed_loop", "active_users": 10},
            "session": {"think_time_ms": 100},
        }
        summary = {
            "latency_ms": {"schedule_lag": {"p99": 0}},
            "load_realization": {
                "achieved_submission_rate_per_s": None,
                "mean_in_flight_before_final_submission": 4.5,
                "mean_request_service_time_s": 0.1,
            },
        }
        calibration = {"record": {"limits": {
            "max_schedule_lag_p99_ms": 10,
            "max_runner_process_cpu_percent_one_core": 100,
            "max_runner_system_cpu_percent": 100,
            "min_closed_loop_concurrency_ratio": 0.8,
            "min_arrival_rate_ratio": 0.98,
        }}}
        runner_load = {
            "runner_process_cpu_percent_one_core": 1,
            "runner_system_cpu_percent": 1,
        }
        value = apparatus_assessment(scenario, summary, calibration, runner_load)
        self.assertEqual(value["status"], "VALID")
        self.assertEqual(
            value["closed_loop_concurrency_check"],
            "interactive_response_time_law",
        )
        self.assertAlmostEqual(value["expected_mean_in_flight"], 5.0)
        self.assertAlmostEqual(value["closed_loop_concurrency_ratio"], 0.9)

        summary["load_realization"]["mean_in_flight_before_final_submission"] = 3.0
        invalid = apparatus_assessment(scenario, summary, calibration, runner_load)
        self.assertEqual(invalid["status"], "CLIENT_SATURATED")
        self.assertIn("closed_loop_concurrency_not_maintained", invalid["reasons"])

    def test_cli_invalid_calibration_is_not_reported_ok(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            benchmark = root / "benchmark"
            benchmark.mkdir()
            for source in EXAMPLE.iterdir():
                if source.is_file():
                    (benchmark / source.name).write_bytes(source.read_bytes())
            run = yaml.safe_load((benchmark / "run.yaml").read_text())
            run["self_calibration"]["max_schedule_lag_p99_ms"] = 0
            (benchmark / "run.yaml").write_text(yaml.safe_dump(run))
            output = io.StringIO()
            with redirect_stdout(output), self.assertRaisesRegex(SystemExit, "2"):
                cli_main(["calibrate", str(benchmark), "--output", str(root / "cal")])
            result = json.loads(output.getvalue())
        self.assertFalse(result["ok"])
        self.assertTrue(result["command_completed"])
        self.assertFalse(result["calibration_valid"])
        self.assertIn("schedule_lag_exceeded", result["invalid_reasons"])

    def test_bundle_records_runner_load_without_dirty_path_names(self) -> None:
        contracts = load_contracts(EXAMPLE)
        now = time.perf_counter_ns()
        row = RequestObservation(
            "m", "x", "measurement", now, now,
            t_first_token_ns=now + 1, t_complete_ns=now + 2,
            success=True, output_tokens=1,
        )
        load = {
            "measurement_duration_s": 1.0,
            "runner_process_cpu_percent_one_core": 1.0,
            "runner_system_cpu_percent": 2.0,
        }
        with tempfile.TemporaryDirectory() as raw:
            bundle = write_bundle(
                Path(raw) / "run", contracts, RunResult([row], now, now + 2, load),
                "local://fixture", None, require_calibration=False,
            )
            environment = json.loads((bundle / "environment.json").read_text())
            recorded = json.loads((bundle / "runner_load.json").read_text())
            manifest = json.loads((bundle / "manifest.json").read_text())
        self.assertEqual(recorded, load)
        self.assertNotIn("git_status_paths", environment["code"])
        self.assertIn("git_status_entry_count", environment["code"])
        self.assertIn("runner_load.json", manifest["files"])

    def test_censored_observation_remains_in_reliability_summary(self) -> None:
        now = time.perf_counter_ns()
        value = summarize([
            RequestObservation(
                "c", "interactive", "measurement", now, now,
                t_error_ns=now + 1, censored=True, error_type="censored_at_run_end",
            )
        ])
        self.assertEqual(value["requests"]["total"], 1)
        self.assertEqual(value["requests"]["censored"], 1)
        self.assertEqual(value["requests"]["errors_by_type"], {"censored_at_run_end": 1})

    def test_workload_snapshot_tamper_is_detected(self) -> None:
        contracts = load_contracts(EXAMPLE)
        now = time.perf_counter_ns()
        row = RequestObservation(
            "m", "interactive", "measurement", now, now,
            t_first_token_ns=now + 1, t_complete_ns=now + 2,
            success=True, output_tokens=1,
        )
        with tempfile.TemporaryDirectory() as raw:
            bundle = write_bundle(
                Path(raw) / "run", contracts, RunResult([row], now, now + 2),
                "https://user:secret@example.invalid/v1?token=secret",
                None, require_calibration=False,
                invocation=["oicap", "run", "<benchmark>"],
            )
            manifest = json.loads((bundle / "manifest.json").read_text())
            self.assertEqual(manifest["endpoint"], "https://example.invalid/v1")
            self.assertNotIn("secret", (bundle / "manifest.json").read_text())
            (bundle / "inputs" / "workload.jsonl").write_text("tampered\n")
            errors = verify_bundle(bundle)["errors"]
            self.assertIn("workload_hash_mismatch", errors)

    def test_verify_rejects_manifest_path_traversal(self) -> None:
        contracts = load_contracts(EXAMPLE)
        now = time.perf_counter_ns()
        row = RequestObservation(
            "m", "interactive", "measurement", now, now,
            t_first_token_ns=now + 1, t_complete_ns=now + 2,
            success=True, output_tokens=1,
        )
        with tempfile.TemporaryDirectory() as raw:
            bundle = write_bundle(
                Path(raw) / "run", contracts, RunResult([row], now, now + 2),
                "local://fixture", None, require_calibration=False,
            )
            manifest_path = bundle / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["files"]["../outside"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
            self.assertIn("unsafe_path:../outside", verify_bundle(bundle)["errors"])

    def test_cli_end_to_end_emits_no_slo_verdict_or_secret(self) -> None:
        with tempfile.TemporaryDirectory() as raw, DeterministicServer() as server:
            root = Path(raw)
            calibration_dir = root / "calibration"
            run_dir = root / "run"
            output = io.StringIO()
            with redirect_stdout(output):
                cli_main(["calibrate", str(EXAMPLE), "--output", str(calibration_dir)])
            self.assertTrue(json.loads(output.getvalue())["ok"])
            output = io.StringIO()
            previous = os.environ.get("OICAP_API_KEY")
            os.environ["OICAP_API_KEY"] = "OICAP_TEST_SECRET_MUST_NOT_LEAK"
            try:
                with redirect_stdout(output):
                    cli_main([
                        "run", str(EXAMPLE), "--endpoint", server.endpoint,
                        "--calibration", str(calibration_dir), "--output", str(run_dir),
                    ])
            finally:
                if previous is None:
                    os.environ.pop("OICAP_API_KEY", None)
                else:
                    os.environ["OICAP_API_KEY"] = previous
            result = json.loads(output.getvalue())
            self.assertTrue(result["ok"])
            self.assertNotIn("slo_verdict", result)
            self.assertTrue(verify_bundle(run_dir)["ok"])
            self.assertTrue((run_dir / "schemas" / "run.schema.json").is_file())
            evidence_text = "\n".join(
                path.read_text(encoding="utf-8", errors="replace")
                for path in run_dir.rglob("*") if path.is_file()
            )
            self.assertNotIn("OICAP_TEST_SECRET_MUST_NOT_LEAK", evidence_text)


if __name__ == "__main__":
    unittest.main()
