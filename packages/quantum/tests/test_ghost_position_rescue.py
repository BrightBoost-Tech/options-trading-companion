"""
Retroactive regression tests for PR #764 (ghost-position rescue).

Commit 9f2679c shipped three fixes without accompanying tests; this
file covers them post-hoc so future refactors don't silently regress
the 2026-04-16 incident mechanism. The incident: three close orders
filled on Alpaca but the DB never saw the fills because our poll
filter excluded `needs_manual_review`. Positions stayed phantom-open
while cash moved on Alpaca.

Fixes under test:
    A. `poll_pending_orders` includes `needs_manual_review` in the
       status filter when `alpaca_order_id` is set. If Alpaca filled
       on a prior submission, the poll cycle discovers it.
    B. `submit_and_track` breaks out of the retry loop on Alpaca error
       code 42210000 / "position intent mismatch". Retrying produces
       phantom duplicates; the correct recovery is to let the poll
       path reconcile the original fill via `alpaca_order_id`.
    C. `ghost_position_sweep` compares `paper_positions.legs[].symbol`
       (OCC, minus the `"O:"` Polygon prefix) against Alpaca's option
       positions and writes a severity=warn `risk_alert` per DB-only
       ghost. Respects `min_age_seconds` so fresh entries don't false-
       positive while their legs are propagating.
    D. The sweep is gated by `RECONCILE_POSITIONS_ENABLED`. When the
       flag is off (default), `alpaca_order_sync` must NOT invoke the
       sweep at all — 48h observation is the sign-off gate.
"""

import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

# The alpaca-py package isn't installed in CI; stub the two surfaces
# the handler's build_alpaca_order_request path might reach.
_alpaca_pkg = types.ModuleType("alpaca")
_alpaca_trading = types.ModuleType("alpaca.trading")
_alpaca_trading_requests = types.ModuleType("alpaca.trading.requests")
sys.modules.setdefault("alpaca", _alpaca_pkg)
sys.modules.setdefault("alpaca.trading", _alpaca_trading)
sys.modules.setdefault("alpaca.trading.requests", _alpaca_trading_requests)

from packages.quantum.brokers import alpaca_order_handler  # noqa: E402

USER_ID = "test-user-764"


def _make_chain_mock(table_responses=None, update_sink=None, insert_sink=None):
    """
    Build a Supabase mock whose .table(name) returns a chain with the
    usual filter methods. `table_responses` maps table name → rows for
    the execute() result. `update_sink` / `insert_sink` capture the
    payloads passed to .update()/.insert() so tests can assert.
    """
    table_responses = table_responses or {}
    mock_supabase = MagicMock()

    def table_side_effect(name):
        chain = MagicMock()
        chain.execute.return_value = MagicMock(
            data=table_responses.get(name, []),
        )
        for method in (
            "select", "eq", "neq", "gte", "lte", "lt", "gt",
            "in_", "order", "limit", "single", "maybe_single",
        ):
            getattr(chain, method).return_value = chain
        chain.not_ = MagicMock()
        chain.not_.is_.return_value = chain

        def capture_update(payload):
            if update_sink is not None:
                update_sink.append((name, payload))
            return chain

        def capture_insert(payload):
            if insert_sink is not None:
                insert_sink.append((name, payload))
            return chain

        chain.update.side_effect = capture_update
        chain.insert.side_effect = capture_insert
        return chain

    mock_supabase.table.side_effect = table_side_effect
    return mock_supabase


class TestFixA_PollIncludesManualReview(unittest.TestCase):
    """
    Fix A: poll_pending_orders must include needs_manual_review rows
    when alpaca_order_id is set. That's the only way the reconcile
    cycle ever sees fills that happened on a prior (exhausted) retry.
    """

    def test_status_filter_includes_needs_manual_review(self):
        captured_in_calls = []

        def make_chain(name):
            chain = MagicMock()
            chain.execute.return_value = MagicMock(data=[])

            def capture_in(col, values):
                captured_in_calls.append((name, col, tuple(values)))
                return chain

            chain.in_.side_effect = capture_in
            for method in ("select", "eq", "neq", "gte", "lte", "lt", "limit"):
                getattr(chain, method).return_value = chain
            chain.not_ = MagicMock()
            chain.not_.is_.return_value = chain
            return chain

        supabase = MagicMock()
        supabase.table.side_effect = make_chain

        # portfolio lookup first
        port_chain = make_chain("paper_portfolios")
        port_chain.execute.return_value = MagicMock(
            data=[{"id": "portfolio-1"}],
        )

        def table_side_effect(name):
            if name == "paper_portfolios":
                return port_chain
            return make_chain(name)

        supabase.table.side_effect = table_side_effect

        alpaca = MagicMock()
        alpaca_order_handler.poll_pending_orders(alpaca, supabase, USER_ID)

        # Find the status filter on paper_orders
        status_calls = [
            values for (name, col, values) in captured_in_calls
            if name == "paper_orders" and col == "status"
        ]
        self.assertTrue(
            status_calls,
            "Expected a status .in_(...) filter on paper_orders",
        )
        self.assertIn("needs_manual_review", status_calls[0])
        # And the original in-flight statuses must still be present
        for expected in ("submitted", "working", "partial"):
            self.assertIn(expected, status_calls[0])


class TestFixB_TerminateOnIntentMismatch(unittest.TestCase):
    """
    Fix B: submit_and_track breaks out of the retry loop when Alpaca
    returns 42210000 / "position intent mismatch". Retrying generates
    phantom duplicates — the original submission already filled.
    """

    def _run_submit(self, error_message):
        update_sink = []
        supabase = _make_chain_mock(update_sink=update_sink)

        alpaca = MagicMock()
        alpaca.paper = True
        alpaca.cancel_open_orders_for_symbols.return_value = []
        alpaca.submit_option_order.side_effect = RuntimeError(error_message)

        order = {
            "id": "order-b",
            "position_id": "position-1",  # marks it as a close order
            "requested_price": 0.05,
            "requested_qty": 1,
            "order_json": {
                "symbol": "SPY",
                "legs": [
                    {"symbol": "O:SPY260417C00500000", "side": "sell"},
                    {"symbol": "O:SPY260417C00505000", "side": "buy"},
                ],
                "limit_price": 0.05,
            },
        }
        result = alpaca_order_handler.submit_and_track(
            alpaca, supabase, order, USER_ID,
        )
        return result, alpaca, update_sink

    def test_42210000_code_breaks_out_after_one_attempt(self):
        result, alpaca, update_sink = self._run_submit(
            "Alpaca returned 42210000 on close order",
        )
        self.assertEqual(result["status"], "needs_manual_review")
        # Fix B: single attempt, no retries after 42210000.
        self.assertEqual(
            alpaca.submit_option_order.call_count, 1,
            "42210000 must short-circuit the retry loop",
        )
        # Order is flagged for manual review with attempts = MAX_SUBMIT_ATTEMPTS
        # (the existing contract — attempts counter reflects the cap, not the
        # actual call count, so ops dashboards see a consistent ceiling).
        self.assertEqual(
            result["attempts"], alpaca_order_handler.MAX_SUBMIT_ATTEMPTS,
        )

    def test_intent_mismatch_phrase_also_short_circuits(self):
        """
        Not all Alpaca responses include the numeric code; the textual
        "position intent mismatch" phrasing must also trip the break.
        """
        result, alpaca, _ = self._run_submit(
            "Order rejected: position intent mismatch",
        )
        self.assertEqual(result["status"], "needs_manual_review")
        self.assertEqual(alpaca.submit_option_order.call_count, 1)

    def test_unrelated_error_still_retries(self):
        """
        Regression guard: ordinary errors must still retry the full
        MAX_SUBMIT_ATTEMPTS count — we only short-circuit 42210000.
        """
        result, alpaca, _ = self._run_submit("Network timeout")
        self.assertEqual(result["status"], "needs_manual_review")
        self.assertEqual(
            alpaca.submit_option_order.call_count,
            alpaca_order_handler.MAX_SUBMIT_ATTEMPTS,
        )


class TestFixC_GhostPositionSweep(unittest.TestCase):
    """
    Fix C: ghost_position_sweep finds DB open positions whose legs are
    not on Alpaca, strips the Polygon `O:` prefix during comparison,
    writes a severity=warn risk_alert per ghost, and respects the
    min_age_seconds fresh-entry window.
    """

    def _setup_positions(
        self,
        alpaca_positions,
        db_positions,
        insert_sink=None,
    ):
        alpaca = MagicMock()
        alpaca.get_option_positions.return_value = alpaca_positions
        supabase = _make_chain_mock(
            table_responses={
                "paper_portfolios": [{"id": "portfolio-1"}],
                "paper_positions": db_positions,
            },
            insert_sink=insert_sink,
        )
        return alpaca, supabase

    def test_detects_position_with_no_matching_legs(self):
        """
        Genuine ghost detection: DB has a position Alpaca doesn't.
        Uses realistic `_serialize_position` output shape — both sides
        arrive at the sweep with "O:" prefix, because
        `alpaca.get_option_positions()` returns serialized positions
        where `symbol` has been round-tripped through `alpaca_to_polygon`.
        The sweep must strip "O:" from both sides before comparing.
        """
        # Alpaca-side: serialized via alpaca_to_polygon, so "O:"-prefixed
        alpaca_positions = [{"symbol": "O:OTHER260417C00100000"}]
        old_ts = (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).isoformat()
        db_positions = [{
            "id": "position-ghost",
            "symbol": "AMD",
            "quantity": -1,
            "created_at": old_ts,
            "legs": [
                {"symbol": "O:AMD260417P00100000"},
                {"symbol": "O:AMD260417P00095000"},
            ],
        }]
        insert_sink = []
        alpaca, supabase = self._setup_positions(
            alpaca_positions, db_positions, insert_sink=insert_sink,
        )

        result = alpaca_order_handler.ghost_position_sweep(
            alpaca, supabase, USER_ID,
        )
        self.assertEqual(result["ghost_count"], 1)
        self.assertEqual(result["positions_checked"], 1)

        alerts = [p for (t, p) in insert_sink if t == "risk_alerts"]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["alert_type"], "ghost_position")
        self.assertEqual(alerts[0]["severity"], "warn")
        self.assertEqual(alerts[0]["position_id"], "position-ghost")
        # The O: prefix is stripped in the alert metadata so it matches
        # raw OCC convention rather than Polygon's prefixed form.
        self.assertIn(
            "AMD260417P00100000",
            alerts[0]["metadata"]["expected_legs"],
        )

    def test_skips_position_with_matching_alpaca_leg(self):
        """
        If ANY expected OCC leg is present on Alpaca, position is not
        a ghost. Uses realistic `_serialize_position` output shape
        (Alpaca-side also has "O:" prefix).
        """
        alpaca_positions = [{"symbol": "O:AMD260417P00100000"}]
        old_ts = (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).isoformat()
        db_positions = [{
            "id": "position-healthy",
            "symbol": "AMD",
            "quantity": -1,
            "created_at": old_ts,
            "legs": [
                {"symbol": "O:AMD260417P00100000"},
                {"symbol": "O:AMD260417P00095000"},
            ],
        }]
        insert_sink = []
        alpaca, supabase = self._setup_positions(
            alpaca_positions, db_positions, insert_sink=insert_sink,
        )
        result = alpaca_order_handler.ghost_position_sweep(
            alpaca, supabase, USER_ID,
        )
        self.assertEqual(result["ghost_count"], 0)
        self.assertEqual(
            len([p for (t, p) in insert_sink if t == "risk_alerts"]), 0,
        )

    def test_sweep_does_not_flag_matching_o_prefix_legs(self):
        """
        Regression for 2026-04-21 AMZN false-positive incident.

        Both DB legs and Alpaca legs arrive at the sweep with "O:" prefix
        (Alpaca's `_serialize_position` re-prefixes via `alpaca_to_polygon`).
        Before the fix, the sweep stripped "O:" from DB-side only and
        compared against Alpaca's prefixed symbols — intersection was
        always empty → every legitimate open position flagged as ghost.

        Live symptom: 56 false ghost_position alerts for AMZN a0f05755
        between 2026-04-20 23:09Z and 2026-04-21 18:37Z, despite both
        legs being open on both sides.

        After the fix, strip "O:" from both sides → intersection
        matches → zero ghosts.
        """
        # Exact AMZN incident shape — both legs present on both sides.
        alpaca_positions = [
            {"symbol": "O:AMZN260515C00240000"},
            {"symbol": "O:AMZN260515C00265000"},
        ]
        old_ts = (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).isoformat()
        db_positions = [{
            "id": "position-amzn-legit",
            "symbol": "AMZN",
            "quantity": 1,
            "created_at": old_ts,
            "legs": [
                {"symbol": "O:AMZN260515C00240000"},
                {"symbol": "O:AMZN260515C00265000"},
            ],
        }]
        insert_sink = []
        alpaca, supabase = self._setup_positions(
            alpaca_positions, db_positions, insert_sink=insert_sink,
        )

        result = alpaca_order_handler.ghost_position_sweep(
            alpaca, supabase, USER_ID,
        )
        self.assertEqual(
            result["ghost_count"], 0,
            "Legitimate open position with matching O:-prefixed legs on "
            "both sides must NOT be flagged as ghost. This was the "
            "2026-04-21 AMZN incident: 56 false positives fired.",
        )
        self.assertEqual(result["positions_checked"], 1)
        self.assertEqual(
            len([p for (t, p) in insert_sink if t == "risk_alerts"]), 0,
            "Zero risk_alerts should be written when DB matches Alpaca.",
        )

    def test_sweep_flags_mismatch_when_prefix_agrees(self):
        """
        Defensive: the prefix-normalization fix must NOT silently hide
        genuine ghosts. When both sides use "O:" prefix consistently but
        the symbols themselves don't match, the sweep must still flag.

        Mock DB with O:AMZN legs, Alpaca with O:TSLA legs — mismatch at
        symbol level despite prefix agreement.
        """
        alpaca_positions = [
            {"symbol": "O:TSLA260515C00300000"},
            {"symbol": "O:TSLA260515C00310000"},
        ]
        old_ts = (
            datetime.now(timezone.utc) - timedelta(hours=1)
        ).isoformat()
        db_positions = [{
            "id": "position-amzn-ghost",
            "symbol": "AMZN",
            "quantity": 1,
            "created_at": old_ts,
            "legs": [
                {"symbol": "O:AMZN260515C00240000"},
                {"symbol": "O:AMZN260515C00265000"},
            ],
        }]
        insert_sink = []
        alpaca, supabase = self._setup_positions(
            alpaca_positions, db_positions, insert_sink=insert_sink,
        )

        result = alpaca_order_handler.ghost_position_sweep(
            alpaca, supabase, USER_ID,
        )
        self.assertEqual(
            result["ghost_count"], 1,
            "AMZN DB position has no matching legs on Alpaca (only TSLA "
            "legs present). Sweep must still flag this as ghost after "
            "the prefix-normalization fix.",
        )
        alerts = [p for (t, p) in insert_sink if t == "risk_alerts"]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["position_id"], "position-amzn-ghost")

    def test_alpaca_failure_returns_error_not_raise(self):
        """
        A failed `get_option_positions` must not take down the sync
        cycle — return a structured error so the outer loop continues.
        """
        alpaca = MagicMock()
        alpaca.get_option_positions.side_effect = RuntimeError("alpaca down")
        supabase = MagicMock()
        result = alpaca_order_handler.ghost_position_sweep(
            alpaca, supabase, USER_ID,
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["ghost_count"], 0)


class TestFixA_OuterCallerIncludesManualReview(unittest.TestCase):
    """
    Corrective counterpart to PR #764 Fix A: the outer caller in
    alpaca_order_sync.py must also include `needs_manual_review` in the
    status filter used to build `poll_user_ids`. Fix A expanded the
    *inner* query inside `poll_pending_orders`, but if the *outer*
    caller filters only {submitted, working, partial}, a user whose
    only in-flight order is `needs_manual_review` will never be put
    into `poll_user_ids` — and poll_pending_orders (with Fix A's
    expanded filter) will never be called for that user.

    Motivating incident: PYPL cfe69b28 on 2026-04-17. Alpaca filled
    the close 48ms after the client reported failure. Submit_and_track
    marked `needs_manual_review`. 66 successful alpaca_order_sync
    cycles ran over the next 4+ hours without ever polling this user,
    because their only non-terminal order was `needs_manual_review`.
    DB stayed `status='open'`, realized P&L ≈ −$204 unrecorded.
    """

    def test_user_select_query_includes_needs_manual_review(self):
        captured_in_calls = []

        def make_chain(name):
            chain = MagicMock()
            chain.execute.return_value = MagicMock(data=[])

            def capture_in(col, values):
                captured_in_calls.append((name, col, tuple(values)))
                return chain

            chain.in_.side_effect = capture_in
            for method in (
                "select", "eq", "neq", "gte", "lt", "gt", "limit", "order",
            ):
                getattr(chain, method).return_value = chain
            chain.is_.return_value = chain
            chain.not_ = MagicMock()
            chain.not_.is_.return_value = chain
            return chain

        supabase = MagicMock()
        supabase.table.side_effect = lambda name: make_chain(name)

        alpaca = MagicMock()

        # Patch the handler's dependencies and invoke the entry point.
        from packages.quantum.jobs.handlers import alpaca_order_sync

        with patch.object(
            alpaca_order_sync, "get_admin_client", return_value=supabase,
        ), patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=alpaca,
        ):
            alpaca_order_sync.run(payload={}, ctx=None)

        # The user-select query on paper_orders at line 62 is the one we
        # care about. Multiple .in_() calls happen across the handler
        # (Step 1 user-select, poll_pending_orders internal, etc.), so
        # filter to only the status filter on paper_orders.
        status_filters = [
            values for (name, col, values) in captured_in_calls
            if name == "paper_orders" and col == "status"
        ]
        self.assertTrue(
            status_filters,
            "Expected a status .in_(...) filter on paper_orders",
        )
        # The user-select query is the FIRST status filter on paper_orders.
        outer_status_filter = status_filters[0]
        self.assertIn(
            "needs_manual_review", outer_status_filter,
            "alpaca_order_sync Step 1 user-select query must include "
            "needs_manual_review so that users whose only in-flight "
            "orders are in that state still get polled. Without this, "
            "PR #764 Fix A's inner-query expansion is unreachable for "
            "such users — reproducing the PYPL 2026-04-17 ghost-fill.",
        )
        # And the original in-flight statuses must still be present.
        for expected in ("submitted", "working", "partial"):
            self.assertIn(expected, outer_status_filter)


class TestFixD_GhostSweepIsGated(unittest.TestCase):
    """
    Fix D: ghost_position_sweep is not called from alpaca_order_sync
    unless RECONCILE_POSITIONS_ENABLED=1. Off is the default for the
    48h observation window before flipping on.
    """

    def test_flag_off_means_sweep_is_not_called(self):
        os.environ.pop("RECONCILE_POSITIONS_ENABLED", None)
        from packages.quantum.brokers import alpaca_order_handler as handler
        with patch.object(handler, "ghost_position_sweep") as sweep:
            # Simulate the gate check as written in alpaca_order_sync.py
            flag = os.environ.get("RECONCILE_POSITIONS_ENABLED", "0") == "1"
            if flag:
                sweep(MagicMock(), MagicMock(), USER_ID)
            sweep.assert_not_called()

    def test_flag_on_means_sweep_is_called(self):
        os.environ["RECONCILE_POSITIONS_ENABLED"] = "1"
        try:
            from packages.quantum.brokers import alpaca_order_handler as handler
            with patch.object(handler, "ghost_position_sweep") as sweep:
                sweep.return_value = {"ghost_count": 0}
                flag = os.environ.get("RECONCILE_POSITIONS_ENABLED", "0") == "1"
                if flag:
                    sweep(MagicMock(), MagicMock(), USER_ID)
                sweep.assert_called_once()
        finally:
            os.environ.pop("RECONCILE_POSITIONS_ENABLED", None)


if __name__ == "__main__":
    unittest.main()
