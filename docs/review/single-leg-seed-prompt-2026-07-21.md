# Operator seed prompt — single-leg experiment DRAFT policy rows (2026-07-21)

> **This document performs NOTHING.** It describes the future, explicit,
> operator-authorized registry-write that would seed the four single-leg
> experiment definitions as `draft` rows. No registry row is created, mutated,
> approved, or opted-in by this PR or this document.

## What exists in the repo (this PR)

- **Design/provenance module** —
  `packages/quantum/policy_lab/single_leg_experiment_design.py` (the
  reproducible source of truth; mirrors `fleet_policy_design.py`).
- **Review manifest** —
  `docs/specs/single_leg_experiment_policy_manifest.md` (regenerated, drift-locked).
- **UNAPPLIED seed transaction** —
  `supabase/seed-transactions/policy_registrations_single_leg_experiment.sql`.
- **Tests** — `packages/quantum/tests/test_single_leg_experiment_design.py`.

The four definitions (all `approval_status='draft'`, epoch
`single_leg_experiment_v1`):

| id | role | base anchor | opt-in flag | config_hash |
|---|---|---|---|---|
| `sl_exp_throughput_v1` | experimental | aggressive_anchor | present | `71e854a6e9f098d561748b49161c5997459b4f2a7a19e27eebcb741c1987db5e` |
| `sl_ctrl_throughput_v1` | control | aggressive_anchor | absent | `441ace2f5dc5b7842f6ae41db30db3dcd32ffbb1afa5585794659b04421fb310` |
| `sl_exp_conviction_v1` | experimental | conservative_anchor | present | `59e02e8f09b3030f7fa5f3cd6f281ee42e80100e73f2a6e8fdcfe1e56374cf09` |
| `sl_ctrl_conviction_v1` | control | conservative_anchor | absent | `5f74bffe2d819d850f9c74be992b82f353a0ff15d5d2912abd9fb96502fc7de0` |

The two control hashes are byte-identical to the seeded `aggressive_anchor` /
`conservative_anchor` fleet rows — the distinct epoch (`single_leg_experiment_v1`
≠ `small_tier_v1`) is what keeps `UNIQUE(effective_epoch, config_hash)` from
colliding with the approved 50-policy fleet.

## Why an operator step is required (do NOT auto-apply)

1. **Registry writes are DB rows of record** (doctrine §1, §10). Seeding is a
   production DB mutation via the migration procedure
   (`docs/migration_procedure.md`) — never a build-agent action.
2. **The registry is immutable post-approval** (`20260719000000_policy_registrations`
   trigger). Once approved, a row's `policy_config` / `config_hash` freeze. So the
   seed inserts `draft` rows only; approval is a **separate, later** forward-only
   transition the operator performs deliberately.
3. **Approval is what turns the experiment on.** The generator is dark until an
   **approved** opt-in row exists (`single_leg_experiment.py`). Seeding `draft`
   rows changes nothing at runtime; only a subsequent `draft → approved`
   transition on an opt-in row (plus shadow-only routing + all entry conditions)
   can emit a candidate — and even then, shadow-only, one contract, no broker
   order (execution-seam veto #1292).

## Preconditions the operator confirms before seeding

- `20260719000000_policy_registrations` migration is APPLIED (table + immutability
  trigger + RLS live).
- `pgcrypto` is available in schema `extensions` (the seed derives
  `encode(extensions.digest(config_canonical,'sha256'),'hex')` server-side).
- No existing rows in epoch `single_leg_experiment_v1` (the seed's `DO` block
  asserts exactly 4 for the epoch — pre-existing rows would fail it).
- The committed manifest + seed are current (`test_single_leg_experiment_design.py`
  green, drift-lock passing).

## The authorization (future step — NOT executed here)

When the owner decides to seed these DRAFT definitions, the explicit registry-write
authorization is:

1. **Apply the seed transaction as-is**, through the migration procedure, against
   production Supabase (`etdlladeorfgdmsopzmz`):
   `supabase/seed-transactions/policy_registrations_single_leg_experiment.sql`.
   It runs inside one `BEGIN … COMMIT`; the in-transaction `DO` block re-asserts
   4 rows / 4 distinct hashes / 4 distinct canonicals / hash==digest / **zero
   non-draft rows**, and RAISEs (rolls back) on any breach.
2. **Read-back** after commit:
   ```sql
   SELECT policy_registration_id, approval_status, effective_epoch, config_hash
     FROM policy_registrations
    WHERE effective_epoch = 'single_leg_experiment_v1'
    ORDER BY policy_registration_id;
   ```
   Expect exactly the 4 ids above, all `approval_status='draft'`, hashes matching
   this document.
3. **Record the receipt** (a `risk_alerts` `migration_apply`-style row / ledger
   entry), and mark the seed file **APPLIED — NEVER REAPPLY** in the doctrine
   registry, mirroring the 50-seed convention.

## What is explicitly NOT authorized by seeding

- Approving any row (`draft → approved`) — a distinct, later owner decision.
- Binding any fleet slot to these ids (fleet activation is its own owner-gated,
  irreversible-in-place step; these rows are a **separate epoch** from the fleet
  and are not part of the 50-slot activation manifest).
- Any live flag, threshold, stop, gate, universe, cadence, routing, or broker
  change. The experiment stays shadow-only and DARK until an **approved** opt-in
  row exists.

## Disable / rollback (owner packet 4 §4)

Turn the experiment off by (a) not approving the opt-in draft rows, or (b) if
already approved, transitioning them forward to `retired`/`revoked` (never back to
`draft` — the trigger forbids it). Disable on any of: a `LIVE_ROUTING_FORBIDDEN`
firing on a policy believed shadow-only or any single-leg order reaching broker
submit (structural breach); a persistent independent-EV dark (`EV_UNAVAILABLE`);
or adverse basis-normalized shadow economics vs the cohort's spread structures.
