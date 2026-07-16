"""Comprehensive scheduler -> RQ queue routing map (A5 re-route, 2026-06-18).

Complements test_background_queue_routing.py (IV-only) by pinning the FULL map:
every task route handler -> its expected RQ queue. The 2026-05-15 worker-queue
blocker showed a long/secondary job on the 'otc' queue starves the trading-day
pipeline. The 6-job post-close learning chain (learning_ingest_eod,
paper_learning_ingest, policy_lab_eval, post_trade_learning, promotion_check,
daily_progression_eval) moves to the 'background' queue; the trading-day
pipeline + per-cycle + IV-daily jobs stay on 'otc'; iv_historical_backfill stays
on 'background' (the original long-run split).

Source-level structural assertions (no FastAPI client needed) — the queue is
decided by the queue_name kwarg at each enqueue_job_run call site.
"""
import re
import unittest
from pathlib import Path

_QUANTUM = Path(__file__).parent.parent
PUBLIC = (_QUANTUM / "public_tasks.py").read_text(encoding="utf-8")
INTERNAL = (_QUANTUM / "internal_tasks.py").read_text(encoding="utf-8")

BG = "background"
OTC = "otc"

# handler fn -> (source, expected queue). Covers EVERY scheduled task route in
# both routers. Update deliberately (with the count backstop below) when a new
# scheduled job is added.
EXPECTED = {
    # ── BACKGROUND: the 6-job post-close learning chain (A5) ──
    "task_learning_ingest":        (PUBLIC, BG),   # job: learning_ingest_eod
    "task_paper_learning_ingest":  (PUBLIC, BG),
    "task_policy_lab_eval":        (PUBLIC, BG),
    "post_trade_learning_task":    (INTERNAL, BG),
    "promotion_check_task":        (INTERNAL, BG),
    "daily_progression_eval_task": (INTERNAL, BG),
    # ── BACKGROUND: original long-run split (not a learning job) ──
    "iv_historical_backfill_task": (INTERNAL, BG),
    # ── BACKGROUND: thesis tracker (I5), learning-chain-adjacent (07-11) ──
    "thesis_score_task":           (INTERNAL, BG),
    # ── BACKGROUND: operator-triggered persisted-tape integrity reader ──
    "replay_integrity_check_task": (INTERNAL, BG),
    # ── OTC: trading-day pipeline + per-cycle + IV-daily ──
    "task_universe_sync":          (PUBLIC, OTC),
    "task_morning_brief":          (PUBLIC, OTC),
    "task_midday_scan":            (PUBLIC, OTC),
    "task_weekly_report":          (PUBLIC, OTC),
    "task_validation_eval":        (PUBLIC, OTC),
    "task_suggestions_close":      (PUBLIC, OTC),
    "task_suggestions_open":       (PUBLIC, OTC),
    "task_strategy_autotune":      (PUBLIC, OTC),
    "task_ops_health_check":       (PUBLIC, OTC),
    "task_paper_auto_execute":     (PUBLIC, OTC),
    "task_paper_auto_close":       (PUBLIC, OTC),
    "task_paper_process_orders":   (PUBLIC, OTC),
    "task_validation_shadow_eval": (PUBLIC, OTC),
    "task_validation_preflight":   (PUBLIC, OTC),
    "task_validation_init_window": (PUBLIC, OTC),
    "task_paper_exit_evaluate":    (PUBLIC, OTC),
    "task_paper_mark_to_market":   (PUBLIC, OTC),
    "alpaca_order_sync_task":      (INTERNAL, OTC),
    "intraday_risk_monitor_task":  (INTERNAL, OTC),
    "day_orchestrator_task":       (INTERNAL, OTC),
    "calibration_update_task":     (INTERNAL, OTC),
    "heartbeat_task":              (INTERNAL, OTC),
    "phase2_precheck_task":        (INTERNAL, OTC),
    "walk_forward_autotune_task":  (INTERNAL, OTC),
    "iv_daily_refresh_task":       (INTERNAL, OTC),
    "vol_signal_snapshot_task":    (INTERNAL, OTC),
    "ipo_readiness_monitor_task":  (INTERNAL, OTC),
}


def _handler_body(src: str, fn: str) -> str:
    """Slice from ``async def <fn>(`` to the next ``@router.post(`` (the next
    endpoint) — scopes the queue_name check to this handler only."""
    a = src.find(f"async def {fn}(")
    assert a > 0, f"handler {fn} not found in source"
    m = re.search(r"\n@router\.post\(", src[a + 10:])
    return src[a: a + 10 + m.start()] if m else src[a:]


class TestSchedulerQueueRoutingMap(unittest.TestCase):

    def test_every_handler_routes_to_expected_queue(self):
        for fn, (src, want) in EXPECTED.items():
            body = _handler_body(src, fn)
            has_bg = "queue_name=BACKGROUND_QUEUE" in body
            if want == BG:
                self.assertTrue(
                    has_bg,
                    f"{fn} must route to BACKGROUND_QUEUE "
                    f"(A5 learning chain / long-run split).",
                )
            else:
                self.assertFalse(
                    has_bg,
                    f"{fn} must stay on the default 'otc' queue (trading-day "
                    f"pipeline) — found queue_name=BACKGROUND_QUEUE.",
                )

    def test_both_routers_import_background_queue_constant(self):
        for src, name in ((PUBLIC, "public_tasks.py"), (INTERNAL, "internal_tasks.py")):
            self.assertIn(
                "from packages.quantum.jobs.rq_enqueue import", src,
                f"{name} must import from rq_enqueue",
            )
            self.assertIn(
                "BACKGROUND_QUEUE", src,
                f"{name} must reference BACKGROUND_QUEUE (no inline 'background').",
            )

    def test_exactly_nine_background_routes_total(self):
        """Backstop against silent drift: exactly 9 enqueue sites route to
        background — the 6 learning-chain jobs + iv_historical_backfill +
        thesis_tracker (I5, learning-chain-adjacent, 07-11) + the unscheduled
        replay integrity reader. A new background
        route OR an accidental trading-job re-route breaks this until the map
        above is updated deliberately."""
        total = (PUBLIC.count("queue_name=BACKGROUND_QUEUE")
                 + INTERNAL.count("queue_name=BACKGROUND_QUEUE"))
        self.assertEqual(
            total, 9,
            f"expected 9 background routes (6 learning + iv_historical_backfill "
            f"+ thesis_tracker + replay integrity), found {total} — update "
            f"EXPECTED + the §6 queue "
            f"map deliberately.",
        )

    def test_no_inline_background_string_at_call_sites(self):
        """Routing must use the BACKGROUND_QUEUE constant, never the inline
        string — a literal would drift from the canonical RQ queue name the
        worker listens on."""
        for src in (PUBLIC, INTERNAL):
            self.assertNotIn('queue_name="background"', src)
            self.assertNotIn("queue_name='background'", src)


if __name__ == "__main__":
    unittest.main()
