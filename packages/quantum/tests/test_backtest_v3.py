import pytest
from unittest.mock import MagicMock, patch
import uuid
from datetime import datetime
from strategy_profiles import BacktestRequestV3, CostModelConfig, WalkForwardConfig, ParamSearchConfig
from services.backtest_engine import BacktestEngine, BacktestRunResult
from services.walkforward_runner import generate_folds

def test_generate_folds_correctness():
    start = "2020-01-01"
    end = "2021-01-01"
    train = 180
    test = 60
    step = 60

    folds = generate_folds(start, end, train, test, step)

    assert len(folds) > 0
    # First fold
    assert folds[0]["train_start"] == "2020-01-01"

    # Second fold
    assert folds[1]["train_start"] > folds[0]["train_start"]

    # Ensure no train/test overlap leakage in same fold
    for f in folds:
        assert f["train_end"] <= f["test_start"]

@patch("services.backtest_engine.PolygonService")
def test_backtest_engine_single_run(mock_poly):
    mock_poly_instance = mock_poly.return_value
    mock_poly_instance.get_historical_prices.return_value = {
        "dates": ["2023-01-01", "2023-01-02", "2023-01-03"],
        "prices": [100.0, 102.0, 101.0]
    }

    engine = BacktestEngine(polygon_service=mock_poly_instance)
    engine.lookback_window = 0 # Disable lookback for test with small data

    # Mock Config
    config = MagicMock()
    config.conviction_floor = 0.5
    config.max_risk_pct_portfolio = 0.1
    config.stop_loss_pct = 0.05
    config.take_profit_pct = 0.1
    config.max_holding_days = 10
    config.regime_whitelist = []

    cost = CostModelConfig()

    with patch("services.backtest_engine.infer_global_context") as mock_infer:
        mock_infer.return_value.global_regime = "bull"
        with patch("services.backtest_engine.run_historical_scoring") as mock_score:
            mock_score.return_value = {"conviction": 0.8}

            res = engine.run_single(
                "SPY",
                "2023-01-01",
                "2023-01-03",
                config,
                cost,
                seed=42,
                initial_equity=100000
            )

            assert isinstance(res, BacktestRunResult)
            assert res.metrics["trades_count"] >= 0

@patch("strategy_endpoints.get_supabase")
def test_v3_backtest_endpoint(mock_get_supabase):
    from strategy_endpoints import run_backtest_v3

    mock_supabase = MagicMock()
    mock_get_supabase.return_value = mock_supabase

    # Mock strategy config fetch
    mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [{
        "params": {
            "name": "TestStrat", "version": 1, "conviction_floor": 0.5, "conviction_slope": 0,
            "max_risk_pct_per_trade": 0.05, "max_risk_pct_portfolio": 1.0, "max_concurrent_positions": 5,
            "max_spread_bps": 10, "max_days_to_expiry": 30, "min_underlying_liquidity": 1000000,
            "take_profit_pct": 0.1, "stop_loss_pct": 0.05, "max_holding_days": 10
        }
    }]

    # Mock insert
    mock_supabase.table.return_value.insert.return_value.execute.return_value.data = [{"id": str(uuid.uuid4())}]

    req = BacktestRequestV3(
        start_date="2023-01-01",
        end_date="2023-02-01",
        ticker="SPY",
        engine_version="v3",
        run_mode="single",
        cost_model=CostModelConfig(),
        seed=42,
        initial_equity=100000
    )

    with patch("strategy_endpoints.PolygonService") as mock_poly:
        mock_poly.return_value.get_historical_prices.return_value = {
            "dates": ["2023-01-01"], "prices": [100.0]
        }

        # We need to patch where it's used inside run_backtest_v3 -> ParamSearchRunner -> BacktestEngine
        # Since ParamSearchRunner creates new BacktestEngine(polygon_service=...)
        # And we passed mock_poly instance? No, endpoint instantiates `PolygonService()`.
        # So `strategy_endpoints.PolygonService` mock works for the instantiation call `poly_service = PolygonService()`.

        # But BacktestEngine imports `infer_global_context` etc. locally or at top level? Top level.
        # So we must patch `services.backtest_engine.infer_global_context`.

        with patch("services.backtest_engine.infer_global_context") as mock_infer:
            mock_infer.return_value.global_regime = "bull"

            with patch("services.backtest_engine.run_historical_scoring") as mock_score:
                mock_score.return_value = {"conviction": 0.8}

                # Mock BacktestEngine.lookback_window?
                # The endpoint creates a fresh engine. We can't easily access the instance to set lookback_window=0.
                # So we must patch BacktestEngine to set it, or patch `run_single`?
                # If we patch `run_single`, we skip the logic we want to test coverage for?
                # The test `test_backtest_engine_single_run` covers the engine logic.
                # Here we test endpoint integration.
                # So we can patch `BacktestEngine.run_single` to return a dummy result.

                with patch("services.param_search_runner.BacktestEngine.run_single") as mock_run:
                    mock_run.return_value = BacktestRunResult(
                        backtest_id="test", trades=[], events=[], equity_curve=[], metrics={"sharpe": 1.0}
                    )

                    res = run_backtest_v3("TestStrat", req, user_id="test_user")

                    assert res["status"] == "completed"
                    assert len(res["backtest_ids"]) > 0
