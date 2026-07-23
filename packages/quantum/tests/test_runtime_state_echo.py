"""Tests for the operator-invoked RUNTIME_STATE_ECHO DB-state reader.

Coverage:
  1. DETERMINISM — same mocked client rows -> byte-identical state + render.
  2. FOUR-STATE HONESTY — HONEST-EMPTY (zero rows) is distinct from FAILED-FETCH
     (the read threw); a dependent read with no fleet id is NOT-FETCHED.
  3. FAIL-CLOSED — a missing/throwing table never renders a dark control as
     armed/active; single-leg -> epoch_read_failed, fleet -> not active, E19 ->
     unknown_fleet_read_failed; the reader never raises.
  4. ARMED only on a genuine 'enabled' epoch row.
  5. READ-ONLY — no insert/update/upsert/delete/rpc is ever called.
  6. SOURCE label — every surface is stamped source='DB_state'.
  7. NOT WIRED TO STARTUP — api.py / jobs/runner.py never import this reader.
"""
import os
import unittest
from pathlib import Path

from packages.quantum.observability import runtime_state_echo as rse
from packages.quantum.observability.runtime_state_echo import (
    collect_runtime_state,
    render_runtime_state_block,
    OK,
    HONEST_EMPTY,
    FAILED_FETCH,
    NOT_FETCHED,
)

_USER = "user-under-test"


# ── Minimal Supabase query-builder / client doubles ─────────────────────────
class _Resp:
    def __init__(self, data):
        self.data = data


class _Query:
    """Records read chaining; RAISES on any write method (read-only proof)."""

    def __init__(self, rows, recorder, table):
        self._rows = rows
        self._rec = recorder
        self._table = table

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        if self._rec is not None:
            self._rec.append(("execute", self._table))
        return _Resp(list(self._rows))

    def _write(self, name):
        raise AssertionError(f"read-only reader called a WRITE: {name}")

    def insert(self, *a, **k):
        self._write("insert")

    def update(self, *a, **k):
        self._write("update")

    def upsert(self, *a, **k):
        self._write("upsert")

    def delete(self, *a, **k):
        self._write("delete")


class _FailQuery:
    """Every read throws — simulates a missing table / relation-does-not-exist."""

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        raise RuntimeError('relation "x" does not exist')


class _Client:
    def __init__(self, tables, recorder=None):
        self._tables = tables
        self._rec = recorder

    def table(self, name):
        if self._rec is not None:
            self._rec.append(("table", name))
        return _Query(self._tables.get(name, []), self._rec, name)

    def rpc(self, *a, **k):
        raise AssertionError("read-only reader called rpc()")


class _FailClient:
    def table(self, name):
        return _FailQuery()

    def rpc(self, *a, **k):
        raise AssertionError("read-only reader called rpc()")


def _fleet_inactive_tables(fleet_status="pending_legacy_terminal"):
    return {
        "single_leg_experiment_epochs": [],  # HONEST-EMPTY -> epoch_absent
        "shadow_fleets": [{
            "id": "fleet-1", "epoch_name": "small_tier_v1",
            "status": fleet_status, "effective_at": None,
            "legacy_terminal_verified_at": None,
        }],
        "shadow_micro_accounts": [
            {"id": "s1", "slot_number": 1, "state": "inactive",
             "portfolio_id": "p1", "policy_registration_id": None},
            {"id": "s2", "slot_number": 2, "state": "inactive",
             "portfolio_id": "p2", "policy_registration_id": None},
            {"id": "s3", "slot_number": 3, "state": "inactive",
             "portfolio_id": "p3", "policy_registration_id": None},
        ],
        "policy_registrations": [
            {"policy_registration_id": "r1", "policy_family": "aggressive",
             "approval_status": "approved", "effective_epoch": "small_tier_v1"},
            {"policy_registration_id": "r2", "policy_family": "neutral",
             "approval_status": "approved", "effective_epoch": "small_tier_v1"},
            {"policy_registration_id": "r3", "policy_family": "conservative",
             "approval_status": "draft", "effective_epoch": "small_tier_v1"},
        ],
        "fleet_reconciliation_receipts": [],  # 0 receipts
    }


class TestDeterministicHappyPath(unittest.TestCase):
    def test_inactive_fleet_and_absent_epoch(self):
        client = _Client(_fleet_inactive_tables())
        state = collect_runtime_state(client, _USER)

        self.assertEqual(state["status"], "OK")
        self.assertEqual(state["failed_sections"], [])

        sl = state["single_leg"]
        self.assertEqual(sl["source"], "DB_state")
        self.assertEqual(sl["read_status"], HONEST_EMPTY)
        self.assertEqual(sl["epoch_state"], "epoch_absent")
        self.assertFalse(sl["armed"])

        fl = state["fleet"]
        self.assertEqual(fl["source"], "DB_state")
        self.assertEqual(fl["fleet_read_status"], OK)
        self.assertEqual(fl["fleet_status"], "pending_legacy_terminal")
        self.assertFalse(fl["active"])
        self.assertEqual(fl["slots_total"], 3)
        self.assertEqual(fl["slots_bound_to_policy"], 0)
        self.assertEqual(fl["slots_active"], 0)
        self.assertEqual(fl["policies_total"], 3)
        self.assertEqual(fl["policies_approved"], 2)
        self.assertEqual(fl["receipts_total"], 0)

        e19 = state["e19_execution"]
        self.assertEqual(e19["source"], "DB_state")
        self.assertEqual(e19["execution_state"], "blocked_pre_fleet_epoch")
        self.assertEqual(e19["runtime_rows"], 0)

    def test_render_is_deterministic_and_greppable(self):
        client = _Client(_fleet_inactive_tables())
        s1 = collect_runtime_state(client, _USER)
        s2 = collect_runtime_state(client, _USER)
        self.assertEqual(s1, s2)  # pure w.r.t. client
        block = render_runtime_state_block(s1)
        self.assertEqual(block, render_runtime_state_block(s2))
        self.assertIn("[RUNTIME_STATE_ECHO]", block)
        self.assertIn("source=DB_state", block)
        self.assertIn("blocked_pre_fleet_epoch", block)
        self.assertIn("single_leg", block)
        self.assertIn("fleet", block)
        self.assertIn("e19", block)

    def test_active_fleet_derives_no_executor_runtime(self):
        tables = _fleet_inactive_tables(fleet_status="active")
        tables["shadow_fleets"][0]["effective_at"] = "2026-07-20T00:00:00Z"
        state = collect_runtime_state(_Client(tables), _USER)
        self.assertTrue(state["fleet"]["active"])
        self.assertEqual(
            state["e19_execution"]["execution_state"],
            "fleet_active_no_executor_runtime",
        )


class TestArmedOnlyOnEnabledEpoch(unittest.TestCase):
    def test_enabled_epoch_reports_armed(self):
        tables = _fleet_inactive_tables()
        tables["single_leg_experiment_epochs"] = [{
            "epoch_name": "single_leg_experiment_v1", "state": "enabled",
            "routing_mode": "shadow_only", "max_contracts": 1,
            "live_submit_allowed": False, "version": 1,
        }]
        state = collect_runtime_state(_Client(tables), _USER)
        sl = state["single_leg"]
        self.assertEqual(sl["read_status"], OK)
        self.assertEqual(sl["epoch_state"], "enabled")
        self.assertTrue(sl["armed"])

    def test_disabled_epoch_row_not_armed(self):
        tables = _fleet_inactive_tables()
        tables["single_leg_experiment_epochs"] = [{
            "epoch_name": "single_leg_experiment_v1", "state": "disabled",
            "routing_mode": "shadow_only", "live_submit_allowed": False,
        }]
        state = collect_runtime_state(_Client(tables), _USER)
        self.assertEqual(state["single_leg"]["epoch_state"], "disabled")
        self.assertFalse(state["single_leg"]["armed"])


class TestFailClosed(unittest.TestCase):
    def test_all_reads_throw_never_raises_and_fails_closed(self):
        state = collect_runtime_state(_FailClient(), _USER)  # must not raise
        self.assertEqual(state["status"], "DEGRADED")
        # single-leg fail-closed (NOT armed, typed read-failed)
        self.assertEqual(state["single_leg"]["read_status"], FAILED_FETCH)
        self.assertEqual(state["single_leg"]["epoch_state"], "epoch_read_failed")
        self.assertFalse(state["single_leg"]["armed"])
        # fleet fail-closed (NOT active)
        self.assertEqual(state["fleet"]["fleet_read_status"], FAILED_FETCH)
        self.assertFalse(state["fleet"]["active"])
        # dependent bindings read could not be attempted -> NOT-FETCHED
        self.assertEqual(state["fleet"]["bindings_read_status"], NOT_FETCHED)
        # E19 unknown, never active
        self.assertEqual(
            state["e19_execution"]["execution_state"], "unknown_fleet_read_failed")
        # failed_sections lists the throwing reads (bindings is NOT-FETCHED, not failed)
        self.assertIn("single_leg_epoch", state["failed_sections"])
        self.assertIn("fleet", state["failed_sections"])
        self.assertNotIn("bindings", state["failed_sections"])

    def test_render_survives_degraded_state(self):
        block = render_runtime_state_block(collect_runtime_state(_FailClient(), _USER))
        self.assertIn("unknown_fleet_read_failed", block)
        self.assertIn("status=DEGRADED", block)


class TestReadOnly(unittest.TestCase):
    def test_only_read_methods_are_called(self):
        recorder = []
        client = _Client(_fleet_inactive_tables(), recorder=recorder)
        collect_runtime_state(client, _USER)  # any write method would AssertionError
        # every recorded interaction is a table() open or an execute()
        for kind, _table in recorder:
            self.assertIn(kind, ("table", "execute"))
        # all five expected tables were read
        read_tables = {t for k, t in recorder if k == "table"}
        self.assertEqual(
            read_tables,
            {
                "single_leg_experiment_epochs",
                "shadow_fleets",
                "shadow_micro_accounts",
                "policy_registrations",
                "fleet_reconciliation_receipts",
            },
        )


class TestNotWiredToStartup(unittest.TestCase):
    def test_startup_import_hooks_do_not_reference_reader(self):
        """A DB read must never sit on a process start path: the two startup
        import hooks (api.py, jobs/runner.py) must not reference this module."""
        pkg_root = Path(rse.__file__).resolve().parents[1]  # packages/quantum
        for rel in ("api.py", "jobs/runner.py"):
            text = (pkg_root / rel).read_text(encoding="utf-8", errors="ignore")
            self.assertNotIn("runtime_state_echo", text,
                             f"{rel} must not import the DB-state reader at startup")


if __name__ == "__main__":
    unittest.main()
