"""F-A9-5 — cohort-decision logging must report the REAL routing decision.

KNOWN DEFECT (bef2cdd): `_filter_for_cohort` routes on
`sizing_metadata.score` (0-100) vs `config.min_score_threshold` (0-100), but
`_log_cohort_decisions` separately compared dollar-denominated `ev` against
`min_score_threshold`, so `ev_below_min` fired on capacity rejections whose
score PASSED, and genuine score rejections were logged as the generic
`filtered_by_policy` (the real reason erased). The logger re-derived routing
from the wrong quantity.

FIX: one canonical `_evaluate_cohort_policy` result consumed by BOTH the
filter (accepted subset) and the logger (decision rows) — the logger never
recomputes routing. Truthful vocabulary: `score_below_min` (score reject),
`daily_limit_reached`/`max_positions_reached` (capacity), and
`routing_decision_unavailable` (missing/typed predicate evidence).

The route-level class runs RED on bef2cdd and GREEN after the fix (drives the
production entrypoint `fork_suggestions_for_cohorts`, asserts the persisted
`policy_decisions.reason_codes`). The unit class locks the canonical
evaluation function directly.

Scope: legacy cohort routing/logging ONLY. #1200 prerejection eligibility /
clones / verdict semantics / champion tagging / executor / sizing untouched.
"""
import copy
import os
import unittest
import uuid
from unittest.mock import patch

from packages.quantum.policy_lab import fork as fork_mod
from packages.quantum.policy_lab.config import PolicyConfig
from packages.quantum.tests.test_prerejection_fork_e19 import (
    FakeSupabase, UID, _seed,
)


def _pending(ticker, score, ev, fp, sid=None):
    """A pending (legacy, cohort_name=NULL) source suggestion with a chosen
    0-100 `score` and dollar `ev`. score=None → sizing_metadata carries no
    score key (the missing-predicate fixture)."""
    sizing = {"contracts": 1, "max_loss_total": 372.0}
    if score is not None:
        sizing["score"] = score
    return {
        "id": sid or str(uuid.uuid4()), "user_id": UID, "window": "midday_entry",
        "cycle_date": fork_mod.date.today().isoformat(),
        "ticker": ticker, "strategy": "IRON_CONDOR", "direction": "neutral",
        "status": "pending", "cohort_name": None,
        "ev": ev, "ev_raw": ev, "risk_adjusted_ev": 0.05,
        "legs_fingerprint": fp, "trace_id": str(uuid.uuid4()),
        "model_version": "m@1", "lineage_hash": "lh-" + fp,
        "order_json": {"contracts": 1, "legs": [
            {"symbol": ticker + "_P1", "side": "buy", "quantity": 1, "mid": 0.2},
            {"symbol": ticker + "_C1", "side": "sell", "quantity": 1, "mid": 1.0},
        ]},
        "sizing_metadata": sizing,
    }


def _cfgs(neutral):
    return {"aggressive": PolicyConfig(), "neutral": neutral}


def _run(client, configs):
    with patch.object(fork_mod, "is_policy_lab_enabled", lambda: True), \
         patch.object(fork_mod, "load_cohort_configs", lambda *a, **k: configs), \
         patch.object(fork_mod, "get_current_champion", lambda *a, **k: "aggressive"):
        return fork_mod.fork_suggestions_for_cohorts(UID, client)


def _neu(client, sid):
    """The neutral-cohort (c-neu) policy_decisions row for a suggestion."""
    for r in client.tables.get("policy_decisions", []):
        if r.get("cohort_id") == "c-neu" and r.get("suggestion_id") == sid:
            return r
    return None


class TestRoutingLogTruthRoute(unittest.TestCase):
    """Route-level: drive fork_suggestions_for_cohorts, assert the persisted
    reason_codes tell the truth. RED on bef2cdd, GREEN after the fix."""

    def setUp(self):
        os.environ.pop("SHADOW_RAW_EV_ENABLED", None)

    def test_capacity_reject_not_labeled_below_min(self):
        # Fixtures 1 + 5: score=80, ev=$1, threshold=50, capacity=1.
        # QQQ accepted; IWM rejected FOR CAPACITY — its score passed, so the
        # logger must NOT say (ev|score)_below_min.
        s_acc = _pending("QQQ", 80.0, 1.0, "fp-qqq")
        s_cap = _pending("IWM", 80.0, 1.0, "fp-iwm")
        client = FakeSupabase()
        _seed(client, s_acc, s_cap)
        _run(client, _cfgs(PolicyConfig(
            min_score_threshold=50.0, max_positions_open=1,
            max_suggestions_per_day=1)))
        acc = _neu(client, s_acc["id"])
        cap = _neu(client, s_cap["id"])
        self.assertIsNotNone(acc)
        self.assertIsNotNone(cap)
        self.assertEqual(acc["decision"], "accepted")
        self.assertEqual(acc["reason_codes"], [])
        self.assertEqual(cap["decision"], "rejected")
        self.assertNotIn("ev_below_min", cap["reason_codes"])     # the false positive
        self.assertNotIn("score_below_min", cap["reason_codes"])  # score PASSED
        self.assertIn("daily_limit_reached", cap["reason_codes"])

    def test_score_reject_labeled_score_below_min(self):
        # Fixture 2: score=40, ev=$100, threshold=50 → rejected FOR SCORE.
        # Old code: ev(100) !< 50 → no ev_below_min → generic filtered_by_policy
        # (the real reason erased). Fixed: score_below_min.
        s = _pending("QQQ", 40.0, 100.0, "fp-q")
        client = FakeSupabase()
        _seed(client, s)
        _run(client, _cfgs(PolicyConfig(min_score_threshold=50.0)))
        d = _neu(client, s["id"])
        self.assertIsNotNone(d)
        self.assertEqual(d["decision"], "rejected")
        self.assertIn("score_below_min", d["reason_codes"])       # the erased truth
        self.assertNotIn("ev_below_min", d["reason_codes"])
        self.assertNotIn("filtered_by_policy", d["reason_codes"])

    def test_boundary_score_equal_threshold_accepted(self):
        # Fixture 3: score == threshold → accepted (strict <). Preserved both
        # before and after (guard against a boundary regression).
        s = _pending("QQQ", 50.0, 1.0, "fp-q")
        client = FakeSupabase()
        _seed(client, s)
        _run(client, _cfgs(PolicyConfig(min_score_threshold=50.0)))
        d = _neu(client, s["id"])
        self.assertIsNotNone(d)
        self.assertEqual(d["decision"], "accepted")
        self.assertEqual(d["reason_codes"], [])

    def test_missing_score_typed_reason(self):
        # Fixture 4: no score → fail-safe REJECTED (unchanged) + a truthful
        # typed reason, never a fabricated ev_below_min.
        s = _pending("QQQ", None, 1.0, "fp-q")
        client = FakeSupabase()
        _seed(client, s)
        _run(client, _cfgs(PolicyConfig(min_score_threshold=50.0)))
        d = _neu(client, s["id"])
        self.assertIsNotNone(d)
        self.assertEqual(d["decision"], "rejected")
        self.assertIn("routing_decision_unavailable", d["reason_codes"])
        self.assertNotIn("ev_below_min", d["reason_codes"])

    def test_accepted_set_preserved(self):
        # Routing preservation guard: only the score-passing candidate is
        # accepted in the log (identical to the filter's accepted set).
        s_acc = _pending("QQQ", 80.0, 1.0, "fp-qqq")
        s_rej = _pending("IWM", 10.0, 1.0, "fp-iwm")
        client = FakeSupabase()
        _seed(client, s_acc, s_rej)
        _run(client, _cfgs(PolicyConfig(
            min_score_threshold=50.0, max_positions_open=5,
            max_suggestions_per_day=5)))
        accepted = {
            r["suggestion_id"] for r in client.tables.get("policy_decisions", [])
            if r.get("cohort_id") == "c-neu" and r["decision"] == "accepted"
        }
        self.assertIn(s_acc["id"], accepted)
        self.assertNotIn(s_rej["id"], accepted)


class TestCanonicalEvaluationUnit(unittest.TestCase):
    """Unit: the canonical _evaluate_cohort_policy result. (New surface —
    exists only after the fix.)"""

    def _cfg(self, thr=50.0, max_pos=5, max_day=5):
        return PolicyConfig(min_score_threshold=thr, max_positions_open=max_pos,
                            max_suggestions_per_day=max_day)

    def _ev(self, suggestions, config, open_positions=0):
        return fork_mod._evaluate_cohort_policy(suggestions, config, open_positions)

    def test_accept_reject_capacity_precedence(self):
        # order [reject-score, accept, accept, capacity] with capacity=2.
        sugg = [
            _pending("A", 40.0, 1.0, "a"),   # score reject (no slot consumed)
            _pending("B", 80.0, 1.0, "b"),   # accept #1
            _pending("C", 90.0, 1.0, "c"),   # accept #2
            _pending("D", 95.0, 1.0, "d"),   # capacity reject
        ]
        ds = self._ev(sugg, self._cfg(thr=50.0, max_pos=2, max_day=5))
        self.assertEqual([d.accepted for d in ds], [False, True, True, False])
        self.assertEqual(ds[0].reason_codes, ["score_below_min"])
        self.assertEqual(ds[1].reason_codes, [])
        self.assertEqual(ds[2].reason_codes, [])
        self.assertEqual(ds[3].reason_codes, ["daily_limit_reached"])
        self.assertEqual(ds[3].capacity_state, "capacity_exhausted")
        self.assertEqual([d.rank for d in ds], [1, 2, 3, 4])

    def test_missing_score_typed_and_never_accepted(self):
        ds = self._ev([_pending("A", None, 1.0, "a")], self._cfg())
        self.assertFalse(ds[0].accepted)
        self.assertEqual(ds[0].reason_codes, ["routing_decision_unavailable"])
        self.assertIsNone(ds[0].score_value)

    def test_max_positions_reason_when_open_positions_bind(self):
        # open_positions already at the cap → capacity reason is
        # max_positions_reached, not daily_limit_reached.
        ds = self._ev([_pending("A", 90.0, 1.0, "a")],
                      self._cfg(max_pos=1, max_day=5), open_positions=1)
        self.assertFalse(ds[0].accepted)
        self.assertEqual(ds[0].reason_codes, ["max_positions_reached"])

    def test_filter_derives_from_same_evaluation(self):
        # _filter_for_cohort must be exactly the accepted subset (order + ids).
        sugg = [
            _pending("A", 40.0, 1.0, "a"),
            _pending("B", 80.0, 1.0, "b"),
            _pending("C", 90.0, 1.0, "c"),
        ]
        cfg = self._cfg(thr=50.0)
        filtered = fork_mod._filter_for_cohort(sugg, cfg, 0)
        ds = self._ev(sugg, cfg)
        self.assertEqual(
            [s["id"] for s in filtered],
            [d.suggestion_id for d in ds if d.accepted],
        )
        self.assertEqual([s["ticker"] for s in filtered], ["B", "C"])


if __name__ == "__main__":
    unittest.main()
