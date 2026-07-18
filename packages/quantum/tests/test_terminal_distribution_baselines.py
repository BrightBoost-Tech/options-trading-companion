"""Frozen-baseline adapter tests (queue-⑤ terminal-distribution foundation).

Pins:
1. Credit identity EV == $0 EXACTLY on the baseline (low AND high credit
   fraction) with the defect stamped visible — the KNOWN baseline defect is
   reproduced, never silently fixed.
2. Byte-parity with the production functions the adapters wrap (credit,
   debit interpolation, condor strict AND tail).
3. Explicit condor model selection (strict vs tail divergence on the same
   structure).
4. Malformed/missing inputs -> typed Unavailable abstention (H9), never a
   fabricated evaluation and never an exception.
"""

import pytest

from packages.quantum.ev_calculator import (
    calculate_condor_ev,
    calculate_condor_ev_tail,
    calculate_ev,
    calculate_pop,
)
from packages.quantum.analytics.terminal_distribution import (
    CREDIT_IDENTITY_DEFECT,
    LegSpec,
    StrategyEvaluation,
    StructureSpec,
    Unavailable,
    baseline_condor,
    baseline_credit_vertical,
    baseline_debit_vertical,
)


def credit_call_vertical(credit: float, contracts: int = 1) -> StructureSpec:
    return StructureSpec(
        strategy="credit_vertical",
        legs=(
            LegSpec(action="sell", option_type="call", strike=105.0, iv=0.25, delta=0.30),
            LegSpec(action="buy", option_type="call", strike=110.0, iv=0.24, delta=0.15),
        ),
        net_premium=credit,
        contracts=contracts,
    )


def debit_call_vertical(debit: float = 2.0) -> StructureSpec:
    return StructureSpec(
        strategy="debit_vertical",
        legs=(
            LegSpec(action="buy", option_type="call", strike=100.0, iv=0.25, delta=0.60),
            LegSpec(action="sell", option_type="call", strike=105.0, iv=0.24, delta=0.30),
        ),
        net_premium=debit,
    )


def condor(credit: float = 1.2, contracts: int = 1) -> StructureSpec:
    return StructureSpec(
        strategy="iron_condor",
        legs=(
            LegSpec(action="buy", option_type="put", strike=90.0, iv=0.26, delta=-0.03),
            LegSpec(action="sell", option_type="put", strike=95.0, iv=0.25, delta=-0.10),
            LegSpec(action="sell", option_type="call", strike=105.0, iv=0.24, delta=0.10),
            LegSpec(action="buy", option_type="call", strike=110.0, iv=0.23, delta=0.03),
        ),
        net_premium=credit,
        contracts=contracts,
    )


class TestCreditIdentityDefectVisibility:
    """The KNOWN defect: raw credit-vertical EV == 0 by fair-odds identity."""

    def test_low_credit_fraction_ev_is_exactly_zero(self):
        result = baseline_credit_vertical(credit_call_vertical(0.50))
        assert isinstance(result, StrategyEvaluation)
        assert result.expected_value == pytest.approx(0.0, abs=1e-9)
        assert result.pop == pytest.approx(1.0 - 0.50 / 5.0, abs=1e-12)  # 0.90

    def test_high_credit_fraction_ev_is_exactly_zero(self):
        result = baseline_credit_vertical(credit_call_vertical(3.0))
        assert isinstance(result, StrategyEvaluation)
        assert result.expected_value == pytest.approx(0.0, abs=1e-9)
        assert result.pop == pytest.approx(1.0 - 3.0 / 5.0, abs=1e-12)  # 0.40

    def test_defect_is_stamped_on_the_result(self):
        result = baseline_credit_vertical(credit_call_vertical(1.5))
        assert isinstance(result, StrategyEvaluation)
        assert CREDIT_IDENTITY_DEFECT in result.known_defects
        assert "credit_identity_ev_zero" in result.known_defects[0]
        assert "never silently fixed" in result.known_defects[0]

    def test_basis_is_raw_and_model_labeled(self):
        result = baseline_credit_vertical(credit_call_vertical(1.5))
        assert result.basis == "raw"
        assert result.model == "baseline_credit_identity"
        assert result.provenance.source == "ev_calculator"


class TestProductionParity:
    """Adapters wrap production verbatim — outputs must match exactly."""

    def test_credit_vertical_parity_with_calculate_ev(self):
        structure = credit_call_vertical(1.5)
        result = baseline_credit_vertical(structure)
        prod = calculate_ev(
            premium=1.5, strike=105.0, current_price=0.0, delta=0.30,
            strategy="credit_spread", width=5.0, contracts=1,
            legs=[{"action": "sell", "delta": 0.30}, {"action": "buy", "delta": 0.15}],
        )
        assert result.pop == prod.win_probability
        assert result.expected_value == prod.expected_value
        assert result.max_gain == prod.max_gain
        assert result.max_loss == prod.max_loss

    def test_debit_interpolation_parity_with_production_numbers(self):
        structure = debit_call_vertical(2.0)
        result = baseline_debit_vertical(structure)
        assert isinstance(result, StrategyEvaluation)
        # Production breakeven interpolation: 0.60 - (0.60-0.30) * (2/5) = 0.48
        expected_pop = calculate_pop(
            "debit_spread",
            legs=[{"action": "buy", "delta": 0.60}, {"action": "sell", "delta": 0.30}],
            credit=2.0,
            width=5.0,
        )
        assert result.pop == expected_pop
        assert result.pop == pytest.approx(0.48, abs=1e-12)
        # EV = 0.48*300 - 0.52*200 = 40
        assert result.expected_value == pytest.approx(40.0, abs=1e-9)
        assert result.max_gain == pytest.approx(300.0)
        assert result.max_loss == pytest.approx(200.0)
        assert result.model == "baseline_debit_interp"

    def test_condor_strict_parity(self):
        result = baseline_condor(condor(1.2), model="strict")
        prod = calculate_condor_ev(
            credit=1.2, width_put=5.0, width_call=5.0,
            delta_short_put=0.10, delta_short_call=0.10,
        )
        assert isinstance(result, StrategyEvaluation)
        assert result.pop == prod.win_probability
        assert result.expected_value == prod.expected_value
        # Hand check: 0.8*120 - 0.1*380 - 0.1*380 = 20
        assert result.expected_value == pytest.approx(20.0, abs=1e-9)
        assert result.model == "baseline_condor_strict"

    def test_condor_tail_parity(self):
        result = baseline_condor(condor(1.2), model="tail")
        prod = calculate_condor_ev_tail(
            credit=1.2, width_put=5.0, width_call=5.0,
            delta_short_put=0.10, delta_short_call=0.10,
            delta_long_put=0.03, delta_long_call=0.03,
            tail_loss_severity=0.50, tail_prob_mult=1.00,
        )
        assert isinstance(result, StrategyEvaluation)
        assert result.pop == prod.win_probability
        assert result.expected_value == prod.expected_value
        # Hand check: per side E_loss = 0.03*3.8 + 0.07*0.5*3.8 = 0.247
        # EV = (0.8*1.2 - 2*0.247) * 100 = 46.6
        assert result.expected_value == pytest.approx(46.6, abs=1e-9)
        assert result.model == "baseline_condor_tail"


class TestCondorModelSelection:
    def test_strict_vs_tail_diverge_on_same_structure(self):
        strict = baseline_condor(condor(1.2), model="strict")
        tail = baseline_condor(condor(1.2), model="tail")
        assert isinstance(strict, StrategyEvaluation)
        assert isinstance(tail, StrategyEvaluation)
        assert abs(strict.expected_value - tail.expected_value) > 1.0
        assert strict.model != tail.model

    def test_model_is_explicit_keyword_only(self):
        with pytest.raises(TypeError):
            baseline_condor(condor(1.2))  # no model -> refuse, never default

    def test_invalid_model_abstains(self):
        result = baseline_condor(condor(1.2), model="ensemble")
        assert isinstance(result, Unavailable)
        assert result.reason_code == "invalid_model"

    def test_contracts_scale_condor_units(self):
        one = baseline_condor(condor(1.2, contracts=1), model="strict")
        two = baseline_condor(condor(1.2, contracts=2), model="strict")
        assert two.expected_value == pytest.approx(2 * one.expected_value)
        assert two.max_loss == pytest.approx(2 * one.max_loss)


class TestTypedAbstention:
    """H9: malformed inputs -> typed Unavailable, never fabrication/exception."""

    def test_missing_legs(self):
        s = StructureSpec(strategy="credit_vertical", legs=(), net_premium=1.0)
        result = baseline_credit_vertical(s)
        assert isinstance(result, Unavailable)
        assert result.reason_code == "wrong_leg_count"

    def test_one_sided_vertical(self):
        s = StructureSpec(
            strategy="credit_vertical",
            legs=(
                LegSpec(action="sell", option_type="call", strike=105.0),
                LegSpec(action="sell", option_type="call", strike=110.0),
            ),
            net_premium=1.0,
        )
        result = baseline_credit_vertical(s)
        assert isinstance(result, Unavailable)
        assert result.reason_code == "missing_legs"

    def test_invalid_width_same_strikes(self):
        s = StructureSpec(
            strategy="credit_vertical",
            legs=(
                LegSpec(action="sell", option_type="call", strike=105.0),
                LegSpec(action="buy", option_type="call", strike=105.0),
            ),
            net_premium=1.0,
        )
        result = baseline_credit_vertical(s)
        assert isinstance(result, Unavailable)
        assert result.reason_code == "invalid_width"

    def test_credit_exceeding_width_abstains(self):
        result = baseline_credit_vertical(credit_call_vertical(5.0))
        assert isinstance(result, Unavailable)
        assert result.reason_code == "premium_exceeds_width"

    def test_negative_premium_abstains(self):
        result = baseline_credit_vertical(credit_call_vertical(-1.0))
        assert isinstance(result, Unavailable)
        assert result.reason_code == "invalid_premium"

    def test_debit_without_deltas_abstains_not_fallback(self):
        s = StructureSpec(
            strategy="debit_vertical",
            legs=(
                LegSpec(action="buy", option_type="call", strike=100.0),
                LegSpec(action="sell", option_type="call", strike=105.0),
            ),
            net_premium=2.0,
        )
        result = baseline_debit_vertical(s)
        assert isinstance(result, Unavailable)
        assert result.reason_code == "missing_delta"

    def test_condor_tail_without_long_deltas_abstains(self):
        legs = (
            LegSpec(action="buy", option_type="put", strike=90.0),
            LegSpec(action="sell", option_type="put", strike=95.0, delta=-0.10),
            LegSpec(action="sell", option_type="call", strike=105.0, delta=0.10),
            LegSpec(action="buy", option_type="call", strike=110.0),
        )
        s = StructureSpec(strategy="iron_condor", legs=legs, net_premium=1.2)
        result = baseline_condor(s, model="tail")
        assert isinstance(result, Unavailable)
        assert result.reason_code == "missing_delta"

    def test_condor_strike_disorder_abstains(self):
        legs = (
            LegSpec(action="buy", option_type="put", strike=96.0, delta=-0.03),
            LegSpec(action="sell", option_type="put", strike=95.0, delta=-0.10),
            LegSpec(action="sell", option_type="call", strike=105.0, delta=0.10),
            LegSpec(action="buy", option_type="call", strike=110.0, delta=0.03),
        )
        s = StructureSpec(strategy="iron_condor", legs=legs, net_premium=1.2)
        result = baseline_condor(s, model="strict")
        assert isinstance(result, Unavailable)
        assert result.reason_code == "invalid_width"

    def test_wrong_strategy_label_abstains(self):
        s = debit_call_vertical(2.0)
        result = baseline_credit_vertical(
            StructureSpec(strategy="debit_vertical", legs=s.legs, net_premium=2.0)
        )
        assert isinstance(result, Unavailable)
        assert result.reason_code == "wrong_strategy"
