# ⑤ Offline Challenger-vs-Baseline Study — 2026-07-18

**Lane 2B / queue-⑤ · OBSERVE-ONLY · READ-ONLY.** This study accumulates dated
evidence comparing the **frozen baseline predictor** against the **lognormal
challenger** (`challenger_lognormal_v1`, PR #1247) over closed historical
outcomes. It changes nothing in the live path (see §7 non-interference proof).

## 0. Recommendation

> **INSUFFICIENT_EVIDENCE.**

The lognormal challenger produced **zero** scored predictions over **all 82**
closed historical outcomes (both cohorts), because the two inputs it requires —
**per-leg implied volatility** and **entry underlying spot** — were **never
persisted** at decision time. The frozen-baseline *adapter* likewise scores
zero offline (it needs per-leg deltas, also unpersisted). With no joint scored
set (`n_joint = 0` in both cohorts) the charter falsifier
("locked prequential cohorts must beat the delta/fair-odds baseline on Brier /
EV-RMSE / net-P&L rank") **cannot be adjudicated on history at all**. The blocker
is *data capture*, not model quality (§8 forward path). Promotion is not on the
table; neither `CONTINUE_OBSERVE` nor `CHALLENGER_READY_*` is reachable because
the challenger has emitted no signal to observe.

What *is* measurable — and reported below as the bar the challenger must one day
clear — is the **frozen baseline as it actually ran** (the production pop/ev
stored in `learning_trade_outcomes_v3`).

## 1. Methodology & predicates (every one explicit)

- **Universe.** Closed outcomes in `learning_trade_outcomes_v3` with a non-null
  `suggestion_id`, joined to `trade_suggestions` for the structure legs.
  Deduped `DISTINCT ON (suggestion_id)` keeping the latest `closed_at`
  (the outcome census carries duplicate rows; the F-CREDIT-SIGN annotation flags
  them via `duplicate_outcome_row`). Exact query: `scripts/analytics/challenger_study.py --emit-sql`.
- **Cohorts kept SEPARATE** by `is_paper`: **live / broker-routed**
  (`is_paper = false`) vs **shadow / internal** (`is_paper = true`). No metric
  is ever pooled across cohorts (shadow fills are fictional — §5).
- **Corrected P&L facts.** `realized_pnl = v3.pnl_realized`, which is already the
  post-`F-CREDIT-SIGN` live value (correction committed 2026-07-18 ~14:2xZ,
  census fingerprint `b780271c…`). Verified: for every corrected suggestion,
  `v3.pnl_realized == learning_feedback_loops.pnl_realized (corrected) ≠
  details_json->'f_credit_sign_correction'->>'original_pnl_realized'` (§4).
- **Win rule.** `win := realized_pnl > 0` (breakeven `0` counts as non-win).
- **Structure mapping.** DB `IRON_CONDOR → iron_condor`;
  `LONG_CALL_DEBIT_SPREAD` / `LONG_PUT_DEBIT_SPREAD → debit_vertical`
  (call/put orientation preserved in the legs; the *segment* strategy label is
  the contract family). Strikes / option-type / expiry parsed from the OCC leg
  symbols (`O:AMD260313P00180000` → put, 180.0, 2026-03-13). `net_premium =
  order_json.limit_price` (positive; credit for condor, debit for verticals).
  `dte_days = max(leg expiry) − date(known_at)`; DTE buckets `0-14/15-30/31-45/46+`.
- **`known_at`** = `entry_ts` (fallback `suggestion.created_at`) — the as-of
  moment; the foundation evaluator orders prequentially on it.
- **Three predictors, all run through the SAME foundation evaluator**
  (`evaluate_model`, `head_to_head` from PR #1247, verbatim):
  1. **Frozen baseline (as-emitted):** the production pop/ev that
     `ev_calculator` produced at decision time, stored in `v3.pop_predicted` /
     `v3.ev_predicted`. This *is* the frozen baseline authority as it ran — no
     re-derivation. Abstains (H9) when a stored value is missing.
  2. **Frozen baseline adapter (offline re-run):** `baselines.py` wrapping
     `ev_calculator` verbatim. Needs per-leg deltas → **abstains** offline.
  3. **Lognormal challenger (offline):** `challenger_lognormal_evaluate`. Needs
     per-leg IV + spot → **abstains** offline.
- **Metrics** (foundation, deterministic): Brier `mean((pop − win)²)`; EV-RMSE
  `sqrt(mean((ev − realized_pnl)²))` in per-position dollars; realized net;
  coverage `scored/eligible`; per-segment (strategy · regime · DTE). Metrics are
  computed on the **both-present** subset (a record scores only if BOTH pop and
  ev exist); records missing a stored pop are **abstained and counted**, never
  coerced to 0.5 (H9).
- **Censoring.** Open/unresolved outcomes are excluded and counted; here every
  studied row is `resolved` (`censored = 0`, `malformed = 0`). The only
  exclusions are (a) baseline abstentions on missing stored pop (12 shadow rows)
  and (b) structurally unmappable rows (0).

## 2. Data provenance & sample counts

| cohort | strategy | deduped n | stored pop present | stored ev present | wins (pnl>0) |
|---|---|---|---|---|---|
| live | IRON_CONDOR | 4 | 4 | 4 | 0 |
| live | LONG_CALL_DEBIT_SPREAD | 3 | 3 | 3 | 0 |
| live | LONG_PUT_DEBIT_SPREAD | 1 | 1 | 1 | 1 |
| shadow | IRON_CONDOR | 38 | 36 | 38 | 33 |
| shadow | LONG_CALL_DEBIT_SPREAD | 20 | 14 | 20 | 5 |
| shadow | LONG_PUT_DEBIT_SPREAD | 16 | 12 | 16 | 6 |
| **total** | | **82** | 70 | 82 | 45 |

- **No credit-vertical outcomes exist** in 82 closed trades — consistent with
  the ⑤ credit-EV ≡ $0 identity producing 0 credit suggestions (the baseline
  defect the foundation keeps visible, never repaired here).
- The census file (`scripts/analytics/fixtures/challenger_study_2026-07-18.json`)
  reproduces this study offline and is metric-validated against the DB
  aggregates (Brier / EV-RMSE / net match to <1e-5 per cohort·strategy).

## 3. The decisive structural finding — inputs the challenger needs were never captured

A full key-scan of every JSONB column on the 82 outcome-linked suggestions
(`order_json`, `sizing_metadata`, `historical_stats`, `agent_signals`,
`decision_lineage`, `marketdata_quality`, `vrp_ranking`, `ranking_costs`) and of
`paper_positions.legs` found:

- **per-leg IV: absent everywhere** (0/82). `sizing_metadata.context.iv_rank`
  is an IV *percentile*, not an implied vol; the budget-snapshot greeks are the
  double-dormant all-zero block (§8 known-liar).
- **per-leg delta: absent everywhere** (0/82).
- **entry underlying spot: absent everywhere** (0/82). `avg_entry_price` /
  `limit_price` is the *spread* net premium, not spot.

Legs carry only `side · OCC symbol · quantity` (strike/type/expiry are
recoverable; IV/delta/spot are not). This is **structural, not sparse** — there
is no IV or spot column to be null. Consequently, per H9, both the challenger
(`missing_spot`) and the frozen adapter (`missing_delta`) abstain on **100%** of
history. This is the correct, non-fabricating outcome — never a defaulted IV or
a reconstructed spot.

## 4. Corrected-fact usage proof

`F-CREDIT-SIGN` corrected 20 `learning_feedback_loops` rows (18 distinct
shadow/internal positions), all `is_paper = true`, all `IRON_CONDOR`; **0 live
rows touched**. Spot checks (v3 now == corrected lfl, ≠ original):

| suggestion_id | v3.pnl_realized (now) | original_pnl_realized | direction |
|---|---|---|---|
| 0708743c… | −224.04 | +1815.96 | win → loss |
| f0050153… | −242.00 | +1202.00 | win → loss |
| 2d15e4b6… | +6142.00 | +6494.00 | reduced |
| 49e911d7… | +8668.50 | +9421.50 | reduced |

The study reads `v3.pnl_realized` throughout (the live value), segments the 18
corrected rows by the annotation (`corrected` flag; all fall in the SHADOW
cohort — 18 of 74 shadow rows), and never mixes them into the live cohort.

## 5. Results

Generated by `challenger_study.py` over the census fixture (verbatim):

### Cohort: LIVE (is_paper=false)

- Rows: **8** · corrected rows in cohort: **0** · unmappable skips: 0 ·
  censored: 0 · malformed: 0 · eligible: 8

| model | scored/eligible (coverage) | abstained | Brier | EV-RMSE ($) | realized net ($) |
|---|---|---|---|---|---|
| frozen baseline (as-emitted, stored production pop/ev) | 8/8 (100%) | 0 | **0.3105** | **69.31** | **−178.00** |
| frozen baseline adapter (offline re-run) | 0/8 (0%) | 8 | — | — | — |
| lognormal_v1 challenger (offline) | 0/8 (0%) | 8 | — | — | — |

- Adapter abstentions: `missing_delta ×8` · Challenger abstentions: `missing_spot ×8`
- **Head-to-head (baseline vs challenger): n_joint = 0 → falsifier UNADJUDICABLE.**

| strategy | regime | DTE | n | Brier | EV-RMSE ($) | realized net ($) |
|---|---|---|---|---|---|---|
| debit_vertical | chop | 15-30 | 1 | 0.2334 | 53.93 | −28.00 |
| debit_vertical | normal | 31-45 | 3 | 0.1983 | 56.60 | −7.00 |
| iron_condor | chop | 15-30 | 1 | 0.4099 | 119.06 | −73.00 |
| iron_condor | chop | 31-45 | 1 | 0.4123 | 80.63 | −45.00 |
| iron_condor | normal | 31-45 | 2 | 0.4168 | 51.18 | −25.00 |

### Cohort: SHADOW (is_paper=true)

- Rows: **74** · corrected rows in cohort: **18** · unmappable skips: 0 ·
  censored: 0 · malformed: 0 · eligible: 74

| model | scored/eligible (coverage) | abstained | Brier | EV-RMSE ($) | realized net ($) |
|---|---|---|---|---|---|
| frozen baseline (as-emitted, stored production pop/ev) | 62/74 (84%) | 12 | **0.2493** | **2117.01** | **43156.50** |
| frozen baseline adapter (offline re-run) | 0/74 (0%) | 74 | — | — | — |
| lognormal_v1 challenger (offline) | 0/74 (0%) | 74 | — | — | — |

- Adapter abstentions: `missing_delta ×74` · Challenger abstentions: `missing_spot ×74`
- Baseline abstentions: `missing_stored_prediction ×12` (shadow rows with no stored pop)
- **Head-to-head (baseline vs challenger): n_joint = 0 → falsifier UNADJUDICABLE.**

| strategy | regime | DTE | n | Brier | EV-RMSE ($) | realized net ($) |
|---|---|---|---|---|---|---|
| debit_vertical | elevated | 15-30 | 1 | 0.4082 | 1806.57 | −1265.50 |
| debit_vertical | elevated | 31-45 | 2 | 0.2464 | 1066.61 | −622.00 |
| debit_vertical | normal | 15-30 | 11 | 0.3048 | 838.72 | 1055.25 |
| debit_vertical | normal | 31-45 | 12 | 0.5001 | 1838.87 | −9926.00 |
| iron_condor | chop | 15-30 | 4 | 0.1172 | 4371.18 | 11035.00 |
| iron_condor | chop | 31-45 | 29 | 0.1402 | 2243.01 | 41245.75 |
| iron_condor | elevated | 31-45 | 3 | 0.2234 | 748.48 | 1634.00 |

### Reading the numbers (with the caveats that bind them)

- **Cross-cohort comparison is basis-broken** (`docs/specs/shadow_fill_realism.md`
  known-liar): the shadow baseline "realized net +43,157" is fiction — shadows
  fill 100% by construction at 5–17× live size, live fill rate ≈ 1/3. Shadow
  condor EV-RMSE ($2,117–$4,371) reflects those inflated magnitudes, not model
  error. **Never rank the baseline (or a future challenger) on shadow P&L.**
- **Live signal (small n, do not act):** the live baseline predicted a mean win
  probability ≈ 0.60 but realized **1 win in 8** (all 4 condors and all 3
  call-debits lost; only the single put-debit won). Live condor Brier ≈ 0.41 on
  a ~0.64 predicted win-prob. On corrected facts the current baseline looks
  **over-confident on the live book** — but n = 8 is far below any decision
  floor (cf. the #1051 8-live-close convergence rule) and this is a baseline
  self-assessment, **not** a challenger comparison.
- **Stored pop artifacts:** two shadow call-debits carry `pop_predicted > 1`
  (1.0383, 1.0143) — the delta-proxy PoP can exceed 1, itself a baseline
  miscalibration tell. Reported verbatim (H9), never clamped.

## 6. Charter falsifier status

The falsifier requires a joint scored set on which challenger and baseline are
both priced. **`n_joint = 0` in both cohorts.** The comparison is therefore
**indeterminate on historical data by construction** — not a pass, not a fail.
Retain the baseline; the challenger cannot yet be tested.

## 7. Non-interference proof (observe-only)

- The runner lives at `scripts/analytics/challenger_study.py`, **outside**
  `packages/quantum/`, so it is invisible to the import-lock sweep
  (`test_terminal_distribution_import_lock.py::test_no_production_module_references_the_package`,
  which scans `packages/quantum/**/*.py`). That suite is **green** (6/6).
- The runner imports only the foundation package + stdlib; it opens **no DB
  connection** (`--emit-sql` prints read-only SQL for the operator to run;
  `--rows-json` consumes the result). `grep -rn "challenger_study" packages/`
  → no hit outside `tests/`. No scanner / ranker / gate / executor / EV module
  imports it or the terminal_distribution package (import-lock enforced).
- No selector/ranker/gate/EV code path was modified. The only files added are
  the runner, its test, the census fixture, and this report.

## 8. Forward path (what would make the challenger testable)

To accumulate real challenger evidence, **capture at decision time** (stage
seam), per selected candidate, into a durable column/JSON:
`entry_spot`, and per leg `iv` + `delta` (the snapshot the scanner already
fetches carries them — they are simply dropped before persistence). Once N
post-capture live closes exist, re-run `challenger_study.py` unchanged: both the
challenger and the frozen adapter will score, `head_to_head` will populate, and
the falsifier becomes adjudicable — **on the live cohort only**, never shadow.
Until then: retain the baseline, keep observing, do not promote.

## 9. Reproduction

```
# print the exact read-only query, run it via the Supabase MCP, save JSON:
python scripts/analytics/challenger_study.py --emit-sql

# regenerate this study's tables from the committed census fixture:
PYTHONPATH=. python scripts/analytics/challenger_study.py \
  --rows-json scripts/analytics/fixtures/challenger_study_2026-07-18.json \
  --out docs/review/challenger-study-2026-07-18.md

# tests (metric math + cohort separation, no live-DB dependency):
PYTHONPATH=. pytest packages/quantum/tests/test_challenger_study.py -q
```
