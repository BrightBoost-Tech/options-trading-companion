import random
from typing import Tuple, Optional, Literal
from pydantic import BaseModel
from packages.quantum.strategy_profiles import CostModelConfig

class ExecutionResult(BaseModel):
    filled_quantity: float
    fill_price: float
    slippage_paid: float
    commission_paid: float
    status: Literal["filled", "partial", "no_fill", "rejected"]

class TransactionCostModel:
    """
    Unified Transaction Cost Model (TCM) for Paper Execution and Backtesting.
    Ensures consistent slippage and fee calculations across environments.
    """
    def __init__(self, config: CostModelConfig = None):
        self.config = config or CostModelConfig()

    def estimate_costs(self, price: float, quantity: float, side: str) -> float:
        """
        Returns estimated total transaction cost (commission + slippage impact).
        Does not simulate fill probability.
        """
        slippage_pct = self.config.spread_slippage_bps / 10000.0
        slippage_cost = (price * slippage_pct) * quantity
        commission = max(self.config.min_fee, self.config.commission_per_contract * quantity)
        return slippage_cost + commission

    def simulate_fill(self,
                      price: float,
                      quantity: float,
                      side: str,
                      rng: random.Random = None) -> ExecutionResult:
        """
        Simulates fill price and quantity based on cost model.
        Returns ExecutionResult with final price and costs.
        """
        if rng is None:
            rng = random.Random()

        slippage_pct = self.config.spread_slippage_bps / 10000.0
        impact = price * slippage_pct

        # Adjust impact based on model
        if self.config.fill_probability_model == "optimistic":
            impact = 0
        elif self.config.fill_probability_model == "conservative":
            impact *= 1.5
            # Maybe add a chance of partial fill?
            # if rng.random() < 0.1:
            #     quantity *= 0.5
            #     status = "partial"

        # Jitter: Randomize slippage slightly [0.5, 1.5] around mean impact
        # Only if neutral/conservative
        if self.config.fill_probability_model != "optimistic":
            jitter = rng.uniform(0.5, 1.5)
            impact *= jitter

        # Apply slippage to price
        # Buy: Price increases (pay more)
        # Sell: Price decreases (receive less)
        if side.lower() == "buy":
            fill_price = price + impact
        else:
            fill_price = price - impact

        commission = max(self.config.min_fee, self.config.commission_per_contract * quantity)
        slippage_paid = abs(fill_price - price) * quantity

        return ExecutionResult(
            filled_quantity=quantity,
            fill_price=fill_price,
            slippage_paid=slippage_paid,
            commission_paid=commission,
            status="filled"
        )
