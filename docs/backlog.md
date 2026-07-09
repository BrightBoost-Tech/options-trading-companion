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
- **Supervised-mutation queue — ALL THREE EXECUTED 07-02 (operator-approved,
  exact counts, ledgered)**: (a) risk_alerts hygiene sweep 1,040 bulk-acked
  (H11 un-acked critical/high now means LIVE actionable) · (b) 82-row
  strategy/regime backfill · (c) 33-row funnel status backfill. Cite, don't
  re-run; the queue is empty.

## P1 — next build slots

<!-- ── 2026-07-09 EOD fix-queue (tomorrow, in order, operator's word) ── -->
- **① CALIBRATION-NOT-APPLYING (HIGH, headline; recon-then-fix, FIRST)** —
  the ×0.5 multiplier computes + stores 0.5-floored at 10:00Z but
  `apply_calibration` returns ×1.0 at the scan (`ev==ev_raw==39.71` verbatim
  07-09). Suspect: `get_calibration_adjustments` fails to map an
  `_overall`-only blob into the `{strategy:{regime}}` return shape → the
  `_overall` fallback (`calibration_service.py:577`) never fires; consumer
  `workflow_orchestrator.py:1745-1755`. **CLASS: built-not-wired (#1126
  family).** Cross-ref: external-reviewer §1 Q(1) — whoever moves first
  claims it, don't double-drive. · origin 07-09 EOD · done when: a stored
  multiplier ≠1.0 verifiably changes scan `ev` vs `ev_raw`.
- **② OPTION-A SHADOW-DETECTION MISS (one-liner + prod-value test)** —
  #1141 keyed `routing_mode == "paper_shadow"`; real values are
  `live_eligible` / `shadow_only` → shadow fix INERT (fail-safe to
  observe-only). Fix: match `shadow_only` (or `!= live_eligible`); pin the
  test on PRODUCTION routing values (the bug was test-fixture-vs-reality).
  · origin 07-09 EOD · done when: shadow qty>1 candidates evaluate on the
  per-contract basis. Ships after/with ①.
- **③ 3-in-1 OBSERVABILITY PR (carried from 07-09 morning FIX-TODAY; slipped
  the slot to the gate-fix)** — flat-book stale-ager guard (ops_output_stale
  on a flat book) + re-egress cross-owner dedup + #1104 writer-hardening
  (reconnect-then-retry; 6/677 lost 07-08) **+ NEW sub-item: accuracy-warn
  dedup** — `signal_accuracy_degraded` fired ×14 on 07-09 (~2/hr, observe-
  only, on the losing pool) = a fresh cry-wolf; add once-per-day /
  condition-fingerprint dedup. · origin 07-09 morning A9/A5/A4 · done when:
  H11 stops carrying the false/repeat HIGH classes.
- **④ OPTION-B OBSERVE-WINDOW CLOCK RESET (marker, at the ①+② SHA)** —
  07-09's 9 `[GATE_QTY_SCALED_SHADOW]` lines are INVALID (would-open on
  un-halved EV; shadows mislabeled live). The ~1–2wk observation counts
  ONLY from the SHA where calibration applies AND shadow-detection is
  correct. · origin 07-09 EOD · done when: the re-arm marker is stamped at
  that SHA and Option-B evidence accrues cleanly.

<!-- ── 2026-07-09 external-review adjudication integration ── -->
- **★ SHADOW-TO-EXPIRY THESIS TRACKER (NEW, P1 — the #1 missing
  measurement, from B1)** — force-closed positions leave NOTHING following
  the underlying to its ORIGINAL expiry, so thesis quality (signal) can't be
  separated from execution. B1 spot-scored **~78% thesis-hit vs 11% P&L →
  the loss is DOWNSTREAM, not signal.** Build: a lightweight tracker that,
  per closed position, records the underlying's path to `nearest_expiry`
  and scores in/out of profit-zone — observe-only, no decision impact.
  · origin 07-09 B1 · done when: thesis hit-rate is a standing metric.
- **Phase-3 exit-basis MEASUREMENT reopen (NEW, P1 — their #3; NOT a stop
  change)** — synchronized combo NBBO / order-preview capture ALONGSIDE the
  full-cross corroborated UPL + quote age + realized fill, at each stop
  fire; shadow noise-band rule observe-only. Quantifies the over-pessimism
  (A7/B1: stops fired on corroborated UPL worse than realized, closing
  winning theses early — QQQ-IC 06-15 inside its range, stopped −73).
  Explicitly instrumentation, not relaxation. · origin 07-09 A7/B1 ·
  TRIGGER: next session after the observability 3-in-1.
- **Multi-basis cost cleanup — RE-ELEVATED P2→P1 (A3 confirmed the ordering
  distortion)** — ranker fee = fee×contracts×2 (NO ×leg-count) + 5%-of-EV
  slippage proxy vs the gate's executable cross; under-costs 4-leg vs 2-leg
  in RANKING. Magnitude small ($ few on tiny EVs) but real; given B1's
  "downstream is the problem," cost coherence matters. Fold in: A4
  score-saturation (min(100) clamp, guardrails.py:138) + the SOFI perpetual-
  100 artifact. · origin 06-10 A1-runner ∪ 07-09 A3.
- **A1 PoP-semantics fix (NEW, HIGH-for-credit-work, LATENT now)** —
  credit-spread PoP = credit/width is INVERTED (≈P(loss); ev_calculator.py
  :42). Unexercised on the live book (IRON_CONDOR + debit spreads not in the
  branch) but **BLOCKS the 2-leg vertical / credit-spread cohort**. · origin
  07-09 A1 · done when: credit-spread PoP = 1 − credit/width (or a proper
  delta-based PoP) + a test on a far-OTM spread (low credit/width → HIGH
  PoP). GATES: the two-leg-vertical shadow cohort waits on this.
- **greedy-stop (Tier-2) — AMENDED (their #2): READ-ONLY REPLAY FIRST** —
  quantify blast radius before any build; staged observe-first. Rider (A5):
  the legacy compounder fit-test uses ~3%×score (~$60) not structure
  max-loss ($372) — a self-alerted 6-8× gap; the "fit" test tests a fiction.
  → **REPLAY DONE 2026-07-09 EOD (Lane A) → DOWNGRADE (tail always-empty at
  this scale).** Replayed the last 4 scan/execute cycles (07-02/07-07/07-08/
  07-09). The greedy stop is `small_account_compounder.py:280-286` (a `break`
  on first budget-non-fit; the count-cap at :258 and quality-floor `continue`
  at :266 are separate). Aggressive (live) candidates/cycle = 1 / 5 / 3 / 1;
  busiest was 07-07 (5 distinct structures, 4 QQQ + 1 SOFI; the DB's "10" is
  cohort-suffix fan-out on `legs_fingerprint`). **The budget BREAK never fired
  in any cycle:** its fit test is `current_risk_usage + estimated_risk >
  risk_budget` where `estimated_risk` is the legacy ~$40–60 stack, and ≤5
  candidates × ~$60 never exceeds `remaining_global_budget`; `risk_budget`
  column is NULL on every suggestion row. **Every non-executed candidate died
  DOWNSTREAM** — `ev_below_roundtrip_cost` ×14 + `symbol_already_held` ×1 +
  EOD dismiss — none by a budget break. Blast radius = **ZERO recovered
  executable candidates on BOTH bases**: legacy (budget never binds) and
  allocator-real (any candidate the break could spare immediately hits the
  roundtrip gate, net-EV-negative). The binding constraints are UPSTREAM
  (scanner yield ~1–2 names/cycle) and the DOWNSTREAM roundtrip cost gate — the
  greedy break is not on the critical path at ~$2k. **Reopen only if** a cycle
  ever presents >4 fitting candidates AND the roundtrip gate starts passing a
  tail (i.e. tier/scale change or spread-regime shift). The cosmetic
  `break`→`continue` fix (P2 item below) is still correct-in-principle but
  buys nothing measurable now.
  · origin 06-10 A6-runner ∪ 07-09 A5.
- **Capital-adequacy honest note (doc line, NOT a deposit rec)** — divisible
  1-lot 4-leg structures clearing real per-contract cost imply ~$7.5-8k
  equity; the ~$2k book is structurally cost-bound (§1 of the external
  packet). Record as a design constraint, not advice. · origin 07-09 §1.

- **Gap-3(a): shadow-ledger promotion-time normalization** — per-contract
  (or per-$-risked) cohort scoring + a measured fill-confidence discount
  (live fill base rate ≈0.33) applied at policy_lab evaluation ONLY (ledger
  rows untouched); kills the 5–17× size fiction before the next promotion
  eval. Spec + recon counts: `docs/specs/shadow_fill_realism.md`. · origin
  07-02 gap-3 recon · done when: cohort scores compare on a normalized
  basis; the full post-and-wait model (b) stays its own recon-first session.

<!-- ── 2026-07-09 backlog reconciliation: items that were ledger-only /
     prompt-KNOWN-PENDING only and had FALLEN OFF this actionable list
     (the report→action drift the 07-08 meta-audit exists to catch —
     re-added here so a "what's next to build" scan actually finds them). -->
- **EV-basis / fee-unit recon (LIVE-MONEY, P1, recon-first)** — the gate's
  `gross_ev` (unscaled scan-time EV) is compared against a
  quantity-scaled `round_trip` cost; the 06-10 A1-runner fee-unit finding
  and the 07-08/07-09 gate mismatch are the same class. **07-09 nightly
  proved it TIMES LIVE ENTRIES**: aggressive QQQ blocked at stamped
  `net_ev +35.62` (16:00Z) while an equivalent structure passed (17:41Z);
  gate log `net −111.86` vs stamp `net_ev NULL/+35.62` on near-identical
  candidates. **URGENCY ↑: the 07-09 10:00Z calibration boundary (EV/PoP
  ×0.5) now flows into this same comparison.** · origin 06-10 A1-runner ∪
  07-08/07-09 · done when: one basis end-to-end; per-decision NO
  reconstructable. TRIGGER: pre-market recon session (do NOT touch the gate
  from a status sweep). **⚠ 07-09 UPDATE: the DECISION-FLIPPING qty-scaling
  portion SHIPPED as #1141 (Option A, `03e11d8`, gate now per-contract for
  shadows / observe-only for live). What REMAINS here is the COSMETIC
  multi-basis unification only — the three cost models that don't flip a
  decision (scanner modeled ~$5.60 · ranker per-structure · gate
  executable). Demoted P1→P2 (cosmetic). Note the calibration ×0.5 does NOT
  currently reach this gate anyway — see the 07-09 EOD fix-queue #1.**
- **NFLX 06-08 pre-epoch live close backfill (P3, data completeness)** — the
  06-08 NFLX −$84 live close is on the broker + champion ledger (9 all-time)
  but absent from `learning_feedback_loops`; pre-epoch so it never feeds
  calibration. Filed in the ledger (07-08); promoted to a backlog line so it
  doesn't fall off (meta-audit lesson). · origin 07-08 shadow-vs-live census
  · done when: rides any future supervised backfill, or explicitly declined.
- **B1/B2 real one-beta bucket control (LIVE-MONEY, P1)** — the per-bucket
  correlation cap; the #1139 tripwire ALARMS on ≥2 live positions but does
  not CONTROL. · origin 07-03 F-A2a · TRIGGER: before the book routinely
  holds 2+ live positions · done when: block-level per-bucket % enforced.
- **Compounder greedy-stop BREAK (LIVE-MONEY volume, P2)** — first candidate
  that doesn't fit zeroes the whole cycle's selection
  (`small_account_compounder.py:286`; the comment self-doubts "skip and see
  if smaller fit? Greedy: stop"). Re-verified still real 07-08. · origin
  06-10 A6-runner · done when: `continue` not `break` (+ test); pairs with
  the A1 volume charter.
- **#1104 writer-hardening (MED, observability)** — reconnect-then-retry
  (fresh client) so a same-connection burst doesn't lose rows; 6/677
  rejection rows lost 07-08 (broken pipe on the retry too); also stamp the
  failed symbols into `result.errors` (F8 surfaced the COUNT, not the
  items). · origin 07-09 A4 · TRIGGER: bundle with today's 3-in-1
  observability PR OR next connection-burst (if it ships in the 3-in-1,
  move to SHIPPED — do not double-track).
- **06-10 runner-finding triage batch (#12, P2, one session)** — the
  goes-silent runners from the meta-audit: expiry-day×unpriceable defer
  seam (own recon, LIVE) · PoP-denominator asymmetry + dead DTE segmentation
  · funnel `universe_size`=scanner_emitted mislabel · time-stop/eod-phantom
  rows (A7-dormant territory) · A9-F4 stored-vs-recomputed fingerprint ·
  F-A2d wrapper-import-seam fail-closed skip · N4 `learning_ingested` dead
  column · N1/N2 backlog orphans · 06-10 A5 queue-HOL + A6 budget-blindness
  (verify partially-superseded). · origin 07-08 meta-audit · done when: each
  gets shipped / filed-with-trigger / acked.
- **gap-3(b) post-and-wait fill model** — promoted from the sub-note above
  to its own line (it had no standalone entry). · origin 07-02 gap-3 ·
  TRIGGER: own recon-first session, after gap-3(a)/#1124 observed at Gate 4.
- **Tradeable-universe recon (read-only)** — which universe names can
  actually pass the round-trip cost gate at current spreads (the first live
  rejection: SOFI round-trip 92 vs gross EV 30.25 — the small-tier universe
  may be structurally spread-eaten); recon before any threshold/universe
  reaction, never a gate loosening. · origin 07-02 first #1101 rejection ·
  done when: a per-symbol executable-spread table exists and the operator
  has read it.

### Shipped 07-02 from this tier (cite, don't rebuild)
data_stale predicate retune → #1115 (weekend-excluded job_late + 360 default;
0 job-arm false HIGHs on day one) · MTM mark-write corroboration → #1116 ·
ops_health_check q30min-real dedup → #1114 · signal-accuracy telemetry
(gap-2) → #1118 (baseline 1/6, Brier 0.2751) · streak breaker (gap-1) →
#1119 (planned first trip exercised + operator-recovered 07-02).
## P2 — real but deferred

- **Greeks populate-at-stage (gap-4 follow-up)** — legs have NEVER carried a
  `greeks` key (envelope double-dormant, §8 doctrine); populate from the
  stage-time snapshots (already fetched), THEN decide caps (all four default
  0 = no-limit). Never silently populate without its own PR + tests. ·
  origin 07-02 gap-4 recon · done when: staged legs persist real greeks and
  the caps question gets an explicit owner decision.
- **Streak-breaker N revisit** — N=3 chosen pre-baseline; revisit against
  gap-2 base rates once n≥15–20 live closes (config change only:
  `STREAK_BREAKER_N`). · origin 07-02 gap-1 · reopen at n≥15 live closes.
- **Mark-write residuals (from #1116)** — monitor Part-B doesn't stamp
  `last_marked_at` (q15min writes invisible to staleness queries);
  `paper_eod_snapshots` doesn't carry the corroborated fields (vol_signal
  analytics stay raw-basis). · origin 07-02 P1-C · done when: both residuals
  closed or explicitly accepted.
- **Broker-clock guard on watch→merge automation** — merge chains must check
  the broker calendar (`get_clock.is_open`, not weekday math) before firing;
  a CI watch that sleeps across a session boundary must fail-safe to
  NOT-merge; the watch must also confirm a CI run EXISTS before watching
  (the instant-return race). · origin 07-03 · done when: clock-gated or
  codified in tooling.
- **F-A1a rollback ghost-restore + recommendation-cooldown** (07-03 audit) —
  `check_rollback`/Gate-7 consume "recommended" promotions rows; an
  interleaved recommendation nets NO champion. **HARD TRIGGER: must ship
  BEFORE any challenger reaches 8 trades** (margin ahead of Gate 4's 10). ·
  origin 07-03 FULL A1 · done when: recommendation rows excluded from
  rollback/cooldown reads.
- **F-A4a stuck-`running` job_runs reaper — P2-ELEVATED (this week's spare
  slot)** — mid-run recycle orphans rows permanently (4 historical fossils
  named 07-06: validation_eval ×2, promotion_check, order_sync);
  merge-every-evening × learning-chain overlap = live odds. TTL-based: mark
  stale `running` → `failed_retryable`. Batch F-A2c (breaker NULL-pnl
  streak-break) + F-A2b (per-position vs per-symbol envelope wording) here
  if trivial. · origin 07-03 FULL A4 · done when: the reaper runs scheduled.
- **Winter-close blind hour (A10 first finding)** — `is_us_market_hours`
  close side hardcoded 20:00Z; in EST the final session hour has data_stale
  suppressed AND `_rth_job_status` unconditionally ok. **HARD CALENDAR
  TRIGGER 2026-10-01** (checked whether the taxonomy PR could carry it —
  different seam territory, kept separate). · origin 07-03 A10 · done when:
  close side DST-hardened like the open's warm-up anchor.
- **Scanner OI-floor strike filter (M2 follow-up)** — the general fix behind
  the GLD strike-modulus: filter selection candidates on `oi >= floor` at
  the same `_split_chain_to_calls_puts` seam (`None` → keep; the legacy
  fallback chain carries no OI). Self-filters every symbol's dead strikes.
  · origin 07-06 M2 recon · done when: OI floor at the seam, H9-safe.
- **Nightly-audit dead-man ping (audit-loop ③, 07-06 night triage)** — a
  healthchecks.co cron check on the local nightly-audit schedule (report
  write → ping), same pattern as the worker's #1109. Root cause of the
  07-05 miss was machine-side (30-min sleep + WakeToRun/StartWhenAvailable
  both False — operator fixing task settings); the ping makes the NEXT miss
  visible in email regardless of cause. · origin 07-06 C3 · done when: a
  missed nightly run emails within Grace.

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
  consumer; largely obviated by the 06-15 structural clamp. **07-09 triage:
  now 2-for-2 on live closes post-#1080 (−48.99 stored vs −15 realized;
  −155 vs −10) — the magnitude gap widens with the Phase-3 over-pessimism
  pattern; anything reading this column for magnitude is misled, bench
  durations unaffected. Refinement folded here, no new line.** · origin
  06-15 · done when: reconcile backfills from the fill, if ever worth it.
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
