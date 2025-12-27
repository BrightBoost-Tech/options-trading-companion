import os
import uuid
from datetime import datetime
import json
from typing import Optional, Dict, List, Any
from supabase import create_client, Client
from dotenv import load_dotenv
import numpy as np

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

def _json_serialize(obj: Any) -> Any:
    """Helper to serialize numpy types for JSON."""
    if isinstance(obj, (np.integer, int)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return float(obj)
    if isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, uuid.UUID):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _json_serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_serialize(x) for x in obj]
    return obj

def log_inference(
    symbol_universe: List[str],
    inputs_snapshot: Dict[str, Any],
    predicted_mu: Dict[str, float],
    predicted_sigma: Dict[str, Any],
    optimizer_profile: str
) -> uuid.UUID:
    """
    Insert into inference_log and return trace_id. Should fail gracefully.
    """
    trace_id = uuid.uuid4()

    supabase = _get_supabase_client()
    if not supabase:
        return trace_id

    try:
        data = {
            "trace_id": str(trace_id),
            "timestamp": datetime.now().isoformat(),
            "symbol_universe": symbol_universe,
            "inputs_snapshot": _json_serialize(inputs_snapshot),
            "predicted_mu": _json_serialize(predicted_mu),
            "predicted_sigma": _json_serialize(predicted_sigma),
            "optimizer_profile": optimizer_profile
        }

        supabase.table("inference_log").insert(data).execute()

    except Exception as e:
        print(f"Logging Error: Failed to write to inference_log: {e}")

    return trace_id

def log_decision(
    trace_id: uuid.UUID,
    user_id: str,
    decision_type: str,
    content: Dict[str, Any]
):
    """
    Log the actual decision taken (optimizer weights, sizing, etc.) to decision_logs.
    """
    supabase = _get_supabase_client()
    if not supabase:
        return

    try:
        data = {
            "trace_id": str(trace_id),
            "user_id": user_id,
            "decision_type": decision_type,
            "content": _json_serialize(content),
            "created_at": datetime.now().isoformat()
        }
        supabase.table("decision_logs").insert(data).execute()
    except Exception as e:
        print(f"Logging Error: Failed to write to decision_logs: {e}")

def log_outcome(
    trace_id: uuid.UUID,
    realized_pl_1d: float,
    realized_vol_1d: float,
    surprise_score: float,
    attribution_type: str = 'portfolio_snapshot',
    related_id: Optional[uuid.UUID] = None
):
    """
    Insert into outcomes_log.
    """
    supabase = _get_supabase_client()
    if not supabase:
        return

    try:
        data = {
            "trace_id": str(trace_id),
            "realized_pl_1d": float(realized_pl_1d),
            "realized_vol_1d": float(realized_vol_1d),
            "surprise_score": float(surprise_score),
            "attribution_type": attribution_type,
            "created_at": datetime.now().isoformat()
        }

        if related_id:
            data["related_id"] = str(related_id)

        supabase.table("outcomes_log").insert(data).execute()

    except Exception as e:
        print(f"Logging Error: Failed to write to outcomes_log: {e}")
