# Disabled / Wired-But-Inactive / No-Runtime Feature Census — 2026-07-23 (RTH, READ-ONLY)

**Auditor role:** OPUS read-only. **Code pin:** `origin/main` = `19afc888a7e8c3573da75486224e90c80672343e` (read via detached worktree). **DB:** Supabase `etdlladeorfgdmsopzmz`, SELECT-only. **Runtime:** Railway worker deploy `b18242bf` (SHA 19afc888, started 2026-07-23 06:09:16Z) read-only.

**Compliance:** Zero DB writes, zero job triggers, zero agents spawned, zero repo edits, no secrets/UUIDs printed. Output only.

## Evidence-source caveats (read first)

- **FLAG_ECHO from the 06:09Z deploy is UNAVAILABLE.** Railway deploy-log retention for this service reaches back only ~40 min (earliest retained line ≈ 17:00Z); the `[FLAG_ECHO]` block is emitted once at process start (06:09Z) and has rotated out. `list_variables` was deliberately NOT called (env-secrets-hygiene: it would land live secrets in the transcript). **Effective flag values are therefore sourced from `DB_state` (0-row tables / observation-write presence) and `code_default`, labelled per field.** Pure behavioral flags with no DB footprint are `INFERRED` from the parser default.
- Proof labels: `VERIFIED-CODE` (read at the pin), `VERIFIED-DB` (SELECT), `VERIFIED-RUNTIME` (job_runs/rows/logs), `VERIFIED-DEPLOYMENT`, `INFERRED`, `NOT_PROVEN`.
- **Runtime anchors captured this session:** `decision_runs` newest row (07-23 16:00:38Z) carries `git_sha=19afc888` (VERIFIED-RUNTIME: the deployed SHA is the running SHA on the decision path). `ops_control`: `global`, mode=`paper`, `paused=false`, `entries_paused=false`. Book: 1 open SPY credit condor, equity ≈ $2,068 (risk monitor q15min, envelope_passed=True). `signal_accuracy_degraded` warning still firing each ops-health cycle (n≥8, hit_rate<0.2).

---

## Classification legend

`ACTIVE_RUNTIME_PROVEN` · `ACTIVE_UNEXERCISED` · `WIRED_DISABLED_BY_FLAG` · `WIRED_DISABLED_BY_DB_STATE` · `WIRED_OBSERVE_ONLY` · `BUILT_NO_PRODUCTION_CALLER` · `SCHEMA_OR_RPC_ONLY` · `DOC_OR_TEST_ONLY` · `DEAD_OR_PHANTOM` · `BLOCKED_BY_EVIDENCE` · `BLOCKED_OWNER_DECISION` · `STALE_DOCUMENTATION` · `NOT_PROVEN`

---

## MATRIX — mandatory census

### 1. Single-leg shadow experiment — `WIRED_DISABLED_BY_DB_STATE`
- **Entrypoint/module:** `services/single_leg_shadow_scan.py` (`run_single_leg_shadow_scan`) + handler `jobs/handlers/single_leg_shadow_scan.py`; design `policy_lab/single_leg_experiment_design.py`; selection `strategies/single_leg_selection.py`; lifecycle `services/single_leg_shadow_lifecycle.py`.
- **Prod callers:** child enqueue from `jobs/handlers/suggestions_open.py` (per scan cycle). Submit-seam hard veto `should_submit_to_broker` (#1292) guarantees no broker order even if it ran.
- **Scheduler/job:** NOT scheduler-registered; child job off `suggestions_open`. **0 `single_leg_shadow_scan` rows in `job_runs`** (VERIFIED-DB).
- **DB tables:** all 9 at **0 rows** — `single_leg_experiment_epochs`, `single_leg_experiment_bindings`, `single_leg_shadow_runs/attempts/lifecycle_events/orders/positions/outcomes/cash_events` (VERIFIED-DB).
- **Gate:** double-gated — (a) an *enabled epoch row* must exist in `single_leg_experiment_epochs` (0 rows → handler returns `status="epoch_absent"`, `single_leg_shadow_scan.py:113`), AND (b) per-policy opt-in `single_leg_experiment_enabled=true` in the registry jsonb — **0 of 50** registrations carry it (`strategies/single_leg_experiment.py:90` `OPT_IN_KEY`).
- **Effective value:** epoch_absent + 0 opt-in (source `DB_state`).
- **Last runtime evidence:** brief-reported child enqueue 07-23 returned `epoch_absent`; zero durable rows ever.
- **Decision consumer:** none (shadow/internal-paper only, never a live suggestion stream).
- **Affect live entries?** No (routing shadow_only + submit-seam veto).
- **Kill/rollback:** retire epoch (none exists) / registry opt-in removal. **Why inactive:** no epoch enabled, no policy opted in. **Action:** natural evidence — owner decision to seed an epoch + two draft opt-in registry rows (owner-packet-4). Keep dark until then.

### 2. Quant Agents (design/scanner/sizing agent pipeline) — `WIRED_DISABLED_BY_FLAG`
- **Entrypoint/module:** `agents/runner.py` (`build_agent_pipeline`, `AgentRunner.run_agents`) + 8 agents in `agents/agents/*` (Regime, VolSurface, Liquidity, EventRisk, StrategyDesign, Sizing, ExitPlan, PostTradeReview).
- **Prod callers (real, on the live path):** `options_scanner.py:3367` + `:4447` (design + scanner phases) and `services/workflow_orchestrator.py:3363/3412/3601` (**`run_midday_cycle`, which `suggestions_open` imports and calls daily** — VERIFIED-CODE). So the blast radius is the live entry-suggestion path + scanner, not an isolated corner.
- **Flag/parser/default:** `QUANT_AGENTS_ENABLED` — `os.getenv(...,"false").lower()=="true"` (orchestrator) / `is_agent_enabled(default=False)` (runner). **Default OFF.** Per-agent sub-flags (`QUANT_AGENT_*_ENABLED`) default True but are dead behind the parent OFF.
- **Effective value:** OFF (source: `code_default` + `INFERRED` — flag not in the echo allowlist; `agent_sessions` writes (340/14d) are the generic per-cycle observability wrapper used by the risk monitor / day-orchestrator / post-trade-learning — `observability/agent_sessions.py` — **not** the QUANT_AGENTS pipeline, so they do not indicate agents ON).
- **Last runtime evidence:** no agent-signal artifact on recent scans; NOT_PROVEN-on but strongly INFERRED off.
- **Affect live entries?** YES if flipped (injects design/sizing signals into the midday suggestion cycle). **Kill:** `QUANT_AGENTS_ENABLED` unset → OFF. **Action:** keep dark; if ever considered, treat as a live-path behavioral change (not observe-only).

### 3. Surface V4 (vol-surface agent) — `WIRED_DISABLED_BY_FLAG` (subsumed by #2)
- No standalone `surface_v4` engine exists. "Surface V4" = `VolSurfaceAgent` in the Quant-Agents pipeline (`agents/runner.py:56`, `QUANT_AGENT_VOL_SURFACE_ENABLED` default True) gated behind the parent `QUANT_AGENTS_ENABLED` (OFF). VERIFIED-CODE. Same disposition as #2.

### 4. Regime Engine V4 — `BUILT_NO_PRODUCTION_CALLER`
- **Module:** `analytics/regime_engine_v4.py`. Header (VERIFIED-CODE): "BUILT BUT UNWIRED … ZERO production callers — only tests import it. The live regime path is regime_engine_v3 everywhere." `test_regime_v4_unwired.py` pins the zero-caller state.
- **Flag:** `REGIME_V4_ENABLED` default false — **"gates nothing today; a set value is a no-op."**
- **Effective value:** irrelevant (flag wired to nothing). **Affect live entries?** No. **Action:** keep as reserved activation interface; remove-or-wire is an owner call. Not in echo (correct — nothing to echo).

### 5. Cross-asset regime filter (D4) — `WIRED_OBSERVE_ONLY` (active)
- **Module:** `analytics/regime_filter.py`. OBSERVATION-ONLY; rates+credit (TLT/HYG) proxy read; logs what it *would* throttle vs the live v3 decision; VIX excluded by design.
- **Flag:** `REGIME_FILTER_OBSERVE_ENABLED` default `0`. **Effective value: ON** — `regime_filter_observations` = 118 rows, **17 in last 7d**, last 07-23 (VERIFIED-DB → flag is enabled in prod).
- **Affect live entries?** No (changes no classification/throttle/sizing). **Why inactive-for-decisions:** graduation to enforcement is a separate gated decision pending agreement-with-reality on the logged record. **Action:** natural evidence accrual, then owner graduation decision.

### 6. Volatility signal observation — `WIRED_OBSERVE_ONLY` (active)
- **Module:** `analytics/vol_signal.py`; handler `jobs/handlers/vol_signal_snapshot.py`, **scheduler-registered** 5:15 CT (`scheduler.py:90`).
- **Flag:** `VOL_SIGNAL_OBSERVE_ENABLED` default OFF. **Effective value: ON** — `vol_signal_observations` = 34 rows, 5 in 7d; `vol_signal_snapshot` job succeeded 07-23 10:15Z (37 runs) (VERIFIED-RUNTIME/DB).
- **Affect live entries?** No (research layer; touches no scanner/regime/trading path). **Action:** natural evidence.

### 7. OI enrichment + hypothetical OI floor — `WIRED_OBSERVE_ONLY` (active, NO gate)
- **Modules:** OI enrichment `analytics/option_liquidity.py` → `option_liquidity_observations` (4,163 rows, **782 in 7d**, VERIFIED-DB, active). Hypothetical floor `services/quote_provenance.py` Lane H (`:153-434`) — per-leg would_pass/would_fail at candidate floors {100,250,500,1000}, recorded into `option_quote_provenance` (471 rows, all in 7d).
- **Header (VERIFIED-CODE):** "There is no control and this recorder NEVER consults these floors to admit or reject … observe-only." Dark legs abstain (INDETERMINATE), never fabricated-fail (H9).
- **Flag:** `QUOTE_PROVENANCE_ENABLED` default-ON (in echo). **Effective: ON** (writes present).
- **Affect live entries?** No. **Action:** natural OI rows → owner floor decision (100/250/500/1000). Owner-owned.

### 8. Tier taper v2 — `WIRED_OBSERVE_ONLY` (DARK, active on the live cycle)
- **Module:** `services/analytics/tier_taper.py` (pure, versioned, no I/O). **Prod caller:** `services/workflow_orchestrator.py:2461-2485` `tier_taper.observe(...)` in `run_midday_cycle` (which `suggestions_open` runs daily) → logs `[TIER_TAPER]` and stamps `suggestion_meta.tier_taper` (VERIFIED-CODE).
- **Effective:** DARK / observe (the live sizing path does NOT consume the proposed params; `current`==raw cliff outside the band). No enable-flag on the observe write; **arming** is separate (`docs/specs/tier_taper_activation_packet.md`).
- **Affect live entries?** No (observe-only). **Why inactive:** activation is a flag-gated owner decision; ratified band `[800,1000]` conflicts with the engine's `[900,1100]` — reconciliation is a pending code step. **Action:** owner decision (band reconcile + `ENGINE_VERSION` bump).

### 9. TCM v2 + promotion consumer — `WIRED_OBSERVE_ONLY`
- **Module:** `services/tcm_v2_proposal.py` (routing-aware commission proposal beside the frozen `execution/transaction_cost_model.py`). **Prod caller:** `paper_endpoints.py:787` `[TCM_V2] dual-run proposal` at the entry-stage seam (observe-only; `TCM_V2_STAMP_KEY` sibling on `entry_tcm`). Promotion/accrual consumer = realized-cost study (`test_realized_cost_study_tcm_v2_accrual`).
- **Effective:** observe-only, **feeds NO decision** (selector/ranker/gate/executor keep reading the frozen model). Backlog: **0/528 v2 stamps** yet (stamps accrue only when an entry is staged — rare book).
- **Affect live entries?** No. **Action:** owner promotion decision at N=15 (owner-packet-5); natural stamp accrual pending.

### 10. Greek capture / counterfactual / live-cap consumer — `WIRED_OBSERVE_ONLY` (caps dormant)
- **Capture (#1259/#1263/#1269):** per-leg stage-time greeks now populate the canonical `normalize_position`/`aggregate_greeks` path; `portfolio_greeks` is the honest signed net. **Consumers (VERIFIED-CODE):** `risk/risk_envelope.py`, `services/risk_budget_engine.py`, `risk/position_model.py`, `paper_endpoints.py`.
- **Counterfactual (#1282):** `risk/risk_envelope.py:508-633` greek-cap ALERT-ONLY counterfactual — records per-tightness-row `would_block` beside the armed caps. **All four caps default 0 = no-limit (dormant).** Because historical/most legs still carry no greeks, every reference row reads `would_block=None` (unavailable) — never a fabricated block (H9).
- **Effective:** caps 0 (source `code_default`); counterfactual observe-only. **Affect live entries?** No (caps 0 → no limit). **Action:** arming caps is a separate owner decision that must consume `greeks_coverage` (Plan A staged, owner-packet-7).

### 11. Risk-basis max-loss shadow + arm evidence — `WIRED_OBSERVE_ONLY` (arm evidence ACTIVE)
- **Module:** `services/risk_basis_shadow.py` (P0-B). Consumers: `services/risk_budget_engine.py`, `risk/utilization_gate.py`, `services/portfolio_allocator.py` — each logs `[RISK_BASIS_SHADOW]` (both bases + `would_flip`).
- **Flag:** `RISK_BASIS_MAX_LOSS_ENABLED` strict `=="1"`, **default OFF** → decisions stay byte-identical on the current basis.
- **Arm evidence (#1306 Lane A):** durable `job_runs.result.cycle_metadata.risk_basis_arm_evidence` — **PRESENT and accruing on the executor path: `paper_auto_execute` = 5 of 20 runs in 14d carry it, last 07-23 16:30Z** (VERIFIED-RUNTIME). (Absent from `suggestions_open`/`suggestions_close` — correct; the risk-basis consumers run in the executor cycle.) This resolves the prior "F-A4-RISKBASIS-SILENT" concern: the durable would-flip evidence contract is now emitting.
- **Affect live entries?** No while OFF. **Action:** ~1-week arm review off the accruing evidence, then owner observe→enforce decision.

### 12. Correlation-bucket shadow / enforcement — `WIRED_OBSERVE_ONLY`
- **Module:** `risk/bucket_control.py` (one-beta bucket control + same-run reservation). Logs `[BUCKET_SHADOW]`; fires the #1139-class alarm on a would-block that PROCEEDS.
- **Flag:** `BUCKET_CONTROL_ENFORCE` strict `=="1"`, **default OFF → observe** (`bucket_max_pct` default 0.25). **Affect live entries?** No while OFF (when armed, rejects with `bucket_exposure_cap`). **Action:** owner observe→enforce decision (fourth Option-A application).

### 13. Independent terminal-distribution / credit-EV replacement — `WIRED_OBSERVE_ONLY` / study
- **Modules:** `analytics/terminal_distribution/*` (contract, baselines, `challenger_lognormal.py`, `payoff.py`, `evaluator.py`, `single_leg.py`). Honest lognormal challenger (abstains on missing IV/spot — no `0.30`/`0.05`/`0.5` fabrications).
- **Consumer:** `analytics/model_review.py` + `scripts/analytics/challenger_study.py` (STUDY read), fired by the #1286 **event-driven model review (inert until first scorable close)**. Live EV stays `ev_calculator` (#1051). Capture side (scan-time spot+IV+delta, #1266/#1274) is active on staged rows.
- **Effective:** challenger scored only via the study/event path; not wired into live scoring. **Affect live entries?** No. **Action:** natural evidence (first scorable close triggers the review) → `INCONCLUSIVE` until then.

### 14. E19 v3(/v4) protocol + executor — `BLOCKED_OWNER_DECISION`
- **Module:** `policy_lab/shadow_fleet.py` (E19 executor) + prereg contract; upstream hash registry `tests/e19_upstream_registry.py`.
- **Status:** E19-2B protocol **v2 FROZEN** (hash `50e7e237…`, #1284); **BLOCKED on the §7 `MINIMUM_DISTINCT_SOURCE_EVENTS` owner value.** Ratified minimum = 8 but awaits **protocol v3 re-freeze**; executor is post-fleet-epoch (needs fleet activation). No runtime.
- **Affect live entries?** No. **Action:** owner (re-freeze v3 @ minimum 8) + fleet activation epoch first.

### 15. 50-policy shadow fleet (activation surface vs recurring evaluator) — `SCHEMA_OR_RPC_ONLY` / `BLOCKED_OWNER_DECISION`
- **Provisioned INACTIVE (VERIFIED-DB):** `shadow_fleets` = 1 row `small_tier_v1` status `pending_legacy_terminal`, `legacy_terminal_verified_at=NULL`, `effective_at=NULL`. `shadow_micro_accounts` = **50 inactive slots, 0 with policy binding, 0 activated.** `policy_registrations` = **50 approved** (17 aggressive / 17 neutral / 16 conservative, all distinct hashes, epoch `small_tier_v1`).
- **Activation surface:** `services/shadow_fleet_activation.py` (RPC `rpc_shadow_fleet_activate`, hardened 5-arg; binding fingerprint reproducible `1cd004b5…`). **There is NO recurring fleet evaluator** — no scheduled job binds/evaluates the 50 slots; activation is a one-shot operator RPC gated by `FLEET_ACTIVATION_AUTHORIZED` (strict `=="1"`, **in the echo allowlist**, default OFF).
- **Effective:** `ACTIVATE_FLEET=false`; fleet UNCHANGED/INACTIVE. **Affect live entries?** No (shadow/observe-only by charter; never authorizes a live flag/control). **Action:** owner-gated activation (re-attest `1cd004b5…` + scenario-5 receipt + Monday evidence). **Do NOT activate.**

### 16. Fleet reconciliation receipts (producers) — mixed
- **stale_order producer:** `jobs/handlers/alpaca_order_sync.py:33-160` (Step 1.5). Flag `FLEET_RECEIPT_PRODUCER_ENABLED` strict `=="1"` **default OFF** (`_fleet_receipt_producer_enabled`). Runtime ghost-sweep line shows `stale_review_orders=0 stale_review_alerts_fired=0` and `fleet_reconciliation_receipts` = **0 rows** (VERIFIED-DB). → **`WIRED_DISABLED_BY_FLAG`** (producer wired, gated off; no stale orders to act on anyway).
- **manual_review / orphan_run producers:** **`BUILT_NO_PRODUCTION_CALLER`** — the canonical writer `services/fleet_reconciliation_receipt.py` header states (VERIFIED-CODE) "NO standing code producer completes these kinds — the four 07-18 reconciliations were operator-run SQL." Only the module (writer + `stamp_and_issue_reconciliation_receipt`) exists.
- **Affect live entries?** No. **Action:** the stale_order producer is the only coded producer; manual_review/orphan_run remain operator-SQL. Keep dark until fleet activation needs receipts.

### 17. Prequential validator cadence — `BUILT_NO_PRODUCTION_CALLER` (study, no cadence)
- **Module:** `analytics/prequential_validator.py`. Header (VERIFIED-CODE): "STUDY tool, not a production path — **it schedules nothing and changes no live behavior.**" No scheduler entry, no handler. **Cadence: NONE.** Invoked only by a script/test. **Action:** keep as falsifier study; no build.

### 18. Strategy graduation / eligibility helper — `ACTIVE_RUNTIME_PROVEN` (terminal no-op)
- **Module:** `services/progression_service.py` `evaluate_strategy_lifecycle()`; job `daily_progression_eval` (scheduler 16:00 CT, 82 runs, last 07-22 succeeded — VERIFIED-RUNTIME).
- **DB:** `strategy_lifecycle_states` = 5 rows, **all `live_full`** (transitioned 2026-05-07). Auto-graduation EXPERIMENTAL→LIVE_FULL machine is terminal (nothing left to graduate). `closed_trade_count` is NULL on all rows (the counter is not being repopulated — minor observability gap, not a gate). **Action:** none; keep. Note the NULL counter for the taxonomy backlog.

### 19. Canonical-position remaining consumers — `ACTIVE_RUNTIME_PROVEN` (largely wired)
- `normalize_position`/`aggregate_greeks` consumers (VERIFIED-CODE): `services/risk_budget_engine.py`, `risk/position_model.py`, `risk/risk_envelope.py`, `paper_endpoints.py`. Greeks wiring (#1263) into the canonical path is live; D3 ratio-blindness RESOLVED (#1290). **Remaining:** arming the greek caps (owner, #10) — the only open consumer decision. **Affect live entries?** Greeks feed the (dormant-cap) envelope; no cap active. **Action:** owner cap-arming decision.

### 20. Multi-basis cost remaining consumers — `ACTIVE_RUNTIME_PROVEN` (consumers 1-3 shipped)
- `analytics/cost_basis.py` consumers (VERIFIED-CODE): `risk_budget_engine.py`, `position_model.py`, `risk_envelope.py`, `paper_endpoints.py` (cost-basis parity locked). Consumer #3 = per-routing realized commission (#1273). **Remaining:** the 4th estimated basis in `scoring.py` + densifying `close_fill_gap` stamps (backlog). **Action:** natural accrual / next consumer slice; no gate change.

### 21. F-REDATE correction — `BLOCKED_OWNER_DECISION` (operator packet, unexecuted)
- **Artifact:** `docs/review/f-redate-correction-packet-2026-07-21-final.md` (20 re-dated shadow `closed_at` rows; paper-window contamination; live calibration excluded by `is_paper=false`). Data correction, not code. **Unexecuted** (operator-owned). **Affect live entries?** No (shadow rows; live calibration already excludes them). **Action:** operator adjudication of the packet.

### 22. Flag-echo allowlist coverage (Lane D feeder) — `ACTIVE_RUNTIME_PROVEN` (27 flags), but census-blind
- **Module:** `observability/flag_echo.py` — allowlist of exactly **27** flags, echoed once per process start (VERIFIED-CODE). Covers the mainline controls (entry/exit safety, streak breaker, calibration, autopilot, execution mode, **`FLEET_ACTIVATION_AUTHORIZED`**).
- **MISSING from the echo (feeds Lane D):** every dark/observe/experimental control in this census is INVISIBLE to the startup echo — `QUANT_AGENTS_ENABLED`, `REGIME_V4_ENABLED`, `REGIME_FILTER_OBSERVE_ENABLED`, `VOL_SIGNAL_OBSERVE_ENABLED`, `RISK_BASIS_MAX_LOSS_ENABLED`, `BUCKET_CONTROL_ENFORCE`, `FLEET_RECEIPT_PRODUCER_ENABLED`, `SINGLE_LEG_*`/`single_leg_experiment_enabled`, tier-taper arming flag, TCM v2, greek-cap arming flags. **Action (Lane D):** extend the allowlist to the observe/enforce toggles so an accidental arm is greppable at startup — the current echo would not surface a dark control being flipped on.

---

## Summary classification table

| # | Feature | Classification | Affects live entries if flipped | Effective (source) |
|---|---------|----------------|---------------------------------|--------------------|
| 1 | Single-leg shadow experiment | WIRED_DISABLED_BY_DB_STATE | No | epoch_absent + 0/50 opt-in (DB_state) |
| 2 | Quant Agents pipeline | WIRED_DISABLED_BY_FLAG | **Yes** | OFF (code_default/INFERRED) |
| 3 | Surface V4 (vol-surface agent) | WIRED_DISABLED_BY_FLAG | Yes (via #2) | OFF (code_default) |
| 4 | Regime Engine V4 | BUILT_NO_PRODUCTION_CALLER | No | flag no-op (VERIFIED-CODE) |
| 5 | Cross-asset regime filter | WIRED_OBSERVE_ONLY | No | ON-observe (DB_state: writes) |
| 6 | Volatility signal observation | WIRED_OBSERVE_ONLY | No | ON-observe (DB_state/RUNTIME) |
| 7 | OI enrichment + hypothetical floor | WIRED_OBSERVE_ONLY | No | ON, no-gate (DB_state) |
| 8 | Tier taper v2 | WIRED_OBSERVE_ONLY (DARK) | No | observe (VERIFIED-CODE) |
| 9 | TCM v2 + promotion consumer | WIRED_OBSERVE_ONLY | No | observe, 0/528 stamps |
| 10 | Greek capture/counterfactual/caps | WIRED_OBSERVE_ONLY | No | caps 0 (code_default) |
| 11 | Risk-basis max-loss shadow + arm ev | WIRED_OBSERVE_ONLY | No | OFF; arm-ev ACTIVE (RUNTIME) |
| 12 | Correlation-bucket shadow/enforce | WIRED_OBSERVE_ONLY | No | enforce OFF (code_default) |
| 13 | Terminal-distribution / credit-EV | WIRED_OBSERVE_ONLY / study | No | study/event, INCONCLUSIVE |
| 14 | E19 v3/v4 protocol + executor | BLOCKED_OWNER_DECISION | No | frozen v2, no runtime |
| 15 | 50-policy shadow fleet | SCHEMA_OR_RPC_ONLY / BLOCKED_OWNER | No | INACTIVE (DB_state) |
| 16a | Fleet stale_order receipt producer | WIRED_DISABLED_BY_FLAG | No | OFF (code_default; 0 receipts) |
| 16b | manual_review/orphan_run producers | BUILT_NO_PRODUCTION_CALLER | No | operator-SQL only |
| 17 | Prequential validator | BUILT_NO_PRODUCTION_CALLER | No | no cadence (VERIFIED-CODE) |
| 18 | Strategy graduation helper | ACTIVE_RUNTIME_PROVEN | No | all live_full (DB) |
| 19 | Canonical-position consumers | ACTIVE_RUNTIME_PROVEN | Greeks feed dormant caps | wired (VERIFIED-CODE) |
| 20 | Multi-basis cost consumers | ACTIVE_RUNTIME_PROVEN | No | #1-3 shipped |
| 21 | F-REDATE correction | BLOCKED_OWNER_DECISION | No | unexecuted packet |
| 22 | Flag-echo allowlist | ACTIVE_RUNTIME_PROVEN (blind) | n/a | 27 flags; dark controls absent |

---

## Free-look — NEW candidates (max 5, deduped vs ledger/backlog + brief non-rediscovery list)

| Candidate | Classification | Evidence | Recommended |
|-----------|----------------|----------|-------------|
| **F1. v4 Accounting ledger subsystem** — `position_groups/position_legs/fills/position_events/reconciliation_breaks/position_leg_marks` | BUILT_NO_PRODUCTION_CALLER | **All 6 tables 0 rows** (VERIFIED-DB). Writers exist (`services/position_ledger_service.py`, `position_pnl_service.py`, `jobs/handlers/seed_ledger_v4.py`) but `seed_ledger_v4` is NOT scheduler-registered and no live caller invokes the ledger service — the live book uses `paper_positions`/`paper_ledger`. | remove-retire OR owner decision (is the double-entry ledger ever adopted?) |
| **F2. Nested-regime inference persistence** — `nested_regimes`(0)/`model_states`(0)/`outcomes_log`(0) | BUILT_NO_PRODUCTION_CALLER | 0 rows all (VERIFIED-DB); writers `nested_logging.py`, `nested/adapters.py` never invoked in prod. Distinct from `regime_engine_v4`. | remove-retire |
| **F3. Walk-forward autotune → `autotune_history`** | BUILT_NO_PRODUCTION_CALLER | `autotune_history` 0 rows (VERIFIED-DB); writer `analytics/walk_forward_autotune.py:443` has no scheduled caller. | remove-retire OR keep dark |
| **F4. `phase2_precheck` scheduled job** | DEAD_OR_PHANTOM | `scheduler.py:132` still registers a PR#6 Phase-2 verifier that self-no-ops once `hours_since_deploy>48` — permanently expired months ago; a standing scheduler slot firing a guaranteed no-op each cadence. | remove-retire |
| **F5. `live_approval_queue`** | ACTIVE_UNEXERCISED | 0 rows (VERIFIED-DB); writer `brokers/safety_checks.py:216` (human live-order approval gate) has never enqueued — the champion routes without hitting it. | owner decision — confirm whether live entries are meant to route through the approval gate or it is superseded |

---

## Lane-F disposition table

### build now
- (none) — no dark/observe control is blocked on a missing build slice this session; every mandatory item is either already-observing, owner-gated, or evidence-gated.

### owner decision
- **Fleet activation** (#15) — re-attest `1cd004b5…` + scenario-5 receipt + Monday-evidence; irreversible-in-place. Do NOT activate.
- **Tier-taper arming** (#8) — reconcile ratified band `[800,1000]` vs engine `[900,1100]` + `ENGINE_VERSION` bump, then arm.
- **TCM v2 promotion** (#9) at N=15 (owner-packet-5).
- **Greek-cap arming** (#10/#19) — Plan A staged; must consume `greeks_coverage`.
- **Correlation-bucket enforce** (#12) and **risk-basis max-loss enforce** (#11) — observe→enforce decisions (arm evidence for #11 is now accruing).
- **OI floor** (#7) — pick 100/250/500/1000 after natural rows.
- **E19** (#14) — re-freeze protocol v3 @ minimum 8 (post fleet epoch).
- **Single-leg** (#1) — seed an epoch + two draft opt-in registry rows (owner-packet-4).
- **F5 live_approval_queue** — adjudicate intended role.

### natural evidence (no action; INCONCLUSIVE until the event)
- Cross-asset regime filter (#5), vol-signal (#6), OI capture (#7), tier-taper observe (#8), TCM v2 stamps (#9), risk-basis arm review ~1 week (#11), terminal-distribution challenger — first scorable close fires #1286 (#13), multi-basis #4 consumer densification (#20).

### remove-retire
- **F1 v4 accounting subsystem**, **F2 nested-regime persistence**, **F3 autotune_history writer**, **F4 phase2_precheck scheduler slot** — dormant/dead with no runtime footprint.
- Consider retiring **Regime Engine V4** (#4) if no V4 wiring is planned (flag gates nothing).

### keep dark
- Quant Agents (#2/#3), fleet receipt producers (#16), prequential validator (#17), single-leg tables (#1), greek-cap counterfactual (#10). No change without an owner trigger.

### Lane D (flag-echo) — actionable
- Extend `observability/flag_echo.py` allowlist to the observe/enforce toggles (`QUANT_AGENTS_ENABLED`, `REGIME_FILTER_OBSERVE_ENABLED`, `VOL_SIGNAL_OBSERVE_ENABLED`, `RISK_BASIS_MAX_LOSS_ENABLED`, `BUCKET_CONTROL_ENFORCE`, `FLEET_RECEIPT_PRODUCER_ENABLED`, tier-taper/TCM-v2/greek-cap arming). Today a dark control being flipped ON would not appear in the startup echo — the one place doctrine says to read effective state.

---

## Side note (not part of the census, surfaced per advisor)
Supabase advisor flags **33 tables with RLS disabled** (incl. `trade_suggestions`, `decision_runs`, most `*_observations`, `suggestion_rejections`). Largely the known forward-only observation/analytics set; pre-existing, not this audit's scope — noting for the operator, no auto-remediation.
