# packages/quantum/analytics/guardrails.py
import os
from datetime import date, timedelta, datetime
from typing import Dict, Any, List
from packages.quantum.market_data import PolygonService

def get_next_earnings_date(symbol: str):
    """
    Estimates the next earnings date using a real data source (Polygon).
    Strategy: Get last financial filing date and project +90-91 days.
    """
    try:
        service = PolygonService()
        last_date_dt = service.get_last_financials_date(symbol)

        if last_date_dt:
            last_date = last_date_dt.date()
            # Standard quarter is ~91 days
            next_date = last_date + timedelta(days=91)

            # If the projected date is in the past, keep adding quarters until it's in the future.
            # This robustly handles data that might be 6+ months stale (e.g. smaller caps).
            while next_date < date.today():
                next_date += timedelta(days=91)

            return next_date

        return None
    except Exception:
        # Fail gracefully to None
        return None

def get_sector_weight(existing_portfolio, sector):
    """
    Calculates the weight of a specific sector in the existing portfolio.

    Args:
        existing_portfolio: List of positions (dicts or objects).
        sector: The sector string to check against.

    Returns:
        float: The proportion of portfolio value in that sector (0.0 to 1.0).
    """
    total_portfolio_value = 0.0
    sector_value = 0.0

    for pos in existing_portfolio:
        # Determine value and sector safely whether pos is dict or object
        val = 0.0
        p_sector = None

        if isinstance(pos, dict):
            val = float(pos.get("current_value", 0.0))
            if val == 0.0 and "quantity" in pos and "current_price" in pos:
                val = float(pos["quantity"]) * float(pos["current_price"])
            p_sector = pos.get("sector")
        else:
            val = getattr(pos, "current_value", 0.0)
            if val == 0.0 and hasattr(pos, "quantity") and hasattr(pos, "current_price"):
                val = float(pos.quantity) * float(pos.current_price)
            p_sector = getattr(pos, "sector", None)

        total_portfolio_value += val

        if p_sector == sector:
            sector_value += val

    if total_portfolio_value <= 0:
        return 0.0

    return sector_value / total_portfolio_value

def apply_guardrails(candidates, existing_portfolio):
    """
    Post-processing filter over candidate trades to apply
    earnings, liquidity, and concentration constraints.
    Expects 'candidates' to be a list of dicts with at least:
    - symbol
    - sector (if available)
    - score (numeric)
    """
    valid_candidates = []

    for c in candidates:
        # 1. Earnings Check (Requires Polygon / reference data)
        earnings_date = get_next_earnings_date(c["symbol"])
        if earnings_date:
            days_until_earnings = (earnings_date - date.today()).days
            if 0 < days_until_earnings < 7:
                # Penalize heavily instead of full exclusion
                c.setdefault("warnings", []).append("EARNINGS_WEEK")
                if "score" in c:
                    c["score"] *= 0.5

        # 2. Concentration Check (sector concentration > 20% gets rejected)
        sector = c.get("sector")
        if sector:
            current_weight = get_sector_weight(existing_portfolio, sector)
            if current_weight > 0.20:
                # Hard reject to avoid over-concentration
                c.setdefault("warnings", []).append("SECTOR_CONCENTRATION")
                continue

        # NOTE: Liquidity gate (OI / Bid-Ask) can be integrated here once available in 'c'
        valid_candidates.append(c)

    return valid_candidates

def compute_conviction_score(trade):
    score = 0.0

    # Trend (e.g., SMA20 > SMA50)
    if trade.get("trend") == "UP":
        score += 20

    # Volatility: good conditions for the chosen strategy
    iv_rank = trade.get("iv_rank")
    if iv_rank is not None:
        if trade.get("direction") == "BUY" and iv_rank < 20:
            score += 20
        elif trade.get("direction") == "SELL" and iv_rank > 50:
            score += 20

    # Reward/Risk or Expected Value
    rr = trade.get("reward_risk")
    if rr and rr > 0:
        score += 30

    # Apply penalties (from guardrails)
    for warning in trade.get("warnings", []):
        if warning == "EARNINGS_WEEK":
            score -= 15
        if warning == "SECTOR_CONCENTRATION":
            score -= 20

    # Clamp 0–100
    return max(0, min(100, int(score)))

def earnings_week_penalty(strategy: str) -> float:
    """
    Returns the score penalty to apply if earnings are within 7 days.
    """
    # Simple constant penalty, matching the implicit -15 logic in compute_conviction_score
    return 15.0

def apply_slippage_guardrail(trade: Dict[str, Any], quote: Dict[str, float]) -> float:
    """
    Returns a slippage penalty multiplier in [0,1] based on bid/ask spread.
    trade: suggestion or candidate (unused in simple logic but kept for context)
    quote: bid/ask data {'bid': float, 'ask': float}
    """
    app_env = os.getenv("APP_ENV", "development").lower()

    bid = quote.get("bid", 0.0) if isinstance(quote, dict) else 0.0
    ask = quote.get("ask", 0.0) if isinstance(quote, dict) else 0.0

    # Dev-mode override: if we have no real quote data, don't kill the trade.
    if app_env == "development" and (bid == 0 or bid is None) and (ask == 0 or ask is None):
        return 1.0

    # STRICT: Reject if bid or ask is missing/zero
    if bid <= 0 or ask <= 0:
        return 0.0 # No liquidity

    width = ask - bid

    # Avoid division by zero (redundant with bid<=0 check but safe)
    if bid == 0:
        return 0.0

    ratio = width / bid

    # 15% spread -> 0 (reject)
    if ratio > 0.15:
        return 0.0

    # 5-15% spread -> 0.8 (penalty)
    if ratio > 0.05:
        return 0.8

    # <= 5% -> 1.0 (pass)
    return 1.0

# --- New Functions ---

def is_earnings_safe(symbol: str, market_data: Dict[str, Any]) -> bool:
    """
    Checks if there is an earnings report for the symbol within the next 14 days.
    """
    # Placeholder: In a real scenario, this would check a live earnings calendar.
    earnings_date_str = market_data.get('earnings_date')
    if not earnings_date_str:
        return True

    try:
        earnings_date = datetime.fromisoformat(earnings_date_str).date()
        if (earnings_date - date.today()).days < 14:
            return False
    except (ValueError, TypeError):
        return True

    return True

def check_liquidity(symbol: str, market_data: Dict[str, Any]) -> bool:
    """
    Checks if the options for a given symbol are liquid enough to trade.
    """
    open_interest = market_data.get('open_interest', 0)
    volume = market_data.get('volume', 0)

    return open_interest > 100 and volume > 50

def sector_penalty(
    symbol: str,
    market_data: Dict[str, Any],
    positions: List[Dict[str, Any]],
    portfolio_value: float
) -> float:
    """
    Calculates a penalty based on sector concentration.
    """
    sector = market_data.get('sector')
    if not sector or not portfolio_value:
        return 0.0

    sector_value = 0
    for pos in positions:
        if pos.get('sector') == sector:
            sector_value += pos.get('current_value', 0)

    concentration = sector_value / portfolio_value
    if concentration > 0.25: # Threshold for penalty
        return (concentration - 0.25) * 100 # Penalty score
    return 0.0


class SmallAccountCompounder:
    """
    Guardrails specifically for a $1k -> $5k compounding objective.
    This is additive and should not break existing guardrail logic.
    """
    MIN_POP: float = 0.60    # min probability of profit
    MAX_RISK_PCT: float = 0.05  # max 5% of account risk per trade
    MAX_LOSS_PCT: float = 0.10  # max 10% of account as max_loss (collateral cap)
    MIN_EV_PCT: float = 5.0  # min expected edge (%)

    @classmethod
    def apply(cls, suggestions: List[Dict[str, Any]], account_value: float) -> List[Dict[str, Any]]:
        """
        Filter + score raw trade suggestions for Compounding Small-Edge mode.
        Assumes each suggestion dict has at least:
          - prob_profit (float)
          - max_loss (float)
          - ev_percent (float) or enough data to derive it
          - undefined_risk (bool?) if available
        Returns a new list, sorted descending by `compound_score`.
        """
        filtered = []
        for trade in suggestions:
            # 1. Reject Undefined Risk
            if trade.get('undefined_risk') is True:
                continue

            # 2. Enforce Min POP
            prob_profit = float(trade.get('prob_profit', 0.0))
            if prob_profit < cls.MIN_POP:
                continue

            # 3. Max Loss Cap relative to account
            max_loss = float(trade.get('max_loss', 0.0))
            if max_loss > account_value * cls.MAX_LOSS_PCT:
                continue

            # 4. EV Threshold (if available)
            # Some sources might not pre-calc EV %, so we check if key exists
            if 'ev_percent' in trade:
                if float(trade['ev_percent']) < cls.MIN_EV_PCT:
                    continue

            # 5. Compute Compound Score
            # Base score = Probability * 100
            score = prob_profit * 100.0

            # Add EV boost
            if 'ev_percent' in trade:
                score += float(trade['ev_percent'])

            # Add Risk/Reward boost
            max_profit = float(trade.get('max_profit', 0.0))
            if max_loss > 0:
                rr = max_profit / max_loss
                score += (rr * 10.0) # Weight RR reasonably

            trade['compound_score'] = score
            filtered.append(trade)

        # Sort descending by score
        filtered.sort(key=lambda x: x.get('compound_score', 0), reverse=True)
        return filtered
