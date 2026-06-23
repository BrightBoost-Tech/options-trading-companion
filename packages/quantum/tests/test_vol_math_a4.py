"""Step 1 — generalized log-return realized vol (A4).

V3 (basis consistency): the generalized fn over a 20d window == the existing
20d result, on the Cluster-1 basis (log returns, ddof=0, ×√252).
Also: arbitrary window, min-returns guard.
"""

import importlib
import math
import random
import sys
import unittest

import numpy as np

from packages.quantum.analytics.vol_math import realized_vol_log_annualized


def _ref(closes, window):
    """Independent reference: np std (ddof=0) of log returns × √252."""
    sub = closes[-(window + 1):]
    rets = np.diff(np.log(sub))
    return float(np.std(rets, ddof=0) * np.sqrt(252))


class TestVolMath(unittest.TestCase):
    def setUp(self):
        random.seed(7)
        self.closes = [100.0]
        for _ in range(40):
            self.closes.append(self.closes[-1] * (1 + random.uniform(-0.02, 0.02)))

    def test_basis_log_ddof0_annualized_20d(self):
        got = realized_vol_log_annualized(self.closes, window=20)
        self.assertAlmostEqual(got, _ref(self.closes, 20), places=9)

    def test_arbitrary_window(self):
        for w in (5, 10, 30):
            self.assertAlmostEqual(
                realized_vol_log_annualized(self.closes, window=w), _ref(self.closes, w), places=9
            )

    def test_full_series_when_window_none(self):
        got = realized_vol_log_annualized(self.closes)  # window=None → len-1
        self.assertAlmostEqual(got, _ref(self.closes, len(self.closes) - 1), places=9)

    def test_matches_existing_regime_method_20d(self):
        # V3: the regime method must equal the fn over 20d (it now delegates).
        sys.modules.pop("packages.quantum.analytics.regime_engine_v3", None)
        mod = importlib.import_module("packages.quantum.analytics.regime_engine_v3")
        # self is unused by the delegating method → call unbound with None.
        method_val = mod.RegimeEngineV3._calculate_realized_volatility(None, self.closes)
        self.assertAlmostEqual(
            method_val, realized_vol_log_annualized(self.closes, window=20), places=12
        )

    def test_min_returns_guard(self):
        self.assertIsNone(realized_vol_log_annualized([100.0, 101.0]))  # 1 return
        self.assertIsNone(realized_vol_log_annualized([100.0]))
        self.assertIsNone(realized_vol_log_annualized([]))

    def test_too_few_for_requested_window(self):
        self.assertIsNone(realized_vol_log_annualized([100, 101, 102], window=20))

    def test_nonpositive_prices_dont_raise(self):
        # guarded to 0.0 returns, never a ValueError
        v = realized_vol_log_annualized([100, 0, 101, 102, 103])
        self.assertIsNotNone(v)


if __name__ == "__main__":
    unittest.main()
