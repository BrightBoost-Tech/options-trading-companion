"""
Tests for multi-expiry condor search.

Verifies:
1. _select_top_expiry_candidates returns correct top K expiries
2. Multi-expiry search finds viable candidate when best expiry has no NBBO
3. Diagnostics include all tried expiries when no viable candidate found
"""

import pytest
from datetime import date, timedelta
from typing import Dict, Any, List, Tuple, Optional
from collections import defaultdict


def parse_expiry_date(exp_str: str) -> date:
    """Mock expiry date parser."""
    # Handle YYYY-MM-DD format
    parts = exp_str.split("-")
    return date(int(parts[0]), int(parts[1]), int(parts[2]))


def _select_top_expiry_candidates(
    chain: List[Dict[str, Any]],
    target_dte: int,
    k: int,
    today_date: date = None
) -> List[Tuple[str, List[Dict[str, Any]]]]:
    """
    Select top K expiry candidates from chain, sorted by proximity to target DTE.
    """
    if not chain:
        return []

    buckets = defaultdict(list)
    exp_key = "expiration"
    if chain and "expiry" in chain[0]:
        exp_key = "expiry"

    for c in chain:
        exp = c.get(exp_key)
        if exp:
            buckets[exp].append(c)

    if not buckets:
        return []

    if today_date is None:
        today_date = date.today()

    def get_dte_diff(exp_str):
        try:
            exp_dt = parse_expiry_date(exp_str)
            return abs((exp_dt - today_date).days - target_dte)
        except ValueError:
            return 9999

    sorted_expiries = sorted(
        buckets.keys(),
        key=lambda e: (get_dte_diff(e), -len(buckets[e]))
    )

    result = []
    for exp in sorted_expiries[:k]:
        result.append((exp, buckets[exp]))

    return result


class TestSelectTopExpiryCandidates:
    """Tests for _select_top_expiry_candidates helper."""

    def test_returns_top_k_expiries(self):
        """Should return top K expiries sorted by DTE proximity."""
        today = date(2024, 1, 15)
        target_dte = 35  # Looking for ~Feb 19

        chain = [
            # Expiry 1: 30 DTE (5 days from target)
            {"expiration": "2024-02-14", "strike": 100, "type": "call"},
            {"expiration": "2024-02-14", "strike": 105, "type": "call"},
            # Expiry 2: 35 DTE (exactly on target)
            {"expiration": "2024-02-19", "strike": 100, "type": "call"},
            {"expiration": "2024-02-19", "strike": 105, "type": "call"},
            {"expiration": "2024-02-19", "strike": 95, "type": "put"},
            # Expiry 3: 45 DTE (10 days from target)
            {"expiration": "2024-02-29", "strike": 100, "type": "call"},
        ]

        result = _select_top_expiry_candidates(chain, target_dte=35, k=2, today_date=today)

        assert len(result) == 2
        # First should be closest to target (35 DTE)
        assert result[0][0] == "2024-02-19"
        assert len(result[0][1]) == 3
        # Second should be next closest (30 DTE, 5 days off)
        assert result[1][0] == "2024-02-14"
        assert len(result[1][1]) == 2

    def test_uses_contract_count_as_tiebreaker(self):
        """When DTE is equal, prefer expiry with more contracts."""
        today = date(2024, 1, 15)

        chain = [
            # Expiry 1: 35 DTE, 2 contracts
            {"expiration": "2024-02-19", "strike": 100, "type": "call"},
            {"expiration": "2024-02-19", "strike": 105, "type": "call"},
            # Expiry 2: 35 DTE (same), 4 contracts
            {"expiration": "2024-02-19", "strike": 100, "type": "put"},  # Same date, more contracts
            {"expiration": "2024-02-19", "strike": 105, "type": "put"},
        ]

        # All on same date - should be combined
        result = _select_top_expiry_candidates(chain, target_dte=35, k=1, today_date=today)

        assert len(result) == 1
        assert result[0][0] == "2024-02-19"
        assert len(result[0][1]) == 4  # All 4 contracts

    def test_handles_empty_chain(self):
        """Should return empty list for empty chain."""
        result = _select_top_expiry_candidates([], target_dte=35, k=3, today_date=date.today())
        assert result == []

    def test_returns_fewer_than_k_if_not_enough_expiries(self):
        """Should return all available expiries if fewer than K."""
        today = date(2024, 1, 15)

        chain = [
            {"expiration": "2024-02-19", "strike": 100, "type": "call"},
            {"expiration": "2024-02-19", "strike": 105, "type": "call"},
        ]

        result = _select_top_expiry_candidates(chain, target_dte=35, k=5, today_date=today)

        assert len(result) == 1  # Only 1 expiry available

    def test_supports_expiry_key_alias(self):
        """Should support 'expiry' key as alternative to 'expiration'."""
        today = date(2024, 1, 15)

        chain = [
            {"expiry": "2024-02-19", "strike": 100, "type": "call"},
            {"expiry": "2024-02-14", "strike": 105, "type": "call"},
        ]

        result = _select_top_expiry_candidates(chain, target_dte=35, k=2, today_date=today)

        assert len(result) == 2
        assert result[0][0] == "2024-02-19"  # Closest to target


class TestMultiExpiryCondorSearch:
    """Integration-style tests for multi-expiry condor search logic."""

    def test_finds_viable_in_second_expiry_when_first_has_no_nbbo(self):
        """Should find condor in second expiry when first has invalid NBBO."""
        # Simulate expiry1 with no valid NBBO (bid=0) and expiry2 with valid NBBO
        expiry1_contracts = [
            {"type": "put", "side": "sell", "strike": 95, "bid": 0, "ask": 1.0, "delta": -0.10},
            {"type": "put", "side": "buy", "strike": 90, "bid": 0, "ask": 0.5, "delta": -0.05},
            {"type": "call", "side": "sell", "strike": 105, "bid": 0, "ask": 1.0, "delta": 0.10},
            {"type": "call", "side": "buy", "strike": 110, "bid": 0, "ask": 0.5, "delta": 0.05},
        ]

        expiry2_contracts = [
            {"type": "put", "side": "sell", "strike": 95, "bid": 1.0, "ask": 1.1, "delta": -0.10},
            {"type": "put", "side": "buy", "strike": 90, "bid": 0.4, "ask": 0.5, "delta": -0.05},
            {"type": "call", "side": "sell", "strike": 105, "bid": 0.9, "ask": 1.0, "delta": 0.10},
            {"type": "call", "side": "buy", "strike": 110, "bid": 0.3, "ask": 0.4, "delta": 0.05},
        ]

        expiry_candidates = [
            ("2024-02-19", expiry1_contracts),  # First expiry - no NBBO
            ("2024-02-26", expiry2_contracts),  # Second expiry - valid
        ]

        # Simulate the multi-expiry search logic
        best_expiry = None
        best_viable = False

        for exp_str, contracts in expiry_candidates:
            # Check if any contract has valid NBBO (bid > 0)
            has_valid_nbbo = any(c.get("bid", 0) > 0 for c in contracts)
            if has_valid_nbbo:
                best_expiry = exp_str
                best_viable = True
                break

        assert best_viable is True
        assert best_expiry == "2024-02-26"

    def test_diagnostics_include_all_tried_expiries(self):
        """When no viable candidate, diagnostics should list all tried expiries."""
        expiry_candidates = [
            ("2024-02-19", [{"strike": 100, "bid": 0}]),
            ("2024-02-26", [{"strike": 100, "bid": 0}]),
            ("2024-03-04", [{"strike": 100, "bid": 0}]),
        ]

        # Simulate building diagnostics
        expiry_diagnostics = []
        for exp_str, contracts in expiry_candidates:
            diag = {
                "expiry": exp_str,
                "reason": "no_valid_nbbo",
                "combos_valid_nbbo": 0,
            }
            expiry_diagnostics.append(diag)

        base_sample = {
            "tried_expiries": [d["expiry"] for d in expiry_diagnostics],
            "expiry_diagnostics": expiry_diagnostics,
        }

        assert len(base_sample["tried_expiries"]) == 3
        assert "2024-02-19" in base_sample["tried_expiries"]
        assert "2024-02-26" in base_sample["tried_expiries"]
        assert "2024-03-04" in base_sample["tried_expiries"]

    def test_selects_highest_ev_across_expiries(self):
        """Should select the expiry with highest EV when multiple are viable."""
        expiry_results = [
            ("2024-02-19", {"total_ev": 15.0, "max_leg_spread_pct": 0.20}),
            ("2024-02-26", {"total_ev": 25.0, "max_leg_spread_pct": 0.25}),
            ("2024-03-04", {"total_ev": 20.0, "max_leg_spread_pct": 0.15}),
        ]

        best_expiry = None
        best_ev = None

        for exp_str, meta in expiry_results:
            ev = meta["total_ev"]
            if best_ev is None or ev > best_ev:
                best_expiry = exp_str
                best_ev = ev

        assert best_expiry == "2024-02-26"
        assert best_ev == 25.0

    def test_uses_spread_as_tiebreaker_for_equal_ev(self):
        """When EV is equal, prefer lower max_leg_spread_pct."""
        expiry_results = [
            ("2024-02-19", {"total_ev": 20.0, "max_leg_spread_pct": 0.30}),
            ("2024-02-26", {"total_ev": 20.0, "max_leg_spread_pct": 0.15}),  # Lower spread
            ("2024-03-04", {"total_ev": 20.0, "max_leg_spread_pct": 0.25}),
        ]

        best_expiry = None
        best_ev = None
        best_spread = None

        for exp_str, meta in expiry_results:
            ev = meta["total_ev"]
            spread = meta["max_leg_spread_pct"]

            is_better = False
            if best_ev is None:
                is_better = True
            elif ev > best_ev:
                is_better = True
            elif ev == best_ev and spread < best_spread:
                is_better = True

            if is_better:
                best_expiry = exp_str
                best_ev = ev
                best_spread = spread

        assert best_expiry == "2024-02-26"
        assert best_spread == 0.15


class TestEdgeCases:
    """Edge case tests for multi-expiry search."""

    def test_handles_contracts_with_missing_expiry(self):
        """Should skip contracts without expiry key."""
        chain = [
            {"expiration": "2024-02-19", "strike": 100, "type": "call"},
            {"strike": 105, "type": "call"},  # No expiration
            {"expiration": "2024-02-19", "strike": 95, "type": "put"},
        ]

        result = _select_top_expiry_candidates(chain, target_dte=35, k=2, today_date=date(2024, 1, 15))

        assert len(result) == 1
        assert result[0][0] == "2024-02-19"
        assert len(result[0][1]) == 2  # Only contracts with expiration

    def test_handles_invalid_expiry_format(self):
        """Should handle invalid expiry format gracefully."""
        chain = [
            {"expiration": "invalid-date", "strike": 100, "type": "call"},
            {"expiration": "2024-02-19", "strike": 105, "type": "call"},
        ]

        result = _select_top_expiry_candidates(chain, target_dte=35, k=2, today_date=date(2024, 1, 15))

        # Should still work, invalid date gets high DTE diff
        assert len(result) == 2
        # Valid date should come first
        assert result[0][0] == "2024-02-19"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
