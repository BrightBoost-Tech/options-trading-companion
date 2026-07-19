"""Close / expiry adjudication for the ONE-LEG shape.

The exit evaluator + expiry path were built for multi-leg structures. These
pins prove the single long call / long put (1-leg) shape flows through the same
decision helpers coherently: DTE, debit-awareness, target-profit, the
single-leg close-limit/direction convention, and the single-leg OCC resolution
the close-ticket builder uses for a <2-leg position.
"""

from datetime import date, timedelta

from packages.quantum.services.paper_exit_evaluator import (
    _check_target_profit,
    _close_limit_and_direction,
    _is_debit_spread,
    days_to_expiry,
)
from packages.quantum.services.paper_autopilot_service import PaperAutopilotService


def _long_call_position(**over):
    pos = {
        "id": "pos-1",
        "symbol": "SPY",
        "strategy_key": "long_call",
        "quantity": 1,
        "max_credit": 1.40,          # debit paid per share ($140 for 1 contract)
        "unrealized_pl": 0.0,
        "nearest_expiry": None,
        "legs": [
            {"symbol": "O:SPY260821C00113000", "action": "buy", "type": "call",
             "strike": 113.0, "expiry": "2026-08-21"}
        ],
    }
    pos.update(over)
    return pos


# ── DTE (leg-scan + nearest_expiry) for a 1-leg position ────────────────────

def test_days_to_expiry_from_single_leg():
    exp = date(2026, 8, 21)
    pos = _long_call_position()
    assert days_to_expiry(pos) == (exp - date.today()).days


def test_days_to_expiry_prefers_nearest_expiry_column():
    future = date.today() + timedelta(days=10)
    pos = _long_call_position(nearest_expiry=future.isoformat())
    assert days_to_expiry(pos) == 10


def test_days_to_expiry_at_or_past_expiry_nonpositive():
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    pos = _long_call_position(legs=[{"symbol": "O:SPY...C", "expiry": yesterday}], nearest_expiry=None)
    assert days_to_expiry(pos) <= 0


def test_days_to_expiry_no_info_is_safe_large():
    pos = _long_call_position(legs=[{"symbol": "O:SPY...C"}], nearest_expiry=None)
    assert days_to_expiry(pos) == 999  # never falsely trigger DTE conditions


# ── Debit-awareness of a long single leg ────────────────────────────────────

def test_long_call_is_debit_by_strategy_name():
    assert _is_debit_spread(_long_call_position()) is True


def test_long_put_is_debit_by_strategy_name():
    pos = _long_call_position(strategy_key="long_put")
    assert _is_debit_spread(pos) is True


def test_long_leg_is_debit_by_positive_quantity_even_without_name():
    pos = _long_call_position(strategy_key="", strategy="", quantity=1)
    assert _is_debit_spread(pos) is True


# ── Target profit (debit branch) on the 1-leg shape ─────────────────────────

def test_target_profit_hit_uses_debit_branch():
    # entry_cost = 1.40 * 100 * 1 = $140; 50% target = $70.
    hit = _long_call_position(unrealized_pl=80.0)
    assert _check_target_profit(hit, tp_pct=0.50) is True
    miss = _long_call_position(unrealized_pl=50.0)
    assert _check_target_profit(miss, tp_pct=0.50) is False


# ── Single-leg close limit + direction convention ───────────────────────────

def test_single_leg_close_uses_unsigned_limit_no_credit_flag():
    # n_legs=1 -> is_credit_close is False (only multi-leg carries direction);
    # limit is the magnitude (Alpaca infers side from the sell-to-close leg).
    limit, is_credit = _close_limit_and_direction(1.55, qty=1, n_legs=1)
    assert limit == 1.55 and is_credit is False
    # Negative mark magnitude is still unsigned.
    limit2, is_credit2 = _close_limit_and_direction(-1.55, qty=1, n_legs=1)
    assert limit2 == 1.55 and is_credit2 is False


# ── The close-ticket builder's single-leg (<2 legs) branch resolves OCC ──────

def test_single_leg_occ_resolution_without_db():
    # _close_position's else-branch (len(orig_legs) < 2) resolves the OCC symbol
    # via this helper; a 1-leg position resolves from its own leg (no DB call).
    pos = _long_call_position()
    occ = PaperAutopilotService._resolve_occ_symbol(pos, None)
    assert occ == "O:SPY260821C00113000"
