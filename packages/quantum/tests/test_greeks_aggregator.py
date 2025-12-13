import pytest
from packages.quantum.analytics.greeks_aggregator import aggregate_portfolio_greeks, build_greek_alerts
from packages.quantum.models import SpreadPosition, SpreadLeg

# Assuming Leg is not exported or needed if we pass legs as dicts to SpreadPosition (per model definition)

def test_aggregate_portfolio_greeks_empty():
    greeks = aggregate_portfolio_greeks([])
    assert greeks["delta"] == 0.0
    assert greeks["gamma"] == 0.0
    assert greeks["theta"] == 0.0
    assert greeks["vega"] == 0.0

def test_aggregate_portfolio_greeks_mixed():
    spread1 = SpreadPosition(
        id="pos1",
        user_id="user1",
        ticker="SPY",
        underlying="SPY",
        spread_type="debit_call", # Valid literal
        legs=[],
        net_cost=100.0,
        current_value=120.0,
        delta=0.5,
        gamma=0.02,
        theta=-0.1,
        vega=0.05
    )
    # Inverse position
    spread2 = SpreadPosition(
        id="pos2",
        user_id="user1",
        ticker="QQQ",
        underlying="QQQ",
        spread_type="debit_put", # Valid literal
        legs=[],
        net_cost=50.0,
        current_value=40.0,
        delta=-0.2,
        gamma=0.01,
        theta=-0.05,
        vega=0.03
    )

    spreads = [spread1, spread2]
    greeks = aggregate_portfolio_greeks(spreads)

    assert pytest.approx(greeks["delta"]) == 0.3
    assert pytest.approx(greeks["gamma"]) == 0.03
    assert pytest.approx(greeks["theta"]) == -0.15
    assert pytest.approx(greeks["vega"]) == 0.08

def test_build_greek_alerts():
    # Test safe levels - ensure we pass dict with 'delta' etc.
    # The function expects 'portfolio_greeks' dict.

    safe_greeks = {"delta": 50.0, "gamma": 5.0, "theta": 10.0, "vega": 50.0}
    alerts = build_greek_alerts(safe_greeks)

    # build_greek_alerts returns a Dictionary of flags (GreekAlerts model or dict)
    assert isinstance(alerts, dict)
    assert alerts.get("delta_over_limit") is False

    # Test high delta
    high_delta = {"delta": 600.0, "gamma": 10.0, "theta": 50.0, "vega": 50.0}
    alerts_high = build_greek_alerts(high_delta)
    assert alerts_high.get("delta_over_limit") is True
