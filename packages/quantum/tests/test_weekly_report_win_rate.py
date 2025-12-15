import sys
from unittest.mock import MagicMock

# Mock heavy dependencies before import to isolate the pure function
sys.modules['supabase'] = MagicMock()
sys.modules['packages.quantum.options_scanner'] = MagicMock()
sys.modules['packages.quantum.analytics.regime_engine_v3'] = MagicMock()
sys.modules['packages.quantum.models'] = MagicMock()
sys.modules['packages.quantum.market_data'] = MagicMock()
sys.modules['packages.quantum.ev_calculator'] = MagicMock()
sys.modules['packages.quantum.analytics.loss_minimizer'] = MagicMock()
sys.modules['packages.quantum.analytics.conviction_service'] = MagicMock()
sys.modules['packages.quantum.services.iv_repository'] = MagicMock()
sys.modules['packages.quantum.services.iv_point_service'] = MagicMock()
sys.modules['packages.quantum.observability.telemetry'] = MagicMock()
sys.modules['packages.quantum.services.cash_service'] = MagicMock()
sys.modules['packages.quantum.services.sizing_engine'] = MagicMock()
sys.modules['packages.quantum.services.journal_service'] = MagicMock()
sys.modules['packages.quantum.services.options_utils'] = MagicMock()
sys.modules['packages.quantum.services.exit_stats_service'] = MagicMock()
sys.modules['packages.quantum.services.market_data_truth_layer'] = MagicMock()
sys.modules['packages.quantum.services.analytics_service'] = MagicMock()

from packages.quantum.services.workflow_orchestrator import normalize_win_rate

def test_normalize_win_rate_percent_input():
    ratio, pct = normalize_win_rate(75.0)
    assert ratio == 0.75
    assert pct == 75.0

def test_normalize_win_rate_ratio_input():
    ratio, pct = normalize_win_rate(0.75)
    assert ratio == 0.75
    assert pct == 75.0

def test_normalize_win_rate_clamps_high_percent():
    ratio, pct = normalize_win_rate(250.0)
    assert ratio == 1.0
    assert pct == 100.0

def test_normalize_win_rate_clamps_negative():
    ratio, pct = normalize_win_rate(-5.0)
    assert ratio == 0.0
    assert pct == 0.0

def test_normalize_win_rate_none():
    ratio, pct = normalize_win_rate(None)
    assert ratio == 0.0
    assert pct == 0.0

def test_normalize_win_rate_string_input():
    # It should gracefully handle string if it's a number
    ratio, pct = normalize_win_rate("50")
    assert ratio == 0.5
    assert pct == 50.0

    # Garbage string should return 0
    ratio, pct = normalize_win_rate("garbage")
    assert ratio == 0.0
    assert pct == 0.0
