
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from packages.quantum.options_scanner import scan_for_opportunities, RegimeState

@pytest.fixture
def mock_dependencies():
    with patch('packages.quantum.options_scanner.PolygonService') as MockPolygon, \
         patch('packages.quantum.options_scanner.StrategySelector') as MockStrategy, \
         patch('packages.quantum.options_scanner.UniverseService') as MockUniverse, \
         patch('packages.quantum.options_scanner.ExecutionService') as MockExecution, \
         patch('packages.quantum.options_scanner.RegimeEngineV3') as MockRegime, \
         patch('packages.quantum.options_scanner.IVRepository') as MockIVRepo, \
         patch('packages.quantum.options_scanner.calculate_ev') as MockCalcEv, \
         patch('packages.quantum.options_scanner.calculate_unified_score') as MockCalcScore:

        # Setup mocks
        mock_market = MockPolygon.return_value

        mock_ev = MagicMock()
        mock_ev.expected_value = 20.0 # High EV to avoid rejection
        MockCalcEv.return_value = mock_ev

        mock_score = MagicMock()
        mock_score.score = 80.0
        mock_score.badges = []
        mock_score.components.dict.return_value = {}
        MockCalcScore.return_value = mock_score

        mock_strategy = MockStrategy.return_value
        mock_universe = MockUniverse.return_value
        mock_execution = MockExecution.return_value
        mock_regime = MockRegime.return_value

        # Default regime snapshot
        mock_snapshot = MagicMock()
        mock_snapshot.state = RegimeState.NORMAL
        mock_snapshot.to_dict.return_value = {"state": "NORMAL", "iv_regime": "NORMAL"}
        mock_regime.compute_global_snapshot.return_value = mock_snapshot
        mock_regime._default_global_snapshot.return_value = mock_snapshot

        # Default symbol snapshot
        mock_sym_snapshot = MagicMock()
        mock_sym_snapshot.iv_rank = 50.0
        mock_regime.compute_symbol_snapshot.return_value = mock_sym_snapshot
        mock_regime.get_effective_regime.return_value = RegimeState.NORMAL

        # Default market data
        mock_market.get_recent_quote.return_value = {"price": 100.0, "bid_price": 99.5, "ask_price": 100.5}
        mock_market.get_historical_prices.return_value = [{"close": 100.0}] * 60
        mock_market.get_option_chain.return_value = [
            {"ticker": "O:SYM250101C00100000", "strike": 100.0, "expiration": "2025-01-01", "type": "call", "delta": 0.5, "price": 2.0}
        ]

        # Default strategy
        mock_strategy.determine_strategy.return_value = {
            "strategy": "long_call",
            "legs": [{"delta_target": 0.5, "side": "buy", "type": "call"}]
        }

        yield {
            "market": mock_market,
            "strategy": mock_strategy,
            "universe": mock_universe,
            "execution": mock_execution,
            "regime": mock_regime
        }

def test_scan_for_opportunities_calls_drag_stats_once(mock_dependencies):
    mock_execution = mock_dependencies["execution"]
    mock_execution.get_batch_execution_drag_stats.return_value = {
        "TEST": {"avg_drag": 0.02, "n": 10}
    }

    # Mock supabase client
    mock_supabase = MagicMock()

    # Run scan
    scan_for_opportunities(
        symbols=["TEST"],
        supabase_client=mock_supabase,
        user_id="user123"
    )

    # Verify get_batch_execution_drag_stats called EXACTLY once
    assert mock_execution.get_batch_execution_drag_stats.call_count == 1

    # Verify logic uses the stats
    # We can check if get_batch_execution_drag_stats was called with correct params
    mock_execution.get_batch_execution_drag_stats.assert_called_with(
        user_id="user123",
        symbols=["TEST"],
        lookback_days=45,
        min_samples=3
    )

def test_scan_uses_fallback_with_details_if_no_stats(mock_dependencies):
    mock_execution = mock_dependencies["execution"]
    # Return empty drag stats
    mock_execution.get_batch_execution_drag_stats.return_value = {}

    # Mock supabase client
    mock_supabase = MagicMock()

    # Run scan
    scan_for_opportunities(
        symbols=["TEST"],
        supabase_client=mock_supabase,
        user_id="user123"
    )

    # Verify estimate_execution_cost called (fallback) with specific args
    assert mock_execution.estimate_execution_cost.called

    # Verify it was called with entry_cost and num_legs
    call_kwargs = mock_execution.estimate_execution_cost.call_args[1]
    assert "entry_cost" in call_kwargs
    assert "num_legs" in call_kwargs
    assert call_kwargs["entry_cost"] == 2.0  # from mock chain price
    assert call_kwargs["num_legs"] == 1      # from mock strategy
