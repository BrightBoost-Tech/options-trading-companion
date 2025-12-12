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
                suggestion["legs"] = [
                    {"side": "buy", "type": "call", "delta_target": 0.60},
                    {"side": "sell", "type": "call", "delta_target": 0.30},
                ]
            elif is_high_vol:
                suggestion["strategy"] = "SHORT_PUT_CREDIT_SPREAD"
                suggestion["rationale"] = "Bullish outlook + Elevated Vol. Selling premium."
                suggestion["legs"] = [
                    {"side": "sell", "type": "put", "delta_target": 0.30},
                    {"side": "buy", "type": "put", "delta_target": 0.15},  # Wing protection
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

        # TODO: extend later for BEARISH/NEUTRAL and explicit earnings regimes
        return suggestion
