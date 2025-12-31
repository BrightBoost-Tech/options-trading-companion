from typing import List, Optional
import random
from dataclasses import dataclass
from packages.quantum.discrete.polynomial_builder import DiscreteCandidate, DiscreteOptimizationRequest

@dataclass
class Scenario:
    name: str
    request: DiscreteOptimizationRequest
    description: str

def generate_cash_tight_knapsack(seed: int, n_candidates: int, max_cash: float) -> Scenario:
    """
    Generates a scenario where many candidates have high EV but budget is tight.
    Selection requires prioritization.
    """
    rng = random.Random(seed)
    candidates = []

    for i in range(n_candidates):
        # Premium 10-100
        premium = rng.uniform(10.0, 100.0)
        # EV correlated with premium but with noise
        # Sharp ratio 0.5 to 2.0
        ev = premium * rng.uniform(0.5, 2.0)
        # Low tail risk for this scenario
        tail_risk = rng.uniform(0.0, 5.0)

        candidates.append(DiscreteCandidate(
            id=f"trade_{i}",
            ev=ev,
            premium=premium,
            tail_risk=tail_risk
        ))

    return Scenario(
        name="cash_tight_knapsack",
        request=DiscreteOptimizationRequest(
            candidates=candidates,
            lambda_tail=0.1,
            lambda_cash=10.0, # Strong penalty for over-budget
            max_cash=max_cash
        ),
        description=f"Knapsack: {n_candidates} items, Budget {max_cash:.1f}"
    )

def generate_greek_tight(seed: int, n_candidates: int, max_risk_unit: float) -> Scenario:
    """
    Generates a scenario where a risk metric (mapped to tail_risk) is the binding constraint.
    This simulates 'max_vega' or similar by using the tail_risk field which the polynomial supports.
    """
    rng = random.Random(seed)
    candidates = []

    for i in range(n_candidates):
        premium = rng.uniform(20.0, 50.0)
        ev = premium * rng.uniform(1.0, 1.5)
        # Risk unit (e.g., Vega) is significant
        risk = rng.uniform(5.0, 20.0)

        candidates.append(DiscreteCandidate(
            id=f"greek_{i}",
            ev=ev,
            premium=premium,
            tail_risk=risk # Using tail_risk slot for the binding constraint
        ))

    return Scenario(
        name="greek_tight",
        request=DiscreteOptimizationRequest(
            candidates=candidates,
            lambda_tail=10.0, # High penalty for risk squared
            lambda_cash=1.0,
            max_cash=n_candidates * 100.0 # Loose cash
        ),
        description=f"Greek Tight: {n_candidates} items, Risk constraint dominant"
    )

def generate_tail_coupled(seed: int, n_candidates: int) -> Scenario:
    """
    Generates a scenario with high tail contributions, encouraging diversification.
    Since polynomial expands (Sum T_i)^2, high T_i values cause quadratic penalty explosion
    if too many are selected.
    """
    rng = random.Random(seed)
    candidates = []

    for i in range(n_candidates):
        premium = rng.uniform(10.0, 30.0)
        # High EV to tempt selection
        ev = premium * rng.uniform(2.0, 3.0)
        # High tail risk
        tail_risk = rng.uniform(10.0, 50.0)

        candidates.append(DiscreteCandidate(
            id=f"tail_{i}",
            ev=ev,
            premium=premium,
            tail_risk=tail_risk
        ))

    return Scenario(
        name="tail_coupled",
        request=DiscreteOptimizationRequest(
            candidates=candidates,
            lambda_tail=5.0,
            lambda_cash=1.0,
            max_cash=n_candidates * 50.0 # Loose cash
        ),
        description=f"Tail Coupled: {n_candidates} items, Quadratic penalty dominant"
    )
