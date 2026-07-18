-- Lane B (funnel taxonomy): mandatory typed h7_subreason on h7_dropped finals.
--
-- FILE-ONLY until the operator applies it. The ACTIVE control is the WRITER
-- (packages/quantum/services/candidate_disposition.py): strict-raise in
-- dev/test (every shipped call site is CI-verified to carry a canonical
-- h7_subreason), fail-soft + counted (writer_taxonomy_violation) in
-- production. This CHECK is a DB-level BACKSTOP the operator opts into.
--
-- OWNER DECISION 2026-07-18 (H7_DROPPED_PARENT_PLUS_TYPED_SUBREASON): keep the
-- parent disposition 'h7_dropped'; require every h7_dropped final to carry
-- exactly one canonical detail->>'h7_subreason' from the five values below.
-- No new disposition VALUES are added (the 10-value CHECK in
-- 20260717100000_candidate_terminal_dispositions.sql is untouched), so
-- backward-compatible `WHERE disposition='h7_dropped'` queries are unchanged.
--
-- ── MIGRATION DECISION: writer-first now, DB CHECK as a NOT VALID backstop ──
-- Chosen over "widen the applied CHECK" because:
--   * The value taxonomy lives in ONE source of truth — the writer's
--     H7_SUBREASONS frozenset — mirrored here and pinned set-equal by
--     test_h7_subreason_migration_contract.py (the same anti-drift discipline
--     the DISPOSITIONS contract test enforces).
--   * ADD CONSTRAINT ... NOT VALID never scans existing rows, so it can land
--     on a live table without a full-table lock or a historical-row failure.
--     PREFLIGHT: candidate_terminal_dispositions is empty / near-empty
--     (Supabase 07-18: 0 rows) and every h7_dropped row the writer produces
--     from Monday-forward already carries a canonical subreason (the strict
--     dev/test raise guarantees it), so a follow-up
--       ALTER TABLE candidate_terminal_dispositions
--         VALIDATE CONSTRAINT ctd_h7_subreason_required;
--     is expected to pass immediately; run it after a soak if preferred.
--
-- ── SENTINEL / INVARIANT NOTE ──
-- The DB allowlist is the FIVE canonical values ONLY (crisp taxonomy). The
-- writer's production soft-fail path stamps detail->>'h7_subreason'
-- ='unspecified' + h7_subreason_violation=true when a (buggy, un-typed) call
-- site slips through. While THIS constraint is unapplied (its indefinite
-- default state) that sentinel row LANDS — the one-final-per-candidate
-- invariant is preserved and the violation is queryable + counted. If the
-- operator later applies + VALIDATEs this constraint, they have opted into
-- strict DB enforcement: a sentinel write is then rejected and counted as a
-- write_failure (the existing invalid-disposition convention — loud, never
-- blocks the cycle). Because the strict dev/test raise keeps every shipped
-- call site typed, writer_taxonomy_violation is 0 in normal operation and the
-- sentinel is never written — this reconciliation is defense-in-depth only.
--
-- Purely ADDITIVE: one CHECK on the new Lane-4B table. No DDL against any
-- other table; no new column; no FK.

ALTER TABLE candidate_terminal_dispositions
  ADD CONSTRAINT ctd_h7_subreason_required
  CHECK (
    disposition <> 'h7_dropped'
    OR (detail->>'h7_subreason') IN (
      'roundtrip_bp',
      'quality_gate',
      'sizing_zero',
      'risk_budget',
      'account_capacity'
    )
  )
  NOT VALID;

COMMENT ON CONSTRAINT ctd_h7_subreason_required
  ON candidate_terminal_dispositions IS
  'Owner 2026-07-18 (H7_DROPPED_PARENT_PLUS_TYPED_SUBREASON): every h7_dropped '
  'final must carry a canonical detail->>''h7_subreason'' (roundtrip_bp | '
  'quality_gate | sizing_zero | risk_budget | account_capacity). Writer-first '
  'backstop; VALIDATE after confirming zero writer_taxonomy_violation.';
