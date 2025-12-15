import math
from typing import Dict, Any, Optional

def calculate_sizing(
    account_buying_power: float,
    max_loss_per_contract: float,
    collateral_required_per_contract: float,
    max_risk_pct: float = 0.02,
    risk_multiplier: float = 1.0,
    profile: str = "balanced",
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
        max_loss_per_contract (float): Maximum loss for a single contract unit (e.g. spread width or premium).
        collateral_required_per_contract (float): Buying power reduction per contract.
        max_risk_pct (float): Base risk percentage (0.0 - 1.0). Default 0.02 (2%).
        risk_multiplier (float): Multiplier for risk (e.g. from Kelly or Conviction). Default 1.0.
        profile (str): Risk profile ('balanced' or 'aggressive'). Used for caps.

    Returns:
        dict: {
          "contracts": int,
          "reason": str,
          "capital_required": float,
          "max_loss_total": float,
          "max_risk_exceeded": bool,
          ...
        }
    """

    # 1. Profile-based Guardrails (User requested removal of 0.40 aggressive)
    # Cap aggressive at something sane, e.g. 0.05
    effective_risk_pct = max_risk_pct

    # If input is > 1.0, normalize it just in case
    if effective_risk_pct > 1.0:
        effective_risk_pct = effective_risk_pct / 100.0

    if profile.lower() == "aggressive":
        # Hard cap aggressive risk to 5% if it wasn't already set higher explicitly?
        # User said: "Cap aggressive to something sane (<=0.05)"
        if effective_risk_pct > 0.05:
            effective_risk_pct = 0.05
    else:
        # Balanced: Cap at 2% if not set
        if effective_risk_pct > 0.02:
            effective_risk_pct = 0.02

    # 2. Validation
    if account_buying_power <= 0:
        return {
            "contracts": 0,
            "reason": "No buying power available",
            "capital_required": 0.0,
            "max_loss_total": 0.0,
            "max_risk_exceeded": False
        }

    if max_loss_per_contract <= 0:
         return {
            "contracts": 0,
            "reason": f"Invalid max_loss_per_contract: {max_loss_per_contract}",
            "capital_required": 0.0,
            "max_loss_total": 0.0,
            "max_risk_exceeded": False
        }

    # 3. Calculate Risk Budget
    risk_dollars = account_buying_power * effective_risk_pct * risk_multiplier

    # 4. Calculate Contracts based on Max Loss
    contracts = math.floor(risk_dollars / max_loss_per_contract)
    contracts = int(max(0, contracts))

    # 5. Calculate Capital Required (Collateral Check)
    capital_required = contracts * collateral_required_per_contract

    # 6. Check Buying Power Constraint
    if capital_required > account_buying_power:
        # If we can't afford the collateral, reduce contracts
        if collateral_required_per_contract > 0:
            contracts = math.floor(account_buying_power / collateral_required_per_contract)
            contracts = int(max(0, contracts))
            capital_required = contracts * collateral_required_per_contract

    # Recalculate totals
    max_loss_total = contracts * max_loss_per_contract

    # 7. Reason Generation
    reason = "Optimal size based on risk"
    if contracts == 0:
        if risk_dollars < max_loss_per_contract:
            reason = f"Risk budget (${risk_dollars:.2f}) < 1 contract risk (${max_loss_per_contract:.2f})"
        elif account_buying_power < collateral_required_per_contract:
             reason = f"Insuff. BP (${account_buying_power:.2f}) for collateral (${collateral_required_per_contract:.2f})"
    else:
        reason = f"Sized for {effective_risk_pct*100:.1f}% risk (x{risk_multiplier})"

    return {
        "contracts": contracts,
        "reason": reason,
        "capital_required": capital_required,
        "max_loss_total": max_loss_total,
        "max_risk_exceeded": False, # Flag if we wanted more but hit a cap? (removed for simplicity unless requested)
        "risk_pct_used": effective_risk_pct,
        "risk_multiplier": risk_multiplier,
        "stop_loss": None, # Should be calculated elsewhere
        "target_price": None
    }
