"""
Observability v4: Audit Log Service

Provides helpers for writing to decision_audit_events and xai_attributions tables.
Ensures proper signing and integrity for all audit records.

Wave 1.1 Enhancements:
    - event_key computed for idempotency (sha256 of suggestion_id:event_name or trace_id:event_name:payload_hash)
    - Idempotent inserts: unique violations return existing row
    - Strengthened verify_audit_event: checks payload_hash AND signature

Usage:
    from packages.quantum.observability.audit_log_service import AuditLogService

    audit_service = AuditLogService(supabase_client)

    # Log a suggestion_generated event (idempotent)
    audit_service.log_audit_event(
        user_id=user_id,
        trace_id=trace_id,
        suggestion_id=suggestion_id,
        event_name="suggestion_generated",
        payload={"lineage": lineage_dict, ...},
        strategy="vertical_spread",
        regime="normal"
    )

    # Write XAI attribution (idempotent - one per suggestion)
    audit_service.write_attribution(
        suggestion_id=suggestion_id,
        trace_id=trace_id,
        drivers_regime={"global": "normal", "local": "elevated"},
        drivers_risk={"budget_used_pct": 45},
        drivers_constraints={"active": {...}},
        drivers_agents=[{"name": "SizingAgent", "score": 72}]
    )
"""

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from supabase import Client

from .lineage import LineageSigner, sign_payload


# Table names
AUDIT_EVENTS_TABLE = "decision_audit_events"
XAI_ATTRIBUTIONS_TABLE = "xai_attributions"


def compute_event_key(
    suggestion_id: Optional[str],
    trace_id: str,
    event_name: str,
    payload_hash: str
) -> str:
    """
    Wave 1.1: Compute deterministic event_key for idempotency.

    Strategy:
        - If suggestion_id is present: sha256(suggestion_id:event_name)
        - Otherwise: sha256(trace_id:event_name:payload_hash)

    This ensures the same logical event always produces the same key,
    allowing idempotent inserts via unique constraint on event_key.

    Args:
        suggestion_id: Optional suggestion UUID
        trace_id: Trace ID
        event_name: Event type name
        payload_hash: Hash of the payload

    Returns:
        64-character hex string (SHA256)
    """
    if suggestion_id:
        # Suggestion-scoped events: one event per (suggestion, event_name)
        key_input = f"{suggestion_id}:{event_name}"
    else:
        # Trace-scoped events: include payload_hash for uniqueness
        key_input = f"{trace_id}:{event_name}:{payload_hash}"

    return hashlib.sha256(key_input.encode('utf-8')).hexdigest()


class AuditLogService:
    """
    Service for writing immutable audit logs and XAI attributions.

    All writes include cryptographic signatures for tamper detection.
    """

    def __init__(self, supabase_client: Client):
        """
        Initialize with a Supabase client.

        Args:
            supabase_client: Supabase client (preferably service role for background jobs)
        """
        self.supabase = supabase_client

    def log_audit_event(
        self,
        user_id: str,
        trace_id: str,
        event_name: str,
        payload: Dict[str, Any],
        suggestion_id: Optional[str] = None,
        strategy: Optional[str] = None,
        regime: Optional[str] = None,
        prev_hash: Optional[str] = None  # For future chaining
    ) -> Optional[Dict]:
        """
        Log an event to decision_audit_events with cryptographic signature.

        Wave 1.1: This method is idempotent. If an event with the same event_key
        already exists, the existing record is returned instead of failing.

        Args:
            user_id: UUID of the user
            trace_id: Trace ID linking related events
            event_name: Event type (e.g., "suggestion_generated", "order_staged")
            payload: Event payload (will be signed)
            suggestion_id: Optional linked suggestion
            strategy: Optional strategy name for filtering
            regime: Optional regime context for filtering
            prev_hash: Optional hash of previous event (for chaining)

        Returns:
            Inserted or existing record, or None on failure
        """
        if not self.supabase:
            return None

        try:
            # Sign the payload
            payload_hash, payload_sig = sign_payload(payload)

            # Wave 1.1: Compute event_key for idempotency
            event_key = compute_event_key(
                suggestion_id=suggestion_id,
                trace_id=trace_id,
                event_name=event_name,
                payload_hash=payload_hash
            )

            record = {
                "user_id": user_id,
                "trace_id": trace_id,
                "suggestion_id": suggestion_id,
                "event_name": event_name,
                "event_key": event_key,  # Wave 1.1
                "payload": payload,
                "payload_hash": payload_hash,
                "payload_sig": payload_sig,
                "prev_hash": prev_hash,
                "strategy": strategy,
                "regime": regime,
                "created_at": datetime.now(timezone.utc).isoformat()
            }

            result = self.supabase.table(AUDIT_EVENTS_TABLE).insert(record).execute()

            if result.data:
                return result.data[0]
            return None

        except Exception as e:
            error_str = str(e).lower()
            # Wave 1.1: Handle unique violation as success (idempotent insert)
            if "unique" in error_str or "duplicate" in error_str or "23505" in error_str:
                # Try to fetch and return the existing record
                try:
                    existing = self.supabase.table(AUDIT_EVENTS_TABLE) \
                        .select("*") \
                        .eq("event_key", event_key) \
                        .limit(1) \
                        .execute()
                    if existing.data:
                        print(f"[AuditLog] Event '{event_name}' already exists (idempotent)")
                        return existing.data[0]
                except Exception:
                    pass
                return None
            print(f"[AuditLog] Failed to log event '{event_name}': {e}")
            return None

    def write_attribution(
        self,
        suggestion_id: str,
        trace_id: str,
        drivers_regime: Optional[Dict[str, Any]] = None,
        drivers_risk: Optional[Dict[str, Any]] = None,
        drivers_constraints: Optional[Dict[str, Any]] = None,
        drivers_agents: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[Dict]:
        """
        Write XAI attribution for a suggestion.

        Wave 1.1: This method is idempotent. Only one attribution per suggestion
        is allowed (enforced by unique index). If attribution already exists,
        the existing record is returned.

        Args:
            suggestion_id: UUID of the suggestion
            trace_id: Trace ID
            drivers_regime: Regime context {global, local, effective}
            drivers_risk: Risk budget info {budget_used_pct, remaining, status}
            drivers_constraints: Constraint info {active, vetoed}
            drivers_agents: Agent contributions [{name, score, metadata}, ...]

        Returns:
            Inserted or existing record, or None on failure
        """
        if not self.supabase:
            return None

        try:
            record = {
                "suggestion_id": suggestion_id,
                "trace_id": trace_id,
                "drivers_regime": drivers_regime,
                "drivers_risk": drivers_risk,
                "drivers_constraints": drivers_constraints,
                "drivers_agents": drivers_agents,
                "computed_at": datetime.now(timezone.utc).isoformat()
            }

            result = self.supabase.table(XAI_ATTRIBUTIONS_TABLE).insert(record).execute()

            if result.data:
                return result.data[0]
            return None

        except Exception as e:
            error_str = str(e).lower()
            # Wave 1.1: Handle unique violation as success (idempotent insert)
            if "unique" in error_str or "duplicate" in error_str or "23505" in error_str:
                # Return existing attribution
                try:
                    existing = self.supabase.table(XAI_ATTRIBUTIONS_TABLE) \
                        .select("*") \
                        .eq("suggestion_id", suggestion_id) \
                        .limit(1) \
                        .execute()
                    if existing.data:
                        print(f"[AuditLog] Attribution for suggestion already exists (idempotent)")
                        return existing.data[0]
                except Exception:
                    pass
                return None
            print(f"[AuditLog] Failed to write attribution: {e}")
            return None

    def get_audit_events_for_trace(self, trace_id: str) -> List[Dict]:
        """
        Retrieve all audit events for a trace, ordered by creation time.

        Args:
            trace_id: The trace ID to query

        Returns:
            List of audit event records
        """
        if not self.supabase:
            return []

        try:
            result = self.supabase.table(AUDIT_EVENTS_TABLE) \
                .select("*") \
                .eq("trace_id", trace_id) \
                .order("created_at", desc=False) \
                .execute()

            return result.data or []

        except Exception as e:
            print(f"[AuditLog] Failed to get audit events: {e}")
            return []

    def get_attribution_for_suggestion(self, suggestion_id: str) -> Optional[Dict]:
        """
        Retrieve XAI attribution for a suggestion.

        Args:
            suggestion_id: The suggestion ID

        Returns:
            Attribution record or None
        """
        if not self.supabase:
            return None

        try:
            result = self.supabase.table(XAI_ATTRIBUTIONS_TABLE) \
                .select("*") \
                .eq("suggestion_id", suggestion_id) \
                .limit(1) \
                .execute()

            if result.data:
                return result.data[0]
            return None

        except Exception as e:
            print(f"[AuditLog] Failed to get attribution: {e}")
            return None

    def verify_audit_event(self, event: Dict) -> Dict[str, Any]:
        """
        Verify the integrity of an audit event.

        Wave 1.1: Strengthened verification that checks BOTH:
        1. Payload hash matches stored hash (content integrity)
        2. Signature is valid (authenticity)

        Args:
            event: Audit event record with payload, payload_hash, payload_sig

        Returns:
            Dict with verification result:
            {
                "valid": bool,
                "status": "VERIFIED" | "TAMPERED" | "UNVERIFIED" | "HASH_MISMATCH",
                "stored_hash": str,
                "computed_hash": str,
                "signature_checked": bool
            }
        """
        payload = event.get("payload", {})
        stored_hash = event.get("payload_hash", "")
        stored_sig = event.get("payload_sig", "")

        result = {
            "valid": False,
            "status": "UNVERIFIED",
            "stored_hash": stored_hash,
            "computed_hash": "",
            "signature_checked": False
        }

        if not stored_hash or not stored_sig:
            result["status"] = "UNVERIFIED"
            return result

        # Wave 1.1: Use verify_with_hash for complete verification
        is_valid, computed_hash, status = LineageSigner.verify_with_hash(
            stored_hash=stored_hash,
            stored_signature=stored_sig,
            data=payload
        )

        result["computed_hash"] = computed_hash
        result["signature_checked"] = True
        result["valid"] = is_valid
        result["status"] = status

        return result

    def verify_audit_event_simple(self, event: Dict) -> bool:
        """
        Simple verification for backward compatibility.

        Args:
            event: Audit event record

        Returns:
            True if event is verified, False otherwise
        """
        result = self.verify_audit_event(event)
        return result.get("valid", False)


# =============================================================================
# Convenience Functions
# =============================================================================

def build_attribution_from_lineage(
    lineage: Dict[str, Any],
    ctx_regime: Optional[str] = None,
    sym_regime: Optional[str] = None,
    global_regime: Optional[str] = None,
    budget_info: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Build XAI attribution dict from lineage and context.

    Args:
        lineage: Decision lineage from DecisionLineageBuilder.build()
        ctx_regime: Effective/context regime
        sym_regime: Symbol-specific regime
        global_regime: Global market regime
        budget_info: Risk budget info dict

    Returns:
        Dict with drivers_* fields ready for write_attribution()
    """
    # Extract agents from lineage
    agents = lineage.get("agents_involved", [])
    vetoed = lineage.get("vetoed_agents", [])
    constraints = lineage.get("active_constraints", {})

    return {
        "drivers_regime": {
            "global": global_regime,
            "local": sym_regime,
            "effective": ctx_regime
        },
        "drivers_risk": budget_info or {},
        "drivers_constraints": {
            "active": constraints,
            "vetoed": vetoed
        },
        "drivers_agents": agents
    }
