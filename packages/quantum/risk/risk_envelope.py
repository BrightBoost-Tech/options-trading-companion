"""
Portfolio Risk Envelope — comprehensive position-level risk limits.

Layers on top of the existing RiskBudgetEngine (not a replacement).
Checks limits that the budget engine doesn't cover:

1. Greeks limits (portfolio-level delta, gamma, vega, theta)
2. Concentration limits (symbol, sector, expiry, correlation)
3. Event concentration (earnings exposure)
4. Loss envelopes (daily, weekly, per-symbol)
5. Stress scenarios (SPY crash, VIX spike, correlation-one)

All limits are configurable via env vars with sensible defaults.
"""

import logging
import math
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from packages.quantum.risk.position_model import (
    PositionNormalizationError,
    RiskClassification,
    _direction_sign,
    aggregate_greeks,
    analyze_payoff,
    normalize_position,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration (env var overrides)
# ---------------------------------------------------------------------------

def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


@dataclass
class EnvelopeConfig:
    """Risk envelope configuration — all limits in one place."""

    # Greeks limits (absolute dollar values per 1% move)
    max_portfolio_delta: float = 0.0     # 0 = no limit
    max_portfolio_gamma: float = 0.0
    max_portfolio_vega: float = 0.0
    max_portfolio_theta: float = 0.0

    # Concentration limits (as fractions 0-1)
    max_single_symbol_pct: float = 0.25   # 25% of risk in one name
    max_sector_pct: float = 0.40          # 40% in one sector
    max_same_expiry_pct: float = 0.50     # 50% expiring on same date
    max_correlation_cluster_pct: float = 0.60

    # Event concentration
    max_event_exposure_pct: float = 0.30  # 30% of risk near-event
    max_earnings_positions: int = 3       # max concurrent earnings plays

    # Loss envelopes (as fractions of equity)
    max_daily_loss_pct: float = 0.05      # -5% daily hard stop
    max_weekly_loss_pct: float = 0.10     # -10% weekly → reduce sizing
    max_per_symbol_loss_pct: float = 0.03 # -3% of equity per name

    # Stress scenario thresholds
    stress_spy_down_pct: float = 0.05     # SPY -5% scenario
    stress_vix_spike_pct: float = 0.50    # VIX +50% scenario
    max_stress_loss_pct: float = 0.15     # -15% max under stress

    # Severity of the share-of-book symbol-concentration check. Default
    # "block" (legacy). Call sites that know deployable capital (the
    # paper-autopilot circuit breaker; the orchestrator's observe-log) demote
    # this to "warn" at small tier when the #1044 utilization gate is
    # explicitly enabled — the pro-forma utilization cap replaces
    # share-of-book as the entry-blocking control there. NOT read from env
    # here: the demotion is tier-conditional, and tier needs a per-user OBP
    # read this pure module must not perform. Sector/expiry/stress severities
    # are NOT configurable — they keep their hardcoded values.
    symbol_concentration_severity: str = "block"

    @classmethod
    def from_env(cls) -> "EnvelopeConfig":
        """Load config from environment variables."""
        return cls(
            max_portfolio_delta=_env_float("RISK_MAX_DELTA", 0),
            max_portfolio_gamma=_env_float("RISK_MAX_GAMMA", 0),
            max_portfolio_vega=_env_float("RISK_MAX_VEGA", 0),
            max_portfolio_theta=_env_float("RISK_MAX_THETA", 0),
            max_single_symbol_pct=_env_float("RISK_MAX_SYMBOL_PCT", 0.25),
            max_sector_pct=_env_float("RISK_MAX_SECTOR_PCT", 0.40),
            max_same_expiry_pct=_env_float("RISK_MAX_EXPIRY_PCT", 0.50),
            max_event_exposure_pct=_env_float("RISK_MAX_EVENT_PCT", 0.30),
            max_earnings_positions=_env_int("RISK_MAX_EARNINGS_POS", 3),
            max_daily_loss_pct=_env_float("RISK_MAX_DAILY_LOSS", 0.05),
            max_weekly_loss_pct=_env_float("RISK_MAX_WEEKLY_LOSS", 0.10),
            max_per_symbol_loss_pct=_env_float("RISK_MAX_SYMBOL_LOSS", 0.03),
            stress_spy_down_pct=_env_float("RISK_STRESS_SPY_DOWN", 0.05),
            stress_vix_spike_pct=_env_float("RISK_STRESS_VIX_SPIKE", 0.50),
            max_stress_loss_pct=_env_float("RISK_MAX_STRESS_LOSS", 0.15),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {k: round(v, 4) if isinstance(v, float) else v
                for k, v in self.__dict__.items()}


# ---------------------------------------------------------------------------
# Envelope check result
# ---------------------------------------------------------------------------

@dataclass
class EnvelopeViolation:
    """A single limit violation."""
    envelope: str       # e.g. "greeks_delta", "concentration_symbol"
    limit: float
    actual: float
    severity: str       # "warn" | "block" | "force_close"
    message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "envelope": self.envelope,
            "limit": round(self.limit, 4),
            "actual": round(self.actual, 4),
            "severity": self.severity,
            "message": self.message,
        }


@dataclass
class EnvelopeCheckResult:
    """Result of checking all envelopes."""
    passed: bool = True
    violations: List[EnvelopeViolation] = field(default_factory=list)
    sizing_multiplier: float = 1.0     # Reduce sizing if approaching limits
    force_close_ids: List[str] = field(default_factory=list)

    # Aggregated portfolio state
    portfolio_greeks: Dict[str, float] = field(default_factory=dict)
    concentration: Dict[str, float] = field(default_factory=dict)
    stress_results: Dict[str, float] = field(default_factory=dict)
    loss_status: Dict[str, float] = field(default_factory=dict)

    # Positions whose per-symbol loss could NOT be evaluated this pass because
    # their mark was unpriceable (legs couldn't price → _mark_unpriceable, set
    # by intraday_risk_monitor._refresh_marks). These are NEITHER force-closed
    # on a stale/uncorroborated value NOR silently skipped — the caller raises
    # a loud degraded-protection alert and retries next pass (#1035 asymmetric
    # mark policy, extended to the loss_per_symbol envelope).
    degraded_per_symbol: List[Dict[str, Any]] = field(default_factory=list)

    # Positions force-closed by the PER-SYMBOL loss envelope this pass — the
    # structured, unambiguous protective-stop set (one entry per breaching
    # symbol: {cohort_id, symbol, position_id, realized_loss}). NOT daily/weekly
    # (those mark ALL positions) and NOT concentration/stress. The monitor reads
    # this to write a re-entry cooldown keyed on (cohort_id, symbol) — gating
    # here, at the decision point, avoids the 5b loop's violation→position
    # conflation (a daily-loss sweep must not bench a symbol per-symbol).
    symbol_loss_stops: List[Dict[str, Any]] = field(default_factory=list)

    # Stress scenarios whose greek inputs were missing this pass — typed
    # unavailability (H9: omit + flag, never a fabricated 0). Keyed by
    # scenario name ("spy_down"/"vix_spike") with {reason, missing_field,
    # legs_missing}. Deliberately NOT an EnvelopeViolation: production legs
    # persist no greeks (§8 double-dormancy), and a per-cycle warn violation
    # here would write a risk_alerts row every monitor pass for a ledgered
    # standing condition (the A9 noise class). correlation_one + worst_case
    # remain in stress_results whenever every structure is representable.
    stress_unavailable: Dict[str, Any] = field(default_factory=dict)

    # Greeks-aggregation coverage this pass (H9 null-safety for check_greeks).
    # {legs_total, legs_with_greeks, complete}: legs_total = leg dicts seen;
    # legs_with_greeks = legs that contributed a COMPLETE finite greeks set to
    # the portfolio_greeks sums. When legs_with_greeks < legs_total the
    # aggregate is PARTIAL — built from a subset — and must not be read as a
    # whole-book exposure; a leg with missing/None/nonfinite greeks contributes
    # NOTHING (never a fabricated 0). Empty until check_greeks runs. §8
    # double-dormancy: production legs carry no greeks today, so legs_with_greeks
    # is expected 0 until #1259's stage-time greek population ships.
    greeks_coverage: Dict[str, Any] = field(default_factory=dict)

    # OBSERVE-ONLY canonical portfolio greeks (aggregate_canonical_greeks): the
    # SIGNED, ratio- and multiplier-aware aggregate built through the canonical
    # position model from the persisted stage-time leg greeks (#1259). Sits
    # ALONGSIDE portfolio_greeks — it modulates NOTHING, arms no cap, and never
    # feeds a violation. Longs and shorts NET here (canonical aggregate_greeks),
    # unlike the D2-defective portfolio_greeks. Empty until check_all_envelopes
    # runs; {delta,gamma,vega,theta} are None (typed unavailable) whenever any
    # contributing structure is missing that greek — never a fabricated 0 (H9).
    canonical_greeks: Dict[str, Any] = field(default_factory=dict)

    # OBSERVE-ONLY greek-cap ALERT-ONLY counterfactual (owner items 9+11). Sits
    # ALONGSIDE canonical_greeks; arms no cap, rejects no entry, scales no size,
    # writes no risk_alerts row, reads no cap flag — ENFORCEMENT-FREE by
    # construction. For a documented set of REFERENCE cap values (derived from
    # existing EnvelopeConfig fields, never invented — see
    # compute_greek_cap_counterfactual) it records, per tightness row, would_block
    # (which cap / which greek), cap_headroom, and a typed-unavailable reason when
    # the exposure cannot be honestly established. Empty until check_all_envelopes
    # runs; every greek is typed UNAVAILABLE (never a fabricated 0) whenever the
    # greeks aggregate is partial, the canonical cross-check is missing, or the two
    # aggregates disagree in sign (H9). §8 double-dormancy: production legs carry
    # no greeks today, so every reference row reads would_block=None (unavailable)
    # until #1259's stage-time greek population accrues real data.
    greek_cap_counterfactual: Dict[str, Any] = field(default_factory=dict)

    def add_violation(self, v: EnvelopeViolation) -> None:
        self.violations.append(v)
        if v.severity in ("block", "force_close"):
            self.passed = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "violations": [v.to_dict() for v in self.violations],
            "sizing_multiplier": round(self.sizing_multiplier, 3),
            "force_close_ids": self.force_close_ids,
            "portfolio_greeks": {k: round(v, 4) for k, v in self.portfolio_greeks.items()},
            "concentration": {k: round(v, 4) for k, v in self.concentration.items()},
            "stress_results": {k: round(v, 4) for k, v in self.stress_results.items()},
            "loss_status": {k: round(v, 4) for k, v in self.loss_status.items()},
            "degraded_per_symbol": self.degraded_per_symbol,
            "symbol_loss_stops": self.symbol_loss_stops,
            "stress_unavailable": self.stress_unavailable,
            "greeks_coverage": self.greeks_coverage,
            "canonical_greeks": self.canonical_greeks,
            "greek_cap_counterfactual": self.greek_cap_counterfactual,
        }


# ---------------------------------------------------------------------------
# Position helpers
# ---------------------------------------------------------------------------

def _pos_field(pos: Dict, key: str, default: Any = 0.0) -> Any:
    """Safely extract a field from a position dict."""
    return pos.get(key) or default


class PositionRiskUnavailable(RuntimeError):
    """Exact structure risk could not be established.

    The envelope must never reinterpret missing/malformed structure state as
    zero risk or fall back to premium received. Callers fail closed on this
    typed outcome.
    """


def _pos_risk(pos: Dict) -> float:
    """Return exact position-level max loss from the canonical payoff surface.

    This is canonical-position consumer PR-2. max_loss_total is already
    scaled by structure quantity and multiplier; it must never be multiplied
    again. Malformed or unbounded structures raise a typed error instead of
    fabricating a finite premium-based risk number.
    """
    position_id = _pos_field(pos, "id", "unknown")
    try:
        canonical = normalize_position(pos, source="risk_envelope")
        profile = analyze_payoff(canonical)
    except PositionNormalizationError as exc:
        raise PositionRiskUnavailable(
            f"position={position_id} normalization failed: {exc}"
        ) from exc

    if (
        profile.classification is not RiskClassification.DEFINED_RISK
        or profile.max_loss_total is None
    ):
        raise PositionRiskUnavailable(
            f"position={position_id} is not defined-risk"
        )

    return float(profile.max_loss_total)


# ---------------------------------------------------------------------------
# Core check functions
# ---------------------------------------------------------------------------

def check_greeks(
    positions: List[Dict],
    config: EnvelopeConfig,
    coverage_out: Optional[Dict[str, Any]] = None,
) -> tuple:
    """Check portfolio-level Greeks limits — null-safe (H9) and SIGN-aware (D2).

    A leg whose greeks are missing / None / partial / nonfinite contributes
    NOTHING to the portfolio sums. It is NEVER coerced to a fabricated 0 (the
    pre-fix ``float(greeks.get("delta", 0))`` raised ``TypeError`` when a
    present greek key held an explicit ``None`` — e.g. #1259's typed-unavailable
    legs — and silently zeroed a genuinely absent one). A leg counts toward the
    aggregate only when ALL of delta/gamma/vega/theta are present and finite.

    **D2 FIX (signed aggregation):** each covered leg's contribution is signed by
    its OWN direction via the canonical sign authority
    ``position_model._direction_sign`` (reuse, not a second copy of the BUY/SELL
    token logic). A long leg and a short leg now NET instead of ADD — the pre-fix
    ``abs(qty)`` add treated a delta-hedged spread as if both legs pointed the
    same way (a 4-leg condor reported 4×|per-leg greek|). A leg whose side cannot
    be determined (unknown / missing action|side) is UNSIGNABLE and therefore
    typed uncovered (contributes nothing, counts against coverage), never a
    fabricated unsigned add (H9). Magnitude scaling (``abs(qty) × 100``) is
    UNCHANGED — leg-ratio (D3) and per-leg multiplier (D4) remain their own lanes.

    Coverage is reported via ``coverage_out`` (optional out-param, matching the
    ``check_loss_envelopes`` ``degraded_out`` idiom): ``{legs_total,
    legs_with_greeks, complete}`` so a consumer can see the aggregate is PARTIAL
    rather than trust a sum built from an incomplete book.

    Caps are UNCHANGED: every greek limit still defaults 0 (no-limit) and the
    ``if limit > 0`` gate is untouched — the aggregate is observe-only telemetry
    (``portfolio_greeks``) while dormant, so ``(violations, passed)`` are
    identical for every caps-0 input. The reported greek VALUE is now the honest
    signed net (a measurement correction, like #1017/#1051/#1071); it diverges
    from the pre-fix unsigned add exactly for opposing-direction legs — the point
    of the D2 lane.
    """
    violations = []
    total_delta = 0.0
    total_gamma = 0.0
    total_vega = 0.0
    total_theta = 0.0
    legs_total = 0
    legs_with_greeks = 0

    for pos in positions:
        qty = float(_pos_field(pos, "quantity", 0))
        legs = pos.get("legs") or []

        for leg in legs:
            if not isinstance(leg, dict):
                continue
            legs_total += 1
            # Source order matches the legacy `or` chain: leg greeks, else
            # position-level, else none. #1259 writes a COMPLETE finite dict OR
            # greeks=None (typed unavailable); a None / empty / absent block
            # resolves to no usable source here.
            src = leg.get("greeks")
            if not (isinstance(src, dict) and src):
                src = pos.get("greeks")
            if not (isinstance(src, dict) and src):
                # No usable greeks for this leg → contributes nothing (H9).
                continue
            d = _finite_greek_value(src, "delta")
            g = _finite_greek_value(src, "gamma")
            v = _finite_greek_value(src, "vega")
            t = _finite_greek_value(src, "theta")
            if d is None or g is None or v is None or t is None:
                # Partial / nonfinite greeks → never fabricate the missing legs
                # as 0; the whole leg is typed uncovered and contributes nothing.
                continue
            # D2: sign by the leg's own direction via the canonical helper. An
            # indeterminate side is unsignable → the leg is typed uncovered, not
            # coerced to a directionless unsigned add.
            side_raw = (
                leg.get("action")
                if leg.get("action") is not None
                else leg.get("side")
            )
            try:
                sign = _direction_sign(side_raw)
            except PositionNormalizationError:
                continue

            total_delta += sign * d * abs(qty) * 100
            total_gamma += sign * g * abs(qty) * 100
            total_vega += sign * v * abs(qty) * 100
            total_theta += sign * t * abs(qty) * 100
            legs_with_greeks += 1

    greeks = {
        "delta": total_delta,
        "gamma": total_gamma,
        "vega": total_vega,
        "theta": total_theta,
    }

    if coverage_out is not None:
        coverage_out["legs_total"] = legs_total
        coverage_out["legs_with_greeks"] = legs_with_greeks
        coverage_out["complete"] = legs_with_greeks == legs_total

    # Check limits (0 = no limit)
    for greek, limit_attr in [
        ("delta", config.max_portfolio_delta),
        ("gamma", config.max_portfolio_gamma),
        ("vega", config.max_portfolio_vega),
        ("theta", config.max_portfolio_theta),
    ]:
        limit = limit_attr
        if limit > 0 and abs(greeks[greek]) > limit:
            violations.append(EnvelopeViolation(
                envelope=f"greeks_{greek}",
                limit=limit,
                actual=abs(greeks[greek]),
                severity="warn",
                message=f"Portfolio {greek} {greeks[greek]:.0f} exceeds limit {limit:.0f}",
            ))

    return violations, greeks


def aggregate_canonical_greeks(positions: List[Dict]) -> Dict[str, Any]:
    """OBSERVE-ONLY signed portfolio greeks via the canonical position model.

    For each position, normalize it (per-contract greeks auto-sourced from the
    position's own persisted leg jsonb — #1259 stage-time populate) and
    aggregate via the canonical ``aggregate_greeks``: ``signed_ratio ×
    structure_quantity × multiplier`` is applied EXACTLY ONCE and a long and a
    short leg NET (never the D2 unsigned add that ``check_greeks`` still carries).

    Book-level: each greek total is the sum across structures, typed UNAVAILABLE
    (``None``) the moment ANY contributing structure is missing that greek — a
    partial book sum is a fabricated total (H9). ``complete`` is True only when
    every structure normalized and every leg carried a complete finite greek set.

    PURE TELEMETRY. It NEVER raises (a structure that fails to normalize is
    counted unrepresentable and drops out, the book flagged incomplete), NEVER
    arms a cap, NEVER gates a decision. It sits ALONGSIDE ``check_greeks`` and
    does not replace or feed it. Returns a JSON-serializable dict.
    """
    names = ("delta", "gamma", "vega", "theta")
    sums = {n: 0.0 for n in names}
    missing = {n: False for n in names}
    legs_total = 0
    legs_with_greeks = 0
    sources: List[str] = []
    as_of: List[str] = []
    missing_legs: List[str] = []
    unrepresentable = 0

    for pos in positions:
        try:
            canonical = normalize_position(pos, source="risk_envelope_observe")
        except PositionNormalizationError:
            # Unrepresentable structure: it cannot contribute an honest greek
            # basis, so the whole book is flagged incomplete (never silently
            # dropped as if flat).
            unrepresentable += 1
            for n in names:
                missing[n] = True
            continue
        exposure = aggregate_greeks(canonical)
        legs_total += exposure.legs_total
        legs_with_greeks += exposure.legs_with_greeks
        missing_legs.extend(exposure.missing_legs)
        sources.extend(exposure.sources)
        as_of.extend(exposure.as_of)
        for name, value in (
            ("delta", exposure.delta_dollars_per_underlying_point),
            ("gamma", exposure.gamma_dollars_per_point_squared),
            ("vega", exposure.vega_dollars_per_vol_point),
            ("theta", exposure.theta_dollars_per_day),
        ):
            if value is None:
                missing[name] = True
            else:
                sums[name] += value

    complete = unrepresentable == 0 and not any(missing.values())
    return {
        "delta": None if missing["delta"] else sums["delta"],
        "gamma": None if missing["gamma"] else sums["gamma"],
        "vega": None if missing["vega"] else sums["vega"],
        "theta": None if missing["theta"] else sums["theta"],
        "complete": complete,
        "legs_total": legs_total,
        "legs_with_greeks": legs_with_greeks,
        "missing_legs": sorted(set(missing_legs)),
        "unrepresentable_structures": unrepresentable,
        "sources": sorted({s for s in sources if s}),
        "as_of": sorted({a for a in as_of if a}),
    }


# ---------------------------------------------------------------------------
# Greek-cap ALERT-ONLY counterfactual (observe-only; owner items 9 + 11)
# ---------------------------------------------------------------------------
#
# ENFORCEMENT-FREE BY CONSTRUCTION. This surface answers "what WOULD a greek cap
# do at a documented reference threshold?" WITHOUT arming any cap: it rejects no
# entry, scales no size, writes no risk_alerts row, and reads no cap flag. The
# four production greek caps (config.max_portfolio_{delta,gamma,vega,theta}) stay
# default-0 (dormant); this computes an INDEPENDENT counterfactual BESIDE them,
# exactly as canonical_greeks sits beside portfolio_greeks. Making any of this
# enforcement is a separate, future PR (ENABLE_LIVE_GREEK_CAPS stays false — no
# cap flag is introduced here).
#
# BASIS: would_block compares against portfolio_greeks — the SAME value the armed
# cap would read inside check_greeks (`abs(greeks[g]) > limit`) — so the
# counterfactual models the ACTUAL enforcement code, not an idealized aggregate
# (doctrine: the decision path is the only truth). Each greek's counterfactual is
# CORROBORATED by the INDEPENDENT canonical signed aggregate: would_block is
# asserted ONLY when the greeks aggregate is whole-book complete AND the canonical
# value is present AND the two aggregates AGREE IN SIGN. A partial book, a missing
# canonical value, or a sign divergence → typed UNAVAILABLE, never a fabricated
# would_block / zero exposure (H9).
#
# REFERENCE CAP DERIVATION (never invented — every number INVERTS an existing
# EnvelopeConfig field). Three tightness rows come from the three loss-envelope
# fractions already in config; each fraction × equity is a dollar loss budget L,
# translated into each greek's OWN unit through the envelope's OWN stress-model
# move sizes, so a book sitting AT a cap loses exactly L under the doctrinal
# scenario:
#   tight   L = max_per_symbol_loss_pct × equity   (0.03 default)
#   medium  L = max_daily_loss_pct      × equity   (0.05 default)
#   loose   L = max_weekly_loss_pct     × equity   (0.10 default)
#   delta_cap = L / stress_spy_down_pct
#       inverts compute_stress_scenarios' spy_down loss (total_delta × spy_move):
#       |delta_$| == delta_cap ⇒ modeled spy-down loss == L.
#   vega_cap  = L / (stress_vix_spike_pct × 100)
#       inverts the vix_spike impact (total_vega × vix_move × 100).
#   theta_cap = L
#       theta is $/day; one day's decay bounded by the day-scaled dollar budget.
#   gamma_cap = L / stress_spy_down_pct**2
#       convexity reference (gamma × move²) reusing the spy_down move basis — the
#       SOFTEST-anchored of the four (the envelope has no first-class gamma
#       scenario), labeled as such; no ½ convexity factor (deliberately
#       conservative-tighter).
# The reference caps INHERIT compute_stress_scenarios' unit convention (greek ×
# fractional-move), so would_block reflects what the code WOULD actually do,
# imperfections included — a counterfactual of the real path, not an idealization.

# Which EnvelopeConfig loss-fraction feeds each tightness row (name, attr).
_GREEK_CF_ROWS = (
    ("tight", "max_per_symbol_loss_pct"),
    ("medium", "max_daily_loss_pct"),
    ("loose", "max_weekly_loss_pct"),
)

# Per-scope memory of the last observed would_block state per reference row, so a
# flip-logger emits ONE INFO line only when a row's would_block CHANGES (no
# per-cycle spam). Keyed by an opt-in caller scope; None scope never logs.
_GREEK_CF_LAST_STATE: Dict[str, Dict[str, Any]] = {}


def reset_greek_cf_state() -> None:
    """Clear the flip-log dedup memory (test seam; also safe to call at boot)."""
    _GREEK_CF_LAST_STATE.clear()


def greek_cap_reference_rows(
    equity: float, config: EnvelopeConfig
) -> List[Dict[str, Any]]:
    """The documented REFERENCE cap rows (tight / medium / loose).

    Every cap INVERTS an existing EnvelopeConfig field (see the module header) —
    no threshold is invented. A non-positive cap (equity ≤ 0, or a config
    fraction / stress move of 0) carries NO usable reference and is emitted as
    None, mirroring check_greeks' `limit > 0` gate — a would_block can never be
    asserted against a non-positive cap.
    """
    spy_move = float(config.stress_spy_down_pct)
    vix_move = float(config.stress_vix_spike_pct)
    rows: List[Dict[str, Any]] = []
    for name, frac_attr in _GREEK_CF_ROWS:
        frac = float(getattr(config, frac_attr))
        budget = frac * float(equity)
        raw_caps = {
            "delta": (budget / spy_move) if spy_move > 0 else None,
            "gamma": (budget / (spy_move ** 2)) if spy_move > 0 else None,
            "vega": (budget / (vix_move * 100)) if vix_move > 0 else None,
            "theta": budget,
        }
        # Only a strictly-positive finite cap is a usable reference.
        caps = {
            g: (round(c, 4) if (c is not None and math.isfinite(c) and c > 0) else None)
            for g, c in raw_caps.items()
        }
        rows.append({
            "name": name,
            "budget_fraction": round(frac, 6),
            "budget_fraction_source": frac_attr,
            "loss_budget_dollars": round(budget, 2),
            "caps": caps,
            "derivation": {
                "delta": f"budget / stress_spy_down_pct  (L / {spy_move})",
                "gamma": (
                    f"budget / stress_spy_down_pct**2  (L / {spy_move}**2) — "
                    "softest-anchored, no 1/2 convexity factor"
                ),
                "vega": f"budget / (stress_vix_spike_pct*100)  (L / ({vix_move}*100))",
                "theta": "budget  (1:1 $/day vs the day-scaled loss budget)",
            },
        })
    return rows


def _greek_cf_availability(
    greek: str,
    portfolio_greeks: Dict[str, Any],
    greeks_coverage: Dict[str, Any],
    canonical: Dict[str, Any],
) -> tuple:
    """Return (available, exposure, canonical_value, reason) for one greek.

    The exposure BASIS is portfolio_greeks[greek] — the value the armed cap would
    compare. Availability is CORROBORATED by the independent canonical aggregate:
    the greek is available only when the greeks aggregate is whole-book complete,
    the exposure is finite, the canonical value is present + finite, AND the two
    agree in sign. Anything else → typed UNAVAILABLE with a reason (never a
    fabricated would_block, never a zero standing in for a missing measurement).
    """
    canon_raw = _finite_greek_value(canonical, greek)
    if not greeks_coverage.get("complete"):
        return (False, None, canon_raw, "greeks_coverage_incomplete")
    exp = _finite_greek_value(portfolio_greeks, greek)
    if exp is None:
        return (False, None, canon_raw, "exposure_nonfinite")
    if not canonical.get("complete") or canon_raw is None:
        return (False, exp, None, "canonical_unavailable")
    if exp != 0 and canon_raw != 0 and (exp > 0) != (canon_raw > 0):
        # The cap's own basis and the honest signed aggregate disagree on
        # direction — untrustworthy; flag, never decide (H9).
        return (False, exp, canon_raw, "sign_mismatch")
    return (True, exp, canon_raw, None)


def _greek_cf_book_summary(positions: List[Dict]) -> Dict[str, Any]:
    """Lightweight book descriptor for the counterfactual (strategy / book type).

    `strategies` are the distinct persisted `strategy` labels present — None-
    tolerant, never fabricated (an unlabeled book yields an empty list, not a
    guessed structure type).
    """
    strategies = sorted(
        {str(p.get("strategy")) for p in positions if p.get("strategy")}
    )
    return {"n_positions": len(positions), "strategies": strategies}


def compute_greek_cap_counterfactual(
    portfolio_greeks: Dict[str, Any],
    greeks_coverage: Dict[str, Any],
    canonical_greeks: Dict[str, Any],
    positions: List[Dict],
    equity: float,
    config: EnvelopeConfig,
) -> Dict[str, Any]:
    """OBSERVE-ONLY greek-cap counterfactual — pure, never raises, arms nothing.

    For each documented reference row (tight/medium/loose) and each greek, records
    would_block (which cap / which greek), cap_headroom, and a typed-unavailable
    reason when the exposure cannot be honestly established. Returns a JSON-
    serializable dict. NEVER a fabricated 0 for a missing exposure (H9): a greek
    whose aggregate is partial / sign-inconsistent / canonically-uncorroborated is
    would_block=None with a reason, and the row is would_block=None when NO greek
    is available.
    """
    if equity is None or not isinstance(equity, (int, float)) or \
            not math.isfinite(equity) or equity <= 0:
        return {
            "enabled": True,
            "basis": "portfolio_greeks",
            "available": False,
            "reason": "nonpositive_equity",
            "reference_rows": [],
        }

    greeks = ("delta", "gamma", "vega", "theta")
    availability: Dict[str, tuple] = {}
    greek_detail: Dict[str, Any] = {}
    for g in greeks:
        ok, exp, canon, reason = _greek_cf_availability(
            g, portfolio_greeks, greeks_coverage, canonical_greeks
        )
        availability[g] = (ok, exp)
        greek_detail[g] = {
            "available": ok,
            "exposure": (round(exp, 4) if exp is not None else None),
            "canonical": (round(canon, 4) if canon is not None else None),
            "reason": reason,
        }

    rows_out: List[Dict[str, Any]] = []
    for row in greek_cap_reference_rows(equity, config):
        caps = row["caps"]
        per_greek: Dict[str, Any] = {}
        blocking: List[Dict[str, Any]] = []
        unavailable_greeks: List[str] = []
        any_available = False
        for g in greeks:
            cap = caps.get(g)
            ok, exp = availability[g]
            if cap is None:
                per_greek[g] = {
                    "cap": None,
                    "exposure": (round(exp, 4) if (ok and exp is not None) else None),
                    "headroom": None,
                    "would_block": None,
                    "reason": "no_reference_cap",
                }
                continue
            if not ok:
                per_greek[g] = {
                    "cap": cap,
                    "exposure": None,
                    "headroom": None,
                    "would_block": None,
                    "reason": greek_detail[g]["reason"],
                }
                unavailable_greeks.append(g)
                continue
            any_available = True
            would_block = abs(exp) > cap
            per_greek[g] = {
                "cap": cap,
                "exposure": round(exp, 4),
                "headroom": round(cap - abs(exp), 4),
                "would_block": would_block,
                "reason": None,
            }
            if would_block:
                blocking.append({
                    "greek": g, "cap": cap, "exposure": round(exp, 4),
                })
        row_would_block = (len(blocking) > 0) if any_available else None
        rows_out.append({
            "name": row["name"],
            "budget_fraction": row["budget_fraction"],
            "budget_fraction_source": row["budget_fraction_source"],
            "loss_budget_dollars": row["loss_budget_dollars"],
            "derivation": row["derivation"],
            "caps": caps,
            "per_greek": per_greek,
            "would_block": row_would_block,
            "blocking": blocking,
            "unavailable_greeks": unavailable_greeks,
        })

    return {
        "enabled": True,
        "available": True,
        "basis": "portfolio_greeks",
        "corroborated_by": "canonical_signed_aggregate (complete + sign-agreement)",
        "note": (
            "OBSERVE-ONLY: arms no cap, rejects no entry, scales no size, writes "
            "no alert; a would_block is a counterfactual, not an action."
        ),
        "size_multiplier": None,
        "size_multiplier_note": (
            "omitted — no greek→sizing semantic exists in the envelope; the "
            "sizing_multiplier is weekly-loss-driven and independent of greeks, so "
            "there is no honest greek-cap sizing counterfactual to report"
        ),
        "equity": round(float(equity), 2),
        "coverage": {
            "greeks_coverage_complete": bool(greeks_coverage.get("complete")),
            "canonical_complete": bool(canonical_greeks.get("complete")),
            "legs_total": greeks_coverage.get("legs_total"),
            "legs_with_greeks": greeks_coverage.get("legs_with_greeks"),
        },
        "book": _greek_cf_book_summary(positions),
        "greeks": greek_detail,
        "reference_rows": rows_out,
    }


def _log_greek_cf_flips(
    scope: Optional[str], counterfactual: Dict[str, Any]
) -> List[str]:
    """Emit ONE INFO line only when a reference row's would_block CHANGES.

    Dedup keyed on `scope` (an opt-in caller book identity, e.g.
    "monitor:<user>"). A None/empty scope NEVER logs — the jsonb field carries the
    evidence and the flip-log is the secondary, dedup-gated surface. Returns the
    list of flipped row names (test seam). The would_block state includes None
    (typed-unavailable), so a book crossing into or out of unavailability also
    flips exactly once.
    """
    if not scope:
        return []
    prior = _GREEK_CF_LAST_STATE.setdefault(scope, {})
    flipped: List[str] = []
    current: Dict[str, Any] = {}
    for row in counterfactual.get("reference_rows", []):
        name = row.get("name")
        would_block = row.get("would_block")
        current[name] = would_block
        if name not in prior or prior[name] != would_block:
            flipped.append(name)
        prior[name] = would_block
    if flipped:
        logger.info(
            "[GREEK_CAP_CF] scope=%s would_block state changed on rows=%s "
            "(OBSERVE-ONLY, no enforcement): %s",
            scope, flipped, {n: current[n] for n in flipped},
        )
    return flipped


def check_concentration(
    positions: List[Dict],
    total_risk: float,
    config: EnvelopeConfig,
    event_signals: Optional[Dict] = None,
) -> tuple:
    """Check concentration limits."""
    violations = []
    concentration = {}

    if total_risk <= 0:
        return violations, concentration

    # Symbol concentration
    by_symbol: Dict[str, float] = {}
    by_sector: Dict[str, float] = {}
    by_expiry: Dict[str, float] = {}
    earnings_count = 0

    from packages.quantum.risk.sector_mapping import canonical_sector

    for pos in positions:
        risk = _pos_risk(pos)
        symbol = _pos_field(pos, "symbol", "UNKNOWN")
        # Map raw SIC industry string to canonical GICS sector so a tech basket
        # (semis + software) aggregates to one bucket instead of fragmenting
        # across "SEMICONDUCTORS & RELATED DEVICES" / "SERVICES-PREPACKAGED
        # SOFTWARE" / etc. and evading the sector cap.
        sector = canonical_sector(_pos_field(pos, "sector", None))
        expiry = _pos_field(pos, "nearest_expiry", "")

        by_symbol[symbol] = by_symbol.get(symbol, 0) + risk
        by_sector[sector] = by_sector.get(sector, 0) + risk
        if expiry:
            by_expiry[expiry] = by_expiry.get(expiry, 0) + risk

        # Event concentration
        if event_signals:
            sig = event_signals.get(symbol)
            if sig:
                is_earnings = (
                    (hasattr(sig, "is_earnings_week") and sig.is_earnings_week)
                    or (isinstance(sig, dict) and sig.get("is_earnings_week"))
                )
                if is_earnings:
                    earnings_count += 1

    # Symbol max
    for sym, risk in by_symbol.items():
        pct = risk / total_risk
        if pct > config.max_single_symbol_pct:
            violations.append(EnvelopeViolation(
                envelope="concentration_symbol",
                limit=config.max_single_symbol_pct,
                actual=pct,
                severity=config.symbol_concentration_severity,
                message=f"{sym} is {pct:.0%} of risk (limit {config.max_single_symbol_pct:.0%})",
            ))

    max_sym_pct = max((r / total_risk for r in by_symbol.values()), default=0)
    concentration["max_symbol_pct"] = max_sym_pct

    # Sector max
    for sector, risk in by_sector.items():
        pct = risk / total_risk
        if pct > config.max_sector_pct:
            violations.append(EnvelopeViolation(
                envelope="concentration_sector",
                limit=config.max_sector_pct,
                actual=pct,
                severity="warn",
                message=f"Sector {sector} is {pct:.0%} of risk",
            ))

    max_sec_pct = max((r / total_risk for r in by_sector.values()), default=0)
    concentration["max_sector_pct"] = max_sec_pct

    # Expiry concentration
    for exp, risk in by_expiry.items():
        pct = risk / total_risk
        if pct > config.max_same_expiry_pct:
            violations.append(EnvelopeViolation(
                envelope="concentration_expiry",
                limit=config.max_same_expiry_pct,
                actual=pct,
                severity="warn",
                message=f"Expiry {exp} has {pct:.0%} of risk",
            ))

    max_exp_pct = max((r / total_risk for r in by_expiry.values()), default=0)
    concentration["max_expiry_pct"] = max_exp_pct

    # Earnings count
    concentration["earnings_positions"] = earnings_count
    if earnings_count > config.max_earnings_positions:
        violations.append(EnvelopeViolation(
            envelope="event_earnings_count",
            limit=float(config.max_earnings_positions),
            actual=float(earnings_count),
            severity="block",
            message=f"{earnings_count} earnings plays exceed limit {config.max_earnings_positions}",
        ))

    return violations, concentration


def check_loss_envelopes(
    equity: float,
    daily_pnl: float,
    weekly_pnl: float,
    positions: List[Dict],
    config: EnvelopeConfig,
    degraded_out: Optional[List[Dict]] = None,
    symbol_loss_stops_out: Optional[List[Dict]] = None,
) -> tuple:
    """Check daily/weekly/per-symbol loss limits.

    `degraded_out` (optional out-param, backward-compatible): when provided,
    positions whose mark was unpriceable this pass (``_mark_unpriceable``) are
    appended here and SKIPPED from the per-symbol loss decision — never
    force-closed on a stale/uncorroborated value, never silently treated as
    no-breach. The caller raises the loud degraded alert (#1035 policy).

    `symbol_loss_stops_out` (optional out-param): when provided, each PER-SYMBOL
    loss breach is appended as {cohort_id, symbol, position_id, realized_loss}
    — the structured protective-stop set the monitor turns into a re-entry
    cooldown. Daily/weekly/concentration never enter it.
    """
    violations = []
    force_close_ids = []
    loss_status = {}

    if equity <= 0:
        return violations, force_close_ids, loss_status

    # Helper: portfolio-wide breach closes all open positions. Daily and weekly
    # loss envelopes are aggregate signals — they don't identify a single bad
    # position, so the appropriate response is to close the book. Without this,
    # a severity=force_close violation with an empty force_close_ids list is
    # alert-only and intraday_risk_monitor has nothing to iterate.
    def _mark_all_positions_for_close():
        for pos in positions:
            pid = _pos_field(pos, "id", None)
            if pid and pid not in force_close_ids:
                force_close_ids.append(pid)

    # Daily loss
    daily_pct = daily_pnl / equity
    loss_status["daily_pnl_pct"] = daily_pct
    if daily_pct < -config.max_daily_loss_pct:
        violations.append(EnvelopeViolation(
            envelope="loss_daily",
            limit=config.max_daily_loss_pct,
            actual=abs(daily_pct),
            severity="force_close",
            message=f"Daily loss {daily_pct:.1%} breaches {-config.max_daily_loss_pct:.1%} limit",
        ))
        _mark_all_positions_for_close()

    # Weekly loss — catastrophic signal (was severity=warn, which was a bug:
    # at -190% weekly loss the message literally said "sizing reduced" while
    # the account was 1.9× underwater). Upgraded to force_close so the loss
    # envelope actually enforces. The sizing_multiplier ramp in
    # check_all_envelopes still handles the soft range (50-99% of limit).
    weekly_pct = weekly_pnl / equity
    loss_status["weekly_pnl_pct"] = weekly_pct
    if weekly_pct < -config.max_weekly_loss_pct:
        violations.append(EnvelopeViolation(
            envelope="loss_weekly",
            limit=config.max_weekly_loss_pct,
            actual=abs(weekly_pct),
            severity="force_close",
            message=f"Weekly loss {weekly_pct:.1%} breaches {-config.max_weekly_loss_pct:.1%} limit",
        ))
        _mark_all_positions_for_close()

    # Per-symbol loss
    symbol_max_loss = equity * config.max_per_symbol_loss_pct
    for pos in positions:
        # Fail-closed (#1035 asymmetric mark policy): a position we could not
        # price this pass must NOT have its per-symbol loss decided on a stale
        # value (act-on-stale) and must NOT be coerced to 0=no-breach by the
        # _pos_field `or 0` default (silent skip of protection). Record it as
        # degraded so the caller alerts loudly + retries next pass; do not
        # force-close on a value we can't trust. (Stage-2 robust policy:
        # last-good / conservative / marketable protective close.)
        if _pos_field(pos, "_mark_unpriceable", False):
            if degraded_out is not None:
                degraded_out.append({
                    "position_id": _pos_field(pos, "id", "unknown"),
                    "symbol": _pos_field(pos, "symbol", "?"),
                    "stale_unrealized_pl": float(_pos_field(pos, "unrealized_pl", 0)),
                })
            continue
        unrealized = float(_pos_field(pos, "unrealized_pl", 0))
        if unrealized < -symbol_max_loss:
            pos_id = _pos_field(pos, "id", "unknown")
            symbol = _pos_field(pos, "symbol", "?")
            force_close_ids.append(pos_id)
            violations.append(EnvelopeViolation(
                envelope="loss_per_symbol",
                limit=symbol_max_loss,
                actual=abs(unrealized),
                severity="force_close",
                message=f"{symbol} loss ${unrealized:.0f} exceeds ${symbol_max_loss:.0f} limit",
            ))
            # Structured protective-stop record for the re-entry cooldown writer
            # (cohort-keyed). Trigger-time loss (the value that tripped the
            # envelope), not the eventual fill.
            if symbol_loss_stops_out is not None:
                symbol_loss_stops_out.append({
                    "cohort_id": pos.get("cohort_id"),
                    "symbol": symbol,
                    "position_id": pos_id,
                    "realized_loss": unrealized,
                })

    return violations, force_close_ids, loss_status


def _finite_greek_value(greeks: Any, key: str) -> Optional[float]:
    """A single finite greek value, or None when MISSING.

    A missing key, None, bool, non-numeric, or non-finite value is a missing
    INPUT (typed unavailable) — never a silent 0 pretending the exposure was
    measured (H9: reject or flag, never fabricate). Shared by both greek
    readers in this module (check_greeks aggregation + the stress model), so
    an explicit-None or nonfinite greek can never raise out of an envelope
    evaluation nor be coerced to a fabricated zero.
    """
    if not isinstance(greeks, dict) or key not in greeks:
        return None
    value = greeks[key]
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def compute_stress_scenarios(
    positions: List[Dict],
    equity: float,
    config: EnvelopeConfig,
) -> tuple:
    """Compute portfolio P&L under stress scenarios, floored at the payoff bound.

    Model scenarios (linear estimates):
    - SPY down X%: delta-based loss estimate
    - VIX spike Y%: vega-based gain/loss estimate
    - Correlation-one: every structure at its exact canonical max loss

    **D2 FIX (signed greek aggregation — stress-lane residual):** each leg's
    delta/vega contribution is signed by its OWN direction via the canonical
    ``position_model._direction_sign`` (the same seam check_greeks/#1269 and
    normalize_position use — reuse, not a second BUY/SELL parser), so a long
    and a short leg NET instead of unsigned-ADD. The pre-fix
    ``greek * abs(qty)`` add treated a delta-hedged vertical/condor as if every
    leg pointed the same way; the payoff clamp bounded the result but a bounded
    phantom is still a dishonest measurement now that legs can carry real
    greeks (post-#1259). Magnitude scaling (``abs(qty) × 100``) is UNCHANGED —
    only the sign is added, applied exactly once. An unsignable side is
    rejected upstream by ``_pos_risk`` (unrepresentable structure → raise).

    Canonical-position consumer PR-3 (D5 closure): a defined-risk book cannot
    lose more than the sum of its structures' payoff max losses — arithmetic,
    not policy (position_model.clamp_stress_to_payoff, applied here at BOOK
    level: the sum of per-structure floors IS the book floor). A delta/vega
    extrapolation landing below -Σ max_loss_total is clamped to it; the raw
    value is preserved in results["<scenario>_raw"] so the phantom stays
    visible while it can no longer win the worst-case min() (the 06-17 MARA
    phantom class, in the stress lane).

    Typed unavailability (H9): a scenario whose greek inputs are missing on
    ANY leg is NOT computed — a partial sum is a fabricated total. The
    scenario key is omitted from `results` (never a placeholder 0) and
    recorded in the returned `unavailable` mapping as
    {reason, missing_field, legs_missing}. Production legs persist no greeks
    today (§8 double-dormancy), so spy_down/vix_spike are expected-unavailable
    there until stage-time greek population ships; correlation_one is always
    computable for a representable book and is itself the payoff bound.

    An unrepresentable or not-defined-risk structure raises
    PositionRiskUnavailable via _pos_risk — a bound is never fabricated for
    an unbounded structure.

    Returns (violations, results, unavailable).
    """
    violations = []
    results: Dict[str, float] = {}
    unavailable: Dict[str, Dict[str, Any]] = {}

    if not positions or equity <= 0:
        return violations, results, unavailable

    total_delta = 0.0
    total_vega = 0.0
    total_risk = 0.0
    delta_missing_legs = 0
    vega_missing_legs = 0

    for pos in positions:
        qty = float(_pos_field(pos, "quantity", 0))
        risk = _pos_risk(pos)
        total_risk += risk

        legs = pos.get("legs") or []
        for leg in legs:
            if not isinstance(leg, dict):
                # Unreadable leg: its greeks cannot be sourced. Unreachable
                # after a successful _pos_risk (normalization rejects
                # non-mapping legs) — kept as defense in depth.
                delta_missing_legs += 1
                vega_missing_legs += 1
                continue
            # D2 FIX (stress-lane residual): sign each leg's greek by its OWN
            # direction via the canonical authority
            # ``position_model._direction_sign`` — the SAME seam check_greeks
            # (#1269) and ``normalize_position`` reuse, never a second copy of
            # the BUY/SELL token logic. A long leg and a short leg now NET
            # instead of unsigned-ADD: the pre-fix ``delta * abs(qty) * 100``
            # summed a delta-hedged vertical as if BOTH legs pointed the same
            # way (a 2-leg vertical reported 2×|per-leg delta|; a 4-leg condor
            # 4×). The book was payoff-clamped so the number stayed
            # bounded-safe, but a bounded phantom is still a dishonest
            # measurement now that legs can carry real greeks (post-#1259).
            # Magnitude scaling is UNCHANGED — the stress lane uses the
            # hardcoded 100 multiplier and the POSITION quantity (leg-ratio D3
            # is its own lane); only the sign is new, applied exactly once.
            #
            # Defense in depth: an unsignable side is already rejected upstream
            # by ``_pos_risk`` (``normalize_position`` calls this exact helper
            # at :1006-1007), so a book with an unknown side raises
            # ``PositionRiskUnavailable`` before reaching here — never a
            # fabricated unsigned add (H9). This guard mirrors the non-dict-leg
            # guard above so a stray sign-parse can never break the envelope
            # check: the leg contributes nothing and the affected scenarios go
            # typed-unavailable.
            side_raw = (
                leg.get("action")
                if leg.get("action") is not None
                else leg.get("side")
            )
            try:
                sign = _direction_sign(side_raw)
            except PositionNormalizationError:
                delta_missing_legs += 1
                vega_missing_legs += 1
                continue
            greeks = leg.get("greeks") or pos.get("greeks") or {}
            delta = _finite_greek_value(greeks, "delta")
            vega = _finite_greek_value(greeks, "vega")
            if delta is None:
                delta_missing_legs += 1
            else:
                total_delta += sign * delta * abs(qty) * 100
            if vega is None:
                vega_missing_legs += 1
            else:
                total_vega += sign * vega * abs(qty) * 100

    # Payoff floor: Σ canonical max-loss totals (position-level, already
    # scaled by structure quantity and multiplier — never rescale). _pos_risk
    # raised above if any structure was unrepresentable or unbounded, so a
    # finite floor here is honest by construction.
    floor_total = -total_risk

    # SPY down scenario (delta-based linear model, clamped at the floor)
    spy_move = config.stress_spy_down_pct
    if delta_missing_legs == 0:
        spy_loss = total_delta * spy_move * -1  # Delta loss from down move
        if spy_loss < floor_total:
            results["spy_down_raw"] = spy_loss / equity
            logger.warning(
                "[STRESS_PAYOFF_CAP] spy_down raw stress $%.2f exceeds the "
                "defined-risk floor $%.2f — clamped to the payoff bound "
                "(D5 class)",
                spy_loss, floor_total,
            )
            spy_loss = floor_total
        results["spy_down"] = spy_loss / equity
    else:
        unavailable["spy_down"] = {
            "reason": "greeks_missing",
            "missing_field": "delta",
            "legs_missing": delta_missing_legs,
        }

    # VIX spike scenario (vega-based linear model, clamped at the floor)
    vix_move = config.stress_vix_spike_pct
    if vega_missing_legs == 0:
        vix_impact = total_vega * vix_move * 100  # Vega * vol points
        if vix_impact < floor_total:
            results["vix_spike_raw"] = vix_impact / equity
            logger.warning(
                "[STRESS_PAYOFF_CAP] vix_spike raw stress $%.2f exceeds the "
                "defined-risk floor $%.2f — clamped to the payoff bound "
                "(D5 class)",
                vix_impact, floor_total,
            )
            vix_impact = floor_total
        results["vix_spike"] = vix_impact / equity
    else:
        unavailable["vix_spike"] = {
            "reason": "greeks_missing",
            "missing_field": "vega",
            "legs_missing": vega_missing_legs,
        }

    # Correlation-one: all positions at their exact canonical max loss
    # simultaneously. This IS the payoff bound — the cap binds here by
    # identity.
    corr_one_loss = -total_risk  # Worst case
    results["correlation_one"] = corr_one_loss / equity

    # Worst case over the scenarios that were honestly computable. The raw
    # (pre-clamp) values never enter — the clamp exists precisely so a
    # phantom extrapolation cannot win this min().
    worst = min(
        results[key]
        for key in ("spy_down", "vix_spike", "correlation_one")
        if key in results
    )
    results["worst_case"] = worst

    if unavailable:
        # INFO, not WARNING: greek absence is the ledgered §8 standing
        # condition on every production book; the typed field is the flag.
        logger.info(
            "[STRESS] scenarios unavailable (typed, no fabricated 0): %s",
            {k: v["legs_missing"] for k, v in unavailable.items()},
        )

    if abs(worst) > config.max_stress_loss_pct:
        violations.append(EnvelopeViolation(
            envelope="stress_scenario",
            limit=config.max_stress_loss_pct,
            actual=abs(worst),
            severity="warn",
            message=f"Worst stress scenario loss {worst:.1%} exceeds {-config.max_stress_loss_pct:.1%} limit",
        ))

    return violations, results, unavailable


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def check_all_envelopes(
    positions: List[Dict],
    equity: float,
    daily_pnl: float = 0.0,
    weekly_pnl: float = 0.0,
    config: Optional[EnvelopeConfig] = None,
    event_signals: Optional[Dict] = None,
    observe_scope: Optional[str] = None,
) -> EnvelopeCheckResult:
    """
    Run all envelope checks against current portfolio state.

    Args:
        positions: List of open position dicts
        equity: Total portfolio equity (net_liq)
        daily_pnl: Today's unrealized + realized P&L
        weekly_pnl: This week's cumulative P&L
        config: EnvelopeConfig (default: from env vars)
        event_signals: Dict of symbol → EventSignal for event concentration
        observe_scope: Optional stable book identity (e.g. "monitor:<user>") used
            ONLY to dedup the OBSERVE-ONLY greek-cap counterfactual flip-log — a
            line fires only when a reference row's would_block CHANGES for that
            scope. None (default) never logs; the counterfactual jsonb field is
            populated regardless. Affects NO decision, NO violation, NO sizing.

    Returns:
        EnvelopeCheckResult with all violations and recommendations
    """
    if config is None:
        config = EnvelopeConfig.from_env()

    result = EnvelopeCheckResult()
    total_risk = sum(_pos_risk(p) for p in positions)

    # 1. Greeks (null-safe; coverage typed onto the result — a partial
    #    aggregate is flagged, never a fabricated whole-book sum)
    greek_violations, greeks = check_greeks(
        positions, config, coverage_out=result.greeks_coverage
    )
    result.portfolio_greeks = greeks
    for v in greek_violations:
        result.add_violation(v)

    # 1b. Canonical signed portfolio greeks (OBSERVE-ONLY telemetry, alongside
    #     the D2-defective portfolio_greeks above). Fail-soft: a computation
    #     error here must NEVER break the envelope check — it modulates nothing.
    try:
        result.canonical_greeks = aggregate_canonical_greeks(positions)
    except Exception as exc:  # observe-only; never break the envelope check
        logger.warning(
            "[CANONICAL_GREEKS] observe-only aggregate failed: %s", exc
        )
        result.canonical_greeks = {"complete": False, "error": str(exc)}

    # 1c. Greek-cap ALERT-ONLY counterfactual (OBSERVE-ONLY; owner items 9+11).
    #     Sits beside canonical_greeks — arms no cap, rejects no entry, scales no
    #     size, writes no alert, reads no cap flag. Fail-soft: a computation error
    #     here must NEVER break the envelope check. The optional observe_scope only
    #     gates the dedup flip-log (INFO on state change); the jsonb field is
    #     populated either way.
    try:
        result.greek_cap_counterfactual = compute_greek_cap_counterfactual(
            portfolio_greeks=result.portfolio_greeks,
            greeks_coverage=result.greeks_coverage,
            canonical_greeks=result.canonical_greeks,
            positions=positions,
            equity=equity,
            config=config,
        )
        _log_greek_cf_flips(observe_scope, result.greek_cap_counterfactual)
    except Exception as exc:  # observe-only; never break the envelope check
        logger.warning(
            "[GREEK_CAP_CF] observe-only counterfactual failed: %s", exc
        )
        result.greek_cap_counterfactual = {
            "enabled": True, "available": False, "error": str(exc),
        }

    # 2. Concentration
    conc_violations, concentration = check_concentration(
        positions, total_risk, config, event_signals
    )
    result.concentration = concentration
    for v in conc_violations:
        result.add_violation(v)

    # 3. Loss envelopes
    loss_violations, force_close_ids, loss_status = check_loss_envelopes(
        equity, daily_pnl, weekly_pnl, positions, config,
        degraded_out=result.degraded_per_symbol,
        symbol_loss_stops_out=result.symbol_loss_stops,
    )
    result.loss_status = loss_status
    result.force_close_ids = force_close_ids
    for v in loss_violations:
        result.add_violation(v)

    # 4. Stress scenarios (payoff-capped at Σ canonical max loss; greek
    #    scenarios are typed-unavailable when inputs are missing — see
    #    compute_stress_scenarios)
    stress_violations, stress_results, stress_unavailable = compute_stress_scenarios(
        positions, equity, config
    )
    result.stress_results = stress_results
    result.stress_unavailable = stress_unavailable
    for v in stress_violations:
        result.add_violation(v)

    # 5. Compute sizing multiplier
    # Approaching weekly loss limit → reduce sizing proportionally
    if equity > 0 and weekly_pnl < 0:
        weekly_pct = abs(weekly_pnl) / equity
        if weekly_pct > config.max_weekly_loss_pct * 0.5:
            # Ramp down: at 50% of limit → 0.8x, at 100% → 0.3x
            ratio = weekly_pct / config.max_weekly_loss_pct
            result.sizing_multiplier = max(0.3, 1.0 - ratio * 0.7)

    logger.info(
        f"risk_envelope: positions={len(positions)} equity={equity:.0f} "
        f"violations={len(result.violations)} passed={result.passed} "
        f"sizing_mult={result.sizing_multiplier:.2f}"
    )

    return result


def check_new_position(
    new_symbol: str,
    new_risk: float,
    existing_positions: List[Dict],
    equity: float,
    config: Optional[EnvelopeConfig] = None,
    event_signals: Optional[Dict] = None,
) -> EnvelopeCheckResult:
    """
    Check if adding a new position would breach any envelope.

    Simulates the portfolio with the new position added and runs
    all envelope checks. Used by the suggestion pipeline before sizing.

    Args:
        new_symbol: Symbol of the candidate position
        new_risk: Estimated risk of the new position in dollars
        existing_positions: Current open positions
        equity: Total portfolio equity
        config: EnvelopeConfig
        event_signals: Event signals for concentration check

    Returns:
        EnvelopeCheckResult — if .passed is False, the position should be
        rejected or reduced.
    """
    if config is None:
        config = EnvelopeConfig.from_env()

    # Simulate adding the new position
    simulated = list(existing_positions)
    simulated.append({
        "id": "candidate",
        "symbol": new_symbol,
        "quantity": 1,
        "max_credit": new_risk / 100,  # Convert back to per-contract
        "unrealized_pl": 0,
        "status": "open",
    })

    result = check_all_envelopes(
        positions=simulated,
        equity=equity,
        config=config,
        event_signals=event_signals,
    )

    # Filter to violations caused by the new position
    relevant = [v for v in result.violations
                if new_symbol in v.message or v.envelope.startswith("concentration")]

    if relevant:
        logger.info(
            f"risk_envelope_new_position: symbol={new_symbol} risk=${new_risk:.0f} "
            f"violations={[v.envelope for v in relevant]}"
        )

    return result
