# Fable Monday Post-Close Max-Throughput Orchestrator — Results (2026-07-20)

**Orchestrator:** Fable (claude-fable-5) · **Build/review agents:** Opus (claude-opus-4-8), ≤7 parallel.
**Merges serialized by Fable.** Zero broker writes · zero fleet activation · zero control/env/schedule
change · entries_paused untouched throughout. Broker flat the entire run.

Proof labels per §10: VERIFIED-CODE / VERIFIED-MERGE / VERIFIED-CI / VERIFIED-RUNTIME / INFERRED /
NOT_PROVEN / INCONCLUSIVE.

## Phase 0 — grounding (VERIFIED-RUNTIME)
Market post-close, broker flat (`get_all_positions`=[]), `entries_paused=false`, fleet
`pending_legacy_terminal`/inactive, 50 policies registered. DB clock ≈ broker clock; no premise drift.

## Serialized merges (each: adversarial opus review → CI green → squash → 4-service deploy-verify → safety checkpoint)

| # | PR | squash SHA | what | migration | deploy (both workers) |
|---|----|-----------|------|-----------|----------------------|
| 1 | #1322 | (Phase 1) | provider-guardrail secret redaction on retries-exhausted path | — | SUCCESS |
| 2 | #1324 | (Phase 1) | signed-CLI `--wait` + read-only `GET /tasks/status/{id}` (`tasks:job_status` scope) | — | SUCCESS |
| 3 | #1323 | (Phase 1) | atomic-close guard hardening (non-finite `p_fill_mid_reference` NaN/Inf; explicit `live_eligible` reject) | `20260720120000` applied by exact name | SUCCESS |
| 4 | #1326 | `0d0c3baf` | nightly wake-lock hardening (ES_CONTINUOUS\|ES_SYSTEM_REQUIRED on long-lived thread; typed acquire-failure) | — | SUCCESS 23:53 UTC |
| 5 | #1327 | `c1a02ab3` | funnel: durable terminal dispositions for the 6 non-selected candidates (`rank_blocked`, observe-only) | — (no migration; `rank_blocked` + `selected` already in schema) | SUCCESS 00:18 UTC |
| 6 | #1328 | `e455ed9f` | fleet Option-A immutable reconciliation-receipt contract + activation binding | D1 `20260720140000` + D3 `20260720150000` applied by exact name | SUCCESS 00:22 UTC |

Final `origin/main` = **`e455ed9f145b87b7780c0b73f91e26dbe23cb069`**.

### #1327 detail (Lane A) — VERIFIED-CODE + VERIFIED-CI
Problem: the Monday cycle emitted 8 candidates; 2 selected primaries got `h7_dropped` finals but the 6
non-selected alternates had NO durable terminal fate (`rank_and_select` returns only survivors). Fix:
`record_not_selected(scout_results, candidates)` at the post-`record_selected` seam writes one
`rank_blocked` / `selected=false` disposition per alternate. **Byte-identity proven** (persisted
`trade_suggestions` + selected finals identical with/without the alternate writes; conflict key is the
durable `cycle_id,candidate_fingerprint,attempt`, NOT `id(cand)`). Adversarial review PASS on all 7
contract points. CI initially red on 2 brittle *source-proximity* tests in `test_cycle_metadata_writer.py`
(the additive H9 `errors`/`candidate_disposition` counts keys pushed `cycle_metadata` past a magic
2000-char window — NOT a behavioral regression; the field is still emitted); fixed by widening the window
(2000→2300 / 2500→2700, presence-not-offset), rebased onto main, CI green at `1ea17d71`. Reviewer note
(carried, non-blocking): the H9 fold now marks the midday job PARTIAL on ANY candidate-disposition write
failure (not only alternates) — doctrine-aligned (fail-loud), job-status-only, 0 in normal operation.
Natural falsifier: the NEXT natural midday cycle's `candidate_terminal_dispositions` finals count ==
scanner emitted count (selected finals + `rank_blocked` alternates, `selected=false`) — **INCONCLUSIVE
until the next cycle** (Monday's cycle already ran before deploy).

### #1328 detail (Lane D) — VERIFIED-CODE + two independent PASS + VERIFIED-RUNTIME(apply)
Two adversarial opus reviews, both PASS:
- **R1 (D1 schema + D2 backfill honesty):** D1 additive-only, immutable (BEFORE UPDATE+DELETE row trigger
  raises for all roles incl service_role), service_role-only RLS, all constraints, table absent pre-apply.
  D2 verdict **`BLOCKED_RECEIPT_ID_NOT_DURABLE`** independently confirmed HONEST — the four 07-18
  reconciliation fingerprints (`04317fc1`/`5d5cd9fc`/`40258ba9`/`b780271c`) carry NO durable typed receipt
  identity (`40258ba9` truncated 16-char + job_runs has no user_id; the rest prose-only / plan-content
  stamps), so the backfill inserts 0 rows — no fabricated identity (H9).
- **R2 (D3 activation-safety):** live-deployed-source diff proves D3's ONLY change vs the `20260719020000`
  hardened body is the additive scenario-5 receipt-binding block. Every prior gate preserved verbatim;
  exactly 1 overload (4-arg defensively dropped); fail-closed against the empty receipt table (every
  activation RAISEs `receipt_not_found`; REQUIRED_KINDS {stale_order, manual_review} both enforced); the
  migration mutates no fleet state; SECURITY INVOKER (no escalation); Python `execute_activation` still
  gated on `FLEET_ACTIVATION_AUTHORIZED=='1'` + confirm literal + attestation, untouched. Scenario-5 pin
  inverted OPEN→CLOSED.

**Applies (VERIFIED-RUNTIME, receipts `618b284f` / `f16670ee`; NEVER REAPPLY):**
- D1 `20260720140000_fleet_reconciliation_receipts` (MCP ver `20260721002415`, file sha256
  `6f068956…`) — post-apply: table present, **0 rows**, RLS on, immutability trigger present, 1 policy,
  5 CHECK + 1 UNIQUE constraints.
- D3 `20260720150000_bind_fleet_activation_to_receipts` (MCP ver `20260721002709`, file sha256
  `3f329c22…`) — post-apply: **1 overload** (5-arg), receipt-binding present, `search_path` pinned
  `public,extensions,pg_temp`, SECURITY INVOKER, EXECUTE = service_role only, **fleet UNCHANGED**.

**D2 backfill: NOT RUN** (BLOCKED_RECEIPT_ID_NOT_DURABLE) — artifact kept in `supabase/backfills/`
(never auto-applied).

**Fleet plan-activation DRY-RUN (READ-ONLY, zero writes) — PASS:** server-derived binding fingerprint
recomputed from pure DB truth = **`1cd004b5167429cf469652bdd04b16d522b0f8b87d98d5a9aa68481c19231a76`**
(matches the reproducible doctrine value), 50 approved registry rows, fleet
`pending_legacy_terminal`/effective_at NULL, **50 inactive / 0 active / 0 bound / 0 receipts**. Activation
is now **fail-closed on empty receipts** (scenario-5 binding live; REQUIRED_KINDS unsatisfiable →
activation impossible). **`ACTIVATE_FLEET=false`; fleet NOT activated; `shadow_fleet_activated` rows = 0
ever.**

Finding (non-blocking, docs-only; DEFENSE-IN-DEPTH): `service_role` retains DELETE/UPDATE/TRUNCATE on
`fleet_reconciliation_receipts` via Supabase blanket default privileges. UPDATE/DELETE are trigger-blocked
regardless of grant; TRUNCATE is not row-trigger-blocked BUT only *removes* receipts → strictly more
fail-closed (can never forge an activation). Reviewer 1's LOW-2 conclusion (not a security hole) holds;
its "service_role holds only SELECT/INSERT" premise was inexact. Optional future hardening:
`REVOKE TRUNCATE,UPDATE,DELETE ON fleet_reconciliation_receipts FROM service_role`.

## Held / not-merged (per authorization)
- **Lane B OI (#1325):** DRAFT-ONLY. Root cause VERIFIED-CODE — Alpaca `/v1beta1/options/snapshots`
  carries volume but NOT open_interest (`market_data_truth_layer.py:1816` `oi=snap.get("openInterest")`→
  None); Polygon has OI but is fallback-on-empty-only (`:1615`). A real fix needs a NEW provider call →
  `NEW_OI_NETWORK_ENRICHMENT=DRAFT_ONLY`. Not merged.
- **Lane E F-REDATE:** operator decision packet delivered (recommendation CORRECT_ALL_CONFIRMED_ROWS);
  `APPLY_F_REDATE_DATA_CORRECTION=false` → NOT executed. 20 shadow `learning_feedback_loops` rows re-dated
  to 07-18; broker-live untouched; live calibration NOT contaminated (`CALIBRATION_TRAIN_LIVE_ONLY` ON +
  #1076 epoch floor); paper-window readers contaminated. Operator-owned.

## Natural evidence (read-only; no triggers; HONEST-EMPTY is valid)
- **07-20 post-close learning chain:** all succeeded (daily_progression 21:00 · paper_learning_ingest 21:20
  · policy_lab_eval 21:30 · post_trade_learning 21:45 · promotion_check + thesis_tracker 22:00 UTC).
- **TCM v2 realized accrual (#1289/#1299):** observe-only; accrues over post-#1278 cycles (0/15 promotion
  sample) — INCONCLUSIVE (accruing, not failed).
- **Model review (#1286):** event-driven, inert until natural trigger — HONEST-EMPTY (not triggered).
- **Atomic internal-close (#1323):** 0 natural fires (book flat) — DEFERRED-SAMPLE / HONEST-EMPTY.
- **00:00 CT nightly (Lane C falsifier):** PENDING / **INCONCLUSIVE** — fires 00:00 CT 2026-07-21
  (05:00 UTC). ⚠ **Operator-gated:** the wake lock is correctly held IN CODE (#1305/#1326 VERIFIED-CODE),
  but the 07-20 run was sleep-killed by the OS `SUB_SLEEP\UNATTENDSLEEP` power-plan timer, which
  `SetThreadExecutionState` does NOT reset and which the orchestrator is FORBIDDEN to change. Unless the
  operator sets that timer to 0 (Never) for unattended runs, tonight's nightly will likely FAIL again on
  the same power-kill, independent of the (now-correct) wake-lock code.

### Morning grading runbook (nightly)
```sql
-- 1) Did the dated report land?  (v5.1 audit writes audit/reports/2026-07-21.md)
--    Check the operator cron.log for per-run START/END markers + the fresh %LOCALAPPDATA% worktree path.
-- 2) job_runs for the audit runner around 05:00 UTC:
SELECT job_name, status, started_at, left(coalesce(result::text,error::text,''),200)
FROM job_runs WHERE started_at BETWEEN '2026-07-21 04:55Z' AND '2026-07-21 05:30Z' ORDER BY started_at;
-- 3) Dead-man ping at the provider (NIGHTLY_AUDIT_PING_URL) — fires only AFTER the dated report exists.
-- PASS only if: dated report present + END marker + ping. Sleep-kill ⇒ FAILED (power setting), not a code regress.
```

## Observations for the operator (non-blocking)
- **OBS-1 calendar-parse blip (A10):** 6 open HIGH `job_succeeded_with_errors` (A4 #1100) trace to ONE
  early `suggestions_open` block at 14:04 UTC — `market_calendar_unavailable` on a calendar row whose
  `open='2026-07-20 09:30:00'`/`close='...16:00:00'` failed the parser's expected format; self-resolved by
  16:00 UTC. NOT from tonight's merges (none touch the scan/calendar path); out of authorized scope. A10 /
  #1229 broker-clock-guard territory owns the follow-up.
- **OBS-2 TRUNCATE grant** on `fleet_reconciliation_receipts` (above) — defense-in-depth only.

## Safety ledger (this run)
Zero broker orders · zero manual suggestions/executor/close/model-review/learning triggers · zero fleet
provisioning/activation · zero policy-registry mutation · zero entry/risk/liquidity/cost/calibration/
DTE/width/sizing change · zero Railway env or schedule change · zero F-REDATE row update · zero historical
suggestion/disposition backfill. Production DB writes: 2 reviewed migrations applied by exact name (D1, D3)
+ 3 `migration_apply` receipts. `ACTIVATE_FLEET=false`; `entries_paused=false` throughout.
