"""
Tests for option quote fallback via /v3/quotes.

Verifies:
1. Fallback is attempted when v4 snapshots return empty/missing quotes
2. Legs are patched with bid/ask/mid/premium when fallback succeeds
3. Fallback metadata reports attempted/hydrated counts
4. Legs remain missing when fallback also returns no quotes
5. Only option symbols (O:) trigger fallback
"""

import pytest
from typing import Dict, Any, Optional, List
from unittest.mock import MagicMock, patch


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


def _hydrate_legs_quotes_v4_local(
    truth_layer,
    legs: List[Dict[str, Any]],
    market_data = None
) -> Dict[str, Any]:
    """
    Local copy of _hydrate_legs_quotes_v4 for testing.
    """
    if not legs:
        return {"hydrated": 0, "missing_after": [], "quality": []}

    # Collect leg symbols
    leg_syms = [leg.get("symbol") for leg in legs if leg.get("symbol")]
    if not leg_syms:
        return {"hydrated": 0, "missing_after": [], "quality": []}

    # Fetch v4 snapshots for leg tickers
    try:
        v4_snaps = truth_layer.snapshot_many_v4(leg_syms) if truth_layer else {}
    except Exception:
        v4_snaps = {}

    hydrated_count = 0
    quality_info = []

    for leg in legs:
        sym = leg.get("symbol")
        if not sym:
            continue

        snap = v4_snaps.get(sym)
        if not snap:
            continue

        # Extract quote from v4 snapshot
        q = snap.get("quote") if isinstance(snap, dict) else getattr(snap, "quote", None)
        if not q:
            continue

        updated = False

        # Update bid if missing/invalid
        q_bid = q.get("bid") if isinstance(q, dict) else getattr(q, "bid", None)
        if q_bid is not None:
            try:
                q_bid_f = float(q_bid)
                if q_bid_f > 0:
                    leg_bid = leg.get("bid")
                    if leg_bid is None or float(leg_bid) <= 0:
                        leg["bid"] = q_bid_f
                        updated = True
            except (TypeError, ValueError):
                pass

        # Update ask if missing/invalid
        q_ask = q.get("ask") if isinstance(q, dict) else getattr(q, "ask", None)
        if q_ask is not None:
            try:
                q_ask_f = float(q_ask)
                if q_ask_f > 0:
                    leg_ask = leg.get("ask")
                    if leg_ask is None or float(leg_ask) <= 0:
                        leg["ask"] = q_ask_f
                        updated = True
            except (TypeError, ValueError):
                pass

        # Compute mid from bid/ask
        if _leg_has_valid_bidask(leg):
            mid = (float(leg["bid"]) + float(leg["ask"])) / 2.0
            leg["mid"] = mid
            leg["premium"] = mid
            updated = True

        if updated:
            hydrated_count += 1

    # Collect symbols still missing valid quotes after v4 snapshot
    missing_after_v4 = [
        leg.get("symbol") for leg in legs
        if not _leg_has_valid_bidask(leg)
    ]

    # Fallback: Use /v3/quotes for legs still missing valid bid/ask
    fallback_meta = None
    if missing_after_v4 and market_data is not None:
        fallback_attempted = 0
        fallback_hydrated = 0
        fallback_still_missing = []

        for leg in legs:
            sym = leg.get("symbol")
            if not sym or _leg_has_valid_bidask(leg):
                continue

            # Only fetch for option symbols (O: prefix)
            if not sym.startswith("O:"):
                fallback_still_missing.append(sym)
                continue

            fallback_attempted += 1
            try:
                q = market_data.get_recent_quote(sym)
                # Support multiple key formats
                bid = q.get("bid") or q.get("bid_price") or 0.0
                ask = q.get("ask") or q.get("ask_price") or 0.0

                if bid > 0 and ask > 0 and ask >= bid:
                    mid = (bid + ask) / 2.0
                    leg["bid"] = bid
                    leg["ask"] = ask
                    leg["mid"] = mid
                    leg["premium"] = mid
                    fallback_hydrated += 1
                    hydrated_count += 1
                else:
                    fallback_still_missing.append(sym)
            except Exception:
                fallback_still_missing.append(sym)

        fallback_meta = {
            "source": "polygon_v3_quotes",
            "attempted": fallback_attempted,
            "hydrated": fallback_hydrated,
            "still_missing": fallback_still_missing,
        }

    # Final list of symbols still missing valid quotes
    missing_after = [
        leg.get("symbol") for leg in legs
        if not _leg_has_valid_bidask(leg)
    ]

    result = {
        "hydrated": hydrated_count,
        "missing_after": missing_after,
        "quality": quality_info,
    }

    if fallback_meta:
        result["fallback"] = fallback_meta

    return result


class MockTruthLayer:
    """Mock TruthLayer that returns empty snapshots."""

    def snapshot_many_v4(self, tickers):
        return {}  # Empty - no snapshots

    def normalize_symbol(self, sym):
        return sym


class MockMarketData:
    """Mock PolygonService for testing."""

    def __init__(self, quote_responses: Dict[str, Dict[str, float]]):
        self.quote_responses = quote_responses
        self.calls = []

    def get_recent_quote(self, symbol: str) -> Dict[str, float]:
        self.calls.append(symbol)
        return self.quote_responses.get(symbol, {"bid": 0.0, "ask": 0.0})


class TestFallbackTriggered:
    """Test that fallback is attempted when v4 snapshots are empty."""

    def test_fallback_called_when_v4_empty(self):
        """Fallback should be attempted when v4 returns no quotes."""
        legs = [
            {"symbol": "O:SPY240119P450", "type": "put", "side": "sell", "strike": 450.0, "bid": None, "ask": None},
            {"symbol": "O:SPY240119P445", "type": "put", "side": "buy", "strike": 445.0, "bid": None, "ask": None},
            {"symbol": "O:SPY240119C465", "type": "call", "side": "sell", "strike": 465.0, "bid": None, "ask": None},
            {"symbol": "O:SPY240119C470", "type": "call", "side": "buy", "strike": 470.0, "bid": None, "ask": None},
        ]

        truth_layer = MockTruthLayer()
        market_data = MockMarketData({
            "O:SPY240119P450": {"bid": 1.50, "ask": 1.60},
            "O:SPY240119P445": {"bid": 0.80, "ask": 0.90},
            "O:SPY240119C465": {"bid": 1.40, "ask": 1.50},
            "O:SPY240119C470": {"bid": 0.70, "ask": 0.80},
        })

        meta = _hydrate_legs_quotes_v4_local(truth_layer, legs, market_data=market_data)

        # Verify fallback was called for all 4 legs
        assert len(market_data.calls) == 4
        assert "fallback" in meta
        assert meta["fallback"]["attempted"] == 4
        assert meta["fallback"]["hydrated"] == 4
        assert meta["fallback"]["source"] == "polygon_v3_quotes"

    def test_legs_patched_after_fallback(self):
        """Legs should have bid/ask/mid/premium after successful fallback."""
        legs = [
            {"symbol": "O:SPY240119P450", "type": "put", "side": "sell", "strike": 450.0, "bid": None, "ask": None},
        ]

        truth_layer = MockTruthLayer()
        market_data = MockMarketData({
            "O:SPY240119P450": {"bid": 1.50, "ask": 1.60},
        })

        meta = _hydrate_legs_quotes_v4_local(truth_layer, legs, market_data=market_data)

        assert legs[0]["bid"] == 1.50
        assert legs[0]["ask"] == 1.60
        assert legs[0]["mid"] == 1.55  # (1.50 + 1.60) / 2
        assert legs[0]["premium"] == 1.55
        assert meta["hydrated"] == 1
        assert len(meta["missing_after"]) == 0


class TestFallbackPartialSuccess:
    """Test fallback with partial success."""

    def test_some_legs_hydrated(self):
        """Only legs with valid quotes from fallback are hydrated."""
        legs = [
            {"symbol": "O:SPY240119P450", "type": "put", "side": "sell", "strike": 450.0, "bid": None, "ask": None},
            {"symbol": "O:SPY240119P445", "type": "put", "side": "buy", "strike": 445.0, "bid": None, "ask": None},
        ]

        truth_layer = MockTruthLayer()
        market_data = MockMarketData({
            "O:SPY240119P450": {"bid": 1.50, "ask": 1.60},  # Valid
            "O:SPY240119P445": {"bid": 0.0, "ask": 0.0},    # Invalid
        })

        meta = _hydrate_legs_quotes_v4_local(truth_layer, legs, market_data=market_data)

        # First leg hydrated
        assert legs[0]["bid"] == 1.50
        assert legs[0]["ask"] == 1.60

        # Second leg still missing
        assert legs[1]["bid"] is None
        assert legs[1]["ask"] is None

        assert meta["fallback"]["hydrated"] == 1
        assert meta["fallback"]["attempted"] == 2
        assert "O:SPY240119P445" in meta["fallback"]["still_missing"]
        assert "O:SPY240119P445" in meta["missing_after"]


class TestFallbackOnlyOptions:
    """Test that fallback only triggers for O: symbols."""

    def test_non_option_symbols_skipped(self):
        """Non-option symbols should not trigger fallback fetch."""
        legs = [
            {"symbol": "SPY", "type": "stock", "side": "buy", "strike": None, "bid": None, "ask": None},
            {"symbol": "O:SPY240119P450", "type": "put", "side": "sell", "strike": 450.0, "bid": None, "ask": None},
        ]

        truth_layer = MockTruthLayer()
        market_data = MockMarketData({
            "O:SPY240119P450": {"bid": 1.50, "ask": 1.60},
        })

        meta = _hydrate_legs_quotes_v4_local(truth_layer, legs, market_data=market_data)

        # Only option symbol should be fetched
        assert market_data.calls == ["O:SPY240119P450"]
        assert meta["fallback"]["attempted"] == 1
        assert meta["fallback"]["hydrated"] == 1
        # Non-option symbol in still_missing
        assert "SPY" in meta["fallback"]["still_missing"]


class TestFallbackNotTriggered:
    """Test cases where fallback should not be triggered."""

    def test_no_fallback_when_no_market_data(self):
        """No fallback when market_data is None."""
        legs = [
            {"symbol": "O:SPY240119P450", "type": "put", "side": "sell", "strike": 450.0, "bid": None, "ask": None},
        ]

        truth_layer = MockTruthLayer()

        meta = _hydrate_legs_quotes_v4_local(truth_layer, legs, market_data=None)

        assert "fallback" not in meta
        assert len(meta["missing_after"]) == 1

    def test_no_fallback_when_v4_provides_quotes(self):
        """No fallback when v4 snapshots provide valid quotes."""

        class MockTruthLayerWithQuotes:
            def snapshot_many_v4(self, tickers):
                return {
                    "O:SPY240119P450": {"quote": {"bid": 1.50, "ask": 1.60}},
                }

        legs = [
            {"symbol": "O:SPY240119P450", "type": "put", "side": "sell", "strike": 450.0, "bid": None, "ask": None},
        ]

        truth_layer = MockTruthLayerWithQuotes()
        market_data = MockMarketData({})

        meta = _hydrate_legs_quotes_v4_local(truth_layer, legs, market_data=market_data)

        # V4 should have hydrated, no fallback needed
        assert legs[0]["bid"] == 1.50
        assert len(market_data.calls) == 0  # Fallback not called
        assert "fallback" not in meta or meta.get("fallback", {}).get("attempted", 0) == 0


class TestFallbackQuoteKeyVariants:
    """Test that fallback handles different quote key formats."""

    def test_bid_price_ask_price_keys(self):
        """Fallback should work with bid_price/ask_price keys."""
        legs = [
            {"symbol": "O:SPY240119P450", "type": "put", "side": "sell", "strike": 450.0, "bid": None, "ask": None},
        ]

        truth_layer = MockTruthLayer()
        market_data = MockMarketData({
            "O:SPY240119P450": {"bid_price": 2.50, "ask_price": 2.60},  # Different keys
        })

        meta = _hydrate_legs_quotes_v4_local(truth_layer, legs, market_data=market_data)

        assert legs[0]["bid"] == 2.50
        assert legs[0]["ask"] == 2.60
        assert meta["fallback"]["hydrated"] == 1


class TestFallbackInvalidQuotes:
    """Test fallback handling of invalid quote values."""

    def test_zero_bid_ask_not_used(self):
        """Zero bid/ask should not hydrate the leg."""
        legs = [
            {"symbol": "O:SPY240119P450", "type": "put", "side": "sell", "strike": 450.0, "bid": None, "ask": None},
        ]

        truth_layer = MockTruthLayer()
        market_data = MockMarketData({
            "O:SPY240119P450": {"bid": 0.0, "ask": 1.60},
        })

        meta = _hydrate_legs_quotes_v4_local(truth_layer, legs, market_data=market_data)

        assert legs[0]["bid"] is None
        assert legs[0]["ask"] is None
        assert meta["fallback"]["hydrated"] == 0
        assert "O:SPY240119P450" in meta["fallback"]["still_missing"]

    def test_crossed_market_not_used(self):
        """Crossed market (bid > ask) should not hydrate the leg."""
        legs = [
            {"symbol": "O:SPY240119P450", "type": "put", "side": "sell", "strike": 450.0, "bid": None, "ask": None},
        ]

        truth_layer = MockTruthLayer()
        market_data = MockMarketData({
            "O:SPY240119P450": {"bid": 1.60, "ask": 1.50},  # Crossed
        })

        meta = _hydrate_legs_quotes_v4_local(truth_layer, legs, market_data=market_data)

        assert legs[0]["bid"] is None
        assert meta["fallback"]["hydrated"] == 0


class TestFullCondorHydration:
    """Test full 4-leg condor hydration via fallback."""

    def test_iron_condor_all_legs_hydrated(self):
        """All 4 iron condor legs should be hydrated via fallback."""
        legs = [
            {"symbol": "O:SPY240119P450", "type": "put", "side": "sell", "strike": 450.0, "bid": None, "ask": None},
            {"symbol": "O:SPY240119P445", "type": "put", "side": "buy", "strike": 445.0, "bid": None, "ask": None},
            {"symbol": "O:SPY240119C465", "type": "call", "side": "sell", "strike": 465.0, "bid": None, "ask": None},
            {"symbol": "O:SPY240119C470", "type": "call", "side": "buy", "strike": 470.0, "bid": None, "ask": None},
        ]

        truth_layer = MockTruthLayer()
        market_data = MockMarketData({
            "O:SPY240119P450": {"bid": 1.50, "ask": 1.60},
            "O:SPY240119P445": {"bid": 0.80, "ask": 0.90},
            "O:SPY240119C465": {"bid": 1.40, "ask": 1.50},
            "O:SPY240119C470": {"bid": 0.70, "ask": 0.80},
        })

        meta = _hydrate_legs_quotes_v4_local(truth_layer, legs, market_data=market_data)

        # All legs should be hydrated
        assert meta["hydrated"] == 4
        assert len(meta["missing_after"]) == 0
        assert meta["fallback"]["hydrated"] == 4

        # Verify each leg has valid quotes
        for leg in legs:
            assert _leg_has_valid_bidask(leg)
            assert leg["mid"] > 0
            assert leg["premium"] > 0

    def test_total_cost_can_be_computed(self):
        """After hydration, total cost should be computable."""
        legs = [
            {"symbol": "O:SPY240119P450", "type": "put", "side": "sell", "strike": 450.0, "bid": None, "ask": None},
            {"symbol": "O:SPY240119P445", "type": "put", "side": "buy", "strike": 445.0, "bid": None, "ask": None},
            {"symbol": "O:SPY240119C465", "type": "call", "side": "sell", "strike": 465.0, "bid": None, "ask": None},
            {"symbol": "O:SPY240119C470", "type": "call", "side": "buy", "strike": 470.0, "bid": None, "ask": None},
        ]

        truth_layer = MockTruthLayer()
        market_data = MockMarketData({
            "O:SPY240119P450": {"bid": 1.50, "ask": 1.60},  # sell -> -1.55
            "O:SPY240119P445": {"bid": 0.80, "ask": 0.90},  # buy -> +0.85
            "O:SPY240119C465": {"bid": 1.40, "ask": 1.50},  # sell -> -1.45
            "O:SPY240119C470": {"bid": 0.70, "ask": 0.80},  # buy -> +0.75
        })

        meta = _hydrate_legs_quotes_v4_local(truth_layer, legs, market_data=market_data)

        # Compute total cost
        total = 0.0
        for leg in legs:
            prem = leg["premium"]
            if leg["side"] == "buy":
                total += prem
            else:
                total -= prem

        # Expected: -1.55 + 0.85 - 1.45 + 0.75 = -1.40 (credit)
        assert abs(total - (-1.40)) < 0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
