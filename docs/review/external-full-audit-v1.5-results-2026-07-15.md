# EXTERNAL FULL AUDIT v1.5R — COMPLETED RESULTS

**Executed:** 2026-07-15 (post-close) · **Charter:** `docs/review/external-full-audit-v1.5-current.md` (BRIEF — this file is the completed report; the brief remains the charter).
**Immutable code baseline audited:** `bef2cdd60edbee8642fa043192fd982d4bfe4436`.
**Method:** read-only code trace at bef2cdd + read-only runtime adjudication (this session has Supabase/Railway/Alpaca; the external brief did not — runtime evidence is labeled separately and never upgraded to code proof).

Proof labels: `VERIFIED-CODE` · `VERIFIED-TEST-REACH` · `ATTESTED-RUNTIME` (direct DB/Railway/broker read this session) · `INFERRED` · `RUNTIME CHECK — NOT RUN` · `NOT PROVEN`.

---

## 1. Step-0 grounding & immutable baseline

- host `2026-07-15 22:43:18Z` ≈ DB `22:43:20Z` (CT 17:43 / ET 18:43) ≈ broker `18:43:21 ET` — agree ~2s; **market CLOSED**, next open 2026-07-16 09:30 ET. (Reconciliation re-pin 2026-07-16 00:51Z host ≈ DB 00:51:22Z ≈ broker 20:51 ET — same close.)
- **origin/main moved during the engagement:** `623044d` → **`d18dd52`** (#1208 "Add files via upload", 22:41Z). `bef2cdd..d18dd52` = **2 docs files only** (`external-full-audit-v1.5-current.md` #1207 + `…-execute-adjudicate-integrate-prompt.md` #1208), **zero code/config/migration** → **production-code baseline is still `bef2cdd`** (VERIFIED-CODE). Deployed SHA on BE + both workers = `623044d`, SUCCESS 09:42Z (docs-only recycle over bef2cdd; the 07-15 falsifier code is bef2cdd-identical).
- Worktree `wt-reconcile-0714` production `.py` == bef2cdd (byte-diff = docs + `test_docs_consistency.py` only) — reads are authoritative.
- Runtime falsifiers already graded PASS this session (ATTESTED-RUNTIME): #1200 SOFI natural falsifier PASS; #1201 calibration PASS (8 post-epoch live outcomes, ev×0.5/pop×0.5); #1201 thesis PASS (execution-mode split, alpaca_live 5/7 distinct from routing); tape 9 blobs/day all `complete`; `decision_runs.git_sha='unknown'` 12/12.

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

Current broker-live thesis accuracy is **directionally encouraging (5/7 scored at the 2026-07-15 census) and not yet falsified, but signal edge is NOT PROVEN at this sample size** (tiny-n; thesis-hit ≠ net economic edge — realized broker-live profitability is **1W/7L** [basis=realized, unit=position-total], and execution, exits, costs, and cross-structure EV semantics remain the leading observed loss mechanisms). Shadow results are NOT used as live evidence, and the economic-ranking signal is **not** sound: A6-3 shows credit/debit/condor candidates are ranked on incoherent EV/probability bases. Two live-entry position reads fail OPEN (`except → return []`) — a *transient/selective* failure or false-empty read followed by successful downstream staging can produce an unsafe entry (`F-MIDDAY-POSITION-READ-FAILOPEN`, 2 sites; the strongest new finding; see §9 for the non-inevitable causality). Capital-comparability is degraded: all three policy-lab portfolios (incl. the live-eligible champion) use a ~$100,000 basis vs the ~$2,067.86 live book (**~48×**) at the dated observation, so raw-dollar P&L / capacity / feasibility / sizing / selected samples are not live-tier comparable. Observe-window instrumentation: **four of five windows lack complete durable decision evidence (W1, W2, W3, W5), but only W1/W2 are strictly logs-only; W3 is partially durable (a cap-breach alarm subset reaches `risk_alerts`), W4 is semi-durable (a count reaches `job_runs.result`), and W5 is absent/unstarted.** No CRITICAL fires on live money today (book flat, post-epoch n=8 live closes, learning-mode). No control-loosening is recommended anywhere. **The single first operator decision** is the shadow-capital epoch (A6-2; see §6 A6-2) — a versioned live-tier observe-only cohort, NOT an in-place re-seed of historical rows. Audit-maturity is an `INFERRED` design-maturity score (see §12 scorecard); it is not a verified profitability/reliability measurement.

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

## 5. W1–W5 observe-window table (C3 — complete, one row per window)

Durability taxonomy is exact, not a bare count: **W1/W2 are strictly logs-only; W3 is partially durable (INFO plus a would-block cap-breach alarm subset persisted to `risk_alerts`); W4 is semi-durable (arm count persisted to `job_runs.result`); W5 is absent/unstarted.** "Sample/sufficiency" never reuses a run-state word — an unknown live-flip count is `NOT_PROVEN` (the Verdict column carries the run-state).

| W | Flag / default | First-valid boundary (UTC + SHA) | Emitter (post-#1198) | Durable sink | Sample / sufficiency | Reset rule | Bypass | Exact runtime check | Expected PASS | Expected FAIL | Why code alone cannot settle | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| W1 | `GATE_QTY_FIX_LIVE_ENABLED` / OFF | `655c9aa` (WARNING, pre-#1198) | WARNING `paper_endpoints.py:1370` | **strictly logs-only** (flip line) | `NOT_PROVEN` (degenerate at qty=1; no live-flip count) | container restart (log stream) | none (centralized `_stage_order_internal`) | grep Railway worker logs for the qty-fix WARNING flip line over an armed window | ≥1 flip line for a qty>1 live stage | zero flip lines while qty>1 live stages occurred | log retention & arm state are runtime facts, not in source | **RUNNING** (sample-starved) |
| W2 | `RISK_BASIS_MAX_LOSS_ENABLED` / OFF | #1198 `1386834` | INFO `risk_basis_shadow.py:40,50` | **strictly logs-only** | `NOT_PROVEN` (would_flip real only at RBE, 1 of 3 consumers) | container restart | 3 self-gated consumers | confirm INFO `[RISK_BASIS…]` emit present in Railway logs post-#1198 | INFO lines present at scoring cadence | no INFO lines (emitter never reached / setup-logging gap) | emit presence is a deploy/log-retention fact | **START-UNVERIFIED** |
| W3 | `BUCKET_CONTROL_ENFORCE` / OFF | #1198 `1386834` | INFO + would-block alarm (`:1082-1095`) | **partially durable** (cap-breach alarm subset → `risk_alerts`; the rest INFO) | `NOT_PROVEN` (alarm subset persists; arm-flip count unknown) | container restart (INFO) / `risk_alerts` durable | **real** (`:636` + endpoint stages bypass) | query `risk_alerts` for the bucket would-block type over an armed window AND confirm INFO reservation-order emit | alarm rows present for breaches + INFO order lines | breaches with no alarm rows / no INFO | retry & cross-job joinability are runtime facts; no shared `decision_id` in source (F-WINDOW-1b) | **START-UNVERIFIED** |
| W4 | `CALIBRATION_APPLY_AT_SCORING` / OFF | #1198 `1386834` | `[APPLY_ORDER_SHADOW]` | **semi-durable** (count→`job_runs.result`, mislabeled `universe_size`) | `NOT_PROVEN` (count durable; sufficiency of arm-flip evidence unproven) | per-run `job_runs` row | single midday call site | read `job_runs.result` apply-order count for the midday cycle | non-null frozen-vs-calibrated top-5 delta count | null/absent count | the count exists only at runtime in `job_runs` | **RUNNING** |
| W5 | composed arm | — | none | **absent** | `NONE` (unstarted) | — | — | none (no emitter to check) | n/a | n/a | nothing is emitted — settled by code inspection as unstarted | **UNSTARTED** |

**Biggest W gap (R4-corrected):** four of five windows lack complete durable decision evidence (W1, W2, W3, W5); of those only **W1/W2 are strictly logs-only** (silently dropped pre-#1198, born 07-11; Railway-retention-bounded even now), **W3 is partially durable** (its cap-breach alarm subset reaches `risk_alerts`), **W4 is semi-durable** (a count reaches `job_runs.result`), and **W5 is absent**. "How many live decisions would arming flip" is not queryable for W1/W2/W3/W5.

## 6. A1–A10 (Pass 1/2/3)

**A1 PROFITS.** Replay runner **NOT buildable today** — *A1-1 (MED, EXTENDS-E19-2B):* capital/OBP/tier/open-book state + `ev_raw` are never captured (only market-data + regime/symbol/ranked_candidates), and `ReplayTruthLayer.from_decision_id` has zero production callers. The raw-vs-calibrated ordering counterfactual is unanswerable from the tape. *A1-2 (NOTE):* ⑤ make-vs-fetch is not input-starved — the chain is captured (fetch reconstructable; make coarse). Pass 3: the replay runner is the top A1 extension, gated on A1-1 capture + A5-2 origin.

**A2 LOSSES.** *A2-1 (MED, EXTENDS-P0-A):* the idle-watchdog writes `status='watchdog_cancelled'` **unconditionally** even when `cancel_order` raises because the order just filled (`alpaca_order_handler.py:846-876`); the next poll excludes `watchdog_cancelled` → the fill is un-polled → suggestion re-executable → new row → new `client_order_id` → **double-entry** (loud via ghost sweep, so MED). *A2-2 (LOW):* `max_loss_total` (#1166) is scalar-safe per consumer (position-total, no ×qty/sign bug); canonical-position gap (signed ratios/multipliers/greeks behind the scalar) remains the P1 target. Assignment/partial-close DEFERRED-DORMANT (0 open credit near expiry).

**A3 SELF-LEARNING.** F-A3-4 shared fetch PASS (None=fail/[]=empty/[…]=rows, live-only). *A3-1 (LOW, NEW):* `thesis=hit ∧ realized_pnl<0 ∧ close_reason=stop ∧ execution_mode=alpaca_live` is readable with no cohort/basis leakage (on `position_thesis_outcomes`), **but `learning_trade_outcomes_v3` has no `close_reason`/`thesis_outcome` column** → the premature-stop signal is un-consumed by any multiplier. *A3-2 (LOW, EXTENDS-segment-n):* DTE bucket is **inert** — the fetch SELECTs no DTE source → every outcome `dte_bucket='unknown'` → redundant `_all` twin; adding a DTE column would activate a double-count trap. *A3-3 (LOW, EXTENDS-E1/segment-n):* `apply_calibration` never re-checks `sample_size` → a 3-sample segment applies un-shrunk (latent; live blob `_overall`-only, n=8). Prequential = study tool (zero callers).

**A4 SELF-SUSTAINING (instrument-integrity headline).** Job classification wired (`runner._classify:46-68`, partial iff users_failed/counts.errors); dead-man fail-safe; bytea symmetric. *A4-1 (MED, = GIT-SHA):* capture reads `os.getenv("GIT_SHA")` only; `RAILWAY_GIT_COMMIT_SHA` exists and is used by `/version` + `backtest_identity` — one-line fallback fix. *A4-2 (MED, NEW):* `decision_runs.input_hash/features_hash` are written but `verify_*` has **no production reader** → determinism regressions are silent. *A4-3 (NOTE, negative result):* no OTHER non-JSON type crosses supabase-py's JSON layer (only the #1199-fixed blob). Instrument-integrity list in §8.

**A5 EFFICIENCY.** *A5-1 (NOTE):* `FORECAST_V4_ENABLED` gates zero compute (doubly inert). *A5-2 (LOW, NEW):* `decision_runs` has no origin/trigger column → scheduled vs operator vs replay cycles are indistinguishable (gates A1's replay runner). *A5-3 (NOTE):* tape growth ~11 KB/day → TTL near-zero priority. Heartbeat vs reservation identity = doc-hygiene, not a code defect.

**A6 VIABLE-SET.** *A6-1 (PASS):* two-track funnel is queryable without calling the raw clone "selected" (distinct tables/bases). ***A6-2 (HIGH — THE FIRST OPERATOR DECISION):*** all three policy-lab portfolios carry `net_liq=$100,000` (incl. the live-eligible champion, cash $106,883.75) vs the ~$2,067.86 live book at the dated observation (**~48×** [basis=realized, unit=position-total]). Narrowed consequence: raw-dollar **P&L, capacity, feasibility, sizing, and selected samples** are not live-tier comparable; **promotion is partially normalized** where `promotion_normalization` (0.31 discount) is enabled; the **thesis hit/miss LABELS themselves are not notional-scaled** (though capital changes *which* trades enter the sample); and `live_eligible` is **routing, not broker execution**. The `or 100000` fallback is **inert** (stored net_liq genuinely $100k) → removing it is a SEPARATE fail-closed code item (does not repair historical comparability). **Operator decision (this is the first operator decision):** preserve the legacy $100k epoch as non-live-tier evidence; at a clean boundary (no open shadow positions/orders) launch versioned live-tier observe-only cohorts on one shared broker-grounded capital snapshot, persisting `capital_basis`/source/as-of/epoch; freeze cross-epoch promotion until a fresh minimum sample exists. **Never rewrite historical fills/P&L as if they occurred at $2k.** *A6-3 (HIGH, EXTENDS-E12/⑤):* three incoherent probability bases (credit EV≡$0 [basis=raw, unit=position-total]; debit breakeven-delta; condor raw `|delta|`+fixed severity [basis=raw, unit=probability]) all write `suggestion["ev"]` and are jointly sorted by one structure-agnostic ranker (`canonical_ranker.py:63,240`) — a condor's cross-structure rank flips on a severity constant *before* any $-gate. Live mis-rank.

**A7 DORMANT PHASE-3 (Pass 1; Pass 2/3 DEFERRED-DORMANT).** *A7-1 (HIGH):* **8 post-epoch broker-live closes (9 all-time including the pre-epoch close)**, last 2026-07-08, 0 in the 7 days to pin (book flat; entries throttled by streak-breaker + #1101 + 1-shot/day) → the ~10–15-fill Phase-3 gate ETA is **INDETERMINATE/PAUSED, entry-rate-bound**, not close-instrumentation-bound. Phase-3 eligible/instrumented is a SEPARATE count: **~3 of 10–15** fills instrumented (2 with a computable `gap_fraction`) — see §1a; it is not equated with close history. *A7-2 (MED, EXTENDS-Phase-3):* exit-basis stamp is durable (`order_json`, not logs) but only **2 of 6** close orders have a computable `gap_fraction`; **all 3 most recent closes are fill-only** (cross/mid NULL — resting-GTC/sweep bypasses stage corroboration). Measurement quality improvable; sample size cannot be manufactured. Phase-3 stop doctrine preserved.

**A8 NEGATIVE-DECISION.** *A8-1 (MED, EXTENDS-F-A9-5):* `_log_cohort_decisions:1536-1546` compares dollar `ev` [basis=raw, unit=position-total] to the 0–100 `min_score_threshold` [unit=score-points] while routing uses `score` → `ev_below_min` is a lie; **56 `policy_decisions` rows carry it** (materialized). `rank_at_decision` is on raev not score (secondary lie). *A8-2 (PASS):* scanner cost-rejection (`suggestion_rejections`) vs ranker edge-floor (`trade_suggestions.blocked_reason`) are distinct tables/vocabularies — separable. *A8-3 (PASS):* #1200 verdicts + champion rejection preserve distinct scopes/bases (SOFI sentinel fired correctly).

**A9 ALERT & SIGNAL INTEGRITY.** *A9-1 (MED, NEW — F-A9-6, 5th typed-column-lie):* `model_version` is set from `os.getenv("APP_VERSION")` (a deploy string) but documented/consumed as model identity — a `GROUP BY model_version` in calibration/analytics would one-bucket every row; `fork.py:1094` already had to stamp `calibration_provenance_status='not_persisted_on_source'` to work around it. *A9-2 (MED, = GIT-SHA):* `decision_runs.git_sha` + `trade_suggestions.code_sha` = 'unknown' (12/12), Railway SHA unwired. *A9-3 (MED, NEW — F-A9-8):* `fork.py:498` sets `status='partial'` on `fork_errors`, but the **champion/legacy path never populates `fork_errors`** (tag failures `except: pass`; clone-insert failures fire a fire-and-forget critical alert only) → a champion clone/tag failure returns green (`champion_status='legacy_unmeasured'`). *A9-4:* "absence-of-INFO before #1198" RESOLVED (#1198); "pooled/routing labeled live before #1201" RESOLVED (#1201); residual LOW — `scheduler.py` never calls `setup_logging` (APScheduler INFO still dropped) and the freshness alert has no no-activity guard for `learning_feedback_loops`/`suggestion_rejections`/`calibration_adjustments` → a quiet learning-mode stretch fires `output_stale=error` (EXTENDS-§8 OUTPUT_FRESHNESS).

**A10 CALENDAR & CLOCK.** *A10-1 (MED, EXTENDS-area10 — hard trigger before 2026-09-07):* `is_us_market_hours:46-69` is DST-correct but **holiday-blind** (weekday math, no `get_calendar`) → **Labor Day 2026-09-07 (Mon)** returns market-open → false `data_stale`/`job_late` HIGHs (docstring "≤1 benign"; area10 measured 4–7/holiday). *A10-2 (NOT_PROVEN):* summer warm-up `_rth_job_status` anchor not fully traced. *A10-3 (LOW, EXTENDS-F-A10-4):* thesis `in_progress` ≠ position-open (9 rows future expiries); Fri→Mon ≤72h scoring lag — accept. *A10-4 (VERIFIED):* 5 clock domains distinguished (broker calendar / ET wall-clock / UTC storage / scheduler CT / process-local date); only A10-1 conflates weekday-math for broker-calendar on the alert path.

## 7. Runtime-check list (C4 — table; every status NOT RUN unless a timestamped prior attestation is cited)

| ID | Exact read / query / log | Service / source | Expected PASS evidence | Expected FAIL evidence | Why code alone cannot settle | Status |
|---|---|---|---|---|---|---|
| RC-1 | echo `CONDOR_EV_MODEL` / `CONDOR_TAIL_LOSS_SEVERITY` / `CONDOR_TAIL_PROB_MULT` on **background** worker env | Railway worker-background | env echoes the deployed `tail` model + severity/mult on the bg worker | env unset/strict on the bg worker (code default) | deployed env ≠ source default; per-worker value is a runtime fact | RUNTIME CHECK — NOT RUN |
| RC-2 | check `RAILWAY_GIT_COMMIT_SHA` presence on both workers | Railway BE + both workers | var present & populated (proves one-line fallback, not a build-arg) | var absent (fix needs build-arg wiring) | presence is a platform-injected runtime var | RUNTIME CHECK — NOT RUN |
| RC-3 | grep Railway logs for W2/W3 post-#1198 INFO emit | Railway worker logs | `[RISK_BASIS…]` + bucket reservation-order INFO present | no INFO lines (emitter unreached / setup-logging gap) | emit presence is a deploy + log-retention fact | RUNTIME CHECK — NOT RUN |
| RC-4 | trace `_rth_job_status` warm-up anchor across summer vs winter | code + Railway clock | anchor season-symmetric (no warm-up skew) | anchor asymmetric (A10-2 confirmed) | seasonal wall-clock behavior needs a live clock | RUNTIME CHECK — NOT RUN |
| RC-5 | inject a `paper_positions`/`live_routed_portfolio_ids` exception into the midday cycle (Site A) | staging test harness | entries do NOT stage on a read exception (post-fix) | entries stage on a read exception (current fail-open) | fail-open manifests only under an injected read failure at runtime | RUNTIME CHECK — NOT RUN |
| RC-6 | inject the same exception into the risk-check breaker (Site B) | breaker test harness | envelopes block/defer on a read exception (post-fix) | envelopes pass green-on-vacuum (current fail-open) | the vacuum only arises under an injected failure | RUNTIME CHECK — NOT RUN |

## 8. Instrument-integrity list (C5 — complete, with natural-proof + exact runtime check)

| Signal | Emitter | Boundary | Durable sink | Consumer | Test reach | Natural proof (observed event/time/basis or NOT_PROVEN) | Exact runtime check | Verdict |
|---|---|---|---|---|---|---|---|---|
| Process INFO | `logger.info` | stdlib→stream | Railway logs | operator | #1198 handler test | ATTESTED post-#1198 (handler INFO emitted); `scheduler.py` un-setup NOT_PROVEN | grep Railway for handler INFO + scheduler INFO | ATTESTED post-#1198; scheduler residual |
| Decision blobs | `BlobStore.commit` | **bytea hex** | `data_blobs` | `ReplayTruthLayer` | real RPC test | 9 blobs/day `complete` observed 2026-07-15 (ATTESTED-RUNTIME) | query `data_blobs` count/status for the day | PASS |
| Tape integrity | `DecisionContext.commit` | JSONB | `decision_runs.tape_integrity` | `runner._classify` | real-JSON+origin test | `tape_integrity` rows present, classifier reached (ATTESTED) | query `decision_runs.tape_integrity` distribution | PASS |
| Job partial | `counts.errors` | JSON | `job_runs.status` | ops_health A4 | classifier tests | partial classified when counts.errors set (VERIFIED-TEST-REACH); champion-path gap A9-3 | inject a champion clone failure; read `job_runs.status` | PASS (champion-path A9-3 gap) |
| **git_sha** | `getenv("GIT_SHA")` | text | `decision_runs.git_sha` | — (no consumer) | none | 12/12 rows literal 'unknown' observed (ATTESTED-RUNTIME) — a proven constant, not identity | query distinct `git_sha` values | **FAIL: constant 'unknown'** (A4-1/A9-2) |
| **Replay hashes** | `compute_aggregate_hash` | text | `decision_runs.*_hash` | **none** (verify_* isolated) | verify_* isolated | NOT_PROVEN (no reader exists to observe a mismatch) | add a reader; replay a decision; compare hashes | **no reader** (A4-2) |
| **Capital/book/ev_raw** | — | — | **absent** | — | — | NOT_PROVEN (never captured) | attempt `ReplayTruthLayer.from_decision_id`; observe missing inputs | **not captured** (A1-1) |
| **W1/W2/W3/W5 arm evidence** | shadow logs | INFO/WARNING | W1/W2 logs-only · W3 partial (alarm subset) · W5 none | — | helper-only | NOT_PROVEN (arm-flip count not queryable) | grep armed-window logs + `risk_alerts` (W3) | non-durable (§5); W3 partial |
| Dead-man ping | `heartbeat` | HTTP | healthchecks.io | DOWN-email | fail-safe test | receipt + DOWN-email proven 07-02 (ATTESTED-RUNTIME) | trigger a miss; confirm DOWN-email | PASS |
| Alert egress relay | ops_health | webhook | inbox | operator | #1111 synthetic | synthetic row → inbox proven 07-02 (ATTESTED-RUNTIME) | insert a synthetic critical; confirm inbox | PASS |

## 9. Fail-open position-read cluster (the headline safety finding)

**F-MIDDAY-POSITION-READ-FAILOPEN — CONFIRMED, 2 sites · VERIFIED-CODE:**
- **Site A (fully silent):** `services/workflow_orchestrator.py:_fetch_positions:2240-2270` — `except Exception: print(...); return []`. Defeats `risk/position_scope.live_routed_portfolio_ids`'s loud-by-contract raise; a failed read = a flat book → bypasses the micro-tier one-at-a-time gate (`:2305 len(positions)>=1`) → oversized/duplicate **live entry**. Only source-string "tested" (`test_workflow_orchestrator_positions_query.py` inspects the source, never drives the seam).
- **Site B (alerts, not silent):** `services/paper_autopilot_service.py:_get_open_positions_for_risk_check:1328-1343` — `except → alert(...) → return []`; the circuit-breaker's concentration/sector/expiry/stress/earnings envelopes then pass **green-on-vacuum**. Un-hardened sibling of the 3 reads #1195/F-E8-3 fixed; loss brakes separately protected (realized brake fails-safe to broker-true).

**Causality (narrowed — a failed read is NOT inevitably an unsafe order):** Site A's false-flat affects scan concurrency, open-book risk usage, and small-tier allocation *before* suggestions persist; Site B's false-flat bypasses live-entry envelope inputs *before* the policy-lab executor. Broker reachability exists via `_stage_order_internal → submit_and_track` for `alpaca_live`+`live_eligible`. **But** later same-symbol dedup and the *enabled* utilization gate can independently stop an entry, and a *persistent* outage tends to fail later. **The dangerous case is a transient/selective failure or false-empty read followed by successful downstream staging.**
Priority: **P1-safety / next live-control build.** **Escalate to `P0-before-next-entry` if** the utilization-gate enforcement is OFF/unproven, any broker-live position is open, or multi-position/qty scaling is enabled.
Smallest decision: type the unavailable state and make BOTH scan and executor outcomes fail-CLOSED (re-raise / typed `capture_partial` that aborts entries), keeping `live_ids==[]` as the **only** legitimate flat-book path (a legitimate successful empty result must remain distinct and healthy). Acceptance: **route tests proving zero `submit_and_track` calls for BOTH a portfolio-ID exception AND a position-query exception**, and that a genuine empty result still stages/flags healthy. Falsifier: a read-exception test that still reaches `submit_and_track`.

## 10. Free look

Correctness hunt across execution/close/monitor/brake/streak/ingest/scope/heartbeat = **well-guarded, no novel correctness defect**. Genuine free-look finding: **OPTIMIZER_V4_ENABLED + ALLOCATION_V4_ENABLED dead-capability cluster** — complete alternative pipeline modules (`core/optimizer_v4.py`, `allocation/capital_allocator.py`) with zero production importers; armed env flags wiring zero behavior (siblings of the filed FORECAST_V4/REGIME_V4 #1126-family). Low-confidence note (not a headline): `paper_learning_ingest.py:456` swallows integrity errors by substring `"duplicate"/"unique"` — a constraint literally named `..._unique_...` could drop one learning outcome (low probability; Postgres FK/CHECK text rarely contains "unique").

## 11. Dependency / collision matrix (C7 — complete)

| Finding | Requires | Unlocks / gates | Supersedes / duplicates | Shared files / models / tables / flags | Ordering | Collision risk | Mitigation |
|---|---|---|---|---|---|---|---|
| F-MIDDAY-POSITION-READ-FAILOPEN (2 sites) | typed unavailable-state + fail-closed decision | live-entry safety | sibling of #1195/F-E8-3 (same class, not duplicate) | `position_scope`, `workflow_orchestrator.py`, `paper_autopilot_service.py` | **first (safety), own lane** | must not break the legitimate empty-book path | route tests: exception → no `submit_and_track`; empty → healthy stage |
| A6-2 shadow-capital epoch | versioned observe-only cohort + shared capital snapshot (operator) | raw-dollar/capacity/sizing comparability (NOT thesis LABELS); cross-epoch promotion | F-POLICY-CAPITAL-FALLBACK is a SEPARATE fail-closed code item (literal inert) — not a duplicate | shadow portfolios, `init_lab`, `promotion_normalization` | **first operator decision** | rewriting history would corrupt the pool | preserve legacy epoch; freeze cross-epoch promotion; never rewrite historical rows |
| A6-3 condor cross-structure mis-rank | ⑤ terminal distribution | viable-set honesty | EXTENDS E12/⑤ | `ev_calculator.py`, `canonical_ranker.py` | with ⑤ (make/fetch) | changing EV basis reorders live ranks | land with ⑤; regression-pin cross-structure order |
| A1-1 replay runner | A1-1 capture + A5-2 origin column | raw-vs-calibrated replay, E19-2B | EXTENDS E19-2B | `decision_context`, `ReplayTruthLayer`, `decision_runs` | after capture | capture schema change touches the tape | additive columns only; version the tape |
| A4-1 / A9-2 git_sha | `RAILWAY_GIT_COMMIT_SHA` env | replay code-drift attribution | GIT-SHA-DECISION-PROVENANCE | Dockerfile ARG, `decision_runs.git_sha`, `trade_suggestions.code_sha` | one-liner, anytime | none (additive read) | fallback `getenv("GIT_SHA") or getenv("RAILWAY_GIT_COMMIT_SHA")` |
| A2-1 watchdog cancel-ack | idempotent cancel-vs-fill classify | double-entry safety before 2+ live | EXTENDS P0-A | `alpaca_order_handler.py`, ghost sweep | before book holds 2+ | mis-classify could strand a real cancel | check fill state before stamping `watchdog_cancelled` |
| A4-2 replay-hash reader | a `verify_*` production reader | determinism-regression alarm | — | `decision_runs.*_hash` | after A1-1 | none (additive) | add reader + alert on mismatch |
| A9-1 / F-A9-6 model_version | a true model-identity column | honest `GROUP BY model_version` | 5th typed-column-lie (class of F-A9-5) | `decision_runs.model_version`, `fork.py:1094` | with taxonomy PR | analytics already one-buckets | stop sourcing identity from `APP_VERSION` |
| A9-3 / F-A9-8 champion job-truth | `fork_errors` populated on champion path | champion clone/tag failure visibility | EXTENDS A4 job-truth | `fork.py:498`, `fork_errors` | with A4 work | silent green today | populate `fork_errors` on champion/legacy path |
| A8-1 ev_below_min basis lie | score-vs-ev basis fix | negative-decision honesty | EXTENDS F-A9-5 | `_log_cohort_decisions:1536-1546`, `policy_decisions` | with taxonomy PR | 56 materialized rows carry the lie | compare score-to-score; re-label existing rows in a doc note |
| A10-1 holiday-blind | `get_calendar` on the alert path | quiet ops before 09-07 | EXTENDS area10 | `is_us_market_hours:46-69` | **hard trigger < 2026-09-07** | false HIGHs on Labor Day | add holiday check to weekday math |
| observe-window durability (W2/W3/W4/W5) | a DB sink for shadow arm decisions | arm decisions | — | `risk_basis_shadow`, `bucket_control`, `calibration_apply_ordering` | before any arm | arming without durable evidence is blind | persist arm-flip counts before enabling |

## 12. Ranked Top 3 + packet/code disagreements + design score

### 12a. Ranked Top 3 (C8 — every field per row)

| Rank | What | Evidence | Value | Effort (single-dev evenings) | Risk | Dependencies / collisions | Backlog interaction | Doctrine check | Falsifier |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **F-MIDDAY-POSITION-READ-FAILOPEN fail-closed (2 sites)** | §9 VERIFIED-CODE (2 sites); source-only "test" today | live-entry safety (highest) | ~0.5 | LOW — healthy & legitimate-empty behavior unchanged; **an unavailable authoritative read intentionally changes the FAILURE path to abort/typed partial before staging** (this tightens failure semantics; it does not loosen a threshold, gate, stop, or healthy-path control) | own lane; sibling of #1195/F-E8-3 | new P1-safety item (escalates P0-before-next-entry per §9) | H9/loud-error — **tightening**, never loosening | read-exception route test stages no entry; genuine empty still stages healthy |
| 2 | **A6-2 versioned live-tier cohort epoch** | §6 A6-2 ATTESTED-RUNTIME ($100k all 3, 48×) | unblocks honest cross-cohort comparability the viable-set/promotion logic depends on | operator design decision (not a dev task) + a later normalization pass | MED — a botched migration could corrupt the pool | first operator decision; F-POLICY-CAPITAL-FALLBACK is a separate code item | freeze cross-epoch promotion until fresh min sample | never rewrite historical rows (measurement integrity) | a **newly versioned** observe-only cohort with an explicit `capital_basis` + clean-boundary proof (NOT mutation of old `net_liq` rows) |
| 3 | **A4-1/A9-2 git_sha one-liner** | §3 + §8 ATTESTED-RUNTIME (12/12 'unknown') | restores decision-tape attribution; unblocks any replay determinism claim (A1/A4-2) | ~0.25 | LOW (additive read) | RC-2 confirms one-liner vs build-arg | with A4/A9 taxonomy | additive provenance, no control change | `decision_runs.git_sha` shows a real SHA after the fallback lands |

### 12b. Packet/code disagreements (high-value)
shadow-capital packet understated (champion is $100k too, 48×); condor code-default (strict) ≠ deployed env (tail); "needs_manual_review as routed success" inverted vs code=critical; git_sha provenance available but unwired.

### 12c. Design-maturity score (C9 — reproducible scalar on the 85/90/95/100 ladder)

**`INFERRED design-maturity score` — not profitability, not measured reliability, not measured efficiency.** Computed from a weighted scorecard; weights sum to 100 and earned points sum to the displayed scalar. The ladder's rungs are 85 / 90 / 95 / 100; **the score cannot exceed the first UNMET rung.**

| Dimension | Weight | State | Earned | Evidence |
|---|---|---|---|---|
| Instrument/tape integrity | 20 | strong | 18 | #1198/#1199 VERIFIED-CODE + 9 blobs/day complete (ATTESTED-RUNTIME) |
| Exclusion-integrity (E1-E20) | 15 | strong w/ 4 conditionals | 13 | §4 (16 PASS, 4 CONDITIONAL) |
| Live-entry safety | 20 | **weak** | 7 | 2 fail-open reads (§9), source-only test |
| Capital/EV/cost coherence | 20 | **weak** | 8 | A6-2 parity (48×) + A6-3 mis-rank + missing canonical-risk |
| Evidence durability (observe windows) | 15 | **weak** | 6 | four windows lack complete durable evidence; only W4 semi-durable, W3 partial (§5) |
| Calendar/clock | 10 | good w/ 1 gap | 8 | A10-1 holiday-blind |
| **Total** | **100** | — | **60** | earned sum: 18+13+7+8+6+8 = **60** |

**INFERRED design-maturity score = 60 / 100.** **First unmet maturity-ladder rung = 85** — the design does not reach the lowest (85) rung, so the score is **capped below 85** (no written exception is claimed). The specific cappers: the known live-entry fail-open on the entry path (§9), incoherent EV/cost/risk bases (A6-3, A8-1), the missing replay-hash reader (A4-2), incomplete observe-window durability (§5), and the **5 `RUNTIME CHECK — NOT RUN` in §7**. Confidence: MODERATE — the strong dimensions (35 wt) are code+runtime verified; the weak dimensions (55 wt) carry the open risk; the missing proof that could move the score is exactly the §7 runtime checks. This is a design-maturity judgement, **not** a live-money score, and `87/100` is **not** reproduced (the computation independently yields 60).

## 13. Charter-completeness matrix (C10 — each requirement linked to a parseable section)

Every v1.5 charter requirement links to a specific parseable section below, or carries an explicit `NOT_PROVEN / RUNTIME CHECK — NOT RUN / DEFERRED-DORMANT / NONE`. **This report is not claimed `FULLY COMPLETE`** — the runtime deltas below are open by design. A row says `populated` only where the named section actually contains the structure (not merely generic prose).

| Charter requirement | Parseable section | Status |
|---|---|---|
| Step-0 grounding | §1 | populated |
| Executive verdict (1 first decision) | §2 (A6-2 epoch) | populated |
| Canonical denominators (separated) | §1a | populated |
| Current-state reconciliation | §3 | populated |
| E1–E20 disposition (PASS/CONDITIONAL/REOPENED/NOT_PROVEN) | §4 | populated (16 PASS, 4 CONDITIONAL) |
| W1–W5 complete (boundary/emitter/sink/sample/reset/bypass/runtime-check/PASS/FAIL/verdict) | §5 | populated (13-column table, one row per window) |
| A1–A10 Pass 1/2/3 prose | §6 | populated; **A7 Pass 2/3 = DEFERRED-DORMANT** |
| A1–A10 Pass 1/2/3 canonical matrix | §14 | populated (one row per area, 3 Pass cells each) |
| Keyed 12-field finding register | §15 | populated (one block per retained finding, 12 fields each) |
| Runtime-check list (read/source/PASS/FAIL/rationale/status) | §7 | populated; all `RUNTIME CHECK — NOT RUN` |
| Instrument-integrity list (natural-proof + exact runtime check) | §8 | populated |
| Free look | §10 | populated (dead-capability cluster; else none) |
| Dependency/collision matrix (8 fields) | §11 | populated |
| Ranked Top 3 (evidence/effort/risk/dep/backlog/doctrine/falsifier) | §12a | populated |
| Packet/code disagreements | §12b | populated |
| Design score (reproducible scalar, weights+earned sum) | §12c | populated (`INFERRED` 60/100, capped <85) |
| EV/PoP/cost/P&L basis+unit on every economic number | §16 + inline tags (§2, §6 A6-3, §8, A8-1) | populated |
| Rejected/duplicate/superseded exclusion memory | §12b + ledger | internal-fill sign = REJECTED; SETTLED/PASS list in the ledger |
| Credential disposition | §1b | `OPERATOR-ATTESTED` class-only |
| DEFERRED-DORMANT items | A7 Pass 2/3; A10-2 NOT_PROVEN | marked |

**Open runtime deltas (why not FULLY COMPLETE):** the 6 `RUNTIME CHECK — NOT RUN` in §7 (RC-1 condor bg-worker env; RC-2 RAILWAY_GIT_COMMIT_SHA presence; RC-3 W2/W3 post-#1198 INFO emit; RC-4 `_rth_job_status` warm-up symmetry; RC-5/RC-6 fail-open injection tests) + A10-2 summer warm-up `NOT_PROVEN`.

## 14. A1–A10 Pass 1/2/3 canonical matrix (C1)

Exactly one row per area. Each Pass cell is explicitly populated; `DEFERRED-DORMANT` is a valid Pass state where the charter permits it.

| Area | Pass 1 (state / exclusion verdict) | Pass 2 (seam / test / instrument verdict) | Pass 3 (dependency / decision-value verdict) | Finding IDs | Retained gap | Rejected gap | Priority | Backlog target |
|---|---|---|---|---|---|---|---|---|
| A1 | replay runner NOT buildable today (capture-starved) | `ReplayTruthLayer.from_decision_id` zero production callers | top A1 extension, gated on A1-1 capture + A5-2 origin | A1-1, A1-2 | capital/OBP/tier/ev_raw not captured | ⑤ make/fetch input-starved (rejected: chain IS captured) | MED | replay-capture + runner (after capture) |
| A2 | watchdog cancel-vs-fill un-idempotent; max_loss scalar-safe | `alpaca_order_handler.py:846-876` unconditional stamp; ghost-sweep loud | double-entry before book holds 2+ live | A2-1, A2-2 | double-entry on cancel-race | assignment/partial-close (DEFERRED-DORMANT, 0 open credit) | MED | cancel-ack idempotency; canonical-position (P1) |
| A3 | shared fetch PASS; premature-stop signal readable | `learning_trade_outcomes_v3` lacks close_reason/thesis_outcome col | un-consumed by any multiplier; DTE double-count trap latent | A3-1, A3-2, A3-3 | premature-stop signal unconsumed | prequential apply (rejected: study tool, zero callers) | LOW | learning-column add (guarded) |
| A4 | classification wired; dead-man fail-safe; bytea symmetric | git_sha constant; replay-hash no reader | git_sha one-liner; hash reader after A1-1 | A4-1, A4-2, A4-3 | git_sha unwired; replay-hash silent | other non-JSON type crossing (rejected: none but #1199) | MED | git_sha fallback; hash reader |
| A5 | FORECAST_V4 gates zero compute; no origin column | `decision_runs` origin/trigger absent | gates A1 replay runner | A5-1, A5-2, A5-3 | no origin/trigger column | tape TTL (rejected: ~11 KB/day, near-zero) | LOW | decision_runs origin column |
| A6 | funnel two-track queryable; all 3 portfolios $100k | ranker structure-agnostic sort of incoherent bases | first operator decision (epoch); condor land with ⑤ | A6-1, A6-2, A6-3 | capital comparability; condor cross-structure mis-rank | thesis LABELS not notional-scaled (rejected as a defect) | HIGH | versioned epoch (operator); EV-basis coherence |
| A7 | 8 post-epoch (9 all-time) closes; 0 in pin week | exit-basis durable; 2/6 gap_fraction computable | Phase-3 gate entry-rate-bound, INDETERMINATE/PAUSED | A7-1, A7-2 | Phase-3 sample entry-rate-bound; exit-basis coverage | DEFERRED-DORMANT Pass 2/3 (no new live fills) | HIGH (dormant) | entry-rate; exit-basis coverage |
| A8 | ev_below_min compares $ ev to score threshold | `_log_cohort_decisions:1536-1546`; 56 materialized rows | negative-decision honesty with taxonomy PR | A8-1, A8-2, A8-3 | ev_below_min basis lie (56 rows) | scanner vs ranker vocab (rejected: separable) | MED | taxonomy PR (score-to-score) |
| A9 | 5th typed-column-lie; git_sha 12/12 unknown; champion job-truth gap | `model_version=APP_VERSION`; `fork_errors` unpopulated on champion path | with taxonomy + A4 work | A9-1/F-A9-6, A9-2, A9-3/F-A9-8, A9-4 | model_version identity lie; champion silent-green | INFO-absence + pooled-live (rejected: RESOLVED #1198/#1201) | MED | taxonomy PR; champion fork_errors |
| A10 | DST-correct but holiday-blind; 5 clock domains distinguished | `is_us_market_hours:46-69` weekday math, no get_calendar | hard trigger before 2026-09-07 | A10-1, A10-2, A10-3, A10-4 | holiday-blind alert path | Fri→Mon scoring lag (rejected: accept ≤72h) | MED | holiday check (< 09-07); A10-2 NOT_PROVEN |

## 15. Keyed 12-field finding register (C2)

One block per retained finding. Every block carries all 12 charter fields and a unique ID. Producer → transformation/failure → consumer is stated in field 4 (no line-number-only findings).

### FR-01 · F-MIDDAY-POSITION-READ-FAILOPEN
- **1. ID / area / severity:** F-MIDDAY-POSITION-READ-FAILOPEN · A2/A8 (live-entry) · HIGH (P1-safety, escalates P0)
- **2. Claim tested:** a failed authoritative position read produces a false-flat book that can reach a live entry.
- **3. Proof label:** VERIFIED-CODE (2 sites).
- **4. Production seam & dataflow (producer→failure→consumer):** `workflow_orchestrator._fetch_positions:2240-2270` (`except→return []`) → false-flat → micro-tier one-at-a-time gate `:2305` → `_stage_order_internal → submit_and_track`; AND `paper_autopilot._get_open_positions_for_risk_check:1328-1343` (`except→alert→return []`) → envelopes pass green-on-vacuum → executor.
- **5. Existing test + reaches seam?:** `test_workflow_orchestrator_positions_query.py` — source-string only, does NOT drive the seam (#1126 costume class).
- **6. Instrument path + durable sink:** Site A silent `print`; Site B `alert()` (durable `risk_alerts`) — neither aborts the entry.
- **7. Impact:** oversized/duplicate live entry on a transient/selective/false-empty read.
- **8. Backlog interaction:** new P1-safety item; sibling of #1195/F-E8-3 (same class, not duplicate).
- **9. Doctrine check / loosens control? / proven error:** H9/loud-error; the fix TIGHTENS the failure path (no loosening); proven error = fail-open defeats `position_scope`'s loud-by-contract raise.
- **10. Smallest operator decision / remediation:** type the unavailable state; make BOTH scan + executor fail-CLOSED; keep `live_ids==[]` as the only legitimate flat path.
- **11. Falsifier:** a read-exception route test that still reaches `submit_and_track`.
- **12. Runtime check required + status:** RC-5 + RC-6 — RUNTIME CHECK — NOT RUN.

### FR-02 · A6-2 shadow-capital epoch
- **1. ID / area / severity:** A6-2 · A6 (viable-set) · HIGH (first operator decision)
- **2. Claim tested:** cross-cohort comparisons are basis-broken because all 3 portfolios use $100k vs a ~$2,068 live book.
- **3. Proof label:** ATTESTED-RUNTIME (net_liq=$100k on all 3 incl. champion; live $2,067.86; ~48×) + VERIFIED-CODE (`or 100000` inert).
- **4. Production seam & dataflow (producer→transformation→consumer):** `init_lab` seeds `net_liq=$100k` → policy-lab P&L/sizing/selection compute on $100k basis → `promotion_normalization` (0.31 discount when enabled) → champion promotion consumes cross-cohort ledgers.
- **5. Existing test + reaches seam?:** `test_docs_consistency` pins the honest scope (doc-level); no code test asserts capital parity (by design — it is an operator epoch decision).
- **6. Instrument path + durable sink:** `policy_lab_cohorts.net_liq` (durable); `promotion_normalization` discount.
- **7. Impact:** raw-dollar P&L/capacity/feasibility/sizing/selected samples not live-tier comparable; thesis LABELS unaffected.
- **8. Backlog interaction:** first operator decision; F-POLICY-CAPITAL-FALLBACK is a SEPARATE fail-closed code item (literal inert).
- **9. Doctrine check / loosens control? / proven error:** measurement integrity; no control loosened; NOT a proven live-money error (comparability, not a loss).
- **10. Smallest operator decision / remediation:** preserve legacy $100k epoch; launch a versioned live-tier observe-only cohort at a clean boundary on one shared capital snapshot; persist `capital_basis`/source/as-of/epoch; freeze cross-epoch promotion.
- **11. Falsifier:** a newly versioned observe-only cohort with an explicit capital basis + clean-boundary proof (NOT mutation of old `net_liq` rows).
- **12. Runtime check required + status:** confirm the new epoch's `capital_basis` persisted at boundary — RUNTIME CHECK — NOT RUN (post-decision).

### FR-03 · A6-3 condor cross-structure mis-rank
- **1. ID / area / severity:** A6-3 · A6 · HIGH (EXTENDS E12/⑤)
- **2. Claim tested:** credit/debit/condor candidates are ranked on incoherent EV/probability bases by one structure-agnostic ranker.
- **3. Proof label:** VERIFIED-CODE.
- **4. Production seam & dataflow (producer→transformation→consumer):** `ev_calculator` writes `suggestion["ev"]` from 3 incoherent bases (credit ≡$0; debit breakeven-delta; condor raw `|delta|`+fixed severity) → `canonical_ranker.py:63,240` sorts structure-agnostically → viable-set ordering before any $-gate.
- **5. Existing test + reaches seam?:** EV drift-guard `test_ev_raw_coalesce_drift_guard.py:32` reaches COALESCE, NOT cross-structure coherence.
- **6. Instrument path + durable sink:** `trade_suggestions.ev` / rank (durable); no cross-structure coherence check.
- **7. Impact:** a condor's cross-structure rank flips on a severity constant → live mis-rank.
- **8. Backlog interaction:** land with ⑤ (make/fetch terminal distribution).
- **9. Doctrine check / loosens control? / proven error:** H9; changing the EV basis is a measurement correction, not a loosening; proven error = severity-constant sensitivity.
- **10. Smallest operator decision / remediation:** put all structures on one coherent terminal-distribution EV basis before the joint sort.
- **11. Falsifier:** a cross-structure ranking regression test whose order is stable under a severity-constant change.
- **12. Runtime check required + status:** observe a live condor rank vs a credit/debit peer — RUNTIME CHECK — NOT RUN.

### FR-04 · A7-1 Phase-3 entry-rate-bound
- **1. ID / area / severity:** A7-1 · A7 · HIGH (DORMANT)
- **2. Claim tested:** the ~10–15-fill Phase-3 gate ETA is close-instrumentation-bound.
- **3. Proof label:** ATTESTED-RUNTIME (8 post-epoch / 9 all-time closes; 0 in the pin week).
- **4. Production seam & dataflow (producer→failure→consumer):** entry throttles (streak-breaker + #1101 + 1-shot/day) → low close rate → Phase-3 instrumentation sample cannot accumulate.
- **5. Existing test + reaches seam?:** none needed (state observation).
- **6. Instrument path + durable sink:** `learning_trade_outcomes_v3` / `position_thesis_outcomes` (durable).
- **7. Impact:** gate ETA is INDETERMINATE/PAUSED, entry-rate-bound — not fixable by more instrumentation.
- **8. Backlog interaction:** Phase-3 stop doctrine preserved; entry-rate is the lever.
- **9. Doctrine check / loosens control? / proven error:** learning-mode (low frequency is a feature); no loosening; not an error.
- **10. Smallest operator decision / remediation:** none — do not loosen a control to manufacture sample.
- **11. Falsifier:** the fill count rises without any entry-throttle change.
- **12. Runtime check required + status:** recount live fills at next close — RUNTIME CHECK — NOT RUN (no new close).

### FR-05 · A7-2 exit-basis coverage
- **1. ID / area / severity:** A7-2 · A7 · MED (EXTENDS-Phase-3)
- **2. Claim tested:** exit-basis corroboration is durable and complete across recent closes.
- **3. Proof label:** ATTESTED-RUNTIME (2 of 6 close orders have a computable `gap_fraction`; 3 most recent fill-only).
- **4. Production seam & dataflow (producer→failure→consumer):** resting-GTC/sweep close path → bypasses stage corroboration → cross/mid NULL in `order_json` → gap_fraction uncomputable for consumers.
- **5. Existing test + reaches seam?:** close-path tests exist; corroboration-coverage not asserted.
- **6. Instrument path + durable sink:** `order_json` (durable, not logs).
- **7. Impact:** measurement quality improvable; sample size cannot be manufactured.
- **8. Backlog interaction:** Phase-3 measurement; not a stop-doctrine change.
- **9. Doctrine check / loosens control? / proven error:** measurement quality; no loosening.
- **10. Smallest operator decision / remediation:** corroborate the resting-GTC/sweep close path at stage time where feasible.
- **11. Falsifier:** a recent close with a computable `gap_fraction` from the sweep path.
- **12. Runtime check required + status:** read `order_json` cross/mid on the next sweep close — RUNTIME CHECK — NOT RUN.

### FR-06 · A2-1 watchdog cancel-ack double-entry
- **1. ID / area / severity:** A2-1 · A2 · MED (EXTENDS-P0-A)
- **2. Claim tested:** a cancel that races a fill can produce a double-entry.
- **3. Proof label:** VERIFIED-CODE.
- **4. Production seam & dataflow (producer→failure→consumer):** idle-watchdog stamps `status='watchdog_cancelled'` unconditionally even when `cancel_order` raises on a just-filled order (`:846-876`) → next poll excludes `watchdog_cancelled` → fill un-polled → suggestion re-executable → new row/new `client_order_id`.
- **5. Existing test + reaches seam?:** watchdog tests exist; cancel-vs-fill race not asserted.
- **6. Instrument path + durable sink:** ghost sweep (loud) → `risk_alerts`.
- **7. Impact:** double-entry (loud via ghost sweep, so MED not HIGH).
- **8. Backlog interaction:** before the book holds 2+ live positions.
- **9. Doctrine check / loosens control? / proven error:** correctness; proven error = unconditional stamp.
- **10. Smallest operator decision / remediation:** check fill state before stamping `watchdog_cancelled`.
- **11. Falsifier:** a cancel-raises-on-fill test that does not re-execute the suggestion.
- **12. Runtime check required + status:** observe a live cancel-vs-fill race — RUNTIME CHECK — NOT RUN.

### FR-07 · A4-1/A9-2 git_sha unwired
- **1. ID / area / severity:** A4-1 = A9-2 · A4/A9 · MED
- **2. Claim tested:** decision-tape rows carry real code provenance.
- **3. Proof label:** VERIFIED-CODE + ATTESTED-RUNTIME (12/12 rows 'unknown').
- **4. Production seam & dataflow (producer→failure→consumer):** capture reads `os.getenv("GIT_SHA")` (Dockerfile `ARG GIT_SHA=unknown`) → `decision_runs.git_sha`/`trade_suggestions.code_sha` = 'unknown' → no drift-attribution consumer.
- **5. Existing test + reaches seam?:** none.
- **6. Instrument path + durable sink:** `decision_runs.git_sha` (durable, constant).
- **7. Impact:** decision-tape attribution absent; blocks replay determinism claims.
- **8. Backlog interaction:** with A4/A9 taxonomy work.
- **9. Doctrine check / loosens control? / proven error:** additive provenance; no control change; proven error = constant 'unknown'.
- **10. Smallest operator decision / remediation:** `getenv("GIT_SHA") or getenv("RAILWAY_GIT_COMMIT_SHA")`.
- **11. Falsifier:** `decision_runs.git_sha` shows a real SHA after the fallback.
- **12. Runtime check required + status:** RC-2 (RAILWAY_GIT_COMMIT_SHA presence) — RUNTIME CHECK — NOT RUN.

### FR-08 · A4-2 replay-hash no-reader
- **1. ID / area / severity:** A4-2 · A4 · MED (NEW)
- **2. Claim tested:** determinism regressions are detectable.
- **3. Proof label:** VERIFIED-CODE (verify_* isolated, zero production reader).
- **4. Production seam & dataflow (producer→failure→consumer):** `compute_aggregate_hash` writes `decision_runs.input_hash/features_hash` → **no** production `verify_*` reader → a hash mismatch is never observed.
- **5. Existing test + reaches seam?:** `verify_*` unit-tested in isolation; not wired to a route.
- **6. Instrument path + durable sink:** `decision_runs.*_hash` (durable, unread).
- **7. Impact:** determinism regressions silent.
- **8. Backlog interaction:** after A1-1 capture.
- **9. Doctrine check / loosens control? / proven error:** additive; no loosening.
- **10. Smallest operator decision / remediation:** add a production reader that alerts on mismatch.
- **11. Falsifier:** a seeded hash mismatch that fires an alert.
- **12. Runtime check required + status:** replay a decision and compare hashes — RUNTIME CHECK — NOT RUN.

### FR-09 · A9-1/F-A9-6 model_version identity lie
- **1. ID / area / severity:** A9-1 = F-A9-6 · A9 · MED (NEW, 5th typed-column-lie)
- **2. Claim tested:** `model_version` is a model identity.
- **3. Proof label:** VERIFIED-CODE.
- **4. Production seam & dataflow (producer→failure→consumer):** `os.getenv("APP_VERSION")` (deploy string) → `decision_runs.model_version` → a `GROUP BY model_version` in calibration/analytics one-buckets every row; `fork.py:1094` already stamps `calibration_provenance_status='not_persisted_on_source'` to work around it.
- **5. Existing test + reaches seam?:** none asserting identity semantics.
- **6. Instrument path + durable sink:** `decision_runs.model_version` (durable, mislabeled).
- **7. Impact:** analytics group-by collapses to one bucket.
- **8. Backlog interaction:** with the taxonomy PR (class of F-A9-5).
- **9. Doctrine check / loosens control? / proven error:** typed-column-lie class; proven error = identity sourced from a deploy string.
- **10. Smallest operator decision / remediation:** stop sourcing model identity from `APP_VERSION`; add a true model-version column.
- **11. Falsifier:** distinct model versions produce distinct `model_version` values.
- **12. Runtime check required + status:** `SELECT DISTINCT model_version` — RUNTIME CHECK — NOT RUN.

### FR-10 · A9-3/F-A9-8 champion-path job-truth gap
- **1. ID / area / severity:** A9-3 = F-A9-8 · A9 · MED (NEW)
- **2. Claim tested:** a champion clone/tag failure surfaces as a partial/failed job.
- **3. Proof label:** VERIFIED-CODE.
- **4. Production seam & dataflow (producer→failure→consumer):** `fork.py:498` sets `status='partial'` on `fork_errors`, but the champion/legacy path never populates `fork_errors` (tag failures `except: pass`; clone-insert failure = fire-and-forget critical alert only) → job returns green (`champion_status='legacy_unmeasured'`).
- **5. Existing test + reaches seam?:** classifier tests cover `counts.errors`, not the champion path.
- **6. Instrument path + durable sink:** `job_runs.status` (durable, green-on-champion-failure).
- **7. Impact:** a champion clone/tag failure is silently green.
- **8. Backlog interaction:** with A4 job-truth work.
- **9. Doctrine check / loosens control? / proven error:** job-truth; proven error = unpopulated `fork_errors` on the champion path.
- **10. Smallest operator decision / remediation:** populate `fork_errors` on the champion/legacy path.
- **11. Falsifier:** an injected champion clone failure that marks the job partial.
- **12. Runtime check required + status:** inject a champion failure; read `job_runs.status` — RUNTIME CHECK — NOT RUN.

### FR-11 · A8-1 ev_below_min basis lie
- **1. ID / area / severity:** A8-1 · A8 · MED (EXTENDS-F-A9-5)
- **2. Claim tested:** `ev_below_min` reflects the real routing gate.
- **3. Proof label:** VERIFIED-CODE + ATTESTED-RUNTIME (56 materialized rows).
- **4. Production seam & dataflow (producer→failure→consumer):** `_log_cohort_decisions:1536-1546` compares dollar `ev` [basis=raw, unit=position-total] to the 0–100 `min_score_threshold` [unit=score-points] while routing uses `score` → `policy_decisions.blocked_reason='ev_below_min'` is a lie (56 rows); `rank_at_decision` on raev not score (secondary lie).
- **5. Existing test + reaches seam?:** negative-decision tests exist; basis mismatch not asserted.
- **6. Instrument path + durable sink:** `policy_decisions` (durable; 56 rows carry the lie).
- **7. Impact:** negative-decision provenance mislabeled.
- **8. Backlog interaction:** with the taxonomy PR.
- **9. Doctrine check / loosens control? / proven error:** honesty; proven error = $-vs-score-points comparison.
- **10. Smallest operator decision / remediation:** compare score-to-score; re-label the 56 existing rows in a doc note (no rewrite of history semantics).
- **11. Falsifier:** a routed rejection whose `blocked_reason` matches the actual score gate.
- **12. Runtime check required + status:** audit `policy_decisions.blocked_reason` vs the score gate — RUNTIME CHECK — NOT RUN.

### FR-12 · A10-1 holiday-blind alert path
- **1. ID / area / severity:** A10-1 · A10 · MED (hard trigger before 2026-09-07)
- **2. Claim tested:** the market-hours check respects exchange holidays.
- **3. Proof label:** VERIFIED-CODE.
- **4. Production seam & dataflow (producer→failure→consumer):** `is_us_market_hours:46-69` uses weekday math (no `get_calendar`) → Labor Day 2026-09-07 (Mon) returns market-open → false `data_stale`/`job_late` HIGHs on the alert path.
- **5. Existing test + reaches seam?:** DST tests exist; holiday not covered.
- **6. Instrument path + durable sink:** `risk_alerts` (durable false HIGHs).
- **7. Impact:** 4–7 false HIGHs per holiday (area10 measured).
- **8. Backlog interaction:** area10; hard trigger < 2026-09-07.
- **9. Doctrine check / loosens control? / proven error:** noise-reduction; proven error = weekday-math on the broker-calendar path.
- **10. Smallest operator decision / remediation:** add a `get_calendar` holiday check to the weekday math.
- **11. Falsifier:** Labor Day 2026 produces zero false HIGHs after the fix.
- **12. Runtime check required + status:** observe alert volume on the next holiday — RUNTIME CHECK — NOT RUN.

### FR-13 · A1-1 replay-capture gap
- **1. ID / area / severity:** A1-1 · A1 · MED (EXTENDS-E19-2B)
- **2. Claim tested:** the tape can answer the raw-vs-calibrated ordering counterfactual.
- **3. Proof label:** VERIFIED-CODE.
- **4. Production seam & dataflow (producer→failure→consumer):** decision capture stores market-data + regime/symbol/ranked_candidates but NOT capital/OBP/tier/open-book/`ev_raw` → `ReplayTruthLayer.from_decision_id` (zero callers) cannot reconstruct sizing/ranking inputs.
- **5. Existing test + reaches seam?:** replay-layer unit tests exist; no production driver.
- **6. Instrument path + durable sink:** `decision_runs` tape (durable, input-incomplete).
- **7. Impact:** replay runner not buildable; counterfactual unanswerable.
- **8. Backlog interaction:** gated on capture + A5-2 origin column.
- **9. Doctrine check / loosens control? / proven error:** additive capture; no loosening.
- **10. Smallest operator decision / remediation:** capture capital/OBP/tier/open-book/`ev_raw` (additive columns, versioned tape).
- **11. Falsifier:** `from_decision_id` reconstructs a full ranking from the tape.
- **12. Runtime check required + status:** attempt a replay reconstruction — RUNTIME CHECK — NOT RUN.

### FR-14 · A5-2 decision_runs origin column
- **1. ID / area / severity:** A5-2 · A5 · LOW (NEW)
- **2. Claim tested:** scheduled vs operator vs replay cycles are distinguishable on the tape.
- **3. Proof label:** VERIFIED-CODE.
- **4. Production seam & dataflow (producer→failure→consumer):** `decision_runs` has no origin/trigger column → all cycle origins collapse → gates A1's replay runner (replay cycles indistinguishable from live).
- **5. Existing test + reaches seam?:** none.
- **6. Instrument path + durable sink:** `decision_runs` (durable, origin-blind).
- **7. Impact:** replay cycles could contaminate live analytics.
- **8. Backlog interaction:** unlocks A1-1 replay runner.
- **9. Doctrine check / loosens control? / proven error:** additive; no loosening.
- **10. Smallest operator decision / remediation:** add an origin/trigger column.
- **11. Falsifier:** a replay cycle is filterable by origin.
- **12. Runtime check required + status:** query cycle origins — RUNTIME CHECK — NOT RUN.

### FR-15 · A3-1 premature-stop signal unconsumed
- **1. ID / area / severity:** A3-1 · A3 · LOW (NEW)
- **2. Claim tested:** a premature-stop-on-a-hit signal feeds a learning multiplier.
- **3. Proof label:** VERIFIED-CODE.
- **4. Production seam & dataflow (producer→failure→consumer):** the signal `thesis=hit ∧ realized_pnl<0 ∧ close_reason=stop ∧ alpaca_live` is readable on `position_thesis_outcomes`, but `learning_trade_outcomes_v3` has **no** `close_reason`/`thesis_outcome` column → no multiplier consumes it.
- **5. Existing test + reaches seam?:** learning tests exist; this signal not wired.
- **6. Instrument path + durable sink:** `position_thesis_outcomes` (durable, unconsumed for learning).
- **7. Impact:** a real premature-stop pattern does not adjust scoring.
- **8. Backlog interaction:** learning-column add (guarded against the DTE double-count trap A3-2).
- **9. Doctrine check / loosens control? / proven error:** additive learning input; no loosening.
- **10. Smallest operator decision / remediation:** add a guarded `close_reason`/`thesis_outcome` column to the learning table.
- **11. Falsifier:** a premature-stop cohort measurably shifts a multiplier.
- **12. Runtime check required + status:** join the signal across tables — RUNTIME CHECK — NOT RUN.

### FR-16 · F-WINDOW-1b reservation/decision identity
- **1. ID / area / severity:** F-WINDOW-1b · W3 (bucket control) · LOW
- **2. Claim tested:** the bucket reservation has a durable identity joinable across scan→executor.
- **3. Proof label:** VERIFIED-CODE.
- **4. Production seam & dataflow (producer→failure→consumer):** `bucket_control` keys on the bucket LABEL (reservation ORDER within one executor process/cycle) but there is **no durable reservation identity and no shared scan→executor cycle/decision identity** (`DecisionContext.decision_id` is a fresh UUID; the runner does not pass `job_runs.id`; the executor heartbeat uses a cohort label as `cycle`) → retry and cross-job joinability UNPROVEN.
- **5. Existing test + reaches seam?:** the arm-evidence clock test pins the split; joinability not asserted.
- **6. Instrument path + durable sink:** `risk_alerts` cap-breach subset (durable); reservation identity absent.
- **7. Impact:** cross-job retry/join cannot be reconstructed.
- **8. Backlog interaction:** doc-hygiene + before any W3 arm.
- **9. Doctrine check / loosens control? / proven error:** additive identity; no loosening; not a live error today.
- **10. Smallest operator decision / remediation:** thread a shared cycle/decision id from runner to handler.
- **11. Falsifier:** a reservation joinable to its originating scan decision.
- **12. Runtime check required + status:** RC-3 (W3 INFO emit) — RUNTIME CHECK — NOT RUN.

### FR-17 · OPTIMIZER_V4/ALLOCATION_V4 dead-capability
- **1. ID / area / severity:** FREE-LOOK · efficiency · NOTE (dead-capability)
- **2. Claim tested:** the V4 optimizer/allocator flags wire real behavior.
- **3. Proof label:** VERIFIED-CODE.
- **4. Production seam & dataflow (producer→failure→consumer):** `core/optimizer_v4.py` + `allocation/capital_allocator.py` have **zero production importers** → `OPTIMIZER_V4_ENABLED`/`ALLOCATION_V4_ENABLED` gate zero behavior (sibling of the FORECAST_V4/REGIME_V4 #1126-family).
- **5. Existing test + reaches seam?:** module-level tests may exist; no production route.
- **6. Instrument path + durable sink:** none (inert).
- **7. Impact:** armed flags imply capability that does not run (audit-surface confusion).
- **8. Backlog interaction:** #1126-family dead-capability cluster.
- **9. Doctrine check / loosens control? / proven error:** DOC≠BUILT; do not cite as live capability.
- **10. Smallest operator decision / remediation:** ledger the dead-capability; retire the flags or wire the modules deliberately.
- **11. Falsifier:** a production importer of either module appears.
- **12. Runtime check required + status:** grep production imports — VERIFIED-CODE (zero); env echo NOT RUN.

## 16. EV / RAeV / score / edge / P&L basis + unit register (C6)

Every economic comparison that drives a finding or ranking carries an explicit basis (`raw | calibrated | realized | unknown`) and unit (`per-contract | position-total | score-points | probability | unknown`). An unknown basis/unit is itself a finding — none are silently chosen here.

| Economic claim | Where | Value | Basis | Unit |
|---|---|---|---|---|
| Realized broker-live P&L | §1a, §2 | 1W/7L ≈ −$178 | realized | position-total |
| Calibration multipliers (floor) | §1 falsifier, A3-3 | ev×0.5 / pop×0.5 | calibrated | ev-multiplier (position-total) / probability |
| Credit-spread EV | A6-3, E12/⑤ | ≡ $0 | raw | position-total |
| Debit-spread EV | A6-3 | breakeven-delta interpolation | raw | position-total |
| Condor EV rank input | A6-3 | raw abs(delta) + fixed severity | raw | probability |
| `ev_below_min` comparison (LHS) | A8-1 | dollar `ev` | raw | position-total |
| `min_score_threshold` (RHS) | A8-1 | 0–100 threshold | n/a | score-points |
| `rank_at_decision` | A8-1 | on raev (secondary lie) | raw | position-total |
| Shadow-vs-live capital ratio | §2, A6-2 | $100k vs $2,067.86 (~48×) | realized | position-total |
| Promotion normalization discount | A6-2 | 0.31 | calibrated | ratio (position-total) |
| Phase-3 exit gap_fraction | A7-2 | 2 of 6 computable | realized | ratio (per-contract normalized) |
| MIN_EDGE_AFTER_COSTS gate | §6 (ranker) | edge floor | raw | position-total |

**STOP.** Read-only report. No production code/config/DB/broker change; nothing merged or deployed.
