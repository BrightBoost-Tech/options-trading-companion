from supabase import Client
from typing import List, Dict, Any, Optional

def _risk_usage_usd(pos: Dict[str, Any], underlying_price: float | None = None) -> float:
    """
    Returns risk usage in USD for this position.
    Prefer defined-risk:
        - if pos has max_loss_per_contract or collateral_required_per_contract: use it * qty
    Else fallback:
        - long option: abs(cost_basis_share)*100*qty
        - short put: strike*100*qty
        - short call: underlying_price*100*qty (approx) if provided else 0
    """
    qty = abs(float(pos.get("quantity") or pos.get("qty") or 0.0))
    if qty <= 0: return 0.0

    max_loss = pos.get("max_loss_per_contract") or pos.get("max_loss")
    collateral = pos.get("collateral_required_per_contract") or pos.get("collateral_per_contract")

    risk_per_contract = None
    if max_loss is not None:
        try:
             if float(max_loss) > 0:
                 risk_per_contract = float(max_loss)
        except (ValueError, TypeError):
             pass

    if risk_per_contract is None and collateral is not None:
        try:
            if float(collateral) > 0:
                risk_per_contract = float(collateral)
        except (ValueError, TypeError):
             pass

    if risk_per_contract is not None:
        return risk_per_contract * qty

    # fallback premium usage:
    cost_basis = float(pos.get("cost_basis") or 0.0)
    instr = str(pos.get("instrument_type") or pos.get("type") or pos.get("asset_type") or "").lower()

    # Check if option
    symbol = str(pos.get("symbol", ""))
    is_option = "option" in instr or symbol.startswith("O:") or len(symbol) > 6

    if is_option:
        # User specified: "long option: abs(cost_basis_share)*100*qty"
        # Since we don't have explicit side in all pos dicts, we might rely on cost_basis sign if pos is from plaid?
        # But Plaid usually has positive cost basis.
        # If we just follow the user prompt exactly:
        return abs(cost_basis) * 100.0 * qty

    # fallback for naked short approximations if present (and not caught by above check):
    strike = pos.get("strike")
    opt_type = str(pos.get("option_type") or pos.get("right") or "").lower()
    if strike and ("put" in opt_type or opt_type == "p"):
        try:
            return float(strike) * 100.0 * qty
        except (ValueError, TypeError):
            pass

    if underlying_price is not None:
         return float(underlying_price) * 100.0 * qty

    return 0.0

class RiskBudgetEngine:
    """
    Computes available risk budget based on market regime and portfolio state.
    """
    def __init__(self, supabase: Client):
        self.supabase = supabase

    def compute(self, user_id: str, deployable_capital: float, regime: str, positions: List[Dict[str, Any]]) -> Dict[str, Any]:
        # Estimate Total Equity
        positions_value = 0.0
        current_risk_usage = 0.0

        for p in positions:
            qty = float(p.get("quantity", 0) or 0)
            curr = float(p.get("current_price", 0) or 0)

            # Value
            val = curr * qty

            # Check if option
            symbol = str(p.get("symbol", ""))
            is_option = p.get("asset_type") == "OPTION" or symbol.startswith("O:") or len(symbol) > 6

            if is_option:
                val *= 100.0
                # Risk Usage: Use helper
                # Note: we pass underlying_price=None as we don't have it easily here for short calls
                # For short calls, fallback will be 0 unless we fetch underlying price.
                current_risk_usage += _risk_usage_usd(p, underlying_price=None)
            else:
                # Stocks
                val *= 1.0

            positions_value += val

        total_equity = deployable_capital + positions_value
        if total_equity <= 0: total_equity = 1.0 # Safety

        # Define Caps (Allocated % of Equity to Options)
        caps = {
            "suppressed": 0.50,
            "normal": 0.40,
            "elevated": 0.25,
            "high_vol": 0.15,
            "shock": 0.05
        }

        # Map regime
        r_key = "normal"
        regime_lower = str(regime).lower()
        if "shock" in regime_lower or "panic" in regime_lower: r_key = "shock"
        elif "elevated" in regime_lower or "high_vol" in regime_lower: r_key = "elevated"
        elif "suppressed" in regime_lower: r_key = "suppressed"

        allocation_cap_pct = caps.get(r_key, 0.40)
        max_risk_allocation = total_equity * allocation_cap_pct

        remaining = max_risk_allocation - current_risk_usage

        return {
            "remaining": max(0.0, remaining),
            "current_usage": current_risk_usage,
            "max_allocation": max_risk_allocation,
            "regime": r_key,
            "cap_pct": allocation_cap_pct,
            "total_equity": total_equity
        }
