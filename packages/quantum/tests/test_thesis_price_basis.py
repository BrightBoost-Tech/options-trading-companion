"""PR-⓪ F-A9-THESIS-BASIS: the thesis price source is disclosed, never hidden.

_underlying_at_expiry must report WHICH bar graded a row — the exact expiry close
(authoritative) vs a ≤7d fallback bar (stale) vs unknown — so a terminal thesis
verdict graded off a days-stale bar is distinguishable from an honest one.
"""
import unittest
from datetime import date

from packages.quantum.jobs.handlers.thesis_tracker import _underlying_at_expiry


class _FakeTruth:
    def __init__(self, bars):
        self._bars = bars

    def daily_bars(self, symbol, start, end):
        return self._bars


class TestPriceBasisDisclosure(unittest.TestCase):
    EXPIRY = date(2026, 8, 21)

    def test_exact_expiry_bar_is_authoritative(self):
        bars = [{"date": "2026-08-19", "close": 100.0},
                {"date": "2026-08-21", "close": 105.0}]
        U, basis, d = _underlying_at_expiry(_FakeTruth(bars), "QQQ", self.EXPIRY)
        self.assertEqual((U, basis, d), (105.0, "expiry_close", "2026-08-21"))

    def test_missing_expiry_bar_is_fallback_with_date(self):
        # holiday/gap: no 08-21 bar → last bar on/before expiry, DISCLOSED as stale
        bars = [{"date": "2026-08-19", "close": 100.0},
                {"date": "2026-08-20", "close": 102.0}]
        U, basis, d = _underlying_at_expiry(_FakeTruth(bars), "QQQ", self.EXPIRY)
        self.assertEqual((U, basis, d), (102.0, "fallback_prior_bar", "2026-08-20"))

    def test_post_expiry_bar_never_used_as_price(self):
        # a bar AFTER expiry must not grade the row; fallback picks the latest ≤ expiry
        bars = [{"date": "2026-08-19", "close": 100.0},
                {"date": "2026-08-24", "close": 110.0}]
        U, basis, d = _underlying_at_expiry(_FakeTruth(bars), "QQQ", self.EXPIRY)
        self.assertEqual((U, basis, d), (100.0, "fallback_prior_bar", "2026-08-19"))

    def test_no_bar_is_unknown_not_fabricated(self):
        U, basis, d = _underlying_at_expiry(_FakeTruth([]), "QQQ", self.EXPIRY)
        self.assertEqual((U, basis, d), (None, None, None))

    def test_failure_degrades_to_unknown(self):
        class _Boom:
            def daily_bars(self, *a):
                raise RuntimeError("feed down")
        self.assertEqual(_underlying_at_expiry(_Boom(), "QQQ", self.EXPIRY),
                         (None, None, None))


if __name__ == "__main__":
    unittest.main()
