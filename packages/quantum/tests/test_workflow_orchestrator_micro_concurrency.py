"""Source-level structural assertions for the micro-tier concurrency
gate (2026-04-27).

Operator spec: under $1000 capital (micro tier), only one open
position at a time. Asymmetric implementation:

  - run_midday_cycle (entries): full gate. Returns
    skipped=True, reason='micro_tier_position_open' when a position
    is already open under micro tier.
  - run_morning_cycle (exits): tier observation log only, NO skip.
    Exits must continue to be generated regardless of position count
    or gating it would dead-lock open positions.

The asymmetry is intentional. TestMorningCycleNoConcurrencyGate
defends against future PRs that "fix" the apparent inconsistency.

Tests are source-level structural (matches H4a/H4b convention) to
avoid triggering the heavy transitive dependency tree of the full
orchestrator import.
"""

import os
import re
import unittest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
ORCHESTRATOR_PATH = os.path.join(
    REPO_ROOT, "packages", "quantum", "services", "workflow_orchestrator.py"
)


def _load_orchestrator_source() -> str:
    with open(ORCHESTRATOR_PATH, "r", encoding="utf-8") as f:
        return f.read()


def _function_block(src: str, fn_name: str, max_chars: int = 8000) -> str:
    """Return a window starting at the function definition.

    The default 8000-char window comfortably covers both run_morning_cycle
    and run_midday_cycle through their post-positions-fetch
    initialization. The midday cycle has ~4000 chars of preamble (parallel
    reads, regime/progression setup) before the concurrency gate; the
    morning cycle similarly has ~3500 chars before the observation log.
    """
    pos = src.find(f"async def {fn_name}")
    assert pos >= 0, f"Could not locate {fn_name} definition"
    return src[pos:pos + max_chars]


class TestMiddayCycleConcurrencyGate(unittest.TestCase):
    """Midday cycle has the full concurrency gate."""

    def setUp(self):
        self.src = _load_orchestrator_source()
        self.midday_block = _function_block(self.src, "run_midday_cycle")

    def test_midday_uses_smallaccountcompounder_get_tier(self):
        self.assertIn(
            "SmallAccountCompounder.get_tier(deployable_capital)",
            self.midday_block,
            "Midday cycle must call SmallAccountCompounder.get_tier "
            "to determine tier.max_trades.",
        )

    def test_midday_checks_max_trades_eq_1(self):
        self.assertIn(
            "max_trades == 1",
            self.midday_block,
            "Midday cycle must check tier.max_trades == 1 for the "
            "concurrency gate.",
        )

    def test_midday_checks_open_positions(self):
        self.assertIn(
            "len(positions) >= 1",
            self.midday_block,
            "Midday cycle must check open position count.",
        )

    def test_midday_returns_skipped_with_reason(self):
        self.assertIn(
            '"reason": "micro_tier_position_open"',
            self.midday_block,
            "Midday cycle gate must return reason='micro_tier_position_open'.",
        )
        self.assertIn(
            '"skipped": True',
            self.midday_block,
            "Midday cycle gate must return skipped=True.",
        )

    def test_midday_gate_emits_skip_log(self):
        self.assertIn(
            "[Midday] Skipped: micro tier",
            self.midday_block,
            "Midday cycle must log the skip with [Midday] Skipped prefix.",
        )


class TestMorningCycleNoConcurrencyGate(unittest.TestCase):
    """Morning cycle has tier observation only — no skip, no gate.

    REGRESSION GUARD: this test class explicitly defends the asymmetric
    design. If a future PR adds a concurrency gate to morning cycle
    (mistakenly believing it should match midday), these tests catch
    it. The asymmetry is intentional: morning cycle generates exit
    suggestions for existing positions; gating it would prevent
    auto-exits and dead-lock open positions.
    """

    def setUp(self):
        self.src = _load_orchestrator_source()
        # Morning cycle is large; pull a generous window.
        self.morning_block = _function_block(
            self.src, "run_morning_cycle", max_chars=8000,
        )

    def test_morning_emits_observation_log(self):
        self.assertIn(
            "[Morning] tier=",
            self.morning_block,
            "Morning cycle must emit a tier observation log line.",
        )
        self.assertIn(
            "exits_continuing",
            self.morning_block,
            "Morning cycle observation must include 'exits_continuing' "
            "marker for parity with midday gate logs.",
        )

    def test_morning_does_not_skip_on_position_count(self):
        # The morning cycle must NOT contain the midday gate's skip
        # reason. If a future edit copies the midday gate over, this
        # fails immediately.
        self.assertNotIn(
            "micro_tier_position_open",
            self.morning_block,
            "REGRESSION: morning cycle must not contain "
            "'micro_tier_position_open'. Morning is exits-only and "
            "must run regardless of position count. See CLAUDE.md "
            "'Concurrency policy (micro tier)' section.",
        )

    def test_morning_does_not_return_skipped_for_micro_tier(self):
        # Defensive: scan for any 'reason.*micro' return in morning.
        # Allow the observation log line itself (which contains
        # "tier=micro") but no return statement that skips on it.
        skip_pattern = re.compile(
            r'return\s*\{[^}]*"reason"\s*:\s*"micro',
            re.DOTALL,
        )
        match = skip_pattern.search(self.morning_block)
        self.assertIsNone(
            match,
            "REGRESSION: morning cycle must not return a "
            "skipped=True dict with a micro-tier reason. "
            "Found: " + (match.group(0) if match else "<none>"),
        )

    def test_morning_uses_get_tier_for_observation(self):
        self.assertIn(
            "SmallAccountCompounder.get_tier(deployable_capital)",
            self.morning_block,
            "Morning cycle must resolve tier for the observation log.",
        )


class TestModuleSyntaxValid(unittest.TestCase):
    """workflow_orchestrator.py parses cleanly post-edit."""

    def test_module_parses(self):
        import ast

        src = _load_orchestrator_source()
        try:
            ast.parse(src)
        except SyntaxError as e:
            self.fail(f"workflow_orchestrator.py has a syntax error: {e}")


if __name__ == "__main__":
    unittest.main()
