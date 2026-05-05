# RQ Dispatch Audit — 2026-05-04

**Backlog item:** #71 — RQ dispatch migration for synchronous task endpoints
**Author:** PR-1 of N (audit only — no code changes)
**Output:** prioritized migration plan for PR-2 onwards

---

## Executive summary

Audited `packages/quantum/public_tasks.py` (22 endpoints) and
`packages/quantum/internal_tasks.py` (16 endpoints) against the
canonical async dispatch pattern (`enqueue_job_run` + `status_code=202`
+ return `job_run_id` envelope). Findings:

- **30 of 38 endpoints already async** (15 in each file). Pattern is
  well-established and consistent.
- **8 endpoints run synchronously**: 7 in `public_tasks.py`, 1 in
  `internal_tasks.py`.
- **Of the 8 sync endpoints, 5 are migration candidates** (work belongs
  in a queued job; current sync execution is the gap #71 was opened to
  close).
- **3 are intentionally synchronous** by design — debug/operator
  tools or read-only computations whose docstrings explicitly justify
  inline execution. Excluded from migration.
- **The headline candidate is `/tasks/policy-lab/eval`**: APScheduler
  fires this endpoint daily at 16:30 CT, the work runs inline against
  the request thread, and the corresponding job handler
  (`packages/quantum/jobs/handlers/policy_lab_eval.py`) already exists
  and is fully wired. Lowest-risk, highest-value migration.
- **Total migration scope: 5 endpoints → 3-5 PRs** depending on
  bundling strategy. PR-2 should ship #1 (policy-lab/eval) standalone
  to validate the pattern, then PR-3 onwards bundles by complexity tier.

---

## STEP 1 — Canonical async pattern

`enqueue_job_run` is defined at `packages/quantum/public_tasks.py:165`.
Signature: `(job_name, idempotency_key, payload, queue_name="otc",
force_rerun=False) -> dict`. Returns `{job_run_id, job_name,
idempotency_key, rq_job_id, status}`.

Canonical handler shape (example: `/tasks/morning-brief` at line 356):

```python
@router.post("/morning-brief", status_code=202)
@limiter.limit("20/minute")
async def task_morning_brief(
    request: Request,
    payload: MorningBriefPayload = Body(default_factory=MorningBriefPayload),
    auth: TaskSignatureResult = Depends(verify_task_signature("tasks:morning_brief"))
):
    today = datetime.now().strftime("%Y-%m-%d")
    return enqueue_job_run(
        job_name="morning_brief",
        idempotency_key=today,
        payload={"date": today},
        force_rerun=payload.force_rerun,
    )
```

A handler is "async pattern" if it:
- Uses `status_code=202` (Accepted) — semantic match for queued work.
- Returns `enqueue_job_run(...)` without inspecting the result.
- Body is small (just builds payload + idempotency_key).

A handler is "sync" if it:
- Uses `status_code=200` (OK).
- Calls business logic inline against the request thread.
- Returns the actual computed result, not a `job_run_id`.

`enqueue_job_run` itself does the right things on the gating side:
checks pause gate (creates auditable `cancelled` row instead of raising),
applies go-live gate for live-exec jobs, and uses `JobRunStore.create_or_get_cancelled` for idempotency. Migrations
inherit those guarantees automatically.

---

## STEP 2 — Endpoint inventory

### `public_tasks.py` — 22 endpoints

**Async (15):**

| Endpoint | Status | Idempotency key | Notes |
|----------|:------:|-----------------|-------|
| /universe/sync | 202 | date | scheduler-fired |
| /morning-brief | 202 | date | scheduler-fired |
| /midday-scan | 202 | date | scheduler-fired |
| /weekly-report | 202 | week | scheduler-fired |
| /validation/eval | 202 | mode+user+cadence | |
| /suggestions/close | 202 | date | scheduler-fired |
| /suggestions/open | 202 | date | scheduler-fired |
| /learning/ingest | 202 | date | scheduler-fired |
| /paper/learning-ingest | 202 | date | scheduler-fired |
| /strategy/autotune | 202 | date | |
| /ops/health_check | 202 | minute-bucketed | scheduler-fired (every 30 min) |
| /paper/auto-execute | 202 | autopilot key | scheduler-fired |
| /paper/auto-close | 202 | autopilot key | scheduler-fired |
| /paper/exit-evaluate | 202 | date+window | scheduler-fired |
| /paper/mark-to-market | 202 | date | scheduler-fired |

**Sync (7):**

| Endpoint | Line | Body shape |
|----------|-----:|------------|
| /policy-lab/eval | 608 | calls `evaluate_cohorts` + `check_promotion` inline; returns combined dict |
| /paper/process-orders | 996 | calls `_process_orders_for_user` inline; **explicitly sync** per docstring |
| /validation/shadow-eval | 1165 | calls `eval_paper_forward_checkpoint_shadow` inline; **explicitly sync** ("fast and side-effect free") |
| /validation/autopromote-cohort | 1304 | reads `shadow_cohort_daily`, evaluates 3-day promotion criteria, may write go-live state |
| /validation/preflight | 1537 | calls `compute_forward_checkpoint_snapshot`; **explicitly read-only** per docstring |
| /validation/init-window | 1594 | calls `ensure_forward_window_initialized`; docstring says "Idempotent once per day (UTC bucket)" |
| /validation/cohort-eval | 1742 | iterates N cohort configs, calls shadow eval per cohort, persists winner to `shadow_cohort_daily` |

### `internal_tasks.py` — 16 endpoints

**Async (15):** /morning-brief, /midday-scan, /weekly-report, /universe/sync,
/alpaca/order-sync, /risk/intraday-monitor, /learning/post-trade,
/orchestrator/start-day, /progression/daily-eval, /calibration/update,
/promotion/check, /heartbeat, /phase2-precheck, /autotune/walk-forward,
/iv/daily-refresh — all use `enqueue_job_run(...)` with `status_code=202`.

**Sync (1):**

| Endpoint | Line | Body shape |
|----------|-----:|------------|
| /train-learning-v3 | 369 | iterates `active_users`, calls `CalibrationService.train_and_persist` + `ConvictionService` inline per user; emits analytics events |

---

## STEP 3 — Caller surface

The scheduler (`packages/quantum/scheduler.py:45-89`) is the **primary
internal caller** of task endpoints. Of the 8 sync endpoints, only ONE
is fired by the scheduler:

| Sync endpoint | Scheduled? | Other repo callers | GHA workflows | Frontend |
|---------------|:---------:|--------------------|----------------|----------|
| /policy-lab/eval | **YES** (16:30 CT daily) | none | none | none |
| /paper/process-orders | no | none | none | none |
| /validation/shadow-eval | no | none | none | none |
| /validation/autopromote-cohort | no | none | none | none |
| /validation/preflight | no | none | none | none |
| /validation/init-window | no | none | none | none |
| /validation/cohort-eval | no | none | none | none |
| /train-learning-v3 | no | none | none | none |

GHA workflows checked: `.github/workflows/{ci-tests,security_v4_smoketest,trading_tasks}.yml` —
zero references to any of the sync endpoints. Frontend grep across
`apps/web/` returns zero references. This is consistent with the
existing observability gap framing — these endpoints are operator-on-
demand or scheduler-fired, not user-facing.

The scheduler caller is `_fire_task` at `scheduler.py:92`, which
POSTs the signed task envelope and discards the response body. Its
caller doesn't depend on the inline sync result, so migrating
`/policy-lab/eval` to async is non-breaking — `_fire_task` will receive
the standard `{job_run_id, status: "queued"}` envelope and proceed
the same way.

---

## STEP 4 — Idempotency review

| Endpoint | Side effects | Idempotency status |
|----------|--------------|---------------------|
| /policy-lab/eval | writes `policy_daily_scores`, `go_live_progression`, `risk_alerts` on failure | **Idempotent** — handler upserts by `(user_id, eval_date)`; multiple calls produce same final state |
| /paper/process-orders | mutates `paper_orders` per stuck row | Conditional (per-row state) — but EXCLUDED from migration |
| /validation/shadow-eval | none (side-effect free per docstring) | N/A — EXCLUDED from migration |
| /validation/autopromote-cohort | reads history, may write `go_live_progression` cohort state | **Conditional idempotency** — generates `idempotency_key` but doesn't enforce via DB; re-promote on second call would be no-op only because state won't move backwards. Needs DB-enforced idempotency before queuing safely |
| /validation/preflight | none (read-only per docstring) | N/A — EXCLUDED |
| /validation/init-window | upserts `paper_window_start`/`paper_window_end` on `go_live_progression` | **Idempotent** — docstring confirms ("Idempotent once per day"); upsert pattern |
| /validation/cohort-eval | writes per-cohort to `shadow_cohort_daily` per call | **Conditional** — believed upsert-shaped but unverified; per-cohort runs independently; needs verification before queuing |
| /train-learning-v3 | writes calibration data (upsert), conviction data (upsert), analytics events (NOT idempotent) | **NOT idempotent at event layer** — duplicate analytics events on retry. Calibration/conviction writes are upsert and safe |

**Idempotency-blocked endpoints** (need redesign before migration):
- `/validation/autopromote-cohort` — needs DB-enforced idempotency key (e.g.,
  unique constraint on `(user_id, bucket_date, alert_type='autopromote_attempt')`)
- `/train-learning-v3` — needs analytics-event dedup OR sub-decomposition into per-user jobs

**Idempotency-clean** (safe to queue today): `/policy-lab/eval`,
`/validation/init-window`. `/validation/cohort-eval` is probably fine
but verify the upsert shape on `shadow_cohort_daily` before PR.

---

## STEP 5 — Recommended migration order

### Tier 1 — Ship in PR-2 (validates pattern)

**1. `/tasks/policy-lab/eval`** [LOW risk, HIGH value]

- **Rationale:** the original CLAUDE.md "documented blind spot" case.
  Scheduler fires it daily at 16:30 CT; failures currently produce no
  `job_runs` trace. Handler at
  `packages/quantum/jobs/handlers/policy_lab_eval.py` already exists,
  is registered with `JOB_NAME = "policy_lab_eval"`, and even includes
  `compute_decision_accuracy` (which the inline endpoint silently
  drops). Migration is a 1-hour endpoint body swap.
- **Idempotency:** handler is upsert-shaped against
  `policy_daily_scores`; safe to queue.
- **Caller impact:** zero — `_fire_task` discards response body.
- **Effort:** ~1 hour (endpoint body swap + 1 test update).
- **Blockers:** none.
- **Verifiable post-deploy:** next 16:30 CT scheduler fire produces a
  `job_runs` row for `policy_lab_eval`; pre-PR there is none.

### Tier 2 — Ship in PR-3

**2. `/tasks/validation/init-window`** [LOW risk, LOW-MEDIUM value]

- **Rationale:** docstring confirms idempotency; operator-on-demand
  with no known callers. Easy second migration to validate the pattern
  reproduces.
- **Idempotency:** explicit per docstring.
- **Caller impact:** zero.
- **Effort:** ~1.5 hours. **Blocker:** handler doesn't exist —
  needs `packages/quantum/jobs/handlers/validation_init_window.py`
  scaffolded (~30 min: thin wrapper around
  `service.ensure_forward_window_initialized`).

### Tier 3 — Ship in PR-4 (after idempotency hardening)

**3. `/tasks/validation/cohort-eval`** [MEDIUM risk, MEDIUM value]

- **Rationale:** writes per-cohort to `shadow_cohort_daily`; verify the
  upsert shape before queuing. Once verified, migration follows the
  same pattern as Tier 1/2.
- **Effort:** ~2 hours including the schema/upsert verification.
- **Blocker:** new handler + idempotency verification.

**4. `/tasks/validation/autopromote-cohort`** [MEDIUM risk, MEDIUM value]

- **Rationale:** writes go-live state; current `idempotency_key`
  generation isn't DB-enforced. Two-step migration: PR-X ships DB
  uniqueness constraint, PR-X+1 wires the endpoint to async.
- **Effort:** ~3 hours total across 2 PRs.
- **Blocker:** idempotency redesign is its own PR.

### Tier 4 — Largest scope, ship last

**5. `/internal/tasks/train-learning-v3`** [HIGH risk, MEDIUM value]

- **Rationale:** heavy iteration over all active users; analytics
  events are NOT idempotent at the event layer — naive retry produces
  duplicate `learning_train_started` / `learning_train_completed`
  events.
- **Recommended decomposition:** split into per-user job dispatch:
  endpoint enqueues N `learning_train_user` jobs, each handles one
  user atomically with its own idempotency key. Avoids the
  duplicate-event problem and aligns with the per-user pattern used
  elsewhere.
- **Effort:** ~4 hours including decomposition.
- **Blocker:** decomposition design + handler scaffolding.

### Defer (NOT migration candidates)

These are intentional sync endpoints. Excluded with reasoning:

- **`/paper/process-orders`** — docstring explicitly: "Unlike auto-
  execute/auto-close, this does NOT enqueue a background job — it
  runs synchronously for immediate feedback. Use cases: Manual re-
  processing of stuck staged orders, debugging order fill simulation,
  observability into paper order lifecycle." Operator debug tool;
  inline response is the value.
- **`/validation/shadow-eval`** — code comment: "Shadow eval is fast
  and side-effect free, so we can run it inline." Lightweight
  computation; queueing would add latency without value.
- **`/validation/preflight`** — docstring: "Read-only (no state
  mutation)." Returns a computed snapshot; immediate response is the
  value.

---

## STEP 6 — Open questions for operator

1. **Bundling strategy.** Tier 1 should ship standalone in PR-2 to
   validate the pattern. Subsequent tiers could bundle by complexity
   (e.g., PR-3 = Tier 2 + Tier 3 if both are quick; PR-4 = Tier 4
   alone). Operator preference?
2. **Tier 3 (`/validation/cohort-eval`) and Tier 4 (`autopromote`)**
   are both currently un-scheduled, operator-on-demand tools. Is
   migrating them ahead of putting them on a schedule the right
   sequencing? Alternative: ship Tier 1 + Tier 2 only, defer Tier 3+
   until they have a scheduled caller that would benefit.
3. **Tier 4 decomposition.** The recommended per-user split changes
   the endpoint's call shape (returns N job_run_ids instead of one
   aggregate). If `/train-learning-v3` has external operator scripts
   calling it (not visible to repo grep), they need to handle the
   shape change. Operator confirmation needed before proceeding.

---

## STEP 7 — Out-of-scope items (explicit)

- ANY code changes to handlers, the runner, or the queue
  infrastructure. This is read-only PR.
- Migrating any endpoint. PR-2 onwards does that.
- Refactoring `enqueue_job_run` itself or RQ configuration.
- Idempotency redesigns of the non-idempotent handlers — flagged
  here, but those are separate PRs per affected endpoint.

---

## Summary table

| Tier | Endpoint | Risk | Value | Effort | PR | Blocker |
|:----:|----------|:----:|:-----:|:------:|:---|---------|
| 1 | /policy-lab/eval | LOW | HIGH | ~1h | PR-2 | none |
| 2 | /validation/init-window | LOW | LOW-MED | ~1.5h | PR-3 | new handler |
| 3 | /validation/cohort-eval | MED | MED | ~2h | PR-4 | new handler + upsert verification |
| 4a | autopromote idempotency redesign | MED | MED | ~1.5h | PR-5 | DB constraint |
| 4b | /validation/autopromote-cohort | MED | MED | ~1h | PR-6 | depends on 4a |
| 5 | /train-learning-v3 | HIGH | MED | ~4h | PR-7 | per-user decomposition |

Total scope: 5 endpoint migrations + 1 idempotency redesign across 6 PRs.

The ordering is conservative — if Tier 2/3 prove low-friction in
practice, they can bundle into one PR. Tier 4 and Tier 5 should stay
standalone given their idempotency / decomposition concerns.
