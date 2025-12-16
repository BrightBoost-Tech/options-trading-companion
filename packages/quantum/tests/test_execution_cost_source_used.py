import pytest
from packages.quantum.options_scanner import _determine_execution_cost

def test_execution_cost_source_used_proxy_wins():
    # Case A) history_cost=2.0, proxy_cost=6.0 => expected=6.0, source_used="proxy"
    # proxy_cost = (combo_width_share * 0.5 + num_legs * 0.0065) * 100

    # Let's align inputs to get proxy_cost = 6.0
    # 6.0 = (combo_width_share * 0.5 + 1 * 0.0065) * 100
    # 0.06 = combo_width_share * 0.5 + 0.0065
    # 0.0535 = combo_width_share * 0.5
    # combo_width_share = 0.107

    symbol = "TEST"
    drag_map = {
        "TEST": {"avg_drag": 2.0, "n": 10} # History cost 2.0
    }

    result = _determine_execution_cost(
        drag_map=drag_map,
        symbol=symbol,
        combo_width_share=0.107,
        num_legs=1
    )

    expected_proxy = (0.107 * 0.5 + 0.0065) * 100 # 6.0

    assert result["expected_execution_cost"] == pytest.approx(expected_proxy, 0.0001)
    assert result["execution_cost_source_used"] == "proxy"
    assert result["execution_cost_samples_used"] == 0
    assert result["execution_drag_source"] == "history" # Because stats exist

def test_execution_cost_source_used_history_wins():
    # Case B) history_cost=10.0, proxy_cost=6.0 => expected=10.0, source_used="history"

    symbol = "TEST"
    drag_map = {
        "TEST": {"avg_drag": 10.0, "n": 10}
    }

    result = _determine_execution_cost(
        drag_map=drag_map,
        symbol=symbol,
        combo_width_share=0.107, # Same width, proxy is 6.0
        num_legs=1
    )

    assert result["expected_execution_cost"] == 10.0
    assert result["execution_cost_source_used"] == "history"
    assert result["execution_cost_samples_used"] == 10
    assert result["execution_drag_source"] == "history"

def test_execution_cost_no_history():
    symbol = "TEST"
    drag_map = {}

    result = _determine_execution_cost(
        drag_map=drag_map,
        symbol=symbol,
        combo_width_share=0.107,
        num_legs=1
    )

    expected_proxy = (0.107 * 0.5 + 0.0065) * 100 # 6.0

    assert result["expected_execution_cost"] == pytest.approx(expected_proxy, 0.0001)
    assert result["execution_cost_source_used"] == "proxy"
    assert result["execution_cost_samples_used"] == 0
    assert result["execution_drag_source"] == "proxy" # No stats exist
