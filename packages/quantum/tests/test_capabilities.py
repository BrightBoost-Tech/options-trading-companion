
import pytest
from unittest.mock import MagicMock
from packages.quantum.services.capability_service import CapabilityResolver
from packages.quantum.models import UpgradeCapability

class TestCapabilityResolver:

    @pytest.fixture
    def mock_supabase(self):
        return MagicMock()

    @pytest.fixture
    def resolver(self, mock_supabase):
        return CapabilityResolver(mock_supabase)

    def test_agent_sizing_active(self, resolver, mock_supabase):
        # Setup: Account > $2000
        mock_response = MagicMock()
        mock_response.data = [{
            "holdings": [{"symbol": "AAPL", "quantity": 10, "current_price": 250.0}],
            "risk_metrics": {"net_liquidity": 2500.0}
        }]

        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_response

        # Execute
        caps = resolver.resolve_capabilities("user_123")

        # Verify
        sizing = next(c for c in caps.capabilities if c.capability == UpgradeCapability.AGENT_SIZING)
        assert sizing.is_active is True
        assert "Account > $2,000" in sizing.reason

    def test_agent_sizing_inactive_low_balance(self, resolver, mock_supabase):
        # Setup: Account < $2000
        mock_response = MagicMock()
        mock_response.data = [{
            "holdings": [{"symbol": "AAPL", "quantity": 1, "current_price": 100.0}],
            "risk_metrics": {"net_liquidity": 100.0}
        }]

        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_response

        # Execute
        caps = resolver.resolve_capabilities("user_123")

        # Verify
        sizing = next(c for c in caps.capabilities if c.capability == UpgradeCapability.AGENT_SIZING)
        assert sizing.is_active is False
        assert "too low" in sizing.reason

    def test_agent_sizing_robustness_null_values(self, resolver, mock_supabase):
        """
        Test that the resolver handles None values in risk_metrics or holdings without crashing.
        This verifies the fix for the TypeError bug.
        """
        # Setup: Risk metrics has None for net_liquidity, holdings has None for quantity
        mock_response = MagicMock()
        mock_response.data = [{
            "holdings": [
                {"symbol": "AAPL", "quantity": None, "current_price": 100.0}, # Should count as 0
                {"symbol": "GOOG", "quantity": 10, "current_price": 250.0}    # Valid: 2500 equity
            ],
            "risk_metrics": {"net_liquidity": None} # Should force fallback to holdings sum
        }]

        mock_supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_response

        # Execute
        caps = resolver.resolve_capabilities("user_123")

        # Verify
        sizing = next(c for c in caps.capabilities if c.capability == UpgradeCapability.AGENT_SIZING)

        # 10 * 250 = 2500, which is > 2000, so it should be active
        assert sizing.is_active is True
        assert "Account > $2,000" in sizing.reason

    def test_counterfactual_active(self, resolver, mock_supabase):
        # Setup: Has feedback loops
        mock_sizing_res = MagicMock()
        mock_sizing_res.data = []

        mock_feedback_res = MagicMock()
        mock_feedback_res.count = 5

        mock_guard_res = MagicMock()
        mock_guard_res.data = []

        def table_side_effect(name):
            m = MagicMock()
            if name == "portfolio_snapshots":
                m.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_sizing_res
            elif name == "learning_feedback_loops":
                m.select.return_value.eq.return_value.limit.return_value.execute.return_value = mock_feedback_res
            elif name == "scanner_universe":
                m.select.return_value.limit.return_value.execute.return_value = mock_guard_res
            return m

        mock_supabase.table.side_effect = table_side_effect

        # Execute
        caps = resolver.resolve_capabilities("user_123")

        # Verify
        cf = next(c for c in caps.capabilities if c.capability == UpgradeCapability.COUNTERFACTUAL_ANALYSIS)
        assert cf.is_active is True
        assert "Feedback loop active" in cf.reason

    def test_guardrails_system_readiness(self, resolver, mock_supabase):
         # Setup
        mock_sizing_res = MagicMock()
        mock_sizing_res.data = []

        mock_feedback_res = MagicMock()
        mock_feedback_res.count = 0

        mock_guard_res = MagicMock()
        mock_guard_res.data = [{"ticker": "AAPL"}] # Has data

        def table_side_effect(name):
            m = MagicMock()
            if name == "portfolio_snapshots":
                m.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_sizing_res
            elif name == "learning_feedback_loops":
                m.select.return_value.eq.return_value.limit.return_value.execute.return_value = mock_feedback_res
            elif name == "scanner_universe":
                m.select.return_value.limit.return_value.execute.return_value = mock_guard_res
            return m

        mock_supabase.table.side_effect = table_side_effect

        # Execute
        caps = resolver.resolve_capabilities("user_123")

        # Verify
        gr = next(c for c in caps.capabilities if c.capability == UpgradeCapability.ADVANCED_EVENT_GUARDRAILS)
        assert gr.is_active is True
        assert "System ready" in gr.reason
