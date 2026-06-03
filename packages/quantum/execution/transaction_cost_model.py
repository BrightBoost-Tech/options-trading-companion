from pydantic import BaseModel
from typing import Optional, Dict, Any, Literal
from datetime import datetime, timezone
import hashlib
import math
import random

from packages.quantum.strategy_profiles import CostModelConfig
from packages.quantum.models import TradeTicket


def _compute_deterministic_fill_draw(order_id: str, date_bucket: Optional[str] = None) -> float:
    """
    Compute a deterministic uniform random value [0, 1) based on order_id and date bucket.

    This ensures reproducible fill decisions per day:
    - Same order_id + same day => same draw
    - Different days => different draw (gives orders multiple chances)

    Args:
        order_id: Unique order identifier
        date_bucket: UTC date string (YYYY-MM-DD). If None, uses current UTC date.

    Returns:
        Float in [0, 1) derived from SHA256 hash
    """
    if date_bucket is None:
        date_bucket = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    seed_str = f"{order_id}|{date_bucket}"
    hash_bytes = hashlib.sha256(seed_str.encode("utf-8")).hexdigest()
    # Use first 8 hex chars (32 bits) for uniform distribution
    u = int(hash_bytes[:8], 16) / 0xFFFFFFFF
    return u

class QuoteSnapshot(BaseModel):
    bid_price: float
    ask_price: float
    mid_price: float
    spread_width: float
    timestamp: datetime
    size_bid: Optional[int] = None
    size_ask: Optional[int] = None

def _count_order_legs(order: Dict[str, Any]) -> int:
    """Number of legs on the order (from order_json). 0 when unknown."""
    legs = (order.get("order_json") or {}).get("legs") or []
    return len(legs)


def _live_marketability_label(
    order: Dict[str, Any],
    bid: Optional[float],
    ask: Optional[float],
    limit_price: Optional[float],
    order_type: str,
) -> Dict[str, Any]:
    """Compute the would-be LIVE marketability of this order at this quote.

    Live mid-limit entries empirically fill instantly or never (live fill
    rate ~12%, all instant; see the 2026-06-04 shadow-fill diagnostic), so
    "would this have filled live?" reduces to "was the limit marketable on
    arrival?". This is a pure LABEL for calibration/learning consumers to
    filter on — it never gates the simulated fill (volume preserved).

    Honesty rules (don't fabricate):
    - quote missing/invalid → None ("quote_missing") — UNKNOWN, not False.
    - multi-leg combos → None ("multi_leg_combo_nbbo_unavailable"): the
      quote passed in is leg-1-only (see _resolve_quote_symbol), and a
      combo limit cannot be judged against a single leg's NBBO.
    """
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return {"would_be_live_marketable": None,
                "marketability_basis": "quote_missing"}
    if _count_order_legs(order) > 1:
        return {"would_be_live_marketable": None,
                "marketability_basis": "multi_leg_combo_nbbo_unavailable"}
    if order_type == "market":
        return {"would_be_live_marketable": True,
                "marketability_basis": "market_order"}
    if not limit_price:
        return {"would_be_live_marketable": None,
                "marketability_basis": "no_limit_price"}
    side = order.get("side", "buy")
    if side == "buy":
        marketable = limit_price >= ask
    else:
        marketable = limit_price <= bid
    return {"would_be_live_marketable": bool(marketable),
            "marketability_basis": "single_leg_nbbo"}


class TransactionCostModel:
    # 1.1.0: realistic shadow fills — the missing-quote fallback applies the
    # stored cross cost (fills adverse of mid) and every simulated fill
    # carries fill_model + would_be_live_marketable. Rows without
    # `fill_model` in tcm predate this model (mid-filled; segregable).
    VERSION = "1.1.0"
    FILL_MODEL = "natural_v1"

    # Degradation bound when expected_spread_cost_usd is absent: the scanner's
    # 10% combo-width/cost gate caps combo width at 10% of entry cost, so the
    # cross-to-natural (half-width) is bounded at 5% of the fill price. Never
    # silently fill at exact mid again.
    HALF_WIDTH_BOUND_PCT = 0.05

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
            # Handle malformed quotes (e.g. 0 bid, 0 ask)
            if bid <= 0 or ask <= 0:
                 missing_quote = True
                 used_fallback = True
                 if ticket.limit_price:
                     bid = ticket.limit_price * 0.99
                     ask = ticket.limit_price * 1.01
                 else:
                     bid = 0.0
                     ask = 0.0

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
        # IMPORTANT: For missing/invalid quotes, use deterministic fill logic based on
        # TCM precomputed values (fill_probability, expected_fill_price) stored on the order.
        # This unblocks paper trading when quotes are unavailable while maintaining
        # reproducible behavior per order per day.

        def _handle_missing_quote_fallback(reason: str) -> Dict[str, Any]:
            """
            Handle missing/invalid quote using deterministic fill draw.

            Uses TCM precomputed values from order.tcm:
            - fill_probability: probability threshold for fill
            - expected_fill_price: price to use if filled

            Returns status="working" or "filled", NEVER "staged".
            """
            order_id = order.get("id", "unknown")

            # Get TCM precomputed values from order
            tcm_data = order.get("tcm") or {}
            fill_probability = float(tcm_data.get("fill_probability") or 0.5)
            expected_fill_price = float(tcm_data.get("expected_fill_price") or 0.0)

            # Fallback: use requested_price or a safe default
            if expected_fill_price <= 0:
                expected_fill_price = float(order.get("requested_price") or 0.0)
            if expected_fill_price <= 0:
                # Last resort fallback
                expected_fill_price = 1.0

            # Internal paper trading: always fill (probabilistic rejection is
            # meaningless with no real counterparty) — but NOT at exact mid.
            # Pre-1.1.0 this filled at expected_fill_price (= the combo mid),
            # which understated entry cost by the cross and contaminated
            # calibration/learning inputs (learning_feedback_loops trained on
            # fills live can't achieve). Apply the cross cost the TCM already
            # estimated at staging: fills are ADVERSE of mid — a buy pays
            # more, a sell receives less.
            cross_cost_usd = float(tcm_data.get("expected_spread_cost_usd") or 0.0)
            if cross_cost_usd > 0 and requested_qty > 0:
                cross_per_share = cross_cost_usd / (requested_qty * 100.0)
                cross_source = "tcm_expected_spread_cost"
            else:
                # Degradation: half-combo-width estimate bounded by the 10%
                # spread gate (≤5% of price). Never exact mid.
                cross_per_share = expected_fill_price * TransactionCostModel.HALF_WIDTH_BOUND_PCT
                cross_source = "half_width_bound_estimate"

            side = order.get("side", "buy")
            if side == "buy":
                adjusted_price = expected_fill_price + cross_per_share
            else:
                adjusted_price = max(0.01, expected_fill_price - cross_per_share)

            # Marketability label: quote is missing here by definition →
            # UNKNOWN (None), never fabricated.
            new_total_qty = requested_qty
            new_avg_price = adjusted_price

            return {
                "status": "filled",
                "filled_qty": new_total_qty,
                "avg_fill_price": round(new_avg_price, 4),
                "last_fill_price": round(adjusted_price, 4),
                "last_fill_qty": remaining_qty,
                "reason": "missing_quote_fallback",
                "fallback_source": reason,
                "fill_probability_used": fill_probability,
                "fill_model": TransactionCostModel.FILL_MODEL,
                "mid_price_basis": round(expected_fill_price, 4),
                "simulated_cross_per_share": round(cross_per_share, 4),
                "simulated_cross_source": cross_source,
                "would_be_live_marketable": None,
                "marketability_basis": "quote_missing",
            }

        if not quote or quote.get("status") == "error":
            return _handle_missing_quote_fallback("missing_quote")

        bid = quote.get("bid_price") or quote.get("bid") or 0.0
        ask = quote.get("ask_price") or quote.get("ask") or 0.0

        # Also check 'price' field as fallback for valid quote detection
        price = quote.get("price") or quote.get("last") or 0.0

        if bid <= 0 or ask <= 0:
            # Invalid quote - use fallback logic
            return _handle_missing_quote_fallback("invalid_quote")

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

            # Quote-path fills already price off the real NBBO (ask/bid or
            # probabilistic-at-limit) — no price adjustment. Attach the
            # marketability label + fill model only (pure label, never gates).
            label = _live_marketability_label(order, bid, ask, limit_price, order_type)
            return {
                "status": status,
                "filled_qty": new_total_qty,
                "avg_fill_price": round(new_avg_price, 4),
                "last_fill_price": round(fill_price, 4),
                "last_fill_qty": this_fill_qty,
                "fill_model": TransactionCostModel.FILL_MODEL,
                **label,
            }

        # No fill this tick, but order is actively working
        # Always return "working" status, never echo back the order's current status
        # (which could be "staged" and would prevent transition)
        return {
            "status": "working",
            "filled_qty": filled_qty,
            "avg_fill_price": float(order.get("avg_fill_price") or 0.0),
            "last_fill_qty": 0
        }
