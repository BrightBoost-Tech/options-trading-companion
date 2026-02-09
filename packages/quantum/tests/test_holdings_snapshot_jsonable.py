"""
Tests for holdings snapshot JSON serialization safety.

Verifies fix for:
  Object of type datetime is not JSON serializable

Ensures:
1. Holdings with datetime fields are JSON-serializable via _to_jsonable
2. Portfolio snapshot insert path uses _to_jsonable
"""

import pytest
import json
import os
from datetime import datetime, timezone, date
from decimal import Decimal


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
    if isinstance(obj, Decimal):
        return float(obj)
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


class TestHoldingsJsonSafety:
    """Test that holdings data is JSON-serializable."""

    def test_holding_with_datetime_serializes(self):
        """Verify holding containing datetime field serializes to JSON."""
        holding = {
            "symbol": "AAPL",
            "quantity": 100,
            "cost_basis": 15000.0,
            "current_price": 175.50,
            "last_updated": datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            "asset_type": "EQUITY",
        }

        # Apply _to_jsonable
        result = _to_jsonable_local(holding)

        # Should serialize without error
        json_str = json.dumps(result)
        assert "AAPL" in json_str
        assert "2024-01-15" in json_str

        # datetime should now be a string
        assert isinstance(result["last_updated"], str)

    def test_holdings_list_with_datetime_serializes(self):
        """Verify list of holdings with datetime fields serializes."""
        holdings = [
            {
                "symbol": "AAPL",
                "quantity": 100,
                "last_updated": datetime(2024, 1, 15, tzinfo=timezone.utc),
            },
            {
                "symbol": "MSFT",
                "quantity": 50,
                "last_updated": datetime(2024, 1, 14, tzinfo=timezone.utc),
            },
        ]

        result = _to_jsonable_local(holdings)

        # Should serialize without error
        json_str = json.dumps(result)
        assert "AAPL" in json_str
        assert "MSFT" in json_str
        assert "2024-01-15" in json_str
        assert "2024-01-14" in json_str

    def test_nested_datetime_in_holdings_metadata(self):
        """Verify nested datetime in holdings metadata serializes."""
        holding = {
            "symbol": "SPY",
            "quantity": 10,
            "metadata": {
                "last_sync": datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
                "positions": [
                    {
                        "opened_at": datetime(2024, 1, 10, tzinfo=timezone.utc),
                        "strike": 450.0,
                    }
                ],
            },
        }

        result = _to_jsonable_local(holding)
        json_str = json.dumps(result)

        # Nested datetime should be converted
        assert "2024-01-15" in json_str
        assert "2024-01-10" in json_str

    def test_decimal_in_holdings_serializes(self):
        """Verify Decimal values in holdings serialize to float."""
        holding = {
            "symbol": "TSLA",
            "quantity": 25,
            "cost_basis": Decimal("4523.75"),
            "current_value": Decimal("5125.00"),
        }

        result = _to_jsonable_local(holding)
        json_str = json.dumps(result)

        assert "4523.75" in json_str
        assert isinstance(result["cost_basis"], float)


class TestHoldingsSyncServiceUsesToJsonable:
    """Verify holdings_sync_service.py uses _to_jsonable for inserts."""

    def test_holdings_sync_service_imports_to_jsonable(self):
        """Verify holdings_sync_service imports _to_jsonable."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "services",
            "holdings_sync_service.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "from packages.quantum.jobs.db import _to_jsonable" in content, \
            "holdings_sync_service should import _to_jsonable"

    def test_holdings_sync_service_wraps_holdings(self):
        """Verify holdings are wrapped with _to_jsonable before insert."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "services",
            "holdings_sync_service.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Check that holdings is wrapped with _to_jsonable
        assert '"holdings": _to_jsonable(holdings)' in content, \
            "holdings should be wrapped with _to_jsonable"


class TestPortfolioSnapshotStructure:
    """Test complete portfolio snapshot structure for JSON safety."""

    def test_full_snapshot_serializes(self):
        """Test that a full portfolio snapshot structure serializes."""
        snapshot = {
            "user_id": "abc12345-1234-1234-1234-123456789abc",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "data_source": "plaid",
            "holdings": [
                {
                    "symbol": "AAPL",
                    "quantity": 100,
                    "cost_basis": 15000.0,
                    "current_price": 175.50,
                    "last_updated": datetime(2024, 1, 15, tzinfo=timezone.utc),
                    "asset_type": "EQUITY",
                },
                {
                    "symbol": "SPY",
                    "quantity": 50,
                    "cost_basis": 22500.0,
                    "current_price": 475.25,
                    "last_updated": datetime(2024, 1, 15, tzinfo=timezone.utc),
                    "asset_type": "EQUITY",
                },
            ],
            "buying_power": 5000.0,
            "risk_metrics": {
                "accounts_synced": 2,
                "total_value": 50000.0,
                "computed_at": datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            },
        }

        # Apply _to_jsonable to holdings and risk_metrics as the service does
        snapshot["holdings"] = _to_jsonable_local(snapshot["holdings"])
        snapshot["risk_metrics"] = _to_jsonable_local(snapshot["risk_metrics"])

        # Should serialize without error
        json_str = json.dumps(snapshot)
        parsed = json.loads(json_str)

        assert parsed["data_source"] == "plaid"
        assert len(parsed["holdings"]) == 2
        assert parsed["holdings"][0]["symbol"] == "AAPL"
        # datetime should be converted to string
        assert isinstance(parsed["holdings"][0]["last_updated"], str)
        assert isinstance(parsed["risk_metrics"]["computed_at"], str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
