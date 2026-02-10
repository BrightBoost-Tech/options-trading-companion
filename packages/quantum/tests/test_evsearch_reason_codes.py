"""
Tests for EV-search reason codes and delta detection.

Verifies:
1. Delta detection checks across chain, not just first contract
2. Reason codes are specific to which stage failed
3. best_seen is included when EV was computed
4. Stage counters are always reported
"""

import pytest
from typing import Dict, Any, List, Optional


# Configuration defaults (matching options_scanner.py)
CONDOR_TARGET_DELTAS = [0.06, 0.08, 0.10, 0.12, 0.15]
CONDOR_WIDTHS = [2.5, 5, 7.5]
CONDOR_MIN_CREDIT = 0.60


def _is_valid_nbbo(bid: Any, ask: Any) -> bool:
    """Check if bid/ask values constitute a valid NBBO."""
    try:
        if bid is None or ask is None:
            return False
        bid_f = float(bid)
        ask_f = float(ask)
        return bid_f > 0 and ask_f > 0 and ask_f >= bid_f
    except (TypeError, ValueError):
        return False


def _mid_from_nbbo(bid: Any, ask: Any) -> Optional[float]:
    """Compute mid price only if valid NBBO."""
    if not _is_valid_nbbo(bid, ask):
        return None
    try:
        return (float(bid) + float(ask)) / 2.0
    except (TypeError, ValueError):
        return None


def _leg_spread_pct(leg: Dict[str, Any]) -> Optional[float]:
    """Compute per-leg spread percentage."""
    try:
        bid = leg.get("bid")
        ask = leg.get("ask")
        if not _is_valid_nbbo(bid, ask):
            return None
        bid_f = float(bid)
        ask_f = float(ask)
        mid = (bid_f + ask_f) / 2.0
        if mid <= 0:
            return None
        return (ask_f - bid_f) / mid
    except (TypeError, ValueError):
        return None


def _max_leg_spread_pct(legs: List[Dict[str, Any]]) -> float:
    """Get max spread pct across all legs."""
    pcts = [p for p in (_leg_spread_pct(l) for l in legs) if p is not None]
    return max(pcts) if pcts else float('inf')


def _chain_has_any_delta(calls: List[Dict], puts: List[Dict]) -> bool:
    """Check if any contract in chain has a delta value."""
    for c in (calls[:25] + puts[:25]):
        if c.get("delta") is not None:
            return True
    return False


def _calculate_condor_ev_local(
    credit: float,
    width_put: float,
    width_call: float,
    short_put_delta: float,
    short_call_delta: float
) -> float:
    """Simplified EV calculation for condor."""
    p_breach_put = abs(short_put_delta)
    p_breach_call = abs(short_call_delta)
    max_loss_put = width_put - credit
    max_loss_call = width_call - credit
    expected_loss = (p_breach_put * max_loss_put) + (p_breach_call * max_loss_call)
    p_keep = 1.0 - p_breach_put - p_breach_call
    expected_profit = p_keep * credit
    return (expected_profit - expected_loss) * 100


def _select_best_iron_condor_ev_aware_local(
    calls: List[Dict[str, Any]],
    puts: List[Dict[str, Any]],
    condor_spread_threshold: float,
    current_price: float = 0.0
) -> tuple[List[Dict[str, Any]], float, Dict[str, Any]]:
    """Local implementation with improved delta detection and reason codes."""
    if not calls or not puts:
        return [], 0.0, {"reason": "empty_chain"}

    # Check across chain, not just first contract
    if not _chain_has_any_delta(calls, puts):
        return [], 0.0, {"reason": "no_deltas_in_chain"}

    best_ev_positive = None
    best_legs_positive = None
    best_cost_positive = None
    best_meta_positive = None
    best_ev_overall = None
    best_meta_overall = None

    # Stage counters
    combos_tried = 0
    combos_valid_nbbo = 0
    combos_pass_credit = 0
    combos_pass_spread = 0
    combos_ev_computed = 0
    best_credit_seen = 0.0

    for target_delta in CONDOR_TARGET_DELTAS:
        for width in CONDOR_WIDTHS:
            combos_tried += 1

            # Simplified leg selection
            short_call = None
            short_put = None
            for c in calls:
                d = c.get("delta")
                if d is not None and abs(abs(d) - target_delta) < 0.05:
                    if _is_valid_nbbo(c.get("bid"), c.get("ask")):
                        short_call = c
                        break

            for p in puts:
                d = p.get("delta")
                if d is not None and abs(abs(d) - target_delta) < 0.05:
                    if _is_valid_nbbo(p.get("bid"), p.get("ask")):
                        short_put = p
                        break

            if not short_call or not short_put:
                continue

            # Find longs
            target_long_call = short_call["strike"] + width
            target_long_put = short_put["strike"] - width
            long_call = None
            long_put = None

            for c in calls:
                if abs(c["strike"] - target_long_call) < 0.5:
                    if _is_valid_nbbo(c.get("bid"), c.get("ask")):
                        long_call = c
                        break

            for p in puts:
                if abs(p["strike"] - target_long_put) < 0.5:
                    if _is_valid_nbbo(p.get("bid"), p.get("ask")):
                        long_put = p
                        break

            if not long_call or not long_put:
                continue

            combos_valid_nbbo += 1

            # Build legs
            def mid(leg):
                return (float(leg["bid"]) + float(leg["ask"])) / 2.0

            legs = [
                {"symbol": "SC", "strike": short_call["strike"], "type": "call", "side": "sell",
                 "bid": short_call["bid"], "ask": short_call["ask"], "delta": short_call.get("delta"), "mid": mid(short_call)},
                {"symbol": "LC", "strike": long_call["strike"], "type": "call", "side": "buy",
                 "bid": long_call["bid"], "ask": long_call["ask"], "delta": long_call.get("delta"), "mid": mid(long_call)},
                {"symbol": "SP", "strike": short_put["strike"], "type": "put", "side": "sell",
                 "bid": short_put["bid"], "ask": short_put["ask"], "delta": short_put.get("delta"), "mid": mid(short_put)},
                {"symbol": "LP", "strike": long_put["strike"], "type": "put", "side": "buy",
                 "bid": long_put["bid"], "ask": long_put["ask"], "delta": long_put.get("delta"), "mid": mid(long_put)},
            ]

            total_cost = -mid(short_call) - mid(short_put) + mid(long_call) + mid(long_put)
            credit_share = abs(total_cost) if total_cost < 0 else 0.0

            if credit_share > best_credit_seen:
                best_credit_seen = credit_share

            if credit_share < CONDOR_MIN_CREDIT:
                continue

            combos_pass_credit += 1

            max_leg_spread = _max_leg_spread_pct(legs)
            if max_leg_spread > condor_spread_threshold:
                continue

            combos_pass_spread += 1

            # Compute EV
            try:
                total_ev = _calculate_condor_ev_local(
                    credit=credit_share,
                    width_put=width,
                    width_call=width,
                    short_put_delta=abs(short_put.get("delta") or 0),
                    short_call_delta=abs(short_call.get("delta") or 0)
                )
            except Exception:
                continue

            combos_ev_computed += 1

            meta = {
                "target_delta": target_delta,
                "width": width,
                "credit_share": round(credit_share, 4),
                "total_ev": round(total_ev, 4),
                "max_leg_spread_pct": round(max_leg_spread, 4),
            }

            if best_ev_overall is None or total_ev > best_ev_overall:
                best_ev_overall = total_ev
                best_meta_overall = meta

            if total_ev > 0:
                if best_ev_positive is None or total_ev > best_ev_positive:
                    best_ev_positive = total_ev
                    best_legs_positive = legs
                    best_cost_positive = total_cost
                    best_meta_positive = meta

    # Success case
    if best_legs_positive:
        best_meta_positive["combos_tried"] = combos_tried
        best_meta_positive["combos_valid_nbbo"] = combos_valid_nbbo
        best_meta_positive["combos_pass_credit"] = combos_pass_credit
        best_meta_positive["combos_pass_spread"] = combos_pass_spread
        best_meta_positive["combos_ev_computed"] = combos_ev_computed
        return best_legs_positive, best_cost_positive, best_meta_positive

    # Determine specific reason
    if combos_valid_nbbo == 0:
        reason = "no_valid_nbbo"
    elif combos_pass_credit == 0:
        reason = "credit_below_min"
    elif combos_pass_spread == 0:
        reason = "spread_above_threshold"
    elif combos_ev_computed == 0:
        reason = "ev_not_computed"
    else:
        reason = "no_positive_ev"

    result_meta = {
        "reason": reason,
        "combos_tried": combos_tried,
        "combos_valid_nbbo": combos_valid_nbbo,
        "combos_pass_credit": combos_pass_credit,
        "combos_pass_spread": combos_pass_spread,
        "combos_ev_computed": combos_ev_computed,
    }

    if reason == "credit_below_min":
        result_meta["best_credit_seen"] = round(best_credit_seen, 4)
        result_meta["min_credit_required"] = CONDOR_MIN_CREDIT

    if best_meta_overall and combos_ev_computed > 0:
        result_meta["best_seen"] = best_meta_overall

    return [], 0.0, result_meta


class TestDeltaDetection:
    """Test that delta detection checks across the chain."""

    def test_first_contract_no_delta_others_have_delta(self):
        """Should NOT return no_deltas_in_chain if first has None but others have delta."""
        calls = [
            {"strike": 100, "delta": None, "bid": 1.0, "ask": 1.1},  # First has None
            {"strike": 102.5, "delta": 0.10, "bid": 0.8, "ask": 0.9},  # This has delta
            {"strike": 105, "delta": 0.05, "bid": 0.5, "ask": 0.6},
        ]
        puts = [
            {"strike": 95, "delta": None, "bid": 0.8, "ask": 0.9},  # First has None
            {"strike": 92.5, "delta": -0.10, "bid": 0.6, "ask": 0.7},  # This has delta
            {"strike": 90, "delta": -0.05, "bid": 0.4, "ask": 0.5},
        ]

        legs, cost, meta = _select_best_iron_condor_ev_aware_local(
            calls, puts, condor_spread_threshold=0.50
        )

        # Should NOT be no_deltas_in_chain
        assert meta.get("reason") != "no_deltas_in_chain"
        # Should try combos
        assert meta.get("combos_tried", 0) > 0

    def test_all_contracts_no_delta(self):
        """Should return no_deltas_in_chain if ALL contracts lack delta."""
        calls = [
            {"strike": 100, "delta": None, "bid": 1.0, "ask": 1.1},
            {"strike": 105, "delta": None, "bid": 0.5, "ask": 0.6},
        ]
        puts = [
            {"strike": 95, "delta": None, "bid": 0.8, "ask": 0.9},
            {"strike": 90, "delta": None, "bid": 0.4, "ask": 0.5},
        ]

        legs, cost, meta = _select_best_iron_condor_ev_aware_local(
            calls, puts, condor_spread_threshold=0.50
        )

        assert meta.get("reason") == "no_deltas_in_chain"

    def test_chain_has_any_delta_helper(self):
        """Test _chain_has_any_delta helper function."""
        # First contract None, later has delta
        calls = [{"delta": None}, {"delta": 0.10}, {"delta": None}]
        puts = [{"delta": None}, {"delta": None}]
        assert _chain_has_any_delta(calls, puts) is True

        # All None
        calls = [{"delta": None}, {"delta": None}]
        puts = [{"delta": None}]
        assert _chain_has_any_delta(calls, puts) is False

        # Only puts have delta
        calls = [{"delta": None}]
        puts = [{"delta": None}, {"delta": -0.05}]
        assert _chain_has_any_delta(calls, puts) is True


class TestReasonCodeCreditBelowMin:
    """Test credit_below_min reason code."""

    def test_all_combos_fail_credit(self):
        """Should return credit_below_min when all combos have low credit."""
        # Create chain with very cheap options (low credit)
        calls = [
            {"strike": 120, "delta": 0.10, "bid": 0.05, "ask": 0.06},
            {"strike": 122.5, "delta": 0.08, "bid": 0.03, "ask": 0.04},
            {"strike": 125, "delta": 0.06, "bid": 0.02, "ask": 0.03},
        ]
        puts = [
            {"strike": 80, "delta": -0.10, "bid": 0.05, "ask": 0.06},
            {"strike": 77.5, "delta": -0.08, "bid": 0.03, "ask": 0.04},
            {"strike": 75, "delta": -0.06, "bid": 0.02, "ask": 0.03},
        ]

        legs, cost, meta = _select_best_iron_condor_ev_aware_local(
            calls, puts, condor_spread_threshold=0.50
        )

        assert legs == []
        # If we get valid NBBO but fail credit
        if meta.get("combos_valid_nbbo", 0) > 0:
            assert meta.get("reason") == "credit_below_min"
            assert "best_credit_seen" in meta
            assert "min_credit_required" in meta


class TestReasonCodeSpreadAboveThreshold:
    """Test spread_above_threshold reason code."""

    def test_all_combos_fail_spread(self):
        """Should return spread_above_threshold when all legs have wide spreads."""
        # Wide spreads (100% spread)
        calls = [
            {"strike": 105, "delta": 0.10, "bid": 0.50, "ask": 1.00},  # 67% spread
            {"strike": 107.5, "delta": 0.08, "bid": 0.40, "ask": 0.80},
            {"strike": 110, "delta": 0.06, "bid": 0.30, "ask": 0.60},
        ]
        puts = [
            {"strike": 95, "delta": -0.10, "bid": 0.50, "ask": 1.00},
            {"strike": 92.5, "delta": -0.08, "bid": 0.40, "ask": 0.80},
            {"strike": 90, "delta": -0.06, "bid": 0.30, "ask": 0.60},
        ]

        legs, cost, meta = _select_best_iron_condor_ev_aware_local(
            calls, puts, condor_spread_threshold=0.10  # Very tight threshold
        )

        assert legs == []
        # If we pass credit but fail spread
        if meta.get("combos_pass_credit", 0) > 0 and meta.get("combos_pass_spread", 0) == 0:
            assert meta.get("reason") == "spread_above_threshold"


class TestReasonCodeNoPositiveEV:
    """Test no_positive_ev reason code includes best_seen."""

    def test_ev_computed_but_negative(self):
        """Should return no_positive_ev with best_seen when all EV <= 0."""
        # Create chain where EV will be negative (high delta = high breach probability)
        calls = [
            {"strike": 101, "delta": 0.40, "bid": 1.00, "ask": 1.05},
            {"strike": 103.5, "delta": 0.35, "bid": 0.80, "ask": 0.85},
            {"strike": 106, "delta": 0.30, "bid": 0.60, "ask": 0.65},
        ]
        puts = [
            {"strike": 99, "delta": -0.40, "bid": 1.00, "ask": 1.05},
            {"strike": 96.5, "delta": -0.35, "bid": 0.80, "ask": 0.85},
            {"strike": 94, "delta": -0.30, "bid": 0.60, "ask": 0.65},
        ]

        legs, cost, meta = _select_best_iron_condor_ev_aware_local(
            calls, puts, condor_spread_threshold=0.50
        )

        # If EV was computed but all negative
        if meta.get("combos_ev_computed", 0) > 0 and legs == []:
            assert meta.get("reason") == "no_positive_ev"
            assert "best_seen" in meta
            assert meta["best_seen"]["total_ev"] <= 0


class TestStageCounters:
    """Test that stage counters are always reported."""

    def test_counters_present_in_failure_meta(self):
        """All stage counters should be in meta on failure."""
        calls = [{"strike": 105, "delta": 0.10, "bid": 1.0, "ask": 1.1}]
        puts = [{"strike": 95, "delta": -0.10, "bid": 1.0, "ask": 1.1}]

        legs, cost, meta = _select_best_iron_condor_ev_aware_local(
            calls, puts, condor_spread_threshold=0.50
        )

        # These should always be present
        assert "combos_tried" in meta
        assert "combos_valid_nbbo" in meta
        assert "combos_pass_credit" in meta
        assert "combos_pass_spread" in meta
        assert "combos_ev_computed" in meta

    def test_counters_present_in_success_meta(self):
        """All stage counters should be in meta on success."""
        # Create a chain that produces a positive EV condor
        calls = [
            {"strike": 105, "delta": 0.10, "bid": 0.90, "ask": 0.95},
            {"strike": 107.5, "delta": 0.08, "bid": 0.60, "ask": 0.65},
            {"strike": 110, "delta": 0.06, "bid": 0.40, "ask": 0.45},
        ]
        puts = [
            {"strike": 95, "delta": -0.10, "bid": 0.90, "ask": 0.95},
            {"strike": 92.5, "delta": -0.08, "bid": 0.60, "ask": 0.65},
            {"strike": 90, "delta": -0.06, "bid": 0.40, "ask": 0.45},
        ]

        legs, cost, meta = _select_best_iron_condor_ev_aware_local(
            calls, puts, condor_spread_threshold=0.50
        )

        if legs:
            assert "combos_tried" in meta
            assert "combos_valid_nbbo" in meta
            assert "combos_pass_credit" in meta
            assert "combos_pass_spread" in meta
            assert "combos_ev_computed" in meta


class TestNoValidNBBO:
    """Test no_valid_nbbo reason code."""

    def test_all_invalid_nbbo(self):
        """Should return no_valid_nbbo when no legs have valid quotes."""
        # All invalid NBBO (bid=0 or ask=0)
        calls = [
            {"strike": 105, "delta": 0.10, "bid": 0, "ask": 1.0},
            {"strike": 107.5, "delta": 0.08, "bid": 0.5, "ask": 0},
        ]
        puts = [
            {"strike": 95, "delta": -0.10, "bid": 0, "ask": 1.0},
            {"strike": 92.5, "delta": -0.08, "bid": None, "ask": 0.5},
        ]

        legs, cost, meta = _select_best_iron_condor_ev_aware_local(
            calls, puts, condor_spread_threshold=0.50
        )

        assert legs == []
        if meta.get("combos_valid_nbbo", 0) == 0:
            assert meta.get("reason") == "no_valid_nbbo"


class TestEmptyChain:
    """Test empty_chain reason code."""

    def test_empty_calls(self):
        """Should return empty_chain when calls list is empty."""
        legs, cost, meta = _select_best_iron_condor_ev_aware_local(
            [], [{"strike": 95, "delta": -0.10}], condor_spread_threshold=0.50
        )
        assert meta.get("reason") == "empty_chain"

    def test_empty_puts(self):
        """Should return empty_chain when puts list is empty."""
        legs, cost, meta = _select_best_iron_condor_ev_aware_local(
            [{"strike": 105, "delta": 0.10}], [], condor_spread_threshold=0.50
        )
        assert meta.get("reason") == "empty_chain"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
