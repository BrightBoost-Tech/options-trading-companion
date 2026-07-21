"""Continuous tier-taper engine (DARK / observe-only, versioned, PURE).

Motivation
----------
``SmallAccountCompounder.get_tier`` (small_account_compounder.py) resolves
capital into three tiers with HARD cliffs at $1,000 and $5,000. Lane D
targets the **$1,000 micro↔small cliff**. At that boundary the effective
sizing parameters jump discontinuously:

    micro  (equity < $1,000):  envelope 0.90×regime, ONE trade at a time,
                               a single position consumes the whole slot
                               (RBE micro path + compounder micro path).
    small  (equity ≥ $1,000):  envelope 0.85×regime (PortfolioAllocator
                               GLOBAL_ENVELOPE_PCT), per-trade ceiling 0.36
                               (PER_TRADE_CEILING_PCT), up to 4 concurrent
                               (MAX_CONCURRENT_POSITIONS).

A $999↔$1,001 equity oscillation therefore thrashes tier behavior: the
TOTAL deployable envelope steps 0.90→0.85 (a discontinuous DROP as equity
rises past $1,000) and the concurrent-position count flips 1↔4.

This module is a **pure, versioned taper engine**. It smoothly interpolates
the tier-derived risk parameters across a documented band around the
$1,000 boundary and applies Schmitt-trigger hysteresis to the discrete
tier state. It performs NO I/O, holds NO state, and NEVER mutates its
inputs. The live sizing path does not consume it yet — a caller wires it
DARK (observe-only) and emits the ``current`` vs ``proposed`` comparison
into an observability sink. Activation is a separate, flag-gated decision
(see ``docs/specs/tier_taper_activation_packet.md``).

Invariants (see the activation packet for the full proof)
---------------------------------------------------------
1. **Monotonicity (proven):** for a fixed regime multiplier m > 0, the
   tapered TOTAL deployable dollars  D(e) = e · envelope_pct(e) · m  is
   monotonically NON-DECREASING in equity e over the whole domain. A drop
   in equity never increases total deployable risk. The RAW cliff VIOLATES
   this (D drops from $899 to $851 crossing $1,000 upward — i.e. rises when
   equity falls); the taper removes that violation.
2. **SHOCK ceiling retained:** ``envelope_pct(e) ∈ [0.85, 0.90]`` for all e
   (never exceeds the MAX of the two adjacent tier caps; micro's own cap is
   0.90). The regime multiplier (shock = 0.5, etc.) is applied on top,
   unchanged, so the portfolio-wide shock ceiling is preserved exactly.
3. **Outside-band identity:** for equity outside the band the proposed
   parameters equal the raw-cliff parameters exactly — current behavior is
   preserved byte-for-byte outside the transition band.
4. **Per-trade ceiling is a CAP, monotone in fraction:**
   ``per_trade_ceiling_pct(e)`` is non-increasing in e (0.90 at micro →
   0.36 at small) — the cap tightens (in fraction terms) as equity grows,
   the safe direction. Its DOLLAR value is not a monotonicity target: the
   two tiers' raw per-trade ceilings are dollar-inverted at the band edges
   ($810 at $900 micro vs $396 at $1,100 small), so no edge-preserving
   equity-continuous taper can be per-trade-dollar-monotone. The taper
   replaces the raw discontinuous per-trade JUMP with a continuous ramp
   bounded between the two adjacent tiers' caps — it never loosens beyond
   either tier's own ceiling. This preserves the deliberate
   aggressive-micro / diversified-small regime distinction.
5. **Fail-closed hysteresis seed:** with no prior state (cold start / stale
   / unreadable) the effective tier state seeds from the RAW cliff
   (equity ≥ $1,000 → small, else micro) — the current behavior, never a
   loosened default.
6. **Never-loosen (v2 conservative band):** ``proposed envelope_pct ≤ raw
   envelope_pct`` for ALL equity — the taper lies entirely below the
   boundary and lands on small's 0.85 exactly at $1,000, so the ``verdict``
   is only ever ``would_tighten`` / ``identical`` / ``not_applicable``,
   NEVER ``would_loosen``. (v1's symmetric [$900, $1,100] band had a bounded
   would_loosen region just above $1,000, ≤ micro's own 0.90 cap; v2 removes
   it — this is the ratified reconciliation, owner-packet-6.)
7. **Version-partitioned evidence:** v1 and v2 are different band/state
   semantics; every emitted payload carries ``engine_version`` and a reader
   MUST partition observe aggregates by it (never pool a [$900, $1,100]-era
   sample with a [$800, $1,000]-era sample). See ``ENGINE_VERSION`` below
   and ``scripts/analytics/monday_evidence_reader.build_tier_taper``.

Band derivation (v2 — conservative never-loosen, ratified 2026-07-19)
--------------------------------------------------------------------
Band = **[$800, $1,000]** — ``BAND_PCT`` (0.20) is the reach BELOW the
$1,000 boundary (``BAND_LO = BOUNDARY·(1 − BAND_PCT) = 800``,
``BAND_HI = BOUNDARY = 1,000``). The taper lies ENTIRELY below the boundary
and lands exactly on small's 0.85 at $1,000, so it is **proposed ≤ current
everywhere** (no ``would_loosen`` region — invariant 6). The owner ratified
this conservative band (owner-packet-6, owner-ratifications-2026-07-19 §6)
over the original symmetric ±10% [$900, $1,100] band (v1, #1283): in
learning-mode (correctness > deployment) the symmetric band's small
above-boundary ``would_loosen`` region buys nothing the owner asked for.
The endpoints move 720 → 850 (``D(800)=800·0.90=720`` up to
``D(1,000)=1,000·0.85=850``) and stay monotone (§ invariant 1). The band
edges are module constants so any future owner decision is a one-line,
version-bumped change — this v2 IS that change relative to v1.

Hysteresis derivation (v2 — one-sided gap below the boundary)
-------------------------------------------------------------
The continuous fraction taper is a pure function of equity (no path
dependence → no dollar thrash). Only the DISCRETE tier state (concurrent
count 1↔4, tier label) is hysteretic, via a Schmitt trigger. For the
conservative band the boundary IS the band's upper edge, so the Schmitt
gap is ONE-SIDED and sits entirely BELOW the boundary — inner band
[$950, $1,000] (``HYST_LO = BOUNDARY·(1 − HYST_PCT) = 950``,
``HYST_HI = BOUNDARY = 1,000``):

  • From ``micro``: flip to ``small`` only at equity ≥ $1,000 — the taper
    NEVER enters the looser ``small`` state (4 concurrent) BELOW the raw
    cliff, so hysteresis introduces no downward-risk loosening (invariant
    6). This is stricter than v1, whose symmetric gap flipped at $1,050.
  • From ``small``: hold ``small`` down to $950 before reverting to
    ``micro`` — a $50 (5%) anti-thrash gap so a $999↔$1,001 oscillation
    flips at most ONCE (on first crossing of the $1,000 cliff) then STICKS,
    never thrashing 1↔4 each wobble.

``HYST_LO`` ($950) sits strictly inside the taper band ($950 > $800); the
upper edge equals the boundary ($1,000 = ``BAND_HI``), so OUTSIDE the taper
band the discrete state matches the raw cliff exactly (invariant 3) — from
any prior, equity < $800 resolves ``micro`` and equity ≥ $1,000 resolves
``small``.

Versioning
----------
``ENGINE_VERSION`` bumps on ANY change to a band edge, hysteresis edge,
tier anchor, or the interpolation/state-machine semantics. The emitted
payload always carries it so a downstream reader can attribute an
observation to an exact engine build. **v2 (this build) moved the band from
the symmetric [$900, $1,100] to the conservative [$800, $1,000] and moved
``HYST_HI`` from $1,050 to the boundary $1,000 — a band + state-machine
semantics change. Evidence gathered under v1 and v2 MUST NOT be pooled;
partition every observe aggregate by ``engine_version`` (invariant 7).**
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional

# ── Version ──────────────────────────────────────────────────────────────
# v2: conservative never-loosen band [800, 1000] (ratified 2026-07-19,
# owner-packet-6); v1 was the symmetric [900, 1100]. Bumped because the band
# edges AND the hysteresis upper edge moved — v1/v2 evidence must not pool
# (invariant 7).
ENGINE_VERSION = "tier_taper.v2"

# ── Boundary + band (see "Band derivation") ──────────────────────────────
# Conservative band: the taper lies ENTIRELY below the boundary and lands on
# small's 0.85 exactly at $1,000, so proposed <= current everywhere (no
# would_loosen). BAND_PCT is the reach BELOW the boundary; the upper edge IS
# the boundary (not boundary·(1+pct) as in the v1 symmetric band).
BOUNDARY = 1000.0            # the micro↔small cliff in get_tier
BAND_PCT = 0.20             # below-boundary reach as a fraction of BOUNDARY
BAND_LO = BOUNDARY * (1.0 - BAND_PCT)   # 800.0  (fully micro at/below)
BAND_HI = BOUNDARY                      # 1000.0 (== boundary; taper top edge)

# Upper cliff (micro↔small is Lane D's scope; the standard cliff at $5,000
# is explicitly OUT of scope and the taper never activates there).
STANDARD_BOUNDARY = 5000.0

# ── Hysteresis inner band (see "Hysteresis derivation") ──────────────────
# One-sided gap BELOW the boundary: flip to small only at the cliff (>=
# BOUNDARY, never loosens below it), hold small down to HYST_LO (anti-thrash).
HYST_PCT = 0.05             # below-boundary hysteresis reach
HYST_LO = BOUNDARY * (1.0 - HYST_PCT)   # 950.0
HYST_HI = BOUNDARY                      # 1000.0 (== boundary; one-sided gap)

# ── Tier anchors ─────────────────────────────────────────────────────────
# MICRO: a single position consumes the whole 0.90×regime slot (RBE micro
#        global_max/max_risk_trade == deployable × 0.90 × regime; one trade).
# SMALL: PortfolioAllocator envelope 0.85, per-trade ceiling 0.36, ≤4.
# These MUST stay in sync with the source-of-truth modules; the drift-guard
# test (test_tier_taper.py::test_anchors_match_source_of_truth) asserts it.
MICRO_ENVELOPE_PCT = 0.90
MICRO_PER_TRADE_CEILING_PCT = 0.90      # single trade may take the whole slot
MICRO_MAX_CONCURRENT = 1

SMALL_ENVELOPE_PCT = 0.85
SMALL_PER_TRADE_CEILING_PCT = 0.36
SMALL_MAX_CONCURRENT = 4

# ── Regime multipliers ───────────────────────────────────────────────────
# Mirror of PortfolioAllocator._REGIME_MULT / the compounder mapping. Kept
# local to keep this module import-light and pure; the drift-guard test
# (test_tier_taper.py::test_regime_mult_matches_allocator) asserts equality.
_REGIME_MULT = {
    "normal": 1.0,
    "suppressed": 0.9,
    "elevated": 0.8,
    "shock": 0.5,
    "chop": 1.0,
    "rebound": 1.0,
}

_VALID_STATES = ("micro", "small")


# ── Pure helpers ─────────────────────────────────────────────────────────
def normalize_regime(regime: Any) -> str:
    """Coerce a regime input to a lowercase key for ``_REGIME_MULT``.

    Accepts a plain string ("normal"), an enum with ``.name``
    (RegimeState.NORMAL), or a snapshot with ``.state`` — same resilience
    pattern as ``PortfolioAllocator._normalize_regime``. Unknown values map
    to ``normal`` (multiplier 1.0), the do-no-harm default.
    """
    if regime is None:
        return "normal"
    name = getattr(regime, "name", None)
    if isinstance(name, str):
        return name.lower()
    state = getattr(regime, "state", None)
    if state is not None:
        sub = getattr(state, "value", None) or getattr(state, "name", None)
        if isinstance(sub, str):
            return sub.lower()
    return str(regime).lower()


def regime_mult(regime: Any) -> float:
    """Regime multiplier for a regime input; unknown → 1.0 (do-no-harm)."""
    return _REGIME_MULT.get(normalize_regime(regime), 1.0)


def taper_fraction(equity: float) -> float:
    """Linear taper position t ∈ [0, 1] across the band.

    0 at/below ``BAND_LO`` (fully micro), 1 at/above ``BAND_HI`` (fully
    small), linear in between. C0-continuous at both edges by construction.
    """
    if equity <= BAND_LO:
        return 0.0
    if equity >= BAND_HI:
        return 1.0
    return (equity - BAND_LO) / (BAND_HI - BAND_LO)


def _interp(lo: float, hi: float, t: float) -> float:
    return lo + t * (hi - lo)


def raw_tier_name(equity: float) -> str:
    """The tier label ``get_tier`` would assign (micro/small/standard).

    Mirrors ``SmallAccountCompounder.get_tier``'s ``min_cap <= cap < max_cap``
    bands: micro [0, 1000), small [1000, 5000), standard [5000, ∞). Used for
    the honest ``raw_tier`` label only.
    """
    if equity < BOUNDARY:
        return "micro"
    if equity < STANDARD_BOUNDARY:
        return "small"
    return "standard"


@dataclass(frozen=True)
class TierParams:
    """Effective sizing parameters at one tier (pre-regime fractions)."""
    tier: str
    envelope_pct: float
    per_trade_ceiling_pct: float
    max_concurrent: int


def _raw_params(equity: float) -> Optional[TierParams]:
    """RAW-cliff parameters (what the live pipeline effectively uses).

    Returns None for the standard tier (out of Lane D scope) so the caller
    can mark the observation not-applicable rather than fabricate a small
    envelope for a $6,000 account.
    """
    tier = raw_tier_name(equity)
    if tier == "micro":
        return TierParams("micro", MICRO_ENVELOPE_PCT,
                          MICRO_PER_TRADE_CEILING_PCT, MICRO_MAX_CONCURRENT)
    if tier == "small":
        return TierParams("small", SMALL_ENVELOPE_PCT,
                          SMALL_PER_TRADE_CEILING_PCT, SMALL_MAX_CONCURRENT)
    return None  # standard — out of scope


def resolve_tier_state(equity: float,
                       previous_state: Optional[str]) -> tuple[str, str]:
    """Schmitt-trigger hysteresis on the discrete tier state.

    Returns ``(effective_state, decision)`` where ``effective_state`` is
    ``"micro"`` or ``"small"`` and ``decision`` names the transition taken.

    State machine (v2 one-sided gap [HYST_LO, HYST_HI] = [$950, $1,000],
    HYST_HI == BOUNDARY):

        previous ``micro`` : flip to ``small`` iff equity ≥ HYST_HI
                             ($1,000 = the raw cliff — never enters the
                             looser small state below it), else hold
                             ``micro``.
        previous ``small`` : flip to ``micro`` iff equity ≤ HYST_LO ($950 —
                             a $50 anti-thrash gap below the cliff), else
                             hold ``small``.
        no/invalid prior   : FAIL-CLOSED seed from the raw cliff
                             (equity ≥ BOUNDARY → small, else micro).

    The fail-closed seed is the CURRENT behavior, never a loosened default —
    missing / stale / unreadable prior state degrades to the raw cliff.
    """
    if previous_state not in _VALID_STATES:
        seed = "small" if equity >= BOUNDARY else "micro"
        return seed, "cold_start_raw_seed"

    if previous_state == "micro":
        if equity >= HYST_HI:
            return "small", "flip_to_small"
        return "micro", "hold_micro"

    # previous_state == "small"
    if equity <= HYST_LO:
        return "micro", "flip_to_micro"
    return "small", "hold_small"


def _proposed_params(equity: float,
                     effective_state: str) -> Optional[TierParams]:
    """Tapered parameters.

    Outside the band (or standard tier) → identical to raw. Inside the band
    → continuous linear interpolation of the fractions; ``max_concurrent``
    tracks the hysteretic discrete state (micro→1, small→4).
    """
    raw = _raw_params(equity)
    if raw is None:
        return None  # standard — identity handled by caller
    if equity <= BAND_LO or equity >= BAND_HI:
        return raw  # outside band → exact raw behavior (invariant 3)

    t = taper_fraction(equity)
    env = _interp(MICRO_ENVELOPE_PCT, SMALL_ENVELOPE_PCT, t)
    ptc = _interp(MICRO_PER_TRADE_CEILING_PCT, SMALL_PER_TRADE_CEILING_PCT, t)
    max_conc = (SMALL_MAX_CONCURRENT if effective_state == "small"
                else MICRO_MAX_CONCURRENT)
    # Label the proposed tier by which side of the boundary we are on
    # (honest: the fractions are a blend, but the "tier" the operator would
    # name still tracks the raw boundary crossing).
    return TierParams(raw.tier, env, ptc, max_conc)


@dataclass(frozen=True)
class TaperDecision:
    """One observe-only taper decision (pure; serializes via to_payload)."""
    engine_version: str
    equity: float
    regime: str
    regime_mult: float
    in_band: bool
    taper_applied: bool
    taper_fraction: float
    raw_tier: str
    effective_tier_state: str
    previous_tier_state: Optional[str]
    hysteresis_decision: str
    current: Optional[TierParams]
    proposed: Optional[TierParams]
    current_envelope_dollars: Optional[float]
    proposed_envelope_dollars: Optional[float]
    current_per_trade_ceiling_dollars: Optional[float]
    proposed_per_trade_ceiling_dollars: Optional[float]
    verdict: str

    def to_payload(self) -> Dict[str, Any]:
        """Plain-dict payload for a JSON observability sink."""
        cur = asdict(self.current) if self.current is not None else None
        prop = asdict(self.proposed) if self.proposed is not None else None

        def _round(x: Optional[float]) -> Optional[float]:
            return None if x is None else round(x, 6)

        difference: Dict[str, Any] = {}
        if cur is not None and prop is not None:
            difference = {
                "envelope_pct": _round(prop["envelope_pct"]
                                       - cur["envelope_pct"]),
                "per_trade_ceiling_pct": _round(
                    prop["per_trade_ceiling_pct"]
                    - cur["per_trade_ceiling_pct"]),
                "max_concurrent": (prop["max_concurrent"]
                                   - cur["max_concurrent"]),
                "envelope_dollars": _round(
                    (self.proposed_envelope_dollars or 0.0)
                    - (self.current_envelope_dollars or 0.0)),
                "per_trade_ceiling_dollars": _round(
                    (self.proposed_per_trade_ceiling_dollars or 0.0)
                    - (self.current_per_trade_ceiling_dollars or 0.0)),
            }

        if cur is not None:
            cur = dict(cur)
            cur["envelope_dollars"] = _round(self.current_envelope_dollars)
            cur["per_trade_ceiling_dollars"] = _round(
                self.current_per_trade_ceiling_dollars)
        if prop is not None:
            prop = dict(prop)
            prop["envelope_dollars"] = _round(self.proposed_envelope_dollars)
            prop["per_trade_ceiling_dollars"] = _round(
                self.proposed_per_trade_ceiling_dollars)

        return {
            "engine_version": self.engine_version,
            "equity": _round(self.equity),
            "regime": self.regime,
            "regime_mult": self.regime_mult,
            "boundary": BOUNDARY,
            "band": {"lo": BAND_LO, "hi": BAND_HI, "pct": BAND_PCT},
            "hysteresis": {"lo": HYST_LO, "hi": HYST_HI, "pct": HYST_PCT},
            "in_band": self.in_band,
            "taper_applied": self.taper_applied,
            "taper_fraction": _round(self.taper_fraction),
            "raw_tier": self.raw_tier,
            "effective_tier_state": self.effective_tier_state,
            "previous_tier_state": self.previous_tier_state,
            "hysteresis_decision": self.hysteresis_decision,
            "current": cur,
            "proposed": prop,
            "difference": difference,
            "verdict": self.verdict,
        }


def decide(equity: float,
           regime: Any = "normal",
           previous_state: Optional[str] = None) -> TaperDecision:
    """Compute the taper decision for one (equity, regime) — PURE.

    Args:
        equity: deployable capital in USD.
        regime: market regime (string, enum, or snapshot).
        previous_state: prior effective tier state ("micro"/"small") for
            hysteresis. None / invalid → fail-closed raw-cliff seed.

    Returns a ``TaperDecision``. Never mutates inputs, never does I/O.
    """
    reg_key = normalize_regime(regime)
    m = _REGIME_MULT.get(reg_key, 1.0)
    raw_tier = raw_tier_name(equity)

    eff_state, hyst_decision = resolve_tier_state(equity, previous_state)

    cur = _raw_params(equity)
    prop = _proposed_params(equity, eff_state)

    in_band = BAND_LO < equity < BAND_HI and raw_tier != "standard"
    # taper is "applied" only when it actually changes something (in band).
    taper_applied = in_band

    def _env_usd(p: Optional[TierParams]) -> Optional[float]:
        return None if p is None else equity * p.envelope_pct * m

    def _ptc_usd(p: Optional[TierParams]) -> Optional[float]:
        return None if p is None else equity * p.per_trade_ceiling_pct * m

    cur_env, prop_env = _env_usd(cur), _env_usd(prop)
    cur_ptc, prop_ptc = _ptc_usd(cur), _ptc_usd(prop)

    # Verdict on the TOTAL deployable envelope dollars (the monotone,
    # SHOCK-ceiling-governed quantity).
    if cur_env is None or prop_env is None:
        verdict = "not_applicable"
    elif abs(prop_env - cur_env) < 1e-9:
        verdict = "identical"
    elif prop_env < cur_env:
        verdict = "would_tighten"
    else:
        verdict = "would_loosen"

    return TaperDecision(
        engine_version=ENGINE_VERSION,
        equity=equity,
        regime=reg_key,
        regime_mult=m,
        in_band=in_band,
        taper_applied=taper_applied,
        taper_fraction=taper_fraction(equity),
        raw_tier=raw_tier,
        effective_tier_state=eff_state,
        previous_tier_state=previous_state,
        hysteresis_decision=hyst_decision,
        current=cur,
        proposed=prop,
        current_envelope_dollars=cur_env,
        proposed_envelope_dollars=prop_env,
        current_per_trade_ceiling_dollars=cur_ptc,
        proposed_per_trade_ceiling_dollars=prop_ptc,
        verdict=verdict,
    )


def observe(equity: float,
            regime: Any = "normal",
            previous_state: Optional[str] = None) -> Dict[str, Any]:
    """DARK observe-only entrypoint: returns the payload dict for a sink.

    Thin wrapper over ``decide(...).to_payload()`` — the single call the
    orchestrator wire-in makes. PURE; safe to call on the hot path.
    """
    return decide(equity, regime, previous_state).to_payload()


def extract_previous_tier_state(job_run_result: Optional[Dict[str, Any]]
                                ) -> Optional[str]:
    """Pull the prior effective tier state from a persisted job_run result.

    Migration-free hysteresis durability: the prior decision already lives
    in ``job_runs.result.cycle_metadata.tier_taper.effective_tier_state``.
    Returns None on any missing / malformed shape (→ engine fail-closes to
    the raw-cliff seed). Kept pure so activation can wire real cross-cycle
    hysteresis with a one-line read; the DARK wire-in passes None.
    """
    try:
        tt = (job_run_result or {}).get("cycle_metadata", {}).get("tier_taper")
        if not isinstance(tt, dict):
            return None
        state = tt.get("effective_tier_state")
        return state if state in _VALID_STATES else None
    except (AttributeError, TypeError):
        return None


__all__ = [
    "ENGINE_VERSION",
    "BOUNDARY", "BAND_PCT", "BAND_LO", "BAND_HI",
    "HYST_PCT", "HYST_LO", "HYST_HI", "STANDARD_BOUNDARY",
    "MICRO_ENVELOPE_PCT", "MICRO_PER_TRADE_CEILING_PCT", "MICRO_MAX_CONCURRENT",
    "SMALL_ENVELOPE_PCT", "SMALL_PER_TRADE_CEILING_PCT", "SMALL_MAX_CONCURRENT",
    "TierParams", "TaperDecision",
    "normalize_regime", "regime_mult", "taper_fraction", "raw_tier_name",
    "resolve_tier_state", "decide", "observe", "extract_previous_tier_state",
]
