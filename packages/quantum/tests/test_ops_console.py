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
from datetime import datetime, timezone, timedelta

from packages.quantum.services.ops_health_service import (
    MarketDataFreshnessResult,
)

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
        mock_client = MagicMock()

        # Mock build_freshness_universe at service level
        with patch("packages.quantum.services.ops_health_service.build_freshness_universe") as mock_universe:
            mock_universe.return_value = ["SPY", "QQQ"]

            with patch.dict("os.environ", {"POLYGON_API_KEY": ""}, clear=False):
                # Need to patch os.getenv in the ops_endpoints module
                import packages.quantum.ops_endpoints as ops_mod
                original_getenv = ops_mod.os.getenv

                def mock_getenv(key, default=None):
                    if key == "POLYGON_API_KEY":
                        return None
                    return original_getenv(key, default)

                with patch.object(ops_mod.os, "getenv", side_effect=mock_getenv):
                    results, meta = _get_market_freshness(mock_client)

                    assert len(results) == 1  # Returns single ALL item now
                    assert results[0].status == "ERROR"
                    assert results[0].issues is not None
                    assert any("POLYGON_API_KEY" in issue for issue in results[0].issues)

    def test_market_freshness_with_snapshot(self):
        """Returns proper status when snapshots available"""
        mock_client = MagicMock()

        # Mock build_freshness_universe at service level
        with patch("packages.quantum.services.ops_health_service.build_freshness_universe") as mock_universe:
            mock_universe.return_value = ["SPY", "QQQ"]

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

                    results, meta = _get_market_freshness(mock_client)

                    assert len(results) == 2
                    for item in results:
                        assert item.status == "OK"
                        assert item.freshness_ms == 5000
                        assert item.score == 100


# =============================================================================
# Phase 1 Gap-Closure Tests: ops_health_service
# =============================================================================

from packages.quantum.services.ops_health_service import (
    DataFreshnessResult,
    ExpectedJob,
    compute_data_freshness,
    get_expected_jobs,
    get_recent_failures,
    get_suggestions_stats,
    send_ops_alert,
    DATA_STALE_THRESHOLD_MINUTES,
)


class TestComputeDataFreshness:
    """Tests for compute_data_freshness function."""

    def test_freshness_from_job_runs_fresh(self):
        """Returns fresh data when recent job_runs exist."""
        mock_client = MagicMock()

        # Mock job_runs query returning recent success
        mock_now = datetime.now(timezone.utc)
        recent_time = (mock_now - timedelta(minutes=5)).isoformat()

        mock_client.table.return_value.select.return_value.in_.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"finished_at": recent_time, "job_name": "suggestions_close"}]
        )

        result = compute_data_freshness(mock_client)

        assert result.is_stale is False
        assert result.source == "job_runs"
        assert result.as_of is not None
        assert result.age_seconds < 600  # Less than 10 minutes

    def test_freshness_from_job_runs_stale(self):
        """Returns stale when job_runs are old."""
        mock_client = MagicMock()

        # Mock job_runs query returning old success (> 30 min)
        mock_now = datetime.now(timezone.utc)
        old_time = (mock_now - timedelta(minutes=60)).isoformat()

        mock_client.table.return_value.select.return_value.in_.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"finished_at": old_time, "job_name": "suggestions_open"}]
        )

        result = compute_data_freshness(mock_client)

        assert result.is_stale is True
        assert result.source == "job_runs"
        assert result.reason is not None

    def test_freshness_fallback_to_trade_suggestions(self):
        """Falls back to trade_suggestions when no job_runs."""
        mock_client = MagicMock()

        # Mock job_runs returning empty
        mock_job_runs = MagicMock()
        mock_job_runs.data = []

        # Mock trade_suggestions returning recent data
        mock_now = datetime.now(timezone.utc)
        recent_time = (mock_now - timedelta(minutes=10)).isoformat()
        mock_suggestions = MagicMock()
        mock_suggestions.data = [{"created_at": recent_time}]

        def table_side_effect(name):
            mock_table = MagicMock()
            if name == "job_runs":
                mock_table.select.return_value.in_.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_job_runs
            else:
                mock_table.select.return_value.order.return_value.limit.return_value.execute.return_value = mock_suggestions
            return mock_table

        mock_client.table.side_effect = table_side_effect

        result = compute_data_freshness(mock_client)

        assert result.source == "trade_suggestions"
        assert result.is_stale is False

    def test_freshness_no_data_source_found(self):
        """Returns stale with reason when no data sources found."""
        mock_client = MagicMock()

        # Mock both queries returning empty
        mock_empty = MagicMock()
        mock_empty.data = []

        mock_client.table.return_value.select.return_value.in_.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = mock_empty
        mock_client.table.return_value.select.return_value.order.return_value.limit.return_value.execute.return_value = mock_empty

        result = compute_data_freshness(mock_client)

        assert result.is_stale is True
        assert result.source == "none"
        assert result.reason == "no_data_source_found"
        assert result.as_of is None


class TestGetExpectedJobs:
    """Tests for get_expected_jobs function."""

    def test_job_ok_when_recent(self):
        """Returns ok status when job ran recently."""
        mock_client = MagicMock()

        mock_now = datetime.now(timezone.utc)
        recent_time = (mock_now - timedelta(hours=2)).isoformat()

        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"finished_at": recent_time, "status": "succeeded"}]
        )

        results = get_expected_jobs(mock_client)

        # Should have all expected jobs
        assert len(results) == 4
        suggestions_close = next(j for j in results if j.name == "suggestions_close")
        assert suggestions_close.status == "ok"

    def test_job_late_when_stale(self):
        """Returns late status when daily job > 26 hours old."""
        mock_client = MagicMock()

        mock_now = datetime.now(timezone.utc)
        old_time = (mock_now - timedelta(hours=30)).isoformat()

        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"finished_at": old_time, "status": "succeeded"}]
        )

        results = get_expected_jobs(mock_client)

        suggestions_close = next(j for j in results if j.name == "suggestions_close")
        assert suggestions_close.status == "late"

    def test_job_never_run(self):
        """Returns never_run when no successful runs exist."""
        mock_client = MagicMock()

        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )

        results = get_expected_jobs(mock_client)

        for job in results:
            assert job.status == "never_run"
            assert job.last_success_at is None


class TestSendOpsAlert:
    """Tests for send_ops_alert function."""

    def test_alert_skipped_when_no_webhook(self):
        """Returns False when no webhook URL configured."""
        with patch.dict("os.environ", {"OPS_ALERT_WEBHOOK_URL": ""}, clear=False):
            result = send_ops_alert("test_alert", "Test message", webhook_url=None)
            assert result is False

    def test_alert_sent_successfully(self):
        """Returns True when webhook responds with 200."""
        import requests as req_module
        with patch.object(req_module, "post") as mock_post:
            mock_post.return_value.status_code = 200

            result = send_ops_alert(
                "data_stale",
                "Test alert message",
                {"detail": "test"},
                webhook_url="https://hooks.example.com/test"
            )

            assert result is True
            mock_post.assert_called_once()

    def test_alert_handles_webhook_failure(self):
        """Returns False and doesn't raise when webhook fails."""
        import requests as req_module
        with patch.object(req_module, "post") as mock_post:
            mock_post.side_effect = Exception("Connection failed")

            result = send_ops_alert(
                "job_late",
                "Test alert",
                webhook_url="https://hooks.example.com/test"
            )

            assert result is False  # Graceful failure


class TestOpsHealthCheckHandler:
    """Tests for ops_health_check job handler."""

    def test_handler_returns_expected_structure(self):
        """Handler returns dict with ok, issues_found, alerts_sent, health_snapshot."""
        from packages.quantum.jobs.handlers.ops_health_check import run

        with patch("packages.quantum.jobs.handlers.ops_health_check.get_admin_client") as mock_client:
            mock_client.return_value = MagicMock()

            # Mock all service calls
            with patch("packages.quantum.jobs.handlers.ops_health_check.compute_data_freshness") as mock_fresh:
                mock_fresh.return_value = DataFreshnessResult(
                    is_stale=False,
                    as_of=datetime.now(timezone.utc),
                    age_seconds=100,
                    reason=None,
                    source="job_runs"
                )

                with patch("packages.quantum.jobs.handlers.ops_health_check.get_expected_jobs") as mock_jobs:
                    mock_jobs.return_value = [
                        ExpectedJob("suggestions_close", "daily", datetime.now(timezone.utc), "ok")
                    ]

                    with patch("packages.quantum.jobs.handlers.ops_health_check.get_recent_failures") as mock_fail:
                        mock_fail.return_value = []

                        with patch("packages.quantum.jobs.handlers.ops_health_check.get_suggestions_stats") as mock_stats:
                            mock_stats.return_value = {"last_cycle_date": "2026-01-20", "count_last_cycle": 5}

                            with patch("packages.quantum.jobs.handlers.ops_health_check.get_integrity_stats") as mock_int:
                                mock_int.return_value = {"recent_incidents": 0, "last_incident_at": None}

                                with patch("packages.quantum.jobs.handlers.ops_health_check.AuditLogService"):
                                    result = run({"timestamp": datetime.now().isoformat(), "force": False})

                                    assert "ok" in result
                                    assert "issues_found" in result
                                    assert "alerts_sent" in result
                                    assert "health_snapshot" in result
                                    assert "timing_ms" in result

    def test_handler_sends_alert_on_stale_data(self):
        """Handler sends alert when data is stale (Phase 1.1 version)."""
        from packages.quantum.jobs.handlers.ops_health_check import run

        with patch("packages.quantum.jobs.handlers.ops_health_check.get_admin_client") as mock_client:
            mock_client.return_value = MagicMock()

            # Phase 1.1: Mock build_freshness_universe
            with patch("packages.quantum.jobs.handlers.ops_health_check.build_freshness_universe") as mock_universe:
                mock_universe.return_value = ["SPY", "QQQ"]

                # Phase 1.1: Mock compute_market_data_freshness (stale)
                with patch("packages.quantum.jobs.handlers.ops_health_check.compute_market_data_freshness") as mock_market_fresh:
                    mock_market_fresh.return_value = MarketDataFreshnessResult(
                        is_stale=True,
                        as_of=datetime.now(timezone.utc) - timedelta(hours=1),
                        age_seconds=3600,
                        universe_size=2,
                        stale_symbols=["SPY"],
                        source="MarketDataTruthLayer",
                        reason="stale_symbols"
                    )

                    # Also mock job-based freshness (for backwards compat check)
                    with patch("packages.quantum.jobs.handlers.ops_health_check.compute_data_freshness") as mock_fresh:
                        mock_fresh.return_value = DataFreshnessResult(
                            is_stale=False,
                            as_of=datetime.now(timezone.utc),
                            age_seconds=60,
                            reason="ok",
                            source="job_runs"
                        )

                        with patch("packages.quantum.jobs.handlers.ops_health_check.get_expected_jobs") as mock_jobs:
                            mock_jobs.return_value = []

                            with patch("packages.quantum.jobs.handlers.ops_health_check.get_recent_failures") as mock_fail:
                                mock_fail.return_value = []

                                with patch("packages.quantum.jobs.handlers.ops_health_check.get_suggestions_stats") as mock_stats:
                                    mock_stats.return_value = {"last_cycle_date": None, "count_last_cycle": 0}

                                    with patch("packages.quantum.jobs.handlers.ops_health_check.get_integrity_stats") as mock_int:
                                        mock_int.return_value = {"recent_incidents": 0, "last_incident_at": None}

                                        # Phase 1.1: Mock alert functions
                                        with patch("packages.quantum.jobs.handlers.ops_health_check.get_alert_fingerprint") as mock_fp:
                                            mock_fp.return_value = "abc123"

                                            with patch("packages.quantum.jobs.handlers.ops_health_check.should_suppress_alert") as mock_suppress:
                                                mock_suppress.return_value = (False, None)  # Not suppressed

                                                with patch("packages.quantum.jobs.handlers.ops_health_check.send_ops_alert_v2") as mock_alert:
                                                    mock_alert.return_value = {"sent": True, "suppressed_reason": None}

                                                    with patch("packages.quantum.jobs.handlers.ops_health_check.AuditLogService"):
                                                        result = run({"timestamp": datetime.now().isoformat()})

                                                        # Verify alert was attempted for stale data
                                                        mock_alert.assert_called()
                                                        assert "data_stale" in result["alerts_sent"]


class TestPauseAuditEvent:
    """Test that pause/resume writes audit events."""

    def test_pause_code_contains_audit_call(self):
        """Verify ops_endpoints pause function contains audit logging code."""
        import inspect
        import packages.quantum.ops_endpoints as ops_mod

        # Get the source of the pause endpoint
        source = inspect.getsource(ops_mod.set_pause_state)

        # Verify audit logging code is present
        assert "AuditLogService" in source
        assert "log_audit_event" in source
        assert "ops." in source  # ops.trading.paused or similar event name


class TestOpsHealthEndpoint:
    """Tests for GET /ops/health endpoint."""

    def test_ops_health_response_model_structure(self):
        """OpsHealthResponse has all required fields."""
        from packages.quantum.ops_endpoints import (
            OpsHealthResponse,
            DataFreshnessResponse,
            JobsResponse,
            ExpectedJobResponse,
            IntegrityResponse,
            SuggestionsStatsResponse,
        )

        # Create a valid response using Pydantic models
        response = OpsHealthResponse(
            now=datetime.now(timezone.utc),
            paused=False,
            pause_reason=None,
            data_freshness=DataFreshnessResponse(
                is_stale=False,
                stale_reason=None,
                as_of=datetime.now(timezone.utc),
                age_seconds=100,
                source="job_runs"
            ),
            jobs=JobsResponse(
                expected=[ExpectedJobResponse(name="suggestions_close", cadence="daily", last_success_at=None, status="ok")],
                recent_failures=[]
            ),
            integrity=IntegrityResponse(recent_incidents=0, last_incident_at=None),
            suggestions=SuggestionsStatsResponse(last_cycle_date="2026-01-20", count_last_cycle=5)
        )

        assert response.paused is False
        assert response.data_freshness.is_stale is False
        assert len(response.jobs.expected) == 1

    def test_ops_health_returns_graceful_nulls(self):
        """OpsHealthResponse handles null values gracefully."""
        from packages.quantum.ops_endpoints import (
            OpsHealthResponse,
            DataFreshnessResponse,
            JobsResponse,
            IntegrityResponse,
            SuggestionsStatsResponse,
        )

        response = OpsHealthResponse(
            now=datetime.now(timezone.utc),
            paused=True,
            pause_reason="Testing",
            data_freshness=DataFreshnessResponse(
                is_stale=True,
                stale_reason="no_data_source_found",
                as_of=None,
                age_seconds=None,
                source="none"
            ),
            jobs=JobsResponse(expected=[], recent_failures=[]),
            integrity=IntegrityResponse(recent_incidents=0, last_incident_at=None),
            suggestions=SuggestionsStatsResponse(last_cycle_date=None, count_last_cycle=0)
        )

        assert response.data_freshness.as_of is None
        assert response.suggestions.last_cycle_date is None


# =============================================================================
# Phase 1.1 Tests: Mode Audit + Expanded Freshness + Cooldown + Severity
# =============================================================================

from packages.quantum.services.ops_health_service import (
    build_freshness_universe,
    compute_market_data_freshness,
    get_alert_fingerprint,
    should_suppress_alert,
    send_ops_alert_v2,
    MarketDataFreshnessResult,
    ALERT_SEVERITY,
)


class TestModeAuditEvent:
    """Test POST /ops/mode writes audit event."""

    def test_mode_code_contains_audit_call(self):
        """Verify ops_endpoints mode function contains audit logging code."""
        import inspect
        import packages.quantum.ops_endpoints as ops_mod

        # Get the source of the mode endpoint
        source = inspect.getsource(ops_mod.set_mode)

        # Verify audit logging code is present
        assert "AuditLogService" in source
        assert "log_audit_event" in source
        assert "ops.mode.changed" in source
        assert "previous_mode" in source


class TestExpandedFreshnessUniverse:
    """Tests for build_freshness_universe function."""

    def test_universe_includes_baseline(self):
        """Universe always includes SPY, QQQ."""
        mock_client = MagicMock()

        # Mock empty results for both queries
        mock_client.table.return_value.select.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        mock_client.table.return_value.select.return_value.gte.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

        universe = build_freshness_universe(mock_client)

        assert "SPY" in universe
        assert "QQQ" in universe

    def test_universe_adds_holdings(self):
        """Holdings tickers added to universe."""
        mock_client = MagicMock()

        def table_side_effect(name):
            mock_table = MagicMock()
            if name == "positions":
                mock_table.select.return_value.limit.return_value.execute.return_value = MagicMock(
                    data=[{"symbol": "AAPL"}, {"symbol": "MSFT"}]
                )
            else:
                mock_table.select.return_value.gte.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
            return mock_table

        mock_client.table.side_effect = table_side_effect

        universe = build_freshness_universe(mock_client)

        assert "AAPL" in universe
        assert "MSFT" in universe
        assert "SPY" in universe
        assert "QQQ" in universe

    def test_universe_adds_suggestions(self):
        """Recent suggestion underlyings added to universe."""
        mock_client = MagicMock()

        def table_side_effect(name):
            mock_table = MagicMock()
            if name == "positions":
                mock_table.select.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
            else:
                mock_table.select.return_value.gte.return_value.limit.return_value.execute.return_value = MagicMock(
                    data=[{"ticker": "NVDA"}, {"ticker": "AMD"}]
                )
            return mock_table

        mock_client.table.side_effect = table_side_effect

        universe = build_freshness_universe(mock_client)

        assert "NVDA" in universe
        assert "AMD" in universe

    def test_universe_capped_at_max(self):
        """Universe capped at max_symbols."""
        mock_client = MagicMock()

        # Create many symbols
        many_positions = [{"symbol": f"SYM{i}"} for i in range(50)]

        def table_side_effect(name):
            mock_table = MagicMock()
            if name == "positions":
                mock_table.select.return_value.limit.return_value.execute.return_value = MagicMock(data=many_positions)
            else:
                mock_table.select.return_value.gte.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
            return mock_table

        mock_client.table.side_effect = table_side_effect

        universe = build_freshness_universe(mock_client, max_symbols=10)

        assert len(universe) == 10

    def test_universe_fallback_on_error(self):
        """Falls back to SPY/QQQ on query errors."""
        mock_client = MagicMock()
        mock_client.table.side_effect = Exception("DB error")

        universe = build_freshness_universe(mock_client)

        # Should still have baseline
        assert "SPY" in universe
        assert "QQQ" in universe


class TestMarketDataFreshnessResult:
    """Tests for MarketDataFreshnessResult dataclass."""

    def test_missing_api_key_returns_stale(self):
        """Missing POLYGON_API_KEY returns stale result."""
        with patch.dict("os.environ", {"POLYGON_API_KEY": ""}, clear=False):
            # Need to patch at module level where it's checked
            import packages.quantum.services.ops_health_service as service_mod
            original_getenv = service_mod.os.getenv

            def mock_getenv(key, default=None):
                if key == "POLYGON_API_KEY":
                    return None
                return original_getenv(key, default)

            with patch.object(service_mod.os, "getenv", side_effect=mock_getenv):
                result = compute_market_data_freshness(["SPY", "QQQ"])

                assert result.is_stale is True
                assert result.source == "missing_api_key"
                assert result.reason == "missing_api_key"


class TestAlertFingerprint:
    """Tests for alert fingerprint generation."""

    def test_same_inputs_same_fingerprint(self):
        """Same inputs produce same fingerprint."""
        fp1 = get_alert_fingerprint("data_stale", {"symbols": ["SPY", "QQQ"]})
        fp2 = get_alert_fingerprint("data_stale", {"symbols": ["SPY", "QQQ"]})

        assert fp1 == fp2

    def test_different_inputs_different_fingerprint(self):
        """Different inputs produce different fingerprints."""
        fp1 = get_alert_fingerprint("data_stale", {"symbols": ["SPY"]})
        fp2 = get_alert_fingerprint("data_stale", {"symbols": ["QQQ"]})

        assert fp1 != fp2

    def test_different_alert_types_different_fingerprint(self):
        """Different alert types produce different fingerprints."""
        fp1 = get_alert_fingerprint("data_stale", {"symbols": ["SPY"]})
        fp2 = get_alert_fingerprint("job_late", {"symbols": ["SPY"]})

        assert fp1 != fp2


class TestAlertCooldown:
    """Tests for alert cooldown suppression."""

    def test_cooldown_suppresses_repeat_alert(self):
        """Same fingerprint within cooldown is suppressed."""
        mock_client = MagicMock()

        # Simulate recent job_run with matching fingerprint
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{
                "result": {"alert_fingerprints": ["abc123"]},
                "finished_at": datetime.now(timezone.utc).isoformat()
            }]
        )

        suppressed, last_sent = should_suppress_alert(mock_client, "abc123", cooldown_minutes=30)

        assert suppressed is True
        assert last_sent is not None

    def test_different_fingerprint_not_suppressed(self):
        """Different fingerprint not suppressed."""
        mock_client = MagicMock()

        # Simulate recent job_run with different fingerprint
        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{
                "result": {"alert_fingerprints": ["xyz789"]},
                "finished_at": datetime.now(timezone.utc).isoformat()
            }]
        )

        suppressed, last_sent = should_suppress_alert(mock_client, "abc123", cooldown_minutes=30)

        assert suppressed is False
        assert last_sent is None

    def test_no_recent_jobs_not_suppressed(self):
        """No recent jobs means no suppression."""
        mock_client = MagicMock()

        mock_client.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )

        suppressed, last_sent = should_suppress_alert(mock_client, "abc123", cooldown_minutes=30)

        assert suppressed is False


class TestAlertSeverity:
    """Tests for severity-based alert filtering."""

    def test_alert_severity_mapping_exists(self):
        """ALERT_SEVERITY mapping has expected entries."""
        assert "data_stale" in ALERT_SEVERITY
        assert "job_late" in ALERT_SEVERITY
        assert "job_failure" in ALERT_SEVERITY

        assert ALERT_SEVERITY["data_stale"] == "error"
        assert ALERT_SEVERITY["job_late"] == "warning"

    def test_warning_filtered_when_min_error(self):
        """Warning alerts filtered when min_severity=error."""
        result = send_ops_alert_v2(
            "job_late",  # warning severity
            "Test message",
            severity="warning",
            min_severity="error",
            webhook_url="https://hooks.example.com/test"
        )

        assert result["sent"] is False
        assert result["suppressed_reason"] == "below_min_severity"

    def test_error_sent_when_min_error(self):
        """Error alerts pass severity filter when min_severity=error."""
        import requests as req_module
        with patch.object(req_module, "post") as mock_post:
            mock_post.return_value.status_code = 200

            result = send_ops_alert_v2(
                "data_stale",  # error severity
                "Test message",
                severity="error",
                min_severity="error",
                webhook_url="https://hooks.example.com/test"
            )

            assert result["sent"] is True
            mock_post.assert_called_once()

    def test_no_webhook_returns_suppressed(self):
        """No webhook URL returns suppressed reason."""
        with patch.dict("os.environ", {"OPS_ALERT_WEBHOOK_URL": ""}, clear=False):
            result = send_ops_alert_v2(
                "data_stale",
                "Test message",
                min_severity="warning",
                webhook_url=None
            )

            assert result["sent"] is False
            assert result["suppressed_reason"] == "no_webhook"


# =============================================================================
# Phase 1.1.1 Tests: Dashboard Truth Alignment
# =============================================================================

from packages.quantum.services.ops_health_service import (
    MarketFreshnessBlock,
    compute_market_freshness_block,
    get_integrity_stats,
)


class TestMarketFreshnessBlock:
    """Tests for MarketFreshnessBlock dataclass and compute function."""

    def test_block_has_required_fields(self):
        """MarketFreshnessBlock has all required fields."""
        block = MarketFreshnessBlock(
            status="OK",
            as_of="2026-01-20T12:00:00+00:00",
            age_seconds=60.0,
            universe_size=5,
            symbols_checked=["SPY", "QQQ", "AAPL"],
            stale_symbols=[],
            issues=[]
        )

        assert block.status == "OK"
        assert block.universe_size == 5
        assert len(block.symbols_checked) == 3
        assert block.stale_symbols == []

    def test_compute_block_missing_api_key(self):
        """Returns ERROR status when API key missing."""
        mock_client = MagicMock()

        # Mock empty holdings/suggestions
        mock_client.table.return_value.select.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )
        mock_client.table.return_value.select.return_value.gte.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )

        with patch.dict("os.environ", {"POLYGON_API_KEY": ""}, clear=False):
            block = compute_market_freshness_block(mock_client)

            assert block.status == "ERROR"
            assert "POLYGON_API_KEY not configured" in block.issues


class TestExpandedFreshnessDashboard:
    """Tests that dashboard uses expanded freshness universe."""

    def test_dashboard_freshness_includes_holdings(self):
        """Dashboard freshness builds universe from holdings."""
        from packages.quantum.ops_endpoints import _get_market_freshness, FreshnessItem

        mock_client = MagicMock()

        # Mock build_freshness_universe at service level to return expanded list
        with patch("packages.quantum.services.ops_health_service.build_freshness_universe") as mock_build:
            mock_build.return_value = ["AAPL", "MSFT", "QQQ", "SPY"]  # Expanded universe

            with patch.dict("os.environ", {"POLYGON_API_KEY": "test_key"}, clear=False):
                import packages.quantum.ops_endpoints as ops_mod

                with patch.object(ops_mod.os, "getenv", return_value="test_key"):
                    with patch("packages.quantum.services.market_data_truth_layer.MarketDataTruthLayer") as mock_layer_class:
                        # Mock snapshot_many_v4 to return data for all symbols
                        mock_layer = MagicMock()
                        mock_layer_class.return_value = mock_layer

                        mock_snap = MagicMock()
                        mock_snap.quality.freshness_ms = 5000
                        mock_snap.quality.quality_score = 95
                        mock_snap.quality.issues = []
                        mock_snap.quality.is_stale = False

                        mock_layer.snapshot_many_v4.return_value = {
                            "SPY": mock_snap,
                            "QQQ": mock_snap,
                            "AAPL": mock_snap,
                            "MSFT": mock_snap,
                        }

                        freshness_items, meta = _get_market_freshness(mock_client)

                        # Should have expanded universe
                        assert meta.universe_size == 4  # SPY, QQQ, AAPL, MSFT
                        symbols = [item.symbol for item in freshness_items]
                        assert "AAPL" in symbols
                        assert "MSFT" in symbols

    def test_freshness_meta_tracks_stale_count(self):
        """FreshnessMeta correctly tracks stale symbol count."""
        from packages.quantum.ops_endpoints import FreshnessMeta

        meta = FreshnessMeta(
            universe_size=10,
            total_stale_count=3,
            stale_symbols=["AAPL", "MSFT", "GOOGL"]
        )

        assert meta.universe_size == 10
        assert meta.total_stale_count == 3
        assert len(meta.stale_symbols) == 3


class TestIntegrityStatsReal:
    """Tests for real integrity stats from decision_audit_events."""

    def test_integrity_stats_returns_nonzero_with_events(self):
        """Returns actual count when audit events exist."""
        mock_client = MagicMock()

        # Mock query returning integrity incidents
        mock_client.table.return_value.select.return_value.in_.return_value.gte.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[
                {
                    "id": "123",
                    "event_name": "integrity_incident",
                    "created_at": "2026-01-20T12:00:00+00:00",
                    "payload": {"type": "missing_legs_fingerprint"}
                },
                {
                    "id": "456",
                    "event_name": "integrity_incident_linked",
                    "created_at": "2026-01-20T11:00:00+00:00",
                    "payload": {"type": "missing_legs_fingerprint_linked"}
                }
            ]
        )

        stats = get_integrity_stats(mock_client, hours=24)

        assert stats["recent_incidents_24h"] == 2
        assert stats["last_incident_at"] == "2026-01-20T12:00:00+00:00"

    def test_integrity_stats_returns_top_types(self):
        """Returns breakdown of incident types."""
        mock_client = MagicMock()

        # Mock query returning multiple incidents of same type
        mock_client.table.return_value.select.return_value.in_.return_value.gte.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[
                {"id": "1", "event_name": "integrity_incident", "created_at": "2026-01-20T12:00:00+00:00", "payload": {"type": "missing_legs_fingerprint"}},
                {"id": "2", "event_name": "integrity_incident", "created_at": "2026-01-20T11:00:00+00:00", "payload": {"type": "missing_legs_fingerprint"}},
                {"id": "3", "event_name": "integrity_incident", "created_at": "2026-01-20T10:00:00+00:00", "payload": {"type": "data_mismatch"}},
            ]
        )

        stats = get_integrity_stats(mock_client, hours=24)

        assert stats["recent_incidents_24h"] == 3
        assert len(stats["top_incident_types_24h"]) >= 1
        # missing_legs_fingerprint should be first (count=2)
        assert stats["top_incident_types_24h"][0]["event_name"] == "missing_legs_fingerprint"
        assert stats["top_incident_types_24h"][0]["count"] == 2

    def test_integrity_stats_handles_empty_table(self):
        """Gracefully returns zeros when no events."""
        mock_client = MagicMock()

        mock_client.table.return_value.select.return_value.in_.return_value.gte.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )

        stats = get_integrity_stats(mock_client, hours=24)

        assert stats["recent_incidents_24h"] == 0
        assert stats["last_incident_at"] is None
        assert stats["top_incident_types_24h"] == []

    def test_integrity_stats_handles_query_error(self):
        """Returns zeros with diagnostic on query error."""
        mock_client = MagicMock()

        mock_client.table.return_value.select.return_value.in_.return_value.gte.return_value.order.return_value.limit.return_value.execute.side_effect = Exception("DB error")

        stats = get_integrity_stats(mock_client, hours=24)

        assert stats["recent_incidents_24h"] == 0
        assert stats["last_incident_at"] is None
        assert "diagnostic" in stats


class TestNoRegressionDeterminism:
    """Guard tests ensuring banned terms don't appear."""

    def test_canonical_jobs_no_regression(self):
        """CANONICAL_JOB_NAMES doesn't include regression/determinism."""
        from packages.quantum.ops_endpoints import CANONICAL_JOB_NAMES

        for job in CANONICAL_JOB_NAMES:
            assert "regression" not in job.lower(), f"Found 'regression' in {job}"
            assert "determinism" not in job.lower(), f"Found 'determinism' in {job}"

    def test_expected_jobs_no_regression(self):
        """EXPECTED_JOBS doesn't include regression/determinism."""
        from packages.quantum.services.ops_health_service import EXPECTED_JOBS

        for job_name, cadence in EXPECTED_JOBS:
            assert "regression" not in job_name.lower(), f"Found 'regression' in {job_name}"
            assert "determinism" not in job_name.lower(), f"Found 'determinism' in {job_name}"

    def test_alert_severity_no_regression(self):
        """ALERT_SEVERITY keys don't include regression/determinism."""
        for alert_type in ALERT_SEVERITY.keys():
            assert "regression" not in alert_type.lower()
            assert "determinism" not in alert_type.lower()
