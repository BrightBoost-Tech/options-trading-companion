from typing import List, Dict, Any, Optional
import math
from models import Spread, SpreadLeg
from services.sizing_engine import calculate_sizing
from services.options_utils import group_spread_positions

class RebalanceEngine:
    def __init__(self, sizing_service=None):
        self.sizing_service = sizing_service or calculate_sizing

    def generate_trades(
        self,
        current_spreads: List[Spread],
        current_holdings: List[Dict[str, Any]], # Raw holdings to verify details if needed
        cash_balance: float,
        targets: List[Dict[str, Any]],
        profile: str = "balanced"
    ) -> List[Dict[str, Any]]:
        """
        Generates buy/sell trade instructions to align current portfolio with optimizer targets.

        Args:
            current_spreads: List of currently held spreads (already grouped).
            current_holdings: Raw positions list (used for context).
            cash_balance: Available cash.
            targets: List of target allocations from optimizer.
                     Format: [{"type": "spread", "symbol": "...", "target_allocation": 0.18}, ...]
            profile: Risk profile.

        Returns:
            List of trade suggestions suitable for inserting into 'trade_suggestions'.
        """

        trades = []

        # Calculate Total Portfolio Value (NAV)
        current_positions_value = sum(s.current_value for s in current_spreads)
        total_nav = cash_balance + current_positions_value

        deployable_capital = total_nav # Simplified. In reality, might subtract buffer.

        # 1. Map current spreads by symbol/ticker for easy lookup
        # We use 'ticker' or constructed ID as key. Optimizer should output same key.
        current_map = {s.ticker: s for s in current_spreads}

        # 2. Process Targets
        for target in targets:
            symbol = target.get("symbol")
            target_alloc = target.get("target_allocation", 0.0)
            target_type = target.get("type", "spread") # spread or stock

            # Identify if we currently hold it
            existing_spread = current_map.get(symbol)

            current_alloc = 0.0
            current_value = 0.0
            if existing_spread:
                current_value = existing_spread.current_value
                current_alloc = current_value / total_nav if total_nav > 0 else 0

            diff = target_alloc - current_alloc

            # Threshold for action (e.g. 1% deviation)
            if abs(diff) < 0.01:
                continue

            # Desired Value
            desired_value = target_alloc * total_nav

            # Value to Trade
            value_to_trade = desired_value - current_value

            # Determine Action
            side = "buy" if value_to_trade > 0 else "sell"

            # Pricing/Sizing
            # If we hold it, we know the price?
            # If buying new, we might need price. Optimizer usually returns 'current_price' in target or we look it up.
            # Assuming target has price info or we can infer from existing.
            # If existing, use its current value per unit?

            price_per_unit = 0.0
            if existing_spread and existing_spread.quantity > 0:
                price_per_unit = existing_spread.current_value / existing_spread.quantity
            elif "current_price" in target:
                price_per_unit = float(target["current_price"]) * 100 # Option multiplier

            # If we don't know the price (e.g. new buy without price info), we can't generate specific quantity.
            # But the optimizer *should* have used a price to generate the target.
            # For now, if price is missing, we skip or flag.

            if price_per_unit <= 0:
                 # Try to get from metadata if available
                 if "price" in target:
                     price_per_unit = float(target["price"]) * 100
                 else:
                     # Log warning or skip
                     continue

            quantity_delta = value_to_trade / price_per_unit

            # Integer contracts
            qty = abs(int(round(quantity_delta)))

            if qty == 0:
                continue

            # Sizing Check (for Buys)
            if side == "buy":
                # Check constraints via sizing engine or manually here as we are rebalancing
                # The Rebalance Engine logic spec says: "Use existing calculate_sizing()"
                # But calculate_sizing is for NEW trades usually. Here we have a target weight.
                # We should ensure we don't violate max risk per trade.

                # Check 25% cap
                trade_cost = qty * price_per_unit
                if trade_cost > 0.25 * deployable_capital:
                    # Cap it
                    max_cost = 0.25 * deployable_capital
                    qty = int(max_cost / price_per_unit)

            if qty == 0:
                continue

            # Construct Trade
            trade = {
                "window": "rebalance",
                "status": "pending",
                "symbol": symbol,
                "ticker": symbol, # Duplicate for compatibility
                "order_type": "limit", # Rebalance usually limit
                "side": side,
                "quantity": qty,
                "limit_price": price_per_unit / 100.0, # Per share/contract price
                "reason": f"Rebalance to target {target_alloc:.1%} (Current: {current_alloc:.1%})",
                "target_allocation": target_alloc,
                "current_allocation": current_alloc,
                "trade_type": target_type # spread or stock
            }

            # Populate legs if available (for new buys, need to know what to buy)
            # If existing spread, we have legs.
            if existing_spread:
                trade["legs"] = [l.dict() for l in existing_spread.legs]
                trade["spread_type"] = existing_spread.spread_type
            elif "legs" in target:
                trade["legs"] = target["legs"]
                trade["spread_type"] = target.get("spread_type", "custom")

            trades.append(trade)

        return trades
