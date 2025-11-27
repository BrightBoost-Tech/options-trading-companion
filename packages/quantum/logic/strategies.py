# packages/quantum/logic/strategies.py
from datetime import datetime, timedelta

class StrategyEngine:
    """
    Decides HOW to trade a ticker based on Volatility and Sentiment.
    Encodes trader intuition into structured option strategies.
    """

    def match_strategy(
        self,
        ticker: str,
        sentiment: str,
        iv_rank: float,
        current_price: float,
    ) -> dict:
        suggestion = {
            "ticker": ticker,
            "action": "HOLD",
            "structure": None,
            "legs": [],
            "reasoning": [],
        }

        # Volatility regime
        if iv_rank < 25:
            vol_regime = "LOW_VOL_BUY"       # Cheap options → buy premium
        elif iv_rank > 50:
            vol_regime = "HIGH_VOL_SELL"     # Expensive options → sell premium
        else:
            vol_regime = "NEUTRAL_VOL"

        # Strategy selection
        if sentiment == "BULLISH":
            if vol_regime == "LOW_VOL_BUY":
                suggestion["action"] = "OPEN"
                suggestion["structure"] = "LONG_CALL_VERTICAL"
                suggestion["reasoning"].append(
                    f"IV Rank {iv_rank} is low. Buying call spread for leveraged upside."
                )
                suggestion["legs"] = [
                    {"side": "buy", "delta": 0.65, "type": "call"},
                    {"side": "sell", "delta": 0.30, "type": "call"},
                ]
            elif vol_regime == "HIGH_VOL_SELL":
                suggestion["action"] = "OPEN"
                suggestion["structure"] = "BULL_PUT_SPREAD"
                suggestion["reasoning"].append(
                    f"IV Rank {iv_rank} is high. Selling put spread to collect rich premium."
                )
                suggestion["legs"] = [
                    {"side": "sell", "delta": 0.30, "type": "put"},
                    {"side": "buy", "delta": 0.10, "type": "put"},
                ]

        elif sentiment == "BEARISH":
            if vol_regime == "LOW_VOL_BUY":
                suggestion["action"] = "OPEN"
                suggestion["structure"] = "LONG_PUT_VERTICAL"
                suggestion["reasoning"].append("Cheap vol. Buying put spread for downside protection.")
            elif vol_regime == "HIGH_VOL_SELL":
                suggestion["action"] = "OPEN"
                suggestion["structure"] = "BEAR_CALL_SPREAD"
                suggestion["reasoning"].append("High vol. Selling call spread against bearish view.")

        # Future: add NEUTRAL sentiment + earnings-aware structures
        return suggestion
