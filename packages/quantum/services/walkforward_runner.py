from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import copy
import itertools
import numpy as np

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

    v5 fix: Added 1-day gap between train_end and test_start to prevent
    data leakage. Fold windows: Train [T0..T1], Test [T1+1+embargo .. T2]

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

        # v5 fix: Add 1-day gap to prevent train/test overlap (leakage)
        test_start = train_end + timedelta(days=1 + embargo_days)
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

def _compute_objective_score(metrics: Dict[str, Any], objective: str) -> float:
    """
    Compute score for a given objective metric.

    Args:
        metrics: Backtest metrics dict
        objective: One of "sharpe", "profit_factor", "calmar"

    Returns:
        Score value (higher is better)
    """
    if objective == "sharpe":
        return metrics.get("sharpe", -999.0)
    elif objective == "profit_factor":
        return metrics.get("profit_factor", 0.0)
    elif objective == "calmar":
        # Calmar = total_return / max_drawdown
        total_return = metrics.get("total_return", 0.0)
        max_dd = metrics.get("max_drawdown", 0.0)
        if max_dd > 0:
            return total_return / max_dd
        elif total_return > 0:
            return float("inf")  # Positive return with no drawdown
        else:
            return 0.0
    else:
        # Fallback to sharpe
        return metrics.get("sharpe", -999.0)


def _compute_wfa_stability(fold_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Compute walk-forward analysis stability metrics and worst-fold risk indicators.

    v6: Provides institutional-grade robustness diagnostics including:
    - Dispersion metrics (std, median vs mean)
    - Worst-fold identification
    - Bounded stability score (0-100) with categorical tier

    Args:
        fold_results: List of fold dicts with test_metrics

    Returns:
        Dict with stability metrics:
        - fold_count, sharpe_mean, sharpe_median, sharpe_std
        - max_drawdown_mean, max_drawdown_median, max_drawdown_worst
        - profit_factor_mean, profit_factor_median
        - pct_positive_folds
        - worst_fold_index_by_drawdown, worst_fold_index_by_sharpe
        - stability_score (0-100), stability_tier (A/B/C/D)
    """
    # Edge case: empty folds
    if not fold_results:
        return {
            "fold_count": 0,
            "sharpe_mean": 0.0,
            "sharpe_median": 0.0,
            "sharpe_std": 0.0,
            "max_drawdown_mean": 0.0,
            "max_drawdown_median": 0.0,
            "max_drawdown_worst": 0.0,
            "profit_factor_mean": 0.0,
            "profit_factor_median": 0.0,
            "pct_positive_folds": 0.0,
            "worst_fold_index_by_drawdown": None,
            "worst_fold_index_by_sharpe": None,
            "stability_score": 0.0,
            "stability_tier": "D"
        }

    # Extract metrics from folds (handle missing keys with defaults)
    sharpes = []
    drawdowns = []
    profit_factors = []
    positive_count = 0

    worst_dd_idx = 0
    worst_dd_val = 0.0
    worst_sharpe_idx = 0
    worst_sharpe_val = float("inf")

    for i, fold in enumerate(fold_results):
        test_metrics = fold.get("test_metrics", {})

        sharpe = test_metrics.get("sharpe", 0.0)
        dd = test_metrics.get("max_drawdown", 0.0)
        pf = test_metrics.get("profit_factor", 0.0)
        total_pnl = test_metrics.get("total_pnl", None)
        trades_count = fold.get("trades_count", 0)

        sharpes.append(sharpe)
        drawdowns.append(dd)
        profit_factors.append(pf)

        # Determine if positive fold
        if total_pnl is not None:
            if total_pnl > 0:
                positive_count += 1
        elif trades_count > 0 and sharpe > 0:
            # Fallback heuristic
            positive_count += 1

        # Track worst folds
        if dd > worst_dd_val:
            worst_dd_val = dd
            worst_dd_idx = i
        if sharpe < worst_sharpe_val:
            worst_sharpe_val = sharpe
            worst_sharpe_idx = i

    fold_count = len(fold_results)

    # Compute statistics safely (avoid NaN)
    sharpe_arr = np.array(sharpes)
    dd_arr = np.array(drawdowns)
    pf_arr = np.array(profit_factors)

    sharpe_mean = float(np.mean(sharpe_arr)) if len(sharpe_arr) > 0 else 0.0
    sharpe_median = float(np.median(sharpe_arr)) if len(sharpe_arr) > 0 else 0.0
    sharpe_std = float(np.std(sharpe_arr)) if len(sharpe_arr) > 1 else 0.0

    dd_mean = float(np.mean(dd_arr)) if len(dd_arr) > 0 else 0.0
    dd_median = float(np.median(dd_arr)) if len(dd_arr) > 0 else 0.0
    dd_worst = float(np.max(dd_arr)) if len(dd_arr) > 0 else 0.0

    pf_mean = float(np.mean(pf_arr)) if len(pf_arr) > 0 else 0.0
    pf_median = float(np.median(pf_arr)) if len(pf_arr) > 0 else 0.0

    pct_positive = positive_count / fold_count if fold_count > 0 else 0.0

    # Compute stability score (0-100)
    # Formula: rewards high median sharpe, low dispersion, low worst drawdown
    base = max(0.0, sharpe_median)
    dispersion_penalty = 1.0 / (1.0 + sharpe_std)  # in (0,1]
    dd_penalty = 1.0 - min(0.95, dd_worst)  # in [0.05,1]

    raw_score = 100.0 * base * dispersion_penalty * dd_penalty

    # Clamp to [0, 100]
    stability_score = max(0.0, min(100.0, raw_score))

    # Categorical tier
    if stability_score >= 70:
        stability_tier = "A"
    elif stability_score >= 45:
        stability_tier = "B"
    elif stability_score >= 25:
        stability_tier = "C"
    else:
        stability_tier = "D"

    return {
        "fold_count": fold_count,
        "sharpe_mean": round(sharpe_mean, 4),
        "sharpe_median": round(sharpe_median, 4),
        "sharpe_std": round(sharpe_std, 4),
        "max_drawdown_mean": round(dd_mean, 4),
        "max_drawdown_median": round(dd_median, 4),
        "max_drawdown_worst": round(dd_worst, 4),
        "profit_factor_mean": round(pf_mean, 4),
        "profit_factor_median": round(pf_median, 4),
        "pct_positive_folds": round(pct_positive, 4),
        "worst_fold_index_by_drawdown": worst_dd_idx,
        "worst_fold_index_by_sharpe": worst_sharpe_idx,
        "stability_score": round(stability_score, 2),
        "stability_tier": stability_tier
    }


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
            # 1. TRAIN: Optimize parameters
            # v4: Use train_start_engine (includes warmup) for engine execution
            best_score = -999.0
            best_params: Dict[str, Any] = {"conviction_floor": base_config.conviction_floor}
            best_train_metrics: Dict[str, Any] = {}

            # v4: Determine objective metric (default: sharpe)
            objective_metric = getattr(wf_config, "objective_metric", None) or "sharpe"
            min_trades = getattr(wf_config, "min_trades_per_fold", 5)
            max_combinations = getattr(wf_config, "max_tune_combinations", 50)

            # v4: Check if tune_grid is provided
            tune_grid = getattr(wf_config, "tune_grid", None)

            if tune_grid:
                # v4: Generate param combinations from tune_grid
                param_names = list(tune_grid.keys())
                param_values = [tune_grid[k] for k in param_names]
                all_combinations = list(itertools.product(*param_values))

                # Apply max_tune_combinations cap
                combinations = all_combinations[:max_combinations]

                for combo in combinations:
                    train_config = base_config.model_copy()
                    combo_params = dict(zip(param_names, combo))

                    # Apply params where hasattr
                    for k, v in combo_params.items():
                        if hasattr(train_config, k):
                            setattr(train_config, k, v)

                    res = self.engine.run_single(
                        request.ticker,
                        fold["train_start_engine"],
                        fold["train_end"],
                        train_config,
                        request.cost_model,
                        request.seed,
                        initial_equity=100000.0
                    )

                    # v4: Enforce min_trades_per_fold
                    if len(res.trades) < min_trades:
                        continue

                    # Score using objective_metric
                    score = _compute_objective_score(res.metrics or {}, objective_metric)
                    if score > best_score:
                        best_score = score
                        best_params = combo_params.copy()
                        best_train_metrics = copy.deepcopy(res.metrics) if res.metrics else {}

            else:
                # Fallback: Simple grid for conviction_floor only
                candidates = [0.5, 0.6, 0.7, 0.8, 0.9]

                for thresh in candidates:
                    train_config = base_config.model_copy()
                    train_config.conviction_floor = thresh

                    res = self.engine.run_single(
                        request.ticker,
                        fold["train_start_engine"],
                        fold["train_end"],
                        train_config,
                        request.cost_model,
                        request.seed,
                        initial_equity=100000.0
                    )

                    # v4: Enforce min_trades_per_fold
                    if len(res.trades) < min_trades:
                        continue

                    # Score using objective_metric
                    score = _compute_objective_score(res.metrics or {}, objective_metric)
                    if score > best_score:
                        best_score = score
                        best_params = {"conviction_floor": thresh}
                        best_train_metrics = copy.deepcopy(res.metrics) if res.metrics else {}

            # v5: Fallback when no tuning candidate passed min_trades_per_fold
            tuning_fallback = False
            if not best_train_metrics and best_score == -999.0:
                # Run ONE fallback with base_config (ignore min_trades for this run)
                fallback_res = self.engine.run_single(
                    request.ticker,
                    fold["train_start_engine"],
                    fold["train_end"],
                    base_config,
                    request.cost_model,
                    request.seed,
                    initial_equity=100000.0
                )
                tuning_fallback = True
                best_params = {"fallback": True}
                best_train_metrics = copy.deepcopy(fallback_res.metrics) if fallback_res.metrics else {}

            # 2. TEST: Run with best params
            test_config = base_config.model_copy()
            for k, v in best_params.items():
                if hasattr(test_config, k):
                    setattr(test_config, k, v)

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
            # v5: Ensure train_sharpe is never the sentinel -999.0
            train_sharpe = best_train_metrics.get("sharpe", 0.0)
            if train_sharpe == -999.0:
                train_sharpe = 0.0

            fold_results.append({
                "fold_index": i,
                "train_window": f"{fold['train_start']} to {fold['train_end']}",
                "test_window": f"{fold['test_start']} to {fold['test_end']}",
                "optimized_params": best_params,
                "train_sharpe": train_sharpe,  # backward compat, never sentinel
                "train_metrics": best_train_metrics,  # v4: full metrics dict
                "test_metrics": test_res.metrics if test_res.metrics else {},
                "trades_count": len(test_res.trades),
                "tuning_fallback": tuning_fallback  # v5: explicit flag for UI/debug
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

        # v6: Compute walk-forward stability metrics and worst-fold risk indicators
        stability = _compute_wfa_stability(fold_results)
        metrics.update(stability)

        return WalkForwardResult(
            folds=fold_results,
            aggregate_metrics=metrics,
            oos_trades=oos_trades,
            oos_events=oos_events
        )
