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
        # Regime B: High IV (IV Rank > 50) → Sell credit structures

        if sentiment == "BULLISH":
            if iv_rank < 30:
                suggestion["strategy"] = "LONG_CALL_DEBIT_SPREAD"
                suggestion["rationale"] = "Bullish outlook + Cheap Volatility (Low IV). Buying leverage."
                suggestion["legs"] = [
                    {"side": "buy", "type": "call", "delta_target": 0.60},
                    {"side": "sell", "type": "call", "delta_target": 0.30},
                ]
            elif iv_rank > 50:
                suggestion["strategy"] = "SHORT_PUT_CREDIT_SPREAD"
                suggestion["rationale"] = "Bullish outlook + Expensive Volatility. Selling premium."
                suggestion["legs"] = [
                    {"side": "sell", "type": "put", "delta_target": 0.30},
                    {"side": "buy", "type": "put", "delta_target": 0.15},  # Wing protection
                ]

        elif sentiment == "BEARISH":
            if iv_rank < 30:
                suggestion["strategy"] = "LONG_PUT_DEBIT_SPREAD"
                suggestion["rationale"] = "Bearish outlook + Cheap Volatility (Low IV). Buying leverage."
                suggestion["legs"] = [
                    {"side": "buy", "type": "put", "delta_target": 0.60},
                    {"side": "sell", "type": "put", "delta_target": 0.30},
                ]
            elif iv_rank > 50:
                suggestion["strategy"] = "SHORT_CALL_CREDIT_SPREAD"
                suggestion["rationale"] = "Bearish outlook + Expensive Volatility. Selling premium."
                suggestion["legs"] = [
                    {"side": "sell", "type": "call", "delta_target": 0.30},
                    {"side": "buy", "type": "call", "delta_target": 0.15},
                ]

        elif sentiment == "NEUTRAL":
            if iv_rank > 50:
                suggestion["strategy"] = "SHORT_IRON_CONDOR"
                suggestion["rationale"] = "Neutral outlook + Expensive Volatility. Selling both sides."
                suggestion["legs"] = [
                    {"side": "sell", "type": "put", "delta_target": 0.20},
                    {"side": "buy", "type": "put", "delta_target": 0.10},
                    {"side": "sell", "type": "call", "delta_target": 0.20},
                    {"side": "buy", "type": "call", "delta_target": 0.10},
                ]
            elif iv_rank < 30:
                suggestion["strategy"] = "LONG_CALENDAR_SPREAD"
                suggestion["rationale"] = "Neutral outlook + Cheap Volatility. Buying time/volatility."
                # Note: Calendar spreads require different expiries which might need specific handling downstream
                suggestion["legs"] = [
                    {"side": "sell", "type": "call", "delta_target": 0.50, "expiry_offset": "near"},
                    {"side": "buy", "type": "call", "delta_target": 0.50, "expiry_offset": "far"},
                ]

        elif sentiment == "EARNINGS":
            # Explicit earnings play (Volatility play)
            if iv_rank > 50:
                suggestion["strategy"] = "SHORT_IRON_CONDOR"
                suggestion["rationale"] = "Earnings Volatility Crush Play."
                suggestion["legs"] = [
                    {"side": "sell", "type": "put", "delta_target": 0.20},
                    {"side": "buy", "type": "put", "delta_target": 0.10},
                    {"side": "sell", "type": "call", "delta_target": 0.20},
                    {"side": "buy", "type": "call", "delta_target": 0.10},
                ]
            elif iv_rank < 30:
                suggestion["strategy"] = "LONG_STRADDLE"
                suggestion["rationale"] = "Earnings Volatility Expansion Play."
                suggestion["legs"] = [
                    {"side": "buy", "type": "call", "delta_target": 0.50},
                    {"side": "buy", "type": "put", "delta_target": 0.50},
                ]

        return suggestion
