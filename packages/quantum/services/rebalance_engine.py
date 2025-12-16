from typing import List, Dict, Any, Optional
import datetime
import math
# from .trade_builder import SafetySelectionLayer # Removed because it does not exist in trade_builder.py
from ..models import SpreadPosition
# Removed WorkflowOrchestrator import to avoid circular dependency
# from .workflow_orchestrator import WorkflowOrchestrator

# Using services to fetch context is safer than direct imports
from ..analytics.conviction_service import ConvictionService
from ..analytics.iv_regime_service import IVRegimeService

class RiskBudgetEngine:
    """
    Computes risk utilization against defined budgets for strategies, underlyings, and global risk (VaR).
    """
    def __init__(self, default_strategy_cap=0.30, default_underlying_cap=0.20, max_var_pct=0.25, default_vega_cap_pct=0.01, default_delta_cap=2000.0):
        self.default_strategy_cap = default_strategy_cap
        self.default_underlying_cap = default_underlying_cap
        self.max_var_pct = max_var_pct
        self.default_vega_cap_pct = default_vega_cap_pct
        self.default_delta_cap = default_delta_cap

    def compute(self, current_positions: List[SpreadPosition], total_equity: float, risk_profile: str = "balanced") -> Dict[str, Any]:
        """
        Calculates current usage and remaining budgets.

        Returns:
            Dict containing:
            - usage: {strategy: val, underlying: val, var: val, greeks: {underlying: {delta: val, vega: val}}}
            - remaining: {strategy: val, underlying: val, var: val}
            - limits: {strategy: val, underlying: val, var: val}
        """
        usage = {
            "strategy": {},
            "underlying": {},
            "var": 0.0,
            "greeks": {} # underlying -> {delta: x, vega: y}
        }

        # Calculate usage
        for pos in current_positions:
            val = pos.current_value
            # Strategy Usage
            stype = pos.spread_type or "unknown"
            usage["strategy"][stype] = usage["strategy"].get(stype, 0.0) + val

            # Underlying Usage
            und = pos.underlying or "unknown"
            usage["underlying"][und] = usage["underlying"].get(und, 0.0) + val

            # VaR Usage (Approximated by net_cost/max loss for debit, or margin for credit)
            # Using net_cost if positive (debit), else approx margin.
            # Simplified: Use current_value as a proxy for exposure if net_cost not reliable
            risk_amt = max(pos.net_cost, pos.current_value) if pos.net_cost > 0 else (pos.current_value * 1.5) # Rough heuristic
            usage["var"] += risk_amt

            # Greeks Usage
            if und not in usage["greeks"]:
                usage["greeks"][und] = {"delta": 0.0, "vega": 0.0}
            usage["greeks"][und]["delta"] += abs(pos.delta)
            usage["greeks"][und]["vega"] += abs(pos.vega)

        # Calculate Limits
        # Adjust caps based on risk_profile if needed
        strat_cap_pct = self.default_strategy_cap
        und_cap_pct = self.default_underlying_cap
        var_cap_pct = self.max_var_pct
        vega_cap_pct = self.default_vega_cap_pct
        delta_cap = self.default_delta_cap

        if risk_profile == "aggressive":
            strat_cap_pct *= 1.5
            und_cap_pct *= 1.5
            var_cap_pct = 0.35 # Higher max risk
            vega_cap_pct *= 1.5
            delta_cap *= 1.5
        elif risk_profile == "conservative":
            strat_cap_pct *= 0.7
            und_cap_pct *= 0.7
            var_cap_pct = 0.15
            vega_cap_pct *= 0.7
            delta_cap *= 0.7

        limits = {
            "strategy": {k: total_equity * strat_cap_pct for k in usage["strategy"].keys()}, # limits for existing keys
            "underlying": {k: total_equity * und_cap_pct for k in usage["underlying"].keys()},
            "var": total_equity * var_cap_pct,
            "greeks": {
                "delta": delta_cap,
                "vega": total_equity * vega_cap_pct
            },
            "defaults": {
                "strategy": total_equity * strat_cap_pct,
                "underlying": total_equity * und_cap_pct
            }
        }
        # Include greeks defaults for consistency
        limits["defaults"]["greeks"] = limits["greeks"]

        # Calculate Remaining
        remaining = {
            "strategy": {},
            "underlying": {},
            "var": limits["var"] - usage["var"],
            "greeks": {}
        }

        for und, g_usage in usage["greeks"].items():
            rem_delta = limits["greeks"]["delta"] - g_usage["delta"]
            rem_vega = limits["greeks"]["vega"] - g_usage["vega"]
            remaining["greeks"][und] = {"delta": rem_delta, "vega": rem_vega}

        for k, v in usage["strategy"].items():
            limit = limits["strategy"].get(k, limits["defaults"]["strategy"])
            remaining["strategy"][k] = limit - v

        for k, v in usage["underlying"].items():
            limit = limits["underlying"].get(k, limits["defaults"]["underlying"])
            remaining["underlying"][k] = limit - v

        return {
            "usage": usage,
            "limits": limits,
            "remaining": remaining
        }

class RebalanceEngine:
    """
    Compares current holdings (SpreadPosition objects) to optimizer targets,
    generating buy/sell suggestions to bridge the gap.
    """

    def __init__(self, conviction_service: ConvictionService = None, iv_regime_service: IVRegimeService = None):
        self.conviction_service = conviction_service
        self.iv_regime_service = iv_regime_service

    def generate_trades(
        self,
        current_holdings: List[Any], # Changed from List[SpreadPosition] to Any to support dicts as well
        target_weights: Dict[str, float],
        total_equity: float,
        deployable_capital: float,
        pricing_data: Dict[str, float],
        market_context: Dict[str, Any] = None,  # Contains 'regime', 'vix', etc.
        risk_summary: Dict[str, Any] = None     # Contains budget info
    ) -> List[Dict[str, Any]]:
        """
        Generates buy/sell suggestions based on weight differences, enforcing risk budgets.

        Args:
            current_holdings: List of current SpreadPositions (objects or dicts).
            target_weights: {ticker: target_pct} from optimizer.
            total_equity: Current Net Liquidity.
            deployable_capital: Cash available for new trades.
            pricing_data: {ticker: current_price} for valuation.
            market_context: Optional dictionary with market regime info.
            risk_summary: output from RiskBudgetEngine.compute().

        Returns:
            List of trade dictionaries compatible with SuggestionCard.
        """
        trades = []

        # 1. Normalize current holdings to dicts for easier processing
        normalized_holdings = []
        for pos in current_holdings:
            if isinstance(pos, dict):
                normalized_holdings.append(pos)
            elif hasattr(pos, 'model_dump'):
                normalized_holdings.append(pos.model_dump())
            elif hasattr(pos, 'dict'):
                normalized_holdings.append(pos.dict())
            else:
                 # Fallback for generic object
                 try:
                     normalized_holdings.append(vars(pos))
                 except:
                     pass

        # 2. Map normalized holdings by symbol/ticker
        holding_map = {} # symbol -> dict

        for pos in normalized_holdings:
            # Try to find symbol in various fields (robustness)
            symbol = pos.get('symbol') or pos.get('ticker') or pos.get('underlying')
            if symbol:
                holding_map[symbol] = pos

        # 3. Identify all relevant symbols (targets + holdings)
        # Using sorted list to ensure deterministic order during processing
        all_symbols = sorted(list(set(target_weights.keys()).union(holding_map.keys())))

        # 4. Canonical Trade Loop
        for symbol in all_symbols:
            # Determine current value
            pos = holding_map.get(symbol)
            if pos:
                current_val = float(pos.get("current_value") or 0.0)
            else:
                current_val = 0.0

            # Determine target value
            target_w = float(target_weights.get(symbol, 0.0) or 0.0)
            target_val = target_w * float(total_equity or 0.0)

            diff_val = target_val - current_val

            # Determine price_unit (MUST be > 0)
            price_unit = 0.0
            if pricing_data and symbol in pricing_data:
                price_data = pricing_data[symbol]
                if isinstance(price_data, dict):
                    price_unit = float(price_data.get("price") or 0.0)
                else:
                    # Handle case where pricing_data values might be floats directly (unlikely but safe)
                    try:
                        price_unit = float(price_data)
                    except:
                        price_unit = 0.0

            # Fallback: estimate from position if price not found in pricing_data
            if price_unit <= 0.0 and pos:
                qty = abs(float(pos.get("quantity") or 0.0))
                if qty > 0:
                    price_unit = abs(current_val) / qty

            if price_unit <= 0.0:
                continue

            # Calculate quantity delta
            qty_delta = int(math.floor(abs(diff_val) / price_unit))

            if qty_delta == 0:
                continue

            side = "buy" if diff_val > 0 else "sell"

            trade = {
                "symbol": symbol,
                "action": side,
                "quantity": qty_delta,
                "price_unit": price_unit,
                "value_delta": (qty_delta * price_unit) * (1 if side == "buy" else -1),
                "reason": "rebalance_target",
            }

            trades.append(trade)

        # 5. Sort by abs(value_delta) descending
        trades.sort(key=lambda t: abs(float(t.get("value_delta") or 0.0)), reverse=True)

        return trades
