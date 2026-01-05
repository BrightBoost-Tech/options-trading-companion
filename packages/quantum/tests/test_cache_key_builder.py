import unittest
from datetime import datetime, date
from packages.quantum.services.cache_key_builder import make_cache_key_parts, normalize_symbol, normalize_date

class TestCacheKeyBuilder(unittest.TestCase):

    def test_normalize_symbol(self):
        self.assertEqual(normalize_symbol("AAPL"), "AAPL")
        self.assertEqual(normalize_symbol("aapl "), "AAPL")
        # Option symbol normalization
        self.assertEqual(normalize_symbol("AMZN230616C00125000"), "O:AMZN230616C00125000")
        self.assertEqual(normalize_symbol("O:AMZN230616C00125000"), "O:AMZN230616C00125000")

    def test_normalize_date(self):
        self.assertEqual(normalize_date(date(2023, 1, 1)), "2023-01-01")
        self.assertEqual(normalize_date(datetime(2023, 1, 1, 12, 0, 0)), "2023-01-01")
        self.assertEqual(normalize_date("2023-01-01T10:00:00"), "2023-01-01")
        self.assertEqual(normalize_date("2023-01-01T10:00:00Z"), "2023-01-01")
        self.assertEqual(normalize_date("2023-01-01"), "2023-01-01")

    def test_ohlc_key(self):
        # Different input formats should yield same key
        k1 = make_cache_key_parts("OHLC", symbol="AAPL", days=100, to_date=date(2023, 1, 1))
        k2 = make_cache_key_parts("OHLC", symbol="aapl ", days="100", to_date_str="2023-01-01")

        self.assertEqual(k1, ["AAPL", "100", "2023-01-01"])
        self.assertEqual(k1, k2)

    def test_quote_key(self):
        k1 = make_cache_key_parts("QUOTE", symbol="tsla")
        self.assertEqual(k1, ["TSLA"])

    def test_chain_key(self):
        # Chain key has implicit hour if not provided, so provide one for stability check
        d_str = "2023-01-01-10"
        k1 = make_cache_key_parts("CHAIN", underlying="spy", strike_range=0.1, limit=100, date_str=d_str)
        k2 = make_cache_key_parts("CHAIN", underlying="SPY", strike_range="0.1", limit="100", date_str=d_str)

        self.assertEqual(k1, ["SPY", "0.1", "100", d_str])
        self.assertEqual(k1, k2)

    def test_earnings_key(self):
        k1 = make_cache_key_parts("EARNINGS", symbol="nvda", today_str="2023-10-10")
        self.assertEqual(k1, ["NVDA", "2023-10-10"])

if __name__ == '__main__':
    unittest.main()
