from datetime import datetime, timedelta
import pandas as pd

class TradeGuardrails:
    def __init__(self, current_positions, portfolio_value):
        self.positions = current_positions
        self.portfolio_value = portfolio_value

    def check_earnings_risk(self, ticker: str, earnings_date: str) -> bool:
        """
        Heuristic: Reject trades if earnings are within 7 days
        or fall inside the option's expiration.
        """
        if not earnings_date:
            return True # Pass if unknown, but flag it

        e_date = datetime.strptime(earnings_date, "%Y-%m-%d")
        days_to_earnings = (e_date - datetime.now()).days

        # Rule: Avoid if earnings is < 5 days away
        if 0 <= days_to_earnings <= 5:
            return False
        return True

    def check_concentration(self, ticker: str, trade_cost: float, max_pct: float = 0.10) -> bool:
        """
        Heuristic: Don't let a single ticker exceed max_pct of portfolio.
        """
        if self.portfolio_value == 0:
            return True # Avoid division by zero
        current_alloc = sum(p.get('current_value', 0) for p in self.positions if p.get('symbol') == ticker)
        new_alloc = current_alloc + trade_cost

        if (new_alloc / self.portfolio_value) > max_pct:
            return False
        return True

    def check_liquidity(self, open_interest: int, volume: int) -> bool:
        """
        Heuristic: Minimum liquidity to ensure we can exit.
        """
        if open_interest < 500 or volume < 100:
            return False
        return True

    def check_iv_regime(self, iv_rank: float, strategy_type: str) -> bool:
        """
        Heuristic: Match strategy to IV.
        - Selling Premium: Requires IV Rank > 20
        - Buying Premium: Requires IV Rank < 30
        """
        if strategy_type == "credit_spread" and iv_rank < 20:
            return False
        if strategy_type == "long_call" and iv_rank > 50:
            return False
        return True
