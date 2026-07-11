"""PR2 (2026-07-11) — deterministic client_order_id attach + targeted reconcile.

Closes the response-lost blind class (P0-A completion). Tests drive PRODUCTION
functions with fakes (no real Alpaca SDK dependency — matches the repo's mock
convention):

  T1  id attached on entry + close + resting-TP GTC submits (the one funnel)
  T2  duplicate-422 classifier resolves by lookup — no false needs_manual_review
  T3  reconciler Step 1.5 FOUND → backfill alpaca_order_id
  T4  reconciler Step 1.5 404 → re-arm to terminal 'cancelled'
  T5  reconcile flag OFF → resolve inert, but id-attach still writes (additive)
  T6  legacy rows (client_order_id NULL) untouched by the resolver
"""

import unittest
from unittest.mock import MagicMock, patch

from packages.quantum.brokers.alpaca_order_handler import (
    build_alpaca_order_request,
    deterministic_client_order_id,
    submit_and_track,
)
from packages.quantum.jobs.handlers.alpaca_order_sync import (
    _client_order_id_reconcile_enabled,
    _resolve_lost_submit,
)


# ── shared fakes (modeled on test_alpaca_order_handler_alert.py) ────────────

def _make_supabase_mock():
    m = MagicMock()
    chain = MagicMock()
    for method in ("select", "eq", "in_", "is_", "not_", "lt", "neq", "single", "limit", "order"):
        getattr(chain, method).return_value = chain
    chain.update.return_value = chain
    chain.insert.return_value = chain
    chain.execute.return_value = MagicMock(data=[], count=0)
    m.table.return_value = chain
    return m


def _entry_order(order_id="entry-1", exec_mode="alpaca_live"):
    return {
        "id": order_id,
        "execution_mode": exec_mode,
        "requested_price": 1.20,
        "requested_qty": 1,
        "order_json": {
            "symbol": "SPY", "side": "buy",
            "legs": [
                {"symbol": "SPY260605C00500000", "side": "buy"},
                {"symbol": "SPY260605C00505000", "side": "sell"},
            ],
        },
    }


def _close_order(order_id="close-1", exec_mode="alpaca_live"):
    return {
        "id": order_id, "position_id": "pos-1", "execution_mode": exec_mode,
        "order_json": {
            "limit_price": 1.50, "side": "buy",
            "legs": [
                {"symbol": "BAC260605C00051000", "side": "buy"},
                {"symbol": "BAC260605C00056000", "side": "sell"},
            ],
        },
    }


def _gtc_order(order_id="gtc-1", exec_mode="alpaca_live"):
    # A resting-TP GTC close on a net-credit structure (limit encoded credit).
    return {
        "id": order_id, "position_id": "pos-2", "execution_mode": exec_mode,
        "order_json": {
            "limit_price": 0.81, "side": "buy", "time_in_force": "gtc",
            "is_credit_close": True,
            "legs": [
                {"symbol": "QQQ260710C00560000", "side": "buy"},
                {"symbol": "QQQ260710C00565000", "side": "sell"},
            ],
        },
    }


# ── T1 — id attached across all three funnel entrances ──────────────────────

class TestT1IdAttach(unittest.TestCase):
    def test_entry_carries_deterministic_id(self):
        o = _entry_order("entry-1")
        req = build_alpaca_order_request(o)
        self.assertEqual(req["client_order_id"], "otc1-l-entry-1")

    def test_close_carries_deterministic_id(self):
        o = _close_order("close-1")
        req = build_alpaca_order_request(o)
        self.assertEqual(req["client_order_id"], "otc1-l-close-1")

    def test_gtc_carries_deterministic_id_and_is_gtc(self):
        o = _gtc_order("gtc-1")
        req = build_alpaca_order_request(o)
        self.assertEqual(req["client_order_id"], "otc1-l-gtc-1")
        self.assertEqual(req["time_in_force"], "gtc")

    def test_persisted_column_preferred_over_recompute(self):
        o = _entry_order("entry-9")
        o["client_order_id"] = "otc1-l-PERSISTED"
        req = build_alpaca_order_request(o)
        self.assertEqual(req["client_order_id"], "otc1-l-PERSISTED")

    def test_scheme_paper_vs_live_discriminator(self):
        self.assertEqual(
            deterministic_client_order_id({"id": "x", "execution_mode": "alpaca_paper"}),
            "otc1-p-x",
        )
        self.assertEqual(
            deterministic_client_order_id({"id": "x", "execution_mode": "alpaca_live"}),
            "otc1-l-x",
        )

    def test_scheme_length_and_charset(self):
        import re
        coid = deterministic_client_order_id(
            {"id": "3fa85f64-5717-4562-b3fc-2c963f66afa6", "execution_mode": "alpaca_live"}
        )
        self.assertLessEqual(len(coid), 128)
        self.assertRegex(coid, r"^[a-z0-9-]+$")

    def test_no_id_is_none_byte_identical(self):
        # No row id → None → submit_option_order's exclude_none drops it →
        # byte-identical to a legacy submit (Alpaca auto-generates one).
        o = _entry_order("x")
        del o["id"]
        req = build_alpaca_order_request(o)
        self.assertIsNone(req["client_order_id"])


# ── T2 — duplicate-422 classifier ───────────────────────────────────────────

class TestT2DuplicateClassifier(unittest.TestCase):
    def _run(self, dup_msg):
        alpaca = MagicMock()
        alpaca.paper = False
        alpaca.cancel_open_orders_for_symbols.return_value = []
        alpaca.submit_option_order.side_effect = Exception(dup_msg)
        alpaca.get_order_by_client_id.return_value = {
            "alpaca_order_id": "brk-777", "status": "accepted",
        }
        supabase = _make_supabase_mock()
        with patch("packages.quantum.brokers.alpaca_order_handler.time") as mt, \
             patch("packages.quantum.observability.alerts.alert") as mock_alert, \
             patch("packages.quantum.observability.alerts._get_admin_supabase",
                   return_value=MagicMock()):
            mt.monotonic.return_value = 0.0
            mt.sleep.return_value = None
            result = submit_and_track(alpaca, supabase, _close_order("dup-1"), "u1")
        return result, alpaca, supabase, mock_alert

    def test_duplicate_resolves_by_lookup_no_false_critical(self):
        result, alpaca, supabase, mock_alert = self._run("client_order_id must be unique")
        # Resolved as submitted via lookup — NOT needs_manual_review.
        self.assertEqual(result["status"], "submitted")
        self.assertTrue(result.get("resolved_by_client_order_id"))
        alpaca.get_order_by_client_id.assert_called_once_with("otc1-l-dup-1")
        # No critical alert fired.
        self.assertEqual(mock_alert.call_count, 0)
        # No needs_manual_review write; a backfill write DID happen.
        updates = [c.args[0] for c in supabase.table.return_value.update.call_args_list if c.args]
        self.assertFalse(any(u.get("status") == "needs_manual_review" for u in updates))
        self.assertTrue(any(u.get("alpaca_order_id") == "brk-777"
                            and u.get("status") == "submitted" for u in updates))

    def test_duplicate_but_not_found_falls_through_loud(self):
        # Duplicate reported but lookup finds nothing → anomalous → standard
        # needs_manual_review path (loud), never a silent swallow.
        alpaca = MagicMock()
        alpaca.paper = False
        alpaca.cancel_open_orders_for_symbols.return_value = []
        alpaca.submit_option_order.side_effect = Exception("client_order_id must be unique")
        alpaca.get_order_by_client_id.return_value = None
        supabase = _make_supabase_mock()
        with patch("packages.quantum.brokers.alpaca_order_handler.time") as mt, \
             patch("packages.quantum.observability.alerts.alert") as mock_alert, \
             patch("packages.quantum.observability.alerts._get_admin_supabase",
                   return_value=MagicMock()):
            mt.monotonic.return_value = 0.0
            mt.sleep.return_value = None
            result = submit_and_track(alpaca, supabase, _close_order("dup-2"), "u1")
        self.assertEqual(result["status"], "needs_manual_review")
        self.assertEqual(mock_alert.call_count, 1)


# ── T3 / T4 — reconciler Step 1.5 ───────────────────────────────────────────

class TestT3T4Reconciler(unittest.TestCase):
    def _row(self):
        return {"id": "ord-1", "client_order_id": "otc1-l-ord-1",
                "status": "needs_manual_review", "position_id": "pos-1"}

    def test_found_backfills(self):
        alpaca = MagicMock()
        alpaca.get_order_by_client_id.return_value = {
            "alpaca_order_id": "brk-1", "status": "accepted",
        }
        client = _make_supabase_mock()
        res = _resolve_lost_submit(alpaca, client, self._row())
        self.assertEqual(res, "backfilled")
        upd = client.table.return_value.update.call_args.args[0]
        self.assertEqual(upd["alpaca_order_id"], "brk-1")
        self.assertEqual(upd["status"], "submitted")

    def test_404_rearms_to_cancelled(self):
        alpaca = MagicMock()
        alpaca.get_order_by_client_id.return_value = None
        client = _make_supabase_mock()
        res = _resolve_lost_submit(alpaca, client, self._row())
        self.assertEqual(res, "rearmed")
        upd = client.table.return_value.update.call_args.args[0]
        self.assertEqual(upd["status"], "cancelled")
        self.assertIn("cancelled_reason", upd)
        self.assertIn("cancelled_at", upd)


# ── T5 — flag OFF: resolve inert, attach still writes ───────────────────────

class TestT5FlagOff(unittest.TestCase):
    def test_reconcile_flag_polarity(self):
        import os
        old = os.environ.get("CLIENT_ORDER_ID_RECONCILE_ENABLED")
        try:
            for val in ("0", "false", "no", "off"):
                os.environ["CLIENT_ORDER_ID_RECONCILE_ENABLED"] = val
                self.assertFalse(_client_order_id_reconcile_enabled())
            os.environ.pop("CLIENT_ORDER_ID_RECONCILE_ENABLED", None)
            self.assertTrue(_client_order_id_reconcile_enabled())  # default-ON
            os.environ["CLIENT_ORDER_ID_RECONCILE_ENABLED"] = "1"
            self.assertTrue(_client_order_id_reconcile_enabled())
        finally:
            if old is None:
                os.environ.pop("CLIENT_ORDER_ID_RECONCILE_ENABLED", None)
            else:
                os.environ["CLIENT_ORDER_ID_RECONCILE_ENABLED"] = old

    def test_attach_is_not_gated_by_reconcile_flag(self):
        import os
        old = os.environ.get("CLIENT_ORDER_ID_RECONCILE_ENABLED")
        try:
            os.environ["CLIENT_ORDER_ID_RECONCILE_ENABLED"] = "0"
            req = build_alpaca_order_request(_entry_order("e2"))
            self.assertEqual(req["client_order_id"], "otc1-l-e2")
        finally:
            if old is None:
                os.environ.pop("CLIENT_ORDER_ID_RECONCILE_ENABLED", None)
            else:
                os.environ["CLIENT_ORDER_ID_RECONCILE_ENABLED"] = old


# ── T6 — legacy rows (NULL client_order_id) untouched ───────────────────────

class TestT6LegacyRows(unittest.TestCase):
    def test_null_client_order_id_is_noop(self):
        alpaca = MagicMock()
        client = _make_supabase_mock()
        res = _resolve_lost_submit(alpaca, client, {"id": "x", "client_order_id": None})
        self.assertEqual(res, "noop")
        alpaca.get_order_by_client_id.assert_not_called()
        client.table.return_value.update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
