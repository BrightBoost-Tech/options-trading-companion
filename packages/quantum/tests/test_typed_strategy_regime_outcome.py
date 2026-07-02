"""A2 (2026-07-02) — typed strategy/regime on trade_closed outcome rows.

The outcome builder carried strategy/regime only inside details_json
(strategy_at_entry / regime_at_entry) while the typed columns — the ones
post_trade_learning._build_segment_key reads — were never written, so
segment learning silently no-oped (83/98 trade_closed rows NULL through
07-01). Values come from the already-fetched suggestion metadata; when no
suggestion is linked they stay NULL — never fabricated (H9).
"""

import unittest

from packages.quantum.jobs.handlers.paper_learning_ingest import (
    _create_paper_outcome_record,
)

ENTRY = "2026-06-01T14:00:00+00:00"
EXIT = "2026-06-09T20:00:00+00:00"


def _pos():
    return {
        "id": "p1", "realized_pl": 50.0, "status": "closed",
        "created_at": ENTRY, "closed_at": EXIT,
        "suggestion_id": "s1", "trace_id": "t1", "symbol": "AAPL",
    }


def _order():
    return {
        "id": "o1", "filled_qty": 1, "avg_fill_price": 1.5, "requested_price": 1.5,
        "side": "sell", "status": "filled", "order_type": "limit",
        "trace_id": "t1", "suggestion_id": "s1", "order_json": {"symbol": "AAPL"},
    }


class TestTypedStrategyRegime(unittest.TestCase):
    def test_typed_columns_written_from_suggestion_meta(self):
        rec = _create_paper_outcome_record(
            "u1", _order(), "2026-06-09", _pos(),
            suggestion_ev=10.0,
            suggestion_meta={
                "strategy": "bull_put_spread",
                "regime": "neutral",
                "probability_of_profit": 0.6,
            },
            is_paper=True,
        )
        self.assertEqual(rec["strategy"], "bull_put_spread")
        self.assertEqual(rec["regime"], "neutral")
        # details_json mirrors stay unchanged (analytics readers).
        self.assertEqual(rec["details_json"]["strategy_at_entry"], "bull_put_spread")
        self.assertEqual(rec["details_json"]["regime_at_entry"], "neutral")

    def test_no_suggestion_meta_stays_null_never_fabricated(self):
        rec = _create_paper_outcome_record(
            "u1", _order(), "2026-06-09", _pos(),
            suggestion_ev=10.0, suggestion_meta=None, is_paper=True,
        )
        self.assertIn("strategy", rec)
        self.assertIn("regime", rec)
        self.assertIsNone(rec["strategy"])
        self.assertIsNone(rec["regime"])
        # The core outcome record is untouched by the missing metadata.
        self.assertEqual(rec["pnl_realized"], 50.0)
        self.assertEqual(rec["outcome_type"], "trade_closed")

    def test_partial_meta_writes_what_exists_only(self):
        rec = _create_paper_outcome_record(
            "u1", _order(), "2026-06-09", _pos(),
            suggestion_ev=10.0,
            suggestion_meta={"strategy": "long_call"},
            is_paper=True,
        )
        self.assertEqual(rec["strategy"], "long_call")
        self.assertIsNone(rec["regime"])
