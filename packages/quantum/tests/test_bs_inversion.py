"""Round-trip + edge-case tests for ``bs_inversion``.

The core correctness check is round-trip: given (S, K, T, r, q, σ),
price the option, then invert the price back to σ. The recovered σ
must match the input within solver tolerance (1e-4).
"""
from __future__ import annotations

import math

import pytest

from packages.quantum.services.bs_inversion import (
    DEEP_OTM_PRICE,
    IV_MAX_BOUND,
    IV_MIN_BOUND,
    MONEYNESS_DEEP,
    TTE_MIN_DAYS,
    bs_call_price,
    bs_put_price,
    invert_iv,
)


# ---- Round-trip property tests ----------------------------------

# (S, K, T, r, q, sigma, right) — spans ATM/ITM/OTM, short/long TTE,
# typical IV range. Each row exercises a different region of the
# parameter space.
ROUND_TRIP_CASES = [
    # ATM, 30d, normal vol
    (100.0, 100.0, 30 / 365, 0.045, 0.0, 0.20, "call"),
    (100.0, 100.0, 30 / 365, 0.045, 0.0, 0.20, "put"),
    # ATM, 90d, normal vol
    (100.0, 100.0, 90 / 365, 0.045, 0.0, 0.25, "call"),
    # ITM call (slightly), 30d
    (100.0,  95.0, 30 / 365, 0.045, 0.0, 0.30, "call"),
    # OTM call (slightly), 30d
    (100.0, 105.0, 30 / 365, 0.045, 0.0, 0.30, "call"),
    # ITM put (slightly), 30d
    (100.0, 105.0, 30 / 365, 0.045, 0.0, 0.30, "put"),
    # High vol, short TTE
    (100.0, 100.0, 14 / 365, 0.045, 0.0, 0.60, "call"),
    # Low vol, long TTE
    (100.0, 100.0, 180 / 365, 0.045, 0.0, 0.12, "put"),
]


@pytest.mark.parametrize("S,K,T,r,q,sigma,right", ROUND_TRIP_CASES)
def test_invert_iv_round_trip(S, K, T, r, q, sigma, right):
    """Price with σ, then invert — recovered σ should match within tol."""
    pricer = bs_call_price if right == "call" else bs_put_price
    price = pricer(S, K, T, r, q, sigma)
    recovered = invert_iv(price, S, K, T, r, q, right)
    assert recovered is not None, f"inversion returned None for {right} σ={sigma}"
    assert abs(recovered - sigma) < 1e-4, (
        f"σ mismatch: input={sigma}, recovered={recovered}, "
        f"S={S} K={K} T={T} right={right}"
    )


# ---- bs_call / bs_put basic sanity ------------------------------

def test_bs_call_at_zero_T_is_intrinsic():
    """At T=0, call price = max(S-K, 0) (discount factors collapse)."""
    assert bs_call_price(110, 100, 0, 0.05, 0.0, 0.30) == pytest.approx(10.0)
    assert bs_call_price(90, 100, 0, 0.05, 0.0, 0.30) == pytest.approx(0.0)


def test_bs_put_call_parity():
    """C - P = S*exp(-qT) - K*exp(-rT) — fundamental BS identity."""
    S, K, T, r, q, sigma = 100, 100, 30/365, 0.045, 0.01, 0.25
    c = bs_call_price(S, K, T, r, q, sigma)
    p = bs_put_price(S, K, T, r, q, sigma)
    parity_rhs = S * math.exp(-q * T) - K * math.exp(-r * T)
    assert abs((c - p) - parity_rhs) < 1e-9


def test_bs_call_monotonic_in_sigma():
    """Vega is positive — call price strictly increases in σ."""
    S, K, T, r, q = 100, 100, 30/365, 0.045, 0.0
    prev = bs_call_price(S, K, T, r, q, 0.05)
    for sigma in [0.10, 0.20, 0.40, 0.80, 1.50]:
        cur = bs_call_price(S, K, T, r, q, sigma)
        assert cur > prev
        prev = cur


# ---- Edge-case skip behavior ------------------------------------

def test_invert_iv_short_tte_returns_none():
    """TTE < TTE_MIN_DAYS triggers gamma-blowup skip."""
    # 0.5 days < TTE_MIN_DAYS (1.0)
    T = 0.5 / 365
    price = bs_call_price(100, 100, T, 0.045, 0.0, 0.30)
    assert invert_iv(price, 100, 100, T, 0.045, 0.0, "call") is None


def test_invert_iv_deep_otm_intrinsic_returns_none():
    """Deep moneyness + price ~ intrinsic → no time value to invert."""
    # Deep ITM call: log(S/K) = log(150/100) ≈ 0.405 > MONEYNESS_DEEP (0.20)
    S, K = 150.0, 100.0
    intrinsic = S - K  # 50
    # Price exactly equal to intrinsic
    assert invert_iv(intrinsic, S, K, 30/365, 0.045, 0.0, "call") is None


def test_invert_iv_below_price_floor_returns_none():
    """Option price < DEEP_OTM_PRICE is numerical noise."""
    # Very small price — far OTM in moderate moneyness range
    S, K = 100.0, 105.0
    price = DEEP_OTM_PRICE * 0.5
    assert invert_iv(price, S, K, 30/365, 0.045, 0.0, "call") is None


def test_invert_iv_zero_bid_returns_none():
    """When bid<=0 caller signals no liquidity → skip."""
    # Use any inputs that would normally invert fine.
    S, K, T = 100.0, 100.0, 30/365
    price = bs_call_price(S, K, T, 0.045, 0.0, 0.20)
    assert invert_iv(price, S, K, T, 0.045, 0.0, "call", bid=0.0) is None


def test_invert_iv_recovered_iv_in_bounds():
    """Successfully recovered IV must satisfy IV_MIN_BOUND ≤ iv ≤ IV_MAX_BOUND."""
    S, K, T = 100.0, 100.0, 30/365
    for sigma in [0.05, 0.20, 0.80, 1.50]:
        price = bs_call_price(S, K, T, 0.045, 0.0, sigma)
        recovered = invert_iv(price, S, K, T, 0.045, 0.0, "call")
        assert recovered is not None
        assert IV_MIN_BOUND <= recovered <= IV_MAX_BOUND


def test_invert_iv_handles_put_round_trip_with_dividends():
    """Dividend yield != 0 — verify parity term carries through."""
    S, K, T, r, q, sigma = 100.0, 100.0, 60/365, 0.045, 0.02, 0.22
    price = bs_put_price(S, K, T, r, q, sigma)
    recovered = invert_iv(price, S, K, T, r, q, "put")
    assert recovered is not None
    assert abs(recovered - sigma) < 1e-4
