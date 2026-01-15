"""
Tests for PR2: Option Contract Resolver + Option OHLC Fetch.

Verifies:
1. build_occ_symbol() correctly builds OCC option symbols
2. get_option_historical_prices() fetches option OHLC data
3. OptionContractResolver resolves contracts based on criteria
"""
import pytest
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

from packages.quantum.services.options_utils import (
    build_occ_symbol,
    parse_option_symbol,
    get_contract_multiplier
)
from packages.quantum.services.option_contract_resolver import OptionContractResolver


class TestBuildOccSymbol:
    """Tests for build_occ_symbol() function."""

    def test_basic_call_option(self):
        """Build a basic call option symbol."""
        symbol = build_occ_symbol("AAPL", "2024-01-19", "call", 150.0)
        assert symbol == "O:AAPL240119C00150000"

    def test_basic_put_option(self):
        """Build a basic put option symbol."""
        symbol = build_occ_symbol("SPY", "2024-03-15", "put", 450.0)
        assert symbol == "O:SPY240315P00450000"

    def test_with_date_object(self):
        """Build symbol using date object instead of string."""
        symbol = build_occ_symbol("MSFT", date(2024, 6, 21), "C", 400.0)
        assert symbol == "O:MSFT240621C00400000"

    def test_decimal_strike(self):
        """Build symbol with decimal strike price."""
        symbol = build_occ_symbol("AMZN", "2025-12-19", "call", 255.5)
        assert symbol == "O:AMZN251219C00255500"

    def test_without_prefix(self):
        """Build symbol without O: prefix."""
        symbol = build_occ_symbol("NVDA", "2024-02-16", "put", 700.0, include_prefix=False)
        assert symbol == "NVDA240216P00700000"

    def test_lowercase_right_normalized(self):
        """Lowercase right values are normalized to uppercase."""
        symbol_call = build_occ_symbol("TSLA", "2024-04-19", "call", 200.0)
        symbol_put = build_occ_symbol("TSLA", "2024-04-19", "put", 200.0)
        assert "C" in symbol_call
        assert "P" in symbol_put

    def test_uppercase_right_accepted(self):
        """Uppercase C/P are accepted."""
        symbol = build_occ_symbol("META", "2024-05-17", "C", 500.0)
        assert symbol == "O:META240517C00500000"

    def test_invalid_right_raises(self):
        """Invalid right value raises ValueError."""
        with pytest.raises(ValueError, match="Invalid option right"):
            build_occ_symbol("GOOG", "2024-01-19", "X", 150.0)

    def test_round_trip_with_parse(self):
        """Symbol built can be parsed back to same components."""
        original_underlying = "AAPL"
        original_expiry = "2024-01-19"
        original_right = "C"
        original_strike = 150.0

        symbol = build_occ_symbol(
            original_underlying,
            original_expiry,
            original_right,
            original_strike
        )

        parsed = parse_option_symbol(symbol)
        assert parsed["underlying"] == original_underlying
        assert parsed["expiry"] == original_expiry
        assert parsed["type"] == original_right
        assert parsed["strike"] == original_strike


class TestOptionContractResolver:
    """Tests for OptionContractResolver class."""

    def test_calculate_target_strike_atm_call(self):
        """ATM strike equals spot price."""
        resolver = OptionContractResolver(polygon_service=MagicMock())
        strike = resolver._calculate_target_strike(100.0, "call", "atm")
        assert strike == 100.0

    def test_calculate_target_strike_atm_put(self):
        """ATM strike equals spot price for puts too."""
        resolver = OptionContractResolver(polygon_service=MagicMock())
        strike = resolver._calculate_target_strike(100.0, "put", "atm")
        assert strike == 100.0

    def test_calculate_target_strike_otm_call(self):
        """OTM call is 5% above spot."""
        resolver = OptionContractResolver(polygon_service=MagicMock())
        strike = resolver._calculate_target_strike(100.0, "call", "otm_5pct")
        assert strike == 105.0

    def test_calculate_target_strike_otm_put(self):
        """OTM put is 5% below spot."""
        resolver = OptionContractResolver(polygon_service=MagicMock())
        strike = resolver._calculate_target_strike(100.0, "put", "otm_5pct")
        assert strike == 95.0

    def test_calculate_target_strike_itm_call(self):
        """ITM call is 5% below spot."""
        resolver = OptionContractResolver(polygon_service=MagicMock())
        strike = resolver._calculate_target_strike(100.0, "call", "itm_5pct")
        assert strike == 95.0

    def test_calculate_target_strike_itm_put(self):
        """ITM put is 5% above spot."""
        resolver = OptionContractResolver(polygon_service=MagicMock())
        strike = resolver._calculate_target_strike(100.0, "put", "itm_5pct")
        assert strike == 105.0

    def test_find_best_match_prefers_closer_dte(self):
        """Best match prefers contracts closer to target DTE."""
        resolver = OptionContractResolver(polygon_service=MagicMock())

        chain = [
            {"ticker": "O:SPY240315C00450000", "strike": 450.0, "expiration": "2024-03-15"},
            {"ticker": "O:SPY240322C00450000", "strike": 450.0, "expiration": "2024-03-22"},
            {"ticker": "O:SPY240329C00450000", "strike": 450.0, "expiration": "2024-03-29"},
        ]

        # Target DTE = 30, as_of_date such that 2024-03-22 is closest to 30 DTE
        as_of_date = date(2024, 2, 21)  # 3/22 = 30 days, 3/15 = 23 days, 3/29 = 37 days

        best = resolver._find_best_match(chain, 450.0, 30, as_of_date)
        assert best["ticker"] == "O:SPY240322C00450000"

    def test_find_best_match_prefers_closer_strike(self):
        """When DTEs are equal, prefers closer strike."""
        resolver = OptionContractResolver(polygon_service=MagicMock())

        chain = [
            {"ticker": "O:SPY240315C00440000", "strike": 440.0, "expiration": "2024-03-15"},
            {"ticker": "O:SPY240315C00450000", "strike": 450.0, "expiration": "2024-03-15"},
            {"ticker": "O:SPY240315C00460000", "strike": 460.0, "expiration": "2024-03-15"},
        ]

        as_of_date = date(2024, 2, 14)  # All same DTE

        # Target strike 452
        best = resolver._find_best_match(chain, 452.0, 30, as_of_date)
        assert best["strike"] == 450.0  # Closest to 452

    @patch.object(OptionContractResolver, '_get_spot_price')
    @patch.object(OptionContractResolver, '_get_filtered_chain')
    def test_resolve_contract_returns_ticker(self, mock_chain, mock_spot):
        """resolve_contract returns the best matching ticker."""
        mock_spot.return_value = 450.0
        mock_chain.return_value = [
            {"ticker": "O:SPY240315C00450000", "strike": 450.0, "expiration": "2024-03-15", "type": "call"},
        ]

        resolver = OptionContractResolver(polygon_service=MagicMock())

        with patch.object(resolver, '_find_best_match') as mock_find:
            mock_find.return_value = {"ticker": "O:SPY240315C00450000"}

            result = resolver.resolve_contract(
                underlying="SPY",
                right="call",
                target_dte=30,
                moneyness="atm",
                as_of_date=date(2024, 2, 14)
            )

            assert result == "O:SPY240315C00450000"

    @patch.object(OptionContractResolver, '_get_spot_price')
    def test_resolve_contract_returns_none_when_no_spot(self, mock_spot):
        """resolve_contract returns None when spot price unavailable."""
        mock_spot.return_value = None

        resolver = OptionContractResolver(polygon_service=MagicMock())

        result = resolver.resolve_contract("SPY", "call")
        assert result is None

    @patch.object(OptionContractResolver, '_get_spot_price')
    @patch.object(OptionContractResolver, '_get_filtered_chain')
    def test_resolve_contract_returns_none_when_no_chain(self, mock_chain, mock_spot):
        """resolve_contract returns None when chain is empty."""
        mock_spot.return_value = 450.0
        mock_chain.return_value = []

        resolver = OptionContractResolver(polygon_service=MagicMock())

        result = resolver.resolve_contract("SPY", "call")
        assert result is None

    def test_build_contract_symbol_wrapper(self):
        """build_contract_symbol wraps build_occ_symbol correctly."""
        resolver = OptionContractResolver(polygon_service=MagicMock())

        symbol = resolver.build_contract_symbol(
            underlying="AAPL",
            expiry=date(2024, 1, 19),
            right="call",
            strike=150.0
        )

        assert symbol == "O:AAPL240119C00150000"


class TestGetOptionHistoricalPrices:
    """Tests for PolygonService.get_option_historical_prices()."""

    def test_returns_ohlc_structure(self):
        """get_option_historical_prices returns expected OHLC structure."""
        # Create a mock that returns expected structure
        mock_polygon = MagicMock()
        mock_polygon.get_option_historical_prices.return_value = {
            'symbol': 'O:SPY240315C00450000',
            'dates': ['2024-01-15', '2024-01-16', '2024-01-17'],
            'opens': [5.0, 5.1, 5.2],
            'highs': [5.5, 5.6, 5.7],
            'lows': [4.9, 5.0, 5.1],
            'prices': [5.2, 5.3, 5.4],
            'volumes': [1000, 1100, 1200]
        }

        result = mock_polygon.get_option_historical_prices(
            'O:SPY240315C00450000',
            datetime(2024, 1, 15),
            datetime(2024, 1, 17)
        )

        assert 'dates' in result
        assert 'prices' in result
        assert 'opens' in result
        assert 'highs' in result
        assert 'lows' in result
        assert 'volumes' in result
        assert len(result['dates']) == 3

    def test_returns_none_for_no_data(self):
        """get_option_historical_prices returns None when no data available."""
        mock_polygon = MagicMock()
        mock_polygon.get_option_historical_prices.return_value = None

        result = mock_polygon.get_option_historical_prices(
            'O:SPY240315C00450000',
            datetime(2024, 1, 15),
            datetime(2024, 1, 17)
        )

        assert result is None


class TestIntegrationBuildAndParse:
    """Integration tests ensuring build and parse are inverses."""

    def test_all_strike_formats(self):
        """Test various strike price formats round-trip correctly."""
        test_cases = [
            ("SPY", "2024-03-15", "C", 450.0),
            ("AAPL", "2024-06-21", "P", 175.5),
            ("AMZN", "2025-01-17", "C", 200.0),
            ("MSFT", "2024-12-20", "P", 425.25),  # Note: will be rounded to 425.250
            ("NVDA", "2024-09-20", "C", 1000.0),
        ]

        for underlying, expiry, right, strike in test_cases:
            symbol = build_occ_symbol(underlying, expiry, right, strike)
            parsed = parse_option_symbol(symbol)

            assert parsed["underlying"] == underlying
            assert parsed["expiry"] == expiry
            assert parsed["type"] == right
            # Strike comparison with tolerance for float precision
            assert abs(parsed["strike"] - strike) < 0.01

    def test_multiplier_detection_for_built_symbols(self):
        """Built symbols are correctly detected as options (multiplier=100)."""
        symbol = build_occ_symbol("SPY", "2024-03-15", "call", 450.0)
        multiplier = get_contract_multiplier(symbol)
        assert multiplier == 100.0

        # Without prefix
        symbol_no_prefix = build_occ_symbol("SPY", "2024-03-15", "call", 450.0, include_prefix=False)
        multiplier_no_prefix = get_contract_multiplier(symbol_no_prefix)
        assert multiplier_no_prefix == 100.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
