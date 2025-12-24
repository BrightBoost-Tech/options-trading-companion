from typing import List, Dict, Any, Optional
from datetime import datetime
from .historical_simulation import HistoricalCycleService

def _run_backtest_workflow(user_id: str, request, name: str, config) -> List[Dict[str, Any]]:
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

        # Run one cycle
        result = service.run_cycle(
            cursor_date_str=cursor,
            symbol=symbol,
            user_id=user_id,
            config=config,
            mode="deterministic"
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

    return results
