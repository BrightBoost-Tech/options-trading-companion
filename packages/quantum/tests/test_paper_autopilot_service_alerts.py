"""Source-level structural assertions for #72-H5b doctrine application
in paper_autopilot_service.

H5b — paper_autopilot_service HOT swallows (10 alert sites):
  - TestStalenessGateAlert (site 191, single-fire safety)
  - TestCircuitBreakerCriticalAlert (site 236, single-fire CRITICAL)
  - TestPreSweepAlert (site 279, single-fire)
  - TestPerSuggestionAggregation (sites 411+438 collapsed, loop)
  - TestCohortPerSuggestionAggregation (site 605, loop)
  - TestCohortSweepAlert (site 618, single-fire)
  - TestRiskCheckPositionsFetchAlert (site 700, single-fire safety)
  - TestPortfolioBudgetFailedAlert (site 748, single-fire)
  - TestOccResolveFailedAlert (site 802, single-fire per-call)
  - TestPerPositionCloseAggregation (site 1000, loop)

Plus shared helpers:
  - TestModuleSyntaxValid (ast.parse check)
  - TestAlertImportPresent (module-level imports)

All tests are source-level structural assertions, matching the
test_paper_exit_evaluator_alerts.py convention from #72-H5a.
"""

import os
import unittest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
AUTOPILOT_PATH = os.path.join(
    REPO_ROOT, "packages", "quantum", "services", "paper_autopilot_service.py"
)


def _load_autopilot_source() -> str:
    with open(AUTOPILOT_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _block_around_alert_type(src: str, alert_type: str, before: int = 300, after: int = 1500) -> str:
    """Return source slice around a specific alert_type marker."""
    pos = src.find(f'alert_type="{alert_type}"')
    if pos < 0:
        return ""
    return src[max(0, pos - before):pos + after]


class TestStalenessGateAlert(unittest.TestCase):
    """Site 191: staleness_gate check failure must write
    paper_autopilot_staleness_gate_failed alert (SAFETY)."""

    @classmethod
    def setUpClass(cls):
        cls.src = _load_autopilot_source()
        cls.block = _block_around_alert_type(cls.src, "paper_autopilot_staleness_gate_failed")

    def test_alert_present(self):
        self.assertGreater(len(self.block), 0,
                           "Could not locate paper_autopilot_staleness_gate_failed alert.")

    def test_alert_call_present(self):
        self.assertIn("alert(", self.block)

    def test_alert_type_correct(self):
        self.assertIn('alert_type="paper_autopilot_staleness_gate_failed"', self.block)

    def test_uses_admin_supabase(self):
        self.assertIn("_get_admin_supabase()", self.block)

    def test_includes_consequence(self):
        self.assertIn('"consequence"', self.block)


class TestCircuitBreakerCriticalAlert(unittest.TestCase):
    """Site 236 (SAFETY-CRITICAL): circuit-breaker check failure means
    risk envelope state could not be verified; autopilot proceeds with
    entries despite a potential breach. Same severity convention as
    H5a site 9 (Alpaca submit fallback)."""

    @classmethod
    def setUpClass(cls):
        cls.src = _load_autopilot_source()
        cls.block = _block_around_alert_type(cls.src, "paper_autopilot_circuit_breaker_failed")

    def test_alert_present(self):
        self.assertGreater(len(self.block), 0,
                           "Could not locate paper_autopilot_circuit_breaker_failed alert.")

    def test_alert_type_correct(self):
        self.assertIn('alert_type="paper_autopilot_circuit_breaker_failed"', self.block)

    def test_uses_admin_supabase(self):
        self.assertIn("_get_admin_supabase()", self.block)

    def test_severity_is_critical(self):
        self.assertIn(
            'severity="critical"', self.block,
            "Site 236 alert MUST be severity='critical' (not 'warning'). "
            "Same convention as H5a site 9: silent failure leaves the "
            "system in a degraded state requiring operator intervention.",
        )

    def test_operator_action_required_metadata_field(self):
        self.assertIn(
            '"operator_action_required"', self.block,
            "Critical alerts must include operator_action_required field "
            "with explicit runbook text. Convention introduced by H5a, "
            "extended in H5b.",
        )

    def test_consequence_references_envelope_breach(self):
        self.assertIn(
            "envelope breach", self.block,
            "Consequence text should reference the envelope-breach risk "
            "so triage can find the safety semantics.",
        )

    def test_consequence_present(self):
        self.assertIn('"consequence"', self.block)

    def test_includes_function_name(self):
        self.assertIn('"function_name"', self.block)

    def test_alert_fires_before_fall_through(self):
        """The alert call must appear BEFORE the
        '[CIRCUIT_BREAKER] Check failed (non-fatal)' log line — operator
        awareness precedes the unsafe-entry fall-through."""
        alert_pos = self.src.find('alert_type="paper_autopilot_circuit_breaker_failed"')
        fallthrough_pos = self.src.find("[CIRCUIT_BREAKER] Check failed (non-fatal)")
        self.assertGreater(alert_pos, 0)
        self.assertGreater(fallthrough_pos, 0)
        self.assertLess(
            alert_pos, fallthrough_pos,
            "Alert MUST appear before the fall-through log line so "
            "operator awareness precedes unsafe-entry accumulation.",
        )


class TestPreSweepAlert(unittest.TestCase):
    """Site 279: pre-execution order sweep failure must write
    paper_autopilot_pre_sweep_failed alert."""

    @classmethod
    def setUpClass(cls):
        cls.src = _load_autopilot_source()
        cls.block = _block_around_alert_type(cls.src, "paper_autopilot_pre_sweep_failed")

    def test_alert_present(self):
        self.assertGreater(len(self.block), 0)

    def test_alert_type_correct(self):
        self.assertIn('alert_type="paper_autopilot_pre_sweep_failed"', self.block)

    def test_uses_admin_supabase(self):
        self.assertIn("_get_admin_supabase()", self.block)

    def test_includes_consequence(self):
        self.assertIn('"consequence"', self.block)


class TestPerSuggestionAggregation(unittest.TestCase):
    """Sites 411+438 collapsed: per-suggestion failures (status update +
    full execution) aggregated into one summary alert
    (paper_autopilot_per_suggestion_failed)."""

    @classmethod
    def setUpClass(cls):
        cls.src = _load_autopilot_source()

    def test_pre_loop_failures_list_init_present(self):
        self.assertIn(
            "_per_suggestion_failures = []", self.src,
            "Aggregation requires `_per_suggestion_failures = []` init "
            "before the suggestion loop.",
        )

    def test_in_loop_append_present(self):
        self.assertIn(
            "_per_suggestion_failures.append(", self.src,
            "Per-suggestion excepts must append to _per_suggestion_failures.",
        )

    def test_both_stages_append(self):
        # Two stages share the list: status_staged_update + full_execution
        self.assertGreaterEqual(
            self.src.count("_per_suggestion_failures.append("), 2,
            "Both per-suggestion stages must append to the shared list.",
        )

    def test_post_loop_conditional_present(self):
        self.assertIn(
            "if _per_suggestion_failures:", self.src,
            "Post-loop alert must be guarded by `if _per_suggestion_failures:`.",
        )

    def test_post_loop_alert_type_correct(self):
        block = _block_around_alert_type(self.src, "paper_autopilot_per_suggestion_failed")
        self.assertIn('alert_type="paper_autopilot_per_suggestion_failed"', block)

    def test_post_loop_uses_admin_supabase(self):
        block = _block_around_alert_type(self.src, "paper_autopilot_per_suggestion_failed")
        self.assertIn("_get_admin_supabase()", block)

    def test_post_loop_metadata_has_failed_count_and_tickers(self):
        block = _block_around_alert_type(self.src, "paper_autopilot_per_suggestion_failed")
        self.assertIn('"failed_count"', block)
        self.assertIn('"failed_tickers"', block)

    def test_post_loop_metadata_has_stages_affected(self):
        block = _block_around_alert_type(self.src, "paper_autopilot_per_suggestion_failed")
        self.assertIn('"stages_affected"', block,
                      "Aggregation metadata must include stages_affected so "
                      "triage can see whether status_staged_update or "
                      "full_execution (or both) were the failing stages.")

    def test_post_loop_includes_consequence(self):
        block = _block_around_alert_type(self.src, "paper_autopilot_per_suggestion_failed")
        self.assertIn('"consequence"', block)


class TestCohortPerSuggestionAggregation(unittest.TestCase):
    """Site 605: per-cohort per-suggestion execution failure aggregated
    into paper_autopilot_cohort_per_suggestion_failed alert."""

    @classmethod
    def setUpClass(cls):
        cls.src = _load_autopilot_source()

    def test_pre_loop_failures_list_init_present(self):
        self.assertIn(
            "_cohort_per_suggestion_failures = []", self.src,
            "Aggregation requires `_cohort_per_suggestion_failures = []` "
            "init before the cohort loop.",
        )

    def test_in_loop_append_present(self):
        self.assertIn(
            "_cohort_per_suggestion_failures.append(", self.src,
            "Cohort-loop except must append to _cohort_per_suggestion_failures.",
        )

    def test_post_loop_conditional_present(self):
        self.assertIn(
            "if _cohort_per_suggestion_failures:", self.src,
            "Post-loop alert must be guarded by "
            "`if _cohort_per_suggestion_failures:`.",
        )

    def test_post_loop_alert_type_correct(self):
        block = _block_around_alert_type(self.src, "paper_autopilot_cohort_per_suggestion_failed")
        self.assertIn('alert_type="paper_autopilot_cohort_per_suggestion_failed"', block)

    def test_post_loop_uses_admin_supabase(self):
        block = _block_around_alert_type(self.src, "paper_autopilot_cohort_per_suggestion_failed")
        self.assertIn("_get_admin_supabase()", block)

    def test_post_loop_metadata_has_cohorts_affected(self):
        block = _block_around_alert_type(self.src, "paper_autopilot_cohort_per_suggestion_failed")
        self.assertIn('"cohorts_affected"', block,
                      "Cohort-loop metadata must include cohorts_affected.")

    def test_post_loop_includes_consequence(self):
        block = _block_around_alert_type(self.src, "paper_autopilot_cohort_per_suggestion_failed")
        self.assertIn('"consequence"', block)


class TestCohortSweepAlert(unittest.TestCase):
    """Site 618: Policy Lab cohort sweep failure must write
    paper_autopilot_cohort_sweep_failed alert."""

    @classmethod
    def setUpClass(cls):
        cls.src = _load_autopilot_source()
        cls.block = _block_around_alert_type(cls.src, "paper_autopilot_cohort_sweep_failed")

    def test_alert_present(self):
        self.assertGreater(len(self.block), 0)

    def test_alert_type_correct(self):
        self.assertIn('alert_type="paper_autopilot_cohort_sweep_failed"', self.block)

    def test_uses_admin_supabase(self):
        self.assertIn("_get_admin_supabase()", self.block)

    def test_includes_consequence(self):
        self.assertIn('"consequence"', self.block)


class TestRiskCheckPositionsFetchAlert(unittest.TestCase):
    """Site 700: _get_open_positions_for_risk_check failure must write
    paper_autopilot_risk_check_positions_fetch_failed alert (SAFETY)."""

    @classmethod
    def setUpClass(cls):
        cls.src = _load_autopilot_source()
        cls.block = _block_around_alert_type(cls.src, "paper_autopilot_risk_check_positions_fetch_failed")

    def test_alert_present(self):
        self.assertGreater(len(self.block), 0)

    def test_alert_type_correct(self):
        self.assertIn('alert_type="paper_autopilot_risk_check_positions_fetch_failed"', self.block)

    def test_uses_admin_supabase(self):
        self.assertIn("_get_admin_supabase()", self.block)

    def test_function_name_correct(self):
        self.assertIn(
            '"function_name": "_get_open_positions_for_risk_check"', self.block,
        )

    def test_includes_consequence(self):
        self.assertIn('"consequence"', self.block)


class TestPortfolioBudgetFailedAlert(unittest.TestCase):
    """Site 748: _get_portfolio_budget failure must write
    paper_autopilot_portfolio_budget_failed alert."""

    @classmethod
    def setUpClass(cls):
        cls.src = _load_autopilot_source()
        cls.block = _block_around_alert_type(cls.src, "paper_autopilot_portfolio_budget_failed")

    def test_alert_present(self):
        self.assertGreater(len(self.block), 0)

    def test_alert_type_correct(self):
        self.assertIn('alert_type="paper_autopilot_portfolio_budget_failed"', self.block)

    def test_uses_admin_supabase(self):
        self.assertIn("_get_admin_supabase()", self.block)

    def test_metadata_has_fallback_budget(self):
        self.assertIn(
            '"fallback_budget"', self.block,
            "Metadata must include the fallback_budget value so triage "
            "can see what default was used.",
        )

    def test_includes_consequence(self):
        self.assertIn('"consequence"', self.block)


class TestOccResolveFailedAlert(unittest.TestCase):
    """Site 802: _resolve_occ_symbol failure (per-call alert; static
    method can't aggregate across close-loop without signature change)."""

    @classmethod
    def setUpClass(cls):
        cls.src = _load_autopilot_source()
        cls.block = _block_around_alert_type(cls.src, "paper_autopilot_occ_resolve_failed")

    def test_alert_present(self):
        self.assertGreater(len(self.block), 0)

    def test_alert_type_correct(self):
        self.assertIn('alert_type="paper_autopilot_occ_resolve_failed"', self.block)

    def test_uses_admin_supabase(self):
        self.assertIn("_get_admin_supabase()", self.block)

    def test_metadata_has_position_id_and_underlying(self):
        self.assertIn('"position_id"', self.block)
        self.assertIn('"underlying"', self.block)

    def test_includes_consequence(self):
        self.assertIn('"consequence"', self.block)


class TestPerPositionCloseAggregation(unittest.TestCase):
    """Site 1000: per-position close failures aggregated into
    paper_autopilot_per_position_close_failed alert."""

    @classmethod
    def setUpClass(cls):
        cls.src = _load_autopilot_source()

    def test_pre_loop_failures_list_init_present(self):
        self.assertIn(
            "_per_position_close_failures = []", self.src,
            "Aggregation requires `_per_position_close_failures = []` "
            "init before the close loop.",
        )

    def test_in_loop_append_present(self):
        self.assertIn(
            "_per_position_close_failures.append(", self.src,
            "Close-loop except must append to _per_position_close_failures.",
        )

    def test_post_loop_conditional_present(self):
        self.assertIn(
            "if _per_position_close_failures:", self.src,
            "Post-loop alert must be guarded by "
            "`if _per_position_close_failures:`.",
        )

    def test_post_loop_alert_type_correct(self):
        block = _block_around_alert_type(self.src, "paper_autopilot_per_position_close_failed")
        self.assertIn('alert_type="paper_autopilot_per_position_close_failed"', block)

    def test_post_loop_uses_admin_supabase(self):
        block = _block_around_alert_type(self.src, "paper_autopilot_per_position_close_failed")
        self.assertIn("_get_admin_supabase()", block)

    def test_post_loop_metadata_has_failed_count_and_symbols(self):
        block = _block_around_alert_type(self.src, "paper_autopilot_per_position_close_failed")
        self.assertIn('"failed_count"', block)
        self.assertIn('"failed_symbols"', block)

    def test_post_loop_includes_consequence(self):
        block = _block_around_alert_type(self.src, "paper_autopilot_per_position_close_failed")
        self.assertIn('"consequence"', block)


class TestModuleSyntaxValid(unittest.TestCase):
    """Verify paper_autopilot_service.py is syntactically valid Python
    after the H5b edits."""

    def test_module_parses(self):
        import ast
        src = _load_autopilot_source()
        try:
            ast.parse(src)
        except SyntaxError as e:
            self.fail(f"paper_autopilot_service.py has a syntax error: {e}")


class TestAlertImportPresent(unittest.TestCase):
    """The H5b edit adds a module-level import of alert and
    _get_admin_supabase from observability.alerts."""

    def test_alert_imported_at_module_level(self):
        src = _load_autopilot_source()
        self.assertIn(
            "from packages.quantum.observability.alerts import alert",
            src,
            "paper_autopilot_service must import alert from "
            "observability.alerts at module level.",
        )

    def test_get_admin_supabase_imported_at_module_level(self):
        src = _load_autopilot_source()
        self.assertIn(
            "_get_admin_supabase", src,
            "paper_autopilot_service must reference _get_admin_supabase.",
        )


if __name__ == "__main__":
    unittest.main()
