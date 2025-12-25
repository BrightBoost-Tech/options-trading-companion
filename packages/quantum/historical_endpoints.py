import traceback
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, Literal, Dict, Any
from pydantic import BaseModel
from packages.quantum.security import get_current_user
from packages.quantum.services.historical_simulation import HistoricalCycleService
from packages.quantum.market_data import PolygonService

router = APIRouter(tags=["Historical Simulation"])

class HistoricalCycleRequest(BaseModel):
    mode: Literal["deterministic", "random"] = "deterministic"
    cursor: Optional[str] = None
    symbol: Optional[str] = "SPY"
    seed: Optional[int] = None

@router.post("/historical/run-cycle")
async def run_historical_cycle(
    request: HistoricalCycleRequest,
    user_id: str = Depends(get_current_user)
):
    try:
        # Instantiate service (PolygonService handles its own env vars)
        poly_service = PolygonService()
        service = HistoricalCycleService(polygon_service=poly_service)

        # Run cycle
        result = service.run_cycle(
            cursor_date_str=request.cursor,
            symbol=request.symbol,
            user_id=user_id,
            mode=request.mode,
            seed=request.seed
        )

        # Map backend keys to frontend expectations
        # Frontend expects: entryConviction, exitConviction, regime (top level)
        if "convictionAtEntry" in result:
            result["entryConviction"] = result["convictionAtEntry"]
        if "convictionAtExit" in result:
            result["exitConviction"] = result["convictionAtExit"]

        # Map regime for easy display (prefer entry regime as the "trade regime")
        if "regimeAtEntry" in result:
            result["regime"] = result["regimeAtEntry"]
        elif "regimeAtExit" in result:
             result["regime"] = result["regimeAtExit"]

        return result

    except Exception as e:
        print(f"Historical cycle error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
