from typing import Optional, Literal, Dict, Any
from pydantic import BaseModel, Field

class EVResult(BaseModel):
    expected_value: float
    win_probability: float
    loss_probability: float
    max_gain: float
    max_loss: float
    risk_reward_ratio: Optional[float] = None
    trade_cost: float
    breakeven_price: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        data = self.model_dump()
        if self.risk_reward_ratio is not None:
            data['risk_reward_ratio_str'] = f"1:{self.risk_reward_ratio:.2f}"
        return data

class PositionSizeResult(BaseModel):
    contracts_to_trade: int
    risk_per_trade_usd: float
    max_loss_per_contract: float

def calculate_ev(
    premium: float,
    strike: float,
    current_price: float,
    delta: float,
    strategy: Literal["long_call", "long_put", "short_call", "short_put",
                      "credit_spread", "debit_spread", "iron_condor", "strangle"],
    width: Optional[float] = None,
    contracts: int = 1
) -> EVResult:
    """
    Calculates the Expected Value (EV) of an options trade.
    """
    delta = abs(delta) # Use absolute delta for probability
    win_prob = delta
    loss_prob = 1 - delta

    max_gain = 0
    max_loss = 0
    trade_cost = 0
    breakeven = None

    if strategy == "long_call":
        max_gain = float('inf')
        max_loss = premium * 100
        trade_cost = premium * 100
        breakeven = strike + premium

    elif strategy == "long_put":
        max_gain = (strike - premium) * 100
        max_loss = premium * 100
        trade_cost = premium * 100
        breakeven = strike - premium

    elif strategy == "short_call":
        max_gain = premium * 100
        max_loss = float('inf')
        trade_cost = -premium * 100 # Negative cost = credit
        win_prob, loss_prob = loss_prob, win_prob # Invert for short positions
        breakeven = strike + premium

    elif strategy == "short_put":
        max_gain = premium * 100
        max_loss = (strike - premium) * 100
        trade_cost = -premium * 100
        win_prob, loss_prob = loss_prob, win_prob
        breakeven = strike - premium

    elif strategy in ["credit_spread", "debit_spread", "iron_condor"]:
        if width is None:
            raise ValueError("`width` is required for spread and condor strategies.")

        if strategy == "credit_spread":
            max_gain = premium * 100
            max_loss = (width - premium) * 100
            trade_cost = -premium * 100
            win_prob, loss_prob = loss_prob, win_prob

        elif strategy == "debit_spread":
            max_gain = (width - premium) * 100
            max_loss = premium * 100
            trade_cost = premium * 100

        elif strategy == "iron_condor":
            max_gain = premium * 100
            max_loss = (width - premium) * 100
            trade_cost = -premium * 100
            win_prob = delta * 2 # Simplified approximation for condors

    else:
         raise NotImplementedError(f"Strategy '{strategy}' not yet implemented.")

    # Apply number of contracts
    max_gain *= contracts
    max_loss *= contracts
    trade_cost *= contracts

    # Calculate EV
    expected_value = (win_prob * max_gain) - (loss_prob * max_loss)

    risk_reward = None
    if max_loss > 0 and max_gain > 0:
        risk_reward = max_loss / max_gain

    return EVResult(
        expected_value=expected_value,
        win_probability=win_prob,
        loss_probability=loss_prob,
        max_gain=max_gain,
        max_loss=max_loss,
        risk_reward_ratio=risk_reward,
        trade_cost=trade_cost,
        breakeven_price=breakeven
    )


def calculate_position_size(
    account_value: float,
    max_risk_percent: float,
    max_loss_per_contract: float,
) -> PositionSizeResult:
    """
    Calculates the optimal number of contracts based on risk tolerance.
    """
    if max_loss_per_contract <= 0:
        return PositionSizeResult(
            contracts_to_trade=1, # Default for no-risk/undefined-risk trades
            risk_per_trade_usd=0,
            max_loss_per_contract=max_loss_per_contract
        )

    risk_per_trade_usd = account_value * (max_risk_percent / 100)

    num_contracts = risk_per_trade_usd / max_loss_per_contract

    return PositionSizeResult(
        contracts_to_trade=int(max(1, num_contracts)), # Trade at least 1 contract
        risk_per_trade_usd=risk_per_trade_usd,
        max_loss_per_contract=max_loss_per_contract
    )


class PositionSizingResult(BaseModel):
    ev_amount: float
    ev_percent: float
    win_rate: float
    recommended_contracts: int
    risk_of_ruin_contribution: float
    kelly_fraction: float
    rationale: str

def calculate_kelly_sizing(
    entry_price: float,
    max_loss: float,
    max_profit: float,
    prob_profit: float,
    account_value: float,
    kelly_multiplier: float = 0.5,
) -> PositionSizingResult:
    """
    Compounding Small-Edge mode sizing:
    - Uses a simplified Kelly-style fraction.
    - Applies fractional Kelly via `kelly_multiplier` (default: half-Kelly).
    - Hard-caps risk per trade at 5% of account_value.
    - Returns 0 contracts if EV is non-positive or invalid.
    """
    prob_loss = 1.0 - prob_profit
    ev = (prob_profit * max_profit) - (prob_loss * max_loss)

    # Avoid division by zero in ev_percent
    denominator = max_loss if max_loss > 0 else 1.0
    ev_percent = (ev / denominator) * 100.0

    # Basic validity checks
    if max_loss <= 0 or ev <= 0:
        return PositionSizingResult(
            ev_amount=ev,
            ev_percent=ev_percent,
            win_rate=prob_profit,
            recommended_contracts=0,
            risk_of_ruin_contribution=0.0,
            kelly_fraction=0.0,
            rationale="Negative EV or invalid risk profile"
        )

    # Kelly Calculation
    # b = odds received on the wager = (profit / loss)
    b = max_profit / max_loss

    # Kelly fraction f = (p * b - q) / b
    # where p = win probability, q = loss probability
    raw_kelly = ((prob_profit * b) - prob_loss) / b
    safe_kelly = max(0.0, raw_kelly * kelly_multiplier)

    # Sizing Logic
    max_risk_dollars = account_value * 0.05  # Hard cap 5% risk
    kelly_allocation = account_value * safe_kelly

    # Allowable risk is min of Kelly allocation and Hard cap
    allowed_risk = min(kelly_allocation, max_risk_dollars)

    # Contract sizing (assuming max_loss is risk per contract)
    risk_per_contract = max_loss
    ideal_size = int(allowed_risk // risk_per_contract)
    ideal_size = max(0, ideal_size)

    # Heuristic for Risk of Ruin Contribution
    # Simplified: Higher allocation + lower win rate = higher ruin risk
    # This is a qualitative score 0.0 - 1.0
    ruin_risk = 0.0
    if ideal_size > 0:
        actual_risk_pct = (ideal_size * risk_per_contract) / account_value
        ruin_risk = actual_risk_pct * (1.0 - prob_profit) * 10.0 # Scaling factor

    rationale = f"Kelly {safe_kelly:.2f} -> {ideal_size} contracts"

    return PositionSizingResult(
        ev_amount=ev,
        ev_percent=ev_percent,
        win_rate=prob_profit,
        recommended_contracts=ideal_size,
        risk_of_ruin_contribution=ruin_risk,
        kelly_fraction=safe_kelly,
        rationale=rationale
    )
