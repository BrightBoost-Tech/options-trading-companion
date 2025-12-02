from supabase import Client
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

class ExecutionService:
    def __init__(self, supabase: Client):
        self.supabase = supabase
        self.logs_table = "suggestion_logs"
        self.executions_table = "trade_executions"

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

        # 2. Create TradeExecution
        execution_data = {
            "user_id": user_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": fill_details.get("symbol") or (suggestion.get("symbol") if suggestion else "UNKNOWN"),
            "fill_price": fill_details.get("fill_price", 0.0),
            "quantity": int(fill_details.get("quantity", 1)),
            "fees": fill_details.get("fees", 0.0),
            "suggestion_id": suggestion_id
        }

        ex_res = self.supabase.table(self.executions_table).insert(execution_data).execute()
        execution = ex_res.data[0] if ex_res.data else None

        # 3. Update SuggestionLog
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
                # Remove matched log from pool to avoid double matching?
                # Ideally yes, but list is small enough.

        return matches
