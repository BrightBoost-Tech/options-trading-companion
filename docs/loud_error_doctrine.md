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

- Grep test asserting wrappers in `packages/quantum/brokers/`
  forward upstream objects rather than hand-building return dicts
  (catches future Anti-pattern 8 reintroduction).
- Convention enforcement via pyright/mypy: wrapper return types
  must be unions like `Result[T, E]` or `Optional[T]` with
  documented success/failure semantics, not bare `Dict[str, Any]`
  that lies about success.

#### Origin

2026-05-04 → 2026-05-10 cascade week. PR-A's 7-layer cascade was
the headline; Issue B + #62a + #117 + #864 are the concurrent data
points that elevate this from "interesting incident" to
"architectural class." Adding this as H9 captures the synthesis
while it's fresh — the operator-side question for Monday review is
**which class-prevention infrastructure to ship next** (the AST/
wrapper-grep/type-narrowing candidates above), not whether the
class is real.

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
