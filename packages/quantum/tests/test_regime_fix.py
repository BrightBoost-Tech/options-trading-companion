import pytest
from unittest.mock import MagicMock
import sys

# Mock external deps
sys.modules['numpy'] = MagicMock()
sys.modules['logging'] = MagicMock()

# Mock imports
sys.modules['packages.quantum.services.iv_repository'] = MagicMock()
sys.modules['packages.quantum.services.iv_point_service'] = MagicMock()
sys.modules['packages.quantum.services.universe_service'] = MagicMock() # Mock UniverseService to avoid supabase import

# Mock Truth Layer module so we can check usage
mock_truth_module = MagicMock()
sys.modules['packages.quantum.services.market_data_truth_layer'] = mock_truth_module

# Mock factors (imported by RegimeEngineV3)
sys.modules['packages.quantum.analytics.factors'] = MagicMock()

# Mock common_enums to allow RegimeEngineV3 import to work
mock_enums = MagicMock()
sys.modules['packages.quantum.common_enums'] = mock_enums
mock_enums.RegimeState = MagicMock()

# Now import RegimeEngineV3
from packages.quantum.analytics.regime_engine_v3 import RegimeEngineV3

def test_regime_engine_wiring():
    mock_supabase = MagicMock()

    # Create a mock Truth Layer instance
    mock_truth_instance = MagicMock()
    # It must have daily_bars
    mock_truth_instance.daily_bars = MagicMock()

    # Pass it explicitly (like we did in the fix)
    mock_iv_repo = MagicMock()
    mock_iv_point = MagicMock()

    engine = RegimeEngineV3(
        supabase_client=mock_supabase,
        market_data=mock_truth_instance,
        iv_repository=mock_iv_repo,
        iv_point_service=mock_iv_point
    )

    # Assert
    assert engine.market_data == mock_truth_instance
    assert hasattr(engine.market_data, "daily_bars")

    # Verify that we didn't use PolygonService (if we were somehow testing the old code, this would fail if we passed PolygonService which doesn't have daily_bars)
    # But here we are testing that if we pass an object, it is used.

    # Test default instantiation logic (if market_data=None, it uses MarketDataTruthLayer())
    # Note: Since we mocked the module, MarketDataTruthLayer() inside RegimeEngineV3 will return a mock.
    mock_truth_module.MarketDataTruthLayer.return_value = mock_truth_instance

    engine_default = RegimeEngineV3(supabase_client=mock_supabase)
    assert engine_default.market_data == mock_truth_instance
