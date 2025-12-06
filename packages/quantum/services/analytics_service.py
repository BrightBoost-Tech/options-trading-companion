import os
import uuid
from datetime import datetime
from typing import Optional, Dict, Any

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
    ) -> None:
        """
        Logs a generic event to the analytics_events table.
        """
        if not self.supabase:
            return

        try:
            # Ensure trace_id is valid UUID string if provided
            if trace_id:
                try:
                    uuid.UUID(str(trace_id))
                except ValueError:
                    trace_id = None

            data = {
                "user_id": user_id,
                "event_name": event_name,
                "category": category,
                "properties": properties,
                "trace_id": str(trace_id) if trace_id else None,
                "session_id": session_id,
                "timestamp": datetime.now().isoformat()
            }

            # Fire and forget (async ideally, but simple synchronous insert here is fine for low volume)
            self.supabase.table("analytics_events").insert(data).execute()

        except Exception as e:
            # Swallow error, maybe print to stderr
            print(f"[Analytics] Failed to log event '{event_name}': {e}")

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
            props = {
                "suggestion_id": suggestion.get("id"),
                "symbol": suggestion.get("symbol") or suggestion.get("ticker"),
                "strategy": suggestion.get("strategy"),
                "window": suggestion.get("window"),
                "score": suggestion.get("score") or suggestion.get("confidence_score"),
                "iv_regime": suggestion.get("iv_regime"),
                "ev": suggestion.get("metrics", {}).get("ev") or suggestion.get("ev"),
            }

            if extra_props:
                props.update(extra_props)

            # Try to find trace_id in suggestion if not provided
            if not trace_id:
                # Some suggestions might store trace_id in context or metadata
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
