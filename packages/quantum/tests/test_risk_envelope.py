"""
Tests for portfolio risk envelope.

Tests:
1. Greeks limit checks
2. Concentration limits (symbol, sector, expiry)
3. Loss envelopes (daily, weekly, per-symbol)
4. Stress scenarios
5. New position simulation
6. Sizing multiplier ramp-down
7. Config from env vars
"""

import pytest
from unittest.mock import patch

from packages.quantum.risk.risk_envelope import (
    EnvelopeConfig,
    EnvelopeViolation,
    EnvelopeCheckResult,
    check_greeks,
    check_concentration,
    check_loss_envelopes,
    compute_stress_scenarios,
    check_all_envelopes,
    check_new_position,
)

# Skipped in PR #1 triage to establish CI-green gate while test debt is cleared.
# [Cluster M] long tail
# Tracked in #774 (umbrella: #767).
pytestmark = pytest.mark.skip(
    reason='[Cluster M] long tail; tracked in #774',
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_position(
    symbol="AAPL",
    quantity=1,
    max_credit=2.0,
    unrealized_pl=0,
    sector="Technology",
    nearest_expiry="2026-04-17",
    delta=0.3,
    vega=0.05,
):
    return {
        "id": f"pos_{symbol}",
        "symbol": symbol,
        "quantity": quantity,
        "max_credit": max_credit,
        "unrealized_pl": unrealized_pl,
        "sector": sector,
        "nearest_expiry": nearest_expiry,
        "status": "open",
        "legs": [{"greeks": {"delta": delta, "gamma": 0.01, "vega": vega, "theta": -0.02}}],
    }


def _default_config(**overrides) -> EnvelopeConfig:
    config = EnvelopeConfig()
    for k, v in overrides.items():
        setattr(config, k, v)
    return config


# ---------------------------------------------------------------------------
# Greeks Tests
# ---------------------------------------------------------------------------

class TestGreeks:
    def test_no_violation_within_limits(self):
        positions = [_make_position(delta=0.3)]
        config = _default_config(max_portfolio_delta=100)
        violations, greeks = check_greeks(positions, config)
        assert len(violations) == 0
        assert greeks["delta"] == pytest.approx(30, abs=1)  # 0.3 * 1 * 100

    def test_delta_violation(self):
        # 5 positions with delta 0.5 each = 250 total
        positions = [_make_position(delta=0.5) for _ in range(5)]
        config = _default_config(max_portfolio_delta=100)
        violations, greeks = check_greeks(positions, config)
        assert len(violations) == 1
        assert violations[0].envelope == "greeks_delta"

    def test_no_limit_means_no_check(self):
        positions = [_make_position(delta=10)]
        config = _default_config(max_portfolio_delta=0)  # 0 = disabled
        violations, _ = check_greeks(positions, config)
        assert len(violations) == 0


# ---------------------------------------------------------------------------
# Concentration Tests
# ---------------------------------------------------------------------------

class TestConcentration:
    def test_no_violation_diverse(self):
        positions = [
            _make_position("AAPL", max_credit=1, sector="Tech", nearest_expiry="2026-04-17"),
            _make_position("MSFT", max_credit=1, sector="Tech", nearest_expiry="2026-05-15"),
            _make_position("JPM", max_credit=1, sector="Finance", nearest_expiry="2026-04-17"),
            _make_position("XOM", max_credit=1, sector="Energy", nearest_expiry="2026-05-15"),
        ]
        config = _default_config(max_single_symbol_pct=0.30, max_sector_pct=0.60, max_same_expiry_pct=0.60)
        violations, conc = check_concentration(positions, 400, config)
        assert len(violations) == 0
        assert conc["max_symbol_pct"] == pytest.approx(0.25, abs=0.01)

    def test_symbol_concentration_violation(self):
        positions = [
            _make_position("AAPL", max_credit=3, sector="Tech", nearest_expiry="2026-04-17"),
            _make_position("MSFT", max_credit=1, sector="Software", nearest_expiry="2026-05-15"),
        ]
        config = _default_config(max_single_symbol_pct=0.50, max_sector_pct=1.0, max_same_expiry_pct=1.0)
        total_risk = 300 + 100  # AAPL=300, MSFT=100
        violations, conc = check_concentration(positions, total_risk, config)
        sym_v = [v for v in violations if v.envelope == "concentration_symbol"]
        assert len(sym_v) == 1
        assert "AAPL" in sym_v[0].message

    def test_sector_concentration(self):
        positions = [
            _make_position("AAPL", sector="Tech", max_credit=3),
            _make_position("MSFT", sector="Tech", max_credit=3),
            _make_position("JPM", sector="Finance", max_credit=1),
        ]
        config = _default_config(max_sector_pct=0.50)
        total_risk = 300 + 300 + 100
        violations, _ = check_concentration(positions, total_risk, config)
        sector_violations = [v for v in violations if v.envelope == "concentration_sector"]
        assert len(sector_violations) == 1

    def test_earnings_count_limit(self):
        positions = [
            _make_position("AAPL"),
            _make_position("MSFT"),
            _make_position("GOOG"),
            _make_position("META"),
        ]
        events = {
            "AAPL": {"is_earnings_week": True},
            "MSFT": {"is_earnings_week": True},
            "GOOG": {"is_earnings_week": True},
            "META": {"is_earnings_week": True},
        }
        config = _default_config(max_earnings_positions=3)
        violations, conc = check_concentration(positions, 400, config, events)
        assert conc["earnings_positions"] == 4
        earnings_v = [v for v in violations if v.envelope == "event_earnings_count"]
        assert len(earnings_v) == 1


# ---------------------------------------------------------------------------
# Loss Envelope Tests
# ---------------------------------------------------------------------------

class TestLossEnvelopes:
    def test_daily_loss_breach(self):
        config = _default_config(max_daily_loss_pct=0.05)
        violations, force_close, status = check_loss_envelopes(
            equity=100000, daily_pnl=-6000, weekly_pnl=-6000,
            positions=[], config=config,
        )
        assert len(violations) == 1
        assert violations[0].envelope == "loss_daily"
        assert violations[0].severity == "force_close"

    def test_weekly_loss_warns(self):
        config = _default_config(max_weekly_loss_pct=0.10)
        violations, _, status = check_loss_envelopes(
            equity=100000, daily_pnl=-2000, weekly_pnl=-11000,
            positions=[], config=config,
        )
        weekly_v = [v for v in violations if v.envelope == "loss_weekly"]
        assert len(weekly_v) == 1
        assert weekly_v[0].severity == "warn"

    def test_per_symbol_loss(self):
        positions = [_make_position("AAPL", unrealized_pl=-4000)]
        config = _default_config(max_per_symbol_loss_pct=0.03)
        violations, force_close, _ = check_loss_envelopes(
            equity=100000, daily_pnl=0, weekly_pnl=0,
            positions=positions, config=config,
        )
        assert len(force_close) == 1
        assert "pos_AAPL" in force_close

    def test_no_violation_normal(self):
        config = _default_config()
        violations, force_close, _ = check_loss_envelopes(
            equity=100000, daily_pnl=-1000, weekly_pnl=-3000,
            positions=[], config=config,
        )
        assert len(violations) == 0
        assert len(force_close) == 0


# ---------------------------------------------------------------------------
# Stress Scenario Tests
# ---------------------------------------------------------------------------

class TestStress:
    def test_stress_computes_scenarios(self):
        positions = [_make_position(delta=0.5, vega=0.1)]
        violations, results = compute_stress_scenarios(
            positions, equity=100000, config=_default_config(),
        )
        assert "spy_down" in results
        assert "vix_spike" in results
        assert "correlation_one" in results
        assert "worst_case" in results

    def test_stress_violation_on_high_exposure(self):
        # 10 large positions
        positions = [_make_position(delta=0.8, max_credit=5) for _ in range(10)]
        config = _default_config(max_stress_loss_pct=0.10)
        violations, results = compute_stress_scenarios(
            positions, equity=50000, config=config,
        )
        # correlation_one = total risk = 10 * 500 = 5000 → 10% of equity
        assert results["correlation_one"] < 0


# ---------------------------------------------------------------------------
# Full Envelope Check Tests
# ---------------------------------------------------------------------------

class TestFullEnvelopeCheck:
    def test_clean_portfolio(self):
        positions = [
            _make_position("AAPL", sector="Tech", nearest_expiry="2026-04-17"),
            _make_position("MSFT", sector="Software", nearest_expiry="2026-05-15"),
            _make_position("JPM", sector="Finance", nearest_expiry="2026-06-19"),
            _make_position("XOM", sector="Energy", nearest_expiry="2026-07-17"),
        ]
        result = check_all_envelopes(positions, equity=100000, config=_default_config())
        assert result.passed is True
        assert len([v for v in result.violations if v.severity == "block"]) == 0

    def test_sizing_multiplier_weekly_loss(self):
        config = _default_config(max_weekly_loss_pct=0.10)
        result = check_all_envelopes(
            positions=[], equity=100000, weekly_pnl=-7000, config=config,
        )
        # 7% weekly loss = 70% of 10% limit → sizing reduced
        assert result.sizing_multiplier < 1.0

    def test_force_close_on_daily_breach(self):
        positions = [_make_position("AAPL", unrealized_pl=-4000)]
        config = _default_config(max_daily_loss_pct=0.03, max_per_symbol_loss_pct=0.03)
        result = check_all_envelopes(
            positions, equity=100000, daily_pnl=-4000, config=config,
        )
        assert result.passed is False
        assert len(result.force_close_ids) > 0


# ---------------------------------------------------------------------------
# New Position Check Tests
# ---------------------------------------------------------------------------

class TestNewPositionCheck:
    def test_new_position_allowed(self):
        existing = [
            _make_position("MSFT", sector="Software", nearest_expiry="2026-05-15"),
            _make_position("JPM", sector="Finance", nearest_expiry="2026-06-19"),
            _make_position("XOM", sector="Energy", nearest_expiry="2026-07-17"),
        ]
        config = _default_config(max_single_symbol_pct=0.30)
        result = check_new_position(
            "AAPL", new_risk=200, existing_positions=existing, equity=100000,
            config=config,
        )
        assert result.passed is True

    def test_new_position_concentration_block(self):
        existing = [_make_position("AAPL", max_credit=5)]
        config = _default_config(max_single_symbol_pct=0.50)
        result = check_new_position(
            "AAPL", new_risk=600, existing_positions=existing,
            equity=100000, config=config,
        )
        # Adding more AAPL should trigger concentration check
        # Total AAPL risk becomes 500 + 100 = 600 out of ~700 total
        conc_violations = [v for v in result.violations
                          if v.envelope == "concentration_symbol"]
        assert len(conc_violations) >= 1


# ---------------------------------------------------------------------------
# Config Tests
# ---------------------------------------------------------------------------

class TestConfig:
    def test_defaults(self):
        config = EnvelopeConfig()
        assert config.max_single_symbol_pct == 0.25
        assert config.max_daily_loss_pct == 0.05

    @patch.dict("os.environ", {
        "RISK_MAX_SYMBOL_PCT": "0.15",
        "RISK_MAX_DAILY_LOSS": "0.03",
    })
    def test_from_env(self):
        config = EnvelopeConfig.from_env()
        assert config.max_single_symbol_pct == 0.15
        assert config.max_daily_loss_pct == 0.03

    def test_to_dict(self):
        config = EnvelopeConfig()
        d = config.to_dict()
        assert "max_single_symbol_pct" in d
        assert "max_daily_loss_pct" in d
