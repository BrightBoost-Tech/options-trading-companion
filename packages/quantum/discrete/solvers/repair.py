from typing import Dict, Any, List
from packages.quantum.discrete.models import DiscreteSolveRequest, CandidateTrade
from packages.quantum.discrete.objective import compute_components, check_hard_constraints

def greedy_repair(req: DiscreteSolveRequest,
                  current_qty_map: Dict[str, int]) -> Dict[str, int]:
    """
    Iteratively repairs a solution by reducing quantity of the 'least efficient'
    trades until hard constraints (primarily max_cash) are satisfied.

    Efficiency Metric: EV / Cost.
    (If Cost is 0 or negative, infinite efficiency, so those are kept last).

    Args:
        req: The solve request.
        current_qty_map: Map of candidate_id -> quantity.

    Returns:
        New map of candidate_id -> quantity (feasible).
    """
    # Create a working copy
    qty_map = current_qty_map.copy()

    # 1. Identify candidates involved
    # Create a lookup for candidates
    candidate_map = {c.id: c for c in req.candidates}

    while True:
        # Check constraints
        components = compute_components(req, qty_map)
        check = check_hard_constraints(req, components)

        if check["ok"]:
            return qty_map

        violations = check["violations"]

        # Determine what to cut.
        # We need to find active trades (qty > 0)
        active_ids = [cid for cid, q in qty_map.items() if q > 0]

        if not active_ids:
            # No trades left, but still violated?
            # (Should not happen for max_cash/contracts unless max is negative or 0 and we have 0 trades).
            # Return empty map.
            return {}

        # Heuristic: Sort active trades by EV / Cost (Efficiency).
        # We want to cut the one with LOWEST Efficiency.

        scored_candidates = []
        for cid in active_ids:
            cand = candidate_map[cid]
            cost = cand.premium_per_unit
            ev = cand.ev_per_unit

            # Efficiency logic
            if cost > 0:
                efficiency = ev / cost
            elif cost < 0:
                 # Negative cost (credit) -> usually good to keep, high efficiency
                 # Treat as very high positive number
                 efficiency = 1e9 * ev # scale by EV
            else:
                # Cost is 0
                efficiency = 1e9 * ev

            scored_candidates.append((cid, efficiency, cost, ev))

        # Sort by efficiency ascending (lowest first)
        scored_candidates.sort(key=lambda x: x[1])

        # Pick the worst one to reduce
        worst_cid = scored_candidates[0][0]

        # Reduce quantity by 1
        qty_map[worst_cid] -= 1
        if qty_map[worst_cid] <= 0:
            del qty_map[worst_cid]

    return qty_map
