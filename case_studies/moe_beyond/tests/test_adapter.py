"""Product-driven tests for the MoE-Beyond adapter and probe writer.

Every assertion calls the adapter or probe code itself.  Expected values come
from the third-party file format, from hand-checkable constructions, or from
the frozen pre-registration; none come from an analysis result.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

CASE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = CASE_DIR.parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(CASE_DIR))

import adapter  # noqa: E402
import probes  # noqa: E402
from moe_controller.convert import convert_decode_trace  # noqa: E402
from moe_controller.events import PHASE_PREFILL, load_event_trace  # noqa: E402

# Five hand-written rows in the published predicted-CSV format, including its
# CRLF line endings and minimal quoting (only fields containing a comma).
HANDWRITTEN = (
    "Layer ID,Token,Activated Expert IDs,Predicted Expert IDs\r\n"
    '1,0,"[8, 26, 43, 56, 57, 60]","[8, 26, 43, 56, 57, 60]"\r\n'
    '1,1,"[8, 22, 25, 43, 46, 63]","[8, 22, 43, 46, 56, 63]"\r\n'
    '2,0,"[0, 1, 2, 3, 4, 5]",[]\r\n'
    '2,1,"[5, 10, 20, 30, 40, 50]","[1, 2]"\r\n'
    '3,0,"[7, 9, 11, 13, 15, 17]",[7]\r\n'
)


def _full_prompt_rows(per_layer_sets):
    """Rows for a well-formed 26-layer prompt; per_layer_sets[t] is used in every layer."""
    return [
        (layer, experts, ())
        for layer in range(1, 27)
        for experts in per_layer_sets
    ]


class RoundTripTests(unittest.TestCase):
    def test_handwritten_rows_round_trip_byte_for_byte(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "hand.csv"
            source.write_bytes(HANDWRITTEN.encode("utf-8"))
            rows = list(adapter.load_raw(source))
            self.assertEqual(len(rows), 5)
            self.assertEqual(rows[0].experts, (8, 26, 43, 56, 57, 60))
            self.assertEqual(rows[2].predicted, ())
            self.assertEqual(rows[3].src_row, 5)
            rewritten = adapter.to_moebeyond_format(
                [(r.layer, r.experts, r.predicted) for r in rows], Path(tmp) / "out.csv"
            )
            self.assertEqual(rewritten.read_bytes(), source.read_bytes())


class ValidationTests(unittest.TestCase):
    def _write(self, tmp: str, rows) -> Path:
        return adapter.to_moebeyond_format(rows, Path(tmp) / "p.csv")

    def test_well_formed_prompt_has_no_violations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(tmp, _full_prompt_rows([(0, 1, 2, 3, 4, 5), (6, 7, 8, 9, 10, 11)]))
            trace = adapter.parse_prompt_file(path, request_id="r")
            self.assertEqual(trace.violations, {})
            self.assertEqual(trace.experts.shape, (26, 2, 6))
            self.assertEqual(trace.experts[25, 1].tolist(), [6, 7, 8, 9, 10, 11])
            self.assertIsNone(trace.tokens)

    def test_violations_are_counted_not_dropped(self) -> None:
        rows = _full_prompt_rows([(0, 1, 2, 3, 4, 5)])
        rows[0] = (1, (0, 1, 2, 3, 4), ())          # five experts
        rows[1] = (2, (0, 0, 2, 3, 4, 5), ())       # duplicate expert
        rows[2] = (3, (0, 1, 2, 3, 4, 64), ())      # out of range
        rows = [row for row in rows if row[0] != 26]  # missing layer 26
        with tempfile.TemporaryDirectory() as tmp:
            trace = adapter.parse_prompt_file(self._write(tmp, rows), request_id="r")
        self.assertEqual(
            trace.violations,
            {
                "row_not_exactly_top_k": 1,
                "row_duplicate_expert": 1,
                "expert_id_out_of_range": 1,
                "layer_set_not_1_to_26": 1,
            },
        )

    def test_canonical_writers_refuse_traces_with_violations(self) -> None:
        rows = _full_prompt_rows([(0, 1, 2, 3, 4, 5)])
        rows[0] = (1, (0, 1, 2, 3, 4), ())
        with tempfile.TemporaryDirectory() as tmp:
            trace = adapter.parse_prompt_file(self._write(tmp, rows), request_id="r")
            with self.assertRaises(ValueError):
                adapter.build_e2_trace([trace], Path(tmp) / "e2", dataset_label="x")
            with self.assertRaises(ValueError):
                adapter.write_e1_source([trace], Path(tmp) / "e1", dataset_label="x")


class BijectionTests(unittest.TestCase):
    def _trace(self, tmp: str, name: str, sets) -> adapter.PromptTrace:
        path = adapter.to_moebeyond_format(_full_prompt_rows(sets), Path(tmp) / f"{name}.csv")
        return adapter.parse_prompt_file(path, request_id=name)

    def test_renumbered_files_are_matched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a = self._trace(tmp, "a", [(0, 1, 2, 3, 4, 5)])
            b = self._trace(tmp, "b", [(6, 7, 8, 9, 10, 11)])
            # Within-row order differs (ascending vs router order); sets are equal.
            b_reordered = self._trace(tmp, "b2", [(11, 10, 9, 8, 7, 6)])
            mapping = adapter.match_by_signature({1: a, 2: b}, {7: b_reordered, 9: a})
        self.assertEqual(mapping, {1: 9, 2: 7})

    def test_ambiguous_matching_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a = self._trace(tmp, "a", [(0, 1, 2, 3, 4, 5)])
            a_copy = self._trace(tmp, "a2", [(0, 1, 2, 3, 4, 5)])
            with self.assertRaises(ValueError):
                adapter.match_by_signature({1: a}, {1: a, 2: a_copy})


class TextTests(unittest.TestCase):
    def test_prompt_text_reconstruction_rule(self) -> None:
        tokens = [adapter.BOS_TOKEN, "what", "Ġis", "Ġit", "?", "Ċ", "ok"]
        self.assertEqual(adapter.reconstruct_prompt_text(tokens), "what is it?\nok")


class CanonicalFormatTests(unittest.TestCase):
    def test_e2_event_is_union_over_prompt_positions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = adapter.to_moebeyond_format(
                _full_prompt_rows([(0, 1, 2, 3, 4, 5), (3, 4, 5, 6, 7, 8)]), Path(tmp) / "p.csv"
            )
            trace = adapter.parse_prompt_file(path, request_id="r")
            root = adapter.build_e2_trace([trace], Path(tmp) / "e2", dataset_label="x")
            events = load_event_trace(root)
        self.assertEqual(events.num_events, 26)
        first = events.event(0)
        self.assertEqual(first.expert_ids.tolist(), [0, 1, 2, 3, 4, 5, 6, 7, 8])
        self.assertEqual(first.assignment_counts.tolist(), [1, 1, 1, 2, 2, 2, 1, 1, 1])
        self.assertEqual(int(events.token_counts[0]), 2)
        self.assertTrue(np.all(events.phases == PHASE_PREFILL))
        self.assertEqual(events.manifest["counts"]["logical_expert_assignments_before_dedup"], 26 * 12)

    def test_e1_source_is_consumed_by_the_package_fcfs_builder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            traces = []
            for name, sets in (("r1", [(0, 1, 2, 3, 4, 5)] * 3), ("r2", [(6, 7, 8, 9, 10, 11)] * 2)):
                path = adapter.to_moebeyond_format(_full_prompt_rows(sets), Path(tmp) / f"{name}.csv")
                traces.append(adapter.parse_prompt_file(path, request_id=name))
            source = adapter.write_e1_source(traces, Path(tmp) / "src", dataset_label="x")
            manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["collection"]["physical_phase"], "prefill")
            out = convert_decode_trace(
                source, Path(tmp) / "b1", batch_size=1, queue_order="source", category_field="source_dataset"
            )
            events = load_event_trace(out)
        # B = 1: one event per (position, layer), each with exactly the six row experts.
        self.assertEqual(events.num_events, (3 + 2) * 26)
        self.assertTrue(np.all(np.diff(events.offsets) == 6))
        self.assertEqual(events.manifest["counts"]["logical_expert_assignments_before_dedup"], 5 * 26 * 6)


class ProbeTests(unittest.TestCase):
    def test_probe_files_and_expectations_follow_prereg_p1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            expected = probes.write_probes(Path(tmp))
            a2_rows = list(adapter.load_raw(Path(tmp) / "A2.csv"))
            a1_rows = list(adapter.load_raw(Path(tmp) / "A1.csv"))
        self.assertEqual([r.experts for r in a2_rows], [(63,), (0, 1, 2), (0, 1, 2)])
        self.assertTrue(all(r.predicted == () for r in a2_rows))
        self.assertEqual(expected["A0"]["capacity_blocks"], 3)
        self.assertEqual(expected["A2"]["capacity_blocks"], 2)
        self.assertEqual(expected["A1"]["capacity_blocks"], 6)
        self.assertEqual(
            expected["A2"]["expected_probe_counts"],
            {"event_level_retention": {"hits": 2, "misses": 4}, "per_access_retention": {"hits": 0, "misses": 6}},
        )
        self.assertEqual(expected["A1"]["sentinel_contribution"], {"hits": 1, "misses": 2})
        # A1: each of layers 1-3 starts with the sentinel, followed by the §2.5 sets.
        layer1 = [r.experts for r in a1_rows if r.layer == 1]
        self.assertEqual(layer1, [(63,), (0, 1), (0, 2), (0, 1), (0, 3), (0, 1)])


if __name__ == "__main__":
    unittest.main()
