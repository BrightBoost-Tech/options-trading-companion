"""Truthful funnel status for trade_suggestions (backlog P1#5).

The funnel bug: execution never stamped the suggestion, so an executed
suggestion stayed ``pending`` and the next-morning ``suggestions_close`` sweep
relabeled every stale ``pending`` row ``dismissed`` — the funnel showed
executed trades as dismissed. Two layers restore truth, behind ONE default-ON
flag:

  A. ``stamp_executed()`` — called at the ``paper_positions`` INSERT seam
     (``paper_endpoints``, the only place ``paper_positions.suggestion_id`` is
     set). A position INSERT is the initial fill; an add-to-position is an
     UPDATE to an existing row, so it never reaches this seam and cannot
     mis-stamp the original. A cohort fork carries its own ``suggestion_id``
     and is stamped on its own fill.
  B. ``reconcile_stale_pending()`` — the morning sweep reconciles each
     prior-day ``pending`` suggestion to a truthful TERMINAL status via the
     position-exists signal: a ``paper_positions`` row exists for its id ->
     ``executed``, none -> ``dismissed``. Replaces the legacy blanket
     ``pending -> dismissed``.

A and B both key off the SAME position-exists signal and only ever write
``executed``, so they are idempotent: whichever fires first wins, the other is
a no-op. A gives same-day real-time truth; B reconciles prior-day stragglers
and corrects anything A missed (e.g. an entry path that forgets to stamp), so
a suggestion can never get stuck ``pending``.

Flag ``FUNNEL_STATUS_TRUTHFUL_ENABLED`` — default ON (data-truth, not
live-risk): unset/empty -> ON; only an explicit ``0/false/no/off`` reverts to
the legacy stamp/sweep. Safety-flag polarity per CLAUDE.md §3.

NOTE: this module is intentionally dependency-light (os + logging only) so it
can be imported from both ``paper_endpoints`` (the fill path) and
``suggestions_close`` (the sweep) without circular-import risk.
"""
import logging
import os
from typing import Any, Dict

logger = logging.getLogger(__name__)

_TABLE = "trade_suggestions"
_POSITIONS = "paper_positions"

# Statuses a suggestion may be promoted FROM into 'executed' — the in-flight,
# not-yet-terminal states. Excludes terminal history (dismissed / superseded /
# expired) so a real-time stamp can never overwrite it; a HISTORICAL
# dismissed-but-executed row is corrected by the separate supervised backfill,
# not by this real-time stamp.
_PROMOTABLE = ["pending", "staged", "queued"]


def funnel_status_truthful_enabled() -> bool:
    """``FUNNEL_STATUS_TRUTHFUL_ENABLED`` — default ON.

    Empty/unset -> ON; only an explicit ``0/false/no/off`` disables (reverting
    to the legacy 'staged'-stamp + blanket 'pending->dismissed' sweep).
    """
    raw = os.environ.get("FUNNEL_STATUS_TRUTHFUL_ENABLED", "")
    if not raw.strip():
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off")


def stamp_executed(supabase, suggestion_id: Any) -> bool:
    """Layer A — promote a suggestion to ``executed`` at position creation.

    Idempotent and non-fatal:
      * promotes ONLY from an in-flight status (``_PROMOTABLE``), so a second
        call — e.g. an incremental-fill insert for an already-executed
        suggestion, or a future add-to-position — is a no-op;
      * never raises into the caller's fill path.

    Returns True iff a row was promoted. No-op (returns False) when the flag is
    off or ``suggestion_id`` is falsy.
    """
    if not suggestion_id or not funnel_status_truthful_enabled():
        return False
    try:
        res = (
            supabase.table(_TABLE)
            .update({"status": "executed"})
            .eq("id", suggestion_id)
            .in_("status", _PROMOTABLE)
            .execute()
        )
        promoted = bool(getattr(res, "data", None))
        if promoted:
            logger.info(
                f"[FUNNEL_STATUS] suggestion {str(suggestion_id)[:8]} "
                f"-> executed (position created)"
            )
        return promoted
    except Exception as e:  # non-fatal: never break the fill path
        logger.warning(
            f"[FUNNEL_STATUS] stamp_executed failed for "
            f"{str(suggestion_id)[:8]}: {e}"
        )
        return False


def reconcile_stale_pending(
    supabase, user_id: str, today_str: str
) -> Dict[str, int]:
    """Layer B — reconcile prior-day ``pending`` suggestions to a truthful
    terminal status.

    For each ``(user_id, status='pending', cycle_date < today_str)``:
      * a ``paper_positions`` row exists for its id -> ``executed``
      * none                                        -> ``dismissed``

    Replaces the legacy blanket ``pending -> dismissed``. Idempotent with
    Layer A (same position-exists signal). Returns
    ``{'executed': n, 'dismissed': n}``.
    """
    counts = {"executed": 0, "dismissed": 0}

    stale = (
        supabase.table(_TABLE)
        .select("id")
        .eq("user_id", user_id)
        .eq("status", "pending")
        .lt("cycle_date", today_str)
        .execute()
    )
    stale_ids = [
        r["id"] for r in (getattr(stale, "data", None) or []) if r.get("id")
    ]
    if not stale_ids:
        return counts

    pos = (
        supabase.table(_POSITIONS)
        .select("suggestion_id")
        .in_("suggestion_id", stale_ids)
        .execute()
    )
    executed_ids = sorted({
        r["suggestion_id"]
        for r in (getattr(pos, "data", None) or [])
        if r.get("suggestion_id")
    })
    executed_set = set(executed_ids)
    dismissed_ids = [sid for sid in stale_ids if sid not in executed_set]

    if executed_ids:
        supabase.table(_TABLE).update({"status": "executed"}) \
            .in_("id", executed_ids).execute()
        counts["executed"] = len(executed_ids)
    if dismissed_ids:
        supabase.table(_TABLE).update({"status": "dismissed"}) \
            .in_("id", dismissed_ids).execute()
        counts["dismissed"] = len(dismissed_ids)
    return counts
