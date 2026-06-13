# SPEC: Fast Exit Loop (1–2 min mark + exit evaluation cycle)

Status: PROPOSED — design only (2026-06-12). No code ships with this doc.
Decision context: the 06-12 spike forensics (audit/reports/2026-06-12 session;
summary below) concluded the chart spike was a **mark artifact** — a fast loop
would have captured $0 today and, run naively on mid-marks, would have
*submitted more phantom closes*. This spec is therefore hardening for the
*next* real fleeting move, and it is gated on the #1034 enforcement
prerequisites below. Build order recommendation: after resting-TP
(docs/specs/resting_tp_orders.md), before streaming
(docs/specs/streaming_exits.md).

## 1. Motivating incident (what this loop is and is not for)

2026-06-12 14:41–14:52Z: QQQ dipped −0.65% and V-recovered; the Alpaca equity
chart printed +$180 (peak $2,465.34 at 14:49–14:51Z) from **leg-timestamp
skew** (short C750 marked at its fresh dip-bottom print 7.79 while the
offsetting long C755 sat on a pre-dip 7.11 print). Executable close (sell at
bid / buy at ask) never came near any cohort tp. The 14:45:02Z monitor cycle
ran *during* the chart spike with live NBBO and correctly found no trigger.
Meanwhile the real failure that day was the opposite class: a 13:30:08Z
phantom TP on a degenerate quote (C750 bid 0.76 / ask 14.09 → mid 7.425
looked plausible; achievable P&L was **−$599** vs triggering +$96).

Conclusion: cadence was not the binding defect; mark quality and gate
enforcement were. A fast loop is only safe **after** those are fixed, and its
genuine value is reducing detection latency for *real* fleeting moves
(primarily the stop side, where every minute of delay is unbounded risk).

## 2. Prerequisites (hard gates — do not build past these)

1. **Deploy the close-hardening commits** currently on `post-close-hardening`:
   `745ced4` (single-submitter close, terminal-reject classification) and
   `48cf8ec` (degenerate-quote rejection + stale-fallback trigger guard).
   Both address failure modes a faster loop would *amplify*.
2. **#1034 spread_width normalization fix.** The 06-12 13:30Z QQQ observation
   row shows `divergence_frac = 0.060` for a $695 divergence because
   `spread_width` was computed as 115 (max strike − min strike across the
   condor: 755−640) instead of the wing width (5). Tolerance (0.10) is
   meaningless against that denominator. Fix: per-vertical width (or
   max-loss basis) in `packages/quantum/analytics/exit_mark_corroboration.py`
   `compute_corroboration()`.
3. **#1034 Stage-2 enforcement for target_profit.** Today the gate is
   observe-only (`would_suppress` recorded, never acted on —
   `intraday_risk_monitor.py` force-close path calls `observe_exit_mark()`
   purely for logging). A 1-min loop multiplies trigger evaluations ~15×;
   the suppress verdict must actually suppress TP staging. `stop_loss` stays
   never-suppressed (existing doctrine, `suppress_reason =
   stop_loss_never_suppress`).

## 3. What the loop does

Every 60–120s during RTH, for **live-routed open positions only**
(`risk/position_scope.live_routed_portfolio_ids` — shadows keep the 15-min
cadence; their fills are synthetic, latency buys nothing):

1. Batch-fetch leg snapshots via the truth layer (one
   `MarketDataTruthLayer.snapshot_many(all_symbols)` call — same source as
   the monitor, `intraday_risk_monitor.py:494` pattern).
2. Recompute structure marks with the shared mark math
   (`risk/mark_math.compute_current_value` + `finalize_mark`) — **no parallel
   mark logic**, the degenerate-quote / stale-fallback guards from `48cf8ec`
   apply by construction because the same functions run.
3. Evaluate exits with the same evaluator (`evaluate_position_exit` +
   `load_cohort_configs` from `packages/quantum/policy_lab/config.py`) —
   cohort-aware tp/stop, identical thresholds to the monitor.
4. On trigger: #1034 corroboration on the EXECUTABLE side (enforcing, per
   prerequisite 3) → stage through `paper_exit_evaluator._close_position()`
   with `exit_price_override` — the **same single submitter** as the monitor
   (745ced4). No new order path exists.

Explicitly NOT in scope: envelope evaluation, sizing multipliers, ghost
reconciliation, learning writes — those remain 15-min monitor
responsibilities. The fast loop marks and exits, nothing else.

## 4. Quote cost arithmetic

Current live book: 6 legs (NFLX 2-leg debit spread + QQQ 4-leg condor);
design envelope 8–10 legs (max_positions_open=4 aggressive × ≤4 legs = 16
worst case).

- Truth layer batches up to 100 symbols per Alpaca options-snapshot request →
  **1 request per cycle** regardless of 6 vs 16 legs.
- 1-min cadence × 6.5h RTH = **390 requests/day**; 2-min = 195/day.
- Alpaca data API budget: 200 req/min on the basic plan (10k/min on paid).
  The loop consumes ≤1/min — ~0.5% of the *worst-case* budget, alongside the
  existing order-sync (q5min) and monitor (q15min) consumers. No new 429
  exposure; the existing retry stack covers transients
  (`market_data_truth_layer.py:728-840`: urllib3 status_forcelist
  [429,5xx] + app-level MAX_RETRIES=5, backoff 0.5–30s, ±25% jitter).
- Polygon is fallback-only (Alpaca miss); Options Developer plan has no
  monthly cap; worst case adds 1 request/cycle.
- Verify the actual Alpaca data-plan tier on Railway env before setting
  cadence to 60s; at 120s the question is moot on any tier.

## 5. Scheduling and interaction with the 15-min monitor

- **New job, not a tightened `paper_exit_evaluate`.** `paper_exit_evaluate`
  is twice-daily (scheduler.py:53,63 — 8:35/14:45 CT) and does close-cycle
  work beyond exits; retuning it couples unrelated behavior. Register
  `fast_exit_scan` in `packages/quantum/scheduler.py` as its own CronTrigger
  (minute `*`, hour 8-15, America/Chicago, weekdays — same shape as
  `intraday_risk_monitor` at scheduler.py:99) firing a new signed endpoint
  `/internal/tasks/risk/fast-exit-scan`.
- Market-hours gate: reuse `_is_market_open()`
  (intraday_risk_monitor.py:391-430, Alpaca clock, 60s TTL).
- `misfire_grace_time=30` (not the monitor's 300): a missed fast tick must
  DROP, not queue — bunched ticks after a stall are how duplicate pressure
  starts.
- Hard runtime cap < cadence (45s timeout): a hung cycle self-terminates
  before the next fires. Skip-if-running via the existing `job_runs`
  `locked_by/locked_at` pattern keyed on its own job name.
- **Who wins if both the fast loop and the monitor fire on the same
  position:** nobody needs to — the close path is idempotent by
  construction: already-closed guard (`paper_exit_evaluator.py:1494-1509`),
  blocking-close-order filter (`filter_blocking_close_orders`,
  paper_exit_evaluator.py:601-689, #1046-aware), and the single-submitter
  rule (745ced4). First staged close wins; the second caller gets
  `skipped_duplicate`. The 15:30Z SPY double-submit on 06-12 (second
  submission rejected by the broker's intent check *after* the first filled)
  is the regression test scenario: with 745ced4 the second submission is
  classified terminal-duplicate and returns gracefully.
- The monitor remains authoritative for envelopes and force-close severity;
  the fast loop never writes envelope state.

## 6. Failure containment

- Own `job_runs` rows, own job name, own endpoint. No shared locks held
  beyond the per-position close staging instant. A fast-loop exception
  cannot block the monitor (different scheduler entries, different
  endpoints, stateless between ticks).
- Register `fast_exit_scan` in the ops_health OUTPUT_FRESHNESS registry
  (#1045 pattern): if the loop stops *running* during RTH, that is an
  alert, not silence.
- Self-disable breaker: N (suggest 5) consecutive failed cycles → stop
  firing for the session + one critical `risk_alerts` row. The 15-min
  monitor is the floor protection and is unaffected.

## 7. Rollout

- Flag `FAST_EXIT_LOOP_ENABLED` — behavioral/opt-in per §3 doctrine:
  requires exactly `=1`; absent/empty → loop does not run; non-empty
  non-`1` logs WARNING and does not run.
- Mode flag `FAST_EXIT_LOOP_MODE`: `observe` (default) → full mark +
  evaluate + #1034 observation rows + would-trigger WARNING logs, **no
  staging**; `act` → TP and stop staging live. Observe for ≥3 sessions;
  promote on zero false would-triggers against corroboration verdicts.
- Kill switch: unset the flag (reverts to 15-min-only). No code revert
  needed.

## 8. Effort estimate

- Loop job + endpoint + scheduler entry + flag plumbing: ~1 day (the body is
  a scoped re-composition of `_refresh_marks` + `_collect_intraday_exit_triggers`
  internals; factoring the shared core out of `IntradayRiskMonitor` is most
  of the work).
- #1034 width fix + Stage-2 TP enforcement (prerequisite, separate PR):
  ~0.5–1 day incl. regression tests against the 06-12 13:30Z observation row.
- Tests (flag polarity both ways, idempotent dual-fire, breaker): ~1 day.
- Total: **2–3 dev-days** + 3 observe sessions. One worker recycle per PR.
