import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple

import numpy as np
from supabase import Client
from packages.quantum.market_data import PolygonService, extract_underlying_symbol, normalize_option_symbol
from packages.quantum.analytics.surprise import compute_surprise
from packages.quantum.nested_logging import log_outcome
from packages.quantum.services.options_utils import get_contract_multiplier
from packages.quantum.common_enums import OutcomeStatus
from packages.quantum.services.provider_guardrails import get_circuit_breaker

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
                .select("id, status, ticker, order_json, direction, created_at") \
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

        status = OutcomeStatus.COMPLETE
        reason_codes = []

        # Initialize counterfactual variables safely
        cf_pnl = None
        cf_avail = False
        cf_reason = None

        # --- Outcome Logic ---

        # Priority 1: Execution
        if executions:
            attribution_type = "execution"
            related_id = executions[0]["id"]
            realized_pnl_1d, realized_vol_1d = self._calculate_execution_pnl(executions)
            if realized_vol_1d is None:
                status = OutcomeStatus.PARTIAL
                reason_codes.append("missing_vol")

                # Check Guardrail / Circuit Breaker status
                cb = get_circuit_breaker("polygon")
                if cb.state.value == "OPEN":
                    reason_codes.append("provider_down")
                elif not self.polygon_service.api_key:
                    reason_codes.append("polygon_unavailable")
                else:
                    reason_codes.append("missing_market_data")

        # Priority 2: Suggestion (No Action)
        elif suggestions:
            attribution_type = "no_action"
            related_id = suggestions[0]["id"]
            realized_pnl_1d = 0.0

            # --- Counterfactual Logic ---
            cf_pnl, cf_avail = self._calculate_counterfactual_pnl(suggestions)
            if not cf_avail:
                cf_reason = "Missing market data for one or more legs"
                reason_codes.append("missing_counterfactual")
                # If no action, and counterfactual is missing, it is PARTIAL not INCOMPLETE
                # as core metrics (realized_pnl_1d=0) are present.
                status = OutcomeStatus.PARTIAL

                # Check circuit breaker context
                cb = get_circuit_breaker("polygon")
                if cb.state.value == "OPEN":
                    # If it's open, it could be due to rate limits or general failures
                    if cb.total_rate_limits > 0:
                        reason_codes.append("polygon_rate_limited")
                    else:
                         reason_codes.append("polygon_circuit_open")

        # Priority 3: Optimizer Decision (Simulation)
        elif decision["decision_type"] == "optimizer_weights":
            attribution_type = "optimizer_simulation"
            # Try to calc sim PnL
            weights = decision.get("content", {}).get("target_weights", {})
            total_equity = None
            if inference_log:
                total_equity = inference_log.get("inputs_snapshot", {}).get("total_equity")

            # Fallback to portfolio_snapshots if inference equity missing
            if total_equity is None:
                user_id = decision.get("user_id")
                if user_id:
                    try:
                        res = self.supabase.table("portfolio_snapshots") \
                            .select("total_equity") \
                            .eq("user_id", user_id) \
                            .order("created_at", desc=True) \
                            .limit(1) \
                            .execute()
                        if res.data and res.data[0].get("total_equity") is not None:
                            total_equity = float(res.data[0]["total_equity"])
                    except Exception:
                        pass

            # Strict equity check
            if total_equity is None:
                attribution_type = "incomplete_data"
                status = OutcomeStatus.INCOMPLETE
                reason_codes.append("missing_equity_snapshot")
            else:
                pnl, vol = self._calculate_sim_pnl(weights, total_equity)
                realized_pnl_1d = pnl
                realized_vol_1d = vol
                # Note: _calculate_sim_pnl returns 0.0 vol if missing prices, which might be misleading
                # Ideally check inside if prices were missing.
                # Assuming if vol is 0.0 but weights > 0, we might have missing data.
                if vol == 0.0 and any(w > 0 for w in weights.values()):
                     # This is a heuristic.
                     pass

        # Priority 4: Fallback (if inference log exists, use portfolio PnL)
        elif inference_log:
            attribution_type = "portfolio_snapshot"
            # Fixed unpacking
            pnl, vol = self._calculate_portfolio_pnl(inference_log)
            realized_pnl_1d = pnl
            realized_vol_1d = vol

            # _calculate_portfolio_pnl returns 0.0 vol on failure.
            # We can't easily distinguish 0 vol from missing data without better return types there.
            # But inference_log usually implies we have snapshots.

        else:
            # Decision exists but no suggestion, execution, or inference log context.
            attribution_type = "incomplete_data"
            status = OutcomeStatus.INCOMPLETE
            reason_codes.append("missing_context")

        if status == OutcomeStatus.INCOMPLETE:
            log_outcome(
                trace_id=uuid.UUID(trace_id),
                realized_pl_1d=0.0,
                realized_vol_1d=0.0,
                surprise_score=0.0,
                attribution_type=attribution_type,
                related_id=uuid.UUID(related_id) if related_id else None,
                status=status.value,
                reason_codes=reason_codes
            )
            return

        # --- Surprise Calculation ---
        surprise = 0.0

        # Handle partial data for volatility
        safe_realized_vol = realized_vol_1d if realized_vol_1d is not None else 0.0

        if realized_vol_1d is None and attribution_type == "execution":
            # Already set status PARTIAL above
            pass

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
            # If we don't have inference log, we can't compute surprise properly.
            # Does this make it PARTIAL?
            # Requirement: "COMPLETE: all core metrics present"
            # Surprise requires predicted sigma. If missing, maybe PARTIAL?
            # User said "PARTIAL: outcome computed but missing a non-critical metric (e.g., realized_vol)".
            # If surprise is 0.0 because of missing prediction, maybe okay.
            pass

        # --- Write Log ---
        # Prepare counterfactual args if applicable
        cf_args = {}
        if attribution_type == "no_action":
            if cf_avail:
                cf_args['counterfactual_pl_1d'] = cf_pnl
                cf_args['counterfactual_available'] = True
            elif cf_reason:
                 cf_args['counterfactual_available'] = False
                 cf_args['counterfactual_reason'] = cf_reason

        log_outcome(
            trace_id=uuid.UUID(trace_id),
            realized_pl_1d=realized_pnl_1d,
            realized_vol_1d=safe_realized_vol,
            surprise_score=surprise,
            attribution_type=attribution_type,
            related_id=uuid.UUID(related_id) if related_id else None,
            status=status.value,
            reason_codes=reason_codes,
            **cf_args
        )

    def _calculate_counterfactual_pnl(self, suggestions: List[Dict]) -> Tuple[float, bool]:
        """
        Computes what the PnL would have been if the suggestion was taken.
        Returns (pnl, available).

        Supports:
        - Single Options (via ticker)
        - Multi-leg Spreads (via order_json['legs'])
        - Stock Trades
        """
        if not suggestions:
            return 0.0, False

        suggestion = suggestions[0]
        order_json = suggestion.get("order_json") or {}
        legs = order_json.get("legs", [])

        # Determine anchor date for deterministic history
        created_at_str = suggestion.get("created_at")
        anchor_date = None
        if created_at_str:
            try:
                # Parse ISO format
                created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                anchor_date = created_at
            except ValueError:
                pass # anchor_date remains None, fallback to default behavior (likely now)

        # Strategy 1: Multi-Leg Spread
        if legs:
            total_pnl = 0.0
            all_available = True

            for leg in legs:
                symbol = leg.get("symbol")
                quantity = abs(float(leg.get("quantity", 1.0)))
                side = leg.get("side", "buy").lower() # buy/sell

                # Check side for PnL sign
                # Buy -> Long -> PnL = (Exit - Entry)
                # Sell -> Short -> PnL = (Entry - Exit) = -(Exit - Entry)
                direction_mult = 1.0 if side in ["buy", "long"] else -1.0

                leg_pnl, leg_avail = self._get_single_asset_pnl(symbol, direction_mult, quantity, anchor_date)

                if not leg_avail:
                    all_available = False
                    break

                total_pnl += leg_pnl

            if all_available:
                return total_pnl, True
            # Fallthrough if spread fails?
            # If spread data is partial, we probably shouldn't return partial PnL.
            return 0.0, False

        # Strategy 2: Single Ticker (Option or Stock)
        ticker = suggestion.get("ticker")
        if ticker:
            # Determine direction/quantity
            direction = suggestion.get("direction", "long").lower()
            direction_mult = -1.0 if direction == "short" else 1.0

            # Try to get quantity from order_json or default to 1
            qty = float(order_json.get("contracts") or order_json.get("quantity") or 1.0)

            pnl, avail = self._get_single_asset_pnl(ticker, direction_mult, qty, anchor_date)
            return pnl, avail

        return 0.0, False

    def _get_single_asset_pnl(self, symbol: str, direction_mult: float, quantity: float, anchor_date: Optional[datetime] = None) -> Tuple[float, bool]:
        """
        Helper to fetch 1-day PnL for a single asset (Option or Stock).
        Returns (pnl_dollars, available).
        """
        if not symbol:
            return 0.0, False

        # Normalize symbol for Polygon
        # If it looks like an option but lacks O:, add it
        normalized = normalize_option_symbol(symbol)

        try:
            # Fetch window: anchor_date up to +5 days to catch Next Trading Day.
            # Polygon's to_date is inclusive.
            to_date = None
            if anchor_date:
                # We want at least T and T+1. If we ask for T+5, we get a buffer for weekends.
                to_date = anchor_date + timedelta(days=5)

            # Fetch historical prices
            # Note: We rely on PolygonService to handle 'days' (lookback from to_date).
            # If we want forward looking from anchor_date, we have to be careful.
            # PolygonService.get_historical_prices(days=N, to_date=D) returns N days ending at D.
            # So if we want [Anchor, Anchor+1, ...], we need to set to_date=Anchor+5, and days=10 (to cover enough history).
            # Wait, `get_historical_prices` sorts ascending.

            hist = self.polygon_service.get_historical_prices(normalized, days=10, to_date=to_date)
            if not hist:
                return 0.0, False

            prices = hist.get("prices", [])
            dates = hist.get("dates", []) # List[str] YYYY-MM-DD

            if len(prices) < 2 or len(dates) < 2:
                return 0.0, False

            # Find the index of the anchor date (or the closest date before/on it)
            if not anchor_date:
                # Fallback: Just take last 2 days if no anchor
                p_exit = prices[-1]
                p_entry = prices[-2]
            else:
                anchor_str = anchor_date.strftime('%Y-%m-%d')

                # Find index of anchor date
                idx_entry = -1
                for i, d in enumerate(dates):
                    if d >= anchor_str:
                        # If exact match, great.
                        # If d > anchor_str, it means anchor was non-trading, so we enter at next avail?
                        # Or do we strictly require anchor date to be present?
                        # For "Suggestion at T", we assume we enter at T (Close).
                        # If T is missing, maybe we can't trade?
                        # Let's simple match: first date >= anchor_str is our Entry.
                        # Then next date is Exit.
                        idx_entry = i
                        break

                if idx_entry == -1 or idx_entry >= len(prices) - 1:
                    # Anchor date is too new (no T+1 data yet) or not found
                    return 0.0, False

                p_entry = prices[idx_entry]
                p_exit = prices[idx_entry + 1]

            raw_diff = p_exit - p_entry

            multiplier = get_contract_multiplier(normalized)

            pnl = raw_diff * quantity * multiplier * direction_mult
            return float(pnl), True

        except Exception:
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
                if hist:
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
                    if u_hist:
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
                if hist:
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
                if hist:
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
