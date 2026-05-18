"""
Regression tests for the 2026-05-18 staleness-gate over-tightening fix.

Mechanism (pre-fix): `ops_health_service.compute_market_data_freshness`
per-symbol decision combined `snap.quality.is_stale` (vendor-quality
flag, set by MarketDataTruthLayer.snapshot_many_v4 independently of
timestamp age) OR (`freshness_ms > stale_threshold_ms`). The vendor-
quality clause frequently fires on SIP-entitled core symbols (SPY/QQQ)
within minutes of opening — well below the 600s timestamp threshold.
Combined with the SPY-or-QQQ override (line 582-584), this blocked
entire entry cycles on routine-regime days. Today's 18:01:48 UTC CSX
incident was the forcing example: regime=normal, freshness=108s,
threshold=600s, but SPY+QQQ vendor-quality flag triggered the block.

Fix: activate the vendor-quality clause ONLY in shock/elevated regimes.
Other regimes fall back to timestamp-vs-threshold only. Fail-closed on
unknown regime (treat as shock).

Tests cover all 6 regime states + unknown + the 2-symbol incident
scenario.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Stub alpaca-py so imports resolve in the test venv.
sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
sys.modules.setdefault(
    "alpaca.trading.requests", types.ModuleType("alpaca.trading.requests")
)

from packages.quantum.services import ops_health_service as ohs  # noqa: E402


def _make_snap(is_stale, freshness_ms):
    """Construct a snapshot mock with the .quality.is_stale / .freshness_ms
    shape that snapshot_many_v4 returns."""
    quality = MagicMock()
    quality.is_stale = is_stale
    quality.freshness_ms = freshness_ms
    snap = MagicMock()
    snap.quality = quality
    return snap


def _patch_truth_layer(snapshots_map):
    """Patch MarketDataTruthLayer so snapshot_many_v4 returns the
    provided dict and snapshot_many is a no-op. Returns the patcher
    context manager."""
    truth_module = "packages.quantum.services.market_data_truth_layer"
    truth_layer_class = MagicMock()
    instance = truth_layer_class.return_value
    instance.snapshot_many.return_value = {}
    instance.snapshot_many_v4.return_value = snapshots_map
    return patch(f"{truth_module}.MarketDataTruthLayer", truth_layer_class)


def _patch_api_key():
    """Avoid the early `missing_api_key` short-circuit."""
    return patch.dict("os.environ", {"POLYGON_API_KEY": "test-key"})


class TestRegimeConditionalIsStale(unittest.TestCase):
    """Per-symbol decision: vendor-quality flag only in shock/elevated."""

    UNIVERSE = ["SPY"]
    THRESHOLD_MS = 600 * 1000  # 600 seconds = 10 minutes

    def _run(self, regime, is_stale, freshness_ms):
        snaps = {"SPY": _make_snap(is_stale=is_stale, freshness_ms=freshness_ms)}
        with _patch_api_key(), _patch_truth_layer(snaps):
            return ohs.compute_market_data_freshness(
                universe=self.UNIVERSE,
                stale_threshold_ms=self.THRESHOLD_MS,
                regime=regime,
            )

    def test_normal_regime_ignores_vendor_flag_when_timestamp_fresh(self):
        """Normal + is_stale=True + freshness=60s → NOT stale.
        Vendor clause skipped; timestamp under threshold."""
        result = self._run("normal", is_stale=True, freshness_ms=60_000)
        self.assertFalse(result.is_stale)
        self.assertEqual(result.stale_symbols, [])

    def test_normal_regime_respects_timestamp_threshold(self):
        """Normal + is_stale=False + freshness=700s → STALE.
        Timestamp clause always active regardless of regime."""
        result = self._run("normal", is_stale=False, freshness_ms=700_000)
        self.assertTrue(result.is_stale)
        self.assertEqual(result.stale_symbols, ["SPY"])

    def test_shock_regime_activates_vendor_flag(self):
        """Shock + is_stale=True + freshness=60s → STALE.
        Vendor clause active in shock; volatile conditions justify
        extra caution."""
        result = self._run("shock", is_stale=True, freshness_ms=60_000)
        self.assertTrue(result.is_stale)
        self.assertEqual(result.stale_symbols, ["SPY"])

    def test_elevated_regime_activates_vendor_flag(self):
        """Elevated + is_stale=True + freshness=60s → STALE."""
        result = self._run("elevated", is_stale=True, freshness_ms=60_000)
        self.assertTrue(result.is_stale)

    def test_chop_regime_ignores_vendor_flag(self):
        """Chop + is_stale=True + freshness=60s → NOT stale.
        Chop is range-bound; not volatile enough to justify the
        vendor-quality clause."""
        result = self._run("chop", is_stale=True, freshness_ms=60_000)
        self.assertFalse(result.is_stale)

    def test_rebound_regime_ignores_vendor_flag(self):
        """Rebound + is_stale=True + freshness=60s → NOT stale.
        Rebound is recovery-from-shock; treated as routine."""
        result = self._run("rebound", is_stale=True, freshness_ms=60_000)
        self.assertFalse(result.is_stale)

    def test_suppressed_regime_ignores_vendor_flag(self):
        """Suppressed + is_stale=True + freshness=60s → NOT stale.
        Suppressed is below-baseline vol; least caution needed."""
        result = self._run("suppressed", is_stale=True, freshness_ms=60_000)
        self.assertFalse(result.is_stale)

    def test_case_insensitive_regime_normalization(self):
        """Regime string is normalized to lowercase + stripped before
        the set membership check."""
        result = self._run("  SHOCK  ", is_stale=True, freshness_ms=60_000)
        self.assertTrue(result.is_stale)
        result = self._run("Normal", is_stale=True, freshness_ms=60_000)
        self.assertFalse(result.is_stale)


class TestFailClosedDefault(unittest.TestCase):
    """Unknown / unresolvable regime → treat as shock (vendor clause active)."""

    UNIVERSE = ["SPY"]
    THRESHOLD_MS = 600 * 1000

    def test_unknown_regime_falls_back_to_shock_via_lookup_failure(self):
        """regime=None + lookup raises → fail-closed = vendor clause
        active. is_stale=True + freshness=60s → STALE."""
        snaps = {"SPY": _make_snap(is_stale=True, freshness_ms=60_000)}
        with _patch_api_key(), _patch_truth_layer(snaps), patch(
            "packages.quantum.jobs.handlers.utils.get_admin_client",
            side_effect=Exception("simulated lookup failure"),
        ):
            result = ohs.compute_market_data_freshness(
                universe=self.UNIVERSE,
                stale_threshold_ms=self.THRESHOLD_MS,
                regime=None,
            )
        self.assertTrue(result.is_stale)
        self.assertEqual(result.stale_symbols, ["SPY"])

    def test_unknown_regime_with_lookup_returning_normal_uses_normal(self):
        """regime=None + lookup returns last-recorded='normal' →
        normal regime applied → vendor clause skipped."""
        snaps = {"SPY": _make_snap(is_stale=True, freshness_ms=60_000)}
        admin_client = MagicMock()
        admin_client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
            {
                "result": {
                    "cycle_results": [
                        {"cycle_metadata": {"regime": "NORMAL"}}
                    ]
                }
            }
        ]
        with _patch_api_key(), _patch_truth_layer(snaps), patch(
            "packages.quantum.jobs.handlers.utils.get_admin_client",
            return_value=admin_client,
        ):
            result = ohs.compute_market_data_freshness(
                universe=self.UNIVERSE,
                stale_threshold_ms=self.THRESHOLD_MS,
                regime=None,
            )
        self.assertFalse(result.is_stale)


class TestIncidentReproduction(unittest.TestCase):
    """The 2026-05-18 18:01:48 UTC CSX block scenario, replayed
    end-to-end against compute_market_data_freshness."""

    THRESHOLD_MS = 600 * 1000  # 600s — production threshold

    def test_spy_qqq_vendor_flag_in_normal_regime_does_not_block(self):
        """Today's incident: SPY+QQQ vendor-flag=True, freshness=108s,
        threshold=600s, regime=NORMAL. Pre-fix: core_stale=True →
        is_stale=True → gate blocks. Post-fix: per-symbol clause
        skipped (normal); timestamp under threshold; core_stale=False;
        gate passes."""
        snaps = {
            "SPY": _make_snap(is_stale=True, freshness_ms=108_000),
            "QQQ": _make_snap(is_stale=True, freshness_ms=108_000),
        }
        with _patch_api_key(), _patch_truth_layer(snaps):
            result = ohs.compute_market_data_freshness(
                universe=["SPY", "QQQ"],
                stale_threshold_ms=self.THRESHOLD_MS,
                regime="normal",
            )
        self.assertFalse(result.is_stale, "Pre-fix would have blocked; post-fix must pass")
        self.assertEqual(result.stale_symbols, [])

    def test_spy_qqq_vendor_flag_in_shock_regime_blocks(self):
        """Inverse: same snapshot shape but regime=SHOCK. Vendor
        clause active → SPY+QQQ stale → core_stale=True → gate blocks.
        This is the protective behavior preserved for volatile
        regimes."""
        snaps = {
            "SPY": _make_snap(is_stale=True, freshness_ms=108_000),
            "QQQ": _make_snap(is_stale=True, freshness_ms=108_000),
        }
        with _patch_api_key(), _patch_truth_layer(snaps):
            result = ohs.compute_market_data_freshness(
                universe=["SPY", "QQQ"],
                stale_threshold_ms=self.THRESHOLD_MS,
                regime="shock",
            )
        self.assertTrue(result.is_stale)
        self.assertEqual(result.stale_symbols, ["QQQ", "SPY"])


class TestSpyQqqOverridePreserved(unittest.TestCase):
    """The core SPY-or-QQQ override (ops_health_service:line 582-584)
    must remain unchanged: if EITHER SPY or QQQ ends up in
    stale_symbols, the cycle is stale regardless of universe-wide
    majority. Only the per-symbol decision was loosened."""

    def test_spy_timestamp_stale_blocks_regardless_of_regime(self):
        """SPY freshness=700s in normal regime → SPY stale via
        timestamp → core_stale=True → gate fires."""
        snaps = {
            "SPY": _make_snap(is_stale=False, freshness_ms=700_000),
            "QQQ": _make_snap(is_stale=False, freshness_ms=60_000),
        }
        with _patch_api_key(), _patch_truth_layer(snaps):
            result = ohs.compute_market_data_freshness(
                universe=["SPY", "QQQ", "AAPL"],
                stale_threshold_ms=600 * 1000,
                regime="normal",
            )
        self.assertTrue(result.is_stale)
        self.assertIn("SPY", result.stale_symbols)


class TestResolveRegimeHelper(unittest.TestCase):
    """Unit tests for _resolve_regime_for_staleness."""

    def test_explicit_regime_returned_normalized(self):
        self.assertEqual(ohs._resolve_regime_for_staleness("SHOCK"), "shock")
        self.assertEqual(ohs._resolve_regime_for_staleness("  normal  "), "normal")

    def test_empty_string_treated_as_none(self):
        """Empty / whitespace regime triggers lookup fallback."""
        with patch(
            "packages.quantum.jobs.handlers.utils.get_admin_client",
            side_effect=Exception("no client"),
        ):
            self.assertEqual(ohs._resolve_regime_for_staleness(""), "shock")
            self.assertEqual(ohs._resolve_regime_for_staleness("   "), "shock")

    def test_none_with_lookup_failure_falls_back_to_shock(self):
        with patch(
            "packages.quantum.jobs.handlers.utils.get_admin_client",
            side_effect=Exception("supabase unavailable"),
        ):
            self.assertEqual(ohs._resolve_regime_for_staleness(None), "shock")

    def test_none_with_lookup_returning_last_regime(self):
        admin_client = MagicMock()
        admin_client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
            {
                "result": {
                    "cycle_results": [
                        {"cycle_metadata": {"regime": "elevated"}}
                    ]
                }
            }
        ]
        with patch(
            "packages.quantum.jobs.handlers.utils.get_admin_client",
            return_value=admin_client,
        ):
            self.assertEqual(ohs._resolve_regime_for_staleness(None), "elevated")

    def test_none_with_lookup_returning_no_rows_falls_back_to_shock(self):
        admin_client = MagicMock()
        admin_client.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []
        with patch(
            "packages.quantum.jobs.handlers.utils.get_admin_client",
            return_value=admin_client,
        ):
            self.assertEqual(ohs._resolve_regime_for_staleness(None), "shock")


if __name__ == "__main__":
    unittest.main()
