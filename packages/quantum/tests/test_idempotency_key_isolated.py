"""
Isolated unit tests for _suggestions_idempotency_key logic.

These tests don't import the full public_tasks module to avoid
deep import chains requiring redis/etc modules.
"""

import re
import secrets
from datetime import datetime

import pytest


DEFAULT_STRATEGY_NAME = "spy_opt_autolearn_v6"


def _suggestions_idempotency_key(
    task_type: str,
    user_id=None,
    skip_sync: bool = False,
    strategy_name: str = DEFAULT_STRATEGY_NAME,
    force_rerun: bool = False,
    force_nonce=None,
) -> str:
    """
    Copy of _suggestions_idempotency_key logic for isolated testing.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    user_part = user_id or "all"
    ss_part = f"ss{int(skip_sync)}"

    if strategy_name == DEFAULT_STRATEGY_NAME:
        strat_part = "default"
    else:
        strat_part = strategy_name[:16]

    base_key = f"{today}-{task_type}-{user_part}-{ss_part}-{strat_part}"

    if force_rerun:
        nonce = force_nonce if force_nonce else secrets.token_hex(4)
        return f"{base_key}-force-{nonce}"

    return base_key


class TestSuggestionsIdempotencyKey:
    """Test idempotency key generation."""

    def test_basic_key_format(self):
        """Key should include date, task_type, user, skip_sync, strategy."""
        key = _suggestions_idempotency_key(task_type="open")
        today = datetime.now().strftime("%Y-%m-%d")

        assert key.startswith(today)
        assert "-open-" in key
        assert "-all-" in key
        assert "-ss0-" in key
        assert "-default" in key

    def test_close_task_type(self):
        """Key should reflect 'close' task type."""
        key = _suggestions_idempotency_key(task_type="close")
        assert "-close-" in key
        assert "-open-" not in key

    def test_user_id_included(self):
        """Key should include user_id when provided."""
        user_id = "00000000-0000-0000-0000-000000000001"
        key = _suggestions_idempotency_key(task_type="open", user_id=user_id)
        assert user_id in key
        assert "-all-" not in key

    def test_skip_sync_true(self):
        """Key should reflect skip_sync=True."""
        key = _suggestions_idempotency_key(task_type="open", skip_sync=True)
        assert "-ss1-" in key
        assert "-ss0-" not in key

    def test_skip_sync_false(self):
        """Key should reflect skip_sync=False."""
        key = _suggestions_idempotency_key(task_type="open", skip_sync=False)
        assert "-ss0-" in key
        assert "-ss1-" not in key

    def test_custom_strategy_name(self):
        """Key should include custom strategy name (truncated)."""
        key = _suggestions_idempotency_key(
            task_type="open",
            strategy_name="my_custom_strategy_v1"
        )
        assert "-default" not in key
        assert "-my_custom_strat" in key

    def test_default_strategy_shortens(self):
        """Default strategy should be shortened to 'default'."""
        key = _suggestions_idempotency_key(
            task_type="open",
            strategy_name=DEFAULT_STRATEGY_NAME
        )
        assert "-default" in key
        assert DEFAULT_STRATEGY_NAME not in key

    def test_different_inputs_produce_different_keys(self):
        """Different input combinations should produce different keys."""
        user_id = "00000000-0000-0000-0000-000000000001"

        key1 = _suggestions_idempotency_key(task_type="open")
        key2 = _suggestions_idempotency_key(task_type="close")
        key3 = _suggestions_idempotency_key(task_type="open", user_id=user_id)
        key4 = _suggestions_idempotency_key(task_type="open", skip_sync=True)
        key5 = _suggestions_idempotency_key(task_type="open", strategy_name="other_strat")

        keys = [key1, key2, key3, key4, key5]
        assert len(keys) == len(set(keys)), "All keys should be unique"


class TestSuggestionsIdempotencyKeyForceRerun:
    """Test force_rerun behavior."""

    def test_force_rerun_appends_nonce(self):
        """force_rerun should append '-force-{nonce}' suffix."""
        key = _suggestions_idempotency_key(task_type="open", force_rerun=True)
        assert "-force-" in key
        assert re.search(r"-force-[a-f0-9]{8}$", key)

    def test_force_rerun_produces_unique_keys(self):
        """Multiple force_rerun calls should produce different keys."""
        keys = [
            _suggestions_idempotency_key(task_type="open", force_rerun=True)
            for _ in range(5)
        ]
        assert len(keys) == len(set(keys)), "Force rerun keys should be unique"

    def test_force_nonce_deterministic(self):
        """force_nonce should produce deterministic keys."""
        nonce = "abc12345"
        key1 = _suggestions_idempotency_key(
            task_type="open",
            force_rerun=True,
            force_nonce=nonce
        )
        key2 = _suggestions_idempotency_key(
            task_type="open",
            force_rerun=True,
            force_nonce=nonce
        )

        assert key1 == key2, "Same nonce should produce same key"
        assert f"-force-{nonce}" in key1

    def test_force_nonce_without_force_rerun_ignored(self):
        """force_nonce should be ignored if force_rerun=False."""
        key = _suggestions_idempotency_key(
            task_type="open",
            force_rerun=False,
            force_nonce="ignored123"
        )
        assert "-force-" not in key
        assert "ignored123" not in key

    def test_force_rerun_still_includes_all_inputs(self):
        """force_rerun key should still include user_id, skip_sync, strategy."""
        user_id = "00000000-0000-0000-0000-000000000002"
        key = _suggestions_idempotency_key(
            task_type="close",
            user_id=user_id,
            skip_sync=True,
            strategy_name="test_strat",
            force_rerun=True,
            force_nonce="abc123"
        )

        assert "-close-" in key
        assert user_id in key
        assert "-ss1-" in key
        assert "-test_strat-" in key
        assert "-force-abc123" in key


class TestSuggestionsIdempotencyKeySameDay:
    """Test same-day key consistency."""

    def test_same_day_same_inputs_same_key(self):
        """Same inputs on same day should produce same key."""
        key1 = _suggestions_idempotency_key(
            task_type="open",
            user_id="test-user",
            skip_sync=True
        )
        key2 = _suggestions_idempotency_key(
            task_type="open",
            user_id="test-user",
            skip_sync=True
        )

        assert key1 == key2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
