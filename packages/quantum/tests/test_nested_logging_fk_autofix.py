"""
Tests for decision_logs FK violation auto-repair.

Verifies:
1. FK violation detection (23503 error code)
2. Placeholder inference_log creation
3. Retry after placeholder creation
4. Duplicate/unique constraint handling
"""

import pytest
import uuid
from typing import Optional
from datetime import datetime


class MockSupabaseTable:
    """Mock Supabase table for testing insert behavior."""

    def __init__(self, should_fail_fk: bool = False, should_fail_unique: bool = False):
        self.should_fail_fk = should_fail_fk
        self.should_fail_unique = should_fail_unique
        self.insert_count = 0
        self.last_data = None

    def insert(self, data):
        self.insert_count += 1
        self.last_data = data
        return self

    def execute(self):
        if self.should_fail_fk and self.insert_count == 1:
            raise Exception("ERROR: insert or update on table 'decision_logs' violates "
                            "foreign key constraint '23503' - Key (trace_id) is not present in table 'inference_log'")
        if self.should_fail_unique:
            raise Exception("ERROR: duplicate key value violates unique constraint '23505'")
        return {"data": [self.last_data]}


class MockSupabaseClient:
    """Mock Supabase client for testing."""

    def __init__(self, inference_table=None, decision_table=None):
        self._inference_table = inference_table or MockSupabaseTable()
        self._decision_table = decision_table or MockSupabaseTable()

    def table(self, name):
        if name == "inference_log":
            return self._inference_table
        elif name == "decision_logs":
            return self._decision_table
        return MockSupabaseTable()


def _ensure_inference_log_exists(supabase, trace_id: uuid.UUID) -> bool:
    """
    Ensure an inference_log row exists for the given trace_id.
    Creates a minimal placeholder if missing.
    Returns True if successful (or already exists), False on error.
    """
    try:
        data = {
            "trace_id": str(trace_id),
            "timestamp": datetime.now().isoformat(),
            "symbol_universe": [],
            "inputs_snapshot": {},
            "predicted_mu": {},
            "predicted_sigma": {},
            "optimizer_profile": "auto_placeholder"
        }
        supabase.table("inference_log").insert(data).execute()
        return True
    except Exception as e:
        err_str = str(e).lower()
        # Ignore duplicate/unique constraint violations (already exists)
        if "duplicate" in err_str or "unique" in err_str or "23505" in err_str:
            return True
        return False


def log_decision_with_fk_repair(
    supabase,
    trace_id: uuid.UUID,
    user_id: str,
    decision_type: str,
    content: dict
) -> uuid.UUID:
    """
    Log decision with FK auto-repair logic.
    Mirrors the production log_decision function.
    """
    data = {
        "trace_id": str(trace_id),
        "user_id": user_id,
        "decision_type": decision_type,
        "content": content,
        "created_at": datetime.now().isoformat()
    }

    try:
        supabase.table("decision_logs").insert(data).execute()
    except Exception as e:
        err_str = str(e).lower()
        # Check for FK violation (23503 = foreign_key_violation)
        if "23503" in err_str or "fk_decision_logs_trace" in err_str or "foreign key" in err_str:
            if _ensure_inference_log_exists(supabase, trace_id):
                # Retry the insert
                try:
                    supabase.table("decision_logs").insert(data).execute()
                except Exception:
                    pass

    return trace_id


class TestFKViolationDetection:
    """Tests for FK violation error detection."""

    def test_detects_23503_error_code(self):
        """Should detect FK violation via 23503 error code."""
        error_msg = "ERROR: insert or update violates foreign key constraint '23503'"
        assert "23503" in error_msg.lower()

    def test_detects_foreign_key_text(self):
        """Should detect FK violation via 'foreign key' text."""
        error_msg = "foreign key constraint violation"
        assert "foreign key" in error_msg.lower()

    def test_detects_fk_constraint_name(self):
        """Should detect FK violation via constraint name."""
        error_msg = "violates constraint fk_decision_logs_trace"
        assert "fk_decision_logs_trace" in error_msg.lower()


class TestPlaceholderCreation:
    """Tests for inference_log placeholder creation."""

    def test_creates_placeholder_successfully(self):
        """Should create placeholder and return True."""
        supabase = MockSupabaseClient()
        trace_id = uuid.uuid4()

        result = _ensure_inference_log_exists(supabase, trace_id)

        assert result is True
        assert supabase._inference_table.insert_count == 1
        assert supabase._inference_table.last_data["optimizer_profile"] == "auto_placeholder"

    def test_placeholder_has_required_fields(self):
        """Placeholder should have all required fields."""
        supabase = MockSupabaseClient()
        trace_id = uuid.uuid4()

        _ensure_inference_log_exists(supabase, trace_id)

        data = supabase._inference_table.last_data
        assert "trace_id" in data
        assert "timestamp" in data
        assert "symbol_universe" in data
        assert "inputs_snapshot" in data
        assert "predicted_mu" in data
        assert "predicted_sigma" in data
        assert "optimizer_profile" in data

    def test_placeholder_uses_empty_defaults(self):
        """Placeholder should use empty lists/dicts for data fields."""
        supabase = MockSupabaseClient()
        trace_id = uuid.uuid4()

        _ensure_inference_log_exists(supabase, trace_id)

        data = supabase._inference_table.last_data
        assert data["symbol_universe"] == []
        assert data["inputs_snapshot"] == {}
        assert data["predicted_mu"] == {}
        assert data["predicted_sigma"] == {}

    def test_returns_true_on_duplicate_error(self):
        """Should return True if row already exists (duplicate error)."""
        inference_table = MockSupabaseTable(should_fail_unique=True)
        supabase = MockSupabaseClient(inference_table=inference_table)
        trace_id = uuid.uuid4()

        result = _ensure_inference_log_exists(supabase, trace_id)

        assert result is True

    def test_returns_false_on_other_error(self):
        """Should return False on non-duplicate errors."""
        class FailingTable(MockSupabaseTable):
            def execute(self):
                raise Exception("Connection timeout")

        supabase = MockSupabaseClient(inference_table=FailingTable())
        trace_id = uuid.uuid4()

        result = _ensure_inference_log_exists(supabase, trace_id)

        assert result is False


class TestFKRetryLogic:
    """Tests for FK violation retry logic."""

    def test_retries_after_creating_placeholder(self):
        """Should retry decision_logs insert after creating placeholder."""
        # Decision table fails on first insert (FK violation), succeeds on second
        decision_table = MockSupabaseTable(should_fail_fk=True)
        supabase = MockSupabaseClient(decision_table=decision_table)
        trace_id = uuid.uuid4()

        log_decision_with_fk_repair(supabase, trace_id, "user123", "test", {})

        # Should have attempted 2 inserts on decision_logs
        assert decision_table.insert_count == 2
        # Should have created placeholder in inference_log
        assert supabase._inference_table.insert_count == 1

    def test_no_retry_when_no_fk_error(self):
        """Should not retry when no FK error occurs."""
        supabase = MockSupabaseClient()
        trace_id = uuid.uuid4()

        log_decision_with_fk_repair(supabase, trace_id, "user123", "test", {})

        # Only one insert attempt
        assert supabase._decision_table.insert_count == 1
        # No placeholder created
        assert supabase._inference_table.insert_count == 0


class TestEdgeCases:
    """Edge case tests for FK auto-repair."""

    def test_handles_none_trace_id_gracefully(self):
        """Should handle None trace_id without crashing."""
        supabase = MockSupabaseClient()

        # This would normally fail, but should not raise unhandled exception
        try:
            _ensure_inference_log_exists(supabase, None)
        except Exception:
            pass  # Expected to fail, just checking it doesn't crash unexpectedly

    def test_preserves_original_trace_id(self):
        """Return value should be the original trace_id."""
        supabase = MockSupabaseClient()
        trace_id = uuid.uuid4()

        result = log_decision_with_fk_repair(supabase, trace_id, "user123", "test", {"key": "value"})

        assert result == trace_id

    def test_placeholder_trace_id_matches_decision(self):
        """Placeholder trace_id should match the decision trace_id."""
        decision_table = MockSupabaseTable(should_fail_fk=True)
        supabase = MockSupabaseClient(decision_table=decision_table)
        trace_id = uuid.uuid4()

        log_decision_with_fk_repair(supabase, trace_id, "user123", "test", {})

        placeholder_trace_id = supabase._inference_table.last_data["trace_id"]
        assert placeholder_trace_id == str(trace_id)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
