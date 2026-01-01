import os
import time
from typing import List, Dict, Any, Optional
from packages.quantum.discrete.models import (
    DiscreteSolveRequest, DiscreteSolveResponse, SelectedTrade,
    DiscreteSolveMetrics, CandidateTrade
)
from packages.quantum.discrete.polynomial_builder import build_discrete_polynomial, DiscreteCandidate, DiscreteOptimizationRequest
from packages.quantum.discrete.objective import objective_value, compute_components, check_hard_constraints
from packages.quantum.discrete.solvers.repair import greedy_repair
from packages.quantum.core.qci_adapter import QciDiracAdapter
from packages.quantum.discrete.solvers.postprocess import postprocess_and_score, vector_to_qty_map

class QciDiracDiscreteSolver:
    _trial_call_count = 0

    def __init__(self):
        self.adapter = QciDiracAdapter()

    @classmethod
    def _reset_trial_budget_for_tests(cls):
        cls._trial_call_count = 0

    def solve(self, req: DiscreteSolveRequest) -> DiscreteSolveResponse:
        start_time = time.time()

        # --- Preflight Trial Budgeting ---
        is_trial_mode = req.parameters.trial_mode or os.getenv('QCI_TRIAL_MODE') == '1'

        # Defaults
        num_samples = 20
        timeout = 20
        max_dirac_calls = 2
        max_candidates = 40

        if req.parameters.max_dirac_calls:
            max_dirac_calls = req.parameters.max_dirac_calls

        # Local candidate list to avoid mutating req
        candidates_local = list(req.candidates)

        if is_trial_mode:
            # Check budget
            if self._trial_call_count >= max_dirac_calls:
                 return DiscreteSolveResponse(
                    status="ok",
                    strategy_used="dirac3",
                    selected_trades=[],
                    metrics=DiscreteSolveMetrics(
                        expected_profit=0, total_premium=0, tail_risk_value=0,
                        delta=0, gamma=0, vega=0, objective_value=0, runtime_ms=0
                    ),
                    diagnostics={
                        "reason": "dirac_trial_budget_exhausted",
                        "trial_mode": True,
                        "used": self._trial_call_count,
                        "limit": max_dirac_calls
                    }
                )

            # Caps
            num_samples = min(req.parameters.num_samples or 5, 5)
            timeout = 10 # 8-10s
            candidate_cap = 25

            # 1. Filter candidates if too many
            if len(candidates_local) > max_candidates:
                return DiscreteSolveResponse(
                    status="error",
                    strategy_used="dirac3",
                    selected_trades=[],
                    metrics=DiscreteSolveMetrics(
                        expected_profit=0, total_premium=0, tail_risk_value=0,
                        delta=0, gamma=0, vega=0, objective_value=0, runtime_ms=0
                    ),
                    diagnostics={"reason": f"Too many candidates for trial mode ({len(candidates_local)} > {max_candidates})"}
                )

            # If candidates exceed trial cap (25), pick top 25 by EV/Cost
            if len(candidates_local) > candidate_cap:
                # Greedy pre-filter
                sorted_cands = sorted(
                    candidates_local,
                    key=lambda c: c.ev_per_unit / (c.premium_per_unit if c.premium_per_unit > 0 else 1e-4),
                    reverse=True
                )
                candidates_local = sorted_cands[:candidate_cap]
        else:
            if req.parameters.num_samples:
                num_samples = req.parameters.num_samples

        if not candidates_local:
             return self._empty_response(req, "No candidates provided")

        # --- Build Polynomial ---
        # Map DiscreteSolveRequest candidates to DiscreteOptimizationRequest candidates
        # Specifically, map ev_per_unit -> ev, premium_per_unit -> premium, tail_risk_contribution -> tail_risk

        poly_candidates = []
        for c in candidates_local:
            poly_candidates.append(DiscreteCandidate(
                id=c.id,
                ev=c.ev_per_unit,
                premium=c.premium_per_unit,
                tail_risk=c.tail_risk_contribution
            ))

        poly_req = DiscreteOptimizationRequest(
            candidates=poly_candidates,
            lambda_tail=req.parameters.lambda_tail,
            lambda_cash=req.parameters.lambda_cash,
            max_cash=req.constraints.max_cash
        )

        polynomial, scale_info, index_map = build_discrete_polynomial(poly_req)

        if not polynomial:
            # Empty polynomial (e.g. no candidates or everything zeroed)
            return self._empty_response(req, "Empty polynomial generated")

        # --- Call Adapter ---
        # Update call count
        if is_trial_mode:
            QciDiracDiscreteSolver._trial_call_count += 1

        var_max = max(c.qty_max for c in candidates_local)

        job_params = {
            "job_type": "sample-hamiltonian-integer",
            "num_samples": num_samples,
            "var_min": 0,
            "var_max": var_max,
            "timeout": timeout,
            "relaxation_schedule": 3
        }

        try:
            results = self.adapter.solve_polynomial_custom(
                polynomial=polynomial,
                job_params=job_params
            )
        except Exception as e:
            # Re-raise to let hybrid handle it
            raise e

        # --- Post-processing ---
        samples = results.get("samples", [])

        best_solution = None
        best_obj_val = float('inf')
        best_metrics = None

        rev_index_map = {v: k for k, v in index_map.items()}
        local_candidate_map = {c.id: c for c in candidates_local}

        # Evaluate ALL samples
        for s_vec in samples:
            # Convert to qty_map
            qty_map = vector_to_qty_map(req, s_vec, rev_index_map, local_candidate_map)

            # Postprocess & Score
            qty_map_fixed, components, obj_val, check, diag = postprocess_and_score(req, qty_map)

            # Minimize objective value
            if obj_val < best_obj_val:
                best_obj_val = obj_val
                best_solution = qty_map_fixed
                best_metrics = components

        if best_solution is None:
             best_solution = {}
             best_metrics = compute_components(req, {})
             best_obj_val = objective_value(req, best_metrics)

        # Construct response
        selected_trades = []
        for cid, qty in best_solution.items():
            if qty > 0:
                selected_trades.append(SelectedTrade(id=cid, qty=qty, reason="qci_dirac_optimal"))

        runtime = (time.time() - start_time) * 1000

        metrics = DiscreteSolveMetrics(
            expected_profit=best_metrics["expected_profit"],
            total_premium=best_metrics["total_premium"],
            tail_risk_value=best_metrics["tail_risk_value"],
            delta=best_metrics["delta"],
            gamma=best_metrics["gamma"],
            vega=best_metrics["vega"],
            objective_value=best_obj_val,
            runtime_ms=runtime
        )

        return DiscreteSolveResponse(
            status="ok",
            strategy_used="dirac3",
            selected_trades=selected_trades,
            metrics=metrics,
            diagnostics={
                "scale_info": scale_info.model_dump() if scale_info else None,
                "samples_returned": len(samples),
                "trial_mode": is_trial_mode,
                "dirac_calls_used": self._trial_call_count if is_trial_mode else 0
            }
        )

    def _empty_response(self, req, reason):
        return DiscreteSolveResponse(
            status="ok",
            strategy_used="dirac3",
            selected_trades=[],
            metrics=DiscreteSolveMetrics(
                expected_profit=0, total_premium=0, tail_risk_value=0,
                delta=0, gamma=0, vega=0, objective_value=0, runtime_ms=0
            ),
            diagnostics={"reason": reason}
        )
