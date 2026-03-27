from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

from packages.quantum.analytics.canonical_ranker import (
    compute_risk_adjusted_ev,
    CANONICAL_RANKING_ENABLED,
)


def calculate_yield_on_risk(suggestion: Dict[str, Any]) -> float:
    """
    Legacy metric: yield_on_risk = EV / capital_requirement.
    Retained for backwards compatibility and transition logging.
    """
    ev = suggestion.get("ev") or 0.0
    sizing = suggestion.get("sizing_metadata") or {}

    denom = sizing.get("max_loss_total")
    if denom is None:
        denom = sizing.get("capital_required_total")
    if denom is None:
        denom = sizing.get("capital_required")
    if denom is None or denom == 0:
        denom = 1.0

    return float(ev) / float(denom)


def rank_suggestions(
    suggestions: List[Dict[str, Any]],
    stale_after_seconds: int = 300,
    existing_positions: Optional[List[Dict[str, Any]]] = None,
    portfolio_budget: float = 100_000.0,
) -> List[Dict[str, Any]]:
    """
    Ranks suggestions by risk_adjusted_ev (canonical) or yield_on_risk (legacy).
    Augments suggestions with ranking metadata.
    """
    now = datetime.now(timezone.utc)
    positions = existing_positions or []

    for s in suggestions:
        # Always compute legacy metric for backwards compat
        yor = calculate_yield_on_risk(s)
        s["yield_on_risk"] = yor

        # Compute canonical metric
        raev = compute_risk_adjusted_ev(s, positions, portfolio_budget)
        s["risk_adjusted_ev"] = round(raev, 6)

        # Inbox score uses canonical when enabled
        s["inbox_score"] = raev if CANONICAL_RANKING_ENABLED else yor

        # Stale check
        created_at_str = s.get("created_at")
        is_stale = False
        if created_at_str:
            try:
                dt = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                age = (now - dt).total_seconds()
                is_stale = age > stale_after_seconds
            except ValueError:
                pass
        s["is_stale"] = is_stale

    # Sort by canonical metric when enabled, legacy otherwise
    if CANONICAL_RANKING_ENABLED:
        def sort_key(x):
            ts = x.get("created_at") or ""
            return (x.get("risk_adjusted_ev", -999), ts)
    else:
        def sort_key(x):
            ts = x.get("created_at") or ""
            return (x["yield_on_risk"], ts)

    suggestions.sort(key=sort_key, reverse=True)
    return suggestions
