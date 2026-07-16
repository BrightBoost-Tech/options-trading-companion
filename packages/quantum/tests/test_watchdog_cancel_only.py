"""Entry-order watchdog: behavior-preservation pins for the honesty cleanup.

The 2026-06-04 fill-mechanics diagnostic found two honesty defects in the
watchdog (alpaca_order_handler.poll_pending_orders):
  1. "cancel and resubmit" comments were vaporware — it is CANCEL-ONLY;
  2. IDLE_WATCHDOG_SECONDS=90 is a threshold checked on the order_sync
     cadence, so the EFFECTIVE cancel time is the first sync after 90s
     (~up to 6 min), not 90s.

The cleanup is comments/documentation only (Option A — the constant is
unchanged because order_sync also runs ad-hoc/back-to-back, so raising the
constant WOULD change marginal cancels). These tests pin that the behavior
is exactly what it was:
  - an idle working order past the threshold is still cancelled;
  - NOTHING is resubmitted after the cancel (no new order row, no broker
    submit — the only broker calls are get_order + cancel_order);
  - a fresh order under the threshold is NOT cancelled;
  - the threshold value itself is unchanged (90).
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from packages.quantum.brokers import alpaca_order_handler

USER_ID = "user-1"


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _working_order(idle_seconds: float) -> dict:
    submitted = datetime.now(timezone.utc) - timedelta(seconds=idle_seconds)
    return {
        "id": "order-1",
        "alpaca_order_id": "alp-1",
        "status": "working",
        "submitted_at": _iso(submitted),
        "broker_status": "new",
        "position_id": None,
        "side": "buy",
        "order_json": {"symbol": "NFLX", "legs": []},
    }


def _mock_supabase(order: dict):
    """Minimal poll_pending_orders supabase: one portfolio, one order.
    Captures every table().update(...) payload and every insert."""
    updates = []
    inserts = []

    def make_chain(name):
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[])
        for method in ("select", "eq", "neq", "in_", "gte", "lte", "lt", "limit"):
            getattr(chain, method).return_value = chain
        chain.not_ = MagicMock()
        chain.not_.is_.return_value = chain

        if name == "paper_portfolios":
            chain.execute.return_value = MagicMock(data=[{"id": "port-1"}])
        elif name == "paper_orders":
            chain.execute.return_value = MagicMock(data=[order])

            def capture_update(payload):
                updates.append((name, payload))
                up = MagicMock()
                up.eq.return_value.execute.return_value = MagicMock()
                return up

            chain.update.side_effect = capture_update

        def capture_insert(payload):
            inserts.append((name, payload))
            ins = MagicMock()
            ins.execute.return_value = MagicMock()
            return ins

        chain.insert.side_effect = capture_insert
        return chain

    sb = MagicMock()
    sb.table.side_effect = make_chain
    return sb, updates, inserts


class TestWatchdogCancelOnly(unittest.TestCase):
    def test_idle_order_past_threshold_still_cancelled(self):
        """Same orders cancelled at the same effective times: an order idle
        292s (yesterday's NFLX) at poll time is cancelled."""
        order = _working_order(idle_seconds=292)
        sb, updates, _ = _mock_supabase(order)
        alpaca = MagicMock()
        alpaca.get_order.side_effect = [
            {"status": "new", "filled_qty": 0},
            {"status": "canceled", "filled_qty": 0},
        ]

        alpaca_order_handler.poll_pending_orders(alpaca, sb, USER_ID)

        alpaca.cancel_order.assert_called_once_with("alp-1")
        self.assertEqual(alpaca.get_order.call_count, 2)
        watchdog_updates = [
            p for (_n, p) in updates if p.get("status") == "watchdog_cancelled"
        ]
        self.assertTrue(watchdog_updates, "expected a watchdog_cancelled update")
        self.assertIn(
            "watchdog_idle_timeout", watchdog_updates[0].get("cancelled_reason", "")
        )

    def test_cancel_only_no_resubmission(self):
        """After the watchdog cancel: NO new order row is inserted and the
        only broker interactions are get_order + cancel_order — there is no
        resubmission path (the old comments claiming one were vaporware)."""
        order = _working_order(idle_seconds=292)
        sb, _updates, inserts = _mock_supabase(order)
        alpaca = MagicMock()
        alpaca.get_order.side_effect = [
            {"status": "new", "filled_qty": 0},
            {"status": "canceled", "filled_qty": 0},
        ]

        alpaca_order_handler.poll_pending_orders(alpaca, sb, USER_ID)

        self.assertEqual(
            [n for (n, _p) in inserts if n == "paper_orders"], [],
            "watchdog must not insert a replacement order",
        )
        broker_methods = {c[0] for c in alpaca.method_calls}
        self.assertTrue(
            broker_methods.issubset({"get_order", "cancel_order"}),
            f"unexpected broker calls (resubmission?): {broker_methods}",
        )

    def test_cancel_race_filled_uses_fresh_broker_truth(self):
        """A cancel exception can mean the order filled in the race.  The
        refetched fill must use normal reconciliation, never the stale
        watchdog terminal."""
        from unittest.mock import patch

        order = _working_order(idle_seconds=292)
        order["position_id"] = "pos-1"
        sb, updates, inserts = _mock_supabase(order)
        alpaca = MagicMock()
        alpaca.get_order.side_effect = [
            {"status": "new", "filled_qty": 0},
            {
                "status": "filled",
                "filled_qty": "1",
                "filled_avg_price": "1.25",
                "filled_at": "2026-07-15T20:00:00Z",
            },
        ]
        alpaca.cancel_order.side_effect = RuntimeError("already filled")

        with patch.object(
            alpaca_order_handler, "_close_position_on_fill"
        ) as commit_fill:
            result = alpaca_order_handler.poll_pending_orders(
                alpaca, sb, USER_ID
            )

        self.assertFalse(
            [p for (_n, p) in updates if p.get("status") == "watchdog_cancelled"]
        )
        filled = [p for (_n, p) in updates if p.get("status") == "filled"]
        self.assertEqual(len(filled), 1)
        commit_fill.assert_called_once()
        self.assertEqual(result["fills"], 1)
        self.assertEqual(inserts, [])

    def test_nonterminal_refetch_stays_pollable(self):
        order = _working_order(idle_seconds=292)
        sb, updates, _ = _mock_supabase(order)
        alpaca = MagicMock()
        alpaca.get_order.side_effect = [
            {"status": "new", "filled_qty": 0},
            {"status": "pending_cancel", "filled_qty": 0},
        ]

        result = alpaca_order_handler.poll_pending_orders(alpaca, sb, USER_ID)

        self.assertEqual(result["watchdog_cancels"], 0)
        self.assertFalse(
            [p for (_n, p) in updates if p.get("status") == "watchdog_cancelled"]
        )
        working = [p for (_n, p) in updates if p.get("status") == "working"]
        self.assertEqual(len(working), 1)

    def test_refetch_failure_makes_no_terminal_write(self):
        order = _working_order(idle_seconds=292)
        sb, updates, _ = _mock_supabase(order)
        alpaca = MagicMock()
        alpaca.get_order.side_effect = [
            {"status": "new", "filled_qty": 0},
            RuntimeError("broker read unavailable"),
        ]

        result = alpaca_order_handler.poll_pending_orders(alpaca, sb, USER_ID)

        self.assertEqual(updates, [])
        self.assertEqual(result["watchdog_cancels"], 0)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("broker read unavailable", result["errors"][0]["error"])

    def test_canceled_with_fill_is_not_clean_watchdog_cancel(self):
        order = _working_order(idle_seconds=292)
        sb, updates, _ = _mock_supabase(order)
        alpaca = MagicMock()
        alpaca.get_order.side_effect = [
            {"status": "new", "filled_qty": 0},
            {"status": "canceled", "filled_qty": "0.5"},
        ]

        result = alpaca_order_handler.poll_pending_orders(alpaca, sb, USER_ID)

        self.assertEqual(result["watchdog_cancels"], 0)
        self.assertFalse(
            [p for (_n, p) in updates if p.get("status") == "watchdog_cancelled"]
        )
        cancelled = [p for (_n, p) in updates if p.get("status") == "cancelled"]
        self.assertEqual(len(cancelled), 1)
        self.assertEqual(cancelled[0]["filled_qty"], 0.5)

    def test_fresh_order_under_threshold_not_cancelled(self):
        order = _working_order(idle_seconds=30)
        sb, updates, _ = _mock_supabase(order)
        alpaca = MagicMock()
        alpaca.get_order.return_value = {"status": "new", "filled_qty": 0}

        alpaca_order_handler.poll_pending_orders(alpaca, sb, USER_ID)

        alpaca.cancel_order.assert_not_called()
        self.assertFalse(
            [p for (_n, p) in updates if p.get("status") == "watchdog_cancelled"]
        )

    def test_threshold_value_unchanged(self):
        """Option A: the constant stays 90 — order_sync also runs ad-hoc /
        back-to-back, so raising it WOULD change marginal cancels."""
        self.assertEqual(alpaca_order_handler.IDLE_WATCHDOG_SECONDS, 90)


class TestCommentsHonesty(unittest.TestCase):
    """Source-level: the vaporware 'resubmit' claims are gone — the file
    must not describe a resubmission the code doesn't perform."""

    def test_no_vaporware_resubmit_comments(self):
        import os

        path = os.path.join(
            os.path.dirname(__file__), "..", "brokers", "alpaca_order_handler.py"
        )
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()
        self.assertNotIn("cancel and resubmit", source)
        self.assertNotIn("mark for resubmission", source)
        # The honest description is present instead.
        self.assertIn("CANCEL-ONLY", source)


if __name__ == "__main__":
    unittest.main()
