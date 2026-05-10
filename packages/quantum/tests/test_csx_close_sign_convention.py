"""Tests for #101 — Issue B: CSX close-order sign convention +
diagnostic instrumentation.

Background: CSX position opened 2026-05-05 at $2.16 debit produced 22
close orders rejected by Alpaca over 36+ hours (2026-05-07 → 2026-05-09).
Root cause: paper_exit_evaluator sent positive limit_price for SELL-to-
close on a long debit-opened spread, but Alpaca's mleg parent
limit_price is signed — positive = net debit (you pay), negative = net
credit (you receive). For a SELL-to-close debit spread the close
produces credit, so positive limit_price is rejected as economically
incoherent within ~4-9ms at the gateway.

Plus 3 diagnostic instrumentation gaps that obscured the failure for
~36 hours:
- 22 broker rejections produced ZERO order_rejected risk_alerts
- cancelled_at + cancelled_reason were NULL on every cancelled row
- broker_response did not capture Alpaca's rejection text

This file exercises:
- Component 1: is_credit_close marker upstream → sign-flip downstream
- Component 2: sign-preserving worthless-spread clamp
- Component 3: order_rejected_by_broker alert with throttle
- Component 4: rejection-reason capture in cancelled_reason
"""

import sys
import types
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock

# Stub alpaca-py + supabase surfaces so the broker module imports
# cleanly when those libs aren't installed in the test venv.
_alpaca_pkg = types.ModuleType("alpaca")
_alpaca_trading = types.ModuleType("alpaca.trading")
_alpaca_trading_requests = types.ModuleType("alpaca.trading.requests")
sys.modules.setdefault("alpaca", _alpaca_pkg)
sys.modules.setdefault("alpaca.trading", _alpaca_trading)
sys.modules.setdefault("alpaca.trading.requests", _alpaca_trading_requests)


REPO_ROOT = Path(__file__).parent.parent
HANDLER_PATH = REPO_ROOT / "brokers" / "alpaca_order_handler.py"
EVALUATOR_PATH = REPO_ROOT / "services" / "paper_exit_evaluator.py"
MODELS_PATH = REPO_ROOT / "models.py"


# ─────────────────────────────────────────────────────────────────────
# Component 1 — sign-flip via is_credit_close marker
# ─────────────────────────────────────────────────────────────────────


class TestIsCreditCloseMarkerOnTradeTicket(unittest.TestCase):
    """The TradeTicket model carries the credit-close marker so it
    survives the model_dump → order_json round-trip."""

    def test_field_exists_on_model(self):
        from packages.quantum.models import TradeTicket
        ticket = TradeTicket(symbol="CSX", legs=[])
        self.assertTrue(hasattr(ticket, "is_credit_close"))
        self.assertIsNone(ticket.is_credit_close)

    def test_field_round_trips_through_model_dump(self):
        from packages.quantum.models import TradeTicket
        ticket = TradeTicket(
            symbol="CSX", legs=[], limit_price=1.86, is_credit_close=True,
        )
        dumped = ticket.model_dump(mode="json")
        self.assertIn("is_credit_close", dumped)
        self.assertIs(dumped["is_credit_close"], True)


class TestPaperExitEvaluatorSetsMarker(unittest.TestCase):
    """paper_exit_evaluator must compute is_credit_close from qty
    sign + leg count and pass it to TradeTicket."""

    @classmethod
    def setUpClass(cls):
        cls.src = EVALUATOR_PATH.read_text(encoding="utf-8")

    def test_marker_computed_from_qty_and_leg_count(self):
        # Source-level: rule must reference both qty>0 and len(close_legs)>=2
        idx = self.src.find("is_credit_close")
        self.assertGreater(
            idx, 0, "is_credit_close marker computation missing from "
            "paper_exit_evaluator.py — Component 1 regressed",
        )
        block = self.src[idx:idx + 400]
        self.assertIn("qty > 0", block)
        self.assertIn("len(close_legs)", block)

    def test_marker_passed_to_ticket(self):
        # The TradeTicket(...) construction call must include
        # is_credit_close=is_credit_close as a kwarg.
        idx = self.src.find("ticket = TradeTicket(")
        self.assertGreater(idx, 0)
        block = self.src[idx:idx + 600]
        self.assertIn("is_credit_close=is_credit_close", block)


class TestBuildAlpacaOrderRequestSignFlip(unittest.TestCase):
    """build_alpaca_order_request must negate limit_price when
    order_json.is_credit_close=True. CSX-class regression guard."""

    def setUp(self):
        from packages.quantum.brokers.alpaca_order_handler import (
            build_alpaca_order_request,
        )
        self.build = build_alpaca_order_request

    def _csx_close_order(self, requested_price=1.86, is_credit_close=True):
        """Shape mirrors the actual CSX order_json captured 2026-05-08."""
        return {
            "id": "test-csx-close-1",
            "position_id": "1f77f6af-b536-46a3-9975-88dfef41f855",
            "side": "sell",
            "requested_qty": 1,
            "requested_price": requested_price,
            "order_json": {
                "symbol": "CSX",
                "limit_price": requested_price,
                "is_credit_close": is_credit_close,
                "legs": [
                    {
                        "symbol": "O:CSX260605C00043000",
                        "action": "sell",
                        "type": "call",
                        "strike": 43,
                        "quantity": 1,
                    },
                    {
                        "symbol": "O:CSX260605C00047000",
                        "action": "buy",
                        "type": "call",
                        "strike": 47,
                        "quantity": 1,
                    },
                ],
            },
        }

    def test_credit_close_negates_limit_price(self):
        req = self.build(self._csx_close_order(requested_price=1.86))
        # Should be -1.86, not +1.86 — Alpaca mleg credit convention
        self.assertEqual(req["limit_price"], -1.86)

    def test_non_credit_close_keeps_positive(self):
        # Same shape but is_credit_close=False (e.g., closing a credit
        # spread by buying it back — that's a debit, positive).
        req = self.build(self._csx_close_order(is_credit_close=False))
        self.assertEqual(req["limit_price"], 1.86)

    def test_open_order_unaffected_even_with_no_position_id(self):
        # Entry order: no position_id, no marker. Must stay positive
        # regardless of order_json contents.
        order = self._csx_close_order()
        order.pop("position_id")
        # Mark would be ignored because is_close_order=False
        req = self.build(order)
        self.assertEqual(req["limit_price"], 1.86)

    def test_legs_carry_position_intent_for_close(self):
        # Sanity check that we didn't break the existing intent logic
        req = self.build(self._csx_close_order())
        intents = sorted(leg.get("position_intent") for leg in req["legs"])
        self.assertEqual(intents, ["buy_to_close", "sell_to_close"])


# ─────────────────────────────────────────────────────────────────────
# Component 2 — sign-preserving worthless-spread clamp
# ─────────────────────────────────────────────────────────────────────


class TestSignPreservingClamp(unittest.TestCase):
    """The 2026-04-10 clamp at alpaca_order_handler.py:86-93 used to
    flip negative→+0.01, which masked the credit-close convention.
    Sign-preserving variant clamps the magnitude only."""

    def setUp(self):
        from packages.quantum.brokers.alpaca_order_handler import (
            build_alpaca_order_request,
        )
        self.build = build_alpaca_order_request

    def _close(self, requested_price, is_credit_close=False):
        return {
            "id": "test-clamp",
            "position_id": "pos-clamp",
            "side": "sell",
            "requested_qty": 1,
            "requested_price": requested_price,
            "order_json": {
                "symbol": "X",
                "is_credit_close": is_credit_close,
                "legs": [
                    {"symbol": "X-LONG",  "action": "sell", "quantity": 1},
                    {"symbol": "X-SHORT", "action": "buy",  "quantity": 1},
                ],
            },
        }

    def test_legitimate_negative_credit_close_passes_through(self):
        # Pre-fix this would clamp to +0.01 and reject at Alpaca; the
        # sign-flip path delivers -1.86 which must NOT trip the clamp.
        req = self.build(self._close(1.86, is_credit_close=True))
        self.assertEqual(req["limit_price"], -1.86)

    def test_near_worthless_negative_clamps_to_negative_penny(self):
        # Worthless credit close: signed price would be ~-0.005 → must
        # clamp to -0.01 (preserving sign so Alpaca still sees credit).
        # We simulate by sending requested_price=0.005 with credit marker.
        # After sign-flip: -0.005, |x| < 0.01 → -0.01.
        req = self.build(self._close(0.005, is_credit_close=True))
        self.assertEqual(req["limit_price"], -0.01)

    def test_near_worthless_positive_clamps_to_positive_penny(self):
        # Original 2026-04-10 case: debit-direction close near zero →
        # +0.01 (paying a penny to close).
        req = self.build(self._close(0.005, is_credit_close=False))
        self.assertEqual(req["limit_price"], 0.01)

    def test_zero_limit_price_raises(self):
        # Magnitude check, not sign. requested_price=0 stays 0, raises.
        with self.assertRaises(ValueError):
            self.build(self._close(0, is_credit_close=False))


# ─────────────────────────────────────────────────────────────────────
# Component 3 — order_rejected_by_broker alert (source-level)
# ─────────────────────────────────────────────────────────────────────


class TestBrokerRejectionAlertWired(unittest.TestCase):
    """Source-level checks: alert is wired into poll_pending_orders,
    has critical severity, and is throttled to prevent retry-storm
    flooding."""

    @classmethod
    def setUpClass(cls):
        cls.src = HANDLER_PATH.read_text(encoding="utf-8")

    def test_alert_type_present(self):
        self.assertIn(
            "order_rejected_by_broker", self.src,
            "Component 3 alert_type missing — broker rejections will "
            "regress to silent failure (CSX 22-cascade class).",
        )

    def test_alert_is_critical_severity(self):
        idx = self.src.find('alert_type="order_rejected_by_broker"')
        self.assertGreater(idx, 0)
        block = self.src[max(0, idx - 200):idx + 800]
        self.assertTrue(
            'severity="critical"' in block,
            "order_rejected_by_broker must be severity='critical' — "
            "matches paper_order_marked_needs_manual_review precedent.",
        )

    def test_throttle_query_present(self):
        # Must check risk_alerts before inserting to prevent retry-storm
        idx = self.src.find('alert_type="order_rejected_by_broker"')
        block = self.src[max(0, idx - 1500):idx + 300]
        self.assertIn(
            'order_rejected_by_broker', block,
        )
        self.assertIn("risk_alerts", block)
        self.assertIn("hours=1", block)

    def test_alert_path_failure_does_not_break_poll(self):
        # The alert must be wrapped in try/except so a failure to write
        # an alert never derails the poll loop's primary work.
        idx = self.src.find('alert_type="order_rejected_by_broker"')
        block = self.src[max(0, idx - 1500):idx + 3500]
        self.assertIn("except Exception", block)

    def test_alert_metadata_includes_diagnostic_fields(self):
        # Future investigators need: alpaca_order_id, leg_structure,
        # rejection_reason, limit_price.
        idx = self.src.find('alert_type="order_rejected_by_broker"')
        block = self.src[max(0, idx - 200):idx + 2000]
        for field in (
            "alpaca_order_id", "leg_structure", "rejection_reason",
            "limit_price", "consequence",
        ):
            self.assertIn(
                field, block,
                f"order_rejected_by_broker alert metadata missing "
                f"field: {field}",
            )


# ─────────────────────────────────────────────────────────────────────
# Component 4 — rejection reason capture in cancelled_reason
# ─────────────────────────────────────────────────────────────────────


class TestRejectionReasonCaptureWired(unittest.TestCase):
    """Source-level: cancelled_reason + cancelled_at must populate on
    rejection paths (Alpaca-side AND watchdog)."""

    @classmethod
    def setUpClass(cls):
        cls.src = HANDLER_PATH.read_text(encoding="utf-8")

    def test_status_text_extracted_from_legs(self):
        # Alpaca surfaces rejection text on legs[i].status_text for mleg
        self.assertIn("status_text", self.src)

    def test_cancelled_reason_written_on_alpaca_rejection(self):
        # The rejection-capture block must write cancelled_reason
        idx = self.src.find("is_broker_rejection")
        self.assertGreater(idx, 0)
        block = self.src[idx:idx + 1500]
        self.assertIn('"cancelled_reason"', block)
        self.assertIn('"cancelled_at"', block)

    def test_cancelled_at_uses_broker_timestamp_when_present(self):
        # Should prefer broker_failed_at / broker_canceled_at over now()
        idx = self.src.find("is_broker_rejection")
        block = self.src[idx:idx + 1500]
        self.assertIn("broker_failed_at", block)
        self.assertIn("broker_canceled_at", block)

    def test_watchdog_path_also_writes_cancelled_fields(self):
        # The 90s idle-watchdog branch must also populate the
        # column-level transition fields, not just nest under
        # broker_response.watchdog.
        idx = self.src.find('"broker_status": "watchdog_cancelled"')
        self.assertGreater(idx, 0)
        block = self.src[idx:idx + 600]
        self.assertIn('"cancelled_at"', block)
        self.assertIn('"cancelled_reason"', block)
        self.assertIn("watchdog_idle_timeout", block)


# ─────────────────────────────────────────────────────────────────────
# Cross-component: CSX scenario reproduction
# ─────────────────────────────────────────────────────────────────────


class TestCSXIncidentReproduction(unittest.TestCase):
    """End-to-end: feeding the actual CSX close payload through the
    broker translator must produce the corrected request shape."""

    def test_csx_friday_close_attempt_reproduces_correctly(self):
        from packages.quantum.brokers.alpaca_order_handler import (
            build_alpaca_order_request,
        )

        # Reconstruct the order shape captured from paper_orders for
        # the 2026-05-08 19:45 UTC attempt that Alpaca rejected.
        order = {
            "id": "ac8d1cb6-2908-4c9c-b06e-751a693c7ac8",
            "position_id": "1f77f6af-b536-46a3-9975-88dfef41f855",
            "side": "sell",
            "requested_qty": 1,
            "requested_price": 1.86,
            "order_json": {
                "symbol": "CSX",
                "quantity": 1,
                "order_type": "limit",
                "limit_price": 1.86,
                "is_credit_close": True,  # set by post-fix evaluator
                "strategy_type": "custom",
                "source_engine": "paper_exit_evaluator",
                "legs": [
                    {
                        "type": "call",
                        "action": "sell",
                        "expiry": "2026-06-05",
                        "strike": 43,
                        "symbol": "O:CSX260605C00043000",
                        "quantity": 1,
                    },
                    {
                        "type": "call",
                        "action": "buy",
                        "expiry": "2026-06-05",
                        "strike": 47,
                        "symbol": "O:CSX260605C00047000",
                        "quantity": 1,
                    },
                ],
            },
        }

        req = build_alpaca_order_request(order)

        # The fix: limit_price now signed negative for the credit close.
        # Pre-fix this was +1.86 → Alpaca instant-rejected in 4-9ms.
        self.assertEqual(req["limit_price"], -1.86)
        self.assertEqual(req["order_type"], "limit")
        self.assertEqual(req["time_in_force"], "day")
        self.assertEqual(req["qty"], 1)

        # Both legs carry their close intents (unchanged by this PR).
        intents = {
            leg["symbol"]: leg["position_intent"]
            for leg in req["legs"]
        }
        self.assertEqual(
            intents.get("CSX260605C00043000"), "sell_to_close",
        )
        self.assertEqual(
            intents.get("CSX260605C00047000"), "buy_to_close",
        )


if __name__ == "__main__":
    unittest.main()
