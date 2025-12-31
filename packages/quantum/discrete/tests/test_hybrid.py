import pytest
import os
import sys
from unittest.mock import patch, MagicMock
from packages.quantum.discrete.models import (
    DiscreteSolveRequest, DiscreteSolveResponse, CandidateTrade,
    DiscreteConstraints, DiscreteParameters, DiscreteSolveMetrics
)
from packages.quantum.discrete.solvers import hybrid

@pytest.fixture
def basic_request():
    c1 = CandidateTrade(
        id="c1", symbol="AAPL", side="buy",
        qty_max=10, premium_per_unit=1.0, ev_per_unit=2.0,
        delta=0.5, gamma=0.01, vega=0.1,
        tail_risk_contribution=0.0
    )
    c2 = CandidateTrade(
        id="c2", symbol="GOOG", side="buy",
        qty_max=5, premium_per_unit=2.0, ev_per_unit=5.0,
        delta=0.2, gamma=0.02, vega=0.2,
        tail_risk_contribution=0.1
    )
    return DiscreteSolveRequest(
        candidates=[c1, c2],
        constraints=DiscreteConstraints(
            max_cash=100.0,
            max_vega=1.0,
            max_delta_abs=10.0,
            max_gamma=1.0
        ),
        parameters=DiscreteParameters(
            mode="hybrid",
            lambda_tail=1.0,
            lambda_cash=1.0,
            lambda_vega=1.0,
            lambda_delta=1.0,
            lambda_gamma=1.0
        )
    )

@pytest.fixture
def mock_qci_available():
    """Forces QCI_AVAILABLE=True and injects a Mock solver class."""
    original_avail = hybrid.QCI_AVAILABLE
    original_solver = getattr(hybrid, 'QciDiracDiscreteSolver', None)

    hybrid.QCI_AVAILABLE = True
    mock_solver_cls = MagicMock()
    hybrid.QciDiracDiscreteSolver = mock_solver_cls

    yield mock_solver_cls

    # Restore
    hybrid.QCI_AVAILABLE = original_avail
    if original_solver:
        hybrid.QciDiracDiscreteSolver = original_solver
    else:
        # If it wasn't there originally, remove it
        if hasattr(hybrid, 'QciDiracDiscreteSolver'):
             del hybrid.QciDiracDiscreteSolver

def test_hybrid_classical_fallback_no_token(basic_request):
    """Hybrid mode without token should return classical ok response."""
    with patch.dict(os.environ, {}, clear=True):
        resp = hybrid.HybridDiscreteSolver.solve(basic_request)
        assert resp.status == "ok"
        assert resp.strategy_used == "classical"
        assert "fallback_reason" in resp.diagnostics
        assert len(resp.selected_trades) > 0

def test_classical_only_always_classical(basic_request, mock_qci_available):
    """Classical only mode should never try quantum even if token exists."""
    basic_request.parameters.mode = "classical_only"

    with patch.dict(os.environ, {"QCI_API_TOKEN": "fake"}, clear=True):
        resp = hybrid.HybridDiscreteSolver.solve(basic_request)
        assert resp.status == "ok"
        assert resp.strategy_used == "classical"
        mock_qci_available.assert_not_called()

def test_quantum_only_success(basic_request, mock_qci_available):
    """Quantum only with token and success response."""
    basic_request.parameters.mode = "quantum_only"

    # Setup mock return
    mock_instance = mock_qci_available.return_value
    mock_instance.solve.return_value = DiscreteSolveResponse(
        status="ok",
        strategy_used="dirac3",
        selected_trades=[],
        metrics=DiscreteSolveMetrics(
            expected_profit=0.0, total_premium=0.0, tail_risk_value=0.0,
            delta=0.0, gamma=0.0, vega=0.0, objective_value=0.0, runtime_ms=0.0
        ),
        diagnostics={}
    )

    with patch.dict(os.environ, {"QCI_API_TOKEN": "fake"}, clear=True):
        resp = hybrid.HybridDiscreteSolver.solve(basic_request)
        assert resp.status == "ok"
        assert resp.strategy_used == "dirac3"

def test_quantum_only_missing_token(basic_request, mock_qci_available):
    """Quantum only without token should error."""
    basic_request.parameters.mode = "quantum_only"

    # Even if QCI available locally, missing token prevents usage
    with patch.dict(os.environ, {}, clear=True):
        resp = hybrid.HybridDiscreteSolver.solve(basic_request)
        assert resp.status == "error"
        assert "unavailable" in resp.diagnostics.get("reason", "")

def test_quantum_only_solver_error(basic_request, mock_qci_available):
    """Quantum only should return error if solver fails/skips."""
    basic_request.parameters.mode = "quantum_only"

    mock_instance = mock_qci_available.return_value
    mock_instance.solve.return_value = DiscreteSolveResponse(
        status="error",
        strategy_used="dirac3",
        selected_trades=[],
        metrics=DiscreteSolveMetrics(
            expected_profit=0.0, total_premium=0.0, tail_risk_value=0.0,
            delta=0.0, gamma=0.0, vega=0.0, objective_value=0.0, runtime_ms=0.0
        ),
        diagnostics={"reason": "Too many candidates"}
    )

    with patch.dict(os.environ, {"QCI_API_TOKEN": "fake"}, clear=True):
        resp = hybrid.HybridDiscreteSolver.solve(basic_request)
        assert resp.status == "error"
        assert resp.diagnostics["reason"] == "Too many candidates"

def test_hybrid_fallback_on_solver_error(basic_request, mock_qci_available):
    """Hybrid should fallback if solver returns error."""
    basic_request.parameters.mode = "hybrid"

    mock_instance = mock_qci_available.return_value
    mock_instance.solve.return_value = DiscreteSolveResponse(
        status="error",
        strategy_used="dirac3",
        selected_trades=[],
        metrics=DiscreteSolveMetrics(
            expected_profit=0.0, total_premium=0.0, tail_risk_value=0.0,
            delta=0.0, gamma=0.0, vega=0.0, objective_value=0.0, runtime_ms=0.0
        ),
        diagnostics={"reason": "Too many candidates"}
    )

    with patch.dict(os.environ, {"QCI_API_TOKEN": "fake"}, clear=True):
        resp = hybrid.HybridDiscreteSolver.solve(basic_request)
        assert resp.status == "ok"
        assert resp.strategy_used == "classical"
        assert "fallback_reason" in resp.diagnostics

def test_empty_candidates(basic_request):
    """Empty candidates should return ok with empty selected_trades."""
    basic_request.candidates = []

    resp = hybrid.HybridDiscreteSolver.solve(basic_request)
    assert resp.status == "ok"
    assert len(resp.selected_trades) == 0

def test_qty_max_zero(basic_request):
    """Candidates with qty_max=0 should never be selected."""
    c = basic_request.candidates[0]
    c.qty_max = 0
    basic_request.candidates = [c]

    resp = hybrid.HybridDiscreteSolver.solve(basic_request)
    assert resp.status == "ok"
    assert len(resp.selected_trades) == 0
