import logging
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
from packages.quantum.observability.feature_flags import is_iv_rank_none_routing_enabled

logger = logging.getLogger(__name__)

MIN_TRADES = 20
LEAKAGE_FLOOR = 1.0
SHRINKAGE_CONST = 30.0
Z_SCORE_THRESHOLD = 1.0


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

        # NOTE: _get_performance_multipliers now returns a mix of keys:
        # - (strategy, window) for legacy compatibility
        # - "strategy:window:regime" for V3 specificity
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
            # Priority: Specific Regime > Unknown Regime > Generic Tuple

            # Using 'paper_trading' as the window for portfolio positions
            window = "paper_trading"

            regime_key = f"{strategy}:{window}:{current_regime}"
            unknown_regime_key = f"{strategy}:{window}:unknown"
            generic_key = (strategy, window)

            m_perf = perf_mult_map.get(regime_key)
            if m_perf is None:
                m_perf = perf_mult_map.get(unknown_regime_key)
            if m_perf is None:
                m_perf = perf_mult_map.get(generic_key, 1.0)

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
          - For each suggestion, find best matching key.
          - Apply multiplier to 'score' and/or 'otc_score'.
          - Clamp result [0.5 * base, 1.5 * base].
        """
        multipliers = self._get_performance_multipliers(user_id)
        if not multipliers:
            return suggestions

        for s in suggestions:
            # Determine keys
            strategy = s.get("strategy") or s.get("type") or "unknown"
            window = s.get("window") or "unknown"
            regime = s.get("regime") or "unknown"

            regime_key = f"{strategy}:{window}:{regime}"
            unknown_regime_key = f"{strategy}:{window}:unknown"
            generic_key = (strategy, window)

            w = multipliers.get(regime_key)
            if w is None:
                w = multipliers.get(unknown_regime_key)
            if w is None:
                w = multipliers.get(generic_key, 1.0)

            if w == 1.0:
                continue

            # Apply to score
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
            if "probability_of_profit" in s and s["probability_of_profit"] is not None:
                p = float(s["probability_of_profit"])
                p_adj = p * w
                p_final = max(p * 0.5, min(p * 1.5, p_adj))
                p_final = min(1.0, max(0.0, p_final))
                s["probability_of_profit"] = p_final

        return suggestions

    def _compute_raw_score_helper(self, pos: PositionDescriptor, regime: str) -> Optional[float]:
        try:
            # #115 PR-B-2: when IV_RANK_NONE_ROUTING_ENABLED and iv_rank
            # is None, return None so the caller routes the position to
            # conviction=0.5 (neutral) rather than scoring against a
            # fabricated 50.0 input. Trend/value placeholders here are a
            # separate concern (out of scope for #115). Flag OFF
            # preserves the legacy silent fallback verbatim.
            if is_iv_rank_none_routing_enabled() and pos.iv_rank is None:
                logger.info(
                    "conviction_service: pos.iv_rank=None for %s, returning None "
                    "(routes caller to conviction=0.5)",
                    pos.symbol,
                )
                return None
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

    def _get_performance_multipliers(self, user_id: str) -> Dict[Any, float]:
        """
        Returns a dict mapping keys -> weight multiplier (float).
        Keys can be:
          - (strategy, window)  (Legacy/Fallback)
          - f"{strategy}:{window}:{regime}" (V3 Specific)
        """
        if not self.supabase or not user_id:
            return {}

        multipliers = {}
        v3_success = False

        # Attempt V3 Logic: Query learning_performance_summary_v3
        try:
            response = self.supabase.table("learning_performance_summary_v3")\
                .select("*")\
                .eq("user_id", user_id)\
                .execute()

            rows = response.data or []
            if rows:
                v3_success = True
                multipliers = self._compute_v3_multipliers(rows)
        except Exception as e:
            # If query fails (e.g. view missing), swallow error and fallback
            # print(f"[ConvictionService] V3 View Query Failed: {e}")
            pass

        if not v3_success:
             # Fallback to legacy logic
             multipliers = self._get_legacy_multipliers(user_id)

        return multipliers

    def _compute_v3_multipliers(self, rows: List[Dict]) -> Dict[Any, float]:
        multipliers = {}

        for row in rows:
            strategy = row.get("strategy") or "unknown"
            window = row.get("window") or "unknown"
            regime = row.get("regime") or "unknown"

            total_trades = row.get("total_trades") or 0
            if total_trades < MIN_TRADES:
                # Explicitly set to 1.0 to prevent inheritance from generic fallbacks
                self._store_v3_multiplier(multipliers, strategy, window, regime, 1.0)
                continue

            # Check confidence interval if data available
            avg_pnl = row.get("avg_realized_pnl")
            std_pnl = row.get("std_realized_pnl")

            if avg_pnl is not None and std_pnl is not None:
                avg_pnl = float(avg_pnl)
                std_pnl = float(std_pnl)
                se = std_pnl / math.sqrt(total_trades)
                # If signal is weak (within Z*SE of zero), treat as noise -> 1.0
                if abs(avg_pnl) < Z_SCORE_THRESHOLD * se:
                    # We store 1.0 explicitly so it overrides defaults
                    m = 1.0
                    self._store_v3_multiplier(multipliers, strategy, window, regime, m)
                    continue

            # Calculate EV-based multiplier.
            # #115c (observability): pre-fix `or 0.0` arithmetically
            # collapsed to a neutral 1.0 multiplier when either field
            # was None — same outcome as the explicit weak-signal
            # branch above (line ~290). Make the path explicit so
            # missing-data fallbacks surface in logs instead of
            # masquerading as "real signal that happens to be zero."
            raw_leakage = row.get("avg_ev_leakage")
            raw_predicted = row.get("avg_predicted_ev")
            if raw_leakage is None or raw_predicted is None:
                logger.info(
                    "conviction_service: leakage/predicted_ev missing for "
                    "%s/%s/%s — storing neutral 1.0 multiplier",
                    strategy, window, regime,
                )
                self._store_v3_multiplier(multipliers, strategy, window, regime, 1.0)
                continue
            avg_leakage = float(raw_leakage)
            avg_predicted = float(raw_predicted)

            # leakage = realized - predicted
            # raw = 1 + (leakage / basis)
            # basis = max(abs(predicted), LEAKAGE_FLOOR)
            basis = max(abs(avg_predicted), LEAKAGE_FLOOR)
            raw_adjustment = avg_leakage / basis
            raw_multiplier = 1.0 + raw_adjustment

            # Shrinkage: n / (n + 30)
            shrink_factor = total_trades / (total_trades + SHRINKAGE_CONST)

            # Multiplier = 1 + shrink * (raw - 1)
            final_multiplier = 1.0 + shrink_factor * (raw_multiplier - 1.0)

            # Clamp [0.7, 1.3]
            final_multiplier = max(0.7, min(1.3, final_multiplier))

            self._store_v3_multiplier(multipliers, strategy, window, regime, final_multiplier)

        return multipliers

    def _store_v3_multiplier(self, multipliers: Dict[Any, float], strategy: str, window: str, regime: str, val: float):
        # Store regime-specific key
        regime_key = f"{strategy}:{window}:{regime}"
        multipliers[regime_key] = val

        # Store legacy tuple key if regime is 'normal' (as a representative proxy)
        # OR if we don't have one yet.
        # But 'normal' is preferred for compatibility.
        legacy_key = (strategy, window)

        if regime == "normal":
            multipliers[legacy_key] = val
        elif legacy_key not in multipliers:
            # If we haven't seen 'normal' yet, store this as placeholder.
            # 'normal' will overwrite later if encountered.
            multipliers[legacy_key] = val

    def _get_legacy_multipliers(self, user_id: str) -> Dict[tuple, float]:
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

                # Skip if insufficient sample size — checked BEFORE the
                # avg_return None-check below so we don't log a missing
                # value for buckets that wouldn't be considered anyway.
                if trade_count < 5:
                    continue

                # #115c (observability): pre-fix `or 0.0` produced
                # pnl_edge=0 ("no edge") indistinguishable from a real
                # zero-edge result when avg_return was NULL despite
                # sufficient sample size. Skip rather than fabricate.
                raw_avg_return = row.get("avg_return")
                if raw_avg_return is None:
                    logger.info(
                        "conviction_service: avg_return is None for legacy "
                        "(%s, %s) despite trade_count=%s — skipping bucket",
                        strat, win_key, trade_count,
                    )
                    continue
                avg_pnl_val = float(raw_avg_return)

                base_val = 1.0
                pnl_edge = avg_pnl_val

                # Clamp edge: max(-0.3, min(0.5, pnl_edge))
                pnl_clamped = max(-0.3, min(0.5, pnl_edge))

                final_weight = base_val + pnl_clamped

                # Global safety clamp: keep multiplier between 0.7x and 1.5x
                final_weight = max(0.7, min(1.5, final_weight))

                multiplier_map[lookup_key] = final_weight

            return multiplier_map

        except Exception as err:
            print(f"[ConvictionService] Error calculating legacy multipliers: {err}")
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
