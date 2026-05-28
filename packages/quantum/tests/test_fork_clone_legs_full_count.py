"""#3 convention — cohort clones scale legs.quantity to their OWN contract count.

PR #990's live F-row check observed legs.quantity=5 identical across the 5/12/26
cohort rows because `_clone_suggestion_for_cohort` copied the champion's legs
verbatim. This asserts each clone's legs now match the clone's own contracts
(full-count), so cohort suggestion rows are convention-correct at emission.
"""

import unittest

from packages.quantum.policy_lab.fork import _clone_suggestion_for_cohort
from packages.quantum.policy_lab.config import PolicyConfig


def _source(champion_contracts=5):
    return {
        "user_id": "u1",
        "window": "midday_entry",
        "ticker": "F",
        "strategy": "LONG_CALL_DEBIT_SPREAD",
        "direction": "long",
        "ev": 24.0,
        "risk_adjusted_ev": 0.03,
        "order_json": {
            "contracts": champion_contracts,
            "limit_price": 0.96,
            "legs": [
                {"side": "buy", "symbol": "O:F260626C00015500", "quantity": champion_contracts},
                {"side": "sell", "symbol": "O:F260626C00017500", "quantity": champion_contracts},
            ],
        },
        "sizing_metadata": {"max_loss_total": 96.0 * champion_contracts, "score": 80},
        "cycle_date": "2026-05-28",
        "legs_fingerprint": "fp_f",
        "trace_id": "11111111-2222-3333-4444-555555555555",
        "model_version": "v1",
        "features_hash": "fh",
        "regime": "NORMAL",
        "decision_lineage": {},
        "lineage_hash": "lh",
        "agent_signals": {},
        "agent_summary": {},
    }


class TestCloneLegsFullCount(unittest.TestCase):
    def test_clone_legs_match_clone_contracts(self):
        clone = _clone_suggestion_for_cohort(
            source=_source(5), cohort_name="neutral",
            config=PolicyConfig(), deployable_capital=5000.0,
        )
        self.assertIsNotNone(clone)
        contracts = clone["order_json"]["contracts"]
        legs = clone["order_json"]["legs"]
        self.assertTrue(len(legs) == 2)
        for leg in legs:
            self.assertEqual(
                leg["quantity"], contracts,
                "Each clone leg quantity must equal the clone's own contract "
                "count (full-count), not the champion's.",
            )

    def test_clone_legs_not_left_at_champion_quantity_when_different(self):
        # Force a clone whose contract count differs from the champion's 5.
        clone = _clone_suggestion_for_cohort(
            source=_source(5), cohort_name="conservative",
            config=PolicyConfig(max_risk_pct_per_trade=0.02, risk_multiplier=1.0),
            deployable_capital=100000.0,
        )
        contracts = clone["order_json"]["contracts"]
        if contracts != 5:
            for leg in clone["order_json"]["legs"]:
                self.assertEqual(leg["quantity"], contracts)
                self.assertNotEqual(
                    leg["quantity"], 5,
                    "Clone legs must be rescaled away from the champion's 5.",
                )


if __name__ == "__main__":
    unittest.main()
