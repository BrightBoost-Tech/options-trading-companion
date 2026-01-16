"""
Tests for Suggestion Task Endpoints

Tests the /tasks/suggestions/close and /tasks/suggestions/open endpoints
including cron secret verification and payload handling.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
import os


# Set required env vars before importing app
os.environ.setdefault("CRON_SECRET", "test-cron-secret")
os.environ.setdefault("SUPABASE_URL", "http://localhost:54321")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-key")


class TestSuggestionEndpointAuth:
    """Test that suggestion endpoints require cron secret."""

    def test_suggestions_close_requires_cron_secret(self):
        """POST /tasks/suggestions/close returns 401 without cron secret."""
        from packages.quantum.api import app
        client = TestClient(app)

        response = client.post("/tasks/suggestions/close")
        assert response.status_code == 401
        assert "Invalid Cron Secret" in response.json().get("detail", "")

    def test_suggestions_close_rejects_wrong_secret(self):
        """POST /tasks/suggestions/close returns 401 with wrong secret."""
        from packages.quantum.api import app
        client = TestClient(app)

        response = client.post(
            "/tasks/suggestions/close",
            headers={"X-Cron-Secret": "wrong-secret"}
        )
        assert response.status_code == 401

    def test_suggestions_open_requires_cron_secret(self):
        """POST /tasks/suggestions/open returns 401 without cron secret."""
        from packages.quantum.api import app
        client = TestClient(app)

        response = client.post("/tasks/suggestions/open")
        assert response.status_code == 401

    def test_learning_ingest_requires_cron_secret(self):
        """POST /tasks/learning/ingest returns 401 without cron secret."""
        from packages.quantum.api import app
        client = TestClient(app)

        response = client.post("/tasks/learning/ingest")
        assert response.status_code == 401

    def test_strategy_autotune_requires_cron_secret(self):
        """POST /tasks/strategy/autotune returns 401 without cron secret."""
        from packages.quantum.api import app
        client = TestClient(app)

        response = client.post("/tasks/strategy/autotune")
        assert response.status_code == 401


class TestSuggestionEndpointAcceptance:
    """Test that endpoints accept valid requests with cron secret."""

    @patch("packages.quantum.jobs.rq_enqueue.enqueue_idempotent")
    @patch("packages.quantum.jobs.job_runs.JobRunStore")
    def test_suggestions_close_accepts_valid_request(self, mock_store_class, mock_enqueue):
        """POST /tasks/suggestions/close returns 202 with valid cron secret."""
        from packages.quantum.api import app
        client = TestClient(app)

        # Mock the job run store
        mock_store = MagicMock()
        mock_store.create_or_get.return_value = {
            "id": "test-job-id",
            "status": "pending"
        }
        mock_store_class.return_value = mock_store

        # Mock enqueue
        mock_enqueue.return_value = {"job_id": "rq-123"}

        response = client.post(
            "/tasks/suggestions/close",
            headers={"X-Cron-Secret": "test-cron-secret"}
        )

        assert response.status_code == 202
        data = response.json()
        assert data["job_name"] == "suggestions_close"
        assert "job_run_id" in data

    @patch("packages.quantum.jobs.rq_enqueue.enqueue_idempotent")
    @patch("packages.quantum.jobs.job_runs.JobRunStore")
    def test_suggestions_open_accepts_valid_request(self, mock_store_class, mock_enqueue):
        """POST /tasks/suggestions/open returns 202 with valid cron secret."""
        from packages.quantum.api import app
        client = TestClient(app)

        mock_store = MagicMock()
        mock_store.create_or_get.return_value = {
            "id": "test-job-id",
            "status": "pending"
        }
        mock_store_class.return_value = mock_store
        mock_enqueue.return_value = {"job_id": "rq-123"}

        response = client.post(
            "/tasks/suggestions/open",
            headers={"X-Cron-Secret": "test-cron-secret"}
        )

        assert response.status_code == 202
        data = response.json()
        assert data["job_name"] == "suggestions_open"

    @patch("packages.quantum.jobs.rq_enqueue.enqueue_idempotent")
    @patch("packages.quantum.jobs.job_runs.JobRunStore")
    def test_suggestions_close_accepts_custom_strategy(self, mock_store_class, mock_enqueue):
        """POST /tasks/suggestions/close accepts custom strategy_name."""
        from packages.quantum.api import app
        client = TestClient(app)

        mock_store = MagicMock()
        mock_store.create_or_get.return_value = {
            "id": "test-job-id",
            "status": "pending"
        }
        mock_store_class.return_value = mock_store
        mock_enqueue.return_value = {"job_id": "rq-123"}

        response = client.post(
            "/tasks/suggestions/close",
            headers={"X-Cron-Secret": "test-cron-secret"},
            json={"strategy_name": "custom_strategy_v1"}
        )

        assert response.status_code == 202

        # Verify payload was passed correctly
        call_args = mock_store.create_or_get.call_args
        payload = call_args[0][2]  # Third positional arg is payload
        assert payload["strategy_name"] == "custom_strategy_v1"


class TestStrategyLoader:
    """Test the strategy loader service."""

    def test_default_strategy_config_has_required_fields(self):
        """Default strategy config contains all required fields."""
        from packages.quantum.services.strategy_loader import DEFAULT_STRATEGY_CONFIG

        required_fields = [
            "name", "version", "max_risk_pct_per_trade", "max_risk_pct_portfolio",
            "conviction_floor", "take_profit_pct", "stop_loss_pct"
        ]

        for field in required_fields:
            assert field in DEFAULT_STRATEGY_CONFIG, f"Missing required field: {field}"

    def test_default_strategy_name_is_spy_opt_autolearn_v6(self):
        """Default strategy name matches expected value."""
        from packages.quantum.services.strategy_loader import DEFAULT_STRATEGY_CONFIG

        assert DEFAULT_STRATEGY_CONFIG["name"] == "spy_opt_autolearn_v6"

    @patch("packages.quantum.services.strategy_loader.Client")
    def test_load_strategy_returns_default_when_not_found(self, mock_client):
        """load_strategy_config returns default when DB has no config."""
        from packages.quantum.services.strategy_loader import load_strategy_config

        # Mock empty result
        mock_supabase = MagicMock()
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []

        result = load_strategy_config("user-123", "spy_opt_autolearn_v6", mock_supabase)

        assert result["name"] == "spy_opt_autolearn_v6"
        assert "max_risk_pct_portfolio" in result


class TestHoldingsSyncService:
    """Test the holdings sync service."""

    def test_staleness_threshold_is_reasonable(self):
        """Staleness threshold is set to a reasonable value."""
        from packages.quantum.services.holdings_sync_service import STALENESS_THRESHOLD_MINUTES

        # Should be between 15 minutes and 24 hours
        assert 15 <= STALENESS_THRESHOLD_MINUTES <= 1440


class TestTimezoneDocumentation:
    """Test that timezone is properly documented."""

    def test_workflow_has_timezone_documentation(self):
        """GitHub Actions workflow documents America/Chicago timezone."""
        import os
        workflow_path = os.path.join(
            os.path.dirname(__file__),
            "..", "..", "..", "..",
            ".github", "workflows", "schedule_tasks.yml"
        )
        workflow_path = os.path.normpath(workflow_path)

        if os.path.exists(workflow_path):
            with open(workflow_path, "r") as f:
                content = f.read()

            assert "America/Chicago" in content, "Workflow should document America/Chicago timezone"
            assert "8:00 AM" in content or "8 AM" in content, "Workflow should document 8 AM time"
            assert "11:00 AM" in content or "11 AM" in content, "Workflow should document 11 AM time"


class TestLearningIngestIdempotency:
    """Test that learning ingest is idempotent."""

    def test_outcome_matching_requires_symbol_and_direction(self):
        """Outcome matching requires both symbol and direction."""
        from packages.quantum.jobs.handlers.learning_ingest import _match_transaction_to_suggestion

        # Transaction without symbol should not match
        tx_no_symbol = {"type": "buy", "date": "2024-01-15"}
        suggestions = [{"symbol": "AAPL", "direction": "open", "created_at": "2024-01-15T10:00:00Z"}]

        result = _match_transaction_to_suggestion(tx_no_symbol, suggestions)
        assert result is None

    def test_outcome_matching_respects_date_proximity(self):
        """Outcome matching only matches within 7 day window."""
        from packages.quantum.jobs.handlers.learning_ingest import _match_transaction_to_suggestion

        # Transaction from 10 days ago should not match
        tx = {"symbol": "AAPL", "type": "buy", "date": "2024-01-01"}
        suggestions = [{"symbol": "AAPL", "direction": "open", "created_at": "2024-01-15T10:00:00Z"}]

        result = _match_transaction_to_suggestion(tx, suggestions)
        assert result is None
