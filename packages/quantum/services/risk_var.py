import numpy as np

try:
    from scipy.stats import norm
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

def annual_cov_to_daily(annual_cov: np.ndarray, trading_days: int = 252) -> np.ndarray:
    """
    Converts an annualized covariance matrix to a daily covariance matrix.
    """
    return annual_cov / float(trading_days)

def portfolio_sigma(weights: np.ndarray, cov_daily: np.ndarray, covariance_scale: float = 1.0) -> float:
    """
    Calculates portfolio daily standard deviation (volatility).

    Args:
        weights: Array of portfolio weights (sums to ~1).
        cov_daily: Daily covariance matrix.
        covariance_scale: Multiplier for the covariance matrix (regime scaling).
    """
    scaled_cov = cov_daily * covariance_scale
    # Variance = w.T * Cov * w
    portfolio_variance = np.dot(weights.T, np.dot(scaled_cov, weights))
    return np.sqrt(portfolio_variance)

def _get_z_score(alpha: float) -> float:
    """Helper to get z-score from scipy or fallback."""
    if SCIPY_AVAILABLE:
        return norm.ppf(alpha)
    else:
        # Hardcoded fallbacks for common alphas
        if abs(alpha - 0.95) < 0.001:
            return 1.64485
        elif abs(alpha - 0.99) < 0.001:
            return 2.32635
        # Fallback to simple approximation or error if strictly required
        # For this task, hardcode z=1.645 for 95% is the requirement.
        return 1.645

def _get_pdf_val(z: float) -> float:
    """Helper to get pdf value from scipy or fallback."""
    if SCIPY_AVAILABLE:
        return norm.pdf(z)
    else:
        # PDF of standard normal: (1 / sqrt(2*pi)) * exp(-0.5 * z^2)
        return (1.0 / np.sqrt(2 * np.pi)) * np.exp(-0.5 * z**2)

def var_normal(net_liq: float, sigma: float, alpha: float = 0.95) -> float:
    """
    Calculates Value at Risk (VaR) using the Delta-Normal method.
    Returns a positive dollar amount representing the potential loss.

    Args:
        net_liq: Net liquidation value of the portfolio.
        sigma: Daily portfolio volatility (standard deviation).
        alpha: Confidence level (default 0.95).
    """
    z_score = _get_z_score(alpha)
    return net_liq * sigma * z_score

def cvar_normal(net_liq: float, sigma: float, alpha: float = 0.95) -> float:
    """
    Calculates Conditional Value at Risk (CVaR), also known as Expected Shortfall.
    Returns a positive dollar amount.

    Formula: ES = sigma * (pdf(z) / (1 - alpha)) * value
    """
    z_score = _get_z_score(alpha)
    pdf_val = _get_pdf_val(z_score)

    # Expected tail loss factor
    tail_loss_factor = pdf_val / (1.0 - alpha)
    return net_liq * sigma * tail_loss_factor
