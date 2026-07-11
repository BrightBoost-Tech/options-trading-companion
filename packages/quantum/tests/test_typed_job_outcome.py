"""F-A4-1 typed job-outcome contract (2026-07-11).

A handler's fatal must never be recorded 'succeeded'. The 3 swallow-fatal
monitors now RAISE; the runner derives a REAL 'partial' status from the return
(users_failed / counts.errors / a swallowed-fatal 'error' key); designed-false
handlers stay 'succeeded'. Behavioral tests on the production seam
(_classify_handler_return, which run_job_run calls) + wiring pins on the
consumers that must recognize 'partial'.
"""

from pathlib import Path

from packages.quantum.jobs.runner import _classify_handler_return

_Q = Path(__file__).parent.parent


class TestClassifyHandlerReturn:
    # --- designed-false MUST stay succeeded (T2) ---
    def test_ops_health_check_issues_is_success(self):
        # health check ran; issues_found is payload, not a failure
        assert _classify_handler_return(
            {"ok": True, "healthy": False, "issues_found": ["x", "y"]}) == "succeeded"

    def test_executor_gate_rejects_is_success(self):
        # paper_auto_execute all-rejected: ok:False + status:partial, NO
        # users_failed / counts.errors / top-level error → designed, succeeded
        assert _classify_handler_return(
            {"ok": False, "status": "partial", "errors": [{"e": "ev_below"}]}) == "succeeded"

    def test_policy_lab_no_active_users_is_success(self):
        assert _classify_handler_return({"status": "error", "reason": "no active users"}) == "succeeded"

    def test_clean_success(self):
        assert _classify_handler_return({"ok": True, "status": "completed"}) == "succeeded"

    def test_non_dict_is_success(self):
        assert _classify_handler_return("done") == "succeeded"

    # --- failure-shaped returns MUST be partial (T1 + T3) ---
    def test_swallowed_fatal_error_key_is_partial(self):
        # the q15 fatal shape a future handler might still RETURN (the 3 known
        # ones now RAISE) — the error key catches it
        assert _classify_handler_return({"ok": False, "error": "boom"}) == "partial"

    def test_counts_errors_is_partial(self):
        assert _classify_handler_return({"ok": True, "counts": {"errors": 2}}) == "partial"

    def test_users_failed_is_partial(self):
        assert _classify_handler_return({"users_failed": 1, "users_total": 3}) == "partial"

    def test_zero_counts_errors_is_success(self):
        assert _classify_handler_return({"ok": True, "counts": {"errors": 0}}) == "succeeded"


class TestWiring:
    def _txt(self, *parts):
        return (_Q.joinpath(*parts)).read_text(encoding="utf-8")

    def test_three_monitors_raise_not_return_ok_false(self):
        for parts in (("jobs", "handlers", "intraday_risk_monitor.py"),
                      ("jobs", "handlers", "post_trade_learning.py"),
                      ("jobs", "handlers", "day_orchestrator.py")):
            src = self._txt(*parts)
            # the swallow-fatal return is gone; the fatal path RAISES
            assert '"ok": False,\n            "error": str(e),' not in src, parts
            assert "raise" in src, parts

    def test_mark_partial_writes_partial_status(self):
        src = self._txt("jobs", "job_runs.py")
        assert '"status": "partial",' in src
        assert '"status": "failed_retryable",' not in src  # partial path no longer mislabels

    def test_runner_terminal_skip_includes_partial(self):
        src = self._txt("jobs", "runner.py")
        assert '("succeeded", "partial", "cancelled", "dead_lettered")' in src

    def test_ops_health_consumers_include_partial(self):
        src = self._txt("services", "ops_health_service.py")
        assert '.in_("status", ["succeeded", "partial"])' in src
        assert '.eq("status", "succeeded")' not in src  # all job_runs reads migrated

    def test_dependency_phantom_enum_fixed(self):
        src = self._txt("services", "job_dependency_service.py")
        assert '["succeeded", "partial"]' in src
        assert "partial_failure" not in src  # the never-a-DB-value phantom is gone

    def test_terminal_states_and_enum(self):
        assert '"partial"' in self._txt("public_tasks.py")
        assert 'PARTIAL = "partial"' in self._txt("jobs", "types.py")
