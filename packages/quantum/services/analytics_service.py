"""
Analytics Service for logging UX, system, and trade events.

Wave 1.2 Enhancements:
    - event_key computed for idempotency (sha256 of suggestion_id:event_name or trace_id:event_name:timestamp)
    - Idempotent inserts: unique violations return existing row

Wave 1.3 Enhancements:
    - Added payload_hash support for trace-scoped idempotent events
    - New compute_analytics_event_key_v2() with explicit_idempotency_key option
    - canonical_json() helper for deterministic payload hashing
"""

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple


def canonical_json(data: Dict[str, Any]) -> str:
    """
    Wave 1.3: Convert dict to canonical JSON string for deterministic hashing.

    Uses sorted keys and minimal separators to ensure the same logical dict
    always produces the same string representation.

    Args:
        data: Dictionary to canonicalize

    Returns:
        Canonical JSON string
    """
    if data is None:
        data = {}
    return json.dumps(
        data,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=True,
        default=str
    )


def compute_payload_hash(payload: Dict[str, Any]) -> str:
    """
    Wave 1.3: Compute SHA256 hash of a payload for idempotency.

    Args:
        payload: Dictionary to hash

    Returns:
        64-character hex string (SHA256)
    """
    canonical = canonical_json(payload)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def compute_analytics_event_key(
    event_name: str,
    suggestion_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    timestamp: Optional[str] = None
) -> str:
    """
    Wave 1.2: Compute deterministic event_key for analytics idempotency.

    Strategy:
        - If suggestion_id is present: sha256(suggestion_id:event_name)
        - Else if trace_id is present: sha256(trace_id:event_name:timestamp)
        - Else: sha256(event_name:timestamp) as fallback

    Args:
        event_name: Event type name
        suggestion_id: Optional suggestion UUID
        trace_id: Optional trace ID
        timestamp: Event timestamp (ISO format)

    Returns:
        64-character hex string (SHA256)
    """
    if suggestion_id:
        # Suggestion-scoped events: one event per (suggestion, event_name)
        key_input = f"{suggestion_id}:{event_name}"
    elif trace_id:
        # Trace-scoped events: include timestamp for uniqueness
        key_input = f"{trace_id}:{event_name}:{timestamp or ''}"
    else:
        # Fallback: event_name + timestamp
        key_input = f"{event_name}:{timestamp or ''}"

    return hashlib.sha256(key_input.encode('utf-8')).hexdigest()


def compute_analytics_event_key_v2(
    event_name: str,
    suggestion_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    timestamp: Optional[str] = None,
    payload_hash: Optional[str] = None,
    explicit_idempotency_key: Optional[str] = None
) -> str:
    """
    Wave 1.3: Compute deterministic event_key with enhanced idempotency options.

    Strategy (in priority order):
        1. If explicit_idempotency_key provided: sha256(explicit_idempotency_key)
        2. If suggestion_id present: sha256(suggestion_id:event_name)
        3. If trace_id AND payload_hash present: sha256(trace_id:event_name:payload_hash)
        4. If trace_id present (no payload_hash): sha256(trace_id:event_name:timestamp) [original behavior]
        5. Fallback: sha256(event_name:timestamp)

    Args:
        event_name: Event type name
        suggestion_id: Optional suggestion UUID (makes event suggestion-scoped)
        trace_id: Optional trace ID
        timestamp: Event timestamp (ISO format) - used when no payload_hash
        payload_hash: Optional hash of idempotency payload (enables trace-scoped idempotency)
        explicit_idempotency_key: Optional explicit key (highest priority)

    Returns:
        64-character hex string (SHA256)
    """
    if explicit_idempotency_key:
        # Explicit key takes priority - hash it for consistency
        key_input = explicit_idempotency_key
    elif suggestion_id:
        # Suggestion-scoped events: one event per (suggestion, event_name)
        key_input = f"{suggestion_id}:{event_name}"
    elif trace_id and payload_hash:
        # Wave 1.3: Trace-scoped idempotent events with payload_hash
        key_input = f"{trace_id}:{event_name}:{payload_hash}"
    elif trace_id:
        # Trace-scoped time-series events (original Wave 1.2 behavior)
        key_input = f"{trace_id}:{event_name}:{timestamp or ''}"
    else:
        # Fallback: event_name + timestamp
        key_input = f"{event_name}:{timestamp or ''}"

    return hashlib.sha256(key_input.encode('utf-8')).hexdigest()


class AnalyticsService:
    """
    Low-friction analytics service for logging UX, system, and trade events to Supabase.
    Swallows errors to prevent disruption of main application flow.
    """
    def __init__(self, supabase_client):
        self.supabase = supabase_client

    def log_event(
        self,
        user_id: Optional[str],
        event_name: str,
        category: str,
        properties: Dict[str, Any],
        trace_id: Optional[str] = None,
        session_id: Optional[str] = None,
        idempotency_payload: Optional[Dict[str, Any]] = None,
        idempotency_key: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Logs a generic event to the analytics_events table.
        Extracts typed columns from properties if present for v3 observability.

        Wave 1.2: This method is idempotent. If an event with the same event_key
        already exists, the existing record is returned instead of failing.

        Wave 1.3: Added idempotency_payload and idempotency_key options for
        trace-scoped idempotent events. When provided, the event_key is computed
        deterministically without timestamp, allowing true idempotency on retries.

        Args:
            user_id: User UUID
            event_name: Event type name
            category: Event category (ux, system, trade)
            properties: Event properties dict
            trace_id: Optional trace ID
            session_id: Optional session ID
            idempotency_payload: Optional dict used to compute payload_hash for idempotent key
            idempotency_key: Optional explicit idempotency key (highest priority)

        Returns:
            Inserted or existing record, or None on failure
        """
        if not self.supabase:
            return None

        event_key = None
        try:
            # Ensure trace_id is valid UUID string if provided
            if trace_id:
                try:
                    uuid.UUID(str(trace_id))
                except ValueError:
                    trace_id = None

            # Extract v3 typed columns from properties
            suggestion_id = properties.get("suggestion_id")
            execution_id = properties.get("execution_id")
            model_version = properties.get("model_version")
            window = properties.get("window")
            strategy = properties.get("strategy")
            regime = properties.get("regime")
            features_hash = properties.get("features_hash")
            is_paper = properties.get("is_paper", False)

            # Validate UUIDs for typed columns
            if suggestion_id:
                try:
                    uuid.UUID(str(suggestion_id))
                except ValueError:
                    suggestion_id = None

            if execution_id:
                try:
                    uuid.UUID(str(execution_id))
                except ValueError:
                    execution_id = None

            timestamp = datetime.now(timezone.utc).isoformat()

            # Wave 1.3: Compute payload_hash if idempotency_payload provided
            payload_hash = None
            if idempotency_payload:
                payload_hash = compute_payload_hash(idempotency_payload)

            # Wave 1.3: Use v2 event_key computation with payload_hash support
            event_key = compute_analytics_event_key_v2(
                event_name=event_name,
                suggestion_id=str(suggestion_id) if suggestion_id else None,
                trace_id=str(trace_id) if trace_id else None,
                timestamp=timestamp,
                payload_hash=payload_hash,
                explicit_idempotency_key=idempotency_key
            )

            data = {
                "user_id": user_id,
                "event_name": event_name,
                "category": category,
                "properties": properties,
                "trace_id": str(trace_id) if trace_id else None,
                "session_id": session_id,
                "timestamp": timestamp,
                "event_key": event_key,  # Wave 1.2/1.3
                # v3 Typed Columns
                "suggestion_id": str(suggestion_id) if suggestion_id else None,
                "execution_id": str(execution_id) if execution_id else None,
                "model_version": model_version,
                "window": window,
                "strategy": strategy,
                "regime": regime,
                "features_hash": features_hash,
                "is_paper": is_paper
            }

            # Fire and forget (async ideally, but simple synchronous insert here is fine for low volume)
            result = self.supabase.table("analytics_events").insert(data).execute()
            if result.data:
                return result.data[0]
            return None

        except Exception as e:
            error_str = str(e).lower()
            # Wave 1.2: Handle unique violation as success (idempotent insert)
            if event_key and ("unique" in error_str or "duplicate" in error_str or "23505" in error_str):
                try:
                    existing = self.supabase.table("analytics_events") \
                        .select("*") \
                        .eq("event_key", event_key) \
                        .limit(1) \
                        .execute()
                    if existing.data:
                        print(f"[Analytics] Event '{event_name}' already exists (idempotent)")
                        return existing.data[0]
                except Exception:
                    pass
                return None
            # Swallow error, maybe print to stderr
            print(f"[Analytics] Failed to log event '{event_name}': {e}")
            return None

    def log_suggestion_event(
        self,
        user_id: str,
        suggestion: Dict[str, Any],
        event_name: str,
        trace_id: Optional[str] = None,
        extra_props: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Helper to log events related to trade suggestions with pre-populated properties.
        """
        if not self.supabase:
            return

        try:
            # Use v3 fields from suggestion if available
            s_trace_id = suggestion.get("trace_id")
            s_id = suggestion.get("id")
            s_model = suggestion.get("model_version")
            s_features_hash = suggestion.get("features_hash")
            s_regime = suggestion.get("regime")

            props = {
                "suggestion_id": s_id,
                "symbol": suggestion.get("symbol") or suggestion.get("ticker"),
                "strategy": suggestion.get("strategy"),
                "window": suggestion.get("window"),
                "score": suggestion.get("score") or suggestion.get("confidence_score"),
                "iv_regime": suggestion.get("iv_regime"), # local iv regime (legacy)
                "ev": suggestion.get("metrics", {}).get("ev") or suggestion.get("ev"),
                # v3 fields
                "model_version": s_model,
                "features_hash": s_features_hash,
                "regime": s_regime, # global regime
            }

            if extra_props:
                props.update(extra_props)

            # Try to find trace_id in suggestion if not provided
            if not trace_id:
                if s_trace_id:
                    trace_id = s_trace_id
                else:
                    # Legacy fallback
                    context = suggestion.get("order_json", {}).get("context", {})
                    trace_id = context.get("trace_id")

            self.log_event(
                user_id=user_id,
                event_name=event_name,
                category="ux", # Usually suggestion events are UX driven or system generation
                properties=props,
                trace_id=trace_id
            )

        except Exception as e:
             print(f"[Analytics] Failed to log suggestion event: {e}")
