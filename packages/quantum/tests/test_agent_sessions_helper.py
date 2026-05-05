"""Tests for the shared agent_session helper.

Covers:
- Layer 1: helper unit behavior (start row, complete row, exception path,
  summary mutation, DB-write failure resilience).
- Layer 2: structural assertions that Loss Min + Self-Learning agents
  import and use the helper at their entry points.

Out of scope (per PR): Day Orchestrator (intentionally not refactored)
and Profit Optimization (`apply_calibration` — per-suggestion math
function, doesn't fit the agent_sessions row model; deferred).
"""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from packages.quantum.observability.agent_sessions import (
    AgentSession,
    agent_session,
)


SELF_LEARNING_PATH = (
    Path(__file__).parent.parent / "jobs" / "handlers"
    / "post_trade_learning.py"
)
LOSS_MIN_PATH = (
    Path(__file__).parent.parent / "jobs" / "handlers"
    / "intraday_risk_monitor.py"
)
HELPER_PATH = (
    Path(__file__).parent.parent / "observability" / "agent_sessions.py"
)


# ─────────────────────────────────────────────────────────────────────
# Layer 1 — Helper unit tests
# ─────────────────────────────────────────────────────────────────────


def _make_supabase_mock(start_row_id="session-uuid-1", insert_sink=None,
                       update_sink=None, raise_on=None):
    """Mock supabase client that captures inserts + updates against
    agent_sessions. `raise_on` can be 'insert', 'update', or None to
    simulate DB write failures."""
    raise_on = raise_on or set()
    if isinstance(raise_on, str):
        raise_on = {raise_on}

    mock = MagicMock()

    def table_side_effect(name):
        chain = MagicMock()

        def insert_side_effect(payload):
            if "insert" in raise_on:
                raise RuntimeError("simulated DB insert failure")
            if insert_sink is not None:
                insert_sink.append((name, payload))
            chain.execute.return_value = MagicMock(
                data=[{"id": start_row_id}]
            )
            return chain

        def update_side_effect(payload):
            if "update" in raise_on:
                raise RuntimeError("simulated DB update failure")
            if update_sink is not None:
                update_sink.append((name, payload))
            chain.execute.return_value = MagicMock(data=[])
            return chain

        chain.insert.side_effect = insert_side_effect
        chain.update.side_effect = update_side_effect
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock(data=[{"id": start_row_id}])
        return chain

    mock.table.side_effect = table_side_effect
    return mock


class TestAgentSessionHelper:
    """Layer 1 — direct helper behavior."""

    def test_writes_start_row_with_status_started(self):
        """Helper inserts a row with status='started' on enter."""
        insert_sink = []
        supabase = _make_supabase_mock(insert_sink=insert_sink)
        with agent_session("test_agent", supabase=supabase):
            pass
        starts = [p for (t, p) in insert_sink if t == "agent_sessions"]
        assert len(starts) == 1
        assert starts[0]["agent_name"] == "test_agent"
        assert starts[0]["status"] == "started"
        assert "started_at" in starts[0]
        assert starts[0]["summary"] == {}

    def test_initial_summary_persisted_at_start(self):
        """initial_summary kwarg is written on the start row."""
        insert_sink = []
        supabase = _make_supabase_mock(insert_sink=insert_sink)
        with agent_session(
            "test_agent",
            initial_summary={"trade_date": "2026-05-04"},
            supabase=supabase,
        ):
            pass
        starts = [p for (t, p) in insert_sink if t == "agent_sessions"]
        assert starts[0]["summary"] == {"trade_date": "2026-05-04"}

    def test_updates_to_completed_on_normal_exit(self):
        """On normal exit, helper updates row to status='completed'."""
        update_sink = []
        supabase = _make_supabase_mock(update_sink=update_sink)
        with agent_session("test_agent", supabase=supabase) as s:
            s.summary["candidates"] = 47
        updates = [p for (t, p) in update_sink if t == "agent_sessions"]
        assert len(updates) == 1
        assert updates[0]["status"] == "completed"
        assert "completed_at" in updates[0]
        assert updates[0]["summary"] == {"candidates": 47}
        # No error key on the success path
        assert "error" not in updates[0]

    def test_updates_to_failed_on_exception_and_reraises(self):
        """On exception inside the context, helper updates row to
        status='failed', captures error class + message, then re-raises."""
        update_sink = []
        supabase = _make_supabase_mock(update_sink=update_sink)
        with pytest.raises(ValueError, match="boom"):
            with agent_session("test_agent", supabase=supabase) as s:
                s.summary["partial"] = True
                raise ValueError("boom")
        updates = [p for (t, p) in update_sink if t == "agent_sessions"]
        assert len(updates) == 1
        assert updates[0]["status"] == "failed"
        assert "completed_at" in updates[0]
        assert updates[0]["error"].startswith("ValueError: boom")
        # Partial summary captured even on failure
        assert updates[0]["summary"] == {"partial": True}

    def test_summary_mutation_during_run_is_persisted(self):
        """Caller mutates session.summary; final row reflects the
        mutated state, not the initial_summary."""
        update_sink = []
        supabase = _make_supabase_mock(update_sink=update_sink)
        with agent_session(
            "test_agent",
            initial_summary={"phase": "start"},
            supabase=supabase,
        ) as s:
            s.summary = {"phase": "end", "rows": 12}
        updates = [p for (t, p) in update_sink if t == "agent_sessions"]
        assert updates[0]["summary"] == {"phase": "end", "rows": 12}

    def test_db_insert_failure_does_not_crash_agent(self):
        """Per Loud-Error Doctrine Valid 5: if the start row insert
        fails, the helper logs but the body still runs and the agent
        return value is unaffected."""
        supabase = _make_supabase_mock(raise_on="insert")
        body_ran = {"ran": False}
        with agent_session("test_agent", supabase=supabase) as s:
            body_ran["ran"] = True
            s.summary["x"] = 1
        # Body executed despite DB write failure
        assert body_ran["ran"] is True

    def test_db_update_failure_does_not_crash_agent(self):
        """If the complete-update fails, the helper logs but doesn't
        propagate. Agent's return value is preserved."""
        supabase = _make_supabase_mock(raise_on="update")
        # No exception should escape the context manager
        with agent_session("test_agent", supabase=supabase) as s:
            s.summary["x"] = 1

    def test_exception_in_body_with_failing_update_still_reraises_original(self):
        """If body raises AND the failure-update DB write itself fails,
        the helper logs the DB failure but re-raises the original
        exception (not the DB failure). The body's error is what the
        caller cares about."""
        supabase = _make_supabase_mock(raise_on="update")
        with pytest.raises(ValueError, match="body error"):
            with agent_session("test_agent", supabase=supabase):
                raise ValueError("body error")

    def test_session_object_carries_id_and_name(self):
        """The yielded AgentSession exposes session_id + agent_name."""
        supabase = _make_supabase_mock(start_row_id="known-id-42")
        with agent_session("named_agent", supabase=supabase) as s:
            assert isinstance(s, AgentSession)
            assert s.session_id == "known-id-42"
            assert s.agent_name == "named_agent"


# ─────────────────────────────────────────────────────────────────────
# Layer 2 — Structural assertions for the wired agents
# ─────────────────────────────────────────────────────────────────────


class TestLossMinAgentWiring:
    """Loss Minimization agent imports + uses the helper."""

    def test_loss_min_imports_helper(self):
        src = LOSS_MIN_PATH.read_text(encoding="utf-8")
        assert "from packages.quantum.observability.agent_sessions import agent_session" in src

    def test_loss_min_uses_named_agent(self):
        """agent_name must be 'loss_minimization' to match CLAUDE.md."""
        src = LOSS_MIN_PATH.read_text(encoding="utf-8")
        assert (
            'agent_session("loss_minimization")' in src
            or "agent_session('loss_minimization')" in src
        )

    def test_loss_min_session_wraps_execute_body(self):
        """The agent_session call must appear inside execute(), not at
        module scope, to ensure the helper covers the actual run."""
        src = LOSS_MIN_PATH.read_text(encoding="utf-8")
        # Locate execute() definition
        exec_pos = src.find("def execute(self")
        assert exec_pos != -1, "execute() method must exist on IntradayRiskMonitor"
        # The session call must appear AFTER def execute()
        session_pos = src.find('agent_session("loss_minimization")', exec_pos)
        assert session_pos != -1, (
            "agent_session('loss_minimization') must appear inside "
            "execute() — not at module scope"
        )


class TestSelfLearningAgentWiring:
    """Self-Learning (post_trade_learning) agent imports + uses the helper."""

    def test_self_learning_imports_helper(self):
        src = SELF_LEARNING_PATH.read_text(encoding="utf-8")
        assert "from packages.quantum.observability.agent_sessions import agent_session" in src

    def test_self_learning_uses_named_agent(self):
        """agent_name must be 'self_learning' to match CLAUDE.md."""
        src = SELF_LEARNING_PATH.read_text(encoding="utf-8")
        assert (
            'agent_session("self_learning")' in src
            or "agent_session('self_learning')" in src
        )

    def test_self_learning_session_wraps_execute_body(self):
        src = SELF_LEARNING_PATH.read_text(encoding="utf-8")
        exec_pos = src.find("def execute(self")
        assert exec_pos != -1, (
            "execute() method must exist on PostTradeLearningAgent"
        )
        session_pos = src.find('agent_session("self_learning")', exec_pos)
        assert session_pos != -1, (
            "agent_session('self_learning') must appear inside execute() "
            "— not at module scope"
        )


class TestHelperFollowsDayOrchestratorConvention:
    """Helper's column writes match Day Orchestrator's existing pattern.

    Same columns, same value shapes — guards against drift between the
    new helper and the load-bearing existing convention. If Day Orch's
    convention changes, this test surfaces the divergence.
    """

    def test_helper_writes_same_columns_as_day_orchestrator(self):
        src = HELPER_PATH.read_text(encoding="utf-8")
        # Match Day Orch's 5 columns at start; status='started'
        assert '"agent_name"' in src
        assert '"status": "started"' in src
        assert '"started_at"' in src
        assert '"summary"' in src

    def test_helper_writes_completed_at_on_complete(self):
        src = HELPER_PATH.read_text(encoding="utf-8")
        assert '"completed_at"' in src

    def test_helper_uses_failed_status_on_exception(self):
        """Day Orch never writes 'failed' but the schema has the column.
        New helper fills the gap."""
        src = HELPER_PATH.read_text(encoding="utf-8")
        assert 'status="failed"' in src

    def test_helper_writes_to_error_text_column(self):
        """Schema has `error` (text) column; helper populates it on
        the failure path so future audits can grep failures."""
        src = HELPER_PATH.read_text(encoding="utf-8")
        assert '"error"' in src
