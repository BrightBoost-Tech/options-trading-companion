"""
Integration tests for `alpaca_order_handler._close_position_on_fill` —
the Alpaca-fill reconciler's close path.

PR #6 refactor (Commit 4b) migrated this function from inline
parent-level sign-flip math to the shared 3-stage pipeline
(extract_close_legs → compute_realized_pl → close_position_shared).
This file covers the integration surface: the handler as glue code
between Alpaca order shape and paper_positions close write. Pure
math invariants live in test_close_math.py; helper invariants live
in test_close_helper.py.

Motivating incident (PYPL cfe69b28, 2026-04-17): Alpaca filled a
long-debit-spread CLOSE at net credit 2.60/spread. Pre-PR #790 the
reconciler read −2.60 literally and computed realized_pl = -$3,324
when the actual loss was -$204. Pre-PR #790 also allowed any
close-path caller to write `realized_pl` inconsistently (e.g. the
NFLX 846bc787 $138 overcount 2026-04-16: the internal-fill path
wrote `unrealized_pl` into `realized_pl`). The shared pipeline
structurally eliminates both classes by routing all 4 close
handlers through a single pure math function + a single atomic
writer.

The PYPL regression headline test below now asserts the canonical
leg-level inputs produce realized_pl = -204.00 through the whole
reconciler path — not just through the pure math function.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock

# Stub alpaca-py surface so `from packages.quantum.brokers ...`
# imports cleanly when alpaca-py isn't installed in the test venv.
_alpaca_pkg = types.ModuleType("alpaca")
_alpaca_trading = types.ModuleType("alpaca.trading")
_alpaca_trading_requests = types.ModuleType("alpaca.trading.requests")
sys.modules.setdefault("alpaca", _alpaca_pkg)
sys.modules.setdefault("alpaca.trading", _alpaca_trading)
sys.modules.setdefault("alpaca.trading.requests", _alpaca_trading_requests)

from packages.quantum.brokers import alpaca_order_handler  # noqa: E402


def _make_supabase(position_row, update_rows=None):
    """Build a Supabase-client mock for the reconciler path.

    `position_row` is returned from the initial
    paper_positions.select(*).eq(id).single().execute() fetch.

    `update_rows` controls the result of the conditional update
    inside close_position_shared: default [{"id": "pos-1"}] = 1 row
    affected (happy path). Pass [] to simulate a 0-rows-affected
    update and exercise the diagnostic SELECT branch.
    """
    if update_rows is None:
        update_rows = [{"id": (position_row or {}).get("id", "pos-1")}]

    captured_updates = []
    captured_inserts = []
    supabase = MagicMock()

    def table_side_effect(name):
        chain = MagicMock()

        if name == "paper_positions":
            # Initial fetch chain: .select(*).eq().single().execute()
            # returns the position row.
            select_chain = MagicMock()
            select_chain.execute.return_value = MagicMock(data=position_row)
            for method_name in ("select", "eq", "single", "limit"):
                getattr(select_chain, method_name).return_value = select_chain
            chain.select.return_value = select_chain

            # Update chain:
            # .update(payload).eq("id", pid).neq("status", "closed")
            #     .execute() → data=[{...}]  (1 row on happy path)
            def capture_update(payload):
                captured_updates.append(payload)
                update_chain = MagicMock()
                update_chain.eq.return_value = update_chain
                update_chain.neq.return_value = update_chain
                update_chain.execute.return_value = MagicMock(data=update_rows)
                return update_chain

            chain.update.side_effect = capture_update

        elif name == "risk_alerts":
            # _write_close_path_critical_alert inserts a row here on
            # any anomaly. We capture to let tests assert what fired.
            def capture_insert(payload):
                captured_inserts.append(payload)
                insert_chain = MagicMock()
                insert_chain.execute.return_value = MagicMock(data=None)
                return insert_chain

            chain.insert.side_effect = capture_insert

        else:
            # Fallback passthrough for any other table access.
            for method_name in ("select", "eq", "in_", "single", "limit"):
                getattr(chain, method_name).return_value = chain
            chain.execute.return_value = MagicMock(data=[])

        return chain

    supabase.table.side_effect = table_side_effect
    return supabase, captured_updates, captured_inserts


def _position(qty, entry_price, symbol="PYPL", user_id="user-1"):
    """Build a minimal paper_positions row."""
    return {
        "id": "pos-1",
        "user_id": user_id,
        "symbol": symbol,
        "quantity": qty,
        "avg_entry_price": entry_price,
        "portfolio_id": "port-1",
        "status": "open",
        "legs": [],
    }


class TestMultilegSignConvention(unittest.TestCase):
    """The PR #790 sign-convention invariants, re-expressed against
    the PR #6 leg-level pipeline. Parent-level filled_avg_price sign
    is no longer a concern — the new pipeline consumes legs directly,
    so Alpaca's mleg parent sign convention is structurally irrelevant.
    """

    def test_pypl_incident_reproduction_long_close_at_credit(self):
        """Canonical PYPL cfe69b28 regression.

        entry 2.94 debit, qty 6. Close legs: sell 5.05 + buy 2.45.
        Expected realized_pl = (-2.94 + 5.05 - 2.45) × 6 × 100 = -$204.
        """
        position = _position(qty=6.0, entry_price=2.94)
        supabase, updates, inserts = _make_supabase(position)
        alpaca_order = {
            "order_class": "mleg",
            "filled_qty": 6,
            "filled_at": "2026-04-17T17:15:11.251325Z",
            "legs": [
                {"symbol": "PYPL-LONG",  "side": "sell",
                 "filled_qty": 6, "filled_avg_price": 5.05},
                {"symbol": "PYPL-SHORT", "side": "buy",
                 "filled_qty": 6, "filled_avg_price": 2.45},
            ],
        }

        alpaca_order_handler._close_position_on_fill(
            supabase, "pos-1", order={}, alpaca_order=alpaca_order,
        )

        self.assertEqual(len(updates), 1, f"Expected 1 close-write; inserts={inserts}")
        upd = updates[0]
        self.assertEqual(upd["status"], "closed")
        self.assertEqual(upd["quantity"], 0)
        # realized_pl is stored as string (Decimal → str for PostgREST).
        self.assertEqual(str(upd["realized_pl"]), "-204.00")
        self.assertEqual(upd["close_reason"], "alpaca_fill_reconciler_standard")
        self.assertEqual(upd["fill_source"], "alpaca_fill_reconciler")
        self.assertEqual(inserts, [])  # no risk_alerts on happy path

    def test_mleg_long_close_at_profit(self):
        """Long debit spread closed at profit: entry 2.94,
        close legs sell 7.00 + buy 3.00 = net 4.00 credit.
        Expected realized_pl = (-2.94 + 7.00 - 3.00) × 6 × 100 = +$636.
        """
        position = _position(qty=6.0, entry_price=2.94)
        supabase, updates, _ = _make_supabase(position)
        alpaca_order = {
            "order_class": "mleg",
            "filled_qty": 6,
            "filled_at": "2026-04-20T14:00:00Z",
            "legs": [
                {"symbol": "X-LONG",  "side": "sell",
                 "filled_qty": 6, "filled_avg_price": 7.00},
                {"symbol": "X-SHORT", "side": "buy",
                 "filled_qty": 6, "filled_avg_price": 3.00},
            ],
        }

        alpaca_order_handler._close_position_on_fill(
            supabase, "pos-1", order={}, alpaca_order=alpaca_order,
        )

        self.assertEqual(str(updates[0]["realized_pl"]), "636.00")

    def test_mleg_short_close_at_profit(self):
        """Short credit spread: entry 4.20 credit (qty -3), closed via
        buy-back at 1.00 debit net. Close legs: buy 2.00 + sell 1.00.
        Expected realized = (+4.20 - 2.00 + 1.00) × 3 × 100 = +$960.
        """
        position = _position(qty=-3.0, entry_price=4.20, symbol="GOOGL")
        supabase, updates, _ = _make_supabase(position)
        alpaca_order = {
            "order_class": "mleg",
            "filled_qty": 3,
            "filled_at": "2026-04-20T14:00:00Z",
            "legs": [
                {"symbol": "GOOGL-LONG",  "side": "buy",
                 "filled_qty": 3, "filled_avg_price": 2.00},
                {"symbol": "GOOGL-SHORT", "side": "sell",
                 "filled_qty": 3, "filled_avg_price": 1.00},
            ],
        }

        alpaca_order_handler._close_position_on_fill(
            supabase, "pos-1", order={}, alpaca_order=alpaca_order,
        )

        self.assertEqual(str(updates[0]["realized_pl"]), "960.00")

    def test_mleg_short_close_at_loss(self):
        """Short credit spread moved against us: entry 1.50 credit
        (qty -4), closed at 2.75 debit. Legs: buy 3.50 + sell 0.75.
        Expected realized = (+1.50 - 3.50 + 0.75) × 4 × 100 = -$500.
        """
        position = _position(qty=-4.0, entry_price=1.50, symbol="AMD")
        supabase, updates, _ = _make_supabase(position)
        alpaca_order = {
            "order_class": "mleg",
            "filled_qty": 4,
            "filled_at": "2026-04-20T14:00:00Z",
            "legs": [
                {"symbol": "AMD-LONG",  "side": "buy",
                 "filled_qty": 4, "filled_avg_price": 3.50},
                {"symbol": "AMD-SHORT", "side": "sell",
                 "filled_qty": 4, "filled_avg_price": 0.75},
            ],
        }

        alpaca_order_handler._close_position_on_fill(
            supabase, "pos-1", order={}, alpaca_order=alpaca_order,
        )

        self.assertEqual(str(updates[0]["realized_pl"]), "-500.00")

    def test_single_leg_long_close(self):
        """Single-leg long call: entry 5.00, close sale at 6.00,
        qty 1. _synthesize_single_leg constructs the LegFill from
        parent-level fields. Expected realized = +$100.
        """
        position = _position(qty=1.0, entry_price=5.00, symbol="AAPL")
        supabase, updates, _ = _make_supabase(position)
        alpaca_order = {
            "order_class": "simple",
            "symbol": "O:AAPL250117C00150000",
            "side": "sell",
            "filled_qty": 1,
            "filled_avg_price": 6.00,
            "filled_at": "2026-04-20T14:00:00Z",
        }

        alpaca_order_handler._close_position_on_fill(
            supabase, "pos-1", order={}, alpaca_order=alpaca_order,
        )

        self.assertEqual(str(updates[0]["realized_pl"]), "100.00")

    def test_single_leg_short_close(self):
        """Single-leg short call bought back: entry 3.00 credit
        (qty -1), close buy at 1.50. Expected = (+3.00 - 1.50) × 1
        × 100 = +$150.
        """
        position = _position(qty=-1.0, entry_price=3.00, symbol="TSLA")
        supabase, updates, _ = _make_supabase(position)
        alpaca_order = {
            "order_class": "simple",
            "symbol": "O:TSLA250117C00200000",
            "side": "buy",
            "filled_qty": 1,
            "filled_avg_price": 1.50,
            "filled_at": "2026-04-20T14:00:00Z",
        }

        alpaca_order_handler._close_position_on_fill(
            supabase, "pos-1", order={}, alpaca_order=alpaca_order,
        )

        self.assertEqual(str(updates[0]["realized_pl"]), "150.00")


class TestPositionSkipPaths(unittest.TestCase):
    """Fast-path guards: no pipeline invocation, no updates, no
    alerts. Unchanged behavior from pre-PR-#6.
    """

    def test_position_already_closed_is_skipped(self):
        position = _position(qty=6.0, entry_price=2.94)
        position["status"] = "closed"
        supabase, updates, inserts = _make_supabase(position)
        alpaca_order = {
            "order_class": "mleg",
            "filled_qty": 6,
            "legs": [
                {"side": "sell", "filled_qty": 6, "filled_avg_price": 5.05},
                {"side": "buy",  "filled_qty": 6, "filled_avg_price": 2.45},
            ],
        }

        alpaca_order_handler._close_position_on_fill(
            supabase, "pos-1", order={}, alpaca_order=alpaca_order,
        )
        self.assertEqual(updates, [])
        self.assertEqual(inserts, [])

    def test_position_not_found_is_skipped(self):
        supabase, updates, inserts = _make_supabase(position_row=None)
        alpaca_order = {
            "order_class": "mleg",
            "filled_qty": 6,
            "legs": [
                {"side": "sell", "filled_qty": 6, "filled_avg_price": 5.05},
                {"side": "buy",  "filled_qty": 6, "filled_avg_price": 2.45},
            ],
        }
        alpaca_order_handler._close_position_on_fill(
            supabase, "missing", order={}, alpaca_order=alpaca_order,
        )
        self.assertEqual(updates, [])
        self.assertEqual(inserts, [])


class TestAnomalyAlerts(unittest.TestCase):
    """Pipeline exceptions must fire a severity='critical' risk_alert
    and abort the close — no paper_positions write."""

    def test_partial_fill_on_legs_aborts_and_alerts(self):
        """Alpaca returned filled_qty=5 but position has qty=6 — not
        an all-or-nothing close. extract_close_legs raises
        PartialFillDetected; handler writes critical alert and returns.
        """
        position = _position(qty=6.0, entry_price=2.94)
        supabase, updates, inserts = _make_supabase(position)
        alpaca_order = {
            "order_class": "mleg",
            "filled_qty": 5,
            "legs": [
                {"side": "sell", "filled_qty": 5, "filled_avg_price": 5.05},
                {"side": "buy",  "filled_qty": 5, "filled_avg_price": 2.45},
            ],
        }

        alpaca_order_handler._close_position_on_fill(
            supabase, "pos-1", order={}, alpaca_order=alpaca_order,
        )

        self.assertEqual(updates, [])  # no close-write
        self.assertEqual(len(inserts), 1)
        alert = inserts[0]
        self.assertEqual(alert["severity"], "critical")
        self.assertEqual(alert["alert_type"], "close_path_anomaly")
        self.assertEqual(alert["metadata"]["stage"], "compute_realized_pl")

    def test_malformed_fill_aborts_and_alerts(self):
        """No legs, no parent fill data → extract_close_legs raises
        MalformedFillData. Handler writes critical alert and returns.
        """
        position = _position(qty=1.0, entry_price=5.00, symbol="AAPL")
        supabase, updates, inserts = _make_supabase(position)
        alpaca_order = {
            "order_class": "simple",
            # missing: symbol, side, filled_qty, filled_avg_price
            "filled_at": "2026-04-20T14:00:00Z",
        }

        alpaca_order_handler._close_position_on_fill(
            supabase, "pos-1", order={}, alpaca_order=alpaca_order,
        )

        self.assertEqual(updates, [])
        self.assertEqual(len(inserts), 1)
        self.assertEqual(inserts[0]["severity"], "critical")
        self.assertEqual(inserts[0]["metadata"]["stage"], "extract_close_legs")


if __name__ == "__main__":
    unittest.main()
