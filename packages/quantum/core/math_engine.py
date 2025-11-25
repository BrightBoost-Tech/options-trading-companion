import numpy as np
import pandas as pd

class PortfolioMath:
    def __init__(self, returns_df: pd.DataFrame):
        self.returns = returns_df.values # Matrix T x N
        self.assets = returns_df.columns.tolist()
        self.n_assets = len(self.assets)
        self.n_obs = len(returns_df)

    def get_mean_returns(self):
        # Annualized Mean Returns
        # Simple mean * 252 trading days
        return np.mean(self.returns, axis=0) * 252

    def get_covariance_matrix(self):
        # Annualized Covariance
        return np.cov(self.returns, rowvar=False) * 252

    def get_coskewness_tensor(self):
        """
        Calculates the 3D Co-skewness tensor (N x N x N).
        This represents the joint tail risk between assets.
        Formula: E[(r_i - mu_i)(r_j - mu_j)(r_k - mu_k)] / TimeScaling
        """
        # 1. Center the returns (r - mu)
        centered = self.returns - np.mean(self.returns, axis=0)

        # 2. Initialize 3D tensor
        N = self.n_assets
        T = self.n_obs
        M3 = np.zeros((N, N, N))

        # 3. Vectorized calculation (faster than 3 loops)
        # We use Einstein Summation to compute the outer product of the centered returns
        # 'ti,tj,tk->ijk' means: for every timepoint t, take product of asset i, j, and k
        M3 = np.einsum('ti,tj,tk->ijk', centered, centered, centered)

        # 4. Normalize by time (unbiased estimator roughly 1/T) and Annualize
        # Note: Annualization for skewness is roughly * sqrt(252), but often treated as raw moment
        # For optimization weights, scaling consistency matters more than absolute units.
        M3 = M3 / (T - 1)

        return M3
