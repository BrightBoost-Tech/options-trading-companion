Warning: truncated output (original token count: 88943)
Total output lines: 4891

# Audit Ledger — findings already found

Every finding listed here is EXCLUDED from future audit runs. Re-finding a
ledger item is a wasted slot. Runs append new findings as `status:reported`;
the human flips them to `status:shipped` (with PR#) or `status:rejected`.

## 2026-07-16 — OVERNIGHT BACKLOG LANES · status:merged-foundation/draft

Grounded GitHub main at `0e3e54f0821f2114b3d1b10074f15686f5e555c5`.

- #1224 merged the post-merge standing and fleet doctrine.
- #1225 merged the **dormant** `small_tier_v1` schema/pure contract. This is
  not activation: migration unapplied; zero fleet/account/portfolio/policy
  rows provisioned; no runtime caller; legacy-terminal boundary unproven.
- #1226 merged test-only rolling calibration-floor stability.
- #1227 merged read-only calibration-report fetch truth; multiplier behavior
  is unchanged.
- #1228 is DRAFT: persisted decision-tape aggregate hash/count reader plus a
  signed operator-triggered job path. It reads zero live data and is
  deliberately unscheduled. Full deterministic replay remains open.
- #1229 is DRAFT: broker-clock holiday/half-day truth is threaded through
  ops-health `data_stale` and RTH job-liveness gates. Detection-only; no
  cadence/control change.

Neither draft is shipped, runtime-proven, or authorized for merge by this
documentation record. No migration, fleet activation, policy registration,
schedule, flag, threshold, stop, gate, broker write, or DB write occurred.

## 2026-07-16 — POST-MERGE RECONCILIATION · status:shipped-code/runtime-pending

Grounded repository truth through `main=b6496b60d46d137806a80577581d19a4b06eec8c`.
The following closures supersede stale `status:reported` and queue language
below; historical entries remain exclusion memory.

- #1203 shipped F-A9-5 truthful Policy-Lab reason serialization.
- #1204 shipped the canonical position/payoff model; #1214 wired exact
  defined-risk max loss into the risk envelope. Only that slice is closed.
- Current main's two midday live-position reads raise a typed unavailable-state
  error rather than returning a false-flat `[]`; handler job truth consumes the
  failure. Runtime exception injection is pending.
- #1215 shipped strict Policy-Lab capital reads and partial/failure propagation;
  it removed the nominal $100k code fallback. This does **not** make existing
  $100k shadow portfolio rows comparable to the ~$2k live book.
- #1216 shipped the model-version/deploy-version provenance split.
- Current main's decision writer resolves a full SHA from explicit input,
  `GIT_SHA`, or `RAILWAY_GIT_COMMIT_SHA`; the first natural production row
  remains the runtime falsifier.
- #1218 shipped leg × quantity × entry/exit commission in canonical ranking.
  Remaining scanner/gate/slippage/realized cost-basis work stays open.
- #1219 shipped honest funnel denominators; per-selected-item terminal
  disposition remains open.
- #1220 shipped regular-session-close-aware thesis expiry scoring. It changes
  evidence timing only, not trading exits.
- #1222 shipped the durable doctrine for those three contracts.
- #1223 shipped the restored legacy #775 PoP suite; tests only.

### Operator authorization — prospective small_tier_v1 fleet

The operator authorized a prospective fleet of exactly 50 isolated virtual
accounts, each with $2,000 initial net liquidation and $2,000 cash. The
$100,000 sum is administrative only and can never enter sizing, allocation, or
cross-account loss recovery. Only uniquely pre-registered policy slots may
activate; all other slots remain inactive. Existing $100k portfolios and their
history remain `legacy_100k` and are never rewritten. Activation requires all
legacy positions and working orders to be terminal plus one explicit
timezone-aware effective timestamp. All parallel evaluations share the source
suggestion UUID as immutable `decision_event_id`; evidence n is distinct
decision events, never account-row count. No live control, threshold, stop,
gate, strategy, universe, or cadence change was authorized.

Implementation status (historical at this entry; superseded by the overnight
entry above):

- #1225 **DRAFT / CI GREEN** — dormant schema and side-effect-free validation
  only. Migration unapplied; no fleet/account/portfolio/cohort rows created; no
  runtime caller or activation path.
- #1226 **DRAFT / CI GREEN** — test-only rolling calibration-floor fixture.
- #1227 **DRAFT** — report-only typed fetch-failure semantics; live multiplier
  behavior untouched.
- E19-2B stays gated until the fleet is actually activated at a proven clean
  legacy boundary. Authorization alone is not runtime parity.

### Practical effect on the next trading session

- Exact payoff max loss can change risk-envelope arithmetic and can fail a
  malformed/unbounded defined-risk candidate closed.
- Leg-aware commissions can lower the rank/RAeV of four-leg structures relative
  to two-leg structures and can reject a marginal candidate that previously
  cleared on the universal $1.30 estimate. No threshold changed.
- Position-state read failures cannot masquerade as a flat live book.
- Provenance and funnel changes make the evidence attributable; they do not
  select or submit a trade by themselves.
- Expiry-day thesis scoring occurs post-close and cannot change an intraday
  entry or exit.

**Runtime boundary:** deployment/H8, first natural max-loss decision, first
natural leg-aware cost decision, first resolved decision-tape SHA, and next
post-close thesis run are NOT_PROVEN_RUNTIME in this GitHub-only lane. No
broker, DB, Railway, environment, flag, threshold, stop, or schedule write was
performed.

### Exclusion memory / do not reopen as fresh findings

Do not refile the shipped slices above. Reopen only on a named falsifier or on
the explicitly listed remainder: shadow-capital parity, terminal-distribution
source, cost phase 2, canonical-position greeks/stress/reconciliation, funnel
terminal dispositions, or durable cross-job identity.


## 2026-07-15 — ADJUDICATED: external full audit v1.5 · status:reported

Executed the v1.5 BRIEF (`docs/review/external-full-audit-v1.5-current.md`) — it was BRIEF_ONLY (no completed
v1.5 results existed). Full completed report: **`docs/review/external-full-audit-v1.5-results-2026-07-15.md`**.
Audited production code at the immutable baseline **`bef2cdd`** (main moved 623044d→d18dd52 during the run =
**docs-only** #1207+#1208, zero code). E1–E20 + W1–W5 + A1–A10 (Pass 1/2/3) + instrument-integrity + free look
all completed; runtime adjudicated read-only. **Audit-maturity = `INFERRED design-maturity score 60/100`
(arithmetic-reproducible reviewer-weighted scorecard in results §12c: weights sum 100 and earned points sum 60;
the judgment-to-points method is not empirically calibrated; capped below the 85 maturity-ladder rung by the open
live-entry fail-open, incoherent EV/cost bases, missing replay reader, incomplete observe-window durability, and
6 unrun runtime checks); NOT a verified profitability/reliability/efficiency measurement, and NOT the earlier
unsupported 87/100 (the arithmetic independently yields 60).**

**RETAINED findings (exclusion memory — do not re-derive; build queue in the backlog v1.5 section):**
- **F-MIDDAY-POSITION-READ-FAILOPEN — CONFIRMED, 2 sites, live-entry safety (HIGH).** `except → return []`:
  Site A `workflow_orchestrator.py:_fetch_positions:2240-2270` (bare `print`, defeats `position_scope`'s
  loud-by-contract raise → micro-tier gate bypass); Site B `paper_autopilot_service.py:_get_open_positions_for_risk_check:1328-1343`
  (alerts, but envelopes pass green-on-vacuum). Un-hardened siblings of the 3 reads #1195 fixed. VERIFIED-CODE.
  Site A only source-string tested. **Causality NOT inevitable** — later same-symbol dedup + the *enabled*
  utilization gate can independently stop an entry; the dangerous case is a transient/selective/false-empty read
  followed by successful staging. P1-safety; **escalate to P0-before-next-entry if the utilization gate is
  OFF/unproven, any broker-live position is open, or multi-position/qty scaling is enabled.** Acceptance: route
  tests proving zero `submit_and_track` for BOTH a portfolio-ID and a position-query exception; a legitimate empty
  stays healthy.
- **A6-2 shadow-capital parity — HIGH, THE FIRST OPERATOR DECISION.** All three policy-lab portfolios `net_liq=$100,000`
  (incl. the live-eligible champion) vs the ~$2,067.86 live book (**~48× capital ratio**, basis=n/a dated account
  snapshots, unit=account-equity USD; ratio dimensionless). Raw-dollar
  P&L/capacity/feasibility/sizing/selected-samples are NOT live-tier comparable; promotion is *partially* normalized
  where enabled; **thesis hit/miss LABELS are NOT notional-scaled** (capital changes *which* trades enter the sample);
  `live_eligible`=routing ≠ broker execution. The `or 100000` literal is INERT (stored net_liq IS $100k) — removing
  it is a SEPARATE fail-closed code item, NOT the fix. **Operator decision: preserve the $100k epoch as non-live-tier
  evidence; at a clean boundary (no open shadow positions/orders) launch a versioned live-tier observe-only cohort on
  one shared broker-grounded capital snapshot (persist capital_basis/source/as-of/epoch); freeze cross-epoch promotion
  until a fresh min sample; NEVER rewrite historical rows as if at $2k.** VERIFIED-CODE + ATTESTED-RUNTIME. Strengthens
  F-SHADOW-CAPITAL-PARITY.
- **A6-3 condor-EV mis-rank — HIGH, live.** Three incoherent per-structure-contract dollar-EV constructions
  (credit≡$0 raw / debit breakeven-delta raw / condor delta-tail probability plus fixed-severity raw heuristic)
  all write `suggestion["ev"]`, jointly sorted by one structure-agnostic ranker; cross-structure rank flips on a
  severity constant before any $-gate. EXTENDS-E12/⑤.
- **A7-1 Phase-3 live-close accrual STALLED — HIGH.** 8 POST-EPOCH live closes (9 all-time incl. the pre-epoch
  NFLX 06-08), last 2026-07-08, 0 in the 7 days to pin; the ~10–15-fill gate is entry-rate-bound
  (INDETERMINATE/PAUSED), not close-instrumentation-bound. (Denominators kept separate — see results §1a.)
- **MED:** A2-1 watchdog writes terminal-cancelled on an unconfirmed cancel → double-entry (loud via ghost sweep;
  EXTENDS-P0-A) · A4-1/A9-2 git_sha reads `GIT_SHA` not `RAILWAY_GIT_COMMIT_SHA`, 12/12 'unknown' (= GIT-SHA-
  DECISION-PROVENANCE, one-liner) · A4-2 replay input/features hashes have a durable sink but ZERO reader (NEW) ·
  A7-2 exit-basis stamp lands on only 2/6 closes, all 3 recent fill-only (resting-GTC bypass; EXTENDS-Phase-3) ·
  A8-1 F-A9-5 confirmed: 56 `policy_decisions` rows carry a dollar-`ev` vs score-threshold lie; stored `ev` is
  the served value (historical basis unknown; calibrated at the attested successful-calibration runtime, with
  `ev_raw` separate), and `rank_at_decision` is an ordinal (EXTENDS-F-A9-5) · **A9-1 5th
  typed-column-lie F-A9-6:** `model_version` = `APP_VERSION` deploy string presented as model identity (NEW) ·
  **A9-3 F-A9-8:** champion/legacy fork path never populates `fork_errors` → champion clone/tag failure returns
  job-green (NEW) · A10-1 `is_us_market_hours` holiday-blind → Labor Day 2026-09-07 false HIGHs (EXTENDS-area10,
  hard trigger < 09-07) · E2 roundtrip qty-fix LIVE-INERT (default OFF) · observe-window durability: four of five
  windows (W1/W2/W3/W5) lack complete durable evidence — W1/W2 strictly logs-only, W3 partially durable (cap-breach
  alarm subset → risk_alerts), W4 semi-durable (count → job_runs.result), W5 absent/unstarted. Backlog interaction:
  **EXTENDS the existing split: F-WINDOW-1a EMISSION is CLOSED at `1386834`/#1198; F-WINDOW-1b COVERAGE+JOINABILITY remains OPEN; not a new finding identifier.**
- **LOW/NOTE:** A1-1 replay runner input-blocked (capital/OBP/book/ev_raw uncaptured; EXTENDS-E19-2B) · A5-2 no
  decision_runs origin column (**EXTENDS the existing `suggestions_open untraced extra runs` item and replay runner;
  not a new standalone filing**) · A3-1 stop-vs-thesis signal readable but unconsumed (NEW) ·
  A3-2 DTE bucket inert · A3-3 no apply-time sample re-check · A9-4 freshness alert lacks no-activity guard for
  learning/rejection/calibration tables · OPTIMIZER_V4/ALLOCATION_V4 dead-capability cluster (free look; EXTENDS
  FORECAST_V4 #1126 inventory) · A2-2 max_loss_total is quantity-coherent, while signed-leg/payoff/multiplier
  semantics remain a retained **EXTENDS-canonical-position-P1** gap.

**Register governance:** results §15 is the version of record for retained/conditional finding detail. Every retained
finding in this ledger/backlog matrix maps to one 12-field register block, or carries an explicit settled, rejected,
runtime-only, or dormant disposition. The current pin contains 22 unique register blocks.

**REJECTED (do NOT rediscover):**
- **Internal-fill close-price sign — NOT PROVEN as a defect.** `paper_exit_evaluator._select_internal_fill_price`
  is shadow-ONLY (P0-A guard makes it unreachable for a live close), stores the signed value consistent with the
  system-wide signed `avg_fill_price` convention (`paper_endpoints.py:1908`), and is not read for realized-P&L
  learning (`paper_learning_ingest` uses `realized_pl`). No positive-expecting consumer exists. Realized-P&L sign
  is owned by #1017/#1079.

**SETTLED / PASS (verified at bef2cdd; do not re-open):** E1,E3,E4,E5,E7,E9,E10,E11,E13,E14,E15,E16,E17,E18,E19,E20
PASS; A6-1, A8-2, A8-3 PASS; A4-3 (no other non-JSON type crosses supabase-py's JSON layer — negative result);
F-WINDOW-1 = inert identifier drift (prefix-disambiguated), not a new collision. E6 needs_manual_review is safe
(code = critical hold, tracked, not double-fired) — the "routed-success" framing was inverted, not the code.

## 2026-07-15 (Wed, post-close) — UNIVERSE-CENSUS ADJUDICATION (read-only; corrects the same-day 18:38Z status) · status:reported

STEP-0: host `20:59:06Z` ≈ DB `now()` `20:59:15Z` ≈ broker `16:59:17 ET` — agree; market CLOSED.
Deployed SHA `623044d` (docs-only over `bef2cdd`; the 07-15 falsifier code is `bef2cdd`-identical).
Read-only census of the 78-symbol production universe + a live Aug-21 chain snapshot (19:29–19:33Z).
Verified findings (exclusion memory — do not re-derive):

1. **78 active symbols; ALL 78 SELECTED every 2026-07-15 cycle** (`universe_selection_log`
   09:30Z/14:32Z/16:00Z: total_active=78, selected=78, dropped=0). Full breadth, no prune.
2. **job-result `universe_size=10` = scanner-EMITTED candidate count (6 IC + 4 debit), NOT ten
   symbols scanned** (`[APPLY_ORDER_SHADOW] n=10`, mislabeled).
3. **`symbols_processed=98` vs `selected=78` remains NOT_PROVEN** (20-symbol gap unreconciled).
4. **BKNG WAS scanned and RANKED** (#3; raw 42.1/47.4, calib 13.5/18.4); its actual **$20-wide
   long-call debit spread (C175/C195 Aug-21)** was first excluded at **SIZING** — 1-contract risk
   **$855/$885 > available budget $703/$469** → contracts=0 (both cycles). Sizing drops are
   stdout-only (no `suggestion_rejections` row) — why the 18:38Z pass mis-called it NOT_IN_RUN.
5. **BKNG ticker suitability is DISTINCT from structure suitability** — the symbol is
   universe-suitable (liquid, OI-rich puts); the $20-wide debit STRUCTURE failed the budget.
   **Do NOT record "BKNG was missed."**
6. **A hypothetical $5-wide BKNG put spread fits the capital budget ($412 max loss) — this does NOT
   prove positive EV or entry suitability.** Earnings (07-27) and true EV remain unresolved.
7. **$62.04 = q15 mark-based FORCE-CLOSE threshold on open-position UPL** (`risk_envelope.py:444`,
   `envelope="loss_per_symbol"`, iterates open positions' `unrealized_pl` and force-closes at
   `unrealized < -$62.04`). **NOT an entry max-loss gate** — no production entry code rejects
   `max_loss_total > $62.04` (distinct from the entry sizing param `max_risk_pct_per_trade`).
   Reclassified as "defined payoff exceeds the mark-stop threshold" → Phase-3 exit-basis question;
   no stop change recommended.
8. **The census `PoP×credit − (1−PoP)×max_loss` (PoP = 1−|Δ_short|) is a BINARY MAX-LOSS LOWER
   BOUND, not true spread EV** — it ignores the partial-payoff interval between strikes and uses
   short-delta as a probability proxy. "Net economics negative" is a conservative lower bound,
   NOT proven-negative.
9. **True credit-spread EV remains NOT_PROVEN pending queue-⑤** (the payoff-circular ≡$0 class; no
   independent terminal distribution integrated).
10. **Two-leg verticals have PROVEN lower fees (fee-only $2.60 vs $5.20) + fewer dead-leg failure
    modes than four-leg ICs** (BKNG IC unbuildable — C205/C215 dark wings, #1038 class); economic/EV
    superiority is **NOT PROVEN**.
11. **Configured $2.50/$5 widths are large for the ~$2,067.86 account; $1 widths scale risk better**
    (~$75 vs ~$440 max loss) **but may worsen fee/credit economics. No live width change is justified.**
12. **No ticker activation/deactivation is justified from one snapshot.** `option_liquidity_score` is
    40 days stale (67/78 stamped 2026-06-05; all 10 zero-scores in that batch) → zero ≠ current
    illiquidity; `get_option_contracts` OI is deep on the ETFs (SPY 34,265; TLT 65,864).

Preserved as a SEPARATE VERIFIED fact: the engine executed **0** today — QQQ IC roundtrip-rejected
(`net −$5.03`, #1101) and SOFI persisted `edge_below_minimum` — real and independent of the EV
mislabel. XSP: broker-listed/tradable (European, cash-settled) but the feed returns null OI/close →
data-sparse, and not in the scanner universe.

## 2026-07-14 (Tue ~19:2x CT, post-close) — POST-MERGE RECONCILIATION: ④ #1201 + ③ #1200 SHIPPED · QUEUE ①–④ CLOSED · ★ #1199 FALSIFIER PASSED · ★ NEW GIT-SHA-DECISION-PROVENANCE · status:shipped

STEP-0: host `2026-07-15T00:15:42Z` = DB `now()` `00:15:44Z` = broker `2026-07-14 20:15:44 ET`
— all three agree within ~2s; market CLOSED (next open 07-15 09:30 ET). **Premise note (not a
correction): the invoking header's "2026-07-14" is the ET/CT session date; the UTC date is already
07-15.** All UTC timestamps below are clock-grounded; "07-14 RTH" = the session that closed 20:00Z.
Docs-only lane, isolated worktree from `bef2cdd`; no merge/deploy/migration/flag/env/schedule/DB/
broker change. Deployed SHA `bef2cdd` PRESERVED for the 07-15 natural falsifiers.

**H8 PIN (both PRs, verified against Railway + `origin/main`, not local):** `origin/main` =
`bef2cdd60edbee8642fa043192fd982d4bfe4436`. Railway worker: `bef2cdd` **SUCCESS 2026-07-14
23:05:33Z = the ONLY non-REMOVED deployment**.

**④ F-A3-4 #1201 — squash `9670712`, merged 22:28:02Z. ⚠ DEPLOYED *WITHIN* `bef2cdd`, NOT AT ITS
OWN SHA.** Its own deployment (`9670712`, 23:28:05Z record 22:28:05Z) is **REMOVED** — superseded
37 minutes later by #1200's merge. `9670712` IS an ancestor of `bef2cdd` (verified
`git merge-base --is-ancestor`), so the code is live; but **no container ever ran `9670712` to a
falsifier.** Consequence for future audits: **verify #1201 behavior at `bef2cdd` BY CONTENT — a
deployment-SHA search for `9670712` returns REMOVED and reads as "never shipped" (H8 squash-merge
class).**
- D1 validator fetch parity: `prequential_validator.fetch_live_outcomes` now delegates to the ONE
  shared production cohort contract (`CalibrationService.fetch_eligible_outcomes` — rolling window ·
  `CORRUPTED_PNL_FLOOR` · `CALIBRATION_EV_EPOCH` · `CALIBRATION_TRAIN_LIVE_ONLY`). Fetch is
  `Optional`: `None` = failure → `status=error/fetch_failed`, `[]` = legit-empty →
  `insufficient_data`. Closes the []-sentinel disease (E8-3 class link) at this seam.
- D3 thesis headline: `population_by_execution_mode` + `population_by_routing_x_execution`;
  `pooled_all_modes` is the ONLY pooled label; `routing_mode='live_eligible'` is **never** called
  "live"; unknown mode isolated, never silently live.
- CENSUS PRESERVED (do not re-derive): `pre_epoch=0` → **NIL current numerical impact; structural
  only.** This does NOT weaken with time — it is a census as-of the v1.4 adjudication.

**③ E19-2A #1200 — squash `bef2cdd`, merged 23:05:30Z, deployed 23:05:33Z SUCCESS. LIVE.**

**★ NARROW CLAIM — PRESERVE VERBATIM; DO NOT LET IT WIDEN BY RETELLING.** #1200 delivers
**`raw_candidate_eligibility_only`** and nothing else. It is **NOT** selection · **NOT** execution ·
**NOT** fill simulation · **NOT** P&L evidence · **NOT** thesis evidence · **NOT** capacity/slot
accounting (`max_positions_open` / `max_suggestions_per_day`) · **NOT** joint normal-vs-prerejection
ranking · **NOT** entry-rate evidence. Every clone AND both verdict types carry the full contract:
`observation_scope='raw_candidate_eligibility_only'`, `decision_semantics=
'raw_candidate_eligibility'`, `selected_for_entry=false`, `capacity_evaluated=false`,
`joint_rank_evaluated=false`, `execution_state='not_executed'`, `execution_intent=
'internal_paper_only'`, `routing_intent='shadow_only'`. Accepted verdict
`reason_codes=['raw_candidate_eligible_observation']` with `rank_at_decision=NULL` **because no
ranking occurred**. `simulated_fill` is a sizing/TCM snapshot, **NOT an execution or fill**. Source
boundary: `edge_below_minimum` ONLY — `marketdata_quality_gate` (stale/dark/unpriceable) and all
scanner-level rejects are NEVER resurrected (H9: a dark leg stays unmarkable, §7 area8).
- **D② un-mute is STILL PARTIAL — `bef2cdd` does NOT stamp "the FULL experiment."** The 07-12
  backlog line ("`9a540ce` stamps the FLAG, ③'s SHA stamps the FULL experiment") is **superseded**:
  ③ shipped as **E19-2A (eligibility observation)**, not the full selector. The FULL experiment
  stamp now waits on **E19-2B** (below). Entry-rate evidence remains excluded until E19-2B.

**★ E19-2B (NEW, SPLIT OUT — the full counterfactual selector) — the separate dependency.**
#1200 explicitly scopes it out. E19-2B = joint normal-vs-prerejection ranking + capacity/slot
accounting + selection semantics, i.e. everything required before ANY entry-rate / conversion /
P&L claim can attach to the prerejection fork. **Blocks: the D② full un-mute.** Depends on
F-POLICY-CAPITAL-FALLBACK + F-SHADOW-CAPITAL-PARITY (a counterfactual selector that sizes against
a fabricated capital basis produces fabricated selections). → backlog P1.

**PENDING FALSIFIERS (the recoverable runbook — all three are 07-15 events; NOT verifiable tonight):**
- **#1200 · first post-merge midday cycle with a calibrated-rejected candidate.** EXPECT: a
  `shadow_prerejection_fork` clone + verdict carrying the per-contract unit contract, **identical
  `raev1` across cohort sizes**, `coverage_complete=true`, and a **byte-identical champion set**.
  **⚠ NO QUALIFYING CANDIDATE = INCONCLUSIVE — not PASS, not FAIL.** Base rate (DB, 5d):
  `edge_below_minimum` = 1 (07-14) · 2 (07-13) · 1 (07-10) · 0 (07-11/07-12 weekend) → **~1–2 per
  trading day; likely but NOT guaranteed on 07-15.** Do not record a quiet day as a PASS. Any
  champion-set deviation, or any infrastructure fault surfacing green = **REVERT**.
- **#1201 · `calibration_update`** — schedule 05:00 CT = **10:00Z**; last run 07-14 10:00:02Z ran on
  `f34d5cd` (**pre-#1201**). **First exercise = 07-15 10:00Z.** EXPECT: the shared
  `fetch_eligible_outcomes` contract yields the SAME eligible rows production calibration already
  used (pre_epoch=0 ⇒ no numerical move); a fetch failure must surface `error/fetch_failed`, never
  a green `insufficient_data`.
- **#1201 · `thesis_tracker`** — schedule **17:00 CT = 22:00Z, DAILY** (single run — NOT hourly;
  the "hourly arm" in prior entries is the watchdog's expectation, not the schedule); last run
  07-14 22:00:16Z ran on `f34d5cd` (**pre-#1201**, 12 min before the merge). **First exercise =
  07-15 22:00Z.** EXPECT: `population_by_execution_mode` present; `pooled_all_modes` the only
  pooled label; no `live_eligible`-as-"live"; a population-summary failure → PARTIAL with the
  thesis upserts preserved.

**★ #1199 (F-REPLAY-FK) FALSIFIER — PASSED. The 07-14 pending disposition #1 is RESOLVED
(verified tonight, DB).** The nightly (00:00 CT) could only predict this; the RTH day delivered it:
- `data_blobs` = **9 rows; FIRST BLOB EVER at 2026-07-14 13:00:08.800835Z** — exactly the predicted
  13:00Z `suggestions_close`. (All-time count was **0** at the nightly.)
- `decision_runs` clean split, no ambiguity: **5 runs `failed`/`blob_never_persisted`, ALL 07-13
  (13:00→17:29Z, the annotated-unrecoverable set)** vs **4 runs `ok`/`tape_integrity='complete'`,
  ALL 07-14** (13:00 close + 14:11/16:00/17:48 opens).
- **The tape is now COMPLETE.** F-REPLAY-FK: `status:shipped`, falsifier PASSED — **do not re-find,
  do not re-verify.**

**★ NEW — GIT-SHA-DECISION-PROVENANCE (MED, CONFIRMED-empirically, evidence-integrity).**
**The replay tape is now complete in CONTENT and silent on PROVENANCE: `decision_runs.git_sha` =
the literal string `'unknown'` on 9/9 rows, all-time** (`distinct_sha = 1`) — across runs spanning
**TWO distinct deployed SHAs**, cross-referenced against Railway deployment times: **`8d93621`
carried the five 07-13 runs** (13:00→17:29Z; deployed 07-13 04:21:36Z) and **`f34d5cd` carried the
four 07-14 runs** (13:00→17:48Z; deployed 07-13 20:08:47Z). Two different code SHAs, one identical
non-SHA stamp — sufficient to prove the stamp does not track the running code.
- **⚠ ERRATUM against my own first draft of this entry (caught + corrected PRE-MERGE; recorded
  because the mistake is the instructive part).** The draft put the span at **4** SHAs, listing
  `8d93621` → `1386834` → `f34d5cd` → `bef2cdd`. **FALSE.** That is the period's DEPLOYMENT LIST,
  not the set the runs actually sit under: `1386834` lived ~5 minutes with no decision cycle, and
  `bef2cdd` deployed 23:05Z — **after** the day's last cycle (17:48Z). **The number of SHAs a
  run-set spans is a JOIN against deployment WINDOWS, not a count of deployments in the period.**
  The corrected span (2) already carries the finding in full; the overclaim was refutable by one
  query — a stretch where the honest smaller number was strictly better. Pinned by
  `test_docs_consistency.test_git_sha_span_claim_is_two_not_four`.

MECHANISM: the decision path reads **only** `GIT_SHA`
(`suggestions_open.py:139`, `suggestions_close.py:128` — `os.getenv("GIT_SHA")`, no fallback) and
`lineage.get_code_sha` (`:264`) degrades `GIT_SHA` → `APP_VERSION` → `"unknown"`; the **healthcheck
already solves this** (`api.py:154-157` resolves `GIT_SHA` **or** `RAILWAY_GIT_COMMIT_SHA`, the
name Railway actually injects) — the decision path simply does not reuse it. **This is not
cosmetic: it defeats the stated experiment contract "③'s SHA stamps the FULL experiment"** — a
replay tape that cannot name the code that produced it cannot attribute a decision to a SHA, which
is the whole point of the tape. Also blocks any before/after A-B read across a recycle. FIX SHAPE:
the decision path consumes the healthcheck's existing resolution (env NAME-only observation; no
value read, no env change in this lane). Falsifier: a post-fix `decision_run` carries a real
12-char SHA that MATCHES the Railway deployment SHA of the container that produced it. → backlog
P2 (evidence-integrity; rides the replay/tape family). **Not a #1199 regression — #1199 delivered
content integrity and never claimed provenance.**

**★ NEW — F-SHADOW-CAPITAL-PARITY (HIGH, CONFIRMED-empirically, evidence-integrity).**
**All three policy-lab cohort portfolios carry `net_liq = 100000` — including `aggressive`, the LIVE
CHAMPION (`routing_mode='live_eligible'`) — while broker truth is `$2,067.86`** (verified tonight:
equity = cash = OBP = portfolio_value = 2067.86, positions `[]`, `last_equity` 2067.86,
balance_asof 2026-07-13). DB-verified: aggressive `net_liq 100000` / `cash_balance 106883.75` ·
neutral `100000` / `97400.82` · conservative `100000` / `100031.64`. **≈48× the deployable basis
(§5.1: deployable = live Alpaca `options_buying_power`, never a DB snapshot).**
- **⚠ THE SHARP EDGE — #1200's fail-closed normalizer does NOT close this.** `_normalize_capital`
  (`fork.py:435-442`) correctly removes the hardcoded `or 100000` **literal** and treats `net_liq`
  as authoritative — but **the column itself contains the fabrication.** Reading a fabricated value
  authoritatively is still fabrication (H9). Removing a default that names $100,000 while the
  source-of-truth column *is* $100,000 changes the code path, not the number.
- SCOPE, stated honestly: this is the **policy-lab evidence surface**, NOT live sizing — live
  entry capital comes from the broker OBP path (§5.1) and `RiskBudgetEngine`, which this does not
  touch. It is nonetheless the quantified root under §8's "shadow ledgers are partly fiction /
  shadows fill at 5–17× live size" and it makes **champion promotion basis-broken** (the promotion
  compares cohorts sized against $100k to a live account at $2,068). Interacts with — does not
  duplicate — #1124's promotion-time normalization (discount 0.31 measured).
- **BLOCKS E19-2B**: a counterfactual *selector* sized on $100k selects trades the live account
  could never fund. → backlog P1.
- Falsifier: cohort capital reads resolve to a broker-grounded basis (or the experiment declares its
  basis explicitly and promotion normalizes it), and a promotion comparison states its capital basis.

**★ NEW — F-POLICY-CAPITAL-FALLBACK (MED, CONFIRMED-by-cite, evidence-integrity) — filed by #1200,
WIDENED here: it is TWO sites, not one.** The `net_liq or cash_balance or 100000` fabrication
survives at:
- `policy_lab/fork.py:210` — the legacy normal-shadow-clone loop (**the one #1200's §9 DISCLOSURE
  names**; explicitly out of #1200's narrowed/frozen scope, annotated in-place at `:201`).
- **`policy_lab/evaluator.py:251` — a SECOND, UN-NAMED site** (`float(portfolio.get("net_liq") or
  portfolio.get("cash_balance") or 100000)`). Found this session by grep; **#1200's PR body names
  only the fork site.** Fixing only the disclosed site would leave the evaluator fabricating.
- `policy_lab/init_lab.py:12` `INITIAL_CAPITAL = 100_000.0` is the **seeding origin** of
  F-SHADOW-CAPITAL-PARITY's DB values — the two findings share a root; fix them as a family, not
  ad hoc. → backlog P2 (rides F-SHADOW-CAPITAL-PARITY).

**★ prequential_validator OPERATIONALIZATION (NEW, structural — the falsifier that never runs).**
**`prequential_validator` has ZERO production callers** (verified repo-wide this session): no
scheduler entry (`scheduler.py` has none), no job handler, no import outside its own module — the
sole non-test reference is a **docstring mention** at `calibration_service.py:317`. It is reachable
only via its own `main()` / `if __name__ == "__main__"` (`:242`, `:281`). **So #1201 correctly
repaired a validator that nothing invokes** — the fix is real and the []-green disease is closed at
the seam, but the seam is not on any live route. **This is the #1126/9a2cef1 costume's cousin, with
the honest difference that #1201 never claimed a caller** — recording it so no future audit reads
"prequential parity shipped" as "prequential validation runs."
- **SCHEDULING IS AN OPERATOR DECISION — explicitly NOT taken here and NOT recommended by default.**
  The validator is the designated **falsifier** for the calibration multiplier (F-A1-3 / E17
  family); wiring it to a schedule is a live-adjacent decision (queue routing, cadence, what a
  failing prequential verdict should *do*), and doctrine reserves that for the operator. Options,
  unranked: (a) leave manual/on-demand — status quo, zero risk, the falsifier stays unexercised;
  (b) schedule read-only on `background` and alert on divergence; (c) gate the multiplier on it —
  behavioral, needs its own PR + flag. → backlog P2 (RESEARCH-adjacent; owner-gated).

**QUEUE ①–④ — ALL FOUR CLOSED (the v1.4 post-close queue is fully cleared):**
| # | Item | PR | Squash SHA | Merged (UTC) | Deploy status |
|---|---|---|---|---|---|
| ① | E8-3 typed sentinel | #1195 | `af1c5be` | 2026-07-13 03:42 | superseded (REMOVED) |
| ② | E16-3 manifests + F-REPLAY-FK | #1199 | `f34d5cd` | 2026-07-13 20:08 | superseded (REMOVED) · **falsifier PASSED 07-14** |
| ③ | E19-2 → shipped as **E19-2A** | #1200 | `bef2cdd` | 2026-07-14 23:05 | **LIVE** · falsifier 07-15 |
| ④ | F-A3-4 prequential parity | #1201 | `9670712` | 2026-07-14 22:28 | **deployed within `bef2cdd`** · falsifier 07-15 |

**★ F-WINDOW-1 — IDENTIFIER COLLISION RESOLVED (two different defects were riding one name).**
The name was reused across two genuinely distinct defects, and the 07-13/07-14 entries closed one
while the backlog still carried the other — a silent-retirement hazard. **Split, both preserved:**
- **F-WINDOW-1a — heartbeat EMISSION.** "The beats exist (#1187 `log_shadow_heartbeat`) but ride a
  dead channel (root logger unconfigured → every `logger.info` destroyed in-process)." **CLOSED at
  `1386834` (#1198)** — the deliverable was the handler, not new heartbeats; proven post-close by
  an `[ALPACA_SYNC]` INFO line reaching Railway. **This — and ONLY this — is what the 07-14 nightly
  entry's "F-WINDOW-1 CLOSED" means.**
- **F-WINDOW-1b — heartbeat COVERAGE + JOINABILITY (OPEN, P2 tail).** The v1.4 original
  (CONFIRMED-by-cite): only W4 (APPLY_ORDER) + a generic post-portfolio EXECUTOR_SHADOW; **W1 no
  gate-site beat · W2 no per-consumer zero-eval beat · W3 pre-portfolio miss + no candidate/
  reservation-order identity · no shared cycle/decision ID → W5 unjoinable.** A live channel does
  not create a shared correlation ID. **The ARM decisions wait on JOINABLE evidence — 1a's closure
  does NOT release them.** W-clocks do NOT reset for observability-only additions (unchanged).
- **DOCTRINE PRESERVED (unchanged, restated so the split cannot lose it): the arm-evidence clock
  restarted at `1386834` — the THIRD restart** (`d5edd50`'s evidence never existed; the channel was
  dead; `[RISK_BASIS_SHADOW]` has NEVER emitted).

**F-A9-5 — DRAFT, NOT SHIPPED (Lane A is OPEN as of this session).** `_log_cohort_decisions`
compares dollar `ev` to a 0-100 score threshold (`fork.py:466-477`) while the real filter compares
`sizing_metadata.score` (`:233-236`) → `ev_below_min` is an evidentiary lie (routing byte-correct).
Lane A = PR #1203 `fix/f-a9-5-routing-log-truth` is **DRAFT, 1 commit at `28e4990`** — its
#1200-live-observation block is cleared but it is **not shipped** (BEHIND current main; needs rebase +
adversarial/CI review). Status stays `status:reported` / DRAFT until a squash SHA + H8 pin exist.
Do not mark shipped on branch existence.

**CREDENTIAL HYGIENE (standing doctrine, re-affirmed — no incident recorded).** Diff env key
**NAMES** only; never `list_variables`/`printenv`/`env`; never emit values (origin: the 06-18
transcript incident). **Nothing in this lane read an env value**; the GIT-SHA finding above is a
NAME-only observation. Pinned by `test_docs_consistency.py` — the audit docs are committed and
world-readable, so a credential-**shaped** string in `ledger.md` / `backlog.md` / any dated report
now fails CI. Credential **classes and names only, never values, fragments, or fingerprints.**
*(Operator decision this session: no credential-incident entry is recorded here — the ledger
carries no security disposition either way. F-FREE-1 (07-04) stands unchanged on its own terms:
LOCAL-ONLY-FAKE, no live rotation warranted.)*

**PRESERVED, NOT RE-LITIGATED (carried forward untouched — do not reopen):** calibration ×0.5 floor
SETTLED (floor-HOLD until ~15–20 live closes; F-A1-3 scope = persisted-ev + roundtrip gate ONLY,
selection/sizing RAW) · pool **8/8 post-epoch (1W/7L)** · close-fill-gap **3/10–15** · universe
**78** · breaker armed-quiet (`entries_paused=false`, fingerprint [055ead84, 7dd459f8, bd895160],
trip 07-08 21:20Z; edge-trigger; recovery OPERATOR-ONLY) · SOFI sentinel SETTLED trigger · 1-of-N
economics SETTLED · greeks envelope DOUBLE-dormant · EXCLUDED-EVIDENCE day 07-06 · retirement
counters **A1=6 · A2=4 · A3=6 · A4=2 · A5=4 · A6=6 · A8=5 · A9=2 · A10=6** with the nightly's
honest read (quiet-regime artifact, NOT territory coverage — **recommend KEEP all four**;
owner-gated, never unattended) · A10 → A11 Security-lens rotation queued · the autopilot costume
(A5/A9, 4× on 07-13) still riding the slipping 3-in-1 observability PR.

## 2026-07-14 (Tue 00:00 CT) — NIGHTLY AUDIT (v5.5, scheduled) — report audit/reports/2026-07-14.md · NO NEW FINDING

STEP-0: DB `now()` 05:00:35Z = Tue 00:00:35 CT (dow=Tue) = broker 01:00:35 ET, agree to the second,
market CLOSED. Tuesday ⇒ NIGHTLY. **Run NOT broker-blind** (interactive; Alpaca MCP surfaced — 3
broker calls). H8 pin: run-START = run-END SHA = **`f34d5cd`** (#1199), sole non-REMOVED Railway
deployment (SUCCESS 07-13 20:08:47Z) = local HEAD; no overnight mover.

**No new finding; no ALERT file (zero new criticals).** Window audited = the full Monday 07-13 RTH
day + the two post-close merges — the richest moved-signal window in a week, but both merges' first
natural tests are in 07-14 RTH, not the window just closed.

VERIFICATIONS (all ✅ / expected):
- **Monday 07-13 = zero-entry day**: 6 suggestions, 0 orders, 0 opens, 0 closes, 665 rejection rows
  (~2× over-count). Pool 8/8 (1W/7L) unchanged; close-fill-gap 3/10–15 unchanged.
- **Broker flat, unchanged to the cent**: positions `[]`; equity=cash=OBP=portfolio_value=**$2,067.86**;
  last_equity $2,067.86; balance_asof 2026-07-10. A2 one-beta condition holds (0 live positions).
- **F-REPLAY-FK still-latent-through-07-13 (KNOWN, verified, not re-found)**: `data_blobs`=0 all-time;
  `decision_runs`=5 all `failed` (latest 17:29Z) = the exact 5 unrecoverable runs the 07-13 morning
  diagnosis named. #1199 merged 20:08Z after the last decision cycle → **first exercise = 07-14
  13:00Z** (expect first-ever `data_blobs>0` + `tape_integrity='complete'`). VERIFY IF fired.
- **Calibration ×0.5 confirmed in production**: every aggressive suggestion `ev = ev_raw × 0.5000`
  exactly (F-A1-3 scope: persisted-ev + roundtrip gate ONLY; selection/sizing RAW). Out of raw mode,
  SETTLED (floor-HOLD until ~15–20 live closes) — do NOT re-flag.
- **Breaker armed-quiet**: `entries_paused=false`, reason NULL, unchanged since 07-09 11:53Z;
  `streak_breaker_state.last_tripped_fingerprint` = [055ead84, 7dd459f8, bd895160], tripped_at
  07-08 21:20Z intact. 0 closes ⇒ trailing window unchanged ⇒ edge-trigger correctly did NOT re-pause.
  Zero flag-only-if conditions met.
- **SOFI sentinel QUIET (A8)**: 2 SOFI debit spreads blocked at `edge_below_minimum` (upstream of the
  roundtrip gate — did NOT clear it). The SETTLED trigger did not fire.
- **Full learning chain + all 22 job types succeeded** Monday; no failures. H11 critical = only
  `ops_job_never_run` ×9 (latest 21:07Z) = the known thesis_tracker hourly arm, self-resolved at its
  22:00Z first run (thesis_tracker succeeded 22:00:02Z; none since).

FREE LOOK (1 SQL): traced the sole unexplained warning class
`paper_autopilot_cohort_per_suggestion_failed` ×4 (07-13) → metadata
`distinct_error_classes:["EntryRoundtripCostExceedsEV"]`, ticker QQQ. **Resolved to the KNOWN 07-10
A5/A9 "autopilot costume"**: `EntryRoundtripCostExceedsEV` (the #1101 gate) lacks a dedicated
`except` clause in `_execute_per_cohort`, so a designed NO falls to the catch-all `except Exception`
(paper_autopilot_service.py:1182-1191) and is dressed as "executions failed / did not execute as
expected" — unlike the sibling enforced blocks (SymbolCooldownActive :1131, EntryUtilizationBlocked
:1138) that each `continue` without polluting the failure aggregation. Also emits a
`logger.error("policy_lab_execute_error…")` line per fire. NOT a new finding — fix already queued in
the slipping 3-in-1 observability PR (now ~5th consecutive build-day slip). Recurred 4× on the first
fully-visible RTH day, sharpening the A5 slip case.

RETIREMENT COUNTERS: A1=6, A2=4, A3=6, A4=2, A5=4, A6=6, A8=5, A9=2, A10=6. **A1/A3/A6/A10 hit 6 =
proposal territory (owner-gated).** Honest read: quiet-regime artifact (weekend + zero-entry + flat
book), NOT territory coverage — a proposal would fail its own "covered elsewhere" test; A10's path is
A11's Security-lens rotation. Recommend KEEP all four; owner glance only.

PROMPT-STATE DRIFT (for v5.5→v5.6, movers named not alarms): running-SHA STATE still pins
`655c9aa`/#1143 → HEAD now `f34d5cd`/#1199 · "first calibrated production scan pends 07-10 16:00Z"
line stale (calibration ×0.5 in prod since 07-10, re-confirmed tonight).


## 2026-07-13 (Mon ~15:1x CT, post-close) — PR-0 #1198 + PR-② #1199 SHIPPED — H8 PASS ×2 · status:shipped

STEP-0: host 20:04:31Z = DB 20:04:33Z = broker 16:04 ET, market CLOSED. RTH
premise in the queue header corrected at 18:02Z (clocks won; both PRs prepared
on branches during RTH, merged only post-close). Single controller confirmed;
the obsolete 20:01Z sleep loop was already dead (600s cap), replaced by a
Monitor that fired at 20:01Z.

**PR-0 #1198 (logging) — squash `1386834`, merged 20:03:07Z. H8 PASS.**
All 3 services SUCCESS at the SHA (20:03:09-10Z). Canaries: BE 20:04:29Z
(container start) · worker 20:05:01Z (first post-recycle job) — and the fix
visibly WORKING: the same job's `[ALPACA_SYNC]` app INFO line reached Railway
(impossible pre-fix). No tracebacks.
- ⭐ **THE ARM-EVIDENCE CLOCK RESTARTS AT `1386834`** (third restart —
  d5edd50's evidence never existed; the channel was dead).
- **The #1187 heartbeats are LIVE at this SHA with zero code change.
  F-WINDOW-1 CLOSED** (the deliverable was the handler).
- Residual (minor, tunable): `rq.worker` sets its own child-logger level, so
  the parent-`rq` WARNING pin doesn't stop propagation → RQ job lines print
  twice (rq handler + root). Cosmetic; pin `rq.worker` if it grates.

**Migration `decision_runs_tape_integrity` — applied 20:03:33Z, read-back
PASS** (tracked as latest; backfill = exactly 5 rows `blob_never_persisted`,
0 NULL, 5 total runs). ORDERING DEVIATION (recorded): applied while PR-0's
deploy was still BUILDING, i.e. before PR-0 H8 completed — the load-bearing
constraint (migration BEFORE #1199 merge) was preserved; the column is
annotation-only and nothing at `1386834` reads it.

**PR-② #1199 (tape integrity) — squash `f34d5cd`, merged 20:08:47Z (after a
BEHIND branch-update + fresh CI green; head `33cc5aa` content unchanged,
update was main-merge only). H8 PASS.** All 3 services SUCCESS at the SHA
(worker+bg 20:08:46-47Z records; BE 20:08:46Z → SUCCESS). Content verified
by grep AT the squash SHA: payload hex-encode + `_decode_bytea` (blob_store) ·
`unpersisted_of` + capture_partial ×4 (decision_context) ·
`_capture_decision_manifest` ×10 sites (7 midday + 2 morning + def) · both
handler surfacings. Canaries on the NEW containers: worker 20:10:01Z · BE
20:09:59Z; worker Error-line sweep clean. worker-background canary
PENDING-BY-DESIGN (first job = the 21:00Z learning chain; its 20:03Z container
start was clean).
- **THE TAPE-COMPLETE BOUNDARY STAMPS AT `f34d5cd`** — first natural test:
  tomorrow 13:00Z suggestions_close (expect decision_run status ok,
  tape_integrity='complete', data_blobs > 0 for the first time ever).
- CI note (E8-3-adjacent lesson, small): the route-driving tests initially
  used `asyncio.get_event_loop()` — green locally on a leftover loop, red in
  CI (`no current event loop`); fixed to `asyncio.run` (fresh loop). The
  local pass was environment luck, not correctness.

**Post-close health (20:1xZ):** broker positions [] = DB open 0 · broker open
orders [] = DB working 0 · H11 since 18:00Z = ONLY `ops_job_never_run`
(thesis_tracker, hourly, expected until its 22:00Z first run — P9 grades it)
· stuck-`running` ×4 = exactly the known reaper fossils (06-11 order_sync ·
05-18 promotion_check · 01-14/01-09 validation_eval), NO new orphans from
tonight's two recycles · extra-runs CLASSIFIED: the 14:05/15:02/17:29Z
suggestions_open extras carry an EXPLICIT user_id payload (scheduler runs
carry user_id null) each followed ~90-120s by a paper_auto_execute with a
`timestamp` payload — an API-triggered per-user chain, NOT scheduler
duplicates; provenance (which endpoint/caller) still UNTRACED — the existing
backlog line now has its discriminator.

**③ E19-2 + ④ F-A3-4 HELD to tomorrow post-close (zero cost, sanctioned)** —
the RTH correction compressed the evening; E19-2 is design-care/MED-risk.

## 2026-07-13 (Mon ~13:0x CT, RTH read-only) — ② PRE-BUILD DIAGNOSIS: F-REPLAY-FK ROOT CAUSE + ★ NEW F-LOG-INFO-DROP · status:reported

STEP-0: DB 17:37Z / broker 13:37 ET agree; read-only + doc writes (repro script
scratchpad-only, not committed).

**F-REPLAY-FK ROOT CAUSE (CORRECTS both prior framings — the morning entry's
"partial batch" and the midday grade's "one deterministic blob"):** `data_blobs`
has **ZERO rows, all-time**. Every blob batch fails; smoking gun 5/5 cycles in
worker logs: `BlobStore batch commit failed: Object of type bytes is not JSON
serializable`. Mechanism: `blob_store.py:158` stages raw gzip BYTES as
`payload`; `commit()` (`:289-292`) upserts via supabase-py, which JSON-serializes
the row batch → TypeError on EVERY batch (~5 blobs/run ride ONE batch,
COMMIT_BATCH_SIZE=200) → all hashes failed → `decision_context` inserts
decision_inputs referencing never-persisted hashes → FK 23503 → run failed, job
green. `82b5be18…` is merely the FIRST violating row in stable insert order (the
input shared by close + open cycles), not a special blob. The 2MB cap is
warn-only AND never triggered — unrelated. REPRODUCED locally
(scratchpad/repro_blob_fk.py): json.dumps of the staged row → the exact
TypeError; fix shape PROVEN: payload as PostgREST bytea hex-string (`\x`+hex)
serializes and round-trips. HOW IT SHIPPED GREEN:
`test_replay_feature_store.py:202-203` MagicMock supabase client — a mock AT the
failing layer (the client serialization boundary); 4th instance of the
inject-at-origin class (§9).
**② FIX SHAPE (tonight):** (a) hex-encode payload at commit + decode `\x`-hex on
`get()`/`get_many()` (the read path `:184-189` expects bytes and would fail on
the string PostgREST returns — fix BOTH sides); (b) atomicity gate:
blobs_committed == expected BEFORE the decision_inputs insert — shortfall →
typed `capture_partial`, never an FK-orphaned insert attempt; (c) oversize →
the same typed capture_partial, never staged-and-referenced; (d) the test drives
the REAL serialization boundary (json.dumps of the batch at minimum), not a
MagicMock. Annotation sweep: 5 runs today (13:00 close + 14:05/15:02/16:00/
17:29 opens), ALL unrecoverable (no blobs exist), same first-FK hash.

**★ F-LOG-INFO-DROP (NEW, HIGH, instrumentation-integrity) — the worker process
DROPS every `logger.info` in the app.** No logging config exists ANYWHERE in the
repo (basicConfig/dictConfig/addHandler: test-local only); workers are bare RQ
SimpleWorker → root logger unconfigured → Python lastResort handler = stderr at
WARNING. So print() and warning+ reach Railway; EVERY info line in
packages/quantum is destroyed IN-PROCESS (never emitted — not a Railway filter).
Proof: intraday_risk_monitor ran 17:30/17:45Z (RQ "Job OK" wrapper lines) but
its `[RISK_MONITOR]` info summary (`:583`) is absent; utilization_gate logs at
WARNING only (`utilization_gate.py:119-424`) — exactly why its lines are the
ones we see.
- **Shadow-window verdicts — all three = CONFIG (not gated-behind-arm, not
  unreached-path):** [APPLY_ORDER_SHADOW] (`calibration_apply_ordering.py:158`,
  info) · [RISK_BASIS_SHADOW] (`risk_basis_shadow.py:40/:50`, info) ·
  [BUCKET_SHADOW] (`bucket_control.py:177`, info). All emit at info on paths that
  RAN today (gate evaluated, executor processed 4 candidates, scan ranked). The
  observe guards are CORRECT — each logs when the arm flag is OFF; no window
  logs-only-when-armed.
- **The heartbeats ALREADY EXIST and ride the same dead channel:**
  `log_shadow_heartbeat` (`risk_basis_shadow.py:58-70`, info) is wired at the
  apply seam (`calibration_apply_ordering.py:118-124`) and the executor
  (`paper_autopilot_service.py:976-983`) — built by #1187 PRECISELY to
  disambiguate "ran-saw-nothing vs logging lost", and killed by the exact
  logging loss it exists to detect. F-WINDOW-1 reframed: not "build heartbeats"
  — "give the channel a handler".
- **⚠ W-CLOCK ANNOTATION: the arm-evidence stream since d5edd50 (07-12) has
  produced ZERO collectible lines** — [RISK_BASIS_SHADOW] has NEVER appeared in
  Railway (4d search; the current deployment covers the whole window; no market
  cycles before Monday). Day-1/day-2 evidence LOST; the ~1wk observation clock
  was never running; **it restarts at tonight's logging-fix SHA.** (The one
  shadow marker ever observed — 07-09's [GATE_QTY_SCALED_SHADOW] ×9 — is
  logger.WARNING, `paper_endpoints.py:1370`: consistent, and explains why the
  v1.3 W2/W4 analyses were code-reads, not log-reads.)
- **② RIDER (small, tonight per operator): worker logging config at startup** —
  root INFO, or a targeted INFO level for the shadow/heartbeat/monitor loggers
  (owner's call on noise; scanner info is voluminous) + confirm RQ noise stays
  bounded. Supersedes the F-WINDOW-1 P2-tail build item (heartbeats exist; the
  fix is the channel).

## 2026-07-13 (Mon ~12:5x CT, RTH read-only) — SCORING/GAP-REPORT ADJUDICATION (the doctrinal audit's 64/100 companion) — reconciliation + adoptions · status:reported

STEP-0: DB `17:48Z` / broker `13:48 ET` agree (Mon 07-13, market OPEN — read-only
+ doc writes; tonight's ②③④ UNCHANGED). Source document NOT on disk (same as the
~12:1x doctrinal entry); adjudicated against the operator's restated gap set.
H11: only the known `ops_job_never_run` thesis_tracker arm (×5, latest 17:07Z;
self-resolves at the 17:00 CT first run per the morning entry).

**RECONCILIATION (10 ranked gaps → backlog): ALL TEN HAVE HOMES; queue order
UNCHANGED.** 1→canonical-position-representation (07-13 P1) · 2→queue-⑤ (charter
enriched 07-13) · 3→⑥ partial-close (trigger-gated P0) · 4→multi-basis cost P1
(incl. the ranker 4× worst case) · 5→tonight's ②+③ (② already expanded by
F-REPLAY-FK this morning) · 6→④ F-A3-4 + ③ E19-2 + the NEW segment-n line
(below) · 7→Phase-3 gate — **3/10-15 VERIFIED**: 3 stamped live fills
07-01→07-08 in `paper_orders.order_json` (`close_fill_gap_*` keys), all with
gap_fraction; the 07-08 SIGN FIX is IN CODE (`alpaca_order_handler.py:660-665`)
so the accruing evidence basis is clean — the stale "first gap_fraction still
pending" backlog line corrected · 8→versioned-earnings + per-leg quote envelope
(+ the r/q rider, below) · 9→vertical-before-IC (07-13 GATED) · 10→throughput
tail (greedy-stop DOWNGRADE stands · reaper∪F-A4-2 · W2b · F-A10-1 DST/warm-up
+ the A10 winter-close note).

**NEW CLAIM 2a — CONFIRMED (LATENT): segment calibration admits at n=3.**
`calibration_service.py:240` `if len(group) < max(3, min_trades // 4)` with
MIN_CALIBRATION_TRADES=8 → per-segment floor **3**, while the OVERALL gate
requires 8 (`:217`); `apply_calibration` (`:610-641`) applies the most-specific
segment multiplier with NO sample-size re-check at apply time; and the >5%
deviation filter (`:250`) preferentially persists small-n noise (small samples
deviate more). LATENT today: the live blob is `_overall`-only (n=8, ev/pop ×0.5
floor — DB-verified this session); it fires as live segments reach 3-4 closes.
→ NEW backlog line (07-13 section).

**NEW CLAIM 2b — PARTIALLY BUILT: r/q basis captured on ONE path only.**
`bs_inversion.py` prices with caller-supplied r/q; the sole production caller
family assumes FIXED r=0.045 (`BACKFILL_RISK_FREE_RATE` default,
`iv_historical_backfill.py:41`) and q=0.0 (`HistoricalIVService` default, never
overridden — the handler doesn't pass dividend_yield at all). The BACKFILL path
DOES persist both (`historical_iv_service.py:359-361` →
`underlying_iv_points.inputs` jsonb, `iv_repository.py:116`). NOT captured: the
daily snapshot path (feed-provided IV — the provider's r/q assumptions unknown)
and decision-stage per-leg quotes/greeks. → one-line rider on the per-leg
quote-envelope item (cheap; replay fidelity).

**CORRECTIONS CARRIED (annotated, not adopted):** (3a) gap 1's "feeds active
monitoring and entry breakers" is OVERSTATED — the ~12:1x verdict stands:
CONFIRMED-LATENT, P1 with the re-arming seam as the trigger (greeks doubly
dormant · stress warn-only · concentration demoted-to-WARN with the flag
live-echoed). Not P0-live. (3b) gap 10's "greedy-stop removed" done-criterion
CONTRADICTS the Lane-A replay DOWNGRADE (the budget break never fired in any
replayed cycle); the standing done-criterion is "downgrade verdict stands with
its mechanical reopen (>4 fitting candidates AND the roundtrip gate passing a
tail)," not "removed."

**MILESTONE SCALE — ADOPTED as the standing convention (theirs, verbatim):**
**85** = no known critical correctness defect, decisions reproducible · **90** =
canonical risk/EV/costs/replay/partial-close complete · **95** = repeated
runtime proof + Phase-3 evidence + failure-injection exercises · **100** =
reference ceiling only. **Realistic goal: 90-95.** Adopted closing line: "a
genuinely excellent design may correctly conclude that none of today's
candidates has positive net edge" — the capital-adequacy note's doctrine twin.

**POINTS-AS-CROSS-CHECK:** their point-weighting independently converges on our
queue — their #1/#2/#5 = our canonical-position / ⑤ / tonight's ②③, and their
cost-basis (+3) above partial-close (+2) effectively matches our ⑥
trigger-gating (both orderings say cost coherence binds before partial-close
custody while the book is flat). No divergence demands an owner look; NO queue
changes from scoring alone. Only the +3/+2 values were restated by the operator
— rubric weights are opinions, not adjudicable facts.

**SCORECARD (filed as CONTEXT, not a verified quantity):** 64/100, stated range
62-68, on their stricter rubric. Epistemics worth paying externals for: they
retracted their own "28.1% growth" figure as false precision — the
self-correction is the value; the number itself is context only.

## 2026-07-13 (Mon ~12:1x CT, RTH read-only) — DOCTRINAL-AUDIT ADJUDICATION (Sinclair/Natenberg) — scorecard + verdicts · status:reported

STEP-0: DB `17:11Z` / broker `13:11 ET` agree (Mon 07-13, market OPEN — sanctioned
read-only doc session, no builds/recycles). Source document NOT on disk (Downloads
swept, repo grepped — no Sinclair/Natenberg artifact); adjudicated against the
operator's restated claim set, fully specified per sub-claim. Their blind spot
honored: every live-path claim got the runtime check they couldn't run. Tonight's
queue (② E16-3 → ③ E19-2 → ④ F-A3-4 → tail) **UNCHANGED** — the P0 gate condition
(CONFIRMED-ARMED) did not obtain.

**F-RISK-ENV (their #3) — VERDICT: CONFIRMED-LATENT (all four sub-claims CONFIRMED
in code; NO defective number can flip a live decision as deployed today) + a NAMED
RE-ARMING SEAM.**
- (i) CONFIRMED `risk_envelope.py:200-201` — `_pos_risk` returns
  `max_credit×qty×100` (the credit RECEIVED = max GAIN) as "risk" for credit
  structures; true defined-risk basis is width−credit. Feeds all concentration
  ratios + `total_risk`.
- (ii) CONFIRMED `:230-233` (stress twin `:519-520`) — leg greeks ×
  `abs(position_qty)`×100: no buy/sell sign, per-leg quantity ignored entirely.
- (iii) CONFIRMED `:524` — `spy_loss = total_delta × 0.05` treats −5% SPY as a
  −$0.05 move (underlying price missing; ~600× understated). Same-family bonus
  `:530`: the VIX leg treats "+50%" as +50 vol points (overstated).
- (iv) CONFIRMED `:535` — correlation-one = −`total_risk` = Σ of (i)'s basis.
- RUNTIME (the check they couldn't run): consumers at HEAD = autopilot breaker
  (`paper_autopilot_service.py:407-427`, blocks ONLY on passed=False =
  block/force_close) · monitor 5b (`intraday_risk_monitor.py:517-572` —
  force_close only ever from LOSS envelopes, whose basis is unrealized_pl, NOT
  `_pos_risk`; warn/block → `envelope_violation` alert rows, no action) · MTM +
  orchestrator log-only · `check_new_position` still zero production callers.
  Greeks DOUBLY dormant RE-VERIFIED TODAY: 0 legs (of 83 positions ever) carry a
  `greeks` key + RISK_MAX_DELTA/GAMMA/VEGA/THETA unset (default 0 = no-limit) —
  (ii)+(iii) SPY-side compute only zeros, and are severity=warn regardless.
  Stress = warn → alert-noise ceiling. The ONLY block-capable defective-basis
  path is `concentration_symbol` (basis = (i)) — DEMOTED to WARN in the sole
  blocking consumer, read back on the RUNNING worker today
  (`[UTILIZATION_GATE] flag RISK_UTILIZATION_GATE_ENABLED raw='1' → enabled=True`
  + small-tier demotion lines at 14:06/16:09/16:30Z). Armed envelope env
  (worker; names+values non-secret): SYMBOL_PCT=.4 · DAILY=.08 · WEEKLY=.1 ·
  SYMBOL_LOSS=.03 · utilization =1 cap .85 · RISK_ENVELOPE_ENFORCE=1; stress
  thresholds at defaults.
- THE RE-ARMING SEAM (why this is P1, not P3): unsetting
  RISK_UTILIZATION_GATE_ENABLED (a §4 SANCTIONED kill switch — "reverts to the
  stricter BLOCK" — i.e. reverts to a block ON THE WRONG BASIS), any
  demotion-check failure (fail-safe retains BLOCK), or tier growth past small
  → `concentration_symbol` blocks entries on credit-received ratios. Alert-noise
  is DEMONSTRATED, not hypothetical: 6 `envelope_violation` rows 07-07/07-08
  (symbol high ×2 / sector ×2 / expiry ×2) fired off this basis. Book FLAT
  (broker + DB) at adjudication; QQQ candidates ALLOWed today, so the basis
  becomes computable on the next fill — still non-blocking under demotion.
- DISPOSITION: MERGED into the NEW canonical-position-representation P1
  (backlog 07-13 section) with the book-scaling family (#1166's persisted
  max_loss_total is the same truth — reuse, don't recompute).

**IC EV BASIS (their #2) — CONFIRMED, with a runtime CORRECTION.** Deployed model
is `tail` (CONDOR_EV_MODEL=tail on worker): `calculate_condor_ev_tail`
(`ev_calculator.py:632-712`) = |shortΔ|×prob_mult as breach prob, |longΔ| as
max-loss prob, fixed partial-loss severity — but the deployed constants are
severity **0.35** (not the 0.50 default they read) and CONDOR_TAIL_PROB_MULT
**0.6** (an ad-hoc 40% delta haircut they didn't see — which REINFORCES their
point: this is a tuned modeled EV, not a physical forecast). The scanner stamps it
(`options_scanner.py:1800-1823` → `:3505-3506` → suggestion ev_raw; 22 IC
suggestions/30d, latest today 16:00Z QQQ), calibration halves it (ev = 0.5×ev_raw
exactly — floor engaged, live rows verified), and the #1101 roundtrip gate
compares costs against THAT number. Honest framing: the known "modeled EV" made
precise — NOT a new gate bug. → queue-⑤ charter ENRICHED (backlog): ONE
independent terminal distribution, TWO payoff integrations (credit verticals E12
+ condor EV); their ensemble spec + falsifier attached verbatim.

**CALIBRATION CLAMP (their #4) — CONFIRMED; floor-HOLD annotation only.**
`calibration_service.py:466-479`: ratio = realized_avg/predicted_avg clamped
[0.5,1.5]; a NEGATIVE realized average floors at ×0.5 — multiplicative, so it
can only shrink a positive predicted edge, never flip its sign. ANNOTATION on the
SETTLED floor-HOLD decision (07-09; stands): **the 0.5 floor bounds shrink but
cannot correct a sign-wrong edge — the falsifier (E17/preq…58943 tokens truncated…ity_of_profit`
PRESERVED unchanged; before+after read-backs shown. All pre-04-16, paper,
consumed by nothing live.

**ERRATUM (the premise-check doctrine working).** The 07-10 build spec's ITEM-1
fork verdict placed the overshoot at the delta-cushion composition path; the
pre-build premise check re-confirmed the actual site (calibration multiplier,
already clamped 04-16) and prevented shipping a dead-code clamp. The
fork-verdict METHOD held; the SITE (in the spec AND in the original v1.2
free-look "delta-based overshoot; one-liner clamp") was wrong — corrected here
+ in backlog.

**RIDERS FILED.** (i) PoP CENSUS — verified **7 base PoP computations**
(ev_calculator.calculate_pop; calculate_exit_metrics `abs(delta)` = the
take_profit_limit source; calculate_condor_ev; options_scanner
`_estimate_probability_of_profit`; `_condor_pop_from_legs`;
opportunity_scorer `_calculate_ev_pop`; forecast_interface `forecast_ev_pop`)
+ 2 transforms (apply_calibration, conviction) — NOT "5" (the spec undercounted).
The inverted credit/width one (F-A3-1, latent) is calculate_pop's credit branch.
Rider on the multi-basis/PoP-unification item: **"the unified PoP MUST
bound-assert [0,1] at the compute site"** — the insurance lands once, at the
right place, when that work runs. I touched only the calibration-apply clamp (a
transform), NO base computation. (ii) Clamp boundary-log review trigger:
frequent `POP_CLAMP_ENGAGED` → cushion/multiplier revision, WITH the dormancy
note (can't fire while pop_mult ≤ 1.0). (iii) Prequential UNBLOCKED — the A1a
field-contract prerequisite is CLOSED; remaining for that build: add the
`is_paper=false` live-only filter (smoke-run used 99 mixed rows) + confirm
`ev_predicted` is RAW not calibrated.

## 2026-07-09 EOD (latest) — COMPARATIVE-RECON INTEGRATION (v1.2) + v5.5 CANONICAL

STEP-0: broker 19:35 ET (closed) / DB 23:35Z — agreed. Doc/prompt writes only,
runtime-inert (prompt files read by `run-nightly.cmd` + humans, not services).

**A1 VERIFICATIONS (the recon's two falsifiable code claims + two gated grades):**
- **A1a field contract → CONFIRMED.** `walkforward_validate_learning_v3.py`
  reads `learning_trade_outcomes_v3` expecting `ev`/`expected_value` +
  `realized_pnl`/`pnl`; the table exposes `ev_predicted`/`pnl_realized`
  (+`pnl_predicted`/`pop_predicted`) → `KeyError` at `df['ev'].fillna` (`:101`).
  Script cannot honestly validate the view → field-contract fix folded into the
  calibration-ordering item.
- **A1b F-A2-1 vs recon #4 → MERGE.** F-A2-1's charter had the invariant but no
  explicit reconciling state; the recon supplies `UNKNOWN_RECONCILING` + typed
  transitions + targeted client_order_id lookup + fill+closure invariant
  (Nautilus/Hummingbot cites). Merged into P0-A (what it lacked: the state
  machine + the targeted lookup).
- **A1c(i) replay substrate → CONFIRMED ~55%, but WORSE than graded.**
  `from_decision_id` = ZERO production callers (docstrings + 1 test); capture
  tables `decision_runs`/`decision_inputs`/`decision_features` EXIST **but hold 0
  ROWS** — schema-only, nothing writes them. The replay item's prereq (capture
  rows) is UNMET → its drop-condition fired → item rescoped to include a
  capture-WRITE path first.
- **A1c(ii) earnings gate → CONFIRMED.** `options_scanner.py:3866-3879` gates on
  `days_to_earnings<=2` (hard) / `<=7` (penalty) only — NO event-before-expiry
  check. Grade holds.

**RECON SCORECARD:** claims spot-checked where falsifiable were evidence-verified
(A1a field mismatch, A1c earnings gate, replay caller/schema); coverage grades
materially correct (replay ~55% — adjusted down for the 0-row capture);
falsifiers carried verbatim into the items as retirement conditions (the GOLD
prequential falsifier especially). Recon method: sound; one grade optimistic
(assumed capture rows existed).

**CORRECTION to OUR earlier framing (A2.7, move-don't-lose):** the recon
confirmed **21-DTE / 50%-credit / DTE gates already ~85% EXIST in cohort
policy** — the earlier deep-dive's "position-management conventions missing"
impression is WRONG and is corrected here + filed in the DO-NOT-RE-LITIGATE
backlog section. Do not re-derive them as a new build.

**BACKLOG DIFF:** P0-A absorbed recon #4 state machine; calibration-ordering item
absorbed recon #2 (prequential + A1a field-contract fix + GOLD falsifier); NEW P1
deterministic replay (+ 0-row capture prereq); NEW P2 versioned earnings cohort
(fix gate to event-before-expiry, observe-first); NEW P2 per-leg entry quote
envelope; DO-NOT-RE-LITIGATE standing section seeded.

**v5.5 CANONICAL ON DISK:** `audit/v5-prompt.md` upgraded to v5.5 ELEVEN AREAS
(A1-A9 + A10 rotating Calendar&Clock + A11 permanent Self-Extension) at this SHA;
STATE refreshed to tonight; external prompt STATE re-stamped. **Prompt-drift class
CLOSED: the invoked file (`run-nightly.cmd:8` → `audit/v5-prompt.md`) IS the
version of record; session-prompt changes MUST land here same-day.** Tonight's
midnight run is the first eleven-area (v5.5) nightly.

## 2026-07-09 EOD (late) — EXTERNAL AUDIT v1.1 ADJUDICATION (P0/P1 verified vs code+DB+broker)

STEP-0: broker 19:15 ET (closed) / DB 23:15Z — agreed. READ-ONLY + the one
pre-authorized security commit. Book FLAT now (0 open, 0 live-routed).

**P0-1 CREDENTIAL (F-FREE-1) → LOCAL-ONLY-FAKE (NOT a live compromise).**
`.env.example` (git-tracked since the 2025-11-19 initial commit `82e8ef8`)
carried real-shaped Supabase anon + `service_role` + S3 keys. Fingerprint:
URL is `http://127.0.0.1:54321`, keys are modern `sb_publishable_`/`sb_secret_`
format; production `etdlladeorfgdmsopzmz` exposes a legacy JWT anon key at its
cloud URL — different host/format/value. **No production credential exposed →
no live rotation warranted.** Pre-authorized scrub SHIPPED as placeholders
(PR #1145, `95d3bb5`, NOT merged — left for operator). OPERATOR ITEMS (not
done): git-history cleanup (BFG/filter-repo of the pre-scrub blob) + GitHub
secret-scanning/push-protection enablement. Even LOCAL keys public 8 months
= rotate the local stack at leisure.

**P0-2 LIVE-CLOSE CUSTODY (F-A2-1) → LATENT (chain real, NEVER fired).**
All four sub-claims CONFIRMED at the deployed SHA (d45ad63):
(i) `paper_exit_evaluator.py:1700` `position_is_alpaca=False` default +
`:1712-1727` routing-query failure only WARNs (`paper_exit_routing_query_failed`,
no raise); (ii) `:2162` `submit_and_track` result discarded, `:2172-2177`
returns `routed_to='alpaca'` unconditionally; (iii) `:2178-2207` a RAISED
submit exception (from `get_alpaca_client`/order fetch/imports/the pre-cancel
`cancel_open_orders_for_symbols` at `alpaca_order_handler.py:245`, OUTSIDE the
retry-try) falls through to an INTERNAL FILL — `:2272-2280` writes
`status='filled'` on a LIVE position with no broker ack (fires
`paper_exit_alpaca_submit_fallback_to_internal` critical first); (iv)
`intraday_risk_monitor.py:1428-1434` treats ONLY `deferred_uncorroborated` as
not-closed, so the internal-fill return (no `routed_to`) logs as a SUCCESSFUL
`force_close`. **RUNTIME: never fired on a live position.** All 9 post-epoch
live closes are `close_reason='alpaca_fill_reconciler_standard'` (broker-
reconciled); 42 filled close orders carry a broker id; the 10
`submission_failed`+filled internal-fill rows are all PRE-LIVE alpaca-paper era
(latest 2026-04-06); ZERO `submit_fallback_to_internal` alerts ever (the 3
`paper_order_marked_needs_manual_review`, latest 06-12, are the ordinary
broker-reject path that leaves the position OPEN, not internal-filled).
**→ E6 exclusion-integrity FAIL:** the live-close-custody closure claim fails
as written — the fallthrough hole is real and unclosed, merely un-triggered.
**→ NEW #1 BUILD: the broker-acknowledged-close invariant** (a live close may
NOT record `status='filled'` without a broker ack; raise→retry/needs-manual-
review, never internal-fill). Supersedes strategy work + Phase-3.

**P0-3 RISK CUSTODY (F-A1-1/A1-2) → CONFIRMED book-blind + PREMISE CORRECTED.**
(a) `paper_positions` has NO `cost_basis`/`current_value`/`max_loss`/
`collateral` columns at all → the allocator (`portfolio_allocator.py:116-144`
`_sum_open_cost_basis`) and RBE (`risk_budget_engine.py:99-208`
`_estimate_risk_usage_usd`) read those keys and get None→0, so the OPEN book
contributes ~$0 to utilization/envelope; writer omits them too (both true).
(b) Utilization gate (`utilization_gate.py:323-341`): candidate cost =
`limit_price*contracts*100` = ~$149 for a 1.49-credit IC, NOT the ~$351 max
loss — AND asymmetric with the already-open side (`structure_commitment_usd`
uses `width*100`=margin). **PREMISE CORRECTION (four-source: packet/registry
said "book ≤1 always"; DB says peak 3):** 3 concurrent real-money live
positions ran **2026-06-11 16:20Z → 06-12** (NFLX+QQQ+SPY; again 06-12
18:30-18:45 NFLX+QQQ+MARA). So the book-blind sizing + credit-basis gate + the
one-beta exposure were ALL live-reached, BEFORE the #1139 tripwire shipped
(07-08). Grade: latent-critical **that has already occurred** (no realized harm
— positions were small — but the aggregate cap was un-enforced across that
window). Merges with B1/B2 into ONE "book-scaling readiness" epic.

**P1 VERDICTS:**
- **(d) F-A1-3 calibration ORDERING → CONFIRMED.** `apply_calibration` at
  `workflow_orchestrator.py:3562-3569`, AFTER select(`:2495`)/allocate(`:2634`)/
  size(`:3241`); score/selection/sizing consume RAW ev; only persisted `ev`
  (`:3609`) + post-selection `risk_adjusted_ev` recompute (`:3669-3674`) reflect
  the multiplier. Morning path stamps `risk_adjusted_ev`/`status` on RAW then
  overwrites `ev` (`:1753-1755`) — raw/calibrated divergence on one row.
  **RE-SCOPES tomorrow's 16:00Z proof** (below). NEW P1 (design, not one-liner).
- **(e) F-A3-1 PoP → CONFIRMED-but-LATENT (our adjudication upheld).** The
  inverted `credit/width` branch (`ev_calculator.py:34-42`) accepts ONLY 2-leg
  credit verticals (`credit_spread` et al.); IRON_CONDOR (condor precomp +
  delta-tail) and debit spreads (delta interp) never enter. DB: strategies ever
  stored = IRON_CONDOR/LONG_CALL_DEBIT/LONG_PUT_DEBIT/take_profit_limit — ZERO
  credit verticals ever → branch never reached. (FREE-LOOK: stored PoP > 1.0 on
  debit-spread + take_profit_limit rows (max 1.0704) — impossible probability,
  delta-PoP overshoot; additive one-liner filed.)
- **(f) F-A4-1/A4-2 → both CONFIRMED.** `iv_daily_refresh` returns
  `status:ok` on all-missing (accounting `0==0`); it is ABSENT from
  `EXPECTED_JOBS`, and the watched `learning_ingest` is an explicit NO-OP STUB
  while the real producer `paper_learning_ingest` is unwatched. Observability
  → the carried 3-in-1 PR (recommend SPLIT into a 2nd observability PR, below).
- **(g) F-A9-1 → CONFIRMED.** `signal_accuracy_rolling` win = `pnl_realized>0`
  (realized win-rate), not thesis accuracy. Relabel → `realized_trade_win_rate`
  rides the thesis-tracker build; B1 ≈78% thesis vs this view's 12.5% is the
  exhibit.
- **(h) F-A8-1 → CONFIRMED.** Rejection over-count: inner `process_symbol`
  reason + outer wrapper `no_fallback_strategies_available`/
  `all_strategies_rejected` both `record()` (`options_scanner.py:4106/4141`),
  so `total_rejections` > distinct rejections. Annotate the packet's ~916.
  (Lane A greedy replay used `trade_suggestions`, NOT the 916 figure — Lane A
  unaffected; future rejection-based analysis must dedupe.)
- **(i) F-A2-2 → CONFIRMED (nuance).** `quote_complete=False` requires BOTH
  sides of EVERY leg (`exit_mark_corroboration.py:172-178`); when a non-
  executable side is missing it discards a COMPUTED executable-side divergence
  and force-suppresses — but ONLY for TARGET_PROFIT (`:246-253`); stop_loss is
  NEVER suppressed (`:243-245`). So it's a named mechanism for MISSED profit-
  takes (→ held longer → more stop exposure), NOT direct stop over-pessimism.
  Feeds Phase-3 instrumentation as a specific thing to measure.
- **(j) A10 import-time flags → CONFIRMED, no NEW class.** Module-scope env
  reads: `MIDDAY_TEST_MODE`/`COMPOUNDING_MODE` (`workflow_orchestrator.py:179-180`),
  `CALIBRATION_ENABLED` (`calibration_service.py:34`) — added to the inventory.

**RE-SCOPED "tomorrow 16:00Z proof" language (per d):** a persisted scan row
with `ev == ev_raw × 0.5` proves E1's flag — the multiplier reaches the
PERSISTED ev and therefore the final-stage round-trip gate. It does NOT prove
the calibrated value influenced SCORE, SELECTION, or SIZING — those consume raw
ev by construction (apply runs post-sizing). State it exactly: raw = score /
selection / sizing; calibrated = final-stage gate reading persisted ev +
persisted `risk_adjusted_ev`.

**EXTERNAL v1.1 SCORECARD (exclusion-integrity E1-E9 as graded):** E6 FAIL
(headline — custody closure claim false-as-written); the rest of their P0/P1
CONFIRMED at the line (their runtime-flag/mapping method vindicated again, Q1-
class). Weight: high. 11 packet/prompt disagreements → annotate move-don't-
erase (the ≤1-position premise correction is the load-bearing one).

## 2026-07-09 EOD — BUILD #1143 SHIPPED (shadow-detection + calibration fail-loud) + ⭐ OPTION-B CLOCK-RESET MARKER

**#1143 `655c9aa` — MERGED + H8 VERIFIED.** Post-close (merge 22:54:19Z;
STEP-0 grounded: broker 18:45 ET market-closed, DB 22:45Z). Two fail-safe
fixes:
- **Shadow-detection value match (E2 residue):** `_is_shadow_routing()`
  (`paper_endpoints.py`) now whitelists the REAL production value
  `shadow_only`. The prior check matched `paper_shadow`, which production never
  emits → the #1141 Option-A shadow branch was INERT (all cohorts fell to the
  observe-only legacy-sized basis, `basis=legacy_sized`). Unknown/None routing
  → False → observe-only (fail-safe: an unknown value never flips a live
  decision). Live path still behind `GATE_QTY_FIX_LIVE_ENABLED` default-OFF.
- **Calibration fail-loud:** once-per-scan WARNING at the midday apply site
  (`workflow_orchestrator.py`) + a write-side WARNING when a blob is stored
  while apply is disabled (`calibration_update.py`) + an import-time-flag
  caveat comment (`calibration_service.py`). Logs only; the flag itself was
  re-enabled by env flip earlier this session (a Railway flip needs a recycle
  — exactly what the import-time comment documents).
- **H8:** BE `d1fe9f87` / worker `74f3c83d` / worker-background `dad9b9e0` —
  all SUCCESS at `655c9aa`, created 22:54:22–23Z > merge 22:54:19Z; prior
  `907d4cd` deploys REMOVED. No new flags → no read-back beyond confirming
  `GATE_QTY_FIX_LIVE_ENABLED` OFF + `CALIBRATION_ENABLED=1` (both unchanged).
- **Tests:** `test_shadow_routing_fix.py` (13) pin `_is_shadow_routing` on the
  exact production strings + the routing→gate-decision chain (shadow PASS /
  live REJECT+observe / unknown observe-only / qty=1 invariant) + the two
  fail-loud source sites. CI green (run 29055518433, 1m42s).

**⭐ OPTION-B CLOCK-RESET MARKER — STAMPED AT `655c9aa` (recycle 22:54:22–23Z).**
Both preconditions are now met ON THE RUNNING PROCESS: (1) calibration APPLYING
(`CALIBRATION_ENABLED=1`, re-enabled this session) and (2) shadow-detection
CORRECT (`shadow_only` matched). **The Option-B (live gate-qty apply) observe
window's evidence clock RESETS here: the 9 `[GATE_QTY_SCALED_SHADOW]` observe
lines logged before this recycle are DISCARDED** — they were counted on the
inert-shadow + inert-calibration basis and are not clean. **Clean observe
evidence counts only from the first scan after this recycle (07-10 16:00Z scan
onward).** `GATE_QTY_FIX_LIVE_ENABLED` stays OFF — Option B remains an operator
decision, now to be made on clean data.

**B4 — EXTERNAL-REVIEWER SCORECARD (so future sessions weight their input
correctly):** external Q1 (calibration computes/stores but returns ×1.0 =
a runtime-flag/mapping issue) **CONFIRMED-RIGHT-FOR-THE-RIGHT-REASON** by
internal recon — root cause was `CALIBRATION_ENABLED='0'`, stale since the
06-11 epoch, never restored. Their A7 ("stops saved money") **REFUTED on broker
truth** — the stops mostly force-closed thesis-favorable positions early (B1's
downstream finding); an honest data limitation on their side (no broker
access), not a reasoning error. Net: a **calibration-proven** external — high
weight on their future findings.

## 2026-07-09 EOD — EXTERNAL-REVIEW ADJUDICATION (read-only; verdicts + B1 headline + A6 corrections)

**B1 — THE HEADLINE (the number the external couldn't compute): thesis
hit-rate ≈ 7/9 (~78%) vs P&L hit-rate 1/9 (~11%). THE PROBLEM IS
DOWNSTREAM (execution/exits/costs), NOT the signal.** Scored each live
close's entry thesis against the underlying's path to its INTENDED horizon
(strikes + exp vs 07-09 prices): NFLX(down, hit), NFLX(down, hit, +48),
QQQ-IC 06-15 (QQQ 723 inside 645-750 → hit but force-closed −73), SPY-IC
(751 inside 681-765, on-track, −45), SOFI(18.6>17, on-track, −40),
QQQ-IC 07-07 (inside, −15), QQQ-IC 07-08 (inside, −10) = 7 thesis-
favorable; MARA×2 (13.2<13.5/14, didn't rise) = 2 miss. **6 of 9 were
thesis-RIGHT-but-lost-money** — the underlying was in/toward the profit
zone but the position was force-closed early at a loss (the premature-stop
/ Phase-3 over-pessimism pattern, now quantified). CAVEAT: 5 of 9 expiries
are FUTURE (07-24→08-21) → "on-track" not "hit"; labeled in-progress.
**INSTRUMENTATION GAP FILED: no shadow-to-expiry tracker — positions
force-closed in minutes leave nothing following the underlying to the
original expiry, so thesis quality is only spot-scoreable. This is the #1
missing measurement.**

**A6 — LEDGER CORRECTIONS (broker=truth; the realized P&L was always
RIGHT, the EXIT-PRICE DISPLAY used the MARK not the FILL — mid-vs-fill
confusion, recurring class):**
- QQQ 07-07: exit shown 1.74 (mark) → **broker FILL 1.64**; realized −$15 ✓.
- SOFI 06-30: exit shown 1.53 (mark) → **broker FILL 1.36**; entry 1.44 →
  1.36 = −0.08 ×5×100 = **−$40 ✓ (reconciles the "impossible" row)**.
- QQQ 07-08: exit shown 1.535 (mark) → **broker FILL 1.59**; credit 1.49 −
  1.59 = −0.10 ×1×100 = **−$10 ✓ (the "−5" was the mark)**.
  → The external packet §2a exit-price column reads MARKS; correct to these
  fills on its next revision (packet is committed #1142 — annotate there,
  not erase). P&L rows unchanged.

**A1-A7 VERDICTS (cites in the session):** A1 credit-spread PoP=credit/width
= max_gain/(max_gain+max_loss) (ev_calculator.py:42) — **CONFIRMED inverted
(≈P(loss)); but LATENT** — IRON_CONDOR + debit strategies (the whole live
book) are NOT in that branch's strategy_type list; blocks the 2-leg-vertical
cohort. A2 stop = pct × max_CREDIT (policy_lab/config.py:33), cohorts
0.40/0.50/0.65 — **CONFIRMED credit-relative** (~17% of max loss at 0.40),
naming-clear in config but the basis is credit not max-loss. A3 ranker fee
= fee×contracts×2, NO ×leg-count (canonical_ranker.py:69) + slippage =
5%-of-EV proxy (:145) vs the gate's executable cross — **CONFIRMED
multi-basis; ranker under-costs 4-leg → ordering distortion (small $, but
real)**. A4 score clamped min(100) (guardrails.py:138) — **saturation
CONFIRMED**; but compute_conviction_score DOES use iv_rank conditionally
(:118-123) → "IV not in score" **PARTIAL** (the roi×500 production score not
located). A5 compounder legacy path ~3%×score (~$60) with a self-alert of
"~6-8× smaller budget" — **CONFIRMED sizing-model gap** (production uses the
allocator ≈ max_loss; the legacy fit-test tests a fiction). A6 above. A7
the stops fired on OVER-pessimistic corroborated UPL and the positions were
in-profit-zone at horizon → **"stops saved money" REFUTED** — they mostly
stopped WINNING theses early (= B1's downstream finding + Phase-3).
**External Q1 (runtime flag) CONFIRMED — weight their findings accordingly.**

## 2026-07-09 ~21:29Z — CALIBRATION RE-ENABLED (env flip + recycle, supervised)

**ROOT CAUSE (recon-proven by execution): `CALIBRATION_ENABLED='0'` stale
kill-switch, off since the 06-11 epoch, never restored.** Calibration was
LIVE 04-13→06-10 (38 rows, ev≠ev_raw), then disabled at the epoch to stop
pre-epoch sign-flipped multipliers applying to post-epoch predictions —
correct then, but the master apply switch was never flipped back when the
pool matured (07-09). The apply sites (`workflow_orchestrator.py:3554`
midday scan / `:1740` morning) are gated on the module-level flag; both
skipped. `get_calibration_adjustments` returned the correct 0.5 blob and
`apply_calibration(real blob)` → 19.85 in positive control — **the code was
never broken; the flag was off.** **NEW CLASS LINE: disabled-and-never-
restored** — a deliberate temporary disable with NO re-enable trigger; kin
to dead-triggers (§backlog) and prescribed-not-applied (WakeToRun). The
disable was FAIL-QUIET (no per-scan log; the write job kept computing +
storing a blob nothing read).

**SEQUENCE (all gates cleared before the flip):**
- STEP 1 — 21:20Z SUPPRESSION TEST **PASSED** (edge-trigger case 3, first
  live proof): `suppressed_standing_window:true`, tripped:false,
  paused_written:false, reason "standing_window_already_reviewed —
  fingerprint matches the last trip"; window unchanged, entries stay
  unpaused, 0 trips. #1135 fully validated.
- STEP 2 — pre-flight cleared: the only `MIN_POP=0.60` gate
  (`guardrails.SmallAccountCompounder.apply`) is **DORMANT** (not called by
  the scan; field-name `prob_profit` vs prod `probability_of_profit`;
  superseded by `services/analytics/small_account_compounder.py`) → a halved
  PoP breaks nothing live. Epoch off-reason moot (blob is post-epoch by
  construction).
- STEP 3 — **`CALIBRATION_ENABLED` set 0→1 on worker + worker-background**
  (BE is not an apply site). Recycle → both SUCCESS at `907d4cdd` (= the
  running `03e11d8` apply code + #1142 docs packet the operator merged;
  **zero code change**, H8-verified by diff). **Read-back: env=1, module
  CALIBRATION_ENABLED=True on the worker.**
- STEP 4 — **PRODUCTION PROOF: PARTIAL tonight, FULL pending 16:00Z
  tomorrow.** The forced post-close scan (job cb2db12c) short-circuited on
  the market-data **staleness gate** (age 94.8min, fast_path, processed 0)
  BEFORE scoring — so no scanned ev and no apply-site log tonight. Confirmed
  tonight: flag flipped + module True + `apply_calibration(blob)`→0.5
  (function). **NOT YET CONFIRMED (the built-not-wired class is NOT fully
  closed until this lands): a real scanned `ev == ev_raw × 0.5`** — rides
  tomorrow's 16:00Z scheduled scan on fresh quotes. Verify then.

**⚠ TRUE BOUNDARY MARKER (supersedes the annotated-false 07-09 10:00Z
marker): the apply path is ENABLED from 2026-07-09 ~21:29Z (907d4cdd,
CALIBRATION_ENABLED=1), but NO production ev has been calibrated yet
(tonight's scan was staleness-gated). The FIRST calibrated production ev is
2026-07-10 16:00Z. Every EV ever stamped before that moment was RAW except
the 38 pre-epoch rows (04-13→06-10).** Direction: TIGHTENING (EV×0.5 →
gate rejects more) — doctrine-clean, not a loosening.

**Option-B observe window: reset condition HALF-MET** (calibration now
enabled); fully resets when the shadow-detection one-liner ships. 07-09's 9
observe lines stay discarded (computed on un-halved EV).

**FILED (small PR, tomorrow / with the shadow one-liner): fail-loud
hardening** — log once-per-scan when `CALIBRATION_ENABLED` gates apply off +
flag the compute-but-never-apply waste; optionally move the flag read from
import-time to call-time (so it takes effect without a recycle). A
month-long silent recurrence must be impossible.

**PENDING-VERIFY (tomorrow morning): (1) 16:00Z scan produces ev=ev_raw×0.5
on a real suggestion [closes the class]; (2) the PoP ×0.5 lands only on
display (no live consumer) — confirm no regression; (3) the 21:45Z/22:00Z
learning chain ran clean post-recycle.**

## 2026-07-09 EOD — FIRST-CALIBRATED-SCAN-DAY FINDINGS (doc-only; fix-queue for tomorrow)

Flat day (0 trades, equity $2,067.86, −$0 P&L). First full day on the
supposed ×0.5 calibration + the gate-fix observe-log armed. Two findings,
both Claude Code's own, both fail-safe, both self-caught same day.

- **FINDING #1 (HIGH, headline) — CALIBRATION COMPUTED-NOT-APPLIED**: the
  0.5 multiplier stores at 10:00Z but `apply_calibration` returns ×1.0 at
  the scan — champion first calibrated scan verbatim `ev==ev_raw==39.71`
  (halved would be 19.86). Insert path stamps ev_raw then overwrites
  ev=apply_calibration(...) (workflow_orchestrator.py:1745-1755); equal
  values ⇒ ×1.0 returned. Suspect: `get_calibration_adjustments` fails to
  map an `_overall`-only blob into the `{strategy:{regime}}` return shape,
  so the documented `_overall` fallback (calibration_service.py:577) never
  fires and application silently falls to ×1.0. **CLASS: built-not-wired
  (#1126 family — computes/stores but doesn't reach the decision path).**
  RECON-THEN-FIX, own session, FIRST work tomorrow. Cross-ref: flagged to
  the external reviewer as §1 question (1) — do not double-drive; whoever
  moves first claims it.
- **FINDING #2 (one-liner + test) — OPTION-A SHADOW-DETECTION MISS**:
  #1141's gate keyed `routing_mode == "paper_shadow"`, but production
  values are aggressive=`live_eligible`, neutral/conservative=`shadow_only`
  → matched nothing → ALL cohorts ran `basis=legacy_sized` (observe-only),
  the shadow-side fix INERT, observe-log mislabeled shadows as `cohort=live`.
  FAIL-SAFE (zero live change; the miss defaults to the protected path) but
  promotion-un-biasing didn't happen. FIX: match `shadow_only` (or
  `!= live_eligible`) + pin the test on PRODUCTION routing values (the bug
  was test-fixture `paper_shadow` vs reality `shadow_only` — a test-vs-truth
  value mismatch, adjacent to the 9a2cef1 class). Ships after/with #1.
- **OPTION-B OBSERVE-WINDOW — EVIDENCE INVALIDATED, CLOCK RESET**: 07-09's 9
  `[GATE_QTY_SCALED_SHADOW]` lines are CONTAMINATED — the "would-open"
  new_net was computed on the UN-halved EV (39.71); with the real ×0.5
  (finding #1) new_net ≈ 19.86 − 12 = +7.86 < $15 → would NOT open. And the
  qty7/qty15 lines are shadows mislabeled live (finding #2). **The ~1–2wk
  Option-B observation clock counts ONLY from the SHA where BOTH #1 (calib
  applies) AND #2 (shadow-detection correct) are live. Discard 07-09's 9
  lines.** Re-arm marker to be stamped at that SHA.
- **ERRATA (annotation #6)**: this morning's ritual assertion "every EV
  number is now calibrated ×0.5" was a **verify-before-asserting miss** —
  overturned same day by ev==ev_raw. Pattern line: **TWO Claude-Code errata
  today (this + the recon's "champion always qty-1" caught by the SOFI qty-5
  fixture), both fail-safe, both self-caught within the day.** The standing
  boundary marker (07-08 postclose entry) is annotated in place, not erased.
- **NOISE-CLASS PRESSURE (reinforces the TOP-3 3-in-1)**: the observability
  PR was FIX-TODAY in the morning triage and DID NOT ship (the gate-fix took
  the slot). Carried to tomorrow's 2nd build slot. Today's reinforcement:
  ops_output_stale +7, job_succeeded_with_errors +5, **signal_accuracy_
  degraded ×14 (observe-only warning firing ~2/hr on the losing pool — a NEW
  cry-wolf; ADD a once-per-day / condition-dedup sub-item to the 3-in-1).**

**TOMORROW'S BUILD ORDER (operator's word, post-close, sequential deltas):
① calibration recon-then-fix (#1) · ② shadow one-liner + prod-value test
(#2) · ③ 3-in-1 observability PR (flat-book stale + re-egress dedup + #1104
writer-hardening + accuracy-warn dedup) · ④ stamp the Option-B clock-reset
marker at the #1+#2 SHA.**

## 2026-07-09 MORNING TRIAGE — dispositions recorded (doc-only)

First v5.4-from-disk nightly ran + dead-man pinged GREEN (first live night).
Calibration PRINTED 10:00:03Z: `_overall ev_multiplier 0.5 / pop_multiplier
0.5` (BOTH clamp-floored; ev_calibration_error 65.34 — raw wanted lower;
single _overall bucket, 30d window at n=8) — **raw mode EXITED; EV/PoP now
calibrated ×0.5, the ledgered boundary is CROSSED.** Un-paused + acked the
21:20Z breaker trip + 3 accuracy warnings; fingerprint survived (holds the
QQQ−10 window bd895160 — tonight's suppression test armed).

Dispositions:
- **FILED-TRIGGERED**: #1104 writer-hardening (6/677 rows lost 07-08;
  bundle w/ today's 3-in-1 or next burst) → backlog P2 · reentry_cooldowns
  realized_loss=estimate → FOLDED into the 06-15 backlog item (2-for-2
  live, no new line).
- **ACK-NO-ACTION** (recorded so no re-raise): A6 executor 4×/day = operator
  manual mid-session/post-close cycles, NOT a scheduler defect (scheduled
  cadence is the one-shot) · phase2_precheck = paper-shadow phase-2 gate,
  operator to name it in the scheduler doc.
- **GATED-REOPEN counter: Phase-3 exit over-pessimism now 3rd instance,
  15.5× worst yet** (cohort stop −155 vs broker −10, 07-08). Counter
  **3/[10-15 reopen gate]**. ⚠ **PATTERN NOTE for the reopen session: three
  instances (QQQ 3.3× · SOFI 1.6× · QQQ 15.5×) — the reopen's HEADLINE
  question is "is the cohort stop systematically over-pessimistic on
  defined-risk structures?" (same question SOFI stop-tightness raised).**
  Do NOT act now — gated, outcome-bias-protected; recorded so the reopen
  opens on the pattern.
- **⚠ META-AUDIT DRIFT CAUGHT LIVE (the exact class the 07-08 meta-audit
  targeted): 4 items were ledger-only / prompt-KNOWN-PENDING and had FALLEN
  OFF the actionable backlog.md** — EV-basis recon (LIVE), B1/B2 bucket
  control (LIVE), compounder greedy-stop (LIVE), the #12 06-10-runner batch;
  gap-3(b) existed only as a sub-note. **All re-added to backlog.md this
  session** (P1 for the two live-money, P2 for the rest). Process note: the
  ledger narrative is NOT the actionable list — filed items must land in
  backlog.md or they silently vanish from build-planning.
- **FIX-TODAY queue (pending-today, NOT built)**: the 3-in-1 observability
  PR — flat-book guard on ops_output_stale (A9) + re-egress cross-owner
  dedup (A5) + #1104 writer-hardening (A4). Post-close, one recycle. All
  three health-check/observability-side; zero decision-path risk.
- CONFIRM list checked: F-A1a · reaper · winter-close 2026-10-01 present ✓;
  one-beta tripwire SHIPPED #1139 ✓ (B1/B2 the only open bucket item);
  gap-3(a) SHIPPED #1124 present ✓.

## 2026-07-08 PR-B #1139 ONE-BETA TRIPWIRE — status:SHIPPED

**H8 VERIFIED: squash `7db5a36` (7db5a36dcd4fc1bf58eb67878e387ce2f3c3a2bd)
= origin/main; all three services SUCCESS at that SHA (22:29:35Z);
new-container work flowing by 22:30:04Z (heartbeat OK on the recycled
worker).** PR-A #1138 (`e26bcfe`) merged immediately before — tonight's
midnight nightly runs the v5.4 charter from disk for the first time.

Tripwire live: `concurrent_live_positions_uncontrolled` critical at ≥2 open
LIVE-routed positions, q15 monitor, immediate-egress + receipt.
**VERSION SHIPPED: simplest-correct (ANY 2 live positions), per owner
rationale — bucket refinement stays B1/B2's (still FILED; the alarm is not
the control).** Semantics: alarm-on-onset (position-set dedup; a 3rd
position re-alarms; dedup-read failure alarms anyway; scope-failed cycle
skips). Flag CONCURRENT_POSITION_ALARM_ENABLED default-ON. Disaster-pinned:
never mutates positions/orders/ops_control (test). 12 tests incl. the
production-call-path wiring pin. OPERATOR REMAINING: create the
healthchecks check + set machine env NIGHTLY_AUDIT_PING_URL (PR-A's ping
gate is a logged no-op until then).

## 2026-07-08 META-AUDIT (chat-run, gap register) + TIER-1 PROCESS FIXES — status:SHIPPED (PR-A)

**Meta-audit verdict (full register in session 07-08 ~22:15Z): ship-side
TRUSTWORTHY (ledger↔git 1:1 over 22 commits; 4 spot-checked fixes verified
against RUNNING behavior; zero built-not-wired in the shipped set); intake
side LEAKY (9 goes-silent findings, concentrated pre-ledger 06-10 runners;
2 re-verified STILL REAL); charter side STALE (disk prompt was v5.0/06-12;
scheduled cadence 6 reports/27 nights; 3 silent-empty runs 06-13/14/20).**

PR-A ships: **v5.4 TO DISK** (audit/v5-prompt.md — gap #7; adds A1(iv)
sizing/allocation custody [gap #10] + expected-state: suppression-is-
designed, headless-broker-blind, breaker ritual) · **ping-after-file-exists**
in run-nightly.cmd (gap #8; NO ping existed at all — first wiring;
PowerShell date because %DATE% is locale-formatted and would never match;
gate dry-run verified both directions; operator: create the healthchecks
check + set machine env NIGHTLY_AUDIT_PING_URL, Grace ~26h) · **sweep
convention** (gap #9, CLAUDE.md §7; 07-08 report swept in this PR) ·
**#1104 CLOSED**: operator confirmed reset ~13:45 CT → 18:45:26Z burst =
C1 rotation artifact CONFIRMED; pool-config reopen stays SHUT.

Meta-audit open register (dispositions pending owner triage): expiry-day ×
unpriceable defer seam (live$, own recon) · compounder greedy-stop BREAK
:286 (live$, Tier-2 fix) · EV-basis ∪ fee-unit recon (merged charter,
pre-market session) · F-A1a mechanical guard · one-beta tripwire (PR-B
TONIGHT) · PoP-denom/DTE segmentation (fold into clamp review) · smaller
silents batch (envelope re-egress 13/3h · A9-F4 · F-A2d · N4 · universe_size
mislabel · time-stop/eod-phantoms · N1/N2 · 06-10 A5/A6 partials) · A6
executor-4× question ANSWERED (operator manual cycles, no scheduler change).

## 2026-07-08 POST-CLOSE — #1137 SIGN FIX + FALSE-AGER — status:SHIPPED · THE TRIPLE-GATE POOL SEALED (8/8)

**H8 VERIFIED: squash `2a83174` (2a83174ed78080e329626297d1c9eaab8d8c6bb1)
= origin/main; all three services SUCCESS; worker-background container
20:51:29Z > merge 20:50:03Z — 29 min settle margin before the 21:20Z
ingest (race deadline CI-green-by-21:05Z beaten at 20:49:38Z).**

- **Sign fix live**: `broker_fill_to_mark_basis` (negation, not abs) at the
  live-fill reconciler; QQQ credit pin 1.4167 + SOFI debit 0.2326 + corrupt
  -15.08-shape regression + call-site wiring all test-pinned. **Both
  poisoned rows RE-DERIVED (supervised, read-back)**: bd25cc9d 15.083→
  **1.4167**, 3139842b 3.076→**0.9635**. The live Phase-3 gap dataset (3
  rows: SOFI 0.23 · QQQ 1.42 · QQQ 0.96) is now honest.
- **False-ager fixed**: monitor Part-B persist stamps `last_marked_at`;
  **9** ops_output_stale highs ACKed cause-fixed (2 more had fired since
  the mid-session count of 7; ids in session log).
- **BREAKER — edge-trigger case 2 FIRST LIVE PROOF (21:20:02Z on
  `2a83174`)**: new loss → new window [QQQ −10 bd895160 · QQQ −15 7dd459f8
  · SOFI −40 055ead84] → `edge_trigger:true, tripped:true, paused_written:
  true, fingerprint_stamped:true` — the NEW fingerprint REPLACED the old
  stamp (read-back ✓; MARA 0c54ead8 aged out). Critical receipt:
  webhook_sent=true 21:20:05Z. **Tomorrow's suppression test compares
  against THIS window** — morning un-pause, then a no-close Thursday must
  yield `suppressed_standing_window:true`, no re-pause, no critical.
- **CLOSE #9 INGESTED**: outcomes_created=1, errors=0; typed
  strategy=IRON_CONDOR / regime=normal ✓; gap datapoint born clean
  (its order row was re-derived pre-ingest). **Post-epoch live pool = 8/8.**
- **⚠ TRIPLE-GATE BOUNDARY MARKER — EV numbers change at 2026-07-09
  10:00Z, not tonight**: the pool sealed at 21:20Z tonight, but the relearn
  executes at the scheduled calibration_update (05:00 CT / 10:00Z). First
  real multipliers print then; consumers from that run onward:
  `apply_calibration` → scanner EV/PoP scoring → `risk_adjusted_ev`
  (executor sort) AND `ticket.expected_value` = the #1101 roundtrip gate's
  gross_ev — every gate decision after 10:00Z is on calibrated numbers.
  **⚠⚠ ANNOTATION 2026-07-09 EOD (do NOT erase this marker — correct it):
  this boundary is FALSE. The multiplier COMPUTED + STORED 0.5 at 10:00Z but
  apply_calibration returns ×1.0 at the scan (ev==ev_raw==39.71 verbatim
  07-09) — see the 07-09 EOD entry, fix-queue #1. "Every EV after 10:00Z is
  calibrated" holds only from the SHA where finding #1 ships; re-mark the
  TRUE boundary there.**
  Training pool: {+48, −45, −28, −73, −15, −40, −15, −10} (1W/7L) — expect
  a SHRINK; whether the 0.5 clamp floor binds is the clamp-review question,
  answerable when the multiplier prints. Winsorize: no extreme outlier in
  the live-only pool (max |x|=73) — likely no-action, owner-gated.
- **Accuracy alert**: expected at the first post-ingest health check
  (21:37Z; n=8, hit 12.5% < 0.2) — observe-only; verify in the morning
  ritual.
- **FILED: 06-08 NFLX pre-epoch live close missing from
  learning_feedback_loops** (broker+champion ledger=9 all-time, outcome
  table=8 post-tonight) — pre-epoch-flagged backfill, rides any future PR;
  no effect on the calibration pool (pre-epoch excluded by design).
- Untouched, confirmed: roundtrip gate (EV-basis recon own session — now
  MORE important: the new multiplier flows into that same comparison) ·
  one-beta B1/B2 · reaper · gap-3(b) · #1104 (pending reset-time).

## 2026-07-07 POST-CLOSE — #1135 EDGE-TRIGGER BREAKER — status:SHIPPED

**H8 VERIFIED: squash `be13733` (be137338ac1e89299cc18034bc04c6201427e47f)
= origin/main; BE + worker + worker-background all SUCCESS at that SHA;
container start 22:18:03Z > merge ~22:16Z.** CI green first try. Migration
`20260707221500` (ops_control.streak_breaker_state jsonb, additive
nullable) applied + tracked PRE-merge, read-back verified.

**Semantics live**: re-trip ONLY on window CHANGE. Fingerprint =
CONTENT-based sorted trailing-N outcome row ids, stamped at TRIP time —
**the operator un-pause SQL is UNCHANGED and is sufficient review** (the
window identity was recorded when it paged them). Suppression needs a
POSITIVE match; no-stamp/NULL/malformed/read-error/stamp-failure all
degrade toward tripping. A NEW loss trips instantly (protection intact —
framed in the PR: not loosening, operator-override-respect added). **Flag
`STREAK_BREAKER_EDGE_TRIGGER_ENABLED` DEFAULT-ON** (explicit falsy →
legacy level-trigger byte-identical); wiring test-pinned in
evaluate_and_trip (no #1126-class inert flag). CLAUDE.md §4 runbook
REPLACED (the nightly-re-trip paragraph is retired).

**Baseline + stamp (tomorrow's before/after)**: tonight's 21:20:02Z trip
ran on `5809505` (level-trigger era, PRE-#1135) — window by ingest order =
QQQ −15 (7dd459f8) / SOFI −40 (055ead84) / MARA −15 (0c54ead8); the trip
critical carries the #1134 receipt: webhook_sent=true, egressed_at
21:20:06Z, owner=alert — **#1134's receipt FIRST LIVE EXERCISE, PASS**.
One-time operator-approved stamp EXECUTED post-H8 (tonight's window
fingerprint backfilled via the breaker's own ordering; read-back
confirmed) because the trip predated the stamping code.
entries_paused=TRUE now (tonight's trip — morning un-pause ritual
unchanged).

**TOMORROW'S PIN (first suppression test)**: morning un-pause → 21:20Z
ingest on an UNCHANGED window → expect `suppressed_standing_window: true`
in job_runs.result.streak_breaker, NO re-pause, NO nightly critical,
entries stay armed. A NEW loss instead → trips (also correct). Attribution
clean: #1135 is the only behavioral change in its recycle.

## 2026-07-07 POST-CLOSE — #1134 TAXONOMY + ALERT-INTEGRITY — status:SHIPPED

**H8 VERIFIED (the shipped bar): squash `5809505`
(58095053c10eb76607552355acb1aecc0c2a8a9a) = origin/main; BE + worker +
worker-background all deployment SUCCESS at that SHA; container start
21:10:18Z > merge ~21:08Z; post-recycle job flow confirmed (21:10:01Z
learning_ingest succeeded).** CI green first try (run 28898768862).

**Old→new alert-type map (readers map old→new; historical rows untouched):**
- `force_close` + real submitted close → `force_close` (unchanged, critical,
  immediate egress)
- `force_close` + "Force close FAILED" → **`force_close_failed`** (critical,
  ADDED to immediate-egress allowlist)
- `force_close` + "[WARN-ONLY] … enforcement disabled" →
  **`envelope_violation_warn_only`** (high — was critical; relay path)
- `warn` (envelope block) → **`envelope_violation`** (high; relay)
- `warn` (envelope warn) → **`envelope_violation`** (warning — was the
  out-of-vocab 'medium'; no egress, anti-spam unchanged)
- Writer unification: monitor `_log_alert` now delegates to canonical
  `alert()` (severity normalize medium/warn→warning, error→high; #1100
  retry; owner stamp; receipt) — the which-writer-wrote-it egress lottery
  (today's real force_close on the ≤37-min relay) is closed.

**A9 receipt live**: `metadata.egress_receipt` {webhook_sent, sent,
suppressed_reason, receipted_at} + `egressed_at` stamped post-send;
`[ALERT_RECEIPT]` WARNING both outcomes; FAIL-OPEN test-pinned. **F8 live**:
suggestions_open rolls `rejection_persist_failures` → top-level
`counts.errors` + ok:false; runner folds alert-write-failure deltas into
every job's `counts.errors` (A4-visible; zero-delta byte-identical).

**F3 PATH TAKEN — UNAMBIGUOUS: F3-MINIMAL SHIPPED / F3-FULL FILED.**
Shipped: transient matcher now catches the 18:45Z specimen (httpx
WriteError / "Connection reset by peer" → retries), and a critical/high
whose insert is STILL lost force-egresses the webhook marked
`[DB-ROW-LOST]` (inbox = durable trace; test-pinned). NOT built: the
all-severities durable buffer — warning-class rows still degrade to
logger.exception only; filed as its own item (the critical-class hard
trigger is satisfied by the fail-safe).

PENDING VERIFICATION (tonight/tomorrow): 21:20Z ingest runs on `5809505` —
today's −$15 QQQ close makes the window MARA −15 / QQQ −73 / QQQ −15 →
expected RE-TRIP = **first live exercise of the new immediate-egress path**:
the `streak_breaker_tripped` critical should carry
`metadata.egress_receipt.webhook_sent=true` + `egressed_at` + an
`[ALERT_RECEIPT]` worker-background log line. Also watch: first
`envelope_violation`-typed rows at the next violation; the designed
channel-2 INFO replacing the legacy-mode WARNING; morning un-pause ritual
unchanged.

HYGIENE (filed 07-06, from the M4 CI failure): `test_weekly_report_win_rate.py`
replaces 18 modules (incl. cash_service, options_scanner) with MagicMocks in
sys.modules at import time and NEVER restores — any later lazy in-test import
binds a mock (green single-file local, red full-suite CI; cost tonight: one
red CI round on #1132). M4's test file now binds real modules at import with a
de-poison guard; the POISONER itself is unfixed and has pre-existing order
sensitivity (6 capital-basis failures in explicit weekly-first order — never
CI's alphabetical order). Follow-up: convert to conftest fixture/unpatch;
grep for siblings doing module-level sys.modules assignment without restore.

## status:reported — 2026-07-08 NIGHTLY run (report `audit/reports/2026-07-08.md`)

Window 07-06 05:01Z → 07-08 05:01Z — the 15-day flat stretch ENDED. Both workers
SUCCESS @ `be137338` (#1135) = origin/main HEAD (H8 clean; start 07-07 22:17:35Z).
**First LIVE fill since 06-30:** QQQ iron condor `386a39fe` (aggressive cohort
`3d289dca`), entry 14:37Z (off-schedule executor run, filled 1.49 credit vs 1.41 limit,
+$8 improvement, 76ms), force-closed 17:45Z on `intraday_stop_loss`, realized −$15.00.
`entries_paused=TRUE` since 07-07 21:20Z (breaker re-trip; **operator un-pause required**).
Live champion now 1 win / 7 post-epoch closes, −$168, hit-rate 14.3% (Brier 0.296).
⚠ **RUN LIMITATION:** alpaca MCP tools absent — broker not snapshot-read; live trade
DB-corroborated (execution_mode=alpaca_live + reconciler + is_paper=false), not
broker-confirmed. Equity/OBP not re-read (last $2,093.74 07-06, −15 QQQ ⇒ ≈$2,078.7 DB-derived).

- **[A4 2026-07-08 — FINDING] `close_fill_gap` sign-convention bug corrupts every
  live-close gap_fraction (poisons the deferred Phase-3 reopen gate).** The #1102
  instrumentation computes `gap_fraction=(fill−cross)/(mid−cross)` with NO sign normalization
  (`services/close_fill_gap.py:62-78`). On the LIVE/reconciler path
  `brokers/alpaca_order_handler.py:571` forces `fill=abs(filled_avg_price)` (+1.64) while
  `cross`/`mid` are stamped SIGNED (`paper_exit_evaluator.py:1913,1976` from `current_mark`
  −1.74 / corroboration −1.98). QQQ 07-07, the FIRST live full-quad close, stored
  fraction **15.0833** (=3.62/0.24) vs the correct-sign **1.417**. Internal/shadow exit
  path passes signed fill → self-consistent; only the LIVE path is wrong. Test fixture
  (`tests/test_close_fill_gap.py:44-47`) uses consistent-positive signs (SOFI→0.2326) → CI
  green while production is corrupt = the #1126/9a2cef1 test-green-production-wrong class
  (§9 never-do). Since #1102 shipped: 0 usable live gap_fractions (QQQ corrupt, SOFI-07-01
  shadow null). FIX: one line — sign-match fill at `:571` (drop `abs()`) or abs cross/mid at
  `:567`; add a mixed-sign fixture. RISK zero (observe-only, best-effort try/except).
  CONFIDENCE high (DB arithmetic + code both dispositive). Blast-radius note: the deferred
  Phase-3 "two-quote confirmation" safety fix (reduces over-pessimistic premature
  force-closes: QQQ −49-est/−15-fill, SOFI −65/−40) is GATED on this now-broken distribution.
- **[A5 2026-07-08 — FINDING] Standing-envelope alerts re-egress to the operator phone
  every 15-min monitor cycle (no content-dedup) — cry-wolf burying criticals.** While one
  live QQQ was held, "QQQ is 100% of risk (limit 40%)" was re-written HIGH and relay-egressed
  every cycle → **13 phone egresses in 3h** (14:45–17:45Z) + 26 non-egressed medium
  expiry/sector; the `force_close` critical egressed 18:07Z, AFTER them.
  `risk/risk_envelope.py:316-354` appends fresh each check; `intraday_risk_monitor.py:449-496`
  no changed-since-last-cycle guard (concentration severity default `"block"`→HIGH); relay
  poller `ops_health_service.py:1431` suppresses only per-row already-egressed stamps
  (`:1479`), NO type+symbol+content fingerprint. **Confirmed persists post-#1134** (rename
  kept concentration→high→relay). FIX (additive): apply #1135's edge-trigger principle to
  egress — suppress re-egress of an unchanged (type,symbol,bucket) standing condition within
  a hold. RISK zero (egress-only). CONFIDENCE high.
- **A1/A3/A7 UNCHANGED** (raw mode holds at 7/8 post-epoch live; ingest clean errors=0;
  QQQ condor hold 3h07m = ledgered cohort-stop-dominates-condors). **A2** — GATED Phase-3
  over-pessimism class exercised a 2nd time (QQQ −49 corroborated est vs −15 fill; cited,
  not re-found); its reopen data is the A4 bug. **A6** — binding constraint = EV-after-cost
  ($15 roundtrip floor rejected aggressive `38d57d55` at net +14.45), not cadence; OPEN Q:
  executor ran 4× on 07-07 (14:37 exec-1, 16:30/17:59/18:47 exec-0) vs one-shot/day — likely
  operator retries around the un-pause, confirm.
- **A8** roundtrip-reject class now exercised LIVE (aggressive +14.45 = edge-lost;
  neutral/conservative = spread-eaten); reject-was-a-win again (QQQ passed→−15). Per-gate
  marker still backlog RESEARCH. **A9** no new integrity finding (all alerts honest; the
  egress noise is honest→A5; ops_data_stale silent — market open). **A10** no new instance;
  winter-close blind hour (Nov) still queued; no fixture inside 45d.

VERIFICATIONS CLOSED THIS RUN:
- ✅ **M4 post-fix healthy scan** (07-07): 0 `micro_tier_underlying_too_high`, 76 syms, 0
  `alpaca_options_buying_power_query_failed`. The 07-06 inverted-universe incident's zero was
  the incident's, not the gates' — M4 (#1132) HELD on the next RTH day.
- ✅ **CVX IV-eligibility**: scanned 07-07, `iv_rank_insufficient_history`=0, rejected on
  real `spread_too_wide_real`. **GLD**: scanned clean (no strike/IV errors). M1/M2/CVX closed.
- ✅ **Breaker re-eval**: 07-06 21:20Z re-tripped; 07-07 21:20Z re-tripped on NEW QQQ−15
  (window rolled QQQ−73→QQQ−15). #1134 streak-breaker critical carried `egressed_at`
  21:20:06Z (receipt partial-confirm).

PENDING VERIFICATIONS (2026-07-08 → next session):
- **⚠ OPERATOR: `entries_paused=TRUE`** (07-07 21:20Z, QQQ−15/SOFI−40/MARA−15). Un-pause
  before the next RTH else the 16:30Z staging proof no-ops.
- **#1135 edge-trigger FIRST SUPPRESSION test — STILL PENDING**: 07-07 21:20Z ran on #1134
  (pre-#1135 deploy 22:17Z) AND a new loss landed (window changed→tripped). The distinctive
  `suppressed_standing_window` path fires 07-08 21:20Z IFF operator un-pauses and no new loss.
- **#1134 first `envelope_violation` typed rows + egress receipt** on the next position-hold.
- **First CORRECTED `[CLOSE_FILL_GAP]`** once the A4 sign fix ships (expect ~1.4, not 15.08).
- **A6 executor-cadence**: confirm whether 4×/day is scheduled or operator-driven.

## status:reported — 2026-07-09 NIGHTLY run (report `audit/reports/2026-07-09.md`)

Window 07-08 05:01Z → 07-09 05:01Z. Clocks grounded (DB 05:01:23Z = broker 01:02 ET ✓).
**Broker READ DIRECTLY this run** (MCP present): equity $2,067.87 = cash = OBP (settled,
flat, 0 positions); 07-08 day −$10.43. H8 CLEAN: all THREE services SUCCESS @ `7db5a36`
(#1139) 22:29:35Z; movers off the prompt pin: `e26bcfe` #1138, `7db5a36` #1139.
**POOL SEALED 8/8** (1W/7L, −$178): live QQQ IC `305e476a` staged 17:41Z (ev 41.75 / pop
0.6425 raw), force-closed 18:00:11Z after ~15min — cohort stop on corroborated −$155 vs
broker fill −$10 (15.5×; Phase-3 class instance #3, counter 3/10-15). Breaker: designed
edge-trigger case-2 trip 21:20Z (window CHANGED: QQQ−10 in / MARA−15 out; fingerprint
stamped; receipt egressed). `entries_paused=TRUE` — **operator un-pause required**.
**CALIBRATION BOUNDARY: first calibrated multipliers print 07-09 10:00Z** (07-08 run was
sample 7 insufficient) — the three 8th-close checks are DUE.

- **[A9 2026-07-09 — FINDING] `ops_output_stale` paper_positions arm = standing HIGH
  false alarm, UNCLEARABLE while the book is flat + paused; the v5.4 STATE "RESOLVED"
  verdict is half-true.** 11 HIGH rows 07-08 (13:07→22:07Z, self-superseding; latest 2
  unresolved, 176→177h and climbing) assert a dead mark-refresh loop while Part-B wrote
  `mark_corroborated −3.04` the same hour. Root: `MAX(last_marked_at)` = 07-01 13:00Z —
  BOTH July QQQ holds ran pre-#1137 code (deploy 20:50Z 07-08 was post-close; QQQ 07-08
  row `last_marked_at=NULL`), and a flat book gives the live fix nothing to stamp. The
  §8 flat-book caveat is DOCUMENTED at `ops_health_service.py:149-152` but UNGUARDED
  (`:527-548` has no open-positions check). Projected ~48 HIGH rows/day for the whole
  pause (0 egressed — ops_* relay-skipped; poisons H11 triage). FIX (additive): flat-book
  guard — `open_n=0` → status `flat`/INFO, never `stale`/HIGH. RISK zero. CONF high.
- **[A5 2026-07-09 — FINDING, broadens the ledgered 07-08 re-egress item] the
  duplicate-egress class includes `egress_owner='alert'` writers, not just the relay.**
  `job_succeeded_with_errors` for the ONE 19:02Z scan run (`run_id ef8a2d4e`) re-wrote +
  re-egressed at 19:07/20:07/21:07/22:07Z — 4 receipted phone hits for one condition.
  The queued dedup fix must fingerprint the CONDITION (run_id / type+symbol+bucket)
  across BOTH owners or it fixes half the class. Watch, same shape:
  `ops_signal_accuracy_degraded` re-writes ~2/hr while hit<0.2 (designed first fire
  07-08 21:37Z at n=8 hit 0.125; warning-only, not egressed — row noise).
- **[A4 2026-07-09 — FINDING, small] rejection-persist retry loses rows when the retry
  hits the same dead connection — first data loss since #1104.** 19:02Z broken-pipe
  burst: 7 inserts recovered, **6 lost for good** (SLV/ISRG/C/HOOD/PLTR/AMGN, broken pipe
  on retry too); `counts.errors=6` with `result.errors=NULL` (count surfaced, items only
  in Railway logs). The #1100 detector caught it and it reached the phone with receipt —
  the chain WORKED; the residual is the writer. FIX (additive): reconnect-then-retry or
  ×2 backoff + stamp failed symbols into `result.errors`. Impact 6/677 (0.9%) of A8's
  counterfactual data. CONF high (logs + counts agree).
- **[A2 2026-07-09 — refinement of the 06-15 deferred cooldown item; metadata-only]**
  `reentry_cooldowns.realized_loss` stores the trigger-time corroborated ESTIMATE, not
  the fill — now 2-for-2 on live closes post-#1080 (−48.99 recorded vs −15 realized
  07-07; −155 vs −10 07-08). Bench durations unaffected; magnitude readers misled.
- **A1** EV-basis recon item (KNOWN-PENDING) reproduced with dispositive numbers on the
  LIVE cohort: aggressive QQQ 16:00Z stamped `net_ev +35.62` but gate-BLOCKED; gate log
  basis `gross_ev 42.14 − round_trip 154.00 = −111.86` (neutral twin; stamped net_ev
  NULL). Two bases disagree on the same candidate; it demonstrably timed the live entry
  (16:00 block → 17:41 pass). Urgency ↑ post-boundary. **A6** unchanged (677 rejections,
  mix stable; iv-seasoning 40/10syms = 06-17 adds, eligible ~mid-Aug; Polygon DARK on 8
  liquid QQQ legs 19:03Z, truth-layer priced — #1052 saved staging). **A8** SOFI sentinel
  quiet; gate discriminated (aggressive edge-passed, shadows spread-eaten). **A10** no
  new instance (counter 2). **A7** dormant, fills 3/10.

VERIFICATIONS CLOSED THIS RUN:
- ✅ **#1134 typed rows + delivery receipt — BOTH egress owners**: 2 `envelope_violation`
  HIGH (17:45/18:00Z) relay-egressed with `egressed_at`; `job_succeeded_with_errors`
  carried full `egress_receipt {sent, receipted_at, webhook_sent}` (alert-owner).
- ✅ **Cooldown bench post-stop**: 19:02Z pending aggressive QQQ NOT staged at the 19:03Z
  executor run (benched until 07-09 13:30Z) — the bench gate exercised, correct.
- ✅ **#1071/#1058 brake line**: `[EQUITY_STATE]` used broker-true −10.43 over the $0
  open-book proxy — tighter value chosen, correct.

PENDING VERIFICATIONS (2026-07-09 → next session):
- **⚠ OPERATOR: `entries_paused=TRUE`** (07-08 21:20Z window QQQ−10/QQQ−15/SOFI−40);
  un-pause is operator-only.
- **CALIBRATION BOUNDARY 07-09 10:00Z**: expect raw-mode EXIT (first real multipliers on
  8 live closes); run the clamp(0.5-floor) + winsorize reviews (owner-gated). Attribute
  any post-10:00Z scoring/gate shift to the multiplier FIRST.
- **#1135 FIRST SUPPRESSION — decisive test 07-09 21:20Z**: book flat + paused + no new
  close ⇒ expect `suppressed_standing_window: true` and NO new critical. A re-pause/
  critical on the UNCHANGED window = edge-trigger FAILURE (flag hard).
- **First NATIVE post-#1137 `[CLOSE_FILL_GAP]` stamp** on the next live close (the 07-08
  quad was corrected in-DB, not code-native).
- **First post-#1137 hold stamps `last_marked_at`** (currently MAX=07-01 13:00Z; the fix
  is live but UNEXERCISED — this is the condition the A9 finding's "RESOLVED" verdict
  hangs on).
- **#1139 one-beta tripwire**: live but unexercisable at ≤1 position; fires only if 2+
  concurrent live positions ever exist (that event ALSO reopens A2's settled condition).
- **A6 executor cadence** (3rd ask): scans 16:00/17:41/19:02Z + execs 16:30/17:43/19:03Z
  on 07-08 — scheduled multi-cycle or operator-driven?
- **phase2_precheck naming**: 4×/day green job outside the doctrine's scheduler map
  (free-look, no anomaly) — one-line operator naming requested.

## status:reported — 2026-07-10 NIGHTLY run (report `audit/reports/2026-07-10.md`; first v5.5 eleven-area nightly)

Window 07-09 05:01Z → 07-10 05:01Z. DB clock grounded 05:01:05Z; **broker-blind run** (Alpaca
MCP absent — equity ≈$2,067.86 DB-derived, hypothesis). ZERO criticals (H11 clean). Zero-trade
day: 3 SOFI forks (ev_raw 39.71) all blocked `ev_below_roundtrip_cost`; book flat; pool stays
8/8 (1W/7L, −$178); gap counter 3/10–15. H8: HEAD moved `655c9aa`→`d275d28` (4 movers named —
#1144/#1145 docs, **#1147 `168a752` code**, `d275d28` doc-wrap runtime-inert, deployed 05:03:37Z
DURING the audit); all 3 services SUCCESS @ `d275d28`; 5 recycles 22:54→05:03Z, 0 orphaned jobs.

- **VERIFICATIONS CLOSED**: ✅ **#1135 FIRST SUPPRESSION DB-PROVEN** — 21:20:03Z ingest result
  verbatim `suppressed_standing_window:true, tripped:false, paused_written:false` on the
  unchanged 07-08 window; `entries_paused=false` (operator un-pause 11:53:33Z); fingerprint
  intact. Edge-trigger case 3 exercised — breaker fully validated, entries ARMED. ·
  ✅ **EDGE-TRIGGER FULLY PROVEN IN PRODUCTION; the morning un-pause ritual is RETIRED**
  (07-10 AM confirmation — all four silence conditions held: no streak_breaker email overnight ·
  `entries_paused=false` · `streak_breaker_state.last_tripped_fingerprint` intact
  [055ead84/7dd459f8/bd895160, tripped_at 07-08 21:20Z] · 21:20Z 07-09 ingest
  `suppressed_standing_window:true`). This was the last morning it needed checking as a ritual
  item; future mornings assume armed unless a flag-condition fires. ·
  ✅ post-recycle learning chain clean (21:00–22:00Z all green, errors=0) · ✅ universe 78 ·
  ✅ A6-cadence + phase2_precheck = ACK'd dispositions observed again, closed. ·
  ⚠ STATE CHANGE: F-FREE-1 scrub MERGED via #1145 `f6b204c` (was "PR pending"); operator items
  (history cleanup + secret-scanning) still open.
- **[A5 2026-07-10 — quantified continuation, urgency ↑, no new class]** ZERO-trade day wrote
  ~53 warning+ alert rows; `job_succeeded_with_errors` re-egressed the SAME stale run
  `ef8a2d4e` 6 more times (13:07→18:07Z) = **10 cumulative phone hits/2 days for one condition**,
  self-terminating only at the detector's ~24h lookback; ops_output_stale ×10 HIGH (unclearable,
  `MAX(last_marked_at)` still 07-01); accuracy ×20; chain_mechanics ×14; autopilot costume ×3
  (`distinct_error_classes=["EntryRoundtripCostExceedsEV"]` — 100% designed NOs as "failed",
  metadata-proven). **The 3-in-1 observability PR slipped a 2nd consecutive build day.** A9
  rider: the alert text "silently masked failure" is self-falsifying by its 10th delivery —
  message-honesty fix rides the dedup PR.
- **[A1/A3 2026-07-10 — structural arithmetic, exhibit for the OWNER-GATED clamp review; no
  action, no loosening]** From 07-10 16:00Z gate-pass requires `ev_raw ≥ 2×(15 + roundtrip)`:
  QQQ-IC class (cost ≈4.8, ev_raw 41.75) passes barely (thr ≈39.6); SOFI class (cost >24.7)
  needs >79. Expected entry volume ≈ zero-to-rare = do-no-harm working, BUT couples: multiplier
  rises only via pool improvement → pool grows only via closes → closes need entries. Not a
  strict deadlock (30d window ages June losses out ~early-Aug; 0.5-floor review is the owner
  lever). Hand to the clamp review as one exhibit with the funnel arithmetic.
- **[A11 2026-07-10 — proposal]** Run-boundary integrity: pin running SHA at audit START and
  END, name mid-run movers as a header field (tonight's `d275d28` landed 2 min into the run;
  caught only by late deployment listing). Also recorded: scheduled session has NO shell
  (subagents included) — git verified via `.git` metadata only.

PENDING VERIFICATIONS (2026-07-10 → next session):
- **FIRST CALIBRATED PRODUCTION EV — 07-10 16:00Z scan**: persisted `ev == ev_raw × 0.5`
  (re-scoped claim: proves persisted-ev + final gate ONLY; selection/sizing RAW). Option-B clean
  observe lines start counting at the same scan. `POP_CLAMP_ENGAGED` never firing is
  dormant-by-arithmetic, NOT broken (pop_mult ≤ 1.0).
- **First native [CLOSE_FILL_GAP] + first post-#1137 `last_marked_at` stamp** — need a live
  close / held book (none this window).
- **#1139 one-beta tripwire** — unexercisable at 0 positions; fires only at 2+ concurrent live
  (that event also reopens A2's settled condition).
- **3-in-1(+accuracy-dedup) observability PR** — TOP-1 again; verify IF shipped, don't re-find.
