# Loud-Error Doctrine v1.0

**Created:** 2026-04-27
**Backlog item:** #72
**Audit catalog:** see CLAUDE.md `### #72 — Loud-error doctrine + silent-failure catalog`
**Status:** Ratified

---

## Principle

Every production exception must do exactly one of three things:

1. **Re-raise** — let the caller decide what to do.
2. **Write a `risk_alert`** with `severity ≥ 'info'` capturing what failed,
   then return / fall through.
3. **Fail loudly to a structured log handler** that itself produces
   `risk_alerts` (e.g., a shared `notes_to_risk_alerts` helper).

The forbidden state is **silent failure**: `try / except / pass`, or
`try / except / log.warning(...) / return default`, with no
`risk_alerts` write. These patterns hide bugs and corrupt downstream
data because the system continues "as if everything was fine" while a
required input is missing.

## Why this doctrine exists

Six independent silent-failure incidents, all surfaced in the seven
days of 2026-04-19 → 2026-04-26:

1. **`ALPACA_PAPER` vs `ALPACA_PAPER_TRADE` env mismatch** (Sat
   2026-04-25). Two layers read different env vars; one was set, the
   other was not. The mismatch was a configuration drift hidden behind
   an `if not key: return` early-exit. Cost: an entire Saturday of
   diagnostic time.
2. **Polygon `@guardrail` decorator pattern.** Returns `None` on
   retry-exhaustion. Saturday 2026-04-25's `update_metrics` 429s left
   zero database trace. Cost: incident reconstructed by reading
   Railway logs hours later.
3. **`policy_lab_eval` ImportError + scheduler swallow.** Job
   scheduled to fire at 16:30 CT, didn't fire for 7 days. Scheduler
   logged a warning per day; no `risk_alerts` row. Cost: 7 days of
   missing cohort scoring data.
4. **`evaluator.py:151-153` per-cohort exception swallow.** Per-cohort
   work in a loop; one cohort's failure silently dropped that cohort
   from the day's evaluation. Fixed via PR #807 / commit `1649f1a` —
   the first concrete instance of the doctrine being applied.
5. **`outcome_aggregator.py` silent-`None` pattern.** 5 `try/except:
   pass` blocks. Was thought to corrupt the calibration loop; turned
   out the entire path was dead code (zero rows in `outcomes_log`
   ever). Cost: investigation time pursuing the wrong hypothesis.
6. **`nested_regimes` `log_global_context` bare `try/except`.** Wrote
   to a non-existent column AND missed a required column AND swallowed
   the result. Zero rows ever in `nested_regimes`. Cost: a phantom
   "broken regime persistence" item in the backlog. Resolved by
   deleting the writer in PR #813.

The pattern across all six: **the bug existed long before discovery,
and the discovery was incidental** (Saturday 429 incident, manual
audit, etc.) — not because monitoring caught it. Loud errors invert
that. A `risk_alert` row makes "should I look into this?" a one-query
question instead of an archaeology project.

## How to apply

Decision tree for new code OR for code-review on existing PRs:

```
Is this exception expected and handled correctly?
  Yes (input validation, expected-empty-result, etc.) → re-raise
       OR return correctly-typed value, no alert needed.
  No → continue.

Is this exception transient and retried?
  Yes → alert ONLY on final failure after retries, not each attempt.
        Use a counter or batch alert if attempts are frequent.
  No → continue.

Is the data path consumed by anyone?
  Yes (active consumer reads the result) → MUST write risk_alert
       before returning default. Default value should be the
       "safest possible" (skip envelope rather than fabricate).
  No (dead code, orphan write) → DO NOT add observability. Mark for
       deletion via #67 / #75 / dead-code sweep instead.

Is this in a tight loop (>10 iterations expected)?
  Yes → aggregate alerts. Write one summary row at end of loop:
        e.g. "10 polygon failures in this batch" with metadata
        listing affected symbols.
  No → write alert per occurrence.

Did the alert-write itself fail?
  Yes → fall back to logger.exception with structured fields.
        Do NOT recurse. The outer `except: pass` around the alert
        insert is acceptable (see Valid 5 below) precisely because
        we've exhausted reasonable observability options.
  No → continue.
```

Severity guide:
- `info` — expected-but-noteworthy events ("envelope skipped because
  Alpaca unreachable; using cached equity").
- `warning` — unexpected events that don't block ("Polygon retry
  exhausted; using stale snapshot").
- `critical` — data corruption or live-trade-affecting issues
  (force-close failed, position state inconsistent with broker).

## Anti-patterns

### Anti-pattern 1 — Bare `try/except: pass`

❌ **Broken:**
```python
try:
    supabase.table("nested_regimes").insert(data).execute()
except Exception as e:
    print(f"L2 Backbone: Failed to log context: {e}")
```
What goes wrong: Schema drift (column doesn't exist), connection
failure, JSON-encoding bug — all indistinguishable. `print` to stdout
in a Railway container is technically logged but not surfaced.

✅ **Corrected (when path is live):**
```python
try:
    supabase.table("nested_regimes").insert(data).execute()
except Exception as e:
    logger.exception("nested_regimes insert failed")
    alert(
        supabase,
        alert_type="regime_persistence_failed",
        severity="warning",
        message=str(e),
        metadata={"data": data, "error_class": type(e).__name__},
    )
```

✅ **Corrected (when path is dead):** delete the writer. Don't add
observability to dead code; that perpetuates the orphan.

Migration complexity: low (~5-10 min per site once `alert()` helper
exists).

### Anti-pattern 2 — Log-only swallow with default return

❌ **Broken:**
```python
@guardrail(provider="polygon", fallback=None)
def _get_historical_prices_api(self, symbol, days, to_date, ...):
    # ... HTTP call ...
```
The `@guardrail` decorator catches all exceptions and returns
`fallback`. Caller cannot distinguish "Polygon returned no data" from
"Polygon was unreachable for 90s and we gave up."

✅ **Corrected:** the decorator should write a `risk_alert` row when
the fallback is used after retry exhaustion, with metadata including
provider, retry count, last exception class. Caller still gets the
typed-empty result but the failure is now queryable.

Migration complexity: medium (~half day for the decorator + audit
the 8 callers in `market_data.py`).

### Anti-pattern 3 — Synchronous endpoint without enqueue

❌ **Broken:**
```python
@router.post("/tasks/policy-lab/eval")
def policy_lab_eval(...):
    # do work synchronously, return 200
```
A scheduler dispatch can fail at the HTTP boundary (4xx/5xx, network
timeout). The scheduler's `_fire_task` logs the error but does NOT
write `risk_alerts` or update `job_runs`. The job appears to have
"never fired" rather than "fired and failed."

✅ **Corrected:** every scheduled task endpoint creates a `job_runs`
row at entry; on failure, marks it `failed_retryable` or
`dead_lettered` AND writes a `risk_alerts` row. Scheduler-side
HTTP error handling does the same.

Migration complexity: medium (#71 RQ dispatch audit covers this
domain; coordinate scope).

### Anti-pattern 4 — Per-iteration swallow in tight loops

❌ **Broken:**
```python
for cohort in cohorts:
    try:
        evaluate(cohort)
    except Exception as e:
        logger.warning(f"Cohort {cohort.name} failed: {e}")
```
One bad cohort silently disappears from the eval. If 2/3 cohorts fail,
the daily summary looks like "1 cohort succeeded" instead of "1
cohort succeeded + 2 cohorts had errors."

✅ **Corrected (PR #807 / commit `1649f1a` applied this):**
```python
for cohort in cohorts:
    try:
        evaluate(cohort)
    except Exception as e:
        logger.exception(f"Cohort {cohort.name} failed")
        alert(
            supabase,
            alert_type="policy_lab_eval_cohort_failure",
            severity="warning",
            message=f"Cohort {cohort.name} eval failed",
            metadata={"cohort_name": cohort.name, "error": str(e)},
        )
```

Migration complexity: low (~10-15 min per loop).

### Anti-pattern 5 — Env-var branch without observability

❌ **Broken:**
```python
if os.environ.get("SOMETHING_ENABLED") == "1":
    do_the_thing()
# else: silently do nothing
```
The "else" branch is unobservable. Operator who expected
`do_the_thing()` to run sees nothing happen and no error.

✅ **Corrected:** at startup or first-execution, log the resolved
flag state; at the branch, if `else` is taken when the operator might
expect otherwise, write an `info`-severity `risk_alert` describing
the gating.

Migration complexity: low; mostly applies to feature-flag branches
in `paper_autopilot_service`, `policy_lab/config.py`, etc.

### Anti-pattern 6 — Scheduler-side swallow

❌ **Broken** (`scheduler.py:_fire_task`):
```python
try:
    resp = httpx.post(url, ...)
    if resp.status_code >= 400:
        logger.error(f"{job_id} returned {resp.status_code}")
        return
    # ...
except Exception as e:
    logger.error(f"{job_id} failed: {e}")
```
Both the 4xx/5xx branch AND the exception branch only log. The job
silently "didn't run" from the operator's POV.

✅ **Corrected:** the scheduler should mark the corresponding
`job_runs` row `failed_retryable` AND write a `risk_alerts` row
including the response body / exception class. The operator's
"why didn't this fire?" question becomes a one-query lookup.

Migration complexity: medium (~2 hours).

### Anti-pattern 7 — Alerts at exception-raising sites don't catch dict-return failure markers

The H5a/H5b sweep added critical alerts at sites that raise
exceptions on failure. Production failure modes can also include
functions that swallow exceptions into dict-return failure
markers (e.g., `submit_and_track` returns
`{"status": "needs_manual_review"}` instead of raising).

Both modes need observability. A try/except above a function
call is no guarantee the called function will raise.

**Pattern:** when auditing for silent-failure sites, distinguish
between exception-raising and return-value-marking paths.
Coverage requires alerts on BOTH:
- At the call site (catches raised exceptions)
- At the write site of the failure marker (catches dict-return
  failures, regardless of who calls the function)

**Origin:** 2026-05-01 BAC ghost position incident. PR #853
addresses by alerting at the marker write site, catching all
callers regardless of how they handle the return.

**Implementation precedent:** see PR #853, `alpaca_order_handler.py`
needs_manual_review write site alert.

Migration complexity: small (~1-2 hours per site once the
write-site pattern is identified).

### Anti-pattern 8 — Intermediate wrapper drops fields the caller depends on

When a service-layer fix introduces a dependency on a NEW field from
an upstream provider, that field must traverse every intermediate
wrapper between provider and consumer. A whitelist-style wrapper that
hand-builds its return dict will silently drop fields the caller now
needs — no exception, no log, just `None` flowing through. The
consumer's safest-default branch then takes over and the fix appears
to ship without taking effect.

Each layer in isolation looks correct: the upstream API returns the
field, the new helper coerces it correctly, the consumer falls back
gracefully when the field is absent. The defect is in the seam
between layers.

**Example:** PR #849 (#93 broker-truth fix) moved
`cash_service.get_deployable_capital` to read Alpaca
`options_buying_power` directly via a new helper. The helper called
`AlpacaClient.get_account()` which had a hand-built return dict
listing equity, buying_power, etc. — but NOT
`options_buying_power`. The helper always read `None` and the
consumer fell back to the stale `paper_baseline_capital` for 5 days.
Surfaced 2026-05-04 by manual diagnostic, not by alert.

**Pattern:** any time a fix introduces a NEW field dependency on an
upstream provider, audit the WHOLE chain end-to-end. Whitelist-style
wrappers (hand-built return dicts) are the high-risk shape. Forwarding
wrappers (return the upstream object directly) don't have this
failure mode but lose type-narrowing and explicit-contract benefits.

**Detection:**
- Integration tests that exercise the new field through the real
  wrapper chain catch this at PR time.
- Source-level guards that assert the wrapper exposes the field
  catch regressions. Precedent:
  `test_alpaca_client_get_account_wrapper.py` shipped in PR #864.
- Defense-in-depth: alert at the consumer's fallback site so future
  drops surface within one cycle. Precedent: PR #865.

**Origin:** 2026-05-04 OBP-divergence diagnostic. Fixed by PR #864
(field added to wrapper) + PR #865 (alert at cash_service fallback).

Migration complexity: small (~30 min per wrapper to identify caller
fields). Audit pattern: grep callers of the wrapper, list fields
they read, diff against the wrapper's whitelist.

### Anti-pattern 9 — Syntactic-only verification of dead code paths

Code that has never executed in production cannot be verified for
correctness by reading it. Static inspection confirms syntax, type
signatures, import resolution, and call shape — but a method call
that's syntactically valid against an imported class is still wrong
if the method doesn't exist on the class. Only runtime exercise
surfaces this class of bug.

**Worked example (2026-05-05):** `/internal/tasks/train-learning-v3`
(deleted in PR #880) called `CalibrationService.train_and_persist`.
The endpoint imported `CalibrationService`, the call shape was
valid Python, code-level review would have passed. The method
didn't exist on the class — first execution would have raised
`AttributeError`. The bug was invisible because the endpoint had
zero production runs.

**Pattern:** Before refactoring or migrating dead code, confirm it
actually works at runtime — even briefly. The migration cost of
preserving dead-but-broken code is wasted; deletion is usually
correct.

**Audit implications:** "Does this endpoint exist and have valid
call shape?" is necessary but not sufficient. "Has this endpoint
ever fired in production?" must also be answered before scope
decisions (migrate vs delete vs rewrite) are made. The #71 sweep
(2026-05-04 to 2026-05-05) demonstrated this concretely — three
of the seven planned endpoint migrations became deletions once
production-exercise verification was added at the diagnostic
stage. Audit catalogued endpoints that EXISTED but didn't catalogue
endpoints that FIRED. For #71, those were different sets, and
the difference materially changed scope (3 PRs of migration work
avoided).

**Detection at audit time:**

```sql
-- For each endpoint candidate, check production-exercise count:
SELECT job_name, COUNT(*) AS runs, MAX(started_at)
FROM job_runs
WHERE job_name = '<candidate>'
GROUP BY job_name;

-- If endpoint doesn't use enqueue_job_run yet (sync endpoint),
-- check side-effect tables instead — analytics_events, the
-- target table the endpoint writes to, etc.
SELECT COUNT(*), MAX(created_at)
FROM <table_endpoint_writes_to>
WHERE <evidence_columns> AND created_at > NOW() - INTERVAL '90 days';
```

Zero production exercise + operator-on-demand only + no scheduler
caller = strong deletion candidate, regardless of how clean the
code reads.

**Origin:** 2026-05-05 #71 sweep closure. PR-4 (PR #879) and PR-5
(PR #880) both surfaced the same shape — endpoints that looked
ready to migrate were actually never-fired dead code, with PR-5
additionally surfacing a broken method reference that syntactic
inspection wouldn't have caught.

Migration complexity: zero — this is an audit-input recommendation,
not a code change. Adding the production-exercise check to future
audit prompts is a one-line addition to whatever diagnostic
template the audit uses.

## Higher-order coverage doctrines

The anti-patterns above target specific code-shape mistakes. The
doctrines in this section sit one level up — they describe
verification disciplines and cross-cutting invariants that
prevent whole classes of silent failures from shipping in the
first place.

### Verify code path exercised in production before shipping safety logic for it

Three instances surfaced in 2026-04-29 to 2026-05-01 session:

1. **D4-PR3 (PR #844)** corrected a clone-builder symbol-field
   bug in code that never executed in production (zero shadow
   cohort clones in entire DB history)

2. **PR2a/PR2b (PRs #842/#843)** shipped routing gates and
   fill paths for cohort clones that never existed

3. **D4 sequence framing as "30-day broken cohort fan-out"**
   was based on the assumption that cohort comparison data
   existed historically. DB query showed zero clones EVER.

**Pattern:** before shipping safety/observability logic for a
code path, verify the code path is exercised in production via:
- DB query for the data the code path produces/consumes
- Log evidence the path executes
- Audit table entries showing function invocation

**The cost of skipping verification:** safety logic that's
architecturally correct but operationally inert. Code looks
right in tests, ships clean, never fires.

**The verification step is cheap.** A simple `SELECT COUNT(*)
FROM <table> WHERE <conditions>` query at the start of design
is all that's needed.

**Origin:** 2026-05-01 cohort fan-out diagnostic. Surfaced
that #95 fork.py threshold semantic mismatch was the upstream
cause that made D4 sequence inert.

### Operations preserve capital invariants in both directions

When a system models capital as a single number (e.g.,
`account_buying_power`, `deployable_capital`), verify that
operations preserve the invariant in BOTH directions of the
transaction.

Half the BP problems come from forgetting the close requires
capital too. The entry-side check is the obvious one; the
exit-side check is the often-missed one.

**Patterns to look for:**
- Sizing: does it check entry_cost AND close_cost ≤
  available_capital?
- Lifecycle: does each state transition preserve total capital
  conservation?
- Multi-leg: does the close-side margin recompute match the
  entry-side reservation?
- Async: do partial fills preserve invariants between fill
  events?

**Specific application:** Option A (#100) implements this for
sizing logic. Sizing now checks
`entry_cost + close_cost × safety_factor ≤ available_OBP`, not
just `entry_cost ≤ available_OBP`.

**Origin:** 2026-05-01 BP-to-close architectural diagnostic.
BAC stuck-close revealed sizing's one-direction check.

### Persistent worker deploys ≠ code restart

Long-running workers (RQ, APScheduler) on Railway do NOT auto-reload
on code deploy. The deploy ships a new image to the service slot,
but the existing worker process keeps executing the prior image's
code until it is explicitly restarted. A PR that ships, gets a green
deploy, and runs in CI is NOT the same as that PR's code being
executed by the production worker.

The diagnostic shape is distinctive: "PR shipped, deployment shows
SUCCESS, but production behavior unchanged." Almost always the
worker hasn't recycled. Wasted hours come from re-reading the diff
looking for a bug that isn't there.

**Pattern:** any PR that touches code path X must verify that the
process running code path X has been restarted post-deploy before
declaring the fix verified. Validation cycles before restart are
running the OLD code and produce misleading evidence — both
"unchanged" (suggests fix didn't work) and "changed" (suggests
correlation with something else) are unreliable signals.

**Verification step (cheap):** check Railway deployment status via
`mcp__railway-mcp-server__list-deployments` AND the worker's most
recent boot timestamp. If `last_deployment_at > worker_boot_time`,
the deploy hasn't propagated to that worker yet. For the worker
service specifically, deploy state of `DEPLOYING` (vs `SUCCESS`)
means the new image is shipping but isn't running.

**Operator-side mitigation:** if the worker doesn't restart on its
own within the expected window (typically <5 min for image swap on
Railway), trigger explicit restart via Railway MCP. The deploy step
ships the image; the restart applies it.

**Origin:** 2026-05-04 OBP-fix verification incident. PR #864
("PR A") was thought stale at 17:46 UTC because the OBP reading
hadn't moved. Diagnostic via Railway MCP showed the deploy was in
DEPLOYING state, not SUCCESS — the 17:46 cycle ran on PR #862's
image. Once #864 finished deploying ~5 minutes later, the 17:54
cycle correctly read $417.75. No code defect; pure deploy-timing
gap dressed up as a fix-validity question.

**Scope:** affects RQ workers (`worker.railway.internal`),
APScheduler-resident jobs, any long-running process on Railway.
Does NOT affect FastAPI request handlers, which re-instantiate per
request from the deployed image.

#### False-alarm pattern + verification discipline (added 2026-05-12)

H8-class hypotheses ("PR shipped, behavior unchanged, suspect worker
stale") should ALWAYS go through worker verification BEFORE any
restart action is taken. Hypothesis-generation is cheap; acting on an
unverified hypothesis is the failure mode.

The verification step itself is small — typically 5-10 minutes:

1. **Get PR merge time** from `git log -1 --format='%ci' <merge_sha>`.
2. **Get deployment SUCCESS timestamp** via
   `mcp__railway-mcp-server__list-deployments` (filter to SUCCESS,
   note the latest one's timestamp).
3. **Get current worker process boot timestamp** by searching deploy
   logs for `Worker <id>: started with PID` (or the equivalent boot
   signature for the worker runtime in use).
4. **Compare:**
   - If `worker_boot_time > deploy_SUCCESS_time` AND
     `deploy_SUCCESS_time > PR_merge_time`: the code is live; H8 is a
     false alarm; look elsewhere.
   - If `worker_boot_time < deploy_SUCCESS_time` (worker booted on an
     older image): TRUE H8; restart the worker.
   - If most-recent deploy is in DEPLOYING state: wait for SUCCESS;
     the H8 is real but transient.
5. **Action gated on (4):** only restart if verification confirms
   stale code. Do not restart on hypothesis alone.

#### Why verification matters even when hypothesis seems likely

- **Cost of acting on a FALSE H8 hypothesis:** unnecessary worker
  restart (~1-2 min outage, brief reset of in-memory state including
  RQ queue subscriptions). Small but real.
- **Cost of acting on a TRUE H8 hypothesis when undetected:** stale
  code keeps running indefinitely. High if not caught.
- **Cost of skipping verification:** the diagnostic becomes
  unreproducible — the operator can't tell after the fact whether
  the restart was needed or whether it was a false positive that
  also happened to fix things via coincidence (e.g., the next deploy
  cycle landed during the "restart window").

Verification is always cheaper than the false-action outcome in
either direction. Run the steps even when the H8 hypothesis has
strong supporting evidence; the verification refutes the hypothesis
cleanly when warranted.

#### Confirmed instances this month

| Date | Hypothesis | Result | Action taken |
|---|---|---|---|
| 2026-05-04 | OBP-fix verification (PR #864) | TRUE H8 — deploy still in DEPLOYING state | Waited ~5 min for SUCCESS; no restart needed |
| 2026-05-12 | PR #908 mleg sign-flip not live | FALSE alarm — current worker booted 19:00:46 UTC on image built post-PR-#908 merge; 15:15Z rejection was on now-REMOVED earlier deploy | No restart; root cause for the rejection was deploy timing, not staleness |

#### Doctrine signal — false-alarm count is itself useful

The 2026-05-12 false alarm is NOT evidence the verification step is
overkill or that hypothesis-generation was wrong. The evidence
supporting the H8 hypothesis was real (pre-PR-#908 error text in
production). The verification step is what refuted the hypothesis
cleanly. Don't penalize hypothesis-generation when the diagnostic
produced concrete supporting evidence — penalize only the case where
action was taken without verification.

The discipline working as intended: hypothesis surfaces with concrete
evidence → verification tests against ground truth → action is gated
on verification result. Both TRUE and FALSE outcomes of verification
are healthy diagnostic signals.

#### Diagnostic-prompt convention

When a diagnostic surfaces "PR shipped, behavior unchanged" as a
hypothesis, the prompt MUST include the verification steps above
before any restart action is recommended. Verification = compare
worker boot time to PR's deploy SUCCESS time. Restart action is
gated on the verification result.

### H9 — Verified-write across wrapper chains

When data flows producer → wrapper(s) → consumer through more than
one process boundary, **the consumer (or end of the chain) must
verify the side effect actually occurred**, not infer success from
intermediate "no exception raised" signals.

This sits one level above Anti-pattern 8 (whitelist wrapper drops
fields). Anti-pattern 8 is one *manifestation*; H9 is the *class*.
Five+ data points surfaced this week confirm the class shape:
producer assumes success, intermediate wrapper silently degrades
output, consumer sees a default-shaped value (None / empty dict /
fallback path), nothing alerts. Each layer in isolation looks
correct. The defect is always in the seam.

**The class is recursive.** Once you start fixing one cascade, the
next layer's silent-degrade often surfaces as the layer before it
gains honest accounting. PR-A (#115) was the headline example: a
URL-typo fix exposed an enqueue-path drop, which exposed a missing
DB constraint, which exposed a swallowed upsert, which exposed a
body-dropping endpoint signature, which exposed a logger-formatter
drop, which exposed an INTEGER coercion drop. Seven layers, each
genuinely independent, surfaced one-by-one over 36 hours as each
fix unblocked the next failure to become loud.

#### The 2026-05-04 → 2026-05-10 catalog

Six concurrent or near-concurrent instances surfaced this past week,
each at a different boundary type:

| # | Cascade | Boundary | Layers | Closure |
|---|---|---|---|---|
| 1 | PR #864 alpaca_client field-drop | provider→wrapper→consumer (HTTP API) | 1 | PR #864 fixed wrapper, PR #865 added consumer fallback alert |
| 2 | #115 PR-A iv_daily_refresh | scheduler → endpoint → handler → DB write | 7 | PRs #899, #901, #903, #905, #906, #907 |
| 3 | Issue B CSX close-orders (#908) | sizing → broker translation → broker API | 4 | PR #908 (sign-flip + clamp + alert + reason capture) |
| 4 | #62a-D3 regime_snapshots | producer → DB write into missing table | 1 (silent) | PR #912 deletion |
| 5 | #62a-D5 / #117 DROPPABLE shim | producer → persistence shim → DB | 1 (silent strip + retry) | PR #912 (D5 fields) + #117 backlog (broader audit) |
| 6 | drop-table apply-time FK surprise | diagnostic tool → operator | 1 (`information_schema` underreports) | This week's #62a sweep documented the methodology gap |

The boundaries vary widely (HTTP API, DB constraint, broker
gateway, scheduler URL, persistence shim, diagnostic introspection).
The shape is identical: an intermediate transform silently degrades
information, and a downstream consumer or operator proceeds on a
false-positive success signal.

#### Detection signatures

These shapes are high-risk and should trigger careful review at PR
time:

- **Wrapper hand-builds output dict** instead of forwarding the
  upstream object. Risk: any new field the consumer needs from
  upstream silently goes missing. Anti-pattern 8 case.
- **Wrapper catches exceptions and returns success-shaped default**
  without alerting. Risk: consumer can't distinguish "operation
  succeeded with no result" from "operation failed silently."
  Anti-pattern 2 case.
- **Producer's success indicator doesn't reflect the side effect**
  (e.g., function returns "ok" without checking the DB row landed,
  HTTP returns 202 without verifying the queue accepted the job).
  Risk: handler-trusts-wrapper class.
- **Consumer fallback path is operationally indistinguishable from
  the success path** (e.g., empty dict produces same downstream
  behavior as a populated dict that happens to have no entries).
  Risk: silent fallback masks upstream failure for unbounded time.
- **Type signature lies** (function annotated `-> dict` returns
  `{}` on both success-with-no-data AND failure). Risk: caller
  can't distinguish.
- **Tooling that under-reports** (introspection query, schema
  lookup, FK enumerator that misses some entries). Risk: diagnostic
  itself becomes a wrapper-drift instance. The 2026-05-10
  drop-table apply caught this — `information_schema.referential_constraints`
  underreported inbound FKs vs `pg_constraint`-against-`confrelid`.

#### Convention: "verified-write"

For any operation with externally-visible side effects, the
producer/wrapper/consumer chain MUST satisfy:

1. **Wrappers return outcome, not just absence-of-exception.**
   Boolean / Result / typed enum reflecting the actual write.
   Pre-#115-PR-A `IVRepository.upsert_iv_point` returned `None`
   on both success and failure; post-fix it returns `bool`
   distinguishing the two paths.

2. **Consumers verify the outcome AND verify the side effect at
   anchor checkpoints.** Anchor checkpoints are independent
   queries that confirm the chain worked end-to-end (the fish
   actually got into the boat, not just that the line tugged).
   PR-A Layer 4's `count_rows_for_date` post-loop check is the
   reference implementation. The handler's per-symbol stats can
   lie; the row count cannot.

3. **Silent-degrade paths must `alert()` per Anti-pattern 2.**
   The DROPPABLE shim's `print(...)` was the failure mode that
   let #62a-D5's silently-dropped fields persist for unknown
   duration. Loud-Error Doctrine v1.0 is structurally what closes
   wrapper drift over time.

4. **Class-prevention tests at the seam, not just at the
   endpoints.** The wrapper boundary is what drifts; the test
   should walk the chain and assert the field/outcome survives.
   `test_alpaca_client_get_account_wrapper.py` (PR #864) and
   `TestNoProductionCodeImportsLegacyEnqueue` (PR #913) are the
   reference shape.

#### Codified pattern with empirical anchors (2026-05-12)

The four rules above are abstract. The five H9 instances closed
between 2026-05-04 and 2026-05-12 used a consistent concrete fix
shape. Codifying it here with the actual code anchors so future
fixes can copy from precedent rather than re-derive.

##### Cross-instance fix-pattern table

| Instance | Boundary | Wrapper's pre-fix claim | Actual outcome | Fix shape (rule mapping) |
|---|---|---|---|---|
| PR-A Layer 4 (PR #903) | DB write (`upsert_iv_point`) | `None` return on both success/exception | Silent rejection (PostgreSQL 42P10 from missing UNIQUE) | Typed return + anchor checkpoint + critical alert (Rules 1+2+3) |
| Issue B / PR #908 | Broker API (`build_alpaca_order_request`) | Positive limit_price clamped to ≥0.01 → "submitted" | Alpaca rejected with 4-9ms latency (sign convention) | Sign-preserving magnitude clamp + `order_rejected_by_broker` alert at poll site (Rules 1+3) |
| PR #864 | Broker API (`AlpacaClient.get_account`) | Hand-built dict missing `options_buying_power` | Consumer fell back to `paper_baseline_capital` for 5 days | Wrapper forwards field + source-level guard test + consumer-fallback alert (Rules 1+4 + Anti-pattern 8) |
| #62a-D5 / #117 (PR #912) | Persistence shim (`DROPPABLE_SUGGESTION_COLUMNS`) | `print(...)` on drop, retry, return success | Fields silently stripped for unknown duration | Loud-Error Doctrine Anti-pattern 2 closure + field-presence audit (Rule 3) |
| MTM PR-1+PR-2 (#919, #920) | Refresh service (`refresh_marks`) | `{"status": "ok"}` on partial-skip | DB unrealized stale by -$188 | `{ok, partial, fallback_used, skipped}` return + `last_marked_at` column + `mtm_refresh_partial` alert + broker-authoritative fallback (Rules 1+2+3) |

The boundaries differ (DB write, broker API in/out, persistence
shim, refresh-side-effect) but each fix used the same building
blocks: typed return + anchor checkpoint + loud-partial alert.

##### Rule 1 — Typed-outcome return (concrete anchors)

The wrapper's return must distinguish "wrote it" from "didn't
write it" — boolean / Result / typed enum, not `None` on both
paths or `dict` with single `"status": "ok"` shape that doesn't
encode partial state.

- **PR-A Layer 4 anchor:** `IVRepository.upsert_iv_point` at
  `packages/quantum/services/iv_repository.py:50-55` —
  `-> bool` annotation; returns `True` on confirmed write, `False`
  on exception OR empty PostgREST `result.data` (server-side
  silent rejection).
- **MTM PR-1 anchor:** `refresh_marks` at
  `packages/quantum/services/paper_mark_to_market_service.py:29`
  returns extended dict including
  `{"status", "positions_marked", "positions_skipped",
  "fallback_used", "errors", "total_positions"}` — `status`
  enum carries `"ok"`, `"partial"`, `"failed"` semantics; the
  count fields encode partial state explicitly.
- **#864 anchor:** `AlpacaClient.get_account` at
  `packages/quantum/brokers/alpaca_client.py:200-225` —
  `options_buying_power` uses **None-preserving coercion**
  (`float(_obp) if _obp is not None else None`) so consumers can
  distinguish "field absent" from "valid 0.0", which is itself a
  typed-outcome distinction.

##### Rule 2 — Anchor checkpoint (concrete anchors)

Independent query / authoritative re-read that confirms the
side effect occurred. Not the wrapper's own success indicator.

- **PR-A Layer 4 anchor:** `IVRepository.count_rows_for_date(date)`
  at `packages/quantum/services/iv_repository.py:158`. The
  handler at `packages/quantum/jobs/handlers/iv_daily_refresh.py:130`
  calls it post-loop; mismatch with `stats["ok"]` fires
  `iv_handler_accounting_mismatch` (`severity="critical"`,
  `:137-153`). Returns `-1` sentinel on query failure so the
  handler doesn't fire false positives when verification itself
  fails.
- **MTM PR-2 anchor:**
  `paper_mark_to_market_service._compute_position_value_from_broker`
  at `:518` reads from broker-authoritative
  `broker_positions_by_symbol` dict (pre-fetched via
  `Alpaca.get_all_positions()` at `:73-95`) when snapshot path
  returns incomplete leg pricing. Verification source IS the
  broker, not derived snapshot state.
- **#864 anchor:** PR #864's
  `test_alpaca_client_get_account_wrapper.py` is the anchor
  checkpoint at the source-code level — asserts the wrapper
  exposes the field. PR #865 added the consumer-side alert at
  `cash_service` fallback so missing-field surfaces at runtime
  within one cycle.

##### Rule 3 — Loud-partial alert (concrete anchors)

When partial state is encountered, emit an alert per Anti-pattern
2. The wrapper's return must enable callers to distinguish, AND
the wrapper itself must alert when it detects partial.

- **MTM PR-1 anchor:** `mtm_refresh_partial` alert at
  `paper_mark_to_market_service.py:240` (severity=warning,
  metadata includes `{positions_marked, positions_skipped,
  total_positions, source, errors, consequence, fallback_used,
  skipped}` — captures both "what was skipped" and "what fell
  back to broker authoritative").
- **#908 anchor:** `order_rejected_by_broker` alert at
  `packages/quantum/brokers/alpaca_order_handler.py:705`
  (severity=critical, 1/hour throttled per
  `(alert_type, position_id)` via the dedup query at `:687`).
  Wrapped in try/except so alert-path failure never breaks the
  poll loop's primary work.
- **PR-A Layer 4 anchor:** `iv_handler_accounting_mismatch` at
  `iv_daily_refresh.py:137-153` (severity=critical, metadata
  includes `{stats_ok, actual_rows, delta, as_of_date,
  doctrine_ref}`).
- **#62a-D5 anchor:** the DROPPABLE shim's `print(...)` was
  exactly the failure mode this rule forbids. PR #912 closed
  the silent path; Anti-pattern 2 in this doctrine documents
  the broader shape.

##### Boundary-specific applications

The convention applies across four boundary types with shape
variations. The first three have empirical instances; the
fourth is hypothetical.

| Boundary | Producer | Anchor checkpoint | Alert pattern | Reference instance |
|---|---|---|---|---|
| DB write | iteration writing rows | `SELECT COUNT(*)` vs expected | `<handler>_accounting_mismatch` | PR-A Layer 4 / `iv_handler_accounting_mismatch` |
| Broker API (outbound) | order construction / submission | re-read order from broker; check fields match intent | `order_rejected_by_broker` or `broker_intent_mismatch` | PR #908 + #864 |
| Refresh / RMW | data-fetch that may return incomplete data | timestamp/completeness probe (e.g. `last_marked_at`) | `<service>_refresh_partial` | MTM PR-1+PR-2 |
| CLI/route | HTTP endpoint / CLI command | re-read state via separate endpoint to confirm action | `<endpoint>_action_unconfirmed` | **None yet** — first instance will calibrate |

For DB writes specifically: prefer authoritative-source
verification (the table the wrapper writes to) over derived
stats. `stats["ok"]` is a producer's claim;
`count_rows_for_date` is the side effect itself.

For broker API: prefer the broker as authoritative
(`get_all_positions()`, `get_order(id)`) over our own ledger.
The broker is the source of truth for what actually exists in
the market; our ledger is a hopeful mirror.

##### When the convention does NOT apply

The convention is for wrappers where the return value drives
downstream decisions on operationally important side effects.
It is NOT required for:

- **Pure functions** with no side effects (nothing to verify).
- **Fire-and-forget logging** where the wrapper's failure is
  acceptable (the failure mode itself is the "no log line").
- **Wrappers where the side effect IS the return value** (e.g.,
  `compute_unified_score(...)` returns the score; there is no
  separate side effect).
- **Hot-path inner loops** where authoritative re-read would
  add unacceptable latency. In this case, fall back to typed
  return + alert; skip the anchor checkpoint, but DO emit
  alerts on partial state so operators can sample post-hoc.

Use judgment. The convention prevents wrapper-drift on
operationally important side effects; it does not exist to add
ceremony to every function call.

##### Future considerations

- **CLI/route boundary instances:** the convention's shape there
  is hypothetical. First real instance will refine — e.g., a
  CLI command that triggers a side-effect endpoint and needs
  post-hoc verification before reporting success to the
  operator.
- **Cost of verification:** Rule 2 (anchor checkpoint) adds API
  calls or DB reads. Acceptable trade-off for operationally
  important side effects; not always for every wrapper. See
  "hot-path inner loops" exception above.
- **Recursive verification:** if the verification step itself
  uses a wrapper, the same convention applies recursively.
  Cycle-safety needs monitoring (verify-then-verify-then-verify
  could exhaust budget). Pre-fetch + cache pattern in MTM PR-2
  amortizes this — broker positions fetched once, used as
  verification source for many positions.

#### Class-prevention infrastructure proposals (2026-05-12)

Three infrastructure pieces would mechanically enforce H9
Convention. Ranked by coverage × effort + precedent strength.

Each proposal is a future PR slot, not part of this codification
PR.

##### Slot 1 — AST gate: "wrapper returns success without verification"

**Goal:** at CI time, flag Python wrapper functions that return
typed-success indicators without a corresponding verification
step.

**Detection heuristic:**
- Function name matches side-effect wrapper pattern:
  `refresh_*`, `write_*`, `submit_*`, `update_*`, `upsert_*`,
  `persist_*`, `apply_*`, `mark_*` (configurable allow-list).
- Function returns dict with `"status"` key OR returns `bool`
  OR returns enum/Literal that carries success/failure
  semantics.
- Function body OR caller chain contains NO verification
  pattern: no `count_*_for_*`, `get_*_by_id`, `assert_*`,
  `verify_*`, post-loop `SELECT COUNT`, broker-side re-read.

**Precedent:** PR #917 Class B AST gate
(`test_internal_tasks_class_b_body_gate.py`) — uses
`ast.parse` + node-walker to enforce structural rules on
`/internal/tasks/*` endpoints. Same skeleton applies here.

**Coverage:** would have caught all 5 H9 instances at PR time
(each wrapper had typed return without verification before
the fix). High-precision rule via name + signature filtering.

**Effort:** ~half day implementation + ~half day to build the
allow-list with operator sign-off on legitimate exceptions
(e.g., fire-and-forget loggers, pure-compute wrappers
mis-named).

**Limitations:**
- False positives on wrappers whose verification is implicit
  in the caller chain (e.g., test wrappers, scheduler retry
  paths).
- Doesn't catch verification that exists but is wrong (verifies
  the wrong thing, returns dummy data).
- Naming-pattern drift requires periodic allow-list maintenance.

**Test fixtures:** each of the 5 H9 instances has a "before"
code state available via `git show <pre-fix-sha>`. Build
fixtures from those; verify the AST gate flags each.

##### Slot 2 — Grep test: silent-exception patterns in wrapper paths

**Goal:** detect `try: ... except: pass`,
`try: ... except: return None`, and `print(...)` swallow
patterns specifically in wrapper-path files
(`services/`, `brokers/`, `jobs/handlers/`).

**Detection rule (regex sketch, brittle but viable):**
- Pattern: `except.*:\s*\n\s*(pass|return None|return False|continue|print\()`
- Scope: only files under `packages/quantum/services/`,
  `packages/quantum/brokers/`, `packages/quantum/jobs/handlers/`.
- Allow-list: per-file or per-line annotation pragma
  (`# noqa: H9-AP2-VALID` for legitimate cases — Valid 5
  alert-write recursion, Valid 7 idempotent inserts).

**Precedent:** PR #913 Tier 3 widen test (legacy `enqueue_idempotent`
grep gate). Same shape: codebase-wide scan with allow-list.

**Coverage:** medium. Catches Anti-pattern 1 (bare except: pass)
and Anti-pattern 2 (log-only swallow) in the boundary-relevant
directories. Misses wrappers that return success-shaped data
without try/except at all (Slot 1 covers those).

**Effort:** ~2 hours. Most of the cost is curating the initial
allow-list — every existing `except: pass` in scope needs an
explicit decision (legitimate / refactor target / migrate to
alert).

**Limitations:**
- Brittle regex; can be evaded with slightly different syntax
  (`except Exception as _: pass` doesn't match the simplest
  rule).
- Doesn't understand semantics — some `except: pass` is
  legitimate (Valid 5 alert-write recursion, Valid 7
  idempotency).
- Requires growing allow-list as new legitimate cases surface.

**Cross-reference with Anti-pattern 2 above:** the doctrine
already forbids silent-fallback; this gate mechanizes the
forbiddance for the high-risk directories.

##### Slot 3 — Type-narrowing convention: Literal status returns

**Goal:** encode the "fully succeeded / partial / failed"
distinction in return types so the type checker forces callers
to handle each case explicitly.

**Convention sketch:**
```python
from typing import Literal, TypedDict

class RefreshResult(TypedDict):
    status: Literal["ok", "partial", "failed"]
    marked: int
    skipped: list[str]
    errors: list[dict]

def refresh_marks(user_id: str) -> RefreshResult:
    ...

# Caller must handle all 3 Literal cases
match result["status"]:
    case "ok":     ...
    case "partial": ...   # mypy/pyright enforces no-skip
    case "failed":  ...
```

**Precedent:** no direct codebase precedent yet. Would establish
the pattern for new wrappers. MTM PR-1's extended return shape
is the implicit precedent — explicit Literal typing would
formalize it.

**Coverage:** new wrappers + opt-in refactors of existing
wrappers. Does not retrofit; grows over time.

**Effort:** ongoing rather than one-shot. Per-wrapper effort is
~10 min (TypedDict definition + caller-site match statement).
mypy strict mode requirement is the upfront cost; current
codebase config likely needs incremental tightening.

**Limitations:**
- Doesn't retrofit existing code without operator decision.
- Requires mypy strict mode OR pyright strict — current CI
  may not have either enabled at the requisite level.
- Adds slight verbosity at caller sites (match statement vs
  single dict-key check).

##### Priority recommendation

Ship **Slot 1 first** (AST gate): highest coverage, clearest
precedent (#917), would have caught all 5 known H9 instances
at PR time. Ship **Slot 2 second**: backfills the
silent-exception pattern coverage in the same directories.
Adopt **Slot 3 as convention** for new wrappers — no upfront
retrofit, but new code should follow the Literal pattern.

If only one slot ships near-term: **Slot 1.** It is the highest
leverage; Slot 2's coverage is partially redundant with
Anti-pattern 2 already documented, and Slot 3 grows from
discipline rather than enforcement.

If verification reveals Slot 1's AST gate would cover Slot 2's
grep pattern as a subset (i.e., the AST gate already detects
silent-exception inside wrapper bodies), **consolidate** rather
than ship overlapping infrastructure.

##### Status

- **Slot 1:** PR slot queued. No assignee, no scheduled merge.
- **Slot 2:** PR slot queued behind Slot 1. May be cancelled
  if Slot 1 covers the same surface.
- **Slot 3:** convention adopted for new wrappers starting
  2026-05-13. No infrastructure work required; code review
  catches violations.

#### Cascading-cascade discipline

When one wrapper-drift fix surfaces another, the temptation is to
batch them all into one mega-PR. Don't. Each layer should ship
independently so:

- Each layer's deploy validates the next-layer surface before fixing
  it. Pre-PR-A Layer 4's accounting fix, Layers 5 and 6 weren't
  visible. Skipping the validation cycle would have shipped Layer 5
  blind — it would have surfaced via the next operator-driven
  re-fire instead.
- Each layer's PR description carries a single clean root-cause
  story rather than a tangled multi-cause narrative. Future debugging
  benefits from linear history.
- The doctrine-document anchor (this entry) gets one new data point
  per PR, not a blob of 5+ items in one commit.

The cascading-cascade pattern is itself a class signature: if PR-A's
shape recurs (single-cascade investigation that grows into a
multi-PR sequence), explicit "wait for next-layer surface before
shipping the next fix" discipline is what keeps the work tractable.

#### Anti-pattern catalog updates

Anti-pattern 2 (silent fallback) and Anti-pattern 8 (whitelist
wrapper) remain the specific code-shape rules. H9 sits above them
and answers the meta-question: when these shapes manifest in a
chain rather than a single function, how do you prevent the chain
from silently degrading end-to-end?

**Class-prevention infrastructure shipped:**

- **Class A — grep gate (PR #913):** no production module imports
  `enqueue_idempotent` from `packages.quantum.jobs.enqueue` (the
  legacy DB-only path). Codebase-wide AST walk excluding
  `scripts/`, `tests/`, `__pycache__/`, `venv/`. Failure message
  points at canonical `enqueue_job_run` migration target.
- **Class B — AST gate (PR \<NEXT\>):** every internal_tasks
  endpoint that BOTH calls `enqueue_job_run` AND appears in the
  CLI TASKS catalog at `scripts/run_signed_task.py` must accept
  a Body parameter. The CLI-catalog intersection precisely matches
  the threat model — scheduler-only enqueue callers are
  auto-exempt because nothing external sends them a body.
  First design pass tried "all enqueue callers must have Body"
  but caught 5 false positives (intraday_risk_monitor,
  day_orchestrator, promotion_check, heartbeat, phase2_precheck);
  CLI-catalog intersection is the correct enforcement axis.

**Future class-prevention infrastructure candidates** (separate
backlog work):

Replaced 2026-05-12 by the **Slot 1 / Slot 2 / Slot 3** ranked
proposals in "Class-prevention infrastructure proposals" above.
The two bullets that previously lived here (broker-wrapper grep
test + pyright/mypy convention) are subsumed:
- Broker-wrapper grep → Slot 2 (silent-exception patterns in
  wrapper paths, scoped to `services/` + `brokers/` + `jobs/handlers/`)
- pyright/mypy Literal convention → Slot 3 (Literal status
  returns)

Plus a new Slot 1 (AST gate for wrappers-without-verification)
that has no prior bullet and is the recommended first ship.

#### Origin

2026-05-04 → 2026-05-10 cascade week. PR-A's 7-layer cascade was
the headline; Issue B + #62a + #117 + #864 are the concurrent data
points that elevate this from "interesting incident" to
"architectural class." Adding this as H9 captures the synthesis
while it's fresh — the operator-side question for Monday review is
**which class-prevention infrastructure to ship next** (the AST/
wrapper-grep/type-narrowing candidates above), not whether the
class is real.

#### H9 generalization — silent decisions (2026-05-20)

H9 was originally codified around error handling: silent
try/except patterns where wrappers swallow exceptions and
consumers infer success from absence-of-exception. The
underlying principle is broader: **any decision the system makes
that affects downstream behavior should leave a queryable
trace.** Error handling is one instance; selection/filter/
threshold decisions are another.

**Operational instance discovered 2026-05-19:** universe
selection via `UniverseService.get_scan_candidates(limit=50)`
was making 50-of-70 selection decisions every scanner cycle
with zero observability. The bottom 20 symbols by
`liquidity_score` were silently dropped — no rejection record,
no alert, no surface anywhere. 19 of the 34 never-emitter
symbols surfaced in that day's funnel diagnostic were
attributable to this single silent-truncation site. The pattern
is structurally identical to silent-error-swallow: a decision
boundary with no verification.

**General pattern:** when a function returns a SUBSET of
available inputs (filter, top-N, threshold cut), the function
must log what was *excluded*, not just what was *included*.
Consumers of the function naturally verify inclusion (they see
the returned set); observability of exclusion requires that
the dropped tail also be queryable. Without it, "system did
nothing for symbol X" is operationally indistinguishable from
"symbol X was silently dropped at an early boundary."

**Convention:** the four verified-write rules above generalize
to verified-decision. Replace "side effect" with "selection
decision" and "anchor checkpoint" with "queryable exclusion
log":

1. **Selectors return outcome, not just inclusion.** The
   wrapper's primary return is the included set; the
   observability surface captures both included and excluded
   sets with the decision criteria (threshold, score, reason).
2. **Consumers can verify the decision at anchor checkpoints.**
   The exclusion log IS the anchor — independent of the
   wrapper's success indicator, queryable post-hoc.
3. **Selector-write failure must `alert()`.** The exclusion
   log writer is itself H9-compliant; observability cannot
   silently regress.
4. **Class-prevention tests at the decision boundary.** Tests
   walk the selector and assert both halves of the decision
   are captured.

**Operational instances of this generalized pattern** (catalog
as discovered):

- 2026-05-20: `universe_service.get_scan_candidates` →
  `universe_selection_log` table; verified-write per Rule 3
  via `universe_selection_log_write_failed` alert. Resolved
  in PR #970.
- 2026-05-21: `workflow_orchestrator.run_midday_cycle` →
  `cycle_metadata` + `enriched_counts` emitted at all 7
  return paths via `_build_cycle_metadata` /
  `_build_enriched_counts` helpers; `exit_reason` field
  distinguishes pre-funnel vs. post-funnel exits vs. happy
  path. See "Early-exit observability symmetry" below.
- Future instances: add as discovered. Likely surfaces:
  ranker top-N cuts, EV-floor filters, strategy_selector
  emission gates, any `policy_lab` cohort selection step.
  Each is a decision boundary where exclusion is operationally
  important but pre-PR-time observability typically only
  captured inclusion.

**Early-exit observability symmetry (2026-05-21):** when a
function has multiple return paths, observability surfaces
should be emitted at all of them, with explicit discriminators
distinguishing the paths. Asymmetric observability across
return paths is a silent-decision pattern — the consumer
cannot tell "field intentionally absent because pre-funnel
exit" from "field forgotten because the writer skipped this
return path." Encode partial-state by field *value* (None for
"not measured", a measured value for "measured"), and add an
explicit `exit_reason` (or equivalent) field that names which
return path was taken. The presence/absence of fields should
not carry semantics; values should. Origin: PR #959's
`cycle_metadata` writer fired only on `run_midday_cycle`'s
happy path; 6 early-exit returns went without the surface for
~2 days until today's 16:00 UTC cycle landed on the
`no_suggestions_after_gates` early-exit and the gap surfaced.

The doctrine catalog (Anti-pattern 2, Anti-pattern 8) remains
specific to error-handling shapes. H9 sits above both; the
silent-decision generalization extends H9's class without
introducing a new top-level entry — the principle is the same.

### H10 — Stale state cascades through pipeline gates (ghost reconciliation is load-bearing)

A single stale row in a hot table can suppress an entire pipeline by
cascading through multiple sequential gates. The symptom presents as
"system is silent" — no trades, no candidates, no obvious error — but
the underlying state is the opposite of silent: each gate is firing
loud diagnostics against the stale row, the gates are just consecutive
enough that the surface appears blank.

Reconciliation of orphan rows (after operator-side manual actions
bypass the system's submission chain) is not optional observability
hygiene. It is a **load-bearing prerequisite** for the trade pipeline
to function.

#### Observed cascade (2026-05-12 CSX ghost incident)

A `paper_positions` row marked `status='open'` after the underlying
position was closed via the Alpaca UI cascaded through three pipeline
gates:

| Layer | Gate | Effect |
|---|---|---|
| 1 | `suggestions_open` micro-tier "one position at a time" | `suggestions_skipped:true, reason:micro_tier_position_open, 0 candidates produced` |
| 2 | `paper_auto_execute` per-symbol risk envelope cap | `"CSX is 100% of risk (limit 40%)"` fired every 15 min from 14:45Z; `status:blocked, executed_count:0` |
| 3 | `intraday_risk_monitor` in-memory loss recompute | Stale `unrealized_pl` triggered force-close attempt against a phantom position → broker rejection → 2 critical `paper_order_marked_needs_manual_review` alerts |

Each layer in isolation looked like normal gating behavior. Read in
sequence, they describe a pipeline that has been suppressed end-to-end
by a single row.

#### Detection signatures

- **"No trades today"** symptom with healthy scheduler heartbeats.
  Gate diagnostics are firing in `risk_alerts` but the user-facing
  surface is blank.
- **`ghost_position` alerts firing repeatedly** against the same
  `paper_positions.id`. PR #98's Option B sweep emits these at
  `~1 fire per 5 min` matching `alpaca_order_sync` cadence. Treat
  the volume as urgent operational signal, not informational noise.
- **Force-close attempts producing broker rejections** without any
  recent live entry. The phantom unrealized triggered the close; the
  broker rejects because there's nothing to close.

#### Operational discipline

When operator manually intervenes (e.g., closing a position via Alpaca
UI to bypass a broken code path, manual SQL update to unblock a
diagnostic, etc.), the FIRST follow-up action is DB reconciliation —
before any other engineering work resumes. Operator-side state changes
that bypass the system's submission chain create orphan rows that the
system will then treat as load-bearing.

The reconciliation procedure for `paper_positions` orphans (see CSX
2026-05-11 entry in `docs/backlog.md`):
1. Identify the orphan via Alpaca authoritative fill data
2. Compute realized P&L from entry + close fills
3. `UPDATE paper_positions SET status='closed', closed_at=<fill_ts>,
   realized_pl=<computed>, close_reason='manual_close_user_initiated',
   fill_source='manual_endpoint'` (matches CHECK constraint enums)
4. Write `risk_alerts` audit row with the reconciliation rationale

#### Relationship to other doctrines

- **Adjacent to H9 (verified-write across wrapper chains):** H9 covers
  data flow from producer to consumer through wrappers; H10 covers a
  single stale state propagating through sequential pipeline GATES.
  H9's seam-between-layers maps to H10's between-gates.
- **Adjacent to "parallel architectures without integration"** (the
  doctrine candidate raised in #62a-D1's sub-investigation). Both
  describe failure modes where each component works in isolation but
  the *interaction* (between layers, between gates, between
  unconnected architectures) is the bug.

#### Origin

2026-05-12 trade-absence diagnostic. The CSX ghost row had existed
for ~6 days post-operator manual close but only surfaced as a pipeline
liveness issue when a new candidate was expected. PR #921's
reconciliation framing as "data correction to silence alerts" was
incomplete — the reconciliation was the unblock for tomorrow's
suggestions + execution.

### H11 — Status-check methodology: critical alerts as baseline section

Every operational status check or diagnostic that investigates a
specific operator hypothesis (e.g., "did a trade happen?", "is the
worker stale?", "did the close fire?") MUST also include a baseline
section querying critical/high severity `risk_alerts` independently
of the hypothesis. The operator's framing is the hypothesis *under
investigation*, not the *boundary* of the investigation.

When status-check queries are anchored on `paper_positions` and
`paper_orders` only, critical events that don't materialize on those
tables (force-close attempts rejected at the broker handler, manual
review alerts, `ghost_position` storms) go unseen — even when they
are the actual operationally critical story of the period.

#### Required baseline query

Every operational diagnostic touching `risk_alerts` indirectly should
include this as a baseline section, queried independently of the
hypothesis being tested:

```sql
-- BASELINE — critical/high severity events regardless of operator framing
SELECT alert_type, severity, position_id, symbol, message,
       metadata, created_at
FROM risk_alerts
WHERE created_at >= NOW() - INTERVAL '<window>'
  AND severity IN ('critical', 'high')
ORDER BY created_at DESC;
```

Window choice: align to the operator's stated period (e.g., NOW() - 24h
for end-of-day, NOW() - 4h for post-trade-execution, NOW() - 30 min
for incident-in-progress). When in doubt, widen rather than narrow —
the cost of returning a few extra rows is small; the cost of missing
the actual story is large.

#### Where to apply

- Morning post-open status check templates
- Post-trade-execution status check
- End-of-day status check
- Any operational diagnostic that touches `risk_alerts` indirectly via
  joins or downstream tables
- Worker verification (H8) diagnostics — the baseline catches the
  alert volume that motivates the H8 hypothesis in the first place

#### Origin

2026-05-12 morning status check. Structured around "did a position
open" rather than "what critical events happened regardless of operator
framing." Missed two critical `paper_order_marked_needs_manual_review`
alerts at 15:15Z because the queries were anchored on `paper_positions`
and `paper_orders`. The force-close attempt + broker rejection only
appeared in `risk_alerts` and the status check never reached that
table. The H8 hypothesis that later surfaced ("worker stale, PR #908
not running") was generated from re-reading the worker logs after the
fact, not from the morning status check — which itself is evidence
the baseline section would have changed the diagnostic timeline.

### H12 — Framing-artifact discipline

Diagnostics can produce concrete-evidence conclusions whose underlying
ASSUMPTION is wrong. The measurement is accurate; the interpretation
(against what baseline, with what generalization) is where the error
enters. H8 already codifies verification of hypotheses; H12 sharpens
H8 by naming the specific failure mode — the verification step often
confirms surface evidence (true) without confirming the baseline
assumption (false).

**Discipline statement:** when a diagnostic conclusion is drawn from
data, explicitly state the baseline assumption AND the generalization
scope. Verify both before treating the conclusion as actionable.

#### Confirmed instances (codification trigger reached at 4)

The pattern was tracked as a backlog observation from 2026-05-12 with
"4th instance with new sub-shape" as the promotion criterion. Today's
KO H7 spread-width attribution provides that 4th instance with a
distinct sub-shape from the prior three. Promoted to formal doctrine
2026-05-13.

1. **2026-05-11 H11 status-check methodology gap.**
   - Diagnostic finding: status check showed no operational issues
   - Wrong baseline: framing assumed critical risk_alerts irrelevant
     to "did anything trade today" question
   - Correction: H11 baseline now includes critical alerts regardless
     of operator framing (codified separately as H11)
   - Sub-shape: **wrong-baseline framing**

2. **2026-05-12 PR #908 worker-stale hypothesis.**
   - Diagnostic finding: timestamp evidence suggested PR #908 not
     deployed
   - Wrong baseline: framing assumed single deploy point
   - Correction: verified earlier deploy had been replaced; PR #908
     IS live (codified separately as H8 extension)
   - Sub-shape: **wrong-deploy-model framing**

3. **2026-05-12 analytics_events writer-break hypothesis.**
   - Diagnostic finding: `analytics_events` "stale since 2026-05-05"
   - Wrong baseline: framing assumed time-based writing pattern
   - Correction: writer is event-driven; zero output during
     zero-activity period is healthy
   - Sub-shape: **wrong-temporal-model framing**

4. **2026-05-13 KO H7 spread-width attribution (this codification).**
   - Diagnostic finding: KO LONG_CALL_DEBIT_SPREAD $486 max_loss
     attributable to `options_scanner.py:1260` spread-width threshold
   - Wrong generalization: line 1260 was generalized from
     iron-condor-only to all spreads
   - Correction: debit spreads use `_select_legs_from_chain`
     (delta-target leg selection), not width-threshold logic; line
     1260 lives inside `_select_iron_condor_legs` and applies only
     to iron condors. KO's $486 max_loss comes from chain strike
     granularity ($5-wide strikes on $78 underlying) plus
     debit-spread leg_defs targeting deltas ~1 strike apart.
   - The verification escape hatch in the γ1 implementation prompt
     caught the error before shipping — STOP triggered when the
     code path read revealed line 1260 was iron-condor-only.
   - Sub-shape: **wrong-scope-generalization framing**

5. **2026-05-14 scheduler-stuck mechanism attribution.**
   - Diagnostic finding: BE service silent on job dispatches since
     05:00 UTC (~8h40m); morning jobs (`iv_daily_refresh`,
     `day_orchestrator`, `alpaca_order_sync`) missing.
   - Initial framing: "APScheduler dispatcher stuck / scheduler
     thread died."
   - Wrong baseline: assumed scheduler thread had failed.
   - Actual cause: scheduler thread was ALIVE and dispatching. Every
     job hung on outbound Supabase HTTP timeout
     (`observability/alerts.py:85` raising `httpx.ConnectTimeout`).
     Dispatcher queued jobs faster than they could complete because
     jobs couldn't complete (they hung on HTTP). `Auto-retry failed
     jobs` hit instance limit, confirming dispatcher was alive but
     all execution paths were blocked.
   - Correction: surface symptom (no `job_runs` writes) was correct
     evidence; inferred mechanism (scheduler dead) was wrong. Real
     mechanism was downstream outbound provider HTTP hang.
   - Recovery: BE service restart via env-var trigger
     (`RESTART_NONCE`). Scheduler resumed dispatching within 3 min;
     `suggestions_open` validation cycle fired cleanly.
   - Sub-shape: **wrong-mechanism-attribution framing** — same class
     as instance 1 (wrong-baseline). Surface measurement accurate,
     causal mechanism inferred from measurement was wrong.

6. **2026-05-14 cycle-shape misread during midday status check.**
   - Diagnostic finding: today's two `suggestions_open` cycles had
     "anemic payloads" — short duration (14-21s), no top-level
     `rejection_counts` / `budget` / `emission_counts_by_strategy`
     keys in `result`. The cycles "looked like wrapper-only success
     markers" relative to the assumed shape of a full scanner cycle.
   - Wrong baseline: framing assumed scanner output lives at the
     TOP-LEVEL of the `result` JSON. The comparison to "yesterday's
     full payload" was based on conversation-memory of what a
     successful cycle returns, not a verified read of any
     known-good day's row.
   - Correction: the full cycle data has always lived nested at
     `result.cycle_results[0].debug.rejection_stats` — not at the
     top level. Yesterday's (2026-05-13) cycle has the SAME thin
     top-level shape as today's. Today's midday cycle additionally
     lacks the `debug` block because it took the SUCCESS branch
     (candidate found), not because of degradation. The "thin
     top-level" is the consistent handler shape across the entire
     week (2026-05-08 → 2026-05-14).
   - Empirical impact: the midday combined status check produced a
     partial BLOCKER verdict on grounds that included "midday cycle
     looks like wrapper success." That sub-finding was wrong. The
     cycle-shape diagnostic surfaced the misread. Today's midday
     cycle actually produced a real Ford F LONG_CALL_DEBIT_SPREAD
     candidate that reached `trade_suggestions` (blocked downstream
     at `edge_below_minimum`, not at scanner / H7).
   - Sub-shape: **wrong-payload-shape framing** — same class as
     instance 1 (wrong baseline) and instance 4 (wrong-line
     attribution). Surface measurement was real (top-level
     keys missing); inference about what that meant (cycle
     degraded) was wrong because the baseline of "what real
     output looks like" was inferred from memory, not from data.
   - Discipline lesson: when comparing "today's output" to
     "expected shape," pull a representative known-good day's
     output FIRST and verify the comparison structure end-to-end.
     Don't infer comparison shape from conversation memory.
     Specifically, when JSON output has nested structure, the
     `jsonb_pretty` of a single row is the cheapest baseline read.

The six sub-shapes (wrong baseline / wrong deploy model / wrong
temporal model / wrong scope generalization / wrong mechanism
attribution / wrong payload shape) share the underlying class:
surface measurement accurate, model behind interpretation wrong.

Instance #5 status: H12 already covers this shape; the doctrine
worked as designed — operator pulled BE logs before assuming the
"scheduler thread died" hypothesis was correct, and the logs
revealed the actual mechanism. H12's verification protocol
(identify baseline / verify holds for THIS case / test before
shipping) prevented restart-then-find-it-still-broken outcome.

#### Meta-observation (2026-05-14): H12 applies to diagnostic synthesis

Today's Option A validation diagnostic synthesis initially produced
a broader framing than evidence supported:

- **Specific finding (well-supported):** 2-leg debit spreads on
  $50+ underlyings with $5-wide strikes produce ~$500 max_loss
  which exceeds H7 round-trip safety at $681 BP.

- **Over-generalized inference (NOT well-supported):** "$681
  capital + standard chain geometry = no viable strategies
  regardless of universe tuning."

The over-generalization was caught by operator pushback in real
time. The diagnostic's evidence was specific to 2-leg debit spreads;
the synthesis broadened it to "all strategies" without verifying
non-debit-spread structures (credit spreads, iron condors, 1-leg
longs, sub-$30 names with $1/$2.50 strikes).

**H12-shaped:** measurement accurate (2-leg debit spreads at $681
fail H7 ✓), generalization to "all strategies" unjustified, the
generalization was treated as actionable until operator caught it.

**Doctrine implication:** H12 applies to diagnostic SYNTHESIS, not
just root-cause attribution. When summarizing findings, separate
"evidence about specific X" from "general conclusion about Y
broader than X." The verification protocol's step 3 ("test before
shipping") should explicitly include "test whether synthesis scope
matches evidence scope."

**Refinement candidate for next doctrine hygiene round:** add an
explicit step to the verification protocol — "verify synthesis
scope matches evidence scope." Not adding inline today; capturing
as observation pending broader doctrine review.

#### In-conversation H12 catch (2026-05-14 midday): date-framing artifact

During the 2026-05-14 midday combined status check, the conversation
framing had treated "today" as 2026-05-15 throughout (earlier prompts,
PR #936 draft headings, "yesterday's PR #934" temporal references).
H12 discipline applied to the SQL date filter (`WHERE created_at >=
'2026-05-15 13:41:00+00'` returned 0 rows) forced a verification
query against `NOW()` — which returned `2026-05-14 16:35 UTC`.

System clock was the source of truth; conversation framing was one
calendar day ahead.

**Affected artifacts (corrected in PR #936's amendments):**
- PR #936's CLAUDE.md operational note heading
  ("Entry-premium-vs-width ratio (2026-05-15)") → 2026-05-14
- PR #936's backlog entry datestamps → 2026-05-14
- PR #936's "yesterday's note" temporal framing for PR #934 → "the
  prior note" (PR #934 actually merged 2026-05-14 10:31 CT, before
  PR #935 11:03 CT, before PR #936 itself)

**Discipline shape:** the date filter sub-routine in the status-check
prompt template ("query NOW() if returns look suspicious") caught
this prospectively. The doctrine's check-the-baseline reflex worked
exactly as designed — not retrospective root-cause analysis but
real-time verification when surface data felt off (0 rows where some
expected). Not promoted to a numbered instance because it was caught
during verification rather than after acting on the wrong inference.

Before treating a diagnostic conclusion as actionable:

1. **Identify the baseline assumption.** What model does the
   conclusion assume? Examples:
   - "single deploy point" (assumes the deploy timeline maps to a
     single timestamp; reality: deploys can be replaced)
   - "time-based writing" (assumes a writer fires on a schedule;
     reality: event-driven writers fire only on events)
   - "universal spread-width threshold" (assumes one width constant
     applies to all strategies; reality: separate strategy paths)
   - "single-table data origin" (assumes anchoring on one table
     suffices; reality: critical signals live in a different table)

2. **Verify the assumption holds for THIS case.** The fact that
   "spread-width often is threshold-based" doesn't mean "this
   specific candidate's spread-width is threshold-based." Test the
   premise before testing the conclusion.

3. **Test before shipping.** If the conclusion suggests a code
   change, verify the code path actually runs as the conclusion
   assumes BEFORE shipping. Today's STOP at the verification step
   caught instance 4.

#### Diagnostic-prompt convention

When drafting investigation prompts that lead to fix prompts:

- Have the investigation prompt state: "the conclusion assumes X.
  Verify X before treating the conclusion as actionable."
- Have the fix prompt include an explicit STOP-and-verify step that
  reads the code path the conclusion names — not as ceremony, as
  H12's load-bearing safety check.
- Treat the verification step itself as a doctrine instance: even
  when it produces "no, the conclusion holds," that's signal worth
  noting in synthesis. False-alarm refutations have value (H8
  doctrine note).

#### Relation to existing doctrine

- **H8 (false-alarm verification discipline):** covers "verify
  hypothesis before acting." H12 sharpens H8 by naming the specific
  failure mode where verification can pass on surface evidence yet
  miss the baseline assumption. H8 + H12 together: "verify both the
  evidence AND the baseline."
- **H11 (status-check methodology):** instance 1 of H12 is the
  origin of H11. H11 is the specific corrective for one sub-shape
  (wrong-baseline framing in status checks).
- **H9 (verified-write across wrapper chains):** structurally
  similar pattern — the "wrong baseline" in H9 is "wrapper return
  value reflects side effect," and the verification disposition is
  similar (verify the side effect, not the wrapper claim).

#### When this fires

H12 applies whenever a diagnostic:
- Identifies a specific code line / config / data point as causal
- Generalizes from a known pattern to a new context
- Assumes a temporal / structural / behavioral model that wasn't
  separately verified

If the diagnostic involves "this works like X, therefore Y"
reasoning, verify the "works like X" claim explicitly for the
current case.

#### Origin

2026-05-12 backlog observation codifying 3-instance pattern with
"4th instance with new sub-shape" as promotion criterion.
2026-05-13 KO H7 spread-width attribution provided that 4th
instance. Promotion to doctrine concurrent with Option A revert
(reverting Path A's universe-widening experiment that produced
the empirical data revealing instance 4).

### H13 — Parallel architectures without integration

When two complete subsystems exist that should be connected, the
integration seam itself can be the bug. Each subsystem in isolation
appears correct; their handoff is what's missing or wrong.

Distinguishing signal: the **writer** of some piece of state and the
**consumer** of that state exist independently. Nothing reads what the
writer wrote; nothing writes what the consumer reads.

This is distinct from H9 (verified-write across wrapper chains): H9 is
about a single producer → wrapper(s) → consumer flow where intermediate
layers swallow signal. H13 is about two complete flows that should be
one.

**Origin instance: 2026-05-18 #62a-D1.** `policy_lab_evaluator.py`
runs daily and writes `promoted_at` on promotion-eligible cohorts;
`fork.py:67` hardcoded `cohort_name = "aggressive"` and never read
`promoted_at`. Two complete-but-unwired subsystems. The fix was
mechanical (~half day): a small `get_current_champion` helper that
reads `promoted_at` (with a defensive fallback to "aggressive" for
transition windows), plus a DB migration aligning `promoted_at` with
operator intent, plus rewrites of two adjacent silent-failure query
sites (`_get_champion_portfolio` and `_resolve_position_cohort` path 3)
that had been authored under the same assumed-but-never-built
`is_champion` integration model.

**Diagnostic:** when investigating a feature that's "complete but not
working," check whether the data flow ends where it should. If the
writer's output isn't read by anyone, or the consumer's input isn't
written by anyone, the integration seam is the bug.

**Mitigation:** when introducing a new producer → consumer pair,
write an integration test that exercises the full path end-to-end.
The H9 AST gate catches wrapper-drift (single-flow signal loss); a
similar integration-completeness check could catch parallel-
architecture-drift, but is not yet codified. Until then: review the
seam explicitly during architecture review, not just each subsystem
in isolation.

**Numbering note:** the original #62a-D1 backlog framing called this
"H12 candidate" before H12 was claimed by the framing-artifact
discipline doctrine (codified 2026-05-13). Numbered H13 here per
codification order, not per discovery order.

## Valid silent-failure patterns

Not all exception swallowing is a doctrine violation. The following
patterns are CORRECT and should not be flagged in code review:

### Valid 1 — Re-raise after wrapping

```python
try:
    external_call()
except ProviderError as e:
    raise InternalServiceError("provider unavailable") from e
```

Re-raise (with optional wrapping) is option 1 of the doctrine. Always
acceptable.

### Valid 2 — Input validation with typed exception

```python
try:
    parsed = json.loads(payload)
except json.JSONDecodeError as e:
    return JSONResponse({"error": "invalid_payload"}, status_code=400)
```

Expected error mode → typed handling → caller-visible error response.
No alert needed because the failure is a known boundary condition.

### Valid 3 — Cache miss with default

```python
try:
    cached = redis.get(key)
except redis.RedisError:
    cached = None  # Cache miss; recompute below
```

Cache failures are routine and the fallback (recompute) handles them
correctly. Per the decision tree: "is the data path consumed?" Yes,
but the fallback IS the consumption. No silent corruption.

### Valid 4 — Final fallback in chain after structured log

```python
try:
    primary_result = primary_source.fetch()
    return primary_result
except PrimaryError:
    logger.exception("primary_failed_falling_back_to_secondary")
    try:
        return secondary_source.fetch()
    except SecondaryError:
        # Both sources failed; alert and return safe default
        alert(supabase, alert_type="all_sources_failed", ...)
        return safe_default
```

Multi-source fallback chains are acceptable as long as the FINAL
failure produces an alert. Intermediate fallbacks log without
alerting because each is an "expected partial failure."

### Valid 5 — Alert-write recursion prevention

```python
try:
    supabase.table("risk_alerts").insert({...}).execute()
except Exception:
    logger.exception("alert_write_failed", extra={...})
```

The bare `except` around an alert insert is acceptable. We've
exhausted reasonable observability options; recursing into another
alert insert would loop. Logger captures the failure.

### Valid 6 — Test code

Tests, mocks, and fixtures may swallow intentionally to assert specific
failure modes. The doctrine applies to runtime production code only.

### Valid 7 — Idempotency check / "may already exist"

```python
try:
    supabase.table("foo").insert({...}).execute()
except UniqueViolation:
    pass  # Row already exists; idempotent operation
```

Expected uniqueness violations on idempotent inserts are correct
silent handling. Add a comment explaining the idempotency contract.

## Edge cases and caveats

- **Alert-write failure.** When `risk_alerts.insert()` itself fails
  (DB unreachable, FK violation), fall back to `logger.exception` with
  full structured fields. **Do not recurse.** Outer-scope `try` around
  the alert insert with bare `except: pass` is acceptable here
  precisely because we've exhausted reasonable options. (See Valid 5.)
- **Severity drift.** Don't pile on `critical` for everything —
  reserve it for force-close failures, ledger-vs-broker divergence,
  hard data corruption. `warning` covers most "unexpected but
  recoverable." `info` is for "expected-but-noteworthy."
- **Throttling in tight loops.** If a per-iteration call fails 100×
  per scan (e.g., per-symbol Polygon failures during an outage), don't
  write 100 `risk_alerts`. Aggregate: count + symbol list in metadata,
  one alert per scan. Check if the path's caller is iterating before
  picking per-iter vs aggregated.
- **Test code.** Tests don't follow the doctrine; mocks and fixtures
  may swallow intentionally to assert specific failure modes. The
  doctrine applies to runtime production code only.
- **Dead code.** Don't add observability to code that has zero
  active callers or is in a feature-flag-off subsystem (Replay,
  AUTOTUNE, dead nested writer). Delete instead. The doctrine is
  about live failure modes.

## Reference implementation: `alert()` helper

The canonical shape for writing `risk_alerts` under this doctrine:

```python
def alert(
    supabase,
    *,
    alert_type: str,
    message: str,
    severity: str = "info",  # info | warning | critical
    metadata: dict | None = None,
    user_id: str | None = None,
    position_id: str | None = None,
    symbol: str | None = None,
) -> None:
    """Write a risk_alert. On alert-write failure, fall back to
    logger.exception. Never raises.

    Per Loud-Error Doctrine v1.0.
    """
    try:
        supabase.table("risk_alerts").insert({
            "user_id": user_id,
            "alert_type": alert_type,
            "severity": severity,
            "message": message[:500],  # cap length
            "metadata": metadata or {},
            "position_id": position_id,
            "symbol": symbol,
        }).execute()
    except Exception:
        logger.exception(
            "alert_write_failed",
            extra={
                "intended_alert_type": alert_type,
                "intended_severity": severity,
                "intended_message": message[:200],
            }
        )
```

This helper SHOULD be the standard way to write `risk_alerts` in code
affected by this doctrine. Anti-pattern fixes should reference this
function rather than re-implementing the insert+fallback pattern.

**Location:** `packages/quantum/observability/alerts.py`
(matches existing `packages/quantum/observability/` package
convention).

Phase 2 PR `#72-H1` (`equity_state` envelope-skip) is the natural
place to introduce this helper, since it's the first
doctrine-application PR.

## Migration plan

| Phase | Window | Scope |
|---|---|---|
| **Phase 1 — Doctrine + catalog** | This week | Doctrine ratified; catalog of ~242 sites in CLAUDE.md backlog as `#72` sub-items. |
| **Phase 2 — HOT fixes (waves)** | Next 2-4 weeks | ~95 sites grouped into ~5 PRs by file/area. Each PR references this doctrine. |
| **Phase 3 — WARM fixes** | 1-2 months | ~85 sites in handler family; shared `notes_to_risk_alerts` helper as the unifying primitive. |
| **Phase 4 — COLD touch-ups** | Eventual | ~50 sites; only patched on-touch when adjacent code is modified. |

Each fix PR description must reference the doctrine version (e.g.
"Loud-Error Doctrine v1.0 anti-pattern 1") so the discipline is
auditable across the migration.

Future code reviews should ask: **"does this conform to the loud-error
doctrine?"** as a standard checklist item.

## How to add new patterns

The doctrine evolves; the principle is stable. When a new
silent-failure shape is discovered:

1. Append it as a new anti-pattern (numbered ≥7) in this document.
2. Bump version (v1.0 → v1.1).
3. Add the discovered site to the CLAUDE.md catalog with the new
   pattern tag.
4. Reference both the new pattern and the version bump in the
   discovery PR's description.

The principle (re-raise / alert / structured-log) stays at v1; only
new anti-pattern shapes drive minor-version bumps.

---

## Appendix — Doctrine observation summary (2026-05-12)

Five doctrine-class observations surfaced across multiple
diagnostics on 2026-05-12 (CSX trade-absence + worker verification
+ MTM-staleness + #62a-D1 sub-investigation). Consolidated here for
future design review. Each is captured in its own section above or
in `docs/backlog.md`; this appendix is the cross-reference index.

### 1. H9 wrapper-drift (5th confirmed instance class)

Five concurrent or near-concurrent instances this week, all
sharing the producer → wrapper → consumer silent-degrade shape:

| # | Cascade | Closure |
|---|---|---|
| 1 | PR-A `iv_daily_refresh` (7-layer) | PRs #899, #901, #903, #905, #906, #907 |
| 2 | Issue B CSX close-order rejection (4-layer) | PR #908 |
| 3 | PR #864 `alpaca_client` field-drop | PR #864 + #865 (consumer fallback alert) |
| 4 | #62a-D5 / #117 DROPPABLE shim | PR #912 + #117 backlog |
| 5 | MTM-staleness silent-skip (this morning) | PRs #919 (alert + observability column) + #920 (broker fallback) |

H9 doctrine catalogued at section above. Class-prevention work
proposed in PR #916 (H9 ratification PR).

### 2. Intent drift across encodings (3rd instance class — distinct from H9)

Distinct from wrapper-drift: this class describes mismatches
between intent encoded in different artifacts (migrations vs code,
docs vs implementation, framing-as-X vs operationally-Y), not
information lost between layers of a single data flow.

| # | Instance | Encoding mismatch |
|---|---|---|
| 1 | #62a-D1 (yesterday) | 4-way encoding map: migration intent ≠ live code ≠ DB state ≠ operator intent |
| 2 | MTM staleness (this morning) | Documented behavior ("refresh on read") ≠ actual (silent-skip on incomplete snapshot) |
| 3 | 3-layer cascade (this evening) | Ghost reconciliation framed as "data hygiene" but operationally load-bearing for pipeline liveness |

Worth design-review discussion alongside H9 work. Currently no
doctrine entry; candidate name **H12 — Intent drift across
encodings** if the class earns its third independent instance via
a NEW finding (not retrospective relabeling of the three above).

### 3. Status-check structural requirement (H11, captured)

- Operator's framing is hypothesis, not investigation boundary
- Critical/high severity `risk_alerts` must be queried independently
  as baseline section in every operational diagnostic
- Captured as **H11** doctrine entry above; applies to all future
  diagnostic prompts

### 4. H8 false-alarm verification discipline (H8 extension, captured)

- Hypothesis-generation produces real value even when refuted by
  verification
- Verification cost (5-10 min) < false-action cost in both
  directions
- Today's PR #908 H8 hypothesis: false-alarm caught cleanly via
  verification procedure
- Confirmed instance table updated under H8 doctrine entry above

### 5. Cascading suppression pattern (H10, captured)

- A single stale `paper_positions` row can suppress entire pipeline
  via gate cascade (suggestions_open → paper_auto_execute →
  intraday_risk_monitor)
- Reconciliation is operationally urgent, not just cosmetic
- Captured as **H10** doctrine entry above
- CLAUDE.md "Design principles" section carries the brief
  cross-reference for in-session lookup

### Why this appendix exists

Five doctrine-class findings in a single day is unusual. The
appendix prevents the consolidation work from being lost in
session context. Two of the five (intent drift, possible H12) are
NOT yet ratified as doctrine entries — they need a third
independent instance to earn the class-elevation. The other three
(H10 cascade-suppression, H11 status-check baseline, H8 false-alarm
extension) shipped as durable doctrine entries above in this same
PR.

Future design review (likely the Monday wrapper-drift session
already scheduled in CLAUDE.md active focus #2) is the natural
forum to discuss: which class-prevention infrastructure earns
priority next, and whether the H12 candidate has accumulated
enough instances to elevate to ratified doctrine.
