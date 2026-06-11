# Audit Ledger — findings already found

Every finding listed here is EXCLUDED from future audit runs. Re-finding a
ledger item is a wasted slot. Runs append new findings as `status:reported`;
the human flips them to `status:shipped` (with PR#) or `status:rejected`.

## status:shipped — 2026-06-09 v4 seven-area run (PRs #1044–#1049, all live on worker 4bd5779)

- **[#1044] Pre-entry concentration BLOCK froze sequential accumulation** — share-of-book
  `concentration_symbol` check on a 1-position book = 100% > 40% → blocked ALL entries incl.
  diversifying ones. Replaced (small tier, explicit flag) by the pro-forma 85% total-utilization
  gate; concentration demoted BLOCK→WARN. (e329bf0)
- **[A1+A3+A4 → #1045] Calibration circuit frozen + strategy-asymmetric** — daily job silently
  no-opped 25 days (7 outcomes < MIN=8 in fixed 30d window); consumer served the frozen 05-15 blob
  with no TTL; apply_calibration silently defaulted ×1.0 for uncovered strategies (puts raw while
  calls halved; 2 recorded gate flips F/AAL). Fixed: window escalation 30→60→90, consumer TTL +
  calibration_stale alerts, `_overall` fallback, ops_health OUTPUT_FRESHNESS registry. (24533a8)
- **[A2 → #1046] Terminal-'cancelled' close orders permanently disarmed all exits** — BUG-C
  overcorrection; one broker-rejected/manually-cancelled close satisfied the idempotency guards
  forever; only the 'watchdog_cancelled' string accident kept retries alive. Fixed: freshness
  window (30min) + retry budget (3/4h) + critical exit_protection_disarmed alert; stale rows
  re-arm. (c63943c)
- **[A6 → #1047] Spread gate mis-keyed to account tier** — crossing the $1k micro→small cliff on
  2026-05-20 silently tightened 0.30→0.10 universe-wide (~250 would-pass kills/11d; killed the
  sub-$60 class behind 3 of 5 live fills). Fixed: dispatch = micro OR underlying <
  PRICE_CLASS_SPREAD_CUTOFF ($60). (02e1020)
- **[A7 → #1048] Stop-side cadence asymmetry** — 15-min monitor enforced cohort TPs but evaluated
  stops at the flat 0.50 default; cohort stops (0.15/0.20/0.30) checked only 2-3×/day; shadow books
  had no envelope backstop and overshot configured stops by $211.80 on 06-08. Fixed: cohort-aware
  stops at monitor cadence, fail-safe to default. (edb70d6)
- **[A5 → #1049] order_sync Step-3 unbounded reconcile** — every historical filled order + one
  pos-check round-trip per close-engine row, q5min (~52k queries/14d, #1 compute sink). Fixed:
  set-based, scoped to open positions. (4bd5779)

## status:reported — open tickets (also EXCLUDED as new findings; refining with new data is allowed only if the refinement changes the action)

- **Dismissed-status funnel gap** — `trade_suggestions.status` never reflects execution (filled
  orders reference `dismissed` suggestions; morning sweep overwrites history); the
  suggested→staged→filled funnel is uncomputable from status. Observability-only.
- **Dead instrumentation fields** — `learning_feedback_loops.entry_mid/exit_mid/
  pnl_execution_drag/pnl_alpha` populated 9/72 rows (90d), zero live readers.
- **Calibration clamp limitation** — [0.5,1.5] cannot represent a negative-realized segment
  (put ratio −3.8 floors at 0.5); calibration under-corrects catastrophic segments by design.
- **EXPECTED_JOBS coverage** — ops_health monitors 4 of ~15 scheduled jobs; nothing watches the
  scheduler/watcher itself. Partially subsumed by the OUTPUT_FRESHNESS registry (#1045) — the
  remaining work is adding entries/jobs, not a new finding.
- **PDT-P0 closure pending** — `alpaca_client.get_account()` int(None) coercions break when
  Alpaca removes the placeholder PDT fields (~2026-07-06). Ticketed P0 in docs/backlog.md.

## status:shipped — 2026-06-10 evening runbook (Phases B+C; PRs #1051 #1052, live on worker 93d19c6)

- **[v5-A1 → #1051] Honest debit-spread PoP at source** — both halves (scanner passes legs
  side→action; calculate_ev passes credit for debit) + CALIBRATION_EV_EPOCH (2026-06-11; pre-fix
  prediction/outcome pairs never calibrate the post-fix predictor) + deploy-time empty-blob reset
  (raw predictions serve until post-fix closes accumulate — calibration is in RAW MODE by design;
  a calibration_stale alert after ~06-20 is the reminder, not a defect). NFLX 06-08 fixture pinned
  both ways (0.6581→0.4840; +95.67→≈−26 SIGN FLIP); credit math pinned unchanged. (756627e)
- **[v5-A3 → #1051] Learning-store dedup + live dimension** — position-level dedup (suggestion_id
  key; order-id retained for legacy), is_paper resolved from routing (live-routed + alpaca_live →
  False) + details_json.routing/position_id; floor 04-13→04-16. Historical dup rows NOT cleaned
  (epoch excludes them from calibration; conviction legacy rollups still see them — ticketed).
- **[06-10 A1 diagnostic → #1052] Stage-quote FEED DIVERGENCE** — entry validator read Polygon-only
  while the scanner priced via the truth layer; 3/3 stage attempts on day one of #1047 died on a
  leg OPRA quoted 2.15×428/2.39×565 (83 trades). Fix: fetch_fn = truth-layer primary → Polygon
  fallback + divergence WARNING; all-sources-dark still raises EntryQuoteUnpriceable.
  Flag ENTRY_QUOTE_SOURCE_ALIGNED default-ON. (93d19c6)
- **Riders (#1051):** [UTILIZATION_GATE]/demotion/[EXIT_EVAL]-cohort lines INFO→WARNING (the 06-10
  observability miss); blocked_reason/_detail stamped on stage-time rejections (quote/cooldown/
  utilization) — closes the swept-as-stale gap. NOTE: the lying [EXIT_EVAL_DEBUG] threshold print
  itself remains TICKETED (not fixed); what shipped is the positive cohort-config WARNING line.
  The runbook's INTRADAY_COHORT_STOP polarity rider was MOOT — #1048 shipped default-ON.

### Pending verifications added 2026-06-10 evening

- ✅ VERIFIED 2026-06-11 10:00Z (M2): raw mode persisting as designed — calibration_update
  succeeded with users_updated:0, escalation tried 30/60/90d all sample_size 0 (epoch bounds
  every window; zero pre-epoch leak), last_write_age_days 0.6 (no false stale alert); latest
  blob still the 06-10 20:27Z empty reset. Consumer serves {} → 16:00Z scan scores raw.
- 2026-06-11 16:00Z: FIRST HONEST-EV CYCLE — record per-candidate ev_raw/pop_raw deltas vs prior
  days (debit EVs should drop ~2×; entries may drop to zero = CORRECT). Calibration ratio should be
  1.0 (raw mode — empty blob).
- 2026-06-11 16:30Z: if a candidate stages, watch for [ENTRY_QUOTE] FEED DIVERGENCE warnings (the
  XLE class should now price via truth layer instead of rejecting) and blocked_reason stamps on any
  rejected rows.
- Nightly-audit queue: CLOSE-side Polygon-only quote validation check (same divergence class).

### 2026-06-10 v5 FULL baseline run (all adversarially verified CONFIRMED; report `audit/reports/2026-06-10.md`)

- **[A1 2026-06-10 — CRITICAL, see ALERT-2026-06-10.md] Debit-spread PoP/EV = raw long-leg delta** —
  breakeven interpolation (ev_calculator.py:54-70) unreachable from the only production call path:
  scanner omits `legs` (options_scanner.py:3411) AND `credit=premium` is passed only for credit
  strategies (ev_calculator.py:165) → PoP falls to `abs(delta)` (:91-92). Sign-flips live entries
  (NFLX 06-08: EV +95.67 → ≈−26/ct; XLF 06-09: +55.92 → ≈+3..6/ct, below the $15 gate — passed on
  inflated PoP alone). Commit 9a2cef1 (04-12) claimed this exact fix but never wired the call site;
  test file module-skipped (#775), zero active coverage. Fix = (a)+(b) together (legs w/ side→action
  map + credit for debit), MUST sequence with reset/relearn of the floored debit calibration
  segments (06-10 blob halves both; uncoordinated fix double-corrects ≈0.24).
- **[A2 2026-06-10] Daily-loss envelope realized-blind; entry circuit breaker blind twice** — all
  FOUR check_all_envelopes feeders pass open-book unrealized only (intraday_risk_monitor.py:221,
  paper_autopilot_service.py:228, paper_mark_to_market.py:103, workflow_orchestrator.py:2834 passes
  neither), violating the risk_envelope.py:573 contract: realized stops vanish from the 8% daily
  brake (06-08 −$84 = 47.3% of budget invisible to ~22 subsequent cycles); sequential stops can
  never trip it (4×−3% = −12%/$266.50 with no brake); CB omits weekly_pnl (:256-261 → 0.0 default)
  and skips ALL envelope checks on an empty book (:227). Fix: broker-true daily (equity−last_equity,
  mirroring weekly; never fabricate) + feed all four sites + wire weekly into CB + empty-book
  aggregates (companion to the daily fix).
- **[A3 2026-06-10] Learning store double/triple-counts and can't tell live from simulator** —
  dedup keyed on closing-order id with position-level pnl (paper_learning_ingest.py:224-232,:339):
  ADBE f6eee0e9 ×2 / AMD 91d4e119 ×2 = 76.5% of training dollars; NFLX whipsaw thesis ×3 (live
  −$42/ct broker fill vs −$91/ct simulator forks); is_paper hardcoded True (:375,:394; live ingest a
  no-op stub); calibration unscoped to cohorts (calibration_service.py:258-267). The 06-10 10:00Z
  post-#1045 write trained on exactly this set (60d, N=18 claiming −$4,281.50 vs 12 deduped
  real-broker outcomes −$2,017); the frozen 05-15 blob was ALSO duplicate-trained (LONG_CALL n=10
  incl. 2 AMD dups). Fix: position-level dedup, CALIBRATION_PNL_FLOOR_DATE→2026-04-16, live/shadow
  dimension at ingest (position_scope pattern). Runner-up: pop denominator asymmetry (:299-315) +
  dead DTE segmentation (every blob ever = {_all, unknown}).
- **[A4 2026-06-10] Ops-health alert delivery 0% lifetime** — all 5 detection classes route only to
  send_ops_alert_v2 (ops_health_check.py:111-274; zero risk_alerts writes); OPS_ALERT_WEBHOOK_URL
  unset on worker AND BE → suppressed no_webhook inside status=succeeded (916 runs / 869 unhealthy /
  0 alerts EVER since 2026-01-22); severity map lacks "critical" (→0 < warning,
  ops_health_service.py:942-946) so even a webhook wouldn't deliver job_never_run; the #1045
  OUTPUT_FRESHNESS watcher inherits the dead tail. Fix: dual-channel to risk_alerts (error/critical,
  existing alert() helper + fingerprint cooldown) AFTER fixing the chronic data_stale false positive
  (30-min threshold vs once-daily jobs) and the severity map. Runner-up: scheduler_heartbeat written
  but absent from EXPECTED_JOBS — scheduler death undetectable.
- **[A5 2026-06-10] Hot-queue head-of-line blocking puts the loss monitor last in line** — monitor +
  order_sync share the serial otc worker with unbudgeted suggestions_open (no internal time budget;
  10-min RQ ceiling; options_scanner has zero deadline constructs). 06-03: 422.7s scan (70% of
  ceiling, provider latency — same workload 14.9s on 06-08) → order_sync waited 417.1s, monitor
  129.0s; daily 16:00Z grid collision dequeues the monitor LAST (25-55s, live capital open 06-09).
  Fix: route monitor+order_sync to a dedicated queue on the idle worker-background ("rq worker risk
  background") gated on read-back + monitor-cadence freshness alert (mis-route = silently disabled
  loss protection); + ~120s scan budget with loud exit_reason.
- **[A6 2026-06-10] Entry-budget stack book-blind: open positions contribute $0** — RBE
  (risk_budget_engine.py:54-57,156-208) and PortfolioAllocator._sum_open_cost_basis
  (portfolio_allocator.py:116-144) read fields absent from the 32-col paper_positions schema →
  usage:0 in 4/4 cycles since 06-08 on a non-empty book; remaining overstated 2.16× (06-08) / 1.41×
  (06-09) RBE-side; the documented 85%-less-cost-basis deduction is a no-op; the :2340 exhausted
  guard cannot fire from usage accumulation; underlying_allocation has ZERO consumers though
  utilization_gate.py:46 cites it as retained; the workflow_orchestrator.py:2179-2186 comment claims
  "under-counts slightly" + a nonexistent "backlog #80". Fix: shared paper-aware position-cost
  adapter (avg_entry_price×100×qty debit; H9 fail-loud) + ONE cap-semantics policy (40% vs 85% vs
  RISK_MAX_UTILIZATION_PCT) + wire-or-delete underlying_allocation. Runner-up: counts.universe_size
  = scanner_emitted (3 conflation sites) — universe regressions invisible in the funnel;
  rank_and_select greedy BREAK (small_account_compounder.py:280-286).
- **[A7 2026-06-10] Time-scaled profit capture unreachable in production** —
  _time_scaled_target_profit_pct's sole caller is the cohort-resolve-FAILURE fallback
  (paper_exit_evaluator.py:397); both production exit paths use flat cohort tp via
  build_exit_conditions (:421-423); the champion lookup resolves any position → ~100% of production
  positions live on the flat bar (aggressive +50% for life, incl. the max-theta window where the
  documented curve drops to ~0.245); CLAUDE.md Exit-thresholds asserts the opposite; the curve has
  zero test references (flat IS pinned). BAC 06-04 fire (+18.8% of $1,020 4ct entry) explainable
  only by the flat bar. Realized cost $0 so far (no winner aged into divergence). Fix: doc truth-fix
  + optional flag-gated min(tp, time_scaled) wiring, shadow-first, capture-earlier-only. Runner-up:
  no time-stop for stalled theses (dte_threshold only at 7 DTE, scheduled path only);
  paper_eod_snapshots accrues phantom post-close rows during manual-close reconciliation lag.
- **[A8 2026-06-10] Negative decisions 100% outcome-unmeasured (counterfactual lens adopted →
  audit/area8.md)** — ~2,384 rejects/blocks/dismissals per 30d vs 6 learned closes (~400:1);
  calibration trains only on gate-survivors (calibration_service.py:258-259); d8_v1 rejection
  capture lacks expiry → 0% of 2,361 reject rows repriceable (options_scanner.py:295-305); executor
  risk blocks stamp nothing (paper_autopilot_service.py:269-275; 06-09 XLF blocked_reason null);
  policy_decisions captured 1 rejected outcome/30d; gate-bug detection latency historically 11-25d,
  code-audit-only. 06-09 blocked XLF hand-repriced +$32..$66 in <1 day (point-in-time; +$24..$42 at
  re-read) vs held book ≈−$30. Fix (additive only): expiry in d8_v1 capture + nightly read-only
  counterfactual marker on the 100%-repriceable dismissed/blocked suggestions + per-gate
  reject-vs-accept metric with info alert at ≥3 consecutive inverted windows (never auto-loosen).

## status:reported — 2026-06-11 NIGHTLY run (report `audit/reports/2026-06-11.md`)

- **[N1 2026-06-11] CLOSE/internal-fill quote reads still Polygon-only (#1052 divergence class, close
  side)** — outcome of the ledger-queued nightly check. Stage-time combo quote (`paper_endpoints.py:645`,
  feeds TCM staging values for ALL orders incl. closes) and the internal fill engine's fresh-quote read
  (`:1179`, prices every internal/shadow fill) remain legacy `_fetch_quote_with_retry`; #1052's
  `_aligned_leg_quote_fetch` is wired ONLY into `_validate_entry_quotes`. A Polygon-dark-but-OPRA-real
  leg (the 06-10 XLE class) on a shadow CLOSE → TCM missing_quote_fallback fill at a stale
  staging-derived price (`:1219-1230`) or a stalled close — biases shadow learning outcomes/D6.
  LIVE path insulated (monitor marks = MarketDataTruthLayer `intraday_risk_monitor.py:462-487`; live
  fills = broker). Impact prospective (zero close orders since); severity LOW-MEDIUM. Fix: reuse the
  aligned fetch at both sites, observe-first.
- **[N2 2026-06-11] Stage-time skip stamping gap (refinement of the dismissed-status gap + #1051
  rider — changes the action)** — per-cohort symbol-dedup (`paper_autopilot_service.py:746-770`) and
  user-level dedup/min-edge/min-score filters (`:390-427`) skip with `continue` at logger.INFO and
  never call `_stamp_blocked_reason` (stamps cover only cooldown/utilization/quote, `:850-894`) —
  suggestions stay pending/NULL and get swept. Observed: both 06-10 16:30Z NFLX forks (aggressive
  `ff1f65b7…`, neutral `2c1d7f79…`) unprocessed + unstamped; dedup is the high-probability cause
  (both cohort books hold NFLX) — per-event attribution HYPOTHESIS (INFO line unretrievable),
  stamping gap itself code-certain. Severity LOW, observability-only. Fix: stamp
  `symbol_already_held` / `edge_below_minimum_at_stage` / `below_min_score` at the three skip sites.

## Pending verifications (not findings — check, then update here)

- ✅ VERIFIED 2026-06-10 10:00Z: first calibration write post-#1045. job_runs verbatim:
  `users_updated:1, users_skipped:0, user_details: attempts [{30d insufficient_data n=7},
  {60d ok n=18}], window_used:60` — the escalation worked exactly as designed on the first
  run, ending 26 days of silent no-ops. Fresh calibration_adjustments row 10:00:03Z
  (total_outcomes 18) with top-level keys `LONG_PUT_DEBIT_SPREAD` (first time ever:
  normal/_all ev_mult=0.5 pop_mult=0.5 [clamp floor], n=5, ev_calibration_error +$450.90,
  pop_calibration_error +0.6234), `LONG_CALL_DEBIT_SPREAD`, and `_overall` (n=18,
  ev_mult=0.5, error +$453.71). Today's 16:00Z scan is the first to score puts calibrated.
- ✅ VERIFIED 2026-06-10 16:00:34Z: `[CONVICTION]` honesty line fired EXACTLY ONCE on the first
  conviction read (entry ranker): "V3 performance-summary source unavailable (PGRST205 …
  learning_performance_summary_v3 …) — falling back to legacy … DEGRADED". Silent swallow dead.
- ✅ VERIFIED (behaviorally) 2026-06-10 16:30Z: #1044 — same 100%-NFLX one-position book that
  produced `risk_envelope_breach` on 06-09 now PROCEEDS through the breaker (result
  status=partial, per-suggestion processing reached). ⚠️ OBSERVABILITY MISS: all
  [UTILIZATION_GATE] lines (flag echo, demotion, per-evaluation numbers) are logger.INFO and
  the worker surfaces only WARNING+/print — invisible in Railway logs. Follow-up: bump those
  lines to WARNING (or set worker log level) so "log every evaluation" is actually observable.
- ✅ VERIFIED 2026-06-10: #1047 — sub-$60 rejections carry nested `spread_debug.spread_debug.
  threshold: 0.3` (CMCSA 0.3985 vs 0.30, CSX); scanner_emitted 14 (prior 1-12); FIRST 2-candidate
  staged day (XLE + NFLX). #1045 application live: puts calibrated for the first time (NFLX
  ev_raw 89.6→44.8 pop 0.321; XLE 84.1→42.0 pop 0.296) — asymmetry gone.
- ✅ BONUS-VERIFIED 2026-06-10 16:30Z: #1038 first LIVE rejections — all 3 XLE cohort forks
  raised `entry_quote_unpriceable: leg=O:XLE260717C00058000 quote={bid:0, ask:0}` (error, not
  executed). The fabricated-fill class is dead on a real dead leg.
- ✅ VERIFIED 2026-06-10: #1049 — alpaca_order_sync avg 1.38s today vs 6.46s prior (−79%).
- ⏳ #1048 exercised-no-trigger: cohort conditions loaded without failure warnings all day; no
  position crossed a cohort stop (book in profit) — first behavioral confirmation pends a breach.
- ✅ SPCX monitor first run 16:45:01Z: scanned_today=true, quote/chain false (pre-listing,
  correct), rejection_reasons [insufficient_history, no_fallback_strategies_available] — the
  loud zero-history skip on record; no scan poisoning.
- Next system close: PR #908 live credit-mleg-close validation.
