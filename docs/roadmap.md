# Roadmap Status

This file is the durable home for roadmap entries (Completed, Prioritized Roadmap, retrospective findings). CLAUDE.md references this file but does not duplicate its contents.

Last migrated from CLAUDE.md: 2026-04-28.

---

## Roadmap Status

### Completed
- [x] 10-day paper test
- [x] Policy Lab (3 cohorts)
- [x] Alpaca paper execution
- [x] Parallel reads via asyncio.gather() in suggestion pipeline
- [x] Promotion check job
- [x] Risk envelope wired into pre-entry and MTM
- [x] Multi-strategy scan caching
- [x] Scheduler heartbeat + never-run escalation
- [x] Calibration DTE-bucket segmentation
- [x] Risk envelope circuit breaker
- [x] Alpaca primary for options data (2026-04-08)
- [x] Security: explicit auth on all 17 broker + policy lab endpoints (2026-04-09)
- [x] Loss Minimization Agent (2026-04-09)
- [x] Self-Learning Agent (2026-04-10)
- [x] Profit Optimization Agent (2026-04-10)
- [x] Day Orchestrator Agent (2026-04-10)
- [x] Efficiency: async optimizer, V4 quality cache, condor EV memoization (2026-04-10)
- [x] Alpaca primary for equity data (2026-04-10)
- [x] Time-scaled profit targets (50% early → 25% late, 2026-04-11)
- [x] Sector field wired for envelope concentration checks (2026-04-11)
- [x] Raw EV stored alongside calibrated EV (2026-04-11)
- [x] Auto-retry failed_retryable jobs during market hours (2026-04-11)
- [x] PoP fix: breakeven-adjusted delta (2026-04-12)
- [x] Intraday stop losses (2026-04-12)
- [x] Cohort decision accuracy (2026-04-12)
- [x] Baseline capital synced to Alpaca at micro_live (2026-04-12)
- [x] MTM batch updates (2026-04-12)
- [x] Intraday stop-loss decoupled from RISK_ENVELOPE_ENFORCE (2026-04-13)
- [x] Symbol-level dedup in paper_auto_execute (2026-04-13)
- [x] Pre-cancel conflicting Alpaca orders + idempotency (2026-04-13)
- [x] Risk envelope force-close mode (`RISK_ENVELOPE_ENFORCE=1`, 2026-04-16)
- [x] Ghost-position rescue + reconcile sweep (PR #764, 2026-04-16)
- [x] Alpaca-authoritative weekly P&L math (83872db, 2026-04-16)
- [x] CI workflow with pytest + coverage (PR #1, 2026-04-17)
- [x] Close-path consolidation: 5 violators → single `close_helper.close_position_shared`,
      Phase 1 enum expand (PR #796, 2026-04-23) + Phase 2 enum contract (PR #802)
- [x] `_estimate_equity` / `_compute_weekly_pnl` consolidation: canonical
      `services/equity_state.py` module + shim delegations from
      `intraday_risk_monitor`, `paper_mark_to_market`, `paper_autopilot_service`.
      PR #780 (2026-04-19) extracted to `services/equity_state.py` + migrated
      `intraday_risk_monitor`. PR #795 (2026-04-22) migrated `paper_mark_to_market`
      and `paper_autopilot_service`. Zero false `loss_weekly` events since
      83872db patch on 2026-04-16. Tests in `test_equity_state_*.py` defend
      the invariant.
- [x] Micro-live promotion ($500 cap, Alpaca live) — operator-initiated 2026-04-25
- [x] Policy lab eval ImportError fix (PR #807, 2026-04-25)
- [x] Policy lab eval schema-drift fix + per-cohort observability (PR #808, 2026-04-26 06:15Z)
- [x] #62a-D2 nested_regimes write-only orphan deleted (2026-04-26) — 0 rows ever, 0 readers; deleted `log_global_context` rather than fix; table drop tracked as #75
- [x] **#62a-D4-PR1** — `routing_mode` column migration applied 2026-04-26 16:41Z via `mcp__supabase__apply_migration` (PR #815). Backfilled Conservative + Neutral cohort portfolios to `shadow_only` per design intent; Aggressive Cohort + Main Paper rows defaulted to `live_eligible`. First of 3-PR D4 sequence. PR2 (dispatch enforcement) and PR3 (symbol drop) remain pending. Audit-trail row in `risk_alerts` (alert_type=`migration_apply`).
- [x] Tier-aware sizing: micro tier 90% one-at-a-time + standard tier 2-3% multi-position. Closes the compounder-vs-engine `min()` disagreement at `workflow_orchestrator.py:2347` (2026-04-27, PR feat/micro-tier-90pct-single-position). Asymmetric concurrency gate: midday blocks new entries when position open; morning continues exit generation. Backlog #89 (tier-aware envelope) and #90 (`STRATEGY_TRACK` cleanup) deferred.
- [x] Micro-tier universe price filter: drops symbols with underlying > $50 from scanner for micro tier only, configurable via `MICRO_TIER_MAX_UNDERLYING` env (2026-04-27, PR feat/85-micro-tier-universe-price-filter). Closes #85. Composes with PR feat/micro-tier-90pct-single-position.
- [x] **Universe expansion + scanner limit raise** (PR #834, 2026-04-29). Added 8 sub-$50 tickers to BASE_UNIVERSE (PFE, WBD, AAL, CCL, KMI, DKNG, EWZ, LYFT — 62 → 70 symbols) and raised scanner candidate limit from 30 → 50 in `options_scanner.py:2112`. Selected for established options markets, mid-cap range (>$15 underlying to avoid FXI-style penny-premium spread blowout). Standard/small tiers unaffected. Bundles with operator post-merge action (universe_sync trigger to populate metadata for new tickers — see #87b retirement).
- [x] **#87b — `scanner_universe` metadata backfill** (RETIRED 2026-04-28). **Operational closure — no code change required.** Universe_sync trigger run post-Polygon-upgrade populated all 62 symbols' metadata (pre: 9/62 scored; post: 62/62). Sync ran in 26s vs 145s pre-upgrade. Underlying issue was pre-upgrade Polygon Basic-tier rate limits causing silent per-symbol metric-fetch failures inside the sync loop; the post-#87 plan upgrade removed the cap and a trigger achieved the desired state. Audit-trail row in `risk_alerts.alert_type='universe_sync_backfill'` (id `6b9430d1-215e-4539-81dc-2497f029a7ed`).
- [x] **#72-H4c — workflow_orchestrator audit + ancillary** (PR #835, 2026-04-29). Closes Group C+D of #72-H4 sequence. 6 alert sites covered (5 from original H4 catalog + 1 bonus mirror site discovered during diagnostic): exit market-data fetch, morning per-suggestion insert (loop), morning v4 post-insert observability, midday progression fetch (async helper), midday v4 post-insert observability, midday per-suggestion insert (loop, bonus). 34 new structural tests in `test_workflow_orchestrator_alerts.py`. Closes #72-H4 entirely; only #72-H5 remains in #72-Phase 2.
- [x] **#92 — Tier-aware spread threshold for micro tier** (PR #837, 2026-04-30). New helper `_get_micro_tier_spread_threshold()` reads `MICRO_TIER_SPREAD_THRESHOLD` env (default 0.30 = 30%). Dispatch at `options_scanner.py:2286` uses `max(regime_default, micro_override)` so micro tier gets at least 30% while regime loosening (SUPPRESSED 20%) still applies. Standard/small tiers unchanged. Catches BAC-class liquid mid-caps (~14% spread ratio) without opening the gate to truly thin markets. Future operators tune via env, no code change. 11 structural tests in new `test_scanner_micro_tier_spread_threshold.py`.
- [x] **#72-H5a — paper_exit_evaluator loud errors** (PR #838, 2026-04-30). First half of #72-H5. 9 alert sites in `paper_exit_evaluator.py`: per-condition eval (loop), cohort configs load, close-loop (loop), open positions fetch (safety), cohort resolve exhausted (collapsed 3 paths into 1 alert when all fail), routing query (safety), idempotency check (safety), Alpaca DRY_RUN build, Alpaca submit fallback to internal (CRITICAL — 2026-04-16 ghost-position bug shape). **New convention introduced:** `operator_action_required` metadata field on critical-severity alerts; provides explicit operator runbook text without lookup. Future critical alerts in H5b and beyond can adopt. 57 structural tests in new `test_paper_exit_evaluator_alerts.py`.
- [x] **#72-H5b — paper_autopilot_service loud errors** (PR #839, 2026-04-30). **Closes #72-Phase 2 entirely.** 10 alert sites in `paper_autopilot_service.py` including SAFETY-CRITICAL site 236 (`paper_autopilot_circuit_breaker_failed`) with `operator_action_required` metadata (H5a convention adopted). Site 4 (lines 411+438) collapsed two-stage pattern sharing failures list. 63 structural tests. All 8 sub-PRs of #72-Phase 2 shipped (H1, H2, H2a, H3, H4a, H4b, H4c, H5a, H5b).
- [x] **Iron condor clarification + design principle** (PR #841, 2026-04-30). Fixed stale `CLAUDE.md:31` claim ("DISABLED in current phase"); diagnostic verified iron condors are enabled, regime-driven natural selection determines what gets emitted (CHOP regime or NEUTRAL/EARNINGS+high-IV). Captured "tune thresholds, not strategy availability" design principle in CLAUDE.md Working Style with rejected-2026-04-30 example (CMCSA credit-spread disable that was correctly turned down — PR #837 spread threshold raise was the right fix instead).
- [x] **#62a-D4-PR2a — routing safety gate** (PR #842, 2026-04-30). Helper `should_submit_to_broker` at `brokers/execution_router.py` + 3 gate sites (autopilot entry, exit close, human approval) + `alpaca_order_sync` filter. Shadow_only portfolios cannot reach Alpaca regardless of `EXECUTION_MODE`. Includes `routing_dispatch_query_failed` critical alert with `operator_action_required` (matching H5a site 9 + H5b site 236 convention). PR2a explicitly deferred shadow fill simulation to PR2b — orders mark `execution_mode='shadow_blocked'` and stay at `status='staged'` until PR2b lands.
- [x] **#62a-D4-PR2b — shadow fill simulation** (PR #843, 2026-04-30). Wires `_process_orders_for_user(target_order_id=...)` at entry path (reuses existing TCM simulate + `_commit_fill` machinery); removes early-return at close path so shadow_blocked orders fall through to existing internal-fill block at `paper_exit_evaluator.py:1252+` (current_mark fill, matches live close semantics). `shadow_blocked` marker preserved through `_commit_fill` (which only writes filled-state fields, not `execution_mode`).
- [x] **#62a-D4-PR3 — clone-builder symbol fix** (PR #844, 2026-04-30). **Closes #62a-D4 sequence entirely.** One-line removal at `fork.py:229` (`"symbol": source.get("symbol")`). Was the upstream-most blocker — without PR3, suggestion fan-out errored at clone insert ('column symbol does not exist'). Verification SQL in PR description becomes meaningful only post-PR3 + next shadow-eligible cycle. Full shadow cohort fan-out restored after ~30 days broken: routing gated (PR2a), fills materializing (PR2b), suggestions writing with correct fields (PR3). **Caveat surfaced 2026-05-01 (see #95):** D4 sequence is shipped but operationally inert — `fork.py:_filter_for_cohort` filters every suggestion out of conservative + neutral cohorts via threshold mismatch. Shadow infrastructure runs but produces zero data until #95 ships.
- [x] **#93 — deployable_capital broker-truth fix** (PR #849, 2026-05-01). Replaced `cash_service.get_deployable_capital` body to read Alpaca `options_buying_power` directly via new helper `equity_state.get_alpaca_options_buying_power`. Removes `SUM(pending trade_suggestions.sizing_metadata.capital_required)` reservation arithmetic and stale Plaid CUR:USD reads (was returning $247.84 from 2026-03-26 against live Alpaca $500). Same architectural pattern as 2026-04-16 `_compute_weekly_pnl` fix (commit 83872db). Initial framing (PR #847) attributed yesterday's $208 reading to cohort clones; today's diagnostic showed zero clones exist (root cause is #95) — actual root causes were the BAC source row staying `pending` (paper_autopilot status-update silently bypassed, see #96) plus stale Plaid. Fix shape unchanged; broker-truth read resolves both.

### Prioritized Roadmap (post-2026-04-26)

Bucketing criteria, in order: SAFETY (live trades / P&L / execution) →
OBSERVABILITY (surfaces other bugs faster) → CORRECTNESS → CLEANUP.

**Priority 1 — Do This Week**

#62a audit complete (2026-04-26). Two small high-value drift fixes
slot in here alongside the Monday verification:

- [ ] **#65 final verification** (Monday 2026-04-27 16:30 CT scheduler
      fire — passive observation only, ~5 min check). Expected: 3
      rows with `trade_date=2026-04-27` in `policy_daily_scores`
      within 10 minutes of fire time, no
      `policy_lab_eval_cohort_failure` alerts. Final acceptance
      criterion for #65 closure.
**Priority 1 status as of 2026-04-27 evening:** drained.
- #65 verification: ✅ confirmed via natural Monday 16:30 CT
  scheduler fire (3 rows in `policy_daily_scores` for
  `trade_date=2026-04-27` written at 21:30:02Z).
- #62a-D4-PR1: ✅ applied 2026-04-26 16:41Z (see Roadmap →
  Completed and migration_apply audit row).

**Active focus (next 3, drawn from Priority 2):**
Updated 2026-05-01 (third hygiene pass) — #93 closed by PR #849.
Today's morning diagnostic surfaced #95 (fork.py threshold
semantic mismatch — D4 sequence operationally inert) and #96
(paper_autopilot status-update silently bypassed). #95 promoted
to top of active focus given high leverage (unlocks 30+ days of
shadow-cohort comparison data accumulation that the just-shipped
D4 sequence was built to support).

1. **#95** — fork.py threshold semantic mismatch (~half day).
   `_filter_for_cohort` compares `risk_adjusted_ev` (~0–2 ratio)
   against `min_score_threshold` (50/70 score scale) → all
   non-aggressive cohorts produce 0 clones forever. Recommended
   fix: switch comparison to `score` field (single-line change).
   Unblocks the D4 sequence (PR2a/PR2b/PR3) by giving it actual
   clones to gate, materialize, and write.
2. **#71** — RQ dispatch audit (~3-5 PRs depending on what
   surfaces). Sweep `public_tasks.py` / `internal_tasks.py` for
   synchronous handlers; migrate to `enqueue_job_run` pattern.
   Same shape as the policy_lab_eval diagnostic that surfaced
   the 2026-04-26 ImportError.
3. **Agent sessions observability** (~half day). Shared
   `agent_session_context` helper so Loss Min / Self-Learning /
   Profit Optimization Agents write `agent_sessions` rows (only
   Day Orchestrator currently does).

**Deferred from active focus (priority drop):**
- **#62a-D5** — execution_cost_* silently dropped (decision-needed
  item; defer until operator confirms whether signals are
  load-bearing).
- **#96** — paper_autopilot status-update silently bypassed
  (MEDIUM-LATENT). Operationally inert post-#93; investigation
  worth doing but not before #95 lands.

**Priority 2 — This Month**
- [ ] **#72 Loud-error doctrine — Phase 2 HOT fixes.** Doctrine
      ratified 2026-04-27 (see `docs/loud_error_doctrine.md`). Catalog
      of ~242 sites in backlog below. Phase 2 ships ~5 PRs:
      `#72-H1` (`equity_state` envelope-skip + `alert()` helper),
      `#72-H2` (`scheduler._fire_task` HTTP alerting), `#72-H3`
      (`@guardrail` + market_data callers), `#72-H4a/b/c`
      (workflow_orchestrator HOT swallows — split into safety,
      calibration, observability sub-PRs after diagnostic), `#72-H5`
      (paper_exit / paper_autopilot HOT swallows).
- [ ] **#71 RQ dispatch audit** — sweep `public_tasks.py` /
      `internal_tasks.py` for synchronous handlers; migrate to
      `enqueue_job_run` pattern.
- [ ] **Agent sessions observability** — shared `agent_session_context`
      helper so Loss Min / Self-Learning / Profit Optimization write rows.
- [ ] **#62a-D1 — `is_champion` column missing** (LATENT-HIGH).
      Prerequisite: resolve `'neutral'` vs `'aggressive'` intent
      disagreement between migration and code. See #62a-D1 below.
- [ ] **#62a-D3 — `regime_snapshots` table missing.** Decision needed:
      apply migration vs delete writes. See #62a-D3 below.
- [ ] **#62a-D5 — `execution_cost_*` silently dropped.** Decision
      needed: are signals load-bearing? See #62a-D5 below.
- [x] **#62a-D4-PR2 — routing dispatch enforcement.**
      **CLOSED 2026-04-30 by PR #842 (PR2a, safety gate) + PR #843
      (PR2b, shadow fill simulation).** Mid-implementation diagnostic
      surfaced architectural friction (entry path uses TCM +
      `_commit_fill`; exit close path uses inline fill at
      `current_mark` — different machineries). Split into PR2a
      (Alpaca block + `execution_mode='shadow_blocked'` marker, half
      day) and PR2b (TCM simulate + commit for entry; fall-through
      to internal-fill block for closes, half day).
      `should_submit_to_broker` helper at `brokers/execution_router.py`.
      New `routing_dispatch_query_failed` critical alert with
      `operator_action_required`.
- [x] **#62a-D4-PR3 — symbol drop fix.**
      **CLOSED 2026-04-30 by PR #844.** One-line removal at
      `fork.py:229`. Was the upstream-most blocker — without PR3,
      suggestion fan-out errored at clone insert (`column "symbol"
      does not exist`), meaning PR2a/PR2b had nothing to gate or
      materialize for Conservative + Neutral cohorts. **Closes
      #62a-D4 sequence entirely.** Full shadow cohort fan-out
      restored after ~30 days broken: routing gated (PR2a), fills
      materializing (PR2b), suggestions writing with correct fields
      (PR3).
(#68 and #69 demoted from Priority 2 to Priority 4 on 2026-04-27
after the Polygon plan upgrade resolved #87 — see *Polygon
dependency status* and the entries below.)

**Priority 3 — Next Quarter**
- [ ] **GAP 1** — Canonical ranking metric (PnL ÷ marginal risk,
      correlation-adjusted). Hold until P2 observability ships.
- [ ] **GAP 2** — EV-aware exit ranking. Depends on GAP 1.
- [ ] **GAP 3** — Calibration deepening (segment by strategy / regime /
      DTE / liquidity). Gated on ≥30d micro_live data.
- [ ] **GAP 4** — Autotune walk-forward replacement. After GAP 3.
- [ ] **#62 — Migration drift reconciliation** (329 cols + 12 tables).
      Multi-PR effort, sequenced from #62a catalog.
- [ ] **#62a-D6 — `model_governance_states` table missing.** Apply
      table-creation portion of `20251215000000_learned_nesting_v3.sql`,
      OR delete writes if v3 is dormant.
- [ ] **#62a-D7 — `shadow_cohort_daily` table missing.** Consumer
      feature is permanently off; recommend remove writer rather
      than apply migration.
- [ ] **#62a-D8 — `trade_executions` 8 wrong columns.** Investigation
      first: is `register_execution` still on any active path?
- [ ] **#73 — Remove dead `GET /policy-lab/results` endpoint and
      `policy_lab_daily_results` table.** Gated on #65 fully closed.
- [ ] **#66 Polygon Tier 1 — dead-code deletion** (`polygon_client.py`,
      `_get_option_snapshot_api`). Wait until #69 lands so callers gone.
- [ ] **Dead-code sweep:** v4 accounting ledger, outcomes_log chain,
      strategy_backtest v3 endpoints, adaptive-caps stack
      (`RiskEngine.get_active_policy`, `apply_adaptive_caps`).
- [ ] **Drop-unused-tables migration:** `outcomes_log`,
      `risk_budget_policies`, `risk_state`, `signal_weight_history`,
      `strategy_adjustments`, v4 accounting ledger,
      `strategy_backtest_folds/trades/events`.

**Priority 4 — Deferred (no plan to do)**
- [ ] **#68 Polygon Tier 2 — `universe_service` Alpaca migration.**
      Original 429-elimination motivation resolved by 2026-04-27
      Polygon plan upgrade. Reactivate if Polygon billing changes
      or live Alpaca account unlocks SIP. Provider-redundancy value
      remains.
- [ ] **#69 Polygon Tier 2 — `market_data.py` base-layer migration.**
      Same status as #68. Foundational refactor for Alpaca-primary
      future; not urgent post-upgrade.
- [ ] **#70 Polygon Tier 3** (HARD_TO_REPLACE Supabase-cache strategy).
      Permanent residual post-upgrade. `get_ticker_details` /
      `get_last_financials_date` cacheable subset overlaps with
      #87b; `I:VIX` is forever-Polygon by necessity.
- [ ] **Replay subsystem evaluation** — gated on micro_live stable for
      30+ days. Wire up or remove.
- [ ] **GHA `trading_tasks.yml` cleanup** (~1000 LOC unreachable
      schedule blocks). APScheduler is primary; pure hygiene.
- [ ] **#62a-D9 — `trade_suggestions` rebalance flow extra cols.**
      Cleanup batch (verify cold then fix or remove endpoint).
- [ ] **#62a-D11 — `symbol_regime_snapshots`** — note only, no active
      writer.
- [ ] **#62a-D12 — Out-of-band tables** — acknowledge, do not rebuild
      migration history.
- [ ] **Full live automation** — final, after GAPs 1-4.

### Notable findings 2026-04-26 (Sunday)

#67 was queued as Priority 1 SAFETY work based on Saturday's
Diagnostic B premise that `outcome_aggregator` was corrupting the
calibration loop. Sunday's pre-fix diagnostic showed the premise
was wrong:

- `outcome_aggregator.py` has never run in production.
- `outcomes_log` table is empty for all time (zero rows ever).
- Calibration reads `learning_feedback_loops`, not `outcomes_log`.
- Six test files were already marked dead (Cluster I, PR #9 / #770).

The error in Saturday's analysis was inferring the consumption chain
from code structure rather than verifying through DB state and a
caller search. Pattern lesson: when claiming a path is "live and
hot," verify with `COUNT(*)` on the destination table and grep for
scheduler bindings.

Outcome: #67 demoted to dead-code cleanup. The Priority 1 SAFETY
slot is filled by `_estimate_equity` / `_compute_weekly_pnl`
consolidation plus the #62a schema drift audit kickoff — **not** by
close-path consolidation, which was already completed by PR #796 +
PR #802 and lives in the Completed list. #62a was elevated to
Priority 2 (with kickoff in Priority 1) due to a third confirmed
instance of the schema-drift pattern in one week.

**Pattern check applied 2026-04-26:** even immediately after
documenting this lesson, the operator's first revision of the
backlog update attempted to re-add close-path consolidation to
Priority 1 (which was completed by PR #796 / PR #802) and reference
a "Sequence" section that exists only in chat history, not in
CLAUDE.md. Both errors caught pre-apply via verification against
current file state. The lesson generalizes: verify the file state
before making edits to it, not just the consumption chain before
claiming behavior.

### Backlog/PR closure discipline gap (2026-04-26)

Two Priority 1 items in two consecutive sessions were found to be
already completed by earlier PRs:

- **Close-path consolidation:** completed by PR #796 + PR #802, but
  item remained in Priority 1 until 2026-04-26 backlog correction.
- **`_estimate_equity` / `_compute_weekly_pnl` consolidation:**
  completed by PR #780 (2026-04-19) + PR #795 (2026-04-22), but item
  remained in Priority 1 until 2026-04-26 (this session).

Root cause: the backlog tracked deferral commitments but PRs
fulfilling them did not close those entries back into CLAUDE.md.
Result: operator energy spent investigating what's already done.

Process fix: every PR that fulfills a backlog item should include a
CLAUDE.md edit marking the item DONE in the same PR. The PR
description should reference the specific backlog line being closed.
Future backlog audits should expect Priority 1 items to be small and
active, not commitment shadows from weeks-old commits.

Pattern check: the diagnostic discipline lessons documented today
("verify consumption chain before claiming behavior" + "verify file
state before editing it") apply equally to backlog state. Verify
backlog-tracked work is actually outstanding before scheduling work
against it.

### #62a-D4 fix scope correction (2026-04-26)

Audit catalog flagged D4 as a 1-hour fix (one-line drop). Diagnostic
revealed a routing safety question that wasn't visible from static
analysis. Fix scope correctly expanded from 1 PR to 3 PRs after
understanding the architectural intent (shadow cohorts are
paper-only learning channels, must be enforced regardless of
`EXECUTION_MODE`).

Pattern: audit catalogs surface candidate symptoms. Architectural
intent (the "why") often determines the right fix shape, and intent
isn't always visible from code alone — sometimes requires operator
clarification.

This is the 5th time this weekend that diagnostic-first discipline
caught something audit-surface analysis missed. The discipline is
robust enough to formalize as protocol: every backlog fix begins
with diagnosis, then design conversation, then implementation.

### #72-H4 audit-vs-actual scope correction (2026-04-27)

Audit catalog flagged ~25 sites in `workflow_orchestrator.py` as
P1/P2 violations and estimated ~1 day of work. Diagnostic-first
review reduced scope to **11 actionable sites**:

- 3 sites are VALID under doctrine (input parsing fallback, typed
  coercion with sentinel return, multi-source fallback intermediate).
- 3 sites are DEAD-leaning (Replay subsystem gated off via
  `REPLAY_ENABLE=0`).
- 2 sites OVERLAP with `#62a-D3` (writing to non-existent
  `regime_snapshots` table).
- 11 sites are genuine HOT silent failures, naturally grouped into
  trade-decision safety (2), calibration data integrity (4), and
  audit/ancillary (5).

The 11 actionable sites were split into three sub-PRs (`#72-H4a`,
`#72-H4b`, `#72-H4c`) matching the H1-H3 cadence rather than one
"~1 day" PR.

This is the **third** time this weekend an audit's apparent scope
reduced significantly under investigation:

- **#62a schema drift audit:** ~25 instances → ~12 actionable
- **#67 outcome_aggregator hardening:** 5 sites → all dead
- **#72-H4 workflow_orchestrator HOT swallows:** ~25 sites → 11 actionable

The diagnostic discipline reliably distinguishes "audit-flagged"
from "actually-broken." Worth continuing to apply, especially when
catalog estimates feel unrelatedly large (e.g., a "~1 day" item that
doesn't match the file's logical structure usually has hidden
VALID/DEAD/OVERLAP entries).

### #87 diagnostic-vs-actual root cause (2026-04-27)

The #87 diagnostic correctly identified contributing factors
(deploy-induced cold cache, retry amplification, missing
`scanner_universe` metadata) but **underweighted the actual root
cause**: Polygon Basic-tier rate limit (5/min/product) plus
missing entitlements for snapshot/Greeks/IV/OI endpoints. The
`403 NOT_AUTHORIZED` errors visible in worker logs were the
clearest signal pointing at plan-tier, but the diagnostic
narrative leaned on the 429 patterns instead.

Lesson: when a web search returns "paid plans are unlimited" and
the production data shows persistent 429s plus 403s, verify the
actual plan tier first (5-min operator dashboard check) before
building cold-cache or rate-limiter theories. The cheap operator
action shifts diagnostic weight in minutes — and is the kind of
verification step that diagnose-first protocol benefits from
adding alongside its existing "audit-surface vs actually-broken"
filter.

Pattern observed this weekend across #62a, #67, #72-H4, and #87:
diagnose-first correctly distinguishes audit surface from working
truth, but cheap external state checks (plan tiers, env vars,
dashboard settings, billing pages) deserve equal weight. Adding
"check the cheapest external thing first" as a parallel discipline
would have shifted multiple diagnostics from hours to minutes.

### Backlog hygiene check (2026-04-27 evening)

`#62a-D4-PR1` was listed as Priority 1 *pending manual apply*
despite being applied 24h prior (2026-04-26 16:41Z, audit row in
`risk_alerts.alert_type='migration_apply'`). This is the third
closure-discipline gap surfaced this weekend (Saturday's commit
messages referencing closed items, today's PR #828/#829
prioritization re-adding completed items, tonight's D4-PR1
phantom-pending). Pattern is documentation drift, not operator
error — applied migrations and merged PRs don't have an
automatic step that updates the backlog tracker.

Procedure fix: *Migration Apply Procedure* gains step 8 below —
"Update backlog tracker" — to make backlog closure part of the
apply workflow rather than a separate hygiene pass. Same step
should be folded into the PR Merge Procedure when one is
formalized.

---

