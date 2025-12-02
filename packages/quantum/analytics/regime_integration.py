from typing import List, Dict, Any
from .regime_scoring import ScoringEngine, ConvictionTransform
from .risk_manager import RiskBudgetManager, MorningManager

# --- Configuration Templates ---

DEFAULT_WEIGHT_MATRIX = {
    'normal': {'trend': 0.4, 'value': 0.3, 'volatility': 0.3},
    'high_vol': {'trend': 0.2, 'value': 0.3, 'volatility': 0.5},
    'panic': {'trend': 0.1, 'value': 0.1, 'volatility': 0.8}
}

DEFAULT_CATALYST_PROFILES = {
    'none': {'trend': 1.0, 'value': 1.0, 'volatility': 1.0},
    'pre': {'trend': 0.8, 'value': 0.8, 'volatility': 1.5}, # Vol matters more pre-event
    'event': {'trend': 0.0, 'value': 0.0, 'volatility': 2.0}, # Pure vol play
    'post': {'trend': 1.5, 'value': 1.0, 'volatility': 0.5} # Trend re-establishment
}

DEFAULT_LIQUIDITY_SCALAR = {
    'top': 1.0,
    'mid': 0.9,
    'lower': 0.7,
    'illiquid': 0.0
}

DEFAULT_REGIME_PROFILES = {
    'normal': {
        'k': 0.1,
        'mu': 50.0,
        'absolute_hard_floor': 30.0,
        'mu_dynamic_weight': 0.5
    },
    'high_vol': {
        'k': 0.08, # Flatter curve, more uncertainty
        'mu': 60.0, # Higher bar
        'absolute_hard_floor': 40.0,
        'mu_dynamic_weight': 0.7 # Anchor more to relativity
    },
    'panic': {
        'k': 0.2, # Steep binary decisions
        'mu': 40.0,
        'absolute_hard_floor': 20.0,
        'mu_dynamic_weight': 0.2,
        'panic_scale': 0.5 # Halve all conviction
    }
}

DEFAULT_RISK_BUDGETS = {
    'normal': {'trend': 0.4, 'value': 0.4, 'volatility': 0.2},
    'high_vol': {'trend': 0.2, 'value': 0.3, 'volatility': 0.5},
    'panic': {'trend': 0.1, 'value': 0.1, 'volatility': 0.8}
}

# --- Integration Logic ---

def map_market_regime(global_context: Dict[str, Any]) -> str:
    """
    Maps global context/state to effective scoring regime.
    Input fields expected:
      - state: 'bull' | 'bear' | 'crab' | 'shock' (from nested/backbone)
      - vol_annual: float (optional, overrides if high)
    Output: 'normal' | 'high_vol' | 'panic'
    """
    state = global_context.get('state', 'normal')
    vol = global_context.get('vol_annual', 0.0)

    # 1. Hard Overrides (Shock -> Panic)
    if state == 'shock':
        return 'panic'

    # 2. Volatility Check
    # If vol > 20%, force high_vol even if state is bull/crab
    if vol > 0.20:
        return 'high_vol'

    # 3. State Mapping
    if state == 'bear':
        return 'high_vol'

    return 'normal'


def run_scoring_pipeline(
    universe_data: List[Dict[str, Any]],
    current_regime: str,
    scoring_engine: ScoringEngine = None,
    conviction_transform: ConvictionTransform = None
) -> List[Dict[str, Any]]:
    """
    Example of a full scoring pass:
    1. Score all symbols.
    2. Compute universe stats (median).
    3. Calculate Conviction (C_i).
    """

    # Initialize services if not provided
    if not scoring_engine:
        scoring_engine = ScoringEngine(
            DEFAULT_WEIGHT_MATRIX,
            DEFAULT_CATALYST_PROFILES,
            DEFAULT_LIQUIDITY_SCALAR
        )

    if not conviction_transform:
        conviction_transform = ConvictionTransform(DEFAULT_REGIME_PROFILES)

    # 1. First Pass: Raw Scores
    scored_symbols = []
    raw_scores = []

    for symbol_data in universe_data:
        # Calculate raw score
        result = scoring_engine.calculate_score(symbol_data, current_regime)
        scored_symbols.append(result)
        raw_scores.append(result['raw_score'])

    # 2. Compute Universe Median (Regime-Specific Anchor)
    universe_median = 0.0
    if raw_scores:
        # Simple median implementation
        sorted_scores = sorted(raw_scores)
        n = len(sorted_scores)
        mid = n // 2
        if n % 2 == 1:
            universe_median = sorted_scores[mid]
        else:
            universe_median = (sorted_scores[mid-1] + sorted_scores[mid]) / 2.0

    # 3. Second Pass: Conviction C_i
    final_results = []
    for item in scored_symbols:
        c_i = conviction_transform.get_conviction(
            raw_score=item['raw_score'],
            regime=current_regime,
            universe_median=universe_median
        )

        # Enrich item with conviction
        item['conviction'] = c_i
        item['universe_median_used'] = universe_median
        final_results.append(item)

    return final_results

def run_historical_scoring(
    symbol_data: Dict[str, Any],
    regime: str,
    scoring_engine: ScoringEngine = None,
    conviction_transform: ConvictionTransform = None,
    universe_median: Any = None
) -> Dict[str, Any]:
    """
    Helper for single-symbol historical scoring to align with live pipeline.
    """
    if not scoring_engine:
        scoring_engine = ScoringEngine(
            DEFAULT_WEIGHT_MATRIX,
            DEFAULT_CATALYST_PROFILES,
            DEFAULT_LIQUIDITY_SCALAR
        )
    if not conviction_transform:
        conviction_transform = ConvictionTransform(DEFAULT_REGIME_PROFILES)

    # 1. Score
    score_res = scoring_engine.calculate_score(symbol_data, regime)

    # 2. Conviction
    c_i = conviction_transform.get_conviction(
        score_res['raw_score'],
        regime,
        universe_median=universe_median
    )

    return {
        **score_res,
        "conviction": c_i
    }

def evaluate_trade_risk(
    trade_proposal: Dict[str, Any],
    portfolio_snapshot: Dict[str, Any],
    regime: str
) -> bool:
    """
    Wrapper for RiskBudgetManager.
    """
    rm = RiskBudgetManager(DEFAULT_RISK_BUDGETS)
    return rm.check_trade_viability(trade_proposal, portfolio_snapshot, regime)


def get_morning_exits(
    positions: List[Dict[str, Any]],
    current_convictions: Dict[str, float], # map symbol -> C_i
    nav: float,
    regime: str
) -> List[Dict[str, Any]]:
    """
    Scans positions and returns those with high exit urgency.
    """
    mm = MorningManager(theta_sensitivity=100.0, base_floor=0.4)

    exits = []
    for pos in positions:
        symbol = pos.get('underlying', pos.get('symbol'))
        c_i = current_convictions.get(symbol, 0.5) # Default to mid if missing

        urgency = mm.get_exit_urgency(pos, c_i, nav, regime)

        if urgency > 0.6: # Threshold for "Actionable Exit"
            exits.append({
                'symbol': symbol,
                'urgency': urgency,
                'reason': f"Low Conviction ({c_i:.2f}) vs Theta Cost"
            })

    # Sort by urgency desc
    exits.sort(key=lambda x: x['urgency'], reverse=True)
    return exits
