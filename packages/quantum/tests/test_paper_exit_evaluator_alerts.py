"""Source-level structural assertions for #72-H5a doctrine application
in paper_exit_evaluator.

H5a — paper_exit_evaluator HOT swallows (9 alert sites):
  - TestPerConditionEvalAggregation (site 461, loop-aggregation)
  - TestCohortConfigsLoadAlert (site 557, single-fire)
  - TestCloseLoopAggregation (site 699, loop-aggregation)
  - TestOpenPositionsFetchAlert (site 748, single-fire safety)
  - TestCohortResolveExhaustedAlert (sites 772+788+803 collapsed, special)
  - TestRoutingQueryFailedAlert (site 848, single-fire safety)
  - TestIdempotencyCheckFailedAlert (site 895, single-fire safety)
  - TestAlpacaDryRunBuildFailedAlert (site 1002, single-fire)
  - TestAlpacaSubmitFallbackCriticalAlert (site 1039, single-fire CRITICAL)

Plus shared helpers:
  - TestModuleSyntaxValid (ast.parse check)
  - TestAlertImportPresent (module-level imports)

All tests are source-level structural assertions, matching the
test_workflow_orchestrator_alerts.py convention from #72-H4.
"""

import os
import unittest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
EVALUATOR_PATH = os.path.join(
    REPO_ROOT, "packages", "quantum", "services", "paper_exit_evaluator.py"
)


def _load_evaluator_source() -> str:
    with open(EVALUATOR_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _block_around_alert_type(src: str, alert_type: str, before: int = 300, after: int = 1500) -> str:
    """Return source slice around a specific alert_type marker."""
    pos = src.find(f'alert_type="{alert_type}"')
    if pos < 0:
        return ""
    return src[max(0, pos - before):pos + after]


class TestPerConditionEvalAggregation(unittest.TestCase):
    """Site 461: per-condition exit eval failures aggregated into one
    summary alert (paper_exit_per_condition_eval_failed)."""

    @classmethod
    def setUpClass(cls):
        cls.src = _load_evaluator_source()

    def test_pre_loop_failures_list_init_present(self):
        self.assertIn(
            "per_condition_failures = []", self.src,
            "Aggregation pattern requires `per_condition_failures = []` "
            "init before the per-condition loop.",
        )

    def test_in_loop_append_present(self):
        self.assertIn(
            "per_condition_failures.append(", self.src,
            "Per-condition except must append failure to "
            "per_condition_failures (aggregation pattern, #72-H5a).",
        )

    def test_post_loop_conditional_present(self):
        self.assertIn(
            "if per_condition_failures:", self.src,
            "Post-loop alert must be guarded by "
            "`if per_condition_failures:` conditional.",
        )

    def test_post_loop_alert_type_correct(self):
        block = _block_around_alert_type(self.src, "paper_exit_per_condition_eval_failed")
        self.assertGreater(len(block), 0,
                           "Could not locate paper_exit_per_condition_eval_failed alert.")
        self.assertIn(
            'alert_type="paper_exit_per_condition_eval_failed"', block,
        )

    def test_post_loop_uses_admin_supabase(self):
        block = _block_around_alert_type(self.src, "paper_exit_per_condition_eval_failed")
        self.assertIn("_get_admin_supabase()", block)

    def test_post_loop_metadata_has_failed_count_and_symbols(self):
        block = _block_around_alert_type(self.src, "paper_exit_per_condition_eval_failed")
        self.assertIn('"failed_count"', block,
                      "Aggregation metadata must include failed_count.")
        self.assertIn('"failed_symbols"', block,
                      "Aggregation metadata must include failed_symbols.")

    def test_post_loop_includes_consequence(self):
        block = _block_around_alert_type(self.src, "paper_exit_per_condition_eval_failed")
        self.assertIn('"consequence"', block,
                      "Aggregation alert must include `consequence` field.")


class TestCohortConfigsLoadAlert(unittest.TestCase):
    """Site 557: cohort configs load failure must write
    paper_exit_cohort_configs_load_failed alert."""

    @classmethod
    def setUpClass(cls):
        cls.src = _load_evaluator_source()
        cls.block = _block_around_alert_type(cls.src, "paper_exit_cohort_configs_load_failed")

    def test_alert_present(self):
        self.assertGreater(len(self.block), 0,
                           "Could not locate paper_exit_cohort_configs_load_failed alert.")

    def test_alert_call_present(self):
        self.assertIn("alert(", self.block)

    def test_alert_type_correct(self):
        self.assertIn('alert_type="paper_exit_cohort_configs_load_failed"', self.block)

    def test_uses_admin_supabase(self):
        self.assertIn("_get_admin_supabase()", self.block)

    def test_includes_consequence(self):
        self.assertIn('"consequence"', self.block)


class TestCloseLoopAggregation(unittest.TestCase):
    """Site 699: close-loop failures (record_day_trade + unhandled
    _close_position exceptions) aggregated into
    paper_exit_day_trade_record_failed alert."""

    @classmethod
    def setUpClass(cls):
        cls.src = _load_evaluator_source()

    def test_pre_loop_failures_list_init_present(self):
        self.assertIn(
            "_close_loop_failures = []", self.src,
            "Aggregation requires `_close_loop_failures = []` init "
            "before the close loop.",
        )

    def test_in_loop_append_present(self):
        self.assertIn(
            "_close_loop_failures.append(", self.src,
            "Close-loop except must append failure to _close_loop_failures.",
        )

    def test_post_loop_conditional_present(self):
        self.assertIn(
            "if _close_loop_failures:", self.src,
            "Post-loop alert must be guarded by `if _close_loop_failures:`.",
        )

    def test_post_loop_alert_type_correct(self):
        block = _block_around_alert_type(self.src, "paper_exit_day_trade_record_failed")
        self.assertIn('alert_type="paper_exit_day_trade_record_failed"', block)

    def test_post_loop_uses_admin_supabase(self):
        block = _block_around_alert_type(self.src, "paper_exit_day_trade_record_failed")
        self.assertIn("_get_admin_supabase()", block)

    def test_post_loop_metadata_has_failed_count_and_symbols(self):
        block = _block_around_alert_type(self.src, "paper_exit_day_trade_record_failed")
        self.assertIn('"failed_count"', block)
        self.assertIn('"failed_symbols"', block)

    def test_post_loop_includes_consequence(self):
        block = _block_around_alert_type(self.src, "paper_exit_day_trade_record_failed")
        self.assertIn('"consequence"', block)


class TestOpenPositionsFetchAlert(unittest.TestCase):
    """Site 748: _get_open_positions failure must write
    paper_exit_open_positions_fetch_failed alert (SAFETY)."""

    @classmethod
    def setUpClass(cls):
        cls.src = _load_evaluator_source()
        cls.block = _block_around_alert_type(cls.src, "paper_exit_open_positions_fetch_failed")

    def test_alert_present(self):
        self.assertGreater(len(self.block), 0)

    def test_alert_call_present(self):
        self.assertIn("alert(", self.block)

    def test_alert_type_correct(self):
        self.assertIn('alert_type="paper_exit_open_positions_fetch_failed"', self.block)

    def test_uses_admin_supabase(self):
        self.assertIn("_get_admin_supabase()", self.block)

    def test_includes_consequence(self):
        self.assertIn('"consequence"', self.block)


class TestCohortResolveExhaustedAlert(unittest.TestCase):
    """Site 772+788+803 collapsed: cohort resolution exhausted alert
    fires only when all 3 fallback paths failed."""

    @classmethod
    def setUpClass(cls):
        cls.src = _load_evaluator_source()
        cls.block = _block_around_alert_type(cls.src, "paper_exit_cohort_resolve_exhausted")

    def test_resolution_failures_list_present(self):
        self.assertIn(
            "_resolution_failures = []", self.src,
            "Collapse pattern requires `_resolution_failures = []` init "
            "at start of _resolve_position_cohort.",
        )

    def test_resolution_failures_appended_in_each_path(self):
        # All 3 except blocks must append to the same list.
        self.assertGreaterEqual(
            self.src.count("_resolution_failures.append("), 3,
            "All 3 cohort-resolution fallback excepts must append to "
            "_resolution_failures.",
        )

    def test_alert_only_when_all_three_failed(self):
        self.assertIn(
            "if len(_resolution_failures) == 3:", self.src,
            "Alert must be guarded by `if len(_resolution_failures) == 3:` "
            "so it only fires when ALL 3 paths failed.",
        )

    def test_alert_type_correct(self):
        self.assertGreater(len(self.block), 0)
        self.assertIn('alert_type="paper_exit_cohort_resolve_exhausted"', self.block)

    def test_uses_admin_supabase(self):
        self.assertIn("_get_admin_supabase()", self.block)

    def test_metadata_has_resolution_attempts(self):
        self.assertIn(
            '"resolution_attempts"', self.block,
            "Metadata must include resolution_attempts list with per-path "
            "error details.",
        )

    def test_includes_consequence(self):
        self.assertIn('"consequence"', self.block)


class TestRoutingQueryFailedAlert(unittest.TestCase):
    """Site 848: entry-routing query failure during close path
    determination must write paper_exit_routing_query_failed alert."""

    @classmethod
    def setUpClass(cls):
        cls.src = _load_evaluator_source()
        cls.block = _block_around_alert_type(cls.src, "paper_exit_routing_query_failed")

    def test_alert_present(self):
        self.assertGreater(len(self.block), 0)

    def test_alert_type_correct(self):
        self.assertIn('alert_type="paper_exit_routing_query_failed"', self.block)

    def test_uses_admin_supabase(self):
        self.assertIn("_get_admin_supabase()", self.block)

    def test_includes_position_id_metadata(self):
        self.assertIn('"position_id"', self.block,
                      "Metadata must include position_id for triage.")

    def test_includes_consequence(self):
        self.assertIn('"consequence"', self.block)


class TestIdempotencyCheckFailedAlert(unittest.TestCase):
    """Site 895: idempotency-check query failure must write
    paper_exit_idempotency_check_failed alert."""

    @classmethod
    def setUpClass(cls):
        cls.src = _load_evaluator_source()
        cls.block = _block_around_alert_type(cls.src, "paper_exit_idempotency_check_failed")

    def test_alert_present(self):
        self.assertGreater(len(self.block), 0)

    def test_alert_type_correct(self):
        self.assertIn('alert_type="paper_exit_idempotency_check_failed"', self.block)

    def test_uses_admin_supabase(self):
        self.assertIn("_get_admin_supabase()", self.block)

    def test_includes_position_id_metadata(self):
        self.assertIn('"position_id"', self.block)

    def test_includes_consequence(self):
        self.assertIn('"consequence"', self.block)


class TestAlpacaDryRunBuildFailedAlert(unittest.TestCase):
    """Site 1002: Alpaca DRY_RUN order build failure must write
    paper_exit_alpaca_dry_run_build_failed alert."""

    @classmethod
    def setUpClass(cls):
        cls.src = _load_evaluator_source()
        cls.block = _block_around_alert_type(cls.src, "paper_exit_alpaca_dry_run_build_failed")

    def test_alert_present(self):
        self.assertGreater(len(self.block), 0)

    def test_alert_type_correct(self):
        self.assertIn('alert_type="paper_exit_alpaca_dry_run_build_failed"', self.block)

    def test_uses_admin_supabase(self):
        self.assertIn("_get_admin_supabase()", self.block)

    def test_includes_consequence(self):
        self.assertIn('"consequence"', self.block)


class TestP0ABrokerAckCloseInvariant(unittest.TestCase):
    """P0-A (2026-07-10, F-A2-1 / E6). REPLACES TestAlpacaSubmitFallbackCritical-
    Alert, which pinned the REMOVED behavior (a live Alpaca-submit failure fell
    through to an internal fill — the 2026-04-16 ghost-position shape). That
    fallthrough is now gone: a live submit failure fires force_close_failed
    critical, holds the position OPEN (unknown_reconciling), and NEVER internally
    fills; the internal-fill block is structurally unreachable for live routes."""

    @classmethod
    def setUpClass(cls):
        cls.src = _load_evaluator_source()

    def test_old_fallback_alert_type_removed(self):
        self.assertNotIn(
            'alert_type="paper_exit_alpaca_submit_fallback_to_internal"', self.src,
            "P0-A removes the fall-back-to-internal-fill for live closes; the "
            "old alert type must be gone.",
        )

    def test_fallthrough_language_removed(self):
        for phrase in ("Falling back to internal fill", "Fall through to internal fill below"):
            self.assertNotIn(
                phrase, self.src,
                f"P0-A removes the internal-fill fallthrough — {phrase!r} must be gone.",
            )

    def test_submit_failure_fires_force_close_failed_critical(self):
        block = _block_around_alert_type(self.src, "force_close_failed")
        self.assertGreater(len(block), 0,
                           "Submit failure must fire force_close_failed (its first close-path producer).")
        self.assertIn('severity="critical"', block)
        self.assertIn('"operator_action_required"', block)

    def test_failed_close_returns_unknown_reconciling(self):
        self.assertIn(
            '"routed_to": "unknown_reconciling"', self.src,
            "A failed/ambiguous LIVE close returns unknown_reconciling — held "
            "open, never internally filled.",
        )

    def test_structural_guard_gates_on_should_submit(self):
        self.assertIn("STRUCTURAL INVARIANT GUARD (P0-A", self.src)
        self.assertIn(
            "_p0a_should_submit(", self.src,
            "The internal-fill guard must gate on should_submit_to_broker.",
        )

    def test_guard_precedes_internal_fill_block(self):
        gi = self.src.find("STRUCTURAL INVARIANT GUARD (P0-A")
        fi = self.src.find("--- Internal fill (internal_paper or Alpaca fallback) ---")
        self.assertGreater(gi, 0, "structural guard missing.")
        self.assertGreater(fi, gi, "guard must sit BEFORE the internal-fill block.")


class TestModuleSyntaxValid(unittest.TestCase):
    """Verify paper_exit_evaluator.py is syntactically valid Python
    after the H5a edits. ast.parse rather than import to avoid the
    heavy transitive dependency tree."""

    def test_module_parses(self):
        import ast
        src = _load_evaluator_source()
        try:
            ast.parse(src)
        except SyntaxError as e:
            self.fail(f"paper_exit_evaluator.py has a syntax error: {e}")


class TestAlertImportPresent(unittest.TestCase):
    """The H5a edit adds a module-level import of alert and
    _get_admin_supabase from observability.alerts."""

    def test_alert_imported_at_module_level(self):
        src = _load_evaluator_source()
        self.assertIn(
            "from packages.quantum.observability.alerts import alert",
            src,
            "paper_exit_evaluator must import alert from "
            "observability.alerts at module level.",
        )

    def test_get_admin_supabase_imported_at_module_level(self):
        src = _load_evaluator_source()
        self.assertIn(
            "_get_admin_supabase", src,
            "paper_exit_evaluator must reference _get_admin_supabase.",
        )


if __name__ == "__main__":
    unittest.main()
