# Tier Taper — Activation Packet (Lane D)

**Status:** DARK / observe-only. No live sizing consumer. No env flag set.
**Owner decision:** `TIER_CLIFF = CONTINUOUS_TAPER_WITH_HYSTERESIS`.
**Engine:** `packages/quantum/services/analytics/tier_taper.py`
(`ENGINE_VERSION = "tier_taper.v1"`, PURE, no I/O, no state).
**Wire-in (DARK):** `workflow_orchestrator.run_midday_cycle` — computes
`tier_taper.observe(...)` after the micro fast-skip and emits it to
`job_runs.result.cycle_metadata.tier_taper`. The live sizing path is
byte-identical (proven; see §6).

This packet is the evidence the owner reviews **before** flipping the kill
switch. It documents the engine (band, state machine, version), the
monotonicity proof, the before/after matrix, the hysteresis walk-through,
the rollback/kill-switch design, and the go-live checklist.

---

## 1. Problem — the $1,000 cliff

`SmallAccountCompounder.get_tier` (small_account_compounder.py) has HARD
cliffs at $1,000 and $5,000. Lane D targets the **$1,000 micro↔small
cliff**. The two tiers' effective sizing parameters (verified in code):

| Parameter | micro (`equity < $1,000`) | small (`$1,000 ≤ equity < $5,000`) | source |
|---|---|---|---|
| total deployable envelope | `0.90 × regime` | `0.85 × regime` | RBE `compute` micro path (`× 0.90 × regime`); PortfolioAllocator `GLOBAL_ENVELOPE_PCT = 0.85` |
| per-trade ceiling | `0.90` (one trade takes the slot) | `0.36` | RBE micro `max_risk_trade`; `PER_TRADE_CEILING_PCT = 0.36` |
| max concurrent | `1` | `4` | `CapitalTier.max_trades`; `MAX_CONCURRENT_POSITIONS = 4` |

At exactly $1,000 all three jump discontinuously. Total deployable
**dollars** actually DROP crossing the boundary upward — `D(999) = 999 ×
0.90 = $899.10` vs `D(1,001) = 1,001 × 0.85 = $850.85`. A `$999↔$1,001`
oscillation therefore thrashes: the envelope steps ~$48 and the concurrent
count flips `1↔4` each time equity wobbles across the line.

---

## 2. Engine design

### 2.1 Band (continuous fraction taper)

Band = **±10% around $1,000 → [$900, $1,100]** (`BAND_PCT = 0.10`).
Derivation: 10% of $1,000 ($100) is roughly one good-day/bad-day P&L swing
at this account size, so an equity oscillation contained inside a single
session's range should not see a discontinuous change in deployable risk.
Inside the band the tier fractions interpolate **linearly** (C0-continuous)
by `t = (equity − 900) / 200 ∈ [0, 1]`:

- `envelope_pct(e) = interp(0.90, 0.85, t)`
- `per_trade_ceiling_pct(e) = interp(0.90, 0.36, t)`

Outside the band the fractions equal the raw-cliff values **exactly**
(invariant §4.3).

### 2.2 Hysteresis (discrete tier state)

The continuous fraction taper is a pure function of equity (no path
dependence → no dollar thrash). Only the **discrete tier state**
(concurrent count `1↔4`, tier label) is hysteretic, via a Schmitt trigger
with an inner band **[$950, $1,050]** (`HYST_PCT = 0.05`):

```
state machine  (state = last effective tier ∈ {micro, small})
────────────────────────────────────────────────────────────
prev = micro :  equity ≥ $1,050  → small  (flip_to_small)
                else               → micro  (hold_micro)
prev = small :  equity ≤ $950    → micro  (flip_to_micro)
                else               → small  (hold_small)
prev = None / invalid / stale :  FAIL-CLOSED seed from the raw cliff
                (equity ≥ $1,000 → small, else micro)   (cold_start_raw_seed)
```

The inner band sits strictly inside the taper band ($950 > $900,
$1,050 < $1,100) so **outside the taper band the discrete state matches
the raw cliff exactly**. Entering the band from below holds the lower tier
until `$1,050` is crossed; entering from above holds the upper tier until
`$950` is crossed — deterministic, both directions.

### 2.3 Versioning

`ENGINE_VERSION` bumps on ANY change to a band edge, hysteresis edge, tier
anchor, or interpolation/state-machine semantics. Every emitted payload
carries it, so a downstream reader can attribute an observation to an exact
build. Tier anchors and the regime map are **drift-guarded** by
`test_tier_taper.py::TestDriftGuards` against
`SmallAccountCompounder.TIERS` and `portfolio_allocator` — a silent
divergence fails the test.

---

## 3. Before / after matrix (regime = normal)

Generated from the engine (`tier_taper.decide`). Dollars are
`equity × pct × regime_mult`.

| equity | raw_tier | in_band | t | cur env $ | **prop env $** | cur ptc $ | prop ptc $ | verdict |
|---:|---|:--:|---:|---:|---:|---:|---:|---|
| 800 | micro | no | 0.000 | 720.00 | **720.00** | 720.00 | 720.00 | identical |
| 950 | micro | yes | 0.250 | 855.00 | **843.12** | 855.00 | 726.75 | would_tighten |
| 999 | micro | yes | 0.495 | 899.10 | **874.37** | 899.10 | 632.07 | would_tighten |
| 1001 | small | yes | 0.505 | 850.85 | **875.62** | 360.36 | 627.93 | would_loosen |
| 1050 | small | yes | 0.750 | 892.50 | **905.62** | 378.00 | 519.75 | would_loosen |
| 1500 | small | no | 1.000 | 1275.00 | **1275.00** | 540.00 | 540.00 | identical |
| 4900 | small | no | 1.000 | 4165.00 | **4165.00** | 1764.00 | 1764.00 | identical |
| 5100 | standard | no | 1.000 | n/a | **n/a** | n/a | n/a | not_applicable |

Reading it:

- **Outside the band ($800, $1,500, $4,900): proposed = current exactly** —
  current behavior preserved byte-for-byte.
- **Below $1,000 in-band ($950, $999): would_tighten** — the taper deploys
  *less* than raw micro (0.90 ramping down). Safe direction.
- **Above $1,000 in-band ($1,001, $1,050): would_loosen** — the taper
  deploys slightly *more* than raw small (0.85), bounded by micro's own
  0.90 cap. This is the cost of a symmetric transition: instead of the raw
  system snapping from 0.90 to 0.85 at $1,000, the taper ramps, so just
  above the boundary the fraction is still on its way down from 0.90. It
  NEVER exceeds 0.90 (micro's existing cap) — no new ceiling is introduced.
- **The anti-thrash win:** raw `D(999)=$899.10` vs `D(1,001)=$850.85` = a
  ~$48 cliff. Tapered `D(999)=$874.37` vs `D(1,001)=$875.62` = a ~**$1.25**
  difference. A `$999↔$1,001` wobble is now a rounding error, not a regime
  flip.
- **Standard tier ($5,100) is out of Lane D scope** — the taper never
  activates there; `verdict = not_applicable`.

Shock regime (`regime_mult = 0.5`) scales every dollar figure by exactly
0.5 — the SHOCK ceiling is applied unchanged (§4.2).

---

## 4. Invariants & proofs

### 4.1 Monotonicity — the one the owner asked to prove

**Claim.** For a fixed regime multiplier `m > 0`, the tapered TOTAL
deployable dollars `D(e) = e · envelope_pct(e) · m` is monotonically
NON-DECREASING in equity `e` over the whole domain. A drop in equity never
increases total deployable risk.

**Proof (piecewise).** `envelope_pct` is:
- `e ≤ 900`: constant `0.90` → `D = 0.90·m·e`, slope `0.90·m > 0`.
- `e ≥ 1,100`: constant `0.85` → `D = 0.85·m·e`, slope `0.85·m > 0`.
- `900 < e < 1,100`: `envelope_pct(e) = 0.90 + (e−900)/200·(0.85−0.90)`
  `= 0.90 − 0.00025·(e−900)`. Then
  `D(e) = m·e·(0.90 − 0.00025·(e−900))`, so
  `D'(e)/m = 0.90 − 0.00025·(e−900) − 0.00025·e
           = envelope_pct(e) − 0.00025·e`.
  This is minimized at the largest `e = 1,100`:
  `D'(1,100)/m = 0.85 − 0.00025·1,100 = 0.85 − 0.275 = 0.575 > 0`.
- **Continuity at the joins:** `envelope_pct(900) = 0.90` and
  `envelope_pct(1,100) = 0.85` match the constant pieces → `D` is
  continuous, and every piece has positive slope ⇒ `D` monotone
  non-decreasing everywhere. ∎

**The raw cliff VIOLATES this** and the taper removes the violation:
`raw D(999) = $899.10 > raw D(1,001) = $850.85` (raw D *drops* as equity
rises past $1,000 — equivalently, D *rises* as equity *falls*, the exact
"increases dollar risk because equity fell" failure). Tapered
`D(999) = $874.37 ≤ D(1,001) = $875.62`.

**Numeric corroboration** (`test_tier_taper.py::TestMonotonicity`, and the
build log): a dense sweep `$600.0 … $1,300.1` step `$0.1` yields **0**
monotonicity violations for `normal`, `shock`, `elevated`, `suppressed`.

### 4.2 SHOCK ceiling retained (unchanged)

`envelope_pct(e) ∈ [0.85, 0.90]` for all `e` — it never exceeds the MAX of
the two adjacent tier caps (micro's own 0.90). The regime multiplier
(`shock = 0.5`, `elevated = 0.8`, …) is applied ON TOP, unchanged:
`prop_env_shock(e) == prop_env_normal(e) × 0.5` exactly
(`test_tier_taper.py::TestShockCeiling`). The portfolio-wide 0.85×regime
allocator envelope and the 0.36 per-trade ceiling are retained exactly on
the pure small side (`e ≥ $1,100`).

### 4.3 Outside-band identity

For `e ∉ (900, 1,100)` the proposed params equal the raw params exactly
(pct, dollars, per-trade, max_concurrent) — current behavior preserved
byte-for-byte (`test_tier_taper.py::TestOutsideBandIdentity`,
`test_edge_params_equal_raw`).

### 4.4 Per-trade ceiling is a CAP (monotone in fraction)

`per_trade_ceiling_pct(e)` is monotonically NON-INCREASING in `e`
(0.90 → 0.36) — the cap tightens in fraction terms as equity grows, the
safe direction. Its DOLLAR value is deliberately NOT a monotonicity target:
the two tiers' raw per-trade ceilings are dollar-inverted at the band edges
($810 at $900 micro vs $396 at $1,100 small), so **no** edge-preserving,
equity-continuous taper can be both edge-preserving AND per-trade-dollar
monotone. The taper replaces the raw discontinuous per-trade JUMP with a
continuous ramp bounded between the two tiers' caps — it never loosens
beyond either tier's own ceiling, preserving the intended
aggressive-micro / diversified-small distinction.

### 4.5 Fail-closed hysteresis seed

Missing / stale / unreadable prior state → the effective tier state seeds
from the RAW cliff (`equity ≥ $1,000 → small`, else `micro`) — the current
behavior, never a loosened default (`test_tier_taper.py::TestHysteresis`).

---

## 5. Hysteresis walk-through

State threads across cycles (in DARK it is stateless — see §7). Both
directions, exercised in `test_tier_taper.py::TestHysteresis`:

**Rising** (seed micro at $920, equity climbs):

| cycle | equity | prev | decision | state | max_conc |
|---:|---:|---|---|---|---:|
| 1 | 920 | None | cold_start_raw_seed | micro | 1 |
| 2 | 980 | micro | hold_micro | micro | 1 |
| 3 | 1010 | micro | hold_micro | micro | 1 |
| 4 | 1049 | micro | hold_micro | micro | 1 |
| 5 | 1050 | micro | **flip_to_small** | small | 4 |
| 6 | 1080 | small | hold_small | small | 4 |

**Falling** (seed small at $1,080, equity drops):

| cycle | equity | prev | decision | state | max_conc |
|---:|---:|---|---|---|---:|
| 1 | 1080 | None | cold_start_raw_seed | small | 4 |
| 2 | 1010 | small | hold_small | small | 4 |
| 3 | 990 | small | hold_small | small | 4 |
| 4 | 951 | small | hold_small | small | 4 |
| 5 | 950 | small | **flip_to_micro** | micro | 1 |
| 6 | 920 | micro | hold_micro | micro | 1 |

**Anti-thrash:** a `$999↔$1,001` oscillation with memory NEVER flips — both
values sit inside the [$950, $1,050] hold band
(`test_hysteresis_gap_prevents_thrash`).

---

## 6. DARK dual-run — live path byte-identical

Wire-in: `run_midday_cycle` calls `tier_taper.observe(deployable_capital,
regime, previous_state=None)` after the micro fast-skip and stashes the
payload into `cycle_metadata.tier_taper` (additive; absent when the sink is
None so legacy readers are byte-identical). It also emits one `[TIER_TAPER]`
INFO line per cycle.

**Why the live path cannot change:**
- `observe` takes only primitives (equity float, regime string) and returns
  a fresh dict. It never receives or returns candidates / `sizing_vars` /
  allocation output, and does no I/O.
- The sizing chain (`PortfolioAllocator.allocate` →
  `_allocator_allocated_budget` → `calculate_variable_sizing(allocation_hint
  =…)`) is untouched.

**Proof** (`test_tier_taper_dual_run_route.py`, driving the REAL production
functions and asserting on OUTPUT):
- `TestLivePathByteIdentical` reproduces the exact `run_midday_cycle` sizing
  seam and asserts the per-candidate `risk_budget` list is identical with
  vs. without the interleaved `observe` call, at $800 / $999 / $1,001 /
  $1,500; and that `observe` mutates no candidate dict.
- `TestPayloadEmittedAdditively` drives the real `_build_cycle_metadata`:
  byte-identical (no `tier_taper` key) without the kwarg, well-formed
  payload with it, and `tier_taper=None` (fail-path) stays additive-absent.

The sink is `job_runs.result.cycle_metadata.tier_taper` — a per-cycle,
already-persisted, authoritative DB row of record. **No migration** (§7).

---

## 7. State durability & migration decision

**Migration needed: NO.** Adjudication (owner's "prefer stateless"):

- The continuous fraction taper is a pure function of equity → no state.
- The only path-dependent quantity is the discrete hysteresis state. In
  DARK it is **stateless**: `previous_state=None` each cycle → the engine
  fail-closes to the raw-cliff seed. The DARK payload's
  `hysteresis_decision = "cold_start_raw_seed"` and
  `previous_tier_state = null` honestly reflect this.
- Cross-cycle hysteresis durability, when activated, is **derived from data
  already in the DB**: the prior decision lives in
  `job_runs.result.cycle_metadata.tier_taper.effective_tier_state`. The
  pure helper `tier_taper.extract_previous_tier_state(job_run_result)` (unit
  tested) reads it; activation threads it in one line. No new table, no new
  column, no migration either way.

---

## 8. Rollback / kill-switch design (for activation — NOT set here)

Per §3 of the project doctrine, activation is a **behavioral / loosening**
change → explicit opt-in, default-OFF, fails SAFE:

- Flag `ENABLE_LIVE_TIER_TAPER` — requires exactly `=1` to arm the live
  sizing consumer. Absent / empty / any non-`1` value → the current
  hard-cliff `get_tier` path (legacy behavior). A non-empty non-truthy
  value logs an explicit WARNING.
- The DARK dual-run (this PR) has **no flag** — it is observe-only and
  cannot alter sizing, so there is nothing to gate.
- Rollback after activation = set `ENABLE_LIVE_TIER_TAPER` to unset/`0` on
  BOTH workers and recycle → instant revert to the raw cliff. No data
  migration to undo (the payload is additive observability).

---

## 9. Go-live checklist (owner)

Before flipping `ENABLE_LIVE_TIER_TAPER=1`:

1. **Observe the DARK payload** across ≥1–2 weeks of midday cycles: read
   `job_runs.result.cycle_metadata.tier_taper` — confirm `verdict`,
   `taper_fraction`, and `effective_tier_state` track equity as this packet
   predicts, and that `engine_version` is the reviewed build.
2. **Confirm the loosening band is acceptable** — the `would_loosen` rows
   ($1,000–$1,100) deploy up to micro's 0.90 cap. If the owner prefers a
   NEVER-loosen taper, adopt the conservative alternative band **[$800,
   $1,000]** (taper entirely below the boundary): proposed ≤ current
   everywhere, `$1,000+` lands exactly on small's 0.85. This is a one-line
   band change + `ENGINE_VERSION` bump; the monotonicity proof and tests
   carry over (endpoints 720 → 850, still monotone).
3. **Confirm hysteresis durability wiring** for the live consumer (thread
   `extract_previous_tier_state` from the prior `job_run`, or in-process
   caching) — recycles reset in-process state, so the DB-derived path is
   preferred.
4. **Build a live sizing consumer** that reads the tapered envelope /
   per-trade ceiling / max_concurrent and feeds them where `get_tier`'s
   values feed today — gated behind the flag, fail-closed to the cliff.
5. **Pre-stage the env** (`skip_deploys`) per the deploy doctrine so the
   arming merge is a single recycle; read the flag back on both workers.
6. **No market-hours activation** — arm after 20:00Z, verify one clean
   midday cycle in DARK-then-armed on the next trading day.

---

## 10. Files & tests

- Engine: `packages/quantum/services/analytics/tier_taper.py`
- Wire-in: `packages/quantum/services/workflow_orchestrator.py`
  (`run_midday_cycle`, `_build_cycle_metadata` additive `tier_taper` kwarg)
- Tests: `packages/quantum/tests/test_tier_taper.py` (pure battery),
  `packages/quantum/tests/test_tier_taper_dual_run_route.py` (route byte-pin
  + additive emission)
