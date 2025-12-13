from typing import List, Dict, Any, Optional
import math
from packages.quantum.common_enums import UnifiedScore, UnifiedScoreComponent, RegimeState

def calculate_unified_score(
    trade: Dict[str, Any],
    regime_snapshot: Dict[str, Any], # GlobalRegimeSnapshot or dict
    market_data: Optional[Dict[str, Any]] = None,
    execution_drag_estimate: float = 0.0
) -> UnifiedScore:
    """
    Calculates the Unified Score (0-100) based on:
    UnifiedScore = EV - ExecutionCostExpected - RegimePenalty - GreekRiskPenalty

    All components are normalized to 'points' where 1 Point approx 0.02% ROI impact,
    scaled to a 0-100 score.
    """
    if market_data is None:
        market_data = {}

    # 1. Extract Core Metrics
    ev = trade.get('ev', 0.0)
    suggested_entry = trade.get('suggested_entry', 0.0)

    # Avoid division by zero
    cost_basis = suggested_entry if suggested_entry > 0.01 else 1.0

    # EV ROI
    ev_roi = ev / cost_basis

    # 2. Expected Execution Cost (Drag)
    # Use provided estimate (from history) or calculate from current spread
    bid_ask_spread_width = trade.get('bid_ask_spread', 0.0)

    # Cost per share
    estimated_cost_per_share = execution_drag_estimate

    if bid_ask_spread_width > 0:
        # If live spread is known, use it: (Spread/2) + Comms
        live_cost = (bid_ask_spread_width * 0.5) + 0.0065 # $0.65 contract / 100
        # Use the worse of historical or live
        estimated_cost_per_share = max(estimated_cost_per_share, live_cost)
    elif estimated_cost_per_share == 0:
         # Fallback
         estimated_cost_per_share = cost_basis * 0.01 # 1% slippage assumption

    # Cost ROI Impact
    cost_roi = estimated_cost_per_share / cost_basis

    # 3. Regime Penalty (ROI Impact)
    regime_state = RegimeState(regime_snapshot.get('state', 'normal'))
    regime_penalty_roi = 0.0

    strategy_type = trade.get('strategy', 'unknown')

    # Example Penalties
    if regime_state == RegimeState.SHOCK:
        if 'credit_put' in strategy_type:
            regime_penalty_roi += 0.10 # 10% ROI penalty
        if 'debit_call' in strategy_type:
             regime_penalty_roi += 0.05

    elif regime_state == RegimeState.ELEVATED:
        if 'debit' in strategy_type:
            regime_penalty_roi += 0.03

    elif regime_state == RegimeState.SUPPRESSED:
        if 'credit' in strategy_type:
            regime_penalty_roi += 0.03

    # 4. Greek Risk Penalty (ROI Impact)
    greek_penalty_roi = 0.0
    gamma = abs(trade.get('gamma', 0.0))
    vega = trade.get('vega', 0.0)

    # Penalize high gamma
    if gamma > 0.1:
        greek_penalty_roi += gamma * 0.1

    # Penalize wrong-way Vega
    if regime_state == RegimeState.ELEVATED and vega > 0:
        greek_penalty_roi += 0.02
    if regime_state == RegimeState.SUPPRESSED and vega < 0:
        greek_penalty_roi += 0.02

    # 5. Synthesis: Unified Score = EV - Cost - Regime - Risk
    # We scale ROI to Score (0-100).
    # Let's say ROI 20% (0.20) = 100 Score.
    SCALING_FACTOR = 500.0

    base_points = ev_roi * SCALING_FACTOR
    cost_points = cost_roi * SCALING_FACTOR
    regime_points = regime_penalty_roi * SCALING_FACTOR
    greek_points = greek_penalty_roi * SCALING_FACTOR

    final_score = base_points - cost_points - regime_points - greek_points

    # Clamp
    final_score = max(0.0, min(100.0, final_score))

    # Badges
    badges = generate_badges(trade, regime_state, ev_roi)

    return UnifiedScore(
        score=final_score,
        components=UnifiedScoreComponent(
            ev=base_points,
            execution_cost=cost_points,
            regime_penalty=regime_points,
            greek_penalty=greek_points,
            total_score=final_score
        ),
        badges=badges,
        regime=regime_state
    )

def generate_badges(trade: Dict[str, Any], regime: RegimeState, roi: float) -> List[str]:
    badges = []

    if roi > 0.30:
        badges.append("High ROI")

    iv_rank = trade.get('iv_rank', 50)
    if regime == RegimeState.ELEVATED and trade.get('type') == 'credit' and iv_rank > 60:
         badges.append("Vol Premium Harvest")

    if regime == RegimeState.SUPPRESSED and trade.get('type') == 'debit' and iv_rank < 30:
        badges.append("Cheap Gamma")

    return badges
