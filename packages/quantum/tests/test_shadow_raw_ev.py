"""PR-D② (decision D②): shadow cohorts score on RAW ev (the experiment breathes on
unclamped EV); SHADOW_RAW_EV_ENABLED is a REVERT lever, default ON. The champion is
tagged in place (never cloned), so every clone is a shadow — raw applies to all.
"""
import os
import types
import unittest

from packages.quantum.policy_lab.fork import _clone_suggestion_for_cohort


def _cfg():
    return types.SimpleNamespace(budget_cap_pct=0.85, max_risk_pct_per_trade=0.02,
                                 risk_multiplier=1.0)


def _source(ev=18.73, ev_raw=37.46):
    s = {"user_id": "u1", "ticker": "QQQ", "strategy": "iron_condor",
         "order_json": {"contracts": 5, "legs": [{"strike": 100, "quantity": 5}]},
         "sizing_metadata": {"max_loss_total": 372.0}, "ev": ev}
    if ev_raw is not None:
        s["ev_raw"] = ev_raw
    return s


class TestShadowRawEv(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("SHADOW_RAW_EV_ENABLED", None)

    def test_default_on_uses_raw_ev(self):
        os.environ.pop("SHADOW_RAW_EV_ENABLED", None)                       # default ON
        clone = _clone_suggestion_for_cohort(_source(18.73, 37.46), "neutral", _cfg(), 2000.0)
        self.assertEqual(clone["ev"], 37.46)                                # RAW, not calibrated 18.73

    def test_empty_string_is_on(self):
        os.environ["SHADOW_RAW_EV_ENABLED"] = ""
        clone = _clone_suggestion_for_cohort(_source(18.73, 37.46), "neutral", _cfg(), 2000.0)
        self.assertEqual(clone["ev"], 37.46)

    def test_explicit_off_inherits_calibrated(self):
        os.environ["SHADOW_RAW_EV_ENABLED"] = "0"                           # revert lever
        clone = _clone_suggestion_for_cohort(_source(18.73, 37.46), "neutral", _cfg(), 2000.0)
        self.assertEqual(clone["ev"], 18.73)

    def test_missing_ev_raw_falls_back_to_calibrated(self):
        os.environ.pop("SHADOW_RAW_EV_ENABLED", None)
        clone = _clone_suggestion_for_cohort(_source(18.73, None), "conservative", _cfg(), 2000.0)
        self.assertEqual(clone["ev"], 18.73)                               # H9: honest fallback, no fabrication


if __name__ == "__main__":
    unittest.main()
