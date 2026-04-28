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
1. **#72-H4c** — workflow_orchestrator audit + ancillary doctrine
   sites (~half day).
2. **#87b** — `scanner_universe` metadata backfill (~half day,
   reduces per-cycle Polygon calls).
3. **#62a-D4-PR2** — routing dispatch enforcement (~1 day; builds
   on D4-PR1 to make conservative/neutral cohorts actually skip
   live dispatch).

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
- [ ] **#62a-D4-PR2 — routing dispatch enforcement** (~1 day, MEDIUM
      risk). Broker dispatch checks `portfolio.routing_mode`;
      `_simulate_fill` path for `shadow_only`. Tests assert
      shadow_only portfolios never reach Alpaca regardless of
      `EXECUTION_MODE`. Sequenced after PR1.
- [ ] **#62a-D4-PR3 — symbol drop fix** (~5 min code + 30 min verify).
      Original one-line drop. Sequenced last; LOW risk after PR1+PR2.
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

