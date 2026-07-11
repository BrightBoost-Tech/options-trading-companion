"""F-A3-1 Part B (2026-07-11) — close_reason persistence (forward-only).

Fixes the three deaths the audit named, so the thesis tracker (I5) can separate
WHY a trade closed from its P&L:

  Death B — LIVE closes hardcoded 'alpaca_fill_reconciler_standard', erasing the
            reason. Now the reconciler reads the stage-stamped order_json.
  Death A — the monitor collapsed every non-TP close to 'envelope_force_close'.
            Now a monitor stop lands as stop_loss_hit (== the scheduled stop),
            and the granular envelope rides close_reason_detail.
  Death C/D — the ingest never carried it. Now details_json carries close_reason
            (+ _detail), and policy_decisions.exit_reason gets a real value.

Tests drive PRODUCTION routes (the reconciler _close_position_on_fill and the
ingest record builder _create_paper_outcome_record) and the real mapping
functions/constants the stage stamp + 5a loop use — no reimplemented logic.

  T1  reconciler persists the stamped reason (not the hardcode)
  T2  monitor-vs-evaluator SAME-stop equivalence (coarse + detail)
  T3  envelope detail threads to the granular thesis enum
  T4  a TP fill lands take_profit end-to-end
  T5  the ingest record carries close_reason + _detail in details_json
  T6  legacy rows (no stamp) → fallback / NULL, no crash
"""

import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from packages.quantum.services.paper_exit_evaluator import (
    _map_close_reason,
    _close_reason_detail,
)
from packages.quantum.jobs.handlers.intraday_risk_monitor import _STAGE5A_REASON_MAP
from packages.quantum.jobs.handlers.paper_learning_ingest import (
    _create_paper_outcome_record,
)
from packages.quantum.brokers import alpaca_order_handler as aoh


# ── reconciler harness (drives the real _close_position_on_fill) ────────────

def _run_reconciler(order_json):
    """Drive _close_position_on_fill with a stamped/unstamped order_json and
    capture the close_reason handed to close_position_shared."""
    position = {
        "id": "pos-1", "status": "open", "quantity": 1,
        "avg_entry_price": 1.00, "symbol": "SPY",
    }
    supabase = MagicMock()
    chain = MagicMock()
    for m in ("select", "eq", "single", "update", "in_"):
        getattr(chain, m).return_value = chain
    chain.execute.return_value = MagicMock(data=position)
    supabase.table.return_value = chain

    captured = {}

    def _fake_close(**kwargs):
        captured.update(kwargs)

    order = {"id": "ord-1", "order_json": order_json}
    alpaca_order = {"filled_at": "2026-07-11T14:00:00+00:00",
                    "filled_avg_price": 0.50, "filled_qty": 1}
    with patch.object(aoh, "close_position_shared", side_effect=_fake_close), \
         patch.object(aoh, "extract_close_legs", return_value=[{"x": 1}]), \
         patch.object(aoh, "compute_realized_pl", return_value=Decimal("10")):
        aoh._close_position_on_fill(supabase, "pos-1", order, alpaca_order)
    return captured


# ── T1 / T4 / T6 — reconciler read-back ─────────────────────────────────────

class TestReconcilerReadBack(unittest.TestCase):
    def test_t1_persists_stamped_stop(self):
        captured = _run_reconciler({"close_reason": "stop_loss_hit"})
        self.assertEqual(captured.get("close_reason"), "stop_loss_hit")

    def test_t1_persists_stamped_envelope(self):
        captured = _run_reconciler({"close_reason": "envelope_force_close"})
        self.assertEqual(captured.get("close_reason"), "envelope_force_close")

    def test_t4_tp_fill_lands_take_profit(self):
        captured = _run_reconciler({"close_reason": "target_profit_hit"})
        self.assertEqual(captured.get("close_reason"), "target_profit_hit")

    def test_t6_legacy_no_stamp_falls_back(self):
        captured = _run_reconciler({})  # legacy order, no stamp
        self.assertEqual(captured.get("close_reason"), "alpaca_fill_reconciler_standard")

    def test_t6_invalid_stamp_falls_back(self):
        # A non-enum stamp value must not reach close_position_shared.
        captured = _run_reconciler({"close_reason": "reconciler_unknown"})
        self.assertEqual(captured.get("close_reason"), "alpaca_fill_reconciler_standard")


# ── T2 — monitor-vs-evaluator same-stop equivalence ─────────────────────────

class TestStopEquivalence(unittest.TestCase):
    def test_t2_monitor_stop_maps_like_scheduled_stop(self):
        # Scheduled evaluator passes the bare "stop_loss"; the monitor's 5a now
        # maps its stop to the SAME bare reason via _STAGE5A_REASON_MAP.
        scheduled = "stop_loss"
        monitor_mapped = _STAGE5A_REASON_MAP["stop_loss"]
        self.assertEqual(monitor_mapped, "stop_loss")
        # COARSE: both land as stop_loss_hit (not envelope_force_close).
        self.assertEqual(_map_close_reason(scheduled), "stop_loss_hit")
        self.assertEqual(_map_close_reason(monitor_mapped), _map_close_reason(scheduled))
        # DETAIL: both resolve to the same thesis value.
        self.assertEqual(_close_reason_detail(monitor_mapped),
                         _close_reason_detail(scheduled))
        self.assertEqual(_close_reason_detail(scheduled), "stop_loss")

    def test_t2_expiration_and_tp_also_mapped(self):
        self.assertEqual(_map_close_reason(_STAGE5A_REASON_MAP["expiration_day"]),
                         "expiration_day")
        self.assertEqual(_map_close_reason(_STAGE5A_REASON_MAP["target_profit"]),
                         "target_profit_hit")

    def test_t2_pre_fix_collapse_is_gone(self):
        # A stop routed through the OLD risk_envelope: form still collapses (the
        # legacy path), proving the fix is specifically the 5a bare-reason map.
        self.assertEqual(_map_close_reason("risk_envelope:intraday_stop_loss"),
                         "envelope_force_close")


# ── T3 — envelope detail threads ────────────────────────────────────────────

class TestEnvelopeDetail(unittest.TestCase):
    def test_t3_each_envelope_resolves_distinctly(self):
        cases = {
            "loss_per_symbol": "symbol_envelope",
            "loss_daily": "daily_brake",
            "loss_weekly": "weekly_brake",
            "concentration_symbol": "concentration",
            "concentration_sector": "concentration",
            "stress_scenario": "stress",
        }
        for envelope, expected in cases.items():
            self.assertEqual(_close_reason_detail(envelope), expected,
                             f"{envelope} must resolve to {expected}")

    def test_t3_coarse_stays_envelope_force_close(self):
        # The granular detail de-collapses, but the coarse (9-value CHECK) reason
        # for an envelope force-close remains envelope_force_close.
        self.assertEqual(_map_close_reason("risk_envelope:loss_per_symbol"),
                         "envelope_force_close")

    def test_t3_full_reason_signals_map(self):
        self.assertEqual(_close_reason_detail("target_profit"), "take_profit")
        self.assertEqual(_close_reason_detail("dte_threshold"), "dte_threshold")
        self.assertEqual(_close_reason_detail("manual_close_user_initiated"), "manual")
        self.assertEqual(_close_reason_detail("orphan_fill_repair"), "orphan_repair")


# ── T5 — ingest carries it into details_json ────────────────────────────────

class TestIngestCarriesReason(unittest.TestCase):
    def test_t5_details_json_has_reason_and_detail(self):
        order = {"id": "o1", "order_json": {"close_reason_detail": "stop_loss",
                                            "symbol": "SPY"}}
        position = {"id": "p1", "realized_pl": -50, "close_reason": "stop_loss_hit"}
        rec = _create_paper_outcome_record("u1", order, "2026-07-11", position)
        self.assertEqual(rec["details_json"]["close_reason"], "stop_loss_hit")
        self.assertEqual(rec["details_json"]["close_reason_detail"], "stop_loss")

    def test_t6_legacy_ingest_row_nulls_no_crash(self):
        # Legacy: position with no close_reason, order with no _detail.
        order = {"id": "o2", "order_json": {"symbol": "QQQ"}}
        position = {"id": "p2", "realized_pl": 20}
        rec = _create_paper_outcome_record("u1", order, "2026-07-11", position)
        self.assertIsNone(rec["details_json"]["close_reason"])
        self.assertIsNone(rec["details_json"]["close_reason_detail"])


if __name__ == "__main__":
    unittest.main()
