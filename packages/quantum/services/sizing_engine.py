import math
from typing import Any, Dict, List, Optional


# Round-trip BP safety factor for #100 / Option A.
# Applied to estimated_close_bp only (NOT to the entry+close sum).
# Calibration set per docs/designs/option_a_round_trip_bp.md Section 6
# regression results.
# Revision plan: see same doc Section 5.
DEFAULT_ROUND_TRIP_SAFETY_FACTOR = 1.1


# Strategy-keyed close-BP shape per docs/designs/option_a_round_trip_bp.md
# Section 3 formula table. "DEBIT" → max_loss (Alpaca's conservative gate
# treats multi-leg combo close as ~entry premium); "CREDIT" → 0 (BP held
# at entry); single-leg long → 0 (sell-to-close); IRON_CONDOR → 2× (bilateral).
_DEBIT_SPREAD_STRATEGIES = {
    "LONG_CALL_DEBIT_SPREAD",
    "LONG_PUT_DEBIT_SPREAD",
}
_CREDIT_SPREAD_STRATEGIES = {
    "SHORT_CALL_CREDIT_SPREAD",
    "SHORT_PUT_CREDIT_SPREAD",
}
_SINGLE_LEG_LONG_STRATEGIES = {
    "LONG_CALL",
    "LONG_PUT",
}


def estimate_close_bp(
    strategy: Optional[str],
    max_loss_per_contract: float,
    legs: Optional[List[Dict[str, Any]]] = None,
) -> float:
    """Estimate Alpaca's conservative buying-power requirement to close
    one contract of this strategy at adverse-move worst case.

    See docs/designs/option_a_round_trip_bp.md Section 3 for derivation.
    Modeled empirically against 2026-05-01 BAC observation (#100).

    Args:
        strategy: Strategy name (case-insensitive). None / empty falls
            through to conservative default (full max_loss).
        max_loss_per_contract: Per-contract max loss in dollars.
        legs: Reserved for future Formula B (quote-based). Unused in v1.

    Returns:
        Per-contract close-BP estimate in dollars.
    """
    if max_loss_per_contract <= 0:
        return 0.0

    key = (strategy or "").upper()

    if key in _SINGLE_LEG_LONG_STRATEGIES:
        return 0.0
    if key in _CREDIT_SPREAD_STRATEGIES:
        return 0.0
    if key in _DEBIT_SPREAD_STRATEGIES:
        return float(max_loss_per_contract)
    if key == "IRON_CONDOR":
        return 2.0 * float(max_loss_per_contract)

    # Unknown / None / empty → conservative default (full max_loss).
    # Better to over-reject novel strategies than stuck-close.
    return float(max_loss_per_contract)


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
    *,
    strategy: Optional[str] = None,
    safety_factor: float = DEFAULT_ROUND_TRIP_SAFETY_FACTOR,
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
        strategy (str, optional): Strategy name for round-trip BP estimation
            (#100 / Option A). Falls through to conservative default if None.
        safety_factor (float): Multiplier on estimated_close_bp for round-trip
            check. Default per DEFAULT_ROUND_TRIP_SAFETY_FACTOR.

    Returns:
        dict: {
          "contracts": int,
          "reason": str,
          "capital_required": float,
          "max_dollar_risk": float,
          "estimated_close_bp": float,
          "round_trip_required": float,
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
    #    Tolerance: allow 1 contract if budget covers >= 95% of the risk.
    #    Without this, a $1,873 budget vs $1,925 risk = 0 contracts (2.7% shortfall).
    SINGLE_CONTRACT_TOLERANCE = 0.95
    if max_loss_per_contract <= 0:
        contracts_by_risk = 0
    else:
        ratio = max_dollar_risk / max_loss_per_contract
        if ratio >= SINGLE_CONTRACT_TOLERANCE and ratio < 1.0:
            contracts_by_risk = 1  # Close enough for a single contract
        else:
            contracts_by_risk = math.floor(ratio)

    # 4. Calculate Contracts by Collateral (Buying Power)
    if collateral_required_per_contract <= 0:
        # Treat as no collateral constraint -> infinite (limited by risk only)
        contracts_by_collateral = float('inf')
    else:
        contracts_by_collateral = math.floor(account_buying_power / collateral_required_per_contract)

    # 4b. Calculate Contracts by Round-Trip BP (#100 / Option A).
    # Verifies account_buying_power covers BOTH entry collateral AND
    # estimated close BP. Without this, sizing accepts trades the account
    # can't safely exit (2026-05-01 BAC ghost position incident).
    estimated_close_bp = estimate_close_bp(
        strategy=strategy,
        max_loss_per_contract=max_loss_per_contract,
    )
    round_trip_required_per_contract = (
        collateral_required_per_contract + estimated_close_bp * safety_factor
    )
    if round_trip_required_per_contract <= 0:
        contracts_by_round_trip = float('inf')
    else:
        contracts_by_round_trip = math.floor(
            account_buying_power / round_trip_required_per_contract
        )

    # 5. Final Contracts
    # min(risk_contracts, collateral_contracts, round_trip_contracts, max_contracts)
    contracts = min(
        contracts_by_risk,
        contracts_by_collateral,
        contracts_by_round_trip,
        max_contracts,
    )
    contracts = int(max(0, contracts))

    # 6. Computed Totals
    capital_required = contracts * collateral_required_per_contract
    max_loss_total = contracts * max_loss_per_contract
    round_trip_required_total = contracts * round_trip_required_per_contract

    # 7. Refine Reason
    reason = reason_prefix
    if contracts == 0:
        # Order of evaluation: round-trip explanation is more specific than
        # plain collateral, so check it first.
        if (
            estimated_close_bp > 0
            and account_buying_power < round_trip_required_per_contract
        ):
            reason = (
                f"round_trip_bp_insufficient: BP=${account_buying_power:.2f} < "
                f"entry${collateral_required_per_contract:.2f} + "
                f"close${estimated_close_bp:.2f}×{safety_factor}"
            )
        elif max_loss_per_contract > 0 and max_dollar_risk < max_loss_per_contract:
            reason = f"Risk budget (${max_dollar_risk:.2f}) < 1 contract risk (${max_loss_per_contract:.2f})"
        elif collateral_required_per_contract > 0 and account_buying_power < collateral_required_per_contract:
             reason = f"Insuff. BP (${account_buying_power:.2f}) for collateral (${collateral_required_per_contract:.2f})"
        elif max_loss_per_contract <= 0:
            reason = "Invalid max_loss_per_contract"
    elif contracts == max_contracts:
        reason += " (capped by max_contracts)"
    elif contracts == contracts_by_round_trip and contracts < contracts_by_collateral:
        reason += " (capped by round-trip BP)"
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
        "risk_budget_dollars": risk_budget_dollars,
        # #100 / Option A: per-contract round-trip details persisted for
        # post-hoc calibration analysis (Section 5 revision plan).
        "estimated_close_bp": estimated_close_bp,
        "round_trip_required": round_trip_required_per_contract,
        "round_trip_required_total": round_trip_required_total,
    }
