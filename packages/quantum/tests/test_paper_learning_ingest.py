"""
Tests for paper_learning_ingest job handler.

Verifies:
1. Outcome records created from paper_ledger FILL entries
2. Idempotency via (user_id, order_id) deduplication
3. is_paper flag set to True on all outcomes
4. Correct PnL calculation based on side
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timedelta, timezone


class TestCreatePaperOutcomeRecord:
    """Tests for _create_paper_outcome_record helper."""

    def test_creates_outcome_with_trade_closed_type(self):
        """Outcome should have outcome_type='trade_closed' for view compatibility."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )

        order = {
            "id": "order-123",
            "portfolio_id": "port-1",
            "status": "filled",
            "side": "buy",
            "order_type": "limit",
            "filled_qty": 10,
            "avg_fill_price": 100.0,
            "requested_price": 99.0,
            "requested_qty": 10,
            "suggestion_id": "sugg-abc",
            "order_json": {"symbol": "SPY"},
        }

        result = _create_paper_outcome_record("user-1", order, "2025-01-15")

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

        order = {
            "id": "order-123",
            "status": "filled",
            "side": "sell",
            "filled_qty": 10,
            "avg_fill_price": 100.0,
            "requested_price": 100.0,
            "suggestion_id": "sugg-xyz-456",
            "order_json": {"symbol": "SPY"},
        }

        result = _create_paper_outcome_record("user-1", order, "2025-01-15")

        assert result["suggestion_id"] == "sugg-xyz-456"

    def test_win_pnl_for_sell_above_requested(self):
        """Selling above requested price should have positive PnL."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )

        order = {
            "id": "order-sell-win",
            "status": "filled",
            "side": "sell",
            "filled_qty": 10,
            "avg_fill_price": 105.0,  # Sold higher
            "requested_price": 100.0,
            "order_json": {"symbol": "SPY"},
        }

        result = _create_paper_outcome_record("user-1", order, "2025-01-15")

        # outcome_type is always 'trade_closed', pnl_outcome in details_json
        assert result["outcome_type"] == "trade_closed"
        assert result["pnl_realized"] == 50.0  # (105 - 100) * 10
        assert result["details_json"]["pnl_outcome"] == "win"

    def test_loss_pnl_for_sell_below_requested(self):
        """Selling below requested price should have negative PnL."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )

        order = {
            "id": "order-sell-loss",
            "status": "filled",
            "side": "sell",
            "filled_qty": 10,
            "avg_fill_price": 95.0,  # Sold lower
            "requested_price": 100.0,
            "order_json": {"symbol": "SPY"},
        }

        result = _create_paper_outcome_record("user-1", order, "2025-01-15")

        assert result["outcome_type"] == "trade_closed"
        assert result["pnl_realized"] == -50.0  # (95 - 100) * 10
        assert result["details_json"]["pnl_outcome"] == "loss"

    def test_win_pnl_for_buy_below_requested(self):
        """Buying below requested price should have positive PnL (saved money)."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )

        order = {
            "id": "order-buy-win",
            "status": "filled",
            "side": "buy",
            "filled_qty": 10,
            "avg_fill_price": 95.0,  # Bought lower
            "requested_price": 100.0,
            "order_json": {"symbol": "SPY"},
        }

        result = _create_paper_outcome_record("user-1", order, "2025-01-15")

        assert result["outcome_type"] == "trade_closed"
        assert result["pnl_realized"] == 50.0  # (100 - 95) * 10
        assert result["details_json"]["pnl_outcome"] == "win"

    def test_loss_pnl_for_buy_above_requested(self):
        """Buying above requested price should have negative PnL (slippage)."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )

        order = {
            "id": "order-buy-loss",
            "status": "filled",
            "side": "buy",
            "filled_qty": 10,
            "avg_fill_price": 105.0,  # Bought higher (slippage)
            "requested_price": 100.0,
            "order_json": {"symbol": "SPY"},
        }

        result = _create_paper_outcome_record("user-1", order, "2025-01-15")

        assert result["outcome_type"] == "trade_closed"
        assert result["pnl_realized"] == -50.0  # (100 - 105) * 10
        assert result["details_json"]["pnl_outcome"] == "loss"

    def test_breakeven_pnl(self):
        """Zero PnL should have pnl_outcome='breakeven' in details."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )

        order = {
            "id": "order-even",
            "status": "filled",
            "side": "buy",
            "filled_qty": 10,
            "avg_fill_price": 100.0,
            "requested_price": 100.0,
            "order_json": {"symbol": "SPY"},
        }

        result = _create_paper_outcome_record("user-1", order, "2025-01-15")

        assert result["outcome_type"] == "trade_closed"
        assert result["pnl_realized"] == 0.0
        assert result["details_json"]["pnl_outcome"] == "breakeven"

    def test_includes_tcm_metrics(self):
        """Should include TCM metrics in details_json."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )

        order = {
            "id": "order-tcm",
            "status": "filled",
            "side": "buy",
            "filled_qty": 10,
            "avg_fill_price": 99.50,
            "requested_price": 100.0,
            "order_json": {"symbol": "SPY"},
            "tcm": {
                "fill_probability": 0.85,
                "expected_fill_price": 99.75,
                "expected_slippage": -0.25,
            },
        }

        result = _create_paper_outcome_record("user-1", order, "2025-01-15")

        assert result["details_json"]["tcm_fill_probability"] == 0.85
        assert result["details_json"]["tcm_expected_fill_price"] == 99.75
        assert result["pnl_predicted"] == -0.25

    def test_includes_trace_id(self):
        """Should include trace_id from order."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )

        order = {
            "id": "order-trace",
            "status": "filled",
            "side": "buy",
            "filled_qty": 10,
            "avg_fill_price": 100.0,
            "requested_price": 100.0,
            "trace_id": "trace-abc-123",
            "order_json": {"symbol": "SPY"},
        }

        result = _create_paper_outcome_record("user-1", order, "2025-01-15")

        assert result["trace_id"] == "trace-abc-123"

    def test_includes_date_bucket_in_details(self):
        """Should include date_bucket in details_json."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )

        order = {
            "id": "order-date",
            "status": "filled",
            "side": "buy",
            "filled_qty": 10,
            "avg_fill_price": 100.0,
            "requested_price": 100.0,
            "order_json": {"symbol": "SPY"},
        }

        result = _create_paper_outcome_record("user-1", order, "2025-01-15")

        assert result["details_json"]["date_bucket"] == "2025-01-15"

    def test_includes_reason_codes(self):
        """Should include reason_codes in details_json."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _create_paper_outcome_record
        )

        order = {
            "id": "order-reason",
            "status": "filled",
            "side": "sell",
            "filled_qty": 10,
            "avg_fill_price": 100.0,
            "requested_price": 100.0,
            "order_json": {"symbol": "SPY"},
        }

        result = _create_paper_outcome_record("user-1", order, "2025-01-15")

        assert "reason_codes" in result["details_json"]
        assert "paper_trade_close" in result["details_json"]["reason_codes"]
        assert result["details_json"]["is_paper"] is True


class TestIngestPaperOutcomesForUser:
    """Tests for _ingest_paper_outcomes_for_user."""

    @pytest.mark.asyncio
    async def test_skips_existing_outcomes(self):
        """Should skip orders that already have outcomes (idempotency)."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _ingest_paper_outcomes_for_user
        )

        mock_supabase = MagicMock()

        # Mock ledger entries
        mock_supabase.table.return_value.select.return_value.eq.return_value.in_.return_value.gte.return_value.execute.return_value = MagicMock(
            data=[
                {"id": "ledger-1", "order_id": "order-existing", "event_type": "FILL"},
                {"id": "ledger-2", "order_id": "order-new", "event_type": "FILL"},
            ]
        )

        def table_side_effect(table_name):
            mock_table = MagicMock()
            if table_name == "paper_ledger":
                mock_table.select.return_value.eq.return_value.in_.return_value.gte.return_value.execute.return_value = MagicMock(
                    data=[
                        {"id": "ledger-1", "order_id": "order-existing", "event_type": "FILL"},
                        {"id": "ledger-2", "order_id": "order-new", "event_type": "FILL"},
                    ]
                )
            elif table_name == "paper_orders":
                mock_table.select.return_value.in_.return_value.execute.return_value = MagicMock(
                    data=[
                        {
                            "id": "order-existing",
                            "status": "filled",
                            "side": "buy",
                            "filled_qty": 10,
                            "avg_fill_price": 100.0,
                            "requested_price": 100.0,
                            "order_json": {"symbol": "SPY"},
                        },
                        {
                            "id": "order-new",
                            "status": "filled",
                            "side": "buy",
                            "filled_qty": 5,
                            "avg_fill_price": 50.0,
                            "requested_price": 50.0,
                            "order_json": {"symbol": "AAPL"},
                        },
                    ]
                )
            elif table_name == "learning_feedback_loops":
                # First call: check existing
                if hasattr(mock_table, '_select_called'):
                    # Insert call
                    mock_table.insert.return_value.execute.return_value = MagicMock()
                else:
                    # Select call - order-existing already has outcome
                    mock_table.select.return_value.eq.return_value.in_.return_value.execute.return_value = MagicMock(
                        data=[{"source_event_id": "order-existing"}]
                    )
                    mock_table._select_called = True
            return mock_table

        mock_supabase.table.side_effect = table_side_effect

        result = await _ingest_paper_outcomes_for_user(
            "user-1", mock_supabase, 7, "2025-01-15"
        )

        assert result["ledger_entries"] == 2
        assert result["skipped_duplicate"] == 1
        assert result["outcomes_created"] == 1

    @pytest.mark.asyncio
    async def test_returns_zero_counts_when_no_ledger_entries(self):
        """Should return zero counts when no ledger entries found."""
        from packages.quantum.jobs.handlers.paper_learning_ingest import (
            _ingest_paper_outcomes_for_user
        )

        mock_supabase = MagicMock()
        mock_supabase.table.return_value.select.return_value.eq.return_value.in_.return_value.gte.return_value.execute.return_value = MagicMock(
            data=[]
        )

        result = await _ingest_paper_outcomes_for_user(
            "user-1", mock_supabase, 7, "2025-01-15"
        )

        assert result["ledger_entries"] == 0
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
            assert result["counts"]["ledger_entries_found"] == 5
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
        with open(path, "r") as f:
            source = f.read()

        assert '"paper_learning_ingest"' in source
        assert '"/tasks/paper/learning-ingest"' in source
        assert '"tasks:paper_learning_ingest"' in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
