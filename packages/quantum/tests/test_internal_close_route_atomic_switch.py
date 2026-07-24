"""V17-1 A2 (Lane 1B) — the internal/shadow close route commits its economic
effects through ONE atomic RPC (rpc_commit_internal_close_v1), not the old
non-atomic order-filled → cash → ledger → position-close sequence.

TEST DOCTRINE (CLAUDE.md §9): drive the PRODUCTION route end-to-end —
``PaperExitEvaluator._close_position`` — injecting the failure at the DEEPEST
callee (the quote origin ``MarketDataTruthLayer.snapshot_many`` for the fill
price; the RPC boundary for a commit failure) and asserting the TOP-level
outcome (the position closed / held-open, the economic writes present / absent,
the typed non-success). No source-string assertions.

What each scenario pins:
  1/2. debit + credit closes commit via the RPC with the correct cash DIRECTION
       (long→sell→cash-in; short→buy→cash-out); the rpc is called exactly once
       with the expected UNSIGNED magnitude + structural side + realized_pl.
  3.   each prevalidation failure (bad reason / realized-P&L failure) → ZERO
       economic writes + typed partial, and the RPC is NEVER called.
  4.   RPC failure (mocked to raise) → ZERO economic writes, position OPEN,
       typed partial (routed_to='internal_commit_failed').
  5.   CAS race (RPC raises position_already_closed) → one typed conflict, no
       duplicate write.
  6.   exact retry (same STABLE idempotency key) → RPC returns idempotent_replay
       → no duplicate ledger/outcome.
  7.   live/broker route byte-identical: a live close still takes the broker-ack
       path, NEVER the RPC.
  8.   shadow-only fleet close stays internal + atomic (through the RPC).
  9.   a non-finite fill_mid_reference is coerced to None BEFORE the RPC call.
"""

import math
import sys
import types
import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

# Stub alpaca-py surface so imports don't fail in the test venv.
from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

from packages.quantum.services import paper_exit_evaluator as pe  # noqa: E402
from packages.quantum.services.close_math import PartialFillDetected  # noqa: E402

RPC_NAME = "rpc_commit_internal_close_v1"


# ─────────────────────────────────────────────────────────────────────────────
# Capturing Supabase — models the internal close route's reads AND a FAITHFUL
# stand-in for the atomic commit RPC. The fake RPC mirrors the server contract:
# it derives cash direction from the LOCKED position sign, REJECTS a
# non-positive/non-finite magnitude (so a signed/garbage magnitude fails the
# test the same way it would fail in the DB), and returns the typed receipt.
# ─────────────────────────────────────────────────────────────────────────────

class _FakeRpcChain:
    def __init__(self, parent, name, params):
        self.parent, self.name, self.params = parent, name, params

    def execute(self):
        return self.parent._run_rpc(self.name, self.params)


class _CapturingSupabase:
    def __init__(self, position, portfolio_cash=10000.0, routing_mode="shadow_only",
                 entry_alpaca_order_id=None, rpc_raise=None, rpc_replay=False,
                 rpc_noncommitted=False):
        self.position = position
        self.portfolio_cash = portfolio_cash
        self.routing_mode = routing_mode
        self.entry_alpaca_order_id = entry_alpaca_order_id
        self.rpc_raise = rpc_raise
        self.rpc_replay = rpc_replay
        self.rpc_noncommitted = rpc_noncommitted
        self.position_updates = []
        self.portfolio_updates = []
        self.order_updates = []
        self.ledger_fills = []
        self.risk_alerts = []
        self.rpc_calls = []

    def table(self, name):
        return _TableChain(self, name)

    def rpc(self, name, params):
        return _FakeRpcChain(self, name, params)

    def _run_rpc(self, name, params):
        self.rpc_calls.append((name, dict(params)))
        if self.rpc_raise is not None:
            raise self.rpc_raise
        qty = float(self.position["quantity"])
        abs_qty = abs(qty)
        sign = 1 if qty > 0 else -1
        mag = params["p_fill_price_magnitude"]
        mult = params["p_multiplier"]
        # Mirror the RPC's H9 guards: a signed (negative) or non-finite magnitude
        # must reject — this is what catches a Python-side double-negation.
        if mag is None or not math.isfinite(float(mag)) or float(mag) <= 0:
            raise RuntimeError(
                f"commit_internal_close: nonpositive_fill_magnitude ({mag})"
            )
        if self.rpc_noncommitted:
            return MagicMock(data={"committed": False})
        if self.rpc_replay:
            # Idempotent replay: reconstruct receipt from durable truth, ZERO writes.
            return MagicMock(data={
                "committed": True, "idempotent_replay": True,
                "order_id": params["p_close_order_id"],
                "position_id": params["p_position_id"],
                "cash_after": self.portfolio_cash,
                "realized_pl": params["p_realized_pl"],
            })
        cash_delta = sign * float(mag) * abs_qty * float(mult)
        new_cash = self.portfolio_cash + cash_delta
        self.portfolio_cash = new_cash
        self.portfolio_updates.append({"cash_balance": new_cash})
        self.position_updates.append({
            "status": "closed", "quantity": 0,
            "realized_pl": str(params["p_realized_pl"]),
            "close_reason": params["p_close_reason"],
            "fill_source": params["p_fill_source"],
        })
        self.order_updates.append({
            "status": "filled", "avg_fill_price": round(float(mag), 2),
            "order_json": {"fill_quality": params["p_fill_quality"],
                           "fill_mid_reference": params["p_fill_mid_reference"]},
        })
        self.ledger_fills.append({
            "amount": cash_delta, "balance_after": new_cash,
            "metadata": {"side": params["p_close_side"], "qty": abs_qty,
                         "price": float(mag),
                         "fill_quality": params["p_fill_quality"],
                         "fill_mid_reference": params["p_fill_mid_reference"]},
        })
        return MagicMock(data={
            "committed": True, "idempotent_replay": False,
            "order_id": params["p_close_order_id"],
            "position_id": params["p_position_id"],
            "cash_after": new_cash, "ledger_event_id": "ledger-1",
            "realized_pl": params["p_realized_pl"],
        })


class _TableChain:
    def __init__(self, parent, name):
        self.parent, self.name = parent, name
        self._op = None
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
        p = self.parent
        cols = str(self._select_cols or "")
        if self.name == "paper_orders":
            if self._op == "select":
                if "alpaca_order_id" in cols:  # entry-routing check
                    return MagicMock(data=[{
                        "id": "entry-order-1",
                        "alpaca_order_id": p.entry_alpaca_order_id,
                    }])
                return MagicMock(data=[])  # idempotency / order_json reads
            if self._op == "update":
                p.order_updates.append(self._payload)
                return MagicMock(data=None)
        if self.name == "paper_positions":
            if self._op == "select":
                return MagicMock(data=dict(p.position))
            if self._op == "update":
                p.position_updates.append(self._payload)
                return MagicMock(data=[{"id": p.position["id"]}])
        if self.name == "paper_portfolios":
            if self._op == "select":
                if "routing_mode" in cols:  # should_submit_to_broker (P0-A)
                    return MagicMock(data=[{"routing_mode": p.routing_mode}])
                return MagicMock(data={"cash_balance": p.portfolio_cash})
            if self._op == "update":
                p.portfolio_updates.append(self._payload)
                return MagicMock(data=None)
        if self.name == "risk_alerts" and self._op == "insert":
            p.risk_alerts.append(self._payload)
            return MagicMock(data=None)
        return MagicMock(data=[])


# ── Fixtures ────────────────────────────────────────────────────────────────

def _condor_position(qty=-6.0, entry=1.3266, mark=-1.65, symbol="QQQ"):
    """Short iron condor (credit): closing pays a net debit (buy-to-close)."""
    return {
        "id": "pos-qqq-1", "user_id": "user-1", "symbol": symbol,
        "quantity": qty, "avg_entry_price": entry, "current_mark": mark,
        "portfolio_id": "port-1", "status": "open", "strategy_key": "IRON_CONDOR",
        "legs": [
            {"symbol": "O:QQQ260821C00610000", "action": "sell", "type": "call",
             "strike": 610.0, "expiry": "2026-08-21", "quantity": abs(qty)},
            {"symbol": "O:QQQ260821C00620000", "action": "buy", "type": "call",
             "strike": 620.0, "expiry": "2026-08-21", "quantity": abs(qty)},
            {"symbol": "O:QQQ260821P00560000", "action": "sell", "type": "put",
             "strike": 560.0, "expiry": "2026-08-21", "quantity": abs(qty)},
            {"symbol": "O:QQQ260821P00550000", "action": "buy", "type": "put",
             "strike": 550.0, "expiry": "2026-08-21", "quantity": abs(qty)},
        ],
    }


# Executable close = Σ(long bids) − Σ(short asks) = (0.10+0.20) − (1.20+0.80) = −1.70
_QQQ_QUOTES = {
    "O:QQQ260821C00610000": {"bid": 1.10, "ask": 1.20, "last": 1.15},
    "O:QQQ260821C00620000": {"bid": 0.10, "ask": 0.15, "last": 0.12},
    "O:QQQ260821P00560000": {"bid": 0.70, "ask": 0.80, "last": 0.75},
    "O:QQQ260821P00550000": {"bid": 0.20, "ask": 0.25, "last": 0.22},
}


def _nflx_debit_position(qty=3.0, entry=3.6865, mark=4.7355):
    """Long debit vertical: closing receives a net credit (sell-to-close)."""
    return {
        "id": "pos-nflx-1", "user_id": "user-1", "symbol": "NFLX",
        "quantity": qty, "avg_entry_price": entry, "current_mark": mark,
        "portfolio_id": "port-1", "status": "open", "strategy_key": "DEBIT_SPREAD",
        "legs": [
            {"symbol": "O:NFLX260710P00086000", "action": "buy", "type": "put",
             "strike": 86.0, "expiry": "2026-07-10", "quantity": qty},
            {"symbol": "O:NFLX260710P00079000", "action": "sell", "type": "put",
             "strike": 79.0, "expiry": "2026-07-10", "quantity": qty},
        ],
    }


# Executable close = 6.14 bid (long) − 2.009 ask (short) = 4.131 → +133.35
_NFLX_QUOTES = {
    "O:NFLX260710P00086000": {"bid": 6.14, "ask": 7.23, "last": 6.64},
    "O:NFLX260710P00079000": {"bid": 1.89, "ask": 2.009, "last": 2.10},
}


def _run_close(supabase, quotes, reason="stop_loss", position_id="pos-qqq-1",
               exit_price_override=..., extra_patches=None):
    """Drive the PRODUCTION close route with the executable-fill quote origin
    injected at MarketDataTruthLayer.snapshot_many and the order-stager stubbed."""
    evaluator = pe.PaperExitEvaluator(supabase)

    class _FakeTruthLayer:
        def snapshot_many(self, occs):
            return {occ: {"quote": quotes.get(occ, {})} for occ in occs}

    kwargs = {"user_id": "user-1", "position_id": position_id, "reason": reason}
    if exit_price_override is not ...:
        kwargs["exit_price_override"] = exit_price_override

    patches = [
        patch("packages.quantum.paper_endpoints._stage_order_internal",
              return_value="order-close-1"),
        patch("packages.quantum.paper_endpoints.get_analytics_service",
              return_value=MagicMock()),
        patch("packages.quantum.services.market_data_truth_layer.MarketDataTruthLayer",
              _FakeTruthLayer),
    ]
    for extra in (extra_patches or []):
        patches.append(extra)

    import contextlib
    with contextlib.ExitStack() as stack:
        for cm in patches:
            stack.enter_context(cm)
        return evaluator._close_position(**kwargs)


# ── 1/2. Happy-path commits via the RPC with correct cash direction ─────────

class TestCreditCloseCommitsViaRpc(unittest.TestCase):
    def test_credit_close_one_atomic_rpc_buy_side_cash_out(self):
        sb = _CapturingSupabase(_condor_position())
        result = _run_close(sb, _QQQ_QUOTES)

        self.assertEqual(result.get("processed"), 1)
        self.assertFalse(result.get("idempotent_replay"))
        # EXACTLY ONE economic-commit RPC call, with the expected args.
        self.assertEqual(len(sb.rpc_calls), 1)
        name, params = sb.rpc_calls[0]
        self.assertEqual(name, RPC_NAME)
        self.assertEqual(params["p_close_side"], "buy")          # short close = buy-to-close
        self.assertEqual(params["p_fill_source"], "exit_evaluator")
        self.assertEqual(params["p_close_reason"], "stop_loss_hit")
        self.assertAlmostEqual(params["p_fill_price_magnitude"], 1.70, places=6)  # UNSIGNED
        self.assertEqual(params["p_fill_qty"], 6.0)
        self.assertEqual(params["p_fill_quality"], "executable")
        self.assertEqual(Decimal(str(params["p_realized_pl"])), Decimal("-224.04"))
        self.assertNotEqual(Decimal(str(params["p_realized_pl"])), Decimal("1815.96"))
        # Server-derived cash: buy-to-close PAYS 1.70×6×100 = 1,020 → 10,000→8,980.
        self.assertAlmostEqual(sb.portfolio_updates[0]["cash_balance"], 8980.0, places=6)
        self.assertAlmostEqual(sb.ledger_fills[0]["amount"], -1020.0, places=6)

    def test_credit_close_idempotency_key_is_order_derived_and_stable(self):
        sb = _CapturingSupabase(_condor_position())
        _run_close(sb, _QQQ_QUOTES)
        self.assertEqual(
            sb.rpc_calls[0][1]["p_idempotency_key"], "internal_close::order-close-1"
        )


class TestDebitCloseCommitsViaRpc(unittest.TestCase):
    def test_debit_close_one_atomic_rpc_sell_side_cash_in(self):
        sb = _CapturingSupabase(_nflx_debit_position())
        result = _run_close(sb, _NFLX_QUOTES, reason="target_profit",
                            position_id="pos-nflx-1")

        self.assertEqual(result.get("processed"), 1)
        self.assertEqual(len(sb.rpc_calls), 1)
        _, params = sb.rpc_calls[0]
        self.assertEqual(params["p_close_side"], "sell")         # long close = sell-to-close
        self.assertEqual(params["p_close_reason"], "target_profit_hit")
        self.assertAlmostEqual(params["p_fill_price_magnitude"], 4.131, places=3)
        self.assertEqual(Decimal(str(params["p_realized_pl"])), Decimal("133.35"))
        # sell-to-close RECEIVES 4.131×3×100 = 1,239.30 → 10,000→11,239.30.
        self.assertAlmostEqual(sb.portfolio_updates[0]["cash_balance"], 11239.30, places=2)
        self.assertGreater(sb.ledger_fills[0]["amount"], 0)


# ── 3. Prevalidation failures → ZERO writes, RPC never called ───────────────

class TestPrevalidationBlocksTheRpc(unittest.TestCase):
    def test_unknown_reason_aborts_before_the_rpc(self):
        sb = _CapturingSupabase(_condor_position())
        result = _run_close(sb, _QQQ_QUOTES, reason="emergency_uncategorized")

        self.assertEqual(result.get("routed_to"), "internal_aborted")
        self.assertEqual(result.get("processed"), 0)
        self.assertEqual(sb.rpc_calls, [])                 # RPC NEVER called
        self.assertEqual(sb.position_updates, [])
        self.assertEqual(sb.portfolio_updates, [])
        self.assertEqual(sb.ledger_fills, [])
        self.assertEqual(len(sb.risk_alerts), 1)
        self.assertEqual(sb.risk_alerts[0]["severity"], "critical")
        self.assertEqual(sb.risk_alerts[0]["metadata"]["stage"], "map_close_reason")

    def test_realized_pl_failure_aborts_before_the_rpc(self):
        sb = _CapturingSupabase(_condor_position())
        # Inject at the callee: compute_realized_pl raises PartialFillDetected.
        result = _run_close(
            sb, _QQQ_QUOTES,
            extra_patches=[patch.object(
                pe, "compute_realized_pl",
                side_effect=PartialFillDetected("synthetic partial"),
            )],
        )
        self.assertEqual(result.get("routed_to"), "internal_aborted")
        self.assertEqual(result.get("processed"), 0)
        self.assertEqual(sb.rpc_calls, [])                 # RPC NEVER called
        self.assertEqual(sb.position_updates, [])
        self.assertEqual(sb.ledger_fills, [])
        self.assertEqual(sb.risk_alerts[0]["metadata"]["stage"], "compute_realized_pl")


# ── 4/5. RPC failure + CAS race → ZERO writes, position OPEN, typed partial ─

class TestRpcFailureHoldsPositionOpen(unittest.TestCase):
    def test_generic_rpc_failure_leaves_zero_writes_and_types_partial(self):
        sb = _CapturingSupabase(
            _condor_position(),
            rpc_raise=RuntimeError("commit_internal_close: schema_missing_column"),
        )
        result = _run_close(sb, _QQQ_QUOTES)

        self.assertEqual(result.get("routed_to"), "internal_commit_failed")
        self.assertEqual(result.get("processed"), 0)
        self.assertEqual(len(sb.rpc_calls), 1)             # attempted once
        self.assertEqual(sb.position_updates, [])          # atomic: nothing committed
        self.assertEqual(sb.portfolio_updates, [])
        self.assertEqual(sb.ledger_fills, [])
        self.assertEqual(sb.risk_alerts[0]["metadata"]["stage"], "commit_internal_close")

    def test_cas_race_position_already_closed_is_one_typed_conflict(self):
        sb = _CapturingSupabase(
            _condor_position(),
            rpc_raise=RuntimeError(
                "commit_internal_close: position_already_closed pos-qqq-1"
            ),
        )
        result = _run_close(sb, _QQQ_QUOTES)

        self.assertEqual(result.get("routed_to"), "internal_commit_failed")
        self.assertEqual(result.get("processed"), 0)
        self.assertEqual(sb.position_updates, [])          # no duplicate close
        self.assertEqual(sb.ledger_fills, [])
        self.assertEqual(
            sb.risk_alerts[0]["metadata"]["stage"], "commit_internal_close_cas"
        )

    def test_noncommitted_receipt_is_not_a_success(self):
        sb = _CapturingSupabase(_condor_position(), rpc_noncommitted=True)
        result = _run_close(sb, _QQQ_QUOTES)
        self.assertEqual(result.get("routed_to"), "internal_commit_failed")
        self.assertEqual(result.get("processed"), 0)
        self.assertEqual(sb.position_updates, [])


# ── 6. Exact retry (same stable key) → idempotent replay, no duplicate ──────

class TestExactRetryReplays(unittest.TestCase):
    def test_second_call_same_order_replays_with_no_duplicate_writes(self):
        sb = _CapturingSupabase(_condor_position())
        first = _run_close(sb, _QQQ_QUOTES)
        self.assertEqual(first.get("processed"), 1)
        self.assertFalse(first.get("idempotent_replay"))
        writes_after_first = (len(sb.position_updates), len(sb.ledger_fills),
                              len(sb.portfolio_updates))

        # Exact retry: the RPC now recognizes the SAME committed (order,key).
        sb.rpc_replay = True
        second = _run_close(sb, _QQQ_QUOTES)

        self.assertEqual(second.get("processed"), 1)
        self.assertTrue(second.get("idempotent_replay"))     # replay, not a new commit
        # No duplicate economic effect on the replay.
        self.assertEqual(
            (len(sb.position_updates), len(sb.ledger_fills), len(sb.portfolio_updates)),
            writes_after_first,
        )
        # The idempotency key was IDENTICAL across both attempts (stable, order-derived).
        self.assertEqual(
            sb.rpc_calls[0][1]["p_idempotency_key"],
            sb.rpc_calls[1][1]["p_idempotency_key"],
        )


# ── 7. Live/broker route byte-identical — NEVER the RPC ─────────────────────

class TestLiveRouteNeverUsesTheRpc(unittest.TestCase):
    def test_p0a_routing_edge_live_close_held_open_no_rpc(self):
        # live_eligible portfolio, no alpaca entry → reaches the P0-A guard,
        # held OPEN (unknown_reconciling). The internal-fill block is unreachable.
        sb = _CapturingSupabase(_condor_position(), routing_mode="live_eligible")
        result = _run_close(sb, _QQQ_QUOTES)
        self.assertEqual(result.get("routed_to"), "unknown_reconciling")
        self.assertEqual(result.get("processed"), 0)
        self.assertEqual(sb.rpc_calls, [])                 # NEVER the internal RPC
        self.assertEqual(sb.position_updates, [])
        self.assertEqual(sb.ledger_fills, [])

    def test_broker_submit_path_returns_alpaca_no_rpc(self):
        # A genuinely live-routed close (alpaca entry + live_eligible) takes the
        # submit_and_track broker-ack path and returns 'alpaca' — never the RPC.
        sb = _CapturingSupabase(
            _condor_position(), routing_mode="live_eligible",
            entry_alpaca_order_id="alp-entry-1",
        )
        result = _run_close(
            sb, _QQQ_QUOTES,
            extra_patches=[
                patch("packages.quantum.brokers.alpaca_order_handler.submit_and_track",
                      return_value={}),
                patch("packages.quantum.brokers.alpaca_client.get_alpaca_client",
                      return_value=MagicMock()),
            ],
        )
        self.assertEqual(result.get("routed_to"), "alpaca")
        self.assertEqual(sb.rpc_calls, [])                 # NEVER the internal RPC


# ── 8. Shadow-only fleet close stays internal + atomic ──────────────────────

class TestShadowOnlyStaysInternalAtomic(unittest.TestCase):
    def test_shadow_only_portfolio_commits_through_the_rpc(self):
        sb = _CapturingSupabase(_condor_position(), routing_mode="shadow_only")
        result = _run_close(sb, _QQQ_QUOTES)
        self.assertEqual(result.get("processed"), 1)
        self.assertEqual(len(sb.rpc_calls), 1)
        self.assertEqual(sb.rpc_calls[0][0], RPC_NAME)


# ── 9. Non-finite provenance coerced to None before the RPC ─────────────────

class TestNonFiniteFillMidReferenceCoerced(unittest.TestCase):
    def test_infinite_mid_reference_becomes_none_before_the_rpc(self):
        # exit_price_override = +inf makes _mid_reference non-finite, while the
        # executable quotes still yield a finite fill magnitude.
        sb = _CapturingSupabase(_condor_position())
        result = _run_close(sb, _QQQ_QUOTES, exit_price_override=float("inf"))

        self.assertEqual(result.get("processed"), 1)
        _, params = sb.rpc_calls[0]
        self.assertIsNone(params["p_fill_mid_reference"])   # coerced away
        self.assertTrue(math.isfinite(params["p_fill_price_magnitude"]))
        self.assertGreater(params["p_fill_price_magnitude"], 0)


if __name__ == "__main__":
    unittest.main()
