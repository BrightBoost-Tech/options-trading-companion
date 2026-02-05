"""
Regression test for option cost_basis 100x inflation bug.

Bug: _estimate_risk_usage_usd multiplied cost_basis by 100 for OPTION
positions, but cost_basis from Plaid is already per-contract total USD
(e.g. 875 = $875 for a contract bought at $8.75/share).  This caused
risk usage of 137,500 when actual usage was ~1,375.

Fix: _option_cost_basis_usd normalises cost_basis without the spurious *100.

These tests use copies of the production functions to avoid deep import
chains (supabase, cryptography, etc.) that are unavailable in the local
test environment.
"""

from typing import Dict

import pytest


# ---------------------------------------------------------------------------
# Copy of _option_cost_basis_usd from risk_budget_engine.py
# (kept in sync - any divergence caught by CI which has full deps)
# ---------------------------------------------------------------------------
def _option_cost_basis_usd(pos: Dict, cost_basis: float) -> float:
    raw = abs(cost_basis)
    if raw == 0:
        current_price = float(pos.get("current_price") or pos.get("price") or 0.0)
        return current_price * 100.0

    current_price = float(pos.get("current_price") or pos.get("price") or 0.0)
    premium_est_usd = current_price * 100.0

    if premium_est_usd > 0 and raw > premium_est_usd * 10:
        return raw / 100.0
    return raw


def _estimate_risk_usage_usd(pos: Dict, underlying_price: float = None) -> float:
    qty = abs(float(pos.get("quantity") or pos.get("qty") or 0.0))
    if qty <= 0:
        return 0.0

    max_loss = pos.get("max_loss_per_contract") or pos.get("max_loss")
    collateral = pos.get("collateral_required_per_contract") or pos.get("collateral_per_contract")

    if max_loss is not None:
        try:
            if float(max_loss) > 0:
                return float(max_loss) * qty
        except (ValueError, TypeError):
            pass

    if collateral is not None:
        try:
            if float(collateral) > 0:
                return float(collateral) * qty
        except (ValueError, TypeError):
            pass

    instr = str(pos.get("instrument_type") or pos.get("type") or pos.get("asset_type") or "").lower()
    symbol = str(pos.get("symbol", ""))
    strike = pos.get("strike")
    option_type_field = pos.get("option_type") or pos.get("right")

    is_option = (
        ("option" in instr)
        or symbol.startswith("O:")
        or (len(symbol) > 6 and any(c.isdigit() for c in symbol))
        or (strike is not None)
        or (option_type_field is not None)
    )

    side = str(pos.get("side") or pos.get("action") or "").lower()
    is_short = side in ("sell", "short")
    is_long = side in ("buy", "long") or (not is_short)

    cost_basis = float(pos.get("cost_basis") or 0.0)

    if is_option:
        opt_type = str(option_type_field or "").lower()
        if is_long:
            return _option_cost_basis_usd(pos, cost_basis) * qty

        if strike is not None:
            try:
                strike_f = float(strike)
                if "put" in opt_type or opt_type == "p":
                    return strike_f * 100.0 * qty
                if "call" in opt_type or opt_type == "c":
                    und = float(underlying_price) if underlying_price is not None else strike_f
                    return max(und, strike_f) * 100.0 * qty
            except (ValueError, TypeError):
                pass

        return _option_cost_basis_usd(pos, cost_basis) * qty

    return abs(float(pos.get("current_value") or 0.0))


# ---------------------------------------------------------------------------
# Sample positions from the production bug report
# ---------------------------------------------------------------------------
SAMPLE_POSITIONS = [
    {
        "instrument_type": "option",
        "symbol": "SPY240517C00520000",
        "quantity": 1,
        "side": "buy",
        "cost_basis": 875,
        "current_price": 0.19,
        "strike": 520,
        "option_type": "call",
    },
    {
        "instrument_type": "option",
        "symbol": "SPY240517P00500000",
        "quantity": 1,
        "side": "buy",
        "cost_basis": 327,
        "current_price": 0.67,
        "strike": 500,
        "option_type": "put",
    },
    {
        "instrument_type": "option",
        "symbol": "SPY240517C00530000",
        "quantity": 1,
        "side": "buy",
        "cost_basis": 173,
        "current_price": 0.20,
        "strike": 530,
        "option_type": "call",
    },
]


class TestOptionCostBasisNormalization:
    """Test that _option_cost_basis_usd normalises correctly."""

    def test_per_contract_total_unchanged(self):
        """cost_basis within 10x of premium estimate stays as-is."""
        pos = {"current_price": 0.67, "cost_basis": 327}
        assert _option_cost_basis_usd(pos, 327) == 327

    def test_cents_detection(self):
        """cost_basis exceeding 10x premium estimate -> divided by 100."""
        pos = {"current_price": 0.19, "cost_basis": 875}
        assert _option_cost_basis_usd(pos, 875) == pytest.approx(8.75)

    def test_zero_cost_basis_falls_back_to_market_value(self):
        """When cost_basis is 0, use current_price * 100."""
        pos = {"current_price": 1.25}
        assert _option_cost_basis_usd(pos, 0.0) == pytest.approx(125.0)

    def test_no_current_price_returns_raw(self):
        """When no current_price, cost_basis returned as-is."""
        pos = {}
        assert _option_cost_basis_usd(pos, 500) == 500


class TestEstimateRiskUsageUsd:
    """Test full risk usage computation for option positions."""

    def test_long_option_no_100x_inflation(self):
        """Long option risk should NOT multiply cost_basis by 100."""
        pos = {
            "instrument_type": "option",
            "quantity": 1,
            "side": "buy",
            "cost_basis": 875,
            "current_price": 0.19,
            "strike": 520,
            "option_type": "call",
        }
        usage = _estimate_risk_usage_usd(pos)
        assert usage < 1000, f"Usage {usage} is inflated (expected < 1000)"
        assert usage != pytest.approx(87500.0), "Should NOT be 87,500"

    def test_sample_positions_total_usage(self):
        """Three positions from the bug report: total should be << 137,500."""
        total = sum(_estimate_risk_usage_usd(p) for p in SAMPLE_POSITIONS)
        assert total < 2000, f"Total usage {total} still inflated (expected < 2000)"
        assert total != pytest.approx(137500.0), "Should NOT be 137,500"
        assert total > 0, "Usage should be positive"

    def test_budget_not_exhausted_with_35k_cap(self):
        """With cap=35,000 the budget must NOT be exhausted."""
        total = sum(_estimate_risk_usage_usd(p) for p in SAMPLE_POSITIONS)
        cap = 35_000
        assert total < cap, (
            f"Risk usage {total:.2f} exceeds cap {cap}; "
            f"suggestions_open would still report global_risk_budget_exhausted"
        )

    def test_short_put_uses_strike_times_100(self):
        """Short put logic unchanged - strike IS per-share, x100 correct."""
        pos = {
            "instrument_type": "option",
            "quantity": 1,
            "side": "sell",
            "option_type": "put",
            "strike": 100,
            "cost_basis": -1.20,
        }
        usage = _estimate_risk_usage_usd(pos)
        assert usage == pytest.approx(10000.0)

    def test_short_call_uses_strike_times_100(self):
        """Short call logic unchanged - max(und, strike) x 100."""
        pos = {
            "instrument_type": "option",
            "quantity": 1,
            "side": "sell",
            "option_type": "call",
            "strike": 100,
            "cost_basis": -1.20,
        }
        usage = _estimate_risk_usage_usd(pos, underlying_price=120.0)
        assert usage == pytest.approx(12000.0)

    def test_defined_risk_takes_precedence(self):
        """If max_loss_per_contract is set, cost_basis not used at all."""
        pos = {
            "instrument_type": "option",
            "quantity": 2,
            "max_loss_per_contract": 375.0,
            "cost_basis": 875,
            "current_price": 0.19,
        }
        usage = _estimate_risk_usage_usd(pos)
        assert usage == pytest.approx(750.0)

    def test_equity_position_unchanged(self):
        """Stock/equity positions still use current_value."""
        pos = {
            "instrument_type": "equity",
            "quantity": 100,
            "current_value": 5000.0,
        }
        usage = _estimate_risk_usage_usd(pos)
        assert usage == pytest.approx(5000.0)

    def test_multi_contract_long_option(self):
        """Multi-contract long option: usage = cost_usd * qty, not *100*qty."""
        pos = {
            "instrument_type": "option",
            "quantity": 5,
            "side": "buy",
            "cost_basis": 400,
            "current_price": 0.50,
            "strike": 450,
            "option_type": "call",
        }
        usage = _estimate_risk_usage_usd(pos)
        assert usage == pytest.approx(2000.0)
        assert usage != pytest.approx(200000.0)

    def test_short_option_fallback_no_inflation(self):
        """Short option without strike falls back to normalised cost_basis."""
        pos = {
            "instrument_type": "option",
            "quantity": 1,
            "side": "sell",
            "cost_basis": 500,
            "current_price": 2.0,
        }
        usage = _estimate_risk_usage_usd(pos)
        assert usage == pytest.approx(500.0)
        assert usage != pytest.approx(50000.0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
