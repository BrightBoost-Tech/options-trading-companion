"""PR3 (#62a-D4-PR3) — clone-builder symbol field removal.

trade_suggestions schema has 'ticker' (NOT NULL); 'symbol' is not
a column. Inserting clone dicts with 'symbol' present errors at
the DB layer ("column symbol does not exist"), which silently
blocked Conservative + Neutral cohort fan-out for ~30 days.

Two layers of test:
1. Source-level structural — catches re-add via copy-paste
2. Behavioral — invokes _clone_suggestion_for_cohort and asserts
   'symbol' is not a key in the returned dict (catches AST-level
   regressions where someone adds the field via different syntax)
"""

import ast
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).parent.parent


class TestSourceLevelSymbolFieldRemoved(unittest.TestCase):
    """Source-level: clone-builder dict literal must not contain
    'symbol' field. trade_suggestions has no such column."""

    def test_clone_dict_does_not_emit_symbol_field(self):
        src = (REPO_ROOT / "policy_lab" / "fork.py").read_text(encoding="utf-8")
        self.assertNotIn(
            '"symbol": source.get("symbol")', src,
            "fork.py clone builder must not include 'symbol' in "
            "returned dict — trade_suggestions has no 'symbol' "
            "column. See #62a-D4-PR3.",
        )

    def test_module_parses(self):
        src = (REPO_ROOT / "policy_lab" / "fork.py").read_text(encoding="utf-8")
        try:
            ast.parse(src)
        except SyntaxError as e:
            self.fail(f"policy_lab/fork.py has a syntax error: {e}")

    def test_ticker_field_still_present(self):
        """Sanity: removing 'symbol' must not have collateral-removed
        'ticker' (the correct field that the schema requires)."""
        src = (REPO_ROOT / "policy_lab" / "fork.py").read_text(encoding="utf-8")
        self.assertIn(
            '"ticker": source.get("ticker")', src,
            "Clone builder must still emit 'ticker' field "
            "(trade_suggestions.ticker is NOT NULL).",
        )


class TestBehavioralSymbolNotInCloneDict(unittest.TestCase):
    """Behavioral: invoke _clone_suggestion_for_cohort with a source
    dict that intentionally includes a 'symbol' key. Assert the
    returned clone does NOT propagate that key.

    Catches AST-level regressions where someone re-adds the field
    via a different syntax shape (e.g., dict update, conditional
    insert) that the source-level grep wouldn't catch."""

    def test_clone_dict_has_no_symbol_key(self):
        from packages.quantum.policy_lab.fork import _clone_suggestion_for_cohort
        from packages.quantum.policy_lab.config import PolicyConfig

        # Source dict mirrors a trade_suggestions row shape; includes
        # 'symbol' explicitly so we can verify it does NOT propagate.
        source = {
            "user_id": "test_user",
            "window": "morning_limit",
            "ticker": "AAPL",
            "symbol": "should_not_propagate",  # ← if leaked, regression
            "strategy": "long_call_debit_spread",
            "direction": "long",
            "ev": 0.05,
            "risk_adjusted_ev": 0.04,
            "order_json": {"contracts": 1},
            "sizing_metadata": {"max_loss_total": 200.0},
            "cycle_date": "2026-04-30",
            "legs_fingerprint": "fp123",
            "trace_id": "trace_abc",
            "model_version": "v1",
            "features_hash": "fh123",
            "regime": "NORMAL",
            "decision_lineage": {},
            "lineage_hash": "lh123",
            "agent_signals": {},
            "agent_summary": {},
        }

        clone = _clone_suggestion_for_cohort(
            source=source,
            cohort_name="conservative",
            config=PolicyConfig(),
            deployable_capital=500.0,
        )

        self.assertIsNotNone(
            clone,
            "Clone builder returned None — fixture may be missing a "
            "required field. Adjust fixture to match production shape.",
        )
        self.assertNotIn(
            "symbol", clone,
            "Clone dict must not have 'symbol' key — would cause DB "
            "insert error since trade_suggestions has no such column.",
        )
        # Sanity: ticker IS present and correct
        self.assertEqual(clone.get("ticker"), "AAPL")
        # Sanity: cohort_name is set correctly
        self.assertEqual(clone.get("cohort_name"), "conservative")


if __name__ == "__main__":
    unittest.main()
