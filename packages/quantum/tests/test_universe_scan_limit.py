"""Tests for the UNIVERSE_SCAN_LIMIT bridge (config/parameter only).

The 2026-06-05 universe-selection diagnostic found INVERTED selection: the
equity liquidity_score awards ETFs 0/40 market-cap points, hard-capping
SPY/QQQ/IWM/sector-ETFs at 60 and statically dropping the same 24 symbols
from every limit=50 scan, while measured option-dead single names
(option_liquidity_score=0.0) passed at 90. The bridge raises the scanner's
universe limit above the full active set (74) via an env-configurable
UNIVERSE_SCAN_LIMIT (default 100) so the broken ranking never excludes
anyone. NO scoring/scanner/gate/exit logic is touched.

These tests verify ONLY the parameter plumbing:
- default is 100 (> 74 active, headroom for adds)
- env override is honored (lenient parse)
- garbage / non-positive env values fail soft to the default
- the hardcoded limit=50 is gone from the get_scan_candidates call site
- the limit is read at CALL time, not import time
"""

import os
import sys
import types
import unittest
from unittest.mock import patch

# Stub alpaca-py so imports resolve in the test venv (mirrors
# test_intraday_target_profit / test_force_close_path).
sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
sys.modules.setdefault("alpaca.trading.requests", types.ModuleType("alpaca.trading.requests"))


class TestUniverseScanLimitParse(unittest.TestCase):
    """Lenient parse semantics of _universe_scan_limit()."""

    def setUp(self):
        from packages.quantum import options_scanner
        self.scanner = options_scanner

    def _with_env(self, value):
        if value is None:
            env_patch = patch.dict(os.environ, {}, clear=False)
            os.environ.pop("UNIVERSE_SCAN_LIMIT", None)
            return env_patch
        return patch.dict(os.environ, {"UNIVERSE_SCAN_LIMIT": value}, clear=False)

    def test_default_is_100(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("UNIVERSE_SCAN_LIMIT", None)
            self.assertEqual(self.scanner._universe_scan_limit(), 100)

    def test_default_clears_full_active_universe(self):
        # 74 active as of 2026-06-05; the default must clear it with headroom
        # or the bridge silently reverts to ranked exclusion as adds land.
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("UNIVERSE_SCAN_LIMIT", None)
            self.assertGreater(self.scanner._universe_scan_limit(), 74)

    def test_env_override_honored(self):
        with patch.dict(os.environ, {"UNIVERSE_SCAN_LIMIT": "150"}):
            self.assertEqual(self.scanner._universe_scan_limit(), 150)

    def test_env_override_with_whitespace(self):
        with patch.dict(os.environ, {"UNIVERSE_SCAN_LIMIT": " 80 "}):
            self.assertEqual(self.scanner._universe_scan_limit(), 80)

    def test_garbage_value_falls_back_to_default(self):
        # Fail-soft: a typo'd env var must not kill the scan cycle.
        for garbage in ("all", "fifty", "1.5", "true", ""):
            with patch.dict(os.environ, {"UNIVERSE_SCAN_LIMIT": garbage}):
                self.assertEqual(
                    self.scanner._universe_scan_limit(), 100,
                    f"garbage value {garbage!r} should fall back to default",
                )

    def test_non_positive_falls_back_to_default(self):
        # limit=0 / negative would silently empty the scan — fail soft.
        for bad in ("0", "-5"):
            with patch.dict(os.environ, {"UNIVERSE_SCAN_LIMIT": bad}):
                self.assertEqual(self.scanner._universe_scan_limit(), 100)

    def test_read_at_call_time_not_import_time(self):
        # The whole point of the function (vs a module constant): env changes
        # apply on the next call without a worker reimport.
        with patch.dict(os.environ, {"UNIVERSE_SCAN_LIMIT": "90"}):
            self.assertEqual(self.scanner._universe_scan_limit(), 90)
        with patch.dict(os.environ, {"UNIVERSE_SCAN_LIMIT": "120"}):
            self.assertEqual(self.scanner._universe_scan_limit(), 120)


class TestCallSiteUsesConfigurableLimit(unittest.TestCase):
    """Source pin: the scanner's get_scan_candidates call uses the helper,
    and the hardcoded limit=50 is gone from that call site."""

    def setUp(self):
        import inspect
        from packages.quantum import options_scanner
        self.source = inspect.getsource(options_scanner.scan_for_opportunities)

    def test_call_site_uses_helper(self):
        self.assertIn("limit=_universe_scan_limit()", self.source)

    def test_hardcoded_50_is_gone(self):
        self.assertNotIn("limit=50", self.source)

    def test_caller_attribution_preserved(self):
        # universe_selection_log attribution (H9 verified-decision) must keep
        # identifying this call site.
        self.assertIn(
            'caller="options_scanner.scan_for_opportunities"', self.source
        )


if __name__ == "__main__":
    unittest.main()
