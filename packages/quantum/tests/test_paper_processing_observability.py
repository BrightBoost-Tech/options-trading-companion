"""
Tests for paper processing observability improvements.

Verifies:
1. paper_autopilot_service captures _process_orders_for_user return value
2. processed_summary is included in execute_top_suggestions/close_positions responses
3. Status is "partial" when processing errors exist
4. Structured logging in _process_orders_for_user
5. New /tasks/paper/process-orders endpoint
"""

import pytest
from unittest.mock import MagicMock, patch
import logging

from packages.quantum.services.paper_autopilot_service import PaperAutopilotService


class TestExecuteTopSuggestionsProcessedSummary:
    """Tests for processed_summary in execute_top_suggestions."""

    def test_returns_processed_summary_on_success(self):
        """Should include processed_summary with total_processed and processing_error_count."""
        mock_client = MagicMock()

        # Setup suggestion query
        mock_query = MagicMock()
        mock_client.table.return_value = mock_query
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.gte.return_value = mock_query
        mock_query.lt.return_value = mock_query
        mock_query.in_.return_value = mock_query

        # Suggestions query returns one suggestion
        suggestions_result = MagicMock(data=[
            {"id": "s1", "score": 60.0, "created_at": "2024-01-01T10:00:00Z"}
        ])

        # Paper orders query returns empty (no already executed)
        orders_result = MagicMock(data=[])

        def table_side_effect(table_name):
            mock_q = MagicMock()
            mock_q.select.return_value = mock_q
            mock_q.eq.return_value = mock_q
            mock_q.gte.return_value = mock_q
            mock_q.lt.return_value = mock_q
            mock_q.update.return_value = mock_q

            if table_name == "trade_suggestions":
                mock_q.execute.return_value = suggestions_result
            elif table_name == "paper_orders":
                mock_q.execute.return_value = orders_result
            else:
                mock_q.execute.return_value = MagicMock(data=[])
            return mock_q

        mock_client.table.side_effect = table_side_effect

        with patch.dict("os.environ", {"PAPER_AUTOPILOT_ENABLED": "1"}):
            service = PaperAutopilotService(mock_client)

            # Mock the internal functions to simulate successful execution
            with patch("packages.quantum.services.paper_autopilot_service._suggestion_to_ticket") as mock_ticket, \
                 patch("packages.quantum.services.paper_autopilot_service._stage_order_internal") as mock_stage, \
                 patch("packages.quantum.services.paper_autopilot_service._process_orders_for_user") as mock_process:

                mock_ticket.return_value = MagicMock()
                mock_stage.return_value = "order-123"
                mock_process.return_value = {"processed": 1, "errors": [], "total_orders": 1}

                result = service.execute_top_suggestions(user_id="test-user")

        # Verify processed_summary is present
        assert "processed_summary" in result
        assert result["processed_summary"]["total_processed"] == 1
        assert result["processed_summary"]["processing_error_count"] == 0
        assert result["status"] == "ok"

    def test_status_partial_when_processing_errors(self):
        """Should set status='partial' when processing errors exist."""
        mock_client = MagicMock()

        # Setup suggestion query
        mock_query = MagicMock()
        mock_client.table.return_value = mock_query
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.gte.return_value = mock_query
        mock_query.lt.return_value = mock_query
        mock_query.in_.return_value = mock_query

        # Suggestions query returns one suggestion
        suggestions_result = MagicMock(data=[
            {"id": "s1", "score": 60.0, "created_at": "2024-01-01T10:00:00Z"}
        ])

        # Paper orders query returns empty
        orders_result = MagicMock(data=[])

        def table_side_effect(table_name):
            mock_q = MagicMock()
            mock_q.select.return_value = mock_q
            mock_q.eq.return_value = mock_q
            mock_q.gte.return_value = mock_q
            mock_q.lt.return_value = mock_q
            mock_q.update.return_value = mock_q

            if table_name == "trade_suggestions":
                mock_q.execute.return_value = suggestions_result
            elif table_name == "paper_orders":
                mock_q.execute.return_value = orders_result
            else:
                mock_q.execute.return_value = MagicMock(data=[])
            return mock_q

        mock_client.table.side_effect = table_side_effect

        with patch.dict("os.environ", {"PAPER_AUTOPILOT_ENABLED": "1"}):
            service = PaperAutopilotService(mock_client)

            # Mock processing to return errors
            with patch("packages.quantum.services.paper_autopilot_service._suggestion_to_ticket") as mock_ticket, \
                 patch("packages.quantum.services.paper_autopilot_service._stage_order_internal") as mock_stage, \
                 patch("packages.quantum.services.paper_autopilot_service._process_orders_for_user") as mock_process:

                mock_ticket.return_value = MagicMock()
                mock_stage.return_value = "order-123"
                # Processing had an error
                mock_process.return_value = {
                    "processed": 0,
                    "errors": [{"order_id": "order-123", "error": "Quote unavailable"}],
                    "total_orders": 1
                }

                result = service.execute_top_suggestions(user_id="test-user")

        # Verify status is partial due to processing errors
        assert result["status"] == "partial"
        assert result["processed_summary"]["processing_error_count"] == 1


class TestClosePositionsProcessedSummary:
    """Tests for processed_summary in close_positions."""

    def test_close_positions_returns_processed_summary(self):
        """Should include processed_summary in close_positions response."""
        mock_client = MagicMock()

        # Setup queries
        mock_query = MagicMock()
        mock_client.table.return_value = mock_query
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.gte.return_value = mock_query
        mock_query.lt.return_value = mock_query
        mock_query.in_.return_value = mock_query

        # Portfolio query
        portfolios_result = MagicMock(data=[{"id": "port-1"}])

        # Positions query
        positions_result = MagicMock(data=[
            {"id": "pos-1", "symbol": "SPY", "quantity": 10, "portfolio_id": "port-1", "created_at": "2024-01-01"}
        ])

        # Learning feedback (positions closed today)
        feedback_result = MagicMock(data=[], count=0)

        def table_side_effect(table_name):
            mock_q = MagicMock()
            mock_q.select.return_value = mock_q
            mock_q.eq.return_value = mock_q
            mock_q.gte.return_value = mock_q
            mock_q.lt.return_value = mock_q
            mock_q.in_.return_value = mock_q

            if table_name == "paper_portfolios":
                mock_q.execute.return_value = portfolios_result
            elif table_name == "paper_positions":
                mock_q.execute.return_value = positions_result
            elif table_name == "learning_feedback_loops":
                mock_q.execute.return_value = feedback_result
            else:
                mock_q.execute.return_value = MagicMock(data=[])
            return mock_q

        mock_client.table.side_effect = table_side_effect

        with patch.dict("os.environ", {"PAPER_AUTOPILOT_ENABLED": "1"}):
            service = PaperAutopilotService(mock_client)

            # Mock close operations
            with patch("packages.quantum.services.paper_autopilot_service._stage_order_internal") as mock_stage, \
                 patch("packages.quantum.services.paper_autopilot_service._process_orders_for_user") as mock_process:

                mock_stage.return_value = "order-123"
                mock_process.return_value = {"processed": 1, "errors": [], "total_orders": 1}

                result = service.close_positions(user_id="test-user")

        # Verify processed_summary is present
        assert "processed_summary" in result
        assert result["processed_summary"]["total_processed"] == 1
        assert result["processed_summary"]["processing_error_count"] == 0


class TestExecutedItemStructure:
    """Tests for executed item structure with processing info."""

    def test_executed_item_includes_processing_info(self):
        """Each executed item should include processed count and processing_errors."""
        mock_client = MagicMock()

        # Setup
        mock_query = MagicMock()
        mock_client.table.return_value = mock_query
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.gte.return_value = mock_query
        mock_query.lt.return_value = mock_query
        mock_query.update.return_value = mock_query

        suggestions_result = MagicMock(data=[
            {"id": "s1", "score": 60.0, "created_at": "2024-01-01T10:00:00Z"}
        ])
        orders_result = MagicMock(data=[])

        def table_side_effect(table_name):
            mock_q = MagicMock()
            mock_q.select.return_value = mock_q
            mock_q.eq.return_value = mock_q
            mock_q.gte.return_value = mock_q
            mock_q.lt.return_value = mock_q
            mock_q.update.return_value = mock_q

            if table_name == "trade_suggestions":
                mock_q.execute.return_value = suggestions_result
            elif table_name == "paper_orders":
                mock_q.execute.return_value = orders_result
            else:
                mock_q.execute.return_value = MagicMock(data=[])
            return mock_q

        mock_client.table.side_effect = table_side_effect

        with patch.dict("os.environ", {"PAPER_AUTOPILOT_ENABLED": "1"}):
            service = PaperAutopilotService(mock_client)

            with patch("packages.quantum.services.paper_autopilot_service._suggestion_to_ticket") as mock_ticket, \
                 patch("packages.quantum.services.paper_autopilot_service._stage_order_internal") as mock_stage, \
                 patch("packages.quantum.services.paper_autopilot_service._process_orders_for_user") as mock_process:

                mock_ticket.return_value = MagicMock()
                mock_stage.return_value = "order-123"
                mock_process.return_value = {"processed": 1, "errors": [], "total_orders": 1}

                result = service.execute_top_suggestions(user_id="test-user")

        # Verify executed item structure
        assert len(result["executed"]) == 1
        executed_item = result["executed"][0]
        assert "suggestion_id" in executed_item
        assert "order_id" in executed_item
        assert "processed" in executed_item
        assert "processing_errors" in executed_item
        assert executed_item["processed"] == 1
        assert executed_item["processing_errors"] is None


class TestStructuredLoggingInProcessOrders:
    """Tests for structured logging in _process_orders_for_user."""

    def test_source_contains_structured_log_statements(self):
        """Verify paper_endpoints has structured logging in _process_orders_for_user."""
        import os
        paper_endpoints_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "paper_endpoints.py"
        )

        with open(paper_endpoints_path, "r") as f:
            source = f.read()

        # Verify structured log statements are present
        assert "paper_order_process:" in source, "Missing paper_order_process structured log"
        assert "paper_order_filled:" in source, "Missing paper_order_filled structured log"
        assert "paper_order_transition:" in source, "Missing paper_order_transition structured log"
        assert "paper_order_error:" in source, "Missing paper_order_error structured log"

    def test_log_includes_key_observability_fields(self):
        """Verify structured log includes order_id, prior_status, fill_status, etc."""
        import os
        paper_endpoints_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "paper_endpoints.py"
        )

        with open(paper_endpoints_path, "r") as f:
            source = f.read()

        # Check for key fields in the structured log
        assert "order_id=" in source
        assert "prior_status=" in source
        assert "fill_status=" in source
        assert "quote_present=" in source
        assert "last_fill_qty=" in source


class TestPaperProcessOrdersEndpoint:
    """Tests for /tasks/paper/process-orders endpoint."""

    def test_endpoint_exists_in_public_tasks(self):
        """Verify the endpoint is defined in public_tasks.py."""
        import os
        public_tasks_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "public_tasks.py"
        )

        with open(public_tasks_path, "r") as f:
            source = f.read()

        assert '/paper/process-orders' in source
        assert 'task_paper_process_orders' in source
        assert 'tasks:paper_process_orders' in source

    def test_payload_model_exists(self):
        """Verify PaperProcessOrdersPayload model exists."""
        from packages.quantum.public_tasks_models import PaperProcessOrdersPayload

        # Should be importable
        assert PaperProcessOrdersPayload is not None

        # Should require user_id
        import pytest
        with pytest.raises(Exception):
            PaperProcessOrdersPayload()  # Missing required user_id

    def test_task_scope_is_registered(self):
        """Verify the task scope is registered in TASK_SCOPES."""
        from packages.quantum.public_tasks_models import TASK_SCOPES

        assert "/tasks/paper/process-orders" in TASK_SCOPES
        assert TASK_SCOPES["/tasks/paper/process-orders"] == "tasks:paper_process_orders"


class TestRunSignedTaskMapping:
    """Tests for run_signed_task.py task mapping."""

    def test_paper_process_orders_in_task_mapping(self):
        """Verify paper_process_orders is in the TASKS dict."""
        import os
        script_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "..",
            "scripts",
            "run_signed_task.py"
        )

        with open(script_path, "r") as f:
            source = f.read()

        assert '"paper_process_orders"' in source
        assert '"/tasks/paper/process-orders"' in source
        assert '"tasks:paper_process_orders"' in source
        assert '"user_id_mode": "require"' in source


class TestWorkflowDispatchOption:
    """Tests for workflow_dispatch option."""

    def test_paper_process_orders_in_workflow_dispatch(self):
        """Verify paper_process_orders is in workflow_dispatch options."""
        import os
        workflow_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "..",
            ".github",
            "workflows",
            "trading_tasks.yml"
        )

        with open(workflow_path, "r") as f:
            source = f.read()

        assert "paper_process_orders" in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
