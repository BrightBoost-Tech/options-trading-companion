import pytest
from unittest.mock import MagicMock, patch, ANY
from packages.quantum.jobs.handlers.iv_daily_refresh import run, JOB_NAME

class TestIVDailyRefreshHandler:

    @patch("packages.quantum.jobs.handlers.iv_daily_refresh.get_admin_client")
    @patch("packages.quantum.jobs.handlers.iv_daily_refresh.UniverseService")
    @patch("packages.quantum.jobs.handlers.iv_daily_refresh.MarketDataTruthLayer")
    @patch("packages.quantum.jobs.handlers.iv_daily_refresh.IVRepository")
    @patch("packages.quantum.jobs.handlers.iv_daily_refresh.IVPointService")
    def test_run_success(self, MockIVPointService, MockIVRepository, MockTruthLayer, MockUniverseService, mock_get_client):
        # Setup mocks
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_universe_svc = MockUniverseService.return_value
        # Use simple return value
        mock_universe_svc.get_scan_candidates.return_value = [{"symbol": "AAPL"}]

        mock_truth = MockTruthLayer.return_value
        mock_truth.normalize_symbol.side_effect = lambda x: x

        # Snapshot mock
        mock_truth.snapshot_many.return_value = {
            "AAPL": {
                "quote": {"mid": 150.0}
            }
        }

        # Chain mock
        mock_truth.option_chain.return_value = [
            {"expiry": "2023-01-01", "strike": 150, "right": "call", "greeks": {}, "iv": 0.2}
        ]

        # Computation mock
        MockIVPointService.compute_atm_iv_target_from_chain.return_value = {"iv_30d": 0.2}

        # Execute
        result = run({})

        # Verify
        assert result["status"] == "ok"
        # Since we added SPY, QQQ etc to list, count should be at least 1 (for AAPL if not filtered)
        # Actually SPY etc are added to the list.
        # stats['ok'] counts successful upserts.

        mock_universe_svc.get_scan_candidates.assert_called()

        # Verify that upsert was called
        MockIVRepository.return_value.upsert_iv_point.assert_called()

    @patch("packages.quantum.jobs.handlers.iv_daily_refresh.get_admin_client")
    def test_run_fail_universe(self, mock_get_client):
         mock_client = MagicMock()
         mock_get_client.return_value = mock_client

         with patch("packages.quantum.jobs.handlers.iv_daily_refresh.UniverseService", side_effect=Exception("Universe Error")):
             with pytest.raises(Exception) as exc:
                 run({})
             assert "Universe Error" in str(exc.value)
