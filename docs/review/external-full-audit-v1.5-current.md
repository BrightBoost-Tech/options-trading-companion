# EXTERNAL FULL AUDIT v1.5R — Ten-Area Deep Dive
## Current-state revision through PR #1200 / PR #1201

**Issued:** 2026-07-14  
**Expected immutable code baseline:** `bef2cdd60edbee8642fa043192fd982d4bfe4436`  
**Area 11 / self-extension slot:** EXCLUDED  
**Reviewer access:** full codebase + review packet + prior reports/adjudications in `docs/review/`, `audit/reports/`, and `audit/ledger.md`; **no Supabase, Railway, or Alpaca access**.  
**Mode:** read-only analysis and written report. Implement nothing.

---

## STEP 0 — REPRODUCIBLE GROUNDING

Before analysis:

1. State host UTC and local timezone time.
2. Resolve the exact 40-character SHA being reviewed.
3. Expected `origin/main` at issuance is:
   `bef2cdd60edbee8642fa043192fd982d4bfe4436`.
4. If the repository has advanced, do **not** silently audit the moving target. Report:
   - expected SHA;
   - observed SHA;
   - intervening commits/files;
   - whether the delta touches any audit territory.
   Then pin one immutable observed SHA and use it for the entire report.
5. Record `git status` and distinguish pre-existing/untracked material. Do not edit,
   stash, reset, clean, commit, build, install, migrate, deploy, trigger jobs, change
   configuration, or touch broker/DB state.
6. You cannot ground DB or broker clocks because those systems are outside your access.
   State that explicitly. Any requested DB/Railway/Alpaca proof becomes a `RUNTIME CHECK — NOT RUN`,
   never an implied verification.
7. Permitted operations are source search and read-only Git/object inspection. Do not run the
   application or test suite. If a remote-ref check is available without changing local refs,
   recheck it at report end; a newer SHA is an out-of-scope delta, not a reason to move the pin.

### Baseline reconciliation that must be checked first

- PR #1201 merged at `967071277b12cdfc602d8801fc4d8640a74fa4c5`:
  F-A3-4 shared calibration/prequential cohort fetch + thesis execution-mode headline.
- PR #1200 merged at `bef2cdd60edbee8642fa043192fd982d4bfe4436`:
  E19-2A raw-candidate-eligibility observation.
- `docs/backlog.md` and `audit/ledger.md` were not updated by #1200/#1201 and may describe
  the pre-merge state. This is **known version-of-record lag**. Code/merged PR state governs;
  any additional disagreement is a finding.
- The 2026-07-14 nightly report was not committed at issuance. Treat packet material as an
  attestation, not repository state.
- The credential-exposure incident is operator-attested `ROTATED_AND_REVOKED`.
  Audit repository/code exposure and secret-handling design only. Never reproduce a secret,
  token, value, fragment, fingerprint, or screenshot; report credential class + path only.

---

## EVIDENCE AND CLAIM CONTRACT

Use exactly these proof labels:

- `VERIFIED-CODE` — proven at the pinned SHA by production code/dataflow.
- `VERIFIED-TEST-REACH` — an existing test reaches the actual production seam, including the
  external/serialization boundary it claims to protect.
- `ATTESTED-RUNTIME` — packet/ledger/operator evidence from Supabase/Railway/Alpaca that you
  cannot independently query.
- `INFERRED` — reasoned conclusion with its premises stated.
- `RUNTIME CHECK — NOT RUN` — exact external read needed to confirm/refute a claim.
- `NOT PROVEN` — evidence is insufficient and no honest narrower claim is available.

Never upgrade an attestation to code verification. Never downgrade a code/packet disagreement
into “documentation drift” without proving which side is wrong.

### EV-basis rule — mandatory for every number

Calibration now applies in production, but ordering remains post-sizing/post-score. Therefore:

- `ev_raw` = uncalibrated model output;
- stored/served `ev` may be calibrated;
- #1200 observational rows may carry both `ev_raw` and `ev_calibrated` with an explicit basis;
- no EV, RAeV, score, edge, or P&L comparison may appear without
  `basis=raw | calibrated | realized | unknown` and `unit=per-contract | position-total | unknown`.

Unknown basis is a finding when the number drives a decision.

### Existing contract tags

- `STATE` — verify; mismatch is a finding.
- `SETTLED(condition)` — inspect the condition; a changed condition reopens the item.
- `CHARTER` — answer with evidence not already supplied; contradiction/extension is valuable.
- `OBSERVE-WINDOW` — audit whether the evidence window can support its decision.
- `INSTRUMENT-INTEGRITY` — audit whether the reporting/capture mechanism reaches a durable,
  observable sink.

### Per-finding schema

For every finding report:

1. ID + area + severity (`CRITICAL/HIGH/MED/LOW/NOTE`)
2. Claim being tested
3. Proof label
4. Exact production seam (`file:function:line` at the pinned SHA)
5. Existing test and whether it reaches that seam
6. Instrument path and durable sink, if applicable
7. Impact on correctness, evidence quality, profit/loss inference, or operator control
8. Backlog interaction (`NEW | EXTENDS-X | DUPLICATES-X | CONFLICTS-X | SETTLED`)
9. Doctrine check: does the recommendation loosen a control? If yes, name the **proven error**;
   adverse outcomes alone never justify loosening
10. Smallest operator decision / remediation
11. Falsifier
12. Exact `RUNTIME CHECK — NOT RUN`, when runtime evidence is required

No line-number-only findings. Show the dataflow and consumer.

---

## PREDECESSOR BAR

Five engagements established the signature:

- v1.1 — fail-open close chain
- v1.2 — false-green runner + re-bypassed bias
- v1.3 — per-user seam inside the v1.2 fix + EV≡$0 algebra + replay early returns
- v1.4 — `[]` sentinel, selection-biased un-mute, manifest coverage 2-of-7
- post-v1.4 — observability itself failed: INFO logs died before a sink and decision blobs
  failed serialization while mocked tests remained green

Standing question for every claim:

> Does the test reach the production seam, and can the instrument that reports failure
> actually emit to a durable sink?

Reserve a genuine `FREE LOOK` outside every charter. Do not rename a known backlog item as a
new finding; a stronger mechanism, newly proven dependency, or contradiction is valuable.

---

## INSTRUMENT-INTEGRITY — FIRST-CLASS MANDATE

Historical failures:

- pre-#1198: no process logging setup; application `logger.info` died in-process;
- pre-#1199: gzip bytes crossed supabase-py’s JSON boundary, every blob write failed,
  `data_blobs` stayed empty, and decision inputs could reference never-persisted hashes;
- tests mocked the boundary that failed.

Current code/runtime claims:

- #1198 added root INFO + stream handler + noisy-library pinning at all service entrypoints;
- #1199 added bytea encode/decode, an atomicity gate, typed `capture_partial`, generic error
  roll-up, and terminal manifests;
- packet attests the 2026-07-14 13:00Z natural `suggestions_close` run produced the first
  cryptographically complete tape; packet further attests all four 2026-07-14 decision runs
  were `tape_integrity='complete'` with blobs;
- `decision_runs.git_sha` remained `unknown` because worker `GIT_SHA` provenance was unstamped.

For every relied-upon control/log/capture, determine:

1. emitter;
2. serialization/transport boundary;
3. durable sink;
4. reader/alert/dashboard;
5. origin-injected failure test;
6. natural runtime proof, if attested;
7. exact runtime check still needed.

Deliver an `INSTRUMENT-INTEGRITY LIST`. Prime suspects:

- any INFO-only evidence whose window began before #1198;
- any non-JSON type written through a JSON client;
- any commit/error swallowed below job classification;
- tests mocking the deepest failing boundary;
- SHA/version provenance that depends on an unset environment variable;
- absence-of-log treated as evidence that nothing occurred.

---

## EXCLUSIONS — VERIFIED-CLOSED OR CONDITIONALLY CLOSED

Contradiction to a closure claim is an exclusion-integrity finding and receives top priority.

### E1 — Calibration kill-switch

Flag/runtime application previously proven. `SETTLED`: 0.5 floor held; winsorization no-action
was an owner decision; do not re-litigate merely because losses occurred. Known limitations:

- the 0.5 clamp cannot correct sign-wrong edge;
- segment calibration admits at n=3 with no apply-time sample re-check and a persistence rule
  that can favor small-n deviations;
- calibration still applies after sizing/scoring, so ranking may remain raw-score ordered.

Verify current code and keep the prequential falsifier + queue-⑤ as the defenses.

### E2–E7

- **E2:** gate quantity scaling per-contract; live observe-only W1.
- **E3:** streak breaker edge-trigger proven; quiet nights are designed.
- **E4:** CLOSE_FILL_GAP sign fix in code; disposition of the pre-fix QQQ 15.08 row remains a
  filed runtime-evidence loose end.
- **E5:** OBP capital read fails closed.
- **E6:** broker-ack close invariant complete. Known open edges: ①b
  `needs_manual_review` treated as routed success; ⑥ residual partial-close custody, hard-triggered
  before routine qty>1 credit or any open position ≤~10 DTE.
- **E7:** viability bias rewired at active route; real ordering awaits ≥2 executor survivors.

### E8 — Sentinel disease

The original runner, per-user seam, and #1195 `[]` sentinel are closed. #1201/F-A3-4 is now
**SHIPPED**, not pending: validator fetch delegates to the production calibration cohort contract,
and read failure is distinct from legitimate zero rows. Verify that both production and validator
routes truly share the same predicate and failure semantics. Find any **fourth** authoritative
read that returns empty/default on failure.

### E9–E15

- **E9:** observability remainder; #1104 writer-hardening was orphaned in rescoping—verify state,
  do not rediscover it.
- **E10:** close_reason propagation + price_basis disclosure shipped (#1185).
- **E11:** thesis tracker live. Replace the stale 13/16 headline with the authoritative census
  now pinned by #1201 tests: 83 rows total; 77 scored = 37 hit + 40 miss; 6 in-progress;
  `alpaca_live` broker-filled = 5/7 scored with 5 additional in-progress rows;
  `live_eligible` routing is not broker execution. Only 2 of the 6 in-progress rows were Aug-21.
  Current-era live+shadow proxy was 12/15=80%, but shadow fill fiction and tiny-n caveats bind.
- **E12:** PoP label fix shipped; credit-vertical EV remains payoff-circular/unevaluable until ⑤.
  Condor EV remains a hand-tuned heuristic (`|delta|`, fixed severity, tail haircut). One terminal
  distribution must serve both vertical and condor payoff integrations.
- **E13:** COALESCE restore + narrow migration-content drift guard shipped; runtime view identity
  remains P2.
- **E14:** clone risk normalizer/backfill **shipped in #1189**. Verify ancestry and implementation
  at the pinned SHA, name the exact trustworthy-evidence boundary, and do not infer full selection
  validity from normalized rows.
- **E15:** winter-close ET wall-clock shipped. Summer warm-up blind remains filed.

### E16 — Replay/tape integrity

**SHIPPED in #1199 and naturally runtime-attested.** Verify at HEAD:

- all 7 midday returns + morning terminals emit manifests;
- bytea write encoding and read decoding are symmetrical;
- atomicity prevents references to unpersisted hashes;
- shortfall becomes typed `capture_partial` and reaches top-level job truth;
- existing tests exercise real JSON serialization and the RPC/commit boundary rather than mocks;
- all pre-#1199 rows remain honestly annotated, not silently promoted to complete.

Runtime attestation is citable, but the external reviewer must label it `ATTESTED-RUNTIME`.

### E17–E18

- **E17:** prequential validator remains on-demand and non-circular; after #1201 it still has
  **zero production callers**. Decide whether this is an operator study tool or a future
  observe-only scheduled runner; do not call it continuously validating today.
- **E18:** PoP terminal clamp + legacy deletion shipped.

### E19 — Raw-EV observation

**SHIPPED in #1200, but scope is deliberately narrow.** It observes candidates that are fully
formed, pass raw eligibility, and die only at calibrated `edge_below_minimum`. It writes a
`NOT_EXECUTABLE` clone + policy verdict with:

- `observation_scope='raw_candidate_eligibility_only'`;
- no selection, capacity, joint ranking, execution, fill, P&L, or thesis claim;
- fail-closed prerejection cohort binding/capital;
- normalized per-contract eligibility;
- typed error propagation to job partial;
- champion/executable effect-set non-interference.

Verify all of those claims and the frozen-baseline test. Do **not** describe #1200 as the complete
shadow un-mute or entry-rate experiment. E19-2B—the full counterfactual selector—is open.
Known residuals:

- legacy normal-shadow loop still has the `$100,000` capital fallback;
- shadow capital remains incomparable with the ~$2k live account;
- code defaults `SHADOW_RAW_EV_ENABLED` ON when unset; packet attests it was unset/default-ON at
  the final merge check—label configuration as `ATTESTED-RUNTIME`;
- first qualifying post-merge candidate is the live falsifier;
- no qualifying candidate = `INCONCLUSIVE`, never pass/fail.

### E20 — Logging

**SHIPPED in #1198 and packet-attested across service entrypoints.** Verify code calls logging
setup at every process entry and that tests use a real handler/stream. The original
F-WINDOW-1—INFO instruments being unable to emit—is closed.

After the final `bef2cdd` recycle, packet attests clean service deployment/BE startup; fresh
worker and background-worker import canaries require their next natural jobs. Keep
“logging infrastructure proven” separate from “this exact recycled process emitted its canary.”

There is now an identifier conflict: the tail reuses `F-WINDOW-1` for “per-decision-site
heartbeats + W3 reservation-order identity.” Classify it as already closed, doc drift, or a
distinct residual requiring a new ID. Do not silently merge two defects.

---

## OBSERVE-WINDOWS W1–W5

Use absolute boundaries, not “tonight/Monday/day 2.”

- **W1:** `GATE_QTY_FIX_LIVE_ENABLED=OFF`; WARNING-level evidence window from `655c9aa` remains
  the one pre-#1198 window that emitted.
- **W2:** `RISK_BASIS_MAX_LOSS_ENABLED=OFF`; first valid INFO evidence begins at #1198
  (`1386834daed4bfed9a18206338c0fe6b2aa8a8ce`).
- **W3:** `BUCKET_CONTROL_ENFORCE=OFF`; unknown/unreadable armed state blocks. Verify INFO evidence
  emits after #1198 and reservation identity cannot diverge from decision identity.
- **W4:** `CALIBRATION_APPLY_AT_SCORING=OFF`; first valid INFO evidence begins at #1198.
- **W5:** composed arm remains deferred. Later deploys do not erase durable evidence, but every
  recycle requires canary/flag readback. #1200 supplies raw-candidate eligibility evidence only;
  it does not satisfy full-selection evidence. Canonical position truth, shadow-capital parity,
  E19-2B, and sufficient clean observation remain dependencies.

Audit each window:

1. exact first valid evidence timestamp/SHA;
2. emitter live after #1198;
3. durable sink and retention;
4. whether the evidence measures the eventual arm decision;
5. bypass around the enforcement seam;
6. sample sufficiency and reset rules;
7. natural runtime check.

Assign each window one status:
`UNSTARTED | START UNVERIFIED | RUNNING | GAPPED/PAUSED | COMPLETE`.
A merge alone neither starts nor resets a window. Reset only when population, semantics,
capture integrity, or the decision-generating mechanism changes, and state why earlier evidence
becomes invalid or remains usable.

The #1187 heartbeats were themselves previously logged below the live threshold. Verify their
post-#1198 emit path and do not equate code presence with durable evidence.

---

## SETTLED DECISIONS D①–D④

- **D①:** Calendar & Clock retained; security lens queued.
- **D②:** #1200 E19-2A raw-candidate-eligibility observation shipped. Full counterfactual
  selection remains E19-2B; no execution/P&L inference.
- **D③:** composed arm package may be built, but ARM remains NO pending trustworthy evidence.
- **D④:** queue-⑤ approved; the two-leg credit cohort stays gated on its probability source.

Reopen only when the recorded condition changes.

---

## KNOWN-PENDING / OPEN — VERIFY, EXTEND, OR CONTRADICT; DO NOT REDISCOVER

### Immediate tail

- **F-A9-5:** `_log_cohort_decisions` compares dollar `ev` with a 0–100 score threshold;
  logging reason can lie. The fix must consume the routing predicate’s actual result.
- **Heartbeat/reservation residual:** reconcile the reused F-WINDOW-1 ID with W3 identity.
- **F-A10-4:** thesis rows can remain `in_progress` through the Friday-to-Monday 72h lag;
  low priority, accept-or-adjust decision.

### Headline P1

- **Canonical position representation:** signed per-leg ratios, explicit multipliers, exact
  defined-risk payoff/max loss, signed Greeks, payoff-capped stress, and broker reconciliation.
  This is the merge target for `risk_envelope`, #1166 risk-basis truth, and Greeks-at-stage.
- **⑤ independent credit-spread probability source:** one terminal distribution, two payoff
  integrations (vertical + condor), locked prequential falsifier against delta/fair-odds baseline
  on Brier, EV-RMSE, and net-P&L rank.
- **Multi-basis cost unification:** canonical ranker currently charges two leg-contracts for
  open+close; a 4-leg IC round trip is approximately 4× understated.
- **Phase-3 exit-basis measurement:** combo NBBO, per-leg quote age, spread-noise floor, trigger
  measure, and realized close pairing. Measurement only; no stop loosening.
- **F-A1-3 calibration ordering:** calibration applies after sizing/score; recompute score/rank
  only under an explicit observe→falsify→operator decision.
- **B1/B2 bucket control:** before the book routinely holds 2+ live positions.

### Newly filed from #1200/#1201 work

- **F-SHADOW-CAPITAL-PARITY:** shadows sized near $100k are not economically comparable to
  the ~$2k live account.
- **F-POLICY-CAPITAL-FALLBACK:** remove legacy `net_liq or cash_balance or 100000`; fail closed.
- **GIT-SHA-DECISION-PROVENANCE:** `decision_runs.git_sha` remains unstamped/unknown.
- **Prequential operationalization:** decide study tool vs scheduled observe-only runner.
- **E19-2B:** full counterfactual selector with unioned candidate set, coherent basis, joint rank,
  capacity/slot limits, stable tie-break, and input-order independence.

### Trigger-owned / gated

Keep ①b, W2b, ⑥ partial-close custody, P0-A client-order-ID reconciliation, book-scaling ARM,
Phase-3 10–15 live-close gate, reaper/retry, #1104 writer hardening, replay config/multiplier/TTL,
versioned earnings, per-leg quote envelope, segment-n floor, and the remaining filed items under
their existing triggers. Do not convert a trigger-owned item into a free build recommendation.

`FORECAST_V4_ENABLED=true` while the forecast package has no production consumer remains an
inverse kill-switch candidate: verify whether any compute actually runs. Any other armed-but-
unwired capability flag is a finding.

---

## SYSTEM + STATE AT ISSUANCE

Code baseline:

- `main = bef2cdd60edbee8642fa043192fd982d4bfe4436` (#1200 on top of #1201).
- #1198 logging, #1199 tape integrity, #1201 cohort/headline parity, and #1200 raw-candidate
  observation are merged.

Runtime facts below are packet attestations, not external-reviewer verification:

- 9 live closes, 8 post-epoch, 1W/7L, approximately −$178 post-epoch;
- calibration applies a 0.5 floor, but post-sizing/post-score ordering remains;
- authoritative thesis population: 37/77 pooled; broker-filled live 5/7 scored; six rows
  in-progress; routing and execution must never be conflated;
- Phase-3 evidence approximately 3/10–15 instrumented live close fills;
- broker live account was flat at the final merge check; internal DB state was not literally
  flat because a shadow position and historical paper-order/job fossils existed;
- first complete natural decision tape was attested on 2026-07-14;
- #1201’s next natural calibration/thesis runs and #1200’s first qualifying candidate remain
  runtime falsifiers unless newer packet evidence supersedes them;
- credentials exposed in the prior transcript are operator-attested rotated and revoked.

Use the milestone scale:

- **85:** no known critical correctness defect + reproducible decisions
- **90:** canonical risk/EV/cost/replay/partial-close complete
- **95:** repeated runtime proof + Phase-3 evidence + origin failure injection
- **100:** reference ceiling

A low trade rate is not itself a defect. A correct system may conclude no candidate has positive
net edge after honest costs.

---

## MODE — THREE PASSES

### Pass 1 — State and exclusion integrity

Verify E1–E20, the current baseline, settled conditions, and packet/code disagreements.

### Pass 2 — Seam, test-reach, and instrument integrity

Trace the production dataflow, find the deepest failing seam, grade existing tests, and prove
whether the evidence emitter reaches a durable sink.

### Pass 3 — Dependency graph, free look, and decision value

Identify the highest-value non-duplicate extension, its dependencies/collisions, smallest honest
implementation boundary, and falsifier. Do not implement it.

For dormant areas, explicitly mark unavailable passes `DEFERRED-DORMANT`; do not manufacture
findings to satisfy the template.

---

## THE TEN AREAS — KEEP THESE TEN AND NO OTHERS

### A1 — PROFITS

With the tape naturally proven alive after #1199, determine whether the minimal deterministic
replay runner is now buildable from persisted inputs. The first replay question is:

> On identical captured candidates and capital state, how would the champion executable set,
> ordering, and rejection reasons differ under `basis=raw` versus `basis=calibrated`?

Do not mistake #1200 for that replay: #1200 observes raw-candidate eligibility only and does not
perform joint selection/capacity. Audit what terminal-distribution inputs already exist for ⑤’s
make-vs-fetch decision. The n≈8 live-outcome disqualifier binds; every profit/EV number needs
basis and unit.

### A2 — LOSSES

Audit re-arm-loop economics and identity: max attempts, cancel/re-arm drift guards, and whether a
replacement can escape its original reservation/order identity. Treat the canonical-position
model as the merge target: exact vertical/IC max loss, signed ratios, explicit multipliers, signed
Greeks, and payoff-capped stress. Determine whether `max_loss_total` from #1166 is semantically
safe for each consumer. Walk assignment/exercise and residual partial-close custody as credit
structures approach expiry. No stop loosening.

### A3 — SELF-LEARNING

Now that close_reason, thesis outcome, P&L, and complete decision tape exist, determine whether
`thesis=hit ∧ realized_pnl<0 ∧ close_reason=stop` is readable without cohort/basis leakage. Verify
#1201’s shared fetch contract, the execution-mode/routing-mode separation, and failure-vs-empty
semantics. Trace the segment-n=3 fuse and any apply-time omission. Determine whether the
always-unknown DTE bucket contaminates labels. Prequential validator has no production caller:
grade it as a study tool, not an active control.

### A4 — SELF-SUSTAINING

Make instrument integrity the headline. Grade the complete self-observation stack after #1198
and #1199: process logging, decision tape, job classification, alert egress/receipts, dead-man,
replay hashes, and deployment/SHA provenance. Identify every relied-upon signal that is
code-present but lacks a proven sink or natural observation. Find any other non-JSON type crossing
supabase-py’s JSON layer. Include `decision_runs.git_sha='unknown'` and the credential-output
incident’s code/process lessons without reproducing secrets.

### A5 — EFFICIENCY

Compute real post-#1199 replay/tape growth and TTL needs using basis-labeled counts. Audit duplicate
or operator-triggered suggestion cycles and whether provenance can distinguish them. Determine
whether `FORECAST_V4_ENABLED` causes any compute despite zero consumers. Reconcile heartbeat and
reservation identity before recommending more instrumentation. Rank waste by single-developer
evenings saved, not theoretical scale.

### A6 — VIABLE-SET

Retain the v1.4 settled conditions. Audit the two-track funnel on the same source candidate:
champion calibrated versus #1200 raw eligibility observation. Determine whether rejection,
provenance, and cohort semantics are queryable without calling the raw clone “selected.” Quantify
how the legacy $100k shadow basis prevents comparison with the ~$2k live book. Audit whether the
condor-EV heuristic mis-ranks structures before downstream gates. Do not expand symbols or loosen
cost gates as a substitute for honest economics.

### A7 — DORMANT PHASE-3 EXIT EVIDENCE

Evidence gate remains approximately 3/10–15 instrumented live close fills.

- **Pass 1:** recompute the evidence-accrual ETA using live broker closes only; shadows and
  raw-eligibility observations do not count.
- **Pass 2:** `DEFERRED-DORMANT` unless enough new live fills exist.
- **Pass 3:** `DEFERRED-DORMANT` unless the gate opens.

Audit whether complete tape and exit-basis instrumentation can accelerate **measurement quality**,
not fabricate sample size. Preserve the Phase-3 stop doctrine.

### A8 — NEGATIVE-DECISION EFFICACY

Preserve the SOFI per-track sentinel: a shadow/raw clear can be designed; a champion/calibrated
clear is the alarm. Verify per-cycle rejection stamps distinguish scanner cost rejection from
ranker edge-floor rejection. Audit F-A9-5: logger reason currently compares dollar EV against a
score threshold even though routing uses score. Determine whether #1200 accepted/rejected verdicts
and champion rejection reasons preserve their distinct scopes and bases.

### A9 — ALERT & SIGNAL INTEGRITY

Continue the typed-column-lies inventory: prior #4 was `direction='long'`; find the next genuine
member. Include structural lies:

- absence of INFO before #1198 interpreted as “nothing happened”;
- pooled/routing figures labeled live before #1201;
- `decision_runs.git_sha='unknown'` despite deployment identity existing elsewhere;
- any success headline that suppresses partial experimental failure;
- any alert/dashboard that infers state from missing logs or stale summary rows.

Trace each lie to its consumer and operational consequence.

### A10 — CALENDAR & CLOCK (INCUMBENT, KEPT)

Walk expiry-day semantics from entry through early close, thesis terminal scoring, assignment, and
the Friday-expiry-to-Monday 72-hour tracker lag. Verify F-A10-1 summer warm-up state and Labor Day
2026-09-07 handling. Distinguish broker calendar, ET wall clock, UTC storage, scheduler timezone,
and process-local date. No schedule or clock recommendation may rely on weekday arithmetic when
the broker calendar is authoritative.

---

## REQUIRED OUTPUT — IN THIS ORDER

1. **Step-0 grounding** — host time, pinned SHA, dirty-state note, access limitations.
2. **One-paragraph executive verdict** — signal vs execution vs exit vs capital vs evidence
   integrity; name the single first operator decision.
3. **Current-state reconciliation table** — code state, packet attestation, disagreement,
   proof label.
4. **E1–E20 exclusion-integrity table** — `PASS | REOPENED | CONDITIONAL | NOT PROVEN`.
5. **W1–W5 observe-window table** — first valid boundary, emitter, sink, sample, bypass, verdict.
6. **A1–A10**, each with Pass 1/2/3 and findings in the required schema.
7. **Runtime-check list** — exact read/query/log needed, expected pass/fail evidence, and why code
   alone cannot settle it. Mark every item `NOT RUN`.
8. **Instrument-integrity list** — signal → emitter → boundary → durable sink → consumer → test
   reach → natural proof → verdict.
9. **Free look** — genuinely outside the charter; “none found” is acceptable.
10. **Dependency/collision matrix** — for each serious candidate: requires, unlocks/gates,
    overlaps, supersedes/duplicates, shared files/models/tables/flags, ordering, and collision risk.
11. **Ranked Top 3** — what, evidence, value, effort in single-developer evenings, risk,
    dependencies/collisions, backlog interaction, doctrine check, falsifier.
12. **Packet/ledger/code disagreements** — disagreements are high-value evidence.
13. **Design score** on the 85/90/95/100 scale, with confidence and explicit missing proof.
14. **STOP.** Implement nothing and make no external changes.

The report must be self-contained. Do not rely on prior reviewers’ prose as proof; trace the code.
Do not recommend an item already on the backlog unless you concretely improve its design,
dependency ordering, test seam, or falsifier and label it `EXTENDS-X`.
