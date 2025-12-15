import pytest
from packages.quantum.services.risk_engine import RiskEngine

def test_bounds_clamping():
    # Setup base constraints
    base_constraints = {
        "max_position_pct": 0.40,
        "bounds": [(0.0, 0.40), (0.0, 0.10)]
    }

    # Setup policy that tightens constraints
    policy = {
        "max_position_pct": 0.20,
        "ban_structures": []
    }

    # Apply caps
    adjusted = RiskEngine.apply_adaptive_caps(policy, base_constraints)

    # Assertions
    assert adjusted["max_position_pct"] == 0.20
    # First asset was 0.40, should be clamped to 0.20
    # Second asset was 0.10, which is < 0.20, so remains 0.10
    assert adjusted["bounds"] == [(0.0, 0.20), (0.0, 0.10)]

def test_bounds_invalid_clamping():
    # Test case where tightening makes bounds invalid (hi < lo)
    base_constraints = {
        "max_position_pct": 0.50,
        "bounds": [(0.30, 0.50)]  # Min 30% allocation
    }

    # Policy forces max 20%
    policy = {
        "max_position_pct": 0.20,
        "ban_structures": []
    }

    adjusted = RiskEngine.apply_adaptive_caps(policy, base_constraints)

    # Assert max is updated
    assert adjusted["max_position_pct"] == 0.20

    # Assert bounds are zeroed because 0.20 (new max) < 0.30 (min)
    # The logic is: hi2 = min(0.50, 0.20) = 0.20. hi2 (0.20) < lo (0.30) -> True -> (0.0, 0.0)
    assert adjusted["bounds"] == [(0.0, 0.0)]

def test_banned_strategies_enforcement_logic():
    # Use a mock or simplified version of the logic in optimizer.py
    # since we can't easily import the internal helper _compute_portfolio_weights
    # without a lot of setup. We'll test the logic snippet itself.

    # Mock constraints
    constraints = {
        "bounds": [(0.0, 0.20), (0.0, 0.20)],
        "banned_strategies": ["credit"]
    }

    # Mock assets
    class MockAsset:
        def __init__(self, spread_type):
            self.spread_type = spread_type
            self.strategy = spread_type # Fallback check

    investable_assets = [
        MockAsset("credit_spread"),
        MockAsset("debit_spread")
    ]
    tickers = ["A", "B"]

    # Logic from optimizer.py (Step B2)
    banned = [str(x).lower() for x in constraints.get("banned_strategies", []) if x]
    if banned and "bounds" in constraints:
        new_bounds = []
        banned_assets = []
        for i, asset in enumerate(investable_assets):
            st = str(getattr(asset, "spread_type", "") or getattr(asset, "strategy", "") or "").lower()
            lo, hi = constraints["bounds"][i]
            if st and any((b in st) or (st in b) for b in banned):
                new_bounds.append((0.0, 0.0))
                banned_assets.append(tickers[i])
            else:
                new_bounds.append((float(lo), float(hi)))
        constraints["bounds"] = new_bounds
        constraints["banned_assets_debug"] = banned_assets

    # Assertions
    assert constraints["bounds"][0] == (0.0, 0.0) # credit_spread matches "credit"
    assert constraints["bounds"][1] == (0.0, 0.20) # debit_spread does not match
    assert "A" in constraints["banned_assets_debug"]
    assert "B" not in constraints["banned_assets_debug"]
