"""Tests for #97 Phase 2 — fresh trace_id per cohort clone.

Phase 1 (PR #859) wired a critical alert at the cloner's INSERT
exception path. Today's first production fire (Tuesday 2026-05-05
16:00:18Z, CSX cycle) classified the root cause:

    error_class:    APIError (postgres 23505 unique violation)
    constraint:     idx_trade_suggestions_trace_id_unique
    error_message:  Key (trace_id)=(7919b18f-...) already exists.

Both alerts (conservative + neutral cohorts) showed the SAME source
trace_id colliding — the cloner at fork.py:287 inherited
`source.get("trace_id")` rather than generating fresh per clone.

The unique index is partial unique on non-null:
    UNIQUE INDEX ... ON trade_suggestions (trace_id) WHERE trace_id IS NOT NULL

Lineage tracking is via separate columns (lineage_hash, lineage_sig,
lineage_version, decision_lineage) — those ARE intentionally inherited
across clones. trace_id is row-unique; this PR enforces that.

Same Layer-1 + Layer-2 shape as `test_fork_clone_dict_symbol_removed.py`
(source-level guard + behavioral invocation).
"""
import re
import unittest
from pathlib import Path


FORK_PATH = (
    Path(__file__).parent.parent / "policy_lab" / "fork.py"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────
# Layer 1 — Source-level guard
# ─────────────────────────────────────────────────────────────────────


class TestCloneNoLongerInheritsTraceId(unittest.TestCase):
    """Source-level guard: catches AST-level regressions where someone
    re-adds `source.get("trace_id")` via a different syntax shape."""

    @classmethod
    def setUpClass(cls):
        cls.src = _read(FORK_PATH)

    def test_uuid_imported(self):
        """The fix uses uuid.uuid4() to generate fresh trace_ids;
        verify the import is present so no NameError surprises."""
        # Match `import uuid` on its own line (top-level), not e.g.
        # `import uuid_mod` or `from uuid import ...`
        self.assertRegex(
            self.src,
            r'(?m)^import uuid$',
            "uuid module must be imported in fork.py for the trace_id "
            "fix",
        )

    def test_clone_does_not_inherit_source_trace_id(self):
        """The bug was `"trace_id": source.get("trace_id")` at fork.py:287.
        Post-fix, that exact pattern must NOT appear inside
        _clone_suggestion_for_cohort. Match it broadly via regex."""
        # Locate the clone function
        m = re.search(
            r'def _clone_suggestion_for_cohort\(.*?(?=^def |^class )',
            self.src,
            re.DOTALL | re.MULTILINE,
        )
        self.assertIsNotNone(
            m, "_clone_suggestion_for_cohort must exist in fork.py",
        )
        clone_body = m.group(0)
        self.assertNotRegex(
            clone_body,
            r'"trace_id":\s*source\.get\(\s*"trace_id"\s*\)',
            "Cloner must NOT inherit source's trace_id — that was the "
            "#97 bug. Each clone needs its own UUID.",
        )

    def test_clone_uses_fresh_uuid_for_trace_id(self):
        """The fix: the cloner sets `trace_id` to a fresh UUID. Match
        the exact pattern str(uuid.uuid4())."""
        m = re.search(
            r'def _clone_suggestion_for_cohort\(.*?(?=^def |^class )',
            self.src,
            re.DOTALL | re.MULTILINE,
        )
        clone_body = m.group(0)
        self.assertRegex(
            clone_body,
            r'"trace_id":\s*str\(\s*uuid\.uuid4\(\s*\)\s*\)',
            "Cloner must set trace_id to str(uuid.uuid4()) per #97 "
            "Phase 2 fix",
        )

    def test_lineage_fields_still_inherited(self):
        """The fix is scoped to trace_id ONLY. Lineage-tracking fields
        (lineage_hash, decision_lineage) MUST still be inherited from
        the source — that's intentional per the schema design."""
        m = re.search(
            r'def _clone_suggestion_for_cohort\(.*?(?=^def |^class )',
            self.src,
            re.DOTALL | re.MULTILINE,
        )
        clone_body = m.group(0)
        self.assertIn(
            'source.get("lineage_hash")', clone_body,
            "lineage_hash must remain inherited from source — it's the "
            "actual lineage key (separate from trace_id which is "
            "row-unique)",
        )
        self.assertIn(
            'source.get("decision_lineage")', clone_body,
            "decision_lineage must remain inherited",
        )

    def test_phase1_alert_wiring_still_present(self):
        """The Phase 1 alert site (PR #859) is the regression canary.
        If the fix is ever reverted or a new failure shape emerges,
        this alert is what surfaces it. MUST remain wired."""
        self.assertIn(
            'cohort_clone_insert_failed', self.src,
            "Phase 1 alert wiring must remain — it's the regression "
            "canary. PR #859 added it; do NOT remove.",
        )


# ─────────────────────────────────────────────────────────────────────
# Layer 2 — Behavioral test
# ─────────────────────────────────────────────────────────────────────


class TestCloneTraceIdBehavior(unittest.TestCase):
    """Invoke _clone_suggestion_for_cohort against a fixture mirroring
    a trade_suggestions row; assert trace_id semantics are correct."""

    def _make_source(self):
        """Source dict mirroring production shape — explicitly sets
        trace_id so we can verify it's NOT inherited."""
        return {
            "user_id": "test-user-97p2",
            "window": "morning_limit",
            "ticker": "CSX",
            "strategy": "long_call_debit_spread",
            "direction": "long",
            "ev": 0.05,
            "risk_adjusted_ev": 0.04,
            "order_json": {"contracts": 1},
            "sizing_metadata": {"max_loss_total": 200.0},
            "cycle_date": "2026-05-05",
            "legs_fingerprint": "fp_97p2",
            "trace_id": "11111111-2222-3333-4444-555555555555",
            "model_version": "v1",
            "features_hash": "fh_97p2",
            "regime": "NORMAL",
            "decision_lineage": {"x": 1},
            "lineage_hash": "lineage_97p2",
            "agent_signals": {},
            "agent_summary": {},
        }

    def test_clone_does_not_inherit_source_trace_id(self):
        """The CSX-class bug: clone's trace_id collides with source's
        trace_id, then second cohort INSERT fails the unique index."""
        from packages.quantum.policy_lab.fork import _clone_suggestion_for_cohort
        from packages.quantum.policy_lab.config import PolicyConfig

        source = self._make_source()
        clone = _clone_suggestion_for_cohort(
            source=source,
            cohort_name="conservative",
            config=PolicyConfig(),
            deployable_capital=500.0,
        )
        self.assertIsNotNone(clone)
        self.assertNotEqual(
            clone["trace_id"], source["trace_id"],
            "Clone trace_id must NOT match source trace_id — the "
            "unique index would reject the second cohort INSERT",
        )

    def test_two_clones_have_distinct_trace_ids(self):
        """Per cohort, each clone gets its own UUID. Two clones from
        the same source must NOT collide either."""
        from packages.quantum.policy_lab.fork import _clone_suggestion_for_cohort
        from packages.quantum.policy_lab.config import PolicyConfig

        source = self._make_source()
        config = PolicyConfig()
        clone_conservative = _clone_suggestion_for_cohort(
            source=source, cohort_name="conservative",
            config=config, deployable_capital=500.0,
        )
        clone_neutral = _clone_suggestion_for_cohort(
            source=source, cohort_name="neutral",
            config=config, deployable_capital=500.0,
        )
        self.assertIsNotNone(clone_conservative)
        self.assertIsNotNone(clone_neutral)
        self.assertNotEqual(
            clone_conservative["trace_id"], clone_neutral["trace_id"],
            "Two cohort clones from the same source must have distinct "
            "trace_ids — this was the exact CSX failure mode "
            "(2026-05-05 16:00:18Z): both clones inherited the same "
            "trace_id, second INSERT collided",
        )

    def test_clone_trace_id_is_valid_uuid(self):
        """Sanity: the generated trace_id is a syntactically valid
        UUID string (for the DB column type)."""
        import uuid as uuid_module
        from packages.quantum.policy_lab.fork import _clone_suggestion_for_cohort
        from packages.quantum.policy_lab.config import PolicyConfig

        source = self._make_source()
        clone = _clone_suggestion_for_cohort(
            source=source,
            cohort_name="conservative",
            config=PolicyConfig(),
            deployable_capital=500.0,
        )
        # uuid.UUID() raises ValueError on invalid syntax
        try:
            uuid_module.UUID(clone["trace_id"])
        except (ValueError, TypeError) as e:
            self.fail(
                f"Clone trace_id '{clone['trace_id']}' is not a valid "
                f"UUID: {e}",
            )

    def test_source_trace_id_not_mutated(self):
        """The fix must NOT mutate the source dict — the original
        suggestion's trace_id stays intact for the source row's own
        identity."""
        from packages.quantum.policy_lab.fork import _clone_suggestion_for_cohort
        from packages.quantum.policy_lab.config import PolicyConfig

        source = self._make_source()
        original_trace_id = source["trace_id"]
        _ = _clone_suggestion_for_cohort(
            source=source,
            cohort_name="conservative",
            config=PolicyConfig(),
            deployable_capital=500.0,
        )
        self.assertEqual(
            source["trace_id"], original_trace_id,
            "Source dict must NOT be mutated — the original "
            "suggestion's trace_id must remain intact",
        )

    def test_lineage_hash_still_inherited(self):
        """Sanity: the fix is scoped to trace_id only; lineage_hash
        is correctly inherited from source (intentional lineage
        propagation)."""
        from packages.quantum.policy_lab.fork import _clone_suggestion_for_cohort
        from packages.quantum.policy_lab.config import PolicyConfig

        source = self._make_source()
        clone = _clone_suggestion_for_cohort(
            source=source,
            cohort_name="conservative",
            config=PolicyConfig(),
            deployable_capital=500.0,
        )
        self.assertEqual(
            clone["lineage_hash"], source["lineage_hash"],
            "lineage_hash must be inherited (intentional lineage "
            "propagation across clones)",
        )

    def test_cohort_name_set_correctly(self):
        """Sanity from existing test pattern."""
        from packages.quantum.policy_lab.fork import _clone_suggestion_for_cohort
        from packages.quantum.policy_lab.config import PolicyConfig

        source = self._make_source()
        clone = _clone_suggestion_for_cohort(
            source=source,
            cohort_name="conservative",
            config=PolicyConfig(),
            deployable_capital=500.0,
        )
        self.assertEqual(clone["cohort_name"], "conservative")


if __name__ == "__main__":
    unittest.main()
