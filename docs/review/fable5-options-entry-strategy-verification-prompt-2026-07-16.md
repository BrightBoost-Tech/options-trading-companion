# Claude Fable 5 — current options-entry strategy verification and backlog adjudication

## Invocation

Run this brief from a clean checkout of `BrightBoost-Tech/options-trading-companion` with Claude Code using the exact model identifier:

```bash
claude --model claude-fable-5
```

Then paste this entire file as the task prompt.

Before doing any work, report the effective model. If the effective model is not Claude Fable 5 / `claude-fable-5`, stop with:

`BLOCKED_MODEL_MISMATCH`

Do not silently substitute another model.

---

## Mission

Perform a fresh, adversarial verification of the prior options-entry strategy audit against:

1. the current `origin/main` repository;
2. the code actually deployed, when read-only Railway evidence is available;
3. the current broker account, when read-only Alpaca evidence is available;
4. current database state, when read-only Supabase evidence is available; and
5. the canonical backlog, ledger, open PRs, and issues.

Treat every statement in the hypothesis packet below as an **untrusted claim to prove, disprove, narrow, supersede, or deduplicate**. Do not copy conclusions from the packet into the backlog without re-tracing the current production path.

This is a software, controls, evidence-integrity, and account-suitability audit. It is **not** authorization to place a trade and must not recommend a specific live order.

The required outcome is a documentation-only draft PR containing:

- a self-contained verification-results artifact under `docs/review/`;
- an adjudicated update to `docs/backlog.md` containing only retained actionable findings;
- an exclusion-memory update to `audit/ledger.md`; and
- any narrow documentation-consistency test updates already used by the repository, only if needed to protect the new audit contract.

Do not change production code in this lane.

---

## Absolute operating constraints

### Read-only runtime

Allowed:

- Git and GitHub reads;
- repository code inspection;
- read-only Supabase queries;
- read-only Railway deployment, environment-name, and log inspection;
- read-only Alpaca account, positions, orders, and clock inspection;
- documentation-only writes on the audit branch;
- documentation-consistency tests that do not import or exercise production trading behavior;
- opening or updating one draft PR for this audit.

Prohibited:

- no broker order submission, replacement, cancellation, or close;
- no DB inserts, updates, deletes, RPC writes, migrations, or manual task triggers;
- no Railway variable changes, deploys, restarts, or service recycling;
- no changes to flags, gates, thresholds, strategy widths, DTE ranges, risk settings, sizing, universe membership, schedules, entries, exits, or controls;
- no production-code changes;
- no merges;
- no force pushes;
- no secrets, tokens, account identifiers, credential fragments, or private values in committed files;
- no claim that a merged path is running without deployed-SHA and runtime evidence;
- no claim that a code path is broker-reachable without tracing the caller chain to the live executor.

### Market-hours discipline

The lane is docs-only, but still obey the repository doctrine:

- do not deploy or change production during RTH;
- do not trigger a trading or scheduled job to manufacture evidence;
- natural runtime evidence may be observed read-only;
- if runtime evidence is unavailable, use `NOT-PROVEN`, not inference dressed as fact.

### Evidence labels

Use only these labels:

- `VERIFIED-CODE`
- `VERIFIED-TEST-REACH`
- `VERIFIED-MERGE`
- `VERIFIED-CI`
- `VERIFIED-RUNTIME`
- `INFERRED`
- `NOT-PROVEN`
- `REJECTED`
- `SUPERSEDED`
- `DUPLICATE`

A code observation does not prove deployed behavior. A database row does not prove broker execution. A shadow or paper row does not prove broker-live profitability. A UI label does not prove a reachable execution path.

---

## Source-of-truth precedence

Follow the repository's current doctrine, after verifying that it still says this:

1. current code at an immutable SHA describes what can run;
2. Supabase rows of record describe what the application recorded;
3. Railway deployment SHA and effective environment describe what is running;
4. Alpaca describes broker truth for account, positions, orders, fills, buying power, and market clock.

When sources disagree, report the disagreement. Do not average or silently choose the convenient source.

For account suitability, use current broker-grounded values and stamp their timestamp and basis. Do not reuse the prior `$2,067.86` observation unless it is independently re-read or clearly labeled as a historical dated census.

---

## Step 0 — model, clocks, SHA, deployment, and ownership

Before evaluating any strategy claim:

1. Report:
   - effective Claude model;
   - host UTC;
   - America/Chicago;
   - America/New_York;
   - DB `now()` if available;
   - broker clock, `is_open`, next open, and next close if available.

2. Ground repository state:
   - `origin/main` full SHA;
   - local HEAD and worktree cleanliness;
   - default branch;
   - current `docs/backlog.md` SHA;
   - current `audit/ledger.md` SHA;
   - current `CLAUDE.md` SHA.

3. Ground deployed state, read-only when available:
   - BE SHA;
   - worker SHA;
   - background-worker SHA;
   - deployment status and start time;
   - whether all relevant services run code-equivalent content.

4. Inspect current open PRs and issues for ownership of:
   - `docs/backlog.md`;
   - `audit/ledger.md`;
   - strategy selection;
   - EV/PoP/terminal distribution;
   - account-tier sizing;
   - broker options-level preflight;
   - lifecycle gating;
   - user strategy bans;
   - Compose/manual-entry UI;
   - 0DTE, CSP, covered-call, calendar, butterfly, or long-option work.

5. If another active branch owns the same docs or finding family, do not overwrite it. Either reuse the named audit/reconciliation branch when ownership is clear or stop with:

`BLOCKED_BACKLOG_OWNERSHIP_COLLISION`

6. Pin an immutable code basis for all line citations. If main moves during the audit:
   - compare the complete delta;
   - continue only if production-code conclusions remain valid or are re-audited at the new SHA;
   - state both the audit basis and documentation-write basis.

---

## Step 1 — canonical current strategy inventory

Build a current strategy capability manifest by tracing all of the following, not by trusting one registry:

- `packages/quantum/analytics/strategy_selector.py`
- `packages/quantum/options_scanner.py`
- `packages/quantum/analytics/strategy_policy.py`
- `packages/quantum/strategy_registry.py`
- `packages/quantum/services/sizing_engine.py`
- `packages/quantum/services/workflow_orchestrator.py`
- `packages/quantum/services/progression_service.py`
- broker order construction and submission paths
- lifecycle migration/service code
- strategy metadata endpoints
- strategy-config/backtest endpoints
- relevant frontend strategy selectors and manual-entry surfaces
- tests proving production-route reachability

Produce one row per discovered strategy identifier or alias with these columns:

`canonical strategy | aliases | selector-emittable | scanner builder exists | EV/PoP model | sizing model | lifecycle row/state | user-ban support | broker minimum level | live executor reachable | exit support | UI advertised | backtest-only | final capability verdict | evidence`

Allowed capability verdicts:

- `LIVE-REACHABLE`
- `LIVE-REACHABLE-BUT-GATED`
- `CODE-SUPPORTED-NOT-SELECTOR-REACHABLE`
- `PAPER/SHADOW-ONLY`
- `BACKTEST-ONLY`
- `UI-MOCK/DEAD-SURFACE`
- `DESIGNED-NOT-ACTIVE`
- `UNSUPPORTED`
- `NOT-PROVEN`

A strategy is `LIVE-REACHABLE` only if the complete chain is proven:

`selector or authorized entry source → contract builder → honest quotes → EV/score → sizing → persistence → stage gate → broker request → live route`

Green unit tests on an orphan helper are insufficient.

---

## Step 2 — hypothesis packet to adjudicate

For every hypothesis H1–H18 below, output:

`ID | exact hypothesis | current seam | code evidence | test reach | runtime evidence | disposition | backlog interaction | priority | acceptance criteria | falsifier`

Allowed dispositions:

- `CONFIRMED-NEW`
- `CONFIRMED-EXTENDS-EXISTING`
- `CONFIRMED-ALREADY-OWNED`
- `PARTIAL`
- `SUPERSEDED`
- `DUPLICATE`
- `REJECTED`
- `NOT-PROVEN`

No missing rows.

### H1 — actual selector set

Hypothesis: the normal automated selector currently emits only:

- `LONG_CALL_DEBIT_SPREAD`
- `LONG_PUT_DEBIT_SPREAD`
- `SHORT_PUT_CREDIT_SPREAD`
- `SHORT_CALL_CREDIT_SPREAD`
- `IRON_CONDOR`
- no-trade states such as `HOLD` or `CASH`

Verify the exact current pool, all alternate selectors/agents/overrides, feature flags, phase exclusions, and whether any path can inject a strategy outside the selector's declared set.

### H2 — advertised versus executable strategies

Hypothesis: registry, UI, and backtest surfaces advertise strategies that are not reachable by the automated live entry path, including some combination of:

- long calls;
- long puts;
- generic verticals;
- covered calls;
- custom strategy configs.

Trace every advertised option to a real API and executor. Classify dead, mock, backtest-only, paper-only, or live-reachable surfaces. Randomized/mock validation must be named explicitly if still present.

### H3 — debit vertical suitability

Hypothesis: for the current small defined-risk account, long call and long put debit spreads are the strongest existing core structures, subject to independent economic and liquidity gates.

Do not turn this into trade advice. Evaluate software suitability using:

- bounded maximum loss;
- account buying power;
- round-trip BP model;
- leg count and expected costs;
- current DTE policy;
- assignment exposure;
- exit support;
- recent broker-live outcomes by strategy, if sample identity is trustworthy;
- current regime and no-trade behavior only as context, not a recommendation.

If current evidence does not support a ranking among strategies, say so.

### H4 — credit-spread EV identity defect

Hypothesis: the current credit-spread PoP and payoff formulas create an algebraic identity in which raw EV is always zero before costs:

- `max_gain = credit × 100`
- `max_loss = (width − credit) × 100`
- `p(win) = max_loss / (max_gain + max_loss) = 1 − credit/width`
- `EV = p(win)×max_gain − (1−p(win))×max_loss = 0`

Verify the exact current implementation and all production call sites. Test the equation numerically across representative valid credits and widths. Determine whether:

- the identity still exists;
- another probability source overrides it before ranking;
- calibration changes it;
- the terminal-distribution work in backlog item `⑤` already owns the defect;
- current credit strategies are selector-visible but economically unable to clear downstream cost/edge gates.

Do not file a duplicate if `⑤ Independent terminal-distribution probability source` already owns the root cause. Extend it only if the current audit adds a distinct acceptance criterion or reachable defect.

### H5 — iron-condor cross-structure comparability

Hypothesis: iron condors are reachable but structurally disadvantaged for the current account by:

- four-leg commissions and quote completeness;
- model-dependent EV;
- a more conservative close-BP estimate;
- cross-structure ranking on non-comparable probability/EV bases;
- progression or regime gates.

Verify code default versus deployed `CONDOR_EV_MODEL` and related settings on every relevant worker when read-only environment evidence is available. Do not expose secret values. Report only non-secret control names and effective non-sensitive enum/numeric settings needed for the audit.

Deduplicate with current `⑤`, multi-basis-cost phase 2, ranking-commission work, and canonical-position work.

### H6 — current account tier and strategy capacity

Hypothesis: the prior account observation placed it in `small`, not `micro`.

Re-read current broker account state. Report, with timestamp and basis:

- equity;
- cash;
- options buying power;
- open option positions;
- open orders relevant to entry capacity;
- current code-derived tier;
- maximum concurrent trades;
- current global risk envelope by regime;
- whether unsettled funds create a cash/OBP gap.

Never commit account number, UUID, credentials, or raw broker payload.

If the broker read is unavailable, mark current tier `NOT-PROVEN` and use code-only tier boundaries separately.

### H7 — the `$1,000` tier cliff

Hypothesis: crossing from `$1,000` small tier to `$999.99` micro tier can sharply increase permitted per-trade risk, potentially from low-single-digit allocation behavior to a 90% one-position budget.

Verify:

- exact current tier boundaries;
- micro and small base risk math;
- allocator behavior;
- global envelope interaction;
- round-trip BP and collateral caps;
- concurrency gate;
- whether a recent change already smoothed or superseded the cliff;
- whether the cliff is intentional operator doctrine.

Produce a pure table at capital values `$900`, `$999.99`, `$1,000`, `$1,001`, `$2,000`, and `$5,000` under at least NORMAL and SHOCK, showing the maximum theoretical budget before contract granularity. Do not execute a trade or mutate config.

If the cliff remains, determine whether it is a new finding, already ledgered, or an intentional-but-reviewable control. Do not call operator intent a defect without evidence.

### H8 — absolute minimum-edge gate

Hypothesis: an absolute `MIN_EDGE_AFTER_COSTS` value, historically `$15`, is materially binding for a roughly `$2,000` account.

Verify current source and deployed value, ranking basis, fee/slippage basis, calibration application order, and recent durable rejection evidence. Separate:

- scanner rejection;
- canonical-ranker rejection;
- stage-time round-trip-cost rejection;
- calibrated versus raw EV;
- score versus dollar-EV reasons.

Do not recommend lowering the threshold. Any tier-aware alternative belongs in `RESEARCH` or observe-only design and must name the evidence needed before a control change.

### H9 — broker options approval preflight

Hypothesis: the broker wrapper exposes options buying power but not both:

- approved options level; and
- effective options trading level.

Verify current broker SDK fields, wrapper serialization, consumers, stage-time checks, and actual account read-only values when available. Build a strategy-to-minimum-level matrix from current broker documentation or SDK semantics, citing the authoritative source in the results artifact.

Determine whether the application can reject an unsupported structure before expensive scanning/staging or only learns through missing OBP / broker rejection.

If a gap exists, file or extend a backlog item with fail-closed preflight acceptance criteria. Do not assume the README's stated level is current broker truth.

### H10 — progression-phase exclusions

Hypothesis: one or more strategies, especially iron condors, are excluded in `alpaca_paper` or another progression phase.

Trace the current phase source, process environment mutation, fallback behavior, scanner filtering, and observability. Verify whether a failed progression read suppresses a strategy, opens it, or changes the universe. Classify the safety direction and whether the operator can distinguish “not eligible in phase” from “no economic candidate.”

### H11 — lifecycle fail-open behavior

Hypothesis: missing, invalid, or unreadable `strategy_lifecycle_states` data may default an unknown strategy to `live_full`.

Verify current migration state, loader behavior, scanner default, sizing cap, tests, and deployed DB state. Distinguish:

- table missing;
- query failure;
- empty table;
- missing strategy row;
- malformed state;
- `designed`;
- `experimental`;
- `live_full`;
- `deprecated`.

A result is safety-relevant only if the strategy is otherwise production-route reachable. Acceptance criteria for any retained item must keep exits working while entries fail closed.

### H12 — user strategy bans

Hypothesis: the workflow reads `settings.banned_strategies`, but the canonical migration history may not define the column, and read failure may degrade to an empty ban list.

Verify:

- actual migration history;
- current production schema through read-only introspection;
- RLS and user access;
- UI/API write surface;
- selector enforcement;
- final redundant gate;
- exception behavior;
- durable observability;
- current operator row, without exposing user identifiers.

A manually drifted production column is a finding, not proof that migrations are correct. If the feature does not exist end-to-end, classify it honestly rather than calling it a working user preference.

### H13 — DTE and intraday strategy availability

Hypothesis: the normal scanner's DTE range prevents 0DTE and other short-DTE entries, historically by enforcing 25–45 DTE.

Verify current constants, per-strategy expiry selection, any alternate scanner cycles, scheduler cadence, forced-close logic, monitor cadence, and live executor paths. Deduplicate with any current 0DTE design or backlog item.

Do not propose activation without a complete same-day lifecycle and market-calendar contract.

### H14 — single-leg long options as an experimental addition

Hypothesis: long calls and puts have partial support—mapping, EV, sizing, or broker submission—but are not selector-reachable.

Verify the exact missing seams. Evaluate whether the current unbounded-gain cap, PoP, cost, DTE, exit, lifecycle, and broker-level models make them suitable for an `experimental` one-contract state. A strategy is not “easy to add” merely because one helper supports one leg.

### H15 — debit butterfly as a future candidate

Hypothesis: a debit butterfly may be relevant to a small defined-risk account but currently lacks a complete production route.

Search for existing builders, payoff models, canonical-position support, risk/greeks, multi-leg order support, partial-fill handling, exit support, and backtests. Keep this in `RESEARCH` unless a complete reachable path and evidence threshold already exist. Do not outrank repairs to current EV, costs, lifecycle, or controls.

### H16 — strategies to defer

Adjudicate, separately:

- 0DTE verticals;
- cash-secured puts;
- covered calls;
- calendars;
- diagonals;
- naked short options;
- straddles and strangles.

For each, report:

`capital fit | broker level | assignment/equity handling | DTE/monitor support | builder | EV model | sizing | exit support | current lifecycle | verdict`

Possible verdicts:

- `RELEVANT-NOW`
- `EXPERIMENTAL-CANDIDATE`
- `RESEARCH-ONLY`
- `DEFER-CAPITAL`
- `DEFER-ARCHITECTURE`
- `PROHIBIT-UNDEFINED-RISK`
- `NOT-PROVEN`

### H17 — manual Compose and paper-entry surfaces

Hypothesis: the Compose UI may be a mock validator and the paper page may manage existing positions without providing a real guarded open-entry route.

Trace frontend calls to backend endpoints and then to staging/execution. Identify any random/mock results, stale example dates, or strategy choices that imply unsupported capability. Decide whether this is harmless prototype code, an operator-facing capability lie, or already removed.

### H18 — strategy identifier drift

Hypothesis: strategy names and aliases are duplicated across registry, selector, scanner, sizing, lifecycle, risk caps, persistence, learning, and UI, creating silent capability drift.

Build an identifier crosswalk. Detect aliases that:

- do not normalize to the same canonical strategy;
- receive different risk or cost handling;
- cannot resolve metadata;
- bypass bans or lifecycle states;
- split learning buckets;
- collide with exit strategy names;
- appear only in dead surfaces.

Do not propose a large rewrite by default. Rank a canonical capability manifest only if it beats current open work on safety/value/effort.

---

## Step 3 — account-specific strategy audit

Using current broker-grounded account state when available, create an account-fit matrix for every live-reachable or experimental-candidate strategy.

Columns:

`strategy | direction/volatility use | max-loss basis | collateral/BP basis | estimated round-trip BP | leg count | fee basis | assignment exposure | DTE | monitor/exit support | current gate state | recent live evidence n | current account fit | confidence | reason`

Account-fit verdicts:

- `CORE-CANDIDATE`
- `CONDITIONAL`
- `BLOCKED-BY-DEFECT`
- `BLOCKED-BY-CONTROL`
- `BLOCKED-BY-BROKER-LEVEL`
- `BLOCKED-BY-CAPITAL`
- `EXPERIMENTAL-ONLY`
- `DEFER`
- `NOT-PROVEN`

Do not call a strategy ideal solely because its payoff is defined-risk. Costs, executable quotes, exit buying power, assignment, account concentration, and current model integrity must all be considered.

Do not claim statistical edge from tiny samples. State exact denominators separately:

- all broker-live closes;
- post-epoch broker-live closes;
- per-strategy broker-live closes;
- paper closes;
- shadow closes;
- thesis rows;
- selected suggestions;
- staged orders;
- filled orders.

Never combine them into a generic “live n.”

---

## Step 4 — gating and blockage audit

Build a complete entry-funnel matrix from opportunity generation to broker submission:

`gate/order | source seam | input basis | strategies affected | fail-open/fail-closed | durable reason | user-visible | recent count | current setting | control owner | bypass/kill switch | verdict`

At minimum cover:

- account/OBP readability;
- options approval/effective level;
- account tier and concurrency;
- progression phase;
- lifecycle state;
- user strategy bans;
- regime/sentiment selector;
- DTE;
- real IV availability;
- chain and greeks completeness;
- per-leg quote validation;
- liquidity/spread thresholds;
- earnings proximity;
- EV positivity;
- execution-cost versus EV;
- canonical minimum edge;
- calibration ordering;
- score floor;
- sizing and contract granularity;
- collateral;
- round-trip BP;
- global risk envelope;
- utilization and concentration;
- same-symbol dedup/cooldown;
- entries-paused breaker;
- market clock/session;
- broker request validation;
- broker rejection handling.

Identify blockers that make a strategy theoretically present but practically inaccessible. Separate **designed suppression** from a defect.

---

## Step 5 — test and falsifier requirements

For each retained code finding, identify the narrowest production-route test that would falsify it. Prefer route tests over helper-only tests.

Required targeted checks include, when applicable:

1. Credit-spread EV:
   - multiple valid `(credit, width)` pairs;
   - exact raw EV output;
   - downstream rank result after fees/slippage;
   - proof of whether another probability source changes the identity.

2. Tier boundary:
   - pure sizing outputs immediately below and above `$1,000`;
   - NORMAL and SHOCK;
   - micro concurrency;
   - allocator bypass/activation.

3. Lifecycle:
   - table read exception;
   - empty rows;
   - missing strategy;
   - invalid state;
   - experimental cap;
   - exits unaffected.

4. User bans:
   - persisted ban reaches selector and final gate;
   - schema/read failure does not silently authorize a banned strategy;
   - observable typed rejection.

5. Broker level:
   - approved and effective levels serialized distinctly;
   - each strategy preflighted against a minimum level;
   - missing field fails closed for entries;
   - no impact on exits.

6. UI reachability:
   - every displayed executable strategy maps to a real guarded endpoint;
   - mock-only surfaces are clearly labeled or removed.

Do not implement production fixes in this lane. Record the tests as acceptance criteria and, when safe, run existing tests that already cover the seam.

---

## Step 6 — deduplication against current backlog and ledger

Read `docs/backlog.md` and `audit/ledger.md` completely before filing anything.

At minimum deduplicate against:

- `⑤ Independent terminal-distribution probability source`;
- multi-basis cost phase 2;
- canonical-position remainder;
- funnel telemetry phase 2;
- F-SHADOW-CAPITAL-PARITY / small-tier fleet work;
- Phase-3 exit-basis measurement;
- option-liquidity freshness/provenance;
- exact-leg OI floor;
- lifecycle work;
- existing entry fail-closed items;
- strategy breadth / multi-strategy design history;
- any existing account-tier, risk-cliff, or micro-tier doctrine;
- any current PR or issue for broker options level;
- any Compose/manual-entry cleanup;
- 0DTE/CSP designs;
- strategy-ID normalization;
- replay and evidence-integrity items unrelated to this audit.

Rules:

- A root cause already owned is `CONFIRMED-ALREADY-OWNED` or `DUPLICATE`, not new.
- Add an extension only if it contributes a distinct reachable seam, acceptance criterion, dependency, or falsifier.
- Shipped code with only runtime proof pending belongs in ledger pending verification, not the active build queue.
- A `NOT-PROVEN` hypothesis does not enter the backlog.
- A rejected hypothesis stays in the results artifact and ledger exclusion memory.
- Do not re-open settled findings without a named falsifier.

---

## Step 7 — required results artifact

Create:

`docs/review/fable5-options-entry-strategy-verification-results-YYYY-MM-DD.md`

Use the actual grounded Chicago audit date.

The document must be self-contained and contain, in this order:

1. title, effective model, audit date, immutable code SHA, documentation SHA, deployment SHAs, and runtime observation window;
2. clock and environment grounding;
3. scope, evidence doctrine, and limitations;
4. current account census with redacted identifiers and exact source/timestamp;
5. canonical strategy capability manifest;
6. H1–H18 disposition table;
7. account-fit matrix;
8. complete entry-funnel/gating matrix;
9. current strategy distribution and recent entry outcomes, with denominators separated;
10. retained findings, ranked by safety/value/effort;
11. recommended backlog integrations and exact existing items extended;
12. rejected, duplicate, superseded, and not-proven appendix;
13. operator decisions required;
14. runtime falsifiers still pending;
15. files, commands, tests, queries, and source citations used;
16. exact diff scope and no-control-change attestation.

Every code finding must cite an exact path and line/symbol at the immutable SHA. Every runtime claim must state source, query basis, and timestamp. Every economic number must identify:

- basis: raw/calibrated/realized/mark/executable/shadow/broker;
- unit: per-share/per-leg/per-structure-contract/position-total/account-total;
- quantity treatment;
- fee/slippage treatment.

---

## Step 8 — backlog integration

Update `docs/backlog.md` with a new dated section near the current authoritative standing block:

`## YYYY-MM-DD — FABLE 5 OPTIONS-ENTRY STRATEGY VERIFICATION`

Do **not** paste the entire report into the backlog.

Include only retained actionable findings. For each item include:

- canonical ID;
- priority tier (`GATED`, `P0`, `P1`, `P2`, or `RESEARCH`, following current repository conventions);
- exact invariant or defect;
- `new`, `extends <existing ID>`, or `conflicts with <existing ID>` status;
- evidence label and exact seam;
- live reachability/blast radius;
- current account relevance;
- acceptance criteria;
- dependency/trigger;
- whether the future fix would tighten, loosen, or leave controls unchanged;
- falsifier/retirement condition;
- owner decision, when required.

Then reconcile the authoritative “Actual next priorities” list only if the verified evidence changes ordering. Do not reorder the queue merely because a strategy is interesting.

Specific filing rules:

- The credit/condor probability issue should normally extend `⑤`, not create a duplicate.
- Remaining commission/slippage/basis inconsistencies should normally extend multi-basis cost phase 2.
- Broker options-level preflight may be a new safety/control item only if no current owner exists.
- Lifecycle missing-state behavior may be a new safety item only if still live-reachable and not already fixed/owned.
- User-ban schema/enforcement may be a new user-control integrity item only if production and migration evidence support it.
- The `$1,000` tier discontinuity must be classified as defect, intentional doctrine, research, or superseded—not assumed.
- Strategy additions belong behind integrity repairs unless they clearly provide greater safety/value with lower risk.
- No threshold, gate, DTE, width, sizing, strategy activation, or broker-level change is authorized by adding a backlog item.

---

## Step 9 — ledger integration

Append to `audit/ledger.md`:

`## YYYY-MM-DD — ADJUDICATED: Fable 5 options-entry strategy verification`

Record:

- prompt path;
- results path;
- model identifier;
- immutable code/docs SHAs;
- deployment/runtime scope;
- retained findings and backlog destinations;
- findings that merely extend existing work;
- duplicate, rejected, superseded, and not-proven hypotheses;
- pending runtime falsifiers;
- explicit statement that no production code, migration, DB/broker write, deploy, flag, gate, threshold, sizing, strategy activation, entry, exit, or control changed.

This ledger entry is exclusion memory. Phrase it so future audits do not spend slots rediscovering the same hypotheses.

---

## Step 10 — documentation consistency and PR

1. Preserve unrelated working-tree changes byte-for-byte.
2. Use a dedicated branch based on current main unless a clearly owned existing docs branch must be reused.
3. Diff must contain only:
   - this results artifact;
   - `docs/backlog.md`;
   - `audit/ledger.md`;
   - a narrow existing docs-consistency test, if necessary.
4. Run the repository's relevant documentation-consistency tests. Do not run or modify live systems.
5. Inspect the final diff for account identifiers, secrets, raw tokens, and accidental control changes.
6. Commit intentionally.
7. Push the branch.
8. Open a **draft** PR.
9. Do not merge or enable auto-merge.

PR title:

`docs: verify options entry strategies with Fable 5`

PR body must summarize:

- immutable audit basis;
- current account basis and timestamp, without identifiers;
- count of confirmed-new, extends-existing, already-owned, partial, duplicate, superseded, rejected, and not-proven hypotheses;
- retained backlog changes;
- tests run;
- runtime limitations;
- explicit no-control-change attestation.

---

## Final response contract

Return:

A. effective model and clock grounding;

B. immutable code and documentation SHAs;

C. deployment/runtime evidence availability;

D. current account tier and strategy-capability headline, or `NOT-PROVEN`;

E. H1–H18 disposition counts;

F. ranked retained findings and exact backlog IDs;

G. duplicates/rejections not added to backlog;

H. files changed;

I. tests and exact pass/fail totals;

J. draft PR number, URL, branch, and head SHA;

K. remaining operator decisions and runtime falsifiers;

L. this exact attestation:

`DRAFT · NOT MERGED · NOT DEPLOYED · DOCS/TESTS ONLY · NO PRODUCTION CODE · NO MIGRATION · NO DB/BROKER WRITE · NO FLAGS, GATES, STOPS, THRESHOLDS, DTE, WIDTHS, SIZING, STRATEGY ACTIVATION, ENTRY, EXIT, OR CONTROL CHANGED.`

Stop after the draft PR is opened and verified.
