import pytest
from packages.quantum.discrete.models import DiscreteSolveRequest, CandidateTrade, OptimizationParameters, OptimizationConstraints
from packages.quantum.discrete.objective import compute_components, check_hard_constraints, objective_value

@pytest.fixture
def sample_candidates():
    return [
        CandidateTrade(
            id="trade_a",
            ev_per_unit=100.0,
            premium_per_unit=50.0,
            tail_risk_contribution=1.0,
            delta=0.5,
            gamma=0.1,
            vega=2.0
        ),
        CandidateTrade(
            id="trade_b",
            ev_per_unit=200.0,
            premium_per_unit=80.0,
            tail_risk_contribution=2.0,
            delta=-0.2,
            gamma=0.05,
            vega=3.0
        )
    ]

@pytest.fixture
def basic_request(sample_candidates):
    return DiscreteSolveRequest(
        candidates=sample_candidates,
        parameters=OptimizationParameters(
            lambda_tail=0.1,
            lambda_cash=1.0,
            lambda_vega=0.5
        ),
        constraints=OptimizationConstraints(
            max_cash=100.0,
            max_vega=4.0
        )
    )

def test_compute_components_empty(basic_request):
    q_by_id = {}
    comps = compute_components(basic_request, q_by_id)
    assert comps["expected_profit"] == 0.0
    assert comps["total_premium"] == 0.0
    assert comps["tail_risk_value"] == 0.0
    assert comps["delta"] == 0.0
    assert comps["quantity_total"] == 0

def test_compute_components_basic(basic_request):
    q_by_id = {"trade_a": 1, "trade_b": 1}
    comps = compute_components(basic_request, q_by_id)

    # Expected Profit: 100 + 200 = 300
    assert comps["expected_profit"] == 300.0
    # Premium: 50 + 80 = 130
    assert comps["total_premium"] == 130.0
    # Tail Risk: (1 + 2)^2 = 9
    assert comps["tail_risk_value"] == 9.0
    # Vega: 2 + 3 = 5
    assert comps["vega"] == 5.0
    # Delta: 0.5 - 0.2 = 0.3
    assert abs(comps["delta"] - 0.3) < 1e-9

def test_check_hard_constraints(basic_request):
    # Case 1: Violation
    # max_cash=100, actual=130 (from trade_a=1, trade_b=1)
    q_by_id = {"trade_a": 1, "trade_b": 1}
    comps = compute_components(basic_request, q_by_id)
    result = check_hard_constraints(basic_request, comps)

    assert result["ok"] is False
    assert "max_cash" in result["violations"]
    assert result["violations"]["max_cash"] == 130.0
    assert "max_vega" in result["violations"] # max_vega=4, actual=5

    # Case 2: No Violation
    # Trade A only: Prem=50 (<=100), Vega=2 (<=4)
    q_by_id_safe = {"trade_a": 1}
    comps_safe = compute_components(basic_request, q_by_id_safe)
    result_safe = check_hard_constraints(basic_request, comps_safe)
    assert result_safe["ok"] is True
    assert len(result_safe["violations"]) == 0

def test_objective_value(basic_request):
    # Use the example from dry-run
    # q = {A:1, B:1}
    # Net Profit = 300 - 130 = 170. Base Energy = -170.
    # Tail Penalty = 0.1 * 9 = 0.9
    # Cash Penalty = 1.0 * (130 - 100)^2 = 900
    # Vega Penalty = 0.5 * (5 - 4)^2 = 0.5
    # Total = -170 + 0.9 + 900 + 0.5 = 731.4

    q_by_id = {"trade_a": 1, "trade_b": 1}
    comps = compute_components(basic_request, q_by_id)
    val = objective_value(basic_request, comps)

    assert abs(val - 731.4) < 1e-9

def test_objective_improvement_with_ev(basic_request):
    # Test that higher EV reduces objective (better)
    # Baseline: Trade A only
    # Net Profit: 100 - 50 = 50. Energy = -50 + tail_penalty
    # Tail: 1^2 = 1. Penalty = 0.1.
    # Cash: 50 <= 100. Penalty = 0.
    # Vega: 2 <= 4. Penalty = 0.
    # Total = -49.9

    q_by_id = {"trade_a": 1}
    comps = compute_components(basic_request, q_by_id)
    val_1 = objective_value(basic_request, comps)
    assert abs(val_1 - (-49.9)) < 1e-9

    # Modify request to have higher EV for Trade A
    better_candidate = CandidateTrade(
        id="trade_a",
        ev_per_unit=150.0, # Increased by 50
        premium_per_unit=50.0,
        tail_risk_contribution=1.0,
        delta=0.5,
        gamma=0.1,
        vega=2.0
    )
    req_better = DiscreteSolveRequest(
        candidates=[better_candidate],
        parameters=basic_request.parameters,
        constraints=basic_request.constraints
    )

    comps_better = compute_components(req_better, q_by_id)
    val_2 = objective_value(req_better, comps_better)

    # Net Profit: 150 - 50 = 100. Energy = -100 + 0.1 = -99.9
    assert val_2 < val_1
    assert abs(val_2 - (-99.9)) < 1e-9

def test_tail_risk_quadratic_growth(basic_request):
    # 1 unit of A: tail sum = 1, val = 1
    # 2 units of A: tail sum = 2, val = 4 (quadratic)

    comps_1 = compute_components(basic_request, {"trade_a": 1})
    assert comps_1["tail_risk_value"] == 1.0

    comps_2 = compute_components(basic_request, {"trade_a": 2})
    assert comps_2["tail_risk_value"] == 4.0

    comps_3 = compute_components(basic_request, {"trade_a": 10})
    assert comps_3["tail_risk_value"] == 100.0

def test_missing_candidate_ignored(basic_request):
    q_by_id = {"trade_a": 1, "non_existent": 5}
    comps = compute_components(basic_request, q_by_id)

    # Should equal result for just trade_a
    comps_ref = compute_components(basic_request, {"trade_a": 1})

    assert comps == comps_ref

def test_constraints_skipped_if_none():
    # Setup request with no constraints and no lambdas
    candidates = [
        CandidateTrade(id="a", ev_per_unit=10, premium_per_unit=5, tail_risk_contribution=1)
    ]
    req = DiscreteSolveRequest(
        candidates=candidates,
        parameters=OptimizationParameters(), # all 0
        constraints=OptimizationConstraints() # all None
    )

    q_by_id = {"a": 100} # huge quantity
    comps = compute_components(req, q_by_id)

    # Check hard constraints - should pass as none set
    check = check_hard_constraints(req, comps)
    assert check["ok"] is True

    # Objective should just be -NetProfit
    # Profit=1000, Prem=500. Net=500. Energy=-500.
    val = objective_value(req, comps)
    assert val == -500.0
