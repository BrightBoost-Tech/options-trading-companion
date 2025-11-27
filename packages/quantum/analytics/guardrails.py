# packages/quantum/analytics/guardrails.py
from datetime import date, timedelta, datetime
from typing import Dict, Any, List

def get_next_earnings_date(symbol: str):
    # TODO: Implement this with a real data source
    return None

def get_sector_weight(existing_portfolio, sector):
    # TODO: Implement this with a real data source
    return 0.0

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
