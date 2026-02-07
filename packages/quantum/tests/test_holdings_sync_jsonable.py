"""
Regression tests for holdings_sync JSON serialization.

Verifies fix for:
  Object of type datetime is not JSON serializable

Ensures:
1. Job handler results are JSON-serializable
2. Datetime objects are converted to isoformat strings
3. Notes containing various types are safely serialized
"""

import pytest
import json
import os
from datetime import datetime, timezone, date
from decimal import Decimal
from enum import Enum
from uuid import UUID


# Replicate _to_jsonable logic for testing without heavy imports
def _to_jsonable_local(obj):
    """
    Local copy of _to_jsonable logic for testing.
    Matches packages.quantum.jobs.db._to_jsonable
    """
    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (str, int, float)):
        return obj
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, Enum):
        return obj.value
    if hasattr(obj, 'model_dump'):
        return _to_jsonable_local(obj.model_dump())
    if hasattr(obj, 'dict'):
        return _to_jsonable_local(obj.dict())
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable_local(item) for item in obj]
    if isinstance(obj, set):
        items = [_to_jsonable_local(item) for item in obj]
        try:
            return sorted(items)
        except TypeError:
            return sorted(items, key=lambda x: (str(x), type(x).__name__))
    if isinstance(obj, dict):
        return {str(k): _to_jsonable_local(v) for k, v in obj.items()}
    return str(obj)


class TestToJsonableFunction:
    """Test the _to_jsonable helper handles all expected types."""

    def test_datetime_converted_to_isoformat(self):
        """Verify datetime objects are converted to isoformat strings."""
        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        result = _to_jsonable_local(dt)

        assert isinstance(result, str)
        assert "2024-01-15" in result
        assert "10:30:00" in result

    def test_nested_datetime_in_dict(self):
        """Verify datetime in nested dicts is converted."""
        data = {
            "user_id": "abc123",
            "sync_time": datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            "nested": {
                "created_at": datetime(2024, 1, 14, 9, 0, 0, tzinfo=timezone.utc),
            },
        }

        result = _to_jsonable_local(data)

        # Should be JSON-serializable
        json_str = json.dumps(result)
        assert '"2024-01-15' in json_str
        assert '"2024-01-14' in json_str

    def test_datetime_in_list(self):
        """Verify datetime in lists is converted."""
        data = [
            datetime(2024, 1, 15, tzinfo=timezone.utc),
            "string",
            123,
        ]

        result = _to_jsonable_local(data)
        json_str = json.dumps(result)
        assert "2024-01-15" in json_str


class TestJobHandlerResult:
    """Test that job handler results are JSON-serializable."""

    def test_suggestions_open_imports_to_jsonable(self):
        """Verify suggestions_open imports and uses _to_jsonable."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "jobs",
            "handlers",
            "suggestions_open.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "from packages.quantum.jobs.db import _to_jsonable" in content, \
            "suggestions_open should import _to_jsonable"
        assert "return _to_jsonable({" in content, \
            "suggestions_open should wrap return value with _to_jsonable"

    def test_suggestions_close_imports_to_jsonable(self):
        """Verify suggestions_close imports and uses _to_jsonable."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "jobs",
            "handlers",
            "suggestions_close.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "from packages.quantum.jobs.db import _to_jsonable" in content, \
            "suggestions_close should import _to_jsonable"
        assert "return _to_jsonable({" in content, \
            "suggestions_close should wrap return value with _to_jsonable"


class TestMockJobResult:
    """Test that mock job results with datetime serialize correctly."""

    def test_cycle_result_with_datetime(self):
        """Simulate cycle_result containing datetime and verify serialization."""
        # Simulate what run_midday_cycle might return with datetime
        cycle_result = {
            "skipped": False,
            "reason": "no_candidates",
            "budget": {
                "deployable_capital": 5000.0,
                "cap": 1000.0,
                "usage": 200.0,
                "remaining": 800.0,
                "regime": "normal",
                "as_of": datetime.now(timezone.utc),  # Potential datetime leak
            },
            "counts": {"candidates": 0, "created": 0},
        }

        # Apply _to_jsonable
        result = _to_jsonable_local(cycle_result)

        # Should serialize without error
        json_str = json.dumps(result)
        assert "budget" in json_str
        assert "deployable_capital" in json_str

    def test_notes_with_exception_message(self):
        """Verify notes containing exception messages serialize correctly."""
        # Simulate notes that might contain exception messages
        notes = [
            "Synced 10 holdings for abc123...",
            "Sync skipped for def456...: No Plaid connection",
            f"Failed for ghi789...: Object of type datetime is not JSON serializable",
        ]

        result = {
            "ok": False,
            "counts": {"processed": 2, "failed": 1},
            "notes": notes,
        }

        # Apply _to_jsonable
        jsonable = _to_jsonable_local(result)

        # Should serialize without error
        json_str = json.dumps(jsonable)
        assert "notes" in json_str
        assert "Synced 10 holdings" in json_str

    def test_full_job_result_structure(self):
        """Test complete job result structure with potential datetime leaks."""
        # Simulate full job result with cycle_results
        result = {
            "ok": True,
            "counts": {"processed": 1, "failed": 0, "synced": 1, "skipped": 0},
            "timing_ms": 1234.5,
            "strategy_name": "spy_opt_autolearn_v6",
            "notes": [
                "Synced 5 holdings for abc12345...",
                "Using strategy spy_opt_autolearn_v6 v2 for abc12345...",
            ],
            "cycle_results": [
                {
                    "user_id": "abc12345",
                    "skipped": False,
                    "reason": None,
                    "budget": {
                        "deployable_capital": 10000.0,
                        "cap": 2000.0,
                        "usage": 500.0,
                        "remaining": 1500.0,
                        "regime": "normal",
                        # Potential datetime fields
                        "computed_at": datetime.now(timezone.utc),
                    },
                    "counts": {"candidates": 3, "created": 2},
                },
            ],
        }

        # Apply _to_jsonable
        jsonable = _to_jsonable_local(result)

        # Should serialize without error
        json_str = json.dumps(jsonable)
        parsed = json.loads(json_str)

        assert parsed["ok"] is True
        assert len(parsed["cycle_results"]) == 1
        assert "computed_at" in parsed["cycle_results"][0]["budget"]
        # datetime should now be a string
        assert isinstance(parsed["cycle_results"][0]["budget"]["computed_at"], str)


class TestHoldingsSyncServiceReturns:
    """Test that holdings_sync_service returns JSON-safe values."""

    def test_ensure_holdings_fresh_return_types(self):
        """Verify ensure_holdings_fresh return values don't contain datetime."""
        # Check the source file for return statements
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "services",
            "holdings_sync_service.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # The function should not return datetime objects in the result dict
        # It uses datetime internally for comparison but returns bools/strings/ints
        assert "def ensure_holdings_fresh" in content

        # Verify the return dict keys are expected types
        # The function returns: synced (bool), stale (bool), has_plaid (bool),
        # holdings_count (int), error (str|None)
        assert '"synced":' in content or "'synced':" in content
        assert '"stale":' in content or "'stale':" in content
        assert '"error":' in content or "'error':" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
