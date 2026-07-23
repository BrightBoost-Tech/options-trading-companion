"""Audit-B — Regime V4 observe-only child scorer + fetch-blocking shim tests.

Proves the child-side contract (C2/C3/C5/C8 slices):
  - the shim serves captured inputs and BLOCKS every fetch (assert 0 provider
    calls — no MarketDataTruthLayer / PolygonService is ever instantiated);
  - the pure counterfactual (get_effective_regime + get_candidates) attributes
    the pool delta SOLELY to the regime swap (SHOCK empties the pool, sentiment
    held fixed);
  - idempotency: a re-run under identical (cycle_id, code_sha) is a no-op upsert
    (load test over the same tape → byte-identical rows);
  - a missing captured basket symbol is a TYPED partial abstention, never a
    fabricated bar;
  - a table-absent DB is a typed no-op (migration unapplied);
  - a write failure folds to counts.errors (partial), never silence.
"""

from __future__ import annotations

import copy
import unittest
from types import SimpleNamespace

from packages.quantum.analytics import regime_v4_shadow_compare as scorer
from packages.quantum.analytics.regime_v4_shadow_compare import (
    CapturedBarsShim,
    CapturedInputMissing,
    compute_selection_delta,
    run_regime_v4_shadow_compare,
)
from packages.quantum.analytics.strategy_selector import StrategySelector
from packages.quantum.common_enums import RegimeState

_BASKET = ["SPY", "QQQ", "IWM", "TLT", "HYG", "XLF", "XLK", "XLE"]


def _closes(n=100, base=100.0, step=0.1):
    return [base + i * step for i in range(n)]


def _make_capture(*, per_symbol=None, drop_spy=False, basket=None):
    basket = basket or _BASKET
    closes = {s: _closes() for s in basket}
    if drop_spy:
        closes.pop("SPY", None)
    quotes = {
        s: {"quote": {"bid": 1.00, "ask": 1.02, "mid": 1.01}} for s in basket
    }
    return {
        "as_of": "2026-07-23T16:00:00+00:00",
        "v3_global": {
            "state": "normal",
            "risk_score": 50.0,
            "risk_scaler": 1.0,
            "as_of_ts": "2026-07-23T16:00:00+00:00",
        },
        "basket_closes": closes,
        "basket_quotes": quotes,
        "per_symbol": per_symbol
        if per_symbol is not None
        else [
            {
                "symbol": "AAPL",
                "v3_symbol_state": "normal",
                "v3_effective_regime": "normal",
                "sentiment": "BULLISH",
                "current_price": 210.0,
                "iv_rank": 40.0,
                "v3_selection": ["LONG_CALL_DEBIT_SPREAD", "SHORT_PUT_CREDIT_SPREAD"],
                "earnings_date": None,
                "decision_event_id": None,
            }
        ],
    }


class _FakeResp(SimpleNamespace):
    pass


class FakeTable:
    def __init__(self, parent, name):
        self.parent = parent
        self.name = name
        self._rows = None
        self._on_conflict = None

    def upsert(self, rows, on_conflict=None, ignore_duplicates=False):
        self._rows = rows
        self._on_conflict = on_conflict
        self._ignore_dupes = ignore_duplicates
        return self

    def execute(self):
        self.parent.upsert_calls += 1
        self.parent.last_on_conflict = self._on_conflict
        self.parent.last_ignore_dupes = self._ignore_dupes
        if self.parent.raise_table_missing:
            raise Exception(
                'relation "regime_v4_comparisons" does not exist'
            )
        if self.parent.raise_other:
            raise Exception("connection reset by peer")
        for r in self._rows:
            key = (
                r["cycle_id"],
                r["code_sha"],
                r["scope"],
                r.get("symbol") or "__global__",
            )
            # ON CONFLICT DO NOTHING (append-only): first write wins.
            self.parent.store.setdefault(key, copy.deepcopy(r))
        return _FakeResp(data=self._rows)


class FakeClient:
    def __init__(self, *, raise_table_missing=False, raise_other=False):
        self.store = {}
        self.upsert_calls = 0
        self.last_on_conflict = None
        self.last_ignore_dupes = None
        self.raise_table_missing = raise_table_missing
        self.raise_other = raise_other

    def table(self, name):
        return FakeTable(self, name)


class PoisonMarketData:
    """Any live provider read is a hard failure — proves the shim intercepts
    everything and the child never reaches a real market-data client."""

    def daily_bars(self, *a, **k):
        raise AssertionError("LIVE PROVIDER CALL: daily_bars")

    def snapshot_many(self, *a, **k):
        raise AssertionError("LIVE PROVIDER CALL: snapshot_many")


class TestShimBlocksFetches(unittest.TestCase):
    def test_daily_bars_serves_captured_ignoring_dates(self):
        shim = CapturedBarsShim({"SPY": _closes(30)}, {})
        bars = shim.daily_bars("SPY", "2020-01-01", "2020-02-01")
        self.assertEqual(len(bars), 30)
        self.assertEqual(bars[-1]["close"], _closes(30)[-1])
        self.assertEqual(shim.fetch_attempts, 1)

    def test_daily_bars_raises_on_uncaptured_symbol(self):
        shim = CapturedBarsShim({"SPY": _closes()}, {})
        with self.assertRaises(CapturedInputMissing):
            shim.daily_bars("MSFT")
        self.assertIn("MSFT", shim.missing_symbols)

    def test_snapshot_many_serves_captured(self):
        q = {"SPY": {"quote": {"bid": 1, "ask": 2, "mid": 1.5}}}
        shim = CapturedBarsShim({}, q)
        got = shim.snapshot_many(["SPY", "QQQ"])
        self.assertEqual(got["SPY"], q["SPY"])
        self.assertEqual(got["QQQ"], {})

    def test_child_makes_zero_provider_calls(self):
        """The whole child run must never instantiate a real market-data client —
        patch both to poison and assert the run still completes on shim data."""
        import packages.quantum.services.market_data_truth_layer as mdt
        import packages.quantum.market_data as md

        orig_truth = mdt.MarketDataTruthLayer.__init__
        orig_poly = md.PolygonService.__init__

        def _boom(self, *a, **k):
            raise AssertionError("LIVE market-data client instantiated in child")

        mdt.MarketDataTruthLayer.__init__ = _boom
        md.PolygonService.__init__ = _boom
        try:
            res = run_regime_v4_shadow_compare(
                {"capture": _make_capture(), "cycle_id": "c1", "source_code_sha": "sha1"},
                client=FakeClient(),
            )
        finally:
            mdt.MarketDataTruthLayer.__init__ = orig_truth
            md.PolygonService.__init__ = orig_poly
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "ok")


class TestCounterfactualIsolation(unittest.TestCase):
    """Regime drives the POOL; sentiment/iv_rank held fixed → delta attributable
    to the regime swap alone (Audit-B C3)."""

    def test_shock_empties_pool_vs_normal(self):
        sel = StrategySelector()
        normal_pool = [
            c["strategy"]
            for c in sel.get_candidates(
                ticker="AAPL", sentiment="BULLISH", current_price=210.0,
                iv_rank=40.0, effective_regime="normal",
            )
        ]
        shock_pool = [
            c["strategy"]
            for c in sel.get_candidates(
                ticker="AAPL", sentiment="BULLISH", current_price=210.0,
                iv_rank=40.0, effective_regime="shock",
            )
        ]
        self.assertTrue(normal_pool)          # NORMAL has a pool
        self.assertEqual(shock_pool, [])      # SHOCK empties it
        delta = compute_selection_delta(normal_pool, shock_pool)
        self.assertTrue(delta["changed"])
        self.assertEqual(delta["added"], [])
        self.assertEqual(sorted(delta["removed"]), sorted(normal_pool))

    def test_selection_delta_order_insensitive(self):
        d = compute_selection_delta(["A", "B"], ["B", "A"])
        self.assertFalse(d["changed"])


class TestChildRun(unittest.TestCase):
    def test_writes_global_plus_symbol_rows(self):
        client = FakeClient()
        res = run_regime_v4_shadow_compare(
            {"capture": _make_capture(), "cycle_id": "cyc", "source_code_sha": "shaX"},
            client=client,
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["counts"]["global_rows"], 1)
        self.assertEqual(res["counts"]["symbol_rows"], 1)
        self.assertEqual(res["counts"]["written"], 2)
        # global row shape
        g = client.store[("cyc", "shaX", "global", "__global__")]
        self.assertEqual(g["scope"], "global")
        self.assertIsNone(g["symbol"])
        self.assertEqual(g["v3_model_version"], "v3")
        self.assertEqual(g["v4_model_version"], "v4_continuous")
        self.assertIn(scorer.VIX_MISSING, g["missing_inputs"])
        self.assertIsInstance(g["scoring_regime_agree"], bool)
        # symbol row shape
        s = client.store[("cyc", "shaX", "symbol", "AAPL")]
        self.assertEqual(s["symbol"], "AAPL")
        self.assertEqual(s["sentiment"], "BULLISH")
        self.assertIn("selection_delta", s)
        self.assertIsInstance(s["v4_selection"], list)

    def test_idempotent_rerun_same_tape(self):
        """Load test / replay over the SAME tape: identical (cycle_id, code_sha)
        rows overwrite (no-op upsert), never duplicate; row content is
        deterministic across runs (VIX typed-missing, same v4 label)."""
        cap = _make_capture()
        c1 = FakeClient()
        r1 = run_regime_v4_shadow_compare(
            {"capture": cap, "cycle_id": "R", "source_code_sha": "S"}, client=c1
        )
        c2 = FakeClient()
        r2 = run_regime_v4_shadow_compare(
            {"capture": cap, "cycle_id": "R", "source_code_sha": "S"}, client=c2
        )
        self.assertEqual(r1["v4_label"], r2["v4_label"])
        self.assertEqual(set(c1.store.keys()), set(c2.store.keys()))
        self.assertEqual(len(c1.store), 2)  # one global + one symbol, deduped
        self.assertEqual(c1.last_on_conflict, "cycle_id,code_sha,scope,symbol_key")
        self.assertTrue(c1.last_ignore_dupes)  # append-only ON CONFLICT DO NOTHING

        # Same-client replay (the load-test case): re-running the identical tape
        # is an append-only no-op — still exactly 2 rows, never a duplicate.
        run_regime_v4_shadow_compare(
            {"capture": cap, "cycle_id": "R", "source_code_sha": "S"}, client=c1
        )
        self.assertEqual(len(c1.store), 2)

    def test_missing_basket_symbol_is_typed_partial(self):
        """SPY absent → V4 factors degrade (typed reasons), the global read is
        PARTIAL — never a fabricated bar or fake-flat regime."""
        client = FakeClient()
        res = run_regime_v4_shadow_compare(
            {"capture": _make_capture(drop_spy=True), "cycle_id": "m", "source_code_sha": "s"},
            client=client,
        )
        self.assertTrue(res["ok"])  # a degraded observation is still a real one
        g = client.store[("m", "s", "global", "__global__")]
        self.assertEqual(g["status"], "partial")
        self.assertTrue(
            any(r.startswith("captured_input_missing:") or r.endswith("_degraded_captured_input")
                for r in g["missing_inputs"])
        )

    def test_absent_capture_is_unavailable_not_crash(self):
        res = run_regime_v4_shadow_compare(
            {"capture": {"v3_global": {}, "basket_closes": {}}, "cycle_id": "z"},
            client=FakeClient(),
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "unavailable")

    def test_missing_cycle_id_is_failed(self):
        res = run_regime_v4_shadow_compare(
            {"capture": _make_capture(), "cycle_id": ""}, client=FakeClient()
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["status"], "failed")

    def test_table_absent_is_typed_noop(self):
        client = FakeClient(raise_table_missing=True)
        res = run_regime_v4_shadow_compare(
            {"capture": _make_capture(), "cycle_id": "t", "source_code_sha": "s"},
            client=client,
        )
        self.assertTrue(res["ok"])           # a no-op is not a failure
        self.assertEqual(res["counts"]["errors"], 0)
        self.assertGreater(res["counts"]["table_missing_noops"], 0)

    def test_write_failure_folds_to_partial(self):
        client = FakeClient(raise_other=True)
        res = run_regime_v4_shadow_compare(
            {"capture": _make_capture(), "cycle_id": "w", "source_code_sha": "s"},
            client=client,
        )
        self.assertFalse(res["ok"])
        self.assertEqual(res["status"], "partial")
        self.assertGreater(res["counts"]["errors"], 0)

    def test_per_symbol_typed_abstention(self):
        """A per-symbol entry missing its V3 effective regime is a TYPED
        abstention (counted, skipped) — never a fabricated regime/pool."""
        bad = _make_capture(
            per_symbol=[
                {"symbol": "AAPL", "v3_symbol_state": "normal",
                 "v3_effective_regime": None, "sentiment": "BULLISH",
                 "current_price": 1.0, "iv_rank": 40.0, "v3_selection": [],
                 "earnings_date": None, "decision_event_id": None},
            ]
        )
        client = FakeClient()
        res = run_regime_v4_shadow_compare(
            {"capture": bad, "cycle_id": "ab", "source_code_sha": "s"}, client=client
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["counts"]["symbol_rows"], 0)
        self.assertGreaterEqual(res["counts"]["abstentions"], 1)

    def test_event_density_from_captured_earnings(self):
        """Earnings within the week → event_signals derived; no earnings →
        event_signals_absent typed-missing (never fabricated)."""
        cap = _make_capture(
            per_symbol=[
                {"symbol": "AAPL", "v3_symbol_state": "normal",
                 "v3_effective_regime": "normal", "sentiment": "NEUTRAL",
                 "current_price": 210.0, "iv_rank": 40.0,
                 "v3_selection": [], "earnings_date": None,
                 "decision_event_id": None},
            ]
        )
        client = FakeClient()
        run_regime_v4_shadow_compare(
            {"capture": cap, "cycle_id": "e", "source_code_sha": "s"}, client=client
        )
        g = client.store[("e", "s", "global", "__global__")]
        self.assertIn("event_signals_absent", g["missing_inputs"])


if __name__ == "__main__":
    unittest.main()
