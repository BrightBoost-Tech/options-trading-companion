from pydantic import BaseModel
from typing import Optional, Dict, Any, Literal
from datetime import datetime
import math
import random

from packages.quantum.strategy_profiles import CostModelConfig
from packages.quantum.models import TradeTicket

class QuoteSnapshot(BaseModel):
    bid_price: float
    ask_price: float
    mid_price: float
    spread_width: float
    timestamp: datetime
    size_bid: Optional[int] = None
    size_ask: Optional[int] = None

class TransactionCostModel:
    VERSION = "1.0.0"

    @staticmethod
    def estimate(
        ticket: TradeTicket,
        quote: Optional[Dict[str, Any]],
        config: CostModelConfig = CostModelConfig()
    ) -> Dict[str, Any]:
        """
        Estimates transaction costs, slippage, and fill probability before order placement.
        """

        # 1. Parse Quote
        missing_quote = False
        used_fallback = False

        if not quote or quote.get("status") == "error":
            # Fallback logic if quote missing
            missing_quote = True
            used_fallback = True
            # Assume ticket limit or simplistic model
            price = ticket.limit_price or 0.0
            bid = price * 0.99
            ask = price * 1.01
            mid = price
            spread = ask - bid
        else:
            bid = quote.get("bid_price", 0.0)
            ask = quote.get("ask_price", 0.0)
            # Handle malformed quotes (e.g. 0 bid)
            if bid <= 0 or ask <= 0:
                 if ticket.limit_price:
                     bid = ticket.limit_price * 0.99
                     ask = ticket.limit_price * 1.01
                 else:
                     bid = 0.0
                     ask = 0.0 # Will result in 0 fill prob likely

            mid = (bid + ask) / 2.0
            spread = max(0.0, ask - bid)

        qty = abs(ticket.quantity)

        # 2. Fees
        fees_usd = qty * config.commission_per_contract
        fees_usd = max(fees_usd, config.min_fee)

        # 3. Spread Cost (Crossing the spread)
        # If buying, cost is (Ask - Mid) * Qty * 100
        # If selling, cost is (Mid - Bid) * Qty * 100
        # Simplification: Spread Cost is half the spread per unit
        # However, for LIMIT orders, we might not cross spread immediately.
        # But 'spread_cost' usually implies the cost of liquidity.
        expected_spread_cost_usd = (spread / 2.0) * qty * 100.0

        # 4. Slippage (Market Impact / Volatility movement during latency)
        # Bps of notional
        notional = mid * qty * 100.0
        expected_slippage_usd = notional * (config.spread_slippage_bps / 10000.0)

        # 5. Fill Probability
        # Heuristic based on limit price vs bid/ask
        fill_prob = 0.0
        limit = ticket.limit_price

        if ticket.order_type == "market":
            fill_prob = 1.0
            expected_fill_price = ask if ticket.legs[0].action == "buy" else bid # Simplified for single leg direction
        else:
            # Limit order logic
            # If Buying:
            #   Limit >= Ask -> 1.0
            #   Limit >= Mid -> 0.5
            #   Limit <= Bid -> 0.1 (queue priority)
            if not limit:
                # Should not happen for limit order without limit_price, treat as market?
                fill_prob = 0.0
                expected_fill_price = mid
            else:
                if ticket.legs and ticket.legs[0].action == "buy": # BUY
                    if limit >= ask:
                        fill_prob = 0.95
                    elif limit >= mid:
                        fill_prob = 0.50
                    elif limit >= bid:
                        fill_prob = 0.10
                    else:
                        fill_prob = 0.01
                    expected_fill_price = min(limit, ask) # If we fill, we pay at most limit, likely Ask
                else: # SELL
                    if limit <= bid:
                        fill_prob = 0.95
                    elif limit <= mid:
                        fill_prob = 0.50
                    elif limit <= ask:
                        fill_prob = 0.10
                    else:
                        fill_prob = 0.01
                    expected_fill_price = max(limit, bid)


        # Adjust fill prob based on config model
        if config.fill_probability_model == "conservative":
            fill_prob *= 0.8
        elif config.fill_probability_model == "optimistic":
            fill_prob = min(1.0, fill_prob * 1.2)

        return {
            "expected_spread_cost_usd": round(expected_spread_cost_usd, 2),
            "expected_slippage_usd": round(expected_slippage_usd, 2),
            "fill_probability": round(fill_prob, 2),
            "expected_fill_price": round(expected_fill_price, 2),
            "fees_usd": round(fees_usd, 2),
            "tcm_version": TransactionCostModel.VERSION,
            "missing_quote": missing_quote,
            "used_fallback": used_fallback
        }

    @staticmethod
    def simulate_fill(
        order: Dict[str, Any],
        quote: Optional[Dict[str, Any]],
        config: CostModelConfig = CostModelConfig(),
        seed: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Determines the outcome of a working order given a new quote update.
        Returns dict with status, filled_qty, avg_fill_price.
        """
        # Clockwork: Use local random instance if seed provided to avoid polluting global state.
        # Fallback to global random module if seed is None (preserves external seeding).
        rng_gen = random.Random(seed) if seed is not None else random

        # Parse Order
        requested_qty = float(order.get("requested_qty") or order.get("quantity") or 0)
        filled_qty = float(order.get("filled_qty") or 0)
        remaining_qty = requested_qty - filled_qty

        if remaining_qty <= 0:
            return {
                "status": "filled",
                "filled_qty": requested_qty,
                "avg_fill_price": float(order.get("avg_fill_price") or 0.0)
            }

        order_type = order.get("order_type", "limit")
        limit_price = float(order.get("requested_price") or 0.0) if order.get("requested_price") else None
        side = order.get("side", "buy") # buy/sell

        # Parse Quote
        if not quote or quote.get("status") == "error":
             # No fill on missing quote in simulation, unless market?
             # For paper trading robustness, we might assume last price?
             # Let's return no-op
             return {
                 "status": order.get("status", "working"),
                 "filled_qty": filled_qty,
                 "avg_fill_price": float(order.get("avg_fill_price") or 0.0)
             }

        bid = quote.get("bid_price", 0.0)
        ask = quote.get("ask_price", 0.0)

        if bid <= 0 or ask <= 0:
             return {
                 "status": order.get("status", "working"),
                 "filled_qty": filled_qty,
                 "avg_fill_price": float(order.get("avg_fill_price") or 0.0)
             }

        # Logic
        should_fill = False
        fill_price = 0.0

        if order_type == "market":
            should_fill = True
            fill_price = ask if side == "buy" else bid
            # Add slippage
            impact = fill_price * (config.spread_slippage_bps / 10000.0)
            if side == "buy":
                fill_price += impact
            else:
                fill_price -= impact
        else:
            # Limit
            if side == "buy":
                # Buy limit fills if ask <= limit
                if ask <= limit_price:
                    should_fill = True
                    fill_price = ask # Get the better price (market)
                elif bid <= limit_price:
                     # Maybe partial fill or lucky fill?
                     # Let's use probabilistic fill if inside spread
                     rand_val = rng_gen.random()
                     # closer to ask = higher prob
                     spread = ask - bid
                     if spread > 0:
                        dist_from_bid = limit_price - bid
                        prob = (dist_from_bid / spread) * 0.5 # max 50% chance inside spread
                        if rand_val < prob:
                            should_fill = True
                            fill_price = limit_price
            else: # sell
                # Sell limit fills if bid >= limit
                if bid >= limit_price:
                    should_fill = True
                    fill_price = bid
                elif ask >= limit_price:
                    rand_val = rng_gen.random()
                    spread = ask - bid
                    if spread > 0:
                        dist_from_ask = ask - limit_price
                        prob = (dist_from_ask / spread) * 0.5
                        if rand_val < prob:
                            should_fill = True
                            fill_price = limit_price

        if should_fill:
            # Fill whole remaining qty for now (simplification, unless we want partials)
            # To support partials, we could randomize qty fraction.

            # Let's say 100% fill if conditions met, to keep paper trading fluid.
            # But "Partial fills possible" was a criteria.
            # Let's rarely do partials for large orders.

            this_fill_qty = remaining_qty
            if remaining_qty > 10 and rng_gen.random() < 0.1:
                this_fill_qty = math.floor(remaining_qty / 2)

            # Update avg price
            current_notional = filled_qty * float(order.get("avg_fill_price") or 0.0)
            new_fill_notional = this_fill_qty * fill_price
            new_total_qty = filled_qty + this_fill_qty
            new_avg_price = (current_notional + new_fill_notional) / new_total_qty

            status = "filled" if new_total_qty >= requested_qty else "partial"

            return {
                "status": status,
                "filled_qty": new_total_qty,
                "avg_fill_price": round(new_avg_price, 4),
                "last_fill_price": round(fill_price, 4),
                "last_fill_qty": this_fill_qty
            }

        return {
            "status": order.get("status", "working"),
            "filled_qty": filled_qty,
            "avg_fill_price": float(order.get("avg_fill_price") or 0.0)
        }
