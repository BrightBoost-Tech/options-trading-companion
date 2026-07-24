"""
Regression tests for the 2026-05-18 H9 legacy sweep.

Closes 2 of the 3 genuine H9 legacy migration candidates that
were carried as deferred work on the allow-list since strict-mode
ship (2026-05-12):

- universe_service.sync_universe — Anti-pattern 2 (print-swallow)
  rewritten to call alert(); preserves the function's pre-fix
  return contract (None, implicit).
- iv_point_service.upsert_point — dead code (zero production
  callers); deleted entirely. Canonical write path
  IVRepository.upsert_iv_point remains.

The third candidate (position_pnl_service.refresh_marks_for_user)
remains on the allow-list — separate effort, larger scope.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Stub alpaca-py so imports resolve in the test venv.
from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()


class _AlertCapture:
    """Captures alert() calls. Used as a substitute for the real
    alert helper to verify call sites without hitting Supabase."""

    def __init__(self):
        self.calls = []

    def __call__(self, supabase, **kwargs):
        self.calls.append({"supabase": supabase, **kwargs})


# ─────────────────────────────────────────────────────────────────
# FIX 1 — universe_service.sync_universe
# ─────────────────────────────────────────────────────────────────


class TestSyncUniverseAlertOnFailure(unittest.TestCase):
    """sync_universe must call alert() on upsert failure rather than
    silently swallow. The function's return contract (implicit None)
    is preserved — only the visibility surface changes."""

    def _build_service(self, upsert_raises=None):
        from packages.quantum.services.universe_service import UniverseService
        client = MagicMock()
        # Build the .table().upsert().execute() chain.
        if upsert_raises:
            client.table.return_value.upsert.return_value.execute.side_effect = (
                upsert_raises
            )
        # Avoid Polygon network call inside __init__.
        with patch(
            "packages.quantum.services.universe_service.PolygonService"
        ), patch(
            "packages.quantum.services.universe_service.EarningsCalendarService"
        ):
            return UniverseService(client)

    def test_happy_path_does_not_alert(self):
        svc = self._build_service(upsert_raises=None)
        capture = _AlertCapture()
        with patch(
            "packages.quantum.services.universe_service.alert", capture
        ):
            svc.sync_universe()
        self.assertEqual(
            len(capture.calls), 0,
            "Happy path must not fire alerts."
        )

    def test_upsert_failure_fires_alert(self):
        svc = self._build_service(
            upsert_raises=RuntimeError("simulated DB failure")
        )
        capture = _AlertCapture()
        with patch(
            "packages.quantum.services.universe_service.alert", capture
        ):
            svc.sync_universe()  # MUST NOT raise
        self.assertEqual(len(capture.calls), 1, "Exactly one alert expected")

    def test_alert_uses_correct_type_and_severity(self):
        svc = self._build_service(
            upsert_raises=RuntimeError("simulated DB failure")
        )
        capture = _AlertCapture()
        with patch(
            "packages.quantum.services.universe_service.alert", capture
        ):
            svc.sync_universe()
        call = capture.calls[0]
        self.assertEqual(call["alert_type"], "universe_sync_upsert_failed")
        # warning is the alerts.py-valid severity for recoverable
        # operational failures. 'high' from CLAUDE.md framing maps
        # to 'warning' through the helper's enum.
        self.assertEqual(call["severity"], "warning")

    def test_alert_metadata_includes_error_class_and_batch_size(self):
        svc = self._build_service(
            upsert_raises=RuntimeError("simulated DB failure")
        )
        capture = _AlertCapture()
        with patch(
            "packages.quantum.services.universe_service.alert", capture
        ):
            svc.sync_universe()
        meta = capture.calls[0]["metadata"]
        self.assertEqual(meta["error_class"], "RuntimeError")
        self.assertIn("simulated DB failure", meta["error_message"])
        self.assertGreater(meta["batch_size"], 0)
        self.assertEqual(meta["function_name"], "UniverseService.sync_universe")
        self.assertIn("BASE_UNIVERSE", meta["consequence"])

    def test_function_returns_none_on_failure_no_reraise(self):
        """Pre-fix contract: implicit None return after print-swallow.
        Post-fix contract: identical — None after alert. The function
        must not raise to preserve caller behavior."""
        svc = self._build_service(
            upsert_raises=RuntimeError("simulated DB failure")
        )
        with patch(
            "packages.quantum.services.universe_service.alert"
        ):
            result = svc.sync_universe()
        self.assertIsNone(result)


# ─────────────────────────────────────────────────────────────────
# FIX 2 — iv_point_service.upsert_point removed
# ─────────────────────────────────────────────────────────────────


class TestIVPointServiceUpsertPointRemoved(unittest.TestCase):
    """upsert_point was dead code (zero production callers). Deleted
    in this sweep. The IVPointService class stays — its static
    computation methods are heavily used.

    Source-level assertions (rather than `hasattr` on the imported
    class) — full-suite test runs can attach attributes via Mock
    side-effects, and a source check is the unambiguous truth."""

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        cls.src = (
            Path(__file__).resolve().parent.parent
            / "services" / "iv_point_service.py"
        ).read_text(encoding="utf-8")

    def test_upsert_point_method_definition_removed(self):
        # The pre-PR `def upsert_point(...)` method body is gone.
        # The deletion-marker comment `# upsert_point removed` stays
        # to document the cleanup, so the bare string "upsert_point"
        # still appears in the file (in the comment + this test's
        # imports). The structural guard is on `def upsert_point` —
        # the function definition itself.
        self.assertNotIn(
            "def upsert_point(", self.src,
            "iv_point_service.py must not define an `upsert_point` "
            "method. Pre-PR was H9 Anti-pattern 2 (logger.error swallow). "
            "Canonical write path: IVRepository.upsert_iv_point."
        )

    def test_deletion_marker_comment_present(self):
        """The deletion left a marker comment explaining the H9
        cleanup and pointing to the canonical path."""
        self.assertIn(
            "# upsert_point removed", self.src,
            "Deletion marker comment should remain to document the "
            "cleanup for future readers."
        )

    def test_static_computation_methods_still_present(self):
        """Confirm the bulk of IVPointService stays intact."""
        for method_name in (
            "compute_atm_iv_target_from_chain",
            "compute_skew_25d_from_chain",
            "compute_term_slope",
            "get_points",
            "get_latest_point",
            "compute_iv_stats",
        ):
            self.assertIn(
                f"def {method_name}", self.src,
                f"IVPointService.{method_name} should still be defined "
                f"— only upsert_point was dead code."
            )

    def test_canonical_path_intact(self):
        """The canonical write path IVRepository.upsert_iv_point is
        the only one that should remain. Confirm the source still
        defines it."""
        from pathlib import Path
        repo_src = (
            Path(__file__).resolve().parent.parent
            / "services" / "iv_repository.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "def upsert_iv_point", repo_src,
            "Canonical iv_repository.upsert_iv_point path must remain."
        )


# ─────────────────────────────────────────────────────────────────
# Allow-list cleanup invariant
# ─────────────────────────────────────────────────────────────────


class TestAllowListShrunk(unittest.TestCase):
    """The allow-list should have dropped from 7 to 5 entries after
    this sweep. Source-level guard: confirm the two resolved entries
    are no longer present, and the unresolved third candidate is
    still on the list."""

    @classmethod
    def setUpClass(cls):
        from pathlib import Path
        cls.allow_list_src = (
            Path(__file__).resolve().parent
            / "h9_allow_list.yml"
        ).read_text(encoding="utf-8")

    def test_universe_service_sync_universe_removed(self):
        self.assertNotIn(
            "function: sync_universe", self.allow_list_src,
            "universe_service.sync_universe entry should be removed "
            "after FIX 1."
        )

    def test_iv_point_service_upsert_point_removed(self):
        self.assertNotIn(
            "function: upsert_point", self.allow_list_src,
            "iv_point_service.upsert_point entry should be removed "
            "after FIX 2 (dead-code deletion)."
        )

    def test_third_legacy_candidate_now_also_removed(self):
        """Updated 2026-05-18 by PR #968: when PR #966 shipped, this
        test asserted the third candidate (refresh_marks_for_user)
        was STILL on the allow-list as a deferred item. PR #968
        closed that third candidate, completing the 3-of-3 legacy
        sweep. The assertion is inverted to defend against
        accidental re-introduction."""
        self.assertNotIn(
            "function: refresh_marks_for_user", self.allow_list_src,
            "position_pnl_service.refresh_marks_for_user was removed "
            "from the allow-list by PR #968 (the 3rd and final legacy "
            "candidate migration).",
        )

    def test_chain_level_verified_entries_still_present(self):
        """The 4 chain-level-verified false positives must remain
        untouched by this sweep."""
        for name in (
            "function: upsert_iv_point",      # iv_repository
            "function: sync_positions",       # execution_router
            "function: sync_from_alpaca",     # position_sync
            "function: sync_orders",          # alpaca_order_sync
        ):
            self.assertIn(
                name, self.allow_list_src,
                f"{name} entry should remain on allow-list (this sweep "
                f"closes 2 entries; the rest are separate scope)."
            )


if __name__ == "__main__":
    unittest.main()
