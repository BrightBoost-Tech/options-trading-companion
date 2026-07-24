"""Stale/degenerate-mark trigger guard (06-12 QQQ phantom-TP class).

What actually happened at 2026-06-12 13:30Z: C750 quoted 0.76 × 14.09 at the
bell (true value ~8.8). The resolver averaged it ('mid' 7.425), the condor
summed to a FABRICATED −0.65 mark (true ~−1.9 — broker-corroborated), and
target_profit fired on a phantom +$96. It self-defused only because a
phantom TP on a short structure produces an unfillable below-market BUY
limit. The mirror case — a stale/fabricated PESSIMISTIC mark firing
stop_loss — would submit a marketable order and realize a real loss.

Two complementary guards, both fail-closed at the TRIGGER:
- risk.mark_math.usable_mid: a degenerately wide quote (width > $1 AND
  width/mid > 100%, env-tunable) is NOT a price — the leg counts as failed
  → all-or-nothing unpriceable (#1035 handling: TP never fires, stop alerts
  degraded).
- the monitor's stale-fallback guard: a position with no fresh mark this
  pass whose last_marked_at predates the current session open carries
  yesterday's numbers — mark-derived exits skip it loudly
  (stale_mark_exit_guard alert). Missing provenance → stale.
- the 20:30Z MTM flags (does not refuse) marks built from one-sided /
  fallback quotes (the thin after-hours class).
"""

import sys
import types
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

from packages.quantum.risk.mark_math import (  # noqa: E402
    usable_mid,
    compute_current_value,
)

ET = ZoneInfo("America/New_York")


class TestUsableMid(unittest.TestCase):
    def test_degenerate_open_quote_refused(self):
        """The exact 06-12 13:30Z C750 quote: 0.76×14.09 → None, never 7.425."""
        self.assertIsNone(usable_mid(0.76, 14.09))

    def test_tight_quote_normal(self):
        self.assertAlmostEqual(usable_mid(7.06, 7.32), 7.19, places=6)

    def test_cheap_wide_option_still_priceable(self):
        # 0.05×0.15 is 200% relative but only 10¢ wide — legitimate.
        self.assertAlmostEqual(usable_mid(0.05, 0.15), 0.10, places=6)

    def test_expensive_wide_but_sane_priceable(self):
        # $1.09 wide but 16% relative (the 06-12 NFLX P86 shape).
        self.assertAlmostEqual(usable_mid(6.14, 7.23), 6.685, places=6)

    def test_one_sided_uses_fallback(self):
        self.assertEqual(usable_mid(0, 7.32, fallback=7.10), 7.10)
        self.assertEqual(usable_mid(None, None, fallback=0), 0)


class TestPhantomTpRegression(unittest.TestCase):
    """Yesterday's exact four quotes through the shared mark math: the
    fabricated −0.65 condor mark must be impossible — C750 is refused and
    the position goes all-or-nothing unpriceable (no value, no TP)."""

    QUOTES = {
        "O:QQQ260710P00645000": (4.26, 4.33),
        "O:QQQ260710P00640000": (3.70, 3.90),
        "O:QQQ260710C00750000": (0.76, 14.09),  # the garbage quote
        "O:QQQ260710C00755000": (7.12, 7.42),
    }
    LEGS = [
        {"symbol": "O:QQQ260710P00645000", "action": "sell", "quantity": 1},
        {"symbol": "O:QQQ260710P00640000", "action": "buy", "quantity": 1},
        {"symbol": "O:QQQ260710C00750000", "action": "sell", "quantity": 1},
        {"symbol": "O:QQQ260710C00755000", "action": "buy", "quantity": 1},
    ]

    def _mid_for(self, sym):
        bid, ask = self.QUOTES[sym]
        return usable_mid(bid, ask)

    def test_no_fabricated_value(self):
        failed = []
        value = compute_current_value(
            self.LEGS, self._mid_for, -1, failed_legs=failed
        )
        self.assertIsNone(value)  # all-or-nothing: no −0.65, no +$96
        self.assertEqual(failed, ["O:QQQ260710C00750000"])

    def test_sane_quotes_still_price(self):
        quotes = dict(self.QUOTES)
        quotes["O:QQQ260710C00750000"] = (8.70, 8.90)  # plausible true quote

        def mid_for(sym):
            bid, ask = quotes[sym]
            return usable_mid(bid, ask)

        value = compute_current_value(self.LEGS, mid_for, -1, failed_legs=[])
        self.assertIsNotNone(value)
        # sell P645 −4.295, buy P640 +3.80, sell C750 −8.80, buy C755 +7.27
        self.assertAlmostEqual(value, -202.5, places=1)


class TestStaleFallbackGuard(unittest.TestCase):
    def setUp(self):
        from packages.quantum.jobs.handlers.intraday_risk_monitor import (
            _mark_is_stale_fallback,
        )
        self.guard = _mark_is_stale_fallback
        self.now = datetime(2026, 6, 12, 13, 30, tzinfo=ET)  # 13:30 ET

    def test_yesterday_mark_is_stale(self):
        pos = {"last_marked_at": "2026-06-11T16:30:00+00:00"}
        self.assertTrue(self.guard(pos, now=self.now))

    def test_intraday_mark_is_fresh(self):
        pos = {"last_marked_at": "2026-06-12T14:35:00+00:00"}  # 10:35 ET today
        self.assertFalse(self.guard(pos, now=self.now))

    def test_premarket_mark_today_is_stale(self):
        # a 13:15Z (9:15 ET) evaluator-refresh mark is NOT a session price
        pos = {"last_marked_at": "2026-06-12T13:15:00+00:00"}
        self.assertTrue(self.guard(pos, now=self.now))

    def test_missing_provenance_is_stale(self):
        self.assertTrue(self.guard({}, now=self.now))
        self.assertTrue(self.guard({"last_marked_at": None}, now=self.now))

    def test_age_override(self):
        import os
        pos = {"last_marked_at": "2026-06-12T16:00:00+00:00"}  # 12:00 ET, 90m old
        os.environ["EXIT_STALE_MARK_MAX_AGE_MINUTES"] = "60"
        try:
            self.assertTrue(self.guard(pos, now=self.now.replace(hour=13, minute=30)))
            os.environ["EXIT_STALE_MARK_MAX_AGE_MINUTES"] = "240"
            self.assertFalse(self.guard(pos, now=self.now))
        finally:
            os.environ.pop("EXIT_STALE_MARK_MAX_AGE_MINUTES", None)


class TestWiring(unittest.TestCase):
    def test_monitor_trigger_loop_has_guard_and_fresh_flag(self):
        from pathlib import Path
        src = (
            Path(__file__).parent.parent
            / "jobs" / "handlers" / "intraday_risk_monitor.py"
        ).read_text(encoding="utf-8")
        self.assertIn("_mark_is_stale_fallback(pos)", src)
        self.assertIn("stale_mark_exit_guard", src)
        self.assertEqual(src.count('pos["_mark_fresh"] = True'), 2)
        self.assertIn("usable_mid(", src)

    def test_mtm_service_uses_usable_mid_and_flags_suspect(self):
        from pathlib import Path
        src = (
            Path(__file__).parent.parent
            / "services" / "paper_mark_to_market_service.py"
        ).read_text(encoding="utf-8")
        self.assertIn("usable_mid(", src)
        self.assertIn("suspect_fallback_legs", src)
        self.assertIn("SUSPECT mark", src)


if __name__ == "__main__":
    unittest.main()
