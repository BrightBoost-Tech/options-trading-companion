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
