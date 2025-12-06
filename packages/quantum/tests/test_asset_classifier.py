import unittest
from packages.quantum.analytics.asset_classifier import AssetClassifier

class TestAssetClassifier(unittest.TestCase):

    def test_classify_plaid_security_equity(self):
        security = {"type": "equity", "ticker_symbol": "AAPL"}
        self.assertEqual(AssetClassifier.classify_plaid_security(security, {}), "EQUITY")

    def test_classify_plaid_security_etf(self):
        security = {"type": "etf", "ticker_symbol": "SPY"}
        self.assertEqual(AssetClassifier.classify_plaid_security(security, {}), "EQUITY")

    def test_classify_plaid_security_cash(self):
        security = {"type": "cash", "ticker_symbol": "CUR:USD"}
        self.assertEqual(AssetClassifier.classify_plaid_security(security, {}), "CASH")

    def test_classify_plaid_security_option_occ(self):
        security = {"type": "other", "ticker_symbol": "O:AMZN230616C00125000"}
        self.assertEqual(AssetClassifier.classify_plaid_security(security, {}), "OPTION")

    def test_classify_plaid_security_vtsi_fix(self):
        # VTSI scenario: type might be unknown or 'equity', but ticker is not OCC
        security = {"type": "unknown", "ticker_symbol": "VTSI"}
        self.assertEqual(AssetClassifier.classify_plaid_security(security, {}), "EQUITY")

    def test_is_occ_option_symbol(self):
        self.assertTrue(AssetClassifier.is_occ_option_symbol("O:AMZN230616C00125000"))
        self.assertTrue(AssetClassifier.is_occ_option_symbol("AMZN230616C00125000"))
        self.assertFalse(AssetClassifier.is_occ_option_symbol("VTSI"))
        self.assertFalse(AssetClassifier.is_occ_option_symbol("AAPL"))
        self.assertFalse(AssetClassifier.is_occ_option_symbol("CUR:USD"))

if __name__ == '__main__':
    unittest.main()
