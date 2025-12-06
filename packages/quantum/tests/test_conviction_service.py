import pytest
from unittest.mock import MagicMock
from packages.quantum.analytics.conviction_service import ConvictionService, PositionDescriptor
from packages.quantum.analytics.regime_scoring import ScoringEngine

class TestConvictionService:

    @pytest.fixture
    def mock_scoring(self):
        engine = MagicMock(spec=ScoringEngine)
        return engine

    @pytest.fixture
    def service(self, mock_scoring):
        return ConvictionService(scoring_engine=mock_scoring, supabase=None)

    def test_get_portfolio_conviction_bullish_aligned(self, service, mock_scoring):
        # Setup
        # Mock ScoringEngine to return a bullish score (e.g., 80)
        mock_scoring.calculate_score.return_value = {
            "raw_score": 80.0,
            "regime_used": "normal"
        }

        pos = PositionDescriptor(
            symbol="AAPL",
            underlying="AAPL",
            strategy_type="debit_call",
            direction="long",
            iv_rank=50.0
        )

        regime_context = {"current_regime": "normal", "universe_median": 50.0}

        # Action
        conv_map = service.get_portfolio_conviction([pos], regime_context)

        # Assert
        # 80 score -> high conviction. Direction matches (long call is bullish).
        # We expect conviction > 0.5.
        assert "AAPL" in conv_map
        assert conv_map["AAPL"] > 0.5

    def test_get_portfolio_conviction_misaligned_direction(self, service, mock_scoring):
        # Setup
        # Bearish score (e.g., 20) for a Long Call
        mock_scoring.calculate_score.return_value = {
            "raw_score": 20.0,
            "regime_used": "normal"
        }

        pos = PositionDescriptor(
            symbol="AAPL",
            underlying="AAPL",
            strategy_type="debit_call",
            direction="long",
            iv_rank=50.0
        )

        regime_context = {"current_regime": "normal", "universe_median": 50.0}

        # Action
        conv_map = service.get_portfolio_conviction([pos], regime_context)

        # Assert
        # Direction mismatch should clamp to 0.0
        assert conv_map["AAPL"] == 0.0

    def test_get_portfolio_conviction_neutral(self, service, mock_scoring):
        # Neutral score (50) for Iron Condor
        mock_scoring.calculate_score.return_value = {
            "raw_score": 50.0,
            "regime_used": "normal"
        }

        pos = PositionDescriptor(
            symbol="SPY",
            underlying="SPY",
            strategy_type="iron_condor",
            direction="neutral",
            iv_rank=50.0
        )

        # Action
        conv_map = service.get_portfolio_conviction([pos], {})

        # Assert
        # Should be reasonable conviction (mid)
        # 50 vs mu 50 -> 0.5 roughly
        assert conv_map["SPY"] > 0.3

    def test_handles_scoring_failure(self, service, mock_scoring):
        mock_scoring.calculate_score.side_effect = Exception("Boom")

        pos = PositionDescriptor(
            symbol="SPY",
            underlying="SPY",
            strategy_type="long_stock",
            direction="long"
        )

        conv_map = service.get_portfolio_conviction([pos], {})

        # Assert default 0.5
        assert conv_map["SPY"] == 0.5
