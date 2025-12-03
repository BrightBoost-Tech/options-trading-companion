from typing import List, Dict, Any, Optional
from supabase import Client
from datetime import datetime, timezone
import math

from models import SpreadPosition, Holding
from services.sizing_engine import calculate_sizing
from analytics.iv_regime_service import IVRegimeService

class RebalanceEngine:
    """
    Generates actionable trade instructions to rebalance a portfolio
    based on optimizer target weights.
    """

    def __init__(self, supabase: Client = None):
        self.supabase = supabase
        self.iv_service = IVRegimeService(supabase) if supabase else None

    def generate_trades(
        self,
        current_spreads: List[SpreadPosition],
        raw_positions: List[Dict], # including stocks
        cash_balance: float,
        target_weights: List[Dict], # [{type: spread|stock, symbol: str, target_weight: float}, ...]
        profile: str = "balanced"
    ) -> List[Dict]:
        """
        Core logic: compare current vs target and emit trades.
        """
        trades = []

        # 1. Map Targets
        # Targets structure: {"type": "spread", "symbol": "...", "target_allocation": 0.15}
        # Note: 'symbol' in target refers to the ticker/id used in optimization.
        # For spreads, optimizer likely used `spread.ticker` or `spread.id`.
        # Assuming `target_weights` key matches `spread.ticker`.

        target_map = {t["symbol"]: t["target_allocation"] for t in target_weights}

        # Calculate Total Portfolio Value for sizing
        # (Spreads value + Stocks value + Cash)
        # Assuming current_spreads and raw_positions might overlap if we processed everything.
        # But `current_spreads` only contains OPTIONS.
        # We need stocks too.

        stocks = [p for p in raw_positions if p.get("symbol", "").upper() not in ["USD", "CUR:USD", "CASH"] and len(p.get("symbol", "")) <= 6] # Simple heuristic

        total_equity = sum(s.current_value for s in current_spreads)
        total_equity += sum(float(s.get("current_value") or (s.get("quantity") * s.get("current_price"))) for s in stocks)
        total_portfolio_value = total_equity + cash_balance

        deployable_capital = cash_balance # Simplified

        # 2. Process Spreads (Existing vs Target)
        # We need to match existing spreads to targets.
        # Targets might be "open new spread" or "adjust existing".
        # If the target symbol matches an existing spread ticker, we adjust.
        # If the target symbol is new (how? optimizer usually picks from UNIVERSE or HOLDINGS).
        # If optimizer suggests a NEW position, it needs to provide details (legs).
        # Assuming for now rebalance mainly adjusts existing holdings weights,
        # unless optimizer is capable of suggesting new tickers (Universe Selection).
        # If optimizer output includes new tickers, we need their metadata (price, legs) which might be missing in `target_weights`.
        # *Constraint*: For this phase, we'll assume we only rebalance EXISTING assets or explicitly provided candidates.
        # But wait, if we only rebalance existing, how do we "open" new trades?
        # The prompt says: "Inputs: Current SpreadPosition list... Latest optimizer targets... Outputs: trade dicts".

        # We will iterate through TARGETS.
        for target in target_weights:
            symbol = target["symbol"]
            target_w = target["target_allocation"]

            # Find matching holding
            existing_spread = next((s for s in current_spreads if s.ticker == symbol), None)
            existing_stock = next((s for s in stocks if s["symbol"] == symbol), None)

            current_val = 0.0
            current_w = 0.0

            if existing_spread:
                current_val = existing_spread.current_value
                item_type = "spread"
                price_unit = abs(existing_spread.current_value / (existing_spread.quantity or 1)) # approx price per unit
                # If short, current_value might be negative?
                # Using absolute value for weight calc usually.
                # But option values are tricky.
                # Let's assume Long value.
            elif existing_stock:
                current_val = float(existing_stock.get("current_value") or 0)
                item_type = "stock"
                price_unit = float(existing_stock.get("current_price") or 0)
            else:
                # NEW POSITION SUGGESTION?
                # If we don't have metadata, we can't trade it.
                # Skip for now unless we have a way to fetch price.
                continue

            if total_portfolio_value > 0:
                current_w = current_val / total_portfolio_value

            diff_w = target_w - current_w

            # Threshold to trade (e.g. 2% deviation)
            if abs(diff_w) < 0.02:
                continue

            # ACTION
            desired_val_change = diff_w * total_portfolio_value

            if desired_val_change > 0:
                side = "buy" # or "increase"
                action = "increase"
            else:
                side = "sell" # or "decrease"
                action = "decrease"

            # Sizing
            # contracts/shares = desired_change / price_unit
            if price_unit <= 0: continue

            qty_delta = abs(desired_val_change) / price_unit
            qty_delta = math.floor(qty_delta)

            if qty_delta == 0: continue

            # Risk Check (for buys)
            reason = "Rebalance to target"
            if side == "buy":
                # Use sizing engine for safety check
                # Note: Sizing engine is for "opening" trades usually.
                # Here we are adding to position.
                # We check if we have enough cash.
                cost = qty_delta * price_unit

                # Max 25% deployable capital per NEW spread (or addition)
                # Requirement: "max 25% deployable capital per new spread"
                max_allocation = deployable_capital * 0.25
                if cost > max_allocation:
                     qty_delta = math.floor(max_allocation / price_unit)
                     reason = "Rebalance (capped by 25% rule)"
                     cost = qty_delta * price_unit # Recalculate

                if cost > deployable_capital:
                    # Cap it further if cash is tight (though 25% rule usually covers it unless capital is tiny)
                    qty_delta = math.floor(deployable_capital / price_unit)
                    reason = "Rebalance (capped by cash)"

                if qty_delta == 0: continue

            # Construct Trade
            trade = {
                "side": action, # open/close/increase/decrease
                "kind": item_type,
                "symbol": symbol,
                "quantity": qty_delta,
                "limit_price": price_unit, # Using current price as limit
                "reason": f"Target: {target_w:.1%}, Current: {current_w:.1%}. {reason}",
                "target_weight": target_w,
                "current_weight": current_w,
                "target_allocation": target_w,
                "current_allocation": current_w,
                "spread_type": existing_spread.spread_type if existing_spread else "stock",
                "legs": existing_spread.legs if existing_spread else [], # Copy legs if spread
                "risk_metadata": {
                    "diff_value": desired_val_change
                }
            }
            trades.append(trade)

        return trades
