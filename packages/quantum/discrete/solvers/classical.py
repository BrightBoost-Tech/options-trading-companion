import time
import random
from typing import List, Dict, Any, Tuple, Optional
from dataclasses import dataclass

from packages.quantum.discrete.models import (
    DiscreteSolveRequest,
    DiscreteSolveResponse,
    DiscreteSolveMetrics,
    SelectedTrade,
    CandidateTrade,
    DiscreteConstraints,
    DiscreteParameters
)
from packages.quantum.discrete.solvers.postprocess import postprocess_and_score

@dataclass
class Solution:
    # Map of candidate_id -> quantity
    quantities: Dict[str, int]
    # Cached metrics
    total_ev: float
    total_premium: float
    total_tail_risk: float
    total_vega: float
    total_gamma: float
    total_delta: float
    # Objective function value (Energy)
    energy: float

class ClassicalDiscreteSolver:
    def __init__(self):
        # Allow instantiation without request, solve method takes request
        pass

    def solve(self, req: DiscreteSolveRequest) -> DiscreteSolveResponse:
        solver_instance = _ClassicalSolverInstance(req)
        return solver_instance.solve()

class _ClassicalSolverInstance:
    def __init__(self, req: DiscreteSolveRequest, seed: int = 1337):
        self.req = req
        self.candidates = req.candidates
        self.constraints = req.constraints
        self.params = req.parameters
        self.rng = random.Random(seed)

        # Precompute lookups
        self.cand_map = {c.id: c for c in self.candidates}
        self.cand_ids = [c.id for c in self.candidates]

    def solve(self) -> DiscreteSolveResponse:
        start_time = time.perf_counter()

        # 1. Greedy Initialization
        current_sol = self._greedy_init()

        # 2. Local Search (Timeboxed)
        # Limit: 50ms
        time_limit = 0.050

        best_sol = current_sol

        iterations = 0
        swaps_attempted = 0
        swaps_accepted = 0

        start_search = time.perf_counter()

        while (time.perf_counter() - start_search) < time_limit:
            iterations += 1

            # Identify candidates for swap
            # Pick one with qty > 0 to decrease
            # Pick one with qty < max to increase

            # Get list of active and inactive/available
            active_ids = [cid for cid, qty in current_sol.quantities.items() if qty > 0]
            # Available to increase: any candidate where qty < qty_max
            available_ids = [c.id for c in self.candidates if current_sol.quantities.get(c.id, 0) < c.qty_max]

            if not active_ids or not available_ids:
                # Can't swap if nothing selected or everything maxed out (unlikely)
                break

            # Random selection
            remove_id = self.rng.choice(active_ids)
            add_id = self.rng.choice(available_ids)

            if remove_id == add_id:
                # No-op swap
                continue

            swaps_attempted += 1

            # Perform swap
            new_quantities = current_sol.quantities.copy()
            new_quantities[remove_id] -= 1
            if new_quantities[remove_id] == 0:
                del new_quantities[remove_id]

            new_quantities[add_id] = new_quantities.get(add_id, 0) + 1

            # Evaluate new solution
            new_sol = self._evaluate(new_quantities)

            # Check feasibility (hard constraints)
            if not self._is_feasible(new_sol):
                continue

            # Check objective (Energy)
            # Lower energy is better
            if new_sol.energy < current_sol.energy:
                current_sol = new_sol
                swaps_accepted += 1
                if current_sol.energy < best_sol.energy:
                    best_sol = current_sol

        # --- UNIFIED POST-PROCESSING ---
        # Instead of returning best_sol directly, we pass it through postprocess_and_score.
        # This ensures consistent scoring calculation (using shared objective function)
        # and a final repair pass (just in case local search drifted or initial greedy had issues,
        # though _is_feasible checks should prevent that. But strict fairness requires using the same final check).

        qty_map_fixed, components, obj_val, check, diagnostics = postprocess_and_score(self.req, best_sol.quantities)

        # Merge diagnostics
        diagnostics.update({
            "iterations": iterations,
            "swaps_attempted": swaps_attempted,
            "swaps_accepted": swaps_accepted,
            "initial_energy": current_sol.energy if iterations == 0 else "N/A",
        })

        end_time = time.perf_counter()
        runtime_ms = (end_time - start_time) * 1000.0

        # Format response
        selected_trades = []
        for cid, qty in qty_map_fixed.items():
            if qty > 0:
                selected_trades.append(SelectedTrade(
                    id=cid,
                    qty=qty,
                    reason="classical_solver"
                ))

        metrics = DiscreteSolveMetrics(
            expected_profit=components["expected_profit"],
            total_premium=components["total_premium"],
            tail_risk_value=components["tail_risk_value"],
            delta=components["delta"],
            gamma=components["gamma"],
            vega=components["vega"],
            objective_value=obj_val,
            runtime_ms=runtime_ms
        )

        return DiscreteSolveResponse(
            status="ok",
            strategy_used="classical",
            selected_trades=selected_trades,
            metrics=metrics,
            diagnostics=diagnostics
        )

    def _greedy_init(self) -> Solution:
        # Sort candidates by EV/Premium ratio (or similar metric)
        # Handle premium=0 edge case
        def score(c: CandidateTrade):
            denom = max(1e-6, c.premium_per_unit)
            # We want high EV per unit cost.
            return c.ev_per_unit / denom

        sorted_candidates = sorted(self.candidates, key=score, reverse=True)

        current_quantities = {}

        for cand in sorted_candidates:
            if cand.qty_max <= 0:
                continue

            # Try to add units 1 by 1 or binary search?
            # 1 by 1 is safer for "starting from 1".

            for q in range(1, cand.qty_max + 1):
                # Try setting qty = q
                current_quantities[cand.id] = q
                sol = self._evaluate(current_quantities)

                if self._is_feasible(sol):
                    pass # Keep adding
                else:
                    # Backtrack and stop
                    if q == 1:
                        del current_quantities[cand.id]
                    else:
                        current_quantities[cand.id] = q - 1
                    break

        return self._evaluate(current_quantities)

    def _evaluate(self, quantities: Dict[str, int]) -> Solution:
        total_ev = 0.0
        total_premium = 0.0
        total_tail = 0.0
        total_vega = 0.0
        total_gamma = 0.0
        total_delta = 0.0

        for cid, qty in quantities.items():
            if qty <= 0: continue
            cand = self.cand_map[cid]
            total_ev += cand.ev_per_unit * qty
            total_premium += cand.premium_per_unit * qty
            total_tail += cand.tail_risk_contribution * qty
            total_vega += cand.vega * qty
            total_gamma += cand.gamma * qty
            total_delta += cand.delta * qty

        # Compute Energy (Objective Function)
        # Matches polynomial_builder.py logic + extra terms from parameters
        # H = -Utility + RiskPenalty + CashPenalty
        # Utility = (EV - Premium)

        # Term 1: Utility (Linear)
        utility = total_ev - total_premium
        term_utility = -1.0 * utility

        # Term 2: Tail Risk (Quadratic)
        term_tail = self.params.lambda_tail * (total_tail ** 2)

        # Term 3: Cash Penalty (Soft constraint / Objective penalty)
        term_cash = self.params.lambda_cash * (total_premium ** 2)

        # Term 4: Vega (Quadratic)
        term_vega = self.params.lambda_vega * (total_vega ** 2)

        # Term 5: Gamma (Quadratic)
        term_gamma = self.params.lambda_gamma * (total_gamma ** 2)

        # Term 6: Delta (Quadratic around target)
        target = self.constraints.target_delta if self.constraints.target_delta is not None else 0.0
        term_delta = self.params.lambda_delta * ((total_delta - target) ** 2)

        energy = term_utility + term_tail + term_cash + term_vega + term_gamma + term_delta

        return Solution(
            quantities=quantities,
            total_ev=total_ev,
            total_premium=total_premium,
            total_tail_risk=total_tail,
            total_vega=total_vega,
            total_gamma=total_gamma,
            total_delta=total_delta,
            energy=energy
        )

    def _is_feasible(self, sol: Solution) -> bool:
        # Check hard constraints

        # Max Cash
        if sol.total_premium > self.constraints.max_cash:
            return False

        # Max Contracts
        if self.constraints.max_contracts is not None:
            total_qty = sum(sol.quantities.values())
            if total_qty > self.constraints.max_contracts:
                return False

        # Max Vega
        if self.constraints.max_vega is not None:
            if sol.total_vega > self.constraints.max_vega:
                return False

        # Max Delta Abs
        if abs(sol.total_delta) > self.constraints.max_delta_abs:
            return False

        # Max Gamma
        if sol.total_gamma > self.constraints.max_gamma:
            return False

        return True
