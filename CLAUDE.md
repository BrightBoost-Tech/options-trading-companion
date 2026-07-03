# Options Trading Companion — Project Doctrine
# Loaded by Claude Code on EVERY turn. DOCTRINE AND POINTERS, NOT VALUES:
# any fact that changes (equity, OBP, positions, counts, phase, flag value)
# is a POINTER to its source of truth, never an embedded number. Stale
# embedded state caused real phantom reads; this structure is the fix.
# Rewritten 2026-06-13; registry/liars/audit synced 2026-07-02 (≤40k chars).
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
- **#1094–#1097 unattended-readiness quartet** — config fail-CLOSED on cohort
  load failure (#1094: fault → tightest stops, never the 2–3× looser
  defaults) · scheduler watchdog registers monitor/order-sync/heartbeat in
  EXPECTED_JOBS (#1095, detection only) · risk-alert egress for the
  allowlisted critical types (#1096, `_RISK_EGRESS_ALERT_TYPES`) ·
  entries-only break-glass `ops_control.entries_paused` (#1097 — blocks the
  entry seam ONLY, monitor/exits untouched; READ side fails OPEN; flip needs
  no deploy). Exercised: #1097 live 07-02 via the #1119 trip.
- **#1100–#1102 oversight phases** — alert() insert retry (transient
  disconnects) + A4 silent-failure detector (`job_succeeded_with_errors` on
  green jobs with `result.counts.errors>0`) (#1100) · **#1101 entry
  round-trip cost gate**: at the stage seam, reject when
  `suggestion_EV − Σ per-leg (ask−bid)×contracts×100 < $15 floor`;
  `blocked_reason='ev_below_roundtrip_cost'`; flag
  `ENTRY_ROUNDTRIP_COST_GATE_ENABLED` default-ON, explicit falsy kills.
  Exercised: **first live rejection 07-02** (SOFI: gross 30.25, round-trip
  92.00, net −61.75 — the 06-30 own-goal class blocked pre-broker) ·
  #1102 close-fill-gap instrumentation (cross/mid/fill/gap_fraction into
  close order_json; feeds the Phase-3 ≥10–15-fills gate).
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
  Flag `STREAK_BREAKER_ENABLED` default-ON. Tail of paper_learning_ingest;
  result in `job_runs.result.streak_breaker`.
- **Oversight chain — ALL THREE LAST HOPS PROVEN TO THE OPERATOR 07-02**:
  dead-man's switch RECEIPT side (20 pings :00/:30 from 08:00 CT at the
  provider; DOWN-email test delivered 18:45 CT; cron `*/30 8-16 * * 1-5`
  America/Chicago, Grace 45 — FULLY ARMED) · relay path (synthetic critical
  → inbox 08:07 CT) · immediate-egress path (breaker critical → inbox
  16:20 CT, a real safety event). Detection AND delivery are end-to-end;
  do not re-prove these hops — new work verifies only its own seam.

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
· daily_progression_eval) + `iv_historical_backfill` → `background`
(worker-background) — long/secondary work off the trading queue (A5; the
2026-05-15 starve class). Full map pinned by
`test_learning_chain_queue_routing.py`.

## 7. AUDIT LOOP

- **Nightly v5.1 audit** at midnight CT via Windows Task Scheduler
  (`\nightly-audit` → `audit/run-nightly.cmd`): NIGHTLY mode diffs vs the
  prior report (≤8 subagents); FULL on Sundays. Prompt: `audit/v5-prompt.md`.
  v5.1 structure: **A8 = the STANDING graduated area (Negative-Decision
  Efficacy — audited every run, does not rotate; `audit/area8.md`); A9 = the
  single ROTATING lens slot (`audit/area9.md`, one lens per adoption —
  current per the file, not this doc).** Single-run lens rotation is A9's
  mechanism only; A8 does not swap (the 07-01 swap was reverted by owner
  contract 07-02).
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

- **The greeks exposure envelope is DOUBLE-dormant** (verified 07-02): no
  leg jsonb has EVER carried a `greeks` key (check_greeks sums zeros since
  inception) AND all four caps default 0 = no-limit. Anything calling it
  live protection — including old copies of §5 — is lying. Fix path:
  populate greeks on legs at stage time (snapshots already carry them),
  THEN decide caps. Backlogged; do not silently populate.
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
- **OUTPUT_FRESHNESS watches THREE tables** (calibration_adjustments ·
  learning_feedback_loops · paper_positions.last_marked_at 168h). Caveats:
  a FLAT book writes no marks (long flat stretch can false-age the mark
  entry) and the monitor's Part-B persist does NOT stamp last_marked_at
  (q15min writes invisible to staleness queries — residual).
- **POLICY_LAB single-champion path**: the champion fallback (`"aggressive"`
  in transition windows) is ungated — known, accepted, on the ledger.
- **`learning_feedback_loops` has NO typed symbol column** — symbol rides in
  details_json; a typed select 42703s (the #1098 phantom-column class; it
  nearly made the streak breaker fail-closed-pause every run). Introspect
  information_schema BEFORE writing queries against learning tables.
- RESOLVED liars (cite, don't re-find): EXIT_EVAL_DEBUG print (#1067) ·
  ghost-sweep shadow noise (#1107) · is_paper mislabeling (#1069/#1076) ·
  the blanket-dismiss funnel (#1073 + 33-row backfill 07-02).

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
