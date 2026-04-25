# PR #6 Observation-Window Monitoring Queries

Operational queries run during the 48h observation window after
Phase 1 migration apply. Saved here for rapid re-run during
market hours without reconstructing from context.

**Observation window:** 2026-04-23T01:03:41Z → 2026-04-25T01:03:41Z
(48h from PR #6 merge).

**Cadence:**
- Close-path validation (Q-CP): every 30–60 min during market hours
  (13:00–21:00 UTC / 8am–4pm CT). Any row with validation failures
  is a halt-and-diagnose event.
- Cron-fire verification (Q-CF): at each expected `phase2_precheck`
  boundary — 17:00, 23:00, 05:00, 11:00 UTC (next scheduled fires
  based on `minute=0, hour='*/6'` America/Chicago cron). If no new
  row appears within ±5 minutes of the boundary: cron wiring issue.

---

## Q-CP — Close-path validation

Checks every post-T+0 close row for:
- `fill_source` populated (in the 4-value enum)
- `close_reason` populated (in the 9-value enum)
- `close_reason_legacy_original` NULL for post-migration closes
- `realized_pl` present
- `closed_at` populated

```sql
SELECT
  id,
  symbol,
  close_reason,
  fill_source,
  close_reason_legacy_original,
  realized_pl,
  closed_at,
  CASE
    WHEN fill_source IS NULL                                THEN 'FAIL: NULL fill_source'
    WHEN fill_source NOT IN (
           'alpaca_fill_reconciler', 'orphan_fill_repair',
           'exit_evaluator', 'manual_endpoint'
         )                                                  THEN 'FAIL: non-canonical fill_source'
    WHEN close_reason IS NULL                               THEN 'FAIL: NULL close_reason'
    WHEN close_reason NOT IN (
           'target_profit_hit', 'stop_loss_hit', 'dte_threshold',
           'expiration_day', 'manual_close_user_initiated',
           'alpaca_fill_reconciler_sign_corrected',
           'alpaca_fill_reconciler_standard',
           'envelope_force_close', 'orphan_fill_repair'
         )                                                  THEN 'FAIL: non-canonical close_reason'
    WHEN close_reason_legacy_original IS NOT NULL           THEN 'WARN: legacy_original set on post-migration close'
    WHEN realized_pl IS NULL                                THEN 'FAIL: NULL realized_pl'
    WHEN closed_at IS NULL                                  THEN 'FAIL: NULL closed_at'
    ELSE 'OK'
  END AS validation_status
FROM paper_positions
WHERE closed_at > '2026-04-23T01:03:41Z'
ORDER BY closed_at DESC;
```

Any row with `validation_status != 'OK'` is a **halt and diagnose**
event — exercises a broken code path or a constraint gap.

---

## Q-CF — Cron-fire verification

Lists every `phase2_precheck` risk_alert since the T+0 baseline,
with the cron fire count (if present) and pass/fail status.

```sql
SELECT
  id,
  severity,
  metadata->>'verification_type' AS vtype,
  metadata->>'status'            AS status,
  metadata->>'all_checks_passed' AS passed,
  metadata->>'hours_since_deploy' AS hours_since,
  created_at
FROM risk_alerts
WHERE alert_type = 'phase2_precheck'
ORDER BY created_at DESC;
```

**Expected sequence** (verification_type values):
1. `phase2_precheck_manual_t0_after_migration_repair` — baseline
   row `81f10e34-61d8-40d5-9d92-948a17ceaeb7` (written 11:44 UTC)
2. `phase2_precheck` (plain, from the cron) — first fire at
   17:00 UTC ±5min today if PR #799 deployed by 17:00
3. Subsequent cron fires every 6h: 23:00 UTC, 05:00 UTC,
   11:00 UTC, etc.

**Expected rows by 2026-04-25T01:03:41Z** (window close): 1
manual + up to 8 cron fires = 9 total.

---

## T+0 baseline anchor

```
risk_alert.id = 81f10e34-61d8-40d5-9d92-948a17ceaeb7
created_at    = 2026-04-23T11:44:56Z
severity      = info
passed        = true
```

Referenced by the Phase 2 PR description as the starting point
of the verification sequence.
