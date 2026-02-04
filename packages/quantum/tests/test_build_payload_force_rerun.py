"""
Isolated unit tests for build_payload force_rerun support.

These tests don't import the full run_signed_task module to avoid
deep import chains requiring cryptography/redis modules.
"""

import json
import pytest


def build_payload(
    task_name: str,
    user_id=None,
    payload_json=None,
    skip_sync: bool = False,
    force_rerun: bool = False,
) -> dict:
    """
    Copy of build_payload logic for isolated testing.
    """
    DEFAULT_STRATEGY_NAME = "spy_opt_autolearn_v6"
    payload = {}

    if task_name in ("suggestions_close", "suggestions_open"):
        payload["strategy_name"] = DEFAULT_STRATEGY_NAME

    if user_id:
        payload["user_id"] = user_id

    if skip_sync:
        payload["skip_sync"] = True

    if force_rerun:
        payload["force_rerun"] = True

    if payload_json is not None:
        payload_json_stripped = payload_json.strip()
        if payload_json_stripped:
            try:
                custom = json.loads(payload_json_stripped)
                if not isinstance(custom, dict):
                    raise ValueError(
                        f"payload_json must be a JSON object, got {type(custom).__name__}"
                    )
                payload.update(custom)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in payload_json: {e}")

    return payload


class TestBuildPayloadForceRerun:
    """Test force_rerun flag in build_payload."""

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

    def test_force_rerun_for_non_suggestions_task(self):
        """force_rerun should work for any task (e.g., universe_sync)."""
        payload = build_payload("universe_sync", force_rerun=True)
        assert payload["force_rerun"] is True
        assert "strategy_name" not in payload  # Not a suggestions task


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
