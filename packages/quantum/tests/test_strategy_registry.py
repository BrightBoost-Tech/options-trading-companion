import pytest
from packages.quantum.strategy_registry import infer_strategy_key_from_suggestion

def test_infer_strategy_key():
    # 1. Explicit key
    assert infer_strategy_key_from_suggestion({"strategy_key": "iron_condor"}) == "iron_condor"
    assert infer_strategy_key_from_suggestion({"strategy_key": "Iron_Condor"}) == "iron_condor"

    # 2. Strategy Type
    assert infer_strategy_key_from_suggestion({"strategy_type": "vertical_spread"}) == "vertical_spread"
    assert infer_strategy_key_from_suggestion({"strategy": "Long Call"}) == "long_call"
    assert infer_strategy_key_from_suggestion({"type": "Credit-Put-Spread"}) == "credit_put_spread"

    # 3. Order JSON
    assert infer_strategy_key_from_suggestion({
        "order_json": {"strategy_type": "debit_call"}
    }) == "debit_call"

    # 4. Priority
    assert infer_strategy_key_from_suggestion({
        "strategy_key": "winner",
        "strategy_type": "loser"
    }) == "winner"

    # 5. Fallback
    assert infer_strategy_key_from_suggestion({}) == "unknown"
