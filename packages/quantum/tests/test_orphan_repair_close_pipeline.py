"""
Regression tests for PR #6 Commit 6:
paper_endpoints._repair_filled_order_commit close branch migrated to
the shared close_math + close_helper pipeline.

Scope
  Covers the new_qty == 0 close path (when an orphan fill's signed
  quantity cancels out an existing open position). The open/flip
  paths are unchanged and covered by the pre-existing
  test_orphan_order_repair.py (currently module-skipped for mock-drift
  unrelated to this PR).

Invariants asserted
  - Multi-leg orphan close with legs in broker_response → realized_pl
    computed via leg-level math, close_reason='orphan_fill_repair',
    fill_source='orphan_fill_repair'.
  - Single-leg orphan close (no broker_response legs) → synthesized
    from parent-level side/filled_qty/avg_fill_price.
  - mleg order with broker_response.order_class='mleg' but no legs →
    aborts with severity='critical' risk_alert. This is the latent-
    bug guard: parent-level synthesis on mleg data would recreate
    the PYPL cfe69b28-class sign-convention bug.
  - PositionAlreadyClosed race → aborts with critical risk_alert
    carrying the existing row's close_reason/fill_source metadata.
  - Partial fill in broker_response legs → aborts with critical
    risk_alert.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Stub alpaca-py surface so imports don't fail.
sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
sys.modules.setdefault(
    "alpaca.trading.requests", types.ModuleType("alpaca.trading.requests")
)

from packages.quantum import paper_endpoints  # noqa: E402


class _RepairSupabase:
    """Supabase mock for _repair_filled_order_commit's close branch.

    The function performs:
      paper_positions.select(*).eq(portfolio_id).eq(strategy_key).eq(status).execute()
          → return [existing_position]
      (close branch) close_position_shared:
          paper_positions.update(...).eq(id).neq("status","closed").execute()
              → data=[{'id': ...}] on happy path; data=[] on race
      paper_orders.update({position_id}).eq(id).execute()
      paper_ledger.select(id).eq(order_id).execute() → no existing
      paper_ledger.insert(...).execute()
      paper_portfolios.select(cash_balance).eq(id).execute()
      paper_portfolios.update({cash_balance}).eq(id).execute()
      risk_alerts.insert(...).execute() on anomalies
    """

    def __init__(self, position, update_rows=None, diag_rows=None):
        self.position = position
        self.update_rows = update_rows if update_rows is not None else [{"id": position["id"]}]
        # diag_rows controls the post-0-row diagnostic SELECT inside
        # close_position_shared (for the PositionAlreadyClosed path).
        self.diag_rows = diag_rows or []
        self.position_updates = []
        self.risk_alerts = []
        self._pp_select_count = 0

    def table(self, name):
        return _Chain(self, name)


class _Chain:
    def __init__(self, parent, name):
        self.parent = parent
        self.name = name
        self._op = None
        self._payload = None
        self._select_cols = None

    def select(self, *a, **k):
        self._op = "select"
        self._select_cols = a[0] if a else "*"
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def eq(self, *a, **k): return self
    def neq(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def single(self): return self

    def execute(self):
        if self.name == "paper_positions":
            if self._op == "select":
                # First call = strategy-key lookup (returns existing).
                # Second call (happens only on 0-row update) = diagnostic.
                self.parent._pp_select_count += 1
                if self.parent._pp_select_count == 1:
                    return MagicMock(data=[self.parent.position])
                return MagicMock(data=self.parent.diag_rows)
            if self._op == "update":
                self.parent.position_updates.append(self._payload)
                return MagicMock(data=self.parent.update_rows)

        if self.name == "paper_orders":
            if self._op == "update":
                return MagicMock(data=None)

        if self.name == "paper_ledger":
            if self._op == "select":
                return MagicMock(data=[])
            if self._op == "insert":
                return MagicMock(data=None)

        if self.name == "paper_portfolios":
            if self._op == "select":
                return MagicMock(data={"cash_balance": 100000.0})
            if self._op == "update":
                return MagicMock(data=None)

        if self.name == "risk_alerts":
            if self._op == "insert":
                self.parent.risk_alerts.append(self._payload)
                return MagicMock(data=None)

        return MagicMock(data=[])


def _existing_position(qty, entry_price, strategy_key="SPY_LONG_CALL_DEBIT_SPREAD"):
    return {
        "id": "pos-1",
        "user_id": "user-1",
        "symbol": "SPY",
        "quantity": qty,
        "avg_entry_price": entry_price,
        "status": "open",
        "portfolio_id": "port-1",
        "strategy_key": strategy_key,
    }


def _close_order(side, filled_qty, avg_fill_price, broker_response=None, symbol="SPY"):
    """Build an orphan-filled close order whose side+filled_qty cancel
    out the existing_position's quantity (forcing the new_qty==0
    branch inside _repair_filled_order_commit)."""
    ticket = {
        "symbol": symbol,
        "quantity": filled_qty,
        "strategy_type": "custom",
        "legs": [{"symbol": f"O:{symbol}250117C00500000", "action": side}],
    }
    return {
        "id": "order-1",
        "order_json": ticket,
        "side": side,
        "filled_qty": filled_qty,
        "avg_fill_price": avg_fill_price,
        "fees_usd": 0,
        "broker_response": broker_response,
    }


class TestOrphanRepairClosePipeline(unittest.TestCase):
    def _run_repair(self, supabase, order, portfolio=None):
        if portfolio is None:
            portfolio = {"id": "port-1", "cash_balance": 100000.0}
        # _derive_strategy_key is called on the ticket. Patch it to
        # return a deterministic value matching the existing position's
        # strategy_key so the select() finds the position.
        with patch(
            "packages.quantum.paper_endpoints._derive_strategy_key",
            return_value=supabase.position["strategy_key"],
        ):
            return paper_endpoints._repair_filled_order_commit(
                supabase, MagicMock(), "user-1", order, portfolio,
            )

    def test_mleg_close_uses_broker_response_legs(self):
        """Long debit spread close: entry 2.94, legs sell 5.05 + buy 2.45,
        qty 6. Expected realized_pl = -204.00 (PYPL-style numbers).
        Validates leg-level math via extract_close_legs(broker_response)."""
        pos = _existing_position(qty=6.0, entry_price=2.94)
        broker_response = {
            "order_class": "mleg",
            "filled_qty": 6,
            "legs": [
                {"symbol": "LONG",  "side": "sell", "filled_qty": 6, "filled_avg_price": 5.05},
                {"symbol": "SHORT", "side": "buy",  "filled_qty": 6, "filled_avg_price": 2.45},
            ],
        }
        order = _close_order(
            side="sell", filled_qty=6, avg_fill_price=-2.60,
            broker_response=broker_response,
        )
        supabase = _RepairSupabase(pos)

        result = self._run_repair(supabase, order)

        self.assertEqual(result["position_id"], "pos-1")
        self.assertEqual(len(supabase.position_updates), 1)
        upd = supabase.position_updates[0]
        self.assertEqual(upd["status"], "closed")
        self.assertEqual(upd["quantity"], 0)
        self.assertEqual(str(upd["realized_pl"]), "-204.00")
        self.assertEqual(upd["close_reason"], "orphan_fill_repair")
        self.assertEqual(upd["fill_source"], "orphan_fill_repair")
        self.assertEqual(supabase.risk_alerts, [])

    def test_single_leg_close_synthesized_from_parent(self):
        """Single-leg close: no broker_response.legs. Parent-level
        side='sell', filled_qty=1, avg_fill_price=6.00, closing a long
        qty=1 entry=5.00. Expected realized_pl = +100.00 via
        _synthesize_single_leg."""
        pos = _existing_position(qty=1.0, entry_price=5.00)
        # broker_response present but no legs → synthesize from parent.
        broker_response = {"order_class": "simple"}
        order = _close_order(
            side="sell", filled_qty=1, avg_fill_price=6.00,
            broker_response=broker_response,
        )
        supabase = _RepairSupabase(pos)

        result = self._run_repair(supabase, order)

        self.assertEqual(result["position_id"], "pos-1")
        self.assertEqual(str(supabase.position_updates[0]["realized_pl"]), "100.00")
        self.assertEqual(supabase.risk_alerts, [])

    def test_no_broker_response_falls_back_to_parent_synthesis(self):
        """If broker_response is entirely missing, synthesize from
        parent-level fields. Long position entry 4.00, close sell at
        7.00, qty 2 → realized = +600.00."""
        pos = _existing_position(qty=2.0, entry_price=4.00)
        order = _close_order(
            side="sell", filled_qty=2, avg_fill_price=7.00,
            broker_response=None,
        )
        supabase = _RepairSupabase(pos)

        self._run_repair(supabase, order)

        self.assertEqual(str(supabase.position_updates[0]["realized_pl"]), "600.00")

    def test_mleg_missing_legs_aborts_with_critical_alert(self):
        """LATENT-BUG GUARD. broker_response.order_class='mleg' but
        no legs sub-array — parent-level synthesis would use
        avg_fill_price which for mleg carries the net-cash-flow sign
        (PYPL cfe69b28-class bug). Must abort + alert, not guess."""
        pos = _existing_position(qty=6.0, entry_price=2.94)
        broker_response = {
            "order_class": "mleg",
            "filled_qty": 6,
            # No legs — this is the pathological shape.
        }
        order = _close_order(
            side="sell", filled_qty=6, avg_fill_price=-2.60,  # mleg-signed!
            broker_response=broker_response,
        )
        supabase = _RepairSupabase(pos)

        result = self._run_repair(supabase, order)

        # No close-write.
        self.assertEqual(supabase.position_updates, [])
        self.assertIsNone(result.get("position_id"))
        # Critical alert fired with mleg-missing-legs context.
        self.assertEqual(len(supabase.risk_alerts), 1)
        alert = supabase.risk_alerts[0]
        self.assertEqual(alert["severity"], "critical")
        self.assertEqual(alert["alert_type"], "close_path_anomaly")
        self.assertEqual(alert["metadata"]["stage"], "extract_close_legs")
        self.assertEqual(alert["metadata"]["order_class"], "mleg")

    def test_partial_fill_on_legs_aborts_with_critical_alert(self):
        """broker_response legs show filled_qty=5 on both legs but
        parent+position expect qty=6. extract_close_legs raises
        PartialFillDetected via parent/leg qty mismatch."""
        pos = _existing_position(qty=6.0, entry_price=2.94)
        broker_response = {
            "order_class": "mleg",
            "filled_qty": 6,
            "legs": [
                {"symbol": "L", "side": "sell", "filled_qty": 5, "filled_avg_price": 5.05},
                {"symbol": "S", "side": "buy",  "filled_qty": 5, "filled_avg_price": 2.45},
            ],
        }
        order = _close_order(
            side="sell", filled_qty=6, avg_fill_price=-2.60,
            broker_response=broker_response,
        )
        supabase = _RepairSupabase(pos)

        result = self._run_repair(supabase, order)

        self.assertEqual(supabase.position_updates, [])
        self.assertEqual(len(supabase.risk_alerts), 1)
        self.assertEqual(supabase.risk_alerts[0]["severity"], "critical")
        self.assertEqual(
            supabase.risk_alerts[0]["metadata"]["stage"], "extract_close_legs"
        )

    def test_position_already_closed_aborts_with_critical_alert(self):
        """Race: another handler closed the same position between our
        SELECT and UPDATE. close_position_shared raises
        PositionAlreadyClosed; caller writes critical alert with
        diagnostic metadata."""
        pos = _existing_position(qty=1.0, entry_price=5.00)
        order = _close_order(
            side="sell", filled_qty=1, avg_fill_price=6.00,
            broker_response={"order_class": "simple"},
        )
        # 0 update rows + diag row showing closed → PositionAlreadyClosed.
        supabase = _RepairSupabase(
            pos,
            update_rows=[],
            diag_rows=[{
                "status": "closed",
                "close_reason": "alpaca_fill_reconciler_standard",
                "fill_source": "alpaca_fill_reconciler",
                "closed_at": "2026-04-22T12:00:00Z",
            }],
        )

        result = self._run_repair(supabase, order)

        self.assertIsNone(result.get("position_id"))
        # The helper's update fired but 0 rows affected; no happy-path
        # close-write to assert on.
        self.assertEqual(len(supabase.risk_alerts), 1)
        alert = supabase.risk_alerts[0]
        self.assertEqual(alert["severity"], "critical")
        self.assertEqual(alert["metadata"]["stage"], "close_position_shared")
        self.assertEqual(
            alert["metadata"]["existing_close_reason"],
            "alpaca_fill_reconciler_standard",
        )
        self.assertEqual(
            alert["metadata"]["existing_fill_source"],
            "alpaca_fill_reconciler",
        )


if __name__ == "__main__":
    unittest.main()
