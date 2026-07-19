# Owner Packet 6 — Tier taper activation band

> **RATIFIED 2026-07-19** → see owner-ratifications-2026-07-19.md

**Decision:** choose the taper band for the $1,000 micro↔small cliff before
`ENABLE_LIVE_TIER_TAPER=1` is ever flipped — the **symmetric ±10% [$900,
$1,100]** band (shipped DARK, #1283) or the **conservative never-loosen
[$800, $1,000]** band. **This packet executes nothing** — the taper is DARK /
observe-only (no live sizing consumer, no env flag in live code). Full engine,
proofs, and before/after matrix: `docs/specs/tier_taper_activation_packet.md`.

**Recommendation:** the **conservative `[$800, $1,000]`** band. It is
proposed ≤ current everywhere (never loosens), lands exactly on small's 0.85
at $1,000, keeps the monotonicity proof and tests, and is a one-line band
change + `ENGINE_VERSION` bump. In learning-mode (correctness > deployment),
the ±10% band's small `would_loosen` region above $1,000 buys nothing the
owner has asked for.

---

## 1. Problem (recap)

`SmallAccountCompounder.get_tier` has a HARD cliff at $1,000: crossing upward,
total deployable dollars actually **drop** (`D(999)=$899.10` vs
`D(1,001)=$850.85`) and max-concurrent flips `1↔4`. A `$999↔$1,001` wobble
thrashes the envelope ~$48 and the tier state each time
(`tier_taper_activation_packet.md` §1).

## 2. The two rollout options

### Option A — symmetric ±10% band `[$900, $1,100]` (shipped DARK, `BAND_PCT=0.10`)

- Fractions interpolate linearly across the band; discrete tier state is
  hysteretic via a Schmitt trigger inner band `[$950, $1,050]`
  (`HYST_PCT=0.05`).
- **Anti-thrash:** tapered `D(999)=$874.37` vs `D(1,001)=$875.62` — a ~$1.25
  difference vs the raw ~$48 cliff (§3 matrix).
- **Cost:** the `[$1,000, $1,100]` in-band rows are **`would_loosen`** — the
  taper deploys slightly *more* than raw small (0.85), bounded by micro's own
  0.90 cap (never a new ceiling, §3). This is the price of a symmetric ramp.

### Option B — conservative never-loosen band `[$800, $1,000]` (recommended)

- Taper lies **entirely below** the boundary; `$1,000+` lands exactly on
  small's 0.85. **Proposed ≤ current everywhere** — no `would_loosen` row.
- **Cost:** one-line band change + `ENGINE_VERSION` bump; the monotonicity
  proof and tests carry over (endpoints 720 → 850, still monotone —
  `tier_taper_activation_packet.md` §9 step 2).

## 3. Invariants that hold under BOTH bands (verified in the engine)

| invariant | status | source |
|---|---|---|
| **monotonicity** — `D(e)=e·envelope_pct(e)·m` non-decreasing in equity; a drop in equity never increases deployable risk | proven piecewise; dense sweep $600→$1,300 step $0.1 = **0 violations** across normal/shock/elevated/suppressed | §4.1, `test_tier_taper.py::TestMonotonicity` |
| **SHOCK invariant** — regime multiplier applied on top, unchanged; `prop_env_shock == prop_env_normal × 0.5` exactly | held | §4.2, `TestShockCeiling` |
| **outside-band identity** — outside the band proposed = raw byte-for-byte | held | §4.3, `TestOutsideBandIdentity` |
| **fail-closed hysteresis seed** — missing/stale prior state seeds from the RAW cliff, never a loosened default | held | §4.5, `TestHysteresis` |

**No-downward-risk-increase** is exactly the monotonicity guarantee — it holds
for both bands. Option B additionally guarantees **no-upward-loosening** at any
equity.

## 4. Hysteresis verification

The discrete tier state (`1↔4` concurrent) is the only path-dependent
quantity; the fraction taper is a pure function of equity (no dollar thrash).
The Schmitt hold band `[$950, $1,050]` means a `$999↔$1,001` oscillation with
memory **never flips** (`test_hysteresis_gap_prevents_thrash`; rising/falling
walk-throughs, §5). Under Option B the inner band would move with the outer
band; the same never-flip property is re-verified at activation. In DARK the
state is stateless (`previous_state=None` each cycle → raw-cliff seed), honestly
reflected as `cold_start_raw_seed` / `previous_tier_state=null` (§7).

## 5. Observation duration (dark dual-run before arming)

Read `job_runs.result.cycle_metadata.tier_taper` across **≥1–2 weeks of midday
cycles** (`tier_taper_activation_packet.md` §9 step 1): confirm `verdict`,
`taper_fraction`, and `effective_tier_state` track equity as the before/after
matrix predicts, and `engine_version` is the reviewed build. The DARK dual-run
is proven byte-identical to the live sizing path
(`test_tier_taper_dual_run_route.py`, driving the real `run_midday_cycle`
seam + `_build_cycle_metadata`), so observing costs nothing.

## 6. Flag plan + rollback

- Activation is behavioral/loosening → **`ENABLE_LIVE_TIER_TAPER`**, strict
  **`=1`**, default-OFF. Absent/empty/any non-`1` → the current hard-cliff
  `get_tier` path (fail-safe); a non-empty non-truthy value logs an explicit
  WARNING (doctrine §3).
- The DARK dual-run has **no flag** (it cannot alter sizing).
- **Rollback:** unset/`0` `ENABLE_LIVE_TIER_TAPER` on both workers + recycle →
  instant revert to the raw cliff. No data migration to undo (payload is
  additive observability). **No migration either way** — hysteresis durability,
  when armed, derives from `job_runs.result.cycle_metadata.tier_taper.
  effective_tier_state` via `extract_previous_tier_state` (§7).

## 7. Before/after matrix pointer

The full matrix (equity, raw_tier, in_band, `t`, current vs proposed envelope
$ and per-trade $, verdict) is in `docs/specs/tier_taper_activation_packet.md`
§3 — including the `would_loosen` rows that distinguish the two bands and the
conservative-band endpoints in §9 step 2.

## 8. Why B over A

The owner's stated frame is never-loosen and correctness-first. Option A's only
advantage is symmetric smoothness above $1,000, which requires a bounded
`would_loosen` region; Option B removes the cliff's thrash **and** the
downward-monotonicity violation while never deploying more than the raw system
anywhere. If the owner later wants the symmetric smoothness, A is a one-line
band widen + version bump from B — B is the strictly safer first activation.

---

## APPROVAL TOKEN

> **`TIER_TAPER_BAND=[800,1000]`** (conservative never-loosen) — selects the
> taper band that is proposed ≤ current everywhere, after ≥1–2 weeks of DARK
> `cycle_metadata.tier_taper` observation confirm the payload tracks equity as
> the matrix predicts. *(Alternative:
> `TIER_TAPER_BAND=[900,1100]` symmetric ±10%, the shipped DARK band, accepting
> the bounded `would_loosen` region ≤ micro's 0.90 cap.)* Selecting the band
> does not arm the taper — `ENABLE_LIVE_TIER_TAPER=1` (strict, default-OFF) is
> a separate operator step after a live sizing consumer is built and the
> observation window clears; no market-hours activation.
