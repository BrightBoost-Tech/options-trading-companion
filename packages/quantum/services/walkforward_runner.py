from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import copy

# v4 dual-import shim: support both package and PYTHONPATH imports
try:
    from packages.quantum.strategy_profiles import BacktestRequestV3, StrategyConfig
except ImportError:
    from strategy_profiles import BacktestRequestV3, StrategyConfig

try:
    from packages.quantum.services.backtest_engine import BacktestEngine, BacktestRunResult
except ImportError:
    from services.backtest_engine import BacktestEngine, BacktestRunResult

try:
    from packages.quantum.services.backtest_metrics import calculate_backtest_metrics
except ImportError:
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
    Generates fold windows for walk-forward optimization.

    v4 upgrade: Now includes train_start_engine (train_start - warmup_days)
    for engine execution, while train_start/train_end remain the persisted
    boundaries for fold metrics.

    Returns:
        List of fold dicts with:
        - train_start, train_end: persisted training window boundaries
        - test_start, test_end: persisted test window boundaries
        - train_start_engine: engine execution start (includes warmup)
    """
    folds = []

    try:
        current_start = datetime.strptime(start_date, "%Y-%m-%d")
        final_end = datetime.strptime(end_date, "%Y-%m-%d")
        request_start = current_start  # Floor for warmup expansion
    except ValueError:
        return []

    while True:
        train_start = current_start
        train_end = train_start + timedelta(days=train_days)

        # Engine execution start: expand backward by warmup_days (clamped to request start)
        train_start_engine = train_start - timedelta(days=warmup_days)
        if train_start_engine < request_start:
            train_start_engine = request_start

        test_start = train_end + timedelta(days=embargo_days)
        test_end = test_start + timedelta(days=test_days)

        if test_end > final_end:
            break

        folds.append({
            "train_start": train_start.strftime("%Y-%m-%d"),
            "train_end": train_end.strftime("%Y-%m-%d"),
            "train_start_engine": train_start_engine.strftime("%Y-%m-%d"),
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
            # v4: Use train_start_engine (includes warmup) for engine execution
            best_sharpe = -999.0
            best_threshold = base_config.conviction_floor
            best_train_metrics: Dict[str, Any] = {}

            # Simple grid for entry threshold
            candidates = [0.5, 0.6, 0.7, 0.8, 0.9]

            for thresh in candidates:
                train_config = base_config.model_copy()
                train_config.conviction_floor = thresh

                res = self.engine.run_single(
                    request.ticker,
                    fold["train_start_engine"],  # v4: use engine start (with warmup)
                    fold["train_end"],
                    train_config,
                    request.cost_model,
                    request.seed,
                    initial_equity=100000.0
                )

                # v4: Track full metrics for best candidate
                candidate_sharpe = res.metrics.get("sharpe", -999.0)
                if candidate_sharpe > best_sharpe:
                    best_sharpe = candidate_sharpe
                    best_threshold = thresh
                    best_train_metrics = copy.deepcopy(res.metrics) if res.metrics else {}

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
                initial_equity=request.initial_equity  # Using request equity base for correct trade sizing if pct based
            )

            # v4: Store full train_metrics alongside train_sharpe for backward compat
            fold_results.append({
                "fold_index": i,
                "train_window": f"{fold['train_start']} to {fold['train_end']}",
                "test_window": f"{fold['test_start']} to {fold['test_end']}",
                "optimized_params": {"conviction_floor": best_threshold},
                "train_sharpe": best_sharpe,  # backward compat
                "train_metrics": best_train_metrics,  # v4: full metrics dict
                "test_metrics": test_res.metrics if test_res.metrics else {},
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

        # v4: Pass events for fill_rate calculation
        metrics = calculate_backtest_metrics(oos_trades, [], request.initial_equity, events=oos_events)

        # v4: Handle edge case of empty folds gracefully
        if fold_results:
            # Override Sharpe/DD with average of folds (common WF approximation)
            avg_sharpe = sum(f["test_metrics"].get("sharpe", 0.0) for f in fold_results) / len(fold_results)
            avg_dd = sum(f["test_metrics"].get("max_drawdown", 0.0) for f in fold_results) / len(fold_results)
            metrics["sharpe"] = avg_sharpe
            metrics["max_drawdown"] = avg_dd
        else:
            # Empty folds: safe defaults
            metrics["sharpe"] = 0.0
            metrics["max_drawdown"] = 0.0

        metrics["total_folds"] = len(fold_results)

        return WalkForwardResult(
            folds=fold_results,
            aggregate_metrics=metrics,
            oos_trades=oos_trades,
            oos_events=oos_events
        )
