"""
Market Data Truth Layer
Centralized service for market data fetching, normalization, and IV context.
Implements the "Truth Layer" pattern to ensure consistency across the application.
"""
import os
import time
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import logging
import re
from typing import List, Dict, Optional, Any, Union, Tuple
from datetime import datetime, timedelta
import concurrent.futures
from pydantic import BaseModel

from packages.quantum.services.market_data_cache import get_market_data_cache
from packages.quantum.services.cache_key_builder import normalize_symbol
from packages.quantum.analytics.factors import calculate_iv_rank, calculate_trend

# Use a module-level logger
logger = logging.getLogger(__name__)


# =============================================================================
# Replay Feature Store Integration (lazy import to avoid circular deps)
# =============================================================================
def _get_decision_context():
    """Lazy import of get_current_decision_context to avoid circular imports."""
    try:
        from packages.quantum.services.replay.decision_context import (
            get_current_decision_context,
            is_replay_enabled,
        )
        if not is_replay_enabled():
            return None
        return get_current_decision_context()
    except ImportError:
        return None


def _record_snapshot_to_context(
    ticker: str,
    raw_snapshot: Dict[str, Any],
    v4_snapshot: "TruthSnapshotV4"
) -> None:
    """
    Record a snapshot to the current DecisionContext if one is active.

    Called from snapshot_many_v4 after quality scoring is computed.

    Args:
        ticker: The ticker symbol
        raw_snapshot: Raw snapshot data from Polygon
        v4_snapshot: Quality-scored TruthSnapshotV4
    """
    ctx = _get_decision_context()
    if ctx is None:
        return

    try:
        # Build metadata with quality info
        metadata = {
            "provider": "polygon",
            "received_ts": v4_snapshot.timestamps.received_ts,
            "source_ts": v4_snapshot.timestamps.source_ts,
            "canon_symbol": normalize_symbol(ticker),
            "quality": {
                "score": v4_snapshot.quality.quality_score,
                "is_stale": v4_snapshot.quality.is_stale,
                "freshness_ms": v4_snapshot.quality.freshness_ms,
                "issues": v4_snapshot.quality.issues,
                "code": classify_snapshot_quality(v4_snapshot),
            },
        }

        # Record raw snapshot (for replay) with V4 structure preserved
        key = f"{ticker}:polygon:snapshot_v4"
        ctx.record_input(
            key=key,
            snapshot_type="quote",
            payload=raw_snapshot,
            metadata=metadata,
        )
    except Exception as e:
        logger.debug(f"Failed to record snapshot to context: {e}")


def _record_option_chain_to_context(
    underlying: str,
    expiration_date: Optional[str],
    chain_data: List[Dict],
) -> None:
    """
    Record an option chain to the current DecisionContext if one is active.

    Args:
        underlying: The underlying symbol
        expiration_date: Expiration date filter (if any)
        chain_data: List of option contracts
    """
    ctx = _get_decision_context()
    if ctx is None:
        return

    try:
        # Build key with expiration if provided
        if expiration_date:
            key = f"{underlying}:chain:{expiration_date}"
        else:
            key = f"{underlying}:chain:all"

        metadata = {
            "provider": "polygon",
            "received_ts": int(time.time() * 1000),
            "underlying": underlying,
            "expiration_date": expiration_date,
            "contracts_count": len(chain_data),
        }

        ctx.record_input(
            key=key,
            snapshot_type="chain",
            payload=chain_data,
            metadata=metadata,
        )
    except Exception as e:
        logger.debug(f"Failed to record option chain to context: {e}")


def _record_daily_bars_to_context(
    symbol: str,
    start_date: str,
    end_date: str,
    bars: List[Dict],
) -> None:
    """
    Record daily bars to the current DecisionContext if one is active.

    Args:
        symbol: The normalized symbol
        start_date: Start date string (YYYY-MM-DD)
        end_date: End date string (YYYY-MM-DD)
        bars: List of daily bar dicts
    """
    ctx = _get_decision_context()
    if ctx is None:
        return

    try:
        key = f"{symbol}:bars:{start_date}:{end_date}"

        metadata = {
            "provider": "polygon",
            "received_ts": int(time.time() * 1000),
            "symbol": symbol,
            "start_date": start_date,
            "end_date": end_date,
            "bars_count": len(bars),
        }

        ctx.record_input(
            key=key,
            snapshot_type="bars",
            payload=bars,
            metadata=metadata,
        )
    except Exception as e:
        logger.debug(f"Failed to record daily bars to context: {e}")

# =============================================================================
# V4 Configuration (env-configurable with safe defaults)
# =============================================================================
# Default values (used when env vars are not set)
_DEFAULT_MAX_FRESHNESS_MS = 60000
_DEFAULT_MIN_QUALITY_SCORE = 60
_DEFAULT_WIDE_SPREAD_PCT = 0.10

# Legacy module-level constants for backward compatibility
# NOTE: These are read at import time; prefer getter functions for dynamic env access
MARKETDATA_MAX_FRESHNESS_MS = int(os.getenv("MARKETDATA_MAX_FRESHNESS_MS", str(_DEFAULT_MAX_FRESHNESS_MS)))
MARKETDATA_MIN_QUALITY_SCORE = int(os.getenv("MARKETDATA_MIN_QUALITY_SCORE", str(_DEFAULT_MIN_QUALITY_SCORE)))
MARKETDATA_WIDE_SPREAD_PCT = float(os.getenv("MARKETDATA_WIDE_SPREAD_PCT", str(_DEFAULT_WIDE_SPREAD_PCT)))


def get_marketdata_max_freshness_ms() -> int:
    """Get max freshness threshold in milliseconds (env-safe, reads at call time)."""
    return int(os.getenv("MARKETDATA_MAX_FRESHNESS_MS", str(_DEFAULT_MAX_FRESHNESS_MS)))


def get_marketdata_min_quality_score() -> int:
    """Get minimum quality score threshold (env-safe, reads at call time)."""
    return int(os.getenv("MARKETDATA_MIN_QUALITY_SCORE", str(_DEFAULT_MIN_QUALITY_SCORE)))


def get_marketdata_wide_spread_pct() -> float:
    """Get wide spread percentage threshold (env-safe, reads at call time)."""
    return float(os.getenv("MARKETDATA_WIDE_SPREAD_PCT", str(_DEFAULT_WIDE_SPREAD_PCT)))


def get_marketdata_quality_policy() -> str:
    """
    Get quality gate policy (env-safe, reads at call time).

    Policies:
    - "skip": Hard skip spreads with any quality issues (original behavior)
    - "defer": Mark non-fatal issues as NOT_EXECUTABLE but don't skip
    - "downrank": Apply penalty to ranking score (not yet implemented, falls back to defer)

    Default: "defer"
    """
    return os.getenv("MARKETDATA_QUALITY_POLICY", "defer").lower()


def get_marketdata_warn_penalty() -> float:
    """
    Get penalty multiplier for downrank policy (env-safe, reads at call time).

    Applied to ranking scalar (score, ev) when downrank policy is active.
    Default: 0.7 (30% penalty)
    """
    return float(os.getenv("MARKETDATA_WARN_PENALTY", "0.7"))


# =============================================================================
# V4 Quality Status Codes (machine-readable for UI, alerts, routing)
# =============================================================================
# OK status
QUALITY_OK = "OK"

# Warning codes (non-fatal, can be deferred)
QUALITY_WARN_WIDE_SPREAD = "WARN_WIDE_SPREAD"
QUALITY_WARN_LOW_QUALITY = "WARN_LOW_QUALITY"

# Failure codes (fatal, always skip)
QUALITY_FAIL_STALE = "FAIL_STALE"
QUALITY_FAIL_CROSSED = "FAIL_CROSSED"
QUALITY_FAIL_MISSING_SNAPSHOT = "FAIL_MISSING_SNAPSHOT"
QUALITY_FAIL_MISSING_TIMESTAMP = "FAIL_MISSING_TIMESTAMP"
QUALITY_FAIL_MISSING_QUOTE_FIELDS = "FAIL_MISSING_QUOTE_FIELDS"

# Fatal codes that always cause skip regardless of policy
FATAL_QUALITY_CODES = frozenset({
    QUALITY_FAIL_STALE,
    QUALITY_FAIL_CROSSED,
    QUALITY_FAIL_MISSING_SNAPSHOT,
    QUALITY_FAIL_MISSING_TIMESTAMP,
    QUALITY_FAIL_MISSING_QUOTE_FIELDS,
})


def classify_snapshot_quality(
    snap: "TruthSnapshotV4",
    min_quality_score: Optional[int] = None
) -> str:
    """
    Classify a snapshot's quality into a machine-readable status code.

    Args:
        snap: The TruthSnapshotV4 to classify
        min_quality_score: Minimum quality score threshold (uses getter if None)

    Returns:
        One of the QUALITY_* constants
    """
    if min_quality_score is None:
        min_quality_score = get_marketdata_min_quality_score()

    issues = snap.quality.issues

    # Check fatal issues first (order matters for priority)
    if "crossed_market" in issues:
        return QUALITY_FAIL_CROSSED

    if snap.quality.is_stale:
        if "missing_timestamp" in issues:
            return QUALITY_FAIL_MISSING_TIMESTAMP
        return QUALITY_FAIL_STALE

    if "missing_quote_fields" in issues:
        return QUALITY_FAIL_MISSING_QUOTE_FIELDS

    # Check warnings
    if snap.quality.quality_score < min_quality_score:
        return QUALITY_WARN_LOW_QUALITY

    if "wide_spread" in issues:
        return QUALITY_WARN_WIDE_SPREAD

    return QUALITY_OK


def classify_missing_snapshot(raw_sym: str, canon_sym: Optional[str] = None) -> str:
    """
    Classify a missing snapshot as FAIL_MISSING_SNAPSHOT.

    Args:
        raw_sym: The raw symbol that was requested
        canon_sym: The canonical symbol (if different from raw)

    Returns:
        QUALITY_FAIL_MISSING_SNAPSHOT
    """
    return QUALITY_FAIL_MISSING_SNAPSHOT


def is_fatal_quality_code(code: str) -> bool:
    """Check if a quality code is fatal (always causes skip)."""
    return code in FATAL_QUALITY_CODES


# =============================================================================
# V4 Issue Formatters (human-readable for UI, logs, alerts)
# =============================================================================
def format_quality_issues(issues: List[str]) -> str:
    """
    Format quality issues into a compact, deterministic string.

    Args:
        issues: List of issue codes (e.g., ["stale_quote", "wide_spread"])

    Returns:
        Pipe-separated string in sorted order (e.g., "stale_quote|wide_spread")
    """
    if not issues:
        return ""
    return "|".join(sorted(issues))


def format_snapshot_summary(symbol: str, snap: "TruthSnapshotV4") -> Dict[str, Any]:
    """
    Format a snapshot into a compact summary dict for logs/UI.

    Args:
        symbol: The symbol (raw or canonical)
        snap: The TruthSnapshotV4 to summarize

    Returns:
        Dict with symbol, code, score, freshness_ms, issues
    """
    return {
        "symbol": symbol,
        "code": classify_snapshot_quality(snap),
        "score": snap.quality.quality_score,
        "freshness_ms": snap.quality.freshness_ms,
        "issues": format_quality_issues(snap.quality.issues),
    }


def format_quality_gate_result(
    snapshots: Dict[str, "TruthSnapshotV4"],
    required_symbols: List[str],
    min_quality_score: Optional[int] = None
) -> Dict[str, Any]:
    """
    Format the full quality gate result for structured logging.

    Args:
        snapshots: Dict of symbol -> TruthSnapshotV4
        required_symbols: List of required symbols
        min_quality_score: Minimum quality score threshold

    Returns:
        Dict with per-symbol summaries, overall status, fatal/warning counts
    """
    if min_quality_score is None:
        min_quality_score = get_marketdata_min_quality_score()

    summaries = []
    fatal_count = 0
    warning_count = 0

    for raw_sym in required_symbols:
        # Try both raw and normalized lookup
        snap = snapshots.get(raw_sym)
        if snap is None:
            try:
                canon_sym = normalize_symbol(raw_sym)
                snap = snapshots.get(canon_sym)
            except Exception:
                pass

        if snap is None:
            code = QUALITY_FAIL_MISSING_SNAPSHOT
            summaries.append({
                "symbol": raw_sym,
                "code": code,
                "score": None,
                "freshness_ms": None,
                "issues": "missing_snapshot",
            })
            fatal_count += 1
        else:
            summary = format_snapshot_summary(raw_sym, snap)
            summary["code"] = classify_snapshot_quality(snap, min_quality_score)
            summaries.append(summary)

            if is_fatal_quality_code(summary["code"]):
                fatal_count += 1
            elif summary["code"] != QUALITY_OK:
                warning_count += 1

    return {
        "symbols": summaries,
        "fatal_count": fatal_count,
        "warning_count": warning_count,
        "has_fatal": fatal_count > 0,
        "has_warning": warning_count > 0,
        "min_quality_score": min_quality_score,
        "max_freshness_ms": get_marketdata_max_freshness_ms(),
    }


def format_blocked_detail(gate_result: Dict[str, Any]) -> str:
    """
    Format a compact blocked_detail string from gate result for UI display.

    Args:
        gate_result: Output from format_quality_gate_result()

    Returns:
        Compact string like "AAPL:WARN_WIDE_SPREAD|SPY:FAIL_STALE"
        Sorted deterministically by symbol then code for stable logs/UI diffing.
    """
    entries = []
    for sym_info in gate_result.get("symbols", []):
        symbol = sym_info.get("symbol", "?")
        code = sym_info.get("code", "?")
        if code != QUALITY_OK:
            entries.append((symbol, code))

    # Sort deterministically by symbol, then by code
    entries.sort(key=lambda x: (x[0], x[1]))

    parts = [f"{sym}:{code}" for sym, code in entries]
    return "|".join(parts) if parts else "unknown_issue"


# =============================================================================
# V4 Effective Action Constants (what actually happened)
# =============================================================================
EFFECTIVE_ACTION_SKIP_FATAL = "skip_fatal"
EFFECTIVE_ACTION_SKIP_POLICY = "skip_policy"
EFFECTIVE_ACTION_DEFER = "defer"
EFFECTIVE_ACTION_DOWNRANK = "downrank"
EFFECTIVE_ACTION_DOWNRANK_FALLBACK = "downrank_fallback_to_defer"


def build_marketdata_block_payload(
    gate_result: Dict[str, Any],
    policy: str,
    effective_action: str,
    downrank_applied: bool = False,
    downrank_reason: Optional[str] = None,
    warn_penalty: Optional[float] = None
) -> Dict[str, Any]:
    """
    Build a complete marketdata_quality payload for attaching to candidates/suggestions.

    Args:
        gate_result: Output from format_quality_gate_result()
        policy: Current policy (skip/defer/downrank)
        effective_action: What actually happened (EFFECTIVE_ACTION_* constants)
        downrank_applied: Whether downrank penalty was applied
        downrank_reason: Reason for downrank status (if not applied)
        warn_penalty: The penalty multiplier used (if downrank applied)

    Returns:
        Complete payload dict for candidate["marketdata_quality"]
    """
    payload = {
        "event": "marketdata.v4.quality_gate",
        "policy": policy,
        "effective_action": effective_action,
        **gate_result,
    }

    if policy == "downrank":
        payload["downrank_applied"] = downrank_applied
        if downrank_applied and warn_penalty is not None:
            payload["warn_penalty"] = warn_penalty
        if not downrank_applied and downrank_reason:
            payload["downrank_reason"] = downrank_reason

    return payload


# =============================================================================
# V4 Canonical Models (Pydantic)
# =============================================================================
class TruthQuoteV4(BaseModel):
    """Canonical quote structure for V4 snapshots."""
    bid: Optional[float] = None
    ask: Optional[float] = None
    mid: Optional[float] = None
    last: Optional[float] = None
    bid_size: Optional[int] = None
    ask_size: Optional[int] = None


class TruthTimestampsV4(BaseModel):
    """Timestamp metadata for V4 snapshots."""
    source_ts: Optional[int] = None  # Provider timestamp (ms)
    received_ts: int                  # When we received it (ms)


class TruthQualityV4(BaseModel):
    """Quality assessment for V4 snapshots."""
    quality_score: int                    # 0-100
    issues: List[str]                     # List of issue codes
    is_stale: bool
    freshness_ms: Optional[float] = None  # received_ts - source_ts


class TruthSourceV4(BaseModel):
    """Source metadata for V4 snapshots."""
    provider: str = "polygon"
    endpoint: str = "/v3/snapshot"
    request_id: Optional[str] = None


class TruthSnapshotV4(BaseModel):
    """
    Canonical V4 market data snapshot with quality scoring.
    Used for typed, quality-aware market data access.
    """
    symbol_canonical: str
    quote: TruthQuoteV4
    timestamps: TruthTimestampsV4
    quality: TruthQualityV4
    source: TruthSourceV4
    # Optional fields
    iv: Optional[float] = None
    greeks: Optional[dict] = None
    open_interest: Optional[int] = None
    volume: Optional[int] = None
    day: Optional[dict] = None


# =============================================================================
# V4 Quality Scoring Functions
# =============================================================================
def compute_quote_quality(
    quote: TruthQuoteV4,
    freshness_ms: Optional[float],
    max_freshness_ms: Optional[int] = None,
    wide_spread_pct: Optional[float] = None
) -> TruthQualityV4:
    """
    Deterministic rule-based quality scoring for market quotes.

    Returns quality_score (0-100), issues list, and is_stale flag.

    Scoring rules:
    - Crossed market (ask < bid): score=0, issue="crossed_market"
    - Missing bid/ask: score-=40, issue="missing_quote_fields"
    - Wide spread (> threshold): score-=20, issue="wide_spread"
    - Stale timestamp: score-=30, issue="stale_quote"
    - Missing timestamp: is_stale=True, issue="missing_timestamp"

    Args:
        quote: The quote to score
        freshness_ms: Quote freshness in milliseconds (None if unknown)
        max_freshness_ms: Max freshness threshold (uses env getter if None)
        wide_spread_pct: Wide spread threshold (uses env getter if None)
    """
    # Use getters for env-safe defaults (read at call time, not import time)
    if max_freshness_ms is None:
        max_freshness_ms = get_marketdata_max_freshness_ms()
    if wide_spread_pct is None:
        wide_spread_pct = get_marketdata_wide_spread_pct()

    score = 100
    issues: List[str] = []

    # Check 1: Crossed market (ask < bid) - fatal quality issue
    if quote.bid is not None and quote.ask is not None:
        if quote.ask < quote.bid:
            score = 0
            issues.append("crossed_market")

    # Check 2: Missing bid/ask
    if quote.bid is None or quote.ask is None:
        score -= 40
        issues.append("missing_quote_fields")

    # Check 3: Wide spread (only if we have valid values)
    # Use explicit None checks to handle 0.0 values correctly
    if (quote.mid is not None and quote.bid is not None and
            quote.ask is not None and quote.mid > 0):
        spread_pct = (quote.ask - quote.bid) / quote.mid
        if spread_pct > wide_spread_pct:
            score -= 20
            issues.append("wide_spread")

    # Check 4: Staleness
    is_stale = False
    if freshness_ms is None:
        issues.append("missing_timestamp")
        is_stale = True  # Conservative: treat missing timestamp as stale
    elif freshness_ms > max_freshness_ms:
        is_stale = True
        issues.append("stale_quote")
        score -= 30

    # Clamp score to valid range
    score = max(0, min(100, score))

    return TruthQualityV4(
        quality_score=score,
        issues=issues,
        is_stale=is_stale,
        freshness_ms=freshness_ms
    )


def check_snapshots_executable(
    snapshots: Dict[str, TruthSnapshotV4],
    required_symbols: List[str],
    min_quality_score: Optional[int] = None
) -> Tuple[bool, List[str]]:
    """
    Checks if all required symbols have executable-quality snapshots.

    Handles symbol normalization automatically - tries both raw and canonical
    key lookups to prevent false "missing_snapshot" errors.

    Returns:
        (is_executable, list_of_issues)

    A snapshot is NOT executable if:
    - Missing from the snapshots dict (after trying normalized lookup)
    - is_stale is True
    - quality_score < min_quality_score
    """
    # Use getter for env-safe default (read at call time, not import time)
    if min_quality_score is None:
        min_quality_score = get_marketdata_min_quality_score()

    issues: List[str] = []

    for raw_sym in required_symbols:
        # Try both raw and normalized key lookups to handle mismatches
        snap = snapshots.get(raw_sym)
        canonical_sym = raw_sym

        if snap is None:
            # Try normalized/canonical lookup
            try:
                canonical_sym = normalize_symbol(raw_sym)
                snap = snapshots.get(canonical_sym)
            except Exception:
                # If normalization fails, treat symbol as-is
                pass

        if snap is None:
            # Include both raw and canonical in error for debugging
            if canonical_sym != raw_sym:
                issues.append(f"{raw_sym} (canon={canonical_sym}): missing_snapshot")
            else:
                issues.append(f"{raw_sym}: missing_snapshot")
            continue

        if snap.quality.is_stale:
            issues.append(f"{raw_sym}: stale_quote (freshness={snap.quality.freshness_ms}ms)")

        if snap.quality.quality_score < min_quality_score:
            issues.append(
                f"{raw_sym}: low_quality (score={snap.quality.quality_score}, "
                f"issues={snap.quality.issues})"
            )

    return (len(issues) == 0, issues)


class _ResilientAdapter(HTTPAdapter):
    """HTTPAdapter that recovers from stale connection pools.

    When a worker idles between jobs (13+ min), Polygon drops the TCP
    connection.  With pool_maxsize=50, urllib3's Retry(total=3) can
    exhaust its budget pulling stale sockets from the pool without ever
    opening a fresh one.  This adapter detects that scenario, discards
    all pooled connections, and retries once with a fresh socket.

    Catches ConnectionError (includes BrokenPipeError), OSError (covers
    low-level socket errors like EPIPE/ECONNRESET), and requests-level
    connection failures.
    """

    def send(self, request, stream=False, timeout=None, verify=True, cert=None, proxies=None):
        try:
            return super().send(
                request, stream=stream, timeout=timeout,
                verify=verify, cert=cert, proxies=proxies,
            )
        except (ConnectionError, OSError, requests.exceptions.ConnectionError) as exc:
            self.close()
            return super().send(
                request, stream=stream, timeout=timeout,
                verify=verify, cert=cert, proxies=proxies,
            )


class MarketDataTruthLayer:
    """
    Truth Layer for Market Data.
    Handles caching, rate limiting, normalization, and fallback logic.
    """

    def __init__(self, api_key: Optional[str] = None):
        # 1. Resolve API Key
        self.api_key = (
            api_key
            or os.getenv("MARKETDATA_API_KEY")
            or os.getenv("POLYGON_API_KEY")
        )
        if not self.api_key:
            logger.warning("No API key provided for MarketDataTruthLayer. Calls may fail.")

        self.base_url = "https://api.polygon.io"
        self.cache = get_market_data_cache()

        # Initialize Session with Connection Pooling
        self.session = requests.Session()

        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            connect=3,
            read=2,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )

        # Mount resilient adapter — auto-recovers from stale connection pools
        # pool_maxsize=50 supports up to 50 concurrent threads without blocking on connection pool
        adapter = _ResilientAdapter(
            pool_connections=10,
            pool_maxsize=50,
            max_retries=retry_strategy
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        # Caching TTLs (in seconds)
        self.ttl_snapshot = 10
        self.ttl_option_chain = int(os.environ.get("OPTION_CHAIN_CACHE_TTL", "300"))
        self.ttl_daily_bars = 43200  # 12 hours

    def _get_headers(self):
        return {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}

    # Application-level retry config (on top of urllib3 adapter retries)
    _APP_MAX_RETRIES = 5
    _APP_BASE_DELAY = 0.5   # seconds
    _APP_MAX_DELAY = 30.0   # seconds
    _APP_JITTER = 0.25      # ±25%
    _TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}

    def _make_request(self, endpoint: str, params: Dict = None, retries: int = 2) -> Any:
        """
        Make HTTP request with exponential backoff + jitter on transient errors.

        The urllib3 adapter handles low-level retries, but during sustained
        volatility (e.g., Polygon 502 storms) adapter retries exhaust quickly.
        This application-level retry catches those and applies jitter to avoid
        thundering herd on recovery.
        """
        import random

        url = f"{self.base_url}{endpoint}"
        params = params or {}
        if self.api_key and "apiKey" not in params:
             params["apiKey"] = self.api_key

        last_status = None
        last_error = None

        for attempt in range(self._APP_MAX_RETRIES):
            try:
                start_ts = time.time()
                response = self.session.get(url, params=params, timeout=10)
                elapsed_ms = (time.time() - start_ts) * 1000
                last_status = response.status_code

                if response.status_code == 200:
                    if attempt > 0:
                        logger.info(
                            f"OK {endpoint} {response.status_code} {elapsed_ms:.1f}ms "
                            f"(recovered after {attempt} retries)"
                        )
                    else:
                        logger.info(f"OK {endpoint} {response.status_code} {elapsed_ms:.1f}ms")
                    return response.json()

                if response.status_code in self._TRANSIENT_STATUS_CODES:
                    if attempt < self._APP_MAX_RETRIES - 1:
                        base = min(self._APP_BASE_DELAY * (2 ** attempt), self._APP_MAX_DELAY)
                        jitter = base * random.uniform(-self._APP_JITTER, self._APP_JITTER)
                        delay = max(0.1, base + jitter)
                        logger.warning(
                            f"[POLYGON] {response.status_code} on {endpoint} "
                            f"(attempt {attempt + 1}/{self._APP_MAX_RETRIES}). "
                            f"Retrying in {delay:.2f}s..."
                        )
                        time.sleep(delay)
                        continue

                # Non-transient error — fail immediately
                logger.error(f"Error {endpoint}: {response.status_code} {response.text}")
                return None

            except requests.exceptions.RequestException as e:
                last_error = e
                if attempt < self._APP_MAX_RETRIES - 1:
                    base = min(self._APP_BASE_DELAY * (2 ** attempt), self._APP_MAX_DELAY)
                    jitter = base * random.uniform(-self._APP_JITTER, self._APP_JITTER)
                    delay = max(0.1, base + jitter)
                    logger.warning(
                        f"[POLYGON] Request error on {endpoint} "
                        f"(attempt {attempt + 1}/{self._APP_MAX_RETRIES}): {e}. "
                        f"Retrying in {delay:.2f}s..."
                    )
                    time.sleep(delay)
                    continue

                logger.error(f"Request failed {endpoint} after {self._APP_MAX_RETRIES} attempts: {e}")
                return None

        logger.error(
            f"[POLYGON] {endpoint} failed after {self._APP_MAX_RETRIES} attempts "
            f"(last_status={last_status}, last_error={last_error})"
        )
        return None

    # ... rest of the class methods ...
    def snapshot_many(self, tickers: List[str]) -> Dict[str, Dict]:
        """
        Fetches snapshots for multiple tickers (up to 250).
        Returns a dict keyed by ticker.

        Routing: option tickers (O: prefix) → Alpaca primary, Polygon fallback.
        Equity tickers → Polygon primary.
        """
        if not tickers:
            return {}

        # 1. Normalize tickers and filter valid ones
        normalized_tickers = [self.normalize_symbol(t) for t in tickers]
        unique_tickers = list(set(normalized_tickers))

        # 2. Check Cache
        results = {}
        missing_tickers = []

        for ticker in unique_tickers:
            cached = self.cache.get("snapshot_many", ticker)
            if cached:
                results[ticker] = cached
            else:
                missing_tickers.append(ticker)

        if not missing_tickers:
            return results

        # 3. Split into options vs equities
        missing_options = [t for t in missing_tickers if t.startswith("O:")]
        missing_equities = [t for t in missing_tickers if not t.startswith("O:")]

        # 4a. Options → Alpaca primary
        if missing_options:
            logger.info(f"[SNAPSHOT] Fetching {len(missing_options)} option(s) via Alpaca primary")
            alpaca_snaps = self._fetch_alpaca_options_snapshots(missing_options)
            for ticker, snap in alpaca_snaps.items():
                self.cache.set("snapshot_many", ticker, snap, self.ttl_snapshot)
                results[ticker] = snap

            # Fallback: options that Alpaca missed → try Polygon
            alpaca_misses = [t for t in missing_options if t not in results]
            if alpaca_misses:
                logger.info(
                    f"[SNAPSHOT] Alpaca missed {len(alpaca_misses)} option(s), "
                    f"falling back to Polygon: {alpaca_misses}"
                )
                polygon_snaps = self._fetch_polygon_snapshots(alpaca_misses)
                for ticker, snap in polygon_snaps.items():
                    q = snap.get("quote", {})
                    if (q.get("bid") or 0) > 0 or (q.get("ask") or 0) > 0:
                        self.cache.set("snapshot_many", ticker, snap, self.ttl_snapshot)
                        results[ticker] = snap

        # 4b. Equities → Alpaca primary, Polygon fallback
        if missing_equities:
            alpaca_eq_snaps = self._fetch_alpaca_equity_snapshots(missing_equities)
            for ticker, snap in alpaca_eq_snaps.items():
                self.cache.set("snapshot_many", ticker, snap, self.ttl_snapshot)
                results[ticker] = snap

            # Fallback: equities that Alpaca missed → try Polygon
            eq_misses = [t for t in missing_equities if t not in results]
            if eq_misses:
                logger.info(
                    f"[SNAPSHOT] Alpaca missed {len(eq_misses)} equity(ies), "
                    f"falling back to Polygon: {eq_misses}"
                )
                polygon_snaps = self._fetch_polygon_snapshots(eq_misses)
                for ticker, snap in polygon_snaps.items():
                    self.cache.set("snapshot_many", ticker, snap, self.ttl_snapshot)
                    results[ticker] = snap

        return results

    def _fetch_polygon_snapshots(self, tickers: List[str]) -> Dict[str, Dict]:
        """
        Batch-fetch snapshots from Polygon /v3/snapshot.
        Extracted so snapshot_many can route options vs equities to different providers.
        """
        results: Dict[str, Dict] = {}
        chunk_size = 50

        def fetch_chunk(chunk):
            tickers_str = ",".join(chunk)
            return self._make_request("/v3/snapshot", params={"ticker.any_of": tickers_str})

        chunks = [tickers[i:i + chunk_size] for i in range(0, len(tickers), chunk_size)]

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_chunk = {executor.submit(fetch_chunk, chunk): chunk for chunk in chunks}

            for future in concurrent.futures.as_completed(future_to_chunk):
                try:
                    data = future.result()
                    if data and "results" in data:
                        for item in data["results"]:
                            ticker = item.get("ticker")
                            if not ticker:
                                continue
                            results[ticker] = self._parse_snapshot_item(item)
                    else:
                        chunk = future_to_chunk[future]
                        logger.warning(f"No results for Polygon snapshot batch: {chunk}")
                except Exception as e:
                    logger.error(f"Error fetching Polygon snapshot chunk: {e}")

        return results

    def _fetch_alpaca_equity_snapshots(self, tickers: List[str]) -> Dict[str, Dict]:
        """
        Batch-fetch equity snapshots from Alpaca /v2/stocks/snapshots.
        Returns canonical snapshot dicts keyed by ticker.
        """
        try:
            from packages.quantum.brokers.alpaca_client import get_alpaca_client
            alpaca = get_alpaca_client()
            if not alpaca:
                logger.warning("[SNAPSHOT] No Alpaca client — cannot fetch equity snapshots")
                return {}

            raw = alpaca.get_stock_snapshots(tickers)
            logger.info(f"[SNAPSHOT] Alpaca returned {len(raw)}/{len(tickers)} equity snapshot(s)")
            return raw
        except Exception as e:
            logger.error(f"[SNAPSHOT] Alpaca equity snapshot failed: {e}")
            return {}

    def snapshot_many_v4(
        self,
        tickers: List[str],
        raw_snapshots: Optional[Dict[str, Dict]] = None
    ) -> Dict[str, TruthSnapshotV4]:
        """
        V4 API: Returns canonical TruthSnapshotV4 objects with quality scoring.

        This is the preferred method for quality-aware market data access.
        Backward compatible: existing snapshot_many() unchanged.

        Args:
            tickers: List of ticker symbols to fetch
            raw_snapshots: Optional pre-fetched raw snapshots to avoid double fetch.
                           If provided, snapshot_many() will NOT be called.

        Returns:
            Dict mapping ticker to TruthSnapshotV4 with quality scoring
        """
        # Use provided raw_snapshots or fetch them
        if raw_snapshots is None:
            raw_snapshots = self.snapshot_many(tickers)

        # V4 quality cache — within the same minute, quality scores don't change
        if not hasattr(self, '_v4_quality_cache'):
            self._v4_quality_cache = {}
            self._v4_quality_cache_minute = None
        current_minute = datetime.utcnow().strftime('%Y%m%d%H%M')
        if self._v4_quality_cache_minute != current_minute:
            self._v4_quality_cache = {}
            self._v4_quality_cache_minute = current_minute

        # Check cache for exact ticker set
        cache_key = frozenset(raw_snapshots.keys())
        if cache_key in self._v4_quality_cache:
            return self._v4_quality_cache[cache_key]

        v4_results: Dict[str, TruthSnapshotV4] = {}
        received_ts = int(time.time() * 1000)

        for ticker, raw in raw_snapshots.items():
            quote_data = raw.get("quote", {})

            # Build TruthQuoteV4
            quote = TruthQuoteV4(
                bid=quote_data.get("bid"),
                ask=quote_data.get("ask"),
                mid=quote_data.get("mid"),
                last=quote_data.get("last"),
                bid_size=quote_data.get("bid_size"),
                ask_size=quote_data.get("ask_size"),
            )

            # Compute mid if missing but bid/ask present
            if quote.mid is None and quote.bid is not None and quote.ask is not None:
                quote = quote.model_copy(update={"mid": (quote.bid + quote.ask) / 2.0})

            # Build timestamps
            source_ts = raw.get("provider_ts")
            if source_ts:
                source_ts = self._normalize_timestamp_to_ms(source_ts)

            timestamps = TruthTimestampsV4(
                source_ts=source_ts,
                received_ts=received_ts
            )

            # Compute freshness from raw staleness_ms or calculate from timestamps
            freshness_ms = raw.get("staleness_ms")
            if freshness_ms is None and source_ts:
                freshness_ms = float(received_ts - source_ts)

            # Compute quality
            quality = compute_quote_quality(quote, freshness_ms)

            # Build source metadata — reflect actual provider
            raw_source = raw.get("source", "polygon")
            source = TruthSourceV4(
                provider=raw_source,
                endpoint="/v1beta1/options/snapshots" if raw_source == "alpaca" else "/v3/snapshot"
            )

            v4_results[ticker] = TruthSnapshotV4(
                symbol_canonical=ticker,
                quote=quote,
                timestamps=timestamps,
                quality=quality,
                source=source,
                iv=raw.get("iv"),
                greeks=raw.get("greeks"),
                day=raw.get("day"),
                volume=raw.get("day", {}).get("v"),
            )

            # Record to DecisionContext if active (for replay feature store)
            _record_snapshot_to_context(ticker, raw, v4_results[ticker])

        self._v4_quality_cache[cache_key] = v4_results
        return v4_results

    def _normalize_timestamp_to_ms(self, ts: Optional[Union[int, float]]) -> Optional[int]:
        """
        Normalize timestamp to milliseconds.

        Handles timestamps in nanoseconds, microseconds, milliseconds, or seconds.
        """
        if ts is None:
            return None
        try:
            ts_val = float(ts)
            if ts_val > 1e16:  # Nanoseconds (> 10^16)
                return int(ts_val / 1e6)
            elif ts_val > 1e14:  # Microseconds (> 10^14)
                return int(ts_val / 1e3)
            elif ts_val > 1e11:  # Already milliseconds (> 10^11)
                return int(ts_val)
            else:  # Seconds
                return int(ts_val * 1000)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _get_first(d: Optional[Dict], keys: List[str]) -> Optional[Any]:
        """Get first non-None value from dict using multiple possible keys."""
        if d is None:
            return None
        for k in keys:
            val = d.get(k)
            if val is not None:
                return val
        return None

    @staticmethod
    def _extract_last_quote_fields(last_quote: Optional[Dict]) -> Tuple[Optional[float], Optional[float], Optional[int], Optional[int], Optional[int]]:
        """
        Extract quote fields from Polygon last_quote with multi-key support.

        Returns: (bid, ask, quote_ts, bid_size, ask_size)

        Supports multiple key variants:
        - ask: ["a", "ask", "P", "ap", "ask_price"]
        - bid: ["b", "bid", "p", "bp", "bid_price"]
        - ts: ["t", "timestamp", "quote_ts", "updated", "last_updated"]
        - bid_size: ["bx", "bid_size", "bs"]
        - ask_size: ["ax", "ask_size", "as"]
        """
        if not last_quote:
            return (None, None, None, None, None)

        # Extract with fallback keys
        ask_raw = MarketDataTruthLayer._get_first(last_quote, ["a", "ask", "P", "ap", "ask_price"])
        bid_raw = MarketDataTruthLayer._get_first(last_quote, ["b", "bid", "p", "bp", "bid_price"])
        ts_raw = MarketDataTruthLayer._get_first(last_quote, ["t", "timestamp", "quote_ts", "updated", "last_updated"])
        bid_size_raw = MarketDataTruthLayer._get_first(last_quote, ["bx", "bid_size", "bs"])
        ask_size_raw = MarketDataTruthLayer._get_first(last_quote, ["ax", "ask_size", "as"])

        # Convert to proper types
        def to_float(v):
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        def to_int(v):
            if v is None:
                return None
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        return (
            to_float(bid_raw),
            to_float(ask_raw),
            to_int(ts_raw),
            to_int(bid_size_raw),
            to_int(ask_size_raw)
        )

    @staticmethod
    def _extract_last_trade_fields(last_trade: Optional[Dict], session: Optional[Dict] = None) -> Tuple[Optional[float], Optional[int]]:
        """
        Extract trade fields from Polygon last_trade with multi-key support.

        Returns: (last_price, trade_ts)

        Supports multiple key variants:
        - price: ["p", "price", "last", "c", "close"]
        - ts: ["t", "timestamp", "trade_ts", "updated"]
        Falls back to session.close if no trade price found.
        """
        if not last_trade:
            last_trade = {}

        # Extract with fallback keys
        price_raw = MarketDataTruthLayer._get_first(last_trade, ["p", "price", "last", "c", "close"])
        ts_raw = MarketDataTruthLayer._get_first(last_trade, ["t", "timestamp", "trade_ts", "updated"])

        # Fallback to session close if no trade price
        if price_raw is None and session:
            price_raw = session.get("close")

        # Convert to proper types
        def to_float(v):
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        def to_int(v):
            if v is None:
                return None
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        return (to_float(price_raw), to_int(ts_raw))

    def _parse_snapshot_item(self, item: Dict) -> Dict:
        """
        Parses a Polygon snapshot item into our canonical format.

        Uses robust extractors to support multiple key variants for bid/ask/timestamps
        across different Polygon API versions and asset types.
        """
        # Extract quote fields using robust multi-key extractor
        last_quote = item.get("last_quote") or item.get("quote") or {}
        last_trade = item.get("last_trade") or {}
        session = item.get("session") or {}

        # Use extractors for consistent parsing
        bid, ask, quote_ts, bid_size, ask_size = self._extract_last_quote_fields(last_quote)
        last_price, trade_ts = self._extract_last_trade_fields(last_trade, session)

        # Mid calculation with strict validation
        mid = None
        if bid is not None and ask is not None and bid > 0 and ask > 0 and ask >= bid:
            mid = (ask + bid) / 2.0

        # Provider timestamp: prefer item.updated, fallback to quote_ts, then trade_ts
        provider_ts = item.get("updated") or quote_ts or trade_ts

        # Greek handling (if available - e.g. for options)
        greeks = item.get("greeks", {})
        iv = item.get("implied_volatility")

        return {
            "ticker": item.get("ticker"),
            "asset_type": item.get("type"),  # e.g. "CS" (Common Stock), "O" (Option)
            "quote": {
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "last": last_price,
                "quote_ts": quote_ts,
                "bid_size": bid_size,
                "ask_size": ask_size,
            },
            "day": {
                "o": session.get("open"),
                "h": session.get("high"),
                "l": session.get("low"),
                "c": session.get("close"),
                "v": session.get("volume"),
                "vwap": None  # Not always in snapshot
            },
            "greeks": {
                "delta": greeks.get("delta"),
                "gamma": greeks.get("gamma"),
                "theta": greeks.get("theta"),
                "vega": greeks.get("vega")
            },
            "iv": iv,
            "source": "polygon",
            "retrieved_ts": datetime.utcnow().isoformat(),
            "provider_ts": provider_ts,
            "staleness_ms": self._compute_staleness(provider_ts),
            "parser_version": "v2",  # Track parser version for debugging
        }

    def _compute_staleness(self, provider_ts: Optional[Union[int, float]]) -> Optional[float]:
        """
        Computes staleness in milliseconds.
        Handles provider_ts in milliseconds, microseconds, or nanoseconds automatically.
        """
        if not provider_ts:
            return None

        try:
            # Current time in milliseconds
            now_ms = time.time() * 1000.0
            ts_val = float(provider_ts)

            # Determine unit based on magnitude
            # Unix 2025: ~1.7e9 (sec), ~1.7e12 (ms), ~1.7e15 (us), ~1.7e18 (ns)

            if ts_val > 1e16: # Nanoseconds (> 10^16)
                ts_ms = ts_val / 1e6
            elif ts_val > 1e14: # Microseconds (> 10^14)
                ts_ms = ts_val / 1e3
            elif ts_val > 1e11: # Milliseconds (> 10^11)
                ts_ms = ts_val
            else: # Seconds or invalid
                ts_ms = ts_val * 1000.0

            staleness = max(0.0, now_ms - ts_ms)
            return staleness

        except (ValueError, TypeError):
            return None

    def _fetch_alpaca_options_snapshots(self, occ_symbols: List[str]) -> Dict[str, Dict]:
        """
        Fetch option snapshots from Alpaca's indicative options feed.
        Primary source for options pricing (Phase 1).

        Endpoint: GET https://data.alpaca.markets/v1beta1/options/snapshots
        Auth: ALPACA_API_KEY + ALPACA_SECRET_KEY headers

        Returns dict keyed by O:-prefixed OCC symbol in our canonical format.
        """
        logger.info(
            f"[MTM] _fetch_alpaca_options_snapshots called with "
            f"{len(occ_symbols)} symbol(s): {occ_symbols[:5]}"
        )

        alpaca_key = os.getenv("ALPACA_API_KEY", "")
        alpaca_secret = os.getenv("ALPACA_SECRET_KEY", "")
        if not alpaca_key or not alpaca_secret:
            logger.warning("[MTM] Alpaca options skipped — ALPACA_API_KEY/ALPACA_SECRET_KEY not set")
            return {}

        logger.info(f"[MTM] Alpaca keys present, key_id={alpaca_key[:8]}...")

        # Alpaca wants bare OCC symbols without the O: prefix
        # e.g. "ADBE260515P00255000" not "O:ADBE260515P00255000"
        stripped = {sym.removeprefix("O:"): sym for sym in occ_symbols}

        results: Dict[str, Dict] = {}
        # Alpaca allows up to 100 symbols per request
        chunk_size = 100
        symbol_list = list(stripped.keys())

        for i in range(0, len(symbol_list), chunk_size):
            chunk = symbol_list[i:i + chunk_size]
            params = {"symbols": ",".join(chunk)}
            headers = {
                "APCA-API-KEY-ID": alpaca_key,
                "APCA-API-SECRET-KEY": alpaca_secret,
            }

            try:
                resp = self.session.get(
                    "https://data.alpaca.markets/v1beta1/options/snapshots",
                    params=params,
                    headers=headers,
                    timeout=10,
                )
                if resp.status_code != 200:
                    logger.warning(
                        f"[MTM] Alpaca options snapshot returned {resp.status_code}: "
                        f"{resp.text[:200]}"
                    )
                    continue

                data = resp.json()
                snapshots = data.get("snapshots", data)  # top-level may be the dict itself
                logger.info(
                    f"[MTM] Alpaca response: status={resp.status_code}, "
                    f"symbols_returned={len(snapshots)}, "
                    f"keys={list(snapshots.keys())[:5]}"
                )

                for bare_sym, snap in snapshots.items():
                    original_key = stripped.get(bare_sym)
                    if not original_key:
                        continue

                    # Parse Alpaca snapshot into our canonical format
                    quote = snap.get("latestQuote", {})
                    trade = snap.get("latestTrade", {})
                    greeks = snap.get("greeks", {})

                    bid = None
                    ask = None
                    try:
                        bid = float(quote.get("bp", 0) or 0)
                        ask = float(quote.get("ap", 0) or 0)
                    except (TypeError, ValueError):
                        pass

                    mid = None
                    if bid and ask and bid > 0 and ask > 0 and ask >= bid:
                        mid = (bid + ask) / 2.0

                    last_price = None
                    try:
                        last_price = float(trade.get("p", 0) or 0) or None
                    except (TypeError, ValueError):
                        pass

                    if mid is None and last_price is None:
                        logger.warning(f"[MTM] Alpaca returned empty data for {original_key}")
                        continue

                    logger.info(f"[MTM] Alpaca options snapshot OK for {original_key}")

                    results[original_key] = {
                        "ticker": original_key,
                        "asset_type": "O",
                        "quote": {
                            "bid": bid if bid and bid > 0 else None,
                            "ask": ask if ask and ask > 0 else None,
                            "mid": mid,
                            "last": last_price,
                            "quote_ts": None,
                            "bid_size": None,
                            "ask_size": None,
                        },
                        "day": {
                            "o": None, "h": None, "l": None,
                            "c": snap.get("dailyBar", {}).get("c"),
                            "v": snap.get("dailyBar", {}).get("v"),
                            "vwap": None,
                        },
                        "greeks": {
                            "delta": greeks.get("delta"),
                            "gamma": greeks.get("gamma"),
                            "theta": greeks.get("theta"),
                            "vega": greeks.get("vega"),
                        },
                        "iv": snap.get("impliedVolatility"),
                        "source": "alpaca",
                        "retrieved_ts": datetime.utcnow().isoformat(),
                        "provider_ts": None,
                        "staleness_ms": None,
                        "parser_version": "v2",
                    }

            except requests.exceptions.RequestException as e:
                logger.error(f"[MTM] Alpaca options snapshot request failed: {e}")

        return results

    def option_chain(self, underlying: str, *,
                     expiration_date: Optional[str] = None,
                     min_expiry: Optional[str] = None,
                     max_expiry: Optional[str] = None,
                     strike_range: Optional[float] = None,
                     right: Optional[str] = None,
                     spot: Optional[float] = None) -> List[Dict]:
        """
        Fetches option chain snapshot for an underlying.
        Returns a list of canonical option objects.
        """
        # 1. Check Cache (include strike_range for determinism)
        cache_key = f"{underlying}_{expiration_date}_{min_expiry}_{max_expiry}_{right}_{strike_range}"
        cached = self.cache.get("option_chain", cache_key)
        if cached:
            return cached

        # 2. Get spot price if not provided (for strike filtering)
        spot_for_filter = spot
        if spot_for_filter is None and strike_range is not None:
            # Fetch spot from snapshot to apply strike filtering
            snapshots = self.snapshot_many([underlying])
            snap = snapshots.get(underlying, {})
            quote = snap.get("quote", {})
            spot_for_filter = quote.get("mid") or quote.get("last")

        # 3. Try Alpaca first for option chain
        all_contracts = self._fetch_alpaca_option_chain(
            underlying, spot_for_filter, expiration_date, min_expiry, max_expiry,
            strike_range, right
        )

        # 4. Fallback to Polygon if Alpaca returned nothing
        if not all_contracts:
            logger.info(f"[CHAIN] Alpaca returned no contracts for {underlying}, falling back to Polygon")
            all_contracts = self._fetch_polygon_option_chain(
                underlying, spot_for_filter, expiration_date, min_expiry, max_expiry,
                strike_range, right
            )

        # Record to DecisionContext if active (for replay feature store)
        _record_option_chain_to_context(underlying, expiration_date, all_contracts)

        self.cache.set("option_chain", cache_key, all_contracts, self.ttl_option_chain)
        return all_contracts

    def _fetch_alpaca_option_chain(
        self, underlying: str, spot: Optional[float],
        expiration_date: Optional[str], min_expiry: Optional[str],
        max_expiry: Optional[str], strike_range: Optional[float],
        right: Optional[str],
    ) -> List[Dict]:
        """
        Fetch option chain from Alpaca /v1beta1/options/snapshots/{underlying}.
        Returns list of canonical contract dicts matching option_chain() format.
        """
        alpaca_key = os.getenv("ALPACA_API_KEY", "")
        alpaca_secret = os.getenv("ALPACA_SECRET_KEY", "")
        if not alpaca_key or not alpaca_secret:
            logger.warning("[CHAIN] Alpaca skipped — keys not set")
            return []

        headers = {
            "APCA-API-KEY-ID": alpaca_key,
            "APCA-API-SECRET-KEY": alpaca_secret,
        }

        all_contracts: List[Dict] = []
        page_token: Optional[str] = None
        page_limit = 100

        while True:
            params: Dict[str, Any] = {"limit": page_limit}

            if expiration_date:
                params["expiration_date"] = expiration_date
            else:
                if min_expiry:
                    params["expiration_date_gte"] = min_expiry
                if max_expiry:
                    params["expiration_date_lte"] = max_expiry

            if right:
                params["type"] = right.lower()  # "call" or "put"

            if strike_range is not None and spot and spot > 0:
                params["strike_price_gte"] = str(round(spot * (1 - strike_range), 2))
                params["strike_price_lte"] = str(round(spot * (1 + strike_range), 2))

            if page_token:
                params["page_token"] = page_token

            try:
                resp = self.session.get(
                    f"https://data.alpaca.markets/v1beta1/options/snapshots/{underlying}",
                    params=params,
                    headers=headers,
                    timeout=15,
                )
                if resp.status_code != 200:
                    logger.warning(
                        f"[CHAIN] Alpaca option chain returned {resp.status_code}: "
                        f"{resp.text[:200]}"
                    )
                    break

                data = resp.json()
                snapshots = data.get("snapshots", {})

                for occ_symbol, snap in snapshots.items():
                    contract = self._parse_alpaca_chain_item(occ_symbol, underlying, snap)
                    if contract:
                        all_contracts.append(contract)

                # Pagination
                page_token = data.get("next_page_token")
                if not page_token:
                    break

            except requests.exceptions.RequestException as e:
                logger.error(f"[CHAIN] Alpaca option chain request failed: {e}")
                break

        if all_contracts:
            logger.info(
                f"[CHAIN] Alpaca returned {len(all_contracts)} contracts for {underlying}"
            )

        return all_contracts

    def _parse_alpaca_chain_item(self, occ_symbol: str, underlying: str, snap: Dict) -> Optional[Dict]:
        """Parse a single Alpaca option snapshot into the canonical chain contract format."""
        from packages.quantum.services.options_utils import parse_option_symbol

        parsed = parse_option_symbol(occ_symbol)
        if not parsed:
            return None

        quote = snap.get("latestQuote", {})
        trade = snap.get("latestTrade", {})
        greeks = snap.get("greeks", {})

        bid = None
        ask = None
        try:
            bid = float(quote.get("bp", 0) or 0) or None
            ask = float(quote.get("ap", 0) or 0) or None
        except (TypeError, ValueError):
            pass

        mid = None
        if bid and ask and bid > 0 and ask > 0:
            mid = (bid + ask) / 2.0

        last_price = None
        try:
            last_price = float(trade.get("p", 0) or 0) or None
        except (TypeError, ValueError):
            pass

        # Map parsed type (C/P) to canonical right (call/put)
        opt_type = parsed.get("type", "")
        right_val = "call" if opt_type == "C" else "put" if opt_type == "P" else opt_type.lower()

        return {
            "contract": f"O:{occ_symbol}",
            "underlying": underlying,
            "strike": parsed.get("strike"),
            "expiry": parsed.get("expiry"),
            "right": right_val,
            "quote": {
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "last": last_price,
            },
            "iv": snap.get("impliedVolatility"),
            "greeks": {
                "delta": greeks.get("delta"),
                "gamma": greeks.get("gamma"),
                "theta": greeks.get("theta"),
                "vega": greeks.get("vega"),
            },
            "oi": snap.get("openInterest"),
            "volume": snap.get("dailyBar", {}).get("v"),
            "retrieved_ts": datetime.utcnow().isoformat(),
            "provider_ts": None,
            "source": "alpaca",
        }

    def _fetch_polygon_option_chain(
        self, underlying: str, spot: Optional[float],
        expiration_date: Optional[str], min_expiry: Optional[str],
        max_expiry: Optional[str], strike_range: Optional[float],
        right: Optional[str],
    ) -> List[Dict]:
        """
        Fetch option chain from Polygon /v3/snapshot/options/{underlying}.
        Fallback when Alpaca returns no data.
        """
        params: Dict[str, Any] = {"limit": 250}

        if strike_range is not None and spot and spot > 0:
            params["strike_price.gte"] = spot * (1 - strike_range)
            params["strike_price.lte"] = spot * (1 + strike_range)

        if expiration_date:
            params["expiration_date"] = expiration_date
        elif min_expiry or max_expiry:
            if min_expiry:
                params["expiration_date.gte"] = min_expiry
            if max_expiry:
                params["expiration_date.lte"] = max_expiry

        if right:
            params["contract_type"] = right.lower()

        all_contracts: List[Dict] = []
        url: Optional[str] = f"/v3/snapshot/options/{underlying}"

        while url:
            data = self._make_request(url, params=params)
            if not data:
                break

            for item in data.get("results", []):
                details = item.get("details", {})

                last_quote = item.get("last_quote")
                last_trade = item.get("last_trade")
                bid, ask, quote_ts, bid_size, ask_size = self._extract_last_quote_fields(last_quote)
                last_price, trade_ts = self._extract_last_trade_fields(last_trade)

                mid = None
                if bid is not None and ask is not None:
                    mid = (bid + ask) / 2.0

                provider_ts = quote_ts or trade_ts

                all_contracts.append({
                    "contract": details.get("ticker"),
                    "underlying": underlying,
                    "strike": details.get("strike_price"),
                    "expiry": details.get("expiration_date"),
                    "right": details.get("contract_type"),
                    "quote": {
                        "bid": bid,
                        "ask": ask,
                        "mid": mid,
                        "last": last_price
                    },
                    "iv": item.get("implied_volatility"),
                    "greeks": {
                        "delta": item.get("greeks", {}).get("delta"),
                        "gamma": item.get("greeks", {}).get("gamma"),
                        "theta": item.get("greeks", {}).get("theta"),
                        "vega": item.get("greeks", {}).get("vega")
                    },
                    "oi": item.get("open_interest"),
                    "volume": item.get("day", {}).get("volume"),
                    "retrieved_ts": datetime.utcnow().isoformat(),
                    "provider_ts": provider_ts,
                    "source": "polygon"
                })

            next_url = data.get("next_url")
            if next_url:
                url = next_url.replace(self.base_url, "")
                params = {}
            else:
                url = None

        return all_contracts

    def daily_bars(self, ticker: str, start_date: datetime, end_date: datetime) -> List[Dict]:
        """
        Fetches daily bars (adjusted).
        Primary: Alpaca /v2/stocks/bars.  Fallback: Polygon /v2/aggs.
        """
        # Normalize
        symbol = self.normalize_symbol(ticker)

        # Cache key
        s_str = start_date.strftime("%Y-%m-%d")
        e_str = end_date.strftime("%Y-%m-%d")
        cache_key = f"{symbol}_{s_str}_{e_str}"

        cached = self.cache.get("daily_bars", cache_key)
        if cached:
            _record_daily_bars_to_context(symbol, s_str, e_str, cached)
            return cached

        # --- Alpaca primary (equity bars only, not option symbols) ---
        bars = []
        if not symbol.startswith("O:"):
            try:
                from packages.quantum.brokers.alpaca_client import get_alpaca_client
                alpaca = get_alpaca_client()
                if alpaca:
                    bars = alpaca.get_stock_bars(symbol, start_date, end_date)
                    if bars:
                        logger.info(f"[DAILY_BARS] Alpaca returned {len(bars)} bars for {symbol}")
            except Exception as e:
                logger.warning(f"[DAILY_BARS] Alpaca bars failed for {symbol}: {e}")

        # --- Polygon fallback ---
        if not bars:
            endpoint = f"/v2/aggs/ticker/{symbol}/range/1/day/{s_str}/{e_str}"
            params = {"adjusted": "true", "sort": "asc", "limit": 50000}
            data = self._make_request(endpoint, params)
            if data and "results" in data:
                for r in data["results"]:
                    dt = datetime.fromtimestamp(r["t"] / 1000.0)
                    bars.append({
                        "date": dt.strftime("%Y-%m-%d"),
                        "open": r.get("o"),
                        "high": r.get("h"),
                        "low": r.get("l"),
                        "close": r.get("c"),
                        "volume": r.get("v"),
                        "vwap": r.get("vw")
                    })

        if not bars:
            return []

        _record_daily_bars_to_context(symbol, s_str, e_str, bars)
        self.cache.set("daily_bars", cache_key, bars, self.ttl_daily_bars)
        return bars

    def get_trend(self, symbol: str) -> str:
        """Determines trend using simple moving averages (100 days)."""
        end_date = datetime.now()
        start_date = end_date - timedelta(days=150) # Fetch enough data
        bars = self.daily_bars(symbol, start_date, end_date)

        if not bars:
            return "NEUTRAL"

        prices = [b["close"] for b in bars]
        return calculate_trend(prices)

    def iv_context(self, underlying: str) -> Dict[str, Any]:
        """
        Returns IV context including Rank and Regime.
        Uses historical volatility proxy for now.
        """
        # 1. Fetch history (1 year for rank)
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365)

        bars = self.daily_bars(underlying, start_date, end_date)

        # Calculate returns
        if not bars or len(bars) < 30:
            return {
                "iv_rank": None,
                "iv_rank_source": "unknown",
                "iv_regime": None
            }

        closes = [b["close"] for b in bars]
        returns = []
        for i in range(1, len(closes)):
            r = (closes[i] - closes[i-1]) / closes[i-1]
            returns.append(r)

        # Calculate Rank
        # Note: calculate_iv_rank expects returns list
        rank = calculate_iv_rank(returns) # Returns 0..100 or None

        regime = None
        if rank is not None:
            if rank < 20:
                regime = "suppressed"
            elif rank < 60:
                regime = "normal"
            else:
                regime = "elevated"

        return {
            "iv_rank": rank,
            "iv_rank_source": "hv_proxy",
            "iv_regime": regime
        }

    def normalize_symbol(self, symbol: str) -> str:
        """
        Ensures proper Polygon format.
        Delegates to centralized cache_key_builder for consistent sanitization.
        """
        return normalize_symbol(symbol)

    # Backward compat
    _normalize_symbol = normalize_symbol

    def rates_divs(self, underlying: str, as_of: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Get risk-free rate and dividend yield for an underlying.

        v1.1: Returns env-based constants for deterministic replay.
        Future: could query actual rates/dividends from a data source.

        Args:
            underlying: The underlying symbol
            as_of: Reference timestamp (default: now)

        Returns:
            Dict with risk_free_rate, div_yield, as_of, source
        """
        if as_of is None:
            as_of = datetime.utcnow()

        as_of_date = as_of.strftime("%Y-%m-%d")

        # Get rates from environment with safe defaults
        risk_free_rate = float(os.getenv("REPLAY_RISK_FREE_RATE", "0.05"))
        div_yield = float(os.getenv("REPLAY_DIVIDEND_YIELD", "0.0"))

        payload = {
            "underlying": underlying,
            "risk_free_rate": risk_free_rate,
            "div_yield": div_yield,
            "as_of": as_of_date,
            "source": "env_defaults",
        }

        # Record to DecisionContext if active (for replay feature store)
        ctx = _get_decision_context()
        if ctx is not None:
            try:
                key = f"{underlying}:rates_divs:{as_of_date}"
                metadata = {
                    "source": "env_defaults",
                    "received_ts": int(time.time() * 1000),
                }
                ctx.record_input(
                    key=key,
                    snapshot_type="rates_divs",
                    payload=payload,
                    metadata=metadata,
                )
            except Exception as e:
                logger.debug(f"Failed to record rates_divs to context: {e}")

        return payload
