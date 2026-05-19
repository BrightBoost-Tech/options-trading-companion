# Bugs Fixed — history

Full chronology of fixed bugs. CLAUDE.md keeps a 5-7 entry "Recently fixed (last 7 days)" condensed list; everything older lands here.

Entries are verbatim — when a fix moves out of the CLAUDE.md window, copy the entry as-is, do not edit for style.

## Last 30 days

- **2026-05-18 H9 legacy sweep 3-of-3 (PR #968):** Final genuine H9
  legacy candidate closed. `position_pnl_service.refresh_marks_for_user`
  (and `compute_group_nlv`) had 3 silent-swallow sites that matched
  H9 Anti-pattern 2 — `errors.append + logger.warning` with no
  `alert()`. Migrated all three to call the canonical `alert()` helper
  at severity `warning`, with `errors.append` and `logger.warning`
  preserved as secondary channels (typed-Result contract for callers
  + log visibility). Alert types: `position_pnl_mark_leg_failed`,
  `position_pnl_group_update_failed`, `position_pnl_compute_nlv_failed`.
  Allow-list shrunk 5 → 4 entries (remaining 4 are all chain-level-
  verified false positives or the analyzed-and-deferred
  `alpaca_order_sync.sync_orders` per `docs/sync_orders_analysis.md`).
  **BUG-A-safe finding:** the function's MTM math operates per-leg
  (each leg has its own `qty_current` and `avg_cost_open`); the
  scale-asymmetry shape that fired BUG-A in `intraday_risk_monitor`
  doesn't apply here structurally. **Dormant-subsystem framing:**
  function is part of the v4 PnL ledger subsystem — `position_legs`,
  `position_groups`, `position_leg_marks` exist but are empty; zero
  `job_runs` for `refresh_ledger_marks_v4` in 30 days; not wired to
  `scheduler.py`. Same operational shape as the Replay/forensic
  subsystem. The H9 migration is correct shape if/when the v4 ledger
  ever gets wired up; the wire-or-remove decision is deferred per
  the CLAUDE.md "v4-accounting playbook" framing. Files:
  `packages/quantum/services/position_pnl_service.py:184-186,192-194,282-287`;
  `packages/quantum/tests/h9_allow_list.yml` (entry removed);
  `CLAUDE.md` (new dormant-subsystem entry).
- **2026-05-18 staleness-gate over-tightening on routine regimes:**
  `ops_health_service.compute_market_data_freshness` per-symbol decision
  combined `snap.quality.is_stale` (vendor-quality flag set by
  `MarketDataTruthLayer.snapshot_many_v4` independent of timestamp age —
  vendor-quote-completeness / market-hours / quote-quality logic) OR
  `freshness_ms > stale_threshold_ms`. The vendor-quality clause
  frequently fires on SIP-entitled core symbols within minutes of data
  refresh — well below the 600s timestamp threshold. Combined with the
  SPY-or-QQQ override (line 582-584), this blocked entire entry cycles
  on routine-regime days. Forcing example: 2026-05-18 18:01:48 UTC
  paper_auto_execute block on a valid CSX micro-tier candidate
  (regime=NORMAL, freshness=108s, threshold=600s, SPY+QQQ both
  `is_stale=True` from vendor side). Fix: vendor-quality clause is now
  regime-conditional — active only in `shock` and `elevated` regimes
  (the regimes that also trigger sub-1.0 `regime_mult` per the Risk per
  trade math section). Other regimes (`normal`, `suppressed`, `chop`,
  `rebound`) fall back to timestamp-vs-threshold only. The
  `_resolve_regime_for_staleness` helper accepts an optional explicit
  regime; if None, it reads the last recorded regime from the most
  recent `suggestions_open` job_run's `cycle_results[0].cycle_metadata.regime`
  (PR #959 enriched writer); if that lookup yields nothing, fails closed
  with `shock`. SPY-or-QQQ override at line 582-584 PRESERVED — only the
  per-symbol decision was loosened. Files:
  `packages/quantum/services/ops_health_service.py:531-625`;
  `packages/quantum/risk/staleness_gate.py:35-89`.
- **2026-05-18 BUG-A scale-asymmetric unrealized_pl recompute:**
  `intraday_risk_monitor._refresh_marks` multi-leg branch computed
  `leg_total` per-1-spread (using `leg.quantity = 1` per the stored
  per-leg JSON convention) but `entry_value` per-N-spread (using
  `pos.quantity`, e.g. 4). For any multi-contract position the
  subtraction `leg_total - entry_value` produced a fabricated large
  loss. Today's CSX 4-contract debit spread (entry $2.50, current
  spread mid ~$2.20) computed unrealized_pl = $220 - $1000 = -$780
  within 5 seconds of opening, triggering immediate intraday
  stop_loss force-close. Fix: scale BOTH sides by `pos.quantity` in
  the same step (long: `(per_spread_value - per_spread_entry) ×
  qty_abs`; short: `(per_spread_entry - abs(per_spread_value)) ×
  qty_abs`); credit/debit branch preserved. Inline scale-consistency
  invariant comment defends against regression. Single-leg branch
  was already scale-consistent; no change there. Tier-transition
  blocker — at micro tier (contracts=1) the bug was invisible; at
  small tier with `PortfolioAllocator` (PR #958) emitting 2-4
  contracts, this fires on every multi-contract live position.
  File: `packages/quantum/jobs/handlers/intraday_risk_monitor.py:354-407`.
- **2026-05-18 BUG-C retry against already-closed position:** within a
  single `intraday_risk_monitor` cycle, after the first successful
  force-close the in-memory `positions` list (fetched once at line
  127) is stale. The violation loop in 5b iterates
  `result.force_close_ids` per force-close-severity violation;
  multiple loss-envelope violations against the same position
  produced 4 spurious retries today. Two idempotency checks
  (`intraday_risk_monitor._execute_force_close:462-489` and
  `paper_exit_evaluator._close_position:1000-1024`) omitted
  status='filled' from their status filter — internal-paper close
  orders fill synchronously, so the prior close was already 'filled'
  and the retry punched through. Neither check filtered by side, so
  adding 'filled' alone would also match the (filled) entry order.
  `_close_position` had no `status='closed'`/`quantity=0` early-return,
  so retries reached compute_realized_pl(qty=0) and raised. Fix
  (4 sub-fixes): (a) add 'filled' + 'cancelled' to both idempotency
  filters AND scope by close side (sell for long, buy for short);
  (b) add `status='closed' or quantity=0` early-return to
  `_close_position` returning `routed_to='already_closed'` (not an
  error, expected behavior — H9 verified-state check); (c) move
  position fetch ahead of idempotency check in `_close_position` so
  the side filter can use observed `quantity`; (d) track
  `closed_in_this_cycle` set in `intraday_risk_monitor` violation
  loop and skip subsequent iterations for already-closed positions.
  Files: `packages/quantum/jobs/handlers/intraday_risk_monitor.py:186-260,453-505`;
  `packages/quantum/services/paper_exit_evaluator.py:995-1115`.
- **2026-04-27 Polygon plan upgrade (#87 RESOLVED):** Stocks Basic
  ($0) → Stocks Starter ($29/mo); Options Basic ($0) → Options
  Developer ($79/mo). Total $108/mo recurring. Today's "chronic 429
  storm" was actually two stacked failures on Basic tier:
  (a) hard 5 calls/min/product cap, and (b) Basic tier lacked
  entitlements for the snapshot, Greeks, IV, and Open Interest
  endpoints used by the scanner — surfaced as `403 NOT_AUTHORIZED`
  on `/v3/snapshot` for KURA/AMZN options in worker logs. PR #823's
  H3 doctrine alerts (`polygon_circuit_open` × 46,
  `polygon_retries_exhausted` × 18 in 24h) gave us the diagnostic
  signal; the diagnostic narrative initially attributed it to
  cold-cache cycling but the underlying root cause was plan-tier
  insufficient + entitlements missing. No code change required —
  same API key, new entitlements propagate automatically. Tomorrow's
  16:00 UTC scheduled cycle is the validation window.
- **2026-04-27 universe-price filter for micro tier:** with the
  sizing fix landed (PR feat/micro-tier-90pct-single-position),
  the 19:16 UTC manual rerun proved the budget gate worked but
  produced 0 suggestions — only AMZN passed the scanner ($1247
  underlying, $1223 max_loss/contract), and $1223 > $450 micro
  budget. Root cause: ~80% of the 62-symbol universe is FAANG +
  high-priced ETFs whose contracts run $300-$1500; only sub-$50
  underlyings produce contracts that fit micro tier. Fix:
  `options_scanner._apply_tier_price_filter` drops symbols with
  underlying > $50 (configurable via `MICRO_TIER_MAX_UNDERLYING`
  env) for micro tier only. Inserted after the batch quote
  fetch, before per-symbol option-chain calls — saves Polygon
  API calls too. PR feat/85-micro-tier-universe-price-filter.
  Closes #85.
- **2026-04-27 sizing-layer override:** `RiskBudgetEngine` flat 3%
  balanced default silently shadowed `SmallAccountCompounder` tier
  math via `min()` at `workflow_orchestrator.py:2347`. With $500
  micro-tier capital, all 3 candidates (BAC/AMZN/AAPL) were vetoed
  at sizing because `max_risk_per_trade=$15` < single-contract risk
  ($286/$1248/$1274). Engine + compounder rewired tier-aware:
  micro = 90% × regime, one trade at a time; small/standard
  unchanged. `STRATEGY_TRACK` env now no-op for micro tier. Asymmetric
  concurrency gate (entries blocked when position open; exits continue).
  PR feat/micro-tier-90pct-single-position.
- `paper_learning_ingest` must be in cron — not just manual trigger
- OCC symbol format for Alpaca order submission
- Internal fills miscounted as Alpaca fills in green day logic (fixed + reset 2026-04-04)
- Polygon options data empty (plan lacks quotes) — Alpaca now primary for options (2026-04-08)
- MTM `_compute_position_value_from_snapshots` read `snap.get("bid")` instead of `snap.get("quote", {}).get("bid")` — fixed 2026-04-08
- 11 broker endpoints + 6 policy lab endpoints missing explicit `Depends(get_current_user)` — fixed 2026-04-09
- Deprecated `POST /tasks/iv/daily-refresh` stub accepting legacy X-Cron-Secret — removed 2026-04-09
- `calculate_portfolio_inputs()` was synchronous inside async optimizer endpoint — wrapped 2026-04-10
- Close orders missing `position_intent` — Alpaca inferred `buy_to_open` — fixed 2026-04-10
- Close orders on near-worthless spreads had negative `limit_price` — clamp to 0.01 (2026-04-10)
- `paper_exit_evaluate` 3 PM never fired — idempotency key collision with 8:15 AM (2026-04-10)
- Debit spread PoP used raw long-leg delta instead of breakeven-adjusted — fixed 2026-04-12
- Intraday risk monitor only checked portfolio-level envelopes, not per-position stops — fixed 2026-04-12
- Intraday stop_loss=True was gated behind `RISK_ENVELOPE_ENFORCE` — decoupled 2026-04-13
- `paper_auto_execute` had no symbol-level dedup (3-AMD bug) — fixed 2026-04-13
- `_close_position` multi-leg inversion read `leg.get("side")` but stored legs use `action` — fixed 2026-04-13
- Close orders rejected with `held_for_orders` — pre-cancel + idempotency guard (2026-04-15)
- Alpaca close orders filled but paper_positions never marked closed — `_close_position_on_fill` (2026-04-15)
- Calibration DTE_BUCKETS misaligned with post_trade_learning buckets — aligned 2026-04-16
- `compute_risk_adjusted_ev` called with empty `existing_positions` (3-AMD entry bug) — fixed 2026-04-16
- Sector concentration check used raw SIC strings — canonical GICS mapping 2026-04-16
- `ttl_snapshot` hardcoded at 10s — env-configurable via `SNAPSHOT_CACHE_TTL` (2026-04-16)
- `apply_calibration` multiplied PoP without output clamp — clamped to [0,1] 2026-04-16
- `loss_weekly` severity=warn at -190% — upgraded to force_close 2026-04-16
- `PROFIT_AGENT_RANKING` was a dead kill switch — retired 2026-04-16
- **2026-04-16 ghost-position incident:** 3 close orders filled on Alpaca but
  stuck in `needs_manual_review` due to retry loop treating Alpaca code
  42210000 "position intent mismatch" as retriable. Fixes: (a) `poll_pending_
  orders` now includes `needs_manual_review` in status filter when
  `alpaca_order_id` is set; (b) `submit_and_track` breaks on 42210000 — no
  duplicate retries; (c) new `ghost_position_sweep` gated on
  `RECONCILE_POSITIONS_ENABLED` for 48h observation (PR #764).
- **2026-04-16 weekly_pnl math:** `_compute_weekly_pnl` summed per-position
  EOD marks (not P&L deltas) including closed positions — produced -190%
  weekly on a real week-to-date of ~-1%. Fix: Alpaca-authoritative
  `get_account()` + `get_portfolio_history(1W/1D)` with per-user cache;
  caller skips envelope on None rather than fabricating equity (commit 83872db).
- **2026-04-16 calibration pnl_realized corruption:** 34 outlier rows from
  internal-paper era and early Alpaca-paper era (before 2026-04-13) produced
  cumulative +$95K P&L in learning_feedback_loops vs Alpaca lifetime -$3K.
  Fix: hard date floor (`CORRUPTED_PNL_FLOOR`) in calibration_service filters
  pre-2026-04-13 rows out of the fetch. Query-time only; source preserved.

## Historical bugs (pre-2026-04-01, summarized)

Approximately 20 fixes before the current 30-day window covered:
- Scheduler heartbeat + never-run alert escalation
- Calibration DTE-bucket segmentation
- Risk-envelope circuit breaker (auto-execute blocks on breach)
- Multi-strategy scan caching reuse
- Debit spread stop-loss widening 20% → 50%
- Directional bid/ask pricing on spread legs (sell@bid, buy@ask)
- Option chain cache TTL 300s (env-configurable)
- Alpaca retry: 10 retries, exponential backoff, 90s watchdog, needs_manual_review fallback

Full chronology lives in git history; search commits from 2026-03 and earlier.
