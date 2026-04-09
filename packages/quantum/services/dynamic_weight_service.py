"""
Dynamic Weight Service

Loads calibrated signal weights from the learning pipeline.
Called once at the start of suggestions_open, cached for the session.
"""

import logging
import os
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Feature flag — dynamic weights only applied when enabled
PROFIT_AGENT_RANKING = os.environ.get("PROFIT_AGENT_RANKING", "0") == "1"


class DynamicWeightService:
    """Loads and applies learned signal weight adjustments."""

    def __init__(self, supabase):
        self.supabase = supabase
        self._segment_cache: Optional[Dict[str, float]] = None
        self._strategy_cache: Optional[Dict[str, float]] = None

    def get_weight_overrides(self, user_id: str) -> Dict:
        """
        Load latest multiplier per segment_key from signal_weight_history
        and strategy-level weight reductions from strategy_adjustments.
        Cached in memory for the duration of the suggestions run.
        """
        if self._segment_cache is not None:
            return {
                "segments": self._segment_cache,
                "strategies": self._strategy_cache or {},
            }

        segments: Dict[str, float] = {}
        strategies: Dict[str, float] = {}

        try:
            # Latest multiplier per segment from signal_weight_history
            res = self.supabase.table("signal_weight_history") \
                .select("segment_key, new_multiplier") \
                .eq("user_id", user_id) \
                .order("created_at", desc=True) \
                .limit(100) \
                .execute()

            seen = set()
            for row in (res.data or []):
                key = row.get("segment_key")
                if key and key not in seen:
                    segments[key] = float(row.get("new_multiplier", 1.0))
                    seen.add(key)

            # Strategy-level weight reductions (unresolved only)
            res2 = self.supabase.table("strategy_adjustments") \
                .select("strategy, new_weight") \
                .eq("user_id", user_id) \
                .eq("action", "weight_reduce") \
                .eq("resolved", False) \
                .order("created_at", desc=True) \
                .limit(20) \
                .execute()

            seen_strat = set()
            for row in (res2.data or []):
                strat = row.get("strategy")
                if strat and strat not in seen_strat:
                    strategies[strat] = float(row.get("new_weight", 1.0))
                    seen_strat.add(strat)

        except Exception as e:
            logger.warning(f"[DYNAMIC_WEIGHTS] Failed to load overrides: {e}")

        self._segment_cache = segments
        self._strategy_cache = strategies

        if segments or strategies:
            logger.info(
                f"[DYNAMIC_WEIGHTS] Loaded {len(segments)} segment overrides, "
                f"{len(strategies)} strategy overrides"
            )

        return {"segments": segments, "strategies": strategies}

    def apply_to_score(self, base_score: float, strategy: str,
                       regime: str, dte: int) -> float:
        """
        Apply learned multiplier to a base score.
        Looks up segment_key, then strategy-level override.
        Returns adjusted score clamped to [0, 100].
        """
        if not PROFIT_AGENT_RANKING:
            return base_score

        if self._segment_cache is None:
            return base_score

        # Determine DTE bucket
        if dte <= 21:
            dte_bucket = "0-21"
        elif dte <= 35:
            dte_bucket = "21-35"
        elif dte <= 45:
            dte_bucket = "35-45"
        else:
            dte_bucket = "45+"

        # Try segment-specific multiplier
        segment_key = f"{strategy}|{regime}|{dte_bucket}"
        multiplier = self._segment_cache.get(segment_key, 1.0)

        # Layer on strategy-level override
        strat_mult = (self._strategy_cache or {}).get(strategy, 1.0)
        multiplier *= strat_mult

        adjusted = base_score * multiplier
        return max(0.0, min(100.0, adjusted))
