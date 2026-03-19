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
import unittest
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
    get_current_chicago_offset,
    _is_correct_season_cron,
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
        """Should return None (run) when skip_time_gate is True."""
        assert check_time_gate("suggestions_close", skip_time_gate=True) is None

    def test_ungated_task(self):
        """Tasks without time gates should always pass."""
        assert check_time_gate("universe_sync", skip_time_gate=False) is None
        assert check_time_gate("morning_brief", skip_time_gate=False) is None

    def test_gated_task_on_weekend(self):
        """Gated tasks should fail on weekends."""
        mock_now = datetime(2025, 1, 18, 8, 0, tzinfo=CHICAGO_TZ)  # Saturday
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = check_time_gate("suggestions_close", skip_time_gate=False)
            assert result is not None
            assert "Not a market day" in result

    def test_gated_task_outside_window(self):
        """Gated tasks should fail outside time window."""
        mock_now = datetime(2025, 1, 13, 10, 0, tzinfo=CHICAGO_TZ)  # Monday 10 AM
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = check_time_gate("suggestions_close", skip_time_gate=False)
            assert result is not None
            assert "not within" in result

    def test_gated_task_within_window(self):
        """Gated tasks should pass within time window."""
        mock_now = datetime(2025, 1, 13, 8, 5, tzinfo=CHICAGO_TZ)  # Monday 8:05 AM
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            with patch("run_signed_task.is_market_day", return_value=True):
                with patch("run_signed_task.is_within_time_window", return_value=True):
                    assert check_time_gate("suggestions_close", skip_time_gate=False) is None

    # --- DST dual-cron dedup tests for paper_auto_execute ---

    def test_paper_auto_execute_passes_at_1130_chicago(self):
        """paper_auto_execute should pass at 11:30 AM Chicago (the intended time)."""
        mock_now = datetime(2025, 7, 14, 11, 30, tzinfo=CHICAGO_TZ)  # Monday 11:30 CDT
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            assert check_time_gate("paper_auto_execute", skip_time_gate=False) is None

    def test_paper_auto_execute_blocked_at_1030_chicago(self):
        """CST wrong-offset cron at 10:30 AM Chicago should be rejected."""
        # 16:30 UTC during CST = 10:30 AM Chicago (1 hour too early)
        mock_now = datetime(2025, 1, 13, 10, 30, tzinfo=CHICAGO_TZ)  # Monday 10:30 CST
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = check_time_gate("paper_auto_execute", skip_time_gate=False)
            assert result is not None
            assert "not within" in result

    def test_paper_auto_execute_blocked_at_1230_chicago(self):
        """CDT wrong-offset cron at 12:30 PM Chicago should be rejected."""
        # 17:30 UTC during CDT = 12:30 PM Chicago (1 hour too late)
        mock_now = datetime(2025, 7, 14, 12, 30, tzinfo=CHICAGO_TZ)  # Monday 12:30 CDT
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = check_time_gate("paper_auto_execute", skip_time_gate=False)
            assert result is not None
            assert "not within" in result

    # --- DST dual-cron dedup tests for validation_preflight ---

    def test_validation_preflight_passes_at_1305_chicago(self):
        """validation_preflight should pass at 1:05 PM Chicago (the intended time)."""
        mock_now = datetime(2025, 7, 14, 13, 5, tzinfo=CHICAGO_TZ)  # Monday 1:05 PM CDT
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            assert check_time_gate("validation_preflight", skip_time_gate=False) is None

    def test_validation_preflight_blocked_at_1205_chicago(self):
        """CST wrong-offset cron at 12:05 PM Chicago should be rejected."""
        # 18:05 UTC during CST = 12:05 PM Chicago (1 hour too early)
        mock_now = datetime(2025, 1, 13, 12, 5, tzinfo=CHICAGO_TZ)  # Monday 12:05 CST
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = check_time_gate("validation_preflight", skip_time_gate=False)
            assert result is not None
            assert "not within" in result

    def test_validation_preflight_blocked_at_1405_chicago(self):
        """CDT wrong-offset cron at 2:05 PM Chicago should be rejected."""
        # 19:05 UTC during CDT = 2:05 PM Chicago (1 hour too late)
        mock_now = datetime(2025, 7, 14, 14, 5, tzinfo=CHICAGO_TZ)  # Monday 2:05 PM CDT
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = check_time_gate("validation_preflight", skip_time_gate=False)
            assert result is not None
            assert "not within" in result


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


class TestCorrectSeasonCron(unittest.TestCase):
    """Tests for _is_correct_season_cron — validates triggering cron matches DST season."""

    def test_correct_cdt_cron_accepted(self):
        """During CDT, the CDT-season cron should be accepted."""
        # CDT: 08:00 Chicago = 13:00 UTC, so cron '0 13 * * 1-5' is correct
        with patch("run_signed_task.datetime") as mock_dt, \
             patch.dict(os.environ, {"GITHUB_EVENT_SCHEDULE": "0 13 * * 1-5"}):
            # July = CDT, UTC offset is -5
            mock_dt.now.return_value = datetime(2024, 7, 15, 8, 10, tzinfo=CHICAGO_TZ)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertTrue(_is_correct_season_cron("08:00"))

    def test_wrong_cst_cron_rejected_during_cdt(self):
        """During CDT, the CST-season cron should be rejected."""
        # CDT: 08:00 Chicago = 13:00 UTC, so cron '0 14 * * 1-5' is wrong season
        with patch("run_signed_task.datetime") as mock_dt, \
             patch.dict(os.environ, {"GITHUB_EVENT_SCHEDULE": "0 14 * * 1-5"}):
            mock_dt.now.return_value = datetime(2024, 7, 15, 9, 10, tzinfo=CHICAGO_TZ)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertFalse(_is_correct_season_cron("08:00"))

    def test_correct_cst_cron_accepted(self):
        """During CST, the CST-season cron should be accepted."""
        # CST: 08:00 Chicago = 14:00 UTC, so cron '0 14 * * 1-5' is correct
        with patch("run_signed_task.datetime") as mock_dt, \
             patch.dict(os.environ, {"GITHUB_EVENT_SCHEDULE": "0 14 * * 1-5"}):
            mock_dt.now.return_value = datetime(2024, 1, 15, 8, 10, tzinfo=CHICAGO_TZ)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertTrue(_is_correct_season_cron("08:00"))

    def test_wrong_cdt_cron_rejected_during_cst(self):
        """During CST, the CDT-season cron should be rejected."""
        # CST: 08:00 Chicago = 14:00 UTC, so cron '0 13 * * 1-5' is wrong
        with patch("run_signed_task.datetime") as mock_dt, \
             patch.dict(os.environ, {"GITHUB_EVENT_SCHEDULE": "0 13 * * 1-5"}):
            mock_dt.now.return_value = datetime(2024, 1, 15, 7, 10, tzinfo=CHICAGO_TZ)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertFalse(_is_correct_season_cron("08:00"))

    def test_no_env_var_allows_run(self):
        """Without GITHUB_EVENT_SCHEDULE, always allow (manual/local run)."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GITHUB_EVENT_SCHEDULE", None)
            self.assertTrue(_is_correct_season_cron("08:00"))

    def test_paper_auto_execute_wrong_season(self):
        """paper_auto_execute at 11:30 CDT = 16:30 UTC; CST cron '30 17' should be rejected."""
        with patch("run_signed_task.datetime") as mock_dt, \
             patch.dict(os.environ, {"GITHUB_EVENT_SCHEDULE": "30 17 * * 1-5"}):
            mock_dt.now.return_value = datetime(2024, 7, 15, 12, 30, tzinfo=CHICAGO_TZ)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertFalse(_is_correct_season_cron("11:30"))

    def test_validation_preflight_wrong_season(self):
        """validation_preflight at 13:05 CDT = 18:05 UTC; CST cron '5 19' should be rejected."""
        with patch("run_signed_task.datetime") as mock_dt, \
             patch.dict(os.environ, {"GITHUB_EVENT_SCHEDULE": "5 19 * * 1-5"}):
            mock_dt.now.return_value = datetime(2024, 7, 15, 14, 10, tzinfo=CHICAGO_TZ)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertFalse(_is_correct_season_cron("13:05"))

    def test_learning_ingest_nightly_wrong_season(self):
        """learning_ingest at 03:30 CDT = 08:30 UTC; CST cron '30 09' should be rejected."""
        with patch("run_signed_task.datetime") as mock_dt, \
             patch.dict(os.environ, {"GITHUB_EVENT_SCHEDULE": "30 09 * * 2-6"}):
            mock_dt.now.return_value = datetime(2024, 7, 16, 3, 45, tzinfo=CHICAGO_TZ)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            self.assertFalse(_is_correct_season_cron("03:30"))

    def test_shadow_eval_midday_rejects_afternoon_cron(self):
        """Shadow eval 13:00 CDT = 18:00 UTC; afternoon cron '0 21' should be rejected."""
        with patch("run_signed_task.datetime") as mock_dt, \
             patch.dict(os.environ, {"GITHUB_EVENT_SCHEDULE": "2 21 * * 1-5"}):
            mock_dt.now.return_value = datetime(2024, 7, 15, 16, 10, tzinfo=CHICAGO_TZ)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            # 13:00 Chicago CDT = 18:00 UTC. Cron says hour 21 → wrong.
            self.assertFalse(_is_correct_season_cron("13:00"))


class TestScheduledLocalTimeGate(unittest.TestCase):
    """Tests for --scheduled-local-time gate in check_time_gate (backward compat path)."""

    @patch("run_signed_task.is_market_day", return_value=True)
    @patch("run_signed_task._is_correct_season_cron", return_value=True)
    def test_correct_season_passes(self, *_):
        """Correct season cron on a market day should pass."""
        self.assertIsNone(check_time_gate("suggestions_close", scheduled_local_time="08:00"))

    @patch("run_signed_task.is_market_day", return_value=True)
    @patch("run_signed_task._is_correct_season_cron", return_value=False)
    def test_wrong_season_rejected(self, *_):
        """Wrong season cron should be rejected."""
        self.assertIsNotNone(check_time_gate("suggestions_close", scheduled_local_time="08:00"))

    @patch("run_signed_task.is_market_day", return_value=False)
    def test_non_market_day_rejected(self, _):
        """Non-market day should be rejected regardless of cron."""
        result = check_time_gate("suggestions_close", scheduled_local_time="08:00")
        self.assertIsNotNone(result)
        self.assertIn("Not a market day", result)

    def test_skip_time_gate_overrides_scheduled_local_time(self):
        """--skip-time-gate should override --scheduled-local-time."""
        self.assertIsNone(check_time_gate("any_task", skip_time_gate=True, scheduled_local_time="11:30"))

    @patch("run_signed_task.is_market_day", return_value=True)
    @patch("run_signed_task._is_correct_season_cron", return_value=True)
    def test_scheduled_local_time_overrides_time_gates(self, *_):
        """--scheduled-local-time should bypass legacy TIME_GATES."""
        # learning_ingest has a TIME_GATES entry, but --scheduled-local-time should bypass it
        self.assertIsNone(check_time_gate("learning_ingest", scheduled_local_time="03:30"))

    @patch("run_signed_task.is_market_day", return_value=True)
    @patch("run_signed_task._is_correct_season_cron", return_value=True)
    def test_delayed_execution_still_passes(self, *_):
        """GitHub Actions delayed 90+ minutes should still pass with season-cron gate."""
        # This is the exact scenario that failed on 2026-03-18:
        # CDT cron fires at 13:00 UTC for 08:00 Chicago, but GH delays to 14:13 UTC (09:14 Chicago)
        # The old 60-min window rejected this. The new season-cron gate should allow it.
        self.assertIsNone(check_time_gate("suggestions_close", scheduled_local_time="08:00"))


# =============================================================================
# Season-Aware Gate Tests (new --expected-chicago-offset + --window-minutes)
# =============================================================================

class TestSeasonAwareGate:
    """Tests for the new --expected-chicago-offset + --window-minutes gate."""

    # --- Core behavior ---

    def test_correct_offset_within_window_runs(self):
        """Correct seasonal offset + within 90-minute window => runs."""
        mock_now = datetime(2025, 7, 14, 8, 15, tzinfo=CHICAGO_TZ)  # Monday 8:15 CDT
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = check_time_gate(
                "suggestions_close",
                scheduled_local_time="08:00",
                expected_chicago_offset="-05:00",
                window_minutes=90,
            )
            assert result is None

    def test_wrong_offset_within_window_skips_season(self):
        """Wrong seasonal offset + within window => skips due to season mismatch."""
        mock_now = datetime(2025, 7, 14, 8, 15, tzinfo=CHICAGO_TZ)  # Monday 8:15 CDT
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = check_time_gate(
                "suggestions_close",
                scheduled_local_time="08:00",
                expected_chicago_offset="-06:00",
                window_minutes=90,
            )
            assert result is not None
            assert "Season mismatch" in result

    def test_correct_offset_outside_window_skips_window(self):
        """Correct seasonal offset + outside 90-minute window => skips due to window."""
        mock_now = datetime(2025, 7, 14, 10, 0, tzinfo=CHICAGO_TZ)  # Monday 10:00 CDT
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = check_time_gate(
                "suggestions_close",
                scheduled_local_time="08:00",
                expected_chicago_offset="-05:00",
                window_minutes=90,
            )
            assert result is not None
            assert "Time gate window missed" in result

    # --- suggestions_close seasonal cases ---

    def test_suggestions_close_cdt_cron(self):
        """suggestions_close CDT cron (-05:00) should run during CDT."""
        mock_now = datetime(2025, 7, 14, 8, 30, tzinfo=CHICAGO_TZ)  # CDT
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = check_time_gate(
                "suggestions_close",
                scheduled_local_time="08:00",
                expected_chicago_offset="-05:00",
                window_minutes=90,
            )
            assert result is None

    def test_suggestions_close_cst_cron(self):
        """suggestions_close CST cron (-06:00) should run during CST."""
        mock_now = datetime(2025, 1, 13, 8, 30, tzinfo=CHICAGO_TZ)  # CST
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = check_time_gate(
                "suggestions_close",
                scheduled_local_time="08:00",
                expected_chicago_offset="-06:00",
                window_minutes=90,
            )
            assert result is None

    def test_suggestions_close_cst_cron_rejected_during_cdt(self):
        """suggestions_close CST cron (-06:00) should be rejected during CDT."""
        mock_now = datetime(2025, 7, 14, 8, 30, tzinfo=CHICAGO_TZ)  # CDT
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = check_time_gate(
                "suggestions_close",
                scheduled_local_time="08:00",
                expected_chicago_offset="-06:00",
                window_minutes=90,
            )
            assert result is not None
            assert "Season mismatch" in result

    # --- validation_preflight seasonal cases ---

    def test_validation_preflight_cdt_cron(self):
        """validation_preflight CDT cron (-05:00) should run during CDT."""
        mock_now = datetime(2025, 7, 14, 13, 20, tzinfo=CHICAGO_TZ)  # CDT
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = check_time_gate(
                "validation_preflight",
                scheduled_local_time="13:05",
                expected_chicago_offset="-05:00",
                window_minutes=90,
            )
            assert result is None

    def test_validation_preflight_cst_cron(self):
        """validation_preflight CST cron (-06:00) should run during CST."""
        mock_now = datetime(2025, 1, 13, 13, 20, tzinfo=CHICAGO_TZ)  # CST
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = check_time_gate(
                "validation_preflight",
                scheduled_local_time="13:05",
                expected_chicago_offset="-06:00",
                window_minutes=90,
            )
            assert result is None

    def test_validation_preflight_wrong_season_cdt(self):
        """validation_preflight CST cron should be rejected during CDT."""
        mock_now = datetime(2025, 7, 14, 13, 20, tzinfo=CHICAGO_TZ)  # CDT
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = check_time_gate(
                "validation_preflight",
                scheduled_local_time="13:05",
                expected_chicago_offset="-06:00",
                window_minutes=90,
            )
            assert result is not None
            assert "Season mismatch" in result

    def test_validation_preflight_wrong_season_cst(self):
        """validation_preflight CDT cron should be rejected during CST."""
        mock_now = datetime(2025, 1, 13, 13, 20, tzinfo=CHICAGO_TZ)  # CST
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = check_time_gate(
                "validation_preflight",
                scheduled_local_time="13:05",
                expected_chicago_offset="-05:00",
                window_minutes=90,
            )
            assert result is not None
            assert "Season mismatch" in result

    # --- learning_ingest_nightly seasonal cases ---

    def test_learning_ingest_nightly_cdt_cron(self):
        """learning_ingest_nightly CDT cron (-05:00) should run during CDT."""
        mock_now = datetime(2025, 7, 15, 3, 45, tzinfo=CHICAGO_TZ)  # CDT, Tuesday
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = check_time_gate(
                "learning_ingest",
                scheduled_local_time="03:30",
                expected_chicago_offset="-05:00",
                window_minutes=90,
            )
            assert result is None

    def test_learning_ingest_nightly_cst_cron(self):
        """learning_ingest_nightly CST cron (-06:00) should run during CST."""
        mock_now = datetime(2025, 1, 14, 3, 45, tzinfo=CHICAGO_TZ)  # CST, Tuesday
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = check_time_gate(
                "learning_ingest",
                scheduled_local_time="03:30",
                expected_chicago_offset="-06:00",
                window_minutes=90,
            )
            assert result is None

    def test_learning_ingest_nightly_wrong_season(self):
        """learning_ingest_nightly CST cron should be rejected during CDT."""
        mock_now = datetime(2025, 7, 15, 3, 45, tzinfo=CHICAGO_TZ)  # CDT
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = check_time_gate(
                "learning_ingest",
                scheduled_local_time="03:30",
                expected_chicago_offset="-06:00",
                window_minutes=90,
            )
            assert result is not None
            assert "Season mismatch" in result

    # --- validation_shadow_eval shared task name (13:00 and 16:00 slots) ---

    def test_shadow_eval_midday_slot(self):
        """validation_shadow_eval 13:00 local slot should run at correct time."""
        mock_now = datetime(2025, 7, 14, 13, 30, tzinfo=CHICAGO_TZ)  # CDT
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = check_time_gate(
                "validation_shadow_eval",
                scheduled_local_time="13:00",
                expected_chicago_offset="-05:00",
                window_minutes=90,
            )
            assert result is None

    def test_shadow_eval_afternoon_slot(self):
        """validation_shadow_eval 16:00 local slot should run at correct time."""
        mock_now = datetime(2025, 7, 14, 16, 30, tzinfo=CHICAGO_TZ)  # CDT
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = check_time_gate(
                "validation_shadow_eval",
                scheduled_local_time="16:00",
                expected_chicago_offset="-05:00",
                window_minutes=90,
            )
            assert result is None

    def test_shadow_eval_midday_wrong_season(self):
        """validation_shadow_eval 13:00 slot with wrong offset should be rejected."""
        mock_now = datetime(2025, 7, 14, 13, 30, tzinfo=CHICAGO_TZ)  # CDT
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = check_time_gate(
                "validation_shadow_eval",
                scheduled_local_time="13:00",
                expected_chicago_offset="-06:00",
                window_minutes=90,
            )
            assert result is not None
            assert "Season mismatch" in result

    # --- Skip reason differentiation ---

    def test_skip_reason_season_mismatch(self):
        """Skip reason should indicate season mismatch, not time window."""
        mock_now = datetime(2025, 7, 14, 8, 15, tzinfo=CHICAGO_TZ)
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = check_time_gate(
                "suggestions_close",
                scheduled_local_time="08:00",
                expected_chicago_offset="-06:00",
                window_minutes=90,
            )
            assert "Season mismatch" in result
            assert "Time gate window" not in result

    def test_skip_reason_time_window(self):
        """Skip reason should indicate time window missed, not season mismatch."""
        mock_now = datetime(2025, 7, 14, 10, 0, tzinfo=CHICAGO_TZ)
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = check_time_gate(
                "suggestions_close",
                scheduled_local_time="08:00",
                expected_chicago_offset="-05:00",
                window_minutes=90,
            )
            assert "Time gate window missed" in result
            assert "Season mismatch" not in result

    def test_skip_reason_not_market_day(self):
        """Skip reason should indicate not a market day."""
        mock_now = datetime(2025, 7, 12, 8, 15, tzinfo=CHICAGO_TZ)  # Saturday CDT
        with patch("run_signed_task.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            result = check_time_gate(
                "suggestions_close",
                scheduled_local_time="08:00",
                expected_chicago_offset="-05:00",
                window_minutes=90,
            )
            assert result is not None
            assert "Not a market day" in result
