"""D2 Phase 1 harness — row-builder + MANDATORY isolation tests.

OBSERVATION-ONLY: momentum signals/tempers are logged, never applied to the real
EV/score/ranking/selection. These prove:
  (A) row builder logs the ACTUAL (unchanged) ev/score/rank alongside the would-be
      tempers, skipping suggestions without signals;
  (B) ISOLATION — attaching momentum_signals (even an extreme run-up that a temper
      would heavily discount) does NOT change canonical_ranker's score, so the
      ranker/selection is unaffected (the real logic wins; momentum is log-only).
"""

import unittest

from packages.quantum.services.workflow_orchestrator import (
    build_momentum_observation_rows,
)
from packages.quantum.analytics.canonical_ranker import compute_risk_adjusted_ev


def _inserted(suggestion_id, ev, score, signals, status="pending", raev=0.03):
    return {
        "suggestion_id": suggestion_id,
        "original": {
            "ticker": "F",
            "ev": ev,
            "risk_adjusted_ev": raev,
            "status": status,
            "sizing_metadata": {"score": score},
            "internal_cand": {"momentum_signals": signals} if signals else {},
        },
    }


_HIGH_MOM = {
    "direction": "bullish",
    "signed_run_up_in_direction": 0.40,  # +40% already ran our way
    "dist_from_sma20": 0.20,
    "rsi": 80.0,
    "momentum_following": True,
}


class TestRowBuilder(unittest.TestCase):
    def test_logs_actual_and_tempers(self):
        rows = build_momentum_observation_rows(
            "u1", "2026-05-28", [_inserted("s1", ev=100.0, score=80.0, signals=_HIGH_MOM)]
        )
        self.assertEqual(len(rows), 1)
        r = rows[0]
        # ACTUAL values logged unchanged:
        self.assertEqual(r["actual_ev"], 100.0)
        self.assertEqual(r["actual_score"], 80.0)
        self.assertEqual(r["actual_risk_adjusted_ev"], 0.03)
        self.assertEqual(r["actual_status"], "pending")
        self.assertEqual(r["suggestion_id"], "s1")
        # Tempers present as SEPARATE would-be values (discounted, never applied):
        self.assertIn("T1", r["tempers"])
        self.assertLess(r["tempers"]["T1"]["would_be_ev"], 100.0)

    def test_skips_suggestions_without_signals(self):
        rows = build_momentum_observation_rows(
            "u1", "2026-05-28", [_inserted("s1", ev=100.0, score=80.0, signals=None)]
        )
        self.assertEqual(rows, [])

    def test_handles_empty(self):
        self.assertEqual(build_momentum_observation_rows("u1", "2026-05-28", []), [])
        self.assertEqual(build_momentum_observation_rows("u1", "2026-05-28", None), [])


class TestRankerIsolation(unittest.TestCase):
    """MANDATORY: momentum has NO effect on the ranker's selection metric."""

    def _suggestion(self, with_momentum):
        s = {
            "ticker": "F",
            "ev": 100.0,
            "sizing_metadata": {"contracts": 5, "max_loss_total": 480.0, "score": 80.0},
        }
        if with_momentum:
            # Extreme momentum-following signal a temper would heavily discount.
            s["momentum_signals"] = _HIGH_MOM
        return s

    def test_ranker_ignores_momentum_signals(self):
        budget = 1531.0
        raev_base = compute_risk_adjusted_ev(self._suggestion(False), [], budget)
        raev_mom = compute_risk_adjusted_ev(self._suggestion(True), [], budget)
        # Identical: attaching momentum_signals does not change the ranking metric,
        # so candidate selection/ordering is unaffected. Momentum is log-only.
        self.assertEqual(raev_base, raev_mom)


if __name__ == "__main__":
    unittest.main()
