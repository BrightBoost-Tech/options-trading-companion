"""Shadow-to-expiry thesis tracker (I5, 2026-07-11) — scoring + job contract.

Drives the pure scorer per structure AND the production handler end-to-end
(fake client + mocked price feed): the F-A4-1 partial contract, idempotent
skip of terminal verdicts, in_progress on a future expiry, unknown on a missing
price.
"""
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

from packages.quantum.analytics.thesis_scoring import score_thesis, classify_structure


def _ic(sp=650, lp=645, sc=765, lc=770, expiry="2026-06-18"):
    return [
        {"type": "put",  "action": "sell", "strike": sp, "expiry": expiry},
        {"type": "put",  "action": "buy",  "strike": lp, "expiry": expiry},
        {"type": "call", "action": "sell", "strike": sc, "expiry": expiry},
        {"type": "call", "action": "buy",  "strike": lc, "expiry": expiry},
    ]


def _bull_put(sold=500, bought=495):
    return [{"type": "put", "action": "sell", "strike": sold},
            {"type": "put", "action": "buy",  "strike": bought}]


def _bull_call(bought=500, sold=505):
    return [{"type": "call", "action": "buy",  "strike": bought},
            {"type": "call", "action": "sell", "strike": sold}]


# ── scoring (pure) ──────────────────────────────────────────────────────────

class TestClassify(unittest.TestCase):
    def test_iron_condor(self):
        self.assertEqual(classify_structure(_ic()), "iron_condor")

    def test_credit_vertical(self):
        self.assertEqual(classify_structure(_bull_put()), "credit_vertical")

    def test_debit_vertical(self):
        self.assertEqual(classify_structure(_bull_call()), "debit_vertical")

    def test_directional(self):
        self.assertEqual(classify_structure([{"type": "call", "action": "buy", "strike": 500}]),
                         "directional")


class TestIronCondor(unittest.TestCase):
    def test_inside_is_hit(self):
        self.assertEqual(score_thesis(_ic(), 700.0)[0], "hit")

    def test_above_short_call_is_miss(self):
        self.assertEqual(score_thesis(_ic(), 800.0)[0], "miss")

    def test_below_short_put_is_miss(self):
        self.assertEqual(score_thesis(_ic(), 600.0)[0], "miss")

    def test_at_short_call_boundary_is_miss(self):
        # strict: AT the short strike = reached = MISS
        self.assertEqual(score_thesis(_ic(), 765.0)[0], "miss")

    def test_at_short_put_boundary_is_miss(self):
        self.assertEqual(score_thesis(_ic(), 650.0)[0], "miss")


class TestVerticals(unittest.TestCase):
    def test_credit_put_kept_is_hit(self):
        self.assertEqual(score_thesis(_bull_put(), 510.0)[0], "hit")   # above short → OTM

    def test_credit_put_breached_is_miss(self):
        self.assertEqual(score_thesis(_bull_put(), 490.0)[0], "miss")  # below short → breached

    def test_debit_call_itm_is_hit(self):
        self.assertEqual(score_thesis(_bull_call(), 510.0)[0], "hit")  # above long → ITM

    def test_debit_call_otm_is_miss(self):
        self.assertEqual(score_thesis(_bull_call(), 495.0)[0], "miss")


class TestDirectionalAndUnknown(unittest.TestCase):
    def test_long_call_itm_hit(self):
        self.assertEqual(score_thesis([{"type": "call", "action": "buy", "strike": 500}], 510.0)[0], "hit")

    def test_long_call_otm_miss(self):
        self.assertEqual(score_thesis([{"type": "call", "action": "buy", "strike": 500}], 490.0)[0], "miss")

    def test_unknown_on_missing_price(self):
        self.assertEqual(score_thesis(_ic(), None)[0], "unknown")


# ── handler (production route, fake client + mocked feed) ────────────────────

class _Q:
    """Fake supabase query for the handler. Dispatches by table; records upserts."""
    def __init__(self, table, store):
        self.table_name = table
        self.store = store
        self._filters = {}

    def select(self, *a, **k):
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def in_(self, col, vals):
        self._filters[(col, "in")] = set(vals)
        return self

    def execute(self):
        if self.table_name == "paper_positions":
            return MagicMock(data=list(self.store["positions"]))
        if self.table_name == "paper_portfolios":
            return MagicMock(data=list(self.store["portfolios"]))
        if self.table_name == "paper_orders":
            return MagicMock(data=list(self.store["orders"]))
        if self.table_name == "position_thesis_outcomes":
            return MagicMock(data=list(self.store["terminal"]))
        return MagicMock(data=[])

    def upsert(self, row, on_conflict=None):
        self.store["upserts"].append(row)
        return self


class _FakeClient:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _Q(name, self.store)


def _run_handler(store, bars_by_symbol):
    from packages.quantum.jobs.handlers import thesis_tracker as tt

    class _Truth:
        def daily_bars(self, symbol, start, end):
            return bars_by_symbol.get(symbol, [])

    with patch.object(tt, "get_admin_client", return_value=_FakeClient(store)), \
         patch("packages.quantum.services.market_data_truth_layer.MarketDataTruthLayer",
               return_value=_Truth()):
        return tt.run({})


class TestHandlerContract(unittest.TestCase):
    def _store(self, positions, orders=None, terminal=None):
        return {
            "positions": positions,
            "portfolios": [{"id": "port-agg", "routing_mode": "live_eligible"}],
            "orders": orders or [],
            "terminal": terminal or [],
            "upserts": [],
        }

    def _pos(self, pid, expiry, legs, symbol="QQQ"):
        return {"id": pid, "user_id": "u1", "symbol": symbol, "nearest_expiry": expiry,
                "created_at": "2026-06-01T00:00:00+00:00", "closed_at": "2026-06-10T00:00:00+00:00",
                "close_reason": "stop_loss_hit", "realized_pl": -50, "legs": legs,
                "portfolio_id": "port-agg"}

    def test_scores_hit_from_bars(self):
        store = self._store([self._pos("p1", "2026-06-18", _ic())])
        out = _run_handler(store, {"QQQ": [{"date": "2026-06-18", "close": 700.0}]})
        self.assertEqual(out["counts"]["errors"], 0)
        row = store["upserts"][0]
        self.assertEqual(row["thesis_outcome"], "hit")
        self.assertEqual(row["underlying_at_expiry"], 700.0)

    def test_partial_when_price_missing(self):
        # expiry passed but the feed returns no bars → unknown → counts.errors>0
        store = self._store([self._pos("p2", "2026-06-18", _ic())])
        out = _run_handler(store, {})  # no bars
        self.assertGreaterEqual(out["counts"]["errors"], 1)
        self.assertEqual(store["upserts"][0]["thesis_outcome"], "unknown")

    def test_in_progress_on_future_expiry(self):
        future = (datetime.now(timezone.utc) + timedelta(days=30)).date().isoformat()
        store = self._store([self._pos("p3", future, _ic())])
        out = _run_handler(store, {"QQQ": [{"date": future, "close": 700.0}]})
        self.assertEqual(out["counts"]["errors"], 0)  # in_progress is NOT an error
        self.assertEqual(store["upserts"][0]["thesis_outcome"], "in_progress")

    def test_idempotent_skips_terminal(self):
        store = self._store(
            [self._pos("p4", "2026-06-18", _ic())],
            terminal=[{"position_id": "p4", "thesis_outcome": "hit"}],
        )
        out = _run_handler(store, {"QQQ": [{"date": "2026-06-18", "close": 700.0}]})
        self.assertEqual(len(store["upserts"]), 0)  # terminal verdict never re-scored


if __name__ == "__main__":
    unittest.main()
