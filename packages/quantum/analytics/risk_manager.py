from typing import Dict, Any, Optional
import math

class RiskBudgetManager:
    """
    Enforces regime-dependent factor risk budgets.

    Prevents the portfolio from becoming over-exposed to a single risk factor
    (e.g., Trend, Volatility, Liquidity) beyond what the current regime allows.
    """

    def __init__(self, budgets_pct: Dict[str, Dict[str, float]]):
        """
        Args:
            budgets_pct: budgets_pct[regime][factor] = max share of global risk (0.0 - 1.0).
                         Example: {'high_vol': {'trend': 0.2, 'vol': 0.5, 'liquidity': 0.3}}
        """
        self.budgets_pct = budgets_pct

    def check_trade_viability(
        self,
        proposed_trade: Dict[str, Any],
        current_portfolio_snapshot: Dict[str, Any],
        regime: str,
    ) -> bool:
        """
        Checks if adding a trade violates the risk budget for its primary driver factor.

        Args:
            proposed_trade: Dict with:
                - 'max_risk': float (max loss / VAR approximation in $)
                - 'factor_contribution': {factor: contribution_to_score}
            current_portfolio_snapshot: Dict exposing:
                - 'equity': float (Total Account Value)
                - 'max_risk_pct': float (Global max risk allowed as % of equity)
                - 'factor_risk': {factor: current_risk_notional ($)}
            regime: Current market regime string.

        Returns:
            bool: True if trade is viable (fits within budget), False otherwise.
        """
        # Extract portfolio metrics
        equity = float(current_portfolio_snapshot.get('equity', 0.0))
        max_risk_pct = float(current_portfolio_snapshot.get('max_risk_pct', 0.25)) # Default 25% global risk
        current_factor_risk_map = current_portfolio_snapshot.get('factor_risk', {})

        # Extract trade metrics
        trade_risk = float(proposed_trade.get('max_risk', 0.0))
        factor_contrib = proposed_trade.get('factor_contribution', {})

        if not factor_contrib:
            # If no factor contribution data, we can't attribute risk.
            # Default to PASS or FAIL? Assuming PASS but logging could be useful.
            return True

        # 1. Determine primary_factor = argmax |factor_contribution[f]|
        # We look for the factor that contributed most to the score (abs value)
        primary_factor = max(factor_contrib, key=lambda k: abs(factor_contrib[k]))

        # 2. Get budget for this factor in this regime
        regime_budgets = self.budgets_pct.get(regime, self.budgets_pct.get('normal', {}))
        # Default to 1.0 (100% allowed) if factor not explicitly constrained
        factor_budget_pct = regime_budgets.get(primary_factor, 1.0)

        # 3. Calculate Max Allowed Risk for this factor ($)
        # Global Max Risk ($) = max_risk_pct * equity
        # Factor Max Risk ($) = factor_budget_pct * Global Max Risk
        global_max_risk_dollars = max_risk_pct * equity
        max_factor_risk_dollars = factor_budget_pct * global_max_risk_dollars

        # 4. Current Risk for this factor ($)
        current_factor_risk = float(current_factor_risk_map.get(primary_factor, 0.0))

        # 5. New Risk if trade added
        new_factor_risk = current_factor_risk + trade_risk

        # 6. Check constraint
        return new_factor_risk <= max_factor_risk_dollars


class MorningManager:
    """
    Manages morning exit logic by computing urgency based on Conviction and Theta Decay.
    """

    def __init__(self, theta_sensitivity: float, base_floor: float):
        """
        Args:
            theta_sensitivity: Scales the impact of theta_cost_ratio (theta/NAV) on the required conviction floor.
                               Higher value = more impatient with theta decay.
            base_floor: The minimum conviction (0.0 - 1.0) required to hold a position even with zero theta decay.
        """
        self.theta_sensitivity = theta_sensitivity
        self.base_floor = base_floor

    def get_exit_urgency(
        self,
        position: Dict[str, Any],
        current_c_i: float,
        nav: float,
        vol_regime: str, # Unused in signature provided but useful for extensions
        regime_scalar: float = 1.0,
    ) -> float:
        """
        Calculates exit urgency score [0.0, 1.0].

        Args:
            position: Position dict/object expected to have 'theta' (daily P&L decay, negative).
            current_c_i: The current Conviction Coefficient [0, 1] for the position.
            nav: Net Account Value (Equity).
            vol_regime: Market regime (e.g., 'high_vol').
            regime_scalar: Multiplier for patience/impatience.
                           > 1.0 means regime is hostile/fast, increasing urgency penalty.

        Returns:
            float: 0.0 (Hold) to 1.0 (Exit Immediately).
        """
        # 1. Calculate Theta Cost Ratio
        theta = float(position.get('theta', 0.0))
        if nav <= 0:
            theta_cost_ratio = 0.0 # Safety for empty/busted account
        else:
            theta_cost_ratio = abs(theta) / nav

        # 2. Calculate Decay Penalty
        # penalty = ratio * sensitivity * regime_scalar
        decay_penalty = theta_cost_ratio * self.theta_sensitivity * regime_scalar

        # 3. Dynamic Floor
        # The required conviction to hold this position.
        # As decay gets expensive, the bar to keep holding raises.
        # Cap at 0.99 so 1.0 conviction always holds.
        dynamic_floor = min(self.base_floor + decay_penalty, 0.99)

        # 4. Compare Conviction to Floor
        if current_c_i >= dynamic_floor:
            # Conviction is strong enough to justify the theta cost
            return 0.0
        else:
            # Conviction is too low given the cost
            gap = dynamic_floor - current_c_i
            # Urgency scales with how far we are below the floor
            urgency = gap / dynamic_floor if dynamic_floor > 0 else 0.0
            return max(0.0, min(1.0, urgency))
