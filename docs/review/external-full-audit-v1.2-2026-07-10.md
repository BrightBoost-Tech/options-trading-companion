# External Full Audit v1.2 — Ten-Area Deep Dive

**Repository:** `BrightBoost-Tech/options-trading-companion`  
**Audit finalization clock:** 2026-07-10 20:32:59Z / 15:32:59 CDT (`America/Chicago`)  
**Initial clock grounding:** 2026-07-10 20:25:58Z; the workspace shell itself reported a Pacific offset, so UTC is the common clock used below.  
**Audit-start `origin/main`:** [`d275d28`](https://github.com/BrightBoost-Tech/options-trading-companion/commit/d275d28ca28666e2069dc01df976884af7bd5d14)  
**Final `origin/main`:** [`3d7e4ee`](https://github.com/BrightBoost-Tech/options-trading-companion/commit/3d7e4ee59a4cf9768f3b903a07db2a88f3951c67) (documentation-only wrap)  
**Final runtime-relevant code SHA:** [`e45290f`](https://github.com/BrightBoost-Tech/options-trading-companion/commit/e45290fe77ca1b9a3c630c76f7267e17aacfa020)  
**Mode:** Read-only. No build, test run, code/config/PR change, broker/database action, or stop/gate/control change was performed.

## Clock and evidence boundary

| Clock/source | Grounded value | Use in this report |
|---|---|---|
| Reviewer UTC | 2026-07-10 20:32:59Z | Common comparison clock |
| Reviewer Chicago time | 2026-07-10 15:32:59 CDT | Operator-local rendering |
| GitHub `main` | `3d7e4ee`, committed 2026-07-10 20:26:15Z | Final repository state; docs-only over code SHA below |
| Runtime-relevant code | `e45290f`, committed 2026-07-10 20:21:37Z | Final code basis |
| Packet runtime cutoff | Approximately 2026-07-10 20:00Z, with the stated 32/32 calibrated-row proof | Accepted runtime attestation |
| Supabase `now()` | Unavailable to this reviewer | Runtime check; not inferred |
| Railway/container clocks and deployed SHA | Unavailable to this reviewer | Runtime check; not inferred |
| Alpaca broker clock/state | Unavailable to this reviewer | Runtime check; not inferred |

The audit began on `d275d28`. During the read, `main` advanced first to `e45290f`, the first half of I1’s broker-acknowledged-close work, and then to docs-only `3d7e4ee`. The code delta changes `paper_exit_evaluator.py`, the late result handling in `intraday_risk_monitor.py`, and tests; the final commit updates audit/ledger/report text only. I reviewed both changed-file inventories and commit contracts to ensure they did not invalidate the findings below. Per the engagement boundary, I did **not** re-design or certify I1’s newly merged result; PR2’s targeted broker lookup/reconciler remains described by the commits as outstanding.

Evidence consists of the repository, tests, migrations, `CLAUDE.md`, committed audit/ledger/backlog/history, the evidence packet and its erratum, and GitHub commit state. I had no live Supabase, Railway, Alpaca, or log access. Packet runtime claims are treated as citable observations. Code determines what the system can do. Where the two disagree, both are preserved and the disagreement is a finding.

### EV and cost basis used throughout

- Current production calibration basis: **`EV_cal = 0.5 × EV_raw`**, based on the prompt’s 32/32 full-day runtime proof.
- Unless a row explicitly says `EV_raw`, every profitability number in this report uses **calibrated EV**.
- Entry economics use the **per-one-lot executable round-trip cost**, not quantity-scaled cost, except where demonstrating a code defect.
- Current entry-floor condition is therefore:

  `0.5 × EV_raw − executable_cost_per_contract ≥ $15`

  or equivalently:

  `EV_raw ≥ 2 × (executable_cost_per_contract + $15)`.

- The packet’s historical raw-era observations are not silently reinterpreted as calibrated production results. Where recalculated, both bases are shown.

## Executive verdict

The most consequential fresh finding is operational, not strategic: the generic job runner can persist a fatal `{"ok": false}` q15 risk-monitor result as **succeeded**, while the health detector recognizes only one narrow `result.counts.errors` shape. A live protection cycle can therefore fail green, advance its freshness anchor, and avoid retry/dead-letter behavior.

The profitability diagnosis is also sharper. With calibration applying, the current four-leg/low-account design is constrained by **per-contract EV density versus executable friction**. In the five packet candidates that can be reconstructed consistently, **0/5 clears the $15 calibrated per-contract floor**. More capital can make max-loss sizing divisible; it cannot repair negative per-contract economics. The provisional 78% thesis figure is not enough to call the signal real because five of nine horizons are incomplete and only eight post-epoch closes exist.

Three new integrity failures matter before strategy tuning:

1. fatal job outcomes can be recorded green;
2. the GTC post-fill path bypasses the named pilot allowlist; and
3. outcome ingest can silently omit a real close and erases the causal exit reason even when it does ingest.

Two closure/status claims also fail cold-code review: E7’s viability bias is bypassed by the active cohort executor, and I6’s “merged package” claim is not present on current `main` or in the schema/backlog.

## Finding register

| ID | Severity | Finding | Present consequence |
|---|---:|---|---|
| F-A4-1 / E6 | Critical | Runner treats most error-shaped dict results as success; F8 recognizes only `counts.errors` | A fatal q15 risk-control cycle can fail green and avoid retry/escalation |
| F-A2-1 | High | GTC post-fill placement bypasses pilot position allowlist | Broker-side close orders may be created outside operator-approved pilot scope |
| F-A3-1 | High | Outcome ingest is not conserved and discards the actual exit cause | Tiny-N learning can lose a close and cannot separate thesis from exit mechanism |
| F-A6-1 / E7 | High | Active Policy-Lab cohort route bypasses viability bias; test inspects inactive path | Closure claim is false; small pre-gate top-N remains raw-EV ordered |
| F-STATE-I6 | High, latent | Book-scaling package is claimed merged but remains open/unbuilt in current code/schema | Routine multi-position operation would still rely on book-blind custody |
| F-A10-1 | High consequence, latent | Missing/unparseable expiry becomes `999` DTE; assignment-created equity is filtered from option sync | Expiry protection can silently disable and resulting stock can be unmanaged |
| F-A6-2 | Medium-high | Cohort attempt limit is applied before executable eligibility | Rejected top-N rows are not backfilled by viable tail candidates |
| F-A3-2 | Medium | Strategy autotune persists versions that scanner only logs | A successful tuner can look applied while decisions remain unchanged |
| F-A4-2 | High if confirmed | APScheduler “retry” may only repaint a DB row to queued without enqueuing RQ work | Retry may be a silent zero depending on deployed worker topology |
| F-A9-1 | Medium | Composite rank score is displayed as “Confidence N%” | Score 100 is presented as calibrated certainty |
| F-A9-2 | Medium | Job Monitor UI uses obsolete statuses and attempt field | Real job state can render blank, neutral, or filter to zero |
| F-A8-1 | Medium | `execution_cost_exceeds_ev` is recorded before a soft-mode candidate is emitted | Stored rejection can describe an actual “yes, penalized” |
| F-A8-2 | Medium | `ev_below_roundtrip_cost` includes positive-net but sub-$15 rows | Safe decision, false causal label |
| F-A10-2 | Medium | Default-off import-pinned day orchestrator can report green-disabled and is unwatched | Missed-job recovery can be absent indefinitely without a red signal |
| F-A10-3 | Medium | Weekday schedules/health disagree with broker session truth on holidays and early closes | A 14:45 CT exit run can occur hours after a half-day close |
| F-A5-1 | Low | Expired 48-hour Phase-2 precheck still runs every six hours on weekdays | About 20 no-information jobs per week |

---

# A1 — PROFITS

## Pass 1 — charter verdict

**Still the right question, with a changed answer.** At eight post-epoch closes, outcome-pattern claims remain disqualified. The current binding constraint is not “the account is too small” in isolation; it is the calibrated EV carried by the supported structure class relative to executable per-contract friction and the $15 evidence floor.

Capital is a secondary constraint. One typical one-lot five-wide IC with roughly $351 max loss and $21–40 costs consumes about 18–19% of $2,067.86. The repository’s $7.5–8k adequacy figure describes a desired 5%-per-trade/20%-aggregate risk policy. Actual small-tier allocator constants permit 36% per trade and an 85% envelope. A one-lot IC can therefore “fit” current code while remaining economically unattractive and policy-coarse.

## Pass 2 — cold-code findings

Core paths read: scanner/score → compounder → canonical ranker → allocator/sizer → final round-trip gate; `portfolio_allocator.py`, the position schema, capital-adequacy note, packet candidate economics, backlog and ledger.

### Structural economics on the current basis

| Reconstructable candidate | `EV_raw` | `EV_cal = 0.5×raw` | Executable RT/contract | Calibrated net | Gap to $15 |
|---|---:|---:|---:|---:|---:|
| QQQ IC 07-07 | $42.45 | $21.225 | $7 | **$14.225** | **−$0.775** |
| QQQ IC 07-08, qty 1 | $41.22 | $20.610 | $39 | −$18.390 | −$33.390 |
| QQQ IC 07-08 neutral | $42.14 | $21.070 | $22 | −$0.930 | −$15.930 |
| SOFI 07-09 candidate | $39.71 | $19.855 | $12 | $7.855 | −$7.145 |
| SOFI 06-30 vertical | $30.63 | $15.315 | $27 | −$11.685 | −$26.685 |

This is **0/5 clears** in the evidence that can be recomputed. The best row needed `EV_raw ≥ 2×($7+$15) = $44`; it had $42.45. For the packet’s common $21–40 cost range, raw EV must be **$72–110 per contract**. The packet says typical raw EV is about $40.

A two-leg structure could lower leg friction, but it must independently produce sufficient raw EV and pass the known PoP-semantics prerequisite. Halving the IC’s $7 cost in the best historical row would mathematically clear only under the unproven assumption that a vertical has the same EV. This audit does not make that assumption and recommends no live structure change.

### F-STATE-I6 — High, latent: the book-scaling package is not merged

**What.** The supplied v1.2 state calls I6’s risk custody, utilization basis, bucket control and same-run reservation a “merged package.” Current `main` and the backlog do not.

**Where.** `docs/backlog.md:47-60` still lists P0-B as open. [`portfolio_allocator.py:116-144`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/services/portfolio_allocator.py#L116-L144) still reads `paper_positions.cost_basis/current_value`; [`20250101000009_paper_trading.sql:25-36`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/supabase/migrations/20250101000009_paper_trading.sql#L25-L36) does not define those columns.

**Why/impact.** Open spread exposure can still collapse toward $0 in allocator custody. This does not prove a current breach while the book is at most one position, but it disproves readiness for routine two-position operation. The one-beta alarm is not a blocking control.

**Evidence/confidence.** Repository-dispositive; high confidence. Runtime deployment could be ahead of GitHub only if doctrine/source precedence has been violated, which itself would require explanation.

**Risk.** High on future live entry/book-scaling path; latent under the one-position condition.

**Runtime check.** Verify deployed SHA and query `information_schema.columns` for `cost_basis`, `current_value`, `max_loss`, and `collateral` on `paper_positions`. Zero matching columns plus deployed `e45290f` confirms the package is unbuilt. A later deployed SHA containing the package refutes only the status mismatch.

**Recommendation boundary.** Do not redesign I6 here. Correct the ledger/state claim and do not treat routine two-position operation as authorized until the owned package is actually merged and runtime-proven.

### Known open, not re-promoted: canonical ranker quantity units

The prior committed external audit already recorded that [`canonical_ranker.py:63-96`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/analytics/canonical_ranker.py#L63-L96) subtracts quantity-total fees and divides by quantity-total max loss from one-lot EV. At ×0.5, the 07-07 q4 candidate computes `$21.225 − $1.061 − $5.20 = $14.964` and hard-rejects, while the per-contract expression is `$18.864` and passes that ranker floor. This remains a real upstream false-NO/downranking mechanism, but it is a known multi-basis/qty-unit item, not a fresh finding from this pass. Any correction can admit trades and therefore belongs in observe/replay before live use.

## Pass 3 — value grade

**A / EARNING; retain.** A1 continues to produce structural arithmetic and custody truth that eight outcomes cannot. It also caught a material state/merge disagreement. The area remains load-bearing until unit economics and book custody are coherent.

---

# A2 — LOSSES

## Pass 1 — charter verdict

**Sound and load-bearing.** I1 owns broker acknowledgment after close submission and I4 owns stop measurement. Fresh territory is broker-order admission and expiry ownership. The most likely avoidable loss outside those owned items is an unapproved resting broker order or an expiry/assignment state that no internal book owns.

## Pass 2 — cold-code findings

Core paths read: full `gtc_profit_exit.py`, its tests and job hook; Alpaca open-fill hook; exit DTE/expiry conditions and quote defers; full option-position sync and Alpaca position adapter.

### F-A2-1 — High: post-fill GTC placement bypasses the pilot allowlist

**What.** `GTC_PROFIT_EXIT_PILOT_POSITION_IDS` constrains the scheduled sweep, but the automatic post-entry-fill path never checks it. If the global GTC flag is on, every otherwise eligible live fill can receive a broker-side resting close regardless of the operator’s named pilot positions.

**Where.** [`gtc_profit_exit.py:194-246`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/services/gtc_profit_exit.py#L194-L246) parses and applies the allowlist only in `place_resting_tp_for_open_positions`. [`alpaca_order_handler.py:936-947`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/brokers/alpaca_order_handler.py#L936-L947) invokes `maybe_place_gtc_profit_exit` after every live opening fill; [`gtc_profit_exit.py:328-458`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/services/gtc_profit_exit.py#L328-L458) never reads the allowlist. [`test_gtc_profit_exit.py:445-470`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/tests/test_gtc_profit_exit.py#L445-L470) tests pilot scope only through the sweep.

**Why it matters.** This is not an exit-threshold disagreement. It widens the set of positions allowed to create broker-side orders and exposes unapproved positions to GTC/stop pre-cancel, orphan/parity, and refresh lifecycle behavior.

**Impact/evidence.** The packet says the 07-07 force-close pre-cancelled a resting TP; `CLAUDE.md` says live exercise began 06-13. The code is therefore not safely dismissible as dead. Historical exercise depends on contemporaneous flag/allowlist values.

**Risk/confidence.** High, live broker close path. Code confidence very high; historical exercise medium pending runtime reconstruction. It is independent of I1 because I1 governs submission outcome, while this defect governs which positions may submit.

**Additive recommendation.** Use one shared pilot-scope predicate at the common placement boundary for both sweep and fill-hook paths; first inventory existing broker/DB GTC orders. This narrows behavior and loosens no control.

**Runtime check/falsifier.** Read current and historical `GTC_PROFIT_EXIT_ENABLED` and `GTC_PROFIT_EXIT_PILOT_POSITION_IDS`, then enumerate all `paper_orders` whose `order_json.source_engine='gtc_profit_exit'` or `order_class='intentional_resting_exit'`. An order created by the post-fill hook outside a contemporaneous nonempty allowlist confirms exercise. Flag-off at every such fill, or an intentionally empty list meaning “all eligible,” refutes historical exercise but not the split-scope code defect.

### F-A2-2 — Medium-high, latent: assignment can create a position outside the managed book

**What.** The system tries to exit before expiry and on expiration day, but has no exercise/assignment/expiration-activity reconciliation. An assignment-created stock position is deliberately excluded by option-only synchronization.

**Where.** [`paper_exit_evaluator.py:107-158`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/services/paper_exit_evaluator.py#L107-L158) returns `999` DTE when no expiry parses; DTE and expiration-day triggers are at `:474-515`. Dark executable sides can defer a live close at `:1958-1967`; repeated defer alerts but continues to hold at `:747-805`. [`position_sync.py:27-47`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/brokers/position_sync.py#L27-L47) fetches only option positions. [`alpaca_client.py:535-543`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/brokers/alpaca_client.py#L535-L543) filters all broker positions using option-symbol shape; assigned QQQ/SPY stock is excluded. Repo search found no assignment/DNE/activity reconciler.

**Why/impact.** Defined risk remains capped only while both legs settle as intended. Pin risk or asymmetric exercise can create temporary stock exposure far larger than a ~$2k account, invisible to the internal option book and learner. No assignment is present in the packet; 7–14-DTE exits lower probability. The precise exposure path is a repeatedly dark/rejected close carried to expiry.

**Risk/confidence.** High consequence, currently low probability. High confidence that code ownership is absent; occurrence unproven.

**Additive recommendation.** Add an alert-only expiry sentinel that reads **all** broker positions and option lifecycle activities and loudly quarantines unexpected equity/assignment state. No automatic liquidation is authorized by this report.

**Runtime check/falsifier.** Pull all broker positions without the option filter plus assignment/exercise/expiration activities since 2026-06-08. Any unexpected equity position or lifecycle activity without an internal reconciliation row confirms exposure. A verified broker guarantee of pre-assignment liquidation for every supported multileg shape plus runtime proof of no such activity would retire it.

### Resting-GTC lifecycle status note

The existing spec already calls for refresh-on-recalculation and nightly parity, so those are not re-filed. Current code skips when any close-side order exists without comparing its price with the current cohort target (`gtc_profit_exit.py:264-278,394-408`). More importantly, `docs/specs/resting_tp_orders.md:3-6` still says the feature was never enabled live, while `CLAUDE.md` and the packet prove live use. That stale status is listed under disagreements.

## Pass 3 — value grade

**A+ / EARNING; retain permanently.** This area again found a production-path/test-path scope mismatch on a live broker-order path. Its territory cannot retire while close-order admission and expiry/assignment ownership remain incomplete.

---

# A3 — SELF-LEARNING

## Pass 1 — charter verdict

**Sound, but the binding question is conservation before sophistication.** At about one live close per week, losing one outcome costs about a week of evidence. Before adding models, the system must prove that every real close produces exactly one causally complete record and every learned adjustment has a named decision consumer.

## Pass 2 — cold-code findings

Core paths read: full `paper_learning_ingest.py`; `learning_ingest.py`, outcome normalization, post-trade learning; strategy autotune, `suggestions_open.py`, dynamic weight service; and the canonical learning view migration.

### F-A3-1 — High: outcome ingest is not conserved and erases the exit cause

**What.** Three seams compose:

1. a closed position without a filled closing-order row is silently skipped;
2. the caller computes `order.suggestion_id OR position.suggestion_id`, but the builder re-reads only the order value; and
3. `close_reason`, entry DTE, and expiry are not selected, so learning stores generic `paper_trade_close` and policy backfill writes a blank exit reason.

**Where.** [`paper_learning_ingest.py:231-234`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/jobs/handlers/paper_learning_ingest.py#L231-L234) omits the causal fields. Missing order continues at `:382-386`; `skipped_no_order` is omitted from returned counts at `:464-471`. Fallback resolution occurs at `:394-397`, but the builder reads only `order.suggestion_id` at `:571-590`. The canonical view inner-joins suggestion ID at [`20260411000000_add_ev_raw_and_entry_dte.sql:42-44`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/supabase/migrations/20260411000000_add_ev_raw_and_entry_dte.sql#L42-L44). Generic reason is written at `paper_learning_ingest.py:628`; policy backfill reads the unselected `position.close_reason` at `:671-686`.

**Why it matters.** The working thesis is “signal may be directionally right while costs/exits lose money.” That cannot be tested when stop, target, DTE, expiry, manual, and reconciled exits collapse to one generic label. Manual/reconciled closes can disappear while the job reports success.

**Impact/evidence.** The packet records NFLX 06-08 as absent from the learning table: **1 of 9 real broker closes missing, or 11.1% all-time conservation failure**. It is pre-epoch and does not reduce the stated eight-close calibration set. Its exact missing-order cause needs the runtime join. Causal labels are structurally lost more broadly, including the two force-close cases where they matter most.

**Risk/confidence.** No direct trading mutation; high learning/governance risk. Structural confidence very high; NFLX root-cause attribution medium.

**Additive recommendation.** Enforce: “every closed live position creates exactly one `trade_closed` record or one explicit quarantined exception.” Carry position-level suggestion ID, close reason, entry DTE, and expiry. Count and alert missing closing orders. This loosens no control.

**Runtime check/falsifier.** Join all live-routed closed positions to their latest filled close order and `learning_feedback_loops` outcome. Confirm with any missing/duplicate outcome, null outcome suggestion ID, or generic/blank exit reason. Exact one-to-one post-epoch coverage narrows observed impact but does not refute future manual/assignment shapes in the current code.

### F-A3-2 — Medium, latent: strategy autotune persists versions that decisions do not consume

**What.** `strategy_autotune` computes and inserts mutated `strategy_configs`. `suggestions_open` loads the latest version for a note, then calls `run_midday_cycle(client, user_id)` without passing or applying it. Repo-wide `load_strategy_config` search found no scanner/orchestrator consumer.

**Where.** [`strategy_autotune.py:235-323,384-408`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/jobs/handlers/strategy_autotune.py#L235-L408) computes/persists; [`suggestions_open.py:126-151`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/jobs/handlers/suggestions_open.py#L126-L151) logs then invokes the native workflow. The tuner has no APScheduler entry and is manually dispatchable.

**Why/impact.** A successful job can say “Using strategy vN” while live decisions are byte-identical. At n=8, inertness is safer than automatically activating mutations; the immediate decision is to label/retire the component as observe-only unless a governed consumer is intended. Impact is latent if no successful run/version >1 exists.

**Risk/confidence.** Current live-decision risk low because output is inert; high confidence from call graph.

**Runtime check/falsifier.** Query `job_runs` for successful `strategy_autotune` and `strategy_configs` for versions >1. Such rows followed by unchanged decision parameters confirm exercised inertness. Zero successful jobs and only v1 refute current impact. A decision trace proving version-dependent scanner output would refute the code-path conclusion.

### Known item confirmed, not re-filed

`post_trade_learning` writes `signal_weight_history` and `strategy_adjustments`; `DynamicWeightService.apply_to_score` documents and exhibits no call sites. The backlog already owns this dormant consumer and its missing live/epoch filters. It is not counted again.

## Pass 3 — value grade

**A / EARNING; retain.** Prior work fixed duplicate outcomes, live/paper labels and calibration application. This pass found a more fundamental conservation/causality failure and another inert writer. Tiny-N makes every missing or mislabeled close disproportionately expensive.

---

# A4 — SELF-SUSTAINING

## Pass 1 — charter verdict

**Sound, with the next question one layer lower than I2.** Six named producer/noise gaps are owned by I2. The fresh control is the generic contract between a handler’s return value, `job_runs.status`, retries, and health. A job that truthfully returns failure but is persisted green is slower to detect than a missing job.

## Pass 2 — cold-code findings

Core paths read: job dispatcher/runner outcome handling; q15 risk-monitor and day-orchestrator top-level exceptions; ops-health job-result detector; retry scheduler; scheduler/worker architecture and tests. I2’s six owned items and the known stuck-running reaper were not re-derived.

### F-A4-1 / E6 — Critical: fatal handler results can be persisted as succeeded

**What.** The generic runner treats every dict result as success unless top-level `users_failed > 0`. It ignores `ok:false`, error-like `status`, `counts.failed`, and most `counts.errors`. Health then inspects only already-succeeded rows with exactly `result.counts.errors > 0`.

**Where.** [`jobs/runner.py:124-140`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/jobs/runner.py#L124-L140) defines the success translation. [`intraday_risk_monitor.py:147-158`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/jobs/handlers/intraday_risk_monitor.py#L147-L158) returns `{"ok": false}` on a fatal risk-monitor exception; [`day_orchestrator.py:38-48`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/jobs/handlers/day_orchestrator.py#L38-L48) does likewise. [`ops_health_service.py:636-684`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/services/ops_health_service.py#L636-L684) recognizes only the narrow `counts.errors` shape.

**Why it matters.** A fatal q15 stop/risk-monitor cycle can advance the latest-success freshness anchor, avoid runner retry/dead-letter behavior, and evade F8. A deterministic fault can repeat every cycle while each row remains green. This is not I1’s close-state design; it is the job-control plane surrounding the entire live protection cycle.

**Impact/evidence.** The packet’s 07-08 F8 proof is valid for its exact producer: `counts.errors=6` was detected. That narrow success does not make the generic contract safe. The direct code path supports one missed 15-minute protection cycle per event, repeatable for persistent faults. Historical frequency is unknown.

**Risk/confidence.** Critical live-capital control path; high confidence.

**Additive recommendation.** Define one typed outcome contract for every handler and make any explicit failure shape non-green at the runner boundary. Health should reason from normalized `job_runs.status/error_code`, not producer-specific JSON. Roll out with an inventory because changing generic retry semantics may expose previously hidden failures. This tightens truth and loosens no trading control.

**Runtime check/falsifier.** Run the P0 false-green query in the consolidated list. Any succeeded row with `ok=false`, error/failed status, or positive failed count proves exercise. Zero rows limits the observed blast radius; only a deployed normalization layer absent from the repository would refute the structural path.

### F-A4-2 — High if confirmed: the scheduled “retry” may repaint DB state without re-enqueuing work

**What.** APScheduler selects `failed_retryable`, updates it to `queued`, and logs requeue, but does not call the canonical RQ enqueue path. Tests pin only the database transition. A legacy DB-poll worker also exists, so deployment topology decides whether the row is ever reclaimed.

**Where.** [`scheduler.py:288-326`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/scheduler.py#L288-L326).

**Why/impact.** If Railway runs only RQ workers, “retry” is a silent zero and failed jobs remain unexecuted despite a queued status. If a deployed DB-poll worker claims these rows, the design is functional. Code-only evidence cannot settle the topology.

**Risk/confidence.** High operational impact if confirmed; medium confidence pending deployment read.

**Runtime check/falsifier.** Inspect all Railway worker start commands. Trace rows that transition `failed_retryable → queued` and see whether `started_at/locked_at` advances or an RQ job ID appears. Confirm if only RQ workers exist and rows never start. Refute if a deployed DB-poll worker consistently claims them.

## Pass 3 — value grade

**A+ / EARNING; retain.** A4 found a generic false-green seam beneath the producer-specific fixes and a plausible silent-zero retry path. Because one finding guards q15 live protection, this territory is load-bearing regardless of consecutive quiet audits.

---

# A5 — EFFICIENCY

## Pass 1 — charter verdict

**Sound, but subordinate to correctness.** “Waste” should include recurring work that can no longer produce information, not just API dollars. The calibration-ordering work is owned by I3 and the unexplained third scan cycle is already filed; neither is re-litigated here.

## Pass 2 — cold-code findings

Core paths read: scheduler inventory, expired phase precheck, job dispatch and cadence comments; cross-checked against the cadence-map known item.

### F-A5-1 — Low: an expired 48-hour precheck runs forever

**What.** `phase2_precheck` is scheduled every six hours Monday–Friday. Once the 48-hour window expires, the handler deliberately returns `ok:true,status:'window_expired'`, but the schedule remains permanent.

**Where.** [`scheduler.py:124-128`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/scheduler.py#L124-L128); [`phase2_precheck.py:177-188`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/jobs/handlers/phase2_precheck.py#L177-L188).

**Why/impact.** It still incurs signed HTTP, queue/job rows, worker dispatch, and database/config reads while buying zero evidence: **20 no-op runs per week**, roughly 220 since the 04-25 window ended, subject to runtime count.

**Risk/confidence.** Low; high code confidence.

**Recommendation.** An operator decision to retire or explicitly archive the expired schedule. No control or gate is affected.

**Runtime check/falsifier.** Count `job_runs` where `job_name='phase2_precheck'` and `result.status='window_expired'`. Zero refutes realized waste; any count measures it exactly.

### No second promoted efficiency finding

The no-op `learning_ingest`, all-missing IV refresh, 13:34Z cadence anomaly, and downstream calibration ordering are already owned by I2, the known-open cadence query, or I3. The audit did not inflate the area by renaming them.

## Pass 3 — value grade

**B / EARNING at low priority.** The area found a clean, low-effort deletion candidate but should not consume capacity ahead of A4/A2/A3 integrity.

---

# A6 — VIABLE-SET HANDLING

## Pass 1 — charter verdict

**Reopened and still central.** Raw-era labels such as `_VIABILITY_TIERS['SPY']='CLEARS'` no longer establish a viable set under production ×0.5 calibration. Code-only review cannot perform a live “today” chain search; the honest evidence is the five reconstructable packet candidates plus a precisely specified 07-10 runtime census.

Observed evidence is 0/5 calibrated clears. A two-leg cost sensitivity is only a sensitivity, not proof that a corresponding vertical has the same EV or valid PoP. The known PoP-unification prerequisite remains controlling.

## Pass 2 — cold-code findings

Core paths read: `execute_top_suggestions` dispatch, `get_executable_suggestions`, active per-cohort executor, query limit and downstream gates, viability tests, final stage gate and rejection writers.

### F-A6-1 / E7 — High exclusion-integrity failure: viability bias is bypassed on the active cohort route

**What.** With Policy Lab enabled, `execute_top_suggestions` immediately returns `_execute_per_cohort`. The only method using `_viability_rank_key` is the bypassed `get_executable_suggestions`. The active cohort method SQL-orders raw `risk_adjusted_ev, ev` and never calls the bias.

**Where.** [`paper_autopilot_service.py:449-452`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/services/paper_autopilot_service.py#L449-L452) dispatches. Biased sorting exists only at [`:118-149`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/services/paper_autopilot_service.py#L118-L149). The active query is at [`:857-868`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/services/paper_autopilot_service.py#L857-L868). [`test_m4_obp_failclosed_and_wiring.py:143-183`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/tests/test_m4_obp_failclosed_and_wiring.py#L143-L183) source-inspects the bypassed method instead of exercising dispatch.

**Why it matters.** E7’s “wired with executor-path test” closure claim is false. It is the same test-green/wrong-production-path class that previously allowed bad routing values. Because only a small top-N enters downstream checks, unreachable bias can change which rows are attempted.

**Impact/evidence.** Packet-reported neutral/conservative shadow executions demonstrate the cohort path is active when Policy Lab is enabled. Current direct economic impact is likely zero because bias cannot make a sub-floor candidate clear and its raw-era tiers are stale. That is a reason **not to wire it blindly**, not a reason to preserve a false closure claim.

**Risk/confidence.** High evidence-quality/viable-set relevance; direct live-profit impact unproven. High confidence conditional on the deployed Policy Lab flag, which runtime logs can settle.

**Recommendation.** First revalidate viability tiers under calibrated, executable economics. Then make one dispatch-level test prove the production route uses the intended rank key. Any live ordering change should be shadow/diffed. No gate should be loosened.

**Runtime check/falsifier.** Read `POLICY_LAB_ENABLED` and one executor log. `true` plus `[AUTO_EXEC] cohort=` confirms the bypass path. Refutation requires an execution trace proving `_viability_rank_key` affected the cohort ordering.

### F-A6-2 — Medium-high: the daily attempt limit is applied before executable eligibility

**What.** `_execute_per_cohort` applies `.limit(config.max_suggestions_per_day)` in SQL, then evaluates cooldown, already-held symbol, utilization, quote freshness and final round-trip economics. A rejected row within top N is not replaced by rank N+1.

**Where.** Query/limit at [`paper_autopilot_service.py:857-868`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/services/paper_autopilot_service.py#L857-L868); downstream gates at `:876-1031`.

**Why it matters.** This is distinct from the known greedy compounder `break`. It is a third evidence-starvation mechanism beyond shared calibrated scoring and shadow fill fiction: top-N means “top N before eligibility,” not “attempt up to N eligible rows.”

**Impact.** Blast radius is runtime-dependent. Current calibrated zero-clear state may make it irrelevant today; when any rows become economic, it can suppress evidence volume without recording that a viable tail was never attempted.

**Risk/confidence.** Medium-high learning-volume impact; high code confidence, realized impact unknown.

**Recommendation.** Read-only replay first: examine rows beyond N and require a tail row to pass every unchanged gate before considering a bounded eligible-backfill design. This finding does not justify increasing the daily cap.

**Runtime check/falsifier.** For each cohort/cycle, rank all pending rows by the active SQL order, compare beyond-N rows with created orders, and reprice only the unattempted tails. Confirmed impact requires fewer than N successful attempts **and** a tail candidate that passes every current gate. No such row falsifies present blast radius.

### Current viable-set runtime check

Parse every 07-10 `[ENTRY_ROUNDTRIP_GATE]` record and compute the maximum **per-contract calibrated** `new_net`. “Approximately zero clear” is confirmed if every row is `<15`. Any row `≥15` immediately reopens the settled condition and should be traced by underlying, structure, DTE, width and quote timestamp.

## Pass 3 — value grade

**A / EARNING; retain.** A6 caught an E7 exclusion-integrity failure and a distinct pre-eligibility truncation seam. It remains central because honest learning volume is zero if no structure clears.

---

# A7 — DORMANT

**Fills to date: 9/10.** The area remains dormant exactly as directed; no timing/hold-period conclusion is drawn.

**Pass 3 grade:** Dormant, not retired. Exit custody remains covered by A2 and learning conservation by A3.

---

# A8 — NEGATIVE-DECISION EFFICACY

## Pass 1 — charter verdict

**Sound, but no fresh class is proven to have discarded a finally economic trade.** E2 and the known ranker unit issue own the strongest false-NO arithmetic. The fresh result is narrower: two rejection labels are provably false, so rejection-ledger studies can answer the wrong causal question even when the final decision was safe.

## Pass 2 — cold-code findings

Core paths read: scanner execution-cost branch across regime hard/soft behavior; final entry round-trip gate; rejection persistence and packet counterexamples.

### F-A8-1 — Medium: `execution_cost_exceeds_ev` may describe a candidate that was emitted

**What.** The scanner records the rejection reason before choosing the hard/soft regime branch. In ELEVATED/SHOCK or configured soft mode, a candidate with cost between `1.0×EV` and `1.5×EV` is penalized and emitted, yet remains counted/persisted as a rejection.

**Where.** [`options_scanner.py:3781-3821`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/options_scanner.py#L3781-L3821).

**Why/impact.** This inflates rejection counts and contaminates counterfactual studies with decisions that were actually “yes, with penalty.” It can also make the funnel appear more restrictive than execution behavior.

**Risk/confidence.** Observability only if corrected as taxonomy; high confidence.

**Runtime check/falsifier.** Query `suggestion_rejections` with `reason='execution_cost_exceeds_ev'`, join regime/soft-mode fields, and compare cost with deployed `EXECUTION_COST_MAX_MULT` and `EXECUTION_COST_HARD_REJECT`. A row below the soft maximum that subsequently became a suggestion/order confirms. No soft-mode rows refutes observed incidence.

### F-A8-2 — Medium: `ev_below_roundtrip_cost` conflates negative net with positive-but-insufficient net

**What.** The final gate rejects whenever `EV − cost < $15`, then always stamps `ev_below_roundtrip_cost`.

**Where.** [`paper_endpoints.py:1311-1377`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/paper_endpoints.py#L1311-L1377).

**Direct evidence.** The packet’s 07-08 QQQ row had raw-era EV $41.22, cost $39 and positive net **+$2.22**. The decision was correct under a $15 floor, but EV was not below round-trip cost.

**Why/impact.** Negative-after-cost and positive-but-below-required-margin have different economic diagnoses. Conflating them can send the operator toward spreads/fees when the actual shortfall is margin-of-safety, or vice versa.

**Risk/confidence.** No live risk for a taxonomy-only distinction; high confidence.

**Runtime check/falsifier.** Parse `blocked_detail` for net among rows with this reason. Any `net ≥ 0` confirms a mislabeled row. The packet already supplies one historical counterexample.

## Pass 3 — value grade

**B+ / EARNING.** The area found two false causal classes, including one recorded “NO” where the branch actually emitted a candidate. It remains useful, but no hidden profitable trade is proved in this pass.

---

# A9 — ALERT & SIGNAL INTEGRITY

## Pass 1 — charter verdict

**Sound and standing.** The most misleading surfaces now are not the I2-owned alert-noise classes. They are a composite rank displayed as calibrated probability and an operator job monitor whose schema no longer matches the database.

## Pass 2 — cold-code findings

Core paths read: suggestion card display/fallbacks, opportunity scorer, job-run database enum, frontend job types/badges/filters/table, and packet labels. F-A4-1 is cross-referenced rather than duplicated: a green job status is itself the most dangerous signal-integrity failure.

### F-A9-1 — Medium: rank score is displayed as “Confidence N%”

**What.** The dashboard converts `agent_summary.overall_score` or raw `score` to a percentage and labels it confidence. The producer defines a composite total built from EV points, PoP points, IV bonus, liquidity/event penalties, and a 100 cap. It is not calibrated probability.

**Where.** [`SuggestionCard.tsx:343-355,679-684`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/apps/web/components/dashboard/SuggestionCard.tsx#L343-L355); [`opportunity_scorer.py:59-63,194-251`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/analytics/opportunity_scorer.py#L194-L251).

**Why/impact.** Score 100 is saturation, not certainty. Presenting it as `Confidence 100%` encourages the reader to interpret a rank feature as a calibrated forecast, precisely when current EV/PoP calibration is still tiny-N and score ancestry can be raw.

**Risk/confidence.** Medium operator-decision risk; high confidence.

**Recommendation/falsifier.** Label the field “Rank score” and reserve confidence/probability for a calibrated field with provenance. This is display-only. A hidden API transformation that supplies a formally calibrated `overall_score` for every card could narrow the fallback issue, but the raw-score fallback still proves the label unsafe.

### F-A9-2 — Medium: Job Monitor UI is schema-drifted

**What.** The database statuses are `queued/running/succeeded/failed_retryable/dead_lettered/cancelled`. Frontend types and components expect `pending/processing/completed/failed/...` plus `attempt_count`, while the table schema uses different attempt fields.

**Where.** [`20251220000001_job_runs_db_queue.sql:4-16`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/supabase/migrations/20251220000001_job_runs_db_queue.sql#L4-L16); [`apps/web/lib/types.ts:233-249`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/apps/web/lib/types.ts#L233-L249); `JobStatusBadge.tsx:12-35`; `JobFilters.tsx:31-46`; `JobsTable.tsx:50-57`.

**Why/impact.** Filters can return zero for real states, successful/running jobs fall to neutral styling, and attempts can render blank. This weakens the operator’s ability to notice F-A4-1/F-A4-2 symptoms.

**Risk/confidence.** Medium operational visibility; high code confidence, visible runtime symptom needs API readback.

**Runtime check/falsifier.** Compare the jobs API JSON with one known row in each current database status and render/filter it. A server-side translation to the legacy enum plus `attempt_count` could refute the visible symptom; absent that, code mismatch confirms it.

### Cross-reference: false-green is the dominant signal lie

F-A4-1 also belongs conceptually here. The packet’s exact `counts.errors=6` proof remains true; the generic “F8 closed” inference is not. A status badge cannot compensate for a runner that writes the wrong status.

## Pass 3 — value grade

**A− / EARNING; retain.** The area found two present-tense operator lies and shares the critical job-outcome seam. It remains standing.

---

# A10 — CALENDAR & CLOCK INTEGRITY

## Pass 1 — charter verdict

**Sound; retain the incumbent.** The territory should be framed as one authoritative exchange-session/expiry boundary rather than a collection of UTC constants. Correct components presently disagree about holidays, half-days, expiry metadata and when configuration changes become effective.

## Pass 2 — cold-code findings

Core paths read: DTE/expiration parsing, quote-defer behavior, option sync; scheduler and shared market-day helper; ops-health age calculation; day orchestrator; repository-wide module-scope environment reads; runbook schedule text.

### F-A10-1 — High consequence, latent: unknown expiry silently becomes 999 DTE

**What.** If neither nearest expiry nor a leg expiry parses, `days_to_expiry` returns `999`. That prevents DTE and expiration-day conditions from firing despite the module’s “must close” expiry doctrine.

**Where.** [`paper_exit_evaluator.py:107-158`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/services/paper_exit_evaluator.py#L107-L158); DTE/expiry triggers at `:474-515`.

**Why/impact.** Missing metadata is translated into “very far away,” the least protective answer. If an affected row is live, the normal pre-expiry close rule is disabled and assignment exposure from A2 becomes reachable.

**Risk/confidence.** High live-capital consequence if a row is affected; high code confidence, blast radius unknown.

**Additive recommendation.** Treat expiry as typed `KNOWN/UNKNOWN`, fail loud on UNKNOWN, and surface the row for operator action. This report does not authorize automatic close or a stop change.

**Runtime check/falsifier.** List all open `paper_positions` whose `nearest_expiry` is null/unparseable and validate every leg expiry. Any row lacking both confirms active exposure. Zero refutes current blast radius, not the fail-open conversion.

### F-A10-2 — Medium: default-off import-pinned orchestrator can be green and unwatched

**What.** `ORCHESTRATOR_ENABLED` is read at import with default `0`. When disabled, the scheduled handler returns `ok:true,status:'disabled'`. It is absent from the expected-jobs health registry. The prompt’s import-time inventory does not name this flag. `EXIT_RANKING_ENABLED` is another unlisted import-pinned decision flag.

**Where.** [`day_orchestrator.py:1-48`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/jobs/handlers/day_orchestrator.py#L1-L48); `paper_exit_evaluator.py:37-38`.

**Why/impact.** A component advertised as missed-job recovery can be absent indefinitely, report green-disabled, and remain outside health. An environment flip also requires recycle, repeating E1’s operational surprise class.

**Risk/confidence.** Medium resilience risk; high code confidence, deployed flag unknown.

**Runtime check/falsifier.** Read Railway env and process start/recycle time; inspect the latest ten `day_orchestrator` results. Repeated `status=disabled` confirms. A deployed enabled flag plus successful recovery traces refutes current inertness.

### Import-time inventory is materially incomplete

The prompt names four flags, but cold search found many additional module-scope environment reads on decision, safety, data-quality and operations paths, including:

- `RISK_ENVELOPE_ENFORCE` and intraday target-profit controls in `intraday_risk_monitor.py`;
- `CANONICAL_RANKING_ENABLED` and `MIN_EDGE_AFTER_COSTS` in `canonical_ranker.py`;
- market-data freshness/quality/spread thresholds in `market_data_truth_layer.py`;
- PDT, exit ranking, stop scaling, default target/stop/DTE in `paper_exit_evaluator.py`;
- scanner multi-strategy/spread/condor/execution-cost controls;
- equity-source, policy-promotion, post-trade-learning and scheduler flags.

This is broader than one new flag: the operator has no complete registry telling which environment changes require recycle and what effective value each process actually holds. The recommendation is additive observability—a generated flag registry (`name/default/polarity/read-mode/owner`) plus startup effective-config attestation. It does **not** recommend flipping any flag.

### F-A10-3 — Medium: early-close sessions compose weekday scheduling into late action

**What.** Schedules are weekday-only. The shared helper checks only weekdays while saying scheduler handles holidays. Ops health uses approximate hard-coded UTC hours and subtracts weekends, not holidays. The q15 risk monitor asks the broker clock, so components have different session truth.

**Where.** [`scheduler.py:245-250`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/scheduler.py#L245-L250); [`jobs/handlers/utils.py:44-50`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/jobs/handlers/utils.py#L44-L50); [`ops_health_service.py:42-55,379-384`](https://github.com/BrightBoost-Tech/options-trading-companion/blob/e45290fe77ca1b9a3c630c76f7267e17aacfa020/packages/quantum/services/ops_health_service.py#L42-L55); afternoon exit schedule at `scheduler.py:59-64`.

**Why/impact.** On a 13:00 ET half-day close, the 14:45 CT exit run occurs 2h45 after the market closed and may stage non-executable work. Holiday gaps can also produce stale-age noise. This extends the known holiday alert issue into action timing without re-filing the November DST item.

**Risk/confidence.** Medium; high code confidence.

**Recommendation.** One broker/exchange-session object should feed scheduler gates, exit eligibility and health age. This is not permission to relax any exit rule.

### Documentation clock disagreement

Current code schedules morning exit at 08:35 CT and afternoon exit at 14:45 CT. `docs/daily_workflow.md` still states 08:15/15:00 and describes orchestrator recovery despite the green-disabled default path. This is misleading documentation, not a second scheduling bug.

## Pass 3 — value grade

**A / EARNING; retain.** The incumbent found a fail-open expiry sentinel, new import-pinned controls and an early-close action seam. Rotation should wait until authoritative session/expiry ownership covers this live-money territory elsewhere.

---

# Consolidated runtime-check list

These are read-only checks. Priority reflects live-capital consequence and ability to settle a code/runtime uncertainty. Queries may need column-name adjustment to the deployed schema; do not substitute guessed values.

## P0 — False-green job outcomes, especially the q15 risk monitor

```sql
select
  job_name,
  count(*) as false_green,
  min(finished_at) as first_seen,
  max(finished_at) as last_seen
from job_runs
where status = 'succeeded'
  and finished_at >= now() - interval '30 days'
  and (
    result->>'ok' = 'false'
    or result->>'status' in (
      'error', 'failed', 'config_missing',
      'config_parse_error', 'user_id_missing'
    )
    or coalesce(result#>>'{counts,failed}', '0') ~ '^[1-9]'
  )
group by job_name
order by false_green desc;
```

**Confirm:** any row, with `intraday_risk_monitor` highest priority. Then inspect logs/alerts and whether the next cycle actually ran.  
**Refute observed incidence:** zero rows in the interval.  
**Structural falsifier:** only a deployed normalization layer not present on current `main` that converts every explicit failure shape before persistence.

Also query the narrow F8 shape separately (`status='succeeded' AND result#>>'{counts,errors}' > 0`) so the proven 07-08 behavior is not confused with the broader gap.

## P0 — GTC pilot-scope reconstruction and broker/DB parity

Read current and historical values of:

- `GTC_PROFIT_EXIT_ENABLED`
- `GTC_PROFIT_EXIT_PILOT_POSITION_IDS`

Then enumerate every intentional resting exit:

```sql
select
  id,
  position_id,
  created_at,
  status,
  alpaca_order_id,
  requested_price,
  order_json->>'source_engine' as source_engine,
  order_json->>'order_class' as order_class
from paper_orders
where order_json->>'source_engine' = 'gtc_profit_exit'
   or order_json->>'order_class' = 'intentional_resting_exit'
order by created_at;
```

For every row, compare with the allowlist effective at that entry fill and the broker’s current/historical order record.

**Confirm scope breach:** a post-fill-hook order outside a contemporaneous nonempty allowlist.  
**Confirm parity/lifecycle breach:** wrong target limit, duplicate working GTC, GTC on a closed position, DB-working/broker-absent, or broker-working/DB-absent.  
**Refute historical scope exercise:** the flag was off at every nonallowed fill, or the list was intentionally empty with documented “all eligible” semantics.

## P0 — Clock and deploy grounding

In one capture window, record:

1. Supabase `select now(), current_setting('TimeZone');`
2. Railway process UTC time, service name, process start time and deployed SHA for BE/worker/background;
3. Alpaca clock timestamp, `is_open`, next open and next close.

**Confirm clock/session disagreement:** material skew, different deployed SHAs, or a service using a stale process across an import-time flag change.  
**Refute:** clocks agree within normal network delay, services report intended SHAs, and effective flags match the recycled process.

## P1 — Learning-outcome conservation and causal completeness

```sql
with live_closed as (
  select
    p.id,
    p.symbol,
    p.closed_at,
    p.suggestion_id,
    p.close_reason
  from paper_positions p
  join paper_portfolios pf on pf.id = p.portfolio_id
  where p.status = 'closed'
    and pf.routing_mode = 'live_eligible'
)
select
  lc.*,
  o.id as close_order_id,
  o.execution_mode,
  l.id as outcome_id,
  l.suggestion_id as outcome_suggestion_id,
  l.details_json->'reason_codes' as reason_codes
from live_closed lc
left join lateral (
  select *
  from paper_orders po
  where po.position_id = lc.id
    and po.status = 'filled'
  order by po.filled_at desc nulls last
  limit 1
) o on true
left join learning_feedback_loops l
  on l.source_event_id = o.id
 and l.outcome_type = 'trade_closed'
order by lc.closed_at;
```

**Confirm:** missing order, missing or duplicate outcome, null outcome suggestion ID, or generic/blank exit cause.  
**Refute post-epoch blast radius:** exact one-to-one coverage for all eight post-epoch closes with correct suggestion links and causal reasons. The current code still leaves future manual/reconciled shapes exposed.

## P1 — Expiry/assignment inventory

1. Query all open positions with null/unparseable `nearest_expiry`; validate expiry on every leg.
2. Pull **all** Alpaca positions without the option-symbol filter.
3. Pull assignment, exercise and expiration activities since 2026-06-08.
4. Join each lifecycle event to internal position/reconciliation/learning records.

**Confirm:** an open row with no parseable expiry, an unexpected equity position, or an activity without internal ownership.  
**Refute current blast radius:** all open rows have valid expiry and no unexpected activity/equity exists.  
**Retirement falsifier:** a broker guarantee plus runtime history proving supported structures cannot leave assignment-created exposure.

## P1 — I6 merge/status truth

```sql
select column_name
from information_schema.columns
where table_name = 'paper_positions'
  and column_name in ('cost_basis','current_value','max_loss','collateral');
```

Also record deployed SHA and inspect current bucket/reservation enforcement logs.

**Confirm prompt disagreement:** deployed current `main`, zero required custody columns, and no blocking bucket/reservation path.  
**Refute:** a later deployed SHA and schema migration containing the owned package, with runtime proof.

## P1 — Calibrated viable-set census and E7 dispatch

For every 07-10 entry round-trip decision, extract structure, ticker, DTE, width, quantity, `ev_raw`, calibrated EV, sized and per-contract executable cost, `new_net`, quote timestamps, cohort and final status.

**Confirm zero-clear condition:** `max(new_net) < $15` on the per-contract calibrated basis.  
**Reopen immediately:** any row `new_net ≥ $15`.

Then read `POLICY_LAB_ENABLED` and capture executor logs.

**Confirm E7 bypass:** enabled plus `[AUTO_EXEC] cohort=` and no viability-rank trace on ordering.  
**Refute:** trace proving `_viability_rank_key` changed the active per-cohort ordering.

## P1 — Pre-limit viable-tail replay

For each cohort/cycle, reproduce the active `risk_adjusted_ev DESC, ev DESC` order for all pending rows, identify rows beyond `max_suggestions_per_day`, and read-only replay cooldown, held-symbol, utilization, quote freshness and final economic gates.

**Confirm impact:** fewer than N successful attempts and at least one beyond-N row passes every unchanged gate.  
**Refute current impact:** no beyond-N row clears all gates. Do not increase N merely because a tail exists.

## P1 — Retry topology

Inspect Railway worker commands and trace recent retryable rows:

```sql
select
  id, job_name, status, attempt, run_after,
  locked_at, updated_at, started_at, finished_at
from job_runs
where updated_at >= now() - interval '30 days'
  and status in ('queued','failed_retryable')
order by updated_at desc;
```

**Confirm silent retry:** only RQ workers are deployed and rows repainted queued never acquire a new `started_at`, lock or RQ job.  
**Refute:** a deployed DB-poll worker consistently claims them.

## P2 — Import-time effective-config inventory

For each service, generate the set of module-scope environment reads and compare it with current Railway env, process start/recycle time and startup logs.

Minimum explicit checks: `ORCHESTRATOR_ENABLED`, `EXIT_RANKING_ENABLED`, `RISK_ENVELOPE_ENFORCE`, `CANONICAL_RANKING_ENABLED`, `MIN_EDGE_AFTER_COSTS`, scanner execution-cost controls, market-data quality/age thresholds and exit defaults.

**Confirm stale-effective state:** env changed after process start or runtime behavior/logged effective value differs from current env.  
**Refute current mismatch:** every value is attested at startup and process recycle postdates the last change.

## P2 — Strategy-autotune exercise

```sql
select job_name, status, started_at, finished_at, result
from job_runs
where job_name = 'strategy_autotune'
order by started_at desc;

select name, version, created_at, params
from strategy_configs
order by name, version desc;
```

**Confirm exercised inertness:** successful job or version >1 followed by scans that retain native workflow parameters.  
**Refute current impact:** no successful runs and only version 1.

## P2 — Rejection-taxonomy truth

- For `execution_cost_exceeds_ev`, join regime/soft-mode fields, subsequent suggestion/order existence, and deployed hard/soft multipliers.
- For `ev_below_roundtrip_cost`, parse/recompute net.

**Confirm:** a soft-mode row was emitted after being recorded as rejected, or any labeled row has `net ≥ 0`.  
**Refute incidence:** no qualifying rows. The packet already confirms one positive-net historical label.

## P2 — UI truth and expired precheck count

Read the jobs API and render one row per current database status. Confirm or refute server-side status translation and attempt-field mapping. Separately count:

```sql
select count(*) as expired_runs,
       min(created_at), max(created_at)
from job_runs
where job_name = 'phase2_precheck'
  and result->>'status' = 'window_expired';
```

Any positive count measures F-A5-1; zero refutes realized waste.

---

# Free look

The free look covered scheduler retry semantics, manually dispatched learning components, status/schema boundaries, tracked environment/example files, private-key/credential-shaped patterns, and stale design/runbook claims.

It produced two material leads:

1. APScheduler’s retry loop appears to repaint `failed_retryable` rows as queued without calling the RQ enqueue path. Deployment topology determines whether this is a defect; it is F-A4-2 and has a concrete runtime falsifier.
2. `strategy_autotune` persists a config that production only logs. A secondary ordering defect also exists inside that currently inert component: mixed paper/live metrics can return “no mutation” before the live-only paper guard, allowing strong simulation rows to mask weak live performance. Because the component is not a scanner consumer, that secondary issue is not promoted separately.

The targeted secret sweep found **no new credential instance** beyond the historical `.env.example` material explicitly excluded by the brief. No value was inspected into or reproduced in this report. The absence is limited to tracked current repository content and the searched credential/private-key patterns; it is not a claim about git history or runtime secret stores.

---

# Exclusion-integrity results

| Exclusion | Result | Cold-code adjudication |
|---|---|---|
| E1 — calibration kill-switch | **Pass** | Apply path and fail-loud guard remain; 32/32 production proof is accepted. I3 ordering remains separate and owned. |
| E2 — gate qty scaling | **Partial / narrow pass** | The designated final stage gate implements Option A and real `shadow_only` routing. End-to-end closure wording is too broad because the upstream canonical ranker still repeats a known qty-unit defect; that residue was already in the prior report/multi-basis backlog and is not re-promoted. |
| E3 — streak-breaker edge trigger | **Pass** | No contradiction found; quiet unchanged windows remain expected. |
| E4 — close-fill-gap sign | **Pass** | Corrected basis remains in code; no contrary formula path found. |
| E5 — OBP null coercion | **Pass** | Null-tolerant/fail-closed path remains; no reopened universe inversion found. |
| E6 — force-close taxonomy + receipts + F8 | **Partial fail, promoted** | Taxonomy/receipts match. The generic F8 implication is false: most explicit handler failures can still persist as succeeded. I1 PR1 merged during this audit but is a separate close-state invariant. |
| E7 — viability bias wired | **Fail, promoted** | Active Policy-Lab cohort dispatch bypasses the only biased method; the claimed executor-path test inspects the bypassed method. |
| E8 — nightly audit dead-man | **Pass** | Wake/ping closure was not contradicted. F-A4-1 concerns application job outcomes, not the external nightly report ping. |
| E9 — one-beta tripwire | **Pass narrowly** | Alarm semantics match. The actual book control remains absent; more importantly, I6’s supplied “merged” status is false on current `main`. |
| E10 — PoP clamp log | **Pass** | Clamp/log path at calibration apply remains; dormancy at ×0.5 is consistent. |
| E11 — walk-forward field contract | **Pass** | Real field names, zero-row guard and no fabricated 0.5 probability remain on current code basis. |

### In-flight boundary status

- **I1:** PR1 (`e45290f`) merged at 20:21Z while this audit was running; the commit states PR2 targeted lookup/reconciliation remains. Per brief, the shipped design was not certified here. New GTC-scope and runner findings are independent.
- **I2:** no I2 merge was visible on final `main`; none of its six owned findings was re-derived.
- **I3/I4/I5/I7:** boundaries respected; no alternative design or stop/gate loosening proposed.
- **I6:** supplied “merged package” state disagrees with current code, schema and backlog. The disagreement is reported; the owned design is not replaced.

---

# Ranked top three operator decisions

## 1. Normalize handler outcomes at the runner boundary; explicit failure must never be green

**What.** Introduce one typed result contract and translate `ok:false`, error/failed statuses and positive failure/error counts into a non-success `job_runs` state with consistent retry/dead-letter/health behavior. Inventory handlers before rollout so retry side effects are understood.

**Evidence.** F-A4-1: `runner.py:124-140` recognizes only top-level `users_failed`; the q15 risk monitor returns `ok:false`; health recognizes only succeeded rows with `counts.errors`. This is a deterministic live-capital false-green path. The packet proves only one narrow producer shape, not the generic contract.

**Value.** Highest. Restores truth to every scheduled control and directly protects the q15 exit/risk monitor.

**Effort.** Approximately 1–2 single-developer evenings for the contract, handler inventory, migration-safe status mapping and focused tests/observe telemetry.

**Implementation risk.** Low-to-medium. It changes orchestration/retry behavior across many jobs and may reveal a backlog of hidden failures; stage with counts before enabling automatic retry where idempotency is not proven.

**Doctrine check.** No trading control is loosened. This is a fail-loud truth correction justified by a proven code error, not by outcome sting.

**What falsifies it.** A deployed wrapper absent from current GitHub that already normalizes every failure-shaped return before persistence. Zero historical false-green rows reduces urgency but does not falsify the code defect.

## 2. Enforce one shared GTC pilot-scope predicate and inventory all resting exits

**What.** Apply the same position-allowlist predicate at the common placement boundary used by both the scheduled sweep and immediate post-fill hook. Reconcile every intentional resting exit with the broker before relying on the pilot.

**Evidence.** F-A2-1: the sweep checks the allowlist, the post-fill hook does not; the test covers only the sweep. The packet proves resting GTC use on live positions.

**Value.** Very high. Prevents broker-side close orders outside explicit operator scope and reduces exposure to lifecycle behavior not yet approved for those positions.

**Effort.** Less than one developer evening plus a read-only broker/DB inventory.

**Implementation risk.** Low. It narrows admission. The only operational risk is discovering that existing nonallowed GTCs need operator disposition; this report authorizes no cancellation.

**Doctrine check.** Tightens a pilot boundary. `CLAUDE.md` explicitly forbids widening allowlists without proof. No stop/target threshold changes.

**What falsifies it.** Historical exercise is falsified if the flag was always off for nonallowed fills or the list was intentionally empty. The split-scope implementation remains falsified only when both entry points share the predicate.

## 3. Enforce one-close/one-outcome conservation with causal exit fields

**What.** Every closed live position must yield exactly one `trade_closed` outcome or an explicit quarantined exception. Carry the position-level suggestion fallback, real close reason, entry DTE and expiry; count/alert missing close orders.

**Evidence.** F-A3-1: missing close orders silently continue and do not increment returned errors; suggestion fallback is dropped; the canonical view inner-joins the lost link; exit reasons are generic/blank. Packet evidence: NFLX 06-08 is one of nine real closes missing from learning (11.1% all-time).

**Value.** High. At roughly one close per week, it prevents weeks of evidence loss and makes the signal-versus-exit diagnosis testable.

**Effort.** Approximately 1–2 developer evenings including conservation query, quarantine path and targeted tests.

**Implementation risk.** Low. Learning-write/observability path only if no auto-promotion behavior is added. Do not backfill guessed reasons.

**Doctrine check.** No trading control is loosened; it enforces H9/no-fabrication and broker-truth provenance.

**What falsifies it.** Exact one-to-one post-epoch coverage and a separate writer preserving causal reasons would falsify current impact. The present code paths still require correction for future manual/reconciled/assignment shapes.

### Near-miss fourth

**Revalidate and dispatch-test the viability bias (E7).** It is a genuine exclusion-integrity failure and likely under one evening, but current economic value is muted by the 0/5 calibrated viable evidence. Do not wire raw-era tiers blindly. It becomes top-three immediately after any structure clears the calibrated floor.

---

# Packet/code and state disagreements

1. **Running/main SHA moved during the audit.** The prompt expected `168a752` and later I1/I2 merges. Final `main` is docs-only `3d7e4ee` over runtime-relevant `e45290f`; only I1 PR1 is visible. I2 and I1 PR2 were not on final HEAD.
2. **I6 merge status is false on current repository truth.** The brief says merged; backlog, allocator readers and schema say open/unbuilt.
3. **E7 closure is false on the active executor.** The bias exists and its test is green, but Policy-Lab cohort dispatch bypasses both.
4. **E6/F8 closure is overgeneralized.** The packet’s exact 07-08 `counts.errors=6` detection is true. The generic runner/health contract still accepts other explicit fatal results as green.
5. **GTC status documentation is stale.** `docs/specs/resting_tp_orders.md` says never enabled live; `CLAUDE.md` and packet evidence show live use from 06-13 and a pre-cancel on 07-07.
6. **The packet’s deployed-flag list is insufficient for GTC and effective-config adjudication.** It omits GTC pilot flags, the default-off orchestrator and many import-pinned decision controls. This is an evidence gap, not proof of a deployed value.
7. **“Best-certified exit stack” is not contradicted by missing-expiry code.** The packet certifies observed closes; `999` DTE is an unexercised residual risk unless the runtime query finds affected rows.
8. **Capital-adequacy language and allocator behavior describe different policies.** The $7.5–8k note is a 5%/20% coherence tier; active small-tier code permits 36%/85%. Neither changes per-contract profitability.
9. **Raw-era viable labels are stale under ×0.5.** A static `SPY='CLEARS'` label cannot establish current viability; packet/current arithmetic says approximately zero.
10. **Runbook schedule text is stale.** Code uses 08:35/14:45 CT; `docs/daily_workflow.md` states 08:15/15:00 and implies recovery even when orchestrator defaults green-disabled.
11. **Packet outcome truth is richer than learning truth.** Broker-real close mechanisms are preserved in the packet but collapsed to `paper_trade_close` or blank in ingest.

---

# Honest overall verdict and first change

The data do **not** support calling this a signal problem: eight post-epoch closes and five incomplete thesis horizons are insufficient, even if the provisional directional figure is 78%. The current binding profitability problem is **execution/structure economics**—calibrated one-lot EV versus executable friction and the $15 evidence floor—with **capital as a risk-granularity constraint, not a cure for negative per-contract economics**. Exit behavior may be a loss mechanism, but I4 owns the missing measurement needed to prove that; this audit does not loosen or retune stops. Operationally, custody and learning truth are also incomplete. The single first change I would make is the **typed runner outcome invariant**: a fatal protective job must never be recorded green. It is the highest-value, doctrine-clean correction and restores the evidence surface on which every later profitability decision depends.

**Implementation status:** nothing in this report was built or changed. Every recommendation is an operator decision.
