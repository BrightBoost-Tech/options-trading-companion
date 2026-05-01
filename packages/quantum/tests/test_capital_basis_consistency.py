"""
Regression tests for capital basis consistency between sizing and risk budget.

Updated 2026-05-01 for #93 fix: cash_service.get_deployable_capital now
reads Alpaca options_buying_power directly (via equity_state helper)
instead of computing buying_power - cash_buffer - reserved_capital from
DB-derived sources. The previous logic produced phantom reservations
when trade_suggestions stayed `pending` indefinitely.

Pre-#93 tests asserted the old DB arithmetic (paper-baseline floor +
buffer + reserved subtraction). Those scenarios are no longer reachable
via the public API; the broker-truth read is the only path. Tests below
exercise the new contract:
- Alpaca returns OBP → that value is the deployable
- Alpaca unavailable → fall back to v3_go_live_state.paper_baseline_capital
- Both unavailable → 0.0 (caller's CapitalScanPolicy gates the cycle)
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
from packages.quantum.services.equity_state import (  # noqa: E402
    _reset_caches_for_testing,
)

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


class TestDeployableReadsBrokerTruth(unittest.TestCase):
    """#93: get_deployable_capital reads Alpaca options_buying_power."""

    def setUp(self):
        _reset_caches_for_testing()

    def test_returns_alpaca_options_buying_power(self):
        """When Alpaca returns OBP, that is the deployable value."""
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client"
        ) as mock_factory:
            mock_client = MagicMock()
            mock_client.get_account.return_value = {
                "options_buying_power": "500.00",
            }
            mock_factory.return_value = mock_client

            svc = CashService(_make_chain_mock())
            result = asyncio.run(svc.get_deployable_capital(USER_ID))
            self.assertEqual(result, 500.0)

    def test_falls_back_to_paper_baseline_on_alpaca_failure(self):
        """When Alpaca unavailable, read paper_baseline_capital."""
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            side_effect=Exception("Alpaca down"),
        ):
            mock_sb = _make_chain_mock(
                v3_go_live_state=[{"paper_baseline_capital": 500}],
            )
            svc = CashService(mock_sb)
            result = asyncio.run(svc.get_deployable_capital(USER_ID))
            self.assertEqual(result, 500.0)

    def test_falls_back_to_zero_when_no_baseline(self):
        """Both Alpaca and baseline unavailable → 0 (caller skips cycle)."""
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client",
            return_value=None,
        ):
            mock_sb = _make_chain_mock(v3_go_live_state=[])
            svc = CashService(mock_sb)
            result = asyncio.run(svc.get_deployable_capital(USER_ID))
            self.assertEqual(result, 0.0)

    def test_does_not_subtract_pending_reservations(self):
        """#93 regression: pending trade_suggestions must NOT reduce
        deployable. Pre-#93 logic subtracted SUM(capital_required) from
        the buying_power source; that caused phantom reservations when
        suggestions stayed `pending` (paper_autopilot status-update
        bypass). Broker-truth read sidesteps the lifecycle entirely."""
        with patch(
            "packages.quantum.brokers.alpaca_client.get_alpaca_client"
        ) as mock_factory:
            mock_client = MagicMock()
            mock_client.get_account.return_value = {
                "options_buying_power": "500.00",
            }
            mock_factory.return_value = mock_client

            mock_sb = _make_chain_mock(
                trade_suggestions=[
                    {"sizing_metadata": {"capital_required": 292.0}},
                ],
            )
            svc = CashService(mock_sb)
            result = asyncio.run(svc.get_deployable_capital(USER_ID))
            # Pre-#93 would have returned 500 - 292 = 208.
            self.assertEqual(result, 500.0)


class TestRiskBudgetGuardrail(unittest.TestCase):
    """Tests for the risk budget engine capital mismatch guardrail."""

    def test_diagnostics_flags_capital_mismatch(self):
        """
        When usage >> deployable, diagnostics should include capital_mismatch.
        """
        # Import here to avoid complex mocking at module level
        from packages.quantum.services.risk_budget_engine import RiskBudgetEngine

        # RiskEngine.get_active_policy was retired in PR #4 — no mock needed.

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
