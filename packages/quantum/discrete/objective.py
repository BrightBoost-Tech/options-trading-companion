from typing import Dict, Any, List
from packages.quantum.discrete.models import DiscreteSolveRequest, CandidateTrade

def compute_components(req: DiscreteSolveRequest, q_by_id: Dict[str, int]) -> Dict[str, Any]:
    """
    Computes objective components for a given allocation vector.

    Args:
        req: The solve request containing candidates and parameters.
        q_by_id: Dictionary mapping candidate ID to integer quantity.
                 Missing candidates are treated as 0 quantity.

    Returns:
        Dictionary with keys:
            - expected_profit: float
            - total_premium: float
            - tail_risk_value: float (squared term)
            - delta: float
            - gamma: float
            - vega: float
            - quantity_total: int
    """
    expected_profit = 0.0
    total_premium = 0.0
    tail_risk_sum = 0.0
    delta = 0.0
    gamma = 0.0
    vega = 0.0
    quantity_total = 0

    # Pre-index candidates for O(1) lookup if needed, or iterate
    # Iterating q_by_id is better if sparse, but we need candidate data.
    # So map candidates by ID first.
    candidate_map = {c.id: c for c in req.candidates}

    for cid, qty in q_by_id.items():
        if qty == 0:
            continue

        candidate = candidate_map.get(cid)
        if not candidate:
            # Treat missing candidate as having no impact (zeros)
            continue

        expected_profit += qty * candidate.ev_per_unit
        total_premium += qty * candidate.premium_per_unit
        tail_risk_sum += qty * candidate.tail_risk_contribution
        delta += qty * candidate.delta
        gamma += qty * candidate.gamma
        vega += qty * candidate.vega
        quantity_total += qty

    tail_risk_value = tail_risk_sum ** 2

    return {
        "expected_profit": expected_profit,
        "total_premium": total_premium,
        "tail_risk_value": tail_risk_value,
        "delta": delta,
        "gamma": gamma,
        "vega": vega,
        "quantity_total": quantity_total
    }

def check_hard_constraints(req: DiscreteSolveRequest, components: Dict[str, Any]) -> Dict[str, Any]:
    """
    Checks if the components satisfy hard constraints.

    Args:
        req: The solve request.
        components: Output from compute_components.

    Returns:
        Dict with:
            - ok: bool
            - violations: Dict[str, float] (name -> actual value that violated)
    """
    violations = {}
    constraints = req.constraints

    # max_cash (total_premium <= max_cash)
    if constraints.max_cash is not None:
        if components["total_premium"] > constraints.max_cash:
            violations["max_cash"] = components["total_premium"]

    # max_vega
    if constraints.max_vega is not None:
        if abs(components["vega"]) > constraints.max_vega:
             violations["max_vega"] = components["vega"]

    # max_delta_abs
    if constraints.max_delta_abs is not None:
        if abs(components["delta"]) > constraints.max_delta_abs:
            violations["max_delta_abs"] = components["delta"]

    # max_gamma
    if constraints.max_gamma is not None:
        if abs(components["gamma"]) > constraints.max_gamma:
            violations["max_gamma"] = components["gamma"]

    # max_contracts
    if constraints.max_contracts is not None:
        if components["quantity_total"] > constraints.max_contracts:
            violations["max_contracts"] = components["quantity_total"]

    return {
        "ok": len(violations) == 0,
        "violations": violations
    }

def objective_value(req: DiscreteSolveRequest, components: Dict[str, Any]) -> float:
    """
    Calculates the scalar objective value (energy) to minimize.

    Formula:
        energy = -(expected_profit - total_premium)
                 + lambda_tail * tail_risk_value
                 + lambda_cash * max(0, total_premium - max_cash)^2
                 + lambda_vega * max(0, abs(vega) - max_vega)^2
                 + lambda_delta * max(0, abs(delta) - max_delta_abs)^2
                 + lambda_gamma * max(0, abs(gamma) - max_gamma)^2

    Args:
        req: The solve request containing parameters and constraints.
        components: Output from compute_components.

    Returns:
        float: The energy value.
    """
    params = req.parameters
    constraints = req.constraints

    # Base energy: Negative Net Profit (Profit - Cost)
    # Assumes ev_per_unit is gross expected value.
    # If ev_per_unit is already net, this formula might penalize premium twice.
    # But adhering to the requirement "-(expected_profit - total_premium)"
    net_profit = components["expected_profit"] - components["total_premium"]
    energy = -net_profit

    # Tail Risk Penalty
    if params.lambda_tail != 0:
        energy += params.lambda_tail * components["tail_risk_value"]

    # Cash Constraint Penalty (Soft)
    if params.lambda_cash != 0 and constraints.max_cash is not None:
        violation = max(0.0, components["total_premium"] - constraints.max_cash)
        if violation > 0:
            energy += params.lambda_cash * (violation ** 2)

    # Vega Constraint Penalty (Soft)
    if params.lambda_vega != 0 and constraints.max_vega is not None:
        violation = max(0.0, abs(components["vega"]) - constraints.max_vega)
        if violation > 0:
            energy += params.lambda_vega * (violation ** 2)

    # Delta Constraint Penalty (Soft)
    if params.lambda_delta != 0 and constraints.max_delta_abs is not None:
        violation = max(0.0, abs(components["delta"]) - constraints.max_delta_abs)
        if violation > 0:
            energy += params.lambda_delta * (violation ** 2)

    # Gamma Constraint Penalty (Soft)
    if params.lambda_gamma != 0 and constraints.max_gamma is not None:
        violation = max(0.0, abs(components["gamma"]) - constraints.max_gamma)
        if violation > 0:
            energy += params.lambda_gamma * (violation ** 2)

    return energy
