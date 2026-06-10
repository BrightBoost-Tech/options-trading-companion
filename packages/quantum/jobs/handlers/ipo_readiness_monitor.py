"""
IPO Readiness Monitor — daily watch for newly-listed symbols (SPCX, 2026-06-12).

One-time-diagnostic deliverable (2026-06-09): a new listing becomes ELIGIBLE
the moment it is tradeable by the system's OWN rules — no gate is loosened,
no special case, no pre-staged orders. This job only OBSERVES and logs the
transitions:
  (a) first equity quote seen (provider probe)
  (b) first options chain seen (provider probe)
  (c) today's gate outcomes for the symbol from the system's own artifacts
      (universe_selection_log membership, suggestion_rejections reasons,
      trade_suggestions created)
plus approximate progress toward the scanner's 50-daily-closes history gate
(options_scanner `insufficient_history` — the binding constraint for a new
listing: ~50 trading days post-IPO, BEFORE the chain is even fetched). The
per-day gate-failure log IS the deliverable: it shows exactly when the
symbol becomes genuinely tradeable, gate by gate.

State (first-seen dates) is carried in this job's own job_runs.result — no
migration, durable, queryable. First-seen transitions also write an INFO
risk_alert so they surface in the normal alert stream. Watch list:
IPO_WATCH_SYMBOLS env (default "SPCX"); empty string retires the watch.
READ-ONLY against providers; writes nothing but its own job result + info
alerts.
"""

import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from packages.quantum.jobs.handlers.utils import get_admin_client
from packages.quantum.jobs.handlers.exceptions import RetryableJobError

logger = logging.getLogger(__name__)

JOB_NAME = "ipo_readiness_monitor"

# The scanner's insufficient_history threshold (options_scanner.py — 50 daily
# closes required before strategy evaluation). Mirrored here ONLY to report
# progress; the gate itself is untouched.
HISTORY_GATE_CLOSES = 50


def _watch_symbols() -> List[str]:
    raw = os.environ.get("IPO_WATCH_SYMBOLS", "SPCX")
    return [s.strip().upper() for s in raw.split(",") if s.strip()]


def _load_prior_state(client: Any) -> Dict[str, Dict[str, Any]]:
    """First-seen dates from this job's most recent succeeded run."""
    try:
        res = client.table("job_runs") \
            .select("result") \
            .eq("job_name", JOB_NAME) \
            .eq("status", "succeeded") \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()
        if res.data:
            return ((res.data[0].get("result") or {}).get("state")) or {}
    except Exception as e:
        logger.warning(f"[IPO_WATCH] prior-state load failed (fresh start): {e}")
    return {}


def _approx_trading_days(start_iso: Optional[str], today: date) -> Optional[int]:
    """Weekday count from first_quote_date through today — an APPROXIMATION
    of accumulated daily closes (ignores market holidays; labeled approx in
    the report)."""
    if not start_iso:
        return None
    try:
        start = date.fromisoformat(start_iso)
    except (TypeError, ValueError):
        return None
    n, d = 0, start
    while d <= today:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def _transition_alert(client: Any, sym: str, alert_type: str, message: str) -> None:
    try:
        from packages.quantum.observability.alerts import alert
        alert(client, alert_type=alert_type, severity="info",
              message=message, symbol=sym)
    except Exception as e:
        logger.warning(f"[IPO_WATCH] transition alert failed: {e}")


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    started = time.time()
    try:
        client = get_admin_client()
        from packages.quantum.market_data import PolygonService
        md = PolygonService()

        today = datetime.now(timezone.utc).date()
        today_iso = today.isoformat()
        prior = _load_prior_state(client)
        state: Dict[str, Dict[str, Any]] = {}
        report: Dict[str, Dict[str, Any]] = {}

        for sym in _watch_symbols():
            st = dict(prior.get(sym) or {})

            # (a) equity quote probe — fail-soft per symbol
            quote_seen = False
            try:
                q = md.get_recent_quote(sym) or {}
                quote_seen = bool(
                    q.get("price") or (q.get("bid") and q.get("ask"))
                )
            except Exception as e:
                logger.warning(f"[IPO_WATCH] {sym}: equity quote probe failed: {e}")
            if quote_seen and not st.get("first_quote_date"):
                st["first_quote_date"] = today_iso
                _transition_alert(
                    client, sym, "ipo_watch_first_equity_quote",
                    f"{sym}: first equity quote seen {today_iso}",
                )

            # (b) options chain probe — fail-soft per symbol
            chain_seen = False
            try:
                chain = md.get_option_chain(sym, min_dte=1, max_dte=120, limit=25)
                chain_seen = bool(chain)
            except Exception as e:
                logger.warning(f"[IPO_WATCH] {sym}: option chain probe failed: {e}")
            if chain_seen and not st.get("first_chain_date"):
                st["first_chain_date"] = today_iso
                _transition_alert(
                    client, sym, "ipo_watch_first_option_chain",
                    f"{sym}: first options chain seen {today_iso}",
                )

            # (c) the system's own gate verdicts for today
            rejections: List[str] = []
            selected: Optional[bool] = None
            suggested = 0
            try:
                rej = client.table("suggestion_rejections") \
                    .select("reason") \
                    .eq("symbol", sym) \
                    .eq("cycle_date", today_iso) \
                    .execute()
                rejections = sorted({r.get("reason") for r in (rej.data or []) if r.get("reason")})
            except Exception as e:
                logger.warning(f"[IPO_WATCH] {sym}: rejection read failed: {e}")
            try:
                sel = client.table("universe_selection_log") \
                    .select("selected_symbols") \
                    .gte("selected_at", f"{today_iso}T00:00:00+00:00") \
                    .order("selected_at", desc=True) \
                    .limit(1) \
                    .execute()
                if sel.data:
                    selected = sym in (sel.data[0].get("selected_symbols") or [])
            except Exception as e:
                logger.warning(f"[IPO_WATCH] {sym}: selection-log read failed: {e}")
            try:
                sug = client.table("trade_suggestions") \
                    .select("id") \
                    .eq("ticker", sym) \
                    .eq("cycle_date", today_iso) \
                    .execute()
                suggested = len(sug.data or [])
            except Exception as e:
                logger.warning(f"[IPO_WATCH] {sym}: suggestions read failed: {e}")

            closes = _approx_trading_days(st.get("first_quote_date"), today)
            report[sym] = {
                "quote_seen_today": quote_seen,
                "chain_seen_today": chain_seen,
                "first_quote_date": st.get("first_quote_date"),
                "first_chain_date": st.get("first_chain_date"),
                "scanned_today": selected,
                "rejection_reasons_today": rejections,
                "suggestions_today": suggested,
                "approx_daily_closes": closes,
                "history_gate_remaining": (
                    max(0, HISTORY_GATE_CLOSES - closes)
                    if closes is not None else None
                ),
            }
            state[sym] = st
            logger.info(f"[IPO_WATCH] {sym}: {report[sym]}")

        return {
            "ok": True,
            "state": state,
            "report": report,
            "watched": _watch_symbols(),
            "timing_ms": (time.time() - started) * 1000,
        }

    except Exception as e:
        raise RetryableJobError(f"ipo_readiness_monitor failed: {e}")
