import pytest
from discrete.models import (
    DiscreteSolveRequest,
    CandidateTrade,
    DiscreteConstraints,
    DiscreteParameters
)
from discrete.solvers.classical import solve_classical

@pytest.fixture
def basic_request():
    candidates = [
        CandidateTrade(
            id="c1", symbol="AAPL", side="buy", qty_max=5,
            ev_per_unit=10.0, premium_per_unit=2.0,
            delta=0.5, gamma=0.1, vega=0.1, tail_risk_contribution=0.5
        ),
        CandidateTrade(
            id="c2", symbol="GOOG", side="buy", qty_max=3,
            ev_per_unit=12.0, premium_per_unit=10.0, # Less efficient EV/Premium, and low Utility (2)
            delta=0.2, gamma=0.05, vega=0.2, tail_risk_contribution=1.0
        ),
        CandidateTrade(
            id="c3", symbol="MSFT", side="buy", qty_max=10,
            ev_per_unit=5.0, premium_per_unit=1.0,
            delta=0.1, gamma=0.01, vega=0.05, tail_risk_contribution=0.1
        )
    ]
    constraints = DiscreteConstraints(
        max_cash=100.0,
        max_vega=10.0,
        max_delta_abs=50.0,
        max_gamma=10.0,
        max_contracts=10
    )
    params = DiscreteParameters(
        lambda_tail=0.1,
        lambda_cash=0.01,
        lambda_vega=0.0,
        lambda_delta=0.0,
        lambda_gamma=0.0,
        mode="classical_only"
    )
    return DiscreteSolveRequest(
        candidates=candidates,
        constraints=constraints,
        parameters=params
    )

def test_classical_empty_candidates():
    req = DiscreteSolveRequest(
        candidates=[],
        constraints=DiscreteConstraints(max_cash=100.0, max_vega=10, max_delta_abs=10, max_gamma=10),
        parameters=DiscreteParameters(lambda_tail=0.1, lambda_cash=0.0, lambda_vega=0, lambda_delta=0, lambda_gamma=0, mode="classical_only")
    )
    res = solve_classical(req)
    assert len(res.selected_trades) == 0
    assert res.metrics.expected_profit == 0
    assert res.status == "success"

def test_classical_greedy_selection(basic_request):
    # c1 is best (10/2=5, Util 8), c3 is next (5/1=5, Util 4), c2 is worst (12/10=1.2, Util 2)
    # Greedy should fill c1, then c3, then c2
    # Constraints: max_contracts=10
    # c1: qty 5. Remaining contracts: 5.
    # c3: qty 5 (out of 10). Remaining contracts: 0.
    # c2: qty 0.
    # Local search should NOT swap because c2 has lower utility per contract AND per dollar.

    res = solve_classical(basic_request)

    selected_map = {t.id: t.qty for t in res.selected_trades}

    assert selected_map.get("c1") == 5
    assert selected_map.get("c3") == 5
    assert "c2" not in selected_map

    # Utility dominates penalties (EV positive)
    # Check that objective_value is correctly populated (can be negative due to negative utility term)
    assert res.metrics.objective_value < 0

def test_classical_max_cash_constraint(basic_request):
    # Set max_cash very low
    basic_request.constraints.max_cash = 5.0
    # c1 costs 2. c3 costs 1.
    # c1 ratio 5, c3 ratio 5. Stable sort might pick c1 first.
    # c1 * 2 = 4 (cost 4). Remaining cash 1.
    # c3 * 1 = 1 (cost 1). Total cost 5.
    # Total: 2 units c1 + 1 unit c3? Or 2.5? Discrete.
    # Greedy order: c1 (ratio 5), c3 (ratio 5).
    # If tie, original order? c1 then c3.
    # Try c1: qty 1 (cost 2). ok.
    # Try c1: qty 2 (cost 4). ok.
    # Try c1: qty 3 (cost 6) -> Fail. Backtrack to 2.
    # Remaining: c3.
    # Try c3: qty 1 (cost 1 + 4 = 5). ok.
    # Try c3: qty 2 (cost 2 + 4 = 6) -> Fail.

    res = solve_classical(basic_request)
    selected_map = {t.id: t.qty for t in res.selected_trades}

    total_cost = (selected_map.get("c1", 0) * 2.0) + (selected_map.get("c3", 0) * 1.0)
    assert total_cost <= 5.0
    assert total_cost > 0 # Should pick something

def test_classical_improves_over_nothing():
    # Single candidate with positive EV, no penalties
    c = CandidateTrade(
        id="c1", symbol="A", side="buy", qty_max=1,
        ev_per_unit=100, premium_per_unit=10,
        delta=0, gamma=0, vega=0, tail_risk_contribution=0
    )
    req = DiscreteSolveRequest(
        candidates=[c],
        constraints=DiscreteConstraints(max_cash=100, max_vega=100, max_delta_abs=100, max_gamma=100),
        parameters=DiscreteParameters(lambda_tail=0, lambda_cash=0, lambda_vega=0, lambda_delta=0, lambda_gamma=0, mode="classical_only")
    )

    res = solve_classical(req)
    assert len(res.selected_trades) == 1
    # Energy = - (100 - 10) = -90. Nothing = 0.
    assert res.metrics.objective_value == -90.0

def test_local_search_improvement():
    # Construct a scenario where Greedy is suboptimal.
    # Knapsack problem:
    # Item A: Value 20, Weight 10 (Ratio 2.0)
    # Item B: Value 15, Weight 6 (Ratio 2.5)
    # Item C: Value 15, Weight 6 (Ratio 2.5)
    # Constraint Weight 10.

    # Greedy picks B (Weight 6). Remaining 4.
    # Cannot pick C (Weight 6).
    # Cannot pick A (Weight 10).
    # Total Value 15.

    # Optimal: Pick A (Weight 10, Value 20).

    c_A = CandidateTrade(
        id="A", symbol="A", side="buy", qty_max=1,
        ev_per_unit=25.0, premium_per_unit=10.0, # Ratio 2.5. Net Utility 15.
        delta=0, gamma=0, vega=0, tail_risk_contribution=0
    )
    c_B = CandidateTrade(
        id="B", symbol="B", side="buy", qty_max=1,
        ev_per_unit=18.0, premium_per_unit=6.0, # Ratio 3.0. Net Utility 12.
        delta=0, gamma=0, vega=0, tail_risk_contribution=0
    )
    c_C = CandidateTrade(
        id="C", symbol="C", side="buy", qty_max=1,
        ev_per_unit=18.0, premium_per_unit=6.0, # Ratio 3.0. Net Utility 12.
        delta=0, gamma=0, vega=0, tail_risk_contribution=0
    )

    req = DiscreteSolveRequest(
        candidates=[c_A, c_B, c_C],
        constraints=DiscreteConstraints(max_cash=10.0, max_vega=100, max_delta_abs=100, max_gamma=100),
        parameters=DiscreteParameters(lambda_tail=0, lambda_cash=0, lambda_vega=0, lambda_delta=0, lambda_gamma=0, mode="classical_only")
    )

    res = solve_classical(req)

    selected_ids = [t.id for t in res.selected_trades]
    assert "A" in selected_ids
    assert "B" not in selected_ids
    assert "C" not in selected_ids
    assert res.metrics.objective_value == -15.0
