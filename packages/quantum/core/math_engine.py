import numpy as np
import pandas as pd

class PortfolioMath:
    def __init__(self, returns_df: pd.DataFrame):
        self.returns = returns_df.values # Matrix T x N
        self.assets = returns_df.columns.tolist()
        self.n_assets = len(self.assets)
        self.n_obs = len(returns_df)

    def get_mean_returns(self, method='exponential'):
        """
        Calculates expected returns.
        'simple': Standard average (Past performance = Future performance)
        'exponential': Recent days matter more (Momentum / "Learned Behavior")
        """
        if method == 'simple':
            return np.mean(self.returns, axis=0) * 252

        # Exponential Moving Average of returns (Momentum Proxy)
        # We treat the mean of the last 60 days with higher weight
        T, N = self.returns.shape
        weights = np.exp(np.linspace(-1., 0., T)) # Increasing weights
        weights /= weights.sum()

        # Weighted average of columns
        weighted_returns = np.dot(weights, self.returns)
        return weighted_returns * 252

    def get_covariance_matrix(self):
        return np.cov(self.returns, rowvar=False) * 252

    def get_coskewness_tensor(self):
        # ... (Keep existing tensor logic) ...
        centered = self.returns - np.mean(self.returns, axis=0)
        M3 = np.einsum('ti,tj,tk->ijk', centered, centered, centered)
        return M3 / (len(self.returns) - 1)
