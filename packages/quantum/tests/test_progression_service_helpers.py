"""Tests for the shared get_alpaca_real_closed_trades + cumulative_realized_pl
helpers introduced 2026-05-06 (extracted from daily_progression_eval inline
pattern, used by both daily_progression_eval and promotion_check)."""

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from packages.quantum.services.progression_service import (
    cumulative_realized_pl,
    get_alpaca_real_closed_trades,
)


class TestCumulativeRealizedPl(unittest.TestCase):
    """Pure-function tests on the aggregation helper."""

    def test_empty_list_returns_zero(self):
        self.assertEqual(cumulative_realized_pl([]), 0.0)

    def test_sum_positive_values(self):
        trades = [
            {"realized_pl": 10.0},
            {"realized_pl": 20.5},
            {"realized_pl": 5},
        ]
        self.assertEqual(cumulative_realized_pl(trades), 35.5)

    def test_sum_mixed_sign(self):
        trades = [
            {"realized_pl": 50.0},
            {"realized_pl": -75.0},
            {"realized_pl": 25.0},
        ]
        self.assertEqual(cumulative_realized_pl(trades), 0.0)

    def test_handles_none_values(self):
        """Trades with realized_pl=None must not raise; treated as 0."""
        trades = [
            {"realized_pl": None},
            {"realized_pl": 100.0},
            {"realized_pl": None},
        ]
        self.assertEqual(cumulative_realized_pl(trades), 100.0)

    def test_handles_missing_key(self):
        """Trades without realized_pl key must not raise."""
        trades = [
            {"id": "abc"},  # no realized_pl
            {"realized_pl": 50.0},
        ]
        self.assertEqual(cumulative_realized_pl(trades), 50.0)


def _make_supabase_mock(
    paper_positions_response,
    paper_orders_responses,
):
    """Build a Supabase mock with a single paper_positions response and a
    pop-on-each-call queue for paper_orders responses (one per position
    in paper_positions_response)."""

    def _make_chain(execute_data):
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=execute_data)
        for method in (
            "select", "eq", "neq", "gte", "lte", "lt", "gt",
            "in_", "order", "limit", "single",
        ):
            getattr(chain, method).return_value = chain
        return chain

    paper_orders_queue = list(paper_orders_responses)

    def table_side_effect(name):
        if name == "paper_positions":
            return _make_chain(paper_positions_response)
        if name == "paper_orders":
            data = paper_orders_queue.pop(0) if paper_orders_queue else []
            return _make_chain(data)
        return _make_chain([])

    sb = MagicMock()
    sb.table.side_effect = table_side_effect
    return sb


class TestGetAlpacaRealClosedTrades(unittest.TestCase):
    """Behavioral tests on the trade-lens helper."""

    def test_empty_when_no_closed_positions(self):
        sb = _make_supabase_mock(paper_positions_response=[], paper_orders_responses=[])
        result = get_alpaca_real_closed_trades("user-1", sb)
        self.assertEqual(result, [])

    def test_includes_position_with_alpaca_entry(self):
        """Closed position whose entry order has alpaca_order_id is included."""
        positions = [{"id": "pos-1", "realized_pl": 50.0}]
        # Entry order for pos-1 has alpaca_order_id set
        orders = [[{"alpaca_order_id": "alpaca-abc"}]]
        sb = _make_supabase_mock(positions, orders)
        result = get_alpaca_real_closed_trades("user-1", sb)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "pos-1")

    def test_excludes_position_with_internal_entry(self):
        """Closed position whose entry order has alpaca_order_id=None is excluded.
        This is the 34-corrupted-rows / internal-paper case from CLAUDE.md
        2026-04-16 entry."""
        positions = [{"id": "pos-internal", "realized_pl": 999.0}]
        orders = [[{"alpaca_order_id": None}]]
        sb = _make_supabase_mock(positions, orders)
        result = get_alpaca_real_closed_trades("user-1", sb)
        self.assertEqual(result, [])

    def test_mixed_alpaca_and_internal(self):
        """Filter keeps the Alpaca one, drops the internal one."""
        positions = [
            {"id": "pos-alpaca", "realized_pl": 100.0},
            {"id": "pos-internal", "realized_pl": -200.0},
        ]
        orders = [
            [{"alpaca_order_id": "alpaca-1"}],
            [{"alpaca_order_id": None}],
        ]
        sb = _make_supabase_mock(positions, orders)
        result = get_alpaca_real_closed_trades("user-1", sb)
        ids = [r["id"] for r in result]
        self.assertEqual(ids, ["pos-alpaca"])

    def test_excludes_position_with_no_orders(self):
        """If paper_orders has no rows for a position (orphan or migration
        artifact), it's excluded — can't verify entry was Alpaca-routed."""
        positions = [{"id": "pos-orphan", "realized_pl": 50.0}]
        orders = [[]]  # zero entry orders
        sb = _make_supabase_mock(positions, orders)
        result = get_alpaca_real_closed_trades("user-1", sb)
        self.assertEqual(result, [])

    def test_paper_orders_query_failure_skips_position(self):
        """Per existing pattern's graceful degradation: a per-position order
        lookup exception drops that position, doesn't abort the sweep."""
        positions = [
            {"id": "pos-a", "realized_pl": 50.0},
            {"id": "pos-b", "realized_pl": 25.0},
        ]
        # paper_orders raises on first call, succeeds on second
        sb = MagicMock()

        positions_chain = MagicMock()
        positions_chain.execute.return_value = MagicMock(data=positions)
        for m in ("select", "eq", "neq", "gte", "lte", "lt", "gt",
                  "in_", "order", "limit", "single"):
            getattr(positions_chain, m).return_value = positions_chain

        orders_call_count = [0]

        def make_orders_chain():
            chain = MagicMock()

            def execute_side_effect():
                orders_call_count[0] += 1
                if orders_call_count[0] == 1:
                    raise RuntimeError("simulated DB failure on first lookup")
                return MagicMock(data=[{"alpaca_order_id": "alpaca-2"}])

            chain.execute.side_effect = execute_side_effect
            for m in ("select", "eq", "neq", "gte", "lte", "lt", "gt",
                      "in_", "order", "limit", "single"):
                getattr(chain, m).return_value = chain
            return chain

        def table_side_effect(name):
            if name == "paper_positions":
                return positions_chain
            if name == "paper_orders":
                return make_orders_chain()
            raise AssertionError(f"unexpected table {name}")

        sb.table.side_effect = table_side_effect

        result = get_alpaca_real_closed_trades("user-1", sb)
        # pos-a was skipped (its lookup raised); pos-b included
        self.assertEqual([r["id"] for r in result], ["pos-b"])


class TestEligibilityForFullAuto(unittest.TestCase):
    """Behavioral tests on the new eligibility method."""

    def _setup_svc(
        self,
        equity,
        positions,
        orders,
    ):
        """Wire ProgressionService with mocked supabase + alpaca client."""
        from packages.quantum.services import progression_service as ps_mod
        from unittest.mock import patch

        sb = _make_supabase_mock(positions, orders)
        svc = ps_mod.ProgressionService(sb)

        # Patch alpaca client used inside is_eligible_for_full_auto
        mock_alpaca = MagicMock()
        mock_alpaca.get_account.return_value = {"equity": str(equity)}
        return svc, mock_alpaca, sb

    def _eligibility_with(self, equity, positions, orders):
        svc, mock_alpaca, sb = self._setup_svc(equity, positions, orders)
        from unittest.mock import patch
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=mock_alpaca,
        ):
            return svc.is_eligible_for_full_auto("user-1")

    def test_eligible_when_all_gates_pass(self):
        """equity=$1600, 3 Alpaca trades summing to +$50 → eligible."""
        positions = [
            {"id": "p1", "realized_pl": 20.0},
            {"id": "p2", "realized_pl": 20.0},
            {"id": "p3", "realized_pl": 10.0},
        ]
        orders = [
            [{"alpaca_order_id": "a1"}],
            [{"alpaca_order_id": "a2"}],
            [{"alpaca_order_id": "a3"}],
        ]
        result = self._eligibility_with(1600.0, positions, orders)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["alpaca_real_trade_count"], 3)
        self.assertEqual(result["cumulative_realized_pl"], 50.0)
        self.assertEqual(result["reason"], "all_gates_passed")

    def test_blocked_when_equity_below_threshold(self):
        result = self._eligibility_with(1499.99, [], [])
        self.assertFalse(result["eligible"])
        self.assertIn("equity_below_threshold", result["reason"])

    def test_blocked_when_cumulative_pl_zero(self):
        """Boundary: pl exactly 0 must NOT pass (gate is > 0, not >= 0)."""
        positions = [
            {"id": "p1", "realized_pl": 50.0},
            {"id": "p2", "realized_pl": -50.0},
            {"id": "p3", "realized_pl": 0.0},
        ]
        orders = [
            [{"alpaca_order_id": "a1"}],
            [{"alpaca_order_id": "a2"}],
            [{"alpaca_order_id": "a3"}],
        ]
        result = self._eligibility_with(2000.0, positions, orders)
        self.assertFalse(result["eligible"])
        self.assertIn("cumulative_pl_not_positive", result["reason"])

    def test_blocked_when_cumulative_pl_negative(self):
        positions = [
            {"id": "p1", "realized_pl": 10.0},
            {"id": "p2", "realized_pl": -50.0},
            {"id": "p3", "realized_pl": 5.0},
        ]
        orders = [
            [{"alpaca_order_id": "a1"}],
            [{"alpaca_order_id": "a2"}],
            [{"alpaca_order_id": "a3"}],
        ]
        result = self._eligibility_with(2000.0, positions, orders)
        self.assertFalse(result["eligible"])
        self.assertIn("cumulative_pl_not_positive", result["reason"])

    def test_blocked_when_insufficient_trades(self):
        """Even with great equity + great pl, < 3 trades blocks."""
        positions = [
            {"id": "p1", "realized_pl": 500.0},
            {"id": "p2", "realized_pl": 500.0},
        ]
        orders = [
            [{"alpaca_order_id": "a1"}],
            [{"alpaca_order_id": "a2"}],
        ]
        result = self._eligibility_with(5000.0, positions, orders)
        self.assertFalse(result["eligible"])
        self.assertIn("insufficient_trades", result["reason"])
        self.assertEqual(result["alpaca_real_trade_count"], 2)

    def test_internal_paper_trades_excluded_from_count(self):
        """The shared helper's filtering means internal-paper trades don't
        inflate the count toward the 3-trade threshold."""
        positions = [
            {"id": "p1", "realized_pl": 50.0},   # alpaca
            {"id": "p2", "realized_pl": 999.0},  # internal — should be ignored
            {"id": "p3", "realized_pl": 25.0},   # alpaca
        ]
        orders = [
            [{"alpaca_order_id": "a1"}],
            [{"alpaca_order_id": None}],
            [{"alpaca_order_id": "a3"}],
        ]
        result = self._eligibility_with(2000.0, positions, orders)
        self.assertFalse(result["eligible"])
        # Only 2 Alpaca-real trades; internal trade ignored
        self.assertEqual(result["alpaca_real_trade_count"], 2)
        # Cumulative pl reflects ONLY Alpaca-real trades (50 + 25 = 75),
        # not the inflated 1074 you'd get from naive sum
        self.assertEqual(result["cumulative_realized_pl"], 75.0)
        self.assertIn("insufficient_trades", result["reason"])

    def test_operator_current_state_does_not_promote(self):
        """Sanity check matching the diagnostic data:
          - Alpaca-only: 17 trades, cumulative_pl=-$20
          - Equity: $696.61 (today's reading)
        All three gates fail; equity is the binding (first) failure."""
        positions = [
            {"id": f"p{i}", "realized_pl": (-20.0 if i == 0 else 0.0)}
            for i in range(17)
        ]
        orders = [[{"alpaca_order_id": f"a{i}"}] for i in range(17)]
        result = self._eligibility_with(696.61, positions, orders)
        self.assertFalse(result["eligible"])
        # Equity gate is checked first → that's the surfaced reason
        self.assertIn("equity_below_threshold", result["reason"])
        # Diagnostic fields populated for audit even though blocked
        self.assertEqual(result["alpaca_real_trade_count"], 17)
        self.assertEqual(result["cumulative_realized_pl"], -20.0)


# ─────────────────────────────────────────────────────────────────────
# Source-level structural guards
# ─────────────────────────────────────────────────────────────────────


class TestStructuralGuards(unittest.TestCase):
    """Source-level guards against regression.

    Per #62a-D7 / #71 PR-5 doctrine: dead state references should not
    return after replacement. The substring may appear in commentary
    explaining what was removed; check for the actual call pattern."""

    def test_dead_column_state_get_pattern_removed(self):
        """state.get("micro_live_green_days", ...) must not appear in
        source code. Bare substring may legitimately appear in docstring
        history notes."""
        from pathlib import Path
        src = (
            Path(__file__).parent.parent / "jobs" / "handlers"
            / "promotion_check.py"
        ).read_text(encoding="utf-8")
        import re
        bad = re.findall(
            r'state\.get\(\s*"micro_live_green_days"',
            src,
        )
        self.assertEqual(
            bad, [],
            "Active state.get('micro_live_green_days', ...) call must "
            "not remain after the rewrite (column doesn't exist).",
        )

    def test_alpaca_paper_path_untouched(self):
        """Operator decision: alpaca_paper → micro_live logic stays as-is."""
        from pathlib import Path
        src = (
            Path(__file__).parent.parent / "services"
            / "progression_service.py"
        ).read_text(encoding="utf-8")
        # Spot-check key tokens of the existing logic
        self.assertIn("alpaca_paper_green_days", src)
        self.assertIn("alpaca_paper_green_days_required", src)
        self.assertIn("record_trading_day", src)

    def test_helper_used_by_both_callers(self):
        """Helper extraction means BOTH daily_progression_eval and
        progression_service.is_eligible_for_full_auto reference the
        new function."""
        from pathlib import Path
        deval = (
            Path(__file__).parent.parent / "jobs" / "handlers"
            / "daily_progression_eval.py"
        ).read_text(encoding="utf-8")
        psvc = (
            Path(__file__).parent.parent / "services"
            / "progression_service.py"
        ).read_text(encoding="utf-8")
        self.assertIn("get_alpaca_real_closed_trades", deval)
        self.assertIn("get_alpaca_real_closed_trades", psvc)

    def test_promotion_check_uses_eligibility_method(self):
        from pathlib import Path
        src = (
            Path(__file__).parent.parent / "jobs" / "handlers"
            / "promotion_check.py"
        ).read_text(encoding="utf-8")
        self.assertIn("is_eligible_for_full_auto", src)


if __name__ == "__main__":
    unittest.main()
