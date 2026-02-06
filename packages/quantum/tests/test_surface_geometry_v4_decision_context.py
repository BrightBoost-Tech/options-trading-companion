"""
Tests for surface_geometry_v4 DecisionContext integration.

Ensures record_surface_to_context uses the correct DecisionContext API
and includes content hash in metadata.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

from packages.quantum.services.surface_geometry_v4 import (
    build_arb_free_surface,
    record_surface_to_context,
    SURFACE_VERSION,
)

# Patch target: where get_current_decision_context is imported FROM
PATCH_TARGET = "packages.quantum.services.replay.decision_context.get_current_decision_context"


class TestRecordSurfaceToContext:
    """Tests for record_surface_to_context function."""

    @pytest.fixture
    def sample_chain(self):
        """Minimal valid option chain for testing."""
        expiry = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%d")
        return [
            {"strike": 95.0, "iv": 0.22, "expiry": expiry, "right": "call", "greeks": {"delta": 0.65}},
            {"strike": 100.0, "iv": 0.20, "expiry": expiry, "right": "call", "greeks": {"delta": 0.5}},
            {"strike": 105.0, "iv": 0.22, "expiry": expiry, "right": "call", "greeks": {"delta": 0.35}},
        ]

    @pytest.fixture
    def valid_surface_result(self, sample_chain):
        """Build a valid surface result for testing."""
        return build_arb_free_surface(
            chain=sample_chain,
            spot=100.0,
            symbol="SPY",
        )

    def test_record_input_called_with_correct_args(self, valid_surface_result):
        """Verifies record_input is called with correct key, snapshot_type, and metadata."""
        # Create a mock context with record_input method
        mock_ctx = MagicMock()
        mock_ctx.record_input = MagicMock(return_value="mock_hash")

        with patch(PATCH_TARGET, return_value=mock_ctx):
            # This should NOT throw TypeError
            record_surface_to_context("SPY", valid_surface_result)

        # Verify record_input was called exactly once
        mock_ctx.record_input.assert_called_once()

        # Get the call arguments
        call_kwargs = mock_ctx.record_input.call_args.kwargs

        # Verify key
        assert call_kwargs["key"] == "SPY:surface:v4"

        # Verify snapshot_type
        assert call_kwargs["snapshot_type"] == "surface"

        # Verify payload is a dict
        assert isinstance(call_kwargs["payload"], dict)
        assert call_kwargs["payload"]["is_valid"] is True

        # Verify metadata contains content_hash
        metadata = call_kwargs["metadata"]
        assert metadata is not None
        assert "content_hash" in metadata
        assert metadata["content_hash"] == valid_surface_result.content_hash
        assert metadata["version"] == SURFACE_VERSION
        assert "signature_status" in metadata
        assert "warnings" in metadata
        assert "errors" in metadata

    def test_no_type_error_on_record(self, valid_surface_result):
        """Ensures no TypeError is thrown when recording a valid surface."""
        mock_ctx = MagicMock()
        mock_ctx.record_input = MagicMock(return_value="mock_hash")

        with patch(PATCH_TARGET, return_value=mock_ctx):
            # This should complete without exception
            try:
                record_surface_to_context("SPY", valid_surface_result)
            except TypeError as e:
                pytest.fail(f"TypeError raised: {e}")

    def test_no_record_when_context_is_none(self, valid_surface_result):
        """Verifies no action when DecisionContext is not active."""
        with patch(PATCH_TARGET, return_value=None):
            # Should complete silently without error
            record_surface_to_context("SPY", valid_surface_result)

    def test_no_record_when_surface_invalid(self, sample_chain):
        """Verifies no record attempt when surface is invalid."""
        # Build an invalid surface (empty chain)
        invalid_result = build_arb_free_surface(
            chain=[],
            spot=100.0,
            symbol="SPY",
        )

        mock_ctx = MagicMock()
        mock_ctx.record_input = MagicMock()

        with patch(PATCH_TARGET, return_value=mock_ctx):
            record_surface_to_context("SPY", invalid_result)

        # record_input should NOT be called
        mock_ctx.record_input.assert_not_called()

    def test_no_record_when_surface_is_none(self):
        """Verifies no record attempt when surface result has no surface."""
        from packages.quantum.services.surface_geometry_v4 import SurfaceResult

        # Create a result with is_valid=True but surface=None (edge case)
        edge_result = SurfaceResult(
            is_valid=True,
            surface=None,
            content_hash="abc123",
        )

        mock_ctx = MagicMock()
        mock_ctx.record_input = MagicMock()

        with patch(PATCH_TARGET, return_value=mock_ctx):
            record_surface_to_context("SPY", edge_result)

        # record_input should NOT be called
        mock_ctx.record_input.assert_not_called()

    def test_metadata_truncates_warnings_and_errors(self, sample_chain):
        """Verifies warnings and errors are truncated to max 5 items."""
        from packages.quantum.services.surface_geometry_v4 import SurfaceResult, ArbFreeSurface

        # Create a surface result with many warnings
        surface = ArbFreeSurface(
            symbol="SPY",
            spot=100.0,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            as_of_ts="2024-01-01T00:00:00.000Z",
            smiles=[],
        )

        result_with_many_warnings = SurfaceResult(
            surface=surface,
            is_valid=True,
            content_hash="test_hash",
            warnings=["w1", "w2", "w3", "w4", "w5", "w6", "w7"],
            errors=["e1", "e2", "e3", "e4", "e5", "e6"],
        )

        mock_ctx = MagicMock()
        mock_ctx.record_input = MagicMock(return_value="mock_hash")

        with patch(PATCH_TARGET, return_value=mock_ctx):
            record_surface_to_context("SPY", result_with_many_warnings)

        metadata = mock_ctx.record_input.call_args.kwargs["metadata"]
        assert len(metadata["warnings"]) == 5
        assert len(metadata["errors"]) == 5

    def test_exception_is_caught_and_logged(self, valid_surface_result):
        """Verifies exceptions are caught and logged, not raised."""
        mock_ctx = MagicMock()
        mock_ctx.record_input = MagicMock(side_effect=Exception("DB error"))

        with patch(PATCH_TARGET, return_value=mock_ctx):
            # Should not raise, just log warning
            try:
                record_surface_to_context("SPY", valid_surface_result)
            except Exception as e:
                pytest.fail(f"Exception was not caught: {e}")


class TestRecordSurfaceReplayDisabled:
    """Tests for behavior when replay is disabled."""

    def test_noop_when_replay_disabled(self):
        """Verifies record is a no-op when REPLAY_ENABLE is not set."""
        from packages.quantum.services.surface_geometry_v4 import SurfaceResult, ArbFreeSurface

        surface = ArbFreeSurface(
            symbol="SPY",
            spot=100.0,
            risk_free_rate=0.05,
            dividend_yield=0.0,
            as_of_ts="2024-01-01T00:00:00.000Z",
            smiles=[],
        )

        result = SurfaceResult(
            surface=surface,
            is_valid=True,
            content_hash="test_hash",
        )

        # When get_current_decision_context returns None (replay disabled),
        # function should return early
        with patch(PATCH_TARGET, return_value=None):
            # Should complete silently
            record_surface_to_context("SPY", result)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
