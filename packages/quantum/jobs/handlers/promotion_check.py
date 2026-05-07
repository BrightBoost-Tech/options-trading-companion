"""
Promotion Check Job Handler

Runs daily after market close. For users in micro_live phase, evaluates
the equity-based full_auto promotion gate and auto-promotes when all
gates pass.

Rewritten 2026-05-06:
- Old logic read a `micro_live_green_days` field that doesn't exist
  in go_live_progression schema. Handler fired 23 times historically
  without ever triggering the "READY" alert because the counter was
  permanently 0 (default for missing keys).
- New logic uses ProgressionService.is_eligible_for_full_auto which
  evaluates: broker equity ≥ $1500 + cumulative realized_pl > 0 +
  Alpaca-real trade count ≥ 3.

When all gates pass, this handler auto-promotes via
ProgressionService.promote() — no manual approval required. Manual
override remains available via direct promote() calls.

For users where the gate blocks, log the reason but do NOT pollute
risk_alerts with daily "still not eligible" rows (per loud-error
doctrine: not-yet-eligible is the expected state, not a failure).
"""

import logging
import time
from typing import Any, Dict

from packages.quantum.services.progression_service import ProgressionService
from packages.quantum.jobs.handlers.utils import get_admin_client, get_active_user_ids
from packages.quantum.jobs.handlers.exceptions import RetryableJobError

logger = logging.getLogger(__name__)

JOB_NAME = "promotion_check"


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """
    Evaluate full_auto promotion eligibility for all active users in
    micro_live phase. Auto-promote when gates pass.
    """
    start_time = time.time()

    try:
        client = get_admin_client()
        users = get_active_user_ids(client)
        promoted = []
        blocked = []

        for uid in users:
            try:
                svc = ProgressionService(client)
                state = svc.get_state(uid)
                phase = state.get("current_phase", "")

                if phase != "micro_live":
                    continue  # only the micro_live → full_auto path runs here

                eligibility = svc.is_eligible_for_full_auto(uid)

                if eligibility["eligible"]:
                    _execute_auto_promotion(svc, client, uid, eligibility)
                    promoted.append({
                        "user_id": uid[:8],
                        "from_phase": "micro_live",
                        "to_phase": "full_auto",
                        "equity": eligibility["equity"],
                        "cumulative_realized_pl": eligibility["cumulative_realized_pl"],
                        "alpaca_real_trade_count": eligibility["alpaca_real_trade_count"],
                    })
                else:
                    blocked.append({
                        "user_id": uid[:8],
                        "phase": phase,
                        "reason": eligibility["reason"],
                        "equity": eligibility["equity"],
                        "cumulative_realized_pl": eligibility["cumulative_realized_pl"],
                        "alpaca_real_trade_count": eligibility["alpaca_real_trade_count"],
                    })
                    logger.info(
                        f"[PROMOTION_CHECK] {uid[:8]} micro_live → full_auto: "
                        f"BLOCKED — {eligibility['reason']} "
                        f"(equity=${eligibility['equity']:.2f}, "
                        f"pl=${eligibility['cumulative_realized_pl']:.2f}, "
                        f"trades={eligibility['alpaca_real_trade_count']})"
                    )

            except Exception as e:
                logger.error(f"[PROMOTION_CHECK] Error checking {uid[:8]}: {e}")

        timing_ms = (time.time() - start_time) * 1000

        if promoted:
            logger.warning(
                f"[PROMOTION_CHECK] AUTO-PROMOTED {len(promoted)} user(s) "
                f"to full_auto: {[p['user_id'] for p in promoted]}"
            )

        return {
            "ok": True,
            "promoted_count": len(promoted),
            "blocked_count": len(blocked),
            "promoted": promoted,
            "blocked": blocked,
            "timing_ms": timing_ms,
        }

    except Exception as e:
        raise RetryableJobError(f"Promotion check failed: {e}")


def _execute_auto_promotion(
    svc: ProgressionService,
    client: Any,
    user_id: str,
    eligibility: Dict[str, Any],
) -> None:
    """Promote user to full_auto + write phase_auto_promoted risk_alert.

    Uses ProgressionService.promote() with trigger_details to record the
    auto-trigger context in the audit log, then writes a separate
    risk_alerts row for operator visibility (severity=warning since
    promotion is good news, not an emergency).
    """
    trigger_details = {
        "trigger": "auto_full_auto_gate",
        "equity": eligibility["equity"],
        "cumulative_realized_pl": eligibility["cumulative_realized_pl"],
        "alpaca_real_trade_count": eligibility["alpaca_real_trade_count"],
        "reason": eligibility["reason"],
    }
    result = svc.promote(user_id, "full_auto", trigger_details=trigger_details)

    if result.get("error"):
        # Transition validation rejected — log and skip alert
        logger.error(
            f"[PROMOTION_CHECK] promote({user_id[:8]}, full_auto) refused: "
            f"{result['error']}"
        )
        return

    # Operator-visible alert at warning severity (state-change, not error)
    try:
        from packages.quantum.observability.alerts import alert, _get_admin_supabase
        alert(
            _get_admin_supabase(),
            user_id=user_id,
            alert_type="phase_auto_promoted",
            severity="warning",
            message=(
                f"User auto-promoted micro_live → full_auto "
                f"(equity=${eligibility['equity']:.2f}, "
                f"cumulative_pl=${eligibility['cumulative_realized_pl']:.2f}, "
                f"trades={eligibility['alpaca_real_trade_count']})"
            ),
            metadata={
                "from_phase": "micro_live",
                "to_phase": "full_auto",
                "equity": eligibility["equity"],
                "cumulative_realized_pl": eligibility["cumulative_realized_pl"],
                "alpaca_real_trade_count": eligibility["alpaca_real_trade_count"],
                "trigger": "auto_full_auto_gate",
                "doctrine_ref": "phase_auto_promotion_v1",
            },
        )
    except Exception as e:
        # Alert write failure must not undo the promotion. Per doctrine
        # Valid 5 (alert-write recursion prevention).
        logger.exception(f"[PROMOTION_CHECK] Failed to write phase_auto_promoted alert: {e}")
