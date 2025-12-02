import os
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from analytics.regime_scoring import ScoringEngine, ConvictionTransform
from analytics.regime_integration import (
    DEFAULT_WEIGHT_MATRIX,
    DEFAULT_CATALYST_PROFILES,
    DEFAULT_LIQUIDITY_SCALAR,
    DEFAULT_REGIME_PROFILES,
    map_market_regime,
    run_historical_scoring
)
from market_data import PolygonService
from analytics.factors import calculate_trend, calculate_volatility, calculate_rsi
from nested.backbone import infer_global_context, GlobalContext

# --- Learning Hook ---

def learn_from_cycle(
    trajectory: List[Dict[str, Any]],
    entry: Dict[str, Any],
    exit: Dict[str, Any],
    reward: float,
    mode: str = "historical",
) -> None:
    """
    Placeholder hook for nested learning.
    This would eventually feed (state, action, reward) tuples into the QCI/Surrogate optimizer
    or update the regime-conditional weights.
    """
    # For now, just log structured data for debug/analysis
    print(f"[NestedLearning:{mode}] Cycle closed. PnL: {reward:.2f}. "
          f"EntryRegime: {entry.get('regime')}, ExitRegime: {exit.get('regimeAtExit')}")

class HistoricalCycleService:
    def __init__(self, polygon_service: PolygonService = None):
        self.polygon = polygon_service or PolygonService()
        self.scoring_engine = ScoringEngine(
            DEFAULT_WEIGHT_MATRIX,
            DEFAULT_CATALYST_PROFILES,
            DEFAULT_LIQUIDITY_SCALAR
        )
        self.conviction_transform = ConvictionTransform(DEFAULT_REGIME_PROFILES)
        self.lookback_window = 60 # Days needed for indicators
        self.enable_learning = os.getenv("ENABLE_HISTORICAL_NESTED_LEARNING", "false").lower() == "true"

    def run_cycle(self, cursor_date_str: str, symbol: str = "SPY") -> Dict[str, Any]:
        """
        Runs exactly one historical trade cycle (Entry -> Exit) starting from cursor_date.
        """
        # 1. Parse Cursor
        try:
            start_date = datetime.strptime(cursor_date_str, "%Y-%m-%d")
        except (ValueError, TypeError):
            # If invalid or empty, default to 2 years ago
            start_date = datetime.now() - timedelta(days=365*2)

        # 2. Fetch Data Chunk (Start Date -> 1 Year Forward + Lookback)
        simulation_end_date = start_date + timedelta(days=365)
        days_needed = 365 + self.lookback_window

        try:
            hist_data = self.polygon.get_historical_prices(
                symbol,
                days=days_needed,
                to_date=simulation_end_date
            )
        except Exception as e:
            return {"error": f"Data fetch failed: {str(e)}", "done": True, "status": "no_data"}

        dates = hist_data.get('dates', [])
        prices = hist_data.get('prices', [])
        # volumes = hist_data.get('volumes', []) # Unused

        # 3. Locate Start Index
        start_idx = -1
        for i, d_str in enumerate(dates):
            d = datetime.strptime(d_str, "%Y-%m-%d")
            if d >= start_date:
                start_idx = i
                break

        if start_idx == -1 or start_idx >= len(dates) - 1:
            return {
                "done": True,
                "status": "no_data",
                "message": "No more historical data starting from cursor"
            }

        if start_idx < self.lookback_window:
            start_idx = self.lookback_window

        # 4. Simulation Loop
        in_trade = False
        entry_details = {}
        trajectory = [] # Capture state at each step for learning
        current_idx = start_idx

        while current_idx < len(dates):
            # GUARD: Future Leakage Check
            # We strictly slice up to current_idx (inclusive)
            price_slice = prices[:current_idx+1]
            current_date_str = dates[current_idx]
            current_price = prices[current_idx]

            # --- Shared Logic Usage ---
            # 1. Compute Factors
            trend = calculate_trend(price_slice) # UP/DOWN/NEUTRAL
            vol_annual = calculate_volatility(price_slice, window=30)
            rsi_val = calculate_rsi(price_slice, period=14)

            # 2. Detect Regime (Global Backbone)
            features = {
                "spy_trend": trend.lower(),
                "vix_level": 20.0, # Baseline
            }
            # Enhanced VIX proxy from vol
            if vol_annual > 0.30: features["vix_level"] = 35.0
            elif vol_annual > 0.20: features["vix_level"] = 25.0
            else: features["vix_level"] = 15.0

            global_context: GlobalContext = infer_global_context(features)

            # 3. Map to Scoring Regime (Centralized Helper)
            regime_mapped = map_market_regime({
                "state": global_context.global_regime,
                "vol_annual": vol_annual
            })

            # 4. Score using Centralized Pipeline
            # Map factors to scoring inputs (0-100)
            trend_score = 100.0 if trend == "UP" else (0.0 if trend == "DOWN" else 50.0)

            vol_score = 50.0
            if vol_annual < 0.15: vol_score = 100.0
            elif vol_annual > 0.30: vol_score = 0.0

            value_score = 50.0
            if rsi_val < 30: value_score = 100.0
            elif rsi_val > 70: value_score = 0.0

            factors_input = {
                "trend": trend_score,
                "volatility": vol_score,
                "value": value_score
            }

            scoring_result = run_historical_scoring(
                symbol_data={
                    "symbol": symbol,
                    "factors": factors_input,
                    "liquidity_tier": "top"
                },
                regime=regime_mapped,
                scoring_engine=self.scoring_engine,
                conviction_transform=self.conviction_transform,
                universe_median=None
            )

            c_i = scoring_result['conviction']

            # Capture state for trajectory
            step_snapshot = {
                "date": current_date_str,
                "price": current_price,
                "regime": regime_mapped,
                "conviction": c_i,
                "factors": factors_input
            }

            # 6. State Machine
            if not in_trade:
                if c_i >= 0.70: # High conviction entry
                    in_trade = True
                    entry_details = {
                        "entryIndex": current_idx,
                        "entryTime": current_date_str,
                        "entryPrice": current_price,
                        "direction": "long",
                        "regimeAtEntry": regime_mapped,
                        "convictionAtEntry": c_i
                    }
                    trajectory = [step_snapshot] # Start trajectory
                # else: pass (continue scanning)

            else:
                # In Trade - Monitor for Exit
                trajectory.append(step_snapshot)
                should_exit = False

                # Exit Rule 1: Loss of Conviction
                if c_i < 0.5: should_exit = True

                # Exit Rule 2: Hard Stops / Targets (simplified)
                pnl_pct = (current_price - entry_details['entryPrice']) / entry_details['entryPrice']
                if pnl_pct < -0.05: should_exit = True
                if pnl_pct > 0.08: should_exit = True

                if should_exit:
                    pnl_amount = (current_price - entry_details['entryPrice'])

                    exit_details = {
                        "exitIndex": current_idx,
                        "exitTime": current_date_str,
                        "exitPrice": current_price,
                        "regimeAtExit": regime_mapped,
                        "convictionAtExit": c_i
                    }

                    # Nested Learning Trigger
                    if self.enable_learning:
                        learn_from_cycle(
                            trajectory,
                            entry_details,
                            exit_details,
                            pnl_amount,
                            mode="historical"
                        )

                    return {
                        **entry_details,
                        **exit_details,
                        "pnl": pnl_amount,
                        "done": False,
                        "status": "normal_exit",
                        "nextCursor": dates[current_idx + 1] if current_idx + 1 < len(dates) else dates[-1]
                    }

            current_idx += 1

        # End of Data Loop
        if in_trade:
            # Forced Exit
            pnl_amount = (prices[-1] - entry_details['entryPrice'])
            exit_details = {
                "exitIndex": len(dates)-1,
                "exitTime": dates[-1],
                "exitPrice": prices[-1],
                "regimeAtExit": "unknown", # Data ended
                "convictionAtExit": 0.5
            }

            if self.enable_learning:
                learn_from_cycle(
                    trajectory,
                    entry_details,
                    exit_details,
                    pnl_amount,
                    mode="historical_forced"
                )

            return {
                **entry_details,
                **exit_details,
                "pnl": pnl_amount,
                "done": True,
                "status": "forced_exit",
                "message": "Data ended during trade",
                "nextCursor": None
            }

        return {
            "done": True,
            "status": "no_entry",
            "message": "End of data reached without finding another trade.",
            "nextCursor": None
        }
