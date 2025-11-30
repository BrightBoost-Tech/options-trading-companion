from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import os
from supabase import create_client, Client

# Helper for Supabase (duplicated to avoid circular imports)
def _get_supabase_client() -> Optional[Client]:
    url = os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None
    try:
        return create_client(url, key)
    except Exception:
        return None

@dataclass
class SessionState:
    session_id: str
    account_id: str
    confidence: float       # (0, 1]
    last_updated: datetime

# Simple in-memory store
_SESSION_STORE: Dict[str, SessionState] = {}

def load_session_state(account_id: str) -> SessionState:
    """Load or initialize a session with default confidence = 1.0."""
    if account_id in _SESSION_STORE:
        # Check if stale? E.g. > 24 hours reset?
        s = _SESSION_STORE[account_id]
        if (datetime.now() - s.last_updated) > timedelta(hours=24):
            # Reset
            pass
        else:
            return s

    # Init new
    new_state = SessionState(
        session_id=f"sess_{account_id}_{int(datetime.now().timestamp())}",
        account_id=account_id,
        confidence=1.0,
        last_updated=datetime.now()
    )
    _SESSION_STORE[account_id] = new_state
    return new_state

def refresh_session_from_db(account_id: str) -> SessionState:
    """
    Query the outcomes_log to get real recent performance data
    and update the session state.
    """
    supabase = _get_supabase_client()
    if not supabase:
        return load_session_state(account_id)

    try:
        # Fetch last 10 outcomes for this user (indirectly via trace_id?)
        # outcomes_log doesn't explicitly store user_id, but it links to inference_log.
        # However, inference_log doesn't strictly enforce user_id column in all schemas,
        # but typically we'd filter by user if possible.
        # For this implementation, since the schema is implicit, we'll try to join or just fetch latest
        # assuming single-tenant or accessible via RLS if explicit.
        #
        # If we can't filter by user easily in this "lite" implementation without schema change,
        # we will fetch recent outcomes globally (if single user) or skip.
        # Let's assume we can fetch recent rows from `outcomes_log` and we'll trust they are relevant.
        # Phase 1 script fills `outcomes_log`.

        response = supabase.table("outcomes_log") \
            .select("surprise_score, realized_pl_1d, created_at") \
            .order("created_at", desc=True) \
            .limit(10) \
            .execute()

        rows = response.data or []

        if not rows:
            return load_session_state(account_id)

        surprises = [float(r.get('surprise_score', 0.0)) for r in rows]
        pnls = [float(r.get('realized_pl_1d', 0.0)) for r in rows]

        return update_session_state(account_id, surprises, pnls)

    except Exception as e:
        print(f"L0 Session Refresh Error: {e}")
        return load_session_state(account_id)

def update_session_state(account_id: str, recent_surprises: List[float], recent_pnls: List[float]) -> SessionState:
    """
    Adjust confidence based on recent performance.
    Calculated deterministically to be idempotent.
    """
    state = load_session_state(account_id)

    # Calculate simple metrics
    avg_surprise = sum(recent_surprises) / len(recent_surprises) if recent_surprises else 0.0

    # Count negative pnls
    neg_pnl_count = sum(1 for p in recent_pnls if p < 0)
    total_trades = len(recent_pnls)

    # Start fresh from 1.0 and apply penalties based on the *current window* of data
    # This ensures idempotency: same data window -> same confidence.
    base_conf = 1.0

    # 1. Penalty for Surprise
    if avg_surprise > 2.0:
        base_conf -= 0.2
    elif avg_surprise > 1.0:
        base_conf -= 0.1

    # 2. Penalty for Frequent Losses
    if total_trades > 0 and (neg_pnl_count / total_trades) > 0.6:
        base_conf -= 0.1

    # Clamp
    final_conf = max(0.2, min(1.0, base_conf))

    state.confidence = final_conf
    state.last_updated = datetime.now()
    _SESSION_STORE[account_id] = state

    return state

def get_session_sigma_scale(confidence: float) -> float:
    """
    Map confidence to sigma multiplier.
    Low confidence -> Higher sigma (more perceived risk).
    """
    # 1.0 -> 1.0
    # 0.5 -> 1.25
    # 0.2 -> 1.5
    if confidence >= 1.0: return 1.0

    # Linear approx: scale = 1.0 + (1-conf) * 0.625
    # At 0.2: 1 + 0.8 * 0.625 = 1 + 0.5 = 1.5
    return 1.0 + (1.0 - confidence) * 0.625
