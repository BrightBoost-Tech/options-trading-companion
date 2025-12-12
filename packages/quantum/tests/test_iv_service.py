import unittest
from datetime import datetime, date, timedelta
from packages.quantum.services.iv_point_service import IVPointService

class TestIVPointService(unittest.TestCase):

    def test_compute_atm_iv_for_expiry(self):
        # Setup: 3 strikes around spot 100
        # 95: Call IV 0.25, Put IV 0.26
        # 100: Call IV 0.20, Put IV 0.21
        # 105: Call IV 0.18, Put IV 0.19

        spot = 100.0

        contracts = [
            {'details': {'strike_price': 95.0, 'contract_type': 'call'}, 'implied_volatility': 0.25},
            {'details': {'strike_price': 95.0, 'contract_type': 'put'}, 'implied_volatility': 0.26},
            {'details': {'strike_price': 100.0, 'contract_type': 'call'}, 'implied_volatility': 0.20},
            {'details': {'strike_price': 100.0, 'contract_type': 'put'}, 'implied_volatility': 0.21},
            {'details': {'strike_price': 105.0, 'contract_type': 'call'}, 'implied_volatility': 0.18},
            {'details': {'strike_price': 105.0, 'contract_type': 'put'}, 'implied_volatility': 0.19},
        ]

        iv, strike, penalty = IVPointService._compute_atm_iv_for_expiry(contracts, spot)

        self.assertEqual(strike, 100.0)
        self.assertAlmostEqual(iv, 0.205) # Average of 0.20 and 0.21
        self.assertEqual(penalty, 0)

    def test_compute_atm_iv_30d_interpolation(self):
        # Setup: 2 expiries, 25 DTE and 35 DTE
        # Spot 100
        as_of = datetime(2023, 1, 1, 12, 0, 0)
        t1_date = (as_of + timedelta(days=25)).date() # 2023-01-26
        t2_date = (as_of + timedelta(days=35)).date() # 2023-02-05

        # Format dates as string for parser
        d1 = t1_date.strftime('%Y-%m-%d')
        d2 = t2_date.strftime('%Y-%m-%d')

        contracts = [
            # Expiry 1 (25 days) - ATM IV 0.20
            {'details': {'strike_price': 100.0, 'contract_type': 'call', 'expiration_date': d1}, 'implied_volatility': 0.20},
            {'details': {'strike_price': 100.0, 'contract_type': 'put', 'expiration_date': d1}, 'implied_volatility': 0.20},

            # Expiry 2 (35 days) - ATM IV 0.30
            {'details': {'strike_price': 100.0, 'contract_type': 'call', 'expiration_date': d2}, 'implied_volatility': 0.30},
            {'details': {'strike_price': 100.0, 'contract_type': 'put', 'expiration_date': d2}, 'implied_volatility': 0.30},
        ]

        res = IVPointService.compute_atm_iv_30d_from_chain(contracts, 100.0, as_of)

        # Logic check:
        # T1 = 25/365, T2 = 35/365, T_target = 30/365
        # V1 = 0.20^2 * T1 = 0.04 * 25/365 = 1/365
        # V2 = 0.30^2 * T2 = 0.09 * 35/365 = 3.15/365
        # Slope = (2.15/365) / (10/365) = 0.215
        # V_30 = V1 + Slope * (5/365) = 1/365 + 0.215 * 5/365 = (1 + 1.075)/365 = 2.075/365
        # IV_30 = sqrt(V_30 / (30/365)) = sqrt(2.075/30) = sqrt(0.069166) = 0.263

        iv_30d = res['iv_30d']
        self.assertIsNotNone(iv_30d)

        # Approximate check
        self.assertTrue(0.20 < iv_30d < 0.30)
        self.assertAlmostEqual(iv_30d, 0.26299, places=3)
        self.assertEqual(res['iv_30d_method'], 'var_interp_spot_atm')

    def test_compute_iv_fallback_single_expiry(self):
        # Only 25 days available
        as_of = datetime(2023, 1, 1, 12, 0, 0)
        t1_date = (as_of + timedelta(days=25)).date()
        d1 = t1_date.strftime('%Y-%m-%d')

        contracts = [
            {'details': {'strike_price': 100.0, 'contract_type': 'call', 'expiration_date': d1}, 'implied_volatility': 0.20},
            {'details': {'strike_price': 100.0, 'contract_type': 'put', 'expiration_date': d1}, 'implied_volatility': 0.20},
        ]

        res = IVPointService.compute_atm_iv_30d_from_chain(contracts, 100.0, as_of)

        self.assertEqual(res['iv_30d'], 0.20)
        self.assertEqual(res['iv_30d_method'], 'nearest_expiry')
        self.assertTrue(res['quality_score'] < 100)

    def test_percentile_iv_rank(self):
        # Logic is in IVRepository, but we can verify the math here.
        # IV Rank = (current - min) / (max - min) * 100

        history = [0.10, 0.20, 0.30, 0.40, 0.50]
        current = 0.30

        min_iv = min(history)
        max_iv = max(history)

        iv_rank = (current - min_iv) / (max_iv - min_iv) * 100.0
        self.assertAlmostEqual(iv_rank, 50.0)

        # Test 100%
        current = 0.50
        iv_rank = (current - min_iv) / (max_iv - min_iv) * 100.0
        self.assertAlmostEqual(iv_rank, 100.0)

        # Test 0%
        current = 0.10
        iv_rank = (current - min_iv) / (max_iv - min_iv) * 100.0
        self.assertEqual(iv_rank, 0.0)

if __name__ == '__main__':
    unittest.main()
