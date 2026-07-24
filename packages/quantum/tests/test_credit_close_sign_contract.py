"""F-CREDIT-SIGN (2026-07-15 nightly audit, A2, HIGH) — internal-fill closes
of CREDIT structures double-negated the signed executable mark.

THE BUG. `_select_internal_fill_price` returns the SIGNED `achievable_close`
(negative = closing the structure pays a net debit — every credit-structure
buy-back). Every consumer downstream of the fill seam is contractually
UNSIGNED-magnitude + structural-direction:

  - `paper_orders.avg_fill_price` — a broker fill price is always positive;
  - the cash delta — direction comes from the close `side` (buy/sell);
  - the fill ledger amount — same;
  - `synth_legs.filled_avg_price` → `close_math.compute_realized_pl`, which
    signs by LEG ACTION and documents `filled_avg_price` as "a positive
    per-contract price".

Feeding the signed mark negates twice: deterministic error
2 × |close mark| × qty × 100, wrong in SIGN and MAGNITUDE. 2026-07-14 QQQ
`c1c9ad04` (6-lot iron condor, credit entry 1.3266, corroborated close
−1.70): truth −$224.04; booked +$1,815.96; the shadow cash ledger was
CREDITED +$1,020 for a buy-to-close that pays out $1,020. #1056 (06-11)
fixed the identical class at the broker-LIMIT seam (`_close_limit_and_
direction` returns the magnitude); #1017 (06-12) opened the FILL seam a day
later. The fix routes the internal fill through the same canonical owner of
"unsigned magnitude + structural direction": `_close_limit_and_direction`.

V17-1 A2 (2026-07-19, Lane 1B): the economic commit (order-fill + cash + one
fill ledger event + the position close) now lands ATOMICALLY through
`rpc_commit_internal_close_v1` instead of the old non-atomic write sequence.
The sign contract is therefore asserted AT THE ATOMIC BOUNDARY: the UNSIGNED
`p_fill_price_magnitude` and the structural `p_close_side` the Python hands the
RPC, and the resulting server-derived cash. The capturing supabase's fake RPC
is a FAITHFUL stand-in for the committed transaction (Lane 1A tests the RPC
internals) — crucially it mirrors the RPC's H9 guard and REJECTS a non-positive
magnitude, so a Python-side double-negation (passing the signed −1.70) fails
the test exactly as it would fail in the DB.

TEST DOCTRINE (CLAUDE.md): drive the PRODUCTION route end-to-end —
`PaperExitEvaluator._close_position` — with the failure injected at the
DEEPEST callee (the quote origin, `MarketDataTruthLayer.snapshot_many`,
exactly where the signed achievable close is born) and assert the truth at
the TOP (the magnitude / side / realized_pl committed via the RPC, and the
server-derived cash + ledger). No source-string assertions — the 07-15 report
caught `test_csx_close_sign_convention.py` staying green for 34 days while the
live route walked past the function it string-pinned.
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


# ─────────────────────────────────────────────────────────────────────────────
# Capturing Supabase stub — the call graph _close_position's internal-fill path
# uses, plus a FAITHFUL fake of the atomic commit RPC (derives cash direction
# from the LOCKED position sign, rejects a non-positive magnitude, records the
# committed order-fill / cash / ledger / position-close so the same economic
# truths are assertable at the top).
# ─────────────────────────────────────────────────────────────────────────────

class _FakeRpcChain:
    def __init__(self, parent, name, params):
        self.parent, self.name, self.params = parent, name, params

    def execute(self):
        return self.parent._run_rpc(self.name, self.params)


class _CapturingSupabase:
    def __init__(self, position, portfolio_cash=10000.0,
                 routing_mode="shadow_only", entry_alpaca_order_id=None):
        self.position = position
        self.portfolio_cash = portfolio_cash
        self.routing_mode = routing_mode
        self.entry_alpaca_order_id = entry_alpaca_order_id
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
        qty = float(self.position["quantity"])
        abs_qty = abs(qty)
        sign = 1 if qty > 0 else -1
        mag = params["p_fill_price_magnitude"]
        mult = params["p_multiplier"]
        # Mirror the RPC's H9 guard: a signed/garbage magnitude MUST reject —
        # this is what makes a Python-side double-negation fail the test.
        if mag is None or not math.isfinite(float(mag)) or float(mag) <= 0:
            raise RuntimeError(
                f"commit_internal_close: nonpositive_fill_magnitude ({mag})"
            )
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


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures — the real 2026-07-14 16:30:22Z QQQ c1c9ad04 shape (values from
# the 07-15 audit's A2 evidence block: credit entry 1.3266, qty 6, signed
# achievable close −1.70, alert/corroborated truth −224.04, booked fiction
# +1815.96) plus the NFLX #1017 debit twin and two historical credit rows.
# ─────────────────────────────────────────────────────────────────────────────

def _condor_position(qty=-6.0, entry=1.3266, mark=-1.65, symbol="QQQ"):
    return {
        "id": "pos-qqq-1",
        "user_id": "user-1",
        "symbol": symbol,
        "quantity": qty,
        "avg_entry_price": entry,
        "current_mark": mark,
        "portfolio_id": "port-1",
        "status": "open",
        "strategy_key": "IRON_CONDOR",
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


# Executable close = Σ(long bids) − Σ(short asks)
#                  = (0.10 + 0.20) − (1.20 + 0.80) = −1.70 per spread.
_QQQ_QUOTES = {
    "O:QQQ260821C00610000": {"bid": 1.10, "ask": 1.20, "last": 1.15},
    "O:QQQ260821C00620000": {"bid": 0.10, "ask": 0.15, "last": 0.12},
    "O:QQQ260821P00560000": {"bid": 0.70, "ask": 0.80, "last": 0.75},
    "O:QQQ260821P00550000": {"bid": 0.20, "ask": 0.25, "last": 0.22},
}


def _vertical_position(qty, entry, mark, symbol, leg_a, leg_b):
    return {
        "id": f"pos-{symbol.lower()}-1",
        "user_id": "user-1",
        "symbol": symbol,
        "quantity": qty,
        "avg_entry_price": entry,
        "current_mark": mark,
        "portfolio_id": "port-1",
        "status": "open",
        "strategy_key": "VERTICAL",
        "legs": [leg_a, leg_b],
    }


def _run_close(supabase, quotes, reason="stop_loss", position_id="pos-qqq-1"):
    """Drive the PRODUCTION close route. Failure injection point = the quote
    origin: executable_close_estimate constructs MarketDataTruthLayer itself
    (the call site passes no snapshot_fn), so the deepest injectable seam is
    snapshot_many. Returns the route result; the economic effects land on the
    capturing supabase (position_updates / portfolio_updates / order_updates /
    ledger_fills), committed through the fake atomic RPC."""
    evaluator = pe.PaperExitEvaluator(supabase)

    class _FakeTruthLayer:
        def snapshot_many(self, occs):
            return {occ: {"quote": quotes.get(occ, {})} for occ in occs}

    with patch(
        "packages.quantum.paper_endpoints._stage_order_internal",
        return_value="order-close-1",
    ), patch(
        "packages.quantum.paper_endpoints.get_analytics_service",
        return_value=MagicMock(),
    ), patch(
        "packages.quantum.services.market_data_truth_layer.MarketDataTruthLayer",
        _FakeTruthLayer,
    ):
        return evaluator._close_position(
            user_id="user-1",
            position_id=position_id,
            reason=reason,
        )


class TestQqqCreditRegression(unittest.TestCase):
    """The exact 07-14 numbers, through the real route: entry 1.3266 credit,
    qty 6, signed achievable close −1.70 → realized −224.04. NEVER +1815.96."""

    def _close_qqq(self):
        supabase = _CapturingSupabase(_condor_position())
        result = _run_close(supabase, _QQQ_QUOTES)
        return supabase, result

    def test_realized_pl_is_truthful_never_the_fiction(self):
        supabase, result = self._close_qqq()
        self.assertEqual(result.get("processed"), 1)
        self.assertEqual(len(supabase.position_updates), 1)
        upd = supabase.position_updates[0]
        self.assertEqual(upd["status"], "closed")
        self.assertEqual(upd["close_reason"], "stop_loss_hit")
        realized = Decimal(str(upd["realized_pl"]))
        # Truth: +795.96 credit received − 1,020.00 buy-back = −224.04.
        self.assertEqual(realized, Decimal("-224.04"))
        # The double-negation fiction (error = 2 × 1.70 × 600 = 2,040.00):
        self.assertNotEqual(realized, Decimal("1815.96"))
        # And the committed magnitude is UNSIGNED (the signed −1.70 would have
        # been rejected by the RPC's H9 guard, failing this test).
        self.assertAlmostEqual(
            supabase.rpc_calls[0][1]["p_fill_price_magnitude"], 1.70, places=6
        )

    def test_cash_delta_debits_the_buy_to_close(self):
        supabase, _ = self._close_qqq()
        self.assertEqual(len(supabase.portfolio_updates), 1)
        new_cash = supabase.portfolio_updates[0]["cash_balance"]
        # Buy-to-close PAYS 1.70 × 6 × 100 = 1,020: 10,000 → 8,980.
        # Pre-fix it CREDITED +1,020 (→ 11,020): a $2,040 cash error.
        self.assertAlmostEqual(new_cash, 8980.0, places=6)

    def test_ledger_agrees_with_cash_and_carries_unsigned_price(self):
        supabase, _ = self._close_qqq()
        self.assertEqual(len(supabase.ledger_fills), 1)
        fill = supabase.ledger_fills[0]
        self.assertAlmostEqual(fill["amount"], -1020.0, places=6)
        self.assertAlmostEqual(fill["balance_after"], 8980.0, places=6)
        self.assertAlmostEqual(fill["metadata"]["price"], 1.70, places=6)
        self.assertEqual(fill["metadata"]["side"], "buy")
        self.assertEqual(fill["metadata"]["fill_quality"], "executable")

    def test_order_row_fill_price_is_broker_convention_unsigned(self):
        supabase, _ = self._close_qqq()
        fill_upds = [u for u in supabase.order_updates if "avg_fill_price" in u]
        self.assertEqual(len(fill_upds), 1)
        self.assertAlmostEqual(fill_upds[0]["avg_fill_price"], 1.70, places=6)
        self.assertEqual(fill_upds[0]["status"], "filled")
        self.assertEqual(
            fill_upds[0]["order_json"]["fill_quality"], "executable"
        )

    def test_four_way_agreement_cash_ledger_legs_realized(self):
        """entry_cash + close_cash(ledger amount) == realized_pl — the same
        identity compute_realized_pl derives from the synthetic leg."""
        supabase, _ = self._close_qqq()
        realized = Decimal(str(supabase.position_updates[0]["realized_pl"]))
        entry_cash = Decimal("1.3266") * 6 * 100  # +795.96 credit received
        close_cash = Decimal(str(supabase.ledger_fills[0]["amount"]))
        self.assertEqual(
            (entry_cash + close_cash).quantize(Decimal("0.01")), realized
        )

    def test_exactly_one_atomic_commit_rpc(self):
        """The whole economic effect is ONE atomic RPC call — never the old
        multi-write sequence."""
        supabase, _ = self._close_qqq()
        self.assertEqual(len(supabase.rpc_calls), 1)
        self.assertEqual(supabase.rpc_calls[0][0], "rpc_commit_internal_close_v1")


class TestCreditMidFallbackSameContract(unittest.TestCase):
    """Dark quotes → mid fallback: the SIGNED mid (current_mark −1.65) must
    hit the same unsigned-magnitude contract. realized = 795.96 − 990.00 =
    −194.04, flagged mid_fallback_quote_missing."""

    def test_signed_mid_fallback_books_truthfully(self):
        supabase = _CapturingSupabase(_condor_position(mark=-1.65))
        _run_close(supabase, quotes={})  # all legs dark
        upd = supabase.position_updates[0]
        self.assertEqual(Decimal(str(upd["realized_pl"])), Decimal("-194.04"))
        fill = supabase.ledger_fills[0]
        self.assertEqual(
            fill["metadata"]["fill_quality"], "mid_fallback_quote_missing"
        )
        self.assertAlmostEqual(fill["amount"], -990.0, places=6)
        self.assertAlmostEqual(
            supabase.portfolio_updates[0]["cash_balance"], 9010.0, places=6
        )


class TestDebitTwinUnchanged(unittest.TestCase):
    """The #1017 NFLX debit fixture through the SAME route: positive
    achievable close 4.131 (P86 sell at bid 6.14, P79 buy at ask 2.009) →
    realized +133.35, cash CREDITED. The fix must not move the debit path."""

    def test_debit_close_still_books_executable_positive(self):
        pos = _vertical_position(
            qty=3.0, entry=3.6865, mark=4.7355, symbol="NFLX",
            leg_a={"symbol": "O:NFLX260710P00086000", "action": "buy",
                   "type": "put", "strike": 86.0, "expiry": "2026-07-10",
                   "quantity": 3},
            leg_b={"symbol": "O:NFLX260710P00079000", "action": "sell",
                   "type": "put", "strike": 79.0, "expiry": "2026-07-10",
                   "quantity": 3},
        )
        quotes = {
            "O:NFLX260710P00086000": {"bid": 6.14, "ask": 7.23, "last": 6.64},
            "O:NFLX260710P00079000": {"bid": 1.89, "ask": 2.009, "last": 2.10},
        }
        supabase = _CapturingSupabase(pos)
        _run_close(
            supabase, quotes, reason="target_profit",
            position_id="pos-nflx-1",
        )
        upd = supabase.position_updates[0]
        self.assertEqual(Decimal(str(upd["realized_pl"])), Decimal("133.35"))
        self.assertEqual(upd["close_reason"], "target_profit_hit")
        fill = supabase.ledger_fills[0]
        self.assertEqual(fill["metadata"]["side"], "sell")
        self.assertAlmostEqual(fill["amount"], 1239.30, places=2)
        self.assertAlmostEqual(
            supabase.portfolio_updates[0]["cash_balance"], 11239.30, places=2
        )


class TestHistoricalCreditShapes(unittest.TestCase):
    """The two historical rows the 07-15 audit reproduced to the cent —
    AMD 75204e83 (04-10) and the META 2f316f4a condor-batch signature —
    as credit verticals through the real route (property check: for every
    credit shape, realized == entry_credit − |close| × qty × 100)."""

    def _credit_vertical(self, symbol, qty_abs, entry, short_ask, long_bid):
        pos = _vertical_position(
            qty=-float(qty_abs), entry=entry, mark=-(short_ask - long_bid),
            symbol=symbol,
            leg_a={"symbol": f"O:{symbol}270115C00100000", "action": "sell",
                   "type": "call", "strike": 100.0, "expiry": "2027-01-15",
                   "quantity": qty_abs},
            leg_b={"symbol": f"O:{symbol}270115C00110000", "action": "buy",
                   "type": "call", "strike": 110.0, "expiry": "2027-01-15",
                   "quantity": qty_abs},
        )
        quotes = {
            f"O:{symbol}270115C00100000":
                {"bid": short_ask - 0.05, "ask": short_ask, "last": None},
            f"O:{symbol}270115C00110000":
                {"bid": long_bid, "ask": long_bid + 0.05, "last": None},
        }
        return pos, quotes

    def _assert_shape(self, symbol, qty_abs, entry, short_ask, long_bid,
                      expected_realized):
        pos, quotes = self._credit_vertical(
            symbol, qty_abs, entry, short_ask, long_bid
        )
        supabase = _CapturingSupabase(pos)
        _run_close(
            supabase, quotes, position_id=pos["id"],
        )
        realized = Decimal(str(supabase.position_updates[0]["realized_pl"]))
        self.assertEqual(realized, Decimal(expected_realized))
        # Structural direction: a credit close always pays out.
        self.assertLess(supabase.ledger_fills[0]["amount"], 0)
        # The double-negation fiction for this shape, ruled out by identity:
        close_debit = Decimal(str(short_ask - long_bid)) * qty_abs * 100
        fiction = (Decimal(str(entry)) * qty_abs * 100 + close_debit)
        self.assertNotEqual(realized.quantize(Decimal("0.01")),
                            fiction.quantize(Decimal("0.01")))

    def test_amd_75204e83_shape(self):
        # entry 1.20 credit ×4, close debit 1.805 → −242.00 (booked +1,202.00
        # pre-fix; error 2 × 1.805 × 400 = 1,444.00 — audit-verified).
        self._assert_shape("AMD", 4, 1.20, short_ask=2.005, long_bid=0.20,
                           expected_realized="-242.00")

    def test_meta_2f316f4a_shape(self):
        # entry 10.05 credit ×9, close debit 0.41833 → +8,668.50 (booked
        # 9,421.50 pre-fix; Δ = 2 × 0.41833 × 900 = 753.00 — audit-verified).
        self._assert_shape("META", 9, 10.05, short_ask=0.51833, long_bid=0.10,
                           expected_realized="8668.50")


class TestBrokerAckSafetyUntouched(unittest.TestCase):
    """P0-A/E6: a live-routed close that reaches the internal-fill guard is
    HELD OPEN — the sign fix sits strictly INSIDE the internal-fill block and
    must not perturb the broker-ack invariant. The atomic RPC is NEVER
    reached on the live path."""

    def test_live_routed_close_held_open_no_fill_no_cash_no_realized(self):
        supabase = _CapturingSupabase(
            _condor_position(), routing_mode="live_eligible"
        )
        result = _run_close(supabase, _QQQ_QUOTES)
        self.assertEqual(result.get("routed_to"), "unknown_reconciling")
        self.assertEqual(result.get("processed"), 0)
        self.assertEqual(supabase.position_updates, [])   # no close write
        self.assertEqual(supabase.portfolio_updates, [])  # no cash effect
        self.assertEqual(supabase.ledger_fills, [])       # no ledger fill
        self.assertEqual(supabase.rpc_calls, [])          # never the internal RPC
        # the order is parked for the operator, not filled
        statuses = [u.get("status") for u in supabase.order_updates]
        self.assertIn("needs_manual_review", statuses)
        self.assertNotIn("filled", statuses)


class TestSeamUnit(unittest.TestCase):
    """The canonical owner: _close_limit_and_direction returns the MAGNITUDE
    and the STRUCTURAL direction for the signed credit-close mark."""

    def test_signed_credit_close_mark_yields_magnitude_and_debit_direction(self):
        limit, is_credit_close = pe._close_limit_and_direction(-1.70, -6.0, 4)
        self.assertAlmostEqual(limit, 1.70, places=6)
        self.assertFalse(is_credit_close)  # buy-to-close pays a debit


if __name__ == "__main__":
    unittest.main()
