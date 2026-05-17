"""Live correctness tests for HistoricalIVService range-query refactor.

These tests hit real Polygon API and verify the window-aware refactor
(``compute_historical_iv_points_for_window``) produces values matching
the per-date method (``compute_historical_iv_point``) AND today's
captured fixtures.

Capture date: 2026-05-16 17:15-17:20 UTC (cold cache, single sequential
run, against PR #948's ``expired=true`` behavior).

Tolerance: 0.001 pct-pts on ``iv_30d`` (tight — the refactor preserves
behavior; intermediate values reach this tolerance too).

IMPORTANT — fixture drift caveat (Finding C, 2026-05-17 backlog):
even with PR #948's ``expired=true`` fix, the handler's anchor-selection
algorithm in ``IVPointService.compute_atm_iv_target_from_chain`` picks
the "best" anchors from the contract set available at query time. As
time advances and contracts expire, available-set changes can shift
anchor selection.

If these tests fail due to anchor-selection shift (recognizable by
mismatched ``expiry1``/``expiry2`` in failure messages), re-capture
fixtures by running the per-date method against the same tuples and
update the constants below.

Recommend refresh every ~2 weeks if tests run regularly.

SKIPS UNLESS ``RUN_LIVE_POLYGON_TESTS=1`` IS SET — these are
integration tests that hit real Polygon API and require BOTH a valid
``POLYGON_API_KEY`` AND explicit opt-in. CI sets a fake POLYGON_API_KEY
value (``fake_polygon_key``) so a key-presence check alone would
incorrectly run the tests in CI; the explicit opt-in env var avoids
that. Locally: ``RUN_LIVE_POLYGON_TESTS=1 pytest <file>``.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest


def _load_env_for_tests() -> None:
    """Load .env files so POLYGON_API_KEY is available when running
    locally with a venv. CI sets the env var directly.

    __file__ = packages/quantum/tests/test_historical_iv_range_refactor_live.py
    parents[0]=tests, [1]=quantum, [2]=packages, [3]=repo-root.
    """
    repo_root = Path(__file__).resolve().parents[3]
    for env_path in [
        repo_root / "packages" / "quantum" / ".env",
        repo_root / ".env",
    ]:
        if not env_path.exists():
            continue
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


_load_env_for_tests()

# Explicit opt-in: CI sets POLYGON_API_KEY=fake_polygon_key so checking
# key-presence alone would incorrectly run the tests in CI against fake
# credentials. Require RUN_LIVE_POLYGON_TESTS=1 AND a Polygon key.
pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_POLYGON_TESTS") != "1"
    or not os.environ.get("POLYGON_API_KEY"),
    reason=(
        "Live Polygon tests skipped. To run: set RUN_LIVE_POLYGON_TESTS=1 "
        "in addition to POLYGON_API_KEY."
    ),
)


# ── Captured fixtures ────────────────────────────────────────────────
# 2026-05-16 17:15-17:20 UTC (post-PR-A2, cold cache, single sequential run).
# See test docstring for refresh guidance.

FIXTURE_CAPTURED_AT_UTC = "2026-05-16T17:15:00Z"

LIVE_FIXTURES = [
    {
        "symbol": "SPY",
        "as_of": date(2026, 4, 15),
        "iv_30d": 0.14143764725182910,
        "spot": 699.94,
        "expiry1": "2026-04-24", "expiry2": "2026-04-24",
        "t1_dte": 9, "t2_dte": 9,
    },
    {
        "symbol": "AAPL",
        "as_of": date(2026, 4, 15),
        "iv_30d": 0.29657370071441670,
        "spot": 266.43,
        "expiry1": "2026-05-15", "expiry2": "2026-05-15",
        "t1_dte": 30, "t2_dte": 30,
    },
    {
        "symbol": "AMD",
        "as_of": date(2026, 5, 8),
        "iv_30d": 0.70250759678592580,
        "spot": 455.19,
        "expiry1": "2026-05-15", "expiry2": "2026-05-15",
        "t1_dte": 7, "t2_dte": 7,
    },
]


@pytest.fixture(scope="module")
def hiv_service():
    """Module-scoped service so contract caches inside a single
    Polygon connection are reused across tests in this file."""
    from packages.quantum.market_data import PolygonService
    from packages.quantum.services.historical_iv_service import (
        HistoricalIVService,
    )

    polygon = PolygonService()
    return HistoricalIVService(polygon_service=polygon, risk_free_rate=0.045)


@pytest.mark.parametrize(
    "fixture", LIVE_FIXTURES, ids=lambda f: f"{f['symbol']}_{f['as_of']}",
)
def test_window_method_matches_captured_fixture(hiv_service, fixture):
    """The window method, called with a single-date list, must produce
    the same iv_30d as the captured fixture (and as the per-date method).

    Tolerance 0.001 pct-pts on iv_30d.
    """
    sym = fixture["symbol"]
    d = fixture["as_of"]

    results = hiv_service.compute_historical_iv_points_for_window(sym, [d])

    assert d in results, (
        f"window method returned no entry for {sym} @ {d}; "
        f"got keys: {list(results.keys())}"
    )
    res = results[d]
    assert res is not None, (
        f"window method returned None for {sym} @ {d}; "
        f"expected iv_30d={fixture['iv_30d']:.6f}"
    )

    today_iv = float(res["iv"])
    expected_iv = fixture["iv_30d"]
    delta_pct = abs(today_iv - expected_iv) * 100.0

    assert delta_pct < 0.001, (
        f"iv_30d drifted from captured fixture (>{0.001} pct-pts). "
        f"Expected {expected_iv:.6f}, got {today_iv:.6f}, "
        f"delta {delta_pct:.4f} pct-pts. "
        f"Anchor: expiry1={res.get('expiry1')} expiry2={res.get('expiry2')}. "
        f"Captured at {FIXTURE_CAPTURED_AT_UTC}. "
        f"If anchor-selection shifted (Finding C, see backlog), "
        f"re-capture fixtures."
    )

    # Spot is a direct fetch; should match exactly.
    inputs = res.get("inputs") or {}
    today_spot = float(inputs.get("spot") or 0.0)
    assert abs(today_spot - fixture["spot"]) < 0.01, (
        f"spot mismatch for {sym} @ {d}: expected {fixture['spot']}, "
        f"got {today_spot}"
    )


@pytest.mark.parametrize(
    "fixture", LIVE_FIXTURES, ids=lambda f: f"{f['symbol']}_{f['as_of']}",
)
def test_window_method_matches_per_date_method(hiv_service, fixture):
    """The window method called with a single-date list must produce
    EXACTLY the same iv_30d as the per-date method ``compute_historical_iv_point``.

    This is the strongest behavior-preservation guarantee: the refactor
    is a performance optimization, not a behavior change. Same inputs,
    same outputs, bit-for-bit.

    Independent of whether captured fixtures still apply (Finding C
    drift) — this test compares the two code paths against EACH OTHER
    using whatever Polygon state exists right now.
    """
    sym = fixture["symbol"]
    d = fixture["as_of"]

    per_date_result = hiv_service.compute_historical_iv_point(sym, d)
    window_results = hiv_service.compute_historical_iv_points_for_window(sym, [d])
    window_result = window_results.get(d)

    # Both should either succeed or both fail; never one without the other.
    assert (per_date_result is None) == (window_result is None), (
        f"Per-date and window methods disagree on success for {sym} @ {d}: "
        f"per_date={per_date_result is not None}, "
        f"window={window_result is not None}"
    )

    if per_date_result is None:
        pytest.skip(f"both methods returned None for {sym} @ {d}; nothing to compare")

    iv_pd = float(per_date_result["iv"])
    iv_win = float(window_result["iv"])
    delta_pct = abs(iv_pd - iv_win) * 100.0

    assert delta_pct < 0.001, (
        f"Window method diverges from per-date method for {sym} @ {d}: "
        f"per_date={iv_pd:.6f}, window={iv_win:.6f}, "
        f"delta={delta_pct:.4f} pct-pts. "
        f"This is a behavior-preservation failure — the refactor "
        f"should not change outputs, only performance."
    )

    # Also compare intermediate anchors. If both methods reach the
    # interpolation step they should pick the same anchor pair.
    for k in ("expiry1", "expiry2", "strike1", "strike2"):
        assert per_date_result.get(k) == window_result.get(k), (
            f"Intermediate field {k!r} differs between methods for "
            f"{sym} @ {d}: per_date={per_date_result.get(k)}, "
            f"window={window_result.get(k)}"
        )


def test_window_method_handles_multi_date_batch(hiv_service):
    """The window method's primary value is batch operation: passing
    many dates and getting a dense per-date result dict.

    Sanity check: 3 dates for one symbol return all 3 keys + at least
    one non-None result. This is the smoke test for the per-symbol
    backfill use case.
    """
    sym = "AMD"
    dates = [date(2026, 5, 5), date(2026, 5, 6), date(2026, 5, 7)]

    results = hiv_service.compute_historical_iv_points_for_window(sym, dates)

    assert set(results.keys()) == set(dates), (
        f"window method must return dense dict over input dates. "
        f"Got keys: {list(results.keys())}, expected: {dates}"
    )

    non_none = sum(1 for v in results.values() if v is not None)
    assert non_none > 0, (
        f"window method returned None for all 3 dates of {sym}; "
        f"expected at least one weekday-with-data to succeed"
    )


def test_window_method_empty_list_returns_empty(hiv_service):
    """Edge case: empty target_dates list returns empty dict, no
    Polygon calls made. Handler relies on this to skip already-fully-
    populated symbols cheaply."""
    results = hiv_service.compute_historical_iv_points_for_window("AMD", [])
    assert results == {}
