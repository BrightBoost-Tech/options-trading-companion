"""
Weekly Options Scout - Find high-probability credit spread opportunities
"""
import numpy as np
from typing import List, Dict
from datetime import datetime, timedelta


def calculate_iv_rank(current_iv: float, iv_history: List[float]) -> float:
    """Calculate IV rank (percentile)"""
    if not iv_history:
        return 0.5
    
    below_current = sum(1 for iv in iv_history if iv < current_iv)
    return below_current / len(iv_history)


def score_opportunity(
    symbol: str,
    iv_rank: float,
    dte: int,
    delta: float,
    credit: float,
    width: float,
    underlying_price: float
) -> Dict:
    """
    Score an option opportunity based on key factors
    Higher score = better opportunity
    """
    score = 0
    reasons = []
    
    # IV Rank scoring (higher is better for selling premium)
    if iv_rank > 0.70:
        score += 40
        reasons.append(f"Excellent IV rank ({iv_rank*100:.0f}%)")
    elif iv_rank > 0.50:
        score += 25
        reasons.append(f"Good IV rank ({iv_rank*100:.0f}%)")
    elif iv_rank > 0.30:
        score += 10
        reasons.append(f"Moderate IV rank ({iv_rank*100:.0f}%)")
    else:
        reasons.append(f"Low IV rank ({iv_rank*100:.0f}%) - not ideal for premium selling")
    
    # DTE scoring (30-45 days optimal for credit spreads)
    if 30 <= dte <= 45:
        score += 30
        reasons.append(f"Optimal DTE ({dte} days)")
    elif 21 <= dte <= 60:
        score += 15
        reasons.append(f"Acceptable DTE ({dte} days)")
    
    # Risk/Reward scoring
    max_loss = (width * 100) - (credit * 100)
    max_gain = credit * 100
    if max_loss > 0:
        risk_reward_ratio = max_gain / max_loss
        if risk_reward_ratio > 0.33:  # Getting $1 for every $3 risked
            score += 20
            reasons.append(f"Good risk/reward (1:{max_loss/max_gain:.1f})")
        elif risk_reward_ratio > 0.20:
            score += 10
            reasons.append(f"Acceptable risk/reward (1:{max_loss/max_gain:.1f})")
    
    # Delta scoring (0.25-0.35 is sweet spot)
    delta_abs = abs(delta)
    if 0.25 <= delta_abs <= 0.35:
        score += 10
        reasons.append(f"Ideal delta ({delta_abs:.2f})")
    elif 0.15 <= delta_abs <= 0.45:
        score += 5
        reasons.append(f"Acceptable delta ({delta_abs:.2f})")
    
    return {
        'score': score,
        'reasons': reasons,
        'max_gain': max_gain,
        'max_loss': max_loss,
        'risk_reward': f"1:{max_loss/max_gain:.1f}" if max_gain > 0 else "N/A"
    }


def scan_for_opportunities() -> List[Dict]:
    """
    Scan for weekly option opportunities
    Returns top opportunities ranked by score
    """
    # Mock data - in production, this would fetch real option chains
    opportunities = [
        {
            'symbol': 'SPY',
            'type': 'Credit Put Spread',
            'short_strike': 575,
            'long_strike': 570,
            'expiry': '2025-12-20',
            'dte': 37,
            'credit': 1.25,
            'width': 5,
            'iv_rank': 0.62,
            'delta': -0.30,
            'underlying_price': 590.50
        },
        {
            'symbol': 'QQQ',
            'type': 'Credit Put Spread',
            'short_strike': 495,
            'long_strike': 490,
            'expiry': '2025-12-20',
            'dte': 37,
            'credit': 1.50,
            'width': 5,
            'iv_rank': 0.68,
            'delta': -0.28,
            'underlying_price': 510.30
        },
        {
            'symbol': 'IWM',
            'type': 'Credit Put Spread',
            'short_strike': 220,
            'long_strike': 215,
            'expiry': '2025-12-20',
            'dte': 37,
            'credit': 1.10,
            'width': 5,
            'iv_rank': 0.55,
            'delta': -0.32,
            'underlying_price': 228.75
        },
        {
            'symbol': 'AAPL',
            'type': 'Credit Put Spread',
            'short_strike': 235,
            'long_strike': 230,
            'expiry': '2025-12-20',
            'dte': 37,
            'credit': 1.30,
            'width': 5,
            'iv_rank': 0.72,
            'delta': -0.29,
            'underlying_price': 245.80
        },
        {
            'symbol': 'TSLA',
            'type': 'Credit Put Spread',
            'short_strike': 350,
            'long_strike': 340,
            'expiry': '2025-12-13',
            'dte': 30,
            'credit': 2.50,
            'width': 10,
            'iv_rank': 0.78,
            'delta': -0.31,
            'underlying_price': 375.20
        }
    ]
    
    # Score each opportunity
    scored_opportunities = []
    for opp in opportunities:
        analysis = score_opportunity(
            opp['symbol'],
            opp['iv_rank'],
            opp['dte'],
            opp['delta'],
            opp['credit'],
            opp['width'],
            opp['underlying_price']
        )
        
        opp.update(analysis)
        scored_opportunities.append(opp)
    
    # Sort by score (highest first)
    scored_opportunities.sort(key=lambda x: x['score'], reverse=True)
    
    return scored_opportunities


if __name__ == '__main__':
    print("Weekly Options Scout")
    print("=" * 60)
    print()
    
    opportunities = scan_for_opportunities()
    
    print(f"Found {len(opportunities)} opportunities\n")
    print("Top 3 Trades This Week:")
    print("-" * 60)
    
    for i, opp in enumerate(opportunities[:3], 1):
        print(f"\n#{i} - {opp['symbol']} {opp['type']}")
        print(f"   Score: {opp['score']}/100")
        print(f"   Strikes: {opp['short_strike']}/{opp['long_strike']}")
        print(f"   Credit: ${opp['credit']:.2f} (Max Gain: ${opp['max_gain']:.0f})")
        print(f"   Risk/Reward: {opp['risk_reward']}")
        print(f"   Expiry: {opp['expiry']} ({opp['dte']} DTE)")
        print(f"   Why:")
        for reason in opp['reasons'][:3]:
            print(f"      • {reason}")
