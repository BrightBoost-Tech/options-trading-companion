# Tier Taper — Activation Packet (Lane D)

**Status:** DARK / observe-only. No live sizing consumer. No env flag set.
**Owner decision:** `TIER_CLIFF = CONTINUOUS_TAPER_WITH_HYSTERESIS`.
**Band (ratified):** `TIER_TAPER_BAND = [800, 1000]` — the conservative
never-loosen band (owner-packet-6, owner-ratifications-2026-07-19 §6),
reconciled from the v1 symmetric `[900, 1100]` band by the band-reconciliation
code step (this v2). Proposed ≤ current everywhere (no `would_loosen` region).
**Engine:** `packages/quantum/services/analytics/tier_taper.py`
(`ENGINE_VERSION = "tier_taper.v2"`, PURE, no I/O, no state). v1/v2 evidence
must never be pooled — the version bump partitions the observe evidence.
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

### 2.1 Band (continuous fraction taper) — v2 conservative `[800, 1000]`

Band = **[$800, $1,000]** (`BAND_PCT = 0.20` is the reach BELOW the $1,000
boundary; `BAND_LO = 800`, `BAND_HI = BOUNDARY = 1,000`). The taper lies
**entirely below the boundary** and lands exactly on small's 0.85 at
$1,000, so it is **proposed ≤ current everywhere** (no `would_loosen`
region — §4.6). Ratified over the v1 symmetric ±10% `[900, 1100]` band
because in learning-mode the symmetric band's above-boundary `would_loosen`
region buys nothing the owner asked for. Inside the band the tier fractions
interpolate **linearly** (C0-continuous) by `t = (equity − 800) / 200 ∈
[0, 1]`:

- `envelope_pct(e) = interp(0.90, 0.85, t)`
- `per_trade_ceiling_pct(e) = interp(0.90, 0.36, t)`

Outside the band the fractions equal the raw-cliff values **exactly**
(invariant §4.3).

### 2.2 Hysteresis (discrete tier state) — v2 one-sided gap `[950, 1000]`

The continuous fraction taper is a pure function of equity (no path
dependence → no dollar thrash). Only the **discrete tier state**
(concurrent count `1↔4`, tier label) is hysteretic, via a Schmitt trigger.
For the conservative band the boundary IS the band's upper edge, so the
Schmitt gap is **one-sided**, sitting entirely below the boundary — inner
band **[$950, $1,000]** (`HYST_LO = 950`, `HYST_HI = BOUNDARY = 1,000`,
`HYST_PCT = 0.05` below-boundary reach):

```
state machine  (state = last effective tier ∈ {micro, small})
────────────────────────────────────────────────────────────
prev = micro :  equity ≥ $1,000  → small  (flip_to_small)   # AT the cliff
                else               → micro  (hold_micro)
prev = small :  equity ≤ $950    → micro  (flip_to_micro)
                else               → small  (hold_small)
prev = None / invalid / stale :  FAIL-CLOSED seed from the raw cliff
                (equity ≥ $1,000 → small, else micro)   (cold_start_raw_seed)
```

From `micro` the state flips to `small` only at the raw cliff ($1,000) — it
**never enters the looser small state (4 concurrent) below the boundary**,
so hysteresis introduces no downward-risk loosening (§4.6). From `small` it
holds down to $950 (a $50 anti-thrash gap) so a `$999↔$1,001` oscillation
flips at most ONCE then sticks. `HYST_LO` ($950) sits strictly inside the
band ($950 > $800); the upper edge equals the boundary, so **outside the
taper band the discrete state matches the raw cliff exactly**.

### 2.3 Versioning

`ENGINE_VERSION` bumps on ANY change to a band edge, hysteresis edge, tier
anchor, or interpolation/state-machine semantics. Every emitted payload
carries it, so a downstream reader can attribute an observation to an exact
build. **v2 moved the band `[900,1100]`→`[800,1000]` and `HYST_HI`
$1,050→$1,000 — v1 and v2 evidence have different band/state semantics and
MUST NOT be pooled; `monday_evidence_reader.build_tier_taper` partitions
every verdict tally by `engine_version`.** Tier anchors and the regime map
are **drift-guarded** by `test_tier_taper.py::TestDriftGuards` against
`SmallAccountCompounder.TIERS` and `portfolio_allocator` — a silent
divergence fails the test.

---

## 3. Before / after matrix (regime = normal)

Generated from the engine (`tier_taper.decide`). Dollars are
`equity × pct × regime_mult`.

| equity | raw_tier | in_band | t | cur env $ | **prop env $** | cur ptc $ | prop ptc $ | verdict |
|---:|---|:--:|---:|---:|---:|---:|---:|---|
| 700 | micro | no | 0.000 | 630.00 | **630.00** | 630.00 | 630.00 | identical |
| 800 | micro | no | 0.000 | 720.00 | **720.00** | 720.00 | 720.00 | identical |
| 850 | micro | yes | 0.250 | 765.00 | **754.38** | 765.00 | 650.25 | would_tighten |
| 900 | micro | yes | 0.500 | 810.00 | **787.50** | 810.00 | 567.00 | would_tighten |
| 950 | micro | yes | 0.750 | 855.00 | **819.38** | 855.00 | 470.25 | would_tighten |
| 999 | micro | yes | 0.995 | 899.10 | **849.40** | 899.10 | 362.34 | would_tighten |
| 1000 | small | no | 1.000 | 850.00 | **850.00** | 360.00 | 360.00 | identical |
| 1001 | small | no | 1.000 | 850.85 | **850.85** | 360.36 | 360.36 | identical |
| 1500 | small | no | 1.000 | 1275.00 | **1275.00** | 540.00 | 540.00 | identical |
| 4900 | small | no | 1.000 | 4165.00 | **4165.00** | 1764.00 | 1764.00 | identical |
| 5100 | standard | no | 1.000 | n/a | **n/a** | n/a | n/a | not_applicable |

Reading it:

- **Outside the band ($700, $800, $1,000+): proposed = current exactly** —
  current behavior preserved byte-for-byte. The taper's upper edge IS the
  boundary, so $1,000 and above already read the pure small anchor.
- **In-band, below the boundary ($850…$999): would_tighten** — the taper
  deploys *less* than raw micro (0.90 ramping down toward small's 0.85).
  Safe direction, at EVERY in-band equity.
- **No `would_loosen` row anywhere** — this is the conservative-band
  guarantee (§4.6). The taper ramps micro's 0.90 DOWN to small's 0.85 and
  lands on it exactly at $1,000; it never deploys more than the raw system
  at any equity. (v1's symmetric band had a bounded `would_loosen` region
  above $1,000; v2 removes it.)
- **The anti-thrash win:** raw `D(999)=$899.10` vs `D(1,001)=$850.85` = a
  ~$48 cliff. Tapered `D(999)=$849.40` vs `D(1,001)=$850.85` = a ~**$1.45**
  difference. A `$999↔$1,001` wobble is now a rounding error, not a regime
  flip — and the envelope is continuous through the cliff.
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
- `e ≤ 800`: constant `0.90` → `D = 0.90·m·e`, slope `0.90·m > 0`.
- `e ≥ 1,000`: constant `0.85` → `D = 0.85·m·e`, slope `0.85·m > 0`.
- `800 < e < 1,000`: `envelope_pct(e) = 0.90 + (e−800)/200·(0.85−0.90)`
  `= 0.90 − 0.00025·(e−800)`. Then
  `D(e) = m·e·(0.90 − 0.00025·(e−800))`, so
  `D'(e)/m = 0.90 − 0.00025·(e−800) − 0.00025·e
           = envelope_pct(e) − 0.00025·e`.
  This is minimized at the largest `e = 1,000`:
  `D'(1,000)/m = 0.85 − 0.00025·1,000 = 0.85 − 0.25 = 0.60 > 0`.
- **Continuity at the joins:** `envelope_pct(800) = 0.90` and
  `envelope_pct(1,000) = 0.85` match the constant pieces → `D` is
  continuous, and every piece has positive slope ⇒ `D` monotone
  non-decreasing everywhere. Endpoints: `D(800)=720`, `D(1,000)=850`. ∎

**The raw cliff VIOLATES this** and the taper removes the violation:
`raw D(999) = $899.10 > raw D(1,001) = $850.85` (raw D *drops* as equity
rises past $1,000 — equivalently, D *rises* as equity *falls*, the exact
"increases dollar risk because equity fell" failure). Tapered
`D(999) = $849.40 ≤ D(1,001) = $850.85`.

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
the pure small side (`e ≥ $1,000`).

### 4.3 Outside-band identity

For `e ∉ (800, 1,000)` the proposed params equal the raw params exactly
(pct, dollars, per-trade, max_concurrent) — current behavior preserved
byte-for-byte (`test_tier_taper.py::TestOutsideBandIdentity`,
`test_edge_params_equal_raw`).

### 4.4 Per-trade ceiling is a CAP (monotone in fraction)

`per_trade_ceiling_pct(e)` is monotonically NON-INCREASING in `e`
(0.90 → 0.36) — the cap tightens in fraction terms as equity grows, the
safe direction. Its DOLLAR value is deliberately NOT a monotonicity target:
the two tiers' raw per-trade ceilings are dollar-inverted at the band edges
($720 at $800 micro vs $360 at $1,000 small), so **no** edge-preserving,
equity-continuous taper can be both edge-preserving AND per-trade-dollar
monotone. The taper replaces the raw discontinuous per-trade JUMP with a
continuous ramp bounded between the two tiers' caps — it never loosens
beyond either tier's own ceiling, preserving the intended
aggressive-micro / diversified-small distinction.

### 4.5 Fail-closed hysteresis seed

Missing / stale / unreadable prior state → the effective tier state seeds
from the RAW cliff (`equity ≥ $1,000 → small`, else `micro`) — the current
behavior, never a loosened default (`test_tier_taper.py::TestHysteresis`).

### 4.6 Never-loosen (v2 conservative band)

`proposed envelope_pct ≤ raw envelope_pct` for ALL equity — the taper lies
entirely below the boundary and lands on small's 0.85 exactly at $1,000, so
the `verdict` is only ever `would_tighten` / `identical` / `not_applicable`,
NEVER `would_loosen` (`test_tier_taper.py::TestVerdict::
test_never_loosens_anywhere`, `TestConservativeBand`). The discrete state
never enters `small` (4 concurrent) below the cliff (§2.2), so max_concurrent
never loosens below the boundary either. This is the property that
distinguishes v2 from v1's symmetric band.

---

## 5. Hysteresis walk-through

State threads across cycles (in DARK it is stateless — see §7). Both
directions, exercised in `test_tier_taper.py::TestHysteresis`:

**Rising** (seed micro at $820, equity climbs — v2 holds micro across the
WHOLE band until the raw cliff, never entering small below $1,000):

| cycle | equity | prev | decision | state | max_conc |
|---:|---:|---|---|---|---:|
| 1 | 820 | None | cold_start_raw_seed | micro | 1 |
| 2 | 900 | micro | hold_micro | micro | 1 |
| 3 | 980 | micro | hold_micro | micro | 1 |
| 4 | 999 | micro | hold_micro | micro | 1 |
| 5 | 1000 | micro | **flip_to_small** | small | 4 |
| 6 | 1080 | small | hold_small | small | 4 |

**Falling** (seed small at $1,080, equity drops — holds small down to $950):

| cycle | equity | prev | decision | state | max_conc |
|---:|---:|---|---|---|---:|
| 1 | 1080 | None | cold_start_raw_seed | small | 4 |
| 2 | 1010 | small | hold_small | small | 4 |
| 3 | 990 | small | hold_small | small | 4 |
| 4 | 951 | small | hold_small | small | 4 |
| 5 | 950 | small | **flip_to_micro** | micro | 1 |
| 6 | 920 | micro | hold_micro | micro | 1 |

**Anti-thrash (v2 one-sided gap):** a `$999↔$1,001` oscillation flips
micro→small ONCE on first crossing of the $1,000 cliff, then STICKS small
($999 > `HYST_LO` $950) — no 1↔4 thrash on subsequent wobbles. A sub-cliff
wobble (e.g. `$940↔$960`) from micro never flips up at all — the taper
never enters small below the boundary (`test_hysteresis_gap_prevents_thrash`,
`test_hysteresis_at_both_band_edges`).

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
   predicts, and that `engine_version` is the reviewed build
   (`tier_taper.v2`). **Observe ONLY v2 rows** — the reader partitions by
   `engine_version` so a residual v1 row from before the reconciliation is
   never pooled into the v2 window.
2. **Band already reconciled to the ratified `[800, 1000]`** — this v2 build
   IS the conservative never-loosen band: proposed ≤ current everywhere
   (no `would_loosen` row), `$1,000+` lands exactly on small's 0.85,
   endpoints 720 → 850 monotone. No further band decision is pending; the
   only remaining owner action is arming the flag (steps 4–6).
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
