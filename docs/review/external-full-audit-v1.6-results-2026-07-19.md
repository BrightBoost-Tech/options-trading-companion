# External Full Audit v1.6 — Ten-Area Current-State Results — 2026-07-19

---

## 1. TITLE · BASES · WINDOW

- **Audit:** External Full Audit v1.6 — Ten-Area Current-State Deep Dive (successor to v1.5).
- **Date:** 2026-07-19 (Sunday).
- **Immutable code basis (pinned, held for the entire report):** `20ca312e789fbb3dd4229edceaf74220d0f178b0` = `origin/main`. Pinned once at start; `origin/main` re-checked at the end of the A9+A10 run and confirmed **unmoved**.
- **Documentation-write basis:** `20ca312e…` on branch `docs/external-audit-v16-results` (the required results artifact `docs/review/external-full-audit-v1.6-results-2026-07-19.md` is authored on this branch; this file is its draft).
- **Deployment basis (VERIFIED-DEPLOYMENT):** BE, worker, and worker-background all **SUCCESS @ `20ca312e`**, container starts **15:10:20–15:10:21Z, 2026-07-19**. FE not separately advanced (UI files Palette/Jules-owned; see §3).
- **Runtime-observation window:** Sunday 2026-07-19, start ~15:12Z. Market **CLOSED**; next open **Mon 2026-07-20 09:30 ET**. Consequence: **no fresh RTH runtime evidence is producible.** Natural absence in this window adjudicates as **DEFERRED-SAMPLE**, never INCONCLUSIVE, and nothing was triggered to manufacture evidence (read-only runtime adjudication).

---

## 2. CLOCK AND MARKET GROUNDING

| clock | value |
|---|---|
| Effective model / subagent policy | Fable orchestrator; every delegated audit agent used **Opus** |
| DB `now()` (Supabase `etdlladeorfgdmsopzmz`) | 2026-07-19 ~15:12–15:17Z (agents grounded across the run; A9+A10 anchor 15:15:01Z) |
| Broker clock (Alpaca LIVE `211900084`) | 2026-07-19 11:12–11:15 ET |
| DB ≡ broker agreement | **Agree** (DB now() ≡ broker clock, ET/UTC offset consistent) |
| `is_open` | **false** (Sunday) |
| Next open | Mon 2026-07-20 09:30 ET |
| Weekend silence | by design |

Broker LIVE `211900084`: ACTIVE, options L3, not blocked. **Equity / cash / options_buying_power = $2,067.86** (uniform), portfolio_value $2,067.86, **0 positions, 0 open orders** → **SMALL tier**. DB `paper_positions` open = **0** (reconciles broker 0/0). `entries_paused=false` (armed; edge-trigger state present). Latest suggestion 2026-07-17 14:10Z; latest staged order 2026-07-15 14:15Z → a correct **no-trade window** (Thu/Fri candidates rejected, no pause). Live is armed: `EXECUTION_MODE=alpaca_live` + `LIVE_ENABLED=True` (VERIFIED-DEPLOYMENT via flag echo).

---

## 3. CURRENT-STATE RECONCILIATION (INTERVENING COMMITS · OPEN-PR OWNERSHIP)

**Source classification of the executed document: `AUDIT_BRIEF_ONLY`.** The executed document `docs/review/external-full-audit-v1.6-current.md` is an audit **specification**, not a results document. The absence of embedded results in it is expected and is **not a finding**.

**Movement from issuance baseline to pin.** Issuance baseline was `fdf5b55cb9f9dc5391f191df3e3876a3c5ded355`. The movement `fdf5b55c → 20ca312e` consists **entirely of this session's own reviewed merges (#1296–#1302)**, including the operator's **#1301** which merged the v1.6 brief itself. Every delta was session-reviewed; one pin (`20ca312e`) was chosen and held; `origin/main` was re-checked at the end of the A9+A10 run and was **unmoved**. Because every intervening commit is a session-reviewed merge already inside the audit's own lane, there is **no out-of-scope delta**.

- PR #1296 — scorable-outcome join readiness + documentation (A7). Merged into the pinned line.
- PR #1299 — TCM-v2 realized accrual extended to the complete fill inventory, observe-only (A1/A6). Merged into the pinned line.
- PR #1300 — signed, read-only **Monday evidence reader**; not a control; test-pinned single-SELECT/no-write-verbs (A10). In the pinned line; first natural output is a RUNTIME-CHECK on Monday ≥17:45Z.
- PR #1301 — merged the v1.6 audit brief (operator).
- PR #1302 — docs commit in the same sequence.

> Characterization note (minor, reconciled): one area agent described `20ca312e` locally as "main `27204bd0` + 2 docs commits #1301/#1302" while the grounding-authoritative A9+A10 agent and the orchestrator state `20ca312e` **is** `origin/main`. Reconciled: `20ca312e` = `origin/main` = `fdf5b55c` + the session-reviewed #1296–#1302 sequence. No pin ambiguity remains.

**Open-PR ownership.** ~40 open **Palette/Jules** PRs own the UI files (TradeInbox / Portfolio / Compose / ThemeToggle). UI/API label honesty is therefore **BLOCKED_UI_FILE_OWNERSHIP** — the collision is reported, not edited around (cross-area check #10). No open PR touches audit / backlog / ledger / policy / fleet / risk / cost / model-review / funnel / market-data territory beyond the session's own merges.

**Governance / fleet state (VERIFIED-DB @ ~15:15Z):** `shadow_fleets` = 1 row `pending_legacy_terminal` (shared_capital=false, micro_ct=50, cap=2000); **50 INACTIVE $2,000 slots**; 50 `shadow_only` `paper_portfolios` (cash=2000, net_liq=2000, uniform; isolated from `paper_orders`/`paper_positions`); **0 bindings, 0 activation receipts**; `FLEET_ACTIVATION_AUTHORIZED=False`. `policy_registrations` = **50/50 approved**, 50 distinct `config_hash`, 0 mismatch, family lineage **17 / 17 / 16**; single-leg opt-in **0/50**. Binding-manifest fingerprint `6f8d14995ff4371bf940364d90bf82de1faff188823cf3e61280b81740836bad`.

**Operator worktree** preserved READ-ONLY; start inventory hash `ddb9e07362a1a26b`; end inventory hash `ddb9e07362a1a26b` — **byte-identical** (start == end; the audit changed nothing in the operator checkout).

---

## 4. EVIDENCE DOCTRINE AND LIMITATIONS

Proof labels used exactly per the brief: `VERIFIED-CODE`, `VERIFIED-TEST-REACH`, `VERIFIED-GITHUB`, `VERIFIED-CI`, `VERIFIED-DEPLOYMENT`, `VERIFIED-DB`, `VERIFIED-BROKER`, `ATTESTED-RUNTIME`, `INFERRED`, `RUNTIME CHECK — NOT RUN`, `NOT-PROVEN`, `REJECTED`, `DUPLICATE`, `SUPERSEDED`. Attestation is never upgraded to verification; a merge is never called deployed; a deployment is never called naturally exercised; a `live_eligible` row is never called broker-live; a shadow outcome is never called live evidence.

**Source precedence:** code (intended mechanics) → Supabase (durable events) → Railway (running code / effective process state) → Alpaca (authoritative for positions, orders, fills, OBP). A disagreement between sources **is** the finding and is not averaged away.

**Binding limitation of this window:** Sunday, market closed, book flat (0/0). No natural scan / stage / close / model-review / fleet-route / evidence-job fired or was triggered. Every "would emit on Monday" instrument is graded **DEFERRED-SAMPLE** with its Monday falsifier stated — never as PASS and never as a defect. The two newest evidence tables (`candidate_terminal_dispositions`, `option_quote_provenance`) are **HONEST-EMPTY** (migrated 07-18, after the last scan; recorders wired and flushed; writers self-activate at the Mon 07-20 11:00 CT scan). A correct no-trade / inactive-fleet / zero-executable outcome is not a defect.

**Read-only statement.** No production code, test (outside docs), migration, DB write, broker write, fleet action, env/config/flag/schedule change, manual scan, deploy, or merge occurred during this audit. All MCP reads were read-only. No secrets, tokens, credential fragments, or raw private payloads appear in this document; only stable public pointers (Alpaca account `211900084`, Supabase `etdlladeorfgdmsopzmz`, Railway project `empowering-commitment`) are cited per CLAUDE.md.

---

## 5. INSTRUMENT-INTEGRITY TABLE (merged, all areas)

`instrument | emitter | boundary | durable sink | reader/consumer | test reach | natural proof | verdict | limitation`

| instrument | emitter | boundary | durable sink | consumer | test reach | natural proof | verdict | limitation |
|---|---|---|---|---|---|---|---|---|
| Frozen TCM stamp | `paper_endpoints._stage_order_internal` | stage seam | `paper_orders.tcm` | realized_cost_study / cost_basis | yes | **188/189 filled stamped** | GOOD | one legacy fill unstamped |
| TCM v2 dual-run stamp | `paper_endpoints.py:776` | every route | `paper_orders.tcm.tcm_v2_proposal` | realized_cost_study accrual | route test | **0/528** | HONEST-EMPTY | no stage cycle since #1278 deploy (07-19); latest order 07-15 |
| Realized-cost-study spine | `STUDY_SQL` | read-only `paper_positions⋈paper_orders` | study CLI (non-durable) | study CLI | yes | **86/86 closed w/ sugg+PL; complete fill inv.** | GOOD | ranker basis 0/86 |
| `should_submit_to_broker` veto | `execution_router.py:210` | submit gate + alerts | (gate; critical alerts) | 4 submit sites | yes | **42 broker fills all live_eligible; 0 single-leg live** | GOOD | veto DARK (0/50 opt-in) |
| Broker commission | `alpaca_fill_reconciler` | reconcile | `paper_orders.fees_usd` | realized_commission | yes | **42/42 = $0** | GOOD | $0 options today |
| cost_reconciliation_artifact | `candidate_disposition` recorder | record | `candidate_terminal_dispositions.detail` | none (non-decisional) | yes | **0 rows** | HONEST-EMPTY | zero code readers; DEFERRED-SAMPLE |
| candidate terminal disposition | `CandidateDispositionRecorder` (`workflow_orchestrator.py:2734`) | finalize @ H7/allocator/quality/risk/sizing/rank/persist seams | `candidate_terminal_dispositions` | none (observe-only) | wired seam tests | **0 rows** (HONEST-EMPTY, self-activates Mon) | HONEST-EMPTY | lifecycle stops at persist (staged/broker_submitted/filled unwired) |
| quote/OI provenance | `QuoteProvenanceRecorder` (`options_scanner.py:2878`) | snapshot/chain boundary; always-persist rejected+selected | `option_quote_provenance` | none (observe-only, no gate) | wired seam tests | **0 rows** (HONEST-EMPTY, self-activates Mon) | HONEST-EMPTY | OI known-at always unavailable (`oi_freshness=known_at_unavailable`) |
| canonical max-loss `_pos_risk` | `risk_envelope` | `normalize_position→analyze_payoff` | envelope result (in-mem) | LIVE concentration/loss/stress | `test_position_model` | 0 positions → no fire | SOUND | — |
| canonical signed greeks / greek-cap CF | `risk_envelope` | `check_all_envelopes` | `job_runs.result` (monitor `_compact_greek_cf`) | observe telemetry | tests | `legs_with_greeks=0` & `would_block=None` expected | SOUND-DORMANT | §8 double-dormancy |
| exit-trigger corroboration `corroborated_exit_upl` | `exit_mark_corroboration` | `executable_close_estimate` | decision-time per-position | LIVE stop/TP/cohort triggers | tests | 0 positions → no fire | SOUND | raw-fallback = fire-if-past |
| close custody `close_position_shared` | `close_helper` | conditional-UPDATE CAS | `paper_positions(status=closed,qty=0,realized_pl)` | 4 close handlers | tests | 7 closes/30d, 1 sign-corrected | SOUND | paper_positions-only |
| close-fill-gap sign | `alpaca_order_handler.py:672-677` | `broker_fill_to_mark_basis` | `paper_orders.order_json` | Phase-3 gate (observe) | tests | negation-mapped (15.08→1.42) | SOUND | observe-only |
| tier taper | `tier_taper.observe` | `workflow_orchestrator.py:2442` | `job_runs.result.cycle_metadata.tier_taper` | none (DARK) | `test_tier_taper` | equity $2,067 out-of-band → identity | SOUND-DARK | band `[900,1100]` ≠ ratified `[800,1000]` |
| premium-basis shadow | `risk_basis_shadow` | `RBE:418` / `util_gate:353` | logs `[RISK_BASIS_SHADOW]` | `choose_basis` (flag OFF) | tests | **ARM EVIDENCE ABSENT** — the exact P0-B arm-decision / `would_flip` comparison has not emitted or reached a durable evidence contract (historical generic lines, e.g. `basis=null_legacy` / heartbeats for `rbe_open_book`-class consumers, do not satisfy the gate) | **DEGRADED-INSTRUMENT** | arm gate cannot clear on generic/ephemeral lines |
| nightly completion contract | `NightlyRunner.run` | cron.log append + report/manifest copy-back | `audit/cron.log` (gitignored), manifests/, reports/ | operator + dead-man provider | route-driven runner tests | 07-19: manifest+report+transcript OK, **cron.log markers absent** | **PARTIAL/HIGH** | contract "met" on in-memory flag while sink empty; ping decoupled from evidence |
| flag echo #1268 | `echo_effective_flags` | INFO log | Railway deploy logs (ephemeral) | operator | `test_flag_echo` (route + registry-drift) | `[FLAG_ECHO]` @15:11:33Z BE, 30 flags/0 errors | CLEAN | log-only, no DB sink |
| job_runs status | jobs runner | DB write | `job_runs.status/result` | ops_health, A4 detector | — | 519 succ / 1 canc / 0 partial (4d) | CLEAN | succeeded-with-errors only via `result.errors` (paper_learning_ingest) — §8 known |
| alerts / relay / dead-man | `alert()` + relay + runner ping | webhook / curl | `risk_alerts` + provider | operator inbox | — | 0 crit/high 72h | CLEAN baseline | 07-19 dead-man ping unconfirmed at provider (folds into wrapper) |
| deployment identity | Railway | container | Railway deploy | operator | — | 3 svc SUCCESS @`20ca312e` | CLEAN (H8) | — |
| HMAC signed-task | `task_signing_v4` | header verify | `task_nonces` / reject | `public_tasks` routes | route test un-skipped; **unit suite skipped #768** | fleet route drives real HMAC | PARTIAL | replay/expiry/fail-open unverified in CI (F-A9-2); prod-detector divergence (F-A9-1) |
| policy registry / fleet | `shadow_fleet_activation` | RPC | `policy_registrations` / `shadow_fleets` | plan/execute | `test_shadow_fleet_activation_route` (real route + real HMAC) | 50/50 approved, fleet inactive, 0 receipts | CLEAN | activation correctly forbidden |

**Instrument headline:** the only non-GOOD/non-CLEAN durable instruments are (a) the **nightly completion contract** (PARTIAL/HIGH — the F-RUNNER-WORKTREE-DEADFALLBACK root cause), (b) the **premium-basis `[RISK_BASIS_SHADOW]`** evidence chain (DEGRADED-INSTRUMENT — the exact P0-B arm-decision / `would_flip` evidence has not emitted or reached its expected durable evidence contract; historical generic risk-basis lines do not satisfy that gate — blocks the P0-B arm), and (c) **HMAC signed-task** (PARTIAL — behavioral suite skipped). Everything else is GOOD/CLEAN or truthfully HONEST-EMPTY/DARK.

---

## 6. PREDECESSOR / NON-REDISCOVERY DISPOSITION TABLE

The ledger is exclusion memory. Every item below is **SETTLED / dark / owned** unless a current-state contradiction was proven. No contradiction was found for any; each restatement is `DUPLICATE`. Non-rediscovery is absolute — the items in the lower block appear only here and in §11, never as a new finding.

| settled/dark item | area(s) | current-state disposition |
|---|---|---|
| Options-level entry preflight; closes/shadow exemption | A6 | SETTLED — 4-site veto + fail-closed submit gate |
| Lifecycle typed degradation for entries | A3/A6 | SETTLED |
| F-BAN phantom feature removal (#1280) | A3 | SETTLED — do not cite `banned_strategies` as live |
| F-CREDIT-SIGN code fix + fingerprinted historical correction | A2/A7 | SETTLED — 1 live `alpaca_fill_reconciler_sign_corrected` row; no double-correction; corrected rows `is_paper=true` never reach live calibration |
| Broker/account reconciliation + fail-closed OBP reads | A2/A6 | SETTLED — 0/0 clean at window; OBP $2,067.86 |
| H7 parent + mandatory typed subreason (#1281) | A3 | SETTLED code-CONFIRMED; natural rows DEFERRED-SAMPLE (0 rows) |
| Candidate terminal dispositions + quote/OI provenance schemas | A3/A5 | SETTLED, HONEST-EMPTY (migrated 07-18 post-scan) |
| Source-label correction (#1271) + A5-2 job-origin provenance | A5/A9 | SETTLED (origin in `result` jsonb) |
| Decision `git_sha` + ranking-cost / code-sha writer coverage | A1 | SETTLED; ranking_costs realized overlap 0/86 → see A1-G1 (LOW) |
| Canonical max loss, payoff-capped stress, signed Greek aggregation, D3 ratio-aware full-contract count (#1290) | A4 | SETTLED — no greek defect remains pinned |
| Tier taper, Greek caps, single-leg experiment, OI floors, TCM-v2 | A3/A4/A5/A6/A7 | SETTLED-DARK / observe-only; none activated |
| ⑤ terminal-distribution foundation, scan-time spot/IV/delta, scorable-join (#1296), event-driven review (#1286) | A7 | SETTLED; natural chain DEFERRED-SAMPLE (0 scorable closes) |
| Policy registry 50 approved hash-valid + fleet provisioned inactive | A8 | SETTLED-INACTIVE; every count matches ledger, no drift |
| E19-2B preregistered protocol execution-gated | A7/A8 | SETTLED/BLOCKED; hash `50e7e237…` untouched |
| Test honesty, SQL-mirror parity (#1291), fork/collection sweeps | A9 | SETTLED — #1291 0 defects; no source-pin costume observed |
| Three evidence/fleet migrations + registry/H7 migrations applied; never-reapply | A3/A8/A10 | SETTLED — all applied+tracked; no double-apply |
| Correct no-trade outcome is not a failure | all | Acknowledged — flat book / 0 executable is correct, not a defect |
| **WRAPPER_PARTIAL** (nightly-runner P1) | A9 | Owned/OPEN — F-RUNNER-WORKTREE-DEADFALLBACK **EXTENDS** it (root cause), not a re-find |
| **F-RUNNER-BROKER-CREDS** | A9 | DUPLICATE (ledgered; snapshot `available:false` re-confirmed) |
| **Taper band `[900,1100]` vs ratified `[800,1000]`** | A4/A8/A10 | DUPLICATE — owned DARK-state governance reconciliation |
| **Shadow-fill fiction** (100% fills, 5–17× live size) | A2/A7 | DUPLICATE (ledgered `shadow_fill_realism.md`) |
| **Greeks double-dormant** (now single-dormant per §8; caps still 0) | A4 | DUPLICATE — §8 known-liar; not live protection |
| **EXIT_EVAL_DEBUG partial-fix** (no-cohort default path) | — | DUPLICATE (ledgered A9-F9) |
| **Severity-taxonomy fragmentation** (`medium`/`warn` invisible to `warning` filters) | A9 | DUPLICATE (ledger-queued taxonomy PR) |

---

## 7. A1–A10 THREE-PASS RESULTS

### A1 — ECONOMIC EDGE, PROFITABILITY, COMPARABLE UNITS
- **Pass 1 (state/exclusion).** Frozen TCM (`transaction_cost_model.py:93 TransactionCostModel`, VERSION 1.1.0) is the sole decision-cost authority; TCM v2 (`services/tcm_v2_proposal.py`, `tcm_v2_proposal/0.1.0`) is observe-only (`ENABLE_LIVE_TCM_MODEL`/`PROMOTE_TCM_V2` false, feeds no rank/gate). Ranker `canonical_ranker.py:24 MIN_EDGE_AFTER_COSTS=$15`, `:25 DEFAULT_FEE_PER_CONTRACT=0.65`. All settled (#1273/#1278/#1289/#1299). No exclusion-memory contradiction.
- **Pass 2 (seam/test-reach).** Realized-cost-study spine (`realized_cost_study.py STUDY_SQL:131`) selects **all** closed positions ⋈ filled orders — **no selection bias** (VERIFIED-DB: 86/86 closed carry suggestion_id + realized_pl; complete fill inventory). COMPARE-never-SUM; cohorts partitioned; H9 typed-UNAVAILABLE; version-segregation on `(cohort, v2 model_version)`; dedup `{record_id}:{side}`. Multi-fill accrual (`_split_fill_inventory:1228`, `_sum_components_total:1270`) fill-complete: side-flip boundary = first nonzero fill flipping the opening side; 4 zero-qty artifacts dropped to `zero_fill_rows`; mixed-routing → side typed UNAVAILABLE; version mixing → `mixed:v1+v2`. Test-reach via `test_realized_cost_study_multifill.py`, `test_realized_cost_study_tcm_v2_accrual.py`.
- **Pass 3 (adversarial).** Primary Q ("same candidate profitable under one hidden basis, unprofitable under another, report omits difference?") **refuted as a defect:** the one real cross-basis divergence (frozen 0.65/leg/contract/side vs broker realized $0, #1273 `−1.55` mean over-charge) is *surfaced* by both TCM v2 dual-run and the study's typed deltas, and its direction is a **tightening** (ranker overstates cost → rejects some genuinely-profitable candidates), never a loosening. Natural cross-basis overlap is near-empty.
- **Retained (A1-G1, LOW).** ranker_model cost basis has **zero realized overlap**: `trade_suggestions.ranking_costs` present on **0/86** realized round-trips, only 2/265 suggestions total (both 07-16/07-17, after the last close); `candidate_terminal_dispositions` = 0; `filled_with_tcm_stamp=188/189`. Evidence-completeness, not correctness (typed-UNAVAILABLE, not fabrication). Seam `realized_cost_study.py:244` / persist `canonical_ranker.py:65`. VERIFIED-DB.
- **Maturity — code/instrument 8 · natural-runtime 4.**

### A2 — LOSSES, EXITS, CLOSES, POSITION CUSTODY
- **Pass 1.** Custody reconciles cleanly (broker 0/0, DB 0 open). Single-submitter intact: `paper_exit_evaluator._close_position:1705` is the sole close submitter; canonical writer `close_helper.close_position_shared:158` is a compare-and-swap `UPDATE … WHERE id=? AND status<>'closed'`, raising `PositionAlreadyClosed` loudly (never a silent no-op), setting `quantity=0`/`realized_pl`/`closed_at` atomically. F-CREDIT-SIGN present and fingerprinted-settled; the 1 live sign-corrected row is the reconciler path, no double-correction.
- **Pass 2.** Close-fill-gap **sign fix VERIFIED-CODE** at `alpaca_order_handler.py:672-677` (`broker_fill_to_mark_basis` negation-maps the broker net-combo fill onto the signed mark basis; replaces the pre-07-08 `abs()` that stored QQQ `gap_fraction 15.08` vs true `1.42`), observe-only into `order_json`. Exit-trigger basis executable-corroborated: `_corroborate_positions_for_exit:1527` swaps `unrealized_pl` for `corroborated_exit_upl` (`exit_mark_corroboration.py:487`), **raw-fallback = fire-if-past, never a suppressed stop**. Resting-TP single-owner skip (`:1915`) and the **CLOSE_QUOTE_VALIDATION DEFER placed BEFORE `submit_and_track`'s pre-cancel** (`:1997-2026`) so a defer can never strand a naked leg. Partial fills → `compute_realized_pl` raises `PartialFillDetected`, caller writes critical alert and does NOT close.
- **Pass 3.** Primary Q ("closed in one subsystem while custody open elsewhere?") — no live counterexample at the pin (CAS + `quantity=0` + idempotency guard + resting-TP owner skip + DEFER-before-pre-cancel; broker/DB agree 0/0). **Residual (NOT-PROVEN):** assignment/exercise + at-expiry residual-quantity custody was not traced to a handler; runtime close firing is DEFERRED-SAMPLE (0 open positions).
- **Retained (A2-ASSIGNMENT, LOW / NOT-PROVEN → DEFERRED-SAMPLE).** No assignment/exercise consumer found; defined-risk spreads carry `dte_threshold`/`expiration_day` reasons but no confirmed broker-assignment reconciliation path. Seam `paper_exit_evaluator._close_position` / `alpaca_order_sync` (no assignment consumer).
- **Rejected/duplicate.** `reconcile_legs` (`position_model.py:766`) has zero production callers → DUPLICATE of ledgered **A2-2** (`backlog.md:708`). F-CREDIT-SIGN idempotency, canonical max-loss/stress vs close outcomes → SETTLED.
- **Maturity — code/instrument 8 · natural-runtime 6.**

### A3 — STRATEGY FUNNEL, VIABLE SET, ACCOUNT AFFORDABILITY
- **Pass 1.** Selector = four verticals + iron condor (pre-existing); `long_call`/`long_put` added only by #1287's single-leg experiment, confirmed DARK (0/50 opt-in + two-layer guard). Disposition writer + H7 typed-subreason (#1281) live and wired. No code/docs/runtime disagreement; ledger/backlog current through #1300.
- **Pass 2.** `CandidateDispositionRecorder` constructed in the real cycle (`workflow_orchestrator.py:2734`), finalizes at every production seam (H7 prefilter `2835`, allocator_dropped `2955`, quality_gate E4/E5 `3311/3792/3848`, risk_budget `3554`, sizing_zero `4115`, rank_blocked `4082`, persisted_executable/blocked `4367/4381`). Every `h7_dropped` carries exactly one `detail['h7_subreason']`; writer strict-raises in dev/test, fail-soft `unspecified` sentinel in prod (`candidate_disposition.py:524-546`) — closes the #1272 E4/E5 invariant hole. Submit-seam single-leg veto (#1292) threads `order=` at all 4 `should_submit_to_broker` call sites; generator fail-closed to dark, refuses `live_eligible` batch wholesale (`single_leg_experiment.py:587-605`).
- **Pass 3.** Adversarial ("every disappeared candidate has one durable truthful disposition") HOLDS for selection→persist. Strongest counterexample = **disposition lifecycle stops at persist**: `staged`/`broker_submitted`/`filled` are in the taxonomy (`candidate_disposition.py:82-85`) with zero production call sites (docstring `:48-49` admits "reserved for the executor phase"). Blast radius NIL (observe-only). No narrower structure would pass a gate a correct gate blocked.
- **Retained (A3-LIFECYCLE, LOW/NOTE).** Lifecycle terminates at persist; three executor-phase disposition values unwired. Seam `candidate_disposition.py:82-85` (+ docstring `:48-49`). VERIFIED-CODE.
- **Maturity — code/instrument 8 · natural-runtime 2** (HONEST-EMPTY, self-activates Mon).

### A4 — RISK, SIZING, CANONICAL POSITION TRUTH
- **Pass 1.** Canonical position model rigorous; greek/stress/max-loss lane fully migrated: `_pos_risk` (`risk_envelope.py:263`) uses `normalize_position→analyze_payoff.max_loss_total` (position-total, never re-×qty); D2 signed aggregation and **D3 ratio-aware `leg_full_contract_count` (#1290, `position_model.py:949`)** wired into BOTH `check_greeks:392` and `compute_stress_scenarios:1190`; stress payoff-clamped at `-Σ max_loss_total`, raw phantom preserved in `*_raw`. Non-rediscovery SETTLED.
- **Pass 2.** D3 helper composes byte-identically to `aggregate_greeks` on the persisted full-count convention (1×2 scales twice; 1:1 byte-identical). Canonical signed greeks + enforcement-free greek-cap counterfactual flow **observe-only** into `job_runs.result` via `intraday_risk_monitor.py:637` (`_compact_greek_cf`, "arms nothing"). LIVE envelope decisions (concentration block, per-symbol/daily/weekly loss force-close, stress warn) DO use canonical `_pos_risk`; loss force-close reads corroborated `unrealized_pl`. **Greeks/caps double-dormant** (§8): legs carry no greeks, all four caps default 0 → `passed` byte-identical.
- **Pass 3.** Primary Q ("any live/report consumer computing exposure from a parallel, ratio-blind, sign-blind, or placeholder representation?") **YES, and it is owned/dark:** `RiskBudgetEngine.compute` (`risk_budget_engine.py:365 _estimate_risk_usage_usd`) and the #1044 utilization gate (`utilization_gate.py:334`) cost exposure on the **premium/cost basis**; canonical `max_loss_total` is computed alongside but decisive only under `RISK_BASIS_MAX_LOSS_ENABLED=1` (default OFF → byte-identical). Real bite: the open book is costed ~$0 in utilization and CREDIT/IC max-loss understated (QQQ-IC ~$149 premium vs ~$372 max loss) — the **P0-B book-scaling epic** (`backlog.md:1365`), GATED on an owner arm decision after ~1 week of shadow logs. Second adversarial (declining equity raising live risk): the **micro↔small hard cliff** is a live monotonicity violation (at ~$999 micro `0.90×equity≈$899` vs ~$1,001 small `0.85×equity≈$851`), documented in `tier_taper.py:37-38`; at current $2,067.86 the cliff is ~$1,068 of drawdown away (not active). The fix (`tier_taper.decide/observe`, #1283) is DARK (observe payload only; band `[900,1100]` vs ratified `[800,1000]` pending).
- **Retained (A4 · two).**
  - **F-A4-RISKBASIS-SILENT (MED).** Sizing/utilization stay on premium basis and the exact P0-B arm-decision / `would_flip` evidence that gates arming `RISK_BASIS_MAX_LOSS_ENABLED` **has not emitted or reached its expected durable evidence contract** (`risk_basis_shadow.py:31` ← `risk_budget_engine.py:418`, `utilization_gate.py:353`; ledger.md:1030/1236). Historical generic `[RISK_BASIS_SHADOW]` lines (e.g. `basis=null_legacy` and heartbeat variants for consumers such as `rbe_open_book` / `allocator_open_book`) do not satisfy that gate — and log lines are ephemeral, not a durable evidence sink → the observe→enforce gate cannot clear on what exists today. VERIFIED-CODE + VERIFIED-DB(ledger). P0-B + A9 marker-silence.
  - **A4-DIVISIBILITY (LOW-INERT).** `check_greeks` D3 path lacks the `_pos_risk`/normalize divisibility guard that `compute_stress` gets first — a non-divisible leg would be scaled by raw full-count instead of rejected. Seam `risk_envelope.py:392`. Decision-affecting only if caps armed AND greeks populated (both dark). VERIFIED-CODE.
- **Maturity — code/instrument 8 · natural-runtime 5.**

### A5 — MARKET DATA, LIQUIDITY, OI, KNOWN-AT PROVENANCE
- **Pass 1.** Truth layer = Alpaca primary → Polygon fallback with 429/500/502/503/504 retry adapter (`market_data_truth_layer.py:733`). Quote/OI provenance (#1285) + source-label repair (#1271) + scan-time spot/IV/delta (#1259/#1266/#1274) present. `option_quote_provenance` OBSERVE-ONLY, no gate; OI has NO live floor (`ENABLE_LIVE_OI_FLOOR` unbuilt). No decision/provenance disagreement.
- **Pass 2.** `QuoteProvenanceRecorder` constructed in the live scan (`options_scanner.py:2878`), attached to the truth layer (`:2896`), `mark_selected` on emit (`:4463`), single `flush()` at cycle end (`:4634`). Boundary events wired in the real fetch path (`record_snapshot_boundary` `truth_layer:946`, `record_chain_boundary` `:1597`); `fetch_meta["requests"]` captures HTTP status + 429 + error per request/page. Quote notes carry bid/ask/mid/`quote_ts_ms`/`stale_age_ms`/`crossed`/`zero_bid`/requested_at/received_at (`quote_provenance.py:418-433`); spread verdict records the gate's own verdict/threshold + `spread_basis.denominator_basis`. Exact-leg OI (`_build_oi_by_contract` `:1037`, `resolve_leg_oi` `:232`) preserves the H9 0-vs-absent distinction (`coerce_oi`: 0→0 real, None/neg→unavailable), computes per-floor pass/fail/**indeterminate** counterfactuals. Stage-time spot/IV/greeks stamped into `order_json` BEFORE the exec-mode branch (`paper_endpoints.py:804-811`), typed-unavailable never fabricated. Single persistence seam scrubs secret-named keys + apiKey/Bearer patterns; deterministic 1-in-N sampling + hard cap; always-persist for rejected+selected leg sets.
- **Pass 3.** Adversarial ("verdict attributed to a stale/relabeled/sampled-away quote/OI/source") REFUTED for decisions (recorder observe-only, never feeds the gate; rejected+emitted always-persist). Strongest honest residual = **OI freshness structurally unobservable**: `market_data_truth_layer.py:1856` sets oi/provider_ts but not `open_interest_date`; `_build_oi_by_contract:1063` reads a key the chain never sets → `oi_known_at` always None → `oi_freshness` always `known_at_unavailable`. Blast radius NIL.
- **Retained (A5-OI-KNOWNAT, LOW/NOTE).** OI `open_interest_date` never threaded; every OI observation freshness-unknown. Seam `quote_provenance.py:261-266` + `market_data_truth_layer.py:1856`. VERIFIED-CODE.
- **Maturity — code/instrument 8 · natural-runtime 2** (HONEST-EMPTY, self-activates Mon).

### A6 — EXECUTION, BROKER, ORDERS, TRANSACTION COSTS
- **Pass 1.** `should_submit_to_broker` (`execution_router.py:210`) is the real submit seam: gates on `routing_mode=='live_eligible'`, **fail-closed False** on missing/query-error (critical alert), plus single-leg experiment hard veto (`is_single_leg_experiment_row`, returns False regardless of routing). 4 order-passing call sites confirmed: `paper_endpoints.py:933`, `paper_exit_evaluator.py:2004` + `:2221`, `brokers/safety_checks.py:272`. Single-leg registry opt-in 0/50 → veto DARK. Settled (#1292).
- **Pass 2.** TCM v2 dual-run stamp at `paper_endpoints.py:776` into `paper_orders.tcm.tcm_v2_proposal` on every route, OPEN+close, fail-soft. Routing classifier `classify_routing:122` mirrors the submit gate; unknown routes → INTERNAL (fail-safe never understate cost). Realized commission per-routing: broker-routed → KNOWN `fees_usd`; internal → UNAVAILABLE; multi-fill mixed → side UNAVAILABLE. VERIFIED-DB: **42/42 broker-routed filled orders carry `fees_usd=0`**; 120 internal fills. Test-reach `test_single_leg_submit_seam_veto.py`, `test_routing_dispatch_pr2a/b.py`, `test_tcm_v2_dual_run_route.py`.
- **Pass 3.** Primary Q ("shadow/blocked/unpriceable path reaching broker, or a broker fill missing a durable sink?") **refuted:** veto + live_eligible gate + fail-closed-on-missing at all 4 sites; internal-fill P0-A guard keys on the same seam. Broker reconciliation clean (0 positions, 0 open, 15 most-recent orders all `mleg` — no single-leg live order, latest broker activity 07-08 QQQ). Signed-fill unreliability is live-present (a filled sell shows `filled_avg=-1.49`) — correctly handled magnitude-only.
- **Retained: NONE new.** The one measurable-but-empty item is TCM v2 natural accrual → DEFERRED-SAMPLE.
- **Maturity — code/instrument 8 · natural-runtime 5.**

### A7 — LEARNING, CALIBRATION, TERMINAL DISTRIBUTION, MODEL REVIEW
- **Pass 1.** All pillars SETTLED, current state matches ledger. Live-only calibration quarantine (`CALIBRATION_TRAIN_LIVE_ONLY` default-ON, `calibration_service.py:55-68,391`) holds; F-CREDIT-SIGN corrected rows are `is_paper=true` and training filters `is_paper=false` → no double-correction into live. ⑤ scorable-join (#1296) documented COMPLETE; event-driven review (#1286) observe-only/inert; E19-2B frozen+BLOCKED. No disagreement.
- **Pass 2.** Detector wired for real: `paper_learning_ingest.py:192-199` calls `model_review.evaluate_and_maybe_enqueue_review(client)` as a fail-soft tail; return flows into `job_runs.result.model_review:212` (VERIFIED-CODE). Scorability = the study's own mapper (`is_scorable_row:248-264` → `challenger_study.to_foundation_row`, requires `spot` + every leg `iv`+`delta`, **STATUS-gated not source-gated**; historical rows H9). Test-reach (#1296): `test_scorable_join_readiness.py` drives the REAL producers end-to-end and asserts top-level outcome (scorable→exactly-one enqueue, provenance, cohorts separate, `client.writes==[]`) — injects at deepest callee, asserts at top → VERIFIED-TEST-REACH, #1126-safe. Idempotency: content fingerprint = sorted scorable ids ⊕ `MODEL_SET_VERSION`, durable 3 ways; cohorts kept separate; corrected-flag routed through #1042 quarantine. E19-2B: `test_e19_2b_preregistration.py` hashes the real doc (`50e7e237…`), asserts BLOCKED/false/UNDEFINED.
- **Runtime (VERIFIED-DB 15:17Z).** `learning_trade_outcomes_v3` = 102 total / **8 live** / 94 shadow / 0 null. `paper_orders` carrying `entry_underlying_spot` marker = **0**; v3-closed rows with a marker-carrying open order = **0** ⇒ **scorable-close count = 0 (DEFERRED-SAMPLE)**. `model_review_event` job_runs = **0** (review correctly never fired). Calibration: `total_outcomes=8`, `_overall` only, `ev_multiplier=0.5` & `pop_multiplier=0.5` (both at the 0.5 clamp floor), `ev_calibration_error=65.34`, computed 07-17 10:00Z (weekend-silent, not stale, `MAX_AGE_DAYS=10`). The 8 live are post-EV-epoch (2026-06-11); `sample_size==live count` → live-only quarantine re-confirmed.
- **Pass 3.** Strongest counterexample: model-review fingerprint keys on the scorable id-SET not row CONTENT → a post-hoc correction to an already-reviewed row would not re-fire. Blast radius **nil** (observe-only, `client.writes==[]`, mutates no selector/ranker/gate/calibration) → NOTE (N2), not a gap. The clamp state (both multipliers floored at 0.5, 65% EV over-prediction) is the doctrine "8th-close clamp review" — already owned (`backlog.md:1183-1185, 1634-1635`, settled 07-09: HOLD clamp, revisit ~15-20 live closes; winsorize NO-ACTION). Clamp direction is do-no-harm (halves EV → tighter entries).
- **Retained: NONE new** that outrank backlog.
- **Maturity — code/instrument 8 · natural-runtime 3** (producer chain zero natural proof; calibration only 8 clamped samples).

### A8 — FLEET, POLICY REGISTRY, EXPERIMENTAL DESIGN
- **Pass 1.** Registry + fleet provisioning SETTLED-INACTIVE; runtime matches every ledger/backlog count, no drift. `ACTIVATE_FLEET=false`, 0 bindings, 0 activation receipts.
- **Pass 2 (VERIFIED-DB unless noted).** `policy_registrations` @ epoch `small_tier_v1` = **50 rows / 50 distinct config_hash / 50 distinct config_canonical / 0 hash-mismatch / 50 approved / 0 non-approved**. Structure = **3 anchors + 39 single-axis + 8 two-axis + 0 (>2)**; lineage aggressive 17 / neutral 17 / conservative 16. `max(stop_loss_pct)=0.30` across all 50 ⇒ **no variant widens the live stop** (hull ceiling = live champion stop). Server-derived hash `config_hash == encode(digest(config_canonical,'sha256'),'hex')` for all rows. Seed-vs-design byte-fidelity cross-check: the three anchor `config_canonical` strings match `fleet_policy_design.py` canonicalization exactly (aggressive hash `441ace2f…`, recompute-clean; anchors reflect DB truth stop 0.30). Provisioning: `shadow_fleets`=1 (`pending_legacy_terminal`, shared_capital=false, micro_ct=50, cap=2000); `shadow_micro_accounts`=50 (all inactive, 0 active, 0 with policy_registration_id → 0 bindings); comparison_eligible=50 / promotion_eligible=0. 50 `portfolio_id`s live in **`paper_portfolios`** (extra isolation), `routing_mode='shadow_only'`, cash=2000, net_liq=2000, 0 appear in `paper_orders`/`paper_positions`. Receipts: 1 provision / 0 activation; idempotency proven. Activation gating (`shadow_fleet_activation.py:729 execute_activation`) fail-closed behind ALL of — `FLEET_ACTIVATION_AUTHORIZED` strict `=='1'` (`:153-168`), confirm literal `EXECUTE-SHADOW-FLEET`, idempotency key, full 50-slot operator payload, validated attestation; `_validate_policy_registrations:230-277` + `_validate_registry_approvals:282-340` (fail-closed → `schema_unavailable` on read error, the E8-3 lesson). Slot↔policy bijection forced (exactly 50 approved ids exist; operator must supply 50 unique approved). Atomicity: each execute step is ONE `supabase.rpc` (single plpgsql txn); no direct table writes → no partial activation. RPC EXECUTE granted to `postgres`+`service_role` only; route `public_tasks.py:1199` requires v4 HMAC scope `tasks:shadow_fleet_activation`, rate-limited 5/min, never scheduled, defaults to dry-run.
- **Pass 3.** "Could a malformed/duplicated/unapproved/mismatched policy bind, or partial activation leave an inconsistent fleet?" — No: duplicate → `POLICY_REGISTRATION_DUPLICATE`; unregistered → `POLICY_NOT_REGISTERED`; draft/retired → `POLICY_NOT_APPROVED`; registry read failure → `SCHEMA_UNAVAILABLE`; single-RPC atomicity forbids partial. Cross-area #2: the Sunday `SIGNED_DRY_RUN_PASS` is a **replicated/plan-mode** read (`plan_activation` zero-write `:639-685`; fingerprint `6f8d1499…` recomputed from DB), NOT an authenticated invocation through the live service route — distinction preserved. #3: **no un-activate RPC** — reversal = retire path (irreversible-in-place), all-or-nothing. #9: #1298 recorded 7 decisions, activated nothing; E19 hash untouched; runtime 0/0/0 confirms.
- **Retained: NONE new.**
- **Maturity — code/instrument 9 · natural-runtime 6** (provisioning fully proven & isolated; activation intentionally unexercised — dry-run only, 0 receipts by design).

### A9 — OPERATIONS, OBSERVABILITY, SECURITY, TEST REACH
- **Pass 1.** Baseline clean: H8 (3 services @ pin), H11 (risk_alerts 0 critical / 0 high in 72h; 41 warning + 9 info), job_runs 519 succeeded / 1 cancelled / 0 failed / 0 partial (4d). `entries_paused=false`. Live armed (VERIFIED-DEPLOYMENT via flag echo). WRAPPER_PARTIAL + F-RUNNER-BROKER-CREDS already ledgered — extended below, not restated.
- **Pass 2.** Flag echo #1268 emits in prod (VERIFIED-DEPLOYMENT, BE 15:11:33Z, 30 flags, 0 parse errors, allowlist-scrubbed, real parsers). Completion contract: manifest+report+transcript landed; **cron.log runner markers ENTIRELY ABSENT**. HMAC uses constant-time compare + v4 nonce/TTL, fail-closed on missing secret, dry-run/execute separated; but the HMAC behavioral unit suite is module-skipped. job_runs `origin` rides in `result` jsonb (A5-2 settled); retry via `attempt`/`idempotency_key`.
- **Pass 3.** The A9 adversarial question resolves **YES for the audit loop itself**: the runner can fire the dead-man UP-ping while its entire cron.log evidence trail silently failed to reach the sink, and it mutated the operator checkout it swore never to touch.
- **Retained (A9 · three).**
  - **F-RUNNER-WORKTREE-DEADFALLBACK (HIGH).** `nightly_runner.py:918` — `worktree = Path(os.environ.get("AUDIT_WORKTREE_DIR","")) or _local_appdata_worktree()`. `Path("")` is truthy (`WindowsPath('.')`, verified) and `AUDIT_WORKTREE_DIR` is unset ⇒ the `%LOCALAPPDATA%\otc-audit-worktree` fallback is **dead code**; `worktree="."`. Consequence A (data-safety, un-ledgered): `refresh_audit_worktree:318-327` runs `git checkout --force --detach origin/main` + `git reset --hard origin/main` with `-C "."` = the operator checkout (operator reflog `HEAD@{0}: checkout: moving from main to origin/main` proves it); tracked `audit/ledger.md` carrying uncommitted edits is discarded by the `--force`. Consequence B (isolation defeated): `child_cwd="."` → audit ran in the operator checkout. Consequence C (false-green): cron.log is held open by the shim's `>> audit\cron.log` redirect (`run-nightly.cmd:34`); the runner's separate `append_line:87-94` hits a Windows sharing violation swallowed by `except OSError: pass` ⇒ every marker dropped, yet `_end_marker_written` is set unconditionally (`:705`) so `evaluate_completion_contract` reports **met** and `_do_ping` fires the dead-man UP-ping on an empty evidence sink — the exact mode #1264 was built to kill. VERIFIED-CODE + VERIFIED-DB(reflog). **EXTENDS the OPEN nightly-runner P1 (WRAPPER_PARTIAL root cause).** Falsifier: `build_production_config()` with `AUDIT_WORKTREE_DIR` unset should assert `cfg.audit_worktree == _local_appdata_worktree()`; it currently `== Path(".")`.
  - **F-A9-1 (MED, NEW P2 security).** `task_signing_v4.py:59-79 _is_production_mode()` keys prod off `ENV=="production"` OR `ENABLE_DEV_AUTH_BYPASS=="0"`, diverging from canonical `security/config.is_production()` (`config.py:45-64`, keys `APP_ENV`/`RAILWAY_ENVIRONMENT*`). A prod worker with `APP_ENV=production` but `ENV` unset ⇒ `_is_production_mode()` False ⇒ nonce-store outage **fails OPEN** (`:169,173-182`) while `audit_production_security()` reports healthy. Bounded: HMAC + 300s TTL hold; replay window widens to the TTL during a store outage. INFERRED (from code). Falsifier: `RAILWAY_ENVIRONMENT=production`, `ENV` unset, drop nonce store → replay accepted within TTL.
  - **F-A9-2 (MED, EXTENDS skip-discipline).** Module-level `pytestmark=pytest.mark.skip` on the HMAC/security behavioral suite — `test_task_signing_v4.py:36`, `test_run_signed_task.py:42`, `test_admin_auth.py:30`, `test_security_v3.py:10` (#768), `test_is_localhost_spoofing.py:8` (#769), `test_security_headers.py:9`/`test_api_info_disclosure.py:13`/`test_optimizer_security.py:12` (#774). Net: nonce-replay detection, timestamp-expiry, scope-mismatch, and the fail-open determination (the exact F-A9-1 seam) **do not run in CI**; the un-skipped route test covers happy-path + unsigned→401 only. VERIFIED-CODE. Falsifier: unskip #768; assert replay/expiry cases pass on the real route.
- **Rejected/duplicate/settled.** Flag echo #1268, job_runs `'partial'` (in CHECK, 0 natural rows), H8/H11, secret scrubbing + debug/auth-bypass (`ENABLE_DEV_AUTH_BYPASS=1` = hard prod abort; localhost triple-gate), no source-pin costume, disciplined `sys.modules` → all CLEAN. F-RUNNER-BROKER-CREDS → DUPLICATE. `secrets_audit.py` real but not CI-wired → NOTE. `settings.json` cosmetic `Write(audit/**)` warning → NOTE.
- **Maturity — code/instrument 7 · natural-runtime 6** (strong instruments undercut by a HIGH self-defeating bug in the sole oversight loop and a skipped HMAC behavioral suite).

### A10 — PRODUCT/API, CALENDAR/CLOCK, GOVERNANCE
- **Pass 1.** Governance state VERIFIED-DB: `policy_registrations` 50/50 approved / 50 distinct hashes; `shadow_fleets` 1 `pending_legacy_terminal` / 0 active / no shared capital; `FLEET_ACTIVATION_AUTHORIZED=False` (VERIFIED-DEPLOYMENT). Ratifications are DOCS (`owner-packet-1..7`, `owner-ratifications-2026-07-19.md`) — no DB mutation. CLAUDE.md/backlog/ledger content current through #1300. UI BLOCKED (40 open Palette/Jules PRs).
- **Pass 2.** Clock: winter-close blind hour RESOLVED (`ops_health_service.py:46-75` DST-aware ET + broker-clock gating; hardcoded UTC window retired). Fleet activation fail-closed behind 4 gates + attestation + full 50-slot payload, single-RPC atomic, routing never live_eligible. Monday reader #1300 read-only, `test_read_only_single_select` pins single-SELECT/no-write-verbs. Migrations reconciled (partial CHECK applied; 50 seed rows; receipts per ledger).
- **Pass 3.** A10 adversarial ("does a surface/doc/clock/endpoint imply an ability the system lacks?") → mostly NO (fleet inactive and truthfully so; ratifications activate nothing; single-leg veto DARK 0/50). Two exceptions below.
- **Retained (A10 · one finding + one NOTE).**
  - **F-A10-HOLIDAY (MED, mitigated, NEW P2 calendar integrity).** `jobs/handlers/utils.py:49-69 is_market_day()` is weekday-only; its docstring `:54` ("no holiday calendar — scheduler already handles this") is **affirmatively false** (CronTrigger fires mon-fri regardless of holidays). Consumers `suggestions_open.py:77` / `suggestions_close.py:54` ⇒ suggestion generation runs on holidays. Live pre-submit `brokers/safety_checks.py:100-108 market_hours` is weekday + Chicago-hour-8..16 only (holiday-blind, loose 8:00-8:30/15:00-16:00 pass). Mitigations: Alpaca rejects orders on a closed market; monitor + reentry-cooldown gate on the holiday-aware broker clock; learning-mode low frequency. VERIFIED-CODE. Falsifier: `is_market_day(2026-11-26)` (Thanksgiving) → True.
  - **CLAUDE.md size drift (NOTE).** CLAUDE.md at the pin is **70,827 bytes** (~1.77× the historical ≤40k self-cap). The 06-13 rewrite's "≤40k chars" cap was **dropped** from the header (now "synced 2026-07-16") rather than the file trimmed. Content is current (references #1279–#1300). Disposition: size-discipline abandoned; trim or restore the cap.
- **Rejected/duplicate/settled.** Winter-close blind hour RESOLVED; ratification-vs-activation CLEAN (docs-only, 0 activation); fleet dry-run/execute + irreversibility CLEAN (4-gate fail-closed, single-RPC atomic, retire = irreversible-in-place); UI honesty BLOCKED_UI_FILE_OWNERSHIP (40 Palette PRs; report collision, no edit; label honesty not independently verified — FE-owned limitation); Monday reader #1300 CLEAN read-only (first natural output RUNTIME-CHECK Monday ≥17:45Z); taper band `[900,1100]` vs `[800,1000]` DUPLICATE; DTE/Friday-Monday/DST CLEAN; migration-vs-filename reconciled, no double-apply.
- **Maturity — code/instrument 7 · natural-runtime 6.**

---

## 8. MANDATORY CROSS-AREA CANDIDATE DISPOSITIONS

| # | check | disposition |
|---|---|---|
| 1 | Current-docs lag after #1296/#1299 | **NO material misstatement.** backlog/ledger accurately state "0/528 v2 stamps, accrues forward"; CLAUDE.md §5 fee-doctrine line stale-but-acknowledged/owner-gated. Multi-fill TCM coverage not misstated. |
| 2 | Fleet signed-route dry-run gap | **DUPLICATE (owned).** Sunday `SIGNED_DRY_RUN_PASS` is a replicated/plan-mode read (`plan_activation` zero-write; fingerprint `6f8d1499…` recomputed from DB), NOT an authenticated invocation through the live service route. Distinction preserved; no activation. |
| 3 | Activation irreversibility | **CLEAN/DUPLICATE.** No un-activate RPC; reversal = retire path (irreversible-in-place); single-RPC atomicity = all-or-nothing. |
| 4 | Single-leg dark guarantee | **CONFIRMED.** Two-layer guard (generator fail-closed dark + 4-site submit veto) + 0/50 DB opt-in + generator/selection zero production callers. `order=` threaded at all 4 `should_submit_to_broker` seams. VERIFIED-CODE + VERIFIED-DB. |
| 5 | H7 taxonomy integrity | **code-CONFIRMED; natural DEFERRED-SAMPLE.** 5 canonical subreasons, each orchestrator site maps correctly (account_capacity reserved-honest); one-subreason invariant enforced. 0 rows in `candidate_terminal_dispositions`. |
| 6 | TCM-v2 stamp population + multi-fill selection | **0/528 stamped; HONEST; DEFERRED-SAMPLE.** No natural stage cycle since #1278 deployed 07-19 (latest order 07-15). Multi-fill selection code correct (side-flip/zero-qty/dedup/mixed-abstention), exercised only by fixtures. |
| 7 | Scorable outcome first natural row | **DEFERRED-SAMPLE.** scorable-close count = 0 (0 marker-carrying open orders); `model_review_event` job_runs = 0. Did not trigger a close. |
| 8 | Quote/OI evidence first natural rows | **DEFERRED-SAMPLE.** 0 rows, HONEST-EMPTY (applied 07-18 post-last-scan; recorder wired + flushed). No OI gate confirmed. Did not trigger a scan. |
| 9 | Owner ratification vs activation | **CLEAN.** #1298 recorded 7 decisions, activated nothing; E19 hash untouched; runtime 0/0/0 active/bindings/receipts. |
| 10 | UI/API honesty | **BLOCKED_UI_FILE_OWNERSHIP.** 40 Palette/Jules PRs own the UI files; collision reported, not edited around. Label honesty not independently verifiable this run (FE-owned). |
| — | Realized-cost study selection bias (A1) | **None** — all 86 closed + full fill inventory enter. VERIFIED-DB. |
| — | Broker/cash/OBP reconciliation at window (A6) | **Flat & consistent** — 0 pos / 0 open / OBP $2,067.86. VERIFIED-BROKER. |

---

## 9. FREE-LOOK

**ZERO promotions.** The free-look pass examined the candidate set and every candidate either folded into an area finding (F-A4-RISKBASIS-SILENT, A1-G1, A3-LIFECYCLE, A5-OI-KNOWNAT, A2-ASSIGNMENT, A4-DIVISIBILITY, the three A9 findings, F-A10-HOLIDAY) or deduplicated against ledger/backlog (WRAPPER_PARTIAL, F-RUNNER-BROKER-CREDS, taper-band reconciliation, shadow-fill fiction, greeks dormancy, EXIT_EVAL_DEBUG partial, severity-taxonomy fragmentation). The promote-≤2 budget is **unused** — no residual outranks an existing open item beyond what the areas already retained.

---

## 10. RANKED RETAINED FINDINGS

| rank | ID | area | severity | proof | one-line |
|---|---|---|---|---|---|
| 1 | **F-RUNNER-WORKTREE-DEADFALLBACK** | A9 | **HIGH** | VERIFIED-CODE + VERIFIED-DB(reflog) | Dead `%LOCALAPPDATA%` fallback (`Path("")` truthy) → nightly runner `--force`-resets the OPERATOR checkout, drops all cron.log markers via a swallowed `OSError`, yet fires the dead-man UP-ping on an empty evidence sink. EXTENDS the OPEN nightly-runner P1 (WRAPPER_PARTIAL root cause). |
| 2 | **F-A4-RISKBASIS-SILENT** | A4 | **MED** | VERIFIED-CODE + VERIFIED-DB(ledger) | The exact P0-B arm-decision / `would_flip` evidence has not emitted or reached its expected durable evidence contract (`risk_basis_shadow.py:31`); historical generic `[RISK_BASIS_SHADOW]` lines do not satisfy that gate, so sizing/utilization stay on premium basis indefinitely. NEW. |
| 3 | **F-A9-1** | A9 | **MED** | INFERRED (from code) | `task_signing_v4._is_production_mode()` diverges from canonical `is_production()`; a prod worker with `APP_ENV=production` but `ENV` unset fails OPEN on a nonce-store outage (replay window widens to the 300s TTL). NEW P2 security. |
| 4 | **F-A9-2** | A9 | **MED** | VERIFIED-CODE | HMAC/security behavioral suites module-skipped (#768/#769/#774) — replay/expiry/scope/fail-open never run in CI. EXTENDS skip-discipline backlog item. |
| 5 | **F-A10-HOLIDAY** | A10 | **MED (mitigated)** | VERIFIED-CODE | `is_market_day()` weekday-only with an affirmatively-false docstring; suggestion open/close consumers + `safety_checks` holiday-blind. Mitigated by broker rejection on closed market + broker-clock-gated monitor/cooldown. NEW P2 calendar integrity. |
| 6 | **A1-G1** | A1 | **LOW** | VERIFIED-DB | ranker-basis has zero realized overlap: `ranking_costs` 0/86 realized round-trips, `candidate_terminal_dispositions` 0. Evidence-completeness (typed-UNAVAILABLE), not correctness. |
| 7 | **A3-LIFECYCLE** | A3 | **LOW/NOTE** | VERIFIED-CODE | `candidate_disposition` lifecycle values staged/broker_submitted/filled defined but unwired (`:82-85`); lifecycle stops at persist. Blast radius NIL (observe-only). |
| 8 | **A5-OI-KNOWNAT** | A5 | **LOW/NOTE** | VERIFIED-CODE | OI freshness unobservable: `oi_freshness` always `known_at_unavailable` (`quote_provenance.py:261-266`); `market_data_truth_layer.py:1856` never sets `open_interest_date`. |
| 9 | **A2-ASSIGNMENT** | A2 | **LOW** | NOT-PROVEN → DEFERRED-SAMPLE | Assignment/expiry custody path not traced to a handler; no natural sample yet, nothing triggered. |
| 10 | **A4-DIVISIBILITY** | A4 | **LOW-INERT** | VERIFIED-CODE | `check_greeks` D3 path lacks the divisibility guard `compute_stress` gets; inert while all caps are 0/dormant. |

**Retained NOTEs (record, not findings):** N1 stale migration version-prefix comments (`fleet_policy_design.py:10`, `shadow_fleet_activation.py:83`, `public_tasks.py:1231` — NAMES match, prefixes stale; §8 match-by-NAME class); N2 model-review fingerprint keys on scorable id-SET not row CONTENT (zero decision impact, observe-only); CLAUDE.md size drift (70,827 bytes vs historical ≤40k cap dropped from the header); `settings.json` cosmetic `Write(audit/**)` allow-warning; `secrets_audit.py` real but not CI-wired; N3 (orchestrator, found during the Phase-8 workspace-integrity check) tracked-path case-collision — BOTH `.Jules/palette.md` AND `.jules/palette.md` exist as distinct git blobs, which collide into one file on a case-insensitive Windows checkout, so one of the two paths shows phantom `M` drift in `git status` (VERIFIED in the fresh audit worktree; restore of one re-dirties the other by construction; manifestation is checkout-order/ignorecase dependent — the operator checkout does not currently show it). Fix = de-duplicate the tracked path in a normal code PR; the audit branch stages only its three allowed files, so the collision is not committed here.

---

## 11. ADJUDICATION MATRIX

Every candidate finding → disposition + one-line reason.

| candidate | disposition | reason |
|---|---|---|
| F-RUNNER-WORKTREE-DEADFALLBACK | **RETAINED (HIGH)** | New root-cause + operator-checkout data-safety + false-green ping; extends OPEN nightly-runner P1 |
| F-A4-RISKBASIS-SILENT | **RETAINED (MED)** | New synthesis: silent instrument blocks the P0-B observe→enforce arm gate |
| F-A9-1 | **RETAINED (MED)** | New: two prod-mode detectors diverge → fail-open on nonce-store outage |
| F-A9-2 | **RETAINED (MED)** | Extends skip-discipline: HMAC behavioral suite absent from CI |
| F-A10-HOLIDAY | **RETAINED (MED, mitigated)** | New: holiday-blind entry path; mitigated by broker rejection |
| A1-G1 | **RETAINED (LOW)** | New evidence-completeness gap; forward-accruing |
| A3-LIFECYCLE | **RETAINED (LOW/NOTE)** | Documented phase-2 observe-only scope boundary |
| A5-OI-KNOWNAT | **RETAINED (LOW/NOTE)** | Honest limitation of the observe-first no-gate OI lane |
| A2-ASSIGNMENT | **RETAINED (LOW) / NOT-PROVEN → DEFERRED-SAMPLE** | No handler traced; no natural sample yet |
| A4-DIVISIBILITY | **RETAINED (LOW-INERT)** | Inert while caps 0 and greeks dark |
| Frozen-0.65-vs-realized-$0 fee divergence | **DUPLICATE** | #1273 pin + TCM v2 observe-only + owner packet 5 (N=15) |
| CLAUDE.md §5 "fees ~$1–2/round-trip" stale | **DUPLICATE/acknowledged** | Owner-gated by TCM promotion |
| Debit/condor payoff-vs-terminal-distribution, ⑤ challenger separation | **SETTLED** | #1296 (A7) |
| Single-leg live-submit reachability | **DUPLICATE** | #1292, 4-site veto, 0/50 opt-in |
| `EXECUTION_MODE` silent-degradation | **DUPLICATE/SETTLED** | Loud critical alert at `execution_router.py:297` |
| Multi-fill commission completeness (#1299) | **VERIFIED-CODE / DEFERRED-SAMPLE** | Code correct; natural accrual pending Monday |
| `reconcile_legs` unwired (canonical↔broker) | **DUPLICATE** | Ledgered A2-2 (`backlog.md:708`); legacy order_sync reconciles 0/0 |
| F-CREDIT-SIGN idempotency + downstream repair | **SETTLED** | Fingerprinted; 1 sign-corrected reconciler row; no double-correction |
| Canonical max-loss / payoff-capped stress vs close outcomes | **SETTLED** | `analyze_payoff` breakpoint-exact; `NOT_DEFINED_RISK` raises; `*_raw` preserved |
| Premium-basis sizing/utilization | **DUPLICATE (of P0-B)** | Owned/GATED; sharpened synthesis retained as F-A4-RISKBASIS-SILENT |
| Micro↔small declining-equity cliff | **DUPLICATE** | Known hard cliff; DARK taper #1283 is the designed fix; band reconciliation pending |
| D2/D3 signed+ratio greek aggregation | **SETTLED** | #1290; migrated + byte-identical on 1:1 |
| Single-leg strategy-name veto collision (future non-experimental single) | **DUPLICATE** | Add-to-position seam class, §8 ledgered |
| `account_capacity` H7 subreason 0 call sites | **REJECTED (not a gap)** | Honest-by-design (allocator caps→allocator_dropped; tier max→pre-selection) |
| H7 parent+typed-subreason schema | **DUPLICATE** | Non-rediscovery list |
| Quote/OI provenance schema + A5-2 source-label repair | **DUPLICATE** | #1271/#1285 ledgered |
| Sampled-away non-decision provenance rows | **REJECTED** | Always-persist covers every rejected+emitted set; sampling is documented volume control |
| Migration filename-vs-tracked-version drift | **DUPLICATE** | Match-by-NAME class, ledgered (A10 territory) |
| 8/8 clamp-floor + winsorize | **DUPLICATE** | `backlog.md:1183/1634`, settled 07-09; runtime confirms |
| ⑤ / event-review producer chain | **DEFERRED-SAMPLE** | 0 natural scorable closes |
| E19-2B minimum-events | **owner packet OPEN** | #1294 pkt-3 (ratified 8, pending v3 re-freeze); not a defect |
| Model-review fingerprint id-set content-blindness | **NOTE (N2)** | Observe-only, mutates nothing |
| Signed-route-vs-replicated-dry-run | **DUPLICATE** | Owned; recorded as replication |
| Activation irreversibility | **DUPLICATE** | Retire-path, ledgered |
| Taper band `[900,1100]` vs `[800,1000]` | **DUPLICATE** | Owned DARK-state reconciliation |
| Single-leg opt-in 0/50 | **DUPLICATE (owned)** | A3 boundary; registry holds no single-leg opt-in row |
| Migration version-prefix comment drift | **NOTE (N1)** | NAMES match; §8 match-by-NAME; non-material |
| F-RUNNER-BROKER-CREDS | **DUPLICATE** | Ledgered; snapshot `available:false` re-confirmed |
| Winter-close blind hour | **SETTLED/RESOLVED** | `ops_health_service.py:46-75` DST-aware |
| UI label honesty | **BLOCKED_UI_FILE_OWNERSHIP** | 40 Palette PRs; report collision, no edit |
| Monday reader #1300 becoming a control | **REJECTED (not a defect)** | Test-pinned read-only single-SELECT |
| `secrets_audit.py` not CI-wired | **NOTE** | Real tool, unwired |
| `settings.json` cosmetic Write(audit/**) warning | **NOTE** | Both Write+Edit in allow; audits complete |
| CLAUDE.md size drift | **NOTE** | Cap dropped from header, not file trimmed |

---

## 12. REJECTED / DUPLICATE / SUPERSEDED / NOT-PROVEN APPENDIX

- **REJECTED (tested-false / not-a-defect):** `account_capacity` H7 0-call-sites (honest-by-design); sampled-away provenance rows (always-persist covers all decision-bearing sets); Monday reader #1300 as a control (test-pinned read-only).
- **DUPLICATE (owned, no stronger mechanism):** frozen-fee divergence; CLAUDE.md §5 fee line; single-leg live-submit reachability; `EXECUTION_MODE` degradation; `reconcile_legs` unwired; premium-basis sizing (of P0-B); micro↔small cliff; single-leg name-veto collision; H7 schema; quote/OI schema + source-label repair; migration filename drift; 8/8 clamp + winsorize; signed-route-vs-replicated dry-run; activation irreversibility; taper band; single-leg opt-in 0/50; F-RUNNER-BROKER-CREDS; shadow-fill fiction; greeks dormancy; EXIT_EVAL_DEBUG partial; severity-taxonomy fragmentation.
- **SETTLED (non-rediscovery):** F-CREDIT-SIGN idempotency; canonical max-loss/payoff-stress vs close outcomes; D2/D3 signed+ratio aggregation; ⑤ scorable-join; winter-close blind hour (RESOLVED); the three evidence/fleet + registry/H7 migrations applied never-reapply.
- **SUPERSEDED:** none this cycle.
- **NOT-PROVEN:** A2-ASSIGNMENT assignment/exercise + at-expiry residual custody handler (also DEFERRED-SAMPLE — no natural sample); UI label honesty (FE-owned, unverifiable this run); 07-19 dead-man ping at the provider (folds into the wrapper finding).

---

## 13. RUNTIME-ONLY AND SAMPLE-GATED ITEMS

All grade **DEFERRED-SAMPLE** (Sunday, market closed, book flat — natural absence, not INCONCLUSIVE, nothing triggered):

| item | state now | Monday / natural falsifier |
|---|---|---|
| TCM v2 dual-run stamp population | 0/528 (HONEST-EMPTY; latest order 07-15) | ≥1 post-#1278 stage cycle stamps `paper_orders.tcm.tcm_v2_proposal` |
| Candidate terminal dispositions | 0 rows (HONEST-EMPTY, migrated 07-18) | First Mon 11:00 CT scan writes disposition rows; H7 subreasons appear |
| Quote/OI provenance rows | 0 rows (HONEST-EMPTY) | First Mon scan writes `option_quote_provenance`; OI freshness = `known_at_unavailable` (A5-OI-KNOWNAT falsifier) |
| Scorable-outcome close | scorable-close count 0; `model_review_event` 0 | First post-07-16 marker-carrying round-trip close → exactly-one review enqueue |
| A1-G1 ranker overlap | `ranking_costs` 0/86 realized | After ≥1 post-07-16 close, `closed_with_ranking_costs > 0` |
| A2-ASSIGNMENT | no natural assignment sample | A held-to-expiry ITM position produces a broker assignment a close handler reconciles to `status=closed` |
| Monday reader #1300 first output | not yet run | First natural output RUNTIME-CHECK Monday ≥17:45Z |
| 07-19 dead-man ping at provider | unconfirmed | Provider receipt / next 08:00 CT ping (folds into F-RUNNER finding) |
| Fleet activation | provisioned INACTIVE, 0 receipts | Remains 0/0/0 absent separate operator authorization |

---

## 14. BACKLOG INTEGRATION MAP

`finding | severity | evidence | disposition | existing owner | new/extends/duplicate | priority | backlog section | ledger entry | operator decision | falsifier`

| finding | sev | evidence | disposition | existing owner | rel | prio | backlog section | ledger | operator decision | falsifier |
|---|---|---|---|---|---|---|---|---|---|---|
| F-RUNNER-WORKTREE-DEADFALLBACK | HIGH | VERIFIED-CODE + reflog | RETAINED | nightly-runner P1 (WRAPPER_PARTIAL) | EXTENDS | P1 | nightly-runner reliability | new exclusion + pending-verify | Approve fallback fix + marker-landing verify before trusting `end_marker_written` | `build_production_config()` w/ `AUDIT_WORKTREE_DIR` unset ⇒ `audit_worktree==Path(".")` |
| F-A4-RISKBASIS-SILENT | MED | VERIFIED-CODE + VERIFIED-DB(ledger) | RETAINED | P0-B book-scaling epic | EXTENDS | P0-B/P2 | P0-B (backlog.md:1365) + A9 marker-silence | new | Decide the P0-B arm-evidence path: the exact `would_flip` comparison must emit in a natural cycle and land in a durable evidence sink (generic `[RISK_BASIS_SHADOW]` lines do not satisfy the gate) so the ~1-week arm review can begin | A natural-cycle arm-decision record with `would_flip` populated reaching the durable evidence contract |
| F-A9-1 | MED | INFERRED | RETAINED | — | NEW | P2 (security) | security / prod-mode detector | new | Reconcile the two prod-detectors | `RAILWAY_ENVIRONMENT=production` + `ENV` unset + nonce-store down ⇒ replay accepted within TTL |
| F-A9-2 | MED | VERIFIED-CODE | RETAINED | skip-discipline trend-down | EXTENDS | P2 | test skip discipline | new | Unskip #768; assert replay/expiry on the real route | Unskip #768 → suite passes on the real HMAC route |
| F-A10-HOLIDAY | MED (mit.) | VERIFIED-CODE | RETAINED | holiday ops-noise class | NEW/EXTENDS | P2 | calendar integrity | new | Add a holiday calendar to `is_market_day()` / fix the false docstring | `is_market_day(2026-11-26)`→True |
| A1-G1 | LOW | VERIFIED-DB | RETAINED | stamp-densification note (07-18) | EXTENDS | P2 | close_fill_gap / stamps naturally | new | none until natural volume | After ≥1 post-07-16 close, `closed_with_ranking_costs>0` |
| A3-LIFECYCLE | LOW/NOTE | VERIFIED-CODE | RETAINED | funnel phase-3 | NEW | P2 | funnel executor-phase disposition advance | note | none | Mon executor run leaves staged/broker_submitted/filled = 0 for executed candidates |
| A5-OI-KNOWNAT | LOW/NOTE | VERIFIED-CODE | RETAINED | #1285 OI capture | EXTENDS | P2 | thread `open_interest_date` from `get_option_contracts` | note | none | Mon scan rows show `oi_freshness=known_at_unavailable` for 100% of OI-available legs |
| A2-ASSIGNMENT | LOW | NOT-PROVEN | RETAINED (DEFERRED-SAMPLE) | — | NEW | P2 | close-path custody note | note | none until sample | A held-to-expiry ITM position reconciles to `status=closed` with correct realized_pl via a close handler |
| A4-DIVISIBILITY | LOW-INERT | VERIFIED-CODE | RETAINED | canonical-greek note | NEW | P2 | canonical-greek divisibility | note | none (inert while caps 0) | A leg with `quantity % structure_quantity ≠ 0` yields a `check_greeks` sum while `normalize_position` rejects it |

Rules honored: every retained finding appears once; a runtime falsifier is not a build slot; a dark feature is not live; an applied migration is never listed as pending; a merged owner decision is not an activated control; open-PR ownership respected; no implementation/migration/config/broker/DB/fleet/deploy change occurred in this lane. (Canonical-file edits are the reconciliation lane's job, not this draft's.)

---

## 15. OWNER DECISIONS AND NATURAL FALSIFIERS

**Top-3 owner decisions:**
1. **Fix the nightly-runner worktree fallback** (`Path(env) if env else _local_appdata_worktree()`) and route markers through the already-redirected child stdout / verify the append landed before trusting `end_marker_written` — the sole oversight loop currently `--force`-resets the operator checkout and can UP-ping on an empty evidence sink.
2. **Decide the P0-B arm path:** the exact arm-decision / `would_flip` comparison must emit in a natural cycle AND land in a durable evidence sink before the ~1-week observe→enforce arm review can even begin; historical generic `[RISK_BASIS_SHADOW]` lines do not satisfy that gate, so it cannot clear on what exists today.
3. **Reconcile the two prod-mode detectors** (`task_signing_v4._is_production_mode()` vs `security/config.is_production()`) and unskip the HMAC behavioral suite (#768) so replay/expiry/fail-open run in CI.

**Top-3 retained backlog deltas:** F-RUNNER-WORKTREE-DEADFALLBACK (HIGH) · F-A9-2 HMAC behavioral suite skipped (MED) · F-A10-HOLIDAY entry-path holiday blindness (MED). (F-A4-RISKBASIS-SILENT is the strongest evidence-quality delta of the MED tier.)

**Exact natural falsifiers:** as tabled in §13/§14 — the binding ones are the Monday first-scan disposition/provenance rows, the first post-07-16 scorable close, the `[RISK_BASIS_SHADOW]` first emission, and `build_production_config()` asserting `audit_worktree != Path(".")`.

---

## 16. TEN-AREA MATURITY SCORECARD

Two components per area (code/instrument maturity · natural-runtime evidence maturity), never combined.

| area | code/instrument | natural-runtime | note |
|---|---|---|---|
| A1 — Economic edge | **8** | **4** | multi-basis architecture sound; cross-basis overlap near-empty |
| A2 — Losses/exits/custody | **8** | **6** | custody reconciles + close-fill-gap sign proven; assignment path NOT-PROVEN |
| A3 — Strategy funnel | **8** | **2** | HONEST-EMPTY, self-activates Mon |
| A4 — Risk/sizing/canonical | **8** | **5** | canonical lane excellent; sizing lane deliberately dark; silent shadow instrument |
| A5 — Market data/OI | **8** | **2** | HONEST-EMPTY, self-activates Mon |
| A6 — Execution/broker/costs | **8** | **5** | veto + reconciliation clean; TCM v2 accrual DEFERRED-SAMPLE |
| A7 — Learning/calibration/model-review | **8** | **3** | producer chain zero natural proof; 8 clamped samples |
| A8 — Fleet/registry/experiment | **9** | **6** | provisioning fully proven & isolated; activation intentionally unexercised |
| A9 — Ops/observability/security | **7** | **6** | strong instruments undercut by a HIGH self-defeating oversight bug + skipped HMAC suite |
| A10 — Product/API/calendar/governance | **7** | **6** | governance/clock fail-closed & truthful; holiday-blind entry + doc-size drift; UI honesty gated behind ownership |

---

## FILES, SYMBOLS, QUERIES, COMMANDS, AND PRs INSPECTED

**Code (@ `20ca312e`):** `packages/quantum/execution/transaction_cost_model.py` (`TransactionCostModel`); `services/tcm_v2_proposal.py` (`classify_routing`, `build_proposal`, `realized_commission_when_available`); `scripts/analytics/realized_cost_study.py` (`STUDY_SQL`, `_split_fill_inventory`, `_sum_components_total`, `_broker_routed`, `build_accrual_examples`); `brokers/execution_router.py` (`should_submit_to_broker`, `assert_single_leg_shadow_only`, `is_single_leg_experiment_row`, `get_execution_mode`, `SINGLE_LEG_EXPERIMENT_STRATEGIES`); `paper_endpoints.py` (756-832, 929-933, 623-811, 776, 804-811); `services/paper_exit_evaluator.py` (`_close_position:1705`, `_corroborate_positions_for_exit:1527`, resting-TP skip `:1915`, CLOSE_QUOTE_VALIDATION `:1997-2026`, `:2004`, `:2221`); `brokers/safety_checks.py` (`:100-108`, `:272`); `analytics/canonical_ranker.py` (`MIN_EDGE_AFTER_COSTS`, `_ranking_round_trip_fees`, `compute_risk_adjusted_ev`, `:65`); `services/cost_reconciliation_artifact.py`; `strategy_profiles.py` (`CostModelConfig`); `risk/position_model.py` (`normalize_position`, `leg_full_contract_count:949`, `aggregate_greeks`, `analyze_payoff`, `clamp_stress_to_payoff`, `reconcile_legs:766`); `risk/risk_envelope.py` (`_pos_risk:263`, `check_greeks:392`, `aggregate_canonical_greeks`, `compute_greek_cap_counterfactual`, `compute_stress_scenarios:1190`, `check_loss_envelopes`, `check_all_envelopes`); `analytics/exit_mark_corroboration.py` (`corroborated_exit_upl:487`, `executable_close_estimate`, `corroborated_mark_fields`); `services/close_helper.py` (`close_position_shared:158`); `brokers/alpaca_order_handler.py` (`:625-694`, `broker_fill_to_mark_basis:672-677`); `services/risk_budget_engine.py` (`compute`, `_estimate_risk_usage_usd:365`, `:418`, `resolve_risk_cap_family:299`); `risk/utilization_gate.py` (`:334-358`, `:353`); `services/risk_basis_shadow.py` (`:31`, `honest_position_risk`, `choose_basis`); `services/analytics/tier_taper.py` (`decide`/`observe`, `:37-38`); `services/analytics/small_account_compounder.py`; `services/candidate_disposition.py` (`:48-49`, `:82-85`, `:524-546`); `services/quote_provenance.py` (`scrub:87`, `resolve_leg_oi:232`, `:261-266`, `:418-433`, `:650-655`); `services/workflow_orchestrator.py` (2442, 2720-2960, 3290-3860, 4340-4400); `strategies/single_leg_experiment.py` (`:587-605`); `options_scanner.py` (1037-1066, 2523-2657, 2878, 2896, 3290-3360, 4001-4060, 4460-4634); `services/market_data_truth_layer.py` (733-960, 946, 1360-1720, 1597, 1856); `intraday_risk_monitor.py` (`_compact_greek_cf:637`); `analytics/calibration_service.py` (40-114, 55-68, 328-407, 391); `analytics/model_review.py` (`evaluate_and_maybe_enqueue_review`, `is_scorable_row:248-264`, `scorable_fingerprint:271-280`, `run_review`, `partition_trusted_rows:208`); `jobs/handlers/model_review_event.py`; `jobs/handlers/paper_learning_ingest.py` (171-214, 192-199, 212); `scripts/analytics/challenger_study.py` (`MODEL_SET_VERSION`, `to_foundation_row`, `build_study`); `policy_lab/shadow_fleet.py` (`FLEET_EPOCH`, `MICRO_ACCOUNT_COUNT`, `CAPITAL`); `policy_lab/fleet_policy_design.py` (`canonical_config`, `config_hash`, `build_registrations`, `:10`); `services/shadow_fleet_activation.py` (`execute_activation:729`, `:153-168`, `_validate_policy_registrations:230-277`, `_validate_registry_approvals:282-340`, `plan_activation:639-685`, `:83`); `public_tasks.py` (1199-1280, 1231); `audit/run-nightly.cmd` (`:34`); `audit/runner/nightly_runner.py` (`append_line:87-94`, `refresh_audit_worktree:318-327`, `:298`, `:705`, `:918`, `:907-961`); `observability/flag_echo.py`; `security/task_signing_v4.py` (`_is_production_mode:59-79`, `:169`, `:173-182`, `:302-367`); `security/config.py` (`is_production:45-64`); `security/masking.py`; `security/secrets_audit.py`; `task_auth.py`; `cron_auth.py`; `jobs/handlers/utils.py` (`is_market_day:49-69`); `services/ops_health_service.py` (`:46-75`); `packages/quantum/jobs/handlers/{suggestions_open.py:77, suggestions_close.py:54}`.

**Tests inspected:** `test_realized_cost_study_multifill.py`, `test_realized_cost_study_tcm_v2_accrual.py`, `test_single_leg_submit_seam_veto.py`, `test_routing_dispatch_pr2a/b.py`, `test_tcm_v2_dual_run_route.py`, `test_position_model`, `test_tier_taper`, `test_scorable_join_readiness.py`, `test_e19_2b_preregistration.py`, `test_shadow_fleet_activation_route.py`, `test_flag_echo`, `test_monday_evidence_reader` / `test_read_only_single_select`, `test_close_limit_sign`, `test_streak_breaker`, skip clusters #768 (`test_task_signing_v4:36`, `test_run_signed_task:42`, `test_admin_auth:30`, `test_security_v3:10`) / #769 (`test_is_localhost_spoofing:8`) / #774 (`test_security_headers:9`, `test_api_info_disclosure:13`, `test_optimizer_security:12`).

**Queries (read-only):** Supabase (`etdlladeorfgdmsopzmz`) — TCM-v2 stamp census (0/528, latest order 07-15); realized spine (86 closed / 42 broker-$0 / 120 internal / 24 live-aggressive); ranking_costs coverage (0/86 realized, 2/265 total, 188/189 tcm-stamped); dispositions/suggestions counts (ctd 0, sugg 265, latest 07-17); open positions (0); crit/high alerts 72h (0/0; 41 warn + 9 info) + unresolved; closes/30d (7) + sign-corrected (1); `entries_paused=false`; `learning_trade_outcomes_v3` (102/8 live/94 shadow/0 null); scorable-marker on paper_orders (0) + v3 linkage (0); `model_review_event` job_runs (0); `calibration_adjustments` latest (ev/pop 0.5 clamp, err 65.34, 07-17 10:00Z); `policy_registrations` integrity (50/50/50-hash/0-mismatch, structure 3+39+8+0, lineage 17/17/16, max_stop 0.30, anchor hash recompute); `shadow_fleets`/`shadow_micro_accounts`/`paper_portfolios` counts+cols (1/50/50, 0 bindings, 1 provision / 0 activation); RPC EXECUTE grants + prosecdef; `list_migrations`; job_runs status dist + CHECK constraint (519/1/0/0); governance table introspection. Alpaca-live (`211900084`) — `get_account_info`, `get_all_positions` (empty), `get_clock`, `get_orders` (15 mleg, 0 open, latest 07-08). Railway (`empowering-commitment`) — `list_services`, `list_deployments` ×3, `get_logs` (FLAG_ECHO @15:11:33Z). Git — `rev-parse`/`status`/`log`/`reflog`/`ls-files`/`check-ignore`/`worktree list`/`origin` recheck.

**PRs:** #1296 (scorable-join), #1299 (TCM-v2 multi-fill accrual), #1300 (Monday evidence reader), #1301 (v1.6 brief merge), #1302 (docs); prior context #1271/#1272/#1273/#1278/#1280/#1281/#1283/#1285/#1287/#1289/#1290/#1291/#1292/#1294/#1298; ~40 open Palette/Jules UI PRs (ownership only, not inspected for content).

---

## FINAL AUDIT VERDICT

- **Executive verdict.** The 2026-07-16→07-19 closure sequence is code-mature and truthful at the pin: canonical position/greek/stress lane migrated, single-leg submit veto DARK and 4-site-covered, F-CREDIT-SIGN settled, registry 50/50 hash-clean, fleet provisioned inactive and isolated, and the two newest evidence tables honestly empty pending Monday. The single material new defect is in the **oversight loop itself**, not the trading path.
- **Highest-severity current defect:** **F-RUNNER-WORKTREE-DEADFALLBACK (HIGH)** — the nightly runner's dead `%LOCALAPPDATA%` fallback resets the operator checkout and can fire a false-green dead-man UP-ping on an empty evidence sink.
- **Strongest evidence-quality gap:** the multi-basis reconciliation's empty natural cross-basis overlap (TCM v2 0/528, ranker `ranking_costs` 0/86, dispositions/provenance 0) — plus the absent P0-B arm-decision / `would_flip` evidence (F-A4-RISKBASIS-SILENT; generic `[RISK_BASIS_SHADOW]` lines do not satisfy the gate).
- **Strongest economic-coherence gap:** frozen 0.65/contract vs realized $0 fee basis — already owner-gated by TCM promotion (DUPLICATE), surfaced not hidden, tightening not loosening.
- **Strongest operator-control gap:** the self-defeating nightly runner (F-RUNNER-WORKTREE-DEADFALLBACK) — success is currently indistinguishable from silent death.
- **Top-3 retained backlog deltas:** F-RUNNER-WORKTREE-DEADFALLBACK (HIGH) · F-A9-2 HMAC behavioral suite skipped (MED) · F-A10-HOLIDAY holiday-blind entry path (MED).
- **Top-3 owner decisions:** fix the runner worktree fallback + marker landing; decide the P0-B `[RISK_BASIS_SHADOW]` emit/arm path; reconcile the two prod-mode detectors + unskip the HMAC suite.
- **Exact natural falsifiers:** `build_production_config()` asserting `audit_worktree != Path(".")`; the Monday first-scan disposition/provenance rows; the first post-07-16 scorable close; a natural-cycle `[RISK_BASIS_SHADOW]` line with `would_flip`.
- **Fleet activation:** **READY_FOR_SEPARATE_AUTHORIZATION** — registry 50/50 approved & hash-clean, fleet provisioned-inactive & isolated (shadow_only, 0 bindings, 0 receipts), all execute-gates + HMAC route present, dry-run READY_TO_ACTIVATE. Activation still requires the separate operator token (`FLEET_ACTIVATION_AUTHORIZED=1`) + confirm + attestation + the outstanding Monday natural-evidence PASS (Sunday nightly was WRAPPER_PARTIAL).
- **Live-control loosening recommended:** **NONE.** No gate, stop, threshold, universe, cadence, or flag loosening is recommended anywhere; every measurement correction discussed is tightening or neutral.
- **No implementation or production mutation occurred.** No production code, test (outside docs), migration, DB write, broker write, fleet action, env/config/flag/schedule change, manual scan, deploy, or merge occurred during this audit.

`EXTERNAL FULL AUDIT v1.6 · TEN AREAS · READ-ONLY · NO CODE/DB/BROKER/DEPLOY/CONTROL CHANGE`
