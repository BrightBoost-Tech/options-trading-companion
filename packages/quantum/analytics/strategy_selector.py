# packages/quantum/analytics/strategy_selector.py
from typing import Optional, List, Dict, Any
from .regime_engine_v3 import RegimeState

class StrategySelector:
    def determine_strategy(
        self,
        ticker: str,
        sentiment: str,
        current_price: float,
        iv_rank: float,
        days_to_expiry: int = 45,
        effective_regime: str = "normal"
    ) -> Dict[str, Any]:
        """
        Translates a directional sentiment into a specific option structure
        based on Volatility Regimes and Regime Engine V3 state.
        """
        suggestion = {
            "ticker": ticker,
            "strategy": "HOLD",
            "legs": [],
            "rationale": "",
        }

        # Normalize regime
        regime = effective_regime.lower() if effective_regime else "normal"

        # Logic Matrix
        if regime == "suppressed":
            # Low Vol -> Buy Vol (Debit Spreads or Long Options)
            if sentiment == "BULLISH":
                suggestion["strategy"] = "LONG_CALL_DEBIT_SPREAD"
                suggestion["rationale"] = "Bullish + Suppressed IV. Buying cheap leverage."
                suggestion["legs"] = [
                    {"side": "buy", "type": "call", "delta_target": 0.65},
                    {"side": "sell", "type": "call", "delta_target": 0.30},
                ]
            elif sentiment == "BEARISH":
                suggestion["strategy"] = "LONG_PUT_DEBIT_SPREAD"
                suggestion["rationale"] = "Bearish + Suppressed IV. Buying cheap protection."
                suggestion["legs"] = [
                    {"side": "buy", "type": "put", "delta_target": -0.65},
                    {"side": "sell", "type": "put", "delta_target": -0.30},
                ]

        elif regime in ["elevated", "high_vol", "elevated_vol"]:
            # High Vol -> Sell Vol (Credit Spreads)
            if sentiment == "BULLISH":
                suggestion["strategy"] = "SHORT_PUT_CREDIT_SPREAD"
                suggestion["rationale"] = "Bullish + Elevated IV. Selling expensive premium."
                suggestion["legs"] = [
                    {"side": "sell", "type": "put", "delta_target": -0.30},
                    {"side": "buy", "type": "put", "delta_target": -0.15},
                ]
            elif sentiment == "BEARISH":
                suggestion["strategy"] = "SHORT_CALL_CREDIT_SPREAD"
                suggestion["rationale"] = "Bearish + Elevated IV. Selling call premium."
                suggestion["legs"] = [
                    {"side": "sell", "type": "call", "delta_target": 0.30},
                    {"side": "buy", "type": "call", "delta_target": 0.15},
                ]

        elif regime == "rebound":
            # Volatile upside potential
            if sentiment == "BULLISH":
                suggestion["strategy"] = "LONG_CALL_DEBIT_SPREAD" # Or Ratio Backspread?
                suggestion["rationale"] = "Rebound Regime. Aggressive upside capture."
                suggestion["legs"] = [
                    {"side": "buy", "type": "call", "delta_target": 0.60},
                    {"side": "sell", "type": "call", "delta_target": 0.20}, # Wider spread
                ]
            elif sentiment == "BEARISH":
                 # Betting against rebound?
                 suggestion["strategy"] = "LONG_PUT_DEBIT_SPREAD"
                 suggestion["rationale"] = "Fading Rebound."
                 suggestion["legs"] = [
                    {"side": "buy", "type": "put", "delta_target": -0.50},
                    {"side": "sell", "type": "put", "delta_target": -0.20},
                 ]

        elif regime == "chop":
            # Range bound
            suggestion["strategy"] = "IRON_CONDOR"
            suggestion["rationale"] = "Chop Regime. Harvesting theta in range."
            suggestion["legs"] = [
                {"side": "sell", "type": "put", "delta_target": -0.20},
                {"side": "buy", "type": "put", "delta_target": -0.10},
                {"side": "sell", "type": "call", "delta_target": 0.20},
                {"side": "buy", "type": "call", "delta_target": 0.10},
            ]

        elif regime in ["shock", "panic"]:
            # Extreme Vol -> Stay small, maybe defined risk
            if sentiment == "BULLISH":
                 # Selling into panic puts is dangerous but profitable. Be careful.
                 suggestion["strategy"] = "SHORT_PUT_CREDIT_SPREAD"
                 suggestion["rationale"] = "Panic Regime. Selling extremely rich puts (Wide)."
                 suggestion["legs"] = [
                    {"side": "sell", "type": "put", "delta_target": -0.15}, # Far OTM
                    {"side": "buy", "type": "put", "delta_target": -0.05},
                ]
            else:
                 suggestion["strategy"] = "CASH"
                 suggestion["rationale"] = "Panic Regime. Cash is king."

        else: # Normal or Fallback
            # Use IV Rank logic if regime is ambiguous or "normal"
            if sentiment == "BULLISH":
                if iv_rank < 35:
                    suggestion["strategy"] = "LONG_CALL_DEBIT_SPREAD"
                    suggestion["rationale"] = "Bullish + Low/Normal IV."
                    suggestion["legs"] = [
                        {"side": "buy", "type": "call", "delta_target": 0.60},
                        {"side": "sell", "type": "call", "delta_target": 0.30},
                    ]
                else:
                    suggestion["strategy"] = "SHORT_PUT_CREDIT_SPREAD"
                    suggestion["rationale"] = "Bullish + Normal/High IV."
                    suggestion["legs"] = [
                        {"side": "sell", "type": "put", "delta_target": -0.30},
                        {"side": "buy", "type": "put", "delta_target": -0.15},
                    ]
            elif sentiment == "BEARISH":
                 if iv_rank < 35:
                    suggestion["strategy"] = "LONG_PUT_DEBIT_SPREAD"
                    suggestion["rationale"] = "Bearish + Low IV."
                    suggestion["legs"] = [
                        {"side": "buy", "type": "put", "delta_target": -0.60},
                        {"side": "sell", "type": "put", "delta_target": -0.30},
                    ]
                 else:
                    suggestion["strategy"] = "SHORT_CALL_CREDIT_SPREAD"
                    suggestion["rationale"] = "Bearish + High IV."
                    suggestion["legs"] = [
                        {"side": "sell", "type": "call", "delta_target": 0.30},
                        {"side": "buy", "type": "call", "delta_target": 0.15},
                    ]

        return suggestion
