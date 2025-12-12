from typing import Dict, Any
from packages.quantum.optimizer import calculate_dynamic_target

def test_dynamic_constraints_with_conviction():
    # Base params
    # Use a strategy type that has a high enough cap to allow modulation
    # "debit_call" cap is 0.10 in default regime
    strategy_type = "debit_call"
    regime = "normal"
    base_weight = 0.08 # Below cap (0.10) but high enough to be scaled down

    # 1. Test High Conviction (1.0) -> Should be close to base_weight
    # scale = 0.5 + 0.5*1.0 = 1.0
    w_high = calculate_dynamic_target(
        base_weight=base_weight,
        strategy_type=strategy_type,
        regime=regime,
        conviction=1.0
    )
    # 0.08 * 1.0 = 0.08. Min(0.08, 0.10) = 0.08
    assert w_high == 0.08

    # 2. Test Low Conviction (0.0) -> Should be significantly reduced
    # scale = 0.5 + 0.5*0.0 = 0.5
    w_low = calculate_dynamic_target(
        base_weight=base_weight,
        strategy_type=strategy_type,
        regime=regime,
        conviction=0.0
    )
    # 0.08 * 0.5 = 0.04. Min(0.04, 0.10) = 0.04
    assert w_low == 0.04

    # Assert scaling logic
    assert w_low < w_high

    # 3. Test Medium Conviction (0.5)
    # scale = 0.75
    w_mid = calculate_dynamic_target(
        base_weight=base_weight,
        strategy_type=strategy_type,
        regime=regime,
        conviction=0.5
    )
    # 0.08 * 0.75 = 0.06
    assert w_mid == 0.06
    assert w_low < w_mid < w_high

def test_conviction_cap_behavior():
    # If base weight is huge, it should be capped regardless of conviction
    huge_weight = 0.50
    strategy_type = "debit_call" # Cap 0.10

    w_capped = calculate_dynamic_target(
        base_weight=huge_weight,
        strategy_type=strategy_type,
        regime="normal",
        conviction=1.0
    )
    # Should be capped at 0.10
    assert w_capped <= 0.10
    assert w_capped < huge_weight

    # Even with low conviction, if huge_weight * scale > cap, it should be capped?
    # huge_weight * 0.5 = 0.25 > 0.10. So it should still be 0.10.
    w_capped_low = calculate_dynamic_target(
        base_weight=huge_weight,
        strategy_type=strategy_type,
        regime="normal",
        conviction=0.0
    )
    assert w_capped_low == 0.10
