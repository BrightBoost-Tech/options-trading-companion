# Migration Results — 2026-07-18 (Fable Migration Orchestrator)

ORCHESTRATOR=fable · SUBAGENTS=opus (review-only) · market CLOSED (Fri post-close;
next open Mon 2026-07-20 09:30 ET) · source main `aeab21d89714fd1b8344b762feecf76f1e801eb8`
· applied via `mcp__supabase__apply_migration` only, SQL byte-verbatim (SHA-256
recomputed at apply time against the Phase-0 pins) · operator worktree byte-preserved.

## Applied (serialized M1→M2→M3; each: opus review PASS → Fable review PASS → preflight → apply → verify → receipt → safety checkpoint)

| migration | file SHA-256 (16) | preflight | history (by name) | applied (UTC) | receipt | result |
|---|---|---|---|---|---|---|
| M1 shadow_fleet_activation_rpc | 66154821bef7a264 | ABSENT_CLEAN | 20260718033415 | 03:34:15 | 7a3c52c1… | RPC_SCHEMA_READY / ZERO_PROVISIONING / ZERO_ACTIVATION |
| M2 candidate_terminal_dispositions | 7ed2f37a006dfc41 | ABSENT_CLEAN | 20260718033912 | 03:39:12 | 0a50d417… | CANDIDATE_DISPOSITION_SCHEMA_READY / NATURAL_RUNTIME_PROOF_PENDING |
| M3 option_quote_provenance | 186b738e6f02c24d | ABSENT_CLEAN | 20260718034013 | 03:40:13 | ec013a5d… | QUOTE_PROVENANCE_SCHEMA_READY / NATURAL_RUNTIME_PROOF_PENDING |

**NEVER REAPPLY any of the three** (tracking matches by NAME; file version
prefixes 090000/100000/120000 differ from history versions by design — the
known tracking-drift class).

## Verification detail

- **M1**: `rpc_shadow_fleet_provision(uuid,text)` + `rpc_shadow_fleet_activate(uuid,text,jsonb,jsonb)`
  exact identity args; EXECUTE granted to service_role only, revoked from
  PUBLIC/anon/authenticated (has_function_privilege proven both directions);
  zero top-level DML in the file (all writes inside SECURITY-INVOKER plpgsql
  bodies) — apply created 0 rows: shadow_fleets=0, shadow_micro_accounts=0,
  fleet-named paper_portfolios=0, fleet receipts=0.
- **M2**: 19 columns; 3 CHECKs (attempt≥1, 10-value disposition allowlist,
  final-implies-disposition); UNIQUE(cycle_id,candidate_fingerprint,attempt);
  7 indexes incl. partial UNIQUE `idx_ctd_one_final_per_identity` WHERE
  is_final; RLS + service_role FOR ALL + user SELECT; 0 rows.
- **M3**: 31 columns matching the file in exact order (an earlier working
  note said 35 — 31 is file truth and live truth); 5 indexes incl. partial
  `idx_oqp_fallback` WHERE fallback_reason IS NOT NULL; RLS + single
  service_role FOR ALL policy; no secret-bearing columns (writer scrubs
  key-like fields pre-insert); 0 rows.

## Integrated post-run state (Phase 2, all PASS)

- Fleet: **zero provisioning, zero activation** (all fleet tables 0 rows).
- Activation blockers: **SEVEN**, unrepaired (6 `submitted` 2026-04-09 +
  1 `needs_manual_review` 2026-05-11).
- Data corrections NOT executed (all remain operator-gated with fingerprints):
  F-CREDIT-SIGN 19 closes (fp b780271c…) · stale orders 6 rows (fp 04317fc1…)
  · orphan job_runs 5 rows (fp 40258ba9…; 4 running oldest 2026-01-09 +
  1 queued 07-16 — `cancelled`/`dead_lettered` are terminal statuses).
- Broker: 0 positions / 0 open orders at every checkpoint; 0 new
  critical/high alerts; `entries_paused=false` unchanged.
- Deployed SHA unchanged: worker SUCCESS at `aeab21d8` (migrations trigger
  no deploy; no Railway/env/control change made).
- Bundle `otc-friday-post-close-2026-07-17/`: all 20 manifest fingerprints
  re-verified; addendum `post-migration-results-addendum-2026-07-18.md` +
  regenerated `fleet-provisioning-operator-prompt.md` added; manifest
  updated (migrations_applied + new hashes).

## Remaining operator decisions / next authorized steps (NONE executed)

1. Stale-order reconciliation (token APPLY_STALE_ORDER_RECONCILIATION:04317fc1…)
   + adjudicate the 1 needs_manual_review row — clears the seven blockers.
2. F-CREDIT-SIGN 19-close data correction (token in its prompt; fp b780271c…).
3. Orphan job_runs reconciliation (5 rows; fp 40258ba9…).
4. Fleet PROVISION dry-run → execute (new prompt: `fleet-provisioning-operator-prompt.md`).
5. Fleet ACTIVATION — blocked until 1 + policy preregistration + strict
   `FLEET_ACTIVATION_AUTHORIZED=1` + attestation referencing the
   reconciliation receipt.
6. Natural runtime falsifiers (no writes needed): first
   candidate_terminal_dispositions + option_quote_provenance rows at the
   Mon 2026-07-20 scan cycle; `job_succeeded_with_errors` stays quiet on the
   writers' typed no-op removal.
