from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from oicap.contracts import load_contracts
from oicap.translator import DEPLOYMENT_KEYS, TranslationError, translate_expert_draft


def valid_draft() -> dict:
    requirements = {
        key: {"requirement_state": "informational", "constraint": "record at run time"}
        for key in DEPLOYMENT_KEYS
    }
    requirements["model_identity"] = {
        "requirement_state": "required",
        "constraint": "local GGUF model and SHA-256",
    }
    requirements["quantization"] = {
        "requirement_state": "required",
        "constraint": "Q4_K_M",
    }
    requirements["batching_scheduling_admission"] = {
        "requirement_state": "required",
        "constraint": json.dumps(
            {
                "batching": "continuous",
                "admission": "engine-default",
                "preemption": "unknown",
            }
        ),
    }
    return {
        "schema": "oicap-ac04-intake-draft/0.1",
        "status": "READY_FOR_HUMAN_REVIEW",
        "validation": {"error_count": 0, "warning_count": 0, "errors": [], "warnings": []},
        "project": {
            "project_id": "public-alpha-example",
            "deployment_mode": "private_on_prem",
            "buyer_role": "acceptance owner",
            "technical_role": "test operator",
            "measurement_boundary": "buyer client to local OpenAI-compatible endpoint",
        },
        "sla_gates": [
            {
                "metric": "ttft_ms",
                "workload_class": "short-answer",
                "statistic": "p95",
                "comparator": "lte",
                "threshold": 30000,
                "unit": "ms",
                "population": "successful quality-eligible requests",
                "min_samples": 4,
                "min_duration_s": 1,
                "quality_eligible": True,
                "authority": "client_observed",
            },
            {
                "metric": "aggregate_output_tokens_per_second",
                "workload_class": "short-answer",
                "statistic": "mean",
                "comparator": "gte",
                "threshold": 1,
                "unit": "token/s",
                "population": "successful requests with server usage",
                "min_samples": 4,
                "min_duration_s": 1,
                "quality_eligible": True,
                "authority": "server_usage",
            },
        ],
        "workload_classes": [
            {
                "class_id": "short-answer",
                "weight_percent": 100,
                "input_tokens": "1-64",
                "output_tokens": "1-32",
                "source_policy": "public synthetic",
                "session_semantics": "single_turn",
                "buyer_mean_request_cycle_seconds": 2,
                "think_time_ms": 1000,
                "streaming": "required",
                "quality_rule": "non-empty response; not executed by alpha1",
            }
        ],
        "deployment_requirements": requirements,
        "execution": {
            "load_semantics": "closed_loop",
            "max_load": 2,
            "repeats": 2,
            "site_window_minutes": 10,
            "min_point_duration_s": 1,
            "min_point_samples": 4,
            "load_points": [1, 2],
            "max_retests": 1,
            "mutable_paths": "none",
            "preflight": {
                "max_load_sustained": True,
                "resource_recorded": True,
                "onsite_same_path_calibration": True,
                "buyer_controls_responder": True,
            },
        },
    }


class TranslatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.expert = self.root / "expert.json"
        self.workload = self.root / "workload.jsonl"
        self.workload.write_text(
            json.dumps(
                {
                    "id": "one",
                    "workload_class": "short-answer",
                    "body": {
                        "model": "local",
                        "messages": [{"role": "user", "content": "Answer only OK."}],
                        "temperature": 0,
                        "max_tokens": 8,
                        "stream_options": {"include_usage": True},
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_draft(self, draft: dict) -> None:
        self.expert.write_text(json.dumps(draft), encoding="utf-8")

    def translate(self, draft: dict, **kwargs):
        self.write_draft(draft)
        return translate_expert_draft(
            self.expert,
            self.workload,
            self.root / "benchmark",
            load_point=kwargs.pop("load_point", 2),
            **kwargs,
        )

    def test_valid_closed_loop_draft_emits_loadable_contracts_and_honest_report(self) -> None:
        output = self.translate(valid_draft())
        contracts = load_contracts(output)
        self.assertEqual(contracts.scenario["arrival"], {"kind": "closed_loop", "active_users": 2})
        self.assertEqual(contracts.scenario["session"], {"think_time_ms": 1000.0})
        self.assertEqual(contracts.run["measurement"]["requests"], 4)
        self.assertEqual(contracts.run["token_accounting"]["authority"], "server_usage")
        report = json.loads((output / "translation-report.json").read_text())
        self.assertFalse(report["formal_procurement_verdict_enabled"])
        self.assertIn("service_sla_verdict", report["not_included"])
        self.assertIn("quality_gate_execution", report["not_included"])
        self.assertEqual(len(report["source_expert_draft_sha256"]), 64)
        self.assertEqual(report["emitted_contract_identity"], contracts.identity)
        self.assertEqual(
            report["think_time_review"]["short-answer"],
            {"buyer_mean_request_cycle_seconds": 2.0, "reviewed_think_time_ms": 1000.0},
        )

    def test_missing_think_time_is_rejected_instead_of_defaulting_to_zero(self) -> None:
        draft = valid_draft()
        del draft["workload_classes"][0]["think_time_ms"]
        with self.assertRaisesRegex(TranslationError, "think_time_ms"):
            self.translate(draft)

    def test_unfinished_draft_is_rejected(self) -> None:
        draft = valid_draft()
        draft["status"] = "DRAFT_WITH_ERRORS"
        with self.assertRaisesRegex(TranslationError, "not READY_FOR_HUMAN_REVIEW"):
            self.translate(draft)

    def test_workload_class_mismatch_is_rejected(self) -> None:
        self.workload.write_text(
            '{"id":"one","workload_class":"wrong","body":{"model":"local"}}\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(TranslationError, "Workload class set differs"):
            self.translate(valid_draft())

    def test_undeclared_load_point_is_rejected(self) -> None:
        with self.assertRaisesRegex(TranslationError, "not declared"):
            self.translate(valid_draft(), load_point=3)

    def test_multiple_points_require_selection(self) -> None:
        self.write_draft(valid_draft())
        with self.assertRaisesRegex(TranslationError, "select one"):
            translate_expert_draft(self.expert, self.workload, self.root / "benchmark")

    def test_plain_text_service_discipline_is_rejected(self) -> None:
        draft = valid_draft()
        draft["deployment_requirements"]["batching_scheduling_admission"]["constraint"] = (
            "continuous batching"
        )
        with self.assertRaisesRegex(TranslationError, "must be JSON"):
            self.translate(draft)

    def test_authoritative_token_gate_is_rejected(self) -> None:
        draft = valid_draft()
        draft["sla_gates"][0]["authority"] = "authoritative_token_timestamps"
        with self.assertRaisesRegex(TranslationError, "no authoritative per-token"):
            self.translate(draft)

    def test_quality_hook_gate_is_rejected(self) -> None:
        draft = valid_draft()
        draft["sla_gates"][0]["authority"] = "quality_hook"
        with self.assertRaisesRegex(TranslationError, "no locked quality-hook"):
            self.translate(draft)

    def test_open_loop_requires_max_in_flight(self) -> None:
        draft = valid_draft()
        draft["execution"]["load_semantics"] = "open_loop"
        with self.assertRaisesRegex(TranslationError, "requires --max-in-flight"):
            self.translate(draft)

    def test_open_loop_emits_constant_arrival_without_session(self) -> None:
        draft = valid_draft()
        draft["execution"]["load_semantics"] = "open_loop"
        output = self.translate(draft, max_in_flight=4)
        scenario = load_contracts(output).scenario
        self.assertEqual(
            scenario["arrival"],
            {"kind": "open_loop", "process": "constant", "rate_per_s": 2.0},
        )
        self.assertNotIn("session", scenario)

    def test_existing_output_is_not_overwritten(self) -> None:
        output = self.root / "benchmark"
        output.mkdir()
        self.write_draft(valid_draft())
        with self.assertRaisesRegex(TranslationError, "already exists"):
            translate_expert_draft(
                self.expert, self.workload, output, load_point=2
            )


if __name__ == "__main__":
    unittest.main()
