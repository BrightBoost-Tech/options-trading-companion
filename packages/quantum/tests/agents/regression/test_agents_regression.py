import json
import os
import pytest
from datetime import date, timedelta, datetime
from typing import Dict, Any, List
from unittest import mock

# Agent Imports
from packages.quantum.agents.agents.liquidity_agent import LiquidityAgent
from packages.quantum.agents.agents.event_risk_agent import EventRiskAgent
from packages.quantum.agents.agents.strategy_design_agent import StrategyDesignAgent
from packages.quantum.agents.agents.sizing_agent import SizingAgent
from packages.quantum.agents.core import AgentSignal

# Fixture Helper
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

def load_or_update_fixture(fixture_name: str, results: List[Dict[str, Any]]):
    filepath = os.path.join(FIXTURE_DIR, fixture_name)

    # If UPDATE_GOLDEN env var is set, write the file
    if os.environ.get("UPDATE_GOLDEN"):
        with open(filepath, "w") as f:
            json.dump(results, f, indent=2, sort_keys=True)
        return results

    # Otherwise read and return
    if not os.path.exists(filepath):
        with open(filepath, "w") as f:
            json.dump(results, f, indent=2, sort_keys=True)
        return results

    with open(filepath, "r") as f:
        return json.load(f)

def run_agent_scenarios(agent_class, scenarios: List[Dict[str, Any]], config=None):
    agent = agent_class(config)
    results = []

    for scenario in scenarios:
        name = scenario["name"]
        context = scenario["context"]

        # Run agent
        signal = agent.evaluate(context)

        # Serialize signal
        result = {
            "name": name,
            "input": context, # Include input in record for context
            "output": {
                "score": signal.score,
                "veto": signal.veto,
                "reasons": signal.reasons,
                "metadata": signal.metadata
            }
        }
        results.append(result)

    return results

def assert_results_match(actual, expected):
    assert len(actual) == len(expected)
    for act, exp in zip(actual, expected):
        assert act["name"] == exp["name"]
        assert act["output"]["veto"] == exp["output"]["veto"]
        assert act["output"]["score"] == pytest.approx(exp["output"]["score"], 0.1)

        # Compare constraints
        act_constraints = act["output"]["metadata"].get("constraints", {})
        exp_constraints = exp["output"]["metadata"].get("constraints", {})

        for k, v in exp_constraints.items():
            val = act_constraints.get(k)
            if isinstance(v, float):
                if val is None:
                     assert val == v, f"Constraint {k} mismatch in {act['name']}: expected {v}, got None"
                else:
                     assert val == pytest.approx(v, 0.1), f"Constraint {k} mismatch in {act['name']}"
            elif isinstance(v, list) and k == "strategy.banned":
                 # Handle unordered list comparison for banned strategies
                 # We sort both lists before comparison
                 val_sorted = sorted(val) if val else []
                 v_sorted = sorted(v) if v else []
                 assert val_sorted == v_sorted, f"Constraint {k} mismatch in {act['name']}"
            else:
                assert val == v, f"Constraint {k} mismatch in {act['name']}"

        # Compare reasons
        assert act["output"]["reasons"] == exp["output"]["reasons"], f"Reasons mismatch in {act['name']}"


# --- Custom JSON Encoder for Dates ---
class DateEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (date, timedelta, datetime)):
            return str(obj)
        return super().default(obj)

# Helper to serialize before saving/comparing
def serialize_results(results):
    return json.loads(json.dumps(results, cls=DateEncoder))


# ================= TESTS =================

def test_liquidity_agent_regression():
    scenarios = [
        {
            "name": "basic_pass",
            "context": {
                "legs": [
                    {"bid": 10.00, "ask": 10.10, "mid": 10.05},
                    {"bid": 5.00, "ask": 5.05, "mid": 5.025}
                ]
            }
        },
        {
            "name": "wide_spread_veto",
            "context": {
                "legs": [
                    {"bid": 10.00, "ask": 12.00, "mid": 11.00} # ~18% spread
                ]
            }
        },
        {
            "name": "missing_quotes",
            "context": {
                "legs": [
                    {"bid": 10.00, "ask": 10.10, "mid": 10.05},
                    {"bid": None, "ask": None, "mid": None}
                ]
            }
        },
        {
            "name": "crossed_market",
            "context": {
                "legs": [
                    {"bid": 10.10, "ask": 10.00, "mid": 10.05}
                ]
            }
        },
        {
            "name": "worst_case_mode",
            "context": {
                "legs": [
                    {"bid": 10.00, "ask": 10.01, "mid": 10.005}, # Tiny spread
                    {"bid": 1.00, "ask": 1.20, "mid": 1.10}      # ~18% spread
                ]
            }
        }
    ]

    os.environ["QUANT_AGENT_LIQUIDITY_MAX_SPREAD_PCT"] = "0.12"
    os.environ["QUANT_AGENT_LIQUIDITY_MODE"] = "median"

    # Run standard scenarios
    results_std = run_agent_scenarios(LiquidityAgent, scenarios[:-1])

    # Run worst case scenario
    os.environ["QUANT_AGENT_LIQUIDITY_MODE"] = "worst"
    results_worst = run_agent_scenarios(LiquidityAgent, [scenarios[-1]])

    combined_results = serialize_results(results_std + results_worst)

    expected = load_or_update_fixture("liquidity_agent.json", combined_results)
    assert_results_match(combined_results, expected)


class MockDate(date):
    @classmethod
    def today(cls):
        return date(2025, 1, 1)

def test_event_risk_agent_regression():
    # Use a fixed date for deterministic tests
    fixed_today = date(2025, 1, 1)

    scenarios = [
        {"name": "no_earnings", "context": {}},
        {"name": "earnings_tomorrow", "context": {"earnings_date": str(fixed_today + timedelta(days=1))}},
        {"name": "earnings_in_5_days", "context": {"earnings_date": str(fixed_today + timedelta(days=5))}},
        {"name": "earnings_far", "context": {"earnings_date": str(fixed_today + timedelta(days=20))}},
        {"name": "earnings_passed", "context": {"earnings_date": str(fixed_today - timedelta(days=1))}},
        {"name": "invalid_date", "context": {"earnings_date": "not-a-date"}}
    ]

    os.environ["QUANT_AGENT_EVENT_LOOKAHEAD_DAYS"] = "7"
    os.environ["QUANT_AGENT_EVENT_VETO_DAYS"] = "1"

    # Patch 'date' where it is imported in the agent module.
    # The agent does: from datetime import datetime, date
    # So we must patch 'packages.quantum.agents.agents.event_risk_agent.date'
    # We pass MockDate class as the new object.

    with mock.patch('packages.quantum.agents.agents.event_risk_agent.date', MockDate):
        results = run_agent_scenarios(EventRiskAgent, scenarios)
        results = serialize_results(results)

    expected = load_or_update_fixture("event_risk_agent.json", results)
    assert_results_match(results, expected)


def test_strategy_design_agent_regression():
    scenarios = [
        {
            "name": "normal_pass",
            "context": {
                "legacy_strategy": "LONG CALL",
                "effective_regime": "BULLISH",
                "iv_rank": 30,
                "banned_strategies": []
            }
        },
        {
            "name": "shock_override",
            "context": {
                "legacy_strategy": "LONG CALL",
                "effective_regime": "SHOCK",
                "iv_rank": 30,
                "banned_strategies": []
            }
        },
        {
            "name": "chop_override_condor",
            "context": {
                "legacy_strategy": "LONG CALL",
                "effective_regime": "CHOP",
                "iv_rank": 30,
                "banned_strategies": []
            }
        },
        {
            "name": "chop_override_banned_condor",
            "context": {
                "legacy_strategy": "LONG CALL",
                "effective_regime": "CHOP",
                "iv_rank": 30,
                "banned_strategies": ["iron_condor"]
            }
        },
        {
            "name": "high_iv_override",
            "context": {
                "legacy_strategy": "LONG CALL",
                "effective_regime": "BULLISH",
                "iv_rank": 80,
                "banned_strategies": []
            }
        },
        {
            "name": "policy_ban_fallback",
            "context": {
                "legacy_strategy": "CREDIT PUT SPREAD",
                "effective_regime": "BULLISH",
                "iv_rank": 30,
                "banned_strategies": ["credit_put_spread"]
            }
        }
    ]

    results = run_agent_scenarios(StrategyDesignAgent, scenarios)
    results = serialize_results(results)

    expected = load_or_update_fixture("strategy_design_agent.json", results)
    assert_results_match(results, expected)


def test_sizing_agent_regression():
    scenarios = [
        {
            "name": "small_account_high_score",
            "context": {
                "deployable_capital": 500.0,
                "max_loss_per_contract": 50.0,
                "base_score": 90.0,
                "agent_signals": {}
            }
        },
        {
            "name": "large_account_low_score",
            "context": {
                "deployable_capital": 20000.0,
                "max_loss_per_contract": 50.0,
                "base_score": 20.0,
                "agent_signals": {}
            }
        },
        {
            "name": "veto_upstream",
            "context": {
                "deployable_capital": 5000.0,
                "max_loss_per_contract": 50.0,
                "base_score": 50.0,
                "agent_signals": {
                    "liquidity": {"veto": True, "score": 0.0}
                }
            }
        },
        {
            "name": "confluence_boost",
            "context": {
                "deployable_capital": 5000.0,
                "max_loss_per_contract": 50.0,
                "base_score": 50.0,
                "agent_signals": {
                    "regime": {"score": 80.0},
                    "vol": {"score": 80.0}
                }
            }
        },
        {
            "name": "confluence_penalty",
            "context": {
                "deployable_capital": 5000.0,
                "max_loss_per_contract": 50.0,
                "base_score": 50.0,
                "agent_signals": {
                    "liquidity": {"score": 30.0}
                }
            }
        },
        {
            "name": "buying_power_limit",
            "context": {
                "deployable_capital": 1000.0,
                "max_loss_per_contract": 50.0,
                "collateral_required_per_contract": 600.0, # max 1 contract
                "base_score": 90.0,
                "agent_signals": {}
            }
        }
    ]

    # Set milestones env
    os.environ["SIZING_MILESTONE_1000_MIN"] = "10"
    os.environ["SIZING_MILESTONE_1000_MAX"] = "35"
    os.environ["SIZING_MILESTONE_5000_MIN"] = "20"
    os.environ["SIZING_MILESTONE_5000_MAX"] = "75"
    os.environ["SIZING_MILESTONE_10000_MIN"] = "35"
    os.environ["SIZING_MILESTONE_10000_MAX"] = "150"
    os.environ["SIZING_MILESTONE_BIG_MIN"] = "50"
    os.environ["SIZING_MILESTONE_BIG_MAX"] = "250"

    results = run_agent_scenarios(SizingAgent, scenarios)
    results = serialize_results(results)

    expected = load_or_update_fixture("sizing_agent.json", results)
    assert_results_match(results, expected)
