# External Full Audit v1.3 — Ten-Area Deep Dive

**Repository:** `BrightBoost-Tech/options-trading-companion`  
**Audit finalization clock:** 2026-07-12 02:28:33Z / 2026-07-11 21:28:33 CDT (`America/Chicago`)  
**Audit-start `origin/main`:** [`17f84d9`](https://github.com/BrightBoost-Tech/options-trading-companion/commit/17f84d995788aa056b427c9b1d27eca0d31ca2e5)  
**Final `origin/main` at this freeze:** [`b761a3f`](https://github.com/BrightBoost-Tech/options-trading-companion/commit/b761a3f89efec2415da5c7345c6ff96fd0bd2a7f), a documentation wrap  
**Final runtime-relevant code SHA:** [`1b8217b`](https://github.com/BrightBoost-Tech/options-trading-companion/commit/1b8217b40ac2dda569fa81d6320dce0bd07f4a06)  
**Mode:** Read-only. No build, test run, code/config/PR change, database/broker action, or stop/gate/control change was performed.

## Clock and evidence boundary

| Source | Grounded value | Treatment |
|---|---|---|
| Reviewer UTC | 2026-07-12 02:28:33Z | Common clock |
| Reviewer Chicago time | 2026-07-11 21:28:33 CDT | Operator-local rendering |
| GitHub `main` | `b761a3f` | Final repository/document state |
| Runtime-relevant code | `1b8217b` | Final cold-code basis |
| Packet/ledger state | Through approximately 2026-07-12 02:30Z as stated in the brief | Accepted runtime attestations |
| Supabase `now()` / deployed SHA | Unavailable | Runtime check; never inferred |
| Railway clocks, effective env and logs | Unavailable | Runtime check; never inferred |
| Alpaca clock, positions, orders and activities | Unavailable | Runtime check; never inferred |

The audit began at the prompt’s exact pin, `17f84d9`. During the read, E18 landed in two commits: terminal `calculate_pop` clamp/logging (`aca743a`) and deletion of dead `forecast_ev_pop` (`1b8217b`), followed by docs-only `b761a3f`. E18 is therefore evaluated against the later HEAD and passes. The intervening changes do not alter the findings below.

Evidence is limited to the full GitHub repository, tests, migrations, doctrine, packet, ledger, backlog, prior reports and adjudications. Packet/ledger runtime attestations are accepted; code determines what the system can do. Where runtime is required, the report gives an exact confirm/refute check rather than guessing.

### EV basis

- Production calibration remains **`EV_cal = 0.5 × EV_raw`** at the current post-sizing site because W4 is unarmed.
- Every profit number below states whether it is raw or calibrated.
- Entry viability uses **per-contract executable round-trip cost** and the unchanged `$15` per-contract minimum edge.
- The current condition is `0.5 × EV_raw − executable_cost_per_contract ≥ $15`.

## Executive verdict

The thesis tracker materially changes the diagnosis: **13/16 theses hit (81%), including 5/7 live, but only 4/13 hits were profitable**. The signal now appears real enough to move the primary diagnosis downstream. This is not permission to relax stops; it is evidence that execution, structure economics and exits deserve measurement priority.

The weekend’s proposed profit path is nevertheless still blocked. E12 changed credit-spread PoP from `credit/width` to `1−credit/width`, but that replacement is the payoff-implied break-even win rate. Feeding it into the same binary payoff formula makes every valid credit vertical’s modeled EV **identically $0**. The “credit cohort is evaluable” closure claim is false.

The strongest live-control finding is a second E8 false-green seam: `intraday_risk_monitor.run()` raises outer failures, but its normal per-user loop catches a complete user protection failure and still returns `ok:true,status:completed`. On this one-user account, an entire q15 risk cycle can still fail green.

The new replay/observe evidence plane is also not decision-grade: no-trade cycles return before decision-output capture; cache-hit inputs are absent; W2 never emits a non-null `would_flip`; W4 compares ticker-only orderings; and W3 treats unknown risk as zero while hiding it in the log. Four of five observe windows are therefore not armable from their current evidence.

## Finding register

| ID | Severity | Finding | Consequence |
|---|---:|---|---|
| F-A4-E8 | Critical | Per-user intraday-monitor failure is caught and returned green | A complete q15 protection cycle can still fail green on the normal one-user account |
| F-A1/A6-E12 | High | Credit vertical PoP is payoff-derived, forcing EV to exactly zero | The newly “evaluable” two-leg credit cohort remains structurally blocked |
| F-A4-E16 | High | Replay misses zero-decision outputs, rejected tails, cache-hit inputs and commit health | Monday tape can be green but non-reproducible, especially on the near-zero funnel |
| F-A2-1 | High | Partial multileg closes do not update residual DB quantity | A re-arm can close stale full quantity, over-close/reverse, or age into assignment |
| F-W3 | High | Unknown open/candidate risk is converted to $0 and hidden | Armed bucket control can silently allow exposure; W3 is not armable |
| F-A9-E14 | High | Policy-Lab clones drop top-level risk and fail to rescale JSON totals | Clone fills persist `max_loss_total=NULL`; W2/W3 evidence is contaminated |
| F-W2/W5 | High | All W2 production callers omit the threshold; `would_flip` is always `None` | One week of logs cannot justify W2 or the composed W5 arm decision |
| F-A10-1 | High | Fixed 14:30Z RTH warm-up creates a summer first-hour health blind spot | RTH job failure can remain healthy 80–105 minutes after an EDT open |
| F-A8/E6-edge | Medium-high | Known `needs_manual_review` submit failure is discarded and reported as routed success | False force-close alerts/counts/cooldowns and same-cycle close suppression |
| F-A3-1 | Medium-high | Resolved position suggestion fallback is discarded at outcome insertion | A real close can vanish from calibration/prequential despite a valid position link |
| F-W4 | Medium-high | Calibration ordering is compared by ticker only | Same-ticker structure swaps produce false `would_differ=False` |
| F-A3-2 | Medium | DTE calibration inputs are never fetched | Every outcome is classified into DTE bucket `unknown` |
| F-A3-3 | Medium | E13 guard checks committed migration syntax, not deployed view identity | Drop/rename/dynamic/manual drift can pass while runtime view is wrong |
| F-A5-1 | Medium | Replay “2 MB max” is warning-only and retention is unbuilt | Capture growth is unbounded until measured/reaped |
| F-A10-2 | Conditional | Weekend-only age subtraction can false-late after Monday holidays | Tuesday health may inherit a 39-hour apparent gap if no holiday result exists |
| F-A10-3 | Low | New import-pinned `A4_MIN_HOLD_BARS` is absent from inventory | Env changes can remain stale and alter learning detail until recycle |

---

# A1 — PROFITS

## Pass 1 — charter verdict

**Load-bearing, with a now-measured downstream diagnosis.** The 81% thesis hit rate means signal is no longer the best working explanation for the 1W/7L post-epoch ledger. Only 4/13 thesis hits becoming profitable points to execution, structure economics and exits. It does not identify which exit threshold is wrong and does not authorize relaxation.

For the incumbent IC/debit set, the binding constraint remains calibrated EV density versus executable friction and the $15 floor. For the proposed credit vertical, the binding constraint occurs earlier: its probability and payoff use the same ratio, so its modeled EV cannot be positive.

## Pass 2 — findings

Core paths read: two-leg scanner construction → `calculate_pop`/`calculate_ev` → execution-cost rejection → canonical ranker; calibration/risk observe windows; packet economics; weekend closure commits and tests.

### F-A1/A6-E12 — High exclusion-integrity failure: credit-spread EV is identically zero

**What.** The production scanner routes every two-leg net credit through `calculate_ev(strategy='credit_spread')`. For valid credit `c` and width `w`, `calculate_pop` sets `p=(w−c)/w`. The payoff then sets gain=`100c`, loss=`100(w−c)` and computes `EV=p×gain−(1−p)×loss`. Those terms cancel exactly.

**Where.** [`options_scanner.py:3508-3539`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/1b8217b40ac2dda569fa81d6320dce0bd07f4a06/packages/quantum/options_scanner.py#L3508-L3539); [`ev_calculator.py:65-80,243-282`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/1b8217b40ac2dda569fa81d6320dce0bd07f4a06/packages/quantum/ev_calculator.py#L65-L80); downstream rejects at `options_scanner.py:3781-3811` and `canonical_ranker.py:63-79`.

**Worked real-shape example.** For the pinned five-wide, $1.49-credit case:

- `p = 351 / 500 = 0.702`; `q = 0.298`;
- gain = $149; loss = $351;
- `0.702×149 = 104.598`; `0.298×351 = 104.598`;
- `EV_raw = $0`; `EV_cal = 0.5×0 = $0`;
- even with zero friction, net is $0, which misses the $15 floor by $15.

This identity holds for every `0<c<w`.

**Why/impact.** Commit #1169 moved the modeled EV from negative to zero. It corrected a label/value inversion but did not make the structure economic or evaluable for ranking. Unmuting the cohort cannot create a qualifying entry under this path.

**Evidence.** Repository-dispositive algebra and production call graph. [`test_pop_credit_inversion_fix.py:82-89`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/1b8217b40ac2dda569fa81d6320dce0bd07f4a06/packages/quantum/tests/test_pop_credit_inversion_fix.py#L82-L89) asserts only win/loss probabilities, never expected value or route survival.

**Risk/confidence.** High profitability/evidence impact; very high confidence. No runtime read is needed to prove the identity.

**Recommendation.** Do not unmute the credit cohort. Source probability independently of the payoff ratio—such as a properly validated terminal/breakeven distribution—and add a production-route test that asserts nonzero EV and all unchanged gates. Any behavior change begins observe/replay-only.

### F-W2/W5 — High: risk-basis shadow logs cannot answer the arm question

**What.** The helper computes `would_flip` only when a threshold is supplied. None of its three production consumers supplies one.

**Where.** [`risk_basis_shadow.py:31-51`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/1b8217b40ac2dda569fa81d6320dce0bd07f4a06/packages/quantum/services/risk_basis_shadow.py#L31-L51); allocator `portfolio_allocator.py:160-165`; RBE `risk_budget_engine.py:397-402`; utilization candidate `utilization_gate.py:347-352`.

**Why/impact.** Every non-null production line necessarily records `would_flip=None`. Context is only open-count/position-count or symbol, without suggestion/cohort/decision ID. A week of logs measures dollar deltas but not which allocations or gates change, and cannot be joined reliably to W3. The ledger’s claim that each consumer logs `would_flip` disagrees with code.

**Evidence/risk/confidence.** Code-dispositive; high arm-decision risk; very high confidence. Flag-off behavior itself remains byte-identical.

**Runtime check.** Query every `[RISK_BASIS_SHADOW]` line since #1166. Current code predicts no true/false `would_flip`. Refutation requires a line on the audited SHA containing threshold, applied/shadow decision and stable suggestion/cycle identity.

### F-W4 — Medium-high: ticker-only comparison hides structure reordering

**What.** `_top_n` serializes only ticker. Two structures/expiries on one ticker can swap while the arrays remain equal.

**Where.** [`calibration_apply_ordering.py:72-74,112-117`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/1b8217b40ac2dda569fa81d6320dce0bd07f4a06/packages/quantum/analytics/calibration_apply_ordering.py#L72-L74). The test uses distinct `HI`/`MID` tickers only (`test_calibration_apply_ordering.py:108-125`).

**Why/impact.** Four QQQ structures in a cycle are already packet-observed. A structural selection change can be logged as `would_differ=False`. The line also omits strategy, expiry/legs, candidate ID, raw/calibrated scores and magnitude.

**Risk/confidence.** Medium-high selection evidence risk; high confidence. Flag-off mutation remains byte-identical.

## Pass 3 — value grade

**A+ / EARNING; retain.** A1 killed the central two-leg profit premise and found two corrupt arm-decision notebooks. This is higher value than v1.2’s arithmetic-only result.

---

# A2 — LOSSES

## Pass 1 — charter verdict

**Retain and sharpen around residual quantity custody.** E6 prevents phantom internal fills, but does not own partial parent fills, cancelled residuals or assignment. Those edges become more relevant if quantities above one and credit structures return.

## Pass 2 — findings

Core paths read: broker poll/update, partial/filled transitions, close-fill reconciliation, duplicate/re-arm policy, Step 1.5 client-ID lookup and 0-DTE sequence.

### F-A2-1 — High: partial multileg closes do not update residual position quantity

**What.** A broker `partially_filled` parent becomes DB status `partial` and stores filled quantity, but no path reconciles that partial into `paper_positions`. Position closure runs only after parent `filled`.

**Where.** `alpaca_order_handler.py:795-803,827-840,880-924,993-1052`; duplicate blocker `paper_exit_evaluator.py:1871-1905`.

**Why.** The broker may hold only a residual quantity while the database still holds the original full quantity. If the order later cancels/expires, the 30-minute re-arm can stage the full stale DB quantity.

**Impact.** At qty>1 this can reject-loop, over-close or reverse exposure. On expiry day it composes with assignment risk. If a parent reports filled but leg quantities disagree, `_close_position_on_fill` alerts and returns without closing (`alpaca_order_handler.py:580-601`), yet the caller still logs “Position closed on fill” and increments fills (`:1002-1010`).

**Risk/confidence.** High consequence; lower probability at qty 1, material for supported qty 1–7. High code confidence; incidence unknown.

**Runtime check.** Find close-source orders with `status='partial'`, or terminal orders with `0<filled_qty<requested_qty`; compare broker parent/leg fills and current OCC positions with DB position quantity. Any mismatch confirms exposure. Zero rows refutes history only.

**Additive recommendation.** Cancel the unfilled remainder, reconcile exact broker leg quantities, update the DB residual, and only then authorize a close for that residual. No stop threshold changes.

### F-A2-2 — Medium-high: 404 re-arm has no lifetime/DTE-aware breaker

Step 1.5 turns a client-ID 404 into `cancelled`; close re-arm waits 30 minutes and suspends after three attempts in a rolling four-hour window. Once the oldest attempt ages out, retry resumes. On 0-DTE this can create indefinite four-hour-cadenced rearming rather than a terminal escalation, while no assignment/exercise activity reconciler exists.

**Where.** `alpaca_order_sync.py:33-84,169-198`; `paper_exit_evaluator.py:584-635,869-980`.

**Runtime check.** For every open position at ≤7 DTE, reconstruct close attempts and `client_order_id_not_at_broker` transitions; compare with broker assignment/exercise activities and equity positions.

### Cross-area close-state lie

A known terminal/exhausted submit failure is persisted and returned as `needs_manual_review` by `submit_and_track` (`alpaca_order_handler.py:432-502`). `_close_position` discards the result and unconditionally returns `routed_to='alpaca', Fill pending` (`paper_exit_evaluator.py:2238-2260`). The monitor then emits “Force-closed,” returns true, increments close counts and can write stop cooldown (`intraday_risk_monitor.py:458-504,1462-1490`). No phantom fill occurs, so E6’s narrow closure passes; consumer state/alerts are false and same-cycle close work can be suppressed.

## Pass 3 — value grade

**A / EARNING; retain.** The area found a high-consequence residual-quantity hole and a distinct known-failure/success costume without touching stop policy.

---

# A3 — SELF-LEARNING

## Pass 1 — charter verdict

**Retain, but do not claim the three facts are wholly siloed.** `position_thesis_outcomes` stores `thesis_outcome`, realized P&L and close reason together. The lossy seam is the link from closed positions/orders into calibration and the absence of DTE features.

## Pass 2 — findings

Core paths read: close/order/position suggestion resolution, LFL insert, v3 inner join, thesis tracker row, calibration/prequential fetch and migration drift guard.

### F-A3-1 — Medium-high: the resolved suggestion fallback is discarded at insertion

**What.** Ingest collects order and position suggestion IDs and correctly resolves `order.suggestion_id OR position.suggestion_id`. `_create_paper_outcome_record` then re-reads only the order value.

**Where.** `paper_learning_ingest.py:273-313,394-425,571-589`; canonical v3 view inner-joins `lfl.suggestion_id` to `trade_suggestions.id`.

**Why/impact.** A close order missing its link creates an LFL row with null suggestion ID even when the position has the correct ID; that close disappears from calibration and prequential validation. The broad test module is skipped (`test_paper_learning_ingest.py:20-25`), and the surviving source pin asserts order-only behavior.

**Risk/confidence.** Medium-high learning integrity; high code confidence, incidence unknown.

**Runtime check.** Count closed positions with non-null position suggestion ID whose latest filled close has null suggestion ID; locate LFL rows and show whether each is absent from `learning_trade_outcomes_v3`.

### F-A3-2 — Medium: DTE-segmented calibration is inert

`_classify_dte` requires `details_json.dte_at_entry`, `dte_at_entry` or `days_to_expiry` (`calibration_service.py:281-302`). Production and prequential fetches select none of these; the v3 view exposes none. Every outcome enters DTE bucket `unknown`. Current impact is limited by a mostly ~44-DTE sample but grows as structures/DTEs diversify.

### F-A3-3 — Medium: E13 drift guard is literal but narrow

`test_ev_raw_coalesce_drift_guard.py:14-35` selects the latest migration matching `CREATE OR REPLACE VIEW`. It cannot see a later `DROP VIEW`, rename/dynamic SQL, manual DB drift, or an unapplied migration.

**Runtime check.** Read `pg_get_viewdef('public.learning_trade_outcomes_v3'::regclass,true)` and assert both raw-value coalesces. A nightly runtime schema attestation would complement—not replace—the committed guard.

### Closure notes

- E10 core close-reason propagation passes. The stage stamp is best-effort and swallowed; reconciler falls back to `alpaca_fill_reconciler_standard`, so query post-fix fallback/null reasons.
- E11 passes: terminal tracker rows keep thesis/P&L/reason together and do not get rewritten.
- E17 passes its non-circular/prefix contract; it intentionally uses a study warm-up and inherits DTE=`unknown`.

## Pass 3 — value grade

**A− / EARNING; retain.** The chain is substantially better, but a valid fallback link can still be dropped and the advertised DTE learning dimension is empty.

---

# A4 — SELF-SUSTAINING

## Pass 1 — charter verdict

**Retain; the evidence plane must prove its own liveness.** E8 improved the generic runner, but the normal intraday-monitor route can still manufacture a green result. Separately, replay is designed fail-soft with no manifest/health consumer, making “quiet day” indistinguishable from “capture broken.”

## Pass 2 — findings

Core paths read: typed outcome classifier and intraday per-user loop; replay DecisionContext begin/commit/failure; suggestions handlers; workflow early returns/output capture; market-data cache consumption; ops-health registry.

### F-A4-E8 — Critical exclusion-integrity failure: per-user fatal remains green

**What.** `run()` raises when `execute()` raises, satisfying the new source-level test. But `execute()` catches every `_check_user` exception, appends an error object, and unconditionally returns `ok:true,status:'completed'` without `users_failed`, `counts.errors` or top-level error.

**Where.** [`intraday_risk_monitor.py:150-218`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/1b8217b40ac2dda569fa81d6320dce0bd07f4a06/packages/quantum/jobs/handlers/intraday_risk_monitor.py#L150-L218); runner classifier `jobs/runner.py:36-62`; `test_typed_job_outcome.py:60-67` only pins that some `raise` appears in the file.

**Why.** On the normal one-user account, any `_check_user` exception means the entire protection cycle failed. The typed runner receives an explicitly green result and correctly persists the lie.

**Impact.** The q15 risk/exit monitor can still fail green, advance freshness and avoid retry/escalation. This is the same class E8 claimed closed, one layer inside the handler.

**Evidence/risk/confidence.** Code-dispositive; critical live-capital protection; very high confidence. Runtime incidence unknown.

**Runtime check.** Query succeeded `intraday_risk_monitor` rows whose nested `result.results` array contains an `error`. Any row proves exercise. Zero rows limits history, not the structural path.

**Additive recommendation.** Mixed user results must normalize to `partial`; all-user failure must raise or return a normalized failed outcome. Drive the production route in test. This tightens truth and loosens no control.

### F-A4-E16 — High exclusion-integrity failure: replay tape omits the dominant decision shape

This is one evidence-contract cluster with four seams:

1. **No-trade early return.** `run_midday_cycle` returns when `suggestions=[]` at `workflow_orchestrator.py:3771-3826`; `decision_id` linkage and `__decision__/ranked_candidates` capture occur only later at `:3834-3855,3941-3976`. The current funnel is near-zero, so the dominant decision has no output.
2. **Rejected candidates omitted.** Candidates discarded by `continue` at `:3025,3261,3470,3502,3590` never enter the later output loop despite the comment claiming accepted plus rejected/reason.
3. **Cache-hit inputs omitted.** Option-chain cache returns at `market_data_truth_layer.py:1434-1438` before recording at `:1463-1466`; snapshot cache returns at `:997-1009` before the hook at `:1068-1071`. Cache is process-global and chain TTL is 300 seconds. Daily bars correctly record cache hits, proving the intended pattern.
4. **Commit failure invisible.** `DecisionContext.commit` catches and returns `{error}` (`decision_context.py:251-373`); suggestions handlers discard the result. Even mark-failed is fail-soft. Ops health watches no replay manifest/output.

**Why/impact.** A green decision run may have inputs without an output, outputs without cache-consumed inputs, or a swallowed commit failure. It cannot byte-replay why the system said “NO”—the most important current decision.

**Test gap.** `test_replay_decision_output_capture.py:26-49` directly records a feature and never drives `run_midday_cycle`, repeating the source/helper-test versus production-route pattern.

**Risk/confidence.** High learning/governance impact, low direct trading risk; very high code confidence.

**Runtime check.** For every `suggestions_open` decision run, require one terminal capture manifest. Confirm failure with any successful zero-created cycle lacking `ranked_candidates`; any consumed chain/snapshot key lacking a `decision_input`; or a job result that omits commit error/counts. Monday’s first capture is the immediate test.

**Recommendation.** Capture a terminal manifest before every return, including zero and reject reasons; record at the consumption boundary for both cache/fetch; include commit counts/error in the job result; health-check manifest freshness/completeness. No decision behavior changes.

### Observe-log liveness

No health registry monitors `[BUCKET_SHADOW]`, `[RISK_BASIS_SHADOW]` or `[APPLY_ORDER_SHADOW]`. Marker silence can mean no candidates, flag/cache precondition, code path failure, logging loss or a genuinely quiet window. Each arm notebook needs an expected-cycle heartbeat and counts, not only event lines.

## Pass 3 — value grade

**A+ / EARNING; retain.** A4 again killed a closure claim on a live protection path and found that the new replay evidence can be green but non-reproducible.

---

# A5 — EFFICIENCY

## Pass 1 — charter verdict

**Keep, but do not optimize hypothetical bytes before Monday telemetry.** Capture retention is the only plausible new spend issue. The ~61 quarantined legacy rows are not a material steady-state scan under current filters.

## Pass 2 — findings

### F-A5-1 — Medium: replay growth is warning-bounded, not storage-bounded

`blob_store.py` declares a 2 MB maximum but only warns and still stages the blob (`:26-28,137-160`). Full per-symbol chains are captured; default universe limit is 100. Open and close schedules imply roughly 10 decision runs per trading week/user and about 20 in 14 calendar days. Deduplication/compression/filters determine actual bytes, so the ledger’s ~70 MB/month is a forecast, not a code bound.

`BlobStore.commit` also permits partial batch failures (`:253-321`), composing with E16’s missing completeness manifest.

**Runtime measurement.** Daily count and sum both logical `size_bytes` and stored `octet_length(payload)` for `data_blobs`, plus runs/inputs/features per strategy. A 14-day steady estimate is mean unique stored bytes per trading day ×10 weekdays, plus row overhead. Without the known reaper, long-run growth is unbounded.

**Decision.** Only if chain blobs dominate after dedupe, store one content-addressed canonical chain per freshness bucket and link decisions to it. Do not delete by age without the filed cascade/orphan anti-join design.

### Quarantined-row check — not promoted

`learning_read_filter` filters fetched rows; conviction normally uses v3 and scans legacy only in degraded fallback; autotune is 30-day bounded; post-trade is type/48h bounded. The audit found no evidence that ~61 quarantined legacy rows justify a cleanup build.

## Pass 3 — value grade

**B+ / CONDITIONAL EARNING.** It supplied the correct growth measurement and rejected a weak cleanup. Runtime bytes, not intuition, should decide the retention optimization.

---

# A6 — VIABLE-SET / STRUCTURE-SET HANDLING

## Pass 1 — charter verdict

**Still correct; the settled zero-clear condition holds.** E12 does not reopen viability. It proves the proposed credit structure remains mathematically unevaluable under the current model.

## Pass 2 — structure ranking

The honest evidence ranks the classes as follows:

| Rank | Structure | Current economic evidence |
|---:|---|---|
| 1 | Iron condor | Four-leg friction, but model can produce positive raw EV. Best reconstructable QQQ 07-07: `0.5×42.45−7 = $14.225`, only $0.775 below the floor. |
| 2 | Debit vertical | Two-leg friction and non-circular delta-interpolated probability; positive EV is possible, but packet examples remain below the floor. |
| 3 | Credit vertical | Two legs, but raw/calibrated EV is identically $0 for every valid credit/width. Even zero friction misses the floor by $15. |

The packet has no matched same-time, same-underlying real quote set spanning IC, credit vertical and debit vertical. A numeric comparison that assumes equal EV or “half the legs means half the cost” would be fabricated. The credit zero identity is underlying-independent and sufficient to reject that experiment slot now.

E7 code integrity now passes: the active route fetches the full pending set, reranks, and slices. The first real ≥2-survivor ordering effect remains a runtime pin as stated.

## Pass 3 — value grade

**A+ / EARNING; retain.** A6 answers the concrete structure-slot question: the credit cohort is not ready, and lower friction alone cannot rescue a zero-EV model.

---

# A7 — DORMANT / NEAR REINSTATEMENT

**Fills: 9/10.** Do not reopen optimization yet. At the 10th qualifying live close, reinstate A7 as a **causal close-quality charter**, not a threshold-tuning charter:

- count only broker-acknowledged live close fills on the current epoch;
- separate full from partial/residual fills;
- join thesis outcome, close reason, combo/leg quote quality, quote age, stop/target measure and realized fill;
- report the measurement distribution before any policy recommendation.

Ten fills is the minimum to restart measurement, not evidence sufficient to loosen a stop.

**Pass 3:** Dormant but correctly poised for reinstatement; territory remains covered by A2 and the owned Phase-3 instrumentation.

---

# A8 — NEGATIVE-DECISION EFFICACY

## Pass 1 — charter verdict

**Retain.** The SOFI sentinel remains a correct NO on the supplied runtime state. The new bucket rejection is queryable when armed. The fresh false decision is on the close plane: a known failed submit is reclassified as routed success.

## Pass 2 — findings

### F-A8/E6-edge — Medium-high: `needs_manual_review` is costumed as close success

**What.** `submit_and_track` honestly persists and returns `needs_manual_review` after terminal/exhausted submission failure. Its caller discards the return and reports `routed_to='alpaca'`; monitor code treats that as success.

**Where.** `alpaca_order_handler.py:432-502`; `paper_exit_evaluator.py:2238-2260`; `intraday_risk_monitor.py:458-504,1462-1490`.

**Why/impact.** No filled row or closed position is fabricated, so E6’s narrow invariant holds. But the system emits “Force-closed,” increments `force_closes_submitted`/same-cycle closed sets, may write cooldown, and suppresses another same-cycle close attempt despite a known submit failure.

**Risk/confidence.** Medium-high live protection and evidence risk; very high code confidence, incidence runtime-dependent.

**Runtime check.** Join close-side `paper_orders.status='needs_manual_review'` to same-cycle intraday job results and force-close alerts. Any force-close count/message for that failed order confirms exercise.

### New bucket rejection class

When armed, `bucket_exposure_cap` is stamped on `trade_suggestions.blocked_reason` with bucket exposure/cap detail, so it is queryable alongside cohort, legs and order JSON. It need not be forced into the scanner-only rejection view. Its shadow evidence lacks stable identity, which is a W3/W5 integrity problem rather than a new taxonomy build.

## Pass 3 — value grade

**A / EARNING; retain.** A8 found a live false-success state without re-filing the v1.2 label issues.

---

# A9 — ALERT & SIGNAL INTEGRITY

## Pass 1 — charter verdict

**Retain and focus on typed/JSON disagreements with a consumer.** The fourth material member is clone risk basis: JSON has a value, the typed field drops it, and fill consumers read only the typed field.

## Pass 2 — findings

### F-A9-E14 — High exclusion-integrity failure: cohort clones drop and mis-scale risk truth

**What.** Policy-Lab fork reads source `sizing_metadata.max_loss_total`, copies that position total unchanged even when clone contracts change, and omits top-level `max_loss_total`. Fill and orphan-repair consumers read only the top-level field.

**Where.** [`policy_lab/fork.py:254-333`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/1b8217b40ac2dda569fa81d6320dce0bd07f4a06/packages/quantum/policy_lab/fork.py#L254-L333); `paper_endpoints.py:2092-2114,2563-2584`; `test_fork_clone_legs_full_count.py:15-77` asserts leg count only.

**Why.** Clone fill can persist `paper_positions.max_loss_total=NULL` even though a source value exists in JSON. The JSON total is itself stale because it was not rescaled from source contracts to clone contracts.

**Impact.** E14 works on the champion path but fails on neutral/conservative clones. W2/W3 observe evidence is contaminated precisely in the experiment cohorts intended to inform future decisions.

**Risk/confidence.** High risk-evidence and future arm impact; very high code confidence. Current live champion decisions are not directly changed.

**Runtime check.** Find non-champion clones where typed `max_loss_total` is null and `sizing_metadata.max_loss_total` is non-null; join orders/positions and recompute `(source_total/source_contracts)×clone_contracts`. Any mismatch/null confirms realization.

**Recommendation.** One clone risk normalizer should rescale per-contract truth and emit the canonical top-level total plus consistent JSON provenance. Unknown must remain explicit, never silently zero.

### Near miss: hardcoded `direction='long'`

`workflow_orchestrator.py:3633-3647` writes `direction='long'` for all structures and clones copy it, while legs and `premium_direction` carry the real economics. Current readers mostly use direction as open-versus-close, so this is an evidentiary liar without a proved control impact. It is inventoried, not promoted.

The known `time_in_force` typed-column lie remains filed and was not re-reported.

## Pass 3 — value grade

**A / EARNING; retain.** A9 found a new typed/JSON disagreement with a real risk consumer and exclusion impact.

---

# A10 — CALENDAR & CLOCK INTEGRITY

## Pass 1 — charter verdict

**Retain the incumbent.** E15 repaired winter close, but an adjacent date/offset boundary still creates a summer opening blind spot. Expiry-day sequencing also remains incomplete at the close-state edge.

## Pass 2 — findings

### F-A10-1 — High: fixed UTC warm-up blinds the first summer hour

**What.** Market-hours detection now correctly uses ET, but `_RTH_WARMUP_OPEN_UTC=(14,30)` remains fixed. During EDT the market opens at 13:30Z; the age anchor is one hour in the future and reads healthy.

**Where.** [`ops_health_service.py:46-69,104-111,376-390`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/1b8217b40ac2dda569fa81d6320dce0bd07f4a06/packages/quantum/services/ops_health_service.py#L46-L69).

**Impact arithmetic.** With current margins, first possible late detection becomes approximately:

- Alpaca order sync: 14:50Z, 80 minutes after open;
- risk monitor: 15:00Z, 90 minutes after open;
- heartbeat: 15:15Z, 105 minutes after open.

**Risk/confidence.** High detection value; high code confidence. This is adjacent to, not a reopening of, E15.

**Recommendation.** Derive the session-open instant from the same date-aware ET/broker session object used by the market-hours predicate.

### Expiry-day sequence

Expiration fires from the morning sweep and q15 monitor. A 404 marks an attempt cancelled; each attempt blocks 30 minutes and three within four hours suspend further attempts. Because the budget rolls, retry eventually resumes—there is no DTE-aware terminal escalation. Partial fills can leave stale quantity. The tracker scores thesis at expiry, but no assignment/exercise activity reconciler owns resulting equity. This is the A2 residual-custody package, not a stop-threshold proposal.

### F-A10-2 — Conditional Monday-holiday staleness

`_weekend_excluded_age` subtracts only Saturday/Sunday (`ops_health_service.py:394-423`). If Monday produces no job row, a Friday 17:00 CT daily result appears roughly 39 hours old Tuesday at 08:07 CT, above the 26-hour threshold. The weekday scheduler may still create holiday no-op results, so actual symptom requires the holiday runtime query.

### F-A10-3 — New import-time flag

`A4_MIN_HOLD_BARS` is read at import in `paper_learning_ingest.py:37-40` and controls whether realized-vol-over-hold is populated. An env change requires recycle. Its risk is learning quality, not live capital. New W1–W4 flags are correctly read per call.

## Pass 3 — value grade

**A / EARNING; retain.** It found a high-value summer blind adjacent to the retired winter issue and clarified the 0-DTE close/assignment chain.

---

# Observe-window integrity W1–W5

| Window | Verdict | Does the evidence serve the arm decision? |
|---|---|---|
| W1 — live gate qty basis | **Pass in code; runtime pending** | Yes. All gate lines carry both cost/net bases, floor, applied basis and suggestion ID; divergence lines add qty and old/new decisions. Verify flag OFF and post-clock logs. |
| W2 — max-loss risk basis | **Fail / not armable** | No. Every production caller omits `threshold_usd`, so `would_flip=None`; identifiers are insufficient for W3 joins. |
| W3 — bucket enforcement | **Fail / not armable** | No. Unknown risk becomes zero and can proceed when armed; log hides missing open risk and lacks stable attribution/heartbeat. This is a second hard precondition beyond the known unreadable-equity polarity. |
| W4 — calibration at scoring | **Fail / not armable from quiet logs** | No. Ticker-only top-five comparison masks same-ticker structural swaps and omits score magnitude/identity. Flag-off mutation itself is byte-identical. |
| W5 — composed W2+W3 arm | **Fail / not armable** | No. Both component notebooks are defective and W3 has two fail-open preconditions. |

## W3 second unbackstopped path

`bucket_control._risk_from_fields` returns `(0,true)` when both `max_loss_total` and `cost_basis_total` are unknown (`:47-60`). `evaluate_bucket` adds zero and sets the legacy caveat only when `v>0` (`:101-131`), so the log actively hides the unknown open exposure. Candidate fallback can also return zero (`:67-82`); armed caller sees `would_block=false` and proceeds (`paper_autopilot_service.py:1038-1056`). The forward-only migration explicitly leaves legacy rows null, and tests pin null→zero without an armed unknown-risk assertion.

**Required precondition.** Unknown open or candidate risk must be explicit and fail-closed/not-armable before W3 can flip. Add stable ticker/suggestion/cohort/portfolio/routing/armed status and an expected-cycle heartbeat. This tightens a control.

---

# Exclusion-integrity results E1–E18

| Exclusion | Result | Adjudication |
|---|---|---|
| E1 calibration kill-switch | **Pass** | Production ×0.5 proof accepted; no contrary apply kill switch found. |
| E2 gate qty scaling | **Pass narrowly** | Per-contract/shadow routing and W1 evidence match; live remains observe-only. |
| E3 streak-breaker edge trigger | **Pass** | No changed condition or contrary code path found. |
| E4 close-fill-gap sign | **Pass** | Corrected basis/dataset remain intact. |
| E5 OBP null fail-closed | **Pass** | No reopened unreadable-capital allow path in the closed territory. |
| E6 broker-ack live-close invariant | **Pass narrowly** | No live fill/position close without broker acknowledgement was found. Partial quantity and returned-failure success telemetry are adjacent FSM-edge findings, not phantom fills. |
| E7 viability bias active route | **Pass in code** | Full fetch → active-route rerank → Python slice is real; first ≥2-survivor runtime effect remains pending. |
| E8 typed job outcomes | **Fail, promoted** | Outer handler raises, but per-user intraday failure is swallowed into `ok:true,completed`; one-user protection can fail green. |
| E9 observability remainder | **Pass as scoped** | Named producers/registry/partial handling match. Replay/window liveness is new territory. |
| E10 close_reason end-to-end | **Pass with durability caveat** | Core path works; stage stamp is best-effort and may fall back to generic reconciler reason. |
| E11 thesis tracker | **Pass** | Tracker is live, terminal rows are stable, and thesis/P&L/reason share one row. |
| E12 credit PoP inversion | **Fail, promoted** | PoP label changed, but payoff-derived PoP forces EV exactly zero; cohort is not economically evaluable. |
| E13 raw-EV coalesce | **Pass core / narrow guard** | Current committed view fix is present; guard cannot attest deployed/manual/drop-view drift. |
| E14 risk totals persistence | **Partial fail, promoted** | Champion path works; Policy-Lab clone path drops/mis-scales available risk and can persist null position totals. |
| E15 winter close | **Pass** | ET wall-clock fix holds; summer warm-up defect is adjacent health math. |
| E16 replay capture | **Fail, promoted** | Writer/flag exist, but zero decisions, rejected tails, cache-hit inputs and commit health are missing. |
| E17 prequential validator | **Pass** | Prefix/no-lookahead/non-circular contract holds; study warm-up and unknown DTE should be labeled. |
| E18 clamp + dead forecast delete | **Pass at final HEAD** | Clamp/log shipped at `aca743a`; dead `forecast_ev_pop` deleted at `1b8217b`; docs wrapped at `b761a3f`. |

---

# Consolidated runtime-check list

All checks are read-only. Confirm/refute criteria distinguish historical exercise from a structural code defect.

## P0 — Intraday-monitor nested false-green census

Query recent `intraday_risk_monitor` job rows with `status='succeeded'` and inspect the nested `result.results` array for objects containing `error`.

Example shape:

```sql
select id, started_at, finished_at, status, result
from job_runs
where job_name = 'intraday_risk_monitor'
  and status = 'succeeded'
  and finished_at >= now() - interval '30 days'
  and result::text like '%"error"%'
order by finished_at desc;
```

**Confirm:** any nested user error in a succeeded row; on a one-user cycle, that is a complete false-green protection failure.  
**Refute history:** zero rows in the interval.  
**Structural falsifier:** only a deployed wrapper absent from current GitHub that rewrites this result before runner classification.

## P0 — Partial/residual close custody

Enumerate all close-source orders where:

- `status='partial'`; or
- terminal status with `filled_qty>0` and `filled_qty<requested_qty`; or
- parent `filled` but stored broker leg quantities disagree.

For each, compare paper-order requested/filled quantities, `paper_positions.quantity`, Alpaca parent/leg fills and current OCC positions.

**Confirm:** any broker residual different from DB quantity, any cancelled partial later re-armed for full stale quantity, or “position closed” success log with DB still open.  
**Refute historical exercise:** zero qualifying orders. The missing residual transition remains structural.

## P0 — Clone risk-basis conservation

```sql
select
  id, source_suggestion_id, cohort_name,
  max_loss_total,
  sizing_metadata->>'contracts' as contracts,
  sizing_metadata->>'max_loss_total' as json_max_loss_total
from trade_suggestions
where cohort_name <> 'champion'
  and max_loss_total is null
  and sizing_metadata->>'max_loss_total' is not null;
```

Join resulting suggestions to orders/positions and source suggestions. Recompute `source_total/source_contracts×clone_contracts`.

**Confirm:** any clone/position typed null or unscaled JSON total.  
**Refute current realization:** no post-migration clone fills with this shape; code path still needs conservation before relying on W2/W3.

## P1 — Replay terminal-manifest completeness

For every successful `suggestions_open` decision run, left join:

- `decision_features` for namespace/key `__decision__/ranked_candidates`;
- linked `trade_suggestions.decision_id` rows;
- a terminal commit/count/error manifest, if one exists.

Stratify by `job_runs.result` created/suggestion count.

**Confirm:** an OK zero-created cycle with neither output feature nor linked rows; any successful run missing terminal manifest; or output claiming accepted+rejected while reject counts exceed captured rows.  
**Refute current incidence:** every run, including zero, has an explicit empty/rejected decision output and successful commit manifest.

## P1 — Replay input completeness under cache warmth

For each run, reconstruct the chain/snapshot keys actually consumed from scanner diagnostics and compare with `decision_inputs`.

**Confirm:** any consumed underlying/chain/snapshot lacking a link, particularly within the 300-second cache TTL or minute snapshot cache.  
**Refute:** consumption manifests equal captured input keys for warm and cold cache paths.

## P1 — Credit-vertical production census

Query recent two-leg net-credit candidates/rejections for `ev_raw`, `ev`, execution cost and `risk_adjusted_ev`.

**Code prediction:** production `total_ev=0`, followed by execution-cost or canonical minimum-edge rejection.  
**Confirm:** zero-EV rows on the audited path.  
**Refute the path, not the algebra:** a positive raw EV proves a different producer/path and must be traced; it does not make the cited formula nonzero.

## P1 — W2 decision evidence

Read every `[RISK_BASIS_SHADOW]` line since #1166.

**Confirm defect:** all non-null basis lines show `would_flip=None` and lack threshold/applied/shadow decision identity.  
**Refute:** current-SHA lines contain true/false would-flip, threshold, consumer outcome, suggestion/cycle/cohort identity.

## P1 — W3 unknown-risk census

Query all open live/shadow positions where both `max_loss_total` and `cost_basis_total` are null; query pending candidates where both max-loss and derivable premium are absent.

**Confirm active exposure:** any such row entering a bucket evaluation or any `[BUCKET_SHADOW]` line showing zero candidate/open risk without an explicit unknown count.  
**Refute current blast:** no open/pending unknown rows. Armed-state fail-open remains until code treats unknown explicitly.

## P1 — W4 same-ticker collision

Using replay decision IDs, compare full tuples `(ticker,strategy,expiry/legs,id,raw_score,calibrated_score)` against each `[APPLY_ORDER_SHADOW]` ticker list.

**Confirm:** a full structural reorder while logged ticker arrays are equal and `would_differ=false`.  
**Refute current incidence:** no same-ticker candidate multiplicity in the observation period. The serializer remains lossy.

## P1 — Known submit failure costumed as success

Join close orders with `status='needs_manual_review'` to same-cycle risk-monitor job results, alerts and cooldown rows.

**Confirm:** matching “Force-closed,” `force_closes_submitted>0`, closed-in-cycle suppression or cooldown.  
**Refute historical incidence:** zero joins.

## P1 — Summer RTH blind-window verification

For an EDT trading day, simulate/read `_rth_job_status` at 13:30Z, 14:00Z and 14:29Z with no current-day job. Record first time each RTH job becomes late.

**Confirm:** all read healthy before 14:30Z and first alerts match the 80/90/105-minute arithmetic.  
**Refute:** deployed code derives date-aware session open rather than the audited constant.

## P2 — Learning fallback/link conservation

Count closed positions with non-null `position.suggestion_id` and latest filled close `suggestion_id IS NULL`; join LFL and v3.

**Confirm:** LFL null link or missing v3 row despite the valid position link.  
**Refute current incidence:** zero qualifying closes.

## P2 — DTE calibration coverage

Group current calibration outcomes/prequential rows by `_classify_dte` input availability and resulting bucket.

**Confirm:** all rows are `unknown`.  
**Refute:** v3/fetch exposes entry DTE and multiple real buckets appear.

## P2 — Runtime view identity

```sql
select
  to_regclass('public.learning_trade_outcomes_v3') as view_oid,
  pg_get_viewdef('public.learning_trade_outcomes_v3'::regclass, true) as definition;
```

**Confirm closure:** deployed definition includes both `COALESCE(ev_raw,ev)` and raw PoP fallback.  
**Refute E13 runtime closure:** missing coalesce, absent view, or deployed definition not matching current migration intent.

## P2 — Replay growth/retention baseline

Daily measure `count(*)`, `sum(size_bytes)` and `sum(octet_length(payload))` for `data_blobs`, plus decision runs/inputs/features by strategy. Report dedupe ratio and partial commit errors.

**Confirm material growth:** extrapolated 14-day retained bytes breach the operator’s chosen budget or chain blobs dominate.  
**Refute immediate optimization need:** small stable unique-byte growth with high dedupe.

## P2 — Monday-holiday age behavior

For the next observed Monday market holiday, inspect whether each daily/RTH job writes a no-op success. On Tuesday, compute age after `_weekend_excluded_age`.

**Confirm:** missing Monday result plus false-late Tuesday alert from a Friday row.  
**Refute symptom:** holiday no-op rows or exchange-session-aware age exclusion.

## P2 — Clock/deploy/effective-config grounding

In one capture, record Supabase `now()`/timezone, Railway UTC/process start/deployed SHA for all services, Alpaca clock/next open/close, and effective values of W1–W4 plus `A4_MIN_HOLD_BARS`.

**Confirm mismatch:** service SHA divergence, unrecycled import-time value, or broker/session disagreement.  
**Refute:** clocks and effective states agree within normal network delay.

---

# Free look

The free look covered nested handler outcomes, replay cache/commit boundaries, clone risk dual storage, typed order/suggestion columns, current tracked secret patterns and the conditional E18 landing.

It produced the audit’s strongest control finding: E8’s source-level “raise” fix does not reach the normal per-user failure because `execute()` catches it first and returns green. It also found the E14 clone risk loss and E16 cache-hit/input hole.

The typed-column inventory found one lower-severity evidentiary liar (`trade_suggestions.direction='long'` for every open structure), but no current consumer that turns it into a live decision error. It is not promoted.

Targeted searches for private-key markers, live-key patterns and secret-shaped assignments found no new current-tree credential instance beyond the historical `.env.example` material excluded by the brief. No value is reproduced here.

---

# Ranked top three operator decisions

## 1. Close E8 at the actual per-user seam

**What.** Normalize nested user results: mixed success/failure → typed `partial`; all-user failure → raise/failed outcome. Add a route-driving test around `execute()`, not a source pin for an outer `raise`.

**Evidence.** `intraday_risk_monitor.execute()` catches `_check_user` failure and returns `ok:true,completed`; the typed runner therefore persists success. On the one-user account this is a complete protection-cycle failure.

**Value.** Highest. Restores truth to q15 live protection and makes the weekend E8 control real.

**Effort.** Less than one developer evening plus focused tests/readback.

**Risk.** Low implementation risk; may reveal previously hidden failures and create honest partial/failed rows. Automatic retry behavior remains the known F-A4-2 package.

**Doctrine.** Tightens fail-loud behavior; loosens no stop, gate or close control. Justified by a deterministic code error.

**Falsifier.** A deployed layer absent from current GitHub that rewrites nested user errors before runner classification. Zero historical errors narrows incidence only.

## 2. Repair the credit-vertical measurement before unmuting the cohort

**What.** Replace payoff-implied “PoP” with an independently estimated probability/return distribution, then drive the real scanner→cost→rank route in observe/replay. Keep every existing executable-cost and $15 floor gate unchanged.

**Evidence.** For every valid credit/width, current `p=(w−c)/w` makes `p×c=(1−p)×(w−c)` and EV exactly zero. The pinned $1.49/$5 case proves it numerically. Tests assert probability only.

**Value.** Very high, direct profitability/structure-set value. Until corrected, the lower-friction experiment cannot produce honest evidence.

**Effort.** Approximately 1–2 evenings for a defensible model seam and route tests, plus an observation period; more if a new distribution source is required.

**Risk.** Medium because a corrected measurement may admit candidates. Begin shadow-only; do not weaken any gate.

**Doctrine.** A proven mathematical circularity justifies measurement correction. Loss sting does not.

**Falsifier.** None for the algebra. Only proving production uses a different independent-probability path would change the affected scope.

## 3. Repair replay’s terminal capture contract before trusting Monday evidence

**What.** Emit a terminal output/manifest before every return, including explicit empty/no-trade and all rejected reasons; capture cache-hit inputs at consumption; surface commit counts/errors in job results; health-check completeness/freshness.

**Evidence.** Zero-suggestion return precedes output capture; multiple rejects disappear; cache returns precede input hooks; commit errors are swallowed. The current near-zero funnel maximizes exposure to the no-output path.

**Value.** High learning-mode value. It prevents weeks of apparently valid but non-replayable evidence.

**Effort.** Approximately 1–2 evenings.

**Risk.** Low; evidence/observability only if no decision logic is moved.

**Doctrine.** Additive truth capture; no trading-control change.

**Falsifier.** A Monday runtime manifest proving every zero/reject/cache-consumed decision is already complete would refute current incidence, but not the audited early-return/cache ordering.

### Near-miss fourth

**Residual partial-close custody** has higher loss severity but likely 2–3 evenings and lower observed frequency. It should precede routine qty>1 credit-spread use or any approach to expiry.

---

# Packet/ledger/code disagreements

1. **E8 closure overstates the production route.** Outer handlers raise, but the intraday per-user loop still returns complete failure green.
2. **E12 “credit cohort evaluable/gate cleared” is false.** The PoP number changed; modeled EV is exactly zero and still hard-rejected.
3. **E16 “decision output + linkage shipped” is incomplete.** Zero decisions return first; rejected tails and cache-consumed inputs are absent; commit health is not surfaced.
4. **E14 persistence is path-dependent.** Champion fills carry totals; Policy-Lab clones omit typed risk and carry stale JSON totals.
5. **Ledger says W2 consumers log `would_flip`; code makes it `None`.** No caller supplies the threshold.
6. **W4’s two orderings are not structure identities.** Ticker-only lists can falsely agree.
7. **E6 narrow invariant is true, but the surrounding typed-state narrative is too strong.** A returned known submission failure is reported to monitor consumers as routed success; partial fills are not first-class residual states.
8. **E15 winter closure is true; summer opening health remains wrong.** These are adjacent date/offset seams, not the same defect.
9. **The requested matched same-underlying three-structure example is not in the evidence universe.** The report refuses to fabricate equal EV or half-cost assumptions; the credit zero proof is stronger and universal.
10. **HEAD moved during the audit.** Start was `17f84d9`; terminal clamp landed at `aca743a`; dead forecast deletion at `1b8217b`; final docs wrap is `b761a3f`. E18 is closed at final HEAD.

---

# Honest overall verdict and first change

The measured **81% thesis hit rate makes signal the least likely primary problem**; only 4/13 thesis hits becoming profitable makes the loss mechanism downstream. The current diagnosis is **execution/structure economics first, exit measurement second, capital granularity third**: four-leg ICs are friction-bound, the proposed credit vertical is still zero-EV by construction, and the ~$2k account makes one-lot risk coarse but cannot repair negative per-contract economics. Phase-3 must determine how much of the downstream loss belongs to entry/exit quotes versus stop measurement; this audit offers no stop relaxation. The single first change is the **intraday per-user typed-outcome fix**, because the evidence and loss controls cannot be trusted while a complete q15 protection failure can still be green. Nothing in this report was implemented; every recommendation remains an operator decision.
