import pytest
from unittest.mock import MagicMock, patch
from packages.quantum.options_scanner import scan_for_opportunities

def test_scanner_scoring_logic():
    # Mock UniverseService and PolygonService to return controlled data
    with patch('packages.quantum.options_scanner.UniverseService') as mock_universe:
        with patch('packages.quantum.options_scanner.PolygonService') as mock_poly:
            with patch('packages.quantum.options_scanner.enrich_trade_suggestions') as mock_enrich:

                # Mock enrich returning a candidate without score but with metrics
                mock_enrich.return_value = [{
                    "symbol": "TEST",
                    "metrics": {
                        "iv_rank": 50, # 0.5
                        "probability_of_profit": 0.6, # 0.6
                        "reward_to_risk": 1.5 # 1.5/3.0 = 0.5
                    },
                    "score": None
                }]

                # Setup basic mocks to avoid crash
                mock_poly.return_value.get_historical_prices.return_value = {'prices': [100.0]}
                mock_poly.return_value.get_recent_quote.return_value = {'bid': 100.0, 'ask': 101.0}
                # Fix iv_rank to avoid Mock vs int comparison in classify_iv_regime
                mock_poly.return_value.get_iv_rank.return_value = 50.0
                mock_poly.return_value.get_trend.return_value = "UP"

                results = scan_for_opportunities(symbols=['TEST'])

                # Verify calculation
                # Score = 100 * (0.5 + 0.6 + 0.5) / 3 = 100 * 1.6 / 3 = 53.33
                assert len(results) == 1
                score = results[0]['score']
                assert score is not None
                assert 53 < score < 54

def test_scanner_null_score():
    with patch('packages.quantum.options_scanner.UniverseService'):
        with patch('packages.quantum.options_scanner.PolygonService') as mock_poly:
            with patch('packages.quantum.options_scanner.enrich_trade_suggestions') as mock_enrich:

                # Configure PolygonService to return valid floats/dicts
                mock_poly.return_value.get_recent_quote.return_value = {'bid': 100.0, 'ask': 101.0}
                mock_poly.return_value.get_historical_prices.return_value = {'prices': [100.0]}
                mock_poly.return_value.get_iv_rank.return_value = 50.0
                mock_poly.return_value.get_trend.return_value = "UP"

                # Mock candidate with NO metrics
                mock_enrich.return_value = [{
                    "symbol": "TEST",
                    "metrics": None,
                    "score": None # Ensure input score is None
                }]

                results = scan_for_opportunities(symbols=['TEST'])
                assert len(results) == 1
                assert results[0]['score'] is None
