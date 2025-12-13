from datetime import datetime, timezone
import uuid
from typing import Dict, Any, Optional
from supabase import Client

from packages.quantum.models import TradeTicket
from packages.quantum.services.transaction_cost_model import TransactionCostModel, CostModelConfig
from packages.quantum.observability.telemetry import TradeContext, emit_trade_event

class PaperExecutionService:
    def __init__(self, supabase: Client):
        self.supabase = supabase
        self.tcm = TransactionCostModel(CostModelConfig(spread_slippage_bps=5, fill_probability_model="neutral"))

    def stage_order(self, user_id: str, ticket: TradeTicket, portfolio_id: str, suggestion_id: Optional[str] = None) -> Dict:
        """
        Creates an order in 'staged' status.
        """
        # Resolve Context
        trace_id = None
        model_version = "v3"
        features_hash = "unknown"
        regime = None
        strategy = ticket.strategy_type

        if suggestion_id:
            try:
                s_res = self.supabase.table("trade_suggestions").select("*").eq("id", suggestion_id).single().execute()
                if s_res.data:
                    s_data = s_res.data
                    trace_id = s_data.get("trace_id")
                    model_version = s_data.get("model_version", "v3")
                    features_hash = s_data.get("features_hash", "unknown")
                    regime = s_data.get("regime")
                    strategy = s_data.get("strategy") or strategy
            except Exception:
                pass

        if not trace_id:
            trace_id = str(uuid.uuid4())

        order_payload = {
            "portfolio_id": portfolio_id,
            "status": "staged",
            "order_json": ticket.model_dump(mode="json"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "suggestion_id": suggestion_id,
            "trace_id": trace_id
        }

        res = self.supabase.table("paper_orders").insert(order_payload).execute()
        if not res.data:
            raise Exception("Failed to stage order")

        order = res.data[0]

        # Telemetry
        ctx = TradeContext(
            trace_id=trace_id,
            suggestion_id=suggestion_id,
            model_version=model_version,
            strategy=strategy,
            regime=regime,
            features_hash=features_hash,
            window="paper"
        )
        # Emit order_staged (handled by analytics service if we pass it, or just return ctx)
        return order, ctx

    def process_order(self, order_id: str, user_id: str, analytics_service=None) -> Dict:
        """
         transitions order from staged -> filled (or rejected).
         applies TCM simulation.
         updates portfolio and positions.
        """
        # 1. Fetch Order
        res = self.supabase.table("paper_orders").select("*").eq("id", order_id).single().execute()
        if not res.data:
            raise ValueError("Order not found")
        order = res.data

        if order["status"] != "staged":
            return order # Idempotent-ish

        # 2. TCM Simulation
        ticket_data = order["order_json"]
        price = float(ticket_data.get("limit_price") or ticket_data.get("price") or 0.0) # Market orders need current price injection!
        # If price is 0 (market), we need current price.
        # Ideally stage_order gets current price.
        # Assuming ticket has a price for now or we fetch it?
        # For V3 Paper, let's assume client passes price or we trust ticket price.
        # Real fill simulation should fetch live quote.

        # NOTE: If ticket price is 0/None, we should ideally fetch quote.
        # For now, using ticket price. If 0, fail?
        if price <= 0:
             # Try to fetch from recent suggestion?
             pass

        qty = float(ticket_data.get("quantity", 0))
        side = "buy" # default? Need to parse action.
        # Actions: Buy, Sell, Buy to Open, etc.
        action = ticket_data.get("action", "").lower()
        if "sell" in action: side = "sell"

        sim_result = self.tcm.simulate_fill(price, qty, side)

        # 3. Update Order Status
        update_payload = {
            "status": sim_result.status,
            "filled_at": datetime.now(timezone.utc).isoformat(),
            "fill_price": sim_result.fill_price,
            "filled_quantity": sim_result.filled_quantity,
            "commission": sim_result.commission_paid,
            "slippage": sim_result.slippage_paid
        }

        self.supabase.table("paper_orders").update(update_payload).eq("id", order_id).execute()

        # 4. Update Portfolio & Position (only if filled)
        if sim_result.status == "filled":
            self._update_holdings(order["portfolio_id"], ticket_data, sim_result, side)

        # 5. Telemetry
        if analytics_service:
            # Reconstruct context (expensive? or pass through?)
            # Just minimal event
            pass

        return {**order, **update_payload}

    def _update_holdings(self, portfolio_id: str, ticket: Dict, fill: Any, side: str):
        # Update Cash
        port_res = self.supabase.table("paper_portfolios").select("*").eq("id", portfolio_id).single().execute()
        portfolio = port_res.data

        notional = fill.fill_price * fill.filled_quantity * 100 # Option multiplier
        cost = notional + fill.commission_paid

        new_cash = float(portfolio["cash_balance"])
        if side == "buy":
            new_cash -= cost
        else:
            new_cash += (notional - fill.commission_paid) # Proceeds

        self.supabase.table("paper_portfolios").update({"cash_balance": new_cash}).eq("id", portfolio_id).execute()

        # Update Position
        symbol = ticket.get("symbol")
        strategy = ticket.get("strategy_type", "custom")
        strategy_key = f"{symbol}_{strategy}" # Simplified key

        pos_res = self.supabase.table("paper_positions").select("*").eq("portfolio_id", portfolio_id).eq("strategy_key", strategy_key).execute()

        if pos_res.data:
            pos = pos_res.data[0]
            old_qty = float(pos["quantity"])

            if side == "buy":
                # Avg up
                total_cost = (old_qty * float(pos["avg_entry_price"])) + (fill.filled_quantity * fill.fill_price)
                new_qty = old_qty + fill.filled_quantity
                new_avg = total_cost / new_qty if new_qty > 0 else 0

                self.supabase.table("paper_positions").update({
                    "quantity": new_qty,
                    "avg_entry_price": new_avg
                }).eq("id", pos["id"]).execute()
            else:
                # Reduce qty (Sell)
                new_qty = max(0, old_qty - fill.filled_quantity)
                if new_qty == 0:
                    self.supabase.table("paper_positions").delete().eq("id", pos["id"]).execute()
                else:
                    self.supabase.table("paper_positions").update({"quantity": new_qty}).eq("id", pos["id"]).execute()
        elif side == "buy":
            # New Position
            self.supabase.table("paper_positions").insert({
                "portfolio_id": portfolio_id,
                "strategy_key": strategy_key,
                "symbol": symbol,
                "quantity": fill.filled_quantity,
                "avg_entry_price": fill.fill_price,
                "current_mark": fill.fill_price
            }).execute()
