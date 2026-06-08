"""Just-stopped re-entry cooldown — HARD LOCKOUT, durable in Postgres.

The 2026-06-08 whipsaw: the per-symbol loss envelope stopped NFLX at 14:15Z
(−$84); the 16:30Z scan re-ranked NFLX score=100 and re-entered the identical
bearish structure on LIVE money — because the monitor and scanner share NO
state about just-stopped symbols. This module is that shared state.

Design (operator-chosen Option B, intent-based):
- WRITER (risk monitor): on a per-symbol loss envelope stop (the structured
  `EnvelopeResult.symbol_loss_stops` set — NOT daily/weekly/concentration),
  INSERT a cooldown for (cohort_id, symbol) at STAGE time (intent, no fill
  wait). An unfilled close leaves the position open, where a cooldown harmlessly
  blocks open/add and expires at next session open.
- READER (scanner/autopilot), two gates: a FILTER gate (exclude before ranking,
  best-effort) and an authoritative STAGE gate (re-check just before staging an
  open/add; fail-CLOSED on query error — a skipped cycle is cheap, a missed
  lockout isn't). The stage gate blocks adds too: position_id must NOT exempt.

Durable in PG, never in-process memory or RQ Redis: every merge recycles the
worker (the #1039 doc PR did at 19:01:43Z), so memory-wipe-on-recycle is the
zero-shared-state bug we're fixing.

Append-only table; active = EXISTS row WHERE cohort_id=? AND symbol=? AND
cooldown_until > now(). Kill-switch REENTRY_COOLDOWN_ENABLED, default-ON.
"""

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

TABLE = "reentry_cooldowns"
FLAG_ENV = "REENTRY_COOLDOWN_ENABLED"
OVERRIDE_ENV = "REENTRY_COOLDOWN_OVERRIDE_MINUTES"
COOLDOWN_REASON = "envelope_force_close"
_FALLBACK_HOURS = 24  # fail-closed when the clock can't be fetched and no override


class SymbolCooldownActive(Exception):
    """Raised by the stage gate to REJECT an open/add order for a symbol with
    an active cohort cooldown (mirrors #1038's EntryQuoteUnpriceable shape)."""

    def __init__(self, cohort_id: Optional[str], symbol: str, cooldown_until: Any = None):
        self.cohort_id = cohort_id
        self.symbol = symbol
        self.cooldown_until = cooldown_until
        super().__init__(
            f"symbol_cooldown_active: cohort={cohort_id} symbol={symbol} "
            f"until={cooldown_until}"
        )


class CooldownQueryError(Exception):
    """The cooldown read query failed (transient). The stage gate treats this
    as fail-CLOSED (skip staging) — never fail-open into a re-entry."""


def _is_missing_table_error(e: Exception) -> bool:
    """True if the error means `reentry_cooldowns` doesn't exist yet (migration
    not applied). DISTINCT from a transient error: pre-migration there are no
    cooldowns to enforce, and a fail-CLOSED block of EVERY entry during the
    deploy window (worker recycles on merge before the migration lands) is a
    far worse blast radius than the whipsaw. So a missing table fails OPEN with
    a loud warning until the migration applies; transient errors fail closed."""
    msg = str(e).lower()
    return TABLE in msg and (
        "does not exist" in msg
        or "schema cache" in msg
        or "could not find the table" in msg
        or "pgrst205" in msg
    )


def is_enabled() -> bool:
    """REENTRY_COOLDOWN_ENABLED — kill-switch, DEFAULT ON. Empty/unset → ON
    (NOT off; the empty-string-no-op lesson, INTRADAY_TARGET_PROFIT 2026-06-04 /
    #1038). Only an explicit 0/false/no/off disables. Mirrors #1038's helper."""
    raw = os.environ.get(FLAG_ENV, "")
    if not raw.strip():
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


def echo_flag_state() -> None:
    """Log the parsed flag value once (pays down the SILENT-FLAG-PARSE backlog —
    flags must be read-back-confirmed, not assumed)."""
    raw = os.environ.get(FLAG_ENV, "")
    logger.info(
        "[REENTRY_COOLDOWN] flag %s raw=%r → enabled=%s",
        FLAG_ENV, raw, is_enabled(),
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def compute_cooldown_until(clock_fn: Optional[Callable[[], Dict[str, Any]]] = None) -> str:
    """Cooldown expiry as an ISO timestamptz string.

    1. REENTRY_COOLDOWN_OVERRIDE_MINUTES (int) → now()+minutes (tuning/tests).
    2. else: next market session OPEN (Alpaca clock `next_open`) — benches the
       symbol for the rest of the session, robust to time-of-day, aligns with
       the T+1 settled-funds throttle.
    3. FAIL-CLOSED: if the clock can't be fetched/parsed AND no override is set,
       return now()+24h and log CRITICAL — NEVER a zero/past value (that = no
       lockout, the bug).
    """
    raw_override = os.environ.get(OVERRIDE_ENV, "").strip()
    if raw_override:
        try:
            minutes = int(raw_override)
            if minutes > 0:
                return (_now() + timedelta(minutes=minutes)).isoformat()
            logger.warning("[REENTRY_COOLDOWN] %s=%r non-positive; ignoring",
                           OVERRIDE_ENV, raw_override)
        except (TypeError, ValueError):
            logger.warning("[REENTRY_COOLDOWN] %s=%r not an int; ignoring",
                           OVERRIDE_ENV, raw_override)

    try:
        if clock_fn is None:
            from packages.quantum.brokers.alpaca_client import get_alpaca_client
            alpaca = get_alpaca_client()
            if alpaca is None:
                raise RuntimeError("no alpaca client")
            clock_fn = alpaca.get_market_clock
        clock = clock_fn() or {}
        next_open = clock.get("next_open")
        if not next_open:
            raise RuntimeError(f"clock missing next_open: {clock!r}")
        # Validate it parses to a real future-ish timestamp; keep the string.
        parsed = datetime.fromisoformat(str(next_open).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.isoformat()
    except Exception as e:
        fallback = (_now() + timedelta(hours=_FALLBACK_HOURS)).isoformat()
        logger.critical(
            "[REENTRY_COOLDOWN] next_open fetch/parse FAILED (%s) and no override "
            "— FAIL-CLOSED to now()+%dh=%s (never a zero/past cooldown)",
            e, _FALLBACK_HOURS, fallback,
        )
        return fallback


def is_active(supabase, cohort_id: Optional[str], symbol: str) -> bool:
    """True iff an active cooldown row exists for (cohort_id, symbol).

    Raises CooldownQueryError on DB failure so the caller can fail-CLOSED — a
    swallowed read error that returns False is exactly the fail-open-into-
    re-entry we must avoid.
    """
    now_iso = _now().isoformat()
    try:
        res = (
            supabase.table(TABLE)
            .select("id, cooldown_until")
            .eq("cohort_id", cohort_id)
            .eq("symbol", symbol)
            .gt("cooldown_until", now_iso)
            .limit(1)
            .execute()
        )
        return bool(getattr(res, "data", None))
    except Exception as e:
        if _is_missing_table_error(e):
            logger.warning(
                "[REENTRY_COOLDOWN] table %s missing (migration not applied?) — "
                "fail-OPEN (no cooldowns pre-migration): cohort=%s symbol=%s",
                TABLE, cohort_id, symbol,
            )
            return False
        logger.error(
            "[REENTRY_COOLDOWN] is_active query FAILED for cohort=%s symbol=%s: %s",
            cohort_id, symbol, e,
        )
        raise CooldownQueryError(str(e)) from e


def write_cooldown(
    supabase,
    *,
    cohort_id: Optional[str],
    symbol: str,
    cooldown_until: str,
    reason: str = COOLDOWN_REASON,
    triggering_position_id: Optional[str] = None,
    realized_loss: Optional[float] = None,
) -> bool:
    """INSERT a cooldown row (append-only). Idempotent: skips if an active
    cooldown already exists for (cohort_id, symbol). LOUD on failure — a stop
    without a recorded cooldown is the exact gap, so a write failure logs
    CRITICAL + fires an alert and returns False; it does NOT roll back the stop
    (the close already staged). Returns True on insert, False on skip/failure.
    """
    try:
        if is_active(supabase, cohort_id, symbol):
            logger.info(
                "[REENTRY_COOLDOWN] active cooldown already exists for cohort=%s "
                "symbol=%s — skipping duplicate insert", cohort_id, symbol,
            )
            return False
    except CooldownQueryError:
        # Can't confirm idempotency — proceed to insert (append-only; a
        # duplicate is harmless). Do not skip the write on a read error.
        pass

    row = {
        "cohort_id": cohort_id,
        "symbol": symbol,
        "cooldown_until": cooldown_until,
        "reason": reason,
        "triggering_position_id": triggering_position_id,
        "realized_loss": realized_loss,
    }
    try:
        res = supabase.table(TABLE).insert(row).execute()
        if not getattr(res, "data", None):
            raise RuntimeError("insert returned empty data (silent rejection)")
        logger.warning(
            "[REENTRY_COOLDOWN] benched cohort=%s symbol=%s until=%s "
            "(reason=%s pos=%s loss=%s)",
            cohort_id, symbol, cooldown_until, reason, triggering_position_id,
            realized_loss,
        )
        return True
    except Exception as e:
        logger.critical(
            "[REENTRY_COOLDOWN] cooldown INSERT FAILED for cohort=%s symbol=%s: "
            "%s — the symbol was stopped but is NOT benched (re-entry gap). "
            "Stop itself is unaffected.", cohort_id, symbol, e,
        )
        try:
            from packages.quantum.observability.alerts import alert
            alert(
                supabase,
                alert_type="reentry_cooldown_write_failed",
                severity="critical",
                message=(
                    f"re-entry cooldown insert failed for {symbol} "
                    f"(cohort {cohort_id}): {type(e).__name__}"
                ),
                symbol=symbol,
                metadata={
                    "cohort_id": cohort_id, "symbol": symbol,
                    "triggering_position_id": triggering_position_id,
                    "error": str(e)[:300],
                    "consequence": "stopped symbol not benched — re-entry possible",
                },
            )
        except Exception as alert_err:
            logger.critical("[REENTRY_COOLDOWN] alert ALSO failed: %s", alert_err)
        return False


def active_symbols(supabase, cohort_id: Optional[str], symbols: List[str]) -> set:
    """The subset of `symbols` with an active cooldown for `cohort_id`. Raises
    CooldownQueryError on DB failure (caller decides fail-open vs fail-closed)."""
    if not symbols:
        return set()
    now_iso = _now().isoformat()
    try:
        res = (
            supabase.table(TABLE)
            .select("symbol")
            .eq("cohort_id", cohort_id)
            .in_("symbol", list(set(symbols)))
            .gt("cooldown_until", now_iso)
            .execute()
        )
        return {r["symbol"] for r in (getattr(res, "data", None) or [])}
    except Exception as e:
        if _is_missing_table_error(e):
            logger.warning(
                "[REENTRY_COOLDOWN] table %s missing (migration not applied?) — "
                "fail-OPEN (no cooldowns pre-migration): cohort=%s", TABLE, cohort_id,
            )
            return set()
        logger.error(
            "[REENTRY_COOLDOWN] active_symbols query FAILED for cohort=%s: %s",
            cohort_id, e,
        )
        raise CooldownQueryError(str(e)) from e


def resolve_cohort_id(supabase, portfolio_id: Optional[str]) -> Optional[str]:
    """portfolio_id → cohort_id via policy_lab_cohorts (the reader has the
    portfolio; the writer keys on the position's cohort_id, which is 1:1 with
    its portfolio). None when unresolved (cooldown keys on cohort_id; an
    unresolved cohort can't match a written row — safe degradation)."""
    if not portfolio_id:
        return None
    try:
        res = (
            supabase.table("policy_lab_cohorts")
            .select("id")
            .eq("portfolio_id", portfolio_id)
            .limit(1)
            .execute()
        )
        rows = getattr(res, "data", None) or []
        return rows[0]["id"] if rows else None
    except Exception as e:
        logger.warning(
            "[REENTRY_COOLDOWN] resolve_cohort_id failed for portfolio=%s: %s",
            portfolio_id, e,
        )
        return None
