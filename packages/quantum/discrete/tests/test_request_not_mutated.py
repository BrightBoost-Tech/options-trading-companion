import pytest
from packages.quantum.discrete.models import DiscreteSolveRequest, CandidateTrade, DiscreteParameters, DiscreteConstraints
from packages.quantum.discrete.solvers.qci_dirac import QciDiracDiscreteSolver
from unittest.mock import MagicMock, patch

@patch('packages.quantum.discrete.solvers.qci_dirac.QciDiracAdapter')
def test_request_not_mutated(MockAdapter):
    # Create request with many candidates to trigger trimming in trial mode
    candidates = [
        CandidateTrade(id=f"c{i}", symbol=f"C{i}", side="buy", ev_per_unit=i, premium_per_unit=1, tail_risk_contribution=0.1, qty_max=1, delta=0.1, gamma=0.01, vega=0.1)
        for i in range(50)
    ]

    # Copy for verification
    original_ids = [c.id for c in candidates]
    original_len = len(candidates)

    req = DiscreteSolveRequest(
        candidates=candidates,
        constraints=DiscreteConstraints(max_cash=1000, max_vega=100, max_delta_abs=100, max_gamma=100),
        parameters=DiscreteParameters(trial_mode=True, num_samples=1, lambda_tail=1, lambda_cash=1, lambda_vega=1, lambda_delta=1, lambda_gamma=1, mode='hybrid')
    )

    # Setup mock
    mock_instance = MockAdapter.return_value
    mock_instance.solve_polynomial_custom.return_value = {
        "samples": [[1] * 25], # Assume it trimmed to 25
        "energies": [0]
    }

    solver = QciDiracDiscreteSolver()

    # Solve
    solver.solve(req)

    # Verify req.candidates is untouched
    assert len(req.candidates) == original_len
    assert [c.id for c in req.candidates] == original_ids
    # Specifically check it wasn't trimmed to 25
    assert len(req.candidates) == 50
