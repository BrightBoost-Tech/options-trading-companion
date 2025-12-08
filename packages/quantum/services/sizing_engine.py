import math

def calculate_sizing(
    account_buying_power: float,
    ev_per_contract: float,
    contract_ask: float,
    max_risk_pct: float = 0.05,
    profile: str = "balanced"
) -> dict:
    """
    Calculates the appropriate position size based on risk and account value.

    Args:
        account_buying_power (float): Total available buying power in the account.
        ev_per_contract (float): Expected Value per contract (not used for basic sizing but kept for interface).
        contract_ask (float): The cost to buy one contract (premium).
        max_risk_pct (float): Maximum percentage of account to risk on this trade.
        profile (str): User risk profile ('balanced' or 'aggressive').

    Returns:
        dict: {
          "contracts": int,
          "reason": str,
          "capital_required": float
        }
    """

    # Override risk pct for aggressive profile
    if profile.upper() == "AGGRESSIVE":
        max_risk_pct = 0.40

    # Validation
    if account_buying_power <= 0:
        return {
            "contracts": 0,
            "reason": "No buying power available",
            "capital_required": 0.0
        }

    if contract_ask <= 0:
        return {
            "contracts": 0,
            "reason": "Invalid contract price",
            "capital_required": 0.0
        }

    # Logic
    # Max dollar risk = account_buying_power * max_risk_pct
    max_dollar_risk = account_buying_power * max_risk_pct

    # Risk per contract (Assuming max loss is the premium paid for long positions)
    # For spreads, this might be width - credit, but starting simple as per instructions:
    # "Risk per contract ≈ contract_ask * 100"
    risk_per_contract = contract_ask * 100.0

    if risk_per_contract <= 0:
         return {
            "contracts": 0,
            "reason": "Invalid risk per contract",
            "capital_required": 0.0
        }

    # Contracts = floor(max_dollar_risk / risk_per_contract)
    contracts = math.floor(max_dollar_risk / risk_per_contract)
    contracts = max(0, int(contracts))

    capital_required = contracts * risk_per_contract

    # Determine if max risk is exceeded (for dev override logic)
    # Exceeded if raw capital required > max_dollar_risk or > account_buying_power
    # But contracts logic above already caps it.
    # The flag is meant to signal if the *uncapped* request would be too risky, OR
    # if the resulting trade is at the limit.
    # Spec: "max_risk_exceeded = capital_required > max_per_trade or capital_required > account_buying_power"
    # But capital_required is calculated FROM contracts which is already capped.
    # So checking `capital_required > max_dollar_risk` will usually be False (due to floor).
    # However, if we recalculate what *would* be needed for 1 contract vs limit...
    # Spec says: "Set max_per_trade = account_buying_power * max_risk_pct. max_risk_exceeded = capital_required > max_per_trade..."
    # If `contracts` was clamped to 0 because 1 contract cost > max_dollar_risk, then `capital_required` is 0.
    # In that case 0 is not > max_per_trade.
    # But we want to flag it so dev mode doesn't override it if it's truly risky.
    # If contracts == 0 and risk_per_contract > max_dollar_risk, then it IS exceeded.

    max_risk_exceeded = False
    if contracts > 0:
        # If we found valid contracts, check if we hit the ceiling
        # Actually, if we are within limits, we are fine.
        # But let's follow the logic: is the *trade* (even 1 unit) exceeding risk?
        if risk_per_contract > max_dollar_risk or risk_per_contract > account_buying_power:
             max_risk_exceeded = True
    else:
        # If 0 contracts, check if it was due to risk
        if risk_per_contract > max_dollar_risk or risk_per_contract > account_buying_power:
            max_risk_exceeded = True

    reason = "Optimal size based on risk"
    if contracts == 0:
        if max_dollar_risk < risk_per_contract:
            reason = f"Insufficient risk budget (Need ${risk_per_contract:.2f}, Have ${max_dollar_risk:.2f})"
        else:
            reason = "Calculated zero contracts"
    elif contracts > 0:
         reason = f"Capped by {max_risk_pct*100}% risk rule"

    return {
        "contracts": contracts,
        "reason": reason,
        "capital_required": capital_required,
        "max_risk_exceeded": max_risk_exceeded,
        "stop_loss": round(contract_ask * 0.5, 2),  # Example: 50% stop loss
        "target_price": round(contract_ask * 1.5, 2) # Example: 50% profit target
    }
