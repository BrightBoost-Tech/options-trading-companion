"""Tests for MTM-staleness PR-1: alerts + last_marked_at observability.

Closes the silent-failure observability gap surfaced by 2026-05-12 CSX
situation. Both intraday-critical refresh paths
(`paper_mark_to_market_service.refresh_marks` writes to DB;
`intraday_risk_monitor._refresh_marks` recomputes in-memory) used to
silently skip positions when option-leg snapshot data was incomplete.
Callers trusted the wrapper's success return; threshold checks ran on
stale values; no alert ever fired.

This PR's contract:
1. Successful per-position MTM write populates `last_marked_at`
2. Silently-skipped positions do NOT have `last_marked_at` updated
   (preserves observability — `WHERE last_marked_at < NOW() - 30m`
   surfaces them)
3. `mtm_refresh_partial` alert fires when ANY position is skipped at
   either refresh site, with `source` field distinguishing them

Source-level structural assertions only — exercising the real
refresh_marks flow requires heavy Supabase + MarketDataTruthLayer
mocking that would obscure the contract being asserted.
"""

import re
import unittest
from pathlib import Path


_QUANTUM_ROOT = Path(__file__).resolve().parent.parent
MTM_SERVICE_PATH = _QUANTUM_ROOT / "services" / "paper_mark_to_market_service.py"
RISK_MONITOR_PATH = _QUANTUM_ROOT / "jobs" / "handlers" / "intraday_risk_monitor.py"
MIGRATION_DIR = _QUANTUM_ROOT.parent.parent / "supabase" / "migrations"


class TestMigrationAddsLastMarkedAt(unittest.TestCase):
    """The `last_marked_at` column migration ships in this PR."""

    def test_migration_file_exists(self):
        matches = list(MIGRATION_DIR.glob("*add_last_marked_at*.sql"))
        self.assertEqual(
            len(matches), 1,
            f"Expected exactly one add_last_marked_at migration file, "
            f"found {len(matches)}: {[m.name for m in matches]}",
        )

    def test_migration_adds_nullable_timestamptz(self):
        matches = list(MIGRATION_DIR.glob("*add_last_marked_at*.sql"))
        self.assertGreater(len(matches), 0, "Migration file missing")
        sql = matches[0].read_text(encoding="utf-8")

        # Column added to correct table
        self.assertIn("paper_positions", sql)
        # TIMESTAMPTZ type (matches existing time columns)
        self.assertIn("TIMESTAMPTZ", sql)
        # IF NOT EXISTS — re-apply safe
        self.assertIn("IF NOT EXISTS", sql)
        # Comment explaining purpose (forensic queries find it)
        self.assertIn("MTM refresh", sql)


class TestPaperMarkToMarketServicePopulatesLastMarkedAt(unittest.TestCase):
    """Successful per-position write must include `last_marked_at`."""

    @classmethod
    def setUpClass(cls):
        cls.src = MTM_SERVICE_PATH.read_text(encoding="utf-8")

    def test_batch_update_dict_includes_last_marked_at(self):
        """The dict appended to batch_updates (success path) must have
        last_marked_at."""
        # Anchor: the construction of the per-position update dict
        idx = self.src.find('"current_mark": per_contract_mark,')
        self.assertGreater(idx, 0, "batch_updates dict construction missing")
        # Scan 1500 chars forward — the explanatory comment block above
        # the new field pushes it deeper into the dict literal.
        window = self.src[idx:idx + 1500]
        self.assertIn('"last_marked_at"', window)
        # And the value must be NOW()-style (not a fixed string or None)
        self.assertIn("datetime.now(timezone.utc).isoformat()", window)

    def test_last_marked_at_not_populated_on_skip_path(self):
        """The skip path (current_value is None) must NOT touch
        last_marked_at — preserves staleness observability."""
        # Anchor at the silent-skip branch
        idx = self.src.find('"incomplete_quotes_skipped"')
        self.assertGreater(idx, 0)
        # 200 chars around this branch shouldn't mention last_marked_at
        window = self.src[max(0, idx - 200):idx + 200]
        self.assertNotIn(
            '"last_marked_at"', window,
            "skip path appears to write last_marked_at — that defeats "
            "the observability purpose (operators can't distinguish "
            "successfully-marked from silently-skipped positions).",
        )


class TestPaperMarkToMarketServiceAlertOnSkip(unittest.TestCase):
    """`mtm_refresh_partial` alert must fire when any position is
    skipped during refresh_marks."""

    @classmethod
    def setUpClass(cls):
        cls.src = MTM_SERVICE_PATH.read_text(encoding="utf-8")

    def test_alert_helper_imported(self):
        self.assertIn(
            "from packages.quantum.observability.alerts import alert",
            self.src,
            "alert helper not imported — refresh_marks can't emit alerts.",
        )

    def test_alert_fires_in_partial_branch(self):
        """The alert call must be guarded by `skipped > 0 or errors`."""
        idx = self.src.find('alert_type="mtm_refresh_partial"')
        self.assertGreater(
            idx, 0,
            "mtm_refresh_partial alert call missing from refresh_marks.",
        )
        # Find the conditional wrapping the alert
        block = self.src[max(0, idx - 500):idx]
        self.assertIn("skipped > 0 or errors", block)

    def test_alert_severity_warning(self):
        idx = self.src.find('alert_type="mtm_refresh_partial"')
        block = self.src[idx:idx + 600]
        self.assertIn('severity="warning"', block)

    def test_alert_metadata_has_diagnostic_fields(self):
        idx = self.src.find('alert_type="mtm_refresh_partial"')
        block = self.src[idx:idx + 1500]
        for field in (
            "positions_marked",
            "positions_skipped",
            "total_positions",
            "source",
            "errors",
            "consequence",
        ):
            self.assertIn(
                f'"{field}"', block,
                f"Alert metadata missing field: {field}",
            )

    def test_alert_source_identifies_call_site(self):
        idx = self.src.find('alert_type="mtm_refresh_partial"')
        block = self.src[idx:idx + 1500]
        self.assertIn(
            '"paper_mark_to_market_service.refresh_marks"', block,
            "source field should identify which refresh path fired the "
            "alert. The intraday_risk_monitor variant uses a different "
            "source string.",
        )

    def test_alert_path_failure_does_not_crash_refresh(self):
        """If the alert write itself throws, refresh_marks must still
        return its normal result. Best-effort observability — never
        crash the primary path."""
        idx = self.src.find('alert_type="mtm_refresh_partial"')
        block = self.src[max(0, idx - 100):idx + 1500]
        self.assertIn("except Exception", block)


class TestIntradayRiskMonitorAlertOnSkip(unittest.TestCase):
    """`mtm_refresh_partial` alert must also fire in the in-memory
    recompute path at intraday_risk_monitor._refresh_marks."""

    @classmethod
    def setUpClass(cls):
        cls.src = RISK_MONITOR_PATH.read_text(encoding="utf-8")

    def _refresh_marks_body(self) -> str:
        """Source of the _refresh_marks method only."""
        anchor = self.src.find("def _refresh_marks(self")
        self.assertGreater(anchor, 0, "_refresh_marks not found")
        # End at next top-level method in the class
        end_match = re.search(
            r"\n    def [a-zA-Z_]",
            self.src[anchor + 50:],
        )
        end = (anchor + 50 + end_match.start()) if end_match else len(self.src)
        return self.src[anchor:end]

    def test_skipped_positions_tracked_in_loop(self):
        """When the per-leg `all_priced` guard short-circuits, the
        skipped position must be appended to a tracking list. Without
        this, the alert below has no input."""
        body = self._refresh_marks_body()
        self.assertIn("skipped_positions", body)
        # Tracked from the else-branch of the all_priced check
        self.assertIn("skipped_positions.append", body)

    def test_alert_fires_when_any_position_skipped(self):
        body = self._refresh_marks_body()
        self.assertIn('alert_type="mtm_refresh_partial"', body)
        # Guarded by skipped_positions being non-empty
        idx = body.find('alert_type="mtm_refresh_partial"')
        self.assertGreater(idx, 0)
        block = body[max(0, idx - 200):idx]
        self.assertIn("if skipped_positions", block)

    def test_alert_source_identifies_intraday_path(self):
        body = self._refresh_marks_body()
        idx = body.find('alert_type="mtm_refresh_partial"')
        block = body[idx:idx + 1500]
        self.assertIn(
            '"intraday_risk_monitor._refresh_marks"', block,
            "source field should distinguish this refresh path from "
            "paper_mark_to_market_service.refresh_marks's variant.",
        )

    def test_alert_metadata_lists_skipped_position_ids_and_symbols(self):
        body = self._refresh_marks_body()
        idx = body.find('alert_type="mtm_refresh_partial"')
        block = body[idx:idx + 1500]
        # The per-position skip records include id + symbol — must
        # surface in alert metadata for operator forensics.
        self.assertIn('"skipped"', block)

    def test_alert_uses_existing_log_alert_helper(self):
        """Use the in-class _log_alert helper rather than reaching for
        the observability.alerts module directly (matches the existing
        4 alert sites in the file)."""
        body = self._refresh_marks_body()
        # The alert call should be `self._log_alert(...)` not
        # `alert(self.supabase, ...)`
        self.assertIn("self._log_alert(", body)


if __name__ == "__main__":
    unittest.main()
