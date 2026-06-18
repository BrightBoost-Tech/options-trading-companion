"""Tests for truthful funnel status transitions (backlog P1#5).

Bug: execution never stamped the suggestion, so executed suggestions stayed
``pending`` and the morning ``suggestions_close`` sweep relabeled them
``dismissed`` (funnel showed executed trades as dismissed). Two layers behind
one default-ON flag (``FUNNEL_STATUS_TRUTHFUL_ENABLED``):

  A. ``stamp_executed`` at the ``paper_positions`` INSERT seam (initial fill;
     idempotent so an add-to-position / incremental-fill can't mis-stamp).
  B. ``reconcile_stale_pending`` sweep: prior-day pending with a position ->
     ``executed``, without -> ``dismissed``.

These are unit tests on the helper (with a tiny fake Supabase that records
updates) plus source-level structural assertions for the two wiring seams and
the supersession-set invariant.
"""
import inspect
import os
from pathlib import Path
from unittest.mock import patch

from packages.quantum.services import suggestion_status as ss
from packages.quantum.services.suggestion_status import (
    funnel_status_truthful_enabled,
    stamp_executed,
    reconcile_stale_pending,
)

_PKG = Path(__file__).parent.parent


# ── tiny fake Supabase (supports the exact builder chains used) ──────

class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, store, table):
        self.store = store
        self.table = table
        self.op = "select"
        self.payload = None
        self.filters = {}   # col -> (op, val)
        self.ins = {}       # col -> [vals]

    def select(self, *a, **k):
        self.op = "select"; return self

    def update(self, payload):
        self.op = "update"; self.payload = payload; return self

    def insert(self, payload):
        self.op = "insert"; self.payload = payload; return self

    def eq(self, col, val):
        self.filters[col] = ("eq", val); return self

    def lt(self, col, val):
        self.filters[col] = ("lt", val); return self

    def in_(self, col, vals):
        self.ins[col] = list(vals); return self

    def execute(self):
        return self.store._execute(self)


class FakeSupabase:
    def __init__(self, suggestions=None, positions=None):
        # suggestions: [{id, user_id, status, cycle_date}]
        # positions:   [{suggestion_id}]
        self.suggestions = [dict(r) for r in (suggestions or [])]
        self.positions = [dict(r) for r in (positions or [])]
        self.updates = []  # (table, payload, filters, ins)

    def table(self, name):
        return _Query(self, name)

    def _rows(self, table):
        return self.suggestions if table == "trade_suggestions" else self.positions

    def _match(self, q):
        out = []
        for r in self._rows(q.table):
            ok = True
            for col, (op, val) in q.filters.items():
                if op == "eq" and r.get(col) != val:
                    ok = False
                if op == "lt" and not (str(r.get(col)) < str(val)):
                    ok = False
            for col, vals in q.ins.items():
                if r.get(col) not in vals:
                    ok = False
            if ok:
                out.append(r)
        return out

    def _execute(self, q):
        if q.op == "update":
            affected = self._match(q)
            self.updates.append((q.table, dict(q.payload), dict(q.filters), dict(q.ins)))
            for row in affected:
                row.update(q.payload)
            return _Result([dict(r) for r in affected])
        return _Result([dict(r) for r in self._match(q)])

    def status_of(self, sid):
        for r in self.suggestions:
            if r.get("id") == sid:
                return r.get("status")
        return None


# ── flag polarity ───────────────────────────────────────────────────

class TestFlag:
    def test_default_on(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FUNNEL_STATUS_TRUTHFUL_ENABLED", None)
            assert funnel_status_truthful_enabled() is True

    def test_empty_is_on(self):
        with patch.dict(os.environ, {"FUNNEL_STATUS_TRUTHFUL_ENABLED": "  "}):
            assert funnel_status_truthful_enabled() is True

    def test_explicit_off_variants(self):
        for v in ("0", "false", "no", "off", "OFF", "False"):
            with patch.dict(os.environ, {"FUNNEL_STATUS_TRUTHFUL_ENABLED": v}):
                assert funnel_status_truthful_enabled() is False

    def test_explicit_on(self):
        with patch.dict(os.environ, {"FUNNEL_STATUS_TRUTHFUL_ENABLED": "1"}):
            assert funnel_status_truthful_enabled() is True


# ── Layer A: stamp_executed ─────────────────────────────────────────

class TestStampExecuted:
    def setup_method(self):
        os.environ.pop("FUNNEL_STATUS_TRUTHFUL_ENABLED", None)  # default ON

    def test_pending_promoted_to_executed(self):
        sb = FakeSupabase(suggestions=[{"id": "s1", "status": "pending"}])
        assert stamp_executed(sb, "s1") is True
        assert sb.status_of("s1") == "executed"

    def test_staged_promoted_to_executed(self):
        sb = FakeSupabase(suggestions=[{"id": "s1", "status": "staged"}])
        assert stamp_executed(sb, "s1") is True
        assert sb.status_of("s1") == "executed"

    def test_idempotent_on_already_executed(self):
        # add-to-position / incremental-fill seam: a second insert for an
        # already-executed suggestion must NOT re-stamp or clobber.
        sb = FakeSupabase(suggestions=[{"id": "s1", "status": "executed"}])
        assert stamp_executed(sb, "s1") is False
        assert sb.status_of("s1") == "executed"

    def test_does_not_clobber_dismissed(self):
        # a genuinely-dismissed (or superseded) suggestion is terminal history;
        # the real-time stamp leaves it alone (backfill handles history).
        sb = FakeSupabase(suggestions=[{"id": "s1", "status": "dismissed"}])
        assert stamp_executed(sb, "s1") is False
        assert sb.status_of("s1") == "dismissed"

    def test_flag_off_is_noop(self):
        sb = FakeSupabase(suggestions=[{"id": "s1", "status": "pending"}])
        with patch.dict(os.environ, {"FUNNEL_STATUS_TRUTHFUL_ENABLED": "0"}):
            assert stamp_executed(sb, "s1") is False
        assert sb.status_of("s1") == "pending"   # untouched
        assert sb.updates == []                  # no DB write attempted

    def test_falsy_suggestion_id_noop(self):
        sb = FakeSupabase(suggestions=[])
        assert stamp_executed(sb, None) is False
        assert sb.updates == []

    def test_cohort_fork_stamped_by_own_sid(self):
        # fork carries its own suggestion_id; stamping the fork must not touch
        # the parent suggestion.
        sb = FakeSupabase(suggestions=[
            {"id": "parent", "status": "executed"},
            {"id": "fork", "status": "pending"},
        ])
        assert stamp_executed(sb, "fork") is True
        assert sb.status_of("fork") == "executed"
        assert sb.status_of("parent") == "executed"  # unchanged

    def test_never_raises(self):
        class Boom:
            def table(self, *a, **k): raise RuntimeError("db down")
        assert stamp_executed(Boom(), "s1") is False  # swallowed


# ── Layer B: reconcile_stale_pending ────────────────────────────────

class TestReconcileStalePending:
    def setup_method(self):
        os.environ.pop("FUNNEL_STATUS_TRUTHFUL_ENABLED", None)  # default ON

    def test_executed_when_position_exists(self):
        sb = FakeSupabase(
            suggestions=[{"id": "s1", "user_id": "u", "status": "pending",
                          "cycle_date": "2026-06-10"}],
            positions=[{"suggestion_id": "s1"}],
        )
        out = reconcile_stale_pending(sb, "u", "2026-06-18")
        assert out == {"executed": 1, "dismissed": 0}
        assert sb.status_of("s1") == "executed"

    def test_dismissed_when_no_position(self):
        sb = FakeSupabase(
            suggestions=[{"id": "s1", "user_id": "u", "status": "pending",
                          "cycle_date": "2026-06-10"}],
            positions=[],
        )
        out = reconcile_stale_pending(sb, "u", "2026-06-18")
        assert out == {"executed": 0, "dismissed": 1}
        assert sb.status_of("s1") == "dismissed"

    def test_mixed_partition(self):
        # B backstop: one prior-day pending WITH a position -> executed; one
        # WITHOUT -> dismissed.
        sb = FakeSupabase(
            suggestions=[
                {"id": "exec", "user_id": "u", "status": "pending", "cycle_date": "2026-06-10"},
                {"id": "drop", "user_id": "u", "status": "pending", "cycle_date": "2026-06-10"},
            ],
            positions=[{"suggestion_id": "exec"}],
        )
        out = reconcile_stale_pending(sb, "u", "2026-06-18")
        assert out == {"executed": 1, "dismissed": 1}
        assert sb.status_of("exec") == "executed"
        assert sb.status_of("drop") == "dismissed"

    def test_today_and_nonpending_untouched(self):
        sb = FakeSupabase(
            suggestions=[
                {"id": "today", "user_id": "u", "status": "pending", "cycle_date": "2026-06-18"},
                {"id": "done", "user_id": "u", "status": "executed", "cycle_date": "2026-06-10"},
                {"id": "other", "user_id": "OTHER", "status": "pending", "cycle_date": "2026-06-10"},
            ],
            positions=[],
        )
        out = reconcile_stale_pending(sb, "u", "2026-06-18")
        assert out == {"executed": 0, "dismissed": 0}
        assert sb.status_of("today") == "pending"   # same-day, not swept
        assert sb.status_of("done") == "executed"   # not pending
        assert sb.status_of("other") == "pending"   # different user

    def test_empty_is_noop(self):
        sb = FakeSupabase(suggestions=[], positions=[])
        assert reconcile_stale_pending(sb, "u", "2026-06-18") == {"executed": 0, "dismissed": 0}
        assert sb.updates == []


# ── structural: wiring + invariants ─────────────────────────────────

class TestWiringAndInvariants:
    def test_layer_a_wired_at_both_position_inserts(self):
        src = (_PKG / "paper_endpoints.py").read_text(encoding="utf-8")
        assert "from packages.quantum.services.suggestion_status import stamp_executed" in src
        # stamped at BOTH paper_positions insert seams
        assert src.count("stamp_executed(supabase, order.get(\"suggestion_id\"))") >= 2

    def test_layer_b_wired_behind_flag_with_legacy_fallback(self):
        src = (_PKG / "jobs" / "handlers" / "suggestions_close.py").read_text(encoding="utf-8")
        assert "reconcile_stale_pending" in src
        assert "funnel_status_truthful_enabled" in src
        # legacy blanket dismiss retained for the flag-off branch
        assert '.update({"status": "dismissed"})' in src

    def test_executed_not_in_supersession_set(self):
        # a completed trade must fall OUT of supersession eligibility.
        src = (_PKG / "services" / "workflow_orchestrator.py").read_text(encoding="utf-8")
        assert '.in_("status", ["pending", "queued", "staged"])' in src
        # guard against 'executed' creeping into the supersession set literal
        assert '"executed"' not in (
            '["pending", "queued", "staged"]'
        )

    def test_promotable_excludes_terminal_states(self):
        assert "executed" not in ss._PROMOTABLE
        assert "dismissed" not in ss._PROMOTABLE
        assert set(ss._PROMOTABLE) == {"pending", "staged", "queued"}
