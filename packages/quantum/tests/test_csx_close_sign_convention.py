"""CSX #101 incident coverage — the parts no other suite owns, driven
through the REAL seams (rewritten 2026-07-17, Lane 4A test-honesty).

HISTORY. The original file mixed real translator tests with SOURCE-STRING
assertions (``self.src.find("def _close_limit_and_direction")`` + ``assertIn``)
— the #1126 costume in test form. The 07-15 nightly caught it: the string
pins stayed green for 34 days while the active internal-fill route walked
past the function they referenced (F-CREDIT-SIGN). Every costume class was
removed; every behavior it CLAIMED to pin is owned by a route-driving suite:

  - is_credit_close marker computation + ticket plumbing + the internal-fill
    sign contract → test_credit_close_sign_contract.py (drives
    ``PaperExitEvaluator._close_position`` end-to-end) and
    test_close_limit_sign.py (``_close_limit_and_direction`` unit + handler
    guards).
  - credit-close sign flip at the broker translator (±1.86) →
    test_close_limit_sign.py (flip + refuse-unmarked-negative) and
    test_submit_option_order_credit_seam.py (the exact CSX 2026-05-08
    payload through build_alpaca_order_request AND submit_option_order).
  - watchdog-cancel cancelled_at/cancelled_reason →
    test_watchdog_cancel_only.py (drives poll_pending_orders).

WHAT LIVES HERE (distinct, behavior-driven):

  Part A — build_alpaca_order_request edge cases nothing else pins:
    entry orders ignore a stray is_credit_close marker; close legs carry
    position_intent; sub-penny prices land at the ±0.01 minimum with sign
    per direction; unpriceable (zero) closes REJECT loudly (H9).

  Part B — #101 Components 3+4, rewritten from source-string pins to
    DRIVING ``poll_pending_orders`` with the failure injected at the broker
    payload (its origin) and truth asserted on the writes:
    a broker rejection populates cancelled_reason from leg status_text and
    cancelled_at from the BROKER timestamp, and inserts one critical
    ``order_rejected_by_broker`` risk_alert (throttled 1/hour; alert-path
    failure never breaks the poll; a plain user cancel is NOT a rejection).
    Pre-fix, 22 CSX close rejections over 36+ hours produced ZERO alerts
    and NULL cancelled_at/cancelled_reason on every row.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock

# Stub alpaca-py surfaces so the broker module imports cleanly when the
# lib isn't installed in the test venv (setdefault: no-op when it is).
sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
sys.modules.setdefault(
    "alpaca.trading.requests", types.ModuleType("alpaca.trading.requests")
)

from packages.quantum.brokers.alpaca_order_handler import (  # noqa: E402
    build_alpaca_order_request,
    poll_pending_orders,
)


# ─────────────────────────────────────────────────────────────────────
# Part A — translator edge cases (real function, real payload shapes)
# ─────────────────────────────────────────────────────────────────────


def _csx_close_order(requested_price=1.86, is_credit_close=True):
    """Shape mirrors the actual CSX close order_json captured 2026-05-08."""
    return {
        "id": "test-csx-close-1",
        "position_id": "1f77f6af-b536-46a3-9975-88dfef41f855",
        "side": "sell",
        "requested_qty": 1,
        "requested_price": requested_price,
        "order_json": {
            "symbol": "CSX",
            "is_credit_close": is_credit_close,
            "legs": [
                {"symbol": "O:CSX260605C00043000", "action": "sell",
                 "type": "call", "strike": 43, "quantity": 1},
                {"symbol": "O:CSX260605C00047000", "action": "buy",
                 "type": "call", "strike": 47, "quantity": 1},
            ],
        },
    }


class TestTranslatorCloseEdges(unittest.TestCase):
    """Distinct build_alpaca_order_request behaviors: entry exemption,
    close intents, sub-penny minimums, zero-price rejection."""

    def test_entry_order_ignores_stray_credit_close_marker(self):
        # No position_id → not a close: is_credit_close in order_json must
        # be inert (stays +1.86) and no position_intent is stamped. Guards
        # the add-to-position seam (§8): close semantics key on position_id.
        order = _csx_close_order()
        order.pop("position_id")
        req = build_alpaca_order_request(order)
        self.assertEqual(req["limit_price"], 1.86)
        for leg in req["legs"]:
            self.assertNotIn("position_intent", leg)

    def test_close_legs_carry_position_intents(self):
        # Alpaca infers buy_to_OPEN without explicit close intents — the
        # translator must stamp them per leg side.
        req = build_alpaca_order_request(_csx_close_order())
        intents = {
            leg["symbol"]: leg.get("position_intent") for leg in req["legs"]
        }
        self.assertEqual(intents["CSX260605C00043000"], "sell_to_close")
        self.assertEqual(intents["CSX260605C00047000"], "buy_to_close")

    def test_sub_penny_credit_close_lands_at_negative_penny(self):
        # Near-worthless credit close: 0.005 → the broker request must be
        # exactly -0.01 (a penny credit, sign preserved). Pre-2026-05-10 the
        # clamp forced any negative to +0.01, masking the credit convention.
        req = build_alpaca_order_request(
            _csx_close_order(requested_price=0.005)
        )
        self.assertEqual(req["limit_price"], -0.01)

    def test_sub_penny_debit_close_lands_at_positive_penny(self):
        # The original 2026-04-10 case: near-worthless debit-direction close
        # → +0.01 (paying a penny to close).
        req = build_alpaca_order_request(
            _csx_close_order(requested_price=0.005, is_credit_close=False)
        )
        self.assertEqual(req["limit_price"], 0.01)

    def test_zero_price_close_raises_never_fabricates(self):
        # H9: an unpriceable close REJECTS loudly — no fabricated penny.
        with self.assertRaises(ValueError):
            build_alpaca_order_request(
                _csx_close_order(requested_price=0, is_credit_close=False)
            )

    def test_rounds_to_zero_close_raises_never_fabricates(self):
        # 0.004 rounds to 0.00 at the translator entry — same rejection.
        with self.assertRaises(ValueError):
            build_alpaca_order_request(
                _csx_close_order(requested_price=0.004, is_credit_close=False)
            )


# ─────────────────────────────────────────────────────────────────────
# Part B — Components 3+4 driven through poll_pending_orders
# ─────────────────────────────────────────────────────────────────────


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, sb, table):
        self._sb = sb
        self._table = table
        self._op = "select"
        self._payload = None
        self._eq = {}

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
        self._eq[col] = val
        return self

    def gte(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    @property
    def not_(self):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return self._sb._execute(self)


class _CapturingSupabase:
    """Just enough of the client for poll_pending_orders' call graph."""

    def __init__(self, order_row, recent_alert_rows=(),
                 alert_select_raises=False):
        self.order_row = order_row
        self.recent_alert_rows = list(recent_alert_rows)
        self.alert_select_raises = alert_select_raises
        self.order_updates = []  # (eq_filters, payload)
        self.alert_inserts = []

    def table(self, name):
        return _Query(self, name)

    def _execute(self, q):
        if q._table == "paper_portfolios":
            return _Result([{"id": "port-1"}])
        if q._table == "paper_orders":
            if q._op == "select":
                return _Result([dict(self.order_row)])
            if q._op == "update":
                self.order_updates.append((dict(q._eq), q._payload))
                return _Result(None)
        if q._table == "risk_alerts":
            if q._op == "select":
                if self.alert_select_raises:
                    raise RuntimeError("risk_alerts read unavailable")
                return _Result(list(self.recent_alert_rows))
            if q._op == "insert":
                self.alert_inserts.append(q._payload)
                return _Result([{"id": "alert-row-1"}])
        return _Result([])


_FAILED_AT = "2026-05-08T19:45:09.123456Z"
_CANCELED_AT = "2026-05-08T20:00:00.000000Z"
_REJECT_TEXT = "cost basis must not exceed order cost basis"


def _db_order_row():
    return {
        "id": "order-1",
        "alpaca_order_id": "alp-1",
        "status": "submitted",
        "submitted_at": None,  # watchdog not under test here
        "broker_status": "submitted",
        "position_id": "pos-1",
        "side": "sell",
        "order_json": {
            "symbol": "CSX",
            "time_in_force": "day",
            "legs": _csx_close_order()["order_json"]["legs"],
        },
    }


def _rejected_alpaca_order():
    """Broker truth for the CSX class: mleg reject with leg-level
    status_text and a broker-side failed_at timestamp."""
    return {
        "id": "alp-1",
        "status": "rejected",
        "failed_at": _FAILED_AT,
        "canceled_at": None,
        "filled_qty": "0",
        "limit_price": "1.86",
        "legs": [
            {"symbol": "CSX260605C00043000", "side": "sell",
             "position_intent": "sell_to_close",
             "status_text": _REJECT_TEXT},
            {"symbol": "CSX260605C00047000", "side": "buy",
             "position_intent": "buy_to_close"},
        ],
    }


def _poll(supabase, alpaca_order):
    alpaca = MagicMock()
    alpaca.get_order.return_value = alpaca_order
    return poll_pending_orders(alpaca, supabase, "user-1")


class TestBrokerRejectionCaptureAndAlert(unittest.TestCase):
    """#101 Components 3+4 as behavior: drive the poll with a rejected
    broker payload, assert the DB writes and the alert row."""

    def test_rejection_captures_reason_timestamp_and_alerts(self):
        sb = _CapturingSupabase(_db_order_row())
        result = _poll(sb, _rejected_alpaca_order())

        self.assertEqual(result["synced"], 1)
        self.assertEqual(result["cancels"], 1)
        self.assertEqual(result["errors"], [])

        # Component 4: forensic fields populated from BROKER truth.
        self.assertEqual(len(sb.order_updates), 1)
        eq_filters, upd = sb.order_updates[0]
        self.assertEqual(eq_filters.get("id"), "order-1")
        self.assertEqual(upd["status"], "cancelled")
        self.assertEqual(upd["broker_status"], "rejected")
        self.assertIn(_REJECT_TEXT, upd["cancelled_reason"])
        # cancelled_at is the broker's failed_at, never a local now().
        self.assertEqual(upd["cancelled_at"], _FAILED_AT)

        # Component 3: exactly one critical alert, diagnostics attached.
        self.assertEqual(len(sb.alert_inserts), 1)
        row = sb.alert_inserts[0]
        self.assertEqual(row["alert_type"], "order_rejected_by_broker")
        self.assertEqual(row["severity"], "critical")
        self.assertIn("CSX", row["message"])
        self.assertIn(_REJECT_TEXT, row["message"])
        self.assertEqual(row["position_id"], "pos-1")
        self.assertEqual(row["user_id"], "user-1")
        meta = row["metadata"]
        self.assertEqual(meta["alpaca_order_id"], "alp-1")
        self.assertEqual(meta["internal_order_id"], "order-1")
        self.assertEqual(meta["rejection_reason"], _REJECT_TEXT)
        self.assertEqual(meta["limit_price"], "1.86")
        self.assertIn("consequence", meta)
        self.assertEqual(
            [leg["position_intent"] for leg in meta["leg_structure"]],
            ["sell_to_close", "buy_to_close"],
        )

    def test_alert_throttled_when_recent_alert_exists(self):
        # A retry storm must produce ONE alert per hour, not one per
        # attempt (the CSX cascade was 22 rejections in 36 hours).
        sb = _CapturingSupabase(
            _db_order_row(), recent_alert_rows=[{"id": "existing-alert"}]
        )
        result = _poll(sb, _rejected_alpaca_order())
        self.assertEqual(result["synced"], 1)
        self.assertEqual(sb.alert_inserts, [])
        # The forensic capture still happens regardless of the throttle.
        _, upd = sb.order_updates[0]
        self.assertEqual(upd["cancelled_at"], _FAILED_AT)

    def test_alert_path_failure_never_breaks_the_poll(self):
        # The throttle query exploding must not derail the sync: the order
        # row is still reconciled and the poll reports no error.
        sb = _CapturingSupabase(_db_order_row(), alert_select_raises=True)
        result = _poll(sb, _rejected_alpaca_order())
        self.assertEqual(result["synced"], 1)
        self.assertEqual(result["cancels"], 1)
        self.assertEqual(result["errors"], [])
        self.assertEqual(sb.alert_inserts, [])
        _, upd = sb.order_updates[0]
        self.assertEqual(upd["status"], "cancelled")

    def test_plain_cancel_is_not_a_rejection(self):
        # A user/watchdog cancel (no failed_at) still captures forensic
        # fields — cancelled_at from the broker's canceled_at, reason
        # falls back to the status code — but raises NO critical alert.
        cancelled = _rejected_alpaca_order()
        cancelled["status"] = "canceled"
        cancelled["failed_at"] = None
        cancelled["canceled_at"] = _CANCELED_AT
        for leg in cancelled["legs"]:
            leg.pop("status_text", None)
        sb = _CapturingSupabase(_db_order_row())
        result = _poll(sb, cancelled)
        self.assertEqual(result["cancels"], 1)
        self.assertEqual(sb.alert_inserts, [])
        _, upd = sb.order_updates[0]
        self.assertEqual(upd["status"], "cancelled")
        self.assertEqual(upd["cancelled_at"], _CANCELED_AT)
        self.assertEqual(upd["cancelled_reason"], "alpaca_status=canceled")


if __name__ == "__main__":
    unittest.main()
