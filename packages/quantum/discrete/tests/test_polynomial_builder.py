import pytest
from packages.quantum.discrete.polynomial_builder import (
    build_discrete_polynomial,
    DiscreteOptimizationRequest,
    DiscreteCandidate
)

def test_empty_request():
    req = DiscreteOptimizationRequest(candidates=[])
    terms, info, idx_map = build_discrete_polynomial(req)
    assert terms == []
    assert info.scale == 1.0
    assert info.num_terms == 0
    assert idx_map == {}

def test_linear_utility_only():
    c1 = DiscreteCandidate(id="c1", ev=100.0, premium=10.0, tail_risk=0.0)
    req = DiscreteOptimizationRequest(candidates=[c1], lambda_tail=0.0, lambda_cash=0.0)

    terms, info, idx_map = build_discrete_polynomial(req)

    # Expected: -1 * (100 - 10) = -90
    # Scaled: |90| > 10 => scale = 10/90 = 1/9
    # Coef = -90 * 1/9 = -10

    assert len(terms) == 1
    term = terms[0]
    assert term["terms"] == [{"index": 0, "power": 1}]
    assert pytest.approx(term["coef"]) == -10.0
    assert pytest.approx(info.scale) == 10.0 / 90.0
    assert idx_map["c1"] == 0

def test_tail_risk_quadratic():
    # c1: T=5, c2: T=2
    # Lambda = 1.0
    # Term: (5q1 + 2q2)^2 = 25q1^2 + 4q2^2 + 20q1q2
    # Utility: 0 (ev=premium)
    c1 = DiscreteCandidate(id="c1", ev=10.0, premium=10.0, tail_risk=5.0)
    c2 = DiscreteCandidate(id="c2", ev=10.0, premium=10.0, tail_risk=2.0)

    req = DiscreteOptimizationRequest(candidates=[c1, c2], lambda_tail=1.0)

    terms, info, idx_map = build_discrete_polynomial(req)

    # Coefs before scale:
    # 25 for q1^2, 4 for q2^2, 20 for q1q2
    # Max abs = 25. Scale = 10/25 = 0.4

    # Expected scaled coefs:
    # q1^2: 25 * 0.4 = 10.0
    # q2^2: 4 * 0.4 = 1.6
    # q1q2: 20 * 0.4 = 8.0

    assert len(terms) == 3
    # Check scaling
    assert pytest.approx(info.scale) == 0.4

    # Verify terms exist
    term_map = {}
    for t in terms:
        indices = tuple(sorted(x["index"] for x in t["terms"]))
        powers = tuple(sorted(x["power"] for x in t["terms"]))
        term_map[(indices, powers)] = t["coef"]

    # q1^2 (index 0)
    assert pytest.approx(term_map[((0,), (2,))]) == 10.0
    # q2^2 (index 1)
    assert pytest.approx(term_map[((1,), (2,))]) == 1.6
    # q1q2 (index 0, 1)
    # Note: power for q1q2 is 1, 1
    assert pytest.approx(term_map[((0, 1), (1, 1))]) == 8.0

def test_pruning_small_coefficients():
    # c1 has tiny utility, small enough that after scaling it gets pruned?
    # Or set up a scenario where one term is huge, making scale small, and another term is small.

    # Huge term: T=100 => coef 10000. Scale = 10/10000 = 0.001
    # Tiny term: utility = 0.01. Coef = -0.01. Scaled = -0.00001 < 1e-4. Should be pruned.

    c1 = DiscreteCandidate(id="huge", ev=0, premium=0, tail_risk=100.0)
    c2 = DiscreteCandidate(id="tiny", ev=0.01, premium=0, tail_risk=0)

    req = DiscreteOptimizationRequest(candidates=[c1, c2], lambda_tail=1.0)
    terms, info, idx_map = build_discrete_polynomial(req)

    # Expect only huge tail term (q1^2), tiny linear term for c2 should be gone.
    # Note: c1 also has 0 linear utility.

    assert len(terms) == 1
    t = terms[0]
    # Check it corresponds to c1 (index 0)
    assert t["terms"][0]["index"] == 0
    assert t["terms"][0]["power"] == 2
    assert pytest.approx(t["coef"]) == 10.0

def test_large_candidate_set_pruning():
    # 65 candidates. All have T=1.
    # Full quadratic would be 65*65 terms.
    # Pruned should be diagonals (65) + top 1000 off-diagonals.
    # Since all T=1, all interactions are equal (value 1).
    # Sorting is stable or arbitrary, should pick 1000.

    candidates = [
        DiscreteCandidate(id=f"c{i}", ev=0, premium=0, tail_risk=1.0)
        for i in range(65)
    ]

    req = DiscreteOptimizationRequest(candidates=candidates, lambda_tail=1.0)
    terms, info, idx_map = build_discrete_polynomial(req)

    # Terms should include:
    # 65 diagonal terms (q_i^2)
    # 1000 off-diagonal terms
    # Total 1065

    assert len(terms) == 1065
    assert "Pruned tail expansion" in info.notes
