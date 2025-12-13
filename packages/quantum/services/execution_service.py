from supabase import Client
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import logging
import statistics
from packages.quantum.services.transaction_cost_model import TransactionCostModel

logger = logging.getLogger(__name__)

class ExecutionService:
    def __init__(self, supabase: Client):
        self.supabase = supabase
        self.logs_table = "suggestion_logs"
        self.executions_table = "trade_executions"
        self.cost_model = TransactionCostModel()

    def register_execution(self,
                           user_id: str,
                           suggestion_id: str,
                           fill_details: Dict[str, Any] = None) -> Dict:
        """
        Explicitly links a suggestion to an execution.
        """
        if not fill_details:
            fill_details = {}

        # 1. Fetch suggestion
        try:
            s_res = self.supabase.table(self.logs_table).select("*").eq("id", suggestion_id).single().execute()
            suggestion = s_res.data
        except Exception:
            suggestion = None

        # 2. Calculate Realized Slippage & Drag
        mid_price = fill_details.get("mid_price_at_submission")
        fill_price = fill_details.get("fill_price", 0.0)

        # Realized Cost = Fill Price + Fees
        # Drag = |Fill - Mid| + Fees (per share)
        fees = fill_details.get("fees", 0.0)
        quantity = int(fill_details.get("quantity", 1))

        realized_execution_cost = 0.0
        slippage = 0.0

        if quantity > 0:
            if mid_price and fill_price > 0:
                slippage = abs(fill_price - mid_price)

            # Drag per unit
            fees_per_unit = fees / quantity
            realized_execution_cost = slippage + fees_per_unit

        # 3. Create TradeExecution
        execution_data = {
            "user_id": user_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": fill_details.get("symbol") or (suggestion.get("symbol") if suggestion else "UNKNOWN"),
            "fill_price": fill_price,
            "quantity": quantity,
            "fees": fees,
            "suggestion_id": suggestion_id
        }

        # Note: We rely on 'fees' or 'details' in schema if available.
        # Since we cannot modify schema, we calculate drag but might not store it explicitly
        # unless we piggyback on 'fees' or a JSON field.
        # Requirement D.1: "Store execution drag per symbol".
        # We assume 'fees' captures explicit costs. Slippage is implicit.

        try:
            ex_res = self.supabase.table(self.executions_table).insert(execution_data).execute()
            execution = ex_res.data[0] if ex_res.data else None
        except Exception as e:
            logger.error(f"Failed to insert execution: {e}")
            return None

        # 4. Update SuggestionLog
        if execution:
            self.supabase.table(self.logs_table).update({
                "was_accepted": True,
                "trade_execution_id": execution["id"]
            }).eq("id", suggestion_id).execute()

        return execution

    def get_execution_drag_stats(self, symbol: str) -> float:
        """
        Returns average execution drag (slippage + fees per share) for a symbol
        based on historical executions.
        """
        # This single-symbol fetch is kept for backward compat,
        # but batched fetch is preferred.
        res = self.get_batch_execution_drag_stats([symbol])
        return res.get(symbol, 0.05)

    def get_batch_execution_drag_stats(self, symbols: List[str], user_id: str = None, lookback_days: int = 30) -> Dict[str, float]:
        """
        Fetches avg execution drag for a list of symbols.
        Returns { symbol: drag_amount }. Default 0.05 if no history.

        Logic:
        1. Query Executions (filtered by symbol, user_id, lookback).
        2. Query Suggestions (by suggestion_id from step 1).
        3. Compute slippage = abs(fill - target).
        4. Compute drag = slippage + fees_per_share.
        5. Aggregate.
        """
        if not symbols:
            return {}

        default_drag = 0.05
        results = {s: default_drag for s in symbols}

        try:
            # 1. Fetch Executions
            # We filter by symbol IN list.
            query = self.supabase.table(self.executions_table)\
                .select("id, symbol, fill_price, fees, quantity, suggestion_id")\
                .in_("symbol", symbols)\
                .gte("timestamp", (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat())

            if user_id:
                query = query.eq("user_id", user_id)

            # Limit to prevent massive fetch, though batch size in scanner is small (5)
            # If symbols list is small, we get all relevant history up to limit.
            ex_res = query.order("timestamp", desc=True).limit(100).execute()

            executions = ex_res.data
            if not executions:
                return results

            # 2. Fetch Suggestions
            sugg_ids = [x['suggestion_id'] for x in executions if x.get('suggestion_id')]
            sugg_ids = list(set(sugg_ids)) # dedup

            suggestion_map = {}
            if sugg_ids:
                # Chunk IDs if too many? Supabase URL length limit.
                # Assuming < 100 IDs is fine.
                s_res = self.supabase.table(self.logs_table)\
                    .select("id, target_price, suggested_entry, order_json")\
                    .in_("id", sugg_ids)\
                    .execute()

                for s in s_res.data:
                    # Priority: target_price -> order_json.limit_price -> suggested_entry
                    ref_price = s.get('target_price')
                    if not ref_price and s.get('order_json'):
                        ref_price = s['order_json'].get('limit_price')
                    if not ref_price:
                        ref_price = s.get('suggested_entry')

                    suggestion_map[s['id']] = float(ref_price or 0.0)

            # 3. Calculate Drag per Symbol
            symbol_drags = {s: [] for s in symbols}

            for ex in executions:
                sym = ex.get('symbol')
                if sym not in symbol_drags: continue

                fill_price = float(ex.get('fill_price', 0.0))
                fees = float(ex.get('fees', 0.0))
                qty = float(ex.get('quantity', 1.0))
                s_id = ex.get('suggestion_id')

                if fill_price <= 0: continue

                # Slippage
                slippage = 0.0
                if s_id and s_id in suggestion_map:
                    target_price = suggestion_map[s_id]
                    if target_price > 0:
                        slippage = abs(fill_price - target_price)

                        # Calculate BPS for logging/telemetry if needed
                        # slip_bps = (slippage / target_price) * 10000

                # Total Drag per share
                fee_per_share = fees / qty if qty > 0 else 0
                drag = slippage + fee_per_share

                # Sanity check: Ignore outliers > 10% of price or huge absolute drag
                # Assuming drag < $5.00 is reasonable for options.
                if drag < 10.0:
                    symbol_drags[sym].append(drag)

            # 4. Average
            for sym, drags in symbol_drags.items():
                if drags:
                    avg_drag = statistics.mean(drags)
                    results[sym] = avg_drag
                    # If drag is very low (e.g. 0), keep it 0.
                    # But if 0, maybe fallback to default?
                    # No, if history says 0 slippage, use 0.
                else:
                    # No valid drags found despite executions? Use default.
                    results[sym] = default_drag

        except Exception as e:
            logger.error(f"Error fetching batch execution stats: {e}")
            # Return defaults on error

        return results

    def estimate_execution_cost(self, symbol: str, regime: str = "normal") -> float:
        """
        Returns estimated execution cost per share (slippage + fees) based on symbol history and regime.
        """
        base_cost = self.get_execution_drag_stats(symbol)

        if regime == "suppressed":
            return base_cost * 0.8
        elif regime == "elevated":
            return base_cost * 1.5
        elif regime == "shock":
            return base_cost * 3.0

        return base_cost

    def simulate_fill(self,
                      symbol: str,
                      order_type: str,
                      price: float,
                      quantity: float,
                      regime: str) -> Dict[str, Any]:
        """
        Simulates an execution for backtesting/paper trading with probabilistic fill logic.
        """
        side = "buy"
        if quantity < 0: side = "sell"

        res = self.cost_model.simulate_fill(price, abs(quantity), side)

        return {
            "fill_price": res.fill_price,
            "quantity": res.filled_quantity,
            "fees": res.commission_paid,
            "slippage": res.slippage_paid,
            "status": res.status,
            "fill_probability": res.fill_probability,
            "execution_drag": res.slippage_paid + (res.commission_paid / res.filled_quantity if res.filled_quantity > 0 else 0)
        }
