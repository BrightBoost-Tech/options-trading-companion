"""Admit the deep ETFs to the entry scan (2026-06-08 class-bug fix).

#1026/#1027 fixed the universe table + get_scan_candidates to return a
SCORE-ranked list (deep ETFs / mega-caps on top). But scan_for_opportunities
then undid them twice:
  (A) sorted(list(set(...))) at :2660 re-sorted ALPHABETICALLY, destroying the
      score order before any cap;
  (B) the SCANNER_LIMIT_DEV=40 cap was gated on `os.getenv("APP_ENV") !=
      "production"` — TRUE on the Railway worker because the worker sets
      RAILWAY_ENVIRONMENT=production but NOT APP_ENV — so the dev cap truncated
      the live scan to the alphabetically-first 40, dropping SPY/QQQ/TLT/XL*
      (all score 100) while admitting IWM (rank 32).

Fixes: order-preserving dedupe (dict.fromkeys) + route the cap through the
canonical is_production() (recognizes the Railway platform signal).
"""

import os
import sys
import types
import unittest
from unittest.mock import patch

sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
sys.modules.setdefault("alpaca.trading.requests", types.ModuleType("alpaca.trading.requests"))

from packages.quantum.security.config import is_production, is_production_env  # noqa: E402


# The 14 ETFs that were past the alphabetical 40-cut (alpha_rank > 40).
MISSED_14 = ["QQQ", "SMH", "SPY", "TLT", "XLB", "XLC", "XLE", "XLF",
             "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]


class TestCanonicalProductionCheck(unittest.TestCase):
    def _env(self, **kv):
        # Clear the three relevant signals, then set what's given.
        base = {}
        return patch.dict(os.environ, {**base, **kv}, clear=False)

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in
                       ("APP_ENV", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_ENVIRONMENT")}
        for k in self._saved:
            os.environ.pop(k, None)

    def tearDown(self):
        for k in ("APP_ENV", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_ENVIRONMENT"):
            os.environ.pop(k, None)
            if self._saved.get(k) is not None:
                os.environ[k] = self._saved[k]

    def test_app_env_production(self):
        with patch.dict(os.environ, {"APP_ENV": "production"}):
            self.assertTrue(is_production())

    def test_railway_name_production_is_the_worker_fix(self):
        # The worker: no APP_ENV, RAILWAY_ENVIRONMENT_NAME=production.
        with patch.dict(os.environ, {"RAILWAY_ENVIRONMENT_NAME": "production"}):
            self.assertTrue(is_production())

    def test_railway_environment_production(self):
        with patch.dict(os.environ, {"RAILWAY_ENVIRONMENT": "production"}):
            self.assertTrue(is_production())

    def test_neither_is_dev(self):
        # genuine dev / test: none of the signals set.
        self.assertFalse(is_production())

    def test_is_production_env_delegates(self):
        # H13: the security helper now delegates to the canonical check.
        with patch.dict(os.environ, {"RAILWAY_ENVIRONMENT_NAME": "production"}):
            self.assertTrue(is_production_env())
        # ...and stays True on the BE (APP_ENV=production), unchanged.
        with patch.dict(os.environ, {"APP_ENV": "production"}):
            self.assertTrue(is_production_env())


# ── Scanner ordering + cap (pure logic, no live scan) ───────────────────────
# Reproduce the two transformed lines exactly as they run in
# scan_for_opportunities, so the test pins the behavior without driving the
# full (heavy) scanner.

def _normalize(s):  # equities unchanged; matches truth_layer for tickers
    return s


def _scan_select(score_ranked_symbols, prod, scanner_limit_dev=40):
    """The :2660 + :2663-2664 logic post-fix."""
    symbols = list(dict.fromkeys(_normalize(s) for s in score_ranked_symbols))
    if not prod:
        symbols = symbols[:scanner_limit_dev]
    return symbols


# 74 active, score-ranked: ETFs/mega-caps first (the get_scan_candidates order).
# Deep ETFs at the TOP, then 60 single names A..Z to push past 40.
_SCORE_RANKED = (
    ["SPY", "QQQ", "IWM", "TLT", "HYG", "EEM", "EWZ", "XLE", "XLF", "XLK"]
    + [f"N{i:02d}" for i in range(60)]   # filler single names, lower score
)


class TestScannerOrderingAndCap(unittest.TestCase):
    def test_order_preserved_not_alphabetical(self):
        out = _scan_select(_SCORE_RANKED, prod=True)
        # Score order kept: SPY first, not alphabetically (EEM would be first).
        self.assertEqual(out[0], "SPY")
        self.assertEqual(out[:5], ["SPY", "QQQ", "IWM", "TLT", "HYG"])

    def test_production_does_not_truncate(self):
        out = _scan_select(_SCORE_RANKED, prod=True)
        self.assertEqual(len(out), len(_SCORE_RANKED))  # all reach eval

    def test_production_includes_the_missed_14(self):
        ranked = MISSED_14 + [f"N{i:02d}" for i in range(60)]
        out = _scan_select(ranked, prod=True)
        for etf in MISSED_14:
            self.assertIn(etf, out, f"{etf} must reach eval in prod")

    def test_dev_still_truncates_to_40_but_by_score(self):
        out = _scan_select(_SCORE_RANKED, prod=False)
        self.assertEqual(len(out), 40)
        # The deep ETFs (top score) survive the dev cut now (were dropped when
        # the cut was alphabetical).
        for etf in ["SPY", "QQQ", "IWM", "TLT"]:
            self.assertIn(etf, out)

    def test_dedupe_and_normalize_preserved(self):
        dupes = ["SPY", "SPY", "QQQ", "IWM", "QQQ"]
        out = _scan_select(dupes, prod=True)
        self.assertEqual(out, ["SPY", "QQQ", "IWM"])

    def test_live_scanner_source_pins(self):
        """The live scan_for_opportunities uses the order-preserving dedupe +
        the canonical prod gate — not sorted(set()) / bare APP_ENV."""
        import inspect
        from packages.quantum import options_scanner
        src = inspect.getsource(options_scanner.scan_for_opportunities)
        self.assertIn("dict.fromkeys(", src)
        self.assertIn("if not is_production():", src)
        # the two undoing constructs are gone from the executable lines
        self.assertNotIn("symbols = sorted(list(set(", src)
        self.assertNotIn('if os.getenv("APP_ENV") != "production":', src)


# ── Slippage guardrail: dev-leniency must not fire in prod (same class bug) ──

class TestSlippageGuardrailProdNoLeniency(unittest.TestCase):
    def setUp(self):
        from packages.quantum.analytics import guardrails
        self.guardrails = guardrails

    def test_no_quote_rejected_in_production(self):
        # Worker prod (RAILWAY signal): a no-quote trade must be REJECTED (0.0),
        # not waved through by the dev leniency.
        with patch.dict(os.environ, {"RAILWAY_ENVIRONMENT_NAME": "production"}, clear=False):
            os.environ.pop("APP_ENV", None)
            mult = self.guardrails.apply_slippage_guardrail({}, {"bid": 0.0, "ask": 0.0})
        self.assertEqual(mult, 0.0)

    def test_no_quote_lenient_in_dev(self):
        with patch.dict(os.environ, {}, clear=False):
            for k in ("APP_ENV", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_ENVIRONMENT"):
                os.environ.pop(k, None)
            mult = self.guardrails.apply_slippage_guardrail({}, {"bid": 0.0, "ask": 0.0})
        self.assertEqual(mult, 1.0)  # dev leniency: don't kill the trade

    def test_real_quote_unaffected_by_env(self):
        # A tight real quote scores the same regardless of env.
        with patch.dict(os.environ, {"RAILWAY_ENVIRONMENT_NAME": "production"}, clear=False):
            os.environ.pop("APP_ENV", None)
            prod = self.guardrails.apply_slippage_guardrail({}, {"bid": 1.00, "ask": 1.02})
        with patch.dict(os.environ, {}, clear=False):
            for k in ("APP_ENV", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_ENVIRONMENT"):
                os.environ.pop(k, None)
            dev = self.guardrails.apply_slippage_guardrail({}, {"bid": 1.00, "ask": 1.02})
        self.assertEqual(prod, dev)
        self.assertGreater(prod, 0.0)


if __name__ == "__main__":
    unittest.main()
