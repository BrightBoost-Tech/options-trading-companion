import os
import uuid
from datetime import datetime
import json
from typing import Optional, Dict, List, Any
from supabase import create_client, Client
from dotenv import load_dotenv
import numpy as np
from packages.quantum.common_enums import OutcomeStatus

# Ensure env vars are loaded
load_dotenv()

def _get_supabase_client() -> Optional[Client]:
    from packages.quantum.supabase_env import get_sanitized_supabase_env
    url, key = get_sanitized_supabase_env()
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
    optimizer_profile: str,
    trace_id: Optional[uuid.UUID] = None
) -> uuid.UUID:
    """
    Insert into inference_log and return trace_id. Should fail gracefully.
    If trace_id is provided, it uses it; otherwise generates new one.
    """
    if trace_id is None:
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

def _ensure_inference_log_exists(supabase: Client, trace_id: uuid.UUID) -> bool:
    """
    Ensure an inference_log row exists for the given trace_id.
    Creates a minimal placeholder if missing.
    Returns True if successful (or already exists), False on error.
    """
    try:
        data = {
            "trace_id": str(trace_id),
            "timestamp": datetime.now().isoformat(),
            "symbol_universe": [],
            "inputs_snapshot": {},
            "predicted_mu": {},
            "predicted_sigma": {},
            "optimizer_profile": "auto_placeholder"
        }
        supabase.table("inference_log").insert(data).execute()
        print(f"[nested_logging] Created placeholder inference_log for trace_id={trace_id}")
        return True
    except Exception as e:
        err_str = str(e).lower()
        # Ignore duplicate/unique constraint violations (already exists)
        if "duplicate" in err_str or "unique" in err_str or "23505" in err_str:
            return True
        print(f"[nested_logging] Failed to create inference_log placeholder: {e}")
        return False


def log_decision(
    trace_id: uuid.UUID,
    user_id: str,
    decision_type: str,
    content: Dict[str, Any]
) -> uuid.UUID:
    """
    Log the actual decision taken (optimizer weights, sizing, etc.) to decision_logs.
    Returns the trace_id (decision_id) to verify stability.

    If FK constraint fails (inference_log missing), auto-creates a placeholder and retries.
    """
    supabase = _get_supabase_client()
    if not supabase:
        return trace_id

    data = {
        "trace_id": str(trace_id),
        "user_id": user_id,
        "decision_type": decision_type,
        "content": _json_serialize(content),
        "created_at": datetime.now().isoformat()
    }

    try:
        supabase.table("decision_logs").insert(data).execute()
    except Exception as e:
        err_str = str(e).lower()
        # Check for FK violation (23503 = foreign_key_violation, or constraint name)
        if "23503" in err_str or "fk_decision_logs_trace" in err_str or "foreign key" in err_str:
            print(f"[nested_logging] FK violation on decision_logs, creating inference_log placeholder...")
            if _ensure_inference_log_exists(supabase, trace_id):
                # Retry the insert
                try:
                    supabase.table("decision_logs").insert(data).execute()
                    print(f"[nested_logging] Retry succeeded after creating inference_log placeholder")
                except Exception as retry_err:
                    print(f"Logging Error: Retry failed for decision_logs: {retry_err}")
            else:
                print(f"Logging Error: Could not create inference_log placeholder, decision_logs insert failed")
        else:
            print(f"Logging Error: Failed to write to decision_logs: {e}")

    return trace_id

def log_outcome(
    trace_id: uuid.UUID,
    realized_pl_1d: float,
    realized_vol_1d: float,
    surprise_score: float,
    attribution_type: str = 'portfolio_snapshot',
    related_id: Optional[uuid.UUID] = None,
    counterfactual_pl_1d: Optional[float] = None,
    counterfactual_available: bool = False,
    status: str = OutcomeStatus.COMPLETE.value,
    reason_codes: List[str] = None,
    **kwargs
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
            "created_at": datetime.now().isoformat(),
            "status": status
        }

        if reason_codes is not None:
             data["reason_codes"] = reason_codes
        else:
             data["reason_codes"] = []

        if related_id:
            data["related_id"] = str(related_id)

        if counterfactual_available:
            data["counterfactual_available"] = True
            if counterfactual_pl_1d is not None:
                data["counterfactual_pl_1d"] = float(counterfactual_pl_1d)

        # Merge extra kwargs like counterfactual_reason
        data.update(kwargs)

        supabase.table("outcomes_log").insert(data).execute()

    except Exception as e:
        print(f"Logging Error: Failed to write to outcomes_log: {e}")
