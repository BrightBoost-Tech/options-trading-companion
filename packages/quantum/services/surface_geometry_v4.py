"""
Arb-Free Surface Geometry v4 (Strict)

Canonical artifact for IV surface construction with:
- SVI parameterization per expiry in total variance w(k) = a + b*(rho*(k-m) + sqrt((k-m)^2 + sigma^2))
- Log-moneyness k = ln(K/F) where F = S*exp((r-q)*T)
- Butterfly arbitrage: convexity of w(k) enforced via slope monotonicity
- Calendar arbitrage: w(T,k) nondecreasing in T for each k on common grid
- Deterministic repair + enforcement: invalid if violations remain after repair
- DecisionContext recording for replay

Usage:
    from packages.quantum.services.surface_geometry_v4 import build_arb_free_surface

    result = build_arb_free_surface(
        chain=option_chain,
        spot=100.0,
        risk_free_rate=0.05,
        dividend_yield=0.01,
        as_of_ts=datetime.now(timezone.utc)
    )

    if result.is_valid:
        surface = result.surface
        print(f"Surface hash: {result.content_hash}")
"""

from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from packages.quantum.observability.canonical import (
    compute_content_hash,
    normalize_float,
)
from packages.quantum.observability.lineage import LineageSigner

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

SURFACE_VERSION = "v4"

# Butterfly arbitrage threshold for slope violations
BUTTERFLY_SLOPE_EPSILON = 1e-8

# Calendar arbitrage tolerance
CALENDAR_VARIANCE_EPSILON = 1e-8

# Minimum points per expiry to build a valid smile
MIN_STRIKES_PER_EXPIRY = 3

# SVI fitting parameters
SVI_FIT_MAX_ITERS = 200
SVI_FIT_TOLERANCE = 1e-6

# Repair loop max iterations
MAX_REPAIR_ITERS = 5

# K-grid resolution for calendar checks
K_GRID_POINTS = 21


# =============================================================================
# Pydantic Models - Canonical Data Structures
# =============================================================================

class SVIParams(BaseModel):
    """SVI model parameters for total variance w(k)."""
    model_config = ConfigDict(frozen=True)

    a: float = Field(..., description="Level parameter")
    b: float = Field(..., ge=0, description="Slope parameter (b >= 0)")
    rho: float = Field(..., ge=-1, le=1, description="Correlation (-1 < rho < 1)")
    m: float = Field(..., description="Location parameter")
    sigma: float = Field(..., gt=0, description="Curvature parameter (sigma > 0)")
    fit_rmse: float = Field(0.0, description="Fit RMSE in w-space")

    def to_canonical_dict(self) -> Dict[str, Any]:
        return {
            "a": normalize_float(self.a),
            "b": normalize_float(self.b),
            "rho": normalize_float(self.rho),
            "m": normalize_float(self.m),
            "sigma": normalize_float(self.sigma),
            "fit_rmse": normalize_float(self.fit_rmse),
        }


class CanonicalSmilePoint(BaseModel):
    """A single point on an IV smile curve."""
    model_config = ConfigDict(frozen=True)

    strike: float = Field(..., description="Strike price")
    moneyness: float = Field(..., description="Strike / Spot")
    log_moneyness: float = Field(0.0, description="ln(K/F)")
    iv: float = Field(..., description="Implied volatility (annualized)")
    total_variance: float = Field(0.0, description="iv^2 * T")
    bid_iv: Optional[float] = Field(None, description="IV from bid price")
    ask_iv: Optional[float] = Field(None, description="IV from ask price")
    delta: Optional[float] = Field(None, description="Option delta")
    vega: Optional[float] = Field(None, description="Option vega")
    is_call: bool = Field(..., description="True for call, False for put")
    convexified: bool = Field(False, description="True if adjusted for butterfly arb")

    def to_canonical_dict(self) -> Dict[str, Any]:
        return {
            "strike": normalize_float(self.strike),
            "moneyness": normalize_float(self.moneyness),
            "log_moneyness": normalize_float(self.log_moneyness),
            "iv": normalize_float(self.iv),
            "total_variance": normalize_float(self.total_variance),
            "bid_iv": normalize_float(self.bid_iv) if self.bid_iv else None,
            "ask_iv": normalize_float(self.ask_iv) if self.ask_iv else None,
            "delta": normalize_float(self.delta) if self.delta else None,
            "vega": normalize_float(self.vega) if self.vega else None,
            "is_call": self.is_call,
            "convexified": self.convexified,
        }


class PerExpirySmile(BaseModel):
    """IV smile for a single expiration date with SVI fit."""
    model_config = ConfigDict(frozen=True)

    expiry: str = Field(..., description="Expiration date YYYY-MM-DD")
    dte: int = Field(..., description="Days to expiration")
    time_to_expiry: float = Field(..., description="Years to expiration")
    forward: float = Field(..., description="Forward price F = S*exp((r-q)*T)")

    # Observed data points
    points: List[CanonicalSmilePoint] = Field(default_factory=list)

    # SVI fit
    svi_params: Optional[SVIParams] = Field(None, description="SVI fit parameters")

    # Grids (k = log-moneyness, w = total variance, iv = implied vol)
    k_grid: List[float] = Field(default_factory=list, description="Log-moneyness grid")
    w_grid: List[float] = Field(default_factory=list, description="Total variance grid")
    iv_grid: List[float] = Field(default_factory=list, description="IV grid (sqrt(w/T))")

    # ATM metrics
    atm_iv: Optional[float] = Field(None, description="ATM implied volatility")
    atm_total_variance: float = Field(0.0, description="ATM total variance w(0)")

    # Butterfly arb diagnostics
    butterfly_arb_detected_pre: bool = Field(False)
    butterfly_arb_detected_post: bool = Field(False)
    butterfly_arb_count_pre: int = Field(0)
    butterfly_arb_count_post: int = Field(0)
    butterfly_max_violation: float = Field(0.0)

    # Validity
    is_valid: bool = Field(True)

    def to_canonical_dict(self) -> Dict[str, Any]:
        return {
            "expiry": self.expiry,
            "dte": self.dte,
            "time_to_expiry": normalize_float(self.time_to_expiry),
            "forward": normalize_float(self.forward),
            "points": [p.to_canonical_dict() for p in self.points],
            "svi_params": self.svi_params.to_canonical_dict() if self.svi_params else None,
            "k_grid": [normalize_float(k) for k in self.k_grid],
            "w_grid": [normalize_float(w) for w in self.w_grid],
            "iv_grid": [normalize_float(iv) for iv in self.iv_grid],
            "atm_iv": normalize_float(self.atm_iv) if self.atm_iv else None,
            "atm_total_variance": normalize_float(self.atm_total_variance),
            "butterfly_arb_detected_pre": self.butterfly_arb_detected_pre,
            "butterfly_arb_detected_post": self.butterfly_arb_detected_post,
            "butterfly_arb_count_pre": self.butterfly_arb_count_pre,
            "butterfly_arb_count_post": self.butterfly_arb_count_post,
            "butterfly_max_violation": normalize_float(self.butterfly_max_violation),
            "is_valid": self.is_valid,
        }


class ArbFreeSurface(BaseModel):
    """Complete arb-free IV surface across all expiries."""
    model_config = ConfigDict(frozen=True)

    symbol: str = Field(..., description="Underlying symbol")
    spot: float = Field(..., description="Spot price at construction time")
    risk_free_rate: float = Field(..., description="Risk-free rate used")
    dividend_yield: float = Field(..., description="Dividend yield used")
    as_of_ts: str = Field(..., description="Construction timestamp ISO format")
    version: str = Field(default=SURFACE_VERSION)

    smiles: List[PerExpirySmile] = Field(default_factory=list)

    # Common k-grid for calendar checks
    common_k_grid: List[float] = Field(default_factory=list)

    # Calendar arb diagnostics
    calendar_arb_detected_pre: bool = Field(False)
    calendar_arb_detected_post: bool = Field(False)
    calendar_arb_count_pre: int = Field(0)
    calendar_arb_count_post: int = Field(0)
    calendar_max_violation: float = Field(0.0)
    calendar_arb_expiries: List[str] = Field(default_factory=list)

    # Repair iterations
    repair_iterations: int = Field(0)

    def to_canonical_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "spot": normalize_float(self.spot),
            "risk_free_rate": normalize_float(self.risk_free_rate),
            "dividend_yield": normalize_float(self.dividend_yield),
            "as_of_ts": self.as_of_ts,
            "version": self.version,
            "smiles": [s.to_canonical_dict() for s in self.smiles],
            "common_k_grid": [normalize_float(k) for k in self.common_k_grid],
            "calendar_arb_detected_pre": self.calendar_arb_detected_pre,
            "calendar_arb_detected_post": self.calendar_arb_detected_post,
            "calendar_arb_count_pre": self.calendar_arb_count_pre,
            "calendar_arb_count_post": self.calendar_arb_count_post,
            "calendar_max_violation": normalize_float(self.calendar_max_violation),
            "calendar_arb_expiries": sorted(self.calendar_arb_expiries),
            "repair_iterations": self.repair_iterations,
        }


@dataclass
class SurfaceResult:
    """Result of surface construction with lineage."""
    surface: Optional[ArbFreeSurface] = None
    is_valid: bool = False
    content_hash: str = ""
    signature: str = ""
    signature_status: str = "UNVERIFIED"
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "surface": self.surface.to_canonical_dict() if self.surface else None,
            "is_valid": self.is_valid,
            "content_hash": self.content_hash,
            "signature": self.signature,
            "signature_status": self.signature_status,
            "errors": self.errors,
            "warnings": self.warnings,
        }


# =============================================================================
# Math Utilities
# =============================================================================

def compute_forward(spot: float, r: float, q: float, T: float) -> float:
    """Compute forward price F = S * exp((r - q) * T)."""
    if T <= 0:
        return spot
    return spot * math.exp((r - q) * T)


def compute_log_moneyness(strike: float, forward: float) -> float:
    """Compute log-moneyness k = ln(K/F)."""
    if forward <= 0 or strike <= 0:
        return 0.0
    return math.log(strike / forward)


def compute_time_to_expiry(expiry_str: str, as_of: datetime) -> float:
    """Compute time to expiry in years."""
    try:
        expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        delta = expiry_date - as_of
        dte = max(0, delta.days)
        return dte / 365.0
    except Exception:
        return 0.0


def compute_dte(expiry_str: str, as_of: datetime) -> int:
    """Compute days to expiry."""
    try:
        expiry_date = datetime.strptime(expiry_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=timezone.utc)
        delta = expiry_date - as_of
        return max(0, delta.days)
    except Exception:
        return 0


def compute_moneyness(strike: float, spot: float) -> float:
    """Compute simple moneyness K/S."""
    if spot <= 0:
        return 0.0
    return strike / spot


# =============================================================================
# SVI Model
# =============================================================================

def svi_total_variance(k: float, a: float, b: float, rho: float, m: float, sigma: float) -> float:
    """
    SVI total variance: w(k) = a + b * (rho*(k-m) + sqrt((k-m)^2 + sigma^2))
    """
    diff = k - m
    return a + b * (rho * diff + math.sqrt(diff * diff + sigma * sigma))


def svi_w_grid(k_grid: List[float], a: float, b: float, rho: float, m: float, sigma: float) -> List[float]:
    """Evaluate SVI on a grid of k values."""
    return [svi_total_variance(k, a, b, rho, m, sigma) for k in k_grid]


def _deterministic_seed(symbol: str, expiry: str, k_obs: List[float], w_obs: List[float]) -> int:
    """Generate a deterministic seed from input data."""
    data_str = f"{symbol}|{expiry}|{len(k_obs)}|{sum(k_obs):.6f}|{sum(w_obs):.6f}"
    hash_bytes = hashlib.sha256(data_str.encode()).digest()
    return int.from_bytes(hash_bytes[:4], 'big')


def _simple_rng(seed: int):
    """Simple deterministic PRNG (Linear Congruential Generator)."""
    a, c, m = 1664525, 1013904223, 2**32
    state = seed
    while True:
        state = (a * state + c) % m
        yield state / m


def fit_svi(
    k_obs: List[float],
    w_obs: List[float],
    symbol: str = "",
    expiry: str = "",
) -> Optional[SVIParams]:
    """
    Fit SVI model to observed (k, w) data using coordinate descent.

    Deterministic: seeded by hash of inputs.
    """
    n = len(k_obs)
    if n < 3:
        return None

    # Seed RNG deterministically
    seed = _deterministic_seed(symbol, expiry, k_obs, w_obs)
    rng = _simple_rng(seed)

    # Initial guesses
    w_mean = sum(w_obs) / n
    k_mean = sum(k_obs) / n
    k_var = sum((k - k_mean) ** 2 for k in k_obs) / n if n > 1 else 0.01

    # Initial params
    a = max(0.001, w_mean * 0.8)
    b = max(0.01, 0.1)
    rho = 0.0
    m = k_mean
    sigma = max(0.01, math.sqrt(k_var) if k_var > 0 else 0.1)

    best_params = (a, b, rho, m, sigma)
    best_mse = float('inf')

    def compute_mse(a, b, rho, m, sigma):
        total = 0.0
        for k, w in zip(k_obs, w_obs):
            w_pred = svi_total_variance(k, a, b, rho, m, sigma)
            if w_pred < 0:
                return float('inf')  # Penalize negative variance
            total += (w_pred - w) ** 2
        return total / n

    # Coordinate descent with random restarts
    for restart in range(3):
        if restart > 0:
            # Perturb initial values
            a = max(0.001, w_mean * (0.5 + next(rng)))
            b = max(0.01, 0.05 + 0.15 * next(rng))
            rho = -0.5 + next(rng)
            m = k_mean + (next(rng) - 0.5) * 0.2
            sigma = max(0.01, 0.05 + 0.2 * next(rng))

        for iteration in range(SVI_FIT_MAX_ITERS):
            improved = False

            # Optimize each parameter
            for param_idx in range(5):
                # Line search
                best_val = [a, b, rho, m, sigma][param_idx]
                best_local_mse = compute_mse(a, b, rho, m, sigma)

                # Search range based on parameter
                if param_idx == 0:  # a
                    vals = [max(0.001, a + delta) for delta in [-0.01, -0.005, 0.005, 0.01]]
                elif param_idx == 1:  # b
                    vals = [max(0.001, b + delta) for delta in [-0.02, -0.01, 0.01, 0.02]]
                elif param_idx == 2:  # rho
                    vals = [max(-0.99, min(0.99, rho + delta)) for delta in [-0.1, -0.05, 0.05, 0.1]]
                elif param_idx == 3:  # m
                    vals = [m + delta for delta in [-0.05, -0.02, 0.02, 0.05]]
                else:  # sigma
                    vals = [max(0.001, sigma + delta) for delta in [-0.02, -0.01, 0.01, 0.02]]

                for val in vals:
                    test_params = [a, b, rho, m, sigma]
                    test_params[param_idx] = val
                    mse = compute_mse(*test_params)
                    if mse < best_local_mse:
                        best_local_mse = mse
                        best_val = val
                        improved = True

                # Update parameter
                if param_idx == 0:
                    a = best_val
                elif param_idx == 1:
                    b = best_val
                elif param_idx == 2:
                    rho = best_val
                elif param_idx == 3:
                    m = best_val
                else:
                    sigma = best_val

            mse = compute_mse(a, b, rho, m, sigma)
            if mse < best_mse:
                best_mse = mse
                best_params = (a, b, rho, m, sigma)

            if not improved or mse < SVI_FIT_TOLERANCE:
                break

    a, b, rho, m, sigma = best_params

    # Final validity check
    if best_mse == float('inf') or b < 0 or sigma <= 0 or abs(rho) >= 1:
        return None

    return SVIParams(
        a=a,
        b=b,
        rho=rho,
        m=m,
        sigma=sigma,
        fit_rmse=math.sqrt(best_mse) if best_mse < float('inf') else 0.0,
    )


# =============================================================================
# Butterfly Arbitrage (w(k) convexity via slope monotonicity)
# =============================================================================

def detect_butterfly_w(k_grid: List[float], w_grid: List[float]) -> Tuple[int, float]:
    """
    Detect butterfly arbitrage violations in w(k).

    Butterfly-free requires convexity: slopes must be nondecreasing.
    s_i = (w_{i+1} - w_i) / (k_{i+1} - k_i) must satisfy s_i <= s_{i+1}.

    Returns: (violation_count, max_violation_magnitude)
    """
    n = len(k_grid)
    if n < 3:
        return 0, 0.0

    violations = 0
    max_violation = 0.0

    # Compute slopes
    slopes = []
    for i in range(n - 1):
        dk = k_grid[i + 1] - k_grid[i]
        if dk > 1e-10:
            slopes.append((w_grid[i + 1] - w_grid[i]) / dk)
        else:
            slopes.append(0.0)

    # Check monotonicity of slopes
    for i in range(len(slopes) - 1):
        if slopes[i] > slopes[i + 1] + BUTTERFLY_SLOPE_EPSILON:
            violations += 1
            max_violation = max(max_violation, slopes[i] - slopes[i + 1])

    return violations, max_violation


def convexify_w(k_grid: List[float], w_grid: List[float]) -> List[float]:
    """
    Repair w(k) to ensure convexity (nondecreasing slopes).

    Uses pool-adjacent-violators (PAV) algorithm on slopes,
    then reconstructs w from corrected slopes.
    """
    n = len(k_grid)
    if n < 3:
        return list(w_grid)

    # Compute slopes
    slopes = []
    for i in range(n - 1):
        dk = k_grid[i + 1] - k_grid[i]
        if dk > 1e-10:
            slopes.append((w_grid[i + 1] - w_grid[i]) / dk)
        else:
            slopes.append(0.0)

    # PAV algorithm to make slopes nondecreasing
    iso_slopes = _isotonic_regression(slopes)

    # Reconstruct w from slopes, anchoring at first point
    w_new = [w_grid[0]]
    for i in range(n - 1):
        dk = k_grid[i + 1] - k_grid[i]
        w_new.append(w_new[-1] + iso_slopes[i] * dk)

    # Ensure all values are non-negative
    w_min = min(w_new)
    if w_min < 0:
        w_new = [w + abs(w_min) + 1e-6 for w in w_new]

    return w_new


def _isotonic_regression(values: List[float]) -> List[float]:
    """
    Pool-adjacent-violators algorithm for isotonic (nondecreasing) regression.
    """
    n = len(values)
    if n == 0:
        return []

    result = list(values)
    blocks = [[i] for i in range(n)]

    while True:
        merged = False
        i = 0
        while i < len(blocks) - 1:
            # Compute block averages
            avg_curr = sum(result[j] for j in blocks[i]) / len(blocks[i])
            avg_next = sum(result[j] for j in blocks[i + 1]) / len(blocks[i + 1])

            if avg_curr > avg_next + 1e-12:
                # Merge blocks
                merged_block = blocks[i] + blocks[i + 1]
                merged_avg = sum(result[j] for j in merged_block) / len(merged_block)
                for j in merged_block:
                    result[j] = merged_avg
                blocks[i] = merged_block
                blocks.pop(i + 1)
                merged = True
            else:
                i += 1

        if not merged:
            break

    return result


# =============================================================================
# Calendar Arbitrage (w nondecreasing in T for each k)
# =============================================================================

def build_common_k_grid(slices: List[Tuple[float, List[float], List[float]]]) -> Optional[List[float]]:
    """
    Build a common k-grid that covers the intersection of all slices.

    Args:
        slices: List of (T, k_grid, w_grid) tuples sorted by T

    Returns:
        Common k-grid or None if no overlap
    """
    if len(slices) < 2:
        return None

    # Find intersection of k ranges
    k_min = max(min(s[1]) for s in slices)
    k_max = min(max(s[1]) for s in slices)

    if k_min >= k_max:
        return None

    # Create uniform grid
    step = (k_max - k_min) / (K_GRID_POINTS - 1)
    return [k_min + i * step for i in range(K_GRID_POINTS)]


def interpolate_w_at_k(k_grid: List[float], w_grid: List[float], k_target: float) -> float:
    """Linear interpolation of w at a target k value."""
    n = len(k_grid)
    if n == 0:
        return 0.0
    if n == 1:
        return w_grid[0]

    # Clamp to range
    if k_target <= k_grid[0]:
        return w_grid[0]
    if k_target >= k_grid[-1]:
        return w_grid[-1]

    # Find bracketing points
    for i in range(n - 1):
        if k_grid[i] <= k_target <= k_grid[i + 1]:
            t = (k_target - k_grid[i]) / (k_grid[i + 1] - k_grid[i])
            return w_grid[i] + t * (w_grid[i + 1] - w_grid[i])

    return w_grid[-1]


def detect_calendar_violations(
    slices: List[Tuple[float, List[float], List[float]]],
    common_k_grid: List[float],
) -> Tuple[int, float, List[int]]:
    """
    Detect calendar arbitrage violations.

    For each k in common_k_grid, w must be nondecreasing with T.

    Returns: (violation_count, max_violation, violating_slice_indices)
    """
    if len(slices) < 2 or not common_k_grid:
        return 0, 0.0, []

    violations = 0
    max_violation = 0.0
    violating_indices = set()

    for k in common_k_grid:
        prev_w = -float('inf')
        for idx, (T, k_grid, w_grid) in enumerate(slices):
            w = interpolate_w_at_k(k_grid, w_grid, k)
            if w < prev_w - CALENDAR_VARIANCE_EPSILON:
                violations += 1
                max_violation = max(max_violation, prev_w - w)
                violating_indices.add(idx)
            prev_w = max(prev_w, w)

    return violations, max_violation, list(violating_indices)


def repair_calendar(
    slices: List[Tuple[float, List[float], List[float]]],
    common_k_grid: List[float],
) -> List[Tuple[float, List[float], List[float]]]:
    """
    Repair calendar arbitrage by ensuring w is nondecreasing in T for each k.

    Uses isotonic regression per k-point across T dimension,
    then updates each slice's w_grid.
    """
    if len(slices) < 2 or not common_k_grid:
        return slices

    n_slices = len(slices)
    n_k = len(common_k_grid)

    # Build matrix of w values: rows = k, columns = T
    w_matrix = []
    for k in common_k_grid:
        row = [interpolate_w_at_k(s[1], s[2], k) for s in slices]
        w_matrix.append(row)

    # Apply isotonic regression to each row (per k)
    for i in range(n_k):
        w_matrix[i] = _isotonic_regression(w_matrix[i])

    # Reconstruct slice w_grids by interpolating back
    new_slices = []
    for slice_idx, (T, k_grid, w_grid) in enumerate(slices):
        # For each point in this slice's k_grid, interpolate from corrected matrix
        new_w = []
        for k_point in k_grid:
            # Find position in common_k_grid and interpolate
            w_val = _interpolate_from_matrix(common_k_grid, w_matrix, slice_idx, k_point)
            new_w.append(max(0.0, w_val))
        new_slices.append((T, k_grid, new_w))

    return new_slices


def _interpolate_from_matrix(
    common_k_grid: List[float],
    w_matrix: List[List[float]],
    slice_idx: int,
    k_target: float,
) -> float:
    """Interpolate w value from corrected matrix for a given k and slice."""
    n_k = len(common_k_grid)
    if n_k == 0:
        return 0.0

    # Clamp
    if k_target <= common_k_grid[0]:
        return w_matrix[0][slice_idx]
    if k_target >= common_k_grid[-1]:
        return w_matrix[-1][slice_idx]

    # Find bracketing indices
    for i in range(n_k - 1):
        if common_k_grid[i] <= k_target <= common_k_grid[i + 1]:
            t = (k_target - common_k_grid[i]) / (common_k_grid[i + 1] - common_k_grid[i])
            return w_matrix[i][slice_idx] + t * (w_matrix[i + 1][slice_idx] - w_matrix[i][slice_idx])

    return w_matrix[-1][slice_idx]


# =============================================================================
# Legacy compatibility functions
# =============================================================================

def detect_butterfly_arbitrage(points: List[CanonicalSmilePoint]) -> List[int]:
    """Legacy function for backward compatibility."""
    if len(points) < 3:
        return []
    k_grid = [p.log_moneyness for p in sorted(points, key=lambda p: p.strike)]
    w_grid = [p.total_variance for p in sorted(points, key=lambda p: p.strike)]
    count, _ = detect_butterfly_w(k_grid, w_grid)
    return list(range(count)) if count > 0 else []


def convexify_smile(points: List[CanonicalSmilePoint]) -> List[CanonicalSmilePoint]:
    """Legacy function for backward compatibility."""
    return points  # Convexification now happens on w_grid


def detect_calendar_arbitrage(smiles: List[PerExpirySmile]) -> List[str]:
    """Legacy function for backward compatibility."""
    if len(smiles) < 2:
        return []
    # Check using ATM total variance
    sorted_smiles = sorted(smiles, key=lambda s: s.time_to_expiry)
    violations = []
    prev_w = 0.0
    for s in sorted_smiles:
        if s.atm_total_variance < prev_w - CALENDAR_VARIANCE_EPSILON:
            violations.append(s.expiry)
        prev_w = max(prev_w, s.atm_total_variance)
    return violations


def find_atm_iv(points: List[CanonicalSmilePoint]) -> Optional[float]:
    """Find ATM IV as the point closest to log_moneyness=0."""
    if not points:
        return None
    closest = min(points, key=lambda p: abs(p.log_moneyness))
    if abs(closest.log_moneyness) < 0.15:  # Within ~15% of ATM
        return closest.iv
    return None


# =============================================================================
# Main Surface Builder
# =============================================================================

def build_per_expiry_smile(
    contracts: List[Dict[str, Any]],
    spot: float,
    expiry: str,
    as_of: datetime,
    r: float,
    q: float,
    symbol: str = "",
) -> Optional[PerExpirySmile]:
    """
    Build a single per-expiry smile with SVI fit.
    """
    if len(contracts) < MIN_STRIKES_PER_EXPIRY:
        return None

    dte = compute_dte(expiry, as_of)
    T = compute_time_to_expiry(expiry, as_of)

    if T <= 0:
        return None

    F = compute_forward(spot, r, q, T)

    # Build observed points
    points = []
    k_obs = []
    w_obs = []

    for c in contracts:
        strike = c.get("strike")
        iv = c.get("iv")
        right = c.get("right", "").lower()

        if strike is None or iv is None or iv <= 0:
            continue

        k = compute_log_moneyness(strike, F)
        w = iv * iv * T
        moneyness = compute_moneyness(strike, spot)
        greeks = c.get("greeks") or {}

        point = CanonicalSmilePoint(
            strike=float(strike),
            moneyness=moneyness,
            log_moneyness=k,
            iv=float(iv),
            total_variance=w,
            delta=greeks.get("delta"),
            vega=greeks.get("vega"),
            is_call=(right == "call"),
            convexified=False,
        )
        points.append(point)
        k_obs.append(k)
        w_obs.append(w)

    if len(points) < MIN_STRIKES_PER_EXPIRY:
        return None

    # Sort by log-moneyness
    sorted_indices = sorted(range(len(k_obs)), key=lambda i: k_obs[i])
    k_obs = [k_obs[i] for i in sorted_indices]
    w_obs = [w_obs[i] for i in sorted_indices]
    points = [points[i] for i in sorted_indices]

    # Fit SVI
    svi_params = fit_svi(k_obs, w_obs, symbol, expiry)

    # Build grids
    if svi_params:
        k_grid = k_obs[:]
        w_grid = svi_w_grid(k_grid, svi_params.a, svi_params.b, svi_params.rho, svi_params.m, svi_params.sigma)
    else:
        # Fallback: use observed values
        k_grid = k_obs[:]
        w_grid = w_obs[:]

    # Check butterfly pre-repair
    butterfly_count_pre, butterfly_max_pre = detect_butterfly_w(k_grid, w_grid)
    butterfly_detected_pre = butterfly_count_pre > 0

    # Repair butterfly if needed
    if butterfly_detected_pre:
        w_grid = convexify_w(k_grid, w_grid)

    # Check butterfly post-repair
    butterfly_count_post, butterfly_max_post = detect_butterfly_w(k_grid, w_grid)
    butterfly_detected_post = butterfly_count_post > 0

    # Compute IV grid from w_grid
    iv_grid = [math.sqrt(max(0, w) / T) if T > 0 else 0.0 for w in w_grid]

    # Find ATM values (k closest to 0)
    atm_idx = min(range(len(k_grid)), key=lambda i: abs(k_grid[i]))
    atm_iv = iv_grid[atm_idx] if iv_grid else None
    atm_w = w_grid[atm_idx] if w_grid else 0.0

    # Update points with potentially convexified values
    updated_points = []
    for i, p in enumerate(points):
        if i < len(iv_grid):
            convexified = butterfly_detected_pre and (iv_grid[i] != p.iv)
            updated_points.append(CanonicalSmilePoint(
                strike=p.strike,
                moneyness=p.moneyness,
                log_moneyness=p.log_moneyness,
                iv=iv_grid[i],
                total_variance=w_grid[i] if i < len(w_grid) else p.total_variance,
                bid_iv=p.bid_iv,
                ask_iv=p.ask_iv,
                delta=p.delta,
                vega=p.vega,
                is_call=p.is_call,
                convexified=convexified,
            ))
        else:
            updated_points.append(p)

    is_valid = not butterfly_detected_post

    return PerExpirySmile(
        expiry=expiry,
        dte=dte,
        time_to_expiry=T,
        forward=F,
        points=updated_points,
        svi_params=svi_params,
        k_grid=k_grid,
        w_grid=w_grid,
        iv_grid=iv_grid,
        atm_iv=atm_iv,
        atm_total_variance=atm_w,
        butterfly_arb_detected_pre=butterfly_detected_pre,
        butterfly_arb_detected_post=butterfly_detected_post,
        butterfly_arb_count_pre=butterfly_count_pre,
        butterfly_arb_count_post=butterfly_count_post,
        butterfly_max_violation=max(butterfly_max_pre, butterfly_max_post),
        is_valid=is_valid,
    )


def build_arb_free_surface(
    chain: List[Dict[str, Any]],
    spot: float,
    symbol: str = "UNKNOWN",
    risk_free_rate: float = 0.05,
    dividend_yield: float = 0.0,
    as_of_ts: Optional[datetime] = None,
) -> SurfaceResult:
    """
    Build an arbitrage-free IV surface from an option chain.

    Implements strict no-arb enforcement:
    - SVI fit per expiry
    - Butterfly convexity in w(k) space
    - Calendar monotonicity across k-grid
    - Iterative repair with validity enforcement
    """
    result = SurfaceResult()

    if not chain:
        result.errors.append("Empty option chain")
        return result

    if spot <= 0:
        result.errors.append(f"Invalid spot price: {spot}")
        return result

    as_of = as_of_ts or datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)

    r = risk_free_rate
    q = dividend_yield

    # Group contracts by expiry
    by_expiry: Dict[str, List[Dict[str, Any]]] = {}
    for contract in chain:
        expiry = contract.get("expiry")
        if not expiry:
            continue
        if expiry not in by_expiry:
            by_expiry[expiry] = []
        by_expiry[expiry].append(contract)

    # Build per-expiry smiles
    smiles = []
    for expiry in sorted(by_expiry.keys()):
        contracts = by_expiry[expiry]
        smile = build_per_expiry_smile(contracts, spot, expiry, as_of, r, q, symbol)
        if smile:
            smiles.append(smile)
        else:
            result.warnings.append(f"Insufficient data for expiry {expiry}")

    if not smiles:
        result.errors.append("No valid smiles could be built")
        return result

    # Build slices for calendar arbitrage (sorted by T)
    smiles = sorted(smiles, key=lambda s: s.time_to_expiry)
    slices = [(s.time_to_expiry, s.k_grid, s.w_grid) for s in smiles]

    # Build common k-grid
    common_k_grid = build_common_k_grid(slices)

    # Detect calendar arb pre-repair
    calendar_count_pre = 0
    calendar_max_pre = 0.0
    calendar_violating_pre = []

    if common_k_grid and len(slices) >= 2:
        calendar_count_pre, calendar_max_pre, calendar_violating_pre = detect_calendar_violations(slices, common_k_grid)

    calendar_detected_pre = calendar_count_pre > 0

    # Iterative repair loop
    repair_iterations = 0
    for iteration in range(MAX_REPAIR_ITERS):
        repair_iterations = iteration + 1
        any_violation = False

        # 1. Calendar repair
        if common_k_grid and len(slices) >= 2:
            cal_count, _, _ = detect_calendar_violations(slices, common_k_grid)
            if cal_count > 0:
                slices = repair_calendar(slices, common_k_grid)
                any_violation = True

        # 2. Butterfly repair per slice
        new_slices = []
        for T, k_grid, w_grid in slices:
            bf_count, _ = detect_butterfly_w(k_grid, w_grid)
            if bf_count > 0:
                w_grid = convexify_w(k_grid, w_grid)
                any_violation = True
            new_slices.append((T, k_grid, w_grid))
        slices = new_slices

        if not any_violation:
            break

    # Check final state
    calendar_count_post = 0
    calendar_max_post = 0.0
    calendar_violating_post = []

    if common_k_grid and len(slices) >= 2:
        calendar_count_post, calendar_max_post, calendar_violating_post = detect_calendar_violations(slices, common_k_grid)

    calendar_detected_post = calendar_count_post > 0

    # Update smiles with repaired w_grids
    updated_smiles = []
    for i, smile in enumerate(smiles):
        T, k_grid, w_grid = slices[i]

        # Recompute IV grid
        iv_grid = [math.sqrt(max(0, w) / T) if T > 0 else 0.0 for w in w_grid]

        # Check butterfly post
        bf_count_post, bf_max_post = detect_butterfly_w(k_grid, w_grid)

        # Update points
        updated_points = []
        for j, p in enumerate(smile.points):
            if j < len(iv_grid):
                updated_points.append(CanonicalSmilePoint(
                    strike=p.strike,
                    moneyness=p.moneyness,
                    log_moneyness=p.log_moneyness,
                    iv=iv_grid[j],
                    total_variance=w_grid[j] if j < len(w_grid) else p.total_variance,
                    bid_iv=p.bid_iv,
                    ask_iv=p.ask_iv,
                    delta=p.delta,
                    vega=p.vega,
                    is_call=p.is_call,
                    convexified=True if smile.butterfly_arb_detected_pre else p.convexified,
                ))
            else:
                updated_points.append(p)

        # ATM values
        atm_idx = min(range(len(k_grid)), key=lambda i: abs(k_grid[i])) if k_grid else 0
        atm_iv = iv_grid[atm_idx] if iv_grid else smile.atm_iv
        atm_w = w_grid[atm_idx] if w_grid else smile.atm_total_variance

        is_valid = bf_count_post == 0

        updated_smiles.append(PerExpirySmile(
            expiry=smile.expiry,
            dte=smile.dte,
            time_to_expiry=smile.time_to_expiry,
            forward=smile.forward,
            points=updated_points,
            svi_params=smile.svi_params,
            k_grid=k_grid,
            w_grid=w_grid,
            iv_grid=iv_grid,
            atm_iv=atm_iv,
            atm_total_variance=atm_w,
            butterfly_arb_detected_pre=smile.butterfly_arb_detected_pre,
            butterfly_arb_detected_post=bf_count_post > 0,
            butterfly_arb_count_pre=smile.butterfly_arb_count_pre,
            butterfly_arb_count_post=bf_count_post,
            butterfly_max_violation=max(smile.butterfly_max_violation, bf_max_post),
            is_valid=is_valid,
        ))

    # Determine overall validity
    any_butterfly_post = any(s.butterfly_arb_detected_post for s in updated_smiles)
    surface_valid = not any_butterfly_post and not calendar_detected_post

    if any_butterfly_post:
        result.errors.append("Butterfly arbitrage violations remain after repair")
    if calendar_detected_post:
        violating_expiries = [smiles[i].expiry for i in calendar_violating_post if i < len(smiles)]
        result.errors.append(f"Calendar arbitrage violations remain in expiries: {violating_expiries}")

    if calendar_detected_pre and not calendar_detected_post:
        result.warnings.append("Calendar arbitrage repaired successfully")
    if any(s.butterfly_arb_detected_pre for s in updated_smiles) and not any_butterfly_post:
        result.warnings.append("Butterfly arbitrage repaired successfully")

    # Build surface
    calendar_expiries = [smiles[i].expiry for i in calendar_violating_post if i < len(smiles)]

    surface = ArbFreeSurface(
        symbol=symbol,
        spot=spot,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
        as_of_ts=as_of.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        version=SURFACE_VERSION,
        smiles=updated_smiles,
        common_k_grid=common_k_grid or [],
        calendar_arb_detected_pre=calendar_detected_pre,
        calendar_arb_detected_post=calendar_detected_post,
        calendar_arb_count_pre=calendar_count_pre,
        calendar_arb_count_post=calendar_count_post,
        calendar_max_violation=max(calendar_max_pre, calendar_max_post),
        calendar_arb_expiries=calendar_expiries,
        repair_iterations=repair_iterations,
    )

    # Compute content hash
    canonical_dict = surface.to_canonical_dict()
    content_hash = compute_content_hash(canonical_dict)

    # Sign the surface
    sig_result = LineageSigner.sign(canonical_dict)

    result.surface = surface
    result.is_valid = surface_valid
    result.content_hash = content_hash
    result.signature = sig_result.signature
    result.signature_status = sig_result.status

    return result


# =============================================================================
# DecisionContext Recording
# =============================================================================

def record_surface_to_context(
    symbol: str,
    surface_result: SurfaceResult,
) -> None:
    """
    Record a surface to the current DecisionContext if active.
    """
    try:
        from packages.quantum.services.replay.decision_context import (
            get_current_decision_context,
        )

        ctx = get_current_decision_context()
        if ctx is None:
            return

        if not surface_result.surface:
            return

        # Record as v4 surface key (even if invalid, for diagnostics)
        key = f"{symbol}:surface:v4"

        metadata = {
            "content_hash": surface_result.content_hash,
            "signature_status": surface_result.signature_status,
            "version": SURFACE_VERSION,
            "is_valid": surface_result.is_valid,
            "warnings": surface_result.warnings[:5],
            "errors": surface_result.errors[:5],
        }

        ctx.record_input(
            key=key,
            snapshot_type="surface",
            payload=surface_result.to_dict(),
            metadata=metadata,
        )

    except Exception as e:
        logger.warning(f"Failed to record surface to context: {e}")
