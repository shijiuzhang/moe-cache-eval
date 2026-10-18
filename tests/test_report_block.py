"""Product-driven tests for the minimal reporting block (Appendix B.1)."""

from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from build_decode_operating_envelope import build_regime_rows  # noqa: E402
from build_paper_blocking_evidence import _toy_trace  # noqa: E402
from moe_controller.events import save_event_trace  # noqa: E402
from moe_controller.report_block import (  # noqa: E402
    FIELDS,
    FieldValue,
    answered_count,
    build_block,
    not_applicable_count,
    regime_fields,
    render_markdown,
)

FAKE_SHA = "0" * 64

# Labels of Appendix B.1 / §10.5, in order.
B1_LABELS = [
    "event unit", "retention decision", "intra-event order (if immediate)", "conformance trace",
    "templates per category", "distinct prompt heads / finals", "chat template applied",
    "decode steps recorded", "position-locked cohorts", "unique generated sequences",
    "positional token agreement", "expert Jaccard | low-text-overlap",
    "effect stable across position bands",
    "experts N, top-k, layers", "residency fraction rho", "cache scope", "union per layer-step",
    "capacity per layer", "r(s,l) = union / capacity", "concurrency", "service discipline",
    "miss denominator", "dedup credited to policy", "static fit source", "static quota rule",
    "initial pinned load counted",
    "offline bound reported", "forced-admission decomposition",
    "absolute bytes per output token", "bandwidth budget assumed",
]


def _saved_toy(tmp: str) -> Path:
    toy = _toy_trace()
    return save_event_trace(
        Path(tmp) / "toy",
        manifest={
            "model": {"num_layers": 3, "num_experts": 4, "top_k": 2},
            "conversion": {"batch_size": 1},
            "counts": {"logical_expert_assignments_before_dedup": int(toy.assignment_counts.sum())},
        },
        request_indices=toy.request_indices,
        scheduler_steps=toy.scheduler_steps,
        forward_cycles=toy.forward_cycles,
        phases=toy.phases,
        layer_ids=toy.layer_ids,
        token_counts=toy.token_counts,
        offsets=toy.offsets,
        expert_ids=toy.expert_ids,
        assignment_counts=toy.assignment_counts,
        gate_mass=toy.gate_mass,
    )


class FieldRegistryTests(unittest.TestCase):
    def test_fields_match_appendix_b1(self) -> None:
        self.assertEqual([label for _, _, label in FIELDS], B1_LABELS)
        self.assertEqual(len(FIELDS), 30)


class RegimeTests(unittest.TestCase):
    def test_reference_trace_per_layer(self) -> None:
        # 12 blocks at rho = 0.5 -> 6 blocks, 2 per layer; every event has 2 experts.
        fields = regime_fields(_toy_trace(), rho=0.5, scope="per_layer", trace_sha256=FAKE_SHA)
        self.assertEqual(fields["r_union_over_capacity"].value, {"mean": 1.0, "p95": 1.0, "fraction_gt_1": 0.0})
        self.assertEqual(fields["union_per_layer_step"].value, {"mean": 2.0, "p95": 2.0})

    def test_reference_trace_global(self) -> None:
        fields = regime_fields(_toy_trace(), rho=0.5, scope="global", trace_sha256=FAKE_SHA)
        self.assertAlmostEqual(fields["r_union_over_capacity"].value["mean"], 2 / 6)

    def test_per_layer_definitions_match_the_paper_regime_script(self) -> None:
        # rho = 0.4 gives 5 blocks -> quotas 2, 2, 1, so layer 2 events exceed their quota.
        with tempfile.TemporaryDirectory() as tmp:
            root = _saved_toy(tmp)
            (reference,) = build_regime_rows([root], rho=0.4)
            from moe_controller.events import load_event_trace

            fields = regime_fields(load_event_trace(root), rho=0.4, scope="per_layer", trace_sha256=FAKE_SHA)
        r = fields["r_union_over_capacity"].value
        self.assertAlmostEqual(r["mean"], reference["mean_union_to_capacity_ratio"])
        self.assertAlmostEqual(r["fraction_gt_1"], reference["event_over_capacity_fraction"])
        self.assertAlmostEqual(r["fraction_gt_1"], 1 / 3)
        self.assertAlmostEqual(fields["union_per_layer_step"].value["p95"], reference["p95_union"])
        self.assertAlmostEqual(fields["union_per_layer_step"].value["mean"], reference["mean_union"])


class BlockTests(unittest.TestCase):
    def test_paper_only_defaults_to_nr_and_counts_classes_separately(self) -> None:
        block = build_block(mode="paper_only", supplied={
            "concurrency": FieldValue("1", "answered", "Abstract", "text"),
            "static_fit_source": FieldValue("no static policy", "not_applicable", "Section 4", "text"),
        })
        self.assertEqual(answered_count(block), 1)
        self.assertEqual(not_applicable_count(block), 1)
        self.assertEqual(block["cache_scope"].kind, "NR")

    def test_artifact_provenance_must_cite_a_file_hash(self) -> None:
        with self.assertRaises(ValueError):
            build_block(mode="with_artifacts", supplied={
                "concurrency": FieldValue(1, "answered", "no hash", "execution")})
        block = build_block(mode="with_artifacts", supplied={
            "concurrency": FieldValue(1, "answered", f"x {FAKE_SHA}", "execution"),
            "static_quota_rule": FieldValue("no static policy", "not_applicable", f"y {FAKE_SHA}", "code_inspection"),
        })
        self.assertEqual(answered_count(block), 1)
        self.assertEqual(not_applicable_count(block), 1)
        self.assertEqual(block["event_unit"].kind, "NA")

    def test_mode_and_class_rules(self) -> None:
        bad = [
            ("paper_only", FieldValue(1, "answered", FAKE_SHA, "execution")),      # artifact provenance in paper mode
            ("paper_only", FieldValue("x", "NA", "")),                              # paper mode uses NR
            ("with_artifacts", FieldValue("1", "answered", "Abstract", "text")),    # text provenance with artifacts
            ("with_artifacts", FieldValue(1, "answered", FAKE_SHA, "")),            # answered without provenance
            ("with_artifacts", FieldValue("x", "NA", "", "execution")),             # NA with provenance
            ("with_artifacts", FieldValue(1, "computed", FAKE_SHA, "execution")),   # retired class
        ]
        for mode, value in bad:
            with self.assertRaises(ValueError, msg=(mode, value)):
                build_block(mode=mode, supplied={"concurrency": value})
        with self.assertRaises(ValueError):
            build_block(mode="with_artifacts", supplied={"not_a_field": FieldValue("x", "NA", "")})

    def test_regime_parameters_carry_their_own_provenance(self) -> None:
        fields = regime_fields(_toy_trace(), rho=0.5, scope="global", trace_sha256=FAKE_SHA,
                               parameter_provenance="code_inspection", parameter_source=f"simulator {FAKE_SHA}")
        self.assertEqual(fields["cache_scope"].provenance, "code_inspection")
        self.assertEqual(fields["union_per_layer_step"].provenance, "execution")

    def test_markdown_lists_every_field(self) -> None:
        text = render_markdown(build_block(mode="paper_only"), title="t")
        for label in B1_LABELS:
            self.assertIn(label, text)

    def test_provenance_table_rows_have_four_cells(self) -> None:
        # One B.1 label contains '|'; an unescaped pipe would add a column.
        text = render_markdown(build_block(mode="paper_only"), title="t")
        rows = [line for line in text.splitlines() if line.startswith("| ") and "class" not in line]
        self.assertEqual(len(rows), 30)
        for row in rows:
            self.assertEqual(len(re.split(r"(?<!\\)\|", row)) - 2, 4, row)


if __name__ == "__main__":
    unittest.main()
