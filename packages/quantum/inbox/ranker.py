from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

def calculate_yield_on_risk(suggestion: Dict[str, Any]) -> float:
    """
    Computes yield_on_risk = EV / capital_requirement.
    Fallback order for denominator:
    1. sizing_metadata.max_loss_total
    2. sizing_metadata.capital_required_total
    3. sizing_metadata.capital_required
    4. 1.0
    """
    ev = suggestion.get("ev") or 0.0

    sizing = suggestion.get("sizing_metadata") or {}

    # Check keys in order
    denom = sizing.get("max_loss_total")
    if denom is None:
        denom = sizing.get("capital_required_total")
    if denom is None:
        denom = sizing.get("capital_required")

    # Ensure denom is a valid number and not zero
    if denom is None or denom == 0:
        denom = 1.0

    return float(ev) / float(denom)

def rank_suggestions(suggestions: List[Dict[str, Any]], stale_after_seconds: int = 300) -> List[Dict[str, Any]]:
    """
    Ranks suggestions by yield_on_risk desc, then created_at desc.
    Augments suggestions with ranking metadata.
    """
    now = datetime.now(timezone.utc)

    for s in suggestions:
        # Calculate scores
        yor = calculate_yield_on_risk(s)
        s["yield_on_risk"] = yor

        # Inbox score can be same as yield_on_risk or scaled
        # For MVP, we use yield_on_risk as the score
        s["inbox_score"] = yor

        # Stale check
        created_at_str = s.get("created_at")
        is_stale = False
        if created_at_str:
            try:
                # Handle potentially missing Z or different formats if necessary,
                # but standard ISO from Supabase usually works with fromisoformat
                dt = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                age = (now - dt).total_seconds()
                is_stale = age > stale_after_seconds
            except ValueError:
                pass # Default false if parse fails

        s["is_stale"] = is_stale

    # Sort
    # Tie-break: created_at desc
    def sort_key(x):
        ts = x.get("created_at") or ""
        return (x["yield_on_risk"], ts)

    suggestions.sort(key=sort_key, reverse=True)

    return suggestions
