import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
import numpy as np
from packages.quantum.analytics.regime_engine_v3 import RegimeEngineV3, RegimeState, GlobalRegimeSnapshot

# Fixtures
@pytest.fixture
def mock_market_data():
    mock = Mock()
    # Mock SPY bars for Global Snapshot
    # 60 days of data
    mock.get_historical_prices.return_value = [
        {'close': 100 + i, 'date': (datetime.now() - timedelta(days=60-i)).isoformat()}
        for i in range(60)
    ]
    return mock

@pytest.fixture
def mock_iv_repo():
    mock = Mock()
    mock.get_iv_context.return_value = {'iv_rank': 50.0, 'current_iv': 0.15}
    return mock

@pytest.fixture
def mock_iv_point_service():
    mock = Mock()
    mock.get_latest_point.return_value = {'skew_25d': 0.0, 'term_slope': 0.0}
    return mock

@pytest.fixture
def engine(mock_market_data, mock_iv_repo, mock_iv_point_service):
    return RegimeEngineV3(mock_market_data, mock_iv_repo, mock_iv_point_service)

# Tests
def test_compute_global_snapshot_normal(engine):
    snap = engine.compute_global_snapshot(datetime.now())
    # With linear price increase (trend up), low vol (implicit in constant slope),
    # and default fallbacks for breadth/corr, should likely be NORMAL or ELEVATED depending on thresholds.
    # Our simple logic:
    # SMA50 dist > 0 (Risk=0)
    # Slope > 0 (Risk=0)
    # Vol (std of linear) is very low ~0 (Risk=0)
    # Breadth default 0.5 (Risk=0)
    # Corr default 0.0 (Risk=0)
    # Total Risk Score ~ 0 -> NORMAL (or SUPPRESSED if vol very low)

    assert isinstance(snap, GlobalRegimeSnapshot)
    assert snap.state in [RegimeState.NORMAL, RegimeState.SUPPRESSED]
    assert snap.risk_score < 3.0

def test_compute_global_snapshot_shock(engine, mock_market_data):
    # Mock a crash
    # Price drops 10% in last few days
    # Need >= 60 bars for vol calc to trigger (code checks len >= 60)
    prices = [100.0] * 60 + [90.0, 80.0, 70.0, 60.0, 50.0] # 65 bars
    mock_market_data.get_historical_prices.return_value = [
        {'close': p, 'date': '2025-01-01'} for p in prices
    ]

    snap = engine.compute_global_snapshot(datetime.now())

    # Analysis:
    # SMA50 ~95. Current 50. Dist -47% (Risk +2)
    # Slope Negative (Risk +1)
    # Vol High (Risk +3 due to crash volatility)
    # Breadth/Corr will likely be poor too (Risk +1.5 +1.5)
    # Total > 6 -> SHOCK

    assert snap.state == RegimeState.SHOCK
    assert snap.risk_scaler < 1.0 # Should be conservative (0.4)

def test_compute_symbol_snapshot(engine):
    snap = engine.compute_symbol_snapshot("AAPL", datetime.now())
    assert snap.symbol == "AAPL"
    assert snap.state == RegimeState.NORMAL # Default iv_rank 50
    assert snap.symbol_score == 0.0

def test_compute_symbol_snapshot_elevated(engine, mock_iv_repo):
    mock_iv_repo.get_iv_context.return_value = {'iv_rank': 85.0, 'current_iv': 0.40}
    snap = engine.compute_symbol_snapshot("TSLA", datetime.now())
    assert snap.state == RegimeState.ELEVATED
    assert snap.symbol_score > 0

def test_effective_regime_logic(engine):
    # G=Normal, S=Shock -> S
    g_snap = GlobalRegimeSnapshot(datetime.now(), RegimeState.NORMAL, 0, 1.0)
    s_snap = engine.compute_symbol_snapshot("MOCK", datetime.now()) # Normal
    s_snap.state = RegimeState.SHOCK

    eff = engine.get_effective_regime(s_snap, g_snap)
    assert eff == RegimeState.SHOCK

    # G=Shock, S=Normal -> Shock (Global Override)
    g_snap.state = RegimeState.SHOCK
    s_snap.state = RegimeState.NORMAL
    eff = engine.get_effective_regime(s_snap, g_snap)
    assert eff == RegimeState.SHOCK

def test_map_to_scoring_regime(engine):
    assert engine.map_to_scoring_regime(RegimeState.NORMAL) == "normal"
    assert engine.map_to_scoring_regime(RegimeState.SHOCK) == "panic"
    assert engine.map_to_scoring_regime(RegimeState.ELEVATED) == "high_vol"
    assert engine.map_to_scoring_regime(RegimeState.SUPPRESSED) == "normal"
