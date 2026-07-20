# External Full Audit v1.7 — Findings Verification Results — 2026-07-19

Orchestrator: Fable (claude-fable-5). Verification/build/review agents: Opus (`model=opus`).
The v1.7 candidate findings were re-adjudicated against the then-current main `f48c298c` (the
implementation base), NOT assumed true from the audit prompt. The audit-prompt PR **#1312**
(`docs(audit): add ChatGPT-solo external full audit v1.7 prompt`) is an audit SPECIFICATION, not
this results record; it is left as a draft (disposition below).

## Verdict summary

| finding | severity | verdict at base `f48c298c` | disposition |
|---|---|---|---|
| V17-1 F-A2-INTERNAL-CLOSE-PRECOMMIT-SIDE-EFFECTS | HIGH | **CONFIRMED** (Fable-reproduced: write-before-CAS ordering at `paper_exit_evaluator.py:2464/2488/2493` vs CAS `:2573`) | **FIXED + MIGRATED** (Lane 1A #1316 + Lane 1B #1317) |
| V17-2 F-A8-FLEET-ACTIVATION-ARTIFACT-UNBOUND | HIGH (activation-gated) | **CONFIRMED** (Fable-reproduced: applied RPC had no `approval_status`/`effective_epoch`/`fingerprint` clause; all 6 bypass scenarios accepted) | **FIXED + MIGRATED** (Lane 2 #1315); fleet stays INACTIVE |
| V17-3 F-A1-TCM-V2-PARTIAL-STAMP-UNDERCOUNT | MED (observe-only) | **SUPERSEDED** by #1299 (undercount harm already closed; mixed side → typed `incomplete_side` UNAVAILABLE, runtime-proven) | coverage-field polish shipped in Lane 4 #1318 |
| V17-4 F-A1-TCM-LIVE-COHORT-CONFLATION | MED (observe-only) | **PARTIAL/CONFIRMED** (Fable-reproduced census: aggressive cohort 12 alpaca_live / 11 alpaca_paper / 1 internal — 81% paper under a "LIVE / authoritative" headline) | **FIXED** (Lane 4 #1318) |
| V17-5 F-A9-MARKETDATA-CREDENTIAL-PREFIX-LOG | MED | **CONFIRMED** (Fable-reproduced: `market_data_truth_layer.py:1417` key-ID prefix at INFO on the RTH options path; + a sibling Polygon exception-snippet leak `market_data.py:605`) | **FIXED** (Lane 3 #1314) |

## Detail

### V17-1 — CONFIRMED → FIXED + MIGRATED (HIGH)
The internal/shadow close route wrote order-filled, portfolio cash, and the fill ledger BEFORE the
realized-P&L validation, close-reason mapping, and the position-close CAS — so an abort or CAS race
could orphan economic side-effects or double-book a racing close (supabase-py has no client-side
transaction). Scope was shadow/paper only (live is barred by the P0-A guard). **Fix:** a server-side
atomic economic-commit RPC `rpc_commit_internal_close_v1` (all four writes in one all-or-none
transaction; cash direction/delta derived server-side from the locked position; write-once commit
marker; idempotent replay; typed rejects; live-order isolation guard; non-finite guard; #1017
fill-quality provenance) — Lane 1A #1316, migration `20260719180000_rpc_commit_internal_close_v1`
APPLIED (receipt `risk_alerts 8cfd7333`, zero business-row change). The route now makes exactly one
RPC call with no non-atomic fallback; an RPC failure leaves the position OPEN + typed partial and
the monitor holds it — Lane 1B #1317. A read-only production census (separate operator packet
`docs/review/v17-1-internal-close-anomaly-census-2026-07-19.md`) found current-state CLEAN (0
orphans) with 3 pre-guard historical incidents — NO rows corrected.

### V17-2 — CONFIRMED → FIXED + MIGRATED (HIGH, activation-gated)
The applied fleet-activation RPC validated only the structural shape of the operator's slot→id
payload; registry-approval/epoch was client-side only and the manifest fingerprint + reconciliation
receipts were unbound inside the transaction, so a direct service-role call could accept a
permutation, unregistered ids, draft/retired ids, a mid-flight-retired id, a fabricated receipt, or
a wrong manifest. **Fix:** the hardened RPC server-DERIVES the binding from the 50 approved
registry rows for the epoch (`ORDER BY policy_registration_id COLLATE "C" ASC` — structurally equal
to the client codepoint sort, closing a latent collation-determinism gap), binds off the
fingerprint-verified `v_derived_map` (closing a concurrent-INSERT TOCTOU), and requires the
operator-attested manifest fingerprint to equal the server recomputation — Lane 2 #1315, migration
`20260719020000_harden_shadow_fleet_activation_rpc` APPLIED (old 4-arg overload DROPPED; hardened
5-arg service_role-only; receipt `risk_alerts 84687a20`; fleet UNCHANGED and INACTIVE). Scenario 5
(reconciliation-receipt EXISTENCE) is OPEN by design — no durable typed receipt contract exists;
the prerequisite is designed (not applied) in
`docs/review/fleet-receipt-contract-prerequisite-2026-07-19.md`, and activation remains blocked.
The reproducible binding fingerprint is `1cd004b5…` (the pre-existing `6f8d1499…` was not
reproducible from committed code — an out-of-repo bundle script over a richer manifest); **owner-
packet-1's activation attestation must be re-issued against `1cd004b5…`** (reconciliation note,
not actioned here).

### V17-3 — SUPERSEDED (MED, observe-only)
The multi-fill undercount was already fixed by #1299 (merged 07-19): a side with mixed
stamped/unstamped fills returns typed `incomplete_side:n/m` UNAVAILABLE, not the stamped subtotal
(runtime-proven, 58/58 tests). The only residual was observability: no first-class
`contributing_fill_count`/`stamped_fill_count`/`stamp_complete` fields. Those were added in Lane 4
#1318 with the sum/abstention logic unchanged.

### V17-4 — CONFIRMED → FIXED (MED, observe-only)
`realized_cost_study.py` mapped policy `aggressive → "live"` and pooled ALL fills into a "LIVE /
real capital / authoritative Realized P&L" headline; the live census showed 81% of the aggressive
cohort's P&L magnitude was `alpaca_paper`/`internal_paper`, not broker-live. **Fix:** three
separated axes — `policy_cohort` / `execution_realism` (from `execution_mode`, not the noisy
`fill_source`) / `economic_evidence_cohort` — so `broker_live` contains only `alpaca_live` rows; the
broker-live headline is now provably == the alpaca_live sum (a −$1M internal magnitude cannot move
it). Rejected-CLEAN surfaces (already execution-truth-keyed, untouched): monday_evidence_reader,
tcm_v2_proposal + promotion gate, signal_accuracy view, challenger_study — Lane 4 #1318.

### V17-5 — CONFIRMED → FIXED (MED)
`market_data_truth_layer.py:1417` logged an 8-char prefix of the Alpaca key-ID at INFO on the
primary options-snapshot path (every RTH scan/MTM/monitor); a sibling unredacted Polygon
exception-snippet at `market_data.py:605` could embed a query-param secret. **Fix:** constant
non-secret message + redact-before-truncate on the exception path; 6 synthetic-secret tests (no
credential value ever read/printed) — Lane 3 #1314. **provider-side rotation status = NOT_PROVEN**
(nothing rotated; no secret inspected). A third same-class site (`provider_guardrails.py` decorator)
was flagged and left for a follow-up to keep the diff minimal.

## Runtime-pending / follow-ups (not gating)
- The atomic close RPC's first NATURAL internal-close is the runtime falsifier for Lane 1A/1B.
- Align the RPC's internal-close accept-gate (`routing_mode='shadow_only'`) with the route's
  (`routing_mode <> 'live_eligible'`) — fail-safe today (the inert #1003 `paper_shadow` mode would
  be held open, never phantom-filled).
- `provider_guardrails.py` credential-in-exception (V17-5 sibling).
- Extend the RPC non-finite guard to `p_fill_mid_reference` when convenient (provenance-only; never
  touches cash).
- Scenario-5 durable reconciliation-receipt contract (fleet activation prerequisite).

## #1312 disposition
Leave as a **draft** — it is the audit prompt/spec, superseded as the canonical record by THIS
results file. Do not merge it as though it were results.
