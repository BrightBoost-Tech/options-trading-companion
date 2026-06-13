# Options Trading Companion — Project Doctrine
# Loaded by Claude Code on EVERY turn. DOCTRINE AND POINTERS, NOT VALUES:
# any fact that changes (equity, OBP, positions, counts, phase, flag value)
# is a POINTER to its source of truth, never an embedded number. Stale
# embedded state caused real phantom reads; this structure is the fix.
# Rewritten 2026-06-13 (≤40k chars). Pre-rewrite snapshots: docs/history.md
# (pre-06-10), git history of this file. Running SHA + flags: verify on
# Railway (§2), never trust this file for a value.

---

## 1. TRUTH DOCTRINE — read this before trusting anything, including yourself

Four sources, in precedence order (lowest to highest):

1. **CODE** — what's written. Read it; never assume. Comments and docstrings
   routinely describe unbuilt behavior (see §8 Known Liars).
2. **SUPABASE** — what happened. Query it via MCP. DB *marks/unrealized P&L
   are NOT authoritative* — they lag and can be wrong-signed (#1022 phantom
   class) and shadow marks carry the #1017 fill-optimism bias even after the
   06-12 fix corrected the close path. DB rows of record (job_runs, orders,
   suggestions, alerts, learning outcomes) are authoritative.
3. **RAILWAY** — what's actually RUNNING: deployment SHA + container start +
   effective env. Merged ≠ running (§2).
4. **ALPACA** — broker truth: fills, positions, buying power. **Outranks
   everything above.** Deployable capital = live `options_buying_power`
   (settled funds; `equity_state.get_alpaca_options_buying_power`, 60s TTL).
   The cash↔OBP gap is the broker's own unsettled funds (T+1), not our bug.
   Account `last_equity` is the realized-blind brake's baseline (#1058/N1,
   wrapper-exposed since the 06-12 fix — it had been silently None).

Corollaries:
- **Debug prints and displays lie.** `[EXIT_EVAL_DEBUG]` prints flat default
  thresholds while the decision path is cohort-aware and time-scaled. The
  Alpaca portfolio CHART lies too: it marks each option leg at its own last
  trade, so leg-timestamp skew on a hedged structure prints phantom equity
  spikes (06-12: a +$180 chart spike whose executable close never crossed any
  threshold). The decision path / executable side is the only truth; a log
  line or chart that doesn't compute through the same functions as the
  decision is a hypothesis about the code.
- **Verify before asserting — including your own confident reads.** Multiple
  confident claims this project ("the flag is on", "the gate fired", "that
  symbol is illiquid", "the chart shows a missed gain") were overturned by
  one direct query against the right source. A claim with multi-source
  agreement is a finding; anything else is a hypothesis and must be labeled
  as one. If two sources disagree, the disagreement IS the finding — report
  it, never average it.
- **H9 both ends:** a value you cannot price must REJECT or flag, never
  fabricate — entries AND exits. Measurement-basis corrections (honest PoP,
  broker-true feeds, executable-side fills) change what is measured, not what
  is permitted — they are never "loosening".
- **H11:** every status check includes a baseline query of critical/high
  `risk_alerts` regardless of the hypothesis being checked.
- **H10:** on any manual operator intervention (e.g. closing via the Alpaca
  UI), DB reconciliation is the FIRST follow-up. `ghost_position` alerts are
  urgent, not noise — but the sweep currently also flags shadow positions
  (§8 seam), so confirm live-routed before treating one as a broker desync.

## 2. DEPLOY DOCTRINE

- **Merged ≠ running (H8).** Verify against `origin/main`, not local (the
  06-09 quarantine/honesty commits sat unpushed while "merged"). The repo
  SQUASH-merges: original SHAs are not ancestors of main — verify deployed
  code by CONTENT at the squashed SHA. After every merge: Railway deployment
  SUCCESS + container start > merge time + flags read back on the running
  process. The auto-deploy hook can lag ~10 min after rapid merges and the
  listing API lags further — don't declare a deploy missing inside the lag
  window (06-11 erratum); but DO verify before trusting behavior to a merge.
- **Every merge to main auto-deploys and recycles BOTH workers (worker +
  worker-background) — doc-only PRs included.** A recycle resets all
  once-per-process state (the conviction DEGRADED line fires once per
  container; raw-mode calibration resets). Ship sequential, attributable
  deltas: one recycle per behavioral change wherever possible.
- **Migration-before-merge** for any PR that reads a new table/column
  (`docs/migration_procedure.md`). Env-first for new flags: set + read back
  on BOTH workers BEFORE the code that reads them lands. Use `skip_deploys`
  when pre-staging env so the merge deploy is the single recycle.
- **No building or merging during market hours. No fix-forward mid-session.**
  An anomaly during RTH gets: evidence capture first, then at most ONE
  sanctioned kill switch flip (§4 registry lists them). Diagnosis and fixes
  happen after 20:00Z. (Two 06-12 deploys carried RTH timestamps under a
  prior gate — the rule stands; that was a process miss, not a precedent.)
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
- **Behavioral/loosening changes: explicit opt-in.** Requires exactly `=1`
  (lenient variants accept `1/true/yes/on` — check the parser); absent/empty
  → the stricter legacy behavior, so an env regression fails SAFE. A
  non-empty non-truthy value logs an explicit WARNING.
  Canonical: RISK_UTILIZATION_GATE_ENABLED (threshold
  RISK_MAX_UTILIZATION_PCT has NO implicit default — enabled-but-unset fails
  closed), EXIT_MARK_SANITY_ENFORCE_ENABLED, GTC_PROFIT_EXIT_ENABLED.
- **Flags must be read-back-confirmed** on the running process, not assumed
  from the dashboard. Some legacy flags strict-parse `== "1"`
  (INTRADAY_TARGET_PROFIT_ENABLED) — check the parse before trusting a
  `true`. Startup flag-echo is backlogged (P2).

## 4. ACTIVE CONTROLS REGISTRY

One entry per live control: behavior · flag/polarity · kill switch ·
exercised-status. Verify current flag VALUES on Railway, never here.

- **#1038 entry-quote rejection** — an OPEN order with ANY leg unpriceable at
  stage time raises `EntryQuoteUnpriceable` (error, never a fabricated
  fill). Closes exempt (position_id set). Flag
  `ENTRY_QUOTE_VALIDATION_ENABLED`, default-ON. Kill: explicit falsy.
  Exercised: first live rejections 2026-06-10 (3 XLE forks, dead leg
  `O:XLE260717C00058000` bid/ask 0/0 — the counterfactual is unmarkable by
  construction, §7 area8). ⚠ Seam: a future add-to-position entry carries a
  position_id and would be wrongly exempted.
- **#1040 re-entry cooldown** — a symbol stopped by the per-symbol loss
  envelope is hard-benched per (cohort, symbol) until next session open;
  durable in PG `reentry_cooldowns`; writer keyed on the envelope's
  structured `symbol_loss_stops` (never daily/weekly/concentration); FILTER
  gate pre-ranking + fail-closed STAGE gate. Flag `REENTRY_COOLDOWN_ENABLED`
  default-ON. Exercised: UNEXERCISED (no per-symbol envelope stop yet; the
  06-11 QQQ shadow stop was a COHORT stop, #1048, which does not write a
  cooldown).
- **#1042 learning quarantine** — fail-closed `outcome_type` allowlist on
  live-affecting learning reads (conviction legacy, autotune); historical-
  simulation rows can't feed live multipliers. Flag
  `LEARNING_HISTORICAL_QUARANTINE_ENABLED` default-ON. Exercised: yes.
- **#1043 conviction fallback honesty** — the V3→legacy drop logs
  `[CONVICTION] … DEGRADED` once per process. The v3 view
  (`learning_performance_summary_v3`) is STILL MISSING — the line is designed
  honesty, not an incident; it reappears once after every recycle. No flag.
- **#1044 utilization gate** — small-tier entry capital control:
  `(committed + candidate)/(committed + settled OBP) ≤
  RISK_MAX_UTILIZATION_PCT` (pro-forma; broker cost basis, fresh reads,
  fail-closed). Replaces the share-of-book `concentration_symbol` BLOCK
  (demoted to WARN at small tier when on). Flag
  `RISK_UTILIZATION_GATE_ENABLED` — **explicit =1** (behavioral). Kill:
  unset → legacy concentration BLOCK. Exercised: 06-10; WARNING-level lines.
- **#1045 calibration circuit** — window escalation 30→60→90 on insufficient
  data; consumer TTL (`CALIBRATION_MAX_AGE_DAYS`, stale blob → `{}` +
  `calibration_stale` alert); `_overall` fallback (no silent ×1.0);
  ops_health OUTPUT_FRESHNESS registry (job RAN ≠ job WROTE). Kill:
  `CALIBRATION_STALENESS_TTL_ENABLED` falsy → legacy serve-stale. **Partially
  superseded by #1051's epoch.** Exercised: daily; in raw mode since the
  epoch (job returns `insufficient_data`, last real write 06-10).
- **#1046 exit re-arm** — a terminal-'cancelled' close order blocks retries
  only while fresh (30min) or budget-tripped (≥3/4h → block + critical
  `exit_protection_disarmed`); stale terminal failures RE-ARM the exits
  (kills the permanent-disarm class). `filter_blocking_close_orders` also
  EXCLUDES resting GTC profit-limits (else a parked TP disarms stops). Flag
  `CLOSE_REARM_ENABLED` default-ON. Exercised: UNEXERCISED (no
  terminal-cancelled close since).
- **#1047 spread re-key** — the 0.30 combo spread threshold keys on PRICE
  CLASS (`micro tier OR underlying < PRICE_CLASS_SPREAD_CUTOFF`, default
  $60), not account tier. Kill: `PRICE_CLASS_SPREAD_CUTOFF=0` restores
  tier-only. Exercised: 06-10.
- **#1048 cohort stops intraday** — the 15-min monitor evaluates stop_loss
  against COHORT conditions (not the flat 0.50 default); shadows' only loss
  protection. Flag `INTRADAY_COHORT_STOP_ENABLED` default-ON. Fail-safe →
  default. Exercised: **YES, live 06-11 19:00Z** — neutral QQQ shadow 7-lot
  breached the cohort stop (−$235 vs −$213) and force-closed at monitor
  cadence (the realized-sign corruption it exposed is the #1056 item).
- **#1049 order-sync O(open)** — Step-3 stuck-open reconcile scoped to the
  open-position id set. No flag. Exercised: 06-10 (6.5s→1.38s).
- **#1051 honest PoP + epoch + dedup** — debit-spread PoP computes breakeven
  interpolation (scanner passes legs; `credit=premium` for debit), not raw
  long-leg delta (the sign-flip class). **NO flag by design — rollback =
  revert PR + owner sign-off.** `CALIBRATION_EV_EPOCH` (2026-06-11): pre-fix
  prediction/outcome pairs never calibrate the post-fix predictor;
  calibration runs RAW MODE (empty blob, deploy-time reset) until ≥8
  post-epoch closes — a `calibration_stale` alert ~06-20 is the DESIGNED
  reminder of raw mode. Status: 5/8 post-epoch closes accrued (06-13).
  Learning ingest: position-level dedup + `is_paper` resolved from routing.
- **#1052 stage-quote alignment** — entry-leg validation reads the scanner's
  source set (Alpaca options snapshots primary → Polygon fallback), legacy
  Polygon NBBO probed as final fallback + divergence recorder
  (`[ENTRY_QUOTE] FEED DIVERGENCE`). All-sources-dark still rejects. Flag
  `ENTRY_QUOTE_SOURCE_ALIGNED` default-ON; explicit falsy → Polygon-only.
- **#1034 exit-mark corroboration (Stage-2 LIVE 06-13)** — at a mark-derived
  fire, corroborates the triggering mark against the achievable close on the
  EXECUTABLE side (sell→bid, buy→ask), writing one
  `exit_mark_corroboration_observations` row. Divergence normalized by the
  achievable PRICE, not strike geometry (the 06-12 fix: the QQQ condor
  phantom re-scores 0.06→~0.91). Stage-2 flag
  `EXIT_MARK_SANITY_ENFORCE_ENABLED` (behavioral, default-OFF) SUPPRESSES a
  TARGET_PROFIT fire whose row says `would_suppress` — stop_loss NEVER
  suppressed (double-guarded: compute layer + call-site). Observe flag
  `EXIT_MARK_SANITY_OBSERVE_ENABLED` writes the row without acting. Kill:
  unset either flag. Exercised: observe since 06-08; enforce armed 06-13,
  awaiting first fire.
- **#1017 executable-side internal fills** — internal/shadow/fallback closes
  fill at the executable side via the same corroboration computation, never
  the optimistic mid; mid fallback only with a persisted `fill_quality` flag
  (order_json + ledger) so learning can weight/exclude. No flag (measurement
  correction). Exercised: NFLX shadow 06-12 (mid +314.70 → executable
  +133.35; the +$181 fiction was also corrected in-DB pre-ingest).
- **Resting take-profit (PR #1021 + #1064 pilot, LIVE 06-13)** — morning
  sweep parks a closing mleg GTC limit at the cohort flat tp per open
  live-routed structure (buy-to-close for credit, sell-to-close for debit);
  `intentional_resting_exit` order class is watchdog-exempt; the exit
  evaluator DEFERS the profit side to a live resting order
  (`skipped_resting_tp_owns_profit_side` — single-submitter), stops still
  pre-cancel. Flag `GTC_PROFIT_EXIT_ENABLED` (behavioral) + pilot scope
  `GTC_PROFIT_EXIT_PILOT_POSITION_IDS`. Exercised: **YES, live 06-13** — QQQ
  condor resting GTC accepted at the broker, limit 0.81. Specs for the
  unbuilt detectors: `docs/specs/fast_exit_loop.md`,
  `docs/specs/streaming_exits.md`, `docs/specs/resting_tp_orders.md`.

Sanctioned mid-session kill switches, complete list: the explicit-falsy
flags above (#1038, #1040, #1046, #1048, #1045-TTL, #1052), unset
`RISK_UTILIZATION_GATE_ENABLED` (reverts to the stricter BLOCK),
`PRICE_CLASS_SPREAD_CUTOFF=0`, unset `EXIT_MARK_SANITY_ENFORCE_ENABLED`
(reverts to observe-only), unset `GTC_PROFIT_EXIT_ENABLED` (no new resting
TPs; existing rest until filled/cancelled), and the global trio
`SCHEDULER_ENABLED` / `CALIBRATION_ENABLED` / `RISK_ENVELOPE_ENFORCE`.
The #1051 PoP fix and #1017 fill fix deliberately have no switch.

## 5. RISK FRAME

Constraint stack, in evaluation order (current numbers: query, don't trust
docs — H14):

1. **Settled-OBP truth** — deployable = live Alpaca `options_buying_power`
   (60s TTL). Never equity, never a DB snapshot.
2. **Realized-blind daily brake** (#1058/N1) — broker `equity − last_equity`
   tightens all four envelope feeders (GATED: pre-approved, do not re-find).
3. **Utilization cap** (#1044, small tier) — pro-forma total-utilization.
4. **Envelopes** (`risk/risk_envelope.py`): `concentration_symbol` block
   (WARN at small tier under #1044) · sector/expiry/stress/greeks warn ·
   earnings-count block · daily/weekly/per-symbol loss **force_close**.
   `passed=False` only on block/force_close — warns never block.
5. **Per-symbol $ allocation cap** (RiskBudgetEngine `underlying_allocation`)
   — separate code from the envelope share-of-book check, deliberately.
6. **Per-candidate allocator split** (small tier: 0.85×regime×equity over ≤4
   candidates, 36% per-trade ceiling, score skew).
7. **H7 round-trip BP** (entry AND exit must fit) → per-contract floor.

Loss-control precedence on a live position: **per-symbol envelope (−3% of
equity, 15-min cadence) binds before cohort stops (cohort-conditioned, now
also 15-min via #1048) binds before the vestigial 0.50 position stop.** This
asymmetry is deliberate-but-undecided at compounding capital — the coherence
question is BACKLOGGED (P2); do not "fix" it ad hoc, and NEVER loosen the
stop to reduce re-entry whipsaw (that is #1040's job).

- **PDT is RETIRED** (FINRA + Alpaca, 2026-06-04). daytrade fields are
  placeholders. Real costs of trade velocity are fees (~$1–2/round-trip) and
  #1040 cooldown benches — nothing else.
- **Never loosen a control on outcome or hindsight.** A losing trade that
  passed every gate is not evidence a gate is wrong; a gate-killed trade that
  would have won is ONE data point for the audit's counterfactual lens (§7
  area8), not a loosening argument.
- Cohorts: 3 books (aggressive = live champion via
  `policy_lab_cohorts.promoted_at`; neutral + conservative shadow-only,
  internal fills, no real capital, no envelope backstop — cohort stops are
  their protection; their marks carry the #1017 bias even post-fix).

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
  `process_symbol` (universe from `scanner_universe`; every rejection →
  `suggestion_rejections` with `spread_debug`; defensive
  `chain_mechanics_formula_anomaly` warn on >300% spread_pct edge cases).
- Score: EV/PoP `ev_calculator.py` (breakeven interpolation for debit —
  #1051) → conviction `analytics/conviction_service.py` (v3 missing →
  legacy, quarantined) → calibration `analytics/calibration_service.py`
  (`apply_calibration`; raw mode until post-epoch data) → ranking
  `analytics/canonical_ranker.py` (MIN_EDGE_AFTER_COSTS gate).
- Size: `services/risk_budget_engine.py` + `PortfolioAllocator` +
  `services/analytics/small_account_compounder.py` (`get_tier` — hard
  $1k/$5k cliffs).
- Execute: `services/paper_autopilot_service.py` — circuit breaker
  (`check_all_envelopes` + #1044 demotion) → `_execute_per_cohort`: cooldown
  gates → utilization gate → `_stage_order_internal` (`paper_endpoints.py`;
  #1038 validation on the #1052-aligned fetch) → broker via
  `brokers/execution_router.py` / `alpaca_order_handler.py` (idle watchdog
  cancels non-GTC DAY limits ~90s/poll; GTC + `intentional_resting_exit`
  exempt).
- Monitor: `jobs/handlers/intraday_risk_monitor.py` (15-min: mark refresh
  fail-closed #1035/#1036 → envelopes → cohort stops/TP #1048 → #1034
  corroboration/Stage-2 → force-close via the shared close path, re-arm
  guards #1046).
- Close: SINGLE SUBMITTER is `paper_exit_evaluator._close_position`
  (745ced4); staging never also submits; terminal-reject classification
  returns broker duplicate-rejects gracefully. Internal fills at the
  executable side (#1017). Canonical writer `services/close_helper.py` —
  never write `status='closed'` directly.
- Reconcile: `jobs/handlers/alpaca_order_sync.py` (5-min: poll fills, orphan
  repair, stuck-open reconcile #1049, ghost sweep behind
  `RECONCILE_POSITIONS_ENABLED`).
- Learn: `jobs/handlers/paper_learning_ingest.py` (position-level dedup,
  routing-aware is_paper) → `learning_feedback_loops` →
  `learning_trade_outcomes_v3` → calibration/post_trade_learning.

**Feeds**: truth layer `services/market_data_truth_layer.py`
(`snapshot_many`: options + equities Alpaca-primary → Polygon fallback; 429
retry stack with backoff; 60s snapshot TTL); scanner chains
`truth_layer.option_chain`; stage validation aligned to it (#1052);
`market_data.py` PolygonService is the legacy/fallback path. DB marks persist
only on monitor/MTM cadence — broker outranks (#1022).

**Scheduler**: `packages/quantum/scheduler.py` SCHEDULES (CT, mon–fri):
05:00 calibration · 08:00 close-cycle → 08:35 exits (+ resting-TP sweep) ·
RTH order-sync q5min + monitor q15min · 11:00 scan → 11:30 executor (**one
execution shot/day — known volume bottleneck, backlogged P1**) · 11:45 IPO
watch · 14:45 exits → 15:30 MTM · 16:00–17:00 learning chain. Weekend
silence is by design.

## 7. AUDIT LOOP

- **Nightly v5 audit** at midnight CT via Windows Task Scheduler
  (`\nightly-audit` → `audit/run-nightly.cmd`): NIGHTLY mode diffs vs the
  prior report (≤8 subagents); FULL on Sundays. Prompt: `audit/v5-prompt.md`.
- **READ-ONLY contract is absolute**: the loop writes reports
  (`audit/reports/YYYY-MM-DD.md`) and `audit/ALERT-<date>.md` files only — it
  never merges, flips flags, or trades, even on a critical finding. The human
  acts in the morning.
- `audit/ledger.md` = exclusion memory (shipped/reported findings — re-
  finding is a wasted slot) **+ pending-verifications list = the recoverable
  runbook if a session drops**. `audit/area8.md` = the single self-extension
  slot (current lens: Negative-Decision Efficacy — counterfactuals of
  rejected candidates). Human reviews area8 + ledger weekly. Note: a
  rejected leg that was DARK at decision time (the XLE dead-leg class) is
  UNMARKABLE on the executable side — its counterfactual is indeterminate by
  doctrine, not lazily skipped; the additive recommendation is an underlying-
  move proxy field, never a hindsight quote.
- **SPCX**: in `scanner_universe`; `ipo_readiness_monitor` (11:45 CT) logs
  first-quote/first-chain/per-gate verdicts; listed 2026-06-12 (first equity
  quote seen 06-12 16:45Z); options ~2nd business day (expedited,
  unconfirmed). **No special-casing — the gates decide.** Binding gate: the
  50-daily-closes history → ~late Aug.

## 8. KNOWN LIARS & SEAMS

- `[EXIT_EVAL_DEBUG]` threshold prints compute flat defaults; decisions are
  cohort-aware + time-scaled (fix ticketed P1). Already manufactured one
  phantom incident. The Alpaca portfolio CHART is the same class at the
  display layer (§1).
- **DOC≠BUILT instances**: `learning_performance_summary_v3` referenced,
  never shipped (Gate A/B backlogged) · `check_new_position`
  (risk_envelope) has zero production callers · the `9a2cef1` pattern — a
  commit that claims a fix without wiring the call site, its test
  module-skipped; grep for the implementation before believing any claim.
- **Add-to-position seam**: #1038 exempts and #1040 must NOT exempt orders
  with a position_id; a future add-to-position feature hits both — revisit
  before building it. The resting-TP single-owner skip keys on the
  `intentional_resting_exit` marker + close side; an add-to-position close
  side could collide — revisit there too.
- **ghost_position sweep does not exclude shadows** (`alpaca_order_sync.py`
  selects all open-position users, no live-routed filter) — open shadow
  positions generate recurring ghost alerts that bury a real broker desync.
  H10 still holds; scope before trusting the count (backlog P2).
- **OUTPUT_FRESHNESS watches ONE table** (`ops_health_service.py`:
  calibration_adjustments only). A silent stall of the learning ingest or
  mark refresh would not alert — expansion backlogged (P2).
- **is_paper tags every learning row paper** (live SPY/MARA/NFLX closes
  included) — the routing resolver does not distinguish live broker fills in
  the learning rows this week; green-day counting reads elsewhere. Confirm
  before trusting is_paper as a live/shadow discriminator (backlog P2).
- **POLICY_LAB single-champion path**: the champion fallback (`"aggressive"`
  in transition windows) is ungated — known, accepted, on the ledger.
- The morning suggestions sweep relabels everything `dismissed` — suggestion
  `status` never reflects execution (funnel plumbing backlogged P1;
  `blocked_reason` stamping closed the rejection half).

## 9. NEVER-DO (carried forward; update only with evidence)

- **Never merge a code-change PR without CI green.** Fix or
  skip-with-tracking-issue before other work.
- **Never add a new `@pytest.mark.skip`** without: (a) tracking issue with
  unskip criteria, (b) issue number in the reason string, (c) reviewer
  approval. Skip count must trend down.
- **Never write `paper_positions.status='closed'` directly.** Use the
  canonical close helper (`services/close_helper.py`) — duplicate close-order
  logic is the 2026-04-10→04-15 bug class.
- **Never run a second profit-side submitter while a resting TP is live.**
  The exit evaluator defers (`skipped_resting_tp_owns_profit_side`); the
  06-11/06-12 double-submit class is what the single-submitter rule fixed.
  Stops are the exception — they pre-cancel the resting order first.
- Never count `internal_paper` fills as green days — Alpaca fills only.
- Never enable iron condors during `alpaca_paper` phase.
- Never rebuild the entire system prompt on every AI call (split
  static/dynamic).
- Never deploy without verifying `TASK_NONCE_PROTECTION=1` on both workers.
- Never touch `intraday_risk_monitor.py` or the `risk_alerts` migration
  without reading this file.
- Never enable `PROFIT_AGENT_RANKING=1` — retired 2026-04-16, ignored by
  code.
- Never fabricate equity, weekly_pnl, marks, or quotes when a source is
  unavailable — skip/reject loudly (H9 both ends; applies to entries AND
  exits, live AND shadow).
- Never flip `PDT_PROTECTION_ENABLED` ON — it would enforce a retired rule.
- Never loosen a stop/envelope to fix re-entry whipsaw — that is #1040's job.
- Never merge or build during market hours; never fix-forward mid-session
  (recycles reset once-per-process state and orphan in-flight cycles).
- Never widen the resting-TP pilot allowlist without first confirming the
  sweep's live-routed scoping (shadows must never get broker orders).

---

## Working style

Exact SQL, exact file:line, exact Railway commands — no placeholders. Show
broken code before fixing it. Minimal diffs over rewrites. Always check
`job_runs` before assuming a cron ran. Aggregate in SQL (COUNT/SUM/GROUP BY),
never page raw rows into context. Regression tests for every bug fixed;
test-deletion discipline (state what's deleted and why in the PR). Operator
is in **learning-mode** (correctness > capital deployment; low trade
frequency is a feature; mode exits only by explicit operator declaration).
Operational velocity: ship the correct fix efficiently when evidence
supports it — caution needs a named signal, not a feeling. Ground
recommendations in this system's own data; an honest "no finding" beats a
stretch. Reference docs: `docs/loud_error_doctrine.md` (H1–H15),
`docs/risk_math.md`, `docs/small_tier_allocation.md`,
`docs/structural_findings.md`, `docs/cohort_architecture.md`,
`docs/migration_procedure.md`, `docs/history.md`, `docs/bugs_fixed_history.md`,
`docs/backlog.md` (tiered), `audit/ledger.md`.
