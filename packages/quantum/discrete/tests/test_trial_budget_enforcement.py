import os
import pytest
from unittest.mock import MagicMock, patch
from packages.quantum.discrete.models import DiscreteSolveRequest, CandidateTrade, DiscreteParameters, DiscreteConstraints
from packages.quantum.discrete.solvers.qci_dirac import QciDiracDiscreteSolver

@pytest.fixture
def mock_req():
    return DiscreteSolveRequest(
        candidates=[
            CandidateTrade(id="c1", symbol="C1", side="buy", ev_per_unit=100, premium_per_unit=10, tail_risk_contribution=0.1, qty_max=5, delta=0.1, gamma=0.01, vega=0.1),
            CandidateTrade(id="c2", symbol="C2", side="buy", ev_per_unit=150, premium_per_unit=20, tail_risk_contribution=0.2, qty_max=5, delta=0.1, gamma=0.01, vega=0.1),
            CandidateTrade(id="c3", symbol="C3", side="buy", ev_per_unit=80, premium_per_unit=5, tail_risk_contribution=0.05, qty_max=5, delta=0.1, gamma=0.01, vega=0.1),
        ],
        constraints=DiscreteConstraints(max_cash=1000, max_contracts=10, max_vega=100, max_delta_abs=100, max_gamma=100),
        parameters=DiscreteParameters(trial_mode=True, max_dirac_calls=2, lambda_tail=1, lambda_cash=1, lambda_vega=1, lambda_delta=1, lambda_gamma=1, mode='hybrid')
    )

@patch('packages.quantum.discrete.solvers.qci_dirac.QciDiracAdapter')
def test_trial_budget_enforcement(MockAdapter, mock_req):
    # Reset budget
    QciDiracDiscreteSolver._reset_trial_budget_for_tests()

    # Setup mock adapter instance
    mock_instance = MockAdapter.return_value
    mock_instance.solve_polynomial_custom.return_value = {
        "samples": [[1, 0, 0]],
        "energies": [-100]
    }

    solver = QciDiracDiscreteSolver()

    # Call 1
    resp1 = solver.solve(mock_req)
    assert resp1.status == "ok"
    assert mock_instance.solve_polynomial_custom.call_count == 1
    assert resp1.diagnostics["dirac_calls_used"] == 1

    # Call 2
    resp2 = solver.solve(mock_req)
    assert resp2.status == "ok"
    assert mock_instance.solve_polynomial_custom.call_count == 2
    assert resp2.diagnostics["dirac_calls_used"] == 2

    # Call 3 (Should skip adapter)
    resp3 = solver.solve(mock_req)
    assert resp3.status == "skipped"  # Changed from "ok"
    # Call count should still be 2
    assert mock_instance.solve_polynomial_custom.call_count == 2
    assert resp3.diagnostics["reason"] == "dirac_trial_budget_exhausted"
    assert resp3.diagnostics["used"] == 2

@patch('packages.quantum.discrete.solvers.qci_dirac.QciDiracAdapter')
def test_no_budget_in_prod(MockAdapter, mock_req):
    # Reset budget
    QciDiracDiscreteSolver._reset_trial_budget_for_tests()

    # Setup mock
    mock_instance = MockAdapter.return_value
    mock_instance.solve_polynomial_custom.return_value = {"samples": [[1, 0, 0]], "energies": [-100]}

    # Disable trial mode
    mock_req.parameters.trial_mode = False

    solver = QciDiracDiscreteSolver()

    # Run 3 times
    for _ in range(3):
        solver.solve(mock_req)

    assert mock_instance.solve_polynomial_custom.call_count == 3
