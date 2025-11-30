import unittest
from packages.quantum.analytics.surprise import compute_surprise

class TestSurpriseMetric(unittest.TestCase):

    def test_surprise_basic(self):
        # Case 1: Perfect prediction, no loss
        score = compute_surprise(sigma_pred=0.02, sigma_realized=0.02, pnl_realized=100.0)
        self.assertEqual(score, 0.0)

    def test_surprise_volatility_miss(self):
        # Case 2: Volatility miss, but profitable
        # |0.02 - 0.05| = 0.03
        # ReLU(-100) = 0
        # Score = 0.03
        score = compute_surprise(sigma_pred=0.02, sigma_realized=0.05, pnl_realized=100.0)
        self.assertAlmostEqual(score, 0.03)

    def test_surprise_loss(self):
        # Case 3: Perfect volatility, but loss
        # Vol diff = 0
        # ReLU(-(-50)) = 50
        # Score = 50
        score = compute_surprise(sigma_pred=0.02, sigma_realized=0.02, pnl_realized=-50.0)
        self.assertEqual(score, 50.0)

    def test_surprise_mixed(self):
        # Case 4: Vol miss and loss
        # Vol diff = |0.02 - 0.04| = 0.02
        # PnL = -10
        # ReLU(10) = 10
        # Score = 0.02 + 10 = 10.02
        score = compute_surprise(sigma_pred=0.02, sigma_realized=0.04, pnl_realized=-10.0)
        self.assertAlmostEqual(score, 10.02)

    def test_weights(self):
        # Case 5: Custom weights
        # Vol diff = 0.02, w1=10 -> 0.2
        # Loss = 10, w2=0.5 -> 5
        # Total = 5.2
        score = compute_surprise(sigma_pred=0.02, sigma_realized=0.04, pnl_realized=-10.0, w1=10.0, w2=0.5)
        self.assertAlmostEqual(score, 5.2)

if __name__ == '__main__':
    unittest.main()
