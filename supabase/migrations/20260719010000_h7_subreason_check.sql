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
-- exactly one typed detail->>'h7_subreason'. No new disposition VALUES are
-- added (the 10-value CHECK in
-- 20260717100000_candidate_terminal_dispositions.sql is untouched), so
-- backward-compatible `WHERE disposition='h7_dropped'` queries are unchanged.
--
-- ── ALLOWLIST = 5 canonical + the 'unspecified' sentinel (SIX total) ──
-- The five canonical values are the writer's H7_SUBREASONS frozenset
-- (roundtrip_bp | quality_gate | sizing_zero | risk_budget | account_capacity),
-- pinned set-equal by test_h7_subreason_migration_contract.py (the same
-- anti-drift discipline the DISPOSITIONS contract test enforces). The sixth,
-- 'unspecified', is the writer's HONEST soft-fail marker: when a (buggy,
-- un-typed) PRODUCTION call site slips past the strict dev/test raise, the
-- writer counts a writer_taxonomy_violation, stamps h7_subreason='unspecified'
-- + h7_subreason_violation=true, and STILL writes the row. The sentinel is
-- allow-listed ON PURPOSE so that soft-fail row is ACCEPTED even with this
-- constraint live — the one-final-per-candidate invariant GENUINELY always
-- wins. (If the sentinel were rejected, the writer's demote-then-retry
-- fallback would first demote a prior final to superseded_retry and then fail
-- the retry, leaving the identity with ZERO active finals — the exact gap the
-- table exists to close. Proven on live PG by the #1281 reviewer.) Violations
-- stay fully queryable and never silent:
--     ... WHERE detail->>'h7_subreason_violation' = 'true'
--     ... WHERE detail->>'h7_subreason'           = 'unspecified'
-- and writer_taxonomy_violation is 0 in normal operation (the strict dev/test
-- raise keeps every shipped call site canonical), so 'unspecified' is never
-- actually written outside a genuine regression.
--
-- ── PRESENCE enforcement (COALESCE) ──
-- (detail->>'h7_subreason') is NULL when the key is ABSENT, and `NULL IN (…)`
-- evaluates to NULL — and a CHECK treats NULL as PASS — so a bare h7_dropped
-- row with NO subreason key would slip through. COALESCE(…, '') maps a missing
-- key to '' (not in the allowlist) → the row is REJECTED. Net semantics: an
-- h7_dropped final must carry an h7_subreason KEY *and* its value must be one
-- of {5 canonical, unspecified}.
--
-- ── APPLY SEMANTICS (NOT VALID — corrected) ──
-- ADD CONSTRAINT … NOT VALID ENFORCES ON EVERY NEW WRITE IMMEDIATELY at ADD
-- time. NOT VALID only skips the one-time scan of PRE-EXISTING rows (so adding
-- it never locks/fails the table on legacy data). A later
--     ALTER TABLE candidate_terminal_dispositions
--       VALIDATE CONSTRAINT ctd_h7_subreason_required;
-- scans ONLY those pre-existing rows; it changes NOTHING about new-write
-- enforcement and NOTHING about the sentinel (allow-listed, accepted at all
-- times, before and after VALIDATE). PREFLIGHT: the table is empty (Supabase
-- 07-18: 0 rows) and every writer-produced row from Monday-forward is already
-- typed, so VALIDATE is expected to pass immediately; run it after a soak if
-- preferred.
--
-- Purely ADDITIVE: one CHECK on the new Lane-4B table. No DDL against any
-- other table; no new column; no FK.

ALTER TABLE candidate_terminal_dispositions
  ADD CONSTRAINT ctd_h7_subreason_required
  CHECK (
    disposition <> 'h7_dropped'
    OR COALESCE(detail->>'h7_subreason', '') IN (
      'roundtrip_bp',
      'quality_gate',
      'sizing_zero',
      'risk_budget',
      'account_capacity',
      'unspecified'
    )
  )
  NOT VALID;

COMMENT ON CONSTRAINT ctd_h7_subreason_required
  ON candidate_terminal_dispositions IS
  'Owner 2026-07-18 (H7_DROPPED_PARENT_PLUS_TYPED_SUBREASON): every h7_dropped '
  'final must carry a PRESENT detail->>''h7_subreason'' whose value is one of '
  'the five canonical subreasons OR the writer soft-fail sentinel '
  '''unspecified'' (allow-listed so the one-final invariant always wins). '
  'Writer-first backstop; enforces on every NEW write at ADD time (NOT VALID '
  'skips only the pre-existing-row scan).';
