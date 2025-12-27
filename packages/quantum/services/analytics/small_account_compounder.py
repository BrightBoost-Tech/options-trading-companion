from typing import Dict, Any, List, Optional
import math
from pydantic import BaseModel

class SizingConfig(BaseModel):
    min_trade_size: float = 10.0  # Minimum dollar amount per trade
    max_position_pct: float = 0.10 # Hard cap 10%
    compounding_enabled: bool = False

class CapitalTier(BaseModel):
    name: str
    min_cap: float
    max_cap: float
    base_risk_pct: float
    max_trades: int
    selection_logic: str # "rank_top_n", "rank_select_compound"

class SmallAccountCompounder:
    """
    Implements tiered sizing and selection logic for accounts of varying sizes.
    Focuses on aggressive growth for small accounts while preserving capital.
    """

    TIERS = [
        CapitalTier(
            name="micro",
            min_cap=0,
            max_cap=1000,
            base_risk_pct=0.05,  # 5% risk for <$1k
            max_trades=3,        # Allow up to 3 trades to spread risk
            selection_logic="rank_select_compound"
        ),
        CapitalTier(
            name="small",
            min_cap=1000,
            max_cap=5000,
            base_risk_pct=0.03,  # 3% risk for $1k-$5k
            max_trades=4,
            selection_logic="rank_select_compound"
        ),
        CapitalTier(
            name="standard",
            min_cap=5000,
            max_cap=float('inf'),
            base_risk_pct=0.02,  # 2% standard
            max_trades=5,
            selection_logic="rank_top_n"
        )
    ]

    @staticmethod
    def get_tier(capital: float) -> CapitalTier:
        for tier in SmallAccountCompounder.TIERS:
            if tier.min_cap <= capital < tier.max_cap:
                return tier
        return SmallAccountCompounder.TIERS[-1] # Fallback to largest

    @staticmethod
    def calculate_variable_sizing(
        candidate: Dict[str, Any],
        capital: float,
        tier: CapitalTier,
        regime: str = "normal",
        compounding: bool = False
    ) -> Dict[str, Any]:
        """
        Calculates risk % and budget based on score, regime, and tier.
        """
        score = candidate.get("score", 50)

        # Base Risk from Tier
        risk_pct = tier.base_risk_pct

        # If compounding is OFF, and account is small/micro, reduce risk to safer levels
        # Standard safety is 2% (0.02)
        if not compounding and tier.name in ["micro", "small"]:
            risk_pct = 0.02 # Force standard risk behavior

        # Score Multiplier:
        # Score 50 -> 0.8x
        # Score 75 -> 1.0x
        # Score 90 -> 1.2x
        score_mult = 0.8 + ((score - 50) / 50.0) * 0.4
        score_mult = max(0.8, min(1.2, score_mult))

        # Regime Multiplier
        regime_mult = 1.0
        if regime == "suppressed":
            regime_mult = 0.9
        elif regime == "elevated":
            regime_mult = 0.8 # Reduce size in high vol due to whippiness
        elif regime == "shock":
            regime_mult = 0.5 # Halve size in crash

        # Compounding Boost (if enabled and small account)
        compounding_mult = 1.0
        if compounding and tier.name in ["micro", "small"]:
            # Boost logic: If score is high (>80), allow slightly more risk (1.2x)
            if score >= 80:
                compounding_mult = 1.2

        final_risk_pct = risk_pct * score_mult * regime_mult * compounding_mult

        # Calculate Dollar Budget
        risk_budget = capital * final_risk_pct

        return {
            "risk_pct": final_risk_pct,
            "risk_budget": risk_budget,
            "tier_name": tier.name,
            "multipliers": {
                "score": score_mult,
                "regime": regime_mult,
                "compounding": compounding_mult
            }
        }

    @staticmethod
    def rank_and_select(
        candidates: List[Dict[str, Any]],
        capital: float,
        risk_budget: float,
        config: SizingConfig = SizingConfig(),
        regime: str = "normal"
    ) -> List[Dict[str, Any]]:
        """
        Selects candidates based on capital tier rules.
        Respects the global risk budget.
        """
        tier = SmallAccountCompounder.get_tier(capital)

        # 1. Sort by Score (Desc)
        sorted_candidates = sorted(
            candidates,
            key=lambda x: x.get("score", 0),
            reverse=True
        )

        selected = []
        current_risk_usage = 0.0

        # Determine max trades for this session
        limit = tier.max_trades

        # Assume compounding mode from config if passed, or default to False (safe)
        compounding = config.compounding_enabled

        for cand in sorted_candidates:
            if len(selected) >= limit:
                break

            if current_risk_usage >= risk_budget:
                break

            # Basic checks
            score = cand.get("score", 0)
            if score < 50: # Minimum quality floor
                continue

            # Estimate risk for this candidate
            sizing = SmallAccountCompounder.calculate_variable_sizing(
                candidate=cand,
                capital=capital,
                tier=tier,
                regime=regime,
                compounding=compounding
            )
            estimated_risk = sizing["risk_budget"]

            # Check if this single trade fits in remaining budget
            if current_risk_usage + estimated_risk > risk_budget:
                # Can we partial fill?
                # For selection, we might skip or stop.
                # Let's stop to be conservative.
                # Or skip and see if smaller trades fit?
                # Greedy: stop.
                break

            # Add to selection
            selected.append(cand)
            current_risk_usage += estimated_risk

        return selected
