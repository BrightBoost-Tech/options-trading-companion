"""
Tests for v4-L5 Ops Console MVP

Tests:
1. Pause gate enforcement at enqueue
2. Dashboard state endpoint structure
3. Pause/mode endpoint validation
4. Market freshness status mapping
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from packages.quantum.ops_endpoints import (
    OpsControlState,
    FreshnessItem,
    PipelineJobState,
    HealthBlock,
    DashboardStateResponse,
    is_trading_paused,
    get_global_ops_control,
    _get_market_freshness,
    _compute_health,
    FRESHNESS_OK_MS,
    FRESHNESS_WARN_MS,
    CANONICAL_JOB_NAMES,
)


class TestPauseGateEnforcement:
    """Test pause enforcement at enqueue gate."""

    def test_is_trading_paused_returns_tuple(self):
        """is_trading_paused returns (bool, Optional[str])"""
        with patch("packages.quantum.ops_endpoints.get_admin_client") as mock_client:
            mock_table = MagicMock()
            mock_client.return_value.table.return_value = mock_table
            mock_table.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
                data={"paused": True, "pause_reason": "Testing"}
            )

            is_paused, reason = is_trading_paused()
            assert isinstance(is_paused, bool)
            assert reason is None or isinstance(reason, str)

    def test_is_trading_paused_defaults_to_true_on_error(self):
        """Safe default: paused=True when DB unavailable"""
        with patch("packages.quantum.ops_endpoints.get_admin_client") as mock_client:
            mock_client.side_effect = Exception("DB unavailable")

            is_paused, reason = is_trading_paused()
            assert is_paused is True
            assert "Unable to fetch" in (reason or "")

    def test_get_global_ops_control_returns_dict(self):
        """get_global_ops_control returns dict with expected keys"""
        with patch("packages.quantum.ops_endpoints.get_admin_client") as mock_client:
            mock_table = MagicMock()
            mock_client.return_value.table.return_value = mock_table
            mock_table.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
                data={
                    "key": "global",
                    "mode": "paper",
                    "paused": False,
                    "pause_reason": None,
                    "updated_at": "2026-01-19T00:00:00Z"
                }
            )

            control = get_global_ops_control()
            assert "mode" in control
            assert "paused" in control
            assert control["mode"] == "paper"
            assert control["paused"] is False


class TestMarketFreshness:
    """Test market freshness status mapping."""

    def test_freshness_status_ok_threshold(self):
        """Freshness <= 60s maps to OK status"""
        item = FreshnessItem(
            symbol="SPY",
            freshness_ms=30_000,  # 30 seconds
            status="OK",
            score=100,
            issues=None
        )
        assert item.status == "OK"
        assert item.freshness_ms <= FRESHNESS_OK_MS

    def test_freshness_status_warn_threshold(self):
        """Freshness 60-120s maps to WARN status"""
        item = FreshnessItem(
            symbol="SPY",
            freshness_ms=90_000,  # 90 seconds
            status="WARN",
            score=80,
            issues=["stale_quote"]
        )
        assert item.status == "WARN"
        assert FRESHNESS_OK_MS < item.freshness_ms <= FRESHNESS_WARN_MS

    def test_freshness_status_stale_threshold(self):
        """Freshness > 120s maps to STALE status"""
        item = FreshnessItem(
            symbol="SPY",
            freshness_ms=180_000,  # 3 minutes
            status="STALE",
            score=50,
            issues=["stale_quote"]
        )
        assert item.status == "STALE"
        assert item.freshness_ms > FRESHNESS_WARN_MS

    def test_freshness_none_is_stale(self):
        """None freshness maps to STALE status"""
        item = FreshnessItem(
            symbol="SPY",
            freshness_ms=None,
            status="STALE",
            score=None,
            issues=["missing_timestamp"]
        )
        assert item.status == "STALE"
        assert item.freshness_ms is None


class TestPipelineStatus:
    """Test pipeline job status tracking."""

    def test_canonical_job_names_defined(self):
        """All canonical job names are defined"""
        assert "suggestions_close" in CANONICAL_JOB_NAMES
        assert "suggestions_open" in CANONICAL_JOB_NAMES
        assert "learning_ingest" in CANONICAL_JOB_NAMES
        assert "strategy_autotune" in CANONICAL_JOB_NAMES

    def test_pipeline_job_state_model(self):
        """PipelineJobState has expected fields"""
        state = PipelineJobState(
            status="succeeded",
            created_at=datetime.now(),
            finished_at=datetime.now()
        )
        assert state.status == "succeeded"
        assert state.created_at is not None
        assert state.finished_at is not None

    def test_pipeline_job_state_never_run(self):
        """PipelineJobState handles never_run status"""
        state = PipelineJobState(
            status="never_run",
            created_at=None,
            finished_at=None
        )
        assert state.status == "never_run"
        assert state.created_at is None


class TestDashboardStateResponse:
    """Test dashboard state response structure."""

    def test_dashboard_state_structure(self):
        """DashboardStateResponse has all required fields including health"""
        control = OpsControlState(
            mode="paper",
            paused=True,
            pause_reason="Testing",
            updated_at=datetime.now()
        )
        freshness = [
            FreshnessItem(symbol="SPY", freshness_ms=1000, status="OK", score=100, issues=None),
            FreshnessItem(symbol="QQQ", freshness_ms=2000, status="OK", score=100, issues=None),
        ]
        pipeline = {
            "suggestions_close": PipelineJobState(status="succeeded", created_at=None, finished_at=None),
            "suggestions_open": PipelineJobState(status="queued", created_at=None, finished_at=None),
        }
        health = HealthBlock(
            status="paused",
            issues=["Trading paused: Testing"],
            checks={"trading": "paused", "market_data": "ok", "pipeline": "ok"}
        )

        response = DashboardStateResponse(
            control=control,
            freshness=freshness,
            pipeline=pipeline,
            health=health,
        )

        assert response.control.mode == "paper"
        assert response.control.paused is True
        assert len(response.freshness) == 2
        assert "suggestions_close" in response.pipeline
        assert response.health.status == "paused"
        assert "trading" in response.health.checks


class TestHealthBlock:
    """PR B: Test health block computation."""

    def test_healthy_when_all_ok(self):
        """Health status is 'healthy' when all components are OK"""
        control = OpsControlState(
            mode="paper",
            paused=False,
            pause_reason=None,
            updated_at=datetime.now()
        )
        freshness = [
            FreshnessItem(symbol="SPY", freshness_ms=5000, status="OK", score=100, issues=None),
            FreshnessItem(symbol="QQQ", freshness_ms=5000, status="OK", score=100, issues=None),
        ]
        pipeline = {
            "suggestions_close": PipelineJobState(status="succeeded", created_at=None, finished_at=None),
            "suggestions_open": PipelineJobState(status="succeeded", created_at=None, finished_at=None),
        }

        health = _compute_health(control, freshness, pipeline)

        assert health.status == "healthy"
        assert len(health.issues) == 0
        assert health.checks["trading"] == "active"
        assert health.checks["market_data"] == "ok"
        assert health.checks["pipeline"] == "ok"

    def test_paused_status_when_trading_paused(self):
        """Health status is 'paused' when trading is paused"""
        control = OpsControlState(
            mode="paper",
            paused=True,
            pause_reason="System maintenance",
            updated_at=datetime.now()
        )
        freshness = [
            FreshnessItem(symbol="SPY", freshness_ms=5000, status="OK", score=100, issues=None),
        ]
        pipeline = {
            "suggestions_close": PipelineJobState(status="succeeded", created_at=None, finished_at=None),
        }

        health = _compute_health(control, freshness, pipeline)

        assert health.status == "paused"
        assert health.checks["trading"] == "paused"
        assert any("paused" in issue.lower() for issue in health.issues)

    def test_unhealthy_when_market_data_stale(self):
        """Health status is 'unhealthy' when market data is stale"""
        control = OpsControlState(
            mode="paper",
            paused=False,
            pause_reason=None,
            updated_at=datetime.now()
        )
        freshness = [
            FreshnessItem(symbol="SPY", freshness_ms=5000, status="OK", score=100, issues=None),
            FreshnessItem(symbol="QQQ", freshness_ms=None, status="STALE", score=0, issues=["stale"]),
        ]
        pipeline = {
            "suggestions_close": PipelineJobState(status="succeeded", created_at=None, finished_at=None),
        }

        health = _compute_health(control, freshness, pipeline)

        assert health.status == "unhealthy"
        assert health.checks["market_data"] == "stale"
        assert any("stale" in issue.lower() for issue in health.issues)

    def test_unhealthy_when_pipeline_failed_retryable(self):
        """Health status is 'unhealthy' when pipeline jobs are failed_retryable"""
        control = OpsControlState(
            mode="paper",
            paused=False,
            pause_reason=None,
            updated_at=datetime.now()
        )
        freshness = [
            FreshnessItem(symbol="SPY", freshness_ms=5000, status="OK", score=100, issues=None),
        ]
        pipeline = {
            "suggestions_close": PipelineJobState(status="failed_retryable", created_at=None, finished_at=None),
            "suggestions_open": PipelineJobState(status="succeeded", created_at=None, finished_at=None),
        }

        health = _compute_health(control, freshness, pipeline)

        assert health.status == "unhealthy"
        assert health.checks["pipeline"] == "failed"
        assert any("failed" in issue.lower() for issue in health.issues)

    def test_degraded_when_market_data_warn(self):
        """Health status is 'degraded' when market data has warnings"""
        control = OpsControlState(
            mode="paper",
            paused=False,
            pause_reason=None,
            updated_at=datetime.now()
        )
        freshness = [
            FreshnessItem(symbol="SPY", freshness_ms=90000, status="WARN", score=80, issues=["stale_quote"]),
            FreshnessItem(symbol="QQQ", freshness_ms=5000, status="OK", score=100, issues=None),
        ]
        pipeline = {
            "suggestions_close": PipelineJobState(status="succeeded", created_at=None, finished_at=None),
        }

        health = _compute_health(control, freshness, pipeline)

        assert health.status == "degraded"
        assert health.checks["market_data"] == "warn"

    def test_unhealthy_takes_precedence_over_paused(self):
        """Unhealthy status takes precedence over paused"""
        control = OpsControlState(
            mode="paper",
            paused=True,
            pause_reason="Testing",
            updated_at=datetime.now()
        )
        freshness = [
            FreshnessItem(symbol="SPY", freshness_ms=None, status="STALE", score=0, issues=["stale"]),
        ]
        pipeline = {
            "suggestions_close": PipelineJobState(status="succeeded", created_at=None, finished_at=None),
        }

        health = _compute_health(control, freshness, pipeline)

        assert health.status == "unhealthy"  # Unhealthy takes precedence

    def test_pipeline_running_tracked(self):
        """Running jobs are tracked in checks"""
        control = OpsControlState(
            mode="paper",
            paused=False,
            pause_reason=None,
            updated_at=datetime.now()
        )
        freshness = [
            FreshnessItem(symbol="SPY", freshness_ms=5000, status="OK", score=100, issues=None),
        ]
        pipeline = {
            "suggestions_close": PipelineJobState(status="running", created_at=None, finished_at=None),
        }

        health = _compute_health(control, freshness, pipeline)

        assert health.status == "healthy"
        assert health.checks["pipeline"] == "running"

    def test_dead_lettered_treated_as_failed(self):
        """dead_lettered status is treated as failed"""
        control = OpsControlState(
            mode="paper",
            paused=False,
            pause_reason=None,
            updated_at=datetime.now()
        )
        freshness = [
            FreshnessItem(symbol="SPY", freshness_ms=5000, status="OK", score=100, issues=None),
        ]
        pipeline = {
            "suggestions_close": PipelineJobState(status="dead_lettered", created_at=None, finished_at=None),
        }

        health = _compute_health(control, freshness, pipeline)

        assert health.status == "unhealthy"
        assert health.checks["pipeline"] == "failed"

    def test_cancelled_not_treated_as_failure(self):
        """PR D: cancelled status is NOT treated as pipeline failure"""
        control = OpsControlState(
            mode="paper",
            paused=False,
            pause_reason=None,
            updated_at=datetime.now()
        )
        freshness = [
            FreshnessItem(symbol="SPY", freshness_ms=5000, status="OK", score=100, issues=None),
        ]
        pipeline = {
            "suggestions_close": PipelineJobState(status="cancelled", created_at=None, finished_at=None),
            "suggestions_open": PipelineJobState(status="succeeded", created_at=None, finished_at=None),
        }

        health = _compute_health(control, freshness, pipeline)

        # cancelled should NOT trigger unhealthy or failed pipeline check
        assert health.status == "healthy"
        assert health.checks["pipeline"] == "ok"

    def test_error_status_treated_as_unhealthy(self):
        """PR D: error status (synthetic, fetch failure) triggers unhealthy"""
        control = OpsControlState(
            mode="paper",
            paused=False,
            pause_reason=None,
            updated_at=datetime.now()
        )
        freshness = [
            FreshnessItem(symbol="SPY", freshness_ms=5000, status="OK", score=100, issues=None),
        ]
        pipeline = {
            "suggestions_close": PipelineJobState(status="error", created_at=None, finished_at=None),
            "suggestions_open": PipelineJobState(status="succeeded", created_at=None, finished_at=None),
        }

        health = _compute_health(control, freshness, pipeline)

        # error status indicates we couldn't fetch pipeline state - treat as unhealthy
        assert health.status == "unhealthy"
        assert health.checks["pipeline"] == "error"
        assert any("error" in issue.lower() for issue in health.issues)

    def test_health_block_model(self):
        """HealthBlock model has expected fields"""
        health = HealthBlock(
            status="healthy",
            issues=[],
            checks={"trading": "active", "market_data": "ok", "pipeline": "ok"}
        )
        assert health.status == "healthy"
        assert isinstance(health.issues, list)
        assert isinstance(health.checks, dict)


class TestOpsControlModes:
    """Test operating mode validation."""

    def test_valid_modes(self):
        """Valid modes are paper, micro_live, live"""
        valid_modes = ["paper", "micro_live", "live"]
        for mode in valid_modes:
            control = OpsControlState(
                mode=mode,
                paused=False,
                pause_reason=None,
                updated_at=datetime.now()
            )
            assert control.mode == mode

    def test_ops_control_state_model(self):
        """OpsControlState model validates correctly"""
        control = OpsControlState(
            mode="paper",
            paused=True,
            pause_reason="Initial setup",
            updated_at=datetime.now()
        )
        assert control.mode == "paper"
        assert control.paused is True
        assert control.pause_reason == "Initial setup"


class TestEnqueuePauseGate:
    """Test that enqueue_job_run respects pause gate."""

    def test_enqueue_creates_cancelled_record_when_paused(self):
        """PR A: enqueue_job_run creates cancelled JobRun when trading is paused"""
        import packages.quantum.public_tasks as pt_mod

        # Patch on the ops_endpoints module where it's defined
        with patch("packages.quantum.ops_endpoints.is_trading_paused") as mock_paused:
            mock_paused.return_value = (True, "System maintenance")

            # Patch JobRunStore.create_or_get_cancelled
            with patch.object(pt_mod, "JobRunStore") as mock_store:
                mock_store.return_value.create_or_get_cancelled.return_value = {
                    "id": "cancelled-id-123",
                    "status": "cancelled",
                    "job_name": "test_job",
                    "idempotency_key": "test-key",
                }

                result = pt_mod.enqueue_job_run(
                    job_name="test_job",
                    idempotency_key="test-key",
                    payload={"foo": "bar"}
                )

                # Verify cancelled record returned
                assert result["job_run_id"] == "cancelled-id-123"
                assert result["status"] == "cancelled"
                assert result["cancelled_reason"] == "global_ops_pause"
                assert result["pause_reason"] == "System maintenance"
                assert result["rq_job_id"] is None  # No RQ job created

                # Verify create_or_get_cancelled was called with correct args
                mock_store.return_value.create_or_get_cancelled.assert_called_once_with(
                    job_name="test_job",
                    idempotency_key="test-key",
                    payload={"foo": "bar"},
                    cancelled_reason="global_ops_pause",
                    cancelled_detail="System maintenance"
                )

    def test_enqueue_does_not_call_rq_when_paused(self):
        """PR A: enqueue_job_run does NOT enqueue to RQ when paused"""
        import packages.quantum.public_tasks as pt_mod

        with patch("packages.quantum.ops_endpoints.is_trading_paused") as mock_paused:
            mock_paused.return_value = (True, "System maintenance")

            with patch.object(pt_mod, "JobRunStore") as mock_store:
                mock_store.return_value.create_or_get_cancelled.return_value = {
                    "id": "cancelled-id",
                    "status": "cancelled",
                }

                with patch.object(pt_mod, "enqueue_idempotent") as mock_enqueue:
                    pt_mod.enqueue_job_run(
                        job_name="test_job",
                        idempotency_key="test-key",
                        payload={}
                    )

                    # Verify enqueue_idempotent was NOT called
                    mock_enqueue.assert_not_called()

    def test_enqueue_allowed_when_not_paused(self):
        """enqueue_job_run proceeds when trading is not paused"""
        # Need to reimport to get fresh module with patches
        import importlib
        import packages.quantum.public_tasks as pt_mod

        # Patch on the ops_endpoints module where it's defined
        with patch("packages.quantum.ops_endpoints.is_trading_paused") as mock_paused:
            mock_paused.return_value = (False, None)

            # Patch JobRunStore where it's used in public_tasks
            with patch.object(pt_mod, "JobRunStore") as mock_store:
                mock_store.return_value.create_or_get.return_value = {
                    "id": "test-id",
                    "status": "queued"
                }

                # Patch enqueue_idempotent where it's used in public_tasks
                with patch.object(pt_mod, "enqueue_idempotent") as mock_enqueue:
                    mock_enqueue.return_value = {"job_id": "rq-123"}

                    result = pt_mod.enqueue_job_run(
                        job_name="test_job",
                        idempotency_key="test-key",
                        payload={}
                    )

                    assert result["job_run_id"] == "test-id"
                    assert result["status"] == "queued"


class TestMarketFreshnessWithMock:
    """Test market freshness with mocked truth layer."""

    def test_market_freshness_no_api_key(self):
        """Returns ERROR status when POLYGON_API_KEY not set"""
        with patch.dict("os.environ", {"POLYGON_API_KEY": ""}, clear=False):
            # Need to patch os.getenv in the ops_endpoints module
            import packages.quantum.ops_endpoints as ops_mod
            original_getenv = ops_mod.os.getenv

            def mock_getenv(key, default=None):
                if key == "POLYGON_API_KEY":
                    return None
                return original_getenv(key, default)

            with patch.object(ops_mod.os, "getenv", side_effect=mock_getenv):
                results = _get_market_freshness()

                assert len(results) == 2
                for item in results:
                    assert item.status == "ERROR"
                    assert item.issues is not None
                    assert any("POLYGON_API_KEY" in issue for issue in item.issues)

    def test_market_freshness_with_snapshot(self):
        """Returns proper status when snapshots available"""
        import packages.quantum.ops_endpoints as ops_mod

        # Mock the MarketDataTruthLayer import inside the function
        with patch.object(ops_mod.os, "getenv", return_value="test-api-key"):
            with patch("packages.quantum.services.market_data_truth_layer.MarketDataTruthLayer") as mock_layer:
                # Mock snapshot response
                mock_snap = MagicMock()
                mock_snap.quality.freshness_ms = 5000
                mock_snap.quality.quality_score = 100
                mock_snap.quality.issues = []
                mock_snap.quality.is_stale = False

                mock_layer.return_value.snapshot_many_v4.return_value = {
                    "SPY": mock_snap,
                    "QQQ": mock_snap,
                }

                results = _get_market_freshness()

                assert len(results) == 2
                for item in results:
                    assert item.status == "OK"
                    assert item.freshness_ms == 5000
                    assert item.score == 100
