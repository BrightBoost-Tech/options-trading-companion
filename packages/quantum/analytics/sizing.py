
import math

def calculate_contract_size(
    target_dollar_exposure: float,
    share_price: float,
    option_delta: float,
    max_loss_per_contract: float,
    portfolio_value: float,
    max_risk_percent: float = 2.0
) -> int:
    """
    Calculates the number of option contracts to trade based on delta equivalence
    and a maximum portfolio risk constraint.

    Args:
        target_dollar_exposure: The target value of the equivalent stock position.
        share_price: The current price of the underlying stock.
        option_delta: The delta of the chosen option contract.
        max_loss_per_contract: The maximum potential loss for one contract.
        portfolio_value: The total value of the portfolio.
        max_risk_percent: The maximum percentage of the portfolio to risk (e.g., 2.0 for 2%).

    Returns:
        The recommended number of contracts, rounded down to the nearest integer.
    """
    if share_price <= 0 or option_delta == 0 or max_loss_per_contract <= 0 or portfolio_value <= 0:
        return 0

    # 1. Calculate ideal contracts based on delta-equivalent exposure
    # This tells us how many contracts are needed to mimic the share exposure.
    try:
        delta_equivalent_contracts = (target_dollar_exposure / share_price) / (option_delta * 100)
    except ZeroDivisionError:
        delta_equivalent_contracts = 0

    # 2. Calculate max allowed contracts based on portfolio risk guardrail
    # This is the safety override.
    total_max_loss_allowed = portfolio_value * (max_risk_percent / 100)
    risk_based_contracts = total_max_loss_allowed / max_loss_per_contract

    # 3. Use the more conservative of the two calculations
    # We cannot exceed our risk limit, even if the optimizer wants more exposure.
    final_contracts = min(abs(delta_equivalent_contracts), risk_based_contracts)

    # Return the floor to be conservative, ensuring we don't trade partial contracts.
    return math.floor(final_contracts)
