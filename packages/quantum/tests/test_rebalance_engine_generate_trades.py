
import pytest
import math
from packages.quantum.services.rebalance_engine import RebalanceEngine
# Mocking SpreadPosition if needed, or using dicts if the engine tolerates it.
# The engine expects SpreadPosition objects because it accesses attributes like .current_value, .ticker_key.
# But looking at the requested implementation in step 4:
# "if there is a position row: current_val = float(pos.get('current_value') or 0.0)"
# This implies the prompt wants the code to handle dicts OR objects?
# "For each key in targets_dict (and also each symbol present in spread_positions)"
# Wait, the prompt in step 4 says:
# "pos.get('current_value')" - this suggests pos is a dict.
# But the existing code uses SpreadPosition objects: "pos.current_value".
# Let's check the prompt step 4 carefully.

# "Determine current_val: if there is a position row: current_val = float(pos.get("current_value") or 0.0)"
# The prompt seems to imply I should treat `spread_positions` as a list of dicts or objects behaving like dicts in the new implementation?
# OR I should adapt the code to handle both? Or maybe the prompt assumes spread_positions are dicts?
# The prompt's test case says: spread_positions = [{"symbol":"AAA","current_value":1000.0,"quantity":10}]
# This is a list of dicts.
# The CURRENT code expects objects: "pos.current_value", "pos.ticker_key".
# If I follow the prompt instructions for the implementation, I will be writing code that does `pos.get("current_value")`.
# If the input `spread_positions` in the real app are objects (Pydantic models), `get` will fail unless I handle it.
# However, the prompt explicitly says: "Implement a single canonical trade-generation loop using ONLY known variables... Determine current_val: if there is a position row: current_val = float(pos.get("current_value") or 0.0)"

# This suggests the user might want me to support dicts (maybe from a test or simplified context) OR they might be mistaken about the input type.
# But since I am supposed to fix the bug and make it "correct + executable", and the test case provided uses dicts,
# I should probably support dict access.
# Ideally, I should support both or convert input.
# But strictly following the prompt instructions for the loop logic:
# It says "For each key in targets_dict (and also each symbol present in spread_positions)".
# And "Determine current_val: ... pos.get(...)".

# I will write the test as requested.
# And I will implement the code to handle the test case (dicts).
# If the real application passes objects, `pos.get` will fail on a Pydantic model (unless it has a get method or is compatible).
# Pydantic v2 models do not have `.get()`.
# The current code uses `pos.current_value`.
# I should probably make the code robust to handle both or checking what the user intends.
# "Goal: generate_trades() must not reference undefined locals... return deterministic list... based ONLY on inputs".

# Let's look at the PROMPT again.
# "Determine current_val: if there is a position row: current_val = float(pos.get("current_value") or 0.0)"
# The user might be simplifying the requirement description.
# Given the existing code uses `SpreadPosition` models, I should verify what `SpreadPosition` is.
# It is imported from `..models`.
# I'll check `packages/quantum/models.py`.

# If SpreadPosition is a Pydantic model, I should probably use `getattr(pos, 'current_value', 0.0)` or convert it to dict first.
# The prompt says: "pos.get('current_value')".
# If I write exactly what the prompt asks, it will work for the provided test case (dicts).
# Will it break the existing app if it passes objects? Yes.
# BUT, the prompt is "FIX a runtime-breaking bug... GOAL ... generate_trades() must not reference undefined locals".
# It also provides a specific logic implementation.
# I will assume the user knows what they are asking for regarding `pos.get`, OR I should enable `pos` to be a dict.
# Maybe I should convert incoming objects to dicts at the start of the function?
# Or maybe the prompt implies I should adapt the logic to work for the input.
# "3) In generate_trades(), remove the FIRST trade-building block... 4) Implement a single canonical trade-generation loop..."
# The instructions in step 4 are quite specific about the logic logic (using .get).
# It is safer to make the code handle both dicts and objects to avoid breaking the real app while satisfying the test.
# Or better: The test uses dicts. The real app uses objects.
# I will write the test first.

def test_generate_trades_no_nameerror_and_deterministic():
    engine = RebalanceEngine()
    # Mock ExecutionService not needed as per prompt "Instantiate engine minimally".

    spread_positions = [{"symbol":"AAA","current_value":1000.0,"quantity":10}]
    targets_dict = {"AAA": 0.05, "BBB": 0.02}
    portfolio_value = 10000.0
    pricing_data = {"AAA":{"price":100.0},"BBB":{"price":50.0}}

    trades = engine.generate_trades(
        current_holdings=spread_positions,
        target_weights=targets_dict,
        total_equity=portfolio_value,
        deployable_capital=portfolio_value, # Not specified in prompt for this arg, but needed by signature
        pricing_data=pricing_data
    )

    # Expect:
    # AAA target=500 (0.05 * 10000), current=1000. diff=-500.
    # price_unit AAA = 100.
    # qty_delta = floor(500/100) = 5. side=sell.

    # BBB target=200 (0.02 * 10000), current=0. diff=200.
    # price_unit BBB = 50.
    # qty_delta = floor(200/50) = 4. side=buy.

    assert len(trades) == 2

    # Sort order is by abs(value_delta) descending.
    # AAA value_delta = 5 * 100 * -1 = -500. abs=500.
    # BBB value_delta = 4 * 50 * 1 = 200. abs=200.
    # So AAA comes first.

    t1 = trades[0]
    t2 = trades[1]

    assert t1["symbol"] == "AAA"
    assert t1["action"] == "sell"
    assert t1["quantity"] == 5

    assert t2["symbol"] == "BBB"
    assert t2["action"] == "buy"
    assert t2["quantity"] == 4
