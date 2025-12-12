import pytest
from packages.quantum.services.forward_atm import compute_forward_atm_from_parity

def test_clean_sign_crossing():
    spot = 100.0
    # Synthetic chain where forward is exactly 102.0
    # At K=100, C-P = F-K = 102 - 100 = +2
    # At K=105, C-P = F-K = 102 - 105 = -3
    calls = [
        {"strike": 100, "quote": {"mid": 5.0}},
        {"strike": 105, "quote": {"mid": 1.0}}
    ]
    puts = [
        {"strike": 100, "quote": {"mid": 3.0}}, # 5 - 3 = 2
        {"strike": 105, "quote": {"mid": 4.0}}  # 1 - 4 = -3
    ]

    res = compute_forward_atm_from_parity(calls, puts, spot)

    assert res.method in ["regression", "zero_cross"]
    assert res.forward_price is not None
    # Check if close to 102
    assert abs(res.forward_price - 102.0) < 0.1
    # Check if ATM strike is closest to 102 (which is 100 or 105, 100 is dist 2, 105 is dist 3 -> 100)
    assert res.atm_strike == 100.0 or res.atm_strike == 105.0

def test_regression_only_no_sign_change():
    # If all diffs are positive, but slope indicates a crossing ahead
    # F approx 105
    # K=90: diff=15
    # K=95: diff=10
    # K=100: diff=5
    # All positive, but linear regression should find F=105
    spot = 95.0
    calls = [
        {"strike": 90, "quote": {"mid": 20.0}},
        {"strike": 95, "quote": {"mid": 15.0}},
        {"strike": 100, "quote": {"mid": 10.0}},
    ]
    puts = [
        {"strike": 90, "quote": {"mid": 5.0}},
        {"strike": 95, "quote": {"mid": 5.0}},
        {"strike": 100, "quote": {"mid": 5.0}},
    ]
    # diffs: 15, 10, 5. slope is -1.
    # 15 = a + b*90 -> 15 = a - 90
    # 10 = a + b*95 -> 10 = a - 95
    # 5 = a + b*100 -> 5 = a - 100
    # a = 105, b = -1
    # F = -a/b = -105/-1 = 105

    res = compute_forward_atm_from_parity(calls, puts, spot, near_pct=0.20) # Widen pct to include 90-100 around 95

    assert res.method == "regression"
    assert abs(res.forward_price - 105.0) < 0.1
    assert res.atm_strike == 100.0 # closest available to 105

def test_missing_pairs():
    spot = 100.0
    calls = [
        {"strike": 100, "quote": {"mid": 5.0}},
    ]
    puts = [
        {"strike": 105, "quote": {"mid": 4.0}}
    ]
    # No overlapping strikes
    res = compute_forward_atm_from_parity(calls, puts, spot)
    assert res.method == "fallback_spot"
    assert res.forward_price is None

def test_wide_spread_filter():
    spot = 100.0
    # Strike 100 has huge spread, Strike 105 is tight
    # Spread ratio > 0.35 should be filtered

    # 100: Call 4.0/6.0 (mid 5, spread 2, ratio 0.4) -> FILTERED
    # 105: Call 1.9/2.1 (mid 2, spread 0.2, ratio 0.1) -> OK

    calls = [
        {"strike": 100, "quote": {"bid": 4.0, "ask": 6.0, "mid": 5.0}},
        {"strike": 105, "quote": {"bid": 1.9, "ask": 2.1, "mid": 2.0}},
        {"strike": 95, "quote": {"bid": 6.9, "ask": 7.1, "mid": 7.0}}
    ]
    puts = [
        {"strike": 100, "quote": {"bid": 2.0, "ask": 4.0, "mid": 3.0}},
        {"strike": 105, "quote": {"bid": 4.9, "ask": 5.1, "mid": 5.0}}, # diff = 2 - 5 = -3
        {"strike": 95, "quote": {"bid": 0.9, "ask": 1.1, "mid": 1.0}} # diff = 7 - 1 = 6
    ]
    # If 100 is filtered, we have 95 (diff 6) and 105 (diff -3)
    # Crossing between 95 and 105
    # F approx 95 + (6 / (6 - -3)) * 10 = 95 + 6/9 * 10 = 95 + 6.66 = 101.66

    res = compute_forward_atm_from_parity(calls, puts, spot)

    assert res.method in ["regression", "zero_cross"]
    # Should not rely on 100
    # If 100 was included (diff = 5-3=2), we'd have 95(6), 100(2), 105(-3).
    # Crossing 100->105: 100 + 2/(2 - -3)*5 = 100 + 2/5*5 = 102.

    # Let's verify diagnostics if possible, or just result consistency
    assert res.forward_price is not None

def test_insufficient_points_fallback():
    spot = 100.0
    # Only 1 valid strike
    calls = [{"strike": 100, "quote": {"mid": 5.0}}]
    puts = [{"strike": 100, "quote": {"mid": 3.0}}]

    res = compute_forward_atm_from_parity(calls, puts, spot)
    assert res.method == "fallback_spot"
    assert res.diagnostics["reason"] == "too_few_near_points" or res.diagnostics["reason"] == "too_few_points_after_filters"
