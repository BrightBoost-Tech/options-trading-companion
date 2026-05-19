"""
Regression tests for the universe_selection_log observability surface
introduced 2026-05-20 (H9 silent-decision generalization).

Closes the gap discovered in the 2026-05-19 funnel diagnostic:
universe_service.get_scan_candidates(limit=50) was silently dropping
20 of 70 active symbols every cycle with zero observability.

Three guarantees verified here:

1. The selection-log shape captures BOTH selected and dropped
   symbols (the inclusion-only shape would have missed the
   originating defect).
2. The dropped-symbol list is the universe tail beyond `limit`,
   sorted consistently with the inclusion ordering.
3. The write itself is H9-compliant: failure produces an
   `alert()` call (not a silent swallow). Observability is the
   whole point — the writer can't itself be silent-failure-prone.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Stub alpaca-py so imports resolve in the test venv (matches the
# convention from test_h9_legacy_sweep.py).
sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
sys.modules.setdefault(
    "alpaca.trading.requests", types.ModuleType("alpaca.trading.requests")
)


class _AlertCapture:
    """Captures alert() calls. Substitute for the real alert helper
    so we can assert against the alert payload without touching
    Supabase."""

    def __init__(self):
        self.calls = []

    def __call__(self, supabase, **kwargs):
        self.calls.append({"supabase": supabase, **kwargs})


def _build_service(scan_rows, insert_response=None, insert_raises=None):
    """Build a UniverseService with mocked Supabase + Polygon.

    `scan_rows` is the list of rows returned by the
    scanner_universe SELECT query. `insert_response` (or
    `insert_raises`) controls the universe_selection_log INSERT
    side effect."""
    from packages.quantum.services.universe_service import UniverseService

    client = MagicMock()

    # scanner_universe SELECT chain:
    #   .table("scanner_universe").select(...).eq(...).order(...).order(...).execute()
    scanner_query = MagicMock()
    scanner_query.execute.return_value = MagicMock(data=scan_rows)

    # universe_selection_log INSERT chain:
    #   .table("universe_selection_log").insert(payload).execute()
    log_insert = MagicMock()
    log_execute = MagicMock()
    if insert_raises is not None:
        log_execute.execute.side_effect = insert_raises
    else:
        # Default: insert returns single-row data (verified-write
        # anchor passes).
        log_execute.execute.return_value = MagicMock(
            data=(insert_response if insert_response is not None
                  else [{"id": "log-row-1"}])
        )
    log_insert.insert.return_value = log_execute

    def table_router(name):
        if name == "scanner_universe":
            return scanner_query
        if name == "universe_selection_log":
            return log_insert
        # Unknown table — fall back to a default mock so any
        # incidental .table() call doesn't blow up.
        return MagicMock()

    # Build the routing for .select().eq().order().order().execute()
    scanner_query.select.return_value = scanner_query
    scanner_query.eq.return_value = scanner_query
    scanner_query.order.return_value = scanner_query
    scanner_query.limit.return_value = scanner_query

    client.table.side_effect = table_router

    with patch(
        "packages.quantum.services.universe_service.PolygonService"
    ), patch(
        "packages.quantum.services.universe_service.EarningsCalendarService"
    ):
        svc = UniverseService(client)

    return svc, client, log_insert


def _fixture_rows():
    """Universe fixture mirroring the 2026-05-19 finding: 5 active
    rows with descending liquidity_score. With limit=3, the bottom
    2 are dropped — exactly the silent-truncation shape this PR
    closes."""
    return [
        {"symbol": "AAPL", "earnings_date": "2026-04-30", "liquidity_score": 100},
        {"symbol": "MSFT", "earnings_date": "2026-07-27", "liquidity_score": 100},
        {"symbol": "SBUX", "earnings_date": "2026-07-27", "liquidity_score": 90},
        {"symbol": "QQQ",  "earnings_date": None,         "liquidity_score": 60},
        {"symbol": "DIA",  "earnings_date": None,         "liquidity_score": 50},
    ]


# ─────────────────────────────────────────────────────────────────
# Test 1 — selection log shape
# ─────────────────────────────────────────────────────────────────


class TestUniverseSelectionLogShape(unittest.TestCase):
    """The selection log captures the full decision: selected +
    dropped symbols, both score thresholds, and caller identity."""

    def test_log_row_written_on_every_call(self):
        svc, _, log_insert = _build_service(_fixture_rows())
        svc.get_scan_candidates(limit=3, caller="test.suite")
        self.assertEqual(
            log_insert.insert.call_count, 1,
            "Exactly one universe_selection_log insert per call",
        )

    def test_payload_includes_total_and_counts(self):
        svc, _, log_insert = _build_service(_fixture_rows())
        svc.get_scan_candidates(limit=3, caller="test.suite")
        payload = log_insert.insert.call_args[0][0]
        self.assertEqual(payload["total_active"], 5)
        self.assertEqual(payload["limit_applied"], 3)
        self.assertEqual(payload["selected_count"], 3)
        self.assertEqual(payload["dropped_count"], 2)

    def test_payload_captures_score_thresholds(self):
        svc, _, log_insert = _build_service(_fixture_rows())
        svc.get_scan_candidates(limit=3, caller="test.suite")
        payload = log_insert.insert.call_args[0][0]
        # Selected tail (lowest in-set) is SBUX@90; dropped head
        # (highest out-of-set) is QQQ@60. The gap is the policy
        # signal.
        self.assertEqual(payload["score_threshold"], 90)
        self.assertEqual(payload["score_at_cutoff"], 60)

    def test_payload_metadata_captures_caller(self):
        svc, _, log_insert = _build_service(_fixture_rows())
        svc.get_scan_candidates(limit=3, caller="test.suite")
        payload = log_insert.insert.call_args[0][0]
        self.assertEqual(payload["metadata"]["caller"], "test.suite")
        self.assertFalse(payload["metadata"]["fallback_used"])
        self.assertEqual(
            payload["metadata"]["sort_order"],
            "liquidity_score DESC, symbol ASC",
        )

    def test_function_return_value_unchanged_by_logging(self):
        """The candidate list returned to the caller is unchanged
        in shape from the pre-PR contract — only the side-effect
        surface is new."""
        svc, _, _ = _build_service(_fixture_rows())
        result = svc.get_scan_candidates(limit=3, caller="test.suite")
        self.assertEqual(len(result), 3)
        self.assertEqual(
            [r["symbol"] for r in result],
            ["AAPL", "MSFT", "SBUX"],
        )
        for row in result:
            self.assertIn("symbol", row)
            self.assertIn("earnings_date", row)


# ─────────────────────────────────────────────────────────────────
# Test 2 — dropped symbols captured (the originating defect class)
# ─────────────────────────────────────────────────────────────────


class TestUniverseSelectionLogDroppedSymbols(unittest.TestCase):
    """The dropped-symbol list is what makes this log H9-compliant.
    Pre-PR, exclusion was unobservable. The selection log MUST
    capture exclusion, not just inclusion."""

    def test_dropped_symbols_are_the_universe_tail(self):
        svc, _, log_insert = _build_service(_fixture_rows())
        svc.get_scan_candidates(limit=3, caller="test.suite")
        payload = log_insert.insert.call_args[0][0]
        # AAPL/MSFT/SBUX in; QQQ/DIA out — matches the
        # liquidity_score-sorted tail.
        self.assertEqual(
            payload["selected_symbols"],
            ["AAPL", "MSFT", "SBUX"],
        )
        self.assertEqual(
            payload["dropped_symbols"],
            ["QQQ", "DIA"],
        )

    def test_dropped_list_empty_when_limit_exceeds_universe(self):
        """When limit >= total_active (the iv_daily_refresh
        limit=200 case), no symbols are dropped and the dropped
        list is empty. score_at_cutoff is None in this case."""
        svc, _, log_insert = _build_service(_fixture_rows())
        svc.get_scan_candidates(limit=200, caller="test.suite")
        payload = log_insert.insert.call_args[0][0]
        self.assertEqual(payload["selected_count"], 5)
        self.assertEqual(payload["dropped_count"], 0)
        self.assertEqual(payload["dropped_symbols"], [])
        self.assertIsNone(payload["score_at_cutoff"])
        self.assertEqual(payload["score_threshold"], 50)

    def test_fallback_path_still_writes_a_log_row(self):
        """When the scanner_universe query fails AND the function
        falls back to BASE_UNIVERSE, the log row still fires —
        with `fallback_used=True` so the operator can distinguish
        DB-failure cycles from healthy ones."""
        from packages.quantum.services.universe_service import UniverseService

        client = MagicMock()

        scanner_query = MagicMock()
        scanner_query.select.return_value = scanner_query
        scanner_query.eq.return_value = scanner_query
        scanner_query.order.return_value = scanner_query
        scanner_query.execute.side_effect = RuntimeError("simulated DB outage")

        log_insert = MagicMock()
        log_execute = MagicMock()
        log_execute.execute.return_value = MagicMock(data=[{"id": "log-row-fb"}])
        log_insert.insert.return_value = log_execute

        client.table.side_effect = lambda name: (
            scanner_query if name == "scanner_universe" else log_insert
        )

        with patch(
            "packages.quantum.services.universe_service.PolygonService"
        ), patch(
            "packages.quantum.services.universe_service.EarningsCalendarService"
        ):
            svc = UniverseService(client)

        result = svc.get_scan_candidates(limit=5, caller="test.fallback")

        # Fallback path returned BASE_UNIVERSE[:5] (or similar),
        # AND the log row fired with fallback_used=True.
        self.assertEqual(len(result), 5)
        payload = log_insert.insert.call_args[0][0]
        self.assertTrue(payload["metadata"]["fallback_used"])
        self.assertIn("RuntimeError", payload["metadata"]["fallback_reason"])


# ─────────────────────────────────────────────────────────────────
# Test 3 — H9 verified-write: failure must alert, not silently swallow
# ─────────────────────────────────────────────────────────────────


class TestUniverseSelectionLogH9Verify(unittest.TestCase):
    """The log writer is itself H9-compliant. If the
    universe_selection_log insert fails, the writer must fire
    `universe_selection_log_write_failed` (severity=warning) so
    silent regression of the observability surface is impossible.

    A naive implementation might `try: insert; except: pass` because
    "observability isn't load-bearing." That pattern is the H9
    Anti-pattern 2 shape this PR's doctrine update generalizes —
    the writer cannot itself be silent-failure-prone."""

    def test_exception_during_insert_fires_alert(self):
        svc, _, _ = _build_service(
            _fixture_rows(),
            insert_raises=RuntimeError("simulated insert failure"),
        )
        capture = _AlertCapture()
        with patch(
            "packages.quantum.services.universe_service.alert", capture
        ):
            # Primary work must still succeed — the caller gets its
            # candidate list back.
            result = svc.get_scan_candidates(limit=3, caller="test.suite")
        self.assertEqual(len(result), 3)
        self.assertEqual(
            len(capture.calls), 1,
            "Exactly one universe_selection_log_write_failed alert "
            "expected on insert failure",
        )

    def test_alert_uses_correct_type_and_severity(self):
        svc, _, _ = _build_service(
            _fixture_rows(),
            insert_raises=RuntimeError("simulated insert failure"),
        )
        capture = _AlertCapture()
        with patch(
            "packages.quantum.services.universe_service.alert", capture
        ):
            svc.get_scan_candidates(limit=3, caller="test.suite")
        call = capture.calls[0]
        self.assertEqual(
            call["alert_type"], "universe_selection_log_write_failed"
        )
        self.assertEqual(call["severity"], "warning")

    def test_silent_rejection_empty_data_response_also_alerts(self):
        """The PostgREST silent-rejection shape (no exception, but
        `res.data` is empty) is the Anti-pattern 2 surface this
        gate guards against. RLS denials and constraint violations
        can produce this — the writer must treat empty data as
        failure and alert."""
        svc, _, _ = _build_service(
            _fixture_rows(),
            insert_response=[],  # PostgREST silent-rejection shape
        )
        capture = _AlertCapture()
        with patch(
            "packages.quantum.services.universe_service.alert", capture
        ):
            result = svc.get_scan_candidates(limit=3, caller="test.suite")
        # Primary work still succeeds:
        self.assertEqual(len(result), 3)
        # H9 alert fired:
        self.assertEqual(
            len(capture.calls), 1,
            "Empty insert response (PostgREST silent rejection) "
            "must produce an alert",
        )

    def test_happy_path_does_not_alert(self):
        svc, _, _ = _build_service(_fixture_rows())
        capture = _AlertCapture()
        with patch(
            "packages.quantum.services.universe_service.alert", capture
        ):
            svc.get_scan_candidates(limit=3, caller="test.suite")
        self.assertEqual(
            len(capture.calls), 0,
            "Happy path must not fire alerts",
        )


if __name__ == "__main__":
    unittest.main()
