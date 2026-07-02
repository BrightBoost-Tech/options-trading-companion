"""Consecutive-loss streak breaker (gap-1, NoFx pattern, 2026-07-02).

N consecutive LIVE losing round-trips (learning_feedback_loops
trade_closed, is_paper=false, pnl_realized < 0) → set
``ops_control.entries_paused = true`` with a structured reason + a critical
alert through the existing egress path. Dollar brakes (daily/weekly/
per-symbol) never see a slow bleed of individually-small losses; this does.

Semantics (operator-specified, 07-02):
- FAIL-CLOSED: an error DURING EVALUATION pauses entries — the check is
  never silently skipped (the silent-zero class). A transient DB blip
  pausing entries overnight is the accepted cost; un-pause is a cheap
  operator action.
- Recovery is OPERATOR-ONLY: no code path here (or anywhere) writes
  ``entries_paused = false``.
- Idempotent: an existing pause is never cleared and its reason is never
  clobbered.
- N is config (``STREAK_BREAKER_N``, default 3) so the revisit against the
  gap-2 base rates is a config change, not a PR.
- Tightening-control polarity: ``STREAK_BREAKER_ENABLED`` default-ON;
  only an explicit falsy (0/false/no/off) disables.

Ordering note: the outcome stream is read by ``created_at`` (ingest order —
never NULL) rather than ``updated_at`` (true close time, but NULL on legacy
rows and NULLS-FIRST under desc). Within one ingest run the window is
order-insensitive (all-N-losses is a set property at the boundary the
next run resolves).
"""

import logging
import os
from typing import Any, Dict, List

from packages.quantum.observability.alerts import alert

logger = logging.getLogger(__name__)

_FALSY = ("0", "false", "no", "off")


def _is_enabled() -> bool:
    raw = (os.getenv("STREAK_BREAKER_ENABLED") or "").strip().lower()
    return raw not in _FALSY


def _n() -> int:
    try:
        return max(1, int(os.getenv("STREAK_BREAKER_N", "3")))
    except (TypeError, ValueError):
        return 3


def _pause_entries(client: Any, reason: str, out: Dict[str, Any]) -> None:
    """Set the entries-only halt, idempotently. Never clears, never clobbers."""
    try:
        cur = (
            client.table("ops_control")
            .select("entries_paused, entries_pause_reason")
            .eq("key", "global")
            .limit(1)
            .execute()
        )
        row = (cur.data or [{}])[0]
        if row.get("entries_paused"):
            out["already_paused"] = True
            out["existing_reason"] = row.get("entries_pause_reason")
            return
        client.table("ops_control").update(
            {"entries_paused": True, "entries_pause_reason": reason[:500]}
        ).eq("key", "global").execute()
        out["paused_written"] = True
    except Exception as exc:
        # The pause write itself failed — the loudest remaining option is the
        # alert below plus an error log; there is no stronger lever from here.
        out["pause_write_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        logger.error(
            f"[STREAK_BREAKER] entries-pause WRITE failed after trip: {exc}"
        )
        alert(
            client,
            alert_type="streak_breaker_error",
            severity="critical",
            message=(
                "Streak breaker tripped but the entries_paused write FAILED — "
                "entries are NOT halted. Operator action required: "
                "UPDATE ops_control SET entries_paused=true WHERE key='global'."
            ),
            metadata={"source": "streak_breaker", "reason": reason[:200]},
        )


def evaluate_and_trip(client: Any) -> Dict[str, Any]:
    """Evaluate the live loss streak; trip the entries pause when it binds.

    Never raises. Returns a result dict for job_runs.result surfacing.
    """
    out: Dict[str, Any] = {
        "enabled": _is_enabled(),
        "n": _n(),
        "evaluated": False,
        "tripped": False,
        "paused_written": False,
    }
    if not out["enabled"]:
        out["reason"] = "disabled_by_env"
        return out

    try:
        n = out["n"]
        # NOTE: learning_feedback_loops has NO typed symbol column (verified
        # 07-02 — selecting one 42703s, the #1098 phantom-column class, which
        # under fail-closed semantics would pause entries on every run).
        # Symbol rides inside details_json.
        res = (
            client.table("learning_feedback_loops")
            .select("id, pnl_realized, created_at, details_json")
            .eq("outcome_type", "trade_closed")
            .eq("is_paper", False)
            .order("created_at", desc=True)
            .limit(n)
            .execute()
        )
        rows: List[Dict[str, Any]] = res.data or []
        out["evaluated"] = True

        def _sym(r: Dict[str, Any]) -> str:
            dj = r.get("details_json") or {}
            return (dj.get("symbol") if isinstance(dj, dict) else None) or "?"

        out["window"] = [
            {"id": r.get("id"), "symbol": _sym(r),
             "pnl_realized": r.get("pnl_realized")}
            for r in rows
        ]
        if len(rows) < n:
            out["reason"] = f"insufficient_history:{len(rows)}<{n}"
            return out
        if not all(float(r.get("pnl_realized") or 0) < 0 for r in rows):
            out["reason"] = "streak_broken_by_win"
            return out

        out["tripped"] = True
        losses = ", ".join(
            f"{_sym(r)} {float(r.get('pnl_realized') or 0):+.2f}"
            for r in rows
        )
        reason = (
            f"streak_breaker: {n} consecutive live losing round-trips "
            f"({losses}). Operator un-pause required "
            f"(ops_control.entries_paused)."
        )
        out["reason"] = reason
        logger.critical(f"[STREAK_BREAKER] TRIPPED: {reason}")
        _pause_entries(client, reason, out)
        alert(
            client,
            alert_type="streak_breaker_tripped",
            severity="critical",
            message=reason[:500],
            metadata={
                "source": "streak_breaker",
                "n": n,
                "window": out["window"],
                "paused_written": out.get("paused_written", False),
                "already_paused": out.get("already_paused", False),
            },
        )
        return out

    except Exception as exc:
        # FAIL-CLOSED (operator-specified): an evaluation error results in
        # ENTRIES PAUSED, never a skipped check. This is deliberately the
        # opposite polarity of the read-side are_entries_paused() fail-open —
        # that gate ADDS a halt others set; this evaluator IS the setter.
        out["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
        logger.error(f"[STREAK_BREAKER] evaluation failed — failing CLOSED: {exc}")
        reason = (
            f"streak_breaker_evaluation_error: {type(exc).__name__} — entries "
            f"paused fail-closed (the streak could not be verified). Operator "
            f"un-pause after review."
        )
        _pause_entries(client, reason, out)
        alert(
            client,
            alert_type="streak_breaker_error",
            severity="critical",
            message=reason[:500],
            metadata={"source": "streak_breaker", "error": out["error"]},
        )
        return out
