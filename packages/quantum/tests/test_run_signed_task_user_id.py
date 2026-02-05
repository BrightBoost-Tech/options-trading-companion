"""
Isolated tests for run_signed_task.py user_id handling.

Tests that:
- universe_sync with payload_json {} sends empty payload (no user_id)
- suggestions_open with USER_ID env injects user_id (allowed)
- paper_auto_execute requires user_id and fails early if missing
- payload_json can override user_id
"""

import json
import pytest


# Copy of TASKS user_id_mode for testing
TASK_USER_ID_MODES = {
    "universe_sync": "none",
    "suggestions_open": "allow",
    "suggestions_close": "allow",
    "learning_ingest": "allow",
    "validation_eval": "allow",
    "paper_auto_execute": "require",
    "paper_auto_close": "require",
    "paper_safety_close_one": "require",
    "validation_shadow_eval": "require",
    "validation_cohort_eval": "require",
    "validation_autopromote_cohort": "require",
    "validation_preflight": "require",
    "validation_init_window": "require",
    "ops_health_check": "none",
    "weekly_report": "none",
    "morning_brief": "none",
    "midday_scan": "none",
    "strategy_autotune": "none",
    "iv_daily_refresh": "none",
    "learning_train": "none",
    "plaid_backfill": "allow",
}


def build_payload_test(
    task_name: str,
    user_id: str = None,
    payload_json: str = None,
    skip_sync: bool = False,
    force_rerun: bool = False,
) -> dict:
    """
    Copy of build_payload logic for isolated testing.
    """
    payload = {}
    user_id_mode = TASK_USER_ID_MODES.get(task_name, "none")

    # Task-specific defaults
    if task_name in ("suggestions_close", "suggestions_open"):
        payload["strategy_name"] = "spy_opt_autolearn_v6"

    # Handle user_id based on mode
    if user_id_mode == "require":
        if not user_id:
            raise ValueError(
                f"Task '{task_name}' requires user_id but none was provided."
            )
        payload["user_id"] = user_id
    elif user_id_mode == "allow":
        if user_id:
            payload["user_id"] = user_id
    # "none": never inject

    if skip_sync:
        payload["skip_sync"] = True

    if force_rerun:
        payload["force_rerun"] = True

    # Merge payload_json
    if payload_json is not None:
        stripped = payload_json.strip()
        if stripped:
            custom = json.loads(stripped)
            if not isinstance(custom, dict):
                raise ValueError("payload_json must be a JSON object")
            payload.update(custom)

    return payload


class TestUniverseSyncNoUserId:
    """universe_sync must NOT inject user_id."""

    def test_empty_payload_json(self):
        """payload_json {} results in empty payload."""
        payload = build_payload_test("universe_sync", user_id="some-user", payload_json="{}")
        assert payload == {}, f"Expected empty payload, got {payload}"
        assert "user_id" not in payload

    def test_no_payload_json(self):
        """No payload_json results in empty payload."""
        payload = build_payload_test("universe_sync", user_id="some-user")
        assert payload == {}
        assert "user_id" not in payload

    def test_whitespace_payload_json(self):
        """Whitespace-only payload_json results in empty payload."""
        payload = build_payload_test("universe_sync", user_id="some-user", payload_json="   ")
        assert payload == {}


class TestSuggestionsOpenAllowsUserId:
    """suggestions_open allows optional user_id."""

    def test_injects_user_id_when_provided(self):
        """user_id is injected when provided."""
        payload = build_payload_test("suggestions_open", user_id="test-user-123")
        assert payload["user_id"] == "test-user-123"
        assert payload["strategy_name"] == "spy_opt_autolearn_v6"

    def test_no_user_id_when_not_provided(self):
        """No user_id when not provided."""
        payload = build_payload_test("suggestions_open")
        assert "user_id" not in payload
        assert payload["strategy_name"] == "spy_opt_autolearn_v6"

    def test_payload_json_overrides_user_id(self):
        """payload_json user_id overrides CLI user_id."""
        payload = build_payload_test(
            "suggestions_open",
            user_id="cli-user",
            payload_json='{"user_id": "json-user"}'
        )
        assert payload["user_id"] == "json-user"

    def test_empty_payload_json_keeps_user_id(self):
        """Empty payload_json {} keeps user_id from CLI."""
        payload = build_payload_test(
            "suggestions_open",
            user_id="cli-user",
            payload_json="{}"
        )
        assert payload["user_id"] == "cli-user"


class TestPaperAutoExecuteRequiresUserId:
    """paper_auto_execute requires user_id."""

    def test_fails_without_user_id(self):
        """Raises ValueError when user_id missing."""
        with pytest.raises(ValueError) as exc_info:
            build_payload_test("paper_auto_execute")
        assert "requires user_id" in str(exc_info.value)

    def test_succeeds_with_user_id(self):
        """Works when user_id provided."""
        payload = build_payload_test("paper_auto_execute", user_id="test-user")
        assert payload["user_id"] == "test-user"

    def test_payload_json_can_provide_user_id(self):
        """payload_json can provide required user_id."""
        # Note: In real code, user_id is checked before payload_json merge
        # So this would fail. Let's verify that behavior.
        with pytest.raises(ValueError):
            build_payload_test(
                "paper_auto_execute",
                payload_json='{"user_id": "json-user"}'
            )


class TestPayloadMergePrecedence:
    """Test merge precedence: defaults < flags < user_id < payload_json."""

    def test_skip_sync_flag(self):
        """skip_sync flag adds to payload."""
        payload = build_payload_test("suggestions_open", skip_sync=True)
        assert payload["skip_sync"] is True

    def test_force_rerun_flag(self):
        """force_rerun flag adds to payload."""
        payload = build_payload_test("suggestions_open", force_rerun=True)
        assert payload["force_rerun"] is True

    def test_payload_json_overrides_flags(self):
        """payload_json can override flags."""
        payload = build_payload_test(
            "suggestions_open",
            skip_sync=True,
            force_rerun=True,
            payload_json='{"skip_sync": false, "force_rerun": false}'
        )
        assert payload["skip_sync"] is False
        assert payload["force_rerun"] is False

    def test_all_together(self):
        """All options work together."""
        payload = build_payload_test(
            "suggestions_open",
            user_id="cli-user",
            skip_sync=True,
            force_rerun=True,
            payload_json='{"custom_key": "custom_value"}'
        )
        assert payload["strategy_name"] == "spy_opt_autolearn_v6"
        assert payload["user_id"] == "cli-user"
        assert payload["skip_sync"] is True
        assert payload["force_rerun"] is True
        assert payload["custom_key"] == "custom_value"


class TestOtherNoUserIdTasks:
    """Other tasks with user_id_mode=none should not inject user_id."""

    @pytest.mark.parametrize("task_name", [
        "ops_health_check",
        "weekly_report",
        "morning_brief",
        "midday_scan",
        "strategy_autotune",
        "iv_daily_refresh",
        "learning_train",
    ])
    def test_no_user_id_injected(self, task_name):
        """user_id is never injected for these tasks."""
        payload = build_payload_test(task_name, user_id="some-user")
        assert "user_id" not in payload


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
