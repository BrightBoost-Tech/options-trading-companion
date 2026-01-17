"""
Tests for scripts/run_signed_task.py

Tests:
- Time gate logic (DST-aware Chicago time)
- Dry run mode
- Environment variable handling
- Task validation
"""

import os
import sys
from datetime import datetime
from unittest.mock import patch, MagicMock
from zoneinfo import ZoneInfo

import pytest

# Add scripts to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "scripts"))

from run_signed_task import (
    TASKS,
    CHICAGO_TZ,
    is_market_day,
    is_within_time_window,
    check_time_gate,
    get_signing_secret,
    build_payload,
    run_task,
)


# =============================================================================
# Time Gate Tests
# =============================================================================

class TestIsMarketDay:
    """Test market day detection."""

    def test_monday_is_market_day(self):
        """Monday should be a market day."""
        # Monday = weekday 0
        mock_now = datetime(2025, 1, 13, 10, 0, tzinfo=CHICAGO_TZ)  # Monday
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            assert is_market_day() is True

    def test_friday_is_market_day(self):
        """Friday should be a market day."""
        mock_now = datetime(2025, 1, 17, 10, 0, tzinfo=CHICAGO_TZ)  # Friday
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            assert is_market_day() is True

    def test_saturday_is_not_market_day(self):
        """Saturday should not be a market day."""
        mock_now = datetime(2025, 1, 18, 10, 0, tzinfo=CHICAGO_TZ)  # Saturday
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            assert is_market_day() is False

    def test_sunday_is_not_market_day(self):
        """Sunday should not be a market day."""
        mock_now = datetime(2025, 1, 19, 10, 0, tzinfo=CHICAGO_TZ)  # Sunday
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            assert is_market_day() is False


class TestIsWithinTimeWindow:
    """Test time window detection."""

    def test_exactly_at_target_time(self):
        """Should return True when exactly at target time."""
        mock_now = datetime(2025, 1, 13, 8, 0, tzinfo=CHICAGO_TZ)
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            assert is_within_time_window(8, 0, window_minutes=30) is True

    def test_within_window(self):
        """Should return True when within window."""
        mock_now = datetime(2025, 1, 13, 8, 15, tzinfo=CHICAGO_TZ)
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            assert is_within_time_window(8, 0, window_minutes=30) is True

    def test_at_window_edge(self):
        """Should return True at 29 minutes after target."""
        mock_now = datetime(2025, 1, 13, 8, 29, tzinfo=CHICAGO_TZ)
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            assert is_within_time_window(8, 0, window_minutes=30) is True

    def test_past_window(self):
        """Should return False when past window."""
        mock_now = datetime(2025, 1, 13, 8, 30, tzinfo=CHICAGO_TZ)
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            assert is_within_time_window(8, 0, window_minutes=30) is False

    def test_before_target(self):
        """Should return False when before target time."""
        mock_now = datetime(2025, 1, 13, 7, 59, tzinfo=CHICAGO_TZ)
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            assert is_within_time_window(8, 0, window_minutes=30) is False

    def test_with_non_zero_target_minute(self):
        """Should handle target times with non-zero minutes."""
        mock_now = datetime(2025, 1, 13, 16, 15, tzinfo=CHICAGO_TZ)
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            # 4:10 PM target
            assert is_within_time_window(16, 10, window_minutes=30) is True


class TestCheckTimeGate:
    """Test the full time gate logic."""

    def test_skip_time_gate_flag(self):
        """Should return True when skip_time_gate is True."""
        assert check_time_gate("suggestions_close", skip_time_gate=True) is True

    def test_ungated_task(self):
        """Tasks without time gates should always pass."""
        assert check_time_gate("universe_sync", skip_time_gate=False) is True
        assert check_time_gate("morning_brief", skip_time_gate=False) is True

    def test_gated_task_on_weekend(self, capsys):
        """Gated tasks should fail on weekends."""
        mock_now = datetime(2025, 1, 18, 8, 0, tzinfo=CHICAGO_TZ)  # Saturday
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            assert check_time_gate("suggestions_close", skip_time_gate=False) is False
            captured = capsys.readouterr()
            assert "not a market day" in captured.out

    def test_gated_task_outside_window(self, capsys):
        """Gated tasks should fail outside time window."""
        mock_now = datetime(2025, 1, 13, 10, 0, tzinfo=CHICAGO_TZ)  # Monday 10 AM
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            assert check_time_gate("suggestions_close", skip_time_gate=False) is False
            captured = capsys.readouterr()
            assert "not within" in captured.out

    def test_gated_task_within_window(self):
        """Gated tasks should pass within time window."""
        mock_now = datetime(2025, 1, 13, 8, 5, tzinfo=CHICAGO_TZ)  # Monday 8:05 AM
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            with patch("run_signed_task.is_market_day", return_value=True):
                with patch("run_signed_task.is_within_time_window", return_value=True):
                    assert check_time_gate("suggestions_close", skip_time_gate=False) is True


# =============================================================================
# Signing Secret Tests
# =============================================================================

class TestGetSigningSecret:
    """Test signing secret retrieval."""

    def test_single_secret(self):
        """Should use TASK_SIGNING_SECRET."""
        with patch.dict(os.environ, {"TASK_SIGNING_SECRET": "test-secret"}, clear=True):
            secret, key_id = get_signing_secret()
            assert secret == "test-secret"
            assert key_id is None

    def test_multi_key_format(self):
        """Should parse TASK_SIGNING_KEYS format."""
        with patch.dict(os.environ, {"TASK_SIGNING_KEYS": "primary:secret1,secondary:secret2"}, clear=True):
            secret, key_id = get_signing_secret()
            assert secret == "secret1"
            assert key_id == "primary"

    def test_multi_key_with_whitespace(self):
        """Should handle whitespace in multi-key format."""
        with patch.dict(os.environ, {"TASK_SIGNING_KEYS": " primary : secret1 , secondary : secret2 "}, clear=True):
            secret, key_id = get_signing_secret()
            assert secret == "secret1"
            assert key_id == "primary"

    def test_no_secret_raises(self):
        """Should raise if no secret is configured."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError) as exc_info:
                get_signing_secret()
            assert "No signing secret configured" in str(exc_info.value)

    def test_multi_key_takes_precedence(self):
        """TASK_SIGNING_KEYS should take precedence over TASK_SIGNING_SECRET."""
        with patch.dict(os.environ, {
            "TASK_SIGNING_KEYS": "primary:multi-secret",
            "TASK_SIGNING_SECRET": "single-secret"
        }, clear=True):
            secret, key_id = get_signing_secret()
            assert secret == "multi-secret"
            assert key_id == "primary"


# =============================================================================
# Payload Tests
# =============================================================================

class TestBuildPayload:
    """Test payload construction."""

    def test_empty_payload(self):
        """Should return empty dict for tasks without config."""
        payload = build_payload("universe_sync")
        assert payload == {}

    def test_user_id_added(self):
        """Should add user_id when provided."""
        payload = build_payload("universe_sync", user_id="test-user-123")
        assert payload == {"user_id": "test-user-123"}

    def test_suggestions_defaults(self):
        """Suggestions tasks should include default strategy_name."""
        payload = build_payload("suggestions_close")
        assert "strategy_name" in payload
        assert payload["strategy_name"] == "spy_opt_autolearn_v6"

    def test_suggestions_with_user_id(self):
        """Suggestions tasks should include both strategy and user_id."""
        payload = build_payload("suggestions_open", user_id="user-456")
        assert payload["user_id"] == "user-456"
        assert payload["strategy_name"] == "spy_opt_autolearn_v6"


# =============================================================================
# Task Definition Tests
# =============================================================================

class TestTaskDefinitions:
    """Test task definitions are complete."""

    def test_all_tasks_have_path(self):
        """Every task should have a path."""
        for name, task in TASKS.items():
            assert "path" in task, f"Task {name} missing 'path'"
            assert task["path"].startswith("/tasks/"), f"Task {name} path should start with /tasks/"

    def test_all_tasks_have_scope(self):
        """Every task should have a scope."""
        for name, task in TASKS.items():
            assert "scope" in task, f"Task {name} missing 'scope'"
            assert task["scope"].startswith("tasks:"), f"Task {name} scope should start with tasks:"

    def test_all_tasks_have_description(self):
        """Every task should have a description."""
        for name, task in TASKS.items():
            assert "description" in task, f"Task {name} missing 'description'"
            assert len(task["description"]) > 5, f"Task {name} has too short description"

    def test_expected_tasks_exist(self):
        """All expected tasks should be defined."""
        expected = [
            "suggestions_close",
            "suggestions_open",
            "learning_ingest",
            "universe_sync",
            "morning_brief",
            "midday_scan",
            "weekly_report",
            "validation_eval",
            "strategy_autotune",
        ]
        for task_name in expected:
            assert task_name in TASKS, f"Missing expected task: {task_name}"


# =============================================================================
# Dry Run Tests
# =============================================================================

class TestDryRun:
    """Test dry run mode."""

    def test_dry_run_does_not_send_request(self, capsys):
        """Dry run should not actually send the request."""
        with patch.dict(os.environ, {
            "TASK_SIGNING_SECRET": "test-secret",
            "BASE_URL": "https://api.example.com",
        }):
            with patch("run_signed_task.check_time_gate", return_value=True):
                # Patch requests.post to verify it's not called
                with patch("run_signed_task.requests.post") as mock_post:
                    result = run_task(
                        task_name="universe_sync",
                        dry_run=True,
                        skip_time_gate=True
                    )
                    assert result == 0
                    mock_post.assert_not_called()

                    captured = capsys.readouterr()
                    assert "[DRY-RUN]" in captured.out

    def test_dry_run_logs_request_details(self, capsys):
        """Dry run should log request details."""
        with patch.dict(os.environ, {
            "TASK_SIGNING_SECRET": "test-secret",
            "BASE_URL": "https://api.example.com",
        }):
            with patch("run_signed_task.check_time_gate", return_value=True):
                run_task(
                    task_name="suggestions_open",
                    user_id="test-user",
                    dry_run=True,
                    skip_time_gate=True
                )
                captured = capsys.readouterr()

                assert "POST" in captured.out
                assert "/tasks/suggestions/open" in captured.out
                assert "tasks:suggestions_open" in captured.out
                assert "X-Task-Ts" in captured.out


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestErrorHandling:
    """Test error handling."""

    def test_unknown_task_fails(self):
        """Unknown task name should return error."""
        result = run_task(task_name="nonexistent_task", skip_time_gate=True)
        assert result == 1

    def test_missing_base_url_fails(self, capsys):
        """Missing BASE_URL should return error."""
        with patch.dict(os.environ, {"TASK_SIGNING_SECRET": "test-secret"}, clear=True):
            # Remove BASE_URL
            os.environ.pop("BASE_URL", None)
            result = run_task(task_name="universe_sync", skip_time_gate=True)
            assert result == 1
            captured = capsys.readouterr()
            assert "BASE_URL" in captured.out

    def test_missing_secret_fails(self, capsys):
        """Missing signing secret should return error."""
        with patch.dict(os.environ, {"BASE_URL": "https://api.example.com"}, clear=True):
            result = run_task(task_name="universe_sync", skip_time_gate=True)
            assert result == 1
            captured = capsys.readouterr()
            assert "No signing secret" in captured.out
