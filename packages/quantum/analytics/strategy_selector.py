# packages/quantum/analytics/strategy_selector.py

class StrategySelector:
    def determine_strategy(
        self,
        ticker: str,
        sentiment: str,
        current_price: float,
        iv_rank: float,
        days_to_expiry: int = 45,
    ) -> dict:
        """
        Translates a directional sentiment into a specific option structure
        based on Volatility Regimes.
        """
        suggestion = {
            "ticker": ticker,
            "strategy": "HOLD",
            "legs": [],
            "rationale": "",
        }

        # Regime A: Low IV (IV Rank < 30) → Buy debit structures
        if sentiment == "BULLISH":
            if iv_rank < 30:
                suggestion["strategy"] = "LONG_CALL_DEBIT_SPREAD"
                suggestion["rationale"] = "Bullish outlook + Cheap Volatility (Low IV). Buying leverage."
                suggestion["legs"] = [
                    {"side": "buy", "type": "call", "delta_target": 0.60},
                    {"side": "sell", "type": "call", "delta_target": 0.30},
                ]
            elif iv_rank > 50:
                # Regime B: High IV (IV Rank > 50) → Sell credit structures
                suggestion["strategy"] = "SHORT_PUT_CREDIT_SPREAD"
                suggestion["rationale"] = "Bullish outlook + Expensive Volatility. Selling premium."
                suggestion["legs"] = [
                    {"side": "sell", "type": "put", "delta_target": 0.30},
                    {"side": "buy", "type": "put", "delta_target": 0.15},  # Wing protection
                ]

        # TODO: extend later for BEARISH/NEUTRAL and explicit earnings regimes
        return suggestion
