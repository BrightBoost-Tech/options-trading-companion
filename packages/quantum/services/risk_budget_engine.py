from supabase import Client
from typing import List, Dict, Any, Optional
from packages.quantum.services.market_data_truth_layer import MarketDataTruthLayer

def _risk_usage_usd(pos: Dict[str, Any], underlying_price: float | None = None) -> float:
    """
    Returns risk usage in USD for this position.
    Prefer defined-risk:
        - if pos has max_loss_per_contract or collateral_required_per_contract: use it * qty
    Else fallback:
        - long option: abs(cost_basis_share)*100*qty
        - short put: strike*100*qty
        - short call: max(underlying, strike)*100*qty (approx) if provided else strike*100*qty
    """
    qty = abs(float(pos.get("quantity") or pos.get("qty") or 0.0))
    if qty <= 0: return 0.0

    # 1. Prefer defined risk
    max_loss = pos.get("max_loss_per_contract") or pos.get("max_loss")
    collateral = pos.get("collateral_required_per_contract") or pos.get("collateral_per_contract")

    if max_loss is not None:
        try:
             if float(max_loss) > 0:
                 return float(max_loss) * qty
        except (ValueError, TypeError):
             pass

    if collateral is not None:
        try:
            if float(collateral) > 0:
                return float(collateral) * qty
        except (ValueError, TypeError):
             pass

    # 2. Identify option-ness
    instr = str(pos.get("instrument_type") or pos.get("type") or pos.get("asset_type") or "").lower()
    symbol = str(pos.get("symbol", ""))
    strike = pos.get("strike")
    option_type_field = pos.get("option_type") or pos.get("right")

    is_option = ("option" in instr) or symbol.startswith("O:") or (len(symbol) > 6 and any(c.isdigit() for c in symbol)) or (strike is not None) or (option_type_field is not None)

    # 3. Determine side
    side = str(pos.get("side") or pos.get("action") or "").lower()
    # Normalize: treat "sell"/"short" as short exposure, "buy"/"long" as long
    is_short = side in ("sell", "short")
    is_long = side in ("buy", "long") or (not is_short)

    if is_option:
        cost_basis = float(pos.get("cost_basis") or 0.0)
        opt_type = str(option_type_field or "").lower()

        if is_long:
            return abs(cost_basis) * 100.0 * qty

        # SHORT option approximations
        if strike is not None:
            try:
                strike_f = float(strike)
                if "put" in opt_type or opt_type == "p":
                    return strike_f * 100.0 * qty

                if "call" in opt_type or opt_type == "c":
                    # Use underlying if available, else fall back to strike (conservative-ish)
                    und = float(underlying_price) if underlying_price is not None else strike_f
                    return max(und, strike_f) * 100.0 * qty
            except (ValueError, TypeError):
                pass # Fallback to premium

        # fallback if strike missing or conversion failed:
        return abs(cost_basis) * 100.0 * qty

    # Else (non-option):
    return abs(float(pos.get("current_value") or 0.0))

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

        # Pre-fetch underlying prices for short calls missing them
        underlyings_to_fetch = set()

        for p in positions:
            instr = str(p.get("instrument_type") or p.get("type") or p.get("asset_type") or "").lower()
            symbol = str(p.get("symbol", ""))
            strike = p.get("strike")
            option_type_field = p.get("option_type") or p.get("right")

            is_option = ("option" in instr) or symbol.startswith("O:") or (len(symbol) > 6 and any(c.isdigit() for c in symbol)) or (strike is not None) or (option_type_field is not None)

            side = str(p.get("side") or p.get("action") or "").lower()
            is_short = side in ("sell", "short")
            opt_type = str(option_type_field or "").lower()

            # Condition: Short Call, missing underlying_price in pos
            if is_option and is_short and ("call" in opt_type or opt_type == "c") and p.get("underlying_price") is None:
                und = p.get("underlying") or p.get("underlying_symbol")
                if und:
                    underlyings_to_fetch.add(und)

        fetched_prices = {}
        truth_layer_ref = None

        if underlyings_to_fetch:
            try:
                truth_layer = MarketDataTruthLayer()
                truth_layer_ref = truth_layer
                snaps = truth_layer.snapshot_many(list(underlyings_to_fetch)) or {}

                for ticker, data in snaps.items():
                    q = data.get("quote", {})
                    mid = q.get("mid")
                    if mid is None:
                        bid = q.get("bid")
                        ask = q.get("ask")
                        if bid is not None and ask is not None:
                            mid = (bid + ask) / 2.0
                        else:
                            mid = q.get("last")

                    if mid is not None:
                        # Store by normalized key
                        fetched_prices[ticker] = mid
            except Exception as e:
                print(f"RiskBudgetEngine: Failed to fetch underlyings: {e}")

        for p in positions:
            qty = float(p.get("quantity", 0) or 0)
            curr = float(p.get("current_price", 0) or 0)

            # Value
            val = curr * qty

            # Check if option (logic replicated for robust detection)
            instr = str(p.get("instrument_type") or p.get("type") or p.get("asset_type") or "").lower()
            symbol = str(p.get("symbol", ""))
            strike = p.get("strike")
            option_type_field = p.get("option_type") or p.get("right")
            is_option = ("option" in instr) or symbol.startswith("O:") or (len(symbol) > 6 and any(c.isdigit() for c in symbol)) or (strike is not None) or (option_type_field is not None)

            if is_option:
                val *= 100.0

                # Determine underlying price
                u_price = p.get("underlying_price")
                if u_price is None:
                    und = p.get("underlying") or p.get("underlying_symbol")
                    if und and truth_layer_ref:
                        norm = truth_layer_ref.normalize_symbol(und)
                        u_price = fetched_prices.get(norm)

                current_risk_usage += _risk_usage_usd(p, underlying_price=u_price)
            else:
                # Stocks: do not add to option risk usage, but contribute to equity
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
