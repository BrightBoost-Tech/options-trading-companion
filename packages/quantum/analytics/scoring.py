from typing import List, Dict, Any, Optional
import math
from packages.quantum.common_enums import UnifiedScore, UnifiedScoreComponent, RegimeState

def calculate_unified_score(
    trade: Dict[str, Any],
    regime_snapshot: Dict[str, Any], # GlobalRegimeSnapshot or dict
    market_data: Optional[Dict[str, Any]] = None
) -> UnifiedScore:
    """
    Calculates the Unified Score (0-100) based on:
    UnifiedScore = EV - ExecutionCostExpected - RegimePenalty - GreekRiskPenalty
    """
    if market_data is None:
        market_data = {}

    # 1. Extract Core Metrics
    ev = trade.get('ev', 0.0)
    suggested_entry = trade.get('suggested_entry', 0.0)

    # Avoid division by zero
    cost_basis = suggested_entry if suggested_entry > 0.01 else 1.0

    # 2. Estimate Execution Cost (Drag)
    # Baseline: 1% of premium + fixed fee per leg
    # Real logic: use bid/ask spread if available
    bid_ask_spread_width = trade.get('bid_ask_spread', 0.0)
    if bid_ask_spread_width <= 0:
        # Fallback estimation
        bid_ask_spread_width = suggested_entry * 0.02 # 2% spread assumption

    num_legs = len(trade.get('legs', [])) or 1
    commission = num_legs * 0.65 # $0.65 per contract

    # Execution Cost = (Spread / 2) + Commission
    # Spread/2 is the "fair value" loss vs mid price
    exec_cost = (bid_ask_spread_width * 0.5) * 100 # x100 multiplier for contract size?
    # Usually suggested_entry is total premium per share ($1.50).
    # Spread is width per share ($0.10).
    # So exec cost per share is $0.05 + comms/100.

    exec_drag_per_share = (bid_ask_spread_width * 0.5) + (commission / 100.0)

    # Normalize EV to ROI % for scoring to keep it scale-invariant
    # EV is typically total expected profit per share ($0.20)

    # 3. Regime Penalty
    regime_state = RegimeState(regime_snapshot.get('state', 'normal'))
    regime_penalty = 0.0

    strategy_type = trade.get('strategy', 'unknown')

    # Example Penalties
    if regime_state == RegimeState.SHOCK:
        if 'credit_put' in strategy_type:
            regime_penalty += 0.50 # 50% penalty on ROI
        if 'debit_call' in strategy_type:
             regime_penalty += 0.20

    elif regime_state == RegimeState.ELEVATED:
        # Penalize buying premium (Vega Long)
        if 'debit' in strategy_type:
            regime_penalty += 0.15

    elif regime_state == RegimeState.SUPPRESSED:
        # Penalize selling premium (Vega Short)
        if 'credit' in strategy_type:
            regime_penalty += 0.15

    # 4. Greek Risk Penalty
    greek_penalty = 0.0
    gamma = abs(trade.get('gamma', 0.0))
    vega = trade.get('vega', 0.0)

    # Penalize high gamma (explosive risk)
    if gamma > 0.1:
        greek_penalty += gamma * 1.0

    # Penalize wrong-way Vega
    if regime_state == RegimeState.ELEVATED and vega > 0:
        greek_penalty += 0.10
    if regime_state == RegimeState.SUPPRESSED and vega < 0:
        greek_penalty += 0.10

    # 5. Synthesis
    # Convert everything to "Points"
    # Base Score = EV ROI * Scaling Factor

    ev_roi = ev / cost_basis if cost_basis else 0.0

    # Point Basis: 1% ROI = 1 Point? No, 1% ROI is small.
    # Let's say 10% ROI = 50 Points (Target).
    # ROI of 0.20 (20%) = 100 points.

    base_points = ev_roi * 500.0

    cost_points = (exec_drag_per_share / cost_basis) * 500.0

    regime_points = regime_penalty * 100.0 # 0.15 penalty = 15 points lost

    greek_points = greek_penalty * 100.0

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
