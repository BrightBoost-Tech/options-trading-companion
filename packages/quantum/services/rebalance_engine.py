from typing import List, Dict, Any, Optional, Union
import datetime
import math
from ..models import SpreadPosition

# Using services to fetch context is safer than direct imports
from ..analytics.conviction_service import ConvictionService
from ..analytics.iv_regime_service import IVRegimeService
from .risk_budget_engine import RiskBudgetReport

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
        risk_summary: Union[Dict[str, Any], RiskBudgetReport] = None     # Contains budget info
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

            # 4b. Enforce Risk Budgets (Unification)
            # If buying, verify we have budget
            if side == "buy" and risk_summary:
                cost_est = trade["value_delta"]

                # Check Global Allocation
                if hasattr(risk_summary, 'global_allocation'):
                    # Pydantic Report
                    remaining = risk_summary.global_allocation.remaining
                else:
                    # Legacy or dict
                    remaining = risk_summary.get('global_allocation', {}).get('remaining', 999999.0)

                if cost_est > remaining:
                    # Reduce quantity to fit budget
                    can_afford = max(0.0, remaining)
                    new_qty = int(math.floor(can_afford / price_unit))
                    if new_qty < qty_delta:
                        if new_qty == 0:
                            continue # Skip trade entirely

                        # Adjust trade
                        qty_delta = new_qty
                        trade["quantity"] = qty_delta
                        trade["value_delta"] = qty_delta * price_unit
                        trade["reason"] += " (budget_clamped)"

            trades.append(trade)

        # 5. Sort by abs(value_delta) descending
        trades.sort(key=lambda t: abs(float(t.get("value_delta") or 0.0)), reverse=True)

        return trades
