"""
Alpaca-authoritative equity + weekly-P&L helpers.

Extracted from `intraday_risk_monitor.py` in PR #5 of the audit plan as
the 72h follow-up to commit 83872db (2026-04-16). That commit fixed the
`loss_weekly=−190%` false force-close by routing equity and weekly P&L
through Alpaca's API instead of summing per-position MTM snapshots.
This module makes those helpers available to any caller that wants the
same discipline.

Callers get `Optional[float]`:
    - A concrete value means Alpaca answered.
    - `None` means Alpaca was unavailable; the caller MUST skip any loss
      envelope rather than fabricate an equity denominator. Fabricating
      equity is the mechanism behind the 2026-04-16 incident.

The `RISK_EQUITY_SOURCE=legacy` env flag routes back to the pre-fix
behavior for 72 hours as a rip-cord. Scheduled for removal once stable.
See audit plan Phase 3 Q3 for the sequencing rule.
"""

import logging
import os
import time
from datetime import date, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from packages.quantum.observability.alerts import alert

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────
EQUITY_SOURCE = os.environ.get("RISK_EQUITY_SOURCE", "alpaca").lower()

# ── Per-process caches ─────────────────────────────────────────────
# Keyed by user_id. Bursts within a single monitor cycle hit Alpaca at
# most once per endpoint.
#
# Cache-key safety across phase transitions (paper → micro_live → live):
# `get_alpaca_client()` returns a singleton bound at process start to
# either paper or live via `ALPACA_PAPER`. Phase promotion requires a
# Railway redeploy (env var swap), which restarts the process and wipes
# this cache. We therefore never serve stale paper equity to a freshly
# promoted live account. If that invariant changes (e.g., hot-reload of
# `ALPACA_PAPER` without restart), extend the cache key with
# `:paper` / `:live` — not needed today.
_ALPACA_EQUITY_CACHE: Dict[str, Tuple[float, float]] = {}      # user_id → (ts, equity)
_ALPACA_WEEKLY_PNL_CACHE: Dict[str, Tuple[float, float]] = {}  # user_id → (ts, weekly_pnl)
_ALPACA_OBP_CACHE: Dict[str, Tuple[float, float]] = {}         # user_id → (ts, options_buying_power)
_ALPACA_DAILY_PNL_CACHE: Dict[str, Tuple[float, float]] = {}   # user_id → (ts, equity−last_equity)
_ALPACA_LAST_EQUITY_CACHE: Dict[str, Tuple[float, float]] = {} # user_id → (ts, last_equity)
_ALPACA_STATE_TTL_SECONDS = 60


# ── Public API ─────────────────────────────────────────────────────

def get_alpaca_equity(
    user_id: str,
    supabase: Any = None,
    positions: Optional[Iterable[Dict[str, Any]]] = None,
) -> Optional[float]:
    """Return authoritative Alpaca account equity, or None on failure.

    `supabase` and `positions` are used only by the legacy rip-cord
    path (`RISK_EQUITY_SOURCE=legacy`). In the default Alpaca path
    they are ignored.
    """
    if EQUITY_SOURCE == "legacy":
        return _estimate_equity_legacy(supabase, positions or [])
    return _fetch_alpaca_equity(user_id, supabase=supabase)


def get_alpaca_options_buying_power(
    user_id: str,
    supabase: Any = None,
) -> Optional[float]:
    """Return Alpaca `options_buying_power` as float, or `None` on failure.

    #93 fix (2026-05-01): primary source for budget/sizing computations.
    Replaces the prior DB-derived path (cash_service reading stale Plaid
    CUR:USD positions and subtracting `SUM(pending trade_suggestions
    .sizing_metadata.capital_required)`), which produced phantom
    reservations and divergence from broker truth.

    Mirrors `get_alpaca_equity` exactly: 60s TTL per-user cache, alert +
    `None` return on failure. Caller MUST treat `None` as "fall back to
    paper baseline" rather than fabricating a budget — fabricating is the
    mechanism behind the 2026-04-16 weekly-PnL incident.

    Severity is `critical` because this is the single source of truth for
    deployable budget. Failure here makes every cycle until resolution
    size against the paper baseline (or 0), which is operator-visible
    via the resulting `Deployable capital:` log line.
    """
    return _fetch_alpaca_options_buying_power(user_id, supabase=supabase)


def get_alpaca_weekly_pnl(
    user_id: str,
    supabase: Any = None,
) -> Optional[float]:
    """Return week-to-date P&L from Alpaca `get_portfolio_history(1W, 1D)`.

    Formula: `equity_series[-1] − equity_series[0]` over the 1W/1D
    series — current equity minus Monday's open equity.

    Returns `None` when Alpaca is unavailable; callers MUST skip the
    weekly envelope rather than substitute local data.

    `supabase` is used only by the legacy rip-cord path.
    """
    if EQUITY_SOURCE == "legacy":
        return _compute_weekly_pnl_legacy(supabase)
    return _fetch_alpaca_weekly_pnl(user_id, supabase=supabase)


def get_alpaca_daily_pnl(user_id: str, supabase: Any = None) -> Optional[float]:
    """Broker-true day P&L: ``equity − last_equity`` from ``get_account()``.

    Includes REALIZED losses and fees that the open-book unrealized sum is
    blind to (v5-A2). Empirical 06-11: real day −$188 (−8.3%, broker) while
    the unrealized-sum proxy read ≈−4% — a closed losing trade simply
    vanishes from the proxy. Returns ``None`` when Alpaca is unavailable or
    either field is missing/non-positive — callers fall back to the proxy,
    never fabricate.
    """
    now = time.monotonic()
    cached = _ALPACA_DAILY_PNL_CACHE.get(user_id)
    if cached and (now - cached[0]) < _ALPACA_STATE_TTL_SECONDS:
        return cached[1]
    try:
        from packages.quantum.brokers.alpaca_client import get_alpaca_client
        alpaca = get_alpaca_client()
        if not alpaca:
            return None
        acct = alpaca.get_account()
        equity_raw = acct.get("equity")
        last_raw = acct.get("last_equity")
        if equity_raw is None or last_raw is None:
            # None-preserving (Anti-pattern 8): a missing field is not 0.
            # LOUD (2026-06-12): this path returned silently for every
            # cycle from N1 deploy onward because the wrapper's curated
            # get_account() dict omitted `last_equity` entirely — a code
            # bug in OUR payload contract that the caller's generic
            # "broker daily P&L unavailable" line misreported as a broker
            # outage. Name the missing field so the two are never
            # conflated again.
            _missing = "equity" if equity_raw is None else "last_equity"
            logger.warning(
                f"[EQUITY_STATE] get_account() payload missing '{_missing}' "
                f"for {user_id[:8]} — wrapper/consumer contract violation "
                f"(code bug, not a broker outage); daily P&L unavailable"
            )
            return None
        equity = float(equity_raw)
        last_equity = float(last_raw)
        if equity <= 0 or last_equity <= 0:
            return None
        daily = equity - last_equity
        _ALPACA_DAILY_PNL_CACHE[user_id] = (now, daily)
        return daily
    except Exception as e:
        logger.warning(
            f"[EQUITY_STATE] Alpaca daily P&L fetch failed for {user_id[:8]}: {e}"
        )
        return None


def tightened_daily_pnl(
    user_id: str,
    unrealized_sum: float,
    supabase: Any = None,
) -> float:
    """TIGHTENS-ONLY daily-loss feeder (v5-A2 realized-blind brake):
    ``min(open-book unrealized sum, broker equity − last_equity)``.

    The min() means the daily envelope fires on EITHER signal — the proxy
    (which catches intraday open-book drawdown even when broker day-marks
    lag) or the broker-true delta (which catches realized losses the proxy
    cannot see). Existing behavior is never loosened: the proxy is always a
    floor. Broker unavailable → proxy unchanged (legacy behavior, logged).
    """
    broker_daily = get_alpaca_daily_pnl(user_id, supabase=supabase)
    if broker_daily is None:
        logger.warning(
            f"[EQUITY_STATE] broker daily P&L unavailable for {user_id[:8]} — "
            f"daily envelope runs on the open-book proxy only "
            f"(realized losses invisible this cycle)"
        )
        return unrealized_sum
    if broker_daily < unrealized_sum:
        logger.warning(
            f"[EQUITY_STATE] realized-blind gap for {user_id[:8]}: open-book "
            f"proxy ${unrealized_sum:.2f} vs broker-true day ${broker_daily:.2f} "
            f"— daily envelope uses the broker-true (tighter) value"
        )
    return min(unrealized_sum, broker_daily)


# ── v5 phantom-mark-safe daily/weekly brake (2026-06-17 incident) ───
# tightened_daily_pnl (above) fed the loss envelope the BROKER equity delta,
# which for an OPEN multi-leg position carries the broker's per-leg last-trade
# marks (the Alpaca leg-skew phantom, §8). On 2026-06-17 a phantom broker
# unrealized of −285.52 on an incomplete-leg-quote window force-closed the live
# MARA whose EXECUTABLE close realized −15.00 (settled −16.02 the next cycle).
# The phantom-safe brake fires on realized (DB-authoritative, trusted, UN-GATED
# — preserves the #1058/06-11 realized protection) + executable-corroborated
# unrealized (#1034 executable_close_estimate), never the raw broker/DB mark. A
# position whose executable side can't be priced is EXCLUDED + flagged (H9:
# reject the unpriceable, never fabricate); its per-position stop (#1048)
# remains the backstop. get_alpaca_daily_pnl is retained only for the H10
# reconciliation cross-check (reconcile_realized), not the decision.

def realized_pnl_since(
    supabase: Any,
    user_id: str,
    live_portfolio_ids: Iterable[str],
    since_iso: str,
) -> Optional[float]:
    """Σ ``realized_pl`` over LIVE-routed positions closed at/after ``since_iso``
    (DB row of record — authoritative for realized). The TRUSTED, un-gated
    component of the daily/weekly brake: a real realized loss must trip with NO
    corroboration gate.

    Returns 0.0 when there are no live portfolios or no qualifying closes (a
    fact, not an error). Returns None ONLY when the query itself fails — the
    caller must then fail SAFE (fall back to the legacy broker-true brake),
    never silently treat realized as 0 and under-protect.
    """
    ids = [pid for pid in (live_portfolio_ids or []) if pid]
    if not ids:
        return 0.0
    try:
        res = (
            supabase.table("paper_positions")
            .select("realized_pl")
            .eq("user_id", user_id)
            .eq("status", "closed")
            .gte("closed_at", since_iso)
            .in_("portfolio_id", ids)
            .execute()
        )
        return sum(float(r.get("realized_pl") or 0.0) for r in (res.data or []))
    except Exception as e:
        logger.warning(
            "[EQUITY_STATE] realized_pnl_since query failed for %s: %s",
            user_id[:8], e,
        )
        return None


def corroborated_unrealized(
    open_live_positions: Iterable[Dict[str, Any]],
    snapshot_fn: Optional[Callable] = None,
) -> Tuple[float, List[Dict[str, Any]]]:
    """Σ EXECUTABLE-corroborated unrealized over the OPEN live positions, via the
    #1034 ``executable_close_estimate`` (long→bid, short→ask) — never the broker
    or DB mark. Returns ``(total_unrealized, uncorroborated)`` where
    ``uncorroborated`` lists ``{position_id, symbol, reason}`` for positions whose
    executable side could not be priced (``quote_complete`` False, missing
    implied P&L, or the estimate raised). Those are EXCLUDED from the total (H9)
    — never substituted with a phantom mark. Never raises.
    """
    from packages.quantum.analytics import exit_mark_corroboration as _emc
    total = 0.0
    uncorroborated: List[Dict[str, Any]] = []
    for p in (open_live_positions or []):
        pid = p.get("id") if isinstance(p, dict) else None
        sym = p.get("symbol") if isinstance(p, dict) else None
        try:
            est = _emc.executable_close_estimate(p, snapshot_fn=snapshot_fn)
        except Exception as e:
            uncorroborated.append(
                {"position_id": pid, "symbol": sym,
                 "reason": f"estimate_error:{type(e).__name__}"}
            )
            continue
        impl = est.get("achievable_implied_pl")
        if est.get("quote_complete") and impl is not None:
            total += float(impl)
        else:
            uncorroborated.append(
                {"position_id": pid, "symbol": sym, "reason": "quote_incomplete"}
            )
    return total, uncorroborated


def corroborated_daily_pnl(
    realized_today: float,
    open_live_positions: Iterable[Dict[str, Any]],
    snapshot_fn: Optional[Callable] = None,
) -> Tuple[float, List[Dict[str, Any]]]:
    """Phantom-safe daily brake P&L = ``realized_today`` (trusted) + Σ executable-
    corroborated unrealized. Returns ``(daily_pnl, uncorroborated)``. The weekly
    horizon reuses the same unrealized component with realized-this-week."""
    unrealized, uncorroborated = corroborated_unrealized(
        open_live_positions, snapshot_fn=snapshot_fn
    )
    return realized_today + unrealized, uncorroborated


def get_alpaca_last_equity(user_id: str, supabase: Any = None) -> Optional[float]:
    """Broker prior-session closing equity — the realized-blind brake's baseline
    and the CLEAN %-denominator base (``equity_clean = last_equity +
    daily_brake_pnl``). Using last_equity instead of the live (phantom-marked)
    equity stops a bad open-position mark from depressing the denominator and
    inflating the loss % (06-17: −285/1865 = −15.3% vs −15/2136 = −0.7%). None
    when Alpaca is unavailable or the field is missing/non-positive."""
    now = time.monotonic()
    cached = _ALPACA_LAST_EQUITY_CACHE.get(user_id)
    if cached and (now - cached[0]) < _ALPACA_STATE_TTL_SECONDS:
        return cached[1]
    try:
        from packages.quantum.brokers.alpaca_client import get_alpaca_client
        alpaca = get_alpaca_client()
        if not alpaca:
            return None
        acct = alpaca.get_account()
        raw = acct.get("last_equity")
        if raw is None:
            logger.warning(
                "[EQUITY_STATE] get_account() missing 'last_equity' for %s — "
                "clean-denominator base unavailable; daily/weekly envelope skips "
                "this cycle (fail-safe, no force-close on an unknown denominator)",
                user_id[:8],
            )
            return None
        le = float(raw)
        if le <= 0:
            return None
        _ALPACA_LAST_EQUITY_CACHE[user_id] = (now, le)
        return le
    except Exception as e:
        logger.warning(
            "[EQUITY_STATE] Alpaca last_equity fetch failed for %s: %s",
            user_id[:8], e,
        )
        return None


def broker_unrealized_sum(user_id: str, supabase: Any = None) -> Optional[float]:
    """Σ broker per-position unrealized P&L from Alpaca ``get_positions()``. Used
    ONLY for the H10 realized reconciliation cross-check — NOT the brake decision
    (these are the phantom-prone leg-skew marks the executable estimate
    corrects). None on any failure (the cross-check then simply skips)."""
    try:
        from packages.quantum.brokers.alpaca_client import get_alpaca_client
        alpaca = get_alpaca_client()
        if not alpaca:
            return None
        positions = alpaca.get_positions()
        total = 0.0
        for p in (positions or []):
            upl = (
                p.get("unrealized_pl")
                if isinstance(p, dict)
                else getattr(p, "unrealized_pl", None)
            )
            if upl is not None:
                total += float(upl)
        return total
    except Exception as e:
        logger.warning(
            "[EQUITY_STATE] broker_unrealized_sum fetch failed for %s: %s",
            user_id[:8], e,
        )
        return None


def reconcile_realized(
    user_id: str,
    realized_db: Optional[float],
    supabase: Any = None,
    threshold: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """H10 cross-check (FLAG ONLY — never affects the force-close decision):
    compare broker-implied realized (``equity_delta − Σ broker_unrealized``)
    against the DB realized. A large divergence means broker/DB sync drift worth
    a look. Returns a dict (incl. ``divergent``), or None when the DB realized or
    a broker input is unavailable."""
    if realized_db is None:
        return None
    equity_delta = get_alpaca_daily_pnl(user_id, supabase=supabase)
    broker_unreal = broker_unrealized_sum(user_id, supabase=supabase)
    if equity_delta is None or broker_unreal is None:
        return None
    broker_implied = equity_delta - broker_unreal
    diff = abs(broker_implied - float(realized_db))
    thr = (
        threshold if threshold is not None
        else float(os.environ.get("BRAKE_REALIZED_RECONCILE_THRESHOLD", "25"))
    )
    return {
        "divergent": diff > thr,
        "broker_implied_realized": round(broker_implied, 2),
        "realized_db": round(float(realized_db), 2),
        "diff": round(diff, 2),
        "threshold": thr,
    }


# ── Alpaca-authoritative internals ─────────────────────────────────

def _fetch_alpaca_equity(user_id: str, supabase: Any = None) -> Optional[float]:
    now = time.monotonic()
    cached = _ALPACA_EQUITY_CACHE.get(user_id)
    if cached and (now - cached[0]) < _ALPACA_STATE_TTL_SECONDS:
        return cached[1]
    try:
        from packages.quantum.brokers.alpaca_client import get_alpaca_client
        alpaca = get_alpaca_client()
        if not alpaca:
            return None
        acct = alpaca.get_account()
        equity = float(acct.get("equity") or 0)
        if equity <= 0:
            return None
        _ALPACA_EQUITY_CACHE[user_id] = (now, equity)
        return equity
    except Exception as e:
        logger.warning(
            f"[EQUITY_STATE] Alpaca equity fetch failed for {user_id[:8]}: {e}"
        )
        alert(
            supabase,
            alert_type="equity_state_alpaca_account_failed",
            severity="warning",
            message=f"Alpaca get_account() failed: {e}",
            user_id=user_id,
            metadata={
                "error_class": type(e).__name__,
                "error_message": str(e)[:200],
                "call_site": "_fetch_alpaca_equity",
                "source": "alpaca",
            },
        )
        return None


def _fetch_alpaca_options_buying_power(user_id: str, supabase: Any = None) -> Optional[float]:
    now = time.monotonic()
    cached = _ALPACA_OBP_CACHE.get(user_id)
    if cached and (now - cached[0]) < _ALPACA_STATE_TTL_SECONDS:
        return cached[1]
    try:
        from packages.quantum.brokers.alpaca_client import get_alpaca_client
        alpaca = get_alpaca_client()
        if not alpaca:
            return None
        acct = alpaca.get_account()
        raw = acct.get("options_buying_power")
        if raw is None:
            logger.warning(
                f"[EQUITY_STATE] options_buying_power field missing "
                f"for {user_id[:8]} — account may not have options approval"
            )
            return None
        obp = float(raw)
        if obp < 0:
            obp = 0.0
        _ALPACA_OBP_CACHE[user_id] = (now, obp)
        return obp
    except Exception as e:
        logger.warning(
            f"[EQUITY_STATE] Alpaca options_buying_power fetch failed "
            f"for {user_id[:8]}: {e}"
        )
        try:
            alert(
                supabase,
                alert_type="alpaca_options_buying_power_query_failed",
                severity="critical",
                message=f"Alpaca options_buying_power fetch failed: {type(e).__name__}",
                user_id=user_id,
                metadata={
                    "function_name": "_fetch_alpaca_options_buying_power",
                    "error_class": type(e).__name__,
                    "error_message": str(e)[:500],
                    "consequence": (
                        "deployable_capital falls back to paper_baseline_capital. "
                        "Sizing budget may not match live broker buying_power "
                        "until Alpaca connection recovers."
                    ),
                    "operator_action_required": (
                        "Verify ALPACA_API_KEY/ALPACA_SECRET_KEY in Railway env. "
                        "Check Alpaca account status via dashboard. If credentials "
                        "valid and account active, investigate transient API outage. "
                        "System uses paper_baseline fallback until resolved — no "
                        "trading risk, but budget may be smaller than actual buying_power."
                    ),
                },
            )
        except Exception:
            # Alert path failure must not break the fallback chain.
            # Same precedent as H5a/H5b sites and PR #846 execution_router.
            pass
        return None


def _fetch_alpaca_weekly_pnl(user_id: str, supabase: Any = None) -> Optional[float]:
    now = time.monotonic()
    cached = _ALPACA_WEEKLY_PNL_CACHE.get(user_id)
    if cached and (now - cached[0]) < _ALPACA_STATE_TTL_SECONDS:
        return cached[1]
    try:
        from packages.quantum.brokers.alpaca_client import get_alpaca_client
        alpaca = get_alpaca_client()
        if not alpaca:
            return None
        from alpaca.trading.requests import GetPortfolioHistoryRequest
        req = GetPortfolioHistoryRequest(period="1W", timeframe="1D")
        hist = alpaca._call_with_retry(
            alpaca._client.get_portfolio_history, req,
        )
        eq_series = list(getattr(hist, "equity", None) or [])
        if len(eq_series) >= 2:
            weekly_pnl = float(eq_series[-1]) - float(eq_series[0])
        elif len(eq_series) == 1:
            # Single data point (e.g., Monday before first close): no
            # prior equity to compare. Treat as flat week.
            weekly_pnl = 0.0
        else:
            return None
        _ALPACA_WEEKLY_PNL_CACHE[user_id] = (now, weekly_pnl)
        return weekly_pnl
    except Exception as e:
        logger.warning(
            f"[EQUITY_STATE] Alpaca weekly P&L fetch failed for {user_id[:8]}: {e}"
        )
        alert(
            supabase,
            alert_type="equity_state_alpaca_portfolio_history_failed",
            severity="warning",
            message=f"Alpaca get_portfolio_history(1W/1D) failed: {e}",
            user_id=user_id,
            metadata={
                "error_class": type(e).__name__,
                "error_message": str(e)[:200],
                "call_site": "_fetch_alpaca_weekly_pnl",
                "source": "alpaca",
            },
        )
        return None


# ── Legacy rip-cord (RISK_EQUITY_SOURCE=legacy) ────────────────────
# Known-broken. Retained 72h so ops can cut over instantly if the
# Alpaca-authoritative path regresses. Scheduled for removal after the
# observation window in PR #6's neighborhood.

def _estimate_equity_legacy(supabase: Any, positions: Iterable[Dict[str, Any]]) -> float:
    """Pre-2026-04-16 behavior. Reads a non-existent `deployable_capital`
    column, silently falls through to `max(notional * 2, 500)`.
    """
    if supabase is not None:
        try:
            res = supabase.table("go_live_progression") \
                .select("deployable_capital") \
                .limit(1) \
                .execute()
            if res.data and res.data[0].get("deployable_capital"):
                return float(res.data[0]["deployable_capital"])
        except Exception:
            pass

    total = sum(
        abs(float(p.get("avg_entry_price") or 0))
        * abs(float(p.get("quantity") or 1))
        * 100
        for p in positions
    )
    return max(total * 2, 500.0)


def _compute_weekly_pnl_legacy(supabase: Any) -> float:
    """Pre-2026-04-16 behavior. Sums `paper_eod_snapshots.unrealized_pl`
    since Monday — incorrect math (per-position MTM marks, not deltas;
    includes closed positions forever).
    """
    if supabase is not None:
        try:
            monday = date.today() - timedelta(days=date.today().weekday())
            res = supabase.table("paper_eod_snapshots") \
                .select("unrealized_pl") \
                .gte("snapshot_date", monday.isoformat()) \
                .execute()
            if res.data:
                return sum(float(r.get("unrealized_pl") or 0) for r in res.data)
        except Exception:
            pass
    return 0.0


# ── Test-only helper ───────────────────────────────────────────────

def _reset_caches_for_testing() -> None:
    """Reset the per-user caches between tests. Not for production use."""
    _ALPACA_EQUITY_CACHE.clear()
    _ALPACA_WEEKLY_PNL_CACHE.clear()
    _ALPACA_OBP_CACHE.clear()
    _ALPACA_DAILY_PNL_CACHE.clear()
