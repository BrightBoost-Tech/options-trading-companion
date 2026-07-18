import sys
from unittest.mock import MagicMock

# Stub heavy dependencies ONLY around the workflow_orchestrator import, then
# RESTORE sys.modules. The previous version left these MagicMocks in
# sys.modules for the whole pytest session, so any LATER lazy import of e.g.
# packages.quantum.options_scanner in another file silently bound a mock —
# float(MagicMock()) == 1.0 — the 2026-07-17 CI test_cost_basis_parity
# failure class (green single-file, red at full-suite collection order).
_STUB_KEYS = (
    'supabase',
    'packages.quantum.options_scanner',
    'packages.quantum.analytics.regime_engine_v3',
    'packages.quantum.models',
    'packages.quantum.market_data',
    'packages.quantum.ev_calculator',
    'packages.quantum.analytics.loss_minimizer',
    'packages.quantum.analytics.conviction_service',
    'packages.quantum.services.iv_repository',
    'packages.quantum.services.iv_point_service',
    'packages.quantum.observability.telemetry',
    'packages.quantum.services.cash_service',
    'packages.quantum.services.sizing_engine',
    'packages.quantum.services.journal_service',
    'packages.quantum.services.options_utils',
    'packages.quantum.services.exit_stats_service',
    'packages.quantum.services.market_data_truth_layer',
    'packages.quantum.services.analytics_service',
)
_saved = {_k: sys.modules.get(_k) for _k in _STUB_KEYS}
for _k in _STUB_KEYS:
    if _saved[_k] is None:  # never shadow an already-imported real module
        sys.modules[_k] = MagicMock()
try:
    from packages.quantum.services.workflow_orchestrator import normalize_win_rate
finally:
    for _k in _STUB_KEYS:
        if _saved[_k] is None:
            sys.modules.pop(_k, None)
        else:
            sys.modules[_k] = _saved[_k]
del _saved

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
