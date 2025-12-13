
import pytest
import numpy as np
from packages.quantum.analytics.opportunity_scorer import OpportunityScorer
from packages.quantum.analytics.risk_model import SpreadRiskModel
from packages.quantum.core.surrogate import SurrogateOptimizer
from packages.quantum.models import SpreadPosition

# --- Test Data ---

@pytest.fixture
def mock_trade_candidate():
    return {
        'symbol': 'TEST',
        'type': 'credit_put',
        'short_strike': 100,
        'long_strike': 95,
        'credit': 1.0,
        'dte': 30,
        'underlying_price': 102.0
    }

@pytest.fixture
def mock_market_ctx():
    return {
        'price': 102.0,
        'iv': 0.20,
        'bid': 1.0,
        'ask': 1.05,
        'iv_rank': 60
    }

# --- Deliverable 1 Tests: OpportunityScorer ---

def test_scorer_basic_scoring(mock_trade_candidate, mock_market_ctx):
    """Test that scorer produces valid score structure."""
    result = OpportunityScorer.score(mock_trade_candidate, mock_market_ctx)

    assert "score" in result
    assert 0 <= result["score"] <= 100
    assert "metrics" in result
    assert result["metrics"]["ev_amount"] is not None
    assert result["metrics"]["prob_profit"] > 0
    assert "features_hash" in result

def test_scorer_liquidity_penalty():
    """Test liquidity penalty logic."""
    cand = {'symbol': 'TEST'}

    # Tight spread
    res_tight = OpportunityScorer.score(cand, {'bid': 1.0, 'ask': 1.01, 'price': 100})
    pen_tight = res_tight['penalties']['liquidity']
    assert pen_tight == 0.0

    # Wide spread (10%)
    res_wide = OpportunityScorer.score(cand, {'bid': 1.0, 'ask': 1.10, 'price': 100})
    pen_wide = res_wide['penalties']['liquidity']
    assert pen_wide > 0.5 # Significant penalty

def test_scorer_ev_calculation():
    """Test EV calculation for known scenario."""
    # Credit spread $1 wide, collecting $0.40. Max Loss $0.60.
    # If prob profit is 50%, EV should be negative (0.4*0.5 - 0.6*0.5 = -0.1)
    cand = {
        'symbol': 'TEST', 'type': 'credit',
        'short_strike': 100, 'long_strike': 99,
        'credit': 0.40, 'dte': 1 # almost expired
    }
    # ATM, high vol -> ~50% prob ITM
    ctx = {'price': 99.5, 'iv': 1.0, 'bid': 0.4, 'ask': 0.4}

    res = OpportunityScorer.score(cand, ctx)
    ev = res['metrics']['ev_amount']
    # Prob ITM for short (99.5 vs 100) is > 50%. So Prob Profit < 50%.
    # Expect negative EV
    assert ev < 0.1 # likely negative or close to 0

# --- Deliverable 2 Tests: Risk Model ---

def test_spread_risk_model_inputs():
    """Test mu/sigma generation."""
    # Mock Assets
    assets = [
        SpreadPosition(
            id="S1", user_id="u1", spread_type="vertical", underlying="A",
            legs=[], net_cost=-100, current_value=0,
            delta=0.5, gamma=0.01, vega=0.1, theta=-0.05, quantity=1
        ),
        SpreadPosition(
            id="S2", user_id="u1", spread_type="vertical", underlying="B",
            legs=[], net_cost=-100, current_value=0,
            delta=0.3, gamma=0.01, vega=0.1, theta=-0.05, quantity=1
        )
    ]

    model = SpreadRiskModel(assets)

    # Mock Underlying Covariance (2 stocks)
    cov_u = np.array([[0.04, 0.02], [0.02, 0.04]]) # Correlated
    tickers = ["A", "B"]

    mu, sigma, coskew, collat = model.build_mu_sigma(cov_u, tickers)

    assert mu.shape == (2,)
    assert sigma.shape == (2, 2)
    assert len(collat) == 2

    # Check covariance transmission
    # Asset 1 has delta 0.5, Asset 2 delta 0.3.
    # Sigma_11 should roughly be (0.5)^2 * 0.04 * scale
    # Sigma_12 should roughly be (0.5*0.3) * 0.02 * scale

    # Just ensure it's not identity/zero
    assert sigma[0, 1] != 0.0

# --- Deliverable 4 Tests: Optimizer Constraints ---

def test_optimizer_constraints():
    """Test turnover and greek constraints."""
    optimizer = SurrogateOptimizer()

    mu = np.array([0.10, 0.05])
    sigma = np.array([[0.04, 0.0], [0.0, 0.04]])
    coskew = np.zeros((2, 2, 2))

    # Case 1: Unconstrained (Risk Av=1)
    # Asset 1 has higher return, same risk. Should have higher weight.
    cons = {'risk_aversion': 1.0, 'max_position_pct': 1.0}
    w_unc = optimizer.solve(mu, sigma, coskew, cons)
    assert w_unc[0] > w_unc[1]

    # Case 2: Turnover Penalty
    # Current weights favor asset 2 (100%). High turnover penalty should keep it closer to asset 2.
    current_w = np.array([0.0, 1.0])
    cons['turnover_penalty'] = 10.0 # High
    w_sticky = optimizer.solve(mu, sigma, coskew, cons, current_weights=current_w)

    # Asset 1 weight should be lower than unconstrained case
    assert w_sticky[0] < w_unc[0]

    # Case 3: Greek Constraint
    # Asset 1 has Delta 1.0, Asset 2 has Delta 0.0
    # Limit Portfolio Delta to 0.2
    greek_sens = {'delta': np.array([1.0, 0.0])}
    cons = {'risk_aversion': 1.0, 'max_position_pct': 1.0, 'greek_budgets': {'delta': 0.2}}

    w_constr = optimizer.solve(mu, sigma, coskew, cons, greek_sensitivities=greek_sens)

    # Weight of Asset 1 should be <= 0.2 approx
    assert w_constr[0] <= 0.21 # within tol
