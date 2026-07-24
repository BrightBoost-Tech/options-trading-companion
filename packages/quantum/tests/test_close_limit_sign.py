"""Close-path signed-limit fix (the 06-11 broken-exits bug).

The 16:30Z force-close staged the short-condor closes with the SIGNED mark
(−1.39 / −1.34) as the ticket limit. A close of a credit position is a
net-DEBIT order (buy the structure back) — Alpaca's convention demands a
POSITIVE limit. The live gateway rejected the first QQQ submit, then let the
retry REST at −1.39: a buy-to-close demanding to be PAID, which can never
fill — and while resting it satisfied the close-idempotency guards,
disarming real exit protection (the #1046/#1021 disarm class).

Pins:
- _close_limit_and_direction: unsigned magnitude always; direction from the
  structural leg inversion (qty sign × multi-leg), corroborated by the
  signed mark with a LOUD warning on disagreement (never silent)
- _close_position and paper_shadow_executor.close_arm route through it
- build_alpaca_order_request refuses a negative-limit close that is not
  marked is_credit_close (fail-loud, the inverse of the #1055 credit guard)
- the #101/#999 credit-close behavior (debit position → negative limit at
  the broker) is unchanged
"""

import sys
import types
import unittest

# Stub alpaca-py so transitive imports resolve in the test venv.
from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

from packages.quantum.brokers.alpaca_order_handler import (  # noqa: E402
    build_alpaca_order_request,
)
from packages.quantum.services.paper_exit_evaluator import (  # noqa: E402
    _close_limit_and_direction,
)


class TestCloseLimitAndDirection(unittest.TestCase):
    def test_credit_position_close_is_unsigned_debit(self):
        """The 06-11 QQQ condor: qty=−1, signed mark −1.39 → limit +1.39,
        NOT a credit close (we pay to buy it back)."""
        limit, icc = _close_limit_and_direction(-1.39, qty=-1, n_legs=4)
        self.assertEqual(limit, 1.39)
        self.assertFalse(icc)

    def test_debit_position_close_is_unsigned_credit(self):
        """The NFLX debit spread: qty=+1, mark +4.33 → limit 4.33,
        is_credit_close True (handler signs it negative at the boundary)."""
        limit, icc = _close_limit_and_direction(4.33, qty=1, n_legs=2)
        self.assertEqual(limit, 4.33)
        self.assertTrue(icc)

    def test_single_leg_never_credit_close(self):
        limit, icc = _close_limit_and_direction(2.50, qty=1, n_legs=1)
        self.assertEqual(limit, 2.50)
        self.assertFalse(icc)

    def test_disagreement_logs_loud_and_structural_wins(self):
        """A short structure fed a POSITIVE mark (the unsigned
        avg_entry_price fallback) must warn and stay a debit close."""
        with self.assertLogs(
            "packages.quantum.services.paper_exit_evaluator", level="WARNING"
        ) as cm:
            limit, icc = _close_limit_and_direction(1.61, qty=-1, n_legs=4)
        self.assertEqual(limit, 1.61)
        self.assertFalse(icc)  # structural direction wins
        self.assertTrue(any("close-direction disagreement" in m for m in cm.output))

    def test_agreement_is_silent(self):
        import logging
        logger = logging.getLogger(
            "packages.quantum.services.paper_exit_evaluator"
        )
        records = []
        handler = logging.Handler()
        handler.emit = lambda r: records.append(r)
        logger.addHandler(handler)
        try:
            _close_limit_and_direction(-1.39, qty=-1, n_legs=4)
        finally:
            logger.removeHandler(handler)
        self.assertFalse(
            [r for r in records if "disagreement" in r.getMessage()]
        )

    def test_zero_mark_no_corroboration_no_crash(self):
        limit, icc = _close_limit_and_direction(0, qty=-1, n_legs=4)
        self.assertEqual(limit, 0.0)
        self.assertFalse(icc)


def _close_order(limit_price, is_credit_close=None, n_legs=4):
    leg_syms = [
        ("O:QQQ260710P00645000", "buy"),
        ("O:QQQ260710P00640000", "sell"),
        ("O:QQQ260710C00750000", "buy"),
        ("O:QQQ260710C00755000", "sell"),
    ][:n_legs]
    oj = {
        "limit_price": limit_price,
        "time_in_force": "day",
        "legs": [
            {"symbol": s, "action": a, "quantity": 1} for s, a in leg_syms
        ],
    }
    if is_credit_close is not None:
        oj["is_credit_close"] = is_credit_close
    return {
        "id": "close-1",
        "position_id": "pos-1",
        "side": "buy",
        "requested_qty": 1,
        "order_json": oj,
    }


class TestHandlerDebitCloseGuard(unittest.TestCase):
    def test_negative_limit_unmarked_close_refuses(self):
        """The exact 06-11 shape: buy-to-close at −1.39, is_credit_close
        false → must raise, never reach the broker."""
        with self.assertRaises(ValueError) as cm:
            build_alpaca_order_request(_close_order(-1.39, is_credit_close=False))
        self.assertIn("Sign-incoherent debit close", str(cm.exception))

    def test_negative_limit_missing_flag_also_refuses(self):
        with self.assertRaises(ValueError):
            build_alpaca_order_request(_close_order(-1.39))

    def test_positive_debit_close_passes(self):
        """The post-fix staging shape: +1.39 unmarked → submits +1.39."""
        req = build_alpaca_order_request(_close_order(1.39, is_credit_close=False))
        self.assertEqual(float(req["limit_price"]), 1.39)

    def test_credit_close_still_flips_negative(self):
        """#101/#999 unchanged: debit-position close marked is_credit_close
        → negative at the broker."""
        req = build_alpaca_order_request(_close_order(4.33, is_credit_close=True))
        self.assertEqual(float(req["limit_price"]), -4.33)

    def test_near_worthless_clamp_then_guard(self):
        """A non-credit close clamped negative (−0.005 → −0.01) must hit the
        guard, not rest at an impossible penny credit."""
        with self.assertRaises(ValueError) as cm:
            build_alpaca_order_request(_close_order(-0.005, is_credit_close=False))
        self.assertIn("Sign-incoherent debit close", str(cm.exception))


class TestSourcePins(unittest.TestCase):
    def test_close_position_routes_through_helper(self):
        import inspect
        from packages.quantum.services import paper_exit_evaluator as pee
        src = inspect.getsource(pee.PaperExitEvaluator._close_position)
        self.assertIn("_close_limit_and_direction(", src)
        self.assertIn("round(close_limit, 2)", src)
        self.assertNotIn("limit_price=round(exit_price, 2)", src)

    def test_shadow_close_arm_routes_through_helper(self):
        import inspect
        from packages.quantum.services import paper_shadow_executor as pse
        src = inspect.getsource(pse.close_arm)
        self.assertIn("_close_limit_and_direction(", src)
        self.assertIn("round(close_limit, 2)", src)


if __name__ == "__main__":
    unittest.main()
