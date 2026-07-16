"""F-MIDDAY-POSITION-READ-FAILOPEN origin-to-top regressions.

An authoritative read failure is not a flat live book.  These tests keep a
successful empty scope/position result healthy while proving scan and executor
failures cannot reach selection, staging, or broker-facing code.
"""

import os
from types import SimpleNamespace
from unittest import mock

import pytest

from packages.quantum.jobs.runner import _classify_handler_return
from packages.quantum.risk.position_scope import LivePositionStateUnavailable
from packages.quantum.services import paper_autopilot_service as autopilot_mod


class _Response:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, client, table):
        self.client = client
        self.table_name = table

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def in_(self, *args, **kwargs):
        return self

    def execute(self):
        self.client.executes.append(self.table_name)
        if self.client.fail_on == self.table_name:
            raise RuntimeError(f"origin failure: {self.table_name}")
        if self.table_name == "paper_portfolios":
            return _Response(self.client.portfolios)
        if self.table_name == "paper_positions":
            return _Response(self.client.positions)
        return _Response([])


class _FakeClient:
    def __init__(self, *, fail_on=None, portfolios=None, positions=None):
        self.fail_on = fail_on
        self.portfolios = list(portfolios or [])
        self.positions = list(positions or [])
        self.tables = []
        self.executes = []

    def table(self, name):
        self.tables.append(name)
        return _Query(self, name)


def _service(client):
    svc = autopilot_mod.PaperAutopilotService.__new__(
        autopilot_mod.PaperAutopilotService
    )
    svc.client = client
    svc.config = {
        "enabled": True,
        "max_trades_per_day": 3,
        "min_score": 0.0,
        "close_policy": "close_all",
        "max_closes_per_day": 99,
    }
    return svc


class TestAuthoritativeReadContract:
    def test_no_live_portfolio_is_legitimate_empty(self):
        client = _FakeClient(portfolios=[])
        assert _service(client)._get_open_positions_for_risk_check("u") == []
        assert client.executes == ["paper_portfolios"]

    def test_successful_zero_positions_is_legitimate_empty(self):
        client = _FakeClient(
            portfolios=[{"id": "live", "routing_mode": "live_eligible"}],
            positions=[],
        )
        assert _service(client)._get_open_positions_for_risk_check("u") == []
        assert client.executes == ["paper_portfolios", "paper_positions"]

    @pytest.mark.parametrize("fail_on", ["paper_portfolios", "paper_positions"])
    def test_each_origin_failure_is_typed(self, fail_on):
        client = _FakeClient(
            fail_on=fail_on,
            portfolios=[{"id": "live", "routing_mode": "live_eligible"}],
        )
        with (
            mock.patch.object(autopilot_mod, "alert"),
            mock.patch.object(
                autopilot_mod, "_get_admin_supabase", return_value=object()
            ),
            pytest.raises(LivePositionStateUnavailable),
        ):
            _service(client)._get_open_positions_for_risk_check("u")


class TestExecutorOriginToTop:
    @pytest.mark.parametrize("fail_on", ["paper_portfolios", "paper_positions"])
    def test_position_read_failure_aborts_before_any_execution(self, fail_on):
        from packages.quantum.jobs.handlers import paper_auto_execute

        client = _FakeClient(
            fail_on=fail_on,
            portfolios=[{"id": "live", "routing_mode": "live_eligible"}],
        )
        with (
            mock.patch.dict(
                os.environ, {"PAPER_AUTOPILOT_ENABLED": "1"}, clear=False
            ),
            mock.patch.object(
                paper_auto_execute, "get_admin_client", return_value=client
            ),
            mock.patch(
                "packages.quantum.ops_endpoints.is_trading_paused",
                return_value=(False, ""),
            ),
            mock.patch(
                "packages.quantum.ops_endpoints.are_entries_paused",
                return_value=(False, ""),
            ),
            mock.patch(
                "packages.quantum.risk.staleness_gate.check_staleness_gate",
                return_value=SimpleNamespace(blocked=False),
            ),
            mock.patch.object(autopilot_mod, "alert"),
            mock.patch.object(
                autopilot_mod, "_get_admin_supabase", return_value=object()
            ),
            mock.patch.object(
                autopilot_mod.PaperAutopilotService, "_execute_per_cohort"
            ) as execute_cohorts,
            pytest.raises(paper_auto_execute.RetryableJobError),
        ):
            paper_auto_execute.run({"user_id": "user-1"})

        execute_cohorts.assert_not_called()
        assert "trade_suggestions" not in client.tables
        assert "paper_orders" not in client.tables


class TestScanTruthPropagation:
    def test_scheduled_suggestions_open_is_partial_on_read_abort(self):
        from packages.quantum.jobs.handlers import suggestions_open

        with (
            mock.patch.object(
                suggestions_open, "is_market_day", return_value=(True, "open")
            ),
            mock.patch.object(
                suggestions_open, "get_admin_client", return_value=object()
            ),
            mock.patch.object(suggestions_open, "ensure_default_strategy_exists"),
            mock.patch.object(
                suggestions_open,
                "load_strategy_config",
                return_value={"version": 1},
            ),
            mock.patch.object(
                suggestions_open, "_get_decision_context_class", return_value=None
            ),
            mock.patch.object(
                suggestions_open,
                "run_midday_cycle",
                side_effect=LivePositionStateUnavailable("db unavailable"),
            ),
            mock.patch(
                "packages.quantum.risk.staleness_gate.check_staleness_gate",
                return_value=SimpleNamespace(blocked=False),
            ),
            mock.patch("packages.quantum.observability.alerts.alert"),
        ):
            result = suggestions_open.run({"user_id": "user-1"})

        assert result["ok"] is False
        assert result["counts"]["failed"] == 1
        assert result["counts"]["errors"] == 1
        assert _classify_handler_return(result) == "partial"
        assert result["cycle_results"] == []

    def test_public_midday_route_is_partial_on_read_abort(self):
        from packages.quantum.jobs.handlers import midday_scan

        with (
            mock.patch.object(
                midday_scan, "get_admin_client", return_value=object()
            ),
            mock.patch.object(
                midday_scan, "get_active_user_ids", return_value=["user-1"]
            ),
            mock.patch.object(
                midday_scan,
                "run_midday_cycle",
                side_effect=LivePositionStateUnavailable("db unavailable"),
            ),
        ):
            result = midday_scan.run({})

        assert result["ok"] is False
        assert result["counts"] == {
            "processed": 0,
            "failed": 1,
            "errors": 1,
        }
        assert _classify_handler_return(result) == "partial"


class TestLoadBearingWiring:
    def test_typed_exception_precedes_legacy_broad_swallow(self):
        src = open(autopilot_mod.__file__, encoding="utf-8").read()
        typed = src.index("except LivePositionStateUnavailable:")
        broad = src.index("except Exception as cb_err:")
        assert typed < broad
        assert "entry execution aborted" in src

    def test_midday_fetch_raises_instead_of_returning_false_flat(self):
        from packages.quantum.services import workflow_orchestrator

        src = open(workflow_orchestrator.__file__, encoding="utf-8").read()
        start = src.rindex("    async def _fetch_positions():")
        end = src.index("    async def _compute_regime():", start)
        block = src[start:end]
        assert "raise LivePositionStateUnavailable" in block
        assert "midday live position state unavailable" in block
