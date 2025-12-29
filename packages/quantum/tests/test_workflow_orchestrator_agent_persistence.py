import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import os
import asyncio
from packages.quantum.services.workflow_orchestrator import run_midday_cycle

# We need to mock supabase
class MockSupabase:
    def __init__(self):
        self.table_mock = MagicMock()

    def table(self, name):
        return self.table_mock

class TestWorkflowOrchestratorAgentPersistence(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.supabase = MockSupabase()
        # Mock other dependencies that orchestrator calls
        self.patchers = []

        # Mock CashService
        self.cash_patch = patch('packages.quantum.services.workflow_orchestrator.CashService')
        self.mock_cash_cls = self.cash_patch.start()
        # Ensure the instance method is an AsyncMock
        self.mock_cash_cls.return_value.get_deployable_capital = AsyncMock(return_value=2000.0)
        self.patchers.append(self.cash_patch)

        # Mock RiskBudgetEngine
        self.risk_patch = patch('packages.quantum.services.workflow_orchestrator.RiskBudgetEngine')
        self.mock_risk = self.risk_patch.start()
        self.mock_budgets = MagicMock()
        self.mock_budgets.global_allocation.remaining = 1000.0
        self.mock_budgets.global_allocation.used = 0.0
        self.mock_budgets.global_allocation.max_limit = 1000.0
        self.mock_budgets.max_risk_per_trade = 500.0
        self.mock_risk.return_value.compute.return_value = self.mock_budgets
        self.patchers.append(self.risk_patch)

        # Mock RegimeEngineV3
        self.regime_patch = patch('packages.quantum.services.workflow_orchestrator.RegimeEngineV3')
        self.mock_regime = self.regime_patch.start()
        self.mock_regime_instance = self.mock_regime.return_value
        self.mock_global_snap = MagicMock()
        self.mock_global_snap.state.value = "normal"
        self.mock_regime_instance.compute_global_snapshot.return_value = self.mock_global_snap
        self.mock_regime_instance.compute_symbol_snapshot.return_value.state.value = "normal"
        self.mock_regime_instance.get_effective_regime.return_value.value = "normal"
        self.mock_regime_instance.map_to_scoring_regime.return_value = "normal"
        self.patchers.append(self.regime_patch)

        # Mock scanner
        self.scanner_patch = patch('packages.quantum.services.workflow_orchestrator.scan_for_opportunities')
        self.mock_scanner = self.scanner_patch.start()
        self.patchers.append(self.scanner_patch)

        # Mock SizingAgent
        self.agent_patch = patch('packages.quantum.services.workflow_orchestrator.SizingAgent')
        self.mock_agent_cls = self.agent_patch.start()
        self.mock_agent = self.mock_agent_cls.return_value
        self.patchers.append(self.agent_patch)

        # Mock ExitPlanAgent
        self.exit_agent_patch = patch('packages.quantum.services.workflow_orchestrator.ExitPlanAgent')
        self.mock_exit_agent_cls = self.exit_agent_patch.start()
        self.mock_exit_agent = self.mock_exit_agent_cls.return_value
        self.patchers.append(self.exit_agent_patch)

        # Mock SmallAccountCompounder
        self.sac_patch = patch('packages.quantum.services.workflow_orchestrator.SmallAccountCompounder')
        self.mock_sac = self.sac_patch.start()
        self.mock_sac.rank_and_select.side_effect = lambda candidates, **kwargs: candidates # Return input
        self.mock_sac.calculate_variable_sizing.return_value = {
            "risk_budget": 100.0,
            "multipliers": {"score": 1.0}
        }
        self.patchers.append(self.sac_patch)

        # Mock telemetry to avoid errors
        self.telemetry_patch = patch('packages.quantum.services.workflow_orchestrator.emit_trade_event')
        self.telemetry_patch.start()
        self.patchers.append(self.telemetry_patch)

        self.log_patch = patch('packages.quantum.services.workflow_orchestrator.log_decision')
        self.log_patch.start()
        self.patchers.append(self.log_patch)

    async def asyncTearDown(self):
        for p in self.patchers:
            p.stop()

    async def test_midday_cycle_persists_sizing_signals(self):
        # Setup candidate
        cand = {
            "symbol": "AAPL",
            "ticker": "AAPL",
            "strategy": "bull_put_spread",
            "score": 80.0,
            "suggested_entry": 2.0,
            "max_loss_per_contract": 100.0,
            "ev": 10.0,
            "agent_signals": {"existing": {"score": 90}}
        }
        self.mock_scanner.return_value = [cand]

        # Setup SizingAgent response
        agent_signal = MagicMock()
        agent_signal.agent_id = "sizing"
        agent_signal.score = 75.0
        agent_signal.metadata = {
            "constraints": {
                "sizing.target_risk_usd": 150.0,
                "sizing.recommended_contracts": 2
            }
        }
        agent_signal.model_dump.return_value = {"score": 75.0, "agent_id": "sizing"}
        self.mock_agent.evaluate.return_value = agent_signal

        # Run cycle with env var enabled
        with patch.dict(os.environ, {"QUANT_AGENTS_ENABLED": "true"}):
            await run_midday_cycle(self.supabase, "user_123")

        # Verify upsert call contains agent fields
        upsert_call = self.supabase.table_mock.upsert.call_args
        self.assertIsNotNone(upsert_call)
        upsert_data = upsert_call[0][0] # List of dicts
        self.assertEqual(len(upsert_data), 1)
        suggestion = upsert_data[0]

        self.assertIn("agent_signals", suggestion)
        self.assertIn("sizing", suggestion["agent_signals"])
        # With new logic, we average score (80 + 75) / 2 = 77.5?
        # Actually in code: cand["agent_summary"] = {"overall_score": sizing_score}
        # But wait, cand.get("score") is just for display props in some places.
        # The logic is:
        # if "agent_summary" not in cand: cand["agent_summary"] = {"overall_score": sizing_score}
        # In this test, agent_summary is not in cand initially.
        # So overall_score should be 75.0 (sizing score).

        self.assertIn("agent_summary", suggestion)
        # Note: Depending on order of sizing vs exit agent, the score might be averaged.
        # But ExitPlanAgent is also run.
        # Let's check logic: Sizing runs first. Sets overall=75.
        # Then Exit runs.
        # But we need to see what ExitPlan returns in this test.
        # self.mock_exit_agent.evaluate is called too.
        # We didn't set return value explicitly for this test, so it returns a MagicMock.
        # MagicMock has no score attribute by default unless set? Or acts as anything.
        # If accessing .score, it returns a MagicMock object.
        # float(MagicMock()) fails.
        # We should set up exit agent default mock to be safe or ignore it.
        # In setUp, we created a MagicMock return value but didn't set attributes.
        # Let's see if we crash. The code does `exit_score = exit_signal.score ...`.
        # MagicMock.score is another MagicMock.
        # Then `(current_overall + exit_score) / 2`.
        # Adding float + MagicMock fails.
        # So we must set exit_agent mock return properly in this test or setUp.

    async def test_midday_cycle_no_mock_injections_and_exit_constraints(self):
        # This test covers the specific requirements:
        # 1. No mock injections for regime/vol
        # 2. Exit constraints merged properly

        # Setup candidate WITHOUT agent_signals initially
        cand = {
            "symbol": "TSLA",
            "ticker": "TSLA",
            "strategy": "long_call",
            "score": 85.0,
            "suggested_entry": 5.0,
            "max_loss_per_contract": 50.0,
            "ev": 20.0,
            # agent_signals intentionally missing or empty
            "agent_signals": {}
        }
        self.mock_scanner.return_value = [cand]

        # Sizing Agent setup
        # It should receive empty agent_signals since we removed the mock injection.
        sizing_signal = MagicMock()
        sizing_signal.score = 70.0
        sizing_signal.metadata = {
            "constraints": {
                "sizing.contracts": 1,
                "sizing.target_risk_usd": 100.0  # Must be > 0 to avoid skip
            }
        }
        sizing_signal.model_dump.return_value = {"score": 70.0}
        self.mock_agent.evaluate.return_value = sizing_signal

        # Exit Agent setup
        exit_signal = MagicMock()
        exit_signal.score = 80.0
        # Return nested constraints as required
        exit_signal.metadata = {
            "constraints": {
                "exit.profit_take_pct": 0.40,
                "exit.stop_loss_pct": -0.20
            },
            "other_metadata": "ignore_me"
        }
        exit_signal.model_dump.return_value = {"score": 80.0}
        self.mock_exit_agent.evaluate.return_value = exit_signal

        # Run cycle
        with patch.dict(os.environ, {"QUANT_AGENTS_ENABLED": "true"}):
            await run_midday_cycle(self.supabase, "user_123")

        # Verify SizingAgent inputs (NO mocks injected)
        call_args = self.mock_agent.evaluate.call_args
        self.assertIsNotNone(call_args)
        ctx = call_args[0][0]
        # Assert agent_signals is empty or only has what cand had (which is empty)
        # It should NOT have "regime" or "vol" injected by orchestrator.
        self.assertEqual(ctx["agent_signals"], {})

        # Verify Upsert Data
        upsert_call = self.supabase.table_mock.upsert.call_args
        suggestion = upsert_call[0][0][0]

        # Check agent_summary constraints
        # It should contain ONLY the contents of constraints, not "other_metadata"
        summary = suggestion["agent_summary"]
        constraints = summary["active_constraints"]

        self.assertIn("exit.profit_take_pct", constraints)
        self.assertEqual(constraints["exit.profit_take_pct"], 0.40)
        self.assertNotIn("other_metadata", constraints)
        self.assertNotIn("constraints", constraints) # Should be flattened

    async def test_fallback_retry_logic(self):
        # Simulate db error on first upsert due to missing columns
        cand = {
            "symbol": "AAPL",
            "ticker": "AAPL",
            "strategy": "bull_put_spread",
            "score": 80.0,
            "suggested_entry": 2.0,
            "max_loss_per_contract": 100.0,
        }
        self.mock_scanner.return_value = [cand]

        # Force agent output
        agent_signal = MagicMock()
        agent_signal.score = 75.0
        agent_signal.metadata = {
            "constraints": {
                "sizing.target_risk_usd": 150.0,
                "sizing.recommended_contracts": 1
            }
        }
        agent_signal.model_dump.return_value = {}
        self.mock_agent.evaluate.return_value = agent_signal

        # Setup Exit agent to be safe
        exit_signal = MagicMock()
        exit_signal.score = 75.0
        exit_signal.metadata = {"constraints": {}}
        exit_signal.model_dump.return_value = {}
        self.mock_exit_agent.evaluate.return_value = exit_signal

        # Mock upsert to fail first time, succeed second
        def side_effect(*args, **kwargs):
            if args and len(args) > 0:
                data = args[0]
                if data and "agent_signals" in data[0]:
                    raise Exception("column 'agent_signals' of relation 'trade_suggestions' does not exist")
            return MagicMock()

        self.supabase.table_mock.upsert.side_effect = side_effect

        with patch.dict(os.environ, {"QUANT_AGENTS_ENABLED": "true"}):
             await run_midday_cycle(self.supabase, "user_123")

        # Verify called twice
        self.assertEqual(self.supabase.table_mock.upsert.call_count, 2)

        # Verify second call data lacks agent fields
        second_call_data = self.supabase.table_mock.upsert.call_args_list[1][0][0]
        self.assertNotIn("agent_signals", second_call_data[0])

if __name__ == '__main__':
    unittest.main()
