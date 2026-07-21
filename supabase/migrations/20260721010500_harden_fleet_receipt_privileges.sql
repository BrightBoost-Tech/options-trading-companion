-- =============================================================================
-- Lane B — fleet_reconciliation_receipts privilege hardening
-- =============================================================================
-- NOT APPLIED BY THIS PR. Additive privilege change only; NO data change, NO
-- row read/written, NO fleet/policy/activation effect. Requires
-- 20260720140000_fleet_reconciliation_receipts.sql applied first. Ordered
-- strictly after the Lane-A writer (20260721010000) so the final grant re-assert
-- reflects the intended writer surface.
--
-- WHY (read-only DB adjudication, 2026-07-20): the D1 migration ran
--   REVOKE ALL ... FROM PUBLIC, anon, authenticated;
--   GRANT SELECT, INSERT ... TO service_role;
-- but service_role STILL holds arwdDxtm (ALL: INSERT/SELECT/UPDATE/DELETE/
-- TRUNCATE/REFERENCES/TRIGGER) on the table. The `GRANT SELECT, INSERT` was a
-- redundant no-op because a schema-wide default privilege had ALREADY granted
-- service_role EVERYTHING at CREATE-TABLE time:
--   ALTER DEFAULT PRIVILEGES IN SCHEMA public
--     GRANT ALL ON TABLES TO anon, authenticated, service_role;   -- (pre-existing)
-- verified via pg_default_acl (grantors postgres AND supabase_admin, objtype 'r',
-- acl arwdDxtm) and pg_class.relacl {service_role=arwdDxtm/postgres}.
--
-- THE HOLE THIS CLOSES: the D1 append-only trigger fires BEFORE UPDATE OR DELETE
-- FOR EACH ROW — it does NOT fire on TRUNCATE (a statement-level DDL-ish op).
-- So a service_role holding the TRUNCATE grant could ERASE every receipt,
-- bypassing immutability entirely. Revoking TRUNCATE (plus UPDATE/DELETE/
-- REFERENCES/TRIGGER) from service_role leaves EXACTLY {SELECT, INSERT} — the
-- surface the Lane-A writer RPC needs (SELECT for the idempotency read + the
-- activation RPC's existence check; INSERT for the receipt) and nothing else.
--
-- DEFAULT-PRIVILEGE DURABILITY (the "silently restores them?" check): ALTER
-- DEFAULT PRIVILEGES applies ONLY at object-CREATION time. It does not re-apply
-- to an existing table, so a plain REVOKE on this already-created table is
-- durable — nothing silently re-grants it. This migration deliberately does NOT
-- touch schema-wide ALTER DEFAULT PRIVILEGES (that would change every future
-- table + other migrations — out of scope, and unnecessary for this table).
--
-- Defense-in-depth: we also add a BEFORE TRUNCATE statement-level trigger so
-- immutability holds against TRUNCATE even if a future migration or default-
-- privilege change ever re-grants TRUNCATE to some role (the D1 row trigger
-- cannot see TRUNCATE). Combined, the table is immutable by BOTH privilege and
-- trigger.
-- =============================================================================

-- ── 1. Privilege hardening: land service_role on exactly {SELECT, INSERT} ────
-- Revoke the erase/mutate/DDL-adjacent privileges the default ACL granted.
REVOKE TRUNCATE, UPDATE, DELETE, REFERENCES, TRIGGER
    ON TABLE fleet_reconciliation_receipts FROM service_role;

-- Defensive: PUBLIC/anon/authenticated must hold nothing (D1 revoked ALL from
-- them; re-assert so an intervening default-privilege grant can't have leaked).
REVOKE ALL ON TABLE fleet_reconciliation_receipts FROM PUBLIC, anon, authenticated;

-- Re-assert the intended writer surface (idempotent).
GRANT SELECT, INSERT ON TABLE fleet_reconciliation_receipts TO service_role;

-- ── 2. Defense-in-depth: block TRUNCATE via a statement-level trigger ────────
-- The D1 row trigger only covers UPDATE/DELETE. TRUNCATE needs its own
-- statement-level guard so the table cannot be emptied even by a role that
-- (re)acquires the TRUNCATE grant. Fixed, safe search_path.
CREATE OR REPLACE FUNCTION fleet_reconciliation_receipts_no_truncate()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION
        'fleet_reconciliation_receipts is append-only: TRUNCATE is not permitted '
        '(a receipt is an immutable record of a completed reconciliation)'
        USING ERRCODE = 'restrict_violation';
    RETURN NULL;  -- unreachable; the RAISE aborts.
END;
$$;

DROP TRIGGER IF EXISTS trg_fleet_recon_receipts_no_truncate
    ON fleet_reconciliation_receipts;

CREATE TRIGGER trg_fleet_recon_receipts_no_truncate
    BEFORE TRUNCATE ON fleet_reconciliation_receipts
    FOR EACH STATEMENT
    EXECUTE FUNCTION fleet_reconciliation_receipts_no_truncate();

COMMENT ON FUNCTION fleet_reconciliation_receipts_no_truncate() IS
    'Append-only guard: blocks TRUNCATE on fleet_reconciliation_receipts for all '
    'roles (the D1 BEFORE UPDATE OR DELETE row trigger does not fire on '
    'TRUNCATE). Belt-and-suspenders alongside the Lane-B privilege revoke.';
