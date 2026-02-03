"""
Regression tests for capital basis consistency between sizing and risk budget.

Reproduces the bug where:
- deployable_capital = 20.51 (from stale snapshot)
- paper_baseline_capital = 100,000
- positions sized for 100k had risk usage = 137,500
- budget cap = 35% of 20.51 = 7.18
- Result: false "risk budget exhausted"

Fix: In paper mode, use max(buying_power, paper_baseline_capital) to ensure
consistency between how positions were sized and how budget is calculated.
"""

import asyncio
import unittest
from unittest.mock import MagicMock, patch
import sys

# Persist module-level mocks
_mock_ops_module = MagicMock()
_mock_supabase_module = MagicMock()

_MODULE_PATCHES = {
    "supabase": _mock_supabase_module,
    "packages.quantum.check_version": MagicMock(),
    "packages.quantum.ops_endpoints": _mock_ops_module,
}

for _k, _v in _MODULE_PATCHES.items():
    sys.modules[_k] = _v

from packages.quantum.services.cash_service import CashService  # noqa: E402

USER_ID = "test-user-capital-consistency"


def _make_chain_mock(**table_responses):
    """Build a Supabase mock whose .table(name) returns a chain mock."""
    mock_supabase = MagicMock()

    def table_side_effect(name):
        chain = MagicMock()
        data = table_responses.get(name, [])
        chain.execute.return_value = MagicMock(data=data)
        for method in ["select", "eq", "neq", "gte", "lt", "in_",
                        "order", "limit", "single", "maybe_single"]:
            getattr(chain, method).return_value = chain
        return chain

    mock_supabase.table.side_effect = table_side_effect
    return mock_supabase


class TestCapitalBasisConsistency(unittest.TestCase):
    """
    Regression tests for the bug:
    Usage=$137500.00 vs deployable=$20.51, Cap=$7.18
    """

    def setUp(self):
        _mock_ops_module.reset_mock(side_effect=True, return_value=True)

    def test_paper_mode_uses_max_of_buying_power_and_baseline(self):
        """
        When buying_power (20.51) < paper_baseline (100k) in paper mode,
        deployable should be paper_baseline (100k), not buying_power.

        This ensures budget calculations match how positions were sized.
        """
        _mock_ops_module.get_global_ops_control.return_value = {"mode": "paper"}
        mock_sb = _make_chain_mock(
            portfolio_snapshots=[{"buying_power": 20.51}],
            positions=[],
            v3_go_live_state=[{"paper_baseline_capital": 100_000}],
            user_settings=None,
            trade_suggestions=[],
        )
        svc = CashService(mock_sb)
        result = asyncio.run(svc.get_deployable_capital(USER_ID))

        # Should use baseline (100k) since it's > buying_power (20.51)
        self.assertEqual(result, 100_000.0)

    def test_paper_mode_buying_power_above_baseline_uses_buying_power(self):
        """
        When buying_power (150k) > paper_baseline (100k) in paper mode,
        deployable should be buying_power (150k).

        This handles the case where user increased their paper capital.
        """
        _mock_ops_module.get_global_ops_control.return_value = {"mode": "paper"}
        mock_sb = _make_chain_mock(
            portfolio_snapshots=[{"buying_power": 150_000}],
            positions=[],
            v3_go_live_state=[{"paper_baseline_capital": 100_000}],
            user_settings=None,
            trade_suggestions=[],
        )
        svc = CashService(mock_sb)
        result = asyncio.run(svc.get_deployable_capital(USER_ID))

        # Should use buying_power (150k) since it's > baseline (100k)
        self.assertEqual(result, 150_000.0)

    def test_live_mode_does_not_use_baseline(self):
        """
        In live mode, always use actual buying_power regardless of baseline.
        """
        _mock_ops_module.get_global_ops_control.return_value = {"mode": "live"}
        mock_sb = _make_chain_mock(
            portfolio_snapshots=[{"buying_power": 20.51}],
            positions=[],
            v3_go_live_state=[{"paper_baseline_capital": 100_000}],
            user_settings=None,
            trade_suggestions=[],
        )
        svc = CashService(mock_sb)
        result = asyncio.run(svc.get_deployable_capital(USER_ID))

        # Live mode: use actual buying_power
        self.assertEqual(result, 20.51)

    def test_paper_mode_respects_buffer_and_reserved(self):
        """
        In paper mode with baseline, deductions (buffer, reserved) still apply.
        """
        _mock_ops_module.get_global_ops_control.return_value = {"mode": "paper"}
        mock_sb = _make_chain_mock(
            portfolio_snapshots=[{"buying_power": 20.51}],
            positions=[],
            v3_go_live_state=[{"paper_baseline_capital": 100_000}],
            user_settings={"cash_buffer": 5_000},
            trade_suggestions=[
                {"sizing_metadata": {"capital_required": 10_000}},
            ],
        )
        svc = CashService(mock_sb)
        result = asyncio.run(svc.get_deployable_capital(USER_ID))

        # 100k baseline - 5k buffer - 10k reserved = 85k
        self.assertEqual(result, 85_000.0)


class TestRiskBudgetGuardrail(unittest.TestCase):
    """Tests for the risk budget engine capital mismatch guardrail."""

    @patch("packages.quantum.services.risk_budget_engine.RiskEngine")
    def test_diagnostics_flags_capital_mismatch(self, mock_risk_engine_class):
        """
        When usage >> deployable, diagnostics should include capital_mismatch.
        """
        # Import here to avoid complex mocking at module level
        from packages.quantum.services.risk_budget_engine import RiskBudgetEngine

        # Mock RiskEngine.get_active_policy to return None (no policy)
        mock_risk_engine_class.get_active_policy.return_value = None

        # Mock supabase for RiskBudgetEngine
        mock_sb = MagicMock()
        mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=None)

        engine = RiskBudgetEngine(mock_sb)

        # Simulate: positions with total risk of 137,500 but deployable of only 20.51
        # 5 short puts at strike 275 = 275 * 100 * 5 = 137,500
        positions = [
            {
                "symbol": "O:SPY250117P00275000",
                "quantity": 5,
                "side": "sell",
                "strike": 275,
                "option_type": "put",
                "instrument_type": "option",
            }
        ]

        # This should trigger the guardrail
        with patch.object(engine, 'truth_layer'):
            report = engine.compute(
                user_id=USER_ID,
                deployable_capital=20.51,
                regime_input="chop",
                positions=positions,
            )

        # Check diagnostics contains capital_mismatch
        mismatch_diags = [d for d in report.diagnostics if "capital_mismatch" in d]
        self.assertTrue(
            len(mismatch_diags) > 0,
            f"Expected capital_mismatch in diagnostics, got: {report.diagnostics}"
        )

        # Verify the usage is approximately 137,500 (5 * 275 * 100)
        self.assertGreater(report.global_allocation.used, 100_000)


if __name__ == "__main__":
    unittest.main()
