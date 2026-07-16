# EXTERNAL FULL AUDIT v1.5R — COMPLETED RESULTS

**Executed:** 2026-07-15 (post-close) · **Charter:** `docs/review/external-full-audit-v1.5-current.md` (BRIEF — this file is the completed report; the brief remains the charter).
**Immutable code baseline audited:** `bef2cdd60edbee8642fa043192fd982d4bfe4436`.
**Method:** read-only code trace at bef2cdd + read-only runtime adjudication (this session has Supabase/Railway/Alpaca; the external brief did not — runtime evidence is labeled separately and never upgraded to code proof).

Proof labels: `VERIFIED-CODE` · `VERIFIED-TEST-REACH` · `ATTESTED-RUNTIME` (direct DB/Railway/broker read this session) · `INFERRED` · `RUNTIME CHECK — NOT RUN` · `NOT PROVEN`.

---

## 1. Step-0 grounding & immutable baseline

- host `2026-07-15 22:43:18Z` ≈ DB `22:43:20Z` (CT 17:43 / ET 18:43) ≈ broker `18:43:21 ET` — agree ~2s; **market CLOSED**, next open 2026-07-16 09:30 ET.
- **origin/main moved during the engagement:** `623044d` → **`d18dd52`** (#1208 "Add files via upload", 22:41Z). `bef2cdd..d18dd52` = **2 docs files only** (`external-full-audit-v1.5-current.md` #1207 + `…-execute-adjudicate-integrate-prompt.md` #1208), **zero code/config/migration** → **production-code baseline is still `bef2cdd`** (VERIFIED-CODE). Deployed SHA on BE + both workers = `623044d`, SUCCESS 09:42Z (docs-only recycle over bef2cdd; the 07-15 falsifier code is bef2cdd-identical).
- Worktree `wt-reconcile-0714` production `.py` == bef2cdd (byte-diff = docs + `test_docs_consistency.py` only) — reads are authoritative.
- Runtime falsifiers already graded PASS this session (ATTESTED-RUNTIME): #1200 SOFI natural falsifier PASS; #1201 calibration PASS (8 live outcomes, ev×0.5/pop×0.5); #1201 thesis PASS (execution-mode split, alpaca_live 5/7 distinct from routing); tape 9 blobs/day all `complete`; `decision_runs.git_sha='unknown'` 12/12.

### 1a. Canonical denominators (kept separate everywhere — never "live n")

| Denominator | Value | Label |
|---|---|---|
| All broker-live closes, total history | **9** | ATTESTED-RUNTIME/ledger (8 post-epoch in v3 + 1 pre-epoch NFLX 06-08 walled by `CALIBRATION_EV_EPOCH`, not in the v3 pool) |
| Post-epoch broker-live closes (calibration pool) | **8** | ATTESTED-RUNTIME (`learning_trade_outcomes_v3 is_paper=false`) |
| Broker-live thesis rows, total | **12** | ATTESTED-RUNTIME (`position_thesis_outcomes execution_mode=alpaca_live`) |
| Broker-live **scored** thesis rows | **7** (5 hit / 2 miss = 5/7) | ATTESTED-RUNTIME |
| Broker-live thesis rows **in-progress** | **5** | ATTESTED-RUNTIME (future expiries; `in_progress` ≠ position-open) |
| Phase-3 instrumented/eligible live-close fills | **~3 of 10–15** | ATTESTED-RUNTIME (2 with computable `gap_fraction`) |

Realized broker-live P&L = **1W/7L, ≈ −$178** post-epoch (ATTESTED-RUNTIME). `live_eligible` (routing) ≠ `alpaca_live` (broker execution) — never conflate.

### 1b. Credential disposition (B9)
`OPERATOR-ATTESTED: affected credentials rotated and revoked; exact classes/date not persisted in this audit to avoid fabricating provenance.` Recorded by credential class only — no value, fragment, fingerprint, account identifier, or secret-shaped text. This is a **distinct** disposition from the older `F-FREE-1` (`LOCAL-ONLY-FAKE`, no rotation warranted); the two are not conflated. No independent provider-side verification is claimed.

## 2. Executive verdict

Current broker-live thesis accuracy is **directionally encouraging (5/7 scored at the 2026-07-15 census) and not yet falsified, but signal edge is NOT PROVEN at this sample size** (tiny-n; thesis-hit ≠ net economic edge — realized broker-live profitability is **1W/7L**, and execution, exits, costs, and cross-structure EV semantics remain the leading observed loss mechanisms). Shadow results are NOT used as live evidence, and the economic-ranking signal is **not** sound: A6-3 shows credit/debit/condor candidates are ranked on incoherent EV/probability bases. Two live-entry position reads fail OPEN (`except → return []`) — a *transient/selective* failure or false-empty read followed by successful downstream staging can produce an unsafe entry (`F-MIDDAY-POSITION-READ-FAILOPEN`, 2 sites; the strongest new finding; see §9 for the non-inevitable causality). Capital-comparability is degraded: all three policy-lab portfolios (incl. the live-eligible champion) use a ~$100,000 basis vs the ~$2,067.86 live book (**~48×**) at the dated observation, so raw-dollar P&L / capacity / feasibility / sizing / selected samples are not live-tier comparable. Observe-window instrumentation is largely non-durable (4 of 5 windows INFO/logs-only). No CRITICAL fires on live money today (book flat, post-epoch n=8 live closes, learning-mode). No control-loosening is recommended anywhere. **The single first operator decision** is the shadow-capital epoch (A6-2; see §6 A6-2) — a versioned live-tier observe-only cohort, NOT an in-place re-seed of historical rows. Audit-maturity is `INFERRED` qualitative (see §12 scorecard); it is not a verified profitability/reliability measurement.

## 3. Current-state reconciliation (code vs packet/attestation)

| Claim | Code state (bef2cdd) | Runtime/attestation | Disagreement | Label |
|---|---|---|---|---|
| #1200 E19-2A narrow scope | obs_scope/selected_for_entry=false/exec=not_executed stamped (`fork.py:1101-1136`) | SOFI 14:32Z falsifier PASS | none | VERIFIED-CODE + ATTESTED-RUNTIME |
| #1201 shared fetch + headline | single predicate delegation (`calibration_service.py:397-404`); thesis split (`thesis_tracker.py:66-97`) | calibration + thesis PASS | none | VERIFIED-CODE + ATTESTED-RUNTIME |
| #1199 tape | bytea hex symmetric, atomicity, capture_partial (`blob_store.py:74,333`) | 9 blobs/day complete | none | VERIFIED-CODE + ATTESTED-RUNTIME |
| git_sha stamped | reads only `GIT_SHA` (Dockerfile `ARG GIT_SHA=unknown`) | 12/12 rows 'unknown' | provenance exists (`RAILWAY_GIT_COMMIT_SHA`) but unwired | VERIFIED-CODE + ATTESTED-RUNTIME |
| shadow capital | `or 100000` literal (`fork.py:210`, `evaluator.py:251`) is inert — stored net_liq **is** $100k | all 3 portfolios net_liq=$100k; live $2,067.86 | packet "shadows near $100k" understates: champion too | VERIFIED-CODE + ATTESTED-RUNTIME |
| condor EV model | code default `strict`/0.50/1.00 (`options_scanner.py:214-216`) | worker service ran the `tail` model (non-secret config flag observed on the worker env, 2026-07-15 ~22:50Z) | code-default ≠ deployed | code = VERIFIED-CODE; deployed value = ATTESTED-RUNTIME (single prior-session read; NOT re-read in this lane). Not re-verified per-worker → `RUNTIME CHECK — NOT RUN` on the *background* worker |

## 4. E1–E20 exclusion-integrity table (Pass 1)

| E# | Disposition | Seam (bef2cdd) | Note |
|---|---|---|---|
| E1 | **PASS** | `calibration_service.py:517/533/240/648` | 0.5 floor holds; segment admits n≥3 with no apply-time recheck (see A3-3); applies post-score |
| E2 | **CONDITIONAL** | `paper_endpoints.py:1343-1352` | per-contract fix runs only for shadow OR `GATE_QTY_FIX_LIVE_ENABLED=1` (default OFF) → **live-inert**; qty=1 byte-identical |
| E3 | **PASS** | `streak_breaker.py:236-306,142` | content-fingerprint edge-trigger; fail-closed-pause; no code clears `entries_paused` |
| E4 | **PASS** (code) | `close_fill_gap.py:81-99`; `alpaca_order_handler.py:659-665` | signed-mark negation; QQQ 15.08→1.417 corrected in-place (A7-2) |
| E5 | **PASS** | `cash_service.py:46-74` | None OBP in LIVE → 0.0 + block + critical |
| E6 | **CONDITIONAL** | `alpaca_order_handler.py:429-502,583` | safe (needs_manual_review = critical hold, tracked, not double-fired) but the "routed-**success**" framing is inverted vs code=critical; partial-close = abort-and-defer |
| E7 | **PASS** | `paper_autopilot_service.py:873-897,451` | bias re-rank on full pending set, then slice; dead route early-returned |
| E8 | **CONDITIONAL** | closures OK; **4th sentinel** `paper_autopilot_service.py:1328-1343` | see §9 fail-open cluster |
| E9 | **PASS** | `options_scanner.py:359-402` | retry then re-raise + surfaced to job_runs |
| E10 | **PASS** | `alpaca_order_handler.py:614-628`; `thesis_tracker.py:235` | close_reason enum + price_basis honest sentinels |
| E11 | **PASS** | `thesis_tracker.py:241`; `scheduler.py:75` | wired daily 17:00 CT; observe-only |
| E12 | **CONDITIONAL** | `ev_calculator.py:104/262/568` | PoP fix ✓; credit EV≡$0 (⑤); **condor default = delta-tail heuristic** (A6-3) |
| E13 | **PASS** | `test_ev_raw_coalesce_drift_guard.py:32` | COALESCE(ev_raw,ev) drift-guarded |
| E14 | **PASS** | `fork.py:630-635,704,63-92` | clone rescales max_loss to clone contracts; prerejection crosses the status gate |
| E15 | **PASS** | `ops_health_service.py:46-69`; `intraday_risk_monitor.py:132-141` | ET wall-clock; **but holiday-blind, see A10-1** |
| E16 | **PASS** | `blob_store.py:333,74`; `workflow_orchestrator.py:15` | 7+morning manifests; symmetric bytea; real-JSON+origin-injected test |
| E17 | **PASS** | `prequential_validator.py` | zero production callers (study tool) |
| E18 | **PASS** | `ev_calculator.py:104`; `calibration_service.py:687` | PoP clamped at source + post-multiplier |
| E19 | **PASS** | `fork.py:1059-1136,1139` | narrow scope stamped; fail-closed sentinels; frozen baseline |
| E20 | **PASS** | `logging_setup.py:53`; F-WINDOW-1 = prefix-disambiguated | inert identifier drift, no runtime collision |

**Contradictions to closure (top priority):** (1) E8 sentinel class NOT fully eradicated — 4th read `[]`-on-failure; (2) E2 qty-fix live-inert; (3) E6 framing inverted (safe); (4) E12 condor principled EV env-gated; (5) E20 F-WINDOW-1 = inert drift, not a new collision.

## 5. W1–W5 observe-window table

| W | Flag (default OFF) | First-valid boundary | Emitter post-#1198 | Durable sink | Measures arm? | Bypass | Status |
|---|---|---|---|---|---|---|---|
| W1 | `GATE_QTY_FIX_LIVE_ENABLED` | `655c9aa` (WARNING, pre-#1198) | Yes (WARNING) `paper_endpoints.py:1370` | logs-only (flip line) | partly; degenerate at qty=1 | none (centralized `_stage_order_internal`) | **RUNNING (sample-starved)** |
| W2 | `RISK_BASIS_MAX_LOSS_ENABLED` | #1198 `1386834` | INFO `risk_basis_shadow.py:40,50` | logs-only | yes; would_flip real only at RBE (1/3) | 3 self-gated consumers | **START-UNVERIFIED** |
| W3 | `BUCKET_CONTROL_ENFORCE` | #1198 `1386834` | INFO + **durable would-block alarm→risk_alerts** (`:1082-1095`, subset) | mostly logs-only | partial: reservation **ORDER** exists within one executor process/cycle (`bucket_control` keys on the bucket label), but **no durable reservation identity and no shared scan→executor cycle/decision identity** (`DecisionContext.decision_id` is a fresh UUID; the runner does not pass `job_runs.id` to the handler; the executor heartbeat uses a cohort label as `cycle`) → **retry and cross-job joinability UNPROVEN** (F-WINDOW-1b) | **real** (`:636` + endpoint stages bypass) | **START-UNVERIFIED** |
| W4 | `CALIBRATION_APPLY_AT_SCORING` | #1198 `1386834` | Yes `[APPLY_ORDER_SHADOW]` | **semi-durable** (count→job_runs.result, mislabeled `universe_size`) | yes (frozen vs calibrated top-5) | single midday call site | **RUNNING** |
| W5 | composed arm | — | none | none | — | — | **UNSTARTED** |

**Biggest W gap:** 4 of 5 windows' arm-decision evidence is INFO/logs-only → silently dropped pre-#1198 (born 07-11) and Railway-retention-bounded even now; only W4 reaches a semi-durable sink and W3's cap-breach alarm is durable. "How many live decisions would arming flip" is not queryable.

## 6. A1–A10 (Pass 1/2/3)

**A1 PROFITS.** Replay runner **NOT buildable today** — *A1-1 (MED, EXTENDS-E19-2B):* capital/OBP/tier/open-book state + `ev_raw` are never captured (only market-data + regime/symbol/ranked_candidates), and `ReplayTruthLayer.from_decision_id` has zero production callers. The raw-vs-calibrated ordering counterfactual is unanswerable from the tape. *A1-2 (NOTE):* ⑤ make-vs-fetch is not input-starved — the chain is captured (fetch reconstructable; make coarse). Pass 3: the replay runner is the top A1 extension, gated on A1-1 capture + A5-2 origin.

**A2 LOSSES.** *A2-1 (MED, EXTENDS-P0-A):* the idle-watchdog writes `status='watchdog_cancelled'` **unconditionally** even when `cancel_order` raises because the order just filled (`alpaca_order_handler.py:846-876`); the next poll excludes `watchdog_cancelled` → the fill is un-polled → suggestion re-executable → new row → new `client_order_id` → **double-entry** (loud via ghost sweep, so MED). *A2-2 (LOW):* `max_loss_total` (#1166) is scalar-safe per consumer (position-total, no ×qty/sign bug); canonical-position gap (signed ratios/multipliers/greeks behind the scalar) remains the P1 target. Assignment/partial-close DEFERRED-DORMANT (0 open credit near expiry).

**A3 SELF-LEARNING.** F-A3-4 shared fetch PASS (None=fail/[]=empty/[…]=rows, live-only). *A3-1 (LOW, NEW):* `thesis=hit ∧ realized_pnl<0 ∧ close_reason=stop ∧ execution_mode=alpaca_live` is readable with no cohort/basis leakage (on `position_thesis_outcomes`), **but `learning_trade_outcomes_v3` has no `close_reason`/`thesis_outcome` column** → the premature-stop signal is un-consumed by any multiplier. *A3-2 (LOW, EXTENDS-segment-n):* DTE bucket is **inert** — the fetch SELECTs no DTE source → every outcome `dte_bucket='unknown'` → redundant `_all` twin; adding a DTE column would activate a double-count trap. *A3-3 (LOW, EXTENDS-E1/segment-n):* `apply_calibration` never re-checks `sample_size` → a 3-sample segment applies un-shrunk (latent; live blob `_overall`-only, n=8). Prequential = study tool (zero callers).

**A4 SELF-SUSTAINING (instrument-integrity headline).** Job classification wired (`runner._classify:46-68`, partial iff users_failed/counts.errors); dead-man fail-safe; bytea symmetric. *A4-1 (MED, = GIT-SHA):* capture reads `os.getenv("GIT_SHA")` only; `RAILWAY_GIT_COMMIT_SHA` exists and is used by `/version` + `backtest_identity` — one-line fallback fix. *A4-2 (MED, NEW):* `decision_runs.input_hash/features_hash` are written but `verify_*` has **no production reader** → determinism regressions are silent. *A4-3 (NOTE, negative result):* no OTHER non-JSON type crosses supabase-py's JSON layer (only the #1199-fixed blob). Instrument-integrity list in §8.

**A5 EFFICIENCY.** *A5-1 (NOTE):* `FORECAST_V4_ENABLED` gates zero compute (doubly inert). *A5-2 (LOW, NEW):* `decision_runs` has no origin/trigger column → scheduled vs operator vs replay cycles are indistinguishable (gates A1's replay runner). *A5-3 (NOTE):* tape growth ~11 KB/day → TTL near-zero priority. Heartbeat vs reservation identity = doc-hygiene, not a code defect.

**A6 VIABLE-SET.** *A6-1 (PASS):* two-track funnel is queryable without calling the raw clone "selected" (distinct tables/bases). ***A6-2 (HIGH — THE FIRST OPERATOR DECISION):*** all three policy-lab portfolios carry `net_liq=$100,000` (incl. the live-eligible champion, cash $106,883.75) vs the ~$2,067.86 live book at the dated observation (**~48×**). Narrowed consequence: raw-dollar **P&L, capacity, feasibility, sizing, and selected samples** are not live-tier comparable; **promotion is partially normalized** where `promotion_normalization` (0.31 discount) is enabled; the **thesis hit/miss LABELS themselves are not notional-scaled** (though capital changes *which* trades enter the sample); and `live_eligible` is **routing, not broker execution**. The `or 100000` fallback is **inert** (stored net_liq genuinely $100k) → removing it is a SEPARATE fail-closed code item (does not repair historical comparability). **Operator decision (this is the first operator decision):** preserve the legacy $100k epoch as non-live-tier evidence; at a clean boundary (no open shadow positions/orders) launch versioned live-tier observe-only cohorts on one shared broker-grounded capital snapshot, persisting `capital_basis`/source/as-of/epoch; freeze cross-epoch promotion until a fresh minimum sample exists. **Never rewrite historical fills/P&L as if they occurred at $2k.** *A6-3 (HIGH, EXTENDS-E12/⑤):* three incoherent probability bases (credit EV≡$0; debit breakeven-delta; condor raw `|delta|`+fixed severity) all write `suggestion["ev"]` and are jointly sorted by one structure-agnostic ranker (`canonical_ranker.py:63,240`) — a condor's cross-structure rank flips on a severity constant *before* any $-gate. Live mis-rank.

**A7 DORMANT PHASE-3 (Pass 1; Pass 2/3 DEFERRED-DORMANT).** *A7-1 (HIGH):* live broker closes = **8 total, last 2026-07-08, 0 in the 7 days to pin** (book flat; entries throttled by streak-breaker + #1101 + 1-shot/day) → the ~10–15-fill gate ETA is **INDETERMINATE/PAUSED, entry-rate-bound**, not close-instrumentation-bound. *A7-2 (MED, EXTENDS-Phase-3):* exit-basis stamp is durable (`order_json`, not logs) but only **2 of 6** close orders have a computable `gap_fraction`; **all 3 most recent closes are fill-only** (cross/mid NULL — resting-GTC/sweep bypasses stage corroboration). Measurement quality improvable; sample size cannot be manufactured. Phase-3 stop doctrine preserved.

**A8 NEGATIVE-DECISION.** *A8-1 (MED, EXTENDS-F-A9-5):* `_log_cohort_decisions:1536-1546` compares dollar `ev` to the 0–100 `min_score_threshold` while routing uses `score` → `ev_below_min` is a lie; **56 `policy_decisions` rows carry it** (materialized). `rank_at_decision` is on raev not score (secondary lie). *A8-2 (PASS):* scanner cost-rejection (`suggestion_rejections`) vs ranker edge-floor (`trade_suggestions.blocked_reason`) are distinct tables/vocabularies — separable. *A8-3 (PASS):* #1200 verdicts + champion rejection preserve distinct scopes/bases (SOFI sentinel fired correctly).

**A9 ALERT & SIGNAL INTEGRITY.** *A9-1 (MED, NEW — F-A9-6, 5th typed-column-lie):* `model_version` is set from `os.getenv("APP_VERSION")` (a deploy string) but documented/consumed as model identity — a `GROUP BY model_version` in calibration/analytics would one-bucket every row; `fork.py:1094` already had to stamp `calibration_provenance_status='not_persisted_on_source'` to work around it. *A9-2 (MED, = GIT-SHA):* `decision_runs.git_sha` + `trade_suggestions.code_sha` = 'unknown' (12/12), Railway SHA unwired. *A9-3 (MED, NEW — F-A9-8):* `fork.py:498` sets `status='partial'` on `fork_errors`, but the **champion/legacy path never populates `fork_errors`** (tag failures `except: pass`; clone-insert failures fire a fire-and-forget critical alert only) → a champion clone/tag failure returns green (`champion_status='legacy_unmeasured'`). *A9-4:* "absence-of-INFO before #1198" RESOLVED (#1198); "pooled/routing labeled live before #1201" RESOLVED (#1201); residual LOW — `scheduler.py` never calls `setup_logging` (APScheduler INFO still dropped) and the freshness alert has no no-activity guard for `learning_feedback_loops`/`suggestion_rejections`/`calibration_adjustments` → a quiet learning-mode stretch fires `output_stale=error` (EXTENDS-§8 OUTPUT_FRESHNESS).

**A10 CALENDAR & CLOCK.** *A10-1 (MED, EXTENDS-area10 — hard trigger before 2026-09-07):* `is_us_market_hours:46-69` is DST-correct but **holiday-blind** (weekday math, no `get_calendar`) → **Labor Day 2026-09-07 (Mon)** returns market-open → false `data_stale`/`job_late` HIGHs (docstring "≤1 benign"; area10 measured 4–7/holiday). *A10-2 (NOT_PROVEN):* summer warm-up `_rth_job_status` anchor not fully traced. *A10-3 (LOW, EXTENDS-F-A10-4):* thesis `in_progress` ≠ position-open (9 rows future expiries); Fri→Mon ≤72h scoring lag — accept. *A10-4 (VERIFIED):* 5 clock domains distinguished (broker calendar / ET wall-clock / UTC storage / scheduler CT / process-local date); only A10-1 conflates weekday-math for broker-calendar on the alert path.

## 7. Runtime-check list (NOT RUN — external-brief-class checks now runnable by operator)
- `CONDOR_EV_MODEL` / `CONDOR_TAIL_LOSS_SEVERITY` / `CONDOR_TAIL_PROB_MULT` on both workers (code default strict vs env `tail`).
- `RAILWAY_GIT_COMMIT_SHA` presence on both workers (proves the git_sha fix is one-line, not a build-arg).
- W2/W3 post-#1198 INFO emit presence in Railway logs (durable-emit confirmation).
- `_rth_job_status` warm-up anchor season-symmetry (A10-2).
- Inject a `paper_positions`/`live_routed_portfolio_ids` exception into the midday cycle and the risk-check breaker; confirm entries stage / envelopes pass green (the two fail-open sites).

## 8. Instrument-integrity list

| Signal | Emitter | Boundary | Durable sink | Reader | Test reach | Verdict |
|---|---|---|---|---|---|---|
| Process INFO | `logger.info` | stdlib→stream | Railway logs | operator | #1198 handler test | ATTESTED post-#1198; `scheduler.py` un-setup (residual) |
| Decision blobs | `BlobStore.commit` | **bytea hex** | `data_blobs` | `ReplayTruthLayer` | real RPC test | PASS |
| Tape integrity | `DecisionContext.commit` | JSONB | `decision_runs.tape_integrity` | `runner._classify` | real-JSON+origin test | PASS |
| Job partial | `counts.errors` | JSON | `job_runs.status` | ops_health A4 | classifier tests | PASS (but champion-path A9-3 gap) |
| **git_sha** | `getenv("GIT_SHA")` | text | `decision_runs.git_sha` | — | none | **FAIL: constant 'unknown'** (A4-1/A9-2) |
| **Replay hashes** | `compute_aggregate_hash` | text | `decision_runs.*_hash` | **none** | verify_* isolated | **no reader** (A4-2) |
| **Capital/book/ev_raw** | — | — | **absent** | — | — | **not captured** (A1-1) |
| **W1-W4 arm evidence** | shadow logs | INFO/WARNING | **logs-only (W4 semi-durable)** | — | helper-only | **ephemeral** (§5) |
| Dead-man ping | `heartbeat` | HTTP | healthchecks.io | DOWN-email | fail-safe test | PASS |
| Alert egress relay | ops_health | webhook | inbox | operator | #1111 synthetic | PASS |

## 9. Fail-open position-read cluster (the headline safety finding)

**F-MIDDAY-POSITION-READ-FAILOPEN — CONFIRMED, 2 sites · VERIFIED-CODE:**
- **Site A (fully silent):** `services/workflow_orchestrator.py:_fetch_positions:2240-2270` — `except Exception: print(...); return []`. Defeats `risk/position_scope.live_routed_portfolio_ids`'s loud-by-contract raise; a failed read = a flat book → bypasses the micro-tier one-at-a-time gate (`:2305 len(positions)>=1`) → oversized/duplicate **live entry**. Only source-string "tested" (`test_workflow_orchestrator_positions_query.py` inspects the source, never drives the seam).
- **Site B (alerts, not silent):** `services/paper_autopilot_service.py:_get_open_positions_for_risk_check:1328-1343` — `except → alert(...) → return []`; the circuit-breaker's concentration/sector/expiry/stress/earnings envelopes then pass **green-on-vacuum**. Un-hardened sibling of the 3 reads #1195/F-E8-3 fixed; loss brakes separately protected (realized brake fails-safe to broker-true).

**Causality (narrowed — a failed read is NOT inevitably an unsafe order):** Site A's false-flat affects scan concurrency, open-book risk usage, and small-tier allocation *before* suggestions persist; Site B's false-flat bypasses live-entry envelope inputs *before* the policy-lab executor. Broker reachability exists via `_stage_order_internal → submit_and_track` for `alpaca_live`+`live_eligible`. **But** later same-symbol dedup and the *enabled* utilization gate can independently stop an entry, and a *persistent* outage tends to fail later. **The dangerous case is a transient/selective failure or false-empty read followed by successful downstream staging.**
Priority: **P1-safety / next live-control build.** **Escalate to `P0-before-next-entry` if** the utilization-gate enforcement is OFF/unproven, any broker-live position is open, or multi-position/qty scaling is enabled.
Smallest decision: type the unavailable state and make BOTH scan and executor outcomes fail-CLOSED (re-raise / typed `capture_partial` that aborts entries), keeping `live_ids==[]` as the **only** legitimate flat-book path (a legitimate successful empty result must remain distinct and healthy). Acceptance: **route tests proving zero `submit_and_track` calls for BOTH a portfolio-ID exception AND a position-query exception**, and that a genuine empty result still stages/flags healthy. Falsifier: a read-exception test that still reaches `submit_and_track`.

## 10. Free look

Correctness hunt across execution/close/monitor/brake/streak/ingest/scope/heartbeat = **well-guarded, no novel correctness defect**. Genuine free-look finding: **OPTIMIZER_V4_ENABLED + ALLOCATION_V4_ENABLED dead-capability cluster** — complete alternative pipeline modules (`core/optimizer_v4.py`, `allocation/capital_allocator.py`) with zero production importers; armed env flags wiring zero behavior (siblings of the filed FORECAST_V4/REGIME_V4 #1126-family). Low-confidence note (not a headline): `paper_learning_ingest.py:456` swallows integrity errors by substring `"duplicate"/"unique"` — a constraint literally named `..._unique_...` could drop one learning outcome (low probability; Postgres FK/CHECK text rarely contains "unique").

## 11. Dependency / collision matrix (serious candidates)

| Finding | Requires | Unlocks/gates | Overlaps/shared | Ordering |
|---|---|---|---|---|
| F-MIDDAY-POSITION-READ-FAILOPEN (2 sites) | — | live-entry safety | `position_scope`, workflow_orchestrator, paper_autopilot | **first (safety), own lane** |
| A6-2 shadow-capital epoch | versioned observe-only cohort + shared capital snapshot (operator) | raw-dollar/capacity/sizing comparability (NOT thesis LABELS); cross-epoch promotion | shadow portfolios, init_lab; F-POLICY-CAPITAL-FALLBACK is a SEPARATE fail-closed code item (literal inert) | **first operator decision**; freeze cross-epoch promotion until fresh min sample; never rewrite historical rows |
| A6-3 condor mis-rank | ⑤ terminal distribution | viable-set honesty | E12, ⑤, canonical_ranker | with ⑤ (make/fetch) |
| A1-1 replay runner | A1-1 capture + A5-2 origin | raw-vs-calibrated replay, E19-2B | decision_context, ReplayTruthLayer | after capture |
| A4-1/A9-2 git_sha | RAILWAY_GIT_COMMIT_SHA env | replay code-drift attribution | GIT-SHA-DECISION-PROVENANCE | one-liner, anytime |
| A2-1 watchdog cancel-ack | — | double-entry before 2+ live | P0-A, alpaca_order_handler | before book holds 2+ |
| A10-1 holiday-blind | get_calendar | quiet ops before 09-07 | area10, is_us_market_hours | hard trigger < 2026-09-07 |
| observe-window durability | DB sink for shadow decisions | arm decisions (W2/W3/W4/W5) | risk_basis_shadow, bucket_control, calibration_apply_ordering | before any arm |

## 12. Ranked Top 3 + packet/code disagreements + score

**Top 3 (value / single-dev-evenings):**
1. **F-MIDDAY-POSITION-READ-FAILOPEN fail-closed (2 sites)** — ~0.5 evening; live-entry safety; no decision-path behavior change (only re-raise + typed partial). Falsifier: read-exception test stages no entry.
2. **A6-2 shadow-capital parity re-seed** — operator DB op + a normalization pass; unblocks every honest cross-cohort comparison the viable-set/promotion logic depends on. Falsifier: shadow net_liq at live scale or all consumers per-contract-normalized.
3. **A4-1/A9-2 git_sha one-liner** — 0.25 evening; restores decision-tape attribution; unblocks any replay determinism claim (A1/A4-2).

**Packet/code disagreements (high-value):** shadow-capital packet understated (champion is $100k too, 48×); condor code-default (strict) ≠ deployed env (tail); "needs_manual_review as routed success" inverted vs code=critical; git_sha provenance available but unwired.

**Audit-maturity — `INFERRED` qualitative estimate (NOT a verified measurement; NOT profitability, reliability, or measured efficiency).** No single scalar is asserted. Weighted scorecard (weights sum to 100), evidence per dimension:
| Dimension | Weight | State | Evidence |
|---|---|---|---|
| Instrument/tape integrity | 20 | strong | #1198/#1199 VERIFIED-CODE + 9 blobs/day complete (ATTESTED-RUNTIME) |
| Exclusion-integrity (E1-E20) | 15 | strong w/ 4 conditionals | §4 |
| Live-entry safety | 20 | **weak** | 2 fail-open reads (§9) |
| Capital/EV/cost coherence | 20 | **weak** | A6-2 parity + A6-3 mis-rank + missing canonical-risk |
| Evidence durability (observe windows) | 15 | **weak** | 4/5 windows ephemeral (§5) |
| Calendar/clock | 10 | good w/ 1 gap | A10-1 holiday-blind |
Reproducible reading: the strong dimensions (35 wt) are code+runtime verified; the weak dimensions (55 wt) carry the open risk; 10 wt is good-with-a-gap. **This is an audit-maturity judgement, not a live-money score.** Missing proof: the RUNTIME CHECKS — NOT RUN in §7.

## 13. Charter-completeness matrix

Every v1.5 charter requirement has a populated field or an explicit `NOT_PROVEN / RUNTIME CHECK — NOT RUN / DEFERRED-DORMANT`. **This report is not claimed `FULLY COMPLETE`** — the runtime deltas below are open by design.

| Charter requirement | Where | Status |
|---|---|---|
| Step-0 grounding | §1 | populated |
| Executive verdict (1 first decision) | §2 (A6-2 epoch) | populated |
| Current-state reconciliation | §3 | populated |
| E1–E20 disposition (PASS/CONDITIONAL/REOPENED/NOT_PROVEN) | §4 | populated (16 PASS, 4 CONDITIONAL) |
| W1–W5 (boundary/emitter/sink/sample/bypass/status) | §5 | populated |
| A1–A10 Pass 1/2/3 | §6 | populated; **A7 Pass 2/3 = DEFERRED-DORMANT** (no new live fills) |
| Runtime-check list | §7 | populated; all `RUNTIME CHECK — NOT RUN` |
| Instrument-integrity list (natural-proof field) | §8 | populated |
| Free look | §10 | populated (dead-capability cluster; else none) |
| Dependency/collision matrix | §11 | populated |
| Ranked Top 3 (evidence/effort/risk/dep/doctrine/falsifier) | §12 | populated |
| Packet/code disagreements | §12 | populated |
| Design score | §12 | `INFERRED` qualitative scorecard (no verified scalar) |
| Per-finding schema (12 fields) | §4/§6/§9/§11/§12 | ID/sev/label/seam/impact/backlog/decision/falsifier inline; effort/dependency/doctrine in the ranked/matrix sections |
| EV/PoP/cost basis+unit on every number | §1a, §6 A6-3, §2 | basis+unit stated (raw/calibrated/realized; per-contract/position-total) |
| Rejected/duplicate/superseded exclusion memory | §12 + ledger | internal-fill sign = REJECTED; SETTLED/PASS list in the ledger |
| Credential disposition | §1b | `OPERATOR-ATTESTED` class-only |
| DEFERRED-DORMANT items | A7 Pass 2/3; A10-2 NOT_PROVEN | marked |

**Open runtime deltas (why not FULLY COMPLETE):** the 5 `RUNTIME CHECK — NOT RUN` in §7 (condor bg-worker env; RAILWAY_GIT_COMMIT_SHA presence; W2/W3 post-#1198 INFO emit; `_rth_job_status` warm-up symmetry; fail-open injection tests) + A10-2 summer warm-up `NOT_PROVEN`.

**STOP.** Read-only report. No production code/config/DB/broker change; nothing merged or deployed.
