import unittest
from packages.quantum.services.risk_engine import RiskEngine
from packages.quantum.models import UnifiedPosition

class TestRiskEngine(unittest.TestCase):

    def test_build_unified_positions(self):
        holdings = [
            {"asset_type": "EQUITY", "symbol": "AAPL", "quantity": 10, "current_price": 150.0},
            {"asset_type": "OPTION", "symbol": "O:AMZN...", "quantity": 1, "current_price": 5.0, "delta": 0.5},
            {"asset_type": "CASH", "symbol": "CUR:USD", "quantity": 1000, "current_price": 1.0}
        ]

        unified = RiskEngine.build_unified_positions(holdings)
        self.assertEqual(len(unified), 3)

        # Check Equity
        equity = next(p for p in unified if p.asset_type == "EQUITY")
        self.assertEqual(equity.delta, 10.0) # 1 * 10

        # Check Option
        option = next(p for p in unified if p.asset_type == "OPTION")
        self.assertEqual(option.delta, 50.0) # 0.5 * 100 * 1

        # Check Cash
        cash = next(p for p in unified if p.asset_type == "CASH")
        self.assertEqual(cash.delta, 0.0)

    def test_compute_risk_summary(self):
        unified = [
            UnifiedPosition(
                symbol="AAPL", asset_type="EQUITY", quantity=10,
                cost_basis=100, current_price=150, delta=10.0,
                sector="Technology"
            ),
            UnifiedPosition(
                symbol="OPT", asset_type="OPTION", quantity=1,
                cost_basis=400, current_price=5.0, delta=50.0, # Value = 5.0*100 = 500
                sector="Consumer"
            )
        ]

        summary = RiskEngine.compute_risk_summary(unified)

        # Net Liq: 10*150 + 1*5.0*100 = 1500 + 500 = 2000
        self.assertEqual(summary["summary"]["netLiquidation"], 2000.0)

        # Portfolio Delta: 10 + 50 = 60
        self.assertEqual(summary["greeks"]["portfolioDelta"], 60.0)

        # Sector Exposure
        # Technology: 1500 / 2000 = 75%
        # Consumer: 500 / 2000 = 25%
        self.assertEqual(summary["exposure"]["bySector"]["Technology"], 75.0)
        self.assertEqual(summary["exposure"]["bySector"]["Consumer"], 25.0)

if __name__ == '__main__':
    unittest.main()
