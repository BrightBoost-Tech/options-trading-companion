"""
Regression tests for the internal-fill close path of
paper_exit_evaluator._close_position.

Originally PR #6 Commit 5 (migration to the shared close_math + close_helper
pipeline); updated for V17-1 A2 (2026-07-19, Lane 1B), which moved the economic
commit (order-fill + cash + one fill ledger event + the position close) into the
ATOMIC rpc_commit_internal_close_v1 instead of the old non-atomic sequence.

Scope
  1. _map_close_reason — pure unit tests for every reason string
     the exit evaluator or intraday_risk_monitor emits.
  2. Integration tests for the internal-fill close path: realized_pl
     matches the leg-level pipeline output, close_reason is the
     mapped enum value, fill_source='exit_evaluator', committed through
     EXACTLY ONE atomic RPC call (the capturing supabase records the
     position close the RPC performs server-side).
  3. Anomaly paths: unknown reason (aborts BEFORE the RPC →
     routed_to='internal_aborted'); CAS race (the RPC RAISEs
     position_already_closed → routed_to='internal_commit_failed') —
     both write a severity='critical' risk_alert and make ZERO economic writes.

The Alpaca-fill path (position_is_alpaca=True) is covered by
test_reconciler_multileg_sign_convention.py (Commit 4b) — it flows
through _close_position_on_fill, not the internal-fill math.
"""

import sys
import types
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

# Stub alpaca-py surface so imports don't fail in the test venv.
sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
sys.modules.setdefault(
    "alpaca.trading.requests", types.ModuleType("alpaca.trading.requests")
)

from packages.quantum.services import paper_exit_evaluator as pe  # noqa: E402


class TestMapCloseReason(unittest.TestCase):
    """The translation layer between exit-evaluator-emitted reason
    strings and the 9-value close_reason enum."""

    def test_target_profit_legacy_string_maps_to_hit(self):
        self.assertEqual(pe._map_close_reason("target_profit"), "target_profit_hit")

    def test_target_profit_new_string_passthrough(self):
        self.assertEqual(pe._map_close_reason("target_profit_hit"), "target_profit_hit")

    def test_stop_loss_legacy_string_maps_to_hit(self):
        self.assertEqual(pe._map_close_reason("stop_loss"), "stop_loss_hit")

    def test_stop_loss_new_string_passthrough(self):
        self.assertEqual(pe._map_close_reason("stop_loss_hit"), "stop_loss_hit")

    def test_dte_threshold_passthrough(self):
        self.assertEqual(pe._map_close_reason("dte_threshold"), "dte_threshold")

    def test_expiration_day_passthrough(self):
        self.assertEqual(pe._map_close_reason("expiration_day"), "expiration_day")

    def test_risk_envelope_prefix_maps_to_force_close(self):
        """intraday_risk_monitor emits 'risk_envelope:{reason}' — all
        variants map to 'envelope_force_close'."""
        self.assertEqual(
            pe._map_close_reason("risk_envelope:loss_daily"),
            "envelope_force_close",
        )
        self.assertEqual(
            pe._map_close_reason("risk_envelope:loss_weekly"),
            "envelope_force_close",
        )
        self.assertEqual(
            pe._map_close_reason("risk_envelope:sector_concentration"),
            "envelope_force_close",
        )

    def test_unknown_reason_returns_none(self):
        """Unknown reasons MUST NOT be guessed into an enum value.
        Returning None signals the caller to abort and alert."""
        self.assertIsNone(pe._map_close_reason("bogus"))
        self.assertIsNone(pe._map_close_reason("emergency_close"))
        self.assertIsNone(pe._map_close_reason("forced_expiry"))

    def test_none_and_empty_return_none(self):
        self.assertIsNone(pe._map_close_reason(None))
        self.assertIsNone(pe._map_close_reason(""))
        self.assertIsNone(pe._map_close_reason("   "))

    def test_whitespace_stripped_before_lookup(self):
        self.assertEqual(
            pe._map_close_reason("  target_profit  "), "target_profit_hit"
        )


class _FakeRpcChain:
    def __init__(self, parent, name, params):
        self.parent, self.name, self.params = parent, name, params

    def execute(self):
        return self.parent._run_rpc(self.name, self.params)


class _CapturingSupabase:
    """Supabase mock that intercepts the call graph used by
    _close_position's internal-fill path:
      - paper_orders.select().eq().order().limit().execute()            (entry-order routing check)
      - paper_positions.select().eq().single().execute()                (fetch position)
      - paper_orders.select().eq().in_().order().limit().execute()      (idempotency check, returns no rows)
      - paper_orders.update().eq().execute()                            (F-A3 close-reason order_json stamp)
      - rpc('rpc_commit_internal_close_v1', {...}).execute()            (the ONE atomic economic commit)
      - risk_alerts.insert().execute()                                  (anomaly paths only)
    The atomic RPC (recorded on rpc_calls) performs the order-fill + cash + fill
    ledger + position close server-side; the fake records the position close on
    position_updates so the pipeline assertions can inspect it.
    """

    def __init__(self, position, portfolio_cash=10000.0, update_rows=None,
                 position_is_alpaca=False, rpc_raise=None):
        self.position = position
        self.portfolio_cash = portfolio_cash
        self.update_rows = update_rows if update_rows is not None else [{"id": position.get("id", "pos-1")}]
        self.position_is_alpaca = position_is_alpaca
        self.rpc_raise = rpc_raise
        self.position_updates = []  # Writes to paper_positions (via the atomic RPC)
        self.risk_alerts = []
        self.order_updates = []
        self.rpc_calls = []

    def table(self, name):
        return _TableChain(self, name)

    def rpc(self, name, params):
        return _FakeRpcChain(self, name, params)

    def _run_rpc(self, name, params):
        # Faithful stand-in for rpc_commit_internal_close_v1: records the call,
        # then (unless configured to raise) records the SAME paper_positions
        # close-write the assertions below inspect, and returns the typed receipt.
        self.rpc_calls.append((name, dict(params)))
        if self.rpc_raise is not None:
            raise self.rpc_raise
        self.position_updates.append({
            "status": "closed", "quantity": 0,
            "realized_pl": str(params["p_realized_pl"]),
            "close_reason": params["p_close_reason"],
            "fill_source": params["p_fill_source"],
        })
        return MagicMock(data={
            "committed": True, "idempotent_replay": False,
            "order_id": params["p_close_order_id"],
            "position_id": params["p_position_id"],
            "cash_after": self.portfolio_cash,
            "realized_pl": params["p_realized_pl"],
        })


class _TableChain:
    def __init__(self, parent, name):
        self.parent = parent
        self.name = name
        self._op = None  # 'select' | 'update' | 'insert'
        self._payload = None
        self._select_cols = None

    # Fluent builders — all return self so caller can chain.
    def select(self, *args, **kwargs):
        self._op = "select"
        self._select_cols = args[0] if args else "*"
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
        if self.name == "paper_orders":
            if self._op == "select":
                # Idempotency check → no rows. Entry-order routing → one row.
                if self._select_cols and "alpaca_order_id" in str(self._select_cols):
                    return MagicMock(data=[{
                        "id": "order-x",
                        "alpaca_order_id": "alp-1" if self.parent.position_is_alpaca else None,
                    }])
                return MagicMock(data=[])
            if self._op == "update":
                self.parent.order_updates.append(self._payload)
                return MagicMock(data=None)

        if self.name == "paper_positions":
            if self._op == "select":
                return MagicMock(data=self.parent.position)
            if self._op == "update":
                self.parent.position_updates.append(self._payload)
                return MagicMock(data=self.parent.update_rows)

        if self.name == "paper_portfolios":
            if self._op == "select":
                return MagicMock(data={"cash_balance": self.parent.portfolio_cash})
            if self._op == "update":
                return MagicMock(data=None)

        if self.name == "paper_ledger_events":
            if self._op == "insert":
                return MagicMock(data=None)

        if self.name == "risk_alerts":
            if self._op == "insert":
                self.parent.risk_alerts.append(self._payload)
                return MagicMock(data=None)

        return MagicMock(data=[])


def _position(qty, entry_price, current_mark, symbol="SPY", user_id="user-1"):
    return {
        "id": "pos-1",
        "user_id": user_id,
        "symbol": symbol,
        "quantity": qty,
        "avg_entry_price": entry_price,
        "current_mark": current_mark,
        "portfolio_id": "port-1",
        "status": "open",
        "legs": [],
        "strategy_key": "LONG_CALL_DEBIT_SPREAD",
    }


class TestInternalFillPipeline(unittest.TestCase):
    """End-to-end integration through the internal-fill branch:
    reason mapping → compute_realized_pl → close_position_shared.
    """

    def _run_close(self, supabase, reason):
        """Invoke _close_position with enough mocks to skip the
        order-staging bureaucracy and exercise the math + close write."""
        evaluator = pe.PaperExitEvaluator(supabase)

        # Stub out order staging (returns a fake order_id).
        with patch.object(
            pe, "__name__", pe.__name__
        ), patch(
            "packages.quantum.paper_endpoints._stage_order_internal",
            return_value="order-1",
        ), patch(
            "packages.quantum.paper_endpoints.get_analytics_service",
            return_value=MagicMock(),
        ), patch(
            "packages.quantum.services.paper_ledger_service.PaperLedgerService"
        ) as MockLedger, patch(
            "packages.quantum.services.paper_autopilot_service."
            "PaperAutopilotService._resolve_occ_symbol",
            return_value="O:SPY250117C00500000",
        ):
            MockLedger.return_value.emit_fill = MagicMock()
            return evaluator._close_position(
                user_id="user-1",
                position_id="pos-1",
                reason=reason,
            )

    def test_long_debit_target_profit_close(self):
        """Long debit spread: entry 2.00, exit (current_mark) 3.00,
        qty 5. Expected realized_pl = (3.00 - 2.00) × 5 × 100 = +500.00.
        close_reason must map to 'target_profit_hit'; fill_source =
        'exit_evaluator'. realized_pl is written as a string (Decimal
        serialization for PostgREST)."""
        pos = _position(qty=5.0, entry_price=2.00, current_mark=3.00)
        supabase = _CapturingSupabase(pos)

        result = self._run_close(supabase, reason="target_profit")

        self.assertEqual(result.get("processed"), 1)
        self.assertEqual(len(supabase.position_updates), 1)
        upd = supabase.position_updates[0]
        self.assertEqual(upd["status"], "closed")
        self.assertEqual(upd["quantity"], 0)
        self.assertEqual(Decimal(str(upd["realized_pl"])), Decimal("500.00"))
        self.assertEqual(upd["close_reason"], "target_profit_hit")
        self.assertEqual(upd["fill_source"], "exit_evaluator")
        self.assertEqual(supabase.risk_alerts, [])

    def test_long_debit_stop_loss_close(self):
        """Long debit spread moved against us: entry 4.00, exit 1.50,
        qty 3. realized_pl = (1.50 - 4.00) × 3 × 100 = -750.00.
        Maps 'stop_loss' → 'stop_loss_hit'."""
        pos = _position(qty=3.0, entry_price=4.00, current_mark=1.50, symbol="TSLA")
        supabase = _CapturingSupabase(pos)

        self._run_close(supabase, reason="stop_loss")

        upd = supabase.position_updates[0]
        self.assertEqual(Decimal(str(upd["realized_pl"])), Decimal("-750.00"))
        self.assertEqual(upd["close_reason"], "stop_loss_hit")

    def test_short_credit_dte_threshold_close(self):
        """Short credit spread at DTE threshold: entry 1.80 credit
        (qty -4), current_mark 0.80. realized_pl = (1.80 - 0.80) × 4 ×
        100 = +400.00. close_reason = 'dte_threshold'."""
        pos = _position(qty=-4.0, entry_price=1.80, current_mark=0.80, symbol="AMD")
        supabase = _CapturingSupabase(pos)

        self._run_close(supabase, reason="dte_threshold")

        upd = supabase.position_updates[0]
        self.assertEqual(Decimal(str(upd["realized_pl"])), Decimal("400.00"))
        self.assertEqual(upd["close_reason"], "dte_threshold")
        self.assertEqual(upd["fill_source"], "exit_evaluator")

    def test_envelope_force_close_maps_from_prefix(self):
        """intraday_risk_monitor reason 'risk_envelope:loss_daily'
        maps to 'envelope_force_close'."""
        pos = _position(qty=2.0, entry_price=5.00, current_mark=4.50)
        supabase = _CapturingSupabase(pos)

        self._run_close(supabase, reason="risk_envelope:loss_daily")

        upd = supabase.position_updates[0]
        self.assertEqual(upd["close_reason"], "envelope_force_close")
        self.assertEqual(Decimal(str(upd["realized_pl"])), Decimal("-100.00"))


class TestAnomalyPaths(unittest.TestCase):
    """Unknown reasons and duplicate-close races must abort with a
    critical risk_alert and NOT write paper_positions."""

    def _run_close(self, supabase, reason):
        evaluator = pe.PaperExitEvaluator(supabase)
        with patch(
            "packages.quantum.paper_endpoints._stage_order_internal",
            return_value="order-1",
        ), patch(
            "packages.quantum.paper_endpoints.get_analytics_service",
            return_value=MagicMock(),
        ), patch(
            "packages.quantum.services.paper_ledger_service.PaperLedgerService"
        ) as MockLedger, patch(
            "packages.quantum.services.paper_autopilot_service."
            "PaperAutopilotService._resolve_occ_symbol",
            return_value="O:SPY250117C00500000",
        ):
            MockLedger.return_value.emit_fill = MagicMock()
            return evaluator._close_position(
                user_id="user-1",
                position_id="pos-1",
                reason=reason,
            )

    def test_unknown_reason_aborts_with_critical_alert(self):
        pos = _position(qty=1.0, entry_price=2.00, current_mark=3.00)
        supabase = _CapturingSupabase(pos)

        result = self._run_close(supabase, reason="emergency_uncategorized")

        self.assertEqual(result.get("routed_to"), "internal_aborted")
        self.assertEqual(result.get("processed"), 0)
        self.assertEqual(supabase.position_updates, [])
        self.assertEqual(len(supabase.risk_alerts), 1)
        alert = supabase.risk_alerts[0]
        self.assertEqual(alert["severity"], "critical")
        self.assertEqual(alert["alert_type"], "close_path_anomaly")
        self.assertEqual(alert["metadata"]["stage"], "map_close_reason")

    def test_position_already_closed_aborts_with_critical_alert(self):
        """CAS race (V17-1 A2): another handler already closed the position, so
        the atomic RPC RAISEs position_already_closed. The transaction rolled
        back (ZERO economic writes); the caller writes a critical alert and
        returns the not-completed sentinel routed_to='internal_commit_failed' —
        no duplicate close."""
        pos = _position(qty=1.0, entry_price=2.00, current_mark=3.00)
        supabase = _CapturingSupabase(pos, rpc_raise=RuntimeError(
            "commit_internal_close: position_already_closed pos-1 "
            "(existing reason=target_profit_hit, source=alpaca_fill_reconciler)"
        ))

        result = self._run_close(supabase, reason="target_profit")

        self.assertEqual(result.get("routed_to"), "internal_commit_failed")
        self.assertEqual(result.get("processed"), 0)
        self.assertEqual(supabase.position_updates, [])   # no duplicate close write
        self.assertEqual(len(supabase.rpc_calls), 1)      # one attempt, rolled back
        self.assertEqual(len(supabase.risk_alerts), 1)
        alert = supabase.risk_alerts[0]
        self.assertEqual(alert["severity"], "critical")
        self.assertEqual(alert["metadata"]["stage"], "commit_internal_close_cas")


if __name__ == "__main__":
    unittest.main()
