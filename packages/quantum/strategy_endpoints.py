# ... (previous imports and functions)
import json
import itertools
import numpy as np
from datetime import datetime
import uuid
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from supabase import Client

from packages.quantum.security import get_current_user_id, get_supabase_user_client
from packages.quantum.strategy_profiles import StrategyConfig, BacktestRequest, BacktestRequestV3
from packages.quantum.strategy_requests import BatchSimulationRequest, ResearchCompareRequest
from packages.quantum.services.historical_simulation import HistoricalCycleService
from packages.quantum.services.backtest_engine import BacktestEngine, BacktestRunResult
from packages.quantum.services.param_search_runner import ParamSearchRunner
from packages.quantum.services.walkforward_runner import WalkForwardResult
from packages.quantum.market_data import PolygonService
from packages.quantum.strategy_registry import STRATEGY_REGISTRY

# ... (omitting parts that didn't change for brevity, focusing on _persist_v3_results and imports)

router = APIRouter()

# ... (BatchSimulationRequest, ResearchCompareRequest, get_supabase, generate_param_combinations, _run_simulation_job, _run_backtest_workflow)

def _persist_v3_results(
    supabase,
    user_id: str,
    strategy_name: str,
    request: BacktestRequestV3,
    config: StrategyConfig,
    params: Dict[str, Any],
    output: Any # BacktestRunResult or WalkForwardResult
):
    param_hash = json.dumps(params, sort_keys=True)

    row = {
        "user_id": user_id,
        "strategy_name": strategy_name,
        "version": config.version,
        "param_hash": param_hash,
        "start_date": request.start_date,
        "end_date": request.end_date,
        "ticker": request.ticker,
        "engine_version": "v3",
        "run_mode": request.run_mode,
        "train_days": request.walk_forward.train_days if request.walk_forward else None,
        "test_days": request.walk_forward.test_days if request.walk_forward else None,
        "step_days": request.walk_forward.step_days if request.walk_forward else None,
        "seed": request.seed,
        "status": "completed"
    }

    metrics = {}
    trades = []
    events = []
    folds = []

    if isinstance(output, BacktestRunResult):
        metrics = output.metrics
        trades = output.trades
        events = output.events
        # row updates
        row.update({
            "trades_count": len(trades),
            "win_rate": metrics.get("win_rate"),
            "total_pnl": metrics.get("total_pnl"),
            "sharpe": metrics.get("sharpe"),
            "max_drawdown": metrics.get("max_drawdown"),
            "profit_factor": metrics.get("profit_factor"),
            "turnover": metrics.get("turnover"),
            "slippage_paid": metrics.get("slippage_paid"),
            "fill_rate": metrics.get("fill_rate"),
            "metrics": metrics
        })
    elif isinstance(output, WalkForwardResult):
        metrics = output.aggregate_metrics
        folds = output.folds
        trades = output.oos_trades
        events = output.oos_events
        # row updates
        row.update({
            "trades_count": metrics.get("trades_count", len(trades)),
            "win_rate": metrics.get("win_rate", 0.0),
            "total_pnl": metrics.get("total_pnl", 0.0),
            "sharpe": metrics.get("sharpe", 0.0),
            "max_drawdown": metrics.get("max_drawdown", 0.0),
            "profit_factor": metrics.get("profit_factor", 0.0),
            "turnover": metrics.get("turnover", 0.0),
            "slippage_paid": metrics.get("slippage_paid", 0.0),
            "fill_rate": metrics.get("fill_rate", 0.0),
            "metrics": metrics
        })

    # Insert Parent Row
    res = supabase.table("strategy_backtests").insert(row).execute()
    backtest_id = res.data[0]["id"]

    fold_id_map = {} # fold_index -> fold_uuid

    # Insert Folds (if any)
    if isinstance(output, WalkForwardResult) and folds:
        fold_rows = []
        for f in folds:
            f_row = {
                "backtest_id": backtest_id,
                "fold_index": f["fold_index"],
                "train_start": f["train_window"].split(" to ")[0],
                "train_end": f["train_window"].split(" to ")[1],
                "test_start": f["test_window"].split(" to ")[0],
                "test_end": f["test_window"].split(" to ")[1],
                "train_metrics": {"sharpe": f["train_sharpe"]}, # Simplified
                "test_metrics": f["test_metrics"],
                "optimized_params": f["optimized_params"]
            }
            fold_rows.append(f_row)

        # Insert and retrieve IDs to link trades
        res_folds = supabase.table("strategy_backtest_folds").insert(fold_rows).execute()
        for f_data in res_folds.data:
            fold_id_map[f_data["fold_index"]] = f_data["id"]

    # Insert Trades
    if trades:
        trade_rows = []
        # We need to map trades to their new UUIDs to link events
        # But we do batch insert.
        # Strategy: Insert trades, get IDs back. But order is not guaranteed?
        # Supabase/Postgres insert usually returns in order if rows provided in order.
        # Let's rely on that or handle events without strict FK if simpler.
        # Ideally, we insert trade, get ID, then insert events for that trade.
        # Batching might be tricky for linking.
        # For performance, we can just dump them. Events table has `trade_id` column.
        # But `trade_id` in `BacktestRunResult` is a temporary UUID string generated by engine.
        # We can store that in `strategy_backtest_trades` temporarily or as a reference if we added a column?
        # The migration has `id` UUID default gen.
        # And events link to `trade_id`.
        # If we use the engine's `trade_id` as the primary key?
        # The migration says `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`.
        # We can override it with the engine's UUID if we want to preserve linkage easily.

        # Let's assume we can pass `id` explicitly.

        for t in trades:
            t_id = t["trade_id"] # Engine generated UUID
            t_fold_idx = t.get("fold_index")
            fold_id = fold_id_map.get(t_fold_idx) if t_fold_idx is not None else None

            t_row = {
                "id": t_id, # Use pre-generated ID to allow event linking
                "backtest_id": backtest_id,
                "fold_id": fold_id,
                "symbol": t["symbol"],
                "direction": t["direction"],
                "entry_date": t["entry_date"],
                "exit_date": t["exit_date"],
                "entry_price": t["entry_price"],
                "exit_price": t["exit_price"],
                "quantity": t["quantity"],
                "pnl": t["pnl"],
                "pnl_pct": t["pnl_pct"],
                "commission_paid": t.get("commission_paid", 0),
                "slippage_paid": t.get("slippage_paid", 0),
                "exit_reason": t["exit_reason"]
            }
            trade_rows.append(t_row)

        if trade_rows:
            # Chunking to avoid payload limits
            chunk_size = 1000
            for i in range(0, len(trade_rows), chunk_size):
                supabase.table("strategy_backtest_trades").insert(trade_rows[i:i+chunk_size]).execute()

    # Insert Events
    if events:
        event_rows = []
        for e in events:
            # Events have trade_id from engine
            e_row = {
                "backtest_id": backtest_id,
                "trade_id": e.get("trade_id"), # Links to the ID we forced above
                "event_type": e["event_type"],
                "event_date": e["date"],
                "price": e["price"],
                "quantity": e["quantity"],
                "details": e["details"]
            }
            event_rows.append(e_row)

        if event_rows:
            chunk_size = 1000
            for i in range(0, len(event_rows), chunk_size):
                supabase.table("strategy_backtest_trade_events").insert(event_rows[i:i+chunk_size]).execute()

    return backtest_id

# ... (Endpoints from previous version)
@router.get("/strategies/metadata")
def get_strategy_metadata(user_id: str = Depends(get_current_user_id)):
    return {"registry": STRATEGY_REGISTRY}

@router.post("/strategies")
def create_strategy_config(
    config: StrategyConfig,
    user_id: str = Depends(get_current_user_id),
    supabase: Client = Depends(get_supabase_user_client)
):
    row = {
        "user_id": user_id,
        "name": config.name,
        "version": config.version,
        "description": config.description,
        "params": config.model_dump(),
        "updated_at": datetime.now().isoformat()
    }
    res = supabase.table("strategy_configs").upsert(row, on_conflict="user_id,name,version").execute()
    return {"status": "ok", "data": res.data}

@router.get("/strategies")
def list_strategies(
    user_id: str = Depends(get_current_user_id),
    supabase: Client = Depends(get_supabase_user_client)
):
    res = supabase.table("strategy_configs").select("*").eq("user_id", user_id).execute()
    return {"strategies": res.data}

@router.post("/strategies/{name}/backtest")
def run_backtest(
    name: str,
    request: BacktestRequest,
    user_id: str = Depends(get_current_user_id),
    supabase: Client = Depends(get_supabase_user_client)
):
    res = supabase.table("strategy_configs").select("*").eq("user_id", user_id).eq("name", name).order("version", desc=True).limit(1).execute()
    if not res.data:
         raise HTTPException(status_code=404, detail="Strategy config not found")
    config_data = res.data[0]
    config = StrategyConfig(**config_data["params"])
    results = _run_backtest_workflow(user_id, request, name, config)
    return {"status": "completed", "results_count": len(results), "results": results}

@router.post("/strategies/{name}/backtest/v3")
def run_backtest_v3(
    name: str,
    request: BacktestRequestV3,
    user_id: str = Depends(get_current_user_id),
    supabase: Client = Depends(get_supabase_user_client)
):
    """
    Executes V3 backtest (Single or Walk-Forward) with optional param sweep.
    """
    # 1. Fetch Config
    res = supabase.table("strategy_configs").select("*").eq("user_id", user_id).eq("name", name).order("version", desc=True).limit(1).execute()
    if not res.data:
         raise HTTPException(status_code=404, detail="Strategy config not found")
    base_config = StrategyConfig(**res.data[0]["params"])

    # 2. Initialize Engines
    poly_service = PolygonService()
    engine = BacktestEngine(polygon_service=poly_service)
    runner = ParamSearchRunner(engine)

    # 3. Run
    # This might be long running, should ideally be async background task.
    # For MVP we run synchronously as per request structure implying direct response or updated endpoint pattern.

    search_results = runner.run_search(request, base_config)

    # 4. Persist
    saved_ids = []
    for item in search_results.results:
        params = item["params"]
        output = item["output"]

        bid = _persist_v3_results(
            supabase,
            user_id,
            name,
            request,
            base_config,
            params,
            output
        )
        saved_ids.append(bid)

    return {
        "status": "completed",
        "best_params": search_results.best_params,
        "backtest_ids": saved_ids
    }

@router.post("/research/compare")
def compare_backtests(
    req: ResearchCompareRequest,
    user_id: str = Depends(get_current_user_id),
    supabase: Client = Depends(get_supabase_user_client)
):
    """
    Compares two Walk-Forward backtests using paired fold deltas and bootstrapping.
    """
    # Fetch folds
    folds_base = supabase.table("strategy_backtest_folds").select("*").eq("backtest_id", req.baseline_backtest_id).order("fold_index").execute()
    folds_cand = supabase.table("strategy_backtest_folds").select("*").eq("backtest_id", req.candidate_backtest_id).order("fold_index").execute()

    if not folds_base.data or not folds_cand.data:
        raise HTTPException(status_code=404, detail="Backtest data not found or incomplete")

    if len(folds_base.data) != len(folds_cand.data):
        raise HTTPException(status_code=400, detail="Backtests have different fold counts")

    # Align by index
    base_map = {f["fold_index"]: f for f in folds_base.data}
    cand_map = {f["fold_index"]: f for f in folds_cand.data}

    report = {
        "metrics": {},
        "folds_compared": len(base_map)
    }

    rng = np.random.RandomState(req.seed)

    for metric in req.metric_list:
        deltas = []

        for idx in base_map:
            if idx not in cand_map: continue

            # Extract metric from JSONB
            # Assuming test_metrics has the key
            val_base = base_map[idx]["test_metrics"].get(metric, 0.0)
            val_cand = cand_map[idx]["test_metrics"].get(metric, 0.0)

            deltas.append(val_cand - val_base)

        if not deltas:
            continue

        mean_delta = np.mean(deltas)

        # Bootstrap CI
        # Resample deltas with replacement
        bootstrap_means = []
        for _ in range(req.bootstrap_samples):
            sample = rng.choice(deltas, size=len(deltas), replace=True)
            bootstrap_means.append(np.mean(sample))

        ci_lower = np.percentile(bootstrap_means, 2.5)
        ci_upper = np.percentile(bootstrap_means, 97.5)
        p_val_proxy = np.mean(np.array(bootstrap_means) <= 0) if mean_delta > 0 else np.mean(np.array(bootstrap_means) >= 0)

        report["metrics"][metric] = {
            "mean_delta": float(mean_delta),
            "ci_95": [float(ci_lower), float(ci_upper)],
            "p_value_proxy": float(p_val_proxy),
            "significant": (ci_lower > 0) if mean_delta > 0 else (ci_upper < 0)
        }

    return report

@router.post("/simulation/batch")
async def run_batch_simulation_endpoint(
    req: BatchSimulationRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user_id),
    supabase: Client = Depends(get_supabase_user_client)
):
    batch_id = str(uuid.uuid4())

    res = supabase.table("strategy_configs").select("*").eq("user_id", user_id).eq("name", req.strategy_name).order("version", desc=True).limit(1).execute()
    if not res.data:
         raise HTTPException(status_code=404, detail="Strategy config not found")
    config = StrategyConfig(**res.data[0]["params"])

    row = {
        "user_id": user_id,
        "strategy_name": req.strategy_name,
        "version": config.version,
        "start_date": req.start_date,
        "end_date": req.end_date,
        "ticker": req.ticker,
        "status": "pending",
        "batch_id": batch_id,
        "param_hash": "batch_parent"
    }
    supabase.table("strategy_backtests").insert(row).execute()

    background_tasks.add_task(_run_backtest_workflow, user_id, req, req.strategy_name, config, batch_id)

    return {"status": "queued", "batch_id": batch_id}

@router.get("/simulation/batch/{batch_id}")
def get_batch_status(
    batch_id: str,
    user_id: str = Depends(get_current_user_id),
    supabase: Client = Depends(get_supabase_user_client)
):
    res = supabase.table("strategy_backtests").select("*").eq("batch_id", batch_id).execute()
    return {"results": res.data}

@router.get("/strategies/{name}/backtests")
def list_strategy_backtests(
    name: str,
    limit: int = 20,
    offset: int = 0,
    user_id: str = Depends(get_current_user_id),
    supabase: Client = Depends(get_supabase_user_client)
):
    res = (
        supabase.table("strategy_backtests")
        .select("id, strategy_name, version, param_hash, start_date, end_date, ticker, trades_count, win_rate, max_drawdown, total_pnl, metrics, status, created_at")
        .eq("user_id", user_id)
        .eq("strategy_name", name)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )

    return {"backtests": res.data}

@router.get("/strategy_backtests/recent")
def list_recent_backtests(
    limit: int = 10,
    user_id: str = Depends(get_current_user_id),
    supabase: Client = Depends(get_supabase_user_client)
):
    res = (
        supabase.table("strategy_backtests")
        .select("id, strategy_name, version, param_hash, start_date, end_date, ticker, trades_count, win_rate, total_pnl, status, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )

    return {"recent_backtests": res.data}
