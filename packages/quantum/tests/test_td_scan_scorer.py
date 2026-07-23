"""⑤ Scan-time scorer (scripts/analytics/td_scan_scorer) — pure, H9 abstention.

The scorer is the ONE place the observe-only terminal-distribution package is
named (outside packages/quantum). These tests prove it scores both models,
abstains (never 0.5 / never a default) on any missing input, keeps the credit
identity defect visible, ranks over the identical set, and makes NO provider /
broker / DB call (it takes only a dict).
"""

import copy
import inspect
import unittest

from scripts.analytics import td_scan_scorer as S
from scripts.analytics.td_scan_scorer import (
    MODEL_SET_VERSION,
    rank_scored_set,
    resolve_strategy,
    score_envelope,
)


def _debit_env(**over):
    env = {
        "candidate_fingerprint": "fp-debit",
        "symbol": "SPY",
        "strategy": "LONG_CALL_DEBIT_SPREAD",
        "premium_direction": "debit",
        "net_premium": 1.5,
        "spot": 500.0,
        "dte_days": 35.0,
        "known_at": "2026-07-20T14:00:00Z",
        "risk_free_rate": 0.0,
        "production_ev": 17.5,
        "emitted": True,
        "legs": [
            {"symbol": "O:SPY260824C00500000", "side": "buy", "option_type": "call",
             "strike": 500.0, "expiry": "2026-08-24", "delta": 0.55, "iv": 0.22},
            {"symbol": "O:SPY260824C00510000", "side": "sell", "option_type": "call",
             "strike": 510.0, "expiry": "2026-08-24", "delta": 0.30, "iv": 0.20},
        ],
    }
    env.update(over)
    return env


def _credit_env(**over):
    env = {
        "candidate_fingerprint": "fp-credit",
        "symbol": "SPY",
        "strategy": "CREDIT_CALL_SPREAD",
        "premium_direction": "credit",
        "net_premium": 1.0,
        "spot": 500.0,
        "dte_days": 30.0,
        "known_at": "2026-07-20T14:00:00Z",
        "production_ev": 0.0,
        "emitted": False,
        "reject_reason": "unattributed_post_ev",
        "legs": [
            {"symbol": "O:SPY260819C00500000", "side": "sell", "option_type": "call",
             "strike": 500.0, "expiry": "2026-08-19", "delta": 0.35, "iv": 0.22},
            {"symbol": "O:SPY260819C00505000", "side": "buy", "option_type": "call",
             "strike": 505.0, "expiry": "2026-08-19", "delta": 0.25, "iv": 0.21},
        ],
    }
    env.update(over)
    return env


class TestScoreEnvelope(unittest.TestCase):
    def test_debit_vertical_both_models_score(self):
        r = score_envelope(_debit_env())
        self.assertEqual(r["challenger_model_version"], MODEL_SET_VERSION)
        self.assertEqual(r["basis"], "raw")
        self.assertEqual(r["contracts_basis"], 1)
        self.assertIsNone(r["baseline"]["abstain_reason"])
        self.assertIsNone(r["challenger"]["abstain_reason"])
        self.assertGreater(r["baseline"]["pop"], 0.0)
        self.assertGreater(r["challenger"]["ev"], 0.0)
        self.assertEqual(r["challenger"]["model"], "lognormal_v1")

    def test_missing_iv_challenger_abstains_baseline_scores(self):
        env = _debit_env()
        for l in env["legs"]:
            l["iv"] = None
        r = score_envelope(env)
        # Baseline needs deltas only → still scores; challenger abstains missing_iv.
        self.assertIsNone(r["baseline"]["abstain_reason"])
        self.assertEqual(r["challenger"]["abstain_reason"], "missing_iv")
        self.assertIsNone(r["challenger"]["pop"])
        # NEVER a 0.5 coin flip.
        self.assertNotEqual(r["challenger"]["pop"], 0.5)

    def test_missing_spot_challenger_abstains_missing_spot(self):
        r = score_envelope(_debit_env(spot=None))
        self.assertEqual(r["challenger"]["abstain_reason"], "missing_spot")
        self.assertIsNone(r["challenger"]["ev"])

    def test_missing_delta_debit_baseline_abstains(self):
        env = _debit_env()
        for l in env["legs"]:
            l["delta"] = None
        r = score_envelope(env)
        self.assertEqual(r["baseline"]["abstain_reason"], "missing_delta")

    def test_credit_identity_defect_visible_and_challenger_real(self):
        r = score_envelope(_credit_env())
        # Baseline reproduces the fair-odds EV==0 identity, defect stamped.
        self.assertAlmostEqual(r["baseline"]["ev"], 0.0, places=6)
        self.assertTrue(any("credit_identity" in d for d in r["baseline"]["known_defects"]))
        # The challenger gives a REAL (non-zero) EV — the whole point of ⑤ for
        # the credit cohort that dies invisibly at the execution-cost gate.
        self.assertIsNotNone(r["challenger"]["ev"])
        self.assertNotEqual(r["challenger"]["ev"], 0.0)

    def test_unmapped_strategy_abstains_both(self):
        env = _debit_env(strategy="WHO_KNOWS", legs=[])
        r = score_envelope(env)
        self.assertEqual(r["baseline"]["abstain_reason"], "unmapped_strategy")
        self.assertEqual(r["challenger"]["abstain_reason"], "unmapped_strategy")

    def test_strategy_inference_from_geometry(self):
        # Unknown DB name but 2 debit legs → inferred debit_vertical.
        self.assertEqual(resolve_strategy(_debit_env(strategy="MYSTERY")), "debit_vertical")
        self.assertEqual(resolve_strategy(_credit_env(strategy="MYSTERY")), "credit_vertical")

    def test_gate_counterfactuals_typed_labels(self):
        r = score_envelope(_debit_env())
        gc = r["gate_counterfactuals"]
        self.assertIn(gc["ev_positive"], ("challenger_would_pass", "challenger_would_gate"))
        # Cost/score gates are honestly not-evaluable at the scan seam (H9).
        self.assertEqual(gc["execution_cost_gate"], "not_evaluable")
        self.assertEqual(gc["score_floor_gate"], "not_evaluable")
        self.assertEqual(gc["current_actual_gate"]["emitted"], True)

    def test_condor_scores_strict_baseline(self):
        env = {
            "candidate_fingerprint": "fp-condor", "symbol": "SPY",
            "strategy": "IRON_CONDOR", "premium_direction": "credit",
            "net_premium": 1.0, "spot": 500.0, "dte_days": 35.0,
            "known_at": "2026-07-20T14:00:00Z", "production_ev": 5.0, "emitted": False,
            "legs": [
                {"symbol": "O:SPY260824P00480000", "side": "sell", "option_type": "put", "strike": 480.0, "expiry": "2026-08-24", "delta": -0.15, "iv": 0.25},
                {"symbol": "O:SPY260824P00475000", "side": "buy", "option_type": "put", "strike": 475.0, "expiry": "2026-08-24", "delta": -0.10, "iv": 0.26},
                {"symbol": "O:SPY260824C00520000", "side": "sell", "option_type": "call", "strike": 520.0, "expiry": "2026-08-24", "delta": 0.15, "iv": 0.24},
                {"symbol": "O:SPY260824C00525000", "side": "buy", "option_type": "call", "strike": 525.0, "expiry": "2026-08-24", "delta": 0.10, "iv": 0.23},
            ],
        }
        r = score_envelope(env)
        self.assertIn(r["baseline"]["model"], ("baseline_condor_strict",))
        self.assertIsNone(r["challenger"]["abstain_reason"])
        self.assertEqual(r["provenance"]["condor_model"], "strict")

    def test_one_candidate_failure_does_not_touch_a_sibling(self):
        good = score_envelope(_debit_env())
        bad = score_envelope({"candidate_fingerprint": "x", "legs": [{"bogus": 1}],
                              "strategy": "LONG_CALL_DEBIT_SPREAD"})
        # bad abstains cleanly; good is fully scored (independent).
        self.assertIsNotNone(bad["baseline"]["abstain_reason"])
        self.assertIsNone(good["baseline"]["abstain_reason"])


class TestRankScoredSet(unittest.TestCase):
    def test_ranks_and_topn_deltas(self):
        a = score_envelope(_debit_env(candidate_fingerprint="a", production_ev=30.0))
        b = score_envelope(_credit_env(candidate_fingerprint="b", production_ev=10.0))
        lst = [a, b]
        rank_scored_set(lst, top_n=1)
        self.assertEqual(a["current_rank"], 1)  # higher production_ev ranks first
        self.assertEqual(b["current_rank"], 2)
        self.assertTrue(a["current_topn"])
        self.assertFalse(b["current_topn"])

    def test_abstained_challenger_is_unranked_never_zero(self):
        env = _debit_env(candidate_fingerprint="noiv")
        for l in env["legs"]:
            l["iv"] = None
        r = score_envelope(env)
        rank_scored_set([r], top_n=4)
        # production_ev present → current_rank set; challenger abstained → unranked.
        self.assertEqual(r["current_rank"], 1)
        self.assertIsNone(r["challenger_rank"])
        self.assertIsNone(r["rank_delta"])


class TestPurityNoIO(unittest.TestCase):
    def test_score_envelope_takes_only_a_dict_no_client(self):
        sig = inspect.signature(score_envelope)
        self.assertEqual(list(sig.parameters), ["envelope"])

    def test_scorer_module_names_no_provider_or_broker(self):
        src = inspect.getsource(S)
        for forbidden in ("alpaca", "polygon", "requests", "httpx",
                          "market_data_truth_layer", "supabase", "get_admin_client"):
            self.assertNotIn(forbidden, src,
                             f"scorer must be pure — found {forbidden!r}")

    def test_score_envelope_does_not_mutate_input(self):
        env = _debit_env()
        before = copy.deepcopy(env)
        score_envelope(env)
        self.assertEqual(env, before)


if __name__ == "__main__":
    unittest.main()
