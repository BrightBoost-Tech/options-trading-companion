"""Replay Phase-1 gap-(c): decision-output capture + decision_id linkage.

Pins: the ranked_candidates decision-output stages on the context under the
"__decision__"/"ranked_candidates" key (when replay on); the context accessor
is None when replay off (so the orchestrator capture guard no-ops → byte-
identical); a record_feature failure is swallowed by the orchestrator's
fail-soft wrapper (the invariant the gap-(c) block preserves).
"""
import os
import unittest
from datetime import datetime, timezone


class TestDecisionOutputCapture(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("REPLAY_ENABLE", None)

    def _ctx(self):
        from packages.quantum.services.replay.decision_context import DecisionContext
        return DecisionContext(
            strategy_name="suggestions_open",
            as_of_ts=datetime.now(timezone.utc),
            user_id="u1", git_sha="abc123",
        )

    def test_ranked_candidates_feature_staged_when_on(self):
        os.environ["REPLAY_ENABLE"] = "1"
        ctx = self._ctx()
        ctx.__enter__()
        try:
            ctx.record_feature("__decision__", "ranked_candidates", {
                "count": 2, "cycle_date": "2026-07-13",
                "candidates": [
                    {"ticker": "QQQ", "strategy": "iron_condor", "ev": 1.0,
                     "pop": 0.7, "score": 55.0, "risk_adjusted_ev": 20.0,
                     "status": "pending", "blocked_reason": None,
                     "legs_fingerprint": "fp1"},
                    {"ticker": "SOFI", "strategy": "debit_spread", "ev": 0.5,
                     "pop": 0.6, "score": 40.0, "risk_adjusted_ev": -999,
                     "status": "pending", "blocked_reason": "ev_below_roundtrip_cost",
                     "legs_fingerprint": "fp2"},
                ],
            })
            staged = [f for f in ctx.features
                      if f.symbol == "__decision__" and f.namespace == "ranked_candidates"]
            self.assertEqual(len(staged), 1)
            self.assertEqual(staged[0].features["count"], 2)
            self.assertEqual(staged[0].features["candidates"][1]["blocked_reason"],
                             "ev_below_roundtrip_cost")
        finally:
            ctx.__exit__(None, None, None)

    def test_context_accessor_none_when_off(self):
        os.environ.pop("REPLAY_ENABLE", None)
        from packages.quantum.services.replay.decision_context import (
            get_current_decision_context,
        )
        # replay off → no active context → the orchestrator capture guard no-ops
        self.assertIsNone(get_current_decision_context())


class TestMigrationPresent(unittest.TestCase):
    def test_decision_id_migration_committed(self):
        import re
        from pathlib import Path
        mig = (Path(__file__).resolve().parents[3] / "supabase" / "migrations"
               / "20260712011627_trade_suggestions_decision_id.sql")
        txt = mig.read_text(encoding="utf-8")
        self.assertTrue(re.search(r"ADD COLUMN IF NOT EXISTS decision_id uuid", txt, re.I))


if __name__ == "__main__":
    unittest.main()
