
from typing import List, Dict, Any

def calculate_otc_score(trade: Dict[str, Any], market_data: Dict[str, Any]) -> int:
    """
    Calculates the OTC (Options Trading Companion) Score for a trade.
    The score is a number between 0 and 100, composed of several weighted factors.
    """
    score = 0

    # 1. Edge (Trend Alignment) - 30 points
    edge_score = 0
    if check_trend_alignment(trade, market_data):
        edge_score = 30
    score += edge_score

    # 2. Probability (Delta as Proxy for Probability of Profit) - 25 points
    delta = trade.get('delta', 0.5)
    # Map delta (0 to 1) to a 0-25 point scale
    prob_score = (1 - abs(delta)) * 25
    score += prob_score

    # 3. Risk/Reward - 25 points
    risk_reward = trade.get('risk_reward_ratio', 0)
    # Simple linear scale for risk/reward
    rr_score = min(risk_reward * 25, 25)
    score += rr_score

    # 4. Liquidity/Safety - 20 points
    liquidity_score = 0
    if trade.get('is_liquid', False):
        liquidity_score += 10
    if trade.get('is_earnings_safe', False):
        liquidity_score += 10
    score += liquidity_score

    return int(min(score, 100))

def generate_badges(trade: Dict[str, Any], market_data: Dict[str, Any]) -> List[str]:
    """
    Generates human-readable badges based on trade characteristics.
    """
    badges = []

    # Liquidity
    if trade.get('open_interest', 0) > 1000 and trade.get('volume', 0) > 500:
        badges.append("High Liquidity")

    # Earnings
    if trade.get('is_earnings_safe', True):
        badges.append("Earnings Safe")

    # IV Edge
    iv_rank = trade.get('iv_rank', 0)
    if trade['strategy_type'] == 'credit' and iv_rank > 50:
        badges.append("IV Edge")
    elif trade['strategy_type'] == 'debit' and iv_rank < 30:
        badges.append("IV Edge")

    return badges

def check_trend_alignment(trade: Dict[str, Any], market_data: Dict[str, Any]) -> bool:
    """
    Checks if the trade's sentiment aligns with the market trend.
    """
    sentiment = trade.get('sentiment', 'NEUTRAL')
    trend = market_data.get('trend', 'NEUTRAL') # Assume market_data has a 'trend' field

    if sentiment == "BULLISH" and trend in ["UP", "NEUTRAL"]:
        return True
    if sentiment == "BEARISH" and trend in ["DOWN", "NEUTRAL"]:
        return True

    return False
