"""Tests for option-liquidity weighting (OBSERVATION-FIRST, flag-gated).

Re-derivation (2026-06-02): the OPTION spread gate (liquidity) is the dominant
entry wall, and the universe's equity liquidity_score ranks liquid-stock /
wide-option names (SNAP/NIO/AAL/LYFT) high, diluting scan effort. This feature
computes a per-symbol OPTION-liquidity score from the ATM bid-ask relative
spread, logs it (observe-first), and — only when LIQUIDITY_WEIGHTING_ENABLED —
re-orders the universe to de-PRIORITIZE (not drop) wide-option names.

Load-bearing: with the flag OFF, universe selection is byte-identical AND does
not reference the new column (migration-independent).
"""

import os
import unittest
from unittest import mock

from packages.quantum.analytics import option_liquidity as ol

# Capture the REAL scanner observe-fn at collection time. test_weekly_report_
# win_rate replaces sys.modules['packages.quantum.options_scanner'] with a
# MagicMock for the whole session; collecting alphabetically AFTER this file, so
# this top-level import still binds the real module (documented sys.modules
# pollution class — production is never affected).
from packages.quantum.options_scanner import _observe_option_liquidity as _REAL_OBSERVE


def _contract(strike, right, bid, ask):
    return {"strike": float(strike), "right": right,
            "quote": {"bid": bid, "ask": ask, "mid": (bid + ask) / 2.0}}


class TestScore(unittest.TestCase):
    def test_tight_atm_scores_high_wide_scores_low(self):
        spot = 50.0
        tight_chain = [_contract(50, "call", 4.95, 5.05), _contract(50, "put", 4.95, 5.05)]
        wide_chain = [_contract(50, "call", 0.20, 0.40), _contract(50, "put", 0.20, 0.40)]
        s_tight = ol.liquidity_score(ol.atm_relative_spread(tight_chain, spot))
        s_wide = ol.liquidity_score(ol.atm_relative_spread(wide_chain, spot))
        self.assertGreater(s_tight, s_wide)
        self.assertEqual(s_tight, 100.0)        # <=3% rel spread → fully liquid
        self.assertEqual(s_wide, 0.0)           # >=20% rel spread → fully illiquid

    def test_cheap_wide_name_below_liquid_midcap(self):
        # SNAP-like (cheap, wide options) must score BELOW BAC-like (liquid).
        snap = [_contract(6, "call", 0.10, 0.22), _contract(6, "put", 0.10, 0.22)]   # ~75% rel
        bac = [_contract(53, "call", 1.45, 1.55), _contract(53, "put", 1.45, 1.55)]  # ~6.7% rel
        self.assertLess(
            ol.liquidity_score(ol.atm_relative_spread(snap, 6.0)),
            ol.liquidity_score(ol.atm_relative_spread(bac, 53.0)),
        )

    def test_na_when_no_nbbo(self):
        self.assertIsNone(ol.atm_relative_spread([_contract(50, "call", 0, 0)], 50.0))
        self.assertIsNone(ol.atm_relative_spread([], 50.0))
        self.assertIsNone(ol.liquidity_score(None))


class TestWeightNeverHardDrop(unittest.TestCase):
    def test_weight_floor_is_min_weight(self):
        # Even the lowest-liquidity name keeps min_weight priority (reversible).
        self.assertEqual(ol.would_be_weight(0.0), ol.FLAGGED_ASSUMPTIONS["min_weight"])
        self.assertEqual(ol.would_be_weight(100.0), ol.FLAGGED_ASSUMPTIONS["max_weight"])
        self.assertGreaterEqual(ol.would_be_weight(5.0), ol.FLAGGED_ASSUMPTIONS["min_weight"])

    def test_unknown_score_no_deprioritization(self):
        self.assertEqual(ol.would_be_weight(None), ol.FLAGGED_ASSUMPTIONS["max_weight"])


class TestFlagDefaultOff(unittest.TestCase):
    def test_default_off(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(ol.is_weighting_enabled())


# ── Universe selection: flag OFF byte-identical, flag ON de-prioritizes ──

class _Resp:
    def __init__(self, data):
        self.data = data


class _Tbl:
    def __init__(self, name, rows, recorder):
        self.name = name
        self.rows = rows
        self.rec = recorder
        self._cols = None

    def select(self, cols):
        self._cols = cols
        self.rec.setdefault("selects", {})[self.name] = cols
        return self

    def eq(self, *a):
        return self

    def order(self, *a, **k):
        return self

    def insert(self, payload):
        return self

    def update(self, payload):
        return self

    def execute(self):
        if self.name == "scanner_universe" and self._cols and "symbol" in self._cols:
            return _Resp(list(self.rows))
        return _Resp([{"id": "log-row"}])  # universe_selection_log insert verified-write


class _Supa:
    def __init__(self, rows):
        self.rows = rows
        self.rec = {}

    def table(self, name):
        return _Tbl(name, self.rows, self.rec)


# DB returns rows in liquidity_score DESC order (PostgREST .order applied server-side)
_ROWS = [
    {"symbol": "SNAP", "earnings_date": None, "liquidity_score": 90, "option_liquidity_score": 10},
    {"symbol": "BAC", "earnings_date": None, "liquidity_score": 80, "option_liquidity_score": 95},
    {"symbol": "CSX", "earnings_date": None, "liquidity_score": 70, "option_liquidity_score": 90},
]


def _pin_real_option_liquidity():
    """Defend against in-suite contamination: some scanner tests reload
    options_scanner while packages.quantum.analytics submodules are stubbed in
    sys.modules, rebinding the module-level `_option_liquidity` to a MagicMock.
    Re-pin the REAL module so these tests exercise the real scoring path
    (production is never contaminated — this is a test-env artifact, same class
    as the documented regime_engine_v3 sys.modules pollution)."""
    import packages.quantum.options_scanner as _osc
    import packages.quantum.services.universe_service as _us
    _osc._option_liquidity = ol
    _us._option_liquidity = ol


def _svc(rows):
    from packages.quantum.services.universe_service import UniverseService
    svc = UniverseService.__new__(UniverseService)
    svc.supabase = _Supa(rows)
    return svc


class TestUniverseWeighting(unittest.TestCase):
    def setUp(self):
        _pin_real_option_liquidity()

    def test_flag_off_byte_identical_and_no_new_column(self):
        svc = _svc(_ROWS)
        with mock.patch.dict(os.environ, {}, clear=True):
            cands = svc.get_scan_candidates(limit=3)
        # DB (liquidity_score DESC) order preserved
        self.assertEqual([c["symbol"] for c in cands], ["SNAP", "BAC", "CSX"])
        # migration-independence: OFF path must NOT select the new column
        self.assertNotIn("option_liquidity_score", svc.supabase.rec["selects"]["scanner_universe"])

    def test_flag_on_deprioritizes_wide_option_name_without_dropping(self):
        svc = _svc(_ROWS)
        with mock.patch.dict(os.environ, {ol.FLAG_ENV: "1"}, clear=True):
            cands = svc.get_scan_candidates(limit=3)
        order = [c["symbol"] for c in cands]
        # SNAP (liquid stock, illiquid options) sinks to LAST but is NOT dropped
        self.assertEqual(order[-1], "SNAP")
        self.assertIn("SNAP", order)
        # the liquid-affordable middle is NOT de-weighted (stays ahead of SNAP)
        self.assertLess(order.index("BAC"), order.index("SNAP"))
        self.assertLess(order.index("CSX"), order.index("SNAP"))
        # ON path selects the new column
        self.assertIn("option_liquidity_score", svc.supabase.rec["selects"]["scanner_universe"])

    def test_flag_on_soft_drop_below_cutoff_reversible(self):
        # With limit=2, weighting pushes SNAP below the cutoff (soft drop), and
        # CSX climbs in — a name that tightens its options would climb back.
        svc = _svc(_ROWS)
        with mock.patch.dict(os.environ, {ol.FLAG_ENV: "1"}, clear=True):
            top2 = [c["symbol"] for c in svc.get_scan_candidates(limit=2)]
        self.assertEqual(top2, ["BAC", "CSX"])
        self.assertNotIn("SNAP", top2)


class TestObserveFailSoft(unittest.TestCase):
    def setUp(self):
        _pin_real_option_liquidity()

    def test_observe_never_raises(self):
        _observe_option_liquidity = _REAL_OBSERVE
        # None client, empty chain, bad price — must all be silent no-ops
        _observe_option_liquidity(None, "X", [], 50.0)
        _observe_option_liquidity(None, "X", [_contract(50, "call", 1, 1.1)], None)

    def test_observe_logs_score_and_rolls_universe(self):
        _observe_option_liquidity = _REAL_OBSERVE
        inserts, updates = [], []

        class _T:
            def __init__(self, name):
                self.name = name
            def insert(self, p):
                inserts.append((self.name, p)); return self
            def update(self, p):
                updates.append((self.name, p)); return self
            def eq(self, *a):
                return self
            def execute(self):
                return _Resp([{"id": 1}])

        class _S:
            def table(self, n):
                return _T(n)

        chain = [_contract(50, "call", 4.95, 5.05), _contract(50, "put", 4.95, 5.05)]
        _observe_option_liquidity(_S(), "BAC", chain, 50.0)
        self.assertTrue(any(n == "option_liquidity_observations" for n, _ in inserts))
        self.assertTrue(any(n == "scanner_universe" for n, _ in updates))
        obs = next(p for n, p in inserts if n == "option_liquidity_observations")
        self.assertEqual(obs["liquidity_score"], 100.0)
        self.assertIn("assumptions", obs)


if __name__ == "__main__":
    unittest.main()
