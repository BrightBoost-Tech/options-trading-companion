from typing import List, Optional, Dict, Any, Literal
import time
import os
import math
import logging
from packages.quantum.discrete.models import (
    DiscreteSolveRequest, DiscreteSolveResponse, SelectedTrade, DiscreteSolveMetrics, CandidateTrade
)

# Late import to avoid circular deps if any, though solviers are usually leaf
try:
    from packages.quantum.discrete.solvers.qci_dirac import QciDiracDiscreteSolver
    QCI_AVAILABLE = True
except ImportError:
    QCI_AVAILABLE = False

class HybridDiscreteSolver:
    @staticmethod
    def solve(request: DiscreteSolveRequest) -> DiscreteSolveResponse:
        start_time = time.time()

        # 1. Attempt Quantum Solver if available and configured
        # Check env for token and if request allows it
        use_quantum = False
        fallback_reason = None

        # Check if we should try quantum
        if QCI_AVAILABLE and os.getenv("QCI_API_TOKEN"):
             # If strictly classical requested, skip
             if request.parameters.mode != "classical":
                 use_quantum = True

        if use_quantum:
            try:
                solver = QciDiracDiscreteSolver()
                response = solver.solve(request)

                # If solver skipped (e.g. due to trial limits), it returns status='skipped'.
                # In that case, we fall back.
                if response.status == "ok":
                    return response
                elif response.status == "skipped":
                    fallback_reason = response.diagnostics.get("reason", "Quantum solver skipped")
                else:
                    fallback_reason = f"Quantum solver returned status: {response.status}"

            except Exception as e:
                # Silent fallback
                fallback_reason = f"Quantum solver exception: {str(e)}"
                # Log error in real app
                pass
        else:
             fallback_reason = "Quantum disabled or token missing"

        # 2. Classical Fallback (Greedy)

        # Simple greedy selection based on EV/cost ratio, respecting constraints
        candidates = sorted(request.candidates, key=lambda c: c.ev_per_unit / (c.premium_per_unit if c.premium_per_unit > 0 else 0.001), reverse=True)

        selected_trades = []
        current_cash = 0.0
        current_vega = 0.0
        current_delta = 0.0
        current_gamma = 0.0
        total_ev = 0.0
        total_tail = 0.0

        # Using the constraint object
        max_cash = request.constraints.max_cash if request.constraints.max_cash is not None else float('inf')

        for cand in candidates:
            # Try to add max quantity or as much as fits constraints
            # This is a very simplified solver for the "stub" purpose.

            qty = 0
            # Simple check: can we afford 1 unit?
            # Check cash
            cost = cand.premium_per_unit

            # If cost is negative (credit), it adds to cash, so always affordable in terms of max_cash cap?
            # Usually max_cash limits DEBIT. If credit, we check if we violate other constraints?
            # Simplified: just check if debit doesn't exceed max_cash.

            if cost > 0:
                if current_cash + cost <= max_cash:
                    qty = cand.qty_max
                    # Refine qty
                    if current_cash + (cost * qty) > max_cash:
                         qty = int((max_cash - current_cash) // cost)
            else:
                # Credit trade, take max
                qty = cand.qty_max

            if qty > 0:
                selected_trades.append(SelectedTrade(id=cand.id, qty=qty, reason="greedy_selection"))
                current_cash += cost * qty
                current_vega += cand.vega * qty
                current_delta += cand.delta * qty
                current_gamma += cand.gamma * qty
                total_ev += cand.ev_per_unit * qty
                total_tail += cand.tail_risk_contribution * qty

        runtime = (time.time() - start_time) * 1000

        metrics = DiscreteSolveMetrics(
            expected_profit=total_ev,
            total_premium=current_cash,
            tail_risk_value=total_tail,
            delta=current_delta,
            gamma=current_gamma,
            vega=current_vega,
            objective_value=total_ev, # Simplified
            runtime_ms=runtime
        )

        return DiscreteSolveResponse(
            status="ok",
            strategy_used="classical",
            selected_trades=selected_trades,
            metrics=metrics,
            diagnostics={
                "mode": request.parameters.mode,
                "fallback_reason": fallback_reason
            }
        )
