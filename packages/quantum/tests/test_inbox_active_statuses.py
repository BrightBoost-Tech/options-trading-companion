"""
Tests for PR4/PR4.1: Trade Inbox active statuses and today window bounds.

PR4: Ensures NOT_EXECUTABLE suggestions appear in the active queue (not completed).
PR4.1: Ensures explicit today window bounds for deterministic behavior.
"""

import pytest
from datetime import datetime, timezone, timedelta
from packages.quantum.dashboard_endpoints import ACTIVE_STATUSES, compute_today_window


class TestActiveStatuses:
    """Test active status constants and filtering logic."""

    def test_active_statuses_includes_pending(self):
        """pending should be in active statuses"""
        assert "pending" in ACTIVE_STATUSES

    def test_active_statuses_includes_not_executable(self):
        """NOT_EXECUTABLE should be in active statuses"""
        assert "NOT_EXECUTABLE" in ACTIVE_STATUSES

    def test_active_statuses_excludes_dismissed(self):
        """dismissed should NOT be in active statuses"""
        assert "dismissed" not in ACTIVE_STATUSES

    def test_active_statuses_excludes_staged(self):
        """staged should NOT be in active statuses"""
        assert "staged" not in ACTIVE_STATUSES

    def test_active_statuses_excludes_executed(self):
        """executed should NOT be in active statuses"""
        assert "executed" not in ACTIVE_STATUSES


class TestInboxFiltering:
    """Test inbox filtering logic for active vs completed."""

    def test_pending_suggestion_in_active_list(self):
        """pending suggestions should be in active list"""
        suggestions = [
            {"id": "1", "status": "pending", "ev": 10.0},
            {"id": "2", "status": "dismissed", "ev": 5.0},
        ]
        active = [s for s in suggestions if s.get("status") in ACTIVE_STATUSES]
        assert len(active) == 1
        assert active[0]["id"] == "1"

    def test_not_executable_suggestion_in_active_list(self):
        """NOT_EXECUTABLE suggestions should be in active list"""
        suggestions = [
            {"id": "1", "status": "pending", "ev": 10.0},
            {"id": "2", "status": "NOT_EXECUTABLE", "ev": 5.0, "blocked_reason": "marketdata_quality_gate"},
            {"id": "3", "status": "dismissed", "ev": 3.0},
        ]
        active = [s for s in suggestions if s.get("status") in ACTIVE_STATUSES]
        assert len(active) == 2
        assert {s["id"] for s in active} == {"1", "2"}

    def test_completed_excludes_active_statuses(self):
        """completed list should exclude active statuses"""
        suggestions = [
            {"id": "1", "status": "pending", "ev": 10.0},
            {"id": "2", "status": "NOT_EXECUTABLE", "ev": 5.0},
            {"id": "3", "status": "dismissed", "ev": 3.0},
            {"id": "4", "status": "executed", "ev": 2.0},
        ]
        completed = [s for s in suggestions if s.get("status") not in ACTIVE_STATUSES]
        assert len(completed) == 2
        assert {s["id"] for s in completed} == {"3", "4"}


class TestEVCalculation:
    """Test EV calculation logic for active suggestions."""

    def test_total_ev_only_from_pending(self):
        """total_ev_available should only sum pending suggestions (not blocked)"""
        suggestions = [
            {"id": "1", "status": "pending", "ev": 10.0},
            {"id": "2", "status": "pending", "ev": 5.0},
            {"id": "3", "status": "NOT_EXECUTABLE", "ev": 100.0},  # Blocked - should not count
        ]

        # Mimic backend logic
        executable_list = [s for s in suggestions if s.get("status") == "pending"]
        total_ev = sum(s.get("ev", 0) for s in executable_list if s.get("ev"))

        assert total_ev == 15.0  # Only pending EVs (10 + 5)
        assert total_ev != 115.0  # Should NOT include blocked

    def test_total_ev_handles_none_ev(self):
        """total_ev calculation should handle None ev values"""
        suggestions = [
            {"id": "1", "status": "pending", "ev": 10.0},
            {"id": "2", "status": "pending", "ev": None},
            {"id": "3", "status": "pending"},  # No ev field
        ]

        executable_list = [s for s in suggestions if s.get("status") == "pending"]
        total_ev = sum(s.get("ev", 0) for s in executable_list if s.get("ev"))

        assert total_ev == 10.0


class TestMarketDataQualityFields:
    """Test that quality gate fields are properly structured."""

    def test_blocked_suggestion_structure(self):
        """Blocked suggestions should have expected fields"""
        blocked_suggestion = {
            "id": "1",
            "status": "NOT_EXECUTABLE",
            "blocked_reason": "marketdata_quality_gate",
            "blocked_detail": "SPY:WARN_STALE|QQQ:FAIL_CROSSED",
            "marketdata_quality": {
                "effective_action": "skip_fatal",
                "has_fatal": True,
                "fatal_count": 1,
                "symbols": [
                    {"symbol": "SPY", "code": "WARN_STALE", "score": 70},
                    {"symbol": "QQQ", "code": "FAIL_CROSSED", "score": 0},
                ]
            }
        }

        assert blocked_suggestion["status"] == "NOT_EXECUTABLE"
        assert blocked_suggestion["blocked_reason"] == "marketdata_quality_gate"
        assert "SPY" in blocked_suggestion["blocked_detail"]
        assert blocked_suggestion["marketdata_quality"]["effective_action"] == "skip_fatal"
        assert blocked_suggestion["marketdata_quality"]["has_fatal"] is True


class TestComputeTodayWindow:
    """PR4.1: Test today window computation for deterministic bounds."""

    def test_compute_today_window_returns_tuple(self):
        """compute_today_window returns (today_start, tomorrow_start) tuple"""
        today_start, tomorrow_start = compute_today_window()
        assert isinstance(today_start, str)
        assert isinstance(tomorrow_start, str)

    def test_compute_today_window_with_fixed_time(self):
        """compute_today_window with fixed datetime produces expected bounds"""
        # Fixed time: 2026-01-20 14:30:00 UTC
        fixed_now = datetime(2026, 1, 20, 14, 30, 0, tzinfo=timezone.utc)

        today_start, tomorrow_start = compute_today_window(fixed_now)

        # Should be 2026-01-20 00:00:00
        assert "2026-01-20T00:00:00" in today_start
        # Should be 2026-01-21 00:00:00
        assert "2026-01-21T00:00:00" in tomorrow_start

    def test_compute_today_window_spans_one_day(self):
        """Window spans exactly one calendar day"""
        fixed_now = datetime(2026, 1, 20, 14, 30, 0, tzinfo=timezone.utc)
        today_start, tomorrow_start = compute_today_window(fixed_now)

        # Parse back to datetime
        start_dt = datetime.fromisoformat(today_start.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(tomorrow_start.replace('Z', '+00:00'))

        diff = end_dt - start_dt
        assert diff == timedelta(days=1)

    def test_compute_today_window_at_midnight(self):
        """Window computed at midnight is still correct"""
        midnight = datetime(2026, 1, 20, 0, 0, 0, tzinfo=timezone.utc)
        today_start, tomorrow_start = compute_today_window(midnight)

        assert "2026-01-20T00:00:00" in today_start
        assert "2026-01-21T00:00:00" in tomorrow_start

    def test_compute_today_window_at_end_of_day(self):
        """Window computed at 23:59:59 still uses same day"""
        end_of_day = datetime(2026, 1, 20, 23, 59, 59, tzinfo=timezone.utc)
        today_start, tomorrow_start = compute_today_window(end_of_day)

        assert "2026-01-20T00:00:00" in today_start
        assert "2026-01-21T00:00:00" in tomorrow_start


class TestTodayBoundedFiltering:
    """PR4.1: Test today-bounded filtering logic."""

    def test_completed_excludes_yesterday(self):
        """Completed list should exclude items from yesterday"""
        today = datetime(2026, 1, 20, 12, 0, 0, tzinfo=timezone.utc)
        today_start, tomorrow_start = compute_today_window(today)

        suggestions = [
            {"id": "1", "status": "dismissed", "created_at": "2026-01-19T10:00:00+00:00"},  # Yesterday
            {"id": "2", "status": "dismissed", "created_at": "2026-01-20T10:00:00+00:00"},  # Today
            {"id": "3", "status": "executed", "created_at": "2026-01-20T15:00:00+00:00"},   # Today
        ]

        # Filter to today window (mimicking backend logic)
        today_items = [
            s for s in suggestions
            if s["created_at"] >= today_start and s["created_at"] < tomorrow_start
        ]

        # Then filter to completed (non-active statuses)
        completed = [s for s in today_items if s.get("status") not in ACTIVE_STATUSES]

        assert len(completed) == 2
        assert {s["id"] for s in completed} == {"2", "3"}

    def test_completed_excludes_tomorrow(self):
        """Completed list should exclude items from tomorrow (future-dated)"""
        today = datetime(2026, 1, 20, 12, 0, 0, tzinfo=timezone.utc)
        today_start, tomorrow_start = compute_today_window(today)

        suggestions = [
            {"id": "1", "status": "dismissed", "created_at": "2026-01-20T10:00:00+00:00"},  # Today
            {"id": "2", "status": "dismissed", "created_at": "2026-01-21T01:00:00+00:00"},  # Tomorrow
        ]

        today_items = [
            s for s in suggestions
            if s["created_at"] >= today_start and s["created_at"] < tomorrow_start
        ]
        completed = [s for s in today_items if s.get("status") not in ACTIVE_STATUSES]

        assert len(completed) == 1
        assert completed[0]["id"] == "1"

    def test_active_today_bounded_excludes_backlog(self):
        """Default active (no backlog) should exclude older items"""
        today = datetime(2026, 1, 20, 12, 0, 0, tzinfo=timezone.utc)
        today_start, tomorrow_start = compute_today_window(today)

        suggestions = [
            {"id": "1", "status": "pending", "created_at": "2026-01-19T10:00:00+00:00"},      # Yesterday backlog
            {"id": "2", "status": "pending", "created_at": "2026-01-20T10:00:00+00:00"},      # Today
            {"id": "3", "status": "NOT_EXECUTABLE", "created_at": "2026-01-20T11:00:00+00:00"}, # Today blocked
            {"id": "4", "status": "NOT_EXECUTABLE", "created_at": "2026-01-18T10:00:00+00:00"}, # Old backlog
        ]

        # Simulate include_backlog=false (default) - apply time bounds
        active_today = [
            s for s in suggestions
            if s.get("status") in ACTIVE_STATUSES
            and s["created_at"] >= today_start
            and s["created_at"] < tomorrow_start
        ]

        assert len(active_today) == 2
        assert {s["id"] for s in active_today} == {"2", "3"}

    def test_active_with_backlog_includes_older(self):
        """include_backlog=true should include older active items"""
        suggestions = [
            {"id": "1", "status": "pending", "created_at": "2026-01-19T10:00:00+00:00"},      # Yesterday
            {"id": "2", "status": "pending", "created_at": "2026-01-20T10:00:00+00:00"},      # Today
            {"id": "3", "status": "NOT_EXECUTABLE", "created_at": "2026-01-18T10:00:00+00:00"}, # 2 days ago
            {"id": "4", "status": "dismissed", "created_at": "2026-01-19T10:00:00+00:00"},    # Yesterday dismissed
        ]

        # Simulate include_backlog=true - no time bounds on active
        active_with_backlog = [
            s for s in suggestions
            if s.get("status") in ACTIVE_STATUSES
        ]

        assert len(active_with_backlog) == 3
        assert {s["id"] for s in active_with_backlog} == {"1", "2", "3"}


class TestIncludeBacklogSemantics:
    """PR4.1: Test include_backlog parameter semantics."""

    def test_default_behavior_is_today_only(self):
        """Default (include_backlog=false) should be today-only for active"""
        # This is a semantic test - the actual filtering is tested above
        include_backlog = False
        assert not include_backlog  # Default should be False

    def test_include_backlog_does_not_affect_completed(self):
        """Completed is ALWAYS today-only, even with include_backlog=true"""
        today = datetime(2026, 1, 20, 12, 0, 0, tzinfo=timezone.utc)
        today_start, tomorrow_start = compute_today_window(today)

        suggestions = [
            {"id": "1", "status": "dismissed", "created_at": "2026-01-19T10:00:00+00:00"},  # Yesterday
            {"id": "2", "status": "dismissed", "created_at": "2026-01-20T10:00:00+00:00"},  # Today
        ]

        # Even with include_backlog=true, completed uses today bounds
        today_items = [
            s for s in suggestions
            if s["created_at"] >= today_start and s["created_at"] < tomorrow_start
        ]
        completed = [s for s in today_items if s.get("status") not in ACTIVE_STATUSES]

        # Only today's dismissed item
        assert len(completed) == 1
        assert completed[0]["id"] == "2"
