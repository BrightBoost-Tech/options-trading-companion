import numpy as np
from datetime import datetime, timedelta
from polygon_client import PolygonClient

class DecisionEngine:
    def __init__(self, polygon_api_key):
        self.poly = PolygonClient(polygon_api_key)

    async def analyze_trade(self, ticker, intended_action="LONG", days_to_expiry=45):
        """
        Synthesizes Market Data into a Concrete Decision.
        """
        # 1. LIVE DATA FETCH
        details = await self.poly.get_ticker_details(ticker)
        quote = await self.poly.get_last_quote(ticker)  # Live Price
        iv_rank = await self._calculate_live_iv_rank(ticker)  # Custom logic below

        current_price = quote["price"]

        # 2. GUARDRAILS (The "Don't Trade" Logic)
        next_earnings = await self._get_next_earnings(ticker)
        if next_earnings:
            days_to_earnings = (next_earnings - datetime.now()).days
            if 0 <= days_to_earnings <= days_to_expiry:
                return {
                    "status": "REJECTED",
                    "reason": f"Earnings Collision: Report in {days_to_earnings} days."
                }

        # Liquidity guardrail (simple cap proxy, refine if you already have volume data)
        if details.get("market_cap", 0) < 2_000_000_000:  # 2B Min Cap
            return {"status": "REJECTED", "reason": "Low Liquidity / Small Cap Risk"}

        # 3. STRATEGY SELECTION
        strategy = self._select_strategy(intended_action, iv_rank, current_price)

        return {
            "status": "APPROVED",
            "ticker": ticker,
            "current_price": current_price,
            "iv_rank": iv_rank,
            "suggested_strategy": strategy,
            "greeks_implication": self._get_greeks_profile(strategy.get("type"))
        }

    def _select_strategy(self, action, iv_rank, price):
        """
        Maps Volatility Regime to Option Structure.
        """
        if action == "LONG":
            # High IV = Sell Puts (Bull Put Spread)
            if iv_rank > 50:
                return {
                    "type": "CREDIT_SPREAD",
                    "name": "Bull Put Spread",
                    "legs": [
                        {"side": "sell", "strike": price * 0.95, "delta": 0.30},
                        {"side": "buy", "strike": price * 0.90, "delta": 0.15},
                    ],
                    "logic": "High Implied Volatility favors selling premium."
                }
            # Low IV = Buy Calls (Call Debit Spread)
            else:
                return {
                    "type": "DEBIT_SPREAD",
                    "name": "Call Debit Spread",
                    "legs": [
                        {"side": "buy", "strike": price * 1.02, "delta": 0.55},
                        {"side": "sell", "strike": price * 1.07, "delta": 0.30},
                    ],
                    "logic": "Low Implied Volatility favors buying leverage."
                }
        return {}

    def _get_greeks_profile(self, strategy_type):
        if strategy_type == "CREDIT_SPREAD":
            return {"delta": "Positive", "theta": "Positive (Income)", "vega": "Negative (Short Vol)"}
        return {"delta": "Positive", "theta": "Negative (Decay)", "vega": "Positive (Long Vol)"}

    # Helper stubs for live calculation
    async def _calculate_live_iv_rank(self, ticker):
        # In production, fetch 1 year of IV history from Polygon and compute percentile
        snapshot = await self.poly.get_snapshot(ticker)
        return snapshot.get("implied_volatility", 0.30) * 100  # Normalized percentage

    async def _get_next_earnings(self, ticker):
        # TODO: Implement via Polygon Reference API or your existing earnings source
        return None
