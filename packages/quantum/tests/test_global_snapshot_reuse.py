import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from packages.quantum.options_scanner import scan_for_opportunities
from packages.quantum.analytics.regime_engine_v3 import GlobalRegimeSnapshot, RegimeState

def test_scan_reuses_global_snapshot():
    # Mock services
    mock_supabase = MagicMock()

    # Mock dependencies inside scan_for_opportunities
    with patch('packages.quantum.options_scanner.UniverseService'), \
         patch('packages.quantum.options_scanner.StrategySelector'), \
         patch('packages.quantum.options_scanner.PolygonService'), \
         patch('packages.quantum.options_scanner.ExecutionService'), \
         patch('packages.quantum.options_scanner.MarketDataTruthLayer'), \
         patch('packages.quantum.options_scanner.RegimeEngineV3') as MockRegimeEngine, \
         patch('packages.quantum.options_scanner.concurrent.futures.ThreadPoolExecutor') as MockExecutor:

        # Setup mock regime engine
        mock_engine_instance = MockRegimeEngine.return_value

        # Mock executor to just return empty list and avoid threading in test
        mock_executor_instance = MockExecutor.return_value
        mock_executor_instance.__enter__.return_value = mock_executor_instance
        # Don't mock submit/as_completed too deeply, just enough so it doesn't crash if called
        # But since we provide no symbols (or empty list), it might skip loop.

        # Create a fake snapshot to pass in
        fake_snapshot = MagicMock(spec=GlobalRegimeSnapshot)
        fake_snapshot.state = RegimeState.NORMAL
        fake_snapshot.to_dict.return_value = {"state": "NORMAL"}

        # Run scanner with the snapshot, empty symbols to be fast
        scan_for_opportunities(
            symbols=[],
            supabase_client=mock_supabase,
            global_snapshot=fake_snapshot
        )

        # Assert compute_global_snapshot was NOT called on the engine
        mock_engine_instance.compute_global_snapshot.assert_not_called()

def test_scan_computes_snapshot_if_missing():
    # Mock services
    mock_supabase = MagicMock()

    with patch('packages.quantum.options_scanner.UniverseService'), \
         patch('packages.quantum.options_scanner.StrategySelector'), \
         patch('packages.quantum.options_scanner.PolygonService'), \
         patch('packages.quantum.options_scanner.ExecutionService'), \
         patch('packages.quantum.options_scanner.MarketDataTruthLayer'), \
         patch('packages.quantum.options_scanner.RegimeEngineV3') as MockRegimeEngine:

        mock_engine_instance = MockRegimeEngine.return_value
        # Mock compute to return something valid
        fake_snapshot = MagicMock(spec=GlobalRegimeSnapshot)
        fake_snapshot.state = RegimeState.NORMAL
        mock_engine_instance.compute_global_snapshot.return_value = fake_snapshot

        # Run scanner WITHOUT snapshot
        scan_for_opportunities(
            symbols=[],
            supabase_client=mock_supabase,
            global_snapshot=None
        )

        # Assert compute_global_snapshot WAS called
        mock_engine_instance.compute_global_snapshot.assert_called_once()

def test_orchestrator_passes_snapshot():
    # Mock dependencies for run_midday_cycle
    with patch('packages.quantum.services.workflow_orchestrator.scan_for_opportunities') as mock_scan, \
         patch('packages.quantum.services.workflow_orchestrator.RegimeEngineV3') as MockRegimeEngine, \
         patch('packages.quantum.services.workflow_orchestrator.CashService') as MockCashService, \
         patch('packages.quantum.services.workflow_orchestrator.RiskBudgetEngine') as MockRiskEngine, \
         patch('packages.quantum.services.workflow_orchestrator.MarketDataTruthLayer'), \
         patch('packages.quantum.services.workflow_orchestrator.IVRepository'), \
         patch('packages.quantum.services.workflow_orchestrator.IVPointService'), \
         patch('packages.quantum.services.workflow_orchestrator.AnalyticsService'):

         # Setup
         mock_supabase = MagicMock()
         mock_engine = MockRegimeEngine.return_value
         fake_snap = MagicMock(spec=GlobalRegimeSnapshot)
         fake_snap.state = RegimeState.NORMAL
         mock_engine.compute_global_snapshot.return_value = fake_snap

         # Mock cash service
         mock_cash = MockCashService.return_value
         from unittest.mock import AsyncMock
         mock_cash.get_deployable_capital = AsyncMock(return_value=10000.0)

         # Mock risk engine to allow continuation
         mock_risk = MockRiskEngine.return_value
         mock_risk.compute.return_value = {
             "remaining": 1000,
             "current_usage": 0,
             "max_allocation": 2000,
             "regime": "NORMAL"
         }

         # Import inside test to avoid early import issues if any
         from packages.quantum.services.workflow_orchestrator import run_midday_cycle
         import asyncio

         # Mock supabase table execute calls
         mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []

         # Run orchestrator
         asyncio.run(run_midday_cycle(mock_supabase, "user_123"))

         # Assert scan_for_opportunities called with global_snapshot=fake_snap
         mock_scan.assert_called_once()
         args, kwargs = mock_scan.call_args
         assert kwargs.get('global_snapshot') == fake_snap
