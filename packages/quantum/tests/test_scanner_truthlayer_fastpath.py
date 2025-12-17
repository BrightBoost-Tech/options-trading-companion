import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from packages.quantum.options_scanner import scan_for_opportunities

def test_scanner_uses_truthlayer_fastpath():
    """
    Verifies that scan_for_opportunities:
    1. Instantiates MarketDataTruthLayer
    2. Calls snapshot_many for quotes
    3. Calls daily_bars for history
    4. Calls option_chain for contract chain
    5. Does NOT call PolygonService for these when TruthLayer provides data
    """

    # 1. Mock Data
    mock_symbol = "AAPL"
    mock_symbols = [mock_symbol]

    mock_quote = {
        "bid": 150.0,
        "ask": 150.1,
        "mid": 150.05,
        "last": 150.05
    }

    mock_snapshot_item = {
        "ticker": mock_symbol,
        "quote": mock_quote,
        "day": {"c": 150.05},
        "greeks": {}
    }

    mock_bars = [{"date": "2024-01-01", "close": 100.0 + i} for i in range(60)] # Rising trend

    # Use tight spreads to pass liquidity guardrail (spread/cost < 10%)
    mock_chain_item = {
        "contract": "O:AAPL240621C00150000",
        "ticker": "O:AAPL240621C00150000",
        "underlying": "AAPL",
        "strike": 150.0,
        "expiration_date": "2024-06-21",
        "expiry": "2024-06-21",
        "right": "call",
        "contract_type": "call",
        "type": "call",
        "quote": {"bid": 4.95, "ask": 5.05, "mid": 5.0, "last": 5.0},
        "greeks": {
            "delta": 0.5,
            "gamma": 0.05,
            "vega": 0.1,
            "theta": -0.05
        }
    }

    mock_chain = [
        mock_chain_item,
        {
            **mock_chain_item,
            "strike": 155.0,
            "greeks": {"delta": 0.3, "gamma": 0.04, "vega": 0.1, "theta": -0.05},
            "quote": {"bid": 1.95, "ask": 2.05, "mid": 2.0, "last": 2.0},
            "contract": "O:AAPL240621C00155000"
        }
    ]

    # 2. Patch dependencies
    with patch("packages.quantum.options_scanner.MarketDataTruthLayer") as MockTruthLayer, \
         patch("packages.quantum.options_scanner.PolygonService") as MockPolygonService, \
         patch("packages.quantum.options_scanner.StrategySelector") as MockStrategySelector, \
         patch("packages.quantum.options_scanner.calculate_ev") as mock_calc_ev, \
         patch("packages.quantum.options_scanner.calculate_unified_score") as mock_calc_score, \
         patch("packages.quantum.options_scanner.RegimeEngineV3") as MockRegimeEngine:

        # Setup TruthLayer mock
        truth_instance = MockTruthLayer.return_value
        truth_instance.normalize_symbol.side_effect = lambda s: s
        truth_instance.snapshot_many.return_value = {mock_symbol: mock_snapshot_item}
        truth_instance.daily_bars.return_value = mock_bars
        truth_instance.option_chain.return_value = mock_chain

        # Setup PolygonService mock (Should NOT be called for data)
        poly_instance = MockPolygonService.return_value
        poly_instance.get_recent_quote.side_effect = Exception("PolygonService.get_recent_quote called!")
        poly_instance.get_historical_prices.side_effect = Exception("PolygonService.get_historical_prices called!")
        poly_instance.get_option_chain.side_effect = Exception("PolygonService.get_option_chain called!")

        # Setup Strategy
        selector_instance = MockStrategySelector.return_value
        selector_instance.determine_strategy.return_value = {
            "strategy": "Bull Call Spread",
            "legs": [
                {"type": "call", "side": "buy", "delta_target": 0.5},
                {"type": "call", "side": "sell", "delta_target": 0.3}
            ]
        }

        # Setup EV and Score
        mock_ev_obj = MagicMock()
        mock_ev_obj.expected_value = 100.0
        mock_calc_ev.return_value = mock_ev_obj

        mock_score_obj = MagicMock()
        mock_score_obj.score = 80.0
        mock_score_obj.execution_cost_dollars = 10.0
        mock_score_obj.components.dict.return_value = {}
        mock_score_obj.badges = []
        mock_calc_score.return_value = mock_score_obj

        # Setup Regime
        regime_instance = MockRegimeEngine.return_value
        regime_instance.compute_global_snapshot.return_value = MagicMock(state="NORMAL")
        regime_instance.compute_symbol_snapshot.return_value = MagicMock(iv_rank=50.0)
        regime_instance.get_effective_regime.return_value = MagicMock(value="NORMAL")

        # 3. Execute
        with patch("packages.quantum.options_scanner.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 5, 15)
            mock_datetime.strptime = datetime.strptime
            # Ensure timedelta is available

            candidates = scan_for_opportunities(symbols=mock_symbols)

        # 4. Assert
        assert len(candidates) == 1, f"Expected 1 candidate, got {len(candidates)}"

        cand = candidates[0]
        assert cand["symbol"] == mock_symbol
        assert cand["ev"] == 100.0

        # Verify TruthLayer usage
        truth_instance.snapshot_many.assert_any_call(mock_symbols)
        truth_instance.daily_bars.assert_called()

        # Verify option_chain was called with some args (we added args, so assert_called is safe)
        truth_instance.option_chain.assert_called()

        # Optional: Verify new args are passed
        # call_args = truth_instance.option_chain.call_args
        # assert "min_expiry" in call_args[1]

        # Verify PolygonService avoidance
        poly_instance.get_recent_quote.assert_not_called()
        poly_instance.get_historical_prices.assert_not_called()
        poly_instance.get_option_chain.assert_not_called()
