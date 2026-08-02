from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from measure_victim_rank_quality import (  # noqa: E402
    cluster_bootstrap,
    rankdata_average,
    spearman_tied,
)

ARTIFACT = ROOT / "analysis" / "paper-victim-rank-quality-v2"


class RankStatisticsTests(unittest.TestCase):
    def test_rankdata_average_handles_ties(self) -> None:
        got = rankdata_average(np.array([10.0, 20.0, 20.0, 40.0]))
        np.testing.assert_allclose(got, [1.0, 2.5, 2.5, 4.0])

    def test_rankdata_all_tied(self) -> None:
        got = rankdata_average(np.array([7.0, 7.0, 7.0]))
        np.testing.assert_allclose(got, [2.0, 2.0, 2.0])

    def test_spearman_perfect_and_inverted(self) -> None:
        a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertAlmostEqual(spearman_tied(a, a), 1.0, places=9)
        self.assertAlmostEqual(spearman_tied(a, a[::-1]), -1.0, places=9)

    def test_spearman_is_tie_aware(self) -> None:
        """A constant vector has no rank variance; correlation is undefined."""
        a = np.array([1.0, 2.0, 3.0, 4.0])
        const = np.array([5.0, 5.0, 5.0, 5.0])
        self.assertTrue(np.isnan(spearman_tied(a, const)))

    def test_spearman_ties_do_not_inflate_agreement(self) -> None:
        """Average ranks must not let an arbitrary tie order create signal."""
        pred = np.array([1.0, 2.0, 3.0, 4.0])
        true_ = np.array([9.0, 9.0, 9.0, 1.0])
        first = spearman_tied(pred, true_)
        # permuting the tied block must not change the statistic
        second = spearman_tied(pred, np.array([9.0, 9.0, 9.0, 1.0])[[2, 1, 0, 3]])
        self.assertAlmostEqual(first, second, places=12)

    def test_spearman_too_few_points(self) -> None:
        self.assertTrue(np.isnan(spearman_tied(np.array([1.0, 2.0]), np.array([2.0, 1.0]))))

    def test_cluster_bootstrap_brackets_the_mean(self) -> None:
        rng = np.random.default_rng(0)
        clusters = np.repeat(np.arange(60), 8)
        values = rng.normal(0.4, 0.05, size=clusters.size)
        lo, hi = cluster_bootstrap(values, clusters, reps=300, seed=1)
        self.assertLess(lo, values.mean())
        self.assertGreater(hi, values.mean())


class VictimRankArtifactTests(unittest.TestCase):
    """Guard the reported numbers against silent drift."""

    @classmethod
    def setUpClass(cls) -> None:
        if not (ARTIFACT / "manifest.json").exists():
            raise unittest.SkipTest("victim-rank artifact not built")
        cls.m = json.loads((ARTIFACT / "manifest.json").read_text())

    def test_tie_handling_is_documented(self) -> None:
        self.assertIn("optimal victim set", self.m["config"]["tie_handling"])
        self.assertEqual(self.m["config"]["replay"], "event_atomic")

    def test_inputs_are_hashed(self) -> None:
        for key in ("fit_manifest_sha256", "eval_manifest_sha256"):
            self.assertRegex(self.m["inputs"][key], r"^[0-9a-f]{64}$")
        self.assertRegex(
            self.m["artifacts"]["decisions_csv_sha256"], r"^[0-9a-f]{64}$"
        )

    def test_optimal_sets_are_mostly_singletons(self) -> None:
        """If ties were common the hit-rate comparison would be misleading."""
        self.assertLess(self.m["counts"]["mean_optimal_set_size"], 2.0)

    def test_predictor_is_far_below_causal_baselines(self) -> None:
        s = self.m["summary"]
        self.assertLess(s["pred_hits_optimal"]["ci95_high"],
                        s["lru_hits_optimal"]["ci95_low"])
        self.assertLess(s["pred_hits_optimal"]["ci95_high"],
                        s["lfru_hits_optimal"]["ci95_low"])

    def test_rank_correlation_is_negative_with_and_without_sentinels(self) -> None:
        s = self.m["summary"]
        self.assertLess(s["spearman_all"]["ci95_high"], 0.0)
        self.assertLess(s["spearman_finite"]["ci95_high"], 0.0)

    def test_confidence_intervals_bracket_their_means(self) -> None:
        for key, stat in self.m["summary"].items():
            self.assertLessEqual(stat["ci95_low"], stat["mean"], key)
            self.assertGreaterEqual(stat["ci95_high"], stat["mean"], key)


if __name__ == "__main__":
    unittest.main()
