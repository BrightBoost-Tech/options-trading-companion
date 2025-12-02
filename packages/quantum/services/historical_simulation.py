import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from analytics.regime_scoring import ScoringEngine, ConvictionTransform
from analytics.regime_integration import (
    DEFAULT_WEIGHT_MATRIX,
    DEFAULT_CATALYST_PROFILES,
    DEFAULT_LIQUIDITY_SCALAR,
    DEFAULT_REGIME_PROFILES
)
from market_data import PolygonService
from analytics.factors import calculate_trend, calculate_volatility, calculate_rsi
from nested.backbone import infer_global_context, GlobalContext

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
            return {"error": f"Data fetch failed: {str(e)}", "done": True}

        dates = hist_data['dates'] # List of strings 'YYYY-MM-DD'
        prices = hist_data['prices']
        volumes = hist_data['volumes']

        # 3. Locate Start Index
        start_idx = -1
        for i, d_str in enumerate(dates):
            d = datetime.strptime(d_str, "%Y-%m-%d")
            if d >= start_date:
                start_idx = i
                break

        if start_idx == -1 or start_idx >= len(dates) - 1:
            return {"done": True, "message": "No more historical data"}

        if start_idx < self.lookback_window:
            start_idx = self.lookback_window

        # 4. Simulation Loop
        in_trade = False
        entry_details = {}
        current_idx = start_idx

        while current_idx < len(dates):
            # GUARD: Future Leakage Check
            # We strictly slice up to current_idx (inclusive)
            price_slice = prices[:current_idx+1]
            vol_slice = volumes[:current_idx+1]
            current_date_str = dates[current_idx]
            current_price = prices[current_idx]

            # --- Shared Logic Usage ---
            # 1. Compute Factors using analytics/factors.py
            trend = calculate_trend(price_slice) # UP/DOWN/NEUTRAL
            vol_annual = calculate_volatility(price_slice, window=30) # float
            rsi_val = calculate_rsi(price_slice, period=14)

            # 2. Detect Regime using nested/backbone.py logic
            # We must map our historical factors to the format infer_global_context expects
            features = {
                "spy_trend": trend.lower(), # expects lowercase
                "vix_level": 20.0, # Mock VIX for now as we only have SPY data in this context, or fetch historically?
                # Ideally we fetch historical VIX too, but for single-symbol test we might infer panic from vol
            }
            # Enhanced VIX proxy from vol
            # If vol > 30%, treat as high vix
            if vol_annual > 0.30: features["vix_level"] = 35.0
            elif vol_annual > 0.20: features["vix_level"] = 25.0
            else: features["vix_level"] = 15.0

            global_context: GlobalContext = infer_global_context(features)
            regime = global_context.global_regime # bull, bear, crab, shock

            # 3. Score using existing ScoringEngine
            # Map factors to scoring inputs (0.0-1.0 or similar)
            # We need to adapt our raw factors to the normalized inputs expected by ScoringEngine

            # Trend Score (0-100? or 0-1?)
            # ScoringEngine logic: linear sum of factor_value * weight.
            # Assuming factors are 0-1 or 0-100. Let's look at `_compute_factors` in previous implementation which used 0-1.
            # But `ScoringEngine` weights are typically small (0.4 etc), so output is 0-1.
            # Wait, `ConvictionTransform` expects `raw_score` ~ 0-100 range (mu=50).
            # So factors should be 0-100.

            trend_score = 100.0 if trend == "UP" else (0.0 if trend == "DOWN" else 50.0)

            vol_score = 50.0 # Default
            if vol_annual < 0.15: vol_score = 100.0 # Stable
            elif vol_annual > 0.30: vol_score = 0.0 # Volatile

            value_score = 50.0
            if rsi_val < 30: value_score = 100.0
            elif rsi_val > 70: value_score = 0.0

            factors_input = {
                "trend": trend_score,
                "volatility": vol_score,
                "value": value_score
            }

            score_res = self.scoring_engine.calculate_score(
                {
                    "symbol": symbol,
                    "factors": factors_input,
                    "liquidity_tier": "top"
                },
                regime # We might need to map 'bull'/'bear' to 'normal'/'panic' if schema differs
                # nested/backbone returns: bull, bear, crab, shock
                # regime_scoring expects: normal, high_vol, panic (keys in DEFAULT_WEIGHT_MATRIX)
                # Map:
                # shock -> panic
                # bear/bull/crab -> normal? Or maybe high_vol for bear?
            )

            # Regime Mapping Fix
            regime_mapped = 'normal'
            if regime == 'shock': regime_mapped = 'panic'
            elif regime == 'bear' or vol_annual > 0.20: regime_mapped = 'high_vol'

            # Re-run score with mapped regime if needed (ScoringEngine uses it to pick weights)
            score_res = self.scoring_engine.calculate_score(
                {
                    "symbol": symbol,
                    "factors": factors_input,
                    "liquidity_tier": "top"
                },
                regime_mapped
            )

            # 4. Conviction
            c_i = self.conviction_transform.get_conviction(
                score_res['raw_score'],
                regime_mapped,
                universe_median=None
            )

            # 5. State Machine
            if not in_trade:
                if c_i >= 0.70: # High conviction
                    in_trade = True
                    entry_details = {
                        "entryIndex": current_idx,
                        "entryTime": current_date_str,
                        "entryPrice": current_price,
                        "direction": "long",
                        "regime": regime_mapped,
                        "entryConviction": c_i
                    }

            else:
                should_exit = False
                if c_i < 0.5: should_exit = True

                pnl_pct = (current_price - entry_details['entryPrice']) / entry_details['entryPrice']
                if pnl_pct < -0.05: should_exit = True
                if pnl_pct > 0.08: should_exit = True

                if should_exit:
                    pnl_amount = (current_price - entry_details['entryPrice'])
                    return {
                        **entry_details,
                        "exitIndex": current_idx,
                        "exitTime": current_date_str,
                        "exitPrice": current_price,
                        "pnl": pnl_amount,
                        "exitConviction": c_i,
                        "done": False,
                        "nextCursor": dates[current_idx + 1] if current_idx + 1 < len(dates) else dates[-1]
                    }

            current_idx += 1

        if in_trade:
            pnl_amount = (prices[-1] - entry_details['entryPrice'])
            return {
                **entry_details,
                "exitIndex": len(dates)-1,
                "exitTime": dates[-1],
                "exitPrice": prices[-1],
                "pnl": pnl_amount,
                "exitConviction": 0.5,
                "done": True,
                "message": "Data ended during trade",
                "nextCursor": None
            }

        return {"done": True, "message": "End of data reached without finding another trade."}
