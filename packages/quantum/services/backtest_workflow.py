from typing import List, Dict, Any, Optional
import json
import random
import numpy as np
from datetime import datetime
from .historical_simulation import HistoricalCycleService
from packages.quantum.nested_logging import _get_supabase_client
from packages.quantum.jobs.db import _to_jsonable

def _run_backtest_workflow(user_id: str, request, name: str, config, batch_id: Optional[str] = None, seed: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Restored backtest workflow that iterates through historical cycles.
    Intended for V2/Legacy backtest requests.
    """
    # Initialize service with default dependencies (PolygonService etc.)
    service = HistoricalCycleService()
    results = []

    cursor = request.start_date
    end_date_str = request.end_date
    symbol = request.ticker

    # Deterministic RNG for cycle seeds
    # If seed is None, we use system entropy (nondeterministic)
    rng = random.Random(seed)

    # Safety check for infinite loops
    max_cycles = 1000
    cycles = 0

    # Basic date validation for loop condition
    try:
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
    except ValueError:
        return [{"error": "Invalid end_date format"}]

    while cycles < max_cycles:
        # Check if cursor is past end date
        try:
            curr_date = datetime.strptime(cursor, "%Y-%m-%d")
            if curr_date > end_date:
                break
        except ValueError:
            break

        # Generate deterministic seed for this cycle
        # We use randint to generate a seed for the cycle's local RNG
        cycle_seed = rng.randint(0, 1000000)

        # Run one cycle
        result = service.run_cycle(
            cursor_date_str=cursor,
            symbol=symbol,
            user_id=user_id,
            config=config,
            mode="deterministic",
            seed=cycle_seed
        )

        # Add to results if it was a trade or relevant event
        if result.get("status") in ["normal_exit", "forced_exit"]:
            results.append(result)

        # Advance cursor
        next_cursor = result.get("nextCursor")

        # Stop if no more data or data ended
        if not next_cursor:
            break

        cursor = next_cursor
        cycles += 1

    # Handle Batch Persistence if needed
    if batch_id:
        try:
            supabase = _get_supabase_client()
            if supabase:
                # Calculate metrics
                trades_count = len(results)

                wins = [r for r in results if r.get("pnl", 0) > 0]
                total_pnl = sum([r.get("pnl", 0) for r in results])
                win_rate = len(wins) / trades_count if trades_count > 0 else 0.0

                # Serialize results for JSONB storage
                # Use _to_jsonable for robust handling of numpy, sets, etc.
                serialized_results = _to_jsonable(results)

                supabase.table("strategy_backtests").update({
                    "status": "completed",
                    "trades_count": trades_count,
                    "win_rate": win_rate,
                    "total_pnl": total_pnl,
                    "metrics": {"results": serialized_results}
                }).eq("batch_id", batch_id).execute()
        except Exception as e:
            print(f"Error persisting batch results for {batch_id}: {e}")
            # We don't want to crash the return value, just log the error

    return results
