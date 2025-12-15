import pytest
import numpy as np
import sys
from unittest.mock import patch

# Handle import paths robustly for different execution contexts (repo root vs package root)
try:
    from services.risk_var import annual_cov_to_daily, portfolio_sigma, var_normal, cvar_normal, _get_z_score
    import services.risk_var as risk_var_module
except ImportError:
    from packages.quantum.services.risk_var import annual_cov_to_daily, portfolio_sigma, var_normal, cvar_normal, _get_z_score
    import packages.quantum.services.risk_var as risk_var_module

def test_annual_cov_to_daily():
    annual = np.eye(2) * 252.0
    daily = annual_cov_to_daily(annual, trading_days=252)
    expected = np.eye(2)
    np.testing.assert_array_almost_equal(daily, expected)

def test_portfolio_sigma_sanity():
    # 2 assets, uncorrelated, each sigma=0.01 daily
    # Variance = 0.0001
    cov = np.eye(2) * 0.0001
    weights = np.array([0.5, 0.5])

    # Portfolio variance = w1^2*v1 + w2^2*v2 = 0.25*0.0001 + 0.25*0.0001 = 0.00005
    # Sigma = sqrt(0.00005) ~= 0.007071
    sigma = portfolio_sigma(weights, cov)
    expected_variance = 0.25 * 0.0001 + 0.25 * 0.0001
    expected_sigma = np.sqrt(expected_variance)

    assert abs(sigma - expected_sigma) < 1e-6

def test_portfolio_sigma_scaling():
    cov = np.eye(2) * 0.0001
    weights = np.array([0.5, 0.5])

    sigma_base = portfolio_sigma(weights, cov, covariance_scale=1.0)
    sigma_scaled = portfolio_sigma(weights, cov, covariance_scale=4.0)

    # Scale covariance by 4 -> scale sigma by sqrt(4) = 2
    assert abs(sigma_scaled - 2.0 * sigma_base) < 1e-6
    assert sigma_scaled > sigma_base

def test_var_values():
    # known case: 95% VaR for normal dist is 1.645 * sigma
    net_liq = 100000.0
    sigma = 0.01
    alpha = 0.95

    var = var_normal(net_liq, sigma, alpha)
    # With scipy, z is ~1.64485
    expected_z = 1.64485
    expected_var = net_liq * sigma * expected_z

    # Allow small tolerance for floating point / z-score precision
    assert abs(var - expected_var) < 1.0

def test_cvar_values():
    # known case: 95% CVaR is higher than VaR
    net_liq = 100000.0
    sigma = 0.01
    alpha = 0.95

    var = var_normal(net_liq, sigma, alpha)
    cvar = cvar_normal(net_liq, sigma, alpha)

    assert cvar > var

def test_monotonicity():
    net_liq = 10000.0
    sigma = 0.02

    var_95 = var_normal(net_liq, sigma, 0.95)
    var_99 = var_normal(net_liq, sigma, 0.99)

    assert var_99 > var_95

    cvar_95 = cvar_normal(net_liq, sigma, 0.95)
    cvar_99 = cvar_normal(net_liq, sigma, 0.99)

    assert cvar_99 > cvar_95

def test_fallback_logic():
    # Simulate missing scipy by patching the module attribute SCIPY_AVAILABLE
    with patch.object(risk_var_module, 'SCIPY_AVAILABLE', False):
        # 95% should return approx 1.645
        z_95 = risk_var_module._get_z_score(0.95)
        assert abs(z_95 - 1.64485) < 0.01

        # 99% should return approx 2.326
        z_99 = risk_var_module._get_z_score(0.99)
        assert abs(z_99 - 2.326) < 0.01

        # Fallback default
        z_other = risk_var_module._get_z_score(0.90)
        assert z_other == 1.645 # Logic falls back to 1.645 for unknown alphas in non-scipy mode
