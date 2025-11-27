# packages/quantum/analytics/analytics.py

class OptionsAnalytics:
    @staticmethod
    def portfolio_beta_delta(positions):
        """
        Computes portfolio beta-weighted delta.
        Expects positions to carry:
          - delta
          - beta
          - underlying_price
        """
        total = 0.0
        for p in positions:
            delta = p.delta if hasattr(p, 'delta') else None
            beta = p.beta if hasattr(p, 'beta') else 1.0
            underlying_price = p.current_price if hasattr(p, 'current_price') else None
            if delta is None or underlying_price is None:
                continue
            # Simple beta-weighted delta term
            total += delta * beta * underlying_price
        return total

    @staticmethod
    def theta_efficiency(positions, net_liq: float) -> float:
        """
        Theta / Net Liquidity metric.
        """
        if not net_liq:
            return 0.0
        total_theta = 0.0
        for p in positions:
            theta = p.theta if hasattr(p, 'theta') else None
            if theta is None:
                continue
            total_theta += theta
        return total_theta / net_liq
