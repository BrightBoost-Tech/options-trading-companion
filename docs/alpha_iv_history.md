# α IV pipeline — implementation history

The α historical-IV backfill pipeline reached operational completeness on 2026-05-17. This document captures the delivery history, validation methodology, and architectural notes referenced from `CLAUDE.md` "α IV pipeline" summary.

## Current state (2026-05-18)

- Full-universe historical `iv_rank` decidable for 67 of 70 active universe symbols.
- 2 symbols (WBD, XLK) at 60 rows = threshold; marginal.
- 1 symbol (BKNG) at 30 rows; `daily_refresh` closes the gap naturally over ~30 trading days (mid-July 2026).
- IV-sensitive strategies (credit spreads, iron condors) are decidable for ~95% of the active universe via `strategy_selector`'s existing `iv_rank` consumer paths.
- The "warmup window day N of ~60" framing was correct at Phase 1+2 delivery (3 reference symbols); Phase 3 v3 short-circuited the per-symbol day-counting wait. Warmup gate is no longer the dominant reason for low trade frequency.

Outstanding observations live in `docs/backlog.md`:
- **Finding C (Tier 2, PR #949):** anchor-selection time-instability — same `(symbol, as_of_date)` may produce different `iv_30d` over time as available-contract set shifts. iv_rank consumers tolerate ~1-2 pct-pt drift.
- **BKNG sparse residual (Tier 3, PR #954):** F2a recovered 18 of 19 sparse symbols; BKNG (~$4500/share) remains at 30 rows. Hypotheses: chain-depth exceeding new 20000 cap or strike-density interaction.

## Phase 1 — reference backfill (2026-05-14 plumbing, 2026-05-15 run)

**Trigger plumbing (PR #935 follow-up):** the original PR #935 shipped the `iv_historical_backfill` handler but the operator-trigger plumbing (HTTP route + `run_signed_task.py` registry entry) was missing. Follow-up PR landed the route + entry. Canonical Phase 1 trigger:

```
python scripts/run_signed_task.py iv_historical_backfill \
  --payload-json '{"days": 60, "symbols": ["SPY", "AAPL", "AMD"]}'
```

POSTs to `/internal/tasks/iv/historical-backfill`, writes a `job_runs` row via `enqueue_job_run`, worker claims and executes in production environment. Observability: `job_runs` row + handler's own audit `risk_alerts` row + new `underlying_iv_points` rows. Smoke variant: `'{"days": 1, "symbols": ["SPY"]}'` produces ~1 row for plumbing verification before the 60-day fire.

**Run (2026-05-15):**
- job_run_id: `9627c667-61e5-4915-a83c-a584b03bab0a`
- Duration: 8.5 hours (11:55 → 20:28 UTC, longer than expected)
- Rows written: 165 (55 trading days × 3 underlyings)
- Data quality: PASS — `iv_30d` values smooth and within typical bounds:
  - SPY: 0.14–0.26 (avg 0.18)
  - AAPL: 0.23–0.33 (avg 0.28)
  - AMD: 0.54–0.69 (avg 0.60)
- Handler stats: ok=165, failed=0, skipped_existing=12, missing_data=3
- Accounting verification: PASS (handler's H9 post-write count matches table state)
- Alerts during run: only 2 info-severity audit rows from handler itself

**Operational finding (captured as Tier 1 candidate in `docs/backlog.md`):** Phase 1 ran during trading hours and starved the worker queue for 8.5 hours, delaying the entire trading-day pipeline. Today's actual cost was low (0 open positions, micro tier) but the same pattern at higher tiers or with open positions would starve `intraday_risk_monitor` + `paper_exit_evaluate`. Worker-queue separation (PR #946) addressed this.

## Phase 2 — manual validation (2026-05-15)

Validation harness: `packages.quantum.tests.validate_alpha_backfill`. Reconstructs IV30 live via Polygon BS inversion for each reference symbol on a target date (2026-05-08), then prompts operator for an independent reference value (from barchart.com Options Overview History "Imp Vol" column). Computes delta in percentage points. Pass criterion: ≥2/3 symbols within ±10 percentage points.

**Results (3/3 passed):**

| Symbol | Reconstructed IV30 | Barchart Reference | Delta (pct-points) | Verdict |
|---|---|---|---|---|
| SPY | 0.1381 | 0.1512 | 1.31 | ✓ Pass |
| AAPL | 0.2261 | 0.2388 | 1.27 | ✓ Pass |
| AMD | 0.6814 | 0.6788 | 0.26 | ✓ Pass |

All three reconstructed IV30 values closely match barchart's independently-computed Imp Vol values. AMD's 0.26 pct-point delta is particularly tight (essentially exact match despite 2026-05-08 being a high-IV day for AMD relative to its recent range).

This validates:
- Polygon BS inversion produces accurate IV30 values
- Phase 1's 165 bulk-written rows are trustworthy
- The historical IV pipeline can drive `iv_rank` computation reliably
- IV-rank-gated strategies can be confidently enabled at Phase 5 cutover

**Validation note (transparency):** the operator entered SPY reference as `0.0512` (typo, missing leading "1") instead of `0.1512`. The harness recorded delta as 8.69 pct-points using the typo'd value. The verdict (Pass) was unchanged either way — `0.0512` still passes the ±10 tolerance — but the correct delta is 1.31 pct-points. Future readers should refer to the table above for accurate per-symbol deltas, not the harness's raw terminal output for SPY.

**α validation status: VALIDATED.**

## Phase 3 — full-universe backfill (2026-05-17)

Phase 3 was gated on worker-queue blocker mitigation post-Phase-2; all other prerequisites met. Weekend arc 2026-05-15 → 2026-05-17 — chronological delivery chain:

- **PR #946 (worker queue separation):** new `worker-background` Railway service listening on `background` RQ queue, isolated from trading-day pipeline (`otc` queue). Phase 1's 8.5h run pattern no longer starves trading-day jobs.
- **PR-A2 (PR #948):** `expired=true` parameter on Polygon contracts endpoint. Finding B mechanical fix: contract listings now time-stable.
- **PR-A (PR #950, range-query refactor):** per-contract range OHLC fetch replacing per-(symbol, date, contract) serial calls. Phase 3 wall-clock projection dropped from ~4.5 days to ~hours.
- **F1 (PR #952, RQ timeout map):** per-job-name timeout overrides; `iv_historical_backfill` gets 6h budget (default 10m preserved for trading-day jobs).
- **F2a (PR #953, pagination cap):** raised contract-listing default cap from 1000 to 20000. Deep-chain symbols (QQQ, MSFT, NVDA, etc.) had their pagination budget consumed by daily-expiry strikes; F2a unblocked full coverage.
- **Phase 3 v3 run:** full-universe backfill (job_run `13b89a7e-642c-48f7-9e4f-259c4922eec4`, ~3.5h runtime, 67 of 70 symbols at full 61-row coverage, 0 failed). Completed 2026-05-17 21:36 UTC, ~213 min duration.

Architectural notes for future readers:

- "Phase 3 (full-universe backfill)" is no longer aspirational — it's an operationally tractable trigger with explicit `symbols` list payload. Option P3c (handler-side universe loading via `scanner_universe` table) was discussed but not shipped; explicit `symbols` in payload is the current pattern.
- Worker queue separation (PR #946) is justified by actual usage: long backfill jobs (~3.5h+) MUST route to `background` queue to avoid starving trading-day pipeline.
- Polygon Options Developer tier ($79/mo) is sufficient for α's BS-inversion approach; Options Advanced doesn't expose historical pre-computed IV (verified Sunday 2026-05-17 investigation). Vendor change not needed.

## Phase 4 + Phase 5 framing (UPDATED post-Phase-3)

With Phase 3 complete and `iv_rank` decidable for 67 symbols, the boundary between "Phase 4 sanity check" and "Phase 5 operational cutover" is fuzzy — IV-sensitive strategies are now technically active via `strategy_selector`'s existing `iv_rank` consumer paths. Operator-driven empirical observation will surface any cutover concerns; no explicit cutover event needed.

## iv_handler_accounting_mismatch — RESOLVED 2026-05-14 evening

The `iv_handler_accounting_mismatch` alerts that fired 3 times in table history (2× on 2026-05-09, 1× on 2026-05-14, all with identical `stats_ok=1, actual_rows=5, delta=-4`) were traced via H5 unification investigation to a single mechanism: local developer pytest execution against real Supabase credentials.

**Root cause:** `test_iv_daily_refresh_handler.py` mocks `IVRepository` (causing `count_rows_for_date` to return hardcoded `5` at line 43) AND calls `run({})` directly (line 46) — bypassing `enqueue_job_run`. The handler's accounting check (`iv_daily_refresh.py:130-153`) does a lazy `from packages.quantum.observability.alerts import _get_admin_supabase` which reads env at call time and constructs a REAL admin client, then writes to production `risk_alerts` as a side-effect of test execution. All alert metadata reconciled: "5" = test mock; "1" = universe math (only AAPL succeeds); "delta=-4" = arithmetic; "no `job_runs`" = direct `run()` call.

**Fix applied:** test mocks `_get_admin_supabase` directly (primary); `_get_admin_supabase` gained a `PYTEST_CURRENT_TEST` env-guard returning `None` unless `ALERTS_ALLOW_ADMIN_UNDER_PYTEST=1` is set (defense-in-depth).

**Phase 1 readiness CLEAR.** The production pathway was unaffected — Phase 1 trigger via standard `enqueue_job_run` uses real `IVRepository` against production Supabase; `count_rows_for_date` returns actual count; verification works correctly. `iv_historical_backfill` was never at risk (it writes its audit alert via the test-mocked `client` directly, not via the lazy `_get_admin_supabase` pattern).
