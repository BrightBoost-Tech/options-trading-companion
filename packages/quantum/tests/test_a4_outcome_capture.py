"""Steps 2-3 — A4 entry-IV + realized-vol-over-hold capture at close.

V1 (failure isolation, MOST IMPORTANT): NULL entry IV and/or missing price data
    → outcome record STILL writes with P&L/EV intact, new fields NULL.
V2 (happy path): valid hold → non-NULL entry_iv_rv_spread + realized_vol_over_hold
    + entry_ts stamped.
V4 (min-bars guard): a 1-day hold → realized_vol_over_hold = NULL.
"""

import unittest

from packages.quantum.jobs.handlers.paper_learning_ingest import (
    _create_paper_outcome_record,
    _compute_realized_vol_over_hold,
)


def _bars(closes):
    return [{"close": c} for c in closes]


class _FakeTL:
    def __init__(self, bars):
        self._bars = bars

    def daily_bars(self, symbol, start, end):
        return self._bars


class _BoomTL:
    def daily_bars(self, *a, **k):
        raise RuntimeError("polygon down")


ENTRY = "2026-06-01T14:00:00+00:00"
EXIT = "2026-06-09T20:00:00+00:00"


class TestComputeRvOverHold(unittest.TestCase):
    def test_happy_path_non_null(self):  # V2 (compute side)
        tl = _FakeTL(_bars([100, 101, 99, 103, 104, 102, 105]))
        v = _compute_realized_vol_over_hold(tl, "AAPL", ENTRY, EXIT)
        self.assertIsNotNone(v)
        self.assertGreater(v, 0.0)

    def test_one_day_hold_null(self):  # V4
        tl = _FakeTL(_bars([100, 101]))  # 2 bars < A4_MIN_HOLD_BARS (3)
        self.assertIsNone(
            _compute_realized_vol_over_hold(tl, "AAPL", ENTRY, "2026-06-02T00:00:00+00:00")
        )

    def test_inverted_hold_null(self):
        tl = _FakeTL(_bars([100, 101, 102, 103]))
        self.assertIsNone(_compute_realized_vol_over_hold(tl, "AAPL", EXIT, ENTRY))

    def test_truth_layer_none(self):  # V1 (no market data)
        self.assertIsNone(_compute_realized_vol_over_hold(None, "AAPL", ENTRY, EXIT))

    def test_fetch_error_isolated(self):  # V1 (fetch blows up)
        self.assertIsNone(_compute_realized_vol_over_hold(_BoomTL(), "AAPL", ENTRY, EXIT))

    def test_missing_symbol_null(self):
        tl = _FakeTL(_bars([100, 101, 102, 103]))
        self.assertIsNone(_compute_realized_vol_over_hold(tl, None, ENTRY, EXIT))
        self.assertIsNone(_compute_realized_vol_over_hold(tl, "UNKNOWN", ENTRY, EXIT))

    def test_bad_timestamps_null(self):
        tl = _FakeTL(_bars([100, 101, 102, 103]))
        self.assertIsNone(_compute_realized_vol_over_hold(tl, "AAPL", "not-a-date", EXIT))


class TestOutcomeRecordA4Fields(unittest.TestCase):
    def _pos(self):
        return {
            "id": "p1", "realized_pl": 50.0, "status": "closed",
            "opened_at": ENTRY, "closed_at": EXIT,
            "suggestion_id": "s1", "trace_id": "t1", "symbol": "AAPL",
        }

    def _order(self):
        return {
            "id": "o1", "filled_qty": 1, "avg_fill_price": 1.5, "requested_price": 1.5,
            "side": "sell", "status": "filled", "order_type": "limit",
            "trace_id": "t1", "suggestion_id": "s1", "order_json": {"symbol": "AAPL"},
        }

    def test_happy_path_fields_present(self):  # V2
        rec = _create_paper_outcome_record(
            "u1", self._order(), "2026-06-09", self._pos(),
            suggestion_ev=10.0,
            suggestion_meta={"iv_rv_spread": 0.04, "probability_of_profit": 0.6},
            is_paper=True,
            entry_iv_rv_spread=0.04, entry_ts=ENTRY, realized_vol_over_hold=0.27,
        )
        self.assertEqual(rec["entry_iv_rv_spread"], 0.04)
        self.assertEqual(rec["entry_ts"], ENTRY)
        self.assertEqual(rec["realized_vol_over_hold"], 0.27)
        self.assertEqual(rec["pnl_realized"], 50.0)
        self.assertEqual(rec["pnl_predicted"], 10.0)

    def test_failure_isolation_all_null_still_writes(self):  # V1 (MOST IMPORTANT)
        rec = _create_paper_outcome_record(
            "u1", self._order(), "2026-06-09", self._pos(),
            suggestion_ev=10.0, suggestion_meta=None, is_paper=True,
            entry_iv_rv_spread=None, entry_ts=None, realized_vol_over_hold=None,
        )
        # New fields NULL …
        self.assertIsNone(rec["entry_iv_rv_spread"])
        self.assertIsNone(rec["entry_ts"])
        self.assertIsNone(rec["realized_vol_over_hold"])
        # … but the outcome record is intact (P&L / EV / type preserved).
        self.assertEqual(rec["pnl_realized"], 50.0)
        self.assertEqual(rec["pnl_predicted"], 10.0)
        self.assertEqual(rec["outcome_type"], "trade_closed")
        self.assertEqual(rec["suggestion_id"], "s1")

    def test_defaults_when_a4_kwargs_omitted(self):
        # Backward-compatible: omitting the A4 kwargs entirely → fields default NULL.
        rec = _create_paper_outcome_record(
            "u1", self._order(), "2026-06-09", self._pos(),
            suggestion_ev=10.0, suggestion_meta=None, is_paper=True,
        )
        self.assertIsNone(rec["entry_iv_rv_spread"])
        self.assertIsNone(rec["realized_vol_over_hold"])
        self.assertIsNone(rec["entry_ts"])


if __name__ == "__main__":
    unittest.main()
