import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple

import numpy as np
from supabase import Client
from packages.quantum.market_data import PolygonService, extract_underlying_symbol
from packages.quantum.analytics.surprise import compute_surprise
from packages.quantum.nested_logging import log_outcome
from packages.quantum.services.options_utils import get_contract_multiplier

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
        attribution_type = "portfolio_snapshot"
        related_id = None
        is_incomplete = False

        # Initialize counterfactual variables safely
        cf_pnl = None
        cf_avail = False

        # --- Outcome Logic ---

        # Priority 1: Execution
        if executions:
            attribution_type = "execution"
            related_id = executions[0]["id"]
            realized_pnl_1d, realized_vol_1d = self._calculate_execution_pnl(executions)

        # Priority 2: Suggestion (No Action)
        elif suggestions:
            attribution_type = "no_action"
            related_id = suggestions[0]["id"]
            realized_pnl_1d = 0.0

            # --- Counterfactual Logic ---
            cf_pnl, cf_avail = self._calculate_counterfactual_pnl(suggestions)

        # Priority 3: Optimizer Decision (Simulation)
        elif decision["decision_type"] == "optimizer_weights":
            attribution_type = "optimizer_simulation"
            # Try to calc sim PnL
            weights = decision.get("content", {}).get("target_weights", {})
            total_equity = None
            if inference_log:
                total_equity = inference_log.get("inputs_snapshot", {}).get("total_equity")

            # Strict equity check
            if total_equity is None:
                # Fallback: check db via CashService?
                # For now, if not in inference_log, we assume incomplete data for simulation
                is_incomplete = True
            else:
                realized_pnl_1d, realized_vol_1d = self._calculate_sim_pnl(weights, total_equity)

        # Priority 4: Fallback (if inference log exists, use portfolio PnL)
        elif inference_log:
            attribution_type = "portfolio_snapshot"
            # Fixed unpacking
            realized_pnl_1d, realized_vol_1d = self._calculate_portfolio_pnl(inference_log)

        else:
            # Decision exists but no suggestion, execution, or inference log context.
            attribution_type = "incomplete_data"
            is_incomplete = True

        if is_incomplete:
            # Log as incomplete or skip?
            # User requirement: "if missing, outcomes marked INCOMPLETE (no fake equity)"
            # We will log it with a specific type so we can filter later.
            log_outcome(
                trace_id=uuid.UUID(trace_id),
                realized_pl_1d=0.0,
                realized_vol_1d=0.0,
                surprise_score=0.0,
                attribution_type="incomplete_data",
                related_id=uuid.UUID(related_id) if related_id else None
            )
            return

        # --- Surprise Calculation ---
        surprise = 0.0

        # Handle partial data for volatility
        # If realized_vol_1d is None, we mark as partial and default to 0.0 for logging,
        # but the attribution type signals the data quality issue.
        safe_realized_vol = realized_vol_1d if realized_vol_1d is not None else 0.0

        if realized_vol_1d is None and attribution_type == "execution":
            attribution_type = "partial_execution"

        if inference_log:
            sigma_pred_matrix = inference_log.get("predicted_sigma", {}).get("sigma_matrix", [])
            avg_predicted_vol = 0.0
            if sigma_pred_matrix:
                arr = np.array(sigma_pred_matrix)
                if arr.shape[0] > 0:
                    avg_predicted_vol = np.mean(np.sqrt(np.diag(arr)))

            sigma_pred_1d = avg_predicted_vol / 16.0 # Annualized to daily approx

            surprise = compute_surprise(
                sigma_pred=sigma_pred_1d,
                sigma_realized=safe_realized_vol,
                pnl_realized=realized_pnl_1d
            )
        else:
            surprise = 0.0

        # --- Write Log ---
        # Prepare counterfactual args if applicable
        cf_args = {}
        if attribution_type == "no_action" and cf_avail:
            cf_args['counterfactual_pl_1d'] = cf_pnl
            cf_args['counterfactual_available'] = True

        log_outcome(
            trace_id=uuid.UUID(trace_id),
            realized_pl_1d=realized_pnl_1d,
            realized_vol_1d=safe_realized_vol,
            surprise_score=surprise,
            attribution_type=attribution_type,
            related_id=uuid.UUID(related_id) if related_id else None,
            **cf_args
        )

    def _calculate_counterfactual_pnl(self, suggestions: List[Dict]) -> Tuple[float, bool]:
        """
        Computes what the PnL would have been if the suggestion was taken.
        Returns (pnl, available).
        """
        if not suggestions:
            return 0.0, False

        suggestion = suggestions[0]
        ticker = suggestion.get("ticker")
        if not ticker:
            return 0.0, False

        # Try to parse order details if available, otherwise heuristic
        # We assume entry at T (suggestion time) and exit at T+1 (now)
        # Using PolygonService to get price change over last day

        try:
            # We fetch 5 days to be safe and take last 2
            hist = self.polygon_service.get_historical_prices(ticker, days=5)
            prices = hist.get("prices", [])

            if len(prices) < 2:
                return 0.0, False

            p_today = prices[-1]
            p_prev = prices[-2]

            # Check direction
            direction = suggestion.get("direction", "long").lower()
            multiplier = get_contract_multiplier(ticker)

            # Heuristic: 1 contract or base quantity
            qty = 1.0

            raw_diff = p_today - p_prev

            if direction == "short":
                pnl = -raw_diff * qty * multiplier
            else:
                pnl = raw_diff * qty * multiplier

            return float(pnl), True

        except Exception as e:
            # print(f"Counterfactual calc failed: {e}")
            return 0.0, False

    def _calculate_execution_pnl(self, executions: List[Dict]) -> Tuple[float, Optional[float]]:
        """
        Returns (pnl, vol).
        Computes PnL from option price marks and Vol from underlying returns.
        Returns None for vol if underlying data is unavailable.
        """
        total_pnl = 0.0
        vols = []
        processed_underlyings = set()

        for exc in executions:
            sym = exc["symbol"]
            qty = exc["quantity"]
            fill_price = exc["fill_price"]

            # 1. PnL Calculation (using option/asset price)
            try:
                hist = self.polygon_service.get_historical_prices(sym, days=5)
                prices = hist.get("prices", [])
                if len(prices) >= 1:
                    curr = prices[-1]
                    multiplier = get_contract_multiplier(sym)
                    total_pnl += (curr - fill_price) * qty * multiplier
            except:
                pass

            # 2. Volatility Calculation (using underlying)
            underlying = extract_underlying_symbol(sym)
            if underlying not in processed_underlyings:
                try:
                    # Fetch slightly more history to ensure we have valid returns
                    u_hist = self.polygon_service.get_historical_prices(underlying, days=10)
                    u_returns = u_hist.get("returns", [])

                    # Need at least a few data points for meaningful vol
                    if len(u_returns) >= 3:
                        vol_daily = np.std(u_returns)
                        vols.append(vol_daily)
                        processed_underlyings.add(underlying)
                except:
                    # Failed to get underlying data
                    pass

        # Aggregate Vol (average if multiple underlyings, usually just one)
        avg_vol = float(np.mean(vols)) if vols else None

        return total_pnl, avg_vol

    def _calculate_sim_pnl(self, weights: Dict[str, float], total_equity: float) -> Tuple[float, float]:
        """
        Returns (pnl, vol)
        """
        sim_pnl = 0.0
        rets = []

        for sym, w in weights.items():
            if w == 0: continue
            try:
                hist = self.polygon_service.get_historical_prices(sym, days=5)
                prices = hist.get("prices", [])
                if len(prices) >= 2:
                    ret = (prices[-1] - prices[-2]) / prices[-2]
                    sim_pnl += w * total_equity * ret
                    rets.append(abs(ret)) # Approximation of asset vol contribution
            except:
                pass

        avg_vol = sum(rets) / len(rets) if rets else 0.0
        return sim_pnl, avg_vol

    def _calculate_portfolio_pnl(self, inference_log: Dict) -> Tuple[float, float]:
        """
        Returns (pnl, vol)
        """
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

                    # Vol calculation
                    ret = (p_today - p_yesterday) / p_yesterday
                    realized_vols.append(abs(ret))

                    if sym in qty_map:
                        qty = qty_map[sym]
                        multiplier = get_contract_multiplier(sym)

                        # PnL calculation
                        total_pnl += (p_today - p_yesterday) * qty * multiplier
            except:
                pass

        avg_vol = sum(realized_vols) / len(realized_vols) if realized_vols else 0.0
        return total_pnl, avg_vol
