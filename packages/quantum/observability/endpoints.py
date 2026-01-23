from fastapi import APIRouter, Depends, HTTPException, Query, Path
from typing import List, Optional, Any, Dict
from packages.quantum.security import get_current_user
from packages.quantum.security.admin_auth import verify_admin_access, AdminAuthResult
from packages.quantum.security.secrets_provider import SecretsProvider
from supabase import create_client, Client

from .lineage import LineageSigner
from .audit_log_service import AuditLogService

router = APIRouter(
    prefix="/observability",
    tags=["observability"],
    dependencies=[Depends(get_current_user)]
)

# Admin Client Init
secrets_provider = SecretsProvider()
supa_secrets = secrets_provider.get_supabase_secrets()
url = supa_secrets.url
key = supa_secrets.service_role_key
supabase_admin: Client = create_client(url, key) if url and key else None

def get_admin_client():
    if not supabase_admin:
        raise HTTPException(status_code=503, detail="Database not available")
    return supabase_admin

@router.get("/trade_attribution")
async def get_trade_attribution(
    limit: int = Query(50, le=100),
    window: Optional[str] = Query(None),
    strategy: Optional[str] = Query(None),
    regime: Optional[str] = Query(None),
    client: Client = Depends(get_admin_client),
    admin: AdminAuthResult = Depends(verify_admin_access)
):
    """
    Query the trade_attribution_v3 view.
    Requires Admin privileges.
    """
    query = client.table("trade_attribution_v3").select("*").order("created_at", desc=True).limit(limit)

    if window:
        # Quote "window" just in case, though library handles it.
        # But for filters, Supabase-py maps string keys.
        query = query.eq("window", window)
    if strategy:
        query = query.eq("strategy", strategy)
    if regime:
        query = query.eq("regime", regime)

    try:
        res = query.execute()
        return res.data
    except Exception as e:
        print(f"Error querying trade_attribution_v3: {e}")
        raise HTTPException(status_code=500, detail="Failed to query trade attribution")

@router.get("/ev_leakage")
async def get_ev_leakage(
    limit: int = Query(50, le=100),
    client: Client = Depends(get_admin_client),
    admin: AdminAuthResult = Depends(verify_admin_access)
):
    """
    Query ev_leakage_by_bucket_v3 view, sorted by most negative ev_leakage.
    Requires Admin privileges.
    """
    try:
        query = client.table("ev_leakage_by_bucket_v3").select("*").order("ev_leakage", desc=False).limit(limit)
        res = query.execute()
        return res.data
    except Exception as e:
        print(f"Error querying ev_leakage_by_bucket_v3: {e}")
        raise HTTPException(status_code=500, detail="Failed to query EV leakage")


@router.get("/trace/{trace_id}")
async def get_trace(
    trace_id: str = Path(..., description="Trace ID to look up"),
    user_id: str = Depends(get_current_user),
    client: Client = Depends(get_admin_client)
):
    """
    v4 Observability: Get full trace lifecycle with integrity verification.

    Returns the suggestion, audit log, and XAI attribution for a trace,
    along with cryptographic verification status.

    Enforces ownership: only returns data for suggestions owned by the current user.

    Response:
    {
        "status": "VERIFIED" | "TAMPERED" | "UNVERIFIED",
        "trace_id": "...",
        "integrity": {
            "stored_hash": "...",
            "computed_hash": "...",
            "signature_valid": true/false
        },
        "lifecycle": {
            "suggestion": {...},
            "audit_log": [...],
            "attribution": {...}
        }
    }
    """
    try:
        # 1. Fetch suggestion by trace_id
        suggestion_res = client.table("trade_suggestions") \
            .select("*") \
            .eq("trace_id", trace_id) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()

        if not suggestion_res.data:
            raise HTTPException(status_code=404, detail="Trace not found")

        suggestion = suggestion_res.data[0]

        # 2. Enforce ownership
        suggestion_user_id = suggestion.get("user_id")
        if suggestion_user_id != user_id:
            raise HTTPException(
                status_code=403,
                detail="Access denied: trace belongs to another user"
            )

        # 3. Verify signature
        lineage = suggestion.get("decision_lineage") or {}
        stored_hash = suggestion.get("lineage_hash") or ""
        stored_sig = suggestion.get("lineage_sig") or ""

        integrity = {
            "stored_hash": stored_hash,
            "computed_hash": "",
            "signature_valid": False
        }

        if lineage and stored_hash and stored_sig:
            # Verify using both hash comparison and signature verification
            is_valid, computed_hash, status = LineageSigner.verify_with_hash(
                stored_hash=stored_hash,
                stored_signature=stored_sig,
                data=lineage
            )
            integrity["computed_hash"] = computed_hash
            integrity["signature_valid"] = is_valid
            verification_status = status
        elif not stored_hash and not stored_sig:
            # No v4 fields - might be a v3 suggestion
            verification_status = "UNVERIFIED"
        else:
            verification_status = "UNVERIFIED"

        # 4. Fetch audit log
        audit_service = AuditLogService(client)
        audit_log = audit_service.get_audit_events_for_trace(trace_id)

        # Wave 1.2: Add verification per audit event for institutional usability
        audit_log_verified = []
        for event in audit_log:
            event_copy = dict(event)
            event_copy["verification"] = audit_service.verify_audit_event(event)
            audit_log_verified.append(event_copy)

        # 5. Fetch attribution
        suggestion_id = suggestion.get("id")
        attribution = None
        if suggestion_id:
            attribution = audit_service.get_attribution_for_suggestion(suggestion_id)

        return {
            "status": verification_status,
            "trace_id": trace_id,
            "integrity": integrity,
            "lifecycle": {
                "suggestion": suggestion,
                "audit_log": audit_log_verified,  # Wave 1.2: includes verification per event
                "attribution": attribution
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in get_trace: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve trace")
