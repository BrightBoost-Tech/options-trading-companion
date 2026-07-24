# TD-scan v2 per-gate attribution — AUDIT (read-only)

**Audit date:** 2026-07-24 · **Repo pin:** `f8a69334` (read in place) · **Mode:** READ-ONLY (audit only; build is a later lane).
**Author lane:** TD-scan v2 attribution (stacked on Lane A's shared envelope-v2 contract).
**Shared contract file** `C:\Users\17734\AppData\Local\Temp\otc-fourgap\lane-a-envelope-v2-contract.md`: **ABSENT at audit time.** This audit is therefore designed STANDALONE; alignment with Lane A's frozen contract is a merge-time reconciliation (Lane A owns capture/schema-file ownership; see Blockers).

**Grounding (SELECT-only, production DB `etdlladeorfgdmsopzmz`):**
- `td_scan_envelopes` table EXISTS (migration `20260723160000` applied), **0 rows** — the observe flag `TERMINAL_DISTRIBUTION_SCAN_OBSERVE_ENABLED` is default-OFF; no scan has captured yet.
- `candidate_terminal_dispositions` table EXISTS (migration `20260717100000` applied), **65 rows, all `is_final`, 51 distinct fingerprints** — the downstream disposition writer is live in production. Distribution: `rank_blocked` 44 (reasons `edge_below_minimum`, `not_selected_by_ranker`), `h7_dropped` 20 (all `h7_subreason=roundtrip_bp`, reason `h7_prefilter`), `persisted_executable` 1.
- `option_quote_provenance` EXISTS with `legs jsonb` + `leg_fingerprint text` + `verdict`/`reject_reason`/`selected`.

---

## 1. Rejection topology (post-construction → terminal)

The capture seam is **`options_scanner.py:4107`** (`td_scan_recorder.record(...)`), placed immediately after `total_ev` is computed and BEFORE every cost/spread/earnings/lifecycle/agent gate (comment `:4099-4106`). Fingerprint = `compute_legs_fingerprint` (structure-only, 64-char sha256, leg-order-independent; `options_utils.py:138`). The `emitted` flag is resolved at scan-flush (`td_scan_capture.py:363-406`) by comparing each envelope's fingerprint to the returned candidate set. **v1 labels every non-emitted envelope `reject_reason='unattributed_post_ev'`, `reject_gate='post_ev_gate'`** (`td_scan_capture.py:384-385`).

There are **three sequential phases** after capture. The critical fact for attribution: the **`emitted` boolean cleaves the population into two identity regimes.**

### Phase 1 — WITHIN-SCANNER (`options_scanner.py process_symbol`) → envelopes with `emitted=false`
Gates AFTER the capture seam (a candidate that dies here is captured `emitted=false`; a candidate that survives is `emitted=true`):

| Gate | file:line | Terminal reason(s) | Existing typed evidence | Fingerprint survives? |
|---|---|---|---|---|
| Liquidity/spread | `:4224` | `spread_too_wide_real` / `entry_cost_too_low` / `spread_too_wide` (`:4267-4272`) | (a) `suggestion_rejections` + `spread_debug` sample (`:4307`); (b) `option_quote_provenance` `record_spread_verdict(verdict='rejected')` with `legs`+`leg_fingerprint`+`reject_reason` (`:4281`) | **Coarse** in rejections; **leg-carrying** in provenance but see §2 hash mismatch |
| Execution-cost | `:4416` | `execution_cost_exceeds_ev` (hard reject when `EXECUTION_COST_HARD_REJECT` & not ELEVATED/SHOCK; else soft badge→emit) (`:4442-4453`) | `suggestion_rejections` + `exec_sample` | **No** (coarse only) |
| Earnings | `:4510` | `earnings_short_premium` (≤2d, short premium) | `suggestion_rejections` (coarse) | **No** |
| Lifecycle | `:4543-4574` | `strategy_lifecycle_unavailable/empty/missing/invalid_state`, `strategy_designed`, `strategy_deprecated` | `suggestion_rejections` (coarse) | **No** |
| Agent veto | `:4736` | `agent_veto` | `suggestion_rejections` (coarse) | **No** |
| Processing error | `:4774` | `processing_error` | `suggestion_rejections` (coarse) | **No** |
| **EMIT** | `:4766-4767` | `record_emission` → candidate returned → `emitted=true` | — | — |

`suggestion_rejections` payload (`options_scanner.py:414-424`) = `{symbol, strategy_key(=suggestion["strategy"]), reason, cycle_date, event_id, job_run_id, spread_debug?}`. **No legs, no candidate_fingerprint** — the identity break for the emitted=false population.

> Pre-capture gates (`missing_quotes` `:3386`, `insufficient_history` `:3467`, `no_chain` `:3692`, `strategy_hold_no_candidates` `:3594`, etc.) reject BEFORE the candidate has exact legs → **no envelope is captured** → out of v2 scope by construction.

### Phase 2 — ORCHESTRATION (`workflow_orchestrator.py run_midday_cycle`) → operates on `emitted=true` envelopes
Recorder `CandidateDispositionRecorder` (`_ctd`), created `:2793`, writes `candidate_terminal_dispositions` keyed **`(cycle_id, candidate_fingerprint, attempt)`** — the SAME `compute_legs_fingerprint`. Every row is **leg-exact identity-preserving.**

| Gate | file:line | Disposition · detail | Fingerprint survives? |
|---|---|---|---|
| Ranker: not selected | `:2807` | `rank_blocked` · `not_selected_by_ranker` (`selected=false`, out-ranked alternates) | **YES (exact)** |
| **MIN_EDGE_AFTER_COSTS** ($15, `canonical_ranker.py:24,136-142` → `-999` sentinel) | `:4166-4176` | `rank_blocked` · `edge_below_minimum` + `risk_adjusted_ev`; also stamps `trade_suggestions.blocked_reason='edge_below_minimum'` | **YES (exact)** |
| H7 pre-filter (round-trip BP; `H7_PREFILTER_ENABLED` default **false=shadow**) | `:2870,2904` | `h7_dropped` · `h7_subreason=roundtrip_bp`, reason `h7_prefilter` | **YES (exact)** |
| Marketdata quality gate E4/E5 (HARD) | `:3384,3883,3939` | `h7_dropped` · `h7_subreason=quality_gate` | **YES (exact)** |
| Per-candidate risk budget (`final_risk_dollars<=0`) | `:3645` | `h7_dropped` · `h7_subreason=risk_budget` | **YES (exact)** |
| Sizing→0 (the REAL H7; `contracts==0`, dominant death) | `:4206` | `h7_dropped` · `h7_subreason=sizing_zero` + `round_trip_required` | **YES (exact)** |
| Allocator (`not_in_allocator_output`) | `:3023` | `allocator_dropped` | **YES (exact)** |
| Persist seam | `:4452-4483` | persisted pending→`persisted_executable`; NOT_EXECUTABLE→`rank_blocked`(edge)/`persisted_blocked`; no-row→`persisted_blocked` + `insert_failed=true`; **re-finals the SAME attempt with `suggestion_id`** | **YES (exact) + suggestion_id** |

### Phase 3 — EXECUTION STAGE (`paper_autopilot_service.py`→`paper_endpoints.py`; separate 11:30 executor job) → operates on `persisted_executable`
Stage gates stamp `trade_suggestions.blocked_reason` via `_stamp_blocked_reason` (`paper_autopilot_service.py:766`), keyed by `suggestion_id` (which carries `legs_fingerprint`). Forward milestones advance `_ctd` via `advance_candidate_milestone` (`:1186`, forward-only staged→broker_submitted→filled).

| Gate | file:line | `trade_suggestions.blocked_reason` | Fingerprint survives? |
|---|---|---|---|
| #1040 symbol cooldown | `paper_autopilot_service.py:1234` | `symbol_cooldown` | YES (via `legs_fingerprint`) |
| #1044 utilization | `:1244-1256` | `entry_utilization_blocked` / `utilization_gate_error` | YES |
| #1038 entry-quote unpriceable | `:1278` | `entry_quote_unpriceable` (`EntryQuoteUnpriceable`) | YES |
| **#1101 round-trip cost gate** (`gross_ev − Σ(ask−bid)×contracts×100 < $15`) | `:1295-1304`; `paper_endpoints.py:1572,1764` | `ev_below_roundtrip_cost` | YES |
| #1052 options-level preflight | `paper_endpoints.py:1789-1902` | preflight `blocked_reason` | YES |
| Milestones | `:1186` | (ctd forward advance) staged/broker_submitted/filled | YES (suggestion_id) |

**Key structural note:** execution-stage blocks do **NOT** write a `candidate_terminal_dispositions` block-final — they only stamp `trade_suggestions.blocked_reason` + forward-advance milestones. So a candidate that reached the executor keeps ctd disposition `persisted_executable` while its stage-gate fate lives on `trade_suggestions.blocked_reason`. Both are leg-exact.

---

## 2. JOIN feasibility verdict

**Identity chain (verified, all three use the identical `compute_legs_fingerprint`, structure-only 64-char):**
`td_scan_envelopes.candidate_fingerprint` == `candidate_terminal_dispositions.candidate_fingerprint` == `trade_suggestions.legs_fingerprint` (col added `20251222000000`; ctd migration comment `:104-106`; td migration comment `:68-71`).

### Verdict A — `emitted=true` population: **FULLY join-feasible, leg-exact, ZERO new capture code.**
Every downstream gate (Phase 2 + Phase 3) already writes leg-exact typed provenance. Exact gate attribution is derivable purely by JOIN:
- `candidate_terminal_dispositions` → `rank_blocked{edge_below_minimum|not_selected_by_ranker}`, `h7_dropped{roundtrip_bp|quality_gate|risk_budget|sizing_zero}`, `allocator_dropped`, `persisted_executable/blocked`, milestones. (65 live rows prove the pipe is flowing.)
- `trade_suggestions.blocked_reason` → the Phase-3 stage gates (`ev_below_roundtrip_cost` #1101, `entry_utilization_blocked` #1044, `entry_quote_unpriceable` #1038, `symbol_cooldown` #1040, preflight #1052).

**Join key must be `(cycle_date, candidate_fingerprint)`, NOT `cycle_id`.** `cycle_id` equals the replay `DecisionContext.decision_id` on BOTH tables ONLY when `REPLAY_ENABLE` is on (`td_scan_capture.py:293-302`, `candidate_disposition.py:298-307`, both resolve `get_current_decision_context()`); when replay is off, each recorder mints an INDEPENDENT `uuid4()` → cycle_ids diverge across the two tables. `cycle_date` is safe because the scheduler runs one scan/execution shot per trading day (CLAUDE.md §6: 11:00 scan → 11:30 executor). **Verify `REPLAY_ENABLE` on Railway** — if on, `cycle_id` is additionally usable and preferred; if off, `(cycle_date, candidate_fingerprint)` is the only robust key (add a most-recent tiebreak to defend against a same-day forced re-scan).

### Verdict B — `emitted=false` population (rejected inside the scanner): **PARTIAL; identity break confirmed.**
- `candidate_terminal_dispositions` does **NOT** contain them. The `scanner_rejected` disposition value exists in the CHECK enum (`candidate_disposition.py:86`) but has **NO production writer** (grep: only enum/tests) — the `_ctd` recorder is created in the orchestrator AFTER the scanner returns and only sees the emitted `scout_results`.
- `suggestion_rejections` HAS them but keyed **coarse** `(cycle_date, symbol, strategy_key=suggestion["strategy"], reason)` — **no fingerprint, no legs.** This is the identity break: the leg-exact fingerprint does not survive to the rejection row.
- `option_quote_provenance` carries `legs`+`leg_fingerprint`+`reject_reason` but **ONLY for the spread gate** (`spread_too_wide*`, `entry_cost_too_low`) — not exec-cost/earnings/lifecycle/agent. **⚠ Its `leg_fingerprint` is a DIFFERENT hash** (`quote_provenance.py:134-149`: 16-char, raw-OCC, no `parse_option_symbol`) — it will **not** join directly to `candidate_fingerprint`. A join must **recompute `compute_legs_fingerprint` from `option_quote_provenance.legs` jsonb** (both tables carry the legs), which is exact for spread-gate rejects.

Coarse-join cardinality: within one cycle, `process_symbol` runs once per `(symbol, strategy)` attempt (multi-strategy fallbacks use distinct strategy values; `td_scan_capture.py` flush dedups by fingerprint) → the terminal post-capture reason is ~1:1 with the envelope per `(cycle_date, symbol, strategy)`. Usable for attribution, but **not identity-guaranteed** (two distinct fingerprints sharing `(symbol, strategy)` in one cycle would be ambiguous — flag as `coarse` confidence, never fabricate).

---

## 3. Minimal v2 design (recommendation)

Per the orchestrator directive ("prefer join-based attribution over new write paths; additive-only if a column is genuinely missing"):

### Core v2 = **Option A: read-side scorer join (ZERO scanner change, ZERO schema change).**
The existing background child `td_scan_observe.py` / `scripts/analytics/td_scan_scorer.py` already writes `td_scan_scores.{reject_gate, reject_reason, gate_counterfactuals}` (**columns already exist**, migration `20260723160000:83-111`). v2 resolves the exact gate at SCORE time by joining each envelope, in precedence order:
1. `candidate_terminal_dispositions` on `(cycle_date, candidate_fingerprint)` → exact disposition + `detail.h7_subreason` / `detail.reason` (emitted candidates, Phase 2). → `attribution_confidence='exact_disposition'`.
2. `trade_suggestions` on `(cycle_date, legs_fingerprint)` → `blocked_reason` (Phase-3 stage gates). → `exact_blocked_reason`.
3. `option_quote_provenance` on `(cycle_date, symbol, strategy_key)` with **recomputed** `compute_legs_fingerprint(prov.legs)` → spread-gate emitted=false rejects. → `exact_provenance`.
4. `suggestion_rejections` on `(cycle_date, symbol, strategy)` → remaining emitted=false rejects (exec-cost/earnings/lifecycle/agent). → `coarse_symbol_strategy`.
5. No evidence → **`unresolved`** (typed, never fabricated).
Write the resolved `reject_gate`/`reject_reason` (+ `gate_counterfactuals.attribution_confidence` + `source_table`) into `td_scan_scores`. **No new capture, no scanner touch, no migration** (all target columns exist). Byte-identity of the scanner is trivially preserved (read-side only).
**Limitation:** emitted=false non-spread rejects stay coarse (symbol+strategy).

### Optional follow-up = **Option B: close the emitted=false leg-exact gap (additive capture).**
Thread the terminal within-scanner reject reason+gate into `td_scan_recorder` at each post-capture `return None` site in `process_symbol`, so `flush()` fills `reject_reason`/`reject_gate` EXACTLY instead of the coarse `unattributed_post_ev`. **The `reject_reason`/`reject_gate` columns already exist on `td_scan_envelopes`** (`20260723160000:37-38`) — v1 fills them coarse, v2 fills them exact → **no migration, no new column.** The record call stays observe-only/non-mutating; the byte-identical-output contract (`td_scan_capture.py:16-21`) must be **re-proven** with a test. This is the ONLY way to get leg-exact attribution for the emitted=false non-spread population, since `suggestion_rejections` structurally lacks the fingerprint.

**Schema:** neither option needs a new column. If Lane A's frozen contract introduces a versioned envelope column, v2 must consume it additively (never repurpose `reject_reason`/`reject_gate`). Any v2-specific field belongs on the mutable score output `td_scan_scores`, never the immutable `td_scan_envelopes`.

**Effort estimate:**
- **Option A (core):** SMALL. One-to-two files (`td_scan_scorer.py` + join helper), 4 join queries + precedence resolver + confidence typing. No migration, no scanner touch. Tests: join-resolution unit test (each precedence tier) + a scorer route test asserting typed output on a synthetic cycle. **~0.5–1 day.**
- **Option B (leg-exact emitted=false):** SMALL–MEDIUM. Touches `process_symbol` return sites to thread reason→recorder; re-prove byte-identity. No migration. **~1 day** incl. the byte-identity regression test.

Recommend shipping **A first** (contract-safe, zero-risk, closes 100% of the emitted population + spread-gate emitted=false exactly), then **B** as an additive enhancement once Lane A's envelope contract is frozen.

---

## 4. Natural falsifier + typed outcomes

**Falsifier:** the FIRST natural Friday scan (11:00 CT) with `TERMINAL_DISTRIBUTION_SCAN_OBSERVE_ENABLED` truthy AND the same-day 11:30 executor cycle completing — populates `td_scan_envelopes` (emitted + rejected) for that `cycle_date` alongside the same cycle's `candidate_terminal_dispositions` / `trade_suggestions` / `suggestion_rejections` / `option_quote_provenance`. Until then the join is **INCONCLUSIVE by construction** (`td_scan_envelopes` = 0 rows today; no manual/forced scan may substitute — orchestrator hard-stop). Grade PASS only on a natural event.

**Typed per-envelope outcome (v2 must produce exactly one, never fabricate):**
- `reject_gate` ∈ { `liquidity_spread`(spread_too_wide*/entry_cost_too_low), `execution_cost_exceeds_ev`, `earnings_short_premium`, `strategy_lifecycle_*`, `agent_veto`, `rank_blocked:edge_below_minimum`, `rank_blocked:not_selected_by_ranker`, `h7_dropped:{roundtrip_bp|quality_gate|risk_budget|sizing_zero}`, `allocator_dropped`, `ev_below_roundtrip_cost`(#1101), `entry_utilization_blocked`(#1044), `entry_quote_unpriceable`(#1038), `symbol_cooldown`(#1040), `options_level_preflight`(#1052), `emitted_survived`(persisted_executable→staged/filled) }.
- `attribution_confidence` ∈ { `exact_disposition`, `exact_blocked_reason`, `exact_provenance`, `coarse_symbol_strategy`, `unresolved` }.
- **Invariants to assert:** (a) every `emitted=true` envelope resolves to exactly one `(cycle_date, candidate_fingerprint)` ctd final (ctd's own `idx_ctd_one_final_per_identity` guarantees uniqueness); (b) per cycle_date, `count(emitted=true envelopes)` reconciles with ctd final count (modulo attempt/superseded); (c) no envelope is assigned a gate without a joined evidence row — the `unresolved` bucket is honest, not fabricated (H9).

---

## 5. Blockers

1. **Shared envelope-v2 contract ABSENT** (`lane-a-envelope-v2-contract.md` not present at audit time). Per the orchestrator dependency order, v2 build is stacked AFTER Lane A freezes it (both lanes may touch capture/schema files; Lane A owns them). Design here is standalone; reconcile at merge.
2. **`cycle_id` linkage is `REPLAY_ENABLE`-dependent.** Must join on `(cycle_date, candidate_fingerprint)`; verify `REPLAY_ENABLE` on Railway to know whether `cycle_id` is additionally usable.
3. **`option_quote_provenance.leg_fingerprint` is a DIFFERENT hash** (16-char, no OCC parse) — not directly joinable; must recompute `compute_legs_fingerprint` from its `legs` jsonb.
4. **emitted=false non-spread rejects have NO leg-exact evidence** — only coarse `(symbol, strategy)` `suggestion_rejections`; leg-exact requires Option B additive capture.
5. **Natural evidence pending** — `td_scan_envelopes` is EMPTY (flag OFF); the join cannot be validated with real data until the first flag-on Friday scan. INCONCLUSIVE until that event.
6. **Observe-only invariant** — v2 is scorer/read-side; it must change NO gate behavior and preserve scanner byte-identity (re-prove for Option B).
