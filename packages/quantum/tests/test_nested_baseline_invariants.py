import pytest
import os
import json
import numpy as np
from unittest.mock import patch, MagicMock
from packages.quantum.optimizer import optimize_portfolio, OptimizationRequest, PositionInput

# Mock Dependencies
@pytest.fixture
def mock_market_data():
    with patch("packages.quantum.optimizer.calculate_portfolio_inputs") as mock_calc:
        # Mock 3 assets
        mock_calc.return_value = {
            "expected_returns": [0.001, 0.002, 0.0015],
            "covariance_matrix": [
                [0.0001, 0.0, 0.0],
                [0.0, 0.0002, 0.0],
                [0.0, 0.0, 0.00015]
            ]
        }
        yield mock_calc

@pytest.fixture
def mock_polygon_service():
    with patch("packages.quantum.optimizer.PolygonService") as mock_poly:
        mock_instance = MagicMock()
        mock_instance.get_recent_quote.return_value = {"bid": 100, "ask": 102}
        mock_instance.get_historical_prices.return_value = {"prices": [100, 101, 102]}
        mock_instance.get_iv_rank.return_value = 50.0
        mock_instance.get_trend.return_value = "neutral"
        mock_instance.get_ticker_details.return_value = {"sic_description": "Tech"}
        mock_poly.return_value = mock_instance
        yield mock_instance

@pytest.fixture
def mock_nested_components():
    with patch("packages.quantum.optimizer.compute_macro_features") as mock_macro, \
         patch("packages.quantum.optimizer.infer_global_context") as mock_infer, \
         patch("packages.quantum.optimizer.load_symbol_adapters") as mock_adapters, \
         patch("packages.quantum.optimizer.refresh_session_from_db") as mock_session, \
         patch("packages.quantum.optimizer.get_session_sigma_scale") as mock_scale, \
         patch("packages.quantum.optimizer.log_inference") as mock_log, \
         patch("packages.quantum.optimizer.log_global_context") as mock_log_ctx, \
         patch("packages.quantum.optimizer.StrategySelector") as mock_ss, \
         patch("packages.quantum.optimizer.OptionsAnalytics") as mock_oa, \
         patch("packages.quantum.optimizer.SmallAccountCompounder") as mock_sac, \
         patch("packages.quantum.optimizer.enrich_trade_suggestions") as mock_enrich:

        # Defaults
        mock_macro.return_value = {}

        mock_ctx = MagicMock()
        mock_ctx.global_regime = "bull"
        mock_ctx.global_risk_scaler = 1.0
        mock_infer.return_value = mock_ctx

        mock_adapters.return_value = {} # Identity

        mock_sess = MagicMock()
        mock_sess.confidence = 1.0
        mock_session.return_value = mock_sess

        mock_scale.return_value = 1.0

        mock_enrich.side_effect = lambda trades, *args: trades

        yield {
            "macro": mock_macro,
            "infer": mock_infer,
            "adapters": mock_adapters,
            "session": mock_session,
            "scale": mock_scale
        }

@pytest.mark.asyncio
async def test_flags_off_outputs_unchanged(mock_market_data, mock_polygon_service, mock_nested_components):
    # Setup Request
    req = OptimizationRequest(
        positions=[
            PositionInput(symbol="AAPL", current_value=1000, current_quantity=10, current_price=100),
            PositionInput(symbol="MSFT", current_value=1000, current_quantity=10, current_price=100),
            PositionInput(symbol="GOOG", current_value=1000, current_quantity=10, current_price=100)
        ],
        cash_balance=10000,
        profile="balanced",
        nested_enabled=False,
        nested_shadow=False
    )

    # 1. Run with flags OFF
    with patch.dict(os.environ, {"NESTED_GLOBAL_ENABLED": "False", "NESTED_L2_ENABLED": "False"}):
        res1 = await optimize_portfolio(req, user_id="test_user")

    # 2. Run with flags ON but nested_enabled=False
    with patch.dict(os.environ, {"NESTED_GLOBAL_ENABLED": "True", "NESTED_L2_ENABLED": "True"}):
        res2 = await optimize_portfolio(req, user_id="test_user")

    w1 = res1["target_weights"]
    w2 = res2["target_weights"]

    assert w1 == w2
    assert res1["trades"] == res2["trades"]

@pytest.mark.asyncio
async def test_shadow_mode_is_non_invasive(mock_market_data, mock_polygon_service, mock_nested_components):
    # Make nested logic produce DIFFERENT result
    # Mock L2 risk scaler to be very low (high risk)
    mock_nested_components["infer"].return_value.global_risk_scaler = 0.5

    req = OptimizationRequest(
        positions=[
            PositionInput(symbol="AAPL", current_value=1000, current_quantity=10, current_price=100),
            PositionInput(symbol="MSFT", current_value=1000, current_quantity=10, current_price=100),
            PositionInput(symbol="GOOG", current_value=1000, current_quantity=10, current_price=100)
        ],
        cash_balance=10000,
        profile="balanced",
        nested_enabled=False,
        nested_shadow=True # Enable Shadow
    )

    with patch.dict(os.environ, {"NESTED_GLOBAL_ENABLED": "True", "NESTED_L2_ENABLED": "True"}):
        res = await optimize_portfolio(req, user_id="test_user")

    # Check that main response is Baseline
    diag = res["diagnostics"]["nested_shadow"]
    metrics_base = diag["baseline_metrics"]
    metrics_nest = diag["nested_metrics"]

    # Assert differences exist
    assert metrics_base["sharpe_ratio"] != metrics_nest["sharpe_ratio"]

    # Assert Main Response Weights match Baseline Weights
    req_off = req.model_copy()
    req_off.nested_shadow = False
    req_off.nested_enabled = False

    res_off = await optimize_portfolio(req_off, user_id="test_user")

    assert res["target_weights"] == res_off["target_weights"]

@pytest.mark.asyncio
async def test_identity_adapter_unchanged(mock_market_data, mock_polygon_service, mock_nested_components):
    # Enable Nested Live
    req = OptimizationRequest(
        positions=[
            PositionInput(symbol="AAPL", current_value=1000, current_quantity=10, current_price=100)
        ],
        cash_balance=10000,
        profile="balanced",
        nested_enabled=True, # Live!
        nested_shadow=False
    )

    # Adapters are identity by default in mock
    with patch.dict(os.environ, {"NESTED_GLOBAL_ENABLED": "True", "NESTED_L1_ENABLED": "True"}):
        res_nested = await optimize_portfolio(req, user_id="test_user")

    # Run Baseline
    req_base = req.model_copy()
    req_base.nested_enabled = False
    res_base = await optimize_portfolio(req_base, user_id="test_user")

    assert res_nested["target_weights"] == res_base["target_weights"]

@pytest.mark.asyncio
async def test_nested_trade_count_aggressive(mock_market_data, mock_polygon_service, mock_nested_components):
    req = OptimizationRequest(
        positions=[
            PositionInput(symbol="A", current_value=1000, current_quantity=10, current_price=100),
            PositionInput(symbol="B", current_value=1000, current_quantity=10, current_price=100),
            PositionInput(symbol="C", current_value=1000, current_quantity=10, current_price=100),
            PositionInput(symbol="D", current_value=1000, current_quantity=10, current_price=100)
        ],
        cash_balance=10000,
        profile="aggressive",
        nested_enabled=False,
        nested_shadow=False
    )

    mock_market_data.return_value = {
        "expected_returns": [0.01, 0.02, 0.03, 0.04],
        "covariance_matrix": np.identity(4) * 0.0001
    }

    res = await optimize_portfolio(req, user_id="test_user")
    trades = res["trades"]

    assert len(trades) > 0
