import pytest
import os
from unittest.mock import patch
from quantum.discrete.solvers.hybrid import HybridDiscreteSolver
from quantum.discrete.models import (
    DiscreteSolveRequest,
    DiscreteConstraints,
    DiscreteParameters,
    CandidateTrade
)

@pytest.fixture
def base_request():
    candidates = [
        CandidateTrade(
            id="t1", symbol="AAPL", side="buy", qty_max=1,
            ev_per_unit=10, premium_per_unit=5,
            delta=0.5, gamma=0.01, vega=0.1, tail_risk_contribution=0.2
        )
    ]
    constraints = DiscreteConstraints(
        max_cash=1000, max_vega=10, max_delta_abs=5, max_gamma=1
    )
    parameters = DiscreteParameters(
        lambda_tail=1, lambda_cash=1, lambda_vega=1, lambda_delta=1, lambda_gamma=1,
        mode="hybrid",
        max_candidates_for_dirac=10
    )
    return DiscreteSolveRequest(
        candidates=candidates,
        constraints=constraints,
        parameters=parameters
    )

class TestHybridDiscreteSolver:

    def test_classical_only_returns_classical(self, base_request):
        solver = HybridDiscreteSolver()
        base_request.parameters.mode = 'classical_only'

        with patch.dict(os.environ, {"QCI_API_TOKEN": "valid_token"}):
            resp = solver.solve(base_request)

        assert resp.strategy_used == "classical"
        assert resp.status == "success"

    def test_hybrid_without_token_falls_back(self, base_request):
        solver = HybridDiscreteSolver()
        base_request.parameters.mode = 'hybrid'

        # Ensure token is missing
        with patch.dict(os.environ, {}, clear=True):
            resp = solver.solve(base_request)

        assert resp.strategy_used == "classical"
        assert resp.diagnostics['fallback_reason'] == "missing_qci_token"

    def test_hybrid_too_many_candidates_falls_back(self, base_request):
        solver = HybridDiscreteSolver()
        base_request.parameters.mode = 'hybrid'
        base_request.parameters.max_candidates_for_dirac = 0 # Force limit

        with patch.dict(os.environ, {"QCI_API_TOKEN": "valid_token"}):
            resp = solver.solve(base_request)

        assert resp.strategy_used == "classical"
        assert "too_many_candidates" in resp.diagnostics['fallback_reason']

    def test_hybrid_trial_mode_falls_back(self, base_request):
        solver = HybridDiscreteSolver()
        base_request.parameters.mode = 'hybrid'
        base_request.parameters.trial_mode = True

        with patch.dict(os.environ, {"QCI_API_TOKEN": "valid_token"}):
            resp = solver.solve(base_request)

        assert resp.strategy_used == "classical"
        assert resp.diagnostics['fallback_reason'] == "trial_mode_active"

    def test_quantum_only_without_token_errors(self, base_request):
        solver = HybridDiscreteSolver()
        base_request.parameters.mode = 'quantum_only'

        with patch.dict(os.environ, {}, clear=True):
            resp = solver.solve(base_request)

        assert resp.status == "error"
        assert "missing QCI_API_TOKEN" in resp.diagnostics.get("error", "")

    def test_quantum_only_with_token_attempts_dirac(self, base_request):
        solver = HybridDiscreteSolver()
        base_request.parameters.mode = 'quantum_only'

        with patch.dict(os.environ, {"QCI_API_TOKEN": "valid_token"}):
            # Expect NotImplementedError as stub raises it
            with pytest.raises(NotImplementedError):
                solver.solve(base_request)

    def test_hybrid_attempts_dirac_if_valid(self, base_request):
        solver = HybridDiscreteSolver()
        base_request.parameters.mode = 'hybrid'
        base_request.parameters.trial_mode = False

        with patch.dict(os.environ, {"QCI_API_TOKEN": "valid_token"}):
             with pytest.raises(NotImplementedError):
                solver.solve(base_request)
