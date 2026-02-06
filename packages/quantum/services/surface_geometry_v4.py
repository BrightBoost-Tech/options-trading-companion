"""
Arb-Free Surface Geometry v4

Canonical artifact for IV surface construction with:
- Per-expiry smile construction
- Butterfly arbitrage detection and convexification
- Calendar arbitrage detection (total variance monotonicity)
- Deterministic hashing with LineageSigner
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

import logging
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

# Butterfly arbitrage threshold (minimum second derivative)
BUTTERFLY_EPSILON = 1e-6

# Calendar arbitrage tolerance for total variance monotonicity
CALENDAR_VARIANCE_EPSILON = 1e-8

# Minimum points per expiry to build a valid smile
MIN_STRIKES_PER_EXPIRY = 3


# =============================================================================
# Pydantic Models - Canonical Data Structures
# =============================================================================

class CanonicalSmilePoint(BaseModel):
    """A single point on an IV smile curve."""
    model_config = ConfigDict(frozen=True)

    strike: float = Field(..., description="Strike price")
    moneyness: float = Field(..., description="Strike / Spot (log-moneyness optional)")
    iv: float = Field(..., description="Implied volatility (annualized)")
    bid_iv: Optional[float] = Field(None, description="IV from bid price")
    ask_iv: Optional[float] = Field(None, description="IV from ask price")
    delta: Optional[float] = Field(None, description="Option delta")
    vega: Optional[float] = Field(None, description="Option vega")
    is_call: bool = Field(..., description="True for call, False for put")
    convexified: bool = Field(False, description="True if adjusted for butterfly arb")

    def to_canonical_dict(self) -> Dict[str, Any]:
        """Convert to deterministic dict for hashing."""
        return {
            "strike": normalize_float(self.strike),
            "moneyness": normalize_float(self.moneyness),
            "iv": normalize_float(self.iv),
            "bid_iv": normalize_float(self.bid_iv) if self.bid_iv else None,
            "ask_iv": normalize_float(self.ask_iv) if self.ask_iv else None,
            "delta": normalize_float(self.delta) if self.delta else None,
            "vega": normalize_float(self.vega) if self.vega else None,
            "is_call": self.is_call,
            "convexified": self.convexified,
        }


class PerExpirySmile(BaseModel):
    """IV smile for a single expiration date."""
    model_config = ConfigDict(frozen=True)

    expiry: str = Field(..., description="Expiration date YYYY-MM-DD")
    dte: int = Field(..., description="Days to expiration")
    time_to_expiry: float = Field(..., description="Years to expiration")
    total_variance: float = Field(..., description="IV^2 * T for calendar arb check")
    points: List[CanonicalSmilePoint] = Field(default_factory=list)
    atm_iv: Optional[float] = Field(None, description="ATM implied volatility")
    butterfly_arb_detected: bool = Field(False, description="Butterfly arb found")
    butterfly_arb_count: int = Field(0, description="Number of butterfly arb points")

    def to_canonical_dict(self) -> Dict[str, Any]:
        """Convert to deterministic dict for hashing."""
        return {
            "expiry": self.expiry,
            "dte": self.dte,
            "time_to_expiry": normalize_float(self.time_to_expiry),
            "total_variance": normalize_float(self.total_variance),
            "points": [p.to_canonical_dict() for p in self.points],
            "atm_iv": normalize_float(self.atm_iv) if self.atm_iv else None,
            "butterfly_arb_detected": self.butterfly_arb_detected,
            "butterfly_arb_count": self.butterfly_arb_count,
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
    calendar_arb_detected: bool = Field(False)
    calendar_arb_expiries: List[str] = Field(default_factory=list)

    def to_canonical_dict(self) -> Dict[str, Any]:
        """Convert to deterministic dict for hashing."""
        return {
            "symbol": self.symbol,
            "spot": normalize_float(self.spot),
            "risk_free_rate": normalize_float(self.risk_free_rate),
            "dividend_yield": normalize_float(self.dividend_yield),
            "as_of_ts": self.as_of_ts,
            "version": self.version,
            "smiles": [s.to_canonical_dict() for s in self.smiles],
            "calendar_arb_detected": self.calendar_arb_detected,
            "calendar_arb_expiries": sorted(self.calendar_arb_expiries),
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
        """Convert to dict for storage/transport."""
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
# Core Functions
# =============================================================================

def compute_moneyness(strike: float, spot: float) -> float:
    """Compute simple moneyness as strike / spot."""
    if spot <= 0:
        return 0.0
    return strike / spot


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


def detect_butterfly_arbitrage(points: List[CanonicalSmilePoint]) -> List[int]:
    """
    Detect butterfly arbitrage violations in a smile.

    Butterfly arbitrage occurs when the second derivative of IV w.r.t. strike
    is negative, violating the convexity requirement.

    Returns indices of points that violate convexity.
    """
    if len(points) < 3:
        return []

    violations = []
    sorted_points = sorted(points, key=lambda p: p.strike)

    for i in range(1, len(sorted_points) - 1):
        p_left = sorted_points[i - 1]
        p_mid = sorted_points[i]
        p_right = sorted_points[i + 1]

        # Compute second derivative approximation
        h1 = p_mid.strike - p_left.strike
        h2 = p_right.strike - p_mid.strike

        if h1 <= 0 or h2 <= 0:
            continue

        # Second derivative: (f(x+h) - 2*f(x) + f(x-h)) / h^2
        # Using weighted formula for non-uniform grid
        d2_iv = (
            (p_right.iv - p_mid.iv) / h2 - (p_mid.iv - p_left.iv) / h1
        ) / ((h1 + h2) / 2)

        if d2_iv < -BUTTERFLY_EPSILON:
            violations.append(i)

    return violations


def convexify_smile(points: List[CanonicalSmilePoint]) -> List[CanonicalSmilePoint]:
    """
    Apply convexification to remove butterfly arbitrage.

    Uses simple linear interpolation to fix negative convexity points.
    """
    if len(points) < 3:
        return points

    sorted_points = sorted(points, key=lambda p: p.strike)
    violations = detect_butterfly_arbitrage(sorted_points)

    if not violations:
        return sorted_points

    # Create mutable list of IVs
    ivs = [p.iv for p in sorted_points]

    # Fix violations by linear interpolation
    for idx in violations:
        if idx > 0 and idx < len(ivs) - 1:
            # Linear interpolation between neighbors
            ivs[idx] = (ivs[idx - 1] + ivs[idx + 1]) / 2

    # Rebuild points with convexified IVs
    result = []
    for i, p in enumerate(sorted_points):
        if i in violations:
            result.append(CanonicalSmilePoint(
                strike=p.strike,
                moneyness=p.moneyness,
                iv=ivs[i],
                bid_iv=p.bid_iv,
                ask_iv=p.ask_iv,
                delta=p.delta,
                vega=p.vega,
                is_call=p.is_call,
                convexified=True,
            ))
        else:
            result.append(p)

    return result


def detect_calendar_arbitrage(smiles: List[PerExpirySmile]) -> List[str]:
    """
    Detect calendar arbitrage violations.

    Calendar arbitrage occurs when total variance (IV^2 * T) decreases
    with increasing time to expiry.

    Returns list of expiry dates that violate monotonicity.
    """
    if len(smiles) < 2:
        return []

    violations = []
    sorted_smiles = sorted(smiles, key=lambda s: s.time_to_expiry)

    prev_variance = 0.0
    for smile in sorted_smiles:
        if smile.total_variance < prev_variance - CALENDAR_VARIANCE_EPSILON:
            violations.append(smile.expiry)
        prev_variance = max(prev_variance, smile.total_variance)

    return violations


def find_atm_iv(points: List[CanonicalSmilePoint]) -> Optional[float]:
    """Find ATM IV as the point closest to moneyness=1.0."""
    if not points:
        return None

    closest = min(points, key=lambda p: abs(p.moneyness - 1.0))
    if abs(closest.moneyness - 1.0) < 0.1:  # Within 10% of ATM
        return closest.iv
    return None


def build_per_expiry_smile(
    contracts: List[Dict[str, Any]],
    spot: float,
    expiry: str,
    as_of: datetime,
) -> Optional[PerExpirySmile]:
    """
    Build a single per-expiry smile from option contracts.

    Args:
        contracts: List of option contracts for this expiry
        spot: Current spot price
        expiry: Expiration date string
        as_of: Current timestamp

    Returns:
        PerExpirySmile or None if insufficient data
    """
    if len(contracts) < MIN_STRIKES_PER_EXPIRY:
        return None

    dte = compute_dte(expiry, as_of)
    time_to_expiry = compute_time_to_expiry(expiry, as_of)

    if time_to_expiry <= 0:
        return None

    points = []
    for c in contracts:
        strike = c.get("strike")
        iv = c.get("iv")
        right = c.get("right", "").lower()

        if strike is None or iv is None or iv <= 0:
            continue

        moneyness = compute_moneyness(strike, spot)
        greeks = c.get("greeks") or {}

        point = CanonicalSmilePoint(
            strike=float(strike),
            moneyness=moneyness,
            iv=float(iv),
            bid_iv=None,  # Could compute from bid/ask if available
            ask_iv=None,
            delta=greeks.get("delta"),
            vega=greeks.get("vega"),
            is_call=(right == "call"),
            convexified=False,
        )
        points.append(point)

    if len(points) < MIN_STRIKES_PER_EXPIRY:
        return None

    # Detect and fix butterfly arbitrage
    violations = detect_butterfly_arbitrage(points)
    butterfly_arb_detected = len(violations) > 0

    if butterfly_arb_detected:
        points = convexify_smile(points)

    # Find ATM IV for total variance calculation
    atm_iv = find_atm_iv(points)
    total_variance = (atm_iv ** 2 * time_to_expiry) if atm_iv else 0.0

    return PerExpirySmile(
        expiry=expiry,
        dte=dte,
        time_to_expiry=time_to_expiry,
        total_variance=total_variance,
        points=sorted(points, key=lambda p: p.strike),
        atm_iv=atm_iv,
        butterfly_arb_detected=butterfly_arb_detected,
        butterfly_arb_count=len(violations),
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

    Args:
        chain: List of option contracts from MarketDataTruthLayer.option_chain()
        spot: Current spot price
        symbol: Underlying symbol
        risk_free_rate: Risk-free rate (annualized)
        dividend_yield: Dividend yield (annualized)
        as_of_ts: Construction timestamp (defaults to now)

    Returns:
        SurfaceResult with surface, hash, signature, and validation info
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
        smile = build_per_expiry_smile(contracts, spot, expiry, as_of)
        if smile:
            smiles.append(smile)
        else:
            result.warnings.append(f"Insufficient data for expiry {expiry}")

    if not smiles:
        result.errors.append("No valid smiles could be built")
        return result

    # Detect calendar arbitrage
    calendar_violations = detect_calendar_arbitrage(smiles)
    calendar_arb_detected = len(calendar_violations) > 0

    if calendar_arb_detected:
        result.warnings.append(
            f"Calendar arbitrage detected in expiries: {calendar_violations}"
        )

    # Build surface
    surface = ArbFreeSurface(
        symbol=symbol,
        spot=spot,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
        as_of_ts=as_of.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        version=SURFACE_VERSION,
        smiles=smiles,
        calendar_arb_detected=calendar_arb_detected,
        calendar_arb_expiries=calendar_violations,
    )

    # Compute content hash
    canonical_dict = surface.to_canonical_dict()
    content_hash = compute_content_hash(canonical_dict)

    # Sign the surface
    sig_result = LineageSigner.sign(canonical_dict)

    result.surface = surface
    result.is_valid = True
    result.content_hash = content_hash
    result.signature = sig_result.signature
    result.signature_status = sig_result.status

    return result


def record_surface_to_context(
    symbol: str,
    surface_result: SurfaceResult,
) -> None:
    """
    Record a surface to the current DecisionContext if active.

    Args:
        symbol: The underlying symbol
        surface_result: The constructed surface result
    """
    try:
        from packages.quantum.services.replay.decision_context import (
            get_current_decision_context,
        )

        ctx = get_current_decision_context()
        if ctx is None:
            return

        if not surface_result.is_valid or not surface_result.surface:
            return

        # Record as v4 surface key
        key = f"{symbol}:surface:v4"

        # Build metadata with content hash and quality summary
        metadata = {
            "content_hash": surface_result.content_hash,
            "signature_status": surface_result.signature_status,
            "version": SURFACE_VERSION,
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
