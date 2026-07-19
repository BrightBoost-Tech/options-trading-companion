"""Pure-engine battery for the continuous tier-taper (Lane D, DARK).

Covers: source-of-truth drift guards, interpolation continuity, band edges,
outside-band identity, monotonicity-on-equity-fall (the invariant),
per-trade-ceiling fraction monotonicity, SHOCK-ceiling preservation,
hysteresis transitions (both directions) + fail-closed seed, verdict
semantics, standard-tier out-of-scope, prior-state extraction, and purity.

The engine is PURE — every test drives the real production functions in
``packages.quantum.services.analytics.tier_taper`` and asserts on OUTPUT.
"""
import json
import math

import pytest

from packages.quantum.services.analytics import tier_taper as tt
from packages.quantum.services.analytics.small_account_compounder import (
    SmallAccountCompounder,
)
from packages.quantum.services import portfolio_allocator as pa


# ── Drift guards: anchors + regime map must equal the source of truth ────
class TestDriftGuards:
    def test_anchors_match_source_of_truth(self):
        tiers = {t.name: t for t in SmallAccountCompounder.TIERS}
        micro, small = tiers["micro"], tiers["small"]
        # Micro: single-trade 0.90 slot, one position.
        assert tt.MICRO_ENVELOPE_PCT == pytest.approx(micro.base_risk_pct)
        assert tt.MICRO_ENVELOPE_PCT == pytest.approx(0.90)
        assert tt.MICRO_PER_TRADE_CEILING_PCT == pytest.approx(0.90)
        assert tt.MICRO_MAX_CONCURRENT == micro.max_trades == 1
        # Small: PortfolioAllocator envelope / ceiling / concurrency.
        assert tt.SMALL_ENVELOPE_PCT == pytest.approx(pa.GLOBAL_ENVELOPE_PCT)
        assert tt.SMALL_PER_TRADE_CEILING_PCT == pytest.approx(
            pa.PER_TRADE_CEILING_PCT)
        assert tt.SMALL_MAX_CONCURRENT == pa.MAX_CONCURRENT_POSITIONS
        assert tt.SMALL_MAX_CONCURRENT == small.max_trades == 4

    def test_regime_mult_matches_allocator(self):
        assert tt._REGIME_MULT == pa._REGIME_MULT

    def test_boundary_matches_get_tier_cliff(self):
        # get_tier: micro [0,1000), small [1000,5000).
        assert SmallAccountCompounder.get_tier(999.99).name == "micro"
        assert SmallAccountCompounder.get_tier(1000.0).name == "small"
        assert tt.BOUNDARY == 1000.0
        assert tt.BAND_LO == 900.0 and tt.BAND_HI == 1100.0
        assert tt.HYST_LO == 950.0 and tt.HYST_HI == 1050.0


# ── Interpolation continuity ─────────────────────────────────────────────
class TestInterpolationContinuity:
    def test_taper_fraction_edges(self):
        assert tt.taper_fraction(900.0) == 0.0
        assert tt.taper_fraction(1100.0) == 1.0
        assert tt.taper_fraction(1000.0) == pytest.approx(0.5)

    def test_taper_fraction_monotone_and_bounded(self):
        prev = -1.0
        for e in range(800, 1201, 5):
            t = tt.taper_fraction(float(e))
            assert 0.0 <= t <= 1.0
            assert t >= prev - 1e-12
            prev = t

    def test_envelope_pct_continuous_at_band_edges(self):
        # Approaching 900 from inside → micro 0.90; approaching 1100 → 0.85.
        lo = tt.decide(900.0 + 1e-6).proposed.envelope_pct
        assert lo == pytest.approx(0.90, abs=1e-4)
        hi = tt.decide(1100.0 - 1e-6).proposed.envelope_pct
        assert hi == pytest.approx(0.85, abs=1e-4)
        # Exact edges resolve to the raw anchors (no jump).
        assert tt.decide(900.0).proposed.envelope_pct == pytest.approx(0.90)
        assert tt.decide(1100.0).proposed.envelope_pct == pytest.approx(0.85)

    def test_proposed_envelope_no_discontinuity_across_boundary(self):
        # The RAW cliff jumps 0.90→0.85 at $1000; the taper must not.
        below = tt.decide(999.999).proposed.envelope_pct
        above = tt.decide(1000.001).proposed.envelope_pct
        assert abs(above - below) < 1e-4  # continuous through the boundary


# ── Band edges + in_band flag ────────────────────────────────────────────
class TestBandEdges:
    def test_in_band_strict_interior(self):
        assert tt.decide(900.0).in_band is False   # edge = outside (identity)
        assert tt.decide(1100.0).in_band is False
        assert tt.decide(901.0).in_band is True
        assert tt.decide(1099.0).in_band is True
        assert tt.decide(1000.0).in_band is True

    def test_edge_params_equal_raw(self):
        for e in (900.0, 1100.0):
            d = tt.decide(e)
            assert d.current == d.proposed
            assert d.verdict == "identical"


# ── Outside-band identity (preserve current behavior exactly) ────────────
class TestOutsideBandIdentity:
    @pytest.mark.parametrize("e", [1.0, 500.0, 800.0, 899.99, 900.0,
                                    1100.0, 1100.01, 1200.0, 2500.0, 4999.0])
    def test_proposed_equals_current_outside_band(self, e):
        d = tt.decide(e, "normal")
        assert d.proposed == d.current
        assert d.verdict == "identical"
        assert d.taper_applied is False
        # dollars identical too
        assert d.proposed_envelope_dollars == pytest.approx(
            d.current_envelope_dollars)

    def test_identity_holds_across_regimes_outside_band(self):
        for reg in tt._REGIME_MULT:
            d = tt.decide(700.0, reg)
            assert d.proposed_envelope_dollars == pytest.approx(
                d.current_envelope_dollars)


# ── Monotonicity — THE invariant (never increases dollar risk on a fall) ─
class TestMonotonicity:
    def _sweep(self, regime):
        return [tt.decide(e / 10.0, regime)
                for e in range(6000, 13001, 1)]  # $600.0..$1300.1 step $0.1

    @pytest.mark.parametrize("regime", ["normal", "shock", "elevated",
                                         "suppressed"])
    def test_total_envelope_dollars_non_decreasing(self, regime):
        prev = -1.0
        for d in self._sweep(regime):
            cur = d.proposed_envelope_dollars
            assert cur >= prev - 1e-9, (
                f"monotonicity broken at equity={d.equity} regime={regime}: "
                f"{cur} < {prev}")
            prev = cur

    def test_taper_removes_raw_cliff_violation(self):
        # RAW: total deployable DROPS crossing $1000 upward (rises when
        # equity FALLS) — the violation. TAPER: never.
        raw_lo = tt.decide(999.0).current_envelope_dollars   # 999*0.90
        raw_hi = tt.decide(1001.0).current_envelope_dollars  # 1001*0.85
        assert raw_lo > raw_hi  # raw cliff: equity up → dollars DOWN (bad)

        tap_lo = tt.decide(999.0).proposed_envelope_dollars
        tap_hi = tt.decide(1001.0).proposed_envelope_dollars
        assert tap_hi >= tap_lo - 1e-9  # taper: equity up → dollars up/flat

    def test_equity_fall_never_increases_deployable(self):
        # Direct statement of the invariant across the band, both regimes.
        for regime in ("normal", "shock"):
            e_high, e_low = 1080.0, 920.0
            d_high = tt.decide(e_high, regime).proposed_envelope_dollars
            d_low = tt.decide(e_low, regime).proposed_envelope_dollars
            assert d_low <= d_high + 1e-9


# ── Per-trade ceiling is a CAP: fraction monotone non-increasing ─────────
class TestPerTradeCeiling:
    def test_per_trade_ceiling_pct_non_increasing(self):
        prev = 1e9
        for e in range(800, 1201, 5):
            pct = tt.decide(float(e)).proposed.per_trade_ceiling_pct
            assert pct <= prev + 1e-12
            prev = pct

    def test_per_trade_ceiling_within_tier_bounds(self):
        for e in range(901, 1100, 7):
            pct = tt.decide(float(e)).proposed.per_trade_ceiling_pct
            assert 0.36 - 1e-9 <= pct <= 0.90 + 1e-9


# ── SHOCK ceiling preserved ──────────────────────────────────────────────
class TestShockCeiling:
    def test_envelope_pct_bounded_by_adjacent_tier_caps(self):
        for e in range(850, 1151, 3):
            pct = tt.decide(float(e)).proposed.envelope_pct
            assert 0.85 - 1e-9 <= pct <= 0.90 + 1e-9

    def test_shock_multiplier_applied_unchanged(self):
        # Shock deployable == normal deployable × 0.5 (multiplier untouched).
        for e in (950.0, 1000.0, 1050.0):
            normal = tt.decide(e, "normal").proposed_envelope_dollars
            shock = tt.decide(e, "shock").proposed_envelope_dollars
            assert shock == pytest.approx(normal * 0.5)

    def test_regime_mult_values(self):
        assert tt.regime_mult("shock") == 0.5
        assert tt.regime_mult("normal") == 1.0
        assert tt.regime_mult("elevated") == 0.8
        assert tt.regime_mult("garbage") == 1.0  # unknown → do-no-harm


# ── Hysteresis: both directions + fail-closed seed ───────────────────────
class TestHysteresis:
    def test_cold_start_seed_is_raw_cliff(self):
        assert tt.resolve_tier_state(999.0, None) == ("micro",
                                                       "cold_start_raw_seed")
        assert tt.resolve_tier_state(1000.0, None) == ("small",
                                                       "cold_start_raw_seed")
        assert tt.resolve_tier_state(1001.0, None) == ("small",
                                                       "cold_start_raw_seed")

    @pytest.mark.parametrize("bad", [None, "standard", "STANDARD", "", "foo",
                                      123])
    def test_invalid_prior_state_fails_closed(self, bad):
        state, decision = tt.resolve_tier_state(1020.0, bad)
        assert decision == "cold_start_raw_seed"
        # 1020 >= boundary → raw seed small (current behavior, not loosened)
        assert state == "small"

    def test_hold_micro_until_upper_threshold(self):
        # From micro, stays micro through the band until equity >= 1050.
        for e in (960.0, 1000.0, 1049.999):
            assert tt.resolve_tier_state(e, "micro") == (
                "micro", "hold_micro")
        assert tt.resolve_tier_state(1050.0, "micro") == (
            "small", "flip_to_small")

    def test_hold_small_until_lower_threshold(self):
        # From small, stays small through the band until equity <= 950.
        for e in (1040.0, 1000.0, 950.001):
            assert tt.resolve_tier_state(e, "small") == (
                "small", "hold_small")
        assert tt.resolve_tier_state(950.0, "small") == (
            "micro", "flip_to_micro")

    def test_hysteresis_gap_prevents_thrash(self):
        # $999↔$1001 oscillation with memory never flips (both inside the
        # inner hold band).
        state = "micro"
        for e in (1001.0, 999.0, 1001.0, 999.0, 1001.0):
            state, _ = tt.resolve_tier_state(e, state)
            assert state == "micro"  # held — no thrash
        state = "small"
        for e in (999.0, 1001.0, 999.0, 1001.0):
            state, _ = tt.resolve_tier_state(e, state)
            assert state == "small"  # held — no thrash

    def test_rising_walkthrough(self):
        # Seed micro at $920, ramp up: holds micro until $1050, then small.
        state = None
        seq = [920.0, 980.0, 1010.0, 1049.0, 1050.0, 1080.0]
        results = []
        for e in seq:
            state, dec = tt.resolve_tier_state(e, state)
            results.append(state)
        assert results == ["micro", "micro", "micro", "micro",
                           "small", "small"]

    def test_falling_walkthrough(self):
        # Seed small at $1080, ramp down: holds small until $950, then micro.
        state = None
        seq = [1080.0, 1010.0, 990.0, 951.0, 950.0, 920.0]
        results = []
        for e in seq:
            state, dec = tt.resolve_tier_state(e, state)
            results.append(state)
        assert results == ["small", "small", "small", "small",
                           "micro", "micro"]


# ── Verdict semantics ────────────────────────────────────────────────────
class TestVerdict:
    def test_tightens_below_boundary(self):
        # Below $1000 in-band: raw=micro 0.90, proposed<0.90 → tighten.
        d = tt.decide(960.0)
        assert d.verdict == "would_tighten"
        assert d.proposed_envelope_dollars < d.current_envelope_dollars

    def test_loosens_above_boundary(self):
        # Above $1000 in-band: raw=small 0.85, proposed>0.85 → loosen,
        # bounded by micro's own 0.90 cap.
        d = tt.decide(1040.0)
        assert d.verdict == "would_loosen"
        assert d.proposed.envelope_pct <= 0.90 + 1e-9

    def test_identical_outside_band(self):
        assert tt.decide(880.0).verdict == "identical"
        assert tt.decide(1120.0).verdict == "identical"


# ── Standard tier out of scope ───────────────────────────────────────────
class TestStandardOutOfScope:
    def test_standard_not_applicable(self):
        d = tt.decide(6000.0)
        assert d.raw_tier == "standard"
        assert d.current is None and d.proposed is None
        assert d.verdict == "not_applicable"
        assert d.taper_applied is False

    def test_standard_payload_serializes(self):
        payload = tt.observe(6000.0)
        assert payload["current"] is None
        assert payload["difference"] == {}
        json.dumps(payload)  # must be JSON-serializable


# ── Prior-state extraction (migration-free hysteresis durability) ────────
class TestExtractPreviousState:
    def test_extracts_valid_state(self):
        result = {"cycle_metadata": {"tier_taper":
                                     {"effective_tier_state": "small"}}}
        assert tt.extract_previous_tier_state(result) == "small"

    @pytest.mark.parametrize("result", [
        None, {}, {"cycle_metadata": {}},
        {"cycle_metadata": {"tier_taper": {}}},
        {"cycle_metadata": {"tier_taper": {"effective_tier_state": "bogus"}}},
        {"cycle_metadata": {"tier_taper": "not_a_dict"}},
        {"cycle_metadata": None},
        "not_a_dict",
    ])
    def test_returns_none_on_malformed(self, result):
        assert tt.extract_previous_tier_state(result) is None


# ── Purity / serialization ───────────────────────────────────────────────
class TestPurity:
    def test_observe_is_json_serializable_across_domain(self):
        for e in (0.0, 850.0, 950.0, 1000.0, 1050.0, 1200.0, 6000.0):
            json.dumps(tt.observe(float(e), "normal"))

    def test_negative_and_zero_equity_do_not_crash(self):
        for e in (-100.0, 0.0):
            d = tt.decide(e)
            assert d.raw_tier == "micro"  # < boundary
            assert not math.isnan(d.taper_fraction)

    def test_decide_does_not_mutate_regime_input(self):
        reg = {"state": "normal"}  # a mutable input object
        before = dict(reg)
        tt.decide(1000.0, reg)
        assert reg == before

    def test_payload_has_owner_required_keys(self):
        p = tt.observe(1020.0, "normal")
        for k in ("current", "proposed", "difference", "verdict",
                  "previous_tier_state", "hysteresis_decision",
                  "engine_version"):
            assert k in p


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
