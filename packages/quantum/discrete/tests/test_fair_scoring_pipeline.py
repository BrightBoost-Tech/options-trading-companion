import pytest
from packages.quantum.discrete.models import DiscreteSolveRequest, CandidateTrade, DiscreteConstraints, DiscreteParameters
from packages.quantum.discrete.solvers.postprocess import postprocess_and_score

def test_fair_scoring_pipeline():
    # Setup: 2 candidates.
    # c1: cost 10, ev 100
    # c2: cost 10, ev 50
    # max_cash: 15
    # If we select 1 of each, cost is 20 > 15. Violation.
    # Repair should drop c2 (lower efficiency 50/10=5 vs 100/10=10).

    candidates = [
        CandidateTrade(id="c1", symbol="C1", side="buy", ev_per_unit=100, premium_per_unit=10, tail_risk_contribution=0.1, qty_max=1, delta=0.1, gamma=0.01, vega=0.1),
        CandidateTrade(id="c2", symbol="C2", side="buy", ev_per_unit=50, premium_per_unit=10, tail_risk_contribution=0.1, qty_max=1, delta=0.1, gamma=0.01, vega=0.1)
    ]

    req = DiscreteSolveRequest(
        candidates=candidates,
        constraints=DiscreteConstraints(max_cash=15, max_vega=100, max_delta_abs=100, max_gamma=100),
        parameters=DiscreteParameters(lambda_tail=1, lambda_cash=1, lambda_vega=1, lambda_delta=1, lambda_gamma=1, mode='hybrid')
    )

    # Infeasible qty map
    qty_map = {"c1": 1, "c2": 1}

    # Run pipeline
    qty_map_fixed, components, obj_val, check, diag = postprocess_and_score(req, qty_map)

    # Assertions
    assert diag["repaired"] is True
    # Should have kept c1, dropped c2
    assert qty_map_fixed.get("c1") == 1
    assert qty_map_fixed.get("c2", 0) == 0

    # Verify feasibility
    assert check["ok"] is True
    assert components["total_premium"] == 10

    # Verify objective calculated
    assert obj_val is not None
