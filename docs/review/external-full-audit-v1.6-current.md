# EXTERNAL FULL AUDIT v1.6 — Ten-Area Current-State Deep Dive

**Issued:** 2026-07-19  
**Expected immutable code baseline at issuance:** `fdf5b55cb9f9dc5391f191df3e3876a3c5ded355`  
**Current-state revision:** through PR #1296 and PR #1299, on top of the merged owner-decision and parallel-implementation sequences  
**Area 11 / self-extension slot:** EXCLUDED  
**Mode:** read-only audit, runtime adjudication where available, documentation-only integration. Implement nothing.  
**Claude Code model policy when executed:** Fable orchestrator; every delegated audit/review agent explicitly uses Opus.

---

## PURPOSE

This is the successor to v1.5. It audits the system after the large 2026-07-16 through 2026-07-19 closure sequence: entry preflight and lifecycle fail-closed controls, truthful funnel persistence, historical close-sign correction, versioned policy registry, inactive 50-slot fleet provisioning, terminal-distribution and cost-model foundations, canonical Greek/ratio repairs, typed H7 dispositions, quote/OI provenance, event-driven model review, dark single-leg/taper/Greek-cap experiments, and fill-complete TCM-v2 accrual.

The audit must answer a narrower and harder question than “was the code merged?”:

> Do the current production seams, durable evidence, and operator controls support the claims now made about safety, economic truth, experiment readiness, and fleet activation—and what genuinely new residual outranks the existing backlog?

A low trade rate, zero executable suggestions, or a blocked fleet is not itself a defect. A correct system may reject every candidate or remain inactive.

---

# STEP 0 — REPRODUCIBLE GROUNDING, OWNERSHIP, AND PINNING

Before analysis:

1. Report:
   - effective model and subagent policy;
   - host UTC;
   - America/Chicago;
   - America/New_York;
   - DB `now()`;
   - broker clock, `is_open`, prior close, next open, and next close.

2. Resolve and report:
   - exact 40-character `origin/main` SHA;
   - current local HEAD and branch;
   - `git status --short`;
   - all worktrees;
   - latest main CI;
   - deployed SHA, status, and container start for BE, worker, and worker-background;
   - FE separately;
   - all open PRs touching audit, backlog, ledger, policy/fleet, risk, cost, model-review, funnel, market-data, or UI territory.

3. Expected issuance state to verify, never assume:
   - `main = fdf5b55cb9f9dc5391f191df3e3876a3c5ded355`;
   - PR #1296 added end-to-end scorable-outcome join readiness and documentation;
   - PR #1299 extended TCM-v2 realized accrual to the complete fill inventory, observe-only;
   - Railway status for all four services was reported successful at issuance;
   - `docs/backlog.md`, `audit/ledger.md`, and `CLAUDE.md` may lag #1296/#1299 because those two merges followed the last docs-final PR;
   - open PR #1298 records owner ratifications but activates nothing;
   - open PR #1300 adds a signed, read-only Monday evidence reader and is not part of the pinned baseline unless merged before audit execution;
   - active Palette/Jules PRs may still own UI files.

4. If `origin/main` advanced:
   - list every intervening commit and changed file;
   - classify each as docs/test/production/migration/control;
   - identify overlap with the ten audit areas;
   - pin one immutable observed SHA for the entire report;
   - do not move the pin later because main advances again.

5. Preserve all tracked, modified, untracked, case-collision, and local-operator artifacts byte-for-byte. Do not stash, reset, clean, checkout broadly, install, build, migrate, deploy, change config, trigger jobs, or touch broker state.

6. Recheck `origin/main` at report end. Any movement is an out-of-scope delta unless explicitly re-pinned before analysis begins.

Output the immutable code basis, documentation-write basis, deployment basis, and runtime-observation window before proceeding.

---

# EVIDENCE AND CLAIM CONTRACT

Use exactly these proof labels:

- `VERIFIED-CODE` — production dataflow proven at the pinned SHA.
- `VERIFIED-TEST-REACH` — a test drives the actual production seam and relevant external/serialization boundary.
- `VERIFIED-GITHUB` — current PR/merge/ref metadata directly read.
- `VERIFIED-CI` — current-head workflow result directly read.
- `VERIFIED-DEPLOYMENT` — running service SHA/status/start directly read.
- `VERIFIED-DB` — direct read-only database evidence with query basis and timestamp.
- `VERIFIED-BROKER` — direct broker account/order/position/fill evidence with timestamp.
- `ATTESTED-RUNTIME` — packet/operator evidence that could not be independently queried in this run.
- `INFERRED` — reasoned conclusion with premises stated.
- `RUNTIME CHECK — NOT RUN` — exact external read needed to confirm/refute.
- `NOT-PROVEN` — no honest narrower verified claim is available.
- `REJECTED` — tested claim is false.
- `DUPLICATE` — already owned by backlog/ledger with no stronger mechanism or dependency.
- `SUPERSEDED` — an older claim has been replaced by a newer verified contract.

Never upgrade attestation to verification. Never call a merge deployed, a deployment naturally exercised, a persisted suggestion executable, a `live_eligible` row broker-live, or a shadow outcome live evidence.

## Source precedence

For runtime truth:

1. code defines intended mechanics;
2. Supabase records application events and durable evidence;
3. Railway identifies running code and effective process state;
4. Alpaca is authoritative for broker positions, orders, fills, and options buying power.

A disagreement between sources is the finding. Do not average it away.

## Basis and unit rule

Every EV, score, PoP, cost, risk, P&L, and sample-size statement must name:

- basis: `raw | calibrated | proposed-v2 | executable | realized | unknown`;
- unit: `per-leg | per-contract | position-total | account-total | event-count | unknown`;
- cohort/routing: `broker-live | live-eligible | shadow | internal-paper | policy-lab | unknown`;
- known-at timestamp or reason it is unavailable.

Unknown basis or cohort is a finding when the number drives a decision.

## Per-finding schema

For every retained or rejected candidate report:

1. ID, area, severity (`CRITICAL/HIGH/MED/LOW/NOTE`);
2. exact claim tested;
3. proof label;
4. exact production seam (`path:symbol`, plus pinned-SHA line range where practical);
5. full producer → transport → durable sink → consumer dataflow;
6. existing tests and whether they reach the real seam;
7. natural runtime evidence or exact missing runtime check;
8. impact on safety, economic truth, evidence quality, or operator control;
9. backlog interaction (`NEW | EXTENDS-X | DUPLICATES-X | CONFLICTS-X | SETTLED`);
10. whether a recommendation changes measurement or loosens/tightens control;
11. smallest honest operator decision or implementation boundary;
12. falsifier.

No line-number-only finding. Trace the consumer and failure semantics.

---

# PREDECESSOR AND NON-REDISCOVERY BAR

The ledger is exclusion memory. Read `audit/ledger.md`, `docs/backlog.md`, `CLAUDE.md`, all v1.1–v1.5 audit files, and the dated 2026-07-18/19 results before filing anything.

The following are settled or deliberately dark unless current evidence proves a contradiction, bypass, drift, or newly reachable consumer:

- options-level entry preflight; closes/shadow exemption;
- lifecycle typed degradation for entries;
- F-BAN phantom feature removal;
- F-CREDIT-SIGN code fix and fingerprinted historical correction;
- broker/account reconciliation and fail-closed options-buying-power reads;
- H7 parent plus mandatory typed subreason;
- candidate terminal dispositions and quote/OI provenance schemas;
- source-label correction and A5-2 job-origin provenance;
- decision `git_sha` and ranking-cost/code-sha writer coverage;
- canonical max loss, payoff-capped stress, signed Greek aggregation, and D3 ratio-aware full-contract counts;
- tier taper, Greek caps, single-leg experiment, OI floors, and TCM-v2 remain dark/observe-only unless explicitly activated later;
- ⑤ terminal-distribution foundation, scan-time spot/IV/delta capture, scorable-outcome join readiness, and event-driven review wiring;
- policy registry with 50 approved, hash-valid designs; fleet provisioned inactive;
- E19-2B preregistered protocol remains execution-gated;
- test honesty, SQL-mirror parity, and fork/collection reliability sweeps;
- the three evidence/fleet migrations and later registry/H7 migrations are applied and must never be reapplied;
- a correct no-trade outcome is not a failure.

A contradiction to any item above receives high priority. Merely restating it is `DUPLICATE`.

Standing question for every claim:

> Does the test drive the production seam, does the instrument cross the real boundary into a durable sink, and does a current production consumer actually use the value?

---

# INSTRUMENT-INTEGRITY — MANDATORY FIRST PASS

Before trusting outcomes, grade the instruments that produce them.

At minimum trace:

- deployment/code SHA and container-start identity;
- job origin, parent/retry identity, result status, hidden error/partial fields, and end markers;
- decision context/tape completeness and terminal manifests;
- candidate terminal disposition uniqueness, retries, supersession, and typed H7 details;
- quote/OI provenance source, timestamps, 429/fallback status, selected/rejected linkage, retention, and redaction;
- stage-time spot, IV, delta, Greek coverage, and known-at semantics;
- TCM frozen/v2 stamps, multi-fill inventory, version segregation, and realized joins;
- event-driven model-review fingerprinting and exactly-once behavior;
- fleet policy hash validation, dry-run manifest, provisioning/activation receipts, and state transitions;
- alert egress/receipts, critical/high baseline, direct-insert relay, and quiet-window semantics;
- tests that mock below the boundary they claim to protect;
- docs/backlog/ledger claims that are stale relative to current main.

Deliver:

`instrument | emitter | boundary | durable sink | reader/consumer | test reach | natural proof | integrity verdict | limitation`

An instrument without a durable, queryable sink cannot support a historical claim.

---

# MODE — THREE PASSES FOR EACH AREA

For every A1–A10 area execute:

### Pass 1 — State and exclusion integrity

Verify the current state, settled conditions, dark/live status, ownership, and code/docs/runtime disagreements.

### Pass 2 — Seam, test-reach, and instrument integrity

Trace production inputs, outputs, failure semantics, transport, durable sink, consumer, and origin-injected tests.

### Pass 3 — Adversarial dependency graph and decision value

Construct the strongest counterexample, determine reachability and blast radius, deduplicate, identify the smallest honest boundary, and specify a falsifier. Do not implement.

For dormant or sample-gated areas, use `DEFERRED-DORMANT` or `DEFERRED-SAMPLE` rather than manufacturing a finding.

---

# THE TEN AREAS — KEEP THESE TEN AND NO OTHERS

## A1 — ECONOMIC EDGE, PROFITABILITY, AND COMPARABLE UNITS

Audit whether the system can make a coherent economic claim across structures and cohorts.

Mandatory checks:

- raw vs calibrated vs proposed-v2 vs realized EV/cost bases;
- credit-vertical baseline EV identity and ⑤ challenger separation;
- debit/condor payoff integration against one terminal distribution;
- TCM-v1 versus TCM-v2 commission, slippage, spread, quantity, and routing units;
- PR #1299 complete fill inventory, first-side-flip boundary, zero-quantity handling, version mixing, and H9 unavailable semantics;
- realized-cost study selection bias and whether all eligible fills/positions enter;
- broker-live profitability, shadow profitability, and thesis-hit rates kept separate;
- minimum-edge and calibration interactions without treating low trade rate as failure;
- whether any report compares incompatible per-contract and position-total values;
- promotion packets and owner-ratified sample thresholds, if merged.

Primary adversarial question:

> Can the same candidate or closed position be ranked as profitable under one hidden basis and unprofitable under another, while the operator-facing report omits the difference?

## A2 — LOSSES, EXITS, CLOSES, AND POSITION CUSTODY

Audit the full loss path from open structure to terminal custody.

Mandatory checks:

- F-CREDIT-SIGN historical correction idempotency and downstream learning/policy repair;
- broker-ack guard versus internal/shadow close paths;
- close-limit direction, signed/unsigned fill magnitude, cash ledger, synthetic legs, and realized P&L agreement;
- re-arm, cancellation, retry, client-order identity, and duplicate-close prevention;
- partial fills, partial closes, residual quantities, and custody near expiry;
- assignment/exercise handling and unsupported strategy behavior;
- close-fill-gap provenance and multi-fill cost joins;
- canonical max-loss and payoff stress versus actual close outcomes;
- terminal reason, price basis, and thesis outcome propagation;
- no stop loosening based only on adverse outcomes.

Primary adversarial question:

> Can any credit/debit structure become economically or operationally “closed” in one subsystem while quantity, cash, order, or broker custody remains open elsewhere?

## A3 — STRATEGY FUNNEL, VIABLE SET, AND ACCOUNT AFFORDABILITY

Audit every current strategy from selector attempt through broker submission.

Mandatory checks:

- production selector pools for four verticals, iron condor, and dark single-leg experiment;
- current policy opt-ins and proof that single-leg remains shadow-only and broker-unsubmittable;
- `should_submit_to_broker` at every real submission seam;
- H7 round-trip BP, quality, sizing, risk-budget, and account-capacity subreasons;
- candidate terminal disposition coverage through allocator/ranker/persistence/stage/broker;
- small-account one-contract granularity, structure width, debit/credit collateral, and close-BP assumptions;
- spread-width, execution-cost, earnings, IV-history, liquidity, and model-economics losses kept distinct;
- blocked `NOT_EXECUTABLE` rows versus pending/executable UI/API semantics;
- condor tilt versus selector bias, account BP, and quote liquidity;
- no symbol/strategy expansion recommended as a substitute for honest economics.

Primary adversarial question:

> For every selected candidate that disappears, is there one durable, truthful final disposition—and could a narrower or different structure have passed without weakening a gate?

## A4 — RISK, SIZING, AND CANONICAL POSITION TRUTH

Audit the canonical representation and every current risk consumer.

Mandatory checks:

- signed leg direction, explicit ratios, structure quantity, multiplier, and non-1:1 behavior;
- D2/D3 fixes across `check_greeks`, stress, and any remaining parallel aggregation;
- exact max loss, unbounded/malformed structures, payoff-capped stress, and raw phantom preservation;
- stage-time Greek provenance, coverage, sign mismatch, nonfinite/missing handling;
- Greek-cap counterfactuals, reference-cap derivation, headroom, would-block/would-size output, and zero live enforcement;
- continuous tier-taper monotonicity, hysteresis, SHOCK ceiling, and dark dual-run status;
- current micro/small tier boundary and whether declining equity can raise risk on the live path;
- risk-budget family mapping, global envelope, utilization, quantity, and per-trade ceilings;
- canonical position versus broker-position reconciliation;
- activation packets and rollback assumptions before any risk control is armed.

Primary adversarial question:

> Does any live or report consumer still compute exposure from a parallel, ratio-blind, sign-blind, or placeholder representation rather than the canonical position?

## A5 — MARKET DATA, LIQUIDITY, OI, AND KNOWN-AT PROVENANCE

Audit the entire market-data truth layer and candidate-leg evidence.

Mandatory checks:

- Alpaca primary, pagination, rate limits, retries, Polygon fallback, and source labels;
- quote timestamp, request/receive timestamps, age, stale/crossed/zero-bid flags, and spread denominator;
- exact-leg OI and volume source, freshness, missing/negative/zero semantics;
- hypothetical OI floors remain counterfactual and cannot affect scanning;
- IV, delta, and spot capture at scan/stage with status/source/known-at fields;
- source-label repair and any carrier-versus-persisted naming difference;
- candidate/quote linkage, anomaly retention, volume caps, sampling, and dropped-row counters;
- data unavailable versus legitimate zero;
- post-close reconstruction limits and whether PR #1300, if merged, reads all sinks honestly;
- sensitive-value scrubbing.

Primary adversarial question:

> Can a candidate verdict be attributed to a quote, OI value, or source that was stale, incomplete, sampled away, or relabeled after the decision?

## A6 — EXECUTION, BROKER, ORDERS, AND TRANSACTION COSTS

Audit the last mile from stage eligibility through fill and reconciliation.

Mandatory checks:

- effective options level, approved level, preflight cache/failure behavior, and close exemptions;
- entry quote validation, round-trip cost gate, utilization gate, lifecycle state, and submission ownership;
- all `should_submit_to_broker` call sites and bypasses;
- paper/shadow/live routing distinctions;
- broker submit/retry/terminal permission errors/client-order IDs;
- pending, staged, submitted, partial, filled, rejected, cancelled, and manual-review taxonomy;
- order synchronization, ghost/orphan/stuck-open/untracked-fill detection;
- TCM stamps on all fills and PR #1299 multi-fill completeness;
- realized commission availability by routing and mixed-routing abstention;
- broker positions/orders/cash/OBP reconciliation at the audit window.

Primary adversarial question:

> Can a path that is classified shadow, blocked, or unpriceable reach a broker submission—or can a broker fill fail to enter every durable cost, position, and learning sink?

## A7 — LEARNING, CALIBRATION, TERMINAL DISTRIBUTION, AND MODEL REVIEW

Audit the complete producer-to-consumer model-evidence chain.

Mandatory checks:

- live/shadow/internal outcome quarantine and execution-mode truth;
- corrected historical close data and no double correction;
- calibration epoch, sample count, segments, clamps, staleness, and apply ordering;
- ⑤ frozen baseline and challenger inputs, abstentions, provenance, and metrics;
- PR #1296 scorable-outcome join: suggestion → OPEN order markers → close → outcome → mapper → models → enqueue-once;
- scan-time spot source accepted by status rather than incorrectly source-gated;
- model-review fingerprint/idempotency, new-close edge trigger, and cohort separation;
- event-driven review remains observe-only and cannot mutate selector/ranker/gates/calibration;
- E19-2B protocol hash, minimum event threshold, stopping rules, and execution block;
- owner ratifications versus actual control state.

Primary adversarial question:

> Can a future close be labeled scorable, calibrated, or promotion-worthy using data that was captured after the decision, from the wrong cohort, from an incomplete marker, or from a duplicated event?

## A8 — FLEET, POLICY REGISTRY, AND EXPERIMENTAL DESIGN

Audit the versioned 50-policy fleet from registry to prospective activation.

Mandatory checks:

- policy canonical JSON, server-derived hash, immutability, approval, epoch, and lineage;
- exactly 50 approved unique policies and the 3-anchor/47-variant interpretability claim;
- provisioning state: fleet, slots, portfolios, capital, routing, receipts, and idempotency;
- binding manifest fingerprint and bijection of slot/policy/account/portfolio;
- replicated dry-run versus actual signed-route dry-run distinction;
- activation prerequisites, attestation, DB-time epoch, strict flag polarity, all-or-nothing transaction, and irreversible-in-place retirement model;
- zero active slots/bindings/activation receipts before authorization;
- single-leg opt-in policies versus current 0/50 state;
- E19-2B cohort/arm preregistration and distinct source-event unit;
- shared capital, cross-account recovery, or row-count-as-evidence leakage.

Primary adversarial question:

> Could one malformed, duplicated, unapproved, or mismatched policy bind during activation—or could a partial activation leave an economically inconsistent fleet?

## A9 — OPERATIONS, OBSERVABILITY, SECURITY, AND TEST REACH

Audit whether the system can detect and prove its own failures.

Mandatory checks:

- Sunday/nightly wrapper, fresh checkout, model identity, completion marker, transcript, manifest, and broker snapshot;
- scheduler heartbeat, expected jobs, duplicate/extra runs, origin taxonomy, retries, partial results, and stuck rows;
- `job_runs.status` schema and succeeded-with-errors truth;
- critical/high baseline, warning cadence, egress receipts, relay failures, and quiet-window semantics;
- deployment SHA/content equivalence, startup flag echo, worker disagreement, and recycle effects;
- replay/tape hash reader and unscheduled/operator-only tools;
- security dependencies, HMAC route tests, debug/auth configuration, secret scrubbing, and credential-class reporting;
- test pollution, collection order, real route overrides, SQL mirrors, and external boundary mocks;
- schema-absent typed no-op behavior versus silent evidence loss;
- open PR ownership and stale local artifacts.

Primary adversarial question:

> Can a job, writer, control, or audit report claim success while a substep failed, a dependency was mocked, the deployed SHA differed, or the evidence never reached its sink?

## A10 — PRODUCT/API, CALENDAR/CLOCK, AND GOVERNANCE

Audit the operator-facing truth and control lifecycle.

Mandatory checks:

- Compose/TradeInbox/dashboard labels for simulation, blocked, paper, live-eligible, submitted, and filled states;
- unsupported executable-looking strategies and arbitrary stage/execute endpoints;
- UI file ownership and whether unresolved Palette PRs block an honest fix;
- broker calendar, holidays, early closes, DTE/expiry, Friday-to-Monday scoring, timezone-aware timestamps, and DST;
- signed operator endpoints, dry-run/execute separation, and irreversible actions;
- owner decision packets, ratification PR #1298 if merged, and actual activation state;
- migration history versus repository filenames; never-reapply doctrine;
- `CLAUDE.md`, backlog, ledger, results reports, and current main reconciliation;
- open PR #1300 or successors: reader output must not become a control or manufacture evidence;
- stale docs, duplicate backlog ownership, runtime checks misfiled as builds, and settled items left active.

Primary adversarial question:

> Does any operator-facing surface, document, clock rule, or signed endpoint imply an ability or state that the production system does not actually possess?

---

# MANDATORY CROSS-AREA CANDIDATE CHECKS

Explicitly adjudicate these even if no area agent selects them:

1. **Current-docs lag after #1296/#1299** — determine whether backlog/ledger/CLAUDE omit or misstate scorable-join completeness or multi-fill TCM coverage.
2. **Fleet signed-route dry-run gap** — distinguish replicated readiness from an actual authenticated dry-run through the production route; do not activate.
3. **Activation irreversibility** — prove rollback/retire semantics and all-or-nothing behavior before any recommendation.
4. **Single-leg dark guarantee** — trace all real submit sites and registry opt-in lookup; current policies must not emit live-submittable singles.
5. **H7 taxonomy integrity** — query natural rows if any; parent/subreason/sizing outcome must agree with code and constraint.
6. **TCM-v2 stamp population and multi-fill selection** — determine whether natural post-#1278/1299 data is accruing and whether missing stamps are honest.
7. **Scorable outcome first natural row** — if none, grade `DEFERRED-SAMPLE`; do not trigger a close.
8. **Quote/OI evidence first natural rows** — verify source, timestamps, retention, and candidate linkage; no OI gate.
9. **Owner ratification versus activation** — a merged ratification document must not be treated as a flag, registry mutation, fleet activation, or model promotion.
10. **UI/API honesty** — continue to respect active file ownership; report the collision rather than editing around it.

---

# RUNTIME COMPANION EVIDENCE

Use read-only Supabase, Railway, Alpaca, and GitHub evidence where available. Re-ground clocks before materially separate runtime reads.

At minimum report:

- broker account status, equity/cash/OBP, options levels, positions, orders, and recent fills;
- current `entries_paused`, lifecycle states, progression phase, and effective control values from their true source;
- fleet/policy/slot/portfolio/binding/receipt counts;
- migration history for every relied-upon table/function;
- latest natural suggestion cycles, candidate dispositions, H7 details, quote/OI rows, stage markers, and TCM stamps;
- live/shadow outcome populations and newest scorable close;
- event-driven review jobs and fingerprints;
- latest nightly-wrapper result, manifest, and broker snapshot;
- critical/high alerts and materially noisy warning classes;
- current PR/CI/deployment truth.

Do not manually trigger scans, closes, replay, model review, fleet routes, or evidence jobs. No natural event means `INCONCLUSIVE` or `DEFERRED-SAMPLE`.

Never include secrets, tokens, account identifiers, credential fragments, or raw private payloads in the results document.

---

# FREE LOOK

After completing A1–A10, reserve one free-look pass. A free-look finding must:

- trace a production seam and current consumer;
- survive ledger/backlog deduplication;
- outrank an existing open item in risk or decision value;
- identify the smallest honest boundary and falsifier.

Limit promoted free-look findings to the strongest two. Record weaker observations in the appendix as `NOTE`, `DUPLICATE`, or `NOT-PROVEN`.

---

# REQUIRED RESULTS ARTIFACT

Create:

`docs/review/external-full-audit-v1.6-results-2026-07-19.md`

The report must be self-contained and contain, in this order:

1. title, date, immutable code SHA, docs SHA, deployment SHA, and runtime window;
2. clock and market grounding;
3. current-state reconciliation, including intervening commits and open PR ownership;
4. evidence doctrine and limitations;
5. instrument-integrity table;
6. predecessor/non-rediscovery disposition table;
7. A1–A10 three-pass results, with no missing area;
8. mandatory cross-area candidate dispositions;
9. free-look findings;
10. ranked retained findings;
11. rejected, duplicate, superseded, and not-proven appendix;
12. runtime-only and sample-gated items;
13. exact backlog integration map;
14. owner decisions and natural falsifiers;
15. ten-area maturity scorecard;
16. files, symbols, queries, commands, and PRs inspected.

Every code finding cites an exact path/symbol at the pinned SHA. Every runtime claim names source, query basis, and timestamp.

---

# TEN-AREA SCORECARD

Score each area from 0–10 for **audit maturity**, not profitability:

- 0–2: uninstrumented or unsafe;
- 3–4: partial code with weak truth path;
- 5–6: implemented and tested, runtime or coherence gaps remain;
- 7–8: durable evidence and failure semantics largely complete;
- 9: repeated natural proof, coherent cross-area basis, no material open correctness defect;
- 10: reference ceiling.

Report both:

- `code/instrument maturity`;
- `natural runtime evidence maturity`.

Do not combine them into a single false-precision number without showing both components.

---

# BACKLOG AND LEDGER INTEGRATION

Before editing either canonical file, build:

`finding | severity | evidence | disposition | existing owner | new/extends/duplicate | priority | backlog section | ledger entry | operator decision | falsifier`

Rules:

- every retained finding appears once in the backlog;
- rejected/duplicate/superseded/not-proven claims appear in the results appendix and ledger exclusion memory where appropriate;
- a runtime falsifier is not a build slot;
- a dark feature is not live;
- an applied migration is never listed as pending apply;
- a merged owner decision is not an activated control;
- current open PR ownership is respected;
- no implementation, migration, config, broker, DB, fleet, or deploy change occurs in this audit lane.

Update `docs/backlog.md` and `audit/ledger.md` only with verified, deduplicated outcomes. Update `CLAUDE.md` only for stable doctrine/state pointers; do not embed mutable balances or transient counts.

---

# FINAL AUDIT VERDICT

Return:

- executive verdict;
- highest-severity current defect, or `NONE VERIFIED`;
- strongest evidence-quality gap;
- strongest economic-coherence gap;
- strongest operator-control gap;
- top three retained backlog deltas;
- top three owner decisions;
- exact natural falsifiers;
- whether fleet activation is `NOT_READY | READY_DRY_RUN_ONLY | READY_FOR_SEPARATE_AUTHORIZATION`;
- whether any live control loosening is recommended, with proof of the underlying error;
- explicit statement that no implementation or production mutation occurred.

End the completed results with:

`EXTERNAL FULL AUDIT v1.6 · TEN AREAS · READ-ONLY · NO CODE/DB/BROKER/DEPLOY/CONTROL CHANGE`
