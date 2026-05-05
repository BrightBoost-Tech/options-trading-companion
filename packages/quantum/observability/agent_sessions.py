"""
Shared agent_session helper — closes the documented blind spot where
Loss Minimization and Self-Learning Agents ran on schedule but produced
no `agent_sessions` rows. Day Orchestrator was the only agent writing
session observability, per CLAUDE.md "Managed Agents" table.

Day Orchestrator's existing pattern (jobs/handlers/day_orchestrator.py
_log_session_start / _log_session_complete) is the load-bearing
convention. This helper produces IDENTICAL rows — same columns, same
values, same lifecycle — but exposes a context-manager call site that
is cleaner for new agents to adopt without each duplicating Day Orch's
imperative two-call shape.

Day Orchestrator itself is intentionally NOT migrated to use this
helper in this PR. Refactor of existing observability is separate
scope per the doctrine sweep playbook.

Profit Optimization (`apply_calibration` in calibration_service.py) is
also deferred — it is a per-suggestion math function called hundreds of
times per scanner cycle, not a per-invocation agent. Wrapping it row-
by-row would flood `agent_sessions` without insight. Per-cycle
aggregation at the workflow_orchestrator layer is the right shape; that
work is out of scope here.

Schema reference (`agent_sessions`):
    id            uuid     NOT NULL  (PK)
    created_at    tstz
    agent_name    text     NOT NULL
    session_id    text
    status        text       — 'started' | 'completed' | 'failed'
    started_at    tstz
    completed_at  tstz
    summary       jsonb
    error         text
"""
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, Optional

logger = logging.getLogger(__name__)


class AgentSession:
    """Mutable session state passed to the caller via the context manager.

    The caller may mutate `summary` during the run; whatever is in the
    dict at exit time is persisted to `agent_sessions.summary`.
    """

    def __init__(self, session_id: str, agent_name: str):
        self.session_id = session_id
        self.agent_name = agent_name
        self.summary: Dict[str, Any] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _start_session_row(
    supabase, agent_name: str, initial_summary: Optional[Dict[str, Any]],
) -> str:
    """Insert the start row. Returns session_id, or '' if the insert failed.

    DB-write failures are logged but do not propagate. Per Loud-Error
    Doctrine Valid 5 — observability never blocks the work it observes.
    Same internal-try/except convention as Day Orchestrator's
    `_log_session_start`.
    """
    try:
        res = supabase.table("agent_sessions").insert({
            "agent_name": agent_name,
            "status": "started",
            "started_at": _now_iso(),
            "summary": initial_summary or {},
        }).execute()
        return res.data[0]["id"] if res.data else ""
    except Exception as exc:
        logger.error(
            f"[AGENT_SESSION] Failed to log session start for "
            f"agent={agent_name}: {exc}"
        )
        return ""


def _complete_session_row(
    supabase,
    session_id: str,
    status: str,
    summary: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> None:
    """Update an existing session row. No-op if session_id is empty.

    Same internal-try/except convention as Day Orchestrator's
    `_log_session_complete`.
    """
    if not session_id:
        return
    try:
        update: Dict[str, Any] = {
            "status": status,
            "completed_at": _now_iso(),
        }
        if summary is not None:
            update["summary"] = summary
        if error is not None:
            update["error"] = error[:500]  # text column; cap length
        supabase.table("agent_sessions") \
            .update(update) \
            .eq("id", session_id) \
            .execute()
    except Exception as exc:
        logger.error(
            f"[AGENT_SESSION] Failed to log session complete for "
            f"session={session_id}: {exc}"
        )


@contextmanager
def agent_session(
    agent_name: str,
    initial_summary: Optional[Dict[str, Any]] = None,
    supabase=None,
) -> Generator[AgentSession, None, None]:
    """Track an agent run end-to-end in `agent_sessions`.

    Writes a row at start (status='started', started_at=NOW) and updates
    at end (status='completed' on normal exit, 'failed' on exception with
    error captured). On exception, re-raises after writing the failure
    row — the agent's outer error path keeps its original semantics.

    DB-write failures are logged but never block the agent. If the start
    row fails to insert, session_id is empty and the complete-update is
    a no-op; the agent runs normally with no observability for that run.

    Usage:
        with agent_session("loss_minimization", initial_summary={"x": 1}) as s:
            # ... agent body ...
            s.summary["candidates_evaluated"] = 47
            return result_dict

    Args:
        agent_name: stable identifier — written to `agent_sessions.agent_name`
        initial_summary: dict persisted at start (overwritten by `s.summary`
            mutations during the run)
        supabase: optional admin client; defaults to the canonical one
    """
    if supabase is None:
        # Reuse the same admin-client helper Day Orchestrator uses
        from packages.quantum.jobs.handlers.utils import get_admin_client
        supabase = get_admin_client()

    session_id = _start_session_row(supabase, agent_name, initial_summary)
    session = AgentSession(session_id=session_id, agent_name=agent_name)

    try:
        yield session
    except Exception as exc:
        _complete_session_row(
            supabase,
            session_id,
            status="failed",
            summary=session.summary or None,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    else:
        _complete_session_row(
            supabase,
            session_id,
            status="completed",
            summary=session.summary or None,
        )
