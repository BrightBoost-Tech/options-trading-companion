import os
import time
from typing import Optional, Dict, Any, List
from ..models import (
    DiscreteSolveRequest,
    DiscreteSolveResponse,
    DiscreteSolveMetrics,
    SelectedTrade,
    CandidateTrade
)

class HybridDiscreteSolver:
    """
    Orchestrates the selection between Quantum (Dirac) and Classical solvers
    based on availability, request parameters, and constraints.
    """

    def solve(self, req: DiscreteSolveRequest) -> DiscreteSolveResponse:
        mode = req.parameters.mode
        qci_token = os.environ.get("QCI_API_TOKEN")
        trial_mode = req.parameters.trial_mode
        candidate_count = len(req.candidates)
        max_candidates = req.parameters.max_candidates_for_dirac

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
            elif trial_mode is True:
                error_reason = "trial_mode_active"
            elif candidate_count > max_candidates:
                error_reason = f"too_many_candidates ({candidate_count} > {max_candidates})"

            if error_reason:
                return DiscreteSolveResponse(
                    status="error",
                    strategy_used="classical",
                    selected_trades=[],
                    metrics=self._empty_metrics(),
                    diagnostics={"error": f"Quantum solver unavailable ({error_reason})"}
                )
            # If available, attempt quantum
            return self._solve_quantum(req)

        # 3. Hybrid (Default)
        if mode == 'hybrid':
            fallback_reason = None

            if not has_token:
                fallback_reason = "missing_qci_token"
            elif trial_mode is True:
                fallback_reason = "trial_mode_active"
            elif candidate_count > max_candidates:
                fallback_reason = f"too_many_candidates ({candidate_count} > {max_candidates})"

            if fallback_reason:
                resp = self._solve_classical(req)
                resp.diagnostics['fallback_reason'] = fallback_reason
                return resp

            # Attempt quantum if no fallback reason
            return self._solve_quantum(req)

        # Should not reach here due to Pydantic validation of 'mode', but fallback to classical just in case
        return self._solve_classical(req)

    def _solve_classical(self, req: DiscreteSolveRequest) -> DiscreteSolveResponse:
        """
        Stub for classical solver. Returns empty selection with valid metrics.
        """
        start_time = time.perf_counter()

        # Simulate some processing time
        # In a real implementation, this would run a greedy or genetic algorithm

        runtime_ms = (time.perf_counter() - start_time) * 1000

        return DiscreteSolveResponse(
            status="success",
            strategy_used="classical",
            selected_trades=[],
            metrics=DiscreteSolveMetrics(
                expected_profit=0.0,
                total_premium=0.0,
                tail_risk_value=0.0,
                delta=0.0,
                gamma=0.0,
                vega=0.0,
                objective_value=0.0,
                runtime_ms=runtime_ms
            ),
            diagnostics={}
        )

    def _solve_quantum(self, req: DiscreteSolveRequest) -> DiscreteSolveResponse:
        """
        Stub for quantum solver (Dirac).
        """
        raise NotImplementedError("Dirac solver not implemented yet")

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
