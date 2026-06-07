# Options Trading Companion — Project Context
# Loaded by Claude Code on EVERY turn. Keep this current.

For new-contributor onboarding, see README.md. For AI session context, this file is loaded every turn.

---

## Identity & Repo

- **Repo:** BrightBoost-Tech/options-trading-companion
- **Owner User ID:** 75ee12ad-b119-4f32-aeea-19b4ef55d587
- **Stack:** Python 3.11 / FastAPI backend (`packages/quantum`) · Next.js frontend (`apps/web`) · Supabase Postgres · Railway deploy · APScheduler (primary) · GitHub Actions (fallback) · Alpaca broker + market data (primary) · Polygon.io (Stocks Starter + Options Developer, $108/mo; de facto primary for snapshots/bars where the Alpaca paper account lacks SIP entitlement)

---

## Current Phase

- **Phase:** `micro_live` (operator-set documentation label, flipped 2026-04-25 17:10:36Z). It is **NOT** a valid EXECUTION_MODE value, and it does **NOT** govern capital tier (tier is resolved purely by `get_tier(deployable_capital)`). The `CURRENT_PROGRESSION_PHASE` env only gates the IRON_CONDOR phase-aware exclusion at `strategy_selector.py:375`.
- **EXECUTION_MODE env:** one of `internal_paper`, `alpaca_paper`, `alpaca_live`, `shadow`. Live trading also requires `LIVE_ENABLED=true` (second-stage safety at `execution_router.py:88-94` falls back to `alpaca_paper` otherwise).
- **Promotion type:** manual operator-initiated. Green-day gate (1/4) bypassed; continuous-growth model. Audit `risk_alerts.id = 82f1c294-19a4-4c66-8a68-0b0811ef5b24`.
- **Account:** live Alpaca `211900084`, options Level 3. Starting capital $500 on `v3_go_live_state.paper_baseline_capital` (2026-04-25, audit `c9d87caf-24db-4f7f-842a-748620a5c84f`). **Current equity ~$2,283 → see Live State.**
- **daily_progression_eval:** 16:00 CT. alpaca_paper → micro_live gate bypassed (operator-initiated). Future phase transitions deferred under continuous-growth model.
- **Auto-promotion gates (micro_live → full_auto):** `promotion_check` auto-promotes when ALL pass — (1) broker equity ≥ $1500, (2) cumulative_realized_pl > 0 across Alpaca-real closed trades, (3) alpaca_real_trade_count ≥ 3. Manual override (`ProgressionService.promote(...)`) preserved as bypass. **Note: equity (~$2,283) clears gate (1); gates (2)/(3) still bind — the 2026-06-04 live NFLX entry will count toward (2)/(3) when it closes.**
- **Iron condors:** enabled by pool construction; triggered by `strategy_selector.get_candidates` when regime=CHOP, or sentiment NEUTRAL/EARNINGS with high IV (iv_rank>50 or ELEVATED/SHOCK/REBOUND). Recent regimes NORMAL+directional → IC pool empty → debit spreads dominate (regime-driven natural selection; empirically 52 ICs in 90d at CHOP, 0 at NORMAL — by design). Phase-aware exclusion at `strategy_selector.py:372-387` excludes IRON_CONDOR when `CURRENT_PROGRESSION_PHASE=alpaca_paper`; currently DORMANT (phase=micro_live).
- **Calibration job:** daily 05:00 CT → `calibration_adjustments`.
- **Risk profile:** tier-aware, capital-driven (see "Risk per trade math"). Tier is now SMALL (equity ~$2,283 > $1,000 cliff) — see Live State for the concrete small-vs-micro deltas.
- **Universe:** 74 active. Recent adds: KHC (PR #976), SNAP/RIVN/NIO/MARA (2026-05-21, sub-$30, 4 sectors); FISV deactivated 2026-05-19 (corp action). Audit rows `2c91a730-b4be-4b7e-9433-630be9ddb1d2` (KHC), `a23461cc-3661-45b7-96cb-e7a13dd0779f` (batch). The 4 newest lack α IV backfill (debit spreads emit at `iv_rank=50` default; credit/IC defer).
- **Pipeline:** full end-to-end validated 2026-04-10.
- **Phase 2 contract:** enforced — `check_close_reason_enum` (9 values), `check_fill_source_enum`, `close_path_required` constraints intact.

---

## Infrastructure

| Service | URL / Location |
|---|---|
| Backend (Railway) | https://be-production-48b1.up.railway.app |
| Frontend (Railway) | https://fe-production-d711.up.railway.app |
| Worker (Railway) | worker.railway.internal — RQ queue `otc`, start `rq worker otc` |
| Worker-background (Railway) | worker-background.railway.internal — RQ queue `background`, start `rq worker background` (2026-05-16) |
| Supabase project | etdlladeorfgdmsopzmz.supabase.co |
| GitHub Actions | Manual dispatch only (APScheduler is primary) |

**Worker queue topology (2026-05-16):**
- **`otc` (primary):** all trading-day pipeline jobs — `suggestions_open`, `suggestions_close`, `paper_auto_execute`, `paper_exit_evaluate`, `intraday_risk_monitor`, `iv_daily_refresh`, `alpaca_order_sync`, etc. Default for `enqueue_job_run(...)`.
- **`background` (worker-background):** long-running jobs that would starve the primary queue. Currently routes only `iv_historical_backfill`. Future long-running handlers route here via `queue_name=BACKGROUND_QUEUE`.

### Key Environment Variables (Railway backend unless noted)
| Variable | Value | Purpose |
|---|---|---|
| EXECUTION_MODE | `alpaca_paper` | Phase selector (paper/micro_live/live) |
| SCHEDULER_ENABLED | `1` | APScheduler (primary scheduler) |
| ORCHESTRATOR_ENABLED | `1` | Autonomous Day Orchestrator |
| CALIBRATION_ENABLED | `1` | Master switch for calibrated EV/PoP |
| RISK_ENVELOPE_ENFORCE | `1` | Force-close enabled (warn-only → enforce 2026-04-16) |
| RANKER_PORTFOLIO_AWARE | `1` | Canonical ranker sees open positions |
| CANONICAL_RANKING_ENABLED | `1` | Risk-adjusted EV sort |
| COMPOUNDING_MODE | `true` | 8% base risk + 1.2× boost for micro tier |
| RISK_MAX_SYMBOL_PCT | `0.40` | Paper phase — tighten to 0.30 at micro_live |
| RISK_MAX_DAILY_LOSS | `0.08` | 8% daily loss cap |
| RISK_MAX_WEEKLY_LOSS | `0.10` | 10% weekly loss cap |
| SNAPSHOT_CACHE_TTL | `120` | Seconds; env-configurable |
| OPTION_CHAIN_CACHE_TTL | `300` | Option chain cache TTL |
| ALPACA_API_KEY / ALPACA_SECRET_KEY | set | Alpaca credentials |
| ALPACA_PAPER | `true` | Route to paper endpoint |
| TASK_NONCE_PROTECTION | `1` | Security v4 nonce replay protection |
| TASK_NONCE_FAIL_CLOSED_IN_PROD | `1` | Fail closed if nonce store unavailable |
| TASK_SIGNING_KEYS | set | HMAC keys for /tasks/ endpoint signing |

### Critical env var: paper-vs-live mode

TWO similarly-named vars control different layers — **BOTH must be `false` for live trading**; setting only one yields a split-brain state:
- **`ALPACA_PAPER`** (Railway BE/worker): read by `packages/quantum/brokers/`; routes the trading service to paper vs live Alpaca. Currently `false` post-promotion.
- **`ALPACA_PAPER_TRADE`** (alpaca-mcp-server, `.claude.json` env): read by the alpaca-mcp-server lib to pick endpoint URL (`paper-api` vs `api`.alpaca.markets). Defaults `"true"` if unset.

Verified 2026-04-25 by reading alpaca-mcp-server source.

### Alpaca live key prefix gotcha

Live Trading API keys for this account use the **AK** prefix (public docs say `PK`; some accounts use `AK`) — confirmed working 2026-04-25. The reliable live-vs-paper distinction is the **endpoint**, not the key prefix: `api.alpaca.markets` = live, `paper-api.alpaca.markets` = paper. **Paper creds for account `PA3I8CYLXBOS` live in the Railway worker env (`ALPACA_PAPER_API_KEY` / `ALPACA_PAPER_SECRET_KEY`) — Railway is the source of truth for the current values. Do not pin a paper-key prefix here — pinning one is exactly what drifted; the executor's runtime `assert_paper_account` guard verifies the account, not the doc.**

### Flags in use — single source of truth

**Permanently on** (do not flip without a code change): `TASK_NONCE_PROTECTION=1`, `TASK_NONCE_FAIL_CLOSED_IN_PROD=1`, `SCHEDULER_ENABLED=1`, `ORCHESTRATOR_ENABLED=1`, `CALIBRATION_ENABLED=1`, `RISK_ENVELOPE_ENFORCE=1`, `RANKER_PORTFOLIO_AWARE=1`, `CANONICAL_RANKING_ENABLED=1`, `MULTI_STRATEGY_EVAL=1`, `COMPOUNDING_MODE=true`, `PAPER_AUTOPILOT_ENABLED=1`, `POLICY_LAB_ENABLED=true`, `ALLOCATION_V4_ENABLED=true`, `FORECAST_V4_ENABLED=true`, `OPTIMIZER_V4_ENABLED=true`, `SURFACE_V4_ENABLE=true`, `SHADOW_CHECKPOINT_ENABLED=1`.

**Dead / reserved flags:** `REGIME_V4_ENABLED` — **set `true` in the worker env but read by NOTHING in production** (2026-06-07 census: its only reader is `regime_engine_v4.is_regime_v4_enabled()`, which has zero production callers). `RegimeEngineV4` (continuous-vector, accepts vix_data, falls back to SPY RV) is BUILT BUT UNWIRED; the live regime path is `RegimeEngineV3` everywhere. The flag is the reserved activation gate for a future deliberate V4 wiring (likely the vol-signal arc) — until then its env value is a no-op; do NOT infer V4 behavior from it. Pinned by `test_regime_v4_unwired.py` (wiring V4 forces a test+doc update). The env var may be removed from Railway or left — harmless either way.

**Permanently off:** `AUTOTUNE_ENABLED=false`, `POLICY_LAB_AUTOPROMOTE=false`, `PDT_PROTECTION_ENABLED=0` (PDT rule retired 2026-06-04 — never flip ON), `ALPACA_DRY_RUN=0`, `ENABLE_DEV_AUTH_BYPASS=0`.

**Kill switches** (flip to disable instantly): `SCHEDULER_ENABLED`, `CALIBRATION_ENABLED`, `RISK_ENVELOPE_ENFORCE`.

**Lever / observe flags (operator-flipped; state as of 2026-06-04):**
- `INTRADAY_TARGET_PROFIT_ENABLED` = **`1` (ON)** — 15-min intraday profit capture, **PROVEN** (closed the shadow BAC `target_profit_hit` 2026-06-04 16:45Z, first run after arming). **⚠️ STRICT `== "1"` parsing — setting it to `true` silently no-ops** (this happened 2026-06-04; re-set to `1`). Most other flags accept `1/true/yes/on`.
- `H7_PREFILTER_ENABLED` = `true` (active mode, post-shadow-validation).
- `REGIME_FILTER_OBSERVE_ENABLED` = `true` (D4 observe-logging, flipped 2026-06-03).
- `GTC_PROFIT_EXIT_ENABLED` = OFF (lenient parse; deliberate watched enable pending — competes with intraday TP).
- `MARKETABLE_ENTRY_ENABLED` = OFF (observe mode — would-be decisions logged).
- `LIQUIDITY_WEIGHTING_ENABLED` = OFF/absent (observe-first; graduation pending correlation data).
- `PAPER_SHADOW_EXECUTOR_ENABLED` = `false` (Phase 1b pending; `paper_shadow_pairs` table still unapplied).
- `REGIME_V4_ENABLED` = `true` in env but **DEAD — gates nothing** (see "Dead / reserved flags" above; distinct from the D4 observe filter). The v3 engine file reported `ENGINE_VERSION="v4"` until the 2026-06-07 naming-collision fix — it now reports `v3`; `v4_continuous` is the unwired `RegimeEngineV4`.

---

## Architecture (v4 — 16 Layers + 4 Managed Agents)

Layers: 1 Market Data (Alpaca primary by design; Polygon de facto primary for paper-account paths) · 2 Backtesting · 3 Observability · 4 Security · 5 Regime Engine · 6 Forecast · 7 Capital Allocation · 8 Optimizer/Suggestion Engine · 9 Execution (Alpaca) · 10 Risk & Capital · 11 Learned Nesting · 12 Automation · 13 Quant Agents · 14 UI/UX (Next.js) · 15 Quantum · 16 Regression/Determinism Bot.

### Managed Agents
| Agent | Trigger | Purpose | agent_sessions? |
|---|---|---|---|
| Day Orchestrator | 7:30 AM CT | Boot check, missed-job detection | ✅ |
| Loss Minimization | Every 15 min, market hours | Intraday envelope monitoring + force-close | ✅ (since 2026-05-04) |
| Self-Learning | 4:45 PM CT | Post-trade calibration + drift detection | ✅ (since 2026-05-04) |
| Profit Optimization | apply_calibration during suggestions | Calibrated EV/PoP from learned adjustments | ❌ per-call fn — deferred (would touch `workflow_orchestrator.py`, highest blast radius) |

### Dormant subsystems (gated off; evaluate after micro_live stabilizes — wire up or remove per v4-accounting playbook)

- **Replay / forensic** (`data_blobs`, `decision_runs`, `decision_inputs`, `decision_features`; `services/replay/`): gated off via `REPLAY_ENABLE=0`. Post-incident forensics. Not active.
- **v4 PnL ledger** (`position_legs`, `position_groups`, `position_leg_marks`; `services/position_pnl_service.py` + handlers `refresh_ledger_marks_v4.py` / `run_market_hours_ops_v4.py`): not wired to `scheduler.py`; zero rows / zero `job_runs` in 30d. H9-compliant since PR #968.

---

## Market Data Provider Routing

| Data Type | Primary | Fallback |
|---|---|---|
| Options snapshots (MTM) | Alpaca `/v1beta1/options/snapshots` | Polygon `/v3/snapshot` |
| Option chains (scanner) | Alpaca `/v1beta1/options/snapshots/{underlying}` | Polygon `/v3/snapshot/options/{underlying}` |
| Equity snapshots | Alpaca `/v2/stocks/snapshots` | Polygon `/v3/snapshot` |
| Daily bars (IV rank, trend) | Alpaca `/v2/stocks/bars` | Polygon `/v2/aggs` |
| Equity quotes (NBBO) | Alpaca `/v2/stocks/quotes/latest` | Polygon `/v2/last/nbbo` |
| Equity prev close | Alpaca `/v2/stocks/snapshots` (prev_daily_bar) | Polygon `/v2/aggs/prev` |
| Earnings dates | Polygon `/vX/reference/financials` | — |
| Historical contracts | Polygon `/v3/reference/options/contracts` | — |
| Account equity | Alpaca `get_account()` | — (skip loss envelopes if unavailable) |
| Weekly P&L | Alpaca `get_portfolio_history(1W/1D)` | — (skip weekly envelope) |

**Runtime note (2026-04-27):** Primary/Fallback above is design intent. Alpaca paper accounts lack SIP entitlement (`subscription does not permit querying recent SIP data` on equity bars), so many calls fall through to Polygon. The Polygon plan upgrade makes this de facto path durable. SIP-gap resolution depends on live Alpaca entitlements (backlog #88).

---

## Daily Cron Pipeline (APScheduler — primary)

```
5:00 AM   calibration_update
7:30 AM   day_orchestrator (boot check)
8:00 AM   suggestions_close → 8:15 paper_exit_evaluate (morning)
9:30-4:00 alpaca_order_sync (every 5 min) + intraday_risk_monitor (every 15 min)
11:00 AM  suggestions_open → 11:30 paper_auto_execute
3:00 PM   paper_exit_evaluate (afternoon) → 3:30 paper_mark_to_market
4:00 PM   daily_progression_eval → 4:10 learning_ingest → 4:20 paper_learning_ingest
4:30 PM   policy_lab_eval → 4:45 post_trade_learning
5:00 PM   promotion_check
```

- `paper_learning_ingest` MUST run after exits close each day or the learning view stalls; `post_trade_learning` runs after `learning_ingest` to close the feedback loop.
- GitHub Actions `trading_tasks.yml` is fallback (manual dispatch only).
- **Weekend behavior (Mon-Fri only):** all scheduled jobs apply `day_of_week='mon-fri'` uniformly (`scheduler.py:212-217`; `auto_retry_failed` at 236-248). Sat/Sun silence is expected. Operator HTTP triggers via `scripts/run_signed_task.py` work over weekends. When investigating weekend silence, confirm Mon-Fri scheduling before assuming outage.

---

## Testing & CI

- **Python 3.11 required** (3.14+ incompatible via `qci-client`; sentinel in `packages/quantum/__init__.py`).
- **CI** `.github/workflows/ci-tests.yml` runs `pytest packages/quantum/tests/` on every push/PR. Green required; no merge to main until green (branch-protection enforced).
- **Every code PR must include regression tests for any bug it fixes.**
- **Test deletion discipline:** when removing production code, the PR description must state which tests are deleted and confirm no retained surface is exercised by them. If a test covers both removed and retained surface, split the file before deletion.

---

## Migrations

Supabase migrations do NOT auto-apply on merge. Full procedure at `docs/migration_procedure.md`.

---

## Key Database Tables

| Table | Purpose |
|---|---|
| `paper_positions` | Open/closed paper positions |
| `paper_orders` | Order fills (execution_mode: internal_paper or alpaca_paper) |
| `go_live_progression` | Current phase + green days count (canonical) |
| `go_live_progression_log` | Audit trail of phase events |
| `v3_go_live_state` | Older readiness table — still written by validation_shadow_eval |
| `policy_lab_cohorts` | 3 active cohorts (conservative / moderate / aggressive) |
| `learning_trade_outcomes_v3` | VIEW: realized P&L joined with suggestions |
| `learning_feedback_loops` | Raw outcome records from paper/live ingest |
| `calibration_adjustments` | EV/PoP multipliers (JSONB `adjustments` keyed by segment) |
| `paper_eod_snapshots` | Daily MTM marks per position |
| `job_runs` | Job execution log (idempotency + status) |
| `risk_alerts` | Risk violations, force-close events, drift alerts |
| `policy_decisions` | Per-cohort accept/reject decisions with realized_outcome |
| `agent_sessions` | Managed Agent observability (Day Orch + Loss Min + Self-Learning write; Profit Optimization deferred) |
| `universe_selection_log` | Per-call audit of `UniverseService.get_scan_candidates` (selected + dropped symbols, thresholds, caller). Forward-only since 2026-05-20. |

### Instrumentation coverage (per-cycle writes for observability; post-2026-05-18/05-21 fixes)

Each `suggestions_open` cycle writes:
- **`job_runs.result`** — `counts.{universe_size, scanner_emitted, trade_suggestions_created, h7_passed, edge_above_minimum, executable, staged, candidates, created, existing, rejection_persist_failures}` + `cycle_metadata.{regime, tier, open_position_count, available_envelope_dollars, deployable_capital, exit_reason, h7_prefilter_dropped, h7_prefilter_mode}`. Emitted at ALL 7 return paths of `run_midday_cycle` via `_build_cycle_metadata` / `_build_enriched_counts`; pre-funnel exits emit `None` for unmeasured fields (H9 early-exit symmetry).
- **`suggestion_rejections`** — one row per `RejectionStats.record()` inside a `set_symbol()` context (`RejectionStats` constructed in `options_scanner.scan_options()`, ~`options_scanner.py:2346`). Fail-soft; failure count surfaces via `rejection_persist_failures`.
- **`paper_orders.submitted_at` + `filled_at`** — internal-fill close path (`paper_exit_evaluator.py:~1270`) writes BOTH; for internal fills `submitted_at == filled_at` is intentional. Alpaca-path submissions write `submitted_at` upstream.
- **`universe_selection_log`** — one row per `UniverseService.get_scan_candidates` (`total_active`, `limit_applied`, selected/dropped counts + symbol arrays, `score_threshold`, `score_at_cutoff`, `metadata.caller`). Callers: `options_scanner.scan_for_opportunities` (limit=50), `iv_daily_refresh.run` (limit=200). H9-verified writer (`universe_selection_log_write_failed` on failure; return value unaffected).

### Quick Health Check SQL
```sql
-- Phase status
SELECT current_phase, alpaca_paper_green_days, alpaca_paper_last_green_date FROM go_live_progression;

-- Open positions (authoritative: must match Alpaca get_all_positions())
SELECT symbol, quantity, avg_entry_price, current_mark, unrealized_pl, status
FROM paper_positions WHERE status = 'open' ORDER BY created_at DESC;

-- Today's job runs
SELECT job_name, status, finished_at FROM job_runs WHERE created_at::date = CURRENT_DATE ORDER BY created_at;

-- Risk alerts (last 24h) — H11 baseline: always include critical/high independent of hypothesis
SELECT alert_type, severity, symbol, message, created_at FROM risk_alerts
WHERE created_at > NOW() - INTERVAL '24 hours' ORDER BY created_at DESC;

-- Latest calibration adjustments (JSONB blob keyed by segment)
SELECT computed_at, total_outcomes, jsonb_object_keys(adjustments) AS segment
FROM calibration_adjustments ORDER BY computed_at DESC LIMIT 5;
-- Drill a segment: SELECT computed_at, adjustments->'LONG_CALL_DEBIT_SPREAD:normal:0_21' FROM calibration_adjustments ORDER BY computed_at DESC LIMIT 3;

-- Today's learning outcomes (closes only; filter predates 2026-04-13 pnl-corruption cutoff — see docs/bugs_fixed_history.md)
SELECT COUNT(*), ROUND(AVG(pnl_realized),2) FROM learning_feedback_loops
WHERE outcome_type='trade_closed' AND created_at >= '2026-04-13' AND created_at::date = CURRENT_DATE;

-- Agent sessions (Day Orch + Loss Min + Self-Learning write; Profit Optimization deferred)
SELECT agent_name, status, COUNT(*), MAX(started_at) FROM agent_sessions
WHERE created_at > NOW() - INTERVAL '24 hours' GROUP BY agent_name, status ORDER BY agent_name, status;
```

---

## Cohort architecture

3 cohorts (conservative / neutral / aggressive). Live routing reads `policy_lab_cohorts.promoted_at` via `policy_lab/champion.py::get_current_champion` (defensive fallback to `"aggressive"` in transition windows). `promoted_at` set on `aggressive` per operator intent (migration `20260518000001_promote_aggressive_cohort.sql`, correcting a 2026-04-02 manual neutral). The 2 prior silent-failure `is_champion` sites (`paper_autopilot_service._get_champion_portfolio`, `paper_exit_evaluator._resolve_position_cohort` path 3) now query `promoted_at` (H9 anti-pattern eliminated). Full architecture + sizing duality + seam-closure: `docs/cohort_architecture.md`; doctrine `docs/loud_error_doctrine.md` H13.

---

## Risk per trade math

Tier-aware. Single producer of `max_risk_per_trade`: `RiskBudgetEngine.compute_budgets()`, mirroring `SmallAccountCompounder.calculate_variable_sizing`. **Keep the two layers in sync — change one, change the other.** Tier resolved by `get_tier(deployable_capital)` (capital-based; NOT phase-based).

### Tier definitions

| Tier | Capital | Per-trade base | Multipliers | max_trades | Notes |
|---|---|---|---|---|---|
| micro | $0–$1000 | **90%** | regime only | **1 (one at a time)** | |
| small | $1k–$5k | **3% base / allocation-aware** | full stack via PortfolioAllocator + score_skew | **4** | see `docs/small_tier_allocation.md` |
| standard | $5k+ | 2% | full stack | 5 | |

**Hard cutoff at $1000** — no interpolation. `regime_mult`: 1.0 normal · 0.9 suppressed · 0.8 elevated · 0.5 shock · 1.0 chop · 1.0 rebound.

- **Micro:** `final_risk_pct = 0.90 × regime_mult`. Score/compounding bypassed (operator spec 2026-04-27); `STRATEGY_TRACK` has no effect (tier-aware branch precedes the risk_profile switch).
- **Small** (allocation-aware, post-2026-05-18): per-trade flows through `PortfolioAllocator`, which distributes capital across the viable candidate set in one cycle. Global envelope `0.85 × regime_mult × total_equity` (less open cost basis); per-candidate base `0.85 / n_candidates` (`n_candidates = min(viable, 4)`); score skew `clamp(0.8 + (score − median)/50 × 0.4, 0.8, 1.2)`; **per-trade ceiling 36% of equity** (binding in single-candidate case). 5 worked examples in `docs/small_tier_allocation.md`.
- **Standard:** full stack `base × score_mult × regime_mult × compounding_mult`; `score_mult = clamp(0.8 + (score − 50)/50 × 0.4, 0.8, 1.2)` (50→0.80, 75→1.00, 100→1.20); no compounding boost.
- **Compounding-off override** (small tier only): with `COMPOUNDING_MODE=false`, small-tier falls back to legacy 2% base if the allocator is bypassed (test envs). Production small-tier always goes through the allocator; micro ignores the flag.

**Allocator wiring:** `PortfolioAllocator` runs once per entry cycle (candidate set + equity + regime + open positions → per-candidate budgets). `RiskBudgetEngine` and `SmallAccountCompounder` accept optional `allocation_hint`; when present (small-tier production), it overrides the legacy multiplier stack. PR #958 shipped the allocator; PR (2026-05-21 wiring) threaded the hint from `workflow_orchestrator` + added the defensive `allocator_hint_dropped` alert. Full spec: `docs/small_tier_allocation.md`.

### Concurrency policy (micro tier — asymmetric by design)

- **Midday (entries):** blocks new entries when any position is open → `skipped=True, reason='micro_tier_position_open'`.
- **Morning (exits):** continues normally with a tier observation log line. Gating it would dead-lock exit generation for open positions.

The "one trade at a time" rule applies to **acquisition**, not management. A PR that "fixes" the asymmetry by gating the morning cycle would break exit auto-generation — `test_workflow_orchestrator_micro_concurrency.TestMorningCycleNoConcurrencyGate` defends against that. **Note:** at the current small tier (`max_trades=4`) the micro one-position gate does not fire; this doctrine remains load-bearing for any return to micro and for the morning-cycle no-gate invariant (which is tier-independent).

### Per-symbol risk envelope (live trading)

Under live-equity EXECUTION_MODEs (`alpaca_live`, `alpaca_paper`), the intraday monitor enforces a per-symbol stop = `RISK_MAX_SYMBOL_LOSS` (default `0.03` = 3%). Illustrative: on $500, 3% = $15 / 5% = $25; on current ~$1,635 equity, 3% ≈ $49. **Expected operational behavior:** frequent intraday force-closes on small adverse moves; per-trade losses small; round-trip Alpaca fees ~$1-2; each same-session force-close increments the PDT day-trade counter.

**Day-trade / PDT awareness (OBSOLETE as of 2026-06-04 — see "PDT Regime Change" below):** the 3-in-5 day-trade cap and PDT designation no longer exist; same-session force-close round-trips cost only fees (~$1-2). **Operator lever unchanged:** `RISK_MAX_SYMBOL_LOSS` — tighter (3%) = more force-closes / smaller losses; looser (5%) = fewer / larger losses but more survival.

Full worked examples, global per-tier allocation, universe price-filter rationale, history: `docs/risk_math.md`.

---

## PDT Regime Change (2026-06-04)

SEC-approved FINRA Rule 4210 amendment **eliminated the PDT designation, the $25k minimum, and day-trade counting, effective 2026-06-04**. **Alpaca implemented the same day** (new Intraday Margin Framework) → live `211900084` is **UNCAPPED** on same-day round trips; the constraint is now intraday margin exposure, which a cash-secured defined-risk spread book never strains (H7 round-trip BP + allocator budgets + the BP safety check ARE the relevant guards — no new intraday-margin engine needed at this tier).

- **`pattern_day_trader` / `daytrade_count` API fields are now documented PLACEHOLDERS** (false / 0), **REMOVED entirely by ~2026-07-06**.
- **⚠️ P0 (deadline 2026-07-06):** None-preserving coercion in `alpaca_client.get_account()` — `:221 int(acct.daytrade_count)` raises `int(None)` when the field is removed, **breaking get_account() for ALL consumers** (equity_state → risk envelopes, progression_service, broker endpoints). Also `get_day_trade_count()` (:245) and `is_pdt_restricted()` (:241). The `options_buying_power` None-preserving pattern at `:203-211` is the in-file precedent. Full audit (PDT-SPECIFIC vs ENTANGLED classification, sequenced retirement plan): 2026-06-04 PDT audit in the session transcript / `docs/backlog.md`.
- All internal PDT logic is **dormant** (`PDT_PROTECTION_ENABLED=0`, never flip ON — it would enforce a retired rule). Entangled pieces NOT to blanket-delete: `pdt_guard_service.is_emergency_stop` (capital protection) + `is_same_day_close` (generic utility) — both imported unconditionally by the live exit path.
- **Reframe:** PDT was never the frequency bottleneck — liquidity + the 36% per-trade ceiling are (the EV-vs-H7 finding). The elimination removes a *doctrinal* constraint (day-trade conservation), not a binding one.

---

## Polygon dependency

63 production calls across 23 files; 11 services with direct dep. Plan: Stocks Starter + Options Developer ($108/mo); #87 resolved at plan-tier level (2026-04-27). Tier 1/2/3 phase-out deferred (provider-redundancy / lock-in mitigation only). Full status: `docs/polygon_dependency.md`.

---

## 5 Open Code Gaps (priority order)

- **GAP 1** — Canonical ranking metric: expected PnL after slippage/fees ÷ marginal risk, adjusted for correlation/concentration. DynamicWeightService lays groundwork; full impl pending.
- **GAP 2** — EV-aware exit ranking: close worst marginal-EV positions first.
- **GAP 3** — Score/PoP/EV calibration vs realized outcomes by strategy/regime/DTE/liquidity. Partially live via Self-Learning Agent.
- **GAP 4** — Autotune: replace threshold mutation with walk-forward validation.
- **GAP 5** — Production security flags (set in Railway env, not code). Deployed 2026-04-09.

---

## Promotion Path

```
paper → micro_live ($500–$1K, Alpaca, 5 days) → live ($2.5–$5K, 30 days) → full
```
Gate to `micro_live`: 4 consecutive Alpaca paper green days (not internal fills).

---

## NEVER DO

- **Never merge a code-change PR without CI green.** Fix or skip-with-tracking-issue before other work.
- **Never add a new `@pytest.mark.skip`** without: (a) tracking issue with unskip criteria, (b) issue number in the reason string, (c) reviewer approval. Skip count must trend down.
- **Never write `paper_positions.status='closed'` directly.** Use the canonical close helper (duplicate close-order logic is the 2026-04-10→04-15 bug class).
- Count `internal_paper` fills as green days — Alpaca fills only.
- Enable iron condors during `alpaca_paper` phase.
- Rebuild the entire system prompt on every AI call (split static/dynamic).
- Start a new Claude Code session without `--continue` on this project.
- Use ChatGPT mid-build — architecture decisions live here; mixing tools creates drift.
- Deploy without verifying `TASK_NONCE_PROTECTION=1` in Railway.
- Touch `intraday_risk_monitor.py` or the `risk_alerts` migration without reading this file.
- Enable `PROFIT_AGENT_RANKING=1` — retired 2026-04-16, ignored by code.
- Fabricate equity or weekly_pnl when Alpaca is unavailable — skip the envelope with a warning (pattern in `_check_user` post-83872db).

---

## Bugs Fixed

Entries >7 days old are appended verbatim to `docs/bugs_fixed_history.md` (PR hygiene). The **2026-05-18 batch is archived there**: #968 (H9 sweep 3/3), H9 sweep 2/3 + `iv_point_service` dead-code delete, #62a-D1 cohort seam, H9 AST gate strict-mode flip, staleness-gate regime-conditional, BUG-A scale-asymmetric unrealized_pl + BUG-C retry-against-closed (`intraday_risk_monitor`/`paper_exit_evaluator`).

### Recent (not yet 7-day-archived)

**2026-06-02→04 PR ledger — the live-fill / exit-mechanics arc:**

- **#1014 risk-scope shadow-contamination fix** — MERGED, **VALIDATED in prod both ways** (alert path: phantom BAC concentration alerts 19→0 at the 06-02 19:09Z deploy; block path: 06-03/04 live entries permitted past the risk layer despite the shadow BAC). `risk/position_scope.py` = the canonical live-book filter for any new live-capital consumer.
- **#1015 liquidity-aware universe** — MERGED, observe-first, flag `LIQUIDITY_WEIGHTING_ENABLED` OFF. Hook confirmed firing (`option_liquidity_observations`; OPTION-spread liquidity, distinct from equity liquidity; first directional read: low scores line up with `spread_too_wide_real` rejections). **GRADUATION PENDING** — correlation validation → flip flag.
- **#1017 shadow-fill realism** — MERGED. Cohort shadow books fill via the TCM simulator, which filled 100%-at-exact-mid (price bias ≤5% + DOMINANT selection bias: shadow 100% vs live ~12% fill). Fix: fallback fills adverse-of-mid via stored `expected_spread_cost_usd` + `would_be_live_marketable` label (LABEL not gate — volume preserved). Isolation invariant: writes the fill RESULT only, never `requested_price`. Legacy rows segregable by absent `fill_model`.
- **#1018 marketable-entry lever** — MERGED, flag `MARKETABLE_ENTRY_ENABLED` OFF (observe mode logs would-be decisions to `tcm.marketable_entry`). High-EV gate (net EV ≥ K× actual cross, K=3 default), cross-toward-natural capped AT natural, budget recheck at the marketable price, **no-quote→passive-mid fallback** (the live NFLX's first real record hit exactly this fallback — Polygon leg-quote failure).
- **#1019 watchdog honesty** — MERGED, doc-only. `IDLE_WATCHDOG_SECONDS=90` is a threshold polled on the sync cadence (effective ~5-6 min); "cancel and resubmit" was vaporware (cancel-only); and per the GTC diagnostic, **"GTC" existed only as rationale text — no production order had ever been GTC**.
- **#1021 GTC resting profit-limit** — MERGED, flag `GTC_PROFIT_EXIT_ENABLED` OFF. TIF plumbing (`order_json.time_in_force`, default day) + `services/gtc_profit_exit.py` (close limit = entry × (1 + cohort flat tp)) + **watchdog TIF-exemption** (mandatory — GTC orders are supposed to rest) + OCO both ways (**found+fixed inverse-OCO bug:** a parked GTC close order would have satisfied the close-idempotency guards and permanently disarmed stop/envelope force-closes — guards now exclude `gtc_profit_exit` rows via `filter_blocking_close_orders`). **Closing+credit GTC shape PAPER-VALIDATED 2026-06-04** (#908-adjacent; accepted/rested/cancelled on `PA3I8CYLXBOS`). **Flat-cohort only** (a static resting price cannot time-scale). Competes with poll-side intraday TP — choosing is a pending operator decision.
- **#1022 fresh-mark close-staging fix** — MERGED-pending-deploy. **The loss-protection fix:** the 15-min monitor decided KEEP/CLOSE on FRESH in-memory marks but `_close_position` re-read the STALE DB `current_mark` (persisted only at 13:15Z/20:00Z/20:30Z → up to ~6.5h stale) for the order limit. Loss side (test-pinned): envelope/stop closes staged ABOVE a falling market → rest → watchdog-cancel → re-stage at the same stale mark → **never fill = protection failure**. Profit side (observed): BAC detected ≥+$255, closed at +$192. Fix: `exit_price_override` passes the decision's exact mark (guarded finite>0; degraded → DB fallback, logged — never fabricate). Part B persists monitor marks 15-min fresh (fixes the DB +$52 vs broker −$34 divergence class). **Scope: price coherence, NOT passive→marketable** (closes still rest if the market isn't at the fresh mid — marketable-close/GTC is the completion).

- **2026-05-26: EV-vs-H7 trade-off codified** as the named structural constraint at small-tier capital (doc-only). At ~$1,031 OBP: high-priced underlyings produce sufficient EV but fail H7; sub-$30 underlyings pass H7 but produce insufficient EV after costs — **no shape passes both at current capital** (mechanical capital-vs-size arithmetic, not a code bug). 3 operational paths + 6 rejected code-side fixes catalogued. Full text: `docs/structural_findings.md` "EV-vs-H7 trade-off at small-tier capital".
- **2026-05-21: universe expansion** +SNAP/RIVN/NIO/MARA (sub-$30, 4 sectors); 70→74 active. Data-only. Audit `a23461cc-…`.
- **2026-05-21: H7 allocator-aware pre-check** (PR `fix/h7-prefilter-and-khc-composition`) — `run_midday_cycle` filters candidates between `rank_and_select` and `PortfolioAllocator.allocate` against `sizing_engine.estimate_close_bp`. `H7_PREFILTER_ENABLED=false` (shadow; flip to `true` for active after shadow validation). New `cycle_metadata.{h7_prefilter_dropped, h7_prefilter_mode}`; new `exit_reason='all_candidates_h7_unfit'`. +KHC (69→70). 33 tests in `test_h7_prefilter.py`. Audit `2c91a730-…`.
- **2026-05-21: credit-spread chain-mechanics fix** (PR #975) — gate uses `combo_spread / max_loss_share` for credit spreads (was `/entry_cost`), fixing 90-day zero-emission. +`chain_mechanics_formula_anomaly` alert (>300%). Corrects the old "no phase-aware IC mechanism" claim — the mechanism at `strategy_selector.py:372-387` exists but is dormant under micro_live. 17 tests in `test_credit_spread_emission.py`.
- **2026-05-21: small-tier allocator wiring completed** — `workflow_orchestrator.py` threads `allocation_hint=_allocator_allocated_budget`; cycle-start RBE clamp bypassed when `allocation_hint_applied=True`; +`allocator_hint_dropped` alert (severity=high). Completes PR #958. See `docs/small_tier_allocation.md`.
- **2026-05-21: cycle_metadata + enriched_counts at all 7 return paths** of `run_midday_cycle` (`exit_reason` distinguishes path; pre-funnel exits emit `None`). `ops_health_service._resolve_regime_for_staleness` updated to skip `regime=None` pre-budget exits. Doctrine: H9 "early-exit observability symmetry".
- **2026-05-20: H9 silent-decision generalization** (PR #970) — `universe_service.get_scan_candidates` writes `universe_selection_log` (selected + dropped + thresholds), closing the limit=50 silent-truncation gap. FISV deactivated (corp action). Migration `20260519000001_universe_selection_log.sql`.

---

## Roadmap Status

Completed items, full priority breakdown, retrospective findings: `docs/roadmap.md`. Active priorities below in ## Backlog.

---

## Working Style

- Respond with exact SQL, Railway commands, file paths — no placeholders.
- When fixing bugs: show the broken code, explain why it's wrong, show the fix.
- When adding features: check GAP priority order first.
- Prefer minimal diffs over rewrites.
- Always check `job_runs` before assuming a cron ran successfully.

### Agent recommendation framing (2026-05-21)

- Ground recommendations in specific empirical signals, not general posture.
- Don't frame stopping points as defaults (as options, fine); don't repeat "consider stopping" across turns absent operator request; when the operator says "we continue," accept it and don't re-litigate cadence.
- Match the operator's evident bandwidth (multiple clean PRs → match velocity). Reserve push-back for evidence-supported cases (incomplete diagnostic, structural risk, verified contraindication), not cadence preference.

The agent makes prompts useful and findings rigorous; it does not gatekeep operator cadence decisions. Companion: "Operational velocity" below.

### Design principles

**Strategy availability vs threshold tuning.** Tune thresholds (per-tier, per-regime), not strategy availability — the scanner evaluates all strategies; downstream gates (spread, sizing, EV) decide. Rejection variety is signal. Anti-pattern (rejected 2026-04-30): disabling credit spreads at micro instead of raising the spread threshold (#92).

**Doctrine index** — full text in `docs/loud_error_doctrine.md`. The behaviorally load-bearing ones (H9/H10/H11) are spelled out; the rest are one-liners:

- **H7 — Capital invariants in both directions.** Sizing verifies round-trip BP, not just entry fit. PR #100; protects vs the BAC ghost-position class (2026-05-01).
- **H8 — Persistent worker deploys ≠ code restart.** RQ/APScheduler workers don't auto-reload on deploy. "PR shipped, deploy SUCCESS, behavior unchanged" ≈ worker not recycled. Verify worker restart before validating any worker-resident fix. Origin 2026-05-04 OBP incident (PR #864).
- **Anti-pattern 8 — Wrapper field-drop.** A new field-dependency on an upstream provider → audit the WHOLE wrapper chain; hand-built whitelist wrappers silently drop new fields and consumers fall to safe defaults without alerting. Origin PR #849 (`alpaca_client.py:200-225` dropped `options_buying_power`; fixed #864 + alert #865).
- **H9 — Verified-write/decision across wrapper chains.** When data flows producer → wrapper(s) → consumer across >1 boundary, the consumer must VERIFY the side effect occurred (not infer from "no exception"); wrappers return outcome (bool/Result/enum), consumers verify at anchor checkpoints. Generalized 2026-05-20 from verified-write to verified-decision (selection boundaries). Reference impl: PR-A Layer 4 `count_rows_for_date`. Ship cascade layers independently so each deploy validates the next surface.
- **H10 — Stale state cascades through pipeline gates.** One stale `paper_positions` row can suppress the whole pipeline (micro one-position gate → per-symbol envelope cap → force-close vs phantom). On any manual operator intervention (e.g. closing via Alpaca UI, bypassing our submission chain), **DB reconciliation is the FIRST follow-up** before other work. `ghost_position` alerts are urgent, not noise. Origin CSX 2026-05-12 (PR #921).
- **H11 — Status-check methodology.** Every status check / diagnostic MUST include a baseline query of critical/high `risk_alerts` independent of the operator's hypothesis (`… WHERE severity IN ('critical','high') …`). The operator's framing is the hypothesis, not the boundary. Origin 2026-05-12 (missed 2 critical alerts anchored on the wrong tables).
- **H12 — Framing-artifact discipline.** Don't let the question's framing (dates, labels) manufacture artifacts in the answer; applies to diagnostic synthesis too.
- **H13 — Parallel architectures without integration.** Two architectures coexisting without a wired seam is a latent bug (the cohort `promoted_at`/`is_champion` class).
- **H14 — Reference-document freshness: cite-then-verify.** Before relying on a value in a reference doc, re-verify it against live source — docs drift (e.g. HBAN $15.57 → ~$38). Counterweight: operational velocity below; H14 remains the empirical floor.
- **H15 — Context-repurposed value / dormant-path activation.** Dormant code/data acquires new load-bearing roles when a path activates; re-audit before relying on it.

**2026-06-04 session themes** (candidates for formal H-numbering in `docs/loud_error_doctrine.md`):

- **EVALUATE-FRESH / EXECUTE-STALE.** A decision and the order it triggers must read the SAME observation — the monitor decided on fresh in-memory marks while `_close_position` priced from the stale DB row (the #1022 class). Trace the full handoff when a decision crosses a function boundary by ID alone.
- **THE LYING DEBUG LINE.** BAC's "target_profit: True … result=False" was a debug line computing a flat threshold while the real condition was time-scaled — no execution bug, a dishonest log that manufactured a phantom incident. Debug output must compute via the SAME functions as the decision. (target_profit has fired 44× historically; the mechanism works.)
- **DOC/COMMENT/TEXT ≠ BUILT BEHAVIOR.** "GTC" lived only in rationale strings — no production order was ever GTC; the watchdog's "cancel and resubmit" was vaporware. Grep for the implementation before believing the comment (#1019/#1021 origin).
- **SILENT-FLAG-PARSE-FAILURE.** `== "1"` vs lenient parsing: set a flag to `true`, it silently no-ops, everything *looks* enabled (INTRADAY_TARGET_PROFIT, 2026-06-04). Normalize flag parsing + log parsed flag states at startup — backlog.
- **SHADOW-FILL ≠ REAL-BROKER FILL.** TCM-simulator cohorts filled 100%-at-mid vs live's ~12% instant-or-never — shadow data was an upper bound, not an estimate, until #1017's price correction + marketability label.

---

## Backlog

Full backlog (descriptions, sub-items, audit catalogs) lives in `docs/backlog.md`. This section keeps only the active focus.

### Operating mode — learning-mode (declared 2026-05-12; still active)

**Operator is in learning-mode. Goal is code correctness + system-behavior validation, NOT capital deployment.** Capital level is intentional, not a constraint to escape — the account is the dev environment for perfecting entry/exit logic before scaling. (Declared at $681/micro; equity has since crossed into small tier at ~$1,635, but the mode persists until the operator exits it explicitly — see "Mode exit".)

> Operator: "At micro tier I want to perfect the code and make sure it enters and exits accordingly. After these are perfected I will add more capital. Right now I want to focus on logic and learning to optimize the best list of options and the best combination for profits/time for the account."

**DO:** recommend observability/analytics work; bug fixes as they surface; diagnostics that surface behavior; doctrine/codification of empirical findings; strategy-mix observation. Treat low trade frequency as a FEATURE of careful operation.

**DO NOT:** recommend capital addition unless asked; push "more trades" as a goal; treat "no trade today" as a problem when the system is working as designed; push tier-upgrade work until the operator signals readiness; treat warmup-window low frequency as a bottleneck.

**TREAT WITH CARE:** universe widening / strategy unlocking (valuable for OBSERVATION, not deployment); "system isn't trading enough" diagnostics (first verify the framing — correct operation may produce no trades; H11 baseline still fires on critical alerts, orthogonal to trade-frequency framing).

**Mode exit:** operator declares it explicitly (no hard criteria). Likely signals: "I'm adding capital" / "moving past learning-mode" / asks about scaling / references entry-exit reliability as "good enough." If unsure whether learning-mode still applies, ASK. **Source:** 2026-05-12 strategic discussion; tier-inflection diagnostic surfaced the $1,000 cliff and the operator reframed from "deploy capital efficiently" to "perfect code, then scale." See `docs/backlog.md` "[2026-05-12] LEARNING-MODE CODIFICATION".

### Operational velocity (2026-05-21)

Learning-mode needs data; data needs cycles; cycles fire on the market schedule. Within empirical correctness (H14 cite-then-verify, diagnostic discipline, defensive observability), ship efficiently when evidence supports it. "Wait until Monday" / "let it settle over the weekend" / "stop for the day" are responses to **specific signals** (operator requests pause, evidence incomplete, dependent data not yet landed), NOT defaults after every PR. Operational momentum matters; the agent shouldn't second-guess a clean cadence absent operator signal.

This does NOT relax: H14 pre-flight verification · diagnostic discipline · H9 verified-consumer · catastrophic-failure risk awareness (loss exceeding account capital, ghost-position cascades, allocator emitting over-aggregate budgets) · the 2026-05-12 resistance to activity-maximization. Distinction: activity-maximization = "ship more to make more trades happen"; operational velocity = "ship the correct fix efficiently when evidence supports it." The difference is the evidence base, not the pace. **Origin:** 2026-05-21 operator feedback after a week of six grounded PRs where agent recommendations erred toward excessive caution.

**Caution IS warranted when:**
- Catastrophic failure modes are possible
- Diagnostic evidence is incomplete (N=1 cycle vs needed N cycles)
- An action requires verified state that hasn't been verified (PR #976's pre-flight catching HBAN drift)
- The operator explicitly signals fatigue or wants to pause

**Caution is NOT warranted because:**
- Multiple PRs have shipped recently
- The cadence "feels" heavy
- Defensible inaction is being weighed against verified action
- The agent prefers a slower pace

### Active focus (next 3)

Working backlog: `docs/backlog.md` (grouped + sequenced — Groups 1-7 + highest-leverage items).

1. **PR #908 empirical validation (waiting on next natural close).** PR #908's mleg sign-flip + clamp is live in the worker (verified 2026-05-12) but untested on a real close — no `paper_positions` opened/closed since 2026-05-12, so the event hasn't been triggerable. (The 2026-05-29 F close was a manual Alpaca-UI close, NOT the system exit path — so it does not count as validation; reconcile per H10.) Read "tomorrow's first close" as "whenever the next position closes via the system path". Capture: `limit_price` sign, `abs(limit_price) ≥ 0.01`, broker response. Also on watch: Tier 1 body-acceptance smoke (`python scripts/run_signed_task.py alpaca_order_sync --force-rerun`). Triage in `docs/backlog.md` → "PR #908 empirical validation".
2. **H9 Convention Slot 2 — silent-exception grep test (queued).** Slot 1 (AST gate) closed 2026-05-18 (strict mode; allow-list stable at 7, zero non-allow-listed violations on main). Slot 2 = complementary regex/grep test for shapes AST inspection might miss; may consolidate with Slot 1 if its surface proves adequate. Decision pending ~2 weeks of strict-mode CI observation. Slot 3 (literal status returns) already adopted as convention for new wrappers.
3. **Operator-side decision on small-tier path forward (codified 2026-05-26).** The structural arc through `canonical_ranker` closed (PRs #970/#972/#973/#974/#975/#976/#977/#978 + codification in `docs/structural_findings.md`). Pipeline is structurally healthy through the EV gate; the binding constraint at $1,031 OBP is mechanical and correctly enforced. **Three operator-side paths** (not code workstreams): (a) accept low frequency at small tier; (b) scale to standard tier ($5k+, where the same gross EVs become viable through size); (c) wait for CHOP regime (historically 69 ICs at avg EV $70; last CHOP 2026-02-24→03-17). Six code-side levers catalogued + rejected — `docs/structural_findings.md` "What does NOT resolve this constraint". **Sub-action ready:** flip `H7_PREFILTER_ENABLED=true` on Railway worker (shadow validation 2026-05-22/05-26 confirmed pre-check matches real-H7, zero false positives); changes `exit_reason` `no_suggestions_after_gates` → `all_candidates_h7_unfit`, no execution change. **Note:** at the new ~$1,635 small-tier capital these boundaries should be re-derived — the codification was done at $1,031 OBP.

Full Active-focus block (incl. recently-closed) in `docs/roadmap.md`; full item descriptions + catalogs (#62a schema drift, #72 loud-error doctrine) in `docs/backlog.md`.

### Operational state notes

**α IV pipeline:** historical `iv_rank` decidable for 67 of 70 pre-expansion universe symbols (Phase 3 complete 2026-05-17). WBD/XLK at the 60-row threshold; BKNG sparse at 30 (closes via `daily_refresh` by ~mid-July 2026); the 4 newest adds (SNAP/RIVN/NIO/MARA) pending backfill. α Phase 3 was DATA-side (backfilled IV30 → `iv_rank` computable); emission of IV-sensitive strategies is gated SEPARATELY (ICs regime-gated by design; credit spreads were blocked by chain-mechanics until PR #975, not by α). Full history: `docs/alpha_iv_history.md`.

### Exit thresholds (defaults under empirical review)

`paper_exit_evaluator.py:329-330`: `_DEFAULT_TARGET_PROFIT_PCT = 0.35` (+35% of entry; env `EXIT_TARGET_PROFIT_PCT`), `_DEFAULT_STOP_LOSS_PCT = 0.50` (−50%; env `EXIT_STOP_LOSS_PCT`).

Time-scaling (`:180-203`, stop 225-258): profit target time-scales 50% (entry) → 25% (near expiry) via sqrt-decay (locks profit before theta accelerates). Stop loss FLAT by default; a symmetric sqrt-decay path for debit_spread stops exists behind `EXIT_STOP_LOSS_TIME_SCALING_ENABLED=1` (default OFF; tightens 50% → floor 0.30 via `EXIT_STOP_LOSS_FLOOR_PCT`; iron condors bypass via `_is_iron_condor`).

Empirical table (90-day, paper_positions, as of 2026-05-13), re-eval criterion (N=20/bucket), and caveats: `docs/exit_thresholds.md` + `docs/audit_hold_period_asymmetry.md` (LOW confidence at N=6, sample stale). Headline: iron_condor profit_target N=35 avg +$1,852; debit_spread profit_target N=9 avg +$1,511; debit_spread stop_loss N=6 avg −$2,063. PR #929's `hold_period_buckets` v2 buckets the single profitable IC stop as `profitable_stop`.

### Structural findings (operational summary)

Verified-fittable structure classes (derived at $681 micro — **re-derive at the new ~$1,635 small tier**): Class A 1-leg long at modest deltas · Class B sub-$30 narrow-strike debit spreads (binding constraint `edge_below_minimum`, downstream of H7) · Class C $1-wide credit spreads · Class D narrow-wing iron condors (post-α; `strategy_selector` iv_rank gate no longer holds them) · Class E excluded (CSP/CC capital reservation > BP). Full empirical work, 2-leg debit geometry, entry-premium-vs-width derivation, and the EV-vs-H7 trade-off: `docs/structural_findings.md`.

---

## Live State (auto-updated)

- **Last updated:** 2026-06-04 (end of the live-fill / exit-mechanics session; merged this session: #1017 #1018 #1019 #1021, #1022 merged-pending-deploy — see "PR ledger" in Bugs Fixed).
- **Phase:** micro_live (operator-set label, since 2026-04-25; promotion gate bypassed, continuous-growth model).
- **Live Alpaca `211900084`:** equity **≈ $2,283** · cash ≈ $1,719 · options BP **≈ $6,876** (post-PDT-elimination margin framework — see "PDT Regime Change") · margin multiplier 2. **ONE open live position** (below). PDT designation/day-trade counting ELIMINATED 2026-06-04 (`pattern_day_trader`/`daytrade_count` are placeholder fields, removed ~2026-07-06).
- **OPEN LIVE POSITION — NFLX bear put debit spread:** buy 7/2 P85 / sell 7/2 P79, **2 contracts @ $3.08 = $616 max loss** (bounded). Aggressive/live-champion cohort, portfolio `814cb84b`, opened 2026-06-04 16:03Z, position `a9f977bf`, `execution_mode=alpaca_live`, filled in 32ms at mid. **The first REAL live multi-leg fill of the arc.** All exits live: aggressive cohort target_profit +$308 (15-min intraday TP armed, flag `=1`), cohort stop −$185 (scheduled), per-symbol envelope ≈ −$70 (15-min, enforce ON), DTE/expiry far. Its eventual system close = the long-awaited **PR #908 live credit-mleg-close validation**.
- **TIER: now SMALL** — `get_tier(deployable_capital)` returns `small` above the $1,000 micro→small cliff (`small_account_compounder.py:24-50`; capital-based, not phase-based). Concrete small-vs-micro deltas:
  1. **max concurrent positions 1 → 4** — the micro one-at-a-time gate (`micro_tier_position_open`) no longer fires.
  2. **Sizing is allocation-aware** — `PortfolioAllocator` distributes a `0.85 × regime_mult × equity` envelope across up to 4 viable candidates (36% per-trade ceiling, score-skew clamp 0.8–1.2), instead of micro's single `0.90 × regime_mult` trade.
  3. selection_logic unchanged (`rank_select_compound`).
- **Prior micro-tier assumptions need re-examination at small tier:** the one-position concurrency constraint and the micro EV-vs-H7 boundaries (Class B `edge_below_minimum` at $681) were derived at micro capital. The 2026-05-26 EV-vs-H7 codification was done at small-tier $1,031 OBP (`docs/structural_findings.md`); the structure-class fits should be re-derived at ~$1,635.
- **Shadow book (2026-06-04 EOD):** shadow BAC `043f607e` CLOSED by the newly-armed intraday TP (`target_profit_hit`, 16:45Z, internal fill, realized ≈ +$192) — the first intraday profit capture, proving the 15-min TP branch. Shadow NFLX forks still open: conservative `dd096ef5` (3ct) + neutral `f6d56943` (6ct). Their `ghost_position` order-sync noise persists until Phase-1b exclusion.
- **PR #908 validation watch (updated):** the credit-mleg-close SHAPE is now broker-validated on paper (#1021 smoke test, 2026-06-04: closing+credit GTC accepted/rested/cancelled). The remaining validation is the first LIVE system close — the open NFLX `a9f977bf` is the candidate.
- **Paper account `PA3I8CYLXBOS`** is wired via the `alpaca-paper` MCP server (separate from `alpaca-live`/`211900084`) for testing — 2026-05-29 validated OPENING+debit mleg GTC rests; 2026-06-04 validated CLOSING+credit mleg GTC (negative limit per #999) accepts/rests/cancels.
- **Paper-shadow executor (D6/D2 observation infra):** Phase 1a merged (#1003) — dedicated paper client + `PA3I8CYLXBOS` account guard + `paper_shadow` routing_mode + 3 live-job exclusion filters; flag `PAPER_SHADOW_EXECUTOR_ENABLED` **default OFF** (nothing runs). Worker paper creds provisioned. Phase 1b pending (paired executor + D6 realized; leading safety item: `alpaca_order_sync` Step-2/Step-3 reconcile-loop exclusion). Detail in the `paper-shadow-executor-phases` memory note.
- **Universe:** 74 active (see Current Phase). **α IV:** 67 at full iv_rank decidability; WBD/XLK at 60-row threshold; BKNG sparse (~mid-July 2026); 4 newest pending backfill.
