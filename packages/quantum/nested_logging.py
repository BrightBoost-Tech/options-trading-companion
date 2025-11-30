import os
import uuid
from datetime import datetime
import json
from typing import Optional, Dict, List, Any
from supabase import create_client, Client
from dotenv import load_dotenv

# Ensure env vars are loaded
load_dotenv()

def _get_supabase_client() -> Optional[Client]:
    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Logging Warning: Supabase credentials missing. Logging disabled.")
        return None
    try:
        return create_client(url, key)
    except Exception as e:
        print(f"Logging Error: Failed to initialize Supabase client: {e}")
        return None

def log_inference(
    symbol_universe: List[str],
    inputs_snapshot: Dict[str, Any],
    predicted_mu: Dict[str, float],
    predicted_sigma: Dict[str, Any],
    optimizer_profile: str
) -> uuid.UUID:
    """
    Insert into inference_log and return trace_id. Should fail gracefully.

    Args:
        symbol_universe: List of symbols considered.
        inputs_snapshot: Snapshot of inputs (prices, risk params, etc).
        predicted_mu: Predicted expected returns.
        predicted_sigma: Predicted covariance matrix (or related metrics).
        optimizer_profile: Name of the profile used (e.g., 'balanced', 'aggressive').

    Returns:
        UUID of the trace_id. Returns a new local UUID if DB write fails,
        ensuring the flow continues but marking the log as 'lost' implicitly.
    """
    trace_id = uuid.uuid4()

    supabase = _get_supabase_client()
    if not supabase:
        return trace_id

    try:
        # Pydantic models might be passed, ensure conversion to dict/json compatible types if needed.
        # Ideally caller handles this, but basic safety here:

        # Helper to serialize if needed (though jsonb handles dicts)

        data = {
            "trace_id": str(trace_id),
            "timestamp": datetime.now().isoformat(),
            "symbol_universe": symbol_universe,
            "inputs_snapshot": inputs_snapshot,
            "predicted_mu": predicted_mu,
            "predicted_sigma": predicted_sigma,
            "optimizer_profile": optimizer_profile
        }

        supabase.table("inference_log").insert(data).execute()

    except Exception as e:
        print(f"Logging Error: Failed to write to inference_log: {e}")
        # We return the generated trace_id anyway so the optimization flow doesn't break
        # The outcomes might fail to link if the inference row is missing, which is acceptable failure mode.

    return trace_id

def log_outcome(trace_id: uuid.UUID, realized_pl_1d: float, realized_vol_1d: float, surprise_score: float):
    """
    Insert into outcomes_log.
    """
    supabase = _get_supabase_client()
    if not supabase:
        return

    try:
        data = {
            "trace_id": str(trace_id),
            "realized_pl_1d": realized_pl_1d,
            "realized_vol_1d": realized_vol_1d,
            "surprise_score": surprise_score,
            "created_at": datetime.now().isoformat()
        }

        supabase.table("outcomes_log").insert(data).execute()

    except Exception as e:
        print(f"Logging Error: Failed to write to outcomes_log: {e}")
