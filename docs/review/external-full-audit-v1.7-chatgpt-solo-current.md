# EXTERNAL FULL AUDIT v1.7 — ChatGPT Solo Ten-Area Deep Dive

**Issued:** 2026-07-19  
**Expected immutable code baseline at issuance:** `353b930c4df5ecfbcd204896dbd5f968c60aa85f`  
**Mode:** ChatGPT solo; read-only code/runtime analysis; report findings in chat; stop without implementation or canonical integration.  
**Area 11 / self-extension slot:** EXCLUDED.

---

## Purpose

Audit the current repository after the v1.6 results, the nightly-runner HIGH repair, and the v1.6 remediation documentation merge. The audit must find only genuinely new defects, contradictions, newly reachable blast radii, or stronger mechanisms that are not already owned by `docs/backlog.md`, `audit/ledger.md`, `CLAUDE.md`, v1.1–v1.6 audit reports, dated review reports, or open remediation PRs.

A merged fix is not natural runtime proof. An open PR is not current-main behavior. A low trade rate, empty evidence table, inactive fleet, dark experiment, or blocked suggestion is not itself a defect.

---

## Absolute constraints

- ChatGPT performs the audit alone; no Claude/Fable/Opus/subagents.
- Pin one immutable `origin/main` SHA at audit start and do not move the pin.
- Read-only GitHub, code, CI, deployment, DB, and broker inspection only where available.
- No branch updates beyond this prompt file; no results file, backlog edit, ledger edit, code fix, test edit, migration, deployment, DB write, broker write, fleet action, env/config/flag/schedule change, or manual job trigger.
- Do not merge this prompt PR.
- Preserve operator/local artifacts; do not infer local state from GitHub.
- Never expose secrets, tokens, raw credentials, account identifiers, or private payloads.
- Stop after reporting the audit findings to the user.

Use proof labels:

`VERIFIED-CODE` · `VERIFIED-TEST-REACH` · `VERIFIED-GITHUB` · `VERIFIED-CI` · `VERIFIED-DEPLOYMENT` · `VERIFIED-DB` · `VERIFIED-BROKER` · `ATTESTED-RUNTIME` · `INFERRED` · `NOT-PROVEN` · `DEFERRED-SAMPLE` · `DUPLICATE` · `SUPERSEDED` · `REJECTED`.

---

## Step 0 — Grounding and pinning

Report:

- current UTC/date;
- immutable `origin/main` SHA;
- commits since issuance SHA, classified by docs/test/code/migration/control;
- latest main CI;
- BE, worker, worker-background, and FE status at the pin where visible;
- current open PRs touching any audit area;
- whether the market is open when runtime evidence is used;
- exact source limitations.

If main advances while the audit runs, treat it as an out-of-scope delta. Open remediation PRs are not part of current-main behavior, but may prove that a candidate is already flagged/owned.

---

## Non-rediscovery gate

Before promoting any finding, read and deduplicate against:

- `audit/ledger.md`;
- `docs/backlog.md`;
- `CLAUDE.md`;
- all external audit briefs/results v1.1–v1.6;
- `docs/review/v1.6-remediation-results-2026-07-19.md`;
- `docs/review/sunday-implementation-results-2026-07-19.md`;
- recent owner-decision, parallel-implementation, migration, recovery, and sprint reports;
- open PRs #1304, #1306, #1307, #1308, #1309, #1310 and any newer remediation PRs.

A candidate is retained only when it is:

1. new and unowned;
2. a stronger, materially different mechanism than an existing item;
3. a contradiction to a settled claim;
4. a newly reachable consumer/blast radius;
5. a defect in the evidence instrument that invalidates an existing decision.

Otherwise classify it `DUPLICATE`, `SUPERSEDED`, `REJECTED`, `NOT-PROVEN`, or `DEFERRED-SAMPLE` and do not spend a retained slot on it.

---

## Instrument-integrity first pass

Before trusting evidence, trace:

`emitter → boundary/transport → durable sink → reader/consumer → real test reach → natural proof`

Mandatory instruments:

- deployment/code SHA identity;
- job origin, status, hidden errors, partial classification, and terminal artifacts;
- nightly-runner durable completion contract after #1305;
- risk-basis arm evidence current-main state versus open #1306;
- candidate disposition and quote/OI provenance;
- stage-time spot/IV/delta/Greek capture;
- TCM-v1/v2/multi-fill realized joins;
- event-driven model review exactly-once behavior;
- fleet registry/provisioning/activation evidence;
- HMAC signed-task verifier and behavioral test reach;
- market calendar/session truth;
- alert egress and false-green/false-quiet risks;
- docs/backlog/ledger freshness.

---

## Three passes per area

For each A1–A10:

1. **State/exclusion integrity** — current state, dark/live status, ownership, contradictions.
2. **Seam/test/instrument integrity** — producer, transport, sink, consumer, failure semantics, real test reach.
3. **Adversarial dependency/value** — strongest counterexample, reachability, blast radius, smallest honest boundary, falsifier.

Use `DEFERRED-SAMPLE` rather than inventing a defect when runtime evidence is naturally absent.

---

# The ten areas

## A1 — Economic edge and comparable units

Check raw/calibrated/proposed-v2/realized bases, per-leg/per-contract/position/account units, TCM-v1/v2, multi-fill completeness, commission/slippage/spread decomposition, ranker-versus-realized overlap, credit-vertical EV identity, terminal-distribution consistency, calibration ordering, and operator-facing basis labels.

Primary question: can the same candidate/position look profitable under hidden incompatible bases while the report omits the difference?

## A2 — Losses, exits, closes, and custody

Check signed close fills, F-CREDIT-SIGN correction, close CAS/idempotency, partial fills/closes, re-arm/retry identity, broker acknowledgement, assignment/exercise, expiry custody, residual quantity, cash/ledger/P&L agreement, and close-cost joins.

Primary question: can any subsystem declare a position closed while broker/order/quantity/cash custody remains open or inconsistent?

## A3 — Strategy funnel and viable set

Trace selector through scanner, H7, allocator, ranker, persistence, staging, submission, and fills for all verticals, condors, and dark single-leg experiment. Check terminal dispositions, typed subreasons, account affordability, liquidity/cost/model losses, blocked versus executable truth, and submit-veto coverage.

Primary question: can a candidate disappear, advance, or appear actionable without one honest durable terminal disposition?

## A4 — Risk, sizing, and canonical position

Check canonical leg ratios, multipliers, max loss, payoff stress, signed Greeks, divisibility, Greek coverage, risk-basis shadow/arm evidence, utilization/RBE consumers, tier taper, cap counterfactuals, and fail-closed reads.

Primary question: can a malformed or partially covered structure produce a finite risk/Greek value that a current or future control could trust?

## A5 — Market data, liquidity, OI, and known-at provenance

Check Alpaca/Polygon fallback, 429 behavior, pagination, selected-leg quote provenance, timestamps, stale/crossed/zero quotes, exact-leg OI, observation date versus retrieval time, source labels, redaction, retention, and linkability to candidate decisions.

Primary question: can fallback or missing known-at data silently change a candidate verdict without a durable, source-specific explanation?

## A6 — Execution, broker, orders, and transaction costs

Check real submit seams, HMAC/operator routes, routing versus execution mode, duplicate submit prevention, options-level preflight, client-order identity, order reconciliation, broker truth, TCM stamps, fee provenance, and stage/submit/fill lifecycle.

Primary question: can an order be submitted, duplicated, or costed under a different route/model than the durable record claims?

## A7 — Learning, calibration, terminal distribution, and model review

Check cohort separation, corrected-history use, calibration floors/segments/order, scorable-outcome producer-consumer join, terminal-distribution inputs, abstention, event fingerprinting, exactly-once review, content changes under stable IDs, E19 protocol identity, and promotion gating.

Primary question: can a stale or changed outcome/model row evade re-review or cause a promotion decision on an incomparable cohort?

## A8 — Fleet, policy registry, and experimental design

Check immutable policy IDs/config hashes, 50-policy design, provisioning isolation, binding plan, activation gates, idempotency, irreversible transition/retire path, attestation, epoch identity, single-leg opt-in, and E19 comparability.

Primary question: can fleet activation bind a different policy/account plan than the dry-run manifest or create a partially activated state?

## A9 — Operations, observability, security, and test reach

Check #1305 runner current-main contract, local-versus-deployed distinction, completion artifacts, ping semantics, job statuses, hidden errors, HMAC production detection, nonce outage behavior, test skips/pollution, alert relay, secrets hygiene, and tracked-path/case-collision risks.

Primary question: can a failure mutate operator state or report green while the durable sink or security boundary failed?

## A10 — Product/API, calendar/clock, and governance

Check API/UI status truth, blocked versus executable labels, route exposure, calendar/holiday/early-close semantics, broker clock, DST, open-PR ownership, docs/backlog/ledger consistency, applied migration naming, owner-ratification versus activation, and stale doctrine.

Primary question: can the operator be shown an actionable state, schedule, or governance claim that current production mechanics do not support?

---

## Free-look

Allow at most two free-look retained findings. They must outrank existing work, have a traced production consumer or evidence-invalidating instrument, and survive the non-rediscovery gate.

---

## Required output in chat

1. immutable pin and source limits;
2. instrument-integrity summary;
3. one concise three-pass result for each A1–A10;
4. ranked genuinely new retained findings only;
5. duplicates/rejected/not-proven/deferred appendix;
6. exact evidence and falsifier for each retained finding;
7. direct statement of whether any retained finding outranks the active v1.6 remediation queue;
8. no implementation prompt unless explicitly requested later.

Stop after the report. Do not edit backlog, ledger, CLAUDE.md, or create a results PR.
