"""
Tests for CLOSE_QUOTE_VALIDATION (Phase 2) — stage-time executable-quote
validation on the LIVE close limit.

Gap (diagnosed): the live close staged at the decision MID/mark with no
stage-time executable check (entry #1038 is close-exempt by design), so a
degenerate-but-within-bounds mark could stage a non-executable limit the broker
rejects/rests (the 06-15 class). The shadow/internal path already prices
executable at fill (#1017).

Fix: at the close-staging seam in `_close_position`, for the LIVE path only,
reuse `executable_close_estimate` (#1034) — corroborated → stage at
achievable_close; dark leg → DEFER (hold + flag + re-eval; escalate if stuck,
stops faster than TPs); transient error → mark-limit fallback. Default-ON,
flag-gated (CLOSE_QUOTE_VALIDATION_ENABLED). The DEFER returns BEFORE staging,
so it never reaches submit_and_track's resting-order pre-cancel → never strands
a naked position.
"""
import inspect
import os
from unittest.mock import patch, MagicMock

from packages.quantum.services import paper_exit_evaluator as pxe

_EST = "packages.quantum.analytics.exit_mark_corroboration.executable_close_estimate"
_ALERT = "packages.quantum.observability.alerts.alert"


def _est(achievable, complete=True):
    return {"achievable_close": achievable, "achievable_implied_pl": None,
            "quote_complete": complete, "legs_quotes": {}}


_POS = {"id": "pos-1", "symbol": "MARA", "legs": [{"x": 1}],
        "quantity": 5, "avg_entry_price": 1.21}


# ── flag (CLOSE_QUOTE_VALIDATION_ENABLED) ───────────────────────────

class TestFlag:
    def test_default_on(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLOSE_QUOTE_VALIDATION_ENABLED", None)
            assert pxe._close_quote_validation_enabled() is True

    def test_empty_is_on(self):
        with patch.dict(os.environ, {"CLOSE_QUOTE_VALIDATION_ENABLED": "  "}):
            assert pxe._close_quote_validation_enabled() is True

    def test_explicit_off_variants(self):
        for v in ("0", "false", "no", "off", "OFF", "False"):
            with patch.dict(os.environ, {"CLOSE_QUOTE_VALIDATION_ENABLED": v}):
                assert pxe._close_quote_validation_enabled() is False

    def test_explicit_on(self):
        with patch.dict(os.environ, {"CLOSE_QUOTE_VALIDATION_ENABLED": "1"}):
            assert pxe._close_quote_validation_enabled() is True


# ── escalation thresholds (stops faster than TPs) ───────────────────

class TestEscalateThresholds:
    def test_stop_faster_than_tp_defaults(self):
        with patch.dict(os.environ, {}, clear=False):
            for k in ("CLOSE_STUCK_ESCALATE_STOP_CYCLES", "CLOSE_STUCK_ESCALATE_TP_CYCLES"):
                os.environ.pop(k, None)
            stop = pxe._close_stuck_escalate_cycles(is_stop=True)
            tp = pxe._close_stuck_escalate_cycles(is_stop=False)
        assert stop == 2 and tp == 4 and stop < tp

    def test_env_override(self):
        with patch.dict(os.environ, {"CLOSE_STUCK_ESCALATE_STOP_CYCLES": "1",
                                     "CLOSE_STUCK_ESCALATE_TP_CYCLES": "6"}):
            assert pxe._close_stuck_escalate_cycles(True) == 1
            assert pxe._close_stuck_escalate_cycles(False) == 6


# ── _corroborate_close_stage decisions ──────────────────────────────

class TestCorroborateCloseStage:
    def test_corroborated_complete_stages_executable(self):
        with patch(_EST, return_value=_est(1.06, complete=True)):
            decision, val, *q = pxe._corroborate_close_stage(_POS, 1.86)
        assert decision == "stage_executable"
        assert val == 1.06 and q[0] == "executable"

    def test_corroborated_partial_quote(self):
        with patch(_EST, return_value=_est(1.06, complete=False)):
            decision, val, *q = pxe._corroborate_close_stage(_POS, 1.86)
        assert decision == "stage_executable" and q[0] == "executable_partial_quote"

    def test_dark_leg_defers(self):
        # The 06-15 class: achievable_close None (a leg's executable side missing).
        with patch(_EST, return_value=_est(None, complete=False)):
            decision, reason = pxe._corroborate_close_stage(_POS, 1.86)
        assert decision == "defer" and reason == "executable_side_missing"

    def test_estimate_error_falls_back_to_mark(self):
        with patch(_EST, side_effect=RuntimeError("quote fetch blew up")):
            decision, reason = pxe._corroborate_close_stage(_POS, 1.86)
        assert decision == "stage_mark" and reason.startswith("estimate_error")

    def test_defer_then_corroborates_next_cycle_then_stages(self):
        # cycle 1: dark → defer; cycle 2: quote returns → stage at executable.
        with patch(_EST, side_effect=[_est(None, complete=False), _est(1.10, complete=True)]):
            d1 = pxe._corroborate_close_stage(_POS, 1.86)
            d2 = pxe._corroborate_close_stage(_POS, 1.86)
        assert d1[0] == "defer"
        assert d2[0] == "stage_executable" and d2[1] == 1.10


# ── _handle_close_stage_defer: flag + escalation ────────────────────

def _mock_supabase_with_prior(count):
    sb = MagicMock()
    (sb.table.return_value.select.return_value.eq.return_value.eq.return_value
     .gte.return_value.execute.return_value) = MagicMock(count=count, data=[])
    return sb


def _alert_types(mock_alert):
    return [c.kwargs.get("alert_type") for c in mock_alert.call_args_list]


class TestHandleCloseStageDefer:
    def setup_method(self):
        pxe._REARM_ALERT_LAST.clear()  # clear the 1/h critical throttle between tests

    def test_returns_defer_result_and_flags(self):
        sb = _mock_supabase_with_prior(0)
        with patch(_ALERT) as m:
            out = pxe._handle_close_stage_defer(sb, "pos-1", "MARA", "intraday_stop_loss", "u")
        assert out["routed_to"] == "deferred_uncorroborated"
        assert out["order_id"] is None and out["processed"] == 0
        assert "close_stage_uncorroborated" in _alert_types(m)

    def test_stop_escalates_at_second_defer(self):
        # stop threshold = 2: prior=0 → no critical; prior=1 → critical.
        sb0 = _mock_supabase_with_prior(0)
        with patch(_ALERT) as m0:
            pxe._handle_close_stage_defer(sb0, "pos-A", "MARA", "intraday_stop_loss", "u")
        assert "close_stuck_uncorroborated" not in _alert_types(m0)

        sb1 = _mock_supabase_with_prior(1)
        with patch(_ALERT) as m1:
            pxe._handle_close_stage_defer(sb1, "pos-B", "MARA", "intraday_stop_loss", "u")
        assert "close_stuck_uncorroborated" in _alert_types(m1)

    def test_tp_escalates_slower_than_stop(self):
        # tp threshold = 4: prior=1 → no critical (stop would have escalated).
        sb = _mock_supabase_with_prior(1)
        with patch(_ALERT) as m:
            pxe._handle_close_stage_defer(sb, "pos-C", "QQQ", "intraday_target_profit", "u")
        assert "close_stuck_uncorroborated" not in _alert_types(m)

        sb3 = _mock_supabase_with_prior(3)
        with patch(_ALERT) as m3:
            pxe._handle_close_stage_defer(sb3, "pos-D", "QQQ", "intraday_target_profit", "u")
        assert "close_stuck_uncorroborated" in _alert_types(m3)

    def test_never_raises_on_alert_failure(self):
        sb = _mock_supabase_with_prior(0)
        with patch(_ALERT, side_effect=RuntimeError("alerts down")):
            out = pxe._handle_close_stage_defer(sb, "pos-1", "MARA", "intraday_stop_loss", "u")
        assert out["routed_to"] == "deferred_uncorroborated"  # still returns the defer


# ── structural guarantees (live-only; defer before staging/pre-cancel;
#    shadow path untouched; entry exemption preserved) ────────────────

class TestStructuralInvariants:
    def test_gate_is_live_only_and_flag_gated(self):
        src = inspect.getsource(pxe)
        assert "position_is_alpaca and _close_quote_validation_enabled()" in src

    def test_defer_returns_before_staging_and_before_live_submit(self):
        src = inspect.getsource(pxe)
        defer_at = src.index("return _handle_close_stage_defer(")
        stage_at = src.index("_stage_order_internal(")
        submit_at = src.index("submit_and_track(")
        # DEFER returns BEFORE the order is staged AND before the live submit's
        # resting-order pre-cancel → an uncorroborated defer can never strand a
        # naked position.
        assert defer_at < stage_at < submit_at

    def test_shadow_internal_fill_unchanged(self):
        # The #1017 executable internal-fill helper is untouched and still the
        # internal pricing path (shadow regression guard).
        src = inspect.getsource(pxe)
        assert "_select_internal_fill_price(" in src

    def test_entry_close_exemption_preserved(self):
        # The fix must NOT remove the entry-validation close-exemption.
        from packages.quantum import paper_endpoints
        ep_src = inspect.getsource(paper_endpoints)
        assert "(position_id set) is exempt" in ep_src
