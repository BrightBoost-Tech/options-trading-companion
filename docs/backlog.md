# Backlog — tiered (rewritten 2026-07-02, post-close run)

Every item: one-line context · origin · reopen/done condition. Prior rewrite
(2026-06-13) and full pre-0613 history: `docs/backlog_archive_2026-06-13.md`
(narrative only, not priority). Settled items live in `audit/ledger.md`
(exclusion memory) — do not re-investigate. Pending VERIFICATIONS (as opposed
to builds) live in the ledger's pending lists, not here.

Tiers: **GATED** (built/known, awaiting operator go or an explicit trigger) ·
**P1** (next build slots) · **P2** (real but deferred) · **RESEARCH** (open
questions) · **RESOLVED — DO NOT REINVESTIGATE**.

## 2026-07-16 — POST-MERGE STANDING (authoritative; supersedes older queue text)

This is the current action surface after PRs #1203–#1227. Older dated sections
remain as audit history, but their priority lists are not actionable where they
conflict with this block. A merged code path is not runtime proof; runtime
falsifiers remain in the ledger.

### Shipped / remove from build queue

- **F-A9-5 truthful cohort reasons** — shipped in #1203.
- **Canonical position, max-loss slice** — pure payoff model shipped in #1204;
  the live risk-envelope consumer was wired to exact defined-risk max loss in
  #1214. Missing, malformed, or unbounded structures fail closed.
- **F-MIDDAY-POSITION-READ-FAILOPEN** — both known live-position reads now
  distinguish a legitimate empty book from a failed read via
  `LivePositionStateUnavailable`; the handler cannot remain green on failure.
  Runtime exception-path injection remains a verification, not a build.
- **F-POLICY-CAPITAL-FALLBACK + F-A9-8 job truth** — nominal `or 100000`
  fallbacks and green-on-fork-failure behavior closed in #1215.
- **F-A9-6 provenance identity** — model identity and deploy identity split in
  #1216.
- **Decision-tape git SHA writer contract** — `resolve_git_sha` accepts the
  explicit SHA, `GIT_SHA`, or a valid `RAILWAY_GIT_COMMIT_SHA`; code/tests
  are closed. First naturally written production row is still runtime proof.
- **Ranking commission leg count (cost phase 1)** — #1218 charges legs ×
  quantity × entry/exit in canonical ranking. This closes the $1.30-for-every-
  structure defect, not the full multi-basis-cost family.
- **Funnel denominator truth (telemetry phase 1)** — #1219 separates scanned,
  passed, selected, persisted, executable, and rejected counts.
- **F-A10-4 expiry-day thesis lag** — #1220 scores only after the regular-session
  close; no entry/exit rule changed.
- **Doctrinal reconciliation** — #1222 records the cost/funnel/expiry contracts.
- **Legacy PoP test debt (#775)** — shipped in #1223; the previously skipped
  suite now pins the current credit/debit PoP contract.
- **Small-tier fleet foundation** — #1225 merged the dormant schema and pure
  validation contract. The migration remains unapplied and the fleet has no
  provisioned accounts, policy bindings, runtime caller, or active epoch.
- **Prequential rolling-floor fixture** — #1226 shipped tests only; no runtime
  calibration behavior changed.
- **Calibration-report fetch truth** — #1227 makes the read-only report type a
  failed fetch separately from an empty cohort; the served multiplier path is
  unchanged.

### Current independent draft lanes

- **#1228 — replay tape-hash reader:** DRAFT; recomputes persisted aggregate
  hashes/counts through a signed operator-triggered, read-only job. It is
  deliberately unscheduled and is not full deterministic strategy replay.
- **#1229 — A10 broker-clock holiday guard:** DRAFT; threads one read-only
  broker-clock result through `data_stale` and RTH `job_late` suppression.
  Detection only; no schedule or trading behavior changes.
- Both remain unshipped until adversarial review and fresh CI. Neither draft
  authorizes a merge, deployment, trigger, broker write, or runtime PASS.

### Partial families — only these remainders are open

- **Canonical position remainder:** signed per-leg ratios across all consumers,
  multiplier-aware dollar greeks, payoff-capped stress, stage-time greek
  population, and broker-position reconciliation. Do not rebuild the max-loss
  slice already shipped.
- **Multi-basis cost phase 2:** unify executable spread/slippage/fee/quantity
  bases across scanner, ranker, gate, and realized comparisons. #1218 changed
  ranking commission only.
- **Funnel telemetry phase 2:** persist one terminal disposition for every
  selected symbol/candidate so selected→persisted loss is attributable. #1219
  fixed denominators only.
- **Phase-3 exit-basis measurement:** instrumentation/paired broker-live
  evidence only. No stop loosening; the 10–15 live-close gate still controls.
- **F-WINDOW residual:** heartbeat coverage plus a durable cross-job identity.
  The logging handler is shipped; cross-job joinability is not.

### Actual next priorities

1. **F-SHADOW-CAPITAL-PARITY operationalization — FOUNDATION MERGED #1225 /
   ACTIVATION GATED.**
   Prospective `small_tier_v1` = 50 isolated $2,000 accounts; $100,000 is an
   administrative total only. Activate only uniquely pre-registered policies,
   preserve `legacy_100k`, require terminal legacy positions+orders and one
   explicit DB-time epoch boundary, and count distinct source decision events
   rather than account rows. #1225 is schema+pure-contract only: migration
   unapplied, no rows created, no runtime caller, no policy registration, no
   flag changed. Next code slice is a fail-closed provisioning/activation
   transaction, but it cannot run until the legacy-terminal boundary is
   broker+DB proven.
2. **⑤ Independent terminal-distribution probability source.** One versioned
   terminal distribution feeding two integrations: vertical payoff and condor
   payoff. Observe/prequential first; baseline wins on Brier, EV-RMSE, and net
   outcome unless the challenger proves better.
3. **Multi-basis cost phase 2** (above), designed in parallel with ⑤ but merged
   independently.
4. **Canonical-position remainder** (above), split by one consumer per PR.
5. **Funnel telemetry phase 2**, then **option-liquidity
   freshness/provenance** (migration-bearing), then the observe-first exact-leg
   **OI floor** extension.
6. **A10 market-calendar correctness — DRAFT #1229.** Merge only after review
   and green CI; runtime falsifier is a broker-closed weekday/holiday cycle
   producing zero `data_stale`/RTH `job_late` alerts.

### Gated / runtime-only; not tonight build slots

- #1214–#1222 deployment identity, H8 health, first natural exact-max-loss
  decision, first natural leg-aware ranking decision, first natural git-SHA
  tape row, and the next post-close thesis run are **NOT_PROVEN_RUNTIME** here.
- **F-SHADOW-CAPITAL-PARITY** is authorized in design but not activated.
  #1225 is merged, but its migration must follow the migration procedure, the
  legacy terminal boundary must be runtime-proven, and policy assignments must
  be separately pre-registered before any account row may become active.
- **E19-2B** remains gated on an activated, comparable fleet epoch; **Phase 3**
  remains evidence-gated;
  **prequential operationalization** remains an operator choice between a study
  tool and a scheduled observe-only job.
- No live threshold, stop, gate, structure width, universe membership, or
  cadence change follows from this reconciliation.

---

## 2026-07-16 — FABLE 5 OPTIONS-ENTRY STRATEGY VERIFICATION (adjudicated)

Read-only docs-lane audit at `b95d3a3` (== deployed SHA on BE/worker/worker-
background, verified). Results:
**`docs/review/fable5-options-entry-strategy-verification-results-2026-07-16.md`**
(H1–H18 dispositions, capability manifest, funnel matrix, account census
$2,067.86 flat/small/level-3 re-read 07-16). Ledger 07-16 Fable-5 entry is
exclusion memory. **DEDUPLICATED — deliberately NOT re-filed:** credit-EV≡0
(⑤ owns it; now numerically proven + 0 credit suggestions all-time) · condor
mis-rank (A6-3/⑤) · cost-basis splits (multi-basis phase 2; the three bases
were measured live at scanner/ranker/stage gates) · qty>1 roundtrip basis (E2
observe item) · 07-06 micro-tier storm (resolved M4 item 0) · executor
legacy-filter skip (documented in-code, #1126-family memory) ·
`entries_paused` fail-open polarity (#1097 doctrine). **"Actual next
priorities" ordering: UNCHANGED** — everything below is P2/RESEARCH beneath
the standing safety lane and ①–⑦.

- **F-STRAT-ID-CONSUMERS (P2 · extends canonical-position remainder ·
  VERIFIED-CODE).** Strategy-identifier drift has two behavior-relevant
  consumers: (a) `LossMinimizer.get_strategy_type` classifies
  `LONG_CALL/PUT_DEBIT_SPREAD` as naked `LONG_CALL`/`LONG_PUT` because
  `StrategyType` has no debit-spread member (`common_enums.py:13-19`,
  `loss_minimizer.py:57-67`) — production-wired on the morning deep-loser and
  adaptive-caps paths (`workflow_orchestrator.py:877-896,4431-4472`); wrong
  payoff class for the two most-produced strategies, latent while flat. (b)
  `calculate_strategy_cap` substring-match misses `long_call_debit_spread`
  (reversed token order) → 0.05 floor cap instead of the intended 0.15
  (`risk_budget_engine.py:282-293`) — fail-TIGHT, wrong basis. Fix tightens
  nothing/loosens nothing intentionally: it makes consumers resolve the
  selector's actual identifiers (or consume the canonical position model — do
  NOT rebuild the shipped max-loss slice). Accept: both consumers resolve
  every selector-emitted identifier correctly + one crosswalk test pinning
  each producer identifier to exactly one canonical strategy (route-driven,
  not source-string). Falsifier: a morning-cycle loss analysis of a losing
  debit spread using a naked-long payoff. · origin Fable-5 H18.
- **F-BAN-INTEGRITY (P2 · NEW · VERIFIED-CODE + VERIFIED-RUNTIME).**
  `settings.banned_strategies` is a phantom feature: NO migration defines the
  column (repo grep, all of `supabase/migrations/`); the production column
  exists as untracked drift (ARRAY, `settings` has 0 rows); the sole reader
  silently degrades to `[]` at `logger.debug`
  (`workflow_orchestrator.py:2549-2563`); zero write surface (no UI/API/SQL);
  downstream enforcement (StrategyPolicy → selector → scanner double-check) is
  real, live-routed, and permanently fed `[]`. OWNER DECISION: build it
  end-to-end (migration + write surface + typed loud read failure + a route
  test proving a persisted ban blocks and a failed read never silently
  authorizes) OR remove the dead read+enforcement. Controls unchanged either
  way today (no ban has ever existed). Drift facet strengthens the existing
  migration-drift name-normalized allowlist item. Falsifier: a persisted ban
  row that fails to block on the scheduled route. · origin Fable-5 H12.
- **F-OPTIONS-LEVEL-PREFLIGHT (P2 · NEW · VERIFIED-CODE; account re-read
  VERIFIED-RUNTIME).** The broker wrapper's curated dict drops
  `options_approved_level`/`options_trading_level`
  (`alpaca_client.py:252-267`; repo-wide, the only "level" hit is a log
  string, `cash_service.py:119`); no strategy→minimum-level preflight exists;
  `_TERMINAL_REJECT_MARKERS` has no permission bucket
  (`alpaca_order_handler.py:56-61`) so a level rejection would burn 3 retries
  then land `needs_manual_review`. Alpaca mapping (docs, 2026-07-16): L1
  covered call/CSP · L2 +long call/put · L3 +spreads; account approved=3,
  effective=3 → LATENT (every shipped structure is L3-covered). Fix
  TIGHTENS (entries fail closed on missing/insufficient level; exits
  untouched). Accept: both levels serialized distinctly; per-strategy min-level
  preflight at the entry stage seam; permission-shaped rejects classified
  terminal; missing field → entries reject loudly. Falsifier: a broker
  permission rejection observed being retried as transient. · origin Fable-5 H9.
- **F-LIFECYCLE-TYPED-DEGRADE (P2 · NEW · VERIFIED-CODE · HARD TRIGGER:
  before any `strategy_lifecycle_states` row leaves `live_full`).** Loader
  fail-opens to `live_full` on table-missing/query-throw/empty
  (`progression_service.py:190-224` returns `{}`); missing row → `live_full`
  (`options_scanner.py:3918-3920`); malformed/unknown state is neither
  filtered nor capped (`:3921`, `sizing_engine.py:224`) — documented as
  intentional. Inert today: exactly 5 DB rows, all `live_full` (DB-verified
  07-16); exits are lifecycle-independent (verified), so entry fail-closed
  cannot strand exits. Wiring is pinned only by source-string tests
  (`test_lifecycle_sizing_cap.py:175-229`). Fix TIGHTENS the failure path
  only. Accept: typed loader failure distinguishes failed-read from
  empty-table; unknown state fails closed for ENTRIES (cap or exclude);
  origin-injected route test (query throws → no full-size entry emitted).
  Falsifier: DB blip during a cycle with an `experimental` row → full-size
  entry. · origin Fable-5 H11.
- **F-UI-CAPABILITY-HONESTY (P2 · NEW · VERIFIED-CODE).** The primary "New
  Trade" nav CTA (`DashboardLayout.tsx:66-70`) leads to a `Math.random()`
  mock validator with a 17-month-stale example expiry and zero network calls
  (`compose/page.tsx:17-35`); its dropdown advertises `covered_call`, which
  has ZERO backend hits repo-wide; `GET /validation/self-assessment` returns a
  hardcoded placeholder (`validation_endpoints.py:144-177`); registry
  metadata over-advertises (9 keys; 5 have no live producer; keys match NO
  persisted strategy string). Rider: UI-orphaned arbitrary-ticket endpoints
  `/paper/order/stage` + `/paper/execute` accept out-of-set structures incl.
  1-leg naked at the stage seam (leg-count check only,
  `paper_endpoints.py:91-141`) — still gated by #1038/#1101 but not by
  strategy set/phase/lifecycle. Accept: Compose wired-or-labeled-or-removed;
  dead options removed; orphan endpoints strategy-set-checked at the stage
  seam or removed; TradeInbox "no live execution" copy reflects server truth.
  No trading behavior change. · origin Fable-5 H17/H2/H1-rider.
- **F-SELECTOR-ROUTE-TESTS (P2 · NEW · VERIFIED-TEST-REACH gap).** The
  production selector path `get_candidates` (`strategy_selector.py:241-401`)
  and the IRON_CONDOR phase gate (`:372-387`) have ZERO executing tests
  (`determine_strategy` — off the production route — is the only selector
  method tested); tier-boundary tests pin the legacy ~3% number ($38.88),
  not the production allocator value (~$360 at $1,000). Accept: route tests
  drive `scan_for_opportunities` → `get_candidates` (pool + phase exclusion)
  and the allocator-path boundary numbers; §9 doctrine (drive entrypoint,
  assert output). · origin Fable-5 H1/H7/H10 test-reach.
- **Funnel telemetry phase 2 — EXTENDED (not re-filed):** add (a) a typed
  `strategy_phase_excluded` rejection distinct from
  `strategy_hold_no_candidates` (today conflated,
  `options_scanner.py:3115-3120`; only a filtered INFO line differs), and
  (b) `suggestion_rejections.strategy_key` population — NULL on 5,076/5,076
  rows in the last 14d, so per-strategy rejection attribution is currently
  impossible. · origin Fable-5 H10/H18.
- **F-TIER-CLIFF-REVIEW (RESEARCH · owner decision · VERIFIED-CODE).** The
  micro 90%-per-trade doctrine is documented operator intent
  (`small_account_compounder.py:29-30`, `docs/small_tier_allocation.md` §6,
  `docs/risk_math.md:29-33`) but produces a risk-RAISING discontinuity
  crossing DOWN through $1,000: NORMAL $360→$900 (2.5×), SHOCK $50→$450
  (9× — micro bypasses the 5% shock global cap, `risk_budget_engine.py:465`
  vs `:468`); a second, downward cliff sits at $5,000 (~$720→$112). No doc
  reconciles the drawdown-through-$1,000 direction. NOT a defect filing —
  an owner review: affirm / taper / SHOCK-gate. NEVER ad-hoc-adjust (existing
  loss-limit-coherence doctrine). Current equity $2,067.86. · origin Fable-5 H7.
- **F-SINGLE-LEG-EXPERIMENTAL (RESEARCH · owner-gated · VERIFIED-CODE).**
  Single-leg long calls/puts are supported at EVERY seam except candidate
  generation (registry/EV-with-cap/PoP/sizing/staging/broker-1-leg/close all
  verified; the missing piece is one `get_candidates` pool entry emitting a
  1-element legs list). Prerequisites before any build: scanner primitive
  `max_profit=inf` reconciled with the EV cap (`options_scanner.py:2070,2138`),
  F-OPTIONS-LEVEL-PREFLIGHT, F-LIFECYCLE-TYPED-DEGRADE (it would be the first
  real user of the `experimental` 1-contract cap). Broker level 2 satisfied.
  Strategy additions stay BEHIND integrity repairs. · origin Fable-5 H14.
- **Pending verification (ledger owns):** deployed `CONDOR_EV_MODEL` +
  tail-constant read-back — the ⑤ charter text says "tail deployed" with
  constants 0.6/0.35 that match NO code default (`options_scanner.py:214-216`
  defaults: strict / 1.00 / 0.50); reconcile by operator env read-back
  (names-only hygiene), then correct whichever side is stale. · origin
  Fable-5 H5.

## 2026-07-15 — v1.5 EXTERNAL-AUDIT ADJUDICATION

Executed the v1.5 audit brief; completed report = **`docs/review/external-full-audit-v1.5-results-2026-07-15.md`**
(the brief `…-current.md` is the charter, not results). Audited production code at **`bef2cdd`** (main moved
docs-only #1207/#1208). Ledger 07-15 v1.5 entry is exclusion-memory truth. **Deduplicated** against the existing
canonical-position / ⑤ / multi-basis-cost / Phase-3 / funnel-telemetry / option-liquidity-freshness / OI-floor /
E19-2B / F-SHADOW-CAPITAL-PARITY / F-POLICY-CAPITAL-FALLBACK / GIT-SHA-DECISION-PROVENANCE / prequential /
F-WINDOW-1a-1b items below — those are STRENGTHENED, never re-filed.

**COVERAGE MATRIX (retained findings):**

| Finding | Sev | Disposition | Backlog interaction | Priority | Falsifier / owner decision |
|---|---|---|---|---|---|
| F-MIDDAY-POSITION-READ-FAILOPEN (2 sites) | HIGH | retained | **NEW** | **P1-safety** | read-exception test stages no entry / breaker fails closed |
| A6-2 shadow-capital epoch ($100k, ~48×, champion too) | HIGH | retained | **EXTENDS-F-SHADOW-CAPITAL-PARITY** | **P1 (first operator decision)** | versioned live-tier observe-only cohort at a clean boundary; freeze cross-epoch promotion; NEVER rewrite historical rows |
| A6-3 condor-EV mis-rank | HIGH | retained | **EXTENDS-E12 / ⑤** | P1 (with ⑤) | one terminal distribution feeds both integrations |
| A7-1 Phase-3 accrual stalled (entry-rate-bound) | HIGH | retained | EXTENDS-Phase-3 (measurement) | gated | resume entries; ETA indeterminate until live fills |
| A2-1 watchdog cancel-ack double-entry | MED | retained | **EXTENDS-P0-A** | before 2+ live | broker-ack before terminal write |
| A2-2 canonical-position semantic gap behind quantity-coherent max-loss scalar | LOW | retained | **EXTENDS-canonical-position-P1** | with ① | exact vertical/IC payoff max loss reconciles to broker legs at every quantity |
| A4-1/A9-2 git_sha wrong env var | MED | retained | **EXTENDS-GIT-SHA-DECISION-PROVENANCE** | one-liner | fall back to RAILWAY_GIT_COMMIT_SHA |
| A4-2 replay hashes, zero reader | MED | retained | **NEW** | P2 | scheduled determinism check alerts on mismatch |
| A7-2 exit-basis stamp on 2/6 closes | MED | retained | EXTENDS-Phase-3 | gated | stamp lands on resting-GTC/sweep closes |
| A8-1 F-A9-5 (56 rows carry a dollar-vs-score label lie) | MED | retained | **EXTENDS-F-A9-5** | immediate tail (#1203 draft) | capacity-only rejection carries no score reason; score rejection uses the routing predicate's typed reason |
| A9-1 model_version = APP_VERSION lie | MED | retained | **NEW (F-A9-6)** | P2 | model_version changes on a model change w/o APP_VERSION deploy |
| A9-3 champion-path fork failures unmeasured | MED | retained | **NEW (F-A9-8)** | P2 | champion clone-insert exception yields status='ok' + 0 errors |
| A10-1 is_us_market_hours holiday-blind | MED | retained | **EXTENDS-area10** | **hard trigger < 2026-09-07** | 09-07 produces 0 data_stale/job_late HIGHs |
| E2 roundtrip qty-fix LIVE-INERT | MED | conditional | EXTENDS-W1 (observe) | observe-only | qty>1 live decision uses per-contract basis |
| Observe-window durability (W1/W2/W3/W5 incomplete; W4 semi-durable) | MED | retained | **EXTENDS-F-WINDOW-1a/1b** | before any arm | persist W1/W2 decisions, complete W3 beyond its alarm-only subset, preserve W4's existing count, and leave W5 UNSTARTED until designed |
| A1-1 replay runner input-blocked | LOW | retained | EXTENDS-E19-2B / replay-runner | P2 | replay reconstructs champion set from a decision_id, 0 live reads |
| A5-2 no decision_runs origin column | LOW | retained | **EXTENDS-suggestions_open-untraced-extra-runs + replay-runner** | P2 | scheduled/operator/retry/replay decision runs are durably byte-distinguishable |
| A3-1 stop-vs-thesis signal unconsumed | LOW | retained | NEW | research | the live query returns rows and no code path consumes them |
| A3-2 DTE bucket inert / A3-3 no apply-time n-recheck | LOW | retained | EXTENDS-segment-n floor / E1 | P2 (trigger-owned) | a segment mult≠1.0 with sample_size<8 reaches scoring |
| A9-4 freshness alert no-activity guard | LOW | retained | EXTENDS-§8 OUTPUT_FRESHNESS | P2 | a quiet learning-mode day fires output_stale=error |
| OPTIMIZER_V4/ALLOCATION_V4 dead-capability | NOTE | retained | EXTENDS-FORECAST_V4 #1126 inventory | P3 | any production import of optimizer_v4/capital_allocator |
| Internal-fill close-price sign | — | **REJECTED (NOT PROVEN)** | exclusion memory | — | a live/learning consumer reads avg_fill_price unsigned — none exists |

**ACTIONABLE items adjudicated (NEW or explicit EXTENDS; no duplicate filings):**
- **F-MIDDAY-POSITION-READ-FAILOPEN (P1-safety) — do NOT implement in this docs lane.** Two live-entry authoritative
  position reads fail OPEN (`except → return []`): `workflow_orchestrator.py:2240-2270` (silent, feeds scan
  concurrency/open-book risk/small-tier allocation before persist) + `paper_autopilot_service.py:1328-1343`
  (alerts, but breaker envelopes pass green-on-vacuum before the executor). Broker-reachable via
  `_stage_order_internal → submit_and_track` (alpaca_live+live_eligible). **Causality NOT inevitable** — later
  same-symbol dedup + the *enabled* utilization gate can independently stop it; the dangerous case is a
  transient/selective/false-empty read followed by successful staging. Fix: **type the unavailable state and
  distinguish an empty `live_ids` set from a FAILED authoritative read**; make scan AND executor outcomes
  fail-CLOSED (raise / `capture_partial` that aborts entries), keeping `live_ids==[]` as the only legitimate
  flat-book path (a genuine empty stays healthy). **Acceptance: route tests proving zero `submit_and_track` for
  BOTH a portfolio-ID exception AND a position-query exception.** **Escalate to P0-before-next-entry if the
  utilization gate is OFF/unproven, any broker-live position is open, or multi-position/qty scaling is enabled.**
  Siblings of the 3 reads #1195/F-E8-3 hardened. Own safety lane, above observational cleanup. · origin v1.5
  candidate-1 + E8 fourth-sentinel.
- **F-A9-6 typed-column-lie #5 (P2):** `model_version` written from `os.getenv("APP_VERSION")` (deploy string) but
  documented/consumed as model identity (`workflow_orchestrator.py:1585,3496`; `analytics_service.py:303`). Fix:
  redocument as deploy-provenance (never `GROUP BY` in calibration) OR stamp the real calibration epoch/hash. · v1.5 A9.
- **F-A9-8 champion-path job-truth gap (P2):** `fork.py:498` sets partial on `fork_errors`, but champion/legacy
  tag+clone failures never populate it (`:152-153 except:pass`; `:249-296` alert-only) → champion failure reads
  job-green (`champion_status='legacy_unmeasured'`). Fix: fold champion-path failures into the return counter. · v1.5 A9.
- **Replay determinism reader (P2):** `decision_runs.input_hash/features_hash` written, `verify_*` has no production
  caller → determinism regressions silent. Couples to A1-1 (the replay runner is the missing reader). · v1.5 A4-2.
- **Decision-run origin provenance (EXTENDS `suggestions_open untraced extra runs` and the replay runner, P2):**
  no durable field distinguishes scheduled, operator-triggered, retry, and replay cycles. Add versioned origin/trigger
  provenance so those runs are byte-distinguishable without overloading `strategy_name`; this is not a new standalone
  filing. · v1.5 A5-2.
- **Observe-window durable evidence (EXTENDS-F-WINDOW-1a/1b, P2, before any arm):** persist W1/W2 arm decisions;
  complete W3 beyond its current alarm-only durable subset; retain W4's existing semi-durable `job_runs.result`
  count and correct its label; W5 remains UNSTARTED until it has an approved design. Add the shared retry-stable
  identity owned by F-WINDOW-1b. Do not classify W4 as ephemeral or W5 as logs-only. · v1.5 W.
- **A10-1 Labor Day holiday-blind (EXTENDS-area10, HARD TRIGGER < 2026-09-07):** `is_us_market_hours:46-69` gates on
  weekday math with no `get_calendar` → 09-07 (Mon) reads market-open → false `data_stale`/`job_late` HIGHs. Fix:
  gate the alert path on `get_calendar` before 09-07. · v1.5 A10.
- **A2-1 watchdog cancel-ack (EXTENDS-P0-A):** `alpaca_order_handler.py:846-876` writes `watchdog_cancelled`
  unconditionally even when `cancel_order` raises on a just-filled order; next poll excludes it → double-entry. Fix:
  require a broker-ack (or re-GET) before the terminal write. · v1.5 A2-1.

**STRENGTHENED existing items (EXTENDS, evidence/dependency only — NOT re-filed):** F-SHADOW-CAPITAL-PARITY gains the
~48× champion-too measurement + the **versioned-epoch (not in-place re-seed)** fix shape, and the narrowed scope
(thesis LABELS are not notional-scaled; raw-dollar/capacity/sizing are) — F-POLICY-CAPITAL-FALLBACK literal is
INERT and is a SEPARATE fail-closed code item; E12/⑤ gains the live cross-structure mis-rank + the strict-vs-tail env disagreement; GIT-SHA gains the
root cause (Dockerfile `ARG GIT_SHA=unknown`) + one-line RAILWAY fallback; E19-2B/replay gains the A1-1 capture gaps
(capital/OBP/tier/book/ev_raw uncaptured); F-A9-5 gains the 56-row materialization + the raev/score secondary lie;
Phase-3 gains A7-1 entry-rate-bound ETA + A7-2 stamp-coverage; canonical-position gains A2-2's scalar-vs-structure
semantics; segment-n floor gains A3-2/A3-3; F-WINDOW-1a/1b gains the exact durability taxonomy; the existing
untraced-extra-runs item gains A5-2 durable origin provenance; OUTPUT_FRESHNESS
gains the no-activity guard; FORECAST_V4 #1126 inventory gains OPTIMIZER_V4/ALLOCATION_V4.

**Priority order (v1.5-confirmed, unchanged major ordering):** ① Canonical position representation · ② ⑤ terminal
distribution · ③ Multi-basis cost unification · ④ Phase-3 exit-basis measurement · ⑤ Funnel telemetry truth pack ·
⑥ Option-liquidity freshness/prune provenance · ⑦ Scanner OI-floor extension. **② and ③ may be designed in parallel;
neither licenses a live structure/width change.** Ahead of all of these for SAFETY:
**F-MIDDAY-POSITION-READ-FAILOPEN** (live-entry fail-closed) and **A6-2 shadow-capital parity** (the first operator
decision — gates every honest cross-cohort comparison). No control-loosening recommended anywhere.

**Canonical ordering:** first operator decision = A6-2 prospective shadow-capital epoch; first code build =
F-MIDDAY-POSITION-READ-FAILOPEN. #1203/#1204 follow only after rebase and adversarial review. This docs-only
#1205 reconciliation merges last, after sibling PR status and runtime/deployment evidence are refreshed.

## 2026-07-15 (Wed post-close) — UNIVERSE-CENSUS RECONCILIATION (read-only; ledger 07-15 entry is truth)

Read-only census of the 78-symbol universe + a live Aug-21 chain snapshot. **Nothing built/merged/
flipped.** The 12 verified findings live in the ledger 07-15 entry. Backlog consequences below are
DEDUPLICATED against existing items — deliberately NOT filed: "empty execution universe", "BKNG
missing", a new OI-floor item, a new terminal-distribution item, a new cost-unification item, any
stop-loosening, or any ticker (de)activation.

**PRIORITY ORDER (existing major ordering preserved):** ① Canonical position representation · ② ⑤
independent terminal distribution / payoff integration · ③ Multi-basis cost unification · ④ Phase-3
exit-basis measurement · ⑤ Funnel telemetry truth pack (below) · ⑥ Option-liquidity freshness +
prune provenance (below) · ⑦ Scanner OI-floor extension (below). **② and ③ may be DESIGNED IN
PARALLEL, but NEITHER licenses a live structure/width change.**

- **SMALL-TIER WIDTH RIDER (observational; ATTACHES to ①+②+③ — NOT a separate live-width build).**
  The configured $2.50/$5 widths give ~$440 defined max loss on the $2,067.86 book; $1 widths give
  ~$75 but worse fee/credit. Required FUTURE shadow cohort (observe-only; **no live config change
  until its falsifier clears**): compare $1 vs configured $2.50/$5 · qty=1 only · exact defined max
  loss · TRUE integrated-payoff EV (needs ⑤) · fee-only AND all-in cost · cost/credit + fill rate ·
  same symbol / expiry / directional thesis. · origin 07-15 census.
- **FUNNEL TELEMETRY TRUTH PACK — EXTENDS the existing 06-10-triage `universe_size`=scanner_emitted
  mislabel sub-bullet (below in the P2 batch); NOT a new identifier. Priority: supporting P1
  observability** (learning-mode funnel evidence is currently misleading). Accept: distinguish
  `active_universe_count` / `selected_symbol_count` / `scanner_emitted_candidate_count` /
  `h7_passed_count` / `persisted_count` / `executable_count` (never label emissions `universe_size`);
  PERSIST typed sizing/allocation drops (BKNG + AMD are stdout-only today) so every SELECTED symbol
  reaches a terminal funnel disposition; reconcile or type the `98`-vs-`78` gap; retry/idempotency
  never double-counts; zero-candidate cycles stay honest zeros; **reporting-only — no
  gate/ranking/sizing behavior change.** · origin 06-10 meta-audit ∪ 07-15 census.
- **OPTION-LIQUIDITY FRESHNESS + PRUNE PROVENANCE (NEW P2 package — NOT "small": provenance needs a
  migration).** Evidence: 67/78 `option_liquidity_score` ~40 days stale (2026-06-05); all 10 zero
  scores from that stale batch → zero did NOT prove current illiquidity; AAL/F/LYFT pruned together
  2026-07-06 with NO persisted reason (F still scored ~93 — precisely why reason provenance matters).
  Accept: verify + record the effective option-liquidity-WEIGHTING flag — **if weighting is OFF, mark
  the defect LATENT and require completion BEFORE arming it**; stale/missing scores normalize to
  UNKNOWN (never current zero-liquidity); define a refresh cadence + a freshness timestamp; every
  activation/deactivation carries actor / source / reason / effective_at; PRESERVE history (never
  overwrite the last state); **no automatic reactivation of AAL/F/LYFT.** · origin 07-15 census.

## 2026-07-14 (Tue post-close) — POST-MERGE RECONCILIATION · QUEUE ①–④ CLEARED

Ledger 07-14 (~19:2x CT) entry is truth. Docs-only lane from `bef2cdd`; nothing
merged/deployed/flipped. **The v1.4 post-close build queue is FULLY CLEARED** —
the ①–④ items in the 07-12 section below are RESOLVED and kept only as history.

**RESOLVED — DO NOT REINVESTIGATE (queue ①–④):**

| # | Item | PR | Squash SHA | Deploy status |
|---|---|---|---|---|
| ① | E8-3 typed sentinel | #1195 | `af1c5be` | superseded (REMOVED) |
| ② | E16-3 manifests + F-REPLAY-FK | #1199 | `f34d5cd` | **falsifier PASSED 07-14** (below) |
| ③ | E19-2 → shipped as **E19-2A** only | #1200 | `bef2cdd` | **LIVE** · falsifier 07-15 |
| ④ | F-A3-4 prequential parity | #1201 | `9670712` | **deployed within `bef2cdd`** · falsifier 07-15 |

- **② F-REPLAY-FK — CLOSED, falsifier PASSED (DB-verified 07-15 00:2xZ).** `data_blobs`
  9 rows, **first blob ever 2026-07-14 13:00:08Z** (was 0 all-time); `decision_runs`
  splits cleanly — 5 `failed`/`blob_never_persisted` (all 07-13, the annotated
  unrecoverable set) vs 4 `ok`/`tape_integrity='complete'` (all 07-14). Do not re-verify.
- **④ #1201 deployed WITHIN `bef2cdd`, not at `9670712`** — its own deployment is
  REMOVED (superseded 37 min later). Verify it BY CONTENT at `bef2cdd`; a
  deployment-SHA search for `9670712` reads as "never shipped" (H8 squash class).
- **③ shipped NARROW — `raw_candidate_eligibility_only`.** NOT selection, execution,
  fill, P&L, thesis, capacity, or joint-ranking evidence. **D②'s un-mute stays
  PARTIAL**; the 07-12 line "③'s SHA stamps the FULL experiment" is **superseded** —
  the full stamp waits on E19-2B.

**NEW P1 · E19-2B — full counterfactual selector (the split-out dependency).**
Joint normal-vs-prerejection ranking + capacity/slot accounting
(`max_positions_open` / `max_suggestions_per_day`) + selection semantics —
everything required before ANY entry-rate / conversion / P&L claim can attach to
the prerejection fork. **Blocks the D② full un-mute.** **GATED on
F-SHADOW-CAPITAL-PARITY + F-POLICY-CAPITAL-FALLBACK** — a selector that sizes
against a fabricated capital basis produces fabricated selections; fix the basis
first. · origin #1200 §15 (explicit non-goal) · done when: the fork produces a
joint-ranked, capacity-evaluated counterfactual selection on a broker-grounded
basis, and D② un-mutes in full.

**NEW P1 · F-SHADOW-CAPITAL-PARITY (HIGH, CONFIRMED-empirically).** All three
policy-lab cohort portfolios carry `net_liq = 100000` — **including `aggressive`,
the LIVE CHAMPION (`routing_mode='live_eligible'`)** — while broker truth is
**$2,067.86** (verified 07-15 00:2xZ; equity=cash=OBP=portfolio_value, positions
`[]`). ≈**48×** the deployable basis (§5.1: deployable = live Alpaca
`options_buying_power`, never a DB snapshot). **⚠ #1200's fail-closed
`_normalize_capital` (`fork.py:435-442`) does NOT close this** — it removes the
hardcoded `or 100000` *literal* and reads `net_liq` authoritatively, but the
column *contains* the fabrication; reading a fabricated value authoritatively is
still fabrication (H9). SCOPE (honest): the policy-lab **evidence** surface, NOT
live sizing (live capital comes from the broker OBP path + `RiskBudgetEngine`,
untouched). It is the quantified root under §8's "shadow ledgers are partly
fiction / shadows fill at 5–17× live size", and it makes **champion promotion
basis-broken** (cohorts sized at $100k compared to a $2,068 live account).
Interacts with — does not duplicate — #1124 promotion normalization (discount
0.31 measured). Seeding origin = `init_lab.py:12` `INITIAL_CAPITAL = 100_000.0`.
· origin #1200 §9 disclosure, widened by DB verification · done when: cohort
capital resolves to a broker-grounded basis (or the experiment declares its basis
explicitly AND promotion normalizes it), and a promotion comparison states its
capital basis.

**NEW P2 · F-POLICY-CAPITAL-FALLBACK (MED, CONFIRMED-by-cite) — TWO sites, not
one.** The `net_liq or cash_balance or 100000` fabrication survives at:
`policy_lab/fork.py:210` (legacy normal-shadow-clone loop — **the site #1200's §9
DISCLOSURE names**, annotated in-place at `:201`, out of its frozen scope) **and
`policy_lab/evaluator.py:251` — a SECOND, UN-NAMED site** found by grep this
session (#1200's PR body names only the fork site; fixing only the disclosed one
leaves the evaluator fabricating). Shares a root with F-SHADOW-CAPITAL-PARITY
(`init_lab.py:12`) — **fix as a family, not ad hoc.** · origin #1200 §15 · done
when: no policy-lab capital read can fabricate a default, both sites.

**NEW P2 · GIT-SHA-DECISION-PROVENANCE (MED, CONFIRMED-empirically).** The replay
tape is now complete in CONTENT and **silent on PROVENANCE**:
`decision_runs.git_sha` = the literal string **`'unknown'` on 9/9 rows, all-time**
(`distinct_sha=1`) across runs spanning **TWO distinct deployed SHAs** (joined
against Railway deployment windows: `8d93621` carried the five 07-13 runs,
`f34d5cd` the four 07-14 runs) — two code SHAs, one identical non-SHA stamp.
MECHANISM: the decision path reads **only**
`GIT_SHA` (`suggestions_open.py:139`, `suggestions_close.py:128`, no fallback) and
`lineage.get_code_sha` (`:264`) degrades `GIT_SHA` → `APP_VERSION` → `"unknown"`;
**the healthcheck already solves it** (`api.py:154-157` resolves `GIT_SHA` **or**
`RAILWAY_GIT_COMMIT_SHA`, the name Railway actually injects) — the decision path
just doesn't reuse it. **Defeats the stated contract "③'s SHA stamps the FULL
experiment"**: a tape that cannot name the code that produced it cannot attribute
a decision to a SHA. Also blocks any before/after A-B read across a recycle. NOT a
#1199 regression (#1199 delivered content integrity, never claimed provenance).
FIX: the decision path consumes the healthcheck's existing resolution (env
NAME-only; no value read). · origin 07-14 post-merge reconciliation · done when: a
`decision_run` carries a real SHA MATCHING the Railway deployment SHA of the
container that produced it.

**NEW P2 (RESEARCH-adjacent, OWNER-GATED) · prequential operationalization — the
falsifier that never runs.** **`prequential_validator` has ZERO production
callers** (verified repo-wide): no scheduler entry, no job handler, no import
outside its own module — the sole non-test reference is a **docstring** at
`calibration_service.py:317`; reachable only via its own `main()`/`__main__`
(`:242`,`:281`). **#1201 correctly repaired a validator nothing invokes** — the
[]-green disease is closed at the seam, but the seam is on no live route (the
#1126 costume's cousin, with the honest difference that #1201 never claimed a
caller). Recorded so no future audit reads "prequential parity shipped" as
"prequential validation runs". **SCHEDULING IS AN OPERATOR DECISION — not taken
here, not recommended by default**: the validator is the designated falsifier for
the calibration multiplier (F-A1-3/E17 family), so wiring it is live-adjacent
(cadence, queue routing, and what a failing verdict should *do*). Options,
unranked: (a) leave manual/on-demand — status quo, zero risk, falsifier stays
unexercised; (b) schedule read-only on `background`, alert on divergence; (c) gate
the multiplier on it — behavioral, needs its own PR + flag. · done when: the
operator picks (a)/(b)/(c) and it is recorded.

**★ F-WINDOW-1 — IDENTIFIER COLLISION RESOLVED (two defects were riding one
name).** The 07-13/07-14 entries closed one while the P2 tail still carried the
other — a silent-retirement hazard. Split, both preserved:
- **F-WINDOW-1a — heartbeat EMISSION → CLOSED at `1386834` (#1198).** The beats
  already existed (#1187 `log_shadow_heartbeat`) and rode a dead channel; the
  deliverable was the handler, not new heartbeats. Proven post-close by an
  `[ALPACA_SYNC]` INFO line reaching Railway. **This — and only this — is what the
  07-14 nightly's "F-WINDOW-1 CLOSED" means.**
- **F-WINDOW-1b — heartbeat COVERAGE + JOINABILITY → OPEN, stays P2 tail.** The
  v1.4 original: only W4 (APPLY_ORDER) + a generic post-portfolio EXECUTOR_SHADOW;
  **W1 no gate-site beat · W2 no per-consumer zero-eval beat · W3 pre-portfolio
  miss + no candidate/reservation-order identity · no shared cycle/decision ID → W5
  unjoinable.** A live channel does not create a shared correlation ID. **The ARM
  decisions wait on JOINABLE evidence — 1a's closure does NOT release them.**
  W-clocks do NOT reset for observability-only additions (unchanged). **Doctrine
  preserved: the arm-evidence clock restarted at `1386834` — the THIRD restart.**

**F-A9-5 — DRAFT, NOT SHIPPED (Lane A OPEN).** Stays P2 tail, unchanged in
substance (`_log_cohort_decisions` compares dollar `ev` to a 0-100 score threshold,
`fork.py:466-477` vs the real score filter `:233-236` → `ev_below_min` lies;
routing byte-correct; the logger must CONSUME the routing predicate's result, not
re-derive). Lane A = PR #1203 (`fix/f-a9-5-routing-log-truth`) is **DRAFT at `28e4990`**. The #1200
natural-observation prerequisite is VERIFIED satisfied, but #1203's title/body still carry the stale
`[BLOCKED FROM MERGE]` marker. It remains non-mergeable by process until metadata is corrected, it is
rebased onto current main, adversarially re-reviewed, and fresh CI passes. **Do not mark shipped**; a squash SHA
and H8 pin remain required.

**PENDING FALSIFIERS → the ledger's pending list owns these (not this file):**
#1200 first calibrated-rejected candidate (**no qualifying candidate =
INCONCLUSIVE**, base rate ~1–2/trading day) · #1201 `calibration_update` 07-15
10:00Z · #1201 `thesis_tracker` 07-15 22:00Z (**daily 17:00 CT, not hourly**).

---

## 2026-07-13 (Mon RTH, read-only) — DOCTRINAL-AUDIT ADJUDICATION (Sinclair/Natenberg)

Adjudicated at `8d93621` vs repo + DB + runtime; full verdicts + scorecard in the
ledger 07-13 (~12:1x CT) entry. Doc writes only. **Tonight's queue (② E16-3 →
③ E19-2 → ④ F-A3-4 → tail) UNCHANGED** — F-RISK-ENV returned CONFIRMED-LATENT,
not CONFIRMED-ARMED (the demotion flag is live-verified ON; the defective
concentration basis cannot block today).

- **NEW P1 · CANONICAL POSITION REPRESENTATION (absorbs the risk-envelope
  unit/sign fixes; ~1-2 evenings).** One typed position/structure model consumed
  by risk_envelope + stress: signed per-leg quantity + ratio · multiplier-aware
  dollar greeks · exact defined-risk max loss (vertical: width−credit; IC:
  max(side_width)−credit) replacing `_pos_risk`'s credit-received basis
  (`risk_envelope.py:200-201`) · payoff-CAPPED stress (a defined-risk book cannot
  lose more than Σ max-loss; SPY stress needs Δ×S×pct, `:524`) · broker position
  reconciliation. MERGES: the book-scaling family (#1166's persisted
  `max_loss_total` is the same truth — REUSE it, don't recompute) + greeks
  populate-at-stage (P2 below) as the input feed. The envelope's four confirmed
  defects (ledger 07-13) are the acceptance tests. URGENCY = the re-arming seam:
  unsetting RISK_UTILIZATION_GATE_ENABLED (sanctioned kill) or any demotion-check
  failure re-arms the `concentration_symbol` BLOCK on the credit-received basis.
  · origin doctrinal audit #3 + their #2 rec · done when: envelope + stress
  consume the canonical model and a credit-structure book computes width−credit
  risk end-to-end (test drives check_all_envelopes on a credit book, asserts the
  ratio basis).
- **NEW GATED · Score-each-vertical-before-IC (their #4 structure-selection
  insight).** An IC = two tail forecasts; each side must independently clear the
  ⑤-sourced probability bar + the unified cost bar before combining. GATED on
  queue-⑤ + the multi-basis cost unification — do NOT build against the current
  delta/fair-odds EV. · origin doctrinal audit · done when: IC assembly requires
  two independently-cleared verticals.
- **RV-basis unification (small; rides the multi-basis family).** `vol_math.py`
  (log, √252, ddof=0) is the standard; LIVE simple-return forks to convert (or
  annotate deliberately-simple): `regime_engine_v3.py:204-205` (the GLOBAL SPY
  regime vol — inline simple-return calc in the same file whose per-symbol path
  uses the log helper) · `factors.py:197-244` + `market_data.py:267-269,368`
  (HV-proxy iv_rank fallback) · `market_data.py:1060` calculate_portfolio_inputs
  (optimizer endpoints; np.cov ddof=1). Dormant forks inventoried in the ledger
  07-13 entry — no action there. · origin doctrinal audit RV claim.
- **Surface honesty annotations (doc-level; KEEP OBSERVE-ONLY — their rec =
  ours, runtime-verified policy=observe).** Rename/annotate
  `build_arb_free_surface`: convexity-in-w is necessary-not-sufficient for
  butterfly-freeness (cite their Gatheral note in the comment). Label
  `iv_surface.skew()` honestly (FIXED k=±0.35 raw put−call diff — not 25-delta;
  `iv_point_service.compute_skew_25d_from_chain` is the delta-true
  ATM-normalized one) and pick ONE term_slope form (`iv_surface.py:220`
  front/back RATIO vs `iv_point_service.py:277-283` 90−30 DIFFERENCE — opposite
  sign conventions). · origin doctrinal audit surface claims.
- **NEW P2 · Minimum segment-n for calibration admission (scoring-report §2a,
  verified 07-13).** Segment multipliers are admitted at
  `max(3, min_trades // 4)` = **3** observations (`calibration_service.py:240`,
  MIN_CALIBRATION_TRADES=8) while the overall gate requires 8 (`:217`);
  `apply_calibration` applies the most-specific segment with NO sample-size
  re-check (`:610-641`); the >5% deviation filter (`:250`) selects FOR small-n
  noise. A multiplier fit on 3 closes is noise wearing a coefficient. LATENT
  today (live blob `_overall`-only, n=8, ×0.5 floor — DB-verified); fires as
  live segments reach 3-4 closes. FIX: raise the per-segment admission floor
  (env-config, e.g. match the overall 8) OR serve overall-only until segment
  n ≥ threshold. Interacts with the 0.5 floor's known limits (the floor bounds
  shrink but cannot correct a noise-driven sign — ledger 07-13 clamp
  annotation). · origin scoring/gap report gap 6 · done when: no segment
  multiplier below the floor can reach apply_calibration.

### 07-13 ~13:0x CT — TONIGHT'S ② ADDENDUM + RIDER (root-caused pre-build; ledger 13:0x entry is truth)

- **② ADDENDUM — F-REPLAY-FK root cause is SERIALIZATION, fix both sides + the
  atomicity gate.** `data_blobs` = 0 rows ALL-TIME: every blob batch throws
  `Object of type bytes is not JSON serializable` (raw gzip bytes staged at
  `blob_store.py:158`, upserted through supabase-py's JSON layer at `:289-292`).
  NOT oversize (2MB cap warn-only, never hit), NOT one blob (82b5be18… is just
  the first FK reported). Fix: (a) bytea hex-encode on write + `\x`-hex decode
  on `get()`/`get_many()` (read path `:184-189` would fail on PostgREST's
  string); (b) blobs_committed == expected gate BEFORE decision_inputs insert →
  typed `capture_partial`; (c) oversize → same typed degrade; (d) test drives
  the REAL serialization boundary — the shipped MagicMock
  (`test_replay_feature_store.py:202-203`) is the 4th mock-at-failing-layer
  instance. Today's 5 tapes (13:00 close + 4 opens) unrecoverable — annotate,
  don't chase.
- **② RIDER (PROMOTED into tonight, operator instruction) — F-LOG-INFO-DROP:
  worker logging config.** No logging config exists anywhere in the repo → root
  logger unconfigured on both workers → EVERY `logger.info` dropped in-process
  (lastResort stderr = WARNING). All three shadow windows silent by CONFIG
  (guards correct, paths ran); the F-WINDOW-1 heartbeats are ALREADY BUILT
  (#1187, `log_shadow_heartbeat`) and ride the same dead channel — the fix is a
  handler/level at worker startup (root INFO vs targeted loggers = owner call),
  not new heartbeats. **⚠ W-clocks: [RISK_BASIS_SHADOW] has NEVER emitted; the
  d5edd50 arm-evidence window collected nothing; clocks restart at tonight's
  fix SHA.** ~~Supersedes the F-WINDOW-1 P2-tail item in the 07-12 section.~~
  **CORRECTED 07-14 — this superseded ONLY the EMISSION half (now F-WINDOW-1a,
  CLOSED at `1386834`/#1198). It did NOT supersede the P2-tail item, which is the
  COVERAGE + JOINABILITY defect (now F-WINDOW-1b) and remains OPEN.** Reusing one
  identifier for two defects nearly retired 1b silently; see the 07-14 section.

## 2026-07-12 (Sun night) — v1.4 EXTERNAL-AUDIT ADJUDICATION — 3 seam kills of our own weekend work

Report: `docs/review/external-full-audit-v1.4-2026-07-12.md`. Verdicts + census in
the ledger 07-12 v1.4 entry. All one layer BELOW this weekend's route-driving tests
(doctrine sharpened → CLAUDE.md §9). **Build NOTHING done this session** — read-only
+ doc writes. Monday post-close BUILD QUEUE: ① E8-3 → ② E16-3 → ③ E19-2 → ④ F-A3-4
→ tail (A9-5 · F-WINDOW-1 · F-A10-4).

> **⚠ SUPERSEDED 2026-07-14 — ①–④ ALL RESOLVED; see the 07-14 section at the top of
> this file (authoritative) and the ledger 07-14 (~19:2x CT) entry. Kept as history:
> the defect statements below are the shipped acceptance criteria, NOT open work.
> Deltas the retelling must not lose: ③ shipped NARROW as **E19-2A**
> (`raw_candidate_eligibility_only`) — the FULL experiment stamp moved to the new
> **E19-2B**; ④ deployed **within `bef2cdd`**, not at its own SHA `9670712`; the
> **F-WINDOW-1** tail item below is now split **1a (CLOSED at `1386834`)** /
> **1b (OPEN — coverage + joinability)**; **F-A9-5 is DRAFT, not shipped.**

- **P0-① · [RESOLVED — #1195 `af1c5be`] E8-3 typed sentinel (CRITICAL, <1 eve).** `_fetch_open_positions`
  (`intraday_risk_monitor.py:646-675`) + `_get_active_user_ids` (`:1691`) catch DB
  failures → `[]`, which `_check_user` reads as authoritative-empty → #1186's outer
  typed loop never fires → a failed book read = green q15 cycle blind to
  marks/stops/envelopes/force-close/tripwire. FIX: type BOTH reads — failed read →
  raise/typed failure, NEVER []-as-empty. **TEST (sharpened doctrine): inject the
  failure AT ORIGIN (the Supabase query throws) and assert AT TOP (the job records
  failed/partial) — spanning all layers; NO mock of `_check_user` or any
  intermediate.** CENSUS: 639/30d succeeded, book FLAT → un-disambiguated in
  job_runs; structural-latent, still critical. **LEDGER RIDER: if any position
  fills Monday before ① ships, the latent risk is live that afternoon — accepted,
  one day.** · origin v1.4 F-E8-3 (promoted; 3rd E8 layer) · done when: a failed
  read is never persisted `succeeded`, both sites, origin-to-top test.
- **P1-② · [RESOLVED — #1199 `f34d5cd`; falsifier PASSED 07-14] E16-3 manifest at ALL SEVEN returns + morning + roll-up (~1 eve).**
  `_capture_decision_manifest` covers 2 of 7 midday returns (missing
  `micro_tier_position_open`/`capital_scan_policy_block`/`global_risk_budget_
  exhausted`/`no_candidates`/`scanner_failed` — wire it into the `:2034` early-return
  helper) + the morning `suggestions_close` cycle emits NO terminal feature + the
  roll-up (`suggestions_open.py:26-40`) sums only `rejection_persist_failures`, not
  the generic `counts.errors` (my #1188 `replay_commit_error` never reaches the
  classifier). FIX: manifest at all 7 + morning terminal contract + roll-up carries
  generic nested errors. Test DRIVES each production return + the classifier.
  **CORRECTION: #1188 "EVERY return / COMPLETE" is FALSE — tape complete only from
  ②'s SHA** (3rd exclusion-integrity note on E16). · origin v1.4 F-E16-3 (promoted).
- **P1-③ · [RESOLVED-NARROW — #1200 `bef2cdd` shipped E19-2A only; the FULL
  experiment moved to E19-2B, see the 07-14 section] E19-2 pre-rejection cohort
  branching + coherent basis (design-care, MED fix-risk, ~1-2 eve).** The fork queries only `status IN ('pending','staged')`
  (`fork.py:44-56`), so calibrated-rejected candidates (`NOT_EXECUTABLE`,
  `workflow_orchestrator.py:3750-3767`) never reach the raw-EV cloner → SOFI-class
  divergence cases excluded. FIX: move raw-shadow eligibility BEFORE the calibrated
  rejection (the fork must see calibrated-rejected candidates) + persist `ev_raw` +
  explicit `ev_basis` on every clone + recompute `risk_adjusted_ev`/rank on the
  clone's basis + the decision snapshot from the clone's basis. Champion path
  byte-identical; clones stay simulated. Test: drive scan→calibrated-reject→fork,
  REQUIRE the shadow verdict. **D② ledger annotation gains: un-mute PARTIAL until ③
  — entry-rate evidence excludes divergence cases; `9a540ce` stamps the FLAG, ③'s
  SHA stamps the FULL experiment.** · origin v1.4 F-E19-2 (partial-FAIL promoted).
- **P1-④ · [RESOLVED — #1201 `9670712`, deployed within `bef2cdd`; note the
  validator has NO production caller — see "prequential operationalization" in the
  07-14 section] F-A3-4 prequential cohort parity (small).** `fetch_live_outcomes`
  (`prequential_validator.py:190-239`) ignores `window_days`, skips the epoch +
  corruption floor, and returns [] on failure → green `insufficient_data` (the
  E8-3 []-sentinel class — LINKED). FIX: share the production fetch predicate
  (reuse/import the calibration_service query builder — don't reconstruct) + typed
  fetch failure + honor `window_days`. CENSUS: pre_epoch=0 → NIL current numerical
  impact (structural only). · origin v1.4 F-A3-4.
- **P2 tail:** **F-A9-5 [DRAFT — Lane A OPEN, NOT SHIPPED]** — `_log_cohort_decisions`
  compares dollar `ev` to a 0-100 score threshold (`fork.py:466-477` vs the real score
  filter `:233-236`) → `ev_below_min` lies; the logger must CONSUME the routing
  predicate's result, not re-derive (join check = the test; rides ③'s fork territory if
  clean). PR #1203 `fix/f-a9-5-routing-log-truth` is **DRAFT at `28e4990`**; its #1200 runtime
  prerequisite is satisfied, but its `[BLOCKED FROM MERGE]` metadata is stale and it still needs metadata
  correction, rebase, adversarial review, and fresh CI — **do not mark shipped** · **F-WINDOW-1 → NOW
  SPLIT (see the 07-14 section): 1a EMISSION = CLOSED at `1386834` (#1198); 1b COVERAGE
  + JOINABILITY = the item that stays HERE** — per-decision-site heartbeats sharing ONE
  cycle/decision ID + W3 reservation-order identity (the arm-evidence repair's OWN second
  pass; W-clocks do NOT reset for observability-only additions, but the ARM decisions
  wait on joinable evidence — **a live channel is not a correlation ID; 1a's closure does
  NOT release the ARM decisions**) · **F-A10-4** — expiry-day 72h tracker lag; LOW
  (recommend: accept the documented lag, OR `expiry < today+1` at a post-close run; the
  Aug-21 rows are the live test).

**MONDAY RITUAL PINS += the three prediction checks:** (h) E19 first-scan
divergence grade · (e) E16 decision_runs↔manifest completeness + commit-err-green ·
(b) E8 Railway error-string ↔ job_runs correlation. Standing unchanged: ⑤
credit-probability (next-week strategy build; v1.4 A1 notes a dormant lognormal
terminal kernel in `opportunity_scorer.py:143-180,318-381` — reuse the probability
math only, H9-strict call/put-aware) · W2b (two PRs) · **sleep-hold = operator
tonight**.

## 2026-07-12 (Sun PM) — POST-BUILD STATUS (authoritative; supersedes stale details below)

The v1.3 re-sequenced queue is mostly cleared. Full detail: `audit/ledger.md` 07-11/07-12 entries.

**SHIPPED Sun (cite, do NOT rebuild):** ⓪ #1185 thesis price-basis (`27715ee`) ·
① #1186 E8 per-user seam (`3ef3c83`) · ② #1187 arm-evidence repair /clock-reset
(`d5edd50`) · ③ #1188 replay terminal contract (`9be25c4`) · ④ #1189 clone
normalizer + 33-row backfill (`74b7170`) · D② #1190 shadow raw-EV (`9a540ce`) ·
①b #1191 F-A8/E6-edge (`a6e0cb9`). (Sat shipped #1153-#1184 — see the weekend block.)

**v1.3 QUEUE REMAINING:**
- **⑤ P1 · Independent credit-spread probability source (GATES decision ④).** Credit
  EV ≡ $0 (payoff-circular; E12). Next week's strategy-side build; un-muting the
  2-leg cohort cannot produce a qualifying entry until it ships.
- **⑥ P0 · Residual partial-close custody (F-A2-1).** HARD TRIGGER: before routine
  qty>1 credit OR any open position ≤~10 DTE. Latent today (book FLAT).
- **⑦ P2 tail:** F-A10-1 summer warm-up blind · F-A3-1 fallback-discarded-at-insert
  · F-A3-2 DTE-always-unknown · F-A3-3 runtime view-identity check · F-A10-2
  Monday-holiday · F-A10-3 import-flag inventory · direction='long' liar · F-A5-1
  replay TTL (start measuring Monday).
- **W2b (TWO PRs, L3-spec'd in the 07-12 ledger):** (a) utilization would_flip
  threshold `cap*pool−committed` at `utilization_gate.py:420` — ship-alone M ·
  (b) allocator dual-basis instrumentation (continuous input → NOT would_flip).
  Follows PR-② (W-clocks already reset at `d5edd50`).

**⭐ DECISION / ARM CLOCKS:**
- **Book-scaling arm** (`RISK_BASIS_MAX_LOSS_ENABLED=1` + `BUCKET_CONTROL_ENFORCE=1`)
  — evidence clock reset to PR-②'s `d5edd50`; ~1 week of clean shadow logs from
  there (W3 now fails-closed on armed-unknown, W2 threshold real at RBE). Owner call.
- **Shadow un-mute on raw EV** — SHIPPED #1190 (default ON); shadow risk evidence
  trustworthy from PR-④'s `74b7170`; experiment breathes from Monday's scan.
  Promotion ENTRY-RATE comparisons carry the different-bases caveat; OUTCOME/thesis
  are basis-independent.
- **A10 rotation (D①)** — Security lens QUEUED for the next rotation; Calendar &
  Clock kept one cycle (F-A10-1 still earning).
- **Executor cadence (GATED)** — one-shot/day; trigger (clean relearn + positive EV
  tracking + #1071/#1072 exercised) NOT met.
- **8/8 clamp review + winsorize — SETTLED (not newly-actionable):** calibration is
  OUT of raw mode (ev=0.5×ev_raw since 07-10, L1-verified). Floor-HOLD (revisit
  ~15-20 live closes) + winsorize NO-ACTION were decided 07-09. Prompt v5.5 STATE
  line pending (operator edit) so the nightly stops re-flagging it.

**⚠ STALE-LINE CORRECTION:** the weekend-ships note below "#1169 … 2-leg credit
cohort gate CLEARED" is FALSE (v1.3 E12) — #1169 fixed the PoP LABEL only; credit
EV ≡ $0, cohort NOT evaluable until queue-⑤.

---

## 2026-07-12 v1.3 EXTERNAL-AUDIT ADJUDICATION — re-sequenced queue (verdicts + census in the ledger 07-12 entry)

Full report: `docs/review/external-full-audit-v1.3-2026-07-12.md`. All items below
VERIFIED against code + this DB (censuses in the ledger). **Build NOTHING was done
this session** — read-only + these doc writes.

**RE-SEQUENCED QUEUE (operator decides; verdict-driven):**
①  E8 per-user seam · ②  arm-evidence repair package (W2/W3/W4 + heartbeat) ·
③  replay terminal-capture contract · ④  clone risk normalizer ·
⑤  credit-probability source (GATES decision ④) · ⑥  partial-close custody
(hard trigger) · ⑦  the P2 tail.

- **① P0 · E8 per-user typed-outcome seam (CRITICAL, <1 evening).** `intraday_
  risk_monitor.execute()` swallows a `_check_user` exception into `ok:true,
  completed` (`:198-216`); on the 1-user account a COMPLETE q15 protection cycle
  fails green. FIX: mixed user results → typed `partial`; all-user failure →
  raise/failed; a **route-driving test around `execute()` driving the PER-USER
  loop** (NOT a source pin of the outer `run()` raise — the #1126 costume one
  level down). CENSUS 0/671 succeeded rows in 30d = structural-unexercised, still
  critical. **FALSIFIER (theirs): a deployed layer absent from GitHub that
  rewrites nested user errors before runner classification — none.** · origin
  v1.3 F-A4-E8 (promoted exclusion FAIL) · done when: no handler-caught per-user
  failure is ever persisted `succeeded` + the execute()-route test.
- **② P1 · ARM-EVIDENCE REPAIR PACKAGE (one work package, ~1-2 evenings) — resets
  the W-clocks.** The observe logs can't justify their arm decisions. (a) **W2**:
  pass `threshold_usd` + suggestion/cycle/cohort identity at all 3 callers
  (`utilization_gate.py:349`, `portfolio_allocator.py:163`,
  `risk_budget_engine.py:400`) so `would_flip` is ever non-null. (b) **W4**: full-
  tuple serialization in `_top_n`/shadow log (ticker,strategy,expiry/legs,id,
  raw/cal scores, magnitude) — `calibration_apply_ordering.py:72-74`. (c) **W3**:
  explicit-unknown (count + fail-CLOSED/not-armable when armed) — folds WITH last
  night's L3 unreadable-equity polarity into ONE PR (`bucket_control.py:47-60,
  101-131`). (d) a shadow-log **expected-cycle HEARTBEAT** for [BUCKET_SHADOW]/
  [RISK_BASIS_SHADOW]/[APPLY_ORDER_SHADOW] (nothing watches liveness → marker
  silence is ambiguous). **⚠ CLOCK RESET: W2/W3/W4/W5 arm decisions restart from
  THIS SHA; this week's logs are evidence-defective. W1's clock stands.** · origin
  v1.3 W2/W3/W4/W5 + A4 liveness · done when: each shadow line carries stable
  identity + a heartbeat, and W3 fails-closed on unknown when armed.
- **③ P1 · REPLAY TERMINAL-CAPTURE CONTRACT (E16, ~1-2 evenings).** Four seams:
  no-trade early return (`workflow_orchestrator.py:3771-3826`) precedes the
  `__decision__/ranked_candidates` capture → ZERO-suggestion cycles (the dominant
  funnel) have no output; rejected `continue`d tail omitted (PR-2 #1175 captured
  ACCEPTED only — owned); cache-hit inputs omitted
  (`market_data_truth_layer.py:1434-1438`); commit failure swallowed, no manifest/
  health. FIX: terminal manifest BEFORE every return (incl. zero/reject) · capture
  at the consumption boundary for cache+fetch · commit counts/error in the job
  result · manifest freshness/completeness health-check. · origin v1.3 F-A4-E16
  (promoted FAIL) · **Monday's capture pin RE-SCOPED: grades "rows exist + timing"
  ONLY; completeness known-defective until this ships.** · done when: every run
  (incl. zero/reject) has a terminal manifest + commit health.
- **④ P1 · CLONE RISK NORMALIZER (E14, PRECONDITION for W2/W3 trust).** Policy-Lab
  fork copies source `sizing_metadata.max_loss_total` unchanged across a contract
  change + omits the top-level typed field (`policy_lab/fork.py:254-333`). CENSUS:
  33 non-champion clones (neutral 23/23 + conservative 10/10) typed-null-but-JSON-
  present. FIX: one normalizer rescales per-contract truth → emits the canonical
  top-level total + consistent JSON provenance; **unknown stays explicit, never
  silently zero.** · origin v1.3 F-A9-E14 (partial-FAIL promoted) · done when:
  clone fills persist a rescaled typed total or an explicit unknown.
- **⑤ P1 · INDEPENDENT CREDIT-SPREAD PROBABILITY SOURCE (GATES decision ④).**
  Credit EV ≡ $0 because PoP is the payoff-implied fair-odds ratio (dispositive
  algebra; census 0 credit verticals in 120d). FIX: source probability
  INDEPENDENTLY of the payoff ratio — a validated terminal/breakeven distribution
  — then drive the real scanner→cost→rank route in observe/replay; a production-
  route test asserting NONZERO EV + ALL gates unchanged; observe/replay-only start.
  **⚠ decision ④ (2-leg credit cohort experiment) is GATED on this — un-muting
  cannot produce a qualifying entry until it ships.** ~1-2 evenings + observation.
  **⑤ CHARTER ENRICHED (doctrinal audit 07-13): ONE terminal distribution, TWO
  payoff integrations** — the same independent distribution must serve credit
  VERTICALS (E12) **and CONDOR EV** (today: `calculate_condor_ev_tail` =
  |Δshort|×0.6 breach / |Δlong| max-loss / fixed 0.35 severity,
  CONDOR_EV_MODEL=tail deployed — delta-as-probability plus two tuned constants,
  a modeled EV, not a forecast). Ensemble spec (theirs, attach verbatim to the
  build charter): IV-anchored baseline + EWMA/GARCH + HAR + earnings-jump
  component + uncertainty buffer. FALSIFIER (theirs, keep verbatim): **locked
  prequential cohorts must beat the delta/fair-odds baseline on Brier / EV-RMSE /
  net-P&L rank — else retain the baseline and stop.**
  · origin v1.3 F-A1/A6-E12 (promoted FAIL; corrects the #1169 closure claim)
  ∪ doctrinal audit #2 ·
  done when: a credit vertical can carry a nonzero honest EV through the gates.
- **⑥ P0 · RESIDUAL PARTIAL-CLOSE CUSTODY (F-A2-1, 2-3 evenings).** Partial
  multileg closes don't reconcile residual into `paper_positions`
  (`alpaca_order_handler.py:795-924`); a cancel/expiry → 30-min re-arm can stage
  the full stale DB qty; parent-filled-legs-disagree logs "closed" without closing
  (`:580-601` vs `:1002-1010`). Add partial fills as first-class residual states in
  the E6 machine + DTE-aware terminal escalation on the 404 re-arm loop
  (`alpaca_order_sync.py:33-84`). CENSUS 0 partial fills = structural/latent; live
  book FLAT today. **HARD TRIGGER: before routine qty>1 credit use OR any position
  ≤~10 DTE** (the 6 Aug-21 thesis-tracker rows are CLOSED, not open — watch for
  the next real open near-DTE position). · origin v1.3 F-A2-1 + A10 expiry seq ·
  done when: residual qty is reconciled before any close is authorized for it.
- **⑦ P2 TAIL (one-line each):** F-A10-1 summer warm-up blind — derive session-open
  from the ET/broker session object, `_RTH_WARMUP_OPEN_UTC=(14,30)` is fixed →
  80-105min EDT first-hour blind (`ops_health_service.py:46-69`); pairs with any
  A10 PR · F-A3-1 resolved-suggestion fallback discarded at insertion
  (`paper_learning_ingest.py:273-313` collects order|position id, `_create_paper_
  outcome_record` re-reads order-only) → a real close vanishes from calibration ·
  F-A3-2 DTE bucket always-`unknown` (fetch/v3 select none of the dte fields;
  feeds the validator's labeling) · F-A3-3 drift-guard sees committed migration
  syntax not deployed view identity — add the `pg_get_viewdef` runtime attestation
  as a periodic check · F-A10-2 Monday-holiday false-late (conditional; verify at
  the next holiday) · F-A10-3 `A4_MIN_HOLD_BARS` import-time flag → import-flag
  inventory (recycle to change) · direction='long' liar
  (`workflow_orchestrator.py:3633`) → the typed-column-lies inventory (member #4;
  no proved live consumer, NOT promoted) · F-A5-1 replay `data_blobs` TTL — 2MB cap
  warns-only + retention unbuilt; start the P2 growth measurement Monday (their SQL:
  daily count + sum(size_bytes) + sum(octet_length(payload))).

**MONDAY PINS (re-scoped):** (1) replay capture first-exercise → grades **rows-
exist + timing ONLY** (E16 completeness known-defective) · (2) E8 P0 census re-run
after any monitor incident · (3) replay TTL growth baseline (start measuring) ·
(4) thesis_tracker first authoritative run 17:00 CT (unchanged). The W2/W3/W4/W5
arm clocks do NOT start until ② ships.

## 2026-07-11/12 WEEKEND SHIPS — DONE (cite the ledger, do not rebuild)

Full detail in `audit/ledger.md` (07-11/12 entries). Shipped this weekend:
- **F-A4-1 typed job-outcome contract** #1153 · **observability remainder** #1156
  (5 noise classes) · **E7 viability re-wire** #1158 (3rd #1126, active route) ·
  **PR2 client_order_id + reconcile** #1160 (P0-A complete) · **F-A3-1 close_reason
  persistence** #1162 (thesis prereq).
- **★ Shadow-to-expiry THESIS TRACKER (I5)** #1164 + **F-A9-1** relabel — the #1
  missing measurement; first honest number 13/16=81% (live 5/7, shadow 8/9); only
  4/13 hits profitable (loss is downstream of the signal).
- **P0-B book-scaling PR-A** #1166 (persist cost_basis_total/max_loss_total +
  observe-only [RISK_BASIS_SHADOW]) · **COALESCE ev_raw restore PR-B** #1167
  (prequential prereq closed + drift guard) · **PoP inversion PR-0** #1169
  (credit PoP 0.298→0.702; LABEL only — ⚠ gate NOT cleared: EV≡$0 per v1.3 E12,
  cohort needs queue-⑤) · **REPLAY_ENABLE
  Phase-0** flip (capture live from Mon 07-13's 11:00 CT scan; validation pending).
- **B1/B2 bucket control + same-run reservation** #1171 — observe-first.

---

## P0 — IMMEDIATE NEXT BUILD (07-09 external-audit v1.1 adjudication)

- **P0-A · Broker-acknowledged live-close invariant (F-A2-1) — PR1 BUILT #1149
  (`e45290f`, 07-10); PR2 remaining (submit-path client_order_id).** A LIVE close must NOT record
  `paper_orders.status='filled'` / close the position without a broker
  acknowledgement. Today (verified d45ad63) a RAISED exception around the live
  submit (`paper_exit_evaluator.py:2178-2207`; sources incl. `get_alpaca_client`,
  the order-row fetch, imports, and the pre-cancel
  `alpaca_order_handler.py:245` OUTSIDE the retry-try) falls through to an
  INTERNAL FILL (`:2272-2280` writes `status='filled'`) on a live position, and
  the monitor logs it as a successful `force_close` (`intraday_risk_monitor.py:
  1428-1434`, only `deferred_uncorroborated` counts as failure). Charter: on a
  live-routed close, a submit exception must route to retry / needs_manual_review
  / deferred — NEVER internal-fill; the internal-fill path is paper/shadow ONLY.
  Add a regression test at the seam + keep the existing
  `paper_exit_alpaca_submit_fallback_to_internal` critical.
  **DESIGN — recon #4 state-machine MERGED here (A1b verdict: MERGE, 07-09 v1.2).**
  F-A2-1 as charter-only lacked an explicit reconciling state; the recon's
  order-lifecycle spec supplies it: a typed close-order status enum with an
  **`UNKNOWN_RECONCILING`** state (submit raised → we do NOT know if the broker
  got it) + typed transitions; on `UNKNOWN_RECONCILING`, do a **targeted broker
  order lookup by client_order_id** before any DB write, and only then resolve to
  filled (broker-acked) / retry / needs_manual_review — never a blind internal
  fill. Enforce the **fill+position-closure invariant** (a position may flip to
  closed ONLY paired with a broker-acked fill on a live route). Cites: Nautilus /
  Hummingbot order-state machines (design reference, not a dependency). · origin
  07-09 v1.1 F-A2-1 + v1.2 recon #4 · STATUS: **LATENT** (never fired on a live
  position — all 9 post-epoch closes broker-reconciled; the 10 internal-fill rows
  are pre-live alpaca-paper, latest 04-06). E6 exclusion-integrity FAIL noted in
  ledger. · **PR1 BUILT #1149 (07-10):** structural guard makes internal-fill
  unreachable for live · submit-exception + routing-query-failure fail-closed ·
  monitor success-costume fixed · force_close_failed first producer · E6
  remediated. **PR2 remaining (own session):** set a deterministic
  `client_order_id` at submit (touches the submit path) + reconciler
  `get_order_by_client_id` auto-resolution of the response-lost
  `UNKNOWN_RECONCILING` edge — until then that edge holds OPEN + alarmed
  (operator-resolved). · done when: PR2 ships the targeted auto-resolution.

- **P0-B · "Book-scaling readiness" epic — BUILD HALF COMPLETE (observe-first);
  ARM DECISION PENDING.** **STATUS 07-12:** (1) persist cost_basis_total +
  max_loss_total LIVE (#1166) · (2) allocator/RBE/utilization compute BOTH bases
  + log [RISK_BASIS_SHADOW] (#1166, observe) · (3) utilization candidate honest
  basis wired behind the flag (#1166) · (4) B1/B2 one-beta bucket control +
  same-run reservation BUILT observe-first (#1171, [BUCKET_SHADOW] + #1139-
  class alarm). **The build half is done. Enforcement = ONE composed owner
  decision after ~1 week of [RISK_BASIS_SHADOW] + [BUCKET_SHADOW] logs: arming
  `RISK_BASIS_MAX_LOSS_ENABLED=1` + `BUCKET_CONTROL_ENFORCE=1` together (with
  `BUCKET_MAX_PCT`, default 0.25 — one IC ≈18% of a $2k book fits, two same-
  bucket ≈36% do not).** Worked example (ledger): a real QQQ IC is ~$149 premium
  (7.2%) vs ~$372 honest (18%) at $2,068. The #1139 tripwire remains the armed
  guard meanwhile. · origin 07-09 v1.1 F-A1-1/A1-2 + 07-03 F-A2a · **NEXT: the
  arm decision (owner), not a build.** Legacy note: the pre-build book-blindness
  (allocator ~$0, utilization premium-not-max-loss) is what #1166 addresses.

- **P0/P1 · Calibration-ordering + prequential validation (F-A1-3 + recon #2) —
  design session, not a one-liner.**
  `apply_calibration` runs post-sizing (`workflow_orchestrator.py:3562-3569`),
  so SCORE / SELECTION / SIZING all consume RAW ev; only the persisted `ev` +
  final-stage round-trip gate + persisted `risk_adjusted_ev` are calibrated.
  Either move apply before ranking/sizing OR recompute the derived score/rank
  after apply. **Re-scopes the 07-10 16:00Z "proof":** `ev==0.5×ev_raw` proves
  the multiplier reaches the persisted ev + the gate, NOT that scoring/selection/
  sizing used it.
  **ABSORB recon #2 — prequential validation** so the multiplier is earned, not
  assumed: 4-close warm-up, fit on closes 1..k-1 and score close k (never fit on
  the point being scored); prefix-invariance (adding a close never rewrites past
  scores); knowledge-time fields (`known_at <= decision_at`); append-only
  calibration runs (each run a new immutable row).
  **A1a FIELD-CONTRACT FIX (CONFIRMED IN SCOPE):** `walkforward_validate_learning_v3.py`
  reads `learning_trade_outcomes_v3` expecting `ev`/`expected_value` +
  `realized_pnl`/`pnl`, but the table exposes `ev_predicted` / `pnl_realized`
  (+ `pnl_predicted`/`pop_predicted`) — the script `KeyError`s at `df['ev']`
  (`:101`). Fix the read to the real columns before the script can honestly
  validate anything.
  **FALSIFIER (GOLD — this is the retirement condition, keep verbatim):** *"if
  calibrated fails to beat raw over the next 15–20 forward closes on EV error /
  Brier, retain raw and stop spending complexity on the multiplier."*
  **A1a PREREQUISITE CLOSED (#1147, 07-10):** the walk-forward field contract is
  fixed (reads `ev_predicted`/`pop_predicted`/`pnl_realized`; H9 0.5-fabrication
  deleted; loud zero-row/missing-col guard; ISO8601 timestamp fix; smoke-run
  ran clean on n=99).
  **RAW-BASIS PREREQ CLOSED (#1167 PR-B, 07-12):** `ev_predicted` now
  `COALESCE(ts.ev_raw, ts.ev)` — the 06-23 silent revert to bare (calibrated)
  `ts.ev` is undone + drift-guarded (`test_ev_raw_coalesce_drift_guard.py`).
  Contamination verdict: no annotation needed (raw-mode + ev_raw fallback).
  Remaining for the prequential build: add the `is_paper=false` live-only filter.
  **⚠ L1 RECON (07-12, reshapes the apply-move fix):** SELECTION sorts on
  `score`, NOT `ev` — and `score` is frozen from RAW ev INSIDE the scanner
  (`options_scanner.py:3751,3919`; `rank_and_select` reads `cand["score"]` at
  `small_account_compounder.py:242-246`). So moving `apply_calibration` earlier
  is NOT enough — the fix MUST also RECOMPUTE `score` from the calibrated ev
  (the real cost). TO-seam = right after conviction at
  `workflow_orchestrator.py:2441` (before rank :2495); DELETE the midday
  :3562-3569 apply (move-not-add — a left-behind site → ev×mult²) + an
  idempotency sentinel; hash `ev_raw` for features_hash continuity. Effort ~M
  (half-full day, dominated by score-recompute). Full spec in the 07-12 ledger.
  · origin 07-09 v1.1 F-A1-3 + v1.2 recon #2 + 07-10 #1147.

## 07-11 v1.2 adjudication — NEW ITEMS + RE-SEQUENCED QUEUE

- **NEW P0 (headline) · F-A4-1 typed job-outcome contract.** The runner
  (`runner.py:134`) decides `succeeded` on `users_failed>0` ONLY; a handler that
  RETURNS a failure (`intraday_risk_monitor.py:152-158` → `{"ok":False}`) is
  recorded `succeeded` and is invisible to the A4 detector (reads only
  `counts.errors`). FIX (doctrine-clean): a typed outcome contract at the runner
  boundary — job status DERIVED from the normalized result
  (ok/status/counts.errors/users_failed); ops-health reasons from the normalized
  status, not raw producer JSON. Rollout WITH an inventory. **FALSIFIER (theirs):
  "a deployed normalization layer absent from the repo" — NONE exists
  (confirmed).** Absorbs the A4-detector half of obs PR #1. · origin 07-11 v1.2 ·
  STATUS: confirmed-structural, **0 fatal-masked-green instances** (356 designed
  ok=false; 0 intraday_risk_monitor false-green) — bounded · done when: no
  handler-returned failure is ever persisted `succeeded` (+ a test on the
  risk-monitor fatal-return path).
- **NEW P1 · E7 viability-bias re-wire (3rd #1126 instance).** Active
  `_execute_per_cohort` (`paper_autopilot_service.py:864`) sorts by DB
  `.order(risk_adjusted_ev)` on the STORED column; the M4 bias (sort-key-only,
  in `get_executable_suggestions`) is UNREACHABLE past the `:452` early-return.
  FIX: re-rank the fetched suggestions in Python inside `_execute_per_cohort` +
  a test that DRIVES that route (not a source-string pin on the dead function).
  **FALSIFIER: does any production cohort cycle traverse
  get_executable_suggestions? — No (dead past :452).** · origin 07-11 v1.2 E7.
- **NEW P1 · F-A3-1 outcome conservation + exit-cause propagation.** Ingest
  drops closes (7d window roll-off + no-filled-closing-order silent skip) and
  ERASES the exit cause (LFL writes static `reason_codes`, never `close_reason`).
  FIX: conserve (widen/backfill + surface `skipped_no_order` in counts) + carry
  `close_reason` into LFL details. **Thesis-tracker (I5) PREREQUISITE — the
  learning chain can't see WHY trades closed until this ships.** CONSERVATION
  COUNT (07-11): of 74 live-portfolio closes, **3 missing from LFL** (MSFT
  04-15, META 02-24, AVGO 02-18) — ALL pre-live PAPER era; the 9 real post-epoch
  closes are 100% conserved. So the CONSERVATION half is LOW urgency (old paper
  data); the **exit-cause ERASURE is the real driver** (all 71 in-LFL outcomes
  lack close_reason → the thesis tracker is blind to WHY). Prioritise part (b).
  · origin 07-11 v1.2 F-A3-1.
- **NEW P2 · F-A4-2 retry re-enqueue.** `mark_retryable` flips DB state without
  an RQ `q.enqueue`; 22 `queued` + 5 `failed_retryable` fossils never re-ran.
  FIX: re-enqueue on mark_retryable (or a DB-poll re-dispatcher). **FALSIFIER (a
  deploy read): worker start cmd RQ-only vs DB-poll — RQ-only CONFIRMED →
  silent-zero.** **MERGE with the stuck-running reaper — ONE work package
  (re-dispatch + fossil disposition), same mechanism.** Fossil census (07-11):
  27 stranded rows (22 queued + 5 failed_retryable), age 19–179d, ALL STALE —
  validation_eval is deprecated, the rest are stale recurring instances; NONE
  needs replay → disposition = **reap/dead-letter, not re-run**. **FOLLOWS the
  typed-outcome build (C3 verdict: TWO builds — F-A4-1 is result-derivation,
  F-A4-2 is re-dispatch; orthogonal).** The reap is a PREREQUISITE to reading
  F-A4-1's new output (else the fossils skew the A4/dashboard baselines the
  contract surfaces). · origin 07-11 v1.2 F-A4-2 ∪ reaper.
- **NEW P2 · F-A10-1 expiry/assignment safety.** 999-DTE default on missing
  expiry (`paper_exit_evaluator.py:158`, silently disables DTE exits) +
  assignment EQUITY filtered out of the option sync (`alpaca_client.py:540`,
  `len>10` heuristic → unmanaged stock). Assignment-adjacent; latent (flat book).
  FIX: reject/flag unpriceable-expiry (H9) not 999; add an equity/assignment sync
  path. · origin 07-11 v1.2 F-A10-1.
- **NEW P2 · F-A2-1 GTC post-fill allowlist.** `maybe_place_gtc_profit_exit`
  (`gtc_profit_exit.py:328`, wired `alpaca_order_handler.py:944`) NEVER checks
  `GTC_PROFIT_EXIT_PILOT_POSITION_IDS` (the sweep does; the post-fill hook
  doesn't); gated only by `GTC_PROFIT_EXIT_ENABLED` (OFF). FIX: enforce the
  allowlist on the post-fill hook. **FALSIFIER: any GTC placed outside pilot in
  broker history — none confirmed (flag off; 6 resting orders all pilot-sweep).**
  · origin 07-11 v1.2 F-A2-1.
- **NEW P3 (cosmetic/rider):** F-A5-1 dead `phase2_precheck` (past its 48h
  self-expiry, no machine consumer — retire/re-scope) · F-A9-1 "Confidence N%"
  mislabel (`SuggestionCard.tsx:683`, a 0-100 score shown as confidence —
  relabel) · F-A8-1/2 rejection CATEGORY dimension (flat reason; economics/error
  conflated — rides the taxonomy PR) · F-A3-2 autotune logged-not-applied
  (flag-gated compute-not-apply — rides the E1 family).
- **RE-SEQUENCED POST-CLOSE QUEUE (recommended; verdict-driven — the operator
  decides):** ① **F-A4-1 typed-outcome contract** (headline — the plane beneath
  job monitoring; cheap now, 0 fatals to expose) + absorbs obs-PR-#1's
  A4-detector half · ② **obs PRs (rest)** — flat-book stale guard · cross-owner
  re-egress dedup · accuracy-warn dedup · iv-refresh all-missing→ok · stub watch ·
  ③ **E7 viability re-wire** (small) · ④ **PR2 client_order_id** (P0-A
  completion) · ⑤ **F-A3-1** (thesis-tracker prereq) → remaining latents (F-A4-2
  · F-A10-1 · F-A2-1) + P3 cosmetics. REFUTED (no item): F-A6-2, F-A9-2, I6,
  most of F-A10-2/3 (broker get_clock covers holidays).

## 07-09 v1.1 adjudication — AMENDMENTS to existing items

- **Observability PR → SPLIT (recommended).** The carried 3-in-1 (ops_output_
  stale false-ager · job_succeeded_with_errors re-egress · re-egress dedup) gains
  F-A4-1 (`iv_daily_refresh` returns ok on all-missing) + F-A4-2 (`iv_daily_refresh`
  absent from `EXPECTED_JOBS`; the watched `learning_ingest` is a no-op STUB
  while real `paper_learning_ingest` is unwatched). Recommend TWO PRs: (1) the
  alert-noise 3-in-1 as-is; (2) a watchdog-coverage PR (EXPECTED_JOBS: add
  `iv_daily_refresh` + `paper_learning_ingest`, drop/replace the stub;
  iv all-missing → non-ok). Different surfaces, cleaner attribution.
- **Thesis-tracker build gains F-A9-1 relabel:** `signal_accuracy_rolling.win =
  pnl_realized>0` is a realized win-rate, mislabeled as signal accuracy → rename
  to `realized_trade_win_rate`; the tracker becomes the real thesis_accuracy
  source. Exhibit: B1 ≈78% thesis vs the view's 12.5% realized.
- **Phase-3 instrumentation gains F-A2-2 named mechanism:** TARGET_PROFIT
  suppression on `quote_complete=False` (`exit_mark_corroboration.py:246-253`)
  discards a computed executable-side divergence when a NON-executable leg side
  is missing (stop_loss never suppressed). Measure how often TP is suppressed on
  quote-incompleteness (→ positions held longer → more stop exposure).
- **Greedy replay gains F-A8-1 dedupe requirement:** rejection totals over-count
  (inner `process_symbol` reason + outer wrapper reason both `record()`); any
  future rejection-figure analysis must dedupe. (Lane A's 07-09 replay used
  `trade_suggestions`, not the ~916 rejection figure — unaffected.)
- **A11 SECURITY LENS → recommended as the next A10 rotation** (owner-gated).
  Credential/secret-scanning/history-hygiene as a standing audit lens; the
  incumbent (Calendar & Clock) rotates out only by the owner stating what it
  structurally misses. · recommended-pending.
- **FREE-LOOK — RESOLVED #1147 (attribution CORRECTED).** stored PoP > 1.0
  (16 rows, max 1.0704) was NOT "delta-based overshoot" — the delta composition
  is bounded ≤1 (raw pop max 0.7945). It was the calibration MULTIPLIER
  (`pop × pop_mult`), already silently clamped since 2026-04-16
  (`calibration_service.py:629`). #1147 made that clamp LOUD (`POP_CLAMP_ENGAGED`,
  dormant-by-arithmetic while pop_mult ≤ 1.0) and annotated the 16 stale rows
  (annotate-not-rederive, pop preserved). Do not re-file a clamp. Re-attribution
  ledgered 07-10 as a premise-check catch.

## 07-09 v1.2 comparative-recon integration (verified before backlogging)

- **NEW P1 · Deterministic decision replay (recon #1).** A runner over the
  existing capture substrate: freeze clock / SHA / config / equity / positions,
  inject `ReplayTruthLayer`, byte-compare decision outputs. **DECISION replay,
  NOT a P&L backtest** — fill evidence stays gap-3b's. Substrate grade ~55%
  CONFIRMED: `ReplayTruthLayer.from_decision_id` has ZERO production callers
  (docstrings + one test only); capture tables (`decision_runs`/`decision_inputs`/
  `decision_features`) EXIST. **⚠ PREREQ / DROP-CONDITION FIRED (verified 07-09):
  those tables have 0 ROWS** — capture is schema-only, nothing writes it. So the
  item is bigger than "runner over existing rows": step 1 is a **capture-WRITE
  path** (wire decision capture to persist runs/inputs/features), THEN the byte-
  compare runner. Prereq rider (recon's own): the runner is blocked until
  production capture rows exist. Effort: capture-write ~3-5 evenings + runner ~3-5
  evenings (recon's "3-5" assumed rows existed). · origin 07-09 v1.2 recon #1.

- **NEW P2 · Versioned earnings-event cohort (recon #3).** Replace the
  static-2025 / filing+90d earnings estimates with a **versioned feed**
  (`known_at`, `source`, `raw_hash`); classify **ETF-exempt / earnings_overlap /
  `event_unknown`-never-silently-safe**; **fix the gate to event-before-EXPIRY**
  (A1c(ii) CONFIRMED: `options_scanner.py:3866-3879` gates ONLY on
  `days_to_earnings<=2`/`<=7`, so an earnings event inside the hold window but
  >2 days out passes — the event-in-hold-window risk is unscreened). OBSERVE-ONLY
  first; a hard skip is an operator decision after source-reliability observation.
  Falsifier/guard: `event_unknown` must never resolve to "safe". 1-2 evenings.
  **ENRICHED (doctrinal audit 07-13) with their point-in-time schema: per-row
  status enum {confirmed / estimated / implied / unknown} + `known_at` +
  before-expiry flag** — today's filing+90d stepped projection
  (`earnings_calendar_service.py:75-88`) is served as a bare date with no
  confidence class, and the stub fallback map is 2025-dated fixture rot
  (`:27-42`; latent, only active if POLYGON_API_KEY unset).
  · origin 07-09 v1.2 recon #3 ∪ doctrinal audit.

- **NEW P2 · Per-leg quote envelope at entry staging (recon #5).** A timestamped
  `OptionLegQuote` threaded through to the final stage with identity / executable /
  age / skew invariants; **unknown age → one refresh → `quote_age_unknown`, never
  "fresh"**. Extends the Phase-3 quote-age plumbing to the ENTRY side (today entry
  staging has no per-leg quote-age guard). 1-2 evenings. **RIDER (scoring-report
  §2b, verified 07-13): capture the IV/greeks RATE + DIVIDEND basis per leg** —
  feed-provided IV carries unknown provider assumptions, and our own inversion
  assumes fixed r=0.045 / q=0.0 (`bs_inversion.py`; persisted ONLY on the
  historical-backfill path via `underlying_iv_points.inputs` — the daily
  snapshot + decision-stage paths capture nothing). Cheap; replay fidelity.
  · origin 07-09 v1.2 recon #5 ∪ scoring/gap report gap 8.

- *(recon #4 → MERGED into P0-A above per A1b; not a separate item.)*

## DO-NOT-RE-LITIGATE — rejected/settled gaps (stop next month's re-derivation)

Standing exclusion list. Each line is a gap CONSIDERED and REJECTED (or settled)
with why — re-proposing one is a wasted slot. Verified this session unless noted.

- **Full P&L backtest engine** — REJECTED in favor of *decision* replay (recon
  #1); fill realism is gap-3b's job, not a backtester's. Don't build a P&L
  backtester to "validate edge" at single-digit live closes.
- **Compounder greedy-stop `break`→`continue` build** — DOWNGRADED (Lane A
  replay 07-09): the budget break never fired in the last 4 cycles; blast radius
  zero on both risk bases. Reopen ONLY if a cycle presents >4 fitting candidates
  AND the roundtrip gate starts passing a tail. Don't re-file as a volume fix.
- **Credit-spread PoP inversion (F-A3-1)** — LATENT, NO FIX: the inverted
  `credit/width` branch (`ev_calculator.py:34-42`) accepts only 2-leg credit
  verticals; DB shows ZERO ever stored (only condors + debit spreads). Fix only
  if/when a credit vertical is actually produced.
- **Loosening any stop / envelope / gate on outcome or hindsight** — PERMANENTLY
  REJECTED (doctrine). A losing trade that passed every gate is not a gate bug; a
  proven arithmetic error is the only basis for passing more trades.
- **Shadow-cohort ledgers as EDGE evidence** — REJECTED: fill-fiction (100% fill
  at 5-17× live size; `SHADOW_FILL_DISCOUNT=0.31`). Mechanism evidence only until
  gap-3b normalization is observable.
- **"Position-management conventions missing" (21-DTE / 50%-credit / DTE gates)** —
  CORRECTED/REJECTED (A2.7): the recon confirmed these already ~85% EXIST in
  cohort policy; the earlier deep-dive's "missing" impression was wrong. Don't
  re-derive them as a new build.
- **Doctrinal-audit reject/defer list (07-13, adopted verbatim — re-proposing any
  is a wasted slot):** dynamic hedging at $2k · Kelly sizing at n=8 ·
  Heston/rough-vol/deep-learning vol models · SVI promotion before the risk-unit
  + cost fixes · universal 21-DTE/50%-credit exits as DOCTRINE (cohort policy
  already covers ~85%, per the A2.7 line above) · "high IV rank means sell
  premium" as a rule · OPRA historical tick purchases · more symbols / more
  frequency as an edge fix.
- **⚠ PROVENANCE NOTE:** the comparative recon's OWN rejected-gaps appendix
  (its Nautilus/Hummingbot comparison rejections) was produced in a prior session
  and is NOT recoverable from this session's context. The items above are the
  rejections VERIFIED this session; the operator should paste the recon's full
  appendix here verbatim to complete the standing list.

## GATED — pre-approved/known, do not re-find (operator/trigger owns the go)

- **Executor cadence — DO NOT BUILD until the trigger is met** — one execution
  shot/day (11:30 CT) is the known volume bottleneck, but the one-shot cadence
  is PROTECTIVE while calibration is unproven. Trigger, verbatim: **clean
  relearn + positive EV tracking + #1071/#1072 exercised — NOT MET** (07-02:
  calibration raw at 6/8 live post-epoch closes; #1071 evaluated-clear only;
  #1072 live-unexercised). · origin pre-0610 · when met: add ONE window
  incrementally + observe — never as a gate loosening.
- **Clamp review + winsorize (calibration outlier caps) — gated on 8/8** —
  the 0.5 ev/pop floor clamp and shadow-outlier winsorize (the 06-18 +662
  NFLX rail-pin class) only bite once a segment reaches ≥8 LIVE post-epoch
  closes; 6/8 as of 07-01. · origin pre-0610 + 06-18 · do when: 8th live
  post-epoch close lands; NOT before (raw mode makes both moot).
- **Durable-oversight Phase 3 (fill-quality-informed exits)** — precursor
  instrumentation shipped (#1102 close_fill_gap); evidence accruing **3 of the
  10–15 gate** (stamped live fills 07-01→07-08 in `paper_orders.order_json`,
  all with gap_fraction; the 07-08 sign fix at `alpaca_order_handler.py:660-665`
  means the basis is clean — verified 07-13). · origin 06-30 approved queue ·
  do when: ≥10–15 live close fills accumulated; the #1102 fields are the
  evidence base.
- **Paper-shadow migration pair — APPLY AS A UNIT, pre-enable gate** —
  `20260531000000_add_paper_shadow_routing_mode` (CHECK-constraint widen) +
  `20260601000000_paper_shadow_pairs` (state-machine table, lands RLS-off:
  mirror the rls_hardening precedent at apply time). Doubly inert today
  (`PAPER_SHADOW_EXECUTOR_ENABLED=false`; even a mistaken flip dies at the
  current CHECK before touching the missing table, swallowed as a midday
  warning). Blast radius: one ACCESS EXCLUSIVE lock on tiny
  `paper_portfolios` + a new table; zero behavior until the flag flips.
  · origin 06-29 diag Part 1/2, verdict re-confirmed 07-02 recon · do when:
  immediately BEFORE any `PAPER_SHADOW_EXECUTOR_ENABLED` flip
  (`docs/migration_procedure.md`, owner sign-off); RETIRE both + the executor
  module together only if Phase 1b is abandoned.
- **Dead-man's-switch operator handoff (code side SHIPPED #1109)** —
  heartbeat pings `HEARTBEAT_PING_URL` each run (:00/:30, hours 8–17 CT).
  Operator: un-pause the healthchecks check; cron `*/30 8-16 * * 1-5`
  America/Chicago, Grace 45 min; one after-hours Grace-to-1-min email test to
  prove the last hop, then restore. Semantics: silent check = one of
  APScheduler→BE→RQ→worker died — diagnose `job_runs` vs Railway. RTH-only
  trade-off accepted. · origin durable-oversight Window 1 · done when: first
  ping observed at the provider + the email test round-trips.
- **Supervised-mutation queue — ALL THREE EXECUTED 07-02 (operator-approved,
  exact counts, ledgered)**: (a) risk_alerts hygiene sweep 1,040 bulk-acked
  (H11 un-acked critical/high now means LIVE actionable) · (b) 82-row
  strategy/regime backfill · (c) 33-row funnel status backfill. Cite, don't
  re-run; the queue is empty.

## P1 — next build slots

<!-- ── 2026-07-09 EOD fix-queue (tomorrow, in order, operator's word) ── -->
- **① CALIBRATION-NOT-APPLYING (HIGH, headline; recon-then-fix, FIRST)** —
  the ×0.5 multiplier computes + stores 0.5-floored at 10:00Z but
  `apply_calibration` returns ×1.0 at the scan (`ev==ev_raw==39.71` verbatim
  07-09). Suspect: `get_calibration_adjustments` fails to map an
  `_overall`-only blob into the `{strategy:{regime}}` return shape → the
  `_overall` fallback (`calibration_service.py:577`) never fires; consumer
  `workflow_orchestrator.py:1745-1755`. **CLASS: built-not-wired (#1126
  family).** Cross-ref: external-reviewer §1 Q(1) — whoever moves first
  claims it, don't double-drive. · origin 07-09 EOD · done when: a stored
  multiplier ≠1.0 verifiably changes scan `ev` vs `ev_raw`.
- **② OPTION-A SHADOW-DETECTION MISS (one-liner + prod-value test)** —
  #1141 keyed `routing_mode == "paper_shadow"`; real values are
  `live_eligible` / `shadow_only` → shadow fix INERT (fail-safe to
  observe-only). Fix: match `shadow_only` (or `!= live_eligible`); pin the
  test on PRODUCTION routing values (the bug was test-fixture-vs-reality).
  · origin 07-09 EOD · done when: shadow qty>1 candidates evaluate on the
  per-contract basis. Ships after/with ①.
- **③ 3-in-1 OBSERVABILITY PR (carried from 07-09 morning FIX-TODAY; slipped
  the slot to the gate-fix)** — flat-book stale-ager guard (ops_output_stale
  on a flat book) + re-egress cross-owner dedup + #1104 writer-hardening
  (reconnect-then-retry; 6/677 lost 07-08) **+ NEW sub-item: accuracy-warn
  dedup** — `signal_accuracy_degraded` fired ×14 on 07-09 (~2/hr, observe-
  only, on the losing pool) = a fresh cry-wolf; add once-per-day /
  condition-fingerprint dedup. · origin 07-09 morning A9/A5/A4 · done when:
  H11 stops carrying the false/repeat HIGH classes.
- **④ OPTION-B OBSERVE-WINDOW CLOCK RESET (marker, at the ①+② SHA)** —
  07-09's 9 `[GATE_QTY_SCALED_SHADOW]` lines are INVALID (would-open on
  un-halved EV; shadows mislabeled live). The ~1–2wk observation counts
  ONLY from the SHA where calibration applies AND shadow-detection is
  correct. · origin 07-09 EOD · done when: the re-arm marker is stamped at
  that SHA and Option-B evidence accrues cleanly.

<!-- ── 2026-07-09 external-review adjudication integration ── -->
- **★ SHADOW-TO-EXPIRY THESIS TRACKER (NEW, P1 — the #1 missing
  measurement, from B1)** — force-closed positions leave NOTHING following
  the underlying to its ORIGINAL expiry, so thesis quality (signal) can't be
  separated from execution. B1 spot-scored **~78% thesis-hit vs 11% P&L →
  the loss is DOWNSTREAM, not signal.** Build: a lightweight tracker that,
  per closed position, records the underlying's path to `nearest_expiry`
  and scores in/out of profit-zone — observe-only, no decision impact.
  · origin 07-09 B1 · done when: thesis hit-rate is a standing metric.
- **Phase-3 exit-basis MEASUREMENT reopen (NEW, P1 — their #3; NOT a stop
  change)** — synchronized combo NBBO / order-preview capture ALONGSIDE the
  full-cross corroborated UPL + quote age + realized fill, at each stop
  fire; shadow noise-band rule observe-only. Quantifies the over-pessimism
  (A7/B1: stops fired on corroborated UPL worse than realized, closing
  winning theses early — QQQ-IC 06-15 inside its range, stopped −73).
  Explicitly instrumentation, not relaxation. · origin 07-09 A7/B1 ·
  TRIGGER: next session after the observability 3-in-1.
- **Multi-basis cost cleanup — RE-ELEVATED P2→P1 (A3 confirmed the ordering
  distortion)** — ranker fee = fee×contracts×2 (NO ×leg-count) + 5%-of-EV
  slippage proxy vs the gate's executable cross; under-costs 4-leg vs 2-leg
  in RANKING. Magnitude small ($ few on tiny EVs) but real; given B1's
  "downstream is the problem," cost coherence matters. **Worst case quantified
  (doctrinal audit 07-13): an IC round trip is 8 leg-contracts ≈ $5.20 at
  $0.65/ct vs $1.30 computed at `canonical_ranker.py:69` — 4× understate
  (verticals 2×). Their one-basis spec adopted: a single executable cost model
  (per-LEG-contract fees + executable spread) shared by scanner, ranker, and
  gate.** Fold in: A4
  score-saturation (min(100) clamp, guardrails.py:138) + the SOFI perpetual-
  100 artifact.
  **PoP-UNIFICATION CENSUS (rider, #1147 07-10, hard-gate before the 2-leg
  cohort):** SEVEN base PoP computations exist (ev_calculator.calculate_pop ·
  calculate_exit_metrics `abs(delta)` [take_profit_limit source] ·
  calculate_condor_ev · options_scanner `_estimate_probability_of_profit` ·
  `_condor_pop_from_legs` · opportunity_scorer `_calculate_ev_pop` ·
  forecast_interface `forecast_ev_pop`) + 2 transforms (apply_calibration,
  conviction) — the multi-basis disease extends to probabilities. The inverted
  credit/width one (F-A1 PoP-semantics, below) is calculate_pop's credit
  branch. **A unified PoP MUST bound-assert [0,1] at the compute site** (the
  insurance the #1147 clamp-log defers to the right place — do NOT scatter
  per-site clamps). · origin 06-10 A1-runner ∪ 07-09 A3 ∪ 07-10 #1147 census.
- **A1 PoP-semantics fix (NEW, HIGH-for-credit-work, LATENT now)** —
  credit-spread PoP = credit/width is INVERTED (≈P(loss); ev_calculator.py
  :42). Unexercised on the live book (IRON_CONDOR + debit spreads not in the
  branch) but **BLOCKS the 2-leg vertical / credit-spread cohort**. · origin
  07-09 A1 · done when: credit-spread PoP = 1 − credit/width (or a proper
  delta-based PoP) + a test on a far-OTM spread (low credit/width → HIGH
  PoP). GATES: the two-leg-vertical shadow cohort waits on this.
- **greedy-stop (Tier-2) — AMENDED (their #2): READ-ONLY REPLAY FIRST** —
  quantify blast radius before any build; staged observe-first. Rider (A5):
  the legacy compounder fit-test uses ~3%×score (~$60) not structure
  max-loss ($372) — a self-alerted 6-8× gap; the "fit" test tests a fiction.
  → **REPLAY DONE 2026-07-09 EOD (Lane A) → DOWNGRADE (tail always-empty at
  this scale).** Replayed the last 4 scan/execute cycles (07-02/07-07/07-08/
  07-09). The greedy stop is `small_account_compounder.py:280-286` (a `break`
  on first budget-non-fit; the count-cap at :258 and quality-floor `continue`
  at :266 are separate). Aggressive (live) candidates/cycle = 1 / 5 / 3 / 1;
  busiest was 07-07 (5 distinct structures, 4 QQQ + 1 SOFI; the DB's "10" is
  cohort-suffix fan-out on `legs_fingerprint`). **The budget BREAK never fired
  in any cycle:** its fit test is `current_risk_usage + estimated_risk >
  risk_budget` where `estimated_risk` is the legacy ~$40–60 stack, and ≤5
  candidates × ~$60 never exceeds `remaining_global_budget`; `risk_budget`
  column is NULL on every suggestion row. **Every non-executed candidate died
  DOWNSTREAM** — `ev_below_roundtrip_cost` ×14 + `symbol_already_held` ×1 +
  EOD dismiss — none by a budget break. Blast radius = **ZERO recovered
  executable candidates on BOTH bases**: legacy (budget never binds) and
  allocator-real (any candidate the break could spare immediately hits the
  roundtrip gate, net-EV-negative). The binding constraints are UPSTREAM
  (scanner yield ~1–2 names/cycle) and the DOWNSTREAM roundtrip cost gate — the
  greedy break is not on the critical path at ~$2k. **Reopen only if** a cycle
  ever presents >4 fitting candidates AND the roundtrip gate starts passing a
  tail (i.e. tier/scale change or spread-regime shift). The cosmetic
  `break`→`continue` fix (P2 item below) is still correct-in-principle but
  buys nothing measurable now.
  · origin 06-10 A6-runner ∪ 07-09 A5.
- **Capital-adequacy honest note (doc line, NOT a deposit rec)** — divisible
  1-lot 4-leg structures clearing real per-contract cost imply ~$7.5-8k
  equity; the ~$2k book is structurally cost-bound (§1 of the external
  packet). Record as a design constraint, not advice. **Rider (doctrinal audit
  07-13, their Chicago Fed citation): the edge must be PROVEN conditional,
  never assumed structural — small-account survival math compounds the cost
  bound.** · origin 07-09 §1 ∪ doctrinal audit.

- **Gap-3(a): shadow-ledger promotion-time normalization** — per-contract
  (or per-$-risked) cohort scoring + a measured fill-confidence discount
  (live fill base rate ≈0.33) applied at policy_lab evaluation ONLY (ledger
  rows untouched); kills the 5–17× size fiction before the next promotion
  eval. Spec + recon counts: `docs/specs/shadow_fill_realism.md`. · origin
  07-02 gap-3 recon · done when: cohort scores compare on a normalized
  basis; the full post-and-wait model (b) stays its own recon-first session.

<!-- ── 2026-07-09 backlog reconciliation: items that were ledger-only /
     prompt-KNOWN-PENDING only and had FALLEN OFF this actionable list
     (the report→action drift the 07-08 meta-audit exists to catch —
     re-added here so a "what's next to build" scan actually finds them). -->
- **EV-basis / fee-unit recon (LIVE-MONEY, P1, recon-first)** — the gate's
  `gross_ev` (unscaled scan-time EV) is compared against a
  quantity-scaled `round_trip` cost; the 06-10 A1-runner fee-unit finding
  and the 07-08/07-09 gate mismatch are the same class. **07-09 nightly
  proved it TIMES LIVE ENTRIES**: aggressive QQQ blocked at stamped
  `net_ev +35.62` (16:00Z) while an equivalent structure passed (17:41Z);
  gate log `net −111.86` vs stamp `net_ev NULL/+35.62` on near-identical
  candidates. **URGENCY ↑: the 07-09 10:00Z calibration boundary (EV/PoP
  ×0.5) now flows into this same comparison.** · origin 06-10 A1-runner ∪
  07-08/07-09 · done when: one basis end-to-end; per-decision NO
  reconstructable. TRIGGER: pre-market recon session (do NOT touch the gate
  from a status sweep). **⚠ 07-09 UPDATE: the DECISION-FLIPPING qty-scaling
  portion SHIPPED as #1141 (Option A, `03e11d8`, gate now per-contract for
  shadows / observe-only for live). What REMAINS here is the COSMETIC
  multi-basis unification only — the three cost models that don't flip a
  decision (scanner modeled ~$5.60 · ranker per-structure · gate
  executable). Demoted P1→P2 (cosmetic). Note the calibration ×0.5 does NOT
  currently reach this gate anyway — see the 07-09 EOD fix-queue #1.**
- **NFLX 06-08 pre-epoch live close backfill (P3, data completeness)** — the
  06-08 NFLX −$84 live close is on the broker + champion ledger (9 all-time)
  but absent from `learning_feedback_loops`; pre-epoch so it never feeds
  calibration. Filed in the ledger (07-08); promoted to a backlog line so it
  doesn't fall off (meta-audit lesson). · origin 07-08 shadow-vs-live census
  · done when: rides any future supervised backfill, or explicitly declined.
- **B1/B2 real one-beta bucket control (LIVE-MONEY, P1)** — the per-bucket
  correlation cap; the #1139 tripwire ALARMS on ≥2 live positions but does
  not CONTROL. · origin 07-03 F-A2a · TRIGGER: before the book routinely
  holds 2+ live positions · done when: block-level per-bucket % enforced.
- **Compounder greedy-stop BREAK (LIVE-MONEY volume, P2)** — first candidate
  that doesn't fit zeroes the whole cycle's selection
  (`small_account_compounder.py:286`; the comment self-doubts "skip and see
  if smaller fit? Greedy: stop"). Re-verified still real 07-08. · origin
  06-10 A6-runner · done when: `continue` not `break` (+ test); pairs with
  the A1 volume charter.
- **#1104 writer-hardening (MED, observability)** — reconnect-then-retry
  (fresh client) so a same-connection burst doesn't lose rows; 6/677
  rejection rows lost 07-08 (broken pipe on the retry too); also stamp the
  failed symbols into `result.errors` (F8 surfaced the COUNT, not the
  items). · origin 07-09 A4 · TRIGGER: bundle with today's 3-in-1
  observability PR OR next connection-burst (if it ships in the 3-in-1,
  move to SHIPPED — do not double-track).
- **06-10 runner-finding triage batch (#12, P2, one session)** — the
  goes-silent runners from the meta-audit: expiry-day×unpriceable defer
  seam (own recon, LIVE) · PoP-denominator asymmetry + dead DTE segmentation
  · funnel `universe_size`=scanner_emitted mislabel · time-stop/eod-phantom
  rows (A7-dormant territory) · A9-F4 stored-vs-recomputed fingerprint ·
  F-A2d wrapper-import-seam fail-closed skip · N4 `learning_ingested` dead
  column · N1/N2 backlog orphans · 06-10 A5 queue-HOL + A6 budget-blindness
  (verify partially-superseded). · origin 07-08 meta-audit · done when: each
  gets shipped / filed-with-trigger / acked.
- **gap-3(b) post-and-wait fill model** — promoted from the sub-note above
  to its own line (it had no standalone entry). · origin 07-02 gap-3 ·
  TRIGGER: own recon-first session, after gap-3(a)/#1124 observed at Gate 4.
- **Tradeable-universe recon (read-only)** — which universe names can
  actually pass the round-trip cost gate at current spreads (the first live
  rejection: SOFI round-trip 92 vs gross EV 30.25 — the small-tier universe
  may be structurally spread-eaten); recon before any threshold/universe
  reaction, never a gate loosening. · origin 07-02 first #1101 rejection ·
  done when: a per-symbol executable-spread table exists and the operator
  has read it.

### Shipped 07-02 from this tier (cite, don't rebuild)
data_stale predicate retune → #1115 (weekend-excluded job_late + 360 default;
0 job-arm false HIGHs on day one) · MTM mark-write corroboration → #1116 ·
ops_health_check q30min-real dedup → #1114 · signal-accuracy telemetry
(gap-2) → #1118 (baseline 1/6, Brier 0.2751) · streak breaker (gap-1) →
#1119 (planned first trip exercised + operator-recovered 07-02).
## P2 — real but deferred

- **Greeks populate-at-stage (gap-4 follow-up)** — legs have NEVER carried a
  `greeks` key (envelope double-dormant, §8 doctrine); populate from the
  stage-time snapshots (already fetched), THEN decide caps (all four default
  0 = no-limit). Never silently populate without its own PR + tests. ·
  origin 07-02 gap-4 recon · done when: staged legs persist real greeks and
  the caps question gets an explicit owner decision.
- **Streak-breaker N revisit** — N=3 chosen pre-baseline; revisit against
  gap-2 base rates once n≥15–20 live closes (config change only:
  `STREAK_BREAKER_N`). · origin 07-02 gap-1 · reopen at n≥15 live closes.
- **Mark-write residuals (from #1116)** — monitor Part-B doesn't stamp
  `last_marked_at` (q15min writes invisible to staleness queries);
  `paper_eod_snapshots` doesn't carry the corroborated fields (vol_signal
  analytics stay raw-basis). · origin 07-02 P1-C · done when: both residuals
  closed or explicitly accepted.
- **Broker-clock guard on watch→merge automation** — merge chains must check
  the broker calendar (`get_clock.is_open`, not weekday math) before firing;
  a CI watch that sleeps across a session boundary must fail-safe to
  NOT-merge; the watch must also confirm a CI run EXISTS before watching
  (the instant-return race). · origin 07-03 · done when: clock-gated or
  codified in tooling.
- **F-A1a rollback ghost-restore + recommendation-cooldown** (07-03 audit) —
  `check_rollback`/Gate-7 consume "recommended" promotions rows; an
  interleaved recommendation nets NO champion. **HARD TRIGGER: must ship
  BEFORE any challenger reaches 8 trades** (margin ahead of Gate 4's 10). ·
  origin 07-03 FULL A1 · done when: recommendation rows excluded from
  rollback/cooldown reads.
- **F-A4a stuck-`running` job_runs reaper — P2-ELEVATED (this week's spare
  slot)** — mid-run recycle orphans rows permanently (4 historical fossils
  named 07-06: validation_eval ×2, promotion_check, order_sync);
  merge-every-evening × learning-chain overlap = live odds. TTL-based: mark
  stale `running` → `failed_retryable`. Batch F-A2c (breaker NULL-pnl
  streak-break) + F-A2b (per-position vs per-symbol envelope wording) here
  if trivial. · origin 07-03 FULL A4 · done when: the reaper runs scheduled.
- **Winter-close blind hour (A10) — SHIPPED #1172 (07-12).** `is_us_market_hours`
  now ET wall-clock (9:30–16:00 America/New_York) via zoneinfo (mirrors
  intraday_risk_monitor._fallback_is_market_open_et); byte-identical for EDT, the
  EST 20:00–21:00Z blind hour is fixed. **The 2026-10-01 hard trigger is RETIRED.**
  Cite, don't rebuild.
- **Scanner OI-floor strike filter (M2 follow-up)** — the general fix behind
  the GLD strike-modulus: filter selection candidates on `oi >= floor` at
  the same `_split_chain_to_calls_puts` seam (`None` → keep; the legacy
  fallback chain carries no OI). Self-filters every symbol's dead strikes.
  **07-15 census EXTENSION (not a new item):** OI IS available read-only from
  `get_option_contracts` (with an `open_interest_date` — carry the freshness
  alongside the value) but is ABSENT from the snapshot path used for leg
  selection; wire exact-LEG OI (never a symbol aggregate) into selection;
  round-strike concentration matters (IWM 280 = 64,908 OI vs off-round
  282/277 = 1,357/256 — prefer the deep round strike); missing/stale OI →
  typed UNKNOWN, never zero; OBSERVE-ONLY measurement before any enforcing
  floor; adjusted/nonstandard contracts stay excluded.
  · origin 07-06 M2 recon ∪ 07-15 census · done when: OI floor at the seam,
  H9-safe, observe-first.
- **Nightly-audit dead-man ping (audit-loop ③, 07-06 night triage)** — a
  healthchecks.co cron check on the local nightly-audit schedule (report
  write → ping), same pattern as the worker's #1109. Root cause of the
  07-05 miss was machine-side (30-min sleep + WakeToRun/StartWhenAvailable
  both False — operator fixing task settings); the ping makes the NEXT miss
  visible in email regardless of cause. · origin 07-06 C3 · done when: a
  missed nightly run emails within Grace.

- **Migration tracking drift check (process fix, recon COMPLETE 07-02)** —
  27/112 migration files tracked (82 pre-tracking-era, 1 post-era procedure
  miss `20260426000000`, 2 deliberately gated). Fix: nightly-audit/CI
  drift check — diff `supabase/migrations/*.sql` basenames vs
  `supabase_migrations.schema_migrations` names (match by NAME, not version
  prefix) against a checked-in allowlist carrying each gate condition;
  not-tracked + not-allowlisted → audit ALERT. Keeps `apply_migration` the
  single canonical path. Pre-era 82-file reconciliation stays #62, separate.
  · origin 06-29 diag Part 2 · done when: the drift check runs nightly and
  the allowlist exists.
- **OUTPUT_FRESHNESS registry expansion** — watches `calibration_adjustments`
  + `learning_feedback_loops` (Phase 1); mark refresh
  (`paper_positions.last_marked_at`) still unregistered — and the monitor
  Part-B persist doesn't stamp that column (fold into the MTM P1). · origin
  06-13 audit A4 · done when: mark refresh registered with a tuned max-age.
- **v3 view Gate B (wire-vs-retire)** — `learning_performance_summary_v3`
  live since #1076; conviction multipliers all-1.0 until a live bucket ≥20
  (far off). · origin pre-0610 · reopen when: any live bucket approaches 20.
- **config.py fail-open-looser stop** — `policy_lab/config.py`
  DEFAULT_CONFIGS hardcode 2–3× LOOSER stops (≈0.40/0.50/0.65) than live DB
  cohorts (0.15/0.20/0.30); a cohort-load failure fails LOOSE — make it
  fail-CLOSED. (Ex-bundle partner ghost-sweep shipped #1107; this stands
  alone now.) · origin 06-15 · done when: cohort-load failure falls back to
  the TIGHTEST config.
- **IV/vol remaining gaps (clusters 1–3 shipped #1086–#1089)** — delta-only
  PoP for non-spread strategies, no IV-accuracy outcome loop (A4 capture
  fields now accumulating), vol-unaware sizing. · origin 06-2x IV audit ·
  reopen when: A4 rows suffice to grade IV-rank vs realized (needs live
  volume).
- **Greeks validator observe-only** — promote the greeks envelope from warn
  to a tested observe→enforce path. · origin pre-0610 · reopen with data.
- **signal_weight_history epoch/is_paper guard (tripwire, dormant consumer)**
  — segment-multiplier writer has no epoch/is_paper filter; sole reader
  `DynamicWeightService` has ZERO call sites. · origin Phase-1 scope-lock ·
  do IF/BEFORE `DynamicWeightService` is ever activated; do not guard a dead
  reader.
- **chain_mechanics_formula_anomaly noise** — legacy `option_spread_pct`
  fires >300% on deep-ITM verticals (~24×/week, observability-only). · origin
  06-13 audit A6 · done when: formula handles deep-ITM or the print is made
  honest.
- **Startup flag-echo** — boot should log the parsed value of every registry
  flag; read-back is manual per deploy. · origin pre-0610 · done when: boot
  echo exists on both workers.
- **Loss-limit coherence** — per-symbol envelope vs cohort stop vs vestigial
  0.50 precedence is deliberate-but-undecided at compounding capital (§5). ·
  origin pre-0610 · reopen when capital crosses a tier cliff; never ad-hoc.
- **Legacy rollups** — older aggregation paths duplicate canonical_ranker /
  close_math; consolidate. · origin pre-0610 · reopen with data.
- **Dead instrumentation** — submitted_at/latency fields and lying counters
  partially fixed 06-12; sweep the remainder. · origin pre-0610 · done when:
  no counter interpolates a MAX constant as an actual.
- **FK wart** — foreign-key/nullable mismatch noted in migrations. · origin
  pre-0610 · reopen with the next migration touching it.
- **Deploy windows** — codify no-RTH-merge as a CI/branch guard. · origin
  06-13 · done when: an RTH merge is blocked or warns.
- **#908 live credit-mleg-close validation** — next system close on a credit
  structure (the QQQ resting TP fill would qualify). · origin pre-0610 ·
  done when: a credit close validates positive-limit, no sign-incoherent
  raise.
- **#1035/#1036 mark fail-closed exercise** — verify both monitor fail-closed
  paths fire under partial-quote. · origin pre-0610 · reopen with a
  partial-quote incident.
- **Cohort-stop cooldown realized_loss from fill** — writer records
  trigger-time UPL, not the close fill; minor metadata inaccuracy, no
  consumer; largely obviated by the 06-15 structural clamp. **07-09 triage:
  now 2-for-2 on live closes post-#1080 (−48.99 stored vs −15 realized;
  −155 vs −10) — the magnitude gap widens with the Phase-3 over-pessimism
  pattern; anything reading this column for magnitude is misled, bench
  durations unaffected. Refinement folded here, no new line.** · origin
  06-15 · done when: reconcile backfills from the fill, if ever worth it.
- **IRON_CONDOR/chop structural suppression (WATCH)** — live-only→raw forgoes
  the old ×0.5 deflate; if IC/chop keeps losing, suppress STRUCTURALLY
  (StrategyPolicy ban / min-edge), never via thin calibration. · origin
  06-18 · revisit at n≈8–10 IC/chop closes.
- **Persistent job-level worker/queue tag in job_runs** — `locked_by` is null
  post-completion; otc-vs-bg unaditable after the fact. · origin 06-18 ·
  done when: job_runs carries the executing queue/worker durably.
- **trade_suggestions.created_at index (minor)** — created_at-filtered
  queries full-scan; EOD sweeps use indexed cycle_date as workaround. ·
  origin 06-18 · done when: the index exists (fold into the next migration
  batch).
- **risk_alerts auto-resolve TTLs (successor to the hygiene sweep)** — after
  the one-time bulk-ack (GATED (a)), consider severity-tiered auto-resolve so
  the un-acked count stays meaningful. · origin 06-18 · done when: TTL policy
  decided (may be "no").
- **suggestions_open untraced extra runs (minor)** — 15 runs in 10 trading
  days vs 1 scheduled (extras ~14:0xZ + one 17:09Z); harmless to freshness
  (extra runs only refresh), provenance unknown. · origin 07-02 recon (B3) ·
  done when: extras traced to their trigger (manual/retry) or stopped.

## RESEARCH — open questions, no committed build

- **Vol brackets** — regime-conditioned sizing/threshold brackets beyond the
  normal/chop split. · origin pre-0610.
- **Area-8 capture fields** — persist underlying-spot-at-decision + spot+1d
  as the conservative proxy for DARK-leg rejects (XLE dead-leg class is
  unmarkable on the executable side by construction). · origin 06-13 audit
  A8 · done when: rejection rows carry the proxy fields (additive, observe).
- **Executable-for-stops (OBSERVE-ONLY experiment)** — log what each stop
  WOULD do on the achievable side vs mid, persist the divergence; review
  after ~2 weeks for over-fire on wide/illiquid names before any adoption
  discussion. · origin 06-15 (Phase B commit-2 deferral).

## RESOLVED — DO NOT REINVESTIGATE (cite, never re-derive)

- **Unattended-operation cluster (06-29 diag Part 4) — ALL SHIPPED**: config
  fail-open #1094 · scheduler watchdog #1095 · alert egress #1096 ·
  entries-only halt #1097 (`ops_control.entries_paused`, migration applied
  06-30) · A4 silent-failure detector + alert() insert retry #1100 ·
  entry round-trip cost gate #1101 (first evaluation pending — ledger) ·
  close-fill-gap instrumentation #1102 · scanner rejection-persist retry
  #1104 · data_stale alert content from the firing arm #1106 ·
  ghost-sweep live-routed scoping #1107 (retires the 06-13 P2 "sweep
  excludes shadows" item; §8 seam note stale pending next doctrine pass) ·
  **07-02 post-close run: dead-man's-switch ping #1109 (`97bace3`) · typed
  strategy/regime on outcome rows #1110 (`716ba2a`) · direct-insert alert
  egress relay #1111 (`7bc9927`)** — with `OPS_ALERT_WEBHOOK_URL` +
  `HEARTBEAT_PING_URL` set on both workers 07-02, detection AND delivery
  paths exist end-to-end; remaining actions are GATED operator handoffs +
  ledgered first-exercise verifications, not builds.
- **A4 ingest opened_at regression** — #1098 (`f7dab1d`); post-fix ingests
  verified clean 06-30/07-01; `realized_vol_over_hold` NULL on short holds is
  DESIGNED (`A4_MIN_HOLD_BARS=3`).
- **Learning-chain queue routing (A5 06-13)** — #1077 + SimpleWorker start
  cmd; 6-job chain on `background`; map test-pinned
  (`test_learning_chain_queue_routing.py`).
- **Funnel status truthful (#1073)** — Layer B exercised 06-18, Layer A
  exercised 06-30 (2 suggestions stamped executed at the position-insert
  seam). Only the 32-row backfill remains (GATED (c)).
- **Live-only calibration + v3 view (#1076)** — empirically confirmed 07-01
  (escalation 30/60/90 all sample_size=6 = live count); raw mode holds until
  8. [CONVICTION] DEGRADED gone (v3 live) — do not re-expect the
  once-per-recycle line.
- **REGIME_V4_ENABLED env drift** — aligned 06-18 (`0` both workers);
  behaviorally inert (flag unwired).
- **EXIT_EVAL_DEBUG honest print** — #1067 (`ad8ce0f`), operator-confirmed
  live 06-16; prints the cohort threshold the decision computes through
  (observed live 07-01: −494.496, not the flat default).
- **is_paper live/shadow discriminator** — #1069 (`efb9a3a`) + supervised row
  corrections 06-17; ingest derives is_paper from `order.execution_mode`.
- **PDT** — retired FINRA + Alpaca 2026-06-04; never flip
  `PDT_PROTECTION_ENABLED`.
- **Historical NBBO** — no historical option-quote endpoint; counterfactuals
  use executable-side-at-decision or are marked indeterminate, never
  hindsight quotes.
- **External frameworks** — no mixed-tool architecture decisions; settled.
- **Retro-recompute** — pre-#1051 sign-flipped EVs walled off by
  `CALIBRATION_EV_EPOCH`, never retro-corrected.
- **Mode-column** — execution_mode layering settled; both ALPACA_PAPER layers
  must be false for live.
- **Backtest deferral** — forward-only learning-mode is the deliberate
  choice this phase.
- **#71 async-dispatch migration sweep** — endpoints moved sync→202+enqueue:
  PR-1 audit (`rq_dispatch_audit_2026_05_04.md`), PR-2
  (/tasks/policy-lab/eval), PR-3 (/tasks/validation/init-window). All
  shipped; traceability tokens retained here because migration-doc guard
  tests assert them in this file (`test_policy_lab_eval_async_migration.py`,
  `test_validation_init_window_async_migration.py`). Do not drop the tokens
  on future reorgs.

---

### Rewrite provenance (2026-07-02)
Sources: `audit/ledger.md` through the 07-02 post-close run (#1109/#1110/
#1111), the three 07-02 recon reports (B1 MTM consumers, B2 migration drift,
B3 data_stale retune — full tables in the 07-02 post-close report), and the
06-29 diagnostic memory set. The 06-13 tier assignments they superseded are
preserved in git history of this file.
