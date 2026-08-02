from __future__ import annotations

import importlib.util
import hashlib
import json
import unittest
from pathlib import Path

import numpy as np

from moe_controller.simulation import simulate_event_atomic


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_paper_blocking_evidence.py"
SPEC = importlib.util.spec_from_file_location("paper_evidence", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

EXTERNAL_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "audit_external_route_contamination.py"
)
EXTERNAL_SPEC = importlib.util.spec_from_file_location(
    "external_route_audit", EXTERNAL_SCRIPT
)
assert EXTERNAL_SPEC is not None and EXTERNAL_SPEC.loader is not None
EXTERNAL_MODULE = importlib.util.module_from_spec(EXTERNAL_SPEC)
EXTERNAL_SPEC.loader.exec_module(EXTERNAL_MODULE)

GAP_ARTIFACT = (
    Path(__file__).resolve().parents[1]
    / "analysis"
    / "paper-gap-invariance-workload-composition-v2"
)
NATURAL_CONTAMINATION_ARTIFACT = (
    Path(__file__).resolve().parents[1]
    / "analysis"
    / "external-route-contamination-allenai-mixtral-c4-v1"
    / "manifest.json"
)
SYNTHETIC_CONTAMINATION_ARTIFACT = (
    Path(__file__).resolve().parents[1]
    / "analysis"
    / "external-route-contamination-allenai-mixtral-c4-synthetic-prefix64-v1"
    / "manifest.json"
)
STATIC_PROTOCOL_ARTIFACT = (
    Path(__file__).resolve().parents[1]
    / "analysis"
    / "paper-static-baseline-protocol-v1"
)


class PaperEvidenceTests(unittest.TestCase):
    def test_toy_trace_is_human_checkable(self) -> None:
        trace = MODULE._toy_trace()
        trace.validate()
        result = simulate_event_atomic(
            trace,
            policy="lru",
            capacity_blocks=6,
            cache_scope="per_layer",
            tie_seed=7,
            include_event_misses=True,
        )
        self.assertEqual(result.hits, 12)
        self.assertEqual(result.misses, 18)
        self.assertEqual(
            result.event_misses,
            (2, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1),
        )

    def test_step_permutation_preserves_union_distribution(self) -> None:
        trace = MODULE._toy_trace()
        permuted = MODULE._permute_step_groups(trace, MODULE.np.asarray([4, 2, 0, 3, 1]))
        original_lengths = MODULE.np.sort(MODULE.np.diff(trace.offsets))
        permuted_lengths = MODULE.np.sort(MODULE.np.diff(permuted.offsets))
        MODULE.np.testing.assert_array_equal(original_lengths, permuted_lengths)

    def test_synthetic_contamination_positive_control(self) -> None:
        tokens = [np.arange(12), np.arange(100, 112)]
        routes = [
            np.arange(24).reshape(12, 1, 2),
            np.arange(100, 124).reshape(12, 1, 2),
        ]
        copied = EXTERNAL_MODULE._inject_shared_prefix(tokens, routes, 4)
        self.assertEqual(copied, 4)
        np.testing.assert_array_equal(tokens[0][:4], tokens[1][:4])
        np.testing.assert_array_equal(routes[0][:4], routes[1][:4])
        self.assertFalse(np.array_equal(tokens[0][4:], tokens[1][4:]))

    def test_gap_invariance_v2_freezes_semantic_conditions(self) -> None:
        manifest = json.loads((GAP_ARTIFACT / "manifest.json").read_text())
        specs = json.loads((GAP_ARTIFACT / "condition-specs.json").read_text())
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["generator"], "scripts/build_paper_gap_invariance.py")
        self.assertEqual(len(specs), 13)
        self.assertAlmostEqual(manifest["gap_min"], 0.44177430907159965)
        self.assertAlmostEqual(manifest["gap_max"], 0.45929495308141005)
        for released in specs:
            claimed = released["sha256"]
            semantic = {key: value for key, value in released.items() if key != "sha256"}
            encoded = json.dumps(
                semantic,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            self.assertEqual(hashlib.sha256(encoded).hexdigest(), claimed)

    def test_external_contamination_detector_has_both_controls(self) -> None:
        natural = json.loads(NATURAL_CONTAMINATION_ARTIFACT.read_text())
        synthetic = json.loads(SYNTHETIC_CONTAMINATION_ARTIFACT.read_text())
        self.assertFalse(natural["summary"]["contamination_flag"])
        self.assertTrue(synthetic["summary"]["contamination_flag"])
        self.assertEqual(
            synthetic["synthetic_transformation"]["prefix_tokens"], 64
        )
        self.assertGreater(
            synthetic["summary"]["token_positional_agreement_mean"],
            natural["summary"]["token_positional_agreement_mean"] * 10,
        )
        self.assertGreater(
            synthetic["summary"]["expert_jaccard_mean"],
            natural["summary"]["expert_jaccard_mean"],
        )

    def test_static_protocols_are_named_and_frozen_separately(self) -> None:
        manifest = json.loads(
            (STATIC_PROTOCOL_ARTIFACT / "manifest.json").read_text()
        )
        rows = (
            STATIC_PROTOCOL_ARTIFACT / "static-protocol-comparison.csv"
        ).read_text()
        self.assertEqual(manifest["status"], "complete_posthoc_protocol_audit")
        self.assertIn("static_same_trace", rows)
        self.assertIn("static_frozen", rows)
        self.assertAlmostEqual(
            manifest["relative_frozen_vs_same_trace_transfer_penalty"],
            0.014028111851723429,
        )


if __name__ == "__main__":
    unittest.main()
