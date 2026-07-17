# Migration Apply Procedure

Supabase migrations in this repo do NOT auto-apply on merge. The
deploy pipeline ships code only — schema changes require a human
operator to apply the SQL manually.

Discovered 2026-04-23 during PR #6 (#796) — the Phase 1 migration
merged with the code but was never applied to production. This gap
has existed for the entire life of the repo (84 of 85 prior
migrations were not tracked in `supabase_migrations.schema_migrations`
before 2026-04-23). Auto-apply wiring and drift reconciliation
(329 divergent columns + 12 missing tables vs migration history)
are planned as separate multi-PR efforts — see backlog #62. Until
then, follow the procedure below for every PR that touches
`supabase/migrations/*.sql`.

## Apply checklist

1. **Confirm merge.** PR includes `supabase/migrations/*.sql`. Note
   the merge commit SHA and timestamp (ISO 8601 UTC, from GitHub's
   `mergedAt` field).

2. **Re-inspect the SQL.** Open the migration file on the merged
   `main` branch. Read it end-to-end with fresh eyes. The
   `manual_endpoint` vs `manual_close_user_initiated` bug in PR #6
   Commit 1 survived both code review and a post-merge
   verification-distribution message because reviewers deferred
   to the artifact under review. At apply time, re-derive expected
   behavior from upstream sources (enum definitions in
   `close_helper.py`, the semantic contract) — not from the SQL
   under review.

3. **Apply via `mcp__supabase__apply_migration`** (canonical for
   this repo). Pass the SQL verbatim from the merged file. This
   tool both runs the DDL and records the migration in
   `supabase_migrations.schema_migrations`.

   Alternative: Supabase Dashboard SQL editor (paste + execute).
   Does NOT record in `schema_migrations`; avoid unless the MCP
   path is unavailable.

   If Dashboard is used (emergency / human-without-Claude), the
   operator MUST manually INSERT a corresponding row into
   `supabase_migrations.schema_migrations` after the DDL runs,
   matching the version and name convention. Otherwise the
   audit-trail gap that caused this procedure to exist reproduces.

   DO NOT use `supabase db push` as of 2026-04-23 — with 84
   un-tracked historical migrations on disk, it would attempt to
   re-apply all of them. Resolution tracked in backlog #62.

4. **Verify the apply took effect.** Query the DB for the specific
   constraints / columns the migration introduced. Example for an
   ADD CONSTRAINT migration:

   ```sql
   SELECT conname, pg_get_constraintdef(oid)
   FROM pg_constraint
   WHERE conrelid = '<table>'::regclass
     AND conname = '<new_constraint>';
   ```

5. **Capture deploy-relevant state.** If the migration introduces
   time-sensitive invariants (e.g. PR #6's 48h observation window
   needing `PR6_DEPLOY_TIMESTAMP`), set those env vars on the
   worker service via `mcp__railway-mcp-server__set-variables`
   with `skipDeploys: true`.

6. **Log the apply for audit trail.** Every manual apply from here
   forward becomes queryable:

   ```sql
   INSERT INTO risk_alerts (user_id, alert_type, severity,
                            message, metadata)
   VALUES (
     '<trading account owner UUID>',
     'migration_apply',
     'info',
     'Applied <migration_name>',
     jsonb_build_object(
       'migration_file', 'supabase/migrations/<filename>',
       'commit_sha',     '<merge commit SHA>',
       'applied_at',     NOW()::text,
       'applied_via',    'mcp__supabase__apply_migration',
       'operator',       '<one of: claude_mcp | human_dashboard | human_cli | automation>',
       'operator_note',  '<free-text: who, why, special circumstances>',
       'pr_number',      <PR number>
     )
   );
   ```

   `operator` values:
   - `claude_mcp` — Claude Code via `mcp__supabase__apply_migration`
   - `human_dashboard` — human via Supabase Dashboard SQL editor
   - `human_cli` — human via `supabase` CLI (viable only post-drift-reconciliation)
   - `automation` — future auto-apply mechanism (backlog #62)

7. **Query manual-apply history** (audit surface for future drift
   analysis):

   ```sql
   SELECT metadata->>'migration_file',
          metadata->>'applied_at',
          metadata->>'operator',
          metadata->>'pr_number'
   FROM risk_alerts
   WHERE alert_type = 'migration_apply'
   ORDER BY created_at DESC;
   ```

8. **Update backlog tracker.** After successful apply, search
   CLAUDE.md for the migration's backlog item by file name or
   item number. If found in any *Priority X* or *pending*
   section, move it to *Roadmap → Completed* (or *Bugs Fixed
   (last 30 days)* if the migration also resolves a runtime bug)
   with the apply date and audit reference (`risk_alerts.id` or
   the `migration_apply` row's `applied_at`). If the apply and
   the backlog edit can't happen in the same operator turn, add
   the backlog edit to the next session's first action so it
   doesn't drift.

   The same step should be applied to *PR Merge Procedure* when
   one is formalized — merged PRs that resolve backlog items
   should close those items in CLAUDE.md within the same
   operator turn. This step exists because three closure-
   discipline gaps surfaced this weekend (see *Backlog hygiene
   check 2026-04-27 evening* in the Notable findings section)
   and the underlying pattern is documentation drift, not
   operator error.

## When NOT to apply on merge

If the migration's PR description explicitly states observation-
window sequencing (e.g. "apply after Phase 1 verifies clean at
T+24h"), do NOT apply on merge. Follow the PR's gating exactly.

## Migration-audit methodology: field-level, not filename-level

Discovered 2026-07-16 (PR #1218 `ranking_costs`). PR #1218 began stamping a new
top-level field, `suggestion["ranking_costs"]`, in
`analytics/canonical_ranker.py` but shipped **no migration**. A
filename-vs-history reconciliation (compare `supabase/migrations/*.sql` names
against `supabase_migrations.schema_migrations`) reported **PASS** — there was
no new migration file to be missing — while production silently could not
persist the field: PostgREST returned `PGRST204` ("Could not find the
'ranking_costs' column of 'trade_suggestions' in the schema cache"),
`created=0`, the executor processed 0, the row (with its required cost
provenance) was lost, and `suggestions_open` still completed green.

**The lesson: a filename/history reconciliation cannot see a persisted field
that never got a migration.** The audit must reconcile at the level of the
**payload fields the code actually writes**, against BOTH the repository
schema and the live schema:

1. **Enumerate newly persisted top-level payload fields.** For each table a
   code path inserts/updates, collect the top-level keys the producer stamps
   onto the row dict (e.g. every `suggestion["<field>"] = ...` reaching the
   `trade_suggestions` insert; every `row["<field>"] = ...` reaching its
   table). Diff against the prior revision to find *newly* added fields.

2. **Reconcile each field against the REPOSITORY schema.** The field must have
   a committed column — a `CREATE TABLE`/`ALTER TABLE ... ADD COLUMN` in
   `supabase/migrations/*.sql` — **or** an explicit, sanctioned entry in the
   producer's droppable/strip list (a deliberate degrade-gracefully shim, not
   a silent loss). A field that is neither is the #1218 class: fail the audit.

3. **Reconcile each field against the LIVE schema.** Query
   `information_schema.columns` for the target table and confirm the column is
   actually present in production (repository-committed ≠ applied — see the
   filename/history procedure above). A field committed but unapplied is a
   deploy-ordering gap; a field applied but not committed is drift.

4. **Never accept "no new migration file" as evidence of "no schema change
   needed."** The absence of a migration is exactly the failure signature when
   a persisted field was added without one.

5. **Required-provenance fields are never droppable.** A field that carries
   decision/cost/risk provenance (e.g. `ranking_costs`) must get a real column;
   silently discarding it via the strip list is not an acceptable resolution.

This methodology is enforced in CI by
`packages/quantum/tests/test_ranking_costs_schema_contract.py`, which parses the
canonical ranker's persisted stamps and asserts each has a committed
`trade_suggestions` column (or a sanctioned droppable entry). Extend that
contract test to any other producer/table pair as new persisted fields are
introduced.
