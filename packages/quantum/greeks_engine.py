import numpy as np

def calculate_iv_rank(current_iv, low_52w, high_52w):
    if high_52w == low_52w:
        return 0
    return ((current_iv - low_52w) / (high_52w - low_52w)) * 100

def score_trade(trade_data):
    """
    Research-Level Synthesis:
    Create a composite 'Alpha Score' for ranking suggestions.

    Score = (Theta_Yield * 0.4) + (Prob_Profit * 0.3) + (IV_Rank_Factor * 0.3)
    """
    theta = trade_data.get('theta', 0)
    margin = trade_data.get('margin_req', 1000)
    pop = trade_data.get('prob_profit', 0.50)
    iv_rank = trade_data.get('iv_rank', 0)

    # Theta Yield: Daily decay collected per dollar of risk
    if margin == 0:
        theta_yield = 0
    else:
        theta_yield = (abs(theta) / margin) * 100

    # IV Factor: Rewards selling high IV
    iv_factor = iv_rank / 100

    # Weighted Score
    score = (theta_yield * 40) + (pop * 30) + (iv_factor * 30)
    return round(score, 2)
