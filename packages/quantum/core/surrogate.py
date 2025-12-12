import numpy as np
from scipy.optimize import minimize
from typing import List, Dict, Any, Tuple

class SurrogateOptimizer:
    def solve(self, mu, sigma, coskew, constraints,
              current_weights: np.ndarray = None,
              greek_sensitivities: Dict[str, np.ndarray] = None,
              shock_losses: np.ndarray = None) -> np.ndarray:
        """
        Solves the Skew-Mean-Variance problem using classical SLSQP.
        Now includes V3 features: Turnover Penalty, Greek Budgets, Drawdown Constraints.

        Args:
            mu: Expected returns (n,)
            sigma: Covariance matrix (n,n)
            coskew: Coskewness tensor (n,n,n)
            constraints: Dictionary of scalar constraints (risk_aversion, etc.)
            current_weights: Existing portfolio weights (n,) for turnover penalty.
            greek_sensitivities: Dict of greek sensitivity vectors (n,), e.g. {'delta': [...], 'vega': [...]}.
            shock_losses: Vector of estimated losses per asset in a market shock scenario.

        Returns:
            Optimal weights vector (n,)
        """
        num_assets = len(mu)
        lamb = constraints.get('risk_aversion', 1.0)
        gamma = constraints.get('skew_preference', 0.0)
        eta = constraints.get('turnover_penalty', 0.0) # Turnover penalty coefficient

        # Greek Budgets (e.g., {'delta': 0.5} means |Portfolio Delta| <= 0.5)
        greek_budgets = constraints.get('greek_budgets', {})

        # Drawdown Constraint (e.g. max_drawdown: 0.20 means Portfolio Shock Loss >= -0.20)
        # shock_losses are typically negative numbers (e.g. -0.30 for 30% loss)
        max_dd = constraints.get('max_drawdown', None)

        # 1. Define the Objective Function
        def objective(weights):
            w = np.array(weights)

            # Term 1: Returns (maximize -> minimize negative)
            ret_term = -1.0 * np.dot(w, mu)

            # Term 2: Variance (minimize)
            # w.T * Sigma * w
            var_term = lamb * np.dot(w.T, np.dot(sigma, w))

            # Term 3: Skewness (maximize -> minimize negative)
            skew_term = 0
            if gamma != 0:
                # np.einsum is the cleanest way to do cubic contraction
                skew_term = -1.0 * gamma * np.einsum('ijk,i,j,k->', coskew, w, w, w)

            # Term 4: Turnover Penalty (minimize sum of squared changes)
            turnover_term = 0
            if eta > 0 and current_weights is not None:
                diff = w - current_weights
                turnover_term = eta * np.dot(diff, diff)

            return ret_term + var_term + skew_term + turnover_term

        # 2. Constraints
        cons = []

        # 2.1 Full Investment
        cons.append({'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0})

        # 2.2 Greek Budgets
        if greek_sensitivities and greek_budgets:
            for greek, limit in greek_budgets.items():
                if greek in greek_sensitivities:
                    sens = greek_sensitivities[greek]
                    # |w . sens| <= limit  =>  -limit <= w.sens <= limit
                    # Implemented as two inequalities
                    # 1. limit - w.sens >= 0
                    cons.append({'type': 'ineq', 'fun': lambda w, s=sens, l=limit: l - np.dot(w, s)})
                    # 2. w.sens - (-limit) >= 0 => w.sens + limit >= 0
                    cons.append({'type': 'ineq', 'fun': lambda w, s=sens, l=limit: np.dot(w, s) + l})

        # 2.3 Scenario Drawdown Constraint
        if max_dd is not None and shock_losses is not None:
            # Portfolio Shock Loss = w . shock_losses
            # Constraint: w . shock_losses >= -max_dd
            # Rearranged: w . shock_losses + max_dd >= 0
            cons.append({'type': 'ineq', 'fun': lambda w: np.dot(w, shock_losses) + max_dd})

        # 3. Bounds (0% to Max%)
        # V3: Bounds can be passed per-asset if 'bounds' key exists in constraints
        # otherwise use global max_position_pct
        if 'bounds' in constraints:
            bounds = tuple(constraints['bounds'])
        else:
            max_w = constraints.get('max_position_pct', 1.0) # Allow up to 100% in one asset
            bounds = tuple((0.0, max_w) for _ in range(num_assets))

        # 4. Initial Guess
        # Use current weights if available to speed up convergence
        if current_weights is not None:
            init_guess = current_weights
        else:
            init_guess = np.array([1/num_assets] * num_assets)

        # 5. Run Optimization
        # V3: Increased maxiter for complex constraints
        result = minimize(objective, init_guess, method='SLSQP', bounds=bounds, constraints=cons, options={'maxiter': 2000})

        if not result.success:
            # Fallback: Relax constraints? Or return current/equal weights?
            # For now, raise error but log it clearly
            # raise ValueError(f"Optimization failed: {result.message}")
            print(f"Warning: Optimization convergence failed ({result.message}). Returning initial guess.")
            return init_guess

        return result.x # Returns array of float weights


def optimize_for_compounding(
    suggestions: List[Dict[str, Any]],
    current_holdings: List[Any],
    account_value: float,
    target_value: float = 5000.0,
) -> List[Dict[str, Any]]:
    """
    Given enriched trade suggestions, compute compounding-related metrics
    and return a new list sorted by their contribution to geometric growth.
    This is an additive helper and should not change any existing behavior.
    """
    for suggestion in suggestions:
        win_amt = float(suggestion.get("max_profit", 0.0))
        loss_amt = float(suggestion.get("max_loss", 0.0))
        p = float(suggestion.get("prob_profit", 0.0))
        q = 1.0 - p
        ev_amount = float(suggestion.get("ev_amount", 0.0))

        # Approximate a variance and geometric growth contribution
        variance = ((win_amt + loss_amt) ** 2) * p * q  # simple heuristic

        # Avoid div/0 if account_value is weird
        denom = max(account_value, 1.0)

        # Approx. Geometric Growth ~ Arithmetic Mean - 0.5 * Variance / Wealth
        # (This comes from Kelly criterion derivations)
        geo_growth = ev_amount - (variance / (2.0 * denom))

        # Approximate est_trades_to_target
        if ev_amount > 0:
            est_trades_to_target = max(0.0, (target_value - account_value) / ev_amount)
        else:
            est_trades_to_target = float("inf")

        suggestion.setdefault("metrics", {})
        suggestion["metrics"].update({
            "geometric_growth_contribution": geo_growth,
            "est_trades_to_target": est_trades_to_target,
            "volatility_drag_coefficient": variance / denom,
        })

    # Sort by geo_growth descending
    suggestions.sort(key=lambda x: x["metrics"].get("geometric_growth_contribution", 0), reverse=True)

    return suggestions
