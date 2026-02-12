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
    VERBOSE_RESPONSE_TASKS,
    is_market_day,
    is_within_time_window,
    check_time_gate,
    get_signing_secret,
    build_payload,
    run_task,
    _should_print_response_json,
    _redact_sensitive_fields,
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

    # === payload_json tests ===

    def test_payload_json_empty_string_no_error(self):
        """Empty string payload_json should not error, just skip parsing."""
        payload = build_payload("suggestions_open", payload_json="")
        assert payload == {"strategy_name": "spy_opt_autolearn_v6"}

    def test_payload_json_whitespace_only_no_error(self):
        """Whitespace-only payload_json should not error, just skip parsing."""
        payload = build_payload("suggestions_open", payload_json="   \n\t  ")
        assert payload == {"strategy_name": "spy_opt_autolearn_v6"}

    def test_payload_json_none_no_error(self):
        """None payload_json should not error."""
        payload = build_payload("suggestions_open", payload_json=None)
        assert payload == {"strategy_name": "spy_opt_autolearn_v6"}

    def test_payload_json_empty_object_valid(self):
        """Empty JSON object {} should be valid and merge nothing."""
        payload = build_payload("suggestions_open", payload_json="{}")
        assert payload == {"strategy_name": "spy_opt_autolearn_v6"}

    def test_payload_json_valid_merges(self):
        """Valid JSON should merge into payload."""
        payload = build_payload(
            "suggestions_open",
            user_id="user-123",
            payload_json='{"skip_sync": true, "custom_key": "value"}'
        )
        assert payload["strategy_name"] == "spy_opt_autolearn_v6"
        assert payload["user_id"] == "user-123"
        assert payload["skip_sync"] is True
        assert payload["custom_key"] == "value"

    def test_payload_json_overrides_user_id(self):
        """payload_json should override user_id from CLI."""
        payload = build_payload(
            "suggestions_open",
            user_id="cli-user",
            payload_json='{"user_id": "json-user"}'
        )
        assert payload["user_id"] == "json-user"

    def test_payload_json_invalid_raises_error(self):
        """Invalid JSON should raise ValueError with clear message."""
        with pytest.raises(ValueError) as exc_info:
            build_payload("suggestions_open", payload_json="{")
        assert "Invalid JSON in payload_json" in str(exc_info.value)

    def test_payload_json_non_object_raises_error(self):
        """Non-object JSON should raise ValueError."""
        with pytest.raises(ValueError) as exc_info:
            build_payload("suggestions_open", payload_json='["array"]')
        assert "must be a JSON object" in str(exc_info.value)

    # === skip_sync tests ===

    def test_skip_sync_flag_adds_to_payload(self):
        """skip_sync=True should add skip_sync to payload."""
        payload = build_payload("suggestions_open", skip_sync=True)
        assert payload["skip_sync"] is True

    def test_skip_sync_false_not_added(self):
        """skip_sync=False should not add skip_sync to payload."""
        payload = build_payload("suggestions_open", skip_sync=False)
        assert "skip_sync" not in payload

    def test_skip_sync_and_payload_json_both_work(self):
        """skip_sync flag and payload_json can both be provided."""
        payload = build_payload(
            "suggestions_open",
            skip_sync=True,
            payload_json='{"custom": "value"}'
        )
        assert payload["skip_sync"] is True
        assert payload["custom"] == "value"

    def test_payload_json_overrides_skip_sync_flag(self):
        """payload_json skip_sync should override --skip-sync flag."""
        payload = build_payload(
            "suggestions_open",
            skip_sync=True,
            payload_json='{"skip_sync": false}'
        )
        # payload_json takes precedence
        assert payload["skip_sync"] is False

    # === force_rerun tests ===

    def test_force_rerun_flag_adds_to_payload(self):
        """force_rerun=True should add force_rerun to payload."""
        payload = build_payload("suggestions_open", force_rerun=True)
        assert payload["force_rerun"] is True

    def test_force_rerun_false_not_added(self):
        """force_rerun=False should not add force_rerun to payload."""
        payload = build_payload("suggestions_open", force_rerun=False)
        assert "force_rerun" not in payload

    def test_force_rerun_and_skip_sync_both_work(self):
        """force_rerun and skip_sync flags can both be provided."""
        payload = build_payload(
            "suggestions_open",
            skip_sync=True,
            force_rerun=True
        )
        assert payload["skip_sync"] is True
        assert payload["force_rerun"] is True

    def test_payload_json_overrides_force_rerun_flag(self):
        """payload_json force_rerun should override --force-rerun flag."""
        payload = build_payload(
            "suggestions_open",
            force_rerun=True,
            payload_json='{"force_rerun": false}'
        )
        # payload_json takes precedence
        assert payload["force_rerun"] is False

    def test_all_flags_together(self):
        """All CLI flags should work together with correct priority."""
        payload = build_payload(
            "suggestions_open",
            user_id="cli-user",
            skip_sync=True,
            force_rerun=True,
            payload_json='{"custom_key": "value"}'
        )
        assert payload["strategy_name"] == "spy_opt_autolearn_v6"
        assert payload["user_id"] == "cli-user"
        assert payload["skip_sync"] is True
        assert payload["force_rerun"] is True
        assert payload["custom_key"] == "value"


# =============================================================================
# Task Definition Tests
# =============================================================================

class TestTaskDefinitions:
    """Test task definitions are complete."""

    def test_all_tasks_have_path(self):
        """Every task should have a path."""
        for name, task in TASKS.items():
            assert "path" in task, f"Task {name} missing 'path'"
            # Allow both public (/tasks/) and internal (/internal/tasks/) paths
            assert task["path"].startswith("/tasks/") or task["path"].startswith("/internal/tasks/"), \
                f"Task {name} path should start with /tasks/ or /internal/tasks/"

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
            "plaid_backfill",
            "iv_daily_refresh",
            "learning_train",
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


# =============================================================================
# Verbose Response Tests
# =============================================================================


class TestVerboseResponseTasks:
    """Tests for verbose response JSON printing."""

    def test_verbose_tasks_constant_contains_paper_tasks(self):
        """VERBOSE_RESPONSE_TASKS should contain all paper pipeline tasks."""
        expected_tasks = {
            "paper_process_orders",
            "paper_auto_execute",
            "paper_auto_close",
            "paper_safety_close_one",
        }
        assert expected_tasks == VERBOSE_RESPONSE_TASKS

    def test_should_print_for_paper_process_orders(self):
        """Should return True for paper_process_orders task."""
        with patch.dict(os.environ, {}, clear=True):
            assert _should_print_response_json("paper_process_orders") is True

    def test_should_print_for_paper_auto_execute(self):
        """Should return True for paper_auto_execute task."""
        with patch.dict(os.environ, {}, clear=True):
            assert _should_print_response_json("paper_auto_execute") is True

    def test_should_print_for_paper_auto_close(self):
        """Should return True for paper_auto_close task."""
        with patch.dict(os.environ, {}, clear=True):
            assert _should_print_response_json("paper_auto_close") is True

    def test_should_print_for_paper_safety_close_one(self):
        """Should return True for paper_safety_close_one task."""
        with patch.dict(os.environ, {}, clear=True):
            assert _should_print_response_json("paper_safety_close_one") is True

    def test_should_not_print_for_suggestions_open(self):
        """Should return False for suggestions_open (not a verbose task)."""
        with patch.dict(os.environ, {}, clear=True):
            assert _should_print_response_json("suggestions_open") is False

    def test_should_not_print_for_universe_sync(self):
        """Should return False for universe_sync (not a verbose task)."""
        with patch.dict(os.environ, {}, clear=True):
            assert _should_print_response_json("universe_sync") is False

    def test_env_var_overrides_for_any_task(self):
        """PRINT_RESPONSE_JSON=1 should enable for any task."""
        with patch.dict(os.environ, {"PRINT_RESPONSE_JSON": "1"}):
            assert _should_print_response_json("suggestions_open") is True
            assert _should_print_response_json("universe_sync") is True

    def test_env_var_true_string(self):
        """PRINT_RESPONSE_JSON=true should also work."""
        with patch.dict(os.environ, {"PRINT_RESPONSE_JSON": "true"}):
            assert _should_print_response_json("universe_sync") is True

    def test_env_var_yes_string(self):
        """PRINT_RESPONSE_JSON=yes should also work."""
        with patch.dict(os.environ, {"PRINT_RESPONSE_JSON": "yes"}):
            assert _should_print_response_json("universe_sync") is True


class TestRedactSensitiveFields:
    """Tests for sensitive field redaction."""

    def test_redacts_secret_field(self):
        """Should redact 'secret' field."""
        data = {"status": "ok", "secret": "hunter2"}
        result = _redact_sensitive_fields(data)
        assert result["secret"] == "[REDACTED]"
        assert result["status"] == "ok"

    def test_redacts_password_field(self):
        """Should redact 'password' field."""
        data = {"user": "admin", "password": "hunter2"}
        result = _redact_sensitive_fields(data)
        assert result["password"] == "[REDACTED]"
        assert result["user"] == "admin"

    def test_redacts_api_key_field(self):
        """Should redact 'api_key' field."""
        data = {"api_key": "sk-12345"}
        result = _redact_sensitive_fields(data)
        assert result["api_key"] == "[REDACTED]"

    def test_redacts_nested_fields(self):
        """Should redact sensitive fields in nested dicts."""
        data = {
            "outer": {
                "token": "secret-token",
                "safe_field": "visible"
            }
        }
        result = _redact_sensitive_fields(data)
        assert result["outer"]["token"] == "[REDACTED]"
        assert result["outer"]["safe_field"] == "visible"

    def test_redacts_in_list_of_dicts(self):
        """Should redact sensitive fields in list of dicts."""
        data = {
            "items": [
                {"name": "item1", "credential": "secret1"},
                {"name": "item2", "credential": "secret2"}
            ]
        }
        result = _redact_sensitive_fields(data)
        assert result["items"][0]["credential"] == "[REDACTED]"
        assert result["items"][1]["credential"] == "[REDACTED]"
        assert result["items"][0]["name"] == "item1"

    def test_preserves_normal_response(self):
        """Should preserve normal response without sensitive fields."""
        data = {
            "status": "ok",
            "processed": 3,
            "errors": None,
            "processed_summary": {
                "total_processed": 3,
                "processing_error_count": 0
            }
        }
        result = _redact_sensitive_fields(data)
        assert result == data

    def test_handles_non_dict_input(self):
        """Should return non-dict input unchanged."""
        assert _redact_sensitive_fields("string") == "string"
        assert _redact_sensitive_fields(123) == 123
        assert _redact_sensitive_fields(None) is None
