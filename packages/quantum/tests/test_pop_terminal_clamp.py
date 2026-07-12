"""PoP census PR-0: terminal [0,1] clamp in calculate_pop (the H9 bound-assert).

The clamp lives ONCE at the exit (_clamp_pop); every branch returns through it.
Pins:
- NO LIVE CHANGE: every structure type's in-range output is bounded AND the clamp
  never engages (assertNoLogs) — proof the clamp is a no-op on the live book
  (max(0,min(1,x))==x for x in [0,1]).
- The terminal clamp binds + LOGS on the values that shouldn't exist: a synthetic
  >1 and <0 (direct) and a malformed |delta|>1 routed THROUGH calculate_pop.
- Non-finite → 0.5 neutral + logged.
"""
import unittest

from packages.quantum import ev_calculator as ec
from packages.quantum.ev_calculator import calculate_pop, _clamp_pop


class TestInRangePassthroughNoOp(unittest.TestCase):
    """Every branch's valid output is in-range AND does not engage the clamp."""

    CASES = [
        # (kwargs, expected) — expected == the pre-clamp value (clamp is a no-op)
        (dict(strategy_type="credit_spread", credit=0.3, width=1.0), 0.7),   # credit_width
        (dict(strategy_type="credit_spread", delta=0.3), 0.7),               # credit_delta_fallback
        (dict(strategy_type="debit_spread",                                  # debit_interp
              legs=[{"action": "buy", "delta": 0.6}, {"action": "sell", "delta": 0.2}],
              credit=0.4, width=1.0), 0.44),
        (dict(strategy_type="debit_spread",                                  # debit_midpoint
              legs=[{"action": "buy", "delta": 0.6}, {"action": "sell", "delta": 0.2}]), 0.4),
        (dict(strategy_type="debit_spread",                                  # debit_long_only
              legs=[{"action": "buy", "delta": 0.6}]), 0.6),
        (dict(strategy_type="long_call", delta=0.35), 0.35),                 # long_single_delta
        (dict(strategy_type="long_put",                                      # long_single_leg
              legs=[{"delta": 0.4}]), 0.4),
        (dict(strategy_type="short_put", delta=0.30), 0.7),                  # short_single_delta
        (dict(strategy_type="naked_call",                                    # short_single_leg
              legs=[{"delta": 0.25}]), 0.75),
        (dict(strategy_type="mystery", delta=0.4), 0.4),                     # raw_delta_fallback
        (dict(strategy_type="mystery"), 0.5),                               # neutral_unknown
    ]

    def test_values_correct_and_bounded(self):
        for kwargs, expected in self.CASES:
            got = calculate_pop(**kwargs)
            self.assertAlmostEqual(got, expected, places=9, msg=str(kwargs))
            self.assertGreaterEqual(got, 0.0)
            self.assertLessEqual(got, 1.0)

    def test_clamp_never_engages_on_valid_inputs(self):
        # No POP_BOUND_ENGAGED warning for any in-range case → the clamp is inert
        # on the live book (byte-identical behavior).
        for kwargs, _ in self.CASES:
            with self.assertNoLogs(ec.__name__, level="WARNING"):
                calculate_pop(**kwargs)


class TestTerminalClampBinds(unittest.TestCase):
    def test_over_one_clamped_and_logged(self):
        with self.assertLogs(ec.__name__, level="WARNING") as cm:
            self.assertEqual(_clamp_pop(1.5, "unit", "long_call"), 1.0)
        self.assertIn("POP_BOUND_ENGAGED", "\n".join(cm.output))

    def test_below_zero_clamped_and_logged(self):
        with self.assertLogs(ec.__name__, level="WARNING") as cm:
            self.assertEqual(_clamp_pop(-0.3, "unit", "short_call"), 0.0)
        self.assertIn("POP_BOUND_ENGAGED", "\n".join(cm.output))

    def test_nonfinite_maps_neutral_and_logged(self):
        with self.assertLogs(ec.__name__, level="WARNING") as cm:
            self.assertEqual(_clamp_pop(float("nan"), "unit", "x"), 0.5)
        self.assertIn("POP_BOUND_ENGAGED", "\n".join(cm.output))


class TestEndToEndOvershoot(unittest.TestCase):
    def test_malformed_delta_over_one(self):
        # |delta|=1.3 (malformed) → long branch yields 1.3 → terminal clamp → 1.0 + log
        with self.assertLogs(ec.__name__, level="WARNING") as cm:
            self.assertEqual(calculate_pop("long_call", delta=1.3), 1.0)
        self.assertIn("branch=long_single_delta", "\n".join(cm.output))

    def test_malformed_delta_below_zero(self):
        # |delta|=1.3 → short branch yields 1.0-1.3=-0.3 → terminal clamp → 0.0 + log
        with self.assertLogs(ec.__name__, level="WARNING") as cm:
            self.assertEqual(calculate_pop("short_call", delta=1.3), 0.0)
        self.assertIn("branch=short_single_delta", "\n".join(cm.output))


if __name__ == "__main__":
    unittest.main()
