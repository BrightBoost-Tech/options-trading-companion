# Audit Ledger — findings already found

Every finding listed here is EXCLUDED from future audit runs. Re-finding a
ledger item is a wasted slot. Runs append new findings as `status:reported`;
the human flips them to `status:shipped` (with PR#) or `status:rejected`.

## 2026-06-15 — Phase B (structural mark-validity) shipped + QQQ phantom-stop saga

- **Phase B MERGED #1067 → main `ad8ce0f`**, live both services (worker
  `2c8fca1d`, worker-background `b5c05eb1`) container start 20:55:06–07Z, CI
  green (run 27575798526). Two commits: (1) structural mark clamp
  (`risk/mark_validity.py` + exit-eval-seam wiring in
  intraday_risk_monitor + paper_exit_evaluator) — rejects |mark|>wing OR
  implied_loss>max_loss, fail-closed, NEVER suppresses a real stop; (2)
  EXIT_EVAL_DEBUG honesty (prints the cohort tp/sl/dte the decision uses, not
  `_DEFAULT_*`). +18 tests; full-suite zero Phase-B regression (31 pre-existing
  local fails == baseline). Commit 3 (resting-TP pre-cancel) DROPPED MOOT
  (broker cancel-ack 14:15:08.884Z before stop submit). Commit-2 executable-
  rewire DECLINED (false premise: decision is stateless/mid and fired
  correctly; the −80.5-vs-48.3 was the debug line interpolating
  `_DEFAULT_STOP_LOSS_PCT` 0.50 vs the cohort 0.30).
- **QQQ saga (book `6798e58f`, aggressive condor 5-wide/1.61cr/max-loss $339):**
  13:30Z monitor force-closed on a PHANTOM stop, mark −7.305 / implied
  −$569.50 (impossible). The 7.30 close order was BROKER-REJECTED → **zero
  loss booked** (luck, not a control — the new clamp is the control).
  CLOSE_REARM deferred re-close; mark recovered; QQQ genuinely rallied →
  **legit corroborated stop filled 14:15 at 2.34 / −$73** (corroboration
  14:15:07Z divergence_frac 0.089; single broker submission `1bcc6e83`).
- **Data correction (supervised, operator-GO, like prior corrections):**
  reentry_cooldowns `3d8a5820` realized_loss **−569.5 → −73.00** (1 row,
  guarded `AND realized_loss=-569.5`). The bench (QQQ → 06-16 13:30Z) was
  always correct; only the metadata carried the phantom.
- **STEP-4 audit (decision-path candidates flagged, NOT auto-fixed → backlog
  P2):** config.py DEFAULT_CONFIGS stops looser than live DB (fail-open looser
  on cohort-load failure); `exit_plan_agent.py:43,50` hardcodes 0.50 wired via
  workflow_orchestrator:3142. CLAUDE.md §5 stop references are ACCURATE (no doc
  fix). Two deferrals filed: executable-for-stops (observe-only) + cooldown
  realized_loss-from-fill (low, obviated by the clamp).
- **PENDING (do not act tonight):** 21:20Z ingest lands the −$73 QQQ close;
  expect `is_paper=true` (wrong) — the known Phase-1 A3 item, caught by the
  supervised historical correction, not a surprise. Post-epoch closes 5 → 6
  after tonight (relearn at ≥8).

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

## status:shipped — 2026-06-11 incident arc + post-close gate (PRs #1055 #1056 #1057 merged; #1058 #1059 at CI)

- **[06-11 incident → #1055] Credit-OPEN mleg sign** — first CHOP condors submitted +1.54/+1.43,
  live gateway instant-rejected in 4ms (the #101 close class, open side). Stamp `is_credit_open`
  from `_net_mid_cost` + handler flip + coherence guard. Merged mid-day by operator;
  LIVE-VALIDATED same session: QQQ filled −1.61 (limit −1.54, +$7 improvement), SPY −1.48
  (−1.43, +$5), third condor accepted+rested at −1.28; 12/12 legs priced by the #1052 truth
  layer (Polygon dark on ALL of them).
- **[06-11 incident → #1056] Fill-commit raw signed entry** — `_commit_fill`/`_repair` stored
  Alpaca's SIGNED filled_avg_price into avg_entry_price/max_credit (violating mark_math's
  absolute contract) → phantom −$300 unrealized on a +$10.50 position → 16:30Z phantom −22.8%
  daily breach force-closed the ENTIRE live book ($0 realized only because the close limits were
  mis-signed too). `_abs_entry_premium`/`_weighted_abs_entry_avg` at all six write seams +
  round-trip regression on the day's actual numbers.
- **[06-11 incident → #1056] Close-path signed limit** — short-structure closes staged the
  SIGNED mark as the limit (−1.39 buy-to-close): gateway reject + an unfillable RESTING close
  that satisfied idempotency and DISARMED exit protection. `_close_limit_and_direction`
  (unsigned magnitude; structural direction; loud disagreement) + handler inverse guard. Also
  fixes the internal-fill realized-P&L sign — the 19:00Z shadow stop close recorded +$2,369.22
  on a −$234.78 trade (the signed limit double-negated through the synthetic close leg).
- **[06-11 V4 gate trail → #1057] Utilization gate signed netting** — `committed=$56` while the
  broker held $1,365 (condor credits netted against the NFLX debit). Per-structure commitment:
  net-debit = net cost basis; net-credit = margin basis (max wing width × 100 × qty, matches
  Alpaca's $1,000 hold); naked/unboundable → fail-closed.
- **[06-11 trace — fix 06-12] Live close double-submission** — `_stage_order_internal`
  broker-submits alpaca-mode orders itself AND `_close_position` submits the same row again;
  the second call's pre-cancel kills the first broker order (2 broker orders per close, first
  canceled ~0.45s in). Never seen before: no live system close had ever executed. Writeup
  `docs/double_submit_close_trace.md`; single-submitter staging param + regression queued 06-12.
- **[v5-A2 → #1058] Realized-blind daily brake** — min(open-book proxy, broker
  equity−last_equity) into all four feeders + weekly into the circuit breaker + empty-book
  de-gates (breaker + MTM). Same-day empirical: real −8.3% day (equity 2075.42 vs 2263.85) read
  as ≈−4% by the proxy. Tightens-only.
- **[v5-A4 → #1059] Ops alert delivery** — dual-channel: risk_alerts PRIMARY (critical→critical,
  error→high) + webhook secondary; severity map gains "critical" (was 0 → the most severe class
  always suppressed); data_stale ALERT market-hours-gated (nightly staleness is structural);
  canonical alert() accepts "high" (was silently downgrading); synthetic_delivery_test payload
  hook for the end-to-end proof.

### Data corrections (2026-06-11, operator-"go" precedent; all documented in-session)

- Live QQQ `6798e58f` / SPY `a5393e2b`: avg_entry_price/max_credit ABS-corrected (−1.61/−1.48 →
  +1.61/+1.48). Applied ~90s after the 16:30Z monitor had already fired on the phantom.
- Shadow QQQ `85db73c8`: realized_pl +2369.22 → **−234.78** (arithmetic truth: credit 1.5246×7
  entry, 1.86 buy-back) BEFORE the 21:20Z learning ingest (learning_ingested was false — zero
  contamination); neutral-cohort cash_balance −$2,604 (the close's fill event credited +1302
  instead of debiting 1302).

### 2026-06-13 combined run (week-review + 8-area audit + CLAUDE.md refresh)

WEEK VERDICT (06-08→06-13): live realized **−$109** (a9f977bf NFLX −84,
7f604f7a NFLX +48, a5393e2b SPY −45, bc399a4f MARA −28), live open = QQQ
condor 6798e58f broker-unrealized **−$45**; shadow realized −$920 (mark-bias
caveat). Fees negligible (TAF pending $0.57). Modeled-vs-realized EV gap:
every staged EV positive (+26…+96), aggregate realized deeply negative;
post-epoch clean read ≈ −$67/trade optimism (raw-mode, uncalibrated —
expected, relearn ~06-20). Live MARA round-trip (18:25→18:46Z) confirms the
N1/UnboundLocalError fix unblocked the 16:00Z funnel.

SETTLED THIS RUN — do not re-find (folded to docs/backlog.md, origin 06-13):
- A1: post-#1051 EV ordering weakly agrees (2 winners carried the highest
  staged EV); uniform +EV optimism is raw-mode, not a defect. No action.
- A2/A4: ghost_position sweep flags shadows (no live-routed filter,
  `alpaca_order_sync.py:245`) → 73 shadow-noise alerts/wk burying real
  desync. → P2.
- A3: calibration healthy in raw mode (job ran 06-11/06-12 `insufficient_data`,
  last real write 06-10; 5/8 post-epoch closes). is_paper tags ALL learning
  rows paper incl. live closes → P2.
- A4: OUTPUT_FRESHNESS watches ONE table (`ops_health_service.py:79`);
  ingest/mark-refresh stalls silent. → P2.
- A5: this run respected budgets (≤10 Part-1 SQL, ≤4 broker, 0 web, archived
  the 240k backlog unread). Largest avoidable cost would have been reading
  it — avoided.
- A6: stage deaths dominated by REAL spread_too_wide_real (323) /
  no_fallback (359), not feed artifacts; #1052 working. chain_mechanics
  anomaly 24×/wk = legacy spread_pct deep-ITM edge (observability noise) →
  P2.
- A7: hold-time bimodal — debit spreads ~94–116h, condors 5–35h, live MARA
  0.3h (cohort-stop velocity). Next binding velocity constraint = the
  one-shot/day executor (P1), not fees/cooldowns.
- A8: XLE dead-leg rejects (#1038, settled 06-10) are UNMARKABLE on the
  executable side — counterfactual indeterminate by doctrine; GLD reject was
  an HONEST save (spread_debug total_ev −934). Additive proxy field →
  RESEARCH.
- TOP-3: (1) OUTPUT_FRESHNESS expansion, (2) ghost-sweep shadow scoping,
  (3) close-side quote check. No conflicts; (1)+(2) share the order-sync/ops
  surface.

PENDING VERIFICATIONS (06-13 night / next session):
- CLAUDE.md refresh PR merges per the W2 gate (CI green on the doc PR; main's
  last gate was clean at #1064 23:49Z). After merge: H8-verify both workers
  recycled to the new SHA; the DEGRADED + raw-mode-reset lines fire once on
  the new container (designed, not an incident).
- backlog.md reorg: full pre-0613 history preserved in
  docs/backlog_archive_2026-06-13.md (move-don't-lose).

## status:reported — 2026-06-15 NIGHTLY run (report `audit/reports/2026-06-15.md`)

**NO NEW FINDINGS.** Quiet weekend (markets closed 06-13/06-14); window 06-13
run → 06-15 05:03Z. Clean operation: both workers on `5778760`/#1065
(CLAUDE.md refresh, dual-parity deploy 06-13 03:15:47Z — the 06-13-pending
merge landed); weekend job silence (only `paper_exit_evaluate` 06-13 00:28Z
[placed the resting TP] + `phase2_precheck` 06-15 05:00Z, 0 failures, 0 stuck
rows); **H11 risk_alerts critical/high since 06-13 = ZERO**; broker healthy
(equity $2,179.15, OBP $1,804.15, one live QQQ 07-10 condor −$45 with resting
TP `550fccc5` GTC 0.81 alive/untouched). Flags clean, no regressions.

- **OVERTURNED CANDIDATE (verify-before-asserting):** SPY `manual_bench` cooldown
  (06-12 15:46Z, correctly valued −45, until 06-15 13:30Z) looked like a
  cohort-stops-don't-auto-cooldown gap → **already fixed in deployed code**:
  `intraday_risk_monitor.py:355` → `_write_cohort_stop_cooldown` (`:757-772`,
  `reason="cohort_stop_force_close"`), shipped #1062. The manual bench predated
  the fix (event on worker 5681919). Not a finding.

VERIFICATIONS CLOSED THIS RUN (do not re-find):
- ✅ **PR #908 live credit-mleg-close** — SPY iron condor close `1f444239`
  (06-12 15:30:07Z): buy-to-close at POSITIVE limit 1.96, filled POSITIVE 1.93,
  single order, instant clean fill, no Sign-incoherent raise → realized −45.
  Credit structure closed correctly. **Pending since the first ledger list — DONE.**
- ✅ **Double-submit pre-fix confirmed** — QQQ condor close attempts `fc1625f1`
  (06-12 13:30:07Z submit→cancel 0.6s) + `0675f969` (13:30:08Z, watchdog-cancel
  13:35Z) = documented pre-cancel double-submit on worker 5681919 (#1064
  single-submitter deployed 06-13 00:20Z, after). SPY/NFLX/MARA = single orders
  (instant fills). Single-submitter fix deployed but UNEXERCISED on a resting close.
- ✅ **#1034 TP fires write price-normalized corroboration rows** —
  `exit_mark_corroboration_observations`: NFLX TP 06-12 15:15Z (4.7355/+314.70 →
  4.131/**+133.35**, divergence_frac 0.086, `corroborated_allow`); SPY stop 15:30Z
  (`stop_loss_never_suppress`); QQQ TP 13:30Z.
- ✅ **Corrected-NFLX ingest** — `1e2dd73f` realized_pl=133.35; outcomes_v3 LPD pair
  sums +181.35 = 133.35 + 48.00. The +314.70 fiction did not propagate.
- ✅ **#1056 write-side** — DB QQQ condor `avg_entry_price=1.61` (positive); coherent.

PENDING VERIFICATIONS (carried — all fire on today's 06-15 RTH, the first
session on #1062+/#1065 code after the weekend):
- **#1034 corrected normalization + Stage-2 enforce, FIRST FIRE.** Every
  corroboration row in-window is PRE-fix (worker 5681919); the QQQ 13:30Z phantom
  (mark −0.65/+96 vs achievable −7.6/**−599**) scored divergence_frac **0.0604**
  `would_suppress=false` — the exact value CLAUDE.md says the 06-12 fix re-scores
  to ~0.91. `EXIT_MARK_SANITY_ENFORCE_ENABLED=1` deployed but never observed on a
  live fire. A phantom TP today should re-score ~0.91 → SUPPRESS (stops never).
- **Cohort-stop auto-cooldown FIRST FIRE** (`_write_cohort_stop_cooldown`, #1062) —
  on the next cohort-stop force-close; should write `reason=cohort_stop_force_close`
  (no manual bench needed).
- **Resting-TP exit-evaluator deferral** (`skipped_resting_tp_owns_profit_side`) —
  first QQQ-condor monitor tick today (resting TP placed post-close 06-13, no RTH
  monitor since).
- **#1058 `[EQUITY_STATE] realized-blind gap`** — 06-12 RTH logs aged out of Railway
  retention; re-check on today's session.
- **#1065 DEGRADED + raw-mode-reset lines** — fire once on the first CONVICTION read
  = first scan (16:00Z); no scan since the recycle.
- **#1059 synthetic-proof wiring** still unmerged (`9c957d9`); webhook still deferred.

### Data corrections (2026-06-12 night, operator-ordered; same precedent as 06-11)

- Shadow NFLX ×3 `1e2dd73f` (conservative): realized_pl **+314.70 → +133.35** at 18:00:58Z,
  BEFORE the 21:20Z learning ingest (learning_ingested was false — zero contamination).
  Basis: its OWN 15:15:04Z corroboration row — triggering mid 4.7355 vs achievable 4.131
  (P86 sell at bid 6.14 − P79 buy at ask 2.009) → (4.131 − 3.6865) × 300 = 133.35. The
  $181.35 delta was the optimistic-mid fiction; the code-side fix (internal fills at the
  EXECUTABLE side + fill_quality flag) ships tonight so this is the LAST manual instance
  of the class. Guarded UPDATE (realized_pl=314.70 AND learning_ingested=false) — idempotent
  against any concurrent session. paper_orders row 4d175584 left as-is (historical record of
  what the old fill simulation did; order_json carries no fill_quality — pre-fix row).

### Pending verifications added 2026-06-12 night

- Post-21:20Z TONIGHT: learning ingest consumed realized_pl **133.35** (not 314.70) for
  `1e2dd73f` — verify learning_trade_outcomes_v3 / learning_feedback_loops row.
- Morning signatures (06-13): (a) any TP fire writes a corroboration row with the
  price-normalized divergence; phantom → `exit_tp_suppressed_phantom_mark` alert + NO close
  staged (Stage-2 live). (b) exactly ONE broker submission per close (single-submitter,
  745ced4). (c) `[EQUITY_STATE]` successful broker daily fetch on the first monitor cycle —
  no "broker daily P&L unavailable" line (d68029c). (d) any internal/shadow fill carries
  order_json.fill_quality + the `[INTERNAL_FILL]` WARNING line. (e) the QQQ resting TP
  (buy-to-close GTC, limit 0.81) alive at the broker, untouched by the watchdog, visible to
  the evaluator as `skipped_resting_tp_owns_profit_side` if its TP condition trips.
- 15:30:08Z `paper_order_marked_needs_manual_review` alert: RESOLVED BENIGN — it was the
  second submission against the already-filled SPY close (intent-mismatch reject, the
  double-submit class); 745ced4's terminal-reject classification returns these gracefully
  without the manual-review mark. No operator action on the order itself (SPY close filled
  clean at 1.93, realized −45).

### Pending verifications added 2026-06-11 night

- 06-12 first credit fill row: avg_entry_price/max_credit POSITIVE (the #1056 write-side proof).
- 06-12 closes: positive limit on credit-position closes, no `Sign-incoherent` raise; the
  double-submission pattern persists (documented) until the 06-12 single-submitter fix.
- #1058 signature: `[EQUITY_STATE] realized-blind gap` WARNING whenever broker day < proxy.
- #1059 signature: `ops_*` rows appearing in risk_alerts (first ops delivery ever); synthetic
  proof row written + deleted post-deploy.
- ✅ #1048 VERIFIED 2026-06-11 19:00Z — first real cohort-stop fire: shadow QQQ 7-lot breached
  the neutral stop (−$235 vs −$213 threshold) and closed intraday at monitor cadence (the
  realized-P&L sign corruption it exposed is the #1056 internal-fill item above).
- ~~Railway auto-deploy MISSED bcbfb0c~~ **ERRATUM (06-12): it self-deployed ~10 min after
  merge** (SUCCESS 20:18:46Z) — the hook lags up to ~10 min after rapid merges and the
  listing API lags further; no forced recycle was required (the marker-var attempts errored
  client-side but one landed harmlessly, same SHA). The durable lesson stands: H8-verify the
  worker SHA before trusting behavior to a merge — but don't declare a deploy missing inside
  the lag window.

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

## status:reported — 2026-06-30 NIGHTLY run (report `audit/reports/2026-06-30.md`)

Window 06-15 → 06-30 (15-day gap; parked week 06-18→06-29 = zero trades; resume-armed tonight).
Infra movement: PRs #1094–#1098 merged + `PAPER_AUTOPILOT_ENABLED` 0→1 (first live-autopilot arm).
Both workers SUCCESS @ `f7dab1d`. Book FLAT (live + shadow). H11 zero critical.

- **[A4 2026-06-30 — FINDING] Learning-ingest silent in-result-error masking (P2→P1; refines the
  ledgered "OUTPUT_FRESHNESS watches ONE table").** `paper_learning_ingest` ran 5×/7d all
  `status=succeeded` while every run 06-23→06-29 carried `result.counts.errors=1,
  outcomes_created=0` (the `opened_at` 42703, fixed by #1098 tonight). EXPECTED_JOBS checks job
  STATUS; OUTPUT_FRESHNESS watches `calibration_adjustments` ONLY → a 6-day silent learning-loop
  death went unalerted. Parked week masked the P&L cost (zero closes); under live autopilot a
  recurrence silently starves calibration + loses real outcomes. FIX (additive, no infra): alert on
  `job_runs.result.counts.errors>0` (status-succeeded included) OR add `learning_feedback_loops` to
  the freshness registry → detection 6d→0d. RISK zero. CONFIDENCE high.
- A1/A6/A7 UNCHANGED (no new fills since 06-17). A2 — 4c fail-open CLOSED (#1094 live); multi-position
  / loss-precedence now live-relevant but backlog-P2 (don't fix ad hoc). A3 — relearn 5/8 post-epoch
  live, raw by #1076 design; ingest break lost ZERO outcomes (flat book that window); path-to-8 now
  depends on autopilot volume. A5 — this loop's only waste: `get_orders` 109k overflow (use
  symbols-filter/subagent next time); else within budget.
- **Four-source disagreement:** −84 NFLX 06-08 LIVE close → paper_positions cohort `3d289dca` (live)
  vs v3 `is_paper=true` (paper); ledgered is_paper P2, pre-epoch so relearn-count-safe but understates
  v3 live realized (−113 vs true −197). Reported not averaged.
- **A8:** lens KEPT (Negative-Decision Efficacy; no data-backed replacement tonight). Named next-run
  replacement **Entry-Fill Efficacy** (staged-live-order watchdog-cancel blind spot, 06-03 NFLX
  precedent) — adopt once autopilot generates staged-live data. See area8.md.

PENDING VERIFICATIONS (next session — first live-autopilot session):
- First 11:30 CT executor cycle on `PAPER_AUTOPILOT_ENABLED=1`: did it stage/fill or pass the EV gate?
- First post-fix `paper_learning_ingest` run (~21:20Z): `outcomes_created>0` on a close, `errors=0`,
  A4 cols (entry_iv_rv_spread/realized_vol_over_hold) populate.
- Entry-Fill Efficacy baseline: of any staged live order, fill vs watchdog-cancel + price vs limit.

## status:shipped — 2026-06-30 post-close runbook · Phase 1 (PR #1100 → main `8faf133`, both workers H8'd)

- **[Phase 1] alert-write resilience + A4 silent-failure detector** (squash `8faf133`; worker +
  worker-background SUCCESS @ 8faf133 21:55Z). (1a/1b) `observability/alerts.py` risk_alerts insert
  wrapped in retry-with-backoff (0.25/0.5s) on TRANSIENT stale-keepalive disconnects ONLY
  (`RemoteProtocolError`/"Server disconnected"); existing `alert_write_failed` log kept as the FINAL
  fallback; distinct `alert_lost_after_retries` marker when a transient exhausts retries. Right-sized
  retry, NOT a durable queue (signature = idle-keepalive drop). (1c) `ops_health_service.
  get_silent_job_failures` + `ops_health_check §3.5` fire a NEW `job_succeeded_with_errors` (high) via
  canonical `alert()` on any `status=succeeded` job with `result.counts.errors>0` (the masking class
  that hid the 6-day `opened_at` ingest death), fingerprint+cooldown, added to `_RISK_EGRESS_ALERT_TYPES`;
  `learning_feedback_loops` already in OUTPUT_FRESHNESS. Detection 6d→0d. 14 new tests + 27+5 regression
  green; ADDITIVE (ingest/executor/exit/monitor untouched). **SYNTHETIC PROOF PASSED:** inserted a
  `succeeded`/`errors=1` job_runs row → dispatched `ops_health_check` → `job_succeeded_with_errors`
  risk_alert fired end-to-end (run_id matched, 22:01:00Z) → both synthetic rows deleted.
  **Operator flag:** `OPS_ALERT_WEBHOOK_URL` unset → a fully-dropped insert reaches NO external
  destination; `alert_lost_after_retries` is the only in-process visibility. Closes the ledgered
  OUTPUT_FRESHNESS / N2-alert-delivery silent-failure gap (the WRITE side; the read-side egress poller
  remains deferred).

- **[Phase 2] entry executable round-trip cost gate** (PR #1101, squash `0ea6583`; worker +
  worker-background SUCCESS @ 0ea6583 22:35Z). Fixes the SOFI 06-30 own-goal class: admitted on EV
  +$30.63 but ~$135 of executable bid/ask cross made it underwater-on-executable from entry →
  force-closed at a 100%-spread-cost loss; the scanner's 5%-of-EV slippage PROXY
  (`canonical_ranker._estimate_slippage`) waved it through. NEW `exit_mark_corroboration.
  executable_roundtrip_cost` (PURE; reuses `compute_corroboration`'s executable basis long→bid/short→ask
  — UNIFIED with the exit, zero refetch; Σ per-leg (ask−bid)×contracts×100). NEW
  `paper_endpoints._apply_entry_roundtrip_gate` in `_stage_order_internal` (after #1038's validated
  `_entry_leg_quotes`, before TCM/insert/submit): `honest_ev_after_cost = ticket.EV − round_trip`,
  REJECT < `MIN_EDGE_AFTER_COSTS` ($15). OPEN-only (closes exempt), skips no-EV (shadow), allows on
  incomplete executable quote (#1038 owns dark legs), WARNING-logs every eval, stamps
  `blocked_reason='ev_below_roundtrip_cost'` (fail-soft), raises `EntryRoundtripCostExceedsEV`
  (#1038-shaped; autopilot counts not-executed). Flag `ENTRY_ROUNDTRIP_COST_GATE_ENABLED` default-ON
  (explicit falsy → legacy). 12 tests (incl. SOFI→REJECT, anti-over-reject PASS, UNIFICATION entry==exit
  basis, flag both ways) + 50+87 regression. ADDITIVE — executor/exit/monitor-force-close/ingest
  untouched (exit_mark_corroboration change = new sibling helper + import only). Resolves the SOFI
  own-goal at the ENTRY (NOT by loosening the stop). Verify on tomorrow's first scan.

- **[Phase 3 — status:DEFERRED 2026-06-30, GATED] Exit-trigger basis calibration (full-cross
  over-pessimism).** The −3% per-symbol envelope force-closes on the FULL-CROSS executable estimate
  (`exit_mark_corroboration.executable_close_estimate`/`compute_corroboration._executable_for`,
  long→bid/short→ask; SOFI `c99d8af2` 06-30: −$65 estimate vs −$40 achievable fill, INSIDE the −$62
  envelope). **WHY DEFERRED:** Phase 2 (#1101) closes the dominant class at ENTRY (SOFI can't be admitted
  now); the residual (a position admitted with tolerable round-trip whose quote later transiently
  widens/one-sides enough to trip the full-cross envelope while the achievable close is still in
  tolerance) is RARE with **N=1 data** — a tuned `k≈0.23` from one fill, on the one stop direction where
  a mistake MASKS real loss, is over-fit. **REOPEN:** ≥10–15 real close fills accumulated (via the
  precursor instrumentation, shipped below) → build on the fill-improvement DISTRIBUTION, not a hand-picked
  constant. **DESIGN (carry forward):** TWO-QUOTE CONFIRMATION — require BOTH the full-cross decision basis
  AND the achievable marketable-limit to breach before force-closing; floored at cross; ≤ mid; gated on
  `quote_complete`/non-wide; NO tuned constant. Survival fixtures: SOFI replays to ~−$40 (SURVIVES,
  −40 > −62) AND a −$200 directional loss STILL fires. **⚠ UNIFICATION TRAP (recon pt 4):** Phase 2's
  `executable_roundtrip_cost` recomputes (ask−bid) directly at `exit_mark_corroboration.py:408` while the
  exit reads `achievable_close` from `_executable_for:191-199` — a Phase 3 that changes ONLY the exit
  primitive makes ENTRY and EXIT diverge, re-creating the entry-admits-what-exit-kills bug this arc fixed.
  Phase 3 moves BOTH seams onto ONE per-leg executable price or it does not ship.

- **[Phase-3 PRECURSOR — SHIPPED 2026-06-30] Close-fill gap instrumentation.** PR #1102 → main `b3479a8`
  (off `0ea6583`). ADDITIVE / observe-only — makes the deferred Phase-3 decision data-driven instead of N=1.
  On EVERY close (force-close AND normal) emits `[CLOSE_FILL_GAP] symbol=… position_id=… cross=<full-cross
  executable estimate> mid=<trigger mark> fill=<marketable-limit fill> gap_fraction=(fill−cross)/(mid−cross)
  reason=…`; the quad is also persisted into the EXISTING close `order_json` JSONB (no migration → SQL-queryable
  for the REOPEN gate beyond short Railway log retention). New pure helper `services/close_fill_gap.py`; cross/mid
  threaded stage→fill via `order_json` (stamped in `paper_exit_evaluator._close_position` post-submit, read back
  at `alpaca_order_handler._close_position_on_fill` LIVE reconcile + the internal/shadow fill). Degenerate
  (mid==cross)→gap None; missing stamp→fill-only NA; every block best-effort try/except — NEVER affects a close.
  NO close-decision / envelope / trigger-basis / force-close / sizing change; no flag. 16 unit + 41 touched-path
  regression tests green (SOFI 06-30 fixture → 0.2326 ≈ 0.23). H8 ✅ both workers SUCCESS @ b3479a8
  (start 23:30Z, prior 0ea6583 REMOVED). First `[CLOSE_FILL_GAP]` line lands on the next live or shadow close.

## status:reported — 2026-07-01 NIGHTLY run (manual; report `audit/reports/2026-07-01.md`)

First session after the live-autopilot arc; verification-first. Both workers @ `b3479a8` all
day (no recycle). Broker flat, equity 2,093.74 (Δ −41.06 = SOFI −40 + fees). H11: 1 critical
= the shadow force-close below (functioning control, not an incident).

- **[A5 2026-07-01 — FINDING] Scanner persist seam unprotected against the stale-keepalive
  disconnect burst (now a 2-day pattern).** 16:00:09Z: 8× "Server disconnected" on
  suggestion_rejections inserts inside the scheduled scan (job result `persist_failures: 8`);
  same class + window as 06-30's storm. #1100's retry wraps ONLY `observability/alerts.py`
  alert() — scanner persists un-retried → 8 rejection rows lost today (observability data, no
  live-risk surface). FIX (additive): reuse the #1100 transient retry at the scanner persist
  seam (or pre-ping the connection before the post-scan write burst). RISK zero. CONF high.
- **[A4 2026-07-01 — REFINEMENT, changes action] Ghost-sweep shadow scoping P2→P1.** 58
  shadow-ghost warns in 2 days from ONE shadow position (51× 06-30 + 7× 07-01) vs ~73/wk
  baseline — the unscoped sweep (`alpaca_order_sync.py:245`) floods exactly when autopilot
  live flow makes a real desync time-critical. Additive scoping only.
- **[A4 2026-07-01 — instance, no new finding] First stranded critical:** 13:30:09Z critical
  `force_close` reached the DB and nothing else — `OPS_ALERT_WEBHOOK_URL` UNSET both workers,
  zero egress lines in logs. Operator owns setting it (+ `HEARTBEAT_PING_URL`, also unset).
- **[A7 2026-07-01 — note] `[CLOSE_FILL_GAP]` line emits at INFO** → invisible on the
  WARNING+/print worker (the [UTILIZATION_GATE] observability class). DB persistence (the
  durable channel) verified working on its first event. Cosmetic rider: bump to WARNING.
- **A8 lens SWAPPED:** Entry-Fill Efficacy ADOPTED (the SOFI staged-live lifecycle is the
  06-30-named trigger data); Negative-Decision Efficacy retired after 6 runs — parting
  datapoint: the conservative SOFI fork's REJECT (edge_below_minimum, EV 19.1) beat both
  accepting books (−40 live / −1,044.48 shadow). Its standing capture/marker recommendation
  stays in backlog RESEARCH, not withdrawn. `audit/area8.md` rewritten.
- Shadow SOFI force-close 07-01 13:30:09Z (−1,044.48; 17 lots; 21h overnight hold; open-
  rotation full-cross 0.84 vs mid 1.57, divergence 0.869): the **GATED Phase-3 class
  exercising** — cited, NOT re-found. All controls fired as designed (verifications below).
  Cohort-comparability caveat: the loss lands on neutral's policy-lab ledger at 26× the live
  twin (#1017 modeled-fill bias, now with a large concrete instance).

VERIFICATIONS CLOSED THIS RUN (the three 06-30 pendings + bonus — do not re-find):
- ✅ **First autopilot executor cycle**: 06-30 16:30Z staged + broker-filled SOFI live (fills
  broker-verified; entry at the 1.44 net limit, ~10s to fill); 07-01 both cycles clean with 0
  candidates (correct zero-entry day on honest scanner math, 382 rejections).
- ✅ **First post-fix paper_learning_ingest** (#1098): 06-30 21:20Z errors=0/created=1;
  07-01 21:20Z errors=0/created=1/dup-skipped=1 (position-level dedup ✓). Live SOFI v3 row
  **is_paper=FALSE**, pnl −40.0; **post-epoch live closes 5→6**. `entry_iv_rv_spread`
  populated (0.1166, first ever); `realized_vol_over_hold` NULL (hypothesis: hold too short —
  verify on a multi-day close before calling it a writer gap).
- ✅ **#1076 live-only calibration EMPIRICALLY confirmed**: 07-01 10:00Z escalation 30/60/90
  all sample_size=6 = exactly the live count (11 post-epoch outcomes exist, only 6 live seen)
  → insufficient_data → raw_mode_reset_written. Raw mode holds until 8.
- ✅ **#1073 Layer A first exercise**: 2 suggestions stamped `status='executed'` 06-30 at the
  position-insert seam.
- ✅ **#1062 first AUTOMATIC cohort-stop cooldown write**: (c8a3a3b0, SOFI) until 07-02
  13:30Z, reason=cohort_stop_force_close, realized_loss −1044.48. #1040's bench is now armed
  with a real row.
- ✅ **#1080 per-position triggers first live fire**: cohort stop evaluated on CORROBORATED
  UPL (obs row 13:30:05Z: mid 1.57/+26 vs achievable 0.84/−1,044.48, divergence 0.869,
  quote_complete=true, stop never suppressed); internal fill at executable w/ fill_quality
  (#1017); [INTERNAL_FILL] WARNING line present.
- ✅ **#1102 first event**: fill-side persist wrote `close_fill_gap_fill=0.84`, cross/mid/
  fraction NULL = the DOCUMENTED fill-only design for internal/shadow closes. Informative
  gap_fraction pends the first LIVE close.
- ✅ **Phase-B EXIT_EVAL_DEBUG honesty observed live**: printed the cohort threshold
  −494.496 (= 0.20 × 2,472.48 basis), not the flat default.
- ✅ **[CONVICTION] DEGRADED**: 0 lines today = CORRECT (v3 view live since #1076) — the
  once-per-recycle DEGRADED expectation is obsolete; do not re-expect it.

PENDING VERIFICATIONS (added 2026-07-01):
- First LIVE close post-#1102 → informative gap_fraction (broker fill vs cross) in
  order_json. The log line is INFO-invisible — query the DB, not Railway.
- First `ENTRY_ROUNDTRIP_COST_GATE` evaluation (next staged candidate): WARNING eval line +
  `blocked_reason='ev_below_roundtrip_cost'` on any reject; classify spread-eaten (correct)
  vs edge-lost (over-reject flag, operator-investigate only).
- 07-02 10:00Z relearn: sample stays live-only n=6 (the 07-01 shadow −1,044.48 is_paper=true
  must NOT appear in the count).
- `realized_vol_over_hold` on the next multi-day close — NULL on short holds is DESIGNED
  (`A4_MIN_HOLD_BARS=3` daily bars; the 15-min/21-h SOFI holds can't qualify); only a NULL on
  a ≥3-day hold would be a writer gap.
- 07-02 13:30Z SOFI cooldown expiry: if SOFI re-emits before expiry, FILTER + fail-closed
  STAGE gates must bench it (#1040's first full pre-ranking exercise).

## status:built — 2026-07-01 post-close · A5 scanner persist-seam retry (PR #1104, CI GREEN, MERGE PENDING operator)

- **[A5 07-01 fix] scanner rejection-persist transient-disconnect retry** — branch
  `fix/scanner-rejection-persist-retry` (tip `a955fc2`), PR #1104, CI green on run 3.
  The 16:00Z post-scan write burst lost 8 `suggestion_rejections` rows to stale-keepalive
  "Server disconnected" (2-day pattern; #1100 wrapped ONLY alerts.py).
  `RejectionStats._persist_rejection` now retries with backoff (0.25/0.5s) reusing #1100's
  classifier (`alerts._is_transient_disconnect`); ONLY transient disconnects retry — any other
  exception keeps the single-attempt fail-soft path byte-for-byte. Exhausted transient →
  DISTINCT `rejection_row_lost_after_retries` marker + unchanged fallback; recovered retry →
  NEW `persist_retry_recoveries` count in the scan job_runs.result (DB-queryable) + WARNING
  line. Backoff sleep is constructor-injected (`retry_sleep=`, default time.sleep test-pinned):
  CI runs 1+2 proved dotted-path @patch on options_scanner is order-fragile in the full suite
  (the MagicMock-shadowing class the suite itself documents at
  test_credit_spread_emission._read_anomaly_threshold). No flag (observability-only; clean path
  unchanged: one attempt, zero sleeps). ADDITIVE — scan decisions/aggregate counts/close paths
  untouched. 9 new tests + 97 touched-path regression local + full CI.
  **Rider (ledger-named 07-01):** `[CLOSE_FILL_GAP]` emits at WARNING (was INFO-invisible);
  level test-pinned.
- **Merge blocked by the session's self-approval gate (correct behavior):** the agent-authored
  PR merge auto-deploys both live workers; operator merges. AFTER merge: H8 both workers
  (deployment SUCCESS at the squash SHA, container start > merge time), then the pendings below.

PENDING VERIFICATIONS (added with #1104; valid only after operator merge + H8):
- Next 16:00Z scan disconnect burst: `persist_failures=0` + `persist_retry_recoveries>0` in the
  scan job_runs.result (retry absorbed it), or the distinct `rejection_row_lost_after_retries`
  marker if one outlives the backoff.
- First live close post-merge: [CLOSE_FILL_GAP] line now VISIBLE at WARNING in Railway logs —
  the "query the DB, not Railway" caveat on the earlier pending item becomes obsolete at this SHA.

## status:reported — 2026-07-02 NIGHTLY (v5.1 first run; report `audit/reports/2026-07-02.md`)

Quiet night: zero market activity since the 07-01 report; movement = #1104 (persist retry,
shipped) + #1105 (docs) merged 02:39/02:41Z, both workers SUCCESS @ `b6a28e1` (H8 clean,
mid-night recycle, no orphaned cycles). Broker flat, equity 2,093.74 == last_equity. H11: 1
critical = the ledgered 07-01 shadow force-close.

- **ONE-TIME CORRECTION (owner, v5.1 contract): the 2026-07-01 A8 swap to Entry-Fill Efficacy
  was ADOPTED IN ERROR and is REVERTED.** Negative-Decision Efficacy is RESTORED as the A8
  graduated standing area (audited every run; does not rotate). Entry-Fill Efficacy is
  RETIRED — not moved to A9; its spec is preserved in `audit/area8.md` under SUPERSEDED
  (move-don't-lose). Reason of record: A8 is the standing counterfactual area; single-run
  lens rotation is Area 9's mechanism. EFE's subject matter stays auditable under A1/A6/A7
  and may compete for the A9 slot on merits, with no incumbency.
- **[A9 2026-07-02 — FINDING, first audit of the new rotating lens "Alert & Signal
  Integrity"] `ops_data_stale` alert content lies about its trigger: 57/69 (83%) of 30d
  firings self-contradictory** ("Market data is stale … Stale: 0 … Reason: ok",
  `stale_symbols=[]`; one at age_seconds=54). Mechanism: `ops_health_check.py:117` ORs
  market_freshness | job_freshness, but message (:141-143) + details (:144-149) are built
  from market_freshness ONLY — every job-arm firing is mislabeled as market-data staleness;
  the correct `stale_reason` (:120-121) never enters the alert; fingerprint (:124-128) hashes
  the empty symbol list → all job-arm firings share one fingerprint. The job-arm predicate
  (30-min threshold vs 1×/day suggestions_open/close, `ops_health_service.py:198-227`) is the
  LEDGERED 2026-06-10 root cause — cited, not re-found; the mislabel wiring is the new
  surface. Realized cost: the 07-01 audit itself mislabeled the class ("chronic
  calibration-freshness artifact"). Projected cost: ~2-4 false highs/RTH-day egress to the
  ops webhook the day OPS_ALERT_WEBHOOK_URL is set → fix the wiring BEFORE/WITH webhook
  arming (order-coupled with the standing TOP-3 #1). FIX (additive): message from
  stale_reason + `trigger_source` + job_freshness fields in details + per-arm fingerprint; no
  predicate/threshold change (that is the separate ledgered item). RISK zero (content-only).
  CONF high. Spec: `audit/area9.md` (fresh adoption, no graduation proposed).
- A1/A2/A6/A7 UNCHANGED (zero fills/scans/closes in window). A3 counter re-verified 6/8 live
  post-epoch (30d: live n=6 −153; paper n=9, 5 post-epoch, −1,870.80). A5 loop self-audit:
  11 SQL (3 wasted on column-name misses — introspect information_schema FIRST), 3 broker, 0
  subagents; prior-session H8/H11 pulls reused. Q9 note: scanner persist-failure key is
  `result.counts.rejection_persist_failures` (options_scanner.py:311) — use it for the #1104
  verification query.

PENDING VERIFICATIONS (2026-07-02 session, in addition to the standing 07-01 list):
- 10:00Z relearn: sample_size=6 live-only (shadow −1,044.48 is_paper=true excluded).
- 13:30Z SOFI cooldown expiry: FILTER + fail-closed STAGE gates bench a pre-expiry re-emit.
- 16:00Z scan: #1104 first live test — `counts.rejection_persist_failures=0` (+
  `persist_retry_recoveries>0` if a disconnect burst occurs); [CLOSE_FILL_GAP] now
  WARNING-visible on any close.
- Scheduled 00:23 CT nightly (v5 prompt) collides with report file `2026-07-02.md` — operator
  to skip or accept overwrite (this run covers the window).

## status:shipped — 2026-07-02 post-close · A9 data_stale content fix (PR #1106 → main `91b1319`, both workers H8 SUCCESS 03:20:55Z)

- **[A9 fix, item 1 of tonight 3] data_stale alert content from the firing arm** — squash
  `91b1319`. NEW pure helper `ops_health_check.build_data_stale_alert_content(market, job)`:
  message/details/fingerprint from the arm(s) that FIRED. Job-arm → names the stale source +
  age vs threshold + true reason (trigger_source="job", job_* detail keys); market-arm →
  EXACT legacy message AND legacy fingerprint shape (cooldown history survives the deploy);
  both → both named, " | "-joined. Job-arm fingerprints hash {job_source, job_reason, arms}
  instead of the empty market symbol list (per-arm dedup buckets). PREDICATE UNTOUCHED
  (test-pinned) — the 30-min-vs-daily-cadence job-arm threshold stays the separately-ledgered
  2026-06-10 item (own PR later, per operator 1c). Regression fixture pins the verbatim 07-01
  production shape: "Market data is stale ... Stale: 0 (). Reason: ok" can never emit again.
  12 new tests + 57 touched-path regression + CI green first try. One-time cooldown reset for
  job-arm firings only. Sequencing honored: shipped BEFORE webhook arming.

PENDING VERIFICATION: next RTH inter-scan gap (e.g. ~14:07Z or ~15:07Z ops_health_check) →
the ops_data_stale row (if the job arm fires) must read "Job-based data freshness is stale.
Source: job_runs. Age: ~N min ..." with trigger_source="job" and NO market-data language.

## status:armed — 2026-07-02 post-close · egress webhook LIVE (item 2 of tonight 3, operator action)

- **`OPS_ALERT_WEBHOOK_URL` SET on BOTH workers ~03:35Z** (operator; names-only hygiene —
  value never in transcript). Var-change recycle: worker + worker-background BOTH SUCCESS
  03:35:44Z, SHA unchanged `91b1319` → running processes carry it. Code reads confirmed:
  `ops_health_service.py:670/:1188` + `observability/alerts.py` (#1096/#1100 senders).
  Sequencing honored: #1106 content fix deployed BEFORE arming (no cry-wolf channel).
  Standing TOP-3 #1 (3 consecutive reports) is CLOSED pending first-egress proof.
- **⚠ `HEARTBEAT_PING_URL` SET but INERT — NO READER EXISTS.** Grep 07-02: zero code
  references (`jobs/handlers/heartbeat.py` is only the internal scheduler job_runs
  heartbeat; no PING_URL/healthchecks reader anywhere). The external dead-man's switch
  (durable-oversight Window 1, P2 half) was NEVER BUILT — only the A4 detector half shipped
  (#1100). The var is correct env-first pre-staging, but **monitoring-by-absence is NOT
  active**; a dead scheduler still alerts nobody externally. DOC≠BUILT instance — do not
  count the switch as armed until its PR ships and pings are observed at the provider.

PENDING VERIFICATION (egress arm): first egress-eligible alert (critical, or the ~14:07Z
ops_data_stale job-arm firing if allowlisted) must produce a webhook send — check for the
sender's egress log line on the worker AND delivery at the operator's channel; a stranded
critical with the var set = new finding (delivery-path bug, not config).

## status:shipped — 2026-07-02 post-close · ghost-sweep live scoping (item 3 of tonight 3; PR #1107 → main `6898bf9`)

- **[07-01/07-02 TOP-3 #3] ghost_position sweep scoped to live-routed portfolios** — squash
  `6898bf9`. Recon first (PR was gated on it): ALL 58 warns 06-30→07-01 traced to ONE
  position — the neutral-cohort shadow SOFI (`08002beb`, `routing_mode=shadow_only`), firing
  every 5-min sync from open+15min to seconds before its 13:30Z force-close. Sweep correct
  per code, spurious per intent (a shadow never exists at the broker). Fix: sweep portfolio
  set through #1014 canonical `position_scope.live_routed_portfolio_ids`, BOTH halves (ghost
  legs + stale needs_manual_review). **Fail-OPEN polarity, test-pinned**: scope-query failure
  → legacy unscoped sweep + warning (noisy beats blind — a detector must never silently
  narrow). Deliberately NO dedup on the ghost half: a real live ghost keeps nagging at full
  cadence (H10 urgency preserved). Dedup/rate-limit evaluated and REJECTED (would mute real
  desyncs). 7 new tests (`test_ghost_sweep_live_scope.py`, verbatim 08002beb fixture) + 21
  existing green; CI green. Closes the ledgered P2→P1 noise item; §8 seam note ("sweep does
  not exclude shadows") is FIXED at this SHA — CLAUDE.md edit deferred to the next doctrine
  pass.

PENDING VERIFICATION (ghost scoping): next session with an open SHADOW position → zero
ghost_position warns from it across sync cycles (the 08002beb class); any LIVE position
ghost must still alert. H8 VERIFIED 03:44Z: worker + worker-background BOTH SUCCESS @
`6898bf9` (deploys 4b9fd393/4401e0ba), zero error-level lines post-start.

## status:shipped — 2026-07-02 post-close run #2 (operator-directed A1–A5 + B1–B3 recons)

Three builds merged sequentially (one PR / one recycle / H8 each), three read-only recons,
backlog rewritten. All H8s: both workers SUCCESS at the squash SHA, container start > merge,
zero error-level lines post-start.

- **[A1 #1109 `97bace3` 04:09:58Z] dead-man's-switch ping** — heartbeat.run() fires one
  best-effort GET at `HEARTBEAT_PING_URL` (timeout 5s, try/except → single WARNING logging
  the exception CLASS only — the URL embeds the check token, never logged). Unset/empty →
  silent no-op. Pin: run() result byte-identical across success/timeout/unset — a
  healthchecks outage can NEVER fail the heartbeat job. **HEARTBEAT ARMED, end-of-chain
  semantics**: silent check = one of APScheduler→BE→RQ→worker died; diagnose job_runs vs
  Railway. RTH-only trade-off accepted (schedule */30, hours 8–17 CT). Env var pre-staged +
  read back 03:35Z; no var mutation since — recycled containers carry it.
- **[A2 #1110 `716ba2a` 04:15:23Z] typed strategy/regime on trade_closed outcomes** —
  the builder carried both only in details_json while the TYPED columns (the ones
  post_trade_learning._build_segment_key reads) were never written → segment learning
  silently no-oped (83/98 rows NULL; the 06-29 "0/13" was the narrower window). Values were
  available-but-unmapped (the metadata SELECT already pulls strategy+regime). No linked
  suggestion → NULL, never fabricated (H9). Every close from this deploy forward carries
  segments. 82 of 83 legacy NULL rows backfillable from linked suggestions → supervised-
  mutation queue (NOT executed).
- **[A3 #1111 `7bc9927` 04:25:51Z] direct-insert alert egress relay (P1 Window-2)** —
  13 sites insert risk_alerts without alert() (incl. the monitor's force_close): with the
  webhook armed they still egressed NOWHERE. relay_direct_insert_alerts polls post-epoch
  critical/high rows and relays via the SAME Channel-2 sender (client=None, no duplicate
  row), marks metadata.egressed_at/egress_owner=relay. Boundaries: ops_* Channel-1 rows
  excluded; alert() pre-stamps egress_owner=alert on its #1096 allowlist. Epoch
  `ALERT_RELAY_EPOCH` = 2026-07-02T00:00Z (#1051 pattern; 0 post-epoch rows at build —
  the 1,040-row backlog can never fire). Best-effort: unmarked-on-failure → retry next
  poll; 3-consecutive-failure circuit; cap 10/poll. Piggybacked as fail-isolated step 0 of
  ops_health_check (effective cadence HOURLY at :07 — the :37 fire is deduped by the hourly
  idempotency key; contradiction filed P1). **Egress now covers alert() AND direct-insert
  paths.**
- **[A4 EXECUTED 07-02 ~04:45Z, operator-approved in-session]** hygiene sweep: bulk-acked
  exactly **1,040** pre-epoch un-acked critical/high (385 c / 655 h; warn×580,
  force_close×356, ops_data_stale×69 dominate) via one UPDATE setting resolved=true +
  resolved_at + jsonb marker `bulk_ack='hygiene_sweep_2026-07-02'`, cutoff = relay epoch
  07-02 00:00Z (move-don't-lose; both production readers key on recent created_at windows —
  behavior-safe). Post-sweep verification: the ONLY remaining un-acked critical/high row is
  the synthetic relay-e2e row `4d0afb05` (by design, deleted after the 13:07Z proof). H11
  baselines are clean from tonight forward: un-acked critical/high now means LIVE actionable.
- **[A5 #1112] docs/backlog.md rewritten** from ledger + recon verdicts; GATED carries the
  executor-cadence trigger verbatim (NOT MET); #71 guard tokens retained (29 guard tests
  green). Final recycle of the night.
- **[B1 recon — MTM mark-write corroboration → PROMOTED P1]** persisted raw marks are
  DECISION-FEEDING on slow paths: policy-lab champion HARD_DRAWDOWN_LIMIT auto-rollback
  (evaluator.py:605-621 via max_drawdown), go-live checkpoints, autopilot-breaker +
  _marginal_ev fallbacks, close-limit seam (mitigated #1072/#1017). Fast loss paths clean
  (#1071/#1075/#1079/#1080). 14d evidence: 2/3 closes wrong-signed at last persist; SOFI
  persisted +196.52 30min before the corroborated −1,044.48 close. Fix = reuse
  exit_mark_corroboration.executable_close_estimate at BOTH write sites
  (paper_mark_to_market_service.py:206-217 + intraday_risk_monitor.py:780-790, snapshots
  already fetched — zero extra API calls), ADDITIVE fields only. Side-finding: monitor
  Part-B persist doesn't stamp last_marked_at.
- **[B2 recon — migration drift]** the 2-file paper-shadow cluster is the only genuinely
  unapplied pair → GATED apply-as-unit pre-enable (INERT confirmed, doubly so). Tracking:
  27/112 by name (82 pre-era, 1 procedure miss `20260426000000` applied-untracked, 2 gated).
  Process fix (P2): name-normalized drift check vs a checked-in allowlist in the nightly
  audit.
- **[B3 recon — data_stale predicate retune table ready]** union arm: max healthy in-gate
  age 187 min over 10/10 trading days → `OPS_DATA_STALE_MINUTES=360` kills 39/39 job-arm
  false HIGHs (78% of all data_stale HIGHs); market-hours gate suffices for the union arm
  (no new weekend guard). Daily job_late arm (NOT market-hours-gated) needs the
  _rth_job_status warm-up-anchor generalized — 40 Monday warns → 0. Contradictions filed:
  ops_health_check hourly-vs-q30 dedup; suggestions_open 15 runs/10d untraced extras.

PENDING VERIFICATIONS (added 2026-07-02 post-close run #2):
- **Heartbeat first ping** at the 08:00 CT slot (13:00Z) — provider dashboard shows it;
  then the operator handoff (un-pause, cron */30 8-16 * * 1-5 America/Chicago, Grace 45,
  after-hours Grace-to-1-min email test to prove the last hop, restore).
- **Relay synthetic e2e** at the 08:07 CT poll (13:07Z): risk_alerts row
  `4d0afb05-3c9a-4c10-ac40-39f55e292ffb` (relay_synthetic_e2e, critical, 04:26:42Z,
  clearly-labeled SYNTHETIC) must egress to the operator inbox;
  job_runs.result.alert_relay.sent=1 + metadata stamped egress_owner=relay. THEN clean up:
  `DELETE FROM risk_alerts WHERE id='4d0afb05-3c9a-4c10-ac40-39f55e292ffb';`
  A stranded synthetic with the webhook set = delivery-path bug (new finding).
- **First typed segment row**: next trade_closed ingest (21:20Z) carries non-NULL
  strategy+regime; post_trade_learning segment keys build without the suggestion-join
  fallback.
- Standing 07-01/07-02 list unchanged (10:00Z relearn live-only n=6 · 13:30Z SOFI cooldown
  expiry · 16:00Z scan #1104 first live test · #1101 first roundtrip-gate evaluation ·
  first LIVE close post-#1102 gap_fraction).

## status:shipped — 2026-07-02 pre-market build session (P1-A/B/C + approved backfills)

Operator-directed session (~09:00–09:30Z, market closed; all merges pre-08:00 CT job spin-up).
Three sequential builds, each CI-green → squash → BOTH workers (+BE for P1-A) H8 SUCCESS at the
squash SHA, container start > merge. Owner decision of record: ops_health_check cadence intent =
**(a) q30min REAL**.

- **[P1-A #1114 `e133063` 09:02:33Z] q30min-real idempotency bucket** — the hour-granular key
  (`public_tasks.py`) deduped the :37 fire against :07 every hour (99/100 observed runs at :07);
  effective cadence was HOURLY, silently halving the health check AND the A3 relay poll. Key now
  buckets by half-hour via pure `_ops_health_idempotency_key`; same-half-hour retries still dedup;
  `-synthetic` suffix composes unchanged. **Relay SLA restated: a direct-insert critical/high
  reaches the inbox within ~37min worst case** (insert just after :07 → :37 poll + send), vs ~67min
  before. BE verified at the SHA too (the endpoint lives there). VERIFY: two ops_health_check
  job_runs per hour from 13:07/13:37Z today.
- **[P1-B #1115 `0b85de6` 09:12:09Z] data_stale predicate retune** — PREDICATE ONLY (#1106 content
  pins green): `OPS_DATA_STALE_MINUTES` default 30→360 (wiring unchanged: code default + env
  override; if the env name is explicitly set on Railway it shadows — operator names-only check);
  daily `job_late` age is now WEEKEND-EXCLUDED (`_weekend_excluded_age` — Fri-evening→Mon-morning
  reads ~16h ok; a genuinely missed Monday reads ~40h late by Tuesday; flat ~74h raise rejected as
  it would delay Tue–Fri detection). Fixture update ledgered: the watchdog daily pin re-anchored on
  a Thursday (its old 30h window crossed Sunday — reads ~17h effective under the deliberate new
  semantics; the 26h-absent-weekend intent preserved). **VERIFICATION CONTRACT: next RTH day
  job-arm false HIGHs 39→0; next Monday job_late storm 20→0; a real dead daily job still alerts
  same-day (367min > 360 at the 19:07Z check).** The alert channel's last known noise source dies
  here.
- **[P1-C #1116 `b18052d` 09:25:52Z] MTM mark-WRITE corroboration (B1 promote)** — both durable-
  mark write sites (`refresh_marks` + monitor Part-B) now persist
  {mark_corroborated, unrealized_pl_corroborated, mark_quality} ALONGSIDE the raw mid (raw
  byte-identical — the load-bearing pin held; the exit evaluator's close-limit read is
  source-pinned to raw). Design call (owner-delegated): ADDITIVE, not replace — replacing
  current_mark would leak into the LIVE close-limit path, and #1072 already restages live closes
  at achievable. Zero extra API calls (cycle-cached snapshots); dark/incomplete → NULLs +
  uncorroborated stamp (H9). Governance now prefers corroborated: policy-lab cohort unrealized
  (max_drawdown → utility + HARD_DRAWDOWN_LIMIT champion auto-rollback) + go-live checkpoint sums;
  breaker/_marginal_ev FALLBACK branches deliberately untouched. OUTPUT_FRESHNESS now watches
  paper_positions.last_marked_at (168h; flat-book caveat) + generic query NULLS LAST fix.
  Migration `20260702100000` applied pre-merge via canonical apply_migration (tracked).
  **BEFORE-BASELINE (do not re-find): 14d = 2/3 closes wrong-signed at last persist; SOFI 07-01
  raw +196.52 persisted 30min before the corroborated −1,044.48 close (divergence 0.869).**
  Pinned: the SOFI fixture now reads −1,044.48 into cohort scoring. Residual (filed, not built):
  Part-B still doesn't stamp last_marked_at; eod snapshots don't carry corroborated fields.
  VERIFY: first RTH mark cycle writes non-NULL corroborated fields on any open position;
  policy_daily_scores unrealized reflects the corroborated basis at the next eval.
- **[Backfills EXECUTED ~09:35Z, operator-approved in-session after fidelity gates]**
  (a) 82-row typed strategy/regime from linked suggestions (10/10 sample fidelity; exactly 82;
  the 1 non-qualifying row stays NULL as pre-fix legacy; no updated_at trigger — v3 close-time
  COALESCE untouched). (b) 33-row funnel dismissed→executed (10/10 sample had real closed
  positions; exactly 33 = the ledgered 32 + 1 accrued; the trade_suggestions integrity trigger
  guards lineage fields only — status explicitly allowed). Historical segment learning and funnel
  stats are now truthful end-to-end.
- **GATED confirmations (encoded, nothing touched):** executor cadence NOT MET (raw 6/8, #1072
  unexercised) · clamp/winsorize await the 8th live close · Phase-3 exits await ≥10–15 fills ·
  paper-shadow migration pair only at the executor-flag flip (RLS at apply). Operator handoff
  outstanding: healthchecks un-pause + cron */30 8-16 * * 1-5 America/Chicago + Grace 45 +
  after-hours Grace-to-1-min email test.

PENDING VERIFICATIONS (added this session): two health-check runs/hour from 13:07Z · job-arm
false-HIGH count = 0 over today's RTH · Monday 07-06 job_late storm = 0 · first mark cycle
writes corroborated fields · next policy_lab_eval scores on the corroborated basis.

## status:shipped — 2026-07-02 gap-report build session (external-reference audit, operator-approved set)

Operator ran a reference-repo gap analysis (NoFx / flashalpha / TradingAgents / ai-hedge-fund
patterns); approved set built in order. Both builds CI-green → squash → both workers H8.

- **[Gap-4 recon — DOC≠BUILT FINDING: the greeks exposure envelope is DOUBLE-dormant]** —
  DB-verified: across 60d (18 positions) NO leg jsonb has ever carried a `greeks` key and
  paper_positions has no greeks column → `check_greeks` (risk_envelope.py:229) has summed
  ZEROS since inception; AND all four caps default 0 = no-limit. §5's "greeks warn" listing
  is a known-liar until fixed (CLAUDE.md edit deferred to the next doctrine pass, #1107
  precedent). Answers the archived #115b narrowed question on the persisted side. NOT
  silently populated (operator-directed); follow-up filed: populate greeks on legs at stage
  time (stage validation already fetches snapshots that carry them), caps decision after
  inputs are real.
- **[Gap-2 #1118 `49f3ba9` 10:02:34Z] rolling signal-accuracy telemetry (OBSERVE-ONLY)** —
  view `signal_accuracy_rolling` (migration 20260702110000, applied+tracked pre-merge):
  live-only last-20 hit-rate + Brier per scope; ops_health section 3.7 fail-isolated;
  `signal_accuracy_degraded` WARNING at n≥8 AND hit_rate<0.2 (env-tunable). Modulates
  nothing. **FIRST BASELINE (do not re-derive): overall 1/6 wins (16.7%), Brier 0.2751;
  IRON_CONDOR 0/2, LONG_CALL_DEBIT_SPREAD 0/3, LONG_PUT_DEBIT_SPREAD 1/1.** n=6<8 → below
  the alert sample gate today.
- **[Gap-1 #1119 `c0268ce` 10:15:31Z] consecutive-loss streak breaker (NoFx pattern)** —
  N consecutive live losses → `ops_control.entries_paused=true` + critical alert
  (streak_breaker_tripped/_error added to the #1096 egress allowlist). N=3 env-config
  (`STREAK_BREAKER_N`); `STREAK_BREAKER_ENABLED` default-ON tightening polarity; FAIL-CLOSED
  the strong way (evaluation error → PAUSED, never check-skipped — deliberately opposite the
  fail-open READ gate, which consumes a halt this evaluator sets); recovery operator-only
  (no code path writes false — source-pinned); idempotent vs existing pauses. Tail step of
  paper_learning_ingest → job_runs.result.streak_breaker. **Pre-merge bug caught
  (verify-before-asserting): a typed `symbol` select would have 42703'd (no such column —
  #1098 class) and, under fail-closed, paused entries EVERY run; symbol now read from
  details_json, select list source-pinned.** ⚠ **KNOWN TRIP, operator-acknowledged: the live
  stream already holds 5 consecutive losses (SOFI −40 · MARA −15 · QQQ −73 · MARA −28 ·
  SPY −45) — the FIRST evaluation (tonight 21:20Z ingest) trips: entries pause + critical
  alert = free live end-to-end exercise. Operator decision of record: ship, let it trip,
  then un-pause (`UPDATE ops_control SET entries_paused=false, entries_pause_reason=NULL
  WHERE key='global'`). A 21:20Z trip is EXPECTED, not an incident.**
- **[Gap-3 recon + spec — NO build]** `docs/specs/shadow_fill_realism.md`. Recon: live fill
  rate ≈1/3 (17 filled / ~54 orders; 10 watchdog-cancelled unfilled — the NFLX class ≈1 in
  5) vs shadow 100%-by-construction; same-period twin magnitudes 3–45× (size-driven, 5–17
  lots vs 1); only 3 shadow closes carry fill_quality=executable (rest predate #1017);
  cohort twin pairing is (symbol, cycle), NEVER suggestion_id. Recommendation: interim
  option (a) per-contract promotion-time normalization + measured fill-discount (one PR)
  BEFORE the next promotion eval; full post-and-wait model (b) in its own recon-first
  session. Owner decision pending on (a).

PENDING VERIFICATIONS (gap session): 21:20Z tonight — `job_runs.result.streak_breaker.tripped=true`
+ entries_paused=true + streak_breaker_tripped critical in the inbox (egress) → operator
un-pauses per decision of record · signal_accuracy view visible in tonight's ops_health
snapshots · no alert from signal accuracy until n≥8.

## status:verified — 2026-07-02 post-close wrap (~23:30–23:50Z): the breaker exercise + doc sync

- **[#1119 FIRST TRIP — VERIFIED END-TO-END, planned, NOT an incident]** 21:20Z ingest:
  errors=0, outcomes_created=0 (flat day; typed-segment FORWARD proof defers to the next real
  close — the 82 backfilled rows stand). `result.streak_breaker`: enabled/evaluated/tripped/
  paused_written ALL true; window = SOFI −40 · MARA −15 · QQQ −73 verbatim. Chain: ops_control
  entries_paused=true + streak reason verbatim → `streak_breaker_tripped` critical 21:20:03Z,
  `metadata.egress_owner='alert'` (immediate-egress path; relay can never double-send) → zero
  `streak_breaker_error` rows → worker log `[STREAK_BREAKER] TRIPPED` 21:20:09Z. Egress nuance:
  the webhook POST attempt is proven and NO failure logged (failures log at WARNING and would
  show); the success line is INFO (not retained) → final receipt = operator inbox (confirm ④).
  Design note answered by the exercise: the breaker evaluates the TRAILING stream on EVERY
  ingest run (it fired with outcomes_created=0) — no fires-only-on-new-outcomes gap.
- **[RECOVERY EXECUTED ~23:35Z, operator-approved in the wrap]** un-pause UPDATE run;
  read-back `false / NULL`. Entry-seam read: `paper_autopilot_service.py:187-196`
  (`are_entries_paused()` → falls through to the staleness gate when false). Staging proof =
  tomorrow's 16:30Z cycle (PENDING). Breaker critical ACKed (exercise complete).
- **[CLEANUP]** synthetic relay row `4d0afb05` DELETED (post-inbox-window); post-sweep H11:
  **un-acked critical/high = 0 — genuinely zero for the first time on record.**
- **[DOC SYNC]** CLAUDE.md registry #1043→#1119 synced (v3-exists correction, 8th-close
  convergence rule, relay route/SLA, close-limit-reads-RAW pin, breaker un-pause procedure
  VALIDATED, §5 greeks layer marked dormant, §7 v5.1 A8-standing/A9-rotating, §8 liars
  rewritten: greeks double-dormant + shadow-ledger fiction added; EXIT_EVAL_DEBUG/ghost-sweep/
  is_paper/funnel moved to RESOLVED-cite-only; no-symbol-column trap; §9 + entries_paused
  operator-only + introspect-before-select). backlog: P1 tier → gap-3(a) normalization +
  tradeable-universe recon; shipped set retired; supervised-mutation queue closed; new P2s
  (greeks populate-at-stage, breaker-N revisit at n≥15, mark-write residuals). ~38.4k chars.
- **Process note (self-caught):** a PowerShell one-liner clobbered docs/backlog.md mid-edit
  (PS 5.1 kept executing after a Substring exception → Set-Content $null). Recovered via
  `git checkout --`; only an uncommitted edit was lost and redone via the Edit tool. Lesson:
  no destructive shell one-liners on tracked docs — Edit tool only.

OPERATOR-CONFIRM — **ALL FOUR CONFIRMED with evidence (operator, 07-03 session)**:
① healthchecks FULLY ARMED — check un-paused; receive-side 20 pings, every :00/:30 from 08:00
  CT (source = the worker; "new → up" at the first ping, per #1109's prediction); cron
  `*/30 8-16 * * 1-5` America/Chicago, Grace 45; Grace-to-1-min DOWN-email test DELIVERED
  18:45 CT, Grace restored. Residual: check reads DOWN overnight post-test — EXPECTED; the
  08:00 CT ping tomorrow auto-flips UP (the UP email = free second confirmation, pended).
② relay synthetic email DELIVERED 08:07 CT (full payload incl. risk_alert_id 4d0afb05) — the
  A3 relay's last hop proven.
③ OPS_DATA_STALE_MINUTES CONFIRMED UNSET (dashboard names-only) — the 07-02 zero-false-HIGH
  result is attributable to #1115's code default, not an env shadow. Behavioral pass = real.
④ breaker critical email DELIVERED 16:20 CT (full window payload, paused_written=true,
  already_paused=false) — the immediate-egress path proven on a REAL safety event.
**With ①–④ the oversight chain is proven at every last hop** (doctrine-synced: CLAUDE.md §4
"Oversight chain" entry). Breaker semantics operator-confirmed from the ④ payload:
TRAILING-window evaluation on EVERY ingest run — trips can occur on zero-close days (the
07-02 window spanned closes 06-15→06-30); the stronger design, now doctrine. Recovery
mutations from the wrap RE-VERIFIED holding at confirm time (entries_paused false/NULL ·
breaker alert ACKed · synthetic gone · H11 = 0).

PARKED (operator's call, no action): rotate the hc-ping UUID (appeared in screenshots) —
healthchecks regenerate + one env update + recycle, whenever chosen.

PENDING (tomorrow): 08:00 CT heartbeat UP email (test residual clears) · 16:30Z post-un-pause
staging proof (final recovery link) · first typed-segment forward row + breaker re-evaluation
at the next real close's ingest (NOTE: the 3 most-recent live closes are all losses, so the
NEXT losing live close re-trips the breaker BY DESIGN — a win resets) · first [CLOSE_FILL_GAP]
live gap_fraction · gap-3(a) build + tradeable-universe recon = next build window.

## status:shipped — 2026-07-03 build window (~00:45–01:15Z): gap-3(a) + tradeable-universe recon

- **DEADLINE (Step 0):** the champion-vs-shadow comparison runs inside `policy_lab_eval`
  (scheduler 16:30 CT daily; `check_promotion` at policy_lab/evaluator.py:282); gap-3(a)
  landed ~15h before the next eval. (`promotion_check` 17:00 CT is phase-transition hygiene,
  not the comparison.)
- **[Gap-3(a) #1124 `48ddcd4` 01:10:59Z] shadow-ledger promotion-time normalization** — NEW
  `policy_lab/promotion_normalization.py`, called ONLY from check_promotion after the daily-
  scores fetch (governance-only, import-pinned): per-contract division on BOTH sides (daily
  contract-exposure attribution, floors at 1, never fabricates) + the MEASURED fill-discount
  on challenger/shadow rows only — `SHADOW_FILL_DISCOUNT` default **0.31 = 17/55 live fills
  re-measured at build time** (spec said 0.33; fresh count used per instruction; RE-DERIVE
  from live fill data as volume grows, never hand-tune). Ledger rows and percent fields
  untouched (rollback semantics preserved); position-fetch failure degrades divisors to 1.0
  with a WARNING. Flag `SHADOW_PROMOTION_NORMALIZATION_ENABLED` default-ON (measurement-basis
  correction, #1052 class). SOFI twin fixture pinned: live −40 → −40.00 byte-identical;
  shadow −1,044.48@17 → **−19.05** expected contribution. 18 tests + 27 touched-path.
  **BEFORE-STATE: promotion evals compared a real ~31%-fill book to a 100%-fill fiction at
  3–45× magnitudes.** H8: both workers SUCCESS @ 48ddcd4 (01:11Z deploys). VERIFY: next
  16:30 CT policy_lab_eval runs the normalized comparison (job green; no verdict flip
  expected at current n).
- **[Tradeable-universe recon — READ-ONLY, owner-decision input, NO changes]** headline:
  **1 of 84 CLEARS the round-trip gate on strict post-epoch evidence (SPY, net ≈ +$16–23 on
  a single candidacy); 5 MARGINAL (QQQ, NFLX, TSLA, IWM, SLV); ~77 STRUCTURALLY-CANNOT.**
  Structure: honest per-contract EV density is $7–45/ct; sub-$60 underlyings size to 4–21
  contracts so per-ct EV collapses to single digits vs $21+/ct minimum round-trip (the
  SOFI/TLT class — TLT has the tightest spread in the universe, $12/ct, and still cannot);
  expensive single names carry $60–1,500/ct crossings. Only penny-increment index-class
  chains get under ~$40/ct. No real-quote row in 1,436 rejections ever printed below $21/ct.
  Within-universe insight: TSLA/IWM already CLEAR the spread (~$13–14/ct) but die upstream
  on EV — if regime ever hands them positive EV they clear where SOFI never can (HYPOTHESIS
  until a post-epoch candidacy). Outside-universe candidates (HYPOTHESIS): GDX/KRE/XBI/EFA
  penny-program ETFs — but the TLT lesson says tight spread is insufficient without a
  contract-count cap in the sizer. Detail note: the gate's DB stamp reads round_trip=88.00
  (4 cts, $22/ct) vs the 16:30Z log line's 92.00 — same verdict either way; likely quote
  drift between eval and stamp passes (minor, watch on the next rejection).
- **Universe-reshape question FRAMED FOR OWNER (no action):** the small-tier universe is
  structurally spread-eaten — options: (a) accept low frequency (learning-mode consistent;
  gate is doing its job), (b) bias scanner ranking toward the 6 CLEARS/MARGINAL names,
  (c) add penny-program ETFs + a sizer contract-cap, (d) nothing until EV density grows with
  equity. Recon is the decision input; no default assumed.

PENDING VERIFICATION (gap-3(a)): 07-03 21:30Z policy_lab_eval green on the normalized basis.
Gap-3(b) post-and-wait fill model remains its own recon-first session (NOT started).

## status:shipped — 2026-07-03 (July-4th-observed HOLIDAY, market closed all day) · decision (b)+(c)

Owner decision on the universe question: (b) ranking bias BUILT + (c1/c2) recons DELIVERED +
refill screen DELIVERED + contract-cap CLOSED. Broker clock verified is_open=false, next open
07-06 — all merges today are closed-market compliant.

- **[Part 1 #1126 `d42d435` 13:38:37Z] universe-viability candidacy bias — SHIPS DARK** —
  sort-key-only multiplier in rank_suggestions_canonical toward the recon-viable set (SPY 1.30 ·
  QQQ/TSLA/IWM/SLV 1.15 · NFLX 1.10 marginal-provisional, pre-epoch-EV hypothesis in-code).
  Never a filter, never a mutation: stored risk_adjusted_ev byte-identical (the allocator's
  split skew reads it), below-floor stays −999, the stage-seam roundtrip gate reads untouched
  ev; positive scores only (boosting a negative would invert intent). Flag
  `UNIVERSE_VIABILITY_BIAS_ENABLED` strict '=1' (behavioral; non-'1' warns once). **ARMING IS
  AN OPERATOR ENV ACTION (not armed).** 10 tests; H8 both workers @ d42d435.
- **[Merge-timing note — false alarm, retracted with evidence]** the CI watch→merge chain
  slept ~7h and merged at 13:38Z "8 minutes into RTH" — flagged as a §2 violation, then
  RETRACTED against the broker clock (July-4th-observed holiday, is_open=false; the morning
  ops_data_stale market-arm firings are the documented holiday pattern; the recycle swallowed
  nothing — 13:40:01Z order_sync tick green). LESSON KEPT: watch→merge automation must
  clock-check (broker calendar, not weekday) before merging — until a guard exists, don't
  leave merge chains unattended near session boundaries.
- **[Part 2A/2B refill screen — READ-ONLY, owner-decision input; all quotes = off-hours
  holiday snapshot, indicative]** **ADD LIST: EMPTY — zero candidates pass f1–f5.** Best new
  name (CVX $52/ct) exceeds the $40 ceiling off-hours; every sizing-trap NO (BITO $10/ct but
  15 lots · GDX A-grade OI but 9 lots · EFA/KRE/XLRE/FXE) is ROBUST to the off-hours caveat —
  spread compression cannot fix per-ct EV collapse. Conditional shortlist for an RTH
  re-screen: **MRK + CVX** (OI grade A, 2–3-lot sizing, need <~$25–40/ct at RTH — 40–60%
  compression on A-grade names is plausible, HYPOTHESIS). **In-universe verdict FLIPS: DIA
  measured $28/ct (SPY-class-adjacent — amend the 07-03 'structurally cannot' class) and GLD
  viable ONLY on $5-multiple strikes** (its $1-strikes are OI-dead). PRUNE candidates
  (owner-gated; cost is scan/API only): strong = SNAP·NIO·MARA·F·LYFT·AAL·RIVN·SOFI (all
  sub-$20, structurally dead per the sizing trap; ⚠ SOFI = the only name that ever live-filled
  — owner judgment); second tier = T·CMCSA·PFE·KHC·DKNG·WBD·CCL·FXI·KMI·EWZ. CAUTIONS:
  (i) iv_rank warm-up — a fresh add is scanner-invisible ~60 trading days
  (`iv_rank_insufficient_history`, options_scanner.py:3032-3040); **SEEDING EXISTS**:
  `iv_historical_backfill` accepts payload {symbols, days} (handler :94-100, background
  queue, idempotent upsert) — pair any add PR with a one-shot seed; thin-contract history may
  stay sparse; unseeded bulk adds push the iv_pipeline_no_data alert threshold.
  (ii) CORRELATION — {SPY, DIA, QQQ, IWM} = one US-equity-beta trade in four wrappers; the
  envelope doesn't know DIA≈SPY; treat as one bucket in any add/prune decision; the
  diversifying conditionals are MRK (pharma) / CVX (energy, but XOM/XLE overlap) / GLD.
- **[Part 3 — sizer contract-cap CLOSED, evidence-based]** the roundtrip gate's verdict is
  contract-count-INVARIANT (both sides scale with n; per-ct terms decide: ev_ct<cost_ct → no
  n clears; ev_ct>cost_ct → MORE contracts help clear the $15 floor — a cap can only flip
  passes into fails). The hypothesized crowd-out mechanism is allocator-slot ORDER, which
  Part 1 addresses. No cap, item closed; slot re-flow-after-reject noted as a possible future
  recon ONLY if a cycle ever demonstrably loses a viable candidate to a doomed higher-ranked
  one.

PENDING (holiday-shifted): market closed 07-03 → post-un-pause staging proof, typed-segment
forward row, [CLOSE_FILL_GAP], and the breaker's next real evaluation all move to MONDAY
07-06. Today's 21:30Z policy_lab_eval still fires (scheduler is holiday-blind) → verify green
on the normalized basis (no verdict flip expected at current n). Heartbeat pings run 8–17 CT
today regardless → the UP email residual clears today. OWNER DECISIONS OPEN: arm
UNIVERSE_VIABILITY_BIAS_ENABLED=1 (env, no deploy) · RTH re-screen of MRK/CVX (next trading
session, read-only) · prune list · DIA/GLD class amendment.

## status:armed — 2026-07-03 ~15:18Z (holiday window) · decision-execution T-phase

- **[T1 — BIAS ARMED]** `UNIVERSE_VIABILITY_BIAS_ENABLED=1` set on BOTH workers; var-change
  recycles SUCCESS @ `a958fb4` 15:18:27/29Z — running containers created post-set carry =1.
  EXPECTATION CORRECTED vs the instruction: a correct `=1` emits NO log line by design (§3
  strict-parse warns ONLY on a non-'1' value) — silence + behavior is the signature.
  Names-only hygiene forbids a value dump read-back; the behavioral read-back is Monday's
  pin: **07-06 16:00Z scan → sort-key reorder visible in ranking, stored risk_adjusted_ev
  byte-identical (the dark-ship pin, now live).**
- **[T2 — baseline captured; closes at 21:30Z tonight]** 07-02 21:30Z eval (pre-#1124):
  `no_promotion`, challengers die at GATE 2 (`insufficient_trades`: conservative 0, neutral 1
  vs required 10) — the utility comparison NEVER RAN at current volume. Tonight's normalized
  first-eval evidence is therefore: job green + flag-default-ON path executed + same
  insufficient_trades verdict; **the SOFI-twin magnitude proof only becomes observable when a
  challenger reaches Gate 4 (≥10 trades + ≥MIN_TRADING_DAYS)** — do not mistake verdict-
  sameness for the normalization not running.
- **[T3 — OPERATOR-CONFIRM open]** heartbeat pings fired 8:00 CT today (scheduler mon–fri,
  holiday-blind) → the check should have flipped UP at the first ping; confirm the UP email
  arrived (closes the Grace-test residual).
- **[T4 — FILED]** broker-clock guard on watch→merge automation → backlog P2 (merge chains
  check `get_clock.is_open`, fail-safe to NOT-merge; no unattended chains near boundaries
  until built).
- CLOSED/DO-NOT-REOPEN (recorded): contract-cap (count-invariant algebra) · slot re-flow
  (future recon only on a demonstrated lost-viable-candidate cycle) · the empty add-list
  verdict STANDS — no refill re-run without new evidence (tier change or structural change).
- MONDAY QUEUE (own sessions): M1 MRK/CVX RTH re-screen (read-only, mid-session batch) ·
  M2 GLD $5-strike feasibility recon (config-vs-surgery verdict) · M3 standing proofs ·
  M4 post-close universe PR (prune strong tier MINUS SOFI — **SOFI stays as the canonical
  gate sentinel**: if it ever CLEARS the roundtrip gate, the spread regime, EV math, or a bug
  changed and we want to see it loudly; DIA → bias tier 1.15 with the one-beta-bucket note;
  GLD/MRK/CVX per M1/M2 verdicts; adds pair with iv_historical_backfill seeding).

## status:reported — 2026-07-03 v5.3 FULL (weekend deep-dive; report `audit/reports/2026-07-03-FULL.md`)

Budgets: 16/20 SQL · 2/6 broker · 4/12 subagents · 24 files fully read. Broker flat,
SHA `e0bbe6e` everywhere, H11 = 4 (all today's holiday data_stale highs). READ-ONLY held.

- **A9 GRADUATION RECORDED (owner decision 2026-07-03, first exercise of the rule):**
  Alert & Signal Integrity is STANDING/PERMANENT (founding finding shipped #1106+#1115,
  measured 39→0). `audit/area9.md` header frozen as the standing contract. The rotating
  slot moved to A10, adopted this run: **Calendar & Clock Integrity** (`audit/area10.md`
  — five time-boundary instances in 72h; first-run NEW finding: the winter-close blind
  hour, 20:00–21:00Z EST-season staleness+watchdog gap, fix before November).
- **TOP-3 #1 — #1126 viability bias is BUILT-NOT-WIRED (HIGH; double-confirmed):**
  `rank_suggestions_canonical` has ZERO production callers; the executor orders
  candidates via its own local sort (`paper_autopilot_service.py:118-131`). This
  morning's armed flag is INERT; Monday's "bias live" pin is VOID until wired. The
  shipped tests pinned the orphan function — the `9a2cef1` class, self-inflicted
  same-day, caught by PASS-2. Fix = one call site + an executor-path wiring test,
  item 0 of Monday's M4 window. Env stays set (correct once wired).
- **TOP-3 #2 — A9 alert-taxonomy cluster (9 findings, 4 MEDIUM):** `force_close` is a
  costume worn by three realities (31% of rows describe NO close — submitted/FAILED/
  warn-only share one critical type; post-epoch all three relay under one phone title);
  `alert_type="warn"` carries zero semantics (706 rows/30d); severity vocabulary
  fragmented — `medium`+`warn` are the two largest warning-class buckets, invisible to
  canonical `severity='warning'` readers (**misses 83%**); the designed client=None
  egress logs a "legacy mode" misconfiguration WARNING on every relayed row. One
  post-close taxonomy PR fixes the channel before the next live force-close egresses.
- **TOP-3 #3 — one-beta-bucket uncontrolled (A2, MEDIUM):** {SPY,DIA,QQQ,IWM} has NO
  block-level control — `max_correlation_cluster_pct` is declared-never-read (config
  fiction), ranker correlation is same-symbol-only, sector check warn-only with ETFs in
  an accidental shared bucket; the bias (once wired) steers INTO this. Additive control
  candidate, owner-gated.
- Other MEDIUMs: `check_rollback` mis-restores after a "recommended" promotions row +
  cooldown consumed by recommendations (latent until promotions move; cheap fix) ·
  promotion utility is structurally single-factor (tail/slippage/concentration inputs
  never written; drawdown penalty unit-mismatched ≈ ≤$0.40) · stuck-`running` job_runs
  have NO reaper (mid-run recycle orphans permanently; learning chain overlaps the merge
  window) · §4 kill-switch coupling: unsetting ENTRY_QUOTE_VALIDATION_ENABLED silently
  disables the #1101 roundtrip gate · GTC pilot-list UNSET = all-eligible (not
  pilot-off).
- Notables: suggestions_open extras RESOLVED benign (operator --force CLI, 5 of 15) ·
  cooldown-vs-cadence NOT doubled by #1114 (hourly by a 2-second phase margin — thin) ·
  SLV structurally benched until ~Sept (iv warmup; viable-tier aspirational) ·
  resting-TP pilot no longer resting (book flat; unexercised) · A8 reconstructability:
  spread-class 100% quotes/no OCC identity, EV-class 0% legs, spot-at-decision 0%
  everywhere · A7 proposed MERGED into A1/A3 until ≥10–15 live fills · scorecard + full
  owner-decision list (10 items) in the report.

PENDING VERIFICATIONS (unchanged + one added): tonight 21:30Z normalized-basis eval
(baseline captured; expect green + insufficient_trades) · Monday M-queue **with M4
item 0 = the F1 wiring fix** · heartbeat UP email (operator ③④-class confirm).

## status:plan-encoded — 2026-07-03 post-deep-dive EXECUTION PLAN (owner decisions, verbatim runbook)

Owner encoded the week 07-03 evening. THE RUNBOOK for Mon/Tue sessions — recover from here.

- **DOCTRINE ADDITION (staged for M4's doc rider, not yet in CLAUDE.md):** "Tests for a
  flag-gated behavior must pin the PRODUCTION CALL PATH, not the function in isolation —
  an orphan function with green tests is the 9a2cef1/#1126 class." (F1 detection latency
  <24h via PASS-2 vs 2 months for 9a2cef1.)
- **MON RTH (read-only):** M1 MRK/CVX re-screen (f1–f5; hypothesis: $52–70/ct compresses
  <$40/ct) · M2 GLD $5-strike config-vs-surgery verdict (no build) · M3 proofs WITH
  CORRECTION: **"bias live at 16:00Z" pin STRUCK VOID (F1)** — replaced by: 16:30Z
  post-un-pause staging proof · typed-segment forward row / first live [CLOSE_FILL_GAP] /
  breaker re-eval IF a close lands (trailing 3 losses — next losing close re-trips BY
  DESIGN).
- **MON POST-CLOSE — M4, ONE PR (item 0 governs):**
  M4.0 F1 wiring fix — `_viability_rank_key` into `get_executable_suggestions`' sort
  (paper_autopilot_service.py:118-131), flag-gated (env stays armed). THE test: viable
  outranks equal-score non-viable IN get_executable_suggestions' OUTPUT; flag-off
  byte-identical THERE. Orphan-function tests stay but don't count as wiring proof;
  rank_suggestions_canonical fate noted-not-deleted.
  M4.1 universe per M1/M2: prune SNAP·NIO·MARA·F·LYFT·AAL·RIVN (SOFI = permanent
  sentinel, code comment + rationale); DIA → tier 1.15 + one-beta note; GLD per M2;
  MRK/CVX per M1 (+ iv seeding if added).
  M4.2 doc riders: §4 corrections (ENTRY_QUOTE_VALIDATION↔#1101 kill-switch coupling;
  GTC pilot-list unset=all-eligible) · §8 additions (A9-F6 legacy-mode WARNING, A9-F7
  severity fragmentation 83%, A9-F8 one-convention detector; EXIT_EVAL_DEBUG entry
  STAYS) · breaker runbook line ("un-pause without a new WIN re-trips on zero new
  closes") · the doctrine addition above · backlog: F-A1a P2 w/ HARD TRIGGER "ship
  before any challenger reaches 8 trades"; reaper P2-ELEVATED (this week's spare slot);
  winter-close → check Tuesday PR carry else CALENDAR TRIGGER 2026-10-01; F-A2b/F-A2c
  P2 tail (batch w/ reaper if trivial).
  Tests: pruned absent · SOFI present + still gate-rejecting (sentinel pin) ·
  executor-path bias green · flag-off byte-identical. New pin on merge: **bias verified
  ON THE EXECUTOR PATH at Tuesday's 16:00Z scan.**
- **TUE POST-CLOSE — ALERT-TAXONOMY PR (approved):** split force_close →
  force_close / force_close_failed / envelope_violation_warn_only · real types for
  alert_type="warn" · normalize medium/warn severities (extend enforcement beyond
  alert() or map at write) · honest channel2-only wording for the designed client=None
  egress. CONSTRAINTS: relay/egress allowlists updated SAME PR (renamed types must not
  drop off the phone path — pin per-type egress tests) · historical rows untouched
  (readers map old types) · fingerprint continuity noted (fresh cooldown history
  acceptable, say so). Ledger line: "the phone channel stops lying."
- **NEXT SLOT — ONE-BETA BUCKET (recon-then-build):** B1 recon: PREFERRED shape =
  implement the dead `max_correlation_cluster_pct` knob as a real block-level envelope
  check with an ETF bucket map ({SPY,DIA,QQQ,IWM}=us_equity_beta), from_env loads it,
  confirm stage-time sees would-be book; FALLBACK ranker bucket factor. STOP after
  recon. B2 build: additive-only BLOCK, default-ON safety polarity, tests (2 same-bucket
  at cap → 3rd BLOCKED stamped; cross-bucket unaffected; flag-off legacy). Must land
  before the book routinely holds 2+ positions.
- Also rides any PR: OUTPUT_FRESHNESS `suggestion_rejections` @120h one-liner
  (no-weekend-exclusion caveat noted).
- **A7 MERGE + A1/A6 REFRAMES approved** — prompt v5.4 is owner-enacted after M4, not a
  session task. Retirement counters: all standing areas at 0.
- Gap-3(b): untouched, own recon-first session.
- STILL PENDING TONIGHT: 21:30Z policy_lab_eval normalized-basis close (baseline:
  no_promotion / insufficient_trades 0-and-1 vs 10; expect same verdict, job green).

## status:reported — 2026-07-04 NIGHTLY (report `audit/reports/2026-07-04.md`)

Quiet window (07-03 holiday close-of-day → Saturday): zero scans/fills/failures; both
workers SUCCESS @ `3689210` (two doc-only merges post-FULL-report, H8 clean, no recycle
since 17:43Z → env unchanged since the 15:18Z bias arming). Broker FLAT, equity =
last_equity = $2,093.74. Budgets: 14 SQL · 2 broker · 0 subagents. **NO NEW FINDINGS.**

- **⚠ OPERATOR PRECONDITION FOR MONDAY (M3): `entries_paused=TRUE` right now.** The
  breaker RE-TRIPPED 07-03 21:20:04Z on ZERO new closes (trailing-3 verbatim SOFI −40 ·
  MARA −15 · QQQ −73; paused_written=true; critical egressed `egress_owner='alert'`).
  **F-A2e LIVE-CONFIRMED <24h after being reported** — the trailing-window-every-ingest
  reading is production truth; the 07-02 PENDING wording ("next losing close re-trips")
  was the weaker reading. Un-pause any time before Mon 16:30Z buys the full session
  (breaker only evaluates at the 21:20Z ingest tail, mon–fri); expect a re-trip EVERY
  ingest night until a live WIN lands. Recovery stays operator-only (§9).
- ✅ **T2/gap-3(a) verification CLOSED**: 07-03 21:30Z policy_lab_eval GREEN on the
  normalized basis — `no_promotion`, Gate-2 insufficient_trades (conservative 0, neutral 1
  vs 10), exactly the encoded baseline. SOFI-twin magnitude proof still pends a Gate-4
  challenger. Side observation (filed under ledgered F-A1b, cited-not-refound): neutral
  eval row `capital_deployed 1876.2 / positions_opened 0` — window-artifact HYPOTHESIS;
  Gate 2 halts before utility consumes it.
- **A9-F5 rate EXACTLY confirmed**: 7 ops_data_stale highs on 07-03 (4 + 3 at
  17:37/18:37/19:37Z, halting at the 20:00Z gate) vs the "at most one" docstring. Feeds
  the Tuesday taxonomy PR context; no new finding.
- **#1114 re-verified**: 12 ops_health_check runs in 6h = 2/hour. **A3**: ingest dedup
  held (closed_positions_found=2 → duplicates skipped 2, outcomes_created=0); live
  post-epoch stays 6/8, raw mode holds. **Cooldowns**: zero active (SOFI expired
  unexercised). **A8 full protocol**: zero new negative-decision population; 30d ratio
  ≈5,603:15 (≈373:1); roundtrip-reject class still N=1; capture d8_v1 unchanged; NEW
  observation — policy_lab `decision_accuracy.rejection_accuracy` (n=7, informational) is
  the lens's first in-system consumer at cohort grain; per-gate efficacy still unmeasured.
  **A10**: no new instance (holiday patterns exercised as spec'd); retirement counter 0→1.
- Heartbeat UP-email confirm still operator-side; weekend cron silence = no false DOWN
  expected before Mon 08:00 CT.

PENDING VERIFICATIONS (2026-07-04 consolidation — the Monday list, gated on the un-pause):
- **Operator un-pause + ACK the 21:20:04Z breaker critical BEFORE Mon 16:30Z** (else the
  staging proof and all downstream M3 proofs silently no-op again).
- Mon 07-06: 16:30Z staging proof · typed-segment forward row · first live
  [CLOSE_FILL_GAP] gap_fraction · breaker re-eval at 21:20Z (zero-close day → re-trip
  EXPECTED) · #1115 job_late Monday storm = 0 · M1 MRK/CVX RTH re-screen · M2 GLD recon ·
  M4 PR (item 0 = F1 wiring fix; new pin: bias verified ON THE EXECUTOR PATH at Tuesday's
  16:00Z scan).

## status:reported — 2026-07-06 NIGHTLY (Monday 00:00 CT scheduled run, pre-RTH; report `audit/reports/2026-07-06.md`)

Dead-quiet window (07-04 report → 07-06 05:01Z): the ONLY job_run was `phase2_precheck`
07-06 05:00:02Z green; zero fills/orders/scans/suggestions/rejections/alerts (any
severity); zero cooldowns; both workers SUCCESS @ `3689210` = origin/main (no deploys or
recycles since 07-03 17:43Z → env unchanged since the 15:18Z bias arming, by
construction). Broker FLAT, equity = last_equity = OBP = $2,093.74. Budgets: 9 SQL ·
4 broker · 2 Railway · 0 subagents. **NO NEW PRODUCTION FINDINGS.**

- **⚠ OPERATOR PRECONDITION STILL OPEN at run time (05:01Z): `entries_paused=TRUE`**
  (unchanged since the 07-03 21:20:04Z re-trip; reason verbatim SOFI −40 · MARA −15 ·
  QQQ −73). Un-acked critical/high = 8, all 07-03 (1 breaker critical `c598eec4` + 7
  holiday `ops_data_stale` highs). This report is the LAST audit checkpoint before the
  Mon 16:30Z window — un-pause + ACK first thing.
- **AUDIT-LOOP OBSERVATION (local tooling, not production): the Sunday 07-05 FULL run
  never started** — `audit/cron.log` has no start marker between Sat 07-04 00:01 (exit
  0) and Mon 07-06 00:00:02 (this run); Task Scheduler didn't fire (machine off/asleep
  HYPOTHESIS). Realized cost $0 (weekend retroactively verified silent); class = the
  watcher has no watcher. Fix (operator-side, additive): Task Scheduler "run after
  missed start" + "wake to run" on `\nightly-audit`; optional #1109-symmetric
  healthchecks ping on report write. Same log shows 3 historical start-without-end
  markers (06-14, 06-20, 06-30).
- **A3 window-slide note (not new data):** paper 30d reads n=8 / −2,062.80 (was 9 /
  −1,870.80) — writer ran 0× in window; one early-June positive paper row aged out of
  the sliding 30d window. Live unchanged: n=6 / −153.00 all post-epoch; raw mode holds
  at 6/8.
- **A5 lesson:** 2 of 9 SQL wasted on 42703s (`job_runs.job_type`→`job_name`,
  `reentry_cooldowns.expires_at`→`cooldown_until`) — the introspect-first rule applies
  to EVERY table not queried this session, not just learning tables.
- A8 full protocol: zero new negative-decision population; 30d ratio ≈5,255:14 ≈375:1
  (both sides sliding); roundtrip-reject class N=1 all-time; counterfactuals correctly
  empty (market closed). A9: zero new alert rows → nothing to measure; Tuesday taxonomy
  PR stands. A10: no new instance; retirement counter 1→2.

PENDING VERIFICATIONS (2026-07-06 — the Monday list, unchanged + one added):
- Standing Monday list above (un-pause gate · staging proof · typed-segment ·
  [CLOSE_FILL_GAP] · 21:20Z breaker re-eval · #1115 job_late storm=0 [checkable at
  Tuesday's nightly] · M1/M2/M4).
- NEW: operator decision on the missed Sunday FULL — wait for 07-12 vs one mid-week
  FULL after M4 + taxonomy land (NIGHTLY tonight was contract-correct; the FULL cadence
  slipped silently).

---

## 2026-07-06 POST-CLOSE — M4 SHIPPED + ERRATUM + INVERTED-UNIVERSE MARKER

- **⚠ INVERTED-UNIVERSE MARKER (07-06 16:00Z scan — EXCLUDE from gate evidence):**
  Alpaca nulled the retired PDT daytrade fields (weekend 07-04) → `int(None)`
  TypeError in `alpaca_client.get_account()` serializer → OBP read died → $500
  `paper_baseline_capital` fallback → `get_tier(500)`=micro → $60 underlying cap →
  56 `micro_tier_underlying_too_high` rejections → zero candidates at 16:30Z
  executor. Today's zero is the INCIDENT's zero, not the gates' — classified (c),
  excluded from honest-economics and gate-behavior baselines (like the 07-03
  holiday). Scan budget observed deployable=500/cap=450 vs healthy 2093.74/837.50.
- **ERRATUM (process, 07-06 ~19:10–19:25Z):** a compaction-summary date phantom
  ("Tue 07-07") + stale context header (07-01) made a 4-minute-old job_runs row
  (19:05Z) read as a 23h scheduler outage; reported to the operator as a system-wide
  incident with a fabricated-by-arithmetic healthcheck-email claim. Operator
  authorized a BE restart on that false report: redeploy `1b3e7dcd`, same SHA
  `3689210`, swap 19:24:25Z, ZERO missed ticks (19:25:01Z order_sync dispatched by
  the new container, succeeded end-to-end). No incident existed — 143 jobs green
  that day. Same class as the 06-11 deploy-lag erratum + 07-03 holiday false alarm.
  **Fix shipped: STEP 0 clock grounding** (DB `now()` + broker `get_clock` BEFORE
  any time arithmetic; clocks beat headers/summaries/stated time) — operator
  directive, now CLAUDE.md §1 first corollary + session memory.
- **M1 verdict (MRK/CVX RTH re-screen, closed 07-06):** MRK = NO ($41–46/ct
  round-trip crossing on every pair sampled RTH). CVX = MARGINAL-ADD ($25–29/ct on
  healthy-OI 170/175 strikes; the $19 headline pair was a dead-OI mirage) → CVX
  added with iv-seeding (60d) + viability tier 1.15.
- **M2 verdict (GLD strike modulus, closed 07-06):** built as one-line-config at
  the `_split_chain_to_calls_puts` seam — `SCANNER_STRIKE_MODULUS` env (default
  "GLD:5"), subset-or-fallback (never filters to empty). OI-floor generalization
  filed as follow-up (backlog).
- **M4 SHIPPED (this squash):** item 0.1 serializer null-tolerance
  (`_req_float` fail-loud-by-name on required fields; retired daytrade fields
  null→placeholder) · item 0.2 fail-CLOSED capital (live-mode OBP-None → critical
  `account_unreadable_entries_blocked` + deployable 0.0 → CapitalScanPolicy blocks
  the cycle; $500 baseline survives ONLY explicit paper mode; unreadable ops mode
  = live) · item 0.3 pin tests (12 new-file + the CONTRACT-CHANGE rewrite pair in
  test_capital_basis_consistency replacing
  `test_falls_back_to_paper_baseline_on_alpaca_failure`) · item 0b **#1126 bias
  WIRED into the production path** (`get_executable_suggestions` sort at
  paper_autopilot_service.py; sort-key-only, positive scores only, flag-off
  byte-identical; EXECUTOR-PATH wiring test per the new §9 never-do) · item 0.4
  OBP-failure alert wording (consequence now truthful) · M2 modulus · tiers
  +DIA/CVX/GLD 1.15 · OUTPUT_FRESHNESS + suggestion_rejections/120h · CLAUDE.md
  riders (STEP 0 corollary · #1038/#1101 kill-switch coupling · GTC pilot
  unset=ALL correction · #1119 runbook line · §8 A9 additions · §9 two never-dos)
  · backlog riders (F-A1a trigger, reaper P2-elevated, winter-close 2026-10-01
  calendar trigger, OI-floor).
- **Post-merge DB mutations (operator-approved, executed tonight):**
  scanner_universe deactivate SNAP/NIO/MARA/F/LYFT/AAL/RIVN (SOFI stays —
  permanent roundtrip-gate sentinel) + add CVX; `iv_historical_backfill` enqueued
  {symbols:["CVX"], days:60}.

PENDING VERIFICATIONS (2026-07-07, added by the M4 ship):
- **Post-fix live proof (first healthy scan):** scan budget deployable≈2093.74 /
  cap≈837.50, tier=small, ZERO `micro_tier_underlying_too_high` rejections.
- **Bias first live cycle:** executor log shows viability-biased ordering (flag
  armed since 07-03); flag-off comparison not required — wiring test pins it.
- **GLD modulus first scan:** GLD rejections collapse to $5-strike population only.
- **CVX:** IV-integrity-ELIGIBLE as of 07-06 20:28Z — days:90 top-up
  (job f5f7b8be, 111s) after the days:60 seed (a06c143d): 84 distinct
  non-null iv_30d days (2026-03-02→06-30), 0 dup (underlying,as_of_date),
  idempotency held (skipped_existing=55/ok=29/failed=0). Gate rule cited:
  iv_repository.py:26 MIN_IV_HISTORY_DAYS=60; :224-249 sample COUNT of
  non-null iv_30d rows (≤252 recent) — contiguity irrelevant; scanner
  rejection seam options_scanner.py:3060-3067. PIN (16:00Z scan, 11:00 CT):
  CVX in the scanned set, iv_rank computed (sample_size 84+), NO
  iv_rank_insufficient_history rejection for CVX; if it candidates, first
  roundtrip-gate evaluation with verbatim numbers (expect MARGINAL vs $15).
- **21:20Z breaker re-eval (tonight):** expected RE-TRIP (no live win 07-06) —
  critical + email is DESIGNED (runbook); un-pause remains operator-only.

2026-07-06 POSTCLOSE AUDIT (v5.4 first run, operator-invoked; report
`audit/reports/2026-07-06-postclose.md`) — status:reported:
- **A9 FINDING — egress delivery-receipt gap**: `_maybe_egress_risk_alert`
  discards send_ops_alert_v2's result (alerts.py:85-95); success logs at
  invisible info (ops_health_service.py:1379); `egressed_at` never stamped
  by inline sends — safety-trip delivery disputes close on inference, not
  fact (tonight's breaker-email triage = 4 evidence hops). FIX (additive):
  capture insert id → post-send metadata UPDATE {webhook_sent, egressed_at,
  suppressed_reason} + warning-visible receipt log both outcomes. RIDES THE
  TAXONOMY PR (same files, one recycle).
- Pins P1–P5 all PENDING → converge on 07-07 16:00–16:30Z + first close.
- Free-look: broker 0 open orders / 0 positions on flat book (no orphaned
  GTC); fossils unchanged (22 queued / 4 stuck-running).
- Counters: A9→0, others →3 (A7 dormant). No retirement candidates.

## 2026-07-09 EOD — BUILD #1143 SHIPPED (shadow-detection + calibration fail-loud) + ⭐ OPTION-B CLOCK-RESET MARKER

**#1143 `655c9aa` — MERGED + H8 VERIFIED.** Post-close (merge 22:54:19Z;
STEP-0 grounded: broker 18:45 ET market-closed, DB 22:45Z). Two fail-safe
fixes:
- **Shadow-detection value match (E2 residue):** `_is_shadow_routing()`
  (`paper_endpoints.py`) now whitelists the REAL production value
  `shadow_only`. The prior check matched `paper_shadow`, which production never
  emits → the #1141 Option-A shadow branch was INERT (all cohorts fell to the
  observe-only legacy-sized basis, `basis=legacy_sized`). Unknown/None routing
  → False → observe-only (fail-safe: an unknown value never flips a live
  decision). Live path still behind `GATE_QTY_FIX_LIVE_ENABLED` default-OFF.
- **Calibration fail-loud:** once-per-scan WARNING at the midday apply site
  (`workflow_orchestrator.py`) + a write-side WARNING when a blob is stored
  while apply is disabled (`calibration_update.py`) + an import-time-flag
  caveat comment (`calibration_service.py`). Logs only; the flag itself was
  re-enabled by env flip earlier this session (a Railway flip needs a recycle
  — exactly what the import-time comment documents).
- **H8:** BE `d1fe9f87` / worker `74f3c83d` / worker-background `dad9b9e0` —
  all SUCCESS at `655c9aa`, created 22:54:22–23Z > merge 22:54:19Z; prior
  `907d4cd` deploys REMOVED. No new flags → no read-back beyond confirming
  `GATE_QTY_FIX_LIVE_ENABLED` OFF + `CALIBRATION_ENABLED=1` (both unchanged).
- **Tests:** `test_shadow_routing_fix.py` (13) pin `_is_shadow_routing` on the
  exact production strings + the routing→gate-decision chain (shadow PASS /
  live REJECT+observe / unknown observe-only / qty=1 invariant) + the two
  fail-loud source sites. CI green (run 29055518433, 1m42s).

**⭐ OPTION-B CLOCK-RESET MARKER — STAMPED AT `655c9aa` (recycle 22:54:22–23Z).**
Both preconditions are now met ON THE RUNNING PROCESS: (1) calibration APPLYING
(`CALIBRATION_ENABLED=1`, re-enabled this session) and (2) shadow-detection
CORRECT (`shadow_only` matched). **The Option-B (live gate-qty apply) observe
window's evidence clock RESETS here: the 9 `[GATE_QTY_SCALED_SHADOW]` observe
lines logged before this recycle are DISCARDED** — they were counted on the
inert-shadow + inert-calibration basis and are not clean. **Clean observe
evidence counts only from the first scan after this recycle (07-10 16:00Z scan
onward).** `GATE_QTY_FIX_LIVE_ENABLED` stays OFF — Option B remains an operator
decision, now to be made on clean data.

**B4 — EXTERNAL-REVIEWER SCORECARD (so future sessions weight their input
correctly):** external Q1 (calibration computes/stores but returns ×1.0 =
a runtime-flag/mapping issue) **CONFIRMED-RIGHT-FOR-THE-RIGHT-REASON** by
internal recon — root cause was `CALIBRATION_ENABLED='0'`, stale since the
06-11 epoch, never restored. Their A7 ("stops saved money") **REFUTED on broker
truth** — the stops mostly force-closed thesis-favorable positions early (B1's
downstream finding); an honest data limitation on their side (no broker
access), not a reasoning error. Net: a **calibration-proven** external — high
weight on their future findings.

## 2026-07-09 EOD — EXTERNAL-REVIEW ADJUDICATION (read-only; verdicts + B1 headline + A6 corrections)

**B1 — THE HEADLINE (the number the external couldn't compute): thesis
hit-rate ≈ 7/9 (~78%) vs P&L hit-rate 1/9 (~11%). THE PROBLEM IS
DOWNSTREAM (execution/exits/costs), NOT the signal.** Scored each live
close's entry thesis against the underlying's path to its INTENDED horizon
(strikes + exp vs 07-09 prices): NFLX(down, hit), NFLX(down, hit, +48),
QQQ-IC 06-15 (QQQ 723 inside 645-750 → hit but force-closed −73), SPY-IC
(751 inside 681-765, on-track, −45), SOFI(18.6>17, on-track, −40),
QQQ-IC 07-07 (inside, −15), QQQ-IC 07-08 (inside, −10) = 7 thesis-
favorable; MARA×2 (13.2<13.5/14, didn't rise) = 2 miss. **6 of 9 were
thesis-RIGHT-but-lost-money** — the underlying was in/toward the profit
zone but the position was force-closed early at a loss (the premature-stop
/ Phase-3 over-pessimism pattern, now quantified). CAVEAT: 5 of 9 expiries
are FUTURE (07-24→08-21) → "on-track" not "hit"; labeled in-progress.
**INSTRUMENTATION GAP FILED: no shadow-to-expiry tracker — positions
force-closed in minutes leave nothing following the underlying to the
original expiry, so thesis quality is only spot-scoreable. This is the #1
missing measurement.**

**A6 — LEDGER CORRECTIONS (broker=truth; the realized P&L was always
RIGHT, the EXIT-PRICE DISPLAY used the MARK not the FILL — mid-vs-fill
confusion, recurring class):**
- QQQ 07-07: exit shown 1.74 (mark) → **broker FILL 1.64**; realized −$15 ✓.
- SOFI 06-30: exit shown 1.53 (mark) → **broker FILL 1.36**; entry 1.44 →
  1.36 = −0.08 ×5×100 = **−$40 ✓ (reconciles the "impossible" row)**.
- QQQ 07-08: exit shown 1.535 (mark) → **broker FILL 1.59**; credit 1.49 −
  1.59 = −0.10 ×1×100 = **−$10 ✓ (the "−5" was the mark)**.
  → The external packet §2a exit-price column reads MARKS; correct to these
  fills on its next revision (packet is committed #1142 — annotate there,
  not erase). P&L rows unchanged.

**A1-A7 VERDICTS (cites in the session):** A1 credit-spread PoP=credit/width
= max_gain/(max_gain+max_loss) (ev_calculator.py:42) — **CONFIRMED inverted
(≈P(loss)); but LATENT** — IRON_CONDOR + debit strategies (the whole live
book) are NOT in that branch's strategy_type list; blocks the 2-leg-vertical
cohort. A2 stop = pct × max_CREDIT (policy_lab/config.py:33), cohorts
0.40/0.50/0.65 — **CONFIRMED credit-relative** (~17% of max loss at 0.40),
naming-clear in config but the basis is credit not max-loss. A3 ranker fee
= fee×contracts×2, NO ×leg-count (canonical_ranker.py:69) + slippage =
5%-of-EV proxy (:145) vs the gate's executable cross — **CONFIRMED
multi-basis; ranker under-costs 4-leg → ordering distortion (small $, but
real)**. A4 score clamped min(100) (guardrails.py:138) — **saturation
CONFIRMED**; but compute_conviction_score DOES use iv_rank conditionally
(:118-123) → "IV not in score" **PARTIAL** (the roi×500 production score not
located). A5 compounder legacy path ~3%×score (~$60) with a self-alert of
"~6-8× smaller budget" — **CONFIRMED sizing-model gap** (production uses the
allocator ≈ max_loss; the legacy fit-test tests a fiction). A6 above. A7
the stops fired on OVER-pessimistic corroborated UPL and the positions were
in-profit-zone at horizon → **"stops saved money" REFUTED** — they mostly
stopped WINNING theses early (= B1's downstream finding + Phase-3).
**External Q1 (runtime flag) CONFIRMED — weight their findings accordingly.**

## 2026-07-09 ~21:29Z — CALIBRATION RE-ENABLED (env flip + recycle, supervised)

**ROOT CAUSE (recon-proven by execution): `CALIBRATION_ENABLED='0'` stale
kill-switch, off since the 06-11 epoch, never restored.** Calibration was
LIVE 04-13→06-10 (38 rows, ev≠ev_raw), then disabled at the epoch to stop
pre-epoch sign-flipped multipliers applying to post-epoch predictions —
correct then, but the master apply switch was never flipped back when the
pool matured (07-09). The apply sites (`workflow_orchestrator.py:3554`
midday scan / `:1740` morning) are gated on the module-level flag; both
skipped. `get_calibration_adjustments` returned the correct 0.5 blob and
`apply_calibration(real blob)` → 19.85 in positive control — **the code was
never broken; the flag was off.** **NEW CLASS LINE: disabled-and-never-
restored** — a deliberate temporary disable with NO re-enable trigger; kin
to dead-triggers (§backlog) and prescribed-not-applied (WakeToRun). The
disable was FAIL-QUIET (no per-scan log; the write job kept computing +
storing a blob nothing read).

**SEQUENCE (all gates cleared before the flip):**
- STEP 1 — 21:20Z SUPPRESSION TEST **PASSED** (edge-trigger case 3, first
  live proof): `suppressed_standing_window:true`, tripped:false,
  paused_written:false, reason "standing_window_already_reviewed —
  fingerprint matches the last trip"; window unchanged, entries stay
  unpaused, 0 trips. #1135 fully validated.
- STEP 2 — pre-flight cleared: the only `MIN_POP=0.60` gate
  (`guardrails.SmallAccountCompounder.apply`) is **DORMANT** (not called by
  the scan; field-name `prob_profit` vs prod `probability_of_profit`;
  superseded by `services/analytics/small_account_compounder.py`) → a halved
  PoP breaks nothing live. Epoch off-reason moot (blob is post-epoch by
  construction).
- STEP 3 — **`CALIBRATION_ENABLED` set 0→1 on worker + worker-background**
  (BE is not an apply site). Recycle → both SUCCESS at `907d4cdd` (= the
  running `03e11d8` apply code + #1142 docs packet the operator merged;
  **zero code change**, H8-verified by diff). **Read-back: env=1, module
  CALIBRATION_ENABLED=True on the worker.**
- STEP 4 — **PRODUCTION PROOF: PARTIAL tonight, FULL pending 16:00Z
  tomorrow.** The forced post-close scan (job cb2db12c) short-circuited on
  the market-data **staleness gate** (age 94.8min, fast_path, processed 0)
  BEFORE scoring — so no scanned ev and no apply-site log tonight. Confirmed
  tonight: flag flipped + module True + `apply_calibration(blob)`→0.5
  (function). **NOT YET CONFIRMED (the built-not-wired class is NOT fully
  closed until this lands): a real scanned `ev == ev_raw × 0.5`** — rides
  tomorrow's 16:00Z scheduled scan on fresh quotes. Verify then.

**⚠ TRUE BOUNDARY MARKER (supersedes the annotated-false 07-09 10:00Z
marker): the apply path is ENABLED from 2026-07-09 ~21:29Z (907d4cdd,
CALIBRATION_ENABLED=1), but NO production ev has been calibrated yet
(tonight's scan was staleness-gated). The FIRST calibrated production ev is
2026-07-10 16:00Z. Every EV ever stamped before that moment was RAW except
the 38 pre-epoch rows (04-13→06-10).** Direction: TIGHTENING (EV×0.5 →
gate rejects more) — doctrine-clean, not a loosening.

**Option-B observe window: reset condition HALF-MET** (calibration now
enabled); fully resets when the shadow-detection one-liner ships. 07-09's 9
observe lines stay discarded (computed on un-halved EV).

**FILED (small PR, tomorrow / with the shadow one-liner): fail-loud
hardening** — log once-per-scan when `CALIBRATION_ENABLED` gates apply off +
flag the compute-but-never-apply waste; optionally move the flag read from
import-time to call-time (so it takes effect without a recycle). A
month-long silent recurrence must be impossible.

**PENDING-VERIFY (tomorrow morning): (1) 16:00Z scan produces ev=ev_raw×0.5
on a real suggestion [closes the class]; (2) the PoP ×0.5 lands only on
display (no live consumer) — confirm no regression; (3) the 21:45Z/22:00Z
learning chain ran clean post-recycle.**

## 2026-07-09 EOD — FIRST-CALIBRATED-SCAN-DAY FINDINGS (doc-only; fix-queue for tomorrow)

Flat day (0 trades, equity $2,067.86, −$0 P&L). First full day on the
supposed ×0.5 calibration + the gate-fix observe-log armed. Two findings,
both Claude Code's own, both fail-safe, both self-caught same day.

- **FINDING #1 (HIGH, headline) — CALIBRATION COMPUTED-NOT-APPLIED**: the
  0.5 multiplier stores at 10:00Z but `apply_calibration` returns ×1.0 at
  the scan — champion first calibrated scan verbatim `ev==ev_raw==39.71`
  (halved would be 19.86). Insert path stamps ev_raw then overwrites
  ev=apply_calibration(...) (workflow_orchestrator.py:1745-1755); equal
  values ⇒ ×1.0 returned. Suspect: `get_calibration_adjustments` fails to
  map an `_overall`-only blob into the `{strategy:{regime}}` return shape,
  so the documented `_overall` fallback (calibration_service.py:577) never
  fires and application silently falls to ×1.0. **CLASS: built-not-wired
  (#1126 family — computes/stores but doesn't reach the decision path).**
  RECON-THEN-FIX, own session, FIRST work tomorrow. Cross-ref: flagged to
  the external reviewer as §1 question (1) — do not double-drive; whoever
  moves first claims it.
- **FINDING #2 (one-liner + test) — OPTION-A SHADOW-DETECTION MISS**:
  #1141's gate keyed `routing_mode == "paper_shadow"`, but production
  values are aggressive=`live_eligible`, neutral/conservative=`shadow_only`
  → matched nothing → ALL cohorts ran `basis=legacy_sized` (observe-only),
  the shadow-side fix INERT, observe-log mislabeled shadows as `cohort=live`.
  FAIL-SAFE (zero live change; the miss defaults to the protected path) but
  promotion-un-biasing didn't happen. FIX: match `shadow_only` (or
  `!= live_eligible`) + pin the test on PRODUCTION routing values (the bug
  was test-fixture `paper_shadow` vs reality `shadow_only` — a test-vs-truth
  value mismatch, adjacent to the 9a2cef1 class). Ships after/with #1.
- **OPTION-B OBSERVE-WINDOW — EVIDENCE INVALIDATED, CLOCK RESET**: 07-09's 9
  `[GATE_QTY_SCALED_SHADOW]` lines are CONTAMINATED — the "would-open"
  new_net was computed on the UN-halved EV (39.71); with the real ×0.5
  (finding #1) new_net ≈ 19.86 − 12 = +7.86 < $15 → would NOT open. And the
  qty7/qty15 lines are shadows mislabeled live (finding #2). **The ~1–2wk
  Option-B observation clock counts ONLY from the SHA where BOTH #1 (calib
  applies) AND #2 (shadow-detection correct) are live. Discard 07-09's 9
  lines.** Re-arm marker to be stamped at that SHA.
- **ERRATA (annotation #6)**: this morning's ritual assertion "every EV
  number is now calibrated ×0.5" was a **verify-before-asserting miss** —
  overturned same day by ev==ev_raw. Pattern line: **TWO Claude-Code errata
  today (this + the recon's "champion always qty-1" caught by the SOFI qty-5
  fixture), both fail-safe, both self-caught within the day.** The standing
  boundary marker (07-08 postclose entry) is annotated in place, not erased.
- **NOISE-CLASS PRESSURE (reinforces the TOP-3 3-in-1)**: the observability
  PR was FIX-TODAY in the morning triage and DID NOT ship (the gate-fix took
  the slot). Carried to tomorrow's 2nd build slot. Today's reinforcement:
  ops_output_stale +7, job_succeeded_with_errors +5, **signal_accuracy_
  degraded ×14 (observe-only warning firing ~2/hr on the losing pool — a NEW
  cry-wolf; ADD a once-per-day / condition-dedup sub-item to the 3-in-1).**

**TOMORROW'S BUILD ORDER (operator's word, post-close, sequential deltas):
① calibration recon-then-fix (#1) · ② shadow one-liner + prod-value test
(#2) · ③ 3-in-1 observability PR (flat-book stale + re-egress dedup + #1104
writer-hardening + accuracy-warn dedup) · ④ stamp the Option-B clock-reset
marker at the #1+#2 SHA.**

## 2026-07-09 MORNING TRIAGE — dispositions recorded (doc-only)

First v5.4-from-disk nightly ran + dead-man pinged GREEN (first live night).
Calibration PRINTED 10:00:03Z: `_overall ev_multiplier 0.5 / pop_multiplier
0.5` (BOTH clamp-floored; ev_calibration_error 65.34 — raw wanted lower;
single _overall bucket, 30d window at n=8) — **raw mode EXITED; EV/PoP now
calibrated ×0.5, the ledgered boundary is CROSSED.** Un-paused + acked the
21:20Z breaker trip + 3 accuracy warnings; fingerprint survived (holds the
QQQ−10 window bd895160 — tonight's suppression test armed).

Dispositions:
- **FILED-TRIGGERED**: #1104 writer-hardening (6/677 rows lost 07-08;
  bundle w/ today's 3-in-1 or next burst) → backlog P2 · reentry_cooldowns
  realized_loss=estimate → FOLDED into the 06-15 backlog item (2-for-2
  live, no new line).
- **ACK-NO-ACTION** (recorded so no re-raise): A6 executor 4×/day = operator
  manual mid-session/post-close cycles, NOT a scheduler defect (scheduled
  cadence is the one-shot) · phase2_precheck = paper-shadow phase-2 gate,
  operator to name it in the scheduler doc.
- **GATED-REOPEN counter: Phase-3 exit over-pessimism now 3rd instance,
  15.5× worst yet** (cohort stop −155 vs broker −10, 07-08). Counter
  **3/[10-15 reopen gate]**. ⚠ **PATTERN NOTE for the reopen session: three
  instances (QQQ 3.3× · SOFI 1.6× · QQQ 15.5×) — the reopen's HEADLINE
  question is "is the cohort stop systematically over-pessimistic on
  defined-risk structures?" (same question SOFI stop-tightness raised).**
  Do NOT act now — gated, outcome-bias-protected; recorded so the reopen
  opens on the pattern.
- **⚠ META-AUDIT DRIFT CAUGHT LIVE (the exact class the 07-08 meta-audit
  targeted): 4 items were ledger-only / prompt-KNOWN-PENDING and had FALLEN
  OFF the actionable backlog.md** — EV-basis recon (LIVE), B1/B2 bucket
  control (LIVE), compounder greedy-stop (LIVE), the #12 06-10-runner batch;
  gap-3(b) existed only as a sub-note. **All re-added to backlog.md this
  session** (P1 for the two live-money, P2 for the rest). Process note: the
  ledger narrative is NOT the actionable list — filed items must land in
  backlog.md or they silently vanish from build-planning.
- **FIX-TODAY queue (pending-today, NOT built)**: the 3-in-1 observability
  PR — flat-book guard on ops_output_stale (A9) + re-egress cross-owner
  dedup (A5) + #1104 writer-hardening (A4). Post-close, one recycle. All
  three health-check/observability-side; zero decision-path risk.
- CONFIRM list checked: F-A1a · reaper · winter-close 2026-10-01 present ✓;
  one-beta tripwire SHIPPED #1139 ✓ (B1/B2 the only open bucket item);
  gap-3(a) SHIPPED #1124 present ✓.

## 2026-07-08 PR-B #1139 ONE-BETA TRIPWIRE — status:SHIPPED

**H8 VERIFIED: squash `7db5a36` (7db5a36dcd4fc1bf58eb67878e387ce2f3c3a2bd)
= origin/main; all three services SUCCESS at that SHA (22:29:35Z);
new-container work flowing by 22:30:04Z (heartbeat OK on the recycled
worker).** PR-A #1138 (`e26bcfe`) merged immediately before — tonight's
midnight nightly runs the v5.4 charter from disk for the first time.

Tripwire live: `concurrent_live_positions_uncontrolled` critical at ≥2 open
LIVE-routed positions, q15 monitor, immediate-egress + receipt.
**VERSION SHIPPED: simplest-correct (ANY 2 live positions), per owner
rationale — bucket refinement stays B1/B2's (still FILED; the alarm is not
the control).** Semantics: alarm-on-onset (position-set dedup; a 3rd
position re-alarms; dedup-read failure alarms anyway; scope-failed cycle
skips). Flag CONCURRENT_POSITION_ALARM_ENABLED default-ON. Disaster-pinned:
never mutates positions/orders/ops_control (test). 12 tests incl. the
production-call-path wiring pin. OPERATOR REMAINING: create the
healthchecks check + set machine env NIGHTLY_AUDIT_PING_URL (PR-A's ping
gate is a logged no-op until then).

## 2026-07-08 META-AUDIT (chat-run, gap register) + TIER-1 PROCESS FIXES — status:SHIPPED (PR-A)

**Meta-audit verdict (full register in session 07-08 ~22:15Z): ship-side
TRUSTWORTHY (ledger↔git 1:1 over 22 commits; 4 spot-checked fixes verified
against RUNNING behavior; zero built-not-wired in the shipped set); intake
side LEAKY (9 goes-silent findings, concentrated pre-ledger 06-10 runners;
2 re-verified STILL REAL); charter side STALE (disk prompt was v5.0/06-12;
scheduled cadence 6 reports/27 nights; 3 silent-empty runs 06-13/14/20).**

PR-A ships: **v5.4 TO DISK** (audit/v5-prompt.md — gap #7; adds A1(iv)
sizing/allocation custody [gap #10] + expected-state: suppression-is-
designed, headless-broker-blind, breaker ritual) · **ping-after-file-exists**
in run-nightly.cmd (gap #8; NO ping existed at all — first wiring;
PowerShell date because %DATE% is locale-formatted and would never match;
gate dry-run verified both directions; operator: create the healthchecks
check + set machine env NIGHTLY_AUDIT_PING_URL, Grace ~26h) · **sweep
convention** (gap #9, CLAUDE.md §7; 07-08 report swept in this PR) ·
**#1104 CLOSED**: operator confirmed reset ~13:45 CT → 18:45:26Z burst =
C1 rotation artifact CONFIRMED; pool-config reopen stays SHUT.

Meta-audit open register (dispositions pending owner triage): expiry-day ×
unpriceable defer seam (live$, own recon) · compounder greedy-stop BREAK
:286 (live$, Tier-2 fix) · EV-basis ∪ fee-unit recon (merged charter,
pre-market session) · F-A1a mechanical guard · one-beta tripwire (PR-B
TONIGHT) · PoP-denom/DTE segmentation (fold into clamp review) · smaller
silents batch (envelope re-egress 13/3h · A9-F4 · F-A2d · N4 · universe_size
mislabel · time-stop/eod-phantoms · N1/N2 · 06-10 A5/A6 partials) · A6
executor-4× question ANSWERED (operator manual cycles, no scheduler change).

## 2026-07-08 POST-CLOSE — #1137 SIGN FIX + FALSE-AGER — status:SHIPPED · THE TRIPLE-GATE POOL SEALED (8/8)

**H8 VERIFIED: squash `2a83174` (2a83174ed78080e329626297d1c9eaab8d8c6bb1)
= origin/main; all three services SUCCESS; worker-background container
20:51:29Z > merge 20:50:03Z — 29 min settle margin before the 21:20Z
ingest (race deadline CI-green-by-21:05Z beaten at 20:49:38Z).**

- **Sign fix live**: `broker_fill_to_mark_basis` (negation, not abs) at the
  live-fill reconciler; QQQ credit pin 1.4167 + SOFI debit 0.2326 + corrupt
  -15.08-shape regression + call-site wiring all test-pinned. **Both
  poisoned rows RE-DERIVED (supervised, read-back)**: bd25cc9d 15.083→
  **1.4167**, 3139842b 3.076→**0.9635**. The live Phase-3 gap dataset (3
  rows: SOFI 0.23 · QQQ 1.42 · QQQ 0.96) is now honest.
- **False-ager fixed**: monitor Part-B persist stamps `last_marked_at`;
  **9** ops_output_stale highs ACKed cause-fixed (2 more had fired since
  the mid-session count of 7; ids in session log).
- **BREAKER — edge-trigger case 2 FIRST LIVE PROOF (21:20:02Z on
  `2a83174`)**: new loss → new window [QQQ −10 bd895160 · QQQ −15 7dd459f8
  · SOFI −40 055ead84] → `edge_trigger:true, tripped:true, paused_written:
  true, fingerprint_stamped:true` — the NEW fingerprint REPLACED the old
  stamp (read-back ✓; MARA 0c54ead8 aged out). Critical receipt:
  webhook_sent=true 21:20:05Z. **Tomorrow's suppression test compares
  against THIS window** — morning un-pause, then a no-close Thursday must
  yield `suppressed_standing_window:true`, no re-pause, no critical.
- **CLOSE #9 INGESTED**: outcomes_created=1, errors=0; typed
  strategy=IRON_CONDOR / regime=normal ✓; gap datapoint born clean
  (its order row was re-derived pre-ingest). **Post-epoch live pool = 8/8.**
- **⚠ TRIPLE-GATE BOUNDARY MARKER — EV numbers change at 2026-07-09
  10:00Z, not tonight**: the pool sealed at 21:20Z tonight, but the relearn
  executes at the scheduled calibration_update (05:00 CT / 10:00Z). First
  real multipliers print then; consumers from that run onward:
  `apply_calibration` → scanner EV/PoP scoring → `risk_adjusted_ev`
  (executor sort) AND `ticket.expected_value` = the #1101 roundtrip gate's
  gross_ev — every gate decision after 10:00Z is on calibrated numbers.
  **⚠⚠ ANNOTATION 2026-07-09 EOD (do NOT erase this marker — correct it):
  this boundary is FALSE. The multiplier COMPUTED + STORED 0.5 at 10:00Z but
  apply_calibration returns ×1.0 at the scan (ev==ev_raw==39.71 verbatim
  07-09) — see the 07-09 EOD entry, fix-queue #1. "Every EV after 10:00Z is
  calibrated" holds only from the SHA where finding #1 ships; re-mark the
  TRUE boundary there.**
  Training pool: {+48, −45, −28, −73, −15, −40, −15, −10} (1W/7L) — expect
  a SHRINK; whether the 0.5 clamp floor binds is the clamp-review question,
  answerable when the multiplier prints. Winsorize: no extreme outlier in
  the live-only pool (max |x|=73) — likely no-action, owner-gated.
- **Accuracy alert**: expected at the first post-ingest health check
  (21:37Z; n=8, hit 12.5% < 0.2) — observe-only; verify in the morning
  ritual.
- **FILED: 06-08 NFLX pre-epoch live close missing from
  learning_feedback_loops** (broker+champion ledger=9 all-time, outcome
  table=8 post-tonight) — pre-epoch-flagged backfill, rides any future PR;
  no effect on the calibration pool (pre-epoch excluded by design).
- Untouched, confirmed: roundtrip gate (EV-basis recon own session — now
  MORE important: the new multiplier flows into that same comparison) ·
  one-beta B1/B2 · reaper · gap-3(b) · #1104 (pending reset-time).

## 2026-07-07 POST-CLOSE — #1135 EDGE-TRIGGER BREAKER — status:SHIPPED

**H8 VERIFIED: squash `be13733` (be137338ac1e89299cc18034bc04c6201427e47f)
= origin/main; BE + worker + worker-background all SUCCESS at that SHA;
container start 22:18:03Z > merge ~22:16Z.** CI green first try. Migration
`20260707221500` (ops_control.streak_breaker_state jsonb, additive
nullable) applied + tracked PRE-merge, read-back verified.

**Semantics live**: re-trip ONLY on window CHANGE. Fingerprint =
CONTENT-based sorted trailing-N outcome row ids, stamped at TRIP time —
**the operator un-pause SQL is UNCHANGED and is sufficient review** (the
window identity was recorded when it paged them). Suppression needs a
POSITIVE match; no-stamp/NULL/malformed/read-error/stamp-failure all
degrade toward tripping. A NEW loss trips instantly (protection intact —
framed in the PR: not loosening, operator-override-respect added). **Flag
`STREAK_BREAKER_EDGE_TRIGGER_ENABLED` DEFAULT-ON** (explicit falsy →
legacy level-trigger byte-identical); wiring test-pinned in
evaluate_and_trip (no #1126-class inert flag). CLAUDE.md §4 runbook
REPLACED (the nightly-re-trip paragraph is retired).

**Baseline + stamp (tomorrow's before/after)**: tonight's 21:20:02Z trip
ran on `5809505` (level-trigger era, PRE-#1135) — window by ingest order =
QQQ −15 (7dd459f8) / SOFI −40 (055ead84) / MARA −15 (0c54ead8); the trip
critical carries the #1134 receipt: webhook_sent=true, egressed_at
21:20:06Z, owner=alert — **#1134's receipt FIRST LIVE EXERCISE, PASS**.
One-time operator-approved stamp EXECUTED post-H8 (tonight's window
fingerprint backfilled via the breaker's own ordering; read-back
confirmed) because the trip predated the stamping code.
entries_paused=TRUE now (tonight's trip — morning un-pause ritual
unchanged).

**TOMORROW'S PIN (first suppression test)**: morning un-pause → 21:20Z
ingest on an UNCHANGED window → expect `suppressed_standing_window: true`
in job_runs.result.streak_breaker, NO re-pause, NO nightly critical,
entries stay armed. A NEW loss instead → trips (also correct). Attribution
clean: #1135 is the only behavioral change in its recycle.

## 2026-07-07 POST-CLOSE — #1134 TAXONOMY + ALERT-INTEGRITY — status:SHIPPED

**H8 VERIFIED (the shipped bar): squash `5809505`
(58095053c10eb76607552355acb1aecc0c2a8a9a) = origin/main; BE + worker +
worker-background all deployment SUCCESS at that SHA; container start
21:10:18Z > merge ~21:08Z; post-recycle job flow confirmed (21:10:01Z
learning_ingest succeeded).** CI green first try (run 28898768862).

**Old→new alert-type map (readers map old→new; historical rows untouched):**
- `force_close` + real submitted close → `force_close` (unchanged, critical,
  immediate egress)
- `force_close` + "Force close FAILED" → **`force_close_failed`** (critical,
  ADDED to immediate-egress allowlist)
- `force_close` + "[WARN-ONLY] … enforcement disabled" →
  **`envelope_violation_warn_only`** (high — was critical; relay path)
- `warn` (envelope block) → **`envelope_violation`** (high; relay)
- `warn` (envelope warn) → **`envelope_violation`** (warning — was the
  out-of-vocab 'medium'; no egress, anti-spam unchanged)
- Writer unification: monitor `_log_alert` now delegates to canonical
  `alert()` (severity normalize medium/warn→warning, error→high; #1100
  retry; owner stamp; receipt) — the which-writer-wrote-it egress lottery
  (today's real force_close on the ≤37-min relay) is closed.

**A9 receipt live**: `metadata.egress_receipt` {webhook_sent, sent,
suppressed_reason, receipted_at} + `egressed_at` stamped post-send;
`[ALERT_RECEIPT]` WARNING both outcomes; FAIL-OPEN test-pinned. **F8 live**:
suggestions_open rolls `rejection_persist_failures` → top-level
`counts.errors` + ok:false; runner folds alert-write-failure deltas into
every job's `counts.errors` (A4-visible; zero-delta byte-identical).

**F3 PATH TAKEN — UNAMBIGUOUS: F3-MINIMAL SHIPPED / F3-FULL FILED.**
Shipped: transient matcher now catches the 18:45Z specimen (httpx
WriteError / "Connection reset by peer" → retries), and a critical/high
whose insert is STILL lost force-egresses the webhook marked
`[DB-ROW-LOST]` (inbox = durable trace; test-pinned). NOT built: the
all-severities durable buffer — warning-class rows still degrade to
logger.exception only; filed as its own item (the critical-class hard
trigger is satisfied by the fail-safe).

PENDING VERIFICATION (tonight/tomorrow): 21:20Z ingest runs on `5809505` —
today's −$15 QQQ close makes the window MARA −15 / QQQ −73 / QQQ −15 →
expected RE-TRIP = **first live exercise of the new immediate-egress path**:
the `streak_breaker_tripped` critical should carry
`metadata.egress_receipt.webhook_sent=true` + `egressed_at` + an
`[ALERT_RECEIPT]` worker-background log line. Also watch: first
`envelope_violation`-typed rows at the next violation; the designed
channel-2 INFO replacing the legacy-mode WARNING; morning un-pause ritual
unchanged.

HYGIENE (filed 07-06, from the M4 CI failure): `test_weekly_report_win_rate.py`
replaces 18 modules (incl. cash_service, options_scanner) with MagicMocks in
sys.modules at import time and NEVER restores — any later lazy in-test import
binds a mock (green single-file local, red full-suite CI; cost tonight: one
red CI round on #1132). M4's test file now binds real modules at import with a
de-poison guard; the POISONER itself is unfixed and has pre-existing order
sensitivity (6 capital-basis failures in explicit weekly-first order — never
CI's alphabetical order). Follow-up: convert to conftest fixture/unpatch;
grep for siblings doing module-level sys.modules assignment without restore.

## status:reported — 2026-07-08 NIGHTLY run (report `audit/reports/2026-07-08.md`)

Window 07-06 05:01Z → 07-08 05:01Z — the 15-day flat stretch ENDED. Both workers
SUCCESS @ `be137338` (#1135) = origin/main HEAD (H8 clean; start 07-07 22:17:35Z).
**First LIVE fill since 06-30:** QQQ iron condor `386a39fe` (aggressive cohort
`3d289dca`), entry 14:37Z (off-schedule executor run, filled 1.49 credit vs 1.41 limit,
+$8 improvement, 76ms), force-closed 17:45Z on `intraday_stop_loss`, realized −$15.00.
`entries_paused=TRUE` since 07-07 21:20Z (breaker re-trip; **operator un-pause required**).
Live champion now 1 win / 7 post-epoch closes, −$168, hit-rate 14.3% (Brier 0.296).
⚠ **RUN LIMITATION:** alpaca MCP tools absent — broker not snapshot-read; live trade
DB-corroborated (execution_mode=alpaca_live + reconciler + is_paper=false), not
broker-confirmed. Equity/OBP not re-read (last $2,093.74 07-06, −15 QQQ ⇒ ≈$2,078.7 DB-derived).

- **[A4 2026-07-08 — FINDING] `close_fill_gap` sign-convention bug corrupts every
  live-close gap_fraction (poisons the deferred Phase-3 reopen gate).** The #1102
  instrumentation computes `gap_fraction=(fill−cross)/(mid−cross)` with NO sign normalization
  (`services/close_fill_gap.py:62-78`). On the LIVE/reconciler path
  `brokers/alpaca_order_handler.py:571` forces `fill=abs(filled_avg_price)` (+1.64) while
  `cross`/`mid` are stamped SIGNED (`paper_exit_evaluator.py:1913,1976` from `current_mark`
  −1.74 / corroboration −1.98). QQQ 07-07, the FIRST live full-quad close, stored
  fraction **15.0833** (=3.62/0.24) vs the correct-sign **1.417**. Internal/shadow exit
  path passes signed fill → self-consistent; only the LIVE path is wrong. Test fixture
  (`tests/test_close_fill_gap.py:44-47`) uses consistent-positive signs (SOFI→0.2326) → CI
  green while production is corrupt = the #1126/9a2cef1 test-green-production-wrong class
  (§9 never-do). Since #1102 shipped: 0 usable live gap_fractions (QQQ corrupt, SOFI-07-01
  shadow null). FIX: one line — sign-match fill at `:571` (drop `abs()`) or abs cross/mid at
  `:567`; add a mixed-sign fixture. RISK zero (observe-only, best-effort try/except).
  CONFIDENCE high (DB arithmetic + code both dispositive). Blast-radius note: the deferred
  Phase-3 "two-quote confirmation" safety fix (reduces over-pessimistic premature
  force-closes: QQQ −49-est/−15-fill, SOFI −65/−40) is GATED on this now-broken distribution.
- **[A5 2026-07-08 — FINDING] Standing-envelope alerts re-egress to the operator phone
  every 15-min monitor cycle (no content-dedup) — cry-wolf burying criticals.** While one
  live QQQ was held, "QQQ is 100% of risk (limit 40%)" was re-written HIGH and relay-egressed
  every cycle → **13 phone egresses in 3h** (14:45–17:45Z) + 26 non-egressed medium
  expiry/sector; the `force_close` critical egressed 18:07Z, AFTER them.
  `risk/risk_envelope.py:316-354` appends fresh each check; `intraday_risk_monitor.py:449-496`
  no changed-since-last-cycle guard (concentration severity default `"block"`→HIGH); relay
  poller `ops_health_service.py:1431` suppresses only per-row already-egressed stamps
  (`:1479`), NO type+symbol+content fingerprint. **Confirmed persists post-#1134** (rename
  kept concentration→high→relay). FIX (additive): apply #1135's edge-trigger principle to
  egress — suppress re-egress of an unchanged (type,symbol,bucket) standing condition within
  a hold. RISK zero (egress-only). CONFIDENCE high.
- **A1/A3/A7 UNCHANGED** (raw mode holds at 7/8 post-epoch live; ingest clean errors=0;
  QQQ condor hold 3h07m = ledgered cohort-stop-dominates-condors). **A2** — GATED Phase-3
  over-pessimism class exercised a 2nd time (QQQ −49 corroborated est vs −15 fill; cited,
  not re-found); its reopen data is the A4 bug. **A6** — binding constraint = EV-after-cost
  ($15 roundtrip floor rejected aggressive `38d57d55` at net +14.45), not cadence; OPEN Q:
  executor ran 4× on 07-07 (14:37 exec-1, 16:30/17:59/18:47 exec-0) vs one-shot/day — likely
  operator retries around the un-pause, confirm.
- **A8** roundtrip-reject class now exercised LIVE (aggressive +14.45 = edge-lost;
  neutral/conservative = spread-eaten); reject-was-a-win again (QQQ passed→−15). Per-gate
  marker still backlog RESEARCH. **A9** no new integrity finding (all alerts honest; the
  egress noise is honest→A5; ops_data_stale silent — market open). **A10** no new instance;
  winter-close blind hour (Nov) still queued; no fixture inside 45d.

VERIFICATIONS CLOSED THIS RUN:
- ✅ **M4 post-fix healthy scan** (07-07): 0 `micro_tier_underlying_too_high`, 76 syms, 0
  `alpaca_options_buying_power_query_failed`. The 07-06 inverted-universe incident's zero was
  the incident's, not the gates' — M4 (#1132) HELD on the next RTH day.
- ✅ **CVX IV-eligibility**: scanned 07-07, `iv_rank_insufficient_history`=0, rejected on
  real `spread_too_wide_real`. **GLD**: scanned clean (no strike/IV errors). M1/M2/CVX closed.
- ✅ **Breaker re-eval**: 07-06 21:20Z re-tripped; 07-07 21:20Z re-tripped on NEW QQQ−15
  (window rolled QQQ−73→QQQ−15). #1134 streak-breaker critical carried `egressed_at`
  21:20:06Z (receipt partial-confirm).

PENDING VERIFICATIONS (2026-07-08 → next session):
- **⚠ OPERATOR: `entries_paused=TRUE`** (07-07 21:20Z, QQQ−15/SOFI−40/MARA−15). Un-pause
  before the next RTH else the 16:30Z staging proof no-ops.
- **#1135 edge-trigger FIRST SUPPRESSION test — STILL PENDING**: 07-07 21:20Z ran on #1134
  (pre-#1135 deploy 22:17Z) AND a new loss landed (window changed→tripped). The distinctive
  `suppressed_standing_window` path fires 07-08 21:20Z IFF operator un-pauses and no new loss.
- **#1134 first `envelope_violation` typed rows + egress receipt** on the next position-hold.
- **First CORRECTED `[CLOSE_FILL_GAP]`** once the A4 sign fix ships (expect ~1.4, not 15.08).
- **A6 executor-cadence**: confirm whether 4×/day is scheduled or operator-driven.

## status:reported — 2026-07-09 NIGHTLY run (report `audit/reports/2026-07-09.md`)

Window 07-08 05:01Z → 07-09 05:01Z. Clocks grounded (DB 05:01:23Z = broker 01:02 ET ✓).
**Broker READ DIRECTLY this run** (MCP present): equity $2,067.87 = cash = OBP (settled,
flat, 0 positions); 07-08 day −$10.43. H8 CLEAN: all THREE services SUCCESS @ `7db5a36`
(#1139) 22:29:35Z; movers off the prompt pin: `e26bcfe` #1138, `7db5a36` #1139.
**POOL SEALED 8/8** (1W/7L, −$178): live QQQ IC `305e476a` staged 17:41Z (ev 41.75 / pop
0.6425 raw), force-closed 18:00:11Z after ~15min — cohort stop on corroborated −$155 vs
broker fill −$10 (15.5×; Phase-3 class instance #3, counter 3/10-15). Breaker: designed
edge-trigger case-2 trip 21:20Z (window CHANGED: QQQ−10 in / MARA−15 out; fingerprint
stamped; receipt egressed). `entries_paused=TRUE` — **operator un-pause required**.
**CALIBRATION BOUNDARY: first calibrated multipliers print 07-09 10:00Z** (07-08 run was
sample 7 insufficient) — the three 8th-close checks are DUE.

- **[A9 2026-07-09 — FINDING] `ops_output_stale` paper_positions arm = standing HIGH
  false alarm, UNCLEARABLE while the book is flat + paused; the v5.4 STATE "RESOLVED"
  verdict is half-true.** 11 HIGH rows 07-08 (13:07→22:07Z, self-superseding; latest 2
  unresolved, 176→177h and climbing) assert a dead mark-refresh loop while Part-B wrote
  `mark_corroborated −3.04` the same hour. Root: `MAX(last_marked_at)` = 07-01 13:00Z —
  BOTH July QQQ holds ran pre-#1137 code (deploy 20:50Z 07-08 was post-close; QQQ 07-08
  row `last_marked_at=NULL`), and a flat book gives the live fix nothing to stamp. The
  §8 flat-book caveat is DOCUMENTED at `ops_health_service.py:149-152` but UNGUARDED
  (`:527-548` has no open-positions check). Projected ~48 HIGH rows/day for the whole
  pause (0 egressed — ops_* relay-skipped; poisons H11 triage). FIX (additive): flat-book
  guard — `open_n=0` → status `flat`/INFO, never `stale`/HIGH. RISK zero. CONF high.
- **[A5 2026-07-09 — FINDING, broadens the ledgered 07-08 re-egress item] the
  duplicate-egress class includes `egress_owner='alert'` writers, not just the relay.**
  `job_succeeded_with_errors` for the ONE 19:02Z scan run (`run_id ef8a2d4e`) re-wrote +
  re-egressed at 19:07/20:07/21:07/22:07Z — 4 receipted phone hits for one condition.
  The queued dedup fix must fingerprint the CONDITION (run_id / type+symbol+bucket)
  across BOTH owners or it fixes half the class. Watch, same shape:
  `ops_signal_accuracy_degraded` re-writes ~2/hr while hit<0.2 (designed first fire
  07-08 21:37Z at n=8 hit 0.125; warning-only, not egressed — row noise).
- **[A4 2026-07-09 — FINDING, small] rejection-persist retry loses rows when the retry
  hits the same dead connection — first data loss since #1104.** 19:02Z broken-pipe
  burst: 7 inserts recovered, **6 lost for good** (SLV/ISRG/C/HOOD/PLTR/AMGN, broken pipe
  on retry too); `counts.errors=6` with `result.errors=NULL` (count surfaced, items only
  in Railway logs). The #1100 detector caught it and it reached the phone with receipt —
  the chain WORKED; the residual is the writer. FIX (additive): reconnect-then-retry or
  ×2 backoff + stamp failed symbols into `result.errors`. Impact 6/677 (0.9%) of A8's
  counterfactual data. CONF high (logs + counts agree).
- **[A2 2026-07-09 — refinement of the 06-15 deferred cooldown item; metadata-only]**
  `reentry_cooldowns.realized_loss` stores the trigger-time corroborated ESTIMATE, not
  the fill — now 2-for-2 on live closes post-#1080 (−48.99 recorded vs −15 realized
  07-07; −155 vs −10 07-08). Bench durations unaffected; magnitude readers misled.
- **A1** EV-basis recon item (KNOWN-PENDING) reproduced with dispositive numbers on the
  LIVE cohort: aggressive QQQ 16:00Z stamped `net_ev +35.62` but gate-BLOCKED; gate log
  basis `gross_ev 42.14 − round_trip 154.00 = −111.86` (neutral twin; stamped net_ev
  NULL). Two bases disagree on the same candidate; it demonstrably timed the live entry
  (16:00 block → 17:41 pass). Urgency ↑ post-boundary. **A6** unchanged (677 rejections,
  mix stable; iv-seasoning 40/10syms = 06-17 adds, eligible ~mid-Aug; Polygon DARK on 8
  liquid QQQ legs 19:03Z, truth-layer priced — #1052 saved staging). **A8** SOFI sentinel
  quiet; gate discriminated (aggressive edge-passed, shadows spread-eaten). **A10** no
  new instance (counter 2). **A7** dormant, fills 3/10.

VERIFICATIONS CLOSED THIS RUN:
- ✅ **#1134 typed rows + delivery receipt — BOTH egress owners**: 2 `envelope_violation`
  HIGH (17:45/18:00Z) relay-egressed with `egressed_at`; `job_succeeded_with_errors`
  carried full `egress_receipt {sent, receipted_at, webhook_sent}` (alert-owner).
- ✅ **Cooldown bench post-stop**: 19:02Z pending aggressive QQQ NOT staged at the 19:03Z
  executor run (benched until 07-09 13:30Z) — the bench gate exercised, correct.
- ✅ **#1071/#1058 brake line**: `[EQUITY_STATE]` used broker-true −10.43 over the $0
  open-book proxy — tighter value chosen, correct.

PENDING VERIFICATIONS (2026-07-09 → next session):
- **⚠ OPERATOR: `entries_paused=TRUE`** (07-08 21:20Z window QQQ−10/QQQ−15/SOFI−40);
  un-pause is operator-only.
- **CALIBRATION BOUNDARY 07-09 10:00Z**: expect raw-mode EXIT (first real multipliers on
  8 live closes); run the clamp(0.5-floor) + winsorize reviews (owner-gated). Attribute
  any post-10:00Z scoring/gate shift to the multiplier FIRST.
- **#1135 FIRST SUPPRESSION — decisive test 07-09 21:20Z**: book flat + paused + no new
  close ⇒ expect `suppressed_standing_window: true` and NO new critical. A re-pause/
  critical on the UNCHANGED window = edge-trigger FAILURE (flag hard).
- **First NATIVE post-#1137 `[CLOSE_FILL_GAP]` stamp** on the next live close (the 07-08
  quad was corrected in-DB, not code-native).
- **First post-#1137 hold stamps `last_marked_at`** (currently MAX=07-01 13:00Z; the fix
  is live but UNEXERCISED — this is the condition the A9 finding's "RESOLVED" verdict
  hangs on).
- **#1139 one-beta tripwire**: live but unexercisable at ≤1 position; fires only if 2+
  concurrent live positions ever exist (that event ALSO reopens A2's settled condition).
- **A6 executor cadence** (3rd ask): scans 16:00/17:41/19:02Z + execs 16:30/17:43/19:03Z
  on 07-08 — scheduled multi-cycle or operator-driven?
- **phase2_precheck naming**: 4×/day green job outside the doctrine's scheduler map
  (free-look, no anomaly) — one-line operator naming requested.
