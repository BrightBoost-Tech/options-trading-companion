import unittest
from datetime import datetime, timedelta
import sys
import os

# Ensure packages is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from packages.quantum.options_scanner import (
    _select_expiry_bucket,
    _filter_chain_by_expiry,
    _select_legs_from_chain
)

class TestSharedExpiryEnforced(unittest.TestCase):
    def test_select_expiry_bucket_counts(self):
        # Scenario: ExpA has 5 contracts, ExpB has 2. ExpA should be chosen.
        chain = [
            {"expiration": "2024-06-20", "id": 1},
            {"expiration": "2024-06-20", "id": 2},
            {"expiration": "2024-06-20", "id": 3},
            {"expiration": "2024-06-20", "id": 4},
            {"expiration": "2024-06-20", "id": 5},
            {"expiration": "2024-07-20", "id": 6},
            {"expiration": "2024-07-20", "id": 7},
        ]
        selected = _select_expiry_bucket(chain, target_dte=30)
        self.assertEqual(selected, "2024-06-20")

    def test_select_expiry_bucket_tie_break_dte(self):
        # Scenario: Equal counts. ExpA is closer to target DTE (35).
        today = datetime.now().date()
        exp_close = (today + timedelta(days=35)).strftime("%Y-%m-%d")
        exp_far = (today + timedelta(days=60)).strftime("%Y-%m-%d")

        chain = [
            {"expiration": exp_close, "id": 1},
            {"expiration": exp_far, "id": 2},
        ]
        # target_dte=35 matches exp_close exactly (diff 0) vs exp_far (diff 25)
        selected = _select_expiry_bucket(chain, target_dte=35)
        self.assertEqual(selected, exp_close)

    def test_filter_chain(self):
        chain = [
            {"expiration": "A", "id": 1},
            {"expiration": "B", "id": 2},
            {"expiration": "A", "id": 3},
        ]
        filtered = _filter_chain_by_expiry(chain, "A")
        self.assertEqual(len(filtered), 2)
        self.assertTrue(all(c["expiration"] == "A" for c in filtered))

    def test_integration_enforcement(self):
        """
        Simulate a vertical spread where:
        - Leg 1 (Buy Call): Best delta is in Exp A
        - Leg 2 (Sell Call): Best delta is in Exp B (if unrestricted)
        - But we force Exp A (if it has more contracts)
        """
        today = datetime.now().date()
        exp_A = (today + timedelta(days=30)).strftime("%Y-%m-%d") # Exp A
        exp_B = (today + timedelta(days=40)).strftime("%Y-%m-%d") # Exp B

        # Chain setup:
        # Exp A (3 items -> selected bucket due to count)
        #   - Call Delta 0.5 (Perfect for Leg 1)
        #   - Call Delta 0.1 (Bad for Leg 2, target is 0.3)
        # Exp B (2 items -> not selected)
        #   - Call Delta 0.9 (Bad for Leg 1)
        #   - Call Delta 0.3 (Perfect for Leg 2)

        chain = [
            # Exp A (3 items)
            {"expiration": exp_A, "type": "call", "delta": 0.50, "strike": 100, "price": 10, "ticker": "A1", "close": 10},
            {"expiration": exp_A, "type": "call", "delta": 0.10, "strike": 110, "price": 2, "ticker": "A2", "close": 2},
            {"expiration": exp_A, "type": "put",  "delta": -0.5, "strike": 100, "price": 10, "ticker": "A3", "close": 10},

            # Exp B (2 items)
            {"expiration": exp_B, "type": "call", "delta": 0.90, "strike": 90,  "price": 20, "ticker": "B1", "close": 20},
            {"expiration": exp_B, "type": "call", "delta": 0.30, "strike": 105, "price": 5, "ticker": "B2", "close": 5},
        ]

        # Strategy: Bull Call Spread
        suggestion_legs = [
            {"side": "buy", "type": "call", "delta_target": 0.50},
            {"side": "sell", "type": "call", "delta_target": 0.30},
        ]

        # 1. Select Bucket (Should pick A due to count 3 vs 2)
        selected_expiry = _select_expiry_bucket(chain, target_dte=35)
        self.assertEqual(selected_expiry, exp_A)

        # 2. Filter
        filtered_chain = _filter_chain_by_expiry(chain, selected_expiry)

        # 3. Select Legs (Constrained to A)
        legs, cost = _select_legs_from_chain(filtered_chain, suggestion_legs, current_price=100.0)

        # Verification
        self.assertEqual(len(legs), 2)
        self.assertEqual(legs[0]["expiry"], exp_A)
        self.assertEqual(legs[1]["expiry"], exp_A)
        self.assertEqual(legs[0]["symbol"], "A1") # Best delta for 0.5 is 0.5 (A1)
        self.assertEqual(legs[1]["symbol"], "A2") # Best delta for 0.3 in A is 0.1 (A2) -- diff 0.2.

        # Counter-factual: Ensure that without filtering, we would have picked mixed expiries
        legs_loose, _ = _select_legs_from_chain(chain, suggestion_legs, current_price=100.0)
        self.assertEqual(legs_loose[0]["symbol"], "A1") # 0.5 vs 0.5 (A1)
        self.assertEqual(legs_loose[1]["symbol"], "B2") # 0.3 vs 0.3 (B2)
        self.assertNotEqual(legs_loose[0]["expiry"], legs_loose[1]["expiry"])

if __name__ == '__main__':
    unittest.main()
