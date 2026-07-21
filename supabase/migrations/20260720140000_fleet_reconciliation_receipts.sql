-- =============================================================================
-- Option A — fleet_reconciliation_receipts (immutable, typed receipt contract)
-- V17-2 F-A8-FLEET-ACTIVATION-ARTIFACT-UNBOUND, scenario 5 (receipt EXISTENCE).
-- =============================================================================
-- NOT APPLIED BY THIS PR. Schema only. Applying it creates the empty receipt
-- table + append-only trigger + service_role RLS; it registers NO receipt,
-- binds NO fleet slot, and activates NOTHING. The fleet stays INACTIVE and
-- activation remains operator-only + FORBIDDEN to the loop.
--
-- WHY (the B4 finding — read-only DB-verified 2026-07-20): the four completed
-- 07-18 reconciliations (stale-order fp 04317fc1…, seventh-row manual-review fp
-- 5d5cd9fc…, orphan-run fp 40258ba9…, credit-sign fp b780271c…) exist today ONLY
-- as scattered CONTENT-STAMPS, in heterogeneous forms and NO stable typed
-- identity:
--   * 04317fc1  → paper_orders.cancelled_reason (12-char prose prefix
--                 "…(fp 04317fc1d91b)…") + a 64-char run inside broker_response
--                 PROSE (no typed key).
--   * 5d5cd9fc  → paper_orders.broker_response PROSE only (no typed key).
--   * 40258ba9  → job_runs.error.reconciliation.census_fingerprint — a TYPED
--                 field but only 16 chars (TRUNCATED); job_runs carries no
--                 user_id/portfolio_id column at all (no durable user scope).
--   * b780271c  → paper_ledger.metadata.census_fingerprint — full 64-char typed.
-- NONE appear in risk_alerts; the reconciliation_audit table referenced in prose
-- does NOT exist. There is no receipt_id, receipt_kind, or effective_epoch typed
-- column anywhere. So the strongest check the activation RPC can make today is
-- NON-BLANK (scenario 5 OPEN). This table is the durable, typed identity that
-- makes receipt EXISTENCE enforceable — WITHOUT fabricating identity that isn't
-- there (H9): the backfill inserts ONLY rows whose full identity is durably
-- present, and the 07-18 stamps do NOT qualify (see the D2 preflight verdict
-- BLOCKED_RECEIPT_ID_NOT_DURABLE, supabase/backfills/…).
--
-- PROVENANCE — FK vs typed source_ref (decision): a single canonical alert
-- table does NOT hold these content-stamps (B4), so a HARD FK to risk_alerts is
-- IMPOSSIBLE for reconciliation receipts. Two provenance forms are supported and
-- at least one is REQUIRED (CHECK): (a) source_alert_id — a NULLABLE FK to
-- risk_alerts(id), valid for receipts that DO originate from an alert row (e.g.
-- the shadow_fleet_activated audit row); (b) a typed source_ref triple
-- (source_table + source_row_id + source_fingerprint) — the durable pointer to a
-- scattered domain-table content-stamp when no alert row owns it. We do NOT
-- fabricate a FK to a nonexistent canonical receipt object.
-- =============================================================================

CREATE TABLE IF NOT EXISTS fleet_reconciliation_receipts (
    -- Stable receipt identity (PK). Non-blank. A receipt is a record of ONE
    -- completed reconciliation; the id is the durable token an activation
    -- attestation references. It is NEVER derived from a displayed/truncated
    -- prefix — the backfill proves a FULL durable token before inserting.
    receipt_id          text PRIMARY KEY CHECK (btrim(receipt_id) <> ''),

    -- Explicit user scope (NEVER defaulted). The activation RPC binds a receipt
    -- to p_user_id, so a receipt for one operator can never satisfy another.
    user_id             uuid NOT NULL,

    -- Typed reconciliation class. Closed allowlist; extend only by migration.
    receipt_kind        text NOT NULL
        CHECK (receipt_kind IN ('stale_order', 'manual_review', 'orphan_run')),

    -- The plan/content fingerprint of the completed reconciliation. Non-blank
    -- AND FULL: a full SHA-256 hex is 64 chars; we floor at 32 so a truncated
    -- display prefix (8/12/16-char) can never be stored as if it were the full
    -- token (this is the structural teeth behind the D2 durability rule).
    content_fingerprint text NOT NULL
        CHECK (btrim(content_fingerprint) <> ''
               AND char_length(content_fingerprint) >= 32),

    -- Explicit epoch scope (NEVER defaulted). The activation binding requires
    -- effective_epoch = the fleet epoch; a legacy-book receipt with no epoch can
    -- never bind a fleet-epoch activation.
    effective_epoch     text NOT NULL CHECK (btrim(effective_epoch) <> ''),

    -- Provenance form (a): nullable FK to the originating alert row, when one
    -- exists. Not all receipts have an alert row (B4), hence nullable.
    source_alert_id     uuid REFERENCES risk_alerts(id),

    -- Provenance form (b): typed pointer to a scattered domain-table stamp.
    source_table        text,
    source_row_id       text,
    source_fingerprint  text,

    created_at          timestamptz NOT NULL DEFAULT now(),
    created_by          text,

    -- At least one durable provenance form must be present — a receipt must
    -- point back to what it records; identity is never free-floating.
    CONSTRAINT fleet_recon_receipt_provenance_present CHECK (
        source_alert_id IS NOT NULL
        OR (btrim(coalesce(source_table, '')) <> ''
            AND btrim(coalesce(source_row_id, '')) <> '')
    ),

    -- One receipt per (kind, content fingerprint): the idempotency key the
    -- backfill's ON CONFLICT DO NOTHING keys on (replay = zero writes).
    CONSTRAINT fleet_recon_receipt_kind_fp_unique
        UNIQUE (receipt_kind, content_fingerprint)
);

-- source_alert uniqueness: an alert row can back at most ONE receipt (partial —
-- only when alert-originated). Two receipts can never claim the same alert.
CREATE UNIQUE INDEX IF NOT EXISTS ux_fleet_recon_receipts_source_alert
    ON fleet_reconciliation_receipts (source_alert_id)
    WHERE source_alert_id IS NOT NULL;

-- Durable domain-provenance uniqueness (partial — only when source_ref present).
CREATE UNIQUE INDEX IF NOT EXISTS ux_fleet_recon_receipts_source_ref
    ON fleet_reconciliation_receipts (source_table, source_row_id, content_fingerprint)
    WHERE source_table IS NOT NULL;

-- Lookup path for the activation binding (user + epoch + kind).
CREATE INDEX IF NOT EXISTS idx_fleet_recon_receipts_user_epoch_kind
    ON fleet_reconciliation_receipts (user_id, effective_epoch, receipt_kind);

-- ── Append-only immutability: no UPDATE, no DELETE of receipt truth ──────────
-- A receipt is a permanent record of a completed reconciliation. This trigger
-- blocks EVERY UPDATE and DELETE for ALL roles (service_role included) — RLS
-- alone would still permit service_role to mutate/erase, so the trigger is the
-- real immutability. Fixed, safe search_path.
CREATE OR REPLACE FUNCTION fleet_reconciliation_receipts_immutable()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION
        'fleet_reconciliation_receipts is append-only: % is not permitted on '
        'receipt % (a receipt is an immutable record of a completed '
        'reconciliation)',
        TG_OP, coalesce(OLD.receipt_id, NEW.receipt_id)
        USING ERRCODE = 'restrict_violation';
    RETURN NULL;  -- unreachable; the RAISE aborts.
END;
$$;

DROP TRIGGER IF EXISTS trg_fleet_recon_receipts_immutable
    ON fleet_reconciliation_receipts;

CREATE TRIGGER trg_fleet_recon_receipts_immutable
    BEFORE UPDATE OR DELETE ON fleet_reconciliation_receipts
    FOR EACH ROW
    EXECUTE FUNCTION fleet_reconciliation_receipts_immutable();

-- ── Row-level security: operator-only (service_role), mirrors policy_registrations
ALTER TABLE fleet_reconciliation_receipts ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Service role full access fleet_reconciliation_receipts"
    ON fleet_reconciliation_receipts;

CREATE POLICY "Service role full access fleet_reconciliation_receipts"
    ON fleet_reconciliation_receipts FOR ALL
    USING (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

-- Grants: service_role only. INSERT is allowed (append-only writes); the trigger
-- blocks UPDATE/DELETE regardless of grant.
REVOKE ALL ON TABLE fleet_reconciliation_receipts FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT ON TABLE fleet_reconciliation_receipts TO service_role;

-- ── Documentation ────────────────────────────────────────────────────────────
COMMENT ON TABLE fleet_reconciliation_receipts IS
    'Immutable, typed record of a COMPLETED fleet-prerequisite reconciliation. '
    'Append-only (trigger blocks UPDATE/DELETE for all roles). Operator-only '
    '(service_role) RLS. The activation RPC validates an attestation''s receipt '
    'reference against a row here (exists + user + epoch + kind + content '
    'fingerprint) to close scenario 5. Provenance is a nullable risk_alerts FK '
    'OR a typed source_ref triple (the reconciliation stamps are scattered '
    'across paper_orders/job_runs/paper_ledger — no single canonical table, so '
    'no hard FK is possible; see the D1 header + the D2 preflight).';
COMMENT ON COLUMN fleet_reconciliation_receipts.receipt_id IS
    'Stable receipt identity (PK). Never derived from a displayed/truncated '
    'fingerprint prefix — the backfill proves a FULL durable token first.';
COMMENT ON COLUMN fleet_reconciliation_receipts.content_fingerprint IS
    'Full plan/content fingerprint of the reconciliation (SHA-256 hex = 64 '
    'chars; CHECK floors length at 32 so a truncated prefix can never pose as '
    'the full token).';
COMMENT ON COLUMN fleet_reconciliation_receipts.effective_epoch IS
    'Epoch this receipt is valid for (e.g. small_tier_v1). The activation '
    'binding requires this to equal the fleet epoch.';
COMMENT ON COLUMN fleet_reconciliation_receipts.source_alert_id IS
    'Provenance (a): nullable FK to the originating risk_alerts row, when one '
    'exists. Nullable because reconciliation stamps are frequently NOT in '
    'risk_alerts (B4 finding).';
COMMENT ON COLUMN fleet_reconciliation_receipts.source_table IS
    'Provenance (b): the durable domain table carrying the content-stamp '
    '(paper_orders / job_runs / paper_ledger), paired with source_row_id + '
    'source_fingerprint when no alert row owns the receipt.';
