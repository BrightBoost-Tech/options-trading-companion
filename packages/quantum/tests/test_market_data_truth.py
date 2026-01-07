
import unittest
from unittest.mock import patch, MagicMock
from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer

class TestMarketDataTruthLayer(unittest.TestCase):

    def setUp(self):
        # Prevent real API calls by patching at class level or instance
        # We will mock requests in tests
        pass

    def test_normalize_symbol(self):
        layer = MarketDataTruthLayer(api_key="test")

        self.assertEqual(layer._normalize_symbol("AAPL"), "AAPL")
        self.assertEqual(layer._normalize_symbol("O:AAPL230616C00150000"), "O:AAPL230616C00150000")

        # Test heuristic
        self.assertEqual(layer._normalize_symbol("AAPL230616C00150000"), "O:AAPL230616C00150000")
        self.assertEqual(layer._normalize_symbol("SPY"), "SPY")

    @patch("packages.quantum.services.market_data_truth_layer.requests.Session.get")
    def test_snapshot_many_parsing(self, mock_get):
        layer = MarketDataTruthLayer(api_key="test")

        mock_response = {
            "results": [
                {
                    "ticker": "AAPL",
                    "type": "CS",
                    "last_quote": {"P": 150.10, "p": 150.00, "t": 123456789},
                    "session": {"close": 150.05, "volume": 1000},
                    "last_trade": {"p": 150.05},
                    "greeks": {} # stocks dont have greeks usually but ok
                },
                {
                    "ticker": "O:SPY231215C00450000",
                    "type": "O",
                    "last_quote": {"b": 5.00, "a": 5.20, "t": 987654321},
                    "session": {"close": 5.10},
                    "implied_volatility": 0.15,
                    "greeks": {"delta": 0.5, "gamma": 0.05, "theta": -0.1, "vega": 0.2}
                }
            ]
        }

        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = mock_response

        results = layer.snapshot_many(["AAPL", "SPY231215C00450000"])

        # Check AAPL
        aapl = results["AAPL"]
        self.assertEqual(aapl["quote"]["bid"], 150.00)
        self.assertEqual(aapl["quote"]["ask"], 150.10)
        self.assertEqual(aapl["quote"]["mid"], 150.05)
        self.assertEqual(aapl["day"]["c"], 150.05)

        # Check Option
        opt = results["O:SPY231215C00450000"]
        self.assertEqual(opt["quote"]["bid"], 5.00)
        self.assertEqual(opt["quote"]["ask"], 5.20)
        self.assertAlmostEqual(opt["quote"]["mid"], 5.10)
        self.assertEqual(opt["greeks"]["delta"], 0.5)
        self.assertEqual(opt["iv"], 0.15)

    @patch("packages.quantum.services.market_data_truth_layer.MarketDataTruthLayer.daily_bars")
    def test_iv_context(self, mock_daily_bars):
        layer = MarketDataTruthLayer(api_key="test")

        # Mock daily bars to return flat bars (low vol)
        mock_daily_bars.return_value = [
            {"close": 100 + (i % 2) * 0.1} for i in range(100) # minimal variance
        ]

        # This relies on calculate_iv_rank logic.
        # If variance is super low, rank might be low or calculation returns 0.

        ctx = layer.iv_context("AAPL")
        self.assertIn("iv_rank", ctx)
        self.assertIn("iv_regime", ctx)
        self.assertEqual(ctx["iv_rank_source"], "hv_proxy")

        # Should be suppressed due to low vol
        # (Though calculate_iv_rank implementation details matter)
        # If returns are constant-ish, vol is low.

    @patch("packages.quantum.services.market_data_truth_layer.MarketDataTruthLayer.daily_bars")
    def test_get_trend(self, mock_daily_bars):
        layer = MarketDataTruthLayer(api_key="test")

        # Mock uptrend
        mock_daily_bars.return_value = [
            {"close": 100 + i} for i in range(100)
        ]

        trend = layer.get_trend("AAPL")
        self.assertEqual(trend, "UP")

if __name__ == "__main__":
    unittest.main()
