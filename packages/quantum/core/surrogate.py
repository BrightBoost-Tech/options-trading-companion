import numpy as np
from scipy.optimize import minimize
from typing import List, Dict, Any

class SurrogateOptimizer:
    def solve(self, mu, sigma, coskew, constraints):
        """
        Solves the Skew-Mean-Variance problem using classical SLSQP.
        """
        num_assets = len(mu)
        lamb = constraints.get('risk_aversion', 1.0)
        gamma = constraints.get('skew_preference', 0.0)

        # 1. Define the Objective Function
        # This matches the Hamiltonian we send to Dirac-3
        def objective(weights):
            w = np.array(weights)

            # Term 1: Returns (maximize -> minimize negative)
            ret_term = -1.0 * np.dot(w, mu)

            # Term 2: Variance (minimize)
            # w.T * Sigma * w
            var_term = lamb * np.dot(w.T, np.dot(sigma, w))

            # Term 3: Skewness (maximize -> minimize negative)
            # Tensor contraction: sum(w_i * w_j * w_k * M3_ijk)
            skew_term = 0
            if gamma != 0:
                # np.einsum is the cleanest way to do cubic contraction
                skew_term = -1.0 * gamma * np.einsum('ijk,i,j,k->', coskew, w, w, w)

            return ret_term + var_term + skew_term

        # 2. Constraints
        cons = (
            {'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}, # Weights sum to 1
        )

        # 3. Bounds (0% to Max%)
        max_w = constraints.get('max_position_pct', 1.0) # Allow up to 100% in one asset
        bounds = tuple((0.0, max_w) for _ in range(num_assets))

        # 4. Initial Guess (Equal Weight)
        init_guess = np.array([1/num_assets] * num_assets)

        # 5. Run Optimization
        result = minimize(objective, init_guess, method='SLSQP', bounds=bounds, constraints=cons, options={'maxiter': 1000})

        if not result.success:
            raise ValueError(f"Optimization failed: {result.message}")

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
