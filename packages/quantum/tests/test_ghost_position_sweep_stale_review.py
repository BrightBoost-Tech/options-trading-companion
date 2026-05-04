"""Tests for #98 Option B — ghost_position_sweep stale needs_manual_review check.

Background
----------
PR #853 (Option C) shipped a write-site alert at submit_and_track when an
order is marked needs_manual_review. That covers the moment the stuck state
is created. But if the alert is missed (operator off-hours, paged for
something else, etc.), the order stays in needs_manual_review and the
linked position stays open indefinitely.

The 2026-05-01 BAC incident proved this class: 3-day stuck state, only
caught when the operator manually checked Alpaca dashboard. Per the
loud-error doctrine "anti-pattern 4" (per-iteration recurring catch),
the defense-in-depth pattern is a sweep that surfaces the persistent
stuck state on every cycle until the operator clears it.

This test file guards:
  - Alert wiring (alert_type + severity + metadata fields present in source)
  - Idempotency gate (1-hour dedup window prevents flood at sweep cadence)
  - Behavioral: alert fires when stale + linked-position-open both true
  - Behavioral: alert does NOT fire when within idempotency window
"""

import re
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock


# Mirror test_ghost_position_rescue.py module stubs (alpaca-py not in CI)
_alpaca_pkg = types.ModuleType("alpaca")
_alpaca_trading = types.ModuleType("alpaca.trading")
_alpaca_trading_requests = types.ModuleType("alpaca.trading.requests")
sys.modules.setdefault("alpaca", _alpaca_pkg)
sys.modules.setdefault("alpaca.trading", _alpaca_trading)
sys.modules.setdefault("alpaca.trading.requests", _alpaca_trading_requests)

from packages.quantum.brokers import alpaca_order_handler  # noqa: E402


SWEEP_PATH = (
    Path(__file__).parent.parent / "brokers" / "alpaca_order_handler.py"
)
USER_ID = "test-user-98b"


def _read_sweep_source() -> str:
    return SWEEP_PATH.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────
# Layer 1 — Source-level structural assertions
# ─────────────────────────────────────────────────────────────────────


class TestStaleManualReviewWiring(unittest.TestCase):
    """#98 Option B — alert wiring + structural conventions."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read_sweep_source()

    def test_alert_type_wired(self):
        """The new alert_type must be referenced in ghost_position_sweep."""
        self.assertIn(
            'stale_manual_review_with_open_position', self.src,
            "alert_type='stale_manual_review_with_open_position' must "
            "be wired in ghost_position_sweep — see #98 Option B"
        )

    def test_severity_matches_existing_sweep_convention(self):
        """Existing sweep uses severity='warn' (not 'warning'). The new
        check must match for consistency. Find the alert insert site."""
        # Locate the alert insert with the new alert_type
        match = re.search(
            r'"alert_type":\s*"stale_manual_review_with_open_position".*?\}',
            self.src,
            re.DOTALL,
        )
        self.assertIsNotNone(
            match,
            "stale_manual_review insert dict not found in sweep source",
        )
        self.assertIn(
            '"severity": "warn"', match.group(0),
            "severity must be 'warn' to match existing ghost_position "
            "alert convention in this file",
        )

    def test_operator_action_required_present(self):
        """H5a/H5b convention: alerts include operator_action_required
        runbook text in metadata."""
        self.assertIn('operator_action_required', self.src)
        # Must appear in proximity to the stale_manual_review alert
        match = re.search(
            r'"alert_type":\s*"stale_manual_review_with_open_position"'
            r'.*?operator_action_required',
            self.src,
            re.DOTALL,
        )
        self.assertIsNotNone(
            match,
            "operator_action_required must appear in the "
            "stale_manual_review alert metadata",
        )

    def test_idempotency_gate_present(self):
        """1-hour dedup window prevents flooding risk_alerts at sweep
        cadence (alpaca_order_sync runs every 5 min). Without this, a
        single stuck order produces ~12 alerts/hour."""
        # The dedup query references the alert_type AND filters by
        # metadata->>order_id within a recency window
        self.assertIn(
            'metadata->>order_id', self.src,
            "Idempotency gate must filter prior alerts by order_id JSON "
            "path (no top-level order_id column on risk_alerts)",
        )
        # The recency window is 1 hour
        self.assertIn(
            'timedelta(hours=1)', self.src,
            "Dedup window must be 1 hour — matches design rationale: "
            "BAC's 3-day stuck duration would produce 864 alerts at "
            "5-min sweep cadence without this gate",
        )

    def test_doctrine_reference_present(self):
        """Alert metadata cites the doctrine entry that motivates it.
        Helps future audits trace design intent."""
        self.assertIn(
            'doctrine_ref', self.src,
            "Alert metadata should include doctrine_ref pointing to the "
            "loud_error_doctrine.md entry that motivates this check",
        )

    def test_existing_ghost_position_alert_unchanged(self):
        """Behavioral preservation: this PR adds a new check; it does
        NOT modify the existing ghost_position alert payload. The
        original alert_type, severity, and metadata fields must remain."""
        self.assertIn('"alert_type": "ghost_position"', self.src)
        # Verify the original ghost alert still has its expected_legs metadata
        match = re.search(
            r'"alert_type":\s*"ghost_position".*?"expected_legs"',
            self.src,
            re.DOTALL,
        )
        self.assertIsNotNone(
            match,
            "Existing ghost_position alert payload must not be modified "
            "by this PR — check expected_legs still in metadata",
        )


# ─────────────────────────────────────────────────────────────────────
# Layer 2 — Behavioral tests
# ─────────────────────────────────────────────────────────────────────


def _make_chain_mock(
    table_responses=None,
    insert_sink=None,
    update_sink=None,
):
    """Extended chain mock supporting .filter() (Supabase JSON path query).

    `table_responses` maps table name → list of rows for the .execute()
    result. For tables that need different responses across multiple calls,
    pass a list-of-lists; the mock pops one per .execute() call. Otherwise
    every call against that table returns the same list.
    """
    table_responses = dict(table_responses or {})

    # Normalize: all values become deque-like list of response lists
    queues = {}
    for name, val in table_responses.items():
        if val and isinstance(val[0], list):
            queues[name] = list(val)
        else:
            queues[name] = None  # static — single response forever
            queues[f"__static__{name}"] = val

    mock_supabase = MagicMock()

    def table_side_effect(name):
        chain = MagicMock()

        def _pop_response():
            if queues.get(name) is not None:
                if queues[name]:
                    return queues[name].pop(0)
                return []
            return queues.get(f"__static__{name}", [])

        def execute_side_effect():
            return MagicMock(data=_pop_response())

        chain.execute.side_effect = execute_side_effect
        for method in (
            "select", "eq", "neq", "gte", "lte", "lt", "gt",
            "in_", "order", "limit", "single", "maybe_single",
            "filter",
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


class TestStaleManualReviewBehavioral(unittest.TestCase):
    """Exercise ghost_position_sweep with stale needs_manual_review fixtures."""

    def _setup(self, alpaca_positions, db_positions, db_orders,
               prior_alerts=None, insert_sink=None):
        alpaca = MagicMock()
        alpaca.get_option_positions.return_value = alpaca_positions

        responses = {
            "paper_portfolios": [{"id": "portfolio-98b"}],
            "paper_positions": db_positions,
            "paper_orders": db_orders,
            # paper_positions and risk_alerts are queried multiple times
            # with different filters; the static-list fallback returns the
            # same data for every call. risk_alerts queries: idempotency
            # check (returns prior_alerts or empty).
            "risk_alerts": prior_alerts or [],
        }
        supabase = _make_chain_mock(
            table_responses=responses,
            insert_sink=insert_sink,
        )
        return alpaca, supabase

    def test_fires_alert_for_stale_needs_manual_review_with_open_position(self):
        """Two-hour-old needs_manual_review order linked to an open
        position triggers the new alert. Same shape as 2026-05-01 BAC."""
        old_position_ts = (
            datetime.now(timezone.utc) - timedelta(hours=3)
        ).isoformat()
        stale_order_ts = (
            datetime.now(timezone.utc) - timedelta(hours=2)
        ).isoformat()

        alpaca_positions = []  # No matching legs on Alpaca (but irrelevant
                                # for this check — we test the order path)
        db_positions = [{
            "id": "pos-bac-98b",
            "symbol": "BAC",
            "quantity": 1,
            "created_at": old_position_ts,
            "legs": [],  # legs empty so existing ghost-check skips it
        }]
        db_orders = [{
            "id": "order-bac-stuck-98b",
            "position_id": "pos-bac-98b",
            "status": "needs_manual_review",
            "broker_status": "needs_manual_review",
            "created_at": stale_order_ts,
            "submitted_at": stale_order_ts,
            "broker_response": {
                "error": "insufficient options buying power",
                "attempts": 3,
            },
        }]

        insert_sink = []
        alpaca, supabase = self._setup(
            alpaca_positions, db_positions, db_orders,
            prior_alerts=[],
            insert_sink=insert_sink,
        )

        result = alpaca_order_handler.ghost_position_sweep(
            alpaca, supabase, USER_ID,
        )

        self.assertEqual(result["stale_review_orders_checked"], 1)
        self.assertEqual(result["stale_review_alerts_fired"], 1)

        alerts = [
            p for (t, p) in insert_sink
            if t == "risk_alerts"
            and p.get("alert_type") == "stale_manual_review_with_open_position"
        ]
        self.assertEqual(len(alerts), 1, "Exactly one stale_review alert")
        a = alerts[0]
        self.assertEqual(a["severity"], "warn")
        self.assertEqual(a["position_id"], "pos-bac-98b")
        self.assertEqual(a["symbol"], "BAC")
        self.assertEqual(a["metadata"]["order_id"], "order-bac-stuck-98b")
        self.assertGreaterEqual(a["metadata"]["hours_stale"], 1.9)
        self.assertIn("operator_action_required", a["metadata"])
        self.assertEqual(
            a["metadata"]["broker_status"], "needs_manual_review",
        )

    def test_no_alert_when_position_is_closed(self):
        """If the linked position is no longer open (closed, missing, or
        belongs to a different portfolio), the order is stuck but the
        position-open-too predicate fails — no alert."""
        stale_order_ts = (
            datetime.now(timezone.utc) - timedelta(hours=2)
        ).isoformat()

        # Empty open-positions list → open_position_map is empty →
        # the order's position_id won't be found
        db_orders = [{
            "id": "order-orphan",
            "position_id": "pos-already-closed",
            "status": "needs_manual_review",
            "broker_status": "needs_manual_review",
            "created_at": stale_order_ts,
            "submitted_at": stale_order_ts,
            "broker_response": {"error": "x"},
        }]

        insert_sink = []
        alpaca, supabase = self._setup(
            alpaca_positions=[],
            db_positions=[],  # no open positions
            db_orders=db_orders,
            prior_alerts=[],
            insert_sink=insert_sink,
        )

        result = alpaca_order_handler.ghost_position_sweep(
            alpaca, supabase, USER_ID,
        )

        self.assertEqual(result["stale_review_orders_checked"], 1)
        self.assertEqual(
            result["stale_review_alerts_fired"], 0,
            "Order is stuck but position is not in open set — no alert",
        )
        stale_alerts = [
            p for (t, p) in insert_sink
            if t == "risk_alerts"
            and p.get("alert_type") == "stale_manual_review_with_open_position"
        ]
        self.assertEqual(len(stale_alerts), 0)

    def test_idempotency_gate_skips_recent_duplicate(self):
        """When a prior alert exists for the same order within the last
        hour, the sweep skips it. Without this, sweep cadence would
        flood risk_alerts with ~12 rows per hour for a single stuck
        order."""
        old_position_ts = (
            datetime.now(timezone.utc) - timedelta(hours=3)
        ).isoformat()
        stale_order_ts = (
            datetime.now(timezone.utc) - timedelta(hours=2)
        ).isoformat()

        db_positions = [{
            "id": "pos-bac-dup",
            "symbol": "BAC",
            "quantity": 1,
            "created_at": old_position_ts,
            "legs": [],
        }]
        db_orders = [{
            "id": "order-already-alerted",
            "position_id": "pos-bac-dup",
            "status": "needs_manual_review",
            "broker_status": "needs_manual_review",
            "created_at": stale_order_ts,
            "submitted_at": stale_order_ts,
            "broker_response": {"error": "x"},
        }]
        # Idempotency check returns a prior alert row → skip
        prior_alerts = [{"id": "prior-alert-uuid"}]

        insert_sink = []
        alpaca, supabase = self._setup(
            alpaca_positions=[],
            db_positions=db_positions,
            db_orders=db_orders,
            prior_alerts=prior_alerts,
            insert_sink=insert_sink,
        )

        result = alpaca_order_handler.ghost_position_sweep(
            alpaca, supabase, USER_ID,
        )

        self.assertEqual(result["stale_review_orders_checked"], 1)
        self.assertEqual(
            result["stale_review_alerts_fired"], 0,
            "Prior alert within idempotency window → no new alert fired",
        )
        stale_alerts = [
            p for (t, p) in insert_sink
            if t == "risk_alerts"
            and p.get("alert_type") == "stale_manual_review_with_open_position"
        ]
        self.assertEqual(len(stale_alerts), 0)

    def test_no_alert_when_no_stale_orders_exist(self):
        """Empty paper_orders query result → zero alerts. Sanity check
        the new check doesn't fire spuriously when there's nothing to
        flag."""
        insert_sink = []
        alpaca, supabase = self._setup(
            alpaca_positions=[],
            db_positions=[],
            db_orders=[],  # no needs_manual_review orders
            prior_alerts=[],
            insert_sink=insert_sink,
        )

        result = alpaca_order_handler.ghost_position_sweep(
            alpaca, supabase, USER_ID,
        )

        self.assertEqual(result["stale_review_orders_checked"], 0)
        self.assertEqual(result["stale_review_alerts_fired"], 0)
        # No alerts of either type
        stale_alerts = [
            p for (t, p) in insert_sink
            if t == "risk_alerts"
            and p.get("alert_type") == "stale_manual_review_with_open_position"
        ]
        self.assertEqual(len(stale_alerts), 0)


if __name__ == "__main__":
    unittest.main()
