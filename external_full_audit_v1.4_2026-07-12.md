# External Full Audit v1.4 — Ten-Area Deep Dive

**Issued:** 2026-07-12  
**Mode:** FULL; read-only code/research audit; three passes per area; Area 11 excluded  
**Repository:** `BrightBoost-Tech/options-trading-companion`  
**Implementation:** none. No build, test, configuration, database, broker, deployment, flag, stop, gate, or control was run or changed.

## 0. Clock, source pin, and evidence universe

**Audit clock.** The review workstation, explicitly rendered in `America/Chicago`, read **2026-07-12 10:22:15 CDT (UTC−05:00)** / **2026-07-12 15:22:15Z** at report close. The evidence ledger's latest runtime grounding read DB `now() = 2026-07-12 14:41Z = 09:41 CDT` and broker `10:41 EDT = 09:41 CDT`; those two production clocks agreed. I had no direct Supabase, Railway, or Alpaca access, so that packet/ledger clock is an attestation, not an independently repeated read. The brief's “Sunday evening” premise is incorrect: its own grounded runtime was Sunday morning.

**Moving-HEAD handling.** `origin/main` was [`d5edd503`](https://github.com/BrightBoost-Tech/options-trading-companion/commit/d5edd503a180c99a59f2ad619404955d94522daf) at audit start and advanced through #1188–#1192. Final audited repository HEAD is [`6edda833975a9d0551b6b142c67da34420b4905c`](https://github.com/BrightBoost-Tech/options-trading-companion/commit/6edda833975a9d0551b6b142c67da34420b4905c) (#1192) at 15:21:18Z; that last mover is ledger/backlog-only. Final behavior-changing HEAD is [`a6e0cb9b`](https://github.com/BrightBoost-Tech/options-trading-companion/commit/a6e0cb9b5b687d5c826d0da74bc3a945920f6c6e) (#1191). Most line-level links remain pinned to `9a540ced`, the last SHA at which those unchanged seams were read; #1191's diff was separately inspected and affects only known E6/①b close accounting plus tests/ledger, while #1192 changes documentation only.

**Evidence universe.** I treated the supplied v1.4 brief, repository packet [`audit/reports/2026-07-12.md`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/audit/reports/2026-07-12.md), and ledger runtime attestations as citable production truth; current source, migrations, tests, and commit contents are the independently reviewed code layer. Anything requiring DB, Railway, or broker truth is listed as an exact runtime check rather than inferred. Packet/code disagreements are preserved, not harmonized.

**EV basis, everywhere in this report.** The champion/live path currently persists and gates on **calibrated EV = 0.5 × raw EV**; selection ordering remains raw while W4 is off. #1190 intends shadow clones to use **raw EV**, but the implementation is partial and internally mixed: a clone's `ev` can be raw while its `risk_adjusted_ev` and its pre-clone decision snapshot remain calibrated, and upstream calibrated rejects never reach the cloner. Accordingly, every economic number below is labeled raw or calibrated. Scanner `net_ev` is also not the final executable-gate margin; it is raw scanner EV less scanner-modeled execution cost.

### Bottom line first

Three closure claims fail at the production seam:

1. **Critical — E8:** a failed position read still becomes a healthy empty book and a green q15 risk-monitor cycle.
2. **High — E16:** replay does not capture every terminal path; a replay commit error can still persist green; the morning context has no terminal output.
3. **High — E19:** raw-EV shadows are created only after a calibrated champion status gate, so the most informative calibrated rejects are selection-excluded; surviving shadow rows mix EV bases.

All three corrections would improve measurement/error truth without loosening a live control.

## 1. Fresh finding register

### F-E8-3 — Critical exclusion-integrity failure: a failed book read is still a green zero-position cycle

- **WHAT:** `_fetch_open_positions()` catches portfolio or position-query exceptions and returns `[]`. `_check_user()` treats `[]` as an authoritative empty book. The outer #1186 contract therefore sees no exception, records no failed user, and persists success. The sibling active-user discovery path similarly converts a database failure to `[]`, which can produce green `status=no_users` when no user ID is explicitly supplied.
- **WHERE:** [`_check_user` consumes the sentinel](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/jobs/handlers/intraday_risk_monitor.py#L190-L253); [`_fetch_open_positions` swallows the failures](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/jobs/handlers/intraday_risk_monitor.py#L629-L658); [active-user discovery has the same ambiguous sentinel](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/jobs/handlers/intraday_risk_monitor.py#L1663-L1675).
- **WHY:** `[]` has two incompatible meanings: “the authoritative book is empty” and “the authoritative read failed.” The typed error contract begins one layer above that ambiguity.
- **IMPACT:** One Supabase read failure can skip marks, stop evaluation, loss envelopes, force-close evaluation, and the two-position tripwire for the full account while the q15 job reports green. This is safety-control blindness, not merely missing telemetry.
- **EVIDENCE:** #1186's [test replaces `_check_user` itself](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/tests/test_e8_per_user_seam.py#L39-L47). It correctly proves the outer loop but cannot exercise a swallowed callee exception—the predecessor pattern the exclusion explicitly asked to hunt.
- **RISK:** Critical operational risk; fix risk low.
- **CONFIDENCE:** Very high, direct production-route code read.
- **RUNTIME CHECK:** Correlate Railway messages `"[RISK_MONITOR] Failed to fetch positions"` and `"Error fetching active users"` to the same-cycle `job_runs` record. A `succeeded` row with nested `positions: 0` or `status: no_users` confirms live exercise. Zero correlated events refutes incidence in the window only; it does not close the structural defect.

### F-E16-3 — High exclusion-integrity failure: replay “complete tape” and commit-health claims are false

- **WHAT:** The midday workflow has seven semantic terminal returns, but `_capture_decision_manifest()` is reached on only two. It misses `micro_tier_position_open`, capital-policy block, global-risk-budget exhaustion, `no_candidates`, and `scanner_failed`. Separately, a `DecisionContext.commit()` error is nested into `cycle_result.counts.errors`, then the handler replaces top-level errors with a roll-up that sums only `rejection_persist_failures`; the runner can still classify the job as succeeded. Finally, `suggestions_close` opens a replay context around the morning cycle, but the morning workflow emits no terminal decision feature.
- **WHERE:** The only two manifest calls are in the [late zero/happy paths](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/services/workflow_orchestrator.py#L3835-L3997). Commit error capture is [nested here](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/jobs/handlers/suggestions_open.py#L144-L152), while the later [roll-up ignores generic nested errors](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/jobs/handlers/suggestions_open.py#L26-L39).
- **WHY:** The new helper was tested in isolation rather than by driving every production terminal route. Error propagation was added at the cycle layer without verifying the existing job-level classifier input.
- **IMPACT:** A green decision run can still have inputs without an output, an entire scheduled morning context without a decision manifest, or a swallowed replay commit failure. Historical replay cannot distinguish “no decision” from “decision evidence missing,” defeating point-in-time learning and audit completeness.
- **EVIDENCE:** The [new tests call the helper directly](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/tests/test_replay_terminal_manifest.py#L1-L89), not the production returns or handler classifier. This directly contradicts #1188's “EVERY return,” “commit health,” and “Monday's tape is COMPLETE” closure language.
- **RISK:** High evidence-integrity risk; no direct capital mutation. Fix risk low.
- **CONFIDENCE:** Very high.
- **RUNTIME CHECK:** For every post-#1188 `decision_runs` row, require exactly one terminal `decision_features` row in namespace `ranked_candidates`. Group misses by `job_runs.result.cycle_results[].reason`; code predicts the five midday reasons above and all ordinary `suggestions_close` morning contexts. Separately query succeeded jobs whose nested cycle result contains `replay_commit_error` while top-level `counts.errors = 0`; any row confirms false-green commit health.

### F-E19-2 — High exclusion-integrity failure: raw shadows are selection-biased and mix EV bases

- **WHAT:** #1190 swaps `ev` to `source.ev_raw` only inside `_clone_suggestion_for_cohort()`. Production invokes the fork after the champion workflow, and the fork queries only champion rows with `status IN ('pending','staged')`. A candidate rejected upstream under calibrated EV as `NOT_EXECUTABLE/edge_below_minimum` cannot reach the raw-EV helper. For rows that do reach it, the clone does not persist `ev_raw` or an explicit `ev_basis`, inherits calibrated `risk_adjusted_ev`, and the cohort decision snapshot was already logged from the calibrated source.
- **WHERE:** [post-cycle fork invocation](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/jobs/handlers/suggestions_open.py#L159-L170); [pending/staged-only source query](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/policy_lab/fork.py#L44-L56); [upstream calibrated rejection](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/services/workflow_orchestrator.py#L3750-L3767); [raw `ev` swap plus inherited rank metric](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/policy_lab/fork.py#L326-L356); [calibrated pre-clone decision snapshot](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/policy_lab/fork.py#L399-L482).
- **WHY:** The unit test fabricates an already eligible source and calls only the helper. It does not drive scan → calibrated canonical decision → persisted status → source query → clone.
- **IMPACT:** The shadow experiment partially breathes but systematically excludes the exact names for which raw and calibrated canonical viability diverge. Surviving rows cannot cleanly attribute a verdict delta to EV basis versus cost basis, and rank-order evidence can use a calibrated rank metric beside a raw `ev`.
- **EVIDENCE:** On the packet's 07-10 candidates, QQQ is **raw EV 37.46 / calibrated EV 18.73**. With approximately $4.80 execution cost and the fixed $15 gate, the calibrated champion margin is `18.73 − 4.80 − 15 ≈ −$1.07`, while the raw-shadow margin is `37.46 − 4.80 − 15 ≈ +$17.66`; QQQ can survive far enough to be cloned. SOFI is **raw EV 39.8828 / calibrated EV 19.9414** but dies earlier at `edge_below_minimum`, so it contributes zero clones even though a raw-shadow clear is the designed result. The packet values are [here](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/audit/reports/2026-07-12.md#L29-L35), and the final gate is [here](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/paper_endpoints.py#L1335-L1382). On that observed-day shape, the upper bound is **up to two QQQ clones**—subject to score, slot, and held-symbol filters—and zero SOFI clones: low/interpretable volume, not a flood, but only a partial un-mute.
- **RISK:** High learning-volume and attribution risk; zero live-capital effect if corrected strictly in shadows. Fix risk medium because source eligibility and lineage change.
- **CONFIDENCE:** Very high.
- **RUNTIME CHECK:** After the first post-`9a540ced` scan, identify rows with `ev_raw != ev`, `status='NOT_EXECUTABLE'`, and `blocked_reason='edge_below_minimum'`; join to neutral/conservative clones by stable lineage if added, otherwise cycle+ticker+strategy+leg fingerprint. Any raw-pass source without its eligible shadow verdict confirms live exercise. For every actual clone, compare `ev`, `ev_raw`, `risk_adjusted_ev`, policy snapshot EV, and explicit basis; current code predicts `ev_raw IS NULL`, no basis stamp, and an inherited calibrated rank metric.

### F-A3-4 — High evidence-risk: the prequential validator fetches a different cohort from production

- **WHAT:** `fetch_live_outcomes(window_days=120)` does not use `window_days`, applies neither the corrupted-P&L floor nor `CALIBRATION_EV_EPOCH`, and returns `[]` on query failure. `main()` then reports `insufficient_data` and exits successfully.
- **WHERE:** [`prequential_validator.py`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/analytics/prequential_validator.py#L190-L239), versus the production cohort in [`calibration_service.py`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/analytics/calibration_service.py#L306-L358).
- **WHY:** The non-circular prefix-fitting math is shared correctly; its data-acquisition boundary is not. Tests exercise synthetic math, not query predicates or typed fetch failure.
- **IMPACT:** Packet state has nine broker closes but eight post-epoch learning closes. One model-incompatible row is 12.5% of the eight-row pool and can flip a tiny-n verdict. A database failure can masquerade as benign insufficiency.
- **EVIDENCE:** The [validator tests](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/tests/test_prequential_validator.py#L58-L103) stop at pure math.
- **RISK:** High to evidence quality; no direct live-control effect. Fix risk low.
- **CONFIDENCE:** High.
- **RUNTIME CHECK:** Count `learning_trade_outcomes_v3` live rows below the effective production epoch/corruption floor, then run the validator on the production-identical cohort and compare the verdict. `pre_epoch > 0` plus a changed metric confirms current impact; zero rows or byte-identical output refutes numerical impact, not the structural mismatch. Force a read failure in a non-production route test and require a typed failure, never `insufficient_data`.

### F-A9-5 — Medium: the negative-decision taxonomy compares dollars to a 0–100 score threshold

- **WHAT:** The real Policy-Lab eligibility predicate compares `sizing_metadata.score` with `min_score_threshold`. `_log_cohort_decisions()` instead compares dollar `ev` to that score threshold when assigning `ev_below_min`.
- **WHERE:** [actual score filter](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/policy_lab/fork.py#L233-L236); [mis-typed decision reason](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/policy_lab/fork.py#L466-L477).
- **WHY:** The same field name “threshold” is reused across incompatible units and the decision logger re-derives, rather than consumes, the routing predicate.
- **IMPACT:** Routing remains correct, but negative evidence lies. A score-70 / EV-$20 candidate can pass a score-50 filter yet be falsely tagged `ev_below_min`; a score-20 / EV-$60 candidate can fail the real score gate without that reason. The two-track rejection study cannot trust this reason distribution.
- **EVIDENCE:** Production source paths above; tests cover filtering, not the corresponding decision-log row.
- **RISK:** Medium analytical risk; low correction risk.
- **CONFIDENCE:** Very high.
- **RUNTIME CHECK:** Join `policy_decisions` to its source suggestion and cohort configuration. Any `ev_below_min` row with `sizing_metadata.score >= min_score_threshold`, or any below-score row lacking the score-failure reason, confirms incidence.

### F-WINDOW-1 — Medium: heartbeat and identity coverage cannot support the W1–W5 arm decisions claimed

- **WHAT:** Production has `APPLY_ORDER_HEARTBEAT` for W4 and a generic `EXECUTOR_SHADOW_HEARTBEAT` only after a Policy-Lab cohort clears preliminary config/portfolio paths. W1 has no gate-site heartbeat. W2's RBE, utilization, and allocator consumers have no per-site zero-evaluation heartbeat. W3 can miss its heartbeat before portfolio resolution. W4's heartbeat has no shared cycle ID. W5 cannot join apply-order and executor evidence into one composed observation. Separately, W3's decision record lacks ticker/suggestion/cohort/portfolio/cycle identity, so a two-candidate same-bucket cycle cannot reconstruct reservation order.
- **WHERE:** [`calibration_apply_ordering.py`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/analytics/calibration_apply_ordering.py#L113-L123); [`paper_autopilot_service.py`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/services/paper_autopilot_service.py#L974-L981); W1's [actual gate path](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/paper_endpoints.py#L1335-L1382).
- **WHY:** One generic loop heartbeat was treated as coverage for multiple downstream decision sites, without a common observation identity.
- **IMPACT:** Marker silence still cannot distinguish zero evaluation from a skipped path at the decision-site granularity required to arm W1/W2/W3/W5. W3 action safety is intact, but its evidence is not attributable enough to justify an arm.
- **EVIDENCE:** The #1187 [test calls the heartbeat helper directly](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/tests/test_arm_evidence_repair.py#L93-L100); it does not drive every window's zero-candidate production route.
- **RISK:** Medium governance/evidence risk. Any correction is observability-only.
- **CONFIDENCE:** High.
- **RUNTIME CHECK:** For a full scan cycle, require one row per window and per actual W2 decision site, all sharing one cycle/decision ID and carrying evaluated count—even zero. For a 2+ candidate same-bucket replay, require candidate identity, reservation order, pre/post exposure, cap, unknown flags, and resulting action. Current logs cannot satisfy that join.

### F-A10-4 — Low: expiry-day thesis rows remain in progress until the next weekday run

- **WHAT:** At the 17:00 CT tracker run, `expiry >= today` remains `in_progress`. A normal Friday expiry first becomes terminal at Monday 17:00 CT, about 72 hours later.
- **WHERE:** [`thesis_tracker.py`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/jobs/handlers/thesis_tracker.py#L70-L145); [weekday scheduler](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/scheduler.py#L72-L75).
- **WHY:** The terminal condition uses a date comparison suitable before close, while this job runs after close.
- **IMPACT:** Evidence latency only. Monday still selects the exact expiry-date close; a genuinely missing bar uses the disclosed fallback basis. Live expiration-day exit handling is independent and not impaired.
- **EVIDENCE:** Direct condition and schedule read.
- **RISK:** Low.
- **CONFIDENCE:** High.
- **RUNTIME CHECK:** For the Aug-21 tracker rows, compare Friday after 17:00 CT with Monday after 17:00 CT. Current code predicts Friday `in_progress`, then Monday `hit|miss` with `price_basis='expiry_close'` for a normal market day.

## 2. Ten-area audit — three passes each

### A1 — Profits

**Pass 1 — charter/state.** Retain. The area is earning because it now separates three different economics: raw scanner EV, calibrated champion EV, and the fixed final executable-cost gate. The n=8 outcome disqualifier remains binding; no strategy-outcome conclusion is justified from 1W/7L. The immediate learning problem is not a predicted raw-shadow flood—it is E19's selection-biased partial un-mute.

**Pass 2 — raw-shadow arithmetic and queue-⑤ make/fetch map.** The 07-10 QQQ example is interpretable: raw EV `37.46` clears the approximate raw shadow margin by `+$17.66`, while calibrated EV `18.73` misses the champion margin by about `−$1.07`. SOFI raw EV `39.8828` could be informative on the shadow basis, but calibrated EV `19.9414` triggers an upstream canonical rejection and the row never reaches the cloner. Thus the observed-day upper bound is up to two QQQ cohort clones and no SOFI clone, not four intended QQQ+SOFI clones and not an uncontrolled flood.

Queue-⑤ does not require a paid probability feed for an observe/replay v1. The repository already has a dormant independent lognormal terminal kernel: normal CDF/terminal `d2` and a piecewise spread EV approximation in [`opportunity_scorer.py`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/analytics/opportunity_scorer.py#L143-L180) and [its spread section](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/packages/quantum/analytics/opportunity_scorer.py#L318-L381). Reuse only the probability math: the wrapper fabricates defaults for missing spot/IV/DTE and is not right-aware enough for put/call orientation. Existing inputs include `underlying_iv_points` spot and 30-day IV, bracketing expiry IV/strikes, current candidate strikes/expiry/premium/chain Greeks, and—after #1188—recorded chain/bar replay blobs including cache hits. An H9-strict, call/put-aware terminal/breakeven probability can therefore be made from current data.

**Pass 3 — value/grade.** **A / EARNING.** Queue-⑤ remains the strongest strategy-side build already approved, but E19 must first let raw-shadow candidates reach the experiment and stamp a coherent basis. No live gate, calibration floor, or exit control should move on this evidence.

### A2 — Losses

**Pass 1 — state.** E6's core broker-ack invariant remains present: deterministic client ID, typed manual-review state, duplicate-422 classification, reconciler Step 1.5, and 404→`cancelled` re-arm. **State advanced during the audit:** #1191/`a6e0cb9` ships known ①b. `_close_position()` now captures `submit_and_track()`; `needs_manual_review` returns `routed_to='needs_manual_review'`, and `_close_completed()` makes that route non-completed beside `deferred_uncorroborated` and `unknown_reconciling`. Consequently the monitor should not count a force close, write cooldown, or suppress same-cycle handling. The diff reaches both relevant production sites and replaces the former source-string pin with a behavioral helper test. Code verdict: PASS; first live/manual-review runtime pin remains. Residual partial-close custody remains known-open and trigger-gated.

**Pass 2 — re-arm economics.** A rolling bound exists: a fresh cancel blocks 30 minutes, and three terminal-failed order rows within four hours suspend retries and alert. One logical order can make up to three duplicate-safe API submits with the same client ID, so the outer three-event budget represents up to nine API calls but not nine distinct broker orders. There is no lifetime-attempt or prior-price-drift ceiling. That is not by itself a defect: every re-stage intentionally uses a fresh decision mark/executable quote, and a protective close should not be disabled merely because the market moved adversely. The next design review should distinguish pathological retry churn from deliberate repricing, rather than add a loss-sensitive stop.

**Pass 3 — first two-position day.** The clean alarm path is credible: live-scoped exact set → onset dedup → critical canonical alert → immediate webhook → stored egress receipt. The test mocks `_log_alert`, so the full path still needs its first live pin. Runtime criterion: on the first 2-position cycle, exactly one `risk_alerts.alert_type='concurrent_live_positions_uncontrolled'` row for the exact position set, with a successful receipt, must appear within one q15 interval. **Grade: A− / EARNING**, with E8 now the dominant upstream threat because a failed book read prevents this entire path from seeing the positions.

### A3 — Self-learning

**Pass 1 — three-way join.** Thesis, realized P&L, and close reason are readable in one row now:

```sql
select position_id, symbol, routing_mode, execution_mode, structure,
       thesis_outcome, realized_pl, close_reason, price_basis
from position_thesis_outcomes
where thesis_outcome in ('hit','miss')
order by scored_at, position_id;
```

Repository search found no analytical consumer. The system can answer “thesis hit + realized loss + stopped” manually, but nothing computes that causal conversion as a standing metric. That is a measurement opportunity, not authorization to change the stop.

**Pass 2 — validator and DTE dependency.** E17's pure prefix-fit remains non-circular, but F-A3-4 breaks acquisition parity. Known F-A3-2 also couples directly: `_classify_dte()` expects DTE fields, while production and prequential selects omit them; all fetched observations become `unknown`. At current state the `unknown` and `_all` aggregates are identical, so segmentation is disabled rather than necessarily biasing the aggregate. Worse, validator output does not disclose the bucket, so the degradation is invisible.

**Pass 3 — value/grade.** **A / EARNING.** The three-way table is decision-grade only after basis/lineage and acquisition parity are enforced. First operator read should be the one-query conversion table above; first code correction in this area would make the prequential fetch exactly share production filters and typed failure semantics. E10 is code-complete but runtime-unpinned at its writer; E11 passes with explicit price basis; E13 passes narrowly in source, pending runtime `pg_get_viewdef` identity.

### A4 — Self-sustaining

**Pass 1 — charter/state.** Retain. This remains the highest-yield operational area. The external dead-man is proven: [`run-nightly.cmd`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/9a540ced330169263e2d8f11917616c1a9dc4b74/audit/run-nightly.cmd#L10-L29) withholds its health ping unless the dated report exists, and the packet attests that Saturday's DOWN email arrived after the sleep-killed run.

**Pass 2 — third-layer and heartbeat hunts.** F-E8-3 is the exact third layer inside #1186: the failed read becomes an empty sentinel before the repaired loop can type it. F-WINDOW-1 contradicts the “every window even at zero” heartbeat claim: only W4 and part of the executor loop are covered; W1/W2/W3/W5 decision-site and identity coverage is incomplete.

**Pass 3 — value/grade.** **A+ / EARNING.** The dead-man demonstrated real value, and this pass killed another one-layer-too-high closure. Operator-side sleep-hold remains outside this repo. The first repo decision should be the E8 sentinel correction; it tightens protection truth and requires no control-policy debate.

### A5 — Efficiency

**Pass 1 — charter/state.** Retain, but measure actual storage before optimizing it. E16 means “complete-tape” growth assumptions are not yet valid.

**Pass 2 — tape and shadow cost math.** The scheduler wraps approximately two decision contexts per active user per trading day—about 10/week or 42/month. The ledger forecast is about **70 MB/month**, or **0.85 GB/year**. A 14-day TTL would settle near **33 MB** at that rate. If per-contract Greeks enlarge chain payloads by 2–5×, annual volume becomes roughly **1.7–4.25 GB**, and 14-day steady state roughly **65–163 MB**. These are forecasts, not bounds: `REPLAY_MAX_BLOB_BYTES=2 MB` only warns and still stages the blob. Content-addressed cache hits mostly add references, while option chains dominate payload.

E19 does not rerun market-data scanning: the fork is post-cycle. It can add up to two clone inserts/executor evaluations per accepted source under the current three-cohort layout; the present calibrated source gate keeps actual volume lower and biased. Correcting E19 could increase shadow DB/executor work, but it remains small beside the chain scan and should be measured, not assumed.

**Pass 3 — value/grade.** **A / EARNING.** First obtain daily logical/stored bytes, dedupe ratio, run/input/feature counts by strategy, and missing-manifest counts. A TTL remains sensible backlog work, but completeness and commit truth outrank storage tuning.

### A6 — Viable-set handling

**Pass 1 — settled conditions.** No named viable-set reopener fired: capital tier remains about $2,068, the calibrated funnel remains near zero by owner decision, and existing spread-economics verdicts stand. Do not reopen those conclusions from this code audit.

**Pass 2 — two-track observability.** The same candidate can receive champion-calibrated and shadow-raw verdicts, but the delta is not causally queryable. The row can mix raw `ev`, calibrated `risk_adjusted_ev`, calibrated pre-clone policy snapshot, and a different per-contract-vs-legacy cost gate. There is no explicit `ev_basis`, both EV margins, both cost margins, or stable source→clone ID. A divergence therefore cannot be assigned to EV basis, cost basis, or cohort policy.

**Pass 3 — value/grade.** **A− / EARNING but evidence-defective.** The minimally honest observation is a 2×2 stamp: raw vs calibrated EV and legacy-sized vs per-contract cost margin, with a single lineage ID and the actual predicate result at each seam. This extends D② measurement; it does not relitigate the live champion or W1.

### A7 — Dormant exit-quality charter

**Pass 1 — reinstatement shape.** The correct counter is **3/10–15 instrumented fills**, not nine all-time closes. Seven additional qualifying fills are required to reach 10; 12 are required to reach 15.

**Pass 2 — ETA.** At about one decision-grade live close per week, the earliest 10-fill threshold is around **2026-08-30** and the 15-fill threshold around **2026-10-04**. Raw shadows can add synthetic close rows faster, but their internal fill fiction is not broker-acknowledged exit-quality evidence.

**Pass 3 — value/grade.** **DORMANT / correctly withheld.** Shadows may accelerate mechanism learning, not the causal Phase-3 gate. No stop or exit threshold recommendation is justified before the instrumented live counter and quote-quality evidence mature.

### A8 — Negative-decision efficacy

**Pass 1 — sentinel by track.** The sentinel must be bifurcated: a **champion/calibrated SOFI clear** remains an alarm; a **shadow/raw SOFI clear** is the intended D② experiment. On 07-10, champion SOFI calibrated EV was `19.9414` and remained blocked. E19 currently prevents the corresponding raw experiment from existing.

**Pass 2 — taxonomy.** Champion and shadow rejects do not carry sufficient, coherent basis stamps. F-A9-5 additionally makes `ev_below_min` unreliable by comparing EV dollars to a score threshold. The rejection row cannot self-repair historically because the snapshot omits the decisive score, typed threshold, EV basis, and lineage.

**Pass 3 — value/grade.** **A− / EARNING.** Make the logger consume the exact typed predicate result emitted by routing, rather than re-derive it. Then stamp champion/calibrated and shadow/raw explicitly. This changes evidence only; routing stays byte-identical.

### A9 — Alert and signal integrity

**Pass 1 — charter/state.** Retain. This pass found one active taxonomy lie and one arm-evidence class, while not promoting an unproven typed-column seam.

**Pass 2 — findings.** F-A9-5 corrupts negative-decision reason evidence. F-WINDOW-1 means the current heartbeats cannot prove every window ran or compose W5. W3's enforcement action itself remains safe: armed plus unknown risk or unreadable equity blocks through `bucket_enforcement_action`; no bypass into an armed proceed was found. Its log, however, lacks enough identity to reconstruct a 2+ candidate reservation sequence.

Typed-column inventory #5 is a **near miss, not a finding**: staging stores `paper_orders.side = ticket.legs[0].action`, while close-idempotency readers infer aggregate side from position quantity. Canonical leg ordering currently makes these agree. A custom/reordered multileg ticket could evade the duplicate-close guard, but no active row or production-route test proves incidence. Runtime promotion condition: any staged close whose stored side disagrees with aggregate position-derived side, or any duplicate close attributable to it.

**Pass 3 — value/grade.** **A− / EARNING.** Fix reason truth and observation identity before using shadow logs for promotion/arm decisions. Do not redefine the allocator's continuous delta as a fake binary “flip”; W2b's site-specific semantics remain the honest design.

### A10 — Calendar and clock

**Pass 1 — state.** E15 winter-close passes: session detection uses `America/New_York` wall clock. The fixed 14:30Z summer warm-up blind remains known-pending, not shipped. Labor Day remains known-pending because scheduler jobs are Monday–Friday and `is_market_day()` is weekday-only despite claiming scheduler holiday handling.

**Pass 2 — expiry-day walk.** Live exit logic computes DTE zero and has an independent expiration-day close condition, so F-A10-4 delays only the tracker. At the Friday Aug-21 17:00 CT tracker run, rows remain `in_progress`; Monday's run should score from the exact Aug-21 close with `price_basis='expiry_close'`. An early-closed live position does not change the thesis horizon; the intended-horizon grading remains at expiry, while realized P&L and close reason remain separately readable.

**Pass 3 — value/grade.** **B+ / still earning.** The new finding is low-severity latency. The more important open clock risks remain the summer warm-up and Labor Day job execution, both already filed. No new import-time flag was found beyond the known inventory.

## 3. Consolidated runtime checks — priority order

These are read-only confirmations/refutations for the operator or the data-side reviewer.

1. **P0 — E8 failed-read truth.** Correlate risk-monitor failure log strings to `job_runs`. Confirm if the same cycle is `succeeded` with zero positions/no users; refute incidence only if there are no pairs. A production-route fault test must inject the exception inside the positions query, not mock `_check_user`.
2. **P0 — E16 terminal completeness and health.** Left-join every post-#1188 `decision_runs` row to exactly one `decision_features(namespace='ranked_candidates')`. Break out `suggestions_open` and `suggestions_close`, then group missing rows by cycle terminal reason. Query succeeded jobs with nested `replay_commit_error` and top-level zero errors.
3. **P1 — E19 raw-shadow reachability and basis.** For each raw-clear/calibrated-fail source, require a lineage-linked neutral/conservative verdict. On each clone require raw `ev`, raw `ev_raw`, explicit `ev_basis`, raw-recomputed rank metric, and both raw/calibrated plus legacy/per-contract margins. Current code predicts missing upstream clones and mixed-basis survivors.
4. **P1 — W1–W5 site coverage.** For one complete zero-candidate and one nonzero scan, require a shared cycle ID across per-window/per-site heartbeat rows. For W3 with 2+ same-bucket candidates, require candidate IDs, reservation order, pre/post exposure, cap, unknown state, and action. Absence confirms the evidence window is not armable.
5. **P1 — prequential cohort parity.** Count live learning rows before the calibration epoch or below the corruption floor; compare current and production-identical prequential results. Force a read error in a non-production route test and require typed failure.
6. **P1 — three-way conversion table.** Run the A3 query over resolved outcomes and report counts of `thesis_outcome × sign(realized_pl) × close_reason × price_basis`. This is the data needed to distinguish thesis from execution/exit conversion; it must not itself change a stop.
7. **P1 — Policy-Lab reason truth.** Join decision rows to source score and cohort threshold. Confirm if `ev_below_min` disagrees with the actual score predicate.
8. **P1 — first two-position tripwire.** On the first changed book, require one exact-set critical alert and successful receipt within q15; confirm dedup on unchanged subsequent cycles.
9. **P2 — replay storage baseline.** Daily: blob count, `sum(size_bytes)`, stored payload bytes, decision runs/inputs/features by strategy, dedupe ratio, and missing-manifest count. Do not choose a TTL from the 70 MB/month estimate alone.
10. **P2 — E10 first-close pin.** On the first post-fix live close, require staged order `close_reason` to equal the final position/outcome reason, with no best-effort writer loss.
11. **P2 — E13 deployed view identity.** Read `pg_get_viewdef('public.learning_trade_outcomes_v3'::regclass, true)` and require both intended raw-EV/raw-PoP `COALESCE` expressions.
12. **P2 — Aug-21 expiry transition.** Friday after 17:00 CT should still show `in_progress`; Monday should show terminal verdict and exact expiry-close basis under current code.
13. **P2 — typed-side near-miss.** Compare staged multileg close `paper_orders.side` to position-quantity-derived aggregate side. Promote only if a mismatch or duplicate-close consequence exists.
14. **P2 — Labor Day.** On 2026-09-07, read scheduler/job rows and broker clock. Current code predicts weekday jobs enqueue despite `is_open=false`; downstream gates may prevent trading but do not make the calendar claim true.

Executable read templates where the checked schema is known:

```sql
-- E16: any row is a terminal-manifest integrity failure.
select r.strategy_name, r.decision_id, r.as_of_ts, r.status,
       count(f.decision_id) as terminal_manifests
from decision_runs r
left join decision_features f
  on f.decision_id = r.decision_id
 and f.symbol = '__decision__'
 and f.namespace = 'ranked_candidates'
where r.created_at >= timestamptz '2026-07-12 14:52:01+00'
group by r.strategy_name, r.decision_id, r.as_of_ts, r.status
having count(f.decision_id) <> 1
order by r.as_of_ts;

-- Replay storage: measure logical versus stored bytes; do not infer completeness.
select date_trunc('day', created_at) as day,
       count(*) as blobs,
       sum(size_bytes) as logical_bytes,
       sum(octet_length(payload)) as stored_bytes
from data_blobs
group by 1
order by 1;

-- Prequential acquisition parity: compare this count with the production cutoff.
select count(*) as all_live,
       count(*) filter (
         where closed_at < timestamptz '2026-06-11 00:00:00+00'
       ) as pre_epoch
from learning_trade_outcomes_v3
where user_id = :uid and is_paper = false;

-- First 2-position alarm: require one exact-set row and a successful receipt.
select created_at,
       metadata->>'position_set' as position_set,
       metadata->'egress_receipt' as receipt
from risk_alerts
where alert_type = 'concurrent_live_positions_uncontrolled'
order by created_at desc;

-- E13: deployed identity, not migration-file identity.
select pg_get_viewdef('public.learning_trade_outcomes_v3'::regclass, true);
```

## 4. Free look

The free-look allowance was spent on two outside-charter seams:

- **Retry provenance:** the original #1104 transient retry exists, but it reuses the same stale Supabase client. The known-open item is the stronger reconnect-before-retry residual; this reconciles the ledger wording and is not a fresh finding.
- **Typed-column inventory #5:** `paper_orders.side` can theoretically disagree with aggregate close side for reordered/custom multileg tickets. Canonical current ordering prevents a proven defect, so it remains the runtime-conditioned near miss in A9 rather than an inflated finding.

No additional fresh issue survived the predecessor bar.

## 5. Exclusion-integrity review

Conditionals are checked first, as required.

| Exclusion | Verdict at final HEAD | Seam/test judgment |
|---|---|---|
| **E14 conditional** | **PASS.** Shipped at [`74b71708`](https://github.com/BrightBoost-Tech/options-trading-companion/commit/74b71708cb3d6614770909a43508087f11dcebb0); packet attests 33/33 supervised backfill, typed=JSON, zero contamination. Trust begins at this SHA. | Production cloner is normalized; test reaches it; explicit unknown remains `NULL`, not fabricated zero. |
| **E16 conditional** | **FAIL — exclusion-integrity.** Shipped #1188, but five midday returns, the morning terminal output, and job-level commit health remain open. | Tests call helper, not all production returns or classifier. “Tape complete” is false. |
| **E19 conditional** | **FAIL — exclusion-integrity.** Shipped #1190, but raw logic sits after calibrated eligibility; surviving rows mix bases. | Tests call helper with an already eligible source; they do not cross the canonical status gate. |
| E1 | PASS / settled. Calibration flag and 0.5 floor decision stand; no 8/8 re-litigation. | Changed condition not found. |
| E2 | PASS in code; W1 observe-only. | Per-contract path exists; runtime arm evidence remains separate. |
| E3 | PASS / settled. | No contrary path found. |
| E4 | PASS. | Sign-fix closure not contradicted. |
| E5 | PASS. | OBP capital read remains fail-closed. |
| E6 | Core PASS; ①b code-PASS at #1191; residual partial close remains open. | #1191 reaches `_close_position` and monitor completion accounting through the tested `_close_completed` seam. Runtime first-occurrence pin remains; residual custody is unchanged. |
| E7 | PASS in code, runtime first ≥2-survivor ordering still pending. | Active route and post-rerank limit intact. |
| **E8** | **FAIL — exclusion-integrity.** #1186 fixes the outer loop, but inner reads still swallow to `[]`. | Test mocks the very seam whose callees needed exercise. |
| E9 | Known-open state verified. | Original retry exists; reconnect-before-retry residual is unshipped. No re-finding. |
| E10 | Code PASS, runtime writer pin pending. | Reader/mapping/ingest covered; writer remains best-effort. |
| E11 | PASS. | Exact/fallback/unknown price basis is explicit; pre-#1185 rows remain annotated partial. |
| E12 | PASS as corrected closure. | Credit cohort remains non-evaluable until independent probability queue-⑤; no premature evaluability claim made here. |
| E13 | Narrow code PASS. | Migration and guard retain `COALESCE`; deployed view identity remains runtime check. |
| E15 | Winter PASS; summer sibling remains known-pending. | No claim that the fixed 14:30Z warm-up is corrected. |
| E17 | Narrow PASS on non-circular math; **fresh adjacent F-A3-4** at acquisition boundary. | Pure-math tests do not prove cohort/failure parity. |
| E18 | PASS. | Terminal clamp and deleted stale path remain shipped. |

## 6. Observe-window integrity

| Window | Control state | Integrity verdict | Trust clock / arm consequence |
|---|---|---|---|
| **W1 — gate quantity** | OFF | Core code pass; **heartbeat claim fails** because actual final gate has no W1 site heartbeat. | Original `655c9aa` behavior clock may stand, but silence cannot prove a zero-evaluation cycle. No arm recommendation. |
| **W2 — max-loss basis** | OFF | Partial: RBE identity/threshold improved; utilization and allocator W2b remain known-pending; no per-consumer heartbeat. | Shadow-risk rows trustworthy only from E14 `74b7170`; W2 is not ready for composed arm. |
| **W3 — bucket control** | OFF | Enforcement safety passes: armed+unknown/unreadable blocks through the single action seam; no bypass found. Evidence identity/heartbeat is inadequate for 2+ candidate attribution. | Risk data trustworthy from `74b7170`; effective evidence clock should use that later SHA. Changed-book early reopen did not occur; arm remains NO. |
| **W4 — calibration apply order** | OFF | Full structural ordering comparison passes. APPLY_ORDER heartbeat exists but lacks shared cycle ID and cannot cover earlier workflow skips. | Structural clock from `d5edd50`; evidence useful but not composable alone. |
| **W5 — composed arm** | NO | **Not armable.** W2b is incomplete and apply/executor heartbeats cannot be joined into one decision observation. | D③'s “package GO, arm NO” remains correct. One week of logs cannot cure an unobservable seam. |

## 7. Ranked top three operator decisions

### 1. Make failed risk-monitor reads typed failures, never empty sentinels

- **WHAT:** Separate authoritative empty results from read failure in `_fetch_open_positions()` and active-user discovery; carry the error through `_check_user` and the real runner classifier. Add a production-route test that injects failure at the query callee.
- **EVIDENCE:** F-E8-3. Current `[]` skips every q15 protection function while #1186's test mocks `_check_user` and therefore cannot see it.
- **VALUE:** Highest. Restores truth to marks, stops, loss envelopes, force closes, and the two-position alarm simultaneously.
- **EFFORT:** **<1 single-developer evening.** The outer typed-failure contract already exists; this is sentinel typing plus route tests.
- **RISK:** Low implementation risk; operationally it may expose retries/failed jobs that were previously hidden, which is the intended truth.
- **DOCTRINE CHECK:** Tightens a safety control's measurement. It loosens nothing and requires no loss-based policy justification.
- **FALSIFIER:** A route-driving test that causes each portfolio/user query failure and proves the real job records failed/partial—not zero positions/no users—would falsify the finding. Merely showing no recent runtime occurrence would not.

### 2. Complete replay at every production terminal route and propagate commit health to the runner

- **WHAT:** Centralize terminal finalization so all seven midday exits and the morning cycle emit exactly one manifest; make generic replay commit failure contribute to top-level job health; test the production routes and classifier, not the helper.
- **EVIDENCE:** F-E16-3: five missing midday paths, no morning terminal feature, and nested commit errors omitted from `_persist_error_rollup`.
- **VALUE:** Very high. The system learns at about one live close/week; replay is the only scalable point-in-time evidence source, and incomplete green tapes manufacture false negatives.
- **EFFORT:** **About 1 evening.** Shared manifest helper and replay context already exist; work is route centralization, morning terminal contract, roll-up, and integration tests.
- **RISK:** Low. More feature rows and some jobs correctly becoming partial/failed; no trading-decision change.
- **DOCTRINE CHECK:** Evidence and health truth only. No stop, gate, sizing, or capital control loosening.
- **FALSIFIER:** Production-route tests enumerate every semantic return and prove exactly one manifest, plus a forced commit error makes the real handler/runner non-green. Runtime post-SHA joins must show zero missing manifests for both strategies.

### 3. Move raw-shadow eligibility before calibrated rejection and stamp one coherent causal basis

- **WHAT:** Let shadow cohorts evaluate raw EV even when the champion is canonically rejected, while keeping champion behavior byte-identical. Recompute raw rank metrics; persist `ev_basis`, both raw/calibrated EV margins, both relevant cost margins, and stable source→clone lineage. Make the route test start before the calibrated rejection.
- **EVIDENCE:** F-E19-2. SOFI raw `39.8828` is selection-excluded; QQQ may clone, but clone `ev` can be raw beside calibrated `risk_adjusted_ev` and calibrated policy snapshots.
- **VALUE:** High. Restores the experiment's intended low/interpretable volume and makes the champion-vs-shadow delta attributable rather than mixed.
- **EFFORT:** **About 1 evening**, possibly two if schema provenance fields need a migration. Existing fork, raw flag, cloner, and cohort machinery reduce the work.
- **RISK:** Medium to shadow evidence volume and fill-fiction interpretation; zero live-capital risk only if champion routing remains byte-identical and clones stay simulated.
- **DOCTRINE CHECK:** This is a proven shadow measurement-path error, not a live gate loosening. It must not alter the calibrated champion or count synthetic fills toward Phase-3 live evidence.
- **FALSIFIER:** A full scan-route test in which a raw-clear/calibrated-fail candidate produces correctly linked raw cohorts with recomputed raw ranks and explicit bases would falsify it; runtime lineage must also show no eligible upstream reject is missing.

## 8. Packet/ledger versus code disagreements

1. **Clock premise:** “Sunday evening” disagrees with the packet's own DB/broker grounding at 09:41 CDT Sunday morning.
2. **E8 closure:** “no per-user fatal can read green at ANY layer” disagrees with the inner portfolio/user reads that convert failure to an empty sentinel.
3. **E16 closure:** #1188 says manifest at every return, commit health surfaced, and tape complete. Code has five uncaptured midday exits, no morning terminal output, and a nested commit failure that can remain green.
4. **E19 closure:** #1190 says the experiment layer breathes and shadows score on raw. Code permits only calibrated-eligible source rows into the cloner and mixes raw `ev` with calibrated rank/snapshot evidence.
5. **Observe heartbeat claim:** “every window even at zero” disagrees with only W4 plus a partial generic executor heartbeat, without W1/W2 site coverage or W5 join identity.
6. **E14:** no disagreement. Code and packet backfill attestation agree; trust begins at `74b7170`.
7. **E6/①b:** state advanced under the audit. It was open at `9a540ced` and code-complete at final HEAD `a6e0cb9`; the final report uses the latter and leaves only its first runtime pin plus known residual partial-close custody.
8. **#1104:** apparent wording tension is reconcilable, not a finding: the original retry shipped; reconnect-before-retry hardening remains orphaned/open.

## 9. Honest overall verdict and first change

The evidence does **not** presently support “signal problem” as the primary diagnosis: the packet reports **13/16 resolved theses hit (81%)**, albeit with five horizons still in progress and a tiny, censored sample, while live post-epoch performance is **1W/7L and −$178**. The defensible label is therefore **downstream conversion/evidence-integrity problem, amplified by capital friction**: predictions appear directionally promising, but execution/exit measurement and four-leg economics at roughly $2,067.86 fail to convert them into realized profit. It is too early to call the stop itself wrong because Phase-3 has only **3/10–15 instrumented fills**; stop territory remains owned by that gate. Capital is a real constraint, but it does not explain false-green monitoring, incomplete replay, or mixed-basis shadow evidence. The **single first change** should be E8's failed-read typing because it restores the truth of every q15 protection cycle with no policy loosening. The external code reviewer should independently re-check the three production-route seams—E8 callee failure propagation, E16 every-return/runner health, and E19 pre-rejection cohort branching—while the data-side reviewer runs runtime checks 1–8. Any disagreement between those two views is the next highest-value evidence.

---

**Stop.** This report makes operator recommendations only. Nothing was built or changed.
