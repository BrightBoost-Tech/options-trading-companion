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
