"""Regression: the scanner candidate_dict's ``execution_cost_source_used`` must
carry the SOURCE STRING ("history"/"proxy"), never the samples COUNT.

L5 (Fable Saturday-Evening review, ledgered LOW): ``options_scanner.py`` built
the candidate with::

    "execution_cost_source_used": cost_details["execution_cost_samples_used"],  # BUG
    "execution_cost_samples_used": cost_details["execution_cost_samples_used"],

— i.e. the SOURCE field was populated from the samples COUNT key, so a proxy
candidate carried ``execution_cost_source_used == 0`` (an int) instead of
``"proxy"``. The #1265 scanner cost capture
(``build_scanner_cost_capture`` → ``scanner_cost_basis_capture``) reads the
CORRECT raw keys and was unaffected; the fix restores the source string on the
top-level candidate field while leaving the samples field (already correct)
untouched.

Test doctrine (CLAUDE.md §9, v1.4 07-12): drive the PRODUCTION route, inject at
the ORIGIN, assert at the TOP; no source-string pins.

  - ``TestCandidateExecutionCostFields`` drives the REAL
    ``scan_for_opportunities`` end-to-end (via the canonical
    ``test_lifecycle_fail_closed_route`` harness, whose healthy path emits a
    candidate) and asserts the emitted candidate's TOP-LEVEL cost fields.
      * proxy path — the real scanner hardcodes ``drag_map={}``
        (options_scanner.py:2920), so the live candidate ALWAYS takes the proxy
        branch: source == "proxy" (str), samples == 0 (int).
      * history path — reachable only by injecting a history-shaped
        ``cost_details`` at its ORIGIN (``_determine_execution_cost``, the exact
        function the candidate copies from). The wrapper calls the real function
        and flips ONLY the two label fields, so the cost number is unchanged and
        the candidate still emits; the assertion is on the TOP-LEVEL candidate.
  - ``TestDetermineExecutionCostOrigin`` pins the source+samples PAIR the
    candidate copies, at the determination origin, for all three paths
    (proxy-wins-with-stats, history-wins, no-stats fallback).
  - ``TestScannerCostCaptureUnaffected`` proves #1265's capture keeps reading
    the correct raw keys for proxy AND history cost_details (its own suite,
    test_cost_reconciliation_scanner_basis.py, stays green).
"""

import unittest
from unittest.mock import patch

import packages.quantum.options_scanner as scanner_mod
from packages.quantum.options_scanner import (
    _determine_execution_cost,
    build_scanner_cost_capture,
)
from packages.quantum.tests.test_lifecycle_fail_closed_route import (
    _run_scan,
    FakeSupabase,
    STRATEGY,
)

_LIVE_FULL_ROWS = [{"strategy_name": STRATEGY, "current_state": "live_full"}]


# ── the production route: real scan_for_opportunities → candidate_dict ───────
class TestCandidateExecutionCostFields(unittest.TestCase):
    def _emit_candidate(self):
        candidates, rej_stats = _run_scan(FakeSupabase(lifecycle_rows=_LIVE_FULL_ROWS))
        # Guard against fixture drift: a broken harness (0 candidates) must not
        # let a source assertion pass vacuously.
        self.assertEqual(
            len(candidates), 1,
            f"harness must emit exactly one candidate; "
            f"rejections={rej_stats.to_dict()['rejection_counts']}",
        )
        return candidates[0]

    def test_proxy_path_candidate_carries_source_string_not_count(self):
        """The real scan (drag_map empty → proxy branch) must stamp the SOURCE
        STRING on ``execution_cost_source_used``. Pre-fix this field held the
        samples count (0), so the string assertion catches the mislabel."""
        cand = self._emit_candidate()
        self.assertEqual(cand["execution_cost_source_used"], "proxy")
        self.assertIsInstance(cand["execution_cost_source_used"], str)
        # The samples field is preserved and remains the (int) count.
        self.assertEqual(cand["execution_cost_samples_used"], 0)
        self.assertIsInstance(cand["execution_cost_samples_used"], int)

    def test_source_field_is_not_the_samples_count(self):
        """The core mislabel signature: the two fields must be DISTINCT — a
        source string, not a duplicate of the numeric samples count."""
        cand = self._emit_candidate()
        self.assertNotEqual(
            cand["execution_cost_source_used"],
            cand["execution_cost_samples_used"],
            "source field must not mirror the samples count (the L5 mislabel)",
        )
        self.assertIn(cand["execution_cost_source_used"], ("history", "proxy"))

    def test_candidate_source_matches_the_capture_block(self):
        """End-to-end coherence: the top-level source field and #1265's capture
        block (which was always correct) must now agree."""
        cand = self._emit_candidate()
        est = cand["scanner_cost_basis_capture"]["scanner_estimate"]
        self.assertEqual(cand["execution_cost_source_used"], est["source_used"])
        self.assertEqual(cand["execution_cost_samples_used"], est["samples_used"])
        self.assertEqual(est["source_used"], "proxy")

    def test_history_path_candidate_carries_history_source(self):
        """ORIGIN INJECTION: a history-source ``cost_details`` (source flipped
        at ``_determine_execution_cost``, cost number preserved so the candidate
        still emits) must surface as the SOURCE STRING on the candidate, with
        the samples COUNT in its own field. Pre-fix, source would be the int 9
        (the samples count) — so ``== "history"`` fails pre-fix."""
        real_fn = scanner_mod._determine_execution_cost

        def _history_cost(*args, **kwargs):
            cd = dict(real_fn(*args, **kwargs))
            cd["execution_cost_source_used"] = "history"
            cd["execution_cost_samples_used"] = 9
            return cd

        with patch.object(scanner_mod, "_determine_execution_cost", _history_cost):
            candidates, rej_stats = _run_scan(
                FakeSupabase(lifecycle_rows=_LIVE_FULL_ROWS))
        self.assertEqual(
            len(candidates), 1,
            f"history-injected harness must still emit; "
            f"rejections={rej_stats.to_dict()['rejection_counts']}",
        )
        cand = candidates[0]
        self.assertEqual(cand["execution_cost_source_used"], "history")
        self.assertIsInstance(cand["execution_cost_source_used"], str)
        self.assertEqual(cand["execution_cost_samples_used"], 9)
        # And the capture block agrees (it reads the same raw keys).
        est = cand["scanner_cost_basis_capture"]["scanner_estimate"]
        self.assertEqual(est["source_used"], "history")
        self.assertEqual(est["samples_used"], 9)


# ── the origin: _determine_execution_cost source+samples pairing ─────────────
class TestDetermineExecutionCostOrigin(unittest.TestCase):
    """The candidate copies ``execution_cost_source_used`` /
    ``execution_cost_samples_used`` verbatim from ``_determine_execution_cost``.
    Pin the source+samples PAIR the copy depends on, per path."""

    def test_history_wins(self):
        # avg_drag 12.0 > proxy → history wins, samples surfaced.
        cd = _determine_execution_cost(
            drag_map={"SOFI": {"avg_drag": 12.0, "n": 9}}, symbol="SOFI",
            combo_width_share=0.10, num_legs=2, is_limit=True,
        )
        self.assertEqual(cd["execution_cost_source_used"], "history")
        self.assertEqual(cd["execution_cost_samples_used"], 9)

    def test_proxy_wins_when_stats_present_but_proxy_higher(self):
        # avg_drag tiny → proxy (bigger) wins; samples reset to 0.
        cd = _determine_execution_cost(
            drag_map={"SOFI": {"avg_drag": 0.01, "n": 9}}, symbol="SOFI",
            combo_width_share=0.10, num_legs=2, is_limit=True,
        )
        self.assertEqual(cd["execution_cost_source_used"], "proxy")
        self.assertEqual(cd["execution_cost_samples_used"], 0)

    def test_no_stats_fallback_is_proxy_zero(self):
        # Empty drag_map (the production scanner's hardcoded case) → proxy/0.
        cd = _determine_execution_cost(
            drag_map={}, symbol="SOFI",
            combo_width_share=0.10, num_legs=2, is_limit=True,
        )
        self.assertEqual(cd["execution_cost_source_used"], "proxy")
        self.assertEqual(cd["execution_cost_samples_used"], 0)


# ── #1265 capture reads the correct RAW keys (unaffected by the mislabel) ────
class TestScannerCostCaptureUnaffected(unittest.TestCase):
    def _capture(self, drag_map):
        cd = _determine_execution_cost(
            drag_map=drag_map, symbol="SOFI",
            combo_width_share=0.10, num_legs=2, is_limit=True,
        )
        cap = build_scanner_cost_capture(
            expected_execution_cost=cd["expected_execution_cost"],
            cost_details=cd, unified_execution_cost=7.25,
            combo_width_share=0.10, num_legs=2, is_limit_order=True,
        )
        return cd, cap

    def test_capture_proxy_reads_source_string_and_zero_samples(self):
        cd, cap = self._capture({})
        est = cap["scanner_estimate"]
        # The capture's source_used comes from the SOURCE key, not the count.
        self.assertEqual(est["source_used"], cd["execution_cost_source_used"])
        self.assertEqual(est["samples_used"], cd["execution_cost_samples_used"])
        self.assertEqual(est["source_used"], "proxy")
        self.assertEqual(est["samples_used"], 0)

    def test_capture_history_reads_source_string_and_count(self):
        cd, cap = self._capture({"SOFI": {"avg_drag": 12.0, "n": 9}})
        est = cap["scanner_estimate"]
        self.assertEqual(est["source_used"], "history")
        self.assertEqual(est["samples_used"], 9)


if __name__ == "__main__":
    unittest.main()
