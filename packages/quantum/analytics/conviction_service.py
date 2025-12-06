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
    ) -> Dict[str, float]:
        """
        Returns {underlying_symbol: conviction in [0.0, 1.0]} for the current portfolio.

        regime_context expected keys:
          - "current_regime": str (default "normal")
          - "universe_median": float (default 0.0)
        """

        conviction_map: Dict[str, float] = {}

        # 1. Batch-level multipliers (stubs for now)
        m_disc = self._get_discipline_multiplier()
        perf_mult_map = self._get_performance_multipliers(regime_context)

        current_regime = str(regime_context.get("current_regime", "normal"))
        universe_median = float(regime_context.get("universe_median", 0.0))

        for pos in positions:
            symbol = pos.underlying or pos.symbol
            strategy = pos.strategy_type or "other"

            # 2. Compute raw score and base conviction from live scoring
            # We construct minimal symbol_data from available info (iv_rank)
            raw_score = self._compute_raw_score_helper(pos, current_regime)

            # If scoring returns None / error (or no factors), default to neutral 0.5
            if raw_score is None:
                conviction_map[symbol] = 0.5
                continue

            if not self._check_direction_alignment(pos, raw_score):
                conviction_map[symbol] = 0.0
                continue

            # Transform raw score to conviction
            # We instantiate a temporary transform helper if needed, or use a cached one?
            # ConvictionTransform is lightweight.
            # Using default profiles for now.
            ct = ConvictionTransform(DEFAULT_REGIME_PROFILES)
            base_conviction = ct.get_conviction(
                raw_score=raw_score,
                regime=current_regime,
                universe_median=universe_median,
            )

            # 3. Performance multiplier, keyed by (regime, strategy)
            # Use 'other' if strategy not found
            key = (current_regime, strategy)
            if key not in perf_mult_map:
                key = (current_regime, "other")

            m_perf = perf_mult_map.get(key, 1.0)

            c_final = base_conviction * m_perf * m_disc
            # Clamp
            conviction_map[symbol] = max(0.0, min(1.0, c_final))

        return conviction_map

    def _compute_raw_score_helper(self, pos: PositionDescriptor, regime: str) -> Optional[float]:
        """
        Helper to run existing scoring pipeline for a single position.
        Constructs a minimal symbol_data dict using pos.iv_rank as a factor.
        """
        try:
            # Construct factors
            # If we only have iv_rank, we treat it as 'volatility' factor.
            # We might mock 'trend' and 'value' as 50 (neutral) if unknown.
            factors = {
                "trend": 50.0,
                "value": 50.0,
                "volatility": pos.iv_rank if pos.iv_rank is not None else 50.0
            }

            symbol_data = {
                "symbol": pos.symbol,
                "factors": factors,
                "catalyst_window": "none", # Unknown without more data
                "liquidity_tier": "mid"    # Assume mid
            }

            result = self.scoring.calculate_score(symbol_data, regime)
            return result.get("raw_score")
        except Exception:
            return None

    def _check_direction_alignment(self, position: PositionDescriptor, raw_score: float) -> bool:
        """
        Ensure we don't assign high conviction when the signal is clearly against the trade direction.
        Example: long debit_call with very bearish score -> return False.

        Assuming raw_score is roughly 0-100.
        Neutral is ~50.
        """

        strategy = position.strategy_type
        # Raw score is 0-100.
        # Bullish: > 50? Or > 40?
        # Bearish: < 50?

        # NOTE: The prompt example used raw_score > -0.5, implying -1 to 1 scale?
        # But ScoringEngine produces linear sum of weights * factors (0-100).
        # So I should assume 0-100 scale. Neutral ~50.

        # Bullish strategies
        if strategy in ("debit_call", "credit_put", "long_stock", "bull_put_spread", "long_call"):
            return raw_score > 40.0 # Allow slightly bearish score but not terrible

        # Bearish strategies
        if strategy in ("debit_put", "credit_call", "short_stock", "bear_call_spread", "long_put"):
            return raw_score < 60.0 # Allow slightly bullish score

        # Neutral / range-bound (condors, strangles)
        if strategy in ("iron_condor", "short_strangle", "butterfly"):
            # Should be "middle" score?
            return 30.0 < raw_score < 70.0

        # Unknown / other -> allow through
        return True

    def _get_performance_multipliers(self, regime_context: Dict[str, Any]) -> Dict[tuple, float]:
        """
        For now, return a simple stub:
          - (regime, strategy_type) -> multiplier in [0.5, 1.0].
        Later, derive from learning_feedback_loops.
        """
        if not self.supabase:
            return {}

        # TODO: query learning_feedback_loops for recent avg pnl_realized per (regime, strategy_type)
        # For now, return all 1.0.
        return {}

    def _get_discipline_multiplier(self) -> float:
        """
        For now, return 1.0. Later, derive from discipline_score_per_user.
        """
        if not self.supabase:
            return 1.0

        # TODO: query discipline_score_per_user for the current user and map to {1.0, 0.5, 0.0}.
        return 1.0
