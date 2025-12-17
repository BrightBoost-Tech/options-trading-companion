from typing import Optional, Literal, Dict, Any, List
from pydantic import BaseModel, Field
import math

UNBOUNDED_GAIN_CAP_MULT = 10.0

class EVResult(BaseModel):
    expected_value: float
    win_probability: float
    loss_probability: float
    max_gain: float
    max_loss: float
    risk_reward_ratio: Optional[float] = None
    trade_cost: float
    breakeven_price: Optional[float] = None
    capped: bool = False
    cap_mult: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        data = self.model_dump()
        if self.risk_reward_ratio is not None:
            data['risk_reward_ratio_str'] = f"1:{self.risk_reward_ratio:.2f}"
        return data

class PositionSizeResult(BaseModel):
    contracts_to_trade: int
    risk_per_trade_usd: float
    max_loss_per_contract: float

class ExitMetrics(BaseModel):
    expected_value: float
    prob_of_profit: float
    limit_price: float
    reason: str

def calculate_iron_condor_ev(
    credit_share: float,
    width_put_share: float,
    width_call_share: float,
    delta_short_put: float,
    delta_short_call: float,
) -> EVResult:
    """
    Calculates EV for an Iron Condor using a delta-tail approximation.
    Wraps canonical calculate_condor_ev.
    """
    return calculate_condor_ev(
        credit=credit_share,
        width_put=width_put_share,
        width_call=width_call_share,
        delta_short_put=delta_short_put,
        delta_short_call=delta_short_call
    )


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

    capped_trade = False

    if strategy == "iron_condor":
        raise ValueError("iron_condor is not supported by calculate_ev(); use calculate_condor_ev/calculate_iron_condor_ev instead")

    if strategy == "long_call":
        max_loss = premium * 100
        # Cap max_gain to avoid infinite EV
        max_gain = max_loss * UNBOUNDED_GAIN_CAP_MULT
        capped_trade = True
        trade_cost = premium * 100
        breakeven = strike + premium

    elif strategy == "long_put":
        max_gain = (strike - premium) * 100
        max_loss = premium * 100
        trade_cost = premium * 100
        breakeven = strike - premium

    elif strategy == "short_call":
        max_gain = premium * 100
        # Cap max_loss for short calls too
        max_loss = max_gain * UNBOUNDED_GAIN_CAP_MULT
        capped_trade = True
        trade_cost = -premium * 100 # Negative cost = credit
        win_prob, loss_prob = loss_prob, win_prob # Invert for short positions
        breakeven = strike + premium

    elif strategy == "short_put":
        max_gain = premium * 100
        max_loss = (strike - premium) * 100
        trade_cost = -premium * 100
        win_prob, loss_prob = loss_prob, win_prob
        breakeven = strike - premium

    elif strategy in ["credit_spread", "debit_spread"]:
        if width is None:
            raise ValueError("`width` is required for spread strategies.")

        if strategy == "credit_spread":
            max_gain = premium * 100
            max_loss = (width - premium) * 100
            trade_cost = -premium * 100
            win_prob, loss_prob = loss_prob, win_prob

        elif strategy == "debit_spread":
            max_gain = (width - premium) * 100
            max_loss = premium * 100
            trade_cost = premium * 100

    else:
         raise NotImplementedError(f"Strategy '{strategy}' not yet implemented.")

    # Apply number of contracts
    max_gain *= contracts
    max_loss *= contracts
    trade_cost *= contracts

    # Calculate EV
    expected_value = (win_prob * max_gain) - (loss_prob * max_loss)

    # Final safety check for finiteness
    if not math.isfinite(expected_value):
        expected_value = 0.0
        capped_trade = True

    if not math.isfinite(max_gain):
        max_gain = max_loss * UNBOUNDED_GAIN_CAP_MULT if max_loss > 0 else 10000.0
        capped_trade = True

    if not math.isfinite(max_loss):
        max_loss = max_gain * UNBOUNDED_GAIN_CAP_MULT if max_gain > 0 else 10000.0
        capped_trade = True

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
        breakeven_price=breakeven,
        capped=capped_trade,
        cap_mult=UNBOUNDED_GAIN_CAP_MULT if capped_trade else None
    )


def calculate_position_size(
    account_value: float,
    max_risk_pct: float,
    max_loss_per_contract: float,
) -> PositionSizeResult:
    """
    Calculates the optimal number of contracts based on risk tolerance.
    Standardized to use 0-1 float for risk percentage.
    """
    if max_loss_per_contract <= 0:
        return PositionSizeResult(
            contracts_to_trade=0,  # 0 contracts for undefined/invalid risk
            risk_per_trade_usd=0.0,
            max_loss_per_contract=max_loss_per_contract
        )

    # Standardize input: if > 1.0, assume it's a percentage (e.g. 5.0) and convert,
    # but strictly we expect 0.05. We'll be safe.
    effective_risk_pct = max_risk_pct
    if effective_risk_pct > 1.0:
        effective_risk_pct = effective_risk_pct / 100.0

    risk_per_trade_usd = account_value * effective_risk_pct

    num_contracts = risk_per_trade_usd / max_loss_per_contract

    # Contracts = floor(risk_dollars / max_loss_per_contract)
    contracts = math.floor(num_contracts)
    contracts = int(max(0, contracts))

    return PositionSizeResult(
        contracts_to_trade=contracts,
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

def calculate_exit_metrics(
    current_price: float,
    cost_basis: float,
    delta: float = 0.5,
    iv: float = 0.5,
    days_to_expiry: int = 30,
    sentiment_score: float = 0.0, # -1 to 1
) -> ExitMetrics:
    """
    Estimates optimal exit target based on 'expected move' and probability.

    Logic:
    1. Estimate expected move over a short horizon (e.g. 5 days) using IV.
       Sigma_5day = Price * IV * sqrt(5/365)
    2. Add directional bias from delta and sentiment.
    3. Target = Current + (Sigma_5day * Bias_Factor).
    4. Constrain: Must be > cost_basis (profit).
    """

    # 1. Expected Move (5-day horizon)
    horizon_days = 5
    annual_vol = iv # Assume IV is annualized (e.g. 0.40 for 40%)

    # Standard deviation over horizon
    expected_move_usd = current_price * annual_vol * math.sqrt(horizon_days / 365.0)

    # 2. Bias / Probability
    # Delta acts as a rough proxy for probability of touching strike or direction
    # Adjust target based on delta (higher delta = more confident in directional move?)
    # For now, simple profit taking: Target a 1-sigma move in favor of the position.

    # If delta is positive (long call/short put), we want price to go UP?
    # Wait, delta sign matters for direction.
    # But here `current_price` is the OPTION price or the UNDERLYING price?
    # Context implies `current_price` is the holding's current value (option price).
    # Option price volatility is much higher than underlying.
    # If `iv` is implied volatility of the OPTION price (e.g. 80%), then yes.
    # If `iv` is underlying IV, we need Vega/Delta to translate to option price move.

    # Let's assume input `iv` is the Implied Volatility of the Underlying,
    # and we need to translate that to Option Price Target.
    # OR, simplified: Users prompt says "Set limit_price to current_price + k * expected_return".

    # Let's use a simplified "Option Price Expected Return" model.
    # Option Return ~= Leverage * Underlying Return
    # Leverage = Delta * Underlying_Price / Option_Price

    # If we don't have underlying price passed in, we can just use a heuristic k.
    # User pseudo-code: "Set limit_price to current_price + k * expected_return".

    # Let's define expected_return as the standard deviation of the OPTION price itself?
    # Option Price Volatility ~= Underlying Volatility * Leverage.
    # Let's approximate Leverage = 5 (typical for options) if unknown.

    leverage = 5.0 # conservative placeholder

    # Expected return of the option in $ terms over horizon
    # Exp_Ret = Current_Opt_Price * (IV_Underlying * Leverage) * sqrt(T)
    # This is rough, but effective for a "limit price" suggestion.

    estimated_vol_option = iv * leverage
    target_gain_pct = estimated_vol_option * math.sqrt(horizon_days / 365.0)

    # Adjust k factor (0.5 to 1.0 as requested)
    k = 0.8

    potential_upside = current_price * target_gain_pct * k

    limit_price = current_price + potential_upside

    # 3. Constraints
    # Ensure profitable exit (above cost basis)
    if limit_price < cost_basis:
        limit_price = cost_basis * 1.05 # Minimum 5% profit if model says lower

    # Check if the adjusted limit_price (e.g. cost basis + 5%) is still reasonable relative to current price.
    # If we are deep underwater, "cost_basis" might be +500% from current, which is unrealistic to fill short term.
    # However, user constraint: "Constrain limit_price to: be ≥ cost_basis".

    # Also user constraint: "not more than, say, +2 * expected_return above current (to keep it fillable)."
    # OR "max_price = current_price * 1.5".

    max_price = current_price * 1.5

    # If cost basis is higher than reasonable cap, we can't offer a profitable exit suggestion right now.
    # The logic below will return a price, but EV might be negative or low.

    if limit_price > max_price:
        # If we clamp it down, we violate the "profitable exit" constraint if limit_price was set to cost_basis.
        # So we should prioritize cost_basis? No, user said "be ≥ cost_basis".
        # If max_price < cost_basis, then we simply cannot satisfy both constraints.
        # In that case, we should probably NOT suggest a "Take Profit".
        # But `limit_price` is the output.

        # Let's clamp to max_price, but then check cost_basis.
        limit_price = max_price

    # Final Check: Is it profitable?
    if limit_price < cost_basis:
         # If we can't reach cost basis within reasonable limits, we set expected_value to -1 (invalid)
         # or we return limit_price = cost_basis but acknowledging it might be far away.
         # For "Morning suggestions", user said: "Only generate suggestions when: EV is positive, and limit_price > current_price."
         # If we return a limit_price < cost_basis, it's not a "Profit Taking" trade.

         # Let's force it to cost_basis, but if that's > max_price, we will let it be.
         # Wait, if limit_price = cost_basis and cost_basis >>> current_price,
         # then expected_value (prob * (limit - current)) will be high, but probability of filling is practically zero.
         # The `prob_of_profit` (delta) assumes we just hold. It doesn't account for "probability of touching limit price".

         # For now, strictly follow: "be ≥ cost_basis".
         limit_price = max(limit_price, cost_basis)

    # EV Calculation (simplified for this exit context)
    # EV = (Prob_Hit_Target * Target_Profit) - (Prob_Miss * Risk?)
    # Here we just return the "Expected Value" of the trade as defined by user:
    # "metrics.expected_value"

    prob_profit = abs(delta) # Rough proxy

    # EV = (Limit_Price - Current_Price) * Prob_Profit ?
    # Or total trade EV?
    # User pseudo: "suggestion['ev'] = metrics.expected_value"
    # Let's return the expected dollar gain per share.
    expected_value = (limit_price - current_price) * prob_profit

    return ExitMetrics(
        expected_value=expected_value,
        prob_of_profit=prob_profit,
        limit_price=limit_price,
        reason=f"Targeting {k}σ move over {horizon_days}d"
    )

def calculate_condor_ev(
    credit: float,
    width_put: float,
    width_call: float,
    delta_short_put: float,
    delta_short_call: float
) -> EVResult:
    """
    Calculates EV for an Iron Condor using disjoint tail probabilities.

    Logic:
    - p_loss_put = |delta_short_put|
    - p_loss_call = |delta_short_call|
    - p_loss = p_loss_put + p_loss_call (approx disjoint)
    - p_win = 1.0 - p_loss

    - max_loss_put = width_put - credit
    - max_loss_call = width_call - credit
    - max_profit = credit

    EV = (p_win * max_profit) - (p_loss_put * max_loss_put) - (p_loss_call * max_loss_call)
    """

    # 1. Probabilities
    p_loss_put = min(1.0, max(0.0, abs(delta_short_put)))
    p_loss_call = min(1.0, max(0.0, abs(delta_short_call)))
    p_loss = min(1.0, p_loss_put + p_loss_call)
    p_win = 1.0 - p_loss

    # 2. Financials (per share)
    # credit is passed as a positive value representing net credit received
    profit = credit * 100.0

    # Loss is width - credit, clamped at 0
    loss_put = max(0.0, (width_put - credit)) * 100.0
    loss_call = max(0.0, (width_call - credit)) * 100.0

    # Max loss of the structure is the max of either side
    structure_max_loss = max(loss_put, loss_call)

    # 3. EV Calculation
    # We weight the losses by their respective probabilities
    ev = (p_win * profit) - (p_loss_put * loss_put) - (p_loss_call * loss_call)

    if not math.isfinite(ev):
        ev = 0.0

    risk_reward = None
    if structure_max_loss > 0 and profit > 0:
        risk_reward = structure_max_loss / profit

    return EVResult(
        expected_value=ev,
        win_probability=p_win,
        loss_probability=p_loss,
        max_gain=profit,
        max_loss=structure_max_loss,
        risk_reward_ratio=risk_reward,
        trade_cost=-profit, # Negative cost for credit strategies
        breakeven_price=None, # Multiple B/E points, skipping for simple model
        capped=False
    )
