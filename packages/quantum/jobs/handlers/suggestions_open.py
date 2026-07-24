"""
Suggestions Open Job Handler

11:00 AM Chicago - Generate OPEN/new positions suggestions.

This handler:
1. Loads strategy config by name
2. Scans for new entry opportunities
3. Persists suggestions to trade_suggestions table with window='midday_entry'
"""

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict

from packages.quantum.services.workflow_orchestrator import run_midday_cycle
from packages.quantum.services.strategy_loader import load_strategy_config, ensure_default_strategy_exists
from packages.quantum.jobs.handlers.utils import (
    get_admin_client,
    get_active_user_ids,
    run_async,
    is_market_day,
    MarketCalendarUnavailable,
)
from packages.quantum.jobs.handlers.exceptions import RetryableJobError, PermanentJobError
from packages.quantum.jobs.db import _to_jsonable
from packages.quantum.services.research_observer_status import (
    OBSERVER_TERMINAL_DISTRIBUTION,
    OBSERVER_SHADOW_FLEET,
    new_research_observers_block,
    record_observer_seam,
    redact_and_truncate,
)

JOB_NAME = "suggestions_open"


def _persist_error_rollup(cycle_results) -> int:
    """A9-F8 (2026-07-07) + E16-3 roll-up fix (PR-②, 2026-07-13): sum BOTH
    ``counts.rejection_persist_failures`` AND the generic nested
    ``counts.errors`` across cycle results, so ANY cycle-level error class
    reaches the TOP-LEVEL ``counts.errors`` the runner classifier reads.

    The 07-13 exhibit: #1188's replay_commit_error incremented the CYCLE's
    counts.errors, but this roll-up summed only rejection_persist_failures —
    the top-level overwrite erased it and all five broken tapes rode green
    jobs. Cycle producers today keep the two classes DISJOINT
    (rejection_persist_failures is never folded into cycle counts.errors), so
    summing both never double-counts. Pure; never raises on malformed shapes."""
    total = 0
    for cr in (cycle_results or []):
        try:
            counts = ((cr or {}).get("counts") or {})
            total += int(counts.get("rejection_persist_failures") or 0)
            total += int(counts.get("errors") or 0)
        except (AttributeError, TypeError, ValueError):
            continue
    return total


# Replay feature store integration (lazy import to avoid circular deps)
def _get_decision_context_class():
    """Lazy import DecisionContext to avoid circular imports."""
    try:
        from packages.quantum.services.replay.decision_context import (
            DecisionContext,
            is_replay_enabled,
        )
        return DecisionContext if is_replay_enabled() else None
    except ImportError:
        return None


def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    """
    Generate OPEN suggestions for all active users.

    Payload:
        - date: str - Date for idempotency
        - type: str - "open"
        - strategy_name: str - Strategy config name (default: spy_opt_autolearn_v6)
        - user_id: str|None - Specific user, or all users if None
        - skip_sync: bool - Skip holdings sync (default: False)
    """
    start_time = time.time()
    notes = []
    counts = {"processed": 0, "failed": 0, "synced": 0, "skipped": 0}

    # === FAST PATH: skip on non-trading days (weekends + exchange holidays) ===
    # ENTRY path (F-A10-HOLIDAY): an UNREADABLE broker calendar FAILS CLOSED —
    # never generate live entries when the trading-day cannot be confirmed, and
    # NEVER silently fall back to weekday logic. A calendar outage surfaces as
    # typed job truth (counts.errors → runner classifies 'partial'); a
    # successfully-determined holiday/weekend is the ordinary ok:True fast-path.
    try:
        is_trading, market_reason = is_market_day()
    except MarketCalendarUnavailable as e:
        counts["errors"] = 1
        return {"ok": False, "fast_path": True, "blocked": True,
                "reason": f"market_calendar_unavailable: {e}",
                "counts": counts, "timing_ms": (time.time() - start_time) * 1000}
    if not is_trading:
        return {"ok": True, "fast_path": True, "reason": market_reason,
                "counts": counts, "timing_ms": 0}

    strategy_name = payload.get("strategy_name", "spy_opt_autolearn_v6")
    target_user_id = payload.get("user_id")
    skip_sync = payload.get("skip_sync", False)

    try:
        client = get_admin_client()

        # Get target users
        if target_user_id:
            active_users = [target_user_id]
        else:
            active_users = get_active_user_ids(client)

        # === FAST PATH: no active users ===
        if not active_users:
            return {"ok": True, "fast_path": True, "reason": "no_active_users",
                    "counts": counts, "timing_ms": (time.time() - start_time) * 1000}

        # Staleness gate: block suggestion generation if market data is stale
        try:
            from packages.quantum.risk.staleness_gate import check_staleness_gate
            stale = check_staleness_gate()
            if stale.blocked:
                return {
                    "ok": True,
                    "fast_path": True,
                    "reason": f"staleness_gate: {stale.reason}",
                    "age_seconds": stale.age_seconds,
                    "stale_symbols": stale.stale_symbols,
                    "counts": counts,
                    "timing_ms": (time.time() - start_time) * 1000,
                }
        except Exception as sg_err:
            import logging as _lg
            _lg.getLogger(__name__).warning(f"[STALENESS_GATE] Check failed (non-fatal): {sg_err}")

        async def process_users():
            processed = 0
            failed = 0
            synced = 0
            skipped = 0
            cycle_results = []  # Capture budget info per user
            # Research-observer isolation (Lane B): the td + fleet enqueue seams'
            # failures accumulate HERE, never into the live counts.errors channel.
            research_observers = new_research_observers_block()
            research_observer_failures = 0

            for uid in active_users:
                try:
                    source_decision_id = None
                    source_code_sha = None
                    source_as_of = None

                    # 1. Ensure default strategy exists
                    ensure_default_strategy_exists(uid, strategy_name, client)

                    # 3. Load strategy config (for logging/tracing)
                    strategy_config = load_strategy_config(uid, strategy_name, client)
                    notes.append(f"Using strategy {strategy_name} v{strategy_config.get('version', 1)} for {uid[:8]}...")

                    # 4. Run midday cycle (generates entry suggestions)
                    # Wrap with DecisionContext if replay feature store is enabled
                    DecisionContext = _get_decision_context_class()
                    if DecisionContext:
                        as_of_ts = datetime.now(timezone.utc)
                        git_sha = os.getenv("GIT_SHA")
                        ctx = DecisionContext(
                            strategy_name="suggestions_open",
                            as_of_ts=as_of_ts,
                            user_id=uid,
                            git_sha=git_sha,
                        )
                        ctx.__enter__()
                        try:
                            cycle_result = await run_midday_cycle(
                                client, uid, job_run_id=payload.get("_job_run_id")
                            )
                            _commit_res = ctx.commit(client, status="ok")
                            # E16 seam 4 (2026-07-12) + PR-② (2026-07-13):
                            # surface a swallowed capture-commit failure OR a
                            # typed capture_partial (the atomicity gate's
                            # degrade) into the cycle result so it reads as
                            # counts.errors (the F-A4-1 contract), never
                            # silence. The roll-up now carries generic nested
                            # counts.errors to the top level.
                            if isinstance(_commit_res, dict):
                                _cc_err = _commit_res.get("error")
                                _cc_partial = _commit_res.get("tape_integrity") not in (None, "complete")
                                if _cc_err or _cc_partial:
                                    cycle_result = cycle_result or {}
                                    _cc = cycle_result.setdefault("counts", {})
                                    _cc["errors"] = int(_cc.get("errors") or 0) + 1
                                    cycle_result["replay_commit_error"] = (
                                        str(_cc_err)[:300] if _cc_err
                                        else f"tape_integrity={_commit_res.get('tape_integrity')}"
                                    )
                                    notes.append(
                                        f"replay commit degraded for {uid[:8]}: "
                                        f"error={_cc_err} tape_integrity="
                                        f"{_commit_res.get('tape_integrity')}"
                                    )
                                else:
                                    # The independent single-leg child is allowed
                                    # to consume only a complete, durably committed
                                    # parent decision tape.
                                    source_decision_id = str(
                                        _commit_res.get("decision_id") or ctx.decision_id
                                    )
                                    source_code_sha = ctx.git_sha
                                    source_as_of = as_of_ts.isoformat()
                        except Exception as cycle_err:
                            ctx.commit(client, status="failed", error_summary=str(cycle_err)[:500])
                            raise
                        finally:
                            ctx.__exit__(None, None, None)
                    else:
                        cycle_result = await run_midday_cycle(
                            client, uid, job_run_id=payload.get("_job_run_id")
                        )

                    # Policy Lab: fork scored suggestions into cohort variants.
                    # E19-2 Blocker-1 (2026-07-13): the fork returns a typed
                    # result contract; ANY experimental-path failure
                    # (source SELECT / clone lookup / clone INSERT / verdict
                    # UPSERT) arrives as fork_result.errors and MUST reach the
                    # job's counts.errors — the roll-up (#1199) carries it to
                    # the top level and the runner classifies the job partial.
                    # The champion detail stays separate so "champion fine,
                    # experiment broken" reads as exactly that.
                    try:
                        from packages.quantum.policy_lab.config import is_policy_lab_enabled
                        if is_policy_lab_enabled():
                            from packages.quantum.policy_lab.fork import fork_suggestions_for_cohorts
                            fork_result = fork_suggestions_for_cohorts(uid, client)
                            _fork_status = fork_result.get("status")
                            if _fork_status in ("ok", "partial"):
                                notes.append(
                                    f"Policy Lab fork [{_fork_status}]: "
                                    f"{fork_result.get('created', {})}")
                            _fork_errors = int(fork_result.get("errors") or 0)
                            if _fork_errors > 0:
                                cycle_result = cycle_result or {}
                                _fc = cycle_result.setdefault("counts", {})
                                _fc["errors"] = int(_fc.get("errors") or 0) + _fork_errors
                                cycle_result["fork_status"] = _fork_status
                                cycle_result["fork_champion_status"] = (
                                    fork_result.get("champion_status"))
                                cycle_result["fork_champion_tagged"] = int(
                                    fork_result.get("champion_tagged") or 0
                                )
                                cycle_result["fork_error_details"] = (
                                    fork_result.get("error_details") or [])[:5]
                                notes.append(
                                    f"Policy Lab fork DEGRADED for {uid[:8]}: "
                                    f"errors={_fork_errors} "
                                    f"champion={fork_result.get('champion_status')}")
                    except Exception as fork_err:
                        # A fork CRASH is an experimental failure too — typed
                        # into counts.errors, never a notes-only burial.
                        cycle_result = cycle_result or {}
                        _fc = cycle_result.setdefault("counts", {})
                        _fc["errors"] = int(_fc.get("errors") or 0) + 1
                        cycle_result["fork_status"] = "failed"
                        cycle_result["fork_error_details"] = [{
                            "stage": "fork_crashed",
                            "error_class": type(fork_err).__name__,
                            "error": str(fork_err)[:200],
                        }]
                        notes.append(f"Policy Lab fork error: {fork_err}")

                    # Independent one-contract single-leg shadow experiment.
                    # The seam is a no-op while the epoch is absent/disabled or
                    # no approved opt-in binding exists. Only a scheduler-origin
                    # parent with a complete decision tape may enqueue a child;
                    # manual/forced scans cannot manufacture research evidence.
                    try:
                        from packages.quantum.services.single_leg_shadow_scan import (
                            maybe_enqueue_single_leg_shadow_scan,
                        )

                        origin_blob = payload.get("origin")
                        parent_origin = (
                            origin_blob.get("origin")
                            if isinstance(origin_blob, dict)
                            else None
                        )
                        _sl_enq = maybe_enqueue_single_leg_shadow_scan(
                            client,
                            user_id=uid,
                            source_job_run_id=payload.get("_job_run_id"),
                            source_decision_id=source_decision_id,
                            source_code_sha=source_code_sha,
                            as_of=source_as_of,
                            parent_origin=parent_origin,
                        )
                        cycle_result = cycle_result or {}
                        cycle_result["single_leg_shadow_enqueue"] = _sl_enq
                        _sl_errors = int(_sl_enq.get("errors") or 0)
                        if _sl_errors:
                            _slc = cycle_result.setdefault("counts", {})
                            _slc["errors"] = (
                                int(_slc.get("errors") or 0) + _sl_errors
                            )
                            notes.append(
                                f"single-leg shadow enqueue DEGRADED for "
                                f"{uid[:8]}: {_sl_enq.get('status')}"
                            )
                        elif _sl_enq.get("enqueued"):
                            notes.append(
                                f"single-leg shadow child enqueued for "
                                f"{uid[:8]}: {_sl_enq.get('job_run_id')}"
                            )
                    except Exception as sl_err:
                        cycle_result = cycle_result or {}
                        _slc = cycle_result.setdefault("counts", {})
                        _slc["errors"] = int(_slc.get("errors") or 0) + 1
                        cycle_result["single_leg_shadow_enqueue"] = {
                            "status": "enqueue_seam_crashed",
                            "enqueued": False,
                            "errors": 1,
                            "error_class": type(sl_err).__name__,
                            "error": str(sl_err)[:200],
                        }
                        notes.append(f"single-leg shadow enqueue error: {sl_err}")

                    # Regime-V4 parallel shadow comparison (observe-only, default
                    # OFF). Mirrors the single-leg seam: scheduler-origin only,
                    # own try/except, NEVER touches parent counts (note-only —
                    # one failure never makes the parent partial). The bulky
                    # capture rides on cycle_result and is POPPED here so it is
                    # never persisted into job_runs.result (no tape bloat).
                    try:
                        _rv4_capture = (
                            cycle_result.pop("regime_v4_capture", None)
                            if isinstance(cycle_result, dict)
                            else None
                        )
                        if _rv4_capture:
                            from packages.quantum.analytics.regime_v4_shadow_capture import (
                                maybe_enqueue_regime_v4_shadow_compare,
                            )
                            _rv4_origin_blob = payload.get("origin")
                            _rv4_parent_origin = (
                                _rv4_origin_blob.get("origin")
                                if isinstance(_rv4_origin_blob, dict)
                                else None
                            )
                            _rv4_enq = maybe_enqueue_regime_v4_shadow_compare(
                                client,
                                capture=_rv4_capture,
                                user_id=uid,
                                source_job_run_id=payload.get("_job_run_id"),
                                source_decision_id=source_decision_id,
                                source_code_sha=source_code_sha,
                                as_of=source_as_of,
                                parent_origin=_rv4_parent_origin,
                            )
                            if _rv4_enq.get("enqueued"):
                                notes.append(
                                    f"regime-v4 shadow compare enqueued for "
                                    f"{uid[:8]}: {_rv4_enq.get('job_run_id')}"
                                )
                    except Exception as rv4_err:
                        # OBSERVE-ONLY: never fold into counts; note-only.
                        notes.append(
                            f"regime-v4 shadow enqueue error (non-fatal): {rv4_err}"
                        )

                    # ⑤ terminal-distribution score-on-scan observer child
                    # (OBSERVE-ONLY, default OFF). Scores every scan-time
                    # research-candidate envelope (emitted AND rejected) against
                    # the frozen baseline vs the lognormal challenger. Gated on
                    # the flag + a complete scheduler-origin decision tape (whose
                    # decision_id == the cycle_id the capture stamped). A no-op
                    # while the flag is off / no tape exists.
                    #
                    # RESEARCH-OBSERVER ISOLATION (Lane B, 2026-07-23): a readiness/
                    # enqueue failure here is a RESEARCH failure, NOT a live-decision
                    # failure — the scan already produced its live suggestions. It
                    # stays durable (the enqueue dict + the research_observers block),
                    # increments counts.research_observer_failures, and emits a typed
                    # deduped research alert — but it NEVER touches counts.errors, so
                    # the parent status/ok is unchanged and the A4 detector is not
                    # tripped on research noise.
                    try:
                        from packages.quantum.services.td_scan_observe import (
                            maybe_enqueue_td_scan_observe,
                        )

                        origin_blob = payload.get("origin")
                        parent_origin = (
                            origin_blob.get("origin")
                            if isinstance(origin_blob, dict)
                            else None
                        )
                        _td_enq = maybe_enqueue_td_scan_observe(
                            client,
                            user_id=uid,
                            source_job_run_id=payload.get("_job_run_id"),
                            source_decision_id=source_decision_id,
                            source_code_sha=source_code_sha,
                            as_of=source_as_of,
                            parent_origin=parent_origin,
                        )
                    except Exception as td_err:
                        # Redact BEFORE truncating: a broker URL whose '@' falls
                        # past char 200 must not leave a partial credential.
                        _td_enq = {
                            "status": "enqueue_seam_crashed",
                            "enqueued": False,
                            "errors": 1,
                            "error_class": type(td_err).__name__,
                            "error": redact_and_truncate(str(td_err)),
                        }
                        notes.append("td-scan-observe enqueue error (redacted)")
                    cycle_result = cycle_result or {}
                    # Redact any observer-returned error before it becomes durable
                    # in job_runs.result (the enqueue_failed path carries the raw
                    # rq/redis broker-URL error).
                    if isinstance(_td_enq, dict) and _td_enq.get("error"):
                        _td_enq["error"] = redact_and_truncate(_td_enq["error"], 300)
                    cycle_result["td_scan_observe_enqueue"] = _td_enq
                    research_observer_failures += record_observer_seam(
                        client=client,
                        observer_name=OBSERVER_TERMINAL_DISTRIBUTION,
                        enq_result=_td_enq,
                        research_observers=research_observers,
                        source_job_run_id=payload.get("_job_run_id"),
                        source_code_sha=source_code_sha,
                        user_id=uid,
                        notes=notes,
                    )

                    # Recurring independent shadow-fleet policy evaluator (C1).
                    # Sibling of the single-leg seam: a no-op while the fleet is
                    # not `active` (returns fleet_inactive before any write).
                    # Only a scheduler-origin parent with a complete, committed
                    # decision tape may enqueue a child.
                    #
                    # RESEARCH-OBSERVER ISOLATION (Lane B, 2026-07-23): same
                    # contract as the td seam above — a fleet readiness/enqueue
                    # failure is research truth (durable + counts.research_observer_
                    # failures + typed deduped alert), NEVER a live counts.errors
                    # increment, so the parent live scan status/ok is untouched.
                    try:
                        from packages.quantum.services.shadow_fleet_evaluate import (
                            maybe_enqueue_fleet_policy_eval,
                        )

                        origin_blob = payload.get("origin")
                        parent_origin = (
                            origin_blob.get("origin")
                            if isinstance(origin_blob, dict)
                            else None
                        )
                        _fleet_enq = maybe_enqueue_fleet_policy_eval(
                            client,
                            user_id=uid,
                            source_job_run_id=payload.get("_job_run_id"),
                            source_decision_id=source_decision_id,
                            source_code_sha=source_code_sha,
                            as_of=source_as_of,
                            parent_origin=parent_origin,
                        )
                    except Exception as fleet_err:
                        # Redact BEFORE truncating (broker-URL credential safety).
                        _fleet_enq = {
                            "status": "enqueue_seam_crashed",
                            "enqueued": False,
                            "errors": 1,
                            "error_class": type(fleet_err).__name__,
                            "error": redact_and_truncate(str(fleet_err)),
                        }
                        notes.append("fleet policy-eval enqueue error (redacted)")
                    cycle_result = cycle_result or {}
                    # Redact any observer-returned error before durable storage
                    # (the fleet readiness/enqueue error carries the raw broker URL).
                    if isinstance(_fleet_enq, dict) and _fleet_enq.get("error"):
                        _fleet_enq["error"] = redact_and_truncate(
                            _fleet_enq["error"], 300
                        )
                    cycle_result["fleet_policy_eval_enqueue"] = _fleet_enq
                    research_observer_failures += record_observer_seam(
                        client=client,
                        observer_name=OBSERVER_SHADOW_FLEET,
                        enq_result=_fleet_enq,
                        research_observers=research_observers,
                        source_job_run_id=payload.get("_job_run_id"),
                        source_code_sha=source_code_sha,
                        user_id=uid,
                        notes=notes,
                    )
                    # Capture cycle result for observability
                    if cycle_result:
                        cycle_results.append({"user_id": uid[:8], **cycle_result})

                    processed += 1

                except Exception as e:
                    # LOUD (2026-06-12): this except used to swallow a
                    # full midday-cycle death into a notes[] entry while
                    # the job recorded 'succeeded' — the MARA candidate
                    # was selected at 16:00:37Z and vanished with no
                    # alert, no traceback, no suggestion row
                    # (UnboundLocalError out of run_midday_cycle, job
                    # ac2f0c08). A cycle death means NO entry suggestions
                    # for the session: traceback + risk_alert, always.
                    import traceback
                    tb = traceback.format_exc()
                    print(
                        f"[suggestions_open] MIDDAY CYCLE DIED for user "
                        f"{uid[:8]}...: {type(e).__name__}: {e}\n{tb}"
                    )
                    notes.append(f"Failed for user {uid[:8]}...: {str(e)}")
                    failed += 1
                    try:
                        from packages.quantum.observability.alerts import alert
                        alert(
                            client,
                            alert_type="suggestions_open_cycle_died",
                            severity="critical",
                            message=(
                                f"Midday cycle died mid-pipeline: "
                                f"{type(e).__name__}: {str(e)[:300]}"
                            ),
                            user_id=uid,
                            metadata={
                                "function_name": "suggestions_open.run",
                                "error_class": type(e).__name__,
                                "error_message": str(e)[:500],
                                "traceback_tail": tb[-1000:],
                                "consequence": (
                                    "no entry suggestions generated this "
                                    "session for this user; paper_auto_execute "
                                    "will find 0 pending"
                                ),
                            },
                        )
                    except Exception as alert_err:
                        # Alert failure must not mask the original error.
                        print(
                            f"[suggestions_open] cycle-death alert dispatch "
                            f"failed (non-fatal): {alert_err}"
                        )

            return (processed, failed, synced, skipped, cycle_results,
                    research_observers, research_observer_failures)

        (processed, failed, synced, skipped, cycle_results,
         research_observers, research_observer_failures) = run_async(process_users())
        counts["processed"] = processed
        counts["failed"] = failed
        counts["synced"] = synced
        counts["skipped"] = skipped

        # A9-F8 2026-07-07: roll cycle-level persistence failures up to the
        # TOP-LEVEL result. The 18:45Z 2026-07-07 scan read ok:true /
        # counts.failed:0 through 11 failed suggestion_rejections inserts —
        # the failure was buried in cycle_results[].counts where the A4
        # silent-failure detector (which reads counts.errors) cannot see it.
        # A per-user cycle death is an origin-to-top failure too.  Before
        # F-MIDDAY this lived only in counts.failed, which the runner does not
        # classify; include it in the canonical counts.errors channel so a
        # position-read abort is persisted partial rather than green.
        counts["errors"] = _persist_error_rollup(cycle_results)
        counts["errors"] += failed

        # Research-observer isolation (Lane B, 2026-07-23): the td + fleet
        # OBSERVER enqueue failures live in their OWN channel — never in
        # counts.errors — so a research hiccup cannot mark the live scan PARTIAL
        # nor trip the A4 detector (both read counts.errors). This counter is
        # DELIBERATELY not consumed by the runner's _classify_handler_return.
        counts["research_observer_failures"] = int(research_observer_failures or 0)

        timing_ms = (time.time() - start_time) * 1000

        # Ensure all values are JSON-serializable (datetime -> isoformat, etc.)
        return _to_jsonable({
            "ok": failed == 0 and counts["errors"] == 0,
            "counts": counts,
            "timing_ms": timing_ms,
            "strategy_name": strategy_name,
            "notes": notes[:20],  # Limit notes to avoid huge payloads
            "cycle_results": cycle_results[:10],  # Budget/reason info per user
            # Durable per-observer research truth (status/errors/job_run_id),
            # separate from the live-decision result.
            "research_observers": research_observers,
        })

    except ValueError as e:
        raise PermanentJobError(f"Configuration error: {e}")
    except Exception as e:
        raise RetryableJobError(f"Suggestions open job failed: {e}")
