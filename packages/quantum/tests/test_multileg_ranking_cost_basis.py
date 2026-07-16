"""Multi-leg commission basis for canonical ranking.

The broker charges per option leg, per structure contract, on entry and exit.
These tests pin the explicit dollar basis without changing MIN_EDGE_AFTER_COSTS.
"""

import unittest

from packages.quantum.analytics import canonical_ranker as cr


def _suggestion(*, legs, contracts=1, ev=100.0):
    return {
        "ticker": "TEST",
        "ev": ev,
        "order_json": {
            "contracts": contracts,
            "legs": [{"symbol": f"L{i}", "quantity": contracts} for i in range(legs)],
        },
        "sizing_metadata": {
            "contracts": contracts,
            "max_loss_total": 500.0 * contracts,
        },
    }


class TestRoundTripCommissionBasis(unittest.TestCase):
    def test_two_leg_vertical_qty_one_costs_260(self):
        s = _suggestion(legs=2)
        self.assertAlmostEqual(cr._ranking_round_trip_fees(s), 2.60)
        self.assertEqual(s["ranking_costs"]["leg_count"], 2)
        self.assertEqual(
            s["ranking_costs"]["commission_basis"],
            "per_leg_per_structure_contract_round_trip",
        )

    def test_four_leg_condor_qty_one_costs_520(self):
        s = _suggestion(legs=4)
        self.assertAlmostEqual(cr._ranking_round_trip_fees(s), 5.20)
        self.assertEqual(s["ranking_costs"]["expected_fees_total"], 5.20)

    def test_cost_scales_by_structure_contract_count(self):
        s = _suggestion(legs=4, contracts=3)
        self.assertAlmostEqual(cr._ranking_round_trip_fees(s), 15.60)
        self.assertEqual(s["ranking_costs"]["structure_contracts"], 3)

    def test_leg_count_can_change_edge_disposition_at_same_ev(self):
        # slippage floor = $1.00. Vertical: 20 - 1 - 2.60 = 16.40 (pass).
        # Condor: 20 - 1 - 5.20 = 13.80 (below the unchanged $15 floor).
        vertical = _suggestion(legs=2, ev=20.0)
        condor = _suggestion(legs=4, ev=20.0)
        self.assertGreater(
            cr.compute_risk_adjusted_ev(vertical, [], 2000.0), -999.0
        )
        self.assertEqual(
            cr.compute_risk_adjusted_ev(condor, [], 2000.0), -999.0
        )

    def test_present_but_empty_order_fails_closed(self):
        s = _suggestion(legs=1)
        s["order_json"]["legs"] = []
        self.assertEqual(cr.compute_risk_adjusted_ev(s, [], 2000.0), -999.0)
        self.assertEqual(s["ranking_costs"]["commission_basis"], "unavailable")
        self.assertEqual(
            s["ranking_costs"]["error"], "ranking_cost_leg_count_unavailable"
        )

    def test_legacy_input_is_stamped_not_mislabeled(self):
        s = {
            "ticker": "LEGACY",
            "ev": 100.0,
            "sizing_metadata": {"contracts": 1, "max_loss_total": 500.0},
        }
        self.assertAlmostEqual(cr._ranking_round_trip_fees(s), 1.30)
        self.assertEqual(
            s["ranking_costs"]["commission_basis"],
            "legacy_single_leg_input_without_order_json",
        )


if __name__ == "__main__":
    unittest.main()
