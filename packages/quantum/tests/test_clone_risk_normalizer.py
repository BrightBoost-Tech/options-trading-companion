"""PR-④ E14: a cohort clone carries the CLONE's rescaled risk (typed top-level +
consistent JSON), or an EXPLICIT unknown (None) — never the source's mis-scaled
total, never a fabricated 0, never a NULL typed column beside a lying JSON total.
"""
import types
import unittest

from packages.quantum.policy_lab.fork import _clone_suggestion_for_cohort


def _cfg(max_risk=0.02):
    return types.SimpleNamespace(budget_cap_pct=0.85, max_risk_pct_per_trade=max_risk,
                                 risk_multiplier=1.0)


def _source(max_loss_total=372.0, contracts=5):
    sm = {} if max_loss_total is None else {"max_loss_total": max_loss_total}
    return {
        "user_id": "u1", "ticker": "QQQ", "strategy": "iron_condor",
        "order_json": {"contracts": contracts,
                       "legs": [{"strike": 100, "quantity": contracts}]},
        "sizing_metadata": sm, "legs_fingerprint": "fp",
    }


class TestCloneRiskNormalizer(unittest.TestCase):
    def test_rescaled_total_typed_and_json_consistent(self):
        # source 372 over 5ct → per-contract 74.4; effective_risk 40 → 1ct → total 74.4
        clone = _clone_suggestion_for_cohort(_source(372.0, 5), "neutral", _cfg(0.02), 2000.0)
        self.assertAlmostEqual(clone["max_loss_total"], 74.4, places=2)                     # typed top-level
        self.assertAlmostEqual(clone["sizing_metadata"]["max_loss_total"], 74.4, places=2)  # JSON consistent
        self.assertEqual(clone["sizing_metadata"]["max_loss_total_basis"],
                         "rescaled_from_source_per_contract")
        self.assertNotAlmostEqual(clone["max_loss_total"], 372.0, places=1)                 # NOT the source's (the bug)

    def test_unknown_source_stays_explicit_none(self):
        clone = _clone_suggestion_for_cohort(_source(None, 5), "conservative", _cfg(0.02), 2000.0)
        self.assertIsNone(clone["max_loss_total"])                       # explicit None, not 0
        self.assertIsNone(clone["sizing_metadata"]["max_loss_total"])    # JSON not lying next to it
        self.assertEqual(clone["sizing_metadata"]["max_loss_total_basis"],
                         "unknown_source_no_max_loss_total")

    def test_scales_with_clone_contracts(self):
        # bigger risk budget → 10ct → total scales to 744 (74.4 × 10)
        clone = _clone_suggestion_for_cohort(_source(372.0, 5), "neutral", _cfg(0.40), 2000.0)
        self.assertEqual(clone["order_json"]["contracts"], 10)
        self.assertAlmostEqual(clone["max_loss_total"], 744.0, places=1)


if __name__ == "__main__":
    unittest.main()
