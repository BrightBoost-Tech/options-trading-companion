import pytest
from unittest.mock import MagicMock, patch
import os
from packages.quantum.discrete.models import (
    DiscreteSolveRequest, CandidateTrade, DiscreteParameters, DiscreteConstraints
)
from packages.quantum.discrete.solvers.qci_dirac import QciDiracDiscreteSolver
from packages.quantum.discrete.solvers.repair import greedy_repair
from packages.quantum.discrete.solvers.hybrid import HybridDiscreteSolver

# --- Fixtures ---

@pytest.fixture
def mock_candidates():
    return [
        CandidateTrade(id="c1", symbol="C1", side="buy", ev_per_unit=100.0, premium_per_unit=50.0, tail_risk_contribution=0.1, delta=0.1, gamma=0.01, vega=0.2, qty_max=5),
        CandidateTrade(id="c2", symbol="C2", side="buy", ev_per_unit=20.0, premium_per_unit=5.0, tail_risk_contribution=0.01, delta=0.05, gamma=0.005, vega=0.05, qty_max=10),
        CandidateTrade(id="c3", symbol="C3", side="buy", ev_per_unit=200.0, premium_per_unit=150.0, tail_risk_contribution=0.5, delta=0.2, gamma=0.02, vega=0.5, qty_max=3),
    ]

@pytest.fixture
def base_request(mock_candidates):
    return DiscreteSolveRequest(
        candidates=mock_candidates,
        parameters=DiscreteParameters(
            lambda_tail=1.0,
            lambda_cash=1.0,
            lambda_vega=0.0,
            lambda_delta=0.0,
            lambda_gamma=0.0,
            mode='hybrid',
            trial_mode=False
        ),
        constraints=DiscreteConstraints(
            max_cash=1000.0,
            max_contracts=20,
            max_vega=100.0,
            max_delta_abs=100.0,
            max_gamma=100.0
        )
    )

# --- Tests ---

def test_trial_mode_limits(base_request, mock_candidates):
    """Verify that trial mode applies caps and filters candidates."""
    # Enforce trial mode
    base_request.parameters.trial_mode = True

    # Create many candidates (over 40 to trigger strict skip, or 25 to trigger sort)
    # Let's try 30 candidates
    many_candidates = []
    for i in range(30):
        many_candidates.append(CandidateTrade(
            id=f"gen_{i}",
            symbol=f"GEN_{i}",
            side="buy",
            ev_per_unit=10 + i,
            premium_per_unit=5,
            tail_risk_contribution=0.1,
            delta=0, gamma=0, vega=0, qty_max=1
        ))
    base_request.candidates = many_candidates

    with patch.dict(os.environ, {"QCI_API_TOKEN": "mock_token"}):
        with patch("packages.quantum.core.qci_adapter.QciClient"):
            solver = QciDiracDiscreteSolver()

            # Mock adapter to avoid network
            solver.adapter = MagicMock()
            solver.adapter.solve_polynomial_custom.return_value = {"samples": [[0]*25], "energies": [0]}

            resp = solver.solve(base_request)

    # In trial mode, candidates should be capped to 25
    # The solver reduces the request.candidates list IN PLACE or passes reduced list to builder.
    # But wait, QciDiracDiscreteSolver modifies req.candidates in place in my implementation:
    # "req.candidates = sorted_cands[:candidate_cap]"

    # Let's check diagnostics
    assert resp.status == "ok"
    assert resp.diagnostics["trial_mode"] == True

    # Verify adapter called with correct params
    args, kwargs = solver.adapter.solve_polynomial_custom.call_args
    job_params = kwargs["job_params"]
    assert job_params["num_samples"] <= 5
    assert job_params["timeout"] <= 10

    # Verify polynomial size corresponds to 25 candidates
    polynomial = kwargs["polynomial"]
    # 25 linear terms at least
    linear_terms = [t for t in polynomial if len(t["terms"]) == 1 and t["terms"][0]["power"] == 1]
    assert len(linear_terms) == 25

def test_trial_mode_skip_excessive(base_request):
    """Verify solver skips if too many candidates provided in trial mode."""
    base_request.parameters.trial_mode = True
    # 41 candidates
    base_request.candidates = [CandidateTrade(id=f"c{i}", symbol=f"C{i}", side="buy", ev=1, premium=1, tail=0, ev_per_unit=1, premium_per_unit=1, tail_risk_contribution=0, delta=0, gamma=0, vega=0, qty_max=1) for i in range(41)]

    with patch.dict(os.environ, {"QCI_API_TOKEN": "mock_token"}):
        with patch("packages.quantum.core.qci_adapter.QciClient"):
            solver = QciDiracDiscreteSolver()
            resp = solver.solve(base_request)

            assert resp.status == "skipped"
    assert "Too many candidates" in resp.diagnostics["reason"]

def test_greedy_repair_logic(base_request):
    """Verify repair reduces quantities to fit constraints."""
    # Constraint: Max cash = 100
    base_request.constraints.max_cash = 100.0

    # Solution that violates:
    # c1: cost 50, qty 3 => 150 cost. (Violates 100)
    # c2: cost 5, qty 1 => 5 cost.

    initial_qty = {"c1": 3, "c2": 1}

    # c1 EV/Cost = 100/50 = 2
    # c2 EV/Cost = 20/5 = 4
    # c1 is less efficient, should be cut first.

    repaired = greedy_repair(base_request, initial_qty)

    # Expect c1 reduced until total cost <= 100
    # 3*50 + 5 = 155 > 100
    # 2*50 + 5 = 105 > 100
    # 1*50 + 5 = 55 <= 100 -> OK

    assert repaired["c1"] == 1
    assert repaired["c2"] == 1

def test_thresholding_and_rounding(base_request):
    """Verify post-processing thresholds and rounds correctly."""
    with patch.dict(os.environ, {"QCI_API_TOKEN": "mock_token"}):
        with patch("packages.quantum.core.qci_adapter.QciClient"):
            solver = QciDiracDiscreteSolver()
            solver.adapter = MagicMock()

            # Mock return: [0.05, 0.9, 1.2]
            # 0.05 -> < 0.1 -> 0
            # 0.9 -> 1
            # 1.2 -> 1 (clamped if qty_max=1, let's see)

            # c1 qty_max=5
            # c2 qty_max=10
            # c3 qty_max=3

            solver.adapter.solve_polynomial_custom.return_value = {
                "samples": [[0.05, 0.9, 4.8]],
                "energies": [-100]
            }

            resp = solver.solve(base_request)

            selected = {t.id: t.qty for t in resp.selected_trades}

            # c1 (idx 0): 0.05 -> 0
            assert "c1" not in selected

            # c2 (idx 1): 0.9 -> 1
            assert selected["c2"] == 1

            # c3 (idx 2): 4.8 -> 5 -> clamped to qty_max=3
            assert selected["c3"] == 3
    # 0.05 -> < 0.1 -> 0
    # 0.9 -> 1
    # 1.2 -> 1 (clamped if qty_max=1, let's see)

    # c1 qty_max=5
    # c2 qty_max=10
    # c3 qty_max=3

    solver.adapter.solve_polynomial_custom.return_value = {
        "samples": [[0.05, 0.9, 4.8]],
        "energies": [-100]
    }

    resp = solver.solve(base_request)

    selected = {t.id: t.qty for t in resp.selected_trades}

    # c1 (idx 0): 0.05 -> 0
    assert "c1" not in selected

    # c2 (idx 1): 0.9 -> 1
    assert selected["c2"] == 1

    # c3 (idx 2): 4.8 -> 5 -> clamped to qty_max=3
    assert selected["c3"] == 3

def test_hybrid_fallback(base_request):
    """Verify hybrid solver falls back silently if QCI fails."""

    # Mock QCI env var
    with patch.dict(os.environ, {"QCI_API_TOKEN": "test_token"}):
        with patch('packages.quantum.discrete.solvers.hybrid.QciDiracDiscreteSolver') as MockQci:
            # Setup mock to raise exception
            instance = MockQci.return_value
            instance.solve.side_effect = Exception("Connection Refused")

            resp = HybridDiscreteSolver.solve(base_request)

            assert resp.status == "ok"
            assert resp.strategy_used == "classical"
            assert "Quantum solver exception" in resp.diagnostics["fallback_reason"]

def test_hybrid_success(base_request):
    """Verify hybrid solver uses Quantum result if success."""

    with patch.dict(os.environ, {"QCI_API_TOKEN": "test_token"}):
        with patch('packages.quantum.discrete.solvers.hybrid.QciDiracDiscreteSolver') as MockQci:
            instance = MockQci.return_value

            # Mock success response
            from packages.quantum.discrete.models import DiscreteSolveResponse, DiscreteSolveMetrics
            instance.solve.return_value = DiscreteSolveResponse(
                status="ok",
                strategy_used="dirac3",
                selected_trades=[],
                metrics=DiscreteSolveMetrics(
                    expected_profit=100, total_premium=0, tail_risk_value=0,
                    delta=0, gamma=0, vega=0, objective_value=0, runtime_ms=10
                ),
                diagnostics={}
            )

            resp = HybridDiscreteSolver.solve(base_request)

            assert resp.status == "ok"
            assert resp.strategy_used == "dirac3"
