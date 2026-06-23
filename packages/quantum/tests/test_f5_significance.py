"""Step 5 (F5) — additive significance testing.

V5: below MIN_TRADES_SIGNIFICANCE → insufficient_n (no claim); above → CI +
    p-value. The function is PURE (no DB, no calibration action) — additive only.
"""

import unittest

from packages.quantum.jobs.handlers.post_trade_learning import (
    compute_edge_significance,
    MIN_TRADES_SIGNIFICANCE,
)


class TestEdgeSignificance(unittest.TestCase):
    def test_below_floor_insufficient_n(self):  # V5 below
        r = compute_edge_significance([1.0, -1.0, 2.0], [0.5, 0.5, 0.5])
        self.assertTrue(r["insufficient_n"])
        self.assertNotIn("alpha_p_value", r)
        self.assertNotIn("win_rate_ci95", r)
        self.assertEqual(r["n"], 3)

    def test_above_floor_has_ci_and_pvalue(self):  # V5 above
        n = MIN_TRADES_SIGNIFICANCE + 5
        # realistic: all wins, positive alpha mean ~8 with non-zero dispersion
        realized = [8.0 + (1.0 if i % 2 else -1.0) for i in range(n)]
        predicted = [0.0] * n
        r = compute_edge_significance(realized, predicted)
        self.assertFalse(r["insufficient_n"])
        self.assertIn("win_rate_ci95", r)
        self.assertIn("alpha_p_value", r)        # scipy present, se > 0
        self.assertIn("alpha_significant", r)
        self.assertEqual(r["win_rate"], 1.0)
        lo, hi = r["win_rate_ci95"]
        self.assertLessEqual(lo, 1.0)
        self.assertLessEqual(hi, 1.0)
        # a strong, consistent positive alpha is significant
        self.assertTrue(r["alpha_significant"])

    def test_zero_variance_consistent_edge_significant(self):
        n = MIN_TRADES_SIGNIFICANCE + 5
        r = compute_edge_significance([8.0] * n, [0.0] * n)  # constant +8 alpha
        self.assertTrue(r["alpha_significant"])
        self.assertEqual(r["alpha_p_value"], 0.0)

    def test_noisy_alpha_not_significant(self):
        n = MIN_TRADES_SIGNIFICANCE + 5
        # alpha alternates ±5 around 0 → mean ~0 → NOT significant
        realized = [5.0 if i % 2 == 0 else -5.0 for i in range(n)]
        predicted = [0.0] * n
        r = compute_edge_significance(realized, predicted)
        self.assertFalse(r["insufficient_n"])
        self.assertIn("alpha_p_value", r)
        self.assertFalse(r["alpha_significant"])

    def test_no_predicted_yields_winrate_only(self):
        n = MIN_TRADES_SIGNIFICANCE + 2
        r = compute_edge_significance([1.0 if i % 2 else -1.0 for i in range(n)])
        self.assertFalse(r["insufficient_n"])
        self.assertIn("win_rate_ci95", r)
        self.assertNotIn("alpha_p_value", r)

    def test_floor_override_via_min_n(self):
        # explicit min_n lets the caller raise/lower the floor (env-overridable)
        r_lo = compute_edge_significance([1.0, -1.0, 2.0, 3.0], [0.0] * 4, min_n=3)
        self.assertFalse(r_lo["insufficient_n"])
        r_hi = compute_edge_significance([1.0, -1.0, 2.0, 3.0], [0.0] * 4, min_n=50)
        self.assertTrue(r_hi["insufficient_n"])

    def test_ci_widens_at_smaller_n(self):
        # identical per-trade alpha dispersion; smaller n → wider alpha CI half-width
        def half(n):
            realized = [5.0 if i % 2 == 0 else -5.0 for i in range(n)]
            r = compute_edge_significance(realized, [0.0] * n, min_n=2)
            lo, hi = r["alpha_ci95"]
            return (hi - lo) / 2.0
        self.assertGreater(half(8), half(40))


if __name__ == "__main__":
    unittest.main()
