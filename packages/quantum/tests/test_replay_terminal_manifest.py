"""PR-③ E16: a terminal decision manifest is captured at EVERY return of the
midday cycle — including the ZERO-suggestion / no-trade path (the dominant shape
at the ×0.5 floor). Drives the shared helper both return paths call, with the
zero-cycle inputs, and asserts honest zeros + reject reasons. Fail-soft preserved.
"""
import os
import unittest
from datetime import datetime, timezone

from packages.quantum.services.workflow_orchestrator import _capture_decision_manifest


class _RejStats:
    def to_dict(self):
        return {"spread_too_wide_real": 3, "execution_cost_exceeds_ev": 2}


class TestTerminalManifest(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("REPLAY_ENABLE", None)

    def _ctx(self):
        from packages.quantum.services.replay.decision_context import DecisionContext
        return DecisionContext(strategy_name="suggestions_open",
                               as_of_ts=datetime.now(timezone.utc),
                               user_id="u1", git_sha="abc")

    def _manifest(self, ctx):
        feats = [f for f in ctx.features
                 if f.symbol == "__decision__" and f.namespace == "ranked_candidates"]
        self.assertEqual(len(feats), 1)
        return feats[0].features

    def test_zero_cycle_manifest_has_honest_zeros(self):
        os.environ["REPLAY_ENABLE"] = "1"
        ctx = self._ctx(); ctx.__enter__()
        try:
            _capture_decision_manifest(
                [], _RejStats(),
                {"scanner_emitted": 78, "candidates": 4, "created": 0},
                "no_suggestions_after_gates", "2026-07-13")
            m = self._manifest(ctx)
            self.assertEqual(m["count"], 0)
            self.assertTrue(m["is_zero_cycle"])
            self.assertEqual(m["exit_reason"], "no_suggestions_after_gates")
            self.assertEqual(m["rejected_summary"]["spread_too_wide_real"], 3)
            self.assertEqual(m["counts"]["scanner_emitted"], 78)
            self.assertEqual(m["candidates"], [])
        finally:
            ctx.__exit__(None, None, None)

    def test_accepted_cycle_ranks_and_carries_rejects(self):
        os.environ["REPLAY_ENABLE"] = "1"
        ctx = self._ctx(); ctx.__enter__()
        try:
            accepted = [
                {"ticker": "SOFI", "strategy": "debit_spread", "risk_adjusted_ev": 5,
                 "status": "pending", "blocked_reason": None},
                {"ticker": "QQQ", "strategy": "iron_condor", "risk_adjusted_ev": 20,
                 "status": "pending", "blocked_reason": None},
            ]
            _capture_decision_manifest(accepted, _RejStats(), {"created": 2},
                                       "suggestions_created", "2026-07-13")
            m = self._manifest(ctx)
            self.assertEqual(m["count"], 2)
            self.assertFalse(m["is_zero_cycle"])
            self.assertEqual(m["candidates"][0]["ticker"], "QQQ")   # ranked risk_adjusted_ev desc
            self.assertEqual(m["rejected_summary"]["execution_cost_exceeds_ev"], 2)
        finally:
            ctx.__exit__(None, None, None)

    def test_replay_off_noop_no_raise(self):
        os.environ.pop("REPLAY_ENABLE", None)
        _capture_decision_manifest([], None, {}, "x", "2026-07-13")  # no context → no-op

    def test_capture_failure_is_fail_soft(self):
        os.environ["REPLAY_ENABLE"] = "1"
        ctx = self._ctx(); ctx.__enter__()
        try:
            class _Bad:
                def to_dict(self):
                    raise RuntimeError("boom")
            # a broken rejection_stats must be swallowed — the cycle never breaks
            _capture_decision_manifest([], _Bad(), {}, "x", "2026-07-13")
        finally:
            ctx.__exit__(None, None, None)


if __name__ == "__main__":
    unittest.main()
