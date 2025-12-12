import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta
import numpy as np

from packages.quantum.analytics.regime_engine_v3 import RegimeEngineV3, RegimeState, GlobalRegimeSnapshot, SymbolRegimeSnapshot

class TestRegimeEngineV3(unittest.TestCase):

    def setUp(self):
        self.mock_supabase = MagicMock()
        self.mock_market = MagicMock()
        self.engine = RegimeEngineV3(self.mock_supabase, self.mock_market)
        # Mock internal repo to avoid real calls or unmockable methods
        self.engine.iv_repo = MagicMock()
        self.ts = datetime(2025, 1, 1, 10, 0, 0)

    def test_map_to_scoring_regime(self):
        self.assertEqual(self.engine.map_to_scoring_regime(RegimeState.SHOCK), "panic")
        self.assertEqual(self.engine.map_to_scoring_regime(RegimeState.ELEVATED), "high_vol")
        self.assertEqual(self.engine.map_to_scoring_regime(RegimeState.REBOUND), "high_vol")
        self.assertEqual(self.engine.map_to_scoring_regime(RegimeState.NORMAL), "normal")
        self.assertEqual(self.engine.map_to_scoring_regime(RegimeState.SUPPRESSED), "normal")
        self.assertEqual(self.engine.map_to_scoring_regime(RegimeState.CHOP), "normal")

    def test_effective_regime_logic(self):
        # 1. Global Shock overrides everything
        g_snap = GlobalRegimeSnapshot("ts", RegimeState.SHOCK, 100, 0.5, 0, 0, 0, 0, 0)
        s_snap = SymbolRegimeSnapshot("sym", "ts", RegimeState.NORMAL, 50, None, None, None, None, None, None)

        eff = self.engine.get_effective_regime(s_snap, g_snap)
        self.assertEqual(eff, RegimeState.SHOCK)

        # 2. Rebound Logic
        g_snap.state = RegimeState.REBOUND
        s_snap.state = RegimeState.ELEVATED # Global Rebound, Symbol Elevated -> Rebound
        eff = self.engine.get_effective_regime(s_snap, g_snap)
        self.assertEqual(eff, RegimeState.REBOUND)

        s_snap.state = RegimeState.SHOCK # Symbol Shock -> Shock
        eff = self.engine.get_effective_regime(s_snap, g_snap)
        self.assertEqual(eff, RegimeState.SHOCK)

        # 3. Standard Max Risk
        g_snap.state = RegimeState.NORMAL
        s_snap.state = RegimeState.ELEVATED
        eff = self.engine.get_effective_regime(s_snap, g_snap)
        self.assertEqual(eff, RegimeState.ELEVATED)

        s_snap.state = RegimeState.SUPPRESSED
        eff = self.engine.get_effective_regime(s_snap, g_snap)
        self.assertEqual(eff, RegimeState.NORMAL)

    def test_compute_global_snapshot_normal(self):
        # Mock SPY bars: Strong Uptrend, Low Vol
        bars = []
        for i in range(100):
            # Increase slope to ensure trend_z > 0.5 to avoid CHOP
            bars.append({"close": 100 + i*0.5, "date": f"2024-01-{i%30+1}"})

        self.mock_market.daily_bars.return_value = bars

        snap = self.engine.compute_global_snapshot(self.ts)

        # Trend should be positive
        # Vol should be low
        self.assertTrue(snap.trend_score > 0)
        # print(f"Trend: {snap.trend_score}, Vol: {snap.vol_score}, Risk: {snap.risk_score}")
        self.assertTrue(snap.risk_score < 40)
        self.assertIn(snap.state, [RegimeState.NORMAL, RegimeState.SUPPRESSED])

    def test_compute_global_snapshot_shock(self):
        # Mock SPY bars: Crash
        bars = [{"close": 100} for _ in range(50)]
        # Add crash
        for i in range(10):
            bars.append({"close": 100 - i*2}) # Drop to 80

        self.mock_market.daily_bars.return_value = bars

        snap = self.engine.compute_global_snapshot(self.ts)

        # Trend negative
        # Vol high
        self.assertTrue(snap.trend_score < 0)
        self.assertTrue(snap.vol_score > 0)
        self.assertTrue(snap.risk_score > 60)
        self.assertIn(snap.state, [RegimeState.ELEVATED, RegimeState.SHOCK])

    @patch("packages.quantum.analytics.regime_engine_v3.IVPointService")
    def test_compute_symbol_snapshot(self, mock_iv_service):
        # Mock IV Context on the engine's repo (already mocked in setUp)
        self.engine.iv_repo.get_iv_context.return_value = {
            "iv_rank": 90.0,
            "iv_30d": 0.50
        }

        # Mock Bars (Realized Vol)
        bars = [{"close": 100 * (1 + ((-1)**i)*0.01)} for i in range(30)] # 1% oscillation -> ~16% vol
        self.mock_market.daily_bars.return_value = bars

        # Mock Option Chain
        self.mock_market.option_chain.return_value = [{"some": "contract"}]
        mock_iv_service.compute_skew_25d_from_chain.return_value = 0.15 # High skew
        mock_iv_service.compute_term_slope.return_value = -0.05 # Inverted term structure (Fear)

        g_snap = GlobalRegimeSnapshot(self.ts.isoformat(), RegimeState.NORMAL, 50, 1.0, 0,0,0,0,0)

        s_snap = self.engine.compute_symbol_snapshot("TSLA", g_snap)

        # Should detect high risk
        self.assertEqual(s_snap.iv_rank, 90.0)
        self.assertTrue(s_snap.score > 60) # High Rank + Skew + Inversion
        self.assertIn(s_snap.state, [RegimeState.ELEVATED, RegimeState.SHOCK])

if __name__ == '__main__':
    unittest.main()
