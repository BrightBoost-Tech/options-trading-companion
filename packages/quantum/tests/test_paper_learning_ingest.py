"""
Tests for paper_learning_ingest job handler.

Verifies:
1. Outcome records created with outcome_type='trade_closed' for view compatibility
2. Idempotency via (user_id, order_id) deduplication
3. is_paper flag set to True on all outcomes
4. pnl_realized sourced from paper_positions.realized_pl
5. pnl_predicted sourced from suggestion EV (matching live ingest semantics)
6. details_json.pnl_outcome correctly classifies win/loss/breakeven
7. Execution drag (TCM slippage) stored in details_json.expected_slippage, not pnl_predicted
8. Structured logger used instead of debug prints
"""

import logging
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timedelta, timezone


# Shared fixtures for position-based tests
_SAMPLE_ORDER = {
    "id": "order-123",
    "portfolio_id": "port-1",
    "status": "filled",
    "side": "sell",
    "order_type": "limit",
    "filled_qty": 10,
    "avg_fill_price": 1.50,
    "requested_price": 1.55,
    "requested_qty": 10,
    "suggestion_id": "sugg-abc",
    "order_json": {"symbol": "SPY"},
}

_SAMPLE_POSITION = {
    "id": "pos-1",
    "realized_pl": 500.0,
    "status": "closed",
    "closed_at": "2025-01-15T16:00:00+00:00",
}


class TestCreatePaperOutcomeRecord:
    """Tests for _create_paper_outcome_record helper."""

    def test_creates_outcome_with_trade_closed_type(self):
        """Outcome should have outcome_type='trade_closed' for view compatibility."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )

        result = _create_paper_outcome_record(
            "user-1", _SAMPLE_ORDER, "2025-01-15", _SAMPLE_POSITION
        )

        # CRITICAL: Must be 'trade_closed' for learning_trade_outcomes_v3 view
        assert result["outcome_type"] == "trade_closed"
        assert result["is_paper"] is True
        assert result["user_id"] == "user-1"
        assert result["source_event_id"] == "order-123"

    def test_includes_suggestion_id_for_view_join(self):
        """Outcome should include suggestion_id for view join to trade_suggestions."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )

        result = _create_paper_outcome_record(
            "user-1", _SAMPLE_ORDER, "2025-01-15", _SAMPLE_POSITION
        )

        assert result["suggestion_id"] == "sugg-abc"

    def test_pnl_from_position_realized_pl(self):
        """pnl_realized should come from paper_positions.realized_pl, not slippage."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )

        position = {**_SAMPLE_POSITION, "realized_pl": 1234.56}
        result = _create_paper_outcome_record(
            "user-1", _SAMPLE_ORDER, "2025-01-15", position
        )

        assert result["pnl_realized"] == 1234.56
        assert result["details_json"]["pnl_outcome"] == "win"

    def test_negative_pnl_from_position(self):
        """Negative realized_pl should produce loss outcome."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )

        position = {**_SAMPLE_POSITION, "realized_pl": -300.0}
        result = _create_paper_outcome_record(
            "user-1", _SAMPLE_ORDER, "2025-01-15", position
        )

        assert result["pnl_realized"] == -300.0
        assert result["details_json"]["pnl_outcome"] == "loss"

    def test_zero_pnl_breakeven(self):
        """Zero realized_pl should produce breakeven outcome."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )

        position = {**_SAMPLE_POSITION, "realized_pl": 0.0}
        result = _create_paper_outcome_record(
            "user-1", _SAMPLE_ORDER, "2025-01-15", position
        )

        assert result["pnl_realized"] == 0.0
        assert result["details_json"]["pnl_outcome"] == "breakeven"

    def test_null_realized_pl_defaults_to_zero(self):
        """Missing realized_pl on position should default to 0."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )

        position = {**_SAMPLE_POSITION, "realized_pl": None}
        result = _create_paper_outcome_record(
            "user-1", _SAMPLE_ORDER, "2025-01-15", position
        )

        assert result["pnl_realized"] == 0.0

    def test_updated_at_uses_position_closed_at(self):
        """updated_at should use position's closed_at for correct view timestamps."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )

        result = _create_paper_outcome_record(
            "user-1", _SAMPLE_ORDER, "2025-01-15", _SAMPLE_POSITION
        )

        assert result["updated_at"] == "2025-01-15T16:00:00+00:00"

    def test_pnl_predicted_uses_suggestion_ev(self):
        """pnl_predicted should come from suggestion EV, matching live ingest."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )

        result = _create_paper_outcome_record(
            "user-1", _SAMPLE_ORDER, "2025-01-15", _SAMPLE_POSITION,
            suggestion_ev=42.50,
        )

        assert result["pnl_predicted"] == 42.50

    def test_pnl_predicted_none_when_no_suggestion_ev(self):
        """pnl_predicted should be None when no suggestion EV is available."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )

        result = _create_paper_outcome_record(
            "user-1", _SAMPLE_ORDER, "2025-01-15", _SAMPLE_POSITION,
        )

        assert result["pnl_predicted"] is None

    def test_slippage_not_in_pnl_predicted(self):
        """TCM expected_slippage must NOT end up in pnl_predicted."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )

        order = {
            **_SAMPLE_ORDER,
            "id": "order-slip",
            "tcm": {
                "fill_probability": 0.85,
                "expected_fill_price": 99.75,
                "expected_slippage": -0.25,
            },
        }

        # No suggestion_ev provided — pnl_predicted must NOT fall back to slippage
        result = _create_paper_outcome_record(
            "user-1", order, "2025-01-15", _SAMPLE_POSITION,
        )

        assert result["pnl_predicted"] is None
        assert result["pnl_predicted"] != -0.25

    def test_slippage_stored_in_details_json(self):
        """TCM expected_slippage should be in details_json.expected_slippage."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )

        order = {
            **_SAMPLE_ORDER,
            "id": "order-drag",
            "tcm": {
                "fill_probability": 0.85,
                "expected_fill_price": 99.75,
                "expected_slippage": -0.25,
            },
        }

        result = _create_paper_outcome_record(
            "user-1", order, "2025-01-15", _SAMPLE_POSITION,
            suggestion_ev=42.50,
        )

        # pnl_predicted is suggestion EV, not slippage
        assert result["pnl_predicted"] == 42.50
        # Slippage preserved in details_json
        assert result["details_json"]["expected_slippage"] == -0.25
        assert result["details_json"]["tcm_fill_probability"] == 0.85
        assert result["details_json"]["tcm_expected_fill_price"] == 99.75

    def test_includes_trace_id(self):
        """Should include trace_id from order."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )

        order = {**_SAMPLE_ORDER, "id": "order-trace", "trace_id": "trace-abc-123"}
        result = _create_paper_outcome_record(
            "user-1", order, "2025-01-15", _SAMPLE_POSITION
        )

        assert result["trace_id"] == "trace-abc-123"

    def test_includes_date_bucket_in_details(self):
        """Should include date_bucket in details_json."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )

        result = _create_paper_outcome_record(
            "user-1", _SAMPLE_ORDER, "2025-01-15", _SAMPLE_POSITION
        )

        assert result["details_json"]["date_bucket"] == "2025-01-15"

    def test_includes_reason_codes(self):
        """Should include reason_codes in details_json."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )

        result = _create_paper_outcome_record(
            "user-1", _SAMPLE_ORDER, "2025-01-15", _SAMPLE_POSITION
        )

        assert "reason_codes" in result["details_json"]
        assert "paper_trade_close" in result["details_json"]["reason_codes"]
        assert result["details_json"]["is_paper"] is True


class TestPnlPredictedSemantics:
    """Verify pnl_predicted matches live semantics."""

    def test_pnl_predicted_is_null_not_slippage(self):
        """pnl_predicted should be None, not expected_slippage."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )
        order = {**_SAMPLE_ORDER, "tcm": {"expected_slippage": 0.05, "fill_probability": 0.9, "expected_fill_price": 1.48}}
        result = _create_paper_outcome_record("user-1", order, "2025-01-15", _SAMPLE_POSITION)
        assert result["pnl_predicted"] is None

    def test_expected_slippage_in_details_json(self):
        """Expected slippage should be in details_json, not pnl_predicted."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )
        order = {**_SAMPLE_ORDER, "tcm": {"expected_slippage": 0.05}}
        result = _create_paper_outcome_record("user-1", order, "2025-01-15", _SAMPLE_POSITION)
        assert result["details_json"]["expected_slippage"] == 0.05


class TestNoDebugPrints:
    """Verify debug prints have been removed."""

    def test_no_ingest_debug_prints(self):
        """No [INGEST_DEBUG] print statements should remain."""
        import inspect
        from packages.quantum.jobs.handlers import paper_learning_ingest
        source = inspect.getsource(paper_learning_ingest)
        assert "INGEST_DEBUG" not in source
        assert 'print(f"[' not in source or "INGEST_DEBUG" not in source


class TestIngestPaperOutcomesForUser:
    """Tests for _ingest_paper_outcomes_for_user."""

    @pytest.mark.asyncio
    async def test_skips_existing_outcomes(self):
        """Should skip positions whose closing orders already have outcomes."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _ingest_paper_outcomes_for_user
        )

        mock_supabase = MagicMock()

        def table_side_effect(table_name):
            mock_table = MagicMock()
            if table_name == "paper_positions":
                # Step 1: query closed positions
                mock_table.select.return_value.eq.return_value.eq.return_value.gte.return_value.execute.return_value = MagicMock(
                    data=[
                        {"id": "pos-1", "realized_pl": 500.0, "status": "closed",
                         "closed_at": "2025-01-15T16:00:00+00:00",
                         "suggestion_id": "sugg-1", "trace_id": "t-1", "symbol": "SPY"},
                        {"id": "pos-2", "realized_pl": 250.0, "status": "closed",
                         "closed_at": "2025-01-15T16:00:00+00:00",
                         "suggestion_id": "sugg-2", "trace_id": "t-2", "symbol": "AAPL"},
                    ]
                )
            elif table_name == "paper_orders":
                # Step 2: query closing orders
                mock_table.select.return_value.in_.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[
                        {"id": "order-existing", "status": "filled", "side": "sell",
                         "filled_qty": 10, "avg_fill_price": 1.50, "requested_price": 1.55,
                         "position_id": "pos-1", "order_json": {"symbol": "SPY"},
                         "suggestion_id": "sugg-1",
                         "filled_at": "2025-01-15T16:00:00+00:00"},
                        {"id": "order-new", "status": "filled", "side": "sell",
                         "filled_qty": 5, "avg_fill_price": 0.80, "requested_price": 0.85,
                         "position_id": "pos-2", "order_json": {"symbol": "AAPL"},
                         "suggestion_id": "sugg-2",
                         "filled_at": "2025-01-15T16:00:00+00:00"},
                    ]
                )
            elif table_name == "trade_suggestions":
                # Step 2b: fetch suggestion EVs
                mock_table.select.return_value.in_.return_value.execute.return_value = MagicMock(
                    data=[
                        {"id": "sugg-1", "ev": 15.0},
                        {"id": "sugg-2", "ev": 8.5},
                    ]
                )
            elif table_name == "learning_feedback_loops":
                if hasattr(mock_table, '_select_called'):
                    mock_table.insert.return_value.execute.return_value = MagicMock()
                else:
                    mock_table.select.return_value.eq.return_value.in_.return_value.execute.return_value = MagicMock(
                        data=[{"source_event_id": "order-existing"}]
                    )
                    mock_table._select_called = True
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        result = await _ingest_paper_outcomes_for_user(
            "user-1", mock_supabase, 7, "2025-01-15"
        )

        assert result["closed_positions"] == 2
        assert result["skipped_duplicate"] == 1
        assert result["outcomes_created"] == 1

    @pytest.mark.asyncio
    async def test_returns_zero_counts_when_no_closed_positions(self):
        """Should return zero counts when no closed positions found."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _ingest_paper_outcomes_for_user
        )

        mock_supabase = MagicMock()
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.execute.return_value = MagicMock(
            data=[]
        )

        result = await _ingest_paper_outcomes_for_user(
            "user-1", mock_supabase, 7, "2025-01-15"
        )

        assert result["closed_positions"] == 0
        assert result["outcomes_created"] == 0
        assert result["skipped_duplicate"] == 0


class TestRunJobHandler:
    """Tests for the main run() function."""

    def test_run_returns_ok_with_counts(self):
        """run() should return ok status with counts."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import run

        with patch("packages.quantum.jobs.handlers.paper_learning_ingest.get_admin_client") as mock_client, \
             patch("packages.quantum.jobs.handlers.paper_learning_ingest.get_active_user_ids") as mock_users, \
             patch("packages.quantum.jobs.handlers.paper_learning_ingest.run_async") as mock_run_async:

            mock_client.return_value = MagicMock()
            mock_users.return_value = ["user-1"]
            mock_run_async.return_value = (1, 5, 3, 2, 0)  # users, entries, outcomes, skipped, errors

            result = run({"date": "2025-01-15", "lookback_days": 7})

            assert result["ok"] is True
            assert result["counts"]["users_processed"] == 1
            assert result["counts"]["closed_positions_found"] == 5
            assert result["counts"]["outcomes_created"] == 3
            assert result["counts"]["outcomes_skipped_duplicate"] == 2
            assert result["lookback_days"] == 7

    def test_run_handles_single_user(self):
        """run() should process single user when user_id provided."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import run

        with patch("packages.quantum.jobs.handlers.paper_learning_ingest.get_admin_client") as mock_client, \
             patch("packages.quantum.jobs.handlers.paper_learning_ingest.get_active_user_ids") as mock_users, \
             patch("packages.quantum.jobs.handlers.paper_learning_ingest.run_async") as mock_run_async:

            mock_client.return_value = MagicMock()
            mock_run_async.return_value = (1, 2, 1, 1, 0)

            result = run({
                "date": "2025-01-15",
                "user_id": "specific-user-uuid",
                "lookback_days": 3,
            })

            # Should not call get_active_user_ids when user_id is provided
            mock_users.assert_not_called()
            assert result["ok"] is True


class TestLoggerUsage:
    """Verify structured logging replaced debug prints."""

    def test_no_print_statements_in_source(self):
        """Source should not contain [INGEST_DEBUG] print statements."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "jobs",
            "handlers",
            "paper_learning_ingest.py"
        )
        with open(path, "r") as f:
            source = f.read()

        assert "[INGEST_DEBUG]" not in source
        assert "print(f\"[INGEST_DEBUG]" not in source

    def test_logger_is_configured(self):
        """Module should use logging.getLogger(__name__)."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "jobs",
            "handlers",
            "paper_learning_ingest.py"
        )
        with open(path, "r") as f:
            source = f.read()

        assert "import logging" in source
        assert "logger = logging.getLogger(__name__)" in source


class TestSourceCodeVerification:
    """Verify source code structure."""

    def test_job_handler_exists(self):
        """Verify paper_learning_ingest handler exists and has run function."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "jobs",
            "handlers",
            "paper_learning_ingest.py"
        )
        with open(path, "r") as f:
            source = f.read()

        assert "def run(payload:" in source
        assert "JOB_NAME = \"paper_learning_ingest\"" in source
        assert "is_paper" in source
        assert "_create_paper_outcome_record" in source

    def test_outcome_type_is_trade_closed(self):
        """Verify outcome_type='trade_closed' for view compatibility."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "jobs",
            "handlers",
            "paper_learning_ingest.py"
        )
        with open(path, "r") as f:
            source = f.read()

        # CRITICAL: Must use 'trade_closed' for learning_trade_outcomes_v3 view
        assert '"outcome_type": "trade_closed"' in source
        assert "learning_trade_outcomes_v3" in source  # Should document this

    def test_suggestion_id_included(self):
        """Verify suggestion_id is included for view join."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "jobs",
            "handlers",
            "paper_learning_ingest.py"
        )
        with open(path, "r") as f:
            source = f.read()

        assert '"suggestion_id": suggestion_id' in source
        assert 'suggestion_id = order.get("suggestion_id")' in source

    def test_is_paper_flag_set(self):
        """Verify is_paper=True is set in outcome records."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "jobs",
            "handlers",
            "paper_learning_ingest.py"
        )
        with open(path, "r") as f:
            source = f.read()

        assert '"is_paper": True' in source

    def test_endpoint_exists_in_public_tasks(self):
        """Verify endpoint is registered in public_tasks.py."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "public_tasks.py"
        )
        with open(path, "r") as f:
            source = f.read()

        assert "/paper/learning-ingest" in source
        assert "paper_learning_ingest" in source
        assert "PaperLearningIngestPayload" in source

    def test_payload_model_exists(self):
        """Verify payload model exists in public_tasks_models.py."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "public_tasks_models.py"
        )
        with open(path, "r") as f:
            source = f.read()

        assert "class PaperLearningIngestPayload" in source
        assert "lookback_days" in source

    def test_scope_mapping_exists(self):
        """Verify scope mapping exists in TASK_SCOPES."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "public_tasks_models.py"
        )
        with open(path, "r") as f:
            source = f.read()

        assert '"/tasks/paper/learning-ingest": "tasks:paper_learning_ingest"' in source

    def test_github_actions_dropdown_updated(self):
        """Verify paper_learning_ingest is in GitHub Actions dropdown."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "..",
            ".github",
            "workflows",
            "trading_tasks.yml"
        )
        with open(path, "r") as f:
            source = f.read()

        assert "paper_learning_ingest" in source

    def test_run_signed_task_has_paper_learning_ingest(self):
        """Verify paper_learning_ingest is registered in run_signed_task.py."""
        import os
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "..",
            "scripts",
            "run_signed_task.py"
        )
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()

        assert '"paper_learning_ingest"' in source
        assert '"/tasks/paper/learning-ingest"' in source
        assert '"tasks:paper_learning_ingest"' in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
