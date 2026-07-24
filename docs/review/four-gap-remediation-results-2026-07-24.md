# Fable Four-Gap Post-Close Orchestrator — Results (2026-07-23/24)

**Scope:** four remediation lanes (observer parent-status isolation · alpaca sys.modules stub
leak · migration-version governance · fleet candidate-universe v2), plus read-only parallel work.
**Excluded by brief:** the C2 fleet intraday stop/TP/DTE trigger + expiry-settlement cadence lane
— **STILL OPEN, not completed.** Orchestrator: Fable; build/review agents: opus. All merges
serialized post-close, broker flat throughout. Final code main **`91c70022`**; docs merged last.

## Phase 0 grounding (2026-07-24 02:09Z)
Clocks agreed to the second (DB = broker = 21:09 Chicago Thu 07-23); market closed. Start state
verified as expected: main `f8a69334`, 4/4 services at it, broker flat $2,067.86, entries_paused
false, fleet `pending_legacy_terminal` 50-inactive/0-bound/0-receipts, all nine research evidence
tables 0 rows. One HIGH in 24h: `job_succeeded_with_errors` on the off-schedule 14:03Z 07-23 scan
(3 real rejection-persist failures, honestly counted — the A4 detector working as designed;
EXPLAINED, and precisely Lane B's subject). Observer children had never run: the observe flags
went live 00:52Z, AFTER Thursday's 16:00Z scan ⇒ natural-evidence reader verdict
**DEFERRED_NATURAL_EVENT** (first qualifying scan = Friday 07-24 16:00Z).

## Merges (order B → D → C → A; per-merge current-head CI + opus adversarial review + 4/4 deploy + broker/alert/fleet checkpoints — all clean)

| # | PR | Lane | Merge | Review story |
|---|----|------|-------|--------------|
| 1 | #1370 | B observer isolation | `291275b7` | PASS-WITH-NITS → nits fixed (masker `scheme://user:pass@` pattern; redact-BEFORE-truncate; PR-body wording) → one CI red caught by the **terminal-distribution import lock** (the guard working) → observer key renamed `terminal_distribution`→`td_scan` → green |
| 2 | #1372 | D sys.modules stub leak | `b79c5e02` | PASS-WITH-NITS (all LOW/cosmetic); full-suite base-vs-head diff exactly +16/+16, zero skip delta; order-broken pair fails at base, passes both orders at head |
| 3 | #1369 | C migration version guard | `3a96ba8b` | **FAIL → fixed → PASS**: reviewer reproduced a HIGH — allowlist SHA-256 pins were CRLF working-tree bytes vs LF git blobs ⇒ the gate failed on ubuntu CI. Fix: CRLF→LF-normalize before hashing; pins recomputed to the LF blob hashes; +3 regression tests (26 total) |
| 4 | #1371 | A fleet universe v2 | `91c70022` | PASS-WITH-NITS → nits fixed (SCAN_CANDIDATE_CAPTURE_ENABLED added to FLAG_ECHO with a split flag-alone/combined-gate parser; typed `skipped_no_identity` writer defense; fail-closed champion token guard) |

**Migration applied by exact name (NEVER REAPPLY):**
`20260724010000_fleet_decisions_candidate_fingerprint_identity` — applied pre-merge (tracked
version `20260724032321`, receipt `b3e9bc3f`, file sha256 `01f05e1d…caa55ae`); post-apply
introspection verified all objects exact (fp column, nullable UUID identity, 4-value disposition
CHECK, identity-present CHECK, 2 indexes, legacy equality CHECK preserved verbatim).

## Lane substance
- **B (#1370):** td + fleet observer enqueue/readiness failures now route to
  `result.research_observers` (keys `td_scan` / `shadow_fleet`, block always present) +
  `counts.research_observer_failures` — never `counts.errors`, so an observer failure can no
  longer mark a clean live scan PARTIAL or trip the A4 detector; failures stay durable + emit a
  deduped `research_observer_enqueue_failed` alert (#1332 mechanism). Flagless. Sibling seams
  byte-identical (single-leg/rv4/fork/replay/rejection-persist). Reviewer proved no silent path
  exists. Rulings recorded: `research_observer_failures` keeps magnitude-sum semantics; a lost
  alert-row write remains a live `counts.errors` (genuine alert-infra failure).
- **D (#1372):** root cause was stubs SHADOWING the genuinely-installed alpaca-py; `ensure_alpaca()`
  binds the real package (tagged stub only when truly absent), ~70 shim files normalized via AST,
  one functional stub converted to restore-safe patch.dict, 16-test subprocess order-matrix
  harness + AST reintroduction tripwire. Zero production change; zero assertion touched.
  Follow-up (named, unfixed): 3 supabase/dotenv MagicMock module-leakers
  (test_jobs_db_jsonable / test_new_features / test_outcome_logic).
- **C (#1369):** repo-wide truth: exactly ONE duplicate 14-digit prefix (`20260723160000` ×3,
  pairwise-disjoint objects, each independently receipted; production tracking has NO collision —
  identity there is unique apply-version + exact name). CLI-level verdict
  **BLOCKED_TOOLING_COLLISION** (local CLI PK is version-only) — documented, not "fixed" by
  rename/reapply. Shipped: CI linter rejecting NEW duplicate prefixes, sha256-pinned legacy
  allowlist (normalized-LF basis), stdlib-only offline audit CLI, 26 tests. **No schema_migrations
  backfill advisable for the three collision files.**
- **A (#1371):** fleet evaluator universe v2 — **envelope-primary** (`td_scan_envelopes` keyed by
  `(cycle_id, candidate_fingerprint)`), including candidates rejected before `trade_suggestions`;
  suggestions are enrichment-only for the emitted subset (fp = `legs_fingerprint`, same
  `compute_legs_fingerprint`); missing fields ⇒ typed `data_unavailable`, never fabricated, never
  champion fallback (legacy builder ACTIVATION-BLOCKED and unwired). Shared capture gate
  `scan_candidate_capture_enabled()` (= new flag OR td-observe) decouples fleet readiness from the
  td scoring flag; byte-identical under today's flags. Fleet decision identity evolves:
  **statistical n over the complete universe = COUNT(DISTINCT candidate_fingerprint)**; suggestion
  UUID retained as emitted-subset provenance (COUNT(DISTINCT decision_event_id) = emitted n) —
  the small-tier contract's suggestion-UUID identity statement is superseded for the complete
  universe by this run's lane spec.

## Fleet v2 NO-WRITE replay (post-merge, tape `be9d5fe5-…`)
**Status `HONEST-EMPTY` — and that is the PASS.** 50 policies evaluated / 50 distinct config
hashes / 0 candidates seen / 0 provider / 0 broker / write_mode NO-WRITE. The tape predates
envelope capture, so the envelope-primary universe is empty — while champion `trade_suggestions`
rows for that decision DO exist (v1 found 1 candidate). v2 returning typed empty instead of
silently reusing them is a live proof of the anti-champion-fallback hard-stop. The
fingerprint-join falsifier remains **INCONCLUSIVE until the first capture-enabled natural scan**
(Friday 16:00Z) — by doctrine, not a defect.

## Read-only parallel work
- **APPLIED_UNTRACKED operator packet** (`docs/review/applied-untracked-operator-packet-2026-07-24.md`,
  fingerprint `d39ef69f…4ab581`): 149 files → 59 TRACKED / **87 APPLIED_UNTRACKED** (81 pre-era +
  6 recent actionable incl. the 04-26 `add_routing_mode` procedure miss) / 2 NOT_APPLIED (the
  deliberately-held paper-shadow pair) / 1 UNKNOWN (`trade_journal`, indeterminate). Surprise:
  `20260721011000_revoke_fleet_receipt_maintain` WAS effectively applied (production ACL shows
  MAINTAIN revoked — high-confidence inference from ACL effect). Single-leg 1/2/3/5 claims
  CONFIRMED (1/2 NEVER REAPPLY — unguarded CREATE POLICY). Proposed name-only 6-row backfill is
  **NOT EXECUTED** — operator-gated.
- **TD-scan v2 attribution audit** (`docs/review/td-scan-v2-attribution-audit-2026-07-24.md`):
  fingerprint identity chain verified (envelopes = ctd = trade_suggestions.legs_fingerprint);
  v2 gate attribution is achievable as a **read-side scorer join (Option A, ~0.5-1 day, zero
  scanner/schema change)** for all emitted + spread-gate rejects; leg-exact for remaining
  within-scanner rejects = additive Option B (~1 day). Join key must be
  `(cycle_date, candidate_fingerprint)` — cycle_id linkage is REPLAY_ENABLE-dependent;
  `option_quote_provenance.leg_fingerprint` is a different hash (recompute from legs jsonb).
  Build deliberately NOT started this run (stacked behind Lane A's contract freeze + Friday's
  first envelopes).
- **PR triage:** ONE closure — #1244 closed as functional duplicate of canonical #1213 (same
  hunk, same transformation; only the icon + a metadata file differ). All other candidate pairs
  diff-verified overlapping-not-exact and retained (#1084/#1196, #1083/#1133, #760/#791,
  #741/#742, #750/#885). No UI merges.

## Production writes + env (complete list)
The ONE migration above (+ its receipt row `b3e9bc3f` and the tracking row the apply created).
**Zero env changes. Zero broker writes. Zero fleet activation/binding/provisioning. Zero
control/schedule/threshold changes. entries_paused untouched.** All nine research evidence tables
still 0 rows at close; fleet `pending_legacy_terminal`, 50 inactive, 0 bound, 0 receipts.

## Natural falsifiers (Friday 2026-07-24 16:00Z scan — never manufacture)
1. Parent scan: `succeeded` with `result.research_observers` block present (`td_scan` /
   `shadow_fleet`), observer failures (if any) in `research_observer_failures` with
   `counts.errors` untouched; no observer-caused `job_succeeded_with_errors`.
2. First `td_scan_envelopes` rows: fingerprint-join falsifier (envelope fp == suggestions
   legs_fingerprint on the emitted subset) — grades the A-lane INCONCLUSIVE item.
3. Fleet readiness: typed `fleet_inactive` no-op, zero fleet writes.
4. Regime-V4 comparison rows; single-leg child first run; rejection-persistence counters clean;
   economic blocks terminal-blocked not errors. Plus the 05:00Z nightly.

## Known residuals (named)
C2 cadence lane OPEN (excluded by brief) · 3 non-alpaca MagicMock test leakers (follow-up) ·
TD-scan v2 build (Option A ready to build post-Friday) · APPLIED_UNTRACKED backfill packet
(operator-gated) · FLAG_ECHO visual confirm of the two 07-23 observe flags + the new
`SCAN_CANDIDATE_CAPTURE_ENABLED` echo line (next recycle's logs) · local `.env` Supabase host is
a homoglyph typo (`etd1la…` digit-1 vs real `etdlla…` letter-l — DNS-dead; operator should fix;
the replay ran with the corrected URL injected) · dead `import sys/types` cosmetics in ~62
normalized test files.
