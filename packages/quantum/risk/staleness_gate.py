"""
Staleness Gate — blocks new position entries when market data is stale.

Probes SPY + QQQ freshness via MarketDataTruthLayer. If the most recent
successful Polygon data pull is older than the configured threshold,
entries are blocked. Exits are never blocked.

Environment Variables:
    STALENESS_GATE_ENABLED       - "1" to enable (default: "1")
    STALENESS_GATE_MAX_AGE_SEC   - Max acceptable data age in seconds (default: "600" = 10 min)
    STALENESS_GATE_PROBE_SYMBOLS - Comma-separated probe symbols (default: "SPY,QQQ")
"""

import os
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Probe these symbols as a canary for Polygon health
_DEFAULT_PROBE_SYMBOLS = "SPY,QQQ"
_DEFAULT_MAX_AGE_SEC = 600  # 10 minutes


@dataclass
class StalenessGateResult:
    """Result of the staleness gate check."""
    blocked: bool
    reason: str
    age_seconds: Optional[float]  # worst-case data age, None if unknown
    stale_symbols: list


def check_staleness_gate(regime: Optional[str] = None) -> StalenessGateResult:
    """
    Check whether market data is too stale to open new positions.

    Args:
        regime: Optional market regime ('normal' | 'suppressed' | 'chop' |
            'rebound' | 'elevated' | 'shock'). Passed through to
            compute_market_data_freshness, which uses it to gate the
            vendor-quality clause (active only in shock/elevated; see
            ops_health_service._REGIME_VENDOR_QUALITY_GATED for the
            2026-05-18 incident that motivated this). Callers that have
            regime context (e.g. mid-cycle re-checks) should pass it;
            callers that don't (e.g. pre-cycle entry gates) leave it
            None and the function resolves the last recorded regime
            internally, failing closed if that lookup yields nothing.

    Returns StalenessGateResult with blocked=True if data is stale.
    Fails closed (blocks) on errors — if we can't verify freshness,
    we don't trust the data.
    """
    enabled = os.environ.get("STALENESS_GATE_ENABLED", "1") == "1"
    if not enabled:
        return StalenessGateResult(
            blocked=False, reason="staleness_gate_disabled",
            age_seconds=None, stale_symbols=[],
        )

    max_age_sec = int(os.environ.get("STALENESS_GATE_MAX_AGE_SEC", str(_DEFAULT_MAX_AGE_SEC)))
    probe_symbols_raw = os.environ.get("STALENESS_GATE_PROBE_SYMBOLS", _DEFAULT_PROBE_SYMBOLS)
    probe_symbols = [s.strip() for s in probe_symbols_raw.split(",") if s.strip()]

    try:
        from packages.quantum.services.ops_health_service import compute_market_data_freshness

        # Threshold in ms for the freshness check
        stale_threshold_ms = max_age_sec * 1000
        result = compute_market_data_freshness(
            universe=probe_symbols,
            stale_threshold_ms=stale_threshold_ms,
            regime=regime,
        )

        if result.is_stale:
            age_min = round(result.age_seconds / 60, 1) if result.age_seconds else "unknown"
            logger.critical(
                f"[STALENESS_GATE] Blocking entry — market data stale "
                f"(last good data: {age_min} minutes ago, "
                f"stale_symbols={result.stale_symbols}, "
                f"threshold={max_age_sec}s, source={result.source})"
            )
            return StalenessGateResult(
                blocked=True,
                reason=f"market_data_stale (age={age_min}min, symbols={result.stale_symbols})",
                age_seconds=result.age_seconds,
                stale_symbols=result.stale_symbols,
            )

        return StalenessGateResult(
            blocked=False, reason="data_fresh",
            age_seconds=result.age_seconds,
            stale_symbols=[],
        )

    except Exception as e:
        # Fail closed: if we can't check freshness, block entries
        logger.error(
            f"[STALENESS_GATE] Freshness check failed — blocking entries "
            f"(fail-closed): {e}"
        )
        return StalenessGateResult(
            blocked=True,
            reason=f"freshness_check_error: {str(e)[:100]}",
            age_seconds=None,
            stale_symbols=[],
        )
