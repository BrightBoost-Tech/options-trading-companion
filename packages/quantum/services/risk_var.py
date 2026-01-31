import math
import numpy as np

# Removed scipy dependency for performance
# Performance: ~100x faster than scipy.stats.norm.ppf/pdf
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

def _fast_norm_ppf(p: float) -> float:
    """
    Approximation of the inverse cumulative normal distribution function.
    Source: Peter J. Acklam
    Relative error < 1.15e-9
    """
    if p <= 0.0 or p >= 1.0:
        if p <= 0: return -float('inf')
        if p >= 1: return float('inf')

    # Coefficients in rational approximations
    a1 = -3.969683028665376e+01
    a2 =  2.209460984245205e+02
    a3 = -2.759285104469687e+02
    a4 =  1.383577518672690e+02
    a5 = -3.066479806614716e+01
    a6 =  2.506628277459239e+00

    b1 = -5.447609879822406e+01
    b2 =  1.615858368580409e+02
    b3 = -1.556989798598866e+02
    b4 =  6.680131188771972e+01
    b5 = -1.328068155288572e+01

    c1 = -7.784894002430293e-03
    c2 = -3.223964580411365e-01
    c3 = -2.400758277161838e+00
    c4 = -2.549732539343734e+00
    c5 =  4.374664141464968e+00
    c6 =  2.938163982698783e+00

    d1 =  7.784695709041462e-03
    d2 =  3.224671290700398e-01
    d3 =  2.445134137142996e+00
    d4 =  3.754408661907416e+00

    p_low = 0.02425
    p_high = 1.0 - p_low

    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c1 * q + c2) * q + c3) * q + c4) * q + c5) * q + c6) / \
               ((((d1 * q + d2) * q + d3) * q + d4) * q + 1.0)
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a1 * r + a2) * r + a3) * r + a4) * r + a5) * r + a6) * q / \
               (((((b1 * r + b2) * r + b3) * r + b4) * r + b5) * r + 1.0)
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((c1 * q + c2) * q + c3) * q + c4) * q + c5) * q + c6) / \
                ((((d1 * q + d2) * q + d3) * q + d4) * q + 1.0)

def _fast_norm_pdf(x: float) -> float:
    """
    Fast PDF of standard normal: (1 / sqrt(2*pi)) * exp(-0.5 * x^2)
    """
    return 0.3989422804014327 * math.exp(-0.5 * x * x)

def _get_z_score(alpha: float) -> float:
    """
    Helper to get z-score.
    Uses fast rational approximation (Acklam's algorithm).
    """
    return _fast_norm_ppf(alpha)

def _get_pdf_val(z: float) -> float:
    """
    Helper to get pdf value.
    Uses math.exp for speed.
    """
    return _fast_norm_pdf(z)

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
