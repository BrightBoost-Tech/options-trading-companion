"""
IVSurface — high-level wrapper around the arb-free surface_geometry_v4 engine.

Provides:
- .iv(strike, expiry) → interpolated IV
- .skew(expiry) → 25-delta skew
- .term_structure() → ATM IV by expiry
- .surface_metrics() → skew, kurtosis, wing richness
- Caching with 5-minute TTL

Does NOT duplicate SVI fitting or arb-repair logic — delegates to
surface_geometry_v4.build_arb_free_surface for all heavy lifting.
"""

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from packages.quantum.services.surface_geometry_v4 import (
    ArbFreeSurface,
    PerExpirySmile,
    SurfaceResult,
    build_arb_free_surface,
    interpolate_w_at_k,
    compute_log_moneyness,
    compute_forward,
)

logger = logging.getLogger(__name__)

# Cache: symbol → (IVSurface, build_timestamp)
_surface_cache: Dict[str, Tuple["IVSurface", float]] = {}
CACHE_TTL_SECONDS = 300  # 5 minutes


def get_cached_surface(
    symbol: str,
    chain: List[Dict[str, Any]],
    spot: float,
    risk_free_rate: float = 0.05,
    dividend_yield: float = 0.0,
) -> Optional["IVSurface"]:
    """
    Get or build a cached IVSurface for a symbol.

    Returns cached surface if less than CACHE_TTL_SECONDS old,
    otherwise builds a fresh one.
    """
    now = time.monotonic()
    cached = _surface_cache.get(symbol)
    if cached:
        surface, ts = cached
        if now - ts < CACHE_TTL_SECONDS:
            return surface

    # Build fresh
    surface = IVSurface.from_chain(
        chain=chain,
        spot=spot,
        symbol=symbol,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
    )
    if surface:
        _surface_cache[symbol] = (surface, now)
    return surface


def clear_cache(symbol: Optional[str] = None) -> None:
    """Clear surface cache for one or all symbols."""
    if symbol:
        _surface_cache.pop(symbol, None)
    else:
        _surface_cache.clear()


@dataclass
class IVSurface:
    """
    High-level IV surface with query methods.

    Wraps an ArbFreeSurface built by surface_geometry_v4 and provides
    interpolation, skew, term structure, and metrics extraction.
    """
    _surface: ArbFreeSurface
    _result: SurfaceResult

    @classmethod
    def from_chain(
        cls,
        chain: List[Dict[str, Any]],
        spot: float,
        symbol: str = "UNKNOWN",
        risk_free_rate: float = 0.05,
        dividend_yield: float = 0.0,
    ) -> Optional["IVSurface"]:
        """Build IVSurface from an options chain snapshot."""
        result = build_arb_free_surface(
            chain=chain,
            spot=spot,
            symbol=symbol,
            risk_free_rate=risk_free_rate,
            dividend_yield=dividend_yield,
        )
        if not result.surface:
            logger.warning(f"iv_surface_build_failed: symbol={symbol} errors={result.errors}")
            return None

        return cls(_surface=result.surface, _result=result)

    @property
    def is_valid(self) -> bool:
        return self._result.is_valid

    @property
    def symbol(self) -> str:
        return self._surface.symbol

    @property
    def spot(self) -> float:
        return self._surface.spot

    @property
    def smiles(self) -> List[PerExpirySmile]:
        return self._surface.smiles

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def iv(self, strike: float, expiry: str) -> Optional[float]:
        """
        Interpolated IV for a given (strike, expiry).

        Uses the SVI-fitted w_grid for the matching expiry slice,
        interpolates in log-moneyness space, converts back to IV.
        Returns None if expiry not in surface.
        """
        smile = self._find_smile(expiry)
        if not smile or smile.time_to_expiry <= 0:
            return None

        F = smile.forward
        k = compute_log_moneyness(strike, F)
        w = interpolate_w_at_k(smile.k_grid, smile.w_grid, k)

        if w <= 0:
            return None

        return math.sqrt(w / smile.time_to_expiry)

    def skew(self, expiry: str) -> Optional[float]:
        """
        25-delta skew for a given expiry.

        Skew = IV(25d put) - IV(25d call).
        Approximated using OTM put IV (k ≈ -0.35) minus OTM call IV (k ≈ +0.35).
        Positive skew = puts more expensive (normal equity skew).
        """
        smile = self._find_smile(expiry)
        if not smile or not smile.k_grid or smile.time_to_expiry <= 0:
            return None

        T = smile.time_to_expiry

        # 25-delta put: k ≈ -0.35 for typical vol
        # 25-delta call: k ≈ +0.35
        w_put = interpolate_w_at_k(smile.k_grid, smile.w_grid, -0.35)
        w_call = interpolate_w_at_k(smile.k_grid, smile.w_grid, 0.35)

        iv_put = math.sqrt(max(0, w_put) / T) if T > 0 else 0
        iv_call = math.sqrt(max(0, w_call) / T) if T > 0 else 0

        return iv_put - iv_call

    def term_structure(self) -> List[Dict[str, Any]]:
        """
        ATM IV by expiry — the term structure of volatility.

        Returns list sorted by DTE: [{expiry, dte, atm_iv, time_to_expiry}]
        """
        result = []
        for s in sorted(self._surface.smiles, key=lambda s: s.dte):
            if s.atm_iv is not None and s.atm_iv > 0:
                result.append({
                    "expiry": s.expiry,
                    "dte": s.dte,
                    "atm_iv": round(s.atm_iv, 4),
                    "time_to_expiry": round(s.time_to_expiry, 4),
                })
        return result

    def surface_metrics(self) -> Dict[str, Any]:
        """
        Summary metrics for the entire surface.

        Returns:
            atm_iv_front: front-month ATM IV
            atm_iv_back: back-month ATM IV
            term_slope: front/back ratio
            avg_skew: average 25-delta skew across expiries
            wing_richness: OTM put wing vs OTM call wing
            butterfly_violations: count of remaining arb violations
            calendar_violations: count of remaining arb violations
            num_expiries: number of valid smile slices
            num_points: total data points
        """
        smiles = sorted(self._surface.smiles, key=lambda s: s.dte)

        # ATM term structure
        atm_ivs = [(s.dte, s.atm_iv) for s in smiles if s.atm_iv and s.atm_iv > 0]
        atm_iv_front = atm_ivs[0][1] if atm_ivs else None
        atm_iv_back = atm_ivs[-1][1] if len(atm_ivs) > 1 else atm_iv_front

        term_slope = None
        if atm_iv_front and atm_iv_back and atm_iv_back > 0:
            term_slope = round(atm_iv_front / atm_iv_back, 4)

        # Average skew
        skews = []
        for s in smiles:
            sk = self.skew(s.expiry)
            if sk is not None:
                skews.append(sk)
        avg_skew = round(sum(skews) / len(skews), 4) if skews else None

        # Wing richness: avg OTM put IV / avg OTM call IV
        put_wing_ivs = []
        call_wing_ivs = []
        for s in smiles:
            if not s.k_grid or s.time_to_expiry <= 0:
                continue
            T = s.time_to_expiry
            for k, w in zip(s.k_grid, s.w_grid):
                if w <= 0:
                    continue
                iv_val = math.sqrt(w / T)
                if k < -0.2:
                    put_wing_ivs.append(iv_val)
                elif k > 0.2:
                    call_wing_ivs.append(iv_val)

        wing_richness = None
        if put_wing_ivs and call_wing_ivs:
            avg_put = sum(put_wing_ivs) / len(put_wing_ivs)
            avg_call = sum(call_wing_ivs) / len(call_wing_ivs)
            if avg_call > 0:
                wing_richness = round(avg_put / avg_call, 4)

        return {
            "atm_iv_front": round(atm_iv_front, 4) if atm_iv_front else None,
            "atm_iv_back": round(atm_iv_back, 4) if atm_iv_back else None,
            "term_slope": term_slope,
            "avg_skew": avg_skew,
            "wing_richness": wing_richness,
            "num_expiries": len(smiles),
            "num_points": sum(len(s.points) for s in smiles),
            "butterfly_violations": sum(s.butterfly_arb_count_post for s in smiles),
            "calendar_violations": self._surface.calendar_arb_count_post,
            "is_valid": self._result.is_valid,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_smile(self, expiry: str) -> Optional[PerExpirySmile]:
        """Find smile by expiry string."""
        for s in self._surface.smiles:
            if s.expiry == expiry:
                return s
        return None
