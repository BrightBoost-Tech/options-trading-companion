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
) -> tuple:
    """Check portfolio-level Greeks limits."""
    violations = []
    total_delta = 0.0
    total_gamma = 0.0
    total_vega = 0.0
    total_theta = 0.0

    for pos in positions:
        qty = float(_pos_field(pos, "quantity", 0))
        legs = pos.get("legs") or []

        for leg in legs:
            if not isinstance(leg, dict):
                continue
            greeks = leg.get("greeks") or pos.get("greeks") or {}
            d = float(greeks.get("delta", 0)) * abs(qty) * 100
            g = float(greeks.get("gamma", 0)) * abs(qty) * 100
            v = float(greeks.get("vega", 0)) * abs(qty) * 100
            t = float(greeks.get("theta", 0)) * abs(qty) * 100

            total_delta += d
            total_gamma += g
            total_vega += v
            total_theta += t

    greeks = {
        "delta": total_delta,
        "gamma": total_gamma,
        "vega": total_vega,
        "theta": total_theta,
    }

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


def _stress_greek_value(greeks: Any, key: str) -> Optional[float]:
    """Finite greek input for the stress model, or None when MISSING.

    A missing key, None, bool, non-numeric, or non-finite value is a missing
    INPUT (typed unavailable at the scenario level) — never a silent 0
    pretending the exposure was measured (H9: reject or flag, never
    fabricate).
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

    Model scenarios (linear estimates, unchanged from the legacy model):
    - SPY down X%: delta-based loss estimate
    - VIX spike Y%: vega-based gain/loss estimate
    - Correlation-one: every structure at its exact canonical max loss

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
            greeks = leg.get("greeks") or pos.get("greeks") or {}
            delta = _stress_greek_value(greeks, "delta")
            vega = _stress_greek_value(greeks, "vega")
            if delta is None:
                delta_missing_legs += 1
            else:
                total_delta += delta * abs(qty) * 100
            if vega is None:
                vega_missing_legs += 1
            else:
                total_vega += vega * abs(qty) * 100

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

    Returns:
        EnvelopeCheckResult with all violations and recommendations
    """
    if config is None:
        config = EnvelopeConfig.from_env()

    result = EnvelopeCheckResult()
    total_risk = sum(_pos_risk(p) for p in positions)

    # 1. Greeks
    greek_violations, greeks = check_greeks(positions, config)
    result.portfolio_greeks = greeks
    for v in greek_violations:
        result.add_violation(v)

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
