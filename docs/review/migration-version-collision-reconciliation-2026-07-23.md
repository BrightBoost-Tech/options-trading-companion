# Duplicate Migration-Version Reconciliation & Prevention (Lane C)

Read-only audit + prevention tooling for the `20260723160000` prefix collision.
Base: `main` @ `f8a69334`. All facts below are SELECT-only against production
Supabase + local `supabase` CLI 2.72.7 + local repo tree. **Zero production writes.**

Proof-layer labels per CLAUDE.md §10: `VERIFIED-RUNTIME`, `VERIFIED-CODE`, `VERIFIED-DOCS`.

---

## 1. Executive summary

Three already-applied migration files share the 14-digit prefix `20260723160000`:

| file | objects | PR | merge |
|---|---|---|---|
| `20260723160000_td_scan_observe_tables.sql` | `td_scan_envelopes`, `td_scan_scores` | #1364 | `55be29b3` |
| `20260723160000_regime_v4_comparisons.sql` | `regime_v4_comparisons` | #1365 | `6883a422` |
| `20260723160000_fleet_policy_decision_foundation.sql` | `fleet_policy_decision_runs`, `fleet_policy_decisions` | #1366 | `b96107a3` |

They came from three parallel research / shadow-fleet lanes that each authored a
migration with the same timestamp prefix on 2026-07-23.

**The collision is strictly repo-side / CLI-bootstrap. Production is CLEAN.** The
repo applies migrations by exact NAME via `mcp__supabase__apply_migration`
(docs/migration_procedure.md), which assigns each file its own apply-timestamp
`version` and stores the filename in `name`. Production therefore has three
DISTINCT `schema_migrations` versions and three INDEPENDENT apply receipts. The
five tables all exist and are disjoint. There is nothing to fix in production and
**no `schema_migrations` backfill is advisable or even possible** (see §6).

The hazard is the Supabase CLI: it keys a local migration on the 14-digit
filename prefix, so a fresh `supabase db push` / `db reset` cannot record all
three (the local `schema_migrations` PRIMARY KEY is `version` alone) →
`BLOCKED_TOOLING_COLLISION` (§5). This PR ships a CI linter + reviewed allowlist +
offline audit CLI so a NEW duplicate prefix can never merge unnoticed, and the one
proven legacy collision is pinned by hash + receipt.

---

## 2. Collision inventory (all duplicate prefixes, repo-wide)

Scan scope: flat, lowercase `*.sql` files DIRECTLY under `supabase/migrations/`
(non-recursive), mirroring the Supabase CLI's own migration discovery.
Subdirectories (e.g. the gated `pg/` real-pg suite) and non-`.sql` files are
excluded. Scan of all 149 such files. Duplicate 14-digit prefixes:

```
$ ls supabase/migrations/ | sed -E 's/^([0-9]{14})_.*/\1/' | sort | uniq -d
20260723160000
```

**Exactly ONE duplicate prefix exists.** No other same-prefix pairs. Every one of
the 149 files conforms to `^\d{14}_<slug>.sql` (the linter's
`test_all_real_migrations_have_canonical_14_digit_prefix` asserts this on the live
tree). `VERIFIED-RUNTIME`.

### Full SHA-256 fingerprints (the three collision files)

**Hash basis: SHA-256 over CRLF->LF-normalized bytes** (each `\r\n` replaced by
`\n` before hashing). This equals the LF git-blob digest, so the pin is identical
on Windows (`core.autocrlf` CRLF checkout) and Linux CI (`ubuntu-latest`,
actions/checkout LF checkout). `size_bytes` is the normalized-LF count.

| file | sha256 (normalized-LF) | bytes (LF) |
|---|---|---|
| `20260723160000_td_scan_observe_tables.sql` | `52f7bf2d2f046bb3c5800024095dd63707bec8998bf2fce95f67d37860302553` | 6904 |
| `20260723160000_regime_v4_comparisons.sql` | `4efc5ea84f49f27225322d5124b87f9a8197f5631521b158fc3b36c27e086a94` | 6173 |
| `20260723160000_fleet_policy_decision_foundation.sql` | `278c87107bf4cdf70d5e775bf97741db61f37fce55b57b1ca6127d5a2ff3211a` | 9272 |

`VERIFIED-RUNTIME` — reproduced via `git cat-file blob HEAD:<path> | sha256sum`
(the LF blob CI checks out) and via `sha256_normalized`. These hashes are pinned in
`scripts/migrations/legacy_duplicate_version_allowlist.json` and re-asserted against
the on-disk normalized-LF hash by `test_real_collision_pins_match_git_lf_blobs`.

> Note: an earlier draft of this report pinned CRLF working-tree digests
> (`2cca2cd1…`/`2221fbec…`/`559ce90e…`, sizes 7057/6300/9463 = LF + line-count) and
> labeled them `VERIFIED-RUNTIME` without stating the platform-dependent basis.
> That was corrected here: the pins are now on the platform-independent
> normalized-LF basis, and hashing normalizes line endings before digesting.

---

## 3. Receipts verification (production, SELECT-only)

### 3a. `supabase_migrations.schema_migrations` — tracked by NAME, distinct versions

```sql
SELECT version, name FROM supabase_migrations.schema_migrations
WHERE name IN (
  '20260723160000_td_scan_observe_tables',
  '20260723160000_regime_v4_comparisons',
  '20260723160000_fleet_policy_decision_foundation');
```

| version (MCP-assigned) | name |
|---|---|
| `20260723232856` | `20260723160000_td_scan_observe_tables` |
| `20260723234851` | `20260723160000_regime_v4_comparisons` |
| `20260724003507` | `20260723160000_fleet_policy_decision_foundation` |

Three DISTINCT versions → **no production version collision.** `VERIFIED-RUNTIME`.

### 3b. `risk_alerts` apply receipts — three independent rows

Receipts are keyed under `metadata->>'migration_name'` (NOT `migration_file` — an
initial `migration_file` filter returned `[]`; empty was the wrong key, not
absence).

| risk_alerts.id | migration_name | applied_at (created_at) |
|---|---|---|
| `715f36a9-c5b0-4866-97b1-94a8d61ff87f` | `20260723160000_td_scan_observe_tables` | 2026-07-23 23:29:29Z |
| `56b3f3aa-bceb-4488-a722-d2884305cebe` | `20260723160000_regime_v4_comparisons` | 2026-07-23 23:49:05Z |
| `b2f09517-a830-4a0d-b3a4-06f89fe22253` | `20260723160000_fleet_policy_decision_foundation` | 2026-07-24 00:35:32Z |

Each row's message confirms "0 rows / applied before code merge / fleet inactive".
`VERIFIED-RUNTIME`. **All three collision files have independent applied receipts.**

### 3c. Tables exist in production

```sql
SELECT table_name FROM information_schema.tables
WHERE table_schema='public' AND table_name IN (...);
```

Returns all five: `fleet_policy_decision_runs`, `fleet_policy_decisions`,
`regime_v4_comparisons`, `td_scan_envelopes`, `td_scan_scores`. The apply took
effect. `VERIFIED-RUNTIME`.

---

## 4. Object parity — disjoint by construction

The three files create PAIRWISE-DISJOINT object sets (no shared table / index /
function / trigger / policy name):

- `td_scan_observe_tables` → `td_scan_envelopes`, `td_scan_scores`
- `regime_v4_comparisons` → `regime_v4_comparisons`
- `fleet_policy_decision_foundation` → `fleet_policy_decision_runs`, `fleet_policy_decisions`

Because the sets are disjoint, applying each file exactly once (the name-based
path) creates every object exactly once — there is no double-create. This is
enforced by `check_collision_object_parity` and
`test_collision_files_create_disjoint_objects`. `VERIFIED-CODE` + `VERIFIED-RUNTIME`.

These are NOT alias migrations duplicating DDL; they are three legitimately
independent migrations that happened to share a timestamp.

---

## 5. How the Supabase CLI parses identity — `BLOCKED_TOOLING_COLLISION`

`VERIFIED-RUNTIME` (`supabase` CLI 2.72.7):

```
$ supabase migration list --local | grep 20260723160000
   20260723160000 |                | 2026-07-23 16:00:00
   20260723160000 |                | 2026-07-23 16:00:00
   20260723160000 |                | 2026-07-23 16:00:00
```

The CLI renders version `20260723160000` **three times** (one row per file, keyed
on the 14-digit prefix), each with an EMPTY `Remote` column — because production
tracks them under `20260723232856 / …234851 / …003507`, which the CLI does not
recognize as this local version.

The local bookkeeping table's PRIMARY KEY is `version` alone:

```
pk_cols = version
columns = version:text, statements:ARRAY, name:text
```

So a fresh CLI bootstrap (`supabase db push` / `db reset`) that tried to record
all three would hit a `version`-PK conflict on the 2nd file. **The standard CLI
cannot support this collision** → `BLOCKED_TOOLING_COLLISION`. `VERIFIED-RUNTIME`.

This matches the repo's own guidance: docs/migration_procedure.md explicitly says
**"DO NOT use `supabase db push`"** (84+ untracked historical migrations would
re-apply), and CLAUDE.md §8 says "match files ↔ tracking by NAME not version
prefix."

### Safe bootstrap path (design — documented, not executed)

The repo's SUPPORTED bootstrap is name-based per-file apply via
`mcp__supabase__apply_migration`, under which each file lands exactly once (the
production proof in §3). No CLI change is required for the supported path. If a
future contributor ever needs a CLI-driven fresh install, the ONLY collision-safe
options are:

1. **Preferred — never let it recur:** the linter in this PR fails CI on any NEW
   duplicate prefix, forcing a rename to a unique prefix BEFORE apply (safe,
   because the file is not yet applied anywhere).
2. **For the existing three (already applied — do NOT rename):** a CLI bootstrap
   would have to apply each file's SQL and insert a UNIQUE local `version`
   matching production's MCP-assigned version (`…232856 / …234851 / …003507`).
   This is a bespoke seed, not `db push`; it is out of scope here and unnecessary
   because production already tracks them correctly. Renaming/reapplying the
   applied files is prohibited.

---

## 6. Operator packet — migration-history backfill assessment

**Recommendation: NO backfill. None is advisable, and none is safe.**

Reasoning:

- Production `schema_migrations` already tracks all three by NAME with three
  DISTINCT versions (§3a). There is no missing row and no drift to repair.
- Three independent `risk_alerts` apply receipts already exist (§3b).
- You **cannot** add local-tracking rows keyed on `20260723160000` for all three:
  the `schema_migrations` PK is `version`, so three rows with that same version
  are impossible (that is the very collision). Production's existing distinct
  versions are the correct, only-workable representation.
- The residual `supabase migration list` cosmetic drift (three local rows show an
  empty Remote column, §5) is ACCEPTED and now documented. It is not a data
  integrity problem; it must not be "fixed" by renaming, reapplying, or pushing.

If, and only if, the team later wants `supabase migration list` cosmetics to
reconcile, that is a bespoke local-seed exercise (§5, option 2) — still no
production write, still never a rename/reapply. This PR deliberately does not
perform it.

---

## 7. What this PR ships (prevention)

| deliverable | path |
|---|---|
| Offline audit CLI + linter core (stdlib-only) | `scripts/migrations/migration_version_audit.py` |
| Reviewed legacy allowlist (hashes + receipts + never-reapply) | `scripts/migrations/legacy_duplicate_version_allowlist.json` |
| Offline remote-history snapshot fixture (no live DB from CI) | `scripts/migrations/remote_history_snapshot.example.json` |
| CI test gate + 7 required cases + parity + offline proof | `packages/quantum/tests/test_migration_version_collision.py` |
| This report | `docs/review/migration-version-collision-reconciliation-2026-07-23.md` |

The linter fails CI on: a NEW unallowlisted duplicate prefix; an allowlisted file
whose hash drifted; an allowlisted file missing on disk; an allowlist entry
missing its durable apply receipt; and two colliding files that create the same
object. It PASSES the one reviewed legacy collision only with exact hash matches.

Run locally:

```
python -m scripts.migrations.migration_version_audit --format text
python -m scripts.migrations.migration_version_audit \
  --remote-snapshot scripts/migrations/remote_history_snapshot.example.json --format json
```

The audit performs ZERO network/DB calls — `test_audit_module_imports_no_db_or_network`
AST-scans the module and asserts no `supabase`/`psycopg`/`requests`/`socket`/… import.

### Allowlist additions are a HUMAN-REVIEW gate (not a cryptographic one)

The offline linter verifies the sha256 pin and that the receipt-id field is
present, but it **cannot** cryptographically prove that a claimed
`apply_receipt_risk_alert_id` / `applied_version` actually exists in production.
Any NEW allowlist entry MUST therefore be justified by re-running the documented
read-only production SELECTs (§3: `schema_migrations` by name + `risk_alerts`
`alert_type='migration_apply'` by `migration_name`) and a human reviewer must
confirm those receipts before approving. The JSON alone is not proof; this is
stated in the allowlist's `_human_review_requirement` field.
