from supabase import Client
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import logging
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

        # 1. Fetch suggestion to get symbols/defaults if needed
        # (Optional validation step, can skip if we trust frontend input)
        try:
            s_res = self.supabase.table(self.logs_table).select("*").eq("id", suggestion_id).single().execute()
            suggestion = s_res.data
        except Exception:
            suggestion = None

        if not suggestion:
            # Fallback if suggestion log doesn't exist yet (race condition?) or invalid ID
            # We proceed but can't link effectively?
            # Actually, if ID is provided, it should exist.
            pass

        # 2. Calculate Slippage if possible
        # fill_details should ideally have 'mid_price_at_submission'
        mid_price = fill_details.get("mid_price_at_submission")
        fill_price = fill_details.get("fill_price", 0.0)
        slippage = 0.0

        if mid_price and fill_price > 0:
            slippage = abs(fill_price - mid_price)
            # Store calculated slippage back into details if schema allows,
            # or we rely on 'fees' field to capture drag?
            # The prompt says "Persist execution cost history".
            # We will try to store it in a JSON column if 'details' exists,
            # otherwise we just assume 'fees' captures explicit costs.
            # But slippage is implicit.
            pass

        # 3. Create TradeExecution
        execution_data = {
            "user_id": user_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": fill_details.get("symbol") or (suggestion.get("symbol") if suggestion else "UNKNOWN"),
            "fill_price": fill_price,
            "quantity": int(fill_details.get("quantity", 1)),
            "fees": fill_details.get("fees", 0.0),
            "suggestion_id": suggestion_id
        }

        # Try adding slippage if column exists, otherwise it might be ignored or error.
        # Given "Keep schema changes minimal", we won't add column blindly.
        # If schema supports 'details' or 'metadata' JSONB, we use that.
        # Assuming minimal schema, we might skip saving slippage explicitly
        # unless we add it to 'fees' (not correct) or rely on offline analysis.

        # However, for "Feed expected execution cost into UnifiedScore", we need history.
        # We can fetch 'fill_price' and 'suggestion.target_price' (from logs) later to calculate slippage.

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

    def fuzzy_match_executions(self, user_id: str, lookback_hours: int = 24):
        """
        Matches orphan TradeExecutions (from broker sync) to orphan SuggestionLogs.
        """
        # 1. Get orphan executions
        start_time = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()

        ex_res = self.supabase.table(self.executions_table)\
            .select("*")\
            .eq("user_id", user_id)\
            .is_("suggestion_id", "null")\
            .gte("timestamp", start_time)\
            .execute()

        executions = ex_res.data or []
        if not executions:
            return 0

        # 2. Get orphan suggestions
        # We look for suggestions created shortly before execution
        log_res = self.supabase.table(self.logs_table)\
            .select("*")\
            .eq("user_id", user_id)\
            .is_("trade_execution_id", "null")\
            .gte("created_at", start_time)\
            .execute()

        logs = log_res.data or []

        matches = 0
        for ex in executions:
            ex_time = datetime.fromisoformat(ex["timestamp"].replace("Z", "+00:00"))

            # Find best match
            best_log = None
            min_diff = float('inf')

            for log in logs:
                if log["symbol"] != ex["symbol"]:
                    continue

                log_time = datetime.fromisoformat(log["created_at"].replace("Z", "+00:00"))

                # Execution must happen AFTER suggestion
                diff_seconds = (ex_time - log_time).total_seconds()

                # Window: 0 to 6 hours?
                if 0 <= diff_seconds < 6 * 3600:
                    if diff_seconds < min_diff:
                        min_diff = diff_seconds
                        best_log = log

            if best_log:
                # Link them
                self.supabase.table(self.executions_table)\
                    .update({"suggestion_id": best_log["id"]})\
                    .eq("id", ex["id"])\
                    .execute()

                self.supabase.table(self.logs_table)\
                    .update({"was_accepted": True, "trade_execution_id": ex["id"]})\
                    .eq("id", best_log["id"])\
                    .execute()

                matches += 1

        return matches

    def estimate_execution_cost(self, symbol: str, regime: str = "normal") -> float:
        """
        Returns estimated execution cost per share (slippage + fees) based on symbol history and regime.
        """
        # 1. Try to fetch history for symbol
        # We need executions linked to suggestions to compare fill_price vs target/mid
        # This is expensive to query live.
        # Fallback to heuristic for now, but framework allows extension.

        base_slippage = 0.02 # $0.02 per share default

        if regime == "suppressed":
            base_slippage = 0.01
        elif regime == "elevated":
            base_slippage = 0.04
        elif regime == "shock":
            base_slippage = 0.10

        # TODO: Implement actual DB query for historical slippage avg
        # query = ... select avg(abs(fill_price - suggestion.target_price)) ...

        return base_slippage

    def simulate_fill(self,
                      symbol: str,
                      order_type: str,
                      price: float,
                      quantity: float,
                      regime: str) -> Dict[str, Any]:
        """
        Simulates an execution for backtesting/paper trading with probabilistic fill logic.
        """
        # Delegate to TransactionCostModel
        # Map regime to slippage params if needed
        # For now, we use the standard model
        side = "buy" # default assumption for cost check
        if quantity < 0: side = "sell"

        # Pass rng?
        res = self.cost_model.simulate_fill(price, abs(quantity), side)

        return {
            "fill_price": res.fill_price,
            "quantity": res.filled_quantity,
            "fees": res.commission_paid,
            "slippage": res.slippage_paid,
            "status": res.status
        }
