"""Tests for #113 PR-6 — per-strategy emission counts + per-(strategy,
reason) rejection counts in scanner observability.

Three layers:
1. ``RejectionStats`` API contract: new ``record_emission`` method,
   strategy-aware ``record`` / ``record_with_sample`` kwarg,
   ``to_dict`` envelope shape.
2. Backward compatibility: callers passing no ``strategy`` still
   work; counts attribute to ``__pre_strategy__`` sentinel.
3. Source-level structural guards on the scanner instrumentation
   sites (lifecycle gate, hold/cash verdict, banned policy,
   emission point, end-of-cycle summary log).
"""

import unittest
from pathlib import Path

from packages.quantum.options_scanner import RejectionStats


SCANNER_PATH = (
    Path(__file__).parent.parent / "options_scanner.py"
)


class TestRejectionStatsStrategyDimension(unittest.TestCase):
    """RejectionStats gains per-strategy emission + rejection counts.

    Backward-compat invariant: every test that used the legacy
    no-kwarg API in PR-867 still works.
    """

    def test_record_with_strategy_attributes_to_strategy(self):
        rs = RejectionStats()
        rs.record("iv_rank_too_low", strategy="LONG_CALL_DEBIT_SPREAD")
        d = rs.to_dict()
        self.assertEqual(
            d["rejection_counts_by_strategy_and_reason"],
            {"LONG_CALL_DEBIT_SPREAD": {"iv_rank_too_low": 1}},
        )
        # Legacy per-reason histogram still updated
        self.assertEqual(d["rejection_counts"], {"iv_rank_too_low": 1})

    def test_record_without_strategy_attributes_to_pre_strategy_sentinel(self):
        rs = RejectionStats()
        rs.record("missing_quotes")  # legacy no-kwarg call
        d = rs.to_dict()
        self.assertEqual(
            d["rejection_counts_by_strategy_and_reason"],
            {RejectionStats.PRE_STRATEGY_KEY: {"missing_quotes": 1}},
        )

    def test_mixed_pre_strategy_and_strategy_known_rejections(self):
        rs = RejectionStats()
        rs.record("missing_quotes")  # pre-strategy
        rs.record("iv_rank_too_low", strategy="LONG_CALL_DEBIT_SPREAD")
        rs.record("iv_rank_too_low", strategy="LONG_CALL_DEBIT_SPREAD")
        rs.record("regime_not_chop", strategy="IRON_CONDOR")
        d = rs.to_dict()
        self.assertEqual(
            d["rejection_counts_by_strategy_and_reason"],
            {
                RejectionStats.PRE_STRATEGY_KEY: {"missing_quotes": 1},
                "LONG_CALL_DEBIT_SPREAD": {"iv_rank_too_low": 2},
                "IRON_CONDOR": {"regime_not_chop": 1},
            },
        )
        self.assertEqual(d["total_rejections"], 4)

    def test_record_with_sample_supports_strategy_kwarg(self):
        rs = RejectionStats()
        rs.record_with_sample(
            "condor_no_credit",
            {"symbol": "AAPL", "credit": 0.0},
            strategy="IRON_CONDOR",
        )
        d = rs.to_dict()
        self.assertEqual(
            d["rejection_counts_by_strategy_and_reason"]["IRON_CONDOR"],
            {"condor_no_credit": 1},
        )
        # Sample preserves the strategy attribution
        self.assertEqual(d["rejection_samples"][0]["strategy"], "IRON_CONDOR")
        self.assertEqual(d["rejection_samples"][0]["reason"], "condor_no_credit")

    def test_record_emission_increments_per_strategy_counter(self):
        rs = RejectionStats()
        rs.record_emission("LONG_CALL_DEBIT_SPREAD")
        rs.record_emission("LONG_CALL_DEBIT_SPREAD")
        rs.record_emission("IRON_CONDOR")
        d = rs.to_dict()
        self.assertEqual(
            d["emission_counts_by_strategy"],
            {"LONG_CALL_DEBIT_SPREAD": 2, "IRON_CONDOR": 1},
        )

    def test_emission_counts_empty_when_no_emissions(self):
        rs = RejectionStats()
        rs.record("missing_quotes")  # rejected but not emitted
        d = rs.to_dict()
        self.assertEqual(d["emission_counts_by_strategy"], {})

    def test_to_dict_envelope_keys(self):
        """to_dict must include the two new dimension keys plus all
        legacy keys for backward compat."""
        rs = RejectionStats()
        d = rs.to_dict()
        legacy_keys = {
            "rejection_counts", "symbols_processed", "chains_loaded",
            "chains_empty", "total_rejections", "rejection_samples",
            "rejection_samples_cap",
        }
        new_keys = {
            "emission_counts_by_strategy",
            "rejection_counts_by_strategy_and_reason",
        }
        self.assertTrue(legacy_keys.issubset(d.keys()))
        self.assertTrue(new_keys.issubset(d.keys()))

    def test_concurrent_increments_thread_safe(self):
        """RejectionStats is shared across the scanner's
        ThreadPoolExecutor. Concurrent record + record_emission calls
        must not lose updates.
        """
        import threading
        rs = RejectionStats()
        N = 100
        threads = []

        def worker():
            for _ in range(N):
                rs.record("dte_out_of_range", strategy="LONG_CALL_DEBIT_SPREAD")
                rs.record_emission("IRON_CONDOR")

        for _ in range(4):
            t = threading.Thread(target=worker)
            threads.append(t)
            t.start()
        for t in threads:
            t.join()

        d = rs.to_dict()
        self.assertEqual(
            d["rejection_counts_by_strategy_and_reason"]["LONG_CALL_DEBIT_SPREAD"][
                "dte_out_of_range"
            ],
            4 * N,
        )
        self.assertEqual(d["emission_counts_by_strategy"]["IRON_CONDOR"], 4 * N)


class TestScannerInstrumentation(unittest.TestCase):
    """Source-level structural guards on the scanner emission +
    rejection sites that #113 PR-6 instruments.
    """

    @classmethod
    def setUpClass(cls):
        cls.src = SCANNER_PATH.read_text(encoding="utf-8")

    def test_emission_counter_at_candidate_dict_return(self):
        """Emission must increment right before the successful return
        of process_symbol — not before agent veto, not after the dict
        is built and discarded.
        """
        anchor = self.src.find('rej_stats.record_emission(')
        self.assertGreater(anchor, 0)
        # The emission call should be on the line immediately preceding
        # `return candidate_dict` — search forward up to ~200 chars.
        window = self.src[anchor:anchor + 300]
        self.assertIn("return candidate_dict", window)

    def test_lifecycle_filter_attributes_to_strategy(self):
        """The designed/deprecated filter (#110) is now strategy-aware
        for #113."""
        anchor = self.src.find('"designed", "deprecated"')
        self.assertGreater(anchor, 0)
        window = self.src[anchor:anchor + 400]
        self.assertIn("rej_stats.record(", window)
        self.assertIn("strategy=suggestion", window)

    def test_hold_cash_verdict_attributes_to_strategy(self):
        """strategy_hold_explicit_verdict carries strategy attribution
        because suggestion['strategy'] is in scope.
        """
        anchor = self.src.find('"strategy_hold_explicit_verdict"')
        self.assertGreater(anchor, 0)
        window = self.src[anchor:anchor + 400]
        self.assertIn("strategy=suggestion[", window)

    def test_cycle_summary_log_emitted(self):
        """End-of-cycle structured log line carries both count
        dimensions and total fields.
        """
        self.assertIn("scanner_cycle_emission_summary", self.src)
        # Must be near the cycle return, not in some other context
        anchor = self.src.find("scanner_cycle_emission_summary")
        # Find the surrounding log call window
        window = self.src[anchor:anchor + 800]
        self.assertIn("emission_counts_by_strategy", window)
        self.assertIn("rejection_counts_by_strategy_and_reason", window)
        self.assertIn("total_emitted", window)
        self.assertIn("total_rejected", window)


class TestPreStrategyKeySentinel(unittest.TestCase):
    """The PRE_STRATEGY_KEY sentinel must remain stable; operator
    queries depend on it as a documented key.
    """

    def test_sentinel_value(self):
        self.assertEqual(RejectionStats.PRE_STRATEGY_KEY, "__pre_strategy__")


if __name__ == "__main__":
    unittest.main()
