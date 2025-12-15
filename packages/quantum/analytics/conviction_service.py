from typing import Dict, List, Optional, Any
from dataclasses import dataclass
import math

from supabase import Client

from .regime_scoring import ConvictionTransform, ScoringEngine
from .regime_integration import (
    DEFAULT_REGIME_PROFILES,
    map_market_regime,
    DEFAULT_WEIGHT_MATRIX,
    DEFAULT_CATALYST_PROFILES,
    DEFAULT_LIQUIDITY_SCALAR
)


@dataclass
class PositionDescriptor:
    symbol: str
    underlying: str
    strategy_type: str  # e.g. 'debit_call', 'iron_condor', 'other'
    direction: str      # 'long' | 'short' | 'neutral'
    # Optional context specific to this position
    iv_rank: Optional[float] = None


class ConvictionService:
    """
    Computes live, learning-aware conviction for the current portfolio.

    C_final = C_live_signal * M_performance * M_discipline
    """

    def __init__(self, scoring_engine: Optional[ScoringEngine] = None, supabase: Optional[Client] = None):
        if scoring_engine:
            self.scoring = scoring_engine
        else:
            self.scoring = ScoringEngine(
                DEFAULT_WEIGHT_MATRIX,
                DEFAULT_CATALYST_PROFILES,
                DEFAULT_LIQUIDITY_SCALAR
            )
        self.supabase = supabase

    def get_portfolio_conviction(
        self,
        positions: List[PositionDescriptor],
        regime_context: Dict[str, Any],
        user_id: Optional[str] = None
    ) -> Dict[str, float]:
        """
        Returns {underlying_symbol: conviction in [0.0, 1.0]} for the current portfolio.

        regime_context expected keys:
          - "current_regime": str (default "normal")
          - "universe_median": float (default 0.0)
        """

        conviction_map: Dict[str, float] = {}

        # 1. Batch-level multipliers
        m_disc = self._get_discipline_multiplier(user_id) if user_id else 1.0

        # NOTE: _get_performance_multipliers now uses user_id and returns (strategy, window) keys.
        # The existing portfolio logic used (regime, strategy).
        # We will attempt to use the "paper_trading" window as a proxy for general performance if user_id is present,
        # otherwise we default to 1.0.
        perf_mult_map = {}
        if user_id:
             perf_mult_map = self._get_performance_multipliers(user_id)

        current_regime = str(regime_context.get("current_regime", "normal"))
        universe_median = float(regime_context.get("universe_median", 0.0))

        for pos in positions:
            symbol = pos.underlying or pos.symbol
            strategy = pos.strategy_type or "other"

            # 2. Compute raw score and base conviction from live scoring
            raw_score = self._compute_raw_score_helper(pos, current_regime)

            if raw_score is None:
                conviction_map[symbol] = 0.5
                continue

            if not self._check_direction_alignment(pos, raw_score):
                conviction_map[symbol] = 0.0
                continue

            # Transform raw score to conviction
            ct = ConvictionTransform(DEFAULT_REGIME_PROFILES)
            base_conviction = ct.get_conviction(
                raw_score=raw_score,
                regime=current_regime,
                universe_median=universe_median,
            )

            # 3. Performance multiplier
            # We try to look up performance for this strategy in 'paper_trading' window as a baseline
            key = (strategy, "paper_trading")
            m_perf = perf_mult_map.get(key, 1.0)

            # If not found, maybe try "all" or generic if we had it. For now default to 1.0.

            c_final = base_conviction * m_perf * m_disc
            # Clamp
            conviction_map[symbol] = max(0.0, min(1.0, c_final))

        return conviction_map

    def adjust_suggestion_scores(self, suggestions: List[Dict], user_id: str) -> List[Dict]:
        """
        Applies learning feedback multipliers to a list of suggestions or candidates.
        Modifies the list in-place and returns it.

        Logic:
          - Fetch multipliers for user.
          - For each suggestion, find (strategy, window) key.
          - Apply multiplier to 'score' and/or 'otc_score'.
          - Clamp result [0.5 * base, 1.5 * base].
        """
        multipliers = self._get_performance_multipliers(user_id)
        if not multipliers:
            return suggestions

        for s in suggestions:
            # Determine keys
            # Candidates from scanner use 'type', suggestions use 'strategy'.
            strategy = s.get("strategy") or s.get("type") or "unknown"
            # Normalize strategy key if needed? We assume DB has same keys.
            # Usually scanner produces human readable types "Debit Call Spread".
            # While DB might store "debit_call_spread" or similar if normalized.
            # But paper_endpoints uses `infer_strategy_key_from_suggestion` which normalizes.
            # Here we might have raw strings.
            # Ideally we'd normalize, but for now we try raw match.
            # NOTE: Phase 1 migration implies paper_endpoints stores keys.

            # Window
            window = s.get("window") or "unknown"
            # Midday scanner candidates don't have 'window' set yet in some flows,
            # but run_midday_cycle sets it later.
            # If we call this on candidates inside run_midday_cycle, we might need to pass window or inject it.
            # Actually run_midday_cycle doesn't set window on candidates, only on final suggestions.
            # So if we adjust candidates, window is "unknown".
            # We should probably pass a default window if missing?
            # Or rely on caller to set it.

            # If s is a suggestion dict, it has window.
            # If s is a candidate, we might need to infer.
            # Let's try "midday_entry" if missing and we are in that context?
            # But here we don't know context.
            # We'll use "unknown" or s.get("window").
            # If caller didn't set window, we can't map.

            key = (strategy, window)
            w = multipliers.get(key, 1.0)

            if w == 1.0:
                continue

            # Apply to score
            # Score keys: 'score', 'otc_score', 'probability_of_profit' (0-1, distinct from score)
            # We focus on 'score' (0-100) and 'otc_score'.

            for score_key in ["score", "otc_score"]:
                if score_key in s and s[score_key] is not None:
                    base = float(s[score_key])
                    adjusted = base * w
                    # Clamp [0.5x, 1.5x] relative to base
                    lower = base * 0.5
                    upper = base * 1.5
                    final = max(lower, min(upper, adjusted))
                    # Also clamp to global bounds if needed (e.g. 0-100)
                    if base <= 100:
                         final = min(100.0, final)

                    s[score_key] = final

            # Special case: Morning suggestions use probability_of_profit (0-1)
            # If we want to bias that:
            if "probability_of_profit" in s and s["probability_of_profit"] is not None:
                p = float(s["probability_of_profit"])
                p_adj = p * w
                p_final = max(p * 0.5, min(p * 1.5, p_adj))
                p_final = min(1.0, max(0.0, p_final))
                s["probability_of_profit"] = p_final

        return suggestions

    def _compute_raw_score_helper(self, pos: PositionDescriptor, regime: str) -> Optional[float]:
        try:
            factors = {
                "trend": 50.0,
                "value": 50.0,
                "volatility": pos.iv_rank if pos.iv_rank is not None else 50.0
            }

            symbol_data = {
                "symbol": pos.symbol,
                "factors": factors,
                "catalyst_window": "none",
                "liquidity_tier": "mid"
            }

            result = self.scoring.calculate_score(symbol_data, regime)
            return result.get("raw_score")
        except Exception:
            return None

    def _check_direction_alignment(self, position: PositionDescriptor, raw_score: float) -> bool:
        strategy = position.strategy_type
        if strategy in ("debit_call", "credit_put", "long_stock", "bull_put_spread", "long_call"):
            return raw_score > 40.0
        if strategy in ("debit_put", "credit_call", "short_stock", "bear_call_spread", "long_put"):
            return raw_score < 60.0
        if strategy in ("iron_condor", "short_strangle", "butterfly"):
            return 30.0 < raw_score < 70.0
        return True

    def _get_performance_multipliers(self, user_id: str) -> Dict[tuple, float]:
        """
        Returns a dict mapping (strategy, window) -> weight multiplier (float)
        based on learning_feedback_loops rows for the user.
        """
        if not self.supabase or not user_id:
            return {}

        try:
            # Query learning_feedback_loops for realized PnL analysis
            # We retrieve all records for the user
            response = self.supabase.table("learning_feedback_loops")\
                .select("*")\
                .eq("user_id", user_id)\
                .execute()

            rows = response.data or []
            multiplier_map = {}

            for row in rows:
                strat = row.get("strategy") or "unknown"
                win_key = row.get("window") or "unknown"
                lookup_key = (strat, win_key)

                trade_count = row.get("total_trades") or 0
                avg_pnl_val = float(row.get("avg_return") or 0.0)

                # Skip if insufficient sample size
                if trade_count < 5:
                    continue

                base_val = 1.0
                pnl_edge = avg_pnl_val

                # Clamp edge: max(-0.3, min(0.5, pnl_edge))
                # Note: pnl_edge is dollar-based (usually).
                # This clamping logic effectively limits the impact of large PnL swings.
                pnl_clamped = max(-0.3, min(0.5, pnl_edge))

                final_weight = base_val + pnl_clamped

                # Global safety clamp: keep multiplier between 0.7x and 1.5x
                final_weight = max(0.7, min(1.5, final_weight))

                multiplier_map[lookup_key] = final_weight

            return multiplier_map

        except Exception as err:
            print(f"[ConvictionService] Error calculating multipliers: {err}")
            return {}

    def _get_discipline_multiplier(self, user_id: str) -> float:
        if not self.supabase or not user_id:
            return 1.0

        try:
            # Query discipline_score_per_user for the current user
            res = self.supabase.table("discipline_score_per_user")\
                .select("discipline_score")\
                .eq("user_id", user_id)\
                .execute()

            rows = res.data or []
            if not rows:
                return 1.0

            score = rows[0].get("discipline_score")
            if score is None:
                return 1.0

            score = float(score)

            # Map to multiplier
            if score >= 0.8:
                return 1.0
            elif score >= 0.5:
                return 0.5
            else:
                return 0.0

        except Exception as e:
            # Log debug message (print for now as we don't have logger here)
            print(f"[ConvictionService] Failed to fetch discipline score: {e}")
            return 1.0
