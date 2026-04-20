"""
Regression tests for multi-leg sign-convention handling in
`_close_position_on_fill` (alpaca_order_handler).

Motivating incident: PYPL cfe69b28 on 2026-04-17. Alpaca filled a
long-debit-spread CLOSE at net credit 2.60/spread (the parent mleg
order reported `filled_avg_price = -2.60` because Alpaca's multi-leg
convention is: positive = net debit paid, negative = net credit
received). The reconciler read −2.60 literally as an "exit price" and
computed `realized_pl = (-2.60 − 2.94) × 6 × 100 = -$3,324` when the
actual loss was just -$204 ( entry 2.94 paid - close 2.60 received =
-$0.34/spread × 6 × 100 ).

The bug is sibling to two earlier close-path findings that also ship
as standalone P0s paying down PR #6's scope:
  - PR #784: `alpaca_order_sync` didn't invoke `poll_pending_orders`
    for users whose only non-terminal orders were `needs_manual_review`
    (outer-caller gap). That let the PYPL fill stay unreconciled for
    4+ hours. See 2026-04-17 diagnosis notes.
  - NFLX 846bc787 $138 overcount (2026-04-16): `manual_internal_fill`
    path wrote `unrealized_pl` into `realized_pl`. Different mechanism,
    same class: a specific close-path caller recording realized P&L
    incorrectly. PR #6's shared helper (with required `realized_pl` +
    `fill_source` parameters) structurally eliminates the class.

This PR fixes the reconciler's sign convention in-place. The cleaner
canonical math lands with PR #6's shared close helper.

Single call site. `paper_exit_evaluator._close_position` uses a
different math pattern (`exit_price = position.current_mark` — a
per-contract price from MTM, not a cash-flow-signed value) so is not
in scope here. Its Alpaca-path route short-circuits to the reconciler
at line 905-953 anyway, so fixing the reconciler fixes the Alpaca-
routed close end to end.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock

# Stub alpaca-py surface so `from packages.quantum.brokers ...` imports
# cleanly when alpaca-py isn't installed in the test venv.
_alpaca_pkg = types.ModuleType("alpaca")
_alpaca_trading = types.ModuleType("alpaca.trading")
_alpaca_trading_requests = types.ModuleType("alpaca.trading.requests")
sys.modules.setdefault("alpaca", _alpaca_pkg)
sys.modules.setdefault("alpaca.trading", _alpaca_trading)
sys.modules.setdefault("alpaca.trading.requests", _alpaca_trading_requests)

from packages.quantum.brokers import alpaca_order_handler  # noqa: E402


def _make_supabase(position_row):
    """Supabase mock that returns `position_row` for the position
    fetch, captures the paper_positions UPDATE payload in a list."""
    updates = []
    supabase = MagicMock()

    def table_side_effect(name):
        chain = MagicMock()
        if name == "paper_positions":
            # Two phases: (1) .select(...).single().execute() returns
            # the fetch; (2) .update(payload).eq(...).execute() is the
            # close-write.
            select_chain = MagicMock()
            select_chain.execute.return_value = MagicMock(data=position_row)
            for m in ("select", "eq", "single", "neq"):
                getattr(select_chain, m).return_value = select_chain
            chain.select.return_value = select_chain

            def capture_update(payload):
                updates.append(payload)
                return chain

            chain.update.side_effect = capture_update
            chain.eq.return_value = chain
            chain.execute.return_value = MagicMock(data=None)
        else:
            for m in ("select", "eq", "in_", "single", "limit"):
                getattr(chain, m).return_value = chain
            chain.execute.return_value = MagicMock(data=[])
        return chain

    supabase.table.side_effect = table_side_effect
    return supabase, updates


def _position(qty, entry_price, symbol="PYPL"):
    """Build a minimal paper_positions row."""
    return {
        "id": "pos-1",
        "symbol": symbol,
        "quantity": qty,
        "avg_entry_price": entry_price,
        "portfolio_id": "port-1",
        "status": "open",
        "legs": [],
    }


class TestMultilegSignConvention(unittest.TestCase):
    """
    The heart of the regression: Alpaca mleg parent filled_avg_price
    uses net-cash-flow sign. The reconciler must translate it to a
    position-side-correct per-contract exit value before differencing
    against entry_price.
    """

    def test_pypl_incident_reproduction_long_close_at_credit(self):
        """
        Exact PYPL cfe69b28 numbers — the live 2026-04-17 incident.
        entry 2.94 debit, close via net credit 2.60, qty 6. Expected
        realized_pl = -$204; the buggy code recorded -$3,324.
        """
        position = _position(qty=6.0, entry_price=2.94)
        supabase, updates = _make_supabase(position)
        alpaca_order = {
            "order_class": "mleg",
            "filled_avg_price": -2.60,  # mleg: negative = credit received
            "filled_qty": 6,
            "filled_at": "2026-04-17T17:15:11.251325Z",
        }

        alpaca_order_handler._close_position_on_fill(
            supabase, "pos-1", order={}, alpaca_order=alpaca_order,
        )

        self.assertEqual(len(updates), 1)
        upd = updates[0]
        self.assertEqual(upd["status"], "closed")
        self.assertEqual(upd["quantity"], 0)
        # The critical assertion: realized_pl matches real P&L, not
        # the sign-convention-broken −$3,324.
        self.assertAlmostEqual(upd["realized_pl"], -204.00, places=2)

    def test_mleg_long_close_at_profit_credit_greater_than_debit(self):
        """
        Long debit spread closed at profit: entry 2.94, close credit 4.00.
        Expected realized_pl = (4.00 − 2.94) × 6 × 100 = +$636.
        """
        position = _position(qty=6.0, entry_price=2.94)
        supabase, updates = _make_supabase(position)
        alpaca_order = {
            "order_class": "mleg",
            "filled_avg_price": -4.00,
            "filled_qty": 6,
            "filled_at": "2026-04-20T14:00:00Z",
        }

        alpaca_order_handler._close_position_on_fill(
            supabase, "pos-1", order={}, alpaca_order=alpaca_order,
        )

        self.assertAlmostEqual(updates[0]["realized_pl"], 636.00, places=2)

    def test_mleg_short_close_uses_direct_debit_sign(self):
        """
        Short credit spread closed for a debit: entry 4.20 credit, qty -3,
        close debit 1.00. Expected realized = (4.20 − 1.00) × 3 × 100 = +$960.
        Short branch formula unchanged.
        """
        position = _position(qty=-3.0, entry_price=4.20, symbol="GOOGL")
        supabase, updates = _make_supabase(position)
        alpaca_order = {
            "order_class": "mleg",
            "filled_avg_price": 1.00,  # mleg short close: positive = net debit paid
            "filled_qty": 3,
            "filled_at": "2026-04-20T14:00:00Z",
        }

        alpaca_order_handler._close_position_on_fill(
            supabase, "pos-1", order={}, alpaca_order=alpaca_order,
        )

        self.assertAlmostEqual(updates[0]["realized_pl"], 960.00, places=2)

    def test_mleg_short_close_at_loss(self):
        """
        Short credit spread that moved against us — closing for more
        debit than we received in credit. entry 1.50 credit, close
        debit 2.75, qty -4. Expected realized = (1.50 − 2.75) × 4 × 100 = -$500.
        """
        position = _position(qty=-4.0, entry_price=1.50, symbol="AMD")
        supabase, updates = _make_supabase(position)
        alpaca_order = {
            "order_class": "mleg",
            "filled_avg_price": 2.75,
            "filled_qty": 4,
            "filled_at": "2026-04-20T14:00:00Z",
        }

        alpaca_order_handler._close_position_on_fill(
            supabase, "pos-1", order={}, alpaca_order=alpaca_order,
        )

        self.assertAlmostEqual(updates[0]["realized_pl"], -500.00, places=2)

    def test_single_leg_long_close_does_not_flip_sign(self):
        """
        Single-leg option close — `filled_avg_price` is the per-contract
        sale price directly, NO sign translation. A long call bought
        at 5.00 and sold at 6.00 must record +$100 profit, not -$1,100.
        """
        position = _position(qty=1.0, entry_price=5.00, symbol="AAPL")
        supabase, updates = _make_supabase(position)
        alpaca_order = {
            "order_class": "simple",  # single-leg
            "filled_avg_price": 6.00,
            "filled_qty": 1,
            "filled_at": "2026-04-20T14:00:00Z",
        }

        alpaca_order_handler._close_position_on_fill(
            supabase, "pos-1", order={}, alpaca_order=alpaca_order,
        )

        self.assertAlmostEqual(updates[0]["realized_pl"], 100.00, places=2)

    def test_single_leg_short_close_unchanged(self):
        """
        Single-leg short call bought back: entry credit 3.00, close
        debit 1.50, qty -1. Expected realized = (3.00 − 1.50) × 1 × 100 = $150.
        Short branch formula works for single-leg just as for mleg.
        """
        position = _position(qty=-1.0, entry_price=3.00, symbol="TSLA")
        supabase, updates = _make_supabase(position)
        alpaca_order = {
            "order_class": "simple",
            "filled_avg_price": 1.50,
            "filled_qty": 1,
            "filled_at": "2026-04-20T14:00:00Z",
        }

        alpaca_order_handler._close_position_on_fill(
            supabase, "pos-1", order={}, alpaca_order=alpaca_order,
        )

        self.assertAlmostEqual(updates[0]["realized_pl"], 150.00, places=2)

    def test_order_class_missing_treated_as_single_leg(self):
        """
        Defensive guard: if Alpaca's response lacks `order_class` for
        any reason, default to single-leg semantics (no sign flip).
        Otherwise a missing field would silently inflate realized_pl
        on long closes — same failure mode in the opposite direction.
        """
        position = _position(qty=1.0, entry_price=5.00, symbol="AAPL")
        supabase, updates = _make_supabase(position)
        alpaca_order = {
            # no order_class
            "filled_avg_price": 6.00,
            "filled_qty": 1,
            "filled_at": "2026-04-20T14:00:00Z",
        }
        alpaca_order_handler._close_position_on_fill(
            supabase, "pos-1", order={}, alpaca_order=alpaca_order,
        )
        # Should compute as single-leg: (6 - 5) × 1 × 100 = 100.
        self.assertAlmostEqual(updates[0]["realized_pl"], 100.00, places=2)


class TestPositionSkipPaths(unittest.TestCase):
    """Sanity: existing skip conditions unchanged by this fix."""

    def test_position_already_closed_is_skipped(self):
        position = _position(qty=6.0, entry_price=2.94)
        position["status"] = "closed"
        supabase, updates = _make_supabase(position)
        alpaca_order = {"order_class": "mleg", "filled_avg_price": -2.60, "filled_qty": 6}

        alpaca_order_handler._close_position_on_fill(
            supabase, "pos-1", order={}, alpaca_order=alpaca_order,
        )
        # No update attempted — existing guard honoured.
        self.assertEqual(updates, [])

    def test_position_not_found_is_skipped(self):
        supabase, updates = _make_supabase(position_row=None)
        alpaca_order = {"order_class": "mleg", "filled_avg_price": -2.60, "filled_qty": 6}
        alpaca_order_handler._close_position_on_fill(
            supabase, "missing", order={}, alpaca_order=alpaca_order,
        )
        self.assertEqual(updates, [])


if __name__ == "__main__":
    unittest.main()
