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
        }


# ---------------------------------------------------------------------------
# Position helpers
# ---------------------------------------------------------------------------

def _pos_field(pos: Dict, key: str, default: Any = 0.0) -> Any:
    """Safely extract a field from a position dict."""
    return pos.get(key) or default


def _pos_risk(pos: Dict) -> float:
    """Estimate risk usage of a position in dollars."""
    max_credit = float(_pos_field(pos, "max_credit", 0))
    qty = abs(float(_pos_field(pos, "quantity", 1)))
    entry = float(_pos_field(pos, "avg_entry_price", 0))

    if max_credit > 0:
        return max_credit * qty * 100  # Credit spreads: risk ≈ max_credit * 100 per contract
    if entry > 0:
        return entry * qty * 100
    return 0.0


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
                severity="block",
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
) -> tuple:
    """Check daily/weekly/per-symbol loss limits."""
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

    return violations, force_close_ids, loss_status


def compute_stress_scenarios(
    positions: List[Dict],
    equity: float,
    config: EnvelopeConfig,
) -> tuple:
    """
    Compute portfolio P&L under stress scenarios.

    Simplified stress model:
    - SPY down X%: delta-based loss estimate
    - VIX spike Y%: vega-based gain/loss estimate
    - Correlation-one: all positions move against you
    """
    violations = []
    results = {}

    if not positions or equity <= 0:
        return violations, results

    total_delta = 0.0
    total_vega = 0.0
    total_risk = 0.0

    for pos in positions:
        qty = float(_pos_field(pos, "quantity", 0))
        risk = _pos_risk(pos)
        total_risk += risk

        legs = pos.get("legs") or []
        for leg in legs:
            if isinstance(leg, dict):
                greeks = leg.get("greeks") or pos.get("greeks") or {}
                total_delta += float(greeks.get("delta", 0)) * abs(qty) * 100
                total_vega += float(greeks.get("vega", 0)) * abs(qty) * 100

    # SPY down scenario
    spy_move = config.stress_spy_down_pct
    spy_loss = total_delta * spy_move * -1  # Delta loss from down move
    spy_loss_pct = spy_loss / equity if equity > 0 else 0
    results["spy_down"] = spy_loss_pct

    # VIX spike scenario (vega impact)
    vix_move = config.stress_vix_spike_pct
    vix_impact = total_vega * vix_move * 100  # Vega * vol points
    vix_impact_pct = vix_impact / equity if equity > 0 else 0
    results["vix_spike"] = vix_impact_pct

    # Correlation-one: all positions at max loss simultaneously
    corr_one_loss = -total_risk  # Worst case
    corr_one_pct = corr_one_loss / equity if equity > 0 else 0
    results["correlation_one"] = corr_one_pct

    # Check stress limits
    worst = min(spy_loss_pct, vix_impact_pct, corr_one_pct)
    results["worst_case"] = worst

    if abs(worst) > config.max_stress_loss_pct:
        violations.append(EnvelopeViolation(
            envelope="stress_scenario",
            limit=config.max_stress_loss_pct,
            actual=abs(worst),
            severity="warn",
            message=f"Worst stress scenario loss {worst:.1%} exceeds {-config.max_stress_loss_pct:.1%} limit",
        ))

    return violations, results


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
        equity, daily_pnl, weekly_pnl, positions, config
    )
    result.loss_status = loss_status
    result.force_close_ids = force_close_ids
    for v in loss_violations:
        result.add_violation(v)

    # 4. Stress scenarios
    stress_violations, stress_results = compute_stress_scenarios(
        positions, equity, config
    )
    result.stress_results = stress_results
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
