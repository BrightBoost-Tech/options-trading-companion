import numpy as np
from scipy.optimize import minimize

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
