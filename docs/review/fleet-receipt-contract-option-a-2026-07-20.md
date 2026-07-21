# Fleet Reconciliation-Receipt Contract — Option A (Lane-D build, 2026-07-20)

> **DESIGN / DRAFT-PR ONLY. NOT APPLIED. Activation remains FORBIDDEN.**
> Two migrations + one operator backfill artifact + Python/service/test updates.
> Nothing here applies a migration, writes a production row, backfills, or
> activates the fleet. Fable applies by exact name after review.

Closes scenario 5 (`F-A8-FLEET-ACTIVATION-ARTIFACT-UNBOUND`, reconciliation-
receipt EXISTENCE) — the last OPEN bypass after Lane-2 hardening
(`20260719020000`). The operator selected **Option A** (a new immutable typed
table) from the prerequisite packet (`fleet-receipt-contract-prerequisite-2026-07-19.md`).

## B4 finding — read-only DB adjudication (2026-07-20)

The four completed 07-18 reconciliations exist ONLY as scattered content-stamps
with **no stable typed identity, no typed receipt_kind, no typed effective_epoch**
anywhere. `reconciliation_audit` (referenced in prose) **does not exist**; none of
the fingerprints are in `risk_alerts`.

| fp prefix | durable source | stored token form | user scope |
|---|---|---|---|
| `04317fc1…` (6 stale orders) | `paper_orders.cancelled_reason` / `broker_response` | 12-char prose prefix in cancelled_reason; 64-char run only in broker_response **prose** (no typed key) | `paper_orders.user_id` present |
| `5d5cd9fc…` (7th row, manual review) | `paper_orders.broker_response` | 64-char run in **prose** only (no typed key) | `paper_orders.user_id` present |
| `40258ba9…` (5 orphan job_runs) | `job_runs.error.reconciliation.census_fingerprint` | **16-char TRUNCATED** typed field | **`job_runs` has NO user_id/portfolio_id column** |
| `b780271c…` (credit-sign) | `paper_ledger.metadata.census_fingerprint` | **full 64-char** typed field (plan-content stamp shared by 19 rows) | `paper_ledger.user_id` present |

## D1 — `20260720140000_fleet_reconciliation_receipts.sql` (schema)

Immutable, typed, operator-only receipt table.
- `receipt_id` PK (non-blank); `user_id` NOT NULL; `receipt_kind` CHECK
  {stale_order, manual_review, orphan_run}; `content_fingerprint` NOT NULL +
  **length ≥ 32** (a truncated prefix can never pose as the full token);
  `effective_epoch` NOT NULL.
- **Provenance decision — typed `source_ref`, NOT a hard FK.** B4 proves no
  single canonical table holds these stamps, so a hard FK to `risk_alerts` is
  impossible. The table supports **both**: a *nullable* `source_alert_id` FK to
  `risk_alerts(id)` (for alert-originated receipts, e.g. the activation audit
  row) **and** a typed `source_ref` triple (`source_table` + `source_row_id` +
  `source_fingerprint`) for scattered domain-table stamps. A CHECK requires at
  least one form. We do **not** fabricate a FK to a nonexistent object (H9).
- Append-only: a `BEFORE UPDATE OR DELETE` trigger RAISEs for **all** roles
  (service_role included) — true immutability, not just RLS. Fixed safe
  `search_path` on the trigger fn.
- `UNIQUE (receipt_kind, content_fingerprint)` (backfill idempotency key);
  partial `UNIQUE (source_alert_id)` (source-alert uniqueness); service_role-only
  RLS + `GRANT SELECT, INSERT` (no UPDATE/DELETE grant).

## D2 — backfill preflight → **BLOCKED_RECEIPT_ID_NOT_DURABLE**

`supabase/backfills/20260720140500_fleet_reconciliation_receipts_backfill.sql`
(operator artifact, **outside** `migrations/`). A source row is ELIGIBLE only
when all seven are independently proven from durable data (exact row, **full
stable receipt token** not derived from a displayed prefix, content fingerprint,
typed receipt kind, user scope, effective epoch, completed semantics).

**Verdict: no row qualifies.** The **exact missing token** for all four is a
durable, typed **receipt IDENTITY** (`receipt_id`) — distinct from the plan
content fingerprint — plus a typed `receipt_kind` and typed `effective_epoch`,
none of which is durably present. Additionally: `40258ba9…` is truncated (16 <
32) and `job_runs` carries no user scope; `04317fc1…`/`5d5cd9fc…` live only as
prose. Manufacturing an id/kind/epoch would fabricate identity that isn't there
(H9 / prerequisite §1).

The backfill is a real idempotent fingerprinted transaction that inserts
**0 rows** (every candidate hard-marked `eligible=false` with its missing-proof
reason; `ON CONFLICT (receipt_kind, content_fingerprint) DO NOTHING`), asserts
before==after, and writes one `risk_alerts` audit receipt recording the verdict +
a derived preflight fingerprint. Rollback script included for the eligible path.

## D3 — `20260720150000_bind_fleet_activation_to_receipts.sql` (RPC binding)

`CREATE OR REPLACE`s `rpc_shadow_fleet_activate` — **signature UNCHANGED**
(5-arg; the receipt bundle rides inside `p_attestation` jsonb, so no new overload
and no bypass surface). The pre-hardening 4-arg overload is defensively
re-dropped.
- **Smallest honest contract:** the attestation must carry a typed
  `reconciliation_receipts` bundle (array of `{receipt_id, receipt_kind,
  content_fingerprint}`). Each element must resolve to **exactly one**
  `fleet_reconciliation_receipts` row for `p_user_id` + fleet epoch + kind +
  content_fingerprint **with present provenance**, else `receipt_not_found`.
  `REQUIRED_KINDS = {stale_order, manual_review}` must both be covered
  (`reconciliation_receipt_kind_missing`) — the second prerequisite is never
  silently ignored. (orphan_run is job_runs hygiene, not an order/position
  terminal-boundary prerequisite: validated if listed, not required.)
- Every prior gate preserved verbatim (registry COLLATE-"C" binding, manifest
  fingerprint, 50-slot/$2k, shadow_only, legacy-terminal, DB-now(), all-or-
  nothing 50-binding, service_role-only, legacy rows never rewritten).
- **Fail-closed:** with the receipt table empty (D2 BLOCKED), every attestation
  now RAISEs `receipt_not_found` → activation stays fail-closed and FORBIDDEN
  until a proper receipt-writer creates a durable receipt.

Python (`shadow_fleet_activation.py`): `validate_attestation` requires + validates
the bundle STRUCTURE (existence is the RPC's authority); `execute_activation`
threads it into `p_attestation`; `plan_activation` reports count/kinds. New
constants `RECONCILIATION_RECEIPT_KINDS`, `REQUIRED_RECEIPT_KINDS`,
`MIN_CONTENT_FINGERPRINT_LEN`.

## Tests

`test_shadow_fleet_receipt_binding.py` (new): SQL-mirror of the RPC receipt
clauses (nonexistent / wrong user / wrong kind / wrong epoch / wrong fingerprint /
missing provenance / missing required kind / empty bundle → reject; exact valid →
pass; direct service-role bypass on empty table → still gated) + real service
preflight (structure rejects zero-RPC; server receipt_not_found leaves 0 writes,
fleet inactive) + D1/D3/D2 migration drift-locks. The scenario-5 OPEN pin in
`test_shadow_fleet_activation_binding.py` is inverted to CLOSED. All existing
fleet tests updated for the new required bundle field. **NEVER the production
RPC; zero production writes.**
