# Options Trading Companion — Project Doctrine
# Loaded by Claude Code on EVERY turn. DOCTRINE AND POINTERS, NOT VALUES:
# any fact that changes (equity, OBP, positions, counts, phase) is a POINTER
# to its source of truth, never an embedded number. Stale embedded state
# caused real phantom reads; this structure is the fix.
# Rewritten 2026-06-10 (≤40k chars). Pre-rewrite snapshot: docs/history.md.

---

## 1. TRUTH DOCTRINE — read this before trusting anything, including yourself

Four sources, in precedence order (lowest to highest):

1. **CODE** — what's written. Read it; never assume. Comments and docstrings
   routinely describe unbuilt behavior (see §8 Known Liars).
2. **SUPABASE** — what happened. Query it via MCP. DB *marks/unrealized P&L
   are NOT authoritative* — they lag and can be wrong-signed (#1022 phantom
   class). DB rows of record (job_runs, orders, suggestions, alerts) are.
3. **RAILWAY** — what's actually RUNNING: deployment SHA + container start +
   effective env. Merged ≠ running (§2).
4. **ALPACA** — broker truth: fills, positions, buying power. **Outranks
   everything above.** Deployable capital = live `options_buying_power`
   (settled funds; `equity_state.get_alpaca_options_buying_power`, 60s TTL).
   The cash↔OBP gap is the broker's own unsettled funds (T+1), not our bug.

Corollaries:
- **Debug prints and displays lie.** `[EXIT_EVAL_DEBUG]` prints flat default
  thresholds while the decision path is cohort-aware and time-scaled. The
  decision path is the only truth; a log line that doesn't compute through
  the same functions as the decision is a hypothesis about the code.
- **Verify before asserting — including your own confident reads.** Multiple
  confident claims this project ("the flag is on", "the gate fired", "that
  symbol is illiquid") were overturned by one direct query against the right
  source. A claim with multi-source agreement is a finding; anything else is
  a hypothesis and must be labeled as one. If two sources disagree, the
  disagreement IS the finding — report it, never average it.
- **H11:** every status check includes a baseline query of critical/high
  `risk_alerts` regardless of the hypothesis being checked.
- **H10:** on any manual operator intervention (e.g. closing via the Alpaca
  UI), DB reconciliation is the FIRST follow-up. `ghost_position` alerts are
  urgent, not noise.

## 2. DEPLOY DOCTRINE

- **Merged ≠ running (H8).** Verify against `origin/main`, not local (the
  06-09 quarantine/honesty commits sat unpushed while "merged"). The repo
  SQUASH-merges: original SHAs are not ancestors of main — verify deployed
  code by CONTENT at the squashed SHA. After every merge: Railway deployment
  SUCCESS + container start > merge time + flags read back on the running
  process.
- **Every merge to main auto-deploys and recycles the worker — doc-only PRs
  included.** A recycle resets all once-per-process state (e.g. the
  conviction DEGRADED line fires once per container). Ship sequential,
  attributable deltas: one recycle per behavioral change wherever possible.
- **Migration-before-merge** for any PR that reads a new table/column
  (`docs/migration_procedure.md`). Env-first for new flags: set + read back
  BEFORE the code that reads them lands.
- **No building or merging during market hours. No fix-forward mid-session.**
  An anomaly during RTH gets: evidence capture first, then at most ONE
  sanctioned kill switch flip (§4 registry lists them). Diagnosis and fixes
  happen after 20:00Z.
- Workers don't hot-reload: RQ/APScheduler processes pick up code only on
  recycle. "PR shipped, behavior unchanged" usually means the worker wasn't
  recycled — check the deployment list before debugging the code.

## 3. FLAG POLARITY DOCTRINE

- **Safety/tightening controls: default-ON.** Unset/empty → ON; only an
  explicit `0/false/no/off` disables. An empty string must never silently
  no-op (the INTRADAY_TARGET_PROFIT burn). Test-pinned both ways.
  Canonical: ENTRY_QUOTE_VALIDATION_ENABLED, REENTRY_COOLDOWN_ENABLED,
  CLOSE_REARM_ENABLED, INTRADAY_COHORT_STOP_ENABLED,
  CALIBRATION_STALENESS_TTL_ENABLED, ENTRY_QUOTE_SOURCE_ALIGNED.
- **Behavioral/loosening changes: explicit opt-in.** Requires exactly `=1`;
  absent/empty/`true` → the stricter legacy behavior, so an env regression
  fails SAFE. A non-empty non-`1` value logs an explicit WARNING.
  Canonical: RISK_UTILIZATION_GATE_ENABLED (and its threshold
  RISK_MAX_UTILIZATION_PCT has NO implicit default — enabled-but-unset
  fails closed).
- **Flags must be read-back-confirmed** on the running process, not assumed
  from the dashboard. Some legacy flags strict-parse `== "1"`
  (INTRADAY_TARGET_PROFIT_ENABLED) — check the parse before trusting a
  `true`. Startup flag-echo is backlogged (P2).

## 4. ACTIVE CONTROLS REGISTRY

One entry per live control: behavior · flag/polarity · kill switch ·
exercised-status. Verify current flag values on Railway, never here.

- **#1038 entry-quote rejection** — an OPEN order with ANY leg unpriceable at
  stage time raises `EntryQuoteUnpriceable` (error, never a fabricated
  fill). Closes exempt (position_id set). Flag
  `ENTRY_QUOTE_VALIDATION_ENABLED`, default-ON. Kill: explicit falsy.
  Exercised: first live rejections 2026-06-10 (3 XLE forks, dead leg).
  ⚠ Seam: a future add-to-position entry carries a position_id and would be
  wrongly exempted.
- **#1040 re-entry cooldown** — a symbol stopped by the per-symbol loss
  envelope is hard-benched per (cohort, symbol) until next session open;
  durable in PG `reentry_cooldowns`; writer keyed on the envelope's
  structured `symbol_loss_stops` (never daily/weekly/concentration); FILTER
  gate pre-ranking + fail-closed STAGE gate. Flag `REENTRY_COOLDOWN_ENABLED`
  default-ON. Exercised: UNEXERCISED (no stop since deploy).
- **#1042 learning quarantine** — fail-closed `outcome_type` allowlist on
  live-affecting learning reads (conviction legacy, autotune); historical-
  simulation rows can't feed live multipliers. Flag
  `LEARNING_HISTORICAL_QUARANTINE_ENABLED` default-ON. Exercised: yes
  (conviction reads).
- **#1043 conviction fallback honesty** — the V3→legacy drop logs
  `[CONVICTION] … DEGRADED` once per process. The v3 view
  (`learning_performance_summary_v3`) is STILL MISSING — the line is
  designed honesty, not an incident; it reappears once after every recycle.
  No flag. Exercised: verified 06-10/06-11.
- **#1044 utilization gate** — small-tier entry capital control:
  `(committed + candidate)/(committed + settled OBP) ≤
  RISK_MAX_UTILIZATION_PCT` (pro-forma; broker cost basis, fresh reads,
  fail-closed). Replaces the share-of-book `concentration_symbol` BLOCK
  (demoted to WARN at small tier when on). Flag
  `RISK_UTILIZATION_GATE_ENABLED` — **explicit =1** (behavioral). Kill:
  unset → legacy concentration BLOCK. Exercised: 06-10 (breaker proceeded
  where 06-09 blocked); evaluation lines WARNING-level since #1051.
- **#1045 calibration circuit** — window escalation 30→60→90 on
  insufficient data; consumer TTL (`CALIBRATION_MAX_AGE_DAYS`, stale blob →
  `{}` + `calibration_stale` alert); `_overall` fallback (no silent ×1.0);
  ops_health OUTPUT_FRESHNESS registry (job RAN ≠ job WROTE). Kill:
  `CALIBRATION_STALENESS_TTL_ENABLED` falsy → legacy serve-stale.
  **Partially superseded by #1051's epoch** (below). Exercised: first
  escalated write 06-10 10:00Z.
- **#1046 exit re-arm** — a terminal-'cancelled' close order blocks retries
  only while fresh (30min) or budget-tripped (≥3/4h → block + critical
  `exit_protection_disarmed`); stale terminal failures RE-ARM the exits
  (kills the permanent-disarm class). Flag `CLOSE_REARM_ENABLED` default-ON.
  Exercised: UNEXERCISED (no terminal-cancelled close since).
- **#1047 spread re-key** — the 0.30 combo spread threshold keys on PRICE
  CLASS (`micro tier OR underlying < PRICE_CLASS_SPREAD_CUTOFF`, default
  $60), not account tier (crossing the $1k cliff had silently tightened the
  funnel 3×). Kill: `PRICE_CLASS_SPREAD_CUTOFF=0` restores tier-only.
  Exercised: 06-10 (threshold 0.3 in spread_debug on sub-$60; first
  2-candidate day).
- **#1048 cohort stops intraday** — the 15-min monitor evaluates stop_loss
  against COHORT conditions (not the flat 0.50 default); shadows' only loss
  protection. Flag `INTRADAY_COHORT_STOP_ENABLED` default-ON. Fail-safe →
  default (looser, never misfires). Exercised: loaded every cycle; no
  cohort-stop breach yet. ⚠ The EXIT_EVAL_DEBUG print still lies about
  these thresholds (ticketed P1).
- **#1049 order-sync O(open)** — Step-3 stuck-open reconcile scoped to the
  open-position id set (was O(all historical closes), ~52k queries/14d). No
  flag. Exercised: duration 6.5s→1.38s verified 06-10.
- **#1051 honest PoP + epoch + dedup** — debit-spread PoP computes breakeven
  interpolation (scanner passes legs; `credit=premium` for debit), not raw
  long-leg delta (the sign-flip class: NFLX staged +95.67 vs honest ≈ −26).
  **NO flag by design — rollback = revert PR + owner sign-off.**
  `CALIBRATION_EV_EPOCH` (default 2026-06-11): pre-fix prediction/outcome
  pairs never calibrate the post-fix predictor; calibration runs RAW MODE
  (empty blob, deploy-time reset) until ≥8 post-epoch closes — a
  `calibration_stale` alert ~06-20 is the DESIGNED reminder of raw mode,
  not a defect. Learning ingest: position-level dedup + `is_paper` resolved
  from routing (live fills distinguishable). Riders: `blocked_reason/_detail`
  stamped on every stage-time rejection; gate/cohort log lines at WARNING.
- **#1052 stage-quote alignment** — entry-leg validation reads the
  scanner's source set (truth layer: Alpaca options snapshots primary →
  Polygon fallback), legacy Polygon NBBO always probed as final fallback +
  divergence recorder (`[ENTRY_QUOTE] FEED DIVERGENCE` WARNING). All-
  sources-dark still rejects. Flag `ENTRY_QUOTE_SOURCE_ALIGNED` default-ON;
  explicit falsy → Polygon-only. Exercised: pending first staged candidate.

Sanctioned mid-session kill switches, complete list: the explicit-falsy
flags above (#1038, #1040, #1046, #1048, #1045-TTL, #1052), unset
`RISK_UTILIZATION_GATE_ENABLED` (reverts to the stricter BLOCK),
`PRICE_CLASS_SPREAD_CUTOFF=0`, and the global trio
`SCHEDULER_ENABLED` / `CALIBRATION_ENABLED` / `RISK_ENVELOPE_ENFORCE`.
The #1051 PoP fix deliberately has no switch.

## 5. RISK FRAME

Constraint stack, in evaluation order (current numbers: query, don't trust
docs — H14):

1. **Settled-OBP truth** — deployable = live Alpaca `options_buying_power`
   (60s TTL). Never equity, never a DB snapshot.
2. **Utilization 85%** (#1044, small tier) — pro-forma total-utilization cap.
3. **Envelopes** (`risk/risk_envelope.py`) with severities:
   `concentration_symbol` block (WARN at small tier under #1044) ·
   sector/expiry/stress/greeks warn · earnings-count block ·
   daily/weekly/per-symbol loss **force_close**. `passed=False` only on
   block/force_close — warns never block.
4. **Per-symbol $ allocation cap** (RiskBudgetEngine `underlying_allocation`)
   — separate code from the envelope share-of-book check, deliberately.
5. **Per-candidate allocator split** (small tier: 0.85×regime×equity over ≤4
   candidates, 36% per-trade ceiling, score skew).
6. **H7 round-trip BP** (entry AND exit must fit) → per-contract floor.

Loss-control precedence on a live position: **per-symbol envelope (−3% of
equity, 15-min cadence) binds before cohort stops (0.15/0.20/0.30 flat, now
also 15-min via #1048) binds before the vestigial 0.50 position stop.** This
asymmetry is deliberate-but-undecided at compounding capital — the coherence
question is BACKLOGGED (P2); do not "fix" it ad hoc, and NEVER loosen the
stop to reduce re-entry whipsaw (that's what #1040 is for).

- **PDT is RETIRED** (FINRA, 2026-06-04; Alpaca same day). daytrade
  fields are placeholders. The real costs of trade velocity are fees
  (~$1–2/round-trip) and #1040 cooldown benches — nothing else.
- **Never loosen a control on outcome or hindsight.** A losing trade that
  passed every gate is not evidence a gate is wrong; a gate-killed trade
  that would have won is ONE data point for the audit's counterfactual
  lens, not a loosening argument. Measurement-basis corrections (honest
  PoP, broker-true P&L feeds, source-aligned quotes) are NOT loosening —
  they change what is measured, not what is permitted.
- Cohorts: 3 books (aggressive = live champion via
  `policy_lab_cohorts.promoted_at`; neutral + conservative shadow-only,
  internal fills, no real capital, no envelope backstop — cohort stops are
  their protection).

## 6. ARCHITECTURE MAP

**Infra pointers** (stable identifiers, not state): repo
`BrightBoost-Tech/options-trading-companion` · owner UUID
`75ee12ad-b119-4f32-aeea-19b4ef55d587` · Railway project
`empowering-commitment` (services: BE, worker [RQ `otc`], worker-background
[RQ `background`], FE, Redis) · Supabase `etdlladeorfgdmsopzmz` · Alpaca
LIVE `211900084` (margin, options L3) + paper `PA3I8CYLXBOS` (creds in
Railway worker env — never pin key prefixes in docs) · Polygon Stocks
Starter + Options Developer (no index entitlement). Python 3.11 required
(3.14+ incompatible via qci-client). Live trading requires BOTH
`EXECUTION_MODE=alpaca_live` AND `LIVE_ENABLED=true`; `ALPACA_PAPER` (BE/
worker) and `ALPACA_PAPER_TRADE` (MCP) are different layers — both must be
false for live.

**Pipeline** (file pointers; read the file, not this summary):

- Scan: `options_scanner.py` `scan_for_opportunities` → per-symbol
  `process_symbol` (universe from `scanner_universe` via
  `services/universe_service.py`, limit `UNIVERSE_SCAN_LIMIT` default 100 >
  active count → everything evaluates; every rejection →
  `suggestion_rejections` with `spread_debug`).
- Score: EV/PoP `ev_calculator.py` (breakeven interpolation for debit —
  #1051) → conviction `analytics/conviction_service.py` (v3 missing →
  legacy, quarantined reads) → calibration `analytics/calibration_service.py`
  (`apply_calibration`; raw mode until post-epoch data) → ranking
  `analytics/canonical_ranker.py` (MIN_EDGE_AFTER_COSTS gate).
- Size: `services/risk_budget_engine.py` + `PortfolioAllocator` +
  `services/analytics/small_account_compounder.py` (`get_tier` —
  capital-based, hard $1k/$5k cliffs).
- Execute: `services/paper_autopilot_service.py` — circuit breaker
  (`check_all_envelopes` + #1044 demotion) → `_execute_per_cohort` per
  suggestion: cooldown FILTER/STAGE gates → utilization gate →
  `_stage_order_internal` (`paper_endpoints.py`; #1038 validation on the
  #1052-aligned fetch) → broker via `brokers/execution_router.py` /
  `alpaca_order_handler.py` (watchdog cancels idle DAY limits ~5min).
- Monitor: `jobs/handlers/intraday_risk_monitor.py` (15-min: mark refresh
  fail-closed #1035/#1036 → envelopes → cohort stops/TP #1048 → force-close
  via the shared close path, re-arm guards #1046).
- Reconcile: `jobs/handlers/alpaca_order_sync.py` (5-min: poll fills, orphan
  repair, stuck-open reconcile #1049).
- Learn: `jobs/handlers/paper_learning_ingest.py` (position-level dedup,
  routing-aware is_paper) → `learning_feedback_loops` →
  `learning_trade_outcomes_v3` → calibration/post_trade_learning.

**Feeds**: truth layer `services/market_data_truth_layer.py`
(`snapshot_many`: options + equities Alpaca-primary → Polygon fallback);
scanner chains `truth_layer.option_chain`; stage validation aligned to it
(#1052); `market_data.py` PolygonService is the legacy/fallback path.
DB marks persist only on monitor/MTM cadence — broker outranks (#1022).

**Scheduler**: `packages/quantum/scheduler.py` SCHEDULES (CT, mon–fri):
05:00 calibration · 08:00 close-cycle → 08:35 exits · RTH order-sync q5min +
monitor q15min · 11:00 scan → 11:30 executor (**one execution shot/day —
known volume bottleneck, backlogged P1**) · 11:45 IPO watch · 14:45 exits →
15:30 MTM · 16:00–17:00 learning chain. Weekend silence is by design.

## 7. AUDIT LOOP

- **Nightly v5 audit** at midnight CT via Windows Task Scheduler
  (`\nightly-audit` → `audit/run-nightly.cmd`, permission-scoped settings):
  NIGHTLY mode diffs vs the prior report (≤8 subagents); FULL on Sundays.
  Prompt: `audit/v5-prompt.md`.
- **READ-ONLY contract is absolute**: the loop writes reports
  (`audit/reports/YYYY-MM-DD.md`) and `audit/ALERT-<date>.md` files only —
  it never merges, flips flags, or trades, even on a critical finding. The
  human acts in the morning.
- `audit/ledger.md` = exclusion memory (shipped/reported findings — re-
  finding is a wasted slot) **+ pending-verifications list = the recoverable
  runbook if a session drops**. `audit/area8.md` = the single self-extension
  slot (current lens: Negative-Decision Efficacy — counterfactuals of
  rejected candidates). Human reviews area8 + ledger weekly.
- **SPCX**: in `scanner_universe`; `ipo_readiness_monitor` (11:45 CT) logs
  first-quote/first-chain/per-gate verdicts; lists 2026-06-12; options
  ~2nd business day (expedited, unconfirmed). **No special-casing — the
  gates decide when it's tradeable** (binding: the 50-daily-closes history
  gate → ~late Aug).

## 8. KNOWN LIARS & SEAMS

- `[EXIT_EVAL_DEBUG]` threshold prints compute flat defaults; decisions are
  cohort-aware + time-scaled (fix ticketed P1). Already manufactured one
  phantom incident.
- **DOC≠BUILT instances**: `learning_performance_summary_v3` referenced,
  never shipped (Gate A/B backlogged) · `check_new_position`
  (risk_envelope) has zero production callers · the `9a2cef1` pattern — a
  commit that claims a fix without wiring the call site, its test
  module-skipped; grep for the implementation before believing any claim.
- **Add-to-position seam**: #1038 exempts and #1040 must NOT exempt orders
  with a position_id; a future add-to-position feature hits both — revisit
  before building it.
- **POLICY_LAB single-champion path**: the champion fallback (`"aggressive"`
  in transition windows) is ungated — known, accepted, on the ledger.
- The morning suggestions sweep relabels everything `dismissed` — suggestion
  `status` never reflects execution (funnel plumbing backlogged P1;
  `blocked_reason` stamping closed the rejection half).

## 9. NEVER-DO (carried forward 2026-06-10; update only with evidence)

- **Never merge a code-change PR without CI green.** Fix or
  skip-with-tracking-issue before other work.
- **Never add a new `@pytest.mark.skip`** without: (a) tracking issue with
  unskip criteria, (b) issue number in the reason string, (c) reviewer
  approval. Skip count must trend down.
- **Never write `paper_positions.status='closed'` directly.** Use the
  canonical close helper (duplicate close-order logic is the
  2026-04-10→04-15 bug class).
- Never count `internal_paper` fills as green days — Alpaca fills only.
- Never enable iron condors during `alpaca_paper` phase.
- Never rebuild the entire system prompt on every AI call (split
  static/dynamic).
- Never start a new Claude Code session on this project without
  `--continue`.
- Never use ChatGPT mid-build — architecture decisions live here; mixing
  tools creates drift.
- Never deploy without verifying `TASK_NONCE_PROTECTION=1` in Railway.
- Never touch `intraday_risk_monitor.py` or the `risk_alerts` migration
  without reading this file.
- Never enable `PROFIT_AGENT_RANKING=1` — retired 2026-04-16, ignored by
  code.
- Never fabricate equity, weekly_pnl, marks, or quotes when a source is
  unavailable — skip/reject loudly (H9 both ends: a value you cannot price
  must REJECT or flag, never fabricate; applies to entries AND exits).
- Never flip `PDT_PROTECTION_ENABLED` ON — it would enforce a retired rule.
- Never loosen a stop/envelope to fix re-entry whipsaw — that is #1040's
  job.
- Never merge or build during market hours; never fix-forward mid-session
  (added 2026-06-10, runbook rule — evidence: recycles reset once-per-
  process state and orphan in-flight cycles).

---

## Working style

Exact SQL, exact file:line, exact Railway commands — no placeholders. Show
broken code before fixing it. Minimal diffs over rewrites. Always check
`job_runs` before assuming a cron ran. Regression tests for every bug fixed;
test-deletion discipline (state what's deleted and why in the PR). Operator
is in **learning-mode** (correctness > capital deployment; low trade
frequency is a feature; mode exits only by explicit operator declaration).
Operational velocity: ship the correct fix efficiently when evidence
supports it — caution needs a named signal, not a feeling. Ground
recommendations in this system's own data; an honest "no finding" beats a
stretch. Reference docs: `docs/loud_error_doctrine.md` (H1–H15),
`docs/risk_math.md`, `docs/small_tier_allocation.md`,
`docs/structural_findings.md`, `docs/cohort_architecture.md`,
`docs/migration_procedure.md`, `docs/history.md` (pre-2026-06-10
narratives), `docs/bugs_fixed_history.md`, `audit/ledger.md`.
