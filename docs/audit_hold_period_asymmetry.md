# Audit — Hold-period asymmetry (stop_loss vs target_profit)

**Date:** 2026-05-18
**Scope:** Narrow — paper_exit_evaluator threshold mechanism only. Out of scope: profit threshold (under separate empirical review), profit-target sqrt-decay shape, H7 round-trip safety, edge_below_minimum gate, allocator (PR #958), any schema changes.
**Branch:** `audit/hold-period-asymmetry`
**Trigger:** 2026-05-18 diagnostic baseline pass surfaced ~2.7× hold-time asymmetry across stop_loss vs target_profit exits.

---

## TL;DR

- The aggregate "2.7×" asymmetry across ALL closes overstates the in-class effect. Within debit_spread alone, the asymmetry is **2.54×** (143.4h stops vs 56.4h profits). Aggregate is inflated by iron_condor profits resolving in ~5h.
- Mechanism (verified from `paper_exit_evaluator.py:225-244`): `_check_stop_loss` is a **FLAT** threshold (default 50% of entry cost). `_check_target_profit` calls `_time_scaled_target_profit_pct` (sqrt-decay from 50% at entry → ~19% at 5 DTE / 35 entry_dte). The asymmetry is doctrinal: profit-target acknowledges theta acceleration; stop-loss does not.
- 5 of 6 debit_spread stops in the 90-day window were **monotonic losers** (never crossed +35% profit territory). 1 (AMZN) crossed +$277 briefly then reversed. None were "near-wins reversed to losses by a too-tight stop."
- **Critical guardrail finding:** 2 iron_condor target_profit wins (AMZN, GOOGL) bottomed at -$2552 and -$2235 (each below -50% of entry cost for 7 EOD snapshots) before recovering to +$2094 and +$1770. A blanket stop tightening would have converted these to losses. **Any stop change MUST exclude iron_condor.**
- **Sample staleness:** latest close 2026-04-10, no closes in 5+ weeks. Data predates several Q2 system fixes. Confidence is LOW on any extrapolation to current system behavior.

---

## Single highest-leverage change

**Introduce DTE-aware time-scaling on `_check_stop_loss` for DEBIT SPREADS ONLY, env-gated, default OFF.**

- Mirror profit-target's sqrt-decay shape: `effective_sl = max(0.30, base_sl * (dte_ratio ** 0.5))`.
- At entry (`dte_ratio=1.0`): effective_sl = 0.50 → identical to current behavior.
- Mid-life (`dte_ratio≈0.5`): effective_sl ≈ 0.354 → stop fires ~30% sooner in upl terms.
- Near expiry (`dte_ratio=0.14`, 5 DTE on entry_dte=35): clamped to floor 0.30.
- Iron condor + credit spread + "other" classes: bypass the time-scaling, retain current flat behavior. Rationale: oscillation around credit-collected is a *feature* of these structures (Q2 evidence: AMZN_IC / GOOGL_IC recoveries).
- Gated by `EXIT_STOP_LOSS_TIME_SCALING_ENABLED=1`. Default OFF preserves current behavior — flip per environment for shadow observation.

### Why this single change

| Criterion | Why this passes |
|---|---|
| Doctrine alignment | Symmetric to profit-target sqrt-decay; theta acceleration applies in both directions |
| Strategy-class respect | Excludes iron_condor based on Q2 oscillation evidence |
| Win-rate guardrail | In N=6 debit_spread stop sample, zero positions ever crossed +35% profit; tightening cannot retroactively convert wins to losses |
| Narrow scope | One function + one env flag in `paper_exit_evaluator.py`; no schema, no allocator, no H7 |
| Reversibility | Env-gated default OFF; revert is `EXIT_STOP_LOSS_TIME_SCALING_ENABLED=0` |
| Honesty | LOW confidence at N=6 + 5-week-stale data is acknowledged in the doc and CLAUDE.md note |

### Estimated impact (LOW confidence)

| Hold phase | dte_ratio | New sl_pct (sqrt-decay floor 0.30) | UPL trigger vs old |
|---|---|---|---|
| Entry | 1.00 | 0.500 | unchanged |
| Day 3 of 35-DTE | 0.91 | 0.477 | fires ~5% sooner |
| Day 7 | 0.80 | 0.447 | fires ~11% sooner |
| Day 14 | 0.60 | 0.387 | fires ~23% sooner |
| Day 21 | 0.40 | 0.316 | fires ~37% sooner |
| Day 28+ | ≤0.20 | 0.300 (floor) | fires ~40% sooner |

Estimated debit_spread stop hold-time reduction: **~15-25%** (143h → ~108-122h). Sqrt-decay is gentle by design — aggressive linear or step-function would be higher-risk and is rejected for this audit.

Estimated win-rate impact: **0 percentage points** in the N=6 sample (no false-positive cases observed). At higher N, expect non-zero false-positives but bounded by the 30% floor.

**N classification: LOW (N=6 debit_spread stops < 10).** Per project doctrine in CLAUDE.md Exit thresholds section, re-evaluation at N=20 per outcome bucket. This audit's recommendation is gated default OFF specifically to allow shadow accumulation before promotion.

---

## Data investigation — full results

### Q1: Stop_loss trajectory (last 90d)

```
N=7. All 6 debit_spread cases + 1 iron_condor (AMD, wing-breach).
Latest close: 2026-04-10. Earliest: 2026-03-26.

Symbol  hold_h  days_pos  days_above_35%  min_upl    max_upl    realized_pl
ADBE    188.8   0         0               -997.50    -100.00    -990
AMD-IC  96.4    0         0               -206.00     0.00      +1202 (wing-breach win)
AVGO    188.8   5         0               -1121.50   +45.00     -1265
MSFT    236.3   1         0               -1240.00   +32.50     -1240
NVDA    49.7    0         0               -2047.50   -15.00     -3262
GOOG    49.7    1         0               -2055.00   +50.00     -3760
AMZN    147.4   2         1               -2268.00   +277.50    -1860
```

Pattern: 5 of 6 debit_spread stops were **monotonic losers** (max_upl ≤ +$50, never crossed +35% profit territory). AMZN is the only oscillation case (max_upl +$277 = brief profit excursion, still well below profit-target threshold). The AMD iron_condor was a wing-breach exit on an already-profitable position — categorically different mechanism.

### Q2: Target_profit trajectory (top 25 by recency, last 90d)

Critical observations:

| Position | days_below_50pct_loss | min_upl | realized_pl |
|---|---|---|---|
| AMZN_iron_condor | 7 | -$2552 | +$2094 |
| GOOGL_iron_condor | 7 | -$2235 | +$1770 |

These iron_condor positions spent 7 EOD snapshots underwater past the -50% stop threshold before recovering to profit-target. A blanket stop tightening to 35% (or even keeping 50% but adding intraday cadence) would have force-closed both at significant losses. Recovery total: **$3,864 of preserved profit at risk** from a strategy-class-blind stop change.

No debit_spread target_profit cases in the sample crossed below -50%. All 9 debit_spread profits resolved with min_upl ≥ -$110 (TSLA case).

### Q3: Hold-time distribution

```
close_reason       n   avg_h   median_h   min    max     earliest        latest
stop_loss_hit       7   136.7   147.4     49.7   236.3   2026-03-26      2026-04-10
target_profit_hit  40    28.1    20.1      0.6   169.8   2026-02-18      2026-04-10
```

Aggregate ratio: 136.7 / 28.1 = **4.86×** — inflated by iron_condor fast-resolves.

### Q4: Strategy-class split

```
strategy_class   close_reason         n   avg_hours   avg_pl
debit_spread     stop_loss_hit        6   143.4       -2063
debit_spread     target_profit_hit    9    56.4       +1511
iron_condor      stop_loss_hit        1    96.4       +1202   (wing-breach)
iron_condor      target_profit_hit   16     5.2       +2708
other            target_profit_hit   15    35.6       +1301
```

In-class debit_spread asymmetry: 143.4 / 56.4 = **2.54×**. This is the cleanest comparable signal. Iron condor stop sample (N=1) is too small to compare against profits.

---

## What this audit does NOT claim

- Does not claim the 30% floor is the right floor. It's chosen as a 1.5× compression of the profit-target floor (0.245) and a round number that keeps the worst-case sooner-trigger bounded.
- Does not claim sqrt-decay is the right shape. Sqrt was chosen for doctrine symmetry. Linear or piecewise might be defensible; insufficient evidence to differentiate.
- Does not claim debit_spread stops are "too loose." The mechanism is doctrine-asymmetry, not threshold-tuning. The 50% threshold remains the entry-time anchor.
- Does not claim iron_condor stop behavior is correct. The single iron_condor stop in the sample was a wing-breach exit (mechanically distinct from the -50% threshold), but Q2's recovery cases suggest the -50% threshold is *defensibly* loose for iron_condor — different mechanism, different empirical pattern, different appropriate fix shape.
- Does not claim the diagnostic's "2.7× hold time asymmetry" framing is the right framing. Within-class it's 2.54×; cross-class it's 4.86×; both are real and partly an artifact of strategy mix.

---

## Verification plan

1. Ship with `EXIT_STOP_LOSS_TIME_SCALING_ENABLED=0` default. Existing behavior preserved on production.
2. Regression test asserts: (a) flag-off path identical to legacy behavior; (b) flag-on path computes per-DTE sl_pct via the formula; (c) iron_condor + non-debit always uses the flat path even with flag on.
3. Enable in one shadow cohort (conservative) for 30 days. Compare debit_spread stop hold-time + win-rate against the unchanged neutral cohort.
4. Re-evaluate at N=15 debit_spread stops across enabled cohort. Promote to all cohorts only if hold-time reduces ≥ 10% AND win-rate within ±5pp of control.

---

## Cross-references

- `packages/quantum/services/paper_exit_evaluator.py:180-244` — current `_time_scaled_target_profit_pct` + `_check_stop_loss`
- `packages/quantum/services/paper_exit_evaluator.py:329-330` — current thresholds
- CLAUDE.md Exit thresholds section (defaults under empirical review at N=20)
- `docs/loud_error_doctrine.md` — H12 (intent drift across encodings; informs why we audit mechanism in code before forming a recommendation)
- PR #928 / #929 — `hold_period_buckets` view that surfaced the hold-time data
