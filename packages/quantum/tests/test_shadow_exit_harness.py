"""D6 Phase 1 shadow harness — ISOLATION (mandatory) + persistence tests.

The harness is OBSERVATION-ONLY: geometry decisions are logged, never acted on.
The real exit stays governed by the premium-% logic. These tests prove:
  (A) decision independence — premium-% says HOLD while geometry says STOP for
      the same position (the real decision wins; geometry is log-only);
  (B) write isolation — the harness writes ONLY shadow_exit_decisions, never
      touches paper_positions (no close/update path);
  (C) persistence — a shadow row is written with the comparison fields.
"""

import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from packages.quantum.services import paper_exit_evaluator as pe
from packages.quantum.services.exit_geometry import (
    compute_spread_geometry,
    evaluate_geometry_rules,
)


def _f_position(far_expiry: str):
    """F debit call spread, healthy premium-% (small +PnL), expiry far out so the
    DTE exit doesn't trigger. Geometry breakeven = 16.46."""
    return {
        "id": "bdbe4d04", "user_id": "u1", "symbol": "F", "quantity": 5,
        "avg_entry_price": 0.96, "max_credit": 0.96, "unrealized_pl": 30.0,
        "nearest_expiry": far_expiry,
        "strategy_key": "F_long_call_debit_spread",
        "legs": [
            {"type": "call", "action": "buy", "strike": 15.5, "symbol": "O:F260626C00015500", "quantity": 5, "expiry": far_expiry},
            {"type": "call", "action": "sell", "strike": 17.5, "symbol": "O:F260626C00017500", "quantity": 5, "expiry": far_expiry},
        ],
    }


class _RecTable:
    def __init__(self, store, name):
        self._store, self._name = store, name

    def insert(self, rows):
        self._store.append((self._name, "insert", rows))
        return self

    def update(self, vals):
        self._store.append((self._name, "update", vals))
        return self

    def eq(self, *a, **k):
        return self

    def execute(self):
        return SimpleNamespace(data=[{}])


class _RecClient:
    def __init__(self):
        self.calls = []

    def table(self, name):
        return _RecTable(self.calls, name)


class _FakeTruth:
    """snapshot_many returns spot ~16.3 (below F's 16.46 breakeven → geometry
    R2/R3 say STOP)."""
    def snapshot_many(self, symbols):
        return {s: {"quote": {"bid": 16.25, "ask": 16.35}} for s in symbols}


class TestShadowExitIsolation(unittest.TestCase):
    def setUp(self):
        self.far = (date.today() + timedelta(days=30)).isoformat()

    def test_A_premium_holds_while_geometry_stops(self):
        """Mandatory isolation: premium-% HOLDS the position (healthy P&L, far
        DTE) while a geometry rule would STOP it — the real decision wins."""
        pos = _f_position(self.far)
        # premium-% champion decision (the REAL one):
        premium_decision = pe.evaluate_position_exit(pos)
        self.assertIsNone(premium_decision, "premium-% must HOLD this healthy position")
        # geometry would STOP (spot 16.3 < breakeven 16.46):
        geom = compute_spread_geometry(pos, underlying_spot=16.3, dte=30)
        rules = evaluate_geometry_rules(geom)
        self.assertEqual(rules["R2"]["decision"], "stop")
        # Independent: the geometry stop has no bearing on the premium-% hold.

    def test_B_harness_writes_only_shadow_table(self):
        """Write isolation: the harness inserts ONLY into shadow_exit_decisions —
        it never updates/closes paper_positions."""
        client = _RecClient()
        evaluator = pe.PaperExitEvaluator(client)
        pos = _f_position(self.far)
        with patch(
            "packages.quantum.services.market_data_truth_layer.MarketDataTruthLayer",
            _FakeTruth,
        ):
            # premium-% holds (None) but geometry will say stop — log only.
            evaluator._persist_shadow_exit_decisions("u1", [(pos, None)])

        tables_written = {name for (name, op, _) in client.calls if op in ("insert", "update")}
        self.assertEqual(tables_written, {"shadow_exit_decisions"})
        self.assertNotIn("paper_positions", tables_written)

    def test_C_shadow_row_records_comparison(self):
        """Persistence: the shadow row carries premium-% decision + geometry
        rule decisions + geometry + spot."""
        client = _RecClient()
        evaluator = pe.PaperExitEvaluator(client)
        pos = _f_position(self.far)
        with patch(
            "packages.quantum.services.market_data_truth_layer.MarketDataTruthLayer",
            _FakeTruth,
        ):
            evaluator._persist_shadow_exit_decisions("u1", [(pos, None)])

        inserts = [rows for (name, op, rows) in client.calls
                   if name == "shadow_exit_decisions" and op == "insert"]
        self.assertEqual(len(inserts), 1)
        row = inserts[0][0]
        self.assertEqual(row["premium_pct_decision"], "hold")
        self.assertEqual(row["symbol"], "F")
        self.assertAlmostEqual(float(row["underlying_spot"]), 16.3, places=2)
        self.assertTrue(row["geometry"]["applicable"])
        # spot 16.3 < breakeven 16.46 → geometry R2 stop, recorded alongside hold.
        self.assertEqual(row["geometry_decisions"]["R2"]["decision"], "stop")

    def test_D_harness_failsoft_on_bad_position(self):
        """A malformed position must not raise out of the harness."""
        client = _RecClient()
        evaluator = pe.PaperExitEvaluator(client)
        with patch(
            "packages.quantum.services.market_data_truth_layer.MarketDataTruthLayer",
            _FakeTruth,
        ):
            # Should not raise.
            evaluator._persist_shadow_exit_decisions("u1", [({"id": "x", "symbol": "F"}, None)])


if __name__ == "__main__":
    unittest.main()
