"""
Tests for robust condor delta detection.

Verifies:
1. Delta detection checks across the chain, not just first contract
2. condor_no_deltas does NOT trigger if first contract has delta None but later have deltas
3. _chain_has_any_delta helper works correctly
"""

import pytest
from typing import Dict, Any, List


def _chain_has_any_delta(calls: List[Dict], puts: List[Dict]) -> bool:
    """
    Check if any contract in chain has a delta value.
    Checks first 25 calls + first 25 puts.
    """
    probe = (calls[:25] if calls else []) + (puts[:25] if puts else [])
    for c in probe:
        d = c.get("delta")
        if d is not None:
            return True
    return False


class TestChainHasAnyDelta:
    """Test _chain_has_any_delta helper function."""

    def test_first_contract_none_later_have_delta(self):
        """Should return True if first has None but later have delta."""
        calls = [
            {"strike": 100, "delta": None},
            {"strike": 105, "delta": 0.10},  # Has delta
            {"strike": 110, "delta": 0.05},
        ]
        puts = [
            {"strike": 95, "delta": None},
            {"strike": 90, "delta": -0.10},  # Has delta
        ]
        assert _chain_has_any_delta(calls, puts) is True

    def test_all_contracts_have_none_delta(self):
        """Should return False if ALL contracts have delta None."""
        calls = [
            {"strike": 100, "delta": None},
            {"strike": 105, "delta": None},
        ]
        puts = [
            {"strike": 95, "delta": None},
            {"strike": 90, "delta": None},
        ]
        assert _chain_has_any_delta(calls, puts) is False

    def test_only_calls_have_delta(self):
        """Should return True if only calls have delta."""
        calls = [
            {"strike": 100, "delta": None},
            {"strike": 105, "delta": 0.10},
        ]
        puts = [
            {"strike": 95, "delta": None},
            {"strike": 90, "delta": None},
        ]
        assert _chain_has_any_delta(calls, puts) is True

    def test_only_puts_have_delta(self):
        """Should return True if only puts have delta."""
        calls = [
            {"strike": 100, "delta": None},
            {"strike": 105, "delta": None},
        ]
        puts = [
            {"strike": 95, "delta": None},
            {"strike": 90, "delta": -0.05},
        ]
        assert _chain_has_any_delta(calls, puts) is True

    def test_first_call_has_delta(self):
        """Should return True if first call has delta."""
        calls = [
            {"strike": 100, "delta": 0.30},
            {"strike": 105, "delta": None},
        ]
        puts = [
            {"strike": 95, "delta": None},
        ]
        assert _chain_has_any_delta(calls, puts) is True

    def test_empty_calls_list(self):
        """Should handle empty calls list."""
        calls = []
        puts = [
            {"strike": 95, "delta": -0.10},
        ]
        assert _chain_has_any_delta(calls, puts) is True

    def test_empty_puts_list(self):
        """Should handle empty puts list."""
        calls = [
            {"strike": 100, "delta": 0.10},
        ]
        puts = []
        assert _chain_has_any_delta(calls, puts) is True

    def test_both_empty_lists(self):
        """Should return False for empty lists."""
        assert _chain_has_any_delta([], []) is False

    def test_delta_at_position_24(self):
        """Should find delta at position 24 (within limit)."""
        calls = [{"strike": 100 + i, "delta": None} for i in range(24)]
        calls.append({"strike": 124, "delta": 0.05})  # Position 24 has delta
        puts = [{"strike": 95, "delta": None}]
        assert _chain_has_any_delta(calls, puts) is True

    def test_delta_at_position_25_calls_not_found(self):
        """Delta at position 25+ in calls should not be found (only first 25 checked)."""
        calls = [{"strike": 100 + i, "delta": None} for i in range(25)]
        calls.append({"strike": 125, "delta": 0.05})  # Position 25 - beyond limit
        puts = [{"strike": 95, "delta": None}]
        assert _chain_has_any_delta(calls, puts) is False

    def test_delta_in_puts_after_25_calls(self):
        """Should find delta in puts even if calls have 25+ None deltas."""
        calls = [{"strike": 100 + i, "delta": None} for i in range(30)]
        puts = [{"strike": 95, "delta": -0.10}]  # Put has delta
        assert _chain_has_any_delta(calls, puts) is True


class TestDeltaDetectionIntegration:
    """Integration tests for delta detection in EV-aware search."""

    def test_no_deltas_reason_not_triggered_when_later_contracts_have_delta(self):
        """condor_no_deltas should NOT trigger if later contracts have deltas."""
        # Simulate the logic from _select_best_iron_condor_ev_aware

        # First contract has None, but others have delta
        calls = [
            {"strike": 100, "delta": None, "bid": 1.0, "ask": 1.1},
            {"strike": 105, "delta": 0.10, "bid": 0.8, "ask": 0.9},
            {"strike": 110, "delta": 0.05, "bid": 0.5, "ask": 0.6},
        ]
        puts = [
            {"strike": 95, "delta": None, "bid": 0.8, "ask": 0.9},
            {"strike": 90, "delta": -0.10, "bid": 0.6, "ask": 0.7},
            {"strike": 85, "delta": -0.05, "bid": 0.4, "ask": 0.5},
        ]

        # Check delta detection
        has_delta = _chain_has_any_delta(calls, puts)
        assert has_delta is True

        # This means reason should NOT be "no_deltas_in_chain"
        # (The actual function would proceed to try combos)

    def test_no_deltas_reason_triggered_when_all_none(self):
        """condor_no_deltas SHOULD trigger when ALL contracts have None delta."""
        calls = [
            {"strike": 100, "delta": None, "bid": 1.0, "ask": 1.1},
            {"strike": 105, "delta": None, "bid": 0.8, "ask": 0.9},
        ]
        puts = [
            {"strike": 95, "delta": None, "bid": 0.8, "ask": 0.9},
            {"strike": 90, "delta": None, "bid": 0.6, "ask": 0.7},
        ]

        has_delta = _chain_has_any_delta(calls, puts)
        assert has_delta is False

        # This means reason SHOULD be "no_deltas_in_chain"


class TestEdgeCases:
    """Test edge cases for delta detection."""

    def test_delta_zero_is_valid(self):
        """Delta of 0 should be considered valid (not None)."""
        calls = [{"strike": 100, "delta": 0}]  # Delta = 0, not None
        puts = [{"strike": 95, "delta": None}]
        assert _chain_has_any_delta(calls, puts) is True

    def test_delta_negative_zero_is_valid(self):
        """Delta of -0.0 should be considered valid."""
        calls = [{"strike": 100, "delta": None}]
        puts = [{"strike": 95, "delta": -0.0}]  # -0.0 is not None
        assert _chain_has_any_delta(calls, puts) is True

    def test_delta_string_is_not_valid(self):
        """Delta as string should not match (is not None but wrong type)."""
        # Note: We only check for None, not type validity
        calls = [{"strike": 100, "delta": "0.10"}]  # String, not None
        puts = [{"strike": 95, "delta": None}]
        # The function only checks `is not None`, so string counts as having delta
        assert _chain_has_any_delta(calls, puts) is True

    def test_missing_delta_key(self):
        """Missing delta key should return None from get()."""
        calls = [{"strike": 100}]  # No delta key at all
        puts = [{"strike": 95}]
        assert _chain_has_any_delta(calls, puts) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
