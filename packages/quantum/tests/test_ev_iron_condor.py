
import pytest
from packages.quantum.ev_calculator import calculate_condor_ev

def test_calculate_condor_ev():
    """
    Test the disjoint tail EV logic for Iron Condor.
    """
    credit = 1.00
    width_put = 5.00
    width_call = 5.00

    # Deltas imply probabilities of touching/ITM
    delta_short_put = -0.15
    delta_short_call = 0.15

    result = calculate_condor_ev(
        credit=credit,
        width_put=width_put,
        width_call=width_call,
        delta_short_put=delta_short_put,
        delta_short_call=delta_short_call
    )

    # Assertions
    # 1. Probabilities
    assert result.win_probability == pytest.approx(0.70) # 1 - (0.15 + 0.15)
    assert result.loss_probability == pytest.approx(0.30)

    # 2. Financials
    assert result.max_gain == 100.0 # credit * 100
    assert result.max_loss == 400.0 # (5 - 1) * 100

    # 3. EV
    # Profit component: 0.70 * 100 = 70.0
    # Loss component Put: 0.15 * 400 = 60.0
    # Loss component Call: 0.15 * 400 = 60.0
    # EV = 70 - 60 - 60 = -50.0

    expected_ev = (0.70 * 100.0) - (0.15 * 400.0) - (0.15 * 400.0)
    assert result.expected_value == pytest.approx(expected_ev)
    assert result.expected_value == pytest.approx(-50.0)

    # Test positive EV case
    # Increase credit to break even point roughly
    # To get EV > 0: 0.7*C - 0.3*(5-C)*100 > 0
    # 0.7C - 150 + 0.3C > 0 => C > 150/100 = 1.50 per contract ($1.50)
    # Actually per share: 0.7*100*c - 0.3*100*(5-c) > 0
    # 70c - 30(5-c) > 0 => 70c - 150 + 30c > 0 => 100c > 150 => c > 1.50

    result_positive = calculate_condor_ev(
        credit=2.00,
        width_put=5.00,
        width_call=5.00,
        delta_short_put=-0.15,
        delta_short_call=0.15
    )

    # Max Loss = (5 - 2) * 100 = 300
    # Max Gain = 200
    # EV = (0.7 * 200) - (0.15 * 300) - (0.15 * 300)
    #    = 140 - 45 - 45 = 50.0
    assert result_positive.expected_value == pytest.approx(50.0)
