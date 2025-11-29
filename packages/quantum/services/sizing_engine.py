import math

def calculate_sizing(
    account_buying_power: float,
    ev_per_contract: float,
    contract_ask: float,
    max_risk_pct: float = 0.05
) -> dict:
    """
    Calculates the appropriate position size based on risk and account value.

    Args:
        account_buying_power (float): Total available buying power in the account.
        ev_per_contract (float): Expected Value per contract (not used for basic sizing but kept for interface).
        contract_ask (float): The cost to buy one contract (premium).
        max_risk_pct (float): Maximum percentage of account to risk on this trade.

    Returns:
        dict: {
          "contracts": int,
          "reason": str,
          "capital_required": float
        }
    """

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
        "stop_loss": round(contract_ask * 0.5, 2),  # Example: 50% stop loss
        "target_price": round(contract_ask * 1.5, 2) # Example: 50% profit target
    }
