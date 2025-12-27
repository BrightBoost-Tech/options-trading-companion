import os
import sys
import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from supabase import Client

# Depending on how this is imported, these might need adjustments
# but assuming standard python path
from packages.quantum.market_data import PolygonService
from packages.quantum.analytics.surprise import compute_surprise
from packages.quantum.nested_logging import log_outcome

class OutcomeAggregator:
    def __init__(self, supabase: Client, polygon_service: PolygonService):
        self.supabase = supabase
        self.polygon_service = polygon_service

    async def run(self, start_time: datetime, end_time: datetime):
        """
        Scans decision logs within the window and computes outcomes.
        """
        print(f"[{datetime.now()}] Starting Outcome Aggregation for window {start_time} to {end_time}...")

        # 1. Fetch relevant decisions
        decisions = self._fetch_decisions(start_time, end_time)
        print(f"Found {len(decisions)} candidate decisions.")

        processed_count = 0
        for decision in decisions:
            trace_id = decision.get("trace_id")
            if not trace_id:
                continue

            # 2. Check if outcome already exists
            if self._outcome_exists(trace_id):
                continue

            # 3. Fetch Context (Inference Log)
            inference_log = self._fetch_inference_log(trace_id)

            # 4. Fetch Linked Suggestions & Executions
            suggestions = self._fetch_suggestions(trace_id)
            executions = self._fetch_executions(suggestions)

            # 5. Compute Outcome
            self._process_single_outcome(decision, inference_log, suggestions, executions)
            processed_count += 1

        print(f"Updated {processed_count} outcomes.")
        return processed_count

    def _fetch_decisions(self, start_time: datetime, end_time: datetime) -> List[Dict]:
        """
        Fetch decision logs that represent actionable events.
        """
        try:
            # We filter for specific decision types that imply a "bet" or "allocation"
            types = ["morning_suggestion", "midday_suggestion", "optimizer_weights"]

            res = self.supabase.table("decision_logs") \
                .select("*") \
                .in_("decision_type", types) \
                .gte("created_at", start_time.isoformat()) \
                .lte("created_at", end_time.isoformat()) \
                .execute()
            return res.data or []
        except Exception as e:
            print(f"Error fetching decisions: {e}")
            return []

    def _outcome_exists(self, trace_id: str) -> bool:
        try:
            check = self.supabase.table("outcomes_log").select("trace_id").eq("trace_id", trace_id).execute()
            return bool(check.data)
        except Exception:
            return False

    def _fetch_inference_log(self, trace_id: str) -> Optional[Dict]:
        try:
            res = self.supabase.table("inference_log") \
                .select("predicted_sigma, inputs_snapshot, symbol_universe") \
                .eq("trace_id", trace_id) \
                .execute()
            return res.data[0] if res.data else None
        except Exception:
            return None

    def _fetch_suggestions(self, trace_id: str) -> List[Dict]:
        try:
            res = self.supabase.table("trade_suggestions") \
                .select("id, status, ticker") \
                .eq("trace_id", trace_id) \
                .execute()
            return res.data or []
        except Exception:
            return []

    def _fetch_executions(self, suggestions: List[Dict]) -> List[Dict]:
        if not suggestions:
            return []
        try:
            s_ids = [s["id"] for s in suggestions]
            res = self.supabase.table("trade_executions") \
                .select("*") \
                .in_("suggestion_id", s_ids) \
                .execute()
            return res.data or []
        except Exception:
            return []

    def _process_single_outcome(
        self,
        decision: Dict,
        inference_log: Optional[Dict],
        suggestions: List[Dict],
        executions: List[Dict]
    ):
        trace_id = decision["trace_id"]

        realized_pnl_1d = 0.0
        realized_vol_1d = 0.0
        attribution_type = "portfolio_snapshot" # default fallback
        related_id = None

        # --- Outcome Logic ---

        # Priority 1: Execution
        if executions:
            attribution_type = "execution"
            related_id = executions[0]["id"]
            realized_pnl_1d = self._calculate_execution_pnl(executions)

        # Priority 2: Suggestion (No Action)
        elif suggestions:
            attribution_type = "no_action"
            related_id = suggestions[0]["id"]
            realized_pnl_1d = 0.0

        # Priority 3: Optimizer Decision (Simulation)
        elif decision["decision_type"] == "optimizer_weights":
            attribution_type = "optimizer_simulation"
            # Try to calc sim PnL
            weights = decision.get("content", {}).get("target_weights", {})
            total_equity = 10000.0 # fallback
            if inference_log:
                total_equity = inference_log.get("inputs_snapshot", {}).get("total_equity", 10000.0)

            realized_pnl_1d = self._calculate_sim_pnl(weights, total_equity)

        # Priority 4: Fallback (if inference log exists, use portfolio PnL)
        elif inference_log:
            attribution_type = "portfolio_snapshot"
            realized_pnl_1d, realized_vol_1d = self._calculate_portfolio_pnl(inference_log)

        else:
            # Decision exists but no suggestion, execution, or inference log context.
            # Likely a filtered out candidate or error.
            attribution_type = "incomplete_data"

        # --- Surprise Calculation ---
        # We need predicted volatility.
        # For Morning/Midday, we might not have 'predicted_sigma' from inference_log.
        # We can use a default or skip surprise.

        surprise = 0.0
        if inference_log:
            sigma_pred_matrix = inference_log.get("predicted_sigma", {}).get("sigma_matrix", [])
            avg_predicted_vol = 0.0
            if sigma_pred_matrix:
                import numpy as np
                arr = np.array(sigma_pred_matrix)
                if arr.shape[0] > 0:
                    avg_predicted_vol = np.mean(np.sqrt(np.diag(arr)))

            sigma_pred_1d = avg_predicted_vol / 16.0 # Annualized to daily approx

            if realized_vol_1d == 0.0 and attribution_type != "portfolio_snapshot":
                 # If we didn't calculate vol explicitly (e.g. execution),
                 # use 0 or some proxy? Leaving as 0.0 means "low realized vol" -> "surprise low vol"
                 pass

            surprise = compute_surprise(
                sigma_pred=sigma_pred_1d,
                sigma_realized=realized_vol_1d,
                pnl_realized=realized_pnl_1d
            )
        else:
            # No prediction context (e.g. Rule-based Morning Suggestion).
            # Surprise is undefined or 0.
            surprise = 0.0

        # --- Write Log ---
        log_outcome(
            trace_id=uuid.UUID(trace_id),
            realized_pl_1d=realized_pnl_1d,
            realized_vol_1d=realized_vol_1d,
            surprise_score=surprise,
            attribution_type=attribution_type,
            related_id=uuid.UUID(related_id) if related_id else None
        )

    def _calculate_execution_pnl(self, executions: List[Dict]) -> float:
        total_pnl = 0.0
        for exc in executions:
            sym = exc["symbol"]
            qty = exc["quantity"]
            fill_price = exc["fill_price"]
            try:
                hist = self.polygon_service.get_historical_prices(sym, days=5)
                prices = hist.get("prices", [])
                if len(prices) >= 1:
                    curr = prices[-1]
                    multiplier = 100 if len(sym) > 6 else 1
                    total_pnl += (curr - fill_price) * qty * multiplier
            except:
                pass
        return total_pnl

    def _calculate_sim_pnl(self, weights: Dict[str, float], total_equity: float) -> float:
        sim_pnl = 0.0
        for sym, w in weights.items():
            try:
                hist = self.polygon_service.get_historical_prices(sym, days=5)
                prices = hist.get("prices", [])
                if len(prices) >= 2:
                    ret = (prices[-1] - prices[-2]) / prices[-2]
                    sim_pnl += w * total_equity * ret
            except:
                pass
        return sim_pnl

    def _calculate_portfolio_pnl(self, inference_log: Dict) -> tuple[float, float]:
        inputs = inference_log.get("inputs_snapshot", {})
        positions = inputs.get("positions", [])
        qty_map = {p.get("symbol"): float(p.get("current_quantity", 0)) for p in positions}
        symbol_universe = inference_log.get("symbol_universe", [])

        total_pnl = 0.0
        realized_vols = []

        for sym in symbol_universe:
            try:
                hist = self.polygon_service.get_historical_prices(sym, days=5)
                prices = hist.get("prices", [])
                if len(prices) >= 2:
                    p_today = prices[-1]
                    p_yesterday = prices[-2]
                    ret = (p_today - p_yesterday) / p_yesterday
                    realized_vols.append(abs(ret))

                    if sym in qty_map:
                        qty = qty_map[sym]
                        multiplier = 100 if len(sym) > 6 else 1
                        total_pnl += (p_today - p_yesterday) * qty * multiplier
            except:
                pass

        avg_vol = sum(realized_vols) / len(realized_vols) if realized_vols else 0.0
        return total_pnl, avg_vol
