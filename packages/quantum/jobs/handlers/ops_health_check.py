"""
Ops Health Check Job Handler

Phase 1.1 Enhanced:
1. Computes full ops health status with expanded market data freshness
2. Sends alerts with severity levels and cooldown suppression
3. Writes audit events for observability
4. Returns result summary in job_runs.result with fingerprints for cooldown tracking
"""

import os
import time
from typing import Any, Dict, List
from datetime import datetime, timezone
import uuid
import logging

from packages.quantum.services.ops_health_service import (
    compute_data_freshness,
    get_expected_jobs,
    get_output_freshness,
    get_recent_failures,
    get_silent_job_failures,
    find_prior_silent_failure_alert,
    a4_failure_signature,
    A4_DETECTOR_VERSION,
    get_suggestions_stats,
    get_integrity_stats,
    send_ops_alert,
    # Phase 1.1 additions
    build_freshness_universe,
    compute_market_data_freshness,
    get_alert_fingerprint,
    should_suppress_alert,
    send_ops_alert_v2,
    is_us_market_hours,
    relay_direct_insert_alerts,
    get_signal_accuracy,
    evaluate_signal_accuracy,
    OPS_ALERT_MIN_SEVERITY,
    OPS_ALERT_COOLDOWN_MINUTES,
)
from packages.quantum.observability.alerts import alert as _alert
from packages.quantum.observability.audit_log_service import AuditLogService
from packages.quantum.jobs.handlers.utils import get_admin_client
from packages.quantum.jobs.handlers.exceptions import RetryableJobError

logger = logging.getLogger(__name__)

JOB_NAME = "ops_health_check"

# System user ID for background jobs
SYSTEM_USER_ID = "00000000-0000-0000-0000-000000000000"


def _broker_market_open() -> Any:
    """Read the broker-authoritative session state once per health cycle.

    ``None`` is a typed degraded result: callers then retain the existing ET
    wall-clock fallback. A successful ``False`` is load-bearing on exchange
    holidays and must never be collapsed with failure.
    """
    try:
        from packages.quantum.brokers.alpaca_client import get_alpaca_client

        clock = get_alpaca_client().get_market_clock()
        return bool(clock["is_open"])
    except Exception as exc:
        logger.warning(
            "[OPS_HEALTH_CHECK] broker clock unavailable; using ET fallback: %s",
            exc,
        )
        return None


def _run_alert_relay(client: Any) -> Dict[str, Any]:
    """A3 egress-relay step, fail-isolated: a relay bug must never fail the
    health check, and the relay itself already never raises — this wrapper
    guards the seam anyway (double isolation, same as the audit-event step).
    """
    try:
        return relay_direct_insert_alerts(client)
    except Exception as e:
        logger.warning(f"[OPS_HEALTH_CHECK] alert relay step failed: {e}")
        return {"error": str(e)[:200]}


def _check_signal_accuracy(
    client: Any, min_severity: str, cooldown_minutes: int
) -> Dict[str, Any]:
    """Gap-2 (2026-07-02) rolling signal-accuracy telemetry — OBSERVE-ONLY,
    fail-isolated: reads the live-only rolling view, alerts (warning, with
    the standard fingerprint cooldown) when the overall hit-rate is degraded
    at a meaningful sample. Modulates no decision path; a failure here must
    never fail the health check."""
    try:
        rows = get_signal_accuracy(client)
        verdict = evaluate_signal_accuracy(rows)
        out: Dict[str, Any] = {
            "degraded": verdict["degraded"],
            "reason": verdict["reason"],
            "scopes": rows,
            "alerted": False,
        }
        if not verdict["degraded"]:
            return out
        overall = verdict["overall"] or {}
        # ACCURACY-WARN DEDUP (2026-07-11): observe-only, was re-firing ~14-20×/
        # day (constant fingerprint + 30-min cooldown on a stable degraded value).
        # Fold wins/n into the fingerprint (re-alert only when the value CHANGES)
        # + a 24h cooldown (a stable value alerts at most once/day). Stays
        # observe-only — modulates nothing.
        fingerprint = get_alert_fingerprint(
            "signal_accuracy_degraded",
            {"scope": "overall", "wins": overall.get("wins"), "n": overall.get("n")},
        )
        suppressed, _last = should_suppress_alert(client, fingerprint, 1440)
        if suppressed:
            out["suppressed"] = "cooldown"
            return out
        alert_result = send_ops_alert_v2(
            "signal_accuracy_degraded",
            (
                f"Rolling live signal accuracy degraded: {verdict['reason']} "
                f"(wins {overall.get('wins')}/{overall.get('n')}, "
                f"brier {overall.get('brier')} over n={overall.get('brier_n')}). "
                f"Observe-only — no decision path reads this."
            ),
            details={"overall": overall},
            severity="warning",
            min_severity=min_severity,
            client=client,
        )
        out["alerted"] = bool(alert_result.get("sent"))
        return out
    except Exception as e:
        logger.warning(f"[OPS_HEALTH_CHECK] signal-accuracy step failed: {e}")
        return {"error": str(e)[:200], "degraded": False, "alerted": False}


def build_data_stale_alert_content(
    market_freshness: Any, job_freshness: Any
) -> tuple:
    """Build the data_stale alert (message, details, fingerprint_details)
    from the freshness arm(s) that actually FIRED.

    A9 2026-07-02: the firing predicate ORs market_freshness |
    job_freshness, but the alert content was built from market_freshness
    unconditionally — a job-arm-only firing emitted the self-contradictory
    "Market data is stale ... Stale: 0 (). Reason: ok" shape (57/69 of the
    trailing-30d firings). This is content/fingerprint wiring ONLY: when
    alerts fire is unchanged, and a market-arm-only firing emits the exact
    legacy message AND the exact legacy fingerprint shape (so its cooldown
    history survives the deploy). PURE — no I/O, no env reads.

    Returns:
        (message, details, fingerprint_details)
    """
    message_parts: List[str] = []
    details: Dict[str, Any] = {}
    fingerprint_details: Dict[str, Any] = {}
    arms: List[str] = []

    if market_freshness.is_stale:
        arms.append("market")
        message_parts.append(
            f"Market data is stale. Universe: {market_freshness.universe_size} symbols. "
            f"Stale: {len(market_freshness.stale_symbols)} ({', '.join(market_freshness.stale_symbols[:3])}). "
            f"Source: {market_freshness.source}. Reason: {market_freshness.reason}"
        )
        details.update({
            "universe_size": market_freshness.universe_size,
            "stale_symbols": market_freshness.stale_symbols,
            "source": market_freshness.source,
            "age_seconds": market_freshness.age_seconds,
        })
        fingerprint_details["symbols"] = (
            sorted(market_freshness.stale_symbols[:5])
            if market_freshness.stale_symbols else []
        )
        fingerprint_details["source"] = market_freshness.source

    if job_freshness.is_stale:
        arms.append("job")
        age_min = (
            round(job_freshness.age_seconds / 60.0, 1)
            if job_freshness.age_seconds is not None else None
        )
        message_parts.append(
            f"Job-based data freshness is stale. Source: {job_freshness.source}. "
            f"Age: {age_min} min. Reason: {job_freshness.reason}"
        )
        details.update({
            "job_source": job_freshness.source,
            "job_age_seconds": job_freshness.age_seconds,
            "job_reason": job_freshness.reason,
        })
        # Per-arm dedup: job-arm firings no longer hash the (empty) market
        # symbol list — distinct job-side problems get distinct fingerprints.
        fingerprint_details["job_source"] = job_freshness.source
        fingerprint_details["job_reason"] = job_freshness.reason

    details["trigger_source"] = "+".join(arms)
    # Market-arm-only keeps the EXACT legacy fingerprint shape
    # ({symbols, source}); any firing involving the job arm carries the
    # arms marker so the shapes can never collide.
    if arms != ["market"]:
        fingerprint_details["arms"] = arms

    return " | ".join(message_parts), details, fingerprint_details


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """
    Run ops health check with Phase 1.1 enhancements.

    1. Builds expanded freshness universe (SPY/QQQ + holdings + suggestions)
    2. Computes market data freshness + job status + suggestions stats
    3. Sends alerts with severity filtering and cooldown suppression
    4. Writes audit event with health snapshot
    5. Returns result with alert fingerprints for future cooldown checks

    Payload:
        - timestamp: str - Task trigger timestamp
        - force: bool - Force run even if recently completed

    Returns:
        Dict with ok, issues_found, alerts_sent, alerts_suppressed,
        alert_fingerprints, market_freshness, health_snapshot, timing_ms
    """
    start_time = time.time()
    alerts_sent: List[str] = []
    alerts_failed: List[str] = []
    alerts_suppressed: List[Dict[str, Any]] = []
    alert_fingerprints: List[str] = []
    issues_found: List[str] = []

    # Get config from env
    min_severity = os.getenv("OPS_ALERT_MIN_SEVERITY", OPS_ALERT_MIN_SEVERITY)
    cooldown_minutes = int(os.getenv("OPS_ALERT_COOLDOWN_MINUTES", str(OPS_ALERT_COOLDOWN_MINUTES)))

    try:
        client = get_admin_client()
        trace_id = str(uuid.uuid4())

        # v5-A4 synthetic end-to-end delivery proof — operator-triggered
        # only (payload flag). Sends ONE critical alert through the real
        # dual-channel path so the risk_alerts write can be verified and
        # then cleaned up. Never fires on scheduled runs.
        if payload.get("synthetic_delivery_test"):
            synth = send_ops_alert_v2(
                "synthetic_delivery_test",
                "Synthetic ops-alert delivery proof (v5-A4) — verify a "
                "risk_alerts row exists, then delete it.",
                details={"requested_at": payload.get("timestamp")},
                severity="critical",
                min_severity=min_severity,
                client=client,
            )
            return {
                "ok": True,
                "synthetic_delivery_test": synth,
                "timing_ms": (time.time() - start_time) * 1000,
            }

        # ==============================================================
        # 0. A3 egress relay — direct-insert critical/high risk_alerts
        #    rows out the ops webhook. FIRST body step, own isolation:
        #    delivery of an already-recorded critical must not wait on
        #    (or die with) the freshness checks below.
        # ==============================================================
        logger.info("[OPS_HEALTH_CHECK] Relaying direct-insert alerts...")
        alert_relay = _run_alert_relay(client)

        # One broker-clock read controls both RTH alert families. A successful
        # closed reading covers weekends, exchange holidays, and half-days;
        # failure stays distinguishable from closed and degrades to the
        # existing ET wall-clock predicate.
        broker_is_open = _broker_market_open()

        # ==============================================================
        # 1. Build expanded freshness universe and check market data
        # ==============================================================
        logger.info("[OPS_HEALTH_CHECK] Building freshness universe...")
        universe = build_freshness_universe(client)
        logger.info(f"[OPS_HEALTH_CHECK] Universe: {len(universe)} symbols: {universe[:5]}...")

        logger.info("[OPS_HEALTH_CHECK] Computing market data freshness...")
        market_freshness = compute_market_data_freshness(universe)

        # Also compute job-based freshness for backwards compatibility
        job_freshness = compute_data_freshness(client)

        # Determine overall staleness: stale if either source indicates stale
        is_data_stale = market_freshness.is_stale or job_freshness.is_stale

        if is_data_stale:
            stale_reason = market_freshness.reason if market_freshness.is_stale else job_freshness.reason
            issues_found.append(f"Data stale: {stale_reason}")

            # A9 2026-07-02: message/details/fingerprint from the arm(s)
            # that FIRED (job-arm firings previously wore a market-data
            # costume). The predicate above is unchanged.
            alert_message, alert_details, fingerprint_details = (
                build_data_stale_alert_content(market_freshness, job_freshness)
            )
            fingerprint = get_alert_fingerprint("data_stale", fingerprint_details)

            # Check cooldown + market hours (v5-A4: snapshots age past any
            # threshold every evening by construction — the data_stale ALERT
            # is market-hours-gated so the new risk_alerts channel doesn't
            # import nightly noise; the snapshot still records staleness).
            suppressed, last_sent = should_suppress_alert(client, fingerprint, cooldown_minutes)
            # Keep the legacy wall-clock predicate as the explicit degraded
            # fallback. A successful broker False is authoritative on exchange
            # holidays; None means the broker read failed, not that it closed.
            market_is_open = (
                broker_is_open
                if broker_is_open is not None
                else is_us_market_hours()
            )
            if not market_is_open:
                suppressed, last_sent = True, "outside_market_hours"

            if not suppressed:
                alert_result = send_ops_alert_v2(
                    "data_stale",
                    alert_message,
                    details=alert_details,
                    severity="error",
                    min_severity=min_severity,
                    client=client,
                )
                if alert_result["sent"]:
                    alerts_sent.append("data_stale")
                    alert_fingerprints.append(fingerprint)
                elif alert_result["suppressed_reason"]:
                    alerts_suppressed.append({
                        "type": "data_stale",
                        "reason": alert_result["suppressed_reason"],
                    })
            else:
                alerts_suppressed.append({
                    "type": "data_stale",
                    "reason": (
                        "outside_market_hours"
                        if last_sent == "outside_market_hours" else "cooldown"
                    ),
                    "last_sent": last_sent,
                })

        # ==============================================================
        # 2. Check expected job status
        # ==============================================================
        logger.info("[OPS_HEALTH_CHECK] Checking expected jobs...")
        expected_jobs = get_expected_jobs(
            client,
            broker_is_open=broker_is_open,
        )

        for job in expected_jobs:
            if job.status == "late":
                issues_found.append(f"Job late: {job.name}")

                fingerprint = get_alert_fingerprint("job_late", {"job_name": job.name})
                suppressed, last_sent = should_suppress_alert(client, fingerprint, cooldown_minutes)

                if not suppressed:
                    alert_result = send_ops_alert_v2(
                        "job_late",
                        f"Job `{job.name}` ({job.cadence}) is late. "
                        f"Last success: {job.last_success_at or 'never'}",
                        details={"job_name": job.name, "cadence": job.cadence},
                        severity="warning",
                        min_severity=min_severity,
                        client=client,
                    )
                    if alert_result["sent"]:
                        alerts_sent.append(f"job_late:{job.name}")
                        alert_fingerprints.append(fingerprint)
                    elif alert_result["suppressed_reason"]:
                        alerts_suppressed.append({
                            "type": f"job_late:{job.name}",
                            "reason": alert_result["suppressed_reason"],
                        })
                else:
                    alerts_suppressed.append({
                        "type": f"job_late:{job.name}",
                        "reason": "cooldown",
                        "last_sent": last_sent,
                    })

            elif job.status == "never_run":
                issues_found.append(f"Job never run: {job.name}")

                fingerprint = get_alert_fingerprint("job_never_run", {"job_name": job.name})
                suppressed, last_sent = should_suppress_alert(client, fingerprint, cooldown_minutes)

                if not suppressed:
                    alert_result = send_ops_alert_v2(
                        "job_never_run",
                        f"Job `{job.name}` ({job.cadence}) has NEVER run. "
                        f"Scheduler may be down or misconfigured.",
                        details={"job_name": job.name, "cadence": job.cadence},
                        severity="critical",
                        min_severity=min_severity,
                        client=client,
                    )
                    if alert_result["sent"]:
                        alerts_sent.append(f"job_never_run:{job.name}")
                        alert_fingerprints.append(fingerprint)
                    elif alert_result.get("suppressed_reason"):
                        alerts_suppressed.append({
                            "type": f"job_never_run:{job.name}",
                            "reason": alert_result["suppressed_reason"],
                        })
                else:
                    alerts_suppressed.append({
                        "type": f"job_never_run:{job.name}",
                        "reason": "cooldown",
                        "last_sent": last_sent,
                    })

            elif job.status == "error":
                issues_found.append(f"Job check error: {job.name}")

        # ==============================================================
        # 2.5 Check feedback-loop OUTPUT freshness (job ran ≠ job wrote —
        #     the distinction that hid the 25-day calibration freeze)
        # ==============================================================
        logger.info("[OPS_HEALTH_CHECK] Checking output freshness...")
        output_freshness = get_output_freshness(client)

        for out in output_freshness:
            if out.status in ("stale", "never"):
                issues_found.append(f"Output {out.status}: {out.table}")

                fingerprint = get_alert_fingerprint(
                    "output_stale", {"table": out.table}
                )
                suppressed, last_sent = should_suppress_alert(
                    client, fingerprint, cooldown_minutes
                )

                if not suppressed:
                    alert_result = send_ops_alert_v2(
                        "output_stale",
                        f"Feedback-loop output `{out.table}` is {out.status}: "
                        f"newest row "
                        f"{f'{out.age_hours:.0f}h old' if out.age_hours is not None else 'absent'} "
                        f"(max {out.max_age_hours}h). The producing job may be "
                        f"silently no-opping even if its job_runs are green.",
                        details={
                            "table": out.table,
                            "status": out.status,
                            "age_hours": out.age_hours,
                            "max_age_hours": out.max_age_hours,
                        },
                        severity="error",
                        min_severity=min_severity,
                        client=client,
                    )
                    if alert_result["sent"]:
                        alerts_sent.append(f"output_stale:{out.table}")
                        alert_fingerprints.append(fingerprint)
                    elif alert_result.get("suppressed_reason"):
                        alerts_suppressed.append({
                            "type": f"output_stale:{out.table}",
                            "reason": alert_result["suppressed_reason"],
                        })
                else:
                    alerts_suppressed.append({
                        "type": f"output_stale:{out.table}",
                        "reason": "cooldown",
                        "last_sent": last_sent,
                    })

        # ==============================================================
        # 3. Check recent failures
        # ==============================================================
        logger.info("[OPS_HEALTH_CHECK] Checking recent failures...")
        recent_failures = get_recent_failures(client)

        if recent_failures:
            failure_names = sorted(set(f["job_name"] for f in recent_failures[:5]))
            issues_found.append(f"Recent failures: {', '.join(failure_names)}")

            fingerprint = get_alert_fingerprint("job_failure", {"jobs": failure_names})
            suppressed, last_sent = should_suppress_alert(client, fingerprint, cooldown_minutes)

            if not suppressed:
                alert_result = send_ops_alert_v2(
                    "job_failure",
                    f"{len(recent_failures)} job failures in last 24h: {', '.join(failure_names)}",
                    details={"count": len(recent_failures), "jobs": failure_names},
                    severity="error",
                    min_severity=min_severity,
                    client=client,
                )
                if alert_result["sent"]:
                    alerts_sent.append("job_failure")
                    alert_fingerprints.append(fingerprint)
                elif alert_result["suppressed_reason"]:
                    alerts_suppressed.append({
                        "type": "job_failure",
                        "reason": alert_result["suppressed_reason"],
                    })
            else:
                alerts_suppressed.append({
                    "type": "job_failure",
                    "reason": "cooldown",
                    "last_sent": last_sent,
                })

        # ==============================================================
        # 3.5 A4 silent-failure detector: jobs that returned
        #     status='succeeded' while their own result.counts.errors > 0
        #     (the masking class — paper_learning_ingest ran 5× "succeeded"
        #     with errors=1 for 6 days, invisible to status-keyed checks).
        #     Fires via the canonical observability alert() with a NEW
        #     alert_type that egresses through _RISK_EGRESS_ALERT_TYPES.
        # ==============================================================
        logger.info("[OPS_HEALTH_CHECK] Checking silent job failures...")
        silent_failures = get_silent_job_failures(client)

        for sf in silent_failures:
            job_name = sf.get("job_name") or "unknown"
            error_count = sf.get("error_count", 0)
            issues_found.append(
                f"Silent failure: {job_name} (errors={error_count})"
            )

            # DURABLE RE-FIRE DEDUP (2026-07-20): the SAME succeeded/partial-
            # with-errors run re-detects on every :07/:37 poll across the
            # detector's ~24h lookback. The prior (2026-07-11) fingerprint
            # cooldown read its sent-fingerprint list back out of only the last
            # 5 ops_health_check runs (`should_suppress_alert` limit(5) ≈ 2.5h)
            # — far shorter than the 24h re-detection window — so a given run
            # re-emitted a fresh HIGH roughly every 3h (df3c56e9 fired
            # 14:07/17:07/20:07Z on 2026-07-20 → the 6 open HIGHs). Key the emit
            # instead on the DURABLE, append-only risk_alerts rows themselves:
            # identity (run_id, alert_type, detector_version, failure_signature).
            # The FIRST emit for an identity stands; a repeat is a TYPED
            # suppressed_duplicate (no new HIGH row, no new egress); a
            # materially changed failure signature OR a new detector_version
            # re-emits. Historical rows (no version/signature field) are matched
            # by deriving those from their own metadata — the known incident is
            # suppressed with ZERO mutation of any existing row. Genuine safety
            # trips (force_close / streak_breaker_* / force_close_failed) are a
            # DIFFERENT alert_type and are entirely UNAFFECTED.
            _run_id = sf.get("run_id")
            _failure_signature = a4_failure_signature(job_name, error_count)
            _prior = find_prior_silent_failure_alert(
                client,
                run_id=_run_id,
                detector_version=A4_DETECTOR_VERSION,
                failure_signature=_failure_signature,
            )
            if _prior is not None:
                alerts_suppressed.append({
                    "type": f"job_succeeded_with_errors:{job_name}",
                    "reason": "duplicate",
                    "run_id": _run_id,
                    "detector_version": A4_DETECTOR_VERSION,
                    "failure_signature": _failure_signature,
                    "prior_alert_id": _prior.get("id"),
                })
                continue

            # alert() is the canonical primitive (never raises) and egresses
            # this high-severity allowlisted type via _maybe_egress_risk_alert.
            # The identity fields are persisted into metadata so the NEXT poll's
            # durable lookup matches on the explicit fields (and future rows
            # never need the historical-derivation path).
            _alert(
                client,
                alert_type="job_succeeded_with_errors",
                severity="high",
                message=(
                    f"Job `{job_name}` reported status=succeeded but its "
                    f"result.counts.errors={error_count} — a silently masked "
                    f"failure (status-keyed checks miss it)."
                ),
                metadata={
                    "source": "ops_health_check",
                    "job_name": job_name,
                    "error_count": error_count,
                    "run_id": _run_id,
                    "finished_at": sf.get("finished_at"),
                    "detector_version": A4_DETECTOR_VERSION,
                    "failure_signature": _failure_signature,
                },
            )
            alerts_sent.append(f"job_succeeded_with_errors:{job_name}")

        # ==============================================================
        # 3.7 Gap-2: rolling signal-accuracy telemetry (observe-only,
        #     fail-isolated — reads the live-only rolling view, warns on
        #     degraded hit-rate at a meaningful sample; modulates nothing)
        # ==============================================================
        logger.info("[OPS_HEALTH_CHECK] Checking signal accuracy...")
        signal_accuracy = _check_signal_accuracy(client, min_severity, cooldown_minutes)
        if signal_accuracy.get("degraded"):
            issues_found.append(f"Signal accuracy degraded: {signal_accuracy.get('reason')}")
            if signal_accuracy.get("alerted"):
                alerts_sent.append("signal_accuracy_degraded")

        # ==============================================================
        # 4. Get suggestions stats
        # ==============================================================
        suggestions_stats = get_suggestions_stats(client)

        # ==============================================================
        # 5. Get integrity stats
        # ==============================================================
        integrity_stats = get_integrity_stats(client)

        # ==============================================================
        # 6. Build health snapshot
        # ==============================================================
        health_snapshot = {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "market_freshness": {
                "is_stale": market_freshness.is_stale,
                "as_of": market_freshness.as_of.isoformat() if market_freshness.as_of else None,
                "age_seconds": market_freshness.age_seconds,
                "universe_size": market_freshness.universe_size,
                "stale_symbols": market_freshness.stale_symbols,
                "source": market_freshness.source,
                "reason": market_freshness.reason,
            },
            "job_freshness": {
                "is_stale": job_freshness.is_stale,
                "as_of": job_freshness.as_of.isoformat() if job_freshness.as_of else None,
                "age_seconds": job_freshness.age_seconds,
                "reason": job_freshness.reason,
                "source": job_freshness.source,
            },
            "jobs": {
                "expected": [
                    {
                        "name": j.name,
                        "status": j.status,
                        "cadence": j.cadence,
                        "last_success_at": j.last_success_at.isoformat() if j.last_success_at else None,
                    }
                    for j in expected_jobs
                ],
                "failure_count_24h": len(recent_failures),
                "silent_failure_count_24h": len(silent_failures),
                "silent_failures": silent_failures,
            },
            "output_freshness": [
                {
                    "table": o.table,
                    "status": o.status,
                    "age_hours": o.age_hours,
                    "max_age_hours": o.max_age_hours,
                    "latest": o.latest.isoformat() if o.latest else None,
                }
                for o in output_freshness
            ],
            "signal_accuracy": signal_accuracy,
            "suggestions": suggestions_stats,
            "integrity": integrity_stats,
            "issues_found": issues_found,
            "alerts_sent": alerts_sent,
            "alerts_failed": alerts_failed,
            "alerts_suppressed": alerts_suppressed,
        }

        # ==============================================================
        # 7. Write audit event
        # ==============================================================
        logger.info("[OPS_HEALTH_CHECK] Writing audit event...")
        try:
            audit_service = AuditLogService(client)
            audit_service.log_audit_event(
                user_id=SYSTEM_USER_ID,
                trace_id=trace_id,
                event_name="ops.health_check.completed",
                payload=health_snapshot,
                suggestion_id=None,
                strategy=None,
                regime=None,
            )
        except Exception as e:
            logger.warning(f"Failed to write health check audit event: {e}")

        timing_ms = (time.time() - start_time) * 1000
        is_healthy = len(issues_found) == 0

        logger.info(
            f"[OPS_HEALTH_CHECK] Complete. Healthy: {is_healthy}, "
            f"Issues: {len(issues_found)}, Alerts sent: {len(alerts_sent)}, "
            f"Alerts suppressed: {len(alerts_suppressed)}, "
            f"Timing: {timing_ms:.1f}ms"
        )

        return {
            # F-A4-1 (2026-07-11): the health CHECK ran successfully — issues
            # found are its PAYLOAD, not a job failure. Was ok=is_healthy, which
            # recorded ~332 designed-false 'succeeded+ok:false' rows (noise in
            # the false-green query). The real health is in `healthy`/issues.
            "ok": True,
            "healthy": is_healthy,
            "issues_found": issues_found,
            "alerts_sent": alerts_sent,
            "alerts_failed": alerts_failed,
            "alerts_suppressed": alerts_suppressed,
            "alert_relay": alert_relay,  # A3: DB-queryable relay counts
            "alert_fingerprints": alert_fingerprints,  # For cooldown tracking
            "market_freshness": {
                "is_stale": market_freshness.is_stale,
                "universe_size": market_freshness.universe_size,
                "stale_symbols": market_freshness.stale_symbols,
                "source": market_freshness.source,
                "reason": market_freshness.reason,
            },
            "health_snapshot": health_snapshot,
            "timing_ms": timing_ms,
        }

    except Exception as e:
        logger.error(f"[OPS_HEALTH_CHECK] Failed: {e}")
        raise RetryableJobError(f"Ops health check failed: {e}")
