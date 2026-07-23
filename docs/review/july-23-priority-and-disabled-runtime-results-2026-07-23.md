# Fable July-23 Priority Orchestrator — Results (2026-07-23)

**Orchestrator:** Fable · **Agents:** Opus (3 RTH read-only audits · 4 post-close builds). RTH was
strictly read-only; all merges/applies/production writes happened post-close (gate confirmed
`is_open=false` 20:05Z, broker flat, 4 services on one SHA). Companion doc:
`disabled-and-inactive-runtime-audit-2026-07-23.md` (the full feature census).

## P1-0 (NEW, evidence-added) — nightly audit child failed 07-22 AND 07-23
Root cause CONFIRMED from transcripts: the audit child's model call hit the **weekly usage limit**
(`resets Jul 23, 12pm America/Chicago`) — the same quota outage that killed the Jul-21 delegated
lanes. The runner hardening worked as designed (contract detection, withheld ping, ALERT files —
swept into this PR: `audit/ALERT-2026-07-22-runner.md`, `audit/ALERT-2026-07-23-runner.md`).
**No code fix needed; self-healing** (quota reset 07-23 17:00Z). Natural falsifier = tonight's
05:00Z (Jul-24) run. Side fix shipped: #1356 removed the dead `Write(audit/**)` settings rule.

## Serialized merges — final code main `2c9ab5f8`

| # | PR | What | Merge order note |
|---|----|------|------------------|
| 1 | #1360 | P1-1 append-only idempotent rejection persistence (`event_id` + partial unique index; `INSERT ... ON CONFLICT DO NOTHING`, NO update-on-conflict; pre-attempt-1 event_id reused across retries; `job_run_id` stamped on new rows; poisoned-client refresh; counters `persisted_new/duplicate_ack/retry_recovery/lost_after_retries/permanent_failure` — only real loss partials) | **DDL applied BEFORE merge**: `20260723150000_suggestion_rejections_event_id` (tracked `20260723204135`, receipt `975ad6ae`); 14,217 historical rows byte-untouched |
| 2 | #1359 | P1-2 typed terminal economic block: dedicated `EntryRoundtripCostExceedsEV` handler; canonical `stamp_not_executable` added to `suggestion_status.py` (counterpart of `stamp_executed`); blocked_count/blocked_by_reason not errors; no cohort-failure alert on the expected path; terminal-persist failure stays a REAL error; $15 floor/EV math byte-identical | — |
| 3 | #1356 | C1: dead `Write(audit/**)` rule deleted from nightly-settings (Edit rule already present) | — |
| 4 | #1358 | Lane D: FLAG_ECHO +7 dark env controls via their REAL parsers (27→34) + separate operator `RUNTIME_STATE_ECHO` DB-state reader (not wired to startup; no-DB-at-startup tripwire). Seam recorded: `QUANT_AGENTS_ENABLED` has two divergent production parsers | — |
| 5 | #1357 | C2 (P2): retired the dead `phase2_precheck` scheduler slot (251 consecutive `window_expired` no-ops since 04-27; resolves F-A5-1); atomic across scheduler/endpoint/handler/tests/docs; never in `EXPECTED_JOBS` so no watchdog change | — |

All four services SUCCESS at `2c9ab5f8` (20:53Z); per-merge checkpoints clean (broker flat,
entries_paused=false, 0 crit/high, fleet unchanged).

## July-23 incident evidence (VERIFIED-DB, pinned by the RTH forensics)
- Scan `2a98d35d` 14:03Z PARTIAL solely from **3 lost rejection rows** (SPY IC suggestion +7
  dispositions durable; `suggestion_insert_failures=0`, ctd `write_failures=0`). New findings: 
  `suggestion_rejections.job_run_id` was NULL on **all 14,217 rows** (stamping gap, fixed in #1360);
  2 historical tuples consistent with retry-after-commit duplication (unprovable pre-`event_id` —
  exactly the case for the fix).
- Executors `acddb64e`/`681d6270`: expected `ev_below_roundtrip_cost` counted as errors=1 via the
  generic exception handler (DOC≠BUILT docstring); the blocked suggestion stayed retryable
  `pending`. Fixed in #1359. Brief-number corrections: the 16:30Z run was rt=9.00/net=12.94; the
  neutral clone executed as `shadow_blocked`, not internal_paper.

## Single-leg guarded setup — COMPLETE, epoch ENABLED shadow-only
Migration-tracking anomaly first (Lane G): verdict **`APPLIED_UNTRACKED_PARTIAL`** — foundation
files 1/2/3/5 were applied out-of-band (full object parity, no `schema_migrations` rows — the known
drift class; files 1/2 carry an unguarded-CREATE POLICY reapply hazard → **NEVER reapply**; their
parity fingerprints are recorded in the census doc). **No tracking backfill was performed** (not in
tonight's authorization; operator follow-up). File 4 was the genuinely missing DDL.

Sequence executed exactly as operator-amended (receipts):
1. **Applied `20260722020000_single_leg_experiment_control_rpcs`** by exact name (receipt
   `6e06695a`). ⚠ Honesty note: the first apply contained ONE hand-transcription error (the
   `sl_ctrl_conviction_v1` expected-hash, `a6bf`↔`d9fb` segment) — **caught by post-apply
   verification** and corrected same-session via `CREATE OR REPLACE` to the reviewed file; all six
   function bodies then **digest-verified byte-identical** to the repo file
   (`1c565469/79d79312/9d1cd1fe/bc03d217/cb619515/ef276899`).
2. Verified the 6-RPC surface; policy count = 0.
3. **Four-row DRAFT seed** executed as its own transaction (in-txn assertions passed); verified
   **4/4 server-derived hashes == the byte-verified manifest**, 4 draft/`approved_at NULL`, opt-in
   on exactly the 2 `sl_exp_*` rows, `small_tier_v1` untouched (50, last-approved 07-19).
4. **T1 setup**: `disabled_setup_ready`, policy_rows=4, experimental_bindings=2,
   enabled_bindings=0, starting_capital=2000, 2 new `shadow_only` portfolios ($2,000/$2,000), 
   **setup_fingerprint (unshortened):
   `a01319a12211592a7750842aa9ed1b98192995e50242459dabfec4abf9d2f3a6`**.
5. **Enforced no-write replay** on the full natural tape
   `be9d5fe5-d9f4-488f-b86d-360238a66d7e` (16:00Z scheduler scan, `tape_integrity=complete`):
   `NO-WRITE`, db_writes=0, provider_calls=0, broker_calls=0, `stored_decision_tape`,
   policies_evaluated=2, attempts=contexts×2, **HONEST-EMPTY** (typed `chain_unavailable`×1 per
   policy covers all contexts — a replay-context limitation, not a production defect).
6. Zero census re-verified (7/7 evidence tables zero); custody 2/0/2.
7. **T2 approve**: 4 rows approved, fingerprint-gated, epoch still disabled.
8. Final safety recheck (broker flat, 0 crit/high, small_tier untouched) → **T3 enable**:
   `status=enabled · routing_mode=shadow_only · execution_mode=internal_paper · max_contracts=1 ·
   live_submit_allowed=false · enabled_bindings=2`.
Rollback lever: `rpc_pause_single_leg_experiment_v1` (persisted kill switch). **No manual
`suggestions_open`/`single_leg_shadow_scan` was or will be triggered.**

## PR cleanup (Lane E)
Closed with canonical comments: **#1352** (superseded by merged #1355 — targets the deleted
fake-validation form; contaminated diff) · **#1339**/**#1350** (exact TradeInbox-disclosure
duplicates of canonical #1196). Kept: #1084/#1083 (overlapping-not-exact), #1312 (draft, doctrine).

## Natural Friday falsifiers (do not manufacture)
Next natural scheduler `suggestions_open`: parent output unchanged · one idempotent child per
source decision · 2 experimental policies evaluated · controls create no attempts · complete typed
attempt coverage (0 candidates allowed) · any candidate 1-leg/1-contract/shadow_only · any fill
internal_paper · broker orders 0. Plus: `rejection_persist_failures=0` with the new counters
(`duplicate_ack`/`retry_recovery` may be >0; no duplicate event_ids) · expected round-trip blocks
in `blocked_count` not `errors` · tonight's 05:00Z nightly child (quota healed). 

## Production writes (complete list)
Migrations by exact name: `20260723150000_suggestion_rejections_event_id` ·
`20260722020000_single_leg_experiment_control_rpcs` (+1 same-session transcription correction to
the reviewed file). Receipts: `975ad6ae`, `6e06695a`. Data: the 4-row DRAFT seed · T1 setup
(2 portfolios + 2 disabled bindings + disabled epoch row) · T2 approval (4 rows) · T3 enable
(epoch + 2 bindings). **Zero**: broker writes, fleet writes, small_tier_v1 changes, live-control
changes, F-REDATE, env changes, manual job triggers.
