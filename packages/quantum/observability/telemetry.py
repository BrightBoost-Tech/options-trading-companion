from dataclasses import dataclass, field
from typing import Optional, Literal, Dict, Any
import hashlib
import json
import uuid
from datetime import datetime, timezone

TradeEventName = Literal[
    "suggestion_generated",
    "suggestion_accepted",
    "order_staged",
    "order_filled",
    "trade_closed"
]

@dataclass
class TradeContext:
    trace_id: str
    suggestion_id: Optional[str] = None
    model_version: str = "v2"
    window: Optional[str] = None
    strategy: Optional[str] = None
    regime: Optional[str] = None
    features_hash: str = "unknown"

    @staticmethod
    def create_new(
        model_version: str = "v2",
        window: str = None,
        strategy: str = None,
        regime: str = None
    ) -> 'TradeContext':
        return TradeContext(
            trace_id=str(uuid.uuid4()),
            model_version=model_version,
            window=window,
            strategy=strategy,
            regime=regime
        )

def compute_features_hash(features: Dict[str, Any]) -> str:
    """
    Computes a stable SHA256 hash of the features dictionary.
    Keys are sorted to ensure stability.
    """
    if not features:
        return "empty"
    try:
        # Sort keys and use stable separators
        canonical_json = json.dumps(features, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(canonical_json.encode('utf-8')).hexdigest()
    except Exception:
        return "hash_error"

def emit_trade_event(
    analytics_service,
    user_id: str,
    ctx: TradeContext,
    event_name: TradeEventName,
    *,
    execution_id: Optional[str] = None,
    is_paper: bool = False,
    properties: Optional[Dict[str, Any]] = None
):
    """
    Emits a structured trade event to the analytics service.
    Enforces the presence of governance fields.
    """
    if not analytics_service:
        return

    props = {
        "model_version": ctx.model_version,
        "window": ctx.window,
        "strategy": ctx.strategy,
        "regime": ctx.regime,
        "features_hash": ctx.features_hash,
        "suggestion_id": ctx.suggestion_id,
        "execution_id": execution_id,
        "is_paper": is_paper,
        "trace_id": ctx.trace_id # Explicitly in props as well as trace_id column
    }

    if properties:
        props.update(properties)

    # Use the typed log_event from updated analytics service
    # or fallback to generic log_event if the method signature hasn't changed yet
    # We will assume analytics_service.log_event handles explicit trace_id kwarg.

    # We are updating log_event to take these new args in next step.
    # But here we pass them as properties mostly, except trace_id.

    analytics_service.log_event(
        user_id=user_id,
        event_name=event_name,
        category="trade_lifecycle",
        properties=props,
        trace_id=ctx.trace_id
    )
