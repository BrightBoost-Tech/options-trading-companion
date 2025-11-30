import numpy as np
import pytest
from packages.quantum.nested.adapters import apply_biases, SymbolAdapterState

def test_apply_biases_identity():
    """Test that missing adapters result in no change."""
    mu = np.array([0.05, 0.08])
    sigma = np.identity(2) * 0.01
    tickers = ["AAPL", "GOOG"]
    adapters = {} # Empty

    adj_mu, adj_sigma = apply_biases(mu, sigma, tickers, adapters)

    np.testing.assert_array_almost_equal(adj_mu, mu)
    np.testing.assert_array_almost_equal(adj_sigma, sigma)

def test_apply_biases_clamping_mu():
    """Test that alpha adjustment is clamped to +/- 25% of raw mu."""
    mu = np.array([0.10]) # 10% return
    sigma = np.array([[0.01]])
    tickers = ["TEST"]

    # Try to double it (+0.10) -> Should be clamped to +0.025 (25% of 0.10)
    # So max is 0.125
    adapter = SymbolAdapterState(
        symbol="TEST",
        alpha_adjustment=0.10, # Huge bias
        sigma_scaler=1.0
    )
    adapters = {"TEST": adapter}

    adj_mu, _ = apply_biases(mu, sigma, tickers, adapters, max_mu_deviation=0.25)

    expected_max = 0.10 * 1.25 # 0.125
    assert np.isclose(adj_mu[0], expected_max)

    # Try to tank it (-0.10) -> Should be clamped to 0.075
    adapter.alpha_adjustment = -0.10
    adj_mu, _ = apply_biases(mu, sigma, tickers, adapters, max_mu_deviation=0.25)

    expected_min = 0.10 * 0.75 # 0.075
    assert np.isclose(adj_mu[0], expected_min)

def test_apply_biases_sigma_scaling():
    """Test that sigma is scaled correctly."""
    mu = np.array([0.05])
    sigma = np.array([[0.04]]) # Volatility = 0.2
    tickers = ["TEST"]

    # Scale up by 1.2 (20% increase in vol -> 1.44 variance)
    # Wait, sigma matrix is variance/covariance.
    # Scaler applies to 'risk' (std dev usually).
    # Logic in code: adj_sigma = sigma * (S_i * S_j)
    # If S=1.2, adj_sigma = 0.04 * 1.2 * 1.2 = 0.0576

    adapter = SymbolAdapterState(
        symbol="TEST",
        alpha_adjustment=0.0,
        sigma_scaler=1.2
    )
    adapters = {"TEST": adapter}

    _, adj_sigma = apply_biases(mu, sigma, tickers, adapters)

    expected_var = 0.04 * (1.2 ** 2)
    assert np.isclose(adj_sigma[0,0], expected_var)

def test_apply_biases_sigma_clamping():
    """Test that sigma scaler is clamped."""
    mu = np.array([0.05])
    sigma = np.array([[0.01]])
    tickers = ["TEST"]

    # Try to scale by 2.0 (above max 1.5)
    adapter = SymbolAdapterState("TEST", 0.0, 2.0)
    adapters = {"TEST": adapter}

    _, adj_sigma = apply_biases(mu, sigma, tickers, adapters, max_sigma_scaler=1.5)

    expected_var = 0.01 * (1.5 ** 2)
    assert np.isclose(adj_sigma[0,0], expected_var)
