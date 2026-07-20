# Options Trading Companion — Project Doctrine
# Loaded by Claude Code on EVERY turn. DOCTRINE AND POINTERS, NOT VALUES:
# any fact that changes (equity, OBP, positions, counts, phase, flag value)
# is a POINTER to its source of truth, never an embedded number. Stale
# embedded state caused real phantom reads; this structure is the fix.
# Rewritten 2026-06-13; orchestration/evidence contract synced 2026-07-16.
# Pre-rewrite snapshots: docs/history.md (pre-06-10), git history of this
# file. Running SHA + flags: verify on Railway (§2), never trust this file
# for a value.

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
- **STEP 0 clock grounding (every session, 07-06 erratum):** ground now()
  against the DB clock + broker clock BEFORE any time arithmetic. If either
  disagrees with a prompt header, session summary, or stated time, THE
  CLOCKS WIN — correct the premise out loud, then proceed. (A
  session-boundary date phantom read a 4-minute-old job as a 23h outage and
  triggered an unnecessary mid-RTH BE recycle.)
- **Debug prints and displays lie.** `[EXIT_EVAL_DEBUG]` printed flat default
  thresholds for weeks while the decision path was cohort-aware (fixed #1067,
  live-confirmed 06-16 — the LESSON stands). The Alpaca portfolio CHART lies
  the same way: it marks each option leg at its own last trade, so
  leg-timestamp skew on a hedged structure prints phantom equity spikes
  (06-12: a +$180 chart spike whose executable close never crossed any
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
  urgent, not noise — the sweep is live-routed-scoped since #1107 (fail-OPEN
  to the unscoped sweep on a scope-query failure: noisy beats blind).

## BROWSER USE

Use Claude Code Desktop Browser only for local UI acceptance,
interaction-dependent source research, or comparing authoritative
API/receipt evidence with operator-facing rendering. Record URL, timestamp,
authentication state, screenshot, DOM result, console/network errors, and
expected-versus-observed behavior. Browser evidence is secondary to
Supabase, Railway, Alpaca MCP, and direct APIs. Prefer connectors, APIs,
web retrieval, or CLI for structured facts. Never place, modify, exercise,
replace, or cancel broker orders; change production configuration; persist
an Alpaca login; or add Browser requirements to the unattended nightly
audit.
Pointers: local preview target `.claude/launch.json` (localhost only);
operator procedures `docs/runbooks/browser-verification.md`.

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
  (SOME variants are lenient `1/true/yes/on` — ALWAYS check the parser;
  07-18 audit: `RISK_UTILIZATION_GATE_ENABLED` is STRICT `=="1"`, and so are
  the global trio `CALIBRATION_ENABLED` / `SCHEDULER_ENABLED` /
  `RISK_ENVELOPE_ENFORCE` — setting `CALIBRATION_ENABLED=true` DISABLES
  calibration; `IV_RANK_NONE_ROUTING_ENABLED` accepts 1/true/yes but NOT
  `on`; `LIVE_ENABLED` accepts true/1 only, no strip); absent/empty
  → the stricter legacy behavior, so an env regression fails SAFE. A
  non-empty non-truthy value logs an explicit WARNING.
  Canonical: RISK_UTILIZATION_GATE_ENABLED (threshold
  RISK_MAX_UTILIZATION_PCT has NO implicit default — enabled-but-unset fails
  closed), EXIT_MARK_SANITY_ENFORCE_ENABLED, GTC_PROFIT_EXIT_ENABLED.
- **Flags must be read-back-confirmed** on the running process, not assumed
  from the dashboard — since 07-18 (#1268) every process start logs a
  `[FLAG_ECHO]` block with each behavioral flag's EFFECTIVE parsed value via
  its real parser (packages/quantum/flag_echo.py, allowlist-only, 27 flags):
  read the echo in the deploy logs instead of guessing. Some legacy flags
  strict-parse `== "1"`
  (INTRADAY_TARGET_PROFIT_ENABLED) — check the parse before trusting a
  `true`. Startup flag-echo is backlogged (P2).

## 4. ACTIVE CONTROLS REGISTRY

One entry per live control: behavior · flag/polarity · kill switch ·
exercised-status. Verify current flag VALUES on Railway, never here.

- **#1038 entry-quote rejection** — an OPEN order with ANY leg unpriceable at
  stage time raises `EntryQuoteUnpriceable` (error, never a fabricated
  fill). Closes exempt (position_id set). Flag
  `ENTRY_QUOTE_VALIDATION_ENABLED`, default-ON. Kill: explicit falsy —
  **⚠ KILL-SWITCH COUPLING (07-06 audit): unsetting this flag ALSO silently
  disables the #1101 roundtrip gate** (it no-ops on empty entry_leg_quotes,
  paper_endpoints.py:1217-1218) — one switch pulls two controls.
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
  `[CONVICTION] … DEGRADED` once per process. RESOLVED path: the v3 view
  exists since #1076 (created dark, epoch+floor wall, all-1.0 below 20 live
  per bucket) — zero DEGRADED lines is CORRECT now; a reappearance means the
  view broke. No flag.
- **#1044 utilization gate** — small-tier entry capital control:
  `(committed + candidate)/(committed + settled OBP) ≤
  RISK_MAX_UTILIZATION_PCT` (pro-forma; broker cost basis, fresh reads,
  fail-closed). Replaces the share-of-book `concentration_symbol` BLOCK
  (demoted to WARN at small tier when on). Flag
  `RISK_UTILIZATION_GATE_ENABLED` — **explicit =1** (behavioral). Kill:
  unset → legacy concentration BLOCK. Exercised: 06-10; WARNING-level lines.
- **#1045 calibration circuit** — window escalation 30→60→90; consumer TTL
  (`CALIBRATION_MAX_AGE_DAYS`, stale → `{}` + alert); `_overall` fallback.
  Kill: `CALIBRATION_STALENESS_TTL_ENABLED` falsy → serve-stale. Partially
  superseded by #1051's epoch; raw mode since 06-11.
- **#1046 exit re-arm** — terminal-'cancelled' close blocks retries only
  while fresh (30min) or budget-tripped (≥3/4h → critical
  `exit_protection_disarmed`); stale failures RE-ARM; resting GTC TPs
  excluded from the block filter. Flag `CLOSE_REARM_ENABLED` default-ON.
  UNEXERCISED.
- **#1047 spread re-key** — 0.30 combo threshold keys on PRICE CLASS
  (micro OR underlying < `PRICE_CLASS_SPREAD_CUTOFF` $60). Kill: =0 →
  tier-only. Exercised 06-10.
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
  post-epoch LIVE closes (#1076 live-only). **8th-close convergence rule —
  three things happen at live close #8: (1) calibration exits raw mode
  (first real multipliers, on clean live-only data); (2) the clamp review
  opens (0.5 ev/pop floor may mask signal); (3) the winsorize/outlier-cap
  gate opens. Check all three that night; count via
  `signal_accuracy_rolling.n` or the relearn's sample_size.** Status:
  query, don't trust docs. Learning ingest: position-level dedup +
  `is_paper` resolved from routing.
- **#1052 stage-quote alignment** — entry-leg validation reads the scanner's
  source set (Alpaca options snapshots primary → Polygon fallback), legacy
  Polygon NBBO probed as final fallback + divergence recorder
  (`[ENTRY_QUOTE] FEED DIVERGENCE`). All-sources-dark still rejects. Flag
  `ENTRY_QUOTE_SOURCE_ALIGNED` default-ON; explicit falsy → Polygon-only.
- **#1034 exit-mark corroboration (Stage-2 LIVE 06-13)** — mark-derived
  fires corroborate against the EXECUTABLE-side achievable close
  (sell→bid, buy→ask), one observations row per fire; divergence normalized
  by achievable PRICE. `EXIT_MARK_SANITY_ENFORCE_ENABLED` (behavioral,
  default-OFF) suppresses `would_suppress` TARGET_PROFIT fires only —
  stop_loss NEVER suppressed (double-guarded). Observe flag writes the row
  without acting. Kill: unset either. Enforce armed 06-13, awaiting first
  fire.
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
  `GTC_PROFIT_EXIT_PILOT_POSITION_IDS` — **⚠ UNSET pilot list = ALL eligible
  live-routed positions, NOT pilot-off** (gtc_profit_exit.py:194-198; 07-06
  audit correction). Exercised: **YES, live 06-13** — QQQ condor resting GTC
  accepted at the broker, limit 0.81. Specs for the unbuilt detectors:
  `docs/specs/fast_exit_loop.md`, `docs/specs/streaming_exits.md`,
  `docs/specs/resting_tp_orders.md`.
- **#1071 phantom-mark-safe brake** — the daily/weekly loss brake fires on
  realized (DB-authoritative, UN-GATED — preserves #1058) + executable-
  corroborated unrealized (#1034), NEVER the raw broker equity delta (a 06-17
  phantom unrealized of -285 force-closed a live MARA that executable-closed
  -15). Fail-SAFE to the legacy broker-true brake when live-scope/realized is
  unavailable; per-position stops (#1048) unchanged. Measurement correction →
  **no behavioral kill switch**; `BRAKE_REALIZED_RECONCILE_THRESHOLD`
  (default 25) tunes only the H10 reconcile cross-check. Seam: autopilot
  breaker FIXED (#1075, P2#6); MTM / midday GATE paths are warn-only (the raw
  phantom there only logs, no action). Exercised: **first live RTH 06-18 —
  evaluated q15min, stayed clear** (the −675.99 loss was shadow_only, correctly
  excluded from the live brake); no losing LIVE session yet.
- **#1072 close-side quote validation** — at a LIVE close stage, reuses
  #1034's executable estimate: corroborated → stage at achievable_close,
  dark/uncorroborated → DEFER (hold + flag + escalate; stop 2 cycles / TP 4)
  BEFORE staging, so a defer never strands a naked position. Flag
  `CLOSE_QUOTE_VALIDATION_ENABLED` default-ON. Kill: explicit falsy → legacy
  mark-limit close. Exercised: deployed 06-18 (`5a1c8a7`), LIVE-UNEXERCISED (no
  live close 06-18 — the only close was a shadow `internal_paper` stop).
- **#1073 funnel truthful status** — execution stamps
  `trade_suggestions.status='executed'` at the position-insert seam (A); the
  morning sweep reconciles prior-day pending (position → executed, none →
  dismissed) instead of blanket-dismissing (B); idempotent on the
  position-exists signal. INDEPENDENT of the relearn (calibration never reads
  status). Flag `FUNNEL_STATUS_TRUTHFUL_ENABLED` default-ON (data-truth, not
  live-risk). Kill: explicit falsy → legacy 'staged'-stamp + blanket dismiss.
  Exercised: **both layers** — Layer B live 06-18, Layer A live 06-30 (2
  suggestions stamped executed at the position-insert seam); 33-row
  historical backfill EXECUTED 07-02 (operator-approved).
- **#1076 live-only calibration + v3 conviction view (#1043)** — calibration
  trains on LIVE outcomes only (`is_paper=false` in `_fetch_outcomes`) so shadow
  / internal-fill outcomes can't drive a live-applied EV/PoP multiplier (the
  06-18 LONG_PUT ×1.5 shadow-outvote, +662 outlier). Below MIN_CALIBRATION_TRADES
  live → insufficient_data → raw mode (×1.0), do-no-harm until live volume
  matures. Flag `CALIBRATION_TRAIN_LIVE_ONLY` default-ON (empty/unset → ON;
  explicit falsy → legacy is_paper-blind). + null-pop basis fix (flagless) +
  `learning_performance_summary_v3` conviction view created DARK (is_paper-blind-
  match, epoch+floor wall; every bucket <20 → all-1.0). Kill: explicit falsy.
  Exercised: **empirically confirmed 07-01** — relearn escalation 30/60/90 all
  sample_size = the live count exactly; shadow outcomes (incl. the −1,044.48
  SOFI) excluded; raw mode holds until 8 live post-epoch closes.
- **#1079/#1080 exit-trigger corroboration** — ALL per-position exit triggers
  (scheduled stop/TP + monitor loss_per_symbol + cohort stop) evaluate on the
  EXECUTABLE-corroborated UPL via `exit_mark_corroboration.corroborated_exit_upl`
  (raw fallback when dark; stops never suppressed). Flagless measurement
  correction. Exercised: **live 07-01** — SOFI cohort stop fired on
  corroborated −1,044.48 while the raw mid said +26.
- **#1094–#1097 unattended-readiness quartet** — config fail-CLOSED on
  cohort-load failure (#1094) · scheduler watchdog in EXPECTED_JOBS (#1095,
  detection only) · risk-alert egress for allowlisted critical types
  (#1096) · entries-only break-glass `ops_control.entries_paused` (#1097 —
  entry seam ONLY, monitor/exits untouched; READ fails OPEN; no deploy to
  flip). #1097 exercised live 07-02 via the #1119 trip.
- **#1100–#1102 oversight phases** — alert() insert retry + A4 silent-
  failure detector (`job_succeeded_with_errors`) (#1100) · **#1101 entry
  round-trip cost gate**: stage-seam reject when `EV − Σ(ask−bid)×contracts
  ×100 < $15`; `blocked_reason='ev_below_roundtrip_cost'`; flag
  `ENTRY_ROUNDTRIP_COST_GATE_ENABLED` default-ON. First live rejection
  07-02 (SOFI net −57.75) · #1102 close-fill-gap instrumentation (feeds the
  Phase-3 ≥10–15-fills gate).
- **#1104/#1106/#1107 observability trio** — scanner rejection-persist
  retry on transient disconnects (exercised 07-02: persist_failures=0) ·
  data_stale alert content from the ARM THAT FIRED (#1106; predicate retuned
  by #1115) · ghost-sweep live-routed scoping (#1107, fail-OPEN to unscoped).
- **#1109 dead-man's-switch ping** — heartbeat GETs `HEARTBEAT_PING_URL`
  each run (:00/:30, hours 8–17 CT; 5s timeout; failure = one WARNING, job
  result byte-identical). Silent check at the provider = APScheduler/BE/RQ/
  worker died — diagnose job_runs vs Railway. Unset var → silent no-op.
  ARMED end-to-end 07-02 (receipt + DOWN-email proven; see oversight-chain
  entry below). RTH-only trade-off accepted; the check reads DOWN overnight
  after a test until the next 08:00 CT ping — expected, not an incident.
- **#1110 typed segment columns** — outcome rows carry typed strategy/regime
  from suggestion_meta (NULL when unlinked, never fabricated); segment
  learning reads these; 82-row backfill executed 07-02.
- **#1111 direct-insert alert egress relay** — ops_health_check step 0 polls
  post-epoch (`ALERT_RELAY_EPOCH` 2026-07-02T00:00Z) critical/high
  risk_alerts rows that no sender owns and POSTs them out the same webhook.
  **Route/SLA: allowlisted alert() types (force_close, streak_breaker_*, …)
  egress IMMEDIATELY at write time; everything else critical/high rides the
  relay at the :07/:37 poll → ≤~37min worst-case to inbox.** Boundaries:
  `ops_*` rows + `metadata.egress_owner` rows skipped; 10/poll cap;
  3-failure circuit. Kill: none needed (best-effort, never blocks).
- **#1114/#1115 ops-noise pair** — q30min-REAL health-check dedup key (the
  :37 fire no longer dedupes; owner decision (a)) · data_stale predicate
  retune: `OPS_DATA_STALE_MINUTES` default 360 (env override) + daily
  job_late age is WEEKEND-EXCLUDED (Monday-storm fix). Exercised 07-02:
  0 job-arm false HIGHs (baseline 3.9/day).
- **#1116 MTM mark-write corroboration** — both durable-mark write sites
  (refresh_marks + monitor Part-B) persist
  {mark_corroborated, unrealized_pl_corroborated, mark_quality} ALONGSIDE
  the raw mid (cycle-cached snapshots, zero extra API calls; dark → NULLs).
  Governance (policy-lab drawdown/rollback, go-live checkpoints) prefers
  corroborated, NULL→raw. **The exit evaluator's close-limit price reads RAW
  `current_mark` — NEVER `mark_corroborated` (source-pinned; #1072 owns
  live-close repricing).** Flagless measurement correction.
- **#1118 signal-accuracy telemetry (observe-only)** — view
  `signal_accuracy_rolling` (live-only, last-20/scope, hit-rate + Brier) →
  ops_health snapshot + `signal_accuracy_degraded` WARNING at n≥8 AND
  hit_rate<0.2. Modulates nothing. Baseline 07-02: 1/6 wins, Brier 0.2751.
- **#1119 consecutive-loss streak breaker** — N consecutive LIVE losing
  round-trips (`STREAK_BREAKER_N`, default 3) → `entries_paused=true` +
  `streak_breaker_tripped` critical (immediate egress). **Semantics
  (operator-confirmed from the live ④ payload): evaluates the TRAILING
  window on EVERY ingest run — a trip can occur on a zero-close day (the
  07-02 first trip fired on a window spanning 06-15→06-30 with no close
  that day). Deliberate: a standing streak never sits unexamined. A win
  resets; the next losing close after a loss-tail re-trips BY DESIGN.**
  FAIL-CLOSED: an evaluation error PAUSES (never skips); the WRITE side is
  fail-closed while #1097's READ side stays fail-open — deliberate opposite
  polarities. Recovery is OPERATOR-ONLY, **validated live 07-02** (planned
  trip at the 21:20Z ingest; full chain incl. the inbox hop confirmed):
  `UPDATE ops_control SET entries_paused=false, entries_pause_reason=NULL
  WHERE key='global';` then confirm read-back + next 16:30Z cycle stages.
  **RUNBOOK (EDGE-TRIGGER since 07-07, replacing the 07-04 level-trigger
  behavior): the breaker re-trips ONLY when the trailing window CHANGES —
  window identity is the CONTENT fingerprint (sorted outcome row ids)
  stamped into `ops_control.streak_breaker_state` AT TRIP TIME. Your manual
  un-pause SQL is UNCHANGED and is sufficient review (the window you were
  paged for was recorded when it tripped). A standing reviewed window no
  longer re-pauses nightly; a NEW loss still trips instantly; un-pause →
  new loss re-trips; evaluation errors still fail-closed-pause. Flag
  `STREAK_BREAKER_EDGE_TRIGGER_ENABLED` default-ON; explicit falsy →
  legacy nightly re-trip.** Flag `STREAK_BREAKER_ENABLED` default-ON.
  Tail of paper_learning_ingest; result in `job_runs.result.streak_breaker`.
- **Oversight chain — ALL THREE LAST HOPS PROVEN 07-02**: dead-man's-switch
  receipt (pings + DOWN-email test; cron `*/30 8-16 * * 1-5` Chicago, Grace
  45 — FULLY ARMED) · relay path (synthetic → inbox) · immediate-egress
  path (breaker critical → inbox, real event). Do not re-prove these hops;
  new work verifies only its own seam.

- **#1228/#1229 merged 07-16 (NOT drafts) + provenance proofs** — #1228
  tape-hash reader: signed, operator-triggered, read-only, deliberately
  UNSCHEDULED; zero runs ever — runtime execution pending, full deterministic
  replay still open. #1229 broker-clock holiday guard: detection-only;
  falsifier = a broker-closed weekday with zero false `data_stale`/`job_late`
  (next natural 2026-09-07). Git-SHA decision provenance: RUNTIME-PROVEN
  2026-07-16 — `decision_runs.git_sha` carried the full deployed SHA on all 3
  natural runs. Condor EV model read-back 07-16: deployed `tail` /
  severity 0.35 / prob-mult 0.6 on BOTH workers (code defaults differ:
  `strict`/0.50/1.00 — env wins; verify on Railway per §1, never here).
  Migration `20260716155023` (trade_suggestions ranking_costs+vrp_ranking)
  APPLIED to production 2026-07-16 15:51Z ahead of its PR (#1231, draft) —
  **NEVER REAPPLY**; repo file exists for history reconciliation.
  F-MIDDAY-POSITION-READ-FAILOPEN, F-A9-6, F-A9-8: shipped CODE; runtime
  falsifiers pending (ledger owns them). 07-17: #1231/#1236/#1234/#1233
  MERGED+DEPLOYED at `b3cf45b`; ⚠ the original #1235/#1237 merged into a
  NON-DEFAULT branch and never reached main — replacements are draft PRs
  (backlog owns them). F-CREDIT-SIGN (07-15 nightly, HIGH) CONFIRMED at
  `b3cf45b`, fix in draft — internal-fill credit closes overstate realized
  P&L until it merges (fix merged #1240; the HISTORICAL book was corrected
  07-18 — see the weekend entry below — shadow realized_pl is no longer
  suspect). 07-18: the Friday sprint
  (#1246-#1253) is MERGED+DEPLOYED at `c51f41eb` — ⑤ foundation, cost-basis
  parity locks, payoff-capped stress, origin provenance, fleet transaction
  (dry-run-only; strict =1 gate), dispositions+quote-provenance writers.
  All three sprint migrations APPLIED 2026-07-18 03:34–03:40Z (by NAME:
  `shadow_fleet_activation_rpc`→20260718033415 ·
  `candidate_terminal_dispositions`→20260718033912 ·
  `option_quote_provenance`→20260718034013 — **NEVER REAPPLY**; receipts in
  risk_alerts `migration_apply`); writers self-activate, natural runtime
  proof pending. **07-18 SAT weekend run** (`docs/review/
  weekend-results-2026-07-18.md`): F-CREDIT-SIGN historical correction
  APPLIED (fp b780271c…; 19/18/19/20/9 rows; −14,367 realized / −16,971
  cash; census-zero) · the SEVEN activation blockers RESOLVED (six stale
  orders fp 04317fc1… + seventh row fp 5d5cd9fc… → cancelled) · five
  orphan job_runs reconciled (fp 40258ba9…) — **legacy-terminal boundary
  CLEAN**. Merged+deployed: #1257 4b311180 · #1256 25d0f494 + migration
  `20260718144818` job_runs-'partial' APPLIED (receipt 38e5ecd9…; NEVER
  REAPPLY) · #1258 72f689c0 · #1259 7f393580 (stage-time leg greeks) ·
  #1260 264b720d (⑤ study: INSUFFICIENT_EVIDENCE) · #1261 e0a1584
  (check_greeks null-safe; ⚠ BE deploy FAILED on clean start — BE serves
  264b720d pending the docs-merge redeploy). Fleet:
  BLOCKED_FLEET_PROVISION (env gate + no 50 policy ids; owner manifest in
  bundle). Zero fleet provisioning/activation; zero broker writes.
  **07-18 SAT NIGHT run** (`docs/review/saturday-night-results-2026-07-18.md`):
  #1264 592a267a nightly-runner reliability (wrapper + fresh audit worktree +
  scrubbed broker snapshot + completion contract; LOCAL Task Scheduler task
  re-registered, backup+rollback in bundle; operator pull needed before Sun
  00:00 CT) · #1265 35836cdc scanner cost bases · #1263 a558de7e canonical
  greeks wiring · #1269 fdcaf644 D2 signed aggregate FIXED · #1266 851416a0
  ⑤ IV capture + typed-unavailable spot (open-order STUDY_SQL linkage) ·
  #1268 76757684 startup flag echo (27 flags, real parsers). Zero
  migrations/production-DB/broker/fleet actions.
  **07-18 SAT EVENING run** (`docs/review/
  saturday-evening-results-2026-07-18.md`): #1274 e2f91ac2 ⑤ scan-time spot
  (capture COMPLETE: delta+IV+spot — first post-07-18 closed outcome is
  challenger-scorable) · #1272 94a4cdb3 E4/E5 quality-gate finals invariant
  (h7_dropped + sizing_outcome key; owner ratification open) · #1271
  53e86f53 source_used mislabel · #1273 9cb3876a realized cost consumer #3
  (per-routing commission: broker-routed = real $0, internal
  typed-unavailable) · #1275 da70b67e drift-summary quirk · #1276 02b2d8b0
  stress-model D2 residual CLOSED. Operator checkout pull
  BLOCKED_OPERATOR_PULL_CONFLICT (dirty audit/ledger.md +281; patch +
  handoff in bundle) — the nightly wrapper flow starts only after the
  operator pull. Zero migrations/production-DB/broker/fleet actions.
  **07-19 OWNER-DECISIONS run** (`docs/review/
  owner-decisions-implementation-2026-07-19.md`): ten merges, adversarial
  review + per-merge deploy each — #1278 1d1951d8 TCM v2 dual-run
  (observe-only) · #1280 79f4ba76 F-BAN phantom REMOVED (no-op by
  construction; `settings.banned_strategies` drift column ledgered to drop
  later) · #1282 3c3874e1 greek-cap alert-only counterfactual (caps 0) ·
  #1281 4c12dafa H7 typed subreason (owner ratification OPEN) · #1279
  78c71a8e versioned policy registry + 3-anchor/47-variant design · #1283
  ed5d6f48 tier taper DARK · #1284 7d95f143 E19-2B protocol v2 FROZEN (hash
  50e7e237…; BLOCKED on §7 minimum) · #1285 e161714f exact-leg OI capture
  (NO gate) · #1287 9b63dcc1 single-leg experiment DARK · #1286 cef4e600
  event-driven model review (inert until natural trigger). **Three
  migrations APPLIED via the migration procedure (receipts in risk_alerts;
  NEVER REAPPLY):** `policy_registrations` (receipt eac6a4b9…) · 50-row
  approved seed in one fingerprinted txn (receipt 14ca10ab…; 50 rows / 50
  distinct hashes / 0 mismatches / lineage 17-17-16) · `h7_subreason_check`
  NOT VALID+VALIDATEd (receipt 6c49ce87…). **Fleet PROVISIONED INACTIVE**:
  `b8b1ea1f…` status pending_legacy_terminal, 50 inactive $2,000 slots / 50
  shadow_only portfolios / 0 bindings, idempotency PROVEN (re-run →
  already_provisioned, 0 writes); **`ACTIVATE_FLEET=false` — NOT activated**.
  Dark states: taper DARK · greek caps counterfactual-only · TCM v2
  observe-only · single-leg DARK · OI observe-first no-gate · E19-2B BLOCKED
  · event-review inert-until-trigger · UI BLOCKED_UI_FILE_OWNERSHIP. Ledger
  reconciliation Phase 1 = 0 PRESERVE / 4 REJECT (local +281 pure lag);
  operator checkout fast-forwarded to main; the nightly wrapper is now LIVE.
  Zero broker writes; zero fleet activation; entries_paused untouched.
  **07-19 PARALLEL IMPLEMENTATION run** (`docs/review/
  parallel-implementation-results-2026-07-19.md`): six merges, adversarial
  review + per-merge deploy each; serialized
  #1290→#1289→#1291→#1293→#1294→#1292; final code main `4851ec8d` — #1290
  89a736807 D3 ratio-blindness FIXED (`leg_full_contract_count` helper;
  1×2→150; 1:1 byte-identical; check_greeks + stress migrated; §8 D3 line now
  RESOLVED) · #1289 b3f10031 TCM v2 realized-accrual reporting (no schema;
  join spine proven; 0/528 v2 stamps yet — accrues post-#1278 cycles) · #1291
  bd87025f SQL-mirror parity fixtures (6 families / 78 tests / ZERO defects) ·
  #1293 d60b7ad0 fork/collection sweep (rq fork-context root cause; 6 files +
  12-file subprocess harness; full-suite collection 0 errors) · #1294
  21e88e5f seven owner-decision packets (owner-packet-1..7:
  activation-after-Sunday+Monday · RETAIN h7_dropped · E19 minimum 8/alt 15 ·
  single-leg opt-in = two NEW draft registry rows · TCM N 15/alt 10 · taper
  [800,1000] band · greek caps Plan A staged) · #1292 4851ec8d single-leg
  hard veto at the REAL submit seam (`should_submit_to_broker` at 4 sites;
  byte-identity vs 100% of live rows; VRP second gate resolves #1287 C1;
  raw-jsonb registry opt-in lookup 0/50 enabled → DARK). **Fleet DRY-RUN
  (Phase 1, READ-ONLY; NO writes)**: registry 50/50 approved, hashes
  recompute-clean; fleet counts BEFORE==AFTER byte-identical (1
  pending_legacy_terminal / 50 inactive / 0 active / 0 bindings / 50
  shadow_only / 0 receipts); binding manifest fingerprint
  6f8d14995ff4371bf940364d90bf82de1faff188823cf3e61280b81740836bad (ORDER BY
  policy_registration_id ASC; anchors 17/33/50); all 13 replicated checks
  PASS ⇒ READY_TO_ACTIVATE; **ACTIVATION REMAINS FORBIDDEN** (no un-activate
  RPC — reversal = retire path; read-only replication, not service
  invocation). States: single-leg DARK 0-opt-in · TCM v2 observe-only · taper
  DARK · greek caps 0 · OI no-gate · E19-2B BLOCKED · event-review inert ·
  operator checkout clean-behind (5c6ae8bf…) · UI still Palette-owned. ZERO
  broker / production-DB-write / migration / env / fleet mutations this run;
  ACTIVATE_FLEET=false; entries_paused untouched.
  **07-19 SUNDAY IMPLEMENTATION run** (`docs/review/
  sunday-implementation-results-2026-07-19.md`): five merges, Fable-central
  adversarial review + per-merge deploy each; serialized
  #1296→#1299→#1297→#1298→#1300; final code main `27204bd0` — #1296 8a7908f1 ⑤
  scorable-outcome join readiness (end-to-end producer→consumer contract test;
  COMPLETE verdict, no join gap; both spot source labels pinned) · #1299
  fdf5b55c TCM v2 multi-fill realized accrual (side-flip boundary; per-side
  all-or-unavailable sums; AMD proof $1.30 vs $0.65 undercount; observe-only) ·
  #1297 df87fe93 single-leg one-contract selection (deterministic
  EV→delta→debit→lexical tie-breaker; DARK, 0 opt-in, zero production callers) ·
  #1298 4ffca2b1 owner ratifications v1 (7 decisions RECORDED not activated; E19
  protocol hash UNTOUCHED; taper band conflict recorded — engine [900,1100] vs
  ratified [800,1000], reconciliation = later code step) · #1300 27204bd0 Monday
  consolidated evidence reader (12 sections, four-state honesty
  OK/HONEST-EMPTY/FAILED-FETCH/NOT-FETCHED; operator prompt
  monday-evidence-operator-prompt-2026-07-20.md; read-only). **Phase 1 (Sunday
  nightly under the wrapper) = WRAPPER_PARTIAL**: a VALID FULL audit report was
  produced (SHA-pinned 17141967, 0 crit/high), but the runner's start/end
  markers, heartbeats, fresh-worktree path, and ping did NOT land in the
  operator cron.log (manifest workspace.path='.', no %LOCALAPPDATA% worktree —
  cwd='.' semantics) ⇒ nightly-runner P1 stays OPEN; morning: fix marker/worktree
  wiring + check the 07-19 dead-man ping at the provider; new finding
  F-RUNNER-BROKER-CREDS (scrubbed snapshot available:false — creds unset in the
  shim env). **Phase 2 (fleet activation dry-run) = SIGNED_DRY_RUN_PASS**:
  plan_activation proven zero-write/no-env by code (:639-685); fingerprint
  6f8d1499… recomputed from the bundle AND rebuilt from pure DB truth to the SAME
  hash; 350/350 binding field-cells match; counts byte-identical before/after (1
  pending_legacy_terminal / 50 inactive / 0 active / 0 bindings / 50 shadow_only /
  0 activation receipts); **ACTIVATION STILL FORBIDDEN** — needs Monday evidence
  PASS + a separate token per ratification 1. States: single-leg DARK 0/50 opt-in
  · TCM v2 observe-only · taper DARK (band reconciliation pending) · greek caps 0
  · OI no-gate · E19 BLOCKED (ratified minimum 8 awaits protocol v3 re-freeze) ·
  UI BLOCKED_UI_FILE_OWNERSHIP · operator checkout hash ddb9e073 (drift = the
  nightly's own artifacts). ZERO migration / production-DB-write / broker / env /
  fleet mutations this run; ACTIVATE_FLEET=false; entries_paused untouched.
  **07-19 EXTERNAL AUDIT v1.6 + REMEDIATION** (`docs/review/
  external-full-audit-v1.6-results-2026-07-19.md` + `v1.6-remediation-results-
  2026-07-19.md`; ledger 07-19 entries = exclusion memory): ten areas at pin
  `20ca312e`, retained 1 HIGH / 4 MED / 5 LOW + notes, free-look 0, fleet
  READY_FOR_SEPARATE_AUTHORIZATION, no loosening anywhere. MERGED+DEPLOYED:
  #1303 `d6a3174e` (results docs; F-A4 = the ABSENT durable arm-decision/
  would_flip evidence contract — generic `[RISK_BASIS_SHADOW]` lines never
  satisfied the arm gate) · #1305 `8588754d` (**the HIGH fixed**: nightly runner
  is disposable-worktree-only — truthy-`Path("")` dead fallback killed, all
  destructive git through one re-verifying choke point, per-run-tagged durable
  markers in `audit/runner-markers.log`, completion re-read from disk, UP-ping
  only after artifacts validate; adversarial FAIL→repair→PASS; the 07-19
  operator-checkout mutation + false-green ping class is dead IN CODE).
  LOCAL LANDING RESOLVED same day (completion run): three-way compare proved
  `LOCAL_UNIQUE_CONTENT=0`, duplicates archived, ff-pull clean — the
  Task-Scheduler checkout now runs the FIXED runner (first natural proof =
  the next 00:00 CT nightly: per-run-tagged markers in
  `audit/runner-markers.log`, fresh `%LOCALAPPDATA%` worktree, checkout
  untouched). **ALL SIX LANES MERGED+DEPLOYED** (serialized, opus adversarial
  PASS each, per-merge 4/4 deploy SUCCESS + safety): A #1306 `362bd3da` arm
  evidence — durable `job_runs.result.cycle_metadata.risk_basis_arm_evidence`,
  enforcement DARK (one H9 loud-partial repair in review) · B #1307 `aced5eaf`
  HMAC canonical prod detector, production nonce-outage UNCONDITIONALLY
  fail-closed (typed 503), all 8 #768/#769/#774 security suites unskipped ·
  C #1304 `54fd978a` holiday market sessions — broker-calendar `MarketSession`,
  ENTRIES fail closed on outage, exits structurally immune · D #1310 `0feb6cec`
  lifecycle milestones staged/broker_submitted/filled (observe-only; broker
  evidence only) · E #1309 `0be131f6` OI observation-date vs retrieved-at split,
  freshness only from real dates · F #1308 `d4c083ea` shared divisibility gate
  (non-divisible leg → typed uncovered; byte-identity proven; caps still 0).
  Full record: `docs/review/v1.6-remediation-merge-completion-2026-07-19.md`.
  **07-19 EXTERNAL AUDIT v1.7 VERIFY+REMEDIATION** (`docs/review/
  external-full-audit-v1.7-results-2026-07-19.md` + `v1.7-remediation-results-
  2026-07-19.md`; ledger 07-19 v1.7 entry = exclusion memory): 5 findings
  re-adjudicated at `f48c298c`, each CONFIRMED Fable-reproduced. **MERGED+
  DEPLOYED + 2 DDL migrations APPLIED by exact name (NEVER REAPPLY):** #1316
  `3ec4f766` + #1317 `2b9099d3` — **V17-1 internal-close atomicity FIXED**:
  atomic `rpc_commit_internal_close_v1` (migration `20260719180000_rpc_commit_
  internal_close_v1`, MCP ver `20260719215826`, receipt `8cfd7333`) all-or-none
  economic commit with server-derived cash + write-once marker + live-order +
  non-finite guards; the internal/shadow close route now makes ONE RPC call, no
  non-atomic fallback (the pre-commit-side-effects orphan/double-book class is
  DEAD). Never write the close economics sequentially again — route them through
  `rpc_commit_internal_close_v1`. · #1315 `390bf3c7` — **V17-2 fleet activation
  binding FIXED**: hardened `rpc_shadow_fleet_activate` (migration `20260719020000_
  harden_shadow_fleet_activation_rpc`, MCP ver `20260719231412`, receipt
  `84687a20`) — old 4-arg overload DROPPED; the 5-arg server-DERIVES the binding
  from the 50 approved registry rows `ORDER BY policy_registration_id COLLATE "C"
  ASC` and requires the operator-attested manifest fingerprint == server
  recompute. **⚠ The reproducible binding fingerprint is now `1cd004b5…`
  (`6f8d1499…` was an out-of-repo bundle value, NOT reproducible from code) —
  owner-packet-1's activation attestation must be RE-ISSUED against `1cd004b5…`;
  fleet UNCHANGED and INACTIVE; scenario-5 receipt-existence OPEN by design.** ·
  #1314 `d7c2ebd5` — V17-5 credential-safe market-data logging (rotation
  NOT_PROVEN). · #1318 `d1a7f22b` — V17-3 SUPERSEDED (#1299) coverage-fields +
  V17-4 TCM cohort conflation FIXED (broker-live keyed on `execution_mode=
  'alpaca_live'`, never on cohort name). V17-1 census CLEAN (operator packet
  `docs/review/v17-1-internal-close-anomaly-census-2026-07-19.md`; NO rows
  corrected). Zero broker/fleet-activation/data-correction/env/control writes.
  **07-20 EMERGENCY MARKET-CALENDAR HOTFIX** (`docs/review/
  calendar-space-datetime-hotfix-2026-07-20.md`; ledger 07-20 entry): a Lane C
  #1304 regression fail-closed ALL entries on valid trading days — the alpaca-py
  SDK `Calendar.open`/`.close` are naive datetimes whose `str()` is
  space-separated `'2026-07-20 09:30:00'`, which `market_session._parse_session_
  time` (accepted only bare/`'T'`-ISO) rejected → `MarketCalendarUnavailable` →
  `suggestions_open` blocked pre-scan (two forced runs `df3c56e9`/`25a96ae6`
  partial + 2 HIGH alerts). **FIXED same-day mid-session (operator-authorized,
  broker flat):** PR #1320 merge `2070056f` — ONE canonical `_parse_session_time`
  authority (shape-branching: datetime aware→ET/naive→ET-wall, `time`,
  `'T'`-or-space ISO via `fromisoformat`, bare; date-only+malformed→None→
  fail-closed) + `normalize_session_bound` the wrapper delegates to. H9
  fail-closed preserved; no holiday/boundary/gate/schedule/threshold/routing
  change. **Natural 16:00 UTC scan PASSED** (succeeded, full cycle, 163 honest
  rejections, 0 suggestions/orders). When touching `market_session.py` /
  `alpaca_client.get_calendar`: the SDK yields naive-ET datetime bounds — keep
  the single parser authority, never re-narrow to a `'T'`-only check.
  Draft-PR tracking lives
  in docs/backlog.md + audit/ledger.md — this registry lists merged/deployed
  facts.

Sanctioned mid-session kill switches, complete list: the explicit-falsy
flags above (#1038, #1040, #1046, #1048, #1045-TTL, #1052, #1072, #1073,
#1076 `CALIBRATION_TRAIN_LIVE_ONLY`, #1101
`ENTRY_ROUNDTRIP_COST_GATE_ENABLED`, #1119 `STREAK_BREAKER_ENABLED`), unset
`RISK_UTILIZATION_GATE_ENABLED` (reverts to the stricter BLOCK),
`PRICE_CLASS_SPREAD_CUTOFF=0`, unset `EXIT_MARK_SANITY_ENFORCE_ENABLED`
(reverts to observe-only), unset `GTC_PROFIT_EXIT_ENABLED` (no new resting
TPs; existing rest until filled/cancelled), the DB lever
`ops_control.entries_paused` (#1097 — entries-only, no deploy), and the
global trio `SCHEDULER_ENABLED` / `CALIBRATION_ENABLED` /
`RISK_ENVELOPE_ENFORCE`. The #1051 PoP fix, #1017 fill fix, #1071 brake,
#1079/#1080 trigger basis, and #1116 mark-write corroboration deliberately
have no switch (measurement corrections).

## 5. RISK FRAME

Constraint stack, in evaluation order (current numbers: query, don't trust
docs — H14):

1. **Settled-OBP truth** — deployable = live Alpaca `options_buying_power`
   (60s TTL). Never equity, never a DB snapshot.
2. **Realized-blind daily brake** (#1058/N1) — broker `equity − last_equity`
   tightens all four envelope feeders (GATED: pre-approved, do not re-find).
3. **Utilization cap** (#1044, small tier) — pro-forma total-utilization.
4. **Envelopes** (`risk/risk_envelope.py`): `concentration_symbol` block
   (WARN at small tier under #1044) · sector/expiry/stress warn ·
   greeks layer DORMANT (§8 — no inputs, no caps; do not cite it as live
   protection) · earnings-count block · daily/weekly/per-symbol loss
   **force_close**. `passed=False` only on block/force_close — warns never
   block.
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
silence is by design. **Queue routing** (RQ, via
`enqueue_job_run(queue_name=…)`): trading-day pipeline + per-cycle + IV-daily →
`otc` (worker); the 6-job post-close learning chain (learning_ingest_eod ·
paper_learning_ingest · policy_lab_eval · post_trade_learning · promotion_check
· daily_progression_eval) + `iv_historical_backfill` + `thesis_tracker` + the
unscheduled operator-triggered `replay_integrity_check` → `background`
(worker-background) — long/secondary work off the trading queue (A5; the
2026-05-15 starve class). Full map pinned by
`test_learning_chain_queue_routing.py`.

## 7. AUDIT LOOP

- **Nightly v5.1 audit** at midnight CT via Windows Task Scheduler
  (`\nightly-audit` → `audit/run-nightly.cmd`): NIGHTLY mode diffs vs the
  prior report (≤8 subagents); FULL on Sundays. Prompt: `audit/v5-prompt.md`.
  Structure: **A8 (Negative-Decision Efficacy) and A9 (Alert & Signal
  Integrity, graduated 07-03) are STANDING; A10 is the rotating lens slot**
  — specs live in `audit/area8/9/10.md`, current lens per the file, never
  this doc.
- **READ-ONLY contract is absolute**: the loop writes reports
  (`audit/reports/YYYY-MM-DD.md`) and `audit/ALERT-<date>.md` files only — it
  never merges, flips flags, or trades, even on a critical finding. The human
  acts in the morning. **Sweep convention (07-08, meta-audit gap #9): the
  loop never commits, so untracked reports hide findings from the committed
  view — every build session sweeps any untracked `audit/reports/*.md` into
  its PR; the morning ritual checks `git status audit/`.** The nightly's
  dead-man ping fires only after the dated report file exists
  (run-nightly.cmd; unset `NIGHTLY_AUDIT_PING_URL` = logged no-op).
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

- **The greeks exposure envelope is SINGLE-dormant since 07-18** (was
  DOUBLE-dormant, verified 07-02): #1259 populates per-leg greeks at stage
  time going forward (complete-finite dict or typed `greeks=None` +
  `greeks_status` — never partial, never fabricated zeros), #1261 made
  check_greeks null-safe with typed `greeks_coverage`, #1263 wires persisted
  greeks into the canonical `normalize_position`/`aggregate_greeks` path
  (sign applied exactly once), and #1269 FIXED D2 in check_greeks — the
  reported `portfolio_greeks` is now the honest SIGNED net (no longer a
  lying display). BUT all four caps still default 0 = no-limit, so it is
  STILL NOT live protection. The `compute_stress_scenarios` unsigned
  residual was CLOSED 07-18 evening (#1276 — signed via the canonical
  `_direction_sign`; clamp preserved; `worst_case ≡ correlation_one` so the
  warn surface is byte-identical). D3 ratio-blindness was RESOLVED 07-19
  (#1290 `89a736807` — `leg_full_contract_count` owner helper; a 1×2 ratio
  spread now scales to 150, a 1:1 structure is byte-identical to the pre-fix
  path; both check_greeks and compute_stress_scenarios migrated to the
  helper) — no greek defect remains pinned. Arming caps is STILL a separate
  owner decision and must consume `greeks_coverage`; historical legs remain
  greeks-less.
- **Shadow-cohort ledgers are partly fiction** (quantified 07-02,
  `docs/specs/shadow_fill_realism.md`): shadows fill 100% by construction
  at 5–17× live size; live fill rate ≈1/3 (10 of ~54 orders died
  watchdog-cancelled unfilled). Same-period twin magnitudes ran 3–45×
  (SOFI −1,044 shadow vs −40 live). Champion promotion compares these
  ledgers — treat cross-cohort P&L comparisons as basis-broken until
  gap-3(a) promotion-time normalization ships. Twin pairing is
  (symbol, cycle), never suggestion_id.
- **DOC≠BUILT instances**: `check_new_position` (risk_envelope) has zero
  production callers · the `9a2cef1` pattern — a commit that claims a fix
  without wiring the call site, its test module-skipped · the greeks
  envelope above — grep for the implementation AND query for real inputs
  before believing any claim.
- **Add-to-position seam**: #1038 exempts and #1040 must NOT exempt orders
  with a position_id; a future add-to-position feature hits both — revisit
  before building it. The resting-TP single-owner skip keys on the
  `intentional_resting_exit` marker + close side; an add-to-position close
  side could collide — revisit there too.
- **OUTPUT_FRESHNESS watches FOUR tables** (calibration_adjustments ·
  learning_feedback_loops · paper_positions.last_marked_at 168h ·
  suggestion_rejections 120h). Caveats: a FLAT book writes no marks (long
  flat stretch can false-age the mark entry); the monitor's Part-B persist
  does NOT stamp last_marked_at (q15min writes invisible — residual); no
  weekend exclusion in the checker.
- **POLICY_LAB single-champion path**: the champion fallback (`"aggressive"`
  in transition windows) is ungated — known, accepted, on the ledger.
- **`learning_feedback_loops` has NO typed symbol column** — symbol rides in
  details_json; a typed select 42703s (the #1098 phantom-column class; it
  nearly made the streak breaker fail-closed-pause every run). Introspect
  information_schema BEFORE writing queries against learning tables.
- **A9 07-06 additions:** the `[OPS_ALERT] no supabase client — webhook-only
  legacy mode` WARNING fires on every DESIGNED client=None egress (relay +
  allowlist path) — it reads as pipeline degradation when the pipeline
  worked · **severity vocabulary is fragmented**: `medium` + `warn` are the
  two LARGEST warning-class buckets (direct-insert writers bypass
  `_VALID_SEVERITIES`) — a `severity='warning'` filter misses ~83% of the
  class · the A4 silent-failure detector reads ONE result convention
  (`counts.errors` — only paper_learning_ingest emits it); executor
  `status:'partial'` errors are invisible to it. Taxonomy PR ledger-queued.
- **EXIT_EVAL_DEBUG is only PARTIALLY fixed** (un-retired 07-06, A9-F9):
  cohort-built conditions print honestly (#1067), but the DEFAULT path
  prints flat 0.35 while the decision time-scales (±43% of entry cost) —
  the original phantom class survives on no-cohort positions.
- RESOLVED liars (cite, don't re-find): ghost-sweep shadow noise (#1107) ·
  is_paper mislabeling (#1069/#1076) · the blanket-dismiss funnel (#1073 +
  33-row backfill 07-02) · the 07-06 OBP int(None)/universe inversion
  (M4 item 0: serializer null-tolerant, live-mode capital fail-closed).

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
- Never write `entries_paused=false` from code — un-pause is OPERATOR-ONLY
  (#1119's recovery contract; the breaker never clears its own trip).
- Never select a typed `symbol`/`strategy` column from a learning table
  without introspecting information_schema first (§8 phantom-column class).
- **Never pin a flag-gated behavior with tests that bypass the production
  call path** — an orphan function with green tests is the 9a2cef1/#1126
  class (detection: 2 months then; <24h via audit PASS-2 now). The wiring
  test must exercise the seam production actually calls.
- **A wiring test must EXECUTE the production route, not REFERENCE the
  production function.** A source-string / `inspect.getsource` assertion (or a
  test that reimplements the logic locally) is the #1126 costume in test form:
  it stays green while the active route bypasses the wired code. (E7, 07-11: the
  M4 viability test source-pinned `get_executable_suggestions` while the live
  executor `_execute_per_cohort` sorted on the stored column — the bias was
  inert for days behind a green test.) Drive the entrypoint end-to-end and
  assert on the OUTPUT.
- **Inject the failure at its ORIGIN, assert the truth at the TOP** — a test
  spanning all layers cannot be beaten by the layer below; mock-replacing an
  INTERMEDIATE function forfeits every layer beneath the mock. (v1.4 07-12: the
  three same-day seam kills all sat ONE layer below their route-driving tests —
  E8-3 #1186's test mocked `_check_user`, so the inner `_fetch_open_positions`
  `[]`-swallow survived green; E16-3 #1188 tested the manifest HELPER, not the 5
  uncovered production returns + the runner classifier; E19-2 #1190 called the
  cloner with an already-eligible source, never crossing the calibrated status
  gate.) Drive the entrypoint through a failure injected at the DEEPEST callee
  (the DB query throws / the upstream gate rejects) and assert the top-level
  outcome (the job records failed/partial; the manifest exists; the shadow verdict
  is produced). A green test on a helper is not a green closure on the route.
- **Never treat a fail-closed degradation as automatically safe: fail-closed
  can still fail-WRONG.** A degradation that changes WHICH universe is
  scanned (the 07-06 $500→micro inversion) is a different strategy, not a
  smaller one. Degraded inputs must block the decision or preserve its
  shape — never silently re-parameterize it. Null-tolerate every optional
  field in external API parses; fail loud BY NAME on required ones.

---

## 10. ORCHESTRATION & EVIDENCE CONTRACT

- **Pin and partition before parallel work.** Ground host, DB, and broker
  clocks where those truth sources are available; otherwise state the missing
  access explicitly. Record `origin/main`, the Railway-deployed SHA, and each
  target PR's base/head/CI state. Enumerate changed files before assigning
  lanes. One active owner per file; shared docs and `CLAUDE.md` belong to the
  final reconciliation lane unless ownership is explicitly transferred.
- **Keep proof layers separate.** Label material claims `VERIFIED-CODE`,
  `VERIFIED-MERGE`, `VERIFIED-CI`, `VERIFIED-RUNTIME`, `INFERRED`, or
  `NOT_PROVEN`. Green tests prove only their exercised route; a merge proves
  neither deployment nor behavior. When no qualifying natural event occurs, the result is
  `INCONCLUSIVE`, never PASS. Use §9's origin-to-top rule for every defect.
- **Empty data is not a failed read.** A successful zero-row result and a DB,
  broker, or provider failure require different typed outcomes. Position,
  order, and capital reads must never turn an exception into `[]`, zero, or a
  fabricated default that makes the book look flat; propagate the error until
  the top-level job is partial/failed or the decision is blocked.
- **Routing intent is not execution fact.** `routing_mode='live_eligible'`
  does not mean broker-live. Only `execution_mode='alpaca_live'` identifies
  the broker-filled cohort; paper/internal/shadow modes stay separate in every
  headline, denominator, calibration cohort, and falsifier.
- **State economic basis and unit before comparing values.** Scanner/
  orchestrator `ev` and `ev_raw` are per one structure-contract; served `ev`
  may be calibrated while `ev_raw` remains separate. `rank_at_decision` is
  ordinal, canonical RAeV is a dimensionless ratio, and account equity is
  capital—not position P&L. Never threshold, aggregate, or compare a value
  whose basis, unit, quantity scaling, and provenance are unknown.
- **Structure risk requires a canonical payoff representation.** Premium
  received, entry debit, and account equity are not substitutes for defined-
  risk max loss. Normalize signed legs, ratios, strikes, expiries, structure
  quantity, and per-leg multipliers; consume a position-level `*_total`
  exactly once. Missing/malformed legs or unbounded payoff must produce a
  typed non-green outcome—never a premium fallback, zero, or finite cap. When
  migrating consumers, invert the existing defect pins and keep unrelated
  greek/stress/sizing seams in separately reviewable changes.
- **Capital evidence has strict precedence.** When `net_liq` is present and
  non-null it is authoritative, including when it is invalid: zero, negative,
  non-numeric, NaN, or infinity must fail closed and may not fall through to
  cash. `cash_balance` is a basis only when `net_liq` is absent/null.
  Never fabricate nominal shadow capital. A failed cohort capital read must
  create no clone/score and must propagate to `counts.errors` plus a
  partial/failed top-level job.
- **Count effects from successful writes, not intended rows.** Tag, clone,
  verdict, and manifest counts increment only after the durable operation
  succeeds. A caught write exception must carry a typed stage to the job
  result; an alert receipt does not convert the failed effect into success.
  Report champion/control status separately from experimental-path status.
- **Model identity and deploy identity are different provenance axes.**
  `APP_VERSION` or a Git SHA identifies deployed code, not the prediction
  model. Persist model/strategy/scanner version from its own source and stamp
  the basis; if none exists, say `unversioned`. Preserve deploy version/SHA
  separately. A model-only change must alter model identity without requiring
  an application-version fiction.

- **Option transaction costs are leg- and quantity-aware.** State whether EV
  is per structure-contract or total before subtracting costs. Commission is
  per leg × structure quantity × side; round-trip measurement includes both
  entry and exit. Never subtract quantity-total fees from per-contract EV.
  Missing or malformed leg count on a production candidate is a typed
  unavailable/fail-closed measurement, not an assumed one-leg structure.
- **Funnel denominators are separate semantic facts.** Active universe,
  selected symbols, scanner-emitted candidates, persisted suggestions, and
  executable suggestions are not aliases. Preserve each name and count; zero
  means measured-empty while null/typed unavailable means unmeasured. On
  retries, report durable unique effects rather than attempted writes.
- **Expiry-day thesis measurement resolves post-close.** The naturally
  scheduled post-close tracker may grade an original expiry equal to its run
  date from the exact expiry-date close only after the post-close guard. A
  missing close remains typed unknown/partial; never defer a Friday expiry
  merely because `expiry == today`, and never fabricate a terminal price.

- **An experiment may claim only what it observes.** Raw-candidate
  eligibility is not entry selection, capacity evaluation, execution, or
  outcome evidence. Shadow fills and $100k-era cohort ledgers do not prove
  live edge for the small account; preserve historical epochs and create a
  versioned prospective cohort instead of rewriting history.
- **Evidence clocks reset only for a named causal change.** Record the UTC
  boundary, full SHA, population, decision mechanism, and capture state.
  Merge/recycle/container restart alone does not reset a window. A real
  semantic, population, decision, or capture-integrity change may reset it;
  otherwise retain the original boundary and report `START UNVERIFIED` when
  the exact first natural event is unknown.
- **Close lanes in order.** Reproduce against the pinned base, make the
  minimal patch, prove champion/control non-interference where applicable,
  rebase, adversarially review, rerun fresh CI, then grade the natural runtime
  falsifier. Update backlog, ledger, audit result, and this doctrine only
  after code lanes settle; deduplicate by extending the canonical item.

Pointers: `docs/backlog.md` and `audit/ledger.md`.

---

## Small-tier shadow-fleet evidence contract

- `small_tier_v1` is exactly 50 isolated virtual accounts, each initialized
  with $2,000 net liquidation and $2,000 cash. The $100,000 sum is
  administrative/reporting-only: it is never a sizing balance and capital,
  utilization, or loss recovery never crosses account boundaries.
- A micro account remains inactive until it has one unique pre-registered
  policy identity. Unassigned slots stay inactive; identical policy copies do
  not manufacture independent evidence.
- Preserve historical $100k portfolios as `legacy_100k`; never rescale,
  rewrite, or pool their fills/P&L with the small-tier epoch. Activation
  requires zero legacy open positions, zero legacy working orders, and one
  explicit timezone-aware effective timestamp at the durable transaction.
- Evaluate each natural candidate once. Every account evaluation carries the
  source suggestion UUID as immutable `decision_event_id`. Statistical n is
  `COUNT(DISTINCT decision_event_id)`, never evaluation/position/account-row
  count; cross-policy analysis is paired on that identity.
- A schema migration, merged contract, or operator design approval is not fleet
  activation. Migration application, policy registration, clean-boundary
  runtime proof, row creation, and any runtime caller are separate gates.
- The fleet is shadow/observe-only. It never authorizes a live flag, control,
  threshold, stop, gate, strategy, universe, cadence, or broker action.

---

## Backlog standing and closure discipline

- The newest dated **POST-MERGE STANDING** block in `docs/backlog.md` is the
  actionable queue. Older dated queue text is preserved as history and must not
  be rebuilt when it conflicts with the newest standing.
- Before opening a lane, verify the alleged gap against current `origin/main`
  code and merged PRs. Classify it as **shipped**, **partial**, **runtime
  pending**, **gated/operator-owned**, or **open**.
- A partial closure must name both the shipped slice and the exact remainder.
  Never close a broad family because one consumer was fixed, and never present
  the shipped slice as a new backlog item.
- Merged code is not runtime proof. Record the natural falsifier separately;
  lack of a qualifying event is **INCONCLUSIVE**, not failure or success.
- Reconciliation/docs work never authorizes a flag, threshold, stop, gate,
  schedule, broker, DB, migration, or environment change.

---

## Current overnight standing (2026-07-16; updated through the 07-19 Sunday-implementation run)

- Main through #1227 contains the dormant small-tier fleet foundation, the
  calendar-stable prequential fixtures, and truthful calibration-report fetch
  semantics. Fleet schema applied 07-17 (`20260717052208`); the fleet
  RPC + dispositions + quote-provenance migrations applied 07-18; the
  `policy_registrations` migration + `h7_subreason_check` constraint applied
  07-19. The seven activation blockers were RESOLVED 07-18 (weekend run) —
  the legacy-terminal boundary is clean. **07-19: the fleet is now PROVISIONED
  INACTIVE** — fleet `b8b1ea1f…` status `pending_legacy_terminal`, 50 inactive
  `$2,000` slots / 50 `shadow_only` portfolios / 0 policy bindings, and **50
  approved policies are registered** (seed receipt `14ca10ab…`; NEVER
  REAPPLY). **07-19 parallel-implementation run: a Phase-1 READ-ONLY fleet
  dry-run (NO writes) PASSED all 13 replicated checks ⇒ `READY_TO_ACTIVATE`**
  — registry 50/50 approved with recompute-clean hashes, fleet counts
  BEFORE==AFTER byte-identical, binding manifest fingerprint
  `6f8d1499…` (`ORDER BY policy_registration_id ASC`). **`ACTIVATE_FLEET=false`
  — the fleet is still NOT active; ACTIVATION (with owner attestation, binding
  the 50 slots to the 50 approved registry ids) is the ONLY remaining
  owner-gated fleet step, and it is IRREVERSIBLE-in-place (no un-activate RPC
  — reversal = the retire path).** F-BAN was removed 07-19 (#1280) — a phantom
  feature; do not cite `banned_strategies` enforcement as live. D3
  ratio-blindness was RESOLVED 07-19 (#1290) — no greek defect remains
  pinned, though all four caps still default 0 (arming is a separate owner
  decision).
- **07-19 Sunday-implementation run: the dry-run was re-signed
  (`SIGNED_DRY_RUN_PASS`)** — fingerprint `6f8d1499…` recomputed from the ops
  bundle AND rebuilt from pure DB truth to the SAME hash, 350/350 binding
  field-cells match, counts byte-identical (READY_TO_ACTIVATE holds). **The
  fleet is STILL NOT active** — activation now waits on ONE gate: a clean Monday
  (2026-07-20) natural-runtime cycle read via `monday_evidence_reader`, then a
  separate explicit operator token per ratification 1 (`FLEET_ACTIVATION_
  AUTHORIZED=1` + `execute_activation` confirm-literal + idempotency key + 50-slot
  payload + §4 attestation). Readiness ≠ authorization. The seven owner packets
  are now RECORDED (ratifications v1, #1298 — RECORDED, activates NOTHING): fleet
  activation (blocked on Monday PASS) · RETAIN `h7_dropped` (no step) · E19
  minimum **8** (awaits protocol **v3 re-freeze**) · single-leg opt-in = two NEW
  draft rows · TCM promotion **N=15** · taper band **`[800,1000]`** (⚠ conflicts
  with the merged engine's `[900,1100]` — reconciliation is a later code step,
  the engine is NOT altered) · greek caps Plan A staged.
- **07-19 nightly-runner remains a P1 OPEN item (`WRAPPER_PARTIAL`).** The Sunday
  00:00 CT shim produced a VALID clean FULL audit report (`17141967`, 0
  crit/high), but the wrapper CONTRACT did not complete — start/end markers,
  heartbeats, the fresh `%LOCALAPPDATA%` worktree, and the completion ping never
  reached the operator `cron.log` (manifest `workspace.path='.'` — `cwd='.'`
  semantics). Morning fix: repair the marker/worktree wiring + check the 07-19
  dead-man ping at the provider. New finding **F-RUNNER-BROKER-CREDS** (scrubbed
  broker snapshot `available:false` — broker creds unset in the shim env;
  non-blocking, a wiring fix).
- #1228 is a draft read-only persisted-tape hash/count verifier with an
  operator-triggered job path. It is unscheduled and does not prove full
  deterministic strategy replay.
- #1229 is a draft detection-only broker-clock guard for ops-health holiday and
  half-day truth. It changes no scheduler cadence or trading control.
- Treat both drafts as **unshipped** until adversarial review, fresh CI, merge,
  deployment attestation, and their named natural falsifiers. Do not report a
  draft, green unit test, or merged schema as live behavior.
- The next safe code work remains: fleet provisioning/activation mechanics
  behind a broker+DB-proven legacy-terminal boundary; the independent terminal-
  distribution probability source; multi-basis cost phase 2; canonical-position
  greeks/stress/reconciliation; and funnel terminal dispositions. None of those
  authorizes a live flag, gate, threshold, stop, universe, width, or cadence
  change.

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
