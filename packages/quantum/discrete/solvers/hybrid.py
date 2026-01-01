import os
import time
from typing import Optional, Dict, Any, List
from packages.quantum.discrete.models import (
    DiscreteSolveRequest,
    DiscreteSolveResponse,
    DiscreteSolveMetrics,
    SelectedTrade,
    CandidateTrade
)
from packages.quantum.discrete.solvers.classical import ClassicalDiscreteSolver
from packages.quantum.discrete.solvers.qci_dirac import QciDiracDiscreteSolver

class HybridDiscreteSolver:
    """
    Orchestrates the selection between Quantum (Dirac) and Classical solvers
    based on availability, request parameters, and constraints.
    """

    def __init__(self):
        self.classical_solver = ClassicalDiscreteSolver()
        self.dirac_solver = QciDiracDiscreteSolver()

    def solve(self, req: DiscreteSolveRequest) -> DiscreteSolveResponse:
        mode = req.parameters.mode
        qci_token = os.environ.get("QCI_API_TOKEN")
        trial_mode = req.parameters.trial_mode
        candidate_count = len(req.candidates)
        max_candidates = req.parameters.max_candidates_for_dirac or 100

        # Determine basic availability
        has_token = bool(qci_token)

        # 1. Classical Only
        if mode == 'classical_only':
            return self._solve_classical(req)

        # 2. Quantum Only
        if mode == 'quantum_only':
            error_reason = None
            if not has_token:
                error_reason = "missing QCI_API_TOKEN"
            # In new logic, trial_mode doesn't automatically mean fallback,
            # but if trial_mode is active and we want to enforce skipping Dirac if budget exhausted:
            # The dirac solver handles budget check and returns empty/skipped.
            # If we enforce Quantum Only, we accept whatever Dirac gives (including empty due to budget).

            if error_reason:
                return DiscreteSolveResponse(
                    status="error",
                    strategy_used="classical",
                    selected_trades=[],
                    metrics=self._empty_metrics(),
                    diagnostics={"error": f"Quantum solver unavailable ({error_reason})"}
                )

            try:
                return self.dirac_solver.solve(req)
            except Exception as e:
                 return DiscreteSolveResponse(
                    status="error",
                    strategy_used="dirac3",
                    selected_trades=[],
                    metrics=self._empty_metrics(),
                    diagnostics={"error": str(e)}
                )

        # 3. Hybrid (Default)
        # Try Quantum, fallback to Classical if it fails OR if budget exhausted

        # Check basic eligibility for Quantum
        if has_token and (candidate_count <= max_candidates):
            try:
                # Attempt Quantum solve
                response = self.dirac_solver.solve(req)

                # Check if it was skipped due to budget
                if response.diagnostics.get("reason") == "dirac_trial_budget_exhausted":
                     # Fallback to classical
                     classical_resp = self._solve_classical(req)
                     classical_resp.diagnostics["fallback_reason"] = "dirac_trial_budget_exhausted"
                     classical_resp.diagnostics["trial_mode"] = True
                     return classical_resp

                return response

            except Exception as e:
                # Log error and fallback
                # In a real app we'd log this.
                pass

        # Fallback to classical
        resp = self._solve_classical(req)
        resp.diagnostics["fallback_reason"] = "quantum_unavailable_or_failed"
        return resp

    def _solve_classical(self, req: DiscreteSolveRequest) -> DiscreteSolveResponse:
        return self.classical_solver.solve(req)

    def _empty_metrics(self) -> DiscreteSolveMetrics:
        return DiscreteSolveMetrics(
            expected_profit=0.0,
            total_premium=0.0,
            tail_risk_value=0.0,
            delta=0.0,
            gamma=0.0,
            vega=0.0,
            objective_value=0.0,
            runtime_ms=0.0
        )
