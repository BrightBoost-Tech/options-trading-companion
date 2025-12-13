import pytest
import random
from packages.quantum.strategy_profiles import CostModelConfig
from packages.quantum.services.transaction_cost_model import TransactionCostModel

def test_tcm_determinism():
    config = CostModelConfig(spread_slippage_bps=10, fill_probability_model="neutral")
    tcm = TransactionCostModel(config)

    seed = 42
    rng1 = random.Random(seed)
    res1 = tcm.simulate_fill(100.0, 10, "buy", rng1)

    rng2 = random.Random(seed)
    res2 = tcm.simulate_fill(100.0, 10, "buy", rng2)

    assert res1.fill_price == res2.fill_price
    assert res1.slippage_paid == res2.slippage_paid
    assert res1.commission_paid == res2.commission_paid

def test_tcm_slippage_buy():
    config = CostModelConfig(spread_slippage_bps=100, fill_probability_model="optimistic") # 1% slippage
    tcm = TransactionCostModel(config)

    # Optimistic = 0 impact
    res = tcm.simulate_fill(100.0, 10, "buy")
    assert res.fill_price == 100.0
    assert res.slippage_paid == 0.0

    config.fill_probability_model = "neutral"
    # Neutral = Impact with jitter
    res = tcm.simulate_fill(100.0, 10, "buy")
    assert res.fill_price > 100.0
    assert res.slippage_paid > 0.0

def test_tcm_slippage_sell():
    config = CostModelConfig(spread_slippage_bps=100, fill_probability_model="neutral")
    tcm = TransactionCostModel(config)

    res = tcm.simulate_fill(100.0, 10, "sell")
    assert res.fill_price < 100.0
    assert res.slippage_paid > 0.0
