from __future__ import annotations

import asyncio
import copy
import io
import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import yaml

from oicap.calibration import calibrate, load_calibration
from oicap.cli import main as cli_main
from oicap.contracts import ContractError, canonical_sha256, load_contracts
from oicap.evidence import apparatus_assessment, verify_bundle, write_bundle
from oicap.metrics import observation_metrics, summarize
from oicap.observations import RequestObservation
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
            with self.assertRaisesRegex(ContractError, "non-empty mapping"):
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
            with self.assertRaisesRegex(ContractError, "Unsupported"):
                load_contracts(root)

    def test_published_schema_documents_are_valid_json(self) -> None:
        schema_root = ROOT / "oicap" / "schemas" / "0.1"
        self.assertEqual(
            {path.name for path in schema_root.glob("*.json")},
            {"scenario.schema.json", "slo.schema.json", "sut.schema.json", "run.schema.json"},
        )
        for path in schema_root.glob("*.json"):
            self.assertEqual(json.loads(path.read_text())["$schema"],
                             "https://json-schema.org/draft/2020-12/schema")


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
            self.assertTrue(verify_bundle(bundle)["ok"])
            with (bundle / "observations.jsonl").open("a") as handle:
                handle.write("{}\n")
            self.assertIn("hash_mismatch:observations.jsonl", verify_bundle(bundle)["errors"])

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
            scenario_path.write_text(json.dumps(scenario, sort_keys=True, indent=2) + "\n")
            from oicap.contracts import file_sha256
            manifest["files"]["contracts/scenario.json"] = file_sha256(scenario_path)
            manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
            self.assertIn("contract_hashes_mismatch", verify_bundle(bundle)["errors"])

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

    def test_warmup_and_measurement_ids_are_distinct(self) -> None:
        contracts = load_contracts(EXAMPLE)
        with DeterministicServer() as server:
            result = asyncio.run(execute_load_point(contracts, server.endpoint))
        ids = [row.request_id for row in result.observations]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(sum(row.phase == "warmup" for row in result.observations), 2)
        self.assertEqual(sum(row.phase == "measurement" for row in result.observations), 8)

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
