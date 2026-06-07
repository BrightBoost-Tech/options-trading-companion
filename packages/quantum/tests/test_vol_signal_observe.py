"""Tests for the Stage 1 vol-signal OBSERVE layer (research only).

Pins the five design invariants:
1. Flag-gated (lenient parse, default OFF) — flag off writes NOTHING.
2. Missing inputs are FLAGGED + NULL, never fabricated or defaulted
   (the stale-VIX-20.0 anti-pattern).
3. NO composite score is computed or persisted — raw components only
   (validation derives weights from the record later).
4. Import boundary: the module + handler touch no scanner / trading /
   exit / regime computation path.
5. Forward-outcome backfill fills t+1/t+3 from available trading-day
   rows and skips rows whose horizon isn't resolvable yet.
"""

import os
import sys
import types
import unittest
from unittest.mock import patch

# Stub alpaca-py so transitive imports resolve in the test venv.
sys.modules.setdefault("alpaca", types.ModuleType("alpaca"))
sys.modules.setdefault("alpaca.trading", types.ModuleType("alpaca.trading"))
sys.modules.setdefault("alpaca.trading.requests", types.ModuleType("alpaca.trading.requests"))

from packages.quantum.analytics import vol_signal  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _iv_series(n=30, base=0.17, last=0.22):
    """Ascending IV history ending in a visible expansion."""
    s = [base + 0.001 * (i % 5) for i in range(n - 1)]
    s.append(last)
    return s


def _full_inputs():
    return dict(
        snapshot_ts="2026-06-07T10:15:00",
        as_of_date="2026-06-07",
        iv_histories={"SPY": _iv_series(), "QQQ": _iv_series(base=0.22),
                      "IWM": _iv_series(base=0.25)},
        spy_skew_25d=0.08,
        spy_term_slope=-0.012,
        etp_closes={s: [20.0 + i * 0.1 for i in range(10)]
                    for s in vol_signal.ETP_SYMBOLS},
        cross_asset_closes={s: [80.0 - i * 0.05 for i in range(10)]
                            for s in vol_signal.CROSS_ASSET_SYMBOLS},
        live_regime_state="normal",
        spy_spots=[500.0 + i for i in range(25)],
    )


class _FakeQuery:
    def __init__(self, parent, name):
        self.parent, self.name = parent, name
        self._mode = None
        self._payload = None
        self._filters = []

    def upsert(self, row, on_conflict=None):
        self._mode = ("upsert", row, on_conflict)
        return self

    def select(self, *a, **k):
        self._mode = ("select",)
        return self

    def update(self, patch):
        self._mode = ("update", patch)
        return self

    def is_(self, col, val):
        self._filters.append(("is", col, val))
        return self

    def eq(self, col, val):
        self._filters.append(("eq", col, val))
        return self

    def execute(self):
        self.parent.calls.append((self.name, self._mode, list(self._filters)))
        if self._mode and self._mode[0] == "select":
            return types.SimpleNamespace(data=list(self.parent.pending_rows))
        return types.SimpleNamespace(data=[{"ok": True}])


class _FakeSupabase:
    def __init__(self, pending_rows=None, raise_on_write=False):
        self.calls = []
        self.pending_rows = pending_rows or []
        self.raise_on_write = raise_on_write

    def table(self, name):
        if self.raise_on_write:
            raise RuntimeError("db down")
        return _FakeQuery(self, name)


# ---------------------------------------------------------------------------
# 1. Flag gate
# ---------------------------------------------------------------------------

class TestFlagGate(unittest.TestCase):
    def test_default_off(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(vol_signal.FLAG_ENV, None)
            self.assertFalse(vol_signal.is_observe_enabled())

    def test_lenient_on_values(self):
        for v in ("1", "true", "yes", "on", "TRUE", " On "):
            with patch.dict(os.environ, {vol_signal.FLAG_ENV: v}):
                self.assertTrue(vol_signal.is_observe_enabled(), v)

    def test_off_values(self):
        for v in ("0", "false", "no", "off", ""):
            with patch.dict(os.environ, {vol_signal.FLAG_ENV: v}):
                self.assertFalse(vol_signal.is_observe_enabled(), v)

    def test_handler_flag_off_writes_nothing(self):
        """Flag off → cheap no-op: no DB client, no market data, no write."""
        from packages.quantum.jobs.handlers import vol_signal_snapshot as h
        with patch.dict(os.environ, {vol_signal.FLAG_ENV: "0"}), patch(
            "packages.quantum.jobs.handlers.vol_signal_snapshot.get_admin_client",
            side_effect=AssertionError("must not touch DB when flag off"),
        ):
            out = h.run({})
        self.assertEqual(out["status"], "flag_off")


# ---------------------------------------------------------------------------
# 2. Component math
# ---------------------------------------------------------------------------

class TestComponents(unittest.TestCase):
    def test_iv_components_from_fixture(self):
        comp = vol_signal.compute_iv_components(_iv_series())
        self.assertAlmostEqual(comp["level"], 0.22)
        self.assertEqual(comp["pctl"], 1.0)  # expansion: above all history
        self.assertGreater(comp["chg_1d"], 0)
        self.assertGreater(comp["chg_5d"], 0)

    def test_iv_components_empty_is_none(self):
        self.assertIsNone(vol_signal.compute_iv_components([]))

    def test_iv_components_short_series_nulls_changes(self):
        # 1 point: level only — pctl/changes None, never defaulted.
        comp = vol_signal.compute_iv_components([0.2])
        self.assertEqual(comp["level"], 0.2)
        self.assertIsNone(comp["pctl"])
        self.assertIsNone(comp["chg_1d"])
        self.assertIsNone(comp["chg_5d"])

    def test_percentile_rank(self):
        self.assertEqual(vol_signal.percentile_rank([1, 2, 3, 4], 3.5), 0.75)
        self.assertIsNone(vol_signal.percentile_rank([], 1.0))

    def test_return_components(self):
        comp = vol_signal.compute_return_components([100, 101, 102, 103, 104, 105, 110])
        self.assertEqual(comp["close"], 110)
        self.assertAlmostEqual(comp["ret_1d"], 110 / 105 - 1)
        self.assertAlmostEqual(comp["ret_5d"], 110 / 101 - 1)

    def test_rv_20d_needs_21_points(self):
        self.assertIsNone(vol_signal.compute_rv_20d([100.0] * 20))
        self.assertEqual(vol_signal.compute_rv_20d([100.0] * 21), 0.0)
        self.assertGreater(
            vol_signal.compute_rv_20d([100.0 + (i % 2) for i in range(25)]), 0)


# ---------------------------------------------------------------------------
# 3. Row assembly: missing inputs flagged, not fabricated; no score
# ---------------------------------------------------------------------------

class TestBuildObservation(unittest.TestCase):
    def test_full_inputs_all_live(self):
        row = vol_signal.build_observation(**_full_inputs())
        st = row["input_status"]
        self.assertEqual(st["spy_iv30"], "live")
        self.assertEqual(st["vxx"], "live")
        self.assertEqual(st["hyg"], "live")
        self.assertEqual(st["spy_skew_25d"], "computed")
        self.assertEqual(st["spy_rv_20d"], "computed")
        self.assertEqual(row["history_window_days"], 30)
        self.assertAlmostEqual(row["spy_iv30"], 0.22)
        self.assertEqual(row["live_regime_state"], "normal")

    def test_missing_inputs_flagged_and_null_never_defaulted(self):
        inputs = _full_inputs()
        inputs["iv_histories"] = {"SPY": _iv_series(), "QQQ": [], "IWM": []}
        inputs["spy_skew_25d"] = None
        inputs["etp_closes"] = {"VXX": [20, 21], "VIXY": [], "UVXY": [], "SVXY": []}
        inputs["cross_asset_closes"] = {s: [] for s in vol_signal.CROSS_ASSET_SYMBOLS}
        inputs["live_regime_state"] = None
        inputs["spy_spots"] = []
        row = vol_signal.build_observation(**inputs)
        st = row["input_status"]
        # Flagged...
        self.assertEqual(st["qqq_iv30"], "missing")
        self.assertEqual(st["uvxy"], "missing")
        self.assertEqual(st["hyg"], "missing")
        self.assertEqual(st["spy_skew_25d"], "missing")
        self.assertEqual(st["live_regime_state"], "missing")
        self.assertEqual(st["spy_rv_20d"], "missing")
        # ...and NULL — no fabricated levels, no 20.0-style defaults anywhere.
        self.assertIsNone(row["qqq_iv30"])
        self.assertIsNone(row["uvxy_close"])
        self.assertIsNone(row["hyg_ret_1d"])
        self.assertIsNone(row["spy_skew_25d"])
        self.assertIsNone(row["spy_rv_20d"])
        # Partial inputs degrade to None, never to a guess.
        self.assertIsNone(row["vxx_ret_5d"])  # only 2 closes available
        self.assertIsNotNone(row["vxx_ret_1d"])

    def test_no_composite_score_anywhere(self):
        """CRITICAL pin: raw components only. No weighted score is computed,
        persisted, or even named — weights are DERIVED from this data later."""
        row = vol_signal.build_observation(**_full_inputs())
        score_keys = [k for k in row if "score" in k.lower()]
        self.assertEqual(score_keys, [], f"composite-score keys found: {score_keys}")
        import inspect
        source = inspect.getsource(vol_signal)
        self.assertNotIn("vol_expansion_score", source)
        # No hardcoded weight constants (the external doc's anti-pattern).
        self.assertNotIn("w_vol", source)
        self.assertNotIn("WEIGHTS", source)


# ---------------------------------------------------------------------------
# 4. Observe write + fail-soft
# ---------------------------------------------------------------------------

class TestObserveWrite(unittest.TestCase):
    def test_upserts_on_as_of_date(self):
        fake = _FakeSupabase()
        row = {"as_of_date": "2026-06-07", "spy_iv30": 0.22}
        out = vol_signal.observe_vol_signal(fake, row)
        self.assertEqual(out, row)
        name, mode, _ = fake.calls[0]
        self.assertEqual(name, vol_signal.OBS_TABLE)
        self.assertEqual(mode[0], "upsert")
        self.assertEqual(mode[2], "as_of_date")

    def test_fail_soft_on_db_error(self):
        fake = _FakeSupabase(raise_on_write=True)
        out = vol_signal.observe_vol_signal(fake, {"as_of_date": "2026-06-07"})
        self.assertIsNone(out)  # never raises into the host job


# ---------------------------------------------------------------------------
# 5. Forward-outcome backfill
# ---------------------------------------------------------------------------

class TestForwardBackfill(unittest.TestCase):
    IV_DATES = ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"]
    IV = {"2026-06-01": 0.17, "2026-06-02": 0.18, "2026-06-03": 0.20,
          "2026-06-04": 0.19, "2026-06-05": 0.22}
    SPOT = {"2026-06-01": 500.0, "2026-06-02": 495.0, "2026-06-03": 490.0,
            "2026-06-04": 492.0, "2026-06-05": 485.0}
    BOOK = {"2026-06-01": -50.0, "2026-06-02": -120.0}

    def test_fills_resolvable_row(self):
        fake = _FakeSupabase(pending_rows=[{"id": "obs-1", "as_of_date": "2026-06-01"}])
        n = vol_signal.backfill_forward_outcomes(
            fake, iv_dates=self.IV_DATES, iv_by_date=self.IV,
            spot_by_date=self.SPOT, book_pl_by_date=self.BOOK)
        self.assertEqual(n, 1)
        update_calls = [c for c in fake.calls if c[1] and c[1][0] == "update"]
        self.assertEqual(len(update_calls), 1)
        patch_ = update_calls[0][1][1]
        self.assertAlmostEqual(patch_["vol_forward_1d"], 0.18 - 0.17)
        self.assertAlmostEqual(patch_["vol_forward_3d"], 0.19 - 0.17)
        self.assertAlmostEqual(patch_["spy_forward_1d"], 495.0 / 500.0 - 1)
        self.assertAlmostEqual(patch_["spy_forward_3d"], 492.0 / 500.0 - 1)
        self.assertAlmostEqual(patch_["book_forward_1d"], -120.0 - (-50.0))

    def test_unresolvable_horizon_skipped_not_stamped(self):
        # 06-04's t+3 doesn't exist yet → skip entirely, retry next run.
        fake = _FakeSupabase(pending_rows=[{"id": "obs-2", "as_of_date": "2026-06-04"}])
        n = vol_signal.backfill_forward_outcomes(
            fake, iv_dates=self.IV_DATES, iv_by_date=self.IV,
            spot_by_date=self.SPOT, book_pl_by_date=self.BOOK)
        self.assertEqual(n, 0)
        self.assertEqual([c for c in fake.calls if c[1] and c[1][0] == "update"], [])

    def test_missing_book_data_nulls_field_only(self):
        # Book P&L absent for the dates → book_forward_1d None; rest filled.
        fake = _FakeSupabase(pending_rows=[{"id": "obs-3", "as_of_date": "2026-06-02"}])
        n = vol_signal.backfill_forward_outcomes(
            fake, iv_dates=self.IV_DATES, iv_by_date=self.IV,
            spot_by_date=self.SPOT, book_pl_by_date={})
        self.assertEqual(n, 1)
        patch_ = [c for c in fake.calls if c[1] and c[1][0] == "update"][0][1][1]
        self.assertIsNone(patch_["book_forward_1d"])
        self.assertIsNotNone(patch_["vol_forward_1d"])


# ---------------------------------------------------------------------------
# 6. Import boundary — zero trading-path coupling
# ---------------------------------------------------------------------------

class TestImportBoundary(unittest.TestCase):
    FORBIDDEN = (
        "options_scanner",
        "workflow_orchestrator",
        "paper_exit_evaluator",
        "paper_autopilot",
        "execution_router",
        "alpaca_order_handler",
        "regime_engine",        # no regime computation — read-only context only
        "intraday_risk_monitor",
        "risk_envelope",
    )

    def _assert_clean(self, module):
        import inspect
        source = inspect.getsource(module)
        for name in self.FORBIDDEN:
            self.assertNotIn(name, source,
                             f"{module.__name__} must not reference {name}")

    def test_vol_signal_module_clean(self):
        self._assert_clean(vol_signal)

    def test_handler_clean(self):
        from packages.quantum.jobs.handlers import vol_signal_snapshot
        self._assert_clean(vol_signal_snapshot)


if __name__ == "__main__":
    unittest.main()
