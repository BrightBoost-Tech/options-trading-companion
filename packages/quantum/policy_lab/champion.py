"""
Cohort champion resolution.

Single source of truth for "which cohort is the live champion at this
moment." Reads `policy_lab_cohorts.promoted_at` (set by the policy_lab
evaluator at `policy_lab/evaluator.py:537-545` when its 7 promotion gates
pass) and returns the most recently promoted cohort name.

Defensive fallback: if no cohort has a non-NULL `promoted_at`, returns
``"aggressive"``. This preserves pre-#62a-D1 hardcoded behavior across
deploy-vs-DB-flip ordering edge cases:

- code deployed before DB migration applied → fallback fires → behavior
  unchanged from pre-PR (aggressive routing)
- DB migration applied before code deployed → no-op (old code ignored
  promoted_at anyway)
- both applied → helper resolves aggressive from the promoted_at column

The warning log is the visibility surface for "we're in fallback mode."
A risk_alerts row is intentionally NOT written — over-alerting during
transition windows. Extended time in fallback mode surfaces via logs.

Used by:
- `policy_lab/fork.py` — tags source suggestions with the champion's
  cohort_name (drives `paper_auto_execute` routing downstream)
- `services/paper_autopilot_service.py` — resolves champion portfolio
  for order staging
- `services/paper_exit_evaluator.py` — third-fallback cohort resolution
  for paper_positions missing direct cohort_id

Doctrine: this helper is the integration seam closure for #62a-D1
(H12 — Parallel architectures without integration). The policy_lab
evaluator writes `promoted_at`; this helper is the consumer that reads
it. See `docs/loud_error_doctrine.md` H12 section.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


_DEFAULT_CHAMPION = "aggressive"


def get_current_champion(user_id: str, supabase) -> str:
    """Return the cohort_name of the currently-promoted champion for
    this user, falling back to ``"aggressive"`` when no cohort is
    promoted.

    Args:
        user_id: trading account owner UUID
        supabase: Supabase client (admin or RLS-authed)

    Returns:
        cohort_name (str). Always returns a value; never None.
    """
    try:
        row = (
            supabase.table("policy_lab_cohorts")
            .select("cohort_name")
            .eq("user_id", user_id)
            .eq("is_active", True)
            .not_.is_("promoted_at", "null")
            .order("promoted_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as e:
        # Real network / permission failure — log loud and fall back.
        # Not silent: the warning surfaces via logs and the fallback
        # is documented behavior, not a silent None return.
        logger.warning(
            "get_current_champion lookup failed for user=%s (%s: %s); "
            "falling back to %r",
            user_id, type(e).__name__, str(e)[:200], _DEFAULT_CHAMPION,
        )
        return _DEFAULT_CHAMPION

    rows = getattr(row, "data", None) or []
    if rows and rows[0].get("cohort_name"):
        return str(rows[0]["cohort_name"])

    # No promoted cohort found — expected during transition windows
    # (e.g., between code deploy and DB migration apply). Log warning
    # so extended time in fallback mode is visible; not an alert.
    logger.warning(
        "No promoted cohort found for user=%s; falling back to %r",
        user_id, _DEFAULT_CHAMPION,
    )
    return _DEFAULT_CHAMPION
