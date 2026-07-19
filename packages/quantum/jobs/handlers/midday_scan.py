import time
from typing import Any, Dict
from packages.quantum.services.workflow_orchestrator import run_midday_cycle
from packages.quantum.services import risk_basis_shadow as rbs
from packages.quantum.jobs.handlers.utils import get_admin_client, get_active_user_ids, run_async
from packages.quantum.jobs.handlers.exceptions import RetryableJobError, PermanentJobError

JOB_NAME = "midday_scan"

# RQ calls run(payload); ctx must be optional.
def run(payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
    start_time = time.time()
    notes = []
    counts = {"processed": 0, "failed": 0, "errors": 0, "suggestion_insert_failures": 0}

    try:
        client = get_admin_client()
        active_users = get_active_user_ids(client)

        async def process_users():
            processed = 0
            failed = 0
            insert_failures = 0
            # F-A4-RISKBASIS-SILENT (2026-07-19): per-user arm-evidence scope so
            # the RiskBudgetEngine.compute open-book comparison seam records
            # durable P0-B arm evidence; drained in a finally so a cycle that
            # RAISES (a read failure at its deepest callee) captures whatever
            # accrued BEFORE the raise — never a fabricated flat book.
            arm_rows = []
            arm_errors = []
            for uid in active_users:
                _arm = None
                try:
                    with rbs.arm_evidence_scope(cycle_id=f"midday_scan:{uid}") as _arm:
                        cycle_result = await run_midday_cycle(client, uid)
                    processed += 1
                    # #1218 job-truth (2026-07-16): run_midday_cycle catches
                    # per-suggestion insert failures internally (it fires the
                    # aggregated alert and returns normally), so a RAISED
                    # exception is NOT the only way a cycle can lose work. A
                    # suggestion that exhausted the strip/retry — e.g. a
                    # required column missing from the schema (the ranking_costs
                    # PGRST204) — is a lost row and must make the run non-green.
                    cyc_counts = (cycle_result or {}).get("counts") or {}
                    insert_failures += int(cyc_counts.get("suggestion_insert_failures") or 0)
                except Exception as e:
                    notes.append(f"Failed for user {uid}: {str(e)}")
                    failed += 1
                finally:
                    if _arm is not None:
                        arm_rows.extend(_arm.rows)
                        arm_errors.extend(_arm.errors)
            return processed, failed, insert_failures, arm_rows, arm_errors

        processed, failed, insert_failures, arm_rows, arm_errors = run_async(process_users())
        counts["processed"] = processed
        counts["failed"] = failed
        counts["suggestion_insert_failures"] = insert_failures
        # The public/manual midday route shares run_midday_cycle with the
        # scheduled handler.  Preserve the same non-green truth contract:
        # a RAISED user failure OR an exhausted per-suggestion insert failure
        # (a lost suggestion) makes the run non-green, so the runner classifier
        # and the A4 job-truth detector see counts.errors>0 -> 'partial'.
        counts["errors"] = failed + insert_failures

        timing_ms = (time.time() - start_time) * 1000
        result = {
            "ok": counts["errors"] == 0,
            "counts": counts,
            "timing_ms": timing_ms,
            "notes": notes
        }
        # Drain the durable arm evidence into cycle_metadata (no migration); a
        # persist fault folds to counts.errors -> 'partial' (never silent).
        result = rbs.persist_arm_evidence(
            result, arm_rows, arm_errors, cycle_id="midday_scan"
        )
        result["ok"] = int(result["counts"].get("errors") or 0) == 0
        return result

    except ValueError as e:
        raise PermanentJobError(f"Configuration error: {e}")
    except Exception as e:
        raise RetryableJobError(f"Midday scan job failed: {e}")
