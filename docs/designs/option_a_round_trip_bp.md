# Option A — Round-Trip BP Check at Sizing

**Status:** Design complete; implementation deferred to Saturday 2026-05-03
**Backlog:** #100
**Discovery:** 2026-05-01 BAC ghost position incident (see PR #853)
**Author:** Diagnostic 2026-05-02

---

## 1. Problem statement

`sizing_engine.py:calculate_sizing` validates that **entry collateral** fits within `account_buying_power`, but does **not** verify that the position can be **safely round-tripped** — i.e., that buying power remains sufficient to close on adverse moves.

For long debit spreads, Alpaca's BP-to-close requirement on a multi-leg combo order ≈ the original entry premium (verified empirically on 2026-05-01 BAC: required $296, available $204 post-entry). When `account_buying_power` is close to `entry_collateral`, the close is mathematically impossible without intervention.

**Empirical proof (2026-05-01):**
- $500 account, $292 BAC entry → $204 OBP remaining
- Force-close attempt rejected 3× with `40310000: insufficient options buying power (required: 296, available: 203.88)`
- Order marked `needs_manual_review`; position open at broker for 5+ hours past intended close
- Real-money exposure during entire window

**Root cause:** sizing computes `min(contracts_by_risk, contracts_by_collateral, max_contracts)` at `sizing_engine.py:106`. No fourth dimension for round-trip safety.

---

## 2. Proposed solution

Add a new dimension `contracts_by_round_trip` to the sizing min(). Compute `estimated_close_bp` per strategy type (Formula table below), require `account_buying_power ≥ entry_collateral + estimated_close_bp × safety_factor`, derive `contracts_by_round_trip` from this constraint, and include it in the `min()`.

When `contracts == 0` because of this constraint, the rejection reason is `round_trip_bp_insufficient`.

**Why Option A over B/C/D/E** (per 2026-05-02 morning diagnostic):
- (A) Round-trip check at sizing — principled, narrow code change, preserves strategy variety
- (B) Restrict to single-leg strategies — too restrictive; severely limits upside
- (C) Accept risk + Option C alert — already shipped via PR #853; defense-in-depth, not a fix
- (D) Shift to credit spreads — depends on regime emission, not a sizing change
- (E) Filter at scanner not sizing — same logic in wrong layer (scanner doesn't know account_buying_power)

---

## 3. New helper: `estimate_close_bp`

**File:** `packages/quantum/services/sizing_engine.py` (collocate with `calculate_sizing`)

```python
def estimate_close_bp(
    strategy: str,
    max_loss_per_contract: float,
    legs: Optional[List[Dict[str, Any]]] = None,
) -> float:
    """Estimate Alpaca's conservative buying-power requirement to close
    one contract of this strategy at adverse-move worst case.

    Modeled empirically against 2026-05-01 BAC observation: Alpaca's
    multi-leg combo order BP gate treats close as ~entry_premium for
    debit spreads. Real close cost is typically much smaller, but the
    gate uses the conservative figure.

    Returns dollars per contract.
    """
```

**Per-strategy formula:**

| Strategy | estimated_close_bp per contract | Reasoning |
|---|---|---|
| `LONG_CALL` | `0` | Sell-to-close; no BP required |
| `LONG_PUT` | `0` | Sell-to-close; no BP required |
| `LONG_CALL_DEBIT_SPREAD` | `max_loss_per_contract` | Buy-to-close short leg; Alpaca treats as ~entry premium |
| `LONG_PUT_DEBIT_SPREAD` | `max_loss_per_contract` | Same shape as call debit |
| `SHORT_CALL_CREDIT_SPREAD` | `0` | BP held aside at entry; close uses reserved capital |
| `SHORT_PUT_CREDIT_SPREAD` | `0` | Same as above |
| `IRON_CONDOR` | `2 × max_loss_per_contract` | Bilateral debit close; both wings consume BP |
| Unknown / default | `max_loss_per_contract` | Conservative fallback — better to skip than stuck-close |

**Edge cases:**
- `max_loss_per_contract <= 0`: return `0` (degenerate; outer sizing will reject anyway)
- `legs` argument unused in v1 (Formula A is premium-based, not quote-based). Reserved for future Formula B if calibration shows the conservative formula wastes too much capacity.
- Strategy field comes from `cand.get("strategy")` at sizing call site — already string, already uppercase per BAC observation (`"LONG_CALL_DEBIT_SPREAD"`).

---

## 4. Sizing engine integration

**File:** `packages/quantum/services/sizing_engine.py`
**Insertion point:** between line 102 (`contracts_by_collateral` computation) and line 106 (final `min()`).

**Current code (line 97-107):**
```python
# 4. Calculate Contracts by Collateral (Buying Power)
if collateral_required_per_contract <= 0:
    contracts_by_collateral = float('inf')
else:
    contracts_by_collateral = math.floor(account_buying_power / collateral_required_per_contract)

# 5. Final Contracts
# min(risk_contracts, collateral_contracts, max_contracts)
contracts = min(contracts_by_risk, contracts_by_collateral, max_contracts)
```

**Proposed additions:**
```python
# 4b. Calculate Contracts by Round-Trip BP (#100 fix)
# Verifies account_buying_power covers BOTH entry collateral AND
# estimated close BP. Without this, sizing accepts trades the account
# can't safely exit (2026-05-01 BAC ghost position incident).
estimated_close_bp = estimate_close_bp(
    strategy=strategy,
    max_loss_per_contract=max_loss_per_contract,
)
round_trip_required_per_contract = (
    collateral_required_per_contract + estimated_close_bp * safety_factor
)
if round_trip_required_per_contract <= 0:
    contracts_by_round_trip = float('inf')
else:
    contracts_by_round_trip = math.floor(
        account_buying_power / round_trip_required_per_contract
    )

# 5. Final Contracts
contracts = min(
    contracts_by_risk,
    contracts_by_collateral,
    contracts_by_round_trip,  # NEW
    max_contracts,
)
```

**Reason field update at line 124-125:**
```python
elif contracts == contracts_by_round_trip and contracts < contracts_by_collateral:
    reason += " (capped by round-trip BP)"
```

**When contracts == 0 due to round-trip:**
```python
elif (
    estimated_close_bp > 0
    and account_buying_power < round_trip_required_per_contract
):
    reason = (
        f"round_trip_bp_insufficient: BP=${account_buying_power:.2f} < "
        f"entry${collateral_required_per_contract:.2f} + "
        f"close${estimated_close_bp:.2f}×{safety_factor}"
    )
```

**New parameters added to `calculate_sizing` signature:**
- `strategy: Optional[str] = None` — passed by `workflow_orchestrator.py:2643` from `cand.get("strategy")`. None falls through to "Unknown / default" formula.
- `safety_factor: float = 1.1` — module-level default; documented at top of `sizing_engine.py`.

**Caller change (`workflow_orchestrator.py:2643`):** add one new kwarg `strategy=cand.get("strategy")`. No other callers (verified via grep).

---

## 5. Safety factor calibration

**Initial value: `safety_factor = 1.1` (10% headroom).**

Reasoning:
- `1.0` (exact match) trusts Formula A precisely. Acceptable as a backstop because Option C alert (PR #853) catches any failure within seconds.
- `1.1` adds 10% cushion against quote staleness, mid-cycle adverse moves, and Alpaca margin-engine surprises that don't match the empirical Formula A model.
- `1.2-1.5` are aggressive and likely reject too much. Defer until live observation.

**Calibration revision plan:**
1. After 30 days of post-#100 trading, query `risk_alerts WHERE alert_type='paper_order_marked_needs_manual_review'`. Each row indicates Option A under-corrected.
2. If 0 occurrences → safety_factor may be too high (over-rejecting). Consider lowering to 1.0.
3. If >0 occurrences → safety_factor too low. Raise to 1.2 and inspect last_error to find Formula A's mismatch shape.
4. Track in `risk_alerts` with `metadata.estimated_close_bp` so post-hoc analysis correlates predicted vs actual.

**Backstop invariant:** even at `safety_factor=1.0` and no fix, the failure mode is "Alpaca rejects close" → Option C alert fires → operator manual close. No silent money loss. Over-rejection symptom is "no live trades" which is operator-visible immediately.

---

## 6. Test plan

### Layer 1 — Source-level structural

```python
# packages/quantum/tests/test_sizing_engine_round_trip_bp.py

def test_estimate_close_bp_function_exists():
    from packages.quantum.services.sizing_engine import estimate_close_bp
    assert callable(estimate_close_bp)

def test_calculate_sizing_accepts_strategy_kwarg():
    # Signature should accept strategy without erroring
    ...

def test_rejection_reason_vocabulary_includes_round_trip():
    src = Path("packages/quantum/services/sizing_engine.py").read_text()
    assert "round_trip_bp_insufficient" in src
```

### Layer 2 — Behavioral (helper)

| Test | strategy | max_loss | Expected estimate |
|---|---|---|---|
| `test_long_call_zero_close_bp` | LONG_CALL | 100 | 0 |
| `test_long_put_zero_close_bp` | LONG_PUT | 100 | 0 |
| `test_long_call_debit_spread_full_close` | LONG_CALL_DEBIT_SPREAD | 296 | 296 |
| `test_long_put_debit_spread_full_close` | LONG_PUT_DEBIT_SPREAD | 200 | 200 |
| `test_short_call_credit_zero_close_bp` | SHORT_CALL_CREDIT_SPREAD | 500 | 0 |
| `test_short_put_credit_zero_close_bp` | SHORT_PUT_CREDIT_SPREAD | 500 | 0 |
| `test_iron_condor_double_close_bp` | IRON_CONDOR | 250 | 500 |
| `test_unknown_strategy_defaults_conservative` | "FOO" | 100 | 100 |
| `test_zero_max_loss_returns_zero` | LONG_CALL_DEBIT_SPREAD | 0 | 0 |

### Layer 3 — Behavioral (sizing integration)

| Test | OBP | entry | close_bp | safety | Expected contracts | Expected reason fragment |
|---|---|---|---|---|---|---|
| `test_sufficient_obp_passes` | 1000 | 296 | 296 | 1.1 | ≥1 | sized normally |
| `test_insufficient_obp_rejected` | 500 | 296 | 296 | 1.1 | 0 | round_trip_bp_insufficient |
| `test_boundary_just_enough` | 622 | 296 | 296 | 1.1 | 1 | 296 + 326 = 622 exactly |
| `test_safety_factor_1_0_more_permissive` | 600 | 296 | 296 | 1.0 | 1 | 296 + 296 = 592 ≤ 600 |
| `test_long_call_unaffected_by_close_bp` | 100 | 50 | 0 | 1.1 | floor(100/50) = 2 | (no round-trip cap fires) |
| `test_credit_spread_unaffected` | 500 | 500 | 0 | 1.1 | 1 | (close_bp=0, no extra constraint) |
| `test_iron_condor_double_constraint` | 1000 | 250 | 500 | 1.1 | floor(1000/(250+550)) = 1 | round-trip dominates |

### Regression analysis (one-shot, pre-merge)

Query historical data to estimate impact:
```sql
WITH base AS (
  SELECT
    strategy,
    (sizing_metadata->>'capital_required')::numeric  AS cap_required,
    -- Formula A: for *_DEBIT_SPREAD, estimated_close_bp = max_loss = cap_required
    (sizing_metadata->>'capital_required')::numeric  AS est_close_bp,
    1.1::numeric                                      AS safety_factor
  FROM trade_suggestions
  WHERE user_id    = '75ee12ad-b119-4f32-aeea-19b4ef55d587'
    AND created_at > NOW() - INTERVAL '30 days'
    AND strategy   LIKE '%DEBIT_SPREAD'
    AND sizing_metadata ? 'capital_required'
),
scored AS (
  SELECT
    strategy,
    cap_required,
    cap_required + est_close_bp * safety_factor      AS round_trip_required
  FROM base
)
SELECT
  strategy,
  COUNT(*)                                                            AS total,
  ROUND(AVG(cap_required), 2)                                         AS avg_cap_required,
  ROUND(AVG(round_trip_required), 2)                                  AS avg_round_trip_required,
  COUNT(*) FILTER (WHERE round_trip_required > 500)                   AS would_reject_at_500,
  COUNT(*) FILTER (WHERE round_trip_required > 650)                   AS would_reject_at_650,
  ROUND(100.0 * COUNT(*) FILTER (WHERE round_trip_required > 500)
        / NULLIF(COUNT(*), 0), 1)                                     AS pct_reject_500,
  ROUND(100.0 * COUNT(*) FILTER (WHERE round_trip_required > 650)
        / NULLIF(COUNT(*), 0), 1)                                     AS pct_reject_650
FROM scored
GROUP BY strategy
ORDER BY total DESC;
```

**Expected outcome:** regression scores rejection rate at both $500 (Friday 2026-05-01's pre-deposit OBP, the BAC-incident baseline) and $650 (Monday 2026-05-04's operative OBP after the 2026-05-02 evening deposit). Per BP-to-close diagnostic, ~50% rejection at $500 is the right shape — those are the unsafe trades the BAC incident exposed. The $650 column quantifies headroom for normal live operation. Document both rates in the implementation PR description so the operator sees impact.

### Regression results (run 2026-05-02)

Query executed against production `trade_suggestions` on 2026-05-02 (Saturday morning, pre-implementation).

**Headline (full 30-day window, all debit-spread suggestions):**

| strategy | total | avg_cap_required | avg_round_trip_required | would_reject_at_500 | would_reject_at_650 | pct_reject_500 | pct_reject_650 |
|---|---:|---:|---:|---:|---:|---:|---:|
| LONG_CALL_DEBIT_SPREAD | 33 | $1589.57 | $3338.10 | 33 | 32 | 100.0% | 97.0% |
| LONG_PUT_DEBIT_SPREAD | 8 | $1790.50 | $3760.05 | 8 | 8 | 100.0% | 100.0% |

**Era-split caveat:** the headline numbers are dominated by 39 pre-2026-04-27 suggestions sized under the prior regime (silent 3% balanced default at `RiskBudgetEngine`, before the tier-aware micro-90% fix landed). Those rows have `cap_required` $1119–$2440 — not representative of forward sizing. Forward-relevant calibration is based on the post-fix subset:

**Forward-representative (post-2026-04-27, N=2 BAC entries):**

| strategy | total | min_cap | avg_cap_required | max_cap | avg_round_trip_required (safety=1.1) | pct_reject_500 | pct_reject_650 |
|---|---:|---:|---:|---:|---:|---:|---:|
| LONG_CALL_DEBIT_SPREAD | 2 | $292 | $301.00 | $310 | $632.10 | 100.0% | 50.0% |

Manual round-trip math at the three candidate calibrations:

| safety | $292 entry → required | $310 entry → required | rejects at $500 | rejects at $650 |
|---|---:|---:|---|---|
| 1.0 | $584 | $620 | both | neither |
| **1.1** | **$613.20** | **$651** | **both** | **only $310 (by $1)** |
| 1.2 | $642.40 | $682 | both | both |

**Calibration decision: ship at `safety_factor = 1.1`.**

Rationale: pct_reject_500=100% confirms calibration would have caught the BAC-class incident at Friday 2026-05-01's pre-deposit OBP — both BAC entries exceed the round-trip threshold. pct_reject_650=50% leaves headroom for ~half of BAC-class candidates under Monday 2026-05-04's $650 OBP, which is sufficient forward breadth (the rejected $310 case exceeds by only $1, naturally accommodated by tomorrow's anticipated win/deposit growth). The 10% safety cushion guards against quote staleness, mid-cycle adverse moves, and Alpaca margin-engine surprises beyond Formula A's empirical model. The 1.1 design default holds; no pre-merge adjustment. N=2 sample is small but unambiguous given the math; ongoing 30-day calibration loop per Section 5 will refine.

Per Section 5's calibration revision plan: if 30-day post-merge observation produces zero `paper_order_marked_needs_manual_review` alerts, consider lowering to 1.0 at next review. If any such alerts fire, raise to 1.2 and inspect `last_error` for Formula A mismatch shape.

---

## 7. Verification path (post-merge)

### Logs to watch

Cycle output should include a new line per candidate that reaches sizing:
```
[Midday] BAC sizing: contracts=1, ...
  round_trip_check: entry $296 + close $326 (1.1×) = $622 required, OBP $1000 → PASS
```

If a candidate is rejected:
```
[Midday] Skipped BAC: round_trip_bp_insufficient: BP=$500.00 < entry$296.00 + close$296.00×1.1
```

### Queries

```sql
-- Did Option A reject candidates today?
SELECT cycle_results
FROM job_runs
WHERE job_name = 'suggestions_open'
  AND started_at::date = CURRENT_DATE
ORDER BY started_at DESC LIMIT 1;
-- Inspect rejection_reasons for "round_trip_bp_insufficient"
```

```sql
-- Option A working as intended: no needs_manual_review writes after merge
SELECT COUNT(*) FROM paper_orders
WHERE status = 'needs_manual_review'
  AND created_at > '<merge-time>';
-- Expected: 0
```

### Alerts

PR #853's `paper_order_marked_needs_manual_review` alert serves as the canary. **If Option A is correctly calibrated, this alert should not fire for sizing-driven failures going forward.** It will still fire for genuine broker errors (auth, network, etc.) — those are a different class.

---

## 8. Risk surface

| Risk | Symptom | Mitigation |
|---|---|---|
| `safety_factor` too high | Unusual jump in `rejection_stats.round_trip_bp_insufficient`; system goes quiet | Log calculation per candidate; calibrate down based on observation |
| `safety_factor` too low | `paper_order_marked_needs_manual_review` alerts continue post-deploy | PR #853 catches it; calibrate up by 0.1 increments |
| Quote staleness | Trade sized OK but rejected at submission | Formula A is premium-based, not quote-based — staleness doesn't apply |
| New strategy type without coverage | Defaults to conservative formula (full max_loss) | Acceptable — better to over-reject novel strategies than stuck-close |
| Live vs shadow account mixing | `account_buying_power` (Alpaca-truth) only meaningful for live_eligible portfolio | Sizing already gets `deployable_capital` from `cash_service` which routes per portfolio. Verify no leakage to shadow paper portfolios in test |
| Iron condor formula wrong | First IC trade hits unexpected close cost | Currently no IC emission in production — non-blocking. Calibrate when first IC appears |
| Empty strategy string at sizing | Defaults conservatively (full max_loss); over-rejects | Acceptable; surfaces as missing strategy field in candidate dict — log warning |

---

## 9. Effort estimate (refined from morning diagnostic)

**Original estimate:** 1-2 days (morning diagnostic)
**Refined estimate:** **~half day**

Reasons for refinement:
- Formula A doesn't need real-time Alpaca quote integration (premium-based, uses already-available `max_loss_per_contract`)
- Single sizing call site (verified via grep — only `workflow_orchestrator.py:2643`)
- Existing test infrastructure is simple parameter-driven (`test_sizing_engine_max_risk.py` pattern)
- No new services, no new schema, no new env vars (safety_factor as default arg is fine for v1)
- The check is one new function + ~10 lines of integration

**Breakdown:**
- ~1 hr: write `estimate_close_bp` helper + per-strategy unit tests (Layer 2)
- ~1 hr: integrate into `calculate_sizing` + integration tests (Layer 3)
- ~30 min: structural tests (Layer 1) + regression query
- ~30 min: PR description + post-merge verification SQL
- ~1 hr: review buffer

---

## 10. Open questions (defer to implementation)

1. ~~Should `safety_factor` be env-configurable? Initial recommendation: no, hardcode at 1.1 with comment. After 30 days observation, decide whether to env-ify.~~ **Resolved 2026-05-02:** `safety_factor = 1.1` hardcoded per regression results above. Env-ification deferred to post-30-day review per Section 5.
2. **Should `estimated_close_bp` be persisted to `sizing_metadata`?** Recommended yes — small disk cost, big calibration value. Add `sizing_metadata.estimated_close_bp` and `sizing_metadata.round_trip_required` for post-hoc analysis.
3. **Iron condor first-fire risk:** the formula `2 × max_loss_per_contract` is theoretical. Until first IC trade, no validation. Document as known calibration item.

---

## Appendix A — Candidate object structure at sizing time

Confirmed via DB query of `trade_suggestions.order_json` for BAC (2026-05-01):
```json
{
  "legs": [
    {"side": "buy",  "symbol": "O:BAC260605C00051000", "quantity": 1},
    {"side": "sell", "symbol": "O:BAC260605C00056000", "quantity": 1}
  ],
  "strategy": "LONG_CALL_DEBIT_SPREAD",
  "contracts": 1,
  "order_type": "multi_leg",
  "underlying": "BAC",
  "limit_price": 3.10
}
```

Note: `order_json.legs[*]` does NOT include `bid`/`ask` — those live elsewhere on the candidate dict in memory at scan time but are not persisted. **For Formula A this is fine** (premium-based, no quote needed).

## Appendix B — Strategy enum (verified via grep)

Production strategies (from `analytics/strategy_selector.py` and `loss_minimizer.py`):
- `LONG_CALL`, `LONG_PUT` (single leg)
- `LONG_CALL_DEBIT_SPREAD`, `LONG_PUT_DEBIT_SPREAD` (debit spreads)
- `SHORT_CALL_CREDIT_SPREAD`, `SHORT_PUT_CREDIT_SPREAD` (credit spreads)
- `IRON_CONDOR` (4-leg neutral)

Recent emission (last 14 days, all users): **100% LONG_CALL_DEBIT_SPREAD** (13/13). Option A's primary impact will be on this strategy until regime shifts produce other types.
