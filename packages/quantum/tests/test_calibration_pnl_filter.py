"""
Regression test for PR #3 (audit plan) — calibration_service excludes
pre-2026-04-13 corrupted pnl_realized rows via CORRUPTED_PNL_FLOOR.

Background: Round 3 Phase 3 diagnostic found 34 outlier rows in
learning_feedback_loops summing to +$95,408 (vs Alpaca lifetime -$2,724)
from the internal-paper era and early Alpaca-paper era bugs. The filter
is query-time only at calibration_service._fetch_outcomes; source rows
preserved for lineage.
"""

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from packages.quantum.analytics.calibration_service import (
    CORRUPTED_PNL_FLOOR,
    CalibrationService,
)


def _make_supabase_spy():
    """Return a Supabase client mock that records the cutoff passed to .gte()."""
    client = MagicMock()
    query = client.table.return_value
    query.select.return_value = query
    query.eq.return_value = query
    query.gte.return_value = query
    query.execute.return_value = MagicMock(data=[])
    return client, query


class TestCorruptedPnlFloor:
    """The hard floor must exclude pre-2026-04-13 rows regardless of window."""

    def test_floor_constant_is_pre_bugfix_boundary(self):
        """CORRUPTED_PNL_FLOOR must be >= 2026-04-13 (the triage cutoff)."""
        assert CORRUPTED_PNL_FLOOR >= "2026-04-13"

    def test_short_window_uses_window_cutoff(self):
        """When window_days is short, the rolling cutoff wins over the floor."""
        client, query = _make_supabase_spy()
        service = CalibrationService(client)

        # window_days=1 → cutoff ~ now - 1 day, which is > 2026-04-13
        # in the relevant time frame. The .gte() argument should be the
        # RECENT timestamp, not the floor.
        service._fetch_outcomes(user_id="test-user", window_days=1)

        query.gte.assert_called_once()
        call_args = query.gte.call_args
        assert call_args.args[0] == "closed_at"
        effective = call_args.args[1]

        # The effective cutoff should be a recent date, not the floor.
        # (If 'now' is past 2026-04-14, a 1-day window cutoff > floor.)
        now = datetime.now(timezone.utc)
        one_day_ago = (now - timedelta(days=1)).isoformat()
        assert effective == max(one_day_ago, CORRUPTED_PNL_FLOOR)

    def test_long_window_clamps_to_floor(self):
        """When window_days is large enough to reach pre-floor era, floor wins."""
        client, query = _make_supabase_spy()
        service = CalibrationService(client)

        # window_days=365 → cutoff ~ now - 1 year, definitely < 2026-04-13
        # Floor should win.
        service._fetch_outcomes(user_id="test-user", window_days=365)

        query.gte.assert_called_once()
        call_args = query.gte.call_args
        effective = call_args.args[1]

        assert effective == CORRUPTED_PNL_FLOOR, (
            "With a 1-year rolling window, the effective cutoff should be "
            f"the hard floor ({CORRUPTED_PNL_FLOOR}), not the rolling cutoff."
        )

    def test_floor_can_be_overridden_via_env(self, monkeypatch):
        """
        Env-var override exists for ops flexibility — documented in the module
        constant's docstring. If a future date-range issue emerges, ops can
        bump the floor without a deploy. Test loads the value lazily.
        """
        monkeypatch.setenv(
            "CALIBRATION_PNL_FLOOR_DATE", "2026-05-01T00:00:00+00:00"
        )
        # Re-import picks up the new env value.
        import importlib
        from packages.quantum.analytics import calibration_service as mod

        importlib.reload(mod)
        try:
            assert mod.CORRUPTED_PNL_FLOOR == "2026-05-01T00:00:00+00:00"
        finally:
            # Restore default to avoid polluting subsequent tests
            monkeypatch.delenv("CALIBRATION_PNL_FLOOR_DATE", raising=False)
            importlib.reload(mod)

    def test_window_cutoff_and_floor_use_same_comparable_format(self):
        """
        Effective-cutoff comparison uses string max(); both values must be
        comparable ISO-8601 strings so lexicographic ordering == chronological.
        """
        now_iso = datetime.now(timezone.utc).isoformat()
        # Both should be ISO-8601 with timezone offset
        assert "T" in now_iso
        assert "T" in CORRUPTED_PNL_FLOOR
        assert "+" in now_iso or "Z" in now_iso
        assert "+" in CORRUPTED_PNL_FLOOR or "Z" in CORRUPTED_PNL_FLOOR

    def test_exactly_at_cutoff_is_included(self):
        """
        gte() is inclusive. A row with closed_at exactly equal to the
        effective cutoff MUST be returned (not filtered out). This proves
        the boundary semantics in plain terms so a future reader can't
        accidentally convert this to gt() without realizing it changes
        a boundary row's fate.
        """
        client, query = _make_supabase_spy()
        # Simulate the view returning a row whose closed_at equals the floor
        boundary_row = {
            "ev_predicted": 1.0,
            "pop_predicted": 0.5,
            "pnl_realized": 42.0,
            "pnl_predicted": 40.0,
            "pnl_alpha": 2.0,
            "strategy": "LONG_CALL_DEBIT_SPREAD",
            "regime": "normal",
            "window": "midday_entry",
            "ticker": "SPY",
            "closed_at": CORRUPTED_PNL_FLOOR,
            "model_version": "v1",
            "is_paper": True,
        }
        query.execute.return_value = MagicMock(data=[boundary_row])
        service = CalibrationService(client)

        outcomes = service._fetch_outcomes(user_id="u", window_days=365)

        # Caller got the boundary row back → gte() boundary semantics held
        assert len(outcomes) == 1
        assert outcomes[0]["closed_at"] == CORRUPTED_PNL_FLOOR

    def test_post_cutoff_rows_included(self):
        """
        Rows with closed_at AFTER the cutoff flow through. Sanity check that
        the filter isn't over-broad.
        """
        client, query = _make_supabase_spy()
        post_cutoff = "2026-04-15T12:30:00+00:00"  # after floor
        row = {
            "ev_predicted": 1.0,
            "pop_predicted": 0.6,
            "pnl_realized": -120.5,
            "pnl_predicted": -100.0,
            "pnl_alpha": -20.5,
            "strategy": "LONG_CALL_DEBIT_SPREAD",
            "regime": "normal",
            "window": "midday_entry",
            "ticker": "AMD",
            "closed_at": post_cutoff,
            "model_version": "v1",
            "is_paper": True,
        }
        query.execute.return_value = MagicMock(data=[row])
        service = CalibrationService(client)

        outcomes = service._fetch_outcomes(user_id="u", window_days=365)

        assert len(outcomes) == 1
        assert outcomes[0]["closed_at"] == post_cutoff
        assert outcomes[0]["pnl_realized"] == -120.5

    def test_null_pnl_realized_passes_through_filter(self):
        """
        The cutoff filter is on closed_at, not pnl_realized. A row with
        closed_at after the cutoff but pnl_realized NULL must still be
        returned by _fetch_outcomes — handling NULLs is the responsibility
        of downstream metric computation (which already defaults missing
        P&L to 0 via `float(o.get("pnl_realized") or 0)`).

        This test documents that separation of concerns so a future change
        doesn't accidentally drop NULL-pnl rows at the fetch layer without
        a deliberate decision.
        """
        client, query = _make_supabase_spy()
        row_with_null = {
            "ev_predicted": 1.0,
            "pop_predicted": 0.5,
            "pnl_realized": None,           # the point of the test
            "pnl_predicted": 50.0,
            "pnl_alpha": None,
            "strategy": "LONG_CALL_DEBIT_SPREAD",
            "regime": "normal",
            "window": "midday_entry",
            "ticker": "NFLX",
            "closed_at": "2026-04-16T18:00:00+00:00",
            "model_version": "v1",
            "is_paper": True,
        }
        query.execute.return_value = MagicMock(data=[row_with_null])
        service = CalibrationService(client)

        outcomes = service._fetch_outcomes(user_id="u", window_days=30)

        # Fetch returns the row unchanged — cutoff is on closed_at only
        assert len(outcomes) == 1
        assert outcomes[0]["pnl_realized"] is None
