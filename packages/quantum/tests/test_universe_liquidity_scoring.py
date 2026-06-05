"""Tests for the 2026-06-05 universe liquidity-scoring fixes.

Two defects in the equity liquidity_score (UniverseService), one tiebreak:

1. ETF zero-cap: ETFs carry no market_cap, so the size component scored
   0/40 and hard-capped every ETF at 60 — SPY/QQQ/IWM + all sector ETFs
   were statically dropped from every bound cut (the inverted-selection
   finding). Fix: fund-type symbols score size on notional dollar volume.
2. Silent fetch failure (H9): get_ticker_details is @guardrail'd with
   fallback={} — an API error returned an empty dict, indistinguishable
   downstream from an ETF's legit absence; both silently zeroed. Fix:
   should-have-a-cap names score on the notional proxy AND are flagged
   loudly (per-symbol warning + aggregate market_cap_unavailable alert).
3. Tiebreak: equal liquidity_scores at a bound cut resolved alphabetically
   (MARA/RIVN lost their slot to KHC by spelling). Fix: ties break on
   avg_volume_30d (NULLS LAST) before the alphabet.

The common case — single-name equity with a successful fetch — must be
byte-identical to the pre-fix heuristic (regression pins below use the
live 2026-04-29 scanner_universe values).
"""

import sys
import types
import unittest

# Stub alpaca-py so transitive imports resolve in the test venv.
sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
sys.modules.setdefault("alpaca.trading.requests", types.ModuleType("alpaca.trading.requests"))

from packages.quantum.services.universe_service import UniverseService  # noqa: E402


def _score(**kw):
    defaults = dict(
        market_cap=None, avg_vol=0, iv_rank=None,
        asset_type=None, avg_notional=None, details_fetch_failed=False,
    )
    defaults.update(kw)
    return UniverseService.compute_liquidity_score(**defaults)


class TestCommonCaseUnchanged(unittest.TestCase):
    """Regression pins: cap-present single names score EXACTLY as the
    pre-fix heuristic did. Values are the live 2026-04-29 rows."""

    def test_aapl_mega_cap(self):
        # $3.93T cap (40) + 41.1M vol (40) + IV (20) = 100
        score, meta = _score(
            market_cap=3_928_819_875_400, avg_vol=41_132_222,
            iv_rank=50.0, asset_type="CS",
        )
        self.assertEqual(score, 100)
        self.assertEqual(meta["size_source"], "market_cap")
        self.assertFalse(meta["cap_missing_anomaly"])

    def test_gild_unchanged_not_boosted(self):
        # $158B (40) + 5.9M vol (30) + IV (20) = 90 — the measured-0.0
        # option-liquidity names must NOT move here; down-ranking them
        # is #1015's job, not this fix's.
        score, _ = _score(
            market_cap=158_563_777_274, avg_vol=5_863_485,
            iv_rank=50.0, asset_type="CS",
        )
        self.assertEqual(score, 90)

    def test_adp_unchanged(self):
        # $79B (30) + 3.6M vol (30) + IV (20) = 80
        score, _ = _score(
            market_cap=79_413_547_911, avg_vol=3_620_775,
            iv_rank=50.0, asset_type="CS",
        )
        self.assertEqual(score, 80)

    def test_regn_unchanged_at_60(self):
        # REGN was hypothesized as a failed cap fetch; live data shows the
        # cap PRESENT ($78B → 30) — its 60 is the share-volume bracket
        # (631k shares/day → 10) + IV (20). Cap present → this fix does
        # not move it; the share-vs-notional volume bracket is a separate
        # decision. Pin the honest outcome.
        score, meta = _score(
            market_cap=78_046_368_982, avg_vol=631_844,
            iv_rank=50.0, asset_type="CS",
        )
        self.assertEqual(score, 60)
        self.assertEqual(meta["size_source"], "market_cap")
        self.assertFalse(meta["cap_missing_anomaly"])

    def test_notional_ignored_when_cap_present(self):
        # A huge notional must not double-dip when a cap exists.
        score_with, _ = _score(
            market_cap=78_046_368_982, avg_vol=631_844, iv_rank=50.0,
            asset_type="CS", avg_notional=400_000_000.0,
        )
        score_without, _ = _score(
            market_cap=78_046_368_982, avg_vol=631_844, iv_rank=50.0,
            asset_type="CS", avg_notional=None,
        )
        self.assertEqual(score_with, score_without)


class TestEtfScoresOnNotionalProxy(unittest.TestCase):
    """Fix 1: fund types score size on notional dollar volume, no alert."""

    def test_spy_deep_etf_scores_100(self):
        # ~$60B/day notional (40) + 81M shares (40) + IV (20) = 100
        score, meta = _score(
            asset_type="ETF", avg_vol=81_169_275,
            avg_notional=59_952_000_000.0, iv_rank=50.0,
        )
        self.assertEqual(score, 100)
        self.assertEqual(meta["size_source"], "notional_fund")
        self.assertFalse(meta["cap_missing_anomaly"], "legit absence — no alert")

    def test_xlu_sector_etf_clears_the_old_60_cap(self):
        # ~$1.1B/day (40) + 24.9M shares (40) + IV (20) = 100 (was 60)
        score, _ = _score(
            asset_type="ETF", avg_vol=24_923_147,
            avg_notional=1_109_703_119.0, iv_rank=50.0,
        )
        self.assertEqual(score, 100)

    def test_xlc_moderate_etf_lands_80(self):
        # ~$789M/day (30) + 7.1M shares (30) + IV (20) = 80 (was 50)
        score, _ = _score(
            asset_type="ETF", avg_vol=7_073_142,
            avg_notional=788_684_602.0, iv_rank=50.0,
        )
        self.assertEqual(score, 80)

    def test_etv_trust_type_counts_as_fund(self):
        # GLD-class trusts report type ETV, not ETF — must not alert.
        score, meta = _score(
            asset_type="ETV", avg_vol=11_967_372,
            avg_notional=4_742_000_000.0, iv_rank=50.0,
        )
        self.assertEqual(score, 100)
        self.assertEqual(meta["size_source"], "notional_fund")
        self.assertFalse(meta["cap_missing_anomaly"])

    def test_thin_etf_does_not_get_free_points(self):
        # $5M/day notional → 0 size points; the proxy ranks, it doesn't gift.
        score, _ = _score(
            asset_type="ETF", avg_vol=150_000,
            avg_notional=5_000_000.0, iv_rank=None,
        )
        self.assertEqual(score, 0)


class TestFailedFetchIsLoud(unittest.TestCase):
    """Fix 2 (H9): a missing cap on a should-have-one name is flagged,
    scored on the proxy — never silently zeroed."""

    def test_cs_without_cap_is_anomaly(self):
        score, meta = _score(
            market_cap=None, asset_type="CS", avg_vol=631_844,
            avg_notional=400_000_000.0, iv_rank=50.0,
        )
        self.assertTrue(meta["cap_missing_anomaly"])
        self.assertEqual(meta["size_source"], "notional_fallback")
        # Proxy keeps the rank sane: $400M/day → 30 + vol 10 + IV 20 = 60
        self.assertEqual(score, 60)

    def test_empty_details_fetch_failure_is_anomaly(self):
        # @guardrail fallback={} → no type at all. Can't prove it's a fund
        # → flag loudly (an ETF flagged during a Polygon outage is correct:
        # it IS a fetch failure).
        score, meta = _score(
            market_cap=None, asset_type=None, avg_vol=41_132_222,
            avg_notional=10_000_000_000.0, iv_rank=50.0,
            details_fetch_failed=True,
        )
        self.assertTrue(meta["cap_missing_anomaly"])
        self.assertTrue(meta["details_fetch_failed"])
        # Not zeroed: 40 + 40 + 20 = 100 — a mega-cap whose fetch failed
        # keeps roughly its rank instead of cratering to 60.
        self.assertEqual(score, 100)

    def test_fund_type_with_failed_fetch_still_flagged(self):
        # details_fetch_failed=True overrides the fund classification for
        # alerting purposes — the type came from a failed/empty payload.
        _, meta = _score(
            market_cap=None, asset_type="ETF", avg_vol=1_000_000,
            avg_notional=500_000_000.0, details_fetch_failed=True,
        )
        self.assertEqual(meta["size_source"], "notional_fallback")
        self.assertTrue(meta["cap_missing_anomaly"])

    def test_old_silent_zero_shape_is_dead(self):
        # The pre-fix behavior: cap None → 0/40 regardless of reality.
        # Now: same inputs with a notional → nonzero size component.
        zeroed, _ = _score(market_cap=None, asset_type="CS",
                           avg_vol=631_844, avg_notional=None, iv_rank=50.0)
        proxied, _ = _score(market_cap=None, asset_type="CS",
                            avg_vol=631_844, avg_notional=400_000_000.0,
                            iv_rank=50.0)
        self.assertEqual(zeroed, 30)   # no notional available → vol+IV only
        self.assertEqual(proxied, 60)  # proxy restores the size component


class TestTiebreakOnVolumeNotAlphabet(unittest.TestCase):
    """Fix 3: ties at the cut break on avg_volume_30d, alphabet last,
    NULL volume sorts last within a tie."""

    def _svc_with_rows(self, rows):
        from unittest.mock import MagicMock, patch

        client = MagicMock()
        universe_q = MagicMock()
        universe_q.select.return_value = universe_q
        universe_q.eq.return_value = universe_q
        universe_q.order.return_value = universe_q
        universe_q.execute.return_value = types.SimpleNamespace(data=rows)
        log_q = MagicMock()
        log_q.insert.return_value = log_q
        log_q.execute.return_value = types.SimpleNamespace(data=[{"id": 1}])

        def _table(name):
            return universe_q if name == "scanner_universe" else log_q

        client.table.side_effect = _table
        with patch(
            "packages.quantum.services.universe_service.PolygonService"
        ), patch(
            "packages.quantum.services.universe_service.EarningsCalendarService"
        ):
            return UniverseService(client)

    def test_higher_volume_wins_the_tie(self):
        # DB hands back alphabetical-within-tie (the old order); KHC has
        # lower volume than MARA/RIVN — they must outrank it now.
        rows = [
            {"symbol": "KHC", "earnings_date": None, "liquidity_score": 75, "avg_volume_30d": 6_000_000},
            {"symbol": "MARA", "earnings_date": None, "liquidity_score": 75, "avg_volume_30d": 30_000_000},
            {"symbol": "RIVN", "earnings_date": None, "liquidity_score": 75, "avg_volume_30d": 25_000_000},
        ]
        svc = self._svc_with_rows(rows)
        out = [c["symbol"] for c in svc.get_scan_candidates(limit=2, caller="t")]
        self.assertEqual(out, ["MARA", "RIVN"])

    def test_null_volume_sorts_last_within_tie(self):
        rows = [
            {"symbol": "AAA", "earnings_date": None, "liquidity_score": 75, "avg_volume_30d": None},
            {"symbol": "BBB", "earnings_date": None, "liquidity_score": 75, "avg_volume_30d": 1_000},
        ]
        svc = self._svc_with_rows(rows)
        out = [c["symbol"] for c in svc.get_scan_candidates(limit=2, caller="t")]
        self.assertEqual(out, ["BBB", "AAA"])

    def test_score_still_dominates_volume(self):
        # Tiebreak must NOT let a high-volume low-score name jump a bracket.
        rows = [
            {"symbol": "HI", "earnings_date": None, "liquidity_score": 90, "avg_volume_30d": 1_000},
            {"symbol": "LO", "earnings_date": None, "liquidity_score": 80, "avg_volume_30d": 99_000_000},
        ]
        svc = self._svc_with_rows(rows)
        out = [c["symbol"] for c in svc.get_scan_candidates(limit=1, caller="t")]
        self.assertEqual(out, ["HI"])

    def test_alphabet_still_breaks_exact_volume_ties(self):
        rows = [
            {"symbol": "ZZZ", "earnings_date": None, "liquidity_score": 75, "avg_volume_30d": 5_000},
            {"symbol": "AAA", "earnings_date": None, "liquidity_score": 75, "avg_volume_30d": 5_000},
        ]
        svc = self._svc_with_rows(rows)
        out = [c["symbol"] for c in svc.get_scan_candidates(limit=2, caller="t")]
        self.assertEqual(out, ["AAA", "ZZZ"])


class TestFisvStaysRetired(unittest.TestCase):
    """Rider: FISV was deactivated 2026-05-19 (corp action) but remained
    in BASE_UNIVERSE — sync_universe upserts is_active=True for every
    member, so the next universe_sync run (the activation step for this
    very fix) would have silently reactivated it."""

    def test_fisv_not_in_base_universe(self):
        self.assertNotIn("FISV", UniverseService.BASE_UNIVERSE)


if __name__ == "__main__":
    unittest.main()
