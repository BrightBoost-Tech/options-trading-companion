"""Tests for #115 PR-B-1 — iv_rank None-routing flag.

Covers:
1. Feature flag default + parsing.
2. Regime engine no-IV-signal classification path.
3. Scanner sort key respects iv_rank_quality when flag is ON and is
   identical to pre-PR-B-1 when flag is OFF.

Source-level structural assertions on the scanner site (the
ThreadPoolExecutor-driven cycle is too heavy for an in-process test
without a substantial fixture). Behavioral tests focus on the regime
engine's classifier, which is pure-Python and easy to call directly.
"""

import os
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from packages.quantum.observability.feature_flags import (
    is_iv_rank_none_routing_enabled,
)


SCANNER_PATH = (
    Path(__file__).parent.parent / "options_scanner.py"
)


def _read_scanner() -> str:
    return SCANNER_PATH.read_text(encoding="utf-8")


class TestFeatureFlag(unittest.TestCase):
    def setUp(self):
        # Make sure no leftover env from a previous test poisons the run.
        self._prior = os.environ.pop("IV_RANK_NONE_ROUTING_ENABLED", None)

    def tearDown(self):
        os.environ.pop("IV_RANK_NONE_ROUTING_ENABLED", None)
        if self._prior is not None:
            os.environ["IV_RANK_NONE_ROUTING_ENABLED"] = self._prior

    def test_default_off(self):
        self.assertFalse(is_iv_rank_none_routing_enabled())

    def test_truthy_values_enable(self):
        for v in ("1", "true", "True", "yes", "YES"):
            os.environ["IV_RANK_NONE_ROUTING_ENABLED"] = v
            self.assertTrue(
                is_iv_rank_none_routing_enabled(),
                f"value {v!r} should enable",
            )

    def test_falsy_values_disable(self):
        for v in ("0", "false", "no", "", "anything-else"):
            os.environ["IV_RANK_NONE_ROUTING_ENABLED"] = v
            self.assertFalse(
                is_iv_rank_none_routing_enabled(),
                f"value {v!r} should disable",
            )


class TestRegimeNoIvSignalClassifier(unittest.TestCase):
    """Direct unit tests for `_classify_no_iv_signal`.

    Avoids the full `compute_symbol_snapshot` flow because that method
    fetches IV context, bars, and chains. The classifier method is
    pure given its inputs and is what PR-B-1 actually changes.
    """

    @classmethod
    def setUpClass(cls):
        from packages.quantum.analytics.regime_engine_v3 import (
            RegimeEngineV3,
        )
        cls.RegimeEngineV3 = RegimeEngineV3

    def _engine(self):
        # The classifier is an instance method but doesn't touch
        # supabase / market_data — a stub instance suffices.
        eng = self.RegimeEngineV3.__new__(self.RegimeEngineV3)
        return eng

    def _common_kwargs(self, rv_20d):
        return dict(
            symbol="AAPL",
            as_of=datetime(2026, 5, 7, 12, 0, tzinfo=timezone.utc),
            atm_iv=None,
            rv_20d=rv_20d,
            iv_rv_spread=None,
            skew_25d=None,
            term_slope=None,
            quality_flags={"rank_missing": True},
        )

    def test_rv_unavailable_returns_normal(self):
        from packages.quantum.common_enums import RegimeState
        snap = self._engine()._classify_no_iv_signal(
            **self._common_kwargs(rv_20d=None),
        )
        self.assertEqual(snap.state, RegimeState.NORMAL)
        self.assertIsNone(snap.iv_rank)
        self.assertTrue(snap.quality_flags.get("no_iv_signal"))

    def test_low_rv_returns_normal(self):
        from packages.quantum.common_enums import RegimeState
        snap = self._engine()._classify_no_iv_signal(
            **self._common_kwargs(rv_20d=0.15),
        )
        self.assertEqual(snap.state, RegimeState.NORMAL)

    def test_elevated_rv_returns_elevated(self):
        from packages.quantum.common_enums import RegimeState
        snap = self._engine()._classify_no_iv_signal(
            **self._common_kwargs(rv_20d=0.35),
        )
        self.assertEqual(snap.state, RegimeState.ELEVATED)

    def test_shock_rv_returns_shock(self):
        from packages.quantum.common_enums import RegimeState
        snap = self._engine()._classify_no_iv_signal(
            **self._common_kwargs(rv_20d=0.60),
        )
        self.assertEqual(snap.state, RegimeState.SHOCK)

    def test_no_iv_signal_flag_set(self):
        snap = self._engine()._classify_no_iv_signal(
            **self._common_kwargs(rv_20d=0.20),
        )
        self.assertTrue(snap.quality_flags["no_iv_signal"])
        # Should not blow away pre-existing quality flags
        self.assertTrue(snap.quality_flags.get("rank_missing"))

    def test_score_is_zero_not_synthetic_50(self):
        """The pre-PR-B-1 silent fallback fabricated 50.0 percentile and
        a NORMAL-bracketing score. The no-IV-signal path must not.
        """
        snap = self._engine()._classify_no_iv_signal(
            **self._common_kwargs(rv_20d=0.20),
        )
        self.assertEqual(snap.score, 0.0)
        self.assertIsNone(snap.features["iv_rank"])


class TestRegimeFlagOffPreservesBehavior(unittest.TestCase):
    """Flag OFF: silent fallback at the line-529 fork must remain
    intact. We exercise the full `compute_symbol_snapshot` once with
    iv_context['iv_rank']=None and assert NORMAL is still returned via
    the f_rank=50.0 path — confirming the routing didn't activate.
    """

    def setUp(self):
        os.environ.pop("IV_RANK_NONE_ROUTING_ENABLED", None)

    def test_flag_off_iv_none_routes_through_legacy_path(self):
        from packages.quantum.analytics.regime_engine_v3 import (
            RegimeEngineV3, GlobalRegimeSnapshot,
        )
        from packages.quantum.common_enums import RegimeState

        # Stub instance to avoid touching network/db.
        eng = RegimeEngineV3.__new__(RegimeEngineV3)
        eng.iv_repo = None
        eng.market_data = MagicMock()
        # daily_bars: 25 closes flat at 100 → rv_20d ≈ 0
        bars = [{"close": 100.0} for _ in range(25)]
        eng.market_data.daily_bars.return_value = bars

        gsnap = GlobalRegimeSnapshot(
            as_of_ts="2026-05-07T12:00:00",
            state=RegimeState.NORMAL,
            risk_score=50.0,
            risk_scaler=1.0,
            trend_score=0.0,
            vol_score=0.0,
            corr_score=0.0,
            breadth_score=0.0,
            liquidity_score=0.0,
        )

        snap = eng.compute_symbol_snapshot(
            symbol="AAPL",
            global_snapshot=gsnap,
            existing_bars=bars,
            iv_context={"iv_rank": None, "iv_30d": None},
            chain_results=None,
        )
        # Legacy path: f_rank=50 → score≈25 → NORMAL bracket. The
        # synthetic iv_rank should NOT be set on the snapshot itself
        # (regime_engine_v3 stores the original None on the snapshot,
        # only the score uses 50.0).
        self.assertEqual(snap.state, RegimeState.NORMAL)
        self.assertIsNone(snap.iv_rank)
        self.assertNotIn("no_iv_signal", snap.quality_flags)

    def test_flag_on_iv_none_routes_through_no_iv_signal(self):
        from packages.quantum.analytics.regime_engine_v3 import (
            RegimeEngineV3, GlobalRegimeSnapshot,
        )
        from packages.quantum.common_enums import RegimeState

        os.environ["IV_RANK_NONE_ROUTING_ENABLED"] = "1"
        try:
            eng = RegimeEngineV3.__new__(RegimeEngineV3)
            eng.iv_repo = None
            eng.market_data = MagicMock()
            bars = [{"close": 100.0} for _ in range(25)]
            eng.market_data.daily_bars.return_value = bars

            gsnap = GlobalRegimeSnapshot(
                as_of_ts="2026-05-07T12:00:00",
                state=RegimeState.NORMAL,
                risk_score=50.0,
                risk_scaler=1.0,
                trend_score=0.0,
                vol_score=0.0,
                corr_score=0.0,
                breadth_score=0.0,
                liquidity_score=0.0,
            )

            snap = eng.compute_symbol_snapshot(
                symbol="AAPL",
                global_snapshot=gsnap,
                existing_bars=bars,
                iv_context={"iv_rank": None, "iv_30d": None},
                chain_results=None,
            )
            self.assertTrue(snap.quality_flags.get("no_iv_signal"))
        finally:
            os.environ.pop("IV_RANK_NONE_ROUTING_ENABLED", None)


class TestScannerSiteWired(unittest.TestCase):
    """Source-level structural assertions on the scanner sort + site.

    The full scanner is too heavy to invoke in a unit test without a
    fixture; structural-only checks match the convention in
    test_iv_pipeline_no_data_alert.py.
    """

    @classmethod
    def setUpClass(cls):
        cls.src = _read_scanner()

    def test_iv_rank_quality_field_in_candidate_dict(self):
        # The candidate_dict construction must include the quality flag.
        m = re.search(
            r'"iv_rank":\s*iv_rank,\s*\n\s*"iv_rank_quality":\s*iv_rank_quality',
            self.src,
        )
        self.assertIsNotNone(
            m,
            "iv_rank_quality must be set adjacent to iv_rank in candidate_dict",
        )

    def test_three_quality_states_present(self):
        # real / missing / unknown — the flag-OFF branch tags "unknown".
        for tag in ('"real"', '"missing"', '"unknown"'):
            self.assertIn(tag, self.src, f"missing quality tag {tag}")

    def test_sort_branches_on_routing_flag(self):
        # Anchor on the sort site itself, not the iv_rank tagging site
        # earlier in the file (multiple occurrences of the flag check).
        anchor = self.src.find(
            'x.get("iv_rank_quality") == "real"'
        )
        self.assertGreater(
            anchor, 0,
            "scanner sort key must inspect iv_rank_quality",
        )
        # The flag-ON sort must order real-iv ahead of missing-iv,
        # then by score, then symbol — verified by literal match on the
        # comparator tuple.
        window = self.src[max(0, anchor - 200):anchor + 400]
        self.assertIn("if is_iv_rank_none_routing_enabled():", window)
        self.assertIn('x["score"]', window)
        self.assertIn('x["symbol"]', window)

    def test_legacy_sort_preserved_on_flag_off(self):
        # Pre-PR-B-1 sort must remain intact in the else branch.
        self.assertIn(
            "candidates.sort(key=lambda x: (x['score'], x['symbol']), reverse=True)",
            self.src,
        )

    def test_flag_module_imported_at_module_level(self):
        self.assertIn(
            "from packages.quantum.observability.feature_flags import "
            "is_iv_rank_none_routing_enabled",
            self.src,
        )


if __name__ == "__main__":
    unittest.main()
