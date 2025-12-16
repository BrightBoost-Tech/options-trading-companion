from typing import List, Dict, Any, Optional
import math
from packages.quantum.common_enums import UnifiedScore, UnifiedScoreComponent, RegimeState

CONTRACT_MULTIPLIER = 100.0

def to_contract_dollars(per_share: float | None) -> float:
    try:
        v = float(per_share or 0.0)
    except Exception:
        return 0.0
    return v * CONTRACT_MULTIPLIER

def calculate_unified_score(
    trade: Dict[str, Any],
    regime_snapshot: Dict[str, Any], # GlobalRegimeSnapshot or dict
    market_data: Optional[Dict[str, Any]] = None,
    execution_drag_estimate: float = 0.0,
    num_legs: Optional[int] = None,
    entry_cost: Optional[float] = None
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
    ev = trade.get('ev', 0.0) # Contract dollars
    suggested_entry = trade.get('suggested_entry', 0.0) # Per-share dollars

    # Normalize entry cost to Contract Dollars for ROI calculation
    if entry_cost is None:
        entry_cost = suggested_entry

    # -----------------------------------------------------
    # ROI Denominator Logic (Risk Basis vs Premium Basis)
    # -----------------------------------------------------
    roi_mode = "premium_basis"
    denom = 100.0

    # Prefer risk basis if available
    max_loss = trade.get("max_loss") or trade.get("max_loss_per_contract")
    collateral = trade.get("collateral_required_per_contract") or trade.get("collateral_per_contract")

    # Check for risk basis (max_loss or collateral)
    # Use the first positive value found
    risk_basis = None
    if max_loss is not None:
        try:
            if float(max_loss) > 0:
                risk_basis = float(max_loss)
        except (ValueError, TypeError):
            pass

    if risk_basis is None and collateral is not None:
        try:
            if float(collateral) > 0:
                risk_basis = float(collateral)
        except (ValueError, TypeError):
            pass

    if risk_basis is not None:
        denom = float(risk_basis)
        roi_mode = "risk_basis"
    else:
        # Fallback to premium/contract basis
        entry_share = abs(float(entry_cost or 0.0))
        denom = max(1e-6, entry_share * 100.0) # Contract dollars
        roi_mode = "premium_basis"

    # Use 'denom' as the cost basis for ROI calculation
    cost_basis = denom

    # EV ROI (Contract $ / Risk Basis $)
    ev_roi = float(ev) / cost_basis

    # 2. Expected Execution Cost (Drag)
    # Use provided estimate (from history) or calculate from current spread

    # Infer defaults
    if num_legs is None:
        legs = trade.get('legs', [])
        num_legs = len(legs) if legs else 1

    bid_ask_spread_width = trade.get('bid_ask_spread', 0.0)

    # Calculate Proxy Cost (PER SHARE first)
    # Formula: (Entry * Spread% * 0.5) + (Legs * 0.0065)
    proxy_cost_share = 0.0

    # Try to use bid_ask_spread_pct from market_data first
    spread_pct = market_data.get('bid_ask_spread_pct')
    if spread_pct is not None and (entry_cost or 0) > 0:
        width = (entry_cost or 0) * spread_pct
        proxy_cost_share = (width * 0.5) + (num_legs * 0.0065)
    elif bid_ask_spread_width > 0:
         # Fallback to pre-calculated width
         # Note: bid_ask_spread in trade is usually width
         proxy_cost_share = (bid_ask_spread_width * 0.5) + (num_legs * 0.0065)
    else:
         # Fallback if no spread info
         proxy_cost_share = ((entry_cost or 0) * 0.01 * 0.5) + (num_legs * 0.0065)

    # Convert Proxy Cost to Contract Dollars
    proxy_cost_contract = to_contract_dollars(proxy_cost_share)

    # Determine Final Execution Cost (Contract Dollars)
    # execution_drag_estimate must be in contract dollars
    final_execution_cost = max(proxy_cost_contract, execution_drag_estimate or 0.0)

    # Cost ROI Impact (Contract $ / Contract $)
    cost_roi = final_execution_cost / cost_basis

    # 3. Regime Penalty (ROI Impact)
    regime_state = RegimeState(regime_snapshot.get('state', 'normal'))
    regime_penalty_roi = 0.0

    raw_strategy = trade.get("strategy_key") or trade.get("strategy") or ""
    strategy_type = str(raw_strategy).lower()

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
            total_score=final_score,
            roi_mode=roi_mode,
            roi_denom=denom
        ),
        badges=badges,
        regime=regime_state,
        execution_cost_dollars=final_execution_cost
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
