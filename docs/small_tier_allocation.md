# Small-Tier Allocation-Aware Sizing

**Status:** Active policy as of 2026-05-18.
**Scope:** Small tier ($1,000-$5,000) only. Micro and standard tiers
unchanged.
**Implementation:**
`packages/quantum/services/portfolio_allocator.py::PortfolioAllocator`

---

## 1. Motivation

Pre-2026-05-18, small-tier sizing was per-trade and order-independent:
each candidate arrived at the routing layer and was sized by
`SmallAccountCompounder.calculate_variable_sizing` and
`RiskBudgetEngine.compute_budgets` independently, multiplying
`base_risk_pct (3%) × score_mult × regime_mult × compounding_mult`.
This produced per-trade max-risk values without any visibility into
other candidates in the same cycle.

That worked when the candidate set was sparse (1-2 emissions per
cycle) and the operator was risk-paranoid (micro-tier $681 capital).
Heading into small tier ($1,500+) with α's full-universe IV pipeline
delivered, the cycle-shape changes:

- More candidates per cycle (IV-aware regime classification unlocks
  iron condors + credit spreads)
- Concurrent-position cap of 4 actually matters (vs micro's 1)
- "How do we distribute capital across the viable candidate set?"
  becomes a load-bearing question that per-trade math doesn't answer

This policy introduces a **portfolio-construction layer** that runs
once per cycle, takes the viable candidate set as input, and
distributes capital across them subject to a global envelope and a
per-trade ceiling. Per-trade math then consumes the allocator's
output as a budget hint rather than computing independently.

This is GAP 1 territory per `CLAUDE.md` "5 Open Code Gaps" — the
portfolio-construction half. `DynamicWeightService` (the existing
signal-weight scoring layer at
`packages/quantum/services/dynamic_weight_service.py`) is a per-segment
score multiplier system, not a portfolio allocator; this work is
independent of that service.

---

## 2. Policy

**Tier boundary:** $1,000-$5,000 (unchanged from `CapitalTier.small`).

**Global envelope:**

- Deployable capital ceiling: **85% × regime_mult** of total equity
- Evaluated at each entry cycle against current open-position cost
  basis (read from `paper_positions.cost_basis`, not total notional,
  not `max_loss`)
- regime_mult: 1.0 normal / 0.9 suppressed / 0.8 elevated / 0.5
  shock / 1.0 chop / 1.0 rebound (matches existing engine semantics)

**Concurrent position cap:** 4 (unchanged from
`CapitalTier(name="small").max_trades`).

**Per-trade ceiling:** 36% of total equity. Binding at score 100 /
normal regime / single candidate. Acts as a defensive max regardless
of allocator math.

**Per-trade allocation:**

- Base per slot: `0.85 / n_candidates` of total equity (where
  `n_candidates = min(len(viable_candidates), 4)`)
- Score skew: `clamp(0.8 + (score − median_score)/50 × 0.4, 0.8, 1.2)`
  — same clamp range as `SmallAccountCompounder.calculate_variable_sizing`'s
  existing `score_mult` for consistency
- Per-candidate pct: `base_per_slot × score_skew`, then clamped to
  the 36% ceiling
- Envelope enforcement: allocations accumulate against
  `available_envelope = envelope_dollars − open_position_cost_basis`;
  candidates beyond the remaining envelope get truncated allocations
  or are dropped if envelope is exhausted

**Allocation objective:** maximize number of positions filled,
weighted by score. Score-skew bias is intentionally mild (0.8-1.2)
to give lower-scored candidates real fills rather than collapsing
to a single high-score position.

**Score weighting model:** skew-with-floor (Interpretation B), not
pure proportional. Floor at 0.8 ensures the lowest-scored candidate
in a viable set still gets a meaningful slot.

**H7 round-trip safety:** unchanged downstream gate. Fires per
candidate after allocation. If H7 fails, that candidate is dropped
from the cycle; remaining candidates keep their original
allocations (Option 1 fallback — see §5).

**Cycle-to-cycle behavior:** single-cycle batch, NOT continuously
rebalancing. Each cycle's allocator reads CURRENT open-position
cost basis from `paper_positions` and distributes within the
remaining envelope. No reduction of existing positions to make
room for new candidates.

---

## 3. Algorithm

```python
def allocate(candidates, total_equity, regime, open_positions):
    if not candidates or total_equity <= 0:
        return []

    regime_mult = REGIME_MULT[regime]  # 1.0 / 0.9 / 0.8 / 0.5 / 1.0 / 1.0
    envelope_dollars = total_equity * 0.85 * regime_mult
    used_dollars = sum(abs(p.cost_basis) for p in open_positions)
    available_envelope = max(0.0, envelope_dollars - used_dollars)
    if available_envelope <= 0:
        return []

    sorted_candidates = sort(candidates, by=score, desc=True)
    n_candidates = min(len(sorted_candidates), 4)
    selected = sorted_candidates[:n_candidates]
    median_score = median([c.score for c in selected])

    base_pct_per_slot = 0.85 / n_candidates
    results = []
    remaining_envelope = available_envelope

    for cand in selected:
        skew = clamp(0.8 + (cand.score - median_score) / 50 * 0.4, 0.8, 1.2)
        raw_pct = base_pct_per_slot * skew
        final_pct = min(raw_pct, 0.36)   # per-trade ceiling
        raw_budget = total_equity * final_pct
        final_budget = min(raw_budget, remaining_envelope)
        if final_budget <= 0:
            break
        results.append(AllocationResult(
            candidate=cand,
            allocated_budget=final_budget,
            ...
        ))
        remaining_envelope -= final_budget

    return results
```

### Worked examples

All examples use `regime_mult=1.0` (normal) unless noted, and
COMPOUNDING_MODE doesn't appear in the allocator's math directly —
it influences the per-trade ceiling indirectly via the historical
"25% × multipliers" derivation, but the allocator caps at a flat 36%.

### Example A — $1,500 equity, 4 candidates, normal regime

Candidates: scores 95, 88, 82, 76.

- `envelope_dollars = 1500 × 0.85 × 1.0 = $1,275`
- `n_candidates = 4`
- `base_pct_per_slot = 0.85 / 4 = 0.2125` (21.25%)
- `median_score = (88 + 82) / 2 = 85`

| Score | Skew | raw_pct | Ceiling? | Final $ |
|---|---|---|---|---|
| 95 | 0.8 + (10/50)×0.4 = **0.880** | 18.70% | no | **$280.50** |
| 88 | 0.8 + (3/50)×0.4 = **0.824** | 17.51% | no | **$262.65** |
| 82 | 0.8 + (-3/50)×0.4 = 0.776 → clamp **0.800** | 17.00% | no | **$255.00** |
| 76 | 0.8 + (-9/50)×0.4 = 0.728 → clamp **0.800** | 17.00% | no | **$255.00** |

Total allocated: **$1,053.15** (70.21% of equity, well under the
85% envelope = $1,275).

### Example B — $1,500 equity, 2 candidates, normal regime

Candidates: scores 92, 78.

- `envelope_dollars = 1500 × 0.85 × 1.0 = $1,275`
- `n_candidates = 2`
- `base_pct_per_slot = 0.85 / 2 = 0.425` (42.5%)
- `median_score = (92 + 78) / 2 = 85`

| Score | Skew | raw_pct | Ceiling? | Final $ |
|---|---|---|---|---|
| 92 | 0.8 + (7/50)×0.4 = **0.856** | 36.38% | **YES → 36%** | **$540.00** |
| 78 | 0.8 + (-7/50)×0.4 = 0.744 → clamp **0.800** | 34.00% | no | **$510.00** |

Total: **$1,050.00** (70% of equity, well within envelope).
Cand 1's ceiling binds (raw 36.38% > 36% cap → final 36%).
Cand 2's ceiling does **not** bind (raw 34% < 36%); skew clamp does.

Note: the spec text says "ceiling binds for both"; in practice only
the higher-score candidate's ceiling binds. The lower-score
candidate's skew clamp at 0.8 keeps it just under 36%.

### Example C — $1,500 equity, 1 candidate, normal regime

Candidate: score 88.

- `envelope_dollars = 1500 × 0.85 × 1.0 = $1,275`
- `n_candidates = 1`
- `base_pct_per_slot = 0.85 / 1 = 0.85` (85%)
- `median_score = 88` (single value → score == median)

| Score | Skew | raw_pct | Ceiling? | Final $ |
|---|---|---|---|---|
| 88 | 0.8 + 0/50 = **0.800** | 68.00% | **YES → 36%** | **$540.00** |

Total: **$540.00**. Ceiling binds. With a single candidate the raw
allocation would be 68% of equity which exceeds the per-trade max;
the 36% cap defends concentration risk.

### Example D — $3,000 equity, 4 candidates, elevated regime

Candidates: scores 90, 85, 80, 72. Elevated regime → `regime_mult = 0.8`.

- `envelope_dollars = 3000 × 0.85 × 0.8 = $2,040`
- `n_candidates = 4`
- `base_pct_per_slot = 0.85 / 4 = 0.2125`
- `median_score = (85 + 80) / 2 = 82.5`

| Score | Skew | raw_pct | raw $ | Envelope? | Final $ |
|---|---|---|---|---|---|
| 90 | 0.8 + (7.5/50)×0.4 = **0.860** | 18.275% | $548.25 | no | **$548.25** |
| 85 | 0.8 + (2.5/50)×0.4 = **0.820** | 17.425% | $522.75 | no | **$522.75** |
| 80 | 0.8 + (-2.5/50)×0.4 = 0.780 → clamp **0.800** | 17.000% | $510.00 | no | **$510.00** |
| 72 | 0.8 + (-10.5/50)×0.4 = 0.716 → clamp **0.800** | 17.000% | $510.00 | **YES (truncated)** | **$459.00** |

Running envelope after each allocation:
$2040.00 → $1491.75 → $969.00 → $459.00 → $0.00.

The fourth candidate's raw $510 exceeds remaining envelope $459.00,
so it gets the truncated remainder. **regime_mult flows through the
envelope** (envelope 68% of equity instead of 85%) and indirectly
through per-trade (Cand 4 truncated by what regime_mult left
available).

Total deployed: **$2,040.00** = exactly 68% of equity = envelope.

### Example E — $1,500 equity, $450 open position, 3 new candidates

Candidates: scores 90, 82, 74. Normal regime. One open position
with cost basis $450.

- `envelope_dollars = 1500 × 0.85 × 1.0 = $1,275`
- `used_dollars = $450`
- `available_envelope = $1,275 − $450 = $825`
- `n_candidates = 3`
- `base_pct_per_slot = 0.85 / 3 = 0.28333…`
- `median_score = 82`

| Score | Skew | raw_pct | raw $ | Envelope? | Final $ |
|---|---|---|---|---|---|
| 90 | 0.8 + (8/50)×0.4 = **0.864** | 24.48% | $367.20 | no | **$367.20** |
| 82 | 0.8 + 0 = **0.800** | 22.67% | $340.00 | no | **$340.00** |
| 74 | 0.8 + (-8/50)×0.4 = 0.736 → clamp **0.800** | 22.67% | $340.00 | **YES (truncated)** | **$117.80** |

Running envelope: $825 → $457.80 → $117.80 → $0.

Cand 3 truncated because the open position consumed enough envelope
that there isn't a full slot left. This is the cycle-to-cycle
behavior in action — Monday's still-open position constrains
Tuesday's allocator.

---

## 4. Edge cases

**0 candidates:** allocator returns `[]`. Cycle produces no entries.
Existing behavior preserved.

**1 candidate:** `base_pct = 0.85`, ceiling at 0.36 binds → 36%
allocation. Single-position concentration concern addressed by
ceiling.

**2 candidates:** `base_pct = 0.425`. Ceiling binds for the
higher-score candidate (typically); lower-score candidate sits
around 34%. Total ~70% of equity.

**3 candidates:** `base_pct ≈ 0.283`. Ceiling does not bind. ~28%
each with mild skew.

**4 candidates:** `base_pct = 0.2125`. Ceiling does not bind. ~21%
each with skew. Hits the concurrent-position cap exactly.

**5+ candidates:** drop the lowest-scored excess (concurrent cap =
4). Top 4 allocated as in the 4-candidate case.

**Envelope exhausted by open positions:** if
`sum(cost_basis) >= envelope_dollars`, allocator returns `[]`. No
new positions opened until existing ones close.

**Envelope partially exhausted:** later candidates in the sort
order get truncated allocations (see Examples D and E). When a
candidate's truncated allocation is `$0`, allocator stops emitting.

**H7 fallback (Option 1):** H7 round-trip safety fires AFTER the
allocator on each candidate independently. If a candidate's
`max_loss × 2.1 > available_BP_at_that_position`, that candidate
is DROPPED from the cycle. Remaining candidates keep their
ORIGINAL allocations — no redistribution of the dropped slot's
budget. Reasoning: simpler cycle-plan semantics; can be optimized
later if empirical data shows H7 dropping candidates frequently.

---

## 5. Interaction with existing systems

**H7 round-trip safety** (`docs/loud_error_doctrine.md` "H7 —
Operations preserve capital invariants in both directions"):
unchanged. Fires post-allocator as a downstream gate. Dropping a
candidate at H7 produces a `h7_drop_post_allocation` alert via
`risk_alerts` so the operator can measure how often Option 1's
no-redistribution stance is suboptimal.

**edge_below_minimum** (downstream EV-floor gate in
`workflow_orchestrator`): unchanged. Edge filtering happens BEFORE
the allocator. The allocator's input candidate set has already
passed edge gates.

**COMPOUNDING_MODE** (env var): the allocator does not directly
read this flag. The 25% × score_mult × regime_mult ×
compounding_mult derivation that motivated the 36% ceiling
(25% × 1.2 × 1.2 ≈ 36%) is the historical reasoning; the allocator
caps at a flat 36% regardless of compounding state. When
`COMPOUNDING_MODE=false`, the per-trade ceiling is still 36% but
fewer candidates typically clear scoring thresholds — same net
effect as the existing compounding-off code paths.

**regime_mult:** flows through the global envelope (envelope
shrinks 5-50% based on regime, capping later-candidate allocations).
This is the canonical regime impact on small tier; per-trade math
itself doesn't multiply by regime_mult because that would
double-count when allocations already share the regime-shrunk
envelope.

**Concurrent position cap (4):** unchanged. Allocator's
`n_candidates = min(len(viable), 4)` enforces this at the
allocation layer; downstream layers can also enforce.

**H10 stale-state cascade** (`docs/loud_error_doctrine.md` "H10 —
Stale state cascades through pipeline gates"): the allocator's
open-position cost-basis subtraction reads from `paper_positions`.
If ghost rows are present, the allocator under-allocates (failure
mode is safe — fewer fills than expected, not over-deployment).
Operator must keep `paper_positions` reconciled. The 2026-05-12 CSX
ghost incident produced 12+ `ghost_position` alerts per hour while
the row was stale; H10 doctrine codified that ghost reconciliation
is load-bearing for pipeline liveness. Same caveat applies here.

---

## 6. What this DOES NOT change

- **Micro tier** ($0-$1000): completely untouched. Still 90% ×
  regime_mult, one position at a time. The allocator is gated on
  `tier == "small"` in workflow_orchestrator.
- **Standard tier** ($5,000+): completely untouched. Still 2%
  base × full multiplier stack via existing
  `RiskBudgetEngine.compute_budgets` path.
- **H7 round-trip safety logic itself:** unchanged. H7 stays where
  it is; allocator's output passes through.
- **Edge gates** (`edge_below_minimum` etc.): unchanged. Edge
  filtering is upstream of allocator.
- **Scanner emission:** unchanged. Allocator receives the existing
  scanner output verbatim.
- **Per-symbol risk envelope** (`RISK_MAX_SYMBOL_PCT`): unchanged.
  Still enforced downstream.
- **Existing `RiskBudgetReport` schema:** unchanged. Allocator
  outputs are passed through `allocation_hint` parameter
  additively; backward-compatible with all existing callers.

---

## 7. Open items deferred

These are intentional out-of-scope items for the initial allocator,
captured for future work:

1. **Continuous rebalancing across cycles:** the allocator does
   single-cycle batch only. A future iteration could reduce
   existing positions when a meaningfully-higher-scored candidate
   appears, but Option 1 explicitly defers that complexity.

2. **H7 redistribution:** when H7 drops a candidate post-allocation,
   the dropped slot's budget is currently NOT redistributed to
   remaining candidates. Option 1 picks simpler semantics. Promote
   to Option 2 (redistribute) if empirical data shows H7 dropping
   candidates >5% of cycles.

3. **Correlation / concentration controls in allocation:** the
   allocator doesn't yet penalize highly-correlated candidates
   (e.g., 4 SPY-tracking ETFs in one cycle). Sector / underlying
   diversification is a separate concern that may layer on top of
   the allocator. Listed under GAP 1 in CLAUDE.md.

4. **Dynamic n_candidates:** currently capped hard at 4
   (`CapitalTier.small.max_trades`). A future iteration could
   adapt n based on regime (fewer concurrent positions in shock,
   more in suppressed) — but that requires empirical evidence the
   current cap is suboptimal.

5. **Allocator-aware H7 pre-check:** allocator could pre-check H7
   per candidate and exclude unsizable candidates from the
   allocation set, avoiding the post-allocation drop. Deferred
   until the H7 drop rate is measured.

---

## Cross-references

- `packages/quantum/services/portfolio_allocator.py` — implementation
- `packages/quantum/services/risk_budget_engine.py` — RBE
  integration via `allocation_hint` parameter
- `packages/quantum/services/analytics/small_account_compounder.py`
  — Compounder integration (mirrored hint pattern per
  CLAUDE.md "single producer of max_risk_per_trade" doctrine)
- `packages/quantum/services/workflow_orchestrator.py` — wire-in
  at the `rank_and_select` callsite (small tier only)
- `docs/loud_error_doctrine.md` — H7, H10 doctrines
- `CLAUDE.md` "Risk per trade math" — top-level summary
- `CLAUDE.md` "5 Open Code Gaps" — GAP 1 context
