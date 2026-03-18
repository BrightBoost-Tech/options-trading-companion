"""
Tests for validation_eval job handler.

Verifies:
1. Existing readiness response remains intact
2. Green-day fields appear when service method is available
3. Safe fallback behavior works when service method is absent
4. Result payloads are audit-friendly and stable
5. Batch mode includes green-day fields per user
"""

import unittest
from unittest.mock import MagicMock, patch
import sys

# Bypass version check so the module can be imported
with patch.dict(sys.modules, {"packages.quantum.check_version": MagicMock()}):
    import packages.quantum.jobs.handlers.validation_eval as ve_mod
    from packages.quantum.jobs.handlers.validation_eval import (
        run,
        _eval_green_day_safe,
        _build_paper_result,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_CHECKPOINT_PASS = {
    "status": "pass",
    "paper_consecutive_passes": 6,
    "streak_before": 5,
    "paper_ready": False,
    "return_pct": 3.2,
    "target_return_now": 2.5,
    "max_drawdown_pct": -0.5,
    "progress": 0.45,
    "window_start": "2024-01-01T06:00:00+00:00",
    "window_end": "2024-01-22T06:00:00+00:00",
    "bucket": "2024-01-10",
    "outcome_count": 7,
    "pnl_total": 3200.0,
    "pnl_realized": 3000.0,
    "pnl_unrealized": 200.0,
    "reason": None,
}

_GREEN_DAY_RESULT = {
    "evaluated_trading_date": "2024-01-10",
    "daily_realized_pnl": 150.0,
    "green_day": True,
    "paper_green_days": 4,
    "paper_last_green_day_date": "2024-01-10",
    "already_evaluated": False,
}

_GREEN_DAY_DEFAULTS = {
    "evaluated_trading_date": None,
    "daily_realized_pnl": None,
    "green_day": None,
    "paper_green_days": None,
    "paper_last_green_day_date": None,
    "green_day_available": False,
}


# ===========================================================================
# Tests: _eval_green_day_safe
# ===========================================================================

class TestEvalGreenDaySafe(unittest.TestCase):
    """Tests for the safe green-day fallback wrapper."""

    def test_returns_defaults_when_method_absent(self):
        """If service has no eval_paper_green_day, return null defaults."""
        service = MagicMock(spec=[])  # empty spec — no methods
        result = _eval_green_day_safe(service, "user-123")

        self.assertIsNone(result["evaluated_trading_date"])
        self.assertIsNone(result["daily_realized_pnl"])
        self.assertIsNone(result["green_day"])
        self.assertIsNone(result["paper_green_days"])
        self.assertIsNone(result["paper_last_green_day_date"])
        self.assertFalse(result["green_day_available"])

    def test_returns_service_result_when_method_present(self):
        """If service has eval_paper_green_day, use its result."""
        service = MagicMock()
        service.eval_paper_green_day.return_value = _GREEN_DAY_RESULT

        result = _eval_green_day_safe(service, "user-123")

        self.assertEqual(result["evaluated_trading_date"], "2024-01-10")
        self.assertEqual(result["daily_realized_pnl"], 150.0)
        self.assertTrue(result["green_day"])
        self.assertEqual(result["paper_green_days"], 4)
        self.assertTrue(result["green_day_available"])

    def test_returns_defaults_when_method_raises(self):
        """If eval_paper_green_day raises, return null defaults with error."""
        service = MagicMock()
        service.eval_paper_green_day.side_effect = RuntimeError("DB down")

        result = _eval_green_day_safe(service, "user-12345678")

        self.assertIsNone(result["green_day"])
        self.assertFalse(result["green_day_available"])
        self.assertEqual(result["green_day_error"], "DB down")


# ===========================================================================
# Tests: _build_paper_result
# ===========================================================================

class TestBuildPaperResult(unittest.TestCase):
    """Tests for the merged result builder."""

    def test_includes_checkpoint_fields(self):
        """Checkpoint fields must be present in merged result."""
        result = _build_paper_result(_CHECKPOINT_PASS, _GREEN_DAY_DEFAULTS)

        self.assertEqual(result["checkpoint_status"], "pass")
        self.assertEqual(result["paper_consecutive_passes"], 6)
        self.assertFalse(result["paper_ready"])
        self.assertEqual(result["return_pct"], 3.2)
        self.assertEqual(result["pnl_realized"], 3000.0)
        self.assertEqual(result["pnl_unrealized"], 200.0)

    def test_includes_green_day_fields(self):
        """Green-day fields must be present in merged result."""
        gd = {
            "evaluated_trading_date": "2024-01-10",
            "daily_realized_pnl": 150.0,
            "green_day": True,
            "paper_green_days": 4,
            "paper_last_green_day_date": "2024-01-10",
            "green_day_available": True,
        }
        result = _build_paper_result(_CHECKPOINT_PASS, gd)

        self.assertEqual(result["evaluated_trading_date"], "2024-01-10")
        self.assertEqual(result["daily_realized_pnl"], 150.0)
        self.assertTrue(result["green_day"])
        self.assertEqual(result["paper_green_days"], 4)
        self.assertTrue(result["green_day_available"])

    def test_null_green_day_fields_when_unavailable(self):
        """When green day is unavailable, fields should be None."""
        result = _build_paper_result(_CHECKPOINT_PASS, _GREEN_DAY_DEFAULTS)

        self.assertIsNone(result["evaluated_trading_date"])
        self.assertIsNone(result["green_day"])
        self.assertIsNone(result["paper_green_days"])
        self.assertFalse(result["green_day_available"])

    def test_all_required_keys_present(self):
        """Merged result must contain exactly the expected audit keys."""
        result = _build_paper_result(_CHECKPOINT_PASS, _GREEN_DAY_DEFAULTS)

        required_keys = {
            "checkpoint_status",
            "paper_consecutive_passes",
            "paper_ready",
            "reason",
            "return_pct",
            "pnl_realized",
            "pnl_unrealized",
            "target_return_now",
            "progress",
            "max_drawdown_pct",
            "bucket",
            "streak_before",
            "window_start",
            "window_end",
            "outcome_count",
            "evaluated_trading_date",
            "daily_realized_pnl",
            "green_day",
            "paper_green_days",
            "paper_last_green_day_date",
            "green_day_available",
            "checkpoint",
            "green_day_detail",
        }
        self.assertEqual(required_keys, set(result.keys()))


# ===========================================================================
# Tests: nested objects in _build_paper_result
# ===========================================================================

class TestNestedObjects(unittest.TestCase):
    """Verify nested checkpoint and green_day objects appear."""

    def test_checkpoint_nested_object_present(self):
        """Nested checkpoint should contain full raw checkpoint data."""
        result = _build_paper_result(_CHECKPOINT_PASS, _GREEN_DAY_DEFAULTS)
        self.assertIn("checkpoint", result)
        self.assertEqual(result["checkpoint"]["status"], "pass")
        self.assertEqual(result["checkpoint"]["paper_consecutive_passes"], 6)

    def test_green_day_nested_object_present(self):
        """Nested green_day_detail should contain full raw green-day data."""
        gd = {
            "evaluated_trading_date": "2024-01-10",
            "daily_realized_pnl": 150.0,
            "green_day": True,
            "paper_green_days": 4,
            "paper_last_green_day_date": "2024-01-10",
            "green_day_available": True,
        }
        result = _build_paper_result(_CHECKPOINT_PASS, gd)
        self.assertIn("green_day_detail", result)
        self.assertEqual(result["green_day_detail"]["daily_realized_pnl"], 150.0)

    def test_nested_and_flat_fields_consistent(self):
        """Flat fields should match nested object values."""
        gd = {
            "evaluated_trading_date": "2024-01-10",
            "daily_realized_pnl": 150.0,
            "green_day": True,
            "paper_green_days": 4,
            "paper_last_green_day_date": "2024-01-10",
            "green_day_available": True,
        }
        result = _build_paper_result(_CHECKPOINT_PASS, gd)
        # Flat and nested should agree
        self.assertEqual(result["checkpoint_status"], result["checkpoint"]["status"])
        self.assertEqual(result["paper_green_days"], result["green_day_detail"]["paper_green_days"])


# ===========================================================================
# Tests: run() — single user paper mode
# ===========================================================================

class TestRunSingleUserPaper(unittest.TestCase):
    """Test the run() handler in single-user paper mode."""

    def test_paper_mode_returns_merged_result(self):
        """Single-user paper mode should return checkpoint + green-day merged."""
        mock_supabase = MagicMock()
        mock_service = MagicMock()
        mock_service.eval_paper_forward_checkpoint.return_value = _CHECKPOINT_PASS
        mock_service.eval_paper_green_day.return_value = _GREEN_DAY_RESULT

        with patch.object(ve_mod, "_get_supabase_client", return_value=mock_supabase), \
             patch.object(ve_mod, "GoLiveValidationService", return_value=mock_service):

            result = run({"mode": "paper", "user_id": "user-abc"})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["checkpoint_status"], "pass")
        self.assertEqual(result["result"]["paper_green_days"], 4)
        self.assertTrue(result["result"]["green_day_available"])
        self.assertIn("timing_ms", result)

    def test_paper_mode_without_green_day_method(self):
        """If service lacks eval_paper_green_day, result still works with nulls."""
        mock_supabase = MagicMock()
        mock_service = MagicMock(spec=["eval_paper_forward_checkpoint"])
        mock_service.eval_paper_forward_checkpoint.return_value = _CHECKPOINT_PASS

        with patch.object(ve_mod, "_get_supabase_client", return_value=mock_supabase), \
             patch.object(ve_mod, "GoLiveValidationService", return_value=mock_service):

            result = run({"mode": "paper", "user_id": "user-abc"})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["checkpoint_status"], "pass")
        self.assertEqual(result["result"]["paper_consecutive_passes"], 6)
        self.assertIsNone(result["result"]["green_day"])
        self.assertFalse(result["result"]["green_day_available"])

    def test_readiness_fields_unchanged(self):
        """Existing readiness fields should pass through unchanged."""
        mock_supabase = MagicMock()
        mock_service = MagicMock()
        mock_service.eval_paper_forward_checkpoint.return_value = _CHECKPOINT_PASS
        mock_service.eval_paper_green_day.return_value = _GREEN_DAY_RESULT

        with patch.object(ve_mod, "_get_supabase_client", return_value=mock_supabase), \
             patch.object(ve_mod, "GoLiveValidationService", return_value=mock_service):

            result = run({"mode": "paper", "user_id": "user-abc"})

        r = result["result"]
        self.assertEqual(r["paper_consecutive_passes"], 6)
        self.assertFalse(r["paper_ready"])
        self.assertEqual(r["return_pct"], 3.2)
        self.assertEqual(r["max_drawdown_pct"], -0.5)
        self.assertEqual(r["window_start"], "2024-01-01T06:00:00+00:00")
        self.assertEqual(r["outcome_count"], 7)


# ===========================================================================
# Tests: run() — batch mode
# ===========================================================================

class TestRunBatchMode(unittest.TestCase):
    """Test the run() handler in batch mode (no user_id)."""

    def test_batch_mode_includes_green_day_per_user(self):
        """Batch mode should include merged results per user."""
        mock_supabase = MagicMock()
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[
            {"user_id": "user-1"},
            {"user_id": "user-2"},
        ])
        chain.select = MagicMock(return_value=chain)
        mock_supabase.table = MagicMock(return_value=chain)

        mock_service = MagicMock()
        mock_service.eval_paper_forward_checkpoint.return_value = _CHECKPOINT_PASS
        mock_service.eval_paper_green_day.return_value = _GREEN_DAY_RESULT

        with patch.object(ve_mod, "_get_supabase_client", return_value=mock_supabase), \
             patch.object(ve_mod, "GoLiveValidationService", return_value=mock_service):

            result = run({"mode": "paper"})

        self.assertEqual(result["status"], "batch_completed")
        self.assertIn("user-1", result["results"])
        self.assertIn("user-2", result["results"])

        u1 = result["results"]["user-1"]
        self.assertEqual(u1["checkpoint_status"], "pass")
        self.assertEqual(u1["paper_green_days"], 4)
        self.assertTrue(u1["green_day_available"])

    def test_batch_mode_handles_per_user_error(self):
        """If one user errors, it should not crash the batch."""
        mock_supabase = MagicMock()
        chain = MagicMock()
        chain.execute.return_value = MagicMock(data=[
            {"user_id": "user-ok"},
            {"user_id": "user-fail"},
        ])
        chain.select = MagicMock(return_value=chain)
        mock_supabase.table = MagicMock(return_value=chain)

        mock_service = MagicMock()

        def checkpoint_side_effect(uid):
            if uid == "user-fail":
                raise RuntimeError("boom")
            return _CHECKPOINT_PASS

        mock_service.eval_paper_forward_checkpoint.side_effect = checkpoint_side_effect
        mock_service.eval_paper_green_day.return_value = _GREEN_DAY_RESULT

        with patch.object(ve_mod, "_get_supabase_client", return_value=mock_supabase), \
             patch.object(ve_mod, "GoLiveValidationService", return_value=mock_service):

            result = run({"mode": "paper"})

        self.assertEqual(result["status"], "batch_completed")
        self.assertEqual(result["results"]["user-ok"]["checkpoint_status"], "pass")
        self.assertEqual(result["results"]["user-fail"]["checkpoint_status"], "error")


# ===========================================================================
# Tests: run() — historical mode unchanged
# ===========================================================================

class TestRunHistoricalMode(unittest.TestCase):
    """Historical mode should remain completely unchanged."""

    def test_historical_eval_unchanged(self):
        mock_supabase = MagicMock()
        mock_service = MagicMock()
        mock_service.eval_historical.return_value = {"score": 0.85}

        with patch.object(ve_mod, "_get_supabase_client", return_value=mock_supabase), \
             patch.object(ve_mod, "GoLiveValidationService", return_value=mock_service):

            result = run({"mode": "historical", "user_id": "user-abc", "config": {}})

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["result"]["score"], 0.85)
        self.assertNotIn("green_day", result.get("result", {}))

    def test_historical_train_unchanged(self):
        mock_supabase = MagicMock()
        mock_service = MagicMock()
        mock_service.train_historical.return_value = {"best_config": {}}

        with patch.object(ve_mod, "_get_supabase_client", return_value=mock_supabase), \
             patch.object(ve_mod, "GoLiveValidationService", return_value=mock_service):

            result = run({
                "mode": "historical",
                "user_id": "user-abc",
                "config": {"train": True},
            })

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["mode"], "train")


# ===========================================================================
# Tests: error handling
# ===========================================================================

class TestRunErrorHandling(unittest.TestCase):
    """Verify error handling hasn't regressed."""

    def test_db_unavailable(self):
        with patch.object(ve_mod, "_get_supabase_client", return_value=None):
            result = run({"mode": "paper", "user_id": "user-abc"})

        self.assertIn("error", result)
        self.assertEqual(result["error"], "Database unavailable")

    def test_unknown_mode(self):
        mock_supabase = MagicMock()
        mock_service = MagicMock()

        with patch.object(ve_mod, "_get_supabase_client", return_value=mock_supabase), \
             patch.object(ve_mod, "GoLiveValidationService", return_value=mock_service):

            result = run({"mode": "unknown", "user_id": "user-abc"})

        self.assertIn("error", result)
        self.assertIn("Unknown mode", result["error"])

    def test_exception_returns_failed_status(self):
        with patch.object(ve_mod, "_get_supabase_client", side_effect=RuntimeError("init failed")):
            result = run({"mode": "paper", "user_id": "user-abc"})

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error"], "init failed")


# ===========================================================================
# Tests: audit-friendliness
# ===========================================================================

class TestAuditFriendliness(unittest.TestCase):
    """Verify the payload contains enough info for ops verification."""

    def test_result_has_all_audit_fields(self):
        """Ops should be able to verify: what day, PnL, green count, streak."""
        mock_supabase = MagicMock()
        mock_service = MagicMock()
        mock_service.eval_paper_forward_checkpoint.return_value = _CHECKPOINT_PASS
        mock_service.eval_paper_green_day.return_value = _GREEN_DAY_RESULT

        with patch.object(ve_mod, "_get_supabase_client", return_value=mock_supabase), \
             patch.object(ve_mod, "GoLiveValidationService", return_value=mock_service):

            result = run({"mode": "paper", "user_id": "user-abc"})

        r = result["result"]

        # Ops verification checklist:
        self.assertIsNotNone(r["evaluated_trading_date"])   # what day
        self.assertIsNotNone(r["daily_realized_pnl"])       # realized PnL
        self.assertIsNotNone(r["paper_green_days"])          # green count
        self.assertIsNotNone(r["paper_consecutive_passes"])  # readiness streak
        self.assertIsNotNone(r["checkpoint_status"])         # checkpoint outcome

    def test_timing_present(self):
        """Result should include timing_ms for ops monitoring."""
        mock_supabase = MagicMock()
        mock_service = MagicMock()
        mock_service.eval_paper_forward_checkpoint.return_value = _CHECKPOINT_PASS
        mock_service.eval_paper_green_day.return_value = _GREEN_DAY_RESULT

        with patch.object(ve_mod, "_get_supabase_client", return_value=mock_supabase), \
             patch.object(ve_mod, "GoLiveValidationService", return_value=mock_service):

            result = run({"mode": "paper", "user_id": "user-abc"})

        self.assertIn("timing_ms", result)
        self.assertIsInstance(result["timing_ms"], float)


if __name__ == "__main__":
    unittest.main()
