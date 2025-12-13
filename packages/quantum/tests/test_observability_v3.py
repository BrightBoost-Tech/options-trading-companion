import pytest
from unittest.mock import MagicMock, patch
import uuid
import json
from packages.quantum.observability.telemetry import TradeContext, compute_features_hash, emit_trade_event

def test_features_hash_stability():
    f1 = {"a": 1, "b": 2, "c": [1, 2]}
    f2 = {"c": [1, 2], "b": 2, "a": 1} # Different order

    h1 = compute_features_hash(f1)
    h2 = compute_features_hash(f2)

    assert h1 == h2
    assert h1 != "unknown"
    assert h1 != "hash_error"

def test_trade_context_creation():
    ctx = TradeContext.create_new(model_version="v3-test", strategy="iron_condor")
    assert ctx.trace_id is not None
    assert ctx.model_version == "v3-test"
    assert ctx.strategy == "iron_condor"
    assert ctx.features_hash == "unknown"

def test_emit_trade_event():
    mock_analytics = MagicMock()
    ctx = TradeContext(
        trace_id=str(uuid.uuid4()),
        suggestion_id="sugg-456",
        model_version="v1",
        window="midday",
        strategy="long_call",
        regime="high_vol",
        features_hash="abcdef"
    )

    emit_trade_event(
        mock_analytics,
        user_id="user-1",
        ctx=ctx,
        event_name="suggestion_generated",
        properties={"ev": 100}
    )

    mock_analytics.log_event.assert_called_once()
    call_args = mock_analytics.log_event.call_args
    assert call_args.kwargs["user_id"] == "user-1"
    assert call_args.kwargs["event_name"] == "suggestion_generated"
    assert call_args.kwargs["trace_id"] == ctx.trace_id

    props = call_args.kwargs["properties"]
    assert props["model_version"] == "v1"
    assert props["strategy"] == "long_call"
    assert props["features_hash"] == "abcdef"
    assert props["ev"] == 100

def test_analytics_service_extracts_typed_columns():
    # We can mock supabase client
    mock_supabase = MagicMock()
    from packages.quantum.services.analytics_service import AnalyticsService
    service = AnalyticsService(mock_supabase)

    trace_id = str(uuid.uuid4())
    props = {
        "model_version": "v3",
        "suggestion_id": str(uuid.uuid4()),
        "is_paper": True
    }

    service.log_event("u1", "test_event", "test_cat", props, trace_id=trace_id)

    mock_supabase.table.assert_called_with("analytics_events")
    mock_supabase.table().insert.assert_called_once()

    data = mock_supabase.table().insert.call_args[0][0]
    assert data["model_version"] == "v3"
    assert data["is_paper"] is True
    assert data["suggestion_id"] == props["suggestion_id"]
    assert data["trace_id"] == trace_id
