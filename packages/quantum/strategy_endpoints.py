from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import datetime
import uuid
import json
import itertools

from security import get_current_user_id
from strategy_profiles import StrategyConfig, BacktestRequest
from services.historical_simulation import HistoricalCycleService

router = APIRouter()

class BatchSimulationRequest(BacktestRequest):
    strategy_name: str

def get_supabase():
    from api import supabase
    if not supabase:
         # For testing/mocking, we might not have it.
         pass
    return supabase

def generate_param_combinations(param_grid: Optional[Dict[str, List[Any]]]) -> List[Dict[str, Any]]:
    if not param_grid:
        return [{}]
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    combinations = []
    for p in itertools.product(*values):
        combinations.append(dict(zip(keys, p)))
    return combinations

def _run_simulation_job(
    user_id: str,
    request: BacktestRequest,
    strategy_name: str,
    config: StrategyConfig,
    batch_id: Optional[str] = None,
    overrides: Optional[Dict[str, Any]] = None,
    job_index: int = 0
):
    """
    Internal synchronous function to run ONE simulation pass (one param combo).
    """
    supabase = get_supabase()
    if not supabase:
        print("Database not available for backtest logic")
        return {}

    # Apply Overrides
    effective_config = config.model_copy()
    if overrides:
        for k, v in overrides.items():
            if hasattr(effective_config, k):
                # Simple type conversion if needed, assuming correct types in grid
                setattr(effective_config, k, v)

    # Generate a param hash or string representation
    param_hash = json.dumps(overrides, sort_keys=True) if overrides else "default"

    service = HistoricalCycleService()

    # Loop over date range
    cursor = request.start_date
    try:
        end_date_dt = datetime.strptime(request.end_date, "%Y-%m-%d")
    except ValueError:
        print(f"Invalid date format for end_date: {request.end_date}")
        return {}

    trades = []
    max_loops = 1000
    loops = 0

    while loops < max_loops:
        loops += 1
        try:
            cursor_dt = datetime.strptime(cursor, "%Y-%m-%d")
        except:
             break

        if cursor_dt > end_date_dt:
            break

        # Run one cycle
        result = service.run_cycle(cursor, request.ticker, effective_config)

        status = result.get("status")
        if status in ["normal_exit", "forced_exit"]:
            trades.append(result)

        next_cursor = result.get("nextCursor")
        if not next_cursor or next_cursor == cursor:
            break

        cursor = next_cursor

    # Compute Metrics
    total_trades = len(trades)
    # wins = [t for t in trades if t.get("pnl", 0) > 0]
    # PnL logic depends on structure. run_cycle returns "pnl" key.

    total_pnl = 0.0
    wins = 0
    for t in trades:
        pnl = t.get("pnl", 0.0)
        total_pnl += pnl
        if pnl > 0:
            wins += 1

    win_rate = wins / total_trades if total_trades > 0 else 0.0

    metrics = {
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "total_trades": total_trades,
        "avg_pnl": total_pnl / total_trades if total_trades > 0 else 0.0,
        "params": overrides
    }

    # Insert Result Row
    row = {
        "user_id": user_id,
        "strategy_name": strategy_name,
        "version": config.version,
        "param_hash": param_hash,
        "start_date": request.start_date,
        "end_date": request.end_date,
        "ticker": request.ticker,
        "trades_count": total_trades,
        "win_rate": win_rate,
        "total_pnl": total_pnl,
        "metrics": metrics,
        "status": "completed",
        "batch_id": batch_id
    }

    supabase.table("strategy_backtests").insert(row).execute()
    return row

def _run_backtest_workflow(
    user_id: str,
    request: BacktestRequest,
    strategy_name: str,
    config: StrategyConfig,
    batch_id: Optional[str] = None
):
    """
    Orchestrates the backtest process, expanding param grid if needed.
    """
    combinations = generate_param_combinations(request.param_grid)

    results = []
    for i, params in enumerate(combinations):
        res = _run_simulation_job(
            user_id,
            request,
            strategy_name,
            config,
            batch_id,
            overrides=params,
            job_index=i
        )
        results.append(res)

    return results

# --- Endpoints ---
# Using standard 'def' to ensure they run in threadpool and don't block event loop

@router.post("/strategies")
def create_strategy_config(
    config: StrategyConfig,
    user_id: str = Depends(get_current_user_id)
):
    supabase = get_supabase()
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

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
def list_strategies(user_id: str = Depends(get_current_user_id)):
    supabase = get_supabase()
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    res = supabase.table("strategy_configs").select("*").eq("user_id", user_id).execute()
    return {"strategies": res.data}

@router.post("/strategies/{name}/backtest")
def run_backtest(
    name: str,
    request: BacktestRequest,
    user_id: str = Depends(get_current_user_id)
):
    supabase = get_supabase()
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    res = supabase.table("strategy_configs").select("*").eq("user_id", user_id).eq("name", name).order("version", desc=True).limit(1).execute()
    if not res.data:
         raise HTTPException(status_code=404, detail="Strategy config not found")

    config_data = res.data[0]
    config = StrategyConfig(**config_data["params"])

    results = _run_backtest_workflow(user_id, request, name, config)
    return {"status": "completed", "results_count": len(results), "results": results}

@router.post("/simulation/batch")
async def run_batch_simulation_endpoint(
    req: BatchSimulationRequest,
    background_tasks: BackgroundTasks,
    user_id: str = Depends(get_current_user_id)
):
    """
    Launches an async backtest. Returns a batch_id immediately.
    """
    supabase = get_supabase()
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    batch_id = str(uuid.uuid4())

    # Verify Strategy
    res = supabase.table("strategy_configs").select("*").eq("user_id", user_id).eq("name", req.strategy_name).order("version", desc=True).limit(1).execute()
    if not res.data:
         raise HTTPException(status_code=404, detail="Strategy config not found")
    config = StrategyConfig(**res.data[0]["params"])

    # Create Initial Pending Row (Parent)
    # We might use this row to track overall progress, or just as a placeholder.
    # The individual runs will insert their own rows with the same batch_id.
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

    # Launch Background Task
    background_tasks.add_task(_run_backtest_workflow, user_id, req, req.strategy_name, config, batch_id)

    return {"status": "queued", "batch_id": batch_id}

@router.get("/simulation/batch/{batch_id}")
def get_batch_status(
    batch_id: str,
    user_id: str = Depends(get_current_user_id)
):
    supabase = get_supabase()
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    res = supabase.table("strategy_backtests").select("*").eq("batch_id", batch_id).execute()
    return {"results": res.data}

@router.get("/strategies/{name}/backtests")
def list_strategy_backtests(
    name: str,
    limit: int = 20,
    offset: int = 0,
    user_id: str = Depends(get_current_user_id)
):
    supabase = get_supabase()
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    # Verify strategy existence/ownership
    # (Optional strict check, or just query backtests directly by user_id+strategy_name)

    res = (
        supabase.table("strategy_backtests")
        .select("id, strategy_name, version, param_hash, start_date, end_date, ticker, trades_count, win_rate, max_drawdown, avg_roi, total_pnl, metrics, status, created_at")
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
    user_id: str = Depends(get_current_user_id)
):
    supabase = get_supabase()
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not available")

    res = (
        supabase.table("strategy_backtests")
        .select("id, strategy_name, version, param_hash, start_date, end_date, ticker, trades_count, win_rate, total_pnl, status, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )

    return {"recent_backtests": res.data}
