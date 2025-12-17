
import pytest
from unittest.mock import MagicMock, patch
from packages.quantum.options_scanner import scan_for_opportunities

@patch('packages.quantum.options_scanner.MarketDataTruthLayer')
@patch('packages.quantum.options_scanner.RegimeEngineV3')
@patch('packages.quantum.options_scanner.StrategySelector')
@patch('packages.quantum.options_scanner.PolygonService')
@patch('packages.quantum.options_scanner.UniverseService')
@patch('packages.quantum.options_scanner.ExecutionService')
def test_iron_condor_candidate_generation(
    mock_execution_service,
    mock_universe_service,
    mock_polygon,
    mock_selector,
    mock_regime_engine,
    mock_truth_layer
):
    """
    Test that scan_for_opportunities correctly identifies and builds an Iron Condor candidate
    when the StrategySelector suggests one.
    """

    # 1. Setup Mock Universe
    mock_universe_service.return_value = None # Not used directly if we pass symbols

    # 2. Setup Regime Engine
    mock_regime_instance = mock_regime_engine.return_value
    mock_global_snapshot = MagicMock()
    mock_global_snapshot.state = "NORMAL"
    mock_global_snapshot.to_dict.return_value = {"state": "NORMAL"}
    mock_regime_instance.compute_global_snapshot.return_value = mock_global_snapshot
    mock_regime_instance._default_global_snapshot.return_value = mock_global_snapshot

    mock_symbol_snapshot = MagicMock()
    mock_symbol_snapshot.iv_rank = 50.0
    mock_regime_instance.compute_symbol_snapshot.return_value = mock_symbol_snapshot

    effective_regime = MagicMock()
    effective_regime.value = "NEUTRAL"
    mock_regime_instance.get_effective_regime.return_value = effective_regime

    # 3. Setup Truth Layer (Quotes & Chain)
    mock_truth_instance = mock_truth_layer.return_value

    # Fix: Ensure normalize_symbol returns the input
    mock_truth_instance.normalize_symbol.side_effect = lambda x: x

    # Batch Quote
    mock_truth_instance.snapshot_many.return_value = {
        "TEST": {
            "quote": {"bid": 100.00, "ask": 100.10, "mid": 100.05, "last": 100.05}
        }
    }

    # Bars (Trend)
    mock_truth_instance.daily_bars.return_value = [{"close": 100.0} for _ in range(60)]

    # Option Chain
    # We need to construct a chain that satisfies the Iron Condor selection logic
    # Target DTE: 35. Price: 100.
    # Short Put Delta -0.15 -> Strike ~90? (Put delta is negative)
    # Short Call Delta 0.15 -> Strike ~110?
    # Width 5.0
    # Long Put Strike 85
    # Long Call Strike 115

    # Create valid expiry ~35 days out
    from datetime import datetime, timedelta
    expiry_date = (datetime.now() + timedelta(days=35)).strftime("%Y-%m-%d")

    chain_data = [
        # Short Put
        {"contract": "TEST_P_95", "ticker": "TEST_P_95", "strike": 95.0, "expiry": expiry_date, "right": "put", "type": "put",
         "greeks": {"delta": -0.15, "gamma": 0.01, "vega": 0.1, "theta": -0.05},
         "quote": {"mid": 2.00, "bid": 1.95, "ask": 2.05, "last": 2.00}},
        # Long Put (Width 5) -> Strike 90
        {"contract": "TEST_P_90", "ticker": "TEST_P_90", "strike": 90.0, "expiry": expiry_date, "right": "put", "type": "put",
         "greeks": {"delta": -0.10, "gamma": 0.01, "vega": 0.1, "theta": -0.05},
         "quote": {"mid": 0.50, "bid": 0.45, "ask": 0.55, "last": 0.50}},

        # Short Call
        {"contract": "TEST_C_105", "ticker": "TEST_C_105", "strike": 105.0, "expiry": expiry_date, "right": "call", "type": "call",
         "greeks": {"delta": 0.15, "gamma": 0.01, "vega": 0.1, "theta": -0.05},
         "quote": {"mid": 2.00, "bid": 1.95, "ask": 2.05, "last": 2.00}},
        # Long Call (Width 5) -> Strike 110
        {"contract": "TEST_C_110", "ticker": "TEST_C_110", "strike": 110.0, "expiry": expiry_date, "right": "call", "type": "call",
         "greeks": {"delta": 0.10, "gamma": 0.01, "vega": 0.1, "theta": -0.05},
         "quote": {"mid": 0.50, "bid": 0.45, "ask": 0.55, "last": 0.50}},

         # Extra noise
         {"contract": "TEST_C_100", "ticker": "TEST_C_100", "strike": 100.0, "expiry": expiry_date, "right": "call", "type": "call",
         "greeks": {"delta": 0.50, "gamma": 0.01, "vega": 0.1, "theta": -0.05},
         "quote": {"mid": 3.00, "bid": 2.90, "ask": 3.10, "last": 3.00}},
    ]

    mock_truth_instance.option_chain.return_value = chain_data

    # 4. Setup Strategy Selector to return IRON_CONDOR
    mock_selector_instance = mock_selector.return_value
    mock_selector_instance.determine_strategy.return_value = {
        "strategy": "IRON_CONDOR",
        "legs": [] # Should be ignored by our new logic
    }

    # 5. Mock Execution Service (Low cost to pass gating)
    mock_execution_instance = mock_execution_service.return_value
    mock_execution_instance.get_batch_execution_drag_stats.return_value = {
        "TEST": {"avg_drag": 1.0, "n": 100} # $1.00 drag vs huge EV
    }

    # Run Scanner
    candidates = scan_for_opportunities(symbols=["TEST"])

    # Assertions
    assert len(candidates) == 1
    cand = candidates[0]

    assert cand['strategy_key'] == 'iron_condor'
    assert len(cand['legs']) == 4

    # Verify legs are correct
    strikes = sorted([l['strike'] for l in cand['legs']])
    assert strikes == [90.0, 95.0, 105.0, 110.0]

    # Verify Risk Primitives
    # Credit = (2.0 - 0.5) + (2.0 - 0.5) = 3.0
    # Max Profit = 300
    # Max Loss = (5 - 3) * 100 = 200
    assert cand['max_profit_per_contract'] == pytest.approx(300.0)
    assert cand['max_loss_per_contract'] == pytest.approx(200.0)
    assert cand['collateral_required_per_contract'] == pytest.approx(500.0) # Width * 100

    # Verify EV
    assert cand['ev'] > 0
