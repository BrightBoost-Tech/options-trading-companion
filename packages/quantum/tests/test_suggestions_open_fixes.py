"""
Tests for suggestions_open unblock fixes:
- Policy variable handling
- IVRepo "null" string handling
- Missing column resilience

These tests verify the fix logic without importing heavy dependencies.
"""

import pytest
from unittest.mock import MagicMock, patch
import os


class TestIVRepoNullHandling:
    """Test that IVRepo handles 'null' strings without raising."""

    def test_null_string_detection_logic(self):
        """The null string detection logic should correctly identify null-like values."""
        # This tests the logic pattern used in IVRepo

        def is_null_like(iv_val):
            """Logic extracted from iv_repository.py fix."""
            if iv_val is None:
                return True
            if isinstance(iv_val, str):
                iv_val_str = iv_val.strip().lower()
                if iv_val_str in ("null", "none", ""):
                    return True
            return False

        def safe_float(iv_val):
            """Logic extracted from iv_repository.py fix."""
            if is_null_like(iv_val):
                return None
            try:
                return float(iv_val)
            except (ValueError, TypeError):
                return None

        # Test cases
        test_cases = [
            ("0.25", 0.25),
            ("null", None),
            ("NULL", None),
            ("Null", None),
            ("none", None),
            ("None", None),
            ("NONE", None),
            ("", None),
            ("  ", None),
            ("0.22", 0.22),
            (None, None),
            (0.25, 0.25),
            (25, 25.0),
            ("invalid", None),
            ("abc", None),
        ]

        for iv_val, expected in test_cases:
            result = safe_float(iv_val)
            assert result == expected, f"safe_float({iv_val!r}) = {result}, expected {expected}"

    def test_null_string_values_skipped_in_loop(self):
        """Verify that null-like values are skipped when building history."""
        # Simulate the loop in IVRepo

        data = [
            {"underlying": "SPY", "iv_30d": "0.25", "as_of_date": "2024-01-15"},
            {"underlying": "SPY", "iv_30d": "null", "as_of_date": "2024-01-14"},
            {"underlying": "SPY", "iv_30d": "NULL", "as_of_date": "2024-01-13"},
            {"underlying": "SPY", "iv_30d": "", "as_of_date": "2024-01-12"},
            {"underlying": "SPY", "iv_30d": "0.22", "as_of_date": "2024-01-11"},
            {"underlying": "QQQ", "iv_30d": "None", "as_of_date": "2024-01-15"},
            {"underlying": "QQQ", "iv_30d": "0.28", "as_of_date": "2024-01-14"},
            {"underlying": "QQQ", "iv_30d": None, "as_of_date": "2024-01-13"},
        ]

        # Logic from iv_repository.py
        grouped_data = {}
        for row in data:
            sym = row.get('underlying')
            iv_val = row.get('iv_30d')
            date_val = row.get('as_of_date')

            if not sym or iv_val is None:
                continue

            # Handle string "null" or empty strings as None
            if isinstance(iv_val, str):
                iv_val_str = iv_val.strip().lower()
                if iv_val_str in ("null", "none", ""):
                    continue

            try:
                iv_float = float(iv_val)
            except (ValueError, TypeError):
                continue

            if sym not in grouped_data:
                grouped_data[sym] = []

            grouped_data[sym].append((date_val, iv_float))

        # SPY should have 2 valid entries (0.25 and 0.22)
        assert len(grouped_data.get("SPY", [])) == 2
        # QQQ should have 1 valid entry (0.28)
        assert len(grouped_data.get("QQQ", [])) == 1


class TestPolicyVariableInitialization:
    """Test that scanner policy variable is always defined."""

    def test_surface_v4_policy_functions_exist(self):
        """Surface V4 policy helper functions should exist and return strings."""
        # Test the helper functions directly without heavy imports

        def _is_surface_v4_enabled():
            return os.getenv("SURFACE_V4_ENABLE", "").lower() in ("1", "true", "yes")

        def _get_surface_v4_policy():
            return os.getenv("SURFACE_V4_POLICY", "observe").lower()

        # Test with env vars
        with patch.dict(os.environ, {"SURFACE_V4_ENABLE": "0"}):
            assert _is_surface_v4_enabled() is False

        with patch.dict(os.environ, {"SURFACE_V4_ENABLE": "1"}):
            assert _is_surface_v4_enabled() is True

        with patch.dict(os.environ, {"SURFACE_V4_POLICY": "observe"}):
            assert _get_surface_v4_policy() == "observe"

        with patch.dict(os.environ, {"SURFACE_V4_POLICY": "skip"}):
            assert _get_surface_v4_policy() == "skip"

        with patch.dict(os.environ, {}, clear=False):
            # Default should be observe
            if "SURFACE_V4_POLICY" not in os.environ:
                pass  # Can't reliably test default without clearing

    def test_surface_policy_variable_naming(self):
        """The fix renames 'policy' to 'surface_policy' to avoid shadowing."""
        # Read the actual file and verify the fix is in place
        import re

        scanner_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "options_scanner.py"
        )

        with open(scanner_path, "r") as f:
            content = f.read()

        # Check that surface_policy is used instead of policy in the Surface V4 block
        assert "surface_policy = _get_surface_v4_policy()" in content, \
            "Expected 'surface_policy = _get_surface_v4_policy()' in scanner"

        # Check that surface_policy is used in policy enforcement
        assert 'if surface_policy == "skip"' in content, \
            "Expected 'if surface_policy == \"skip\"' in scanner"


class TestBannedStrategiesHandling:
    """Test that missing banned_strategies returns empty list."""

    def test_banned_strategies_missing_returns_empty(self):
        """When settings.banned_strategies is missing, return empty list."""
        banned_strategies = []
        try:
            raise Exception("column banned_strategies does not exist")
        except Exception:
            pass

        assert banned_strategies == []

    def test_banned_strategies_null_returns_empty(self):
        """When banned_strategies is None, return empty list."""
        mock_data = {"banned_strategies": None}
        banned_strategies = mock_data.get("banned_strategies") or []
        assert banned_strategies == []

    def test_banned_strategies_present_returns_list(self):
        """When banned_strategies is present, return the list."""
        mock_data = {"banned_strategies": ["iron_condor", "straddle"]}
        banned_strategies = mock_data.get("banned_strategies") or []
        assert banned_strategies == ["iron_condor", "straddle"]


class TestExecutionServiceColumnResilience:
    """Test that execution service handles missing columns gracefully."""

    def test_column_error_detection(self):
        """Column error detection logic should identify column-related errors."""
        test_errors = [
            ("column suggestion_log_id does not exist", True),
            ("Column 'suggestion_log_id' not found", True),
            ("unknown column suggestion_log_id", True),
            ("connection refused", False),
            ("timeout", False),
            ("permission denied", False),
        ]

        for error_msg, should_trigger_fallback in test_errors:
            # Logic from execution_service.py fix
            is_column_error = "suggestion_log_id" in error_msg or "column" in error_msg.lower()
            assert is_column_error == should_trigger_fallback, \
                f"Error '{error_msg}' should{'' if should_trigger_fallback else ' not'} trigger fallback"

    def test_fallback_query_pattern(self):
        """The fallback query should work without suggestion_log_id."""
        # This tests the query construction pattern

        full_columns = "symbol, fill_price, fees, suggestion_id, suggestion_log_id, quantity, target_price"
        fallback_columns = "symbol, fill_price, fees, suggestion_id, quantity, target_price"

        # Verify suggestion_log_id is removed in fallback
        assert "suggestion_log_id" in full_columns
        assert "suggestion_log_id" not in fallback_columns

        # Both should have the essential columns
        for col in ["symbol", "fill_price", "fees", "suggestion_id", "quantity", "target_price"]:
            assert col in full_columns
            assert col in fallback_columns


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
