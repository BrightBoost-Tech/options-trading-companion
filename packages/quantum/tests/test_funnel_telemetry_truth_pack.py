"""Reporting-only funnel telemetry truth contracts."""

import types
import unittest

from packages.quantum.options_scanner import RejectionStats
from packages.quantum.services.universe_service import UniverseService
from packages.quantum.services.workflow_orchestrator import _build_enriched_counts


class _Query:
    def __init__(self, rows=None, error=None):
        self.rows = rows or []
        self.error = error

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def insert(self, *_a, **_k):
        return self

    def execute(self):
        if self.error:
            raise self.error
        return types.SimpleNamespace(data=self.rows)


class _Supabase:
    def __init__(self, rows=None, error=None):
        self.query = _Query(rows, error)

    def table(self, _name):
        return self.query


class TestDenominatorHonesty(unittest.TestCase):
    def test_active_universe_is_not_scanner_emissions(self):
        counts = _build_enriched_counts(
            universe_size=None,
            scanner_emitted=10,
            trade_suggestions_created=2,
            h7_passed=3,
            edge_above_minimum=1,
            executable=1,
            staged=1,
            active_universe_count=78,
            selected_symbol_count=78,
            scanner_emitted_candidate_count=10,
            h7_passed_count=3,
            persisted_count=2,
            executable_count=1,
        )
        self.assertEqual(counts["active_universe_count"], 78)
        self.assertEqual(counts["selected_symbol_count"], 78)
        self.assertEqual(counts["scanner_emitted_candidate_count"], 10)
        self.assertEqual(counts["universe_size"], 78)
        self.assertNotEqual(counts["universe_size"], counts["scanner_emitted"])

    def test_unmeasured_and_measured_zero_stay_distinct(self):
        pre = _build_enriched_counts(
            universe_size=None, scanner_emitted=None,
            trade_suggestions_created=None, h7_passed=None,
            edge_above_minimum=None, executable=None, staged=None,
        )
        zero = _build_enriched_counts(
            universe_size=None, scanner_emitted=0,
            trade_suggestions_created=0, h7_passed=0,
            edge_above_minimum=0, executable=0, staged=0,
            active_universe_count=0, selected_symbol_count=0,
            scanner_emitted_candidate_count=0, h7_passed_count=0,
            persisted_count=0, executable_count=0,
        )
        self.assertIsNone(pre["active_universe_count"])
        self.assertEqual(zero["active_universe_count"], 0)
        self.assertIsNone(pre["persisted_count"])
        self.assertEqual(zero["persisted_count"], 0)


class TestScannerStatsContract(unittest.TestCase):
    def test_rejection_stats_surfaces_selection_denominators(self):
        stats = RejectionStats()
        stats.active_universe_count = 78
        stats.selected_symbol_count = 74
        stats.universe_selection_source = "scanner_universe"
        out = stats.to_dict()
        self.assertEqual(out["active_universe_count"], 78)
        self.assertEqual(out["selected_symbol_count"], 74)
        self.assertEqual(out["universe_selection_source"], "scanner_universe")


class TestUniverseSelectionHandoff(unittest.TestCase):
    def test_db_selection_records_active_and_selected(self):
        rows = [
            {
                "symbol": "SPY",
                "earnings_date": None,
                "liquidity_score": 100,
                "avg_volume_30d": 1_000_000,
            },
            {
                "symbol": "QQQ",
                "earnings_date": None,
                "liquidity_score": 99,
                "avg_volume_30d": 900_000,
            },
        ]
        service = UniverseService(_Supabase(rows))
        selected = service.get_scan_candidates(limit=1, caller="test")
        self.assertEqual([r["symbol"] for r in selected], ["SPY"])
        self.assertEqual(
            service.last_selection_counts,
            {
                "active_universe_count": 2,
                "selected_symbol_count": 1,
                "selection_source": "scanner_universe",
            },
        )

    def test_db_failure_types_active_count_unknown(self):
        service = UniverseService(_Supabase(error=RuntimeError("db down")))
        selected = service.get_scan_candidates(limit=2, caller="test")
        self.assertEqual(len(selected), 2)
        self.assertIsNone(
            service.last_selection_counts["active_universe_count"]
        )
        self.assertEqual(
            service.last_selection_counts["selection_source"], "fallback"
        )


if __name__ == "__main__":
    unittest.main()
