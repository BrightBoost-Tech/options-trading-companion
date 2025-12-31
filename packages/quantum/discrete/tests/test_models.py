import pytest
import math
from pydantic import ValidationError
from packages.quantum.discrete.models import (
    CandidateTrade,
    DiscreteConstraints,
    DiscreteParameters,
    DiscreteSolveRequest,
    SelectedTrade,
    DiscreteSolveMetrics,
    DiscreteSolveResponse
)

def test_candidate_trade_validation():
    # Valid trade
    trade = CandidateTrade(
        id="t1",
        symbol="SPY",
        side="buy",
        qty_max=10,
        ev_per_unit=50.0,
        premium_per_unit=100.0,
        delta=0.5,
        gamma=0.01,
        vega=0.1,
        tail_risk_contribution=0.05
    )
    assert trade.id == "t1"
    assert trade.qty_max == 10

    # Invalid qty_max (negative)
    with pytest.raises(ValidationError):
        CandidateTrade(
            id="t2",
            symbol="SPY",
            side="buy",
            qty_max=-1,
            ev_per_unit=50.0,
            premium_per_unit=100.0,
            delta=0.5,
            gamma=0.01,
            vega=0.1,
            tail_risk_contribution=0.05
        )

    # Invalid side
    with pytest.raises(ValidationError):
        CandidateTrade(
            id="t3",
            symbol="SPY",
            side="hold",  # Invalid
            qty_max=10,
            ev_per_unit=50.0,
            premium_per_unit=100.0,
            delta=0.5,
            gamma=0.01,
            vega=0.1,
            tail_risk_contribution=0.05
        )

def test_candidate_trade_nan_rejection():
    # Test NaN rejection
    with pytest.raises(ValidationError) as excinfo:
        CandidateTrade(
            id="t_nan",
            symbol="SPY",
            side="buy",
            qty_max=10,
            ev_per_unit=float('nan'),
            premium_per_unit=100.0,
            delta=0.5,
            gamma=0.01,
            vega=0.1,
            tail_risk_contribution=0.05
        )
    assert "Values must be finite" in str(excinfo.value)

    # Test Inf rejection
    with pytest.raises(ValidationError) as excinfo:
        CandidateTrade(
            id="t_inf",
            symbol="SPY",
            side="buy",
            qty_max=10,
            ev_per_unit=float('inf'),
            premium_per_unit=100.0,
            delta=0.5,
            gamma=0.01,
            vega=0.1,
            tail_risk_contribution=0.05
        )
    assert "Values must be finite" in str(excinfo.value)

def test_constraints_nan_rejection():
    with pytest.raises(ValidationError) as excinfo:
        DiscreteConstraints(
            max_cash=float('nan'),
            max_vega=10.0,
            max_delta_abs=5.0,
            max_gamma=0.5
        )
    assert "Values must be finite" in str(excinfo.value)

def test_qty_max_zero_allowed():
    trade = CandidateTrade(
        id="t4",
        symbol="SPY",
        side="sell",
        qty_max=0,
        ev_per_unit=50.0,
        premium_per_unit=100.0,
        delta=0.5,
        gamma=0.01,
        vega=0.1,
        tail_risk_contribution=0.05
    )
    assert trade.qty_max == 0

def test_discrete_parameters_defaults():
    params = DiscreteParameters(
        lambda_tail=1.0,
        lambda_cash=1.0,
        lambda_vega=1.0,
        lambda_delta=1.0,
        lambda_gamma=1.0,
        mode="hybrid"
    )
    assert params.num_samples == 20
    assert params.max_candidates_for_dirac == 40
    assert params.max_dirac_calls == 2
    assert params.dirac_timeout_s == 10

def test_solve_request_structure():
    trade = CandidateTrade(
        id="t1",
        symbol="SPY",
        side="buy",
        qty_max=5,
        ev_per_unit=10.0,
        premium_per_unit=20.0,
        delta=0.1,
        gamma=0.01,
        vega=0.05,
        tail_risk_contribution=0.1
    )
    constraints = DiscreteConstraints(
        max_cash=1000.0,
        max_vega=10.0,
        max_delta_abs=5.0,
        max_gamma=0.5
    )
    params = DiscreteParameters(
        lambda_tail=1.0,
        lambda_cash=1.0,
        lambda_vega=1.0,
        lambda_delta=1.0,
        lambda_gamma=1.0,
        mode="classical_only"
    )

    request = DiscreteSolveRequest(
        candidates=[trade],
        constraints=constraints,
        parameters=params
    )

    assert len(request.candidates) == 1
    assert request.constraints.max_cash == 1000.0
    assert request.parameters.mode == "classical_only"

def test_empty_candidates_list():
    constraints = DiscreteConstraints(
        max_cash=1000.0,
        max_vega=10.0,
        max_delta_abs=5.0,
        max_gamma=0.5
    )
    params = DiscreteParameters(
        lambda_tail=1.0,
        lambda_cash=1.0,
        lambda_vega=1.0,
        lambda_delta=1.0,
        lambda_gamma=1.0,
        mode="classical_only"
    )

    request = DiscreteSolveRequest(
        candidates=[],
        constraints=constraints,
        parameters=params
    )
    assert len(request.candidates) == 0

def test_response_models():
    metrics = DiscreteSolveMetrics(
        expected_profit=100.0,
        total_premium=50.0,
        tail_risk_value=10.0,
        delta=0.5,
        gamma=0.1,
        vega=0.2,
        objective_value=5.0,
        runtime_ms=150.0
    )

    selected_trade = SelectedTrade(
        id="t1",
        qty=2,
        reason="Optimal EV"
    )

    response = DiscreteSolveResponse(
        status="success",
        strategy_used="classical",
        selected_trades=[selected_trade],
        metrics=metrics,
        diagnostics={"iterations": 100}
    )

    assert response.status == "success"
    assert response.strategy_used == "classical"
    assert response.metrics.expected_profit == 100.0
