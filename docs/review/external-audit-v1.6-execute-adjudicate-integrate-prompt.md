# EXTERNAL AUDIT v1.6 — EXECUTE, ADJUDICATE, AND INTEGRATE

Run from `BrightBoost-Tech/options-trading-companion` with:

```bash
claude --model fable
```

## MODEL POLICY

```text
ORCHESTRATOR = fable
SUBAGENTS = opus
MAX_PARALLEL_OPUS = 5
```

- Stop unless the effective orchestrator is Fable: `BLOCKED_FABLE_MODEL_MISMATCH`.
- Every Agent/Task delegation explicitly uses `model=opus`.
- Opus agents audit, trace, test-read, and report only.
- Only Fable may create the audit results/docs branch, edit audit/backlog/ledger files, push, and open the final draft PR.
- No agent may implement code, apply a migration, alter config, deploy, trigger a job, mutate DB/broker/fleet state, merge, or spawn another agent.

---

# MISSION

Execute the authoritative specification:

`docs/review/external-full-audit-v1.6-current.md`

against one immutable current-state SHA, create the completed v1.6 results artifact, deduplicate findings against the canonical backlog and audit ledger, and leave all documentation changes in one draft PR for operator review.

The v1.6 brief is intentionally an audit specification, not completed results. The absence of a results file is expected input.

---

# ABSOLUTE CONSTRAINTS

Allowed writes only:

- `docs/review/external-full-audit-v1.6-results-2026-07-19.md`;
- `docs/backlog.md`;
- `audit/ledger.md`;
- `CLAUDE.md` only for stable doctrine/state pointers proven by the audit;
- documentation-consistency or structural tests, only when needed to keep the docs contract truthful;
- one dated audit-results draft PR and its title/body.

Prohibited:

- production-code changes;
- test changes outside docs-consistency/structural docs tests;
- migrations or SQL changes;
- DB writes;
- broker writes;
- fleet provisioning/activation;
- Railway/env/config/flag/schedule changes;
- manual scans, closes, model review, replay, evidence jobs, or retries;
- deploys;
- merges;
- edits to unrelated working-tree files;
- edits underneath an active PR owner without explicit conflict resolution.

Use the proof labels and per-finding schema from the v1.6 brief exactly.

---

# PHASE 0 — GROUND, PIN, AND PRESERVE

1. Report clocks:
   - host UTC;
   - America/Chicago;
   - America/New_York;
   - DB `now()`;
   - Alpaca clock/market state/next boundaries.

2. Report repository/runtime truth:
   - `origin/main` full SHA;
   - current local branch/HEAD/status/worktrees;
   - main CI;
   - BE/worker/worker-background deployed SHA/status/start;
   - FE separately;
   - broker account status, positions, open orders;
   - current critical/high alert baseline.

3. Expected issuance baseline is:

   `fdf5b55cb9f9dc5391f191df3e3876a3c5ded355`

   If main moved, inspect every intervening commit/file and pin one observed SHA. Do not silently move the pin later.

4. Fetch open PR ownership. At issuance, #1298 and #1300 were open and UI files remained heavily Palette/Jules-owned; current GitHub wins.

5. Preserve the operator checkout byte-for-byte. Create an isolated audit worktree/branch from the pinned SHA.

6. Output:

   `immutable code basis | docs-write basis | deployment basis | runtime window | ownership blockers`

Stop only for a real ownership collision, unreviewed code-basis ambiguity, non-flat broker incident, mixed deployment, or new unexplained critical/high alert. A docs-only or non-overlapping main delta is not automatically a blocker.

---

# PHASE 1 — SOURCE, PREDECESSOR, AND LEDGER CLASSIFICATION

Read completely:

- `docs/review/external-full-audit-v1.6-current.md`;
- v1.1–v1.5 briefs/results;
- `docs/backlog.md`;
- `audit/ledger.md`;
- `CLAUDE.md`;
- 2026-07-18/19 results, owner packets, specs, and migration reports;
- current open PRs touching any audit area.

Classify the v1.6 source as `AUDIT_BRIEF_ONLY` and state:

> The v1.6 current file is the authoritative ten-area audit specification. This run is executing it and producing the completed results artifact.

Build a non-rediscovery map before delegating:

`settled claim | current owner/PR | reopen condition | audit areas | duplicate wording to avoid`

A contradiction or newly reachable consumer may reopen an item. Mere restatement is duplicate.

---

# PHASE 2 — INSTRUMENT-INTEGRITY PASS

Before auditing outcomes, trace every instrument listed in the brief.

Create:

`instrument | emitter | transport/serialization boundary | durable sink | reader/consumer | test reach | natural proof | verdict | limitation`

Required instruments include deployment identity, job origin/result truth, decision tapes/manifests, candidate dispositions/H7 details, quote/OI provenance, stage markers, TCM stamps/multi-fill inventory, event-driven model review, fleet receipts/state, alerts/egress, and docs-versus-main reconciliation.

Do not use a metric or row population later unless its instrument passes or its limitation is carried into every claim.

---

# PHASE 3 — EXECUTE THE TEN AREAS

Delegate the ten areas across at most five Opus agents. Give each agent exactly two areas and the shared proof/non-rediscovery contract.

Suggested assignment:

- Agent 1: A1 economic edge + A6 execution/costs;
- Agent 2: A2 exits/custody + A4 risk/canonical position;
- Agent 3: A3 strategy funnel + A5 market data/OI;
- Agent 4: A7 learning/models + A8 fleet/policies;
- Agent 5: A9 operations/security + A10 product/clock/governance.

Each agent must execute all three passes and return:

`Area | Pass 1 state/exclusion | Pass 2 seam/test/instrument | Pass 3 adversarial/dependency | retained gaps | rejected/duplicate gaps | priority | backlog target | falsifier`

Requirements:

- no missing area;
- exact pinned-SHA paths/symbols;
- producer-to-consumer trace;
- test-reach assessment;
- runtime proof or exact runtime check;
- deduplication against ledger/backlog;
- `DEFERRED-DORMANT` or `DEFERRED-SAMPLE` when appropriate;
- no implementation suggestion that bypasses the brief’s control doctrine.

Fable centrally reviews every agent claim and rejects unsupported upgrades.

---

# PHASE 4 — MANDATORY CROSS-AREA CHECKS AND FREE LOOK

Execute all ten mandatory candidate checks in the brief even when area agents do not retain them.

Then run one free-look pass. Promote at most two free-look findings, and only when each:

- traces a current production seam and consumer;
- survives deduplication;
- outranks an existing open item;
- has a smallest honest boundary and falsifier.

Record all other observations as `NOTE`, `DUPLICATE`, `SUPERSEDED`, `REJECTED`, or `NOT-PROVEN`.

---

# PHASE 5 — READ-ONLY RUNTIME ADJUDICATION

Use Supabase, Railway, Alpaca, and GitHub read-only evidence where available. Re-ground clocks before materially separate reads.

At minimum adjudicate:

- current broker/account/book truth;
- fleet/policy/slot/portfolio/binding/receipt state;
- latest natural candidate disposition/H7/quote/OI/stage-marker/TCM evidence;
- live versus shadow outcomes and newest scorable close;
- event-driven model-review jobs/fingerprints;
- latest nightly-wrapper completion;
- critical/high alerts and materially noisy warning classes;
- current deployment/CI/open PR state.

Do not trigger missing evidence. No natural event is `INCONCLUSIVE` or `DEFERRED-SAMPLE`.

Never expose secrets, account identifiers, or credential-shaped values in the report.

---

# PHASE 6 — CREATE THE COMPLETED RESULTS

Create:

`docs/review/external-full-audit-v1.6-results-2026-07-19.md`

Follow the exact ordered structure required by the brief, including:

- immutable bases and runtime window;
- current-state reconciliation;
- instrument-integrity table;
- predecessor/non-rediscovery table;
- A1–A10 results;
- cross-area checks;
- free look;
- ranked findings;
- rejected/duplicate/superseded/not-proven appendix;
- runtime/sample gates;
- integration map;
- owner decisions/falsifiers;
- dual-component ten-area scorecard;
- files/symbols/queries/PRs inspected.

Every retained finding must have a precise code seam and a durable evidence path or explicit runtime limitation.

---

# PHASE 7 — ADJUDICATION MATRIX AND CANONICAL INTEGRATION

Before editing canonical docs, build:

`finding | severity | proof | disposition | existing owner | new/extends/duplicate | priority | backlog section | ledger disposition | owner decision | falsifier`

Rules:

- each retained build gap appears exactly once in `docs/backlog.md`;
- runtime-only checks remain in ledger pending lists, not the build queue;
- duplicate/rejected/superseded claims are preserved as exclusion memory;
- applied migrations are never called pending;
- dark features are never called live;
- ratified decisions are not called activated controls;
- open PR ownership is respected;
- #1296/#1299 documentation lag is reconciled if still present;
- no code, migration, control, or production state changes.

Update:

- `docs/backlog.md` with only verified retained deltas;
- `audit/ledger.md` with one v1.6 audit entry plus exclusion memory;
- `CLAUDE.md` only when a stable doctrine/state pointer is wrong or missing.

Run the current docs consistency suite. Add only structural assertions, not transient runtime counts.

---

# PHASE 8 — DRAFT PR AND FINAL VALIDATION

1. Confirm the diff contains only the allowed audit/docs files and optional docs tests.
2. Run `git diff --check` and docs tests.
3. Re-fetch main; report any out-of-scope movement.
4. Push one branch and open one **draft** PR.
5. PR title:

   `docs(audit): external full audit v1.6 — ten-area current-state results`

6. PR body must include:
   - pinned SHA;
   - runtime window;
   - retained/duplicate/rejected/not-proven counts;
   - highest-severity finding;
   - files changed;
   - tests;
   - explicit read-only/no-production-change statement.

7. Do not merge or deploy.
8. Preserve the operator worktree and report its start/end inventory hash.

---

# FINAL RESPONSE CONTRACT

Return:

A. model and clocks  
B. immutable code/docs/deployment bases  
C. ownership and main-movement reconciliation  
D. instrument-integrity verdict  
E. A1–A10 summary table  
F. mandatory candidate dispositions  
G. retained findings ranked  
H. duplicate/rejected/superseded/not-proven counts  
I. ten-area maturity scorecard  
J. backlog/ledger/CLAUDE changes  
K. results file and draft PR  
L. tests and CI state  
M. owner decisions and natural falsifiers  
N. fleet readiness classification  
O. explicit safety statement

End exactly:

`EXTERNAL FULL AUDIT v1.6 · FABLE ORCHESTRATOR · OPUS AUDIT AGENTS · TEN AREAS · DRAFT DOCS PR · NO CODE/DB/BROKER/DEPLOY/CONTROL CHANGE`
