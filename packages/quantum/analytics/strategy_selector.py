# packages/quantum/analytics/strategy_selector.py
from typing import Optional
from .regime_engine_v3 import RegimeState

class StrategySelector:
    def determine_strategy(
        self,
        ticker: str,
        sentiment: str,
        current_price: float,
        iv_rank: float,
        days_to_expiry: int = 45,
        effective_regime: Optional[RegimeState] = None
        effective_regime: str = "normal" # New argument
    ) -> dict:
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

        # Use effective_regime if provided to guide selection
        # If not, fallback to simple IV Rank logic (backward compatibility)

        # Regime A: Low IV (IV Rank < 30) or SUPPRESSED → Buy debit structures
        is_low_vol = (iv_rank < 30) or (effective_regime == RegimeState.SUPPRESSED)

        # Regime B: High IV (IV Rank > 50) or ELEVATED/SHOCK/REBOUND → Sell credit structures
        is_high_vol = (iv_rank > 50) or (effective_regime in [RegimeState.ELEVATED, RegimeState.SHOCK, RegimeState.REBOUND])

        # CHOP handling: Favor Iron Condors or wide spreads? Or skip?
        is_chop = (effective_regime == RegimeState.CHOP)

        if sentiment == "BULLISH":
            if is_low_vol:
                suggestion["strategy"] = "LONG_CALL_DEBIT_SPREAD"
                suggestion["rationale"] = "Bullish outlook + Suppressed/Low Vol. Buying leverage."
        # Normalize regime
        regime = effective_regime.lower()

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
            elif is_high_vol:
                suggestion["strategy"] = "SHORT_PUT_CREDIT_SPREAD"
                suggestion["rationale"] = "Bullish outlook + Elevated Vol. Selling premium."
            elif sentiment == "BEARISH":
                suggestion["strategy"] = "LONG_PUT_DEBIT_SPREAD"
                suggestion["rationale"] = "Bearish + Suppressed IV. Buying cheap protection."
                suggestion["legs"] = [
                    {"side": "buy", "type": "put", "delta_target": -0.65},
                    {"side": "sell", "type": "put", "delta_target": -0.30},
                ]

        elif regime in ["elevated", "high_vol"]:
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
            elif is_chop:
                 # In chop, maybe wider credit spreads or less directionality?
                 # Sticking to credit spreads for now but noting chop
                 suggestion["strategy"] = "SHORT_PUT_CREDIT_SPREAD"
                 suggestion["rationale"] = "Bullish lean in Choppy market. Selling premium with caution."
                 suggestion["legs"] = [
                    {"side": "sell", "type": "put", "delta_target": 0.25}, # More conservative delta
                    {"side": "buy", "type": "put", "delta_target": 0.10},
                 ]
            else:
                 # Default Normal
                 suggestion["strategy"] = "LONG_CALL_DEBIT_SPREAD"
                 suggestion["rationale"] = "Bullish outlook in Normal conditions."
                 suggestion["legs"] = [
                    {"side": "buy", "type": "call", "delta_target": 0.55},
                    {"side": "sell", "type": "call", "delta_target": 0.25},
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
            # Use IV Rank logic
            if sentiment == "BULLISH":
                if iv_rank < 35:
                    suggestion["strategy"] = "LONG_CALL_DEBIT_SPREAD"
                    suggestion["rationale"] = "Bullish + Low/Normal IV."
                    suggestion["legs"] = [
                        {"side": "buy", "type": "call", "delta_target": 0.60},
                        {"side": "sell", "type": "call", "delta_target": 0.30},
                    ]
                elif iv_rank > 45:
                    suggestion["strategy"] = "SHORT_PUT_CREDIT_SPREAD"
                    suggestion["rationale"] = "Bullish + Normal/High IV."
                    suggestion["legs"] = [
                        {"side": "sell", "type": "put", "delta_target": -0.30},
                        {"side": "buy", "type": "put", "delta_target": -0.15},
                    ]
            elif sentiment == "BEARISH":
                 if iv_rank < 35:
                    suggestion["strategy"] = "LONG_PUT_DEBIT_SPREAD"
                    suggestion["legs"] = [
                        {"side": "buy", "type": "put", "delta_target": -0.60},
                        {"side": "sell", "type": "put", "delta_target": -0.30},
                    ]
                 else:
                    suggestion["strategy"] = "SHORT_CALL_CREDIT_SPREAD"
                    suggestion["legs"] = [
                        {"side": "sell", "type": "call", "delta_target": 0.30},
                        {"side": "buy", "type": "call", "delta_target": 0.15},
                    ]

        return suggestion
