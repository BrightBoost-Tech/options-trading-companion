# F-BAN-INTEGRITY — Operator Decision Packet (2026-07-16)

**Status: DECISION PENDING. No implementation authorized by this document.**
Evidence basis: Fable-5 audit at `b95d3a3` (results doc §H12) — all
`VERIFIED-CODE`/`VERIFIED-DB`, re-verified 2026-07-16.

## The facts

`settings.banned_strategies` is a phantom feature: no migration defines the
column (repo-wide grep of `supabase/migrations/`); the production column exists
as untracked drift (ARRAY, `settings` has **0 rows**); the sole reader
(`workflow_orchestrator.py:2549-2563`) silently degrades to `[]` at
`logger.debug`; there is **no write surface** (no UI/API/SQL). Downstream
enforcement (StrategyPolicy → selector ban+fallback → scanner recheck) is real,
live-routed, and permanently fed `[]`. A ban has never existed and cannot be
created today.

## Option A — Build the control end-to-end

| Field | Assessment |
|---|---|
| Benefit | Real per-strategy operator ban capability; honest feature |
| Effort | ~2–3 evenings |
| Risk | New write surface + RLS to keep honest; enforcement now consequential |
| Migration | **Required** — reconciliation migration codifying the drift column (#1231's pattern) + tracking; apply per `docs/migration_procedure.md`, never `db push` |
| Control effect | Tightening-capable (new suppression control); default empty = no change |
| Rollback | Revert PR; column stays inert |
| Acceptance | Persisted ban blocks on the scheduled route (route test); read failure fails entries **closed and loudly** (never silently authorizes); zero-row behavior byte-identical; write surface authenticated + audited (actor/reason/effective_at); selector AND final-gate route tests |

Also required: user-owned settings row lifecycle (create-on-first-write),
honest UI, typed `settings_read_unavailable` behavior, migration/apply
operator prompt.

## Option B — Remove the phantom

| Field | Assessment |
|---|---|
| Benefit | Deletes a fail-open seam and a capability lie; less surface to keep honest |
| Effort | ~1 evening |
| Risk | Forecloses a cheap future control (rebuildable from this packet) |
| Migration | None (leave the drift column inert; document it) |
| Control effect | None — current zero-row behavior is already "no bans" |
| Rollback | Trivial (revert) |
| Acceptance | Dead read + parameter threading removed; StrategyPolicy retained ONLY where a real producer exists (or deleted with its tests); docs/tests updated; zero-row account behavior equivalent (route test) |

## Recommendation

**Option B**, unless per-strategy operator bans are a near-term committed
requirement. Grounds: single-operator learning-mode account; zero rows ever;
the enforcement path is live code that must be maintained honestly while doing
nothing; Option A is justified the day a real ban use-case (or second user)
appears, and this packet preserves the design for that day.

**Decision required from operator: A or B. Neither is implemented in this run.**
