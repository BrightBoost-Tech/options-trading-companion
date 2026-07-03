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
