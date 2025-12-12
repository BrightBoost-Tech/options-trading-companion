from typing import List, Dict, Any, Optional
import itertools
import random
from pydantic import BaseModel

from strategy_profiles import BacktestRequestV3, StrategyConfig
from services.backtest_engine import BacktestEngine, BacktestRunResult
from services.walkforward_runner import WalkForwardRunner, WalkForwardResult

class ParamSearchResult(BaseModel):
    # Each item tuple: (params, result_object)
    # result_object is either BacktestRunResult or WalkForwardResult
    results: List[Any]
    best_params: Dict[str, Any]

class ParamSearchRunner:
    def __init__(self, engine: BacktestEngine):
        self.engine = engine
        self.wf_runner = WalkForwardRunner(engine)

    def run_search(
        self,
        request: BacktestRequestV3,
        base_config: StrategyConfig
    ) -> ParamSearchResult:

        # 1. Generate Param Sets
        param_sets = []

        # Default to single run if no param_search config
        if not request.param_search:
             param_sets = [{}]
        else:
            if request.param_search.method == "grid":
                # Grid Search
                grid = request.param_search.space or request.param_grid
                if grid:
                    keys = list(grid.keys())
                    values = list(grid.values())
                    for p in itertools.product(*values):
                        param_sets.append(dict(zip(keys, p)))
                else:
                    param_sets = [{}]

            elif request.param_search.method == "random":
                # Random Search
                rng = random.Random(request.param_search.seed or 42)
                space = request.param_search.space
                n_samples = request.param_search.n_samples or 10

                if space:
                    for _ in range(n_samples):
                        sample = {}
                        for k, v in space.items():
                            if isinstance(v, list):
                                sample[k] = rng.choice(v)
                            else:
                                sample[k] = v
                        param_sets.append(sample)
                else:
                    param_sets = [{}]
            else:
                 param_sets = [{}]

        # 2. Run
        results = []
        best_metric = -float('inf')
        best_params = {}

        for params in param_sets:
            # Apply overrides
            config_copy = base_config.model_copy()
            for k, v in params.items():
                if hasattr(config_copy, k):
                    setattr(config_copy, k, v)

            run_output = None
            current_metric = -float('inf')

            if request.run_mode == "walk_forward":
                # Run Walk Forward
                wf_res = self.wf_runner.run_walk_forward(request, config_copy)
                run_output = wf_res
                current_metric = wf_res.aggregate_metrics.get("sharpe", 0)

            else:
                # Run Single
                run_res = self.engine.run_single(
                    request.ticker,
                    request.start_date,
                    request.end_date,
                    config_copy,
                    request.cost_model,
                    request.seed,
                    request.initial_equity
                )
                run_output = run_res
                current_metric = run_res.metrics.get("sharpe", 0)

            results.append({
                "params": params,
                "output": run_output
            })

            if current_metric > best_metric:
                best_metric = current_metric
                best_params = params

        return ParamSearchResult(
            results=results,
            best_params=best_params
        )
