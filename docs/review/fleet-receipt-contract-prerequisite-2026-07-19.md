# Operator Prerequisite Packet — Fleet Reconciliation-Receipt Contract (Scenario 5)

> **DESIGN ONLY. NOT APPLIED. This packet is a prerequisite, not a change.**
> It authorizes nothing, applies no migration, writes no data, and does not
> activate the fleet. Activation remains forbidden to the loop and to every
> agent (operator-only). Until the operator adopts the contract below,
> reconciliation-receipt EXISTENCE cannot be enforced and activation must not
> proceed on receipt existence alone.

**Finding:** V17-2 `F-A8-FLEET-ACTIVATION-ARTIFACT-UNBOUND`, scenario 5
(reconciliation-receipt existence). Lane-2 hardening
(`20260719020000_harden_shadow_fleet_activation_rpc.sql`) closed bypasses
1/2/3/4/6 in-transaction; scenario 5 stays **OPEN** by design because there is
no durable, typed receipt object to bind to today.

---

## 1. What scenario 5 is

The activation attestation must reference the stale-order reconciliation
receipt (CLAUDE.md §4; owner-packet-1 §4). Two receipts are cited:

- `04317fc1…` — the six stale 2026-04-09 `submitted` rows, cancelled.
- `5d5cd9fc…` — the seventh row (`needs_manual_review` 2026-05-11) adjudicated.

**The problem:** these receipts exist today ONLY as `risk_alerts` rows with
`alert_type='migration_apply'` and the fingerprint carried inside
`metadata` (free-form jsonb). There is **no durable, typed, referential
identifier** — no receipt table, no stable id column, no foreign key. So the
strongest check the RPC and `validate_attestation` can make is **non-blank**:

- `validate_attestation` (`shadow_fleet_activation.py`) requires
  `stale_order_reconciliation_receipt` to be a non-blank string.
- The RPC (`20260719020000`) requires the same non-blank reference before it
  will bind.

A syntactically-valid but **fabricated / nonexistent** receipt reference is
therefore **accepted today**. This gap is pinned explicitly by a passing test
(`test_shadow_fleet_activation_binding.py::TestScenario5ReceiptExistenceOpen`)
so it is never silent — it is a known, documented OPEN, not a hidden hole.

**Why we do NOT paper over it now (H9 — never fabricate):** inventing a fake
receipt id, or a foreign key to a receipt object that does not exist, would be
worse than the honest non-blank check. We refuse to fabricate a durable
identity that isn't there.

---

## 2. The smallest immutable receipt contract (proposed — NOT applied)

The minimal contract that makes receipt existence enforceable. **Option A**
(new table) is recommended; **Option B** (typed column) is the lighter
alternative.

### Option A — `fleet_reconciliation_receipts` (recommended)

```sql
-- PROPOSED. NOT APPLIED. Operator applies via the migration procedure only
-- after explicit review. Applying it activates nothing.
CREATE TABLE IF NOT EXISTS fleet_reconciliation_receipts (
    receipt_id        text PRIMARY KEY CHECK (btrim(receipt_id) <> ''),
    receipt_kind      text NOT NULL
        CHECK (receipt_kind IN ('stale_order', 'manual_review', 'orphan_run')),
    content_fingerprint text NOT NULL,     -- the fp already in risk_alerts.metadata
    effective_epoch   text NOT NULL,       -- e.g. small_tier_v1
    source_alert_id   uuid REFERENCES risk_alerts(id),  -- provenance to the existing row
    created_at        timestamptz NOT NULL DEFAULT now(),
    created_by        text
);
-- Immutable after insert (a receipt is a record of a completed reconciliation).
-- Operator-only (service_role) RLS, mirroring policy_registrations.
```

Backfill (operator, one fingerprinted txn): insert one row per existing
`risk_alerts` reconciliation receipt (`04317fc1…`, `5d5cd9fc…`, and the five
orphan-run receipt `40258ba9…` if in scope), copying the fingerprint from
`metadata`. No `risk_alerts` row is rewritten.

**Then the RPC gains one clause** (a follow-up hardening migration, separately
reviewable): the attestation's `stale_order_reconciliation_receipt` must be a
row in `fleet_reconciliation_receipts` whose `receipt_kind='stale_order'` and
`effective_epoch` = the fleet epoch — else RAISE `receipt_not_found`. This
closes scenario 5: nonexistent / wrong-kind / wrong-epoch receipts fail.

### Option B — typed stable id on the reconciliation alert rows (lighter)

Add a `receipt_id text UNIQUE` column to `risk_alerts` (or a narrow companion
table keyed on `risk_alerts.id`), populate it for the reconciliation rows, and
have the RPC validate the attestation reference against that typed id. Less
isolation than Option A (mixes receipts into the alert stream) but no new
table.

---

## 3. Contract the RPC would enforce (once adopted)

| attestation receipt reference | today (OPEN) | after adoption |
|---|---|---|
| blank | REJECT (`attestation_missing_…`) | REJECT (unchanged) |
| non-blank, **nonexistent** | **ACCEPT (the gap)** | REJECT (`receipt_not_found`) |
| non-blank, wrong `receipt_kind` | ACCEPT | REJECT |
| non-blank, wrong `effective_epoch` | ACCEPT | REJECT |
| non-blank, exists + correct kind + epoch | ACCEPT | ACCEPT |

Wrong-user is covered transitively: the fleet activation is already scoped to
`p_user_id`; a receipt contract keyed per epoch + provenance to the
operator-written `risk_alerts` row inherits that scoping.

---

## 4. Sequenced gates (each is a separate operator action)

1. Operator reviews and **decides** Option A vs B.
2. Apply the chosen migration via the migration procedure (schema only —
   activates nothing).
3. Backfill the existing receipts in one fingerprinted transaction (no
   `risk_alerts` rewrite).
4. Ship the follow-up RPC hardening migration adding the `receipt_not_found`
   clause (separately reviewable; re-run the parity/drift-lock tests).
5. Re-run `plan_activation` (dry-run) and confirm the attestation still
   validates against the now-typed receipt.

**Until step 4 merges + deploys, receipt-existence binding is NOT enforced and
activation must not proceed on that basis.** The other five bypasses are
already closed regardless.

---

## 5. What Lane-2 did NOT do (honest boundary)

- Did not invent a receipt id or a foreign key to a nonexistent object.
- Did not apply any migration, write any data, or change any env/flag/fleet
  state.
- Did not weaken the non-blank check (it is the strongest available today).
- Left scenario 5 as a pinned, tested, documented OPEN — the honest state.
