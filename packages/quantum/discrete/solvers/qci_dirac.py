import os
import time
from typing import List, Dict, Any, Optional
from packages.quantum.discrete.models import (
    DiscreteSolveRequest, DiscreteSolveResponse, SelectedTrade,
    DiscreteSolveMetrics, CandidateTrade
)
from packages.quantum.discrete.polynomial_builder import build_discrete_polynomial
from packages.quantum.discrete.objective import objective_value, compute_components, check_hard_constraints
from packages.quantum.discrete.solvers.repair import greedy_repair
from packages.quantum.core.qci_adapter import QciDiracAdapter

class QciDiracDiscreteSolver:
    def __init__(self):
        self.adapter = QciDiracAdapter()

    def solve(self, req: DiscreteSolveRequest) -> DiscreteSolveResponse:
        start_time = time.time()

        # --- Preflight Trial Budgeting ---
        is_trial_mode = req.parameters.trial_mode or os.getenv('QCI_TRIAL_MODE') == '1'

        # Defaults
        num_samples = 20
        timeout = 20
        max_dirac_calls = 2 # Default from intent
        max_candidates = 40 # Default from intent

        if is_trial_mode:
            # Caps
            num_samples = min(req.parameters.num_samples or 5, 5)
            timeout = 10 # 8-10s
            candidate_cap = 25

            # 1. Filter candidates if too many
            if len(req.candidates) > max_candidates:
                return DiscreteSolveResponse(
                    status="skipped",
                    strategy_used="dirac3",
                    selected_trades=[],
                    metrics=DiscreteSolveMetrics(
                        expected_profit=0, total_premium=0, tail_risk_value=0,
                        delta=0, gamma=0, vega=0, objective_value=0, runtime_ms=0
                    ),
                    diagnostics={"reason": f"Too many candidates for trial mode ({len(req.candidates)} > {max_candidates})"}
                )

            # If candidates exceed trial cap (25), pick top 25 by EV/Cost
            if len(req.candidates) > candidate_cap:
                # Greedy pre-filter
                sorted_cands = sorted(
                    req.candidates,
                    key=lambda c: c.ev_per_unit / (c.premium_per_unit if c.premium_per_unit > 0 else 1e-4),
                    reverse=True
                )
                req.candidates = sorted_cands[:candidate_cap]
        else:
            if req.parameters.num_samples:
                num_samples = req.parameters.num_samples

        # Check call limit (mock logic here, real implementation would track usage)
        # Assuming we are within limits for this single call.

        # --- Build Polynomial ---
        # Map DiscreteSolveRequest candidates to DiscreteOptimizationRequest candidates
        # Specifically, map ev_per_unit -> ev, premium_per_unit -> premium, tail_risk_contribution -> tail_risk
        from packages.quantum.discrete.polynomial_builder import DiscreteCandidate, DiscreteOptimizationRequest

        poly_candidates = []
        for c in req.candidates:
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
        # Determine variable bounds
        # Uniform bound: max(qty_max)
        if not req.candidates:
             return self._empty_response(req, "No candidates provided")

        var_max = max(c.qty_max for c in req.candidates)

        job_params = {
            "job_type": "sample-hamiltonian-integer",
            "num_samples": num_samples,
            "var_min": 0,
            "var_max": var_max,
            "timeout": timeout,
            "relaxation_schedule": 3 # Default as per intent
        }

        try:
            results = self.adapter.solve_polynomial_custom(
                polynomial=polynomial,
                job_params=job_params
            )
        except Exception as e:
            # Let the caller (Hybrid solver) handle the exception for fallback
            raise e

        # --- Post-processing ---
        samples = results.get("samples", [])
        energies = results.get("energies", [])

        if not samples:
             # Should be caught by adapter usually, but safe check
             raise Exception("No samples returned from QCI")

        # Combine samples with energies
        # If energies missing, treat as all equal (0)
        if not energies:
            energies = [0.0] * len(samples)

        sample_data = []
        for i, s_vec in enumerate(samples):
            energy = energies[i] if i < len(energies) else 0.0
            sample_data.append({"vector": s_vec, "energy": energy})

        # Sort by energy (ascending, lower is better usually for H?
        # API returns energies corresponding to H. We minimized H in builder.
        # So lowest energy is best.
        sample_data.sort(key=lambda x: x["energy"])

        # Take top 5
        top_samples = sample_data[:5]

        best_solution = None
        best_obj_val = float('inf')
        best_qty_map = {}

        # Reverse index map: index -> candidate_id
        rev_index_map = {v: k for k, v in index_map.items()}

        candidate_map = {c.id: c for c in req.candidates}

        for sample_entry in top_samples:
            raw_vec = sample_entry["vector"]

            # Thresholding & rounding
            qty_map = {}
            for idx, val in enumerate(raw_vec):
                if val < 0.1:
                    val = 0

                # Round to nearest int
                int_val = int(round(val))

                if int_val > 0:
                    cid = rev_index_map.get(idx)
                    if cid:
                        # Clamp to qty_max per candidate
                        c_obj = candidate_map.get(cid)
                        if c_obj:
                            int_val = min(int_val, c_obj.qty_max)

                        qty_map[cid] = int_val

            # Check feasibility
            components = compute_components(req, qty_map)
            check = check_hard_constraints(req, components)

            # If not feasible, Repair
            if not check["ok"]:
                qty_map = greedy_repair(req, qty_map)
                # Re-compute after repair
                components = compute_components(req, qty_map)

            # Calculate objective value (using our python objective function to be consistent)
            obj_val = objective_value(req, components)

            if obj_val < best_obj_val:
                best_obj_val = obj_val
                best_solution = qty_map
                best_metrics = components

        # If no solution found (e.g. all empty?) - best_solution defaults to last or empty
        if best_solution is None:
             best_solution = {}
             best_metrics = compute_components(req, {})

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
                "trial_mode": is_trial_mode
            }
        )

    def _empty_response(self, req, reason):
        return DiscreteSolveResponse(
            status="ok", # or skipped
            strategy_used="dirac3",
            selected_trades=[],
            metrics=DiscreteSolveMetrics(
                expected_profit=0, total_premium=0, tail_risk_value=0,
                delta=0, gamma=0, vega=0, objective_value=0, runtime_ms=0
            ),
            diagnostics={"reason": reason}
        )
