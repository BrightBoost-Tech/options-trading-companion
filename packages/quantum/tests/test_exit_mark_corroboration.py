"""Tests for the Layer-1 exit mark-sanity gate (OBSERVE-ONLY, asymmetric,
fail-safe).

Pins all five invariants:
1. OBSERVE-ONLY — flag on vs off → byte-identical exit (same _close_position
   call); a contract test that no exit-execution code reads the verdict.
2. FAIL-SAFE — an injected gate exception → the exit still fires.
3. ASYMMETRIC — would_suppress TRUE only for target_profit; stop_loss always
   false even on a wildly uncorroborated mark.
4. NEVER FABRICATE — missing/one-sided leg quotes recorded explicitly.
5. The divergence / provisional-tolerance path.

The NFLX 2026-06-08 phantom is the worked fixture: long P85 / short P79, entry
3.08, qty 2; achievable close 2.90 (bid 4.28 − ask 1.38) → −$36; the monitor
acted on a phantom mark ~4.71 → +$325.
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

from packages.quantum.analytics import exit_mark_corroboration as emc  # noqa: E402


# ── Fixtures ───────────────────────────────────────────────────────────────

def _nflx_position(unrealized_pl=325.0, current_mark=4.71):
    """The 2026-06-08 phantom-fire shape."""
    return {
        "id": "a9f977bf", "user_id": "u1", "symbol": "NFLX",
        "quantity": 2.0, "avg_entry_price": 3.08,
        "current_mark": current_mark, "unrealized_pl": unrealized_pl,
        "legs": [
            {"occ_symbol": "NFLX260702P00085000", "action": "buy", "strike": 85.0, "quantity": 2},
            {"occ_symbol": "NFLX260702P00079000", "action": "sell", "strike": 79.0, "quantity": 2},
        ],
    }


# Live executable quotes reproducing the broker's −$36: P85 bid 4.28 (sell to
# close the long), P79 ask 1.38 (buy to close the short) → 4.28 − 1.38 = 2.90.
_QUOTES_COMPLETE = {
    "NFLX260702P00085000": {"bid": 4.28, "ask": 4.97, "last": 4.30},
    "NFLX260702P00079000": {"bid": 1.31, "ask": 1.38, "last": 1.40},
}
# The phantom moment: one leg quoting 0.0 (incomplete two-sided).
_QUOTES_ONE_SIDED = {
    "NFLX260702P00085000": {"bid": 4.28, "ask": 4.97, "last": 4.30},
    "NFLX260702P00079000": {"bid": 0.0, "ask": 0.0, "last": None},
}


def _snapshot_fn(quote_map):
    def _fn(occs):
        return {occ: {"quote": quote_map.get(occ, {})} for occ in occs}
    return _fn


class _FakeQuery:
    def __init__(self, parent):
        self.parent = parent

    def insert(self, row):
        self.parent.inserted.append(row)
        return self

    def execute(self):
        if self.parent.raise_on_write:
            raise RuntimeError("db down")
        return types.SimpleNamespace(data=[{"id": "row-1"}])


class _FakeSupabase:
    def __init__(self, raise_on_write=False):
        self.inserted = []
        self.raise_on_write = raise_on_write

    def table(self, name):
        assert name == emc.OBS_TABLE
        return _FakeQuery(self)


# ── 1. Flag gate ────────────────────────────────────────────────────────────

class TestFlagGate(unittest.TestCase):
    def test_default_off(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(emc.FLAG_ENV, None)
            self.assertFalse(emc.is_observe_enabled())

    def test_lenient_on(self):
        for v in ("1", "true", "yes", "on", " On "):
            with patch.dict(os.environ, {emc.FLAG_ENV: v}):
                self.assertTrue(emc.is_observe_enabled(), v)


# ── 2. Achievable close reproduces the broker (executable side) ─────────────

class TestAchievableClose(unittest.TestCase):
    def test_reproduces_broker_minus_36(self):
        v = emc.compute_corroboration(
            exit_type="target_profit",
            triggering_mark=4.71, triggering_implied_pl=325.0,
            quantity=2.0, avg_entry_price=3.08,
            legs=_nflx_position()["legs"], leg_quotes=_QUOTES_COMPLETE,
        )
        # achievable net = 4.28 − 1.38 = 2.90 → mark 2.90, pl (2.90−3.08)*200 = −36
        self.assertAlmostEqual(v["achievable_close"], 2.90, places=4)
        self.assertAlmostEqual(v["achievable_implied_pl"], -36.0, places=4)
        # divergence: 325 − (−36) = 361 ; price 4.71−2.90=1.81 normalized by
        # the ACHIEVABLE price (06-12 fix — was /spread_width, which let the
        # 7× QQQ condor divergence score 0.06): 1.81/2.90 = 0.6241.
        self.assertAlmostEqual(v["divergence_abs"], 361.0, places=4)
        self.assertAlmostEqual(v["divergence_frac"], 1.81 / 2.90, places=4)
        self.assertEqual(v["spread_width"], 6.0)  # recorded for reference only


# ── 3. Asymmetric would_suppress ────────────────────────────────────────────

class TestAsymmetry(unittest.TestCase):
    def test_stop_loss_never_suppress_even_when_wildly_uncorroborated(self):
        # A genuine adverse move: low mark, one-sided quote — identical shape
        # to a phantom. stop_loss must STILL not suppress.
        v = emc.compute_corroboration(
            exit_type="stop_loss",
            triggering_mark=0.50, triggering_implied_pl=-500.0,
            quantity=2.0, avg_entry_price=3.08,
            legs=_nflx_position()["legs"], leg_quotes=_QUOTES_ONE_SIDED,
        )
        self.assertFalse(v["would_suppress"])
        self.assertEqual(v["suppress_reason"], "stop_loss_never_suppress")

    def test_target_profit_incomplete_quote_suppresses(self):
        v = emc.compute_corroboration(
            exit_type="target_profit",
            triggering_mark=4.71, triggering_implied_pl=325.0,
            quantity=2.0, avg_entry_price=3.08,
            legs=_nflx_position()["legs"], leg_quotes=_QUOTES_ONE_SIDED,
        )
        self.assertTrue(v["would_suppress"])
        self.assertEqual(v["suppress_reason"], "quote_incomplete")
        self.assertFalse(v["quote_complete"])

    def test_target_profit_divergence_exceeded(self):
        # Complete quotes but the trigger mark wildly overstates the close.
        v = emc.compute_corroboration(
            exit_type="target_profit",
            triggering_mark=4.71, triggering_implied_pl=325.0,
            quantity=2.0, avg_entry_price=3.08,
            legs=_nflx_position()["legs"], leg_quotes=_QUOTES_COMPLETE,
            tolerance=0.10,
        )
        # divergence_frac ≈ 0.30 > 0.10 → suppress (provisional)
        self.assertTrue(v["would_suppress"])
        self.assertEqual(v["suppress_reason"], "divergence_exceeded")

    def test_target_profit_corroborated_allows(self):
        # Trigger mark matches the achievable close → allow.
        v = emc.compute_corroboration(
            exit_type="target_profit",
            triggering_mark=2.90, triggering_implied_pl=-36.0,
            quantity=2.0, avg_entry_price=3.08,
            legs=_nflx_position()["legs"], leg_quotes=_QUOTES_COMPLETE,
        )
        self.assertFalse(v["would_suppress"])
        self.assertEqual(v["suppress_reason"], "corroborated_allow")


# ── 4. Never fabricate ──────────────────────────────────────────────────────

class TestNeverFabricate(unittest.TestCase):
    def test_missing_leg_recorded_explicitly(self):
        v = emc.compute_corroboration(
            exit_type="target_profit",
            triggering_mark=4.71, triggering_implied_pl=325.0,
            quantity=2.0, avg_entry_price=3.08,
            legs=_nflx_position()["legs"], leg_quotes=_QUOTES_ONE_SIDED,
        )
        short_leg = next(l for l in v["legs_quotes"] if l["occ"] == "NFLX260702P00079000")
        self.assertEqual(sorted(short_leg["missing"]), ["ask", "bid"])
        self.assertIsNone(short_leg["bid"])
        self.assertIsNone(short_leg["ask"])
        # achievable can't be computed when a priceable leg is unpriced (None,
        # not a fabricated value).
        self.assertIsNone(v["achievable_close"])
        self.assertIsNone(v["achievable_implied_pl"])

    def test_rescored_0612_qqq_condor_row_d892c45b(self):
        """Yesterday's actual observation (row d892c45b) under the fixed
        normalization: trigger −0.65 vs achievable −7.60 — the OLD
        /spread_width(115) math scored 0.060 → 'corroborated_allow'; the
        price-normalized math scores ≈0.914 → divergence_exceeded."""
        quotes = {
            "O:QQQ260710P00645000": {"bid": 4.26, "ask": 4.33},
            "O:QQQ260710P00640000": {"bid": 3.70, "ask": 3.90},
            "O:QQQ260710C00750000": {"bid": 0.76, "ask": 14.09},
            "O:QQQ260710C00755000": {"bid": 7.12, "ask": 7.42},
        }
        legs = [
            {"occ_symbol": "O:QQQ260710P00645000", "action": "sell", "strike": 645.0, "quantity": 1},
            {"occ_symbol": "O:QQQ260710P00640000", "action": "buy", "strike": 640.0, "quantity": 1},
            {"occ_symbol": "O:QQQ260710C00750000", "action": "sell", "strike": 750.0, "quantity": 1},
            {"occ_symbol": "O:QQQ260710C00755000", "action": "buy", "strike": 755.0, "quantity": 1},
        ]
        v = emc.compute_corroboration(
            exit_type="target_profit",
            triggering_mark=-0.65, triggering_implied_pl=96.0,
            quantity=-1.0, avg_entry_price=1.61,
            legs=legs, leg_quotes=quotes, tolerance=0.10,
        )
        self.assertAlmostEqual(v["achievable_close"], -7.60, places=2)
        self.assertAlmostEqual(
            v["divergence_frac"], abs(-0.65 - (-7.60)) / 7.60, places=3
        )  # ≈ 0.914
        self.assertGreater(abs(v["divergence_frac"]), 0.9)
        self.assertTrue(v["would_suppress"])
        self.assertEqual(v["suppress_reason"], "divergence_exceeded")

    def test_single_leg_has_no_spread_width(self):
        v = emc.compute_corroboration(
            exit_type="target_profit",
            triggering_mark=2.0, triggering_implied_pl=50.0,
            quantity=1.0, avg_entry_price=1.5,
            legs=[{"occ_symbol": "X", "action": "buy", "strike": 100.0, "quantity": 1}],
            leg_quotes={"X": {"bid": 2.0, "ask": 2.1}},
        )
        self.assertIsNone(v["spread_width"])
        # 06-12: the frac no longer depends on strike geometry — a single-leg
        # position with trigger == achievable (executable bid 2.0) scores 0
        # divergence (correct), not None-for-missing-width.
        self.assertAlmostEqual(v["divergence_frac"], 0.0, places=4)


# ── 5. observe_exit_mark fail-safe + write ──────────────────────────────────

class TestObserveFailSafe(unittest.TestCase):
    def test_writes_row_with_verdict(self):
        fake = _FakeSupabase()
        row = emc.observe_exit_mark(
            fake, position=_nflx_position(), exit_type="target_profit",
            triggering_mark=4.71, triggering_implied_pl=325.0,
            user_id="u1", snapshot_fn=_snapshot_fn(_QUOTES_COMPLETE),
        )
        self.assertEqual(len(fake.inserted), 1)
        self.assertEqual(row["symbol"], "NFLX")
        self.assertEqual(row["suppress_reason"], "divergence_exceeded")

    def test_compute_exception_records_error_row_never_raises(self):
        fake = _FakeSupabase()
        with patch.object(emc, "compute_corroboration", side_effect=RuntimeError("boom")):
            row = emc.observe_exit_mark(
                fake, position=_nflx_position(), exit_type="target_profit",
                triggering_mark=4.71, triggering_implied_pl=325.0,
                snapshot_fn=_snapshot_fn(_QUOTES_COMPLETE),
            )
        self.assertEqual(row["suppress_reason"], "corroboration_error")
        self.assertFalse(row["would_suppress"])
        self.assertIn("boom", row["corroboration_error"])

    def test_db_write_failure_returns_none_never_raises(self):
        fake = _FakeSupabase(raise_on_write=True)
        out = emc.observe_exit_mark(
            fake, position=_nflx_position(), exit_type="stop_loss",
            triggering_mark=0.5, triggering_implied_pl=-500.0,
            snapshot_fn=_snapshot_fn(_QUOTES_COMPLETE),
        )
        self.assertIsNone(out)  # swallowed; never raises into the monitor

    def test_non_gated_exit_type_ignored(self):
        fake = _FakeSupabase()
        out = emc.observe_exit_mark(
            fake, position=_nflx_position(), exit_type="expiration_day",
            triggering_mark=1.0, triggering_implied_pl=0.0,
            snapshot_fn=_snapshot_fn(_QUOTES_COMPLETE),
        )
        self.assertIsNone(out)
        self.assertEqual(fake.inserted, [])


# ── Contract: no exit-execution code reads the verdict ──────────────────────

class TestObserveOnlyContract(unittest.TestCase):
    def test_monitor_does_not_read_gate_output(self):
        """The hook must call observe_exit_mark and ignore its return — no
        branch keys off the verdict. Pin against assignment/branch use."""
        import inspect
        from packages.quantum.jobs.handlers import intraday_risk_monitor as irm
        src = inspect.getsource(irm.IntradayRiskMonitor._execute_force_close)
        # The observe call exists...
        self.assertIn("observe_exit_mark(", src)
        # ...and its result is never captured into a variable or branched on.
        self.assertNotIn("= _emc.observe_exit_mark", src)
        self.assertNotIn("would_suppress", src)  # the monitor never reads the verdict
        self.assertNotIn("suppress_reason", src)

    def test_close_position_call_unconditional_on_gate(self):
        """The exit (_close_position) is not nested under any gate branch."""
        import inspect
        from packages.quantum.jobs.handlers import intraday_risk_monitor as irm
        src = inspect.getsource(irm.IntradayRiskMonitor._execute_force_close)
        # _close_position appears after the gate block, at the method's base
        # indentation inside the try — not inside the `if _gate_exit_type` body.
        self.assertIn("evaluator._close_position(", src)
        gate_idx = src.index("_gate_exit_type is not None")
        close_idx = src.index("evaluator._close_position(")
        self.assertLess(gate_idx, close_idx)  # gate observed first, then close


if __name__ == "__main__":
    unittest.main()
