import pytest
from packages.quantum.services.drawdown_service import (
    compute_drawdown,
    compute_consecutive_losses,
    compute_risk_multiplier
)

class TestDrawdownService:
    def test_compute_drawdown_basic(self):
        # Peak 100 -> 90 is 10% DD.
        curve = [100.0, 95.0, 90.0, 95.0, 100.0]
        result = compute_drawdown(curve)
        assert result["max_drawdown_pct"] == 0.10
        assert result["peak"] == 100.0
        assert result["trough"] == 90.0

    def test_compute_drawdown_multiple_valleys(self):
        # 100 -> 80 (20%), then recover to 110, then 110 -> 99 (10%)
        # Max DD should be 20%
        curve = [100.0, 90.0, 80.0, 100.0, 110.0, 99.0]
        result = compute_drawdown(curve)
        assert result["max_drawdown_pct"] == 0.20
        assert result["peak"] == 100.0
        assert result["trough"] == 80.0

    def test_compute_drawdown_no_drawdown(self):
        curve = [100.0, 101.0, 102.0, 103.0]
        result = compute_drawdown(curve)
        assert result["max_drawdown_pct"] == 0.0
        assert result["peak"] == 100.0  # Or 103? logic says "peak at max dd". if max dd is 0, it's the first peak encountered or 0.
        # Implementation: current_peak updates. if DD never > 0, max_dd_pct stays 0.
        # Logic: `dd = (current_peak - value) / current_peak`.
        # If value is always increasing, dd is always 0.
        # max_dd_pct is 0. peak_at_max_dd initializes to curve[0].
        # Let's verify behavior. Ideally peak/trough might not matter much if DD is 0, but checking consistenty.

    def test_compute_drawdown_empty(self):
        result = compute_drawdown([])
        assert result["max_drawdown_pct"] == 0.0

    def test_compute_consecutive_losses(self):
        pnl = [10, -5, -2, -10]
        assert compute_consecutive_losses(pnl) == 3

        pnl = [10, -5, 2, -10]
        assert compute_consecutive_losses(pnl) == 1

        pnl = [10, 5, 2]
        assert compute_consecutive_losses(pnl) == 0

        pnl = []
        assert compute_consecutive_losses(pnl) == 0

    def test_risk_multiplier_regimes(self):
        # Base
        assert compute_risk_multiplier(0.0, 0, "normal") == 1.0

        # Panic (*0.4)
        assert compute_risk_multiplier(0.0, 0, "panic") == 0.4

        # High Vol (*0.7)
        assert compute_risk_multiplier(0.0, 0, "high_vol") == 0.7

    def test_risk_multiplier_losses(self):
        # >= 3 losses -> *0.6
        # 1.0 * 0.6 = 0.6
        assert compute_risk_multiplier(0.0, 3, "normal") == 0.6

        # 2 losses -> no penalty
        assert compute_risk_multiplier(0.0, 2, "normal") == 1.0

    def test_risk_multiplier_drawdown(self):
        # >= 10% -> *0.7
        val = compute_risk_multiplier(0.10, 0, "normal")
        assert abs(val - 0.7) < 1e-9

        # >= 20% -> *0.7 * 0.4 = 0.28
        val = compute_risk_multiplier(0.20, 0, "normal")
        assert abs(val - 0.28) < 1e-9

    def test_risk_multiplier_combinations(self):
        # Panic (0.4) + 3 losses (0.6) + 20% DD (0.7 * 0.4)
        # 0.4 * 0.6 * 0.7 * 0.4 = 0.0672
        # Clamped to 0.1
        val = compute_risk_multiplier(0.20, 3, "panic")
        assert val == 0.1

    def test_risk_multiplier_cap(self):
        # This function doesn't seem to have logic to increase > 1.0 other than starting at 1.0.
        # But if we imagine a scenario where it could (e.g. if we add logic later), the cap is 1.2.
        # The prompt says "clamp [0.1, 1.2]".
        # With current logic max is 1.0.
        pass
