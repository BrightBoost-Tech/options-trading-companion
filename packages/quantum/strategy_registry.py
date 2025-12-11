STRATEGY_REGISTRY = {
    "iron_condor": {
        "display_name": "Iron Condor",
        "description": "Neutral premium-selling strategy that profits when price stays in a range.",
        "risk_profile": "moderate",
        "typical_holding_period": "3–7 days",
        "entry_conditions": ["high IV rank", "stable market"],
        "exit_conditions": ["50% profit", "breach of short strike"],
    },
    "vertical_call": {
        "display_name": "Vertical Call Spread",
        "description": "Directional bullish strategy with defined risk.",
        "risk_profile": "medium",
        "typical_holding_period": "2–5 days",
    },
    "vertical_put": {
        "display_name": "Vertical Put Spread",
        "description": "Directional bearish strategy with defined risk.",
        "risk_profile": "medium",
        "typical_holding_period": "2–5 days",
    },
    "long_call": {
        "display_name": "Long Call",
        "description": "Bullish strategy with uncapped upside.",
        "risk_profile": "high",
        "typical_holding_period": "1–30 days",
    },
    "long_put": {
        "display_name": "Long Put",
        "description": "Bearish strategy with substantial upside on drops.",
        "risk_profile": "high",
        "typical_holding_period": "1–30 days",
    },
    "debit_call_spread": {
        "display_name": "Debit Call Spread",
        "description": "Bullish vertical spread paying a net debit.",
        "risk_profile": "defined",
        "typical_holding_period": "2-10 days"
    },
    "debit_put_spread": {
        "display_name": "Debit Put Spread",
        "description": "Bearish vertical spread paying a net debit.",
        "risk_profile": "defined",
        "typical_holding_period": "2-10 days"
    },
    "credit_call_spread": {
        "display_name": "Credit Call Spread",
        "description": "Bearish vertical spread collecting a net credit.",
        "risk_profile": "defined",
        "typical_holding_period": "2-10 days"
    },
    "credit_put_spread": {
        "display_name": "Credit Put Spread",
        "description": "Bullish vertical spread collecting a net credit.",
        "risk_profile": "defined",
        "typical_holding_period": "2-10 days"
    }
}

def infer_strategy_key_from_suggestion(suggestion: dict) -> str:
    """
    Best-effort mapping from a suggestion record or order_json to a normalized strategy_key.

    Priority order:
    - suggestion.get("strategy_key")
    - suggestion.get("strategy_type")
    - suggestion.get("type") # Scanner sometimes uses this
    - suggestion.get("strategy") # Consistency
    - suggestion.get("order_json", {}).get("strategy_type")
    - fallback: "unknown"
    """
    # 1. Explicit key
    if suggestion.get("strategy_key"):
        return str(suggestion["strategy_key"]).lower()

    # 2. Strategy Type fields
    candidates = [
        suggestion.get("strategy_type"),
        suggestion.get("strategy"),
        suggestion.get("type")
    ]

    # Check order_json
    order_json = suggestion.get("order_json") or {}
    if isinstance(order_json, dict):
        candidates.append(order_json.get("strategy_type"))
        candidates.append(order_json.get("strategy"))

    for cand in candidates:
        if cand and isinstance(cand, str):
            # Normalize
            key = cand.lower().strip().replace(" ", "_").replace("-", "_")
            # If it matches registry, great, otherwise return it as best effort
            return key

    return "unknown"
