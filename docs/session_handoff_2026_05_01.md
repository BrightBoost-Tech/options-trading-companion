# Session Handoff — End of Day 3 (2026-05-01)

## Conversation context
- Multi-day options-trading-companion engineering session, Wed → Fri
- This is end of Day 3 Friday night ~10pm CDT
- Predecessor transcript: /mnt/transcripts/2026-05-02-04-04-58-options-trading-day-two-live-deployment.txt
- Conversation arc Day 3: live deployment validation → first live
  trade → ghost position incident → architectural diagnostics →
  Option A design

## Current operational state

### Live Alpaca account
- Account: 211900084
- Funded: $650 (added $200 Friday evening, was $500)
- Phase: micro_live since 2026-04-25 17:10Z
- BAC SPREAD STILL OPEN AT BROKER:
  - Long: BAC260605C00051000 (long $51 call), qty 1
  - Short: BAC260605C00056000 (short $56 call), qty -1
  - Net P/L: ~-$50 as of 21:52 CDT Friday
- Operator plan: manual close Monday 9:30 AM ET via Alpaca UI

### Today's incident summary
- 16:30 UTC: BAC entry filled at Alpaca (first true live trade in
  system history). Entry worked.
- 16:45 UTC: force-close fired. Alpaca rejected close 3x with
  "insufficient options buying power" (required $296, available $204).
- submit_and_track marked needs_manual_review, returned dict (didn't
  raise). H5a alert at paper_exit_evaluator only fires on raised
  exceptions → silent for 5+ hours.
- Operator discovered ghost position via Alpaca dashboard inspection.

### Root cause analysis (architectural)
- Sizing engine at sizing_engine.py:102 only checks
  contracts_by_collateral = floor(account_buying_power /
  collateral_required_per_contract).
- No round-trip BP check. System sizes into trades it cannot
  safely close.
- For long debit spreads: closing requires buy-to-close on short
  leg. Alpaca's pre-trade margin gate treats this conservatively
  (~entry_premium needed). Account couldn't afford close → stuck.
- 100% of recent live trade flow (last 13 trades) is debit spreads.
  All carry this risk shape.

## PRs shipped this session

### Day 1 (Wed 2026-04-29)
- #837 — tier-aware spread threshold (#92 closed)

### Day 2 (Thu 2026-04-30)
- #838 — H5a paper_exit_evaluator alerts
- #839 — H5b paper_autopilot_service alerts (closes #72-Phase 2)
- #840 — backlog hygiene
- #841 — iron condor doc clarification + design principle
- #842 — D4-PR2a routing safety gate
- #843 — D4-PR2b shadow fill simulation
- #844 — D4-PR3 closes D4 sequence
- #845 — second hygiene pass
- #846 — A4 loud-error + CLAUDE.md fixes (EXECUTION_MODE='micro_live'
  misroute fix)
- #847 — backlog add #93 + #94 (with amendment after diagnostic
  refinement)
- #850 — #93 fix (deployable_capital broker-truth read)
- #851 — #95 fix (fork.py threshold semantic mismatch)

### Day 3 (Fri 2026-05-01)
- #853 — #98 loud alert at submit_and_track needs_manual_review
  write site (Option C from BP-to-close diagnostic)

## Verified working in production
- #93 deployable_capital broker-truth read — $500 confirmed in
  16:00 UTC cycle (vs yesterday's $208 stale Plaid)
- #95 score persistence in sizing_metadata — BAC sizing_metadata.score=76.9
- PR2a routing gate — BAC routed live with alpaca_order_id (correct)
- Force-close envelope — per-symbol -8% breach detected, alert fired
  at 16:45:25
- First live trade ENTRY successful (close failed)

## Open issues (NOT YET IN BACKLOG — pending Sunday amendment PR)

### #97 — fork.py clone INSERT silent failure (HIGH)
- Filter ACCEPTS BAC for all 3 cohorts (per policy_decisions empty
  reason_codes)
- Insert at fork.py:123 silently fails for non-aggressive cohorts
- Try/except at fork.py:118-129 swallows with logger.warning, no
  DB-visible alert
- Conservative + neutral cohorts produce 0 clones for entire DB
  history across ALL users
- Likely missing NOT NULL field in _clone_suggestion_for_cohort
  return dict OR unique constraint hit
- D4 sequence (PR2a/PR2b/PR3) is shipped but cohort-clone-dependent
  paths remain inert

### #98 — ghost prevention (PARTIAL — Option C shipped)
- PR #853 ships loud alert at submit_and_track:231 needs_manual_review
  write
- Option B (sweep expansion for stale needs_manual_review) deferred
  as defense-in-depth, not yet shipped

### #100 — round-trip BP at sizing (HIGH — design doc complete)
- Design doc: docs/designs/option_a_round_trip_bp.md
- Implementation planned Saturday-Sunday
- Formula A (entry-premium-based): estimated_close_bp =
  max_loss_per_contract for debit spreads
- safety_factor=1.1 starting calibration (10% headroom)
- Single-call-site change at workflow_orchestrator.py:2643
- Test surface: 3 source-level + 9 helper behavioral + 7 sizing
  integration + 1 regression query
- Effort refined from "1-2 days" to "~half day" via Formula A
  eliminating quote infrastructure

### #101 — STRATEGIES_ALLOWLIST env knob (MEDIUM, optional)
- Allows scanner restriction to specific strategy types via env
- Useful as kill-switch during incidents
- Half day implementation if needed later

### #102 — Round-trip safety as sizing invariant (DOCTRINE)
- Add to design principles: "Sizing must verify the position can
  be safely round-tripped within available buying power, not just
  that entry fits"

### #103 — Regime → strategy selection breadth audit (LOW)
- 100% of recent live trades are LONG_CALL_DEBIT_SPREAD
- May be regime-driven natural selection or coverage gap
- Investigate whether other strategies are reachable in their
  appropriate regimes

### Doctrine candidates
- H6 — "Verify code path exercised in production before shipping
  safety logic for it" (3 instances this session)
- H7 — "When system models capital as single number, verify
  operations preserve invariants in BOTH directions"
- H5c — "Alerts at exception-raising sites don't catch dict-return
  failure markers; both modes need observability"

## Already in backlog — need Sunday amendment

### #93 — already merged but framing was wrong
- Original framing: "cohort clones cause within-day degradation"
- Corrected framing: "stale Plaid CUR:USD + paper_autopilot status
  update bypass; cohort clone narrative was wrong (zero clones
  in DB history)"
- Fix shape (option b: read Alpaca options_buying_power) was correct
  regardless

### #94 — needs update post-#95
- Originally: "phantom-pending row hygiene"
- Now: "phantom-row hygiene" — daily cleanup transitions pending →
  dismissed but rows still accumulate

### #95 — keep open
- Score persistence verified
- Filter accepts conservative+neutral
- But clone INSERT silently fails (#97)
- Full D4 verification blocked until #97 resolves

### #96 — promote MEDIUM-LATENT → MEDIUM
- Reproduced at scale today (BAC source row stayed pending despite
  autopilot firing)
- 2 occurrences in 24 hours

## Weekend plan (committed by operator Friday night)

**Path A1 — careful weekend ship of Option A:**
- Saturday morning: read design doc + run regression query first
  (against last 30 days, both $500 and $650 baselines)
- Saturday afternoon: implementation per design doc
- Sunday morning: tests + regression analysis
- Sunday evening: comprehensive backlog amendment PR (11+ items)
- Monday morning: manual close BAC + reconcile DB + merge both PRs

## Monday operational plan

**Pre-market (~9:00 AM ET):**
- Verify Alpaca position state matches Friday close
- If state changed (assignment, exercise): STOP, investigate

**Market open (~9:30 AM ET):**
- Manual close both BAC legs via Alpaca UI
- Note actual fill prices for DB reconciliation

**~9:35 AM ET:**
- UPDATE paper_positions: status='closed', closed_at=NOW(),
  realized_pl=<from Alpaca fills>
- UPDATE paper_orders: close-order from needs_manual_review →
  manual_close_complete

**Pre-cycle (before 16:00 UTC):**
- Verify Option A merged + Railway redeployed
- Set EXECUTION_MODE=alpaca_paper for ONE verification cycle

**16:00 UTC cycle:**
- Paper-mode run validates Option A behavior on real candidates
  without real money
- Watch for: round-trip BP rejections, sizing log lines, any alerts

**If clean: Tuesday returns to alpaca_live with Option A protecting**

## Conversation patterns to continue

- Diagnostic-first discipline (read DB, read code, then propose;
  don't pattern-match)
- Loud-error doctrine v1.0 (alert + None return; never silent
  swallow without surfacing)
- Push back on premature ship recommendations (operator can override)
- Real-money discipline (broker state verification trumps code purity)
- Verify code path exercised in production before shipping safety
  logic for it (H6 doctrine candidate)
- Capture findings durably in backlog/design docs, not just chat
- Honest pacing reads (flag fatigue/scope concerns; respect operator
  override)

## Key file references

- docs/designs/option_a_round_trip_bp.md — Option A spec (357 lines,
  complete)
- docs/backlog.md — current state (#93/#94 amended, others pending)
- docs/loud_error_doctrine.md — v1.0 deployed
- CLAUDE.md — operator-facing system overview (recently updated
  with EXECUTION_MODE clarification + per-symbol risk envelope)
- packages/quantum/services/sizing_engine.py — Option A integration
  point at line 102/106
- packages/quantum/services/workflow_orchestrator.py:2643 — sizing
  call site
- packages/quantum/services/cash_service.py — #93 fix (Alpaca-truth read)
- packages/quantum/services/equity_state.py — Alpaca-truth helpers
- packages/quantum/policy_lab/fork.py — #95 fix (line 165) + #97
  silent swallow site (line 118-129, line 123)
- packages/quantum/services/paper_autopilot_service.py:457 — #96
  status-update bypass
- packages/quantum/brokers/alpaca_order_handler.py:231-240 — #98
  alert site (just shipped)

## How to start the new chat

Recommended first message:

"Continuing options-trading-companion engineering session, end of
Day 3 → Day 4. Read docs/session_handoff_2026_05_01.md for full
context. Current state: BAC spread open at broker awaiting Monday
manual close, Option A design complete in docs/designs/option_a_round_trip_bp.md,
weekend plan is Path A1 (careful Saturday-Sunday ship). Today's
task: <whatever you're starting with — 'read design doc and run
regression query' is Saturday's first task>."

After that, new-Claude has enough context. It can read specific
files as needed via the view tool, and read the predecessor
transcript at /mnt/transcripts/2026-05-02-04-04-58-options-trading-day-two-live-deployment.txt
for any specific historical detail.
