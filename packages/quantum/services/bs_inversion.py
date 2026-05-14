"""Black-Scholes pricing + implied volatility inversion.

Used by ``HistoricalIVService`` to compute IV from historical option prices
that lack pre-computed IV: Polygon's snapshot endpoint provides IV for the
"now" view only, while historical aggregates provide closing prices but no
IV. This module fills the gap so the existing
``IVPointService.compute_atm_iv_target_from_chain`` interpolation can run
on historical data unchanged.

Reuses scipy + numpy (already in ``packages/quantum/requirements.txt``).
No new dependency added.

See ``docs/loud_error_doctrine.md`` H9 convention (verify outcome of every
operation; here, every returned IV is sanity-bounded and edge cases
explicitly return None so callers can handle them).
"""
from __future__ import annotations

import logging
import math
from typing import Literal, Optional

from scipy.optimize import brentq
from scipy.stats import norm

logger = logging.getLogger(__name__)

# Sanity bounds for computed IV. Values outside this range are numerical
# artifacts, not real implied volatility — return None and let the caller
# skip the contract.
IV_MIN_BOUND = 0.01  # 1%  — below this is numerical noise
IV_MAX_BOUND = 5.00  # 500% — above this is meaningless / blowup

# Edge-case thresholds (per α design diagnostic STEP 2c).
TTE_MIN_DAYS = 1.0        # Skip when TTE < 1 day (gamma blowup region)
MONEYNESS_DEEP = 0.20     # |log(S/K)| > 0.20 + price ~ intrinsic → skip
DEEP_OTM_PRICE = 0.05     # Option price < $0.05 → numerical noise


def bs_call_price(
    S: float, K: float, T: float, r: float, q: float, sigma: float,
) -> float:
    """Black-Scholes call price.

    Parameters
    ----------
    S : spot price
    K : strike
    T : time to expiry in years
    r : risk-free rate (annualized, continuously compounded)
    q : dividend yield (annualized)
    sigma : volatility (annualized)

    Returns
    -------
    Call price at the given inputs. Degenerate cases (T <= 0 or
    sigma <= 0) return intrinsic value under risk-neutral discounting.
    """
    if T <= 0 or sigma <= 0:
        return max(0.0, S * math.exp(-q * T) - K * math.exp(-r * T))

    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    return (
        S * math.exp(-q * T) * norm.cdf(d1)
        - K * math.exp(-r * T) * norm.cdf(d2)
    )


def bs_put_price(
    S: float, K: float, T: float, r: float, q: float, sigma: float,
) -> float:
    """Black-Scholes put price via put-call parity.

    ``put = call - S * exp(-q*T) + K * exp(-r*T)``
    """
    call = bs_call_price(S, K, T, r, q, sigma)
    return call - S * math.exp(-q * T) + K * math.exp(-r * T)


def _vega(
    S: float, K: float, T: float, r: float, q: float, sigma: float,
) -> float:
    """Black-Scholes vega — same for call and put. Used by the
    Newton-Raphson fallback."""
    if T <= 0 or sigma <= 0:
        return 0.0
    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * sqrt_T)
    return S * math.exp(-q * T) * sqrt_T * norm.pdf(d1)


def _newton_fallback(
    price: float, S: float, K: float, T: float, r: float, q: float,
    right: Literal["call", "put"],
    max_iter: int = 50,
) -> Optional[float]:
    """Newton-Raphson fallback when brentq fails to bracket.

    Common when intrinsic value is near the option price — the function
    becomes nearly flat in one direction of σ, breaking brentq's
    sign-change requirement.
    """
    pricer = bs_call_price if right == "call" else bs_put_price
    sigma = 0.5  # Initial guess: 50% IV — reasonable midpoint

    for _ in range(max_iter):
        try:
            f = pricer(S, K, T, r, q, sigma) - price
            vega = _vega(S, K, T, r, q, sigma)

            if vega < 1e-10:
                # Vega too small to make progress — function is flat.
                return None

            sigma_new = sigma - f / vega

            if abs(sigma_new - sigma) < 1e-6:
                return sigma_new if IV_MIN_BOUND <= sigma_new <= IV_MAX_BOUND else None

            sigma = max(IV_MIN_BOUND, min(IV_MAX_BOUND, sigma_new))
        except (ValueError, ZeroDivisionError):
            return None

    return None


def invert_iv(
    price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    q: float,
    right: Literal["call", "put"],
    *,
    bid: Optional[float] = None,
    ask: Optional[float] = None,
) -> Optional[float]:
    """Invert Black-Scholes to compute implied volatility from option price.

    Primary solver: scipy.optimize.brentq over [IV_MIN_BOUND, IV_MAX_BOUND].
    Fallback: Newton-Raphson when brentq fails to bracket (e.g., when the
    option price is near intrinsic value).

    Returns
    -------
    A float in [IV_MIN_BOUND, IV_MAX_BOUND] when inversion succeeds and
    edge-case skips don't fire. Returns None otherwise so the caller can
    skip the contract cleanly.

    Edge cases that return None (per α design diagnostic STEP 2c):
    - TTE < TTE_MIN_DAYS (gamma blowup)
    - Deep moneyness AND price ~ intrinsic (no time value to invert)
    - Option price below DEEP_OTM_PRICE (numerical noise)
    - bid <= 0 (no liquidity → no usable price)
    - brentq + Newton both fail to converge
    - Computed IV outside sanity bounds
    """
    # TTE too short — gamma blowup.
    if T < (TTE_MIN_DAYS / 365.0):
        return None

    # Deep moneyness with intrinsic-only price.
    log_m = math.log(S / K)
    if abs(log_m) > MONEYNESS_DEEP:
        intrinsic = max(0.0, S - K) if right == "call" else max(0.0, K - S)
        # Within 1% of intrinsic = essentially no time value to invert.
        if price <= intrinsic * 1.01:
            return None

    # Option price too low — numerical noise dominates.
    if price < DEEP_OTM_PRICE:
        return None

    # Liquidity gate via bid (caller-provided; optional).
    if bid is not None and bid <= 0:
        return None

    pricer = bs_call_price if right == "call" else bs_put_price

    def objective(sigma: float) -> float:
        return pricer(S, K, T, r, q, sigma) - price

    # Primary: brentq.
    iv: Optional[float] = None
    try:
        f_lo = objective(IV_MIN_BOUND)
        f_hi = objective(IV_MAX_BOUND)
        if f_lo * f_hi > 0:
            # No sign change in bracket — brentq won't work. Fall through.
            iv = _newton_fallback(price, S, K, T, r, q, right)
        else:
            iv = brentq(objective, IV_MIN_BOUND, IV_MAX_BOUND, xtol=1e-6, rtol=1e-6)
    except (ValueError, RuntimeError) as e:
        logger.debug(
            "brentq failed (S=%s K=%s T=%s right=%s price=%s): %s — trying Newton",
            S, K, T, right, price, e,
        )
        iv = _newton_fallback(price, S, K, T, r, q, right)

    if iv is None:
        return None

    if not (IV_MIN_BOUND <= iv <= IV_MAX_BOUND):
        return None

    return float(iv)
