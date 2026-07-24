"""P0-A — broker-acknowledged live-close invariant (F-A2-1 / E6 remediation).

A live-routed position may transition to filled/closed ONLY on a broker ack;
NO code path may internally fill a live-routed close. Every failure lands in an
explicit, alarmed, non-terminal state (unknown_reconciling), position OPEN.

Test split (honest): the guard's DECISION (`should_submit_to_broker`) is tested
behaviorally; `_close_position` is a ~700-line function not unit-testable in
isolation, so its four invariant seams are pinned as WIRING on the production
function (not an orphan). PR2 (client_order_id + reconciler auto-resolution)
adds the end-to-end path.
"""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

from packages.quantum.tests._alpaca_stub import ensure_alpaca as _ensure_alpaca

_ensure_alpaca()

_QUANTUM = Path(__file__).parent.parent


def _client(routing_mode):
    c = MagicMock()
    data = [] if routing_mode is None else [{"routing_mode": routing_mode}]
    (c.table.return_value.select.return_value.eq.return_value
     .limit.return_value.execute.return_value) = MagicMock(data=data)
    return c


class TestGuardDecision:
    """The internal-fill guard fires iff should_submit_to_broker is True.
    internal-fill-allowed == NOT should_submit_to_broker."""

    def test_live_eligible_is_live_close(self):
        from packages.quantum.brokers.execution_router import should_submit_to_broker
        assert should_submit_to_broker("pid", _client("live_eligible")) is True

    def test_shadow_only_is_not_live(self):
        from packages.quantum.brokers.execution_router import should_submit_to_broker
        # shadow_only → guard does NOT fire → internal fill allowed (correct).
        assert should_submit_to_broker("pid", _client("shadow_only")) is False

    def test_missing_portfolio_is_not_live(self):
        from packages.quantum.brokers.execution_router import should_submit_to_broker
        assert should_submit_to_broker("pid", _client(None)) is False


class TestClosePathWiring:
    """Pins the four invariant seams on the PRODUCTION _close_position /
    monitor code (not orphans)."""

    def _pe(self):
        return (_QUANTUM / "services" / "paper_exit_evaluator.py").read_text(encoding="utf-8")

    def _mon(self):
        return (_QUANTUM / "jobs" / "handlers" / "intraday_risk_monitor.py").read_text(encoding="utf-8")

    def test_structural_guard_before_internal_fill(self):
        src = self._pe()
        # the guard checks should_submit_to_broker and returns unknown_reconciling
        assert "STRUCTURAL INVARIANT GUARD (P0-A" in src
        assert "_p0a_is_live_close = _p0a_should_submit(" in src
        assert '"routed_to": "unknown_reconciling"' in src
        # fail-closed on a routing exception
        assert "_p0a_is_live_close = True  # fail-closed" in src
        # the guard sits BEFORE the internal-fill block
        gi = src.index("STRUCTURAL INVARIANT GUARD (P0-A")
        fi = src.index("--- Internal fill (internal_paper or Alpaca fallback) ---")
        assert gi < fi, "guard must precede the internal-fill block"

    def test_submit_exception_returns_reconciling_not_fallthrough(self):
        src = self._pe()
        # the dangerous fall-through language is GONE
        assert "Falling back to internal fill." not in src
        assert "falling back to internal fill" not in src
        assert "Fall through to internal fill below" not in src
        # replaced by force_close_failed + a hard return
        assert 'alert_type="force_close_failed"' in src

    def test_routing_query_failure_fails_closed(self):
        src = self._pe()
        # P0-A change C: unknown routing → treat as live (position_is_alpaca True)
        assert "P0-A FAIL-CLOSED" in src
        assert "position_is_alpaca = True" in src

    def test_monitor_treats_reconciling_as_not_closed(self):
        # PR-①b (2026-07-12): the inline routed_to tuple was extracted into the
        # testable _close_completed() seam — assert the BEHAVIOR, not the source
        # string (the #1126 costume this file otherwise risks). deferred /
        # unknown_reconciling / needs_manual_review are NOT completed closes → no
        # force_close count; a real alpaca route IS.
        from packages.quantum.jobs.handlers.intraday_risk_monitor import _close_completed
        assert _close_completed({"routed_to": "unknown_reconciling"}) is False
        assert _close_completed({"routed_to": "deferred_uncorroborated"}) is False
        assert _close_completed({"routed_to": "needs_manual_review"}) is False  # PR-①b
        assert _close_completed({"routed_to": "alpaca"}) is True
        # the surrounding fail-loud comment remains
        assert "success-costume" in self._mon()
