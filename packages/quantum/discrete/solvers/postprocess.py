from typing import Dict, Any, List, Tuple
from packages.quantum.discrete.models import DiscreteSolveRequest
from packages.quantum.discrete.objective import objective_value, compute_components, check_hard_constraints

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
                 efficiency = 1e9 * abs(ev) # scale by EV
            else:
                # Cost is 0
                efficiency = 1e9 * ev

            scored_candidates.append((cid, efficiency))

        # Sort by efficiency ascending (lowest first)
        scored_candidates.sort(key=lambda x: x[1])

        # Pick the worst one to reduce
        worst_cid = scored_candidates[0][0]

        # Reduce quantity by 1
        qty_map[worst_cid] -= 1
        if qty_map[worst_cid] <= 0:
            del qty_map[worst_cid]

    return qty_map

def vector_to_qty_map(
    req: DiscreteSolveRequest,
    vector: List[float],
    rev_index_map: Dict[int, str],
    candidate_map: Dict[str, Any]
) -> Dict[str, int]:
    """
    Converts a raw solution vector (from Dirac or classical solver) into a quantity map.
    Applies thresholding (val < 0.1 => 0), rounding, and max quantity clamping.

    Args:
        req: Original request (not modified, used for context if needed)
        vector: Raw solution vector [x0, x1, ...]
        rev_index_map: Mapping from vector index to candidate ID
        candidate_map: Mapping from candidate ID to Candidate object

    Returns:
        Dict[candidate_id, quantity]
    """
    qty_map = {}
    for idx, val in enumerate(vector):
        if val < 0.1:
            val = 0

        # Round to nearest integer
        int_val = int(round(val))

        if int_val > 0:
            cid = rev_index_map.get(idx)
            if cid and cid in candidate_map:
                c_obj = candidate_map[cid]
                # Clamp to qty_max
                qty_map[cid] = min(int_val, c_obj.qty_max)

    return qty_map

def postprocess_and_score(
    req: DiscreteSolveRequest,
    qty_map: Dict[str, int]
) -> Tuple[Dict[str, int], Dict[str, float], float, Dict[str, Any], Dict[str, Any]]:
    """
    Shared pipeline for BOTH quantum and classical solvers:
    1. Clamp max quantities (redundant but safe)
    2. Compute components
    3. Check constraints
    4. Repair if needed (greedy repair)
    5. Compute final objective value

    Returns:
        (qty_map_fixed, components, objective_val, check_result, diagnostics)
    """
    diagnostics = {"repaired": False}

    # 1. Enforce qty_max again to be sure (already done in vector_to_qty_map, but good for classical dict inputs)
    # Also ensure we don't have quantities for candidates not in req
    candidate_map = {c.id: c for c in req.candidates}

    # Filter and clamp
    cleaned_qty_map = {}
    for cid, qty in qty_map.items():
        if cid in candidate_map and qty > 0:
            c_obj = candidate_map[cid]
            cleaned_qty_map[cid] = min(qty, c_obj.qty_max)

    qty_map = cleaned_qty_map

    # 2. Compute components
    components = compute_components(req, qty_map)

    # 3. Check hard constraints
    check = check_hard_constraints(req, components)

    # 4. Repair if needed
    if not check["ok"]:
        qty_map = greedy_repair(req, qty_map)
        diagnostics["repaired"] = True
        diagnostics["original_violations"] = check.get("violations", [])

        # Re-compute after repair
        components = compute_components(req, qty_map)
        # Re-check constraints to ensure repair worked (or is at least reflected in check)
        check = check_hard_constraints(req, components)

    # 5. Compute objective value
    obj_val = objective_value(req, components)

    return qty_map, components, obj_val, check, diagnostics
