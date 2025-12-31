from typing import List, Optional, Dict, Any, Literal
import time
import os
import math
import logging
from packages.quantum.discrete.models import (
    DiscreteSolveRequest, DiscreteSolveResponse, SelectedTrade, DiscreteSolveMetrics, CandidateTrade
)
from packages.quantum.discrete.solvers.classical import ClassicalSolver

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

        # 1. Determine Strategy
        mode = request.parameters.mode  # "classical_only", "quantum_only", "hybrid"
        token_available = QCI_AVAILABLE and bool(os.getenv("QCI_API_TOKEN"))

        use_quantum = False
        fallback_reason = None

        if mode == "classical_only":
            use_quantum = False
        elif mode == "quantum_only":
            if not token_available:
                return DiscreteSolveResponse(
                    status="error",
                    strategy_used="dirac3", # was 'none' but simpler to match type hints or use 'dirac3' as intent
                    selected_trades=[],
                    metrics=DiscreteSolveMetrics(
                        expected_profit=0, total_premium=0, tail_risk_value=0,
                        delta=0, gamma=0, vega=0, objective_value=0, runtime_ms=0
                    ),
                    diagnostics={"reason": "Quantum unavailable"}
                )
            use_quantum = True
        elif mode == "hybrid":
            use_quantum = token_available
        else:
            # Default or unknown mode -> Classical
            use_quantum = False

        # 2. Attempt Quantum Solver if selected
        if use_quantum:
            try:
                # We instantiate the class if available.
                # Note: If QCI_AVAILABLE is False, use_quantum would be False for Hybrid.
                # But for Quantum Only, we might have forced it True if token check logic was sloppy?
                # The logic above handles token_available. QCI_AVAILABLE is part of token_available.
                # So here QCI_AVAILABLE is True.

                # We need to import inside if needed? No, it's imported at top.
                if not QCI_AVAILABLE:
                     raise ImportError("QciDiracDiscreteSolver not available")

                solver = QciDiracDiscreteSolver()
                response = solver.solve(request)

                if response.status == "ok":
                    return response

                # If QCI failed/skipped (status="error")
                if mode == "quantum_only":
                    return response

                # Hybrid fallback
                fallback_reason = response.diagnostics.get("reason", f"Quantum status: {response.status}")

            except Exception as e:
                if mode == "quantum_only":
                    return DiscreteSolveResponse(
                        status="error",
                        strategy_used="dirac3",
                        selected_trades=[],
                        metrics=DiscreteSolveMetrics(0,0,0,0,0,0,0,0),
                        diagnostics={"reason": str(e)}
                    )
                fallback_reason = str(e)

        if not fallback_reason and mode == "hybrid" and not token_available:
             fallback_reason = "Quantum disabled or token missing"

        # 3. Classical Fallback
        solver = ClassicalSolver(request)
        response = solver.solve()

        # Inject fallback diagnostics if applicable
        if fallback_reason:
            if not response.diagnostics:
                response.diagnostics = {}
            response.diagnostics["fallback_reason"] = fallback_reason

        return response
