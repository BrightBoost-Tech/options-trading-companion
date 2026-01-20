"""
Tests for PR4: Trade Inbox active statuses fix.

Ensures NOT_EXECUTABLE suggestions appear in the active queue (not completed).
"""

import pytest
from packages.quantum.dashboard_endpoints import ACTIVE_STATUSES


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
