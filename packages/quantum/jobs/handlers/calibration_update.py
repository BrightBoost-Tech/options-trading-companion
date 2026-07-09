"""
Calibration Update Job Handler

5:00 AM Chicago — Recompute calibration adjustments from recent outcomes.

Runs daily before market open. Computes per-(strategy, regime, dte_bucket)
EV and PoP multipliers from recent closed positions, then caches them in
calibration_adjustments for fast lookup during suggestion scoring.

Requires MIN_CALIBRATION_TRADES (default 8; see calibration_service.py)
outcomes. The window ESCALATES on insufficient data: the base window
(default 30d) widens through CALIBRATION_WINDOW_ESCALATION_DAYS (default
"60,90") until the sample clears the threshold — the CORRUPTED_PNL_FLOOR
inside CalibrationService._fetch_outcomes bounds every widened window at
clean data, so escalation can never regress onto the pre-2026-04-13
corrupted rows. Origin: the 2026-05-15→06-09 freeze, where the fixed 30d
window (7 outcomes < 8) silently no-opped for 25 days while 18 clean
outcomes sat just outside it.

If NO window yields a write for a user, the result says so loudly
(per-user status with sample sizes) and, when the newest cached blob is
older than CALIBRATION_MAX_AGE_DAYS, a `calibration_stale` risk_alert
fires from the producer side too (the consumer-side TTL in
get_calibration_adjustments is the second layer).
"""

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from packages.quantum.jobs.handlers.utils import get_admin_client, get_active_user_ids, run_async
from packages.quantum.jobs.handlers.exceptions import RetryableJobError, PermanentJobError

logger = logging.getLogger(__name__)

JOB_NAME = "calibration_update"


def _escalation_windows(base_window_days: int) -> List[int]:
    """The ordered list of windows to try: base first, then each escalation
    step strictly wider than the base. Malformed env values fall back to the
    default ladder (never silently to no-escalation)."""
    raw = os.environ.get("CALIBRATION_WINDOW_ESCALATION_DAYS", "60,90")
    steps: List[int] = []
    try:
        steps = [int(s.strip()) for s in raw.split(",") if s.strip()]
    except ValueError:
        logger.warning(
            "[CALIBRATION] CALIBRATION_WINDOW_ESCALATION_DAYS=%r unparseable — "
            "using default 60,90", raw,
        )
        steps = [60, 90]
    windows = [base_window_days] + sorted({s for s in steps if s > base_window_days})
    return windows


def _compute_with_escalation(
    svc: Any, user_id: str, base_window_days: int
) -> Tuple[Dict[str, Any], int, List[Dict[str, Any]]]:
    """Run compute_calibration_adjustments, widening the window on
    insufficient_data. Returns (final_result, window_used, attempts) where
    attempts records every (window_days, status, sample_size) tried."""
    attempts: List[Dict[str, Any]] = []
    result: Dict[str, Any] = {}
    window_used = base_window_days
    for window in _escalation_windows(base_window_days):
        result = svc.compute_calibration_adjustments(user_id, window_days=window)
        window_used = window
        attempts.append({
            "window_days": window,
            "status": result.get("status"),
            "sample_size": result.get("sample_size", result.get("total_outcomes")),
        })
        if result.get("status") != "insufficient_data":
            break
        logger.info(
            "[CALIBRATION] user=%s window=%sd insufficient (%s < %s) — widening",
            user_id[:8], window,
            result.get("sample_size"), result.get("minimum_required"),
        )
    return result, window_used, attempts


def _last_write_age_days(client: Any, user_id: str) -> Optional[float]:
    """Age in days of the newest cached blob for this user, or None."""
    try:
        res = (
            client.table("calibration_adjustments")
            .select("computed_at")
            .eq("user_id", user_id)
            .order("computed_at", desc=True)
            .limit(1)
            .execute()
        )
        if not res.data:
            return None
        ts = str(res.data[0]["computed_at"]).replace("Z", "+00:00").replace(" ", "T", 1)
        computed_at = datetime.fromisoformat(ts)
        if computed_at.tzinfo is None:
            computed_at = computed_at.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - computed_at).total_seconds() / 86400.0
    except Exception as e:
        logger.warning("[CALIBRATION] last-write age lookup failed: %s", e)
        return None


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """
    Recompute calibration adjustments for all active users.

    Payload:
        - window_days: int - Base lookback window (default: 30; escalates)
        - user_id: str|None - Specific user, or all if None
    """
    start_time = time.time()
    window_days = payload.get("window_days", 30)
    target_user_id = payload.get("user_id")

    try:
        client = get_admin_client()

        if target_user_id:
            active_users = [target_user_id]
        else:
            active_users = get_active_user_ids(client)

        async def process_users():
            from packages.quantum.analytics.calibration_service import (
                CalibrationService,
                CALIBRATION_MAX_AGE_DAYS,
            )

            users_updated = 0
            users_skipped = 0
            user_details: List[Dict[str, Any]] = []

            for uid in active_users:
                svc = CalibrationService(client)
                result, window_used, attempts = _compute_with_escalation(
                    svc, uid, window_days
                )

                detail: Dict[str, Any] = {
                    "user": uid[:8],
                    "status": result.get("status"),
                    "window_used": window_used,
                    "attempts": attempts,
                }

                if result.get("status") != "ok":
                    users_skipped += 1
                    # Producer-side staleness honesty: a skip is fine for a
                    # day, but a skip while the served blob has outlived its
                    # TTL means the loop is broken — say so loudly instead of
                    # the silent {ok:true, users_updated:0} that hid the
                    # 2026-05-15→06-09 freeze.
                    age = _last_write_age_days(client, uid)
                    detail["last_write_age_days"] = round(age, 1) if age is not None else None
                    if age is not None and age > CALIBRATION_MAX_AGE_DAYS:
                        try:
                            from packages.quantum.observability.alerts import alert
                            # "critical": a broken feedback loop feeding live
                            # entry scoring — same class as the OBP-read
                            # failure precedent (equity_state). Fires at most
                            # once daily from this job, only past the TTL.
                            alert(
                                client,
                                alert_type="calibration_stale",
                                severity="critical",
                                message=(
                                    f"calibration_update produced no write again "
                                    f"(status={result.get('status')}, windows tried "
                                    f"{[a['window_days'] for a in attempts]}); newest blob "
                                    f"is {age:.1f}d old (TTL {CALIBRATION_MAX_AGE_DAYS:.0f}d)"
                                ),
                                user_id=uid,
                                metadata={
                                    "attempts": attempts,
                                    "last_write_age_days": round(age, 1),
                                    "function_name": "calibration_update.run",
                                },
                            )
                        except Exception as alert_err:
                            logger.warning(
                                "[CALIBRATION] stale-alert write failed: %s", alert_err
                            )
                    # Raw-mode reset (#1076): on insufficient_data ONLY, WRITE an
                    # empty blob so the served row reflects raw mode.
                    # get_calibration_adjustments serves the LATEST row, so
                    # without this the prior (possibly contaminated) blob keeps
                    # being applied — the 06-18 ×1.5-still-served bug. NOT on
                    # status=error (a transient fetch failure surfaces as error):
                    # last-good is left intact (point 3). apply_calibration on an
                    # empty blob already falls through to ×1.0.
                    if result.get("status") == "insufficient_data":
                        try:
                            client.table("calibration_adjustments").insert({
                                "user_id": uid,
                                "adjustments": {},
                                "total_outcomes": int(result.get("sample_size") or 0),
                                "computed_at": datetime.now(timezone.utc).isoformat(),
                            }).execute()
                            detail["raw_mode_reset_written"] = True
                        except Exception as reset_err:
                            logger.warning(
                                "[CALIBRATION] raw-mode reset write failed for "
                                "%s: %s", uid[:8], reset_err,
                            )
                            detail["raw_mode_reset_written"] = False
                            detail["reset_error"] = str(reset_err)[:200]
                    user_details.append(detail)
                    continue

                # Cache adjustments
                try:
                    client.table("calibration_adjustments").insert({
                        "user_id": uid,
                        "adjustments": result["adjustments"],
                        "total_outcomes": result["total_outcomes"],
                        "computed_at": datetime.now(timezone.utc).isoformat(),
                    }).execute()
                    users_updated += 1
                    detail["total_outcomes"] = result["total_outcomes"]
                    # FAIL-LOUD compute-side (2026-07-09 EOD): make the
                    # split-brain visible from the WRITE side too — a real
                    # multiplier was just stored, but if the apply gate is off
                    # nothing will read it.
                    try:
                        from packages.quantum.analytics.calibration_service import (
                            CALIBRATION_ENABLED as _CAL_EN,
                        )
                        if not _CAL_EN:
                            logger.warning(
                                "[CALIBRATION] wrote a multiplier blob for %s "
                                "(n=%s) but APPLY is DISABLED "
                                "(CALIBRATION_ENABLED falsy) — computed-but-not-"
                                "applied split-brain; no scan will use it until "
                                "the flag is set + workers recycle.",
                                uid[:8], result.get("total_outcomes"),
                            )
                    except Exception:
                        pass
                except Exception as e:
                    print(f"[CALIBRATION] Failed to cache for {uid[:8]}: {e}")
                    users_skipped += 1
                    detail["status"] = "cache_write_failed"
                    detail["error"] = str(e)[:200]
                user_details.append(detail)

            return users_updated, users_skipped, user_details

        updated, skipped, details = run_async(process_users())

        timing_ms = (time.time() - start_time) * 1000

        return {
            "ok": True,
            "users_updated": updated,
            "users_skipped": skipped,
            "window_days": window_days,
            "user_details": details,
            "timing_ms": timing_ms,
        }

    except ValueError as e:
        raise PermanentJobError(f"Configuration error: {e}")
    except Exception as e:
        raise RetryableJobError(f"Calibration update failed: {e}")
