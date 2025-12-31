import pytest
from packages.quantum.analytics.decision_lineage_diff import DecisionLineage, diff_lineage

@pytest.fixture
def base_lineage():
    return DecisionLineage(
        trace_id="trace_1",
        timestamp="2024-01-01T10:00:00Z",
        symbol="SPY",
        strategy_name="IRON_CONDOR",
        regime="NORMAL",
        iv_rank=50.0,
        sentiment="NEUTRAL",
        active_constraints=["max_risk_2pct"],
        agent_scores={"trend": 0.5, "vol": 0.4},
        selected_strategy="IRON_CONDOR",
        fallback_reason=None
    )

def test_no_changes(base_lineage):
    diff = diff_lineage(base_lineage, base_lineage)
    assert diff == {}

def test_constraints_added_removed(base_lineage):
    new_lineage = base_lineage.model_copy(update={
        "active_constraints": ["max_risk_2pct", "liquidity_check"]
    })

    diff = diff_lineage(base_lineage, new_lineage)
    assert diff == {"constraints_added": ["liquidity_check"]}

    new_lineage_2 = base_lineage.model_copy(update={
        "active_constraints": []
    })
    diff2 = diff_lineage(base_lineage, new_lineage_2)
    assert diff2 == {"constraints_removed": ["max_risk_2pct"]}

    new_lineage_3 = base_lineage.model_copy(update={
        "active_constraints": ["liquidity_check"]
    })
    diff3 = diff_lineage(base_lineage, new_lineage_3)
    assert diff3 == {
        "constraints_added": ["liquidity_check"],
        "constraints_removed": ["max_risk_2pct"]
    }

def test_agent_dominance_change(base_lineage):
    # Old dominant: trend (0.5)
    # New dominant: vol (0.6)
    new_lineage = base_lineage.model_copy(update={
        "agent_scores": {"trend": 0.5, "vol": 0.6}
    })

    diff = diff_lineage(base_lineage, new_lineage)
    assert diff == {
        "agent_dominance_change": {
            "from": "trend",
            "to": "vol"
        }
    }

def test_agent_dominance_tie_break(base_lineage):
    # Tie breaking should be deterministic (alphabetical)
    # trend=0.5, vol=0.5. 'trend' comes before 'vol'? No, alphabetical: trend vs vol.
    # T vs V. t > v? No. t < v? Yes.
    # sorted(key=lambda x: (-score, name))

    # "trend" vs "vol". "trend" < "vol".
    # score tie: 0.5.
    # ("trend", 0.5) vs ("vol", 0.5)
    # sort by -0.5, then name.
    # "trend" vs "vol". "trend" comes first alphabetically? No. "t" is after "v"? No.
    # a b c ... r s t u v
    # trend comes before vol.

    l1 = base_lineage.model_copy(update={"agent_scores": {"alpha": 0.5, "beta": 0.5}})
    # Dominant should be alpha.

    l2 = base_lineage.model_copy(update={"agent_scores": {"alpha": 0.5, "beta": 0.6}})
    # Dominant should be beta.

    diff = diff_lineage(l1, l2)
    assert diff == {
         "agent_dominance_change": {
            "from": "alpha",
            "to": "beta"
        }
    }

def test_strategy_fallback_change(base_lineage):
    # Case 1: No fallback -> Fallback
    new_lineage = base_lineage.model_copy(update={
        "selected_strategy": "HOLD",
        "fallback_reason": "Too risky"
    })

    diff = diff_lineage(base_lineage, new_lineage)
    assert diff == {
        "fallback_status_change": {
            "from": False,
            "to": True
        }
    }

    # Case 2: Fallback -> No fallback
    diff_back = diff_lineage(new_lineage, base_lineage)
    assert diff_back == {
        "fallback_status_change": {
            "from": True,
            "to": False
        }
    }

def test_fallback_details_change(base_lineage):
    # From fallback A to fallback B
    l1 = base_lineage.model_copy(update={
        "selected_strategy": "HOLD",
        "fallback_reason": "Reason A"
    })
    l2 = base_lineage.model_copy(update={
        "selected_strategy": "DEBIT_SPREAD",
        "fallback_reason": "Reason B"
    })

    diff = diff_lineage(l1, l2)
    assert "fallback_strategy_change" in diff
    assert diff["fallback_strategy_change"] == {"from": "HOLD", "to": "DEBIT_SPREAD"}
    assert "fallback_reason_change" in diff
    assert diff["fallback_reason_change"] == {"from": "Reason A", "to": "Reason B"}

    # Check if status change is NOT present (since both are fallbacks)
    assert "fallback_status_change" not in diff
