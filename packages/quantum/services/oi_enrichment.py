"""Lane H exact-leg OI enrichment — B3 remediation, DRAFT / OBSERVE-ONLY.

DISPOSITION: DRAFT-ONLY, owner-gated, DEFAULT-OFF. This adds a *secondary
provider network call* per selected candidate, so it is NOT merge-safe by the
Lane-B contract — an owner must review it and flip the flag.

ROOT CAUSE (traced 2026-07-20 Monday, post-close):
  The Alpaca options snapshot endpoint (/v1beta1/options/snapshots/{underlying})
  carries per-contract ``dailyBar`` volume + ``greeks`` + ``impliedVolatility``
  + ``latestQuote`` + ``latestTrade`` but NO ``openInterest`` and no OI
  observation date. A live post-close sample of a liquid SPY contract
  (SPY260724C00630000) returned exactly:
      {dailyBar, greeks, impliedVolatility, latestQuote, latestTrade,
       minuteBar, prevDailyBar}
  — ``openInterest`` / ``open_interest`` / ``open_interest_date`` all absent;
  ``dailyBar.v`` (volume) present. Because Alpaca is the PRIMARY chain source
  and Polygon is only a fallback-on-empty (market_data_truth_layer.py:1615 —
  ``if not all_contracts``), the exact-leg OI was 100% unavailable on the
  natural cycle: ``market_data_truth_layer.py:1816`` ``snap.get("openInterest")``
  → None, and ``_extract_provider_oi_date`` → None → typed
  ``provider_date_unavailable``. The parser/writer thread OI correctly WHEN a
  source supplies it (the Polygon parser at :1899 reads ``open_interest``); the
  value is simply never present on the Alpaca-primary path. This is a MISSING
  PROVIDER SURFACE, not a parser/writer drop — hence a fix requires a NEW call.

WHAT THIS MODULE DOES (and never does):
  For SELECTED (spread-gate-PASSED) candidate legs ONLY — never the whole
  universe — it fetches OI for each EXACT contract whose OI is currently
  UNAVAILABLE from a secondary provider, narrowly rate-limited, and returns an
  enriched ``oi_by_contract`` overlay carrying the real OI + source + provider
  observation date (when the provider supplies one) + retrieval known-at +
  typed failure. It feeds ONLY the observe-only quote-provenance recorder.

  H9 discipline preserved end-to-end:
    * OI 0 stays a REAL value (listed-but-untraded), never conflated with
      unavailable.
    * A provider miss / error / rate-limit stays TYPED UNAVAILABLE with a
      reason — NEVER a fabricated zero or date.
    * An already-AVAILABLE OI is never overwritten (Alpaca-primary carries
      none, so the overlay only fills gaps).

  It NEVER gates, ranks, sizes, selects, or changes any scan verdict: OI feeds
  no decision (byte-identical scan pinned by the existing
  test_oi_scanner_wiring.TestOIIsObserveOnly and by this module's tests).

DEFAULT-OFF: ``OI_ENRICHMENT_ENABLED`` unset/falsy → ``enrich_selected_legs``
returns the base map unchanged (byte-identical no-op, zero provider calls).
Enabling it is an explicit owner decision.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from packages.quantum.services.quote_provenance import _bare, coerce_oi

logger = logging.getLogger(__name__)

_TRUTHY = {"1", "true", "yes", "on"}

# Narrow-scope defaults (env-overridable). A candidate leg set is 1-4 legs; the
# per-call cap is a hard ceiling that makes a whole-universe fan-out impossible
# even if a malformed candidate arrives. The window budget bounds the total
# secondary-provider calls per rolling window across the whole scan.
DEFAULT_MAX_LEGS_PER_CALL = 8
DEFAULT_MAX_CALLS_PER_WINDOW = 120
DEFAULT_WINDOW_SECONDS = 60.0
DEFAULT_MIN_INTERVAL_MS = 0.0


def is_oi_enrichment_enabled() -> bool:
    """``OI_ENRICHMENT_ENABLED`` — DEFAULT-OFF behavioral opt-in.

    A secondary provider call is a real cost, so this fails SAFE: unset/empty
    or any non-truthy value → OFF (no call, byte-identical scan). Only an
    explicit truthy (1/true/yes/on) enables it. Owner decision.
    """
    return os.getenv("OI_ENRICHMENT_ENABLED", "").strip().lower() in _TRUTHY


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return default
    return v if v >= 0 else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        v = int(float(raw))
    except (TypeError, ValueError):
        return default
    return v if v >= 0 else default


class RateLimiter:
    """Thread-safe min-interval + rolling-window call budget.

    ``allow()`` returns True and records the call when both the min-interval
    since the last grant AND the window budget permit it; otherwise False
    (the caller records a typed ``rate_limited`` outcome — never a fabricated
    value). Bounds the secondary-provider fan-out for the whole scan.
    """

    def __init__(
        self,
        max_calls_per_window: Optional[int] = None,
        window_seconds: Optional[float] = None,
        min_interval_ms: Optional[float] = None,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = (max_calls_per_window if max_calls_per_window is not None
                     else _env_int("OI_ENRICHMENT_MAX_CALLS_PER_WINDOW",
                                   DEFAULT_MAX_CALLS_PER_WINDOW))
        self._window = (window_seconds if window_seconds is not None
                        else _env_float("OI_ENRICHMENT_WINDOW_SECONDS",
                                        DEFAULT_WINDOW_SECONDS))
        self._min_interval = (
            (min_interval_ms if min_interval_ms is not None
             else _env_float("OI_ENRICHMENT_MIN_INTERVAL_MS",
                             DEFAULT_MIN_INTERVAL_MS)) / 1000.0)
        self._clock = clock
        self._lock = threading.Lock()
        self._calls: List[float] = []
        self._last: Optional[float] = None

    def allow(self) -> bool:
        with self._lock:
            now = self._clock()
            # Evict calls outside the rolling window.
            if self._window > 0:
                cutoff = now - self._window
                self._calls = [t for t in self._calls if t >= cutoff]
            if self._min_interval > 0 and self._last is not None:
                if now - self._last < self._min_interval:
                    return False
            if self._max >= 0 and len(self._calls) >= self._max:
                return False
            self._calls.append(now)
            self._last = now
            return True


@dataclass(frozen=True)
class OIRecord:
    """Typed result of ONE secondary-provider OI lookup.

    ``status`` is one of ok | miss | error | rate_limited. ``oi`` is the raw
    provider value (coerced downstream — 0 stays 0, None/garbage stays None);
    ``observation_date`` is the provider's genuine OI date (or None — never
    fabricated from retrieval time). ``error`` is a class name only, no
    secrets.
    """

    contract: str
    oi: Any = None
    source: str = "unknown"
    observation_date: Optional[str] = None
    date_field: Optional[str] = None
    status: str = "miss"
    error: Optional[str] = None


# Outcome → the ``source`` label stamped into the overlay entry so the durable
# leg row's ``oi_source`` records WHAT the enrichment did, even when OI stays
# unavailable (captures the typed failure through the existing writer path,
# with no writer change).
_STATUS_SOURCE = {
    "miss": "oi_enrich_miss",
    "error": "oi_enrich_error",
    "rate_limited": "oi_enrich_skipped_rate_limited",
}


def _overlay_entry(rec: OIRecord, retrieved_at: str) -> Dict[str, Any]:
    """Build an ``oi_by_contract`` overlay entry from an OIRecord.

    Uses exactly the keys ``quote_provenance.resolve_leg_oi`` reads (``oi``,
    ``source``, ``oi_observation_date``, ``oi_date_field``, ``oi_retrieved_at``)
    so the enriched OI + provenance thread straight into the durable row with
    no writer change. 0-vs-absent preserved via ``coerce_oi``.
    """
    oi = coerce_oi(rec.oi)
    if oi is not None:
        # A real value (incl. 0) was retrieved.
        source = rec.source or "oi_enrich"
    else:
        # Typed unavailable — name the failure mode in the source label.
        source = _STATUS_SOURCE.get(rec.status, "oi_enrich_unavailable")
        if rec.source and rec.source != "unknown":
            source = f"{source}:{rec.source}"
    return {
        "oi": oi,
        "source": source,
        "oi_observation_date": rec.observation_date,
        "oi_date_field": rec.date_field,
        "oi_retrieved_at": retrieved_at,
        "oi_enrichment_status": rec.status,   # extra; ignored by resolver
    }


def enrich_leg_oi_by_contract(
    legs: List[Dict[str, Any]],
    base_oi_by_contract: Optional[Dict[str, Dict[str, Any]]],
    *,
    fetch_fn: Callable[[str], OIRecord],
    limiter: RateLimiter,
    symbol: Optional[str] = None,
    max_legs_per_call: Optional[int] = None,
    now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> Dict[str, Dict[str, Any]]:
    """Return a NEW ``oi_by_contract`` map = base + secondary-provider OI for
    the exact leg contracts whose OI is currently unavailable.

    NEVER mutates ``base_oi_by_contract``. NEVER overwrites an already-available
    OI. NEVER fabricates: a miss/error/rate-limit leaves OI None and records the
    typed outcome in the entry's ``source`` label + ``oi_enrichment_status``.
    Hard-capped at ``max_legs_per_call`` targets (whole-universe fan-out is
    impossible). Fully fail-soft per leg.
    """
    base = base_oi_by_contract or {}
    # Deep-ish copy: new outer dict + copied per-contract dicts so the base is
    # never mutated (the base map is shared with the rejected-verdict record).
    out: Dict[str, Dict[str, Any]] = {
        k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()
    }

    cap = (max_legs_per_call if max_legs_per_call is not None
           else _env_int("OI_ENRICHMENT_MAX_LEGS_PER_CALL",
                         DEFAULT_MAX_LEGS_PER_CALL))

    # Collect exact target contracts: bare OCC, deduped, ONLY those currently
    # unavailable (base OI is None / entry missing). An available OI is left
    # untouched.
    targets: List[str] = []
    seen = set()
    for leg in (legs or []):
        if not isinstance(leg, dict):
            continue
        contract = _bare(leg.get("symbol"))
        if not contract or contract in seen:
            continue
        seen.add(contract)
        existing = out.get(contract) or {}
        if coerce_oi(existing.get("oi")) is not None:
            continue  # already available — never overwrite a real value
        targets.append(contract)

    # Hard cap — a candidate is 1-4 legs; this makes a fan-out impossible.
    targets = targets[:cap]

    for contract in targets:
        retrieved_at = now_fn().isoformat()
        try:
            if not limiter.allow():
                rec = OIRecord(contract=contract, status="rate_limited")
            else:
                rec = fetch_fn(contract)
                if not isinstance(rec, OIRecord):
                    rec = OIRecord(contract=contract, status="error",
                                   error="bad_fetch_return")
        except Exception as exc:  # noqa: BLE001 — fail-soft per leg
            logger.debug("oi_enrichment fetch failed for %s", contract,
                         exc_info=True)
            rec = OIRecord(contract=contract, status="error",
                           error=type(exc).__name__)
        out[contract] = _overlay_entry(rec, retrieved_at)

    return out


# ---------------------------------------------------------------------------
# Concrete secondary-provider fetchers (only invoked under the flag in prod;
# tests inject fakes so the network is never hit). Each is fully fail-soft and
# returns a typed OIRecord — never raises, never fabricates.
# ---------------------------------------------------------------------------
def polygon_oi_fetcher(polygon_service: Any) -> Callable[[str], OIRecord]:
    """Fetch OI from Polygon /v3/snapshot/options/{underlying}/{contract}.

    Polygon's snapshot returns ``open_interest`` but NO OI observation date
    (only bar timestamps, which are NOT an OI date) — so ``observation_date``
    stays None (typed provider_date_unavailable downstream). Honest: the value
    is real, the date genuinely isn't supplied by this provider.
    """
    def _fetch(contract: str) -> OIRecord:
        try:
            snap = polygon_service.get_option_snapshot(contract) or {}
            if not isinstance(snap, dict) or not snap:
                return OIRecord(contract=contract, source="polygon_snapshot",
                                status="miss")
            raw = snap.get("open_interest")
            if raw is None:
                return OIRecord(contract=contract, source="polygon_snapshot",
                                status="miss")
            return OIRecord(contract=contract, oi=raw,
                            source="polygon_snapshot",
                            observation_date=None, date_field=None, status="ok")
        except Exception as exc:  # noqa: BLE001
            return OIRecord(contract=contract, source="polygon_snapshot",
                            status="error", error=type(exc).__name__)
    return _fetch


def alpaca_contracts_oi_fetcher(
    session: Any, api_key: str, api_secret: str,
    base_url: str = "https://api.alpaca.markets",
) -> Callable[[str], OIRecord]:
    """Fetch OI from the Alpaca trading API /v2/options/contracts/{symbol}.

    Unlike the market-data snapshot, this endpoint returns BOTH
    ``open_interest`` AND ``open_interest_date`` — so it yields a genuine OI
    observation date (the richest source; preferred when trading-API creds are
    present). Fail-soft; credentials never logged.
    """
    headers = {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": api_secret,
    }

    def _fetch(contract: str) -> OIRecord:
        try:
            occ = contract[2:] if contract.startswith("O:") else contract
            resp = session.get(
                f"{base_url}/v2/options/contracts/{occ}",
                headers=headers, timeout=10,
            )
            if resp.status_code != 200:
                return OIRecord(contract=contract, source="alpaca_contracts",
                                status="miss")
            data = resp.json() or {}
            raw = data.get("open_interest")
            if raw is None:
                return OIRecord(contract=contract, source="alpaca_contracts",
                                status="miss")
            return OIRecord(
                contract=contract, oi=raw, source="alpaca_contracts",
                observation_date=data.get("open_interest_date"),
                date_field=("open_interest_date"
                            if data.get("open_interest_date") is not None
                            else None),
                status="ok")
        except Exception as exc:  # noqa: BLE001
            return OIRecord(contract=contract, source="alpaca_contracts",
                            status="error", error=type(exc).__name__)
    return _fetch


# Module-global limiter for the convenience wrapper (one budget per process).
_GLOBAL_LIMITER: Optional[RateLimiter] = None
_GLOBAL_LIMITER_LOCK = threading.Lock()


def _global_limiter() -> RateLimiter:
    global _GLOBAL_LIMITER
    with _GLOBAL_LIMITER_LOCK:
        if _GLOBAL_LIMITER is None:
            _GLOBAL_LIMITER = RateLimiter()
        return _GLOBAL_LIMITER


def make_default_fetcher() -> Optional[Callable[[str], OIRecord]]:
    """Build the production secondary-provider fetch_fn.

    Prefers the Alpaca trading-API contracts endpoint (OI + observation date)
    when creds are present; else Polygon's snapshot (OI, no date). Returns None
    when no secondary provider is configured — the enrichment then no-ops per
    contract (typed miss), never fabricating. Monkeypatched in tests so the
    network is never hit.
    """
    alpaca_key = os.getenv("ALPACA_API_KEY", "")
    alpaca_secret = os.getenv("ALPACA_SECRET_KEY", "")
    if alpaca_key and alpaca_secret:
        try:
            import requests
            return alpaca_contracts_oi_fetcher(
                requests.Session(), alpaca_key, alpaca_secret)
        except Exception:  # noqa: BLE001
            logger.debug("oi_enrichment: alpaca fetcher build failed",
                         exc_info=True)
    if os.getenv("POLYGON_API_KEY", ""):
        try:
            from packages.quantum.market_data import PolygonService
            return polygon_oi_fetcher(PolygonService())
        except Exception:  # noqa: BLE001
            logger.debug("oi_enrichment: polygon fetcher build failed",
                         exc_info=True)
    return None


def enrich_selected_legs(
    legs: List[Dict[str, Any]],
    base_oi_by_contract: Optional[Dict[str, Dict[str, Any]]],
    *,
    symbol: Optional[str] = None,
    fetch_fn: Optional[Callable[[str], OIRecord]] = None,
    limiter: Optional[RateLimiter] = None,
) -> Dict[str, Dict[str, Any]]:
    """Scanner-seam convenience: enrich a SELECTED candidate's exact-leg OI.

    DEFAULT-OFF: returns ``base_oi_by_contract`` UNCHANGED (same object) when
    ``OI_ENRICHMENT_ENABLED`` is off — a byte-identical no-op with zero provider
    calls. When on, runs the real enrichment logic against the configured (or
    injected) secondary-provider fetcher.
    """
    if not is_oi_enrichment_enabled():
        return base_oi_by_contract if base_oi_by_contract is not None else {}
    fetch = fetch_fn or make_default_fetcher()
    if fetch is None:
        # Enabled but no secondary provider configured — no-op, no fabrication.
        return base_oi_by_contract if base_oi_by_contract is not None else {}
    return enrich_leg_oi_by_contract(
        legs, base_oi_by_contract,
        fetch_fn=fetch, limiter=limiter or _global_limiter(), symbol=symbol,
    )
