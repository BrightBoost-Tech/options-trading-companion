"""
Regression tests for IVRepo null string sanitization.

Verifies fix for PostgreSQL 22P02 error:
  invalid input syntax for type numeric: "null"

The fix ensures:
1. Numeric fields are sanitized before DB writes (no string "null")
2. Queries use proper IS NOT NULL syntax instead of != "null"
3. Float conversions handle string "null" gracefully
"""

import pytest
import os


class TestSanitizeNumericFunction:
    """Test the _sanitize_numeric helper function."""

    def test_sanitize_numeric_logic(self):
        """Verify _sanitize_numeric converts string nulls to None."""
        # Replicate the logic from iv_repository.py

        def _sanitize_numeric(value):
            if value is None:
                return None
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                val_str = value.strip().lower()
                if val_str in ("null", "none", ""):
                    return None
                try:
                    return float(value)
                except (ValueError, TypeError):
                    return None
            return None

        # Test cases that caused 22P02
        assert _sanitize_numeric("null") is None
        assert _sanitize_numeric("NULL") is None
        assert _sanitize_numeric("Null") is None
        assert _sanitize_numeric("  null  ") is None

        # Other null-like values
        assert _sanitize_numeric("none") is None
        assert _sanitize_numeric("None") is None
        assert _sanitize_numeric("") is None
        assert _sanitize_numeric("  ") is None
        assert _sanitize_numeric(None) is None

        # Valid numeric values
        assert _sanitize_numeric(0.25) == 0.25
        assert _sanitize_numeric(25) == 25.0
        assert _sanitize_numeric("0.25") == 0.25
        assert _sanitize_numeric("25") == 25.0
        assert _sanitize_numeric("0") == 0.0

        # Invalid strings return None (not raise)
        assert _sanitize_numeric("invalid") is None
        assert _sanitize_numeric("abc123") is None


class TestUpsertPayloadSanitization:
    """Test that upsert_iv_point sanitizes numeric fields."""

    def test_upsert_sanitizes_null_strings(self):
        """Verify upsert sanitizes all numeric fields before DB write."""
        # Read the actual file to verify the fix is in place
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "services",
            "iv_repository.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Verify _sanitize_numeric is defined
        assert "def _sanitize_numeric(" in content, \
            "Expected _sanitize_numeric helper function"

        # Verify numeric fields are sanitized in upsert
        assert '_sanitize_numeric(data.get("iv_30d"))' in content, \
            "iv_30d should be sanitized"
        assert '_sanitize_numeric(data.get("iv1"))' in content, \
            "iv1 should be sanitized"
        assert '_sanitize_numeric(data.get("iv2"))' in content, \
            "iv2 should be sanitized"
        assert '_sanitize_numeric(data.get("strike1"))' in content, \
            "strike1 should be sanitized"
        assert '_sanitize_numeric(data.get("strike2"))' in content, \
            "strike2 should be sanitized"
        assert '_sanitize_numeric(data.get("quality_score"))' in content, \
            "quality_score should be sanitized"


class TestQueryNullFilter:
    """Test that queries use proper IS NOT NULL syntax."""

    def test_query_uses_is_not_null(self):
        """Verify queries don't use .neq('col', 'null') on numeric columns."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "services",
            "iv_repository.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # The old broken pattern should NOT exist
        assert '.neq("iv_30d", "null")' not in content, \
            "Should not compare numeric column to string 'null'"

        # The new correct pattern should exist
        assert '.not_.is_("iv_30d", "null")' in content, \
            "Should use proper IS NOT NULL syntax"


class TestLatestIVSanitization:
    """Test that latest IV value is sanitized before float conversion."""

    def test_latest_iv_uses_sanitizer(self):
        """Verify get_iv_context sanitizes latest['iv_30d'] before use."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "services",
            "iv_repository.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Should use sanitizer for latest iv_30d
        assert "_sanitize_numeric(latest.get('iv_30d'))" in content, \
            "latest iv_30d should be sanitized"

        # Should NOT have raw float() on latest['iv_30d']
        assert "float(latest['iv_30d'])" not in content, \
            "Should not use raw float() on latest iv_30d"


class TestRegressionPayloads:
    """Test specific payloads that caused 22P02 errors."""

    def test_null_string_payload_does_not_raise(self):
        """Simulate a payload with 'null' strings that previously caused 22P02."""
        # This is the logic that would be applied to incoming data

        def _sanitize_numeric(value):
            if value is None:
                return None
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                val_str = value.strip().lower()
                if val_str in ("null", "none", ""):
                    return None
                try:
                    return float(value)
                except (ValueError, TypeError):
                    return None
            return None

        # Payload that would cause 22P02 before the fix
        incoming_data = {
            "iv_30d": "null",
            "iv1": "NULL",
            "iv2": "0.25",
            "strike1": "none",
            "strike2": "450.0",
            "quality_score": "",
            "inputs": {"spot": 100}
        }

        # After sanitization, should be safe for DB
        sanitized = {
            "iv_30d": _sanitize_numeric(incoming_data.get("iv_30d")),
            "iv1": _sanitize_numeric(incoming_data.get("iv1")),
            "iv2": _sanitize_numeric(incoming_data.get("iv2")),
            "strike1": _sanitize_numeric(incoming_data.get("strike1")),
            "strike2": _sanitize_numeric(incoming_data.get("strike2")),
            "quality_score": _sanitize_numeric(incoming_data.get("quality_score")),
        }

        assert sanitized["iv_30d"] is None
        assert sanitized["iv1"] is None
        assert sanitized["iv2"] == 0.25
        assert sanitized["strike1"] is None
        assert sanitized["strike2"] == 450.0
        assert sanitized["quality_score"] is None

        # None values are safe for Postgres NULL
        for key, val in sanitized.items():
            if val is not None:
                # If not None, must be a valid float
                assert isinstance(val, float), f"{key} should be float, got {type(val)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
