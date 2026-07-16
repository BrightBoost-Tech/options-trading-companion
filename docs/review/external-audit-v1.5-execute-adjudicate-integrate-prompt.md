# EXTERNAL AUDIT v1.5 — EXECUTE, ADJUDICATE, AND INTEGRATE

You are operating in the `options-trading-companion` repository.

The file added by PR #1207, `docs/review/external-full-audit-v1.5-current.md`, is intentionally the **audit specification/brief**, not a completed reviewer-results document. Do **not** stop because a separate results file is absent. The purpose of this run is to:

1. execute that v1.5 audit specification against the pinned repository and available read-only runtime evidence;
2. create the missing v1.5 results document;
3. adjudicate the verified results into the canonical backlog and ledger through PR #1205;
4. leave all changes in a draft PR for operator review.

The absence of a pre-existing v1.5 results file is expected input, not an error or blocker.

## ABSOLUTE OPERATING CONSTRAINTS

This is an audit-and-documentation lane.

Allowed writes:

- the existing PR #1205 branch, expected to be `docs/reconcile-2026-07-14-merges`;
- a new audit-results file under `docs/review/`;
- `docs/backlog.md`;
- `audit/ledger.md`;
- documentation-consistency tests already owned by PR #1205;
- PR #1205 title/body, if needed to state the expanded scope honestly.

Prohibited:

- no production-code changes;
- no builds or implementation fixes;
- no migrations;
- no config, environment-variable, schedule, flag, gate, stop, threshold, sizing, entry, exit, ranking, or broker-control changes;
- no DB writes;
- no broker writes;
- no manual job triggers, retries, cancels, submissions, or closes;
- no deploys;
- no merges;
- do not modify PR #1203, PR #1204, or their owned files;
- do not modify any unrelated user-owned working-tree files;
- leave PR #1205 in DRAFT state.

Every proposed code change is an operator decision and must be recorded only as backlog/ledger text.

Use evidence labels precisely:

- `VERIFIED-CODE`
- `VERIFIED-MERGE`
- `VERIFIED-CI`
- `VERIFIED-RUNTIME`
- `INFERRED`
- `NOT-PROVEN`
- `REJECTED`
- `SUPERSEDED`
- `DUPLICATE`

Never promote inference to verification.

---

## STEP 0 — REPRODUCIBLE GROUNDING AND OWNERSHIP

Before reading or writing findings:

1. Ground and report:
   - host UTC;
   - America/Chicago;
   - America/New_York;
   - DB `now()`;
   - broker clock and `is_open`;
   - next market open/close.

2. Fetch and report current GitHub truth:
   - `origin/main` SHA;
   - PR #1205 state, draft status, head SHA, base SHA, mergeability, files, and CI;
   - PR #1203 and #1204 states, heads, and owned files;
   - whether any other open PR owns `docs/backlog.md`, `audit/ledger.md`, the v1.5 audit files, or PR #1205's consistency test.

3. Expected starting facts, which must be verified rather than assumed:
   - PR #1207 added `docs/review/external-full-audit-v1.5-current.md` to main;
   - PR #1207 was documentation-only;
   - the production-code baseline relevant to the audit is `bef2cdd` or code-equivalent descendants;
   - PR #1205 was last reported at head `7e27b9b`, but current refs win if it has moved;
   - PR #1203 owns `packages/quantum/policy_lab/fork.py` and its F-A9-5 test territory;
   - PR #1204 owns canonical-position-model territory.

4. If `origin/main` or PR #1205 moved:
   - inspect the complete delta;
   - continue if movement is documentation-only or non-overlapping;
   - rebase PR #1205 cleanly if necessary and safe;
   - stop with `BLOCKED_SHA_OR_OWNERSHIP_COLLISION` only for a real code-basis change, file collision, unresolved conflict, or ambiguous ownership.

5. Preserve all unrelated tracked, modified, untracked, and case-collision artifacts byte-for-byte.

Output the exact immutable code basis and the exact documentation-write basis before proceeding.

---

## PHASE 1 — CLASSIFY THE v1.5 SOURCE CORRECTLY

Read `docs/review/external-full-audit-v1.5-current.md` completely.

Classify it as one of:

- `COMPLETED_RESULTS`
- `AUDIT_BRIEF_ONLY`
- `MIXED_BRIEF_AND_RESULTS`

A completed results document must contain actual adjudicated dispositions—not merely instructions—for:

- E1–E20;
- W1–W5;
- A1–A10 across the required passes;
- instrument-integrity findings;
- code citations or traced seams;
- retained and rejected findings;
- ranked deltas and falsifiers.

If it is `AUDIT_BRIEF_ONLY`, that is expected. State:

> The PR #1207 file is the authoritative v1.5 audit specification. This run is executing it and producing the missing results artifact.

Search the repository and relevant local audit locations for a separate completed v1.5 output. If one exists, compare it with the brief and use it as evidence after verifying its provenance. If none exists, **continue by executing the brief**. Do not return `BLOCKED_AUDIT_SOURCE_MISSING` merely because results have not been generated yet.

---

## PHASE 2 — EXECUTE THE FULL v1.5 AUDIT

Follow the ten areas and all E/W/A identifiers in the uploaded v1.5 specification exactly. Keep all ten areas; do not replace them with a different audit taxonomy.

Audit the immutable production-code basis, plus current merged state where relevant. Use `git show <pinned-sha>:<path>` or an isolated read-only worktree so a stale local checkout cannot contaminate conclusions.

### 2A. Instrument-integrity pass

Verify whether the evidence-producing instruments themselves are truthful before relying on their output. At minimum examine:

- tape completeness and blob persistence;
- job-result error propagation;
- current-run versus stored-population distinctions;
- execution-mode versus routing-mode distinctions;
- raw versus calibrated EV basis;
- shadow, paper, and broker-live cohort separation;
- broker-truth reconciliation;
- timestamps, quote age, and known-at semantics;
- `decision_runs.git_sha` provenance;
- any logger, counter, or headline that can claim success while suppressing a partial/failure.

For each instrument, report:

`instrument | source seam | claim it supports | integrity verdict | evidence | limitation`

### 2B. E1–E20 dispositions

For every E1–E20 item from the brief, produce:

`ID | exact claim | code/runtime seam | evidence label | verdict | backlog interaction | operator decision | falsifier`

Allowed verdicts:

- `CONFIRMED-NEW`
- `CONFIRMED-EXTENDS-EXISTING`
- `PARTIAL`
- `DUPLICATE`
- `SUPERSEDED`
- `REJECTED`
- `NOT-PROVEN`

No missing rows. If the evidence does not support a claim, use `NOT-PROVEN`; do not fill gaps with assumptions.

### 2C. W1–W5 dispositions

For every W1–W5 item, trace the current implementation and report:

`ID | intended invariant | current code path | durable identity | retry behavior | consumer | present coverage | residual defect | disposition`

Pay special attention to the already observed F-WINDOW naming collision:

- #1198 repaired INFO delivery/handler configuration;
- it did not necessarily add all decision-site heartbeat coverage;
- it did not necessarily create one durable cross-job cycle identity;
- do not mark all of F-WINDOW-1 closed merely because logging now emits.

If confirmed, recommend retiring the ambiguous identifier and splitting the residual into clearly named coverage and identity items. Do not build them in this lane.

### 2D. A1–A10, all required passes

For each A1–A10 area in the v1.5 brief, execute every required pass and report:

1. **State/exclusion integrity** — whether the area is still earning, stale, duplicated, or contradicted by current state.
2. **Seam trace** — exact production paths, inputs, outputs, failure semantics, and consumers.
3. **Adversarial disposition** — the strongest counterexample, whether it reproduces, blast radius, priority, and falsifier.

Use this schema for every area:

`Area | Pass 1 | Pass 2 | Pass 3 | retained gap | rejected gap | priority | backlog target`

### 2E. Free-look pass

After completing the prescribed ten areas, perform the brief's free-look pass. A free-look finding must beat existing retained work on value/risk and must survive deduplication. Keep speculative observations in the results report but do not promote them into the backlog without a traced production seam.

### 2F. Runtime companion evidence

Use available read-only DB, broker, Railway, and GitHub evidence to adjudicate code findings where runtime truth is material. Re-ground clocks before each materially separate runtime read.

Reconcile, rather than blindly copy, these previously reported facts:

- #1200 natural live observation occurred on 2026-07-15: a calibrated `edge_below_minimum` SOFI source produced two `shadow_prerejection_fork` observational clones; both remained `NOT_EXECUTABLE`; executor processed zero; broker remained flat; normalized per-contract RAeV matched across cohort sizes.
- #1201 calibration falsifier reportedly passed.
- #1201 thesis headline/runtime census reportedly passed or is pending depending on current time; grade from current evidence.
- decision tapes after #1199 reportedly have `tape_integrity='complete'` with blobs present.
- `decision_runs.git_sha` reportedly remains `unknown` because the worker lacks the environment stamp.
- current live outcome population was last reported as eight broker-live outcomes, 1W/7L; verify before using.
- routing mode is not execution mode; never label `live_eligible` as broker-live.
- shadow outcomes and internal fills do not prove executable live P&L.

### 2G. Mandatory candidate checks

Explicitly verify and adjudicate these candidates even if the brief does not phrase them identically:

1. **F-MIDDAY-POSITION-READ-FAILOPEN**
   - trace `services/workflow_orchestrator.py` around the midday open-position fetch;
   - determine whether DB failure and legitimate flat book both become `[]`;
   - trace all consumers: open-position count, allocator/envelope, pre-entry risk, concurrency, and job truth;
   - compare with the sentinel class fixed by #1195;
   - if confirmed, classify as a fail-open entry-path safety defect and deduplicate before filing.

2. **Internal-fill close-price sign contract**
   - inspect `paper_exit_evaluator.py`, especially `_select_internal_fill_price` and all consumers of the returned value;
   - determine whether signed executable marks can be double-negated for credit structures;
   - distinguish shadow-only accounting distortion from broker-live exposure;
   - identify any broker-ack guard that limits blast radius;
   - do not claim live exposure without a reachable live path.

3. **GIT-SHA-DECISION-PROVENANCE**
   - confirm whether `decision_runs.git_sha` is unstamped;
   - distinguish missing observability from wrong deployment identity.

4. **F-SHADOW-CAPITAL-PARITY / F-POLICY-CAPITAL-FALLBACK**
   - distinguish cohort-policy sizing against a deliberate shadow baseline from a latent `... or 100000` fabrication;
   - state which paths are fail-closed and which are not;
   - deduplicate with #1200 findings and PR #1203 ownership.

5. **Prequential operationalization**
   - verify whether `prequential_validator` has any production caller;
   - classify it as an operator study tool or an unwired observe-only capability;
   - do not schedule it in this lane.

6. **Option-liquidity freshness/prune provenance**
   - reconcile with the universe-census items already added to PR #1205;
   - avoid duplicating the OI-floor extension, liquidity-freshness/provenance item, funnel truth pack, or small-tier width rider.

---

## PHASE 3 — CREATE THE ACTUAL v1.5 RESULTS ARTIFACT

Create:

`docs/review/external-full-audit-v1.5-results-2026-07-15.md`

Do not overwrite or rename `docs/review/external-full-audit-v1.5-current.md`; retain it as the specification.

The results document must be self-contained and include, in this order:

1. title, audit date, immutable code SHA, documentation SHA, and runtime observation window;
2. clock and environment grounding;
3. source classification explaining that `...current.md` is the brief;
4. evidence doctrine and limitations;
5. instrument-integrity table;
6. E1–E20 disposition table;
7. W1–W5 disposition table;
8. A1–A10 three-pass results;
9. free-look findings;
10. ranked retained findings;
11. rejected/superseded/duplicate appendix;
12. runtime-only or still-unproven items;
13. exact backlog integration map;
14. operator decisions and falsifiers;
15. files and commands inspected, with code citations.

Every retained code finding must cite an exact repository path and line or symbol on the pinned SHA. Every runtime claim must state its query basis and timestamp. Never include credentials, secrets, account identifiers, or raw tokens.

---

## PHASE 4 — BUILD THE ADJUDICATION COVERAGE MATRIX

Before editing the backlog, create a complete matrix:

`finding | severity | evidence | disposition | canonical backlog ID | new/extends/duplicate/conflicts | priority | backlog section | ledger entry | operator decision | falsifier`

Rules:

- every retained finding appears exactly once in the backlog;
- every rejected, duplicate, superseded, or not-proven finding appears in the results appendix so it is not re-litigated;
- no item is called new if an existing backlog item already owns the same defect or acceptance criteria;
- an extension must name the existing backlog item it extends;
- PR #1203/#1204 ownership and implementation status must be recorded accurately;
- findings must be ranked by safety/value/effort for this approximately $2,000 defined-risk options account in learning mode—not by theoretical sophistication.

---

## PHASE 5 — INTEGRATE INTO PR #1205

On PR #1205's branch, update the canonical documents.

### `docs/backlog.md`

Add an explicit block headed:

`## 2026-07-15 — v1.5 EXTERNAL-AUDIT ADJUDICATION`

For every retained item include:

- priority;
- canonical identifier;
- exact defect/invariant;
- evidence label and cited seam;
- blast radius;
- acceptance criteria;
- dependency or trigger;
- whether it changes a control;
- falsifier/retirement condition;
- `new`, `extends X`, `duplicate of X`, or `conflicts with X` status.

Deduplicate against at least:

- canonical position representation;
- independent terminal distribution / queue ⑤;
- multi-basis cost unification;
- Phase-3 exit-basis measurement;
- funnel telemetry truth pack;
- option-liquidity freshness/prune provenance;
- scanner OI-floor extension;
- E19-2B full counterfactual selector;
- F-SHADOW-CAPITAL-PARITY;
- F-POLICY-CAPITAL-FALLBACK;
- GIT-SHA-DECISION-PROVENANCE;
- prequential operationalization;
- F-WINDOW residual coverage/identity;
- existing sentinel/fail-open items;
- any internal-fill or close-price contract item already present.

If F-MIDDAY-POSITION-READ-FAILOPEN is confirmed and not already owned, file it as a safety item with fail-closed typed-error acceptance criteria. Do not patch it here.

If the internal-fill sign defect is confirmed, state whether it is shadow accounting, evidence integrity, or broker-live safety; rank it accordingly. Do not conflate a shadow P&L distortion with live broker loss.

### `audit/ledger.md`

Add:

`## 2026-07-15 — ADJUDICATED: external full audit v1.5`

Record:

- audit brief path;
- generated results path;
- immutable code and docs SHAs;
- runtime observation window;
- retained findings and ranks;
- rejected/duplicate/superseded items;
- backlog identifiers created or extended;
- unresolved runtime falsifiers;
- explicit statement that this lane changed no production code or controls.

Preserve the existing universe-census adjudication and all previously reconciled #1200/#1201 material.

---

## PHASE 6 — DOCUMENTATION TESTS AND CONSISTENCY

Extend PR #1205's existing documentation-consistency test rather than creating a second competing test suite.

Durable tests must prove:

1. both the v1.5 brief and v1.5 results files exist and are classified distinctly;
2. the results file contains E1–E20, W1–W5, and A1–A10 dispositions;
3. every retained finding maps to exactly one canonical backlog item;
4. every new/extended item has evidence, acceptance criteria, dependency/trigger, and falsifier;
5. rejected/duplicate/superseded findings remain recorded outside the active build queue;
6. no imperative text from the brief is mislabeled as a completed finding;
7. no credentials, secrets, account identifiers, or raw tokens are committed;
8. current runtime falsifier grades are not overstated;
9. existing #1200/#1201 and universe-census entries remain present;
10. no production-code, config, migration, or control file enters the diff.

Do not pin transient runtime counts as permanent test invariants unless the test labels them as a dated census fixture. Prefer structural assertions.

Run only the documentation/consistency tests necessary for this docs lane. No application build.

---

## PHASE 7 — PR #1205 DELIVERABLE

Update PR #1205's title/body if necessary so it clearly states that the PR now contains:

- #1200/#1201 reconciliation;
- universe-census adjudication;
- executed external audit v1.5 results;
- backlog/ledger integration;
- documentation consistency guards.

Push only to PR #1205's branch. Leave the PR DRAFT and do not merge.

Final report must contain:

A. clock, SHA, deployment, and ownership grounding;

B. source classification (`AUDIT_BRIEF_ONLY` expected) and proof that the brief was executed rather than rejected;

C. v1.5 audit summary with counts of confirmed-new, extends-existing, partial, duplicate, superseded, rejected, and not-proven findings;

D. ranked retained findings with exact evidence and backlog destinations;

E. rejected-gaps appendix;

F. full adjudication coverage matrix;

G. exact files changed and diff scope;

H. tests and exact pass/fail totals;

I. new PR #1205 head SHA and CI result;

J. remaining runtime falsifiers and operator decisions;

K. explicit confirmation:

`DRAFT · NOT MERGED · NOT DEPLOYED · DOCS/TESTS ONLY · NO PRODUCTION CODE · NO MIGRATION · NO DB/BROKER WRITE · NO FLAGS, GATES, STOPS, THRESHOLDS, SIZING, ENTRY, EXIT, OR CONTROL CHANGED.`

STOP after the draft PR is updated and verified.

