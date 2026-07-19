# Audit Ledger — findings already found

Every finding listed here is EXCLUDED from future audit runs. Re-finding a
ledger item is a wasted slot. Runs append new findings as `status:reported`;
the human flips them to `status:shipped` (with PR#) or `status:rejected`.

## 2026-07-19 — v1.6 REMEDIATION ORCHESTRATOR (fable + opus; serialized) · status:partial-shipped

Full record: `docs/review/v1.6-remediation-results-2026-07-19.md`. Authorization: code/test/docs
merges only; ZERO migration / production-DB-write / broker / env / fleet / control actions (held).

- **#1303 `d6a3174e` MERGED+DEPLOYED** — v1.6 audit results docs, with the operator-directed
  F-A4-RISKBASIS-SILENT rewording (the finding is the ABSENT durable arm-decision/`would_flip`
  evidence contract; historical generic `[RISK_BASIS_SHADOW]` lines — null_legacy/heartbeat
  variants for `rbe_open_book`-class consumers — do NOT satisfy the arm gate). All four services
  SUCCESS at `d6a3174e`.
- **#1305 `8588754d` MERGED+DEPLOYED — the v1.6 HIGH (F-RUNNER-WORKTREE-DEADFALLBACK)**:
  disposable-worktree-only nightly runner (blank/whitespace env → real `%LOCALAPPDATA%` fallback;
  resolve-before-use; typed geometry refusals incl. equals/inside-operator/cwd/missing ownership
  marker; ALL destructive git through one re-verifying choke point `run_destructive_git`; operator
  checkout byte-preserved), typed `AppendResult` marker writes (never swallowed), durable sidecar
  `audit/runner-markers.log` with **per-run tag scoping** (`[run=date-pid-rand]` — a prior night's
  markers can never satisfy tonight's contract), completion re-read from disk, UP-ping only after
  all artifacts validate, `/fail` ping naming the missing artifact class, missing run-SHA fails
  closed. Independent opus adversarial review: **FAIL (1 BLOCKER: cross-run marker accumulation →
  false UP ping; + 3 MINOR) → repaired → re-verified PASS with independent falsifier probes.**
  55 route-driven tests (real temp git repos/filesystems). Self-test on merged content: 55 passed.
- **LOCAL OPERATIONAL LANDING: `BLOCKED_LOCAL_RUNNER_PULL`.** The operator checkout carries a
  TRACKED modification — the 00:00 CT nightly (OLD runner, cwd='.') appended its 07-19 FULL-audit
  entry (43 lines, incl. **F-REDATE-0718 MEDIUM**) to `audit/ledger.md` on a detached HEAD at
  `17141967`. Per the landing contract: no stash/reset — status+diff archived
  (`%TEMP%\otc-friday-post-close-2026-07-17\v16-remediation\`), and **this PR reproduces both the
  nightly's ledger entry (below) and the swept `audit/reports/2026-07-19.md` into main**, so
  tonight's old-runner reset cannot destroy them. **⚠ OPERATOR BEFORE 00:00 CT TONIGHT:** commit or
  reconcile the local `audit/ledger.md` edit, then `git fetch origin && git pull --ff-only` (or
  re-checkout main) — the fixed runner only protects the checkout AFTER the local pull. Scheduled
  task verified read-only (Ready; documented wrapper; workdir pinned; next run 07-20 00:00).
- **Six lane PRs BUILT + review-complete, MERGE-BLOCKED by the landing hard gate** (merge order
  fixed; each needs update-branch + current-head CI at merge time): Lane A #1306 `82ddee38`
  risk-basis arm evidence (durable `job_runs.result.cycle_metadata.risk_basis_arm_evidence`;
  utilization comparison moved to the REAL cap seam in `evaluate_entry`; typed
  `not_applicable_empty_book`; persist-fail → partial; enforcement dark) · Lane B #1307 `69a0b2bf`
  HMAC canonical prod detector + unconditional prod fail-closed nonce outage (typed 503) + ALL
  EIGHT #768/#769/#774 suites unskipped green (6210/0 local) · Lane C #1304 `d4c2dd97` holiday
  market sessions (broker calendar → typed `MarketSession`; entries fail closed; exits proceed;
  safety_checks true 9:30–16:00 ET + holiday/half-day) · Lane D #1310 `49e640e0` lifecycle
  milestones (schema-contract PASS — values already in the CHECK; append-only `detail.lifecycle`
  history; monotonic/idempotent; observe-only) · Lane E #1309 `2ffaeb89` OI known-at provenance
  (neither provider payload carries an OI date today — typed `provider_date_unavailable` stays
  truthful; observation-date vs retrieved-at separated; freshness only from real dates) · Lane F
  #1308 `7597a8a5` greek divisibility (one shared `_full_count_ratio` predicate; non-divisible leg
  → typed uncovered both consumers; byte-identity proven; caps dormant).
- Safety held at every step: broker flat 0/0 · 0 new critical/high · `entries_paused=false` ·
  fleet untouched (1 `pending_legacy_terminal`/50 inactive/0 bindings/0 receipts).
- NOT build slots (unchanged): A1-G1 (natural post-07-16 realized overlap) · A2-ASSIGNMENT
  (DEFERRED-SAMPLE) · UI (Palette-owned) · fleet activation (Monday evidence + separate token) ·
  N1/N2/CLAUDE-size notes.

## 2026-07-19 — EXTERNAL FULL AUDIT v1.6 ADJUDICATION (fable orchestrator + 5 opus area agents; READ-ONLY) · status:reported

Executed `docs/review/external-full-audit-v1.6-current.md` (source classification
**AUDIT_BRIEF_ONLY** — the document is an audit SPEC; absence of embedded results is expected,
not a finding). Pinned immutable basis **`20ca312e`** = origin/main, all three services
deploy-verified at it; issuance baseline `fdf5b55c` → pin delta = this session's own reviewed
merges #1296–#1302 (incl. the operator's #1301 brief-merge). Sunday market-closed window ⇒
runtime adjudication READ-ONLY: natural absence = **DEFERRED-SAMPLE**, never INCONCLUSIVE;
nothing was triggered. Baseline: broker flat 0/0 · 0 crit/high 72h (41 warn + 9 info) ·
`entries_paused=false` · fleet 1 `pending_legacy_terminal` / 50 inactive / 0 bindings / 0
receipts · registry 50/50 approved. Full results (draft PR, NOT merged):
`docs/review/external-full-audit-v1.6-results-2026-07-19.md`. **ZERO code /
test-outside-docs / migration / DB-write / broker / env / fleet / deploy / merge actions.**

**Retained (ranked; 10 findings + notes):**
1. **F-RUNNER-WORKTREE-DEADFALLBACK — HIGH** (A9; EXTENDS the OPEN nightly-runner P1 — the
   root cause of 07-19 WRAPPER_PARTIAL): truthy `Path("")` at `nightly_runner.py:918` kills
   the `%LOCALAPPDATA%` fallback ⇒ worktree=`.` ⇒ the runner ran `git checkout --force
   --detach origin/main` + `reset --hard origin/main` against the OPERATOR CHECKOUT
   (reflog-proven; tracked `audit/ledger.md` uncommitted edits are at risk on every nightly)
   AND cron.log markers were dropped (sharing-violation append swallowed at `:87-94` under the
   shim's own redirect lock) while `_end_marker_written` was set unconditionally ⇒ completion
   contract "met" + dead-man UP-ping fired over an empty evidence sink — success
   indistinguishable from silent death, the exact mode #1264 was built to kill. Proof
   VERIFIED-CODE + reflog.
2. **F-A4-RISKBASIS-SILENT — MED** (A4, NEW): the exact P0-B arm-decision / `would_flip`
   evidence required for the observe→enforce decision has not emitted or reached its expected
   durable evidence contract (`services/risk_basis_shadow.py:31` / `risk_budget_engine.py:418` /
   `utilization_gate.py:353`). Historical generic `[RISK_BASIS_SHADOW]` lines (e.g.
   `basis=null_legacy` / heartbeats for `rbe_open_book`-class consumers) do not satisfy that
   gate, and log lines are ephemeral — the P0-B arm gate cannot clear on what exists today.
3. **F-A9-1 — MED** (A9, NEW P2 security; proof INFERRED-from-code):
   `task_signing_v4._is_production_mode()` (`:59-79`) diverges from canonical
   `security/config.is_production()`; an APP_ENV-only prod worker fails OPEN on nonce-store
   outage (replay window widens to the 300s TTL) while `audit_production_security()` reads
   healthy.
4. **F-A9-2 — MED** (A9; EXTENDS skip-discipline): HMAC/security behavioral suites are
   module-skipped (#768: task_signing_v4/run_signed_task/admin_auth/security_v3 · #769:
   is_localhost_spoofing · #774: security_headers/api_info_disclosure/optimizer_security) —
   replay/expiry/scope/fail-open have zero CI reach; the un-skipped fleet route test covers
   happy-path + unsigned→401 only.
5. **F-A10-HOLIDAY — MED, mitigated** (A10, NEW P2 calendar): `is_market_day()` weekday-only
   with an affirmatively false docstring (`jobs/handlers/utils.py:49-69`; consumers
   `suggestions_open.py:77` / `suggestions_close.py:54`); `safety_checks.py:100-108`
   holiday-blind. Mitigations: broker rejects closed-market orders; monitor + cooldown use the
   holiday-aware broker clock.
6. **A1-G1 — LOW**: ranker-basis zero realized overlap (detail in the results file).
7. **A3-LIFECYCLE — LOW/NOTE**: disposition lifecycle values `staged`/`broker_submitted`/
   `filled` defined-not-wired (`candidate_disposition.py:82-85`); lifecycle stops at persist.
8. **A5-OI-KNOWNAT — LOW/NOTE**: OI freshness unobservable — `oi_freshness` always
   `known_at_unavailable` (`quote_provenance.py:261-266`; truth layer `:1856` never sets
   `open_interest_date`).
9. **A2-ASSIGNMENT — LOW · DEFERRED-SAMPLE**: assignment/expiry custody NOT-PROVEN — no
   natural sample exists; revisit on the first ITM-at-expiry live event.
10. **A4-DIVISIBILITY — LOW-INERT**: `check_greeks` divisibility edge; inert while all caps 0.

**NOTEs (not findings):** stale version-prefix comments (N1) · model-review fingerprint is
id-set-only, content-blind (N2) · CLAUDE.md **70,827 B** vs the historical ≤40k self-cap (cap
silently dropped from the header 07-16 rather than the file trimmed) · settings.json cosmetic
`Write(audit/**)` warning · `secrets_audit.py` real but not CI-wired · **case-collision**: BOTH
`.Jules/palette.md` AND `.jules/palette.md` are tracked (distinct blobs) — on a case-insensitive
Windows checkout they collide into one file, so one of the two paths shows phantom `M` drift
(VERIFIED in the fresh v1.6 audit worktree; restoring one re-dirties the other by construction;
manifestation is checkout-order/ignorecase dependent — the operator checkout does not currently
show it; fix = de-dup the tracked path in a normal code PR).

**Free-look: 0 promotions** (≤2 budget unused — every candidate folded into an area finding or
dedup'd). **Fleet verdict: READY_FOR_SEPARATE_AUTHORIZATION** (activation forbidden pending the
Monday evidence PASS + separate token). **No live-control loosening recommended anywhere.**

**Exclusion memory held (duplicates correctly NOT re-found; do not re-find these either):**
WRAPPER_PARTIAL + F-RUNNER-BROKER-CREDS (now root-caused by finding 1) · taper band
`[900,1100]`-vs-`[800,1000]` · shadow-fill fiction · greeks double-dormant · EXIT_EVAL_DEBUG
partial fix · severity-taxonomy fragmentation · A4-detector single-convention · legacy-mode
WARNING on designed client=None · winter-close blind hour (**RESOLVED** — DST-aware ET +
broker-clock gating confirmed at the pin). **Clean re-verifications (cite, don't re-prove):**
flag echo #1268 live in prod (30 flags, 0 parse errors) · fleet 4-gate fail-closed + registry
immutability trigger + one-way draft · ratify≠activate (docs-only, 0 receipts) · #1300 reader
read-only test-pinned · job_runs 519 succ / 0 failed / 0 partial (4d) · H8/H11 clean.

## 2026-07-19 — SUNDAY IMPLEMENTATION ORCHESTRATOR (fable + opus; serialized) · status:shipped

Full record: `docs/review/sunday-implementation-results-2026-07-19.md`. **Five merges**, each
adversarially (Fable-central) reviewed, serialized, per-merge all-services deploy SUCCESS
(VERIFIED-GITHUB + VERIFIED-DEPLOYMENT). Serialized order #1296→#1299→#1297→#1298→#1300; final
code main **`27204bd0`**. **ZERO broker / production-DB-write / migration / env / fleet mutations
this run.**

- **#1296 `8a7908f1`** ⑤ scorable-outcome join readiness — end-to-end producer→consumer contract
  test; **COMPLETE verdict, no join gap** (the challenger-scorable spine is proven wired end to
  end); both spot source labels pinned (scan-time capture vs typed-unavailable).
- **#1299 `fdf5b55c`** TCM v2 multi-fill realized accrual — side-flip boundary handled; per-side
  **all-or-unavailable** sums (a partial-known side types UNAVAILABLE, never summed as partial);
  AMD proof `$1.30` true vs `$0.65` prior undercount; observe-only.
- **#1297 `df87fe93`** single-leg one-contract selection — deterministic tie-breaker
  **EV→delta→debit→lexical**; **DARK, 0 opt-in, zero production callers** (selection for opted-in
  policies is the next slice; nothing selects today).
- **#1298 `4ffca2b1`** owner ratifications v1 — **7 decisions RECORDED, none activated**; the
  frozen **E19 protocol hash is UNTOUCHED** (immutability pin stays green); **taper band conflict
  recorded** — engine `[900,1100]` (`BAND_PCT=0.10`) vs ratified `[800,1000]`; per the conflict
  rule the engine is NOT altered, reconciliation = a later code step.
- **#1300 `27204bd0`** Monday consolidated evidence reader — 12 natural-evidence sections,
  **four-state honesty** per section (`OK` / `HONEST-EMPTY` / `FAILED-FETCH` / `NOT-FETCHED`; a
  failed fetch is never scored zero, H9); operator prompt
  `docs/review/monday-evidence-operator-prompt-2026-07-20.md`; read-only pure function.

**Phase 1 — Sunday nightly under the wrapper: WRAPPER_PARTIAL.** The 07-19 00:00 CT shim launched
the new runner and a VALID FULL audit report was produced (SHA-pinned `17141967`, **0 crit / 0
high**), BUT the runner's start/end markers, heartbeats, fresh-worktree path, and completion ping
did **not** land in the operator `cron.log` (manifest `workspace.path='.'`; **no `%LOCALAPPDATA%`
worktree** — the runner ran with `cwd='.'` semantics). ⇒ **nightly-runner reliability P1 stays
OPEN.** Morning items: (1) fix the marker / fresh-worktree wiring; (2) **check the 07-19 dead-man
ping at the provider** (it did not reach the log). New finding **F-RUNNER-BROKER-CREDS** —
scrubbed broker snapshot `available:false` (broker creds unset in the shim env; non-blocking, a
morning wiring fix, not a trading-control issue).

**Phase 2 — Fleet activation dry-run (signed replication): SIGNED_DRY_RUN_PASS.** `plan_activation`
proven zero-write / no-env by CODE (`:639-685`); fingerprint `6f8d1499…` recomputed from the ops
bundle **AND** rebuilt from pure DB truth to the SAME hash; **350/350 binding field-cells match**;
fleet counts byte-identical before/after (1 `pending_legacy_terminal` / 50 inactive / 0 active / 0
bindings / 50 `shadow_only` / **0 activation receipts**). **ACTIVATION STILL FORBIDDEN** — needs
the Monday natural-evidence PASS + a separate explicit operator token per ratification 1
(`FLEET_ACTIVATION_AUTHORIZED=1` + `execute_activation` confirm-literal + idempotency key + 50-slot
payload + §4 attestation). Readiness is not authorization; recorded as read-only replication.

**Dark/observe-only states (nothing armed):** single-leg DARK 0/50 opt-in · TCM v2 observe-only
(ratified promotion N=15, a later review) · taper DARK (**band reconciliation pending**: engine
`[900,1100]` vs ratified `[800,1000]`) · greek caps 0 (Plan A staged) · OI no-gate · E19-2B BLOCKED
(ratified minimum **8** awaits protocol **v3 re-freeze** per its §13 procedure) · UI
**BLOCKED_UI_FILE_OWNERSHIP** (Palette-owned). Operator checkout at hash **`ddb9e073`** — the only
drift from main is the nightly's own artifacts (untracked dated report + local runner outputs), not
a code divergence. `ACTIVATE_FLEET=false`; `entries_paused` untouched.

**Owner decisions still OPEN (the seven ratification packets):** fleet ACTIVATION (first, after
Monday PASS; + token + attestation) · `h7_dropped` retention (RETAINED, ratifies merged code, no
step) · E19 §7 minimum adoption (protocol v3 re-freeze) · single-leg opt-in designation (two NEW
draft rows) · TCM promotion at N=15 · taper band reconciliation + activation · greek-cap arming
(Plan A stages).
## 2026-07-19 — FULL AUDIT (Sunday; first wrapper-flow run; broker-blind) · status:reported

Report: `audit/reports/2026-07-19.md`. Run SHA `17141967` all three services; DB-clock grounded
Sunday 00:01 CT; 0 critical/high 72h; 18 SQL / 0 broker / 4 subagents. Findings (status:reported):

- **F-REDATE-0718 (A3, MEDIUM):** the 07-18 F-CREDIT-SIGN correction re-inserted the 20 corrected
  shadow learning rows into `learning_trade_outcomes_v3` with `closed_at`=2026-07-18 (correction
  time) instead of true close times (positions + `learning_feedback_loops` preserve truth; values
  consistent 24/24). ≈ +$33,856 phantom 20-close cluster dated 07-18 enters
  `go_live_validation_service.py:335,525,1089,1459,2413,2673,2917` paper windows +
  `walk_forward_autotune.py:410` + `context_endpoints.py:43,53`. Live calibration EXCLUDED
  (`calibration_service.py:390-391` is_paper=false), model review (#1286) unaffected (id-set
  fingerprint), signal_accuracy live-only. Fix: operator-gated re-stamp from `paper_positions`
  truth via trace_id (fingerprint like the weekend corrections).
- **F-RUNNER-BROKER-CREDS (A4, LOW-MED, operator):** first wrapper run otherwise PROVEN (manifest,
  fresh worktree, wake lock, completion contract) but the broker snapshot fail-softed
  `available:false` — `broker_snapshot.py:132-135` reads `ALPACA_API_KEY`/`ALPACA_SECRET_KEY` from
  process env only; no fallback; no documented setup step; headless runs stay broker-blind until
  the operator places read-only creds in the Task-Scheduler env + docs the step.
- **A9 LOW (latent):** `safety_checks.py:279` hardcodes rejection_reason "Portfolio routing_mode
  flipped…" on a path that (post-#1292) also carries the single-leg veto — a veto row would record
  a false cause. Correct critical fires alongside (`execution_router.py:146-166`); 1-line PR; dark
  while 0/50 opt-ins.

Verifications CLOSED (cite, don't re-find): **E6/P0-A broker-ack-close invariant SHIPPED**
(`paper_exit_evaluator.py:2286-2333` + backstop :2335-2379; runtime falsifier = next natural live
close failure, INCONCLUSIVE until then) · **F-CREDIT-SIGN code fix confirmed at HEAD**
(:2387-2399) **+ data corrections VERIFIED-DB** (QQQ c1c9ad04 = −224.04; v3↔lfl 24/24) · fleet/
registry state verified (50/50/50-hash; 1 fleet pending_legacy_terminal; 50 accounts; orders census
all-terminal = packet §3) · migration/seed/provision receipts all present (8 info rows) · first
natural `ranking_costs` row (Friday suggestion; `vrp_ranking` NULL = INCONCLUSIVE) · new weekend
writers CLEAN (dispositions/provenance/greek-cap/flag-echo honesty content-verified) · single-leg
veto dark at 4 sites, multi-leg byte-identical · taper DARK · P0-B decisive basis still premium
(`RISK_BASIS_MAX_LOSS_ENABLED` default OFF). Clarification: **winsorize/outlier-cap is NOT-BUILT**
(no implementation in `calibration_service.py`; the [0.5,1.5] clamp :527/:543 is the only outlier
control) — the "8th-close winsorize gate" is a decide-whether-to-build owner review, queued with
the clamp review (floor binding: `_overall` 0.5/0.5, sample 8, error 65.34, stable 07-15/16/17).
Calibration floor-pinned since the 07-10 relearn (pool at 8 since 07-08 18:00Z — the 07-14/07-15
closes were shadow). Pending carried: #1198 INFO line + thesis price_basis (needs an RTH day) ·
Monday naturals (dispositions/provenance first rows; morning dry-run re-check) · A10→SECURITY
rotation proposal standing (A11, owner-gated). Sunday fleet-activation gate (packet-1 prereq 1):
met from this run's side — clean dated report at `17141967`.

## 2026-07-19 — PARALLEL IMPLEMENTATION ORCHESTRATOR (fable + opus; serialized) · status:shipped

Full record: `docs/review/parallel-implementation-results-2026-07-19.md`. **Six merges**, each
adversarially reviewed, serialized, per-merge all-services deploy SUCCESS (VERIFIED-GITHUB +
VERIFIED-DEPLOYMENT). Serialized order #1290→#1289→#1291→#1293→#1294→#1292; final code main
**`4851ec8d`**. **ZERO broker / production-DB-write / migration / env / fleet mutations this run.**

- **#1290 `89a736807`** D3 ratio-blindness FIXED — `leg_full_contract_count` owner helper; a 1×2
  ratio spread now scales to 150 (was ratio-blind); a 1:1 structure is byte-identical to the
  pre-fix path; `check_greeks` + `compute_stress_scenarios` both migrated to the helper. **§8 D3
  ratio-blindness line now RESOLVED** (the last-pinned greek defect).
- **#1289 `b3f10031`** TCM v2 realized-accrual reporting — no schema; the join spine (v2 stamp →
  realized close) is proven; **0 / 528 v2 stamps exist yet** — v2 accrues on post-#1278 cycles, so
  the report is empty-by-construction today (accrues naturally forward).
- **#1291 `bd87025f`** SQL-mirror parity fixtures — 6 families, 78 tests; **ZERO defects found**
  (the SQL mirror already agreed with the Python path across all six families).
- **#1293 `d60b7ad0`** fork/collection sweep — root cause = rq fork-context at import; 6 files
  fixed; 12-file subprocess harness; **full-suite collection now 0 errors** (closes the
  fork-uncollectable P2 tail).
- **#1294 `21e88e5f`** seven owner-decision packets — `docs/review/owner-packet-1..7`:
  (1) activation-after-Sunday+Monday · (2) RETAIN `h7_dropped` · (3) E19 minimum = **8** (alt 15) ·
  (4) single-leg opt-in = two NEW draft registry rows + matched controls · (5) TCM N = **15**
  (alt 10) · (6) taper `[800,1000]` band · (7) greek caps Plan A staged.
- **#1292 `4851ec8d`** single-leg hard veto at the REAL submit seam — `should_submit_to_broker`
  guard at **4 sites**; byte-identity proven against 100% of live rows; VRP second gate (resolves
  #1287's C1); raw-jsonb registry opt-in lookup, **0 / 50 enabled** → veto stays DARK; two repair
  cycles synced stage-route fake signatures. (Lands the veto at the seam #1287's reviewer R1
  identified — `execute_order` guard host was DORMANT.)

**Fleet DRY-RUN (Phase 1, READ-ONLY) — VERIFIED-DB (reads only, NO writes):** registry 50 / 50
approved, per-row hashes recompute-clean; fleet counts BEFORE == AFTER byte-identical (1 fleet
`pending_legacy_terminal` / 50 inactive / 0 active / 0 bindings / 50 `shadow_only` / 0 receipts);
binding manifest fingerprint
`6f8d14995ff4371bf940364d90bf82de1faff188823cf3e61280b81740836bad` (`ORDER BY
policy_registration_id ASC`; anchors slots 17 / 33 / 50); **all 13 replicated checks PASS ⇒
`READY_TO_ACTIVATE`**. Artifacts (manifest JSON + dry-run md) in the ops bundle (outside repo).
**ACTIVATION REMAINS FORBIDDEN** — no un-activate RPC exists (reversal = retire path), so it is
irreversible-in-place and owner-gated; recorded as read-only replication, not service invocation.

**Dark/observe-only states (nothing armed):** single-leg DARK 0-opt-in (veto now owns the real
seam) · TCM v2 observe-only (frozen model retains authority) · taper DARK · greek caps 0 · OI
no-gate · E19-2B BLOCKED (§7 minimum now recommended 8/alt 15, unratified) · event-review inert.
Operator checkout **clean-behind** at hash `5c6ae8bf…` (fast-forward pull, no reconciliation this
run). UI still Palette-owned. `ACTIVATE_FLEET=false`; `entries_paused` untouched.

**Owner decisions still OPEN (the seven #1294 packets):** fleet ACTIVATION (first, after
Sunday/Monday PASS; + attestation) · `h7_dropped` retention ratification · E19 §7 minimum ·
single-leg opt-in designation · TCM promotion N · taper activation band · greek-cap arming.

## 2026-07-19 — OWNER-DECISIONS ORCHESTRATOR (fable + opus; serialized) · status:shipped

Full record: `docs/review/owner-decisions-implementation-2026-07-19.md`. **Ten merges**, each
adversarially reviewed, serialized, per-merge all-services deploy SUCCESS (VERIFIED-GITHUB +
VERIFIED-DEPLOYMENT): **#1278 `1d1951d8`** TCM v2 routing-aware dual-run (OBSERVE-ONLY; frozen
model retains authority; promotion packet emitted, owner picks N) · **#1280 `79f4ba76`** F-BAN
phantom REMOVED (dead reads / silent `[]` degradation / unfireable enforcement deleted; no-op
proven BY CONSTRUCTION; `settings.banned_strategies` drift column ledgered for a later drop) ·
**#1282 `3c3874e1`** greek-cap alert-only counterfactual (items 9+11 consolidated; reference caps
INVERTED from envelope doctrine; headroom/would-block evidence only, NO enforcement — all caps 0)
· **#1281 `4c12dafa`** H7 mandatory typed subreason (5 canonical + sentinel; E1→`quality_gate`
adjudication; **owner ratification of `h7_dropped`-for-gate-deaths OPEN**) · **#1279 `78c71a8e`**
versioned policy registry + 3-anchor/47-variant design of the 50 (provisioning trigger HARDENED to
one-way-draft after review) · **#1283 `ed5d6f48`** continuous tier taper w/ hysteresis DARK
dual-run (no live consumer, no env flag in live code; activation packet
`docs/specs/tier_taper_activation_packet.md`; conservative `[800,1000]` band alternative) ·
**#1284 `7d95f143`** E19-2B preregistered protocol v2 FROZEN (hash `50e7e237…`; execution BLOCKED —
§7 `MINIMUM_DISTINCT_SOURCE_EVENTS` UNDEFINED, owner packet; arm B CONTENT-pinned) · **#1285
`e161714f`** exact-leg OI capture + hypothetical-floor counterfactuals (observe-first, NO gate;
floors 100 code-anchored / 1000 doc-anchored / 250–500 labeled UNANCHORED) · **#1287 `9b63dcc1`**
single-leg one-contract shadow-only experiment DARK (0 opt-in policies; reviewer notes for the
future wiring session — **R1** `execute_order` guard host currently DORMANT, real submit seam is
`should_submit_to_broker`; **C1** VRP citation UNWIRED) · **#1286 `cef4e600`** event-driven model
review (inert until the first scorable close; quarantine-helper route corrected after a CI catch;
SQL-mirror fixture gaps noted for Phase-3 volume). **Final code main: `cef4e600`.**

**Ledger reconciliation (Phase 1):** three-way matrix (local vs main vs bundle) verdict
**0 PRESERVE / 4 REJECT** — the local +281 was PURE LAG (3 sections byte-identical to main, 1 fully
superseded). Operator checkout RESTORED + fast-forwarded to main; the blocking untracked reports
were proven byte-identical to main's tracked copies, preserved then replaced; the
reconciliation-branch step recorded as a **NO_SECTIONS_APPROVED no-op**; preservation archive
outside the repo, timestamped `20260718T2310Z`. **The nightly wrapper is now LIVE** for tonight's
00:00 CT run (first wrapper-flow run).

**DB actions (VERIFIED-DB; migration procedure, receipts in `risk_alerts`; NEVER REAPPLY):**
`policy_registrations` migration (receipt `eac6a4b9…`) · 50-row approved seed in ONE fingerprinted
transaction (receipt `14ca10ab…`; 50 rows / 50 distinct hashes / 0 mismatches / lineage 17-17-16 /
0 bindings) · `h7_subreason_check` `NOT VALID` then `VALIDATE`d (receipt `6c49ce87…`).

**Fleet PROVISIONED INACTIVE (VERIFIED-DB):** fleet `b8b1ea1f…`, status `pending_legacy_terminal`;
50 inactive `$2,000` slots; 50 `shadow_only` portfolios; 0 policy bindings (binding is
activation's job); idempotency PROVEN (re-run → `already_provisioned`, 0 writes); 1 provision
receipt / 0 activation receipts. **`ACTIVATE_FLEET` remains `false` — NOT activated.**

**Dark/live states:** taper DARK (no env flag in live code) · greek caps counterfactual-only (all
caps 0) · TCM v2 observe-only · single-leg DARK · OI observe-first NO gate · E19-2B BLOCKED ·
event-review inert-until-natural-trigger · UI BLOCKED_UI_FILE_OWNERSHIP (40 Palette PRs own the
files). ZERO broker writes; ZERO fleet activation; `entries_paused` untouched.

**Owner decisions still OPEN:** E19 §7 minimum · `h7_dropped`-for-gate-deaths ratification · fleet
ACTIVATION authorization (+ attestation; slots bind at activation from the 50 approved registry
ids) · single-leg opt-in policy designation · TCM promotion N · taper activation band choice ·
greek-cap arming.

## 2026-07-18 — SATURDAY-EVENING ORCHESTRATOR (3rd Sat run; fable + ≤6 opus) · status:shipped

Full record: `docs/review/saturday-evening-results-2026-07-18.md`. Six merges,
each adversarially reviewed (+2 FAIL→repair→re-verify cycles), per-merge
deploy-verified: **#1274 `e2f91ac2`** ⑤ scan-time spot threaded scanner→
order_json→stage (deterministic provider-ts as_of; ⑤ capture now COMPLETE:
delta+IV+spot — first post-tonight closed outcome is adapter AND challenger
scorable) · **#1272 `94a4cdb3`** E4/E5 quality-gate hard-mode deaths now
record exactly one final (`h7_dropped` + reason + `sizing_outcome=
'marketdata_quality_gate'`; ⚠ owner ratification of the value = open item) ·
**#1271 `53e86f53`** scanner source_used mislabel (in-memory only) ·
**#1273 `9cb3876a`** realized cost consumer #3 (review caught INVERTED fees
provenance → repaired per-routing: broker-routed = REAL $0 Alpaca commission,
internal typed-unavailable; evidence: TCM over-charges commission −1.55 mean;
F-CREDIT-SIGN double-correction REFUTED — all 19 were pure sign-flips) ·
**#1275 `da70b67e`** drift-summary collection quirk (test-only) · **#1276
`02b2d8b0`** stress-model D2 residual CLOSED (signed via canonical
`_direction_sign`; clamp preserved; `worst_case ≡ correlation_one` proven →
warn surface byte-identical; §8 stress-residual line RESOLVED).
**Operator pull: BLOCKED_OPERATOR_PULL_CONFLICT** — dirty tracked
audit/ledger.md (+281 lines) overlaps main; delta patch + handoff in bundle;
tonight's 00:00 CT nightly runs the OLD flow under the NEW task protections;
wrapper flow starts after the operator pull. Runtime prompts refreshed
(sunday-nightly-audit-verification-2026-07-19.md + monday check extended).
ZERO broker/production-DB/fleet/migration actions; operator worktree
byte-identical (`0d3067b4…`).

## 2026-07-18 — SATURDAY-NIGHT ORCHESTRATOR (2nd Sat run; fable + ≤6 opus) · status:shipped

Full record: `docs/review/saturday-night-results-2026-07-18.md`. Six merges,
all adversarially reviewed + deploy-verified: **#1264 `592a267a` nightly-audit
runner** (all 6 failure-class findings VERIFIED: sleep-kill, stale checkout,
headless broker-blind, no-transcript, existence-not-completeness ping; wrapper
+ fresh origin/main audit worktree + GET-only scrubbed broker snapshot +
completion contract; **local Task Scheduler task re-registered** — 4 deltas,
backup+rollback in bundle; self-test PASS; ⚠ operator must `git pull` the
checkout before Sun 00:00 CT for the wrapper flow) · **#1265 `35836cdc`**
scanner cost bases → disposition artifact · **#1263 `a558de7e`** canonical
greeks wiring (sign-once proven) · **#1269 `fdcaf644`** D2 FIXED in
check_greeks (signed net via canonical `_direction_sign`; re-landing of
reviewed #1267 after stacked-squash conflict; 4 defect-pins flipped to pin
the fix; caps stay 0) · **#1266 `851416a0`** ⑤ per-leg IV capture + typed-
unavailable spot (review FAIL→repair→re-verify PASS: STUDY_SQL close-
contamination fixed — marker-gated open-order LATERAL, geometry always
suggestion legs) · **#1268 `76757684`** startup flag echo, 27 flags, real
parsers (in-lane repair: the wiring test was itself a sys.modules polluter →
subprocess route tests). **Packets:** fleet manifest (3 honest identities vs
50 — gap 47; options gap-stated; registration design specced; strict-endpoint
provisioning/activation prompts SUPERSEDE the old direct-RPC prompt) ·
sizing-loop taxonomy (Option-C rec; **E4/E5 invariant hole found** —
quality-gate HARD drops a selected candidate with NO disposition row, latent
bug; E3e/E3f mislabels) · Monday natural-evidence prompt. **New liars/
findings:** strict-`=="1"` quartet (CALIBRATION_ENABLED — `true` DISABLES it —
SCHEDULER_ENABLED, RISK_ENVELOPE_ENFORCE, RISK_UTILIZATION_GATE_ENABLED;
§3 wording corrected; echo now prints effective values every start) ·
options_scanner.py:4213 source_used↔samples_used mislabel (LOW) · stress-model
unsigned-add D2 residual (payoff-clamped safe; future lane) · ⑤ challenger
still needs a spot source (endorsed follow-up: thread scan-time
current_price). ZERO broker/production-DB/fleet/migration actions; operator
worktree byte-identical (`0d3067b4…`).

## 2026-07-18 — WEEKEND ORCHESTRATOR (Sat; fable + ≤6 opus; serialized production writes) · status:shipped

Full record: `docs/review/weekend-results-2026-07-18.md`. Four data
corrections committed serially, each opus-revalidated exact-set first,
broker/alert checkpoint after each (broker 0/0 + 0 crit/high throughout):
**F-CREDIT-SIGN applied** (fp b780271c…; 19 orders / 18 positions −14,367 /
19 ledger adjustments −16,971 / 20 learning / 9 policy; census-zero after;
2 win→loss flips QQQ −224.04 + AMD −242.00; shadow-only, streak breaker
unaffected) · **six 04-09 stale orders → cancelled** (fp 04317fc1…) ·
**seventh row a94a2761 → cancelled/local_validation_reject_never_sent**
(investigation CONCLUSIVE + second-review PASS-WITH-AMENDMENT; plan fp
5d5cd9fc…; 'rejected' rejected — codebase never persists it) · **five
orphan job_runs → cancelled** (fp 40258ba9…; CAS-guarded). **Legacy-terminal
boundary now FULLY CLEAN (0/0/0)** — the SEVEN activation blockers are
resolved. Six code lanes merged w/ adversarial review + per-merge deploy
verify: #1257 4b311180 (landmine defused) · #1256 25d0f494 + **migration
20260718144818 APPLIED** (job_runs CHECK + 'partial'; zero rows changed;
receipt 38e5ecd9…; NEVER REAPPLY) · #1258 72f689c0 (cost-recon artifact,
zero readers) · #1259 7f393580 (stage-time leg greeks — the greeks envelope
is now SINGLE-dormant: legs populated forward, caps still 0) · #1260
264b720d (⑤ study: **INSUFFICIENT_EVIDENCE** — 100% challenger abstention,
blocker = stage-seam iv/spot/delta capture, not model quality) · #1261
e0a1584 (check_greeks null-safe + greeks_coverage; dormancy byte-proven).
**Fleet: BLOCKED_FLEET_PROVISION** (env-gate FLEET_ACTIVATION_AUTHORIZED
required by execute_provision + no 50 pre-registered policy ids; owner
manifest in bundle `fleet-readiness-2026-07-18.md`; zero fleet writes;
activation forbidden+untouched). **NEW findings:** ① nightly audit runner
DIED 07-16 + 07-17 (no reports; 07-18 ran broker-blind) — runner
reliability P1; ② BE deploy FAILED at e0a1584 despite clean container
start (cause NOT-PROVEN; BE serving 264b720d; mixed backend at close —
morning ritual verifies convergence after the docs merge); ③ erratum:
job_runs terminal vocabulary is the six-status set (cancelled/dead_lettered
ARE terminal). Pending naturals unchanged + new: first natural 'partial'
row · challenger scorability (needs stage-seam iv/spot capture).

## 2026-07-18 — THREE MIGRATIONS APPLIED (Fable migration orchestrator, opus reviews) · status:shipped

Applied serially 03:34–03:40Z, market closed, verbatim from main `aeab21d8`
via mcp apply_migration (never `db push`); preflight ABSENT_CLEAN ×3;
tracked by NAME: `shadow_fleet_activation_rpc`→`20260718033415` ·
`candidate_terminal_dispositions`→`20260718033912` ·
`option_quote_provenance`→`20260718034013`. **NEVER REAPPLY.** One
`migration_apply` receipt each (risk_alerts ids 7a3c52c1… / 0a50d417… /
ec013a5d…). Verified: RPC pair exact-signature, EXECUTE service_role-only;
dispositions 19 cols + partial-unique final + RLS; provenance 31 cols +
partial fallback idx + RLS; both new tables 0 rows. Supersedes the
"Three migrations UNAPPLIED" line in the sprint entry below. Zero fleet
provisioning/activation (fleet tables still 0 rows); SEVEN activation
blockers re-verified unrepaired; F-CREDIT-SIGN/stale-order/orphan-job
corrections NOT applied (zero data-table UPDATE/DELETE); broker flat 0/0 at
all three checkpoints; 0 new crit/high; entries_paused=false; deployed SHA
unchanged (worker SUCCESS `aeab21d8`). Side-note (07-18): orphan check must
treat `cancelled`/`dead_lettered` as terminal — non-terminal = 4 running +
1 queued = the census 5. Pending natural falsifiers (unchanged owners):
disposition/provenance writers first natural rows Mon 07-20 scan cycle ·
fleet provision/activate sequence (operator prompts in bundle).
Results doc: `docs/review/migration-results-2026-07-18.md`.

## 2026-07-18 — FRIDAY POST-CLOSE SPRINT MERGED (Fable orchestrator, opus reviews) · status:shipped-code/runtime-pending

Serialized merges w/ per-PR opus adversarial review, per-merge deploy
verification (GitHub combined status all-services SUCCESS) and broker/alert
safety checks (flat book, 0 crit/high throughout). Squash SHAs: 1947f97c /
276f45d4 / c20f1ae8 / ce2710cb / 08e250d9 / 79790b80 / bb489fdf / c51f41eb.
Three migrations UNAPPLIED (rpc/dispositions/quote-provenance) — bundle
prompts own the applies. Censuses (read-only, fingerprinted): F-CREDIT-SIGN
19-close set fp b780271c… (−14,367/−16,971; QQQ canonical to the cent; live
calibration never contaminated) · stale orders 6/6→cancelled fp 04317fc1… ·
orphan jobs 5/5 dead fp 40258ba9… (side-finding: 'partial' missing from
job_runs CHECK — latent HIGH, needs 1-line constraint migration). SEVEN
activation blockers re-verified post-merge. sys.modules poison class: 2
polluters fixed, 1 landmine remains (test_capital_basis_consistency.py).
Pending natural falsifiers: first live-open preflight · first internal credit
close (post-#1240) · budget_snapshot family truth · disposition/provenance
writers self-activate at migration apply · #1228 reader · #1229 (09-07).
No broker write · no unauthorized DB write · no migration applied · no fleet
row/activation · operator worktree preserved (inventory hash b89a7ca3…
unchanged start-to-finish).

## 2026-07-17 — POST-MERGE RECOVERY SPRINT · status:reported/drafts-pending

**07-17 05:xxZ EXECUTION ADDENDUM (operator-instructed):** #1242 repaired
(CI-only 401 = collection-time auth-patch leakage; diagnostic run proved
override_keys=[] + stale symbol id; fix = route-resolved override keys) and
**MERGED** -> main `e4e634b`; #1241 merged by the operator in parallel
(`6bc0b5f`). **Fleet schema APPLIED** (05:22Z; tracked `20260717052208
small_tier_shadow_fleet`; verified: 2 tables, 0 rows, decision_event_id
0-null/0-mismatch, trigger live) — SCHEMA ONLY, activation still
operator-gated behind the legacy-terminal attestation (6 stale 04-09
'submitted' rows). #1243 refreshed + merged with these facts.
**CORRECTION (same hour): #1238/#1239/#1240 were ALREADY operator-merged
04:50-04:56Z** — the full recovery set (#1238-#1243) is on main; nothing from
the sprint remains draft. Runtime falsifiers now attach at deploy: preflight
first live-open account read · cap-routing budget_snapshot truth ·
F-CREDIT-SIGN first internal credit close · the operator-gated shadow-row
data correction (#1240 PR body) is now unblocked.

Main `b3cf45b` deployed (Railway SUCCESS 02:03Z). Broker flat $2,067.86 L3/L3.
**Stacked-merge gap PROVEN + recovered**: #1235/#1237 merged into the feature
branch, never main → replacement drafts #1238 (preflight, byte-identical port,
154 tests) + #1239 (cap routing; matrix IDENTICAL 30/30; reporting-only blast
radius re-verified — do not re-find). **F-CREDIT-SIGN CONFIRMED_CURRENT +
fixed in draft #1240** (route-reproduced +1815.96 vs −224.04; canonical #1056
seam; data-correction plan operator-gated in PR). **Rebalance: 4 contract
breaks (filed as 1) fixed in draft #1242**; execute = suggestion-only, no
broker path (verified). **Funnel slice draft #1241** (21 attributed sites +
typed phase exclusion; summary rows honestly NULL by design). Shadow-fleet
migration readiness: READY_SCHEMA_APPLY_ONLY; 6 stale 04-09 'submitted'
paper-order rows block only the ACTIVATION attestation. F-BAN
BLOCKED_OWNER_DECISION; UI BLOCKED_UI_FILE_OWNERSHIP (21 PRs). ⑤/cost/
canonical-position foundations NOT attempted (recorded, queue unchanged).
No merge, no deploy, no DB/broker write, no migration apply, no fleet
activation this run; all new PRs draft.

## 2026-07-16 — ADJUDICATED: Fable 5 options-entry strategy verification · status:reported

Prompt: `docs/review/fable5-options-entry-strategy-verification-prompt-2026-07-16.md`
(rides PR #1232, unmerged at audit time). Results:
`docs/review/fable5-options-entry-strategy-verification-results-2026-07-16.md`.
Model `claude-fable-5`. Code basis `b95d3a3f5766ff3689be9816f0f90d13fc8cfa3c`
== deployed SHA on BE/worker/worker-background (Railway SUCCESS 13:19Z,
verified) — no merged-vs-running gap. Docs basis: same SHA (backlog blob
`5d3157b`, ledger blob `9ce8ffa`). Runtime scope: read-only Alpaca live
(clock/account/config/positions/orders ≈19:57Z: $2,067.86 flat,
approved/effective options level 3), Supabase aggregates, Railway deployment
list. Env VALUES deliberately unread (hygiene: env key NAMES only; never
list_variables with values) → deployed flag values labeled NOT-PROVEN.

**Do not re-derive (exclusion memory):**
- H1 selector pool CONFIRMED exactly {4 verticals, IRON_CONDOR, HOLD/CASH or
  empty-list}; `get_candidates` + IC phase gate have ZERO executing tests;
  `/paper/order/stage`+`/paper/execute` are UI-orphaned arbitrary-ticket
  seams (leg-count-only strategy validation, #1038/#1101 still apply).
- H4 credit-vertical raw EV ≡ $0 CONFIRMED numerically (real module import, 6
  credit/width pairs, exact zeros) AND calibration is a pure multiplier
  (0×mult=0) — a credit vertical can never clear either $15 floor; 0 credit
  suggestions ALL-TIME (DB census). ⑤ already owns this — evidence
  strengthened, NOT re-filed.
- H5: condor EV is env-model-selectable; code default `strict`
  (`options_scanner.py:214`); the ⑤ charter's "CONDOR_EV_MODEL=tail deployed
  / ×0.6 / 0.35" matches NO code default → **pending verification: operator
  env read-back**, then fix whichever text is stale.
- H6/H7: account small tier (broker re-read 07-16); micro↔small cliff is
  DOCUMENTED-INTENTIONAL doctrine with an unreconciled risk-RAISING step
  crossing down $1,000 (2.5× NORMAL / 9× SHOCK — micro bypasses the 5% shock
  cap); boundary tests pin the legacy $38.88 number, production is ~$360 →
  F-TIER-CLIFF-REVIEW (RESEARCH, owner) + F-SELECTOR-ROUTE-TESTS (P2).
- H8: $15 MIN_EDGE binding-by-design at $2k (`execution_cost_exceeds_ev` 744
  in 14d vs `ev_non_positive` 5); the three distinct cost bases at
  scanner/ranker/stage gates are multi-basis phase 2's charter measured live —
  no threshold change recommended, no new filing.
- H9 CONFIRMED: wrapper drops both options-level fields
  (`alpaca_client.py:252-267`); no strategy→level preflight; no permission
  bucket in `_TERMINAL_REJECT_MARKERS` → **F-OPTIONS-LEVEL-PREFLIGHT (P2)**.
- H10 VERIFIED end-to-end: phase = `micro_live` (DB, 2026-04-25) → IC live;
  fail-CLOSED to `alpaca_paper` on read failure; phase-excluded IC is
  indistinguishable from no-candidate in `suggestion_rejections` → extends
  funnel telemetry phase 2 (with `strategy_key` NULL-on-all-rows attribution
  gap, 5,076/5,076 in 14d).
- H11 narrowed: lifecycle migration EXISTS and self-verifies; the fail-open
  to `live_full` is intentional loader/consumer behavior; inert today (5 rows
  all `live_full`); exits lifecycle-independent → **F-LIFECYCLE-TYPED-DEGRADE
  (P2, hard trigger: first non-live_full row)**.
- H12 CONFIRMED phantom feature: no migration defines
  `settings.banned_strategies` (production column = untracked drift; table has
  0 rows); reader degrades to `[]` at logger.debug; zero write surface; full
  enforcement machinery live-routed and permanently inert → **F-BAN-INTEGRITY
  (P2, owner: build-or-remove)**. **RESOLVED-BY-REMOVAL 07-18 (Lane C, branch
  `fix/remove-fban-phantom`; owner decision REMOVE_PHANTOM_FEATURE / packet
  Option B):** whole `banned_strategies` capability deleted from the backend
  (dead read, `[]` degradation, `StrategyPolicy` module, selector/scanner
  threading, `strategy_banned` recheck, design-agent ban branches, dead
  optimizer key); `require_defined_risk` preserved; decision-equivalent
  (2,268-scenario byte-identical proof) + structural guard `test_fban_removal.py`.
  DB drift column LEFT (no migration) → drop belongs to the migration-drift
  allowlist cleanup. Do not re-find. See backlog F-BAN-INTEGRITY entry.
- H13 CONFIRMED: DTE 25–45 enforced at chain-fetch, target 35, one scan/day;
  `midday_scan.py` is the same cycle (not separately scheduled); no 0DTE path
  exists — 0DTE stays unfiled.
- H14: single-leg longs supported at every seam EXCEPT the selector pool;
  repair-first defects: scanner `max_profit=inf` primitive + naked-collateral
  placeholder → **F-SINGLE-LEG-EXPERIMENTAL (RESEARCH, owner-gated)**.
- H15/H16: butterfly/calendar/diagonal/straddle/strangle/CSP/covered-call/
  naked/0DTE all ABSENT end-to-end (verdict table in results §6); covered_call
  exists ONLY in the Compose mock; strangle/naked are half-wired
  (`calculate_ev` raises NotImplementedError). Naked shorts:
  PROHIBIT-UNDEFINED-RISK. None filed.
- H17 CONFIRMED: Compose "New Trade" CTA = `Math.random()` mock, stale
  2025-02-21 example, zero network calls; paper page manages-only; the ONLY UI
  entry action (TradeInbox Stage) rides the same gated `_stage_order_internal`
  — **no UI gate bypass exists** (REJECTED worst case) →
  **F-UI-CAPABILITY-HONESTY (P2)**.
- H18 CONFIRMED: ≥11 naming schemes; registry matches zero persisted strategy
  strings; two behavior-relevant consumers (LossMinimizer debit→naked-long
  misclass, production-wired morning path; risk-cap substring miss → 0.05
  floor fail-TIGHT) → **F-STRAT-ID-CONSUMERS (P2, extends canonical-position
  remainder)**; exit evaluator is safe on unknown names via qty-fallback
  (only a `condor`-alias would miss the IC stop-bypass); `take_profit_limit`
  polluted `trade_suggestions.strategy` historically (12 rows, ended
  2026-04-08).
- H3 PARTIAL: debit verticals structurally suitable; superiority NOT
  evidence-rankable at n=8 broker-live closes (IC 0W/4 −$143 · LCDS 0W/3 −$83
  · LPDS 1W/1 +$48; paper/shadow 94 all-time kept separate).

Disposition counts: 13 CONFIRMED-NEW · 3 CONFIRMED-EXTENDS-EXISTING (H5, H8,
H10) · 1 CONFIRMED-ALREADY-OWNED (H4→⑤) · 1 PARTIAL (H3) · 0 DUPLICATE-rows ·
0 REJECTED-rows · 0 NOT-PROVEN-rows (deployed-env sub-claims NOT-PROVEN inside
rows). Backlog destinations: 07-16 Fable-5 backlog section (5 new P2 + 2
RESEARCH + 2 extends + 1 pending-verification). Priority ordering of "Actual
next priorities": UNCHANGED.

**Pending runtime falsifiers (this entry owns):** operator env read-back
`CONDOR_EV_MODEL`/`CONDOR_TAIL_*`/`MIN_EDGE_AFTER_COSTS`/`MULTI_STRATEGY_EVAL`
(names-only hygiene) · first morning-cycle loss analysis on a losing debit
spread (LossMinimizer blast radius) · first non-live_full lifecycle row
(H11 trigger) · any broker permission-shaped rejection (H9 retry misclass;
do not manufacture).

**No production code, migration, DB/broker write, deploy, flag, gate,
threshold, sizing, strategy activation, entry, exit, or control changed.**
Session worked in an isolated pinned worktree; the operator tree's uncommitted
ledger rewrite (+104/−455 vs origin/main) was preserved untouched — reconcile
at merge (results §13.1).

## 2026-07-16 — POST-CLOSE SPRINT (same-day addendum) · status:reported/drafts-pending

Sprint at `b95d3a3` (== deployed). Draft PRs #1234 (strategy-identity crosswalk;
NOTE: cap-key miss verified 4-WIDE incl. both credit verticals;
`get_strategy_type` verified ZERO production callers — latent-orphan, so the
live delta is cap routing only) · #1235 (options-level preflight) · #1236
(lifecycle typed degrade) · #1231 gained the Row-B fix (cohort-clone writer
omitted ranking_costs/code_sha on live-executable rows; fixed + route-tested;
rebalance writer documented inapplicable; #1231 CI green attempt 2; its
migration 20260716155023 APPLIED ~15:51Z — never reapply). CLOSED pending
verification: deployed CONDOR_EV_MODEL=tail / 0.35 / 0.6 on both workers —
the ⑤ charter text was correct, code defaults are the divergent side.
Runtime-PROVEN naturally 07-16: decision_runs.git_sha full-SHA ×3 matching
deployed; first leg-aware ranking_costs row 16:00:32Z. #1228/#1229 = MERGED
code; pending falsifiers: signed tape reader never run (by design) ·
broker-closed weekday (2026-09-07). F-MIDDAY = shipped-code/runtime-pending
(no natural failed read yet). Lane 4 UI honesty BLOCKED_UI_FILE_OWNERSHIP
(Palette #1093 owns compose; ~12 PRs contest TradeInbox). F-BAN-INTEGRITY
packet delivered (rec: Option B remove) — operator decision open. Small
accepted seam: /scout/weekly scans clientless → legacy lifecycle default
(advisory-only). No broker/DB/deploy/control change this sprint; all PRs
draft.

**07-17 INTEGRATION PASS (main still `b95d3a3`; all drafts):** #1234 split →
identity-core-only at `824bdca` (35 tests) + NEW stacked owner-gated #1237
`fix/strategy-risk-cap-routing` at `39d9bc1` (67 tests; **caller trace: cap
reroute is REPORTING-ONLY today** — `strategy_allocation`→`budget_snapshot`
zero readers, optimizer Literal-immune; matrix = potential deltas). #1235
merged-onto identity core, base retargeted, duplicate normalization removed,
60s-TTL account-read cache. #1231 finalized: schema/history/receipt AGREEMENT
(no drift block; `vrp_ranking` also covered by tracked `20260624002451`), 87
tests, never-reapply stated. #1236 verified independent (37 tests). UI lane
BLOCKED_UI_FILE_OWNERSHIP (41 open Palette/Jules PRs own the surfaces). F-BAN
packet: `docs/review/f-ban-integrity-decision-packet-2026-07-16.md` (rec:
Option B) — operator decision open. **Local-ledger reconciliation resolved
without a provenance block**: local tree = f34d5cd base + the 07-15 nightly
entry (loop provenance clear); that section + `audit/reports/2026-07-15.md`
swept INTO this PR — carrying ⚠ **F-CREDIT-SIGN (HIGH, status:reported at
`f34d5cd`; adjudicate at current SHA before building — newer SHAs unread by
the nightly)**; local 07-14 report copy is byte-identical to the committed
one (redundant; left untouched). NEW pre-existing flag: `/rebalance/execute`
+ `/rebalance/preview` → `compute()` stale signature = guaranteed TypeError,
dead on main. Recommended merge order (report-only): #1231 → #1236 → #1234 →
#1235 (retarget to main post-#1234) → owner-gated #1237 → #1233 last. No
merge, no deploy, no DB/broker write, no control change in this pass.

## 2026-07-16 — OVERNIGHT BACKLOG LANES · status:merged-foundation/draft

Grounded GitHub main at `0e3e54f0821f2114b3d1b10074f15686f5e555c5`.

- #1224 merged the post-merge standing and fleet doctrine.
- #1225 merged the **dormant** `small_tier_v1` schema/pure contract. This is
  not activation: migration unapplied; zero fleet/account/portfolio/policy
  rows provisioned; no runtime caller; legacy-terminal boundary unproven.
- #1226 merged test-only rolling calibration-floor stability.
- #1227 merged read-only calibration-report fetch truth; multiplier behavior
  is unchanged.
- #1228 is DRAFT: persisted decision-tape aggregate hash/count reader plus a
  signed operator-triggered job path. It reads zero live data and is
  deliberately unscheduled. Full deterministic replay remains open.
- #1229 is DRAFT: broker-clock holiday/half-day truth is threaded through
  ops-health `data_stale` and RTH job-liveness gates. Detection-only; no
  cadence/control change.

Neither draft is shipped, runtime-proven, or authorized for merge by this
documentation record. No migration, fleet activation, policy registration,
schedule, flag, threshold, stop, gate, broker write, or DB write occurred.

## 2026-07-16 — POST-MERGE RECONCILIATION · status:shipped-code/runtime-pending

Grounded repository truth through `main=b6496b60d46d137806a80577581d19a4b06eec8c`.
The following closures supersede stale `status:reported` and queue language
below; historical entries remain exclusion memory.

- #1203 shipped F-A9-5 truthful Policy-Lab reason serialization.
- #1204 shipped the canonical position/payoff model; #1214 wired exact
  defined-risk max loss into the risk envelope. Only that slice is closed.
- Current main's two midday live-position reads raise a typed unavailable-state
  error rather than returning a false-flat `[]`; handler job truth consumes the
  failure. Runtime exception injection is pending.
- #1215 shipped strict Policy-Lab capital reads and partial/failure propagation;
  it removed the nominal $100k code fallback. This does **not** make existing
  $100k shadow portfolio rows comparable to the ~$2k live book.
- #1216 shipped the model-version/deploy-version provenance split.
- Current main's decision writer resolves a full SHA from explicit input,
  `GIT_SHA`, or `RAILWAY_GIT_COMMIT_SHA`; the first natural production row
  remains the runtime falsifier.
- #1218 shipped leg × quantity × entry/exit commission in canonical ranking.
  Remaining scanner/gate/slippage/realized cost-basis work stays open.
- #1219 shipped honest funnel denominators; per-selected-item terminal
  disposition remains open.
- #1220 shipped regular-session-close-aware thesis expiry scoring. It changes
  evidence timing only, not trading exits.
- #1222 shipped the durable doctrine for those three contracts.
- #1223 shipped the restored legacy #775 PoP suite; tests only.

### Operator authorization — prospective small_tier_v1 fleet

The operator authorized a prospective fleet of exactly 50 isolated virtual
accounts, each with $2,000 initial net liquidation and $2,000 cash. The
$100,000 sum is administrative only and can never enter sizing, allocation, or
cross-account loss recovery. Only uniquely pre-registered policy slots may
activate; all other slots remain inactive. Existing $100k portfolios and their
history remain `legacy_100k` and are never rewritten. Activation requires all
legacy positions and working orders to be terminal plus one explicit
timezone-aware effective timestamp. All parallel evaluations share the source
suggestion UUID as immutable `decision_event_id`; evidence n is distinct
decision events, never account-row count. No live control, threshold, stop,
gate, strategy, universe, or cadence change was authorized.

Implementation status (historical at this entry; superseded by the overnight
entry above):

- #1225 **DRAFT / CI GREEN** — dormant schema and side-effect-free validation
  only. Migration unapplied; no fleet/account/portfolio/cohort rows created; no
  runtime caller or activation path.
- #1226 **DRAFT / CI GREEN** — test-only rolling calibration-floor fixture.
- #1227 **DRAFT** — report-only typed fetch-failure semantics; live multiplier
  behavior untouched.
- E19-2B stays gated until the fleet is actually activated at a proven clean
  legacy boundary. Authorization alone is not runtime parity.

### Practical effect on the next trading session

- Exact payoff max loss can change risk-envelope arithmetic and can fail a
  malformed/unbounded defined-risk candidate closed.
- Leg-aware commissions can lower the rank/RAeV of four-leg structures relative
  to two-leg structures and can reject a marginal candidate that previously
  cleared on the universal $1.30 estimate. No threshold changed.
- Position-state read failures cannot masquerade as a flat live book.
- Provenance and funnel changes make the evidence attributable; they do not
  select or submit a trade by themselves.
- Expiry-day thesis scoring occurs post-close and cannot change an intraday
  entry or exit.

**Runtime boundary:** deployment/H8, first natural max-loss decision, first
natural leg-aware cost decision, first resolved decision-tape SHA, and next
post-close thesis run are NOT_PROVEN_RUNTIME in this GitHub-only lane. No
broker, DB, Railway, environment, flag, threshold, stop, or schedule write was
performed.

### Exclusion memory / do not reopen as fresh findings

Do not refile the shipped slices above. Reopen only on a named falsifier or on
the explicitly listed remainder: shadow-capital parity, terminal-distribution
source, cost phase 2, canonical-position greeks/stress/reconciliation, funnel
terminal dispositions, or durable cross-job identity.


## 2026-07-15 — ADJUDICATED: external full audit v1.5 · status:reported

Executed the v1.5 BRIEF (`docs/review/external-full-audit-v1.5-current.md`) — it was BRIEF_ONLY (no completed
v1.5 results existed). Full completed report: **`docs/review/external-full-audit-v1.5-results-2026-07-15.md`**.
Audited production code at the immutable baseline **`bef2cdd`** (main moved 623044d→d18dd52 during the run =
**docs-only** #1207+#1208, zero code). E1–E20 + W1–W5 + A1–A10 (Pass 1/2/3) + instrument-integrity + free look
all completed; runtime adjudicated read-only. **Audit-maturity = `INFERRED design-maturity score 60/100`
(arithmetic-reproducible reviewer-weighted scorecard in results §12c: weights sum 100 and earned points sum 60;
the judgment-to-points method is not empirically calibrated; capped below the 85 maturity-ladder rung by the open
live-entry fail-open, incoherent EV/cost bases, missing replay reader, incomplete observe-window durability, and
6 unrun runtime checks); NOT a verified profitability/reliability/efficiency measurement, and NOT the earlier
unsupported 87/100 (the arithmetic independently yields 60).**

**RETAINED findings (exclusion memory — do not re-derive; build queue in the backlog v1.5 section):**
- **F-MIDDAY-POSITION-READ-FAILOPEN — CONFIRMED, 2 sites, live-entry safety (HIGH).** `except → return []`:
  Site A `workflow_orchestrator.py:_fetch_positions:2240-2270` (bare `print`, defeats `position_scope`'s
  loud-by-contract raise → micro-tier gate bypass); Site B `paper_autopilot_service.py:_get_open_positions_for_risk_check:1328-1343`
  (alerts, but envelopes pass green-on-vacuum). Un-hardened siblings of the 3 reads #1195 fixed. VERIFIED-CODE.
  Site A only source-string tested. **Causality NOT inevitable** — later same-symbol dedup + the *enabled*
  utilization gate can independently stop an entry; the dangerous case is a transient/selective/false-empty read
  followed by successful staging. P1-safety; **escalate to P0-before-next-entry if the utilization gate is
  OFF/unproven, any broker-live position is open, or multi-position/qty scaling is enabled.** Acceptance: route
  tests proving zero `submit_and_track` for BOTH a portfolio-ID and a position-query exception; a legitimate empty
  stays healthy.
- **A6-2 shadow-capital parity — HIGH, THE FIRST OPERATOR DECISION.** All three policy-lab portfolios `net_liq=$100,000`
  (incl. the live-eligible champion) vs the ~$2,067.86 live book (**~48× capital ratio**, basis=n/a dated account
  snapshots, unit=account-equity USD; ratio dimensionless). Raw-dollar
  P&L/capacity/feasibility/sizing/selected-samples are NOT live-tier comparable; promotion is *partially* normalized
  where enabled; **thesis hit/miss LABELS are NOT notional-scaled** (capital changes *which* trades enter the sample);
  `live_eligible`=routing ≠ broker execution. The `or 100000` literal is INERT (stored net_liq IS $100k) — removing
  it is a SEPARATE fail-closed code item, NOT the fix. **Operator decision: preserve the $100k epoch as non-live-tier
  evidence; at a clean boundary (no open shadow positions/orders) launch a versioned live-tier observe-only cohort on
  one shared broker-grounded capital snapshot (persist capital_basis/source/as-of/epoch); freeze cross-epoch promotion
  until a fresh min sample; NEVER rewrite historical rows as if at $2k.** VERIFIED-CODE + ATTESTED-RUNTIME. Strengthens
  F-SHADOW-CAPITAL-PARITY.
- **A6-3 condor-EV mis-rank — HIGH, live.** Three incoherent per-structure-contract dollar-EV constructions
  (credit≡$0 raw / debit breakeven-delta raw / condor delta-tail probability plus fixed-severity raw heuristic)
  all write `suggestion["ev"]`, jointly sorted by one structure-agnostic ranker; cross-structure rank flips on a
  severity constant before any $-gate. EXTENDS-E12/⑤.
- **A7-1 Phase-3 live-close accrual STALLED — HIGH.** 8 POST-EPOCH live closes (9 all-time incl. the pre-epoch
  NFLX 06-08), last 2026-07-08, 0 in the 7 days to pin; the ~10–15-fill gate is entry-rate-bound
  (INDETERMINATE/PAUSED), not close-instrumentation-bound. (Denominators kept separate — see results §1a.)
- **MED:** A2-1 watchdog writes terminal-cancelled on an unconfirmed cancel → double-entry (loud via ghost sweep;
  EXTENDS-P0-A) · A4-1/A9-2 git_sha reads `GIT_SHA` not `RAILWAY_GIT_COMMIT_SHA`, 12/12 'unknown' (= GIT-SHA-
  DECISION-PROVENANCE, one-liner) · A4-2 replay input/features hashes have a durable sink but ZERO reader (NEW) ·
  A7-2 exit-basis stamp lands on only 2/6 closes, all 3 recent fill-only (resting-GTC bypass; EXTENDS-Phase-3) ·
  A8-1 F-A9-5 confirmed: 56 `policy_decisions` rows carry a dollar-`ev` vs score-threshold lie; stored `ev` is
  the served value (historical basis unknown; calibrated at the attested successful-calibration runtime, with
  `ev_raw` separate), and `rank_at_decision` is an ordinal (EXTENDS-F-A9-5) · **A9-1 5th
  typed-column-lie F-A9-6:** `model_version` = `APP_VERSION` deploy string presented as model identity (NEW) ·
  **A9-3 F-A9-8:** champion/legacy fork path never populates `fork_errors` → champion clone/tag failure returns
  job-green (NEW) · A10-1 `is_us_market_hours` holiday-blind → Labor Day 2026-09-07 false HIGHs (EXTENDS-area10,
  hard trigger < 09-07) · E2 roundtrip qty-fix LIVE-INERT (default OFF) · observe-window durability: four of five
  windows (W1/W2/W3/W5) lack complete durable evidence — W1/W2 strictly logs-only, W3 partially durable (cap-breach
  alarm subset → risk_alerts), W4 semi-durable (count → job_runs.result), W5 absent/unstarted. Backlog interaction:
  **EXTENDS the existing split: F-WINDOW-1a EMISSION is CLOSED at `1386834`/#1198; F-WINDOW-1b COVERAGE+JOINABILITY remains OPEN; not a new finding identifier.**
- **LOW/NOTE:** A1-1 replay runner input-blocked (capital/OBP/book/ev_raw uncaptured; EXTENDS-E19-2B) · A5-2 no
  decision_runs origin column (**EXTENDS the existing `suggestions_open untraced extra runs` item and replay runner;
  not a new standalone filing**) · A3-1 stop-vs-thesis signal readable but unconsumed (NEW) ·
  A3-2 DTE bucket inert · A3-3 no apply-time sample re-check · A9-4 freshness alert lacks no-activity guard for
  learning/rejection/calibration tables · OPTIMIZER_V4/ALLOCATION_V4 dead-capability cluster (free look; EXTENDS
  FORECAST_V4 #1126 inventory) · A2-2 max_loss_total is quantity-coherent, while signed-leg/payoff/multiplier
  semantics remain a retained **EXTENDS-canonical-position-P1** gap.

**Register governance:** results §15 is the version of record for retained/conditional finding detail. Every retained
finding in this ledger/backlog matrix maps to one 12-field register block, or carries an explicit settled, rejected,
runtime-only, or dormant disposition. The current pin contains 22 unique register blocks.

**REJECTED (do NOT rediscover):**
- **Internal-fill close-price sign — NOT PROVEN as a defect.** `paper_exit_evaluator._select_internal_fill_price`
  is shadow-ONLY (P0-A guard makes it unreachable for a live close), stores the signed value consistent with the
  system-wide signed `avg_fill_price` convention (`paper_endpoints.py:1908`), and is not read for realized-P&L
  learning (`paper_learning_ingest` uses `realized_pl`). No positive-expecting consumer exists. Realized-P&L sign
  is owned by #1017/#1079.

**SETTLED / PASS (verified at bef2cdd; do not re-open):** E1,E3,E4,E5,E7,E9,E10,E11,E13,E14,E15,E16,E17,E18,E19,E20
PASS; A6-1, A8-2, A8-3 PASS; A4-3 (no other non-JSON type crosses supabase-py's JSON layer — negative result);
F-WINDOW-1 = inert identifier drift (prefix-disambiguated), not a new collision. E6 needs_manual_review is safe
(code = critical hold, tracked, not double-fired) — the "routed-success" framing was inverted, not the code.

## 2026-07-15 (Wed, post-close) — UNIVERSE-CENSUS ADJUDICATION (read-only; corrects the same-day 18:38Z status) · status:reported

STEP-0: host `20:59:06Z` ≈ DB `now()` `20:59:15Z` ≈ broker `16:59:17 ET` — agree; market CLOSED.
Deployed SHA `623044d` (docs-only over `bef2cdd`; the 07-15 falsifier code is `bef2cdd`-identical).
Read-only census of the 78-symbol production universe + a live Aug-21 chain snapshot (19:29–19:33Z).
Verified findings (exclusion memory — do not re-derive):

1. **78 active symbols; ALL 78 SELECTED every 2026-07-15 cycle** (`universe_selection_log`
   09:30Z/14:32Z/16:00Z: total_active=78, selected=78, dropped=0). Full breadth, no prune.
2. **job-result `universe_size=10` = scanner-EMITTED candidate count (6 IC + 4 debit), NOT ten
   symbols scanned** (`[APPLY_ORDER_SHADOW] n=10`, mislabeled).
3. **`symbols_processed=98` vs `selected=78` remains NOT_PROVEN** (20-symbol gap unreconciled).
4. **BKNG WAS scanned and RANKED** (#3; raw 42.1/47.4, calib 13.5/18.4); its actual **$20-wide
   long-call debit spread (C175/C195 Aug-21)** was first excluded at **SIZING** — 1-contract risk
   **$855/$885 > available budget $703/$469** → contracts=0 (both cycles). Sizing drops are
   stdout-only (no `suggestion_rejections` row) — why the 18:38Z pass mis-called it NOT_IN_RUN.
5. **BKNG ticker suitability is DISTINCT from structure suitability** — the symbol is
   universe-suitable (liquid, OI-rich puts); the $20-wide debit STRUCTURE failed the budget.
   **Do NOT record "BKNG was missed."**
6. **A hypothetical $5-wide BKNG put spread fits the capital budget ($412 max loss) — this does NOT
   prove positive EV or entry suitability.** Earnings (07-27) and true EV remain unresolved.
7. **$62.04 = q15 mark-based FORCE-CLOSE threshold on open-position UPL** (`risk_envelope.py:444`,
   `envelope="loss_per_symbol"`, iterates open positions' `unrealized_pl` and force-closes at
   `unrealized < -$62.04`). **NOT an entry max-loss gate** — no production entry code rejects
   `max_loss_total > $62.04` (distinct from the entry sizing param `max_risk_pct_per_trade`).
   Reclassified as "defined payoff exceeds the mark-stop threshold" → Phase-3 exit-basis question;
   no stop change recommended.
8. **The census `PoP×credit − (1−PoP)×max_loss` (PoP = 1−|Δ_short|) is a BINARY MAX-LOSS LOWER
   BOUND, not true spread EV** — it ignores the partial-payoff interval between strikes and uses
   short-delta as a probability proxy. "Net economics negative" is a conservative lower bound,
   NOT proven-negative.
9. **True credit-spread EV remains NOT_PROVEN pending queue-⑤** (the payoff-circular ≡$0 class; no
   independent terminal distribution integrated).
10. **Two-leg verticals have PROVEN lower fees (fee-only $2.60 vs $5.20) + fewer dead-leg failure
    modes than four-leg ICs** (BKNG IC unbuildable — C205/C215 dark wings, #1038 class); economic/EV
    superiority is **NOT PROVEN**.
11. **Configured $2.50/$5 widths are large for the ~$2,067.86 account; $1 widths scale risk better**
    (~$75 vs ~$440 max loss) **but may worsen fee/credit economics. No live width change is justified.**
12. **No ticker activation/deactivation is justified from one snapshot.** `option_liquidity_score` is
    40 days stale (67/78 stamped 2026-06-05; all 10 zero-scores in that batch) → zero ≠ current
    illiquidity; `get_option_contracts` OI is deep on the ETFs (SPY 34,265; TLT 65,864).

Preserved as a SEPARATE VERIFIED fact: the engine executed **0** today — QQQ IC roundtrip-rejected
(`net −$5.03`, #1101) and SOFI persisted `edge_below_minimum` — real and independent of the EV
mislabel. XSP: broker-listed/tradable (European, cash-settled) but the feed returns null OI/close →
data-sparse, and not in the scanner universe.

## 2026-07-15 (Wed 00:00 CT) — NIGHTLY AUDIT (v5.5, scheduled) — report audit/reports/2026-07-15.md · **1 NEW FINDING (HIGH)**

STEP-0: DB `now()` 05:00:28Z = Wed 00:00:28 CT (dow=3) = broker 01:00:27 ET, agree to the second,
market CLOSED. Wednesday ⇒ NIGHTLY. **Run NOT broker-blind** (interactive; 3 broker calls).
**⚠ H8 pin — MOVED:** run-END running SHA = **`bef2cdd`** (SUCCESS 07-14 23:05:33Z), NOT `f34d5cd`.
Two Tuesday post-close merges (`967071…` 22:28Z REMOVED/superseded; `bef2cdd` 23:05Z live). Local
checkout = `f34d5cd`, no fetch possible (no Bash tool). **The audited RTH window ran entirely under
`f34d5cd` = the SHA read → diagnosis correctly pinned. `bef2cdd` content UNREAD — verify whether it
already touches the F-CREDIT-SIGN seam BEFORE building.** Budget: ~17 SQL (over ≤12, declared) · 3
broker · 1 Railway · 0 subagents.

### 🔴 NEW — status:reported — **[F-CREDIT-SIGN, A2, HIGH] Internal-fill credit-close realized-P&L sign REGRESSION (#1056 re-opened via #1017)**

**WHAT.** Internal-fill closes of CREDIT structures double-negate the signed executable mark →
`realized_pl` wrong in sign AND magnitude. Deterministic error = **2 × |close mark| × qty × 100**.
**This is a REGRESSION of a ledgered `status:shipped` fix** (#1056, 06-11 — see the 06-11 incident-arc
section below, which records the identical mechanism and signature).

**WHERE (verified at `f34d5cd`, the SHA that produced the evidence):**
- `paper_exit_evaluator.py:2384` — `_select_internal_fill_price(...)` **overwrites** exit_price with
  the SIGNED `achievable_close`; `:717` returns `float(ach)` with **no `abs()`**.
- `paper_exit_evaluator.py:334` — `_close_limit_and_direction` DOES return `abs(exit_price)` (#1056's
  fix) but governs the **broker limit only**; the internal-fill path never calls it. **#1017 (06-12)
  re-introduced the signed value ONE DAY after #1056 (06-11) removed it.** The `:2378-2380` comment
  ("Sign convention unchanged — achievable_close comes from the same finalize_mark stack as
  current_mark") is the reasoning error: correct for a *mark*, wrong for a *fill price*.
- Signed value flows to FOUR consumers: `:2443` avg_fill_price · `:2453-2454` cash_delta · `:2470`
  ledger emit_fill · `:2506-2511` synth leg → `close_math.compute_realized_pl:204-212`, whose contract
  derives direction from the **leg action sign** and requires a **positive** `filled_avg_price`.

**IMPACT (reproduces to the cent).** QQQ `c1c9ad04` (6-lot IRON_CONDOR, shadow `c8a3a3b0`, 07-14
16:30:22Z, stop_loss_hit): truth = credit 795.96 − buyback 1,020.00 = **−$224.04** (= persisted
`unrealized_pl_corroborated` = the force_close alert payload). Booked **+$1,815.96**. Overstatement
**$2,040.00 = 2×1.70×600** ✓. Cash ledger hit identically → **$2,040 shadow cash_balance error**
(same signature as 06-11's "credited +1302 instead of debiting 1302"). Historical: AMD `75204e83`
(04-10) realized +1,202.00 vs unrealized −242.00 (err 2×1.805×400=1,444 ✓); the 03-13→03-18
pre-cohort condor batch shows the same signature (META `2f316f4a` Δ=753=2×0.41833×900 ✓).
**CONTAMINATION INGESTED:** `learning_trade_outcomes_v3` holds QQQ `pnl_realized=1815.96` vs
`pnl_predicted=46.394` → fictional **+$1,769.57 alpha** on QQQ/IRON_CONDOR. **06-11's twin was
corrected BEFORE the ingest ("zero contamination"); unattended, 07-14 was not caught.**

**RISK.** **Shadow-only today — by the guard, not by luck.** All 3 Tuesday positions shadow; broker
flat ($2,067.86, positions `[]`); `is_paper=true` holds the #1076 live-calibration wall; live brake is
live-scoped. **E6/P0-A (`:2331-2375`, shipped 07-10) structurally forbids a live close from filling
internally — it is the ONLY thing between this bug and a live phantom realized.** Live blast radius
= zero today; shadow/learning/policy-lab-promotion radius = real (`c8a3a3b0` carries the fiction).

**HOW.** `abs()` the `_select_internal_fill_price` return (`:717`), or route the internal fill through
`_close_limit_and_direction` so ONE function owns unsigned-magnitude + structural-direction for both
limit and fill. **Regression test must DRIVE `_close_position` end-to-end** on a credit structure with
a signed corroborated mark and assert `realized_pl == −224.04` — inject at the deepest callee, assert
at the top. Data correction (operator-gated, 06-11 precedent): `c1c9ad04.realized_pl` +1815.96 →
−224.04 · `ed31cc5f` cash_balance −$2,040 · **and re-derive the ingested learning row** (unlike 06-11,
the ingest already ran). **Post-20:00Z only** (touches the live close path); no rush-fix case (P0-A).

**⚠ TEST-COSTUME (doctrine's own named class, caught live).** `tests/test_csx_close_sign_convention.py:103-111`
pins #1056 via `self.src.find("def _close_limit_and_direction")` + `assertIn` **source-string**
assertions — green for 34 days while the active internal-fill route walks past the function. Exactly
the #1126-costume-in-test-form CLAUDE.md warns about: it verified a *string*, not a *behavior*.

**CONFIDENCE: HIGH** — arithmetic reproduces on 2 independent rows 3 months apart + a 6-row historical
batch; path read end-to-end; ledger records the identical prior incident; DB/alert/broker all agree.

### Adjudications & STATE movers (NOT findings — cite, don't re-find)

- **[A8 SETTLED TRIGGER FIRED → adjudicated DESIGNED, not a bug]** SOFI cleared the roundtrip gate and
  executed 07-14 — **in shadow only**. Cause = **D② shadow-raw-EV (2026-07-12)**, `fork.py:243-251`
  `_is_shadow_raw_ev_enabled()`: shadow clones score on RAW `source.ev_raw`; `SHADOW_RAW_EV_ENABLED`
  default-ON, explicit-falsy = revert lever. Evidence: live `933e20b4` ev_raw 48.5171 → ev 24.2586 →
  **BLOCKED** `ev_below_roundtrip_cost`; forks `c4555db6`/`0134876f` (+4s) ev 48.5171 / ev_raw NULL →
  **executed**. **The live NO was correct; the gate held on live.** (My initial read of NULL `ev_raw`
  as a fork calibration-bypass bug was OVERTURNED by reading `fork.py` — recorded per verify-before-
  asserting.) **D② is the mover that ends the "zero-entry" regime for shadows.**
- **⚠ CONFLICT (carry this):** D②'s written rationale (`fork.py:246-249`) is *"the honest cross-cohort
  comparison lives at OUTCOMES … which are basis-independent."* **F-CREDIT-SIGN falsifies that premise
  asymmetrically** — it corrupts credit + internal-fill closes only, i.e. **only the shadow cohorts**
  (live outcomes come from the broker reconciler). The cohorts D② lets trade freely are exactly the
  ones whose outcome ledger is unreliable. Only Gate-2 volume-freeze (MIN_TRADE_COUNT=10/7d) makes this
  theoretical. **Additive to gap-3b — a DIFFERENT mechanism (arithmetic, not fill-realism).**
- **E6/P0-A broker-ack-close invariant = SHIPPED** (`paper_exit_evaluator.py:2331-2375`, marker
  2026-07-10; fail-CLOSED on unknown routing `:2345`). **Move KNOWN-PENDING → shipped in v5.6 STATE.**
- **P0-B book-scaling readiness = SHIPPED.** `paper_positions.cost_basis_total` + `max_loss_total` now
  EXIST and are POPULATED (all 3 Tuesday rows; NULL on every pre-07-14 row). `risk_basis_shadow.py`,
  `bucket_control.py`, `portfolio_allocator.py:132-157` present. **STATE's "paper_positions has no
  cost_basis/max_loss columns → book-blind" is FACTUALLY STALE.**
- Breaker: `entries_paused=false`, fingerprint intact (3 ids, 07-08 21:20Z). **2 losing closes landed
  and did NOT trip it — CORRECT** (both shadow; breaker counts LIVE round-trips only).
- Pool **8/8 (1W/7L) UNCHANGED**; close-fill-gap **3/10–15 UNCHANGED** (Tuesday's closes were shadow).
- Broker flat 3rd night: equity=cash=OBP=$2,067.86; `balance_asof` advanced 07-10 → **07-13**.
- SOFI `7b39c908` **remains OPEN** (17 lots, corroborated UPL −$364.99) — only open position anywhere.
- A10 flag inventory: `SHADOW_RAW_EV_ENABLED` (`fork.py:252`) is read **per-call**, not module-scope →
  **no recycle needed**; correctly EXCLUDED from the import-time inventory (noted so it isn't re-litigated).
- A11 nightly: proposes a **Regression-Sentinel lens** (re-assert each `status:shipped` ledger
  invariant against live data) — ranked ABOVE the queued Security lens; tonight's finding surfaced only
  by accident (a force_close alert), which no charter guarantees. Owner-gated.
- **Retirement counters:** A2 → **0 (reset, HIGH finding)**; A8 → **0 (reset, trigger fired)**. A1/A3/
  A6/A10 at 7. **The 07-14 "quiet-regime artifact" read is now CONFIRMED**: the moment the book moved,
  A2 produced a HIGH finding in one window. **No retirement proposal warranted.**

PENDING VERIFICATIONS carried into 07-15: (1) **read `bef2cdd` + `967071…` — do they touch the
F-CREDIT-SIGN seam?** (2) F-REPLAY-FK first exercise — did 07-14 13:00Z produce `data_blobs>0` +
`tape_integrity='complete'`? (NOT checked this run — budget spent on the HIGH finding; carry forward.)
(3) #1198 first RTH info-line proof. (4) native `[CLOSE_FILL_GAP]` + post-#1137 `last_marked_at` on a
LIVE close — still gated (0 live closes). (5) first thesis fill with populated `price_basis`.

## 2026-07-14 (Tue ~19:2x CT, post-close) — POST-MERGE RECONCILIATION: ④ #1201 + ③ #1200 SHIPPED · QUEUE ①–④ CLOSED · ★ #1199 FALSIFIER PASSED · ★ NEW GIT-SHA-DECISION-PROVENANCE · status:shipped

STEP-0: host `2026-07-15T00:15:42Z` = DB `now()` `00:15:44Z` = broker `2026-07-14 20:15:44 ET`
— all three agree within ~2s; market CLOSED (next open 07-15 09:30 ET). **Premise note (not a
correction): the invoking header's "2026-07-14" is the ET/CT session date; the UTC date is already
07-15.** All UTC timestamps below are clock-grounded; "07-14 RTH" = the session that closed 20:00Z.
Docs-only lane, isolated worktree from `bef2cdd`; no merge/deploy/migration/flag/env/schedule/DB/
broker change. Deployed SHA `bef2cdd` PRESERVED for the 07-15 natural falsifiers.

**H8 PIN (both PRs, verified against Railway + `origin/main`, not local):** `origin/main` =
`bef2cdd60edbee8642fa043192fd982d4bfe4436`. Railway worker: `bef2cdd` **SUCCESS 2026-07-14
23:05:33Z = the ONLY non-REMOVED deployment**.

**④ F-A3-4 #1201 — squash `9670712`, merged 22:28:02Z. ⚠ DEPLOYED *WITHIN* `bef2cdd`, NOT AT ITS
OWN SHA.** Its own deployment (`9670712`, 23:28:05Z record 22:28:05Z) is **REMOVED** — superseded
37 minutes later by #1200's merge. `9670712` IS an ancestor of `bef2cdd` (verified
`git merge-base --is-ancestor`), so the code is live; but **no container ever ran `9670712` to a
falsifier.** Consequence for future audits: **verify #1201 behavior at `bef2cdd` BY CONTENT — a
deployment-SHA search for `9670712` returns REMOVED and reads as "never shipped" (H8 squash-merge
class).**
- D1 validator fetch parity: `prequential_validator.fetch_live_outcomes` now delegates to the ONE
  shared production cohort contract (`CalibrationService.fetch_eligible_outcomes` — rolling window ·
  `CORRUPTED_PNL_FLOOR` · `CALIBRATION_EV_EPOCH` · `CALIBRATION_TRAIN_LIVE_ONLY`). Fetch is
  `Optional`: `None` = failure → `status=error/fetch_failed`, `[]` = legit-empty →
  `insufficient_data`. Closes the []-sentinel disease (E8-3 class link) at this seam.
- D3 thesis headline: `population_by_execution_mode` + `population_by_routing_x_execution`;
  `pooled_all_modes` is the ONLY pooled label; `routing_mode='live_eligible'` is **never** called
  "live"; unknown mode isolated, never silently live.
- CENSUS PRESERVED (do not re-derive): `pre_epoch=0` → **NIL current numerical impact; structural
  only.** This does NOT weaken with time — it is a census as-of the v1.4 adjudication.

**③ E19-2A #1200 — squash `bef2cdd`, merged 23:05:30Z, deployed 23:05:33Z SUCCESS. LIVE.**

**★ NARROW CLAIM — PRESERVE VERBATIM; DO NOT LET IT WIDEN BY RETELLING.** #1200 delivers
**`raw_candidate_eligibility_only`** and nothing else. It is **NOT** selection · **NOT** execution ·
**NOT** fill simulation · **NOT** P&L evidence · **NOT** thesis evidence · **NOT** capacity/slot
accounting (`max_positions_open` / `max_suggestions_per_day`) · **NOT** joint normal-vs-prerejection
ranking · **NOT** entry-rate evidence. Every clone AND both verdict types carry the full contract:
`observation_scope='raw_candidate_eligibility_only'`, `decision_semantics=
'raw_candidate_eligibility'`, `selected_for_entry=false`, `capacity_evaluated=false`,
`joint_rank_evaluated=false`, `execution_state='not_executed'`, `execution_intent=
'internal_paper_only'`, `routing_intent='shadow_only'`. Accepted verdict
`reason_codes=['raw_candidate_eligible_observation']` with `rank_at_decision=NULL` **because no
ranking occurred**. `simulated_fill` is a sizing/TCM snapshot, **NOT an execution or fill**. Source
boundary: `edge_below_minimum` ONLY — `marketdata_quality_gate` (stale/dark/unpriceable) and all
scanner-level rejects are NEVER resurrected (H9: a dark leg stays unmarkable, §7 area8).
- **D② un-mute is STILL PARTIAL — `bef2cdd` does NOT stamp "the FULL experiment."** The 07-12
  backlog line ("`9a540ce` stamps the FLAG, ③'s SHA stamps the FULL experiment") is **superseded**:
  ③ shipped as **E19-2A (eligibility observation)**, not the full selector. The FULL experiment
  stamp now waits on **E19-2B** (below). Entry-rate evidence remains excluded until E19-2B.

**★ E19-2B (NEW, SPLIT OUT — the full counterfactual selector) — the separate dependency.**
#1200 explicitly scopes it out. E19-2B = joint normal-vs-prerejection ranking + capacity/slot
accounting + selection semantics, i.e. everything required before ANY entry-rate / conversion /
P&L claim can attach to the prerejection fork. **Blocks: the D② full un-mute.** Depends on
F-POLICY-CAPITAL-FALLBACK + F-SHADOW-CAPITAL-PARITY (a counterfactual selector that sizes against
a fabricated capital basis produces fabricated selections). → backlog P1.

**PENDING FALSIFIERS (the recoverable runbook — all three are 07-15 events; NOT verifiable tonight):**
- **#1200 · first post-merge midday cycle with a calibrated-rejected candidate.** EXPECT: a
  `shadow_prerejection_fork` clone + verdict carrying the per-contract unit contract, **identical
  `raev1` across cohort sizes**, `coverage_complete=true`, and a **byte-identical champion set**.
  **⚠ NO QUALIFYING CANDIDATE = INCONCLUSIVE — not PASS, not FAIL.** Base rate (DB, 5d):
  `edge_below_minimum` = 1 (07-14) · 2 (07-13) · 1 (07-10) · 0 (07-11/07-12 weekend) → **~1–2 per
  trading day; likely but NOT guaranteed on 07-15.** Do not record a quiet day as a PASS. Any
  champion-set deviation, or any infrastructure fault surfacing green = **REVERT**.
- **#1201 · `calibration_update`** — schedule 05:00 CT = **10:00Z**; last run 07-14 10:00:02Z ran on
  `f34d5cd` (**pre-#1201**). **First exercise = 07-15 10:00Z.** EXPECT: the shared
  `fetch_eligible_outcomes` contract yields the SAME eligible rows production calibration already
  used (pre_epoch=0 ⇒ no numerical move); a fetch failure must surface `error/fetch_failed`, never
  a green `insufficient_data`.
- **#1201 · `thesis_tracker`** — schedule **17:00 CT = 22:00Z, DAILY** (single run — NOT hourly;
  the "hourly arm" in prior entries is the watchdog's expectation, not the schedule); last run
  07-14 22:00:16Z ran on `f34d5cd` (**pre-#1201**, 12 min before the merge). **First exercise =
  07-15 22:00Z.** EXPECT: `population_by_execution_mode` present; `pooled_all_modes` the only
  pooled label; no `live_eligible`-as-"live"; a population-summary failure → PARTIAL with the
  thesis upserts preserved.

**★ #1199 (F-REPLAY-FK) FALSIFIER — PASSED. The 07-14 pending disposition #1 is RESOLVED
(verified tonight, DB).** The nightly (00:00 CT) could only predict this; the RTH day delivered it:
- `data_blobs` = **9 rows; FIRST BLOB EVER at 2026-07-14 13:00:08.800835Z** — exactly the predicted
  13:00Z `suggestions_close`. (All-time count was **0** at the nightly.)
- `decision_runs` clean split, no ambiguity: **5 runs `failed`/`blob_never_persisted`, ALL 07-13
  (13:00→17:29Z, the annotated-unrecoverable set)** vs **4 runs `ok`/`tape_integrity='complete'`,
  ALL 07-14** (13:00 close + 14:11/16:00/17:48 opens).
- **The tape is now COMPLETE.** F-REPLAY-FK: `status:shipped`, falsifier PASSED — **do not re-find,
  do not re-verify.**

**★ NEW — GIT-SHA-DECISION-PROVENANCE (MED, CONFIRMED-empirically, evidence-integrity).**
**The replay tape is now complete in CONTENT and silent on PROVENANCE: `decision_runs.git_sha` =
the literal string `'unknown'` on 9/9 rows, all-time** (`distinct_sha = 1`) — across runs spanning
**TWO distinct deployed SHAs**, cross-referenced against Railway deployment times: **`8d93621`
carried the five 07-13 runs** (13:00→17:29Z; deployed 07-13 04:21:36Z) and **`f34d5cd` carried the
four 07-14 runs** (13:00→17:48Z; deployed 07-13 20:08:47Z). Two different code SHAs, one identical
non-SHA stamp — sufficient to prove the stamp does not track the running code.
- **⚠ ERRATUM against my own first draft of this entry (caught + corrected PRE-MERGE; recorded
  because the mistake is the instructive part).** The draft put the span at **4** SHAs, listing
  `8d93621` → `1386834` → `f34d5cd` → `bef2cdd`. **FALSE.** That is the period's DEPLOYMENT LIST,
  not the set the runs actually sit under: `1386834` lived ~5 minutes with no decision cycle, and
  `bef2cdd` deployed 23:05Z — **after** the day's last cycle (17:48Z). **The number of SHAs a
  run-set spans is a JOIN against deployment WINDOWS, not a count of deployments in the period.**
  The corrected span (2) already carries the finding in full; the overclaim was refutable by one
  query — a stretch where the honest smaller number was strictly better. Pinned by
  `test_docs_consistency.test_git_sha_span_claim_is_two_not_four`.

MECHANISM: the decision path reads **only** `GIT_SHA`
(`suggestions_open.py:139`, `suggestions_close.py:128` — `os.getenv("GIT_SHA")`, no fallback) and
`lineage.get_code_sha` (`:264`) degrades `GIT_SHA` → `APP_VERSION` → `"unknown"`; the **healthcheck
already solves this** (`api.py:154-157` resolves `GIT_SHA` **or** `RAILWAY_GIT_COMMIT_SHA`, the
name Railway actually injects) — the decision path simply does not reuse it. **This is not
cosmetic: it defeats the stated experiment contract "③'s SHA stamps the FULL experiment"** — a
replay tape that cannot name the code that produced it cannot attribute a decision to a SHA, which
is the whole point of the tape. Also blocks any before/after A-B read across a recycle. FIX SHAPE:
the decision path consumes the healthcheck's existing resolution (env NAME-only observation; no
value read, no env change in this lane). Falsifier: a post-fix `decision_run` carries a real
12-char SHA that MATCHES the Railway deployment SHA of the container that produced it. → backlog
P2 (evidence-integrity; rides the replay/tape family). **Not a #1199 regression — #1199 delivered
content integrity and never claimed provenance.**

**★ NEW — F-SHADOW-CAPITAL-PARITY (HIGH, CONFIRMED-empirically, evidence-integrity).**
**All three policy-lab cohort portfolios carry `net_liq = 100000` — including `aggressive`, the LIVE
CHAMPION (`routing_mode='live_eligible'`) — while broker truth is `$2,067.86`** (verified tonight:
equity = cash = OBP = portfolio_value = 2067.86, positions `[]`, `last_equity` 2067.86,
balance_asof 2026-07-13). DB-verified: aggressive `net_liq 100000` / `cash_balance 106883.75` ·
neutral `100000` / `97400.82` · conservative `100000` / `100031.64`. **≈48× the deployable basis
(§5.1: deployable = live Alpaca `options_buying_power`, never a DB snapshot).**
- **⚠ THE SHARP EDGE — #1200's fail-closed normalizer does NOT close this.** `_normalize_capital`
  (`fork.py:435-442`) correctly removes the hardcoded `or 100000` **literal** and treats `net_liq`
  as authoritative — but **the column itself contains the fabrication.** Reading a fabricated value
  authoritatively is still fabrication (H9). Removing a default that names $100,000 while the
  source-of-truth column *is* $100,000 changes the code path, not the number.
- SCOPE, stated honestly: this is the **policy-lab evidence surface**, NOT live sizing — live
  entry capital comes from the broker OBP path (§5.1) and `RiskBudgetEngine`, which this does not
  touch. It is nonetheless the quantified root under §8's "shadow ledgers are partly fiction /
  shadows fill at 5–17× live size" and it makes **champion promotion basis-broken** (the promotion
  compares cohorts sized against $100k to a live account at $2,068). Interacts with — does not
  duplicate — #1124's promotion-time normalization (discount 0.31 measured).
- **BLOCKS E19-2B**: a counterfactual *selector* sized on $100k selects trades the live account
  could never fund. → backlog P1.
- Falsifier: cohort capital reads resolve to a broker-grounded basis (or the experiment declares its
  basis explicitly and promotion normalizes it), and a promotion comparison states its capital basis.

**★ NEW — F-POLICY-CAPITAL-FALLBACK (MED, CONFIRMED-by-cite, evidence-integrity) — filed by #1200,
WIDENED here: it is TWO sites, not one.** The `net_liq or cash_balance or 100000` fabrication
survives at:
- `policy_lab/fork.py:210` — the legacy normal-shadow-clone loop (**the one #1200's §9 DISCLOSURE
  names**; explicitly out of #1200's narrowed/frozen scope, annotated in-place at `:201`).
- **`policy_lab/evaluator.py:251` — a SECOND, UN-NAMED site** (`float(portfolio.get("net_liq") or
  portfolio.get("cash_balance") or 100000)`). Found this session by grep; **#1200's PR body names
  only the fork site.** Fixing only the disclosed site would leave the evaluator fabricating.
- `policy_lab/init_lab.py:12` `INITIAL_CAPITAL = 100_000.0` is the **seeding origin** of
  F-SHADOW-CAPITAL-PARITY's DB values — the two findings share a root; fix them as a family, not
  ad hoc. → backlog P2 (rides F-SHADOW-CAPITAL-PARITY).

**★ prequential_validator OPERATIONALIZATION (NEW, structural — the falsifier that never runs).**
**`prequential_validator` has ZERO production callers** (verified repo-wide this session): no
scheduler entry (`scheduler.py` has none), no job handler, no import outside its own module — the
sole non-test reference is a **docstring mention** at `calibration_service.py:317`. It is reachable
only via its own `main()` / `if __name__ == "__main__"` (`:242`, `:281`). **So #1201 correctly
repaired a validator that nothing invokes** — the fix is real and the []-green disease is closed at
the seam, but the seam is not on any live route. **This is the #1126/9a2cef1 costume's cousin, with
the honest difference that #1201 never claimed a caller** — recording it so no future audit reads
"prequential parity shipped" as "prequential validation runs."
- **SCHEDULING IS AN OPERATOR DECISION — explicitly NOT taken here and NOT recommended by default.**
  The validator is the designated **falsifier** for the calibration multiplier (F-A1-3 / E17
  family); wiring it to a schedule is a live-adjacent decision (queue routing, cadence, what a
  failing prequential verdict should *do*), and doctrine reserves that for the operator. Options,
  unranked: (a) leave manual/on-demand — status quo, zero risk, the falsifier stays unexercised;
  (b) schedule read-only on `background` and alert on divergence; (c) gate the multiplier on it —
  behavioral, needs its own PR + flag. → backlog P2 (RESEARCH-adjacent; owner-gated).

**QUEUE ①–④ — ALL FOUR CLOSED (the v1.4 post-close queue is fully cleared):**
| # | Item | PR | Squash SHA | Merged (UTC) | Deploy status |
|---|---|---|---|---|---|
| ① | E8-3 typed sentinel | #1195 | `af1c5be` | 2026-07-13 03:42 | superseded (REMOVED) |
| ② | E16-3 manifests + F-REPLAY-FK | #1199 | `f34d5cd` | 2026-07-13 20:08 | superseded (REMOVED) · **falsifier PASSED 07-14** |
| ③ | E19-2 → shipped as **E19-2A** | #1200 | `bef2cdd` | 2026-07-14 23:05 | **LIVE** · falsifier 07-15 |
| ④ | F-A3-4 prequential parity | #1201 | `9670712` | 2026-07-14 22:28 | **deployed within `bef2cdd`** · falsifier 07-15 |

**★ F-WINDOW-1 — IDENTIFIER COLLISION RESOLVED (two different defects were riding one name).**
The name was reused across two genuinely distinct defects, and the 07-13/07-14 entries closed one
while the backlog still carried the other — a silent-retirement hazard. **Split, both preserved:**
- **F-WINDOW-1a — heartbeat EMISSION.** "The beats exist (#1187 `log_shadow_heartbeat`) but ride a
  dead channel (root logger unconfigured → every `logger.info` destroyed in-process)." **CLOSED at
  `1386834` (#1198)** — the deliverable was the handler, not new heartbeats; proven post-close by
  an `[ALPACA_SYNC]` INFO line reaching Railway. **This — and ONLY this — is what the 07-14 nightly
  entry's "F-WINDOW-1 CLOSED" means.**
- **F-WINDOW-1b — heartbeat COVERAGE + JOINABILITY (OPEN, P2 tail).** The v1.4 original
  (CONFIRMED-by-cite): only W4 (APPLY_ORDER) + a generic post-portfolio EXECUTOR_SHADOW; **W1 no
  gate-site beat · W2 no per-consumer zero-eval beat · W3 pre-portfolio miss + no candidate/
  reservation-order identity · no shared cycle/decision ID → W5 unjoinable.** A live channel does
  not create a shared correlation ID. **The ARM decisions wait on JOINABLE evidence — 1a's closure
  does NOT release them.** W-clocks do NOT reset for observability-only additions (unchanged).
- **DOCTRINE PRESERVED (unchanged, restated so the split cannot lose it): the arm-evidence clock
  restarted at `1386834` — the THIRD restart** (`d5edd50`'s evidence never existed; the channel was
  dead; `[RISK_BASIS_SHADOW]` has NEVER emitted).

**F-A9-5 — DRAFT, NOT SHIPPED (Lane A is OPEN as of this session).** `_log_cohort_decisions`
compares dollar `ev` to a 0-100 score threshold (`fork.py:466-477`) while the real filter compares
`sizing_metadata.score` (`:233-236`) → `ev_below_min` is an evidentiary lie (routing byte-correct).
Lane A = PR #1203 `fix/f-a9-5-routing-log-truth` is **DRAFT, 1 commit at `28e4990`** — its
#1200-live-observation block is cleared but it is **not shipped** (BEHIND current main; needs rebase +
adversarial/CI review). Status stays `status:reported` / DRAFT until a squash SHA + H8 pin exist.
Do not mark shipped on branch existence.

**CREDENTIAL HYGIENE (standing doctrine, re-affirmed — no incident recorded).** Diff env key
**NAMES** only; never `list_variables`/`printenv`/`env`; never emit values (origin: the 06-18
transcript incident). **Nothing in this lane read an env value**; the GIT-SHA finding above is a
NAME-only observation. Pinned by `test_docs_consistency.py` — the audit docs are committed and
world-readable, so a credential-**shaped** string in `ledger.md` / `backlog.md` / any dated report
now fails CI. Credential **classes and names only, never values, fragments, or fingerprints.**
*(Operator decision this session: no credential-incident entry is recorded here — the ledger
carries no security disposition either way. F-FREE-1 (07-04) stands unchanged on its own terms:
LOCAL-ONLY-FAKE, no live rotation warranted.)*

**PRESERVED, NOT RE-LITIGATED (carried forward untouched — do not reopen):** calibration ×0.5 floor
SETTLED (floor-HOLD until ~15–20 live closes; F-A1-3 scope = persisted-ev + roundtrip gate ONLY,
selection/sizing RAW) · pool **8/8 post-epoch (1W/7L)** · close-fill-gap **3/10–15** · universe
**78** · breaker armed-quiet (`entries_paused=false`, fingerprint [055ead84, 7dd459f8, bd895160],
trip 07-08 21:20Z; edge-trigger; recovery OPERATOR-ONLY) · SOFI sentinel SETTLED trigger · 1-of-N
economics SETTLED · greeks envelope DOUBLE-dormant · EXCLUDED-EVIDENCE day 07-06 · retirement
counters **A1=6 · A2=4 · A3=6 · A4=2 · A5=4 · A6=6 · A8=5 · A9=2 · A10=6** with the nightly's
honest read (quiet-regime artifact, NOT territory coverage — **recommend KEEP all four**;
owner-gated, never unattended) · A10 → A11 Security-lens rotation queued · the autopilot costume
(A5/A9, 4× on 07-13) still riding the slipping 3-in-1 observability PR.

## 2026-07-14 (Tue 00:00 CT) — NIGHTLY AUDIT (v5.5, scheduled) — report audit/reports/2026-07-14.md · NO NEW FINDING

STEP-0: DB `now()` 05:00:35Z = Tue 00:00:35 CT (dow=Tue) = broker 01:00:35 ET, agree to the second,
market CLOSED. Tuesday ⇒ NIGHTLY. **Run NOT broker-blind** (interactive; Alpaca MCP surfaced — 3
broker calls). H8 pin: run-START = run-END SHA = **`f34d5cd`** (#1199), sole non-REMOVED Railway
deployment (SUCCESS 07-13 20:08:47Z) = local HEAD; no overnight mover.

**No new finding; no ALERT file (zero new criticals).** Window audited = the full Monday 07-13 RTH
day + the two post-close merges — the richest moved-signal window in a week, but both merges' first
natural tests are in 07-14 RTH, not the window just closed.

VERIFICATIONS (all ✅ / expected):
- **Monday 07-13 = zero-entry day**: 6 suggestions, 0 orders, 0 opens, 0 closes, 665 rejection rows
  (~2× over-count). Pool 8/8 (1W/7L) unchanged; close-fill-gap 3/10–15 unchanged.
- **Broker flat, unchanged to the cent**: positions `[]`; equity=cash=OBP=portfolio_value=**$2,067.86**;
  last_equity $2,067.86; balance_asof 2026-07-10. A2 one-beta condition holds (0 live positions).
- **F-REPLAY-FK still-latent-through-07-13 (KNOWN, verified, not re-found)**: `data_blobs`=0 all-time;
  `decision_runs`=5 all `failed` (latest 17:29Z) = the exact 5 unrecoverable runs the 07-13 morning
  diagnosis named. #1199 merged 20:08Z after the last decision cycle → **first exercise = 07-14
  13:00Z** (expect first-ever `data_blobs>0` + `tape_integrity='complete'`). VERIFY IF fired.
- **Calibration ×0.5 confirmed in production**: every aggressive suggestion `ev = ev_raw × 0.5000`
  exactly (F-A1-3 scope: persisted-ev + roundtrip gate ONLY; selection/sizing RAW). Out of raw mode,
  SETTLED (floor-HOLD until ~15–20 live closes) — do NOT re-flag.
- **Breaker armed-quiet**: `entries_paused=false`, reason NULL, unchanged since 07-09 11:53Z;
  `streak_breaker_state.last_tripped_fingerprint` = [055ead84, 7dd459f8, bd895160], tripped_at
  07-08 21:20Z intact. 0 closes ⇒ trailing window unchanged ⇒ edge-trigger correctly did NOT re-pause.
  Zero flag-only-if conditions met.
- **SOFI sentinel QUIET (A8)**: 2 SOFI debit spreads blocked at `edge_below_minimum` (upstream of the
  roundtrip gate — did NOT clear it). The SETTLED trigger did not fire.
- **Full learning chain + all 22 job types succeeded** Monday; no failures. H11 critical = only
  `ops_job_never_run` ×9 (latest 21:07Z) = the known thesis_tracker hourly arm, self-resolved at its
  22:00Z first run (thesis_tracker succeeded 22:00:02Z; none since).

FREE LOOK (1 SQL): traced the sole unexplained warning class
`paper_autopilot_cohort_per_suggestion_failed` ×4 (07-13) → metadata
`distinct_error_classes:["EntryRoundtripCostExceedsEV"]`, ticker QQQ. **Resolved to the KNOWN 07-10
A5/A9 "autopilot costume"**: `EntryRoundtripCostExceedsEV` (the #1101 gate) lacks a dedicated
`except` clause in `_execute_per_cohort`, so a designed NO falls to the catch-all `except Exception`
(paper_autopilot_service.py:1182-1191) and is dressed as "executions failed / did not execute as
expected" — unlike the sibling enforced blocks (SymbolCooldownActive :1131, EntryUtilizationBlocked
:1138) that each `continue` without polluting the failure aggregation. Also emits a
`logger.error("policy_lab_execute_error…")` line per fire. NOT a new finding — fix already queued in
the slipping 3-in-1 observability PR (now ~5th consecutive build-day slip). Recurred 4× on the first
fully-visible RTH day, sharpening the A5 slip case.

RETIREMENT COUNTERS: A1=6, A2=4, A3=6, A4=2, A5=4, A6=6, A8=5, A9=2, A10=6. **A1/A3/A6/A10 hit 6 =
proposal territory (owner-gated).** Honest read: quiet-regime artifact (weekend + zero-entry + flat
book), NOT territory coverage — a proposal would fail its own "covered elsewhere" test; A10's path is
A11's Security-lens rotation. Recommend KEEP all four; owner glance only.

PROMPT-STATE DRIFT (for v5.5→v5.6, movers named not alarms): running-SHA STATE still pins
`655c9aa`/#1143 → HEAD now `f34d5cd`/#1199 · "first calibrated production scan pends 07-10 16:00Z"
line stale (calibration ×0.5 in prod since 07-10, re-confirmed tonight).


## 2026-07-13 (Mon ~15:1x CT, post-close) — PR-0 #1198 + PR-② #1199 SHIPPED — H8 PASS ×2 · status:shipped

STEP-0: host 20:04:31Z = DB 20:04:33Z = broker 16:04 ET, market CLOSED. RTH
premise in the queue header corrected at 18:02Z (clocks won; both PRs prepared
on branches during RTH, merged only post-close). Single controller confirmed;
the obsolete 20:01Z sleep loop was already dead (600s cap), replaced by a
Monitor that fired at 20:01Z.

**PR-0 #1198 (logging) — squash `1386834`, merged 20:03:07Z. H8 PASS.**
All 3 services SUCCESS at the SHA (20:03:09-10Z). Canaries: BE 20:04:29Z
(container start) · worker 20:05:01Z (first post-recycle job) — and the fix
visibly WORKING: the same job's `[ALPACA_SYNC]` app INFO line reached Railway
(impossible pre-fix). No tracebacks.
- ⭐ **THE ARM-EVIDENCE CLOCK RESTARTS AT `1386834`** (third restart —
  d5edd50's evidence never existed; the channel was dead).
- **The #1187 heartbeats are LIVE at this SHA with zero code change.
  F-WINDOW-1 CLOSED** (the deliverable was the handler).
- Residual (minor, tunable): `rq.worker` sets its own child-logger level, so
  the parent-`rq` WARNING pin doesn't stop propagation → RQ job lines print
  twice (rq handler + root). Cosmetic; pin `rq.worker` if it grates.

**Migration `decision_runs_tape_integrity` — applied 20:03:33Z, read-back
PASS** (tracked as latest; backfill = exactly 5 rows `blob_never_persisted`,
0 NULL, 5 total runs). ORDERING DEVIATION (recorded): applied while PR-0's
deploy was still BUILDING, i.e. before PR-0 H8 completed — the load-bearing
constraint (migration BEFORE #1199 merge) was preserved; the column is
annotation-only and nothing at `1386834` reads it.

**PR-② #1199 (tape integrity) — squash `f34d5cd`, merged 20:08:47Z (after a
BEHIND branch-update + fresh CI green; head `33cc5aa` content unchanged,
update was main-merge only). H8 PASS.** All 3 services SUCCESS at the SHA
(worker+bg 20:08:46-47Z records; BE 20:08:46Z → SUCCESS). Content verified
by grep AT the squash SHA: payload hex-encode + `_decode_bytea` (blob_store) ·
`unpersisted_of` + capture_partial ×4 (decision_context) ·
`_capture_decision_manifest` ×10 sites (7 midday + 2 morning + def) · both
handler surfacings. Canaries on the NEW containers: worker 20:10:01Z · BE
20:09:59Z; worker Error-line sweep clean. worker-background canary
PENDING-BY-DESIGN (first job = the 21:00Z learning chain; its 20:03Z container
start was clean).
- **THE TAPE-COMPLETE BOUNDARY STAMPS AT `f34d5cd`** — first natural test:
  tomorrow 13:00Z suggestions_close (expect decision_run status ok,
  tape_integrity='complete', data_blobs > 0 for the first time ever).
- CI note (E8-3-adjacent lesson, small): the route-driving tests initially
  used `asyncio.get_event_loop()` — green locally on a leftover loop, red in
  CI (`no current event loop`); fixed to `asyncio.run` (fresh loop). The
  local pass was environment luck, not correctness.

**Post-close health (20:1xZ):** broker positions [] = DB open 0 · broker open
orders [] = DB working 0 · H11 since 18:00Z = ONLY `ops_job_never_run`
(thesis_tracker, hourly, expected until its 22:00Z first run — P9 grades it)
· stuck-`running` ×4 = exactly the known reaper fossils (06-11 order_sync ·
05-18 promotion_check · 01-14/01-09 validation_eval), NO new orphans from
tonight's two recycles · extra-runs CLASSIFIED: the 14:05/15:02/17:29Z
suggestions_open extras carry an EXPLICIT user_id payload (scheduler runs
carry user_id null) each followed ~90-120s by a paper_auto_execute with a
`timestamp` payload — an API-triggered per-user chain, NOT scheduler
duplicates; provenance (which endpoint/caller) still UNTRACED — the existing
backlog line now has its discriminator.

**③ E19-2 + ④ F-A3-4 HELD to tomorrow post-close (zero cost, sanctioned)** —
the RTH correction compressed the evening; E19-2 is design-care/MED-risk.

## 2026-07-13 (Mon ~13:0x CT, RTH read-only) — ② PRE-BUILD DIAGNOSIS: F-REPLAY-FK ROOT CAUSE + ★ NEW F-LOG-INFO-DROP · status:reported

STEP-0: DB 17:37Z / broker 13:37 ET agree; read-only + doc writes (repro script
scratchpad-only, not committed).

**F-REPLAY-FK ROOT CAUSE (CORRECTS both prior framings — the morning entry's
"partial batch" and the midday grade's "one deterministic blob"):** `data_blobs`
has **ZERO rows, all-time**. Every blob batch fails; smoking gun 5/5 cycles in
worker logs: `BlobStore batch commit failed: Object of type bytes is not JSON
serializable`. Mechanism: `blob_store.py:158` stages raw gzip BYTES as
`payload`; `commit()` (`:289-292`) upserts via supabase-py, which JSON-serializes
the row batch → TypeError on EVERY batch (~5 blobs/run ride ONE batch,
COMMIT_BATCH_SIZE=200) → all hashes failed → `decision_context` inserts
decision_inputs referencing never-persisted hashes → FK 23503 → run failed, job
green. `82b5be18…` is merely the FIRST violating row in stable insert order (the
input shared by close + open cycles), not a special blob. The 2MB cap is
warn-only AND never triggered — unrelated. REPRODUCED locally
(scratchpad/repro_blob_fk.py): json.dumps of the staged row → the exact
TypeError; fix shape PROVEN: payload as PostgREST bytea hex-string (`\x`+hex)
serializes and round-trips. HOW IT SHIPPED GREEN:
`test_replay_feature_store.py:202-203` MagicMock supabase client — a mock AT the
failing layer (the client serialization boundary); 4th instance of the
inject-at-origin class (§9).
**② FIX SHAPE (tonight):** (a) hex-encode payload at commit + decode `\x`-hex on
`get()`/`get_many()` (the read path `:184-189` expects bytes and would fail on
the string PostgREST returns — fix BOTH sides); (b) atomicity gate:
blobs_committed == expected BEFORE the decision_inputs insert — shortfall →
typed `capture_partial`, never an FK-orphaned insert attempt; (c) oversize →
the same typed capture_partial, never staged-and-referenced; (d) the test drives
the REAL serialization boundary (json.dumps of the batch at minimum), not a
MagicMock. Annotation sweep: 5 runs today (13:00 close + 14:05/15:02/16:00/
17:29 opens), ALL unrecoverable (no blobs exist), same first-FK hash.

**★ F-LOG-INFO-DROP (NEW, HIGH, instrumentation-integrity) — the worker process
DROPS every `logger.info` in the app.** No logging config exists ANYWHERE in the
repo (basicConfig/dictConfig/addHandler: test-local only); workers are bare RQ
SimpleWorker → root logger unconfigured → Python lastResort handler = stderr at
WARNING. So print() and warning+ reach Railway; EVERY info line in
packages/quantum is destroyed IN-PROCESS (never emitted — not a Railway filter).
Proof: intraday_risk_monitor ran 17:30/17:45Z (RQ "Job OK" wrapper lines) but
its `[RISK_MONITOR]` info summary (`:583`) is absent; utilization_gate logs at
WARNING only (`utilization_gate.py:119-424`) — exactly why its lines are the
ones we see.
- **Shadow-window verdicts — all three = CONFIG (not gated-behind-arm, not
  unreached-path):** [APPLY_ORDER_SHADOW] (`calibration_apply_ordering.py:158`,
  info) · [RISK_BASIS_SHADOW] (`risk_basis_shadow.py:40/:50`, info) ·
  [BUCKET_SHADOW] (`bucket_control.py:177`, info). All emit at info on paths that
  RAN today (gate evaluated, executor processed 4 candidates, scan ranked). The
  observe guards are CORRECT — each logs when the arm flag is OFF; no window
  logs-only-when-armed.
- **The heartbeats ALREADY EXIST and ride the same dead channel:**
  `log_shadow_heartbeat` (`risk_basis_shadow.py:58-70`, info) is wired at the
  apply seam (`calibration_apply_ordering.py:118-124`) and the executor
  (`paper_autopilot_service.py:976-983`) — built by #1187 PRECISELY to
  disambiguate "ran-saw-nothing vs logging lost", and killed by the exact
  logging loss it exists to detect. F-WINDOW-1 reframed: not "build heartbeats"
  — "give the channel a handler".
- **⚠ W-CLOCK ANNOTATION: the arm-evidence stream since d5edd50 (07-12) has
  produced ZERO collectible lines** — [RISK_BASIS_SHADOW] has NEVER appeared in
  Railway (4d search; the current deployment covers the whole window; no market
  cycles before Monday). Day-1/day-2 evidence LOST; the ~1wk observation clock
  was never running; **it restarts at tonight's logging-fix SHA.** (The one
  shadow marker ever observed — 07-09's [GATE_QTY_SCALED_SHADOW] ×9 — is
  logger.WARNING, `paper_endpoints.py:1370`: consistent, and explains why the
  v1.3 W2/W4 analyses were code-reads, not log-reads.)
- **② RIDER (small, tonight per operator): worker logging config at startup** —
  root INFO, or a targeted INFO level for the shadow/heartbeat/monitor loggers
  (owner's call on noise; scanner info is voluminous) + confirm RQ noise stays
  bounded. Supersedes the F-WINDOW-1 P2-tail build item (heartbeats exist; the
  fix is the channel).

## 2026-07-13 (Mon ~12:5x CT, RTH read-only) — SCORING/GAP-REPORT ADJUDICATION (the doctrinal audit's 64/100 companion) — reconciliation + adoptions · status:reported

STEP-0: DB `17:48Z` / broker `13:48 ET` agree (Mon 07-13, market OPEN — read-only
+ doc writes; tonight's ②③④ UNCHANGED). Source document NOT on disk (same as the
~12:1x doctrinal entry); adjudicated against the operator's restated gap set.
H11: only the known `ops_job_never_run` thesis_tracker arm (×5, latest 17:07Z;
self-resolves at the 17:00 CT first run per the morning entry).

**RECONCILIATION (10 ranked gaps → backlog): ALL TEN HAVE HOMES; queue order
UNCHANGED.** 1→canonical-position-representation (07-13 P1) · 2→queue-⑤ (charter
enriched 07-13) · 3→⑥ partial-close (trigger-gated P0) · 4→multi-basis cost P1
(incl. the ranker 4× worst case) · 5→tonight's ②+③ (② already expanded by
F-REPLAY-FK this morning) · 6→④ F-A3-4 + ③ E19-2 + the NEW segment-n line
(below) · 7→Phase-3 gate — **3/10-15 VERIFIED**: 3 stamped live fills
07-01→07-08 in `paper_orders.order_json` (`close_fill_gap_*` keys), all with
gap_fraction; the 07-08 SIGN FIX is IN CODE (`alpaca_order_handler.py:660-665`)
so the accruing evidence basis is clean — the stale "first gap_fraction still
pending" backlog line corrected · 8→versioned-earnings + per-leg quote envelope
(+ the r/q rider, below) · 9→vertical-before-IC (07-13 GATED) · 10→throughput
tail (greedy-stop DOWNGRADE stands · reaper∪F-A4-2 · W2b · F-A10-1 DST/warm-up
+ the A10 winter-close note).

**NEW CLAIM 2a — CONFIRMED (LATENT): segment calibration admits at n=3.**
`calibration_service.py:240` `if len(group) < max(3, min_trades // 4)` with
MIN_CALIBRATION_TRADES=8 → per-segment floor **3**, while the OVERALL gate
requires 8 (`:217`); `apply_calibration` (`:610-641`) applies the most-specific
segment multiplier with NO sample-size re-check at apply time; and the >5%
deviation filter (`:250`) preferentially persists small-n noise (small samples
deviate more). LATENT today: the live blob is `_overall`-only (n=8, ev/pop ×0.5
floor — DB-verified this session); it fires as live segments reach 3-4 closes.
→ NEW backlog line (07-13 section).

**NEW CLAIM 2b — PARTIALLY BUILT: r/q basis captured on ONE path only.**
`bs_inversion.py` prices with caller-supplied r/q; the sole production caller
family assumes FIXED r=0.045 (`BACKFILL_RISK_FREE_RATE` default,
`iv_historical_backfill.py:41`) and q=0.0 (`HistoricalIVService` default, never
overridden — the handler doesn't pass dividend_yield at all). The BACKFILL path
DOES persist both (`historical_iv_service.py:359-361` →
`underlying_iv_points.inputs` jsonb, `iv_repository.py:116`). NOT captured: the
daily snapshot path (feed-provided IV — the provider's r/q assumptions unknown)
and decision-stage per-leg quotes/greeks. → one-line rider on the per-leg
quote-envelope item (cheap; replay fidelity).

**CORRECTIONS CARRIED (annotated, not adopted):** (3a) gap 1's "feeds active
monitoring and entry breakers" is OVERSTATED — the ~12:1x verdict stands:
CONFIRMED-LATENT, P1 with the re-arming seam as the trigger (greeks doubly
dormant · stress warn-only · concentration demoted-to-WARN with the flag
live-echoed). Not P0-live. (3b) gap 10's "greedy-stop removed" done-criterion
CONTRADICTS the Lane-A replay DOWNGRADE (the budget break never fired in any
replayed cycle); the standing done-criterion is "downgrade verdict stands with
its mechanical reopen (>4 fitting candidates AND the roundtrip gate passing a
tail)," not "removed."

**MILESTONE SCALE — ADOPTED as the standing convention (theirs, verbatim):**
**85** = no known critical correctness defect, decisions reproducible · **90** =
canonical risk/EV/costs/replay/partial-close complete · **95** = repeated
runtime proof + Phase-3 evidence + failure-injection exercises · **100** =
reference ceiling only. **Realistic goal: 90-95.** Adopted closing line: "a
genuinely excellent design may correctly conclude that none of today's
candidates has positive net edge" — the capital-adequacy note's doctrine twin.

**POINTS-AS-CROSS-CHECK:** their point-weighting independently converges on our
queue — their #1/#2/#5 = our canonical-position / ⑤ / tonight's ②③, and their
cost-basis (+3) above partial-close (+2) effectively matches our ⑥
trigger-gating (both orderings say cost coherence binds before partial-close
custody while the book is flat). No divergence demands an owner look; NO queue
changes from scoring alone. Only the +3/+2 values were restated by the operator
— rubric weights are opinions, not adjudicable facts.

**SCORECARD (filed as CONTEXT, not a verified quantity):** 64/100, stated range
62-68, on their stricter rubric. Epistemics worth paying externals for: they
retracted their own "28.1% growth" figure as false precision — the
self-correction is the value; the number itself is context only.

## 2026-07-13 (Mon ~12:1x CT, RTH read-only) — DOCTRINAL-AUDIT ADJUDICATION (Sinclair/Natenberg) — scorecard + verdicts · status:reported

STEP-0: DB `17:11Z` / broker `13:11 ET` agree (Mon 07-13, market OPEN — sanctioned
read-only doc session, no builds/recycles). Source document NOT on disk (Downloads
swept, repo grepped — no Sinclair/Natenberg artifact); adjudicated against the
operator's restated claim set, fully specified per sub-claim. Their blind spot
honored: every live-path claim got the runtime check they couldn't run. Tonight's
queue (② E16-3 → ③ E19-2 → ④ F-A3-4 → tail) **UNCHANGED** — the P0 gate condition
(CONFIRMED-ARMED) did not obtain.

**F-RISK-ENV (their #3) — VERDICT: CONFIRMED-LATENT (all four sub-claims CONFIRMED
in code; NO defective number can flip a live decision as deployed today) + a NAMED
RE-ARMING SEAM.**
- (i) CONFIRMED `risk_envelope.py:200-201` — `_pos_risk` returns
  `max_credit×qty×100` (the credit RECEIVED = max GAIN) as "risk" for credit
  structures; true defined-risk basis is width−credit. Feeds all concentration
  ratios + `total_risk`.
- (ii) CONFIRMED `:230-233` (stress twin `:519-520`) — leg greeks ×
  `abs(position_qty)`×100: no buy/sell sign, per-leg quantity ignored entirely.
- (iii) CONFIRMED `:524` — `spy_loss = total_delta × 0.05` treats −5% SPY as a
  −$0.05 move (underlying price missing; ~600× understated). Same-family bonus
  `:530`: the VIX leg treats "+50%" as +50 vol points (overstated).
- (iv) CONFIRMED `:535` — correlation-one = −`total_risk` = Σ of (i)'s basis.
- RUNTIME (the check they couldn't run): consumers at HEAD = autopilot breaker
  (`paper_autopilot_service.py:407-427`, blocks ONLY on passed=False =
  block/force_close) · monitor 5b (`intraday_risk_monitor.py:517-572` —
  force_close only ever from LOSS envelopes, whose basis is unrealized_pl, NOT
  `_pos_risk`; warn/block → `envelope_violation` alert rows, no action) · MTM +
  orchestrator log-only · `check_new_position` still zero production callers.
  Greeks DOUBLY dormant RE-VERIFIED TODAY: 0 legs (of 83 positions ever) carry a
  `greeks` key + RISK_MAX_DELTA/GAMMA/VEGA/THETA unset (default 0 = no-limit) —
  (ii)+(iii) SPY-side compute only zeros, and are severity=warn regardless.
  Stress = warn → alert-noise ceiling. The ONLY block-capable defective-basis
  path is `concentration_symbol` (basis = (i)) — DEMOTED to WARN in the sole
  blocking consumer, read back on the RUNNING worker today
  (`[UTILIZATION_GATE] flag RISK_UTILIZATION_GATE_ENABLED raw='1' → enabled=True`
  + small-tier demotion lines at 14:06/16:09/16:30Z). Armed envelope env
  (worker; names+values non-secret): SYMBOL_PCT=.4 · DAILY=.08 · WEEKLY=.1 ·
  SYMBOL_LOSS=.03 · utilization =1 cap .85 · RISK_ENVELOPE_ENFORCE=1; stress
  thresholds at defaults.
- THE RE-ARMING SEAM (why this is P1, not P3): unsetting
  RISK_UTILIZATION_GATE_ENABLED (a §4 SANCTIONED kill switch — "reverts to the
  stricter BLOCK" — i.e. reverts to a block ON THE WRONG BASIS), any
  demotion-check failure (fail-safe retains BLOCK), or tier growth past small
  → `concentration_symbol` blocks entries on credit-received ratios. Alert-noise
  is DEMONSTRATED, not hypothetical: 6 `envelope_violation` rows 07-07/07-08
  (symbol high ×2 / sector ×2 / expiry ×2) fired off this basis. Book FLAT
  (broker + DB) at adjudication; QQQ candidates ALLOWed today, so the basis
  becomes computable on the next fill — still non-blocking under demotion.
- DISPOSITION: MERGED into the NEW canonical-position-representation P1
  (backlog 07-13 section) with the book-scaling family (#1166's persisted
  max_loss_total is the same truth — reuse, don't recompute).

**IC EV BASIS (their #2) — CONFIRMED, with a runtime CORRECTION.** Deployed model
is `tail` (CONDOR_EV_MODEL=tail on worker): `calculate_condor_ev_tail`
(`ev_calculator.py:632-712`) = |shortΔ|×prob_mult as breach prob, |longΔ| as
max-loss prob, fixed partial-loss severity — but the deployed constants are
severity **0.35** (not the 0.50 default they read) and CONDOR_TAIL_PROB_MULT
**0.6** (an ad-hoc 40% delta haircut they didn't see — which REINFORCES their
point: this is a tuned modeled EV, not a physical forecast). The scanner stamps it
(`options_scanner.py:1800-1823` → `:3505-3506` → suggestion ev_raw; 22 IC
suggestions/30d, latest today 16:00Z QQQ), calibration halves it (ev = 0.5×ev_raw
exactly — floor engaged, live rows verified), and the #1101 roundtrip gate
compares costs against THAT number. Honest framing: the known "modeled EV" made
precise — NOT a new gate bug. → queue-⑤ charter ENRICHED (backlog): ONE
independent terminal distribution, TWO payoff integrations (credit verticals E12
+ condor EV); their ensemble spec + falsifier attached verbatim.

**CALIBRATION CLAMP (their #4) — CONFIRMED; floor-HOLD annotation only.**
`calibration_service.py:466-479`: ratio = realized_avg/predicted_avg clamped
[0.5,1.5]; a NEGATIVE realized average floors at ×0.5 — multiplicative, so it
can only shrink a positive predicted edge, never flip its sign. ANNOTATION on the
SETTLED floor-HOLD decision (07-09; stands): **the 0.5 floor bounds shrink but
cannot correct a sign-wrong edge — the falsifier (E17/prequential, F-A1-3) and
queue-⑤ are the actual defenses.** No action.

**RV BASIS FORKS — CONFIRMED.** `vol_math.py` correct (log, √252, ddof=0);
per-symbol rv_20d/iv_rv_spread path clean. LIVE simple-return forks: ①
`regime_engine_v3.py:204-205` — the GLOBAL SPY regime vol is an inline
SIMPLE-return calc in the very file whose per-symbol path uses the log helper
(rv_20d→vol_z→global regime state, stamped on every suggestion) · ②
`factors.py:197-244` + `market_data.py:267-269,368` HV-proxy iv_rank (simple) on
the universe/enrichment fallback path · ③ `market_data.py:1060`
calculate_portfolio_inputs (simple returns, np.cov ddof=1) → optimizer endpoints.
Dormant forks (truth_layer iv_context · factors indicators/calculate_volatility ·
vol_signal observe-only · regime v4) inventoried, no action. → backlog
RV-unification line (rides the multi-basis family).

**SURFACE — CONFIRMED; KEEP OBSERVE-ONLY (their recommendation = ours).**
Runtime: SURFACE_V4_ENABLE=true + SURFACE_V4_POLICY unset → default "observe" →
the skip/reject branches (`options_scanner.py:3284-3299`) never fire. Skew fork:
`iv_surface.py:155-177` "25-delta skew" is FIXED k=±0.35 log-moneyness
(e^0.35 ≈ 42% OTM), raw put−call difference — vs `iv_point_service.py:192-268`
actual ±0.25-delta contracts, ATM-NORMALIZED. Term-slope fork: `iv_surface.py:220`
front/back RATIO vs `iv_point_service.py:277-283` 90d−30d DIFFERENCE (different
functional form AND opposite sign convention). arb_free: butterfly enforced as
convexity-in-w via slope monotonicity (`surface_geometry_v4.py:461-530`) —
necessary-not-sufficient (their Gatheral note) → doc-level rename/annotate filed
in backlog.

**RANKER FEES (their cost case) — CONFIRMED, ALREADY-KNOWN (A3 07-09), worst case
sharpened.** `canonical_ranker.py:69` `fee_per_contract × contracts × 2` is
leg-blind: an IC round trip is 8 leg-contracts ≈ $5.20 at $0.65 vs $1.30 computed
(4× understate; verticals 2×). Folded into the multi-basis cost item.

**EARNINGS — CONFIRMED; enriches the versioned-earnings item (recon #3).** Stub
map is 2025-dated fixture rot (`earnings_calendar_service.py:27-42`; LATENT — only
active if POLYGON_API_KEY unset) · filing+90d stepped estimate served as a bare
date, no confidence class (`:75-88`) · hard-reject only ≤2d short-premium +
penalty ≤7d, NO event-before-expiry check (`options_scanner.py:3871-3886`;
A1c(ii) already confirmed this). Point-in-time schema (status enum
confirmed/estimated/implied/unknown + known_at + before-expiry flag) attached to
the backlog item.

**SCORECARD CONVERGENCES:** "richer forecast modules dormant" CONFIRMED and
SHARPENED — the forecast package (`return_forecast`/`vol_forecast`/
`forecast_interface`) has ZERO production consumers while FORECAST_V4_ENABLED=true
sits SET on the worker: an INERT armed flag on an orphan module (#1126-family
inventory member; no urgency, nothing reads it) · "score recomputation defaults
off" = W4 CONFIRMED at code (`calibration_apply_ordering.py:32-34`, strict =1) AND
runtime (unset on worker → observe). Their independent read converging on our
observe-window state + their independent re-derivation of E12 = calibration
signal: their STATIC reads are trustworthy on algebra; their live-path claims
correctly self-flagged as unprovable without runtime access (this session closed
that gap; verdicts above).

**THEIR OVERALL VERDICT (quoted, adopted):** "strongest at measurement, weakest at
converting volatility information into independent probability and net EV — fixing
that + risk units + costs beats any new strike rule."

**H11 side observation (not theirs):** `ops_job_never_run` CRITICAL firing hourly
since 13:07Z today for `thesis_tracker` (daily) — the job entered EXPECTED_JOBS
with the weekend #1164 ship and its first scheduled run is 17:00 CT TODAY (the
morning entry's P9 pin). Expected to self-resolve after that run; still firing
tomorrow morning = real finding. No action taken (RTH read-only).

## 2026-07-13 (Mon ~08:0x CT) — MORNING RITUAL v2 triage (READ-ONLY) — ★ NEW: F-REPLAY-FK

STEP-0: DB `13:04Z` = Mon `08:04 CT` / broker `09:04 ET` = `08:04 CT` agree; market
CLOSED, opens 13:30Z (08:30 CT, ~26 min). READ-ONLY + acks. **Sleep-hold's FIRST
NIGHT PROVEN:** cron.log `Mon 07/13 0:00:02 start → 0:10:23 end (exit 0) → report +
ping (curl 0)` — the AC-standby=Never hold held; nightly survived (no sleep-death).
Report `audit/reports/2026-07-13.md` (NIGHTLY, zero findings/zero alerts) untracked
→ sweep into tonight's ②. All three services @ `8d93621` (#1197 doc mover past
af1c5be, benign). H11 48h = 0 critical/high. entries_paused=false, fingerprint
intact (breaker tripped_at 07-08). Jobs since 05Z ALL succeeded incl.
intraday_risk_monitor ×1 — **the E8-3 fix's first night produced NO false failed/
partial; green is honest.**

**★ F-REPLAY-FK (NEW, MED-HIGH, evidence-integrity) — the first complete-tape day
opened with a BROKEN morning tape that stayed GREEN.** Today's morning
`suggestions_close` decision_run `2612fe81` status=**failed**, error =
`Commit failed: insert on decision_inputs violates FK decision_inputs_blob_hash_fkey
— blob_hash 82b5be18… not present in data_blobs` — a decision_inputs row references
a blob that was never stored. **The JOB stayed green** (`ok:true, processed:1,
failed:0`, no error). This is the LIVE composition of **F-E16-3 seam-4** (swallowed
replay-commit failure → job green; suggestions_close's `ctx.commit` result is NOT
surfaced — my #1188 patched only suggestions_open/midday) + the **v1.4 A5 note**
(`BlobStore.commit` permits partial batch failures → a blob batch partial-failure
leaves the input's blob absent → FK violation → the whole commit fails, tape lost).
**IMPACT:** the "complete tape" goal is broken at the DATA layer, not just coverage
— the morning capture is unrecoverable. **DECISION: FILE → EXPANDS tonight's ②** —
② surfacing the commit error turns this green→partial (VISIBLE, good) but does NOT
fix the FK root cause; ② must ALSO (or a paired item) fix blob-commit atomicity
(blobs committed before/atomically with inputs; no silent partial-batch). Likely
RECURS on today's 11:00 CT + 16:00Z scans — P1 tape pin is PREDICTED-TO-FAIL its
commit; watch it. · origin Mon 07-13 morning ritual (live).

**P10 (E16-3 before-picture) CONFIRMED LIVE:** today's only decision_run
(suggestions_close) = status failed, terminal_manifests **0** (the morning cycle
emits no `__decision__/ranked_candidates` feature, per L1) — the 2-of-7 + morning
gap is visible in today's data. The exact before-picture tonight's ② fixes.

**ANTI-DRIFT:** the v1.4 post-close queue (② E16-3 → ③ E19-2 → ④ F-A3-4 → tail) is
ledgered as TONIGHT'S build (07-12 v1.4 entry). The night-cap lanes (L1 honest-reds
· L2 migration/query drafts · L3 pin manifest) show NO artifacts I can find (only
doc #1197 reported) → **fold L1 (honest-reds: 14d succeeded rows carrying dropped
nested errors — the green→partial blast radius + dedup rider) into tonight's ② as
its opening step; L2/L3 absorbed into this ritual + the already-filed L1/L2 v1.4
specs.** TOOL-LIMITED (noted, not gaps): the E8-3 30d Railway correlation (2d) +
the [RISK_BASIS_SHADOW]/[BUCKET_SHADOW] line counts since d5edd50 (3a) are
per-deployment logs across ~7 recycles — not retrievable via the MCP; E8-3 is
structural-latent-confirmed (fix preventive; no intraday failed/partial last night).

**INTRADAY PIN CHECK-TIMES (grade at time):** P1 11:00 CT replay tape (⚠ predicted
FK-fail per F-REPLAY-FK) · P2 16:00Z E19-2 prediction (QQQ ≤2 clones / SOFI 0 /
clones ev_raw-NULL+no-basis+inherited-cal-raev) · P3 16:00Z un-muted shadows' first
breath · P4 16:00Z window heartbeats (F-WINDOW-1 silence check) · P5 E7 first real
ordering (if ≥2 survivors) · P6 PR2 first otc1-* (if entry) · P7 first typed-partial
watchlist · P8 close_reason e2e (if close) · P9 17:00 CT thesis tracker first
authoritative run (price_basis distribution + 6 Aug-21 in_progress + 81% held/
updated). A8 SOFI sentinel is now PER-TRACK (shadow-raw SOFI clear = DESIGNED; only
champion/calibrated clear alarms).

## 2026-07-13 (Mon 00:01 CT) — NIGHTLY AUDIT (v5.5, scheduled) — report audit/reports/2026-07-13.md

STEP-0: DB `05:01:16Z` = Mon `00:01 CT` / broker `01:01 ET` = `00:01 CT`, agree to
the second; market CLOSED, next open Mon 09:30 ET. Broker MCP surfaced (not blind).
Budgets: 6/12 SQL (1 counted 42703 miss) · 2/4 broker · 0/8 subagents.

**NO NEW FINDINGS — zero-alert night** (H11 48h critical+high = ZERO rows; weekend
scheduler silence is designed — `day_of_week="mon-fri"` applied to ALL SCHEDULES,
scheduler.py:250-255, verified). status:reported items: NONE.

**VERIFICATIONS CLOSED (status:verified, cite don't re-check):**
- H8: run-START = run-END = `8d93621` on all 3 services (SUCCESS, created 04:21:36Z
  > merge); ~12 Sunday movers all ledger-named; ~7 idle-weekend recycles, zero
  orphaned jobs (only job in window: phase2_precheck 05:00:04Z succeeded, post-recycle).
- F-E8-3 #1195 content-verified at deployed SHA (raise-not-empty,
  intraday_risk_monitor.py:673-683). ①b `_close_completed` (:159, wired :1509),
  ② W3 `bucket_enforcement_action` (wired paper_autopilot_service.py:1059), D②
  call-time flag read (fork.py:243-252, applied :340), ⓪ thesis `price_basis`
  threading (thesis_tracker.py:130-160; table 0 rows, born-honest) — ALL verified.
- Broker: equity=cash=OBP $2,067.86, book FLAT, unchanged to the cent from 07-12.
  Pool 8/8 (1W/7L) + fills 3/10-15 unchanged by construction (market closed).
- Breaker armed-quiet: entries_paused=false since 07-09 11:53Z; fingerprint stamp
  intact (`streak_breaker_state.last_tripped_fingerprint`, 3 ids, 07-08 trip).
  NOTE for future queries: the JSON key is `last_tripped_fingerprint`, NOT
  `window_fingerprint` (tonight's null-read was a wrong key guess, not a change).
- decision_runs=0 ✓ (pre-Mon-16:00Z correct) · position_thesis_outcomes=0 ✓ ·
  universe=78 ✓ · suggestions in window=0 ✓.
- FREE LOOK resolved-designed: phase2_precheck Mon-00:00-CT-only weekend pattern =
  `hour="*/6"` × the global mon-fri gate; handler self-expires >48h post-deploy.

**CARRIED (unchanged):** Mon 16:00Z pins (shadow heartbeats · decision_runs
rows-exist w/ 2-of-7 completeness caveat until queue-② · E19 clone-prediction grade)
· Mon 17:00 CT first thesis fill (expect price_basis) · queue ②③④ + tail ·
**A5 3-in-1(+1)+#1104 writer-hardening = 4th consecutive build-day slip** (meter
resumes 08:07 CT) · sleep-hold operator confirmation (next weekend night = live
test) · E6 runtime first-occurrence pin · prompt-STATE drift list for v5.6
(F-E8-3 shipped · ①b code-PASS · L1 8/8-SETTLED · W-clock restart SHA `d5edd50` ·
A7 3/10-15 wording). **Retirement watch: A1/A3/A6/A10 at 5 consecutive — a quiet
07-14 puts them at 6 (proposal territory, owner-gated).**

## 2026-07-12 (Sun ~22:4x CT, after PR-①) — DOC: browser doctrine encoded, 3 layers (PR #1197)

STEP-0: DB `03:36Z` = Sun `22:36 CT` / broker `23:36 ET` agree; market closed
(Sunday). Doc + local-config only — runtime-inert (verified: zero code
references to `.claude/launch.json` or `docs/runbooks/`; merge recycle is a
behavioral no-op).

- **Layer 1 — CLAUDE.md `## BROWSER USE`** (verbatim assessment block, after §1):
  browser = local UI acceptance · interaction-dependent research · API/receipt-
  vs-rendering comparison ONLY; evidence secondary to Supabase/Railway/Alpaca-
  MCP/direct APIs; never broker orders / prod config / persisted Alpaca login /
  nightly-audit browser requirements.
- **Layer 2 — `.claude/launch.json`**: local preview target, `apps/web`
  `pnpm dev` → `next dev`, port 3000 (verified: no override in repo), localhost
  only. `.gitignore` narrowed `.claude/*` + `!.claude/launch.json`
  (settings.local.json stays ignored, check-ignore-verified).
- **Layer 3 — `docs/runbooks/browser-verification.md`**: four operator-triggered
  procedures (morning page-truth check [ritual Part 2 extension; weekly +
  on-anomaly, NOT the nightly] · queue-⑤ make-vs-fetch recon [pre-build of the
  credit-probability build] · earnings-source evaluation [~1h; unblocks the P2
  versioned-earnings cohort] · broker-render spot-check [first-of-class only;
  session NEVER persisted]), each TRIGGER · STEPS · EVIDENCE ARTIFACT · EXTENDS.
- **Guards:** `audit/v5-prompt.md` UNTOUCHED — zero browser mentions confirmed
  (the assessment's explicit exclusion). No untracked `audit/reports/*.md` to
  sweep this session. **Evidence-artifact discipline (URL · timestamp · auth
  state · screenshot · DOM result · console/network errors · expected-vs-
  observed) applies to EVERY browser claim from here.**
- Marker: CLAUDE.md was ALREADY over its stated ≤40k header budget pre-PR
  (43,214 → 44,025 chars) — next doc-sync's item, not this PR's.

## 2026-07-12 (Sun ~22:4x CT) — BUILT: F-E8-3 sentinel typing PR-① (clock-gated) + L1/L2 Monday specs

STEP-0: DB `03:32Z` = Sun `22:32 CT` / broker `23:32 ET` agree; **~87 min to 00:00
CT nightly, ~57 to the 23:30 gate** — build settled ~22:5x CT, clear (sleep-hold
still operator-pending; doc/code recycle finished well before the nightly).

**PR-① — F-E8-3 []-sentinel TYPED at both origins (this PR).** `_fetch_open_positions`
(`intraday_risk_monitor.py:673`) `except → RAISE` (was `return []`) — the
safety-critical fix (a failed position read was becoming a green flat-book cycle,
blind to marks/stops/envelopes/force-close/tripwire). `get_active_user_ids`
(`utils.py:40-42`) `except → RAISE` (was `return []`) — the DISCOVERY origin (a
15-caller shared util; a discovery DB failure SHOULD fail the job, not no-op for
all users; its error string is the v1.4 Railway cite); the monitor's
`_get_active_user_ids` un-swallowed (removed the `except: return []` that would
re-catch the util's raise). Wires into #1186: all-users-unreadable → job raises →
failed_retryable; a per-user read failing → users_failed → typed partial. A
genuinely-empty book (query SUCCEEDS → []) STAYS green — only FAILED reads go
non-green. **ORIGIN-TO-TOP TEST (first §9-doctrine application): the Supabase query
THROWS in the fixture; `_check_user` + `_fetch_open_positions` +
`get_active_user_ids` are REAL (NO intermediate mock); assert `execute()` RAISES /
the util raises. Both directions pinned by ORIGIN (throw vs empty-SUCCESS), not
intermediate inspection.** Tests 7 new + E8 seam 4/4 green. **⚠ SENTINEL-DISEASE
CLASS inventory: members = `_fetch_open_positions` + `get_active_user_ids` (both
closed here) + F-A3-4's `fetch_live_outcomes` ([]-on-failure → green
insufficient_data, SAME fix shape, pending queue-④).** E8's 3rd layer closed at the
origin. H8 SHAs recorded in the session summary.

**L1 — E16-3 ② IMPLEMENT-SPEC (filed).** NO shared `_early_return` helper —
`_build_cycle_metadata` (`:2032`) doesn't receive accepted/rejection_stats/counts.
Wire 5 explicit `_capture_decision_manifest` calls before the returns at `:2295`
(micro_tier), `:2334` (capital-policy), `:2418` (risk-budget), `:2814`
(no_candidates), `:2857` (scanner_failed, in the except); `rejection_stats` bound
only at sites 4/5 (else `None`). Roll-up: `_persist_error_rollup`
(`suggestions_open.py:32-40`) += `int(counts.get("errors") or 0)` — carries #1188's
`replay_commit_error`; the runner classifier reads top-level `counts.errors` →
partial. Morning: `run_morning_cycle` emits NO `__decision__` feature → add one
after the insert block + hoist `cycle_date`. Size M; **riskiest = the roll-up
green→partial blast radius — validate recent `cycle_results[].counts` before
shipping.**

**L2 — E19-2 ③ DESIGN-SPEC (filed).** **Option B** — widen the fork source read
(`fork.py:56`) with a SEPARATE query `status='NOT_EXECUTABLE' AND
blocked_reason='edge_below_minimum' AND ev_raw IS NOT NULL` (NOT_EXECUTABLE rows
ARE inserted at `workflow_orchestrator.py:3909-3927`, only invisible to the fork's
pending/staged filter) + raw-side viability recompute in
`_clone_suggestion_for_cohort`; **recompute `risk_adjusted_ev` on the clone basis
(`fork.py:353` currently INHERITS calibrated = the bug)** + stamp `ev_basis`.
**Migration: YES — one column `trade_suggestions.ev_basis text` (backfill
'calibrated' for the v3 `COALESCE(ev_raw,ev)` honesty).** Champion blast radius ZERO
IFF the widened rows stay OUT of the `:81-87` champion-tag loop (**the named trap** —
a distinct variable, never entering the tag loop / champion decision-log). Option B
touches no workflow_orchestrator scoring line → champion byte-identical. ~2 evenings.

**QUEUE (Monday post-close):** ② E16-3 → ③ E19-2 → ④ F-A3-4 (prequential fetch,
same sentinel fix shape) → tail (A9-5 · F-WINDOW-1 · F-A10-4). Ritual pins filed.

## 2026-07-12 (Sun ~22:1x CT) — ADJUDICATED: external full audit v1.4 (5th engagement) — READ-ONLY, doc writes only

STEP-0: DB `03:11Z` = Sunday `22:11 CT` / broker `23:11 ET` = `22:11 CT`, agree
(UTC rolled to Mon `dow=1`, CT wall-clock Sunday night — the roll, flagged). Market
CLOSED. Report swept to `docs/review/external-full-audit-v1.4-2026-07-12.md`. Build
NOTHING; verdicts + tonight-runnable checks + Monday pins + backlog diff.

**SCORECARD — v1.4 is the sharpest adversarial pass on OUR OWN work: THREE
same-day seam kills (E8-3 / E16-3 / E19-2), ALL one layer below this weekend's
route-driving tests.** Free-look precedent extended (retry provenance + typed-column
#5 near-miss, neither promoted). Owned honestly below.

**SHARPENED DOCTRINE (→ CLAUDE.md §9, landed this session):** "Inject the failure
at its ORIGIN, assert the truth at the TOP — a test spanning all layers cannot be
beaten by the layer below; mock-replacing an intermediate function forfeits every
layer beneath the mock." All three kills are this class: E8-3 mocked `_check_user`
(inner `_fetch_open_positions` []-swallow survived); E16-3 tested the manifest
helper (not the 5 uncovered returns + classifier); E19-2 called the cloner with an
already-eligible source (never crossed the calibrated gate).

**PROMOTED FAILs — VERIFIED against code + this DB:**
- **F-E8-3 (CRITICAL, promoted; 3rd E8 layer).** `_fetch_open_positions`
  (`intraday_risk_monitor.py:646-675`) wraps both the portfolio + position queries
  in one try; `except → logger.error("[RISK_MONITOR] Failed to fetch positions") +
  return []` — a DB failure is indistinguishable from an empty book. `_check_user`
  consumes [] as authoritative-empty; `_get_active_user_ids` (`:1680-1692`) has the
  same `except: return []` (→ green `status=no_users`). My #1186 typed the OUTER
  loop; this INNER read swallows one layer below → one Supabase failure skips
  marks/stops/loss-envelopes/force-close/two-position-tripwire for the WHOLE
  account while q15 reports green. **CENSUS: 639 succeeded intraday rows/30d, book
  FLAT throughout → the []-sentinel is UN-disambiguated in job_runs (a failed read
  and an empty book both show positions:0); only the Railway error-string
  correlation disambiguates, and 30d isn't tool-runnable (per-deployment logs).
  Structural-latent, STILL CRITICAL — the flat book bounds today's exposure; the
  moment a position opens Monday, a failed read = blind protection that afternoon.**
  → queue P0-①.
- **F-E16-3 (HIGH, promoted; 3rd exclusion-integrity note on E16).** `_capture_
  decision_manifest` reaches only 2 of the 7 semantic terminal returns (the reasons
  are enumerated at `workflow_orchestrator.py:2048-2050`): covered =
  `no_suggestions_after_gates` + created; MISSING = `micro_tier_position_open`,
  `capital_scan_policy_block`, `global_risk_budget_exhausted`, `no_candidates`,
  `scanner_failed` (the early-return helper at `:2034` was the single wiring point
  I missed). The morning cycle (`suggestions_close`) emits NO terminal feature.
  And `_persist_error_rollup` (`suggestions_open.py:26-40`) sums ONLY
  `rejection_persist_failures`, NOT the generic `counts.errors` where my #1188
  `replay_commit_error` lands → the runner still classifies succeeded.
  **CENSUS: commit-err-green = 0 (no commit failures yet).** **CORRECTION: #1188's
  "EVERY return / COMPLETE / Monday's tape is COMPLETE" language is FALSE — the
  tape is complete only from queue-②'s SHA.** → queue P1-②.
- **F-E19-2 (HIGH, promoted; the selection-biased un-mute).** The fork runs
  post-cycle (`suggestions_open.py:159-170`) and queries only champion rows
  `status IN ('pending','staged')` (`fork.py:44-56`); a calibrated-rejected
  candidate has `status=NOT_EXECUTABLE` (`workflow_orchestrator.py:3750-3767`) →
  never reaches `_clone_suggestion_for_cohort`. So my #1190 raw-EV un-mute breathes
  ONLY for champion-eligible candidates and SYSTEMATICALLY EXCLUDES the divergence
  cases (SOFI raw 39.88/cal 19.94 dies at `edge_below_minimum` → 0 clones; QQQ raw
  37.46/cal 18.73 survives → up-to-2 clones). Surviving clones mix bases (raw `ev`
  + inherited calibrated `risk_adjusted_ev` + calibrated pre-clone snapshot; no
  `ev_raw`/`ev_basis` persisted). **CORRECTION: D②'s un-mute is PARTIAL until
  queue-③ — entry-rate evidence excludes the divergence cases; the 07-12 un-mute
  SHA `9a540ce` stamps the FLAG, ③'s SHA stamps the FULL experiment.** → queue P1-③.

**OTHER VERDICTS:**
- **F-A3-4 (HIGH-evidence, CONFIRMED-structural, NIL current impact).**
  `fetch_live_outcomes` (`prequential_validator.py:190-239`) ignores `window_days`,
  applies neither `CALIBRATION_EV_EPOCH` nor the corrupted-P&L floor, and returns
  [] on failure → green `insufficient_data` (the SAME []-sentinel disease as E8-3 —
  note the class link). **CENSUS: all_live=8, pre_epoch=0, pre_corruption_floor=0 →
  the missing filters have ZERO current numerical impact (refutes the report's
  "12.5% flip" for now); the structural mismatch + []-green disease stand.** →
  queue P1-④ (small).
- **F-A9-5 (MED, CONFIRMED-by-cite).** `_log_cohort_decisions` compares dollar `ev`
  to the score threshold (`fork.py:466-477`) while the real filter compares
  `sizing_metadata.score` (`:233-236`) → `ev_below_min` is an evidentiary lie
  (routing byte-correct). policy_decisions = 57 rows/30d; the join check is
  Monday-runnable. → queue P2 (rides ③'s fork territory if clean).
- **F-WINDOW-1 (MED, CONFIRMED-by-cite).** Heartbeat coverage: only W4
  (APPLY_ORDER) + a generic post-portfolio EXECUTOR_SHADOW; W1 no gate-site beat,
  W2 no per-consumer zero-eval beat, W3 pre-portfolio miss + no candidate/
  reservation identity, no shared cycle ID → W5 unjoinable. → queue P2 (the
  arm-evidence repair's OWN second-pass repair; **the W-clocks do NOT reset again
  for observability-only additions, but the ARM decisions wait on joinable
  evidence** — stated in the clocks section).
- **F-A10-4 (LOW, CONFIRMED-by-cite).** `expiry >= today` → `in_progress` until the
  next weekday run (Friday expiry → terminal Monday 17:00 CT, ~72h); evidence
  latency only (Monday still scores the exact expiry close). → queue P2; the Aug-21
  rows are the live test (Fri-vs-Mon check filed).

**EXCLUSION TABLE:** E8 FAIL (3rd layer) pending-①; E16 FAIL pending-②; E19
partial-FAIL pending-③; E14 PASS (trust from `74b7170`); E6/①b code-PASS at
`a6e0cb9` (runtime first-occurrence pin remains); E17 narrow-PASS + fresh adjacent
F-A3-4; E1-E5/E7/E9-E13/E15/E18 as prior.

**VERDICT PARAGRAPH (quoted):** "downstream conversion/evidence-integrity problem,
amplified by capital friction" — predictions directionally promising (13/16 theses
81%), live 1W/7L −$178; execution/exit measurement + 4-leg economics at ~$2,068
fail to convert. Stop territory stays Phase-3's (3/10-15 instrumented fills). E8's
failed-read typing is the single first change.

**TONIGHT-RUNNABLE RESULTS:** E8 census 639/flat (un-disambiguated) · E16
commit-err-green 0 · A3-4 pre_epoch 0 (nil impact) · A9-5 policy_decisions 57/30d
(join Monday). **MONDAY PINS (verbatim, filed):** (h/E19) first post-`9a540ce` scan
— rows `ev_raw≠ev`+`NOT_EXECUTABLE`+`edge_below_minimum` producing NO shadow verdict
(SOFI predicted); clones carry `ev_raw` NULL + no basis stamp + calibrated rank; QQQ
≤2-clone upper bound — grade the prediction · (e/E16) post-#1188 `decision_runs` ↔
exactly one terminal `decision_features(ranked_candidates)` per run, group misses by
cycle reason (predicts the 5 midday + all morning) + succeeded jobs with nested
`replay_commit_error` & top-level `counts.errors=0` · (b/E8) Railway
`"Failed to fetch positions"`/`"Error fetching active users"` ↔ same-cycle succeeded
job_runs (needs log retention) · (F-A10-4) Aug-21 Fri-after-17:00 `in_progress` vs
Mon-after-17:00 terminal+`expiry_close`.

## 2026-07-12 (Sun ~10:xx CT) — BUILDS ③→④→D② (+①b optional) + lanes L1/L2/L3

STEP-0 (premise correction): prompt said "Sunday-evening"; DB `14:41Z` = Sunday
`09:41 CT` / broker `10:41 ET` = `09:41 CT` agree — it is Sunday MORNING. Nightly
00:00 CT Monday → ~14h20m runway (sleep-hold NOT yet set — finish well clear).

**LANE L1 — 8/8 TRIGGER CORRECTION (SETTLED, not newly-actionable).** Verified by
query: calibration is OUT of raw mode — `ev = 0.5 × ev_raw` (ratio 0.5000) on 07-10
(IRON_CONDOR 18.73/37.46 + LONG_CALL_DEBIT 19.94/39.88); 07-07→09 were ratio
1.0000 (raw). So the ×0.5 floor clamp APPLIES since 07-10. The 8/8 milestone's two
gate-questions are ALREADY DECIDED (07-09): floor-HOLD (revisit at ~15-20 live
closes — 8 closes / 1W-7L is too thin+loss-heavy to trust un-clamping) + winsorize
NO-ACTION (live-only #1076 already excludes the shadow outliers). **The 07-12
FULL's "newly-actionable" flag is CORRECTED → SETTLED.** → prompt v5.5 STATE line
so no future nightly re-flags it (L2 carries it into the backlog; the prompt edit
is the operator's, flagged).

**LANE L3 — W2b SITE MAP (spec filed, TWO PRs).** Utilization: the flip threshold
is `cap*pool − committed` (= `cap*(committed+obp) − committed`), a CLEAN binary at
`utilization_gate.py:420` (verified vs the boundary tests: cap 0.85, committed 600,
obp 400 → thr 250; premium 149 ALLOW vs honest 372 BLOCK = the QQQ-IC case).
Minimal diff: a `candidate_cost_bases()` splitter + two optional kwargs on
`evaluate_entry` + relocate the log after `:414` + one caller update — effort M,
ship ALONE. Allocator (`portfolio_allocator.py`): the open-book is a CONTINUOUS
sizing input (used_dollars re-slices remaining_envelope, `:276-333`) — **would_flip
is NOT the right primitive**; instrument dual-basis instead (n_funded_current vs
_honest + available_envelope pair), keep would_flip None. → **W2b = two PRs**
(utilization threshold first, allocator instrumentation follow-up). Filed.

**PR-③ — REPLAY TERMINAL-CAPTURE CONTRACT (E16 correction) BUILT (this PR).** Four
seams closed: (1) a shared `_capture_decision_manifest()` fires at EVERY return of
run_midday_cycle — the NO-TRADE/zero path (`:~3790`) now emits the manifest with
honest zeros + exit_reason + `is_zero_cycle`; (2) rejected tail via
`rejected_summary` = rejection_stats.to_dict() (reason→count) in the manifest; (3)
cache-HIT inputs recorded at the consumption boundary — chain
(`market_data_truth_layer.py:1437`, `_record_option_chain_to_context` before the
cached return) + snapshot v4-quality-cache (`:~1008`, `_record_snapshot_to_context`
on hit; blob store dedups); (4) commit health — `suggestions_open` captures
`ctx.commit()`'s return and surfaces an error into `counts.errors` +
`replay_commit_error` (the F-A4-1 contract, never silence). Fail-soft throughout
(capture failure cannot break the cycle; the manifest helper + cache-hit records
are try-wrapped). Keeps the `ranked_candidates` feature key (PR-2 #1175 test +
byte-compare continuity). Tests 4/4 (zero-cycle honest-zeros, accepted-ranked +
rejects, replay-off no-op, capture-failure fail-soft) + PR-2 replay 3/3 +
truth-layer/replay-store 28/139-skip green. **E16 corrected at this SHA; Monday's
tape is COMPLETE from the first scan** (yesterday's rows annotated known-partial;
the Monday capture pin un-re-scopes from "rows+timing only" to full completeness).
**MERGED #1188 `9be25c4` + H8 VERIFIED** (BE `108f5b6c` / worker `d1148556` /
worker-background `922db44e`, all @ `9be25c4`, created 14:52:04Z).

**PR-④ — CLONE RISK NORMALIZER + 33-ROW BACKFILL BUILT (this PR).** E14: the
Policy-Lab clone (`_clone_suggestion_for_cohort`, fork.py:242 — VERIFIED the ONLY
cloner; the autopilot cohort refs are reads) copied the SOURCE's max_loss_total
unchanged into sizing_metadata (mis-scaled) and omitted the top-level column
(→ NULL). FIX: compute `clone_max_loss_total = round(max_loss_per × contracts, 2)`
(max_loss_per = source_total/source_contracts) and emit it as BOTH the typed
top-level `max_loss_total` AND `sizing_metadata.max_loss_total` + a
`max_loss_total_basis` provenance ('rescaled_from_source_per_contract'). UNKNOWN
stays EXPLICIT (None + 'unknown_source_no_max_loss_total') — never a fabricated 0,
never a NULL typed column beside a lying JSON total. Tests 3/3 (rescaled typed==JSON
· unknown→explicit-None · scales-with-clone-contracts) + existing fork 2/2 green.
**SUPERVISED BACKFILL — 33 rows (neutral 23 + conservative 10), ALL derivable,
EXECUTED + read-back**: typed = round(sizing.max_loss_total / original_contracts ×
contracts, 2), JSON set consistent, basis='backfilled_from_source_suggestion'
(e.g. conservative 588/4×8 = 1176 — the large totals reflect honest shadow-cohort
synthetic sizing). Read-back: `still_contaminated=0` (was 33) · `backfilled=33` ·
`typed_equals_json=33`. **⭐ SHADOW RISK EVIDENCE TRUSTWORTHY FROM THIS SHA** — the
pending clock-reset line (D② sequencing) COMPLETES: W2/W3 shadow-cohort risk
evidence + D②'s shadow un-mute may count from here (forward clones are born
correct; the 33 historical rows are backfilled). **MERGED #1189 `74b7170` + H8
VERIFIED** (BE `9d621ced` / worker `f7b4e586` / worker-background `785ce053`, all @
`74b7170`, created 14:59:07Z).

**PR-D② — SHADOW UN-MUTE ON RAW EV BUILT (this PR).** The decision D② implementation:
`_clone_suggestion_for_cohort` (fork.py) now sets a shadow clone's `ev` to the
source's RAW `ev_raw` (not the champion's calibrated `ev`), gated by
`_is_shadow_raw_ev_enabled()`. Flag `SHADOW_RAW_EV_ENABLED` **default ON** (empty/
unset → ON; explicit 0/false/no/off → inherit calibrated) — a REVERT lever, not an
observe gate (shadows are simulated, no live money; the flag defaults to the
active state, so no env pre-staging needed). Every clone is a shadow (the champion
is tagged in place, never cloned) → raw applies to all clones. Fallback to the
calibrated `ev` when `ev_raw` is absent (H9 — no fabrication). `risk_adjusted_ev`
inheritance unchanged (the decided basis change is the ENTRY EV; the champion path
is untouched — it is the source, not a clone). Tests 4/4 (default-ON→raw · empty→ON
· explicit-off→calibrated · missing-ev_raw→honest-fallback) + normalizer 3/3 +
fork 2/2 green.
**DECISION D② ANNOTATIONS (verbatim):** shadows score on RAW ev from `74b7170`
(PR-④'s SHA is the trustworthy-from anchor; this PR is the un-mute itself);
promotion ENTRY-RATE comparisons carry the different-EV-bases caveat; OUTCOME /
thesis comparisons are basis-INDEPENDENT; the experiment layer breathes from
Monday's first 11:00 CT scan (fork runs post-scan; the neutral/conservative clones
emit raw-EV rows).

**PR-D② — MERGED #1190 `9a540ce` + H8 VERIFIED** (BE `25ef4d5d` / worker
`b1a6c13c` / worker-background `50b85631`, all @ `9a540ce`, created 15:05:47Z).

**PR-①b — F-A8/E6-edge (needs_manual_review costumed as routed success) BUILT (this
PR).** The runway held → the optional fourth build shipped. `_close_position`
(paper_exit_evaluator.py:2245) DISCARDED submit_and_track's return and
unconditionally reported `routed_to='alpaca'`; a terminal `needs_manual_review`
submit failure therefore read as a routed success → the monitor emitted
"Force-closed", counted force_closes_submitted, could write cooldown, and
suppressed the same-cycle retry (E6's no-phantom-fill invariant still held — this
is a telemetry/accounting lie, not a ghost fill). FIX (2 sites, the operator's 3
functions): (1) `_close_position` captures the return; on `status==
needs_manual_review` returns a NOT-completed sentinel `routed_to='needs_manual_
review'` (position held OPEN for review); (2) the monitor's success accounting is
now the extracted, testable `_close_completed(result)` — `needs_manual_review`
joins `deferred_uncorroborated`/`unknown_reconciling` in the not-completed set, so
no force_close count / cooldown / same-cycle suppression. BYTE-IDENTICAL for every
other route (only needs_manual_review changed). The evaluator's own scheduled-exit
path (:1385) is routed_to-agnostic → no regression. Tests 4/4 (`_close_completed`:
needs_manual_review→False · deferred/unknown→False · alpaca+5 others→True
byte-identical · None/missing→True) + E8 4/4 + force-close 16/16 green. MERGED +
H8 recorded in the session summary.

**SESSION STATE (CLOSED):** ⓪①②③④D②+①b all shipped + H8 (⓪①② Sat/Sun; ③④D²①b Sun
AM — SHAs `27715ee`/`3ef3c83`/`d5edd50`/`9be25c4`/`74b7170`/`9a540ce`/`a6e0cb9`).
Lanes: L1 (8/8 SETTLED — calibration out of raw mode) + L3 (W2b two-PR site-map
spec) filed; **L2 (backlog rewrite) SHIPPED** — post-build status block prepended,
stale #1169 "gate cleared" line corrected, decision/arm-clocks section added.
REMAINING (Monday+): ⑤ credit-probability source (gates D④) · ⑥ partial-close
custody (trigger-gated) · ⑦ P2 tail · W2b (two PRs) · the prompt v5.5 STATE edit
for the 8/8-SETTLED line (operator). Sleep-hold is the operator's action tonight.

## 2026-07-12 (Sun) — GOs RECORDED + Part-3 BUILD QUEUE (⓪ thesis-basis shipped; ①②③④ sequential)

**FOUR OWNER DECISIONS — CONFIRMED GO (verbatim):**
- **D① — GO as recommended:** KEEP Calendar & Clock one more cycle (F-A10-1 proves
  it's earning; counter 4/6; DST 11-01 pending). QUEUE A11's Security & Credential
  Hygiene lens for the NEXT rotation (strong debut, weak replace-half — queue,
  don't replace).
- **D② — GO:** un-mute shadows at queue-④'s SHA; basis DECIDED = **SHADOWS SCORE
  ON RAW EV (the simple split).** Rationale: evidence volume is the binding
  constraint; the honest cross-cohort comparison happens at OUTCOMES (closes,
  thesis accuracy, per-contract-normalized promotion gates) which are
  basis-independent — NOT at entry EV. Promotion annotation: cohorts run different
  EV bases from that SHA; ENTRY-RATE comparisons carry the caveat, OUTCOME
  comparisons don't.
- **D③ — GO the PACKAGE, not the arm:** queue-② (arm-evidence repair) + the W3
  double-polarity fix as its precondition, ONE PR; W2/W3/W4/W5 clocks restart at
  that SHA. No arm this week.
- **D④ — GO queue-⑤'s spec:** independent terminal/breakeven probability source;
  production-route test asserting NONZERO EV + all gates unchanged; observe/
  replay-only start. Next week's strategy-side build. The 2-leg cohort stays gated
  on it.

**ESCALATION RESOLVED — F-A4-SLEEP-DEATH → DEAD-MAN'S FIRST LIVE CATCH.** The
Saturday 07-11 healthchecks DOWN email ARRIVED — the dead-man is ARMED and
WORKING. Saturday's sequence was the design executing: run died mid-sleep → no
report file → no ping → DOWN fired. The control built after the silent-empty class
caught the very next miss. Remaining fix = SLEEP-HOLD only (operator action
tonight: AC sleep→Never or the task execution-time request; WakeToRun starts the
run, the sleep-hold lets it finish). FILED P3: the DOWN email can't distinguish
never-started from died-mid-run (cron.log start-no-end answers it on inspection —
nice-to-have, not a gap). FILED response-layer note: a DOWN email is a same-day
look, operational habit, no build.

**TWO LEDGER CORRECTIONS (operator-supplied):**
- **A7 counter = 3/10-15 INSTRUMENTED fills** (NOT 9/10 — the v1.3 external prompt
  conflated all-time closes with #1102-instrumented fills). Fix the v1.3 prompt's
  A7 line when it's next touched.
- **A5 noise names its dropped item precisely: the #1104 writer-hardening NEVER
  SHIPPED** — orphaned when F-A4-1 absorbed the A4-half and the obs-remainder
  re-scoped to five items; it lost 5 MORE rows this week. Provenance =
  the-re-scoping-drops-an-item failure mode; file it with that so it stops
  slipping.

**BUILD ORDER (confirmed):** ⓪ thesis-basis → ① E8 per-user seam (+ F-A8/E6-edge
rider, same-PR-if-clean/own-PR-if-not) → ② arm-evidence repair + W3
double-polarity (clock-reset PR; **test matrix NON-NEGOTIABLE: armed-state
unknown-risk → blocked/not-armable, NEVER silent-zero-proceed**) → ③ replay
terminal contract → ④ clone normalizer + 33-row supervised backfill. ⓪①② =
must-lands today; ③④ hold to Monday post-close at no cost. Strictly sequential, H8
between each.

**PR-⓪ — thesis price-basis disclosure BUILT (this PR).** F-A9-THESIS-BASIS:
`_underlying_at_expiry` (thesis_tracker.py) now returns
`(close, price_basis, bar_date)` — `expiry_close` (authoritative) / `fallback_
prior_bar` (≤7d stale, DISCLOSED with the bar date inline in thesis_basis) /
`unknown` (H9 non-fabricated); run() threads it into the new `price_basis` column
+ the non-scoring states (`no_expiry`/`in_progress`). Migration `20260712123000_
thesis_outcomes_price_basis` (ALTER … ADD COLUMN price_basis text) applied +
tracked (version `20260712120301`, col_ok=1) + read-back BEFORE merge; table 0
rows (no backfill; born-honest before the Mon 17:00 CT first authoritative fill).
Observe-only, modulates nothing. Tests 5/5 (exact / fallback+date / post-expiry-
bar-excluded / unknown-not-fabricated / feed-failure→unknown). **MERGED #1185
`27715ee` + H8 VERIFIED** (BE `341a5f7e` / worker `f4efe582` / worker-background
`81d48f7c`, all @ `27715ee`, created 12:10:01Z).

**PR-① — E8 per-user seam BUILT (this PR).** F-A4-E8: `execute()` now COUNTS
per-user failures (`users_failed`) — ALL users failed → RAISE (runner records
failed_retryable; on the 1-user account a single failure IS a complete cycle
failure); MIXED → typed PARTIAL (`users_failed` + `counts.errors` populated →
`_classify_handler_return` returns 'partial', was 'succeeded'); zero-failure
classification byte-identical (succeeded). The route-driving test drives
`execute()` END-TO-END through a `_check_user` failure (NOT the source-pin of the
outer raise — the sharpened doctrine line). Tests 4/4 route + existing
typed-outcome 15/15 + force-close/intraday 39/39 green. **RIDER DECISION:
F-A8/E6-edge is OWN PR (PR-①b), NOT same-PR** — `submit_and_track` cleanly returns
`{status:needs_manual_review}` (+ already fires a critical alert) but making it
not-read-as-success spans 3 functions across 2 files (`_close_position` return →
`_execute_force_close` success mapping → the monitor's force_closes_submitted/
cooldown/closed_in_this_cycle accounting) — a distinct seam; entangling it would
broaden the critical fix's blast radius. **MERGED #1186 `3ef3c83` + H8 VERIFIED**
(BE `f1184417` / worker `7fcd9f82` / worker-background `b8f35a7b`, all @ `3ef3c83`,
created 12:17:54Z).

**PR-② — ARM-EVIDENCE REPAIR (the clock-reset PR) BUILT (this PR).**
- **W3 (safety non-negotiable, DONE):** bucket_control unknown-risk is EXPLICIT —
  `_risk_from_fields`/`position_risk_usd`/`candidate_risk_usd` now return
  `(usd, legacy, is_unknown)` (never a silent $0); `evaluate_bucket` surfaces
  `unknown_risk_present`/`unknown_open_count`/`equity_readable`/`not_armable`; a new
  pure `bucket_enforcement_action(decision, armed)` is the single seam — **ARMED +
  not-armable (unknown risk OR unreadable equity) → BLOCK** (`bucket_not_armable_
  unknown_risk`), the L3 equity-unreadable polarity folded in; OBSERVE → alarm on a
  cap breach only. Caller (`paper_autopilot_service.py:1038`) rewired through it.
  **The non-negotiable test is explicit** (armed+unknown → block; observe+unknown →
  proceed-logged; armed+cap → block; armed+unreadable-equity → block).
- **W4 (DONE):** `_top_n` serializes the full identity tuple (ticker, strategy, id,
  legs/expiry fingerprint, score); `_order_key` compares STRUCTURAL ordering (score
  dropped) so a same-ticker structure swap flips `would_differ` (the QQQ ×4 blind
  spot). Test proves ticker-only agrees while the structural key differs.
- **W2 (PARTIAL — clean parts DONE, one rider):** stable identity (suggestion_id/
  cohort) added at all 3 callers; the DECISION threshold passed at the RBE site
  (`deployable_capital*2`, in scope) → would_flip REAL there. ⚠ **W2b RIDER
  (deferred, documented):** the utilization would_flip threshold (headroom) needs
  committed+OBP from `evaluate_entry`, a log-RELOCATION to the decision site; the
  allocator open-book value is a CONTINUOUS budget input (would_flip is not a
  binary concept there — the delta is the signal). Not entangled into this
  safety-critical PR.
- **Heartbeat (DONE):** `log_shadow_heartbeat(window, evaluated, …)` fires per-cycle
  EVEN AT 0 — wired at the APPLY_ORDER scoring seam (every scan, pre-early-return)
  + the executor per-cohort loop (`EXECUTOR_SHADOW`, covers BUCKET+RISK_BASIS). Marker
  silence is now diagnosable (ran-saw-nothing vs did-not-run).
- Tests: 13 new (arm_evidence_repair) + calibration_apply_ordering 11/11 +
  bucket_control (4 arity-updated) + consumers 162/4-skip green.
- **⚠ CLOCK RESET (ledgered): W2/W3/W4/W5 arm clocks RESTART at PR-②'s SHA.** This
  week's shadow logs are evidence-defective for the arm decisions; W1's clock
  stands. W2b (utilization/allocator would_flip) + the F-A8/E6-edge rider (PR-①b) +
  PR-③ replay-terminal + PR-④ clone-normalizer HOLD to Monday post-close (operator
  sanctioned; ⓪①② were the must-lands). H8 recorded in the session summary.

## 2026-07-12 (Sun ~06:3x CT) — FULL-REPORT TRIAGE + OWNER DECISIONS PRESENTED (awaiting operator confirmation before any build)

STEP-0: DB `11:31Z` = Sunday `06:31 CT` / broker `07:31 ET` = `06:31 CT`, agree to
the second; NO UTC-roll bite (both are 07-12). Market CLOSED.

**PART 1 — the FULL ran correctly.** cron.log: 07-12 `start 0:00:18 → end (exit 0)
0:17:51 → ping sent (curl exit 0)` = scheduled ✅ FULL mode ✅ (header "three
passes per area") all 11 areas ✅ ping GREEN ✅. Expected-state handling WORKED:
breaker 2nd designed suppression, flat book (0 positions), four-source agreement
everywhere — the inverted block is functioning. The FULL respected the v1.3
exclusion floor: **E8/E12/E14/E16/W2-W5/F-A2-1 CONVERGED (cited, NOT re-found)** →
the ①-④ queue owns them.

**TRIAGE TABLE (NEW findings only; CONVERGED = above):**
| Finding | Sev | Path | Decision |
|---|---|---|---|
| F-A9-THESIS-BASIS — thesis_tracker `_underlying_at_expiry` (thesis_tracker.py:55-57) grades a ≤7d-stale fallback bar as the expiry price + persists a TERMINAL hit/miss with NO price-basis field; thesis_basis prints it as expiry price while claiming "NEVER fabricated H9" (thesis_scoring.py:20,88-121) | MED | Evidence — the standing thesis-hit metric the owner steers by; NOT live capital; 0 rows yet | **FIX-TODAY (recommend), PENDING OWNER GO** — time-sensitive: first authoritative fill Mon 17:00 CT; 1 field + 1 line, observe-only, born-honest if shipped first; same 2 files as F-A9-1. NOT in the ①-④ queue → a PR-⓪ insertion candidate. |
| F-A4-SLEEP-DEATH — 07-11 nightly machine-sleep kill (start-no-end; end-marker unconditional so external kill); 4th weekend (06-14·06-20·06-30·07-11); WakeToRun holds no wake-lock | — | Evidence-integrity (audit coverage); NO repo code | **ESCALATE (operator)** — (1) confirm the 07-11 healthchecks DOWN email ARRIVED (else dead-man unarmed); (2) ES_SYSTEM_REQUIRED sleep-hold or mid-run-safe schedule. |
| A5 observability noise — 07-10 14:02Z 5-row loss (#1104 residual, 2nd occ, 11 cumulative) re-egressed hourly ×9; `ops_output_stale` ×10 flat-book false HIGH | MED | Alert-hygiene | **FILE (already filed) — ⚠ slipped THREE build days** (07-08→07-12); the only found item not converging. Owner: give it a slot (fold iv_daily_refresh EXPECTED_JOBS half). |
| `bucket_exposure_would_block` severity='warning' → no egress/relay despite the "#1139-class alarm" comment (paper_autopilot_service.py:1063-64) | LOW-MED | Evidence (observe-week relies on it) | **FILE** — fold into the composed observe→enforce packet (D③); owner READs logs meanwhile. |

**A11 FULL-FORMAT DEBUT — GRADE: STRONG, well-formed (all 4 components present).**
Proposed lens = **SECURITY & CREDENTIAL HYGIENE** (secret scanning · git-history
exposure · key rotation · RLS/permission surfaces · MCP/tool allow-lists).
Examines: credential/permission-surface drift nothing else owns. Ten miss: the
incumbent watches TIME boundaries only. Concrete finding-shaped example: F-FREE-1
checked-in Supabase keys (found by an UN-lensed free look, not a charter) + its 2
operator tails (history cleanup + secret-scanning) still OPEN/unaudited + the
nightly's own allow/deny list is a growing security surface with no reviewer.
Replace-vs-queue: argues the incumbent "completed its headline (winter-close),
look-list in maintenance, marginal yield falling." **My grade:** a genuinely
uncovered surface + a real finding-example → QUEUE-worthy. BUT the replace half is
WEAK — F-A10-1 (summer warm-up blind, HIGH) shows Calendar & Clock is STILL
finding, and A10 still guards DST 11-01. Not a clean retirement. → feeds D①.

**A7 COUNTER RECONCILIATION (corrects the prompt's "9/10"):** two different
counters — all-time live closes = 9 (v1.3's "9/10") vs the #1102-instrumented
close-fill-gap counter = **3/10-15** (the meaningful A7-reinstatement gate, needs
the fill-quality instrumentation). By the correct counter A7 is FAR from
reinstatement (3/10-15), NOT near. The causal close-quality charter reshape
happened in v1.3, not tonight (tonight A7 = one dormant line). PASS-3: all EARNING
except A5 SLIPPING; NO area at 6, NO retirement proposed. **Anti-drift:** Saturday's
FIX-TODAYs all shipped (#1174-#1182, ledgered); the ONE item pending >2 days = the
3-in-1 observability PR (07-08→07-12).

**PART 2 — FOUR OWNER DECISIONS PRESENTED (my recommendations; AWAITING operator
confirmation — NOTHING built until the GOs are recorded):**
- **D① A10 ROTATION.** REC: **KEEP Calendar & Clock one more cycle** (F-A10-1 HIGH
  proves it's still earning; A10 counter=4 not 6; DST 11-01 still to guard) +
  **QUEUE the SECURITY lens** (A11's proposal, strong) for the next rotation.
  Owner's call.
- **D② SHADOW UN-MUTING.** REC: **un-mute at queue-④'s SHA** (after the clone
  normalizer) — until then new shadow evidence is born risk-contaminated (E14
  census 33/33 non-champion typed-null). Promotion-comparison caveat, owner picks:
  shared calibration = honest cross-cohort comparison; split = the experiment
  breathes.
- **D③ THE COMPOSED ARM (W2+W3).** RESHAPE: clocks are RESET → NO arm this week
  regardless. Decision = **GO on the arm-evidence-repair PACKAGE (queue ②) + the
  W3 double-polarity fix as its precondition**; clocks restart at that SHA. GO on
  the package, not the arm.
- **D④ 2-LEG CREDIT COHORT.** RESHAPE: GATED on the credit-probability source
  (queue ⑤; E12 algebra means un-muting cannot produce a qualifying entry).
  Decision = **approve queue-⑤'s spec** (independent terminal/breakeven
  probability source, production-route test asserting NONZERO EV + unchanged
  gates, observe/replay-only start; ~1-2 evenings + observation) as next week's
  strategy build. GO on the spec.

**STOP for operator confirmation. Part 3 (PR-① E8 seam → PR-② arm-evidence → PR-③
replay terminal → PR-④ clone normalizer, + the possible PR-⓪ thesis-basis) builds
ONLY on the recorded GOs. ①② are the must-lands if the day runs long; ③④ hold to
Monday post-close at no cost (capture completeness already known-defective).**

## 2026-07-12 (Sun 00:01 CT) — FULL NIGHTLY AUDIT (v5.5, scheduled) — report audit/reports/2026-07-12.md

STEP-0: DB 05:01:47Z = Sunday 00:01 CT / broker 01:02 ET — agree to the minute; FULL mode.
Broker READ (not blind): equity=cash=OBP $2,067.86, book FLAT. H8: all 3 services @ `a120c5f`
= origin/main; run-START = run-END SHA (first run under the run-boundary pin). H11: 0 critical.
Budgets: 15 SQL · 2 broker · 6 Railway · 6 subagents.

**NEW FINDINGS (status:reported):**
- **F-A9-THESIS-BASIS (MED, observe-only surface, TIME-SENSITIVE for Mon 17:00 CT):**
  thesis_tracker `_underlying_at_expiry` silently falls back to the last bar ≤7d before expiry
  (thesis_tracker.py:55-57) and persists a TERMINAL hit/miss (never re-scored, :84-88/:117) with
  NO price-source/date field; thesis_basis prints the price as the expiry price
  (thesis_scoring.py:88-121) while the module claims "NEVER fabricated (H9)" (:20). Table still
  0 rows — first authoritative fill Mon 17:00 CT. Fix: persist price_basis(_date) + surface in
  thesis_basis (or strict-mode: unknown when no exact-expiry bar). Born-honest if shipped first.
- **F-A4-SLEEP-DEATH (operator-side, no repo code):** the 07-11 nightly start-with-no-end is
  PROVEN external kill — run-nightly.cmd's end marker is UNCONDITIONAL (fires even on claude
  errors, cf. cron.log 06-13), so the cmd process died: machine re-slept moments after the
  00:00:02 start. 4th occurrence, ALL weekends (06-14 · 06-20 · 06-30 · 07-11). WakeToRun wakes
  to START but holds no wake-lock for the run; ping-after-file is positive-only and never ran.
  Operator: (1) confirm the healthchecks DOWN email for the missed 07-11 ping ARRIVED (if not,
  the nightly dead-man is unarmed); (2) add a sleep-hold (ES_SYSTEM_REQUIRED wrapper) or
  equivalent.
- Shared A2/A9 one-liner: `bucket_exposure_would_block` writes severity='warning' → unpaged
  (paper_autopilot_service.py:1063-1064) though the comment says "#1139-class alarm" — fold the
  severity choice into the composed observe→enforce owner decision, not a separate PR.

**VERIFICATIONS CLOSED:**
- ★ **First calibrated PRODUCTION ev — PROVEN + persisted:** 07-10 16:00Z QQQ IC
  `ev 18.73 = ev_raw 37.46 × 0.5000` (+ SOFI 14:02Z ×0.5), blocked ev_below_roundtrip_cost /
  edge_below_minimum. F-A1-3 re-scope honored (persisted ev + final gate only; selection RAW).
  **The composed floor×gate ZERO-ENTRY regime is live-exercised** — the A1 clamp-review exhibit
  now has a production data point (QQQ-IC missed by ~2.1 EV pts). 16:00Z scan LOSSLESS.
- Breaker suppression #2 (07-10 21:20Z): `suppressed_standing_window:true` on unchanged
  fingerprint; entries stayed armed. Designed case-3, second live proof.
- Weekend-PR content verification (subagent reads @ a120c5f): #1178 all-10-branch terminal
  clamp + no double-clamp + zero forecast_ev_pop refs · #1171 seam order (utilization→bucket),
  strict =1 parse, reservation-per-cohort, no unit mix · #1174 flag-off path mutates NOTHING
  (byte-identical claim holds; legacy :3601 single-apply guarded) · #1172 winter-close ET
  wall-clock VERIFIED + repo-wide sweep: NO remaining winter-blind arithmetic (heartbeat crons
  CHICAGO_TZ) — **2026-11-01 trigger retired** · all 6 new flags CALL-TIME reads (no import-time
  growth) · #1164 Monday wiring complete (17:00 CT → background queue → EXPECTED_JOBS → typed
  PARTIAL contract) · E12 / E6-edge (submit_and_track discard :2245) / W2 / W3 / W4 all
  UNCHANGED (cited, clocks stay reset) · zero stale `hit_rate` readers post-F-A9-1.
- A5 continuation counts: 07-10 14:02Z scan lost 5 rejection rows (#1104 residual, 2nd
  occurrence, 11 cumulative) → 9 hourly phone egresses for the one condition; ops_output_stale
  ×10 flat-book HIGHs. **3-in-1(+1) observability PR slipped a 3rd build day** — TOP-2.
- M4 quarantine held: all 168 micro_tier rejects confined to excluded 07-06; zero recurrence.

**PROMPT-STATE CORRECTIONS for v5.6 (movers = 07-11 builds; loop does not edit the prompt):**
(1) iv_daily_refresh ok-on-all-missing FIXED (iv_daily_refresh.py:170-173) — EXPECTED_JOBS half
still open, ride the 3-in-1 PR; (2) watchdog now watches real paper_learning_ingest
(ops_health_service.py:117) — stub-watch claim stale; (3) P0-B BUILD half COMPLETE
(#1166+#1171 observe-off) — enforcement is a composed owner decision on ~1wk of shadow logs.

**A11 FULL-form proposal (owner-gated):** rotate A10 → SECURITY & CREDENTIAL HYGIENE lens
(incumbent's headline shipped+verified; F-FREE-1 tails unaudited; the nightly allow-list is
itself an unreviewed security surface). Decision remains the owner's.

**PENDING (Mon 07-13):** 16:00Z replay capture rows-EXIST + timing (E16 re-scope: completeness
known-defective) · first [APPLY_ORDER_SHADOW]/[GATE_QTY]/[RISK_BASIS_SHADOW]/[BUCKET_SHADOW]
clean lines · 17:00 CT first thesis run (0 rows tonight — ledger's 16-row table was preview) ·
native [CLOSE_FILL_GAP] + last_marked_at stamp still gated on a live close · healthchecks DOWN
confirm (above). Retirement counters: A1/A3/A6/A10 at 4 · A8 3 · A2/A5 2 · A4/A9 reset 0.

## 2026-07-12 (Sat ~21:3x CT) — ADJUDICATED: external full audit v1.3 (4th engagement) — READ-ONLY, doc writes only

STEP-0: DB `02:35Z` (America/Chicago `21:35`, Sat) / broker `22:35 ET` = `21:35
CT`, agree to the second; `dow=0` is the UTC date (rolled to Sun) — CT wall-clock
is SATURDAY 07-11. Market CLOSED. Report swept to
`docs/review/external-full-audit-v1.3-2026-07-12.md` (was dropped to Downloads,
not docs/review — noted). Build NOTHING; verdicts + census + backlog diff only.

**SCORECARD — v1.3 is the strongest engagement yet** (their self-grade, verified
sound): A1 A+ (killed the 2-leg profit premise + 2 corrupt arm notebooks) · A4 A+
(2nd E8 false-green seam + replay-not-decision-grade) · A6 A+ (credit-zero
identity is underlying-independent) · A2/A8/A9/A10 A · A3 A− · A5 B+ · A7 dormant
9/10. Free-look produced the headline (the E8 per-user seam). Audited against the
correct HEADs (start `17f84d9`; runtime code `1b8217b`; E18 PASS at final HEAD).

**PROMOTED EXCLUSION FAILs — all VERIFIED against code + this DB:**
- **E8 (F-A4-E8, CRITICAL, promoted FAIL).** `intraday_risk_monitor.execute()`
  catches every `_check_user` exception → appends `{user_id,error}` to `results`
  → returns hardcoded `ok:true,status:completed` with NO users_failed/counts.errors
  (`intraday_risk_monitor.py:198-216`); `run()` raises only on an OUTER exception
  (the F-A4-1 #1153 fix), so a PER-USER failure never propagates. The runner's
  `_classify_handler_return` only reads top-level keys → classifies `succeeded`
  (faithful, not a runner bug). On the ONE-user account a `_check_user` throw masks
  a COMPLETE protection-cycle failure as green. The E8 test
  (`test_typed_job_outcome.py:60-67`) is a SOURCE-STRING pin of the outer raise —
  the #1126 costume in test form, one layer up from the bug. **CENSUS: 671
  succeeded rows / 30d, 0 with a nested `results[].error`** → structural-unexercised,
  STILL CRITICAL (bounded/latent, exactly F-A4-1's 0-instance posture). F-A4-1 closed
  only the outer seam. → queue ①.
- **E12 (F-A1/A6-E12, HIGH, promoted FAIL).** Credit-spread EV is IDENTICALLY $0,
  dispositive algebra (no runtime): `calculate_pop` returns the fair-odds
  `win_prob=1−c/w`; `calculate_ev` (`ev_calculator.py:282`) then computes
  `win_prob·(c·100) − (1−win_prob)·((w−c)·100)` = `100·[(c−c²/w)−(c−c²/w)]` ≡ 0 for
  ALL c,w (payoff-circular). Their pinned $1.49/$5 case: p=0.702, gain 149, loss
  351, both terms 104.598, EV=$0, misses the $15 floor by $15. #1169 fixed the PoP
  LABEL only; the cohort is NOT evaluable. **CLOSURE CLAIM CORRECTED**: "#1169
  cleared the 2-leg credit gate" → FALSE (label fixed; EV payoff-circular).
  **CENSUS: 0 credit verticals stored in 120d** (only debit spreads + condors) →
  CONFIRMED-but-LATENT. → queue ⑤; **GATES decision ④** (2-leg cohort experiment).
- **E14 (F-A9-E14, HIGH, PARTIAL-FAIL promoted).** Policy-Lab fork copies source
  `sizing_metadata.max_loss_total` unchanged even when clone contracts differ, and
  omits top-level `max_loss_total`; fill/orphan consumers read only the typed
  field (`policy_lab/fork.py:254-333`). **CENSUS (their exact predicate):
  non-champion clones typed-null-but-JSON-present = neutral 23/23 + conservative
  10/10 = 33 rows, 100%.** The shadow cohorts that feed W2/W3 evidence are entirely
  typed-risk-blind → W2/W3 evidence contaminated. Champion path unaffected. →
  queue ④ (PRECONDITION of trusting W2/W3).
- **E16 (F-A4-E16, HIGH, promoted FAIL) — includes a fair critique of my own PR-2
  (#1175).** Four replay seams: (1) `run_midday_cycle` no-trade early return
  (`:3771-3826`) precedes my `__decision__/ranked_candidates` capture → a ZERO-
  suggestion cycle (the dominant near-zero funnel) has NO output; (2) my capture
  serializes only the accepted `suggestions` list, NOT the rejected `continue`d
  tail — my PR framing "accepted + rejected+reason" was aspirational, the code
  captures accepted only; (3) cache-hit inputs omitted (chain cache returns before
  record, `market_data_truth_layer.py:1434-1438`); (4) commit failure swallowed,
  no manifest/health. OWNED: PR-2 shipped a partial capture. → queue ③; **Monday's
  capture pin RE-SCOPED to "rows exist + timing OK" ONLY — completeness is
  KNOWN-DEFECTIVE until the terminal-manifest PR ships.**
- **E18 PASS at final HEAD** (clamp `aca743a` + dead-forecast delete `1b8217b`).

**P0 CUSTODY (verified):**
- **F-A2-1 (HIGH).** Partial multileg closes don't reconcile residual into
  `paper_positions` (closure runs only on parent `filled`); a later cancel/expiry
  → 30-min re-arm can stage the FULL stale DB qty (`alpaca_order_handler.py:795-
  924`). Plus: parent-filled-but-legs-disagree → `_close_position_on_fill` alerts +
  returns without closing (`:580-601`) yet caller logs "Position closed" +
  increments fills (`:1002-1010`). **CENSUS: 0 orders with filled_qty<requested_qty**
  → structural/latent. → queue ⑥ (HARD TRIGGER before routine qty>1 credit OR any
  position ≤~10 DTE).
- **F-A8/E6-edge (MED-HIGH).** `submit_and_track` return is DISCARDED
  (`paper_exit_evaluator.py:2245`, not assigned) → unconditional
  `routed_to:'alpaca',Fill pending` (`:2255-2260`); a `needs_manual_review` RETURN
  (terminal submit failure, not a raise) is costumed as routed success → monitor
  emits "Force-closed", increments counts, may write cooldown, suppresses same-
  cycle retry. E6's narrow no-phantom-fill invariant still holds. → rides the E8 PR
  territory.

**BROKER/DB GROUNDING (ALPACA authoritative):** live book is FLAT — Alpaca
`get_all_positions`=[], DB `paper_positions` 0 open. The "6 Aug-21 ICs" are
thesis-tracker rows (CLOSED positions tracked to expiry, I5/#1164), NOT open
custody exposure — a framing correction to F-A2-1's DTE trigger (nothing open to
trigger on today; the trigger is a standing guard for when qty>1 credit or a
near-DTE position returns).

**OBSERVE-WINDOW VERDICTS (W1 PASS, W2–W5 FAIL) + CLOCK RESET:**
- W1 (live gate qty basis) — **PASS in code**, runtime pending (all gate lines
  carry both bases + floor + applied basis + suggestion id). ITS CLOCK STANDS.
- W2 (max-loss risk basis) — **FAIL/not-armable.** All 3 callers
  (`utilization_gate.py:349`, `portfolio_allocator.py:163`,
  `risk_budget_engine.py:400`) omit `threshold_usd` → `would_flip` ALWAYS None
  (`risk_basis_shadow.py:45-49`); context lacks suggestion/cohort/decision id. The
  ledger's "each consumer logs would_flip" DISAGREES with code.
- W3 (bucket enforcement) — **FAIL/not-armable, TWO fail-open preconditions.**
  `_risk_from_fields` returns `(0,true)` when both totals unknown; `evaluate_bucket`
  adds zero + sets the caveat only when `v>0` → the log HIDES unknown open
  exposure; armed caller sees `would_block=false` and proceeds
  (`paper_autopilot_service.py:1038-1056`). This is the SECOND precondition on top
  of last night's L3 unreadable-equity polarity.
- W4 (calibration at scoring) — **FAIL/not-armable.** `_top_n` serializes ticker
  only (`calibration_apply_ordering.py:72-74`) → same-ticker structure swaps log
  `would_differ=False`; line omits strategy/expiry/id/scores/magnitude. (My own
  #1174 code.)
- W5 (composed W2+W3) — **FAIL** (both components defective).
- **⚠ LEDGER THE CLOCK RESET: W2/W3/W4/W5 arm decisions RESTART from the
  arm-evidence-repair SHA; THIS WEEK'S shadow logs are EVIDENCE-DEFECTIVE for those
  decisions. W1 alone passed — its clock stands.**

**DOCTRINE SHARPENING (adopted, extends the "drive the production route"
NEVER-DO):** "drive the production route" means the FULL route to the FAILURE
SEAM — an outer-layer test of an inner-layer bug (E8: source-pinning `run()`'s
raise while the bug is in `execute()`'s per-user loop) is the source-pin costume
one level down. A route-driving test must exercise the entrypoint END-TO-END to
the seam and assert on the OUTPUT.

**10 PACKET/LEDGER/CODE DISAGREEMENTS (move-don't-lose, annotated):** (1) E8
closure overstates the route [→①] · (2) E12 "cohort evaluable" false [→⑤] · (3)
E16 "output+linkage shipped" incomplete [→③, own PR-2] · (4) E14 persistence
path-dependent [→④] · (5) ledger "W2 logs would_flip" vs code None [→②] · (6) W4
ticker-lists aren't structure identities [→②] · (7) E6 invariant true but
close-state narrative too strong [→ E8 territory] · (8) E15 winter closed but
summer-open health still wrong [→ P2 F-A10-1] · (9) no matched 3-structure same-
underlying example — refused to fabricate; credit-zero proof is universal instead
[accepted] · (10) HEAD moved during audit (17f84d9→aca743a→1b8217b→b761a3f), E18
closed at final HEAD [accepted].

**REFUTED / NOT-PROMOTED (cite, don't re-derive):** direction='long' liar
(`workflow_orchestrator.py:3633`) — evidentiary, no proved live-decision consumer
(typed-column-lies inventory member #4, A9 hunt) · quarantined ~61 legacy rows —
no cleanup justified · no new credential instance in the current tree.

## 2026-07-11 (Sat ~21:1x CT) — BUILT: PoP census PR-0 terminal clamp (#1178) + PR-1 delete #7 (#1179)

STEP-0: DB `02:03Z` (America/Chicago `21:03`, Sat) / broker `22:03 ET` = `21:03
CT`, agree to the second; market CLOSED. Sunday FULL nightly at 00:00 CT — PR-0
H8 landed ~21:12 CT, PR-1 H8 ~21:19 CT, both clear of the ~23:00 CT hold gate
(margin ~2h40m). Sequential, H8 between.

**PR-0 — terminal [0,1] clamp in calculate_pop `aca743a` MERGED + H8 VERIFIED**
(BE `70f3f755` / worker `19307182` / worker-background `7f02521d`, all @
`aca743a`, created 02:09:15–16Z). calculate_pop clamped [0,1] on the CREDIT
branch ONLY (`ev_calculator.py:49`); every other branch (debit interp/midpoint/
long-only, short/long single-leg, raw-delta + neutral fallbacks) returned
UNCLAMPED and the `calculate_ev` consumer (`:176`→win_prob) fed them into EV
math. Fix: ONE clamp at the exit (`_clamp_pop`), every branch returns THROUGH it
(credit's inline clamp folds in — no double-clamp); LOG on engagement
(`[POP_BOUND_ENGAGED]` raw+branch+strategy, #1147 pattern) so an out-of-range
value is caught AND observable; non-finite → 0.5 neutral + logged. NO LIVE CHANGE
(max(0,min(1,x))==x for x∈[0,1]; in-range byte-identical, the clamp never engages
on the live book). Tests 15/15 (11 in-range cases bounded + assertNoLogs = the
no-op proof; clamp binds+logs on >1/<0/non-finite; end-to-end |delta|=1.3 → 1.0
long / 0.0 short + branch-tagged). **SATISFIES the PoP-unification "bound-assert
at the compute site" backlog line — the single terminal clamp IS the home; do
NOT scatter per-site clamps.**

**PR-1 — delete dead #7 `forecast_ev_pop` `1b8217b` MERGED + H8 VERIFIED**
(BE `242f7668` / worker `97b71557` / worker-background `285ab979`, all @
`1b8217b`, created 02:16:28–29Z). Zero-caller RE-VERIFIED at HEAD (`aca743a`, NOT
the census): only the def (`forecast_interface.py:129`) + test_forecast.py
(import + 2 tests); no prod caller, no re-export (`forecast/__init__.py` bare
docstring), no getattr/registry indirection. Deleted the function + orphaned test
import + the TestForecastEvPop class; no imports orphaned. Inert.
test_forecast.py 30 passed (was 32). Zero residual refs in packages/.

**PoP 7-way census — UPDATED MAP (canonical = calculate_pop, now terminally
clamped):**
- **#1 `calculate_pop`** (`ev_calculator.py:8`) = CANONICAL; PR-0 added the single
  terminal [0,1] clamp (the bound-assert home).
- **#7 `forecast_ev_pop`** = **DELETED** (#1179).
- **#6 `_calculate_ev_pop`** (`opportunity_scorer.py:316`) = **CLUSTER-RETIRE
  FILED** — NOT a trivial delete (caller `OpportunityScorer.score()` exercised by
  4 test files; dead-in-prod only transitively via the never-called
  `enrich_trade_suggestions`, `trade_builder.py:14`). Own PR: retire
  score/_calculate_ev_pop/_calculate_liquidity_penalty + enrich_trade_suggestions
  + the `optimizer.py:24` dead import + the 4 scorer test files together.
- **#3 `calculate_condor_ev` p_win** + **#5 `_condor_pop_from_legs`** (dup) =
  **FOLD into a calculate_pop condor branch** — the NEXT PoP PRs, boundary-only
  (observe-first; #5 clamps [0.01,0.99] vs canonical [0,1]), Option-A not a silent
  swap.
- **#4 score-sigmoid fallback** (`options_scanner.py:2134`) + **#2 exit-metrics
  abs-delta** (`ev_calculator.py:405`, live exit path) = **KEEP** (#4 narrow-only;
  #2 stays — folding touches the live take-profit path).
- **2-leg credit cohort's remaining PoP gate = the fold PRs** (#3/#5), sequenced
  after the #6 cluster-retire.

Untouched: everything else. Night ends here.

## 2026-07-11 (Sat ~20:3x ET) — BUILT: calibration apply-move PR-1 (#1174) + replay gap-(c) PR-2 (#1175) + prequential validator PR-3 (#1176)

STEP-0 (premise correction): the prompt/summary said "Sunday"; DB `01:21Z`
(America/Chicago `20:21`, Sat) + broker `21:21 ET` agree to the second → it is
**Saturday 2026-07-11**, market CLOSED, next open Mon 07-13 09:30 ET. The Sunday
FULL nightly fires 00:00 CT tonight — all three recycles landed by ~20:40 CT,
clear of it. Builds STRICTLY SEQUENTIAL, H8 between each.

**PR-1 — calibration apply-move + score recompute, observe-first `6f6a549`
MERGED + H8 VERIFIED** (BE `45eabc07` / worker `f1bb2c68` / worker-background
`8c98b9b9`, all @ `6f6a549`). Closes the L1-flagged real cost: SELECTION sorts on
`score` (frozen from RAW ev inside the scanner), so moving `apply_calibration`
earlier is INERT unless `score` is RECOMPUTED from calibrated ev. New
`analytics/calibration_apply_ordering.py`: `snapshot_pre_conviction_scores`
stamps `_scanner_score` before conviction → EXACT recompute (`soft_earn =
inner_raw − scanner_score` additive penalties; `conv_w = post_score /
scanner_score` multiplicative conviction; `new_score = max(0, clamp(base×ev_mult
− cost − regime − greek) − soft_earn) × conv_w`; de-saturation correct). TO-seam
`workflow_orchestrator.py:2441` (after conviction, before rank). Flag
`CALIBRATION_APPLY_AT_SCORING` default OFF → compute both orderings, log
`[APPLY_ORDER_SHADOW] … would_differ=`, mutate NOTHING (flag-off byte-identical);
armed → apply+recompute + `_calibration_applied` sentinel (the `:3564` legacy
post-sizing apply skips it → SINGLE application) + `_ev_raw_true` stamped.
Fail-safe per candidate + caller-wrapped. Tests 11/11.

**PR-2 — replay decision-output + `decision_id` linkage `057e11a` MERGED + H8
VERIFIED** (BE `a63bc95d` / worker `04f36525` / worker-background `24fd31c6`, all
@ `057e11a`, created 01:25:43–44Z; prior `6f6a549` → REMOVED confirms
supersession). **Replay Phase-1 gap-(c) — the unconditional blocker — CLOSED.**
Migration `20260712011627` `trade_suggestions.decision_id uuid` (nullable,
forward-only; in DROPPABLE_SUGGESTION_COLUMNS → code-before-migration = no-op
drop) applied + tracked + read-back (`col_uuid=1, mig_tracked=1`).
`run_midday_cycle`: fetch the active decision_id once, stamp each suggestion
(linkage); after the insert loop capture the ranked set (accepted +
rejected+reason, sorted by risk_adjusted_ev) as
`record_feature("__decision__","ranked_candidates")` — the decision OUTPUT a
byte-compare replay diffs against. BOTH blocks fail-soft
(`get_current_decision_context()` None when replay off → both no-op → replay-off
byte-identical; capture failure swallowed; `logger` is a module global so the
except branch is safe). Tests 3/3.

**PR-3 — prequential (out-of-sample) validator = the FALSIFIER `d554904` MERGED +
H8 VERIFIED** (BE `9dec42d1` / worker `2a348058` / worker-background `7399ad18`,
all @ `d554904`, created 01:38:00–01Z). Backward calibration-error is circular
(scores the fit on its own fit rows). This scores prequentially: for each live
close k (closed_at order, k≥warmup) fit on PREFIX [0..k-1], apply to close k's
RAW ev_predicted, compare calibrated-vs-raw. `calibration_service`: extracted
`build_adjustments_from_outcomes(outcomes, min_trades)` — a PURE fit (list→blob,
no DB round-trip); `compute_calibration_adjustments` delegates (byte-identical
for the prod default; `min_trades` is a study knob prod never passes; uses no
self.client → fits on `CalibrationService(None)`). New
`analytics/prequential_validator.py`: reuses prod math EXACTLY, reports raw-vs-cal
EV-RMSE/MAE + Brier; HEADLINE `ev_rmse_improvement = raw_rmse − cal_rmse` (≤0
with calibration having fired → FALSIFIED_CALIBRATION_DOES_NOT_HELP; never-fired
→ INCONCLUSIVE; >0 → HELPS); prefix-invariance checked (fit = function of the
SET, not order — order dependence = leakage); zero-row/too-short →
insufficient_data, never raises; `main()` on-demand only (schedules nothing,
changes no live behavior). Non-circular as of #1167 (ev_predicted =
COALESCE(ev_raw, ev) = RAW). Tests 10/10; existing calibration suite 58/58
(extraction backward-compatible).

**Lane deliverables (READ-ONLY, filed):**
- **L1 PoP census → 5-PR map — ⚠ CORRECTS the 07-11 census above (`:64`):** #6
  `_calculate_ev_pop` is NOT a trivial zero-caller delete — its caller is
  `OpportunityScorer.score()` (`opportunity_scorer.py:174`), dead-in-prod only
  transitively (its sole prod caller `enrich_trade_suggestions`,
  `trade_builder.py:14`, has ZERO call sites) yet exercised by 4 test files → a
  CLUSTER retire, not a one-liner. Only **#7 `forecast_ev_pop`**
  (`forecast/forecast_interface.py:129`) is a clean zero-caller delete (tests
  only; no re-export). **PR-0 terminal `[0,1]` clamp STILL NEEDED** — only the
  credit branch clamps (`ev_calculator.py:49`); every other branch + the
  `calculate_ev` consumer (`:176`→`:251`) is unclamped. Map: PR-0 clamp (inert)
  · PR-1 delete #7 (trivial) · PR-2 retire #6 CLUSTER (inert-to-live, medium
  blast) · PR-3 condor fold #3+#5 (boundary, observe) · PR-4 fallback narrow #4
  (observe). #2 STAYS (live exit path `workflow_orchestrator.py:1404`).
- **L2 replay retention TTL spec:** blob table is `data_blobs` (not
  decision_data_blobs); 4 tables in migration `20260120000000`. Growth ≈
  **70 MB/mo ≈ 0.85 GB/yr**, dominated by `data_blobs.payload` (option-chain
  blobs; 2–5× if chains carry per-contract greeks). Recommend **14-day**
  retention + daily fail-open `replay_reaper` ~03:00 CT: (1) `DELETE FROM
  decision_runs WHERE created_at < now()-'14 days'` (cascades inputs+features)
  then (2) orphan-blob anti-join delete (blobs are content-addressed/deduped →
  a pure age-delete would FK-violate). Flags: `trade_suggestions.decision_id`
  has NO FK → dangling after reap (expected; the window must exceed the
  replay-lookback need); `REPLAY_MAX_BLOB_BYTES` 2 MB cap is NOT enforced (warns
  only, still stores); no standalone `decision_runs.created_at` index (tiny
  table → low-pri; it's a migration, out of scope).
- **L3 bucket-control layering check (operator: confirm + flag, DON'T fix):**
  ordering CONFIRMED — utilization gate (`paper_autopilot_service.py:1021`,
  fail-CLOSED on unreadable input) precedes the bucket check (`:1039`). BUT the
  equity-unreadable backstop is CONDITIONAL: the bucket's cap-0-never-blocks
  (equity unreadable → would_block=False, by design at evaluate_bucket) is only
  caught upstream when `_ug_on` (RISK_UTILIZATION_GATE_ENABLED=1). **With that
  flag unset AND BUCKET_CONTROL_ENFORCE=1, an equity-unreadable read makes the
  bucket cap silently never-block — UNBACKSTOPPED.** Deferred polarity fix
  filed: bucket_control fail-CLOSED on equity-unreadable when enforce armed
  (independent of the utilization flag). NOT fixed tonight (per operator).

**Deferred (filed, not built):** L1 PoP 5-PR sequence (PR-1 delete #7 = clean
tomorrow-post-close candidate; #6 is a cluster, re-scope) · L2 `replay_reaper`
job + 14-day TTL (+ optional `decision_runs.created_at` index) · L3
bucket-control equity-unreadable fail-closed polarity.

## 2026-07-11 (Sat ~19:4x ET) — BUILT: B1/B2 bucket control PR-1 (#1171) + winter-close PR-2 (#1172)

STEP-0: DB 00:27Z (dow=0) / broker 20:27 ET — consistent, market CLOSED.

**PR-1 — B1/B2 one-beta bucket control + same-run reservation `d86a270` MERGED +
H8 VERIFIED** (BE `b6e0324e` / worker `ab1c8e0e` / worker-background `2c28a8e1`,
all @ `d86a270`, created 00:39:36–37Z > merge 00:39:34Z). **Completes the BUILD
half of the book-scaling epic** (persist+observe = #1166). `risk/bucket_control.py`:
buckets as DATA ({SPY,DIA,QQQ,IWM}=us_equity_beta, else own). Wired into
`_execute_per_cohort`'s staging loop (after the utilization gate): exposure =
Σ max_loss_total of in-bucket open positions (+ same-run reservations + the
candidate) vs BUCKET_MAX_PCT × equity; honest basis, legacy-NULL at premium WITH
caveat (H9), equity-unreadable → cap 0 → never blocks. **Observe-first** (flag
`BUCKET_CONTROL_ENFORCE` default OFF): log [BUCKET_SHADOW] + fire the #1139-class
alarm (`bucket_exposure_would_block`) on a would-block that PROCEEDS; armed →
reject with a `bucket_exposure_cap` stamp. Same-run reservation accumulates as
each candidate stages (byte-identical for a ≤1-candidate cycle). Tests 14/14
(exposure per basis + NULL-never-fabricated · reservation · fail-safe · polarity
· executor 2-candidate off/armed + ≤1 byte-identical + cross-bucket).
- **⭐ BUCKET_MAX_PCT arithmetic (owner-tunes):** at $2,068, one IC ≈$372 = 18%,
  so **0.25** allows one IC + nothing same-bucket; 0.40 allows two. **Recommend
  0.25.** **ENFORCEMENT = ONE composed owner decision after ~1 week of
  [RISK_BASIS_SHADOW] + [BUCKET_SHADOW] logs: arm `RISK_BASIS_MAX_LOSS_ENABLED=1`
  + `BUCKET_CONTROL_ENFORCE=1` together.** #1139 tripwire is the armed guard
  meanwhile. **The book-scaling epic's BUILD is done; enforcement is a decision,
  not a build.** backlog.md updated (weekend-ships block + P0-B status).

**PR-2 — winter-close blind hour `bd6046a` MERGED + H8 VERIFIED** (BE `12f104e6`
/ worker `ce2764d2` / worker-background `90d918a5`, all @ `bd6046a`, created
00:45:00–01Z > merge 00:44:58Z). `is_us_market_hours` (ops_health_service.py:42)
hardcoded UTC 13:30–20:00 = ONLY the EDT session → in EST the 20:00–21:00Z hour
read CLOSED all winter (data_stale suppressed + `_rth_job_status` ok = the A10
blind hour). Fix: ET wall-clock (9:30–16:00 America/New_York) via zoneinfo,
mirroring `intraday_risk_monitor._fallback_is_market_open_et` (reuse). BYTE-
IDENTICAL for EDT (existing June assertions pass). Winter tests: Nov 20:30/20:59Z
now OPEN, 21:00Z=close. **Retires the 2026-10-01 hard trigger ~3 months early.**

**Lane deliverables (READ-ONLY, filed):**
- **L1 calibration-apply-ordering:** ⚠ **SELECTION sorts on `score`, NOT `ev`** —
  and `score` is frozen from RAW ev INSIDE the scanner (`options_scanner.py:3751,
  3919`). So moving `apply_calibration` earlier is insufficient; the fix MUST
  RECOMPUTE `score` from calibrated ev (the real cost). TO-seam = after
  conviction at `workflow_orchestrator.py:2441` (before rank :2495); DELETE the
  midday :3562-3569 apply (move-not-add → else ev×mult²) + idempotency sentinel;
  hash `ev_raw` for features_hash continuity. Effort ~M (half-full day). Raw-basis
  prereq already closed by PR-B #1167. Filed in backlog's calibration item.
- **L2 replay Phase-1 gaps:** (a) config blob — write at suggestions_open.py:141 /
  close:135, `record_input(snapshot_type="config")`, PARTIAL blocker (code pinned
  by git_sha). (b) applied calibration+conviction — capture at
  `workflow_orchestrator.py:2441`+`:2898`, YES-blocker but LATENT (raw-mode ×1.0
  captures trivially match; breaks the day multipliers turn non-trivial). (c)
  decision OUTPUT + `decision_id` linkage — the UNCONDITIONAL blocker + the only
  gap needing a MIGRATION (`trade_suggestions.decision_id`); ranked-list via
  `record_feature("__decision__","ranked_candidates")`. Sequence: (c) critical
  path → (a) → (b before the 8th live close). ~4–6 evenings on Monday's captures.
- **L3 PoP census (7→canonical):** FOLD #3 (`calculate_condor_ev` p_win) + #5
  (`_condor_pop_from_legs`, dup) into a new `calculate_pop` condor branch; DELETE
  #6 (`_calculate_ev_pop`, dead — enrich_trade_suggestions uncalled) + #7
  (`forecast_ev_pop`, dead — tests only); #4 (score-sigmoid fallback) + #2
  (exit-metrics abs-delta) STAY. **Bound-assert [0,1] home = a single terminal
  clamp in `calculate_pop`** (today only the credit branch clamps). Migration
  order: PR-0 terminal clamp (no live change) · PR-1 dead-code delete · PR-2
  condor fold (boundary-only, observe-first) · PR-3 fallback narrow (observe) ·
  PR-4 exit fold (observe). Live-number-change flags: #5 boundary, #4 fallback,
  #2 short-legs → Option-A, not silent swap.

## 2026-07-11 (Sat ~19:0x ET) — BUILT: PoP inversion fix PR-0 (#1169) + REPLAY_ENABLE Phase-0

STEP-0: DB 00:01Z (dow=0) / broker 20:01 ET — consistent (UTC rolled to Sunday),
market CLOSED, weekend premise holds.

**PART 1 — PoP inversion `aaa8431` MERGED + H8 VERIFIED** (BE `61c01ea7` /
worker `e52b8ae2` / worker-background `c02bd0bd`, all @ `aaa8431`, created
00:08:32–33Z > merge 00:08:30Z). `ev_calculator.py:42` one-token swap
`max_gain`→`max_loss`: credit PoP was `max_gain/(max_gain+max_loss)` =
`credit/width` = **P(LOSS)** (inverted → credit-vertical EV negative → −999
MIN_EDGE gate → 2-leg credit cohort silently blocked). Now
`max_loss/(max_gain+max_loss)` = `1 − credit/width` = **P(WIN)** + terminal
`[0,1]` clamp (H9 bound-assert; width-bound recommended over delta — H9-robust).
Arithmetic: credit 1.49/width 5 → **0.298 → 0.702**. **Byte-identical for the
live book:** only the 5 credit-vertical types hit that branch; ICs RAISE in
calculate_ev (:187 → calculate_condor_ev), debits take the delta branch — both
pinned untouched. Book = ICs + debits today → NO live score change; unblocks the
latent credit cohort. Tests (new RUNNING file — legacy test_calculate_pop.py is
#775-skipped): 12 + the updated test_honest_pop pin (130/200). **The 2-leg
credit cohort PoP gate is CLEARED**; the 7-way PoP census consolidation stays
its own filed item.

**PART 2 — REPLAY_ENABLE Phase-0 (supervised env flip, AFTER Part-1 H8).**
**PRE-FLIGHT CLEAN (the load-bearing check):** `is_replay_enabled()` reads
`REPLAY_ENABLE` at RUNTIME (decision_context.py:34-45); record_input/feature
STAGE in memory and `commit()` flushes ONCE at cycle-end (atomic RPC) — NOT
per-symbol-synchronous in the scan hot path. **AND commit() is FAIL-SAFE**:
wraps everything in try/except (`:297/:366`) that logs + marks-failed +
RETURNS stats WITHOUT re-raising, so `ctx.commit()` at
suggestions_open.py:144 CANNOT break the suggestions cycle (a capture failure
writes a failed decision_run, nothing more). Capture tables were 0/0/0/0 (never
run). **FLIP DONE:** `REPLAY_ENABLE=1` set on BOTH RQ workers (worker
`9b0ffca8` + worker-background `ec49427f`; the otc worker runs
suggestions_open/close), recycled to SUCCESS (worker `816bfaac` / worker-bg
`bfe26936`, same SHA aaa8431, env-only). Env value NOT read back via
list_variables (secrets-hygiene) — the set-success + recycle + Monday capture
rows are the read-back chain.
- **⏳ VALIDATION PENDING (Mon 07-13 11:00 CT scan):** capture rows written
  (decision_runs header + inputs/config/clock/SHA per the replay contract) +
  scan timing not degraded + the job green under the F-A4-1 typed contract. I
  cannot sign a manual weekend scan trigger, and Monday's 11:00 CT
  suggestions_open is the first capture either way, so flipping tonight only
  pre-positions the flag. Replay Phase-1 (the byte-compare runner —
  ReplayTruthLayer.from_decision_id exists) now has data ACCUMULATING from
  Monday; ~4–6-evening estimate stands (writer was already built + wired, per
  the L2 recon).
- **⚠ RETENTION LINE FILED (item 7):** ~2 wrapped cycles/day (suggestions_open
  11:00 + suggestions_close 08:00 CT), each ~a few hundred decision_inputs +
  features + deduped blobs (2 MB soft cap per blob — a full multi-expiry chain
  is the volume risk). Modest rows/day but UNBOUNDED — file an N-day TTL /
  archive before this becomes the next unbounded table. **NEW P2 backlog line.**

## 2026-07-11 (Sat ~18:4x ET) — BUILT: P0-B book-scaling PR-A (#1166) + COALESCE restore PR-B (#1167)

STEP-0: DB 23:26:51Z / broker 23:26:51Z, dow=6, is_open=false — Saturday
CLOSED. Two sequential PRs (PR-A H8 before PR-B started).

**PR-A — book-scaling readiness `6044c77` MERGED + H8 VERIFIED** (BE `1af4ef75`
/ worker `e8f315b6` / worker-background `f1f79ab6`, all @ `6044c77`, created
23:41:18–19Z > merge 23:41:16Z). Migration `20260711233113`: paper_positions
+cost_basis_total +max_loss_total (TOTALS, nullable, forward-only, legacy NULL =
H9). **⚠ units-trap** guarded (column comment + `honest_position_risk()` reads
the total, never ×qty). Write sites (`_commit_fill` + orphan-repair) reuse
`trade_suggestions.max_loss_total` scaled to filled contracts. **Observe-only
shadow** (`services/risk_basis_shadow.py`, flag `RISK_BASIS_MAX_LOSS_ENABLED`
default OFF — third Option-A observe→enforce): RBE / allocator / utilization each
compute BOTH bases, DECIDE current, log `[RISK_BASIS_SHADOW]` + would_flip;
`choose_basis()` swaps to honest only when armed (byte-identical off). Tests
17/17 incl. the units-trap (qty-4 → total as-is).
- **⭐ WORKED EXAMPLE (owner-decision input) at $2,068 equity, real recent QQQ
  IC:** premium basis ~$149 (7.2% of book) vs honest max-loss ~$372 (**18%**).
  The 85% utilization gate + 36% allocator ceiling bind on NEITHER at this
  equity → the honest basis flips NO single-trade decision today. BUT it reveals
  each IC risks 18% of equity (not 7%), and **2 concurrent = 36%** ($744 honest
  vs $298 premium) — the real magnitude the #1139 tripwire alarms on. A
  per-trade cap anywhere in 8–18% would block honest / pass premium. **THE FLIP
  IS THE OWNER'S DECISION on a week of `[RISK_BASIS_SHADOW]` logs.** #1139
  remains the interim guard. B1/B2 bucket control + same-run reservation = the
  epic's NEXT PR, now unblocked by the persisted fields.

**PR-B — COALESCE restore `c069f56` MERGED + H8 VERIFIED** (BE `13413919` /
worker `97f519e5` / worker-background `b08de991`, all @ `c069f56`, created
23:47:43–44Z > merge 23:47:41Z). Migration `20260711234336`:
`learning_trade_outcomes_v3.ev_predicted` → `COALESCE(ts.ev_raw, ts.ev)` (+
pop_raw). The guard was added 04-11 and **silently reverted 06-23**
(20260623010000) → the validator/calibrator would train on their own calibrated
output (circular), masked only by raw mode. **CONTAMINATION VERDICT (verified,
not assumed): NO row annotation needed** — 40 diverged rows all have ev_raw to
fall back to (healed); 175 NULL-ev_raw rows were raw-mode (ev==raw, coalesce→ev
correct); 8 live training rows already clean (0 diverged). Fix is PREVENTIVE for
when calibration leaves raw mode; pre-epoch rows walled off by the epoch +
live-only filter. **Drift guard** (`test_ev_raw_coalesce_drift_guard.py`): a DB
view has no Python route in DB-less CI, so it asserts the LATEST committed
migration coalesces ev_raw — a 4th silent revert (3rd occurrence of this bug)
fails loudly. **Prequential-validator prereq CLOSED.**

**Lane deliverables (READ-ONLY, filed):**
- **L1 PoP-semantics spec:** the inversion is at `ev_calculator.py:42` — one-token
  swap `max_gain`→`max_loss` (= `1 − credit/width` = P(win)); recommend the
  width-bound over delta (H9-robust, minimal diff); add a terminal
  `max(0,min(1,pop))` clamp (the canonical [0,1] bound-assert home). 7-way census:
  fold #5 (`_condor_pop_from_legs`, dup of #3), #2/#3/#6 into canonical
  `calculate_pop`; #7 (forecast) + #4 (score-sigmoid fallback) stay. Ship PR-0
  (inversion + clamp + un-pin the 2 bug-pinning tests) ALONE, non-RTH. Gates the
  2-leg credit cohort.
- **L2 replay capture-write:** **PREMISE CORRECTED — the writer is fully BUILT +
  WIRED, just `REPLAY_ENABLE=0`-gated** (`decision_context.py:34-45`; entrypoints
  suggestions_open/close). Phase-0 = flip the flag env-first + validate (NO code);
  Phase-1 = 3 gaps (config blob · applied-multiplier feature · decision-output +
  decision_id linkage); Phase-2 = the byte-compare runner (ReplayTruthLayer
  exists). ~4–6 evenings, not the ~6–10 backlogged. Suggestion-decision only;
  execution-decision (equity/OBP/positions) is a separate 2nd hook.
- **L3 winter-close:** `ops_health_service.py:56` hardcodes `20*60` (20:00Z)
  close. Fix = ET wall-clock via zoneinfo, mirroring
  `intraday_risk_monitor.py:132-141` (`ZoneInfo("America/New_York")`); do NOT
  wire broker get_clock (network). ~2–4 hrs. Calendar trigger 2026-10-01.

## 2026-07-11 (Sat ~18:0x ET) — BUILT: shadow-to-expiry THESIS TRACKER (I5) + F-A9-1 (#1164)

STEP-0: DB 22:35:56Z / broker 22:35:57Z, dow=6, is_open=false — Saturday
CLOSED. **#1164 `8ffc214` MERGED + H8 VERIFIED** (BE `bdee5e44` / worker
`68103dff` / worker-background `b4ddeb4a`, all @ `8ffc214`, created 23:05:45–46Z
> merge 23:05:43Z). **"The #1 missing measurement."** OBSERVE-ONLY (own table,
alerts nothing, modulates nothing).

**RECON (no surprise):** underlying-at-expiry = `truth_layer.daily_bars`
(Polygon historical → Alpaca fallback), covers all expiries. Storage = OWN
table `position_thesis_outcomes` (migration `20260711224226`, keyed on the
position PK) — only 13/83 closes carry a joinable position_id on their LFL row,
so riding LFL would strand 70. Structure split: 42 two-leg + 41 four-leg.

**Build:** `analytics/thesis_scoring.py` (pure classify + score; strict
inequalities, AT-a-strike = MISS; IC HIT=inside the SHORT strikes, credit
vertical HIT=short not breached, debit vertical HIT=ITM through the LONG strike,
directional=ITM held side, unknown=unresolvable/H9) · `thesis_tracker.py` daily
job (idempotent: terminal never re-scored; in_progress+unknown re-scored;
**FIRST job under the F-A4-1 typed contract** — unscorable → counts.errors →
PARTIAL) · endpoint `/internal/tasks/thesis/score` (background) + SCHEDULES
17:00 CT + EXPECTED_JOBS + the 8th-background-route pin. **F-A9-1** (migration
`20260711225359`): `signal_accuracy_rolling.hit_rate → realized_trade_win_rate`
(it counts pnl>0, NOT thesis — the 12.5%-vs-~78% confusion DIES; thesis accuracy
is now its own measure). Tests: scoring per structure + handler contract, 33+.

**⭐ THE HEADLINE — first honest thesis table (16 post-epoch closes; legacy-paper
era ~61 quarantined; 6 Aug-21 ICs = IN_PROGRESS). PREVIEW basis: Alpaca daily
closes (SIP Jun / iex Jul — SIP blocks recent dates, same reason daily_bars uses
Polygon primary); the job's authoritative Polygon backfill lands Mon 17:00 CT.
None of the 16 sat near a strike boundary, so the source choice flips no
verdict.**

| symbol/exp | fill | structure | close_reason | P&L | thesis |
|---|---|---|---|---|---|
| BAC 06-05 | live-broker | debit call ≥51 | manual | −82 | **HIT** |
| CSX 06-05 | live-broker | debit call ≥43 | manual | −161 | **HIT** |
| F 06-26 | live-broker | debit call ≥15.5 | manual | +105 | miss |
| NFLX 07-02 | live-broker | debit put ≤85 | reconciler | −84 | **HIT** |
| MARA 07-10 | live-broker | debit call ≥13.5 | reconciler | −28 | miss |
| NFLX 07-10 | live-broker | debit put ≤86 | reconciler | +48 | **HIT** |
| QQQ 07-10 | live-broker | IC [645,750] | reconciler | −73 | **HIT** |
| BAC 06-05 | live-internal | debit call ≥51 | envelope | 0 | **HIT** |
| CSX 06-18 | shadow | debit call ≥44 | envelope | 0 | **HIT** |
| BAC 06-26 | shadow | debit call ≥49 | target_profit | +192 | **HIT** |
| NFLX 07-02 | shadow | debit put ≤85 | stop_loss | −273 | **HIT** |
| NFLX 07-02 | shadow | debit put ≤85 | stop_loss | −546 | **HIT** |
| MARA 07-10 | shadow | debit call ≥13.5 | stop_loss | −675.99 | miss |
| NFLX 07-10 | shadow | debit put ≤86 | target_profit | +133.35 | **HIT** |
| NFLX 07-10 | shadow | debit put ≤86 | target_profit | +662.10 | **HIT** |
| QQQ 07-10 | shadow | IC [645,750] | envelope | −234.78 | **HIT** |

**THESIS HIT-RATE = 13/16 = 81%** (LIVE broker fills 5/7 = 71% · shadow/internal
8/9 = 89%) — the formalized B1 ~78%, now a standing metric. **THE FINDING that
justifies the whole build: of the 13 thesis HITs, only 4 were profitable — SEVEN
were losses or force-flat.** The signal was right 81% of the time; execution +
stops converted most right-theses into losses. Exhibits: QQQ 07-10 finished
725.6 INSIDE [645,750] (thesis dead-on) yet stopped −73/−234; NFLX 07-02 expired
77.59 BELOW the 78/79 short puts = MAX PROFIT at expiry, yet the shadows were
stopped −273/−546 on an intraday spike. **The loss is DOWNSTREAM of the signal,
not in it** — the exact thing the tracker exists to measure. (Note: this is a
PREVIEW I computed via the scorer; `position_thesis_outcomes` is populated by
the job's own first run Mon 17:00 CT — I did NOT hand-write the table, so
Monday's authoritative rows are idempotent-clean.)

**⏳ PENDING PINS (Mon 07-13):** thesis_tracker first run 17:00 CT populates the
table + lands the 6 Aug-21 ICs in_progress + the job records `partial` iff any
close is unscorable (F-A4-1 contract's first live exercise on this job).

**Lane deliverables (READ-ONLY):**
- **L1 calibration-ordering prereqs:** (a) training pool LIVE-ONLY CONFIRMED &
  WIRED (`calibration_service.py:336-337`, flag `CALIBRATION_TRAIN_LIVE_ONLY`;
  8 live vs 91 paper excluded). (b) **CIRCULAR-RISK:** `ev_predicted` maps to
  the CALIBRATED `ts.ev` (view def), and the `COALESCE(ev_raw,…)` guard was
  **REVERTED 06-23** (`20260623010000:58-59`, undoing `20260411000000`). Masked
  ONLY by raw mode — the instant calibration leaves raw mode the prequential
  validator trains on its own output. **Epic's #1 remaining task: restore the
  `COALESCE(ev_raw,ev)` view + a drift-guard test (2nd regression).**
- **L2 F-A1a trigger distance:** **PARKED** — both challengers (neutral,
  conservative) at 0 closed round-trips in the trailing-7d Gate-2 window
  (`evaluator.py:318,408`); structurally can't approach 8 at ~1 close/wk. No
  queue jump; cheap standing re-check before each build session.
- **L3 book-scaling spec (P0-B):** **max_loss ALREADY EXISTS** at
  `trade_suggestions.max_loss_total` (from `_compute_risk_primitives_usd`,
  options_scanner.py:2042 — reuse, don't reconstruct). Write sites:
  `paper_endpoints.py` `_commit_fill` (:2525-2546) + orphan-repair (:2070-2090),
  enrich the existing suggestion SELECT (+max_loss_total, /contracts × filled).
  Migration: +cost_basis +max_loss NUMERIC (nullable, no backfill/H9).
  Consumers: PortfolioAllocator :133-135, RBE :160 (**⚠ UNITS TRAP — RBE keys
  max_loss PER-CONTRACT ×qty; persist a TOTAL and it double-scales**),
  utilization candidate-side :330 (separable). Effort ~0.5-1d. Filed for P0-B.

## 2026-07-11 (Sat ~11:1x ET) — BUILT: F-A3-1 Part B close_reason persistence — QUEUE ⑤ COMPLETE (#1162)

STEP-0: DB 14:53:35Z / broker 14:53:35Z, dow=6, is_open=false — Saturday
CLOSED. **#1162 `a5cabd3` MERGED + H8 VERIFIED** (BE `7bb2c9a3` / worker
`3e30bf87` / worker-background `6bbe69a4`, all @ `a5cabd3`, created 15:14:49–50Z
> merge 15:14:47Z). **NO migration** (rides existing JSONB — order_json +
details_json). The thesis-tracker (I5) prerequisite.

**Three deaths fixed FORWARD-ONLY:**
- **Death B** (LIVE closes lost the reason): the exit evaluator stamps the
  mapped close_reason + granular detail onto the close order's `order_json` at
  stage time (`_close_position`, beside the CLOSE_FILL_GAP stamp); the
  reconciler `_close_position_on_fill` READS it back with a
  `_VALID_CLOSE_REASONS` fallback — replacing the hardcoded
  `alpaca_fill_reconciler_standard`. Coarse ∈ the 9-value
  `check_close_reason_enum`; unmappable → left unset → safe fallback.
- **Death A** (monitor collapsed all to envelope_force_close): 5a maps
  stop_loss / expiration via `_STAGE5A_REASON_MAP` (monitor stop ==
  scheduled stop = `stop_loss_hit`); 5b threads `violation.envelope` →
  `reason_detail`; new `_close_reason_detail()` → thesis enum. New OPTIONAL
  `reason_detail` param on `_close_position` + `_execute_force_close`
  (additive; existing callers unchanged).
- **Death C/D** (ingest never carried it): `+close_reason` in the SELECT
  (fixes `policy_decisions.exit_reason` always-"") + `details_json.close_reason`
  + `close_reason_detail` (from the closing order's order_json), mirroring how
  `symbol` rides.

**Thesis enum** (JSONB-only `close_reason_detail`, UNCOUPLED from the 9-value
CHECK): take_profit, stop_loss, symbol_envelope, daily_brake, weekly_brake,
concentration, stress, dte_threshold, expiration_day, manual, orphan_repair,
reconciler_unknown. Entry gates (streak_breaker, reentry_cooldown) EXCLUDED —
they never close a position.

**Backfill (SUPERVISED — shown SQL + read-back):** true count is **100
trade_closed / 0 had close_reason** (CORRECTS the ledger's stale "~71"). 5
annotate-if-derivable via `details_json->>'position_id'` → semantic
`paper_positions.close_reason` (2 target_profit_hit + 2 envelope_force_close +
1 stop_loss_hit) — stamped `close_reason_provenance=backfilled_from_position_row`.
95 stay HONESTLY BLANK (87 no join key, 8 lost at Death B). Read-back: 5 filled
/ 95 blank / 5 provenance-stamped.

Tests T1–T6 (production routes — reconciler + ingest record builder + the real
mapping fns/constant): 13 pass. Regression 285 pass / 54 skip. Two existing
fakes updated for the new `reason_detail` param (contract).

**⭐ I5 THESIS TRACKER UNBLOCKED** — its charter now reads
`details_json.close_reason` (coarse) + `close_reason_detail` (granular) going
forward.

**⏳ NEW PENDING PIN (Mon 07-13):** the FIRST close after #1162 carries an
honest close_reason END-TO-END (`paper_positions.close_reason` semantic +
`details_json.close_reason`/`_detail` populated) — the single pin that proves
all three deaths fixed at once.

**QUEUE ⑤ COMPLETE — the adjudication queue is EMPTY except LATENTS** (all
filed with triggers): F-A4-2 (retry re-enqueue + reaper, one package) ·
F-A10-1 (999-DTE fabrication + equity-assignment filter — CONFIRMED-but-inert,
`docs/backlog.md:149-154`) · F-A2-1 (GTC pilot scope — CLEAN; audit GTC via
order_json/broker, not the `time_in_force` typed column). Monday pins:
PR2 first-submit (otc1-* accepted) · E7 first-ordering (≥2 survivors) · L5
partial watchlist · F-A3-1 first-honest-close.

## 2026-07-11 (Sat ~10:4x ET) — BUILT: PR2 client_order_id + targeted reconcile (P0-A COMPLETE, #1160)

STEP-0: DB 14:24:13Z / broker 14:24:14Z, dow=6, is_open=false — Saturday
CLOSED. **#1160 `2dc5b0d` MERGED + H8 VERIFIED** (BE `6c5f95cc` / worker
`c7df25bb` / worker-background `bfa6544a`, all @ `2dc5b0d`, created 14:42:52–53Z
> merge 14:42:50Z).

**Migration FIRST (order-of-ops honored):** `20260711143151
paper_orders_client_order_id` — `client_order_id text` + PARTIAL UNIQUE index —
applied + TRACKED + read-back (type=text, unique partial index confirmed)
BEFORE the code merge. Repo file mirrors the tracked version by name.

**P0-A COMPLETE.** PR1 = the invariant (a LIVE submit that raises never
internally fills — holds OPEN in needs_manual_review). PR2 = the targeted
resolution: **the response-lost edge now auto-resolves; operator-manual is the
FALLBACK, not the mechanism.**
- **ATTACH** (additive, one funnel): `deterministic_client_order_id =
  otc1-<l|p>-<paper_orders.id>` (~43 chars, [a-z0-9-]). Persisted at insert
  (paper_endpoints; id is DB-generated → written post-insert) + recomputed from
  the PK in `build_alpaca_order_request` as a bulletproof fallback → threaded
  into `submit_option_order`'s LimitOrderRequest (exclude_none → absent =
  byte-identical). Entry + close + resting-TP GTC through the one
  `submit_and_track` funnel. STABLE across in-function retries (dedup), FRESH on
  re-stage (new row → new PK).
- **DUPLICATE-422 CLASSIFIER** (`submit_and_track`): `client_order_id must be
  unique` → `get_order_by_client_id` → backfill → return submitted; NEVER
  needs_manual_review (kills the false-critical-on-every-legitimate-retry).
- **RECONCILER STEP 1.5** (`alpaca_order_sync`, flag
  `CLIENT_ORDER_ID_RECONCILE_ENABLED` default-ON): NULL alpaca_order_id +
  non-NULL client_order_id → FOUND backfill; 404 → re-arm to `'cancelled'`
  (`_TERMINAL_FAILED_STATUS`, paper_exit_evaluator.py:559 → #1046 re-arms a
  fresh close for closes; dedup-exclusion re-executes for entries). Legacy NULL
  rows excluded by the query → inert until ids exist.

Tests T1–T6 (production paths, no real SDK dep): 14 pass. Regression across
every touched module: 147+4 pass, all compile.

**⚠ DEVIATION (surfaced, not silent):** the ATTACH is UNGATED per the L1 spec
(harmless-additive; exclude_none). Blast radius is every live order, but a
broken attach fails **LOUD + SAFE** (needs_manual_review + critical, no phantom
fill, P0-A holds) and reverts by code. Followed the spec over adding a second
kill-switch; the operator can request `CLIENT_ORDER_ID_ENABLED` if preferred.
**⏳ PENDING PIN — first live submit Mon 07-13:** verify the first live
entry/close carries `otc1-*` AND Alpaca accepts it. If it 422s the
`client_order_id` param → revert #1160.

**⚠ SDK verification gap:** `get_order_by_client_id` (TradingClient) +
`client_order_id` (OrderRequest field) verified by RECON against the installed
SDK source, NOT locally runnable (alpaca absent local + CI; tests mock the
client). Standard long-standing alpaca-py API — high confidence, but Monday's
first submit is the empirical proof.

**PR1 integration-test debt (RESTATED with trigger, not paid here):** the
deferred `_close_position` P0-A hold integration test (drive a LIVE-submit
raise → assert the position is HELD OPEN, needs_manual_review, no internal
fill, then Step 1.5 resolves it) is NOT paid in PR2 — PR2's tests cover the
attach/classifier/reconcile SEAMS, not the `_close_position` hold end-to-end.
**TRIGGER:** pay it the next time `_close_position`'s LIVE-submit branch is
touched, OR on the first real response-lost event (whichever first).

Carried forward: L4 `time_in_force` typed-column caveat (audit GTC via
order_json/broker, not the column) · L5 Monday-partial watchlist
(paper_learning_ingest / iv_daily_refresh all-missing / intraday_risk_monitor) ·
E7 first-ordering-effect pin (Mon scan with ≥2 survivors). Queue after ④:
⑤ F-A3-1 close_reason (L2 spec ready) · latents F-A4-2 / F-A10-1 / F-A2-1.

## 2026-07-11 (Sat ~09:5x ET) — BUILT: E7 viability re-wire on the ACTIVE route (#1158)

STEP-0: DB 13:39:06Z / broker 13:39:11Z, dow=6, is_open=false — Saturday
CLOSED. **#1158 `723f9f5` MERGED + H8 VERIFIED** (BE `b8ed41d7` / worker
`b0513f93` / worker-background `bf3a13dd`, all SUCCESS @ `723f9f5`, created
13:50:49–50Z > merge 13:50:47Z). **Third #1126 instance — closed HONESTLY.**

**What was wrong.** M4 item-0b (07-06) wired the viability bias into
`get_executable_suggestions` — but policy-lab mode returns `_execute_per_cohort`
at the `is_policy_lab_enabled()` early-return (paper_autopilot_service.py:452),
BEFORE that method (:506). With `UNIVERSE_VIABILITY_BIAS_ENABLED=1` armed on the
workers since 07-06, **the bias steered NOTHING 07-06→07-11** (the M4 wiring was
INERT). My M4 tests pinned the orphan — the #1126 class in test form.

**Fix (bias re-wired at the ACTIVE route).** In `_execute_per_cohort`'s
per-cohort fetch: re-rank the pending set with `_viability_rank_key` when armed
(sort-KEY only, positive scores only, stored raev untouched; flag-off
byte-identical). **⚠ SEAM disposition:** `.limit(max_suggestions_per_day)`
MOVED off the DB query to a post-re-rank Python slice — a server-side LIMIT
truncated by RAW EV BEFORE the re-rank, which would strand a biased winner
(SPY ×1.30) below the cut (a 4th #1126 in the fix's clothes). Fetch now: full
pending set ordered raw-EV-desc → Python re-rank → slice to cap. Also corrected
the now-false "executor's real candidacy ordering" comment in the dead
`get_executable_suggestions` (retained for the legacy non-policy-lab path only).

**Route-driving test (first CLAUDE.md §9 application).**
`test_e7_viability_rewire_executor_route.py` DRIVES `_execute_per_cohort`
end-to-end (fake Supabase, assert staged ORDER): armed → [SPY, BAC]
(SPY 20×1.30=26 > BAC 25); flag-off → [BAC, SPY]; seam pin → cap=1 armed stages
the RE-RANKED winner (SPY) AND the DB query is never `.limit()`'d. **RETIRED**
the two M4 source-pin tests: `test_executor_sort_applies_bias_when_armed`
(reimplemented the sort in-test) + `test_production_call_path_is_wired`
(`inspect.getsource` string-pin) — both green while the active route bypassed
the wired method. Kept `test_new_tier_members_present` (real data assertion).

**⏳ PENDING PIN (first-live-observation — NOT shipped-proven):** the flag is
armed AND now wired, so the first REAL ordering effect lands on the next live
scan where ≥2 positive-score candidates survive to the executor — earliest
Mon 07-13 (11:00 CT scan → 11:30 executor). Given the current
1/84-clears-roundtrip reality (SPY only), a ≥2-survivor cohort is itself
uncommon — the pin may not fire for days. Verify then; do not claim proven.

docs: I6 one-liner correction applied to the v1.2 report (rides this PR).

**Latents verified this session (READ-ONLY lanes — filed backlog lines STAND):**
- **F-A10-1 CONFIRMED-but-INERT:** 999-DTE fabricate-on-missing at
  `paper_exit_evaluator.py:158` (0/83 positions carry it; `nearest_expiry`
  typed-date always populated; legs fallback always resolves) · option-only
  sync filter at `alpaca_client.py:540` (broker: 0 equity positions ever, 0
  OPASN/OPEXC/JNLS events). Neither needs more than `docs/backlog.md:149-154`.
  H9 fix (reject/flag unpriceable expiry vs `return 999`) stays correct-to-do,
  no signal demanding it.
- **F-A2-1 CLEAN:** 6 GTC orders EVER, 100% on the live-routed promoted
  champion (QQQ×3 / MARA / SOFI), 0 on any shadow cohort. ⚠ data-fidelity
  caveat filed: `paper_orders.time_in_force` typed column reads `DAY` for all 6
  (broker + `order_json->>'time_in_force'` say `gtc`) — future GTC audits query
  `order_json`/broker, NOT the typed column.

**HYGIENE MISS (self-logged):** confirmed the flag via `list_variables` (full
var dump incl. secrets into the transcript) — the 07-06 ledger already recorded
it armed; should have trusted that record. env-check-secrets-hygiene STANDS;
this MCP has no single-var read → do NOT call `list_variables` for one flag.

Queue after ③: ④ PR2 client_order_id (L1 spec ready) · ⑤ F-A3-1 part-B
close_reason (L2 spec ready) · latents F-A4-2 / F-A10-1 / F-A2-1 (filed).

## 2026-06-15 — Phase B (structural mark-validity) shipped + QQQ phantom-stop saga

- **Phase B MERGED #1067 → main `ad8ce0f`**, live both services (worker
  `2c8fca1d`, worker-background `b5c05eb1`) container start 20:55:06–07Z, CI
  green (run 27575798526). Two commits: (1) structural mark clamp
  (`risk/mark_validity.py` + exit-eval-seam wiring in
  intraday_risk_monitor + paper_exit_evaluator) — rejects |mark|>wing OR
  implied_loss>max_loss, fail-closed, NEVER suppresses a real stop; (2)
  EXIT_EVAL_DEBUG honesty (prints the cohort tp/sl/dte the decision uses, not
  `_DEFAULT_*`). +18 tests; full-suite zero Phase-B regression (31 pre-existing
  local fails == baseline). Commit 3 (resting-TP pre-cancel) DROPPED MOOT
  (broker cancel-ack 14:15:08.884Z before stop submit). Commit-2 executable-
  rewire DECLINED (false premise: decision is stateless/mid and fired
  correctly; the −80.5-vs-48.3 was the debug line interpolating
  `_DEFAULT_STOP_LOSS_PCT` 0.50 vs the cohort 0.30).
- **QQQ saga (book `6798e58f`, aggressive condor 5-wide/1.61cr/max-loss $339):**
  13:30Z monitor force-closed on a PHANTOM stop, mark −7.305 / implied
  −$569.50 (impossible). The 7.30 close order was BROKER-REJECTED → **zero
  loss booked** (luck, not a control — the new clamp is the control).
  CLOSE_REARM deferred re-close; mark recovered; QQQ genuinely rallied →
  **legit corroborated stop filled 14:15 at 2.34 / −$73** (corroboration
  14:15:07Z divergence_frac 0.089; single broker submission `1bcc6e83`).
- **Data correction (supervised, operator-GO, like prior corrections):**
  reentry_cooldowns `3d8a5820` realized_loss **−569.5 → −73.00** (1 row,
  guarded `AND realized_loss=-569.5`). The bench (QQQ → 06-16 13:30Z) was
  always correct; only the metadata carried the phantom.
- **STEP-4 audit (decision-path candidates flagged, NOT auto-fixed → backlog
  P2):** config.py DEFAULT_CONFIGS stops looser than live DB (fail-open looser
  on cohort-load failure); `exit_plan_agent.py:43,50` hardcodes 0.50 wired via
  workflow_orchestrator:3142. CLAUDE.md §5 stop references are ACCURATE (no doc
  fix). Two deferrals filed: executable-for-stops (observe-only) + cooldown
  realized_loss-from-fill (low, obviated by the clamp).
- **PENDING (do not act tonight):** 21:20Z ingest lands the −$73 QQQ close;
  expect `is_paper=true` (wrong) — the known Phase-1 A3 item, caught by the
  supervised historical correction, not a surprise. Post-epoch closes 5 → 6
  after tonight (relearn at ≥8).

## status:shipped — 2026-06-09 v4 seven-area run (PRs #1044–#1049, all live on worker 4bd5779)

- **[#1044] Pre-entry concentration BLOCK froze sequential accumulation** — share-of-book
  `concentration_symbol` check on a 1-position book = 100% > 40% → blocked ALL entries incl.
  diversifying ones. Replaced (small tier, explicit flag) by the pro-forma 85% total-utilization
  gate; concentration demoted BLOCK→WARN. (e329bf0)
- **[A1+A3+A4 → #1045] Calibration circuit frozen + strategy-asymmetric** — daily job silently
  no-opped 25 days (7 outcomes < MIN=8 in fixed 30d window); consumer served the frozen 05-15 blob
  with no TTL; apply_calibration silently defaulted ×1.0 for uncovered strategies (puts raw while
  calls halved; 2 recorded gate flips F/AAL). Fixed: window escalation 30→60→90, consumer TTL +
  calibration_stale alerts, `_overall` fallback, ops_health OUTPUT_FRESHNESS registry. (24533a8)
- **[A2 → #1046] Terminal-'cancelled' close orders permanently disarmed all exits** — BUG-C
  overcorrection; one broker-rejected/manually-cancelled close satisfied the idempotency guards
  forever; only the 'watchdog_cancelled' string accident kept retries alive. Fixed: freshness
  window (30min) + retry budget (3/4h) + critical exit_protection_disarmed alert; stale rows
  re-arm. (c63943c)
- **[A6 → #1047] Spread gate mis-keyed to account tier** — crossing the $1k micro→small cliff on
  2026-05-20 silently tightened 0.30→0.10 universe-wide (~250 would-pass kills/11d; killed the
  sub-$60 class behind 3 of 5 live fills). Fixed: dispatch = micro OR underlying <
  PRICE_CLASS_SPREAD_CUTOFF ($60). (02e1020)
- **[A7 → #1048] Stop-side cadence asymmetry** — 15-min monitor enforced cohort TPs but evaluated
  stops at the flat 0.50 default; cohort stops (0.15/0.20/0.30) checked only 2-3×/day; shadow books
  had no envelope backstop and overshot configured stops by $211.80 on 06-08. Fixed: cohort-aware
  stops at monitor cadence, fail-safe to default. (edb70d6)
- **[A5 → #1049] order_sync Step-3 unbounded reconcile** — every historical filled order + one
  pos-check round-trip per close-engine row, q5min (~52k queries/14d, #1 compute sink). Fixed:
  set-based, scoped to open positions. (4bd5779)

## status:reported — open tickets (also EXCLUDED as new findings; refining with new data is allowed only if the refinement changes the action)

- **Dismissed-status funnel gap** — `trade_suggestions.status` never reflects execution (filled
  orders reference `dismissed` suggestions; morning sweep overwrites history); the
  suggested→staged→filled funnel is uncomputable from status. Observability-only.
- **Dead instrumentation fields** — `learning_feedback_loops.entry_mid/exit_mid/
  pnl_execution_drag/pnl_alpha` populated 9/72 rows (90d), zero live readers.
- **Calibration clamp limitation** — [0.5,1.5] cannot represent a negative-realized segment
  (put ratio −3.8 floors at 0.5); calibration under-corrects catastrophic segments by design.
- **EXPECTED_JOBS coverage** — ops_health monitors 4 of ~15 scheduled jobs; nothing watches the
  scheduler/watcher itself. Partially subsumed by the OUTPUT_FRESHNESS registry (#1045) — the
  remaining work is adding entries/jobs, not a new finding.
- **PDT-P0 closure pending** — `alpaca_client.get_account()` int(None) coercions break when
  Alpaca removes the placeholder PDT fields (~2026-07-06). Ticketed P0 in docs/backlog.md.

## status:shipped — 2026-06-10 evening runbook (Phases B+C; PRs #1051 #1052, live on worker 93d19c6)

- **[v5-A1 → #1051] Honest debit-spread PoP at source** — both halves (scanner passes legs
  side→action; calculate_ev passes credit for debit) + CALIBRATION_EV_EPOCH (2026-06-11; pre-fix
  prediction/outcome pairs never calibrate the post-fix predictor) + deploy-time empty-blob reset
  (raw predictions serve until post-fix closes accumulate — calibration is in RAW MODE by design;
  a calibration_stale alert after ~06-20 is the reminder, not a defect). NFLX 06-08 fixture pinned
  both ways (0.6581→0.4840; +95.67→≈−26 SIGN FLIP); credit math pinned unchanged. (756627e)
- **[v5-A3 → #1051] Learning-store dedup + live dimension** — position-level dedup (suggestion_id
  key; order-id retained for legacy), is_paper resolved from routing (live-routed + alpaca_live →
  False) + details_json.routing/position_id; floor 04-13→04-16. Historical dup rows NOT cleaned
  (epoch excludes them from calibration; conviction legacy rollups still see them — ticketed).
- **[06-10 A1 diagnostic → #1052] Stage-quote FEED DIVERGENCE** — entry validator read Polygon-only
  while the scanner priced via the truth layer; 3/3 stage attempts on day one of #1047 died on a
  leg OPRA quoted 2.15×428/2.39×565 (83 trades). Fix: fetch_fn = truth-layer primary → Polygon
  fallback + divergence WARNING; all-sources-dark still raises EntryQuoteUnpriceable.
  Flag ENTRY_QUOTE_SOURCE_ALIGNED default-ON. (93d19c6)
- **Riders (#1051):** [UTILIZATION_GATE]/demotion/[EXIT_EVAL]-cohort lines INFO→WARNING (the 06-10
  observability miss); blocked_reason/_detail stamped on stage-time rejections (quote/cooldown/
  utilization) — closes the swept-as-stale gap. NOTE: the lying [EXIT_EVAL_DEBUG] threshold print
  itself remains TICKETED (not fixed); what shipped is the positive cohort-config WARNING line.
  The runbook's INTRADAY_COHORT_STOP polarity rider was MOOT — #1048 shipped default-ON.

### Pending verifications added 2026-06-10 evening

- ✅ VERIFIED 2026-06-11 10:00Z (M2): raw mode persisting as designed — calibration_update
  succeeded with users_updated:0, escalation tried 30/60/90d all sample_size 0 (epoch bounds
  every window; zero pre-epoch leak), last_write_age_days 0.6 (no false stale alert); latest
  blob still the 06-10 20:27Z empty reset. Consumer serves {} → 16:00Z scan scores raw.
- 2026-06-11 16:00Z: FIRST HONEST-EV CYCLE — record per-candidate ev_raw/pop_raw deltas vs prior
  days (debit EVs should drop ~2×; entries may drop to zero = CORRECT). Calibration ratio should be
  1.0 (raw mode — empty blob).
- 2026-06-11 16:30Z: if a candidate stages, watch for [ENTRY_QUOTE] FEED DIVERGENCE warnings (the
  XLE class should now price via truth layer instead of rejecting) and blocked_reason stamps on any
  rejected rows.
- Nightly-audit queue: CLOSE-side Polygon-only quote validation check (same divergence class).

### 2026-06-10 v5 FULL baseline run (all adversarially verified CONFIRMED; report `audit/reports/2026-06-10.md`)

- **[A1 2026-06-10 — CRITICAL, see ALERT-2026-06-10.md] Debit-spread PoP/EV = raw long-leg delta** —
  breakeven interpolation (ev_calculator.py:54-70) unreachable from the only production call path:
  scanner omits `legs` (options_scanner.py:3411) AND `credit=premium` is passed only for credit
  strategies (ev_calculator.py:165) → PoP falls to `abs(delta)` (:91-92). Sign-flips live entries
  (NFLX 06-08: EV +95.67 → ≈−26/ct; XLF 06-09: +55.92 → ≈+3..6/ct, below the $15 gate — passed on
  inflated PoP alone). Commit 9a2cef1 (04-12) claimed this exact fix but never wired the call site;
  test file module-skipped (#775), zero active coverage. Fix = (a)+(b) together (legs w/ side→action
  map + credit for debit), MUST sequence with reset/relearn of the floored debit calibration
  segments (06-10 blob halves both; uncoordinated fix double-corrects ≈0.24).
- **[A2 2026-06-10] Daily-loss envelope realized-blind; entry circuit breaker blind twice** — all
  FOUR check_all_envelopes feeders pass open-book unrealized only (intraday_risk_monitor.py:221,
  paper_autopilot_service.py:228, paper_mark_to_market.py:103, workflow_orchestrator.py:2834 passes
  neither), violating the risk_envelope.py:573 contract: realized stops vanish from the 8% daily
  brake (06-08 −$84 = 47.3% of budget invisible to ~22 subsequent cycles); sequential stops can
  never trip it (4×−3% = −12%/$266.50 with no brake); CB omits weekly_pnl (:256-261 → 0.0 default)
  and skips ALL envelope checks on an empty book (:227). Fix: broker-true daily (equity−last_equity,
  mirroring weekly; never fabricate) + feed all four sites + wire weekly into CB + empty-book
  aggregates (companion to the daily fix).
- **[A3 2026-06-10] Learning store double/triple-counts and can't tell live from simulator** —
  dedup keyed on closing-order id with position-level pnl (paper_learning_ingest.py:224-232,:339):
  ADBE f6eee0e9 ×2 / AMD 91d4e119 ×2 = 76.5% of training dollars; NFLX whipsaw thesis ×3 (live
  −$42/ct broker fill vs −$91/ct simulator forks); is_paper hardcoded True (:375,:394; live ingest a
  no-op stub); calibration unscoped to cohorts (calibration_service.py:258-267). The 06-10 10:00Z
  post-#1045 write trained on exactly this set (60d, N=18 claiming −$4,281.50 vs 12 deduped
  real-broker outcomes −$2,017); the frozen 05-15 blob was ALSO duplicate-trained (LONG_CALL n=10
  incl. 2 AMD dups). Fix: position-level dedup, CALIBRATION_PNL_FLOOR_DATE→2026-04-16, live/shadow
  dimension at ingest (position_scope pattern). Runner-up: pop denominator asymmetry (:299-315) +
  dead DTE segmentation (every blob ever = {_all, unknown}).
- **[A4 2026-06-10] Ops-health alert delivery 0% lifetime** — all 5 detection classes route only to
  send_ops_alert_v2 (ops_health_check.py:111-274; zero risk_alerts writes); OPS_ALERT_WEBHOOK_URL
  unset on worker AND BE → suppressed no_webhook inside status=succeeded (916 runs / 869 unhealthy /
  0 alerts EVER since 2026-01-22); severity map lacks "critical" (→0 < warning,
  ops_health_service.py:942-946) so even a webhook wouldn't deliver job_never_run; the #1045
  OUTPUT_FRESHNESS watcher inherits the dead tail. Fix: dual-channel to risk_alerts (error/critical,
  existing alert() helper + fingerprint cooldown) AFTER fixing the chronic data_stale false positive
  (30-min threshold vs once-daily jobs) and the severity map. Runner-up: scheduler_heartbeat written
  but absent from EXPECTED_JOBS — scheduler death undetectable.
- **[A5 2026-06-10] Hot-queue head-of-line blocking puts the loss monitor last in line** — monitor +
  order_sync share the serial otc worker with unbudgeted suggestions_open (no internal time budget;
  10-min RQ ceiling; options_scanner has zero deadline constructs). 06-03: 422.7s scan (70% of
  ceiling, provider latency — same workload 14.9s on 06-08) → order_sync waited 417.1s, monitor
  129.0s; daily 16:00Z grid collision dequeues the monitor LAST (25-55s, live capital open 06-09).
  Fix: route monitor+order_sync to a dedicated queue on the idle worker-background ("rq worker risk
  background") gated on read-back + monitor-cadence freshness alert (mis-route = silently disabled
  loss protection); + ~120s scan budget with loud exit_reason.
- **[A6 2026-06-10] Entry-budget stack book-blind: open positions contribute $0** — RBE
  (risk_budget_engine.py:54-57,156-208) and PortfolioAllocator._sum_open_cost_basis
  (portfolio_allocator.py:116-144) read fields absent from the 32-col paper_positions schema →
  usage:0 in 4/4 cycles since 06-08 on a non-empty book; remaining overstated 2.16× (06-08) / 1.41×
  (06-09) RBE-side; the documented 85%-less-cost-basis deduction is a no-op; the :2340 exhausted
  guard cannot fire from usage accumulation; underlying_allocation has ZERO consumers though
  utilization_gate.py:46 cites it as retained; the workflow_orchestrator.py:2179-2186 comment claims
  "under-counts slightly" + a nonexistent "backlog #80". Fix: shared paper-aware position-cost
  adapter (avg_entry_price×100×qty debit; H9 fail-loud) + ONE cap-semantics policy (40% vs 85% vs
  RISK_MAX_UTILIZATION_PCT) + wire-or-delete underlying_allocation. Runner-up: counts.universe_size
  = scanner_emitted (3 conflation sites) — universe regressions invisible in the funnel;
  rank_and_select greedy BREAK (small_account_compounder.py:280-286).
- **[A7 2026-06-10] Time-scaled profit capture unreachable in production** —
  _time_scaled_target_profit_pct's sole caller is the cohort-resolve-FAILURE fallback
  (paper_exit_evaluator.py:397); both production exit paths use flat cohort tp via
  build_exit_conditions (:421-423); the champion lookup resolves any position → ~100% of production
  positions live on the flat bar (aggressive +50% for life, incl. the max-theta window where the
  documented curve drops to ~0.245); CLAUDE.md Exit-thresholds asserts the opposite; the curve has
  zero test references (flat IS pinned). BAC 06-04 fire (+18.8% of $1,020 4ct entry) explainable
  only by the flat bar. Realized cost $0 so far (no winner aged into divergence). Fix: doc truth-fix
  + optional flag-gated min(tp, time_scaled) wiring, shadow-first, capture-earlier-only. Runner-up:
  no time-stop for stalled theses (dte_threshold only at 7 DTE, scheduled path only);
  paper_eod_snapshots accrues phantom post-close rows during manual-close reconciliation lag.
- **[A8 2026-06-10] Negative decisions 100% outcome-unmeasured (counterfactual lens adopted →
  audit/area8.md)** — ~2,384 rejects/blocks/dismissals per 30d vs 6 learned closes (~400:1);
  calibration trains only on gate-survivors (calibration_service.py:258-259); d8_v1 rejection
  capture lacks expiry → 0% of 2,361 reject rows repriceable (options_scanner.py:295-305); executor
  risk blocks stamp nothing (paper_autopilot_service.py:269-275; 06-09 XLF blocked_reason null);
  policy_decisions captured 1 rejected outcome/30d; gate-bug detection latency historically 11-25d,
  code-audit-only. 06-09 blocked XLF hand-repriced +$32..$66 in <1 day (point-in-time; +$24..$42 at
  re-read) vs held book ≈−$30. Fix (additive only): expiry in d8_v1 capture + nightly read-only
  counterfactual marker on the 100%-repriceable dismissed/blocked suggestions + per-gate
  reject-vs-accept metric with info alert at ≥3 consecutive inverted windows (never auto-loosen).

## status:reported — 2026-06-11 NIGHTLY run (report `audit/reports/2026-06-11.md`)

- **[N1 2026-06-11] CLOSE/internal-fill quote reads still Polygon-only (#1052 divergence class, close
  side)** — outcome of the ledger-queued nightly check. Stage-time combo quote (`paper_endpoints.py:645`,
  feeds TCM staging values for ALL orders incl. closes) and the internal fill engine's fresh-quote read
  (`:1179`, prices every internal/shadow fill) remain legacy `_fetch_quote_with_retry`; #1052's
  `_aligned_leg_quote_fetch` is wired ONLY into `_validate_entry_quotes`. A Polygon-dark-but-OPRA-real
  leg (the 06-10 XLE class) on a shadow CLOSE → TCM missing_quote_fallback fill at a stale
  staging-derived price (`:1219-1230`) or a stalled close — biases shadow learning outcomes/D6.
  LIVE path insulated (monitor marks = MarketDataTruthLayer `intraday_risk_monitor.py:462-487`; live
  fills = broker). Impact prospective (zero close orders since); severity LOW-MEDIUM. Fix: reuse the
  aligned fetch at both sites, observe-first.
- **[N2 2026-06-11] Stage-time skip stamping gap (refinement of the dismissed-status gap + #1051
  rider — changes the action)** — per-cohort symbol-dedup (`paper_autopilot_service.py:746-770`) and
  user-level dedup/min-edge/min-score filters (`:390-427`) skip with `continue` at logger.INFO and
  never call `_stamp_blocked_reason` (stamps cover only cooldown/utilization/quote, `:850-894`) —
  suggestions stay pending/NULL and get swept. Observed: both 06-10 16:30Z NFLX forks (aggressive
  `ff1f65b7…`, neutral `2c1d7f79…`) unprocessed + unstamped; dedup is the high-probability cause
  (both cohort books hold NFLX) — per-event attribution HYPOTHESIS (INFO line unretrievable),
  stamping gap itself code-certain. Severity LOW, observability-only. Fix: stamp
  `symbol_already_held` / `edge_below_minimum_at_stage` / `below_min_score` at the three skip sites.

## status:shipped — 2026-06-11 incident arc + post-close gate (PRs #1055 #1056 #1057 merged; #1058 #1059 at CI)

- **[06-11 incident → #1055] Credit-OPEN mleg sign** — first CHOP condors submitted +1.54/+1.43,
  live gateway instant-rejected in 4ms (the #101 close class, open side). Stamp `is_credit_open`
  from `_net_mid_cost` + handler flip + coherence guard. Merged mid-day by operator;
  LIVE-VALIDATED same session: QQQ filled −1.61 (limit −1.54, +$7 improvement), SPY −1.48
  (−1.43, +$5), third condor accepted+rested at −1.28; 12/12 legs priced by the #1052 truth
  layer (Polygon dark on ALL of them).
- **[06-11 incident → #1056] Fill-commit raw signed entry** — `_commit_fill`/`_repair` stored
  Alpaca's SIGNED filled_avg_price into avg_entry_price/max_credit (violating mark_math's
  absolute contract) → phantom −$300 unrealized on a +$10.50 position → 16:30Z phantom −22.8%
  daily breach force-closed the ENTIRE live book ($0 realized only because the close limits were
  mis-signed too). `_abs_entry_premium`/`_weighted_abs_entry_avg` at all six write seams +
  round-trip regression on the day's actual numbers.
- **[06-11 incident → #1056] Close-path signed limit** — short-structure closes staged the
  SIGNED mark as the limit (−1.39 buy-to-close): gateway reject + an unfillable RESTING close
  that satisfied idempotency and DISARMED exit protection. `_close_limit_and_direction`
  (unsigned magnitude; structural direction; loud disagreement) + handler inverse guard. Also
  fixes the internal-fill realized-P&L sign — the 19:00Z shadow stop close recorded +$2,369.22
  on a −$234.78 trade (the signed limit double-negated through the synthetic close leg).
- **[06-11 V4 gate trail → #1057] Utilization gate signed netting** — `committed=$56` while the
  broker held $1,365 (condor credits netted against the NFLX debit). Per-structure commitment:
  net-debit = net cost basis; net-credit = margin basis (max wing width × 100 × qty, matches
  Alpaca's $1,000 hold); naked/unboundable → fail-closed.
- **[06-11 trace — fix 06-12] Live close double-submission** — `_stage_order_internal`
  broker-submits alpaca-mode orders itself AND `_close_position` submits the same row again;
  the second call's pre-cancel kills the first broker order (2 broker orders per close, first
  canceled ~0.45s in). Never seen before: no live system close had ever executed. Writeup
  `docs/double_submit_close_trace.md`; single-submitter staging param + regression queued 06-12.
- **[v5-A2 → #1058] Realized-blind daily brake** — min(open-book proxy, broker
  equity−last_equity) into all four feeders + weekly into the circuit breaker + empty-book
  de-gates (breaker + MTM). Same-day empirical: real −8.3% day (equity 2075.42 vs 2263.85) read
  as ≈−4% by the proxy. Tightens-only.
- **[v5-A4 → #1059] Ops alert delivery** — dual-channel: risk_alerts PRIMARY (critical→critical,
  error→high) + webhook secondary; severity map gains "critical" (was 0 → the most severe class
  always suppressed); data_stale ALERT market-hours-gated (nightly staleness is structural);
  canonical alert() accepts "high" (was silently downgrading); synthetic_delivery_test payload
  hook for the end-to-end proof.

### Data corrections (2026-06-11, operator-"go" precedent; all documented in-session)

- Live QQQ `6798e58f` / SPY `a5393e2b`: avg_entry_price/max_credit ABS-corrected (−1.61/−1.48 →
  +1.61/+1.48). Applied ~90s after the 16:30Z monitor had already fired on the phantom.
- Shadow QQQ `85db73c8`: realized_pl +2369.22 → **−234.78** (arithmetic truth: credit 1.5246×7
  entry, 1.86 buy-back) BEFORE the 21:20Z learning ingest (learning_ingested was false — zero
  contamination); neutral-cohort cash_balance −$2,604 (the close's fill event credited +1302
  instead of debiting 1302).

### 2026-06-13 combined run (week-review + 8-area audit + CLAUDE.md refresh)

WEEK VERDICT (06-08→06-13): live realized **−$109** (a9f977bf NFLX −84,
7f604f7a NFLX +48, a5393e2b SPY −45, bc399a4f MARA −28), live open = QQQ
condor 6798e58f broker-unrealized **−$45**; shadow realized −$920 (mark-bias
caveat). Fees negligible (TAF pending $0.57). Modeled-vs-realized EV gap:
every staged EV positive (+26…+96), aggregate realized deeply negative;
post-epoch clean read ≈ −$67/trade optimism (raw-mode, uncalibrated —
expected, relearn ~06-20). Live MARA round-trip (18:25→18:46Z) confirms the
N1/UnboundLocalError fix unblocked the 16:00Z funnel.

SETTLED THIS RUN — do not re-find (folded to docs/backlog.md, origin 06-13):
- A1: post-#1051 EV ordering weakly agrees (2 winners carried the highest
  staged EV); uniform +EV optimism is raw-mode, not a defect. No action.
- A2/A4: ghost_position sweep flags shadows (no live-routed filter,
  `alpaca_order_sync.py:245`) → 73 shadow-noise alerts/wk burying real
  desync. → P2.
- A3: calibration healthy in raw mode (job ran 06-11/06-12 `insufficient_data`,
  last real write 06-10; 5/8 post-epoch closes). is_paper tags ALL learning
  rows paper incl. live closes → P2.
- A4: OUTPUT_FRESHNESS watches ONE table (`ops_health_service.py:79`);
  ingest/mark-refresh stalls silent. → P2.
- A5: this run respected budgets (≤10 Part-1 SQL, ≤4 broker, 0 web, archived
  the 240k backlog unread). Largest avoidable cost would have been reading
  it — avoided.
- A6: stage deaths dominated by REAL spread_too_wide_real (323) /
  no_fallback (359), not feed artifacts; #1052 working. chain_mechanics
  anomaly 24×/wk = legacy spread_pct deep-ITM edge (observability noise) →
  P2.
- A7: hold-time bimodal — debit spreads ~94–116h, condors 5–35h, live MARA
  0.3h (cohort-stop velocity). Next binding velocity constraint = the
  one-shot/day executor (P1), not fees/cooldowns.
- A8: XLE dead-leg rejects (#1038, settled 06-10) are UNMARKABLE on the
  executable side — counterfactual indeterminate by doctrine; GLD reject was
  an HONEST save (spread_debug total_ev −934). Additive proxy field →
  RESEARCH.
- TOP-3: (1) OUTPUT_FRESHNESS expansion, (2) ghost-sweep shadow scoping,
  (3) close-side quote check. No conflicts; (1)+(2) share the order-sync/ops
  surface.

PENDING VERIFICATIONS (06-13 night / next session):
- CLAUDE.md refresh PR merges per the W2 gate (CI green on the doc PR; main's
  last gate was clean at #1064 23:49Z). After merge: H8-verify both workers
  recycled to the new SHA; the DEGRADED + raw-mode-reset lines fire once on
  the new container (designed, not an incident).
- backlog.md reorg: full pre-0613 history preserved in
  docs/backlog_archive_2026-06-13.md (move-don't-lose).

## status:reported — 2026-06-15 NIGHTLY run (report `audit/reports/2026-06-15.md`)

**NO NEW FINDINGS.** Quiet weekend (markets closed 06-13/06-14); window 06-13
run → 06-15 05:03Z. Clean operation: both workers on `5778760`/#1065
(CLAUDE.md refresh, dual-parity deploy 06-13 03:15:47Z — the 06-13-pending
merge landed); weekend job silence (only `paper_exit_evaluate` 06-13 00:28Z
[placed the resting TP] + `phase2_precheck` 06-15 05:00Z, 0 failures, 0 stuck
rows); **H11 risk_alerts critical/high since 06-13 = ZERO**; broker healthy
(equity $2,179.15, OBP $1,804.15, one live QQQ 07-10 condor −$45 with resting
TP `550fccc5` GTC 0.81 alive/untouched). Flags clean, no regressions.

- **OVERTURNED CANDIDATE (verify-before-asserting):** SPY `manual_bench` cooldown
  (06-12 15:46Z, correctly valued −45, until 06-15 13:30Z) looked like a
  cohort-stops-don't-auto-cooldown gap → **already fixed in deployed code**:
  `intraday_risk_monitor.py:355` → `_write_cohort_stop_cooldown` (`:757-772`,
  `reason="cohort_stop_force_close"`), shipped #1062. The manual bench predated
  the fix (event on worker 5681919). Not a finding.

VERIFICATIONS CLOSED THIS RUN (do not re-find):
- ✅ **PR #908 live credit-mleg-close** — SPY iron condor close `1f444239`
  (06-12 15:30:07Z): buy-to-close at POSITIVE limit 1.96, filled POSITIVE 1.93,
  single order, instant clean fill, no Sign-incoherent raise → realized −45.
  Credit structure closed correctly. **Pending since the first ledger list — DONE.**
- ✅ **Double-submit pre-fix confirmed** — QQQ condor close attempts `fc1625f1`
  (06-12 13:30:07Z submit→cancel 0.6s) + `0675f969` (13:30:08Z, watchdog-cancel
  13:35Z) = documented pre-cancel double-submit on worker 5681919 (#1064
  single-submitter deployed 06-13 00:20Z, after). SPY/NFLX/MARA = single orders
  (instant fills). Single-submitter fix deployed but UNEXERCISED on a resting close.
- ✅ **#1034 TP fires write price-normalized corroboration rows** —
  `exit_mark_corroboration_observations`: NFLX TP 06-12 15:15Z (4.7355/+314.70 →
  4.131/**+133.35**, divergence_frac 0.086, `corroborated_allow`); SPY stop 15:30Z
  (`stop_loss_never_suppress`); QQQ TP 13:30Z.
- ✅ **Corrected-NFLX ingest** — `1e2dd73f` realized_pl=133.35; outcomes_v3 LPD pair
  sums +181.35 = 133.35 + 48.00. The +314.70 fiction did not propagate.
- ✅ **#1056 write-side** — DB QQQ condor `avg_entry_price=1.61` (positive); coherent.

PENDING VERIFICATIONS (carried — all fire on today's 06-15 RTH, the first
session on #1062+/#1065 code after the weekend):
- **#1034 corrected normalization + Stage-2 enforce, FIRST FIRE.** Every
  corroboration row in-window is PRE-fix (worker 5681919); the QQQ 13:30Z phantom
  (mark −0.65/+96 vs achievable −7.6/**−599**) scored divergence_frac **0.0604**
  `would_suppress=false` — the exact value CLAUDE.md says the 06-12 fix re-scores
  to ~0.91. `EXIT_MARK_SANITY_ENFORCE_ENABLED=1` deployed but never observed on a
  live fire. A phantom TP today should re-score ~0.91 → SUPPRESS (stops never).
- **Cohort-stop auto-cooldown FIRST FIRE** (`_write_cohort_stop_cooldown`, #1062) —
  on the next cohort-stop force-close; should write `reason=cohort_stop_force_close`
  (no manual bench needed).
- **Resting-TP exit-evaluator deferral** (`skipped_resting_tp_owns_profit_side`) —
  first QQQ-condor monitor tick today (resting TP placed post-close 06-13, no RTH
  monitor since).
- **#1058 `[EQUITY_STATE] realized-blind gap`** — 06-12 RTH logs aged out of Railway
  retention; re-check on today's session.
- **#1065 DEGRADED + raw-mode-reset lines** — fire once on the first CONVICTION read
  = first scan (16:00Z); no scan since the recycle.
- **#1059 synthetic-proof wiring** still unmerged (`9c957d9`); webhook still deferred.

### Data corrections (2026-06-12 night, operator-ordered; same precedent as 06-11)

- Shadow NFLX ×3 `1e2dd73f` (conservative): realized_pl **+314.70 → +133.35** at 18:00:58Z,
  BEFORE the 21:20Z learning ingest (learning_ingested was false — zero contamination).
  Basis: its OWN 15:15:04Z corroboration row — triggering mid 4.7355 vs achievable 4.131
  (P86 sell at bid 6.14 − P79 buy at ask 2.009) → (4.131 − 3.6865) × 300 = 133.35. The
  $181.35 delta was the optimistic-mid fiction; the code-side fix (internal fills at the
  EXECUTABLE side + fill_quality flag) ships tonight so this is the LAST manual instance
  of the class. Guarded UPDATE (realized_pl=314.70 AND learning_ingested=false) — idempotent
  against any concurrent session. paper_orders row 4d175584 left as-is (historical record of
  what the old fill simulation did; order_json carries no fill_quality — pre-fix row).

### Pending verifications added 2026-06-12 night

- Post-21:20Z TONIGHT: learning ingest consumed realized_pl **133.35** (not 314.70) for
  `1e2dd73f` — verify learning_trade_outcomes_v3 / learning_feedback_loops row.
- Morning signatures (06-13): (a) any TP fire writes a corroboration row with the
  price-normalized divergence; phantom → `exit_tp_suppressed_phantom_mark` alert + NO close
  staged (Stage-2 live). (b) exactly ONE broker submission per close (single-submitter,
  745ced4). (c) `[EQUITY_STATE]` successful broker daily fetch on the first monitor cycle —
  no "broker daily P&L unavailable" line (d68029c). (d) any internal/shadow fill carries
  order_json.fill_quality + the `[INTERNAL_FILL]` WARNING line. (e) the QQQ resting TP
  (buy-to-close GTC, limit 0.81) alive at the broker, untouched by the watchdog, visible to
  the evaluator as `skipped_resting_tp_owns_profit_side` if its TP condition trips.
- 15:30:08Z `paper_order_marked_needs_manual_review` alert: RESOLVED BENIGN — it was the
  second submission against the already-filled SPY close (intent-mismatch reject, the
  double-submit class); 745ced4's terminal-reject classification returns these gracefully
  without the manual-review mark. No operator action on the order itself (SPY close filled
  clean at 1.93, realized −45).

### Pending verifications added 2026-06-11 night

- 06-12 first credit fill row: avg_entry_price/max_credit POSITIVE (the #1056 write-side proof).
- 06-12 closes: positive limit on credit-position closes, no `Sign-incoherent` raise; the
  double-submission pattern persists (documented) until the 06-12 single-submitter fix.
- #1058 signature: `[EQUITY_STATE] realized-blind gap` WARNING whenever broker day < proxy.
- #1059 signature: `ops_*` rows appearing in risk_alerts (first ops delivery ever); synthetic
  proof row written + deleted post-deploy.
- ✅ #1048 VERIFIED 2026-06-11 19:00Z — first real cohort-stop fire: shadow QQQ 7-lot breached
  the neutral stop (−$235 vs −$213 threshold) and closed intraday at monitor cadence (the
  realized-P&L sign corruption it exposed is the #1056 internal-fill item above).
- ~~Railway auto-deploy MISSED bcbfb0c~~ **ERRATUM (06-12): it self-deployed ~10 min after
  merge** (SUCCESS 20:18:46Z) — the hook lags up to ~10 min after rapid merges and the
  listing API lags further; no forced recycle was required (the marker-var attempts errored
  client-side but one landed harmlessly, same SHA). The durable lesson stands: H8-verify the
  worker SHA before trusting behavior to a merge — but don't declare a deploy missing inside
  the lag window.

## Pending verifications (not findings — check, then update here)

- ✅ VERIFIED 2026-06-10 10:00Z: first calibration write post-#1045. job_runs verbatim:
  `users_updated:1, users_skipped:0, user_details: attempts [{30d insufficient_data n=7},
  {60d ok n=18}], window_used:60` — the escalation worked exactly as designed on the first
  run, ending 26 days of silent no-ops. Fresh calibration_adjustments row 10:00:03Z
  (total_outcomes 18) with top-level keys `LONG_PUT_DEBIT_SPREAD` (first time ever:
  normal/_all ev_mult=0.5 pop_mult=0.5 [clamp floor], n=5, ev_calibration_error +$450.90,
  pop_calibration_error +0.6234), `LONG_CALL_DEBIT_SPREAD`, and `_overall` (n=18,
  ev_mult=0.5, error +$453.71). Today's 16:00Z scan is the first to score puts calibrated.
- ✅ VERIFIED 2026-06-10 16:00:34Z: `[CONVICTION]` honesty line fired EXACTLY ONCE on the first
  conviction read (entry ranker): "V3 performance-summary source unavailable (PGRST205 …
  learning_performance_summary_v3 …) — falling back to legacy … DEGRADED". Silent swallow dead.
- ✅ VERIFIED (behaviorally) 2026-06-10 16:30Z: #1044 — same 100%-NFLX one-position book that
  produced `risk_envelope_breach` on 06-09 now PROCEEDS through the breaker (result
  status=partial, per-suggestion processing reached). ⚠️ OBSERVABILITY MISS: all
  [UTILIZATION_GATE] lines (flag echo, demotion, per-evaluation numbers) are logger.INFO and
  the worker surfaces only WARNING+/print — invisible in Railway logs. Follow-up: bump those
  lines to WARNING (or set worker log level) so "log every evaluation" is actually observable.
- ✅ VERIFIED 2026-06-10: #1047 — sub-$60 rejections carry nested `spread_debug.spread_debug.
  threshold: 0.3` (CMCSA 0.3985 vs 0.30, CSX); scanner_emitted 14 (prior 1-12); FIRST 2-candidate
  staged day (XLE + NFLX). #1045 application live: puts calibrated for the first time (NFLX
  ev_raw 89.6→44.8 pop 0.321; XLE 84.1→42.0 pop 0.296) — asymmetry gone.
- ✅ BONUS-VERIFIED 2026-06-10 16:30Z: #1038 first LIVE rejections — all 3 XLE cohort forks
  raised `entry_quote_unpriceable: leg=O:XLE260717C00058000 quote={bid:0, ask:0}` (error, not
  executed). The fabricated-fill class is dead on a real dead leg.
- ✅ VERIFIED 2026-06-10: #1049 — alpaca_order_sync avg 1.38s today vs 6.46s prior (−79%).
- ⏳ #1048 exercised-no-trigger: cohort conditions loaded without failure warnings all day; no
  position crossed a cohort stop (book in profit) — first behavioral confirmation pends a breach.
- ✅ SPCX monitor first run 16:45:01Z: scanned_today=true, quote/chain false (pre-listing,
  correct), rejection_reasons [insufficient_history, no_fallback_strategies_available] — the
  loud zero-history skip on record; no scan poisoning.
- Next system close: PR #908 live credit-mleg-close validation.

## status:reported — 2026-06-30 NIGHTLY run (report `audit/reports/2026-06-30.md`)

Window 06-15 → 06-30 (15-day gap; parked week 06-18→06-29 = zero trades; resume-armed tonight).
Infra movement: PRs #1094–#1098 merged + `PAPER_AUTOPILOT_ENABLED` 0→1 (first live-autopilot arm).
Both workers SUCCESS @ `f7dab1d`. Book FLAT (live + shadow). H11 zero critical.

- **[A4 2026-06-30 — FINDING] Learning-ingest silent in-result-error masking (P2→P1; refines the
  ledgered "OUTPUT_FRESHNESS watches ONE table").** `paper_learning_ingest` ran 5×/7d all
  `status=succeeded` while every run 06-23→06-29 carried `result.counts.errors=1,
  outcomes_created=0` (the `opened_at` 42703, fixed by #1098 tonight). EXPECTED_JOBS checks job
  STATUS; OUTPUT_FRESHNESS watches `calibration_adjustments` ONLY → a 6-day silent learning-loop
  death went unalerted. Parked week masked the P&L cost (zero closes); under live autopilot a
  recurrence silently starves calibration + loses real outcomes. FIX (additive, no infra): alert on
  `job_runs.result.counts.errors>0` (status-succeeded included) OR add `learning_feedback_loops` to
  the freshness registry → detection 6d→0d. RISK zero. CONFIDENCE high.
- A1/A6/A7 UNCHANGED (no new fills since 06-17). A2 — 4c fail-open CLOSED (#1094 live); multi-position
  / loss-precedence now live-relevant but backlog-P2 (don't fix ad hoc). A3 — relearn 5/8 post-epoch
  live, raw by #1076 design; ingest break lost ZERO outcomes (flat book that window); path-to-8 now
  depends on autopilot volume. A5 — this loop's only waste: `get_orders` 109k overflow (use
  symbols-filter/subagent next time); else within budget.
- **Four-source disagreement:** −84 NFLX 06-08 LIVE close → paper_positions cohort `3d289dca` (live)
  vs v3 `is_paper=true` (paper); ledgered is_paper P2, pre-epoch so relearn-count-safe but understates
  v3 live realized (−113 vs true −197). Reported not averaged.
- **A8:** lens KEPT (Negative-Decision Efficacy; no data-backed replacement tonight). Named next-run
  replacement **Entry-Fill Efficacy** (staged-live-order watchdog-cancel blind spot, 06-03 NFLX
  precedent) — adopt once autopilot generates staged-live data. See area8.md.

PENDING VERIFICATIONS (next session — first live-autopilot session):
- First 11:30 CT executor cycle on `PAPER_AUTOPILOT_ENABLED=1`: did it stage/fill or pass the EV gate?
- First post-fix `paper_learning_ingest` run (~21:20Z): `outcomes_created>0` on a close, `errors=0`,
  A4 cols (entry_iv_rv_spread/realized_vol_over_hold) populate.
- Entry-Fill Efficacy baseline: of any staged live order, fill vs watchdog-cancel + price vs limit.

## status:shipped — 2026-06-30 post-close runbook · Phase 1 (PR #1100 → main `8faf133`, both workers H8'd)

- **[Phase 1] alert-write resilience + A4 silent-failure detector** (squash `8faf133`; worker +
  worker-background SUCCESS @ 8faf133 21:55Z). (1a/1b) `observability/alerts.py` risk_alerts insert
  wrapped in retry-with-backoff (0.25/0.5s) on TRANSIENT stale-keepalive disconnects ONLY
  (`RemoteProtocolError`/"Server disconnected"); existing `alert_write_failed` log kept as the FINAL
  fallback; distinct `alert_lost_after_retries` marker when a transient exhausts retries. Right-sized
  retry, NOT a durable queue (signature = idle-keepalive drop). (1c) `ops_health_service.
  get_silent_job_failures` + `ops_health_check §3.5` fire a NEW `job_succeeded_with_errors` (high) via
  canonical `alert()` on any `status=succeeded` job with `result.counts.errors>0` (the masking class
  that hid the 6-day `opened_at` ingest death), fingerprint+cooldown, added to `_RISK_EGRESS_ALERT_TYPES`;
  `learning_feedback_loops` already in OUTPUT_FRESHNESS. Detection 6d→0d. 14 new tests + 27+5 regression
  green; ADDITIVE (ingest/executor/exit/monitor untouched). **SYNTHETIC PROOF PASSED:** inserted a
  `succeeded`/`errors=1` job_runs row → dispatched `ops_health_check` → `job_succeeded_with_errors`
  risk_alert fired end-to-end (run_id matched, 22:01:00Z) → both synthetic rows deleted.
  **Operator flag:** `OPS_ALERT_WEBHOOK_URL` unset → a fully-dropped insert reaches NO external
  destination; `alert_lost_after_retries` is the only in-process visibility. Closes the ledgered
  OUTPUT_FRESHNESS / N2-alert-delivery silent-failure gap (the WRITE side; the read-side egress poller
  remains deferred).

- **[Phase 2] entry executable round-trip cost gate** (PR #1101, squash `0ea6583`; worker +
  worker-background SUCCESS @ 0ea6583 22:35Z). Fixes the SOFI 06-30 own-goal class: admitted on EV
  +$30.63 but ~$135 of executable bid/ask cross made it underwater-on-executable from entry →
  force-closed at a 100%-spread-cost loss; the scanner's 5%-of-EV slippage PROXY
  (`canonical_ranker._estimate_slippage`) waved it through. NEW `exit_mark_corroboration.
  executable_roundtrip_cost` (PURE; reuses `compute_corroboration`'s executable basis long→bid/short→ask
  — UNIFIED with the exit, zero refetch; Σ per-leg (ask−bid)×contracts×100). NEW
  `paper_endpoints._apply_entry_roundtrip_gate` in `_stage_order_internal` (after #1038's validated
  `_entry_leg_quotes`, before TCM/insert/submit): `honest_ev_after_cost = ticket.EV − round_trip`,
  REJECT < `MIN_EDGE_AFTER_COSTS` ($15). OPEN-only (closes exempt), skips no-EV (shadow), allows on
  incomplete executable quote (#1038 owns dark legs), WARNING-logs every eval, stamps
  `blocked_reason='ev_below_roundtrip_cost'` (fail-soft), raises `EntryRoundtripCostExceedsEV`
  (#1038-shaped; autopilot counts not-executed). Flag `ENTRY_ROUNDTRIP_COST_GATE_ENABLED` default-ON
  (explicit falsy → legacy). 12 tests (incl. SOFI→REJECT, anti-over-reject PASS, UNIFICATION entry==exit
  basis, flag both ways) + 50+87 regression. ADDITIVE — executor/exit/monitor-force-close/ingest
  untouched (exit_mark_corroboration change = new sibling helper + import only). Resolves the SOFI
  own-goal at the ENTRY (NOT by loosening the stop). Verify on tomorrow's first scan.

- **[Phase 3 — status:DEFERRED 2026-06-30, GATED] Exit-trigger basis calibration (full-cross
  over-pessimism).** The −3% per-symbol envelope force-closes on the FULL-CROSS executable estimate
  (`exit_mark_corroboration.executable_close_estimate`/`compute_corroboration._executable_for`,
  long→bid/short→ask; SOFI `c99d8af2` 06-30: −$65 estimate vs −$40 achievable fill, INSIDE the −$62
  envelope). **WHY DEFERRED:** Phase 2 (#1101) closes the dominant class at ENTRY (SOFI can't be admitted
  now); the residual (a position admitted with tolerable round-trip whose quote later transiently
  widens/one-sides enough to trip the full-cross envelope while the achievable close is still in
  tolerance) is RARE with **N=1 data** — a tuned `k≈0.23` from one fill, on the one stop direction where
  a mistake MASKS real loss, is over-fit. **REOPEN:** ≥10–15 real close fills accumulated (via the
  precursor instrumentation, shipped below) → build on the fill-improvement DISTRIBUTION, not a hand-picked
  constant. **DESIGN (carry forward):** TWO-QUOTE CONFIRMATION — require BOTH the full-cross decision basis
  AND the achievable marketable-limit to breach before force-closing; floored at cross; ≤ mid; gated on
  `quote_complete`/non-wide; NO tuned constant. Survival fixtures: SOFI replays to ~−$40 (SURVIVES,
  −40 > −62) AND a −$200 directional loss STILL fires. **⚠ UNIFICATION TRAP (recon pt 4):** Phase 2's
  `executable_roundtrip_cost` recomputes (ask−bid) directly at `exit_mark_corroboration.py:408` while the
  exit reads `achievable_close` from `_executable_for:191-199` — a Phase 3 that changes ONLY the exit
  primitive makes ENTRY and EXIT diverge, re-creating the entry-admits-what-exit-kills bug this arc fixed.
  Phase 3 moves BOTH seams onto ONE per-leg executable price or it does not ship.

- **[Phase-3 PRECURSOR — SHIPPED 2026-06-30] Close-fill gap instrumentation.** PR #1102 → main `b3479a8`
  (off `0ea6583`). ADDITIVE / observe-only — makes the deferred Phase-3 decision data-driven instead of N=1.
  On EVERY close (force-close AND normal) emits `[CLOSE_FILL_GAP] symbol=… position_id=… cross=<full-cross
  executable estimate> mid=<trigger mark> fill=<marketable-limit fill> gap_fraction=(fill−cross)/(mid−cross)
  reason=…`; the quad is also persisted into the EXISTING close `order_json` JSONB (no migration → SQL-queryable
  for the REOPEN gate beyond short Railway log retention). New pure helper `services/close_fill_gap.py`; cross/mid
  threaded stage→fill via `order_json` (stamped in `paper_exit_evaluator._close_position` post-submit, read back
  at `alpaca_order_handler._close_position_on_fill` LIVE reconcile + the internal/shadow fill). Degenerate
  (mid==cross)→gap None; missing stamp→fill-only NA; every block best-effort try/except — NEVER affects a close.
  NO close-decision / envelope / trigger-basis / force-close / sizing change; no flag. 16 unit + 41 touched-path
  regression tests green (SOFI 06-30 fixture → 0.2326 ≈ 0.23). H8 ✅ both workers SUCCESS @ b3479a8
  (start 23:30Z, prior 0ea6583 REMOVED). First `[CLOSE_FILL_GAP]` line lands on the next live or shadow close.

## status:reported — 2026-07-01 NIGHTLY run (manual; report `audit/reports/2026-07-01.md`)

First session after the live-autopilot arc; verification-first. Both workers @ `b3479a8` all
day (no recycle). Broker flat, equity 2,093.74 (Δ −41.06 = SOFI −40 + fees). H11: 1 critical
= the shadow force-close below (functioning control, not an incident).

- **[A5 2026-07-01 — FINDING] Scanner persist seam unprotected against the stale-keepalive
  disconnect burst (now a 2-day pattern).** 16:00:09Z: 8× "Server disconnected" on
  suggestion_rejections inserts inside the scheduled scan (job result `persist_failures: 8`);
  same class + window as 06-30's storm. #1100's retry wraps ONLY `observability/alerts.py`
  alert() — scanner persists un-retried → 8 rejection rows lost today (observability data, no
  live-risk surface). FIX (additive): reuse the #1100 transient retry at the scanner persist
  seam (or pre-ping the connection before the post-scan write burst). RISK zero. CONF high.
- **[A4 2026-07-01 — REFINEMENT, changes action] Ghost-sweep shadow scoping P2→P1.** 58
  shadow-ghost warns in 2 days from ONE shadow position (51× 06-30 + 7× 07-01) vs ~73/wk
  baseline — the unscoped sweep (`alpaca_order_sync.py:245`) floods exactly when autopilot
  live flow makes a real desync time-critical. Additive scoping only.
- **[A4 2026-07-01 — instance, no new finding] First stranded critical:** 13:30:09Z critical
  `force_close` reached the DB and nothing else — `OPS_ALERT_WEBHOOK_URL` UNSET both workers,
  zero egress lines in logs. Operator owns setting it (+ `HEARTBEAT_PING_URL`, also unset).
- **[A7 2026-07-01 — note] `[CLOSE_FILL_GAP]` line emits at INFO** → invisible on the
  WARNING+/print worker (the [UTILIZATION_GATE] observability class). DB persistence (the
  durable channel) verified working on its first event. Cosmetic rider: bump to WARNING.
- **A8 lens SWAPPED:** Entry-Fill Efficacy ADOPTED (the SOFI staged-live lifecycle is the
  06-30-named trigger data); Negative-Decision Efficacy retired after 6 runs — parting
  datapoint: the conservative SOFI fork's REJECT (edge_below_minimum, EV 19.1) beat both
  accepting books (−40 live / −1,044.48 shadow). Its standing capture/marker recommendation
  stays in backlog RESEARCH, not withdrawn. `audit/area8.md` rewritten.
- Shadow SOFI force-close 07-01 13:30:09Z (−1,044.48; 17 lots; 21h overnight hold; open-
  rotation full-cross 0.84 vs mid 1.57, divergence 0.869): the **GATED Phase-3 class
  exercising** — cited, NOT re-found. All controls fired as designed (verifications below).
  Cohort-comparability caveat: the loss lands on neutral's policy-lab ledger at 26× the live
  twin (#1017 modeled-fill bias, now with a large concrete instance).

VERIFICATIONS CLOSED THIS RUN (the three 06-30 pendings + bonus — do not re-find):
- ✅ **First autopilot executor cycle**: 06-30 16:30Z staged + broker-filled SOFI live (fills
  broker-verified; entry at the 1.44 net limit, ~10s to fill); 07-01 both cycles clean with 0
  candidates (correct zero-entry day on honest scanner math, 382 rejections).
- ✅ **First post-fix paper_learning_ingest** (#1098): 06-30 21:20Z errors=0/created=1;
  07-01 21:20Z errors=0/created=1/dup-skipped=1 (position-level dedup ✓). Live SOFI v3 row
  **is_paper=FALSE**, pnl −40.0; **post-epoch live closes 5→6**. `entry_iv_rv_spread`
  populated (0.1166, first ever); `realized_vol_over_hold` NULL (hypothesis: hold too short —
  verify on a multi-day close before calling it a writer gap).
- ✅ **#1076 live-only calibration EMPIRICALLY confirmed**: 07-01 10:00Z escalation 30/60/90
  all sample_size=6 = exactly the live count (11 post-epoch outcomes exist, only 6 live seen)
  → insufficient_data → raw_mode_reset_written. Raw mode holds until 8.
- ✅ **#1073 Layer A first exercise**: 2 suggestions stamped `status='executed'` 06-30 at the
  position-insert seam.
- ✅ **#1062 first AUTOMATIC cohort-stop cooldown write**: (c8a3a3b0, SOFI) until 07-02
  13:30Z, reason=cohort_stop_force_close, realized_loss −1044.48. #1040's bench is now armed
  with a real row.
- ✅ **#1080 per-position triggers first live fire**: cohort stop evaluated on CORROBORATED
  UPL (obs row 13:30:05Z: mid 1.57/+26 vs achievable 0.84/−1,044.48, divergence 0.869,
  quote_complete=true, stop never suppressed); internal fill at executable w/ fill_quality
  (#1017); [INTERNAL_FILL] WARNING line present.
- ✅ **#1102 first event**: fill-side persist wrote `close_fill_gap_fill=0.84`, cross/mid/
  fraction NULL = the DOCUMENTED fill-only design for internal/shadow closes. Informative
  gap_fraction pends the first LIVE close.
- ✅ **Phase-B EXIT_EVAL_DEBUG honesty observed live**: printed the cohort threshold
  −494.496 (= 0.20 × 2,472.48 basis), not the flat default.
- ✅ **[CONVICTION] DEGRADED**: 0 lines today = CORRECT (v3 view live since #1076) — the
  once-per-recycle DEGRADED expectation is obsolete; do not re-expect it.

PENDING VERIFICATIONS (added 2026-07-01):
- First LIVE close post-#1102 → informative gap_fraction (broker fill vs cross) in
  order_json. The log line is INFO-invisible — query the DB, not Railway.
- First `ENTRY_ROUNDTRIP_COST_GATE` evaluation (next staged candidate): WARNING eval line +
  `blocked_reason='ev_below_roundtrip_cost'` on any reject; classify spread-eaten (correct)
  vs edge-lost (over-reject flag, operator-investigate only).
- 07-02 10:00Z relearn: sample stays live-only n=6 (the 07-01 shadow −1,044.48 is_paper=true
  must NOT appear in the count).
- `realized_vol_over_hold` on the next multi-day close — NULL on short holds is DESIGNED
  (`A4_MIN_HOLD_BARS=3` daily bars; the 15-min/21-h SOFI holds can't qualify); only a NULL on
  a ≥3-day hold would be a writer gap.
- 07-02 13:30Z SOFI cooldown expiry: if SOFI re-emits before expiry, FILTER + fail-closed
  STAGE gates must bench it (#1040's first full pre-ranking exercise).

## status:built — 2026-07-01 post-close · A5 scanner persist-seam retry (PR #1104, CI GREEN, MERGE PENDING operator)

- **[A5 07-01 fix] scanner rejection-persist transient-disconnect retry** — branch
  `fix/scanner-rejection-persist-retry` (tip `a955fc2`), PR #1104, CI green on run 3.
  The 16:00Z post-scan write burst lost 8 `suggestion_rejections` rows to stale-keepalive
  "Server disconnected" (2-day pattern; #1100 wrapped ONLY alerts.py).
  `RejectionStats._persist_rejection` now retries with backoff (0.25/0.5s) reusing #1100's
  classifier (`alerts._is_transient_disconnect`); ONLY transient disconnects retry — any other
  exception keeps the single-attempt fail-soft path byte-for-byte. Exhausted transient →
  DISTINCT `rejection_row_lost_after_retries` marker + unchanged fallback; recovered retry →
  NEW `persist_retry_recoveries` count in the scan job_runs.result (DB-queryable) + WARNING
  line. Backoff sleep is constructor-injected (`retry_sleep=`, default time.sleep test-pinned):
  CI runs 1+2 proved dotted-path @patch on options_scanner is order-fragile in the full suite
  (the MagicMock-shadowing class the suite itself documents at
  test_credit_spread_emission._read_anomaly_threshold). No flag (observability-only; clean path
  unchanged: one attempt, zero sleeps). ADDITIVE — scan decisions/aggregate counts/close paths
  untouched. 9 new tests + 97 touched-path regression local + full CI.
  **Rider (ledger-named 07-01):** `[CLOSE_FILL_GAP]` emits at WARNING (was INFO-invisible);
  level test-pinned.
- **Merge blocked by the session's self-approval gate (correct behavior):** the agent-authored
  PR merge auto-deploys both live workers; operator merges. AFTER merge: H8 both workers
  (deployment SUCCESS at the squash SHA, container start > merge time), then the pendings below.

PENDING VERIFICATIONS (added with #1104; valid only after operator merge + H8):
- Next 16:00Z scan disconnect burst: `persist_failures=0` + `persist_retry_recoveries>0` in the
  scan job_runs.result (retry absorbed it), or the distinct `rejection_row_lost_after_retries`
  marker if one outlives the backoff.
- First live close post-merge: [CLOSE_FILL_GAP] line now VISIBLE at WARNING in Railway logs —
  the "query the DB, not Railway" caveat on the earlier pending item becomes obsolete at this SHA.

## status:reported — 2026-07-02 NIGHTLY (v5.1 first run; report `audit/reports/2026-07-02.md`)

Quiet night: zero market activity since the 07-01 report; movement = #1104 (persist retry,
shipped) + #1105 (docs) merged 02:39/02:41Z, both workers SUCCESS @ `b6a28e1` (H8 clean,
mid-night recycle, no orphaned cycles). Broker flat, equity 2,093.74 == last_equity. H11: 1
critical = the ledgered 07-01 shadow force-close.

- **ONE-TIME CORRECTION (owner, v5.1 contract): the 2026-07-01 A8 swap to Entry-Fill Efficacy
  was ADOPTED IN ERROR and is REVERTED.** Negative-Decision Efficacy is RESTORED as the A8
  graduated standing area (audited every run; does not rotate). Entry-Fill Efficacy is
  RETIRED — not moved to A9; its spec is preserved in `audit/area8.md` under SUPERSEDED
  (move-don't-lose). Reason of record: A8 is the standing counterfactual area; single-run
  lens rotation is Area 9's mechanism. EFE's subject matter stays auditable under A1/A6/A7
  and may compete for the A9 slot on merits, with no incumbency.
- **[A9 2026-07-02 — FINDING, first audit of the new rotating lens "Alert & Signal
  Integrity"] `ops_data_stale` alert content lies about its trigger: 57/69 (83%) of 30d
  firings self-contradictory** ("Market data is stale … Stale: 0 … Reason: ok",
  `stale_symbols=[]`; one at age_seconds=54). Mechanism: `ops_health_check.py:117` ORs
  market_freshness | job_freshness, but message (:141-143) + details (:144-149) are built
  from market_freshness ONLY — every job-arm firing is mislabeled as market-data staleness;
  the correct `stale_reason` (:120-121) never enters the alert; fingerprint (:124-128) hashes
  the empty symbol list → all job-arm firings share one fingerprint. The job-arm predicate
  (30-min threshold vs 1×/day suggestions_open/close, `ops_health_service.py:198-227`) is the
  LEDGERED 2026-06-10 root cause — cited, not re-found; the mislabel wiring is the new
  surface. Realized cost: the 07-01 audit itself mislabeled the class ("chronic
  calibration-freshness artifact"). Projected cost: ~2-4 false highs/RTH-day egress to the
  ops webhook the day OPS_ALERT_WEBHOOK_URL is set → fix the wiring BEFORE/WITH webhook
  arming (order-coupled with the standing TOP-3 #1). FIX (additive): message from
  stale_reason + `trigger_source` + job_freshness fields in details + per-arm fingerprint; no
  predicate/threshold change (that is the separate ledgered item). RISK zero (content-only).
  CONF high. Spec: `audit/area9.md` (fresh adoption, no graduation proposed).
- A1/A2/A6/A7 UNCHANGED (zero fills/scans/closes in window). A3 counter re-verified 6/8 live
  post-epoch (30d: live n=6 −153; paper n=9, 5 post-epoch, −1,870.80). A5 loop self-audit:
  11 SQL (3 wasted on column-name misses — introspect information_schema FIRST), 3 broker, 0
  subagents; prior-session H8/H11 pulls reused. Q9 note: scanner persist-failure key is
  `result.counts.rejection_persist_failures` (options_scanner.py:311) — use it for the #1104
  verification query.

PENDING VERIFICATIONS (2026-07-02 session, in addition to the standing 07-01 list):
- 10:00Z relearn: sample_size=6 live-only (shadow −1,044.48 is_paper=true excluded).
- 13:30Z SOFI cooldown expiry: FILTER + fail-closed STAGE gates bench a pre-expiry re-emit.
- 16:00Z scan: #1104 first live test — `counts.rejection_persist_failures=0` (+
  `persist_retry_recoveries>0` if a disconnect burst occurs); [CLOSE_FILL_GAP] now
  WARNING-visible on any close.
- Scheduled 00:23 CT nightly (v5 prompt) collides with report file `2026-07-02.md` — operator
  to skip or accept overwrite (this run covers the window).

## status:shipped — 2026-07-02 post-close · A9 data_stale content fix (PR #1106 → main `91b1319`, both workers H8 SUCCESS 03:20:55Z)

- **[A9 fix, item 1 of tonight 3] data_stale alert content from the firing arm** — squash
  `91b1319`. NEW pure helper `ops_health_check.build_data_stale_alert_content(market, job)`:
  message/details/fingerprint from the arm(s) that FIRED. Job-arm → names the stale source +
  age vs threshold + true reason (trigger_source="job", job_* detail keys); market-arm →
  EXACT legacy message AND legacy fingerprint shape (cooldown history survives the deploy);
  both → both named, " | "-joined. Job-arm fingerprints hash {job_source, job_reason, arms}
  instead of the empty market symbol list (per-arm dedup buckets). PREDICATE UNTOUCHED
  (test-pinned) — the 30-min-vs-daily-cadence job-arm threshold stays the separately-ledgered
  2026-06-10 item (own PR later, per operator 1c). Regression fixture pins the verbatim 07-01
  production shape: "Market data is stale ... Stale: 0 (). Reason: ok" can never emit again.
  12 new tests + 57 touched-path regression + CI green first try. One-time cooldown reset for
  job-arm firings only. Sequencing honored: shipped BEFORE webhook arming.

PENDING VERIFICATION: next RTH inter-scan gap (e.g. ~14:07Z or ~15:07Z ops_health_check) →
the ops_data_stale row (if the job arm fires) must read "Job-based data freshness is stale.
Source: job_runs. Age: ~N min ..." with trigger_source="job" and NO market-data language.

## status:armed — 2026-07-02 post-close · egress webhook LIVE (item 2 of tonight 3, operator action)

- **`OPS_ALERT_WEBHOOK_URL` SET on BOTH workers ~03:35Z** (operator; names-only hygiene —
  value never in transcript). Var-change recycle: worker + worker-background BOTH SUCCESS
  03:35:44Z, SHA unchanged `91b1319` → running processes carry it. Code reads confirmed:
  `ops_health_service.py:670/:1188` + `observability/alerts.py` (#1096/#1100 senders).
  Sequencing honored: #1106 content fix deployed BEFORE arming (no cry-wolf channel).
  Standing TOP-3 #1 (3 consecutive reports) is CLOSED pending first-egress proof.
- **⚠ `HEARTBEAT_PING_URL` SET but INERT — NO READER EXISTS.** Grep 07-02: zero code
  references (`jobs/handlers/heartbeat.py` is only the internal scheduler job_runs
  heartbeat; no PING_URL/healthchecks reader anywhere). The external dead-man's switch
  (durable-oversight Window 1, P2 half) was NEVER BUILT — only the A4 detector half shipped
  (#1100). The var is correct env-first pre-staging, but **monitoring-by-absence is NOT
  active**; a dead scheduler still alerts nobody externally. DOC≠BUILT instance — do not
  count the switch as armed until its PR ships and pings are observed at the provider.

PENDING VERIFICATION (egress arm): first egress-eligible alert (critical, or the ~14:07Z
ops_data_stale job-arm firing if allowlisted) must produce a webhook send — check for the
sender's egress log line on the worker AND delivery at the operator's channel; a stranded
critical with the var set = new finding (delivery-path bug, not config).

## status:shipped — 2026-07-02 post-close · ghost-sweep live scoping (item 3 of tonight 3; PR #1107 → main `6898bf9`)

- **[07-01/07-02 TOP-3 #3] ghost_position sweep scoped to live-routed portfolios** — squash
  `6898bf9`. Recon first (PR was gated on it): ALL 58 warns 06-30→07-01 traced to ONE
  position — the neutral-cohort shadow SOFI (`08002beb`, `routing_mode=shadow_only`), firing
  every 5-min sync from open+15min to seconds before its 13:30Z force-close. Sweep correct
  per code, spurious per intent (a shadow never exists at the broker). Fix: sweep portfolio
  set through #1014 canonical `position_scope.live_routed_portfolio_ids`, BOTH halves (ghost
  legs + stale needs_manual_review). **Fail-OPEN polarity, test-pinned**: scope-query failure
  → legacy unscoped sweep + warning (noisy beats blind — a detector must never silently
  narrow). Deliberately NO dedup on the ghost half: a real live ghost keeps nagging at full
  cadence (H10 urgency preserved). Dedup/rate-limit evaluated and REJECTED (would mute real
  desyncs). 7 new tests (`test_ghost_sweep_live_scope.py`, verbatim 08002beb fixture) + 21
  existing green; CI green. Closes the ledgered P2→P1 noise item; §8 seam note ("sweep does
  not exclude shadows") is FIXED at this SHA — CLAUDE.md edit deferred to the next doctrine
  pass.

PENDING VERIFICATION (ghost scoping): next session with an open SHADOW position → zero
ghost_position warns from it across sync cycles (the 08002beb class); any LIVE position
ghost must still alert. H8 VERIFIED 03:44Z: worker + worker-background BOTH SUCCESS @
`6898bf9` (deploys 4b9fd393/4401e0ba), zero error-level lines post-start.

## status:shipped — 2026-07-02 post-close run #2 (operator-directed A1–A5 + B1–B3 recons)

Three builds merged sequentially (one PR / one recycle / H8 each), three read-only recons,
backlog rewritten. All H8s: both workers SUCCESS at the squash SHA, container start > merge,
zero error-level lines post-start.

- **[A1 #1109 `97bace3` 04:09:58Z] dead-man's-switch ping** — heartbeat.run() fires one
  best-effort GET at `HEARTBEAT_PING_URL` (timeout 5s, try/except → single WARNING logging
  the exception CLASS only — the URL embeds the check token, never logged). Unset/empty →
  silent no-op. Pin: run() result byte-identical across success/timeout/unset — a
  healthchecks outage can NEVER fail the heartbeat job. **HEARTBEAT ARMED, end-of-chain
  semantics**: silent check = one of APScheduler→BE→RQ→worker died; diagnose job_runs vs
  Railway. RTH-only trade-off accepted (schedule */30, hours 8–17 CT). Env var pre-staged +
  read back 03:35Z; no var mutation since — recycled containers carry it.
- **[A2 #1110 `716ba2a` 04:15:23Z] typed strategy/regime on trade_closed outcomes** —
  the builder carried both only in details_json while the TYPED columns (the ones
  post_trade_learning._build_segment_key reads) were never written → segment learning
  silently no-oped (83/98 rows NULL; the 06-29 "0/13" was the narrower window). Values were
  available-but-unmapped (the metadata SELECT already pulls strategy+regime). No linked
  suggestion → NULL, never fabricated (H9). Every close from this deploy forward carries
  segments. 82 of 83 legacy NULL rows backfillable from linked suggestions → supervised-
  mutation queue (NOT executed).
- **[A3 #1111 `7bc9927` 04:25:51Z] direct-insert alert egress relay (P1 Window-2)** —
  13 sites insert risk_alerts without alert() (incl. the monitor's force_close): with the
  webhook armed they still egressed NOWHERE. relay_direct_insert_alerts polls post-epoch
  critical/high rows and relays via the SAME Channel-2 sender (client=None, no duplicate
  row), marks metadata.egressed_at/egress_owner=relay. Boundaries: ops_* Channel-1 rows
  excluded; alert() pre-stamps egress_owner=alert on its #1096 allowlist. Epoch
  `ALERT_RELAY_EPOCH` = 2026-07-02T00:00Z (#1051 pattern; 0 post-epoch rows at build —
  the 1,040-row backlog can never fire). Best-effort: unmarked-on-failure → retry next
  poll; 3-consecutive-failure circuit; cap 10/poll. Piggybacked as fail-isolated step 0 of
  ops_health_check (effective cadence HOURLY at :07 — the :37 fire is deduped by the hourly
  idempotency key; contradiction filed P1). **Egress now covers alert() AND direct-insert
  paths.**
- **[A4 EXECUTED 07-02 ~04:45Z, operator-approved in-session]** hygiene sweep: bulk-acked
  exactly **1,040** pre-epoch un-acked critical/high (385 c / 655 h; warn×580,
  force_close×356, ops_data_stale×69 dominate) via one UPDATE setting resolved=true +
  resolved_at + jsonb marker `bulk_ack='hygiene_sweep_2026-07-02'`, cutoff = relay epoch
  07-02 00:00Z (move-don't-lose; both production readers key on recent created_at windows —
  behavior-safe). Post-sweep verification: the ONLY remaining un-acked critical/high row is
  the synthetic relay-e2e row `4d0afb05` (by design, deleted after the 13:07Z proof). H11
  baselines are clean from tonight forward: un-acked critical/high now means LIVE actionable.
- **[A5 #1112] docs/backlog.md rewritten** from ledger + recon verdicts; GATED carries the
  executor-cadence trigger verbatim (NOT MET); #71 guard tokens retained (29 guard tests
  green). Final recycle of the night.
- **[B1 recon — MTM mark-write corroboration → PROMOTED P1]** persisted raw marks are
  DECISION-FEEDING on slow paths: policy-lab champion HARD_DRAWDOWN_LIMIT auto-rollback
  (evaluator.py:605-621 via max_drawdown), go-live checkpoints, autopilot-breaker +
  _marginal_ev fallbacks, close-limit seam (mitigated #1072/#1017). Fast loss paths clean
  (#1071/#1075/#1079/#1080). 14d evidence: 2/3 closes wrong-signed at last persist; SOFI
  persisted +196.52 30min before the corroborated −1,044.48 close. Fix = reuse
  exit_mark_corroboration.executable_close_estimate at BOTH write sites
  (paper_mark_to_market_service.py:206-217 + intraday_risk_monitor.py:780-790, snapshots
  already fetched — zero extra API calls), ADDITIVE fields only. Side-finding: monitor
  Part-B persist doesn't stamp last_marked_at.
- **[B2 recon — migration drift]** the 2-file paper-shadow cluster is the only genuinely
  unapplied pair → GATED apply-as-unit pre-enable (INERT confirmed, doubly so). Tracking:
  27/112 by name (82 pre-era, 1 procedure miss `20260426000000` applied-untracked, 2 gated).
  Process fix (P2): name-normalized drift check vs a checked-in allowlist in the nightly
  audit.
- **[B3 recon — data_stale predicate retune table ready]** union arm: max healthy in-gate
  age 187 min over 10/10 trading days → `OPS_DATA_STALE_MINUTES=360` kills 39/39 job-arm
  false HIGHs (78% of all data_stale HIGHs); market-hours gate suffices for the union arm
  (no new weekend guard). Daily job_late arm (NOT market-hours-gated) needs the
  _rth_job_status warm-up-anchor generalized — 40 Monday warns → 0. Contradictions filed:
  ops_health_check hourly-vs-q30 dedup; suggestions_open 15 runs/10d untraced extras.

PENDING VERIFICATIONS (added 2026-07-02 post-close run #2):
- **Heartbeat first ping** at the 08:00 CT slot (13:00Z) — provider dashboard shows it;
  then the operator handoff (un-pause, cron */30 8-16 * * 1-5 America/Chicago, Grace 45,
  after-hours Grace-to-1-min email test to prove the last hop, restore).
- **Relay synthetic e2e** at the 08:07 CT poll (13:07Z): risk_alerts row
  `4d0afb05-3c9a-4c10-ac40-39f55e292ffb` (relay_synthetic_e2e, critical, 04:26:42Z,
  clearly-labeled SYNTHETIC) must egress to the operator inbox;
  job_runs.result.alert_relay.sent=1 + metadata stamped egress_owner=relay. THEN clean up:
  `DELETE FROM risk_alerts WHERE id='4d0afb05-3c9a-4c10-ac40-39f55e292ffb';`
  A stranded synthetic with the webhook set = delivery-path bug (new finding).
- **First typed segment row**: next trade_closed ingest (21:20Z) carries non-NULL
  strategy+regime; post_trade_learning segment keys build without the suggestion-join
  fallback.
- Standing 07-01/07-02 list unchanged (10:00Z relearn live-only n=6 · 13:30Z SOFI cooldown
  expiry · 16:00Z scan #1104 first live test · #1101 first roundtrip-gate evaluation ·
  first LIVE close post-#1102 gap_fraction).

## status:shipped — 2026-07-02 pre-market build session (P1-A/B/C + approved backfills)

Operator-directed session (~09:00–09:30Z, market closed; all merges pre-08:00 CT job spin-up).
Three sequential builds, each CI-green → squash → BOTH workers (+BE for P1-A) H8 SUCCESS at the
squash SHA, container start > merge. Owner decision of record: ops_health_check cadence intent =
**(a) q30min REAL**.

- **[P1-A #1114 `e133063` 09:02:33Z] q30min-real idempotency bucket** — the hour-granular key
  (`public_tasks.py`) deduped the :37 fire against :07 every hour (99/100 observed runs at :07);
  effective cadence was HOURLY, silently halving the health check AND the A3 relay poll. Key now
  buckets by half-hour via pure `_ops_health_idempotency_key`; same-half-hour retries still dedup;
  `-synthetic` suffix composes unchanged. **Relay SLA restated: a direct-insert critical/high
  reaches the inbox within ~37min worst case** (insert just after :07 → :37 poll + send), vs ~67min
  before. BE verified at the SHA too (the endpoint lives there). VERIFY: two ops_health_check
  job_runs per hour from 13:07/13:37Z today.
- **[P1-B #1115 `0b85de6` 09:12:09Z] data_stale predicate retune** — PREDICATE ONLY (#1106 content
  pins green): `OPS_DATA_STALE_MINUTES` default 30→360 (wiring unchanged: code default + env
  override; if the env name is explicitly set on Railway it shadows — operator names-only check);
  daily `job_late` age is now WEEKEND-EXCLUDED (`_weekend_excluded_age` — Fri-evening→Mon-morning
  reads ~16h ok; a genuinely missed Monday reads ~40h late by Tuesday; flat ~74h raise rejected as
  it would delay Tue–Fri detection). Fixture update ledgered: the watchdog daily pin re-anchored on
  a Thursday (its old 30h window crossed Sunday — reads ~17h effective under the deliberate new
  semantics; the 26h-absent-weekend intent preserved). **VERIFICATION CONTRACT: next RTH day
  job-arm false HIGHs 39→0; next Monday job_late storm 20→0; a real dead daily job still alerts
  same-day (367min > 360 at the 19:07Z check).** The alert channel's last known noise source dies
  here.
- **[P1-C #1116 `b18052d` 09:25:52Z] MTM mark-WRITE corroboration (B1 promote)** — both durable-
  mark write sites (`refresh_marks` + monitor Part-B) now persist
  {mark_corroborated, unrealized_pl_corroborated, mark_quality} ALONGSIDE the raw mid (raw
  byte-identical — the load-bearing pin held; the exit evaluator's close-limit read is
  source-pinned to raw). Design call (owner-delegated): ADDITIVE, not replace — replacing
  current_mark would leak into the LIVE close-limit path, and #1072 already restages live closes
  at achievable. Zero extra API calls (cycle-cached snapshots); dark/incomplete → NULLs +
  uncorroborated stamp (H9). Governance now prefers corroborated: policy-lab cohort unrealized
  (max_drawdown → utility + HARD_DRAWDOWN_LIMIT champion auto-rollback) + go-live checkpoint sums;
  breaker/_marginal_ev FALLBACK branches deliberately untouched. OUTPUT_FRESHNESS now watches
  paper_positions.last_marked_at (168h; flat-book caveat) + generic query NULLS LAST fix.
  Migration `20260702100000` applied pre-merge via canonical apply_migration (tracked).
  **BEFORE-BASELINE (do not re-find): 14d = 2/3 closes wrong-signed at last persist; SOFI 07-01
  raw +196.52 persisted 30min before the corroborated −1,044.48 close (divergence 0.869).**
  Pinned: the SOFI fixture now reads −1,044.48 into cohort scoring. Residual (filed, not built):
  Part-B still doesn't stamp last_marked_at; eod snapshots don't carry corroborated fields.
  VERIFY: first RTH mark cycle writes non-NULL corroborated fields on any open position;
  policy_daily_scores unrealized reflects the corroborated basis at the next eval.
- **[Backfills EXECUTED ~09:35Z, operator-approved in-session after fidelity gates]**
  (a) 82-row typed strategy/regime from linked suggestions (10/10 sample fidelity; exactly 82;
  the 1 non-qualifying row stays NULL as pre-fix legacy; no updated_at trigger — v3 close-time
  COALESCE untouched). (b) 33-row funnel dismissed→executed (10/10 sample had real closed
  positions; exactly 33 = the ledgered 32 + 1 accrued; the trade_suggestions integrity trigger
  guards lineage fields only — status explicitly allowed). Historical segment learning and funnel
  stats are now truthful end-to-end.
- **GATED confirmations (encoded, nothing touched):** executor cadence NOT MET (raw 6/8, #1072
  unexercised) · clamp/winsorize await the 8th live close · Phase-3 exits await ≥10–15 fills ·
  paper-shadow migration pair only at the executor-flag flip (RLS at apply). Operator handoff
  outstanding: healthchecks un-pause + cron */30 8-16 * * 1-5 America/Chicago + Grace 45 +
  after-hours Grace-to-1-min email test.

PENDING VERIFICATIONS (added this session): two health-check runs/hour from 13:07Z · job-arm
false-HIGH count = 0 over today's RTH · Monday 07-06 job_late storm = 0 · first mark cycle
writes corroborated fields · next policy_lab_eval scores on the corroborated basis.

## status:shipped — 2026-07-02 gap-report build session (external-reference audit, operator-approved set)

Operator ran a reference-repo gap analysis (NoFx / flashalpha / TradingAgents / ai-hedge-fund
patterns); approved set built in order. Both builds CI-green → squash → both workers H8.

- **[Gap-4 recon — DOC≠BUILT FINDING: the greeks exposure envelope is DOUBLE-dormant]** —
  DB-verified: across 60d (18 positions) NO leg jsonb has ever carried a `greeks` key and
  paper_positions has no greeks column → `check_greeks` (risk_envelope.py:229) has summed
  ZEROS since inception; AND all four caps default 0 = no-limit. §5's "greeks warn" listing
  is a known-liar until fixed (CLAUDE.md edit deferred to the next doctrine pass, #1107
  precedent). Answers the archived #115b narrowed question on the persisted side. NOT
  silently populated (operator-directed); follow-up filed: populate greeks on legs at stage
  time (stage validation already fetches snapshots that carry them), caps decision after
  inputs are real.
- **[Gap-2 #1118 `49f3ba9` 10:02:34Z] rolling signal-accuracy telemetry (OBSERVE-ONLY)** —
  view `signal_accuracy_rolling` (migration 20260702110000, applied+tracked pre-merge):
  live-only last-20 hit-rate + Brier per scope; ops_health section 3.7 fail-isolated;
  `signal_accuracy_degraded` WARNING at n≥8 AND hit_rate<0.2 (env-tunable). Modulates
  nothing. **FIRST BASELINE (do not re-derive): overall 1/6 wins (16.7%), Brier 0.2751;
  IRON_CONDOR 0/2, LONG_CALL_DEBIT_SPREAD 0/3, LONG_PUT_DEBIT_SPREAD 1/1.** n=6<8 → below
  the alert sample gate today.
- **[Gap-1 #1119 `c0268ce` 10:15:31Z] consecutive-loss streak breaker (NoFx pattern)** —
  N consecutive live losses → `ops_control.entries_paused=true` + critical alert
  (streak_breaker_tripped/_error added to the #1096 egress allowlist). N=3 env-config
  (`STREAK_BREAKER_N`); `STREAK_BREAKER_ENABLED` default-ON tightening polarity; FAIL-CLOSED
  the strong way (evaluation error → PAUSED, never check-skipped — deliberately opposite the
  fail-open READ gate, which consumes a halt this evaluator sets); recovery operator-only
  (no code path writes false — source-pinned); idempotent vs existing pauses. Tail step of
  paper_learning_ingest → job_runs.result.streak_breaker. **Pre-merge bug caught
  (verify-before-asserting): a typed `symbol` select would have 42703'd (no such column —
  #1098 class) and, under fail-closed, paused entries EVERY run; symbol now read from
  details_json, select list source-pinned.** ⚠ **KNOWN TRIP, operator-acknowledged: the live
  stream already holds 5 consecutive losses (SOFI −40 · MARA −15 · QQQ −73 · MARA −28 ·
  SPY −45) — the FIRST evaluation (tonight 21:20Z ingest) trips: entries pause + critical
  alert = free live end-to-end exercise. Operator decision of record: ship, let it trip,
  then un-pause (`UPDATE ops_control SET entries_paused=false, entries_pause_reason=NULL
  WHERE key='global'`). A 21:20Z trip is EXPECTED, not an incident.**
- **[Gap-3 recon + spec — NO build]** `docs/specs/shadow_fill_realism.md`. Recon: live fill
  rate ≈1/3 (17 filled / ~54 orders; 10 watchdog-cancelled unfilled — the NFLX class ≈1 in
  5) vs shadow 100%-by-construction; same-period twin magnitudes 3–45× (size-driven, 5–17
  lots vs 1); only 3 shadow closes carry fill_quality=executable (rest predate #1017);
  cohort twin pairing is (symbol, cycle), NEVER suggestion_id. Recommendation: interim
  option (a) per-contract promotion-time normalization + measured fill-discount (one PR)
  BEFORE the next promotion eval; full post-and-wait model (b) in its own recon-first
  session. Owner decision pending on (a).

PENDING VERIFICATIONS (gap session): 21:20Z tonight — `job_runs.result.streak_breaker.tripped=true`
+ entries_paused=true + streak_breaker_tripped critical in the inbox (egress) → operator
un-pauses per decision of record · signal_accuracy view visible in tonight's ops_health
snapshots · no alert from signal accuracy until n≥8.

## status:verified — 2026-07-02 post-close wrap (~23:30–23:50Z): the breaker exercise + doc sync

- **[#1119 FIRST TRIP — VERIFIED END-TO-END, planned, NOT an incident]** 21:20Z ingest:
  errors=0, outcomes_created=0 (flat day; typed-segment FORWARD proof defers to the next real
  close — the 82 backfilled rows stand). `result.streak_breaker`: enabled/evaluated/tripped/
  paused_written ALL true; window = SOFI −40 · MARA −15 · QQQ −73 verbatim. Chain: ops_control
  entries_paused=true + streak reason verbatim → `streak_breaker_tripped` critical 21:20:03Z,
  `metadata.egress_owner='alert'` (immediate-egress path; relay can never double-send) → zero
  `streak_breaker_error` rows → worker log `[STREAK_BREAKER] TRIPPED` 21:20:09Z. Egress nuance:
  the webhook POST attempt is proven and NO failure logged (failures log at WARNING and would
  show); the success line is INFO (not retained) → final receipt = operator inbox (confirm ④).
  Design note answered by the exercise: the breaker evaluates the TRAILING stream on EVERY
  ingest run (it fired with outcomes_created=0) — no fires-only-on-new-outcomes gap.
- **[RECOVERY EXECUTED ~23:35Z, operator-approved in the wrap]** un-pause UPDATE run;
  read-back `false / NULL`. Entry-seam read: `paper_autopilot_service.py:187-196`
  (`are_entries_paused()` → falls through to the staleness gate when false). Staging proof =
  tomorrow's 16:30Z cycle (PENDING). Breaker critical ACKed (exercise complete).
- **[CLEANUP]** synthetic relay row `4d0afb05` DELETED (post-inbox-window); post-sweep H11:
  **un-acked critical/high = 0 — genuinely zero for the first time on record.**
- **[DOC SYNC]** CLAUDE.md registry #1043→#1119 synced (v3-exists correction, 8th-close
  convergence rule, relay route/SLA, close-limit-reads-RAW pin, breaker un-pause procedure
  VALIDATED, §5 greeks layer marked dormant, §7 v5.1 A8-standing/A9-rotating, §8 liars
  rewritten: greeks double-dormant + shadow-ledger fiction added; EXIT_EVAL_DEBUG/ghost-sweep/
  is_paper/funnel moved to RESOLVED-cite-only; no-symbol-column trap; §9 + entries_paused
  operator-only + introspect-before-select). backlog: P1 tier → gap-3(a) normalization +
  tradeable-universe recon; shipped set retired; supervised-mutation queue closed; new P2s
  (greeks populate-at-stage, breaker-N revisit at n≥15, mark-write residuals). ~38.4k chars.
- **Process note (self-caught):** a PowerShell one-liner clobbered docs/backlog.md mid-edit
  (PS 5.1 kept executing after a Substring exception → Set-Content $null). Recovered via
  `git checkout --`; only an uncommitted edit was lost and redone via the Edit tool. Lesson:
  no destructive shell one-liners on tracked docs — Edit tool only.

OPERATOR-CONFIRM — **ALL FOUR CONFIRMED with evidence (operator, 07-03 session)**:
① healthchecks FULLY ARMED — check un-paused; receive-side 20 pings, every :00/:30 from 08:00
  CT (source = the worker; "new → up" at the first ping, per #1109's prediction); cron
  `*/30 8-16 * * 1-5` America/Chicago, Grace 45; Grace-to-1-min DOWN-email test DELIVERED
  18:45 CT, Grace restored. Residual: check reads DOWN overnight post-test — EXPECTED; the
  08:00 CT ping tomorrow auto-flips UP (the UP email = free second confirmation, pended).
② relay synthetic email DELIVERED 08:07 CT (full payload incl. risk_alert_id 4d0afb05) — the
  A3 relay's last hop proven.
③ OPS_DATA_STALE_MINUTES CONFIRMED UNSET (dashboard names-only) — the 07-02 zero-false-HIGH
  result is attributable to #1115's code default, not an env shadow. Behavioral pass = real.
④ breaker critical email DELIVERED 16:20 CT (full window payload, paused_written=true,
  already_paused=false) — the immediate-egress path proven on a REAL safety event.
**With ①–④ the oversight chain is proven at every last hop** (doctrine-synced: CLAUDE.md §4
"Oversight chain" entry). Breaker semantics operator-confirmed from the ④ payload:
TRAILING-window evaluation on EVERY ingest run — trips can occur on zero-close days (the
07-02 window spanned closes 06-15→06-30); the stronger design, now doctrine. Recovery
mutations from the wrap RE-VERIFIED holding at confirm time (entries_paused false/NULL ·
breaker alert ACKed · synthetic gone · H11 = 0).

PARKED (operator's call, no action): rotate the hc-ping UUID (appeared in screenshots) —
healthchecks regenerate + one env update + recycle, whenever chosen.

PENDING (tomorrow): 08:00 CT heartbeat UP email (test residual clears) · 16:30Z post-un-pause
staging proof (final recovery link) · first typed-segment forward row + breaker re-evaluation
at the next real close's ingest (NOTE: the 3 most-recent live closes are all losses, so the
NEXT losing live close re-trips the breaker BY DESIGN — a win resets) · first [CLOSE_FILL_GAP]
live gap_fraction · gap-3(a) build + tradeable-universe recon = next build window.

## status:shipped — 2026-07-03 build window (~00:45–01:15Z): gap-3(a) + tradeable-universe recon

- **DEADLINE (Step 0):** the champion-vs-shadow comparison runs inside `policy_lab_eval`
  (scheduler 16:30 CT daily; `check_promotion` at policy_lab/evaluator.py:282); gap-3(a)
  landed ~15h before the next eval. (`promotion_check` 17:00 CT is phase-transition hygiene,
  not the comparison.)
- **[Gap-3(a) #1124 `48ddcd4` 01:10:59Z] shadow-ledger promotion-time normalization** — NEW
  `policy_lab/promotion_normalization.py`, called ONLY from check_promotion after the daily-
  scores fetch (governance-only, import-pinned): per-contract division on BOTH sides (daily
  contract-exposure attribution, floors at 1, never fabricates) + the MEASURED fill-discount
  on challenger/shadow rows only — `SHADOW_FILL_DISCOUNT` default **0.31 = 17/55 live fills
  re-measured at build time** (spec said 0.33; fresh count used per instruction; RE-DERIVE
  from live fill data as volume grows, never hand-tune). Ledger rows and percent fields
  untouched (rollback semantics preserved); position-fetch failure degrades divisors to 1.0
  with a WARNING. Flag `SHADOW_PROMOTION_NORMALIZATION_ENABLED` default-ON (measurement-basis
  correction, #1052 class). SOFI twin fixture pinned: live −40 → −40.00 byte-identical;
  shadow −1,044.48@17 → **−19.05** expected contribution. 18 tests + 27 touched-path.
  **BEFORE-STATE: promotion evals compared a real ~31%-fill book to a 100%-fill fiction at
  3–45× magnitudes.** H8: both workers SUCCESS @ 48ddcd4 (01:11Z deploys). VERIFY: next
  16:30 CT policy_lab_eval runs the normalized comparison (job green; no verdict flip
  expected at current n).
- **[Tradeable-universe recon — READ-ONLY, owner-decision input, NO changes]** headline:
  **1 of 84 CLEARS the round-trip gate on strict post-epoch evidence (SPY, net ≈ +$16–23 on
  a single candidacy); 5 MARGINAL (QQQ, NFLX, TSLA, IWM, SLV); ~77 STRUCTURALLY-CANNOT.**
  Structure: honest per-contract EV density is $7–45/ct; sub-$60 underlyings size to 4–21
  contracts so per-ct EV collapses to single digits vs $21+/ct minimum round-trip (the
  SOFI/TLT class — TLT has the tightest spread in the universe, $12/ct, and still cannot);
  expensive single names carry $60–1,500/ct crossings. Only penny-increment index-class
  chains get under ~$40/ct. No real-quote row in 1,436 rejections ever printed below $21/ct.
  Within-universe insight: TSLA/IWM already CLEAR the spread (~$13–14/ct) but die upstream
  on EV — if regime ever hands them positive EV they clear where SOFI never can (HYPOTHESIS
  until a post-epoch candidacy). Outside-universe candidates (HYPOTHESIS): GDX/KRE/XBI/EFA
  penny-program ETFs — but the TLT lesson says tight spread is insufficient without a
  contract-count cap in the sizer. Detail note: the gate's DB stamp reads round_trip=88.00
  (4 cts, $22/ct) vs the 16:30Z log line's 92.00 — same verdict either way; likely quote
  drift between eval and stamp passes (minor, watch on the next rejection).
- **Universe-reshape question FRAMED FOR OWNER (no action):** the small-tier universe is
  structurally spread-eaten — options: (a) accept low frequency (learning-mode consistent;
  gate is doing its job), (b) bias scanner ranking toward the 6 CLEARS/MARGINAL names,
  (c) add penny-program ETFs + a sizer contract-cap, (d) nothing until EV density grows with
  equity. Recon is the decision input; no default assumed.

PENDING VERIFICATION (gap-3(a)): 07-03 21:30Z policy_lab_eval green on the normalized basis.
Gap-3(b) post-and-wait fill model remains its own recon-first session (NOT started).

## status:shipped — 2026-07-03 (July-4th-observed HOLIDAY, market closed all day) · decision (b)+(c)

Owner decision on the universe question: (b) ranking bias BUILT + (c1/c2) recons DELIVERED +
refill screen DELIVERED + contract-cap CLOSED. Broker clock verified is_open=false, next open
07-06 — all merges today are closed-market compliant.

- **[Part 1 #1126 `d42d435` 13:38:37Z] universe-viability candidacy bias — SHIPS DARK** —
  sort-key-only multiplier in rank_suggestions_canonical toward the recon-viable set (SPY 1.30 ·
  QQQ/TSLA/IWM/SLV 1.15 · NFLX 1.10 marginal-provisional, pre-epoch-EV hypothesis in-code).
  Never a filter, never a mutation: stored risk_adjusted_ev byte-identical (the allocator's
  split skew reads it), below-floor stays −999, the stage-seam roundtrip gate reads untouched
  ev; positive scores only (boosting a negative would invert intent). Flag
  `UNIVERSE_VIABILITY_BIAS_ENABLED` strict '=1' (behavioral; non-'1' warns once). **ARMING IS
  AN OPERATOR ENV ACTION (not armed).** 10 tests; H8 both workers @ d42d435.
- **[Merge-timing note — false alarm, retracted with evidence]** the CI watch→merge chain
  slept ~7h and merged at 13:38Z "8 minutes into RTH" — flagged as a §2 violation, then
  RETRACTED against the broker clock (July-4th-observed holiday, is_open=false; the morning
  ops_data_stale market-arm firings are the documented holiday pattern; the recycle swallowed
  nothing — 13:40:01Z order_sync tick green). LESSON KEPT: watch→merge automation must
  clock-check (broker calendar, not weekday) before merging — until a guard exists, don't
  leave merge chains unattended near session boundaries.
- **[Part 2A/2B refill screen — READ-ONLY, owner-decision input; all quotes = off-hours
  holiday snapshot, indicative]** **ADD LIST: EMPTY — zero candidates pass f1–f5.** Best new
  name (CVX $52/ct) exceeds the $40 ceiling off-hours; every sizing-trap NO (BITO $10/ct but
  15 lots · GDX A-grade OI but 9 lots · EFA/KRE/XLRE/FXE) is ROBUST to the off-hours caveat —
  spread compression cannot fix per-ct EV collapse. Conditional shortlist for an RTH
  re-screen: **MRK + CVX** (OI grade A, 2–3-lot sizing, need <~$25–40/ct at RTH — 40–60%
  compression on A-grade names is plausible, HYPOTHESIS). **In-universe verdict FLIPS: DIA
  measured $28/ct (SPY-class-adjacent — amend the 07-03 'structurally cannot' class) and GLD
  viable ONLY on $5-multiple strikes** (its $1-strikes are OI-dead). PRUNE candidates
  (owner-gated; cost is scan/API only): strong = SNAP·NIO·MARA·F·LYFT·AAL·RIVN·SOFI (all
  sub-$20, structurally dead per the sizing trap; ⚠ SOFI = the only name that ever live-filled
  — owner judgment); second tier = T·CMCSA·PFE·KHC·DKNG·WBD·CCL·FXI·KMI·EWZ. CAUTIONS:
  (i) iv_rank warm-up — a fresh add is scanner-invisible ~60 trading days
  (`iv_rank_insufficient_history`, options_scanner.py:3032-3040); **SEEDING EXISTS**:
  `iv_historical_backfill` accepts payload {symbols, days} (handler :94-100, background
  queue, idempotent upsert) — pair any add PR with a one-shot seed; thin-contract history may
  stay sparse; unseeded bulk adds push the iv_pipeline_no_data alert threshold.
  (ii) CORRELATION — {SPY, DIA, QQQ, IWM} = one US-equity-beta trade in four wrappers; the
  envelope doesn't know DIA≈SPY; treat as one bucket in any add/prune decision; the
  diversifying conditionals are MRK (pharma) / CVX (energy, but XOM/XLE overlap) / GLD.
- **[Part 3 — sizer contract-cap CLOSED, evidence-based]** the roundtrip gate's verdict is
  contract-count-INVARIANT (both sides scale with n; per-ct terms decide: ev_ct<cost_ct → no
  n clears; ev_ct>cost_ct → MORE contracts help clear the $15 floor — a cap can only flip
  passes into fails). The hypothesized crowd-out mechanism is allocator-slot ORDER, which
  Part 1 addresses. No cap, item closed; slot re-flow-after-reject noted as a possible future
  recon ONLY if a cycle ever demonstrably loses a viable candidate to a doomed higher-ranked
  one.

PENDING (holiday-shifted): market closed 07-03 → post-un-pause staging proof, typed-segment
forward row, [CLOSE_FILL_GAP], and the breaker's next real evaluation all move to MONDAY
07-06. Today's 21:30Z policy_lab_eval still fires (scheduler is holiday-blind) → verify green
on the normalized basis (no verdict flip expected at current n). Heartbeat pings run 8–17 CT
today regardless → the UP email residual clears today. OWNER DECISIONS OPEN: arm
UNIVERSE_VIABILITY_BIAS_ENABLED=1 (env, no deploy) · RTH re-screen of MRK/CVX (next trading
session, read-only) · prune list · DIA/GLD class amendment.

## status:armed — 2026-07-03 ~15:18Z (holiday window) · decision-execution T-phase

- **[T1 — BIAS ARMED]** `UNIVERSE_VIABILITY_BIAS_ENABLED=1` set on BOTH workers; var-change
  recycles SUCCESS @ `a958fb4` 15:18:27/29Z — running containers created post-set carry =1.
  EXPECTATION CORRECTED vs the instruction: a correct `=1` emits NO log line by design (§3
  strict-parse warns ONLY on a non-'1' value) — silence + behavior is the signature.
  Names-only hygiene forbids a value dump read-back; the behavioral read-back is Monday's
  pin: **07-06 16:00Z scan → sort-key reorder visible in ranking, stored risk_adjusted_ev
  byte-identical (the dark-ship pin, now live).**
- **[T2 — baseline captured; closes at 21:30Z tonight]** 07-02 21:30Z eval (pre-#1124):
  `no_promotion`, challengers die at GATE 2 (`insufficient_trades`: conservative 0, neutral 1
  vs required 10) — the utility comparison NEVER RAN at current volume. Tonight's normalized
  first-eval evidence is therefore: job green + flag-default-ON path executed + same
  insufficient_trades verdict; **the SOFI-twin magnitude proof only becomes observable when a
  challenger reaches Gate 4 (≥10 trades + ≥MIN_TRADING_DAYS)** — do not mistake verdict-
  sameness for the normalization not running.
- **[T3 — OPERATOR-CONFIRM open]** heartbeat pings fired 8:00 CT today (scheduler mon–fri,
  holiday-blind) → the check should have flipped UP at the first ping; confirm the UP email
  arrived (closes the Grace-test residual).
- **[T4 — FILED]** broker-clock guard on watch→merge automation → backlog P2 (merge chains
  check `get_clock.is_open`, fail-safe to NOT-merge; no unattended chains near boundaries
  until built).
- CLOSED/DO-NOT-REOPEN (recorded): contract-cap (count-invariant algebra) · slot re-flow
  (future recon only on a demonstrated lost-viable-candidate cycle) · the empty add-list
  verdict STANDS — no refill re-run without new evidence (tier change or structural change).
- MONDAY QUEUE (own sessions): M1 MRK/CVX RTH re-screen (read-only, mid-session batch) ·
  M2 GLD $5-strike feasibility recon (config-vs-surgery verdict) · M3 standing proofs ·
  M4 post-close universe PR (prune strong tier MINUS SOFI — **SOFI stays as the canonical
  gate sentinel**: if it ever CLEARS the roundtrip gate, the spread regime, EV math, or a bug
  changed and we want to see it loudly; DIA → bias tier 1.15 with the one-beta-bucket note;
  GLD/MRK/CVX per M1/M2 verdicts; adds pair with iv_historical_backfill seeding).

## status:reported — 2026-07-03 v5.3 FULL (weekend deep-dive; report `audit/reports/2026-07-03-FULL.md`)

Budgets: 16/20 SQL · 2/6 broker · 4/12 subagents · 24 files fully read. Broker flat,
SHA `e0bbe6e` everywhere, H11 = 4 (all today's holiday data_stale highs). READ-ONLY held.

- **A9 GRADUATION RECORDED (owner decision 2026-07-03, first exercise of the rule):**
  Alert & Signal Integrity is STANDING/PERMANENT (founding finding shipped #1106+#1115,
  measured 39→0). `audit/area9.md` header frozen as the standing contract. The rotating
  slot moved to A10, adopted this run: **Calendar & Clock Integrity** (`audit/area10.md`
  — five time-boundary instances in 72h; first-run NEW finding: the winter-close blind
  hour, 20:00–21:00Z EST-season staleness+watchdog gap, fix before November).
- **TOP-3 #1 — #1126 viability bias is BUILT-NOT-WIRED (HIGH; double-confirmed):**
  `rank_suggestions_canonical` has ZERO production callers; the executor orders
  candidates via its own local sort (`paper_autopilot_service.py:118-131`). This
  morning's armed flag is INERT; Monday's "bias live" pin is VOID until wired. The
  shipped tests pinned the orphan function — the `9a2cef1` class, self-inflicted
  same-day, caught by PASS-2. Fix = one call site + an executor-path wiring test,
  item 0 of Monday's M4 window. Env stays set (correct once wired).
- **TOP-3 #2 — A9 alert-taxonomy cluster (9 findings, 4 MEDIUM):** `force_close` is a
  costume worn by three realities (31% of rows describe NO close — submitted/FAILED/
  warn-only share one critical type; post-epoch all three relay under one phone title);
  `alert_type="warn"` carries zero semantics (706 rows/30d); severity vocabulary
  fragmented — `medium`+`warn` are the two largest warning-class buckets, invisible to
  canonical `severity='warning'` readers (**misses 83%**); the designed client=None
  egress logs a "legacy mode" misconfiguration WARNING on every relayed row. One
  post-close taxonomy PR fixes the channel before the next live force-close egresses.
- **TOP-3 #3 — one-beta-bucket uncontrolled (A2, MEDIUM):** {SPY,DIA,QQQ,IWM} has NO
  block-level control — `max_correlation_cluster_pct` is declared-never-read (config
  fiction), ranker correlation is same-symbol-only, sector check warn-only with ETFs in
  an accidental shared bucket; the bias (once wired) steers INTO this. Additive control
  candidate, owner-gated.
- Other MEDIUMs: `check_rollback` mis-restores after a "recommended" promotions row +
  cooldown consumed by recommendations (latent until promotions move; cheap fix) ·
  promotion utility is structurally single-factor (tail/slippage/concentration inputs
  never written; drawdown penalty unit-mismatched ≈ ≤$0.40) · stuck-`running` job_runs
  have NO reaper (mid-run recycle orphans permanently; learning chain overlaps the merge
  window) · §4 kill-switch coupling: unsetting ENTRY_QUOTE_VALIDATION_ENABLED silently
  disables the #1101 roundtrip gate · GTC pilot-list UNSET = all-eligible (not
  pilot-off).
- Notables: suggestions_open extras RESOLVED benign (operator --force CLI, 5 of 15) ·
  cooldown-vs-cadence NOT doubled by #1114 (hourly by a 2-second phase margin — thin) ·
  SLV structurally benched until ~Sept (iv warmup; viable-tier aspirational) ·
  resting-TP pilot no longer resting (book flat; unexercised) · A8 reconstructability:
  spread-class 100% quotes/no OCC identity, EV-class 0% legs, spot-at-decision 0%
  everywhere · A7 proposed MERGED into A1/A3 until ≥10–15 live fills · scorecard + full
  owner-decision list (10 items) in the report.

PENDING VERIFICATIONS (unchanged + one added): tonight 21:30Z normalized-basis eval
(baseline captured; expect green + insufficient_trades) · Monday M-queue **with M4
item 0 = the F1 wiring fix** · heartbeat UP email (operator ③④-class confirm).

## status:plan-encoded — 2026-07-03 post-deep-dive EXECUTION PLAN (owner decisions, verbatim runbook)

Owner encoded the week 07-03 evening. THE RUNBOOK for Mon/Tue sessions — recover from here.

- **DOCTRINE ADDITION (staged for M4's doc rider, not yet in CLAUDE.md):** "Tests for a
  flag-gated behavior must pin the PRODUCTION CALL PATH, not the function in isolation —
  an orphan function with green tests is the 9a2cef1/#1126 class." (F1 detection latency
  <24h via PASS-2 vs 2 months for 9a2cef1.)
- **MON RTH (read-only):** M1 MRK/CVX re-screen (f1–f5; hypothesis: $52–70/ct compresses
  <$40/ct) · M2 GLD $5-strike config-vs-surgery verdict (no build) · M3 proofs WITH
  CORRECTION: **"bias live at 16:00Z" pin STRUCK VOID (F1)** — replaced by: 16:30Z
  post-un-pause staging proof · typed-segment forward row / first live [CLOSE_FILL_GAP] /
  breaker re-eval IF a close lands (trailing 3 losses — next losing close re-trips BY
  DESIGN).
- **MON POST-CLOSE — M4, ONE PR (item 0 governs):**
  M4.0 F1 wiring fix — `_viability_rank_key` into `get_executable_suggestions`' sort
  (paper_autopilot_service.py:118-131), flag-gated (env stays armed). THE test: viable
  outranks equal-score non-viable IN get_executable_suggestions' OUTPUT; flag-off
  byte-identical THERE. Orphan-function tests stay but don't count as wiring proof;
  rank_suggestions_canonical fate noted-not-deleted.
  M4.1 universe per M1/M2: prune SNAP·NIO·MARA·F·LYFT·AAL·RIVN (SOFI = permanent
  sentinel, code comment + rationale); DIA → tier 1.15 + one-beta note; GLD per M2;
  MRK/CVX per M1 (+ iv seeding if added).
  M4.2 doc riders: §4 corrections (ENTRY_QUOTE_VALIDATION↔#1101 kill-switch coupling;
  GTC pilot-list unset=all-eligible) · §8 additions (A9-F6 legacy-mode WARNING, A9-F7
  severity fragmentation 83%, A9-F8 one-convention detector; EXIT_EVAL_DEBUG entry
  STAYS) · breaker runbook line ("un-pause without a new WIN re-trips on zero new
  closes") · the doctrine addition above · backlog: F-A1a P2 w/ HARD TRIGGER "ship
  before any challenger reaches 8 trades"; reaper P2-ELEVATED (this week's spare slot);
  winter-close → check Tuesday PR carry else CALENDAR TRIGGER 2026-10-01; F-A2b/F-A2c
  P2 tail (batch w/ reaper if trivial).
  Tests: pruned absent · SOFI present + still gate-rejecting (sentinel pin) ·
  executor-path bias green · flag-off byte-identical. New pin on merge: **bias verified
  ON THE EXECUTOR PATH at Tuesday's 16:00Z scan.**
- **TUE POST-CLOSE — ALERT-TAXONOMY PR (approved):** split force_close →
  force_close / force_close_failed / envelope_violation_warn_only · real types for
  alert_type="warn" · normalize medium/warn severities (extend enforcement beyond
  alert() or map at write) · honest channel2-only wording for the designed client=None
  egress. CONSTRAINTS: relay/egress allowlists updated SAME PR (renamed types must not
  drop off the phone path — pin per-type egress tests) · historical rows untouched
  (readers map old types) · fingerprint continuity noted (fresh cooldown history
  acceptable, say so). Ledger line: "the phone channel stops lying."
- **NEXT SLOT — ONE-BETA BUCKET (recon-then-build):** B1 recon: PREFERRED shape =
  implement the dead `max_correlation_cluster_pct` knob as a real block-level envelope
  check with an ETF bucket map ({SPY,DIA,QQQ,IWM}=us_equity_beta), from_env loads it,
  confirm stage-time sees would-be book; FALLBACK ranker bucket factor. STOP after
  recon. B2 build: additive-only BLOCK, default-ON safety polarity, tests (2 same-bucket
  at cap → 3rd BLOCKED stamped; cross-bucket unaffected; flag-off legacy). Must land
  before the book routinely holds 2+ positions.
- Also rides any PR: OUTPUT_FRESHNESS `suggestion_rejections` @120h one-liner
  (no-weekend-exclusion caveat noted).
- **A7 MERGE + A1/A6 REFRAMES approved** — prompt v5.4 is owner-enacted after M4, not a
  session task. Retirement counters: all standing areas at 0.
- Gap-3(b): untouched, own recon-first session.
- STILL PENDING TONIGHT: 21:30Z policy_lab_eval normalized-basis close (baseline:
  no_promotion / insufficient_trades 0-and-1 vs 10; expect same verdict, job green).

## status:reported — 2026-07-04 NIGHTLY (report `audit/reports/2026-07-04.md`)

Quiet window (07-03 holiday close-of-day → Saturday): zero scans/fills/failures; both
workers SUCCESS @ `3689210` (two doc-only merges post-FULL-report, H8 clean, no recycle
since 17:43Z → env unchanged since the 15:18Z bias arming). Broker FLAT, equity =
last_equity = $2,093.74. Budgets: 14 SQL · 2 broker · 0 subagents. **NO NEW FINDINGS.**

- **⚠ OPERATOR PRECONDITION FOR MONDAY (M3): `entries_paused=TRUE` right now.** The
  breaker RE-TRIPPED 07-03 21:20:04Z on ZERO new closes (trailing-3 verbatim SOFI −40 ·
  MARA −15 · QQQ −73; paused_written=true; critical egressed `egress_owner='alert'`).
  **F-A2e LIVE-CONFIRMED <24h after being reported** — the trailing-window-every-ingest
  reading is production truth; the 07-02 PENDING wording ("next losing close re-trips")
  was the weaker reading. Un-pause any time before Mon 16:30Z buys the full session
  (breaker only evaluates at the 21:20Z ingest tail, mon–fri); expect a re-trip EVERY
  ingest night until a live WIN lands. Recovery stays operator-only (§9).
- ✅ **T2/gap-3(a) verification CLOSED**: 07-03 21:30Z policy_lab_eval GREEN on the
  normalized basis — `no_promotion`, Gate-2 insufficient_trades (conservative 0, neutral 1
  vs 10), exactly the encoded baseline. SOFI-twin magnitude proof still pends a Gate-4
  challenger. Side observation (filed under ledgered F-A1b, cited-not-refound): neutral
  eval row `capital_deployed 1876.2 / positions_opened 0` — window-artifact HYPOTHESIS;
  Gate 2 halts before utility consumes it.
- **A9-F5 rate EXACTLY confirmed**: 7 ops_data_stale highs on 07-03 (4 + 3 at
  17:37/18:37/19:37Z, halting at the 20:00Z gate) vs the "at most one" docstring. Feeds
  the Tuesday taxonomy PR context; no new finding.
- **#1114 re-verified**: 12 ops_health_check runs in 6h = 2/hour. **A3**: ingest dedup
  held (closed_positions_found=2 → duplicates skipped 2, outcomes_created=0); live
  post-epoch stays 6/8, raw mode holds. **Cooldowns**: zero active (SOFI expired
  unexercised). **A8 full protocol**: zero new negative-decision population; 30d ratio
  ≈5,603:15 (≈373:1); roundtrip-reject class still N=1; capture d8_v1 unchanged; NEW
  observation — policy_lab `decision_accuracy.rejection_accuracy` (n=7, informational) is
  the lens's first in-system consumer at cohort grain; per-gate efficacy still unmeasured.
  **A10**: no new instance (holiday patterns exercised as spec'd); retirement counter 0→1.
- Heartbeat UP-email confirm still operator-side; weekend cron silence = no false DOWN
  expected before Mon 08:00 CT.

PENDING VERIFICATIONS (2026-07-04 consolidation — the Monday list, gated on the un-pause):
- **Operator un-pause + ACK the 21:20:04Z breaker critical BEFORE Mon 16:30Z** (else the
  staging proof and all downstream M3 proofs silently no-op again).
- Mon 07-06: 16:30Z staging proof · typed-segment forward row · first live
  [CLOSE_FILL_GAP] gap_fraction · breaker re-eval at 21:20Z (zero-close day → re-trip
  EXPECTED) · #1115 job_late Monday storm = 0 · M1 MRK/CVX RTH re-screen · M2 GLD recon ·
  M4 PR (item 0 = F1 wiring fix; new pin: bias verified ON THE EXECUTOR PATH at Tuesday's
  16:00Z scan).

## status:reported — 2026-07-06 NIGHTLY (Monday 00:00 CT scheduled run, pre-RTH; report `audit/reports/2026-07-06.md`)

Dead-quiet window (07-04 report → 07-06 05:01Z): the ONLY job_run was `phase2_precheck`
07-06 05:00:02Z green; zero fills/orders/scans/suggestions/rejections/alerts (any
severity); zero cooldowns; both workers SUCCESS @ `3689210` = origin/main (no deploys or
recycles since 07-03 17:43Z → env unchanged since the 15:18Z bias arming, by
construction). Broker FLAT, equity = last_equity = OBP = $2,093.74. Budgets: 9 SQL ·
4 broker · 2 Railway · 0 subagents. **NO NEW PRODUCTION FINDINGS.**

- **⚠ OPERATOR PRECONDITION STILL OPEN at run time (05:01Z): `entries_paused=TRUE`**
  (unchanged since the 07-03 21:20:04Z re-trip; reason verbatim SOFI −40 · MARA −15 ·
  QQQ −73). Un-acked critical/high = 8, all 07-03 (1 breaker critical `c598eec4` + 7
  holiday `ops_data_stale` highs). This report is the LAST audit checkpoint before the
  Mon 16:30Z window — un-pause + ACK first thing.
- **AUDIT-LOOP OBSERVATION (local tooling, not production): the Sunday 07-05 FULL run
  never started** — `audit/cron.log` has no start marker between Sat 07-04 00:01 (exit
  0) and Mon 07-06 00:00:02 (this run); Task Scheduler didn't fire (machine off/asleep
  HYPOTHESIS). Realized cost $0 (weekend retroactively verified silent); class = the
  watcher has no watcher. Fix (operator-side, additive): Task Scheduler "run after
  missed start" + "wake to run" on `\nightly-audit`; optional #1109-symmetric
  healthchecks ping on report write. Same log shows 3 historical start-without-end
  markers (06-14, 06-20, 06-30).
- **A3 window-slide note (not new data):** paper 30d reads n=8 / −2,062.80 (was 9 /
  −1,870.80) — writer ran 0× in window; one early-June positive paper row aged out of
  the sliding 30d window. Live unchanged: n=6 / −153.00 all post-epoch; raw mode holds
  at 6/8.
- **A5 lesson:** 2 of 9 SQL wasted on 42703s (`job_runs.job_type`→`job_name`,
  `reentry_cooldowns.expires_at`→`cooldown_until`) — the introspect-first rule applies
  to EVERY table not queried this session, not just learning tables.
- A8 full protocol: zero new negative-decision population; 30d ratio ≈5,255:14 ≈375:1
  (both sides sliding); roundtrip-reject class N=1 all-time; counterfactuals correctly
  empty (market closed). A9: zero new alert rows → nothing to measure; Tuesday taxonomy
  PR stands. A10: no new instance; retirement counter 1→2.

PENDING VERIFICATIONS (2026-07-06 — the Monday list, unchanged + one added):
- Standing Monday list above (un-pause gate · staging proof · typed-segment ·
  [CLOSE_FILL_GAP] · 21:20Z breaker re-eval · #1115 job_late storm=0 [checkable at
  Tuesday's nightly] · M1/M2/M4).
- NEW: operator decision on the missed Sunday FULL — wait for 07-12 vs one mid-week
  FULL after M4 + taxonomy land (NIGHTLY tonight was contract-correct; the FULL cadence
  slipped silently).

---

## 2026-07-06 POST-CLOSE — M4 SHIPPED + ERRATUM + INVERTED-UNIVERSE MARKER

- **⚠ INVERTED-UNIVERSE MARKER (07-06 16:00Z scan — EXCLUDE from gate evidence):**
  Alpaca nulled the retired PDT daytrade fields (weekend 07-04) → `int(None)`
  TypeError in `alpaca_client.get_account()` serializer → OBP read died → $500
  `paper_baseline_capital` fallback → `get_tier(500)`=micro → $60 underlying cap →
  56 `micro_tier_underlying_too_high` rejections → zero candidates at 16:30Z
  executor. Today's zero is the INCIDENT's zero, not the gates' — classified (c),
  excluded from honest-economics and gate-behavior baselines (like the 07-03
  holiday). Scan budget observed deployable=500/cap=450 vs healthy 2093.74/837.50.
- **ERRATUM (process, 07-06 ~19:10–19:25Z):** a compaction-summary date phantom
  ("Tue 07-07") + stale context header (07-01) made a 4-minute-old job_runs row
  (19:05Z) read as a 23h scheduler outage; reported to the operator as a system-wide
  incident with a fabricated-by-arithmetic healthcheck-email claim. Operator
  authorized a BE restart on that false report: redeploy `1b3e7dcd`, same SHA
  `3689210`, swap 19:24:25Z, ZERO missed ticks (19:25:01Z order_sync dispatched by
  the new container, succeeded end-to-end). No incident existed — 143 jobs green
  that day. Same class as the 06-11 deploy-lag erratum + 07-03 holiday false alarm.
  **Fix shipped: STEP 0 clock grounding** (DB `now()` + broker `get_clock` BEFORE
  any time arithmetic; clocks beat headers/summaries/stated time) — operator
  directive, now CLAUDE.md §1 first corollary + session memory.
- **M1 verdict (MRK/CVX RTH re-screen, closed 07-06):** MRK = NO ($41–46/ct
  round-trip crossing on every pair sampled RTH). CVX = MARGINAL-ADD ($25–29/ct on
  healthy-OI 170/175 strikes; the $19 headline pair was a dead-OI mirage) → CVX
  added with iv-seeding (60d) + viability tier 1.15.
- **M2 verdict (GLD strike modulus, closed 07-06):** built as one-line-config at
  the `_split_chain_to_calls_puts` seam — `SCANNER_STRIKE_MODULUS` env (default
  "GLD:5"), subset-or-fallback (never filters to empty). OI-floor generalization
  filed as follow-up (backlog).
- **M4 SHIPPED (this squash):** item 0.1 serializer null-tolerance
  (`_req_float` fail-loud-by-name on required fields; retired daytrade fields
  null→placeholder) · item 0.2 fail-CLOSED capital (live-mode OBP-None → critical
  `account_unreadable_entries_blocked` + deployable 0.0 → CapitalScanPolicy blocks
  the cycle; $500 baseline survives ONLY explicit paper mode; unreadable ops mode
  = live) · item 0.3 pin tests (12 new-file + the CONTRACT-CHANGE rewrite pair in
  test_capital_basis_consistency replacing
  `test_falls_back_to_paper_baseline_on_alpaca_failure`) · item 0b **#1126 bias
  WIRED into the production path** (`get_executable_suggestions` sort at
  paper_autopilot_service.py; sort-key-only, positive scores only, flag-off
  byte-identical; EXECUTOR-PATH wiring test per the new §9 never-do) · item 0.4
  OBP-failure alert wording (consequence now truthful) · M2 modulus · tiers
  +DIA/CVX/GLD 1.15 · OUTPUT_FRESHNESS + suggestion_rejections/120h · CLAUDE.md
  riders (STEP 0 corollary · #1038/#1101 kill-switch coupling · GTC pilot
  unset=ALL correction · #1119 runbook line · §8 A9 additions · §9 two never-dos)
  · backlog riders (F-A1a trigger, reaper P2-elevated, winter-close 2026-10-01
  calendar trigger, OI-floor).
- **Post-merge DB mutations (operator-approved, executed tonight):**
  scanner_universe deactivate SNAP/NIO/MARA/F/LYFT/AAL/RIVN (SOFI stays —
  permanent roundtrip-gate sentinel) + add CVX; `iv_historical_backfill` enqueued
  {symbols:["CVX"], days:60}.

PENDING VERIFICATIONS (2026-07-07, added by the M4 ship):
- **Post-fix live proof (first healthy scan):** scan budget deployable≈2093.74 /
  cap≈837.50, tier=small, ZERO `micro_tier_underlying_too_high` rejections.
- **Bias first live cycle:** executor log shows viability-biased ordering (flag
  armed since 07-03); flag-off comparison not required — wiring test pins it.
- **GLD modulus first scan:** GLD rejections collapse to $5-strike population only.
- **CVX:** IV-integrity-ELIGIBLE as of 07-06 20:28Z — days:90 top-up
  (job f5f7b8be, 111s) after the days:60 seed (a06c143d): 84 distinct
  non-null iv_30d days (2026-03-02→06-30), 0 dup (underlying,as_of_date),
  idempotency held (skipped_existing=55/ok=29/failed=0). Gate rule cited:
  iv_repository.py:26 MIN_IV_HISTORY_DAYS=60; :224-249 sample COUNT of
  non-null iv_30d rows (≤252 recent) — contiguity irrelevant; scanner
  rejection seam options_scanner.py:3060-3067. PIN (16:00Z scan, 11:00 CT):
  CVX in the scanned set, iv_rank computed (sample_size 84+), NO
  iv_rank_insufficient_history rejection for CVX; if it candidates, first
  roundtrip-gate evaluation with verbatim numbers (expect MARGINAL vs $15).
- **21:20Z breaker re-eval (tonight):** expected RE-TRIP (no live win 07-06) —
  critical + email is DESIGNED (runbook); un-pause remains operator-only.

2026-07-06 POSTCLOSE AUDIT (v5.4 first run, operator-invoked; report
`audit/reports/2026-07-06-postclose.md`) — status:reported:
- **A9 FINDING — egress delivery-receipt gap**: `_maybe_egress_risk_alert`
  discards send_ops_alert_v2's result (alerts.py:85-95); success logs at
  invisible info (ops_health_service.py:1379); `egressed_at` never stamped
  by inline sends — safety-trip delivery disputes close on inference, not
  fact (tonight's breaker-email triage = 4 evidence hops). FIX (additive):
  capture insert id → post-send metadata UPDATE {webhook_sent, egressed_at,
  suppressed_reason} + warning-visible receipt log both outcomes. RIDES THE
  TAXONOMY PR (same files, one recycle).
- Pins P1–P5 all PENDING → converge on 07-07 16:00–16:30Z + first close.
- Free-look: broker 0 open orders / 0 positions on flat book (no orphaned
  GTC); fossils unchanged (22 queued / 4 stuck-running).
- Counters: A9→0, others →3 (A7 dormant). No retirement candidates.

## 2026-07-11 (Sat ~02:2x ET) — BUILT: observability remainder — 5 noise classes (#1156)

STEP-0: broker 02:27 ET CLOSED (Sat). **#1156 `cb82692` MERGED + H8 VERIFIED**
(BE `15ac9053` / worker `4c648035` / worker-background `0aed1f7a`, all SUCCESS @
`cb82692`, created 06:45:38–39Z > merge 06:45:36Z). Queue ② — the five items
left after F-A4-1 absorbed the A4-detector half.

1. **Flat-book stale guard** (`get_output_freshness`): count open positions
   once; a flat book (0 open) → `paper_positions.last_marked_at` reads `flat`
   (no alert), not `stale` (~48/day false-HIGH). A HELD position past TTL still
   fires; fail-safe on count error. Both directions tested.
2. **Condition re-emit dedup** (`job_succeeded_with_errors`): **RECON
   CORRECTION** — cross-owner ROW dedup already works (`egress_owner`); the real
   4× was same-condition re-emit. Fingerprint by RUN_ID + 24h cooldown → once
   per run, not 14×. Genuine safety trips (force_close / streak_breaker_* /
   force_close_failed) UNAFFECTED (they keep the shared cooldown).
3. **Accuracy-warn dedup**: fold `wins/n` into the fingerprint (re-alert on
   VALUE CHANGE) + 24h cooldown. Stays observe-only.
4. **IV all-missing → PARTIAL** (chosen per the F-A4-1 contract): `ok==0` with
   symbols present → `counts.errors` → the runner records `partial`.
   Some-missing (ok>0) stays green (individual seasoning is normal).
5. **Stub-vs-real watch**: `EXPECTED_JOBS` now watches `paper_learning_ingest`
   (the real EOD producer, scheduler.py:69), not the `learning_ingest` no-op
   stub. test `DAILY_JOBS` + the `.eq→.in_` mock updated.

Expected H11 delta: **~60+/day quieter** (48 stale + 10–14 accuracy + the
condition re-emits). **⭐ v1.2 report file now ON DISK** (operator dropped it
via #1155, `docs/review/external-full-audit-v1.2-2026-07-10.md`) — the standing
sweep is CLOSED; the I6 wording-fix-inside-the-file remains a pending one-liner.
Untouched: E7 (queue ③, spec on file) · PR2 · F-A3-1 · trading logic.

## 2026-07-11 (Sat ~01:1x ET) — BUILT: F-A4-1 typed job-outcome contract + fossil reap (#1153)

STEP-0: broker 01:54 ET CLOSED (Sat) / DB ~05:5xZ. **#1153 `2478845` MERGED +
H8 VERIFIED** (BE `423bec81` / worker `f0b6b0f2` / worker-background `88f466a7`,
all SUCCESS @ `2478845`, created 06:16:08–09Z > merge 06:16:06Z). ROLLOUT
INVENTORY (post-recycle): **fatal_masked_green=0** (clean — no hidden failures
exposed; the danger was 0-instance pre-build), fossils_remaining=0,
partial_rows=0 (weekend — Monday's runs first exercise the contract), reaped=27.

**PRE-STEP — FOSSIL REAP (supervised):** 27 stranded rows (22 queued + 5
failed_retryable, 19–179d, none needing replay) dead-lettered with a
move-don't-lose annotation (prior_status / days_stale / reason). Before 27,
after 0.

**THE CONTRACT.** The runner recorded a handler's RETURNED failure as
'succeeded' (keyed success solely on `users_failed>0`); a fatal monitor that
returned `{ok:False}` (intraday_risk_monitor / post_trade_learning /
day_orchestrator) was recorded succeeded + invisible to the A4 detector.
- **DESIGN — RAISE-not-return:** the 3 swallow-fatal handlers DELETE their
  catch-all `{ok:False}` returns and RAISE; the runner's exception path owns
  fatals (→ failed_retryable, visible; the next cron re-runs regardless).
- **`_classify_handler_return`** (module-level, testable): derives a REAL
  terminal `partial` from the return — `users_failed>0` OR `counts.errors>0` OR
  a truthy top-level `error` key (future-proofs a new swallow-return).
  Designed-false handlers (ops_health_check `ok:False`→now `ok:True`+`healthy`;
  executor `status:partial`; policy_lab `status:error`) carry none → succeeded.
- **`partial` is a real status** (was mislabeled `failed_retryable`, which the
  scheduler WRONGLY retried + the dependency filter MISSED). EVERY job_runs.status
  consumer from the B2 list migrated: ops_health_service liveness/freshness/
  regime/A4 (`.in_ succeeded,partial`), runner terminal-skip + public_tasks
  TERMINAL_STATES + JobStatus enum, **JobDependencyService phantom
  `partial_failure`→`partial` FIXED**, dashboard (partial→degraded). Scheduler
  retry keys on `failed_retryable` only → partials no longer wrongly retried.
  8 consumer tests updated (mock `.eq`→`.in_`; `ok`→`healthy`) — contract-update
  discipline, not a defect.
- **⚠ `failed_retryable` is now an HONEST LABEL, not a working retry** —
  re-dispatch lands with the **F-A4-2 + reaper** package. **The `mark_retryable`
  finished_at fix is DEFERRED to F-A4-2** (coupling: setting it now + the broken
  re-dispatch would create fossils via the scheduler's flip). C3 verdict: TWO
  builds.
- **ABSORBED obs-PR-#1's A4-detector half** (the `partial` status IS the
  silent-failure signal now). **obs-remainder (queue ②) = flat-book stale
  guard · cross-owner re-egress dedup · accuracy-warn dedup · iv-refresh
  all-missing→ok · stub-vs-real-producer watch.**
- RESIDUAL (cosmetic follow-up): paper_auto_execute still emits `ok:false` on
  gate-rejects (exact return literal not located; the runner ignores `ok`, so
  it is correctly `succeeded` — just ~21 designed-false rows of false-green-query
  noise; ops_health_check's 332 were relabeled).

Untouched: E7 re-wire (queue ③, spec on file) · PR2 client_order_id · F-A3-1 ·
all trading logic. ⚠ The v1.2 report file is STILL not on disk — sweep pending.

## 2026-07-11 (Sat ~01:04 ET) — EXTERNAL AUDIT v1.2 ADJUDICATION (verified vs code@e45290f + DB + broker)

STEP-0: broker 01:04 ET CLOSED (Sat) / DB 05:04Z — agreed. READ-ONLY + doc
writes. ⚠ The v1.2 report file is NOT on disk (`docs/review/` has only the
07-09 packet + v1.1 prompt) — adjudicated from the operator's inline cites;
sweep pending the file at `docs/review/external-full-audit-v1_2-2026-07-10.md`.

**P0 — F-A4-1 (fatal handler results persisted as succeeded) → CONFIRMED
STRUCTURAL, 0 FATAL INSTANCES (bounded).** Chain verified: `runner.py:134`
success keys SOLELY on `users_failed>0` — `ok:false` / `status:partial` /
`counts.errors` all fall to `mark_succeeded` (`job_runs.py:125` writes
`status='succeeded'` blind to the body); `intraday_risk_monitor.py:152-158`
RETURNS `{"ok":False,"error":...}` on a FATAL exception (no `users_failed`, no
`counts`) → recorded succeeded; the A4 detector `ops_health_service.py:669-681`
reads ONLY `counts.errors` → the fatal return is doubly invisible. **No
normalization layer exists (confirmed).** HEADLINE QUERY (45d): 356
`succeeded`+`ok=false` rows BUT **fatal_masked_green = 0 on every job**
(`result ? 'error'` = 0) — the 356 are DESIGNED ok=false (ops_health_check ×332
detecting alerts · paper_auto_execute ×21 gate-rejects · suggestions_open ×3);
**ZERO intraday_risk_monitor false-green rows** — no protection cycle has ever
failed green. So the finding is real-but-unexercised: critical as a CLASS (the
plane beneath all job monitoring), blast radius bounded, rollout won't expose a
hidden backlog (0 current fatals). NEW HEADLINE BUILD (typed outcome contract).

**P1 — E7 (viability bias bypassed) → CLOSURE FALSE = THIRD #1126 INSTANCE.**
The active executor route is `_execute_per_cohort` (`paper_autopilot_service.py
:864-865`), which sorts via a Supabase `.order("risk_adjusted_ev").order("ev")`
on the STORED column. The M4/#1132 viability bias is sort-KEY-only (never
persisted) and lives in `get_executable_suggestions` (`:130,141`), reachable
only at `:506` — AFTER the `:452` early `return self._execute_per_cohort(...)`
when policy-lab is on (the live 3-cohort arch). The wiring test
(`test_m4_obp_failclosed_and_wiring.py:174`) source-string-asserts the DEAD
route — the exact #1126 tell. **The bias is armed + green-tested but INERT on
the live route.** Fix: re-rank the fetched `suggestions` list in Python inside
`_execute_per_cohort` + a test that drives THAT route. (rank_suggestions_canonical
still has ZERO production callers.)

**P1 — F-STATE-I6 → RESOLVED (prompt-wording artifact).** "merged package" =
merged into ONE EPIC (P0-B book-scaling readiness, backlog-level), never
claimed code-shipped; the substantive point (unbuilt, tripwire-only guard) was
already our STATE. Nothing else read "merged" as shipped. Fix the language in
the canonical v1.2 file when placed.

**P2 — HIGH-CONSEQUENCE LATENTS:**
- **F-A10-1 → CONFIRMED (split), LATENT.** (a) missing/unparseable expiry →
  `paper_exit_evaluator.py:158` returns 999 DTE → DTE-based exit conditions
  silently skipped (fail-OPEN; only on absent/corrupt expiry). (b)
  assignment-created EQUITY filtered out of the option sync
  (`alpaca_client.py:540-543`, `len(symbol)>10` heuristic) → unmanaged stock;
  both reconcile paths consume the option-only set. Book flat now → unexercised.
  Assignment-adjacent (A2 charter).
- **F-A2-1 → CONFIRMED (code), likely-not-live-exercised.** The POST-FILL hook
  `maybe_place_gtc_profit_exit` (`gtc_profit_exit.py:328-464`, wired at
  `alpaca_order_handler.py:944`) NEVER checks the pilot allowlist — it parks a
  GTC for any eligible live multileg entry; only `GTC_PROFIT_EXIT_ENABLED`
  (default OFF) gates it (the sweep path DOES check the allowlist). DB: 6
  `intentional_resting_exit` orders (all cancelled, 06-13→07-08) — consistent
  with the pilot sweep; no confirmed out-of-pilot placement (flag OFF). Priority
  jumps only if the flag goes ON before the allowlist is enforced on the hook.
- **F-A3-1 → CONFIRMED (both), NEW loss paths.** Outcome ingest NOT conserved:
  window filter (`:230-235`, 7d roll-off) + silent no-filled-closing-order drop
  (`:382-386`, `skipped_no_order` local-only). Exit cause ERASED: the LFL row
  (`_create_paper_outcome_record`) writes a static `reason_codes:
  ["paper_trade_close"]`, never `position.close_reason` — the learning chain
  never sees WHY a trade closed (close_reason IS carried, but only to
  `policy_decisions.realized_outcome`, a different table, policy-lab-gated).
  Mechanism is DISTINCT from the NFLX-06-08 epoch exclusion (new paths). Feeds
  the thesis-tracker (I5) — amend its charter.
- **F-A4-2 → CONFIRMED (silent-zero).** The automatic retry
  (`runner.py:142-176` → `mark_retryable` → `requeue_job_run` RPC) only FLIPS DB
  state; no `q.enqueue`, no RQ push. DB residue: 22 `queued` (latest 06-22) + 5
  `failed_retryable` (04-10) that never re-ran — the known 22-fossil class, now
  mechanism-explained. Live workers are RQ (no DB-poller in repo). Fix: re-enqueue
  on mark_retryable (or a DB-poll re-dispatcher).

**P3 — REGISTER SWEEP (one-liners):** F-A6-2 REFUTED (counters increment AFTER
eligibility) · F-A3-2 PARTIAL (autotune versions ARE read; but AUTOPROMOTE off
+ unscheduled → logged-not-applied, flag-gated compute-not-apply) · F-A9-1
CONFIRMED ("Confidence N%" from `overall_score`, a 0-100 rank not a probability
— mislabel; `SuggestionCard.tsx:683`) · F-A9-2 REFUTED (UI statuses still
emitted) · F-A8-1/2 PARTIAL (`suggestion_rejections` stores flat reason, no
economics/error category — conflated, not mis-assigned) · F-A10-2/3 PARTIAL
(weekday-only holiday-blind ops checks, BUT execution/monitor defer to broker
`get_clock` which knows holidays; session hours correct; no native calendar) ·
F-A5-1 CONFIRMED (`phase2_precheck` past its 48h self-expiry → `window_expired`
no-op every run; machine-consumed by nothing — dead precheck).

**ECONOMICS (their sharpening):** re-verified on today's live candidate — QQQ
16:00Z calibrated `ev 18.73` (=37.46×0.5), `net −15.27 < floor 15` → does NOT
clear; SOFI `edge_below_minimum`. STRENGTHENS the A6 SETTLED 1-of-N verdict
(does not contradict). Their 78%-thesis caution (5/9 horizons incomplete, n=8)
→ the thesis figure is a directional estimate on a tiny, partly-open sample;
the thesis tracker (I5) is the resolution path.

**EXTERNAL v1.2 SCORECARD (their 3rd engagement):** high hit rate — F-A4-1
(structural CONFIRMED, the class fix), E7 (a real 3rd #1126 instance we missed),
F-A3-1/F-A4-2/F-A5-1/F-A9-1 all CONFIRMED; the rest PARTIAL/REFUTED with the
distinction named. Q1-class method holds; weight high. Two calibrations: F-A4-1's
DANGEROUS manifestation is unexercised (0 fatal); F-A2-1 is flag-gated-off.

## 2026-07-10 (post-close ~16:21 ET) — BUILT: P0-A broker-acknowledged live-close invariant (#1149) [PR1 of 2]

STEP-0: broker 16:21 ET CLOSED (re-confirmed pre-merge) / DB 20:21Z. Post-close;
the live close path — no RTH exceptions. **#1149 `e45290f` MERGED + H8 VERIFIED**
(all three services SUCCESS @ `e45290f`, created 20:21:39–41Z > merge 20:21:37Z).

**E6 EXCLUSION-INTEGRITY FAIL → REMEDIATED (PR1).** Closure claim rewritten to
match the code: *"a live-routed close requires a broker acknowledgement; the
internal-fill block is STRUCTURALLY UNREACHABLE for live routing; every failure
lands in an explicit alarmed non-terminal state (`unknown_reconciling`),
position OPEN — never a silent internal fill."* The 2026-04-16 ghost-position
class is closed in code.

**RECON (STOP-IF-SURPRISED — no surprise in the chain):** the 4 cites re-verified
(routing default False + warn-proceed `:1700-1727` · submit result discarded,
`routed_to='alpaca'` unconditional `:2154-2177` · raised-submit → internal fill
`:2178-2280` · monitor costume `:1428`). ENTRYPOINT MAP: only entrypoints **1**
(scheduled exit evaluator) + **2** (monitor force-close) reach the fallthrough;
resting-TP/GTC (3,5), reconciler (6), orphan-repair (7), `_commit_fill` (8)
close on broker truth or are paper-only; manual endpoint (4) branches on process
`EXECUTION_MODE`, no internal-fill-on-exception. **THE MATERIAL FINDING (→ PR2):**
`client_order_id` is NEVER set at submit — the only broker handle (`alpaca_order_id`)
is lost exactly in the response-lost case; the charter's targeted lookup needs a
submit-path change (PR2). PR1 holds the response-lost case OPEN + alarmed —
invariant still fully held.

**BUILD (PR1):** STRUCTURAL GUARD before the internal-fill block —
`should_submit_to_broker` True → held open (needs_manual_review +
`force_close_failed` critical + `routed_to='unknown_reconciling'`); internal-fill
UNREACHABLE for live; fail-closed on a routing exception; shadow/paper unchanged.
Submit-exception "fall back to internal fill" REMOVED → same held-open. Routing-
query-failure fail-CLOSED (`position_is_alpaca=True` → authoritative portfolio
gate). Monitor success-costume fixed — only a COMPLETED close = success;
`unknown_reconciling` → not-closed, no bench. **`force_close_failed` gets its
FIRST real close-path producer** (allowlisted immediate-egress since #1134).
Reconciler's existing targeted `get_order(alpaca_order_id)` resolves case-(a)
pending closes; case-(b) `client_order_id` auto-resolution is PR2. Additive
(status TEXT, no migration). Tests: `TestAlpacaSubmitFallbackCriticalAlert` (pinned
the REMOVED fallback) → `TestP0ABrokerAckCloseInvariant` + new
`test_p0a_broker_ack_close.py` (guard decision behavioral + 4 seams pinned on
production); 120 exit/monitor tests green; full `_close_position` integration
deferred to PR2.

**CHARTER: BUILT (PR1).** Remaining (PR2, own session): deterministic
`client_order_id` at submit + reconciler `get_order_by_client_id` auto-resolution
of the response-lost `UNKNOWN_RECONCILING` edge. Untouched: stop TRIGGER logic
(what fires a close = Phase-3's territory) — PR1 changes only what happens AFTER
the decision to close.

## 2026-07-10 (early, ~00:1x ET post-close) — BUILD: PoP clamp-AND-log + walk-forward field contract (#1147)

STEP-0: broker 00:08 ET (closed) / DB 04:08Z — agreed. Combined Tier-1 PR per operator GO.
**#1147 `168a752` MERGED + H8 VERIFIED** (BE `5e1d241b` / worker `8a913217` /
worker-background `ca1da3cb`, all SUCCESS at `168a752`, created 04:57:01-02Z >
merge 04:56:59Z). Item 1 rides the recycle via calibration_service; Item 2 is
in zero live paths.

**ITEM 1 — PoP clamp-AND-log (fork verdict: MULTIPLIER overshoot; clamp, not
formula).** The delta-PoP composition (`ev_calculator`, convex combination) is
bounded ≤1 — raw `pop_raw` max 0.7945, 0 rows >1. The >1.0 originated ONLY at
`apply_calibration` (`pop × pop_mult`), already SILENTLY clamped since
2026-04-16 (`calibration_service.py:629`; last >1 row 04-16 16:00Z, zero after).
Made LOUD: `POP_CLAMP_ENGAGED` WARNING (raw pop · mult · product · clamped ·
strategy/regime/dte). **DORMANT-BY-ARITHMETIC:** pop_mult floored at 0.5 and
currently at the floor → pop×0.5 can never breach 1.0, so the log CANNOT fire
today — insurance for the day the multiplier climbs >1.0, NOT dead/broken code
(recorded so a future session doesn't misread "never fires" as broken). Legs
out of scope at the apply site. NO delta-path clamp (would be unreachable —
SKIP per operator).

**ITEM 2 — walk-forward field contract (fork verdict: HONEST CRASH, never
run).** `walkforward_validate_learning_v3.py` read `ev`/`realized_pnl`/`score`;
the VIEW `learning_trade_outcomes_v3` exposes `ev_predicted`/`pop_predicted`/
`pnl_realized` (+strategy/regime). Full rename — the recon's TWO-field diff was
actually FIVE (ev_predicted + pop_predicted + pnl_realized + strategy + regime
resolution; contract-audit catch). DELETED the H9-violating `0.5` prob
fabrication → fail loud. Added `WalkForwardContractError` on zero rows OR a
missing required column (closes the lying-empty class). NO view migration —
strategy/regime already exist + 99/99 populated. **SMOKE-RUN (read-only, n=99)
surfaced a SECOND real bug:** mixed microsecond/whole-second timestamps broke
`pd.to_datetime` → fixed `format='ISO8601'`. Script now runs to completion
honestly (exit 0; tiny-sample NaN Brier; no fabrication) — the rename is DONE,
the script has read the real columns once.

**RECONCILIATION 34→22→16.** The pollution has ONE home:
`trade_suggestions.probability_of_profit` (16 rows). The v3 VIEW's
`pop_predicted` is a JOIN-projection of `ts.probability_of_profit` (view def
confirmed); `learning_feedback_loops` stores no own pop. So 34 AND the earlier
22 were both view+base double-counts of the same 16. **DISPOSITION = ANNOTATE
(not re-derive), supervised, base table:** all 16 `trade_suggestions` rows
annotated (`marketdata_quality.pop_gt1_annotation`, `disposition=
annotate_not_rederive`, `original_pop` recorded), `probability_of_profit`
PRESERVED unchanged; before+after read-backs shown. All pre-04-16, paper,
consumed by nothing live.

**ERRATUM (the premise-check doctrine working).** The 07-10 build spec's ITEM-1
fork verdict placed the overshoot at the delta-cushion composition path; the
pre-build premise check re-confirmed the actual site (calibration multiplier,
already clamped 04-16) and prevented shipping a dead-code clamp. The
fork-verdict METHOD held; the SITE (in the spec AND in the original v1.2
free-look "delta-based overshoot; one-liner clamp") was wrong — corrected here
+ in backlog.

**RIDERS FILED.** (i) PoP CENSUS — verified **7 base PoP computations**
(ev_calculator.calculate_pop; calculate_exit_metrics `abs(delta)` = the
take_profit_limit source; calculate_condor_ev; options_scanner
`_estimate_probability_of_profit`; `_condor_pop_from_legs`;
opportunity_scorer `_calculate_ev_pop`; forecast_interface `forecast_ev_pop`)
+ 2 transforms (apply_calibration, conviction) — NOT "5" (the spec undercounted).
The inverted credit/width one (F-A3-1, latent) is calculate_pop's credit branch.
Rider on the multi-basis/PoP-unification item: **"the unified PoP MUST
bound-assert [0,1] at the compute site"** — the insurance lands once, at the
right place, when that work runs. I touched only the calibration-apply clamp (a
transform), NO base computation. (ii) Clamp boundary-log review trigger:
frequent `POP_CLAMP_ENGAGED` → cushion/multiplier revision, WITH the dormancy
note (can't fire while pop_mult ≤ 1.0). (iii) Prequential UNBLOCKED — the A1a
field-contract prerequisite is CLOSED; remaining for that build: add the
`is_paper=false` live-only filter (smoke-run used 99 mixed rows) + confirm
`ev_predicted` is RAW not calibrated.

## 2026-07-09 EOD (latest) — COMPARATIVE-RECON INTEGRATION (v1.2) + v5.5 CANONICAL

STEP-0: broker 19:35 ET (closed) / DB 23:35Z — agreed. Doc/prompt writes only,
runtime-inert (prompt files read by `run-nightly.cmd` + humans, not services).

**A1 VERIFICATIONS (the recon's two falsifiable code claims + two gated grades):**
- **A1a field contract → CONFIRMED.** `walkforward_validate_learning_v3.py`
  reads `learning_trade_outcomes_v3` expecting `ev`/`expected_value` +
  `realized_pnl`/`pnl`; the table exposes `ev_predicted`/`pnl_realized`
  (+`pnl_predicted`/`pop_predicted`) → `KeyError` at `df['ev'].fillna` (`:101`).
  Script cannot honestly validate the view → field-contract fix folded into the
  calibration-ordering item.
- **A1b F-A2-1 vs recon #4 → MERGE.** F-A2-1's charter had the invariant but no
  explicit reconciling state; the recon supplies `UNKNOWN_RECONCILING` + typed
  transitions + targeted client_order_id lookup + fill+closure invariant
  (Nautilus/Hummingbot cites). Merged into P0-A (what it lacked: the state
  machine + the targeted lookup).
- **A1c(i) replay substrate → CONFIRMED ~55%, but WORSE than graded.**
  `from_decision_id` = ZERO production callers (docstrings + 1 test); capture
  tables `decision_runs`/`decision_inputs`/`decision_features` EXIST **but hold 0
  ROWS** — schema-only, nothing writes them. The replay item's prereq (capture
  rows) is UNMET → its drop-condition fired → item rescoped to include a
  capture-WRITE path first.
- **A1c(ii) earnings gate → CONFIRMED.** `options_scanner.py:3866-3879` gates on
  `days_to_earnings<=2` (hard) / `<=7` (penalty) only — NO event-before-expiry
  check. Grade holds.

**RECON SCORECARD:** claims spot-checked where falsifiable were evidence-verified
(A1a field mismatch, A1c earnings gate, replay caller/schema); coverage grades
materially correct (replay ~55% — adjusted down for the 0-row capture);
falsifiers carried verbatim into the items as retirement conditions (the GOLD
prequential falsifier especially). Recon method: sound; one grade optimistic
(assumed capture rows existed).

**CORRECTION to OUR earlier framing (A2.7, move-don't-lose):** the recon
confirmed **21-DTE / 50%-credit / DTE gates already ~85% EXIST in cohort
policy** — the earlier deep-dive's "position-management conventions missing"
impression is WRONG and is corrected here + filed in the DO-NOT-RE-LITIGATE
backlog section. Do not re-derive them as a new build.

**BACKLOG DIFF:** P0-A absorbed recon #4 state machine; calibration-ordering item
absorbed recon #2 (prequential + A1a field-contract fix + GOLD falsifier); NEW P1
deterministic replay (+ 0-row capture prereq); NEW P2 versioned earnings cohort
(fix gate to event-before-expiry, observe-first); NEW P2 per-leg entry quote
envelope; DO-NOT-RE-LITIGATE standing section seeded.

**v5.5 CANONICAL ON DISK:** `audit/v5-prompt.md` upgraded to v5.5 ELEVEN AREAS
(A1-A9 + A10 rotating Calendar&Clock + A11 permanent Self-Extension) at this SHA;
STATE refreshed to tonight; external prompt STATE re-stamped. **Prompt-drift class
CLOSED: the invoked file (`run-nightly.cmd:8` → `audit/v5-prompt.md`) IS the
version of record; session-prompt changes MUST land here same-day.** Tonight's
midnight run is the first eleven-area (v5.5) nightly.

## 2026-07-09 EOD (late) — EXTERNAL AUDIT v1.1 ADJUDICATION (P0/P1 verified vs code+DB+broker)

STEP-0: broker 19:15 ET (closed) / DB 23:15Z — agreed. READ-ONLY + the one
pre-authorized security commit. Book FLAT now (0 open, 0 live-routed).

**P0-1 CREDENTIAL (F-FREE-1) → LOCAL-ONLY-FAKE (NOT a live compromise).**
`.env.example` (git-tracked since the 2025-11-19 initial commit `82e8ef8`)
carried real-shaped Supabase anon + `service_role` + S3 keys. Fingerprint:
URL is `http://127.0.0.1:54321`, keys are modern `sb_publishable_`/`sb_secret_`
format; production `etdlladeorfgdmsopzmz` exposes a legacy JWT anon key at its
cloud URL — different host/format/value. **No production credential exposed →
no live rotation warranted.** Pre-authorized scrub SHIPPED as placeholders
(PR #1145, `95d3bb5`, NOT merged — left for operator). OPERATOR ITEMS (not
done): git-history cleanup (BFG/filter-repo of the pre-scrub blob) + GitHub
secret-scanning/push-protection enablement. Even LOCAL keys public 8 months
= rotate the local stack at leisure.

**P0-2 LIVE-CLOSE CUSTODY (F-A2-1) → LATENT (chain real, NEVER fired).**
All four sub-claims CONFIRMED at the deployed SHA (d45ad63):
(i) `paper_exit_evaluator.py:1700` `position_is_alpaca=False` default +
`:1712-1727` routing-query failure only WARNs (`paper_exit_routing_query_failed`,
no raise); (ii) `:2162` `submit_and_track` result discarded, `:2172-2177`
returns `routed_to='alpaca'` unconditionally; (iii) `:2178-2207` a RAISED
submit exception (from `get_alpaca_client`/order fetch/imports/the pre-cancel
`cancel_open_orders_for_symbols` at `alpaca_order_handler.py:245`, OUTSIDE the
retry-try) falls through to an INTERNAL FILL — `:2272-2280` writes
`status='filled'` on a LIVE position with no broker ack (fires
`paper_exit_alpaca_submit_fallback_to_internal` critical first); (iv)
`intraday_risk_monitor.py:1428-1434` treats ONLY `deferred_uncorroborated` as
not-closed, so the internal-fill return (no `routed_to`) logs as a SUCCESSFUL
`force_close`. **RUNTIME: never fired on a live position.** All 9 post-epoch
live closes are `close_reason='alpaca_fill_reconciler_standard'` (broker-
reconciled); 42 filled close orders carry a broker id; the 10
`submission_failed`+filled internal-fill rows are all PRE-LIVE alpaca-paper era
(latest 2026-04-06); ZERO `submit_fallback_to_internal` alerts ever (the 3
`paper_order_marked_needs_manual_review`, latest 06-12, are the ordinary
broker-reject path that leaves the position OPEN, not internal-filled).
**→ E6 exclusion-integrity FAIL:** the live-close-custody closure claim fails
as written — the fallthrough hole is real and unclosed, merely un-triggered.
**→ NEW #1 BUILD: the broker-acknowledged-close invariant** (a live close may
NOT record `status='filled'` without a broker ack; raise→retry/needs-manual-
review, never internal-fill). Supersedes strategy work + Phase-3.

**P0-3 RISK CUSTODY (F-A1-1/A1-2) → CONFIRMED book-blind + PREMISE CORRECTED.**
(a) `paper_positions` has NO `cost_basis`/`current_value`/`max_loss`/
`collateral` columns at all → the allocator (`portfolio_allocator.py:116-144`
`_sum_open_cost_basis`) and RBE (`risk_budget_engine.py:99-208`
`_estimate_risk_usage_usd`) read those keys and get None→0, so the OPEN book
contributes ~$0 to utilization/envelope; writer omits them too (both true).
(b) Utilization gate (`utilization_gate.py:323-341`): candidate cost =
`limit_price*contracts*100` = ~$149 for a 1.49-credit IC, NOT the ~$351 max
loss — AND asymmetric with the already-open side (`structure_commitment_usd`
uses `width*100`=margin). **PREMISE CORRECTION (four-source: packet/registry
said "book ≤1 always"; DB says peak 3):** 3 concurrent real-money live
positions ran **2026-06-11 16:20Z → 06-12** (NFLX+QQQ+SPY; again 06-12
18:30-18:45 NFLX+QQQ+MARA). So the book-blind sizing + credit-basis gate + the
one-beta exposure were ALL live-reached, BEFORE the #1139 tripwire shipped
(07-08). Grade: latent-critical **that has already occurred** (no realized harm
— positions were small — but the aggregate cap was un-enforced across that
window). Merges with B1/B2 into ONE "book-scaling readiness" epic.

**P1 VERDICTS:**
- **(d) F-A1-3 calibration ORDERING → CONFIRMED.** `apply_calibration` at
  `workflow_orchestrator.py:3562-3569`, AFTER select(`:2495`)/allocate(`:2634`)/
  size(`:3241`); score/selection/sizing consume RAW ev; only persisted `ev`
  (`:3609`) + post-selection `risk_adjusted_ev` recompute (`:3669-3674`) reflect
  the multiplier. Morning path stamps `risk_adjusted_ev`/`status` on RAW then
  overwrites `ev` (`:1753-1755`) — raw/calibrated divergence on one row.
  **RE-SCOPES tomorrow's 16:00Z proof** (below). NEW P1 (design, not one-liner).
- **(e) F-A3-1 PoP → CONFIRMED-but-LATENT (our adjudication upheld).** The
  inverted `credit/width` branch (`ev_calculator.py:34-42`) accepts ONLY 2-leg
  credit verticals (`credit_spread` et al.); IRON_CONDOR (condor precomp +
  delta-tail) and debit spreads (delta interp) never enter. DB: strategies ever
  stored = IRON_CONDOR/LONG_CALL_DEBIT/LONG_PUT_DEBIT/take_profit_limit — ZERO
  credit verticals ever → branch never reached. (FREE-LOOK: stored PoP > 1.0 on
  debit-spread + take_profit_limit rows (max 1.0704) — impossible probability,
  delta-PoP overshoot; additive one-liner filed.)
- **(f) F-A4-1/A4-2 → both CONFIRMED.** `iv_daily_refresh` returns
  `status:ok` on all-missing (accounting `0==0`); it is ABSENT from
  `EXPECTED_JOBS`, and the watched `learning_ingest` is an explicit NO-OP STUB
  while the real producer `paper_learning_ingest` is unwatched. Observability
  → the carried 3-in-1 PR (recommend SPLIT into a 2nd observability PR, below).
- **(g) F-A9-1 → CONFIRMED.** `signal_accuracy_rolling` win = `pnl_realized>0`
  (realized win-rate), not thesis accuracy. Relabel → `realized_trade_win_rate`
  rides the thesis-tracker build; B1 ≈78% thesis vs this view's 12.5% is the
  exhibit.
- **(h) F-A8-1 → CONFIRMED.** Rejection over-count: inner `process_symbol`
  reason + outer wrapper `no_fallback_strategies_available`/
  `all_strategies_rejected` both `record()` (`options_scanner.py:4106/4141`),
  so `total_rejections` > distinct rejections. Annotate the packet's ~916.
  (Lane A greedy replay used `trade_suggestions`, NOT the 916 figure — Lane A
  unaffected; future rejection-based analysis must dedupe.)
- **(i) F-A2-2 → CONFIRMED (nuance).** `quote_complete=False` requires BOTH
  sides of EVERY leg (`exit_mark_corroboration.py:172-178`); when a non-
  executable side is missing it discards a COMPUTED executable-side divergence
  and force-suppresses — but ONLY for TARGET_PROFIT (`:246-253`); stop_loss is
  NEVER suppressed (`:243-245`). So it's a named mechanism for MISSED profit-
  takes (→ held longer → more stop exposure), NOT direct stop over-pessimism.
  Feeds Phase-3 instrumentation as a specific thing to measure.
- **(j) A10 import-time flags → CONFIRMED, no NEW class.** Module-scope env
  reads: `MIDDAY_TEST_MODE`/`COMPOUNDING_MODE` (`workflow_orchestrator.py:179-180`),
  `CALIBRATION_ENABLED` (`calibration_service.py:34`) — added to the inventory.

**RE-SCOPED "tomorrow 16:00Z proof" language (per d):** a persisted scan row
with `ev == ev_raw × 0.5` proves E1's flag — the multiplier reaches the
PERSISTED ev and therefore the final-stage round-trip gate. It does NOT prove
the calibrated value influenced SCORE, SELECTION, or SIZING — those consume raw
ev by construction (apply runs post-sizing). State it exactly: raw = score /
selection / sizing; calibrated = final-stage gate reading persisted ev +
persisted `risk_adjusted_ev`.

**EXTERNAL v1.1 SCORECARD (exclusion-integrity E1-E9 as graded):** E6 FAIL
(headline — custody closure claim false-as-written); the rest of their P0/P1
CONFIRMED at the line (their runtime-flag/mapping method vindicated again, Q1-
class). Weight: high. 11 packet/prompt disagreements → annotate move-don't-
erase (the ≤1-position premise correction is the load-bearing one).

## 2026-07-09 EOD — BUILD #1143 SHIPPED (shadow-detection + calibration fail-loud) + ⭐ OPTION-B CLOCK-RESET MARKER

**#1143 `655c9aa` — MERGED + H8 VERIFIED.** Post-close (merge 22:54:19Z;
STEP-0 grounded: broker 18:45 ET market-closed, DB 22:45Z). Two fail-safe
fixes:
- **Shadow-detection value match (E2 residue):** `_is_shadow_routing()`
  (`paper_endpoints.py`) now whitelists the REAL production value
  `shadow_only`. The prior check matched `paper_shadow`, which production never
  emits → the #1141 Option-A shadow branch was INERT (all cohorts fell to the
  observe-only legacy-sized basis, `basis=legacy_sized`). Unknown/None routing
  → False → observe-only (fail-safe: an unknown value never flips a live
  decision). Live path still behind `GATE_QTY_FIX_LIVE_ENABLED` default-OFF.
- **Calibration fail-loud:** once-per-scan WARNING at the midday apply site
  (`workflow_orchestrator.py`) + a write-side WARNING when a blob is stored
  while apply is disabled (`calibration_update.py`) + an import-time-flag
  caveat comment (`calibration_service.py`). Logs only; the flag itself was
  re-enabled by env flip earlier this session (a Railway flip needs a recycle
  — exactly what the import-time comment documents).
- **H8:** BE `d1fe9f87` / worker `74f3c83d` / worker-background `dad9b9e0` —
  all SUCCESS at `655c9aa`, created 22:54:22–23Z > merge 22:54:19Z; prior
  `907d4cd` deploys REMOVED. No new flags → no read-back beyond confirming
  `GATE_QTY_FIX_LIVE_ENABLED` OFF + `CALIBRATION_ENABLED=1` (both unchanged).
- **Tests:** `test_shadow_routing_fix.py` (13) pin `_is_shadow_routing` on the
  exact production strings + the routing→gate-decision chain (shadow PASS /
  live REJECT+observe / unknown observe-only / qty=1 invariant) + the two
  fail-loud source sites. CI green (run 29055518433, 1m42s).

**⭐ OPTION-B CLOCK-RESET MARKER — STAMPED AT `655c9aa` (recycle 22:54:22–23Z).**
Both preconditions are now met ON THE RUNNING PROCESS: (1) calibration APPLYING
(`CALIBRATION_ENABLED=1`, re-enabled this session) and (2) shadow-detection
CORRECT (`shadow_only` matched). **The Option-B (live gate-qty apply) observe
window's evidence clock RESETS here: the 9 `[GATE_QTY_SCALED_SHADOW]` observe
lines logged before this recycle are DISCARDED** — they were counted on the
inert-shadow + inert-calibration basis and are not clean. **Clean observe
evidence counts only from the first scan after this recycle (07-10 16:00Z scan
onward).** `GATE_QTY_FIX_LIVE_ENABLED` stays OFF — Option B remains an operator
decision, now to be made on clean data.

**B4 — EXTERNAL-REVIEWER SCORECARD (so future sessions weight their input
correctly):** external Q1 (calibration computes/stores but returns ×1.0 =
a runtime-flag/mapping issue) **CONFIRMED-RIGHT-FOR-THE-RIGHT-REASON** by
internal recon — root cause was `CALIBRATION_ENABLED='0'`, stale since the
06-11 epoch, never restored. Their A7 ("stops saved money") **REFUTED on broker
truth** — the stops mostly force-closed thesis-favorable positions early (B1's
downstream finding); an honest data limitation on their side (no broker
access), not a reasoning error. Net: a **calibration-proven** external — high
weight on their future findings.

## 2026-07-09 EOD — EXTERNAL-REVIEW ADJUDICATION (read-only; verdicts + B1 headline + A6 corrections)

**B1 — THE HEADLINE (the number the external couldn't compute): thesis
hit-rate ≈ 7/9 (~78%) vs P&L hit-rate 1/9 (~11%). THE PROBLEM IS
DOWNSTREAM (execution/exits/costs), NOT the signal.** Scored each live
close's entry thesis against the underlying's path to its INTENDED horizon
(strikes + exp vs 07-09 prices): NFLX(down, hit), NFLX(down, hit, +48),
QQQ-IC 06-15 (QQQ 723 inside 645-750 → hit but force-closed −73), SPY-IC
(751 inside 681-765, on-track, −45), SOFI(18.6>17, on-track, −40),
QQQ-IC 07-07 (inside, −15), QQQ-IC 07-08 (inside, −10) = 7 thesis-
favorable; MARA×2 (13.2<13.5/14, didn't rise) = 2 miss. **6 of 9 were
thesis-RIGHT-but-lost-money** — the underlying was in/toward the profit
zone but the position was force-closed early at a loss (the premature-stop
/ Phase-3 over-pessimism pattern, now quantified). CAVEAT: 5 of 9 expiries
are FUTURE (07-24→08-21) → "on-track" not "hit"; labeled in-progress.
**INSTRUMENTATION GAP FILED: no shadow-to-expiry tracker — positions
force-closed in minutes leave nothing following the underlying to the
original expiry, so thesis quality is only spot-scoreable. This is the #1
missing measurement.**

**A6 — LEDGER CORRECTIONS (broker=truth; the realized P&L was always
RIGHT, the EXIT-PRICE DISPLAY used the MARK not the FILL — mid-vs-fill
confusion, recurring class):**
- QQQ 07-07: exit shown 1.74 (mark) → **broker FILL 1.64**; realized −$15 ✓.
- SOFI 06-30: exit shown 1.53 (mark) → **broker FILL 1.36**; entry 1.44 →
  1.36 = −0.08 ×5×100 = **−$40 ✓ (reconciles the "impossible" row)**.
- QQQ 07-08: exit shown 1.535 (mark) → **broker FILL 1.59**; credit 1.49 −
  1.59 = −0.10 ×1×100 = **−$10 ✓ (the "−5" was the mark)**.
  → The external packet §2a exit-price column reads MARKS; correct to these
  fills on its next revision (packet is committed #1142 — annotate there,
  not erase). P&L rows unchanged.

**A1-A7 VERDICTS (cites in the session):** A1 credit-spread PoP=credit/width
= max_gain/(max_gain+max_loss) (ev_calculator.py:42) — **CONFIRMED inverted
(≈P(loss)); but LATENT** — IRON_CONDOR + debit strategies (the whole live
book) are NOT in that branch's strategy_type list; blocks the 2-leg-vertical
cohort. A2 stop = pct × max_CREDIT (policy_lab/config.py:33), cohorts
0.40/0.50/0.65 — **CONFIRMED credit-relative** (~17% of max loss at 0.40),
naming-clear in config but the basis is credit not max-loss. A3 ranker fee
= fee×contracts×2, NO ×leg-count (canonical_ranker.py:69) + slippage =
5%-of-EV proxy (:145) vs the gate's executable cross — **CONFIRMED
multi-basis; ranker under-costs 4-leg → ordering distortion (small $, but
real)**. A4 score clamped min(100) (guardrails.py:138) — **saturation
CONFIRMED**; but compute_conviction_score DOES use iv_rank conditionally
(:118-123) → "IV not in score" **PARTIAL** (the roi×500 production score not
located). A5 compounder legacy path ~3%×score (~$60) with a self-alert of
"~6-8× smaller budget" — **CONFIRMED sizing-model gap** (production uses the
allocator ≈ max_loss; the legacy fit-test tests a fiction). A6 above. A7
the stops fired on OVER-pessimistic corroborated UPL and the positions were
in-profit-zone at horizon → **"stops saved money" REFUTED** — they mostly
stopped WINNING theses early (= B1's downstream finding + Phase-3).
**External Q1 (runtime flag) CONFIRMED — weight their findings accordingly.**

## 2026-07-09 ~21:29Z — CALIBRATION RE-ENABLED (env flip + recycle, supervised)

**ROOT CAUSE (recon-proven by execution): `CALIBRATION_ENABLED='0'` stale
kill-switch, off since the 06-11 epoch, never restored.** Calibration was
LIVE 04-13→06-10 (38 rows, ev≠ev_raw), then disabled at the epoch to stop
pre-epoch sign-flipped multipliers applying to post-epoch predictions —
correct then, but the master apply switch was never flipped back when the
pool matured (07-09). The apply sites (`workflow_orchestrator.py:3554`
midday scan / `:1740` morning) are gated on the module-level flag; both
skipped. `get_calibration_adjustments` returned the correct 0.5 blob and
`apply_calibration(real blob)` → 19.85 in positive control — **the code was
never broken; the flag was off.** **NEW CLASS LINE: disabled-and-never-
restored** — a deliberate temporary disable with NO re-enable trigger; kin
to dead-triggers (§backlog) and prescribed-not-applied (WakeToRun). The
disable was FAIL-QUIET (no per-scan log; the write job kept computing +
storing a blob nothing read).

**SEQUENCE (all gates cleared before the flip):**
- STEP 1 — 21:20Z SUPPRESSION TEST **PASSED** (edge-trigger case 3, first
  live proof): `suppressed_standing_window:true`, tripped:false,
  paused_written:false, reason "standing_window_already_reviewed —
  fingerprint matches the last trip"; window unchanged, entries stay
  unpaused, 0 trips. #1135 fully validated.
- STEP 2 — pre-flight cleared: the only `MIN_POP=0.60` gate
  (`guardrails.SmallAccountCompounder.apply`) is **DORMANT** (not called by
  the scan; field-name `prob_profit` vs prod `probability_of_profit`;
  superseded by `services/analytics/small_account_compounder.py`) → a halved
  PoP breaks nothing live. Epoch off-reason moot (blob is post-epoch by
  construction).
- STEP 3 — **`CALIBRATION_ENABLED` set 0→1 on worker + worker-background**
  (BE is not an apply site). Recycle → both SUCCESS at `907d4cdd` (= the
  running `03e11d8` apply code + #1142 docs packet the operator merged;
  **zero code change**, H8-verified by diff). **Read-back: env=1, module
  CALIBRATION_ENABLED=True on the worker.**
- STEP 4 — **PRODUCTION PROOF: PARTIAL tonight, FULL pending 16:00Z
  tomorrow.** The forced post-close scan (job cb2db12c) short-circuited on
  the market-data **staleness gate** (age 94.8min, fast_path, processed 0)
  BEFORE scoring — so no scanned ev and no apply-site log tonight. Confirmed
  tonight: flag flipped + module True + `apply_calibration(blob)`→0.5
  (function). **NOT YET CONFIRMED (the built-not-wired class is NOT fully
  closed until this lands): a real scanned `ev == ev_raw × 0.5`** — rides
  tomorrow's 16:00Z scheduled scan on fresh quotes. Verify then.

**⚠ TRUE BOUNDARY MARKER (supersedes the annotated-false 07-09 10:00Z
marker): the apply path is ENABLED from 2026-07-09 ~21:29Z (907d4cdd,
CALIBRATION_ENABLED=1), but NO production ev has been calibrated yet
(tonight's scan was staleness-gated). The FIRST calibrated production ev is
2026-07-10 16:00Z. Every EV ever stamped before that moment was RAW except
the 38 pre-epoch rows (04-13→06-10).** Direction: TIGHTENING (EV×0.5 →
gate rejects more) — doctrine-clean, not a loosening.

**Option-B observe window: reset condition HALF-MET** (calibration now
enabled); fully resets when the shadow-detection one-liner ships. 07-09's 9
observe lines stay discarded (computed on un-halved EV).

**FILED (small PR, tomorrow / with the shadow one-liner): fail-loud
hardening** — log once-per-scan when `CALIBRATION_ENABLED` gates apply off +
flag the compute-but-never-apply waste; optionally move the flag read from
import-time to call-time (so it takes effect without a recycle). A
month-long silent recurrence must be impossible.

**PENDING-VERIFY (tomorrow morning): (1) 16:00Z scan produces ev=ev_raw×0.5
on a real suggestion [closes the class]; (2) the PoP ×0.5 lands only on
display (no live consumer) — confirm no regression; (3) the 21:45Z/22:00Z
learning chain ran clean post-recycle.**

## 2026-07-09 EOD — FIRST-CALIBRATED-SCAN-DAY FINDINGS (doc-only; fix-queue for tomorrow)

Flat day (0 trades, equity $2,067.86, −$0 P&L). First full day on the
supposed ×0.5 calibration + the gate-fix observe-log armed. Two findings,
both Claude Code's own, both fail-safe, both self-caught same day.

- **FINDING #1 (HIGH, headline) — CALIBRATION COMPUTED-NOT-APPLIED**: the
  0.5 multiplier stores at 10:00Z but `apply_calibration` returns ×1.0 at
  the scan — champion first calibrated scan verbatim `ev==ev_raw==39.71`
  (halved would be 19.86). Insert path stamps ev_raw then overwrites
  ev=apply_calibration(...) (workflow_orchestrator.py:1745-1755); equal
  values ⇒ ×1.0 returned. Suspect: `get_calibration_adjustments` fails to
  map an `_overall`-only blob into the `{strategy:{regime}}` return shape,
  so the documented `_overall` fallback (calibration_service.py:577) never
  fires and application silently falls to ×1.0. **CLASS: built-not-wired
  (#1126 family — computes/stores but doesn't reach the decision path).**
  RECON-THEN-FIX, own session, FIRST work tomorrow. Cross-ref: flagged to
  the external reviewer as §1 question (1) — do not double-drive; whoever
  moves first claims it.
- **FINDING #2 (one-liner + test) — OPTION-A SHADOW-DETECTION MISS**:
  #1141's gate keyed `routing_mode == "paper_shadow"`, but production
  values are aggressive=`live_eligible`, neutral/conservative=`shadow_only`
  → matched nothing → ALL cohorts ran `basis=legacy_sized` (observe-only),
  the shadow-side fix INERT, observe-log mislabeled shadows as `cohort=live`.
  FAIL-SAFE (zero live change; the miss defaults to the protected path) but
  promotion-un-biasing didn't happen. FIX: match `shadow_only` (or
  `!= live_eligible`) + pin the test on PRODUCTION routing values (the bug
  was test-fixture `paper_shadow` vs reality `shadow_only` — a test-vs-truth
  value mismatch, adjacent to the 9a2cef1 class). Ships after/with #1.
- **OPTION-B OBSERVE-WINDOW — EVIDENCE INVALIDATED, CLOCK RESET**: 07-09's 9
  `[GATE_QTY_SCALED_SHADOW]` lines are CONTAMINATED — the "would-open"
  new_net was computed on the UN-halved EV (39.71); with the real ×0.5
  (finding #1) new_net ≈ 19.86 − 12 = +7.86 < $15 → would NOT open. And the
  qty7/qty15 lines are shadows mislabeled live (finding #2). **The ~1–2wk
  Option-B observation clock counts ONLY from the SHA where BOTH #1 (calib
  applies) AND #2 (shadow-detection correct) are live. Discard 07-09's 9
  lines.** Re-arm marker to be stamped at that SHA.
- **ERRATA (annotation #6)**: this morning's ritual assertion "every EV
  number is now calibrated ×0.5" was a **verify-before-asserting miss** —
  overturned same day by ev==ev_raw. Pattern line: **TWO Claude-Code errata
  today (this + the recon's "champion always qty-1" caught by the SOFI qty-5
  fixture), both fail-safe, both self-caught within the day.** The standing
  boundary marker (07-08 postclose entry) is annotated in place, not erased.
- **NOISE-CLASS PRESSURE (reinforces the TOP-3 3-in-1)**: the observability
  PR was FIX-TODAY in the morning triage and DID NOT ship (the gate-fix took
  the slot). Carried to tomorrow's 2nd build slot. Today's reinforcement:
  ops_output_stale +7, job_succeeded_with_errors +5, **signal_accuracy_
  degraded ×14 (observe-only warning firing ~2/hr on the losing pool — a NEW
  cry-wolf; ADD a once-per-day / condition-dedup sub-item to the 3-in-1).**

**TOMORROW'S BUILD ORDER (operator's word, post-close, sequential deltas):
① calibration recon-then-fix (#1) · ② shadow one-liner + prod-value test
(#2) · ③ 3-in-1 observability PR (flat-book stale + re-egress dedup + #1104
writer-hardening + accuracy-warn dedup) · ④ stamp the Option-B clock-reset
marker at the #1+#2 SHA.**

## 2026-07-09 MORNING TRIAGE — dispositions recorded (doc-only)

First v5.4-from-disk nightly ran + dead-man pinged GREEN (first live night).
Calibration PRINTED 10:00:03Z: `_overall ev_multiplier 0.5 / pop_multiplier
0.5` (BOTH clamp-floored; ev_calibration_error 65.34 — raw wanted lower;
single _overall bucket, 30d window at n=8) — **raw mode EXITED; EV/PoP now
calibrated ×0.5, the ledgered boundary is CROSSED.** Un-paused + acked the
21:20Z breaker trip + 3 accuracy warnings; fingerprint survived (holds the
QQQ−10 window bd895160 — tonight's suppression test armed).

Dispositions:
- **FILED-TRIGGERED**: #1104 writer-hardening (6/677 rows lost 07-08;
  bundle w/ today's 3-in-1 or next burst) → backlog P2 · reentry_cooldowns
  realized_loss=estimate → FOLDED into the 06-15 backlog item (2-for-2
  live, no new line).
- **ACK-NO-ACTION** (recorded so no re-raise): A6 executor 4×/day = operator
  manual mid-session/post-close cycles, NOT a scheduler defect (scheduled
  cadence is the one-shot) · phase2_precheck = paper-shadow phase-2 gate,
  operator to name it in the scheduler doc.
- **GATED-REOPEN counter: Phase-3 exit over-pessimism now 3rd instance,
  15.5× worst yet** (cohort stop −155 vs broker −10, 07-08). Counter
  **3/[10-15 reopen gate]**. ⚠ **PATTERN NOTE for the reopen session: three
  instances (QQQ 3.3× · SOFI 1.6× · QQQ 15.5×) — the reopen's HEADLINE
  question is "is the cohort stop systematically over-pessimistic on
  defined-risk structures?" (same question SOFI stop-tightness raised).**
  Do NOT act now — gated, outcome-bias-protected; recorded so the reopen
  opens on the pattern.
- **⚠ META-AUDIT DRIFT CAUGHT LIVE (the exact class the 07-08 meta-audit
  targeted): 4 items were ledger-only / prompt-KNOWN-PENDING and had FALLEN
  OFF the actionable backlog.md** — EV-basis recon (LIVE), B1/B2 bucket
  control (LIVE), compounder greedy-stop (LIVE), the #12 06-10-runner batch;
  gap-3(b) existed only as a sub-note. **All re-added to backlog.md this
  session** (P1 for the two live-money, P2 for the rest). Process note: the
  ledger narrative is NOT the actionable list — filed items must land in
  backlog.md or they silently vanish from build-planning.
- **FIX-TODAY queue (pending-today, NOT built)**: the 3-in-1 observability
  PR — flat-book guard on ops_output_stale (A9) + re-egress cross-owner
  dedup (A5) + #1104 writer-hardening (A4). Post-close, one recycle. All
  three health-check/observability-side; zero decision-path risk.
- CONFIRM list checked: F-A1a · reaper · winter-close 2026-10-01 present ✓;
  one-beta tripwire SHIPPED #1139 ✓ (B1/B2 the only open bucket item);
  gap-3(a) SHIPPED #1124 present ✓.

## 2026-07-08 PR-B #1139 ONE-BETA TRIPWIRE — status:SHIPPED

**H8 VERIFIED: squash `7db5a36` (7db5a36dcd4fc1bf58eb67878e387ce2f3c3a2bd)
= origin/main; all three services SUCCESS at that SHA (22:29:35Z);
new-container work flowing by 22:30:04Z (heartbeat OK on the recycled
worker).** PR-A #1138 (`e26bcfe`) merged immediately before — tonight's
midnight nightly runs the v5.4 charter from disk for the first time.

Tripwire live: `concurrent_live_positions_uncontrolled` critical at ≥2 open
LIVE-routed positions, q15 monitor, immediate-egress + receipt.
**VERSION SHIPPED: simplest-correct (ANY 2 live positions), per owner
rationale — bucket refinement stays B1/B2's (still FILED; the alarm is not
the control).** Semantics: alarm-on-onset (position-set dedup; a 3rd
position re-alarms; dedup-read failure alarms anyway; scope-failed cycle
skips). Flag CONCURRENT_POSITION_ALARM_ENABLED default-ON. Disaster-pinned:
never mutates positions/orders/ops_control (test). 12 tests incl. the
production-call-path wiring pin. OPERATOR REMAINING: create the
healthchecks check + set machine env NIGHTLY_AUDIT_PING_URL (PR-A's ping
gate is a logged no-op until then).

## 2026-07-08 META-AUDIT (chat-run, gap register) + TIER-1 PROCESS FIXES — status:SHIPPED (PR-A)

**Meta-audit verdict (full register in session 07-08 ~22:15Z): ship-side
TRUSTWORTHY (ledger↔git 1:1 over 22 commits; 4 spot-checked fixes verified
against RUNNING behavior; zero built-not-wired in the shipped set); intake
side LEAKY (9 goes-silent findings, concentrated pre-ledger 06-10 runners;
2 re-verified STILL REAL); charter side STALE (disk prompt was v5.0/06-12;
scheduled cadence 6 reports/27 nights; 3 silent-empty runs 06-13/14/20).**

PR-A ships: **v5.4 TO DISK** (audit/v5-prompt.md — gap #7; adds A1(iv)
sizing/allocation custody [gap #10] + expected-state: suppression-is-
designed, headless-broker-blind, breaker ritual) · **ping-after-file-exists**
in run-nightly.cmd (gap #8; NO ping existed at all — first wiring;
PowerShell date because %DATE% is locale-formatted and would never match;
gate dry-run verified both directions; operator: create the healthchecks
check + set machine env NIGHTLY_AUDIT_PING_URL, Grace ~26h) · **sweep
convention** (gap #9, CLAUDE.md §7; 07-08 report swept in this PR) ·
**#1104 CLOSED**: operator confirmed reset ~13:45 CT → 18:45:26Z burst =
C1 rotation artifact CONFIRMED; pool-config reopen stays SHUT.

Meta-audit open register (dispositions pending owner triage): expiry-day ×
unpriceable defer seam (live$, own recon) · compounder greedy-stop BREAK
:286 (live$, Tier-2 fix) · EV-basis ∪ fee-unit recon (merged charter,
pre-market session) · F-A1a mechanical guard · one-beta tripwire (PR-B
TONIGHT) · PoP-denom/DTE segmentation (fold into clamp review) · smaller
silents batch (envelope re-egress 13/3h · A9-F4 · F-A2d · N4 · universe_size
mislabel · time-stop/eod-phantoms · N1/N2 · 06-10 A5/A6 partials) · A6
executor-4× question ANSWERED (operator manual cycles, no scheduler change).

## 2026-07-08 POST-CLOSE — #1137 SIGN FIX + FALSE-AGER — status:SHIPPED · THE TRIPLE-GATE POOL SEALED (8/8)

**H8 VERIFIED: squash `2a83174` (2a83174ed78080e329626297d1c9eaab8d8c6bb1)
= origin/main; all three services SUCCESS; worker-background container
20:51:29Z > merge 20:50:03Z — 29 min settle margin before the 21:20Z
ingest (race deadline CI-green-by-21:05Z beaten at 20:49:38Z).**

- **Sign fix live**: `broker_fill_to_mark_basis` (negation, not abs) at the
  live-fill reconciler; QQQ credit pin 1.4167 + SOFI debit 0.2326 + corrupt
  -15.08-shape regression + call-site wiring all test-pinned. **Both
  poisoned rows RE-DERIVED (supervised, read-back)**: bd25cc9d 15.083→
  **1.4167**, 3139842b 3.076→**0.9635**. The live Phase-3 gap dataset (3
  rows: SOFI 0.23 · QQQ 1.42 · QQQ 0.96) is now honest.
- **False-ager fixed**: monitor Part-B persist stamps `last_marked_at`;
  **9** ops_output_stale highs ACKed cause-fixed (2 more had fired since
  the mid-session count of 7; ids in session log).
- **BREAKER — edge-trigger case 2 FIRST LIVE PROOF (21:20:02Z on
  `2a83174`)**: new loss → new window [QQQ −10 bd895160 · QQQ −15 7dd459f8
  · SOFI −40 055ead84] → `edge_trigger:true, tripped:true, paused_written:
  true, fingerprint_stamped:true` — the NEW fingerprint REPLACED the old
  stamp (read-back ✓; MARA 0c54ead8 aged out). Critical receipt:
  webhook_sent=true 21:20:05Z. **Tomorrow's suppression test compares
  against THIS window** — morning un-pause, then a no-close Thursday must
  yield `suppressed_standing_window:true`, no re-pause, no critical.
- **CLOSE #9 INGESTED**: outcomes_created=1, errors=0; typed
  strategy=IRON_CONDOR / regime=normal ✓; gap datapoint born clean
  (its order row was re-derived pre-ingest). **Post-epoch live pool = 8/8.**
- **⚠ TRIPLE-GATE BOUNDARY MARKER — EV numbers change at 2026-07-09
  10:00Z, not tonight**: the pool sealed at 21:20Z tonight, but the relearn
  executes at the scheduled calibration_update (05:00 CT / 10:00Z). First
  real multipliers print then; consumers from that run onward:
  `apply_calibration` → scanner EV/PoP scoring → `risk_adjusted_ev`
  (executor sort) AND `ticket.expected_value` = the #1101 roundtrip gate's
  gross_ev — every gate decision after 10:00Z is on calibrated numbers.
  **⚠⚠ ANNOTATION 2026-07-09 EOD (do NOT erase this marker — correct it):
  this boundary is FALSE. The multiplier COMPUTED + STORED 0.5 at 10:00Z but
  apply_calibration returns ×1.0 at the scan (ev==ev_raw==39.71 verbatim
  07-09) — see the 07-09 EOD entry, fix-queue #1. "Every EV after 10:00Z is
  calibrated" holds only from the SHA where finding #1 ships; re-mark the
  TRUE boundary there.**
  Training pool: {+48, −45, −28, −73, −15, −40, −15, −10} (1W/7L) — expect
  a SHRINK; whether the 0.5 clamp floor binds is the clamp-review question,
  answerable when the multiplier prints. Winsorize: no extreme outlier in
  the live-only pool (max |x|=73) — likely no-action, owner-gated.
- **Accuracy alert**: expected at the first post-ingest health check
  (21:37Z; n=8, hit 12.5% < 0.2) — observe-only; verify in the morning
  ritual.
- **FILED: 06-08 NFLX pre-epoch live close missing from
  learning_feedback_loops** (broker+champion ledger=9 all-time, outcome
  table=8 post-tonight) — pre-epoch-flagged backfill, rides any future PR;
  no effect on the calibration pool (pre-epoch excluded by design).
- Untouched, confirmed: roundtrip gate (EV-basis recon own session — now
  MORE important: the new multiplier flows into that same comparison) ·
  one-beta B1/B2 · reaper · gap-3(b) · #1104 (pending reset-time).

## 2026-07-07 POST-CLOSE — #1135 EDGE-TRIGGER BREAKER — status:SHIPPED

**H8 VERIFIED: squash `be13733` (be137338ac1e89299cc18034bc04c6201427e47f)
= origin/main; BE + worker + worker-background all SUCCESS at that SHA;
container start 22:18:03Z > merge ~22:16Z.** CI green first try. Migration
`20260707221500` (ops_control.streak_breaker_state jsonb, additive
nullable) applied + tracked PRE-merge, read-back verified.

**Semantics live**: re-trip ONLY on window CHANGE. Fingerprint =
CONTENT-based sorted trailing-N outcome row ids, stamped at TRIP time —
**the operator un-pause SQL is UNCHANGED and is sufficient review** (the
window identity was recorded when it paged them). Suppression needs a
POSITIVE match; no-stamp/NULL/malformed/read-error/stamp-failure all
degrade toward tripping. A NEW loss trips instantly (protection intact —
framed in the PR: not loosening, operator-override-respect added). **Flag
`STREAK_BREAKER_EDGE_TRIGGER_ENABLED` DEFAULT-ON** (explicit falsy →
legacy level-trigger byte-identical); wiring test-pinned in
evaluate_and_trip (no #1126-class inert flag). CLAUDE.md §4 runbook
REPLACED (the nightly-re-trip paragraph is retired).

**Baseline + stamp (tomorrow's before/after)**: tonight's 21:20:02Z trip
ran on `5809505` (level-trigger era, PRE-#1135) — window by ingest order =
QQQ −15 (7dd459f8) / SOFI −40 (055ead84) / MARA −15 (0c54ead8); the trip
critical carries the #1134 receipt: webhook_sent=true, egressed_at
21:20:06Z, owner=alert — **#1134's receipt FIRST LIVE EXERCISE, PASS**.
One-time operator-approved stamp EXECUTED post-H8 (tonight's window
fingerprint backfilled via the breaker's own ordering; read-back
confirmed) because the trip predated the stamping code.
entries_paused=TRUE now (tonight's trip — morning un-pause ritual
unchanged).

**TOMORROW'S PIN (first suppression test)**: morning un-pause → 21:20Z
ingest on an UNCHANGED window → expect `suppressed_standing_window: true`
in job_runs.result.streak_breaker, NO re-pause, NO nightly critical,
entries stay armed. A NEW loss instead → trips (also correct). Attribution
clean: #1135 is the only behavioral change in its recycle.

## 2026-07-07 POST-CLOSE — #1134 TAXONOMY + ALERT-INTEGRITY — status:SHIPPED

**H8 VERIFIED (the shipped bar): squash `5809505`
(58095053c10eb76607552355acb1aecc0c2a8a9a) = origin/main; BE + worker +
worker-background all deployment SUCCESS at that SHA; container start
21:10:18Z > merge ~21:08Z; post-recycle job flow confirmed (21:10:01Z
learning_ingest succeeded).** CI green first try (run 28898768862).

**Old→new alert-type map (readers map old→new; historical rows untouched):**
- `force_close` + real submitted close → `force_close` (unchanged, critical,
  immediate egress)
- `force_close` + "Force close FAILED" → **`force_close_failed`** (critical,
  ADDED to immediate-egress allowlist)
- `force_close` + "[WARN-ONLY] … enforcement disabled" →
  **`envelope_violation_warn_only`** (high — was critical; relay path)
- `warn` (envelope block) → **`envelope_violation`** (high; relay)
- `warn` (envelope warn) → **`envelope_violation`** (warning — was the
  out-of-vocab 'medium'; no egress, anti-spam unchanged)
- Writer unification: monitor `_log_alert` now delegates to canonical
  `alert()` (severity normalize medium/warn→warning, error→high; #1100
  retry; owner stamp; receipt) — the which-writer-wrote-it egress lottery
  (today's real force_close on the ≤37-min relay) is closed.

**A9 receipt live**: `metadata.egress_receipt` {webhook_sent, sent,
suppressed_reason, receipted_at} + `egressed_at` stamped post-send;
`[ALERT_RECEIPT]` WARNING both outcomes; FAIL-OPEN test-pinned. **F8 live**:
suggestions_open rolls `rejection_persist_failures` → top-level
`counts.errors` + ok:false; runner folds alert-write-failure deltas into
every job's `counts.errors` (A4-visible; zero-delta byte-identical).

**F3 PATH TAKEN — UNAMBIGUOUS: F3-MINIMAL SHIPPED / F3-FULL FILED.**
Shipped: transient matcher now catches the 18:45Z specimen (httpx
WriteError / "Connection reset by peer" → retries), and a critical/high
whose insert is STILL lost force-egresses the webhook marked
`[DB-ROW-LOST]` (inbox = durable trace; test-pinned). NOT built: the
all-severities durable buffer — warning-class rows still degrade to
logger.exception only; filed as its own item (the critical-class hard
trigger is satisfied by the fail-safe).

PENDING VERIFICATION (tonight/tomorrow): 21:20Z ingest runs on `5809505` —
today's −$15 QQQ close makes the window MARA −15 / QQQ −73 / QQQ −15 →
expected RE-TRIP = **first live exercise of the new immediate-egress path**:
the `streak_breaker_tripped` critical should carry
`metadata.egress_receipt.webhook_sent=true` + `egressed_at` + an
`[ALERT_RECEIPT]` worker-background log line. Also watch: first
`envelope_violation`-typed rows at the next violation; the designed
channel-2 INFO replacing the legacy-mode WARNING; morning un-pause ritual
unchanged.

HYGIENE (filed 07-06, from the M4 CI failure): `test_weekly_report_win_rate.py`
replaces 18 modules (incl. cash_service, options_scanner) with MagicMocks in
sys.modules at import time and NEVER restores — any later lazy in-test import
binds a mock (green single-file local, red full-suite CI; cost tonight: one
red CI round on #1132). M4's test file now binds real modules at import with a
de-poison guard; the POISONER itself is unfixed and has pre-existing order
sensitivity (6 capital-basis failures in explicit weekly-first order — never
CI's alphabetical order). Follow-up: convert to conftest fixture/unpatch;
grep for siblings doing module-level sys.modules assignment without restore.

## status:reported — 2026-07-08 NIGHTLY run (report `audit/reports/2026-07-08.md`)

Window 07-06 05:01Z → 07-08 05:01Z — the 15-day flat stretch ENDED. Both workers
SUCCESS @ `be137338` (#1135) = origin/main HEAD (H8 clean; start 07-07 22:17:35Z).
**First LIVE fill since 06-30:** QQQ iron condor `386a39fe` (aggressive cohort
`3d289dca`), entry 14:37Z (off-schedule executor run, filled 1.49 credit vs 1.41 limit,
+$8 improvement, 76ms), force-closed 17:45Z on `intraday_stop_loss`, realized −$15.00.
`entries_paused=TRUE` since 07-07 21:20Z (breaker re-trip; **operator un-pause required**).
Live champion now 1 win / 7 post-epoch closes, −$168, hit-rate 14.3% (Brier 0.296).
⚠ **RUN LIMITATION:** alpaca MCP tools absent — broker not snapshot-read; live trade
DB-corroborated (execution_mode=alpaca_live + reconciler + is_paper=false), not
broker-confirmed. Equity/OBP not re-read (last $2,093.74 07-06, −15 QQQ ⇒ ≈$2,078.7 DB-derived).

- **[A4 2026-07-08 — FINDING] `close_fill_gap` sign-convention bug corrupts every
  live-close gap_fraction (poisons the deferred Phase-3 reopen gate).** The #1102
  instrumentation computes `gap_fraction=(fill−cross)/(mid−cross)` with NO sign normalization
  (`services/close_fill_gap.py:62-78`). On the LIVE/reconciler path
  `brokers/alpaca_order_handler.py:571` forces `fill=abs(filled_avg_price)` (+1.64) while
  `cross`/`mid` are stamped SIGNED (`paper_exit_evaluator.py:1913,1976` from `current_mark`
  −1.74 / corroboration −1.98). QQQ 07-07, the FIRST live full-quad close, stored
  fraction **15.0833** (=3.62/0.24) vs the correct-sign **1.417**. Internal/shadow exit
  path passes signed fill → self-consistent; only the LIVE path is wrong. Test fixture
  (`tests/test_close_fill_gap.py:44-47`) uses consistent-positive signs (SOFI→0.2326) → CI
  green while production is corrupt = the #1126/9a2cef1 test-green-production-wrong class
  (§9 never-do). Since #1102 shipped: 0 usable live gap_fractions (QQQ corrupt, SOFI-07-01
  shadow null). FIX: one line — sign-match fill at `:571` (drop `abs()`) or abs cross/mid at
  `:567`; add a mixed-sign fixture. RISK zero (observe-only, best-effort try/except).
  CONFIDENCE high (DB arithmetic + code both dispositive). Blast-radius note: the deferred
  Phase-3 "two-quote confirmation" safety fix (reduces over-pessimistic premature
  force-closes: QQQ −49-est/−15-fill, SOFI −65/−40) is GATED on this now-broken distribution.
- **[A5 2026-07-08 — FINDING] Standing-envelope alerts re-egress to the operator phone
  every 15-min monitor cycle (no content-dedup) — cry-wolf burying criticals.** While one
  live QQQ was held, "QQQ is 100% of risk (limit 40%)" was re-written HIGH and relay-egressed
  every cycle → **13 phone egresses in 3h** (14:45–17:45Z) + 26 non-egressed medium
  expiry/sector; the `force_close` critical egressed 18:07Z, AFTER them.
  `risk/risk_envelope.py:316-354` appends fresh each check; `intraday_risk_monitor.py:449-496`
  no changed-since-last-cycle guard (concentration severity default `"block"`→HIGH); relay
  poller `ops_health_service.py:1431` suppresses only per-row already-egressed stamps
  (`:1479`), NO type+symbol+content fingerprint. **Confirmed persists post-#1134** (rename
  kept concentration→high→relay). FIX (additive): apply #1135's edge-trigger principle to
  egress — suppress re-egress of an unchanged (type,symbol,bucket) standing condition within
  a hold. RISK zero (egress-only). CONFIDENCE high.
- **A1/A3/A7 UNCHANGED** (raw mode holds at 7/8 post-epoch live; ingest clean errors=0;
  QQQ condor hold 3h07m = ledgered cohort-stop-dominates-condors). **A2** — GATED Phase-3
  over-pessimism class exercised a 2nd time (QQQ −49 corroborated est vs −15 fill; cited,
  not re-found); its reopen data is the A4 bug. **A6** — binding constraint = EV-after-cost
  ($15 roundtrip floor rejected aggressive `38d57d55` at net +14.45), not cadence; OPEN Q:
  executor ran 4× on 07-07 (14:37 exec-1, 16:30/17:59/18:47 exec-0) vs one-shot/day — likely
  operator retries around the un-pause, confirm.
- **A8** roundtrip-reject class now exercised LIVE (aggressive +14.45 = edge-lost;
  neutral/conservative = spread-eaten); reject-was-a-win again (QQQ passed→−15). Per-gate
  marker still backlog RESEARCH. **A9** no new integrity finding (all alerts honest; the
  egress noise is honest→A5; ops_data_stale silent — market open). **A10** no new instance;
  winter-close blind hour (Nov) still queued; no fixture inside 45d.

VERIFICATIONS CLOSED THIS RUN:
- ✅ **M4 post-fix healthy scan** (07-07): 0 `micro_tier_underlying_too_high`, 76 syms, 0
  `alpaca_options_buying_power_query_failed`. The 07-06 inverted-universe incident's zero was
  the incident's, not the gates' — M4 (#1132) HELD on the next RTH day.
- ✅ **CVX IV-eligibility**: scanned 07-07, `iv_rank_insufficient_history`=0, rejected on
  real `spread_too_wide_real`. **GLD**: scanned clean (no strike/IV errors). M1/M2/CVX closed.
- ✅ **Breaker re-eval**: 07-06 21:20Z re-tripped; 07-07 21:20Z re-tripped on NEW QQQ−15
  (window rolled QQQ−73→QQQ−15). #1134 streak-breaker critical carried `egressed_at`
  21:20:06Z (receipt partial-confirm).

PENDING VERIFICATIONS (2026-07-08 → next session):
- **⚠ OPERATOR: `entries_paused=TRUE`** (07-07 21:20Z, QQQ−15/SOFI−40/MARA−15). Un-pause
  before the next RTH else the 16:30Z staging proof no-ops.
- **#1135 edge-trigger FIRST SUPPRESSION test — STILL PENDING**: 07-07 21:20Z ran on #1134
  (pre-#1135 deploy 22:17Z) AND a new loss landed (window changed→tripped). The distinctive
  `suppressed_standing_window` path fires 07-08 21:20Z IFF operator un-pauses and no new loss.
- **#1134 first `envelope_violation` typed rows + egress receipt** on the next position-hold.
- **First CORRECTED `[CLOSE_FILL_GAP]`** once the A4 sign fix ships (expect ~1.4, not 15.08).
- **A6 executor-cadence**: confirm whether 4×/day is scheduled or operator-driven.

## status:reported — 2026-07-09 NIGHTLY run (report `audit/reports/2026-07-09.md`)

Window 07-08 05:01Z → 07-09 05:01Z. Clocks grounded (DB 05:01:23Z = broker 01:02 ET ✓).
**Broker READ DIRECTLY this run** (MCP present): equity $2,067.87 = cash = OBP (settled,
flat, 0 positions); 07-08 day −$10.43. H8 CLEAN: all THREE services SUCCESS @ `7db5a36`
(#1139) 22:29:35Z; movers off the prompt pin: `e26bcfe` #1138, `7db5a36` #1139.
**POOL SEALED 8/8** (1W/7L, −$178): live QQQ IC `305e476a` staged 17:41Z (ev 41.75 / pop
0.6425 raw), force-closed 18:00:11Z after ~15min — cohort stop on corroborated −$155 vs
broker fill −$10 (15.5×; Phase-3 class instance #3, counter 3/10-15). Breaker: designed
edge-trigger case-2 trip 21:20Z (window CHANGED: QQQ−10 in / MARA−15 out; fingerprint
stamped; receipt egressed). `entries_paused=TRUE` — **operator un-pause required**.
**CALIBRATION BOUNDARY: first calibrated multipliers print 07-09 10:00Z** (07-08 run was
sample 7 insufficient) — the three 8th-close checks are DUE.

- **[A9 2026-07-09 — FINDING] `ops_output_stale` paper_positions arm = standing HIGH
  false alarm, UNCLEARABLE while the book is flat + paused; the v5.4 STATE "RESOLVED"
  verdict is half-true.** 11 HIGH rows 07-08 (13:07→22:07Z, self-superseding; latest 2
  unresolved, 176→177h and climbing) assert a dead mark-refresh loop while Part-B wrote
  `mark_corroborated −3.04` the same hour. Root: `MAX(last_marked_at)` = 07-01 13:00Z —
  BOTH July QQQ holds ran pre-#1137 code (deploy 20:50Z 07-08 was post-close; QQQ 07-08
  row `last_marked_at=NULL`), and a flat book gives the live fix nothing to stamp. The
  §8 flat-book caveat is DOCUMENTED at `ops_health_service.py:149-152` but UNGUARDED
  (`:527-548` has no open-positions check). Projected ~48 HIGH rows/day for the whole
  pause (0 egressed — ops_* relay-skipped; poisons H11 triage). FIX (additive): flat-book
  guard — `open_n=0` → status `flat`/INFO, never `stale`/HIGH. RISK zero. CONF high.
- **[A5 2026-07-09 — FINDING, broadens the ledgered 07-08 re-egress item] the
  duplicate-egress class includes `egress_owner='alert'` writers, not just the relay.**
  `job_succeeded_with_errors` for the ONE 19:02Z scan run (`run_id ef8a2d4e`) re-wrote +
  re-egressed at 19:07/20:07/21:07/22:07Z — 4 receipted phone hits for one condition.
  The queued dedup fix must fingerprint the CONDITION (run_id / type+symbol+bucket)
  across BOTH owners or it fixes half the class. Watch, same shape:
  `ops_signal_accuracy_degraded` re-writes ~2/hr while hit<0.2 (designed first fire
  07-08 21:37Z at n=8 hit 0.125; warning-only, not egressed — row noise).
- **[A4 2026-07-09 — FINDING, small] rejection-persist retry loses rows when the retry
  hits the same dead connection — first data loss since #1104.** 19:02Z broken-pipe
  burst: 7 inserts recovered, **6 lost for good** (SLV/ISRG/C/HOOD/PLTR/AMGN, broken pipe
  on retry too); `counts.errors=6` with `result.errors=NULL` (count surfaced, items only
  in Railway logs). The #1100 detector caught it and it reached the phone with receipt —
  the chain WORKED; the residual is the writer. FIX (additive): reconnect-then-retry or
  ×2 backoff + stamp failed symbols into `result.errors`. Impact 6/677 (0.9%) of A8's
  counterfactual data. CONF high (logs + counts agree).
- **[A2 2026-07-09 — refinement of the 06-15 deferred cooldown item; metadata-only]**
  `reentry_cooldowns.realized_loss` stores the trigger-time corroborated ESTIMATE, not
  the fill — now 2-for-2 on live closes post-#1080 (−48.99 recorded vs −15 realized
  07-07; −155 vs −10 07-08). Bench durations unaffected; magnitude readers misled.
- **A1** EV-basis recon item (KNOWN-PENDING) reproduced with dispositive numbers on the
  LIVE cohort: aggressive QQQ 16:00Z stamped `net_ev +35.62` but gate-BLOCKED; gate log
  basis `gross_ev 42.14 − round_trip 154.00 = −111.86` (neutral twin; stamped net_ev
  NULL). Two bases disagree on the same candidate; it demonstrably timed the live entry
  (16:00 block → 17:41 pass). Urgency ↑ post-boundary. **A6** unchanged (677 rejections,
  mix stable; iv-seasoning 40/10syms = 06-17 adds, eligible ~mid-Aug; Polygon DARK on 8
  liquid QQQ legs 19:03Z, truth-layer priced — #1052 saved staging). **A8** SOFI sentinel
  quiet; gate discriminated (aggressive edge-passed, shadows spread-eaten). **A10** no
  new instance (counter 2). **A7** dormant, fills 3/10.

VERIFICATIONS CLOSED THIS RUN:
- ✅ **#1134 typed rows + delivery receipt — BOTH egress owners**: 2 `envelope_violation`
  HIGH (17:45/18:00Z) relay-egressed with `egressed_at`; `job_succeeded_with_errors`
  carried full `egress_receipt {sent, receipted_at, webhook_sent}` (alert-owner).
- ✅ **Cooldown bench post-stop**: 19:02Z pending aggressive QQQ NOT staged at the 19:03Z
  executor run (benched until 07-09 13:30Z) — the bench gate exercised, correct.
- ✅ **#1071/#1058 brake line**: `[EQUITY_STATE]` used broker-true −10.43 over the $0
  open-book proxy — tighter value chosen, correct.

PENDING VERIFICATIONS (2026-07-09 → next session):
- **⚠ OPERATOR: `entries_paused=TRUE`** (07-08 21:20Z window QQQ−10/QQQ−15/SOFI−40);
  un-pause is operator-only.
- **CALIBRATION BOUNDARY 07-09 10:00Z**: expect raw-mode EXIT (first real multipliers on
  8 live closes); run the clamp(0.5-floor) + winsorize reviews (owner-gated). Attribute
  any post-10:00Z scoring/gate shift to the multiplier FIRST.
- **#1135 FIRST SUPPRESSION — decisive test 07-09 21:20Z**: book flat + paused + no new
  close ⇒ expect `suppressed_standing_window: true` and NO new critical. A re-pause/
  critical on the UNCHANGED window = edge-trigger FAILURE (flag hard).
- **First NATIVE post-#1137 `[CLOSE_FILL_GAP]` stamp** on the next live close (the 07-08
  quad was corrected in-DB, not code-native).
- **First post-#1137 hold stamps `last_marked_at`** (currently MAX=07-01 13:00Z; the fix
  is live but UNEXERCISED — this is the condition the A9 finding's "RESOLVED" verdict
  hangs on).
- **#1139 one-beta tripwire**: live but unexercisable at ≤1 position; fires only if 2+
  concurrent live positions ever exist (that event ALSO reopens A2's settled condition).
- **A6 executor cadence** (3rd ask): scans 16:00/17:41/19:02Z + execs 16:30/17:43/19:03Z
  on 07-08 — scheduled multi-cycle or operator-driven?
- **phase2_precheck naming**: 4×/day green job outside the doctrine's scheduler map
  (free-look, no anomaly) — one-line operator naming requested.

## status:reported — 2026-07-10 NIGHTLY run (report `audit/reports/2026-07-10.md`; first v5.5 eleven-area nightly)

Window 07-09 05:01Z → 07-10 05:01Z. DB clock grounded 05:01:05Z; **broker-blind run** (Alpaca
MCP absent — equity ≈$2,067.86 DB-derived, hypothesis). ZERO criticals (H11 clean). Zero-trade
day: 3 SOFI forks (ev_raw 39.71) all blocked `ev_below_roundtrip_cost`; book flat; pool stays
8/8 (1W/7L, −$178); gap counter 3/10–15. H8: HEAD moved `655c9aa`→`d275d28` (4 movers named —
#1144/#1145 docs, **#1147 `168a752` code**, `d275d28` doc-wrap runtime-inert, deployed 05:03:37Z
DURING the audit); all 3 services SUCCESS @ `d275d28`; 5 recycles 22:54→05:03Z, 0 orphaned jobs.

- **VERIFICATIONS CLOSED**: ✅ **#1135 FIRST SUPPRESSION DB-PROVEN** — 21:20:03Z ingest result
  verbatim `suppressed_standing_window:true, tripped:false, paused_written:false` on the
  unchanged 07-08 window; `entries_paused=false` (operator un-pause 11:53:33Z); fingerprint
  intact. Edge-trigger case 3 exercised — breaker fully validated, entries ARMED. ·
  ✅ **EDGE-TRIGGER FULLY PROVEN IN PRODUCTION; the morning un-pause ritual is RETIRED**
  (07-10 AM confirmation — all four silence conditions held: no streak_breaker email overnight ·
  `entries_paused=false` · `streak_breaker_state.last_tripped_fingerprint` intact
  [055ead84/7dd459f8/bd895160, tripped_at 07-08 21:20Z] · 21:20Z 07-09 ingest
  `suppressed_standing_window:true`). This was the last morning it needed checking as a ritual
  item; future mornings assume armed unless a flag-condition fires. ·
  ✅ post-recycle learning chain clean (21:00–22:00Z all green, errors=0) · ✅ universe 78 ·
  ✅ A6-cadence + phase2_precheck = ACK'd dispositions observed again, closed. ·
  ⚠ STATE CHANGE: F-FREE-1 scrub MERGED via #1145 `f6b204c` (was "PR pending"); operator items
  (history cleanup + secret-scanning) still open.
- **[A5 2026-07-10 — quantified continuation, urgency ↑, no new class]** ZERO-trade day wrote
  ~53 warning+ alert rows; `job_succeeded_with_errors` re-egressed the SAME stale run
  `ef8a2d4e` 6 more times (13:07→18:07Z) = **10 cumulative phone hits/2 days for one condition**,
  self-terminating only at the detector's ~24h lookback; ops_output_stale ×10 HIGH (unclearable,
  `MAX(last_marked_at)` still 07-01); accuracy ×20; chain_mechanics ×14; autopilot costume ×3
  (`distinct_error_classes=["EntryRoundtripCostExceedsEV"]` — 100% designed NOs as "failed",
  metadata-proven). **The 3-in-1 observability PR slipped a 2nd consecutive build day.** A9
  rider: the alert text "silently masked failure" is self-falsifying by its 10th delivery —
  message-honesty fix rides the dedup PR.
- **[A1/A3 2026-07-10 — structural arithmetic, exhibit for the OWNER-GATED clamp review; no
  action, no loosening]** From 07-10 16:00Z gate-pass requires `ev_raw ≥ 2×(15 + roundtrip)`:
  QQQ-IC class (cost ≈4.8, ev_raw 41.75) passes barely (thr ≈39.6); SOFI class (cost >24.7)
  needs >79. Expected entry volume ≈ zero-to-rare = do-no-harm working, BUT couples: multiplier
  rises only via pool improvement → pool grows only via closes → closes need entries. Not a
  strict deadlock (30d window ages June losses out ~early-Aug; 0.5-floor review is the owner
  lever). Hand to the clamp review as one exhibit with the funnel arithmetic.
- **[A11 2026-07-10 — proposal]** Run-boundary integrity: pin running SHA at audit START and
  END, name mid-run movers as a header field (tonight's `d275d28` landed 2 min into the run;
  caught only by late deployment listing). Also recorded: scheduled session has NO shell
  (subagents included) — git verified via `.git` metadata only.

PENDING VERIFICATIONS (2026-07-10 → next session):
- **FIRST CALIBRATED PRODUCTION EV — 07-10 16:00Z scan**: persisted `ev == ev_raw × 0.5`
  (re-scoped claim: proves persisted-ev + final gate ONLY; selection/sizing RAW). Option-B clean
  observe lines start counting at the same scan. `POP_CLAMP_ENGAGED` never firing is
  dormant-by-arithmetic, NOT broken (pop_mult ≤ 1.0).
- **First native [CLOSE_FILL_GAP] + first post-#1137 `last_marked_at` stamp** — need a live
  close / held book (none this window).
- **#1139 one-beta tripwire** — unexercisable at 0 positions; fires only at 2+ concurrent live
  (that event also reopens A2's settled condition).
- **3-in-1(+accuracy-dedup) observability PR** — TOP-1 again; verify IF shipped, don't re-find.
