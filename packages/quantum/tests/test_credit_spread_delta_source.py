
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
from packages.quantum.options_scanner import scan_for_opportunities
from packages.quantum.common_enums import RegimeState

@patch("packages.quantum.options_scanner.PolygonService")
@patch("packages.quantum.options_scanner.StrategySelector")
@patch("packages.quantum.options_scanner.UniverseService")
@patch("packages.quantum.options_scanner.MarketDataTruthLayer")
@patch("packages.quantum.options_scanner.RegimeEngineV3")
@patch("packages.quantum.options_scanner.calculate_ev")
def test_credit_spread_ev_delta(mock_calc_ev, mock_regime, mock_mdtl, mock_univ, mock_selector, mock_poly):
    # Setup
    mock_calc_ev.return_value = MagicMock(expected_value=10.0)

    # Mock Regime Engine
    mock_regime_instance = mock_regime.return_value
    mock_global_snapshot = MagicMock()
    mock_global_snapshot.state = RegimeState.NORMAL
    mock_global_snapshot.to_dict.return_value = {"state": "NORMAL"}
    mock_regime_instance.compute_global_snapshot.return_value = mock_global_snapshot
    mock_regime_instance.compute_symbol_snapshot.return_value = MagicMock(iv_rank=50.0)
    mock_regime_instance.get_effective_regime.return_value = MagicMock(value="NORMAL")

    # Mock Truth Layer (quotes)
    mock_mdtl_instance = mock_mdtl.return_value
    mock_mdtl_instance.normalize_symbol.side_effect = lambda x: x
    mock_mdtl_instance.snapshot_many.return_value = {
        "TEST": {
            "quote": {"bid": 100.0, "ask": 101.0, "last": 100.5, "mid": 100.5}
        }
    }
    mock_mdtl_instance.daily_bars.return_value = [{"close": 100.0}] * 60

    mock_selector_instance = mock_selector.return_value
    mock_selector_instance.determine_strategy.return_value = {
        "strategy": "Credit Spread",
        "legs": [
            {"side": "buy", "type": "put", "delta_target": 0.05},
            {"side": "sell", "type": "put", "delta_target": 0.20}
        ]
    }

    # Mock Option Chain in TruthLayer
    valid_expiry = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

    # NOTE: 'expiry' key is what options_scanner looks for in the raw object
    long_contract = {
        "contract": "TEST_LONG_PUT",
        "strike": 90,
        "expiry": valid_expiry,  # Corrected key
        "right": "put",
        "greeks": {"delta": -0.05, "gamma":0, "vega":0, "theta":0},
        "quote": {"mid": 1.0, "last": 1.0, "bid": 0.9, "ask": 1.1}
    }

    short_contract = {
        "contract": "TEST_SHORT_PUT",
        "strike": 95,
        "expiry": valid_expiry, # Corrected key
        "right": "put",
        "greeks": {"delta": -0.20, "gamma":0, "vega":0, "theta":0},
        "quote": {"mid": 3.0, "last": 3.0, "bid": 2.9, "ask": 3.1}
    }

    mock_mdtl_instance.option_chain.return_value = [long_contract, short_contract]

    # Run scan
    scan_for_opportunities(symbols=["TEST"])

    # Assert
    assert mock_calc_ev.called
    call_args = mock_calc_ev.call_args
    kwargs = call_args.kwargs

    assert kwargs['strategy'] == 'credit_spread'

    # The crucial assertion:
    # Original code passes long_leg['delta'] -> abs(-0.05) = 0.05
    # Correct code should pass short_leg['delta'] -> abs(-0.20) = 0.20

    passed_delta = kwargs['delta']
    print(f"Passed delta: {passed_delta}")

    assert passed_delta == 0.20, f"Expected delta 0.20 from short leg, got {passed_delta}"
