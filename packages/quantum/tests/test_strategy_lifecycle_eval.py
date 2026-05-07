"""Tests for #109 PR-2 — evaluate_strategy_lifecycle + daily_progression_eval hook.

Behavioral tests on the lifecycle evaluation function plus a
structural check that the daily_progression_eval handler hook is
present.

The migration itself is plain SQL; verification of seed shape lives
in the migration's DO $$ ... $$ block (raises on apply if invariant
violated). No need to re-test that in Python.
"""

import unittest
from unittest.mock import MagicMock, patch

from packages.quantum.services.progression_service import (
    evaluate_strategy_lifecycle,
    _get_default_strategy_owner_user_id,
)


def _make_lifecycle_supabase(experimental_rows, eligibility_map):
    """Build a Supabase mock with controlled lifecycle reads + writes.

    Args:
        experimental_rows: list of dicts shaped like
            ``{"strategy_name": str, "current_state": "experimental"}``
            returned by the lifecycle SELECT.
        eligibility_map: dict mapping strategy_name -> dict with shape
            ``{"eligible": bool, "cumulative_pl": float,
              "trade_count": int, "min_required_trades": int}``.

    Captures all writes via the returned ``writes`` dict so tests
    can assert update + alert calls without re-mocking each one.
    """
    writes = {
        "lifecycle_updates": [],
        "alerts": [],
    }

    def _select_chain(rows):
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=list(rows))
        for m in ("select", "eq", "neq", "gte", "lte", "lt", "gt",
                  "in_", "order", "limit", "single"):
            getattr(chain, m).return_value = chain
        return chain

    def _update_chain(table_name):
        chain = MagicMock()
        update_payload = {}

        def _update(payload):
            update_payload.update(payload)
            return chain

        def _eq(col, val):
            update_payload[f"_filter_{col}"] = val
            return chain

        def _execute():
            writes["lifecycle_updates"].append(dict(update_payload))
            update_payload.clear()
            return MagicMock(data=[])

        chain.update.side_effect = _update
        chain.eq.side_effect = _eq
        chain.execute.side_effect = _execute
        for m in ("select", "neq", "gte", "lte", "lt", "gt",
                  "in_", "order", "limit", "single"):
            getattr(chain, m).return_value = chain
        return chain

    def _insert_chain(table_name):
        chain = MagicMock()

        def _insert(payload):
            writes["alerts"].append(dict(payload))
            return chain

        chain.insert.side_effect = _insert
        chain.execute.return_value = MagicMock(data=[])
        for m in ("select", "eq", "neq", "gte", "lte", "lt", "gt",
                  "in_", "order", "limit", "single"):
            getattr(chain, m).return_value = chain
        return chain

    select_call_count = [0]

    def table_side_effect(name):
        if name == "strategy_lifecycle_states":
            select_call_count[0] += 1
            # First call is SELECT (read EXPERIMENTAL); subsequent calls
            # are UPDATE (promote to live_full).
            if select_call_count[0] == 1:
                return _select_chain(experimental_rows)
            return _update_chain(name)
        if name == "risk_alerts":
            return _insert_chain(name)
        # Other tables (paper_positions / paper_orders) used by
        # get_strategy_eligibility — patched separately at test time.
        return _select_chain([])

    sb = MagicMock()
    sb.table.side_effect = table_side_effect
    return sb, writes


def _eligibility_stub(eligibility_map):
    """Patch get_strategy_eligibility to return canned results
    keyed by strategy_name."""
    def _stub(strategy_name, user_id, supabase):
        return eligibility_map.get(strategy_name, {
            "eligible": False,
            "cumulative_pl": 0.0,
            "trade_count": 0,
            "min_required_trades": 3,
        })
    return _stub


class TestEvaluateStrategyLifecycle(unittest.TestCase):

    def test_no_experimental_strategies_returns_empty(self):
        sb, writes = _make_lifecycle_supabase([], {})
        result = evaluate_strategy_lifecycle(sb)
        self.assertEqual(result, [])
        self.assertEqual(writes["lifecycle_updates"], [])
        self.assertEqual(writes["alerts"], [])

    def test_ineligible_experimental_does_not_transition(self):
        rows = [{"strategy_name": "BULL_PUT_SPREAD_0DTE", "current_state": "experimental"}]
        eligibility = {
            "BULL_PUT_SPREAD_0DTE": {
                "eligible": False,
                "cumulative_pl": 50.0,
                "trade_count": 2,
                "min_required_trades": 3,
            },
        }
        sb, writes = _make_lifecycle_supabase(rows, eligibility)
        with patch(
            "packages.quantum.services.progression_service.get_strategy_eligibility",
            side_effect=_eligibility_stub(eligibility),
        ):
            result = evaluate_strategy_lifecycle(sb)
        self.assertEqual(result, [])
        self.assertEqual(writes["lifecycle_updates"], [])
        # No graduation alert — only failure-path alerts would land here
        self.assertEqual(writes["alerts"], [])

    def test_eligible_experimental_graduates_with_audit(self):
        rows = [{"strategy_name": "IRON_CONDOR_VARIANT", "current_state": "experimental"}]
        eligibility = {
            "IRON_CONDOR_VARIANT": {
                "eligible": True,
                "cumulative_pl": 150.0,
                "trade_count": 4,
                "min_required_trades": 3,
            },
        }
        sb, writes = _make_lifecycle_supabase(rows, eligibility)
        with patch(
            "packages.quantum.services.progression_service.get_strategy_eligibility",
            side_effect=_eligibility_stub(eligibility),
        ):
            result = evaluate_strategy_lifecycle(sb)

        self.assertEqual(len(result), 1)
        t = result[0]
        self.assertEqual(t["strategy_name"], "IRON_CONDOR_VARIANT")
        self.assertEqual(t["previous_state"], "experimental")
        self.assertEqual(t["new_state"], "live_full")
        self.assertEqual(t["cumulative_realized_pl"], 150.0)
        self.assertEqual(t["trade_count"], 4)

        # Lifecycle UPDATE captured
        self.assertEqual(len(writes["lifecycle_updates"]), 1)
        upd = writes["lifecycle_updates"][0]
        self.assertEqual(upd["current_state"], "live_full")
        self.assertEqual(upd["closed_trade_count"], 4)
        self.assertEqual(upd["cumulative_realized_pl"], 150.0)
        self.assertEqual(upd["_filter_strategy_name"], "IRON_CONDOR_VARIANT")

        # Audit alert captured
        self.assertEqual(len(writes["alerts"]), 1)
        a = writes["alerts"][0]
        self.assertEqual(a["alert_type"], "strategy_graduated_to_full")
        self.assertEqual(a["severity"], "info")
        self.assertIn("IRON_CONDOR_VARIANT", a["message"])
        self.assertEqual(a["metadata"]["strategy_name"], "IRON_CONDOR_VARIANT")

    def test_mixed_eligibility_only_graduates_eligible(self):
        rows = [
            {"strategy_name": "STRAT_A", "current_state": "experimental"},
            {"strategy_name": "STRAT_B", "current_state": "experimental"},
            {"strategy_name": "STRAT_C", "current_state": "experimental"},
        ]
        eligibility = {
            "STRAT_A": {
                "eligible": True, "cumulative_pl": 100.0,
                "trade_count": 3, "min_required_trades": 3,
            },
            "STRAT_B": {
                "eligible": False, "cumulative_pl": -50.0,
                "trade_count": 5, "min_required_trades": 3,
            },
            "STRAT_C": {
                "eligible": True, "cumulative_pl": 75.0,
                "trade_count": 4, "min_required_trades": 3,
            },
        }
        sb, writes = _make_lifecycle_supabase(rows, eligibility)
        with patch(
            "packages.quantum.services.progression_service.get_strategy_eligibility",
            side_effect=_eligibility_stub(eligibility),
        ):
            result = evaluate_strategy_lifecycle(sb)

        graduated = sorted(t["strategy_name"] for t in result)
        self.assertEqual(graduated, ["STRAT_A", "STRAT_C"])
        self.assertEqual(len(writes["lifecycle_updates"]), 2)
        self.assertEqual(len(writes["alerts"]), 2)

    def test_eligibility_exception_for_one_does_not_block_others(self):
        rows = [
            {"strategy_name": "GOOD_STRAT", "current_state": "experimental"},
            {"strategy_name": "BROKEN_STRAT", "current_state": "experimental"},
        ]
        eligibility = {
            "GOOD_STRAT": {
                "eligible": True, "cumulative_pl": 100.0,
                "trade_count": 3, "min_required_trades": 3,
            },
        }
        sb, writes = _make_lifecycle_supabase(rows, eligibility)

        def _flaky_stub(strategy_name, user_id, supabase):
            if strategy_name == "BROKEN_STRAT":
                raise RuntimeError("simulated DB failure")
            return _eligibility_stub(eligibility)(strategy_name, user_id, supabase)

        with patch(
            "packages.quantum.services.progression_service.get_strategy_eligibility",
            side_effect=_flaky_stub,
        ):
            result = evaluate_strategy_lifecycle(sb)

        # GOOD_STRAT still graduates
        self.assertEqual([t["strategy_name"] for t in result], ["GOOD_STRAT"])
        # BROKEN_STRAT produced an error alert
        error_alerts = [
            a for a in writes["alerts"]
            if a.get("alert_type") == "strategy_lifecycle_eval_error"
        ]
        self.assertEqual(len(error_alerts), 1)
        self.assertEqual(
            error_alerts[0]["metadata"]["strategy_name"], "BROKEN_STRAT",
        )

    def test_idempotency_second_run_finds_nothing(self):
        """After all eligible EXPERIMENTAL strategies have transitioned
        to LIVE_FULL, a second invocation finds none and writes
        nothing. The natural design (filter on current_state) makes
        this implicit; the test locks it in.
        """
        sb, writes = _make_lifecycle_supabase([], {})
        result = evaluate_strategy_lifecycle(sb)
        self.assertEqual(result, [])
        self.assertEqual(writes["lifecycle_updates"], [])

    def test_read_failure_emits_alert_and_returns_empty(self):
        sb = MagicMock()

        # First .table call (lifecycle read) raises on .execute()
        chain = MagicMock()
        chain.execute.side_effect = RuntimeError("simulated read crash")
        for m in ("select", "eq", "neq", "gte", "lte", "lt", "gt",
                  "in_", "order", "limit", "single"):
            getattr(chain, m).return_value = chain

        # alerts table accepts the failure write
        alerts_writes = []
        alert_chain = MagicMock()

        def _alert_insert(payload):
            alerts_writes.append(dict(payload))
            return alert_chain

        alert_chain.insert.side_effect = _alert_insert
        alert_chain.execute.return_value = MagicMock(data=[])

        def table_side_effect(name):
            if name == "strategy_lifecycle_states":
                return chain
            if name == "risk_alerts":
                return alert_chain
            return chain

        sb.table.side_effect = table_side_effect

        result = evaluate_strategy_lifecycle(sb)
        self.assertEqual(result, [])
        # Exactly one error alert (read failure)
        self.assertEqual(len(alerts_writes), 1)
        self.assertEqual(
            alerts_writes[0]["alert_type"], "strategy_lifecycle_eval_error",
        )


class TestStrategyOwnerHelper(unittest.TestCase):
    def test_env_override(self):
        import os as _os
        prior = _os.environ.pop("STRATEGY_LIFECYCLE_OWNER_USER_ID", None)
        _os.environ["STRATEGY_LIFECYCLE_OWNER_USER_ID"] = "00000000-0000-0000-0000-deadbeef0000"
        try:
            self.assertEqual(
                _get_default_strategy_owner_user_id(),
                "00000000-0000-0000-0000-deadbeef0000",
            )
        finally:
            _os.environ.pop("STRATEGY_LIFECYCLE_OWNER_USER_ID", None)
            if prior is not None:
                _os.environ["STRATEGY_LIFECYCLE_OWNER_USER_ID"] = prior

    def test_default_falls_back_to_canonical_operator_uuid(self):
        import os as _os
        prior = _os.environ.pop("STRATEGY_LIFECYCLE_OWNER_USER_ID", None)
        try:
            self.assertEqual(
                _get_default_strategy_owner_user_id(),
                "75ee12ad-b119-4f32-aeea-19b4ef55d587",
            )
        finally:
            if prior is not None:
                _os.environ["STRATEGY_LIFECYCLE_OWNER_USER_ID"] = prior


# ─────────────────────────────────────────────────────────────────────
# Source-level structural guards
# ─────────────────────────────────────────────────────────────────────


class TestDailyProgressionEvalHook(unittest.TestCase):
    """daily_progression_eval must call evaluate_strategy_lifecycle
    AFTER the user loop completes, with failure isolation around it.
    """

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        cls.src = (
            Path(__file__).parent.parent / "jobs" / "handlers"
            / "daily_progression_eval.py"
        ).read_text(encoding="utf-8")

    def test_imports_evaluate_strategy_lifecycle(self):
        self.assertIn(
            "from packages.quantum.services.progression_service import",
            self.src,
        )
        self.assertIn("evaluate_strategy_lifecycle", self.src)

    def test_strategy_transitions_in_result_envelope(self):
        self.assertIn('"strategy_transitions"', self.src)

    def test_user_loop_completes_before_lifecycle_call(self):
        """Hook must come AFTER `run_async(process_users())` so the
        per-user work is committed first. Position by string offsets.
        """
        run_users_idx = self.src.find("run_async(process_users())")
        eval_call_idx = self.src.find("evaluate_strategy_lifecycle(")
        self.assertGreater(run_users_idx, 0)
        self.assertGreater(eval_call_idx, 0)
        self.assertGreater(eval_call_idx, run_users_idx)

    def test_failure_isolated_by_try_except(self):
        """Lifecycle eval must be wrapped in try/except so a crash
        doesn't lose the user-loop result envelope.
        """
        anchor = self.src.find("evaluate_strategy_lifecycle(")
        self.assertGreater(anchor, 0)
        # Walk backward up to ~400 chars — must find a `try:` opening
        # the surrounding block.
        window = self.src[max(0, anchor - 400):anchor + 500]
        self.assertIn("try:", window)
        self.assertIn("except Exception", window)


if __name__ == "__main__":
    unittest.main()
