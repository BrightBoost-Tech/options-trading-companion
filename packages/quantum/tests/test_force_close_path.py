"""
Regression tests for the 2026-05-18 CSX force-close incident.

Two bugs ship in the same PR because they share the same incident
shape and the same files:

BUG-A — scale-asymmetric unrealized_pl in
    intraday_risk_monitor._refresh_marks. Multi-leg branch mixed
    per-1-spread leg_total against per-N-spread entry_value,
    fabricating large losses for any position with pos.quantity > 1
    and force-closing it within seconds of opening.

BUG-C — retry loop fired against an already-closed position. Two
    idempotency checks omitted 'filled' (internal-paper close orders
    fill synchronously), _close_position had no `status='closed'`
    guard, and the violation loop's in-memory positions list was
    never refreshed after a successful close.

Tests are organized:
  * TestRefreshMarksScale — FIX 1 math invariants
  * TestExecuteForceCloseIdempotency — FIX 2a (intraday side+status)
  * TestClosePositionAlreadyClosed — FIX 2c (status='closed' / qty=0)
  * TestClosePositionIdempotencyWithFilledClose — FIX 2b (exit side+status)
  * TestViolationLoopClosedSet — FIX 2d (in-cycle dedup)
  * TestFullCycleNoSpuriousAlerts — incident replay end-to-end
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Stub alpaca-py so imports resolve in the test venv.
sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
sys.modules.setdefault(
    "alpaca.trading.requests", types.ModuleType("alpaca.trading.requests")
)

from packages.quantum.jobs.handlers import intraday_risk_monitor as irm  # noqa: E402
from packages.quantum.services import paper_exit_evaluator as pe  # noqa: E402


# ─────────────────────────────────────────────────────────────────
# Test helpers
# ─────────────────────────────────────────────────────────────────


def _csx_debit_spread_position(quantity, avg_entry_price=2.50, leg_quantity=None):
    """4-contract CSX call debit spread, like the 2026-05-18 incident.

    #3 (2026-05-28): legs default to FULL-COUNT (leg.quantity == abs(quantity)),
    the pinned convention. Pass `leg_quantity` to construct a deliberately
    non-full-count (per-spread) row for the seam/guard regression tests.
    """
    lq = leg_quantity if leg_quantity is not None else abs(int(quantity))
    return {
        "id": "pos-csx",
        "user_id": "user-1",
        "symbol": "CSX",
        "quantity": quantity,
        "avg_entry_price": avg_entry_price,
        "current_mark": avg_entry_price,
        "portfolio_id": "port-1",
        "status": "open",
        "strategy_key": "CSX_long_call_debit_spread",
        "legs": [
            {
                "type": "call",
                "action": "buy",
                "expiry": "2026-06-18",
                "strike": 44,
                "symbol": "O:CSX260618C00044000",
                "quantity": lq,
            },
            {
                "type": "call",
                "action": "sell",
                "expiry": "2026-06-18",
                "strike": 48.5,
                "symbol": "O:CSX260618C00048500",
                "quantity": lq,
            },
        ],
    }


def _short_credit_spread_position(quantity, avg_entry_price=0.50, leg_quantity=None):
    """4-contract short put credit spread (sell higher put, buy lower put).

    #3: legs default to full-count (leg.quantity == abs(quantity))."""
    lq = leg_quantity if leg_quantity is not None else abs(int(quantity))
    return {
        "id": "pos-spy",
        "user_id": "user-1",
        "symbol": "SPY",
        "quantity": quantity,
        "avg_entry_price": avg_entry_price,
        "current_mark": avg_entry_price,
        "portfolio_id": "port-1",
        "status": "open",
        "strategy_key": "SPY_short_put_credit_spread",
        "legs": [
            {
                "type": "put",
                "action": "sell",
                "expiry": "2026-06-18",
                "strike": 500,
                "symbol": "O:SPY260618P00500000",
                "quantity": lq,
            },
            {
                "type": "put",
                "action": "buy",
                "expiry": "2026-06-18",
                "strike": 495,
                "symbol": "O:SPY260618P00495000",
                "quantity": lq,
            },
        ],
    }


def _snapshots_for_csx(mid_44, mid_48_5):
    """Build a snapshots dict matching MarketDataTruthLayer.snapshot_many."""
    return {
        "O:CSX260618C00044000": {"quote": {"bid": mid_44 - 0.05, "ask": mid_44 + 0.05}},
        "O:CSX260618C00048500": {"quote": {"bid": mid_48_5 - 0.05, "ask": mid_48_5 + 0.05}},
    }


def _snapshots_for_spy_put_spread(mid_500, mid_495):
    return {
        "O:SPY260618P00500000": {"quote": {"bid": mid_500 - 0.05, "ask": mid_500 + 0.05}},
        "O:SPY260618P00495000": {"quote": {"bid": mid_495 - 0.05, "ask": mid_495 + 0.05}},
    }


def _run_refresh_marks(positions, snapshots_map):
    """Construct an IntradayRiskMonitor with a stubbed admin client and
    MarketDataTruthLayer, then invoke _refresh_marks on the given positions."""
    with patch.object(irm, "get_admin_client", return_value=MagicMock()), patch(
        "packages.quantum.services.market_data_truth_layer.MarketDataTruthLayer"
    ) as MockTruth:
        instance = MockTruth.return_value
        instance.snapshot_many.return_value = snapshots_map
        monitor = irm.IntradayRiskMonitor()
        return monitor._refresh_marks(positions)


# ─────────────────────────────────────────────────────────────────
# FIX 1 — scale-consistent unrealized_pl
# ─────────────────────────────────────────────────────────────────


class TestRefreshMarksScale(unittest.TestCase):
    """Multi-leg unrealized_pl must be scale-consistent and scaled exactly ONCE.

    #3 (2026-05-28): the convention is now pinned FULL-COUNT (legs[].quantity ==
    contract count) and both mark readers route through the single shared
    risk.mark_math implementation. These fixtures are full-count; the reader
    returns the correct value for each. The original BUG-A defense ("the reader
    handles per-spread") is TRANSFORMED into:
      (1) the reader is correct on the pinned full-count convention (these tests);
      (2) a per-spread row is PREVENTED at the fill seam (see
          test_legs_convention.py / coerce_legs_to_full_count); and
      (3) the reader assumes full-count — a per-spread row fed to it produces a
          WRONG value (test_per_spread_row_is_not_silently_corrected below),
          which is exactly why prevention (2) is load-bearing, and the #987
          payoff-bound guard remains the catch for out-of-bounds corruption.
    """

    def test_qty_one_debit_baseline_unchanged(self):
        """qty=1 full-count baseline. Anchors the regression on the common case.
        leg_qty=1==contracts → current_value=(2.40-0.20)*100*1=$220;
        entry=2.50*1*100=$250; PL=220-250=-$30."""
        pos = _csx_debit_spread_position(quantity=1.0, avg_entry_price=2.50)
        snaps = _snapshots_for_csx(mid_44=2.40, mid_48_5=0.20)
        # Per-spread leg_total = (2.40 - 0.20) * 100 = $220
        # Per-spread entry = 2.50 * 100 = $250
        # PL = (220 - 250) * 1 = -$30
        out = _run_refresh_marks([pos], snaps)
        self.assertAlmostEqual(out[0]["unrealized_pl"], -30.0, places=2)
        self.assertAlmostEqual(out[0]["current_mark"], 2.20, places=2)

    def test_qty_four_debit_loss_is_scaled_not_fabricated(self):
        """The 2026-05-18 CSX incident: 4-contract spread, entry $2.50,
        current spread mid $2.20. Pre-fix produced unrealized_pl ≈ -$780.
        Post-fix must produce -$120 (4 × ($220-$250))."""
        pos = _csx_debit_spread_position(quantity=4.0, avg_entry_price=2.50)
        snaps = _snapshots_for_csx(mid_44=2.40, mid_48_5=0.20)
        out = _run_refresh_marks([pos], snaps)
        self.assertAlmostEqual(out[0]["unrealized_pl"], -120.0, places=2)
        self.assertAlmostEqual(out[0]["current_mark"], 2.20, places=2)
        # Sanity: nowhere near the pre-fix fabricated value.
        self.assertGreater(out[0]["unrealized_pl"], -200.0)

    def test_qty_four_debit_gain_is_scaled_not_inflated(self):
        """Inverse direction — current spread mid $2.80, qty=4.
        Pre-fix would have produced inflated (+$130 expected real,
        but inflated by the per-1 vs per-N mismatch). Post-fix: +$120."""
        pos = _csx_debit_spread_position(quantity=4.0, avg_entry_price=2.50)
        snaps = _snapshots_for_csx(mid_44=3.00, mid_48_5=0.20)
        # per_spread_value = (3.00 - 0.20) * 100 = $280
        # PL = (280 - 250) * 4 = +$120
        out = _run_refresh_marks([pos], snaps)
        self.assertAlmostEqual(out[0]["unrealized_pl"], 120.0, places=2)
        self.assertAlmostEqual(out[0]["current_mark"], 2.80, places=2)

    def test_short_credit_spread_qty_four_pl(self):
        """Short put credit spread, qty=-4, entry $0.50 credit, current
        liability $0.30/spread. PL = ($0.50 - $0.30) × 4 × 100 = +$80."""
        pos = _short_credit_spread_position(quantity=-4.0, avg_entry_price=0.50)
        # sell 500P @ 0.55, buy 495P @ 0.25 → leg_total = -55 + 25 = -$30 per spread
        snaps = _snapshots_for_spy_put_spread(mid_500=0.55, mid_495=0.25)
        out = _run_refresh_marks([pos], snaps)
        # per_spread_value = -$30 (signed by convention)
        # per_spread_entry = $50
        # qty_signed < 0 branch: per_spread_pl = 50 - abs(-30) = 20
        # total = 20 * 4 = $80
        self.assertAlmostEqual(out[0]["unrealized_pl"], 80.0, places=2)

    def test_qty_zero_does_not_raise(self):
        """Edge: position quantity=0 (in-flight close). Should not raise;
        PL collapses to 0."""
        pos = _csx_debit_spread_position(quantity=0.0, avg_entry_price=2.50)
        snaps = _snapshots_for_csx(mid_44=2.40, mid_48_5=0.20)
        out = _run_refresh_marks([pos], snaps)
        self.assertEqual(out[0]["unrealized_pl"], 0.0)

    def test_single_leg_branch_remains_scale_consistent(self):
        """The single-leg branch was already scale-consistent (both
        current_value and entry_value scaled by qty). This test pins
        that behavior so the fix doesn't accidentally regress it."""
        pos = {
            "id": "pos-1leg",
            "user_id": "user-1",
            "symbol": "O:SPY260618C00500000",
            "quantity": 3.0,
            "avg_entry_price": 1.50,
            "current_mark": 1.50,
            "portfolio_id": "port-1",
            "status": "open",
            "legs": [],
        }
        snaps = {"O:SPY260618C00500000": {"quote": {"bid": 1.95, "ask": 2.05}}}
        out = _run_refresh_marks([pos], snaps)
        # mid=2.00, qty=3 → current = 2.00 * 100 * 3 = 600; entry = 1.50 * 3 * 100 = 450
        # PL = 600 - 450 = 150
        self.assertAlmostEqual(out[0]["unrealized_pl"], 150.0, places=2)

    def test_per_spread_row_is_not_silently_corrected(self):
        """BUG-A defense, transformed (#3). The reader assumes the pinned
        full-count convention; it does NOT silently re-handle a per-spread row.

        A 4-contract position stored per-spread (leg.quantity=1) — the exact
        invalid shape the 2026-05-18 CSX BUG-A had — produces the FABRICATED
        value (leg-sum at per-1 = $220, finalized against the per-4 entry $1000
        → -$780), NOT the correct full-count -$120. This is intentional: the
        reader must not contain a leg.quantity-convention branch (the abandoned
        #2 fix re-armed BUG-A by adding one). Correctness instead depends on:
          - the fill-seam coercion (coerce_legs_to_full_count) PREVENTING any
            per-spread row from ever being persisted, and
          - the #987 payoff-bound guard clamping out-of-bounds corruption.
        If a future change makes this assertion fail (reader "fixes" per-spread),
        that is the signal it re-introduced the convention branch this guards
        against — re-read docs/loud_error_doctrine.md (#1/#2/#3 mis-split)."""
        pos = _csx_debit_spread_position(quantity=4.0, avg_entry_price=2.50, leg_quantity=1)
        snaps = _snapshots_for_csx(mid_44=2.40, mid_48_5=0.20)
        out = _run_refresh_marks([pos], snaps)
        # leg-sum at per-1 = $220; finalize_mark(qty=4) entry=$1000 → -$780.
        self.assertAlmostEqual(out[0]["unrealized_pl"], -780.0, places=2)
        # And explicitly NOT the correct full-count value (which only a
        # full-count row, guaranteed by the seam, would produce).
        self.assertNotAlmostEqual(out[0]["unrealized_pl"], -120.0, places=2)


# ─────────────────────────────────────────────────────────────────
# FIX 2a — intraday monitor idempotency (filled+cancelled + side filter)
# ─────────────────────────────────────────────────────────────────


class _IdempotencyCapture:
    """Captures the SQL chain built for the paper_orders idempotency
    lookup and returns a configurable row set."""

    def __init__(self, existing_close_rows=None):
        self.existing_close_rows = existing_close_rows or []
        self.captured_status_filter = None
        self.captured_side_filter = None
        self.captured_position_id_filter = None
        # _execute_force_close → evaluator._close_position invocation
        self.close_invoked = False

    def table(self, name):
        return _IdempotencyChain(self, name)


class _IdempotencyChain:
    def __init__(self, parent, name):
        self.parent = parent
        self.name = name
        self._op = None
        self._payload = None

    def select(self, *a, **k):
        self._op = "select"
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def eq(self, col, val):
        if col == "position_id":
            self.parent.captured_position_id_filter = val
        elif col == "side":
            self.parent.captured_side_filter = val
        return self

    def in_(self, col, vals):
        if col == "status":
            self.parent.captured_status_filter = list(vals)
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def single(self):
        return self

    def execute(self):
        if self.name == "paper_orders" and self._op == "select":
            return MagicMock(data=self.parent.existing_close_rows)
        return MagicMock(data=[])


class TestExecuteForceCloseIdempotency(unittest.TestCase):
    """FIX 2a — intraday_risk_monitor._execute_force_close idempotency
    check must include 'filled' and 'cancelled' AND scope by close side."""

    def _build_monitor(self, supabase):
        with patch.object(irm, "get_admin_client", return_value=supabase):
            return irm.IntradayRiskMonitor()

    def test_filled_close_blocks_retry(self):
        """A previous close order (side='sell', status='filled') on
        this position must block a retry."""
        capture = _IdempotencyCapture(
            existing_close_rows=[{"id": "ord-prior-close", "status": "filled"}]
        )
        monitor = self._build_monitor(capture)
        result = monitor._execute_force_close(
            position={"id": "pos-1", "quantity": 4.0, "symbol": "CSX"},
            reason="intraday_stop_loss",
            user_id="user-1",
        )
        self.assertFalse(result, "Force-close should be skipped when a filled close order exists")
        # Confirm 'filled' was in the queried status list
        self.assertIn("filled", capture.captured_status_filter or [])
        self.assertIn("cancelled", capture.captured_status_filter or [])
        # Confirm side filter scoped to close side (long pos → sell)
        self.assertEqual(capture.captured_side_filter, "sell")

    def test_long_position_filter_is_sell_side(self):
        """Long debit (qty>0) → close is sell. Side filter must be 'sell'."""
        capture = _IdempotencyCapture()
        monitor = self._build_monitor(capture)
        # Patch _close_position to no-op so we just exercise the idempotency check
        with patch(
            "packages.quantum.services.paper_exit_evaluator.PaperExitEvaluator"
        ) as MockEval:
            MockEval.return_value._close_position.return_value = {"order_id": "ord-x"}
            monitor._execute_force_close(
                position={"id": "pos-long", "quantity": 4.0, "symbol": "CSX"},
                reason="intraday_stop_loss",
                user_id="user-1",
            )
        self.assertEqual(capture.captured_side_filter, "sell")

    def test_short_position_filter_is_buy_side(self):
        """Short credit (qty<0) → close is buy. Side filter must be 'buy'."""
        capture = _IdempotencyCapture()
        monitor = self._build_monitor(capture)
        with patch(
            "packages.quantum.services.paper_exit_evaluator.PaperExitEvaluator"
        ) as MockEval:
            MockEval.return_value._close_position.return_value = {"order_id": "ord-x"}
            monitor._execute_force_close(
                position={"id": "pos-short", "quantity": -4.0, "symbol": "SPY"},
                reason="intraday_stop_loss",
                user_id="user-1",
            )
        self.assertEqual(capture.captured_side_filter, "buy")


# ─────────────────────────────────────────────────────────────────
# FIX 2c — _close_position early-return on status='closed' / qty=0
# ─────────────────────────────────────────────────────────────────


class _CapturingSupabase:
    """Minimal Supabase mock matching the call graph of
    paper_exit_evaluator._close_position up to the early-return point."""

    def __init__(self, position, position_is_alpaca=False, existing_close_rows=None):
        self.position = position
        self.position_is_alpaca = position_is_alpaca
        self.existing_close_rows = existing_close_rows or []
        self.captured_status_filter = None
        self.captured_side_filter = None
        self.position_updates = []
        self.risk_alerts = []

    def table(self, name):
        return _CapturingChain(self, name)


class _CapturingChain:
    def __init__(self, parent, name):
        self.parent = parent
        self.name = name
        self._op = None
        self._payload = None
        self._select_cols = None

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

    def eq(self, col, val):
        if col == "side":
            self.parent.captured_side_filter = val
        return self

    def neq(self, *a, **k):
        return self

    def in_(self, col, vals):
        if col == "status":
            self.parent.captured_status_filter = list(vals)
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def single(self):
        return self

    def execute(self):
        if self.name == "paper_orders":
            if self._op == "select":
                cols = str(self._select_cols)
                # Entry-routing lookup (selects alpaca_order_id)
                if "alpaca_order_id" in cols:
                    return MagicMock(data=[
                        {"id": "ord-entry",
                         "alpaca_order_id": "alp-1" if self.parent.position_is_alpaca else None}
                    ])
                # Idempotency lookup
                return MagicMock(data=self.parent.existing_close_rows)
            if self._op == "update":
                return MagicMock(data=None)

        if self.name == "paper_positions":
            if self._op == "select":
                return MagicMock(data=self.parent.position)
            if self._op == "update":
                self.parent.position_updates.append(self._payload)
                return MagicMock(data=[{"id": "pos-1"}])

        if self.name == "risk_alerts":
            if self._op == "insert":
                self.parent.risk_alerts.append(self._payload)
                return MagicMock(data=None)

        return MagicMock(data=[])


class TestClosePositionAlreadyClosed(unittest.TestCase):
    """FIX 2c — _close_position must early-return without staging an
    order or writing alerts when the freshly-fetched position state
    shows status='closed' or quantity=0."""

    def _invoke_close(self, supabase, position_id="pos-1"):
        """Patch out the cascading imports (analytics/ledger) that the
        function pulls in at module-import time; only the routing check
        + position fetch + early-return need real execution."""
        evaluator = pe.PaperExitEvaluator(supabase)
        with patch(
            "packages.quantum.paper_endpoints.get_analytics_service",
            return_value=MagicMock(),
        ), patch(
            "packages.quantum.paper_endpoints._stage_order_internal",
            return_value="order-stub",
        ):
            return evaluator._close_position(
                user_id="user-1",
                position_id=position_id,
                reason="risk_envelope:loss_daily",
            )

    def test_status_closed_returns_already_closed_no_order_no_alert(self):
        pos = {
            "id": "pos-1",
            "user_id": "user-1",
            "symbol": "CSX",
            "quantity": 0,
            "avg_entry_price": 2.50,
            "current_mark": 2.50,
            "portfolio_id": "port-1",
            "status": "closed",
            "legs": [],
        }
        supabase = _CapturingSupabase(pos)
        result = self._invoke_close(supabase)
        self.assertEqual(result.get("routed_to"), "already_closed")
        self.assertEqual(result.get("processed"), 0)
        self.assertEqual(result.get("order_id"), None)
        # No spurious alerts written (this is expected behavior, not error)
        self.assertEqual(supabase.risk_alerts, [])
        # No close-write attempted on paper_positions
        self.assertEqual(supabase.position_updates, [])

    def test_quantity_zero_open_status_also_returns_already_closed(self):
        """Defense in depth: even if some race left status='open' but
        quantity=0, the function must refuse to operate (compute_realized_pl
        would otherwise crash on qty=0)."""
        pos = {
            "id": "pos-1",
            "user_id": "user-1",
            "symbol": "CSX",
            "quantity": 0,
            "avg_entry_price": 2.50,
            "current_mark": 2.50,
            "portfolio_id": "port-1",
            "status": "open",
            "legs": [],
        }
        supabase = _CapturingSupabase(pos)
        result = self._invoke_close(supabase)
        self.assertEqual(result.get("routed_to"), "already_closed")
        self.assertEqual(supabase.risk_alerts, [])


# ─────────────────────────────────────────────────────────────────
# FIX 2b — paper_exit_evaluator idempotency (filled + side filter)
# ─────────────────────────────────────────────────────────────────


class TestClosePositionIdempotencyWithFilledClose(unittest.TestCase):
    """FIX 2b — paper_exit_evaluator._close_position idempotency check
    must include 'filled' and 'cancelled' AND scope by close side, so
    a prior synchronously-filled close order blocks a retry on a
    position whose state hasn't yet updated."""

    def _invoke_close(self, supabase, position_id="pos-1"):
        evaluator = pe.PaperExitEvaluator(supabase)
        with patch(
            "packages.quantum.paper_endpoints.get_analytics_service",
            return_value=MagicMock(),
        ), patch(
            "packages.quantum.paper_endpoints._stage_order_internal",
            return_value="order-stub",
        ):
            try:
                return evaluator._close_position(
                    user_id="user-1",
                    position_id=position_id,
                    reason="risk_envelope:loss_daily",
                )
            except Exception:
                # The minimal mock may not satisfy the downstream
                # staging machinery; the idempotency filter is set
                # well before that — capture it and let the test inspect.
                return None

    def test_filled_sell_close_blocks_long_retry(self):
        """Long position; a prior SELL close already filled. Even if
        position.status is still 'open' (in-flight reconciliation
        between paper_orders fill and paper_positions update), the
        idempotency check should catch it before _close_position stages
        a duplicate."""
        pos = {
            "id": "pos-1",
            "user_id": "user-1",
            "symbol": "CSX",
            "quantity": 4.0,
            "avg_entry_price": 2.50,
            "current_mark": 2.50,
            "portfolio_id": "port-1",
            "status": "open",
            "legs": [],
        }
        supabase = _CapturingSupabase(
            pos,
            existing_close_rows=[
                {"id": "ord-prior-sell-close", "status": "filled",
                 "created_at": "2026-05-18T16:30:19Z"},
            ],
        )
        result = self._invoke_close(supabase)
        self.assertIsNotNone(result, "Idempotency-skip path should return cleanly")
        self.assertEqual(result.get("routed_to"), "skipped_duplicate")
        # Side filter scoped to 'sell' (long position → close = sell)
        self.assertEqual(supabase.captured_side_filter, "sell")
        # 'filled' present in the status list
        self.assertIn("filled", supabase.captured_status_filter or [])
        self.assertIn("cancelled", supabase.captured_status_filter or [])

    def test_short_position_filter_is_buy_side(self):
        """Short position; idempotency check filter must be side='buy'
        (close-to-cover)."""
        pos = {
            "id": "pos-1",
            "user_id": "user-1",
            "symbol": "SPY",
            "quantity": -4.0,
            "avg_entry_price": 0.50,
            "current_mark": 0.50,
            "portfolio_id": "port-1",
            "status": "open",
            "legs": [],
        }
        supabase = _CapturingSupabase(pos)
        # Don't care about end-to-end result here; just inspect the filter
        # set by the idempotency lookup.
        self._invoke_close(supabase)
        self.assertEqual(supabase.captured_side_filter, "buy")


# ─────────────────────────────────────────────────────────────────
# FIX 2d — violation loop closed-set dedup
# ─────────────────────────────────────────────────────────────────


class TestViolationLoopClosedSet(unittest.TestCase):
    """FIX 2d — within a single intraday_risk_monitor cycle, after a
    position has been successfully force-closed once, subsequent
    iterations of the violation loop (5a stop_loss or 5b envelope)
    must NOT attempt close again on the same position."""

    def test_source_level_closed_set_present(self):
        """Source-level structural assertion: the closed_in_this_cycle
        set is declared, populated on success, and consulted in both
        5a and 5b loop branches."""
        from pathlib import Path
        src = Path(irm.__file__).read_text(encoding="utf-8")
        self.assertIn("closed_in_this_cycle", src,
                      "Closed-set must be declared by name")
        # Population: on success, add to set
        self.assertIn("closed_in_this_cycle.add", src)
        # Consultation: skip if pid already closed
        self.assertIn("in closed_in_this_cycle", src)


# ─────────────────────────────────────────────────────────────────
# Full-cycle incident replay
# ─────────────────────────────────────────────────────────────────


class TestFullCycleNoSpuriousAlerts(unittest.TestCase):
    """End-to-end incident replay: 4-contract debit spread + 2
    force-close-severity violations against it. Pre-fix this scenario
    produced 4+ spurious 'compute_realized_pl: qty must be positive'
    alerts. Post-fix it produces at most 1 force-close attempt and 0
    spurious alerts."""

    def test_two_violations_against_same_position_fire_close_once(self):
        positions = [
            {"id": "pos-csx", "quantity": 4.0, "symbol": "CSX"},
        ]
        # Two violations both target pos-csx
        viol_loss_daily = MagicMock(
            severity="force_close", envelope="loss_daily",
            message="daily loss exceeded",
        )
        viol_loss_symbol = MagicMock(
            severity="force_close", envelope="loss_per_symbol",
            message="symbol loss exceeded",
        )
        envelope_result = MagicMock(
            violations=[viol_loss_daily, viol_loss_symbol],
            force_close_ids=["pos-csx"],
            passed=False,
            sizing_multiplier=1,
        )

        # Stub out the real envelope-check + position-level exit
        # evaluation; we only care about the violation-loop arithmetic.
        with patch.object(irm, "get_admin_client", return_value=MagicMock()):
            monitor = irm.IntradayRiskMonitor()

        monitor._fetch_open_positions = MagicMock(return_value=positions)
        monitor._refresh_marks = MagicMock(return_value=positions)
        monitor._estimate_equity = MagicMock(return_value=681.0)
        monitor._compute_weekly_pnl = MagicMock(return_value=0.0)

        # Track force_close invocations against this position
        force_close_calls = []

        def fake_execute_force_close(pos, reason, user_id,
                                     mapped_close_reason=None, reason_detail=None):
            # reason_detail added by F-A3-1 Part B (5b threads violation.envelope).
            force_close_calls.append((pos.get("id"), reason))
            return True  # Always succeed on first call; closed-set then dedups

        monitor._execute_force_close = fake_execute_force_close

        with patch(
            "packages.quantum.risk.risk_envelope.check_all_envelopes",
            return_value=envelope_result,
        ), patch(
            "packages.quantum.risk.risk_envelope.EnvelopeConfig"
        ) as MockConfig, patch(
            "packages.quantum.services.paper_exit_evaluator.evaluate_position_exit",
            return_value=None,  # No 5a stop_loss trigger in this scenario
        ), patch(
            "packages.quantum.services.paper_exit_evaluator.EXIT_CONDITIONS", {}
        ):
            MockConfig.from_env.return_value = MagicMock()
            result = monitor._check_user("user-1")

        # Both violations would have produced 1 close attempt each pre-fix.
        # Post-fix the closed_in_this_cycle set dedups; only the first
        # iteration of the inner loop fires.
        self.assertEqual(len(force_close_calls), 1,
                         f"Expected 1 close attempt, got {len(force_close_calls)}: "
                         f"{force_close_calls}")
        self.assertEqual(result.get("force_closes_submitted"), 1)
        # And the violation count is still reported truthfully (2 violations
        # in result.violations).
        self.assertEqual(result.get("violations"), 2)


if __name__ == "__main__":
    unittest.main()
