"""
Tests for PR6: Option resolver with historical OHLC coverage validation.

Verifies:
1. resolve_contract_with_coverage picks contract with sufficient bars
2. Falls back to next candidate when first has insufficient bars
3. Returns None when no candidates meet min_bars requirement
4. Backward compatible: works without window params
"""
import pytest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch, call

from packages.quantum.services.option_contract_resolver import OptionContractResolver


class TestResolveContractWithCoverage:
    """Tests for resolve_contract_with_coverage method."""

    def test_picks_candidate_with_sufficient_bars(self):
        """Selects first candidate that meets min_bars requirement."""
        mock_polygon = MagicMock()

        # Mock spot price
        mock_polygon.get_recent_quote.return_value = {"price": 450.0}

        # Mock option chain with two candidates
        mock_polygon.get_option_chain.return_value = [
            {"ticker": "O:SPY240315C00450000", "strike": 450.0, "expiration": "2024-03-15", "type": "call"},
            {"ticker": "O:SPY240322C00450000", "strike": 450.0, "expiration": "2024-03-22", "type": "call"},
        ]

        # Mock historical prices - first has 90 bars (sufficient)
        def mock_option_hist(ticker, start_date, end_date):
            if ticker == "O:SPY240315C00450000":
                return {"prices": [5.0] * 90, "dates": ["2024-01-01"] * 90}
            return {"prices": [5.0] * 30, "dates": ["2024-01-01"] * 30}

        mock_polygon.get_option_historical_prices.side_effect = mock_option_hist

        resolver = OptionContractResolver(polygon_service=mock_polygon)

        result = resolver.resolve_contract_with_coverage(
            underlying="SPY",
            right="call",
            target_dte=30,
            moneyness="atm",
            as_of_date=date(2024, 2, 14),
            window_start=date(2024, 1, 1),
            window_end=date(2024, 3, 31),
            min_bars=60
        )

        assert result == "O:SPY240315C00450000"

    def test_skips_candidate_with_insufficient_bars(self):
        """Skips first candidate when it has insufficient bars, picks second."""
        mock_polygon = MagicMock()

        mock_polygon.get_recent_quote.return_value = {"price": 450.0}

        # Two candidates - first is "better" by score but has insufficient bars
        mock_polygon.get_option_chain.return_value = [
            {"ticker": "O:SPY240315C00450000", "strike": 450.0, "expiration": "2024-03-15", "type": "call"},
            {"ticker": "O:SPY240322C00450000", "strike": 450.0, "expiration": "2024-03-22", "type": "call"},
        ]

        # First candidate has only 14 bars, second has 90
        def mock_option_hist(ticker, start_date, end_date):
            if ticker == "O:SPY240315C00450000":
                return {"prices": [5.0] * 14, "dates": ["2024-01-01"] * 14}  # Insufficient
            elif ticker == "O:SPY240322C00450000":
                return {"prices": [5.0] * 90, "dates": ["2024-01-01"] * 90}  # Sufficient
            return None

        mock_polygon.get_option_historical_prices.side_effect = mock_option_hist

        resolver = OptionContractResolver(polygon_service=mock_polygon)

        result = resolver.resolve_contract_with_coverage(
            underlying="SPY",
            right="call",
            target_dte=30,
            moneyness="atm",
            as_of_date=date(2024, 2, 14),
            window_start=date(2024, 1, 1),
            window_end=date(2024, 3, 31),
            min_bars=60
        )

        # Should pick second candidate since first has only 14 bars
        assert result == "O:SPY240322C00450000"

    def test_returns_none_when_no_candidates_meet_min_bars(self):
        """Returns None when no candidates have sufficient bars."""
        mock_polygon = MagicMock()

        mock_polygon.get_recent_quote.return_value = {"price": 450.0}

        mock_polygon.get_option_chain.return_value = [
            {"ticker": "O:SPY240315C00450000", "strike": 450.0, "expiration": "2024-03-15", "type": "call"},
            {"ticker": "O:SPY240322C00450000", "strike": 450.0, "expiration": "2024-03-22", "type": "call"},
        ]

        # Both candidates have insufficient bars
        def mock_option_hist(ticker, start_date, end_date):
            return {"prices": [5.0] * 14, "dates": ["2024-01-01"] * 14}

        mock_polygon.get_option_historical_prices.side_effect = mock_option_hist

        resolver = OptionContractResolver(polygon_service=mock_polygon)

        result = resolver.resolve_contract_with_coverage(
            underlying="SPY",
            right="call",
            target_dte=30,
            moneyness="atm",
            as_of_date=date(2024, 2, 14),
            window_start=date(2024, 1, 1),
            window_end=date(2024, 3, 31),
            min_bars=60
        )

        assert result is None

    def test_falls_back_to_basic_resolution_without_window(self):
        """Falls back to basic resolve_contract when window not specified."""
        mock_polygon = MagicMock()

        mock_polygon.get_recent_quote.return_value = {"price": 450.0}

        mock_polygon.get_option_chain.return_value = [
            {"ticker": "O:SPY240315C00450000", "strike": 450.0, "expiration": "2024-03-15", "type": "call"},
        ]

        resolver = OptionContractResolver(polygon_service=mock_polygon)

        # Call without window params
        result = resolver.resolve_contract_with_coverage(
            underlying="SPY",
            right="call",
            target_dte=30,
            moneyness="atm",
            as_of_date=date(2024, 2, 14)
            # No window_start, window_end
        )

        # Should return result without checking historical bars
        assert result == "O:SPY240315C00450000"
        # Should NOT call get_option_historical_prices
        mock_polygon.get_option_historical_prices.assert_not_called()

    def test_handles_none_historical_response(self):
        """Handles None response from get_option_historical_prices gracefully."""
        mock_polygon = MagicMock()

        mock_polygon.get_recent_quote.return_value = {"price": 450.0}

        mock_polygon.get_option_chain.return_value = [
            {"ticker": "O:SPY240315C00450000", "strike": 450.0, "expiration": "2024-03-15", "type": "call"},
            {"ticker": "O:SPY240322C00450000", "strike": 450.0, "expiration": "2024-03-22", "type": "call"},
        ]

        # First returns None, second has sufficient bars
        def mock_option_hist(ticker, start_date, end_date):
            if ticker == "O:SPY240315C00450000":
                return None  # No data
            return {"prices": [5.0] * 90, "dates": ["2024-01-01"] * 90}

        mock_polygon.get_option_historical_prices.side_effect = mock_option_hist

        resolver = OptionContractResolver(polygon_service=mock_polygon)

        result = resolver.resolve_contract_with_coverage(
            underlying="SPY",
            right="call",
            target_dte=30,
            moneyness="atm",
            as_of_date=date(2024, 2, 14),
            window_start=date(2024, 1, 1),
            window_end=date(2024, 3, 31),
            min_bars=60
        )

        # Should skip first (None) and pick second
        assert result == "O:SPY240322C00450000"

    def test_handles_exception_during_historical_fetch(self):
        """Handles exception during historical fetch gracefully."""
        mock_polygon = MagicMock()

        mock_polygon.get_recent_quote.return_value = {"price": 450.0}

        mock_polygon.get_option_chain.return_value = [
            {"ticker": "O:SPY240315C00450000", "strike": 450.0, "expiration": "2024-03-15", "type": "call"},
            {"ticker": "O:SPY240322C00450000", "strike": 450.0, "expiration": "2024-03-22", "type": "call"},
        ]

        # First raises exception, second succeeds
        call_count = [0]
        def mock_option_hist(ticker, start_date, end_date):
            call_count[0] += 1
            if call_count[0] == 1:
                raise Exception("API error")
            return {"prices": [5.0] * 90, "dates": ["2024-01-01"] * 90}

        mock_polygon.get_option_historical_prices.side_effect = mock_option_hist

        resolver = OptionContractResolver(polygon_service=mock_polygon)

        result = resolver.resolve_contract_with_coverage(
            underlying="SPY",
            right="call",
            target_dte=30,
            moneyness="atm",
            as_of_date=date(2024, 2, 14),
            window_start=date(2024, 1, 1),
            window_end=date(2024, 3, 31),
            min_bars=60
        )

        # Should skip first (exception) and pick second
        assert result == "O:SPY240322C00450000"

    def test_respects_max_candidates_limit(self):
        """Only checks up to max_candidates for coverage."""
        mock_polygon = MagicMock()

        mock_polygon.get_recent_quote.return_value = {"price": 450.0}

        # Create 50 candidates
        candidates = [
            {"ticker": f"O:SPY24031{i}C00450000", "strike": 450.0, "expiration": f"2024-03-{15+i}", "type": "call"}
            for i in range(50)
        ]
        mock_polygon.get_option_chain.return_value = candidates

        # All return insufficient bars
        mock_polygon.get_option_historical_prices.return_value = {
            "prices": [5.0] * 14,
            "dates": ["2024-01-01"] * 14
        }

        resolver = OptionContractResolver(polygon_service=mock_polygon)

        result = resolver.resolve_contract_with_coverage(
            underlying="SPY",
            right="call",
            target_dte=30,
            moneyness="atm",
            as_of_date=date(2024, 2, 14),
            window_start=date(2024, 1, 1),
            window_end=date(2024, 3, 31),
            min_bars=60,
            max_candidates=10  # Only check 10
        )

        # Should only call historical prices 10 times (not 50)
        assert mock_polygon.get_option_historical_prices.call_count == 10
        assert result is None


class TestScoreCandidates:
    """Tests for _score_candidates helper method."""

    def test_scores_by_dte_and_strike(self):
        """Candidates are scored by DTE and strike proximity."""
        mock_polygon = MagicMock()
        resolver = OptionContractResolver(polygon_service=mock_polygon)

        chain = [
            {"ticker": "A", "strike": 450.0, "expiration": "2024-03-15", "type": "call"},  # DTE=30
            {"ticker": "B", "strike": 455.0, "expiration": "2024-03-15", "type": "call"},  # DTE=30, farther strike
            {"ticker": "C", "strike": 450.0, "expiration": "2024-03-22", "type": "call"},  # DTE=37, closer strike
        ]

        scored = resolver._score_candidates(
            chain,
            target_strike=450.0,
            target_dte=30,
            as_of_date=date(2024, 2, 14)
        )

        # First should be A (closest DTE and strike)
        tickers = [s[1]["ticker"] for s in scored]
        assert tickers[0] == "A"

    def test_filters_expired_contracts(self):
        """Expired contracts are filtered out."""
        mock_polygon = MagicMock()
        resolver = OptionContractResolver(polygon_service=mock_polygon)

        chain = [
            {"ticker": "A", "strike": 450.0, "expiration": "2024-02-01", "type": "call"},  # Expired
            {"ticker": "B", "strike": 450.0, "expiration": "2024-03-15", "type": "call"},  # Valid
        ]

        scored = resolver._score_candidates(
            chain,
            target_strike=450.0,
            target_dte=30,
            as_of_date=date(2024, 2, 14)
        )

        # Only B should be included
        assert len(scored) == 1
        assert scored[0][1]["ticker"] == "B"


class TestValidationServiceUsesWindowAwareResolver:
    """Tests that GoLiveValidationService uses window-aware resolution."""

    @patch('packages.quantum.services.go_live_validation_service.OptionContractResolver')
    @patch('packages.quantum.services.go_live_validation_service.BacktestEngine')
    def test_eval_historical_uses_resolve_contract_with_coverage(self, mock_engine_class, mock_resolver_class):
        """eval_historical calls resolve_contract_with_coverage with window params."""
        from packages.quantum.services.go_live_validation_service import GoLiveValidationService

        mock_supabase = MagicMock()
        mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
            "user_id": "test-user",
            "paper_baseline_capital": 10000,
            "paper_ready": False,
            "historical_last_result": {}
        }
        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        # Setup resolver mock
        mock_resolver = MagicMock()
        mock_resolver.resolve_contract_with_coverage.return_value = "O:SPY240315C00450000"
        mock_resolver_class.return_value = mock_resolver

        # Setup backtest engine mock
        mock_engine = MagicMock()
        mock_bt_result = MagicMock()
        mock_bt_result.equity_curve = [{"equity": 11000}]
        mock_bt_result.trades = [{"exit_date": "2024-02-15", "pnl": 1000}]
        mock_engine.run_single.return_value = mock_bt_result
        mock_engine_class.return_value = mock_engine

        service = GoLiveValidationService(mock_supabase)

        result = service.eval_historical("test-user", {
            "symbol": "SPY",
            "instrument_type": "option",
            "option_right": "call",
            "option_dte": 30,
            "option_moneyness": "atm",
            "window_days": 90,
            "concurrent_runs": 1,
            "use_rolling_contracts": False  # PR7: Test static mode
        })

        # Verify resolve_contract_with_coverage was called (not resolve_contract)
        mock_resolver.resolve_contract_with_coverage.assert_called()

        # Verify window params were passed
        call_kwargs = mock_resolver.resolve_contract_with_coverage.call_args.kwargs
        assert "window_start" in call_kwargs
        assert "window_end" in call_kwargs
        assert "min_bars" in call_kwargs


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
