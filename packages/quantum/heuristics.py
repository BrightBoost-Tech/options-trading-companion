# packages/quantum/heuristics.py
from datetime import datetime, timedelta
import logging

class TradeGuardrails:
    """
    Enforces trading rules to prevent 'mathematically correct' but 'practically suicide' trades.
    """
    def __init__(self, current_positions: list, total_portfolio_value: float):
        self.positions = current_positions
        self.portfolio_value = total_portfolio_value
        self.logger = logging.getLogger("quantum.guardrails")

    def validate_trade(self, ticker: str, strategy: str, trade_cost: float, market_data: dict) -> dict:
        """
        Runs a trade through all heuristic filters.
        Returns: {'valid': bool, 'reason': str}
        """
        # 1. Earnings Check (Binary Event Risk)
        if not self._check_earnings_safety(market_data.get('next_earnings_date')):
            return {'valid': False, 'reason': 'EARNINGS_RISK: Report within 7 days'}

        # 2. Liquidity Check (Slippage Risk)
        if not self._check_liquidity(market_data.get('open_interest', 0), market_data.get('volume', 0)):
            return {'valid': False, 'reason': 'LOW_LIQUIDITY: OI < 500 or Vol < 100'}

        # 3. Concentration Check (Ruin Risk)
        if not self._check_concentration(ticker, trade_cost):
            return {'valid': False, 'reason': 'OVER_CONCENTRATION: Exceeds 15% allocation'}

        # 4. IV Regime Check (Strategy Mismatch)
        if not self._check_iv_regime(strategy, market_data.get('iv_rank', 0)):
             return {'valid': False, 'reason': f'IV_MISMATCH: {strategy} unfit for IV Rank {market_data.get("iv_rank")}'}

        return {'valid': True, 'reason': 'PASS'}

    def _check_earnings_safety(self, earnings_date_str: str) -> bool:
        if not earnings_date_str: return True
        try:
            e_date = datetime.strptime(earnings_date_str, "%Y-%m-%d")
            # If earnings are within the next 7 days, avoid.
            if 0 <= (e_date - datetime.now()).days <= 7:
                return False
        except ValueError:
            self.logger.warning(f"Could not parse earnings date: {earnings_date_str}")
            return True # Fail open if date format is weird, but log it
        return True

    def _check_liquidity(self, oi: int, vol: int) -> bool:
        # Research standard: Minimum 500 OI to ensure decent bid-ask spreads
        return oi >= 500 and vol >= 100

    def _check_concentration(self, ticker: str, trade_cost: float) -> bool:
        # Sum existing value for this ticker
        existing_exposure = sum(
            float(p['market_value']) for p in self.positions if p['symbol'] == ticker
        )
        new_exposure = existing_exposure + trade_cost
        # Hard Limit: No single ticker > 15% of portfolio
        return (new_exposure / self.portfolio_value) < 0.15

    def _check_iv_regime(self, strategy: str, iv_rank: float) -> bool:
        # Selling premium (Credit Spreads, Iron Condors) requires high IV (mean reversion)
        if 'credit' in strategy or 'short' in strategy:
            return iv_rank > 20
        # Buying premium (Long Calls/Puts) requires low IV
        if 'long' in strategy or 'debit' in strategy:
            return iv_rank < 50
        return True