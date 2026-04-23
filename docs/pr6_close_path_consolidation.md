# PR #6 Close-Path Consolidation — Operator Reference

**Audience:** on-call operators, DB owners, anyone diagnosing a
`close_path_anomaly` risk_alert or a stuck paper_positions row.
**Status:** Phase 1 deployed. Phase 2 pending (see timeline below).

This doc covers the shared close-path architecture established by
PR #6, the expand-and-contract migration strategy for the
`close_reason` / `fill_source` enums, and the rollback procedures
if something goes wrong during or after Phase 2.

---

## 1. Architecture

Before PR #6 there were **five** call sites that wrote
`paper_positions.status='closed'` directly, each with its own inline
math and its own close_reason string. This was the structural root
cause of the 2026-04-10 → 04-16 class of bugs (PYPL cfe69b28, NFLX
846bc787, and the dormant `PaperExecutionService` sign-convention
bug). PR #6 replaced the 5 writers with one writer:

```
 ┌─────────────────────────────────┐
 │ 1. alpaca_order_handler         │ ── caller of ──┐
 │    ._close_position_on_fill     │                │
 └─────────────────────────────────┘                │
 ┌─────────────────────────────────┐                │
 │ 2. paper_exit_evaluator         │ ── caller of ──┤
 │    ._close_position             │                │
 │    (internal-fill branch)       │                │
 └─────────────────────────────────┘                │
 ┌─────────────────────────────────┐                │
 │ 3. paper_endpoints              │ ── caller of ──┤
 │    ._repair_filled_order_commit │                │
 │    (close branch)               │                │
 └─────────────────────────────────┘                │
 ┌─────────────────────────────────┐                │
 │ 4. paper_endpoints              │ ── caller of ──┤
 │    ._commit_fill                │                │
 │    (close branch)               │                │
 └─────────────────────────────────┘                │
                                                    ▼
          ┌──────────────────────────────────────────────────┐
          │  close_math.compute_realized_pl      (pure)      │
          │  close_math.extract_close_legs       (pure)      │
          │  close_helper.close_position_shared  (I/O)       │
          │     ↓ atomically writes                          │
          │  paper_positions (status, realized_pl,           │
          │    close_reason, fill_source, closed_at,         │
          │    quantity=0, updated_at)                       │
          └──────────────────────────────────────────────────┘
```

The 5th writer — `PaperExecutionService` — was dead code with a
latent sign bug and was deleted in Commit 8a. No production file in
`packages/quantum/` now writes `status='closed'` except
`services/close_helper.py`. Enforced by
`tests/test_pr6_close_path_invariants.py::TestSingleCloseWriter`.

### Why leg-level math

`compute_realized_pl` consumes **leg fills** (per-leg action +
filled_avg_price + filled_qty), NOT an Alpaca parent's
net-cash-flow-signed `filled_avg_price`. This structurally prevents
the PYPL cfe69b28 class of bug: the pre-PR-#6 inline math read
Alpaca's `filled_avg_price = -2.60` (mleg net credit) as an exit
price, computing `-$3,324` for a position whose true loss was
`-$204`. Leg-level math is robust because each leg's direction
(sell = cash in, buy = cash out) is always unambiguous.

---

## 2. Enum Values

### close_reason (9 canonical values, post-Phase-2)

| Value | Emitted by | Meaning |
|---|---|---|
| `target_profit_hit` | exit_evaluator | Position hit target profit threshold |
| `stop_loss_hit` | exit_evaluator | Position hit stop-loss threshold |
| `dte_threshold` | exit_evaluator | DTE ≤ 7 (gamma risk) |
| `expiration_day` | exit_evaluator | Position expires today |
| `manual_close_user_initiated` | commit_fill (POST /paper/close, PaperAutopilot) | User or user-configured autopilot closed |
| `alpaca_fill_reconciler_sign_corrected` | **historical only** — PYPL cfe69b28, manual UPDATE 2026-04-20 | Pre-PR-#790 sign-bug remediation |
| `alpaca_fill_reconciler_standard` | alpaca_order_handler | Alpaca fill reconciled via standard path |
| `envelope_force_close` | exit_evaluator (via intraday_risk_monitor `risk_envelope:*`) | Risk envelope breach force-close |
| `orphan_fill_repair` | paper_endpoints._repair_filled_order_commit | Orphan filled order's position reconstructed + closed |

### fill_source (4 values)

| Value | Written by |
|---|---|
| `alpaca_fill_reconciler` | alpaca_order_handler._close_position_on_fill |
| `exit_evaluator` | paper_exit_evaluator._close_position internal branch |
| `orphan_fill_repair` | paper_endpoints._repair_filled_order_commit |
| `manual_endpoint` | paper_endpoints._commit_fill |

### Legacy close_reason values (Phase 1 only)

Phase-1 CHECK accepts 5 legacy values for grandfathering historical
rows. Phase 2 drops them from the CHECK:

- `target_profit` (renamed to `target_profit_hit` by Phase 1 UPDATE)
- `stop_loss` (renamed to `stop_loss_hit`)
- `alpaca_fill_reconciled_2026_04_16` (renamed to `alpaca_fill_reconciler_standard`)
- `manual_internal_fill` (renamed to `manual_close_user_initiated`)
- `alpaca_fill_manual` (renamed to `manual_close_user_initiated`)

Python-side, `close_helper._VALID_CLOSE_REASONS` is STRICT to the 9
canonical values regardless of phase — no new post-PR-#6 code writes
a legacy string.

---

## 3. Migration Timeline

```
PHASE 0 (pre-merge)
   Production writes close_reason ∈ legacy-5.
   paper_positions has no fill_source column.
   No CHECK on close_reason.

PHASE 1 (merge day — this PR)
   Migration 20260423000001_expand_close_reason_enum_phase1.sql:
     - ADD COLUMN fill_source (nullable)
     - ADD COLUMN close_reason_legacy_original (audit breadcrumb)
     - UPDATE 58 legacy rows → canonical values
     - ADD CHECK accepting 14 values (9 canonical + 5 legacy)
     - ADD CHECK fill_source ∈ 4 values or NULL
   All new post-merge code writes canonical values.
   Legacy values remain in CHECK only for grandfathering.

OBSERVATION WINDOW (~24h post-Phase-1 deploy)
   Verify queries in §5 below show:
     - Zero NEW post-deploy writes of legacy values
     - Every new close has fill_source populated
     - Every new close has one of 9 canonical close_reasons

PHASE 2 (~24h later, separate PR / migration file)
   Migration 20260424000001_contract_close_reason_enum_phase2.sql:
     - DROP CONSTRAINT check_close_reason_enum
     - ADD CONSTRAINT check_close_reason_enum
         CHECK (close_reason IN (9 canonical values))
     - ADD CONSTRAINT close_path_required (fill_source NOT NULL
         AND close_reason NOT NULL AND realized_pl NOT NULL)
         WHERE closed_at > GRANDFATHER_CUTOFF
```

`GRANDFATHER_CUTOFF = '2026-04-26 00:00:00+00'` — historical rows
closed before this timestamp are exempt from `close_path_required`.

---

## 4. Runbook — `close_path_anomaly` risk_alert

When a handler's pipeline raises, the handler writes a
`severity='critical'` row to `risk_alerts` with
`alert_type='close_path_anomaly'` and aborts the close.

**Every occurrence of this alert means a position did NOT close when
the system expected it to.** Operator review required. Position
stays open with `status='open'`, quantity preserved.

### Diagnostic query

```sql
SELECT
  created_at,
  position_id,
  symbol,
  message,
  metadata->>'detector' AS handler,
  metadata->>'stage'    AS pipeline_stage,
  metadata->>'reason'   AS anomaly
FROM risk_alerts
WHERE alert_type = 'close_path_anomaly'
  AND severity   = 'critical'
  AND created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC;
```

### Triage by `stage`

| Stage | Typical cause | Response |
|---|---|---|
| `extract_close_legs` | Alpaca broker_response has mleg but no legs sub-array | Fetch the order from Alpaca; if legs are present, rerun the handler; if not, manually close position with actual realized_pl from broker UI |
| `compute_realized_pl` | Partial fill (leg qtys mismatched, or parent≠leg qty) | Confirm partial fill in broker. If intentional (leg scratched), manually close with correct realized_pl. If bug, capture broker_response shape for post-mortem |
| `close_position_shared` (PositionAlreadyClosed) | Concurrent close from another handler already applied | Safe no-op in 99% of cases; verify existing close via `metadata->>existing_close_reason`. If existing close looks wrong, investigate who wrote it |
| `map_close_reason` | exit_evaluator or commit_fill received an unrecognized source_engine | Check upstream caller emitted the right reason string; if it's a new legitimate close path, extend `_map_close_reason` OR add source_engine to `commit_fill`'s allowlist |
| `derive_inputs` | position has quantity=0 but status != 'closed' | Data corruption; manually inspect + correct via SQL |

### Manual close SQL (last resort)

```sql
UPDATE paper_positions
   SET status      = 'closed',
       quantity    = 0,
       realized_pl = <DECIMAL FROM BROKER>,
       close_reason = '<ONE OF 9 CANONICAL VALUES>',
       fill_source  = '<ONE OF 4 VALUES>',
       closed_at    = NOW(),
       updated_at   = NOW()
 WHERE id = '<POSITION_ID>'
   AND status != 'closed';  -- compare-and-swap safety
```

Record the manual intervention in `risk_alerts` with
`severity='info'` and `alert_type='manual_close_intervention'` for
audit trail.

---

## 5. Observation-Window Verification Queries

Run these ~24h after Phase 1 deploys, before applying Phase 2.

### 5.1 Zero post-deploy writes of legacy close_reason

```sql
SELECT close_reason, COUNT(*) AS post_deploy_writes
  FROM paper_positions
 WHERE closed_at > '<PHASE_1_DEPLOY_TIMESTAMP>'
   AND close_reason IN (
     'target_profit', 'stop_loss',
     'alpaca_fill_reconciled_2026_04_16',
     'manual_internal_fill', 'alpaca_fill_manual'
   )
 GROUP BY close_reason;
```

Expected: **zero rows**. If any row appears, do NOT apply Phase 2 —
a handler is still emitting legacy values. Trace via the
`fill_source` column on the violator row.

### 5.2 Every new close has fill_source populated

```sql
SELECT COUNT(*) AS missing_fill_source
  FROM paper_positions
 WHERE status = 'closed'
   AND closed_at > '<PHASE_1_DEPLOY_TIMESTAMP>'
   AND fill_source IS NULL;
```

Expected: **0**. NULL fill_source on a post-deploy close row means
some path bypassed `close_position_shared`.

### 5.3 Every new close has one of 9 canonical close_reasons

```sql
SELECT close_reason, COUNT(*)
  FROM paper_positions
 WHERE status = 'closed'
   AND closed_at > '<PHASE_1_DEPLOY_TIMESTAMP>'
   AND close_reason NOT IN (
     'target_profit_hit', 'stop_loss_hit', 'dte_threshold',
     'expiration_day', 'manual_close_user_initiated',
     'alpaca_fill_reconciler_sign_corrected',
     'alpaca_fill_reconciler_standard',
     'envelope_force_close', 'orphan_fill_repair'
   )
 GROUP BY close_reason;
```

Expected: **empty result set**.

### 5.4 Zero `close_path_anomaly` alerts in observation window

```sql
SELECT COUNT(*), array_agg(DISTINCT metadata->>'stage') AS stages
  FROM risk_alerts
 WHERE alert_type = 'close_path_anomaly'
   AND severity = 'critical'
   AND created_at > '<PHASE_1_DEPLOY_TIMESTAMP>';
```

Non-zero is not a blocker for Phase 2 if each alert has been triaged
and resolved. It IS a blocker if anomalies are recurring — that
signals a systematic issue the strict Phase 2 CHECK would make worse.

---

## 6. Rollback Procedures

### 6.1 Rolling back Phase 2 (CHECK too strict — production writes rejected)

If Phase 2 deploys and production writes start failing with
`violates check constraint "check_close_reason_enum"`:

```sql
BEGIN;
  ALTER TABLE paper_positions DROP CONSTRAINT check_close_reason_enum;
  ALTER TABLE paper_positions
    ADD CONSTRAINT check_close_reason_enum
    CHECK (
      close_reason IS NULL
      OR close_reason IN (
        -- Restore Phase 1's 14-value permissive set
        'target_profit_hit', 'stop_loss_hit', 'dte_threshold',
        'expiration_day', 'manual_close_user_initiated',
        'alpaca_fill_reconciler_sign_corrected',
        'alpaca_fill_reconciler_standard',
        'envelope_force_close', 'orphan_fill_repair',
        'target_profit', 'stop_loss',
        'alpaca_fill_reconciled_2026_04_16',
        'manual_internal_fill', 'alpaca_fill_manual'
      )
    );
COMMIT;
```

This reverts the CHECK to Phase 1 state without dropping columns or
losing audit data. Investigate which close_reason was being written
via the `risk_alerts` and job logs from the failure window.

### 6.2 Rolling back the `close_path_required` combined CHECK

If Phase 2's combined `(fill_source NOT NULL AND close_reason NOT
NULL AND realized_pl NOT NULL)` constraint rejects a legitimate
edge case (e.g. pre-GRANDFATHER_CUTOFF row backfill):

```sql
ALTER TABLE paper_positions DROP CONSTRAINT close_path_required;
```

Do NOT re-add without first verifying `closed_at >
GRANDFATHER_CUTOFF` truly covers all cases. The grandfather cutoff
is `'2026-04-26 00:00:00+00'`.

### 6.3 Full PR #6 application rollback (worst case)

If a handler migration (Commits 4b–7) introduces a regression, the
rollback path is:

1. Revert the handler commit. Leave the migration in place — the
   Phase 1 CHECK is strictly additive (14 values including all 5
   legacy), so pre-PR-#6 code writing legacy values still passes.
2. The shared helper (`close_helper.py`, `close_math.py`) is
   additive — revert is optional. Leaving them in place doesn't
   affect handlers that haven't been reverted.
3. Do NOT run the Phase 2 migration until all handler regressions
   are resolved.

### 6.4 What cannot be rolled back cleanly

- The 58 UPDATE statements in Phase 1 that renamed legacy
  close_reason values. `close_reason_legacy_original` column
  preserves the pre-rename value. To undo:

  ```sql
  UPDATE paper_positions
     SET close_reason = close_reason_legacy_original
   WHERE close_reason_legacy_original IS NOT NULL;
  ```

- The `paper_execution_service.py` deletion (Commit 8a). Recoverable
  from git history (commit `af971a5`) but the class was dead code
  with a latent sign bug; recovery would intentionally reintroduce
  both problems. Prefer rewriting using the shared pipeline.

---

## 7. Changes Summary (for PR description)

### Added
- `supabase/migrations/20260423000001_expand_close_reason_enum_phase1.sql`
- `packages/quantum/services/close_math.py` — pure realized-P&L math
  + leg-extraction utility
- `packages/quantum/services/close_helper.py` — atomic
  paper_positions close writer with strict enum validation
- Regression tests for every close handler + cross-cutting
  invariants (see §8)

### Modified
- `packages/quantum/brokers/alpaca_order_handler.py` — reconciler
  migration (Commit 4b)
- `packages/quantum/services/paper_exit_evaluator.py` —
  internal-fill branch migration + `_map_close_reason` helper
  (Commit 5)
- `packages/quantum/paper_endpoints.py` — orphan-repair close branch
  + `_commit_fill` close branch migrations + relaxed `avg_fill_price
  <= 0` input guard (Commits 6, 7)
- `packages/quantum/tests/test_observability_v4.py` — removed the
  two PaperExecutionService import/hasattr tests (Commit 8a)

### Deleted
- `packages/quantum/services/paper_execution_service.py` — dead
  code, latent sign bug (Commit 8a)
- `packages/quantum/tests/test_paper_execution.py` — exercised only
  the deleted class (Commit 8a)

### Tests

| File | Tests | Covers |
|---|---:|---|
| `test_close_math.py` | 30 | Pure math + extract_close_legs |
| `test_close_helper.py` | 16 | Helper contract + atomicity |
| `test_reconciler_multileg_sign_convention.py` | 10 | Reconciler integration + PYPL regression |
| `test_exit_evaluator_close_pipeline.py` | 16 | Internal-fill + reason mapping |
| `test_orphan_repair_close_pipeline.py` | 6 | Orphan repair close + latent mleg guard |
| `test_commit_fill_close_pipeline.py` | 6 | Manual close + autopilot close |
| `test_pr6_close_path_invariants.py` | 13 | Cross-cutting structural guarantees |
| **Total** | **97** | |

---

## 8. Contact / Escalation

- On-call runbook: `docs/ops_verification_go_live.md`
- Historical context: CLAUDE.md "Bugs Fixed" section, git log for
  range `90e17ef..2295b51` on branch `feat/pr6-close-path-consolidation`
- The 5 incidents that motivated this PR:
  PYPL cfe69b28 (2026-04-17), NFLX 846bc787 (2026-04-16),
  alpaca close filled / paper_positions open (2026-04-15),
  `_close_position` leg side/action inversion (2026-04-13),
  ghost-position reconcile (2026-04-16).
