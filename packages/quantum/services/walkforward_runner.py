from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import copy

from strategy_profiles import BacktestRequestV3, StrategyConfig
from services.backtest_engine import BacktestEngine, BacktestRunResult
from services.backtest_metrics import calculate_backtest_metrics

class WalkForwardResult(BaseModel):
    folds: List[Dict[str, Any]]
    aggregate_metrics: Dict[str, Any]
    oos_trades: List[Dict[str, Any]]
    oos_events: List[Dict[str, Any]]

def generate_folds(
    start_date: str,
    end_date: str,
    train_days: int,
    test_days: int,
    step_days: int,
    warmup_days: int = 0,
    embargo_days: int = 0
) -> List[Dict[str, str]]:
    """
    Generates (train_start, train_end, test_start, test_end) tuples.
    """
    folds = []

    try:
        current_start = datetime.strptime(start_date, "%Y-%m-%d")
        final_end = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        return []

    while True:
        train_start = current_start
        train_end = train_start + timedelta(days=train_days)

        test_start = train_end + timedelta(days=embargo_days)
        test_end = test_start + timedelta(days=test_days)

        if test_end > final_end:
            break

        folds.append({
            "train_start": train_start.strftime("%Y-%m-%d"),
            "train_end": train_end.strftime("%Y-%m-%d"),
            "test_start": test_start.strftime("%Y-%m-%d"),
            "test_end": test_end.strftime("%Y-%m-%d")
        })

        current_start += timedelta(days=step_days)

    return folds

class WalkForwardRunner:
    def __init__(self, engine: BacktestEngine):
        self.engine = engine

    def run_walk_forward(
        self,
        request: BacktestRequestV3,
        base_config: StrategyConfig
    ) -> WalkForwardResult:

        wf_config = request.walk_forward
        if not wf_config:
            raise ValueError("WalkForwardConfig is missing")

        folds = generate_folds(
            request.start_date,
            request.end_date,
            wf_config.train_days,
            wf_config.test_days,
            wf_config.step_days,
            wf_config.warmup_days,
            wf_config.embargo_days
        )

        fold_results = []
        # Equity tracking for aggregation is complex; simplified to just summing PnL for metrics
        # Ideally we'd stitch daily equity curves.

        oos_trades = []
        oos_events = []

        # Use initial equity for stats normalization on each fold or cumulatively?
        # Standard WF practice is to treat the OOS periods as a continuous simulation.
        # But for simpler implementation, we reset equity each fold for the engine,
        # and then aggregate the trades to compute global metrics.

        for i, fold in enumerate(folds):
            # 1. TRAIN: Optimize Threshold
            best_sharpe = -999.0
            best_threshold = base_config.conviction_floor

            # Simple grid for entry threshold
            candidates = [0.5, 0.6, 0.7, 0.8, 0.9]

            for thresh in candidates:
                train_config = base_config.model_copy()
                train_config.conviction_floor = thresh

                res = self.engine.run_single(
                    request.ticker,
                    fold["train_start"],
                    fold["train_end"],
                    train_config,
                    request.cost_model,
                    request.seed,
                    initial_equity=100000.0
                )

                if res.metrics["sharpe"] > best_sharpe:
                    best_sharpe = res.metrics["sharpe"]
                    best_threshold = thresh

            # 2. TEST: Run with best param
            test_config = base_config.model_copy()
            test_config.conviction_floor = best_threshold

            test_res = self.engine.run_single(
                request.ticker,
                fold["test_start"],
                fold["test_end"],
                test_config,
                request.cost_model,
                request.seed,
                initial_equity=request.initial_equity # Using request equity base for correct trade sizing if pct based
            )

            fold_results.append({
                "fold_index": i,
                "train_window": f"{fold['train_start']} to {fold['train_end']}",
                "test_window": f"{fold['test_start']} to {fold['test_end']}",
                "optimized_params": {"conviction_floor": best_threshold},
                "train_sharpe": best_sharpe,
                "test_metrics": test_res.metrics,
                "trades_count": len(test_res.trades)
            })

            # Collect trades and tag with fold index
            for t in test_res.trades:
                t_tagged = t.copy()
                t_tagged["fold_index"] = i
                oos_trades.append(t_tagged)

            for e in test_res.events:
                e_tagged = e.copy()
                e_tagged["fold_index"] = i
                oos_events.append(e_tagged)

        # Aggregate Metrics based on concatenated OOS trades
        # Use helper
        # We need to construct a synthetic equity curve from the trades to get Sharpe/DD
        # Or just sum PnL.
        # For Sharpe/DD, we need daily returns.
        # Approximation: Sum PnL daily?
        # Let's do trade-based metrics fully, and average fold equity metrics for the rest.

        metrics = calculate_backtest_metrics(oos_trades, [], request.initial_equity)

        # Override Sharpe/DD with average of folds or recalculate if we had stitching logic
        # For now, averaging fold metrics is a common WF approximation if stitching is hard
        avg_sharpe = sum(f["test_metrics"]["sharpe"] for f in fold_results) / len(fold_results) if fold_results else 0
        avg_dd = sum(f["test_metrics"]["max_drawdown"] for f in fold_results) / len(fold_results) if fold_results else 0

        metrics["sharpe"] = avg_sharpe
        metrics["max_drawdown"] = avg_dd
        metrics["total_folds"] = len(fold_results)

        return WalkForwardResult(
            folds=fold_results,
            aggregate_metrics=metrics,
            oos_trades=oos_trades,
            oos_events=oos_events
        )
