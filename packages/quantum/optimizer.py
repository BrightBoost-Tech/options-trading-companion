"""Portfolio Optimizer - Classical Mode"""
import numpy as np
from scipy.optimize import minimize
from typing import Dict, List, Optional
from enum import Enum


class OptimizationMode(str, Enum):
    CLASSICAL = "classical"
    MV = "mean-variance"
    MVS = "mean-variance-skew"


class Portfolio:
    def __init__(self, weights: Dict[str, float], metrics: Dict[str, float], 
                 backend: str, assets: List[str] = None):
        self.weights = weights
        self.metrics = metrics
        self.backend = backend
        self.assets = assets or [f"asset_{i}" for i in range(len(weights))]


def optimize_portfolio(
    mode: str,
    expected_returns: List[float],
    covariance_matrix: List[List[float]],
    constraints: Optional[Dict[str, float]] = None,
    risk_aversion: float = 2.0,
    asset_names: Optional[List[str]] = None
) -> Dict:
    if constraints is None:
        constraints = {
            'max_weight_per_asset': 0.50,  # Changed from 0.25 to 0.50
            'min_weight_per_asset': 0.05   # Minimum 5% per asset
        }
    
    n_assets = len(expected_returns)
    mu = np.array(expected_returns)
    Sigma = np.array(covariance_matrix)
    
    if Sigma.shape != (n_assets, n_assets):
        raise ValueError(f"Covariance matrix shape {Sigma.shape} doesn't match returns length {n_assets}")
    
    eigenvalues = np.linalg.eigvals(Sigma)
    if np.any(eigenvalues < -1e-8):
        Sigma = Sigma + np.eye(n_assets) * 1e-6
    
    max_weight = constraints.get('max_weight_per_asset', 0.50)
    min_weight = constraints.get('min_weight_per_asset', 0.05)
    
    def objective(w):
        portfolio_return = np.dot(mu, w)
        portfolio_variance = np.dot(w, np.dot(Sigma, w))
        
        if mode == OptimizationMode.MVS:
            skew_bonus = 0.1 * np.sum(w ** 3)
            return -(portfolio_return - risk_aversion * portfolio_variance + skew_bonus)
        
        return -(portfolio_return - risk_aversion * portfolio_variance)
    
    cons = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}]
    bounds = [(min_weight, max_weight) for _ in range(n_assets)]
    
    # Start with equal weights
    w0 = np.ones(n_assets) / n_assets
    
    result = minimize(
        objective, 
        w0, 
        method='SLSQP', 
        bounds=bounds, 
        constraints=cons,
        options={'maxiter': 1000, 'ftol': 1e-9}
    )
    
    if not result.success:
        print(f"Warning: Optimization did not fully converge: {result.message}")
    
    weights = result.x
    
    portfolio_return = np.dot(mu, weights)
    portfolio_variance = np.dot(weights, np.dot(Sigma, weights))
    portfolio_std = np.sqrt(portfolio_variance)
    sharpe = portfolio_return / (portfolio_std + 1e-10)
    maxDD_est = -2.0 * portfolio_std
    
    if asset_names:
        weight_dict = {name: float(w) for name, w in zip(asset_names, weights)}
    else:
        weight_dict = {f"asset_{i}": float(w) for i, w in enumerate(weights)}
    
    return {
        'weights': weight_dict,
        'backend': f'classical-{mode}',
        'mode': mode,
        'sharpe_est': float(sharpe),
        'maxDD_est': float(maxDD_est),
        'portfolio_return': float(portfolio_return),
        'portfolio_std': float(portfolio_std),
        'risk_aversion': risk_aversion,
        'optimization_status': 'success' if result.success else 'partial'
    }


def compare_optimizations(
    expected_returns: List[float],
    covariance_matrix: List[List[float]],
    constraints: Optional[Dict[str, float]] = None,
    asset_names: Optional[List[str]] = None
) -> Dict:
    mv_result = optimize_portfolio(
        OptimizationMode.MV,
        expected_returns,
        covariance_matrix,
        constraints,
        risk_aversion=2.0,
        asset_names=asset_names
    )
    
    mvs_result = optimize_portfolio(
        OptimizationMode.MVS,
        expected_returns,
        covariance_matrix,
        constraints,
        risk_aversion=2.0,
        asset_names=asset_names
    )
    
    return {
        'mean_variance': mv_result,
        'mean_variance_skew': mvs_result,
        'comparison': {
            'sharpe_improvement': mvs_result['sharpe_est'] - mv_result['sharpe_est'],
            'return_improvement': mvs_result['portfolio_return'] - mv_result['portfolio_return'],
        }
    }
