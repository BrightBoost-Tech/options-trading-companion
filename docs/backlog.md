# Backlog — tiered (rewritten 2026-07-02, post-close run)

Every item: one-line context · origin · reopen/done condition. Prior rewrite
(2026-06-13) and full pre-0613 history: `docs/backlog_archive_2026-06-13.md`
(narrative only, not priority). Settled items live in `audit/ledger.md`
(exclusion memory) — do not re-investigate. Pending VERIFICATIONS (as opposed
to builds) live in the ledger's pending lists, not here.

Tiers: **GATED** (built/known, awaiting operator go or an explicit trigger) ·
**P1** (next build slots) · **P2** (real but deferred) · **RESEARCH** (open
questions) · **RESOLVED — DO NOT REINVESTIGATE**.

---

## GATED — pre-approved/known, do not re-find (operator/trigger owns the go)

- **Executor cadence — DO NOT BUILD until the trigger is met** — one execution
  shot/day (11:30 CT) is the known volume bottleneck, but the one-shot cadence
  is PROTECTIVE while calibration is unproven. Trigger, verbatim: **clean
  relearn + positive EV tracking + #1071/#1072 exercised — NOT MET** (07-02:
  calibration raw at 6/8 live post-epoch closes; #1071 evaluated-clear only;
  #1072 live-unexercised). · origin pre-0610 · when met: add ONE window
  incrementally + observe — never as a gate loosening.
- **Clamp review + winsorize (calibration outlier caps) — gated on 8/8** —
  the 0.5 ev/pop floor clamp and shadow-outlier winsorize (the 06-18 +662
  NFLX rail-pin class) only bite once a segment reaches ≥8 LIVE post-epoch
  closes; 6/8 as of 07-01. · origin pre-0610 + 06-18 · do when: 8th live
  post-epoch close lands; NOT before (raw mode makes both moot).
- **Durable-oversight Phase 3 (fill-quality-informed exits)** — precursor
  instrumentation shipped (#1102 close_fill_gap; first LIVE-close
  gap_fraction still pending). · origin 06-30 approved queue · do when:
  ≥10–15 live close fills accumulated; the #1102 fields are the evidence base.
- **Paper-shadow migration pair — APPLY AS A UNIT, pre-enable gate** —
  `20260531000000_add_paper_shadow_routing_mode` (CHECK-constraint widen) +
  `20260601000000_paper_shadow_pairs` (state-machine table, lands RLS-off:
  mirror the rls_hardening precedent at apply time). Doubly inert today
  (`PAPER_SHADOW_EXECUTOR_ENABLED=false`; even a mistaken flip dies at the
  current CHECK before touching the missing table, swallowed as a midday
  warning). Blast radius: one ACCESS EXCLUSIVE lock on tiny
  `paper_portfolios` + a new table; zero behavior until the flag flips.
  · origin 06-29 diag Part 1/2, verdict re-confirmed 07-02 recon · do when:
  immediately BEFORE any `PAPER_SHADOW_EXECUTOR_ENABLED` flip
  (`docs/migration_procedure.md`, owner sign-off); RETIRE both + the executor
  module together only if Phase 1b is abandoned.
- **Dead-man's-switch operator handoff (code side SHIPPED #1109)** —
  heartbeat pings `HEARTBEAT_PING_URL` each run (:00/:30, hours 8–17 CT).
  Operator: un-pause the healthchecks check; cron `*/30 8-16 * * 1-5`
  America/Chicago, Grace 45 min; one after-hours Grace-to-1-min email test to
  prove the last hop, then restore. Semantics: silent check = one of
  APScheduler→BE→RQ→worker died — diagnose `job_runs` vs Railway. RTH-only
  trade-off accepted. · origin durable-oversight Window 1 · done when: first
  ping observed at the provider + the email test round-trips.
- **Supervised-mutation queue (operator approves each; move-don't-lose)**:
  (a) **risk_alerts hygiene sweep** — 1,040 un-acked critical/high (385 c /
  655 h, 2026-04-09→07-01) bulk-ack'd `resolved=true` + jsonb marker at
  cutoff = the relay epoch 2026-07-02T00:00Z; SQL proposed in the 07-02
  post-close report, awaiting approval. Both production readers key on
  recent created_at windows — behavior-safe. · origin 06-18 (~350 then) ·
  done when: executed + ledgered with count.
  (b) **82-row strategy/regime backfill** — 82 of 83 NULL typed-segment
  `trade_closed` rows have a linked suggestion carrying both fields
  (`UPDATE … FROM trade_suggestions`); writer fixed forward by #1110.
  · origin 06-29 diag Part 3 · done when: executed post-approval.
  (c) **32-row funnel status backfill** — historical `dismissed`-with-position
  suggestions → `executed` (dry-run-then-go). Layers A+B live and exercised
  (#1073). · origin §8 funnel · done when: executed post-approval.

## P1 — next build slots

- **data_stale job-arm predicate retune (recon COMPLETE 07-02, table ready)** —
  the flat 30-min threshold vs two 1×/day jobs produced 39 job-arm-only false
  HIGHs in 14d (100% of job-arm firings; content fixed by #1106, predicate
  untouched). Minimal fix: `OPS_DATA_STALE_MINUTES=360` (max healthy in-gate
  age observed 187 min; a dead suggestions_open still alerts same-day at
  19:07Z) — env-first, both workers. Companion: daily `job_late` arm needs the
  `_rth_job_status` warm-up-anchor pattern generalized (NOT a bigger
  threshold) — kills the 40-warns-per-Monday storm; that arm has no
  market-hours gate. Full per-job cadence table: 07-02 post-close report (B3).
  · origin 2026-06-10 root cause, ledgered · done when: retune PR ships
  env-first + zero job-arm false HIGHs over a week.
- **MTM mark-WRITE corroboration (recon COMPLETE 07-02 — decision-feeding,
  promoted per the display-vs-decision rule)** — `refresh_marks`
  (`paper_mark_to_market_service.py:206-217`) and the monitor Part-B persist
  (`intraday_risk_monitor.py:780-790`) persist RAW mid marks into
  `current_mark`/`unrealized_pl` → `paper_eod_snapshots`. Fast loss paths are
  clean (#1071/#1075/#1079/#1080); the persisted phantom still feeds
  DECISIONS on slow paths: policy-lab champion utility + HARD_DRAWDOWN_LIMIT
  auto-rollback (`policy_lab/evaluator.py:605-621` via max_drawdown), go-live
  checkpoints (`go_live_validation_service.py:1093`), autopilot-breaker and
  `_marginal_ev` FALLBACK branches, plus the close-limit price seam
  (mitigated by #1072/#1017). Severity nuance: daily cadence, error bounded
  by one day's book. Evidence 14d: 2/3 closes wrong-signed at last persist;
  SOFI persisted +196.52 thirty minutes before a corroborated −1,044.48 close
  (divergence 0.869). Fix (no new machinery): reuse
  `exit_mark_corroboration.executable_close_estimate` over the cycle's
  already-fetched snapshots (zero extra API calls) and persist ADDITIVE
  suspect/basis fields (never replace the mid mark, never fabricate when
  dark); slow-path consumers exclude/downweight suspect rows. Monitor
  Part-B side-finding: it does not stamp `last_marked_at` (staleness queries
  miss those writes). · origin 06-17/06-18 incident, unfiled until 07-02
  recon (B1) · done when: both write sites persist corroboration fields and
  the policy-lab drawdown path reads them.
- **ops_health_check effective cadence is hourly, not q30min** — scheduler
  says `minute="7,37"` but the hourly idempotency key
  (`public_tasks.py:766`) dedupes every :37 fire (99/100 observed runs at
  :07). Consequence: alert cooldowns never suppress consecutive firings, the
  A3 egress relay polls hourly, and the schedule lies. 1-line key fix
  (include minute) — decide intended cadence first. · origin 07-02 recon
  (B3) · done when: observed runs match the schedule.

## P2 — real but deferred

- **Migration tracking drift check (process fix, recon COMPLETE 07-02)** —
  27/112 migration files tracked (82 pre-tracking-era, 1 post-era procedure
  miss `20260426000000`, 2 deliberately gated). Fix: nightly-audit/CI
  drift check — diff `supabase/migrations/*.sql` basenames vs
  `supabase_migrations.schema_migrations` names (match by NAME, not version
  prefix) against a checked-in allowlist carrying each gate condition;
  not-tracked + not-allowlisted → audit ALERT. Keeps `apply_migration` the
  single canonical path. Pre-era 82-file reconciliation stays #62, separate.
  · origin 06-29 diag Part 2 · done when: the drift check runs nightly and
  the allowlist exists.
- **OUTPUT_FRESHNESS registry expansion** — watches `calibration_adjustments`
  + `learning_feedback_loops` (Phase 1); mark refresh
  (`paper_positions.last_marked_at`) still unregistered — and the monitor
  Part-B persist doesn't stamp that column (fold into the MTM P1). · origin
  06-13 audit A4 · done when: mark refresh registered with a tuned max-age.
- **v3 view Gate B (wire-vs-retire)** — `learning_performance_summary_v3`
  live since #1076; conviction multipliers all-1.0 until a live bucket ≥20
  (far off). · origin pre-0610 · reopen when: any live bucket approaches 20.
- **config.py fail-open-looser stop** — `policy_lab/config.py`
  DEFAULT_CONFIGS hardcode 2–3× LOOSER stops (≈0.40/0.50/0.65) than live DB
  cohorts (0.15/0.20/0.30); a cohort-load failure fails LOOSE — make it
  fail-CLOSED. (Ex-bundle partner ghost-sweep shipped #1107; this stands
  alone now.) · origin 06-15 · done when: cohort-load failure falls back to
  the TIGHTEST config.
- **IV/vol remaining gaps (clusters 1–3 shipped #1086–#1089)** — delta-only
  PoP for non-spread strategies, no IV-accuracy outcome loop (A4 capture
  fields now accumulating), vol-unaware sizing. · origin 06-2x IV audit ·
  reopen when: A4 rows suffice to grade IV-rank vs realized (needs live
  volume).
- **Greeks validator observe-only** — promote the greeks envelope from warn
  to a tested observe→enforce path. · origin pre-0610 · reopen with data.
- **signal_weight_history epoch/is_paper guard (tripwire, dormant consumer)**
  — segment-multiplier writer has no epoch/is_paper filter; sole reader
  `DynamicWeightService` has ZERO call sites. · origin Phase-1 scope-lock ·
  do IF/BEFORE `DynamicWeightService` is ever activated; do not guard a dead
  reader.
- **chain_mechanics_formula_anomaly noise** — legacy `option_spread_pct`
  fires >300% on deep-ITM verticals (~24×/week, observability-only). · origin
  06-13 audit A6 · done when: formula handles deep-ITM or the print is made
  honest.
- **Startup flag-echo** — boot should log the parsed value of every registry
  flag; read-back is manual per deploy. · origin pre-0610 · done when: boot
  echo exists on both workers.
- **Loss-limit coherence** — per-symbol envelope vs cohort stop vs vestigial
  0.50 precedence is deliberate-but-undecided at compounding capital (§5). ·
  origin pre-0610 · reopen when capital crosses a tier cliff; never ad-hoc.
- **Legacy rollups** — older aggregation paths duplicate canonical_ranker /
  close_math; consolidate. · origin pre-0610 · reopen with data.
- **Dead instrumentation** — submitted_at/latency fields and lying counters
  partially fixed 06-12; sweep the remainder. · origin pre-0610 · done when:
  no counter interpolates a MAX constant as an actual.
- **FK wart** — foreign-key/nullable mismatch noted in migrations. · origin
  pre-0610 · reopen with the next migration touching it.
- **Deploy windows** — codify no-RTH-merge as a CI/branch guard. · origin
  06-13 · done when: an RTH merge is blocked or warns.
- **#908 live credit-mleg-close validation** — next system close on a credit
  structure (the QQQ resting TP fill would qualify). · origin pre-0610 ·
  done when: a credit close validates positive-limit, no sign-incoherent
  raise.
- **#1035/#1036 mark fail-closed exercise** — verify both monitor fail-closed
  paths fire under partial-quote. · origin pre-0610 · reopen with a
  partial-quote incident.
- **Cohort-stop cooldown realized_loss from fill** — writer records
  trigger-time UPL, not the close fill; minor metadata inaccuracy, no
  consumer; largely obviated by the 06-15 structural clamp. · origin 06-15 ·
  done when: reconcile backfills from the fill, if ever worth it.
- **IRON_CONDOR/chop structural suppression (WATCH)** — live-only→raw forgoes
  the old ×0.5 deflate; if IC/chop keeps losing, suppress STRUCTURALLY
  (StrategyPolicy ban / min-edge), never via thin calibration. · origin
  06-18 · revisit at n≈8–10 IC/chop closes.
- **Persistent job-level worker/queue tag in job_runs** — `locked_by` is null
  post-completion; otc-vs-bg unaditable after the fact. · origin 06-18 ·
  done when: job_runs carries the executing queue/worker durably.
- **trade_suggestions.created_at index (minor)** — created_at-filtered
  queries full-scan; EOD sweeps use indexed cycle_date as workaround. ·
  origin 06-18 · done when: the index exists (fold into the next migration
  batch).
- **risk_alerts auto-resolve TTLs (successor to the hygiene sweep)** — after
  the one-time bulk-ack (GATED (a)), consider severity-tiered auto-resolve so
  the un-acked count stays meaningful. · origin 06-18 · done when: TTL policy
  decided (may be "no").
- **suggestions_open untraced extra runs (minor)** — 15 runs in 10 trading
  days vs 1 scheduled (extras ~14:0xZ + one 17:09Z); harmless to freshness
  (extra runs only refresh), provenance unknown. · origin 07-02 recon (B3) ·
  done when: extras traced to their trigger (manual/retry) or stopped.

## RESEARCH — open questions, no committed build

- **Vol brackets** — regime-conditioned sizing/threshold brackets beyond the
  normal/chop split. · origin pre-0610.
- **Area-8 capture fields** — persist underlying-spot-at-decision + spot+1d
  as the conservative proxy for DARK-leg rejects (XLE dead-leg class is
  unmarkable on the executable side by construction). · origin 06-13 audit
  A8 · done when: rejection rows carry the proxy fields (additive, observe).
- **Executable-for-stops (OBSERVE-ONLY experiment)** — log what each stop
  WOULD do on the achievable side vs mid, persist the divergence; review
  after ~2 weeks for over-fire on wide/illiquid names before any adoption
  discussion. · origin 06-15 (Phase B commit-2 deferral).

## RESOLVED — DO NOT REINVESTIGATE (cite, never re-derive)

- **Unattended-operation cluster (06-29 diag Part 4) — ALL SHIPPED**: config
  fail-open #1094 · scheduler watchdog #1095 · alert egress #1096 ·
  entries-only halt #1097 (`ops_control.entries_paused`, migration applied
  06-30) · A4 silent-failure detector + alert() insert retry #1100 ·
  entry round-trip cost gate #1101 (first evaluation pending — ledger) ·
  close-fill-gap instrumentation #1102 · scanner rejection-persist retry
  #1104 · data_stale alert content from the firing arm #1106 ·
  ghost-sweep live-routed scoping #1107 (retires the 06-13 P2 "sweep
  excludes shadows" item; §8 seam note stale pending next doctrine pass) ·
  **07-02 post-close run: dead-man's-switch ping #1109 (`97bace3`) · typed
  strategy/regime on outcome rows #1110 (`716ba2a`) · direct-insert alert
  egress relay #1111 (`7bc9927`)** — with `OPS_ALERT_WEBHOOK_URL` +
  `HEARTBEAT_PING_URL` set on both workers 07-02, detection AND delivery
  paths exist end-to-end; remaining actions are GATED operator handoffs +
  ledgered first-exercise verifications, not builds.
- **A4 ingest opened_at regression** — #1098 (`f7dab1d`); post-fix ingests
  verified clean 06-30/07-01; `realized_vol_over_hold` NULL on short holds is
  DESIGNED (`A4_MIN_HOLD_BARS=3`).
- **Learning-chain queue routing (A5 06-13)** — #1077 + SimpleWorker start
  cmd; 6-job chain on `background`; map test-pinned
  (`test_learning_chain_queue_routing.py`).
- **Funnel status truthful (#1073)** — Layer B exercised 06-18, Layer A
  exercised 06-30 (2 suggestions stamped executed at the position-insert
  seam). Only the 32-row backfill remains (GATED (c)).
- **Live-only calibration + v3 view (#1076)** — empirically confirmed 07-01
  (escalation 30/60/90 all sample_size=6 = live count); raw mode holds until
  8. [CONVICTION] DEGRADED gone (v3 live) — do not re-expect the
  once-per-recycle line.
- **REGIME_V4_ENABLED env drift** — aligned 06-18 (`0` both workers);
  behaviorally inert (flag unwired).
- **EXIT_EVAL_DEBUG honest print** — #1067 (`ad8ce0f`), operator-confirmed
  live 06-16; prints the cohort threshold the decision computes through
  (observed live 07-01: −494.496, not the flat default).
- **is_paper live/shadow discriminator** — #1069 (`efb9a3a`) + supervised row
  corrections 06-17; ingest derives is_paper from `order.execution_mode`.
- **PDT** — retired FINRA + Alpaca 2026-06-04; never flip
  `PDT_PROTECTION_ENABLED`.
- **Historical NBBO** — no historical option-quote endpoint; counterfactuals
  use executable-side-at-decision or are marked indeterminate, never
  hindsight quotes.
- **External frameworks** — no mixed-tool architecture decisions; settled.
- **Retro-recompute** — pre-#1051 sign-flipped EVs walled off by
  `CALIBRATION_EV_EPOCH`, never retro-corrected.
- **Mode-column** — execution_mode layering settled; both ALPACA_PAPER layers
  must be false for live.
- **Backtest deferral** — forward-only learning-mode is the deliberate
  choice this phase.
- **#71 async-dispatch migration sweep** — endpoints moved sync→202+enqueue:
  PR-1 audit (`rq_dispatch_audit_2026_05_04.md`), PR-2
  (/tasks/policy-lab/eval), PR-3 (/tasks/validation/init-window). All
  shipped; traceability tokens retained here because migration-doc guard
  tests assert them in this file (`test_policy_lab_eval_async_migration.py`,
  `test_validation_init_window_async_migration.py`). Do not drop the tokens
  on future reorgs.

---

### Rewrite provenance (2026-07-02)
Sources: `audit/ledger.md` through the 07-02 post-close run (#1109/#1110/
#1111), the three 07-02 recon reports (B1 MTM consumers, B2 migration drift,
B3 data_stale retune — full tables in the 07-02 post-close report), and the
06-29 diagnostic memory set. The 06-13 tier assignments they superseded are
preserved in git history of this file.
