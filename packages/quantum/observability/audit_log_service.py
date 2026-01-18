"""
Observability v4: Audit Log Service

Provides helpers for writing to decision_audit_events and xai_attributions tables.
Ensures proper signing and integrity for all audit records.

Usage:
    from packages.quantum.observability.audit_log_service import AuditLogService

    audit_service = AuditLogService(supabase_client)

    # Log a suggestion_generated event
    audit_service.log_audit_event(
        user_id=user_id,
        trace_id=trace_id,
        suggestion_id=suggestion_id,
        event_name="suggestion_generated",
        payload={"lineage": lineage_dict, ...},
        strategy="vertical_spread",
        regime="normal"
    )

    # Write XAI attribution
    audit_service.write_attribution(
        suggestion_id=suggestion_id,
        trace_id=trace_id,
        drivers_regime={"global": "normal", "local": "elevated"},
        drivers_risk={"budget_used_pct": 45},
        drivers_constraints={"active": {...}},
        drivers_agents=[{"name": "SizingAgent", "score": 72}]
    )
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from supabase import Client

from .lineage import LineageSigner, sign_payload


# Table names
AUDIT_EVENTS_TABLE = "decision_audit_events"
XAI_ATTRIBUTIONS_TABLE = "xai_attributions"


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
            Inserted record or None on failure
        """
        if not self.supabase:
            return None

        try:
            # Sign the payload
            payload_hash, payload_sig = sign_payload(payload)

            record = {
                "user_id": user_id,
                "trace_id": trace_id,
                "suggestion_id": suggestion_id,
                "event_name": event_name,
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

        Args:
            suggestion_id: UUID of the suggestion
            trace_id: Trace ID
            drivers_regime: Regime context {global, local, effective}
            drivers_risk: Risk budget info {budget_used_pct, remaining, status}
            drivers_constraints: Constraint info {active, vetoed}
            drivers_agents: Agent contributions [{name, score, metadata}, ...]

        Returns:
            Inserted record or None on failure
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

    def verify_audit_event(self, event: Dict) -> bool:
        """
        Verify the integrity of an audit event.

        Args:
            event: Audit event record with payload, payload_hash, payload_sig

        Returns:
            True if signature is valid, False otherwise
        """
        payload = event.get("payload", {})
        stored_sig = event.get("payload_sig", "")

        return LineageSigner.verify(payload, stored_sig)


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
