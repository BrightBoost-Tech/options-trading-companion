from typing import List, Dict, Optional, Any, Tuple
from pydantic import BaseModel, Field
import math
import logging

class DiscreteCandidate(BaseModel):
    id: str
    ev: float = Field(..., description="Expected Value per unit")
    premium: float = Field(..., description="Cost per unit (premium)")
    tail_risk: float = Field(..., description="Tail risk contribution (T_i)")

class DiscreteOptimizationRequest(BaseModel):
    candidates: List[DiscreteCandidate]
    lambda_tail: float = Field(0.0, description="Penalty weight for tail risk")
    lambda_cash: float = Field(0.0, description="Penalty weight for cash usage (soft constraint)")
    max_cash: Optional[float] = Field(None, description="Max cash constraint (not strictly enforced in poly, used for soft penalty)")

class ScaleInfo(BaseModel):
    max_abs_before: float
    scale: float
    max_abs_after: float
    num_terms: int
    notes: Optional[str] = None

def build_discrete_polynomial(req: DiscreteOptimizationRequest) -> Tuple[List[Dict[str, Any]], ScaleInfo, Dict[str, int]]:
    """
    Constructs a polynomial compatible with polynomial_json solvers (e.g. QCI).

    Objective:
    Minimize H = -Utility + RiskPenalty + CashPenalty

    1. Utility (Linear): -1.0 * (EV - Premium) * q_i
    2. Tail Risk (Quadratic): lambda_tail * (Sum T_i * q_i)^2
       = lambda_tail * Sum_ij (T_i * T_j * q_i * q_j)
    3. Cash Penalty (Quadratic Soft): lambda_cash * (Sum P_i * q_i)^2
       = lambda_cash * Sum_ij (P_i * P_j * q_i * q_j)

    Normalization:
       Scales coefficients so max_abs <= 10.0.

    Returns:
       (polynomial_terms, scale_info, index_map)
    """
    candidates = req.candidates
    n = len(candidates)

    # map candidate id -> index
    index_map = {c.id: i for i, c in enumerate(candidates)}

    # Initialize coefficients
    # Linear: coef[i] maps to q_i
    # Quadratic: coef[(i, j)] maps to q_i * q_j (store with i <= j to handle symmetry)
    linear_coefs = {}  # index -> float
    quad_coefs = {}    # (i, j) -> float, where i <= j

    # 1. Linear Utility Terms
    # Minimize -(EV - Premium)
    for i, c in enumerate(candidates):
        utility = c.ev - c.premium
        linear_coefs[i] = -1.0 * utility

    # 2. Tail Risk (Quadratic)
    # lambda_tail * Sum_i Sum_j (T_i * T_j * q_i * q_j)

    # 3. Cash Penalty (Quadratic)
    # lambda_cash * Sum_i Sum_j (P_i * P_j * q_i * q_j)

    # Precompute terms to avoid repeated lookups
    T = [c.tail_risk for c in candidates]
    P = [c.premium for c in candidates]

    lambda_tail = req.lambda_tail
    lambda_cash = req.lambda_cash

    # Guardrail for O(n^2) explosion
    # If candidates > 60, only build diagonal + top-k off-diagonals
    prune_tail_expansion = n > 60
    top_k_off_diagonals = 1000

    if prune_tail_expansion:
        # Build diagonals first
        for i in range(n):
            term_val = lambda_tail * (T[i]**2) + lambda_cash * (P[i]**2)
            if term_val != 0:
                quad_coefs[(i, i)] = term_val

        # Identify top off-diagonals for tail risk (primary concern for density)
        # We assume tail risk dominates complexity. Cash penalty is also dense.
        # If we are pruning, we likely only care about significant interactions.
        # Let's compute magnitude of interaction |T_i*T_j| + |P_i*P_j|?
        # The prompt says "only build diagonal + top-k off-diagonals by |T_i*T_j|".
        # So we focus on Tail Risk for pruning criteria.

        potential_pairs = []
        for i in range(n):
            for j in range(i + 1, n):
                interaction = abs(T[i] * T[j])
                if interaction > 0:
                    potential_pairs.append((interaction, i, j))

        # Sort descending
        potential_pairs.sort(key=lambda x: x[0], reverse=True)

        # Take top k
        kept_pairs = potential_pairs[:top_k_off_diagonals]

        for _, i, j in kept_pairs:
            # Add tail term
            val = lambda_tail * T[i] * T[j]
            # Add cash term (if we are pruning, do we include cash interaction for these pairs?
            # The prompt is specific: "by |T_i*T_j|". I will include cash interaction for the same pairs
            # to be consistent, or just add it. If I add cash interaction for ALL pairs, I defeat the pruning.
            # So I will add cash interaction only for these pairs + maybe diagonals.
            # Pruning implies omitting the term entirely from the polynomial.
            val += lambda_cash * P[i] * P[j]

            # Since sum is symmetric (Sum_ij), we have term for (i,j) and (j,i).
            # Polynomial JSON usually expects terms summed up if they are distinct in the expression,
            # or coefficients combined.
            # The expansion is Sum_i Sum_j ...
            # For i != j, we have q_i q_j and q_j q_i. These are the same variable product.
            # So coefficient is 2 * (value).

            quad_coefs[(i, j)] = 2.0 * val

    else:
        # Full O(n^2) build
        for i in range(n):
            for j in range(i, n):
                # Tail
                val = lambda_tail * T[i] * T[j]
                # Cash
                val += lambda_cash * P[i] * P[j]

                if i != j:
                    # Double for symmetry in Sum_ij vs Sum_{i<=j}
                    val *= 2.0

                if val != 0:
                    quad_coefs[(i, j)] = val

    # Assemble terms list
    raw_terms = []

    # Linear
    for i, coef in linear_coefs.items():
        if coef != 0:
            raw_terms.append({"coef": coef, "terms": [{"index": i, "power": 1}]})

    # Quadratic
    for (i, j), coef in quad_coefs.items():
        if coef != 0:
            if i == j:
                # i=i term. Depending on solver, might prefer power=2 or reduction to linear.
                # Prompt: "Single candidate => quadratic tail still works (i=i term)"
                # implies keeping it quadratic structure.
                # However, usually x^2 = x for binary.
                # If we have both linear and quadratic terms for i, they will be separate entries in the list.
                # The prompt format allows this.
                raw_terms.append({"coef": coef, "terms": [{"index": i, "power": 2}]})
            else:
                raw_terms.append({"coef": coef, "terms": [{"index": i, "power": 1}, {"index": j, "power": 1}]})

    # Normalization
    if not raw_terms:
        return [], ScaleInfo(max_abs_before=0, scale=1.0, max_abs_after=0, num_terms=0, notes="Empty polynomial"), index_map

    max_abs = max(abs(t["coef"]) for t in raw_terms)

    scale = 1.0
    if max_abs > 10.0:
        scale = 10.0 / max_abs

    final_terms = []
    prune_threshold = 1e-4

    for t in raw_terms:
        new_coef = t["coef"] * scale
        if abs(new_coef) >= prune_threshold:
            # Create new dict to avoid mutating original if that mattered (here it's fresh)
            term_entry = {
                "coef": new_coef,
                "terms": t["terms"]
            }
            final_terms.append(term_entry)

    max_abs_after = 0.0
    if final_terms:
        max_abs_after = max(abs(t["coef"]) for t in final_terms)

    scale_notes = None
    if prune_tail_expansion:
        scale_notes = f"Pruned tail expansion: >60 candidates, kept top {top_k_off_diagonals} off-diagonal terms."

    scale_info = ScaleInfo(
        max_abs_before=max_abs,
        scale=scale,
        max_abs_after=max_abs_after,
        num_terms=len(final_terms),
        notes=scale_notes
    )

    return final_terms, scale_info, index_map
