import pytest
import os
from datetime import date, timedelta
from packages.quantum.agents.agents.event_risk_agent import EventRiskAgent

class TestEventRiskAgent:

    @pytest.fixture
    def agent(self):
        return EventRiskAgent()

    def test_no_earnings_data(self, agent):
        context = {"symbol": "AAPL"}
        signal = agent.evaluate(context)
        assert signal.agent_id == "event_risk"
        assert signal.signal == "neutral"
        assert signal.veto is False
        assert 0.5 <= signal.score <= 0.7
        assert signal.reason == "No earnings data found"

    def test_invalid_earnings_date(self, agent):
        context = {"earnings_date": "invalid-date"}
        signal = agent.evaluate(context)
        assert signal.signal == "neutral"
        assert "Invalid" in signal.reason

    def test_earnings_far_out(self, agent):
        future_date = (date.today() + timedelta(days=20)).strftime("%Y-%m-%d")
        context = {"earnings_date": future_date}
        signal = agent.evaluate(context)
        assert signal.signal == "neutral"
        assert signal.veto is False
        constraints = signal.constraints
        assert constraints["event.is_event_window"] is False
        assert constraints["event.days_to_event"] == 20

    def test_earnings_approaching_caution(self, agent):
        # 3 days out (default lookahead is 7)
        future_date = (date.today() + timedelta(days=3)).strftime("%Y-%m-%d")
        context = {"earnings_date": future_date}
        signal = agent.evaluate(context)

        assert signal.veto is False
        assert "approaching" in signal.reason.lower()

        constraints = signal.constraints
        assert constraints["event.is_event_window"] is True
        assert constraints["event.days_to_event"] == 3
        assert constraints["event.require_defined_risk"] is True

    def test_earnings_imminent_veto(self, agent):
        # 1 day out (default veto is 1)
        future_date = (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")
        context = {"earnings_date": future_date}
        signal = agent.evaluate(context)

        assert signal.veto is True
        assert signal.signal == "veto"
        constraints = signal.constraints
        assert constraints["event.days_to_event"] == 1
        assert constraints["event.is_event_window"] is True

    def test_earnings_map_lookup(self, agent):
        future_date = (date.today() + timedelta(days=3)).strftime("%Y-%m-%d")
        context = {
            "symbol": "TSLA",
            "earnings_map": {
                "AAPL": "2025-01-01",
                "TSLA": future_date
            }
        }
        signal = agent.evaluate(context)

        assert signal.veto is False
        constraints = signal.constraints
        assert constraints["event.days_to_event"] == 3
        assert constraints["event.require_defined_risk"] is True

    def test_env_var_configuration(self, monkeypatch):
        # Override env vars
        monkeypatch.setenv("QUANT_AGENT_EVENT_LOOKAHEAD_DAYS", "10")
        monkeypatch.setenv("QUANT_AGENT_EVENT_VETO_DAYS", "2")

        agent = EventRiskAgent()

        # 9 days out (within new lookahead 10)
        future_date = (date.today() + timedelta(days=9)).strftime("%Y-%m-%d")
        context = {"earnings_date": future_date}
        signal = agent.evaluate(context)
        assert signal.constraints["event.is_event_window"] is True

        # 2 days out (veto)
        future_date_veto = (date.today() + timedelta(days=2)).strftime("%Y-%m-%d")
        context_veto = {"earnings_date": future_date_veto}
        signal_veto = agent.evaluate(context_veto)
        assert signal_veto.veto is True

    def test_earnings_passed(self, agent):
        past_date = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        context = {"earnings_date": past_date}
        signal = agent.evaluate(context)
        assert signal.signal == "neutral"
        assert signal.constraints["event.days_to_event"] < 0
