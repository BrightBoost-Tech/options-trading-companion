"""Lane B — research-observer failures must NOT mark the live parent PARTIAL.

Contract (doctrine §10 + Lane B spec): the terminal-distribution
(``td_scan_score_observe``) and shadow-fleet (``shadow_fleet_evaluate``) ENQUEUE
seams are OBSERVE-ONLY research children on the tail of the live
``suggestions_open`` scan. A readiness/enqueue failure in either seam:
  - stays durable in parent metadata (per-user enqueue dict + top-level
    ``result.research_observers``),
  - increments ``counts.research_observer_failures`` (a channel the runner's
    partial classifier NEVER reads),
  - emits a dedicated typed ``research_observer_enqueue_failed`` alert,
  - does NOT touch ``counts.errors`` / processed / failed / ok / status,
so an otherwise-clean LIVE scan stays ``succeeded`` and the A4 silent-failure
detector (``job_succeeded_with_errors``, reads ``counts.errors``) is NOT tripped.

Every parent test DRIVES THE REAL ``suggestions_open.run`` handler end-to-end
and injects the failure at the DEEPEST callee (the real enqueue fn raises / the
real ``shadow_fleets`` DB read raises), then asserts the TOP-LEVEL job outcome —
including the REAL runner classifier ``_classify_handler_return``.

Single-leg is deliberately UNTOUCHED (its enqueue errors still count) — a
separate contract per the Lane B spec default.
"""

from __future__ import annotations

import os
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from packages.quantum.jobs.handlers import suggestions_open
from packages.quantum.jobs.runner import _classify_handler_return
from packages.quantum.services import research_observer_status as ros

_UID = "75ee12ad-b119-4f32-aeea-19b4ef55d587"
_TD_FLAG = "TERMINAL_DISTRIBUTION_SCAN_OBSERVE_ENABLED"


# ── A configurable, side-effect-recording fake supabase client ───────────────
class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    _DB_VERBS = {
        "select", "insert", "upsert", "update", "delete",
        "eq", "neq", "in_", "is_", "filter", "order", "limit",
        "gte", "lte", "gt", "lt", "or_", "single", "maybe_single", "range",
    }

    def __init__(self, table, rules, calls):
        self._table = table
        self._rules = rules
        self._calls = calls
        self._op = None

    def __getattr__(self, name):
        if name in self._DB_VERBS:
            def _builder(*a, **k):
                if name in ("select", "insert", "upsert", "update", "delete"):
                    self._op = name
                self._calls.append((self._table, name))
                return self
            return _builder
        raise AttributeError(
            f"FakeQuery has no attribute {name!r} — a non-DB (broker/provider) "
            f"call leaked into the observer path"
        )

    def execute(self):
        rule = self._rules.get(self._table, [])
        if isinstance(rule, Exception):
            raise rule
        if callable(rule):
            rule = rule(self._op)
        return _FakeResult(list(rule) if rule is not None else [])


class _FakeClient:
    """Sole external-I/O object in scope. Exposes ONLY ``table()`` + DB verbs —
    any broker/provider call would AttributeError, structurally proving 'no
    broker/provider call added' in the observer path."""

    def __init__(self, rules=None):
        self.rules = dict(rules or {})
        self.calls = []  # (table, verb) log

    def table(self, name):
        self.calls.append(("table", name))
        return _FakeQuery(name, self.rules, self.calls)

    def tables_touched(self):
        return {t for (kind, t) in self.calls if kind == "table"}


# ── A minimal complete-decision-tape context (so td reaches its enqueue) ──────
class _FakeCtx:
    def __init__(self, **kwargs):
        self.decision_id = "dec-123"
        self.git_sha = "shaTEST"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def commit(self, client=None, status=None, error_summary=None):
        # A COMPLETE, durably-committed tape (the only tape td/fleet may ride).
        return {"decision_id": self.decision_id, "tape_integrity": "complete"}


async def _healthy_cycle(client, uid, *args, **kwargs):
    return {"skipped": False, "reason": "ok", "counts": {}}


async def _dying_cycle(client, uid, *args, **kwargs):
    raise RuntimeError("run_midday_cycle exploded (simulated live failure)")


class _ObserverIsolationBase(unittest.TestCase):
    def setUp(self):
        self._saved_flag = os.environ.get(_TD_FLAG)

    def tearDown(self):
        if self._saved_flag is None:
            os.environ.pop(_TD_FLAG, None)
        else:
            os.environ[_TD_FLAG] = self._saved_flag

    def _run(self, *, client, cycle=_healthy_cycle, alert_mock=None,
             enqueue_side_effect=None, with_tape=False, payload=None):
        alert_mock = alert_mock or MagicMock()
        # single-leg is deliberately kept a no-op here (its own contract).
        singleleg_noop = MagicMock(
            return_value={"status": "disabled", "enqueued": False, "errors": 0}
        )
        # Stub the enqueue TRANSPORT (the deepest observer callee) via a fake
        # ``public_tasks`` module in sys.modules, so the REAL td seam runs its
        # real ``from packages.quantum.public_tasks import enqueue_job_run`` but
        # the rq-laden real module (Windows-fork-incompatible) is never imported.
        enqueue_mock = MagicMock(
            return_value={"status": "queued", "job_run_id": "jr", "rq_job_id": "rq"}
        )
        if enqueue_side_effect is not None:
            enqueue_mock.side_effect = enqueue_side_effect
        fake_public_tasks = types.ModuleType("packages.quantum.public_tasks")
        fake_public_tasks.enqueue_job_run = enqueue_mock

        patches = [
            patch.dict(sys.modules,
                       {"packages.quantum.public_tasks": fake_public_tasks}),
            patch.object(suggestions_open, "is_market_day",
                         return_value=(True, "open")),
            patch.object(suggestions_open, "get_admin_client", return_value=client),
            patch.object(suggestions_open, "ensure_default_strategy_exists"),
            patch.object(suggestions_open, "load_strategy_config",
                         return_value={"version": 1}),
            patch.object(suggestions_open, "run_midday_cycle", cycle),
            patch("packages.quantum.observability.alerts.alert", alert_mock),
            patch("packages.quantum.risk.staleness_gate.check_staleness_gate",
                  return_value=SimpleNamespace(blocked=False, reason="",
                                               age_seconds=0.0, stale_symbols=[])),
            patch("packages.quantum.policy_lab.config.is_policy_lab_enabled",
                  return_value=False),
            patch("packages.quantum.services.single_leg_shadow_scan."
                  "maybe_enqueue_single_leg_shadow_scan", singleleg_noop),
        ]
        if with_tape:
            patches.append(
                patch.object(suggestions_open, "_get_decision_context_class",
                             return_value=_FakeCtx)
            )
        for p in patches:
            p.start()
        try:
            return suggestions_open.run(
                payload or {"user_id": _UID, "origin": {"origin": "scheduler"},
                            "_job_run_id": "parent-job-1"}
            )
        finally:
            for p in patches:
                p.stop()

    def _research_alerts(self, alert_mock):
        return [
            c for c in alert_mock.call_args_list
            if c.kwargs.get("alert_type") == ros.RESEARCH_OBSERVER_ALERT_TYPE
        ]

    def _cycle_death_alerts(self, alert_mock):
        return [
            c for c in alert_mock.call_args_list
            if c.kwargs.get("alert_type") == "suggestions_open_cycle_died"
        ]


class TestTdEnqueueFailureIsolated(_ObserverIsolationBase):
    def test_td_enqueue_fails_parent_still_succeeded(self):
        os.environ[_TD_FLAG] = "1"  # td observe ON so it reaches its enqueue
        client = _FakeClient(rules={"shadow_fleets": [], "risk_alerts": []})
        alert_mock = MagicMock()
        result = self._run(
            client=client, alert_mock=alert_mock, with_tape=True,
            # Deepest callee: the real enqueue fn raises.
            enqueue_side_effect=RuntimeError("rq broker unreachable"),
        )

        # TOP-LEVEL live truth: parent succeeded, live counts untouched.
        self.assertTrue(result["ok"])
        self.assertEqual(result["counts"]["errors"], 0)
        self.assertEqual(result["counts"]["failed"], 0)
        self.assertEqual(result["counts"]["processed"], 1)
        # The REAL runner classifier agrees.
        self.assertEqual(_classify_handler_return(result), "succeeded")

        # Research failure is durable + counted in its OWN channel.
        self.assertEqual(result["counts"]["research_observer_failures"], 1)
        td = result["research_observers"][ros.OBSERVER_TERMINAL_DISTRIBUTION]
        self.assertEqual(td["errors"], 1)
        self.assertEqual(td["status"], "enqueue_failed")
        # Fleet was a clean no-op (fleet_absent).
        fleet = result["research_observers"][ros.OBSERVER_SHADOW_FLEET]
        self.assertEqual(fleet["errors"], 0)

        # A typed research alert fired; NO cycle-death alert; no A4 trip
        # (A4 reads counts.errors, asserted 0 above).
        self.assertEqual(len(self._research_alerts(alert_mock)), 1)
        self.assertEqual(self._cycle_death_alerts(alert_mock), [])

    def test_research_alert_metadata_is_typed_and_deduppable(self):
        os.environ[_TD_FLAG] = "1"
        client = _FakeClient(rules={"shadow_fleets": [], "risk_alerts": []})
        alert_mock = MagicMock()
        self._run(client=client, alert_mock=alert_mock, with_tape=True,
                  enqueue_side_effect=RuntimeError("rq down"))
        calls = self._research_alerts(alert_mock)
        self.assertEqual(len(calls), 1)
        meta = calls[0].kwargs["metadata"]
        self.assertEqual(meta["observer_name"], ros.OBSERVER_TERMINAL_DISTRIBUTION)
        self.assertEqual(meta["source_job_run_id"], "parent-job-1")
        self.assertEqual(meta["code_sha"], "shaTEST")
        self.assertEqual(meta["detector_version"],
                         ros.RESEARCH_OBSERVER_DETECTOR_VERSION)
        self.assertIn("failure_signature", meta)
        self.assertEqual(calls[0].kwargs["severity"], "warning")


class TestFleetReadinessFailureIsolated(_ObserverIsolationBase):
    def test_fleet_readiness_read_fails_parent_still_succeeded(self):
        # td flag OFF → td no-op; fleet readiness DB read raises at deepest callee.
        os.environ.pop(_TD_FLAG, None)
        boom = RuntimeError("shadow_fleets read: Server disconnected")
        client = _FakeClient(rules={"shadow_fleets": boom, "risk_alerts": []})
        alert_mock = MagicMock()
        result = self._run(client=client, alert_mock=alert_mock)

        self.assertTrue(result["ok"])
        self.assertEqual(result["counts"]["errors"], 0)
        self.assertEqual(_classify_handler_return(result), "succeeded")

        self.assertGreaterEqual(result["counts"]["research_observer_failures"], 1)
        fleet = result["research_observers"][ros.OBSERVER_SHADOW_FLEET]
        self.assertEqual(fleet["errors"], 1)
        self.assertEqual(fleet["status"], "fleet_read_failed")
        # td stayed a no-op (flag off).
        td = result["research_observers"][ros.OBSERVER_TERMINAL_DISTRIBUTION]
        self.assertEqual(td["errors"], 0)

        self.assertEqual(len(self._research_alerts(alert_mock)), 1)
        self.assertEqual(self._cycle_death_alerts(alert_mock), [])


class TestBothObserversFailIsolated(_ObserverIsolationBase):
    def test_both_observers_fail_two_typed_failures_parent_succeeded(self):
        os.environ[_TD_FLAG] = "1"
        boom = RuntimeError("shadow_fleets read failed")
        client = _FakeClient(rules={"shadow_fleets": boom, "risk_alerts": []})
        alert_mock = MagicMock()
        result = self._run(
            client=client, alert_mock=alert_mock, with_tape=True,
            enqueue_side_effect=RuntimeError("rq down"),  # td enqueue deepest callee
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["counts"]["errors"], 0)
        self.assertEqual(_classify_handler_return(result), "succeeded")

        # Two typed research failures, both durable.
        self.assertEqual(result["counts"]["research_observer_failures"], 2)
        self.assertEqual(
            result["research_observers"][ros.OBSERVER_TERMINAL_DISTRIBUTION]["errors"], 1)
        self.assertEqual(
            result["research_observers"][ros.OBSERVER_SHADOW_FLEET]["errors"], 1)

        ra = self._research_alerts(alert_mock)
        self.assertEqual(len(ra), 2)
        observers = {c.kwargs["metadata"]["observer_name"] for c in ra}
        self.assertEqual(
            observers,
            {ros.OBSERVER_TERMINAL_DISTRIBUTION, ros.OBSERVER_SHADOW_FLEET},
        )
        self.assertEqual(self._cycle_death_alerts(alert_mock), [])


class TestLiveScanFailureStillPartial(_ObserverIsolationBase):
    def test_live_cycle_death_is_still_partial(self):
        # The isolation change must NOT weaken live-failure detection: a real
        # midday-cycle death is still counts.failed>0 → counts.errors>0 → partial.
        os.environ.pop(_TD_FLAG, None)
        client = _FakeClient(rules={"shadow_fleets": [], "risk_alerts": []})
        alert_mock = MagicMock()
        result = self._run(client=client, cycle=_dying_cycle, alert_mock=alert_mock)

        self.assertFalse(result["ok"])
        self.assertEqual(result["counts"]["failed"], 1)
        self.assertGreaterEqual(result["counts"]["errors"], 1)
        self.assertEqual(_classify_handler_return(result), "partial")
        # The LIVE failure alert fired (not a research alert).
        self.assertEqual(len(self._cycle_death_alerts(alert_mock)), 1)
        self.assertEqual(self._research_alerts(alert_mock), [])


class TestDisabledObserversNoAlert(_ObserverIsolationBase):
    def test_observers_disabled_inactive_no_alert_no_failures(self):
        # td flag OFF (flag_disabled) + fleet absent (fleet_absent) = pure no-ops.
        os.environ.pop(_TD_FLAG, None)
        client = _FakeClient(rules={"shadow_fleets": [], "risk_alerts": []})
        alert_mock = MagicMock()
        result = self._run(client=client, alert_mock=alert_mock)

        self.assertTrue(result["ok"])
        self.assertEqual(result["counts"]["errors"], 0)
        self.assertEqual(result["counts"]["research_observer_failures"], 0)
        self.assertEqual(_classify_handler_return(result), "succeeded")
        # No alert of ANY kind.
        self.assertEqual(alert_mock.call_args_list, [])
        # The block is present and honest (both no-op, zero errors).
        for name in (ros.OBSERVER_TERMINAL_DISTRIBUTION, ros.OBSERVER_SHADOW_FLEET):
            self.assertEqual(result["research_observers"][name]["errors"], 0)


class TestNormalRunLiveTruthByteIdentical(_ObserverIsolationBase):
    def test_research_block_is_purely_additive_to_live_truth(self):
        """A clean run's LIVE counts are exactly the baseline; the new
        research_observers block + research_observer_failures are purely
        additive keys that carry zero and change no live field."""
        os.environ.pop(_TD_FLAG, None)
        client = _FakeClient(rules={"shadow_fleets": [], "risk_alerts": []})
        result = self._run(client=client)

        # LIVE-decision truth (unchanged by the observer isolation).
        self.assertEqual(result["counts"]["processed"], 1)
        self.assertEqual(result["counts"]["failed"], 0)
        self.assertEqual(result["counts"]["synced"], 0)
        self.assertEqual(result["counts"]["skipped"], 0)
        self.assertEqual(result["counts"]["errors"], 0)
        self.assertTrue(result["ok"])
        # Additive-only keys carry zero.
        self.assertEqual(result["counts"]["research_observer_failures"], 0)
        self.assertIn("research_observers", result)
        # The live cycle result is preserved untouched (aside from the additive
        # enqueue-observability keys the seams have always attached).
        cyc = result["cycle_results"][0]
        self.assertEqual(cyc["reason"], "ok")
        self.assertNotIn("errors", cyc.get("counts", {}))


class TestNoBrokerOrProviderCallAdded(_ObserverIsolationBase):
    def test_failing_observer_path_touches_only_db_tables(self):
        os.environ[_TD_FLAG] = "1"
        boom = RuntimeError("shadow_fleets read failed")
        client = _FakeClient(rules={"shadow_fleets": boom, "risk_alerts": []})
        alert_mock = MagicMock()
        self._run(client=client, alert_mock=alert_mock, with_tape=True,
                  enqueue_side_effect=RuntimeError("rq down"))
        # The sole I/O object only ever performed DB table ops (a broker/provider
        # method would have AttributeError'd out of _FakeQuery). Tables touched
        # are a subset of the observer-path DB allowlist — no orders/positions.
        allowed = {"shadow_fleets", "risk_alerts", "shadow_micro_accounts",
                   "policy_registrations"}
        self.assertTrue(
            client.tables_touched().issubset(allowed),
            f"unexpected table access: {client.tables_touched() - allowed}",
        )


class TestChildKeepsItsOwnTruth(_ObserverIsolationBase):
    def test_observer_child_partial_is_child_truth_only(self):
        """Once enqueued, the observer CHILD keeps its OWN honest partial/failed
        truth — independent of the parent that stayed succeeded. Drive the REAL
        child body (run_fleet_policy_eval) with a failure injected at its
        deepest per-policy callee (the open-positions read raises)."""
        from packages.quantum.services.shadow_fleet_evaluate import (
            run_fleet_policy_eval,
        )

        def _ready(*a, **k):
            return {
                "status": "ready", "ready": True, "errors": 0,
                "fleet_id": "fleet-1",
                "accounts": [{
                    "shadow_micro_account_id": "m1", "fleet_id": "fleet-1",
                    "slot_number": 1, "portfolio_id": "p1",
                    "policy_registration_id": "pol_1",
                    "policy_config": {
                        "max_risk_pct_per_trade": 0.035, "risk_multiplier": 1.2,
                        "budget_cap_pct": 0.35, "max_suggestions_per_day": 4,
                        "max_positions_open": 4, "min_score_threshold": 30,
                    },
                    "deployable_capital": 2000.0,
                }],
            }

        def _universe(client, decision_id, user_id):
            return [{"id": "cand-1",
                     "sizing_metadata": {"score": 80.0, "max_loss_total": 50.0},
                     "order_json": {"contracts": 1}, "ev": 25.0, "ev_raw": 25.0}]

        def _boom_open_positions(client, micro_id):
            raise RuntimeError("open-position read failed (child-internal)")

        child = run_fleet_policy_eval(
            {"user_id": _UID, "source_job_run_id": "parent-job-1",
             "source_decision_id": "dec-123", "source_code_sha": "shaTEST",
             "source_as_of": "2026-07-23T16:00:00+00:00",
             "fleet_epoch": "small_tier_v1"},
            client=object(),
            readiness_loader=_ready,
            universe_builder=_universe,
            writer_factory=_ChildFakeWriter,
            open_positions_loader=_boom_open_positions,
        )
        # The CHILD honestly reports its own partial/failed truth.
        self.assertFalse(child["ok"])
        self.assertEqual(child["status"], "partial")
        self.assertGreaterEqual(child["counts"]["errors"], 1)
        self.assertEqual(child["counts"]["evaluator_failed_runs"], 1)


class TestAlertRefireDedup(unittest.TestCase):
    """Reuses the #1332 mechanism: the append-only risk_alerts rows ARE the
    dedup store, keyed on (source_job_run_id, observer_name, failure_signature,
    code_sha). A byte-identical re-fire is suppressed; a materially-different
    failure (new signature) re-emits; a missing prior fails OPEN (emit)."""

    def _client_with_prior(self, prior_rows):
        return _FakeClient(rules={"risk_alerts": prior_rows})

    def _enq(self):
        return {"status": "enqueue_failed", "enqueued": False, "errors": 1,
                "error": "RuntimeError: rq down"}

    def _prior_row(self, *, signature, observer="terminal_distribution",
                   sha="shaTEST", job="parent-job-1"):
        return {"id": "prior-1", "created_at": "2026-07-23T16:00:00+00:00",
                "metadata": {"source_job_run_id": job, "observer_name": observer,
                             "failure_signature": signature,
                             "code_sha": sha,
                             "detector_version":
                                 ros.RESEARCH_OBSERVER_DETECTOR_VERSION}}

    def test_first_emit_then_identical_refire_suppressed(self):
        enq = self._enq()
        sig = ros.research_observer_failure_signature(
            ros.OBSERVER_TERMINAL_DISTRIBUTION, "enqueue_failed", "RuntimeError")
        # No prior → emit.
        client_empty = self._client_with_prior([])
        with patch("packages.quantum.observability.alerts.alert") as m1:
            r1 = ros.emit_research_observer_failure_alert(
                client_empty, observer_name=ros.OBSERVER_TERMINAL_DISTRIBUTION,
                enq_result=enq, source_job_run_id="parent-job-1", code_sha="shaTEST")
            self.assertTrue(r1["emitted"])
            m1.assert_called_once()
        # Identical prior present → suppressed (no alert() call).
        client_dup = self._client_with_prior([self._prior_row(signature=sig)])
        with patch("packages.quantum.observability.alerts.alert") as m2:
            r2 = ros.emit_research_observer_failure_alert(
                client_dup, observer_name=ros.OBSERVER_TERMINAL_DISTRIBUTION,
                enq_result=enq, source_job_run_id="parent-job-1", code_sha="shaTEST")
            self.assertFalse(r2["emitted"])
            self.assertEqual(r2["reason"], "duplicate")
            m2.assert_not_called()

    def test_different_signature_reemits(self):
        # A prior row for a DIFFERENT failure signature must not suppress.
        stale = self._prior_row(signature="terminal_distribution|status=other|error_class=X")
        client = self._client_with_prior([stale])
        with patch("packages.quantum.observability.alerts.alert") as m:
            r = ros.emit_research_observer_failure_alert(
                client, observer_name=ros.OBSERVER_TERMINAL_DISTRIBUTION,
                enq_result=self._enq(), source_job_run_id="parent-job-1",
                code_sha="shaTEST")
            self.assertTrue(r["emitted"])
            m.assert_called_once()

    def test_lookup_error_fails_open_and_emits(self):
        client = _FakeClient(rules={"risk_alerts": RuntimeError("PostgREST down")})
        with patch("packages.quantum.observability.alerts.alert") as m:
            r = ros.emit_research_observer_failure_alert(
                client, observer_name=ros.OBSERVER_SHADOW_FLEET,
                enq_result={"status": "fleet_read_failed", "errors": 1,
                            "error": "RuntimeError: boom"},
                source_job_run_id="parent-job-1", code_sha="shaTEST")
            self.assertTrue(r["emitted"])
            m.assert_called_once()

    def test_secret_is_redacted_before_truncation(self):
        enq = {"status": "enqueue_failed", "errors": 1,
               "error": "RuntimeError: db postgres://u:supersecretpw@h/db failed"}
        client = _FakeClient(rules={"risk_alerts": []})
        with patch("packages.quantum.observability.alerts.alert") as m:
            ros.emit_research_observer_failure_alert(
                client, observer_name=ros.OBSERVER_SHADOW_FLEET, enq_result=enq,
                source_job_run_id="parent-job-1", code_sha="shaTEST")
            meta = m.call_args.kwargs["metadata"]
            self.assertNotIn("supersecretpw", str(meta["error"]))
            self.assertIn("****", str(meta["error"]))


class _ChildFakeWriter:
    instances = []

    def __init__(self, *a, **k):
        _ChildFakeWriter.instances.append(self)
        self.finished = None
        self._c = {"runs_started": 1, "decisions_written": 0,
                   "write_failures": 0, "table_missing_noops": 0,
                   "duplicate_acks": 0}

    def begin_run(self):
        return "run-1"

    def record_decision(self, decision, **k):
        return True

    def finish_run(self, *, status, counts=None, error_details=None):
        self.finished = {"status": status}
        return True

    def counters_dict(self):
        return dict(self._c)


if __name__ == "__main__":
    unittest.main()
