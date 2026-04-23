"""
Regression tests for PR #6 Commit 7:
paper_endpoints._commit_fill close branch migrated to shared
close_math + close_helper pipeline.

Scope
  _commit_fill is the 4th close handler. It services two source
  engines, both of which stage internal-paper close orders through
  _process_orders_for_user:
    - source_engine='manual_close'     (POST /paper/close endpoint)
    - source_engine='paper_autopilot'  (PaperAutopilotService.close_positions)

  Both map to close_reason='manual_close_user_initiated' and
  fill_source='manual_endpoint'. Autopilot closes are user-configured
  automation (via PAPER_AUTOPILOT_CLOSE_POLICY), not system force-
  closes, so the manual-close mapping is semantically correct.

Out of scope
  The attribution-failure retain-position branch (pre-existing) stays
  unchanged and is NOT exercised by these tests — it's the only path
  through _commit_fill's close branch that does not touch the
  pipeline. See _commit_fill's block: `if not attribution_ok: retain`.

Invariants asserted
  - realized_pl computed by compute_realized_pl with fees_delta
    subtracted post-compute (matches pre-PR-#6 fee semantics).
  - close_reason enum is 'manual_close_user_initiated' for both
    source engines.
  - fill_source is 'manual_endpoint'.
  - Unknown source_engine aborts with severity='critical'
    risk_alert and preserves the position (no close-write).
  - PositionAlreadyClosed race aborts with critical alert carrying
    the existing row's metadata.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Stub alpaca-py surface so imports succeed.
sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
sys.modules.setdefault(
    "alpaca.trading.requests", types.ModuleType("alpaca.trading.requests")
)

from packages.quantum import paper_endpoints  # noqa: E402


class _CommitFillSupabase:
    """Supabase mock for _commit_fill's close branch.

    Captures updates to paper_positions and inserts to risk_alerts.
    Handles the conditional UPDATE + diagnostic SELECT pattern used
    by close_position_shared.
    """

    def __init__(
        self,
        existing_position,
        update_rows=None,
        diag_rows=None,
    ):
        self.existing_position = existing_position
        self.update_rows = update_rows if update_rows is not None else [
            {"id": existing_position["id"]}
        ]
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

    def select(self, *a, **k): self._op = "select"; return self
    def update(self, payload): self._op = "update"; self._payload = payload; return self
    def insert(self, payload): self._op = "insert"; self._payload = payload; return self
    def eq(self, *a, **k): return self
    def neq(self, *a, **k): return self
    def in_(self, *a, **k): return self
    def order(self, *a, **k): return self
    def limit(self, *a, **k): return self
    def single(self): return self

    def execute(self):
        if self.name == "paper_orders" and self._op == "update":
            return MagicMock(data=None)
        if self.name == "paper_portfolios" and self._op == "update":
            return MagicMock(data=None)
        if self.name == "paper_ledger" and self._op in ("select", "insert"):
            return MagicMock(data=[])

        if self.name == "paper_positions":
            if self._op == "select":
                self.parent._pp_select_count += 1
                if self.parent._pp_select_count == 1:
                    return MagicMock(data=self.parent.existing_position)
                return MagicMock(data=self.parent.diag_rows)
            if self._op == "update":
                self.parent.position_updates.append(self._payload)
                return MagicMock(data=self.parent.update_rows)

        if self.name == "risk_alerts" and self._op == "insert":
            self.parent.risk_alerts.append(self._payload)
            return MagicMock(data=None)

        return MagicMock(data=[])


def _existing_position(qty, entry_price, symbol="SPY"):
    return {
        "id": "pos-1",
        "user_id": "user-1",
        "symbol": symbol,
        "quantity": qty,
        "avg_entry_price": entry_price,
        "status": "open",
        "portfolio_id": "port-1",
        "strategy_key": "SPY_LONG_CALL_DEBIT_SPREAD",
    }


def _close_order(qty, fill_price, source_engine, symbol="SPY", side=None):
    """Build an order row simulating a manual/autopilot close that
    fully cancels the existing position."""
    if side is None:
        side = "sell"  # default: close a long
    return {
        "id": "order-1",
        "position_id": "pos-1",
        "side": side,
        "requested_qty": qty,
        "filled_qty": 0,  # incremental fills: 0 before this tick
        "fees_usd": 0,
        "tcm": {"fees_usd": 1.00},  # $1 cost estimate for test
        "portfolio_id": "port-1",
        "order_json": {
            "symbol": symbol,
            "quantity": qty,
            "strategy_type": "custom",
            "source_engine": source_engine,
            "legs": [
                {"symbol": f"O:{symbol}250117C00500000", "action": side},
            ],
        },
    }


def _fill_res(qty, price):
    return {
        "status": "filled",
        "filled_qty": qty,
        "avg_fill_price": price,
        "last_fill_qty": qty,
        "last_fill_price": price,
    }


def _portfolio(cash=100000.0):
    return {"id": "port-1", "cash_balance": cash}


class TestCommitFillClosePipeline(unittest.TestCase):
    def _run(self, supabase, order, fill_res, portfolio=None):
        if portfolio is None:
            portfolio = _portfolio()
        # Patch strategy key derivation and attribution so the close
        # branch is reached deterministically.
        with patch(
            "packages.quantum.paper_endpoints._derive_strategy_key",
            return_value=supabase.existing_position["strategy_key"],
        ), patch(
            "packages.quantum.paper_endpoints._run_attribution",
            return_value=None,
        ), patch(
            "packages.quantum.paper_endpoints.PaperLedgerService"
        ) as MockLedger:
            MockLedger.return_value.emit_fill = MagicMock()
            MockLedger.return_value.emit_partial_fill = MagicMock()
            return paper_endpoints._commit_fill(
                supabase, MagicMock(), "user-1", order,
                fill_res, quote=None, portfolio=portfolio,
            )

    def test_manual_close_long_debit(self):
        """POST /paper/close closes a long debit spread: entry 2.00,
        fill 3.00, qty 6, fees $1 → realized = +600 − 1 = +599.00.
        close_reason='manual_close_user_initiated',
        fill_source='manual_endpoint'."""
        pos = _existing_position(qty=6, entry_price=2.00)
        order = _close_order(qty=6, fill_price=3.00, source_engine="manual_close")
        supabase = _CommitFillSupabase(pos)

        self._run(supabase, order, _fill_res(6, 3.00))

        self.assertEqual(len(supabase.position_updates), 1)
        upd = supabase.position_updates[0]
        self.assertEqual(upd["status"], "closed")
        self.assertEqual(upd["quantity"], 0)
        self.assertEqual(str(upd["realized_pl"]), "599.00")
        self.assertEqual(upd["close_reason"], "manual_close_user_initiated")
        self.assertEqual(upd["fill_source"], "manual_endpoint")
        self.assertEqual(supabase.risk_alerts, [])

    def test_autopilot_close_short_credit(self):
        """PaperAutopilot close on short credit spread: entry 2.50
        credit (qty -4), buy-back at 1.00, fees $1. realized = (+2.50
        − 1.00) × 4 × 100 − 1 = +599.00. Same close_reason mapping."""
        pos = _existing_position(qty=-4, entry_price=2.50, symbol="AMD")
        order = _close_order(
            qty=4, fill_price=1.00,
            source_engine="paper_autopilot",
            symbol="AMD", side="buy",
        )
        supabase = _CommitFillSupabase(pos)

        self._run(supabase, order, _fill_res(4, 1.00))

        upd = supabase.position_updates[0]
        self.assertEqual(str(upd["realized_pl"]), "599.00")
        self.assertEqual(upd["close_reason"], "manual_close_user_initiated")
        self.assertEqual(upd["fill_source"], "manual_endpoint")

    def test_unknown_source_engine_aborts_with_critical_alert(self):
        """Close branch reached with source_engine='midday_entry' (an
        entry engine, never valid here). Must abort + alert, not
        guess a mapping."""
        pos = _existing_position(qty=1, entry_price=4.00)
        order = _close_order(qty=1, fill_price=5.00, source_engine="midday_entry")
        supabase = _CommitFillSupabase(pos)

        self._run(supabase, order, _fill_res(1, 5.00))

        self.assertEqual(supabase.position_updates, [])
        self.assertEqual(len(supabase.risk_alerts), 1)
        alert = supabase.risk_alerts[0]
        self.assertEqual(alert["severity"], "critical")
        self.assertEqual(alert["alert_type"], "close_path_anomaly")
        self.assertEqual(alert["metadata"]["stage"], "map_close_reason")
        self.assertEqual(alert["metadata"]["source_engine"], "midday_entry")

    def test_empty_source_engine_aborts_with_critical_alert(self):
        """Missing/empty source_engine is treated as unknown. No
        silent fall-through into a default close_reason."""
        pos = _existing_position(qty=1, entry_price=4.00)
        order = _close_order(qty=1, fill_price=5.00, source_engine="")
        supabase = _CommitFillSupabase(pos)

        self._run(supabase, order, _fill_res(1, 5.00))

        self.assertEqual(supabase.position_updates, [])
        self.assertEqual(len(supabase.risk_alerts), 1)
        self.assertEqual(supabase.risk_alerts[0]["metadata"]["stage"], "map_close_reason")

    def test_position_already_closed_race_aborts_with_critical_alert(self):
        """Race: a concurrent close handler marked the position
        closed between our fetch and UPDATE. close_position_shared's
        conditional-UPDATE affects 0 rows; diagnostic SELECT surfaces
        the existing close. Caller writes critical alert with
        existing metadata."""
        pos = _existing_position(qty=1, entry_price=4.00)
        order = _close_order(qty=1, fill_price=5.00, source_engine="manual_close")
        supabase = _CommitFillSupabase(
            pos,
            update_rows=[],  # 0 rows affected
            diag_rows=[{
                "status": "closed",
                "close_reason": "alpaca_fill_reconciler_standard",
                "fill_source": "alpaca_fill_reconciler",
                "closed_at": "2026-04-22T13:00:00Z",
            }],
        )

        self._run(supabase, order, _fill_res(1, 5.00))

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

    def test_attribution_failure_retains_position(self):
        """Pre-existing retain-on-attribution-failure behavior must
        survive the refactor. If _run_attribution raises,
        attribution_ok=False, no close-write, no critical alert —
        position preserved for next close cycle."""
        pos = _existing_position(qty=1, entry_price=4.00)
        order = _close_order(qty=1, fill_price=5.00, source_engine="manual_close")
        supabase = _CommitFillSupabase(pos)

        with patch(
            "packages.quantum.paper_endpoints._derive_strategy_key",
            return_value=pos["strategy_key"],
        ), patch(
            "packages.quantum.paper_endpoints._run_attribution",
            side_effect=RuntimeError("downstream attribution down"),
        ), patch(
            "packages.quantum.paper_endpoints.PaperLedgerService"
        ) as MockLedger:
            MockLedger.return_value.emit_fill = MagicMock()
            MockLedger.return_value.emit_partial_fill = MagicMock()
            paper_endpoints._commit_fill(
                supabase, MagicMock(), "user-1", order,
                _fill_res(1, 5.00), quote=None, portfolio=_portfolio(),
            )

        # Position retained: no close-write, no pipeline anomaly alert.
        self.assertEqual(supabase.position_updates, [])
        self.assertEqual(supabase.risk_alerts, [])


if __name__ == "__main__":
    unittest.main()
