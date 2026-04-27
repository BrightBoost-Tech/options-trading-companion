"""
Source-level structural assertions for #72-H4a: workflow_orchestrator
trade-decision-safety alerts.

Per Loud-Error Doctrine v1.0. Two sites in run_midday_cycle now write
risk_alerts when their underlying operations fail:

- Site 2158: envelope check (canonical 2026-04-25 silent-skip anti-pattern)
- Site 2196: ranker positions fetch (3-AMD-class concentration risk)

These tests use source-level structural assertions because
workflow_orchestrator.py is too large to runtime-test the relevant
except blocks without ~30 LOC of dependency stubbing (alpaca-py +
many other heavy imports). Same pattern as
test_workflow_orchestrator_ranker_positions.py — but no alpaca stubs
are needed here because no test imports the module; we only read its
source and parse it via ``ast``.
"""

import os
import unittest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
ORCHESTRATOR_PATH = os.path.join(
    REPO_ROOT, "packages", "quantum", "services", "workflow_orchestrator.py"
)


def _load_orchestrator_source() -> str:
    with open(ORCHESTRATOR_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _extract_except_block(src: str, except_marker: str) -> str:
    """Return the source slice from ``except_marker`` onward, capped at
    1500 chars. Large enough to capture the alert-call body
    (~12 lines × ~80 chars), small enough not to bleed into unrelated
    code below.

    Marker example: ``'except Exception as _env_err:'``
    """
    start = src.find(except_marker)
    if start < 0:
        return ""
    return src[start:start + 1500]


class TestEnvelopeCheckAlert(unittest.TestCase):
    """Site 2158: pre-entry envelope check failure must write a
    workflow_envelope_check_failed alert."""

    def setUp(self):
        self.src = _load_orchestrator_source()
        self.block = _extract_except_block(
            self.src, "except Exception as _env_err:"
        )

    def test_envelope_except_block_present(self):
        self.assertGreater(
            len(self.block), 0,
            "Could not locate the envelope-check except block — "
            "expected `except Exception as _env_err:` in run_midday_cycle.",
        )

    def test_envelope_check_alert_present(self):
        self.assertIn(
            "alert(", self.block,
            "Envelope-check except block must call alert() per "
            "Loud-Error Doctrine v1.0 (#72-H4a).",
        )

    def test_envelope_check_alert_type_correct(self):
        self.assertIn(
            'alert_type="workflow_envelope_check_failed"', self.block,
            "Envelope-check alert must use alert_type="
            "'workflow_envelope_check_failed'.",
        )

    def test_envelope_check_uses_admin_supabase(self):
        self.assertIn(
            "_get_admin_supabase()", self.block,
            "Envelope-check alert must call _get_admin_supabase() "
            "for its supabase arg (shared singleton from H3).",
        )

    def test_envelope_check_includes_consequence_metadata(self):
        self.assertIn(
            '"consequence"', self.block,
            "workflow_*-class alerts must include `consequence` field "
            "in metadata so operators can understand what silently "
            "continued. Pattern established by #72-H4a.",
        )


class TestRankerPositionsAlert(unittest.TestCase):
    """Site 2196: ranker positions fetch failure must write a
    workflow_ranker_positions_fetch_failed alert."""

    def setUp(self):
        self.src = _load_orchestrator_source()
        self.block = _extract_except_block(
            self.src, "except Exception as _pos_err:"
        )

    def test_ranker_except_block_present(self):
        self.assertGreater(
            len(self.block), 0,
            "Could not locate the ranker-positions except block — "
            "expected `except Exception as _pos_err:` in run_midday_cycle.",
        )

    def test_ranker_positions_alert_present(self):
        self.assertIn(
            "alert(", self.block,
            "Ranker-positions except block must call alert() per "
            "Loud-Error Doctrine v1.0 (#72-H4a).",
        )

    def test_ranker_positions_alert_type_correct(self):
        self.assertIn(
            'alert_type="workflow_ranker_positions_fetch_failed"', self.block,
            "Ranker-positions alert must use alert_type="
            "'workflow_ranker_positions_fetch_failed'.",
        )

    def test_ranker_positions_uses_admin_supabase(self):
        self.assertIn(
            "_get_admin_supabase()", self.block,
            "Ranker-positions alert must call _get_admin_supabase() "
            "for its supabase arg.",
        )

    def test_ranker_positions_consequence_mentions_3_amd(self):
        # The metadata's `consequence` value should reference the
        # 3-AMD-class concentration risk per the H4a diagnostic.
        self.assertIn(
            "3-AMD", self.block,
            "Ranker-positions alert consequence should reference the "
            "3-AMD-class concentration risk (the operational bug "
            "shape this alert exists to catch).",
        )


class TestModuleSyntaxValid(unittest.TestCase):
    """Verify workflow_orchestrator.py is syntactically valid Python
    after the H4a edits. Uses ``ast.parse`` rather than ``import`` to
    avoid triggering the heavy transitive dependency tree (alpaca-py,
    qci-client, etc.)."""

    def test_module_parses(self):
        import ast
        src = _load_orchestrator_source()
        try:
            ast.parse(src)
        except SyntaxError as e:
            self.fail(f"workflow_orchestrator.py has a syntax error: {e}")


class TestAlertImportPresent(unittest.TestCase):
    """The H4a edit adds a module-level import of alert and
    _get_admin_supabase from observability.alerts. Verify both
    names are imported."""

    def test_alert_imported_at_module_level(self):
        src = _load_orchestrator_source()
        self.assertIn(
            "from packages.quantum.observability.alerts import alert",
            src,
            "workflow_orchestrator must import alert from "
            "observability.alerts at module level (Loud-Error "
            "Doctrine canonical pattern).",
        )

    def test_get_admin_supabase_imported_at_module_level(self):
        src = _load_orchestrator_source()
        self.assertIn(
            "_get_admin_supabase", src,
            "workflow_orchestrator must reference _get_admin_supabase "
            "(imported alongside alert from observability.alerts).",
        )


if __name__ == "__main__":
    unittest.main()
