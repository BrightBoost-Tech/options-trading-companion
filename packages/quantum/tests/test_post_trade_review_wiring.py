import pytest
from unittest.mock import MagicMock, patch
import uuid
from packages.quantum.paper_endpoints import _run_attribution

@pytest.fixture
def mock_supabase():
    mock = MagicMock()
    # Mock chain for insert
    mock.table.return_value.insert.return_value.execute.return_value.data = [{"id": str(uuid.uuid4())}]
    # Mock chain for select suggestion
    mock.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "ev": 10.0,
        "model_version": "v1",
        "features_hash": "abc",
        "strategy": "iron_condor",
        "window": "midday",
        "regime": "neutral",
        "agent_signals": {"vol_surface": {"score": 80}}
    }
    return mock

@patch("packages.quantum.paper_endpoints.PostTradeReviewAgent")
def test_run_attribution_wires_post_trade_review(MockPostTradeReviewAgent, mock_supabase):
    """
    Test that _run_attribution calls PostTradeReviewAgent and puts the result in details_json.
    """
    # Setup Mock Agent
    mock_agent_instance = MockPostTradeReviewAgent.return_value
    mock_agent_signal = MagicMock()
    mock_agent_signal.model_dump.return_value = {
        "agent_id": "post_trade_review",
        "score": 100.0,
        "metadata": {"review.outcome": "WIN"}
    }
    mock_agent_instance.evaluate.return_value = mock_agent_signal

    user_id = str(uuid.uuid4())
    order = {
        "id": str(uuid.uuid4()),
        "filled_qty": 10,
        "trace_id": "trace-123",
        "suggestion_id": "sugg-123",
        "quote_at_fill": {"bid_price": 1.0, "ask_price": 1.2}
    }
    position = {
        "avg_entry_price": 1.0,
        "strategy_key": "AAPL_iron_condor"
    }
    side = "sell"
    fees = 1.0
    exit_fill = 1.5

    # Execute
    with patch("packages.quantum.paper_endpoints.logging"): # suppress logging
        _run_attribution(mock_supabase, user_id, order, position, exit_fill, fees, side)

    # Verify Agent Call
    MockPostTradeReviewAgent.assert_called_once()
    mock_agent_instance.evaluate.assert_called_once()

    # Verify Context passed to agent
    call_args = mock_agent_instance.evaluate.call_args
    context = call_args[0][0]
    assert context["strategy"] == "iron_condor"
    assert context["window"] == "midday"
    assert context["regime"] == "neutral"
    assert context["agent_signals"] == {"vol_surface": {"score": 80}}
    # Check realized_pnl is present (value depends on PnlAttribution logic, but key must exist)
    assert "realized_pnl" in context

    # Verify insert call
    insert_call = mock_supabase.table("learning_feedback_loops").insert.call_args
    assert insert_call is not None
    payload = insert_call[0][0] # first arg

    # Assertions on payload
    assert payload["user_id"] == user_id
    assert "details_json" in payload
    assert "post_trade_review" in payload["details_json"]

    review = payload["details_json"]["post_trade_review"]
    assert review["agent_id"] == "post_trade_review"
    assert review["metadata"]["review.outcome"] == "WIN"

    # v4-fix: Assert paper tagging is present in both top-level and details_json
    assert payload["is_paper"] is True
    assert payload["details_json"].get("is_paper") is True

@patch("packages.quantum.paper_endpoints.PostTradeReviewAgent")
def test_run_attribution_handles_missing_suggestion(MockPostTradeReviewAgent, mock_supabase):
    """
    Test fallback when suggestion is missing.
    """
    # Mock suggestion return None
    mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = None

    # Setup Mock Agent
    mock_agent_instance = MockPostTradeReviewAgent.return_value
    mock_agent_signal = MagicMock()
    mock_agent_signal.model_dump.return_value = {
        "agent_id": "post_trade_review",
        "score": 100.0,
        "metadata": {"review.outcome": "LOSS"}
    }
    mock_agent_instance.evaluate.return_value = mock_agent_signal

    user_id = str(uuid.uuid4())
    order = {
        "id": str(uuid.uuid4()),
        "filled_qty": 10,
        "trace_id": "trace-123",
        "suggestion_id": None,
        "quote_at_fill": {"bid_price": 0.9, "ask_price": 1.1}
    }
    position = {
        "avg_entry_price": 1.0,
        "strategy_key": "AAPL_iron_condor"
    }
    side = "sell"
    exit_fill = 0.8
    fees = 0.0

    with patch("packages.quantum.paper_endpoints.logging"):
        _run_attribution(mock_supabase, user_id, order, position, exit_fill, fees, side)

    insert_call = mock_supabase.table("learning_feedback_loops").insert.call_args
    payload = insert_call[0][0]

    assert "post_trade_review" in payload["details_json"]
    review = payload["details_json"]["post_trade_review"]
    assert review["metadata"]["review.outcome"] == "LOSS"

    # Verify context has empty agent_signals
    call_args = mock_agent_instance.evaluate.call_args
    context = call_args[0][0]
    assert context["agent_signals"] == {}

    # v4-fix: Assert paper tagging is present in both top-level and details_json
    assert payload["is_paper"] is True
    assert payload["details_json"].get("is_paper") is True
