import unittest
from datetime import datetime, timedelta
import sys
import os

# Ensure packages is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from packages.quantum.options_scanner import (
    _select_best_expiry_chain,
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
        # _select_best_expiry_chain returns (best_expiry, bucket_list)
        selected_expiry, bucket = _select_best_expiry_chain(chain, target_dte=30)
        self.assertEqual(selected_expiry, "2024-06-20")
        self.assertEqual(len(bucket), 5)

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
        selected_expiry, bucket = _select_best_expiry_chain(chain, target_dte=35)
        self.assertEqual(selected_expiry, exp_close)
        self.assertEqual(len(bucket), 1)

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
        # _select_best_expiry_chain returns (best_expiry, bucket_list)
        selected_expiry, filtered_chain = _select_best_expiry_chain(chain, target_dte=35)
        self.assertEqual(selected_expiry, exp_A)
        self.assertEqual(len(filtered_chain), 3)

        # 3. Select Legs (Constrained to A)
        # We assume calls/puts are sorted by strike. In this mock, we sort them manually or rely on function robustness
        # The function expects 'calls' and 'puts' lists, not raw chain.
        # We need to split them as the scanner does.
        calls = sorted([c for c in filtered_chain if c['type'] == 'call'], key=lambda x: x['strike'])
        puts = sorted([c for c in filtered_chain if c['type'] == 'put'], key=lambda x: x['strike'])

        legs, cost = _select_legs_from_chain(calls, puts, suggestion_legs, current_price=100.0)

        # Verification
        self.assertEqual(len(legs), 2)
        self.assertEqual(legs[0]["expiry"], exp_A)
        self.assertEqual(legs[1]["expiry"], exp_A)
        self.assertEqual(legs[0]["symbol"], "A1") # Best delta for 0.5 is 0.5 (A1)
        self.assertEqual(legs[1]["symbol"], "A2") # Best delta for 0.3 in A is 0.1 (A2) -- diff 0.2.

        # Counter-factual: Ensure that without filtering, we would have picked mixed expiries if passed all.
        # But _select_legs_from_chain takes sorted calls/puts. If we pass mixed calls/puts, it might mix them.
        calls_loose = sorted([c for c in chain if c['type'] == 'call'], key=lambda x: x['strike'])
        puts_loose = sorted([c for c in chain if c['type'] == 'put'], key=lambda x: x['strike'])

        legs_loose, _ = _select_legs_from_chain(calls_loose, puts_loose, suggestion_legs, current_price=100.0)

        # NOTE: _select_legs_from_chain just picks best delta. It doesn't enforce expiry if mixed list is passed.
        # So it should pick B2 (delta 0.3) for the sell leg.
        self.assertEqual(legs_loose[0]["symbol"], "A1") # 0.5 vs 0.5 (A1)
        self.assertEqual(legs_loose[1]["symbol"], "B2") # 0.3 vs 0.3 (B2)
        self.assertNotEqual(legs_loose[0]["expiry"], legs_loose[1]["expiry"])

if __name__ == '__main__':
    unittest.main()
