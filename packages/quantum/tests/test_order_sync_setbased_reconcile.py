"""Tests for the set-based Step-3 stuck-open reconcile (audit Area 5).

The prior shape fetched EVERY historical filled order with a position_id
(no date bound, growing +1 per close forever) and issued one
paper_positions "is it still open" round-trip per close-engine row —
~59 round-trips per run, 96 runs/day, the job's entire ~6.5s runtime
floor. The rewrite scopes the stuck query to the OPEN position set:
membership in open_position_ids IS the still-open check.

Pins:
- a stuck-open LIVE position with a filled close order is still reconciled
  (semantics preserved)
- orders pointing at CLOSED positions are never fetched/processed (the
  O(historical) -> O(open) inversion)
- empty open book -> Step 3 no-ops without error
- entry orders (non-close source_engine) never close a position
- shadow-portfolio exclusion retained (handler-level proof lives in
  test_paper_shadow_reconcile_isolation.py, which also pins the literal
  exclusion line at source level)
"""

import os
import unittest
from unittest import mock

from packages.quantum.tests.test_paper_shadow_reconcile_isolation import (
    _FakeSupabase,
)


def _run_with(tables):
    supa = _FakeSupabase(tables)
    from packages.quantum.jobs.handlers import alpaca_order_sync
    closed = []

    def _fake_close(client, pid, filled_order, alpaca_data):
        closed.append(pid)

    with mock.patch.object(alpaca_order_sync, "get_admin_client", return_value=supa), \
         mock.patch("packages.quantum.brokers.alpaca_client.get_alpaca_client",
                    return_value=mock.MagicMock()), \
         mock.patch("packages.quantum.brokers.alpaca_order_handler._close_position_on_fill",
                    side_effect=_fake_close), \
         mock.patch.dict(os.environ, {"RECONCILE_POSITIONS_ENABLED": "0"}, clear=False):
        result = alpaca_order_sync.run({})
    return result, closed, supa


def _close_order(order_id, position_id, portfolio="port-live",
                 source_engine="paper_exit_evaluator"):
    return {
        "id": order_id, "portfolio_id": portfolio, "status": "filled",
        "position_id": position_id, "filled_qty": 1, "side": "sell",
        "alpaca_order_id": f"ax-{order_id}", "avg_fill_price": 1.0,
        "filled_at": None, "broker_response": {},
        "order_json": {"source_engine": source_engine},
    }


class TestSetBasedReconcile(unittest.TestCase):
    def test_stuck_open_position_still_reconciled(self):
        result, closed, _ = _run_with({
            "paper_portfolios": [
                {"id": "port-live", "user_id": "U", "routing_mode": "live_eligible"},
            ],
            "paper_orders": [_close_order("ord-1", "pos-open")],
            "paper_positions": [{"id": "pos-open", "status": "open"}],
        })
        self.assertEqual(closed, ["pos-open"])
        self.assertEqual(result.get("stuck_open_closed"), 1)

    def test_historical_closed_positions_never_processed(self):
        # The O(historical)->O(open) inversion: 3 historical close orders on
        # CLOSED positions produce zero reconcile work; only the open one is
        # touched.
        result, closed, _ = _run_with({
            "paper_portfolios": [
                {"id": "port-live", "user_id": "U", "routing_mode": "live_eligible"},
            ],
            "paper_orders": [
                _close_order("h1", "pos-closed-1"),
                _close_order("h2", "pos-closed-2"),
                _close_order("h3", "pos-closed-3"),
                _close_order("ord-open", "pos-open"),
            ],
            "paper_positions": [
                {"id": "pos-closed-1", "status": "closed"},
                {"id": "pos-closed-2", "status": "closed"},
                {"id": "pos-closed-3", "status": "closed"},
                {"id": "pos-open", "status": "open"},
            ],
        })
        self.assertEqual(closed, ["pos-open"])
        self.assertEqual(result.get("stuck_open_closed"), 1)

    def test_empty_open_book_noops_cleanly(self):
        result, closed, _ = _run_with({
            "paper_portfolios": [
                {"id": "port-live", "user_id": "U", "routing_mode": "live_eligible"},
            ],
            "paper_orders": [
                _close_order("h1", "pos-closed-1"),
            ],
            "paper_positions": [
                {"id": "pos-closed-1", "status": "closed"},
            ],
        })
        self.assertEqual(closed, [])
        self.assertEqual(result.get("stuck_open_closed"), 0)
        self.assertTrue(result.get("ok"))

    def test_entry_orders_never_close_positions(self):
        result, closed, _ = _run_with({
            "paper_portfolios": [
                {"id": "port-live", "user_id": "U", "routing_mode": "live_eligible"},
            ],
            "paper_orders": [
                _close_order("ord-entry", "pos-open", source_engine="midday_entry"),
            ],
            "paper_positions": [{"id": "pos-open", "status": "open"}],
        })
        self.assertEqual(closed, [])
        self.assertEqual(result.get("stuck_open_closed"), 0)

    def test_poll_failure_reaches_runner_as_partial(self):
        from packages.quantum.jobs.handlers import alpaca_order_sync
        from packages.quantum.jobs.runner import _classify_handler_return

        pending = {
            "id": "ord-pending",
            "user_id": "U",
            "portfolio_id": "port-live",
            "status": "working",
            "alpaca_order_id": "alp-pending",
            "filled_qty": 0,
            "position_id": None,
            "order_json": {},
        }
        supa = _FakeSupabase({
            "paper_portfolios": [
                {
                    "id": "port-live",
                    "user_id": "U",
                    "routing_mode": "live_eligible",
                },
            ],
            "paper_orders": [pending],
            "paper_positions": [],
        })
        poll_result = {
            "total_polled": 1,
            "fills": 0,
            "partials": 0,
            "cancels": 0,
            "unchanged": 0,
            "errors": [
                {
                    "order_id": "ord-pending",
                    "error": "watchdog broker refetch failed",
                }
            ],
        }

        with (
            mock.patch.object(
                alpaca_order_sync, "get_admin_client", return_value=supa
            ),
            mock.patch(
                "packages.quantum.brokers.alpaca_client.get_alpaca_client",
                return_value=mock.MagicMock(),
            ),
            mock.patch(
                "packages.quantum.brokers.alpaca_order_handler.poll_pending_orders",
                return_value=poll_result,
            ) as poll,
            mock.patch.dict(
                os.environ, {"RECONCILE_POSITIONS_ENABLED": "0"}, clear=False
            ),
        ):
            result = alpaca_order_sync.run({})

        poll.assert_called_once()
        self.assertFalse(result["ok"])
        self.assertEqual(result["counts"]["errors"], 1)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(len(result["error_details"]), 1)
        self.assertEqual(_classify_handler_return(result), "partial")


if __name__ == "__main__":
    unittest.main()
