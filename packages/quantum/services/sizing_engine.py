import math
from typing import Dict, Any, Optional

def calculate_sizing(
    account_buying_power: float,
    max_loss_per_contract: float,
    collateral_required_per_contract: float,
    max_risk_pct: float = 0.02,
    risk_multiplier: float = 1.0,
    profile: str = "balanced",
    risk_budget_dollars: Optional[float] = None,
    max_contracts: int = 100,
    # Deprecated/Legacy args kept for signature compatibility if needed, but unused
    ev_per_contract: float = 0.0,
    contract_ask: float = 0.0,
) -> Dict[str, Any]:
    """
    Calculates the appropriate position size based on max loss (risk) and available capital.

    Canonical Formula:
      risk_dollars = account_value * max_risk_pct * risk_multiplier
      contracts = floor(risk_dollars / max_loss_per_contract)
      capital_required = contracts * collateral_required_per_contract

    Args:
        account_buying_power (float): Total deployable capital.
        max_loss_per_contract (float): Maximum loss for a single contract unit.
        collateral_required_per_contract (float): Buying power reduction per contract.
        max_risk_pct (float): Base risk percentage (0.0 - 1.0). Default 0.02 (2%).
        risk_multiplier (float): Multiplier for risk (e.g. from Kelly or Conviction). Default 1.0.
        profile (str): Risk profile ('balanced' or 'aggressive'). Used for caps.
        risk_budget_dollars (float, optional): Absolute risk budget in dollars. Overrides percentage calc.
        max_contracts (int): Hard limit on number of contracts. Default 100.

    Returns:
        dict: {
          "contracts": int,
          "reason": str,
          "capital_required": float,
          "max_dollar_risk": float,
          ...
        }
    """

    # 1. Validation
    if account_buying_power <= 0:
        return {
            "contracts": 0,
            "reason": "No buying power available",
            "capital_required": 0.0,
            "max_dollar_risk": 0.0,
            "max_risk_exceeded": False
        }

    # 2. Determine Max Dollar Risk
    max_dollar_risk = 0.0
    reason_prefix = ""

    if risk_budget_dollars is not None:
        # Absolute Sizing Mode
        max_dollar_risk = max(0.0, float(risk_budget_dollars)) * float(risk_multiplier)
        reason_prefix = f"Sized by budget ${max_dollar_risk:.2f}"
    else:
        # Percentage Sizing Mode
        effective_risk_pct = max_risk_pct

        # Normalize if > 1.0
        if effective_risk_pct > 1.0:
            effective_risk_pct = effective_risk_pct / 100.0

        # Profile Caps
        if profile.lower() == "aggressive":
            # Cap aggressive risk to 5%
            if effective_risk_pct > 0.05:
                effective_risk_pct = 0.05
        else:
            # Balanced: Cap at 2%
            if effective_risk_pct > 0.02:
                effective_risk_pct = 0.02

        max_dollar_risk = account_buying_power * effective_risk_pct * risk_multiplier
        reason_prefix = f"Sized for {effective_risk_pct*100:.1f}% risk (x{risk_multiplier})"

    # 3. Calculate Contracts by Risk
    if max_loss_per_contract <= 0:
        # If max loss is zero/negative (undefined risk), we can't size by risk strictly.
        # Fallback: treat as if risk is infinite or handle gracefully?
        # User prompt says: "If max_loss_per_contract is <= 0 or inf => contracts_by_risk = 0"
        contracts_by_risk = 0
    else:
        contracts_by_risk = math.floor(max_dollar_risk / max_loss_per_contract)

    # 4. Calculate Contracts by Collateral (Buying Power)
    if collateral_required_per_contract <= 0:
        # Treat as no collateral constraint -> infinite (limited by risk only)
        contracts_by_collateral = float('inf')
    else:
        contracts_by_collateral = math.floor(account_buying_power / collateral_required_per_contract)

    # 5. Final Contracts
    # min(risk_contracts, collateral_contracts, max_contracts)
    contracts = min(contracts_by_risk, contracts_by_collateral, max_contracts)
    contracts = int(max(0, contracts))

    # 6. Computed Totals
    capital_required = contracts * collateral_required_per_contract
    max_loss_total = contracts * max_loss_per_contract

    # 7. Refine Reason
    reason = reason_prefix
    if contracts == 0:
        if max_loss_per_contract > 0 and max_dollar_risk < max_loss_per_contract:
            reason = f"Risk budget (${max_dollar_risk:.2f}) < 1 contract risk (${max_loss_per_contract:.2f})"
        elif collateral_required_per_contract > 0 and account_buying_power < collateral_required_per_contract:
             reason = f"Insuff. BP (${account_buying_power:.2f}) for collateral (${collateral_required_per_contract:.2f})"
        elif max_loss_per_contract <= 0:
            reason = "Invalid max_loss_per_contract"
    elif contracts == max_contracts:
        reason += " (capped by max_contracts)"
    elif contracts == contracts_by_collateral and contracts < contracts_by_risk:
        reason += " (capped by buying power)"

    return {
        "contracts": contracts,
        "reason": reason,
        "capital_required": capital_required,
        "max_dollar_risk": max_dollar_risk, # The computed risk budget
        "max_loss_total": max_loss_total,
        "max_risk_exceeded": False,
        "risk_multiplier": risk_multiplier,
        "risk_budget_dollars": risk_budget_dollars
    }
