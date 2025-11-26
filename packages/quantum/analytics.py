# packages/quantum/analytics.py
import numpy as np

class OptionsAnalytics:
    @staticmethod
    def calculate_iv_rank(current_iv: float, low_52w: float, high_52w: float) -> float:
        if high_52w == low_52w: return 0.0
        return ((current_iv - low_52w) / (high_52w - low_52w)) * 100

    @staticmethod
    def calculate_alpha_score(trade_data: dict) -> float:
        """
        Research-Level Synthesis:
        Scores trades based on 'Capital Efficiency' and 'Probability'.

        Formula:
        Score = (Theta_Yield_Score * 0.4) + (POP_Score * 0.4) + (IV_Score * 0.2)
        """
        theta = abs(float(trade_data.get('greeks', {}).get('theta', 0)))
        margin = float(trade_data.get('margin_requirement', 1000))
        pop = float(trade_data.get('prob_profit', 0.50))
        iv_rank = float(trade_data.get('iv_rank', 0))

        # 1. Theta Yield: How much daily cash do I get for my margin?
        # Normalized: 0.1% daily yield is great (score 100), 0% is bad (score 0)
        daily_yield = (theta / margin)
        yield_score = min(daily_yield * 1000 * 100, 100) # Cap at 100

        # 2. Probability of Profit (POP)
        # Normalized: 50% is baseline, 90% is max
        pop_score = pop * 100

        # 3. IV Rank (Mean Reversion Potential)
        iv_score = iv_rank

        # Composite Weighted Score
        final_score = (yield_score * 0.4) + (pop_score * 0.4) + (iv_score * 0.2)
        return round(final_score, 1)