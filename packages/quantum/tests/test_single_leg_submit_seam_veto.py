"""Single-leg experiment HARD VETO at the REAL submit seam (R1 follow-up to #1287).

#1287 shipped the veto only in ExecutionRouter.execute_order — a path with ZERO
production callers. The REAL submit seam is ``should_submit_to_broker`` (the
function paper_endpoints entry, paper_exit_evaluator close, and safety_checks
approval ALL call). This suite drives that production decision function directly
(§9: execute the route, inject the attack at the deepest input, assert the
top-level outcome) with the exact ROW SHAPES those routes hand it:

  * entry route  -> a paper_orders row (experiment marker inside ``order_json``)
  * close route  -> a paper_positions row (``strategy`` / ``strategy_key`` =
                    long_call/long_put — the position shape carries no
                    experiment column)

The malicious-live-routing attempt = a single-leg experiment order/position on a
``live_eligible`` portfolio. The seam MUST return False (broker blocked)
regardless of routing_mode. Every non-experiment order is byte-identical.
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from packages.quantum.brokers.execution_router import (
    is_single_leg_experiment_row,
    should_submit_to_broker,
)

# alert() / _get_admin_supabase() are imported LAZILY inside the veto's alert
# helper, so they resolve from — and must be patched at — the source module.
_ALERTS = "packages.quantum.observability.alerts"


@contextmanager
def _silence_alerts():
    with patch(f"{_ALERTS}.alert") as m_alert, \
         patch(f"{_ALERTS}._get_admin_supabase", return_value=MagicMock()):
        yield m_alert


def _client(routing_mode):
    """Fake supabase: paper_portfolios.select(routing_mode).eq(id).limit(1).execute()
    -> [{'routing_mode': routing_mode}] (or [] when routing_mode is None)."""
    c = MagicMock()
    data = [] if routing_mode is None else [{"routing_mode": routing_mode}]
    (c.table.return_value.select.return_value.eq.return_value
     .limit.return_value.execute.return_value) = MagicMock(data=data)
    return c


# Row shapes exactly as the two real routes hand them to the seam.
def _entry_order_row(experiment=True, strategy="long_call"):
    """paper_orders row: the order request lives under order_json (jsonb)."""
    oj = {
        "symbol": "SPY", "strategy_type": strategy, "routing": "shadow_only",
        "lifecycle_state": "experimental", "contracts": 1,
        "legs": [{"action": "buy", "quantity": 1, "type": "call", "strike": 500.0}],
    }
    if experiment:
        oj["experiment"] = "single_leg"
    return {"id": "ord-1", "portfolio_id": "pf-1", "order_json": oj}


def _close_position_row(strategy_key="long_call"):
    """paper_positions row: no experiment column — only strategy/strategy_key."""
    return {
        "id": "pos-1", "portfolio_id": "pf-1", "symbol": "SPY",
        "strategy": strategy_key, "strategy_key": strategy_key, "quantity": 1,
        "legs": [{"action": "buy", "type": "call", "strike": 500.0}],
    }


# ── The MALICIOUS-LIVE-ROUTING attempt: live_eligible + experiment -> blocked ──

def test_entry_experiment_on_live_eligible_portfolio_is_blocked():
    # Even on a live_eligible portfolio, the entry-route experiment order is
    # refused broker submission (returns False). WITHOUT the veto this would
    # return True and reach the broker.
    with _silence_alerts():
        assert should_submit_to_broker("pf-1", _client("live_eligible"),
                                        order=_entry_order_row()) is False


def test_close_experiment_position_on_live_eligible_portfolio_is_blocked():
    with _silence_alerts():
        assert should_submit_to_broker("pf-1", _client("live_eligible"),
                                        order=_close_position_row("long_put")) is False


def test_experiment_on_shadow_only_still_blocked_normal_path():
    # shadow_only would block anyway; the veto returns False without the loud alert.
    assert should_submit_to_broker("pf-1", _client("shadow_only"),
                                   order=_entry_order_row()) is False


def test_experiment_on_missing_portfolio_blocked():
    assert should_submit_to_broker("pf-1", _client(None),
                                   order=_close_position_row()) is False


# ── Byte-identity: non-experiment orders reach the real decision unchanged ─────

def test_non_experiment_entry_on_live_eligible_submits_true():
    # A normal (iron_condor) order on a live_eligible portfolio still returns
    # True — the veto is a precise no-op for everything that is not the experiment.
    row = {"id": "ord-2", "portfolio_id": "pf-1",
           "order_json": {"symbol": "QQQ", "strategy_type": "iron_condor"}}
    assert should_submit_to_broker("pf-1", _client("live_eligible"), order=row) is True


def test_non_experiment_shadow_only_returns_false_like_legacy():
    row = {"id": "ord-3", "portfolio_id": "pf-1",
           "order_json": {"symbol": "QQQ", "strategy_type": "debit_vertical"}}
    assert should_submit_to_broker("pf-1", _client("shadow_only"), order=row) is False


def test_order_omitted_is_byte_identical_to_legacy():
    # The 2-arg call (no order=) is unchanged: routing_mode decides alone.
    assert should_submit_to_broker("pf-1", _client("live_eligible")) is True
    assert should_submit_to_broker("pf-1", _client("shadow_only")) is False
    assert should_submit_to_broker("pf-1", _client(None)) is False


# ── The critical alert fires ONLY when the veto overrode a live_eligible route ─

def test_live_eligible_override_fires_critical_alert():
    with _silence_alerts() as real_alert:
        should_submit_to_broker("pf-1", _client("live_eligible"), order=_entry_order_row())
        assert real_alert.called
        assert real_alert.call_args.kwargs.get("alert_type") == "single_leg_experiment_live_submit_blocked"
        assert real_alert.call_args.kwargs.get("severity") == "critical"


def test_shadow_only_block_does_not_fire_critical_alert():
    with _silence_alerts() as real_alert:
        should_submit_to_broker("pf-1", _client("shadow_only"), order=_entry_order_row())
        assert not real_alert.called


def test_alert_failure_never_breaks_the_block():
    # The block must return False even if the alert path raises.
    with patch(f"{_ALERTS}.alert", side_effect=RuntimeError("alerts down")), \
         patch(f"{_ALERTS}._get_admin_supabase", return_value=MagicMock()):
        assert should_submit_to_broker("pf-1", _client("live_eligible"),
                                       order=_entry_order_row()) is False


# ── Detection recognizer matrix (both real shapes) ────────────────────────────

def test_recognizer_top_level_marker():
    assert is_single_leg_experiment_row({"experiment": "single_leg"}) is True
    assert is_single_leg_experiment_row({"strategy_experiment": "single_leg"}) is True


def test_recognizer_order_json_nested_marker():
    assert is_single_leg_experiment_row(_entry_order_row()) is True


def test_recognizer_position_strategy_names():
    assert is_single_leg_experiment_row(_close_position_row("long_call")) is True
    assert is_single_leg_experiment_row(_close_position_row("long_put")) is True
    assert is_single_leg_experiment_row({"strategy": "LONG_CALL"}) is True  # case-insensitive


def test_recognizer_order_json_strategy_name():
    assert is_single_leg_experiment_row(
        {"order_json": {"strategy_type": "long_put"}}) is True


def test_recognizer_negatives():
    assert is_single_leg_experiment_row({"experiment": "iron_condor"}) is False
    assert is_single_leg_experiment_row({"strategy": "debit_vertical"}) is False
    assert is_single_leg_experiment_row({"order_json": {"strategy_type": "credit_vertical"}}) is False
    assert is_single_leg_experiment_row({"symbol": "SPY"}) is False
    assert is_single_leg_experiment_row(None) is False
    assert is_single_leg_experiment_row("not a mapping") is False


def test_recognizer_object_with_dict():
    class _Row:
        def __init__(self):
            self.strategy_key = "long_call"
    assert is_single_leg_experiment_row(_Row()) is True
