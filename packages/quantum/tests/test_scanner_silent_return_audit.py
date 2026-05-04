"""Tests for #104 — RejectionStats coverage audit of process_symbol +
_process_symbol_multi.

Background
----------
Loud-Error Doctrine v1.0 anti-pattern 4 (per-iteration swallow in tight
loops): every early-return path inside the scanner's per-symbol pipeline
must record a meaningful rejection reason via `rej_stats.record(...)` or
`rej_stats.record_with_sample(...)`. Otherwise diagnostic visibility into
"why did this symbol drop out" degrades silently as new gates are added.

Audit conducted 2026-05-04 against the post-#866 scanner found:

  process_symbol (line 2257):
    All 26 `return None` paths are instrumented (chain by chain — see
    audit table in the PR description). PR #866 closed the last two
    (#105 strategy_hold split + #106 spread_too_wide split).

  _process_symbol_multi (line 3200):
    ONE silent return at line 3219 — `if len(cands) <= 1: return None`
    when the selector produced ≤1 candidate so no fallback retry is
    possible. The primary's rejection reason is already counted by
    process_symbol, but there was no counter measuring "multi-strategy
    mechanism couldn't help because no fallbacks existed." Distinct
    from `all_strategies_rejected` which means fallbacks WERE tried.

This PR adds `rej_stats.record("no_fallback_strategies_available")` at
that site. Observability-only — same trades accepted/rejected as before.
"""

import re
import threading
import unittest
from collections import defaultdict
from pathlib import Path


SCANNER_PATH = (
    Path(__file__).parent.parent / "options_scanner.py"
)


def _read_scanner() -> str:
    return SCANNER_PATH.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────
# Layer 1 — Source-level structural assertions
# ─────────────────────────────────────────────────────────────────────


class TestNoFallbackStrategiesAvailableInstrumented(unittest.TestCase):
    """#104 — silent return at _process_symbol_multi line 3219 fixed."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read_scanner()

    def test_no_fallback_reason_recorded(self):
        """The new rejection reason must be recorded somewhere in the
        scanner. Specifically inside _process_symbol_multi when the
        selector returned ≤1 candidate."""
        self.assertIn(
            'rej_stats.record("no_fallback_strategies_available")',
            self.src,
            "no_fallback_strategies_available must be recorded — see "
            "audit findings in the test docstring",
        )

    def test_record_precedes_no_fallbacks_return(self):
        """The record call must appear BEFORE the `return None  # No
        fallbacks available` line (not after, not in a different
        branch). Window: 600 chars before the return.

        Guards against accidental refactors that move the record into
        a sibling block (e.g., into the fallback loop) where it would
        no longer count the silent path the audit identified.
        """
        return_idx = self.src.find('return None  # No fallbacks available')
        self.assertNotEqual(
            return_idx, -1,
            "The original `return None  # No fallbacks available` "
            "comment marker must remain so this guard keeps anchoring",
        )
        window_start = max(0, return_idx - 600)
        window = self.src[window_start:return_idx]
        self.assertIn(
            'rej_stats.record("no_fallback_strategies_available")',
            window,
            "record() must appear in the 600 chars BEFORE the no-"
            "fallbacks return so it actually fires on the silent path",
        )

    def test_distinct_from_all_strategies_rejected(self):
        """The two reasons cover disjoint cases — both must coexist.
        all_strategies_rejected = primary failed AND fallbacks all
        failed. no_fallback_strategies_available = primary failed AND
        no fallbacks were available to try."""
        self.assertIn(
            'rej_stats.record("all_strategies_rejected")', self.src,
            "all_strategies_rejected must also still be recorded — "
            "the two reasons measure different paths through the "
            "wrapper and the audit only adds, doesn't replace",
        )

    def test_process_symbol_returns_are_all_instrumented(self):
        """Sanity-check the audit finding that process_symbol's return
        paths are fully instrumented. Counts `return None` lines inside
        the function body — every one must have a `rej_stats.record`
        call within the preceding 800 chars (allowing for the longer
        condor-rejection record_with_sample blocks).
        """
        # Locate the `def process_symbol` region (function spans
        # ~940 lines from line 2257 to ~3197 in the post-#866 source).
        ps_start = self.src.find('def process_symbol(symbol: str')
        self.assertNotEqual(ps_start, -1, "process_symbol must exist")
        ps_end = self.src.find(
            '\n    def _process_symbol_multi(', ps_start
        )
        self.assertNotEqual(
            ps_end, -1, "_process_symbol_multi must follow process_symbol"
        )
        body = self.src[ps_start:ps_end]

        # Each `return None` (with optional indent) must have a
        # rej_stats.record OR rej_stats.record_with_sample within
        # the 800 chars preceding it.
        return_positions = [
            m.start() for m in re.finditer(r'\n\s+return None\b', body)
        ]
        self.assertGreater(
            len(return_positions), 20,
            "process_symbol should have >20 early-return paths; "
            "fewer suggests this audit anchor is broken",
        )

        un_instrumented = []
        for pos in return_positions:
            window_start = max(0, pos - 800)
            preceding = body[window_start:pos]
            if ('rej_stats.record(' not in preceding
                    and 'rej_stats.record_with_sample(' not in preceding):
                # Capture the line for reporting
                line_start = body.rfind('\n', 0, pos) + 1
                line_end = body.find('\n', pos + 1)
                un_instrumented.append(
                    body[line_start:line_end].strip()
                )

        self.assertEqual(
            un_instrumented, [],
            f"process_symbol has {len(un_instrumented)} silent "
            f"return(s) that bypass rej_stats — audit regression: "
            f"{un_instrumented}",
        )


# ─────────────────────────────────────────────────────────────────────
# Layer 2 — Behavioral simulation of the wrapper
# ─────────────────────────────────────────────────────────────────────


class _FakeRejStats:
    """Minimal RejectionStats stand-in for behavioral tests. Mirrors
    the production class's record() contract (thread-safe counter)."""

    def __init__(self):
        self._counts = defaultdict(int)
        self._lock = threading.Lock()

    def record(self, reason):
        with self._lock:
            self._counts[reason] += 1

    def count(self, reason):
        with self._lock:
            return self._counts[reason]


def _wrapper_simulator(
    primary_result,
    cands_for_symbol,
    rej_stats,
    multi_eval_enabled=True,
):
    """Mirror of _process_symbol_multi lines 3212-3219 logic. Pure
    function — exercises the silent-return decision without booting
    the scanner's heavy imports (option chains, regime engine, etc.).

    Returns (result, fallbacks_attempted_count).
    """
    result = primary_result
    if result is not None or not multi_eval_enabled:
        return result, 0
    cands = cands_for_symbol
    if len(cands) <= 1:
        rej_stats.record("no_fallback_strategies_available")
        return None, 0
    # Fallback loop omitted — the audit's silent-return concern is
    # before this point. all_strategies_rejected is exercised by
    # existing test_scanner_rejection_stats.py coverage.
    return None, len(cands) - 1


class TestWrapperBehavior(unittest.TestCase):
    """Behavioral tests for the no_fallback_strategies_available path."""

    def test_primary_success_no_record(self):
        """When primary returns a result, no rejection is recorded.
        Sanity-checks the simulator and confirms the record() call is
        only on the silent-return branch."""
        stats = _FakeRejStats()
        result, fb = _wrapper_simulator(
            primary_result={"symbol": "AAPL", "strategy": "x"},
            cands_for_symbol=[],
            rej_stats=stats,
        )
        self.assertIsNotNone(result)
        self.assertEqual(stats.count("no_fallback_strategies_available"), 0)
        self.assertEqual(fb, 0)

    def test_primary_fail_empty_cands_records(self):
        """Sub-case (a) from the comment: primary failed BEFORE line
        2429 populated _multi_strategy_candidates (e.g., HOLD verdict
        recorded earlier). cands == []. Counter must increment."""
        stats = _FakeRejStats()
        result, fb = _wrapper_simulator(
            primary_result=None,
            cands_for_symbol=[],
            rej_stats=stats,
        )
        self.assertIsNone(result)
        self.assertEqual(stats.count("no_fallback_strategies_available"), 1)
        self.assertEqual(fb, 0)

    def test_primary_fail_single_cand_records(self):
        """Sub-case (b) from the comment: selector returned exactly
        one strategy. cands == [primary]. Counter must increment."""
        stats = _FakeRejStats()
        result, fb = _wrapper_simulator(
            primary_result=None,
            cands_for_symbol=[{"strategy": "long_call_debit_spread"}],
            rej_stats=stats,
        )
        self.assertIsNone(result)
        self.assertEqual(stats.count("no_fallback_strategies_available"), 1)
        self.assertEqual(fb, 0)

    def test_primary_fail_multi_cands_no_record(self):
        """When fallbacks are available, the silent-return branch is
        skipped — counter stays at 0. all_strategies_rejected is the
        relevant counter for that path (tested elsewhere)."""
        stats = _FakeRejStats()
        result, fb = _wrapper_simulator(
            primary_result=None,
            cands_for_symbol=[
                {"strategy": "long_call_debit_spread"},
                {"strategy": "long_put_debit_spread"},
                {"strategy": "iron_condor"},
            ],
            rej_stats=stats,
        )
        self.assertIsNone(result)
        self.assertEqual(stats.count("no_fallback_strategies_available"), 0)
        self.assertEqual(fb, 2)

    def test_multi_eval_disabled_short_circuits(self):
        """When MULTI_STRATEGY_EVAL=False, the wrapper returns the
        primary result (None or otherwise) without consulting cands.
        Counter stays at 0 even if cands is empty."""
        stats = _FakeRejStats()
        result, fb = _wrapper_simulator(
            primary_result=None,
            cands_for_symbol=[],
            rej_stats=stats,
            multi_eval_enabled=False,
        )
        self.assertIsNone(result)
        self.assertEqual(stats.count("no_fallback_strategies_available"), 0)
        self.assertEqual(fb, 0)


if __name__ == "__main__":
    unittest.main()
