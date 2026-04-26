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
from typing import Any, Dict, Iterable, Optional, Tuple

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
