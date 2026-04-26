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

**Suggested location for the helper:**
`packages/quantum/services/observability.py`

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
