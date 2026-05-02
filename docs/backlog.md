# Backlog

This file is the durable home for backlog items. CLAUDE.md references this file but does not duplicate its contents.

Last migrated from CLAUDE.md: 2026-04-28.

---

## Backlog (post-promotion)

**#65 — Revive `policy_lab_eval`** (HIGH) — **CLOSED 2026-04-26**
Resolved by PR #807 (ImportError fix) + PR #808 (schema-drift fix +
per-cohort observability), merged 2026-04-26 06:15:54Z. First
successful canary populated `policy_daily_scores` with 3 rows at
2026-04-26 06:19Z. Final end-to-end verification pending Monday
2026-04-27 16:30 CT scheduler fire.

**#66 — Polygon Tier 1: dead-code deletion** (LOW)
Remove `packages/quantum/polygon_client.py` (zero non-test callers) and
`market_data.py:_get_option_snapshot_api` (deprecated). Single PR, no
functional change.

**#67 — outcome_aggregator dead-code removal** (LOW)

CORRECTED 2026-04-26: `outcome_aggregator.py` is dead code. Verified:
- `outcomes_log` table empty for all time (zero rows ever).
- No scheduler entry, no GHA workflow, no FastAPI endpoint.
- Only caller is CLI script `scripts/update_outcomes.py` (never run
  in production).
- `calibration_service` reads `learning_feedback_loops`, NOT
  `outcomes_log`.
- 6 test files already marked `@pytest.mark.skip` with reference to
  Cluster I deletion (PR #9 / issue #770).

Saturday 2026-04-25's Diagnostic B premise that this corrupts the
calibration loop was wrong. Hardening was unnecessary.

Action: fold into the dead-code removal sweep already in Priority 3
("Dead-code sweep: v4 accounting ledger, outcomes_log chain, ...").

Cleanup scope:
- Delete `packages/quantum/services/outcome_aggregator.py`
- Delete `packages/quantum/scripts/update_outcomes.py`
- Delete `log_outcome()` from `packages/quantum/nested_logging.py`
- Update `system_health_service.py:95` and `capability_service.py:34`
  to use `learning_feedback_loops` or remove the checks
- Drop `outcomes_log` table via migration (already in Priority 3
  drop-unused-tables list)
- Delete the 6 already-skipped test files

Keep priority LOW. This is hygiene, not safety.

**#68 — Polygon Tier 2: universe_service migration** (LOW —
post-upgrade)

Replace `get_historical_prices` and `get_iv_rank` with Alpaca
equivalents. Original 429-elimination justification resolved by
2026-04-27 Polygon plan upgrade — `universe_service` calls are
no longer rate-limited or 403-blocked. Remaining value is
provider redundancy (vendor lock-in mitigation) and SIP-fallback
viability if live Alpaca account unlocks SIP entitlement (#88).
Reactivate if Polygon billing changes materially or if live
Alpaca SIP becomes available. Effort: ~half day. Priority: LOW —
defer.

**#69 — Polygon Tier 2: market_data.py base-layer migration**
(LOW — post-upgrade)

Foundational refactor for stock bars and quotes via Alpaca.
Original "unlocks downstream cutovers" motivation now optional
post-2026-04-27 Polygon plan upgrade. Remaining value is
provider redundancy. Reactivate as a prerequisite if #68 is
reactivated. Effort: ~1 day. Priority: LOW — defer.

**#70 — Polygon Tier 3: HARD_TO_REPLACE strategy** (LOW —
permanent residual post-upgrade)

`get_ticker_details` (sector, market_cap), `get_last_financials_date`
(earnings ±90d), and `I:VIX` historical bars have no Alpaca
equivalent. Plan upgrade (2026-04-27) makes the Polygon dependency
durable; Supabase-cache patterns for the first two are still
worthwhile to reduce per-cycle Polygon calls (overlaps with
#87b). The `I:VIX` dependency is permanent; document and accept.
Effort: rolled into #87b for the cacheable subset. Priority: LOW.

**#71 — RQ dispatch migration for synchronous task endpoints** (MEDIUM)
Audit `packages/quantum/public_tasks.py` and `internal_tasks.py` for
handlers that run work synchronously instead of dispatching to RQ.
Pattern surfaced from `policy_lab_eval` diagnostic 2026-04-26: the
endpoint ran synchronously, didn't `enqueue_job_run`, produced no
observability trace. Migrate affected handlers to the `enqueue_job_run`
pattern matching reliable peers. Effort: medium (audit + 1 PR per
affected endpoint). Source: 2026-04-26 morning diagnostic.

**#93 — deployable_capital reads stale Plaid CUR:USD +
paper_autopilot status bypass** (HIGH, FIXED in PR #850)

`cash_service.get_deployable_capital()` previously computed
deployable as `buying_power - cash_buffer - reserved_capital`
where buying_power read from `portfolio_snapshots` (Plaid-sourced)
and reserved_capital was `SUM(sizing_metadata.capital_required)
WHERE status='pending'`. Both inputs were sources of drift.

**Original framing (PR #847 #93 entry) was wrong.** The first
diagnostic attributed the $208 reading to within-day cohort
clone accumulation. Today's diagnostic (2026-05-01) verified
zero cohort clones exist in DB history across all users — D4
sequence is shipped but clone INSERT silently fails (see #97).
Real root cause:

1. portfolio_snapshots last write was 2026-03-26 (5+ weeks
   stale Plaid CUR:USD = $247.84)
2. paper_autopilot status update at line 457 silently bypassed
   for BAC source row (see #96)
3. Net: yesterday's $208 = $500 paper_baseline_floor - $292 BAC
   reservation OR $247.84 stale buying_power, depending on
   fallback path

**Fix shipped (PR #850, 2026-05-01):** replaced
`cash_service.get_deployable_capital` body to read Alpaca
`options_buying_power` directly via new helper
`equity_state.get_alpaca_options_buying_power(user_id)`. Same
architectural pattern as 2026-04-16 `_compute_weekly_pnl` fix
(commit 83872db) — DB-derived state diverging from broker truth
resolved by reading Alpaca-authoritative.

**Verification (2026-05-01 16:00 UTC cycle):**
deployable_capital=$500 (vs prior days' $208/$247.84), budget
cap=$450, no helper failures. Verified working.

**Status:** CLOSED. Both layers fixed; broker-truth read makes
stale Plaid + reservation arithmetic irrelevant. Phantom-row
accumulation continues but is operationally inert (#94).

**#94 — trade_suggestions phantom-row hygiene** (P3-P4)

Source suggestions miss transition on position-close (stay at
`staged` post-execution). Cohort clones from `policy_lab/fork.py`
cannot accumulate — they fail INSERT silently (see #97). Daily
`suggestions_close` cleanup transitions stale `pending` rows
older than today's cycle_date to `dismissed`, but only catches
cross-day rows.

Currently inert post-#93 (broker-truth budget ignores all row
statuses) but rows accumulate indefinitely in the table.

**Risk:** table size growth without bound; no immediate
operational impact post-#93.

**Options:**
- (a) periodic deep-cleanup job (weekly/monthly, archives
  `dismissed`/`staged` rows older than N days)
- (b) extend close-path to transition source rows to terminal
  state (`closed`, `expired`, etc.)
- (c) post-#97 fix, add cohort-clone cleanup at shadow fill
  materialization

**Effort:** small (~half day for option a; ~1 day for b/c with
proper close-path discipline).

**Priority:** P3-P4. Defer until table size becomes operational
issue or close-path discipline becomes load-bearing for future
feature.

**#95 — fork.py threshold semantic mismatch** (HIGH, PARTIAL
FIX in PR #851)

`_filter_for_cohort` at fork.py:165 originally read
`risk_adjusted_ev` (0-2 ratio) and compared against
`min_score_threshold` (50/70 score-scale). Conservative +
neutral cohorts produced 0 clones for entire DB history across
all users (verified 2026-05-01). D4 sequence (PR2a/PR2b/PR3)
was shipped but operationally inert.

**Fix shipped (PR #851, 2026-05-01):**
1. workflow_orchestrator.py:2961 — persist `score` into
   sizing_metadata at suggestion-insert time
2. fork.py:165 — read `sizing_metadata.score` instead of
   `risk_adjusted_ev` for cohort threshold comparison

**Partial verification (16:00 UTC cycle 2026-05-01):**
- score=76.9 persisted correctly in sizing_metadata ✓
- Filter accepted BAC for all 3 cohorts (per policy_decisions) ✓
- But Policy Lab fork result: {'conservative': 0, 'neutral': 0,
  'aggressive': 1} — clone INSERT silently failed (see #97)

**Status:** Score persistence verified. Filter logic verified.
Clone INSERT path still broken — keep open until #97 fix
resolves end-to-end clone production.

**#96 — paper_autopilot status update silently bypassed**
(MEDIUM, reproduced 2x in 24h)

paper_autopilot_service.py:457 attempts to transition
trade_suggestions.status from 'pending' to 'staged' after
autopilot stages a suggestion for execution. The update is
wrapped in try/except at lines 460-471 that swallows status-
update failures with logger.warning, no DB-visible alert.

**Reproduced occurrences:**
- 2026-04-30: BAC source row stayed 'pending' despite autopilot
  firing and creating position
- 2026-05-01: BAC source row stayed 'pending' again, same shape

**Mechanism unclear:** bypass could be exception, async race,
transaction isolation issue, or routing through non-autopilot
path entirely. Needs Railway log inspection at the swallow site
+ audit of autopilot status-transition lifecycle.

**Operational impact:**
- Pre-#93: contributed to phantom reservations in
  cash_service.get_deployable_capital
- Post-#93: operationally inert (broker-truth budget ignores
  'pending' rows)
- Still affects observability — operator can't track which
  suggestions actually executed by status alone

**Recommended fix:** add critical alert at the swallow site
per H5 doctrine. Identify whether failure is exception or
no-op-success-but-no-state-change. ~half day investigation,
~half day fix.

**Priority:** MEDIUM. Promoted from MEDIUM-LATENT after
second occurrence today.

**#97 — fork.py clone INSERT silent failure** (HIGH, blocks
#95 verification)

Filter at fork.py:165 ACCEPTS BAC for all 3 cohorts (verified
via policy_decisions empty reason_codes 2026-05-01). But INSERT
at fork.py:123 silently fails for non-aggressive cohorts. The
try/except at fork.py:118-129 swallows the error with only
`logger.warning("policy_lab_fork_clone_error: ...")`, no
DB-visible alert.

**Likely causes (untested):**
- Missing NOT NULL field in `_clone_suggestion_for_cohort`
  return dict (e.g., lineage_version)
- Unique constraint hit (e.g., (user_id, ticker, cycle_date,
  cohort_name) collision)
- Schema drift between clone shape and trade_suggestions table

**Diagnostic needed:** Railway log inspection at the swallow
site to see actual exception. Once root cause known, fix is
likely small (add missing field, adjust constraint, or fix
schema).

**Architectural note:** the swallow-with-warning pattern at
fork.py:118-129 is the same shape as #98's H5a coverage gap.
Should add critical alert at the swallow site per H5 doctrine
as part of the fix.

**Operational impact:** entire D4 sequence (PR2a routing gate,
PR2b shadow fill simulation, PR3 clone-builder fix) is shipped
but operationally inert until this fixes. Conservative +
neutral cohorts produce zero comparison data.

**Effort:** ~half day investigation + small fix; depends on
actual exception cause.

**#98 — needs_manual_review observability gap** (HIGH,
PARTIAL FIX in PR #853)

On 2026-05-01 16:45 UTC, BAC close order rejected by Alpaca
3x with "insufficient options buying power" (required $296,
available $204). `submit_and_track` at
alpaca_order_handler.py:226-242 marked order
status='needs_manual_review' and returned dict (did NOT raise).
H5a alert at paper_exit_evaluator.py:1226 only fires for raised
exceptions, so silent. Operator discovered ghost position 5+
hours later.

**Fix shipped (PR #853, Option C):** loud alert at
submit_and_track:231 immediately when marking
status='needs_manual_review'. Catches ALL callers (not just
paper_exit_evaluator) within seconds.

**Defense-in-depth deferred (Option B):** expand
ghost_position_sweep to detect stale `needs_manual_review`
orders linked to open positions. ~half day. Catches any
needs_manual_review write that escapes Option C's alert path.
Defer until Option C verifies in production with no recurrence.

**Status:** Option C shipped. Option B follow-up queued.

**Underlying architectural cause:** see #100. The close
rejection happened because sizing didn't check round-trip BP.
Option C addresses observability; #100 addresses prevention.

**#100 — round-trip BP check at sizing** (HIGH, IN PROGRESS)

Sizing logic at sizing_engine.py:102 only checks
`contracts_by_collateral = floor(account_buying_power /
collateral_required_per_contract)`. No second-pass check that
`account_buying_power - entry_cost ≥ exit_cost_estimate`. The
system can size into trades it cannot safely close.

**Today's incident (2026-05-01) is the proof:** BAC entry took
$292 of $500 OBP, leaving $204. Alpaca's close-side margin gate
required $296. Position stuck open at broker for 5+ hours.

**Design doc complete:** docs/designs/option_a_round_trip_bp.md

**Implementation in progress (Saturday-Sunday 2026-05-02 to 03):**
- New helper `estimate_close_bp(legs, strategy_type,
  entry_premium)`
- Formula A (entry-premium-based): for *_DEBIT_SPREAD,
  estimated_close_bp = max_loss_per_contract
- Sizing engine adds 4th dimension: contracts_by_round_trip
- safety_factor=1.1 starting calibration with revision plan
- Single new kwarg at workflow_orchestrator.py:2643
- Test surface: 3 source-level + 9 helper behavioral + 7 sizing
  integration + 1 regression query

**Effort refined:** ~half day (was originally estimated 1-2
days; Formula A eliminates Alpaca quote integration burden).

**Verification path:** regression query against last 30 days
informs calibration; Monday 2026-05-04 paper-mode cycle
validates integration; Tuesday's live cycle confirms in
production.

**Architectural note:** future multi-cohort live routing (#65
`policy_lab_eval`) may need reservation semantics to prevent
simultaneous-cohort competition for live capital. Not today's
problem.

**#101 — STRATEGIES_ALLOWLIST env knob** (MEDIUM, optional
kill-switch)

Environment variable to restrict scanner emission to specific
strategy types. Useful as kill-switch during incidents (e.g.,
"single-leg only after BP-to-close issue") without code
changes.

**Default:** unset (current behavior — all strategies allowed)

**Format:** comma-separated strategy names, e.g.,
`STRATEGIES_ALLOWLIST=long_call,long_put`

**Implementation site:** scanner gate in options_scanner.py,
early-return before strategy emission if not in allowlist.

**Priority:** MEDIUM. Currently inert because Option A (#100)
addresses the use case structurally. Worth keeping as separate
backlog item for incident-response flexibility.

**Effort:** half day (env var read + scanner gate + tests).

**#102 — Round-trip safety as sizing invariant** (DOCTRINE)

Add to design principles document (CLAUDE.md or
docs/design_principles.md):

> "Sizing must verify the position can be safely round-tripped
> within available buying power, not just that entry fits. For
> any multi-leg strategy where close requires fresh BP (debit
> spreads, iron condors, etc.), sizing must reserve sufficient
> headroom for the close-side margin requirement."

Companion to existing principle "tune thresholds, not strategy
availability." This principle complements it: when an account
cannot safely round-trip a strategy, the answer is sizing
rejection, not strategy disablement.

**Status:** to be added during #100 implementation PR.

**#103 — Regime → strategy selection breadth audit** (LOW)

100% of recent live trades (last 14 days) are
LONG_CALL_DEBIT_SPREAD. Code supports more types (iron_condor
function exists at options_scanner.py:1053+) but production mix
is single-shape.

Possibilities:
- Regime-driven natural selection (NORMAL regime favors debit
  spreads): correct behavior
- Coverage gap in strategy emission logic: bug
- Threshold calibration too narrow for non-debit-spread
  strategies: configuration

**Investigation needed:** survey strategy emission across all
regimes (NORMAL, ELEVATED, CONTRACTION) over historical data.
Verify other strategies are reachable in their appropriate
regimes.

**Priority:** LOW. Architectural curiosity, not operational
blocker.

**Effort:** ~half day investigation. Fix scope depends on
findings.

### #72 — Loud-error doctrine + silent-failure catalog

**Phase 1 (doctrine + catalog) complete 2026-04-27.**

Doctrine document: `docs/loud_error_doctrine.md` (v1.0).

**Audit summary:** ~242 silent-failure sites in production
(`packages/quantum/`).

| Pattern | Count |
|---|---:|
| P1 (`try/except: pass`) | ~38 |
| P2 (log-only swallow) | ~165 |
| P3 (`@guardrail`) | 9 |
| P4 (endpoint silent) | ~14 |
| P5 (env-var branch) | ~7 |
| P6 (bare `except`) | ~9 |

| Path heat | Count |
|---|---:|
| HOT (every-trade / every-scan) | ~95 |
| WARM (daily/weekly scheduler) | ~85 |
| COLD (manual / on-demand UI) | ~50 |
| DEAD (gated off; fold into existing dead-code sweeps) | ~12 |

#### #72-Phase 2 — HOT fixes (next 2-4 weeks, ~5 PRs)

- [x] **#72-H1 — `equity_state.py` envelope-skip alert + introduce
      `alert()` helper.** **CLOSED 2026-04-26 by PR #817.** Helper
      shipped at `packages/quantum/observability/alerts.py` (canonical
      location, not `services/observability.py` as originally drafted —
      matched existing `observability/` package convention). Sites
      `services/equity_state.py:_fetch_alpaca_equity` and
      `_fetch_alpaca_weekly_pnl` now write `risk_alerts` on Alpaca
      failure with `alert_type='equity_state_alpaca_account_failed'` /
      `'equity_state_alpaca_portfolio_history_failed'`.
- [x] **#72-H2 — `scheduler.py:_fire_task` HTTP error alerting.**
      **CLOSED 2026-04-26 by PR #818.** Three sites alert: signing
      failure (`scheduler_task_signing_failed`), httpx exception
      (`scheduler_task_http_error`), HTTP 4xx/5xx response
      (`scheduler_task_http_status_error` with response body capped at
      2000 chars). Lazy-singleton supabase client with sentinel
      (`_SUPABASE_INIT_ATTEMPTED`) prevents log spam during sustained
      Supabase outages. (Sentinel later relocated to
      `observability/alerts.py` as `_ADMIN_INIT_ATTEMPTED` per #72-H3.)
- [x] **#72-H2a — `_retry_failed_jobs` ImportError fix + doctrine alert.**
      **CLOSED 2026-04-27 by PR #821.** Function had been silently
      broken since at least 2026-01-10 (3.5+ months) due to
      non-existent `packages.quantum.database` import. Fix swapped to
      canonical `get_admin_client` from
      `packages/quantum/jobs/handlers/utils.py`. Outer except now writes
      `auto_retry_scan_failed` alert per Loud-Error Doctrine v1.0.
      Post-deploy expectation: 5 stuck `failed_retryable` rows will
      progress to `dead_lettered` within ~24h, producing 5
      `job_dead_lettered` `risk_alerts`. Each surfaces a separate
      pre-existing root cause (alpaca_order_sync pytz, alpaca_order_sync
      missing user_id arg, paper_auto_execute trade_suggestions.score
      schema drift, validation_eval StrategyConfig JSON serialization
      ×2). Diagnosis of each underlying issue queued as #76–#79 once
      the dead-letter alerts confirm the failures still reproduce.
- [x] **#72-H3 — `@guardrail` decorator alerts + shared admin
      singleton.** **CLOSED 2026-04-27 by PR (this commit).**
      Decorator-level fix: both fallback paths now write alerts.
      Path A (circuit OPEN) → `{provider}_circuit_open`; Path B
      (retries exhausted) → `{provider}_retries_exhausted`. Metadata
      captures `provider`, `function_name`, args (repr-truncated,
      self-skipped via qualname heuristic), plus path-specific
      fields. Bonus scope: extracted shared `_get_admin_supabase()`
      helper into `observability/alerts.py` and migrated
      `scheduler.py` away from its local singleton — future modules
      adopting the doctrine pattern import from
      `observability.alerts` rather than reinventing.
- [x] **#72-H4a — `workflow_orchestrator.py` trade-decision safety.**
      **CLOSED 2026-04-27 by PR (this commit).** Group A from H4
      diagnostic. Sites `2158` (envelope check) and `2196` (ranker
      positions fetch) now write `risk_alerts` on failure. New
      `alert_type`s: `workflow_envelope_check_failed`,
      `workflow_ranker_positions_fetch_failed`. Establishes the
      `consequence` metadata field convention for `workflow_*`-class
      alerts (which continue silently after the catch, so the
      consequence isn't obvious from `alert_type` alone). Tests use
      source-level structural assertions + `ast.parse` syntax
      validation rather than runtime imports (avoids heavy
      dependency tree).
- [x] **#72-H4b — `workflow_orchestrator.py` calibration data
      integrity.** **CLOSED 2026-04-27 by PR (this commit).** Group B
      from H4 diagnostic. 4 sites covered with new alert_types:
      `workflow_morning_cal_apply_failed` (site 1654, single-fire),
      `workflow_budget_extraction_failed` (site 2076, single-fire,
      bare-except renamed), `workflow_midday_cal_prefetch_failed`
      (site 2172, single-fire), `workflow_per_candidate_cal_apply_failed`
      (site ~2820, **first production use of doctrine's tight-loop
      aggregation pattern**: per-candidate failures collected during
      candidate loop, single summary alert fires after loop with
      `failed_count` + `failed_symbols` (capped at 20) +
      `distinct_error_classes`). Trade-off documented in code comment.
- [x] **#72-H4c — `workflow_orchestrator.py` audit + ancillary.**
      **CLOSED 2026-04-29 by PR #835.** Groups C+D from H4 diagnostic.
      6 sites covered (5 from original + 1 bonus mirror discovered
      during diagnostic): `paper_exit_marketdata_fetch_failed` (line
      1351, single-fire), `workflow_morning_suggestion_insert_failed`
      (1766, loop), `workflow_morning_post_insert_observability_failed`
      (1833, single-fire), `workflow_midday_progression_fetch_failed`
      (1922, single-fire async), `workflow_midday_post_insert_observability_failed`
      (3193, single-fire), `workflow_midday_suggestion_insert_failed`
      (3083, loop — bonus site outside original H4 catalog).
      34 new structural tests in `test_workflow_orchestrator_alerts.py`.

**Deferred from #72-H4 diagnostic (not in scope for any sub-PR):**

- 3 sites (lines `99`, `128`, `169`) — Replay decision-context
  recording. Replay subsystem is gated off via `REPLAY_ENABLE=0`.
  Defers to the Replay wire-up-or-remove decision queued for after
  micro_live stabilizes.
- 2 sites (lines `1131`, `1952`) — `regime_snapshots.insert(...)`.
  Defers to `#62a-D3` (table missing in production). Either the
  migration adds the table or the writes get removed; alerts here
  would be noise until that decision resolves.
- 3 sites (lines `1411`, `1843`, `2060`) — VALID patterns under
  Loud-Error Doctrine v1.0 (input parsing fallback, typed coercion
  with sentinel return, multi-source fallback chain intermediate).
  Documented as compliant for future audits. No fix needed.
- [x] **#72-H5a — `paper_exit_evaluator.py` HOT swallows.**
      **CLOSED 2026-04-30 by PR #838.** First half of #72-H5. 9 alert
      sites covered: per-condition eval (loop), cohort configs load,
      close-loop (loop), open positions fetch (safety), cohort resolve
      exhausted (collapsed 3 paths → 1 alert when all fail), routing
      query (safety), idempotency check (safety), Alpaca DRY_RUN build,
      Alpaca submit fallback to internal (CRITICAL — 2026-04-16
      ghost-position bug shape). **New convention introduced:**
      `operator_action_required` metadata field on critical-severity
      alerts; provides explicit operator runbook text. 57 structural
      tests in new `test_paper_exit_evaluator_alerts.py`.
- [x] **#72-H5b — `paper_autopilot_service.py` HOT swallows.**
      **CLOSED 2026-04-30 by PR #839.** Closes #72-Phase 2 entirely.
      10 alert sites including SAFETY-CRITICAL site 236
      (`paper_autopilot_circuit_breaker_failed`) with
      `operator_action_required` metadata, matching H5a site 9
      convention. Site 4 (lines 411+438) collapsed two-stage pattern
      sharing failures list (status_staged_update + full_execution).
      63 structural tests in `test_paper_autopilot_service_alerts.py`.
      Phase 3 (WARM, shared-helper approach) and Phase 4 (COLD,
      opportunistic) remain as future work.

#### #72-Phase 3 — WARM fixes (this month, shared-helper approach)

- [ ] **#72-W1 — Shared `notes_to_risk_alerts` helper for
      `jobs/handlers/*`.** ~15 sites across `daily_progression_eval`,
      `learning_ingest`, `paper_learning_ingest`, `iv_daily_refresh`,
      `intraday_risk_monitor`, `promotion_check`,
      `reconcile_positions_v4`, `seed_ledger_v4`,
      `refresh_ledger_marks_v4`, `report_seed_review_v4`,
      `run_market_hours_ops_v4`, `strategy_autotune`,
      `suggestions_close`, `suggestions_open`, `validation_eval`.
      Pattern: P2 (notes-list anti-pattern). Effort: ~4h for the helper
      + each handler migration.
- [ ] **#72-W2 — `paper_endpoints.py` post-fill swallow audit.**
      Sites in `_run_attribution` and `_paper_commit_fill` family.
      Pattern: P1/P2. Effort: ~half day.
- [ ] **#72-W3 — `execution_service.py` ledger-record alert.**
      Sites: `services/execution_service.py:182, 193, 256, 271, 349,
      600, 648, 661, 728`. Pattern: P1/P2. Execution-vs-ledger drift
      currently invisible. Effort: ~half day.
- [ ] **#72-W4 — `brokers/alpaca_*` watchdog alerts.** ~12 sites
      across `alpaca_order_handler.py`, `alpaca_client.py`,
      `alpaca_endpoints.py`. Pattern: P2. Effort: ~half day.
- [ ] **#72-Phase3-A — Migrate `_retry_failed_jobs` inline
      `job_dead_lettered` writes to doctrine `alert()` helper.**
      Source: deferred from #72-H2a (PR #821) — 3 inline
      `client.table("risk_alerts").insert(...)` calls in
      `scheduler._retry_failed_jobs` predate the doctrine. Migrate to
      `alert(_get_supabase_for_alerts(), alert_type='job_dead_lettered',
      severity='critical', ...)`. Stylistic refactor; no behavior
      change. Priority: LOW. Effort: ~15 min.

#### #72-Phase 4 — COLD touch-ups (eventual; on-touch only)

- [ ] **#72-C1 — `dashboard_endpoints.py` user-visible failures.**
      ~19 sites of P4 (HTTP 200 + empty payload). Effort: opportunistic;
      patch on-touch.
- [ ] **#72-C2 — Optimizer / agent / regime sub-step fallbacks.**
      Across `optimizer.py`, `analytics/regime_engine_v3.py`,
      `analytics/regime_engine_v4.py`, `agents/runner.py`. Pattern: P2.
      Touch on-modify only.

#### #72-Phase 4 — DEAD-code overlaps (no remediation; fold into existing sweeps)

- `outcome_aggregator.py` (5 sites) — already in #67.
- `nested_logging.py` (6 sites) — already in #67 (log_outcome chain).
- `services/replay/decision_context.py`, `services/replay/blob_store.py`
  (~10 sites) — gated off via `REPLAY_ENABLE=0`; fold into Replay
  evaluation backlog item.
- `analytics/walk_forward_autotune.py`, `services/walkforward_runner.py`
  (~8 sites) — `AUTOTUNE_ENABLED=false` permanently; fold into
  adaptive-caps stack removal item.
- `polygon_client.py` — already in #66.

#### #72 audit method limitations

The audit catches static patterns: `try/except`, decorator-based
swallow, endpoint-silent. It does NOT catch:

1. Methods that raise typed exceptions to a caller that itself
   swallows (the swallow shifts up one frame).
2. Async paths where the exception is captured in a Future and
   never awaited.
3. Errors that propagate cleanly but produce wrong values
   downstream (e.g., a `0` from a defaulted division leaks into
   a sizing calc — the *swallow* is correct, but the *consequence*
   is silent corruption).
4. Operations that "succeed" with a corrupted state (e.g., insert
   succeeds with NULL where downstream expects a value).

Confidence: HIGH on the ~95 HOT site list, MEDIUM on completeness
for COLD/DEAD where greppability degrades. Future drift is expected;
this catalog is a starting point, not a complete enumeration.

**#73 — Remove dead `GET /policy-lab/results` endpoint and table** (LOW)
After PR #808 (closes #65), `policy_lab_daily_results` has zero
writers. Reader at `policy_lab/endpoints.py:42-75` has zero frontend
callers (verified in `apps/web/`). Delete the route, drop the table
via migration, scrub references in CLAUDE.md. Gated on #65 fully
closed (Monday 2026-04-27 verification). Effort: ~1 hour.

**#75 — Drop `nested_regimes` table (orphan after #62a-D2)** (LOW)

Source: #62a-D2 fix on 2026-04-26 deleted `log_global_context`, the
only writer to `nested_regimes`. Table now has zero writers and
zero readers (verified during D2 diagnostic — no Python code reads
the table; no scheduler entry; no FastAPI route).

Cleanup scope:
- Migration to `DROP TABLE nested_regimes`.
- Remove the original creation migration if appropriate (or keep
  as a historical artifact).

Effort: ~30 min, single PR. Bundle with the existing "drop unused
tables" Priority 3 batch.

Priority: LOW — orphan table costs nothing, just noise.

**#74 — Remove `RISK_EQUITY_SOURCE=legacy` rip-cord from `equity_state.py`** (LOW)

Source: 83872db (2026-04-16) committed *"Kept 72h for safety;
scheduled for removal in a follow-up PR."* Now 10 days stable.

Cleanup scope:
- Remove `_estimate_equity_legacy` and `_compute_weekly_pnl_legacy`
  from `equity_state.py`.
- Remove `RISK_EQUITY_SOURCE` env-based switching logic.
- Update `.github/workflows/ci-tests.yml:24` (currently sets
  `RISK_EQUITY_SOURCE=legacy`).
- Prune legacy-branch tests in `test_equity_state_helpers.py`.

Effort: ~1-2 hours, single PR, no functional change in production
(rip-cord is unset in Railway env, defaults to `alpaca`).

**#85 — Universe price filter for micro tier** (HIGH — RESOLVED 2026-04-27)

Source: 2026-04-27 19:16 UTC manual rerun (validating PR
feat/micro-tier-90pct-single-position). With $500 capital and the
new $450 per-trade budget computing correctly, the cycle still
produced 0 suggestions because the only viable scanner output was
AMZN at $1247 underlying / $1223 max_loss/contract — which exceeds
$450 budget. ~80% of the 62-symbol universe (FAANG + high-priced
ETFs) produces uneconomic candidates.

Resolved by PR feat/85-micro-tier-universe-price-filter:
`options_scanner._apply_tier_price_filter` drops symbols with
underlying > $50 (configurable via `MICRO_TIER_MAX_UNDERLYING` env)
for micro tier only. Inserted after the batch quote fetch, before
per-symbol option-chain calls (saves Polygon API calls too).
Threshold aligns with existing 2.5-vs-5 spread-width split.

**#86 — Late-day liquidity degradation in scanner** (LOW —
informational)

Source: 2026-04-27 19:16 UTC manual rerun. BAC went from
"score=100, tradeable" at 17:10 UTC to "spread_too_wide=14.2%" at
19:16 UTC (2:16 PM CT, ~45 min pre-close). Same underlying, same
chain, same scanner — just 2 hours later in the trading day.

Operational implication: scheduled 16:00 UTC cycles (11:00 AM CT)
should not have this problem. Manual reruns close to market close
will. **Don't manual-trigger after 1:00 PM CT for testing
purposes.** Priority: LOW — informational. Tomorrow's normal
schedule is in the right window.

**#87 — Polygon 429 storm chronic** (HIGH — RESOLVED 2026-04-27)

Resolved by Polygon plan upgrade: Stocks Basic ($0) → Stocks
Starter ($29/mo) and Options Basic ($0) → Options Developer
($79/mo), total $108/mo recurring. Diagnostic-first
investigation initially framed the storm as deploy-induced cold
cache + retry amplification, but operator's plan check revealed
the true root cause: Basic tier hard-capped at 5 calls/min/product
*and* lacked entitlements for snapshot / Greeks / IV / Open
Interest endpoints (the `403 NOT_AUTHORIZED` errors on
`/v3/snapshot` for option contracts in worker logs were the
clearest signal, but my diagnostic underweighted them).

Lesson: when web-search returns "paid plans are unlimited" and
the data shows persistent 429s, the actual plan tier (free vs
paid) is the first thing to verify, not the second. The
operator's dashboard check would have shifted the diagnostic
weight in 5 minutes.

**#87a — Polygon rate limiter** (LOW — deprioritized)

Source: deferred from #87 (2026-04-27). My #87 diagnostic
proposed a client-side token-bucket rate limiter (~30 min
implementation) as a tactical guard. After plan upgrade, the
underlying need is gone — the Starter/Developer tier no longer
caps at 5/min, so bursts are safe. Consider during a future
defensive-engineering pass (belt-and-suspenders against future
plan downgrades or unexpected provider throttling), but not
urgent.

**#87b — `scanner_universe` metadata backfill** (MEDIUM — RESOLVED 2026-04-28)

**RESOLVED via operational fix — no code change required.**
Universe_sync trigger run on 2026-04-28 (post-Polygon-upgrade)
populated metadata for all 62 symbols. Pre-state: 9/62 scored.
Post-state: 62/62 scored, 62/62 with avg_volume_30d, 62/62 with
iv_rank. Sync ran in 26s vs 145s pre-upgrade (6× speedup
confirmed Polygon plan upgrade unblocked the helper calls).

Underlying issue: pre-upgrade Polygon Basic-tier rate limits
caused per-symbol metric-fetch failures to cascade silently
through the sync loop (each symbol's exception caught + skipped).
Post-#87 plan upgrade removed the rate cap; a manual sync trigger
populated everything. Audit-trail row in
`risk_alerts.alert_type='universe_sync_backfill'` (id
`6b9430d1-215e-4539-81dc-2497f029a7ed`).

Code-shape concerns (originally listed as part of #87b — sync
schedule cadence, on-failure alerts) deferred to #72-W phase or
follow-up. Operational state is now correct.

**#88 — Verify Alpaca options data access** (LOW)

Source: 2026-04-27 Polygon plan upgrade follow-up (#87
resolution). Today the Alpaca SIP fallback failed for live cycles
(`subscription does not permit querying recent SIP data` errors
on equity bars). Worth understanding what the live Alpaca account
provides as a backup data source — equity SIP, options snapshots,
options Greeks, etc. — but no longer urgent with the Polygon plan
upgrade covering the primary path. Verify on the Alpaca dashboard
whether the live account is entitled to SIP data and options
snapshots; document findings in this entry, then decide whether
to wire `MarketDataTruthLayer` Alpaca-fallback paths that
currently dead-end.

Effort: ~30 min Alpaca dashboard check + ~half day to wire
fallbacks if entitled. Priority: LOW — Polygon primary now
covers the path.

**#91 — Regime-scaled universe price filter** (LOW)

(Renumbered from #88 on 2026-04-27 to honor operator's explicit
numbering of the new #88 — Alpaca options data verify entry
above. Original PR feat/85-micro-tier-universe-price-filter
commit message references "#88" — refers to this entry
pre-renumbering.)

Source: deferred from #85 design (2026-04-27). #85 ships with a
static $50 threshold. In shock-regime cycles, the $450 normal
budget collapses to $225 — but the static $50 filter still allows
BAC ($286 max_loss) through, only to be sizing-vetoed downstream.
Promote to dynamic when shock-regime cycles repeatedly produce
sizing-veto rejections of micro-tier candidates.

Implementation sketch: `threshold = 50.0 × regime_mult_for_micro`
(so $40 elevated, $25 shock). Effort: ~1 hour. Priority: LOW —
defer until evidence demands it.

**#89 — Tier-aware `RISK_MAX_SYMBOL_PCT` envelope cap** (LOW)

(Renumbered from #85 on 2026-04-27 to honor operator's explicit
numbering of universe-filter / late-day / 429 entries above.
Original PR feat/micro-tier-90pct-single-position commit message
references "#85" — refers to this entry pre-renumbering.)

Source: micro tier sizing fix (2026-04-27). The risk envelope at
`packages/quantum/risk/risk_envelope.py` enforces `RISK_MAX_SYMBOL_PCT=0.4`
(40% per-symbol cap) regardless of tier. Under micro tier with 90%
per-trade sizing, BAC at $286 = 57% of $500 capital VIOLATES the
envelope cap. Currently warn-only at the pre-entry check site
(`workflow_orchestrator.py:2186-2222`), so it logs warnings but
doesn't block. Future cleanup: tier-aware envelope cap (e.g., 1.0
for micro tier, 0.4 for standard). Effort: ~1 hour, single PR, plus
matching test in `risk_envelope` test suite. Priority: LOW —
warn-only path means no operational impact today.

**#90 — `STRATEGY_TRACK` env var cleanup** (LOW)

(Renumbered from #86 on 2026-04-27 — same reason as #89.)

Source: micro tier sizing fix (2026-04-27). With tier-aware
`RiskBudgetEngine`, `STRATEGY_TRACK` is now no-op for micro tier
(engine takes the tier branch before the risk_profile switch). Only
affects small/standard tier `per_trade_pct`. Currently set to
`balanced` on both BE and worker services in Railway. Cleanup:
remove the env from Railway (defaults to `balanced` if unset),
simplify the engine code to drop the unused branch (or keep for
small-tier conservative/aggressive override flexibility). Effort:
~30 minutes. Priority: LOW — cosmetic.

### #62a — Schema drift audit COMPLETE 2026-04-26

Audit catalog: **12 drift instances** found across 70 tables, ~1,100
columns, ~60 production write sites, 85 migrations.

The initial Saturday/Sunday findings (3 instances — PR #6 enum, #65
`policy_lab_daily_results`, `outcomes_log` cols) captured a fraction
of actual drift. The audit revealed 9 additional instances including
1 latent live-trade-routing issue and 4 broken data-collection paths
(regime persistence dead, cohort fan-out broken, execution-cost
gating dropped silently, regime_snapshots table missing).

Method limitations documented (8 false-negative classes — see
"#62a audit method limitations" below). Confidence: **HIGH on 10
actionable findings, MEDIUM on completeness.**

Catalog summary:
- **1 CRITICAL** in audit (verified DOWNGRADED to HIGH-LATENT
  after deep-dive — see #62a-D1).
- **4 HIGH** (cohort fan-out broken, regime persistence dead,
  execution-cost gating silently dropped, regime_snapshots table
  missing).
- **3 MEDIUM** (governance state, shadow_cohort_daily, legacy
  execution_service).
- **4 LOW** (rebalance flow, outcomes_log dead-code,
  symbol_regime_snapshots, OOB tables).

Status: AUDIT COMPLETE. Catalog forms the work plan for #62 proper.
Sub-items #62a-D1 through #62a-D12 below.

#### #62a-D1 — `is_champion` column missing (LATENT, HIGH)

Verified 2026-04-26: column missing from `policy_lab_cohorts`, but
autopilot has produced zero orders in 8+ days, and live routing
goes through `fork.py:67` cohort_name tag path — not through
`_get_champion_portfolio`. Not Monday-blocking.

Compounding issue: migration `20260402000000_small_account_cohorts.sql`
intends `'neutral'` as champion; live code (`fork.py:67`) hardcodes
`'aggressive'`. The two designs disagree.

**Prerequisite before fix:** resolve `'neutral'` vs `'aggressive'`
intent disagreement.

Fix scope after intent resolution:
- `ALTER TABLE policy_lab_cohorts ADD COLUMN is_champion boolean DEFAULT false`
- `UPDATE` to set `is_champion=true` on the resolved cohort.
- Decide whether `_get_champion_portfolio` should actually be
  reachable, or be deleted (the live routing stays in fork.py's
  tag-based path).
- Optional: clean up 3 orphan $500 "Main Paper" portfolios from
  2026-04-02.

Effort: ~2-4 hours after intent resolution.

#### #62a-D2 — `nested_regimes` writer deleted (CLOSED 2026-04-26)

Originally classified as HOT-HIGH "rename keys in writer". Diagnostic
revealed three layered failures: wrong column names, missing required
`timestamp` field, silent try/except. Plus zero readers anywhere
(no code, no scheduler, no FastAPI route) and zero rows ever written.

Resolution: **deleted `log_global_context`** rather than fix —
empty-table writes don't fit the loud-error doctrine emerging from
#62a/#67. Also removed dead `_get_supabase_client` helper, dead
`supabase` import in `backbone.py`, dead import in `optimizer.py`,
and three unused test mocks. Table-level cleanup tracked as #75.

#### #62a-D3 — `regime_snapshots` table missing (HOT, HIGH)

Files: `api.py:627`, `workflow_orchestrator.py:1130`, `:1951`.
Migration `20251213000000_regime_snapshots.sql` exists but never
applied. Daily morning + midday cycles attempt persistence and
fail silently.

Fix: apply migration, OR delete the writes (decide if snapshot is
needed for backtest/replay).

Effort: ~1 day if applying migration, ~1 hour if deleting writes.

#### #62a-D4 — Cohort fan-out routing safety + symbol drop fix

Status: HIGH — multi-PR architectural work, **NOT one-line fix.**

Original audit finding: clone path writes `symbol` key to
`trade_suggestions` but column is `ticker`. Single-key drop appears
trivial.

Verification finding 2026-04-26: applying the drop in current
`micro_live` mode could route conservative/neutral cohort orders to
the live broker, violating the design intent that shadow cohorts
are paper-only learning channels (operator clarification 2026-04-26:
fan-out is meant to amplify *learning* per trade — one cohort
trades real capital, others produce shadow observations that must
NEVER reach the live broker).

Current implementation conflates routing: `EXECUTION_MODE` is
global; no portfolio-level safety. Restoring shadow data flow
without routing enforcement is unsafe.

**Required sequence (3 PRs):**

**PR 1 — Add `routing_mode` column to `paper_portfolios`**
- Migration: `ALTER TABLE paper_portfolios ADD COLUMN routing_mode
  text NOT NULL DEFAULT 'live_eligible'
  CHECK (routing_mode IN ('live_eligible', 'shadow_only'))`
- UPDATE existing cohort portfolios:
  - Conservative Cohort, Neutral Cohort → `'shadow_only'`
  - Aggressive Cohort → `'live_eligible'` (current champion path)
  - Main Paper → `'live_eligible'`
- Effort: ~30 min.
- Risk: LOW (data-only change, no code change yet).

**PR 2 — Routing dispatch enforcement**
- Modify broker dispatch to check `portfolio.routing_mode` before
  live submission.
- Implement `_simulate_fill` for shadow_only portfolios (decide
  between mid-price simulation, mirror-champion, or paper_mtm
  reuse).
- Tests: assert shadow_only portfolios never reach Alpaca
  regardless of `EXECUTION_MODE`.
- Effort: ~1 day.
- Risk: MEDIUM (architectural change, needs careful testing).

**PR 3 — Apply original #62a-D4 single-line symbol fix**
- Drop `"symbol": source.get("symbol")` from clone dict at
  `packages/quantum/policy_lab/fork.py:229`.
- Verification: shadow trades start appearing in `trade_suggestions`;
  `paper_orders` for shadow_only portfolios show simulated fills.
- Effort: 5 min code + 30 min verification.
- Risk: LOW after PRs 1 and 2 land.

Total effort: **~2 days across 3 PRs.**

Architectural principle: each portfolio's intent (live-capable vs
shadow-only) becomes explicit data, not implicit code-path
knowledge. Safe by default — new portfolios default to
`live_eligible`; shadow status must be intentionally set.

Verified production state (still true as of 2026-04-26):
**0 conservative/neutral shadow clones in 30 days** vs 58
aggressive. Shadow eval data collection has been broken at the
source for the entire month. The "189 cohort decisions" stat
referenced in CLAUDE.md cohort architecture section is from
`policy_decisions`, NOT actual shadow trades.

#### #62a-D5 — `execution_cost_*` columns silently dropped (HOT, HIGH)

File: `packages/quantum/services/workflow_orchestrator.py:468-478`.
3 columns (`execution_cost_soft_gate`, `execution_cost_soft_penalty`,
`execution_cost_ev_ratio`) dropped via `DROPPABLE_SUGGESTION_COLUMNS`
retry shim on every suggestion write. Verified absent from
`trade_suggestions` schema.

**Decision needed:** are these signals load-bearing for execution
gates? If yes, add columns via migration. If no, remove the
computation and the shim entirely.

Effort: ~2 hours after decision.

#### #62a-D6 — `model_governance_states` table missing (MEDIUM)

Migration `20251215000000_learned_nesting_v3.sql` partially applied
— ALTER statements landed but `CREATE TABLE model_governance_states`
did not. Learned Nesting v3 governance writes fail silently.

Fix: apply table-creation portion, OR delete the writes if Learned
Nesting v3 is dormant.

Effort: ~1 day.

#### #62a-D7 — `shadow_cohort_daily` table missing (MEDIUM)

File: `packages/quantum/public_tasks.py:1861`. Migration
`20260122100000_shadow_cohort_daily.sql` not applied. Autopromote
v4-L1E feature broken silently. Note: `POLICY_LAB_AUTOPROMOTE=false`
permanently, so the consumer feature is off anyway.

Fix: apply migration OR remove writer (deletion is the lower-risk
choice given the consumer is off).

Effort: ~1 hour to remove writer, ~2 hours to apply + verify.

#### #62a-D8 — `trade_executions` 8 wrong columns (MEDIUM)

File: `packages/quantum/services/execution_service.py:215-254`.
Writes `mid_price_at_submission`, `order_json`, `trace_id`,
`window`, `strategy`, `model_version`, `features_hash`, `regime`
— none in legacy `trade_executions` schema. Canonical execution
path is `paper_orders` + `position_legs`.

**Prerequisite:** trace whether `register_execution` is on any
active path. If dead → delete the legacy `ExecutionService`. If
alive → drop-cols-or-add-cols decision.

Effort: ~half day investigation + ~1-2 hours fix.

#### #62a-D9 — `trade_suggestions` rebalance flow extra cols (LOW)

File: `packages/quantum/api.py:869-885,898`. Writes `symbol`,
`confidence_score`, `notes` — none in schema. Rebalance flow likely
unused; insert 400s if exercised.

Effort: ~1 hour (verify cold, then either fix or remove endpoint).

#### #62a-D10 — `outcomes_log` 5 cols (LOW) — TRACKED UNDER #67

5 cols (`status`, `reason_codes`, `counterfactual_pl_1d`,
`counterfactual_available`, `counterfactual_reason`) absent. Already
folded into the dead-code sweep via backlog #67.

#### #62a-D11 — `symbol_regime_snapshots` table missing (LOW)

Created by migration `20251213000000_regime_snapshots.sql` (same as
D3) but no active write site found in code. Note only — no fix
needed unless a writer is reintroduced.

#### #62a-D12 — Out-of-band tables (LOW) — ACKNOWLEDGE, NO ACTION

7 tables exist in prod with no creator migration: `audit_logs`,
`profiles`, `portfolios`, `option_positions`, `weekly_trade_reports`,
`user_settings`, `plaid_items`. Pre-migration-tracking artifacts.
Don't rebuild migration history; just acknowledge.

### #62a audit method limitations

The audit catches static patterns: dict-literal upserts,
enum-constraint writes, migration-vs-prod schema diff. It does
NOT catch:

1. `**kwargs` / variadic dict expansion in writes.
2. Dicts built across functions (9 sites flagged opaque).
3. `SELECT *` reads on schema-drifted tables.
4. JSONB metadata field shape conventions.
5. Joins / RLS / FK referencing dropped columns.
6. Views drifting from base tables.
7. Migrations rolled back via dashboard.
8. **Migration intent vs runtime code disagreement** (the
   `'neutral'` vs `'aggressive'` issue under D1 was caught only
   by manual review of the migration file, not by any automated
   step).

Confidence: HIGH on 10 actionable findings, MEDIUM on completeness.
Future drift is expected; this audit method catches the bulk but
not all.

---

