"""Single source of truth for scoping positions to the LIVE book for risk checks.

Live-capital risk decisions — the autopilot circuit breaker, the intraday
monitor's portfolio-level envelope, the midday allocator/concentration, and the
mark-to-market envelope — must see ONLY live-routed positions. shadow_only /
paper_shadow cohort positions are internal/simulated (no real capital) and must
not contaminate a live decision. This is the twin of the #1011 dedup
contamination, in the risk layer: on 2026-06-02 a shadow_only BAC position made
"BAC = 100% of risk" and blocked LIVE entries on a flat live book.

This is NOT a global "ignore shadow": shadow cohorts are managed by their own
paths (paper_exit_evaluator scheduled exits, the paper-shadow executor, and —
unchanged by this module — the intraday monitor's per-position stop/target/
expiration exits). Only the live-CAPITAL risk aggregates scope to live here.

"live" mirrors execution_router.should_submit_to_broker: routing_mode ==
"live_eligible" (the only routing that reaches the broker). shadow_only and
paper_shadow are excluded.
"""

from typing import List

# Canonical live-routing value — matches execution_router.should_submit_to_broker.
LIVE_ROUTING_MODE = "live_eligible"


class LivePositionStateUnavailable(RuntimeError):
    """Authoritative live position state could not be read.

    This is deliberately distinct from a successful zero-row result. Entry
    paths must fail closed on this error; a real empty portfolio/position
    query remains the only representation of a flat live book.
    """


def live_routed_portfolio_ids(supabase, user_id: str) -> List[str]:
    """Return the user's portfolio ids whose routing_mode is live_eligible.

    Raises on query failure — callers wrap in their existing try/except so a
    failure surfaces (loud) rather than silently widening the risk scope.
    """
    res = (
        supabase.table("paper_portfolios")
        .select("id")
        .eq("user_id", user_id)
        .eq("routing_mode", LIVE_ROUTING_MODE)
        .execute()
    )
    return [p["id"] for p in (res.data or [])]
