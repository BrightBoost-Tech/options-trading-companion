"""Fail-closed mark in the intraday monitor — the 2026-06-08 phantom root.

ROOT (diagnosed): the monitor's _refresh_marks called compute_current_value
WITHOUT failed_legs, so a leg that couldn't price was silently DROPPED and the
surviving leg(s) finalized to a PARTIAL-SUM mark. On 2026-06-08 13:30Z one NFLX
leg quoted 0.0 at the open; dropping it inflated the spread's value to a
fabricated +$325 (achievable close was ~−$36) and intraday_target_profit fired
on a position the spread never held. (The MTM service already passed failed_legs;
the monitor's own trigger-mark path was the lone holdout.)

FIX, asymmetric + fail-closed:
1. NEVER FABRICATE — pass failed_legs → any dead leg makes the mark None, not a
   partial sum.
2. target_profit MUST NOT fire on an unpriceable mark (kills the phantom).
3. stop_loss does NOT act on the uncorroborated value; raises a loud
   stop_loss_protection_degraded alert and waits for the next pass.
4. expiration_day (date-derived) is UNAFFECTED.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Stub alpaca-py so transitive imports resolve in the test venv.
from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

from packages.quantum.services.cache_key_builder import normalize_symbol  # noqa: E402

P85 = "NFLX260702P00085000"
P79 = "NFLX260702P00079000"
STALE_PL = -16.0  # the position's previous (real) mark before this pass


def _nflx_position():
    return {
        "id": "a9f977bf", "user_id": "u1", "symbol": "NFLX",
        "quantity": 2.0, "avg_entry_price": 3.08,
        "current_mark": 2.92, "unrealized_pl": STALE_PL,
        "legs": [
            {"occ_symbol": P85, "action": "buy", "strike": 85.0, "quantity": 2},
            {"occ_symbol": P79, "action": "sell", "strike": 79.0, "quantity": 2},
        ],
    }


def _snapshots(p85_quote, p79_quote):
    return {
        normalize_symbol(P85): {"quote": p85_quote},
        normalize_symbol(P79): {"quote": p79_quote},
    }


def _run_refresh(snapshots):
    from packages.quantum.jobs.handlers.intraday_risk_monitor import IntradayRiskMonitor

    monitor = IntradayRiskMonitor.__new__(IntradayRiskMonitor)
    monitor.supabase = MagicMock()
    monitor.supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
    alerts = []
    monitor._log_alert = lambda **k: alerts.append(k)

    pos = _nflx_position()
    with patch(
        "packages.quantum.services.market_data_truth_layer.MarketDataTruthLayer"
    ) as TL:
        TL.return_value.snapshot_many.return_value = snapshots
        out = monitor._refresh_marks([pos])
    return out[0], alerts


# ── 1. _refresh_marks fail-closed ───────────────────────────────────────────

class TestRefreshMarksFailClosed(unittest.TestCase):

    def test_dead_leg_yields_none_not_partial_sum(self):
        """The phantom: P79 (short) quotes 0.0 → dropped under the old code,
        inflating the surviving long leg to a fabricated profit. Now: the mark
        is unpriceable (None path) — NOT fabricated."""
        pos, alerts = _run_refresh(_snapshots(
            {"bid": 4.65, "ask": 4.77},   # long P85 priced (~4.71)
            {"bid": 0.0, "ask": 0.0},     # short P79 dead at the open
        ))
        # Flagged unpriceable; stale pl retained (NOT the +$325 partial-sum that
        # dropping the short leg would have fabricated).
        self.assertTrue(pos.get("_mark_unpriceable"))
        self.assertEqual(pos["unrealized_pl"], STALE_PL)
        self.assertNotAlmostEqual(pos["unrealized_pl"], 325.0, places=0)
        # Loud mtm_refresh_partial alert fired, naming the failed leg.
        partial = [a for a in alerts if a.get("alert_type") == "mtm_refresh_partial"]
        self.assertEqual(len(partial), 1)
        self.assertIn(P79, str(partial[0]["metadata"]["skipped"]))

    def test_clean_two_sided_mark_is_full_sum(self):
        """Both legs priced → full signed sum, byte-identical to pre-fix; no
        unpriceable flag."""
        pos, alerts = _run_refresh(_snapshots(
            {"bid": 4.20, "ask": 4.40},   # P85 mid 4.30
            {"bid": 1.30, "ask": 1.50},   # P79 mid 1.40
        ))
        # net = (4.30 − 1.40) = 2.90 → pl (2.90−3.08)*200 = −36
        self.assertFalse(pos.get("_mark_unpriceable"))
        self.assertAlmostEqual(pos["current_mark"], 2.90, places=4)
        self.assertAlmostEqual(pos["unrealized_pl"], -36.0, places=4)
        self.assertEqual([a for a in alerts if a.get("alert_type") == "mtm_refresh_partial"], [])

    def test_dead_long_leg_also_none(self):
        """Whichever leg dies → None (all-or-nothing). The long leg dying would
        previously fabricate a phantom LOSS; now it's unpriceable."""
        pos, _ = _run_refresh(_snapshots(
            {"bid": 0.0, "ask": 0.0},     # P85 dead
            {"bid": 1.30, "ask": 1.50},   # P79 priced
        ))
        self.assertTrue(pos.get("_mark_unpriceable"))
        self.assertEqual(pos["unrealized_pl"], STALE_PL)


# ── 2. _collect_intraday_exit_triggers asymmetric handling ──────────────────

def _run_collect(pos, eval_reason, tp_check=False, tp_active=True):
    from packages.quantum.jobs.handlers import intraday_risk_monitor as irm

    monitor = irm.IntradayRiskMonitor.__new__(irm.IntradayRiskMonitor)
    monitor.supabase = MagicMock()
    alerts = []
    monitor._log_alert = lambda **k: alerts.append(k)

    fake_conds = {"target_profit": {"check": lambda p: tp_check}}

    class _FakeEvaluator:
        def __init__(self, supabase):
            pass

        def _resolve_position_cohort(self, p):
            return "aggressive"

    with patch.object(irm, "_INTRADAY_TARGET_PROFIT_ENABLED", tp_active), patch(
        "packages.quantum.services.paper_exit_evaluator.evaluate_position_exit",
        return_value=eval_reason,
    ), patch(
        "packages.quantum.services.paper_exit_evaluator.PaperExitEvaluator",
        _FakeEvaluator,
    ), patch(
        "packages.quantum.services.paper_exit_evaluator.build_exit_conditions",
        return_value=fake_conds,
    ), patch(
        "packages.quantum.policy_lab.config.load_cohort_configs",
        return_value={"aggressive": types.SimpleNamespace(
            target_profit_pct=0.35, stop_loss_pct=0.5, min_dte_to_exit=7)},
    ):
        triggered = monitor._collect_intraday_exit_triggers([pos], "u1")
    return triggered, alerts


class TestCollectAsymmetric(unittest.TestCase):

    def test_target_profit_skipped_when_unpriceable(self):
        """The phantom kill: an unpriceable position whose (stale) value would
        otherwise pass the target_profit check does NOT fire."""
        pos = _nflx_position()
        pos["_mark_unpriceable"] = True
        triggered, _ = _run_collect(pos, eval_reason=None, tp_check=True)
        self.assertEqual(triggered, [])

    def test_target_profit_fires_when_priceable(self):
        """Control: same target_profit check, priceable position → fires.
        06-12: priceable now means FRESH provenance too (_mark_fresh, set by
        _refresh_marks on success) — the stale-mark guard correctly refuses
        an unprovenanced value."""
        pos = _nflx_position()  # no _mark_unpriceable flag
        pos["_mark_fresh"] = True
        triggered, _ = _run_collect(pos, eval_reason=None, tp_check=True)
        self.assertEqual(len(triggered), 1)
        self.assertEqual(triggered[0][1], "target_profit")

    def test_stop_loss_not_acted_on_when_unpriceable_and_alerts(self):
        pos = _nflx_position()
        pos["_mark_unpriceable"] = True
        triggered, alerts = _run_collect(pos, eval_reason="stop_loss")
        self.assertEqual(triggered, [])  # did NOT act on the stale value
        degraded = [a for a in alerts
                    if a.get("alert_type") == "stop_loss_protection_degraded"]
        self.assertEqual(len(degraded), 1)
        self.assertEqual(degraded[0]["severity"], "high")
        self.assertEqual(degraded[0]["position_id"], "a9f977bf")

    def test_stop_loss_fires_normally_when_priceable(self):
        pos = _nflx_position()
        pos["_mark_fresh"] = True  # 06-12 guard: fresh provenance required
        triggered, alerts = _run_collect(pos, eval_reason="stop_loss")
        self.assertEqual(triggered, [(pos, "stop_loss")])
        self.assertEqual(
            [a for a in alerts if a.get("alert_type") == "stop_loss_protection_degraded"], [])

    def test_expiration_day_unaffected_by_unpriceable(self):
        """Date-derived exit must STILL fire — a calendar date is real even
        when quotes aren't."""
        pos = _nflx_position()
        pos["_mark_unpriceable"] = True
        triggered, _ = _run_collect(pos, eval_reason="expiration_day")
        self.assertEqual(triggered, [(pos, "expiration_day")])


if __name__ == "__main__":
    unittest.main()
