import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone
from packages.quantum.analytics.behavior_analysis import BehaviorAnalysisService

class TestBehaviorAnalysis:

    @pytest.fixture
    def mock_supabase(self):
        return MagicMock()

    def test_get_behavior_summary_basic(self, mock_supabase):
        # Setup mock data
        suggestions_data = [
            {"strategy": "iron_condor", "agent_summary": {"active_constraints": {"sizing.max_risk": 1}}},
            {"strategy": "iron_condor", "agent_summary": {"active_constraints": {"sizing.max_risk": 1}}},
            {"strategy": "vertical_spread", "agent_summary": {}}
        ]

        vetoes_data = [
            {"content": {"agent": "RiskBudgetEngine", "reason": "budget"}},
            {"content": {"agent": "SizingAgent", "reason": "zero_contracts", "strategy": "iron_condor"}}
        ]

        fallback_data = [
            {"content": {"fallback": "classic_sizing"}}
        ]

        mock_suggestions_query = MagicMock()
        mock_suggestions_query.execute.return_value.data = suggestions_data

        mock_vetoes_query = MagicMock()
        mock_vetoes_query.execute.return_value.data = vetoes_data

        mock_fallbacks_query = MagicMock()
        mock_fallbacks_query.execute.return_value.data = fallback_data

        def table_se(name):
            if name == "trade_suggestions":
                m = MagicMock()
                m.select.return_value.eq.return_value.gte.return_value = mock_suggestions_query
                m.select.return_value.eq.return_value.eq.return_value.gte.return_value = mock_suggestions_query
                return m
            if name == "decision_logs":
                m = MagicMock()
                select_mock = MagicMock()

                def eq_se(field, value):
                    next_mock = MagicMock()
                    if field == "decision_type" and value == "trade_veto":
                        next_mock.gte.return_value = mock_vetoes_query
                    elif field == "decision_type" and value == "system_fallback":
                        next_mock.gte.return_value = mock_fallbacks_query
                    else:
                        next_mock.eq.side_effect = eq_se
                        next_mock.gte.return_value = MagicMock(execute=MagicMock(return_value=MagicMock(data=[])))
                    return next_mock

                select_mock.eq.side_effect = eq_se
                m.select.return_value = select_mock
                return m

            return MagicMock()

        mock_supabase.table.side_effect = table_se

        service = BehaviorAnalysisService(mock_supabase)
        result = service.get_behavior_summary("user_123", window_days=7)

        assert result["veto_rate_pct"] == 40.0
        assert result["window"] == "7d"
        assert result["veto_breakdown"]["RiskBudgetEngine"] == 1

    def test_get_behavior_summary_filtered(self, mock_supabase):
        # Data for filtered test
        suggestions_data = [{"strategy": "iron_condor", "agent_summary": {}}]

        # Vetoes: One generic (no strategy), one specific (iron_condor)
        vetoes_data = [
            {"content": {"agent": "RiskBudgetEngine", "reason": "budget"}}, # No strategy
            {"content": {"agent": "SizingAgent", "reason": "zero", "strategy": "iron_condor"}}
        ]

        fallback_data = [{"content": {"fallback": "classic", "strategy": "iron_condor"}}]

        mock_s_q = MagicMock()
        mock_s_q.execute.return_value.data = suggestions_data

        mock_v_q = MagicMock()
        mock_v_q.execute.return_value.data = vetoes_data

        mock_f_q = MagicMock()
        mock_f_q.execute.return_value.data = fallback_data

        def table_se(name):
            if name == "trade_suggestions":
                m = MagicMock()
                # Simulate filtering on strategy in the DB call itself
                # The service calls .eq("strategy", ...)
                chain_mock = MagicMock()
                chain_mock.execute.return_value.data = suggestions_data
                m.select.return_value.eq.return_value.gte.return_value = chain_mock
                m.select.return_value.eq.return_value.eq.return_value.gte.return_value = chain_mock
                return m
            if name == "decision_logs":
                m = MagicMock()
                select_mock = MagicMock()
                def eq_se(field, value):
                    next_mock = MagicMock()
                    if field == "decision_type" and value == "trade_veto":
                        next_mock.gte.return_value = mock_v_q
                    elif field == "decision_type" and value == "system_fallback":
                        next_mock.gte.return_value = mock_f_q
                    else:
                        next_mock.eq.side_effect = eq_se
                        next_mock.gte.return_value = MagicMock(execute=MagicMock(return_value=MagicMock(data=[])))
                    return next_mock
                select_mock.eq.side_effect = eq_se
                m.select.return_value = select_mock
                return m
            return MagicMock()

        mock_supabase.table.side_effect = table_se

        service = BehaviorAnalysisService(mock_supabase)
        # Request for 'iron_condor'
        result = service.get_behavior_summary("u1", window_days=7, strategy_family="iron_condor")

        # Vetoes filtered: Only the one with "strategy": "iron_condor" remains
        # 1 Suggestion + 1 Veto = 2 Total
        # Veto rate = 1/2 = 50%
        # The generic veto is excluded.
        assert result["veto_rate_pct"] == 50.0
        assert result["veto_breakdown"]["SizingAgent"] == 1
        assert "RiskBudgetEngine" not in result["veto_breakdown"]

        # Fallbacks filtered
        assert len(result["system_fallbacks"]) == 1
