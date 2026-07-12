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

## 2026-07-11/12 WEEKEND SHIPS — DONE (cite the ledger, do not rebuild)

Full detail in `audit/ledger.md` (07-11/12 entries). Shipped this weekend:
- **F-A4-1 typed job-outcome contract** #1153 · **observability remainder** #1156
  (5 noise classes) · **E7 viability re-wire** #1158 (3rd #1126, active route) ·
  **PR2 client_order_id + reconcile** #1160 (P0-A complete) · **F-A3-1 close_reason
  persistence** #1162 (thesis prereq).
- **★ Shadow-to-expiry THESIS TRACKER (I5)** #1164 + **F-A9-1** relabel — the #1
  missing measurement; first honest number 13/16=81% (live 5/7, shadow 8/9); only
  4/13 hits profitable (loss is downstream of the signal).
- **P0-B book-scaling PR-A** #1166 (persist cost_basis_total/max_loss_total +
  observe-only [RISK_BASIS_SHADOW]) · **COALESCE ev_raw restore PR-B** #1167
  (prequential prereq closed + drift guard) · **PoP inversion PR-0** #1169
  (credit PoP 0.298→0.702; 2-leg credit cohort gate cleared) · **REPLAY_ENABLE
  Phase-0** flip (capture live from Mon 07-13's 11:00 CT scan; validation pending).
- **B1/B2 bucket control + same-run reservation** #1171 — observe-first.

---

## P0 — IMMEDIATE NEXT BUILD (07-09 external-audit v1.1 adjudication)

- **P0-A · Broker-acknowledged live-close invariant (F-A2-1) — PR1 BUILT #1149
  (`e45290f`, 07-10); PR2 remaining (submit-path client_order_id).** A LIVE close must NOT record
  `paper_orders.status='filled'` / close the position without a broker
  acknowledgement. Today (verified d45ad63) a RAISED exception around the live
  submit (`paper_exit_evaluator.py:2178-2207`; sources incl. `get_alpaca_client`,
  the order-row fetch, imports, and the pre-cancel
  `alpaca_order_handler.py:245` OUTSIDE the retry-try) falls through to an
  INTERNAL FILL (`:2272-2280` writes `status='filled'`) on a live position, and
  the monitor logs it as a successful `force_close` (`intraday_risk_monitor.py:
  1428-1434`, only `deferred_uncorroborated` counts as failure). Charter: on a
  live-routed close, a submit exception must route to retry / needs_manual_review
  / deferred — NEVER internal-fill; the internal-fill path is paper/shadow ONLY.
  Add a regression test at the seam + keep the existing
  `paper_exit_alpaca_submit_fallback_to_internal` critical.
  **DESIGN — recon #4 state-machine MERGED here (A1b verdict: MERGE, 07-09 v1.2).**
  F-A2-1 as charter-only lacked an explicit reconciling state; the recon's
  order-lifecycle spec supplies it: a typed close-order status enum with an
  **`UNKNOWN_RECONCILING`** state (submit raised → we do NOT know if the broker
  got it) + typed transitions; on `UNKNOWN_RECONCILING`, do a **targeted broker
  order lookup by client_order_id** before any DB write, and only then resolve to
  filled (broker-acked) / retry / needs_manual_review — never a blind internal
  fill. Enforce the **fill+position-closure invariant** (a position may flip to
  closed ONLY paired with a broker-acked fill on a live route). Cites: Nautilus /
  Hummingbot order-state machines (design reference, not a dependency). · origin
  07-09 v1.1 F-A2-1 + v1.2 recon #4 · STATUS: **LATENT** (never fired on a live
  position — all 9 post-epoch closes broker-reconciled; the 10 internal-fill rows
  are pre-live alpaca-paper, latest 04-06). E6 exclusion-integrity FAIL noted in
  ledger. · **PR1 BUILT #1149 (07-10):** structural guard makes internal-fill
  unreachable for live · submit-exception + routing-query-failure fail-closed ·
  monitor success-costume fixed · force_close_failed first producer · E6
  remediated. **PR2 remaining (own session):** set a deterministic
  `client_order_id` at submit (touches the submit path) + reconciler
  `get_order_by_client_id` auto-resolution of the response-lost
  `UNKNOWN_RECONCILING` edge — until then that edge holds OPEN + alarmed
  (operator-resolved). · done when: PR2 ships the targeted auto-resolution.

- **P0-B · "Book-scaling readiness" epic — BUILD HALF COMPLETE (observe-first);
  ARM DECISION PENDING.** **STATUS 07-12:** (1) persist cost_basis_total +
  max_loss_total LIVE (#1166) · (2) allocator/RBE/utilization compute BOTH bases
  + log [RISK_BASIS_SHADOW] (#1166, observe) · (3) utilization candidate honest
  basis wired behind the flag (#1166) · (4) B1/B2 one-beta bucket control +
  same-run reservation BUILT observe-first (#1171, [BUCKET_SHADOW] + #1139-
  class alarm). **The build half is done. Enforcement = ONE composed owner
  decision after ~1 week of [RISK_BASIS_SHADOW] + [BUCKET_SHADOW] logs: arming
  `RISK_BASIS_MAX_LOSS_ENABLED=1` + `BUCKET_CONTROL_ENFORCE=1` together (with
  `BUCKET_MAX_PCT`, default 0.25 — one IC ≈18% of a $2k book fits, two same-
  bucket ≈36% do not).** Worked example (ledger): a real QQQ IC is ~$149 premium
  (7.2%) vs ~$372 honest (18%) at $2,068. The #1139 tripwire remains the armed
  guard meanwhile. · origin 07-09 v1.1 F-A1-1/A1-2 + 07-03 F-A2a · **NEXT: the
  arm decision (owner), not a build.** Legacy note: the pre-build book-blindness
  (allocator ~$0, utilization premium-not-max-loss) is what #1166 addresses.

- **P0/P1 · Calibration-ordering + prequential validation (F-A1-3 + recon #2) —
  design session, not a one-liner.**
  `apply_calibration` runs post-sizing (`workflow_orchestrator.py:3562-3569`),
  so SCORE / SELECTION / SIZING all consume RAW ev; only the persisted `ev` +
  final-stage round-trip gate + persisted `risk_adjusted_ev` are calibrated.
  Either move apply before ranking/sizing OR recompute the derived score/rank
  after apply. **Re-scopes the 07-10 16:00Z "proof":** `ev==0.5×ev_raw` proves
  the multiplier reaches the persisted ev + the gate, NOT that scoring/selection/
  sizing used it.
  **ABSORB recon #2 — prequential validation** so the multiplier is earned, not
  assumed: 4-close warm-up, fit on closes 1..k-1 and score close k (never fit on
  the point being scored); prefix-invariance (adding a close never rewrites past
  scores); knowledge-time fields (`known_at <= decision_at`); append-only
  calibration runs (each run a new immutable row).
  **A1a FIELD-CONTRACT FIX (CONFIRMED IN SCOPE):** `walkforward_validate_learning_v3.py`
  reads `learning_trade_outcomes_v3` expecting `ev`/`expected_value` +
  `realized_pnl`/`pnl`, but the table exposes `ev_predicted` / `pnl_realized`
  (+ `pnl_predicted`/`pop_predicted`) — the script `KeyError`s at `df['ev']`
  (`:101`). Fix the read to the real columns before the script can honestly
  validate anything.
  **FALSIFIER (GOLD — this is the retirement condition, keep verbatim):** *"if
  calibrated fails to beat raw over the next 15–20 forward closes on EV error /
  Brier, retain raw and stop spending complexity on the multiplier."*
  **A1a PREREQUISITE CLOSED (#1147, 07-10):** the walk-forward field contract is
  fixed (reads `ev_predicted`/`pop_predicted`/`pnl_realized`; H9 0.5-fabrication
  deleted; loud zero-row/missing-col guard; ISO8601 timestamp fix; smoke-run
  ran clean on n=99).
  **RAW-BASIS PREREQ CLOSED (#1167 PR-B, 07-12):** `ev_predicted` now
  `COALESCE(ts.ev_raw, ts.ev)` — the 06-23 silent revert to bare (calibrated)
  `ts.ev` is undone + drift-guarded (`test_ev_raw_coalesce_drift_guard.py`).
  Contamination verdict: no annotation needed (raw-mode + ev_raw fallback).
  Remaining for the prequential build: add the `is_paper=false` live-only filter.
  **⚠ L1 RECON (07-12, reshapes the apply-move fix):** SELECTION sorts on
  `score`, NOT `ev` — and `score` is frozen from RAW ev INSIDE the scanner
  (`options_scanner.py:3751,3919`; `rank_and_select` reads `cand["score"]` at
  `small_account_compounder.py:242-246`). So moving `apply_calibration` earlier
  is NOT enough — the fix MUST also RECOMPUTE `score` from the calibrated ev
  (the real cost). TO-seam = right after conviction at
  `workflow_orchestrator.py:2441` (before rank :2495); DELETE the midday
  :3562-3569 apply (move-not-add — a left-behind site → ev×mult²) + an
  idempotency sentinel; hash `ev_raw` for features_hash continuity. Effort ~M
  (half-full day, dominated by score-recompute). Full spec in the 07-12 ledger.
  · origin 07-09 v1.1 F-A1-3 + v1.2 recon #2 + 07-10 #1147.

## 07-11 v1.2 adjudication — NEW ITEMS + RE-SEQUENCED QUEUE

- **NEW P0 (headline) · F-A4-1 typed job-outcome contract.** The runner
  (`runner.py:134`) decides `succeeded` on `users_failed>0` ONLY; a handler that
  RETURNS a failure (`intraday_risk_monitor.py:152-158` → `{"ok":False}`) is
  recorded `succeeded` and is invisible to the A4 detector (reads only
  `counts.errors`). FIX (doctrine-clean): a typed outcome contract at the runner
  boundary — job status DERIVED from the normalized result
  (ok/status/counts.errors/users_failed); ops-health reasons from the normalized
  status, not raw producer JSON. Rollout WITH an inventory. **FALSIFIER (theirs):
  "a deployed normalization layer absent from the repo" — NONE exists
  (confirmed).** Absorbs the A4-detector half of obs PR #1. · origin 07-11 v1.2 ·
  STATUS: confirmed-structural, **0 fatal-masked-green instances** (356 designed
  ok=false; 0 intraday_risk_monitor false-green) — bounded · done when: no
  handler-returned failure is ever persisted `succeeded` (+ a test on the
  risk-monitor fatal-return path).
- **NEW P1 · E7 viability-bias re-wire (3rd #1126 instance).** Active
  `_execute_per_cohort` (`paper_autopilot_service.py:864`) sorts by DB
  `.order(risk_adjusted_ev)` on the STORED column; the M4 bias (sort-key-only,
  in `get_executable_suggestions`) is UNREACHABLE past the `:452` early-return.
  FIX: re-rank the fetched suggestions in Python inside `_execute_per_cohort` +
  a test that DRIVES that route (not a source-string pin on the dead function).
  **FALSIFIER: does any production cohort cycle traverse
  get_executable_suggestions? — No (dead past :452).** · origin 07-11 v1.2 E7.
- **NEW P1 · F-A3-1 outcome conservation + exit-cause propagation.** Ingest
  drops closes (7d window roll-off + no-filled-closing-order silent skip) and
  ERASES the exit cause (LFL writes static `reason_codes`, never `close_reason`).
  FIX: conserve (widen/backfill + surface `skipped_no_order` in counts) + carry
  `close_reason` into LFL details. **Thesis-tracker (I5) PREREQUISITE — the
  learning chain can't see WHY trades closed until this ships.** CONSERVATION
  COUNT (07-11): of 74 live-portfolio closes, **3 missing from LFL** (MSFT
  04-15, META 02-24, AVGO 02-18) — ALL pre-live PAPER era; the 9 real post-epoch
  closes are 100% conserved. So the CONSERVATION half is LOW urgency (old paper
  data); the **exit-cause ERASURE is the real driver** (all 71 in-LFL outcomes
  lack close_reason → the thesis tracker is blind to WHY). Prioritise part (b).
  · origin 07-11 v1.2 F-A3-1.
- **NEW P2 · F-A4-2 retry re-enqueue.** `mark_retryable` flips DB state without
  an RQ `q.enqueue`; 22 `queued` + 5 `failed_retryable` fossils never re-ran.
  FIX: re-enqueue on mark_retryable (or a DB-poll re-dispatcher). **FALSIFIER (a
  deploy read): worker start cmd RQ-only vs DB-poll — RQ-only CONFIRMED →
  silent-zero.** **MERGE with the stuck-running reaper — ONE work package
  (re-dispatch + fossil disposition), same mechanism.** Fossil census (07-11):
  27 stranded rows (22 queued + 5 failed_retryable), age 19–179d, ALL STALE —
  validation_eval is deprecated, the rest are stale recurring instances; NONE
  needs replay → disposition = **reap/dead-letter, not re-run**. **FOLLOWS the
  typed-outcome build (C3 verdict: TWO builds — F-A4-1 is result-derivation,
  F-A4-2 is re-dispatch; orthogonal).** The reap is a PREREQUISITE to reading
  F-A4-1's new output (else the fossils skew the A4/dashboard baselines the
  contract surfaces). · origin 07-11 v1.2 F-A4-2 ∪ reaper.
- **NEW P2 · F-A10-1 expiry/assignment safety.** 999-DTE default on missing
  expiry (`paper_exit_evaluator.py:158`, silently disables DTE exits) +
  assignment EQUITY filtered out of the option sync (`alpaca_client.py:540`,
  `len>10` heuristic → unmanaged stock). Assignment-adjacent; latent (flat book).
  FIX: reject/flag unpriceable-expiry (H9) not 999; add an equity/assignment sync
  path. · origin 07-11 v1.2 F-A10-1.
- **NEW P2 · F-A2-1 GTC post-fill allowlist.** `maybe_place_gtc_profit_exit`
  (`gtc_profit_exit.py:328`, wired `alpaca_order_handler.py:944`) NEVER checks
  `GTC_PROFIT_EXIT_PILOT_POSITION_IDS` (the sweep does; the post-fill hook
  doesn't); gated only by `GTC_PROFIT_EXIT_ENABLED` (OFF). FIX: enforce the
  allowlist on the post-fill hook. **FALSIFIER: any GTC placed outside pilot in
  broker history — none confirmed (flag off; 6 resting orders all pilot-sweep).**
  · origin 07-11 v1.2 F-A2-1.
- **NEW P3 (cosmetic/rider):** F-A5-1 dead `phase2_precheck` (past its 48h
  self-expiry, no machine consumer — retire/re-scope) · F-A9-1 "Confidence N%"
  mislabel (`SuggestionCard.tsx:683`, a 0-100 score shown as confidence —
  relabel) · F-A8-1/2 rejection CATEGORY dimension (flat reason; economics/error
  conflated — rides the taxonomy PR) · F-A3-2 autotune logged-not-applied
  (flag-gated compute-not-apply — rides the E1 family).
- **RE-SEQUENCED POST-CLOSE QUEUE (recommended; verdict-driven — the operator
  decides):** ① **F-A4-1 typed-outcome contract** (headline — the plane beneath
  job monitoring; cheap now, 0 fatals to expose) + absorbs obs-PR-#1's
  A4-detector half · ② **obs PRs (rest)** — flat-book stale guard · cross-owner
  re-egress dedup · accuracy-warn dedup · iv-refresh all-missing→ok · stub watch ·
  ③ **E7 viability re-wire** (small) · ④ **PR2 client_order_id** (P0-A
  completion) · ⑤ **F-A3-1** (thesis-tracker prereq) → remaining latents (F-A4-2
  · F-A10-1 · F-A2-1) + P3 cosmetics. REFUTED (no item): F-A6-2, F-A9-2, I6,
  most of F-A10-2/3 (broker get_clock covers holidays).

## 07-09 v1.1 adjudication — AMENDMENTS to existing items

- **Observability PR → SPLIT (recommended).** The carried 3-in-1 (ops_output_
  stale false-ager · job_succeeded_with_errors re-egress · re-egress dedup) gains
  F-A4-1 (`iv_daily_refresh` returns ok on all-missing) + F-A4-2 (`iv_daily_refresh`
  absent from `EXPECTED_JOBS`; the watched `learning_ingest` is a no-op STUB
  while real `paper_learning_ingest` is unwatched). Recommend TWO PRs: (1) the
  alert-noise 3-in-1 as-is; (2) a watchdog-coverage PR (EXPECTED_JOBS: add
  `iv_daily_refresh` + `paper_learning_ingest`, drop/replace the stub;
  iv all-missing → non-ok). Different surfaces, cleaner attribution.
- **Thesis-tracker build gains F-A9-1 relabel:** `signal_accuracy_rolling.win =
  pnl_realized>0` is a realized win-rate, mislabeled as signal accuracy → rename
  to `realized_trade_win_rate`; the tracker becomes the real thesis_accuracy
  source. Exhibit: B1 ≈78% thesis vs the view's 12.5% realized.
- **Phase-3 instrumentation gains F-A2-2 named mechanism:** TARGET_PROFIT
  suppression on `quote_complete=False` (`exit_mark_corroboration.py:246-253`)
  discards a computed executable-side divergence when a NON-executable leg side
  is missing (stop_loss never suppressed). Measure how often TP is suppressed on
  quote-incompleteness (→ positions held longer → more stop exposure).
- **Greedy replay gains F-A8-1 dedupe requirement:** rejection totals over-count
  (inner `process_symbol` reason + outer wrapper reason both `record()`); any
  future rejection-figure analysis must dedupe. (Lane A's 07-09 replay used
  `trade_suggestions`, not the ~916 rejection figure — unaffected.)
- **A11 SECURITY LENS → recommended as the next A10 rotation** (owner-gated).
  Credential/secret-scanning/history-hygiene as a standing audit lens; the
  incumbent (Calendar & Clock) rotates out only by the owner stating what it
  structurally misses. · recommended-pending.
- **FREE-LOOK — RESOLVED #1147 (attribution CORRECTED).** stored PoP > 1.0
  (16 rows, max 1.0704) was NOT "delta-based overshoot" — the delta composition
  is bounded ≤1 (raw pop max 0.7945). It was the calibration MULTIPLIER
  (`pop × pop_mult`), already silently clamped since 2026-04-16
  (`calibration_service.py:629`). #1147 made that clamp LOUD (`POP_CLAMP_ENGAGED`,
  dormant-by-arithmetic while pop_mult ≤ 1.0) and annotated the 16 stale rows
  (annotate-not-rederive, pop preserved). Do not re-file a clamp. Re-attribution
  ledgered 07-10 as a premise-check catch.

## 07-09 v1.2 comparative-recon integration (verified before backlogging)

- **NEW P1 · Deterministic decision replay (recon #1).** A runner over the
  existing capture substrate: freeze clock / SHA / config / equity / positions,
  inject `ReplayTruthLayer`, byte-compare decision outputs. **DECISION replay,
  NOT a P&L backtest** — fill evidence stays gap-3b's. Substrate grade ~55%
  CONFIRMED: `ReplayTruthLayer.from_decision_id` has ZERO production callers
  (docstrings + one test only); capture tables (`decision_runs`/`decision_inputs`/
  `decision_features`) EXIST. **⚠ PREREQ / DROP-CONDITION FIRED (verified 07-09):
  those tables have 0 ROWS** — capture is schema-only, nothing writes it. So the
  item is bigger than "runner over existing rows": step 1 is a **capture-WRITE
  path** (wire decision capture to persist runs/inputs/features), THEN the byte-
  compare runner. Prereq rider (recon's own): the runner is blocked until
  production capture rows exist. Effort: capture-write ~3-5 evenings + runner ~3-5
  evenings (recon's "3-5" assumed rows existed). · origin 07-09 v1.2 recon #1.

- **NEW P2 · Versioned earnings-event cohort (recon #3).** Replace the
  static-2025 / filing+90d earnings estimates with a **versioned feed**
  (`known_at`, `source`, `raw_hash`); classify **ETF-exempt / earnings_overlap /
  `event_unknown`-never-silently-safe**; **fix the gate to event-before-EXPIRY**
  (A1c(ii) CONFIRMED: `options_scanner.py:3866-3879` gates ONLY on
  `days_to_earnings<=2`/`<=7`, so an earnings event inside the hold window but
  >2 days out passes — the event-in-hold-window risk is unscreened). OBSERVE-ONLY
  first; a hard skip is an operator decision after source-reliability observation.
  Falsifier/guard: `event_unknown` must never resolve to "safe". 1-2 evenings.
  · origin 07-09 v1.2 recon #3.

- **NEW P2 · Per-leg quote envelope at entry staging (recon #5).** A timestamped
  `OptionLegQuote` threaded through to the final stage with identity / executable /
  age / skew invariants; **unknown age → one refresh → `quote_age_unknown`, never
  "fresh"**. Extends the Phase-3 quote-age plumbing to the ENTRY side (today entry
  staging has no per-leg quote-age guard). 1-2 evenings. · origin 07-09 v1.2
  recon #5.

- *(recon #4 → MERGED into P0-A above per A1b; not a separate item.)*

## DO-NOT-RE-LITIGATE — rejected/settled gaps (stop next month's re-derivation)

Standing exclusion list. Each line is a gap CONSIDERED and REJECTED (or settled)
with why — re-proposing one is a wasted slot. Verified this session unless noted.

- **Full P&L backtest engine** — REJECTED in favor of *decision* replay (recon
  #1); fill realism is gap-3b's job, not a backtester's. Don't build a P&L
  backtester to "validate edge" at single-digit live closes.
- **Compounder greedy-stop `break`→`continue` build** — DOWNGRADED (Lane A
  replay 07-09): the budget break never fired in the last 4 cycles; blast radius
  zero on both risk bases. Reopen ONLY if a cycle presents >4 fitting candidates
  AND the roundtrip gate starts passing a tail. Don't re-file as a volume fix.
- **Credit-spread PoP inversion (F-A3-1)** — LATENT, NO FIX: the inverted
  `credit/width` branch (`ev_calculator.py:34-42`) accepts only 2-leg credit
  verticals; DB shows ZERO ever stored (only condors + debit spreads). Fix only
  if/when a credit vertical is actually produced.
- **Loosening any stop / envelope / gate on outcome or hindsight** — PERMANENTLY
  REJECTED (doctrine). A losing trade that passed every gate is not a gate bug; a
  proven arithmetic error is the only basis for passing more trades.
- **Shadow-cohort ledgers as EDGE evidence** — REJECTED: fill-fiction (100% fill
  at 5-17× live size; `SHADOW_FILL_DISCOUNT=0.31`). Mechanism evidence only until
  gap-3b normalization is observable.
- **"Position-management conventions missing" (21-DTE / 50%-credit / DTE gates)** —
  CORRECTED/REJECTED (A2.7): the recon confirmed these already ~85% EXIST in
  cohort policy; the earlier deep-dive's "missing" impression was wrong. Don't
  re-derive them as a new build.
- **⚠ PROVENANCE NOTE:** the comparative recon's OWN rejected-gaps appendix
  (its Nautilus/Hummingbot comparison rejections) was produced in a prior session
  and is NOT recoverable from this session's context. The items above are the
  rejections VERIFIED this session; the operator should paste the recon's full
  appendix here verbatim to complete the standing list.

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
  100 artifact.
  **PoP-UNIFICATION CENSUS (rider, #1147 07-10, hard-gate before the 2-leg
  cohort):** SEVEN base PoP computations exist (ev_calculator.calculate_pop ·
  calculate_exit_metrics `abs(delta)` [take_profit_limit source] ·
  calculate_condor_ev · options_scanner `_estimate_probability_of_profit` ·
  `_condor_pop_from_legs` · opportunity_scorer `_calculate_ev_pop` ·
  forecast_interface `forecast_ev_pop`) + 2 transforms (apply_calibration,
  conviction) — the multi-basis disease extends to probabilities. The inverted
  credit/width one (F-A1 PoP-semantics, below) is calculate_pop's credit
  branch. **A unified PoP MUST bound-assert [0,1] at the compute site** (the
  insurance the #1147 clamp-log defers to the right place — do NOT scatter
  per-site clamps). · origin 06-10 A1-runner ∪ 07-09 A3 ∪ 07-10 #1147 census.
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
