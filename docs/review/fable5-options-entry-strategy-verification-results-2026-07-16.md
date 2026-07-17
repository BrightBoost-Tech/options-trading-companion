# Fable 5 Options-Entry Strategy Verification — Results (2026-07-16)

**Status: adjudicated results artifact. Read-only audit; docs-only lane. No production
code, migration, DB/broker write, deploy, flag, gate, threshold, sizing, strategy
activation, entry, exit, or control changed.**

## 1. Identity, basis, and observation window

- **Effective model:** Claude Fable 5 (`claude-fable-5`). Model check passed (no
  `BLOCKED_MODEL_MISMATCH`).
- **Audit date (America/Chicago):** 2026-07-16.
- **Immutable code basis (all line citations):** `origin/main` =
  `b95d3a3f5766ff3689be9816f0f90d13fc8cfa3c` ("Reconcile overnight backlog lane
  standing (#1230)", committed 2026-07-16T08:19:12-05:00). Audited in an isolated
  git worktree pinned at this SHA. Main did not move during the audit
  (re-verified at write time); audit basis == documentation-write basis.
- **Documentation SHAs at basis:** `docs/backlog.md` blob `5d3157b` ·
  `audit/ledger.md` blob `9ce8ffa` · `CLAUDE.md` blob `f7ae34a`.
- **Deployment SHAs (Railway, read-only):** BE / worker / worker-background all
  **SUCCESS at `b95d3a3f…`** (deployments created 2026-07-16 13:19:15Z, ~3 s after
  the merge commit). **Deployed SHA == audit SHA on every service** — all
  services run code-equivalent content; no merged-vs-running gap exists for this
  audit.
- **Runtime observation window:** 2026-07-16 19:56–20:4xZ (single session;
  read-only Supabase / Railway / Alpaca reads, each stamped below).

## 2. Clock and environment grounding (STEP 0)

| Clock | Value | Source |
|---|---|---|
| Host UTC | 2026-07-16 19:56:33Z | host `date -u` |
| America/Chicago | 2026-07-16 14:57:02 | host TZ conversion |
| America/New_York | 2026-07-16 15:57:02 | host TZ conversion |
| DB `now()` | 2026-07-16 19:57:05.81Z | Supabase `SELECT now()` |
| Broker clock | 2026-07-16T15:57:23-04:00 · `is_open: true` · next_close 2026-07-16T16:00:00-04:00 · next_open 2026-07-17T09:30:00-04:00 | Alpaca live `get_clock` |

All clocks agree to the second. The audit ran during RTH; per doctrine the lane
performed **zero** deploys, writes, flag changes, or job triggers — natural
runtime evidence was observed read-only only.

Repo state: default branch `main`; local operator worktree carried unrelated
uncommitted changes (modified `audit/ledger.md` [+104/−455 vs origin/main],
untracked `audit/reports/2026-07-14.md`, `2026-07-15.md`, and misc root files)
— **preserved byte-for-byte and untouched**; this audit worked in a separate
pinned worktree. See §13 for the ledger-conflict operator decision.

## 3. Scope, evidence doctrine, limitations

- Source-of-truth precedence re-verified against `CLAUDE.md` §1 at the audit SHA
  (CODE < SUPABASE rows-of-record < RAILWAY running state < ALPACA broker truth);
  disagreements are reported, never averaged.
- Evidence labels used: `VERIFIED-CODE`, `VERIFIED-TEST-REACH`, `VERIFIED-MERGE`,
  `VERIFIED-CI`, `VERIFIED-RUNTIME`, `INFERRED`, `NOT-PROVEN`, `REJECTED`,
  `SUPERSEDED`, `DUPLICATE`.
- **Limitation — deployed env values:** per the standing secrets-hygiene rule
  (never dump the Railway variable set with values into a session), effective
  env values (`CONDOR_EV_MODEL`, `MIN_EDGE_AFTER_COSTS`, `MULTI_STRATEGY_EVAL`,
  tail constants, …) were **not read** this session. Where a deployed value
  matters it is labeled `NOT-PROVEN` with the code default cited
  `VERIFIED-CODE`, and a read-back falsifier is listed in §14. Deployed
  *behavior* was grounded instead through DB rows the running code produced.
- Hypothesis packet H1–H18 was treated as untrusted claims; every disposition
  below was re-traced at the audit SHA.

## 4. Current account census (broker-grounded; identifiers redacted)

Source: Alpaca **live** account read (read-only MCP), 2026-07-16 ≈19:57:30Z.
Basis: broker-reported dollar values, account-total, unsigned.

| Field | Value |
|---|---|
| equity | $2,067.86 |
| last_equity | $2,067.86 |
| cash | $2,067.86 |
| options_buying_power | $2,067.86 |
| portfolio_value | $2,067.86 |
| position_market_value | $0 |
| open positions | 0 (empty list) |
| open orders | 0 (empty list) |
| options_approved_level | 3 |
| options_trading_level (effective) | 3 |
| trading_blocked / account_blocked | false / false |
| balance_asof | 2026-07-15 |

- **Cash↔OBP gap: none** — cash == OBP == equity; no unsettled-funds gap at
  observation time (book flat, no recent T+1 residue).
- The prior audit's `$2,067.86` was **independently re-read** and happens to be
  numerically identical (flat book since; the value is a fresh 2026-07-16
  observation, not a reuse).
- **Code-derived tier:** `small` — `SmallAccountCompounder.get_tier` half-open
  boundaries `[1000, 5000)` (`small_account_compounder.py:24-57`);
  $2,067.86 ∈ small. `VERIFIED-CODE` + `VERIFIED-RUNTIME` (broker value).
- Max concurrent positions (small): 4 (`small_account_compounder.py:34-41`,
  `portfolio_allocator.py:60-64`).
- Global envelope by regime at current equity (pre-granularity, §H7 table for
  detail): NORMAL binding per-trade = 36% ceiling ≈ **$744**; SHOCK binding =
  RBE global cap 5% ≈ **$103**.
- `ops_control` (`key='global'`): `entries_paused = false` (updated 2026-07-09
  11:53Z) — entries enabled. `VERIFIED-RUNTIME`.
- Progression phase (DB row of record): `go_live_progression.current_phase =
  'micro_live'` (updated 2026-04-25). `VERIFIED-RUNTIME`.

## 5. Canonical strategy capability manifest

Traced across `strategy_selector.py`, `options_scanner.py`, `strategy_policy.py`,
`strategy_registry.py`, `sizing_engine.py`, `workflow_orchestrator.py`,
`progression_service.py`, `ev_calculator.py`, broker layer
(`alpaca_client.py`/`alpaca_order_handler.py`/`execution_router.py`/staging
`paper_endpoints.py`), lifecycle migration `20260507000000`, metadata/backtest
endpoints (`strategy_endpoints.py`), and `apps/web` surfaces — never a single
registry. Broker minimum level per Alpaca's documented mapping (L1 covered
call/CSP · L2 +long call/put · L3 +spreads; docs.alpaca.markets/docs/options-trading,
fetched 2026-07-16). The live-reachable chain requires: selector → builder →
honest quotes → EV → sizing → persistence → stage gates (#1038/#1101) → broker
request → live route.

| Canonical strategy | Aliases seen | Selector-emittable | Scanner builder | EV/PoP model | Sizing | Lifecycle row | Ban support | Min broker level | Live-executor reachable | Exit support | UI advertised | Backtest-only | **Verdict** |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| LONG_CALL_DEBIT_SPREAD (2-leg vertical) | `debit_call_spread`, `debit_spread`, misclassified `LONG_CALL` by loss-minimizer | Yes (`strategy_selector.py:143,289`) | Yes (2-leg, `options_scanner.py:3531,3545`) | Debit breakeven-interpolation PoP (#1051, `ev_calculator.py:92-108`) | allocator→compounder→RBE clamp→`sizing_engine` | `live_full` (DB) | Policy heuristic (inert, empty bans) | 3 | **Yes** — 5 executed suggestions/30d, 3 broker-live closes | Yes | Registry mismatch (DRIFT-1: metadata lookup fails) | No | **LIVE-REACHABLE** |
| LONG_PUT_DEBIT_SPREAD | `debit_put_spread`, `debit_spread`, misclassified `LONG_PUT` | Yes (`:172,324`) | Yes | Same | Same | `live_full` | Same | 3 | Yes — 1 broker-live close; last suggestion 2026-06-10 | Yes | Same mismatch | No | **LIVE-REACHABLE** |
| SHORT_PUT_CREDIT_SPREAD | `credit_put_spread`, `credit_spread` | Yes (bullish+high-vol, `:151,283`) | Yes | **Credit identity PoP → raw EV ≡ $0** (`ev_calculator.py:66-80,258-282`) | Same | `live_full` | Yes (credit-category ban would catch) | 3 | Chain intact, **economically un-passable**: EV≡0 can never clear the $15 edge gate or roundtrip gate; **0 suggestions all-time** (DB) | Yes | Compose mock offers lowercase form | No | **LIVE-REACHABLE-BUT-GATED** (defect-suppressed; owned by ⑤) |
| SHORT_CALL_CREDIT_SPREAD | `credit_call_spread` | Yes (bearish+high-vol, `:180,318`) | Yes | Same identity | Same | `live_full` | Yes | 3 | Same — 0 suggestions all-time | Yes | No | No | **LIVE-REACHABLE-BUT-GATED** (⑤) |
| IRON_CONDOR (4-leg) | `iron_condor`, stray `condor` | Yes (NEUTRAL/CHOP/EARNINGS+high-vol, `:350-370`); **phase-excluded only in `alpaca_paper`** (`:372-378`); current phase `micro_live` → allowed | Yes (`_select_best_iron_condor_ev_aware`) | `calculate_condor_ev` (strict, delta-based) / `_tail` selected by `CONDOR_EV_MODEL` env (code default `strict`, `options_scanner.py:214`) | Same (close-BP 2×, `sizing_engine.py:34-70`) | `live_full` | Yes (credit category) | 3 | **Yes** — 3 executed/30d, 4 broker-live closes | Yes (IC stop-loss bypass keyed on name; `condor` alias would miss it) | Yes | No | **LIVE-REACHABLE** |
| HOLD / CASH (no-trade) | empty candidate list in `get_candidates` | Yes (`determine_strategy` only) | n/a | n/a | n/a | n/a | terminal HOLD on banned-no-fallback | n/a | n/a (never staged) | n/a | No | No | designed no-trade states |
| long_call / long_put (single-leg) | `LONG CALL` (agent), registry keys | **No** — no selector pool entry emits a 1-leg candidate | Mapping exists (`_map_single_leg_strategy`, `options_scanner.py:2034-2048`) but **no producer**; scanner primitive returns raw `inf` max-profit (`:2070`) | PoP=|Δ| + `UNBOUNDED_GAIN_CAP_MULT=10` EV cap (`ev_calculator.py:120-126,228-240`) | leg-count agnostic | **No row** (would default `live_full` — H11) | Allowed (not credit) | 2 | Broker path supports 1-leg (`alpaca_client.py:377,401-403`); unreachable upstream | Yes (`close_math._synthesize_single_leg`) | Registry + metadata endpoint advertise | No | **CODE-SUPPORTED-NOT-SELECTOR-REACHABLE** |
| vertical_call / vertical_put | registry only | No | No | n/a | n/a | No row | n/a | 3 | No | n/a | Metadata endpoint | No | **UI-MOCK/DEAD-SURFACE** (registry-only identifiers) |
| covered_call | Compose dropdown only | No | **Zero backend hits** in any `.py` | None | None | No row | **Bypasses credit-category ban heuristic** (no `credit` token) | 1 | No | No | **Compose mock only** (`compose/page.tsx:79`) | No | **UI-MOCK/DEAD-SURFACE** |
| naked_call / naked_put | `short_call`/`short_put` | No | No builder; PoP branch exists; `calculate_ev` **not implemented** | None | None (naked margin "underivable", `utilization_gate.py:201,254`) | No row | `naked_put`/`naked_call` **not in CREDIT_STRATEGIES ban list** | >3 (not offered by Alpaca ≤L3) | No producer; **but `/paper/order/stage` leg validation would accept 1-leg naked** (`paper_endpoints.py:91-99`) | qty-fallback | No | No | **UNSUPPORTED / latent manual seam** |
| straddle / strangle | `short_strangle` in ban list | No | No | `strangle` in `calculate_ev` type signature but raises `NotImplementedError` (`ev_calculator.py:189,273`) | No | No row | strangle banned as credit | 3 | No | n/a | No | No | **DESIGNED-NOT-ACTIVE (half-wired, crashes if called)** |
| debit butterfly | — | No | No (all `butterfly` hits are IV no-arb checks) | payoff explicitly untouched (`payoff_bounds.py:54`) | No | No row | n/a | 3 | No | No | No | No | **UNSUPPORTED** |
| calendar / diagonal | risk-cap key `calendar` exists with no producer (`risk_budget_engine.py:275`) | No | No | No (calendar asserted "not representable" in position model tests) | cap key only | No row | n/a | 3 | No | No | No | No | **UNSUPPORTED** |
| cash-secured put | — | No | No (0 repo hits) | No | No | No row | ban heuristic would miss | 1 | No | No | No | No | **UNSUPPORTED** |
| 0DTE variants | — | No (DTE window excludes; §8) | No | No | No | No row | n/a | 3 | No | expiry-day close support generic | No | No | **UNSUPPORTED** (no 0DTE-specific lifecycle) |
| `take_profit_limit` (exit order class) | — | n/a (exit) | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | Historical pollutant of `trade_suggestions.strategy` (12 rows, 2025-12-11→2026-04-08) — H18 collision evidence |

Manifest evidence labels: code columns `VERIFIED-CODE` at `b95d3a3`; "reachable"
column `VERIFIED-RUNTIME` where DB counts are cited; broker-level column from
Alpaca docs (external, dated). Green tests exist for several helpers but the
production selector path `get_candidates` and the phase gate have **zero test
coverage** (`VERIFIED-TEST-REACH` gap; grep of `packages/quantum/tests`).

## 6. H1–H18 disposition table

Columns: ID · hypothesis (compressed) · current seam · code evidence · test reach ·
runtime evidence · disposition · backlog interaction · priority · acceptance
criteria · falsifier. All code cites at `b95d3a3`.

| ID | Hypothesis | Current seam | Code evidence | Test reach | Runtime evidence | Disposition | Backlog interaction | Priority | Acceptance criteria | Falsifier |
|---|---|---|---|---|---|---|---|---|---|---|
| **H1** | Selector emits only the 5 structures + no-trade | `strategy_selector.py` `get_candidates` (production, via `MULTI_STRATEGY_EVAL` default "1", `options_scanner.py:92,3107`) + legacy `determine_strategy:3124` | Pool exactly {LONG_CALL_DEBIT_SPREAD, LONG_PUT_DEBIT_SPREAD, SHORT_PUT_CREDIT_SPREAD, SHORT_CALL_CREDIT_SPREAD, IRON_CONDOR}; no-trade = `[]` in `get_candidates`, `HOLD`/`CASH` in `determine_strategy` (`strategy_selector.py:143-370`). Injection paths: `/paper/order/stage` accepts arbitrary `strategy_type`+legs incl. `naked_*` (leg-count check only, `paper_endpoints.py:91-141`), UI-orphaned; design-agent override dead as wired (`runner.py:29,71-73`) | `determine_strategy` pinned (`test_strategy_policy.py`); **`get_candidates`: zero tests**; phase gate: zero tests | 30d suggestions contain only IRON_CONDOR + LONG_CALL_DEBIT_SPREAD; all-time adds LONG_PUT_DEBIT_SPREAD + legacy `take_profit_limit` rows; credit spreads 0 all-time | **CONFIRMED-NEW** (pool verified; riders: untested production selector path; manual arbitrary-ticket seam) | test gap → F-SELECTOR-ROUTE-TESTS (new P2); manual seam → F-UI-CAPABILITY-HONESTY (new P2) | P2 | Executing route test drives `scan_for_opportunities`→`get_candidates` and asserts the emitted set; stage seam rejects out-of-set strategy identifiers for OPEN orders | A suggestion row whose `strategy` ∉ pool ∪ {take_profit_limit} appears via the scheduled route |
| **H2** | Surfaces advertise strategies the live path can't produce | `strategy_registry.py:1-58` → `GET /strategies/metadata` (`strategy_endpoints.py:322-324`); backtest configs (`strategy_endpoints.py:326-568`); Compose mock | Registry has 9 keys; live selector produces 5; `long_call`/`long_put`/`vertical_call`/`vertical_put`/`covered_call` have no live producer; registry consumed by nothing on the live path (2 importers total) | UI hooks only | Registry keys never match persisted strategy strings (metadata lookup returns null for real positions) | **CONFIRMED-NEW** | folds into F-UI-CAPABILITY-HONESTY + F-STRAT-ID-CONSUMERS | P2 | Every advertised executable strategy maps to a real producer or is labeled backtest/metadata-only | A live-path consumer of `STRATEGY_REGISTRY` metadata appears |
| **H3** | Debit verticals are the strongest current core structures | scanner debit path + sizing + exits | Bounded max loss (width−credit basis via canonical position #1204/#1214); close-BP 2.1× max-loss vs condor ~3× (`sizing_engine.py:34-70,191-199`); honest #1051 PoP; 2-leg fees lowest of reachable multi-leg | helper-level | Broker-live closes: LCDS 0W/3L −$83; LPDS 1W/1 +$48; IC 0W/4L −$143 (position-total realized USD, broker basis) — **n too small to rank** | **PARTIAL** — structurally suitable (defined-risk, cheapest reachable structure, honest PoP); superiority claim **not evidence-rankable at n=8**; credit comparison impossible until ⑤ | none (no filing; evidence note) | — | Ranking claim requires ⑤ + ≥10–15 live closes/strategy | Post-⑤ prequential comparison contradicts the structural read |
| **H4** | Credit-spread EV ≡ 0 identity | `ev_calculator.py:66-80` (PoP `max_loss/(max_gain+max_loss)` = 1−credit/width), `:258-282` (EV) | Identity algebraically exact; **numerically verified ≡ $0 across 6 (credit,width) pairs by importing the real module**; calibration is pure multiplier `adj_ev = ev×mult` clamped [0.5,1.5] (`calibration_service.py:519-527,691`) — 0×mult=0; can never clear $15 ranker gate (`canonical_ranker.py:136`) or #1101 stage gate | pinned by #1223 PoP suite (helper-level) | **0 credit-vertical suggestions all-time** (trade_suggestions census) | **CONFIRMED-ALREADY-OWNED** — backlog ⑤ names the identity as owned root cause ("Credit EV ≡ $0, payoff-circular; E12"; `docs/backlog.md:596-598,627-629,691-711`) | evidence strengthens ⑤; **no new filing** | (⑤ is P1 #2) | ⑤'s own: a credit vertical carries a nonzero honest EV through the gates | An independent probability source overriding the identity pre-ranking (none exists today — verified) |
| **H5** | Condor cross-structure comparability defect | `options_scanner.py:214-216,1808-1830`; `ev_calculator.py:568-734` | `CONDOR_EV_MODEL` env selects strict (delta-based, code default) vs tail; strict≠identity (semi-independent delta probability); 4-leg fees 8 leg-contracts ≈$5.20 RT vs verticals 2×; close-BP 2× (`sizing_engine.py:66`); ranking mixes identity-EV verticals with delta-EV condors | numeric spot-check (this audit) | Deployed `CONDOR_EV_MODEL` value **NOT-PROVEN** (env not read — secrets hygiene); backlog `:701-703` claims "tail deployed" with constants 0.6/0.35 matching **no code default** (code: mult 1.00, severity 0.50) | **CONFIRMED-EXTENDS-EXISTING** (⑤/A6-3 own mis-rank; multi-basis cost phase 2 owns fee/cost basis) + **NOT-PROVEN** deployed-model sub-claim | strengthens ⑤ + multi-basis phase 2; adds pending verification (ledger): reconcile backlog's "tail deployed" vs code default `strict` | with ⑤ | One terminal distribution feeds both payoff integrations (existing ⑤ criterion) | Operator env read-back of `CONDOR_EV_MODEL` + tail constants on both workers |
| **H6** | Prior census put account in `small`, not `micro` | `small_account_compounder.py:24-57` | Boundaries half-open: micro [0,1000), small [1000,5000), standard [5000,∞) | boundary tests exist but pin legacy path values | Broker re-read 2026-07-16 ≈19:57:30Z: equity=cash=OBP=$2,067.86, flat, 0 open orders → **small** tier; max_trades 4; NORMAL binding/trade ≈$744 (36%), SHOCK ≈$103 (5% RBE cap); no cash↔OBP gap | **CONFIRMED-NEW** (census verification) | none | — | — | Broker equity crossing $1,000 or $5,000 changes tier |
| **H7** | $1,000 cliff can raise per-trade risk to 90% | `small_account_compounder.py:25-33` (micro base_risk 0.90, "operator design intent"), `risk_budget_engine.py:465,526` (micro bypasses `global_caps_map`), `portfolio_allocator.py:60-64` (small 36% ceiling) | Crossing **down** $1,000→$999.99: NORMAL $360→$900 (+150%); **SHOCK $50→$450 (9×)** because micro bypasses the 5% shock cap; table in §H7-table below; no commit ever smoothed the micro↔small step (`91c49dc` created it; `15279fd` smoothed a different $50-floor cliff) | `test_small_account_compounder_micro_90pct.py` pins boundary but **encodes the legacy $38.88 number, not production ~$360**; orchestrator wiring pinned by source-string tests only | Live equity $2,067.86 — one drawdown of ~52% away from the boundary | **CONFIRMED-NEW** — classified **intentional operator doctrine** (in-code comment + `docs/small_tier_allocation.md` §6 + `docs/risk_math.md:29-33` + CLAUDE.md "hard $1k/$5k cliffs") **with an unreconciled risk-direction discontinuity** never flagged in any doc, sharpest under SHOCK | new RESEARCH owner-review item F-TIER-CLIFF-REVIEW; test-truth acceptance criterion (boundary tests must pin the production allocator path) | RESEARCH (owner) | Owner decision recorded: keep 90% micro doctrine as-is, taper it, or gate it under SHOCK; boundary tests re-pinned to production-route numbers | A production sizing run at equity <$1,000 emitting a 90%×regime budget (would confirm live behavior exactly as modeled) |
| **H8** | Absolute $15 MIN_EDGE_AFTER_COSTS materially binding at ~$2k | `canonical_ranker.py:24,100-142` (default $15, dollars/structure, on **calibrated** EV − fees(0.65×contracts×legs×2) − slippage(TCM or 5%-of-EV floor)); #1101 stage gate `paper_endpoints.py:1246-1400` (same $15 floor, **executable bid/ask cross** basis) | Two $15 floors on two different cost bases (proxy vs executable) at two funnel points; scanner-time raw-EV execution-cost gate is a third basis (`options_scanner.py:3799-3839`) | helper-level only (`test_multileg_ranking_cost_basis.py`, `test_entry_roundtrip_cost_gate.py`); wiring at `paper_endpoints.py:1350` untested end-to-end | 14d rejections: `execution_cost_exceeds_ev` 744, `ev_non_positive` 5; 30d: 10 `NOT_EXECUTABLE` LCDS suggestions; binding gate is cost-vs-EV, not EV sign | **CONFIRMED-EXTENDS-EXISTING** — materially binding **by design** (learning-mode doctrine: low frequency is a feature); the mixed-basis inconsistency belongs to multi-basis cost phase 2 | strengthens multi-basis cost phase 2 (no new filing; no threshold change recommended) | with phase 2 | One executable cost model across scanner/ranker/gate (existing phase-2 criterion); any tier-aware alternative = RESEARCH observe-only first | Deployed `MIN_EDGE_AFTER_COSTS` env read-back (NOT-PROVEN this session; default $15 assumed from code) |
| **H9** | Wrapper exposes OBP but not options approval/effective levels | `alpaca_client.py:221-267` `get_account()` curated 12-key dict; `equity_state.py:440-501` | **Confirmed**: `options_approved_level`/`options_trading_level` never read anywhere (repo-wide grep: 1 hit, a log string `cash_service.py:119`); no strategy→min-level preflight; `_TERMINAL_REJECT_MARKERS` (`alpaca_order_handler.py:56-61`) has **no permission bucket** → level reject = 3 retries + `needs_manual_review` critical | none | Broker API itself returns both fields (live read: approved 3, effective 3) — the data exists one dict-key away | **CONFIRMED-NEW** | **new P2** F-OPTIONS-LEVEL-PREFLIGHT (no existing owner — backlog/ledger grepped) | P2 | Wrapper serializes both levels distinctly; entry staging preflights strategy→min-level **fail-closed** (missing field → reject entries, never exits); permission-shaped broker rejects classified terminal | A broker order rejected for insufficient options level being retried as transient (reproduces the gap) |
| **H10** | Phase excludes strategies (IC in `alpaca_paper`) | `strategy_selector.py:372-387` (env `CURRENT_PROGRESSION_PHASE`); bridge `workflow_orchestrator.py:2352-2354` from `go_live_progression` (`progression_service.py:481-507`) | Only IC, only `alpaca_paper`, enforced in selector only; **fail-closed** (all fallbacks → `alpaca_paper` → IC excluded); latent stale-env seam on the `None` branch (`setdefault`, `:2354`); legacy `determine_strategy` ungated | zero tests on phase gate | `current_phase='micro_live'` (DB, since 2026-04-25) → IC live; matches 30 IC suggestions/30d. **Observability gap**: phase-excluded IC lands in the same unattributed `strategy_hold_no_candidates` bucket as "no economic candidate" (`options_scanner.py:3115-3120`); INFO-only distinction | **CONFIRMED-EXTENDS-EXISTING** (exclusion verified; fail-safe direction correct; observability gap extends funnel telemetry phase 2) | phase-excluded typed rejection + `strategy_key` attribution → extends funnel telemetry phase 2 | with phase 2 | `suggestion_rejections` distinguishes `strategy_phase_excluded` from `strategy_hold_no_candidates`, with strategy attribution | A phase flip to `alpaca_paper` producing zero distinguishable rejection rows |
| **H11** | Missing/invalid lifecycle data defaults to `live_full` | loader `progression_service.py:190-224`; consumers `options_scanner.py:3909-3926`, `sizing_engine.py:211-234` | **Confirmed fail-open by documented design** (comments `progression_service.py:200-203`): table missing/query throws/empty → `{}`; missing row → `live_full` (`options_scanner.py:3918-3920`); malformed state → not filtered AND not capped (fails open to full size); migration `20260507000000` exists, self-verifies, seeds 5 `live_full`; exits lifecycle-independent (repo-wide grep) | mocked-loader units + **source-string wiring tests** (`test_lifecycle_sizing_cap.py:175-229`) — no executing route test; `test_live_position_state_failclosed.py` does **not exist** at this SHA (it lives on unmerged PR #1231) | DB: exactly 5 rows, all `live_full` (2026-05-07) → gate currently **inert** | **CONFIRMED-NEW** (premise narrowed: migration exists; the fail-open is loader/consumer behavior, intentional) | **new P2 (trigger-gated)** F-LIFECYCLE-TYPED-DEGRADE — safety-relevant only when a reachable strategy is ever non-`live_full` | P2, hard trigger: before any strategy enters `experimental`/`designed` | Typed loader failure distinguishes empty-table from failed-read; unknown/malformed state fails **closed for entries** (cap or exclude), exits untouched; route-driving test injects the query throw at origin, asserts no full-size entry | A DB blip during a cycle with an `experimental` strategy row producing a full-size entry |
| **H12** | `settings.banned_strategies` unmigrated; read degrades to empty | reader `workflow_orchestrator.py:2549-2563`; enforcement `strategy_policy.py:36-54`, `strategy_selector.py:38,265`, `options_scanner.py:3168-3170` | **No migration anywhere defines the column** (grep of `supabase/migrations/**`: zero SQL hits; `settings` created with 6 columns in `20240101000000_initial_schema.sql:97-104`, never altered); reader swallows failure at `logger.debug` → `[]`; **zero write surface** (no UI/API/migration writes it); enforcement machinery real and live-routed but permanently fed `[]` | fixtures only | Production column **exists** (ARRAY) = **untracked schema drift**; `settings` has **0 rows**; ban never active in any environment | **CONFIRMED-NEW** (phantom feature + drift) | **new P2** F-BAN-INTEGRITY; drift aspect also strengthens the existing migration-drift/name-normalized-allowlist P2 item | P2 | Owner decision: build (migration + write surface + typed loud read failure + route test proving a persisted ban blocks and a read failure never silently authorizes) **or remove** the dead read+enforcement; either outcome typed and observable | A persisted ban row failing to block a banned strategy on the scheduled route |
| **H13** | Scanner DTE prevents 0DTE (25–45 enforced) | `options_scanner.py:98-99,2905-2906,3186,3199` | `SCANNER_MIN_DTE=25`/`SCANNER_MAX_DTE=45` module constants (no env override), enforced at chain-fetch (out-of-band expiries never enter the candidate set); target 35 uniform across strategies; `midday_scan.py` handler calls the SAME cycle (no separate DTE/cadence; not in `scheduler.py` SCHEDULES); one scan/day 11:00 CT + one executor pass 11:30 | n/a | no sub-25-DTE suggestion rows observed | **CONFIRMED-NEW** (verification; 0DTE correctly impossible today) | none — 0DTE stays out of backlog (no same-day lifecycle/market-calendar contract exists; see H16) | — | — | A suggestion with entry DTE <25 via the scheduled route |
| **H14** | Single-leg longs partially supported, not selector-reachable | every seam traced (§5 manifest row) | Supported end-to-end **except candidate generation**: registry, PoP=Δ, EV+`UNBOUNDED_GAIN_CAP_MULT=10`, mapping, sizing, staging leg-count, broker 1-leg path, close math. Missing: one pool entry emitting a 1-element legs list. Repair-first defects: scanner primitive `max_profit=float("inf")` (`options_scanner.py:2070,2138`) and naked-collateral "crude placeholder" (`:2077-2078`) | `test_single_leg_strategy_mapping.py` (helper) | Broker requires level 2 (account has 3) | **CONFIRMED-NEW** | **RESEARCH (owner-gated)** F-SINGLE-LEG-EXPERIMENTAL — behind F-OPTIONS-LEVEL-PREFLIGHT + F-LIFECYCLE-TYPED-DEGRADE + the `inf` primitive fix; would use the existing `experimental` 1-contract lifecycle cap | RESEARCH | Selector pool entry behind an `experimental` lifecycle row; `inf` primitive reconciled with the EV cap; route test drives scan→stage for a 1-leg candidate | — |
| **H15** | Debit butterfly lacks a complete route | repo-wide sweep | **No builder, no payoff model (explicitly untouched, `payoff_bounds.py:54`), no sizing, no exit, no backtest**; all `butterfly` hits are IV-surface no-arb checks | n/a | none | **CONFIRMED-NEW** (absence) | none — stays RESEARCH-only by rule; does not outrank integrity repairs | RESEARCH | — | — |
| **H16** | Defer list adjudication | see §7 note | 0DTE: DEFER-ARCHITECTURE (no same-day lifecycle; H13) · CSP: DEFER-ARCHITECTURE (+level-1 OK but zero code, collateral model absent) · covered call: DEFER-CAPITAL + DEFER-ARCHITECTURE (needs 100 shares; zero backend) · calendar/diagonal: DEFER-ARCHITECTURE (cap key exists with no producer — dead entry) · naked shorts: **PROHIBIT-UNDEFINED-RISK** (also margin "underivable", `utilization_gate.py:201,254`; not offered ≤L3 anyway) · straddle/strangle: DEFER-ARCHITECTURE (`calculate_ev` raises `NotImplementedError`, `ev_calculator.py:273`) | n/a | none | **CONFIRMED-NEW** (verdicts recorded) | none filed | — | — | — |
| **H17** | Compose is a mock; paper page manages-only | `apps/web/app/(protected)/compose/page.tsx`; `paper/page.tsx` | **Confirmed**: `Math.random()>0.3` decision (`compose/page.tsx:20`), fake 1.5s spinner, hardcoded reasons, stale `expiry: '2025-02-21'` (`:28`), **zero network calls**; it is the primary "New Trade" nav CTA (`DashboardLayout.tsx:66-70`); paper page: close/reset/read only, no open-entry; the ONLY UI entry action (TradeInbox Stage) funnels pre-vetted suggestions through the same gated `_stage_order_internal` — **no gate bypass**; `/paper/order/stage`+`/paper/execute` accept arbitrary tickets, UI-orphaned but gated; TradeInbox "no live execution" banner is unenforced copy (routing decided server-side) | none | `GET /validation/self-assessment` also returns a hardcoded placeholder (`validation_endpoints.py:144-177`) | **CONFIRMED-NEW** — operator-facing capability lie (mock validator sold as "AI validation") | **new P2** F-UI-CAPABILITY-HONESTY | P2 | Compose either wired to a real guarded endpoint or clearly labeled mock/removed; `covered_call` option removed; UI-orphaned arbitrary-ticket endpoints either strategy-set-checked at the stage seam or removed; banner copy reflects server truth | A UI action opening a broker-routed position without passing #1038+#1101 (none exists today — verified) |
| **H18** | Identifier drift across modules | 11 naming schemes inventoried | ≥11 schemes; registry matches **zero** persisted strategy strings; `StrategyType` enum lacks debit spreads → **`LossMinimizer` classifies debit spreads as naked longs** (`common_enums.py:13-19`, `loss_minimizer.py:57-67`) — production-wired (`workflow_orchestrator.py:877-896` morning deep-loser path, `:4431-4472` adaptive caps); risk-cap substring match misses `long_call_debit_spread` → falls to 0.05 floor instead of 0.15 (`risk_budget_engine.py:282-293`) — **fail-tight, wrong basis**; sizing close-BP recognizes only uppercase selector names; ban heuristic robust to case but token-dependent; learning buckets keyed on raw strings; exit evaluator safe via qty-fallback except `condor` alias missing the IC stop-bypass; `take_profit_limit` historically pollutes `trade_suggestions.strategy` (12 rows) | helper-level | `suggestion_rejections.strategy_key` **NULL on 5,076/5,076 rows (14d)** — per-strategy rejection attribution nonexistent | **CONFIRMED-NEW** | **new P2** F-STRAT-ID-CONSUMERS (narrow slice: the two behavior-relevant consumers + a collision test) — **EXTENDS canonical-position remainder** (typed structure model is the systemic fix); attribution gap extends funnel telemetry phase 2 | P2 | LossMinimizer + risk-cap keys resolve the selector's actual identifiers (or consume the canonical position model); a crosswalk test pins every producer identifier to exactly one canonical strategy; no new full-rewrite proposed | A morning-cycle loss analysis of a debit spread using a naked-long payoff (reproducible once a losing debit position exists) |

### H7 capital table (max theoretical per-trade budget BEFORE contract granularity)

Method: exact production chain (allocator→compounder→RBE `remaining_global` clamp),
single best candidate, zero open positions, formulas from
`small_account_compounder.py:154-214`, `portfolio_allocator.py:275-322`,
`risk_budget_engine.py:423-468,526`; verified by standalone arithmetic replication
(no config mutated, no trade executed). Basis: account-equity USD, per-trade
budget (risk dollars), pre-fees.

| Equity | Tier | NORMAL binding constraint | NORMAL $ | SHOCK binding constraint | SHOCK $ |
|---|---|---|---|---|---|
| $900 | micro | 0.90×equity×1.0 | **$810.00** | 0.90×equity×0.5 | **$405.00** |
| $999.99 | micro | same | **$899.99** | same | **$450.00** |
| $1,000.00 | small | 36% ceiling (RBE 40% cap above it) | **$360.00** | **RBE 5% global cap** | **$50.00** |
| $1,001 | small | 36% | **$360.36** | 5% | **$50.05** |
| $2,000 | small | 36% | **$720.00** | 5% | **$100.00** |
| $5,000 | standard | 2%×score_mult(1.12) | **$112.00** ($120 @score-100) | ×0.5 | **$56.00** ($60) |

Discontinuities: micro→small crossing **down** raises the budget 2.5× (NORMAL) /
9× (SHOCK); small→standard at $5,000 **drops** the budget ~6× (720→112) — a second,
downward cliff. Note the per-cohort `sizing_engine` risk-% track caps
(balanced 2% / aggressive 5%, `sizing_engine.py:151-158`) apply downstream of
these budgets and can bind tighter at contract conversion; the table is the
budget layer only.

## 7. Account-fit matrix (current $2,067.86 flat small-tier account)

Basis notes: max-loss = defined-risk structure basis (width−credit / debit paid),
per-structure-contract USD; RT BP = `collateral + estimate_close_bp×1.1`
(`sizing_engine.py:191-199`); fees = $0.65/contract-leg ×2 (round trip); live
evidence = broker-live closes only (post-epoch == all-time here, n=8 total).

| Strategy | Direction/vol use | Max-loss basis | Collateral/BP | Est RT BP | Legs | Fee basis (1-lot) | Assignment exposure | DTE | Monitor/exit | Gate state | Live n | **Fit** | Confidence | Reason |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| LONG_CALL_DEBIT_SPREAD | bullish, low/normal IV | debit paid | max_loss×2.1 | ~2.1× max loss | 2 | ≈$2.60 | short leg assignable if ITM near expiry (system has no assignment handler — existing F-A10-1 item) | 25–45 | full (#1048/#1034/#1079) | open | 3 (0W, −$83) | **CORE-CANDIDATE** | med | Cheapest reachable defined-risk structure; honest PoP; costs still eat ~15%+ of typical EV at this size |
| LONG_PUT_DEBIT_SPREAD | bearish, low/normal IV | debit paid | same | same | 2 | ≈$2.60 | same | 25–45 | full | open | 1 (1W, +$48) | **CORE-CANDIDATE** | med | Symmetric case |
| SHORT_PUT_CREDIT_SPREAD | bullish, high IV | width−credit | credit-structure basis | ~1.0–2.1× | 2 | ≈$2.60 | short-leg early assignment | 25–45 | full | open but **EV≡0** | 0 ever | **BLOCKED-BY-DEFECT** | high | ⑤'s identity: raw EV≡$0 can never clear either $15 floor |
| SHORT_CALL_CREDIT_SPREAD | bearish, high IV | width−credit | same | same | 2 | ≈$2.60 | same + upside gap risk within width | 25–45 | full | open but EV≡0 | 0 ever | **BLOCKED-BY-DEFECT** | high | same |
| IRON_CONDOR | neutral/chop, high IV | max(side width)−credit | close-BP 2× | ~3× max loss | 4 | ≈$5.20 | two short legs | 25–45 | full (IC stop-bypass keyed on exact name) | open (phase `micro_live`) | 4 (0W, −$143) | **CONDITIONAL** | med | Reachable and selected in chop, but: 4-leg costs, ~3× BP demand at $2k, EV model-dependent (⑤/A6-3), 0/4 live record (n too small to conclude) |
| long_call / long_put (1-leg) | directional, low IV | full premium | premium | ~1× premium | 1 | ≈$1.30 | none (long) | 25–45 (would inherit) | supported | **not selector-reachable** | 0 | **EXPERIMENTAL-ONLY** | med | Complete downstream support; blocked at pool; repairs first (`inf` primitive, level preflight); level 2 satisfied |
| butterfly/calendar/diagonal/straddle/strangle/CSP/covered call/naked/0DTE | — | — | — | — | — | — | — | — | — | absent | 0 | **DEFER** (naked: **PROHIBIT-UNDEFINED-RISK**) | high | No production route (H15/H16); do not outrank integrity repairs |

## 8. Entry-funnel / gating matrix (condensed; full seams cited)

Order = production execution order. FO/FC = fail-open/fail-closed on error.
"Durable" = persisted rejection trace; "n/14d" = suggestion_rejections counts
2026-07-02→16 where measured. Owner = code default unless stated; deployed env
values not read (NOT-PROVEN; §3).

| # | Gate | Seam | Basis | FO/FC | Durable reason | n/14d | Setting (code default) | Kill switch | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Live-position read | `workflow_orchestrator.py:2319-2330` | live book read | FC (raises `LivePositionStateUnavailable`) | job_runs | — | — | — | correct (post-#1215 family); sibling FAILOPEN item already owned (F-MIDDAY-POSITION-READ-FAILOPEN) |
| 2 | Micro-tier concurrency | `:2364-2406` | tier + open count | skip | cycle result `micro_tier_position_open` | 0 | tier-derived | — | designed |
| 3 | Capital-scan policy | `capital_scan_policy.py:18-43` | deployable vs tier floor ($15/$35/$100) | block | cycle result | — | hardcoded | — | designed |
| 4 | Global risk budget | `:2474-2543` | RBE remaining ≤0 | skip | trade_veto log | — | regime map | `MIDDAY_TEST_MODE` | designed |
| 5 | Universe/scan limit | `options_scanner.py:2759-2798` | scanner_universe (78 active) | **FO** (8-symbol hardcode fallback) | counts | — | `UNIVERSE_SCAN_LIMIT`=100 | — | FO fallback noted |
| 6 | Tier price pre-filter | `:2504,2896` | underlying vs $50 (micro only) | records | `micro_tier_underlying_too_high` | 168 (all cycle 07-06 — the resolved OBP-int(None) incident; 0 since) | `MICRO_TIER_MAX_UNDERLYING`=50 | — | resolved-incident memory |
| 7 | Quote present | `:2962-2964` | underlying quote | reject | `missing_quotes` | — | — | — | H9-honest |
| 8 | History ≥50 bars | `:3043-3045` | daily closes | reject | `insufficient_history` | 29 | — | — | designed |
| 9 | Real IV rank | `:3079-3085` | iv_rank None → reject (no 50.0 fabrication) | FC | `iv_rank_insufficient_history` | 302 | — | — | H9-honest |
| 10 | Regime/sentiment selector | `:3115-3165` | `get_candidates` | empty pool | `strategy_hold_no_candidates` (unattributed; conflates phase exclusion — H10) | 327 + 1,501 `no_fallback_strategies_available` + 622 `all_strategies_rejected` | `MULTI_STRATEGY_EVAL`=1 | =0 → ungated legacy path | observability gap → funnel phase 2 |
| 11 | User bans | `:3168-3170` | settings (always `[]` — H12) | inert | `strategy_banned` | 0 ever | — | — | phantom feature |
| 12 | Chain present | `:3216-3219` | chain fetch | reject | `no_chain` | — | — | — | — |
| 13 | **DTE window 25–45** | `:2905-2906,3227-3244` | chain-fetch bound, target 35 | reject | `dte_out_of_range` | — | module constants | none | designed (H13) |
| 14 | Surface V4 arb | `:3302-3321` | arb-free surface | observe | `surface_*` | — | `SURFACE_V4_ENABLE` off | — | dormant |
| 15 | Greeks completeness | `:3446-3500` | chain deltas | reject + alert | `condor_no_deltas`/`no_deltas_in_chain` | 38+230 (`condor_ev_not_computed`) | — | — | H9-honest |
| 16 | Legs found | `:3504-3506` | leg selection | reject | `legs_not_found` | 2 | — | — | — |
| 17 | Liquidity/spread | `:3680-3739` | spread% vs regime map; price-class 0.30 <$60 (#1047) | reject | `spread_too_wide_real` + `spread_debug` | 867 | `PRICE_CLASS_SPREAD_CUTOFF`=60 | `=0` → tier-only | **top real-market gate** |
| 18 | Execution cost vs raw EV | `:3799-3839` | cost ≥ EV hard reject (NORMAL/CHOP) | reject | `execution_cost_exceeds_ev` | **744** | `EXECUTION_COST_HARD_REJECT`=1 | explicit falsy | **binding economic gate** |
| 19 | Earnings proximity | `:3890-3904` | ≤2d short-premium hard; ≤7d penalty | reject | `earnings_short_premium` | 2 | hardcoded | — | designed |
| 20 | Lifecycle state | `:3918-3926` | `strategy_lifecycle_states` | **FO→live_full** (H11) | `strategy_designed/deprecated` | 0 (all live_full) | table | — | inert; typed-degrade item filed |
| 21 | Agent veto | `:4055-4058` | agent pipeline | veto | `agent_veto` | 0 (`QUANT_AGENTS_ENABLED` default False) | — | — | dormant |
| 22 | Conviction/calibration ordering | `wf:2589-2611,3772-3777` | score multiplier; EV multiplier [0.5,1.5] | FO (log) | — | — | `CALIBRATION_APPLY_AT_SCORING` off; `CALIBRATION_ENABLED` | trio | ordering inconsistency noted (score vs dollar paths) |
| 23 | rank_and_select + allocator | `wf:2667-2871` | score sort; small-tier split ≤4, 36% | drop | counts | — | — | — | selection/sizing math inconsistency (legacy ~3% estimates vs 36% allocator) noted |
| 24 | H7 round-trip BP | `sizing_engine.py:191-208` (pre-filter `wf:2675-2776` shadow) | entry+exit BP ×1.1 | contracts→0 veto | trade_veto | — | `H7_PREFILTER_ENABLED`=false (shadow); real gate in sizing | — | designed |
| 25 | Sizing/granularity + experimental cap | `sizing_engine.py:73-256` | min(risk, collateral, RT, max); experimental→1 | veto | sizing_metadata | 10 `NOT_EXECUTABLE` LCDS/30d (edge gate below) | 2%/5% track caps | — | designed |
| 26 | Marketdata quality | `wf:3598-3751` | snapshot executability | soft→`NOT_EXECUTABLE` | `marketdata_quality_gate` | — | `MIDDAY_QUALITY_GATE_MODE`=soft | — | designed |
| 27 | **MIN_EDGE_AFTER_COSTS** | `canonical_ranker.py:100-142` via `wf:3881-3891` | calibrated EV − fees − slippage < $15 → −999 | `NOT_EXECUTABLE` | `blocked_reason=edge_below_minimum` | (in 30d: 10 rows) | `MIN_EDGE_AFTER_COSTS`=15 | env | H8 |
| 28 | entries_paused breaker | `paper_autopilot_service.py:206-217` | ops_control | **FO (documented deliberate)** | job result | false since 07-09 | #1097/#1119 | DB lever | doctrine |
| 29 | Circuit breaker envelopes | `:247-455` | #1071 de-phantomed basis | FO w/ alert (load-bearing) | alert | — | — | trio | known |
| 30 | Cooldown #1040 | `:920-941,1017-1032` | reentry_cooldowns | filter FO / **stage FC** | `symbol_cooldown` | — | `REENTRY_COOLDOWN_ENABLED` ON | explicit falsy | designed |
| 31 | Same-symbol dedup | `:965-1007` | per-cohort portfolio scope | skip | `symbol_already_held` | — | — | — | scope narrowed by design (BAC incident) |
| 32 | Utilization gate #1044 | `:1039-1046` | pro-forma utilization | **FC** | `entry_utilization_blocked` | — | `RISK_UTILIZATION_GATE_ENABLED` explicit =1 | unset → legacy BLOCK | designed |
| 33 | Bucket control | `:1056-1104` | one-beta bucket | observe | `bucket_exposure_cap` if armed | — | `BUCKET_CONTROL_ENFORCE` off | — | observe window |
| 34 | Leg structural validation | `paper_endpoints.py:641` | leg-count vs strategy | raise | exception | — | — | — | accepts unknown strategies (H1 seam) |
| 35 | **#1038 quote validation** | `:664-672,1103-1140` | per-leg NBBO | FC raise `EntryQuoteUnpriceable` | `entry_quote_unpriceable` | — | `ENTRY_QUOTE_VALIDATION_ENABLED` ON | explicit falsy (⚠ couples to #1101) | designed |
| 36 | **#1101 roundtrip gate** | `:710-713,1246-1400` | gross EV − executable cross < $15 | FC raise | `ev_below_roundtrip_cost` | first live 07-02 | `ENTRY_ROUNDTRIP_COST_GATE_ENABLED` ON; `GATE_QTY_FIX_LIVE_ENABLED` off (live qty>1 on legacy basis — existing E2 observe item) | explicit falsy | designed; E2 rider owned |
| 37 | Broker routing | `execution_router.py:31-137` | `routing_mode='live_eligible'`; `EXECUTION_MODE`+`LIVE_ENABLED` | **FC→shadow** | order row `shadow_blocked` | 4 rows/30d | env | — | designed |
| 38 | Broker submit + reject handling | `alpaca_order_handler.py:349-502` | mleg/single limit; sign guards | retry×3 → `needs_manual_review` critical | order row + alert | 4 cancelled/30d (watchdog) | — | — | **no permission-reject bucket (H9)** |

Practical inaccessibility at ~$2k (designed suppression unless noted): double $15
floors + fees make sub-~$18-EV structures unpassable; condor ~3× BP demand;
2%/5% track caps bind contract counts; credit verticals defect-blocked (⑤). The
executor per-cohort route skips the legacy `min_score`/stage-edge re-checks
(documented in-code, `paper_autopilot_service.py:120-125`) — redundant floors,
not a protection gap: the scanner-side edge gate has already stamped
`NOT_EXECUTABLE` and #1101 still runs inside staging.

## 9. Current strategy distribution and recent outcomes (denominators separated)

All values read 2026-07-16 ≈20:0xZ, Supabase rows of record.

- **Suggestions, 30d** (`trade_suggestions`, created ≥2026-06-16): IRON_CONDOR 30
  (25 dismissed · 3 executed · 2 pending) · LONG_CALL_DEBIT_SPREAD 29 (14
  dismissed · 5 executed · 10 NOT_EXECUTABLE). No other strategy.
- **Suggestions, all-time**: IRON_CONDOR 112 (first 2026-02-11) ·
  LONG_CALL_DEBIT_SPREAD 85 · LONG_PUT_DEBIT_SPREAD 55 (last 2026-06-10) ·
  `take_profit_limit` 12 (exit order class polluting the column; 2025-12-11→
  2026-04-08) · **credit spreads: 0 ever**.
- **Thesis rows**: 86 all-time (`position_thesis_outcomes`), all within 30d.
- **Staged orders, 30d** (`paper_orders`): `alpaca_live` 12 (8 filled · 4
  watchdog/cancelled) · `internal_paper` 5 filled · `shadow_blocked` 4 filled.
- **Positions closed, 30d** (`paper_positions`): 8 (4 via `alpaca_fill_reconciler`,
  4 via `exit_evaluator`).
- **Broker-live closes** (`learning_trade_outcomes_v3`, `is_paper=false`): **8
  all-time, 8 post-epoch (≥2026-06-11)** — IRON_CONDOR 4 (0 wins, −$143.00) ·
  LONG_CALL_DEBIT_SPREAD 3 (0 wins, −$83.00) · LONG_PUT_DEBIT_SPREAD 1 (1 win,
  +$48.00). Basis: realized P&L, position-total USD, broker-fill basis.
- **Paper/shadow closes**: 94 all-time, 8 post-epoch. Never combined with live
  counts anywhere in this report.
- Context only (no action): 8 post-epoch live closes = the #1051 raw-mode exit
  threshold; calibration left raw mode 07-10 (ledger-settled).

## 10. Retained findings, ranked (safety · value · effort)

All are latent today (book flat, entries enabled, no non-`live_full` lifecycle
rows). None changes the "Actual next priorities" ordering; all land at P2 or
RESEARCH beneath the standing safety lane (F-MIDDAY-POSITION-READ-FAILOPEN,
A6-2) and the P1 queue (①–⑦).

1. **F-STRAT-ID-CONSUMERS** (P2, extends canonical-position remainder) — the two
   behavior-relevant identifier-drift consumers: `LossMinimizer` classifies
   debit spreads as naked longs on the production morning deep-loser path
   (`common_enums.py:13-19` + `loss_minimizer.py:57-67`; callers
   `workflow_orchestrator.py:877-896,4431-4472`); `calculate_strategy_cap`
   substring-misses `long_call_debit_spread` → 0.05 floor instead of the
   intended 0.15 (`risk_budget_engine.py:282-293`) — fail-tight, wrong basis.
   Plus one crosswalk test pinning every producer identifier to one canonical
   strategy. No full-rewrite proposed.
2. **F-BAN-INTEGRITY** (P2, new; drift facet strengthens the existing
   migration-drift allowlist item) — `settings.banned_strategies` is a phantom
   feature: no migration defines it, production column is untracked drift with
   0 rows, the sole reader degrades to `[]` at `logger.debug`
   (`workflow_orchestrator.py:2549-2563`), no write surface exists. Build it
   honestly (typed loud read failure + migration + write surface + route test)
   or remove the dead read/enforcement.
3. **F-OPTIONS-LEVEL-PREFLIGHT** (P2, new) — wrapper drops
   `options_approved_level`/`options_trading_level` (`alpaca_client.py:252-267`);
   no strategy→min-level preflight; permission rejects retried as transient
   (`alpaca_order_handler.py:56-61`). Fail-closed entry preflight; exits
   untouched. Latent (account approved=3 covers all shipped structures).
4. **F-LIFECYCLE-TYPED-DEGRADE** (P2, new, hard trigger: before any strategy
   row leaves `live_full`) — lifecycle loader fail-open to `live_full` on read
   failure/missing row/malformed state (`progression_service.py:190-224`,
   `options_scanner.py:3918-3926`, `sizing_engine.py:224`); wiring pinned only
   by source-string tests.
5. **F-UI-CAPABILITY-HONESTY** (P2, new) — the primary "New Trade" CTA is a
   `Math.random()` mock with a 2025 example date (`compose/page.tsx:17-35`);
   `covered_call` advertised nowhere-else; `GET /validation/self-assessment`
   hardcoded; UI-orphaned arbitrary-ticket endpoints (`/paper/order/stage`,
   `/paper/execute`) accept out-of-set (incl. naked) structures at the stage
   seam (gated by #1038/#1101 but not by strategy set/phase/lifecycle).
6. **Phase-exclusion + per-strategy rejection attribution** (extends funnel
   telemetry phase 2) — phase-excluded IRON_CONDOR indistinguishable from
   "no economic candidate" (`options_scanner.py:3115-3120`);
   `suggestion_rejections.strategy_key` NULL on 5,076/5,076 recent rows.
7. **F-TIER-CLIFF-REVIEW** (RESEARCH, owner) — H7: documented-intentional micro
   90% doctrine produces a risk-*raising* discontinuity crossing down through
   $1,000 (2.5× NORMAL, **9× SHOCK** — micro bypasses the 5% shock cap,
   `risk_budget_engine.py:465` vs `:468`), plus a second downward cliff at
   $5,000; boundary tests pin non-production numbers
   (`test_small_account_compounder_micro_90pct.py` → $38.88 legacy vs ~$360
   production).
8. **F-SELECTOR-ROUTE-TESTS** (P2, test-truth) — `get_candidates` (the
   production selector) and the IC phase gate have zero executing tests;
   lifecycle/sizing wiring pinned by source-string assertions (§9-doctrine
   costume class).
9. **F-SINGLE-LEG-EXPERIMENTAL** (RESEARCH, owner-gated, behind 3/4/8 and the
   scanner `inf`-primitive fix) — complete single-leg engine exists; only the
   selector pool entry is missing (H14).
10. **CONDOR_EV_MODEL reconciliation** (pending verification, ledger) — backlog
    claims "tail deployed" with constants matching no code default; deployed
    env value unread this session (secrets hygiene).

## 11. Recommended backlog integrations (exact)

- **Extend ⑤** (evidence only, no text change needed): H4 numeric proof + the
  0-credit-suggestions-all-time census + H5 strict-vs-tail nuance (the vertical
  is the degenerate identity; the condor is mis-modeled, not zero).
- **Extend multi-basis cost phase 2** (evidence only): the three cost bases
  measured at gates 18/27/36 (raw-EV proxy · calibrated-EV ranker ·
  executable-cross stage) are the phase-2 charter in the wild.
- **Extend funnel telemetry phase 2**: add typed `strategy_phase_excluded` and
  `strategy_key` population on rejection rows (finding 6).
- **Extend canonical-position remainder**: F-STRAT-ID-CONSUMERS (finding 1) as
  a named consumer slice.
- **New P2 items**: F-BAN-INTEGRITY, F-OPTIONS-LEVEL-PREFLIGHT,
  F-LIFECYCLE-TYPED-DEGRADE (trigger-gated), F-UI-CAPABILITY-HONESTY,
  F-SELECTOR-ROUTE-TESTS.
- **New RESEARCH items**: F-TIER-CLIFF-REVIEW (owner decision),
  F-SINGLE-LEG-EXPERIMENTAL (owner-gated, behind repairs).
- **"Actual next priorities" ordering: unchanged.** Nothing found outranks the
  standing safety lane or ①–⑦; strategy additions stay behind integrity repairs.

## 12. Rejected / duplicate / superseded / not-proven appendix

- **REJECTED (premise narrowed)**: H11's "missing migration" clause — migration
  `20260507000000` exists and self-verifies; the fail-open is loader behavior.
- **REJECTED**: "UI can bypass entry gates" (H17 worst case) — the only UI entry
  action funnels through `_stage_order_internal` with #1038/#1101 intact.
- **DUPLICATE (not re-filed)**: credit-EV identity (⑤ owns, E12); condor
  mis-rank (A6-3/⑤); qty>1 roundtrip-gate basis (existing E2 observe item);
  min-edge/fee basis inconsistencies (multi-basis phase 2); 07-06
  `micro_tier_underlying_too_high` storm (resolved M4 item 0; all 168 rows on
  the excluded 07-06 cycle); executor-skips-legacy-filters (documented in-code,
  #1126-family ledger memory); `entries_paused` fail-open polarity (#1097
  doctrine); shadow-fill fiction (§8 known-liar + F-SHADOW-CAPITAL-PARITY).
- **NOT-PROVEN**: deployed values of `CONDOR_EV_MODEL`, tail constants,
  `MIN_EDGE_AFTER_COSTS`, `MULTI_STRATEGY_EVAL`, `EXECUTION_MODE`/`LIVE_ENABLED`
  (env not read by policy); runtime behavior of any unmerged PR (#1231's
  `test_live_position_state_failclosed.py` does not exist at the audit SHA).
- **SUPERSEDED**: none.

## 13. Operator decisions required

1. **Ledger merge conflict**: the local working tree carries an uncommitted
   rewrite of `audit/ledger.md` (+104/−455 vs origin/main). This PR appends to
   the origin/main ledger; reconcile before/at merge (this audit did not touch
   the local copy).
2. **F-BAN-INTEGRITY**: build the ban feature end-to-end or delete the dead
   read+enforcement — either is honest; the current state is neither.
3. **F-TIER-CLIFF-REVIEW**: affirm, taper, or SHOCK-gate the micro 90% doctrine.
4. **F-SINGLE-LEG-EXPERIMENTAL**: whether to queue the pool entry behind the
   named repairs (would be the first user of the `experimental` lifecycle cap).
5. **Untracked nightly reports** `audit/reports/2026-07-14.md` (local duplicate)
   and `2026-07-15.md` sit unswept in the operator tree; this lane's diff scope
   excluded them (brief constraint) — sweep in the next build-session PR per §7
   convention.
6. **Compose surface**: label-as-mock, wire, or remove (F-UI-CAPABILITY-HONESTY).

## 14. Runtime falsifiers still pending

- Env read-backs (operator, names-only diff or read-back on the running
  process): `CONDOR_EV_MODEL` + `CONDOR_TAIL_*` (reconcile backlog "tail
  deployed" claim) · `MIN_EDGE_AFTER_COSTS` · `MULTI_STRATEGY_EVAL` ·
  `UNIVERSE_VIABILITY_BIAS_ENABLED`.
- First morning-cycle loss analysis on a losing debit-spread position →
  confirms/refutes the LossMinimizer misclassification blast radius live.
- A phase flip or lifecycle-state change exercises H10/H11 seams (none
  scheduled; trigger-gated).
- A broker permission-shaped rejection (would confirm H9's retry
  misclassification; do NOT manufacture).

## 15. Files, commands, tests, queries used

- Code: pinned worktree at `b95d3a3` (paths cited inline throughout).
- Runtime reads (read-only): Alpaca live `get_clock`/`get_account_info`/
  `get_account_config`/`get_all_positions`/`get_orders`; Railway
  `list_services`/`list_deployments` (BE, worker, worker-background); Supabase
  `SELECT`s over `strategy_lifecycle_states`, `settings`, `ops_control`,
  `go_live_progression`, `trade_suggestions` (30d + all-time GROUP BYs),
  `suggestion_rejections` (14d reason/strategy_key/cycle GROUP BYs),
  `learning_trade_outcomes_v3` (is_paper × epoch × strategy),
  `paper_orders`/`paper_positions` (30d GROUP BYs), `position_thesis_outcomes`,
  `information_schema` introspection, `supabase_migrations.schema_migrations`.
  Aggregates only; no raw-row paging; no writes.
- Numeric verification: standalone scripts in the session scratchpad importing
  `ev_calculator.py` (identity table §6-H4) and replicating sizing formulas
  (§6-H7 table). No project file executed against production state.
- Tests run: `packages/quantum/tests/test_docs_consistency.py` — **103 passed**
  at base and re-run after the doc edits (see PR).
- External: Alpaca options-level documentation (docs.alpaca.markets), fetched
  2026-07-16.

## 16. Diff scope and attestation

Diff contains exactly three files: this results artifact ·
`docs/backlog.md` (new dated section) · `audit/ledger.md` (new adjudication
entry). No production code, no migrations, no test-file changes (the existing
docs-consistency suite passes unmodified), no secrets/identifiers (account
number, account UUID, owner UUID, and broker payloads withheld; only
publicly-documented level semantics cited).

DRAFT · NOT MERGED · NOT DEPLOYED · DOCS/TESTS ONLY · NO PRODUCTION CODE · NO
MIGRATION · NO DB/BROKER WRITE · NO FLAGS, GATES, STOPS, THRESHOLDS, DTE,
WIDTHS, SIZING, STRATEGY ACTIVATION, ENTRY, EXIT, OR CONTROL CHANGED.
