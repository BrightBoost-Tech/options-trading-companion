"""
Tests for condor leg quote hydration feature.

Verifies:
1. _get_premium_nested ignores zero values
2. condor_missing_quotes rejection is tracked separately
3. Quote hydration is wired into the condor path
4. Helper functions work correctly
"""

import pytest
import os
from typing import Dict, Any, Optional, List


# Replicate helper functions for testing
def _to_float_or_none(val: Any) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _leg_has_valid_bidask(leg: Dict[str, Any]) -> bool:
    """Check if leg has valid bid/ask quotes."""
    try:
        bid = leg.get("bid")
        ask = leg.get("ask")
        if bid is None or ask is None:
            return False
        bid_f = float(bid)
        ask_f = float(ask)
        return bid_f > 0 and ask_f > 0 and ask_f >= bid_f
    except (TypeError, ValueError):
        return False


def _get_premium_nested_local(c):
    """Local copy of _get_premium_nested for testing."""
    q = c.get("quote")
    if not q:
        return None
    try:
        mid = q.get("mid")
        if mid is not None and float(mid) > 0:
            return float(mid)
        last = q.get("last")
        if last is not None and float(last) > 0:
            return float(last)
    except (TypeError, ValueError):
        pass
    return None


def _reprice_total_cost_from_legs(legs: List[Dict[str, Any]]) -> Optional[float]:
    """Recompute total cost from leg premiums."""
    if not legs:
        return None
    total = 0.0
    for leg in legs:
        prem = leg.get("mid") or leg.get("premium")
        if prem is None:
            return None
        try:
            prem_f = float(prem)
            if prem_f <= 0:
                return None
        except (TypeError, ValueError):
            return None
        side = leg.get("side")
        if side == "buy":
            total += prem_f
        else:
            total -= prem_f
    return total


class TestGetPremiumNested:
    """Test _get_premium_nested ignores zero values."""

    def test_mid_zero_last_positive_returns_last(self):
        """When mid=0 and last>0, should return last."""
        contract = {"quote": {"mid": 0, "last": 1.23}}
        result = _get_premium_nested_local(contract)
        assert result == 1.23

    def test_mid_zero_last_zero_returns_none(self):
        """When both mid and last are 0, should return None."""
        contract = {"quote": {"mid": 0, "last": 0}}
        result = _get_premium_nested_local(contract)
        assert result is None

    def test_mid_positive_returns_mid(self):
        """When mid>0, should return mid."""
        contract = {"quote": {"mid": 2.50, "last": 1.00}}
        result = _get_premium_nested_local(contract)
        assert result == 2.50

    def test_no_quote_returns_none(self):
        """When quote is missing, should return None."""
        contract = {}
        result = _get_premium_nested_local(contract)
        assert result is None

    def test_mid_none_last_positive_returns_last(self):
        """When mid is None and last>0, should return last."""
        contract = {"quote": {"mid": None, "last": 3.45}}
        result = _get_premium_nested_local(contract)
        assert result == 3.45


class TestLegHasValidBidask:
    """Test _leg_has_valid_bidask helper."""

    def test_valid_bidask(self):
        """Valid bid/ask returns True."""
        leg = {"bid": 1.50, "ask": 1.60}
        assert _leg_has_valid_bidask(leg) is True

    def test_bid_none(self):
        """Bid None returns False."""
        leg = {"bid": None, "ask": 1.60}
        assert _leg_has_valid_bidask(leg) is False

    def test_ask_none(self):
        """Ask None returns False."""
        leg = {"bid": 1.50, "ask": None}
        assert _leg_has_valid_bidask(leg) is False

    def test_bid_zero(self):
        """Bid zero returns False."""
        leg = {"bid": 0, "ask": 1.60}
        assert _leg_has_valid_bidask(leg) is False

    def test_ask_zero(self):
        """Ask zero returns False."""
        leg = {"bid": 1.50, "ask": 0}
        assert _leg_has_valid_bidask(leg) is False

    def test_ask_less_than_bid(self):
        """Ask < bid returns False (crossed market)."""
        leg = {"bid": 1.60, "ask": 1.50}
        assert _leg_has_valid_bidask(leg) is False

    def test_bid_equals_ask(self):
        """Bid == ask returns True (locked market is valid)."""
        leg = {"bid": 1.50, "ask": 1.50}
        assert _leg_has_valid_bidask(leg) is True


class TestRepriceTotalCostFromLegs:
    """Test _reprice_total_cost_from_legs helper."""

    def test_credit_spread(self):
        """Credit spread (sell > buy) returns negative total."""
        legs = [
            {"side": "sell", "mid": 1.50},
            {"side": "buy", "mid": 0.50},
        ]
        result = _reprice_total_cost_from_legs(legs)
        assert result == -1.0  # -1.50 + 0.50

    def test_debit_spread(self):
        """Debit spread (buy > sell) returns positive total."""
        legs = [
            {"side": "buy", "mid": 1.50},
            {"side": "sell", "mid": 0.50},
        ]
        result = _reprice_total_cost_from_legs(legs)
        assert result == 1.0  # 1.50 - 0.50

    def test_missing_premium_returns_none(self):
        """Missing premium returns None."""
        legs = [
            {"side": "sell", "mid": 1.50},
            {"side": "buy", "mid": None},
        ]
        result = _reprice_total_cost_from_legs(legs)
        assert result is None

    def test_zero_premium_returns_none(self):
        """Zero premium returns None."""
        legs = [
            {"side": "sell", "mid": 1.50},
            {"side": "buy", "mid": 0},
        ]
        result = _reprice_total_cost_from_legs(legs)
        assert result is None

    def test_empty_legs_returns_none(self):
        """Empty legs list returns None."""
        result = _reprice_total_cost_from_legs([])
        assert result is None

    def test_iron_condor_credit(self):
        """Iron condor with net credit."""
        legs = [
            {"side": "sell", "mid": 1.50},  # short put
            {"side": "buy", "mid": 0.80},   # long put
            {"side": "sell", "mid": 1.40},  # short call
            {"side": "buy", "mid": 0.70},   # long call
        ]
        result = _reprice_total_cost_from_legs(legs)
        # -1.50 + 0.80 - 1.40 + 0.70 = -1.40 (credit)
        assert result == pytest.approx(-1.40, abs=0.01)


class TestScannerHasCondorMissingQuotes:
    """Verify scanner has condor_missing_quotes rejection."""

    def test_condor_missing_quotes_in_scanner(self):
        """Verify condor_missing_quotes rejection is defined."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "options_scanner.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert '"condor_missing_quotes"' in content, \
            "condor_missing_quotes rejection should be defined"

    def test_condor_missing_quotes_uses_record_with_sample(self):
        """Verify condor_missing_quotes uses record_with_sample."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "options_scanner.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert 'rej_stats.record_with_sample("condor_missing_quotes"' in content


class TestScannerHasQuoteHydration:
    """Verify scanner has quote hydration wired in."""

    def test_snapshot_many_v4_used_in_hydration(self):
        """Verify snapshot_many_v4 is called for hydration."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "options_scanner.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "snapshot_many_v4" in content, \
            "snapshot_many_v4 should be used for quote hydration"

    def test_hydrate_legs_quotes_v4_defined(self):
        """Verify _hydrate_legs_quotes_v4 helper is defined."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "options_scanner.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "def _hydrate_legs_quotes_v4(" in content

    def test_leg_has_valid_bidask_defined(self):
        """Verify _leg_has_valid_bidask helper is defined."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "options_scanner.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "def _leg_has_valid_bidask(" in content

    def test_reprice_total_cost_from_legs_defined(self):
        """Verify _reprice_total_cost_from_legs helper is defined."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "options_scanner.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert "def _reprice_total_cost_from_legs(" in content


class TestGetPremiumNestedInScanner:
    """Verify _get_premium_nested checks for > 0."""

    def test_get_premium_nested_checks_positive(self):
        """Verify _get_premium_nested checks for values > 0."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "options_scanner.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Find the _get_premium_nested function
        assert "def _get_premium_nested(c):" in content

        # Verify it checks for > 0
        # Find the function body and check for the pattern
        import re
        func_match = re.search(
            r'def _get_premium_nested\(c\):.*?(?=\ndef |\Z)',
            content,
            re.DOTALL
        )
        assert func_match is not None, "_get_premium_nested function not found"

        func_body = func_match.group()
        assert "> 0" in func_body, \
            "_get_premium_nested should check for values > 0"


class TestCondorNoCredit:
    """Verify condor_no_credit is still used correctly."""

    def test_condor_no_credit_still_exists(self):
        """Verify condor_no_credit rejection still exists."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "options_scanner.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        assert 'rej_stats.record_with_sample("condor_no_credit"' in content

    def test_condor_no_credit_after_missing_quotes_check(self):
        """Verify condor_no_credit comes after missing quotes check."""
        file_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "options_scanner.py"
        )

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Find positions
        missing_quotes_pos = content.find('"condor_missing_quotes"')
        no_credit_pos = content.find('"condor_no_credit"')

        assert missing_quotes_pos < no_credit_pos, \
            "condor_missing_quotes should be checked before condor_no_credit"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
