# Fable Counterfactual Research + Shadow-Fleet Evaluator — Results (2026-07-23/24)

**Orchestrator:** Fable · **Agents:** Opus (4 read-only audits · 6 build lanes · 3 adversarial
reviews + 1 targeted re-review). All merges/applies/env changes Fable-serialized, post-close,
broker flat throughout. Final code main **`8de051f0`**; docs merged last.

## Audits (frozen contracts, scratch: `%TEMP%\otc-cf\audit-{A,B,C,D}-*.md`)
A: the tape does NOT retain legs/inputs for rejected structures → scan-time capture REQUIRED;
earliest seam = post-EV in `process_symbol`; per-leg IV threads from the fetched chain (zero new
provider calls); import lock preserved via the model_review trio pattern. B: V4 is global-only
unwired; as-written it WOULD refetch bars → fetch-blocking shim over V3's captured basket data;
new `REGIME_V4_OBSERVE_ENABLED` (the dead `REGIME_V4_ENABLED` untouched). C: all 50 policies vary
only policy-layer axes → ONE shared universe from the tape (never 50 scans; fork.py = the named
anti-pattern); `policy_decisions` structurally can't host fleet decisions → two additive tables.
D: E1/E2/E3 already shipped (stale backlog prose); E4 the only genuine small build; 6 PR-close
candidates (3 executed conservatively); tracking-backfill packet drafted (operator-gated).

## Merges (serialized; per-merge 4-service verify + broker/alert/fleet checkpoints — all clean)

| # | PR | Lane | Migration (applied BEFORE merge) · receipt |
|---|----|------|--------------------------------------------|
| 1 | #1364 | A td-scan observer (capture + child + scorer + flag) | `20260723160000_td_scan_observe_tables` · `715f36a9` |
| 2 | #1365 | B regime-V4 observer (capture + shim + child + flag; conflict-resolved keep-both, 87 combined tests) | `20260723160000_regime_v4_comparisons` · (batch receipt) |
| 3 | #1363 | D unified research reader (paginated, six-state honesty) | — |
| 4 | #1366 | C1 fleet evaluator foundation (post-FAIL remediation) | `20260723160000_fleet_policy_decision_foundation` · (batch receipt) |
| 5 | #1367 | C2 fleet internal-paper lifecycle (stacked; 5 fn bodies digest-verified byte-identical post-apply) | `20260723170000_fleet_shadow_internal_lifecycle` · `0035080c` |
| 6 | #1362 | E4 QUANT_AGENTS parser unification (function-local import fix after a red merge) | — |

**Adversarial reviews:** #1364 PASS (4 LOW) · #1365 PASS (4 LOW incl. the same-prefix
migration-name coexistence note) · #1366+#1367 **FAIL→remediated→PASS** — the review caught (1)
HIGH: C2 RPCs referenced `paper_portfolios.updated_at`, a column production lacks, masked by a
bootstrap/production divergence (fixed: column refs removed, bootstrap now production-shaped);
(2) HIGH: the `cohort_name IS NULL` universe was emptied by the champion fork's in-cycle tagging
→ false `no_candidate` ×50 (fixed: `IS NULL OR = champion`, deduped, route-tested); (3) MEDIUM:
the open-positions loader sat outside the per-policy try (fixed: isolated). E4's red merge root
cause = a pre-existing order-sensitive `sys.modules` alpaca-stub leak in test infra (flagged to
the backlog), not the parser change.

## Phase 6 — observe-only enablement + fleet readiness proof
- `TERMINAL_DISTRIBUTION_SCAN_OBSERVE_ENABLED=1` and `REGIME_V4_OBSERVE_ENABLED=1` set via
  **targeted** `set_variables` on worker + worker-background ONLY (no other key touched — the
  only env change; recycles SUCCESS at `8de051f0`). Both parsers accept `'1'` (VERIFIED-TEST,
  pinned both-ways). ⚠ **Echo-line read-back NOT-PROVEN tonight:** the Railway log-search API
  returned empty for every filter on the new deployment while unfiltered logs work; large
  unfiltered pulls were declined (credential-in-logs hygiene). Operator action: view worker
  deployment `345ae118` logs and confirm the two `[FLAG_ECHO] ... = True` lines. Conclusive
  proof = Friday's natural rows.
- **Fleet 50-policy NO-WRITE replay (tape `be9d5fe5-d9f4-488f-b86d-360238a66d7e`): PASS** —
  `write_mode=NO-WRITE`, db_write_attempts=0, provider_calls=0, broker_calls=0,
  policies_evaluated=50, distinct_config_hashes=50, **50/50 complete typed dispositions**
  (0 selected / 15 policy_rejected / 35 capital_rejected on the 1-candidate SPY-IC universe —
  coherent with that candidate failing live cost gates). Fleet remains
  `pending_legacy_terminal`, 0 active slots, 0 bindings; **no bindings/activation/simulated
  outcomes were created**.

## PR reconciliation (Lane F)
Closed as exact duplicates (diff-verified, canonical named): #754→#885, #762→#885, #740→#1103.
Kept #751/#1213/#1146 — Audit D proposed closing them on file-path/title INFERENCE, but the
07-21 diff-based triage classified them overlapping-not-exact; the stronger evidence wins.
#1312 kept draft. No UI merges.

## Natural falsifiers (Friday 2026-07-24 16:00Z scan — never manufacture)
- **Terminal-distribution:** one idempotent `td_scan_score_observe` run; all fully-constructed
  candidates covered or typed not_scorable (credit spreads/condors INCLUDED); baseline+challenger
  EV/PoP/ranks persisted; zero live ranking/gate change; zero provider/broker calls.
- **Regime V4:** V3 stays live authority; global + per-symbol comparison rows; typed
  agreement/abstentions; counterfactual selection present or honestly unavailable.
- **Fleet evaluator:** typed `fleet_inactive` no-op; zero fleet decision/order/position/outcome
  writes (until a separately authorized activation).
- Plus (from July-23 morning): single-leg child first run · rejection-persistence counters clean ·
  blocked-vs-error taxonomy · the 07-24 05:00Z nightly (quota healed).

## Production writes + env (complete list)
Migrations by exact name (each verified post-apply; receipts in risk_alerts): the four above.
Env: the two NEW observe-only flags on the two workers — nothing else. Zero broker writes, zero
fleet bindings/activation, zero small_tier/single-leg mutation, zero live-control change,
zero manual job triggers. All nine new evidence tables at 0 rows at close of run.

## Remaining edges (named)
C2 lifecycle is expiry-settlement-only v1 (intraday stop/TP/DTE trigger management +
`settle_expired_fleet_positions` cadence wiring = follow-up); fleet activation remains
owner-gated (evaluator built, dormant); echo-line visual confirmation (operator);
the alpaca `sys.modules` test-stub leak (new backlog item); the tracking-backfill packet
(operator-gated).
