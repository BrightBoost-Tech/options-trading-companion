import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# Stub dependencies ONLY around the ranker import, then RESTORE sys.modules.
# Leaving these MagicMocks in sys.modules permanently poisons every later
# lazy import suite-wide (the test_weekly_report_win_rate class of pollution;
# see the 2026-07-17 CI test_cost_basis_parity failure — the
# execution.transaction_cost_model mock leaked here was only masked by
# test_tcm_shadow_fill_realism popping it at ITS collection).
import sys
_STUB_KEYS = (
    "packages.quantum.security",
    "packages.quantum.services.journal_service",
    "packages.quantum.analytics.progress_engine",
    "packages.quantum.market_data",
    "packages.quantum.execution.transaction_cost_model",
    "supabase",
    "postgrest.exceptions",
)
_saved = {_k: sys.modules.get(_k) for _k in _STUB_KEYS}
for _k in _STUB_KEYS:
    if _saved[_k] is None:  # never shadow an already-imported real module
        sys.modules[_k] = MagicMock()
try:
    # Import ranker directly
    from packages.quantum.inbox.ranker import rank_suggestions, calculate_yield_on_risk
finally:
    for _k in _STUB_KEYS:
        if _saved[_k] is None:
            sys.modules.pop(_k, None)
        else:
            sys.modules[_k] = _saved[_k]
del _saved

class TestInboxRanker(unittest.TestCase):
    def test_calculate_yield_on_risk(self):
        # Case 1: All denoms present, picks max_loss_total
        s1 = {
            "ev": 10.0,
            "sizing_metadata": {
                "max_loss_total": 100.0,
                "capital_required_total": 200.0
            }
        }
        self.assertAlmostEqual(calculate_yield_on_risk(s1), 0.1)

        # Case 2: Fallback to capital_required_total
        s2 = {
            "ev": 20.0,
            "sizing_metadata": {
                "capital_required_total": 50.0
            }
        }
        self.assertAlmostEqual(calculate_yield_on_risk(s2), 0.4)

        # Case 3: Fallback to capital_required
        s3 = {
            "ev": 5.0,
            "sizing_metadata": {
                "capital_required": 25.0
            }
        }
        self.assertAlmostEqual(calculate_yield_on_risk(s3), 0.2)

        # Case 4: Zero EV
        s4 = {"ev": 0.0, "sizing_metadata": {"max_loss_total": 100.0}}
        self.assertAlmostEqual(calculate_yield_on_risk(s4), 0.0)

        # Case 5: Missing Sizing, Fallback denom 1.0
        s5 = {"ev": 7.0}
        self.assertAlmostEqual(calculate_yield_on_risk(s5), 7.0)

        # Case 6: Zero Denom -> 1.0
        s6 = {"ev": 10.0, "sizing_metadata": {"max_loss_total": 0.0}}
        self.assertAlmostEqual(calculate_yield_on_risk(s6), 10.0)

    def test_rank_suggestions_sorting(self):
        s1 = {"id": "A", "ev": 10.0, "sizing_metadata": {"max_loss_total": 100.0}, "created_at": "2023-01-01T10:00:00Z"} # 0.1
        s2 = {"id": "B", "ev": 50.0, "sizing_metadata": {"max_loss_total": 100.0}, "created_at": "2023-01-01T10:00:00Z"} # 0.5

        ranked = rank_suggestions([s1, s2])
        self.assertEqual(ranked[0]["id"], "B")
        self.assertEqual(ranked[1]["id"], "A")

    def test_rank_suggestions_tiebreak(self):
        # Tie break by created_at desc (newer first)
        s1 = {"id": "Old", "ev": 10.0, "sizing_metadata": {"max_loss_total": 100.0}, "created_at": "2023-01-01T10:00:00Z"} # 0.1
        s2 = {"id": "New", "ev": 10.0, "sizing_metadata": {"max_loss_total": 100.0}, "created_at": "2023-01-02T10:00:00Z"} # 0.1

        ranked = rank_suggestions([s1, s2])
        self.assertEqual(ranked[0]["id"], "New")
        self.assertEqual(ranked[1]["id"], "Old")

if __name__ == '__main__':
    unittest.main()
