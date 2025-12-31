from typing import List, Optional, Dict, Any, Literal
import time
import math
from packages.quantum.discrete.models import (
    DiscreteSolveRequest, DiscreteSolveResponse, SelectedTrade, DiscreteSolveMetrics, CandidateTrade
)

class HybridDiscreteSolver:
    @staticmethod
    def solve(request: DiscreteSolveRequest) -> DiscreteSolveResponse:
        start_time = time.time()

        # Determine strategy: 'classical' fallback unless 'quantum_only' is enforced (but we default to classical for now)
        # Real logic would use QCI adapter if enabled.
        # For this atomic change, we implement a simple greedy/classical solver or a mock.

        # Simple greedy selection based on EV/cost ratio, respecting constraints
        candidates = sorted(request.candidates, key=lambda c: c.ev_per_unit / (c.premium_per_unit if c.premium_per_unit > 0 else 0.001), reverse=True)

        selected_trades = []
        current_cash = 0.0
        current_vega = 0.0
        current_delta = 0.0
        current_gamma = 0.0
        total_ev = 0.0
        total_tail = 0.0

        for cand in candidates:
            # Try to add max quantity or as much as fits constraints
            # This is a very simplified solver for the "stub" purpose.

            qty = 0
            # Simple check: can we afford 1 unit?
            # Check cash
            cost = cand.premium_per_unit
            if current_cash + cost <= request.constraints.max_cash:
                qty = cand.qty_max # Assume we take all or nothing for this simple logic, or 1

                # Check constraints roughly
                if current_cash + (cost * qty) > request.constraints.max_cash:
                    qty = int((request.constraints.max_cash - current_cash) // cost) if cost > 0 else qty

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
            diagnostics={"mode": request.parameters.mode}
        )
