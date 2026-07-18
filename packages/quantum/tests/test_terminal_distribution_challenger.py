"""Lognormal challenger + common payoff integration tests (queue-⑤).

Pins:
1. Distribution honesty: exact-CDF sanity, partial expectation integrates to
   the forward, deterministic provenance hashing.
2. Challenger produces NONZERO credit-vertical EV where the frozen baseline
   is identically $0 (the E12 point of the whole exercise).
3. Call/put-aware breakeven PoP orientation.
4. Closed-form payoff integration matches brute-force numeric integration.
5. H9 abstention: absent/invalid IV, spot, DTE, known_at -> typed
   Unavailable, never a defaulted distribution (the dormant
   opportunity_scorer kernel's `iv or 0.30` fabrication is explicitly dead).
"""

import math

import pytest

from packages.quantum.analytics.terminal_distribution import (
    DistributionInputs,
    LegSpec,
    LognormalTerminal,
    StrategyEvaluation,
    StructureSpec,
    Unavailable,
    baseline_credit_vertical,
    build_lognormal,
    challenger_lognormal_evaluate,
    integrate_structure,
)

KNOWN_AT = "2026-07-01T15:00:00Z"


def inputs(spot=100.0, dte=30.0, known_at=KNOWN_AT, r=0.0):
    return DistributionInputs(spot=spot, dte_days=dte, known_at=known_at, risk_free_rate=r)


def credit_call_vertical(credit: float, iv_short=0.25, iv_long=0.24) -> StructureSpec:
    return StructureSpec(
        strategy="credit_vertical",
        legs=(
            LegSpec(action="sell", option_type="call", strike=105.0, iv=iv_short, delta=0.30),
            LegSpec(action="buy", option_type="call", strike=110.0, iv=iv_long, delta=0.15),
        ),
        net_premium=credit,
    )


def credit_put_vertical(credit: float = 1.0) -> StructureSpec:
    return StructureSpec(
        strategy="credit_vertical",
        legs=(
            LegSpec(action="sell", option_type="put", strike=95.0, iv=0.25),
            LegSpec(action="buy", option_type="put", strike=90.0, iv=0.26),
        ),
        net_premium=credit,
    )


def debit_put_vertical(debit: float = 2.0) -> StructureSpec:
    return StructureSpec(
        strategy="debit_vertical",
        legs=(
            LegSpec(action="buy", option_type="put", strike=105.0, iv=0.25),
            LegSpec(action="sell", option_type="put", strike=100.0, iv=0.25),
        ),
        net_premium=debit,
    )


def condor(credit: float = 1.2) -> StructureSpec:
    return StructureSpec(
        strategy="iron_condor",
        legs=(
            LegSpec(action="buy", option_type="put", strike=90.0, iv=0.26),
            LegSpec(action="sell", option_type="put", strike=95.0, iv=0.25),
            LegSpec(action="sell", option_type="call", strike=105.0, iv=0.24),
            LegSpec(action="buy", option_type="call", strike=110.0, iv=0.23),
        ),
        net_premium=credit,
    )


class TestLognormalDistribution:
    def test_cdf_is_monotone_and_bounded(self):
        dist = build_lognormal(credit_call_vertical(1.0), inputs())
        assert isinstance(dist, LognormalTerminal)
        ks = [0.0, 50.0, 80.0, 95.0, 100.0, 105.0, 120.0, 200.0, 1e6]
        values = [dist.cdf(k) for k in ks]
        assert values[0] == 0.0
        assert all(0.0 <= v <= 1.0 for v in values)
        assert all(a <= b for a, b in zip(values, values[1:]))
        assert values[-1] == pytest.approx(1.0, abs=1e-9)

    def test_median_at_drift_adjusted_spot(self):
        dist = build_lognormal(credit_call_vertical(1.0), inputs())
        # mu=0: median = spot * exp(-sigma^2 T / 2)
        median = 100.0 * math.exp(-0.5 * dist.sigma ** 2 * dist.t_years)
        assert dist.cdf(median) == pytest.approx(0.5, abs=1e-12)

    def test_partial_expectation_totals_the_forward(self):
        dist = build_lognormal(credit_call_vertical(1.0), inputs(r=0.0))
        assert dist.partial_expectation(None, None) == pytest.approx(100.0, abs=1e-9)
        # Additivity across a split point.
        left = dist.partial_expectation(None, 105.0)
        right = dist.partial_expectation(105.0, None)
        assert left + right == pytest.approx(100.0, abs=1e-9)

    def test_sigma_is_equal_weight_mean_of_leg_ivs(self):
        dist = build_lognormal(credit_call_vertical(1.0, iv_short=0.30, iv_long=0.20), inputs())
        assert dist.sigma == pytest.approx(0.25, abs=1e-12)

    def test_deterministic_provenance(self):
        d1 = build_lognormal(credit_call_vertical(1.0), inputs())
        d2 = build_lognormal(credit_call_vertical(1.0), inputs())
        assert d1.provenance == d2.provenance
        r1 = challenger_lognormal_evaluate(credit_call_vertical(1.0), inputs())
        r2 = challenger_lognormal_evaluate(credit_call_vertical(1.0), inputs())
        assert r1 == r2


class TestChallengerBeatsIdentityZero:
    """Baseline credit EV == 0 identically; the challenger must move."""

    @pytest.mark.parametrize("credit", [0.5, 1.5, 3.0])
    def test_challenger_nonzero_where_baseline_is_zero(self, credit):
        structure = credit_call_vertical(credit)
        baseline = baseline_credit_vertical(structure)
        challenger = challenger_lognormal_evaluate(structure, inputs())
        assert isinstance(baseline, StrategyEvaluation)
        assert isinstance(challenger, StrategyEvaluation)
        assert baseline.expected_value == pytest.approx(0.0, abs=1e-9)
        assert abs(challenger.expected_value) > 1e-3
        assert math.isfinite(challenger.expected_value)
        assert 0.0 < challenger.pop < 1.0
        assert challenger.basis == "raw"
        assert challenger.model == "lognormal_v1"


class TestCallPutAwareness:
    def test_credit_call_pop_is_below_breakeven_mass(self):
        structure = credit_call_vertical(1.0)
        result = challenger_lognormal_evaluate(structure, inputs())
        dist = build_lognormal(structure, inputs())
        assert result.breakevens == (106.0,)
        assert result.pop == pytest.approx(dist.cdf(106.0), abs=1e-12)
        assert result.pop > 0.5  # BE above spot -> profitable side holds the bulk

    def test_credit_put_pop_is_above_breakeven_mass(self):
        structure = credit_put_vertical(1.0)
        result = challenger_lognormal_evaluate(structure, inputs())
        dist = build_lognormal(structure, inputs())
        assert result.breakevens == (94.0,)
        assert result.pop == pytest.approx(1.0 - dist.cdf(94.0), abs=1e-12)
        assert result.pop > 0.5

    def test_debit_put_pop_is_below_breakeven_mass(self):
        structure = debit_put_vertical(2.0)
        result = challenger_lognormal_evaluate(structure, inputs())
        dist = build_lognormal(structure, inputs())
        assert result.breakevens == (103.0,)
        assert result.pop == pytest.approx(dist.cdf(103.0), abs=1e-12)

    def test_condor_pop_is_between_breakevens(self):
        structure = condor(1.2)
        result = challenger_lognormal_evaluate(structure, inputs())
        dist = build_lognormal(structure, inputs())
        be_put, be_call = result.breakevens
        assert be_put == pytest.approx(93.8)
        assert be_call == pytest.approx(106.2)
        assert result.pop == pytest.approx(dist.cdf(be_call) - dist.cdf(be_put), abs=1e-12)

    def test_geometry_mismatch_abstains(self):
        # "Credit" call vertical shorting the HIGHER strike is a mislabeled debit.
        structure = StructureSpec(
            strategy="credit_vertical",
            legs=(
                LegSpec(action="sell", option_type="call", strike=110.0, iv=0.25),
                LegSpec(action="buy", option_type="call", strike=105.0, iv=0.25),
            ),
            net_premium=1.0,
        )
        result = challenger_lognormal_evaluate(structure, inputs())
        assert isinstance(result, Unavailable)
        assert result.reason_code == "strategy_geometry_mismatch"


class TestClosedFormMatchesNumericIntegration:
    def _numeric_ev_share(self, dist, payoff, lo=1.0, hi=500.0, steps=40000):
        total = 0.0
        f_prev = dist.cdf(lo)
        total += payoff(lo / 2.0) * f_prev  # mass below the grid
        step = (hi - lo) / steps
        for i in range(1, steps + 1):
            k = lo + i * step
            f_k = dist.cdf(k)
            total += payoff(k - step / 2.0) * (f_k - f_prev)
            f_prev = f_k
        total += payoff(hi * 2.0) * (1.0 - f_prev)  # mass above the grid
        return total

    def test_condor_ev_exact_vs_numeric(self):
        structure = condor(1.2)
        result = challenger_lognormal_evaluate(structure, inputs())
        dist = build_lognormal(structure, inputs())

        def payoff(s):
            put_intrusion = max(0.0, min(95.0 - s, 5.0))
            call_intrusion = max(0.0, min(s - 105.0, 5.0))
            return 1.2 - put_intrusion - call_intrusion

        numeric = self._numeric_ev_share(dist, payoff) * 100.0
        assert result.expected_value == pytest.approx(numeric, abs=0.5)

    def test_credit_vertical_ev_exact_vs_numeric(self):
        structure = credit_call_vertical(1.5)
        result = challenger_lognormal_evaluate(structure, inputs())
        dist = build_lognormal(structure, inputs())

        def payoff(s):
            return 1.5 - max(0.0, min(s - 105.0, 5.0))

        numeric = self._numeric_ev_share(dist, payoff) * 100.0
        assert result.expected_value == pytest.approx(numeric, abs=0.5)

    def test_integrator_geometry_max_gain_loss(self):
        result = challenger_lognormal_evaluate(credit_call_vertical(1.2), inputs())
        assert result.max_gain == pytest.approx(120.0)
        assert result.max_loss == pytest.approx(380.0)


class TestH9Abstention:
    def test_missing_iv_abstains(self):
        structure = StructureSpec(
            strategy="credit_vertical",
            legs=(
                LegSpec(action="sell", option_type="call", strike=105.0, iv=None),
                LegSpec(action="buy", option_type="call", strike=110.0, iv=0.24),
            ),
            net_premium=1.0,
        )
        result = challenger_lognormal_evaluate(structure, inputs())
        assert isinstance(result, Unavailable)
        assert result.reason_code == "missing_iv"

    def test_percent_scale_iv_refused_not_rescaled(self):
        structure = credit_call_vertical(1.0, iv_short=25.0, iv_long=0.24)
        result = challenger_lognormal_evaluate(structure, inputs())
        assert isinstance(result, Unavailable)
        assert result.reason_code == "invalid_iv"

    def test_nonpositive_iv_abstains(self):
        structure = credit_call_vertical(1.0, iv_short=0.0, iv_long=0.24)
        result = challenger_lognormal_evaluate(structure, inputs())
        assert isinstance(result, Unavailable)
        assert result.reason_code == "invalid_iv"

    def test_missing_spot_abstains(self):
        result = challenger_lognormal_evaluate(credit_call_vertical(1.0), inputs(spot=None))
        assert isinstance(result, Unavailable)
        assert result.reason_code == "missing_spot"

    def test_invalid_dte_abstains(self):
        result = challenger_lognormal_evaluate(credit_call_vertical(1.0), inputs(dte=0.0))
        assert isinstance(result, Unavailable)
        assert result.reason_code == "invalid_dte"

    def test_missing_known_at_abstains(self):
        result = challenger_lognormal_evaluate(credit_call_vertical(1.0), inputs(known_at=""))
        assert isinstance(result, Unavailable)
        assert result.reason_code == "missing_known_at"

    def test_missing_inputs_abstains(self):
        result = challenger_lognormal_evaluate(credit_call_vertical(1.0), None)
        assert isinstance(result, Unavailable)
        assert result.reason_code == "missing_inputs"

    def test_invalid_width_abstains_via_shared_validation(self):
        structure = StructureSpec(
            strategy="credit_vertical",
            legs=(
                LegSpec(action="sell", option_type="call", strike=105.0, iv=0.25),
                LegSpec(action="buy", option_type="call", strike=105.0, iv=0.25),
            ),
            net_premium=1.0,
        )
        # Distribution builds fine; the INTEGRATION abstains on geometry.
        dist = build_lognormal(structure, inputs())
        assert isinstance(dist, LognormalTerminal)
        result = integrate_structure(dist, structure)
        assert isinstance(result, Unavailable)
        assert result.reason_code == "invalid_width"
