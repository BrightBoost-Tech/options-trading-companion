import unittest
from packages.quantum.services.options_utils import compute_legs_fingerprint

class TestFingerprint(unittest.TestCase):
    def test_fingerprint_ignores_size_and_price(self):
        """
        Verify that structure-only fingerprinting ignores quantity and limit price.
        """
        # Case 1: Base trade
        trade_1 = {
            "legs": [
                {"symbol": "O:SPY231215C00450000", "side": "buy", "quantity": 1},
                {"symbol": "O:SPY231215C00455000", "side": "sell", "quantity": 1}
            ],
            "limit_price": 1.50
        }

        # Case 2: Same structure, different quantity
        trade_2 = {
            "legs": [
                {"symbol": "O:SPY231215C00450000", "side": "buy", "quantity": 10},
                {"symbol": "O:SPY231215C00455000", "side": "sell", "quantity": 10}
            ],
            "limit_price": 1.50
        }

        # Case 3: Same structure, different price
        trade_3 = {
            "legs": [
                {"symbol": "O:SPY231215C00450000", "side": "buy", "quantity": 1},
                {"symbol": "O:SPY231215C00455000", "side": "sell", "quantity": 1}
            ],
            "limit_price": 2.00
        }

        fp1 = compute_legs_fingerprint(trade_1)
        fp2 = compute_legs_fingerprint(trade_2)
        fp3 = compute_legs_fingerprint(trade_3)

        self.assertEqual(fp1, fp2, "Fingerprint should ignore quantity")
        self.assertEqual(fp1, fp3, "Fingerprint should ignore price")

    def test_fingerprint_order_independence(self):
        """
        Verify that leg order does not affect the fingerprint.
        """
        # Case 1: Leg A then Leg B
        trade_1 = {
            "legs": [
                {"symbol": "O:SPY231215C00450000", "side": "buy"},
                {"symbol": "O:SPY231215C00455000", "side": "sell"}
            ]
        }

        # Case 2: Leg B then Leg A
        trade_2 = {
            "legs": [
                {"symbol": "O:SPY231215C00455000", "side": "sell"},
                {"symbol": "O:SPY231215C00450000", "side": "buy"}
            ]
        }

        fp1 = compute_legs_fingerprint(trade_1)
        fp2 = compute_legs_fingerprint(trade_2)

        self.assertEqual(fp1, fp2, "Fingerprint should be order independent")

    def test_different_structure(self):
        """
        Verify that different structures (different strike, type, side, or expiry)
        produce DIFFERENT fingerprints.
        """
        # Base
        trade_base = {
            "legs": [{"symbol": "O:SPY231215C00450000", "side": "buy"}]
        }

        # Different Type
        trade_diff_type = {
            "legs": [{"symbol": "O:SPY231215P00450000", "side": "buy"}]
        }

        # Different Strike
        trade_diff_strike = {
            "legs": [{"symbol": "O:SPY231215C00460000", "side": "buy"}]
        }

        # Different Side
        trade_diff_side = {
            "legs": [{"symbol": "O:SPY231215C00450000", "side": "sell"}]
        }

        fp_base = compute_legs_fingerprint(trade_base)

        self.assertNotEqual(fp_base, compute_legs_fingerprint(trade_diff_type), "Different type should differ")
        self.assertNotEqual(fp_base, compute_legs_fingerprint(trade_diff_strike), "Different strike should differ")
        self.assertNotEqual(fp_base, compute_legs_fingerprint(trade_diff_side), "Different side should differ")

    def test_missing_legs(self):
        """
        Verify safe fallback for empty or missing legs.
        """
        # Empty legs
        trade_empty = {"legs": []}
        fp_empty = compute_legs_fingerprint(trade_empty)
        self.assertIsNotNone(fp_empty)

        # Stock fallback
        trade_stock = {
            "legs": [],
            "underlying": "AAPL"
        }
        fp_stock = compute_legs_fingerprint(trade_stock)
        self.assertIsNotNone(fp_stock)
        self.assertNotEqual(fp_empty, fp_stock)

    def test_symbol_normalization(self):
        """
        Verify that symbols are parsed and normalized (e.g. O: prefix handled).
        """
        trade_1 = {
            "legs": [{"symbol": "O:SPY231215C00450000", "side": "buy"}]
        }
        trade_2 = {
            "legs": [{"symbol": "SPY231215C00450000", "side": "buy"}] # Missing O:
        }

        fp1 = compute_legs_fingerprint(trade_1)
        fp2 = compute_legs_fingerprint(trade_2)

        self.assertEqual(fp1, fp2, "Should handle symbols with/without 'O:' prefix identically")

if __name__ == "__main__":
    unittest.main()
