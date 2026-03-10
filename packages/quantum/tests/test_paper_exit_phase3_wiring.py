"""
Tests for Phase 3: wiring — task endpoints, payload models, scope registration.

Verifies:
1. PaperExitEvaluatePayload and PaperMarkToMarketPayload exist in models
2. TASK_SCOPES includes both new endpoints
3. public_tasks.py imports the new payload models
4. public_tasks.py defines the two new endpoint functions
5. Job handlers have correct JOB_NAME
6. Backfill migration exists
"""

import pytest
from pathlib import Path


QUANTUM_ROOT = Path(__file__).resolve().parents[1]


class TestPayloadModels:
    """Verify payload models are defined correctly."""

    def test_exit_evaluate_payload_exists(self):
        from packages.quantum.public_tasks_models import PaperExitEvaluatePayload

        p = PaperExitEvaluatePayload(user_id="a" * 36)
        assert p.user_id == "a" * 36

    def test_mark_to_market_payload_exists(self):
        from packages.quantum.public_tasks_models import PaperMarkToMarketPayload

        p = PaperMarkToMarketPayload(user_id="b" * 36)
        assert p.user_id == "b" * 36

    def test_exit_evaluate_rejects_all(self):
        from packages.quantum.public_tasks_models import PaperExitEvaluatePayload

        with pytest.raises(Exception):
            PaperExitEvaluatePayload(user_id="all")

    def test_mark_to_market_rejects_short_id(self):
        from packages.quantum.public_tasks_models import PaperMarkToMarketPayload

        with pytest.raises(Exception):
            PaperMarkToMarketPayload(user_id="short")


class TestTaskScopes:
    """Verify scope registration."""

    def test_exit_evaluate_scope(self):
        from packages.quantum.public_tasks_models import TASK_SCOPES

        assert "/tasks/paper/exit-evaluate" in TASK_SCOPES
        assert TASK_SCOPES["/tasks/paper/exit-evaluate"] == "tasks:paper_exit_evaluate"

    def test_mark_to_market_scope(self):
        from packages.quantum.public_tasks_models import TASK_SCOPES

        assert "/tasks/paper/mark-to-market" in TASK_SCOPES
        assert TASK_SCOPES["/tasks/paper/mark-to-market"] == "tasks:paper_mark_to_market"


class TestPublicTasksWiring:
    """Verify public_tasks.py has the endpoint functions wired up."""

    @staticmethod
    def _get_source():
        return (QUANTUM_ROOT / "public_tasks.py").read_text(encoding="utf-8")

    def test_imports_exit_evaluate_payload(self):
        source = self._get_source()
        assert "PaperExitEvaluatePayload" in source

    def test_imports_mark_to_market_payload(self):
        source = self._get_source()
        assert "PaperMarkToMarketPayload" in source

    def test_exit_evaluate_endpoint_defined(self):
        source = self._get_source()
        assert 'def task_paper_exit_evaluate' in source
        assert '"/paper/exit-evaluate"' in source

    def test_mark_to_market_endpoint_defined(self):
        source = self._get_source()
        assert 'def task_paper_mark_to_market' in source
        assert '"/paper/mark-to-market"' in source

    def test_exit_evaluate_enqueues_correct_job(self):
        source = self._get_source()
        assert '"paper_exit_evaluate"' in source

    def test_mark_to_market_enqueues_correct_job(self):
        source = self._get_source()
        assert '"paper_mark_to_market"' in source


class TestJobHandlers:
    """Verify job handlers have correct JOB_NAME constants."""

    def test_exit_evaluate_handler_job_name(self):
        source = (QUANTUM_ROOT / "jobs" / "handlers" / "paper_exit_evaluate.py").read_text(encoding="utf-8")
        assert 'JOB_NAME = "paper_exit_evaluate"' in source

    def test_mark_to_market_handler_job_name(self):
        source = (QUANTUM_ROOT / "jobs" / "handlers" / "paper_mark_to_market.py").read_text(encoding="utf-8")
        assert 'JOB_NAME = "paper_mark_to_market"' in source


class TestBackfillMigration:
    """Verify backfill migration exists and contains expected operations."""

    @staticmethod
    def _get_migration():
        path = QUANTUM_ROOT.parents[1] / "supabase" / "migrations" / "20260310100000_backfill_paper_positions_exit_fields.sql"
        return path.read_text(encoding="utf-8")

    def test_backfill_migration_exists(self):
        self._get_migration()  # raises if missing

    def test_backfills_user_id(self):
        sql = self._get_migration()
        assert "user_id" in sql
        assert "paper_portfolios" in sql

    def test_backfills_max_credit(self):
        sql = self._get_migration()
        assert "max_credit" in sql
        assert "avg_entry_price" in sql

    def test_backfills_status(self):
        sql = self._get_migration()
        assert "status" in sql
        assert "'open'" in sql
        assert "'closed'" in sql


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
