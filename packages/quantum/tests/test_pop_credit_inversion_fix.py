"""PR-0 (2026-07-12): credit-spread PoP inversion fix (ev_calculator.py:42).

The credit branch returned max_gain/(max_gain+max_loss) = credit/width = P(LOSS)
— inverted, which drove credit-vertical EV strongly negative → the −999 ranker
gate silently blocked the 2-leg credit cohort. Corrected to
max_loss/(max_gain+max_loss) = 1 − credit/width = P(WIN), with a terminal [0,1]
clamp. ONLY the 5 credit-vertical strategy types hit that branch; iron condors
(raise inside calculate_ev) and debit spreads (delta branch) are UNTOUCHED —
pinned byte-identical below. (This file RUNS; the legacy test_calculate_pop.py
is module-skipped under #775.)
"""
import pytest

from packages.quantum.ev_calculator import calculate_pop, calculate_ev


class TestCreditInversionFixed:
    def test_the_inversion_case(self):
        # credit 1.49, width 5: max_gain=149, max_loss=351, total=500.
        # WAS 149/500 = 0.298 (P(loss)); NOW 351/500 = 0.702 (P(win)).
        pop = calculate_pop("credit_spread", credit=1.49, width=5.0)
        assert abs(pop - 0.702) < 0.001

    def test_far_otm_low_credit_high_pop(self):
        # a far-OTM spread (small credit) must be MORE likely to profit.
        # credit 0.50, width 5: max_loss=450 / 500 = 0.90.
        pop = calculate_pop("credit_spread", credit=0.50, width=5.0)
        assert abs(pop - 0.90) < 0.001

    def test_monotonic_richer_credit_lower_pop(self):
        p_lo = calculate_pop("credit_spread", credit=0.50, width=5.0)   # 0.90
        p_mid = calculate_pop("credit_spread", credit=2.50, width=5.0)  # 0.50
        p_hi = calculate_pop("credit_spread", credit=4.00, width=5.0)   # 0.20
        assert p_lo > p_mid > p_hi
        assert abs(p_mid - 0.50) < 0.001  # you get paid a lot BECAUSE it's a coin-flip

    def test_all_five_credit_types_fixed(self):
        # credit 1.0, width 5 → max_loss 400 / 500 = 0.80, for every credit type.
        for st in ("credit_spread", "credit_put_spread", "credit_call_spread",
                   "short_call_spread", "short_put_spread"):
            assert abs(calculate_pop(st, credit=1.0, width=5.0) - 0.80) < 0.001, st

    def test_bounded_zero_one(self):
        for c in (0.01, 1.0, 2.5, 4.99):
            p = calculate_pop("credit_spread", credit=c, width=5.0)
            assert 0.0 <= p <= 1.0

    def test_credit_fallback_to_delta_unchanged(self):
        # no credit/width → 1 − delta (the fallback branch, untouched).
        assert abs(calculate_pop("credit_spread", delta=0.30) - 0.70) < 0.001


class TestOtherStructuresByteIdentical:
    """The fix touches ONLY the credit branch. These prove ICs/debits/singles
    are unchanged (byte-identical)."""

    def test_debit_spread_midpoint_unchanged(self):
        # current debit behavior (no credit/width): midpoint of long/short delta
        # = (0.60 + 0.30)/2 = 0.45. Pinning the ACTUAL value proves the fix left
        # the debit branch untouched (the legacy 0.60 long-delta test is the
        # stale one #775 skipped).
        legs = [{"action": "buy", "delta": 0.60}, {"action": "sell", "delta": 0.30}]
        assert abs(calculate_pop("debit_spread", legs=legs) - 0.45) < 0.001

    def test_long_call_delta_unchanged(self):
        assert abs(calculate_pop("long_call", delta=0.35) - 0.35) < 0.001

    def test_short_call_one_minus_delta_unchanged(self):
        assert abs(calculate_pop("short_call", delta=0.25) - 0.75) < 0.001

    def test_unknown_neutral_unchanged(self):
        assert calculate_pop("unknown_strategy") == 0.5

    def test_iron_condor_not_routed_through_calculate_ev(self):
        # ICs raise in calculate_ev (use calculate_condor_ev) → never hit :42.
        with pytest.raises(ValueError):
            calculate_ev(premium=1.0, strike=100.0, current_price=100.0,
                         delta=0.2, strategy="iron_condor")


class TestCalculateEvUsesFixedPop:
    def test_credit_spread_ev_win_prob_now_p_win(self):
        ev = calculate_ev(premium=1.50, strike=100.0, current_price=95.0,
                          delta=0.30, strategy="credit_spread", width=5.0)
        # PoP now 1 − 1.50/5.0 = 0.70 (was the inverted 0.30).
        assert abs(ev.win_probability - 0.70) < 0.001
        assert abs(ev.loss_probability - 0.30) < 0.001


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
