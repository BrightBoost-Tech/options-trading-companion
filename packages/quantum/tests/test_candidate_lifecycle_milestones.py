"""A3-LIFECYCLE (v1.6) — candidate executor-phase lifecycle milestones.

The three later-lifecycle disposition VALUES (staged → broker_submitted →
filled) were DEFINED BUT UNWIRED: the disposition lifecycle stopped at the
persist seam. These tests cover the wiring that advances the SINGLE is_final
row a candidate already holds, monotonically and idempotently, keyed on the
stable suggestion_id — WITHOUT a migration (the values are already in the
CHECK) and WITHOUT erasing prior disposition history (an append-only
detail['lifecycle'] timeline).

Three lanes, each driving the REAL route per CLAUDE.md §9 (execute the
production route, inject the failure at the deepest callee, assert the
top-level outcome — no source-string pins):
  1. UNIT — advance_candidate_milestone: monotonic, idempotent,
     blocked-guard, orphan/table-missing typed no-ops, write-failure
     visibility, history preservation.
  2. EXECUTOR ROUTE — drive PaperAutopilotService._execute_per_cohort (the
     model is test_e7_viability_rewire_executor_route.py) and assert the
     candidate advances staged → broker_submitted (live) / filled (internal);
     a CTD-update failure injected at the deepest callee leaves the trade job
     green and surfaces the counted write failure.
  3. POLL ROUTE — drive alpaca_order_handler.poll_pending_orders and assert a
     LIVE entry fill advances the candidate to `filled`; a blocked candidate
     never advances.
"""

import types
import unittest
import uuid
from datetime import datetime, timezone
from unittest import mock

from packages.quantum.services.candidate_disposition import (
    MILESTONES,
    TABLE,
    advance_candidate_milestone,
)
from packages.quantum.tests.test_prerejection_fork_e19 import FakeSupabase

UID = "user-1"
_TODAY = datetime.now(timezone.utc).date().isoformat()
SID = "1e8a0f9c-0000-4000-8000-00000000aaaa"


def _ctd_row(disposition="persisted_executable", *, suggestion_id=SID,
             detail=None, is_final=True):
    return {
        "id": str(uuid.uuid4()),
        "cycle_id": str(uuid.uuid4()),
        "cycle_date": _TODAY,
        "user_id": UID,
        "window": "midday_entry",
        "symbol": "SOFI",
        "strategy": "LONG_CALL_DEBIT_SPREAD",
        "candidate_fingerprint": "fp-sofi",
        "attempt": 1,
        "is_primary": True,
        "selected": True,
        "disposition": disposition,
        "is_final": is_final,
        "suggestion_id": suggestion_id,
        "detail": detail,
    }


def _seed_ctd(client, *rows):
    client.tables[TABLE] = [dict(r) for r in rows]


def _row(client):
    return client.tables[TABLE][0]


# ─────────────────────────────────────────────────────────────────────────
# Table-absent fake (the designed pre-migration state)
# ─────────────────────────────────────────────────────────────────────────
class _RaiseMissing:
    def select(self, *a, **k):
        return self

    def update(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        raise RuntimeError(
            "{'code': 'PGRST205', 'message': \"Could not find the table "
            "'public.candidate_terminal_dispositions' in the schema cache\"}"
        )


class SchemaAbsentFake(FakeSupabase):
    def table(self, name):
        if name == TABLE:
            return _RaiseMissing()
        return super().table(name)


# ═════════════════════════════════════════════════════════════════════════
# 1. UNIT — advance_candidate_milestone
# ═════════════════════════════════════════════════════════════════════════
class TestAdvanceMilestoneUnit(unittest.TestCase):
    def test_milestones_are_the_three_executor_values(self):
        self.assertEqual(MILESTONES, ("staged", "broker_submitted", "filled"))

    def test_staged_advances_from_persisted_executable(self):
        client = FakeSupabase()
        _seed_ctd(client, _ctd_row("persisted_executable"))
        ctr = {}
        res = advance_candidate_milestone(
            client, SID, "staged",
            ids={"order_id": "ord-1"}, extra={"cohort": "aggressive"},
            counters=ctr)
        self.assertEqual(res["status"], "advanced")
        self.assertEqual(res["from"], "persisted_executable")
        row = _row(client)
        self.assertEqual(row["disposition"], "staged")
        life = row["detail"]["lifecycle"]["staged"]
        self.assertEqual(life["from"], "persisted_executable")
        self.assertEqual(life["order_id"], "ord-1")
        self.assertEqual(life["cohort"], "aggressive")
        self.assertIn("at", life)
        self.assertEqual(ctr["milestone_advanced"], 1)

    def test_full_forward_chain_monotonic(self):
        client = FakeSupabase()
        _seed_ctd(client, _ctd_row("persisted_executable"))
        advance_candidate_milestone(client, SID, "staged",
                                    ids={"order_id": "ord-1"})
        advance_candidate_milestone(client, SID, "broker_submitted",
                                    ids={"client_order_id": "coid-1"})
        res = advance_candidate_milestone(client, SID, "filled",
                                          ids={"alpaca_order_id": "alp-1"})
        self.assertEqual(res["status"], "advanced")
        row = _row(client)
        self.assertEqual(row["disposition"], "filled")
        life = row["detail"]["lifecycle"]
        # the FULL timeline is preserved — nothing is erased as it advances
        self.assertEqual(set(life), {"staged", "broker_submitted", "filled"})
        self.assertEqual(life["broker_submitted"]["from"], "staged")
        self.assertEqual(life["filled"]["from"], "broker_submitted")

    def test_skipping_intermediate_states_is_allowed_forward(self):
        # a live fill observed with no separate staged/submitted stamp
        client = FakeSupabase()
        _seed_ctd(client, _ctd_row("persisted_executable"))
        res = advance_candidate_milestone(client, SID, "filled")
        self.assertEqual(res["status"], "advanced")
        self.assertEqual(_row(client)["disposition"], "filled")

    def test_idempotent_re_advance_is_noop(self):
        client = FakeSupabase()
        _seed_ctd(client, _ctd_row("staged"))
        ctr = {}
        res = advance_candidate_milestone(client, SID, "staged", counters=ctr)
        self.assertEqual(res["status"], "already_at_or_past")
        self.assertEqual(_row(client)["disposition"], "staged")  # unchanged
        self.assertEqual(ctr["milestone_already_at_or_past"], 1)
        self.assertNotIn("milestone_advanced", ctr)

    def test_never_regresses_past_state(self):
        client = FakeSupabase()
        _seed_ctd(client, _ctd_row("filled"))
        for earlier in ("staged", "broker_submitted"):
            res = advance_candidate_milestone(client, SID, earlier)
            self.assertEqual(res["status"], "already_at_or_past")
            self.assertEqual(_row(client)["disposition"], "filled")

    def test_blocked_and_dead_terminals_never_advance(self):
        for dead in ("persisted_blocked", "rank_blocked", "h7_dropped",
                     "allocator_dropped", "scanner_rejected",
                     "superseded_retry", None):
            client = FakeSupabase()
            _seed_ctd(client, _ctd_row(dead))
            ctr = {}
            for ms in MILESTONES:
                res = advance_candidate_milestone(client, SID, ms, counters=ctr)
                self.assertEqual(res["status"], "not_advanceable",
                                 f"{dead} → {ms} must be un-advanceable")
            self.assertEqual(_row(client)["disposition"], dead)  # untouched
            self.assertEqual(ctr["milestone_not_advanceable"], len(MILESTONES))
            self.assertNotIn("milestone_advanced", ctr)

    def test_orphan_no_row_never_fabricates(self):
        client = FakeSupabase()
        client.tables[TABLE] = []  # no persisted_executable predecessor
        ctr = {}
        res = advance_candidate_milestone(client, SID, "staged", counters=ctr)
        self.assertEqual(res["status"], "orphan_no_row")
        self.assertEqual(client.tables[TABLE], [])  # nothing fabricated
        self.assertEqual(ctr["milestone_orphan_no_row"], 1)

    def test_table_missing_is_typed_noop(self):
        client = SchemaAbsentFake()
        ctr = {}
        res = advance_candidate_milestone(client, SID, "staged", counters=ctr)
        self.assertEqual(res["status"], "table_missing")
        self.assertEqual(ctr["milestone_table_missing_noops"], 1)
        self.assertNotIn("milestone_write_failures", ctr)

    def test_write_failure_is_counted_and_visible_never_raises(self):
        client = FakeSupabase()
        _seed_ctd(client, _ctd_row("persisted_executable"))
        client.raise_when(TABLE, "update")  # deepest callee: the durable write
        ctr = {}
        res = advance_candidate_milestone(client, SID, "staged", counters=ctr)
        self.assertEqual(res["status"], "write_failed")
        self.assertGreaterEqual(ctr["milestone_write_failures"], 1)
        # the read said persisted_executable; the failed write left it there
        self.assertEqual(_row(client)["disposition"], "persisted_executable")

    def test_history_preserved_across_advance(self):
        client = FakeSupabase()
        prior = {"status": "pending", "is_new": True,
                 "cost_reconciliation": {"broker": 0.0, "internal": "unavailable"}}
        _seed_ctd(client, _ctd_row("persisted_executable", detail=dict(prior)))
        advance_candidate_milestone(client, SID, "staged",
                                    ids={"order_id": "ord-1"})
        detail = _row(client)["detail"]
        # every prior key survives — the disposition column advances, the
        # detail timeline only grows
        self.assertEqual(detail["status"], "pending")
        self.assertEqual(detail["is_new"], True)
        self.assertEqual(detail["cost_reconciliation"],
                         prior["cost_reconciliation"])
        self.assertIn("staged", detail["lifecycle"])

    def test_invalid_milestone_refused(self):
        client = FakeSupabase()
        _seed_ctd(client, _ctd_row("persisted_executable"))
        ctr = {}
        res = advance_candidate_milestone(client, SID, "vaporized", counters=ctr)
        self.assertEqual(res["status"], "invalid_milestone")
        self.assertEqual(_row(client)["disposition"], "persisted_executable")
        self.assertEqual(ctr["milestone_invalid"], 1)

    def test_disabled_on_none_client_or_missing_id(self):
        self.assertEqual(
            advance_candidate_milestone(None, SID, "staged")["status"],
            "disabled")
        self.assertEqual(
            advance_candidate_milestone(FakeSupabase(), None, "staged")["status"],
            "disabled")


# ═════════════════════════════════════════════════════════════════════════
# 2. EXECUTOR ROUTE — _execute_per_cohort (model: test_e7_viability_rewire)
# ═════════════════════════════════════════════════════════════════════════
def _sugg():
    return {
        "id": SID, "user_id": UID, "ticker": "SOFI", "symbol": "SOFI",
        "cohort_name": "aggressive", "status": "pending", "cycle_date": _TODAY,
        "strategy": "LONG_CALL_DEBIT_SPREAD",
        "ev": 20.0, "risk_adjusted_ev": 20.0, "legs_fingerprint": "fp-sofi",
    }


def _paper_order(execution_mode, status):
    return {
        "id": "ord-x", "execution_mode": execution_mode, "status": status,
        "client_order_id": "coid-x", "alpaca_order_id": "alp-x",
        "suggestion_id": SID,
    }


def _run_executor(client, *, exec_mode, processed=0):
    from packages.quantum.services.paper_autopilot_service import (
        PaperAutopilotService,
    )
    from packages.quantum.brokers.execution_router import ExecutionMode

    svc = PaperAutopilotService.__new__(PaperAutopilotService)
    svc.client = client
    svc.get_open_positions = lambda uid: []
    svc.get_already_executed_suggestion_ids_today = lambda uid: set()
    svc._stamp_blocked_reason = lambda *a, **k: None
    svc._estimate_equity = lambda *a, **k: 2000.0

    configs = {"aggressive": types.SimpleNamespace(max_suggestions_per_day=5)}
    portfolios = {"aggressive": "port-agg"}

    with mock.patch("packages.quantum.services.reentry_cooldown.is_enabled",
                    return_value=False), \
         mock.patch("packages.quantum.risk.utilization_gate.is_enabled",
                    return_value=False), \
         mock.patch("packages.quantum.policy_lab.config.load_cohort_configs",
                    return_value=configs), \
         mock.patch("packages.quantum.policy_lab.fork._get_cohort_portfolios",
                    return_value=portfolios), \
         mock.patch("packages.quantum.paper_endpoints.get_analytics_service",
                    return_value=mock.MagicMock()), \
         mock.patch("packages.quantum.paper_endpoints._suggestion_to_ticket",
                    side_effect=lambda s: {"sid": s["id"]}), \
         mock.patch("packages.quantum.paper_endpoints._process_orders_for_user",
                    return_value={"processed": processed}), \
         mock.patch("packages.quantum.brokers.execution_router.get_execution_mode",
                    return_value=exec_mode), \
         mock.patch("packages.quantum.paper_endpoints._stage_order_internal",
                    side_effect=lambda *a, **k: "ord-x"):
        return svc._execute_per_cohort(UID)


class TestExecutorRouteMilestones(unittest.TestCase):
    def _client(self, order):
        from packages.quantum.brokers.execution_router import ExecutionMode  # noqa
        client = FakeSupabase()
        client.tables["trade_suggestions"] = [_sugg()]
        client.tables[TABLE] = [_ctd_row("persisted_executable")]
        client.tables["paper_orders"] = [order]
        return client

    def test_live_order_advances_to_broker_submitted(self):
        from packages.quantum.brokers.execution_router import ExecutionMode
        client = self._client(_paper_order("alpaca_live", "submitted"))
        result = _run_executor(client, exec_mode=ExecutionMode.ALPACA_LIVE)
        row = _row(client)
        self.assertEqual(row["disposition"], "broker_submitted")
        life = row["detail"]["lifecycle"]
        self.assertEqual(set(life), {"staged", "broker_submitted"})
        self.assertEqual(life["staged"]["order_id"], "ord-x")
        self.assertEqual(life["broker_submitted"]["client_order_id"], "coid-x")
        self.assertEqual(life["broker_submitted"]["alpaca_order_id"], "alp-x")
        self.assertEqual(result["candidate_milestones"]["milestone_advanced"], 2)

    def test_internal_synchronous_fill_advances_to_filled(self):
        from packages.quantum.brokers.execution_router import ExecutionMode
        client = self._client(_paper_order("internal_paper", "filled"))
        result = _run_executor(client, exec_mode=ExecutionMode.INTERNAL_PAPER,
                               processed=1)
        row = _row(client)
        self.assertEqual(row["disposition"], "filled")
        life = row["detail"]["lifecycle"]
        self.assertEqual(set(life), {"staged", "filled"})  # no broker hop
        self.assertEqual(life["filled"]["fill_source"], "executor_internal")
        self.assertEqual(life["filled"]["routing"], "internal_paper")

    def test_ctd_update_failure_leaves_trade_job_green_and_counts(self):
        """Deepest callee (the durable CTD write) fails: the executor must
        still complete the trade (observe-only), and the milestone failure is
        COUNTED + surfaced in the result — never silent, never a job flip."""
        from packages.quantum.brokers.execution_router import ExecutionMode
        client = self._client(_paper_order("alpaca_live", "submitted"))
        client.raise_when(TABLE, "update")
        result = _run_executor(client, exec_mode=ExecutionMode.ALPACA_LIVE)
        self.assertEqual(result["status"], "ok")          # trade job unaffected
        self.assertEqual(result["executed_count"], 1)
        self.assertGreaterEqual(
            result["candidate_milestones"]["milestone_write_failures"], 1)
        # the failed write left the row at its persisted disposition
        self.assertEqual(_row(client)["disposition"], "persisted_executable")

    def test_table_missing_does_not_disturb_executor(self):
        from packages.quantum.brokers.execution_router import ExecutionMode
        client = SchemaAbsentFake()
        client.tables["trade_suggestions"] = [_sugg()]
        client.tables["paper_orders"] = [_paper_order("alpaca_live", "submitted")]
        result = _run_executor(client, exec_mode=ExecutionMode.ALPACA_LIVE)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["executed_count"], 1)
        self.assertGreaterEqual(
            result["candidate_milestones"]["milestone_table_missing_noops"], 1)


# ═════════════════════════════════════════════════════════════════════════
# 3. POLL ROUTE — poll_pending_orders live entry fill
# ═════════════════════════════════════════════════════════════════════════
class _Resp:
    def __init__(self, data):
        self.data = data


class _PollQ:
    def __init__(self, client, table):
        self.c = client
        self.t = table
        self.op = None
        self.payload = None
        self.filters = []
        self.limit_n = None
        self._neg = False

    def select(self, *a, **k):
        self.op = self.op or "select"
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = payload
        return self

    def insert(self, payload):
        self.op = "insert"
        self.payload = payload
        return self

    def eq(self, col, val):
        self.filters.append(("eq", col, val, self._neg))
        self._neg = False
        return self

    def in_(self, col, vals):
        self.filters.append(("in", col, list(vals), self._neg))
        self._neg = False
        return self

    def is_(self, col, val):
        self.filters.append(("is", col, val, self._neg))
        self._neg = False
        return self

    def gt(self, col, val):
        self.filters.append(("gt", col, val, self._neg))
        self._neg = False
        return self

    @property
    def not_(self):
        self._neg = True
        return self

    def limit(self, n):
        self.limit_n = n
        return self

    def _match(self, row):
        for kind, col, val, neg in self.filters:
            v = row.get(col)
            if kind == "eq":
                ok = v == val
            elif kind == "in":
                ok = v in val
            elif kind == "is":
                ok = (v is None) if val == "null" else (v == val)
            elif kind == "gt":
                ok = v is not None and float(v) > float(val)
            else:
                ok = True
            if neg:
                ok = not ok
            if not ok:
                return False
        return True

    def execute(self):
        exc = self.c.raises.get((self.t, self.op))
        if exc is not None:
            raise exc
        rows = self.c.tables.setdefault(self.t, [])
        if self.op == "select":
            out = [r for r in rows if self._match(r)]
            if self.limit_n is not None:
                out = out[: self.limit_n]
            return _Resp([dict(r) for r in out])
        if self.op == "update":
            for r in rows:
                if self._match(r):
                    r.update(self.payload)
                    self.c.updates.append((self.t, dict(self.payload)))
            return _Resp([{}])
        if self.op == "insert":
            payload = self.payload if isinstance(self.payload, list) else [self.payload]
            for r in payload:
                rows.append(dict(r))
            return _Resp([{}])
        return _Resp([])


class _PollClient:
    def __init__(self):
        self.tables = {}
        self.updates = []
        self.raises = {}

    def table(self, name):
        return _PollQ(self, name)


def _entry_order():
    return {
        "id": "ord-1", "alpaca_order_id": "alp-1", "status": "working",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "broker_status": "new", "position_id": None, "side": "buy",
        "order_json": {"symbol": "SOFI", "legs": []}, "suggestion_id": SID,
        "portfolio_id": "port-1",
    }


def _drive_poll(client):
    from packages.quantum.brokers import alpaca_order_handler
    alpaca = mock.MagicMock()
    alpaca.get_order.return_value = {
        "status": "filled", "filled_qty": "1", "filled_avg_price": "0.50",
        "filled_at": "2026-07-19T16:00:00Z", "id": "alp-1",
    }
    with mock.patch(
        "packages.quantum.paper_endpoints._process_orders_for_user",
        return_value={"processed": 1}), \
         mock.patch(
            "packages.quantum.services.analytics_service.AnalyticsService",
            return_value=mock.MagicMock()), \
         mock.patch(
            "packages.quantum.services.gtc_profit_exit."
            "maybe_place_gtc_profit_exit", return_value=None):
        return alpaca_order_handler.poll_pending_orders(alpaca, client, UID)


class TestPollRouteFilledMilestone(unittest.TestCase):
    def _client(self, ctd_disposition):
        client = _PollClient()
        client.tables["paper_portfolios"] = [{"id": "port-1", "user_id": UID}]
        client.tables["paper_orders"] = [_entry_order()]
        client.tables[TABLE] = [_ctd_row(ctd_disposition)]
        return client

    def test_live_entry_fill_advances_to_filled(self):
        client = self._client("persisted_executable")
        result = _drive_poll(client)
        self.assertEqual(result["fills"], 1)
        row = client.tables[TABLE][0]
        self.assertEqual(row["disposition"], "filled")
        life = row["detail"]["lifecycle"]["filled"]
        self.assertEqual(life["fill_source"], "broker_poll")
        self.assertEqual(life["order_id"], "ord-1")
        self.assertEqual(life["alpaca_order_id"], "alp-1")
        self.assertEqual(life["from"], "persisted_executable")

    def test_already_staged_fill_advances_forward_not_regressed(self):
        client = self._client("staged")
        _drive_poll(client)
        self.assertEqual(client.tables[TABLE][0]["disposition"], "filled")

    def test_blocked_candidate_fill_never_advances(self):
        # a persisted_blocked candidate should never reach the executor, but
        # defense in depth: even a broker fill can't advance a dead terminal
        client = self._client("persisted_blocked")
        _drive_poll(client)
        row = client.tables[TABLE][0]
        self.assertEqual(row["disposition"], "persisted_blocked")

    def test_orphan_fill_fabricates_nothing(self):
        client = self._client("persisted_executable")
        client.tables[TABLE] = []  # no disposition row for this suggestion
        _drive_poll(client)
        self.assertEqual(client.tables[TABLE], [])


if __name__ == "__main__":
    unittest.main()
