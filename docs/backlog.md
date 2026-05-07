# Backlog

This file is the durable home for backlog items. CLAUDE.md references this file but does not duplicate its contents.

Last migrated from CLAUDE.md: 2026-04-28.

---

## Backlog (post-promotion)

**Tier-promotion rewrite — CLOSED 2026-05-06** (PR #<NUM>)

Replaced broken micro_live → full_auto auto-promotion. Pre-rewrite the
handler at `promotion_check.py:26` read state.get for a
`micro_live_green_days` field that doesn't exist in
`go_live_progression` schema. Handler ran 23 times historically without
ever firing the "READY for promotion" critical alert because the
counter was permanently 0.

New gates (operator-confirmed 2026-05-06):
- broker equity ≥ $1500
- cumulative realized_pl > 0 across Alpaca-real closed trades
- alpaca_real_trade_count ≥ 3

Bonus: extracted `get_alpaca_real_closed_trades` shared helper used by
both `daily_progression_eval` (alpaca_paper green-day counter) and the
new `promotion_check` (micro_live → full_auto gate). Both paths now
agree on the trade lens — eliminates drift risk between progression
and promotion accounting.

Diagnostic note: original spec assumed `cumulative_pl=-$82, count=1`.
DB query revealed three lenses with materially different answers:
naive +$66K (inherits 2026-04-16 corruption), date-floor -$1958,
Alpaca-only -$20. Operator confirmed Alpaca-only (matches existing
`daily_progression_eval` pattern). Cross-reference Anti-pattern 9
in `docs/loud_error_doctrine.md` (audit-methodology, 2026-05-05) —
production state should be empirically verified against database
before design specs are locked.

`alpaca_paper → micro_live` logic untouched per operator decision.
Manual override (`ProgressionService.promote()`) preserved.
Doctrine: same dead-state-reference shape as #62a-D7 (PR #879) and
#71 PR-5 (PR #880).

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

**PR-1 shipped 2026-05-04** (audit only, PR #872). Findings at
`docs/rq_dispatch_audit_2026_05_04.md`. Inventory:
- 38 total task endpoints (22 public + 16 internal)
- 30 already async (canonical `enqueue_job_run` pattern)
- 8 sync; **5 are migration candidates**, 3 deferred (intentional
  sync per docstring: /paper/process-orders, /validation/shadow-eval,
  /validation/preflight)

**PR-2 shipped 2026-05-04** (1/5 migrations complete, PR #<NUM>).
`/tasks/policy-lab/eval` migrated from inline sync to canonical async
dispatch. Pre-migration: APScheduler fired the endpoint daily at
16:30 CT and the work ran against the request thread with zero
`job_runs` trace. Post-migration: each fire produces a `job_runs`
row.

Intended behavior changes documented in PR description:
- `compute_decision_accuracy` now runs (was silently dropped by the
  inline endpoint — handler always had it; the inline path was the bug)
- Multi-user fan-out supported when payload omits `user_id` (handler
  iterates active users; inline endpoint required user_id)
- Per-stage `risk_alerts` writes from the prior sync handler replaced
  by `job_runs.status='failed'` observability (different shape, net
  observability improves — pre-migration there were zero rows)

Subsequent migrations (PR-3 through PR-7): `/validation/init-window`,
`/validation/cohort-eval`, `/validation/autopromote-cohort`
(includes idempotency redesign PR), `/train-learning-v3` (largest,
needs per-user decomposition). Total remaining: 4 migrations + 1
idempotency redesign.

**PR-3 shipped 2026-05-04** (2/5 migrations complete, PR #<NUM>).
`/tasks/validation/init-window` migrated to canonical async dispatch.
New handler scaffolded at
`packages/quantum/jobs/handlers/validation_init_window.py` (Tier 2
audit blocker resolved); auto-discovered via the existing
`packages/quantum/jobs/registry.discover_handlers` mechanism — no
explicit registration needed.

Pure migration; no behavior changes (unlike PR-2's
`compute_decision_accuracy` reactivation). Operator-on-demand endpoint;
GHA workflow `validation-init-window` fires it daily 8:40 AM CT via
`run_signed_task.py` which accepts both 200 and 202.

**Design note on gates:** the paper-mode + paused gates
(`_check_readiness_hardening_gates`) remain at the endpoint to reject
before enqueue, avoiding "queued then failed" `job_runs` rows for
gate-rejected calls. This pattern generalizes to Tier 3+ endpoints
that share the same gate helper (`/validation/cohort-eval` and
`/validation/autopromote-cohort`).

**PR-3 validated 2026-05-05** via manual GHA fire (Trading Tasks →
manual-task → `validation_init_window` with `force_rerun=true`).
`job_runs` row produced (id `bbfe5863-f207-426a-86e7-772b12820b63`),
status=`succeeded`, handler duration 0.17s DB-side. Handler's return
matches `v3_go_live_state` row exactly; `was_repaired: false` confirms
correct idempotent no-op behavior (existing window state passes
service contract). Auto-discovery + `force_rerun` plumbing + endpoint
gate behavior + new envelope shape all confirmed working end-to-end.
Migration no longer "deployed-untested."

Side observation (not a migration defect): user's `paper_window_end`
is 2026-03-28 (expired). Service-level question whether
`ensure_forward_window_initialized` should re-window expired states;
out of scope for #71 sweep.

**Tier 3 + Tier 4 closed by DELETION 2026-05-05** (PR #879).
PR-4 attempt on `/validation/cohort-eval` (Tier 3) surfaced a
fourth-case finding: the writer targets `shadow_cohort_daily`, a
table that doesn't exist in production. Verification showed neither
the writer endpoint nor the consumer endpoint
(`/validation/autopromote-cohort`, Tier 4) has ever fired in
production — zero `job_runs` rows for either, ever. The whole
shadow_cohort_daily channel was unexercised dead code.

Per #62a-D7 resolution, both endpoints removed entirely rather than
migrated.

**Tier 5 also closed by DELETION 2026-05-05** (PR #<NUM>).
`/internal/tasks/train-learning-v3` diagnostic confirmed zero
production runs ever, no scheduler entry, no GHA workflow caller.
Bonus finding: `CalibrationService.train_and_persist` (the only
unique service method the endpoint called) doesn't exist on the
class — the endpoint would have crashed with `AttributeError` on
first execution if it had ever fired. Same B2-deletion pattern as
#62a-D7.

**#71 SWEEP CLOSED 2026-05-05.** Final state across 5 PRs:
- PR-1 #872 (audit, docs-only)
- PR-2 #873 (`/policy-lab/eval` migrated)
- PR-3 #874 + #877 (`/validation/init-window` migrated, then validated)
- PR-4 #879 (`/validation/cohort-eval` + `/validation/autopromote-cohort`
  deleted as B2)
- PR-5 #<NUM> (`/internal/tasks/train-learning-v3` deleted as B2)

Original audit's "5 migrations + 1 idempotency redesign" became
"2 migrations + 3 deletions." The audit was conservative on
deletion calculus — production-exercise verification (added at
diagnostic stage) caught three endpoints that had never fired,
making the migration-vs-delete decision moot.

**Doctrine note:** future endpoint audits should include
"production-exercise count" as a first-class column. The original
audit catalogued endpoints that EXIST but didn't catalogue endpoints
that FIRE. For #71, those were different sets, and the difference
materially changed scope (3 PRs avoided).

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

**Verify-pass 2026-05-05:** total_rows = 171 (across 5+ months,
oldest = 2025-12-11). Last 14 days produced only 11 rows
(thin universe + micro-tier sizing keeps emission low). Status
mix: 2 pending, 65 staged, 66 dismissed, 38 other. Phantom-row
volume is not operationally concerning — table size is trivial
and growth rate is ~1 row/day. Re-verify monthly OR if cohort
fan-out post-#876 + #97 produces sustained 3x volume increase.

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

**#95 — fork.py threshold semantic mismatch** (HIGH, AWAITING
NEXT-CYCLE VERIFICATION post-#876)

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

**Verification chain status (2026-05-05 verify-pass):**
- Score persistence verified ✓
- Filter logic verified ✓ (filter accepted BAC for all 3 cohorts)
- Clone INSERT path was broken by #97 trace_id collision —
  resolved by PR #876 (closed 2026-05-05)
- End-to-end verification awaits next cohort-firing cycle —
  zero `cohort_name`-tagged suggestions and zero
  `cohort_clone_insert_failed` alerts since #876 merge
  (today's only suggestions_open ran at 16:00:07Z, BEFORE
  #876's 18:55:34Z merge; pre-fix evidence isn't useful)

**Status:** Functionally unblocked. First post-#876 cohort-firing
cycle (likely tomorrow's 16:00 UTC) will produce 3 clones per
qualifying source. Re-verify on first occurrence and close.

**#96 — paper_autopilot status update silently bypassed** — **CLOSED 2026-05-03**
Covered by PR #839's H5b sweep. The status-update swallow at
`paper_autopilot_service.py:460-471` appends to the shared
`_per_suggestion_failures` list with `stage="status_staged_update"`,
and the aggregated H5b alert at line 513
(`alert_type="paper_autopilot_per_suggestion_failed"`,
severity="warning") fires on that list at end-of-loop. The
`stages_affected` metadata field surfaces "status_staged_update"
specifically, so operators querying `risk_alerts` can distinguish this
swallow site from the line-500 full_execution swallow.

The two BAC reproductions cited in the original entry (2026-04-30,
2026-05-01) predated full appreciation of H5b's coverage shape.
Subsequent reproductions produce
`paper_autopilot_per_suggestion_failed` `risk_alerts` rows with
`metadata.stages_affected` containing "status_staged_update".

Operationally inert post-#93 (broker-truth budget ignores pending
status). Latent observability for downstream consumers
(`policy_decisions` joins on status, learning loops filtering on
status) is now in place.

**#97 — fork.py clone INSERT silent failure** — **CLOSED 2026-05-05**

Two-phase resolution following Loud-Error Doctrine v1.0 anti-pattern 4
(silent-failure → loud-failure → diagnose → fix) lifecycle.

**Phase 1 (PR #859, 2026-05-02):** alert wiring at the cloner's
exception path. New `cohort_clone_insert_failed` critical alert
captures `error_class`, `error_message`, `clone_keys`, `cohort_name`,
`ticker` for next-cycle root-cause classification. Observability-only;
no behavioral change.

**Phase 2 (PR #<NUM>, 2026-05-05):** root cause classified from
production alert metadata. First production fire arrived 2026-05-05
16:00:18Z (today's CSX cycle, ~3h after the suggestions_open
producing the source candidate). Both alert rows (conservative +
neutral cohorts) showed identical signature:
- `error_class`: APIError (PostgreSQL 23505 unique violation)
- `constraint`: `idx_trade_suggestions_trace_id_unique`
- `error_message`: same source `trace_id` collided across cohort
  inserts

Schema verification confirmed `trace_id` is row-unique by design
(partial unique index on non-null; column has
`DEFAULT gen_random_uuid()`). Lineage tracking lives in separate
columns (`lineage_hash`, `lineage_sig`, `lineage_version`,
`decision_lineage`) — those are intentionally inherited across
clones. The cloner's `"trace_id": source.get("trace_id")` at
`fork.py:287` was the bug.

Fix: `"trace_id": str(uuid.uuid4())` per clone — single line.
Phase 1's alert wiring retained as the regression canary. 11 new
tests + 4 existing fork regression tests all pass.

**Doctrine validation:** the alert-then-diagnose-then-fix lifecycle
worked end-to-end. Phase 1 alert sat dormant Sat→Mon→Tue afternoon
(zero fires); first fire arrived within hours of CSX surfacing a
successful primary candidate; full root cause classified from
metadata in a single SQL query; fix shipped same day.

**Unblocks:** #95 verification can now confirm cohort comparison
data accumulates (3 cohorts producing rows in `trade_suggestions`
per fork). Any next-cycle CSX-shape candidate produces 3 cohort
clones inserting cleanly.

**#98 — needs_manual_review observability gap** — **CLOSED 2026-05-04**
Both Option C (write-site alert) and Option B (recurring sweep catch) shipped.

**Origin:** 2026-05-01 16:45 UTC BAC close order rejected by Alpaca 3x
with "insufficient options buying power" (required $296, available $204).
`submit_and_track` at `alpaca_order_handler.py:226-242` marked order
status='needs_manual_review' and returned dict (did NOT raise). H5a alert
at `paper_exit_evaluator.py:1226` only fires for raised exceptions, so
silent. Operator discovered ghost position 5+ hours later.

**Option C shipped (PR #853, 2026-05-01):** loud alert at
`submit_and_track:231` immediately when marking status='needs_manual_review'.
Catches ALL callers within seconds.

**Option B shipped (PR #<NUM>, 2026-05-04):** extended `ghost_position_sweep`
with a new check — paper_orders rows in `status='needs_manual_review'` linked
to open `paper_positions` past 1-hour staleness. New `alert_type=
'stale_manual_review_with_open_position'` at warning severity. 1-hour
idempotency gate via `metadata->>order_id` JSON path filter prevents flooding
risk_alerts at sweep cadence (alpaca_order_sync runs every 5 min; without
the gate, BAC's 3-day stuck duration would have produced ~864 alerts).

Defense-in-depth catch when Option C's write-site alert is missed in the
moment. Sweep surfaces persistent stuck state on every cycle until operator
clears it. 5 structural + 4 behavioral tests guard alert wiring + idempotency.

Operationally inert post-#100 (Option A protects against the Friday-class
sizing failure that produced these stuck states), but the class is latent
for non-Friday failure modes: broker outages, non-BP rejections, manual
operator actions that orphan rows, etc.

**Underlying architectural cause:** see #100. The close rejection happened
because sizing didn't check round-trip BP. Options B and C address
observability; #100 addresses prevention.

**#100 — round-trip BP check at sizing** — **CLOSED 2026-05-04**
Resolved by PR #858 (Option A — Formula A entry-premium-based estimator).
Sizing engine now computes `contracts_by_round_trip` as a 4th sizing
dimension via `estimate_close_bp(legs, strategy_type, entry_premium)`;
for *_DEBIT_SPREAD, `estimated_close_bp = max_loss_per_contract` with
`safety_factor=1.1` starting calibration. Wired through
`workflow_orchestrator.py:2643` via a single new kwarg. Test surface
landed: 3 source-level + 9 helper behavioral + 7 sizing integration +
1 regression query.

**Origin incident (2026-05-01):** BAC entry took $292 of $500 OBP,
leaving $204. Alpaca's close-side margin gate required $296. Position
stuck open at broker for 5+ hours. Doctrine entry (#102) plus this
sizing gate (#100) close the loop on round-trip safety as a sizing
invariant.

**Architectural note (carried forward):** future multi-cohort live
routing (#65 `policy_lab_eval`) may need reservation semantics to
prevent simultaneous-cohort competition for live capital — not blocked
by anything today, just a forward-looking pointer.

**#101 — STRATEGIES_ALLOWLIST env knob** (LOW, incident-response
optional)

Environment variable to restrict scanner emission to specific
strategy types. Useful as kill-switch during incidents (e.g.,
"single-leg only after BP-to-close issue") without code
changes.

**Default:** unset (current behavior — all strategies allowed)

**Format:** comma-separated strategy names, e.g.,
`STRATEGIES_ALLOWLIST=long_call,long_put`

**Implementation site:** scanner gate in options_scanner.py,
early-return before strategy emission if not in allowlist.

**Priority downgraded MEDIUM → LOW (2026-05-05 verify-pass):**
the original BP-to-close incident class that motivated this knob
is structurally addressed by #100 (PR #858, round-trip BP at
sizing). The knob is still independently useful for OTHER future
incident classes (regime-strategy mismatch, broker-rejection
patterns, etc.) — orthogonal to #100, not redundant. Defer until
a future incident class actually demands it; ship if and when.

**Effort:** half day (env var read + scanner gate + tests).

**#102 — Round-trip safety as sizing invariant (DOCTRINE)** — **CLOSED 2026-05-03**
Covered by PR #856's "Operations preserve capital invariants in both
directions" entry in `docs/loud_error_doctrine.md` (the H7 framing).
That entry explicitly names sizing as the primary "Patterns to look for"
case (`Sizing: does it check entry_cost AND close_cost ≤
available_capital?`) and cites Option A (#100) as its concrete
application, with the BAC ghost-position incident as origin. CLAUDE.md
Working Style updated with a cross-reference so future operators find
the doctrine from the system-overview surface.

**#103 — Regime → strategy selection breadth audit** — **CLOSED 2026-05-07**

Resolved 2026-05-07 by #107 diagnostic. Of the three possibilities
originally listed:
- "Regime-driven natural selection" — partially correct for W3
  sentiment alone (SPY+QQQ truly bullish-trending)
- "Coverage gap in strategy emission logic" — confirmed yes, but the
  gap is upstream of the selector: iv_rank=50.0 hardcoded fallback at
  `options_scanner.py:2395` routes 4 of 7 strategy paths to
  never-trigger state
- "Threshold calibration too narrow" — partially relevant (SUPPRESSED
  vs NORMAL borderline), but secondary

**Cross-reference:** the regime → strategy selection breadth is
constrained by iv_rank computation breakage, not classifier behavior.
See #107 (diagnostic) and #115 (iv_rank fix). Classifiers themselves
are working; iv_rank upstream is the actual broken lever.

— Original entry preserved below for context —

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

**#104 — RejectionStats coverage audit of `_process_symbol_multi`** — **CLOSED 2026-05-04**
Resolved by PR #<NUM>. Loud-Error Doctrine v1.0 anti-pattern 4 (per-iteration
swallow in tight loops) requires every early-return path inside the scanner's
per-symbol pipeline to record a meaningful rejection reason via `rej_stats`.

**Audit conducted against post-#866 source.**

`process_symbol` (line 2257): all 26 `return None` paths verified instrumented
(PR #866 closed the last two via #105/#106 splits). Source-level guard added
(`test_process_symbol_returns_are_all_instrumented`) to detect regression
when new gates are introduced.

`_process_symbol_multi` (line 3200): one silent return at line 3219 —
`if len(cands) <= 1: return None` when the selector produced ≤1 candidate
so no fallback retry is possible. The primary's rejection reason was already
counted by `process_symbol`, but there was no counter for "multi-strategy
mechanism couldn't help because no fallbacks existed." Distinct from
`all_strategies_rejected` which means fallbacks WERE tried and all failed.

Fix: added `rej_stats.record("no_fallback_strategies_available")` at the
silent site. Observability-only — same trades accepted/rejected as before.
Operators can now distinguish how often the multi-strategy mechanism added
value (`all_strategies_rejected` count) vs how often it was inert
(`no_fallback_strategies_available` count) per cycle.

**#105 — `strategy_hold` lumps two distinct conditions** — **CLOSED 2026-05-04**
Resolved by PR #<NUM>. `options_scanner.py` recorded
`rej_stats.record("strategy_hold")` at two distinct sites for distinct
conditions:
- Line ~2408: selector returned empty list of candidates
- Line ~2447: explicit `HOLD`/`CASH` verdict from selector

Split into `strategy_hold_no_candidates` and
`strategy_hold_explicit_verdict`. Operators can now distinguish whether
to investigate selector candidate generation versus the HOLD/CASH gate.
Surfaced by 2026-05-04 scanner pipeline diagnostic (6 strategy_holds
in single cycle, ambiguous root cause). Unblocks #107 (strategy
selector low-EV emission investigation needs the disambiguated counts
to tune meaningfully).

**#106 — `spread_too_wide` misnamed for tiny-entry-cost trades** — **CLOSED 2026-05-04**
Resolved by PR #<NUM>. The spread formula `combo_spread / entry_cost`
produces deceptively-large percentages when entry_cost is tiny. Today's
PFE rejection (combo=$0.12, entry=$0.06 = 200%) was correctly rejected
(uneconomic trade) but the name suggested a liquidity issue.

Split into three reason codes via classification at the rejection site:
- `spread_too_wide_real` (combo > $0.20 — actual wide spread)
- `entry_cost_too_low` (entry < $0.15 — uneconomic trade, today's PFE shape)
- `spread_too_wide` (boundary case retained — neither absolute threshold triggered)

Tunable via `ABSOLUTE_SPREAD_THRESHOLD` and `MIN_ECONOMIC_ENTRY` module
constants (env-overridable). Operationally inert — same trades accepted/
rejected as before; operators see accurate signal in `rejection_counts`.

**#107 — Regime + sentiment classifier diagnostic** — **CLOSED 2026-05-07**

Diagnostic completed 2026-05-07. Three original hypotheses partially
refuted in favor of a new H4 finding.

**Findings:**
- **Sentiment classifier (H1 verdict):** SUPPORTED. SPY $686 → $733.77
  (+6.96%) over W3's 17 trading days, daily-return std ~0.65%, annualized
  vol ~10.3%. Internal BULLISH classification matches external truth.
  H3 (sentiment sticky-bullish) refuted — W2 had 29 LONG_PUT_DEBIT_SPREAD
  emissions, sentiment does flip when symbols trend down.
- **Regime classifier (H1 weak/H2 weak):** WEAKLY supported either way.
  Regime varied widely in W1+W2 (CHOP=71, NORMAL=63, ELEVATED=26,
  REBOUND=6 across 90 days). W3's 100%-NORMAL streak is plausible given
  actual W3 market regime. Sub-finding: SUPPRESSED never observed in 90d
  despite genuinely low-vol periods (~10% W3 vol borders SUPPRESSED
  threshold). Minor calibration concern, not a strategic issue — both
  NORMAL and SUPPRESSED routes emit debit spreads for BULLISH.
- **🚨 NEW H4 (PRIMARY VERDICT):** `iv_rank = symbol_snapshot.iv_rank or
  50.0` at `options_scanner.py:2395` is a Loud-Error Doctrine
  Anti-pattern 2 violation. iv_rank=50.0 across ALL 166
  trade_suggestions in 90-day window (zero variance). Hardcoded
  fallback masks broken upstream computation.

**Strategic consequence:** iv_rank=50 routes through "normal IV"
selector branches and eliminates 4 of 7 strategy paths:
SHORT_PUT_CREDIT_SPREAD, SHORT_CALL_CREDIT_SPREAD, NEUTRAL+high-IV
IRON_CONDOR, EARNINGS+high-IV IRON_CONDOR all never trigger.
Surviving paths: 3 directional debit spreads + CHOP-regime IRON_CONDOR.
This is the SINGLE root cause of W3's strategy diversity loss.

**Outcomes:**
- New #115 (HIGH) opened for iv_rank fix work
- #103 closed (#107 + #115 supersede the original "regime → strategy
  selection breadth" question)
- #114 (ban-knob experiment) superseded; would not surface credit
  spreads or non-CHOP iron condors under iv_rank=50

**Effort actual:** ~50 min for diagnostic. No PR drafted (read-only).

**#108 — Multi-strategy Phase 2 PR-1: per-strategy realized P&L helper extension** (LOW)

Phase 1 design doc PR-1. Foundation for strategy lifecycle gating.
Extends `get_alpaca_real_closed_trades(user_id, supabase, since=None,
until=None)` (shipped in PR #883) with optional `strategy_name` parameter.
When provided, joins through `paper_orders → trade_suggestions` to
filter to that strategy's closed trades only.

Add `get_strategy_eligibility(strategy_name, user_id, supabase)`
returning `{eligible, cumulative_pl, trade_count}` matching the
tier-promotion gate shape from PR #883.

Tests: 6-8 unit tests on filter behavior + missing-strategy-name
backward-compat.

**Dependencies:** none. Self-contained extension.

**Effort:** half day.

**Cross-reference:** `docs/designs/multi_strategy_phase1.md` Phase 2 PR-1.

**#109 — Multi-strategy Phase 2 PR-2: strategy_lifecycle_states table + scheduler hook** (LOW)

Phase 1 design doc PR-2. State machine: DESIGNED → EXPERIMENTAL →
LIVE_FULL → DEPRECATED.

Migration: `strategy_lifecycle_states` table with `strategy_name` PK,
`current_state`, `transitioned_at`, `transition_reason` jsonb,
`closed_trade_count`, `cumulative_realized_pl`, `updated_at`.

Initial seed: existing 5 strategies (LONG_CALL_DEBIT_SPREAD,
LONG_PUT_DEBIT_SPREAD, SHORT_PUT_CREDIT_SPREAD,
SHORT_CALL_CREDIT_SPREAD, IRON_CONDOR) as `live_full` (preserves
current behavior). New strategies (BULL_PUT_SPREAD_0DTE,
CASH_SECURED_PUT) as `designed`.

`evaluate_strategy_lifecycle()` function piggybacked on
`daily_progression_eval` (4 PM CT). Reuses helper from #108.

Graduation: EXPERIMENTAL → LIVE_FULL when cumulative_realized_pl > 0
across ≥3 closed Alpaca-real trades for that strategy.

Tests: graduation logic + state transition + audit log.

**Dependencies:** #108 (helper extension).

**Effort:** half day.

**Cross-reference:** `docs/designs/multi_strategy_phase1.md` Phase 2 PR-2.

**#110 — Multi-strategy Phase 2 PR-3: sizing engine EXPERIMENTAL override** (LOW)

Phase 1 design doc PR-3. Caps EXPERIMENTAL strategies at 1 contract
regardless of normal sizing.

Read lifecycle state in sizing_engine via cached lookup:
- EXPERIMENTAL → cap to 1 contract (override max sizing)
- LIVE_FULL → no override (existing risk-pct math)
- DESIGNED/DEPRECATED → strategy filtered upstream by scanner via
  `banned_strategies` env arg

Tests: 4-6 unit tests on size-override behavior + interaction with
existing risk-pct math.

**Dependencies:** #109 (lifecycle states table).

**Effort:** half day.

**Cross-reference:** `docs/designs/multi_strategy_phase1.md` Phase 2 PR-3.

**#111 — Multi-strategy Phase 2 PR-4: 0DTE bull put spread + intraday cadence refactor** (MEDIUM)

Phase 1 design doc PR-4. 0DTE doesn't exist in selector today.

New strategy entry in `strategy_selector.py` (~30 lines). Scanner DTE
filter: support same-day expiry under feature flag.

**Architectural prerequisite:** intraday polling cadence. Current
`intraday_risk_monitor` runs every 15 min; 0DTE benefits from 5-min
cadence. Two options:
- Conditional cadence (accelerate when 0DTE positions are open) —
  touches load-bearing job
- Parallel `intraday_0dte_monitor` (recommended) — independent
  scheduler entry, no-op when no 0DTE positions

Force-close-by-3:55-PM logic for any 0DTE position not exited via
target/stop.

Tests: scanner integration, exit lifecycle, settlement timing,
force-close behavior.

**Dependencies:** #108 + #109 + #110 (lifecycle infrastructure).
Strategy starts in DESIGNED state until polling refactor lands.

**Capital gate:** 0DTE benefits from concurrent positions (multiple
intraday round-trips). Operator account at $696 supports only one
position via micro-tier gate. 0DTE realistically needs small-tier
($1000+) and ideally standard-tier ($5000+) for efficient deployment.

**Effort:** 3-4 days.

**Cross-reference:** `docs/designs/multi_strategy_phase1.md` Phase 2
PR-4 + Step 4c.

**#112 — Multi-strategy Phase 2 PR-5: cash-secured-put + capital gating** (MEDIUM)

Phase 1 design doc PR-5. CSP doesn't exist in selector today.

New strategy entry in `strategy_selector.py` (~20 lines). Single-leg
structure: sizing engine accepts 1-leg candidates with
`collateral_required` field.

Capital gate: `EQUITY_THRESHOLD_CSP = $5,000`. Below threshold,
strategy stays DESIGNED regardless of operator flip.

Auto-close-before-expiry semantics initially (avoids equity-assignment
handling). Real CSP semantics with assignment is a follow-up project.

Tests: capital gate behavior, sizing math, auto-close timing,
refusal-to-emit when below threshold.

**Dependencies:** #108 + #109 + #110 (lifecycle infrastructure).

**Capital gate:** $5,000 minimum. Operator account at $696 doesn't
support CSP at retail-relevant strikes. Strategy stays DESIGNED
indefinitely until equity grows.

**Effort:** 3-4 days for selector + scanner + capital gate.
Equity-assignment handling is separate ~1-week follow-up.

**Cross-reference:** `docs/designs/multi_strategy_phase1.md` Phase 2
PR-5 + Step 4d.

**#113 — Multi-strategy Phase 2 PR-6: per-strategy emission counts in observability** (LOW)

Phase 1 design doc PR-6. Closes #103 (Regime → strategy selection
breadth audit) by making breadth empirically observable.

Add per-strategy emission counts to scanner cycle logs / job_runs
result envelope. Daily aggregate per-strategy counts surfaced in
observability dashboard or log summaries. Enables operator to verify
strategy diversity over time without running ad-hoc SQL.

**Dependencies:** none. Self-contained observability addition.

**Effort:** half day.

**Cross-reference:** `docs/designs/multi_strategy_phase1.md` Phase 2
PR-6. Closes/supersedes #103.

**#114 — Ban-knob experiment for classifier diagnostic** — **SUPERSEDED 2026-05-07**

Superseded 2026-05-07 by #107 diagnostic finding. Under the
iv_rank=50 hardcoded fallback (see #115), the ban-knob experiment
cannot surface credit spreads or non-CHOP iron condors regardless of
which directional strategy is banned — those paths are blocked
upstream by the iv_rank=50 routing through "normal IV" selector
branches. Banning LONG_CALL_DEBIT_SPREAD would shift output to
LONG_PUT_DEBIT_SPREAD or HOLD only; would not surface the missing
strategy paths.

The experiment becomes useful only AFTER #115 (iv_rank fix) lands.
Revisit then if classifier behavior is still unclear.

— Original entry preserved below for context —

Phase 1 diagnostic surfaced this as the cheapest available classifier
diagnostic — operator action, not coding work.

If regime/sentiment classifiers appear stuck on NORMAL+BULLISH (per
#107 investigation findings), set
`banned_strategies=["LONG_CALL_DEBIT_SPREAD"]` for 1-2 days.

Observe what selector emits in current conditions:
- LONG_PUT_DEBIT_SPREAD → confirms sentiment classification was being
  preferred-but-not-required as bullish
- IRON_CONDOR → confirms sentiment was actually NEUTRAL or regime
  was actually CHOP
- HOLD (no emissions) → confirms classifier output is genuinely
  correct, NORMAL+BULLISH is the right state

**Operator action, not coding work.** ~10 min to flip env var +
24-48 hours of observation.

**Dependencies:** #107 should run first to determine if classifier
needs investigation at all.

**Cross-reference:** `docs/designs/multi_strategy_phase1.md` Step 4a.

**#115 — iv_rank computation broken; hardcoded fallback masks failure** (HIGH)

**Discovery:** #107 classifier diagnostic (2026-05-07) identified
iv_rank=50.0 across ALL 166 trade_suggestions in 90-day window. Zero
variance is statistically impossible if iv_rank were computing
correctly; confirms hardcoded fallback masks upstream failure.

**Root cause:** `options_scanner.py:2395` reads
`iv_rank = symbol_snapshot.iv_rank or 50.0`. The `or 50.0` is a
Loud-Error Doctrine v1.0 Anti-pattern 2 violation (silent log-only
swallow with default sentinel value). `symbol_snapshot.iv_rank`
returns None/0 for ALL symbols across the full 90-day window,
suggesting the upstream computation has been broken for ≥90 days,
possibly since feature inception.

**Impact:** eliminates 4 of 7 strategy paths in
`strategy_selector.py`:
- BULLISH + high_vol → SHORT_PUT_CREDIT_SPREAD ❌ never triggers
- BEARISH + high_vol → SHORT_CALL_CREDIT_SPREAD ❌ never triggers
- NEUTRAL + high_vol → IRON_CONDOR ❌ never triggers (BULLISH/BEARISH-NEUTRAL path)
- EARNINGS + high_vol → IRON_CONDOR ❌ never triggers (earnings path)

Surviving paths: 3 directional debit spreads + CHOP-regime
IRON_CONDOR (regime-triggered, not IV-triggered). This explains W3's
100%-LONG_CALL_DEBIT_SPREAD streak entirely.

**Recommended approach (two components):**
1. **Upstream diagnostic** (read-only, ~2 hours): find where iv_rank
   is supposed to be computed, why `symbol_snapshot.iv_rank` is
   None/0, what data source it depends on, whether iv_rank ever
   worked historically. Produces evidence for fix design.
2. **Fix PR** (scope unknown until diagnostic): repair upstream
   computation + replace `or 50.0` fallback with `alert()` call per
   loud-error doctrine. Bundle vs split decided post-diagnostic.

**Why HIGH priority:** fixing this likely restores
SHORT_PUT_CREDIT_SPREAD, SHORT_CALL_CREDIT_SPREAD, and high-IV
IRON_CONDOR emissions immediately. Three strategy paths reactivated
by fixing one bug. The lifecycle PRs (#108-#110) are foundation work
for new strategies (0DTE, CSP) but don't unlock anything from
existing strategies. iv_rank fix does — unblocks credit-strategy
emission without writing any new selector code.

**Doctrine cross-reference:** `docs/loud_error_doctrine.md`
Anti-pattern 2 (silent fallback masking upstream failure). Same
pattern shape as #62a-D7 (shadow_cohort_daily missing) and #71 PR-5
(CalibrationService.train_and_persist missing) — code references
state that doesn't produce real values, no alert fires when fallback
path is taken.

**Estimated effort:** Upstream diagnostic ~2 hours. Fix PR scope
undetermined until diagnostic completes.

**Cross-reference:** #107 diagnostic synthesis (2026-05-07).
Closes the original #103 question about strategy selection breadth.

---

**Diagnostic findings (2026-05-07) — verdict: NEVER WORKED.**

Producer cron `iv_daily_refresh` was never registered in
`packages/quantum/scheduler.py:SCHEDULES`. APScheduler introduced
2026-04-01 (commit `7911076`); the job has zero executions in
`job_runs` ever. The handler, signed endpoint, and tests all
exist — only the schedule entry is missing.

**Root cause chain (3 stacked failures):**

1. `iv_daily_refresh` handler is correctly wired
   (UniverseService → MarketDataTruthLayer → IVPointService →
   IVRepository) but never invoked because the SCHEDULES entry
   is absent.
2. `underlying_iv_points` table is empty (0 rows ever). With
   `sample_size < 60`, `iv_repo.get_iv_context()` returns
   `iv_rank=None` deterministically (`iv_repository.py:135`).
3. Two layers of silent fallback mask the upstream failure.
   `options_scanner.py:2395` (`iv_rank or 50.0`) plus
   `regime_engine_v3.py:529`
   (`f_rank = iv_rank if iv_rank is not None else 50.0`). Both
   are Anti-pattern 2 violations per
   `docs/loud_error_doctrine.md`.

**Consumer split (5 silent / 2 explicit):**

- `options_scanner.py:2395` — `iv_rank or 50.0` ⚠️ (the one #107 surfaced)
- `regime_engine_v3.py:529` — `if iv_rank is not None else 50.0` ⚠️
- `strategy_design_agent.py:73` — `context.get("iv_rank", 50.0)` ⚠️
- `analytics/conviction_service.py:189` — `if pos.iv_rank is not None else 50.0` ⚠️
- `analytics/opportunity_scorer.py:141` — `or 0.0` ⚠️ (different sentinel)
- `agents/agents/vol_surface_agent.py:21` — `if iv_rank is None: …` ✓ explicit
- `analytics/guardrails.py:118` — `if iv_rank is not None: …` ✓ explicit

**Operational impact (now explained):**

- 100% NORMAL regime classification in W3: `iv_rank=50` →
  `score=50` → NORMAL bracket via `regime_engine_v3.py:541-548`.
  With real iv_rank values, the regime classifier would
  distribute across SUPPRESSED / NORMAL / ELEVATED / SHOCK as
  designed.
- Strategy emission asymmetry partially explained: iron condor
  trigger requires `iv_rank > 50` strict OR ELEVATED+ regime.
  With frozen iv_rank=50, neither condition fires post-CHOP
  windows.

**Greeks parallel question:** `analytics/greeks_aggregator.py:48-51`
and `api.py:575-578, 943-946` use `delta or 0.0`, `theta or 0.0`,
etc. — same Anti-pattern 2 shape. Whether Greeks are actually
always-None like iv_rank requires checking the truth_layer Polygon
enrichment path post-2026-04-27 plan upgrade. Deferred to **#115b**.

**Fix-scope decision (operator, 2026-05-07): doctrine-aligned, PR-A + PR-B sequenced.**

- **PR-A (~half day):** add `iv_daily_refresh` entry to
  `SCHEDULES` + add `iv_pipeline_no_data` loud-error alert when
  `get_iv_context()` returns None for >N% of universe in a
  single scan cycle. Producer starts populating
  `underlying_iv_points` daily. Alert ensures future silent
  failures of the producer are caught immediately.
- **PR-B (effort TBD; drafted after PR-A lands):** replace
  silent fallbacks at the 5 consumer sites with explicit
  None-routing per `loud_error_doctrine.md` Anti-pattern 2.
  Semantics (skip vs flag vs explicit-route-to-normal)
  decided during PR-B drafting based on warmup-window
  emission tradeoffs.

**Warmup window:** even after PR-A ships, `iv_rank` doesn't
become meaningful until ~60 trading days of
`underlying_iv_points` history accumulate. PR-B is what makes
the fix meaningful from day one — without it, the system
continues using silent 50.0 fallback during the entire warmup
window.

**Cross-references (additional):**

- `docs/loud_error_doctrine.md` Anti-pattern 2.
- Same dead-state-reference shape as #62a-D7
  (`shadow_cohort_daily` missing) and #71 PR-5
  (`CalibrationService.train_and_persist` missing). Now a
  4-data-point pattern.
- Schedule entry pattern: see existing `daily_progression_eval`
  entry in `SCHEDULES` (recently shipped).

**PR-A status (2026-05-07):** shipped on branch
`feat/115-pr-a-iv-schedule-and-alert`. Adds `iv_daily_refresh`
to `SCHEDULES` (4:30 AM CT, before `calibration_update`) and
the `iv_pipeline_no_data` loud-error alert at the scanner
batch-fetch boundary (threshold 0.5 None-rate, 24h dedup via
`risk_alerts` lookup). Producer starts populating
`underlying_iv_points` daily; iv_rank values become meaningful
after ~60 trading days of accumulated history. PR-B
(None-routing at the 5 silent-fallback consumer sites) still
pending — system continues to fall back to 50.0 during the
warmup window until PR-B lands.

**#115b — Greeks parallel investigation: same-shape fallbacks in greeks_aggregator and api** (MEDIUM)

**Discovery:** #115 iv_rank diagnostic surfaced parallel
`or 0.0` fallback patterns for Greeks at
`analytics/greeks_aggregator.py:48-51` and
`api.py:575-578, 943-946`. Same Anti-pattern 2 shape as
iv_rank's `or 50.0`.

**Question:** are Greeks producing real values, or are they
silently None like iv_rank? Two possibilities:

- **Pre-2026-04-27:** Polygon Options Basic plan didn't include
  real-time Greeks — the `or 0.0` fallback may have been
  load-bearing during that window.
- **Post-2026-04-27:** Polygon Options Developer plan ($79/mo,
  upgraded per #87) should populate Greeks. Whether the
  `MarketDataTruthLayer` enrichment path actually pulls them
  is unknown.

**Approach (when scheduled):** read-only diagnostic similar to
#115. Walk the truth_layer Polygon enrichment chain for
Greeks. Check DB variance: do `delta` / `gamma` / `theta` /
`vega` fields in `paper_orders.order_json` (per leg) or
`trade_suggestions.order_json` show variance, or are they
uniformly 0? If uniform → Greeks have the same upstream
problem. If varied → fallback is defensive only.

**Timing:** schedule AFTER #115 PR-A + PR-B land and `iv_rank`
values are confirmed flowing. Bundling with #115 would couple
two independent investigations.

**Dependencies:** #115 PR-A merged + at least 2 weeks of
`underlying_iv_points` accumulating data (so the iv_rank
diagnostic has clean signal to compare Greeks against).

**Estimated effort:** ~1.5–2 hours diagnostic. Fix scope
undetermined until diagnostic completes.

**Cross-reference:** #115 diagnostic synthesis Step 5.

**#115c — Anti-pattern 2 cleanup batch: non-iv_rank/Greeks sites identified by #115 diagnostic** (LOW)

**Discovery:** #115 diagnostic Step 6 surfaced a small set of
localised (not systemic) `or <sentinel>` patterns in
production code outside the iv_rank and Greeks chains. Same
Anti-pattern 2 shape, smaller blast radius.

**Sites identified:**

- `execution/transaction_cost_model.py:217` — `fill_probability or 0.5`
- `analytics/opportunity_scorer.py:49` — `short_strike or 0.0`
- `analytics/opportunity_scorer.py:50` — `long_strike or 0.0`
- `analytics/opportunity_scorer.py:63` — `debit or cost or 0.0`
- `analytics/opportunity_scorer.py:141` — `iv_rank or 0.0` (also covered by #115/PR-B; remove duplication when batch ships)
- `analytics/conviction_service.py:279` — `avg_ev_leakage or 0.0`
- `analytics/conviction_service.py:280` — `avg_predicted_ev or 0.0`
- `analytics/conviction_service.py:344` — `avg_return or 0.0`

**Approach:** for each site, decide whether the field is
boundary input (validate-and-fail-fast) or internal (route
None forward). Replace `or <sentinel>` with explicit None
handling + alert at the producing-side fallback boundary,
per `loud_error_doctrine.md` Anti-pattern 2.

**Timing:** ships when doctrine-cleanup time is available;
not blocking anything. Coordinate with #115 PR-B if
`opportunity_scorer.py:141` is touched there.

**Estimated effort:** ~2-3 hours total once dispatched.

**Cross-reference:** #72 silent-failure catalog (these are
already counted in the P2 ~165 audit total but not
individually tagged); #115 diagnostic Step 6.

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

#### #62a-D4 — Cohort fan-out routing safety + symbol drop fix — **3-PR SEQUENCE SHIPPED 2026-04-30**

PRs #842 (PR2a routing safety gate) + #843 (PR2b shadow fill simulation)
+ #844 (PR3 clone-builder symbol field removal) all merged
2026-04-30. The architectural sequence (routing_mode column +
dispatch enforcement + simulated fills + symbol-drop) is
functionally complete.

**End-to-end verification gate:** the original D4 verification
step ("shadow trades start appearing in trade_suggestions") was
blocked by the subsequent #97 trace_id collision discovered
2026-05-05 — second cohort INSERT failed unique constraint, so
even though D4 unlocked the path, fan-out remained at
{aggressive: 1, others: 0}. PR #876 (closed 2026-05-05) resolved
the trace_id collision. Both #95 and D4 verification gate on the
same upcoming cohort-firing cycle (likely tomorrow's 16:00 UTC).
Tracked under #95's "awaiting next-cycle verification" status —
no separate action needed for D4.

Status: SHIPPED. Verification rolled into #95.

---

(Original D4 framing preserved below for context — describes the
architectural intent of the 3-PR sequence as designed pre-ship.)

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

#### #62a-D7 — `shadow_cohort_daily` table missing — **CLOSED 2026-05-05**

Resolved by removing the cohort shadow eval entirely (PR #<NUM>).
Earlier framing referenced `POLICY_LAB_AUTOPROMOTE=false` as the
gating env var, but verification revealed the consumer is actually
gated by `AUTOPROMOTE_ENABLED` at `public_tasks.py:1207` (separate
flag from `POLICY_LAB_AUTOPROMOTE` which gates a different
policy_lab evaluator). Both gates default off and neither has been
observed flipped on in production.

**Production-exercise verification (load-bearing):** zero `job_runs`
rows ever for `validation_cohort_eval` (the writer endpoint) AND
zero rows ever for `validation_autopromote_cohort` (the reader
endpoint). The whole shadow_cohort_daily channel was unexercised
dead code — the writer's silent no-op (table missing) had no
downstream consumer to even notice.

**Resolution shape — Branch B2 (delete entirely):**
- Removed both endpoints + their helpers from `public_tasks.py`
- Removed `ValidationCohortEvalPayload` + `ValidationAutopromoteCohortPayload`
  from `public_tasks_models.py`
- Removed dispatch entries from `scripts/run_signed_task.py` +
  `scripts/invoke-task.ps1`
- Removed two scheduled job blocks + manual-dispatch enum entries
  from `.github/workflows/trading_tasks.yml`
- Deleted dedicated test files; surgical removal of references in
  shared test files
- Service method `eval_paper_forward_checkpoint_shadow` PRESERVED
  (still used by `/validation/shadow-eval` which stays — intentional
  sync per audit)

Side benefit: closes Tier 3 (cohort-eval) and Tier 4 (autopromote-cohort)
of the #71 RQ dispatch sweep by removing rather than migrating those
endpoints. See #71 entry for sweep impact.

If autopromote reactivation is ever pursued, restoration requires
re-implementing the eval, the persistence (table + writer), and the
consumer logic together as a unified feature, not piece-by-piece.
See git history for the original endpoint shape (PR #<NUM>).

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

