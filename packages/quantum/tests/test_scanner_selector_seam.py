# packages/quantum/tests/test_scanner_selector_seam.py
"""Proves the PRODUCTION scanner route calls StrategySelector.get_candidates
when MULTI_STRATEGY_EVAL=1 (the default), by driving scan_for_opportunities
end-to-end with fakes at the DATA BOUNDARY only (truth layer / polygon /
regime engine). The selector call itself is NOT stubbed away: a recording
wrapper delegates to the real get_candidates and returns its real candidate
list, so the seam under test executes for real.

The option chain is dark by construction, so after the selector seam the
symbol must die with the downstream `no_chain` rejection — reaching that
rejection is the proof the scan consumed the selector's real output and
continued down the production path (failure injected at the deepest data
callee, truth asserted at the top-level scan result).
"""

import types

from packages.quantum import options_scanner
from packages.quantum.analytics.regime_engine_v3 import RegimeState
from packages.quantum.analytics.strategy_selector import StrategySelector


class _FakeTruthLayer:
    """Data-boundary fake: quotes + bars present, option chain dark."""

    def __init__(self, *args, **kwargs):
        pass

    def normalize_symbol(self, s):
        return s

    def snapshot_many(self, symbols):
        return {
            s: {"quote": {"bid": 99.0, "ask": 101.0, "last": 100.0, "mid": 100.0}}
            for s in symbols
        }

    def daily_bars(self, symbol, start, end):
        # 60 rising closes -> BULLISH trend (close > sma20 > sma50)
        return [{"close": 100.0 + i} for i in range(60)]

    def option_chain(self, symbol, **kwargs):
        return []  # chain dark -> downstream no_chain rejection


class _FakePolygon:
    def __init__(self, *args, **kwargs):
        pass

    def get_recent_quote(self, symbol):
        return {}

    def get_historical_prices(self, symbol, days=90):
        return {"prices": []}

    def get_option_chain(self, symbol, **kwargs):
        return []

    def get_ticker_details(self, symbol):
        return None


class _FakeRegimeEngine:
    def __init__(self, *args, **kwargs):
        self.iv_repo = None

    def compute_symbol_snapshot(
        self, symbol, global_snapshot, existing_bars=None, iv_context=None
    ):
        return types.SimpleNamespace(iv_rank=45.0)  # real (non-None) iv_rank

    def get_effective_regime(self, symbol_snapshot, global_snapshot):
        return RegimeState.NORMAL


class _FakeEarningsService:
    def __init__(self, *args, **kwargs):
        pass

    def get_earnings_map(self, symbols):
        return {}


def test_scan_route_calls_get_candidates_under_multi_strategy_default(monkeypatch):
    # Precondition: the production default route. MULTI_STRATEGY_EVAL is a
    # module constant read from env at import time (default "1").
    assert options_scanner.MULTI_STRATEGY_EVAL is True

    # Stub the DATA BOUNDARY in the scanner module namespace.
    monkeypatch.setattr(options_scanner, "MarketDataTruthLayer", _FakeTruthLayer)
    monkeypatch.setattr(options_scanner, "PolygonService", _FakePolygon)
    monkeypatch.setattr(options_scanner, "RegimeEngineV3", _FakeRegimeEngine)
    monkeypatch.setattr(
        options_scanner, "EarningsCalendarService", _FakeEarningsService
    )

    # Record the selector seam WITHOUT stubbing it: delegate to the real
    # get_candidates and pass its real output through.
    calls = []
    real_get_candidates = StrategySelector.get_candidates

    def recording_get_candidates(self, *args, **kwargs):
        out = real_get_candidates(self, *args, **kwargs)
        calls.append(
            {
                "args": args,
                "kwargs": dict(kwargs),
                "emitted": [c["strategy"] for c in out],
            }
        )
        return out

    monkeypatch.setattr(StrategySelector, "get_candidates", recording_get_candidates)

    # The legacy single-pick path must NOT be taken on this route.
    legacy_calls = []
    real_determine = StrategySelector.determine_strategy

    def recording_determine(self, *args, **kwargs):
        legacy_calls.append((args, kwargs))
        return real_determine(self, *args, **kwargs)

    monkeypatch.setattr(StrategySelector, "determine_strategy", recording_determine)

    global_snapshot = types.SimpleNamespace(state=RegimeState.NORMAL)

    candidates, rej_stats = options_scanner.scan_for_opportunities(
        symbols=["SPY"],
        supabase_client=None,
        global_snapshot=global_snapshot,
    )

    # 1. The production route hit the get_candidates seam exactly once for
    #    the symbol (fallback retries reuse the stashed list, never re-call).
    assert len(calls) == 1
    call = calls[0]
    assert call["kwargs"].get("ticker") == "SPY"
    assert call["kwargs"].get("sentiment") == "BULLISH"  # rising closes
    assert call["kwargs"].get("iv_rank") == 45.0
    assert call["kwargs"].get("effective_regime") == "normal"

    # 2. The wrapper returned a REAL candidate list (bullish + normal IV
    #    pool), and the legacy path was never taken.
    assert call["emitted"] == [
        "LONG_CALL_DEBIT_SPREAD",
        "SHORT_PUT_CREDIT_SPREAD",
    ]
    assert legacy_calls == []

    # 3. Top-level truth: the scan consumed the selector output and died
    #    DOWNSTREAM of the seam at the dark chain (injected at the deepest
    #    data callee), then exhausted the fallback candidate too.
    counts = rej_stats.to_dict()["rejection_counts"]
    assert counts.get("no_chain", 0) >= 1
    assert counts.get("all_strategies_rejected", 0) == 1
    assert candidates == []
